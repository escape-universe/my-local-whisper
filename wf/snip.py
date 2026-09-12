"""Bildausschnitt („Snipping") — Taste druecken, Rahmen aufziehen, Bild in der Zwischenablage.

Auftrag Neben dem Diktat (rechte Strg) soll eine zweite Taste einen
Bildschirm-Ausschnitt machen — schnell, ohne ein Programm zu oeffnen, Ergebnis sofort per Strg+V
einfuegbar und zusaetzlich als Datei abgelegt.

Der entscheidende Unterschied zum Windows-Snipping-Tool
------------------------------------------------------
Beim Snipping-Tool verschwindet ein aufgeklapptes Menue, sobald das Werkzeug den Fokus nimmt —
genau die Faelle, die man dokumentieren will (falsch dargestellte Aufklapp-Menues), lassen sich
damit nicht fotografieren. Hier wird der Bildschirm **im Moment des Tastendrucks eingefroren**,
und erst DANACH oeffnet sich die Auswahl — sie zeigt nur noch das eingefrorene Bild. Was beim
Druecken zu sehen war, ist damit drin, auch offene Menues, Tooltips und Vorschau-Fenster.

Aufbau
  grab_screen()      Bildschirm einfrieren (alle Monitore, Ursprung des virtuellen Desktops)
  select_region()    Auswahl-Fenster ueber dem eingefrorenen Bild (Tk, eigener Thread)
  to_clipboard()     Bild in die Zwischenablage (CF_DIB + PNG, damit Chrome/Slack/Word es nehmen)
  save_image()       PNG in den Bilder-Ordner, Dateiname = Datum_Uhrzeit
  cleanup_old()      Bilder aelter als N Tage loeschen (Standard 14)
  KeyWatcher         eigener Tastatur-Hook fuer die Ausloese-Taste (mit Unterdrueckung)

Warum ein eigener Tastatur-Hook und nicht HoldToTalk: Fuer Tasten mit eigener Aufgabe (z.B. die
Kontextmenue-Taste) soll das Ereignis das Betriebssystem NICHT erreichen. Das geht bei pynput nur
ueber `win32_event_filter` + `suppress_event()`, und dabei kommen die normalen
on_press/on_release-Rueckrufe nicht mehr an — der Filter selbst ist die Quelle. Modifikatoren
(Umschalt/Strg/Alt/Windows) werden davon ausgenommen, siehe NEVER_SUPPRESS.
"""
from __future__ import annotations

import io
import queue
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

# --- Tasten, die als Ausloeser in Frage kommen (Name -> Virtual-Key-Code) -------------------
# Standard ist die **rechte Umschalt-Taste**, und zwar SOFORT beim Antippen (der Nutzer 11.09.2026:
# „wie die Strg-Taste beim Diktat"; er schreibt Grossbuchstaben nur mit der linken Umschalt-Taste,
# die rechte ist frei). Verschluckt wird sie trotzdem nie (NEVER_SUPPRESS) — ein Tippen auf
# Umschalt allein schreibt ohnehin nichts, und so bleibt sie im Notfall benutzbar.
# Die Betriebsart "hold" (halten, ausgeloest beim Loslassen) bleibt fuer Tasten, die im Alltag
# gebraucht werden. AltGr scheidet ganz aus: darauf liegen @ € | { }.
KEYS: dict[str, int] = {
    "shift_r": 0xA1,       # rechte Umschalt-Taste (Standard, Betriebsart "tap" = sofort)
    "menu": 0x5D,          # Kontextmenue-Taste (VK_APPS)
    "scroll_lock": 0x91,   # Rollen
    "pause": 0x13,
    "f9": 0x78, "f10": 0x79, "f12": 0x7B,
    "cmd_r": 0x5C,         # rechte Windows-Taste
    "alt_gr": 0xA5,        # nur, wenn jemand es ausdruecklich will (bricht @ € |)
}

# Umschalt/Strg/Alt/Windows werden NIE verschluckt, egal was in der Konfiguration steht: eine
# verschluckte Umschalt-Taste hiesse, dass an ihr keine Grossbuchstaben mehr entstehen. Ein Tippen
# auf diese Tasten allein schreibt ohnehin nichts, das Durchlassen kostet also nichts.
NEVER_SUPPRESS = {0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x10, 0x11, 0x12, 0x5B, 0x5C}

_WM_KEYDOWN, _WM_KEYUP = 0x0100, 0x0101
_WM_SYSKEYDOWN, _WM_SYSKEYUP = 0x0104, 0x0105

_LABELS = {
    "shift_r": "right Shift key",
    "menu": "context-menu key (left of the right Ctrl)",
    "scroll_lock": "Scroll Lock",
    "pause": "Pause",
    "cmd_r": "right Windows key",
    "alt_gr": "AltGr",
}


def key_label(name: str) -> str:
    """Menschlicher Name der Taste fuer Meldungen."""
    return _LABELS.get(name, name)


# --- Bildschirm einfrieren ------------------------------------------------------------------
def virtual_screen() -> tuple[int, int, int, int]:
    """(x, y, breite, hoehe) des gesamten virtuellen Desktops. x/y koennen negativ sein
    (zweiter Monitor oberhalb oder links vom Hauptmonitor)."""
    import ctypes
    u = ctypes.windll.user32
    return (u.GetSystemMetrics(76), u.GetSystemMetrics(77),
            u.GetSystemMetrics(78), u.GetSystemMetrics(79))


def _dpi_aware() -> None:
    """Echte Pixel statt hochskalierter Ersatzbilder. Nur fuer diesen Thread setzen, damit die
    Tk-Anzeige der App (anderer Thread) davon nichts merkt."""
    import ctypes
    try:                                   # Windows 10 1607+: PER_MONITOR_AWARE_V2
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:                      # noqa: BLE001
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:                  # noqa: BLE001
            pass


def monitor_rect() -> tuple[int, int, int, int] | None:
    """(links, oben, rechts, unten) des Monitors, auf dem der Mauszeiger steht — in
    Bildschirmkoordinaten. None, wenn Windows nichts liefert.

    Wozu: Beim „ganzen Bildschirm" ist bei zwei Monitoren fast immer nur der gemeint, auf dem man
    gerade arbeitet. Beide mitzunehmen macht das Bild doppelt so gross und kostet beim Ansehen
    unnoetig Kontext (Entscheidung)."""
    import ctypes
    from ctypes import wintypes

    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
                    ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]

    u = ctypes.windll.user32
    try:
        pt = _POINT()
        if not u.GetCursorPos(ctypes.byref(pt)):
            return None
        mon = u.MonitorFromPoint(pt, 2)          # 2 = MONITOR_DEFAULTTONEAREST
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not u.GetMonitorInfoW(mon, ctypes.byref(info)):
            return None
        r = info.rcMonitor
        return (r.left, r.top, r.right, r.bottom)
    except Exception:  # noqa: BLE001
        return None


def grab_screen():
    """Friert JETZT den gesamten sichtbaren Bildschirm ein. Gibt (Bild, x, y) zurueck; x/y sind
    der Ursprung des virtuellen Desktops (fuer die Umrechnung Bildpunkt -> Bildschirmpunkt)."""
    from PIL import ImageGrab
    _dpi_aware()
    x, y, w, h = virtual_screen()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    return img, x, y


# --- Auswahl-Fenster ------------------------------------------------------------------------
_HINT = "Bereich mit der Maus aufziehen   ·   Esc bricht ab"


def set_hint(text: str) -> None:
    """Hinweiszeile im Auswahl-Fenster (kommt aus der Oberflaechensprache)."""
    global _HINT
    _HINT = text


def _in_den_vordergrund(root) -> bool:
    """Das Auswahl-Fenster wirklich nach vorn holen — sonst kommen Esc und Enter nicht an.

    `focus_force()` allein reicht nicht: Windows laesst ein Fenster nur dann in den Vordergrund,
    wenn der Aufrufer gerade die Eingabe besitzt. Ein Hintergrundprozess (unsere Tray-App) besitzt
    sie nicht — gemessen 11.09.2026: die Auswahl lag sichtbar oben, der Tastendruck ging aber
    weiter an Chrome, Esc und Enter waren wirkungslos. Der uebliche Weg ist, sich kurz an den
    Eingabe-Zustand des Vordergrund-Fensters anzuhaengen (AttachThreadInput) und in dieser Zeit
    den Vordergrund zu setzen. Mausklicks funktionierten uebrigens die ganze Zeit — deshalb faellt
    so ein Fehler beim Ausprobieren leicht durch."""
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = root.winfo_id()
        hwnd = u.GetParent(hwnd) or hwnd
        fg = u.GetForegroundWindow()
        tid_fg = u.GetWindowThreadProcessId(fg, None) if fg else 0
        tid_me = ctypes.windll.kernel32.GetCurrentThreadId()
        angehaengt = bool(tid_fg) and bool(u.AttachThreadInput(tid_fg, tid_me, True))
        try:
            u.SetForegroundWindow(hwnd)
            u.BringWindowToTop(hwnd)
            u.SetActiveWindow(hwnd)
            u.SetFocus(hwnd)
        finally:
            if angehaengt:
                u.AttachThreadInput(tid_fg, tid_me, False)
        return u.GetForegroundWindow() == hwnd
    except Exception as e:  # noqa: BLE001
        print("[snip] foreground: %s" % e)
        return False


class _Selector:
    """Vollbild-Fenster ueber dem eingefrorenen Bild. Links ziehen = Bereich, loslassen = fertig.
    Esc / Rechtsklick = Abbruch. Klick ohne Ziehen (< 8 px) = Abbruch (kein Ein-Pixel-Bild)."""

    MIN_PX = 8

    def __init__(self, image, ox: int, oy: int):
        self.image = image
        self.ox, self.oy = ox, oy
        self.box: tuple[int, int, int, int] | None = None
        self._x0 = self._y0 = 0
        self._rect = None
        self._label = None
        self._shades: list = []

    def run(self) -> tuple[int, int, int, int] | None:
        import tkinter as tk
        from PIL import ImageTk

        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        w, h = self.image.size
        # Negative Koordinaten muessen als "+-1080" geschrieben werden ("-1080" hiesse
        # „von rechts/unten gemessen") — sonst landet das Fenster auf dem falschen Monitor.
        root.geometry("%dx%d+%d+%d" % (w, h, self.ox, self.oy) if self.ox >= 0 and self.oy >= 0
                      else "%dx%d+%s+%s" % (w, h, str(self.ox), str(self.oy)))
        root.config(cursor="crosshair")
        photo = ImageTk.PhotoImage(self.image, master=root)
        cv = tk.Canvas(root, width=w, height=h, highlightthickness=0, bd=0, cursor="crosshair")
        cv.pack()
        cv.create_image(0, 0, image=photo, anchor="nw")
        # Alles ausserhalb der Auswahl wird abgedunkelt (gerasterte Rechtecke — Tk kann auf dem
        # Canvas kein Alpha, das Raster 'gray50' ist der uebliche, schnelle Ersatz).
        self._shades = [cv.create_rectangle(0, 0, w, h, fill="black", stipple="gray50", width=0)]
        mx = w // 2
        # Hinweiszeile mittig oben auf dem HAUPTmonitor (nicht in der Mitte aller Monitore)
        try:
            import ctypes
            mx = min(w - 10, max(10, -self.ox + ctypes.windll.user32.GetSystemMetrics(0) // 2))
        except Exception:  # noqa: BLE001
            pass
        my = max(28, -self.oy + 28)
        hint_bg = cv.create_rectangle(mx - 230, my - 18, mx + 230, my + 18,
                                      fill="#181818", outline="#3c3c3c")
        hint = cv.create_text(mx, my, text=_HINT, fill="white", font=("Segoe UI", 12))

        def start(e):
            self._x0, self._y0 = e.x, e.y
            cv.delete(hint)
            cv.delete(hint_bg)
            if self._rect:
                cv.delete(self._rect)
            self._rect = cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#e03c3c", width=2)
            self._label = cv.create_text(e.x, e.y - 12, text="", fill="white", anchor="w",
                                         font=("Segoe UI", 10, "bold"))

        def drag(e):
            if not self._rect:
                return
            x0, y0, x1, y1 = self._x0, self._y0, e.x, e.y
            cv.coords(self._rect, x0, y0, x1, y1)
            a, b = min(x0, x1), min(y0, y1)
            c, d = max(x0, x1), max(y0, y1)
            for s in self._shades:                     # Abdunkeln: vier Balken um die Auswahl
                cv.delete(s)
            self._shades = [cv.create_rectangle(*box, fill="black", stipple="gray50", width=0)
                            for box in ((0, 0, w, b), (0, d, w, h), (0, b, a, d), (c, b, w, d))]
            cv.coords(self._label, a, max(12, b - 12))
            cv.itemconfig(self._label, text="%d x %d" % (c - a, d - b))
            cv.tag_raise(self._rect)
            cv.tag_raise(self._label)

        def finish(e):
            x0, y0, x1, y1 = self._x0, self._y0, e.x, e.y
            a, b = min(x0, x1), min(y0, y1)
            c, d = max(x0, x1), max(y0, y1)
            if (c - a) >= self.MIN_PX and (d - b) >= self.MIN_PX:
                self.box = (a, b, c, d)
            root.destroy()

        def cancel(_e=None):
            self.box = None
            root.destroy()

        def ganzer_monitor(_e=None):
            """Enter/Leertaste = der ganze Monitor, auf dem die Maus steht — ohne Rahmen ziehen.
            Seit 11.09.2026 der Weg zum Vollbild: die Ausloese-Taste oeffnet ja sofort die Auswahl,
            ein Doppeltippen ist damit nicht mehr moeglich."""
            r = monitor_rect()
            if r:
                self.box = (r[0] - self.ox, r[1] - self.oy, r[2] - self.ox, r[3] - self.oy)
            else:                                   # kein Monitor ermittelbar: alles nehmen
                self.box = (0, 0, w, h)
            root.destroy()

        cv.bind("<Button-1>", start)
        cv.bind("<B1-Motion>", drag)
        cv.bind("<ButtonRelease-1>", finish)
        cv.bind("<Button-3>", cancel)
        root.bind("<Escape>", cancel)
        root.bind("<Return>", ganzer_monitor)
        root.bind("<KP_Enter>", ganzer_monitor)
        root.bind("<space>", ganzer_monitor)
        cv.focus_set()
        root.focus_force()
        _in_den_vordergrund(root)
        root.mainloop()
        return self.box


def select_region(image, ox: int, oy: int) -> tuple[int, int, int, int] | None:
    """Auswahl-Fenster in einem EIGENEN Thread (die App hat schon ein Tk-Fenster am Mauszeiger;
    zwei Tk-Schleifen im selben Thread gehen nicht). Gibt die Bildkoordinaten zurueck."""
    ergebnis: dict = {}

    def lauf():
        try:
            ergebnis["box"] = _Selector(image, ox, oy).run()
        except Exception as e:  # noqa: BLE001
            ergebnis["fehler"] = e

    t = threading.Thread(target=lauf, name="snip-select", daemon=True)
    t.start()
    t.join()
    if "fehler" in ergebnis:
        raise ergebnis["fehler"]
    return ergebnis.get("box")


# --- Zwischenablage + Datei -----------------------------------------------------------------
def _dib_bytes(image) -> bytes:
    """BMP ohne die 14-Byte-Datei-Kopfzeile = CF_DIB."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, "BMP")
    return buf.getvalue()[14:]


def to_clipboard(image) -> bool:
    """Bild in die Zwischenablage. Zwei Formate, weil Programme unterschiedlich zugreifen:
    CF_DIB nimmt praktisch jedes Windows-Programm, „PNG" bevorzugen Chrome/Slack/Teams."""
    import win32clipboard
    png = io.BytesIO()
    image.save(png, "PNG")
    dib = _dib_bytes(image)
    for versuch in range(5):        # die Zwischenablage kann kurz von einem anderen Programm belegt sein
        try:
            win32clipboard.OpenClipboard()
        except Exception:  # noqa: BLE001
            time.sleep(0.08 * (versuch + 1))
            continue
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(8, dib)       # 8 = CF_DIB
            try:
                fmt = win32clipboard.RegisterClipboardFormat("PNG")
                win32clipboard.SetClipboardData(fmt, png.getvalue())
            except Exception:  # noqa: BLE001
                pass            # DIB allein reicht zum Einfuegen
            return True
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:  # noqa: BLE001
                pass
    return False


def save_image(image, folder: Path) -> Path:
    """PNG mit Datum_Uhrzeit im Namen ablegen; gibt den Pfad zurueck."""
    folder.mkdir(parents=True, exist_ok=True)
    name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    ziel = folder / ("%s.png" % name)
    n = 2
    while ziel.exists():           # zwei Ausschnitte in derselben Sekunde
        ziel = folder / ("%s_%d.png" % (name, n))
        n += 1
    image.save(ziel, "PNG")
    return ziel


def cleanup_old(folder: Path, keep_days: int) -> int:
    """Bilder aelter als keep_days loeschen; gibt die Zahl der geloeschten Dateien zurueck.
    keep_days <= 0 = nie loeschen."""
    if keep_days <= 0 or not folder.exists():
        return 0
    grenze = (datetime.now() - timedelta(days=keep_days)).timestamp()
    weg = 0
    for f in folder.glob("*.png"):
        try:
            if f.stat().st_mtime < grenze:
                f.unlink()
                weg += 1
        except OSError:
            pass
    return weg


# --- Tastatur-Hook --------------------------------------------------------------------------
class KeyWatcher:
    """Lauscht auf EINE Taste und ruft `on_trigger`. Zwei Betriebsarten:

    * **tap** — sofort beim Druecken. Passt fuer Tasten ohne eigene Aufgabe (Kontextmenue-Taste,
      Rollen). Dort wird die Taste zusaetzlich systemweit unterdrueckt, damit sie ihre normale
      Wirkung verliert (sonst klappt bei jedem Ausschnitt auch das Kontextmenue auf).
    * **hold** — die Taste muss `hold_ms` gehalten werden, ausgeloest wird beim LOSLASSEN.
      Das ist die Betriebsart fuer Tasten, die im Alltag gebraucht werden — Standard seit
      10.09.2026 ist die **rechte Umschalt-Taste**. Kurzes Tippen bleibt ein normales Umschalten
      (Grossbuchstaben!), erst das Festhalten meint den Ausschnitt. Unterdrueckt wird dabei NIE.

    Drei Dinge brechen ein Halten ab, damit kein Ausschnitt aufgeht, wenn die Taste normal
    benutzt wird:
      1. eine andere Taste dazwischen (Umschalt+Buchstabe, Umschalt+Entf ...),
      2. ein Mausklick waehrend des Haltens (Umschalt+Klick markiert Text),
      3. Loslassen vor Ablauf der Zeit.

    Der Rueckruf laeuft in einem eigenen Worker — ein blockierender Tastatur-Hook wird von
    Windows entfernt."""

    def __init__(self, key_name: str, on_trigger: Callable[[], None], suppress: bool = True,
                 mode: str = "tap", hold_ms: int = 450,
                 on_arm: Callable[[], None] | None = None,
                 on_double: Callable[[], None] | None = None, double_tap_ms: int = 400):
        self.key_name = (key_name or "shift_r").strip().lower()
        self.vk = KEYS.get(self.key_name, KEYS["shift_r"])
        self.mode = "hold" if str(mode).lower() == "hold" else "tap"
        self.hold_s = max(0.15, hold_ms / 1000.0)
        # Doppeltippen = ganzer Bildschirm (10.09.2026). Zaehlt nur SAUBERES Tippen: kein anderer
        # Tastendruck, kein Mausklick dazwischen. Zwei Grossbuchstaben hintereinander (Umschalt+A,
        # Umschalt+B) haben je einen Buchstaben dazwischen und zaehlen deshalb nicht.
        self._on_double = on_double
        self.double_tap_s = max(0.15, double_tap_ms / 1000.0)
        self._last_tap = 0.0
        self._on_trigger = on_trigger
        self._on_arm = on_arm
        # Eine Taste, die im Alltag gebraucht wird, darf nie verschluckt werden.
        self._suppress = bool(suppress) and self.mode == "tap" and self.vk not in NEVER_SUPPRESS
        self._down = False
        self._down_at = 0.0
        self._blocked = False        # andere Taste waehrend des Haltens
        self._armed = False          # Haltezeit erreicht, Loslassen loest aus
        self._timer: threading.Timer | None = None
        self._listener = None
        self._jobs: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stopping = threading.Event()

    # --- Mausklick waehrend des Haltens erkennen (ohne zweiten Hook) ---
    @staticmethod
    def _mouse_clicked_since(reset: bool = False) -> bool:
        """GetAsyncKeyState liefert im untersten Bit „seit der letzten Abfrage gedrueckt".
        Beim Tastendruck einmal abfragen (= zuruecksetzen), beim Loslassen erneut: ist das Bit
        gesetzt, wurde zwischendurch geklickt."""
        import ctypes
        u = ctypes.windll.user32
        trefferzahl = 0
        for vk in (0x01, 0x02, 0x04):        # links, rechts, Mitte
            zustand = u.GetAsyncKeyState(vk)
            if not reset and (zustand & 0x0001 or zustand & 0x8000):
                trefferzahl += 1
        return trefferzahl > 0

    def _arm(self) -> None:
        """Haltezeit erreicht: ab jetzt loest das Loslassen aus."""
        if self._down and not self._blocked:
            self._armed = True
            if self._on_arm:
                try:
                    self._on_arm()
                except Exception as e:  # noqa: BLE001
                    print("[snip] arm error: %s" % e)

    def _cancel_timer(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def _filter(self, msg, data):
        vk = getattr(data, "vkCode", None)
        runter = msg in (_WM_KEYDOWN, _WM_SYSKEYDOWN)
        if vk != self.vk:
            # fremde Taste waehrend des Haltens -> das war eine normale Tastenkombination
            if runter and self._down:
                self._blocked = True
                self._armed = False
                self._cancel_timer()
            return True
        if runter:
            if not self._down:                 # Tastenwiederholung ignorieren
                self._down = True
                self._down_at = time.time()
                self._blocked = False
                self._armed = False
                if self.mode == "tap":
                    self._jobs.put("go")
                else:
                    self._mouse_clicked_since(reset=True)
                    self._cancel_timer()
                    self._timer = threading.Timer(self.hold_s, self._arm)
                    self._timer.daemon = True
                    self._timer.start()
        elif msg in (_WM_KEYUP, _WM_SYSKEYUP):
            self._cancel_timer()
            if self.mode == "hold" and self._down:
                sauber = not self._blocked and not self._mouse_clicked_since()
                if self._armed and sauber:
                    self._jobs.put("go")                       # gehalten -> Ausschnitt
                elif sauber and not self._armed:
                    jetzt = time.time()
                    if self._on_double and (jetzt - self._last_tap) <= self.double_tap_s:
                        self._last_tap = 0.0
                        self._jobs.put("doppelt")              # zweimal getippt -> ganzer Bildschirm
                    else:
                        self._last_tap = jetzt
            self._down = False
            self._armed = False
        if self._suppress and self._listener is not None:
            self._listener.suppress_event()    # loest eine Ausnahme aus -> Ereignis geht nicht weiter
        return True

    def _run_worker(self) -> None:
        while not self._stopping.is_set():
            try:
                job = self._jobs.get(timeout=0.25)
            except queue.Empty:
                continue
            if job is None:
                break
            try:
                if job == "doppelt" and self._on_double:
                    self._on_double()
                else:
                    self._on_trigger()
            except Exception as e:  # noqa: BLE001
                print("[snip] trigger error: %s" % e)

    def start(self) -> None:
        from pynput import keyboard
        self._stopping.clear()
        self._worker = threading.Thread(target=self._run_worker, name="snip-worker", daemon=True)
        self._worker.start()
        self._listener = keyboard.Listener(on_press=lambda k: None, on_release=lambda k: None,
                                           win32_event_filter=self._filter, suppress=False)
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
        self._stopping.set()
        self._jobs.put(None)
        self._worker = None
