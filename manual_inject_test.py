"""Manueller Injektions-Test — interaktiv auszufuehren.

Warum manuell: Die automatisierte Test-Umgebung liefert keine synthetischen
Tastatureingaben (SendInput/Ctrl+V landen nicht). Wenn DU es startest, ist das
Ziel-Fenster echt im Vordergrund und die Injektion greift.

Ablauf:
    py manual_inject_test.py
-> oeffnet Notepad, zaehlt 4 s runter (Zeit, nichts anzufassen),
   fuegt erst per Clipboard-Paste, dann per SendInput je einen Umlaut-Satz ein,
   liest via WM_GETTEXT zurueck und sagt PASS/FAIL.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time

from wf import inject as ij

u32 = ctypes.windll.user32
WM_GETTEXT, WM_SETTEXT, WM_CLOSE = 0x000D, 0x000C, 0x0010
SAMPLE = "Grüße äöüß, der Besprechungsraum in Nienburg ist ausgebucht."


def _fg(hwnd: int) -> None:
    k32 = ctypes.windll.kernel32
    fg = u32.GetForegroundWindow()
    ft = u32.GetWindowThreadProcessId(fg, None)
    ot = k32.GetCurrentThreadId()
    u32.AttachThreadInput(ot, ft, True)
    try:
        u32.ShowWindow(hwnd, 9); u32.BringWindowToTop(hwnd); u32.SetForegroundWindow(hwnd)
    finally:
        u32.AttachThreadInput(ot, ft, False)


def run() -> int:
    proc = subprocess.Popen(["notepad.exe"])
    np_hwnd = 0
    for _ in range(40):
        time.sleep(0.1)
        np_hwnd = u32.FindWindowW("Notepad", None)
        if np_hwnd:
            break
    edit = u32.FindWindowExW(np_hwnd, 0, "Edit", None) if np_hwnd else 0
    if not edit:
        print("Klassisches Notepad-Edit-Control nicht gefunden (Win11-UWP-Notepad?).")
        print("Test alternativ manuell: irgendein Textfeld fokussieren und Diktat starten.")
        return 2
    print("Notepad offen. NICHT anfassen — Test laeuft in:")
    for i in range(4, 0, -1):
        print(f"  {i} ...", flush=True); time.sleep(1)

    k32 = ctypes.windll.kernel32
    results = []
    for method in ("clipboard", "sendinput"):
        u32.SendMessageW(edit, WM_SETTEXT, 0, ctypes.c_wchar_p(""))
        # robuste Fokus-Uebergabe: an Notepads GUI-Thread attachen, waehrend wir fokussieren + injizieren
        our = k32.GetCurrentThreadId(); tgt = u32.GetWindowThreadProcessId(np_hwnd, None)
        u32.AttachThreadInput(our, tgt, True)
        try:
            u32.ShowWindow(np_hwnd, 9); u32.BringWindowToTop(np_hwnd)
            u32.SetForegroundWindow(np_hwnd); u32.SetFocus(edit); time.sleep(0.3)
            ij.inject(SAMPLE, method=method, restore_delay_ms=150)
            time.sleep(0.6)
        finally:
            u32.AttachThreadInput(our, tgt, False)
        buf = ctypes.create_unicode_buffer(1024)
        u32.SendMessageW(edit, WM_GETTEXT, 1024, buf)
        ok = buf.value == SAMPLE
        results.append((method, ok, buf.value))
        print(f"[{'PASS' if ok else 'FAIL'}] {method:10} -> {buf.value!r}")

    u32.SendMessageW(edit, WM_SETTEXT, 0, ctypes.c_wchar_p(""))
    u32.PostMessageW(np_hwnd, WM_CLOSE, 0, 0)
    time.sleep(0.3); proc.terminate()
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(run())
