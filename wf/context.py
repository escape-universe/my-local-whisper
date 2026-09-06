"""S6 — Kontext-Auswahl: fokussierte App -> Kategorie.

GetForegroundWindow -> Prozessname -> Kategorie (chat/email/code/default).
Deterministisch, kein LLM. Auch Integrity-Level-Check fuers UIPI-Handling (R1).
"""
from __future__ import annotations

import sys
from typing import Any

if sys.platform == "win32":
    import win32gui
    import win32process
    try:
        import psutil  # optional, schneller Prozessname
    except Exception:  # noqa: BLE001
        psutil = None
    import ctypes
    from ctypes import wintypes


def _process_name_for_hwnd(hwnd: int) -> str:
    """Prozessname (lowercase, ohne .exe) des Fensters — ctypes-Fallback ohne psutil."""
    if sys.platform != "win32":
        return ""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except Exception:  # noqa: BLE001
        return ""
    if psutil is not None:
        try:
            name = psutil.Process(pid).name()
            return name.lower().removesuffix(".exe")
        except Exception:  # noqa: BLE001
            pass
    # ctypes-Fallback: QueryFullProcessImageName
    PROCESS_QUERY_LIMITED = 0x1000
    kernel32 = ctypes.windll.kernel32
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            path = buf.value
            base = path.rsplit("\\", 1)[-1]
            return base.lower().removesuffix(".exe")
    finally:
        kernel32.CloseHandle(h)
    return ""


def foreground_info(cfg: dict[str, Any]) -> dict[str, Any]:
    """Returns {process, title, category, method_override}."""
    if sys.platform != "win32":
        return {"process": "", "title": "", "category": "default", "method_override": None}
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd)
    except Exception:  # noqa: BLE001
        hwnd, title = 0, ""
    proc = _process_name_for_hwnd(hwnd) if hwnd else ""
    cats = (cfg.get("context", {}) or {}).get("app_categories", {}) or {}
    category = cats.get(proc, "default")
    method_override = (cfg.get("inject", {}) or {}).get("per_app_method", {}).get(proc)
    return {"process": proc, "title": title, "category": category,
            "method_override": method_override, "hwnd": hwnd}


def is_foreground_elevated() -> bool:
    """True wenn das Vordergrundfenster einem elevated (Admin) Prozess gehoert und WIR nicht.
    Dann schluckt Windows (UIPI) unsere Injektion still (R1)."""
    if sys.platform != "win32":
        return False
    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return _pid_is_elevated(pid) and not _pid_is_elevated(None)
    except Exception:  # noqa: BLE001
        return False


def _pid_is_elevated(pid: int | None) -> bool:
    """Token-Elevation eines Prozesses (pid=None -> eigener Prozess)."""
    if sys.platform != "win32":
        return False
    advapi32 = ctypes.windll.advapi32
    kernel32 = ctypes.windll.kernel32
    PROCESS_QUERY_LIMITED = 0x1000
    TOKEN_QUERY = 0x0008
    TokenElevation = 20
    if pid is None:
        hproc = kernel32.GetCurrentProcess()
        close = False
    else:
        hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
        close = True
    if not hproc:
        return False
    try:
        htok = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(hproc, TOKEN_QUERY, ctypes.byref(htok)):
            return False
        try:
            elevation = wintypes.DWORD()
            ret = wintypes.DWORD()
            if advapi32.GetTokenInformation(htok, TokenElevation,
                                            ctypes.byref(elevation),
                                            ctypes.sizeof(elevation),
                                            ctypes.byref(ret)):
                return bool(elevation.value)
        finally:
            kernel32.CloseHandle(htok)
    finally:
        if close:
            kernel32.CloseHandle(hproc)
    return False
