"""whisperflow.py ohne Modelle: Anhaenge-Entscheidung, Zeitstempel im Protokoll, Verwerfen,
Umschalt-Modus und die Reihenfolge der Endverarbeitung (Faelle aus selftest.py)."""
from __future__ import annotations

import io
import re

import numpy as np
import pytest

import whisperflow as W
from wf import overlay

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
