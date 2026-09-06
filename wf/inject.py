"""S7 — Text-Injektion am Cursor.

DEFAULT (seit 05.09.2026): clipboard_only — Text NUR in die Zwischenablage legen, der Nutzer
fuegt selbst mit Strg+V ein (weiterarbeiten waehrend der Verarbeitung moeglich).
AUTO-PASTE: Clipboard + Ctrl+V mit Save/Restore (umlaut-sicher, R2/R3).
FALLBACK: KEYEVENTF_UNICODE SendInput (fuer Terminals, die Paste blocken).
NIE pynput.type() (korrumpiert Umlaute).
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from typing import Any

if sys.platform == "win32":
    import win32clipboard
    import win32con

# ---------- Clipboard ----------

def _clip_get() -> tuple[Any, int] | tuple[None, None]:
    """Aktuellen Clipboard-Inhalt sichern (Unicode-Text) + Format. None wenn leer/anders."""
    try:
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return data, win32con.CF_UNICODETEXT
        finally:
            win32clipboard.CloseClipboard()
    except Exception:  # noqa: BLE001
        pass
    return None, None


def _clip_set(text: str) -> None:
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


def _clip_restore(data, fmt) -> None:
    if data is None:
        return
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(data, fmt)
        finally:
            win32clipboard.CloseClipboard()
    except Exception:  # noqa: BLE001
        pass


# ---------- SendInput (Unicode + Ctrl+V) ----------

_INPUT_KEYBOARD = 1
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004
_VK_CONTROL = 0x11
_VK_V = 0x56


_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", _ULONG_PTR)]


class _MOUSEINPUT(ctypes.Structure):
    # Nur da, damit die Union die volle INPUT-Groesse (40 Byte auf x64) hat.
    # Ohne diesen groesseren Member ist sizeof(INPUT) zu klein und SendInput
    # verwirft den Aufruf still (cbSize-Mismatch) -> nichts wird getippt.
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", _ULONG_PTR)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(inputs: list[_INPUT]) -> int:
    n = len(inputs)
    arr = (_INPUT * n)(*inputs)
    sent = ctypes.windll.user32.SendInput(n, arr, ctypes.sizeof(_INPUT))
    if sent != n:
        err = ctypes.windll.kernel32.GetLastError()
        print(f"[inject] WARN: SendInput sendete {sent}/{n} Events (GetLastError={err})")
    return sent


def _key_unicode(ch: str) -> list[_INPUT]:
    code = ord(ch)
    down = _INPUT(type=_INPUT_KEYBOARD,
                 ki=_KEYBDINPUT(0, code, _KEYEVENTF_UNICODE, 0, 0))
    up = _INPUT(type=_INPUT_KEYBOARD,
               ki=_KEYBDINPUT(0, code, _KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP, 0, 0))
    return [down, up]


def _vk(vk: int, up: bool) -> _INPUT:
    flags = _KEYEVENTF_KEYUP if up else 0
    return _INPUT(type=_INPUT_KEYBOARD, ki=_KEYBDINPUT(vk, 0, flags, 0, 0))


def type_unicode(text: str) -> None:
    """Tippt text via KEYEVENTF_UNICODE — layout-unabhaengig, Umlaut-sicher."""
    inputs: list[_INPUT] = []
    for ch in text:
        if ch == "\n":
            inputs.append(_vk(0x0D, False)); inputs.append(_vk(0x0D, True))  # Enter
            continue
        inputs.extend(_key_unicode(ch))
    if inputs:
        _send(inputs)


def paste_ctrl_v() -> None:
    """Strg+V an das aktive Fenster schicken (Hybrid-Modus, Zwischenablage ist schon gesetzt)."""
    _paste_ctrl_v()


def _paste_ctrl_v() -> None:
    _send([_vk(_VK_CONTROL, False), _vk(_VK_V, False),
           _vk(_VK_V, True), _vk(_VK_CONTROL, True)])


def to_clipboard(text: str) -> bool:
    """clipboard_only: Text in die Zwischenablage legen, NICHT einfuegen, NICHT wiederherstellen.
    Rueckgabe: True wenn die Zwischenablage den Text danach wirklich traegt (Rueck-Lesen)."""
    if not text:
        return False
    for attempt in range(3):  # Clipboard kann kurz von einer anderen App gesperrt sein
        try:
            _clip_set(text)
            back, _ = _clip_get()
            return back == text
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                print(f"[inject] clipboard not writable: {e}")
                return False
            time.sleep(0.05)
    return False


def inject(text: str, method: str = "clipboard_only", restore_delay_ms: int = 120) -> bool:
    """Text am Cursor einfuegen bzw. bereitlegen. method: 'clipboard_only' | 'clipboard' | 'sendinput'.
    Rueckgabe: True wenn der Schritt nachweislich lief (bei clipboard_only: Rueck-Lesen der Zwischenablage)."""
    if not text:
        return False
    if sys.platform != "win32":
        raise RuntimeError("Injektion nur auf Windows implementiert.")
    if method == "clipboard_only":
        return to_clipboard(text)
    if method == "sendinput":
        type_unicode(text)
        return True
    # Clipboard-Paste mit Save/Restore
    old, fmt = _clip_get()
    _clip_set(text)
    time.sleep(0.02)
    _paste_ctrl_v()
    time.sleep(max(restore_delay_ms, 0) / 1000.0)
    _clip_restore(old, fmt)
    return True
