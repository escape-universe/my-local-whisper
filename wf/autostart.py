"""Mit Windows starten (Arbeitspaket 7, 25.09.2026): eine Verknuepfung im Autostart-Ordner des
Benutzers, ein Haken im Tray.

Bisher verlangte der Autostart Handarbeit in der Aufgabenplanung (README), und das Start-Skript
start-whisperflow-silent.vbs setzt auf VBScript, das Microsoft abkuendigt. Jetzt legt der
Tray-Eintrag "Mit Windows starten" die Verknuepfung
    %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\my-local-whisper.lnk
an bzw. loescht sie. Der Ordner gehoert dem Benutzer (kein Administrator noetig), und die App
startet damit ohne Administratorrechte, sonst blockiert Windows das Einfuegen in normale
Programme. Ziel ist pythonw.exe neben dem laufenden Python (kein Konsolenfenster), Argument
whisperflow.py mit vollem Pfad, Arbeitsordner das Projekt.

Aufbau: shortcut_spec() rechnet Pfad und Ziel aus (rein, ohne Windows testbar), _write_link()
ist der duenne COM-Aufruf (WScript.Shell ueber pywin32, keine neue Abhaengigkeit), set_enabled()
faengt jeden Fehler ab und gibt ihn als Text zurueck (Meldung im Tray statt Absturz).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
LINK_NAME = "my-local-whisper.lnk"
_STARTUP = ("Microsoft", "Windows", "Start Menu", "Programs", "Startup")


class Shortcut(NamedTuple):
    link: Path        # ...\Startup\my-local-whisper.lnk
    target: str       # pythonw.exe; OHNE Anfuehrungszeichen, WScript.Shell setzt TargetPath selbst richtig
    arguments: str    # "C:\...\whisperflow.py"; MIT Anfuehrungszeichen, der Pfad kann Leerzeichen haben
    workdir: str      # Projektordner


def shortcut_spec(appdata: str | None = None, python_exe: str | None = None,
                  root: Path | None = None) -> Shortcut | None:
    """Wohin die Verknuepfung gehoert und was sie startet. None, wenn APPDATA fehlt (dann ist
    der Autostart-Ordner unbekannt) oder kein Python-Pfad bekannt ist.
    appdata/python_exe/root = None: os.environ["APPDATA"], sys.executable, der Projektordner.
    Ziel: pythonw.exe im Ordner des laufenden Pythons (auch in einem venv), fehlt es, der
    laufende Interpreter selbst."""
    appdata = os.environ.get("APPDATA", "") if appdata is None else appdata
    exe = python_exe if python_exe is not None else (sys.executable or "")
    if not appdata or not exe:
        return None
    root = root or ROOT
    pythonw = Path(exe).with_name("pythonw.exe")
    return Shortcut(link=Path(appdata).joinpath(*_STARTUP, LINK_NAME),
                    target=str(pythonw if pythonw.is_file() else Path(exe)),
                    arguments=f'"{root / "whisperflow.py"}"',
                    workdir=str(root))


def is_enabled(spec: Shortcut | None = None) -> bool:
    """Haken im Tray: gibt es die Verknuepfung?"""
    spec = spec or shortcut_spec()
    return bool(spec and spec.link.is_file())


def set_enabled(on: bool, spec: Shortcut | None = None) -> str:
    """Verknuepfung anlegen (on) oder loeschen. Rueckgabe: '' = erledigt, sonst der Grund."""
    spec = spec or shortcut_spec()
    if spec is None:
        return "APPDATA is not set, the Startup folder is unknown"
    try:
        if on:
            spec.link.parent.mkdir(parents=True, exist_ok=True)
            _write_link(spec)
        elif spec.link.exists():
            spec.link.unlink()
        return ""
    except Exception as e:  # noqa: BLE001 - Meldung im Tray statt eines Absturzes der App
        return str(e) or type(e).__name__


def _write_link(spec: Shortcut) -> None:
    """Die .lnk-Datei ueber WScript.Shell (pywin32). Duenn gehalten: alles Pruefbare steckt in
    shortcut_spec(). COM muss im aufrufenden Thread (Tray-Menue) eingerichtet sein. Ist es dort
    schon mit einem anderen Modell eingerichtet, scheitert CoInitialize, und das bestehende wird
    benutzt. Bewusst kein CoUninitialize: es entlaedt die COM-DLLs des Threads, und die Objekte
    hier werden erst danach freigegeben (bei einem Fehler haelt der Traceback sie noch) - ein
    Absturz-Risiko fuer die ganze App. Eingerichtet zu bleiben kostet nichts."""
    import pythoncom
    from win32com.client import Dispatch
    try:
        pythoncom.CoInitialize()
    except pythoncom.com_error:
        pass
    link = Dispatch("WScript.Shell").CreateShortCut(str(spec.link))
    link.TargetPath = spec.target
    link.Arguments = spec.arguments
    link.WorkingDirectory = spec.workdir
    link.Description = "my-local-whisper"
    link.Save()
