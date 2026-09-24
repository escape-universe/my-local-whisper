"""wf/snip.py ohne Bildschirm: der Tastatur-Filter (tap/hold, Haltezeit, Abbruch, Doppeltippen)
mit synthetischen Ereignissen, die Mausklick-Abfrage, Tastennamen, Bilder ablegen und aufraeumen.

Haltezeit und Doppeltippen laufen ueber einen Ersatz-Timer und eine Ersatz-Uhr (Fixtures wecker,
uhr): der Test entscheidet, wann die Haltezeit um ist, statt zu schlafen und auf die Last zu hoffen.
Ein Test laeuft zusaetzlich mit dem echten threading.Timer und wartet dort auf ein Ereignis."""
from __future__ import annotations

import ctypes
import os
import threading
import time
import types
from datetime import datetime

import pytest
from PIL import Image

from wf import snip

RUNTER, HOCH, SYS_RUNTER = 0x0100, 0x0101, 0x0104
SHIFT_R, MENU, TASTE_A = 0xA1, 0x5D, 0x41


class _Daten:
    """Wie die KBDLLHOOKSTRUCT-Daten, die pynput an win32_event_filter gibt."""

    def __init__(self, vk):
        self.vkCode = vk


class _Wecker:
    """Ersatz fuer threading.Timer: laeuft nicht von selbst, der Test loest ihn aus."""

    def __init__(self, interval, function):
        self.interval, self.function = interval, function
        self.daemon = False
        self.gestartet = self.abgebrochen = False

    def start(self):
        self.gestartet = True

    def cancel(self):
        self.abgebrochen = True

    def ausloesen(self):
        if self.gestartet and not self.abgebrochen:
            self.function()


class _Maus:
    """Ersatz fuer KeyWatcher._mouse_clicked_since (echte Klicks kann kein Test garantieren)."""

    def __init__(self, klick: bool = False):
        self.klick, self.aufrufe = klick, []

    def __call__(self, reset: bool = False) -> bool:
        self.aufrufe.append(reset)
        return False if reset else self.klick


@pytest.fixture
def wecker(monkeypatch) -> list[_Wecker]:
    """Alle Timer, die KeyWatcher anlegt, in Reihenfolge."""
    alle: list[_Wecker] = []

    def _neu(interval, function):
        alle.append(_Wecker(interval, function))
        return alle[-1]

    monkeypatch.setattr(snip, "threading", types.SimpleNamespace(
        Timer=_neu, Thread=threading.Thread, Event=threading.Event))
    return alle


@pytest.fixture
def uhr(monkeypatch) -> dict:
    stand = {"jetzt": 1000.0}
    monkeypatch.setattr(snip, "time", types.SimpleNamespace(time=lambda: stand["jetzt"], sleep=time.sleep))
    return stand


def _watcher(key: str = "shift_r", maus: _Maus | None = None, **kw) -> snip.KeyWatcher:
    w = snip.KeyWatcher(key, lambda: None, **kw)
    w._mouse_clicked_since = maus or _Maus()
    return w


def _jobs(w: snip.KeyWatcher) -> list:
    return list(w._jobs.queue)


def _tippen(w: snip.KeyWatcher, vk: int = SHIFT_R) -> None:
    w._filter(RUNTER, _Daten(vk))
    w._filter(HOCH, _Daten(vk))


# --- Betriebsart tap ---------------------------------------------------------------------------
def test_tap_loest_sofort_beim_druecken_aus():
    """11.09.2026: rechte Umschalt-Taste antippen oeffnet die Auswahl, ohne Halten."""
    w = _watcher("shift_r", mode="tap")
    assert w._filter(RUNTER, _Daten(SHIFT_R)) is True
    assert _jobs(w) == ["go"]


def test_tap_auto_repeat_nur_einmal_neuer_druck_wieder():
    w = _watcher("menu", mode="tap")
    for _ in range(3):
        w._filter(RUNTER, _Daten(MENU))          # Druck + Tastenwiederholung
    w._filter(HOCH, _Daten(MENU))
    w._filter(SYS_RUNTER, _Daten(MENU))          # mit gehaltener Alt-Taste: WM_SYSKEYDOWN
    assert _jobs(w) == ["go", "go"]


def test_fremde_tasten_gehen_unveraendert_durch():
    w = _watcher("shift_r", mode="tap")
    assert w._filter(RUNTER, _Daten(TASTE_A)) is True and w._filter(HOCH, _Daten(TASTE_A)) is True
    assert w._filter(RUNTER, object()) is True   # Ereignis ohne vkCode
    assert _jobs(w) == []


@pytest.mark.parametrize("taste, suppress, modus, erwartet", [
    ("shift_r", True, "hold", False),            # Standardtaste: nie verschluckt (Grossbuchstaben!)
    ("shift_r", True, "tap", False),
    ("alt_gr", True, "tap", False),              # Modifikator
    ("menu", True, "tap", True),                 # Taste ohne eigene Aufgabe darf verschluckt werden
    ("menu", True, "hold", False),               # hold = Alltagstaste
    ("menu", False, "tap", False),
])
def test_wann_verschluckt_wird(taste, suppress, modus, erwartet):
    assert snip.KeyWatcher(taste, lambda: None, suppress=suppress, mode=modus)._suppress is erwartet


class _Listener:
    def __init__(self):
        self.unterdrueckt = 0

    def suppress_event(self):
        self.unterdrueckt += 1


def test_nur_die_eigene_taste_wird_unterdrueckt():
    w = _watcher("menu", mode="tap", suppress=True)
    w._listener = _Listener()
    _tippen(w, TASTE_A)
    assert w._listener.unterdrueckt == 0
    _tippen(w, MENU)
    assert w._listener.unterdrueckt == 2 and _jobs(w) == ["go"]


def test_tastenwahl_und_vorgaben():
    assert snip.KeyWatcher("shift_r", lambda: None).vk == 0xA1
    assert snip.KeyWatcher("gibtsnicht", lambda: None).vk == 0xA1     # Rueckfall: rechte Umschalt
    assert snip.KeyWatcher(None, lambda: None).key_name == "shift_r"
    assert snip.KeyWatcher(" MENU ", lambda: None).vk == 0x5D
    assert snip.KEYS["alt_gr"] != snip.KEYS["shift_r"]                 # AltGr: @ € | liegen dort
    assert snip.KeyWatcher("menu", lambda: None, mode="HOLD").mode == "hold"
    assert snip.KeyWatcher("menu", lambda: None, mode="quatsch").mode == "tap"
    assert snip.KeyWatcher("menu", lambda: None, hold_ms=10).hold_s == 0.15


# --- Betriebsart hold --------------------------------------------------------------------------
def test_hold_kurzes_tippen_loest_nicht_aus(wecker):
    """Kurzes Tippen bleibt ein normales Umschalten (Grossbuchstabe bleibt Grossbuchstabe)."""
    w = _watcher("shift_r", mode="hold", hold_ms=200)
    w._filter(RUNTER, _Daten(SHIFT_R))
    assert len(wecker) == 1
    assert (wecker[0].interval, wecker[0].function, wecker[0].gestartet, wecker[0].daemon) == (0.2, w._arm, True, True)
    w._filter(HOCH, _Daten(SHIFT_R))             # vor Ablauf losgelassen
    assert wecker[0].abgebrochen
    wecker[0].ausloesen()                        # abgebrochen = wirkungslos
    assert _jobs(w) == [] and not w._armed


def test_hold_langes_halten_loest_beim_loslassen_aus(wecker):
    angezeigt = []
    maus = _Maus()
    w = _watcher("shift_r", maus, mode="hold", hold_ms=200, on_arm=lambda: angezeigt.append("arm"))
    w._filter(RUNTER, _Daten(SHIFT_R))
    for _ in range(3):
        w._filter(RUNTER, _Daten(SHIFT_R))       # Tastenwiederholung startet keinen neuen Timer
    assert len(wecker) == 1
    wecker[0].ausloesen()                        # Haltezeit erreicht
    assert w._armed and angezeigt == ["arm"] and _jobs(w) == []    # erst das Loslassen loest aus
    w._filter(HOCH, _Daten(SHIFT_R))
    assert _jobs(w) == ["go"] and not w._armed
    assert maus.aufrufe == [True, False]         # beim Druecken zurueckgesetzt, beim Loslassen gefragt


@pytest.mark.parametrize("nach_der_haltezeit", [False, True])
def test_hold_andere_taste_bricht_ab(wecker, nach_der_haltezeit):
    """Umschalt+A ist ein Grossbuchstabe, kein Ausschnitt."""
    w = _watcher("shift_r", mode="hold", hold_ms=200)
    w._filter(RUNTER, _Daten(SHIFT_R))
    if nach_der_haltezeit:
        wecker[0].ausloesen()
    _tippen(w, TASTE_A)
    assert wecker[0].abgebrochen and not w._armed
    wecker[0].ausloesen()
    w._filter(HOCH, _Daten(SHIFT_R))
    assert _jobs(w) == []


def test_hold_mausklick_bricht_ab(wecker):
    """Umschalt+Klick markiert Text, kein Ausschnitt."""
    w = _watcher("shift_r", _Maus(klick=True), mode="hold", hold_ms=200)
    w._filter(RUNTER, _Daten(SHIFT_R))
    wecker[0].ausloesen()
    w._filter(HOCH, _Daten(SHIFT_R))
    assert _jobs(w) == []


def test_hold_fehler_in_der_anzeige_stoert_nicht(wecker, capsys):
    def kaputt():
        raise RuntimeError("Anzeige weg")

    w = _watcher("shift_r", mode="hold", hold_ms=200, on_arm=kaputt)
    w._filter(RUNTER, _Daten(SHIFT_R))
    wecker[0].ausloesen()
    w._filter(HOCH, _Daten(SHIFT_R))
    assert _jobs(w) == ["go"] and "arm error" in capsys.readouterr().out


def test_hold_mit_echtem_timer():
    """Einmal mit dem echten threading.Timer: gewartet wird auf das Ereignis, nicht eine feste Zeit."""
    bereit = threading.Event()
    w = _watcher("shift_r", mode="hold", hold_ms=150, on_arm=bereit.set)
    w._filter(RUNTER, _Daten(SHIFT_R))
    try:
        assert bereit.wait(5), "Haltezeit-Timer hat nicht ausgeloest"
        w._filter(HOCH, _Daten(SHIFT_R))
    finally:
        w._cancel_timer()
    assert _jobs(w) == ["go"]


# --- Doppeltippen (10.09.2026) -----------------------------------------------------------------
def _zweimal(w: snip.KeyWatcher, uhr: dict, pause_s: float, buchstabe: bool = False) -> list:
    for i in range(2):
        w._filter(RUNTER, _Daten(SHIFT_R))
        if buchstabe:
            _tippen(w, TASTE_A)
        uhr["jetzt"] += 0.04
        w._filter(HOCH, _Daten(SHIFT_R))
        if i == 0:
            uhr["jetzt"] += pause_s
    return _jobs(w)


@pytest.mark.parametrize("pause_s, buchstabe, erwartet", [
    (0.15, False, ["doppelt"]),                  # zweimal schnell = ganzer Bildschirm
    (0.7, False, []),                            # zwei langsame Tipper
    (0.15, True, []),                            # zwei Grossbuchstaben hintereinander
])
def test_doppeltippen(wecker, uhr, pause_s, buchstabe, erwartet):
    w = _watcher("shift_r", mode="hold", hold_ms=250, on_double=lambda: None, double_tap_ms=400)
    assert _zweimal(w, uhr, pause_s, buchstabe) == erwartet


def test_dreimal_schnell_ist_einmal_doppelt(wecker, uhr):
    w = _watcher("shift_r", mode="hold", hold_ms=250, on_double=lambda: None, double_tap_ms=400)
    for _ in range(3):
        _tippen(w)
        uhr["jetzt"] += 0.1
    assert _jobs(w) == ["doppelt"]


def test_ohne_doppel_rueckruf_kein_doppeltippen(wecker, uhr):
    w = _watcher("shift_r", mode="hold", hold_ms=250)
    assert _zweimal(w, uhr, 0.15) == []


# --- Mausklick-Abfrage, mit gefaelschtem ctypes.windll -----------------------------------------
def test_mausklick_abfrage_prueft_alle_drei_tasten(monkeypatch):
    zustand = {0x01: 0, 0x02: 0, 0x04: 0}
    user32 = types.SimpleNamespace(GetAsyncKeyState=lambda vk: zustand[vk])
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(user32=user32), raising=False)
    assert snip.KeyWatcher._mouse_clicked_since() is False
    zustand[0x04] = 0x0001                       # Mitte: seit der letzten Abfrage gedrueckt
    assert snip.KeyWatcher._mouse_clicked_since() is True
    assert snip.KeyWatcher._mouse_clicked_since(reset=True) is False
    zustand[0x04], zustand[0x02] = 0, 0x8000     # rechts: gerade unten
    assert snip.KeyWatcher._mouse_clicked_since() is True


# --- Tastennamen, Bilder ablegen und aufraeumen ------------------------------------------------
def test_key_label():
    assert snip.key_label("shift_r") == "right Shift key"
    assert snip.key_label("menu").startswith("context-menu key")
    assert snip.key_label("f9") == "f9"


class _FesteZeit(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 24, 13, 5, 9)


def test_save_image_name_und_kein_ueberschreiben(tmp_path, monkeypatch):
    monkeypatch.setattr(snip, "datetime", _FesteZeit)
    bild = Image.new("RGB", (40, 30), (10, 20, 30))
    ordner = tmp_path / "bilder" / "neu"              # wird angelegt
    dateien = [snip.save_image(bild, ordner) for _ in range(3)]
    assert [d.name for d in dateien] == ["2026-09-24_13-05-09.png", "2026-09-24_13-05-09_2.png",
                                         "2026-09-24_13-05-09_3.png"]
    with Image.open(dateien[0]) as geladen:
        assert geladen.size == (40, 30) and geladen.format == "PNG"


def test_cleanup_old(tmp_path):
    alt, frisch, notiz = tmp_path / "alt.png", tmp_path / "frisch.png", tmp_path / "notiz.txt"
    for p in (alt, frisch, notiz):
        p.write_bytes(b"x")
    vor_20_tagen = time.time() - 20 * 86400
    for p in (alt, notiz):
        os.utime(p, (vor_20_tagen, vor_20_tagen))
    assert snip.cleanup_old(tmp_path, 0) == 0 and alt.exists()        # 0 = nie loeschen
    assert snip.cleanup_old(tmp_path, 14) == 1
    assert not alt.exists() and frisch.exists() and notiz.exists()    # nur alte PNGs
    assert snip.cleanup_old(tmp_path / "fehlt", 14) == 0
