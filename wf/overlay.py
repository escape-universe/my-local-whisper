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
from typing import Callable

from wf import i18n

_OFFSET = (22, 24)      # Abstand vom Mauszeiger (Pixel)
# Das Feld waechst mit dem Text (24.09.2026). Vorher war es fest 150 px breit, und schon das
# englische "Ready - Ctrl+V (appended)" wurde zu "Ready - Ctrl+V (appe" abgeschnitten. 150 px
# bleibt die Mindestbreite (deutsche Texte passen ohne Wachsen hinein, tests/test_i18n.py),
# 300 px die Obergrenze; was selbst dort nicht passt, wird mit „…" gekuerzt (fit_label).
_W_MIN, _W_MAX, _H = 150, 300, 30
_TEXT_X = 32            # hier beginnt der Text, links davon Punkt, Ring oder Haken
_TEXT_RAND = 6          # Luft zwischen Textende und rechtem Feldrand


class Overlay:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled and sys.platform == "win32"
        self._lock = threading.Lock()
        self._state = "hidden"
        self._text = ""
        self._pct = 0.0
        self._t0 = 0.0
        self._eta = 1.0
        self._pct_floor = 0.0       # darunter faellt der Ring nicht mehr (phase() mit Restschaetzung)
        self._until = 0.0
        self._stop_until = 0.0      # bis dahin zeigt "processing" das Stopp-Zeichen statt des Rings
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
        self._note("recording")
        with self._lock:
            self._state, self._t0, self._text = "recording", time.time(), ""

    #: So lange zeigt das Feld direkt nach dem Loslassen „Aufnahme aus" statt des Fortschrittsrings.
    #: Kurz genug, dass es den Fortschritt nicht verdeckt, lang genug, dass man es im Augenwinkel sieht.
    STOP_HINT_S = 0.6

    def processing(self, eta_s: float, text: str = "") -> None:
        text = text or i18n.t("badge_listening")
        self._note("processing", "eta %.1f s" % eta_s)
        with self._lock:
            self._state, self._t0, self._eta, self._text, self._pct = "processing", time.time(), max(0.3, eta_s), text, 0.0
            self._pct_floor = 0.0
            # Der Moment des Loslassens bekommt eine eigene Aussage (13.09.2026): erst „Aufnahme aus",
            # dann der Ring. Ohne das war der Wechsel aus dem Augenwinkel nicht erkennbar.
            self._stop_until = time.time() + self.STOP_HINT_S

    def phase(self, text: str, eta_left_s: float | None = None) -> None:
        """Text unter dem Ring aendern; optional die Restschaetzung nachziehen."""
        with self._lock:
            if self._state != "processing":
                return
            self._text = text
            if eta_left_s is not None:
                # Der Ring laeuft dabei nie rueckwaerts (24.09.2026): die Kurve wird so verschoben,
                # dass sie JETZT genau den angezeigten Wert hat und nach eta_left_s dort steht, wo
                # sie bei einer Punktlandung steht (88,9 % bei el == eta, wie nach processing()).
                # Die neue Schaetzung aendert also nur das Tempo ab jetzt. Bis dahin wurde linear
                # umgerechnet, die Kurve ist aber exponentiell: bei 95 % sprang der Ring auf
                # 87,6 % zurueck, bei 42 % auf 61 % vor.
                jetzt = self._elapsed_pct()
                anteil = -math.log(1 - jetzt / 100) / 2.2    # el/eta, bei dem die Kurve jetzt steht
                if anteil < 1:
                    self._eta = max(0.3, eta_left_s) / (1 - anteil)
                    self._t0 = time.time() - anteil * self._eta
                # Sonst steht der Ring schon ueber 88,9 % (die Schaetzung ist ueberzogen) und
                # kriecht wie bisher auf 95 % zu. Die Untergrenze faengt Rundungsreste ab.
                self._pct_floor = jetzt

    def done(self, text: str = "", seconds: float = 1.3) -> None:
        text = text or i18n.t("badge_ready")
        self._note("done", text)
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
        self._note("error", text)
        with self._lock:
            self._state, self._text, self._until = "error", text, time.time() + seconds

    def hide(self) -> None:
        self._note("hidden")
        with self._lock:
            self._state = "hidden"

    # ---- intern ----
    def _elapsed_pct(self) -> float:
        el = time.time() - self._t0
        # weiche Kurve: schnell am Anfang, kriecht auf 95 zu
        return max(self._pct_floor, min(95.0, 100.0 * (1 - math.exp(-2.2 * el / self._eta))))

    def _note(self, neu_state: str, text: str = "") -> None:
        """Jeden Zustandswechsel mit Zeitstempel protokollieren (landet in data/app.log).
        Ohne das war nicht belegbar, WANN das Aufnahme-Symbol verschwindet — genau die Frage
        vom 13.09.2026 („dass wenigstens die Aufnahmesymbolik weg ist")."""
        print("[badge] %-10s %s" % (neu_state, text), flush=True)

    def _run(self) -> None:
        try:
            import tkinter as tk
            import tkinter.font as tkfont
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
        cv = tk.Canvas(root, width=_W_MIN, height=_H, bg=key, highlightthickness=0)
        cv.pack()
        root.geometry(f"{_W_MIN}x{_H}+-2000+-2000")
        root.update_idletasks()
        hwnd = int(root.winfo_id())
        hwnd = win32gui.GetParent(hwnd) or hwnd
        ex = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        ex |= win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex)
        root.withdraw()
        self._ready.set()
        visible = False
        # Hintergrund-Pille (zwei Kreise + Rechteck) und Text entstehen einmal. tick() misst den
        # Text und passt Pille, Canvas und Fenster nur an, wenn sich der Text aendert, nicht in
        # jedem 50-ms-Takt (24.09.2026). Punkt, Ring und Haken (Tag "symbol") zeichnet es wie
        # bisher in jedem Takt neu, sie blinken bzw. laufen.
        schrift = tkfont.Font(root=root, family="Segoe UI", size=9)
        cv.create_oval(0, 0, _H, _H, fill="#1e1e1e", outline="")
        pille_rechts = cv.create_oval(_W_MIN - _H, 0, _W_MIN, _H, fill="#1e1e1e", outline="")
        pille_mitte = cv.create_rectangle(_H // 2, 0, _W_MIN - _H // 2, _H, fill="#1e1e1e", outline="")
        text_id = cv.create_text(_TEXT_X, _H // 2, text="", anchor="w", fill="white", font=schrift)
        breite, gemessen = _W_MIN, None     # aktuelle Feldbreite, zuletzt gemessener Text
        zeiger, monitor = None, None        # Monitor nur neu abfragen, wenn der Zeiger sich bewegt

        def tick():
            nonlocal visible, breite, gemessen, zeiger, monitor
            with self._lock:
                state, text, t0, until = self._state, self._text, self._t0, self._until
                stop_until = self._stop_until
                pct = self._elapsed_pct() if state == "processing" else self._pct
            if state in ("done", "error", "notice") and time.time() > until:
                self._state = state = "hidden"
            if state == "hidden":
                if visible:
                    root.withdraw(); visible = False
                zeiger = None               # beim naechsten Erscheinen den Monitor frisch abfragen
                root.after(80, tick)
                return
            cv.delete("symbol")
            cx, cy, r = 15, 15, 9
            if state == "recording":
                blink = int(time.time() * 2) % 2 == 0
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#e03c3c" if blink else "#7a2020", outline="",
                               tags="symbol")
                s = int(time.time() - t0)
                label = f"{i18n.t('badge_recording')} {s // 60}:{s % 60:02d}"
            elif state == "processing" and time.time() < stop_until:
                # Die ersten Zehntel nach dem Loslassen: grosses graues Quadrat = „aus", kein Rot,
                # kein Ring. Das ist die Antwort auf „damit ich weiss, es nimmt nicht mehr auf".
                cv.create_rectangle(cx - 6, cy - 6, cx + 6, cy + 6, fill="#9a9a9a", outline="", tags="symbol")
                label = i18n.t("badge_stopped")
            elif state == "processing":
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline="#555555", width=3, tags="symbol")
                cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=-360 * pct / 100,
                              style="arc", outline="#4da3ff", width=3, tags="symbol")
                label = f"{int(pct)} %  {text}"
            elif state == "done":
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#3cb44b", outline="", tags="symbol")
                cv.create_line(cx - 5, cy, cx - 1, cy + 4, cx + 6, cy - 5, fill="white", width=2, tags="symbol")
                label = text
            elif state == "notice":
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#4da3ff", outline="", tags="symbol")
                cv.create_rectangle(cx - 4, cy - 3, cx + 4, cy + 4, outline="white", width=2, tags="symbol")
                label = text
            else:  # error
                cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#e03c3c", outline="", tags="symbol")
                cv.create_text(cx, cy, text="!", fill="white", font=("Segoe UI", 10, "bold"), tags="symbol")
                label = text
            if label != gemessen:
                gemessen = label
                anzeige, neu = fit_label(label, schrift.measure)
                cv.itemconfigure(text_id, text=anzeige)
                if neu != breite:
                    breite = neu
                    cv.configure(width=breite)
                    cv.coords(pille_rechts, breite - _H, 0, breite, _H)
                    cv.coords(pille_mitte, _H // 2, 0, breite - _H // 2, _H)
            try:
                x, y = win32api.GetCursorPos()
            except Exception:  # noqa: BLE001
                x, y = 0, 0
            if (x, y) != zeiger:
                zeiger, monitor = (x, y), _monitor_under_pointer()
            links, oben = badge_position(x, y, breite, monitor)
            root.geometry(f"{breite}x{_H}+{links}+{oben}")
            if not visible:
                root.deiconify()
                win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                                      win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)
                visible = True
            root.after(50, tick)

        root.after(50, tick)
        root.mainloop()


def estimate_seconds(tail_audio_s: float, pending_stream_s: float = 0.0) -> float:
    """Schaetzung fuer den Ring: Whisper ~0,1x Audio + Cleanup ~0,03 s/Wort (2,5 Woerter/s) + Grundkosten.
    pending_stream_s = Audio des Abschnitts, den der Streamer beim Loslassen gerade rechnet — der
    kostet dasselbe wie der Rest (STT + Cleanup) und gehoert in die Prognose (12.09.2026: vorher
    stand der Ring bei 95 % und wartete auf genau diesen Abschnitt)."""
    # Koeffizienten aus 8 echten Diktaten (13.09.2026, data/app.log): stt+cleanup zusammen
    # ~0,70 s Grundkosten + ~0,10 s je Sekunde Audio. Die alte Formel schaetzte das Doppelte,
    # deshalb stand der Ring gefuehlt still.
    je_sekunde = 0.10
    return 0.70 + tail_audio_s * je_sekunde + pending_stream_s * je_sekunde


# ---- Groesse und Lage des Felds: reine Rechnung ohne Tk (tests/test_overlay.py) ----
def badge_width(text_px: int) -> int:
    """Feldbreite fuer einen Text von text_px Pixeln: waechst mit, von _W_MIN bis _W_MAX."""
    return max(_W_MIN, min(_W_MAX, _TEXT_X + text_px + _TEXT_RAND))


def fit_label(label: str, measure: Callable[[str], int]) -> tuple[str, int]:
    """(angezeigter Text, Feldbreite). measure(text) = Pixelbreite in der Schrift des Felds, im
    Overlay tkinter.font.Font.measure. Passt der Text selbst bei _W_MAX nicht, wird er so weit
    gekuerzt, dass er samt „…" hineinpasst, statt am Feldrand hart abgeschnitten zu werden."""
    platz = _W_MAX - _TEXT_X - _TEXT_RAND
    text_px = measure(label)
    if text_px > platz:
        # Laengster Anfang, der mit „…" noch passt. Binaersuche: wenige Messungen je Kuerzung.
        passt, zu_lang = 0, len(label)
        while zu_lang - passt > 1:
            mitte = (passt + zu_lang) // 2
            if measure(label[:mitte].rstrip() + "…") <= platz:
                passt = mitte
            else:
                zu_lang = mitte
        label = label[:passt].rstrip() + "…"
        text_px = measure(label)
    return label, badge_width(text_px)


def badge_position(x: int, y: int, width: int,
                   monitor: tuple[int, int, int, int] | None) -> tuple[int, int]:
    """Linke obere Ecke des Felds fuer den Mauszeiger bei (x, y). Wie bisher rechts unterhalb
    des Zeigers; ragte das Feld dort ueber den rechten Rand des Monitors unter dem Zeiger
    (links, oben, rechts, unten), steht es links vom Zeiger, auf einem sehr schmalen Monitor
    buendig am linken Rand. monitor None (Abfrage gescheitert): wie bisher rechts."""
    links = x + _OFFSET[0]
    if monitor is not None and links + width > monitor[2]:
        links = max(monitor[0], x - _OFFSET[0] - width)
    return links, y + _OFFSET[1]


def _monitor_under_pointer() -> tuple[int, int, int, int] | None:
    """Grenzen des Monitors unter dem Mauszeiger, dieselbe Abfrage wie beim Vollbild-Ausschnitt
    (wf/snip.py). Jeder Fehler ergibt None, das Feld steht dann wie bisher rechts vom Zeiger."""
    try:
        from wf import snip
        return snip.monitor_rect()
    except Exception:  # noqa: BLE001
        return None
