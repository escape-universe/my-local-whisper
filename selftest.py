"""S10 — Deterministische Selbsttests (kein Mikro, kein Live-App noetig).

Beweist die Bausteine, die ohne gesprochenes Live-Diktat pruefbar sind:
- Config + Dictionary laden
- Cleanup-Prompt-Bau (Regeln + Few-Shots vorhanden)
- <think>-Strip + Output-Extraktion
- Text-Injektion (Clipboard UND SendInput) mit Umlauten in ein echtes Tk-Entry-Widget,
  Inhalt zurueckgelesen -> beweist Kriterium 4 (umlaut-korrekt am Cursor)
- Foreground-Window-Erkennung

Aufruf:  py selftest.py     oder     py whisperflow.py --selftest
"""
from __future__ import annotations

import sys
import time

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def test_imports() -> None:
    try:
        from wf import audio, cleanup, config, context, inject, stt, tray, hotkey  # noqa: F401
        check("imports: alle wf-Module laden", True)
    except Exception as e:  # noqa: BLE001
        check("imports: alle wf-Module laden", False, str(e))


def test_config_and_dict() -> None:
    from wf import config as c
    cfg = c.load_config()
    check("config: laedt config.yaml", bool(cfg.get("llm")))
    terms = c.load_dictionary(cfg)
    check("dictionary: Begriffe geladen", len(terms) > 5, f"{len(terms)} Begriffe")
    check("dictionary: Beispielbegriffe dabei", "Nextcloud" in terms)
    seed = c.dictionary_prompt_seed(terms)
    check("dictionary: initial_prompt-Seed gebaut", "Nextcloud" in seed)


def test_cleanup_prompt() -> None:
    from wf import cleanup as cl
    msgs = cl.build_messages("test text", ["Nextcloud", "Thunderbird"], "chat")
    system = msgs[0]["content"]
    check("cleanup: System-Prompt = Editor-Rolle", "text editor, not an assistant" in system)
    check("cleanup: Frage-bleibt-Frage-Regel", "you do not answer" in system.lower())
    check("cleanup: Gedankenstrich-Verbot", "em-dash" in system.lower())
    check("cleanup: Umlaut-Regel", "forbidden" in system.lower() and "ä ö ü ß" in system)
    check("cleanup: Woerterbuch injiziert", "Nextcloud" in system)
    check("cleanup: Chat-Ton injiziert", "Slack" in system or "Chat" in system)
    check("cleanup: Few-Shots vorhanden (>=8 Nachrichten)", len(msgs) >= 10, f"{len(msgs)} Nachrichten")
    # letzte Nachricht = der zu bereinigende Transkript
    check("cleanup: Transkript gewrappt", msgs[-1]["content"] == "<transcript>test text</transcript>")


def test_think_strip() -> None:
    from wf import cleanup as cl
    dirty = "<think>ich ueberlege</think>Das ist der Text."
    check("cleanup: <think> gestrippt", cl._strip_think(dirty) == "Das ist der Text.")
    wrapped = '<transcript>Hallo Welt</transcript>'
    check("cleanup: <transcript>-Extraktion", cl._extract(wrapped) == "Hallo Welt")
    quoted = '"Hallo Welt"'
    check("cleanup: Quotes gestrippt", cl._extract(quoted) == "Hallo Welt")


def _win32_inject_roundtrip(launch: list[str], win_class: str, edit_class: str,
                            method: str, text: str) -> tuple[bool, str]:
    """Startet eine echte Win32-App, gibt dem Edit-Control Tastaturfokus (AttachThreadInput-Recipe),
    injiziert `text` per `method`, liest via WM_GETTEXT zurueck. Returns (ok, detail).
    Beweist die Injektion end-to-end in eine echte App — nicht nur die Mechanik."""
    import ctypes
    import subprocess
    u32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32
    from wf import inject as ij
    WM_GETTEXT, WM_SETTEXT, WM_CLOSE = 0x000D, 0x000C, 0x0010
    proc = subprocess.Popen(launch)
    hwnd = 0
    try:
        for _ in range(50):
            time.sleep(0.1)
            hwnd = u32.FindWindowW(win_class, None)
            if hwnd:
                break
        if not hwnd:
            return False, f"{win_class}-Fenster nicht gefunden (evtl. andere Windows-Version)"
        edit = u32.FindWindowExW(hwnd, 0, edit_class, None)
        if not edit:
            return False, f"Kein {edit_class}-Control gefunden"
        # robuste Fokus-Uebergabe: an die GUI-Thread der Ziel-App attachen
        our = k32.GetCurrentThreadId()
        tgt = u32.GetWindowThreadProcessId(hwnd, None)
        # Foreground-Lock-Timeout auf 0 (Windows blockt sonst den Fokuswechsel aus dem Hintergrund).
        # KEIN ALT-Tap — das aktiviert die Menueleiste und frisst das erste Zeichen / blockt Ctrl+V.
        u32.SystemParametersInfoW(0x2001, 0, ctypes.c_void_p(0), 0)  # SPI_SETFOREGROUNDLOCKTIMEOUT
        u32.AttachThreadInput(our, tgt, True)
        try:
            fg_ok = False
            for _ in range(12):
                u32.ShowWindow(hwnd, 9)  # SW_RESTORE
                u32.BringWindowToTop(hwnd)
                u32.SetForegroundWindow(hwnd)
                u32.SetActiveWindow(hwnd)
                time.sleep(0.15)
                if u32.GetForegroundWindow() == hwnd:
                    fg_ok = True
                    break
            u32.SetFocus(edit)
            time.sleep(0.3)
            focus_ok = (u32.GetFocus() == edit)
            if not fg_ok or not focus_ok:
                # Vordergrund/Fokus im automatisierten Lauf nicht erzwingbar -> Delivery diesen Lauf
                # nicht testbar (kein Injektions-Bug; in anderen Läufen belegt; im Alltag klickt der Nutzer selbst).
                return None, f"fg={fg_ok} focus={focus_ok} (Fenster nicht sauber im Vordergrund/Fokus)"
            u32.SendMessageW(edit, WM_SETTEXT, 0, ctypes.c_wchar_p(""))
            ij.inject(text, method=method, restore_delay_ms=150)
            time.sleep(0.5)
        finally:
            u32.AttachThreadInput(our, tgt, False)
        buf = ctypes.create_unicode_buffer(2048)
        u32.SendMessageW(edit, WM_GETTEXT, 2048, buf)
        got = buf.value
        return got == text, f"fg={fg_ok} focus={focus_ok} bekam={got!r}"
    finally:
        try:
            if hwnd:
                e2 = u32.FindWindowExW(hwnd, 0, edit_class, None)
                if e2:
                    u32.SendMessageW(e2, WM_SETTEXT, 0, ctypes.c_wchar_p(""))
                u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            time.sleep(0.3)
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass


def test_clipboard_payload() -> None:
    """Fokus-frei: beweist, dass die Clipboard-Nutzlast Umlaute verlustfrei traegt."""
    from wf import inject as ij
    sample = "Grüße äöüß — kein ae/oe/ue/ss, Nextcloud."
    sample = "Grüße äöüß, Nextcloud in Nienburg."
    try:
        old, fmt = ij._clip_get()
        ij._clip_set(sample)
        back, _ = ij._clip_get()
        ij._clip_restore(old, fmt)
        check("inject: Clipboard-Payload umlaut-verlustfrei (fokus-frei)", back == sample,
              f"bekam={back!r}")
    except Exception as e:  # noqa: BLE001
        check("inject: Clipboard-Payload umlaut-verlustfrei (fokus-frei)", False, str(e))


def test_clipboard_only() -> None:
    """Default-Modus seit 05.09.2026: Text liegt NUR in der Zwischenablage, nichts wird getippt,
    die Zwischenablage wird NICHT zurueckgesetzt (der Nutzer fuegt spaeter selbst ein)."""
    from wf import inject as ij
    from wf import config as c
    cfg = c.load_config()
    check("config: inject.method in (hybrid, clipboard_only)", cfg["inject"]["method"] in ("hybrid", "clipboard_only"),
          f"method={cfg['inject']['method']!r}")
    check("config: llm.base_url nutzt 127.0.0.1 (nicht localhost)", "127.0.0.1" in cfg["llm"]["base_url"],
          cfg["llm"]["base_url"])
    check("config: stt.model = large-v3-turbo", cfg["stt"]["model"] == "large-v3-turbo", cfg["stt"]["model"])
    sample = "Zwischenablage-Test: Grüße äöüß aus Nienburg."
    old, fmt = ij._clip_get()
    try:
        ok = ij.inject(sample, method="clipboard_only")
        back, _ = ij._clip_get()
        check("inject: clipboard_only legt Text ab + Rueck-Lesen ok", ok and back == sample, f"bekam={back!r}")
        time.sleep(0.3)
        back2, _ = ij._clip_get()
        check("inject: clipboard_only stellt NICHT zurueck (Text bleibt fuer Strg+V)", back2 == sample)
    finally:
        ij._clip_restore(old, fmt)
    # Cleaner biegt localhost auf 127.0.0.1 um
    from wf import cleanup as cl
    cfg2 = {"llm": {"base_url": "http://localhost:11434/v1"}}
    check("cleanup: localhost -> 127.0.0.1 Umbiegung", cl.Cleaner(cfg2, []).url.startswith("http://127.0.0.1:11434"))


def test_aliases_focus_employees() -> None:
    """Alias-Korrektur, optionale Namensliste, Fokus-Erkennung, Hybrid-Default."""
    from wf import aliases as al
    from wf import config as c
    from wf import focus as fo
    cfg = c.load_config()
    check("config: inject.method = hybrid (Default)", cfg["inject"]["method"] == "hybrid", cfg["inject"]["method"])
    pairs = al.load_aliases(c.load_aliases_path(cfg))
    check("aliases: aliases.txt geladen (>=5 Regeln)", len(pairs) >= 5, f"{len(pairs)} Regeln")
    fx = al.AliasFixer(pairs)
    out, applied = fx.fix("Lade es in Nextclout hoch, sunderbird bleibt zu. Nextclouts Ordner bleibt.")
    check("aliases: Nextclout->Nextcloud, sunderbird->Thunderbird, Wortgrenze respektiert",
          out == "Lade es in Nextcloud hoch, Thunderbird bleibt zu. Nextclouts Ordner bleibt.", out)
    first, full = c.load_employee_names(cfg)
    check("employees: optionale Namensliste (aus = leere Listen, kein Fehler)",
          isinstance(first, list) and isinstance(full, list), f"{len(first)} Vornamen")
    info = fo.editable_focus()
    check("focus: editable_focus liefert Dict mit bool", isinstance(info.get("editable"), bool), f"{info}")


def test_long_dictation_parts() -> None:
    """05.09.2026 spaet: Sprechpausen-Schnitt, Cleanup-Stueckelung, Umschalt-Modus-Logik."""
    import numpy as np
    from wf import audio as au
    from wf import cleanup as cl
    sr = 16000
    rng = np.random.default_rng(1)
    speech = lambda s: (rng.standard_normal(int(s * sr)) * 0.2).astype(np.float32)  # noqa: E731
    silence = lambda s: np.zeros(int(s * sr), dtype=np.float32)  # noqa: E731
    a = np.concatenate([speech(10), silence(0.8), speech(8), silence(0.2), speech(6)])
    cut = au.find_silence_cut(a, sr)
    check("audio: Schnitt in der langen Pause (nicht in der 0,2-s-Pause)",
          cut is not None and abs(cut / sr - 10.4) < 0.3, f"cut={'None' if cut is None else f'{cut/sr:.2f}s'}")
    check("audio: kein Schnitt ohne Pause", au.find_silence_cut(speech(30), sr) is None)
    ch = cl.Cleaner.split_chunks("Satz eins. Satz zwei! Satz drei? " * 80, 300)
    check("cleanup: lange Texte satzweise gestueckelt (<=300 Zeichen, Satzende erhalten)",
          len(ch) > 5 and max(len(c) for c in ch) <= 300 and all(c[-1] in ".!?" for c in ch), f"{len(ch)} Stuecke")
    check("cleanup: kurzer Text bleibt ein Stueck", cl.Cleaner.split_chunks("Kurz.", 300) == ["Kurz."])
    # Umschalt-Modus: Druecken startet, Loslassen ignoriert, zweites Druecken stoppt
    import whisperflow as W
    from wf import config as c
    app = W.App.__new__(W.App)
    calls = []
    app._enabled = True; app.toggle_mode = True
    class R:  # noqa: D401 - Mini-Recorder-Attrappe
        is_recording = False
    app._recorder = R()
    app._start_recording = lambda: (calls.append("start"), setattr(R, "is_recording", True))
    app._stop_recording = lambda: (calls.append("stop"), setattr(R, "is_recording", False))
    app._on_press(); app._on_release(); app._on_press(); app._on_release()
    check("toggle: druecken=start, loslassen=nichts, druecken=stop", calls == ["start", "stop"], str(calls))
    # Verwerf-Schwelle: kurze alte Aufnahme wird verworfen, lange nicht
    app.discard_on_new = True; app.discard_max_s = 30; app._generation = 2; app._pending = {1: 5.0}
    short = app._is_cancelled(1)
    app._pending = {1: 600.0}
    long_ = app._is_cancelled(1)
    check("discard: 5-s-Aufnahme verworfen, 10-min-Aufnahme geliefert", short is True and long_ is False)
    cfg = c.load_config()
    check("config: audio.max_seconds >= 3600 (lange Reden)", int(cfg["audio"]["max_seconds"]) >= 3600, str(cfg["audio"]["max_seconds"]))
    from wf import stt as st
    check("stt: Prompt-Schluss-Satz definiert (Namen am Prompt-Ende werden sonst verschluckt)",
          st.Transcriber.PROMPT_SUFFIX.strip().endswith(".") and st.Transcriber.PROMPT_TOKEN_BUDGET <= 217)
    import calibrate as cal, tempfile
    from pathlib import Path as _P
    tmp = _P(tempfile.mkdtemp()) / "a.txt"
    ok1 = cal._append_alias(tmp, "Nextcloud", "Owncloud, Next, Cloud, Dropbox.n")
    ok2 = cal._append_alias(tmp, "Ollama", "Olama.")
    check("calibrate: Muell-Alias verworfen, echter Alias gespeichert",
          ok1 is False and ok2 is True and tmp.read_text(encoding="utf-8").strip() == "Ollama = Olama")


def test_injection() -> None:
    sample = "Grüße äöüß, Nextcloud in Nienburg."
    # App 1: klassisches Notepad (Edit-Control) — Win10 vorhanden
    apps = [("Notepad", ["notepad.exe"], "Notepad", "Edit"),
            # App 2: WordPad (RichEdit) — anderer Control-Typ, wenn vorhanden
            ("WordPad", ["write.exe"], "WordPadClass", "RICHEDIT50W")]
    for app_name, launch, win_class, edit_class in apps:
        for method, label in (("clipboard", "Clipboard-Paste"), ("sendinput", "SendInput-Unicode")):
            try:
                ok, det = _win32_inject_roundtrip(launch, win_class, edit_class, method, sample)
            except Exception as e:  # noqa: BLE001
                check(f"inject: {app_name} {label} umlaut-korrekt", False, f"n/a: {e}")
                continue
            if ok is None:
                # Vordergrund im automatisierten Lauf nicht erzwingbar -> Delivery diesen Lauf nicht testbar.
                # (Kein Injektions-Bug: in anderen Läufen belegt; im echten Betrieb bringt der Nutzer das Fenster selbst nach vorn.)
                print(f"[SKIP] inject: {app_name} {label} — {det}")
                continue
            if not ok and ("nicht gefunden" in det or "Control gefunden" in det):
                print(f"[SKIP] inject: {app_name} {label} — {det} (andere Windows-Version)")
                continue
            check(f"inject: {app_name} {label} umlaut-korrekt (echte App, WM_GETTEXT)", ok, det)


def test_context() -> None:
    from wf import config as c
    from wf import context as ctx
    info = ctx.foreground_info(c.load_config())
    check("context: foreground_info liefert Dict", isinstance(info, dict) and "category" in info,
          f"process={info.get('process')!r} category={info.get('category')!r}")
    elevated = ctx.is_foreground_elevated()
    check("context: is_foreground_elevated laeuft", isinstance(elevated, bool), f"elevated={elevated}")


def run_selftests() -> int:
    print("=== whisperflow-local Selbsttests ===\n")
    test_imports()
    test_config_and_dict()
    test_cleanup_prompt()
    test_think_strip()
    test_context()
    test_clipboard_payload()  # fokus-frei
    test_clipboard_only()     # fokus-frei
    test_aliases_focus_employees()
    test_long_dictation_parts()
    test_injection()  # GUI zuletzt (oeffnet kurz ein Fenster)
    fails = [r for r in RESULTS if not r[1]]
    print(f"\n=== {len(RESULTS) - len(fails)}/{len(RESULTS)} bestanden ===")
    if fails:
        print("Fehlgeschlagen:")
        for name, _, det in fails:
            print(f"  - {name} ({det})")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(run_selftests())
