"""wf/hotkey.py: Entprellung (Auto-Repeat), verlorenes Loslassen, Worker-Reihenfolge.

Der physische Tastenzustand kommt unter Windows aus GetAsyncKeyState. Er wird hier IMMER ersetzt
(Fixture physisch), sonst fragte der Test auf dem Windows-Runner die echte Tastatur ab. Die Uhr
ist ebenfalls ersetzt (Fixture uhr): die Ruhepause-Regel haengt sonst an der Rechnerlast."""
from __future__ import annotations

import ctypes
import threading
import types

import pytest

from wf import hotkey

_ECHT_PHYSICALLY_DOWN = hotkey._physically_down


@pytest.fixture(autouse=True)
def uhr(monkeypatch):
    """uhr['jetzt'] ist die Zeit, die hotkey.py sieht; Tests stellen sie vor."""
    stand = {"jetzt": 1000.0}
    monkeypatch.setattr(hotkey, "time", types.SimpleNamespace(time=lambda: stand["jetzt"]))
    return stand


@pytest.fixture(autouse=True)
def physisch(monkeypatch):
    """zustand['wert']: True = Taste laut Windows unten, False = oben, None = nicht feststellbar."""
    zustand = {"wert": None, "gefragt": []}

    def _gefaelscht(name):
        zustand["gefragt"].append(name)
        return zustand["wert"]

    monkeypatch.setattr(hotkey, "_physically_down", _gefaelscht)
    return zustand


def _jobs(hk: hotkey.HoldToTalk) -> list:
    out = []
    while not hk._jobs.empty():
        out.append(hk._jobs.get_nowait())
    return out


def _hk(name: str = "ctrl_r") -> hotkey.HoldToTalk:
    return hotkey.HoldToTalk(name, lambda: None, lambda: None)


# --- resolve_key -------------------------------------------------------------------------------
def test_resolve_key():
    k = hotkey.keyboard
    assert hotkey.resolve_key("ctrl_r") is k.Key.ctrl_r
    assert hotkey.resolve_key(" F9 ") is k.Key.f9
    assert hotkey.resolve_key("") is k.Key.ctrl_r and hotkey.resolve_key(None) is k.Key.ctrl_r
    assert hotkey.resolve_key("gibtsnicht") is k.Key.ctrl_r                 # Rueckfall
    assert hotkey.resolve_key("x") == k.KeyCode.from_char("x")


# --- Entprellung -------------------------------------------------------------------------------
def test_auto_repeat_loest_nur_einmal_aus(physisch):
    physisch["wert"] = True                      # Taste wird gehalten
    hk = _hk()
    for _ in range(5):                           # Druck + Auto-Repeat
        hk._press(hk._target)
    assert _jobs(hk) == ["press"]


def test_auto_repeat_ohne_windows_innerhalb_der_ruhepause(physisch, uhr):
    """Kein Windows: nur die Zeitregel. Jeder Repeat frischt die Ruhepause auf, sonst loeste ein
    Halten laenger als _STUCK_AFTER_S einen zweiten Druck aus."""
    physisch["wert"] = None
    hk = _hk("x")
    hk._press(hk._target)
    for _ in range(100):                         # Repeat alle 30 ms, 3 s lang
        uhr["jetzt"] += 0.03
        hk._press(hk._target)
    assert _jobs(hk) == ["press"]


def test_loslassen_zaehlt_nur_einmal(uhr):
    hk = _hk()
    hk._press(hk._target)
    uhr["jetzt"] += 2.0
    hk._release(hk._target)
    hk._release(hk._target)                      # zweites Loslassen ohne Druck
    assert _jobs(hk) == ["press", "release"]
    assert (hk.last_press_at, hk.last_release_at) == (1000.0, 1002.0)   # fuer die [timing]-Messung


def test_andere_tasten_werden_ignoriert():
    hk = _hk()
    hk._press(hotkey.keyboard.Key.ctrl_l)
    hk._release(hotkey.keyboard.Key.ctrl_l)
    hk._press(hotkey.keyboard.KeyCode.from_char("a"))
    assert _jobs(hk) == [] and not hk._down


# --- verlorenes Loslassen (Entscheidung 08.09.2026) --------------------------------------------
def test_verlorenes_loslassen_windows_meldet_taste_oben(physisch, capsys):
    hk = _hk()
    physisch["wert"] = True
    hk._press(hk._target)
    assert _jobs(hk) == ["press"]
    # Release-Ereignis geht verloren; Windows sagt: Taste ist laengst oben
    physisch["wert"] = False
    hk._press(hk._target)                        # naechster echter Druck muss durchkommen
    assert _jobs(hk) == ["press"]
    assert "missed key release" in capsys.readouterr().out
    assert physisch["gefragt"] and set(physisch["gefragt"]) == {"ctrl_r"}


def test_verlorenes_loslassen_ohne_windows_nach_ruhepause(physisch, uhr):
    """Selbsttest-Fall: Taste ohne Windows-Code -> die Ruhepause-Regel entscheidet."""
    physisch["wert"] = None
    hk = _hk("x")
    hk._press(hk._target)
    uhr["jetzt"] += hotkey._STUCK_AFTER_S - 0.1  # knapp innerhalb: noch Repeat
    hk._press(hk._target)
    uhr["jetzt"] += hotkey._STUCK_AFTER_S + 0.1  # lange Ruhe ohne Loslassen
    hk._press(hk._target)
    assert _jobs(hk) == ["press", "press"]


def test_lang_gehaltene_taste_ist_kein_verlorenes_loslassen(physisch, uhr):
    """Windows sagt "unten": dann zaehlt die Zeitregel nicht (langes Diktat mit gehaltener Taste)."""
    physisch["wert"] = True
    hk = _hk()
    hk._press(hk._target)
    uhr["jetzt"] += 60                           # eine Minute gehalten, Repeat kommt weiter
    hk._press(hk._target)
    assert _jobs(hk) == ["press"] and hk._down


# --- _physically_down selbst, mit gefaelschtem ctypes.windll -----------------------------------
def _windll(status: int):
    user32 = types.SimpleNamespace(GetAsyncKeyState=lambda vk: status)
    return types.SimpleNamespace(user32=user32)


def test_physically_down_liest_das_hohe_bit(monkeypatch):
    monkeypatch.setattr(ctypes, "windll", _windll(0x8000), raising=False)
    assert _ECHT_PHYSICALLY_DOWN("ctrl_r") is True
    monkeypatch.setattr(ctypes, "windll", _windll(0x0001), raising=False)   # nur "seit letzter Abfrage"
    assert _ECHT_PHYSICALLY_DOWN("ctrl_r") is False


def test_physically_down_ohne_code_oder_ohne_windows(monkeypatch):
    assert _ECHT_PHYSICALLY_DOWN("x") is None                     # kein Code hinterlegt
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(), raising=False)
    assert _ECHT_PHYSICALLY_DOWN("ctrl_r") is None                # Aufruf scheitert -> Zeitregel


# --- Worker: Rueckrufe ausserhalb des Listener-Threads, in Reihenfolge -------------------------
class _Listener:
    """Ersatz fuer pynput.keyboard.Listener (auch wenn das echte pynput installiert ist)."""

    def __init__(self, on_press=None, on_release=None, **kwargs):
        self.on_press, self.on_release, self.laeuft = on_press, on_release, False

    def start(self):
        self.laeuft = True

    def stop(self):
        self.laeuft = False


def test_worker_ruft_in_reihenfolge_und_ueberlebt_fehler(monkeypatch):
    monkeypatch.setattr(hotkey.keyboard, "Listener", _Listener)
    ablauf: list[str] = []
    fertig = threading.Event()

    def on_press():
        ablauf.append("press")
        raise RuntimeError("Fehler im Rueckruf")   # darf den Worker nicht beenden

    def on_release():
        ablauf.append("release")
        fertig.set()

    hk = hotkey.HoldToTalk("ctrl_r", on_press, on_release)
    hk.start()
    worker, listener = hk._worker, hk._listener
    try:
        assert listener.laeuft and listener.on_press == hk._press and listener.on_release == hk._release
        listener.on_press(hk._target)
        listener.on_release(hk._target)
        assert fertig.wait(5), "Worker hat on_release nicht aufgerufen"
    finally:
        hk.stop()
        worker.join(5)
    assert ablauf == ["press", "release"]
    assert not worker.is_alive() and not listener.laeuft
