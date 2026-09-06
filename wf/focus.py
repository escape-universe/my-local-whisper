"""Erkennt, ob gerade ein beschreibbares Textfeld den Fokus hat (fuer den Hybrid-Modus).

Weg: Windows UI Automation (Paket `uiautomation`). Das fokussierte Element muss ein Edit/Document/
ComboBox-Control sein und darf nicht read-only sein. Chromium-Apps (Chrome, Slack, VS Code, Claude)
melden das erst, nachdem sie einmal von einem UIA-Client angefragt wurden — deshalb wird beim App-Start
einmal angefragt (Warmup) und im Zweifel ein zweiter Versuch nach kurzer Pause gemacht.
Gemessen 05.09.2026: Notepad Edit -> True; Explorer-Dateiliste -> False; Chrome textarea -> True
(ab der 2. Anfrage); Chrome Tab-Button -> False; Konsole -> False.

Regel: Unklar = False. Lieber einmal nicht automatisch einfuegen als in ein falsches Fenster tippen.
"""
from __future__ import annotations

import sys
import time
from typing import Any

_EDITABLE_TYPES = {"EditControl", "DocumentControl", "ComboBoxControl"}


def _query() -> dict[str, Any]:
    import uiautomation as ua
    el = ua.GetFocusedControl()
    if el is None:
        return {"editable": False, "type": None, "why": "kein fokussiertes Element"}
    ctype = el.ControlTypeName
    if ctype not in _EDITABLE_TYPES:
        return {"editable": False, "type": ctype, "why": f"{ctype} ist kein Textfeld"}
    try:
        vp = el.GetValuePattern()
        if vp is not None and vp.IsReadOnly:
            return {"editable": False, "type": ctype, "why": "Feld ist read-only"}
    except Exception:  # noqa: BLE001
        pass  # kein ValuePattern -> DocumentControl ohne Pattern gilt als beschreibbar
    return {"editable": True, "type": ctype, "why": "Textfeld mit Fokus"}


def editable_focus(retry_delay_s: float = 0.25) -> dict[str, Any]:
    """{editable: bool, type: str|None, why: str}. Fehler -> editable False."""
    if sys.platform != "win32":
        return {"editable": False, "type": None, "why": "nicht Windows"}
    try:
        info = _query()
        if not info["editable"] and info["type"] in (None, "PaneControl", "WindowControl"):
            # Chromium-Fall: Barrierefreiheit wird durch die erste Anfrage erst eingeschaltet
            time.sleep(retry_delay_s)
            info = _query()
        return info
    except Exception as e:  # noqa: BLE001
        return {"editable": False, "type": None, "why": f"UIA-Fehler: {e}"}


def warmup() -> None:
    """Einmal anfragen, damit Chromium-Apps ihre Barrierefreiheit einschalten (kostet ~50 ms)."""
    try:
        _query()
    except Exception:  # noqa: BLE001
        pass
