"""whisperflow-local — lokaler, privater Diktat-Assistent (Wispr-Flow-Klon).

Pipeline: Hotkey (halten ODER Umschalt-Modus) -> Mic -> faster-whisper (GPU, bei langen Reden schon
waehrend der Aufnahme abschnittsweise) -> Alias-Korrektur -> lokales LLM-Cleanup (gestueckelt)
-> Alias-Korrektur -> Zwischenablage, und im Hybrid-Modus zusaetzlich Einfuegen, wenn das Textfeld,
in dem diktiert wurde, noch den Fokus hat. Nichts verlaesst das LAN.

Aufruf:
    py whisperflow.py                     # startet die Tray-App
    py whisperflow.py --calibrate         # Kalibrierung: Begriffe vorlesen, Hoer-Fehler als Alias uebernehmen
    py whisperflow.py --list-devices      # Mikrofone auflisten
    py whisperflow.py --transcribe-file X.wav   # Datei durch STT+Cleanup (Test, kein Inject)
    py whisperflow.py --clean-text "..."  # nur Cleanup-Stufe testen
    py whisperflow.py --selftest          # deterministische Selbsttests (Inject-Roundtrip etc.)
    py whisperflow.py --no-tray           # ohne Tray (Konsole)
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import numpy as np

from wf import aliases as aliases_mod
from wf import audio as audio_mod
from wf import cleanup as cleanup_mod
from wf import config as config_mod
from wf import context as context_mod
from wf import focus as focus_mod
from wf import inject as inject_mod
from wf import overlay as overlay_mod
from wf import stt as stt_mod
from wf.hotkey import HoldToTalk

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "state.json"


def _beep(kind: str = "ok") -> None:
    """Kurzer Ton: ok (hoch) / pasted (zwei kurze hoch) / start (kurz mittel) / error (tief)."""
    try:
        import winsound
        if kind == "pasted":
            winsound.Beep(1200, 60); winsound.Beep(1500, 60)
        elif kind == "error":
            winsound.Beep(400, 90)
        elif kind == "start":
            winsound.Beep(900, 50)
        elif kind == "stop":
            winsound.Beep(700, 50)
        else:
            winsound.Beep(1200, 90)
    except Exception:  # noqa: BLE001
        pass


def _preview(text: str, n: int = 90) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[state] not saved: {e}")


class Pipeline:
    """Haelt die residenten Modelle + faehrt eine Diktat-Runde."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        base_terms = config_mod.load_dictionary(cfg)
        first_names, full_names = config_mod.load_employee_names(cfg)
        # Whisper-Seed: Begriffe + Vornamen (Reihenfolge = Prioritaet, stt.py kuerzt aufs Token-Budget)
        self.dictionary = base_terms + [n for n in first_names if n not in base_terms]
        # LLM-Woerterbuch darf laenger sein: zusaetzlich volle Namen
        self.llm_dictionary = self.dictionary + [n for n in full_names if n not in self.dictionary]
        self.aliases = aliases_mod.AliasFixer(aliases_mod.load_aliases(config_mod.load_aliases_path(cfg)))
        seed = config_mod.dictionary_prompt_seed(self.dictionary)
        self.transcriber = stt_mod.Transcriber(cfg, initial_prompt=seed)
        self.cleaner = cleanup_mod.Cleaner(cfg, self.llm_dictionary)
        self._inj = cfg.get("inject", {}) or {}
        self._ui = cfg.get("ui", {}) or {}
        self.method = str(self._inj.get("method", "hybrid"))
        self.tray = None  # optional, gesetzt von der Tray-App
        self.overlay = overlay_mod.Overlay(enabled=bool(self._ui.get("cursor_badge", True)))
        # Whisper/CTranslate2 ist nicht fuer parallele transcribe()-Aufrufe gebaut:
        # mehrere Diktate/Abschnitte hintereinander werden hier in Reihenfolge abgearbeitet.
        self._lock = threading.Lock()
        hist = self._ui.get("history_file")
        self.history_path = (ROOT / hist) if hist else None
        print(f"[pipeline] dictionary: {len(base_terms)} terms + {len(first_names)} names from the list, "
              f"{len(self.aliases)} Alias-Regeln")

    def warmup(self) -> dict:
        """STT-Modell laden + Dummy-Inferenz; LLM-Ping laeuft parallel dazu (spart ~1-2 s Start)."""
        t0 = time.time()
        llm_result: dict = {}

        def _llm():
            llm_result["ok"] = self.cleaner.warmup()

        th = threading.Thread(target=_llm, daemon=True)
        th.start()
        self.transcriber.warmup()
        focus_mod.warmup()
        th.join(timeout=max(5, self.cleaner.timeout))
        self._prune_history()
        return {"warmup_s": round(time.time() - t0, 1), "llm_reachable": bool(llm_result.get("ok"))}

    # ---- STT ----

    def transcribe(self, arr: np.ndarray) -> str:
        """Ein Abschnitt -> Rohtext (serialisiert ueber das Modell-Lock)."""
        with self._lock:
            return self.transcriber.transcribe(arr)["text"].strip()

    def clean_text(self, raw: str, category: str) -> tuple[str, list[str]]:
        """Aliases -> LLM-Cleanup -> Aliases fuer einen Abschnitt."""
        raw_fixed, a1 = self.aliases.fix(raw)
        cleaned, _ = self.cleaner.clean(raw_fixed, category)
        cleaned, a2 = self.aliases.fix(cleaned)
        return cleaned, a1 + a2

    # ---- Volle Runde ----

    def process_audio(self, arr: np.ndarray, do_inject: bool = True, ctx: dict | None = None,
                      is_cancelled: Callable[[], bool] | None = None,
                      prefix_cleaned: str = "") -> dict:
        """Voller Weg: STT -> Aliases -> Cleanup -> Aliases -> (Zwischenablage/Einfuegen). Gibt Diagnose zurueck.
        prefix_cleaned = schon waehrend der Aufnahme fertig bereinigte Abschnitte (lange Reden), kommen vor arr.
        is_cancelled() = True, wenn inzwischen ein neues Diktat begonnen hat -> Ergebnis wird verworfen."""
        result: dict = {}
        cancelled = is_cancelled or (lambda: False)
        t0 = time.time()
        if cancelled():
            result["note"] = "verworfen (neue Aufnahme vor STT)"
            return result
        self.overlay.phase("höre zu")
        tail = self.transcribe(arr) if arr is not None and len(arr) else ""
        result["raw"] = tail
        result["language"] = self.transcriber.language or "auto"
        result["stt_s"] = round(time.time() - t0, 2)
        if not tail and not prefix_cleaned:
            result["cleaned"] = ""
            result["note"] = "leeres Transkript"
            return result
        if cancelled():
            result["note"] = "verworfen (neue Aufnahme nach STT)"
            return result

        ctx = ctx or context_mod.foreground_info(self.cfg)
        result["category"] = ctx["category"]
        result["process"] = ctx["process"]

        t1 = time.time()
        applied: list[str] = []
        was_cleaned = False
        cleaned_tail = ""
        if tail:
            self.overlay.phase("räume auf", eta_left_s=0.4 + len(tail.split()) * 0.03)
            raw_fixed, a1 = self.aliases.fix(tail)
            cleaned_tail, was_cleaned = self.cleaner.clean(raw_fixed, ctx["category"])
            cleaned_tail, a2 = self.aliases.fix(cleaned_tail)
            applied = a1 + a2
        cleaned = (prefix_cleaned + " " + cleaned_tail).strip() if prefix_cleaned else cleaned_tail
        result["aliases"] = applied
        result["cleaned"] = cleaned
        result["was_cleaned"] = was_cleaned or bool(prefix_cleaned)
        result["cleanup_s"] = round(time.time() - t1, 2)
        if cancelled():
            result["note"] = "verworfen (neue Aufnahme nach Cleanup)"
            return result

        if do_inject and cleaned:
            self._remember(cleaned)
            result["delivered"] = self._deliver(cleaned, ctx)
        result["total_s"] = round(time.time() - t0, 2)
        return result

    # ---- Verlauf ----

    def _remember(self, text: str) -> None:
        if not self.history_path:
            return
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with self.history_path.open("a", encoding="utf-8") as fh:
                fh.write(f"### {datetime.now().isoformat(timespec='seconds')}\n{text}\n\n")
        except Exception as e:  # noqa: BLE001
            print(f"[history] not written: {e}")

    def last_text(self) -> str:
        if not self.history_path or not self.history_path.exists():
            return ""
        blocks = self.history_path.read_text(encoding="utf-8").split("### ")
        for b in reversed(blocks):
            if "\n" in b:
                return b.split("\n", 1)[1].strip()
        return ""

    def _prune_history(self) -> None:
        """Eintraege aelter als history_keep_days entfernen (Datei bleibt klein und privat)."""
        days = int(self._ui.get("history_keep_days", 14) or 0)
        if not self.history_path or not self.history_path.exists() or days <= 0:
            return
        cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        blocks = [b for b in self.history_path.read_text(encoding="utf-8").split("### ") if b.strip()]
        keep = [b for b in blocks if b[:19] >= cutoff]
        if len(keep) != len(blocks):
            self.history_path.write_text("".join("### " + b for b in keep), encoding="utf-8")

    # ---- Ausgabe ----

    def _deliver(self, text: str, ctx: dict) -> str:
        """Rueckgabe: 'pasted' | 'clipboard' | 'failed'."""
        if self.method == "hybrid":
            return self._deliver_hybrid(text, ctx)
        if self.method == "clipboard_only":
            return "clipboard" if self._to_clipboard_and_notify(text) else "failed"
        # Auto-Paste-Modi (clipboard / sendinput): UIPI: Admin-Fenster schluckt Injektion still (R1)
        if self._ui.get("notify_on_blocked_window", True) and context_mod.is_foreground_elevated():
            msg = "Zielfenster laeuft als Admin, Text NICHT eingefuegt. Fenster ohne Admin nutzen."
            print(f"[inject] {msg}")
            if self.tray:
                self.tray.notify(msg)
            return "failed"
        method = ctx.get("method_override") or self.method
        delay = int(self._inj.get("restore_clipboard_delay_ms", 120))
        return "pasted" if inject_mod.inject(text, method=method, restore_delay_ms=delay) else "failed"

    def _deliver_hybrid(self, text: str, ctx: dict) -> str:
        """Text kommt IMMER in die Zwischenablage. Zusaetzlich Strg+V, wenn (a) beim Loslassen ein
        beschreibbares Textfeld den Fokus hatte, (b) dasselbe Fenster jetzt noch vorne ist und
        (c) jetzt immer noch ein Textfeld den Fokus hat. Sonst nur Zwischenablage + Ton."""
        ok = inject_mod.to_clipboard(text)
        if not ok:
            _beep("error")
            print(f"[deliver] NOT placed on clipboard: {text!r}")
            if self.tray:
                self.tray.notify("Clipboard not writable. The text is in the history file (data/history.log).")
            return "failed"
        why = ""
        if not ctx.get("editable"):
            why = f"beim Stoppen kein Textfeld ({ctx.get('focus_why', '?')})"
        else:
            now = context_mod.foreground_info(self.cfg)
            if now.get("hwnd") != ctx.get("hwnd"):
                why = f"Fenster gewechselt ({ctx.get('process')} -> {now.get('process')})"
            elif context_mod.is_foreground_elevated():
                why = "Zielfenster laeuft als Admin"
            else:
                f = focus_mod.editable_focus()
                if not f["editable"]:
                    why = f"jetzt kein Textfeld ({f['why']})"
        if why:
            print(f"[deliver] clipboard only: {why}")
            self.overlay.done("Strg+V bereit")
            if self._ui.get("beep_on_ready", True):
                _beep("ok")
            if self._ui.get("notify_on_ready", True) and self.tray:
                self.tray.notify(_preview(text), title="Ready - press Ctrl+V")
            return "clipboard"
        inject_mod.paste_ctrl_v()
        self.overlay.done("Eingefügt")
        if self._ui.get("beep_on_ready", True):
            _beep("pasted")
        print("[deliver] pasted (text field had focus); the text also stays on the clipboard")
        return "pasted"

    def _to_clipboard_and_notify(self, text: str) -> bool:
        ok = inject_mod.to_clipboard(text)
        if ok:
            self.overlay.done("Strg+V bereit")
            if self._ui.get("beep_on_ready", True):
                _beep("ok")
            if self._ui.get("notify_on_ready", True) and self.tray:
                self.tray.notify(_preview(text), title="Ready - press Ctrl+V")
        else:
            self.overlay.error("Zwischenablage gesperrt")
            _beep("error")
            if self.tray:
                self.tray.notify("Clipboard not writable. The text is in the history file (data/history.log).")
            print(f"[deliver] NOT placed on clipboard: {text!r}")
        return ok


class App:
    """Tray-App. Zwei Hotkey-Arten: halten (hold) oder Umschalten (toggle: einmal = an, nochmal = aus).
    Verarbeitung laeuft im Worker-Thread. Waehrend einer langen Aufnahme werden fertige Abschnitte
    (an Sprechpausen geschnitten) schon transkribiert. Ein NEUES Diktat verwirft ein noch laufendes,
    wenn das alte kurz war (discard_only_if_shorter_than_s)."""

    def __init__(self, cfg: dict, use_tray: bool = True):
        self.cfg = cfg
        self.pipeline = Pipeline(cfg)
        self.use_tray = use_tray
        self.tray = None
        self._enabled = True
        audio_cfg = cfg.get("audio", {}) or {}
        self._recorder = audio_mod.Recorder(
            samplerate=audio_cfg.get("samplerate", 16000),
            channels=audio_cfg.get("channels", 1),
            device=audio_cfg.get("input_device"),
            max_seconds=audio_cfg.get("max_seconds", 3600),
        )
        self.chunk_seconds = float(audio_cfg.get("chunk_seconds", 25))
        self.chunk_silence_s = float(audio_cfg.get("chunk_silence_s", 0.45))
        self._stop = threading.Event()
        self._busy = 0                 # laufende Verarbeitungen (fuer den Tray-Status)
        self._busy_lock = threading.Lock()
        self._generation = 0           # zaehlt Aufnahmen; ein Job gilt nur, solange er der neueste ist
        self._pending: dict[int, float] = {}   # generation -> Aufnahmedauer (fuer die Verwerf-Schwelle)
        ui = cfg.get("ui", {}) or {}
        self.discard_on_new = bool(ui.get("discard_pending_on_new_recording", True))
        self.discard_max_s = float(ui.get("discard_only_if_shorter_than_s", 30))
        state = _load_state()
        self.toggle_mode = bool(state.get("toggle_mode", (cfg.get("hotkey", {}) or {}).get("mode", "hold") == "toggle"))
        # Streaming-Abschnitte der laufenden Aufnahme
        self._parts: list[str] = []
        self._parts_lock = threading.Lock()
        self._rec_start = 0.0
        self._streamer: threading.Thread | None = None

    # --- Hotkey callbacks (muessen schnell zurueckkehren) ---
    def _on_press(self) -> None:
        if not self._enabled:
            return
        if self.toggle_mode:
            if self._recorder.is_recording:
                self._stop_recording()
            else:
                self._start_recording()
            return
        self._start_recording()

    def _on_release(self) -> None:
        if self.toggle_mode:
            return  # im Umschalt-Modus zaehlt nur das Druecken
        self._stop_recording()

    def _start_recording(self) -> None:
        if self._recorder.is_recording:
            return
        self._generation += 1
        with self._parts_lock:
            self._parts = []
        self._rec_start = time.time()
        self._rec_category = context_mod.foreground_info(self.cfg).get("category", "default")
        self._recorder.start()
        self.pipeline.overlay.recording()
        if self.toggle_mode:
            _beep("start")
        if self.tray:
            self.tray.set_state("recording")
        self._streamer = threading.Thread(target=self._stream_loop, args=(self._generation,), daemon=True)
        self._streamer.start()

    def _stream_loop(self, gen: int) -> None:
        """Waehrend der Aufnahme: fertige Abschnitte (an Sprechpausen) schon transkribieren."""
        limit_warned = False
        while self._recorder.is_recording and gen == self._generation:
            if self._recorder.limit_hit and not limit_warned:
                limit_warned = True
                _beep("error")
                if self.tray:
                    self.tray.notify("Recording limit reached, finishing the recording now.")
                self._stop_recording()
                break
            chunk = self._recorder.drain_until_silence(self.chunk_seconds, self.chunk_silence_s)
            if chunk is None:
                if self.tray and self.toggle_mode:
                    self.tray.set_state("recording", f"{int(self._recorder.elapsed_seconds)} s")
                time.sleep(0.5)
                continue
            try:
                t = time.time()
                text = self.pipeline.transcribe(chunk)
                cleaned, _ = self.pipeline.clean_text(text, self._rec_category) if text else ("", [])
            except Exception as e:  # noqa: BLE001
                print(f"[stream] chunk error: {e}")
                continue
            if cleaned and gen == self._generation:
                with self._parts_lock:
                    self._parts.append(cleaned)
                print(f"[stream] #{gen} chunk {len(self._parts)} ({len(chunk)/self._recorder.samplerate:.0f} s audio, "
                      f"{time.time()-t:.1f} s compute): {_preview(cleaned, 60)!r}")

    def _stop_recording(self) -> None:
        if not self._recorder.is_recording:
            return
        arr = self._recorder.stop()
        gen = self._generation
        duration = time.time() - self._rec_start
        self._pending[gen] = duration
        if self.toggle_mode:
            _beep("stop")
        self.pipeline.overlay.processing(overlay_mod.estimate_seconds(len(arr) / self._recorder.samplerate))
        # Fenster + Fokus JETZT merken (beim Stoppen), nicht erst nach der Transkription
        ctx = context_mod.foreground_info(self.cfg)
        if self.pipeline.method == "hybrid":
            f = focus_mod.editable_focus()
            ctx["editable"] = f["editable"]
            ctx["focus_why"] = f["why"]
        with self._busy_lock:
            self._busy += 1
        if self.tray:
            self.tray.set_state("processing")
        threading.Thread(target=self._process, args=(arr, ctx, gen), daemon=True).start()

    def _is_cancelled(self, gen: int) -> bool:
        if not self.discard_on_new or gen == self._generation:
            return False
        return self._pending.get(gen, 0.0) < self.discard_max_s

    def _process(self, arr: np.ndarray, ctx: dict, gen: int) -> None:
        try:
            # auf den Streamer dieser Aufnahme warten (er beendet sich, sobald der Recorder aus ist)
            st = self._streamer
            if st and st.is_alive():
                st.join(timeout=120)
            with self._parts_lock:
                prefix = " ".join(self._parts) if gen == self._generation or self._pending.get(gen, 0) >= self.discard_max_s else ""
            res = self.pipeline.process_audio(arr, do_inject=True, ctx=ctx,
                                              is_cancelled=lambda: self._is_cancelled(gen),
                                              prefix_cleaned=prefix)
            if res.get("note", "").startswith("verworfen"):
                print(f"[dictation] #{gen} {res['note']}")
                self.pipeline.overlay.hide()
            elif res.get("note") == "leeres Transkript":
                self.pipeline.overlay.error("nichts verstanden", 1.5)
            else:
                al = f" aliases={res['aliases']}" if res.get("aliases") else ""
                print(f"[dictation] #{gen} ({self._pending.get(gen, 0):.0f} s recorded) stt {res.get('stt_s','?')}s + cleanup "
                      f"{res.get('cleanup_s','?')}s = {res.get('total_s','?')}s {res.get('delivered','-')}{al} "
                      f"-> {_preview(res.get('cleaned',''), 120)!r}")
        except Exception as e:  # noqa: BLE001
            print(f"[dictation] error: {e}")
            self.pipeline.overlay.error("Fehler, siehe Konsole")
            _beep("error")
            if self.tray:
                self.tray.notify(f"Error: {e}")
        finally:
            self._pending.pop(gen, None)
            with self._busy_lock:
                self._busy = max(0, self._busy - 1)
                still_busy = self._busy > 0
            if self.tray and not self._recorder.is_recording:
                if still_busy:
                    self.tray.set_state("processing")
                else:
                    self.tray.set_state("idle" if self._enabled else "disabled")

    # --- Tray ---
    def _toggle(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled and self._recorder.is_recording:
            self._stop_recording()
        print(f"[app] {'enabled' if enabled else 'disabled'}")

    def _set_toggle_mode(self, on: bool) -> None:
        self.toggle_mode = on
        state = _load_state(); state["toggle_mode"] = on; _save_state(state)
        print(f"[app] toggle mode {'ON (press once = record, again = stop)' if on else 'OFF (hold the key)'}")

    def _copy_last(self) -> None:
        t = self.pipeline.last_text()
        if t and inject_mod.to_clipboard(t):
            _beep("ok")
            if self.tray:
                self.tray.notify(_preview(t), title="Last text copied to clipboard")
        elif self.tray:
            self.tray.notify("No text in the history.")

    def _quit(self) -> None:
        self._stop.set()

    def run(self) -> None:
        print("[app] warming up ...")
        self.pipeline.overlay.start()
        w = self.pipeline.warmup()
        print(f"[app] warm-up done in {w['warmup_s']}s. LLM reachable: {w['llm_reachable']}")
        if not w["llm_reachable"]:
            print("[app] WARN: clean-up LLM not reachable -> raw transcript is delivered until Ollama runs.")

        key = self.cfg.get("hotkey", {}).get("key", "ctrl_r")
        hk = HoldToTalk(key, self._on_press, self._on_release)
        hk.start()
        mode = self.pipeline.method
        hint = {"hybrid": "focused text field -> pasted directly, otherwise clipboard (Ctrl+V).",
                "clipboard_only": "text goes to the clipboard (Ctrl+V).",
                }.get(mode, f"pastes the text at the cursor ({mode}).")
        how = "press once = on, again = off (toggle mode)" if self.toggle_mode else "hold to talk"
        print(f"[app] ready. '{key}' {how}. Then -> {hint}")

        self.pipeline.tray = None
        if self.use_tray:
            from wf.tray import Tray
            self.tray = Tray(self._toggle, self._quit, on_toggle_mode=self._set_toggle_mode,
                             on_copy_last=self._copy_last, toggle_mode=self.toggle_mode)
            self.pipeline.tray = self.tray
            self.tray.set_state("idle")
            # pystray.run() blockiert im Main-Thread; Hotkey-Listener laeuft eh separat
            self.tray.run()
            hk.stop()
        else:
            try:
                while not self._stop.is_set():
                    time.sleep(0.2)
            except KeyboardInterrupt:
                pass
            hk.stop()
        print("[app] stopped.")


# ---------------- CLI ----------------

def cmd_transcribe_file(cfg: dict, path: str) -> int:
    """Datei -> STT -> Cleanup (kein Inject). Beweist Kriterium 2 + 3 ohne Mikro."""
    p = Path(path)
    if not p.is_file():
        print(f"File not found: {p}")
        return 2
    pipe = Pipeline(cfg)
    pipe.warmup()
    arr = _load_wav_16k_mono(p)
    res = pipe.process_audio(arr, do_inject=False)
    print("\n=== TRANSCRIBE-FILE ===")
    print(f"File:     {p.name}  ({len(arr)/16000:.0f} s)")
    print(f"Language: {res.get('language')}")
    print(f"STT:      {res.get('stt_s')}s  Cleanup: {res.get('cleanup_s')}s")
    print(f"RAW:      {res.get('raw','')!r}")
    print(f"CLEANED:  {res.get('cleaned','')!r}")
    print(f"cleaned:  {res.get('was_cleaned')}  aliases: {res.get('aliases')}")
    return 0


def _load_wav_16k_mono(p: Path) -> np.ndarray:
    """WAV/M4A/MP4 -> float32 mono 16k. Nutzt ffmpeg (vorhanden) fuer robustes Decoding."""
    import subprocess
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(p), "-ac", "1", "-ar", "16000",
           "-f", "f32le", "-"]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32).copy()


def cmd_clean_text(cfg: dict, text: str) -> int:
    pipe = Pipeline(cfg)
    ok = pipe.cleaner.warmup()
    if not ok:
        print("LLM not reachable (is Ollama running?) -> testing anyway, expect the raw-text fallback.")
    cleaned, was = pipe.cleaner.clean(text, "default")
    cleaned, applied = pipe.aliases.fix(cleaned)
    print(f"RAW:      {text!r}")
    print(f"CLEANED:  {cleaned!r}")
    print(f"cleaned:  {was}  aliases: {applied}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="whisperflow-local")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--transcribe-file", metavar="WAV")
    ap.add_argument("--clean-text", metavar="TEXT")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--calibrate", action="store_true", help="Begriffe vorlesen, Hoer-Fehler als Alias uebernehmen")
    ap.add_argument("--no-tray", action="store_true")
    args = ap.parse_args()

    if args.list_devices:
        print(audio_mod.list_devices())
        return 0
    if args.selftest:
        from selftest import run_selftests
        return run_selftests()

    cfg = config_mod.load_config()

    if args.transcribe_file:
        return cmd_transcribe_file(cfg, args.transcribe_file)
    if args.clean_text is not None:
        return cmd_clean_text(cfg, args.clean_text)
    if args.calibrate:
        from calibrate import run_calibration
        return run_calibration(cfg)

    App(cfg, use_tray=not args.no_tray).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
