"""Kleines Anzeigefeld neben dem Mauszeiger (Tk, eigener Thread).

Zustaende:
  hidden      nichts sichtbar
  recording   roter Punkt + Sekunden   (waehrend der Aufnahme)
  processing  Fortschrittsring + Prozent + Text ("hoere zu", "raeume auf")
  done        kurzer gruener Haken + Text ("Pasted" / "Ready - press Ctrl+V"), blendet nach ~1,2 s aus
  error       roter Text, blendet nach ~2 s aus

Das Fenster ist rahmenlos, immer oben, klick-durchlaessig (WS_EX_TRANSPARENT) und nimmt nie den Fokus
(WS_EX_NOACTIVATE), damit es beim Einfuegen nicht das Textfeld stoert. Der Prozentwert ist eine
Schaetzung aus Audio-Laenge und Wortzahl (steigt bis 95 %, springt bei Fertig auf 100).
Alle Tk-Aufrufe laufen im Overlay-Thread; die App setzt nur Zustandswerte.
"""
from __future__ import annotations

import math
import sys
import threading
import time

from wf import i18n

_OFFSET = (22, 24)      # Abstand vom Mauszeiger (Pixel)
_W, _H = 150, 30


class Overlay:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled and sys.platform == "win32"
        self._lock = threading.Lock()
        self._state = "hidden"
        self._text = ""
        self._pct = 0.0
        self._t0 = 0.0
        self._eta = 1.0
        self._until = 0.0
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    # ---- API fuer die App (thread-sicher) ----
    def start(self) -> None:
        if not self.enabled or self._thread:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="overlay")
        self._thread.start()
        self._ready.wait(3)

    def recording(self) -> None:
        with self._lock:
            self._state, self._t0, self._text = "recording", time.time(), ""

    def processing(self, eta_s: float, text: str = "") -> None:
        text = text or i18n.t("badge_listening")
        with self._lock:
            self._state, self._t0, self._eta, self._text, self._pct = "processing", time.time(), max(0.3, eta_s), text, 0.0

    def phase(self, text: str, eta_left_s: float | None = None) -> None:
        """Text unter dem Ring aendern; optional die Restschaetzung nachziehen."""
        with self._lock:
            if self._state != "processing":
                return
            self._text = text
            if eta_left_s is not None:
                done = self._elapsed_pct()
                self._t0 = time.time() - done * 0.01 * max(0.3, eta_left_s) / max(0.01, 1 - done * 0.01)
                self._eta = (time.time() - self._t0) + max(0.3, eta_left_s)

    def done(self, text: str = "", seconds: float = 1.3) -> None:
        text = text or i18n.t("badge_ready")
        with self._lock:
            self._state, self._text, self._pct, self._until = "done", text, 100.0, time.time() + seconds

    def notice(self, text: str, seconds: float = 3.0) -> None:
        """Neutrale Ansage (blau, kein Fehler) — z.B. „loslassen fuer den Ausschnitt", waehrend
        die Ausloese-Taste gehalten wird. Verdraengt keine laufende Verarbeitung."""
        with self._lock:
            if self._state == "processing":
                return
            self._state, self._text, self._until = "notice", text, time.time() + seconds

    def error(self, text: str = "", seconds: float = 2.0) -> None:
        text = text or i18n.t("badge_error")
        with self._lock:
            self._state, self._text, self._until = "error", text, time.time() + seconds

    def hide(self) -> None:
        with self._lock:
            self._state = "hidden"

    # ---- intern ----
    def _elapsed_pct(self) -> float:
        el = time.time() - self._t0
        # weiche Kurve: schnell am Anfang, kriecht auf 95 zu
        return min(95.0, 100.0 * (1 - math.exp(-2.2 * el / self._eta)))

    def _run(self) -> None:
        try:
            import tkinter as tk
            import win32api
            import win32con
            import win32gui
        except Exception as e:  # noqa: BLE001
            print(f"[overlay] not available: {e}")
            self.enabled = False
            self._ready.set()
            return
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.94)
        key = "#ff00fe"
        root.configure(bg=key)
        root.attributes("-transparentcolor", key)
        cv = tk.Canvas(root, width=_W, height=_H, bg=key, highlightthickness=0)
        cv.pack()
        root.geometry(f"{_W}x{_H}+-2000+-2000")
        root.update_idletasks()
        hwnd = int(root.winfo_id())
        hwnd = win32gui.GetParent(hwnd) or hwnd
        ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex |= win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex)
        root.withdraw()
        self._ready.set()
        visible = False

        def tick():
            nonlocal visible
            with self._lock:
                state, text, t0, until = self._state, self._text, self._t0, self._until
                pct = self._elapsed_pct() if state == "processing" else self._pct
            if state in ("done", "error", "notice") and time.time() > until:
                self._state = state = "hidden"
            if state == "hidden":
                if visible:
                    root.withdraw(); visible = False
                root.after(80, tick)
                return
            try:
                x, y = win32api.GetCursorPos()
            except Exception:  # noqa: BLE001
                x, y = 0, 0
            root.geometry(f"{_W}x{_H}+{x + _OFFSET[0]}+{y + _OFFSET[1]}")
            if not visible:
                root.deiconify()
                win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                      win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                visible = True
            cv.delete("all")
            cv.create_rounded = None
            # Hintergrund-Pille
            cv.create_oval(0, 0, _H, _H, fill="#1e1e1e", outline="")
            cv.create_oval(_W - _H, 0, _W, _H, fill="#1e1e1e", outline="")
            cv.create_rectangle(_H // 2, 0, _W - _H // 2, _H, fill="#1e1e1e", outline="")
            cx, cy, r = 15, 15, 9
            if state == "recording":
                blink = int(time.time() * 2) % 2 == 0
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#e03c3c" if blink else "#7a2020", outline="")
                s = int(time.time() - t0)
                label = f"Aufnahme {s // 60}:{s % 60:02d}"
            elif state == "processing":
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#555555", width=3)
                cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=-360 * pct / 100,
                              style="arc", outline="#4da3ff", width=3)
                label = f"{int(pct)} %  {text}"
            elif state == "done":
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#3cb44b", outline="")
                cv.create_line(cx - 5, cy, cx - 1, cy + 4, cx + 6, cy - 5, fill="white", width=2)
                label = text
            elif state == "notice":
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#4da3ff", outline="")
                cv.create_rectangle(cx - 4, cy - 3, cx + 4, cy + 4, outline="white", width=2)
                label = text
            else:  # error
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#e03c3c", outline="")
                cv.create_text(cx, cy, text="!", fill="white", font=("Segoe UI", 10, "bold"))
                label = text
            cv.create_text(32, _H // 2, text=label, anchor="w", fill="white", font=("Segoe UI", 9))
            root.after(50, tick)

        root.after(50, tick)
        root.mainloop()


def estimate_seconds(tail_audio_s: float, pending_stream_s: float = 0.0) -> float:
    """Schaetzung fuer den Ring: Whisper ~0,1x Audio + Cleanup ~0,03 s/Wort (2,5 Woerter/s) + Grundkosten."""
    words = tail_audio_s * 2.5
    return 0.6 + tail_audio_s * 0.1 + words * 0.03 + pending_stream_s * 0.13
