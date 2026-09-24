"""wf/snip.py ohne Bildschirm: der Tastatur-Filter (tap/hold, Haltezeit, Abbruch, Doppeltippen)
mit synthetischen Ereignissen, die Mausklick-Abfrage, Tastennamen, Bilder ablegen und aufraeumen.

Haltezeit und Doppeltippen laufen ueber einen Ersatz-Timer und eine Ersatz-Uhr (Fixtures wecker,
uhr): der Test entscheidet, wann die Haltezeit um ist, statt zu schlafen und auf die Last zu hoffen.
Ein Test laeuft zusaetzlich mit dem echten threading.Timer und wartet dort auf ein Ereignis."""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import types
from datetime import datetime

import pytest
from PIL import Image

from wf import snip

RUNTER, HOCH, SYS_RUNTER = 0x0100, 0x0101, 0x0104
SHIFT_R, MENU, TASTE_A = 0xA1, 0x5D, 0x41
SHIFT_L, ALT_GR, LCTRL_PHANTOM = 0xA0, 0xA5, 0xA2   # fuer die Kombinationen weiter unten


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


@pytest.fixture
def win32clipboard_attrappe(monkeypatch) -> dict:
    """to_clipboard() importiert win32clipboard sich selbst (import win32clipboard, innerhalb der
    Funktion) - ohne diese Attrappe wuerde ein Test auf einem Windows-Rechner mit echtem pywin32
    installiert (dort laeuft conftest.py's eigene Attrappe NICHT) die echte Zwischenablage
    ueberschreiben (Nachbesserung Runde 1, Hinweis des Pruefers). Gibt die "Ablage" zurueck (Format
    -> Bytes), damit ein Test nachsehen kann, was hineingelegt wurde."""
    ablage: dict = {}
    fake = types.SimpleNamespace(
        OpenClipboard=lambda *a, **k: None, CloseClipboard=lambda: None,
        EmptyClipboard=ablage.clear,
        SetClipboardData=lambda fmt, data: ablage.__setitem__(fmt, data),
        RegisterClipboardFormat=lambda name: 0xC000)
    monkeypatch.setitem(sys.modules, "win32clipboard", fake)
    return ablage


def _watcher(key: str = "shift_r", maus: _Maus | None = None, **kw) -> snip.KeyWatcher:
    w = snip.KeyWatcher(key, lambda: None, **kw)
    w._mouse_clicked_since = maus or _Maus()
    # Kein Test drueckt hier wirklich eine Taste - auf einem echten Windows-Rechner (Windows-CI,
    # Nutzer-PC) meldet GetAsyncKeyState fuer eine nur synthetisch geschickte Taste "oben", und
    # _reconcile_down_vks() (B1) wuerde jede gemerkte Taste sofort wieder austragen (Nachbesserung
    # Runde 2, B5). Der eine Test, der die Erkennung "verloren gegangenes Loslassen" gezielt
    # prueft, ueberschreibt das danach selbst (siehe test_verlorenes_loslassen_...).
    w._physically_down = lambda vk: None
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
    ("alt_gr+shift", True, "tap", False),        # Kombination: unterdrueckt grundsaetzlich nichts
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
    # Arbeitspaket 6: der Standard ist jetzt die Kombination AltGr+Umschalt, nicht mehr die
    # rechte Umschalt-Taste allein - und der Rueckfall bei einem unbekannten Namen ist derselbe
    # neue Standard (nicht mehr still die rechte Umschalt-Taste, siehe test_unbekannter_name_...).
    w_unbekannt = snip.KeyWatcher("gibtsnicht", lambda: None)
    assert w_unbekannt.key_name == snip.DEFAULT_KEY and w_unbekannt.vk is None
    assert snip.KeyWatcher(None, lambda: None).key_name == "alt_gr+shift" == snip.DEFAULT_KEY
    assert snip.KeyWatcher(" MENU ", lambda: None).vk == 0x5D
    assert snip.KEYS["alt_gr"] != snip.KEYS["shift_r"]                 # AltGr: @ € | liegen dort
    assert snip.KeyWatcher("menu", lambda: None, mode="HOLD").mode == "hold"
    assert snip.KeyWatcher("menu", lambda: None, mode="quatsch").mode == "tap"
    assert snip.KeyWatcher("menu", lambda: None, hold_ms=10).hold_s == 0.15


# --- Unbekannter Tastenname: Warnung + Rueckfall (Arbeitspaket 6) -------------------------------
def test_unbekannter_name_warnt_laut_und_faellt_auf_den_neuen_standard_zurueck(capsys):
    w = snip.KeyWatcher("gibtsnicht+shift", lambda: None)
    ausgabe = capsys.readouterr().out
    assert "WARNING" in ausgabe and "gibtsnicht+shift" in ausgabe
    for name in ("shift", "alt_gr", "menu", "f1", "ctrl_r"):    # ein paar gueltige Namen genannt
        assert name in ausgabe, ausgabe
    assert w.key_name == snip.DEFAULT_KEY == "alt_gr+shift"


def test_kein_wert_gesetzt_ist_keine_fehlkonfiguration(capsys):
    """Leer/nicht gesetzt ist "nichts eingestellt", kein Tippfehler - keine Warnung dafuer."""
    for wert in (None, "", "   "):
        assert snip.KeyWatcher(wert, lambda: None).key_name == snip.DEFAULT_KEY
    assert "WARNING" not in capsys.readouterr().out


# --- Neue Einzeltasten und Gruppen (Arbeitspaket 6) ----------------------------------------------
@pytest.mark.parametrize("name, vk", [
    ("print_screen", 0x2C), ("insert", 0x2D), ("f1", 0x70), ("f24", 0x87),
    ("ctrl_r", 0xA3), ("ctrl_l", 0xA2), ("shift_l", 0xA0), ("alt_l", 0xA4), ("alt_r", 0xA5),
    ("cmd_l", 0x5B),
])
def test_neue_einzeltasten_sind_bekannt(name, vk):
    assert snip.KeyWatcher(name, lambda: None).vk == vk


@pytest.mark.parametrize("gruppe, erwartet", [
    ("shift", {0xA0, 0xA1, 0x10}), ("ctrl", {0xA2, 0xA3}), ("alt", {0xA4, 0xA5}),
    ("win", {0x5B, 0x5C}), ("cmd", {0x5B, 0x5C}),
])
def test_gruppen_umfassen_beide_seiten(gruppe, erwartet):
    assert snip.KEY_GROUPS[gruppe] == frozenset(erwartet)


def test_key_label_kombination():
    assert snip.key_label("alt_gr+shift") == "AltGr + Shift"
    assert snip.key_label("ctrl_r+shift_r") == "right Ctrl + right Shift key"
    # Leerzeichen um "+" muessen weg, sonst passt der Teil nicht mehr in _LABELS und bleibt roh
    # stehen (Nachbesserung Runde 1, Hinweis des Pruefers).
    assert snip.key_label("alt_gr + shift") == "AltGr + Shift"
    assert snip.key_label(" Alt_Gr  +  SHIFT ") == "AltGr + Shift"


# --- Kombinationen, Betriebsart tap (Arbeitspaket 6: neuer Standard alt_gr+shift) ----------------
# Diese Tests benutzen bewusst die LINKE Umschalt-Taste (SHIFT_L) fuer die Kombination, nicht
# SHIFT_R: der ALTE Code faellt bei einem unbekannten Namen wie "alt_gr+shift" still auf
# KEYS["shift_r"] (0xA1) zurueck (der Befund dieses Arbeitspakets) - mit SHIFT_R im Testablauf
# waeren diese Tests also selbst am alten Stand (zufaellig) gruen. SHIFT_L umgeht das und macht
# die Gegenprobe (Kriterium 3, Protokoll) aussagekraeftig.
def test_kombination_tap_loest_erst_aus_wenn_beide_unten_sind():
    """Windows schickt VOR dem echten AltGr-Tastendruck ein unechtes 'linke Strg unten' (0xA2) -
    das darf die Kombination weder verhindern noch als fremde Taste zaehlen (Kriterium 2)."""
    w = _watcher("alt_gr+shift", mode="tap")
    w._filter(RUNTER, _Daten(LCTRL_PHANTOM))         # unecht, kommt vor dem eigentlichen AltGr
    assert _jobs(w) == []
    w._filter(RUNTER, _Daten(ALT_GR))
    assert _jobs(w) == []                             # AltGr allein: noch nicht vollstaendig
    w._filter(RUNTER, _Daten(SHIFT_L))
    assert _jobs(w) == ["go"]                         # jetzt vollstaendig -> genau ein Ausloesen


def test_kombination_tap_tastenwiederholung_loest_nicht_erneut_aus():
    w = _watcher("alt_gr+shift", mode="tap")
    for _ in range(3):
        w._filter(RUNTER, _Daten(ALT_GR))            # Wiederholung: die Taste war schon unten
    w._filter(RUNTER, _Daten(SHIFT_L))
    for _ in range(3):
        w._filter(RUNTER, _Daten(SHIFT_L))           # Wiederholung der zweiten Taste
        w._filter(RUNTER, _Daten(LCTRL_PHANTOM))     # unecht, mehrfach, waehrend gehalten
    assert _jobs(w) == ["go"]


def test_kombination_tap_nach_loslassen_wieder_ausloesbar():
    w = _watcher("alt_gr+shift", mode="tap")
    w._filter(RUNTER, _Daten(ALT_GR))
    w._filter(RUNTER, _Daten(SHIFT_L))
    assert _jobs(w) == ["go"]
    w._filter(HOCH, _Daten(SHIFT_L))                 # Kombination geloest (eine Taste reicht)
    assert _jobs(w) == ["go"]                         # kein zweites Ausloesen durchs Loslassen
    w._filter(RUNTER, _Daten(SHIFT_L))               # wieder vollstaendig
    assert _jobs(w) == ["go", "go"]
    w._filter(HOCH, _Daten(ALT_GR))
    w._filter(HOCH, _Daten(SHIFT_L))


def test_kombination_shift_gruppe_akzeptiert_links_oder_rechts():
    """Die andere Seite: hier darf SHIFT_R durchaus vorkommen, es geht ja genau darum, dass beide
    Seiten funktionieren (siehe test_kombination_ctrl_r_plus_shift_r fuer die Gegenprobe mit
    SHIFT_R alleine gegen den alten Rueckfall)."""
    w = _watcher("alt_gr+shift", mode="tap")
    w._filter(RUNTER, _Daten(ALT_GR))
    w._filter(RUNTER, _Daten(SHIFT_R))
    assert _jobs(w) == ["go"]
    w._filter(HOCH, _Daten(SHIFT_R))
    w._filter(HOCH, _Daten(ALT_GR))
    w2 = _watcher("alt_gr+shift", mode="tap")
    w2._filter(RUNTER, _Daten(ALT_GR))
    w2._filter(RUNTER, _Daten(SHIFT_L))               # LINKE Umschalt-Taste
    assert _jobs(w2) == ["go"]


def test_kombination_ctrl_r_plus_shift_r():
    """Aus der Aufgabenstellung: 'keine Buchstaben noetig' - zwei einzelne, neu benannte Tasten.
    Rechte Umschalt-Taste ALLEIN darf nicht ausloesen: der ALTE Code kennt "ctrl_r+shift_r" nicht
    und faellt still auf KEYS["shift_r"] zurueck - dort loest die rechte Umschalt-Taste allein
    sofort aus, hier (neu) erst zusammen mit der rechten Strg-Taste."""
    w = _watcher("ctrl_r+shift_r", mode="tap")
    w._filter(RUNTER, _Daten(SHIFT_R))
    assert _jobs(w) == []
    w._filter(RUNTER, _Daten(0xA3))                   # jetzt komplett: rechte Strg-Taste dazu
    assert _jobs(w) == ["go"]


# --- Verlorenes Loslass-Ereignis (Nachbesserung Runde 1, B1) -------------------------------------
def test_verlorenes_loslassen_laesst_die_andere_taste_nicht_allein_ausloesen(monkeypatch):
    """Befund des Pruefers: _down_vks kennt nur Software-Ereignisse. Geht ein Loslassen verloren
    (Fokuswechsel, UAC-Dialog, gesperrter Bildschirm, Unterdrueckung durch eine andere App - siehe
    Kopf von wf/hotkey.py), bleibt eine Taste faelschlich "unten", und die JEWEILS ANDERE Taste
    der Kombination loest danach allein aus. Hier: das AltGr-hoch nach dem ersten Ausschnitt
    kommt nie an (_down_vks bleibt bei {ALT_GR} haengen); drei Grossbuchstaben mit der linken
    Umschalt-Taste duerfen trotzdem KEINEN weiteren Ausschnitt ausloesen, sobald
    _physically_down() (hier ersetzt, echtes GetAsyncKeyState gibt es hier nicht) meldet, dass
    AltGr laengst oben ist."""
    w = _watcher("alt_gr+shift", mode="tap")
    w._filter(RUNTER, _Daten(ALT_GR))
    w._filter(RUNTER, _Daten(SHIFT_L))
    assert _jobs(w) == ["go"]
    w._filter(HOCH, _Daten(SHIFT_L))
    # Das AltGr-hoch (0xA5) kommt absichtlich NIE an - "verloren". Windows wuerde jetzt trotzdem
    # melden, dass die Taste physisch oben ist:
    w._physically_down = lambda vk: False if vk == ALT_GR else None
    for _ in range(3):                              # drei Grossbuchstaben mit der linken Umschalt-Taste
        w._filter(RUNTER, _Daten(SHIFT_L))
        _tippen(w, TASTE_A)
        w._filter(HOCH, _Daten(SHIFT_L))
    assert _jobs(w) == ["go"]                       # kein einziges weiteres Ausloesen


def test_physically_down_ohne_windows_gilt_als_unbekannt(monkeypatch):
    """Ohne ctypes.windll (kein Windows) bleibt der Softwarezustand massgeblich. ctypes.windll
    ausdruecklich entfernt (Nachbesserung Runde 2, B5), statt sich auf "hier ist es sowieso kein
    Windows" zu verlassen - der Test soll auch auf einem echten Windows-CI-Runner beweisen, was er
    behauptet, nicht nur zufaellig hier in der Cloud gruen sein."""
    monkeypatch.delattr(ctypes, "windll", raising=False)
    assert snip.KeyWatcher._physically_down(0xA5) is None


@pytest.mark.parametrize("reihenfolge", [
    (LCTRL_PHANTOM, ALT_GR, SHIFT_L),      # AltGr zuerst (mit der Windows-Vorlaufzeile)
    (SHIFT_L, LCTRL_PHANTOM, ALT_GR),      # Umschalt zuerst, AltGr danach (Vorlaufzeile trotzdem)
])
def test_kombination_reihenfolge_ist_egal(reihenfolge):
    w = _watcher("alt_gr+shift", mode="tap")
    for vk in reihenfolge:
        w._filter(RUNTER, _Daten(vk))
    assert _jobs(w) == ["go"]


# --- Kombinationen, Betriebsart hold --------------------------------------------------------------
def test_kombination_hold_kurz_loest_nicht_aus(wecker):
    w = _watcher("alt_gr+shift", mode="hold", hold_ms=200)
    w._filter(RUNTER, _Daten(ALT_GR))
    assert wecker == []                              # AltGr allein: noch kein Timer
    w._filter(RUNTER, _Daten(SHIFT_L))
    assert len(wecker) == 1                          # jetzt vollstaendig: Haltezeit beginnt
    w._filter(HOCH, _Daten(SHIFT_L))                 # vor Ablauf der Haltezeit losgelassen
    assert wecker[0].abgebrochen
    wecker[0].ausloesen()                            # abgebrochen = wirkungslos
    w._filter(HOCH, _Daten(ALT_GR))
    assert _jobs(w) == []


def test_kombination_hold_muss_komplett_gehalten_werden_loest_beim_loslassen_aus(wecker):
    w = _watcher("alt_gr+shift", mode="hold", hold_ms=200)
    w._filter(RUNTER, _Daten(ALT_GR))
    w._filter(RUNTER, _Daten(SHIFT_L))
    assert len(wecker) == 1
    wecker[0].ausloesen()                            # Haltezeit erreicht
    w._filter(HOCH, _Daten(SHIFT_L))                 # eine der beiden Tasten loslassen reicht
    assert _jobs(w) == ["go"]
    w._filter(HOCH, _Daten(ALT_GR))


def test_kombination_hold_fremde_taste_bricht_ab(wecker):
    w = _watcher("alt_gr+shift", mode="hold", hold_ms=200)
    w._filter(RUNTER, _Daten(ALT_GR))
    w._filter(RUNTER, _Daten(SHIFT_L))
    _tippen(w, TASTE_A)                              # fremde Taste waehrend des Haltens
    assert wecker[0].abgebrochen
    wecker[0].ausloesen()                            # abgebrochen = wirkungslos
    w._filter(HOCH, _Daten(SHIFT_L))
    w._filter(HOCH, _Daten(ALT_GR))
    assert _jobs(w) == []


def test_kombination_hold_phantom_lctrl_bricht_auch_bei_wiederholung_nicht_ab(wecker):
    """B4 (Nachbesserung Runde 1): die Phantom-Strg-Regel muss auch im Modus 'hold' greifen, nicht
    nur bei tap (dort bewirkt eine fremde Taste ohnehin nichts). Reihenfolge wie vom Pruefer
    vorgegeben: Umschalt zuerst, dann das unechte LCtrl gefolgt von AltGr, danach eine
    Tastenwiederholung des unechten LCtrl+AltGr (wie beim Halten der echten Taste ueblich)."""
    w = _watcher("alt_gr+shift", mode="hold", hold_ms=200)
    w._filter(RUNTER, _Daten(SHIFT_L))
    w._filter(RUNTER, _Daten(LCTRL_PHANTOM))
    w._filter(RUNTER, _Daten(ALT_GR))
    assert len(wecker) == 1
    wecker[0].ausloesen()                            # Haltezeit erreicht
    assert w._armed
    for _ in range(2):                               # Tastenwiederholung des unechten LCtrl+AltGr
        w._filter(RUNTER, _Daten(LCTRL_PHANTOM))
        w._filter(RUNTER, _Daten(ALT_GR))
    w._filter(HOCH, _Daten(ALT_GR))
    assert _jobs(w) == ["go"]


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


# --- Gegenprobe B5 (Nachbesserung Runde 2) ------------------------------------------------------
# Ein echter Windows-Rechner meldet GetAsyncKeyState fuer JEDE Taste "oben", solange ein Test nur
# synthetische Ereignisse schickt, ohne wirklich eine Taste zu druecken - genau der Zustand auf
# dem windows-latest-CI-Runner (.github/workflows/tests.yml) und am Rechner des Nutzers. Ohne den
# Schutz in _watcher() (s.o.) wuerde _reconcile_down_vks() (B1) dort JEDE gemerkte Taste sofort
# wieder austragen, Kombinationen wuerden nie vollstaendig, und Loslassen bei hold/Doppeltippen
# wuerde nicht mehr ausgewertet - ein Fehler, den die Linux-CI bisher nie sehen konnte, weil
# ctypes.windll hier gar nicht existiert (_physically_down() faellt dort immer auf None zurueck).
# Diese Tests simulieren genau diesen Windows-Zustand, damit die Fehlerklasse hier sichtbar bleibt.
@pytest.fixture
def kein_echter_tastendruck(monkeypatch):
    """GetAsyncKeyState antwortet fuer JEDE Taste "oben" (0) - wie auf einem echten Windows-
    Rechner, an dem waehrend des Tests niemand wirklich eine Taste haelt."""
    user32 = types.SimpleNamespace(GetAsyncKeyState=lambda vk: 0)
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(user32=user32), raising=False)


def test_b5_einzeltaste_hold_funktioniert_trotz_getasynckeystate_0(kein_echter_tastendruck, wecker):
    w = _watcher("shift_r", mode="hold", hold_ms=200)
    w._filter(RUNTER, _Daten(SHIFT_R))
    wecker[0].ausloesen()
    w._filter(HOCH, _Daten(SHIFT_R))
    assert _jobs(w) == ["go"]


def test_b5_doppeltippen_funktioniert_trotz_getasynckeystate_0(kein_echter_tastendruck, wecker, uhr):
    w = _watcher("shift_r", mode="hold", hold_ms=250, on_double=lambda: None, double_tap_ms=400)
    assert _zweimal(w, uhr, 0.15) == ["doppelt"]


def test_b5_kombination_tap_funktioniert_trotz_getasynckeystate_0(kein_echter_tastendruck):
    w = _watcher("alt_gr+shift", mode="tap")
    w._filter(RUNTER, _Daten(ALT_GR))
    w._filter(RUNTER, _Daten(SHIFT_L))
    assert _jobs(w) == ["go"]


def test_b5_kombination_hold_funktioniert_trotz_getasynckeystate_0(kein_echter_tastendruck, wecker):
    w = _watcher("alt_gr+shift", mode="hold", hold_ms=200)
    w._filter(RUNTER, _Daten(ALT_GR))
    w._filter(RUNTER, _Daten(SHIFT_L))
    wecker[0].ausloesen()
    w._filter(HOCH, _Daten(SHIFT_L))
    assert _jobs(w) == ["go"]


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


# --- Ein PNG, im Hintergrund geschrieben (Arbeitspaket 6) ----------------------------------------
def test_png_wird_nur_einmal_kodiert(tmp_path, monkeypatch, win32clipboard_attrappe):
    """do_snip()/do_fullscreen() kodierten frueher zweimal (Zwischenablage + Datei), zusammen
    rund 100-130 ms bei einem 2560x1440-Bild (Messung siehe encode_png()). Dieser Test zaehlt die
    Aufrufe statt die Zeit zu stoppen - das ist deterministisch und unabhaengig von der Maschine."""
    bild = Image.new("RGB", (12, 9), (5, 6, 7))
    aufrufe: list = []
    orig_save = bild.save

    def _gezaehlt(fp, format=None, **kw):
        aufrufe.append(format)
        return orig_save(fp, format, **kw)

    monkeypatch.setattr(bild, "save", _gezaehlt)

    png = snip.encode_png(bild)
    assert aufrufe == ["PNG"]

    snip.to_clipboard(bild, png)                      # nutzt CF_DIB (BMP) zusaetzlich - keine 2. PNG
    assert aufrufe.count("PNG") == 1
    assert win32clipboard_attrappe.get(0xC000) == png  # PNG-Format traegt genau die uebergebenen Bytes

    pfad, thread = snip.save_image_async(bild, tmp_path, png)
    thread.join(timeout=5)
    assert aufrufe.count("PNG") == 1                  # auch die Datei nutzt dieselben Bytes
    assert pfad.read_bytes() == png


def test_save_image_async_kehrt_zurueck_bevor_geschrieben_ist(tmp_path, monkeypatch):
    """"fertig" (Zwischenablage/Meldung) darf nicht auf die Festplatte warten. Deterministisch
    mit einem Ereignis statt einem festen sleep: das Schreiben haengt, bis der Test es freigibt."""
    bild = Image.new("RGB", (5, 5), (1, 2, 3))
    frei = threading.Event()
    orig = snip._write_png

    def _erst_wenn_freigegeben(path, image, png_bytes):
        frei.wait(5)
        orig(path, image, png_bytes)

    monkeypatch.setattr(snip, "_write_png", _erst_wenn_freigegeben)
    png = snip.encode_png(bild)

    pfad, thread = snip.save_image_async(bild, tmp_path, png)
    assert not pfad.exists()                          # der Aufruf ist zurueck, ohne zu warten
    frei.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert pfad.exists() and pfad.read_bytes() == png


def test_save_image_async_name_steht_sofort_fest_und_bleibt_eindeutig(tmp_path, monkeypatch):
    """Zwei Ausschnitte in derselben Sekunde (fester Zeitstempel): der zweite Name muss feststehen
    UND einzigartig sein, obwohl die erste Datei noch nicht auf der Platte liegt - reines
    Path.exists() (wie zuvor bei save_image) wuerde hier denselben Namen zweimal vergeben."""
    monkeypatch.setattr(snip, "datetime", _FesteZeit)
    bild = Image.new("RGB", (5, 5), (1, 2, 3))
    frei = threading.Event()
    orig = snip._write_png

    def _erst_wenn_freigegeben(path, image, png_bytes):
        frei.wait(5)
        orig(path, image, png_bytes)

    monkeypatch.setattr(snip, "_write_png", _erst_wenn_freigegeben)
    png = snip.encode_png(bild)

    pfad1, thread1 = snip.save_image_async(bild, tmp_path, png)
    pfad2, thread2 = snip.save_image_async(bild, tmp_path, png)     # bevor Datei 1 existiert
    assert pfad1 != pfad2, (pfad1, pfad2)

    frei.set()
    thread1.join(timeout=5)
    thread2.join(timeout=5)
    assert pfad1.read_bytes() == png and pfad2.read_bytes() == png


def test_save_image_async_ordner_nicht_anlegbar_wirft_nicht(tmp_path, capsys):
    """B2 (Nachbesserung Runde 1): der Ordner wird jetzt im Hintergrund-Thread angelegt, nicht
    mehr synchron in _naechster_freier_pfad() - eine Ausnahme dabei (fehlendes Laufwerk, keine
    Rechte, wie hier simuliert: eine DATEI liegt im Weg) darf nicht synchron in do_snip()/
    do_fullscreen() landen, obwohl das Bild schon in der Zwischenablage liegt (Kriterium 7)."""
    bild = Image.new("RGB", (5, 5), (1, 2, 3))
    png = snip.encode_png(bild)
    datei_im_weg = tmp_path / "datei-im-weg"
    datei_im_weg.write_bytes(b"x")                 # eine DATEI dort, wo der "Ordner" hinsoll
    ziel_ordner = datei_im_weg / "images"          # mkdir() darunter schlaegt fehl (kein Ordner)

    pfad, thread = snip.save_image_async(bild, ziel_ordner, png)     # darf NICHT werfen
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert not pfad.exists()
    ausgabe = capsys.readouterr().out
    assert "file NOT written" in ausgabe and pfad.name in ausgabe


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
