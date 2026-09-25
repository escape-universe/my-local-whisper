"""wf/autostart.py: Tray -> "Mit Windows starten" (Arbeitspaket 7, 25.09.2026).

Kein Test legt eine echte Verknuepfung an und keiner spricht mit COM: APPDATA zeigt immer in
tmp_path, und der COM-Aufruf (_write_link) ist entweder ersetzt oder laeuft gegen Attrappen von
pythoncom/win32com in sys.modules - auch auf einem Windows-Rechner mit echtem pywin32."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from wf import autostart

STARTUP = ("Microsoft", "Windows", "Start Menu", "Programs", "Startup")


@pytest.fixture
def appdata(tmp_path, monkeypatch) -> Path:
    """APPDATA mit Leerzeichen im Pfad (wie C:\\Users\\Max Muster\\AppData\\Roaming)."""
    ordner = tmp_path / "Max Muster" / "AppData" / "Roaming"
    ordner.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(ordner))
    return ordner


@pytest.fixture
def python_ordner(tmp_path) -> Path:
    ordner = tmp_path / "Program Files" / "Python311"
    ordner.mkdir(parents=True)
    (ordner / "python.exe").write_bytes(b"")
    return ordner


@pytest.fixture
def kein_com(monkeypatch) -> list:
    """_write_link ersetzt: merkt sich die Verknuepfung und legt eine leere Datei an."""
    geschrieben: list = []

    def _schreiben(spec):
        geschrieben.append(spec)
        spec.link.write_bytes(b"lnk")

    monkeypatch.setattr(autostart, "_write_link", _schreiben)
    return geschrieben


# --- shortcut_spec: reine Berechnung ------------------------------------------------------------
def test_ziel_ist_pythonw_neben_dem_laufenden_python(appdata, python_ordner, tmp_path):
    (python_ordner / "pythonw.exe").write_bytes(b"")
    projekt = tmp_path / "Eigene Dateien" / "my-local-whisper"
    spec = autostart.shortcut_spec(python_exe=str(python_ordner / "python.exe"), root=projekt)
    assert spec.link == appdata.joinpath(*STARTUP, "my-local-whisper.lnk")
    assert spec.target == str(python_ordner / "pythonw.exe")                  # ohne Anfuehrungszeichen
    assert spec.arguments == f'"{projekt / "whisperflow.py"}"'                  # mit, wegen der Leerzeichen
    assert " " in spec.arguments and spec.arguments.count('"') == 2
    assert spec.workdir == str(projekt)


def test_ohne_pythonw_der_laufende_interpreter(appdata, python_ordner):
    spec = autostart.shortcut_spec(python_exe=str(python_ordner / "python.exe"))
    assert spec.target == str(python_ordner / "python.exe")


def test_laeuft_schon_unter_pythonw(appdata, python_ordner):
    (python_ordner / "pythonw.exe").write_bytes(b"")
    spec = autostart.shortcut_spec(python_exe=str(python_ordner / "pythonw.exe"))
    assert spec.target == str(python_ordner / "pythonw.exe")


def test_standardwerte_kommen_aus_sys_executable_und_dem_projekt(appdata, python_ordner, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(python_ordner / "python.exe"))
    spec = autostart.shortcut_spec()
    assert spec.target == str(python_ordner / "python.exe")
    assert spec.arguments == f'"{autostart.ROOT / "whisperflow.py"}"' and spec.workdir == str(autostart.ROOT)
    assert (autostart.ROOT / "whisperflow.py").is_file()


@pytest.mark.parametrize("appdata_wert", [None, ""])
def test_ohne_appdata_keine_verknuepfung(monkeypatch, appdata_wert):
    if appdata_wert is None:
        monkeypatch.delenv("APPDATA", raising=False)
    else:
        monkeypatch.setenv("APPDATA", appdata_wert)
    assert autostart.shortcut_spec(python_exe="C:/Python311/python.exe") is None
    assert autostart.is_enabled() is False
    assert autostart.set_enabled(True) == "APPDATA is not set, the Startup folder is unknown"


# --- is_enabled / set_enabled -------------------------------------------------------------------
def test_anlegen_und_entfernen(appdata, kein_com):
    link = appdata.joinpath(*STARTUP, "my-local-whisper.lnk")
    assert autostart.is_enabled() is False and not link.parent.exists()
    assert autostart.set_enabled(True) == ""
    assert link.is_file() and autostart.is_enabled() is True        # der Autostart-Ordner wurde angelegt
    assert [s.link for s in kein_com] == [link]
    assert autostart.set_enabled(False) == ""
    assert not link.exists() and autostart.is_enabled() is False
    assert autostart.set_enabled(False) == ""                        # schon aus: kein Fehler


def test_fehler_beim_anlegen_wird_eine_meldung(appdata, monkeypatch):
    def _kaputt(spec):
        raise OSError("Zugriff verweigert")

    monkeypatch.setattr(autostart, "_write_link", _kaputt)
    assert autostart.set_enabled(True) == "Zugriff verweigert"
    assert autostart.is_enabled() is False


def test_ohne_pywin32_eine_meldung_statt_absturz(appdata, monkeypatch):
    """Der echte _write_link, aber pythoncom fehlt (wie auf CI-Runnern ohne pywin32)."""
    monkeypatch.setitem(sys.modules, "pythoncom", None)             # import pythoncom -> ImportError
    grund = autostart.set_enabled(True)
    assert "pythoncom" in grund
    assert autostart.is_enabled() is False


def test_fehler_beim_entfernen_wird_eine_meldung(appdata, kein_com, monkeypatch):
    assert autostart.set_enabled(True) == ""

    def _gesperrt(self, missing_ok=False):
        raise PermissionError("in Benutzung")

    monkeypatch.setattr(Path, "unlink", _gesperrt)
    assert autostart.set_enabled(False) == "in Benutzung"


# --- _write_link: der duenne COM-Aufruf, gegen Attrappen ----------------------------------------
class _Link:
    def __init__(self, pfad):
        self.pfad, self.gespeichert = pfad, False

    def Save(self):
        self.gespeichert = True
        Path(self.pfad).write_bytes(b"lnk")


def _com_attrappen(monkeypatch, init_fehler: bool = False) -> dict:
    protokoll: dict = {"links": [], "init": 0, "uninit": 0, "objekte": []}

    class com_error(Exception):
        pass

    def CoInitialize():
        protokoll["init"] += 1
        if init_fehler:
            raise com_error("RPC_E_CHANGED_MODE")

    def CoUninitialize():
        protokoll["uninit"] += 1

    class _Shell:
        def CreateShortCut(self, pfad):
            link = _Link(pfad)
            protokoll["links"].append(link)
            return link

    def Dispatch(name):
        protokoll["objekte"].append(name)
        return _Shell()

    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize, pythoncom.CoUninitialize, pythoncom.com_error = CoInitialize, CoUninitialize, com_error
    client = types.ModuleType("win32com.client")
    client.Dispatch = Dispatch
    paket = types.ModuleType("win32com")
    paket.client = client
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    monkeypatch.setitem(sys.modules, "win32com", paket)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    return protokoll


def test_write_link_setzt_ziel_argumente_und_arbeitsordner(appdata, python_ordner, monkeypatch, tmp_path):
    protokoll = _com_attrappen(monkeypatch)
    (python_ordner / "pythonw.exe").write_bytes(b"")
    spec = autostart.shortcut_spec(python_exe=str(python_ordner / "python.exe"),
                                   root=tmp_path / "Mein Projekt")
    assert autostart.set_enabled(True, spec) == ""
    [link] = protokoll["links"]
    assert protokoll["objekte"] == ["WScript.Shell"] and link.pfad == str(spec.link)
    assert link.TargetPath == str(python_ordner / "pythonw.exe")
    assert link.Arguments == f'"{tmp_path / "Mein Projekt" / "whisperflow.py"}"'
    assert link.WorkingDirectory == str(tmp_path / "Mein Projekt")
    assert link.gespeichert and autostart.is_enabled(spec)
    assert protokoll["init"] == 1 and protokoll["uninit"] == 0     # COM nie abbauen (siehe _write_link)


def test_write_link_mit_schon_eingerichtetem_com(appdata, python_ordner, monkeypatch):
    """CoInitialize scheitert (Thread hat COM schon mit anderem Modell): trotzdem anlegen, mit
    dem schon eingerichteten COM."""
    protokoll = _com_attrappen(monkeypatch, init_fehler=True)
    spec = autostart.shortcut_spec(python_exe=str(python_ordner / "python.exe"))
    assert autostart.set_enabled(True, spec) == ""
    assert protokoll["links"][0].gespeichert and protokoll["uninit"] == 0
