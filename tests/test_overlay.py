"""wf/overlay.py ohne Tk: Zeitschaetzung und die Zustandswechsel des Anzeigefelds (enabled=False).

Vorfall 09.09.2026: ein fehlender Import im Overlay liess die App beim Loslassen haengen. Deshalb
laufen hier alle Zustaende einmal durch. Die Uhr ist ersetzt (Fixture uhr), die Sprache gepinnt."""
from __future__ import annotations

import types

import pytest

from wf import i18n, overlay


@pytest.fixture
def uhr(monkeypatch) -> dict:
    stand = {"jetzt": 1000.0}
    monkeypatch.setattr(overlay, "time", types.SimpleNamespace(time=lambda: stand["jetzt"]))
    return stand


@pytest.fixture(autouse=True)
def englisch(monkeypatch):
    monkeypatch.setattr(i18n, "_current", "en")


@pytest.fixture
def feld(uhr) -> overlay.Overlay:
    o = overlay.Overlay(enabled=False)
    o.start()                                    # ohne Fenster: tut nichts, startet keinen Thread
    return o


# --- estimate_seconds --------------------------------------------------------------------------
def test_schaetzung_formel():
    assert overlay.estimate_seconds(0.0) == pytest.approx(0.70)
    assert overlay.estimate_seconds(10.0) == pytest.approx(1.70)


def test_laufender_abschnitt_zaehlt_wie_der_rest():
    """12.09.2026: der Ring stand bei 95 % und wartete auf genau diesen Abschnitt."""
    assert overlay.estimate_seconds(5.0, 12.0) == pytest.approx(overlay.estimate_seconds(17.0))
    assert overlay.estimate_seconds(5.0, 12.0) > overlay.estimate_seconds(5.0)


@pytest.mark.parametrize("audio_s, gemessen", [(3.2, 1.10), (6.6, 0.88), (12.0, 2.02)])
def test_schaetzung_nah_an_den_messungen(audio_s, gemessen):
    """An echten Diktaten gemessen (data/app.log, 13.09.2026), Fall aus selftest.py."""
    assert abs(overlay.estimate_seconds(audio_s) - gemessen) < 0.8


# --- Zustaende ---------------------------------------------------------------------------------
def test_ohne_fenster_immer_aus():
    assert overlay.Overlay(enabled=False).enabled is False
    o = overlay.Overlay(enabled=False)
    o.start()
    assert o._thread is None and o._state == "hidden"


def test_alle_zustaende_laufen_durch(feld, capsys):
    for schritt in (feld.recording, lambda: feld.processing(2.0), lambda: feld.phase("x"),
                    feld.done, feld.error, lambda: feld.notice("n"), feld.hide):
        schritt()
    protokoll = capsys.readouterr().out
    for zustand in ("recording", "processing", "done", "error", "hidden"):
        assert f"[badge] {zustand}" in protokoll        # Zeitleiste fuer data/app.log


def test_aufnahme(feld, uhr):
    feld.recording()
    assert (feld._state, feld._t0, feld._text) == ("recording", 1000.0, "")


def test_verarbeitung_beginnt_mit_der_stopp_anzeige(feld, uhr):
    """13.09.2026: direkt nach dem Loslassen erst "recording off", dann der Ring."""
    feld.processing(2.0)
    assert (feld._state, feld._eta, feld._pct, feld._text) == ("processing", 2.0, 0.0, i18n.t("badge_listening"))
    assert feld._stop_until == 1000.0 + overlay.Overlay.STOP_HINT_S
    assert 0.2 <= overlay.Overlay.STOP_HINT_S <= 1.0
    feld.recording()                             # neue Aufnahme: keine Stopp-Anzeige
    assert feld._state == "recording"


def test_verarbeitung_eigener_text_und_mindestschaetzung(feld, monkeypatch):
    feld.processing(0.05, text="eigener Text")
    assert feld._eta == 0.3 and feld._text == "eigener Text"
    monkeypatch.setattr(i18n, "_current", "de")
    feld.processing(1.0)
    assert feld._text == "erkenne"               # Text aus der Oberflaechensprache


def test_ring_steigt_und_bleibt_unter_95(feld, uhr):
    feld.processing(2.0)
    werte = []
    for _ in range(10):
        werte.append(feld._elapsed_pct())
        uhr["jetzt"] += 0.5
    assert werte[0] == 0.0 and werte == sorted(werte) and max(werte) == 95.0


def test_phase_nur_waehrend_der_verarbeitung(feld):
    feld.phase("zu frueh")
    assert feld._state == "hidden" and feld._text == ""
    feld.processing(2.0)
    feld.phase("cleaning up")
    assert feld._text == "cleaning up"
    feld.done()
    feld.phase("zu spaet")
    assert feld._state == "done" and feld._text == i18n.t("badge_ready")


def test_phase_zieht_die_restschaetzung_nach(feld, uhr):
    feld.processing(4.0)
    uhr["jetzt"] += 1.0
    feld.phase("cleaning up", eta_left_s=2.5)
    assert feld._eta - (uhr["jetzt"] - feld._t0) == pytest.approx(2.5)
    feld.phase("cleaning up", eta_left_s=0.0)
    assert feld._eta - (uhr["jetzt"] - feld._t0) == pytest.approx(0.3)   # Mindestrest


@pytest.mark.xfail(strict=True, reason="Fehler in wf/overlay.py:75-77: die neue Restschaetzung "
                   "rechnet den Ring so um, als liefe er linear; er laeuft aber exponentiell. War er "
                   "schon bei 95 %, springt er zurueck auf ~88 % (Modul-Doku: 'steigt bis 95 %').")
def test_ring_laeuft_beim_nachziehen_nicht_rueckwaerts(feld, uhr):
    feld.processing(1.0)
    uhr["jetzt"] += 5.0                          # STT dauerte laenger als geschaetzt
    vorher = feld._elapsed_pct()
    feld.phase("cleaning up", eta_left_s=0.5)
    assert feld._elapsed_pct() >= vorher


def test_fertig_fehler_hinweis_verstecken(feld, uhr):
    feld.done()
    assert (feld._state, feld._text, feld._pct, feld._until) == ("done", "Ready - press Ctrl+V", 100.0, 1001.3)
    feld.error()
    assert (feld._state, feld._text, feld._until) == ("error", "Error", 1002.0)
    feld.notice("release to snip", 3.0)
    assert (feld._state, feld._text) == ("notice", "release to snip")
    feld.hide()
    assert feld._state == "hidden"


def test_hinweis_verdraengt_keine_verarbeitung(feld):
    feld.processing(2.0)
    feld.notice("release to snip")
    assert feld._state == "processing"
