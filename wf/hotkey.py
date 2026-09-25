"""S1 — Globaler Hold-to-talk-Hotkey (pynput).

Erkennt Key-Down/Key-Up einer konfigurierten Taste systemweit. Ruft on_press/on_release.
Kein Admin noetig zum Lauschen (nur zum Suppress, was wir nicht tun).

Zwei Haerten gegen "die Taste wird nicht immer sofort erkannt" (Entscheidung 08.09.2026):

1. VERLORENES RELEASE. Die Entprellung merkte sich "Taste ist unten" und wartete auf das
   Release-Event. Geht eines verloren (Fokuswechsel, UAC-Dialog, gesperrter Bildschirm,
   Suppress durch eine andere App), bleibt das Flag fuer immer haengen und JEDER weitere
   Druck wird verworfen — im Umschalt-Modus faellt das besonders auf, weil dort nur das
   Druecken zaehlt. Jetzt wird das Flag zusaetzlich verworfen, wenn Windows meldet, dass
   die Taste physisch oben ist, hilfsweise nach einer Ruhepause (Auto-Repeat feuert im
   Millisekundentakt, eine echte Pause ist also nie Repeat).
2. BLOCKIERTER LISTENER. on_press startete den Audio-Stream direkt im pynput-Thread —
   gemessen ~0,2 s (sounddevice-Stream oeffnen). In dieser Zeit staut pynput die
   nachfolgenden Tastenereignisse. Die Callbacks laufen deshalb in einem eigenen Worker,
   der Listener kehrt sofort zurueck. Ein Worker (keine Threadpool): die Reihenfolge
   press -> release muss erhalten bleiben.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable

from pynput import keyboard

_DEFAULT = "ctrl_r"

# Die bisher einzigen erlaubten Namen -> pynput Key. Seit Arbeitspaket 7 (25.09.2026) gilt jeder
# Name aus pynput.keyboard.Key (siehe _resolve); diese Tabelle wird zuerst gefragt, damit die
# alten Namen genau wie bisher aufgeloest werden (z. B. cmd_r, wo pynput es nicht kennt).
_SPECIAL: dict[str, object] = {
    "ctrl_r": keyboard.Key.ctrl_r,
    "ctrl_l": keyboard.Key.ctrl_l,
    "alt_r": keyboard.Key.alt_r,
    "alt_gr": keyboard.Key.alt_gr,
    "cmd": keyboard.Key.cmd,
    "cmd_r": getattr(keyboard.Key, "cmd_r", keyboard.Key.cmd),
    "scroll_lock": keyboard.Key.scroll_lock,
    "pause": keyboard.Key.pause,
    "f9": keyboard.Key.f9,
    "f10": keyboard.Key.f10,
    "f12": keyboard.Key.f12,
}

# Virtual-Key-Codes fuer die physische Gegenprobe (Windows). Seit Arbeitspaket 7 nur noch der
# Rueckfall: der Code kommt zuerst aus pynput (Key.<name>.value.vk, siehe _vk_code). Ist keiner
# bekannt (Einzelzeichen), greift allein die Ruhepause-Regel.
_VK = {
    "ctrl_r": 0xA3, "ctrl_l": 0xA2, "alt_r": 0xA5, "alt_gr": 0xA5,
    "cmd": 0x5B, "cmd_r": 0x5C, "scroll_lock": 0x91, "pause": 0x13,
    "f9": 0x78, "f10": 0x79, "f12": 0x7B,
}

# Nach so langer Ruhe ohne Release gilt ein "Taste unten" als verlorenes Event.
# Auto-Repeat feuert alle ~30 ms, eine Pause dieser Laenge kann kein Repeat sein.
_STUCK_AFTER_S = 1.0


def _pynput_key(name: str):
    """keyboard.Key.<name> oder None. Nur echte Tasten zaehlen, nicht andere Attribute der
    Enum-Klasse (getattr(Key, "mro") ist eine Methode, keine Taste)."""
    key = getattr(keyboard.Key, name, None) if name else None
    return key if isinstance(key, keyboard.Key) else None


def _resolve(name: str | None) -> tuple[object, str]:
    """(pynput-Taste, wirksamer Name). Bis 25.09.2026 kannte resolve_key nur die kurze Liste
    _SPECIAL, jeder andere Name (z. B. "f8", "insert", "menu") fiel STILL auf die rechte Strg
    zurueck: man drueckte die eingestellte Taste, und nichts geschah. Jetzt: _SPECIAL, dann jeder
    Name aus pynput.keyboard.Key, dann ein einzelnes Zeichen; ein unbekannter Name bekommt eine
    laute Warnung mit den gueltigen Namen. Leer/nicht gesetzt -> ctrl_r ohne Warnung (kein Wert
    ist kein Tippfehler, wie bei snip.key). str(): YAML liest `key: 5` als Zahl, gemeint ist
    die Taste 5 (vorher: AttributeError beim Start)."""
    n = ("" if name is None else str(name)).strip().lower() or _DEFAULT
    if n in _SPECIAL:
        return _SPECIAL[n], n
    key = _pynput_key(n)
    if key is not None:
        return key, n
    if len(n) == 1:
        return keyboard.KeyCode.from_char(n), n
    gueltig = ", ".join(sorted(set(keyboard.Key.__members__) | set(_SPECIAL)))
    print(f"[hotkey] WARNING: unknown key name {name!r} in hotkey.key -> falling back to "
          f"{_DEFAULT!r} (right Ctrl). Valid names: a single character, or {gueltig}")
    return keyboard.Key.ctrl_r, _DEFAULT


def resolve_key(name: str):
    return _resolve(name)[0]


def _vk_code(key_name: str) -> int | None:
    """Windows-Tastencode fuer die physische Gegenprobe: aus pynput (Key.<name>.value.vk), sonst
    aus _VK. None = keiner bekannt (z. B. ein Einzelzeichen), dann gilt die Zeitregel."""
    name = str(key_name or "").strip().lower()
    key = _pynput_key(name)
    vk = getattr(key.value, "vk", None) if key is not None else None
    return vk if isinstance(vk, int) else _VK.get(name)


def _physically_down(key_name: str) -> bool | None:
    """True/False laut Windows, None wenn nicht feststellbar (dann gilt die Zeitregel)."""
    vk = _vk_code(key_name)
    if vk is None:
        return None
    try:
        import ctypes
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:  # noqa: BLE001  (kein Windows / kein ctypes -> Zeitregel)
        return None


class HoldToTalk:
    """Ruft on_press einmal bei Taste-runter, on_release einmal bei Taste-hoch.
    Entprellt gedrueckt-gehalten (kein Repeat-Feuer)."""

    def __init__(self, key_name: str, on_press: Callable[[], None],
                 on_release: Callable[[], None]):
        # Der WIRKSAME Name (nach einem Rueckfall "ctrl_r"): die physische Gegenprobe fragt so
        # die Taste ab, auf die wirklich gehoert wird.
        self._target, self._key_name = _resolve(key_name)
        self._on_press = on_press
        self._on_release = on_release
        self._down = False
        self._last_event = 0.0
        # Wann die Taste zuletzt losgelassen wurde (Listener-Thread) — damit die App messen kann,
        # wie lange der Weg Taste -> Stopp wirklich dauert (Auftrag „reaktiver", 12.09.2026).
        self.last_release_at = 0.0
        self.last_press_at = 0.0
        self._listener: keyboard.Listener | None = None
        # Callbacks laufen im Worker, nicht im pynput-Thread (siehe Modul-Kopf, Punkt 2).
        self._jobs: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stopping = threading.Event()

    @property
    def key_name(self) -> str:
        """Der Name der Taste, auf die wirklich gehoert wird (nach einem Rueckfall "ctrl_r"),
        fuer die Startzeile - nicht der Rohwert aus der Konfiguration."""
        return self._key_name

    def _matches(self, key) -> bool:
        return key == self._target

    def _stale_down(self) -> bool:
        """Haengt das 'Taste ist unten'-Flag, obwohl die Taste laengst oben ist?"""
        if not self._down:
            return False
        phys = _physically_down(self._key_name)
        if phys is False:
            return True
        if phys is True:
            return False
        return (time.time() - self._last_event) > _STUCK_AFTER_S

    def _press(self, key):
        if not self._matches(key):
            return
        if self._down and self._stale_down():
            # Release ist unterwegs verloren gegangen -> Zustand geradeziehen, Druck gilt.
            print("[hotkey] missed key release detected -> state reset")
            self._down = False
        if self._down:
            self._last_event = time.time()   # Auto-Repeat: nur den Zeitstempel auffrischen
            return
        self._down = True
        self._last_event = time.time()
        self.last_press_at = self._last_event
        self._jobs.put("press")

    def _release(self, key):
        if self._matches(key) and self._down:
            self._down = False
            self._last_event = time.time()
            self.last_release_at = self._last_event
            self._jobs.put("release")

    def _run_worker(self) -> None:
        while not self._stopping.is_set():
            try:
                job = self._jobs.get(timeout=0.25)
            except queue.Empty:
                continue
            if job is None:
                break
            try:
                (self._on_press if job == "press" else self._on_release)()
            except Exception as e:  # noqa: BLE001
                print(f"[hotkey] {job} error: {e}")

    def start(self) -> None:
        self._stopping.clear()
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
        self._stopping.set()
        self._jobs.put(None)
        self._worker = None

    def join(self) -> None:
        if self._listener:
            self._listener.join()
