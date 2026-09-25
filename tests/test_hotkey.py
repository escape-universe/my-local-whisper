"""wf/hotkey.py: Tastennamen (seit Arbeitspaket 7 jeder Name aus pynput), Entprellung
(Auto-Repeat), verlorenes Loslassen, Worker-Reihenfolge.

Der physische Tastenzustand kommt unter Windows aus GetAsyncKeyState. Er wird hier IMMER ersetzt
(Fixture physisch), sonst fragte der Test auf dem Windows-Runner die echte Tastatur ab. Die Uhr
ist ebenfalls ersetzt (Fixture uhr): die Ruhepause-Regel haengt sonst an der Rechnerlast."""
from __future__ import annotations

import ctypes
import sys
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


# --- resolve_key: jeder Name aus pynput.keyboard.Key (Arbeitspaket 7, 25.09.2026) ---------------
@pytest.mark.parametrize("name", ["f8", "insert", "caps_lock", "menu", "print_screen", " F8 ", "Insert"])
def test_resolve_key_kennt_jeden_pynput_namen(name, capsys):
    """Bis 25.09.2026 fielen diese Namen STILL auf die rechte Strg zurueck: man drueckte F8, und
    nichts geschah (die App hoerte auf Strg rechts)."""
    assert hotkey.resolve_key(name) is getattr(hotkey.keyboard.Key, name.strip().lower())
    assert "WARNING" not in capsys.readouterr().out


def test_resolve_key_bisherige_namen_wie_bisher(capsys):
    for name, taste in hotkey._SPECIAL.items():
        assert hotkey.resolve_key(name) is taste, name
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("zeichen", ["x", "Q", "5", "#"])
def test_resolve_key_einzelzeichen(zeichen, capsys):
    assert hotkey.resolve_key(zeichen) == hotkey.keyboard.KeyCode.from_char(zeichen.lower())
    assert capsys.readouterr().out == ""


def test_resolve_key_ziffer_als_zahl_aus_yaml(capsys):
    """config.local.yaml `key: 5` liest YAML als Zahl 5, nicht als Text "5"."""
    assert hotkey.resolve_key(5) == hotkey.keyboard.KeyCode.from_char("5")
    assert _hk(5)._key_name == "5" and capsys.readouterr().out == ""


@pytest.mark.parametrize("name", ["gibtsnicht", "f99", "strg_rechts", "mro", "__class__", "name"])
def test_resolve_key_unbekannt_laut_mit_gueltigen_namen_und_rueckfall(name, capsys):
    """"mro", "__class__", "name": Attribute der Enum-Klasse, aber keine Tasten."""
    assert hotkey.resolve_key(name) is hotkey.keyboard.Key.ctrl_r
    out = capsys.readouterr().out
    assert out.startswith(f"[hotkey] WARNING: unknown key name {name!r} in hotkey.key -> falling back to 'ctrl_r'")
    for beispiel in ("f8", "insert", "caps_lock", "menu", "scroll_lock", "ctrl_l", "a single character"):
        assert beispiel in out, beispiel


@pytest.mark.parametrize("leer", ["", "   ", None])
def test_resolve_key_leer_ist_der_standard_ohne_warnung(leer, capsys):
    assert hotkey.resolve_key(leer) is hotkey.keyboard.Key.ctrl_r
    assert capsys.readouterr().out == ""


def _windows_codes(attrappen) -> None:
    """Echtes pynput ausserhalb von Windows traegt keine Windows-Tastencodes (dort X11/macOS)."""
    if "pynput" not in attrappen and sys.platform != "win32":
        pytest.skip("echtes pynput ausserhalb von Windows hat keine Windows-Tastencodes")


@pytest.mark.parametrize("name, vk", [("f8", 0x77), ("insert", 0x2D), ("caps_lock", 0x14),
                                      ("menu", 0x5D), ("ctrl_r", 0xA3), (" F9 ", 0x78)])
def test_gegenprobe_nimmt_den_code_aus_pynput(name, vk, attrappen):
    _windows_codes(attrappen)
    assert hotkey._vk_code(name) == vk


def test_gegenprobe_ohne_pynput_eintrag_aus_der_tabelle(monkeypatch):
    """Kennt pynput einen der bisherigen Namen nicht (cmd_r fehlt ausserhalb von Windows), gilt
    weiter die Tabelle _VK. Einzelzeichen haben keinen Code: dann entscheidet die Zeitregel."""
    monkeypatch.setattr(hotkey, "_pynput_key", lambda name: None)
    assert hotkey._vk_code("cmd_r") == 0x5C and hotkey._vk_code("f12") == 0x7B
    assert hotkey._vk_code("x") is None and hotkey._vk_code("") is None


def test_physically_down_fragt_windows_nach_dem_code_der_neuen_taste(monkeypatch, attrappen):
    _windows_codes(attrappen)
    gefragt = []
    user32 = types.SimpleNamespace(GetAsyncKeyState=lambda vk: (gefragt.append(vk), 0x8000)[1])
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(user32=user32), raising=False)
    assert _ECHT_PHYSICALLY_DOWN("f8") is True
    assert gefragt == [0x77]


def test_key_name_ist_der_wirksame_name(capsys):
    """Fuer die Startzeilen (App.run, calibrate.py): nach einem Rueckfall "ctrl_r", nicht der
    Tippfehler, der gerade als unbekannt gemeldet wurde."""
    assert _hk("gibtsnicht").key_name == "ctrl_r"
    assert _hk(" F8 ").key_name == "f8" and _hk("x").key_name == "x" and _hk(None).key_name == "ctrl_r"


def test_nach_rueckfall_gilt_die_gegenprobe_der_gehoerten_taste(physisch, capsys):
    """Unbekannter Name -> gehoert wird auf die rechte Strg, also fragt die Gegenprobe auch sie ab
    (bis 25.09.2026 den unbekannten Namen, der keinen Code hat)."""
    hk = _hk("gibtsnicht")
    assert hk._target is hotkey.keyboard.Key.ctrl_r and "WARNING" in capsys.readouterr().out
    physisch["wert"] = True
    hk._press(hk._target)
    hk._press(hk._target)                        # Auto-Repeat: jetzt wird Windows gefragt
    assert physisch["gefragt"] == ["ctrl_r"]


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
