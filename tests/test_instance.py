"""wf/instance.py: nur eine laufende Tray-App (Arbeitspaket 7, 25.09.2026).

kernel32 ist IMMER eine Attrappe (ctypes.windll per monkeypatch), auch auf dem Windows-Runner:
sonst legte der Test dort einen echten Mutex an. Der Nicht-Windows-Fall entfernt ctypes.windll
ausdruecklich, statt sich darauf zu verlassen, dass es unter Linux fehlt."""
from __future__ import annotations

import ctypes
import types

import pytest

from wf import instance


class _Kernel32:
    """Benannte Mutexe im Speicher, wie Windows sie fuehrt: CreateMutexW legt an oder oeffnet den
    vorhandenen (letzter Fehler 183), CloseHandle schliesst nur diesen einen Verweis."""

    def __init__(self, scheitert: bool = False):
        self.offen: dict[int, str] = {}           # Handle -> Name
        self.letzter_fehler = 0
        self.scheitert = scheitert
        self._naechster = 0x100

    def CreateMutexW(self, attribute, besitzer, name):
        if self.scheitert:
            self.letzter_fehler = 5               # ERROR_ACCESS_DENIED
            return 0
        self.letzter_fehler = 183 if name in self.offen.values() else 0
        self._naechster += 4
        self.offen[self._naechster] = name
        return self._naechster

    def GetLastError(self):
        return self.letzter_fehler

    def CloseHandle(self, handle):
        del self.offen[handle]
        return 1

    def gibt_es(self, name) -> bool:
        return name in self.offen.values()


@pytest.fixture
def kernel32(monkeypatch) -> _Kernel32:
    k = _Kernel32()
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(kernel32=k), raising=False)
    monkeypatch.setattr(instance, "_handle", None)
    return k


def test_erste_instanz_darf_laufen_und_haelt_den_mutex(kernel32):
    assert instance.acquire() is True
    assert kernel32.gibt_es("Local\\my-local-whisper")
    assert instance._handle in kernel32.offen            # bis Programmende festgehalten, nicht geschlossen


def test_zweite_instanz_erkennt_die_erste_und_laesst_sie_in_ruhe(kernel32):
    assert instance.acquire() is True                    # die erste (zum Beispiel ueber den Autostart)
    erster = instance._handle
    assert instance.acquire() is False                   # die zweite: laeuft schon
    assert instance._handle == erster                    # der Mutex der ersten bleibt ihrer ...
    assert list(kernel32.offen) == [erster]              # ... der eigene Verweis der zweiten ist zu


def test_nach_dem_ende_der_ersten_darf_eine_neue_starten(kernel32):
    assert instance.acquire() is True
    kernel32.CloseHandle(instance._handle)               # Prozessende: Windows schliesst den Handle
    assert instance.acquire() is True


def test_ohne_windows_kein_mutex_kein_fehler(monkeypatch, capsys):
    monkeypatch.delattr(ctypes, "windll", raising=False)
    monkeypatch.setattr(instance, "_handle", None)
    assert instance.acquire() is True
    assert instance._handle is None and capsys.readouterr().out == ""


def test_mutex_nicht_moeglich_startet_trotzdem_mit_warnung(monkeypatch, capsys):
    k = _Kernel32(scheitert=True)
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(kernel32=k), raising=False)
    monkeypatch.setattr(instance, "_handle", None)
    assert instance.acquire() is True
    assert "single-instance lock not available (Windows error 5)" in capsys.readouterr().out
