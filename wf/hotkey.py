"""S1 — Globaler Hold-to-talk-Hotkey (pynput).

Erkennt Key-Down/Key-Up einer konfigurierten Taste systemweit. Ruft on_press/on_release.
Kein Admin noetig zum Lauschen (nur zum Suppress, was wir nicht tun).
"""
from __future__ import annotations

from typing import Callable

from pynput import keyboard

# Erlaubte Hotkey-Namen -> pynput Key
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


def resolve_key(name: str):
    name = (name or "ctrl_r").strip().lower()
    if name in _SPECIAL:
        return _SPECIAL[name]
    # einzelnes Zeichen
    if len(name) == 1:
        return keyboard.KeyCode.from_char(name)
    return keyboard.Key.ctrl_r  # Fallback


class HoldToTalk:
    """Ruft on_press einmal bei Taste-runter, on_release einmal bei Taste-hoch.
    Entprellt gedrueckt-gehalten (kein Repeat-Feuer)."""

    def __init__(self, key_name: str, on_press: Callable[[], None],
                 on_release: Callable[[], None]):
        self._target = resolve_key(key_name)
        self._on_press = on_press
        self._on_release = on_release
        self._down = False
        self._listener: keyboard.Listener | None = None

    def _matches(self, key) -> bool:
        return key == self._target

    def _press(self, key):
        if self._matches(key) and not self._down:
            self._down = True
            try:
                self._on_press()
            except Exception as e:  # noqa: BLE001
                print(f"[hotkey] on_press error: {e}")

    def _release(self, key):
        if self._matches(key) and self._down:
            self._down = False
            try:
                self._on_release()
            except Exception as e:  # noqa: BLE001
                print(f"[hotkey] on_release error: {e}")

    def start(self) -> None:
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None

    def join(self) -> None:
        if self._listener:
            self._listener.join()
