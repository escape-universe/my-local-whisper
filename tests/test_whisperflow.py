"""whisperflow.py ohne Modelle: Anhaenge-Entscheidung, Zeitstempel im Protokoll, Verwerfen,
Umschalt-Modus und die Reihenfolge der Endverarbeitung (Faelle aus selftest.py); dazu die
Konsolen-Ausgaben beim Umschalten und der sichtbare Produktname in Skripten und Selbsttest.
Seit Arbeitspaket 7: state.json atomar, Verlauf im Dauerbetrieb, Tray-Einstellungen und Autostart,
Windows-Meldung und der Start in main() (eine Instanz, kaputte Einstellungen). Die Aufnahmen selbst
(Abschnitte je Aufnahme) stehen in tests/test_aufnahmen.py."""
from __future__ import annotations

import ctypes
import io
import re
import subprocess
import sys
import threading
import time
import types
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import whisperflow as W
from wf import cleanup as cleanup_mod
from wf import i18n, overlay

# --- Pipeline.append_decision (Entscheidung 08.09.2026) ----------------------------------------
LETZTER = {"text": "Hallo Welt.", "mode": "clipboard", "ts": 1000.0}


@pytest.mark.parametrize("letzter, jetzt, ablage, fenster, erwartet", [
    (LETZTER, 1030.0, "Hallo Welt.", 60, True),                      # im Fenster, Ablage unveraendert
    (LETZTER, 1060.0, "Hallo Welt.", 60, True),                      # genau am Rand
    (LETZTER, 1070.0, "Hallo Welt.", 60, False),                     # Fenster abgelaufen
    (LETZTER, 1030.0, "etwas anderes", 60, False),                   # inzwischen anderes kopiert
    (LETZTER, 1030.0, None, 60, False),                              # Ablage nicht lesbar
    ({**LETZTER, "mode": "pasted"}, 1030.0, "Hallo Welt.", 60, False),   # eingefuegt: nie anhaengen
    (LETZTER, 1030.0, "Hallo Welt.", 0, False),                      # Fenster 0 = aus
    (None, 1030.0, "x", 60, False),                                  # kein Vorgaenger
])
def test_append_decision(letzter, jetzt, ablage, fenster, erwartet):
    assert W.Pipeline.append_decision(letzter, jetzt, ablage, fenster) is erwartet


# --- _Stamped: Protokoll der fensterlosen Instanz ----------------------------------------------
UHRZEIT = r"\d\d:\d\d:\d\d "


def test_jede_zeile_bekommt_eine_uhrzeit_teilzeilen_nicht_doppelt():
    puffer = io.StringIO()
    st = W._Stamped(puffer)
    assert st.write("erste Zeile\nzweite") == len("erste Zeile\nzweite")
    st.write(" Zeile weiter\n")
    st.write("\n")                                # Leerzeile bleibt leer
    st.write("dritte\n")
    zeilen = puffer.getvalue().split("\n")
    assert re.fullmatch(UHRZEIT + "erste Zeile", zeilen[0])
    assert re.fullmatch(UHRZEIT + "zweite Zeile weiter", zeilen[1])
    assert zeilen[2] == ""
    assert re.fullmatch(UHRZEIT + "dritte", zeilen[3])


def test_leeres_schreiben_und_flush():
    class _Datei(io.StringIO):
        geleert = 0

        def flush(self):
            self.geleert += 1

    d = _Datei()
    st = W._Stamped(d)
    assert st.write("") == 0 and d.getvalue() == ""
    st.write("x\n")
    st.flush()
    assert d.geleert >= 2                          # jedes write leert sofort (Absturz-sicher)


# --- App: Verwerfen und Umschalt-Modus ---------------------------------------------------------
def _app(**felder) -> W.App:
    app = W.App.__new__(W.App)                     # ohne Mikrofon und Modelle
    app.__dict__.update(felder)
    return app


@pytest.mark.parametrize("max_s, generation, dauer, verworfen", [
    (0.0, 2, 600.0, True),        # neue Aufnahme verwirft auch eine 10-Minuten-Rede (Standard)
    (0.0, 1, 600.0, False),       # das laufende Diktat selbst gilt weiter
    (30.0, 2, 600.0, False),      # mit Laengen-Ausnahme waere die lange Rede geliefert worden
    (30.0, 2, 5.0, True),         # kurze Aufnahme wird auch mit Ausnahme verworfen
])
def test_verwerfen(max_s, generation, dauer, verworfen):
    app = _app(discard_on_new=True, discard_max_s=max_s, _generation=generation, _pending={1: dauer})
    assert app._is_cancelled(1) is verworfen


def test_verwerfen_abgeschaltet():
    assert _app(discard_on_new=False, discard_max_s=0.0, _generation=5, _pending={})._is_cancelled(1) is False


# --- App.wants_all_monitors: fullscreen_scope (Arbeitspaket 6) ---------------------------------
@pytest.mark.parametrize("scope, erwartet", [
    ("monitor", False), ("Monitor", False), ("", False), (None, False), ("weiss nicht", False),
    ("all", True), ("ALL", True), (" all ", True), ("alle", True), ("Alle", True),
])
def test_wants_all_monitors_deutsch_und_englisch(scope, erwartet):
    """Bisher wurde nur das deutsche 'alle' erkannt - ein Nutzer, der 'all' schreibt, bekam
    still nur den Monitor unter der Maus statt den ganzen virtuellen Desktop."""
    assert W.App.wants_all_monitors(scope) is erwartet


def test_umschalt_modus_druecken_startet_loslassen_nichts_druecken_stoppt():
    ablauf: list[str] = []

    class _Recorder:
        is_recording = False

    app = _app(_enabled=True, toggle_mode=True, _recorder=_Recorder())
    app._start_recording = lambda: (ablauf.append("start"), setattr(_Recorder, "is_recording", True))
    app._stop_recording = lambda: (ablauf.append("stop"), setattr(_Recorder, "is_recording", False))
    for taste in (app._on_press, app._on_release, app._on_press, app._on_release):
        taste()
    assert ablauf == ["start", "stop"]
    app.toggle_mode = False                        # halten: druecken = start, loslassen = stop
    app._on_press()
    app._on_release()
    assert ablauf == ["start", "stop", "start", "stop"]
    app._enabled = False
    app._on_press()
    assert ablauf == ["start", "stop", "start", "stop"]   # deaktiviert: Druecken tut nichts


# --- Pipeline.process_audio: Reihenfolge der Endverarbeitung (12.09.2026) ----------------------
@pytest.fixture
def pipeline():
    ablauf: list[str] = []
    P = W.Pipeline.__new__(W.Pipeline)             # ohne Whisper und LLM
    P.overlay = overlay.Overlay(enabled=False)
    P.last_language = "de"
    P.transcriber = type("T", (), {"language": "de"})()
    P.aliases = type("A", (), {"fix": staticmethod(lambda t: (t, []))})()
    P.translate_to = ""
    P.tray = None
    P.cfg = {}
    P.transcribe = lambda arr: (ablauf.append("stt"), "rest text")[1]
    P.cleaner = type("C", (), {"clean": staticmethod(
        lambda t, cat, lang: (ablauf.append("cleanup"), (t.upper(), True))[1])})()
    P.ablauf = ablauf
    return P


CTX = {"category": "default", "process": "x"}
STILLE = np.zeros(16000, dtype=np.float32)


def test_abschnitte_werden_erst_nach_der_stt_des_rests_abgeholt(pipeline):
    def abschnitte():
        pipeline.ablauf.append("prefix")
        return "ABSCHNITT EINS."

    res = pipeline.process_audio(STILLE, do_inject=False, ctx=CTX, prefix_cleaned=abschnitte)
    assert pipeline.ablauf == ["stt", "cleanup", "prefix"]
    assert res["cleaned"] == "ABSCHNITT EINS. REST TEXT" and res["raw"] == "rest text"
    assert res["was_cleaned"] is True and "delivered" not in res


def test_ohne_rest_kommen_die_abschnitte_trotzdem(pipeline):
    pipeline.transcribe = lambda arr: (pipeline.ablauf.append("stt"), "")[1]
    res = pipeline.process_audio(STILLE, do_inject=False, ctx=CTX, prefix_cleaned=lambda: "ABSCHNITT EINS.")
    assert res["cleaned"] == "ABSCHNITT EINS." and pipeline.ablauf == ["stt"]
    assert pipeline.process_audio(STILLE, do_inject=False, ctx=CTX, prefix_cleaned="ALT.")["cleaned"] == "ALT."


def test_leeres_transkript_und_verworfen(pipeline):
    pipeline.transcribe = lambda arr: ""
    assert pipeline.process_audio(STILLE, do_inject=False, ctx=CTX)["note"] == "leeres Transkript"
    res = pipeline.process_audio(STILLE, do_inject=False, ctx=CTX, is_cancelled=lambda: True)
    assert res["note"].startswith("verworfen") and "cleaned" not in res


# --- App._llm_startup_notice(): Konsole + Tray-Text je Diagnose-Status (Arbeitspaket 4) ---------
def _app_mit_diagnose(status: str, detail: str, model: str = "qwen2.5:3b-instruct",
                      enabled: bool = True, native: bool = True) -> tuple[W.App, list]:
    aufrufe: list = []
    cleaner = types.SimpleNamespace(
        diagnose=lambda: (aufrufe.append(1), (status, detail))[1], model=model, enabled=enabled,
        native=native)
    return _app(pipeline=types.SimpleNamespace(cleaner=cleaner)), aufrufe


def test_llm_startup_notice_ok_ist_still(capsys):
    app, _ = _app_mit_diagnose(cleanup_mod.Cleaner.DIAG_OK, "model qwen2.5:3b-instruct is loaded")
    assert app._llm_startup_notice(llm_reachable=False) == ""
    assert capsys.readouterr().out == ""


def test_llm_startup_notice_unbekannt_ist_still(capsys):
    """Kriterium: "unbekannt" behauptet nichts - keine Konsolenzeile, keine Tray-Meldung."""
    app, _ = _app_mit_diagnose(cleanup_mod.Cleaner.DIAG_UNKNOWN, "endpoint has no /models list")
    assert app._llm_startup_notice(llm_reachable=False) == ""
    assert capsys.readouterr().out == ""


def test_llm_startup_notice_nicht_erreichbar(monkeypatch, capsys):
    monkeypatch.setattr(i18n, "_current", "en")
    app, _ = _app_mit_diagnose(cleanup_mod.Cleaner.DIAG_UNREACHABLE, "Ollama not reachable at http://x")
    hinweis = app._llm_startup_notice(llm_reachable=False)
    assert "WARN" in capsys.readouterr().out
    assert hinweis == i18n.t("note_llm_unreachable")


def test_llm_startup_notice_modell_fehlt_nennt_die_abhilfe(monkeypatch, capsys):
    """Konsolenzeile mit Abhilfe (Kriterium, Beispiel "ollama pull qwen2.5:3b-instruct")."""
    monkeypatch.setattr(i18n, "_current", "en")
    app, _ = _app_mit_diagnose(cleanup_mod.Cleaner.DIAG_MODEL_MISSING,
                               "model qwen2.5:3b-instruct is not pulled -> ollama pull qwen2.5:3b-instruct")
    hinweis = app._llm_startup_notice(llm_reachable=False)
    assert "ollama pull qwen2.5:3b-instruct" in capsys.readouterr().out
    assert hinweis == i18n.t("note_llm_model_missing", model="qwen2.5:3b-instruct")


def test_llm_startup_notice_modell_fehlt_openai_nennt_nicht_ollama_pull(monkeypatch, capsys):
    """Nachbesserung Arbeitspaket 4, Runde 1 (B4): 'ollama pull' ist nur bei Ollama selbst eine
    sinnvolle Abhilfe - ein anderer OpenAI-kompatibler Server (z. B. llama.cpp) braucht einen
    eigenen Tray-Text (Hinweis des Pruefers: 'pruefe llm.model / den Server')."""
    monkeypatch.setattr(i18n, "_current", "en")
    app, _ = _app_mit_diagnose(cleanup_mod.Cleaner.DIAG_MODEL_MISSING,
                               "model qwen2.5:3b-instruct was not found -> check llm.model or the server",
                               native=False)
    hinweis = app._llm_startup_notice(llm_reachable=False)
    assert "ollama pull" not in capsys.readouterr().out
    assert hinweis == i18n.t("note_llm_model_missing_other", model="qwen2.5:3b-instruct")
    assert "ollama" not in hinweis.lower()


def test_llm_startup_notice_ueberspringt_diagnose_wenn_warmup_schon_lief(capsys):
    """Nachbesserung Arbeitspaket 4, Runde 1 (B4): ein erfolgreicher Warm-up (ein echter
    Chat-Aufruf) beweist schon, dass das Modell nutzbar ist - diagnose() (ein zusaetzlicher
    HTTP-Aufruf, der bei Single-Model-Servern wie llama.cpp faelschlich 'Modell fehlt' melden
    kann) laeuft dann gar nicht erst."""
    app, aufrufe = _app_mit_diagnose(cleanup_mod.Cleaner.DIAG_MODEL_MISSING, "sollte nicht erscheinen")
    assert app._llm_startup_notice(llm_reachable=True) == ""
    assert capsys.readouterr().out == ""
    assert aufrufe == []                             # diagnose() wurde gar nicht erst gerufen


def test_llm_startup_notice_uebersprungen_wenn_cleanup_abgeschaltet(capsys):
    """Nachbesserung Arbeitspaket 4, Runde 1 (B5): llm.enabled: false ist eine bewusste
    Entscheidung - kein WARN, kein Netzaufruf, auch wenn der Warm-up (folgerichtig) fehlschlug."""
    app, aufrufe = _app_mit_diagnose(cleanup_mod.Cleaner.DIAG_UNREACHABLE, "sollte nicht erscheinen",
                                     enabled=False)
    assert app._llm_startup_notice(llm_reachable=False) == ""
    assert capsys.readouterr().out == ""
    assert aufrufe == []


# --- Konsole englisch, sichtbarer Produktname (24.09.2026) --------------------------------------
def test_umschalten_meldet_sich_englisch_in_der_konsole(monkeypatch, capsys):
    """Projektkonvention (CLAUDE.md): Konsolen-Ausgaben englisch. Bis 24.09.2026 waren diese
    zwei deutsch ("Uebersetzungsmodus: alles wird nach ... uebersetzt", "UI-Sprache: ...")."""
    monkeypatch.setattr(i18n, "_current", "en")                 # _set_ui_language stellt sie um
    monkeypatch.setattr(W, "_load_state", lambda: {})           # state.json bleibt unberuehrt
    monkeypatch.setattr(W, "_save_state", lambda state: None)
    monkeypatch.setattr(W.snip_mod, "set_hint", lambda text: None)
    app = _app(tray=None, pipeline=types.SimpleNamespace(translate_to=""))
    app._set_translate_to("it")
    app._set_ui_language("de")
    zeilen = capsys.readouterr().out.splitlines()
    assert zeilen == ["[app] translation on - everything is translated into Italian.",
                      "[app] UI language: de (setting: de)"]


_START_STOP = ("start-whisperflow.bat", "stop-whisperflow.bat", "testen-konsole.bat")


@pytest.mark.parametrize("datei", _START_STOP)
def test_skripte_zeigen_den_produktnamen_und_finden_laufende_instanzen(datei):
    """Sichtbar heisst das Programm my-local-whisper, nicht mehr whisperflow-local. Die Suche
    nach laufenden Instanzen bleibt bei *whisperflow.py*, so heisst die Datei weiterhin."""
    text = (Path(W.__file__).parent / datei).read_text(encoding="utf-8")
    echos = [z for z in text.splitlines() if z.lower().startswith("echo")]
    assert any("my-local-whisper" in z.lower() for z in echos)
    assert not [z for z in echos if "whisperflow" in z.lower()]
    assert "-like '*whisperflow.py*'" in text


def test_selbsttest_und_moduldoku_tragen_den_produktnamen():
    selbsttest = (Path(W.__file__).parent / "selftest.py").read_text(encoding="utf-8")
    assert '"=== my-local-whisper Selbsttests ===\\n"' in selbsttest and "whisperflow-local" not in selbsttest
    assert W.__doc__.startswith("my-local-whisper — ")


# --- Standard-Bilderordner: config.yaml, whisperflow.py, tools/neue-bilder.py (Arbeitspaket 6) --
def test_snip_ordner_faellt_auf_data_images_zurueck_wie_config_yaml():
    """config.yaml sagt data/images; whisperflow.py fiel bisher auf data/bilder zurueck, wenn
    snip.folder fehlt (tools/neue-bilder.py ebenso, siehe tests/test_neue_bilder.py) - uneinheitlich.
    App() laesst sich hier nicht bauen (laedt Whisper/Ollama), deshalb die Vorgabe im Quelltext
    direkt geprueft, wie schon bei test_selbsttest_und_moduldoku_tragen_den_produktnamen."""
    quelle = Path(W.__file__).read_text(encoding="utf-8")
    assert 'sn.get("folder", "data/images")' in quelle
    assert '"data/bilder"' not in quelle


# --- snip.key: leerer Wert ohne Warnung, Startzeile zeigt den AKTIVEN Namen (Nachbesserung Runde 1) --
def test_snip_key_leerer_wert_ergibt_den_standard_nicht_die_zeichenkette_none():
    """sn.get("key", DEFAULT) gibt bei key: null (Python None) das None selbst zurueck, str(None)
    waere dann "None" gewesen - ein "unbekannter Tastenname" fuer KeyWatcher, mit ueberfluessiger
    Warnung. sn.get("key") or DEFAULT umgeht das. App() laesst sich hier nicht bauen (siehe oben),
    deshalb wieder die Quelltext-Pruefung."""
    quelle = Path(W.__file__).read_text(encoding="utf-8")
    assert 'sn.get("key") or snip_mod.DEFAULT_KEY' in quelle
    assert 'sn.get("key", snip_mod.DEFAULT_KEY)' not in quelle


def test_snip_startzeile_beschriftet_den_aktiven_namen_nicht_den_rohwert():
    """Nach einem Tippfehler in snip.key faellt KeyWatcher (mit Warnung) auf den Standard zurueck -
    die Startzeile muss dann den AKTIVEN Namen zeigen (self._snip_watcher.key_name), nicht mehr
    den nicht mehr aktiven Rohwert aus der Konfiguration (self.snip_key)."""
    quelle = Path(W.__file__).read_text(encoding="utf-8")
    assert "key_label(self._snip_watcher.key_name)" in quelle
    assert "key_label(self.snip_key)" not in quelle


def test_startzeilen_nennen_die_wirksame_diktat_taste():
    """Arbeitspaket 7: nach einem unbekannten hotkey.key warnt HoldToTalk und hoert auf ctrl_r - die
    Startzeile von App.run() und die Kalibrier-Anleitung duerfen dann nicht den Tippfehler nennen.
    App.run() laedt Modelle, deshalb wie oben die Quelltext-Pruefung."""
    quelle = Path(W.__file__).read_text(encoding="utf-8")
    assert "[app] ready. '{hk.key_name}'" in quelle and "[app] ready. '{key}'" not in quelle
    kalibrierung = (Path(W.__file__).parent / "calibrate.py").read_text(encoding="utf-8")
    assert "Hold '{hk.key_name}'" in kalibrierung and "Hold '{key}'" not in kalibrierung


# --- do_snip()/do_fullscreen() Ende-zu-Ende (Nachbesserung Runde 1, B3) -------------------------
# Kriterium 7/8 wurden bisher nur an den Bausteinen geprueft (encode_png, save_image_async,
# wants_all_monitors), nie am tatsaechlichen Aufruf in do_snip()/do_fullscreen() selbst - genau
# dort lagen die Befunde des Arbeitspakets (doppelt kodiert, Datei im kritischen Pfad, nur
# "alle"). grab_screen/select_region/to_clipboard/monitor_rect werden hier ersetzt (echte
# Windows-APIs); encode_png und save_image_async laufen ECHT gegen tmp_path.
def _snip_app(tmp_path, **felder) -> W.App:
    basis = dict(pipeline=types.SimpleNamespace(overlay=overlay.Overlay(enabled=False)),
                 tray=None, _snip_lock=threading.Lock(), snip_folder=tmp_path,
                 snip_beep=False, snip_full_scope="monitor")
    basis.update(felder)
    return _app(**basis)


def _erfasse_hintergrund_threads(monkeypatch) -> list:
    """save_image_async() selbst wird NICHT ersetzt (es soll ja echt gegen tmp_path laufen) -
    dieser Helfer haengt sich nur an, um den entstandenen Thread deterministisch abzuwarten
    (join(), kein sleep)."""
    threads: list = []
    orig = W.snip_mod.save_image_async

    def _mit_erfasstem_thread(image, folder, png_bytes=None):
        pfad, thread = orig(image, folder, png_bytes)
        threads.append(thread)
        return pfad, thread

    monkeypatch.setattr(W.snip_mod, "save_image_async", _mit_erfasstem_thread)
    return threads


def test_do_snip_kodiert_einmal_und_clipboard_bekommt_dieselben_bytes_wie_die_datei(tmp_path, monkeypatch):
    bild = Image.new("RGB", (20, 16), (10, 20, 30))
    monkeypatch.setattr(W.snip_mod, "grab_screen", lambda: (bild, 0, 0))
    monkeypatch.setattr(W.snip_mod, "select_region", lambda img, ox, oy: (0, 0, 8, 8))
    clip_aufrufe: list = []
    monkeypatch.setattr(W.snip_mod, "to_clipboard",
                        lambda img, png=None: (clip_aufrufe.append(png), True)[1])
    encode_aufrufe: list = []
    orig_encode = W.snip_mod.encode_png
    monkeypatch.setattr(W.snip_mod, "encode_png",
                        lambda img: (encode_aufrufe.append(1), orig_encode(img))[1])
    threads = _erfasse_hintergrund_threads(monkeypatch)

    app = _snip_app(tmp_path)
    grund = app.do_snip()

    assert grund == ""
    assert len(encode_aufrufe) == 1                     # PNG genau einmal kodiert (Kriterium 7)
    assert len(clip_aufrufe) == 1 and clip_aufrufe[0] is not None
    for t in threads:
        t.join(timeout=5)
    [datei] = list(tmp_path.glob("*.png"))
    assert datei.read_bytes() == clip_aufrufe[0]        # Zwischenablage und Datei: dieselben Bytes


def test_do_snip_kehrt_zurueck_bevor_die_datei_geschrieben_ist(tmp_path, monkeypatch):
    bild = Image.new("RGB", (10, 10), (1, 2, 3))
    monkeypatch.setattr(W.snip_mod, "grab_screen", lambda: (bild, 0, 0))
    monkeypatch.setattr(W.snip_mod, "select_region", lambda img, ox, oy: (0, 0, 5, 5))
    monkeypatch.setattr(W.snip_mod, "to_clipboard", lambda img, png=None: True)
    frei = threading.Event()
    orig_write = W.snip_mod._write_png

    def _erst_wenn_freigegeben(path, image, png_bytes):
        frei.wait(5)
        orig_write(path, image, png_bytes)

    monkeypatch.setattr(W.snip_mod, "_write_png", _erst_wenn_freigegeben)
    threads = _erfasse_hintergrund_threads(monkeypatch)

    app = _snip_app(tmp_path)
    grund = app.do_snip()

    assert grund == ""
    assert threads and threads[0].is_alive()            # der Schreib-Thread haengt noch
    assert not list(tmp_path.glob("*.png"))             # "fertig" wartet nicht auf die Datei
    frei.set()
    threads[0].join(timeout=5)
    assert list(tmp_path.glob("*.png"))


def test_do_fullscreen_all_schneidet_nicht_auf_einen_monitor_zu(tmp_path, monkeypatch):
    bild = Image.new("RGB", (30, 20), (5, 5, 5))
    monkeypatch.setattr(W.snip_mod, "grab_screen", lambda: (bild, 0, 0))
    monitor_aufrufe: list = []
    monkeypatch.setattr(W.snip_mod, "monitor_rect", lambda: (monitor_aufrufe.append(1), None)[1])
    monkeypatch.setattr(W.snip_mod, "to_clipboard", lambda img, png=None: True)
    monkeypatch.setattr(W, "time", types.SimpleNamespace(sleep=lambda s: None, time=time.time))
    threads = _erfasse_hintergrund_threads(monkeypatch)

    app = _snip_app(tmp_path, snip_full_scope="all")
    grund = app.do_fullscreen()

    assert grund == ""
    assert monitor_aufrufe == []                        # "all": monitor_rect() wird NICHT gerufen
    for t in threads:
        t.join(timeout=5)
    [datei] = list(tmp_path.glob("*.png"))
    with Image.open(datei) as geladen:
        assert geladen.size == (30, 20)                 # unveraendert, das ganze (gefaelschte) Bild


def test_do_fullscreen_monitor_schneidet_zu(tmp_path, monkeypatch):
    bild = Image.new("RGB", (30, 20), (5, 5, 5))
    monkeypatch.setattr(W.snip_mod, "grab_screen", lambda: (bild, 0, 0))
    monitor_aufrufe: list = []
    monkeypatch.setattr(W.snip_mod, "monitor_rect",
                        lambda: (monitor_aufrufe.append(1), (0, 0, 10, 8))[1])
    monkeypatch.setattr(W.snip_mod, "to_clipboard", lambda img, png=None: True)
    monkeypatch.setattr(W, "time", types.SimpleNamespace(sleep=lambda s: None, time=time.time))
    threads = _erfasse_hintergrund_threads(monkeypatch)

    app = _snip_app(tmp_path, snip_full_scope="monitor")
    grund = app.do_fullscreen()

    assert grund == ""
    assert len(monitor_aufrufe) == 1                    # "monitor": monitor_rect() wird gerufen
    for t in threads:
        t.join(timeout=5)
    [datei] = list(tmp_path.glob("*.png"))
    with Image.open(datei) as geladen:
        assert geladen.size == (10, 8)                  # auf den (gefaelschten) Monitor zugeschnitten


# --- state.json atomar (Arbeitspaket 7, 25.09.2026) ------------------------------------------------
@pytest.fixture
def zustand(tmp_path, monkeypatch) -> Path:
    pfad = tmp_path / "state.json"
    monkeypatch.setattr(W, "STATE_PATH", pfad)
    return pfad


def _dateien(ordner: Path) -> list[str]:
    return sorted(p.name for p in ordner.iterdir())


def test_state_json_schreiben_und_lesen_ohne_zwischendatei(zustand):
    W._save_state({"toggle_mode": True, "ui_lang": "de"})
    W._save_state({"toggle_mode": False, "ui_lang": "it"})          # ersetzt die vorhandene Datei
    assert W._load_state() == {"toggle_mode": False, "ui_lang": "it"}
    assert _dateien(zustand.parent) == ["state.json"]


def test_fehler_mitten_im_schreiben_laesst_die_alte_datei_heil(zustand, capsys):
    """Ein Wert, den UTF-8 nicht kodieren kann (einzelnes Surrogat), laesst das Schreiben MITTEN
    im Vorgang scheitern - wie ein Absturz beim Schreiben. Bis 25.09.2026 (write_text) war die
    Datei in dem Moment schon geleert: danach leer, _load_state() gab still {} zurueck."""
    W._save_state({"toggle_mode": True, "ui_lang": "de"})
    alt = zustand.read_bytes()
    W._save_state({"toggle_mode": True, "ui_lang": "\ud800"})
    assert zustand.read_bytes() == alt
    assert W._load_state() == {"toggle_mode": True, "ui_lang": "de"}
    assert "[state] not saved" in capsys.readouterr().out
    assert _dateien(zustand.parent) == ["state.json"]                 # keine Zwischendatei liegen geblieben


def test_scheitert_das_ersetzen_bleibt_die_alte_datei(zustand, monkeypatch, capsys):
    """Zum Beispiel haelt ein anderes Programm state.json gerade offen (Windows: kein Ersetzen)."""
    W._save_state({"ui_lang": "de"})

    def gesperrt(quelle, ziel):
        raise PermissionError("Datei in Benutzung")

    monkeypatch.setattr(W.os, "replace", gesperrt)
    W._save_state({"ui_lang": "ru"})
    assert W._load_state() == {"ui_lang": "de"}
    assert "Datei in Benutzung" in capsys.readouterr().out
    assert _dateien(zustand.parent) == ["state.json"]


def test_ersetzen_passiert_erst_nach_vollstaendigem_schreiben(zustand, monkeypatch):
    """Reihenfolge: temporaere Datei komplett geschrieben und auf der Platte (fsync), erst dann
    os.replace - im selben Ordner wie state.json."""
    ablauf = []
    echt_fsync, echt_replace = W.os.fsync, W.os.replace
    monkeypatch.setattr(W.os, "fsync", lambda fd: (ablauf.append("fsync"), echt_fsync(fd))[1])

    def ersetzen(quelle, ziel):
        ablauf.append(("replace", Path(quelle).parent == Path(ziel).parent,
                       Path(quelle).read_text(encoding="utf-8")))
        echt_replace(quelle, ziel)

    monkeypatch.setattr(W.os, "replace", ersetzen)
    W._save_state({"toggle_mode": True})
    assert ablauf == ["fsync", ("replace", True, '{\n "toggle_mode": true\n}')]


# --- Verlauf im Dauerbetrieb (Arbeitspaket 7, 25.09.2026) --------------------------------------------
class _Uhr(datetime):
    """Kuenstliche Uhr fuer whisperflow.datetime: now() liefert _Uhr.jetzt."""
    jetzt = datetime(2026, 9, 1, 9, 0, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.jetzt


@pytest.fixture
def verlauf(tmp_path, monkeypatch):
    """Pipeline ohne Modelle mit Verlauf in tmp_path (14 Tage), die Uhr steht auf dem 01.09.2026."""
    monkeypatch.setattr(W, "datetime", _Uhr)
    monkeypatch.setattr(_Uhr, "jetzt", datetime(2026, 9, 1, 9, 0, 0))
    P = W.Pipeline.__new__(W.Pipeline)
    P.history_path = tmp_path / "data" / "history.log"
    P._ui = {"history_keep_days": 14}
    P._history_pruned_on = None
    P._history_lock = threading.Lock()
    gekuerzt: list = []
    echt = P._prune_history
    P._prune_history = lambda: (gekuerzt.append(_Uhr.jetzt), echt())[1]
    return P, gekuerzt


def test_verlauf_wird_im_dauerbetrieb_gekuerzt_hoechstens_einmal_am_tag(verlauf):
    P, gekuerzt = verlauf
    P._prune_history()                                       # Start (warmup) am 01.09.
    P._remember("erster Tag morgens")
    _Uhr.jetzt = datetime(2026, 9, 1, 18, 0)
    P._remember("erster Tag abends")
    assert len(gekuerzt) == 1                                # derselbe Tag: Datei nicht noch mal gelesen
    _Uhr.jetzt = datetime(2026, 9, 16, 8, 0)                 # App lief durch, 15 Tage spaeter
    P._remember("Tag 16")
    assert gekuerzt[1:] == [datetime(2026, 9, 16, 8, 0)]
    text = P.history_path.read_text(encoding="utf-8")
    assert "erster Tag" not in text                          # aelter als 14 Tage: weg
    assert text == "### 2026-09-16T08:00:00\nTag 16\n\n"
    _Uhr.jetzt = datetime(2026, 9, 16, 23, 59)
    P._remember("Tag 16 spaet")
    assert len(gekuerzt) == 2                                # am 16.09. kein zweites Mal
    assert P.last_text() == "Tag 16 spaet"


def test_verlauf_innerhalb_der_frist_bleibt_unangetastet(verlauf):
    P, gekuerzt = verlauf
    P._remember("frisch")
    _Uhr.jetzt = datetime(2026, 9, 10, 12, 0)                # neuer Tag, aber nichts ist abgelaufen
    P._remember("auch frisch")
    assert len(gekuerzt) == 2
    assert P.history_path.read_text(encoding="utf-8") == (
        "### 2026-09-01T09:00:00\nfrisch\n\n### 2026-09-10T12:00:00\nauch frisch\n\n")
    assert _dateien(P.history_path.parent) == ["history.log"]


def test_kaputter_verlauf_haelt_das_diktat_nicht_auf(verlauf, capsys):
    """Laesst sich der Verlauf nicht lesen (kein UTF-8), meldet das Kuerzen sich in der Konsole,
    der neue Eintrag steht trotzdem in der Datei und _remember wirft nichts (sonst fiele die
    Lieferung des Diktats aus, sie kommt in process_audio erst danach)."""
    P, _ = verlauf
    P.history_path.parent.mkdir(parents=True)
    P.history_path.write_bytes("### 2026-08-01T10:00:00\nB\xfcro\n\n".encode("cp1252"))
    P._remember("neu")
    assert "[history] not pruned" in capsys.readouterr().out
    assert P.history_path.read_bytes().endswith("neu\n\n".encode("utf-8"))


def test_ohne_verlauf_wird_nichts_gekuerzt(verlauf):
    P, gekuerzt = verlauf
    P.history_path = None
    P._remember("x")
    assert gekuerzt == []


# --- Tray -> Einstellungen / Mit Windows starten (Arbeitspaket 7, 25.09.2026) -----------------------
class _TrayMeldungen:
    def __init__(self):
        self.meldungen: list[str] = []

    def notify(self, message, title="my-local-whisper"):
        self.meldungen.append(message)


@pytest.fixture
def einstellungen(tmp_path, monkeypatch):
    """config.local.yaml in tmp_path, os.startfile/notepad ersetzt (nie echt aufrufen)."""
    monkeypatch.setattr(i18n, "_current", "en")
    lokal = tmp_path / "config.local.yaml"
    monkeypatch.setattr(W.config_mod, "LOCAL_CONFIG_PATH", lokal)
    geoeffnet: list = []
    monkeypatch.setattr(W.os, "startfile", lambda pfad: geoeffnet.append(("startfile", pfad)), raising=False)
    monkeypatch.setattr(subprocess, "Popen", lambda args: geoeffnet.append(("popen", args)))
    tray = _TrayMeldungen()
    return _app(tray=tray), lokal, geoeffnet, tray


def test_einstellungen_legt_aus_der_vorlage_an_oeffnet_und_sagt_neu_starten(einstellungen):
    app, lokal, geoeffnet, tray = einstellungen
    app._open_settings()
    assert lokal.read_text(encoding="utf-8") == W.config_mod.LOCAL_EXAMPLE_PATH.read_text(encoding="utf-8")
    assert geoeffnet == [("startfile", str(lokal))]
    assert tray.meldungen == [i18n.t("note_settings_restart", file="config.local.yaml")]
    assert "restart" in tray.meldungen[0]


def test_einstellungen_ueberschreibt_die_eigene_datei_nie(einstellungen):
    app, lokal, geoeffnet, tray = einstellungen
    lokal.write_text("hotkey:\n  key: f8\n", encoding="utf-8")
    assert app.open_settings() == ""
    assert lokal.read_text(encoding="utf-8") == "hotkey:\n  key: f8\n"


def test_einstellungen_ohne_verknuepfung_fuer_yaml_oeffnet_notepad(einstellungen, monkeypatch):
    app, lokal, geoeffnet, tray = einstellungen

    def keine_verknuepfung(pfad):
        raise OSError("[WinError 1155] No application is associated with the specified file")

    monkeypatch.setattr(W.os, "startfile", keine_verknuepfung, raising=False)
    assert app.open_settings() == ""
    assert geoeffnet == [("popen", ["notepad.exe", str(lokal)])]


def test_einstellungen_nicht_zu_oeffnen_wird_eine_meldung(einstellungen, monkeypatch):
    app, lokal, geoeffnet, tray = einstellungen
    monkeypatch.delattr(W.os, "startfile", raising=False)            # wie ohne Windows

    def kein_notepad(args):
        raise FileNotFoundError("notepad.exe nicht gefunden")

    monkeypatch.setattr(subprocess, "Popen", kein_notepad)
    app._open_settings()
    assert tray.meldungen == [i18n.t("note_settings_open_failed", error="notepad.exe nicht gefunden")]


def test_einstellungen_ordner_nicht_beschreibbar_wird_eine_meldung(einstellungen, monkeypatch):
    app, lokal, geoeffnet, tray = einstellungen

    def schreibgeschuetzt(*a, **kw):
        raise PermissionError("schreibgeschuetzt")

    monkeypatch.setattr(W.config_mod, "ensure_local_config", schreibgeschuetzt)
    assert app.open_settings() == i18n.t("note_settings_open_failed", error="schreibgeschuetzt")
    assert geoeffnet == []


@pytest.mark.parametrize("an, grund, schluessel", [
    (True, "", "note_autostart_on"), (False, "", "note_autostart_off"),
    (True, "Zugriff verweigert", "note_autostart_failed")])
def test_autostart_umschalten_meldet_sich_im_tray(monkeypatch, capsys, an, grund, schluessel):
    monkeypatch.setattr(i18n, "_current", "de")
    gerufen = []
    monkeypatch.setattr(W.autostart_mod, "set_enabled", lambda on: (gerufen.append(on), grund)[1])
    tray = _TrayMeldungen()
    _app(tray=tray)._set_autostart(an)
    assert gerufen == [an]
    assert tray.meldungen == [i18n.t(schluessel, error=grund)]
    assert capsys.readouterr().out.startswith("[autostart] ")


# --- Windows-Meldung ohne Tray (zweiter Start, kaputte Einstellungen) ---------------------------------
def test_message_box_ruft_messageboxw(monkeypatch):
    aufrufe = []
    user32 = types.SimpleNamespace(MessageBoxW=lambda *args: aufrufe.append(args) or 1)
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(user32=user32), raising=False)
    W._message_box("Hallo")
    W._message_box("Kaputt", error=True)
    assert [a[:3] for a in aufrufe] == [(None, "Hallo", "my-local-whisper"), (None, "Kaputt", "my-local-whisper")]
    assert aufrufe[0][3] & 0x40 and not aufrufe[0][3] & 0x10          # Info-Symbol (mit Ton)
    assert aufrufe[1][3] & 0x10                                        # Fehler-Symbol
    assert all(a[3] & 0x40000 for a in aufrufe)                        # vor allen Fenstern


def test_message_box_ohne_windows_still(monkeypatch):
    monkeypatch.delattr(ctypes, "windll", raising=False)
    W._message_box("Hallo")                                            # kein Fehler


# --- main(): nur eine Instanz, nur beim normalen Start, vor den Modellen ---------------------------
@pytest.fixture
def start(monkeypatch, capsys):
    """main() ohne echte App und ohne Windows. ablauf haelt fest, was in welcher Reihenfolge
    geschah; frei["wert"] ist, was instance.acquire() sagt."""
    monkeypatch.setattr(i18n, "_current", "en")
    ablauf: list = []
    frei = {"wert": True, "zustand": {"ui_lang": "en"}}
    monkeypatch.setattr(W, "_load_state", lambda: dict(frei["zustand"]))
    monkeypatch.setattr(W, "_message_box", lambda text, error=False: ablauf.append(("meldung", text, error)))
    monkeypatch.setattr(W.instance_mod, "acquire", lambda: (ablauf.append("acquire"), frei["wert"])[1])

    class _App:
        """Steht fuer die echte App: deren __init__ baut Whisper und das Aufraeum-Modell."""

        def __init__(self, cfg, use_tray=True):
            ablauf.append(("App", use_tray, cfg["hotkey"]["key"]))

        def run(self):
            ablauf.append("run")

    monkeypatch.setattr(W, "App", _App)

    def starten(*argv) -> int:
        monkeypatch.setattr(sys, "argv", ["whisperflow.py", *argv])
        return W.main()

    return starten, ablauf, frei


def test_normaler_start_prueft_die_instanz_vor_der_app(start):
    starten, ablauf, _ = start
    assert starten() == 0
    assert ablauf == ["acquire", ("App", True, "ctrl_r"), "run"]
    ablauf.clear()
    assert starten("--no-tray") == 0
    assert ablauf == ["acquire", ("App", False, "ctrl_r"), "run"]


@pytest.mark.parametrize("sprache", ["en", "de"])
def test_zweiter_start_beendet_sich_sofort_ohne_modelle(start, capsys, sprache):
    starten, ablauf, frei = start
    frei["wert"] = False
    frei["zustand"] = {"ui_lang": sprache}
    assert starten() == 0
    assert ablauf == ["acquire", ("meldung", i18n.TABLE[sprache]["note_already_running"], False)]
    assert "already running" in capsys.readouterr().out


def test_werkzeug_aufrufe_pruefen_keine_instanz(start, monkeypatch):
    starten, ablauf, _ = start
    import calibrate
    import selftest

    from wf import doctor
    monkeypatch.setattr(W.audio_mod, "list_devices", lambda: "keine Geraete")
    monkeypatch.setattr(doctor, "run_doctor", lambda: ablauf.append("doctor") or 0)
    monkeypatch.setattr(selftest, "run_selftests", lambda: ablauf.append("selftest") or 0)
    monkeypatch.setattr(calibrate, "run_calibration", lambda cfg, nur: ablauf.append("calibrate") or 0)
    monkeypatch.setattr(W, "cmd_clean_text", lambda cfg, text: ablauf.append("clean-text") or 0)
    monkeypatch.setattr(W, "cmd_transcribe_file", lambda cfg, pfad: ablauf.append("transcribe-file") or 0)
    for argv in (["--list-devices"], ["--doctor"], ["--selftest"], ["--calibrate"],
                 ["--clean-text", "hallo"], ["--transcribe-file", "x.wav"]):
        assert starten(*argv) == 0, argv
    assert ablauf == ["doctor", "selftest", "calibrate", "clean-text", "transcribe-file"]


def test_start_nennt_die_eigenen_schluessel_und_nimmt_ihre_werte(start, tmp_path, monkeypatch, capsys):
    starten, ablauf, _ = start
    lokal = tmp_path / "config.local.yaml"
    lokal.write_text('hotkey:\n  key: "f8"\naudio:\n  input_device: "Geheimes Headset"\n', encoding="utf-8")
    monkeypatch.setattr(W.config_mod, "LOCAL_CONFIG_PATH", lokal)
    assert starten() == 0
    assert ablauf == ["acquire", ("App", True, "f8"), "run"]
    out = capsys.readouterr().out
    assert "[config] config.local.yaml overrides: hotkey.key, audio.input_device" in out
    assert "Geheimes Headset" not in out


@pytest.mark.parametrize("argv", [[], ["--selftest"], ["--calibrate"]])
def test_kaputte_config_local_klare_meldung_statt_absturz(start, tmp_path, monkeypatch, capsys, argv):
    starten, ablauf, _ = start
    lokal = tmp_path / "config.local.yaml"
    lokal.write_text('hotkey:\n  key: "f8"\n mode: toggle\n', encoding="utf-8")
    monkeypatch.setattr(W.config_mod, "LOCAL_CONFIG_PATH", lokal)
    assert starten(*argv) == 2
    out = capsys.readouterr().out
    assert "[config] ERROR: config.local.yaml, line 3, column" in out
    [(art, text, fehler)] = ablauf                                  # keine Instanzpruefung, keine App
    assert art == "meldung" and fehler is True
    assert text.startswith(i18n.TABLE["en"]["note_config_unreadable"].split("{error}")[0])
    assert "config.local.yaml, line 3" in text
