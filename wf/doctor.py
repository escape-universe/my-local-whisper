"""`py whisperflow.py --doctor`: Selbstdiagnose fuer die Einrichtung auf einem fremden Rechner
(Arbeitspaket 4). Druckt je Pruefpunkt eine [OK]/[WARN]/[FAIL]-Zeile mit Abhilfe und liefert den
Exit-Code (0 ohne FAIL, sonst 1) zurueck. Laeuft auch unter Linux ohne Absturz (dort sind FAIL/WARN
fuer die Windows-Pakete erwartbar - die App selbst unterstuetzt nur Windows live, siehe CLAUDE.md).

Zwei Sicherungen gegen einen Absturz VOR der ersten Zeile (Nachbesserung Arbeitspaket 4, Runde 1,
Bloecker B1/B2 des Pruefers):
  1. Dieses Modul importiert am eigenen Kopf NUR die Standardbibliothek. wf.config/wf.cleanup/
     wf.stt (die yaml/requests/numpy brauchen) werden erst INNERHALB der Pruefung importiert, die
     sie braucht - genau die Pakete, die --doctor melden soll, duerfen es nicht selbst zum
     Absturz bringen. whisperflow.py faengt "--doctor" zusaetzlich VOR seinen eigenen schweren
     Importen ab (numpy, wf.audio/sounddevice, ...), noch bevor dieses Modul ueberhaupt geladen wird.
  2. run_doctor() faengt um JEDEN einzelnen Pruefpunkt eine Ausnahme ab: ein kaputter Konfig-Wert
     oder eine veraltete Mikrofon-Nummer wird eine einzelne [FAIL]-Zeile ("<Pruefpunkt> check
     crashed (...)", wo sinnvoll mit dem betroffenen config.yaml-Abschnitt), reisst aber nicht die
     folgenden Pruefungen mit ab.

Konsolen-Ausgabe englisch (Projektkonvention: sie liest, wer einen Fehler sucht).
"""
from __future__ import annotations

import importlib
import os
import sys

#: importlib-Modulname -> (Pip-Paket-Name fuer die Abhilfe-Zeile, fehlt es nur optional).
_PACKAGES: list[tuple[str, str, bool]] = [
    ("faster_whisper", "faster-whisper", False),
    ("sounddevice", "sounddevice", False),
    ("numpy", "numpy", False),
    ("pynput", "pynput", False),
    ("pystray", "pystray", False),
    ("PIL", "Pillow", False),
    ("win32clipboard", "pywin32", False),
    ("uiautomation", "uiautomation", False),
    ("requests", "requests", False),
    ("yaml", "PyYAML", False),
    # optional: schnellerer Prozessname in wf/context.py, sonst ein ctypes-Fallback (kein FAIL).
    ("psutil", "psutil", True),
]

#: Pruefpunkte, die config.yaml brauchen - wird cfg nicht geladen, bekommt jeder davon eine
# eigene "skipped"-Zeile statt stillschweigend zu fehlen (Nachbesserung Arbeitspaket 4, Runde 2).
_CONFIG_ABHAENGIGE_PRUEFPUNKTE = (
    "dictionary/alias files", "microphone", "GPU", "speech model cache", "clean-up model",
    "translation model",
)


def _check_python() -> tuple[str, str]:
    # Indexzugriff statt .major/.minor/.micro: sys.version_info ist ein structseq (verhaelt sich
    # wie ein Tupel), damit funktioniert dieselbe Zeile auch mit einem einfachen Tupel im Test.
    major, minor, micro = sys.version_info[0], sys.version_info[1], sys.version_info[2]
    text = f"Python {major}.{minor}.{micro}"
    if (major, minor) >= (3, 11):
        return "ok", f"{text} (>= 3.11)"
    return "fail", f"{text} is too old -> install Python 3.11 or newer"


def _check_os() -> tuple[str, str]:
    if sys.platform == "win32":
        return "ok", "Windows"
    return "warn", f"{sys.platform} -> only Windows is supported live, this only checks the setup logic"


def _check_import(module: str, pip_name: str, optional: bool) -> tuple[str, str]:
    try:
        mod = importlib.import_module(module)
    except Exception as e:  # noqa: BLE001 — jeder Importfehler wird eine Zeile, nicht ein Absturz
        return ("warn" if optional else "fail"), f"{module} not importable ({e}) -> py -m pip install {pip_name}"
    if module == "sounddevice":
        # Der Import kann klappen, auch wenn die native PortAudio-Bibliothek fehlt (die schlaegt
        # erst beim ersten Zugriff fehl, nicht beim Import).
        try:
            mod.query_devices()
        except Exception as e:  # noqa: BLE001
            return "fail", f"sounddevice imports, but PortAudio failed ({e}) -> reinstall sounddevice"
    return "ok", f"{module} importable"


def _check_config() -> tuple[str, str, dict | None]:
    """cfg = None, wenn nicht gelesen werden konnte - run_doctor() druckt dann fuer jeden
    abhaengigen Pruefpunkt eine eigene "skipped"-Zeile, statt sie stillschweigend auszulassen.

    Fehlt PyYAML selbst, ist das NICHT "config.yaml ist kaputt" - die eigene [FAIL]-Zeile fuer
    "yaml" (aus _PACKAGES) sagt das schon; eine eigene, richtige Aussage statt einer
    irrefuehrenden (Hinweis Arbeitspaket 4, Runde 2: "config.yaml unreadable" klingt nach einem
    Problem MIT DER DATEI, obwohl sie nur noch nie geparst werden konnte)."""
    try:
        import yaml  # noqa: F401
    except Exception:  # noqa: BLE001
        return "fail", "cannot check config.yaml: PyYAML missing (see above)", None
    try:
        from wf import config as config_mod
    except Exception as e:  # noqa: BLE001
        return "fail", f"config.yaml unreadable ({e})", None
    try:
        cfg = config_mod.load_config()
    except config_mod.ConfigError as e:
        # Arbeitspaket 7 (25.09.2026): ConfigError nennt die Datei (config.yaml ODER
        # config.local.yaml), die Zeile und die Abhilfe schon selbst - "config.yaml unreadable"
        # davor waere bei einer kaputten config.local.yaml irrefuehrend.
        return "fail", str(e), None
    except Exception as e:  # noqa: BLE001
        return "fail", f"config.yaml unreadable ({e})", None
    zusatz = "; ".join(z.removeprefix("[config] ") for z in config_mod.local_summary_lines(cfg))
    return "ok", "config.yaml readable" + (f" ({zusatz})" if zusatz else ""), cfg


def _check_dictionary_files(cfg: dict) -> tuple[str, str]:
    from wf import config as config_mod
    dict_path = config_mod.ROOT / cfg.get("dictionary_path", "dictionary.txt")
    alias_path = config_mod.load_aliases_path(cfg)
    missing = [str(p) for p in (dict_path, alias_path) if not p.exists()]
    if missing:
        return "warn", f"missing: {', '.join(missing)} -> the app runs, but without your vocabulary"
    return "ok", f"{dict_path.name}, {alias_path.name} found"


def _check_microphone(cfg: dict) -> tuple[str, str]:
    """Standard-Eingang bzw. das in audio.input_device konfigurierte Geraet auffindbar?
    sounddevice wird hier absichtlich noch einmal lokal importiert (nicht wf.audio): so bleibt
    dieser Pruefpunkt auch dann sauber "nicht pruefbar", wenn sounddevice/PortAudio fehlt, statt
    beim Import von wf.audio mitzuscheitern."""
    try:
        import sounddevice as sd
    except Exception as e:  # noqa: BLE001
        return "warn", f"cannot check (sounddevice/PortAudio not available: {e})"
    try:
        devices = sd.query_devices()
    except Exception as e:  # noqa: BLE001
        return "fail", f"cannot list audio devices ({e})"
    inputs = [d for d in devices if d.get("max_input_channels", 0) > 0]
    if not inputs:
        return "fail", "no input device found -> connect a microphone"
    configured = (cfg.get("audio", {}) or {}).get("input_device")
    if configured in (None, ""):
        return "ok", f"{len(inputs)} input device(s) found, using the system default"
    from wf.audio import _resolve_device
    idx = _resolve_device(configured)
    # _resolve_device(int) gibt eine Zahl IMMER ungeprueft zurueck (wf/audio.py: nur str wird
    # gegen die echte Geraeteliste gesucht) - eine veraltete Nummer (z. B. nach dem Abstecken
    # eines USB-Mikrofons) waere sonst ein IndexError statt einer FAIL-Zeile (Nachbesserung
    # Arbeitspaket 4, Runde 1, B2).
    if (idx is None or not (0 <= idx < len(devices))
            or devices[idx].get("max_input_channels", 0) <= 0):
        return "fail", (f"configured microphone {configured!r} not found -> check audio.input_device "
                        f"in config.yaml (py whisperflow.py --list-devices shows the current devices)")
    return "ok", f"configured microphone found: {devices[idx].get('name', idx)}"


def _check_gpu() -> tuple[str, str]:
    """CUDA-Karten laut ctranslate2 + das Ergebnis der DLL-Pruefung aus wf/stt.py."""
    try:
        import ctranslate2
    except Exception as e:  # noqa: BLE001
        return "warn", f"cannot check (ctranslate2 not installed yet, it comes with faster-whisper: {e})"
    try:
        n = ctranslate2.get_cuda_device_count()
    except Exception as e:  # noqa: BLE001
        return "warn", f"cannot check ({e})"
    if n <= 0:
        return "warn", "no CUDA GPU detected -> runs on the CPU, noticeably slower"
    from wf import stt as stt_mod
    ok = stt_mod.cuda_dlls_loadable()
    if ok is False:
        return "warn", (f"{n} CUDA GPU(s) found, but cuBLAS/cuDNN could not be loaded -> falls back "
                        f"to the CPU. Fix: {stt_mod.GPU_FIX_HINT}")
    if ok is True:
        return "ok", f"{n} CUDA GPU(s) found, cuBLAS/cuDNN load fine"
    return "ok", f"{n} CUDA GPU(s) found (cuBLAS/cuDNN is only checked on Windows)"


def _check_speech_model_cache(cfg: dict) -> tuple[str, str]:
    """Liegt das Whisper-Modell (stt.model) schon lokal, und mit tokenizer.json? Ohne Netz: der
    lokale Ordner kommt ueber download_model(..., local_files_only=True), denselben Weg wie in
    wf/stt.py (Nachbesserung Arbeitspaket 9, Runde 1). Die tokenizer.json zaehlt, weil
    faster-whisper sonst bei JEDEM Laden Tokenizer.from_pretrained("openai/whisper-tiny...")
    aufruft, also Hugging Face fragt (faster_whisper/transcribe.py, gelesen in 1.1.0 und 1.2.1).
    Ein Modellordner in stt.model wird direkt angesehen, wie faster-whisper es auch tut."""
    model = (cfg.get("stt", {}) or {}).get("model", "large-v3-turbo")
    if os.path.isdir(model):
        ordner, name = model, f"speech model folder {model}"
        if not os.path.isfile(os.path.join(ordner, "model.bin")):
            return "fail", f"{name} has no model.bin -> check stt.model in config.yaml"
    else:
        try:
            from faster_whisper import download_model
        except Exception as e:  # noqa: BLE001
            return "warn", f"speech model: cannot check (faster-whisper not installed yet: {e})"
        from wf import stt as stt_mod
        name = f"speech model {model}"
        try:
            ordner = download_model(model, local_files_only=True)
        except Exception as e:  # noqa: BLE001
            if not stt_mod._nicht_im_cache(e):
                raise                          # z. B. unbekannter Modellname -> FAIL-Zeile mit Hinweis
            ordner = ""
        if not ordner or not os.path.isfile(os.path.join(ordner, "model.bin")):
            return "warn", (f"{name} is not (completely) in the local cache yet -> downloaded once "
                            f"on the next start (from Hugging Face)")
    if not os.path.isfile(os.path.join(ordner, "tokenizer.json")):
        return "warn", (f"{name} is on this machine, but without tokenizer.json -> faster-whisper "
                        f"fetches the tokenizer from Hugging Face at every start")
    return "ok", f"{name} is on this machine, with tokenizer.json -> loads without internet"


def _check_cleanup_model(cfg: dict) -> tuple[str, str, str]:
    """(Zeilen-Status, Text, roher diagnose()-Statuscode). Der dritte Wert ist fuer
    _check_translate_model (identischer Server -> keine zweite, identische Netzabfrage,
    Nachbesserung Arbeitspaket 4 Runde 1). Nie FAIL: ohne das Aufraeum-Modell liefert die App den
    Rohtext, sie bricht nicht ab (wie App.run()/_llm_startup_notice). Bei llm.enabled: false kein
    Netzaufruf (B5) - das ist eine bewusste Nutzerentscheidung, kein Problem."""
    from wf import cleanup
    c = cleanup.Cleaner(cfg, [])
    if not c.enabled:
        return "ok", "clean-up disabled (llm.enabled: false)", cleanup.Cleaner.DIAG_OK
    status, detail = c.diagnose()
    return ("ok" if status == cleanup.Cleaner.DIAG_OK else "warn"), detail, status


def _check_translate_model(cfg: dict, cleanup_status: str = "") -> tuple[str, str]:
    """Nur WARN, wenn es fehlt (Kriterium). Ist keins eigens gesetzt, gilt das Aufraeum-Modell
    (wf/cleanup.py: translate_model faellt darauf zurueck) - dann kein zweiter Netzwerk-Aufruf.
    cleanup_status = der rohe Status aus _check_cleanup_model: war der Server dort schon nicht
    erreichbar, ist er es hier auch (derselbe base_url) - dann keine zweite, identische Anfrage
    (Hinweis des Pruefers, Nachbesserung Runde 1)."""
    from wf import cleanup
    c = cleanup.Cleaner(cfg, [])
    if not c.enabled:
        return "ok", "clean-up disabled (llm.enabled: false)"
    if c.translate_model == c.model:
        return "ok", f"translation model is the same as the clean-up model ({c.model})"
    if cleanup_status == cleanup.Cleaner.DIAG_UNREACHABLE:
        return "warn", "skipped (same server as the clean-up model, see the check above)"
    status, detail = c.diagnose(c.translate_model)
    return ("ok" if status == cleanup.Cleaner.DIAG_OK else "warn"), detail


def run_doctor() -> int:
    """Fuehrt alle Pruefpunkte aus, druckt je eine Zeile, gibt den Exit-Code zurueck. Jeder
    Pruefpunkt ist einzeln durch try/except abgesichert (Nachbesserung Arbeitspaket 4, Runde 1,
    B2): ein Fehler INNERHALB einer Pruefung wird eine einzelne [FAIL]-Zeile ("<Pruefpunkt> check
    crashed (...)"), reisst aber nicht die folgenden Pruefungen mit ab."""
    faelle = 0
    paket_fehlt = False

    def zeile(status: str, text: str) -> None:
        nonlocal faelle
        if status == "fail":
            faelle += 1
        print(f"[{status.upper()}] {text}")

    def check(fn, label: str, *args, hint: str = "") -> None:
        try:
            status, text = fn(*args)
        except Exception as e:  # noqa: BLE001 - kein Pruefpunkt darf --doctor abstuerzen lassen
            # Nachbesserung Arbeitspaket 4, Runde 2: den Pruefpunkt nennen (nicht bei zwei
            # betroffenen Pruefungen wortgleich) und, wo sinnvoll, den config.yaml-Abschnitt.
            status = "fail"
            text = f"{label} check crashed ({e})"
            if hint:
                text += f" -> {hint}"
        zeile(status, text)

    check(_check_python, "Python version")
    check(_check_os, "OS")
    for module, pip_name, optional in _PACKAGES:
        vorher = faelle
        check(_check_import, f"{module} import", module, pip_name, optional)
        if faelle > vorher:
            paket_fehlt = True

    try:
        status, text, cfg = _check_config()
    except Exception as e:  # noqa: BLE001
        status, text, cfg = "fail", f"config.yaml check crashed ({e})", None
    zeile(status, text)

    if cfg is not None:
        check(_check_dictionary_files, "dictionary/alias files", cfg,
             hint="check dictionary_path/aliases_path in config.yaml")
        check(_check_microphone, "microphone", cfg, hint="check audio.input_device in config.yaml")
        check(_check_gpu, "GPU")
        check(_check_speech_model_cache, "speech model cache", cfg, hint="check stt.model in config.yaml")
        try:
            cm_status, cm_text, cleanup_diag_status = _check_cleanup_model(cfg)
        except Exception as e:  # noqa: BLE001
            cm_status = "fail"
            cm_text = f"clean-up model check crashed ({e}) -> check the llm section of config.yaml"
            cleanup_diag_status = ""
        zeile(cm_status, cm_text)
        check(_check_translate_model, "translation model", cfg, cleanup_diag_status,
             hint="check the llm section of config.yaml")
    else:
        # config.yaml selbst hat schon eine eigene [FAIL]-Zeile - diese Pruefpunkte nicht
        # stillschweigend auslassen (Nachbesserung Arbeitspaket 4, Runde 2).
        for name in _CONFIG_ABHAENGIGE_PRUEFPUNKTE:
            zeile("warn", f"{name}: skipped (config.yaml not loaded)")

    print(f"\n{faelle} check(s) failed." if faelle else "\nNo failures (see any WARN lines above).")
    if paket_fehlt:
        print("Fix: py -m pip install -r requirements.txt")
    return 1 if faelle else 0
