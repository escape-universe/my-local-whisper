"""whisperflow.App: jede Aufnahme behaelt ihre Abschnitte, ihren Streamer und ihre Kategorie
(Arbeitspaket 7, Teil B, 25.09.2026).

Befund: lange Diktate werden schon waehrend der Aufnahme in Abschnitten verarbeitet. Eine neue
Aufnahme leerte bis dahin die Abschnitte und ersetzte Streamer und Kategorie, waehrend die vorige
noch verarbeitet wurde. Mit ui.discard_pending_on_new_recording: false oder
discard_only_if_shorter_than_s > 0 (README: "a 15-minute talk ... is delivered anyway") kam nach
Loslassen und sofortigem erneutem Druecken von der langen Rede nur der letzte Rest an, dafuer mit
den Abschnitten der NEUEN Aufnahme, und die Verarbeitung wartete bis zu 120 s auf deren Streamer.

Die App wird echt gebaut (App.__init__, mit den Attrappen aus tests/conftest.py). Ersetzt sind nur
Mikrofon (_Mikro), Whisper/Aufraeum-Modell (_Modelle), die Lieferung (Zwischenablage), Fenster-
und Fokusabfrage und Toene - nichts davon darf hier echt laufen, auch nicht auf Windows. Die
Threads laufen echt; synchronisiert wird ueber Events, nicht ueber feste Wartezeiten."""
from __future__ import annotations

import queue
import threading
import time
import types

import numpy as np
import pytest

import whisperflow as W
from wf import config, i18n

SR = 16000
#: Markenwert im Audio -> was "Whisper" daraus macht.
TEXTE = {1.0: "Eins.", 2.0: "Zwei.", 3.0: "Drei.", 5.0: "Neu.", 10.0: "Rest eins.", 20.0: "Rest zwei."}


def _audio(marke: float) -> np.ndarray:
    return np.full(SR, marke, dtype=np.float32)


class _Mikro:
    """Recorder-Ersatz. Abschnitte legt der Test in die Warteschlange, wie Abschnitte, die
    drain_until_silence() an einer Sprechpause abschneidet; stop() liefert den Rest."""
    samplerate = SR

    def __init__(self):
        self.is_recording = False
        self.limit_hit = False
        self.captured_frames = 1           # Audio kommt an -> Anzeige sofort
        self.elapsed_seconds = 0.0
        self.abschnitte: queue.Queue = queue.Queue()
        self.rest = _audio(10.0)
        self.start_fehler: Exception | None = None

    def start(self):
        if self.start_fehler:
            raise self.start_fehler
        self.is_recording = True

    def stop(self):
        self.is_recording = False
        return self.rest

    def drain_until_silence(self, min_seconds, min_silence_s):
        try:
            return self.abschnitte.get_nowait()
        except queue.Empty:
            return None


class _Modelle:
    """Whisper und Aufraeum-Modell. Abschnitt "Drei" (Marke 3.0) haengt in der Transkription, bis
    der Test ihn freigibt: der Abschnitt, der beim Loslassen noch in Arbeit ist."""

    def __init__(self):
        self.drei_begonnen = threading.Event()
        self.drei_frei = threading.Event()
        self.bereinigt: list[tuple[str, str]] = []       # (Text, Kategorie) der Streamer-Abschnitte
        self._bedingung = threading.Condition()

    def transcribe(self, arr):
        marke = float(arr[0])
        if marke == 3.0:
            self.drei_begonnen.set()
            self.drei_frei.wait(10)
        return TEXTE[marke]

    def clean_text(self, text, kategorie):
        with self._bedingung:
            self.bereinigt.append((text, kategorie))
            self._bedingung.notify_all()
        return text, []

    def warte_bereinigt(self, text: str, anzahl: int = 1, sekunden: float = 5) -> bool:
        """Bis der Streamer text insgesamt anzahl-mal bereinigt hat."""
        with self._bedingung:
            return self._bedingung.wait_for(
                lambda: sum(t == text for t, _ in self.bereinigt) >= anzahl, sekunden)


class _Lieferung:
    """Statt Zwischenablage/Einfuegen: merkt sich jeden gelieferten Text."""

    def __init__(self):
        self.texte: list[str] = []
        self._ereignisse = {rest: threading.Event() for rest in ("Rest eins.", "Rest zwei.")}

    def __call__(self, text, ctx):
        self.texte.append(text)
        for rest, ev in self._ereignisse.items():
            if text.endswith(rest):
                ev.set()
        return "clipboard"

    def warte(self, rest: str, sekunden: float = 5) -> bool:
        return self._ereignisse[rest].wait(sekunden)

    def mit_rest(self, rest: str) -> list[str]:
        return [t for t in self.texte if t.endswith(rest)]


@pytest.fixture
def bau_app(monkeypatch, tmp_path):
    """bau_app(**ui) -> (app, mikro, modelle, lieferung, fenster). ui ergaenzt den ui-Abschnitt
    der ausgelieferten config.yaml."""
    monkeypatch.setattr(i18n, "_current", "en")
    monkeypatch.setattr(W, "STATE_PATH", tmp_path / "state.json")      # keine echte state.json
    monkeypatch.setattr(W, "_beep", lambda kind="ok": None)             # kein winsound
    monkeypatch.setattr(W.snip_mod, "set_hint", lambda text: None)
    fenster = {"category": "email"}
    monkeypatch.setattr(W.context_mod, "foreground_info",
                        lambda cfg: {"category": fenster["category"], "process": "test", "hwnd": 1})
    monkeypatch.setattr(W.focus_mod, "editable_focus", lambda: {"editable": False, "why": "Test"})
    # Der Streamer schlaeft 0,5 s, wenn kein Abschnitt da ist; hier nur kurz (kein Warten im Test).
    monkeypatch.setattr(W, "time", types.SimpleNamespace(time=time.time, strftime=time.strftime,
                                                         sleep=lambda s: time.sleep(min(s, 0.005))))

    def bauen(**ui):
        cfg = config.load_config()
        cfg["stt"]["device"] = "cpu"                   # keine CUDA-/DLL-Pruefung
        cfg["ui"].update({"language": "en", "cursor_badge": False, "history_file": None, **ui})
        app = W.App(cfg, use_tray=False)
        mikro, modelle, lieferung = _Mikro(), _Modelle(), _Lieferung()
        app._recorder = mikro
        app.pipeline.transcribe = modelle.transcribe
        app.pipeline.clean_text = modelle.clean_text
        app.pipeline.cleaner = types.SimpleNamespace(clean=lambda text, kategorie, sprache: (text, True))
        app.pipeline.aliases = types.SimpleNamespace(fix=lambda text: (text, []))
        app.pipeline._deliver = lieferung
        return app, mikro, modelle, lieferung, fenster

    return bauen


def _mit_tor(app) -> tuple[threading.Event, list[threading.Thread]]:
    """Die Verarbeitung von Aufnahme 1 beginnt erst, wenn das Tor offen ist: so laeuft sie sicher
    NACH dem Start von Aufnahme 2 an (der Nutzer drueckt sofort wieder, bevor der Verarbeitungs-
    Thread richtig losgelegt hat). Merkt sich die Verarbeitungs-Threads zum Abwarten."""
    tor = threading.Event()
    threads: list[threading.Thread] = []
    echt = app._process

    def _process(arr, ctx, gen):
        threads.append(threading.current_thread())
        if gen == 1:
            tor.wait(10)
        echt(arr, ctx, gen)

    app._process = _process
    return tor, threads


@pytest.mark.parametrize("ui", [
    {"discard_pending_on_new_recording": False},
    {"discard_pending_on_new_recording": True, "discard_only_if_shorter_than_s": 30},
], ids=["nie_verwerfen", "lange_rede_ausgenommen"])
def test_sofort_neue_aufnahme_verliert_nichts_von_der_vorigen(bau_app, ui):
    app, mikro, modelle, lieferung, fenster = bau_app(**ui)
    tor, threads = _mit_tor(app)
    try:
        # Aufnahme 1: eine 15-Minuten-Rede. Zwei Abschnitte sind fertig, der dritte ist beim
        # Loslassen noch in Arbeit.
        app._start_recording()
        app._rec_start -= 900
        for marke in (1.0, 2.0):
            mikro.abschnitte.put(_audio(marke))
            assert modelle.warte_bereinigt(TEXTE[marke])
        mikro.abschnitte.put(_audio(3.0))
        assert modelle.drei_begonnen.wait(5)
        app._stop_recording()                      # loslassen ...
        fenster["category"] = "chat"               # ... anderes Fenster ...
        mikro.rest = _audio(20.0)
        app._start_recording()                     # ... und sofort wieder druecken: Aufnahme 2
        mikro.abschnitte.put(_audio(5.0))
        assert modelle.warte_bereinigt("Neu.")

        tor.set()                                  # jetzt erst laeuft die Verarbeitung von 1 an
        modelle.drei_frei.set()                    # der Abschnitt in Arbeit wird fertig
        # Aufnahme 2 laeuft weiter, ihr Streamer also auch: die Verarbeitung von 1 darf nicht auf
        # ihn warten (vorher: bis zu 120 s).
        geliefert_waehrend_aufnahme_2 = lieferung.warte("Rest eins.") and mikro.is_recording

        app._stop_recording()                      # Aufnahme 2 endet
        assert lieferung.warte("Rest zwei.", 10)
    finally:
        tor.set()
        modelle.drei_frei.set()
        if mikro.is_recording:
            app._stop_recording()
        for t in list(threads):
            t.join(10)
        lieferung.warte("Rest eins.", 10)

    assert lieferung.mit_rest("Rest eins.") == ["Eins. Zwei. Drei. Rest eins."]   # alle Abschnitte von 1
    assert lieferung.mit_rest("Rest zwei.") == ["Neu. Rest zwei."]                # keiner von 1 in 2
    assert geliefert_waehrend_aufnahme_2, "die Verarbeitung von 1 hat auf den Streamer von 2 gewartet"
    # Der Abschnitt in Arbeit wurde mit der Kategorie SEINER Aufnahme bereinigt, nicht mit der
    # des Fensters, in dem Aufnahme 2 begann.
    assert ("Drei.", "email") in modelle.bereinigt and ("Neu.", "chat") in modelle.bereinigt
    assert len(lieferung.texte) == 2


def test_mit_standard_einstellungen_verwirft_eine_neue_aufnahme_die_vorige_weiter(bau_app):
    """config.yaml: discard_pending_on_new_recording: true, discard_only_if_shorter_than_s: 0.
    Wie bisher: loslassen und sofort wieder druecken heisst "von vorn"."""
    app, mikro, modelle, lieferung, fenster = bau_app()
    assert app.discard_on_new is True and app.discard_max_s == 0
    tor, threads = _mit_tor(app)
    try:
        app._start_recording()
        mikro.abschnitte.put(_audio(1.0))
        assert modelle.warte_bereinigt("Eins.")
        app._stop_recording()
        mikro.rest = _audio(20.0)
        app._start_recording()
        tor.set()
        threads[0].join(10)                        # Verarbeitung von 1: verworfen, nichts geliefert
        assert lieferung.texte == []
        mikro.abschnitte.put(_audio(5.0))
        assert modelle.warte_bereinigt("Neu.")
        app._stop_recording()
        assert lieferung.warte("Rest zwei.", 10)
    finally:
        tor.set()
        if mikro.is_recording:
            app._stop_recording()
        for t in list(threads):
            t.join(10)
    assert lieferung.texte == ["Neu. Rest zwei."]


def test_nach_vielen_diktaten_bleibt_nichts_liegen(bau_app):
    """Aufraeumen: nach der Verarbeitung haelt die App zu keiner Aufnahme mehr etwas fest."""
    app, mikro, modelle, lieferung, fenster = bau_app(discard_pending_on_new_recording=False)
    tor, threads = _mit_tor(app)
    tor.set()                                      # hier nur die Threads mitschreiben
    for runde in range(1, 6):
        app._start_recording()
        mikro.abschnitte.put(_audio(1.0))
        assert modelle.warte_bereinigt("Eins.", runde)
        app._stop_recording()
    for t in list(threads):
        t.join(10)
    assert lieferung.texte == ["Eins. Rest eins."] * 5
    assert app._recs == {} and app._pending == {}


def test_scheitert_der_aufnahme_start_bleibt_kein_eintrag(bau_app):
    app, mikro, *_ = bau_app()
    mikro.start_fehler = OSError("kein Mikrofon")
    with pytest.raises(OSError):
        app._start_recording()
    assert app._recs == {}
