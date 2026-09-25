"""Nur eine laufende Tray-App (Arbeitspaket 7, 25.09.2026).

Zwei gleichzeitig laufende Instanzen hoeren beide auf die Diktat-Taste: jedes Diktat kaeme doppelt
an bzw. wuerde doppelt eingefuegt. start-whisperflow.bat beendet alte Instanzen vor dem Start,
ein direkter Start (py whisperflow.py, die Autostart-Verknuepfung, dazu noch eine Aufgabe in der
Aufgabenplanung) bisher nicht.

Mittel: ein benannter Mutex (kernel32.CreateMutexW). Existiert er schon (GetLastError() ==
ERROR_ALREADY_EXISTS), laeuft eine andere Instanz, und diese hier beendet sich, ohne die erste
anzufassen. Windows schliesst den Handle beim Prozessende selbst, auch nach einem Absturz oder
Stop-Process; danach darf die naechste Instanz starten. "Local\\" = pro Windows-Sitzung: zwei
angemeldete Benutzer haben je ihre eigene Tastatur und ihr eigenes Tray.
"""
from __future__ import annotations

MUTEX_NAME = "Local\\my-local-whisper"
ERROR_ALREADY_EXISTS = 183

#: Handle des eigenen Mutex, solange diese Instanz laeuft. Absichtlich nie geschlossen und hier
#: festgehalten: der Mutex soll bis zum Programmende bestehen.
_handle = None


def acquire(name: str = MUTEX_NAME) -> bool:
    """True = diese Instanz darf laufen (die erste, oder ohne Windows, oder der Mutex liess sich
    nicht anlegen - dann lieber ungeschuetzt starten als gar nicht). False = eine andere laeuft
    schon."""
    global _handle
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        # Beide Funktionen VOR dem Aufruf holen: zwischen CreateMutexW und GetLastError soll kein
        # weiterer Windows-Aufruf (etwa das Nachschlagen der Funktion) den Fehlercode ueberschreiben.
        create_mutex, last_error = kernel32.CreateMutexW, kernel32.GetLastError
    except Exception:  # noqa: BLE001 - kein Windows: kein Mutex, kein Fehler
        return True
    handle = create_mutex(None, False, name)
    fehler = last_error()
    if not handle:
        print(f"[app] WARN: single-instance lock not available (Windows error {fehler}) -> starting anyway")
        return True
    if fehler == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)      # nur der eigene Verweis; der Mutex der ersten bleibt
        return False
    _handle = handle
    return True
