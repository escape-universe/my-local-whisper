"""Grundlage der pytest-Suite (Arbeitspaket 1, 24.09.2026).

Die App laeuft nur unter Windows, mit Mikrofon, GPU und Ollama. Diese Tests pruefen die reine
Logik und laufen ueberall: im Cloud-Container und in GitHub Actions auf Ubuntu UND Windows.
Dafuer bekommen die Pakete, die es dort nicht gibt, eine Attrappe in sys.modules:

    pynput (+ pynput.keyboard), sounddevice, win32clipboard, win32con, win32gui,
    win32process, win32api, uiautomation, pystray

Regeln (Entscheidung 24.09.2026):
- Eine Attrappe kommt NUR, wenn der echte Import scheitert. Ist das Paket installiert (Windows-
  Rechner mit requirements.txt), laufen die Tests gegen das echte Paket.
- Attrappen sind ausdrueckliche Module mit genau den Namen, die der Code benutzt, kein MagicMock:
  ein Tippfehler im App-Code (keyboard.Key.ctrl_rr) bleibt ein AttributeError wie beim echten Paket.
- Projekt-Module (wf.*, whisperflow) werden hier weder ersetzt noch vorab importiert. Ein echter
  Importfehler dort bleibt ein roter Test.
- Welche Attrappen aktiv sind und warum, steht im Kopf der pytest-Ausgabe (Aufruf ohne -q).

Zum Wiederverwenden in spaeteren Paketen: pynput-Tasten tragen die Windows-Tastencodes
(Key.ctrl_r.value.vk == 0xA3), der Listener merkt sich seine Rueckrufe, pystray-Menues merken sich
ihre Eintraege (item.text, item.checked, item.submenu, item(icon) klickt), das Icon sammelt
notify()-Meldungen, die Zwischenablage haelt, was man hineinlegt.
"""
from __future__ import annotations

import enum
import importlib
import inspect
import sys
import types
from typing import Callable

import pytest
import requests.adapters

#: Name -> Grund, warum statt des echten Pakets die Attrappe laeuft.
ATTRAPPEN: dict[str, str] = {}


def _attrappe_falls_noetig(name: str, bauen: Callable[[], dict[str, types.ModuleType]],
                           module: dict | None = None, liste: dict | None = None) -> None:
    """Echtes Paket, wenn es sich importieren laesst; sonst die Module aus bauen() einsetzen.
    OSError zaehlt mit: sounddevice ohne PortAudio-Bibliothek scheitert so, nicht mit ImportError.
    module/liste nur fuer den Test dieser Regel (sonst sys.modules und ATTRAPPEN)."""
    module = sys.modules if module is None else module
    liste = ATTRAPPEN if liste is None else liste
    try:
        importlib.import_module(name)
        return
    except (ImportError, OSError) as e:
        grund = f"{type(e).__name__}: {e}"
    for modulname, modul in bauen().items():
        modul.__attrappe__ = True
        module[modulname] = modul
    liste[name] = grund


def _modul(name: str, **inhalt) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__dict__.update(inhalt)
    return m


# --- pynput ------------------------------------------------------------------------------------
# Windows-Tastencodes wie in pynput/keyboard/_win32.py. Gleiche Codes werden wie dort zu Aliassen
# desselben Enum-Mitglieds (Key.alt_gr is Key.alt_r).
_WIN_VK: list[tuple[str, int]] = [
    ("alt", 0x12), ("alt_l", 0xA4), ("alt_r", 0xA5), ("alt_gr", 0xA5),
    ("backspace", 0x08), ("caps_lock", 0x14),
    ("cmd", 0x5B), ("cmd_l", 0x5B), ("cmd_r", 0x5C),
    ("ctrl", 0x11), ("ctrl_l", 0xA2), ("ctrl_r", 0xA3),
    ("delete", 0x2E), ("enter", 0x0D), ("esc", 0x1B),
    *((f"f{i}", 0x6F + i) for i in range(1, 25)),          # F1 = 0x70 ... F24 = 0x87
    ("insert", 0x2D), ("menu", 0x5D), ("num_lock", 0x90), ("pause", 0x13),
    ("print_screen", 0x2C), ("scroll_lock", 0x91),
    ("shift", 0xA0), ("shift_l", 0xA0), ("shift_r", 0xA1), ("tab", 0x09),
]


def _pynput() -> dict[str, types.ModuleType]:
    class KeyCode:
        """Wie pynput.keyboard.KeyCode: vk = Windows-Tastencode, char = Zeichen."""

        def __init__(self, vk=None, char=None, is_dead=False, **kwargs):
            self.vk, self.char, self.is_dead = vk, char, is_dead

        @classmethod
        def from_vk(cls, vk, **kwargs):
            return cls(vk=vk, **kwargs)

        @classmethod
        def from_char(cls, char, **kwargs):
            return cls(char=char, **kwargs)

        def __eq__(self, other):
            if not isinstance(other, KeyCode):
                return False
            if self.char is not None and other.char is not None:
                return self.char == other.char and self.is_dead == other.is_dead
            return self.vk == other.vk

        def __hash__(self):
            return hash(repr(self))

        def __repr__(self):
            return repr(self.char) if self.char is not None else f"<{self.vk}>"

    Key = enum.Enum("Key", [(n, KeyCode.from_vk(vk)) for n, vk in _WIN_VK]
                    + [("space", KeyCode(vk=0x20, char=" "))], module="pynput.keyboard")

    class SuppressException(Exception):
        """suppress_event() bricht das gerade gefilterte Ereignis per Ausnahme ab (wie pynput)."""

    class Listener:
        """Wie pynput.keyboard.Listener, aber ohne Tastatur-Hook und ohne Thread: merkt sich die
        Rueckrufe. Ein Test loest Ereignisse selbst aus, z. B. listener.on_press(Key.ctrl_r)."""

        def __init__(self, on_press=None, on_release=None, suppress=False, **kwargs):
            self.on_press, self.on_release, self.suppress = on_press, on_release, suppress
            self.kwargs = kwargs            # z. B. win32_event_filter (wf/snip.py)
            self.running = False

        def start(self):
            self.running = True

        def stop(self):
            self.running = False

        def join(self, timeout=None):
            pass

        def suppress_event(self):
            raise SuppressException()

        def __enter__(self):
            self.start()
            return self

        def __exit__(self, *exc):
            self.stop()

    keyboard = _modul("pynput.keyboard", Key=Key, KeyCode=KeyCode, Listener=Listener,
                      SuppressException=SuppressException)
    paket = _modul("pynput", keyboard=keyboard, __path__=[])
    return {"pynput": paket, "pynput.keyboard": keyboard}


# --- sounddevice -------------------------------------------------------------------------------
def _sounddevice() -> dict[str, types.ModuleType]:
    class PortAudioError(Exception):
        pass

    class InputStream:
        """Wie sounddevice.InputStream, ohne Geraet: merkt sich die Argumente. Ein Test fuettert
        stream.callback(indata, frames, time_info, status) selbst."""

        def __init__(self, samplerate=None, channels=None, dtype=None, device=None,
                     callback=None, **kwargs):
            self.samplerate, self.channels, self.dtype = samplerate, channels, dtype
            self.device, self.callback, self.kwargs = device, callback, kwargs
            self.active = False
            self.closed = False

        def start(self):
            self.active = True

        def stop(self):
            self.active = False

        def close(self):
            self.active = False
            self.closed = True

    def query_devices(device=None, kind=None):
        return []       # kein Mikrofon

    return {"sounddevice": _modul("sounddevice", PortAudioError=PortAudioError,
                                  InputStream=InputStream, query_devices=query_devices)}


# --- pywin32 -----------------------------------------------------------------------------------
def _win32con() -> dict[str, types.ModuleType]:
    """Nur die Konstanten, die der Code benutzt, mit den echten Werten."""
    return {"win32con": _modul(
        "win32con", CF_TEXT=1, CF_DIB=8, CF_UNICODETEXT=13, GWL_EXSTYLE=-20,
        WS_EX_TOPMOST=0x8, WS_EX_TRANSPARENT=0x20, WS_EX_TOOLWINDOW=0x80,
        WS_EX_LAYERED=0x80000, WS_EX_NOACTIVATE=0x8000000,
        HWND_TOPMOST=-1, SWP_NOSIZE=0x1, SWP_NOMOVE=0x2, SWP_NOACTIVATE=0x10)}


def _win32clipboard() -> dict[str, types.ModuleType]:
    """Zwischenablage im Speicher: was hineingelegt wird, laesst sich zuruecklesen."""
    ablage: dict[int, object] = {}
    formate: dict[str, int] = {}

    class error(Exception):             # wie pywintypes.error
        pass

    def GetClipboardData(fmt=1):
        if fmt not in ablage:
            raise error("Specified clipboard format is not available")
        return ablage[fmt]

    return {"win32clipboard": _modul(
        "win32clipboard", error=error, GetClipboardData=GetClipboardData,
        OpenClipboard=lambda hwnd=None: None, CloseClipboard=lambda: None,
        EmptyClipboard=ablage.clear,
        SetClipboardText=lambda text, fmt=1: ablage.__setitem__(fmt, text),
        SetClipboardData=lambda fmt, data: ablage.__setitem__(fmt, data),
        IsClipboardFormatAvailable=lambda fmt: fmt in ablage,
        RegisterClipboardFormat=lambda name: formate.setdefault(name, 0xC000 + len(formate)))}


def _win32gui() -> dict[str, types.ModuleType]:
    """Kein Fenster: Vordergrund 0, leerer Titel."""
    return {"win32gui": _modul(
        "win32gui", GetForegroundWindow=lambda: 0, GetWindowText=lambda hwnd: "",
        GetParent=lambda hwnd: 0, GetWindowLong=lambda hwnd, index: 0,
        SetWindowLong=lambda hwnd, index, value: 0, SetWindowPos=lambda *args: None)}


def _win32process() -> dict[str, types.ModuleType]:
    return {"win32process": _modul("win32process", GetWindowThreadProcessId=lambda hwnd: (0, 0))}


def _win32api() -> dict[str, types.ModuleType]:
    return {"win32api": _modul("win32api", GetCursorPos=lambda: (0, 0))}


def _uiautomation() -> dict[str, types.ModuleType]:
    """Kein fokussiertes Element (wf/focus.py wertet das als „kein Textfeld“)."""
    return {"uiautomation": _modul("uiautomation", GetFocusedControl=lambda: None)}


# --- pystray -----------------------------------------------------------------------------------
def _pystray() -> dict[str, types.ModuleType]:
    def _wert(x, item):
        return x(item) if callable(x) else x

    class Menu:
        """Wie pystray.Menu: menu.items = die Eintraege in Reihenfolge. Menu.SEPARATOR s. u."""

        def __init__(self, *items):
            self._items = tuple(items)

        @property
        def items(self):
            return self._items

        def __iter__(self):
            return iter(self._items)

    class MenuItem:
        """Wie pystray.MenuItem: text/checked/radio/... werten Callables aus (mit dem Eintrag als
        Argument), item.submenu ist das Untermenue, item(icon) klickt."""

        def __init__(self, text, action, checked=None, radio=False, default=False,
                     visible=True, enabled=True):
            self._text, self._action, self._checked = text, action, checked
            self._radio, self._default = radio, default
            self._visible, self._enabled = visible, enabled

        text = property(lambda self: _wert(self._text, self))
        checked = property(lambda self: _wert(self._checked, self))
        radio = property(lambda self: _wert(self._radio, self))
        default = property(lambda self: _wert(self._default, self))
        visible = property(lambda self: _wert(self._visible, self))
        enabled = property(lambda self: _wert(self._enabled, self))

        @property
        def submenu(self):
            return self._action if isinstance(self._action, Menu) else None

        def __call__(self, icon):
            """Klick. Wie pystray nimmt die Aktion 0, 1 (icon) oder 2 (icon, item) Argumente."""
            if self._action is None or isinstance(self._action, Menu):
                return None
            n = len(inspect.signature(self._action).parameters)
            return self._action(*(icon, self)[:n])

    Menu.SEPARATOR = MenuItem("- - - -", None)

    class Icon:
        """Wie pystray.Icon, ohne Tray: merkt sich Bild, Titel und Menue, sammelt notify()-Meldungen.
        run() kehrt sofort zurueck (das echte blockiert bis stop())."""

        def __init__(self, name, icon=None, title=None, menu=None, **kwargs):
            self.name, self.icon, self.title, self.menu = name, icon, title, menu
            self.kwargs = kwargs
            self.notifications: list[tuple[str, str | None]] = []
            self.menu_updates = 0
            self.running = False

        def run(self, setup=None):
            self.running = True
            if setup:
                setup(self)

        def stop(self):
            self.running = False

        def notify(self, message, title=None):
            self.notifications.append((message, title))

        def remove_notification(self):
            pass

        def update_menu(self):
            self.menu_updates += 1

    return {"pystray": _modul("pystray", Icon=Icon, Menu=Menu, MenuItem=MenuItem)}


_BAUPLAENE: dict[str, Callable[[], dict[str, types.ModuleType]]] = {
    "pynput": _pynput,
    "sounddevice": _sounddevice,
    "win32clipboard": _win32clipboard,
    "win32con": _win32con,
    "win32gui": _win32gui,
    "win32process": _win32process,
    "win32api": _win32api,
    "uiautomation": _uiautomation,
    "pystray": _pystray,
}

# Muss vor dem Sammeln der Tests laufen: die Testmodule importieren whisperflow schon beim Laden.
for _name, _bauen in _BAUPLAENE.items():
    _attrappe_falls_noetig(_name, _bauen)


def pytest_report_header(config):
    if not ATTRAPPEN:
        return "Attrappen: keine (alle Windows-/Hardware-Pakete echt installiert)"
    return ["Attrappen (echter Import gescheitert):"] + [f"  {n} <- {g}" for n, g in ATTRAPPEN.items()]


@pytest.fixture
def attrappen() -> dict[str, str]:
    """Welche Pakete gerade Attrappen sind (Name -> Grund). Tests, die das Verhalten einer
    Attrappe voraussetzen, ueberspringen sich damit, wenn das echte Paket installiert ist."""
    return dict(ATTRAPPEN)


@pytest.fixture
def attrappe_falls_noetig():
    """Die Einsetz-Regel selbst (fuer ihren eigenen Test)."""
    return _attrappe_falls_noetig


@pytest.fixture(autouse=True)
def _kein_netzwerk(monkeypatch):
    """Kein Test redet mit einem echten Server, auch nicht mit einem laufenden Ollama auf dem
    Entwicklerrechner: sonst waere derselbe Test dort gruen und in CI rot. Wer HTTP braucht,
    ersetzt den Aufruf per monkeypatch (siehe tests/test_cleanup.py). Absichtlich keine
    requests-Ausnahme: der Code faengt die ab, ein versehentlicher Aufruf soll laut scheitern."""
    def _gesperrt(self, request, *args, **kwargs):
        raise RuntimeError(f"Netzwerk im Test: {request.method} {request.url} -> per monkeypatch ersetzen")
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _gesperrt)
