"""wf/overlay.py ohne echtes Tk: Zeitschaetzung, die Zustandswechsel des Anzeigefelds
(enabled=False), Groesse und Lage des Felds und der Tk-Teil mit Attrappen (unten).

Vorfall 09.09.2026: ein fehlender Import im Overlay liess die App beim Loslassen haengen. Deshalb
laufen hier alle Zustaende einmal durch. Die Uhr ist ersetzt (Fixture uhr), die Sprache gepinnt."""
from __future__ import annotations

import math
import sys
import types

import pytest

from wf import i18n, overlay


@pytest.fixture
def uhr(monkeypatch) -> dict:
    stand = {"jetzt": 1000.0}
    monkeypatch.setattr(overlay, "time", types.SimpleNamespace(time=lambda: stand["jetzt"]))
    return stand


@pytest.fixture(autouse=True)
def englisch(monkeypatch):
    monkeypatch.setattr(i18n, "_current", "en")


@pytest.fixture
def feld(uhr) -> overlay.Overlay:
    o = overlay.Overlay(enabled=False)
    o.start()                                    # ohne Fenster: tut nichts, startet keinen Thread
    return o


# --- estimate_seconds --------------------------------------------------------------------------
def test_schaetzung_formel():
    assert overlay.estimate_seconds(0.0) == pytest.approx(0.70)
    assert overlay.estimate_seconds(10.0) == pytest.approx(1.70)


def test_laufender_abschnitt_zaehlt_wie_der_rest():
    """12.09.2026: der Ring stand bei 95 % und wartete auf genau diesen Abschnitt."""
    assert overlay.estimate_seconds(5.0, 12.0) == pytest.approx(overlay.estimate_seconds(17.0))
    assert overlay.estimate_seconds(5.0, 12.0) > overlay.estimate_seconds(5.0)


@pytest.mark.parametrize("audio_s, gemessen", [(3.2, 1.10), (6.6, 0.88), (12.0, 2.02)])
def test_schaetzung_nah_an_den_messungen(audio_s, gemessen):
    """An echten Diktaten gemessen (data/app.log, 13.09.2026), Fall aus selftest.py."""
    assert abs(overlay.estimate_seconds(audio_s) - gemessen) < 0.8


# --- Zustaende ---------------------------------------------------------------------------------
def test_ohne_fenster_immer_aus():
    assert overlay.Overlay(enabled=False).enabled is False
    o = overlay.Overlay(enabled=False)
    o.start()
    assert o._thread is None and o._state == "hidden"


def test_alle_zustaende_laufen_durch(feld, capsys):
    for schritt in (feld.recording, lambda: feld.processing(2.0), lambda: feld.phase("x"),
                    feld.done, feld.error, lambda: feld.notice("n"), feld.hide):
        schritt()
    protokoll = capsys.readouterr().out
    for zustand in ("recording", "processing", "done", "error", "hidden"):
        assert f"[badge] {zustand}" in protokoll        # Zeitleiste fuer data/app.log


def test_aufnahme(feld, uhr):
    feld.recording()
    assert (feld._state, feld._t0, feld._text) == ("recording", 1000.0, "")


def test_verarbeitung_beginnt_mit_der_stopp_anzeige(feld, uhr):
    """13.09.2026: direkt nach dem Loslassen erst "recording off", dann der Ring."""
    feld.processing(2.0)
    assert (feld._state, feld._eta, feld._pct, feld._text) == ("processing", 2.0, 0.0, i18n.t("badge_listening"))
    assert feld._stop_until == 1000.0 + overlay.Overlay.STOP_HINT_S
    assert 0.2 <= overlay.Overlay.STOP_HINT_S <= 1.0
    feld.recording()                             # neue Aufnahme: keine Stopp-Anzeige
    assert feld._state == "recording"


def test_verarbeitung_eigener_text_und_mindestschaetzung(feld, monkeypatch):
    feld.processing(0.05, text="eigener Text")
    assert feld._eta == 0.3 and feld._text == "eigener Text"
    monkeypatch.setattr(i18n, "_current", "de")
    feld.processing(1.0)
    assert feld._text == "erkenne"               # Text aus der Oberflaechensprache


def test_ring_steigt_und_bleibt_unter_95(feld, uhr):
    feld.processing(2.0)
    werte = []
    for _ in range(10):
        werte.append(feld._elapsed_pct())
        uhr["jetzt"] += 0.5
    assert werte[0] == 0.0 and werte == sorted(werte) and max(werte) == 95.0


def test_phase_nur_waehrend_der_verarbeitung(feld):
    feld.phase("zu frueh")
    assert feld._state == "hidden" and feld._text == ""
    feld.processing(2.0)
    feld.phase("cleaning up")
    assert feld._text == "cleaning up"
    feld.done()
    feld.phase("zu spaet")
    assert feld._state == "done" and feld._text == i18n.t("badge_ready")


def test_phase_zieht_die_restschaetzung_nach(feld, uhr):
    feld.processing(4.0)
    uhr["jetzt"] += 1.0
    feld.phase("cleaning up", eta_left_s=2.5)
    assert feld._eta - (uhr["jetzt"] - feld._t0) == pytest.approx(2.5)
    feld.phase("cleaning up", eta_left_s=0.0)
    assert feld._eta - (uhr["jetzt"] - feld._t0) == pytest.approx(0.3)   # Mindestrest


def test_ring_laeuft_beim_nachziehen_nicht_rueckwaerts(feld, uhr):
    feld.processing(1.0)
    uhr["jetzt"] += 5.0                          # STT dauerte laenger als geschaetzt
    vorher = feld._elapsed_pct()
    feld.phase("cleaning up", eta_left_s=0.5)
    assert feld._elapsed_pct() >= vorher


@pytest.mark.parametrize("eta, verstrichen, rest", [
    (4.0, 1.0, 2.5), (1.0, 0.3, 0.4), (1.2, 0.9, 3.0), (2.0, 1.9, 0.3), (1.0, 5.0, 0.5), (0.3, 0.0, 9.0),
])
def test_nachziehen_springt_nicht_und_der_ring_steigt_weiter(feld, uhr, eta, verstrichen, rest):
    """Bis 24.09.2026 rechnete phase() linear um, die Kurve ist aber exponentiell: bei 42 % sprang
    der Ring auf 61 % vor, bei 95 % auf 87,6 % zurueck. Jetzt: derselbe Wert wie eben, danach
    steigt er weiter (bis hoechstens 95 %)."""
    feld.processing(eta)
    uhr["jetzt"] += verstrichen
    vorher = feld._elapsed_pct()
    feld.phase("cleaning up", eta_left_s=rest)
    werte = [feld._elapsed_pct()]
    assert werte[0] == pytest.approx(vorher, abs=1e-9) and werte[0] >= vorher
    for _ in range(40):
        uhr["jetzt"] += 0.1
        werte.append(feld._elapsed_pct())
    assert werte == sorted(werte) and max(werte) <= 95.0


@pytest.mark.parametrize("verstrichen", [0.0, 0.5, 1.0])
def test_restschaetzung_bestimmt_das_tempo(uhr, verstrichen):
    """Nach eta_left_s steht der Ring dort, wo er bei einer Punktlandung steht (88,9 % bei
    el == eta, wie nach processing()); eine laengere Restschaetzung laeuft langsamer."""
    punktlandung = 100 * (1 - math.exp(-2.2))
    kurz, lang = overlay.Overlay(enabled=False), overlay.Overlay(enabled=False)
    for f in (kurz, lang):
        f.processing(2.0)
    uhr["jetzt"] += verstrichen
    kurz.phase("cleaning up", eta_left_s=0.5)
    lang.phase("cleaning up", eta_left_s=3.0)
    uhr["jetzt"] += 0.5
    assert kurz._elapsed_pct() == pytest.approx(punktlandung)
    assert lang._elapsed_pct() < kurz._elapsed_pct()
    uhr["jetzt"] += 2.5
    assert lang._elapsed_pct() == pytest.approx(punktlandung)


def test_fertig_fehler_hinweis_verstecken(feld, uhr):
    feld.done()
    assert (feld._state, feld._text, feld._pct, feld._until) == ("done", "Ready - press Ctrl+V", 100.0, 1001.3)
    feld.error()
    assert (feld._state, feld._text, feld._until) == ("error", "Error", 1002.0)
    feld.notice("release to snip", 3.0)
    assert (feld._state, feld._text) == ("notice", "release to snip")
    feld.hide()
    assert feld._state == "hidden"


def test_hinweis_verdraengt_keine_verarbeitung(feld):
    feld.processing(2.0)
    feld.notice("release to snip")
    assert feld._state == "processing"


# --- Groesse und Lage des Felds (24.09.2026: das Feld waechst mit dem Text) --------------------
def _sieben_px(text: str) -> int:
    """Messung wie tkinter.font.Font.measure, hier 7 px je Zeichen."""
    return 7 * len(text)


_PLATZ = overlay._W_MAX - overlay._TEXT_X - overlay._TEXT_RAND     # breitester Text im Feld


def test_feldbreite_waechst_mit_dem_text_zwischen_mindest_und_hoechstbreite():
    rand = overlay._TEXT_X + overlay._TEXT_RAND
    assert overlay.badge_width(0) == overlay._W_MIN == 150
    assert overlay.badge_width(overlay._W_MIN - rand) == overlay._W_MIN       # passt gerade noch
    assert overlay.badge_width(overlay._W_MIN - rand + 1) == overlay._W_MIN + 1
    assert overlay.badge_width(144) == 144 + rand     # "Ready - Ctrl+V (appended)", in Paket 2 gemessen
    assert overlay.badge_width(_PLATZ) == overlay.badge_width(10_000) == overlay._W_MAX


@pytest.mark.parametrize("label", ["", "Pasted", "Ready - Ctrl+V (appended)", "x" * (_PLATZ // 7)])
def test_passender_text_bleibt_ganz(label):
    anzeige, breite = overlay.fit_label(label, _sieben_px)
    assert anzeige == label
    assert breite == overlay.badge_width(_sieben_px(label))


@pytest.mark.parametrize("label", ["x" * (_PLATZ // 7 + 1), "Готово — нажмите Ctrl+V " * 4, "ein " * 100])
def test_zu_langer_text_endet_sauber_auf_auslassungspunkte(label):
    """Statt hart am Feldrand abgeschnitten: der laengste Anfang, der samt „…" noch passt."""
    anzeige, breite = overlay.fit_label(label, _sieben_px)
    kandidaten = [label[:k].rstrip() + "…" for k in range(len(label) + 1)]
    assert anzeige == max((t for t in kandidaten if _sieben_px(t) <= _PLATZ), key=len)
    assert anzeige[-2] != " " and label.startswith(anzeige[:-1])
    assert breite == overlay.badge_width(_sieben_px(anzeige)) <= overlay._W_MAX


def test_kuerzen_misst_nur_wenige_male():
    """tick() laeuft alle 50 ms: auch ein ueberlanger Text kostet nur eine Handvoll Messungen."""
    gemessen: list[str] = []
    overlay.fit_label("ein sehr langer Text " * 50, lambda t: gemessen.append(t) or _sieben_px(t))
    assert len(gemessen) <= 15


MONITOR = (0, 0, 1920, 1080)


@pytest.mark.parametrize("x, breite, erwartet_links", [
    (100, 150, 122),                  # wie bisher: rechts vom Zeiger (x + 22)
    (1748, 150, 1770),                # endet genau am Monitorrand 1920: bleibt rechts
    (1749, 150, 1577),                # 1 px zu weit: links vom Zeiger (x - 22 - Breite)
    (1900, 300, 1578),                # breites Feld am rechten Rand
])
def test_feld_steht_rechts_und_am_rechten_rand_links_vom_zeiger(x, breite, erwartet_links):
    assert overlay.badge_position(x, 500, breite, MONITOR) == (erwartet_links, 524)


def test_feldposition_zweiter_monitor_links_und_ohne_monitor():
    links_daneben = (-1920, 0, 0, 1080)                   # Monitor links vom Hauptmonitor
    assert overlay.badge_position(-1000, 300, 150, links_daneben) == (-978, 324)
    assert overlay.badge_position(-100, 300, 150, links_daneben) == (-272, 324)
    assert overlay.badge_position(1900, 300, 150, None) == (1922, 324)    # Abfrage gescheitert: rechts
    assert overlay.badge_position(250, 300, 300, (0, 0, 320, 240)) == (0, 324)   # winziger Monitor


def test_monitorabfrage_mit_fehler_gibt_none(monkeypatch):
    from wf import snip

    def kaputt():
        raise OSError("kein Windows")

    monkeypatch.setattr(snip, "monitor_rect", kaputt)
    assert overlay._monitor_under_pointer() is None
    monkeypatch.setattr(snip, "monitor_rect", lambda: MONITOR)
    assert overlay._monitor_under_pointer() == MONITOR


# --- Tk-Teil mit Attrappen: _run() und tick() ----------------------------------------------------
# Keine echte Oberflaeche: tkinter und pywin32 werden nur fuer diese Tests durch ausdrueckliche
# Attrappen ersetzt (auch dort, wo die echten Pakete installiert sind). Geprueft wird das
# Zusammenspiel in tick(): Breite, Pille, Fenstergeometrie, Position und wie oft gemessen wird.
class _Schrift:
    """tkinter.font.Font: 7 px je Zeichen, merkt sich jede Messung."""

    def __init__(self, root=None, family=None, size=None):
        self.family, self.size, self.messungen = family, size, []

    def measure(self, text):
        self.messungen.append(text)
        return _sieben_px(text)


class _Canvas:
    """tkinter.Canvas: haelt die Elemente als {id: {"art", "coords", Optionen ...}}."""

    def __init__(self, master=None, width=0, height=0, **kwargs):
        self.width, self.height, self.elemente, self._zaehler = width, height, {}, 0

    def _neu(self, art, coords, kwargs):
        self._zaehler += 1
        self.elemente[self._zaehler] = {"art": art, "coords": coords, **kwargs}
        return self._zaehler

    def create_oval(self, *coords, **kwargs):
        return self._neu("oval", coords, kwargs)

    def create_rectangle(self, *coords, **kwargs):
        return self._neu("rectangle", coords, kwargs)

    def create_arc(self, *coords, **kwargs):
        return self._neu("arc", coords, kwargs)

    def create_line(self, *coords, **kwargs):
        return self._neu("line", coords, kwargs)

    def create_text(self, *coords, **kwargs):
        return self._neu("text", coords, kwargs)

    def pack(self):
        pass

    def configure(self, width=None):
        self.width = width

    def coords(self, nummer, *coords):
        self.elemente[nummer]["coords"] = coords

    def itemconfigure(self, nummer, **kwargs):
        self.elemente[nummer].update(kwargs)

    def delete(self, tag):
        self.elemente = {n: e for n, e in self.elemente.items() if e.get("tags") != tag}


def _tk_lauf(monkeypatch, feld, schritte, zeiger=None, monitor=None) -> dict:
    """feld._run() mit Attrappen. schritte: je Takt eine Funktion (oder None), die vor dem Takt
    laeuft, z. B. einen Zustand setzt oder zeiger["pos"] verschiebt. Rueckgabe: {"root", "canvas",
    "schrift", "abfragen" (wie oft der Monitor abgefragt wurde)}."""
    zeiger = zeiger if zeiger is not None else {"pos": (100, 200)}
    teile: dict = {"abfragen": 0}

    class _Tk:
        def __init__(self):
            self.geometrien, self.sichtbar, self._naechster = [], False, []
            teile["root"] = self

        def overrideredirect(self, flag):
            pass

        def attributes(self, *args):
            pass

        def configure(self, **kwargs):
            pass

        def geometry(self, text):
            self.geometrien.append(text)

        def update_idletasks(self):
            pass

        def winfo_id(self):
            return 1

        def withdraw(self):
            self.sichtbar = False

        def deiconify(self):
            self.sichtbar = True

        def after(self, ms, rueckruf):
            self._naechster.append(rueckruf)

        def mainloop(self):
            for schritt in schritte:
                if schritt:
                    schritt()
                self._naechster.pop(0)()             # ein Takt

    def canvas(*args, **kwargs):
        teile["canvas"] = _Canvas(*args, **kwargs)
        return teile["canvas"]

    def schrift(**kwargs):
        teile["schrift"] = _Schrift(**kwargs)
        return teile["schrift"]

    def abfrage():
        teile["abfragen"] += 1
        return monitor

    font = types.ModuleType("tkinter.font")
    font.Font = schrift
    tk = types.ModuleType("tkinter")
    tk.Tk, tk.Canvas, tk.font = _Tk, canvas, font
    win32con = types.ModuleType("win32con")
    for name in ("GWL_EXSTYLE", "WS_EX_TOOLWINDOW", "WS_EX_NOACTIVATE", "WS_EX_TRANSPARENT",
                 "WS_EX_LAYERED", "HWND_TOPMOST", "SWP_NOMOVE", "SWP_NOSIZE", "SWP_NOACTIVATE"):
        setattr(win32con, name, 0)
    win32gui = types.ModuleType("win32gui")
    win32gui.GetParent = lambda hwnd: 0
    win32gui.GetWindowLong = lambda hwnd, index: 0
    win32gui.SetWindowLong = lambda hwnd, index, wert: 0
    win32gui.SetWindowPos = lambda *args: None
    win32api = types.ModuleType("win32api")
    win32api.GetCursorPos = lambda: zeiger["pos"]
    for name, modul in (("tkinter", tk), ("tkinter.font", font), ("win32con", win32con),
                        ("win32gui", win32gui), ("win32api", win32api)):
        monkeypatch.setitem(sys.modules, name, modul)
    monkeypatch.setattr(overlay, "_monitor_under_pointer", abfrage)
    feld._run()
    return teile


def test_tk_feld_waechst_und_misst_nur_bei_neuem_text(feld, monkeypatch):
    lang = "x" * 30                                            # 210 px -> Feld 248 px
    zu_lang = "y" * 60                                         # 420 px -> "y" * 36 + "…", Feld 297 px
    teile = _tk_lauf(monkeypatch, feld, [
        lambda: feld.done("Pasted", 60), None, None,
        lambda: feld.done(lang, 60), None, None,
        lambda: feld.done(zu_lang, 60), None,
        feld.hide, None,
    ])
    root, cv = teile["root"], teile["canvas"]
    assert root.geometrien == ["150x30+-2000+-2000"] + ["150x30+122+224"] * 3 \
        + ["248x30+122+224"] * 3 + ["297x30+122+224"] * 2     # versteckt: keine Geometrie mehr
    assert root.sichtbar is False
    schrift = teile["schrift"]
    assert (schrift.family, schrift.size) == ("Segoe UI", 9)
    # Gemessen wird je neuem Text, nicht je Takt; nur das Kuerzen misst ein paar Mal mehr.
    assert schrift.messungen[:2] == ["Pasted", lang] and schrift.messungen.count(zu_lang) == 1
    assert len(schrift.messungen) <= 12
    texte = [e for e in cv.elemente.values() if e["art"] == "text" and e.get("tags") != "symbol"]
    assert len(texte) == 1 and texte[0]["text"] == "y" * 36 + "…" and texte[0]["font"] is schrift
    assert cv.width == 297
    pille = sorted(e["coords"] for e in cv.elemente.values() if e.get("fill") == "#1e1e1e")
    assert pille == [(0, 0, 30, 30), (15, 0, 282, 30), (267, 0, 297, 30)]
    assert len([e for e in cv.elemente.values() if e.get("tags") == "symbol"]) == 2   # Haken: Kreis + Linie


def test_tk_feld_am_rechten_rand_links_vom_zeiger(feld, monkeypatch):
    zeiger = {"pos": (1000, 500)}

    def zeiger_nach(x, y):
        return lambda: zeiger.__setitem__("pos", (x, y))

    teile = _tk_lauf(monkeypatch, feld, [
        lambda: feld.done("Pasted", 60), None,                # Monitormitte: rechts vom Zeiger
        zeiger_nach(1850, 500), None,                          # rechter Rand: links vom Zeiger
        feld.hide, lambda: feld.done("Pasted", 60),          # wieder sichtbar: Monitor frisch
    ], zeiger=zeiger, monitor=MONITOR)
    assert teile["root"].geometrien[1:] == ["150x30+1022+524"] * 2 + ["150x30+1678+524"] * 3
    assert teile["abfragen"] == 3                   # nur nach Zeigerbewegung und beim Erscheinen
