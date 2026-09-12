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
from wf import i18n
from wf import inject as inject_mod
from wf import lang as lang_mod
from wf import overlay as overlay_mod
from wf import snip as snip_mod
from wf import stt as stt_mod
from wf.hotkey import HoldToTalk

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "state.json"


def _beep(kind: str = "ok") -> None:
    """Kurzer Ton: ok (hoch) / pasted (zwei kurze hoch) / start (kurz mittel) / error (tief).
    Laeuft im eigenen Thread: winsound.Beep blockiert so lange wie der Ton dauert, und beim
    Loslassen der Taste liegt dieser Weg vor dem Anzeigefeld (gemessen 13.09.2026: 68 ms statt
    1 ms, bis „Aufnahme aus" erschien)."""
    threading.Thread(target=_beep_sync, args=(kind,), daemon=True).start()


def _beep_sync(kind: str) -> None:
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
        base_terms, llm_only = config_mod.load_dictionary_tiers(cfg)
        first_names, full_names = config_mod.load_employee_names(cfg)
        # Whisper-Seed: Begriffe + Vornamen (Reihenfolge = Prioritaet, stt.py kuerzt aufs Token-Budget)
        self.dictionary = base_terms + [n for n in first_names if n not in base_terms]
        # LLM-Woerterbuch darf laenger sein: zusaetzlich volle Namen + die Nur-Cleanup-Begriffe
        self.llm_dictionary = self.dictionary + [n for n in full_names if n not in self.dictionary] \
            + [t for t in llm_only if t not in self.dictionary]
        self.aliases = aliases_mod.AliasFixer(aliases_mod.load_aliases(config_mod.load_aliases_path(cfg)))
        seed = config_mod.dictionary_prompt_seed(self.dictionary)
        self.transcriber = stt_mod.Transcriber(cfg, initial_prompt=seed)
        self.cleaner = cleanup_mod.Cleaner(cfg, self.llm_dictionary)
        self._inj = cfg.get("inject", {}) or {}
        self._ui = cfg.get("ui", {}) or {}
        self.method = str(self._inj.get("method", "hybrid"))
        self.tray = None  # optional, gesetzt von der Tray-App
        # Uebersetzungsmodus: "" = aus. Wird NICHT in state.json gemerkt (Entscheidung 08.09.2026) —
        # nach jedem Start diktiert er wieder normal in seiner Sprache.
        self.translate_to = ""
        self.last_language = ""   # Whispers Erkennung des letzten Abschnitts
        self.overlay = overlay_mod.Overlay(enabled=bool(self._ui.get("cursor_badge", True)))
        # Whisper/CTranslate2 ist nicht fuer parallele transcribe()-Aufrufe gebaut:
        # mehrere Diktate/Abschnitte hintereinander werden hier in Reihenfolge abgearbeitet.
        self._lock = threading.Lock()
        hist = self._ui.get("history_file")
        self.history_path = (ROOT / hist) if hist else None
        print(f"[pipeline] dictionary: {len(base_terms)} terms + {len(first_names)} names in the Whisper prompt, "
              f"+{len(llm_only)} clean-up only, {len(self.aliases)} alias rules")

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
        """Ein Abschnitt -> Rohtext (serialisiert ueber das Modell-Lock).
        Merkt sich Whispers erkannte Sprache in self.last_language — die bindet den Cleanup."""
        with self._lock:
            res = self.transcriber.transcribe(arr)
        self.last_language = str(res.get("language") or "")
        return res["text"].strip()

    def clean_text(self, raw: str, category: str) -> tuple[str, list[str]]:
        """Aliases -> LLM-Cleanup (in der gesprochenen Sprache) -> Aliases fuer einen Abschnitt."""
        raw_fixed, a1 = self.aliases.fix(raw)
        cleaned, _ = self.cleaner.clean(raw_fixed, category, self.last_language)
        cleaned, a2 = self.aliases.fix(cleaned)
        return cleaned, a1 + a2

    def maybe_translate(self, text: str) -> tuple[str, str]:
        """Uebersetzungsmodus: (text, hinweis). Aus -> unveraendert, leerer Hinweis."""
        target = (self.translate_to or "").strip()
        if not text or not target:
            return text, ""
        t0 = time.time()
        self.overlay.phase(i18n.t("badge_translating"))
        out, ok = self.cleaner.translate(text, target)
        if not ok:
            return text, i18n.t("note_translate_failed", lang=lang_mod.name_native(target))
        print("[translate] -> " + target + " in " + str(round(time.time() - t0, 1)) + "s")
        return out, ""

    # ---- Volle Runde ----

    def process_audio(self, arr: np.ndarray, do_inject: bool = True, ctx: dict | None = None,
                      is_cancelled: Callable[[], bool] | None = None,
                      prefix_cleaned: str | Callable[[], str] = "") -> dict:
        """Voller Weg: STT -> Aliases -> Cleanup -> Aliases -> (Zwischenablage/Einfuegen). Gibt Diagnose zurueck.
        prefix_cleaned = schon waehrend der Aufnahme fertig bereinigte Abschnitte (lange Reden), kommen vor arr.
          Darf eine Funktion sein: sie wird erst beim Zusammensetzen aufgerufen, damit die STT des Rests
          nicht auf den Streamer warten muss (12.09.2026).
        is_cancelled() = True, wenn inzwischen ein neues Diktat begonnen hat -> Ergebnis wird verworfen."""
        result: dict = {}
        cancelled = is_cancelled or (lambda: False)
        t0 = time.time()
        if cancelled():
            result["note"] = "verworfen (neue Aufnahme vor STT)"
            return result
        self.overlay.phase(i18n.t("badge_listening"))
        tail = self.transcribe(arr) if arr is not None and len(arr) else ""
        result["raw"] = tail
        # Whispers ERKANNTE Sprache (nicht die konfigurierte) — sie bindet Cleanup + Guard.
        result["language"] = self.last_language or self.transcriber.language or "auto"
        result["stt_s"] = round(time.time() - t0, 2)
        if not tail and callable(prefix_cleaned):
            prefix_cleaned = prefix_cleaned()      # ohne Rest sofort abholen (sonst gaebe es nichts zu tun)
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
            self.overlay.phase(i18n.t("badge_cleaning"), eta_left_s=0.4 + len(tail.split()) * 0.03)
            raw_fixed, a1 = self.aliases.fix(tail)
            cleaned_tail, was_cleaned = self.cleaner.clean(raw_fixed, ctx["category"], self.last_language)
            cleaned_tail, a2 = self.aliases.fix(cleaned_tail)
            applied = a1 + a2
        if callable(prefix_cleaned):
            prefix_cleaned = prefix_cleaned()      # jetzt erst: Streamer-Abschnitte einsammeln
        cleaned = (prefix_cleaned + " " + cleaned_tail).strip() if prefix_cleaned else cleaned_tail
        # Uebersetzungsmodus zuletzt und auf dem GESAMTtext (nicht pro Abschnitt) — sonst
        # uebersetzt jedes Stueck fuer sich und der Zusammenhang geht verloren.
        if cleaned and self.translate_to:
            cleaned, hinweis = self.maybe_translate(cleaned)
            result["translated_to"] = self.translate_to
            if hinweis:
                result["note_translate"] = hinweis
                if self.tray:
                    self.tray.notify(hinweis)
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

    # ---- Anhaengen (Entscheidung 08.09.2026) ----
    # Kommt kurz nach einem Diktat, das NUR in der Zwischenablage landete (nicht eingefuegt), ein
    # weiteres, wird es angehaengt: Zwischenablage = alter Text + neuer Text. Ein Strg+V bringt dann
    # beides. Bedingungen (alle): letzte Lieferung war 'clipboard', hoechstens append_within_s her,
    # und die Zwischenablage traegt noch genau unseren letzten Text (sonst hat er inzwischen etwas
    # anderes kopiert — dann kein Anhaengen). Wurde der letzte Text automatisch EINGEFUEGT, wird nie
    # angehaengt: der Cursor steht ohnehin hinter dem Text, ein weiteres Diktat setzt dort fort.
    # Bekannte Grenze: hat er den alten Text selbst schon mit Strg+V eingefuegt UND diktiert innerhalb
    # des Fensters weiter, steht der alte Text nach dem naechsten Strg+V doppelt da. Deshalb Fenster
    # kurz halten (ui.append_within_s) oder 0 = aus.

    @staticmethod
    def append_decision(last: dict | None, now_ts: float, clipboard_now: str | None, window_s: float) -> bool:
        if not last or window_s <= 0:
            return False
        if last.get("mode") != "clipboard":
            return False
        if now_ts - float(last.get("ts", 0)) > window_s:
            return False
        return clipboard_now is not None and clipboard_now == last.get("text")

    def _maybe_append(self, text: str) -> tuple[str, bool]:
        window = float(self._ui.get("append_within_s", 0) or 0)
        last = getattr(self, "_last_delivery", None)
        try:
            clip_now, _ = inject_mod._clip_get()
        except Exception:  # noqa: BLE001
            clip_now = None
        if self.append_decision(last, time.time(), clip_now, window):
            return (last["text"].rstrip() + " " + text.lstrip()), True
        return text, False

    def _note_delivery(self, text: str, mode: str) -> None:
        self._last_delivery = {"text": text, "mode": mode, "ts": time.time()}

    def _deliver(self, text: str, ctx: dict) -> str:
        """Rueckgabe: 'pasted' | 'clipboard' | 'failed'."""
        text, appended = self._maybe_append(text)
        if appended:
            print("[deliver] appended to the previous dictation (the clipboard holds both)")
        if self.method == "hybrid":
            mode = self._deliver_hybrid(text, ctx, appended=appended)
            if mode != "failed":
                self._note_delivery(text, mode)
            return mode
        if self.method == "clipboard_only":
            ok = self._to_clipboard_and_notify(text, appended=appended)
            if ok:
                self._note_delivery(text, "clipboard")
            return "clipboard" if ok else "failed"
        # Auto-Paste-Modi (clipboard / sendinput): UIPI: Admin-Fenster schluckt Injektion still (R1)
        if self._ui.get("notify_on_blocked_window", True) and context_mod.is_foreground_elevated():
            msg = i18n.t("note_admin_window")
            print(f"[inject] {msg}")
            if self.tray:
                self.tray.notify(msg)
            return "failed"
        method = ctx.get("method_override") or self.method
        delay = int(self._inj.get("restore_clipboard_delay_ms", 120))
        return "pasted" if inject_mod.inject(text, method=method, restore_delay_ms=delay) else "failed"

    def _deliver_hybrid(self, text: str, ctx: dict, appended: bool = False) -> str:
        """Text kommt IMMER in die Zwischenablage. Zusaetzlich Strg+V, wenn (a) beim Loslassen ein
        beschreibbares Textfeld den Fokus hatte, (b) dasselbe Fenster jetzt noch vorne ist und
        (c) jetzt immer noch ein Textfeld den Fokus hat. Sonst nur Zwischenablage + Ton."""
        ok = inject_mod.to_clipboard(text)
        if not ok:
            _beep("error")
            print(f"[deliver] NOT placed on clipboard: {text!r}")
            if self.tray:
                self.tray.notify(i18n.t("note_clipboard_failed", file=(self.history_path.name if self.history_path else "?")))
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
            label = i18n.t("badge_ready_appended") if appended else i18n.t("badge_ready")
            self.overlay.done(label)
            if self._ui.get("beep_on_ready", True):
                _beep("ok")
            if self._ui.get("notify_on_ready", True) and self.tray:
                self.tray.notify(_preview(text), title=label)
            return "clipboard"
        inject_mod.paste_ctrl_v()
        self.overlay.done(i18n.t("badge_pasted"))
        if self._ui.get("beep_on_ready", True):
            _beep("pasted")
        print("[deliver] pasted (text field had focus); the text also stays on the clipboard")
        return "pasted"

    def _to_clipboard_and_notify(self, text: str, appended: bool = False) -> bool:
        ok = inject_mod.to_clipboard(text)
        if ok:
            label = i18n.t("badge_ready_appended") if appended else i18n.t("badge_ready")
            self.overlay.done(label)
            if self._ui.get("beep_on_ready", True):
                _beep("ok")
            if self._ui.get("notify_on_ready", True) and self.tray:
                self.tray.notify(_preview(text), title=label)
        else:
            self.overlay.error(i18n.t("badge_clipboard_locked"))
            _beep("error")
            if self.tray:
                self.tray.notify(i18n.t("note_clipboard_failed", file=(self.history_path.name if self.history_path else "?")))
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
            persistent=bool(audio_cfg.get("persistent_stream", True)),
            preroll_s=float(audio_cfg.get("preroll_s", 0.6)),
        )
        self.chunk_seconds = float(audio_cfg.get("chunk_seconds", 25))
        self.chunk_silence_s = float(audio_cfg.get("chunk_silence_s", 0.45))
        self._stop = threading.Event()
        self._busy = 0                 # laufende Verarbeitungen (fuer den Tray-Status)
        self._busy_lock = threading.Lock()
        self._generation = 0           # zaehlt Aufnahmen; ein Job gilt nur, solange er der neueste ist
        self._pending: dict[int, float] = {}   # generation -> Aufnahmedauer (fuer die Verwerf-Schwelle)
        ui = cfg.get("ui", {}) or {}
        self.beep_on_stop = bool(ui.get("beep_on_stop", True))
        self.discard_on_new = bool(ui.get("discard_pending_on_new_recording", True))
        self.discard_max_s = float(ui.get("discard_only_if_shorter_than_s", 0))
        state = _load_state()
        # Oberflaechensprache (09.09.2026): config.yaml (ui.language) ist die Vorgabe, die
        # Tray-Wahl in state.json sticht sie. "auto" = Windows-Anzeigesprache, damit das
        # Werkzeug bei jedem sofort in seiner Sprache laeuft.
        self.ui_language = str(state.get("ui_lang") or ui.get("language") or "auto")
        i18n.set_language(i18n.resolve(self.ui_language))
        self.toggle_mode = bool(state.get("toggle_mode", (cfg.get("hotkey", {}) or {}).get("mode", "hold") == "toggle"))
        # Bildausschnitt (10.09.2026): eigene Taste, eigener Ordner, eigene Aufbewahrung
        sn = cfg.get("snip", {}) or {}
        self.snip_enabled = bool(sn.get("enabled", True))
        self.snip_key = str(sn.get("key", "shift_r"))
        self.snip_mode = str(sn.get("mode", "tap"))
        self.snip_hold_ms = int(sn.get("hold_ms", 450))
        self.snip_double = bool(sn.get("fullscreen_on_double", False))
        self.snip_double_ms = int(sn.get("double_tap_ms", 400))
        self.snip_full_scope = str(sn.get("fullscreen_scope", "monitor"))
        self.snip_suppress = bool(sn.get("suppress", True))
        self.snip_keep_days = int(sn.get("keep_days", 14))
        self.snip_beep = bool(sn.get("beep", True))
        self.snip_folder = Path(sn.get("folder", "data/bilder"))
        if not self.snip_folder.is_absolute():
            self.snip_folder = Path(__file__).resolve().parent / self.snip_folder
        self._snip_watcher = None
        self._snip_lock = threading.Lock()   # ein Ausschnitt zur Zeit
        snip_mod.set_hint(i18n.t("snip_hint"))
        # Streaming-Abschnitte der laufenden Aufnahme
        self._parts: list[str] = []
        self._parts_lock = threading.Lock()
        self._rec_start = 0.0
        self._streamer: threading.Thread | None = None
        self._inflight_s = 0.0         # Audio-Sekunden des Abschnitts, den der Streamer gerade rechnet
        self._hk = None                # Hotkey (fuer die Messung Taste -> Stopp)
        self._timing: dict = {}        # Zeitmarken der letzten Aufnahme (Ausgabe als [timing]-Zeile)

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
        # Anzeige erst, wenn wirklich Audio ankommt („damit man weiß, jetzt ist die
        # Aufnahme 100 % da“). Mit offenem Stream ist das sofort; muss der Stream erst geoeffnet werden,
        # erscheint das Rot verzoegert — aber ehrlich. Hoechstens 3 s warten, dann trotzdem anzeigen.
        threading.Thread(target=self._show_recording_when_live, args=(self._generation,), daemon=True).start()
        if self.toggle_mode:
            _beep("start")
        if self.tray:
            self.tray.set_state("recording")
        self._streamer = threading.Thread(target=self._stream_loop, args=(self._generation,), daemon=True)
        self._streamer.start()

    def _show_recording_when_live(self, gen: int) -> None:
        t0 = time.time()
        while gen == self._generation and self._recorder.is_recording and self._recorder.captured_frames <= 0:
            if time.time() - t0 > 3.0:
                break
            time.sleep(0.02)
        if gen == self._generation and self._recorder.is_recording:
            self.pipeline.overlay.recording()
            lag = time.time() - t0
            if lag > 0.5:
                print(f"[audio] recording only started after {lag:.1f} s (the stream had to be opened)")

    def _stream_loop(self, gen: int) -> None:
        """Waehrend der Aufnahme: fertige Abschnitte (an Sprechpausen) schon transkribieren."""
        limit_warned = False
        while self._recorder.is_recording and gen == self._generation:
            if self._recorder.limit_hit and not limit_warned:
                limit_warned = True
                _beep("error")
                if self.tray:
                    self.tray.notify(i18n.t("note_limit_reached"))
                self._stop_recording()
                break
            chunk = self._recorder.drain_until_silence(self.chunk_seconds, self.chunk_silence_s)
            if chunk is None:
                if self.tray and self.toggle_mode:
                    self.tray.set_state("recording", f"{int(self._recorder.elapsed_seconds)} s")
                time.sleep(0.5)
                continue
            self._inflight_s = len(chunk) / self._recorder.samplerate
            try:
                t = time.time()
                text = self.pipeline.transcribe(chunk)
                cleaned, _ = self.pipeline.clean_text(text, self._rec_category) if text else ("", [])
            except Exception as e:  # noqa: BLE001
                print(f"[stream] chunk error: {e}")
                continue
            finally:
                self._inflight_s = 0.0
            if cleaned and gen == self._generation:
                with self._parts_lock:
                    self._parts.append(cleaned)
                print(f"[stream] #{gen} chunk {len(self._parts)} ({len(chunk)/self._recorder.samplerate:.0f} s audio, "
                      f"{time.time()-t:.1f} s compute): {_preview(cleaned, 60)!r}")

    def _stop_recording(self) -> None:
        if not self._recorder.is_recording:
            return
        t_stop = time.time()
        arr = self._recorder.stop()
        gen = self._generation
        duration = time.time() - self._rec_start
        self._pending[gen] = duration
        # Messung „reaktiver" (12.09.2026): Taste -> Stopp (Weg durch Hook + Worker) und Stopp -> Ring
        release_at = float(getattr(self._hk, "last_release_at", 0.0) or 0.0)
        self._timing = {"gen": gen, "release": release_at if release_at and t_stop - release_at < 30 else t_stop,
                        "stop": t_stop, "stop_done": time.time(), "inflight_s": self._inflight_s,
                        "tail_s": len(arr) / self._recorder.samplerate}
        # Alles zwischen "Aufnahme ist aus" und "Verarbeitung laeuft" ist Beiwerk (Anzeige, Fenster,
        # Fokus). Faellt hier etwas aus, darf das NIE das Diktat verschlucken: Die Aufnahme ist dann
        # schon gestoppt, aber ohne den Verarbeitungs-Thread bliebe der Text weg und das rote Feld
        # haengen (Vorfall 09.09.2026: fehlender i18n-Import in overlay.py -> "kann nicht mehr
        # beenden"). Deshalb gefangen und mit leerem Kontext weitergemacht.
        ctx: dict = {}
        try:
            # Prognose = Rest + der Abschnitt, den der Streamer gerade rechnet (sonst steht der Ring bei 95 %)
            self.pipeline.overlay.processing(overlay_mod.estimate_seconds(
                len(arr) / self._recorder.samplerate, self._inflight_s))
            self._timing["badge"] = time.time()
            if self.toggle_mode or self.beep_on_stop:
                _beep("stop")  # hoerbar „nimmt nicht mehr auf" — nach der Anzeige, damit die zuerst kommt
            # Fenster + Fokus JETZT merken (beim Stoppen), nicht erst nach der Transkription
            ctx = context_mod.foreground_info(self.cfg)
            if self.pipeline.method == "hybrid":
                f = focus_mod.editable_focus()
                ctx["editable"] = f["editable"]
                ctx["focus_why"] = f["why"]
        except Exception as e:  # noqa: BLE001
            print(f"[dictation] post-stop extras failed ({e}) -> processing anyway")
        with self._busy_lock:
            self._busy += 1
        if self.tray:
            self.tray.set_state("processing")
        threading.Thread(target=self._process, args=(arr, ctx, gen), daemon=True).start()

    def _is_cancelled(self, gen: int) -> bool:
        """Gilt dieses Diktat noch, oder hat inzwischen ein neues begonnen?
        discard_max_s <= 0 = keine Laengen-Ausnahme: eine neue Aufnahme verwirft die vorige immer
        (Entscheidung)."""
        if not self.discard_on_new or gen == self._generation:
            return False
        if self.discard_max_s <= 0:
            return True
        return self._pending.get(gen, 0.0) < self.discard_max_s

    def _process(self, arr: np.ndarray, ctx: dict, gen: int) -> None:
        try:
            st = self._streamer
            timing = self._timing if self._timing.get("gen") == gen else {}

            def prefix_when_ready() -> str:
                """Die fertig bereinigten Abschnitte — erst abgeholt, wenn sie gebraucht werden
                (beim Zusammensetzen), NICHT vor der STT des Rests. So laeuft der Cleanup des
                Abschnitts, der beim Loslassen in Arbeit war, parallel zur STT des Rests
                (12.09.2026: vorher wartete alles auf den Streamer, bevor irgendetwas begann)."""
                t = time.time()
                if st and st.is_alive():
                    st.join(timeout=120)
                timing["stream_wait_s"] = time.time() - t
                with self._parts_lock:
                    # Abschnitte gehoeren nur zu einem Diktat, das noch gilt.
                    return "" if self._is_cancelled(gen) else " ".join(self._parts)

            res = self.pipeline.process_audio(arr, do_inject=True, ctx=ctx,
                                              is_cancelled=lambda: self._is_cancelled(gen),
                                              prefix_cleaned=prefix_when_ready)
            if timing:
                fertig = time.time()
                print("[timing] #%d key->stop %.0f ms, stop->badge %.0f ms, tail %.1f s + chunk %.1f s audio, "
                      "streamer wait %.2f s, stt %ss, cleanup %ss, total since release %.2f s" % (
                          gen, (timing["stop"] - timing["release"]) * 1000,
                          (timing.get("badge", timing["stop_done"]) - timing["stop"]) * 1000,
                          timing["tail_s"], timing["inflight_s"], timing.get("stream_wait_s", 0.0),
                          res.get("stt_s", "?"), res.get("cleanup_s", "?"), fertig - timing["release"]))
            if res.get("note", "").startswith("verworfen"):
                print(f"[dictation] #{gen} {res['note']}")
                self.pipeline.overlay.hide()
            elif res.get("note") == "leeres Transkript":
                self.pipeline.overlay.error(i18n.t("badge_nothing"), 1.5)
            else:
                al = f" aliases={res['aliases']}" if res.get("aliases") else ""
                print(f"[dictation] #{gen} ({self._pending.get(gen, 0):.0f} s recorded) stt {res.get('stt_s','?')}s + cleanup "
                      f"{res.get('cleanup_s','?')}s = {res.get('total_s','?')}s {res.get('delivered','-')}{al} "
                      f"-> {_preview(res.get('cleaned',''), 120)!r}")
        except Exception as e:  # noqa: BLE001
            print(f"[dictation] error: {e}")
            self.pipeline.overlay.error(i18n.t("badge_error_console"))
            _beep("error")
            if self.tray:
                self.tray.notify(i18n.t("note_error", error=e))
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

    def _set_translate_to(self, code: str) -> None:
        """Tray-Auswahl "Translate into". Bewusst NICHT in state.json — nach einem Neustart
        diktiert der Nutzer wieder normal in seiner Sprache (Entscheidung 08.09.2026)."""
        self.pipeline.translate_to = code or ""
        if code:
            print(f"[app] Übersetzungsmodus: alles wird nach {lang_mod.name_en(code)} übersetzt.")
            if self.tray:
                self.tray.notify(i18n.t("note_translate_on", lang=lang_mod.name_native(code)))
        else:
            print("[app] translation off - the text stays in the language you speak.")

    def _set_toggle_mode(self, on: bool) -> None:
        self.toggle_mode = on
        state = _load_state(); state["toggle_mode"] = on; _save_state(state)
        print(f"[app] toggle mode {'ON (press once = record, again = stop)' if on else 'OFF (hold the key)'}")

    def _copy_last(self) -> None:
        t = self.pipeline.last_text()
        if t and inject_mod.to_clipboard(t):
            _beep("ok")
            if self.tray:
                self.tray.notify(_preview(t), title=i18n.t("note_last_text"))
        elif self.tray:
            self.tray.notify(i18n.t("note_no_text"))

    def open_history(self) -> str:
        """Verlaufsdatei im Standard-Editor oeffnen (Tray -> "Open the log", 09.09.2026).
        Rueckgabe: '' = geoeffnet, sonst der Grund (fuer Tray-Meldung und Test)."""
        p = self.pipeline.history_path
        if p is None:
            return i18n.t("note_no_history_configured")
        if not p.exists():
            return i18n.t("note_no_history_yet", file=p.name)
        try:
            import os
            os.startfile(str(p))  # noqa: S606 — Windows-Standardprogramm fuer .log/.txt
            return ""
        except OSError as e:
            return i18n.t("note_history_open_failed", error=e)

    def _open_log(self) -> None:
        grund = self.open_history()
        if grund:
            print(f"[history] {grund}")
            if self.tray:
                self.tray.notify(grund)

    # ---------------- Bildausschnitt ----------------
    def do_snip(self) -> str:
        """Bildschirm einfrieren -> drag a region -> Zwischenablage + PNG.
        Rueckgabe: '' = Bild gemacht, sonst der Grund (Abbruch/Fehler) — auch fuer den Test.

        Reihenfolge ist wichtig: ERST einfrieren, DANN das eigene Anzeigefeld verstecken und die
        Auswahl oeffnen. Was beim Tastendruck zu sehen war (aufgeklappte Menues!), ist damit auf
        dem Bild — das ist der ganze Zweck gegenueber dem Windows-Snipping-Tool."""
        if not self._snip_lock.acquire(blocking=False):
            return "laeuft schon"
        try:
            bild, ox, oy = snip_mod.grab_screen()
            self.pipeline.overlay.hide()
            box = snip_mod.select_region(bild, ox, oy)
            if not box:
                self.pipeline.overlay.error(i18n.t("badge_snip_cancelled"), 0.9)
                return "abgebrochen"
            ausschnitt = bild.crop(box)
            in_ablage = snip_mod.to_clipboard(ausschnitt)
            datei = snip_mod.save_image(ausschnitt, self.snip_folder)
            groesse = "%d x %d" % ausschnitt.size
            if in_ablage:
                self.pipeline.overlay.done(i18n.t("badge_snip_ready"))
                if self.snip_beep:
                    _beep("ok")
            else:
                self.pipeline.overlay.error(i18n.t("badge_snip_failed"), 1.5)
            print(f"[snip] {groesse} -> clipboard={in_ablage}, file={datei.name}")
            if self.tray:
                self.tray.notify(i18n.t("note_snip_saved", size=groesse, file=datei.name))
            return "" if in_ablage else "Clipboard locked"
        except Exception as e:  # noqa: BLE001
            print(f"[snip] error: {e}")
            self.pipeline.overlay.error(i18n.t("badge_snip_failed"), 1.5)
            if self.tray:
                self.tray.notify(i18n.t("note_error", error=e))
            return str(e)
        finally:
            self._snip_lock.release()

    def do_fullscreen(self) -> str:
        """Ganzer Bildschirm, ohne Rahmen ziehen (zweimal kurz tippen, 10.09.2026).
        Gedacht fuer „schau dir das mal an": ein Griff, das Bild liegt im Ordner und in der
        Zwischenablage. Rueckgabe: '' = Bild gemacht, sonst der Grund."""
        if not self._snip_lock.acquire(blocking=False):
            return "laeuft schon"
        try:
            self.pipeline.overlay.hide()
            time.sleep(0.12)          # das eigene Anzeigefeld soll nicht mit aufs Bild
            bild, ox, oy = snip_mod.grab_screen()
            wo = "all monitors"
            if self.snip_full_scope != "alle":
                # nur der Monitor unter der Maus: halb so grosses Bild, halb so viel Kontext
                r = snip_mod.monitor_rect()
                if r:
                    bild = bild.crop((r[0] - ox, r[1] - oy, r[2] - ox, r[3] - oy))
                    wo = "the monitor under the mouse"
            in_ablage = snip_mod.to_clipboard(bild)
            datei = snip_mod.save_image(bild, self.snip_folder)
            groesse = "%d x %d" % bild.size
            self.pipeline.overlay.done(i18n.t("badge_snip_full"))
            if self.snip_beep:
                _beep("ok")
            print(f"[snip] whole screen ({wo}) {groesse} -> clipboard={in_ablage}, file={datei.name}")
            if self.tray:
                self.tray.notify(i18n.t("note_snip_full", size=groesse, file=datei.name))
            return "" if in_ablage else "Clipboard locked"
        except Exception as e:  # noqa: BLE001
            print(f"[snip] error (whole screen): {e}")
            self.pipeline.overlay.error(i18n.t("badge_snip_failed"), 1.5)
            return str(e)
        finally:
            self._snip_lock.release()

    def _snip_armed(self) -> None:
        """Haltezeit erreicht (Betriebsart „hold"): am Mauszeiger anzeigen, dass Loslassen jetzt
        den Ausschnitt oeffnet. Ohne diese Rueckmeldung haelt man die Taste ins Blaue."""
        self.pipeline.overlay.notice(i18n.t("badge_snip_arm"), 3.0)

    def open_images(self) -> str:
        """Bilder-Ordner im Explorer oeffnen (Tray -> "Bilder oeffnen").
        Rueckgabe: '' = geoeffnet, sonst der Grund."""
        if not self.snip_folder.exists() or not any(self.snip_folder.glob("*.png")):
            return i18n.t("note_no_images_yet", file=self.snip_folder.name)
        try:
            import os
            os.startfile(str(self.snip_folder))  # noqa: S606 — Explorer
            return ""
        except OSError as e:
            return i18n.t("note_images_open_failed", error=e)

    def _open_images(self) -> None:
        grund = self.open_images()
        if grund:
            print(f"[snip] {grund}")
            if self.tray:
                self.tray.notify(grund)

    def _set_ui_language(self, setting: str) -> None:
        """Tray -> Sprache. setting = 'auto' oder ein Code aus i18n.LANGUAGES."""
        self.ui_language = setting
        code = i18n.set_language(i18n.resolve(setting))
        st = _load_state(); st["ui_lang"] = setting; _save_state(st)
        snip_mod.set_hint(i18n.t("snip_hint"))
        print(f"[app] UI-Sprache: {code} (Einstellung: {setting})")
        if self.tray:
            self.tray.notify(i18n.t("note_language_set", lang=i18n.label(code)))

    def _quit(self) -> None:
        self._stop.set()

    def run(self) -> None:
        print("[app] warming up ...")
        self.pipeline.overlay.start()
        w = self.pipeline.warmup()
        print(f"[app] warm-up done in {w['warmup_s']}s. LLM reachable: {w['llm_reachable']}")
        if not w["llm_reachable"]:
            print("[app] WARN: clean-up LLM not reachable -> raw transcript is delivered until Ollama runs.")

        if self._recorder.open():
            print(f"[app] microphone stream open (pre-roll {self._recorder.preroll_frames / self._recorder.samplerate:.1f} s) -> recording starts the instant you press.")

        key = self.cfg.get("hotkey", {}).get("key", "ctrl_r")
        hk = HoldToTalk(key, self._on_press, self._on_release)
        self._hk = hk
        hk.start()
        if self.snip_enabled:
            weg = snip_mod.cleanup_old(self.snip_folder, self.snip_keep_days)
            self._snip_watcher = snip_mod.KeyWatcher(
                self.snip_key, self.do_snip, self.snip_suppress,
                mode=self.snip_mode, hold_ms=self.snip_hold_ms, on_arm=self._snip_armed,
                on_double=(self.do_fullscreen if self.snip_double else None),
                double_tap_ms=self.snip_double_ms)
            self._snip_watcher.start()
            print(f"[snip] screenshots on: {snip_mod.key_label(self.snip_key)} -> drag a region"
                  + (", double-tap -> whole screen. " if self.snip_double
                     else " (Enter in the selection window = whole screen). ")
                  + f"folder {self.snip_folder.name}, kept {self.snip_keep_days} days"
                  + (f", {weg} old ones deleted" if weg else ""))
        mode = self.pipeline.method
        hint = {"hybrid": "a focused text field gets the text directly, otherwise the clipboard (Ctrl+V).",
                "clipboard_only": "text goes to the clipboard (Ctrl+V).",
                }.get(mode, f"inserts text at the cursor ({mode}).")
        how = "press once = on, again = off (toggle mode)" if self.toggle_mode else "hold it down"
        print(f"[app] ready. '{key}' {how}. Then -> {hint}")

        self.pipeline.tray = None
        if self.use_tray:
            from wf.tray import Tray
            self.tray = Tray(self._toggle, self._quit, on_toggle_mode=self._set_toggle_mode,
                             on_copy_last=self._copy_last, toggle_mode=self.toggle_mode,
                             on_translate_to=self._set_translate_to, on_open_log=self._open_log,
                             on_set_ui_language=self._set_ui_language, ui_language=self.ui_language,
                             on_open_images=self._open_images)
            self.pipeline.tray = self.tray
            self.tray.set_state("idle")
            # pystray.run() blockiert im Main-Thread; Hotkey-Listener laeuft eh separat
            self.tray.run()
            hk.stop()
            if self._snip_watcher:
                self._snip_watcher.stop()
        else:
            try:
                while not self._stop.is_set():
                    time.sleep(0.2)
            except KeyboardInterrupt:
                pass
            hk.stop()
            if self._snip_watcher:
                self._snip_watcher.stop()
        self._recorder.close()
        self.pipeline.cleaner.unload()
        print("[app] stopped (models unloaded from VRAM).")


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
    # Ohne Mikro gibt es keine Whisper-Erkennung — hier uebernimmt der deterministische
    # DE/EN-Pruefer die Rolle, damit dieser Aufruf dasselbe Verhalten testet wie ein Diktat.
    erkannt = lang_mod.sniff_de_en(text)
    cleaned, was = pipe.cleaner.clean(text, "default", erkannt)
    cleaned, applied = pipe.aliases.fix(cleaned)
    print(f"Language: {erkannt or '(unklar)'}")
    print(f"RAW:      {text!r}")
    print(f"CLEANED:  {cleaned!r}")
    print(f"cleaned:  {was}  aliases: {applied}")
    return 0


class _Stamped:
    """Schreibt jede Zeile mit Uhrzeit davor in eine Datei (fuer die fensterlose Instanz)."""

    def __init__(self, fh):
        self._fh = fh
        self._at_line_start = True

    def write(self, s: str) -> int:
        if not s:
            return 0
        out = []
        for teil in s.splitlines(True):
            if self._at_line_start and teil.strip():
                out.append(time.strftime("%H:%M:%S ") + teil)
            else:
                out.append(teil)
            self._at_line_start = teil.endswith("\n")
        self._fh.write("".join(out))
        self._fh.flush()
        return len(s)

    def flush(self) -> None:
        self._fh.flush()


def _attach_file_log(path: Path, max_bytes: int = 2_000_000) -> None:
    """Ohne Konsole (pythonw) ging jede Ausgabe bisher ins Leere — ein Absturz oder eine
    Zeitmessung war damit unsichtbar (Vorfall 09.09.2026). Jetzt: data/app.log, Uhrzeit je
    Zeile, bei mehr als max_bytes wird die aeltere Haelfte verworfen."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > max_bytes:
            rest = path.read_bytes()[-max_bytes // 2:]
            path.write_bytes(rest[rest.find(b"\n") + 1:])
        fh = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 — lebt so lange wie der Prozess
        sys.stdout = sys.stderr = _Stamped(fh)  # type: ignore[assignment]
        print("[app] --- start %s ---" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:  # noqa: BLE001 — ohne Protokoll weiterlaufen ist besser als gar nicht
        pass


def main() -> int:
    if sys.stdout is None or sys.stderr is None:       # fensterlos gestartet (pythonw)
        _attach_file_log(ROOT / "data" / "app.log")
    ap = argparse.ArgumentParser(description="my-local-whisper")
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--transcribe-file", metavar="WAV")
    ap.add_argument("--clean-text", metavar="TEXT")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--calibrate", action="store_true", help="Begriffe vorlesen, Hoer-Fehler als Alias uebernehmen")
    ap.add_argument("--nur", default="", metavar="ABSCHNITT",
                    help="calibrate only one section of dictionary.txt, e.g. --nur english")
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
        return run_calibration(cfg, args.nur)

    App(cfg, use_tray=not args.no_tray).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
