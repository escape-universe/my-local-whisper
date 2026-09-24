"""wf/i18n.py: Tabelle vollstaendig, Platzhalter heil, Umschalten, Rueckfall, Systemsprache.

Die Oberflaechensprache ist globaler Zustand. Jeder Test, der sie aendert, pinnt sie vorher mit
monkeypatch (Fixture sprache), damit sie danach wieder stimmt und kein anderer Test davon abhaengt.
Windows wird nie echt gefragt (GetUserDefaultUILanguage/GetUserDefaultLocaleName sind Attrappen);
nur test_systemsprache_ohne_deprecation_warnung liest das echte locale-Modul."""
from __future__ import annotations

import ctypes
import locale
import re
import string
import types
import warnings

import pytest

from wf import i18n, lang, overlay


@pytest.fixture
def sprache(monkeypatch):
    monkeypatch.setattr(i18n, "_current", "en")


def _platzhalter(text: str) -> set[str]:
    return {feld for _, feld, _, _ in string.Formatter().parse(text) if feld is not None}


# --- Tabelle -----------------------------------------------------------------------------------
def test_jede_sprache_im_menue_hat_eine_tabelle():
    assert [code for code, _ in i18n.LANGUAGES] == ["de", "en", "ru", "es", "it"]
    assert set(i18n.TABLE) == {code for code, _ in i18n.LANGUAGES}
    assert i18n.DEFAULT in i18n.TABLE


@pytest.mark.parametrize("code", [c for c, _ in i18n.LANGUAGES])
def test_alle_sprachen_haben_dieselben_schluessel(code):
    referenz = set(i18n.TABLE["en"])
    assert set(i18n.TABLE[code]) == referenz, sorted(referenz ^ set(i18n.TABLE[code]))
    assert not [k for k, v in i18n.TABLE[code].items() if not v.strip()]


@pytest.mark.parametrize("code", [c for c, _ in i18n.LANGUAGES])
def test_platzhalter_stimmen_zwischen_den_sprachen(code):
    """Sonst bricht format() erst im Betrieb, in genau dieser Sprache."""
    schief = [k for k, text in i18n.TABLE[code].items()
              if _platzhalter(text) != _platzhalter(i18n.TABLE["en"][k])]
    assert not schief
    for k, text in i18n.TABLE[code].items():
        text.format(**{feld: "x" for feld in _platzhalter(text)})   # darf nicht werfen


def test_zielsprachen_tragen_denselben_eigennamen():
    for code, name in lang.TARGETS:
        assert i18n.label(code) == name


#: Woerter, die in dieser Sprache zufaellig genauso geschrieben werden wie im Englischen, echte
#: Kognaten, keine vergessene Uebersetzung. {Sprache: {Schluessel: Begruendung}}.
_ECHTE_GLEICHHEIT: dict[str, dict[str, str]] = {
    "es": {
        "badge_error": "Spanisch 'error' schreibt sich genauso wie Englisch (gemeinsame lateinische Wurzel).",
        "note_error": "Gleicher Wortstamm 'Error' wie badge_error.",
    },
}


@pytest.mark.parametrize("code", [c for c, _ in i18n.LANGUAGES if c != "en"])
def test_keine_sprache_kopiert_unuebersetzt_das_englische(code):
    """Arbeitspaket 2 (24.09.2026): die deutsche Tabelle hatte elf Werte unveraendert englisch
    stehen (u. a. "menu_quit": "Quit", "badge_pasted": "Pasted"). Ausnahmen nur fuer echte
    Gleichheit, siehe _ECHTE_GLEICHHEIT. Erkennt nur komplett unveraenderte Werte, keine
    gemischten Reste wie "No history yet vorhanden" - dafuer test_keine_englischen_signalwoerter_in_de."""
    englisch = i18n.TABLE["en"]
    ausnahmen = _ECHTE_GLEICHHEIT.get(code, {})
    unuebersetzt = [k for k, v in i18n.TABLE[code].items() if v == englisch.get(k) and k not in ausnahmen]
    assert not unuebersetzt


@pytest.mark.parametrize("code", ["de", "en"])
def test_kein_langer_gedankenstrich_in_de_und_en(code):
    """Stilregel des Nutzers fuer seine eigenen Sprachen: nie "—"/"–", sondern Bindestrich mit
    Leerzeichen, Komma oder Punkt. Russisch, Spanisch und Italienisch folgen ihrer eigenen
    Typografie (im Russischen ist "—" normale Zeichensetzung) und bleiben deshalb aussen vor."""
    schuldig = [k for k, v in i18n.TABLE[code].items() if "—" in v or "–" in v]
    assert not schuldig


def _ohne_platzhalter(text: str) -> str:
    """Der reine Text ohne die {platzhalter}-Stellen selbst (Feldnamen wie {error} sollen die
    Signalwort-Suche unten nicht faelschlich treffen)."""
    return "".join(literal for literal, _, _, _ in string.Formatter().parse(text))


#: Eindeutig englische Woerter, die in einem deutschen Wert nichts zu suchen haben. Bewusst kurz
#: und pro Wort belegt (Nachbesserung Arbeitspaket 2 Runde 1, 24.09.2026): "the"/"yet" gibt es im
#: Deutschen nicht, "press"/"Ctrl" heissen hier "druecken"/"Strg", "error" ist ausschliesslich ein
#: Platzhalter-Feldname wie {error} (den _ohne_platzhalter schon entfernt hat) oder das englische
#: Wort - Gross-/Kleinschreibung spielt bei diesen fuenf also keine Rolle (Nachbesserung Runde 2:
#: erkennt jetzt auch "The"/"Press"/"Yet" am Satzanfang und ein kleines "ctrl"). Nur "see" bleibt
#: klein-sensitiv: das grossgeschriebene deutsche "See" (Gewaesser) soll nicht anschlagen, kommt
#: in dieser Tabelle aber ohnehin nicht vor.
_SIGNALWOERTER_OHNE_GROSS_KLEIN = ("the", "yet", "press", "Ctrl", "Error")
_SIGNALWORT_RX = re.compile(r"\b(?:" + "|".join(_SIGNALWOERTER_OHNE_GROSS_KLEIN) + r")\b", re.IGNORECASE)
_SEE_RX = re.compile(r"\bsee\b")


def _hat_englisches_signalwort(text: str) -> bool:
    frei = _ohne_platzhalter(text)
    return bool(_SIGNALWORT_RX.search(frei) or _SEE_RX.search(frei))


def test_keine_englischen_signalwoerter_in_de():
    """Ergaenzt test_keine_sprache_kopiert_unuebersetzt_das_englische: der Gleichheitstest dort
    erkennt nur komplett unveraenderte Werte, keine gemischten Reste wie sie vor der Reparatur
    in der deutschen Tabelle standen ("No history yet vorhanden, ...", "Error, see console")."""
    schuldig = {k: v for k, v in i18n.TABLE["de"].items() if _hat_englisches_signalwort(v)}
    assert not schuldig


@pytest.mark.parametrize("code", [c for c, _ in i18n.LANGUAGES if c != "en"])
def test_kein_englisches_off_in_anderen_sprachen(code):
    """Pruefung Arbeitspaket 2: italienisch badge_stopped hiess "registrazione off", halb Englisch
    (en: "recording off", "Off (keep my language)"). Seit 24.09.2026 "registrazione ferma"."""
    schuldig = {k: v for k, v in i18n.TABLE[code].items() if re.search(r"\boff\b", v, re.IGNORECASE)}
    assert not schuldig


# --- Breite im Anzeigefeld (wf/overlay.py: mindestens _W_MIN breit, Text ab x = _TEXT_X) -------
#: Seit Arbeitspaket 3 (24.09.2026) waechst das Feld mit dem Text; die fruehere feste Breite
#: (150 px) ist jetzt seine Mindestbreite. Deutsche Texte sollen ohne Wachsen hineinpassen, das
#: Budget ist deshalb genau die Textbreite, bis zu der wf.overlay.badge_width() noch _W_MIN liefert:
#: _W_MIN minus Textanfang (_TEXT_X = 32) minus Luft rechts (_TEXT_RAND = 6), aus wf/overlay.py
#: abgeleitet statt fest verdrahtet (test_budget_ist_genau_die_grenze_zum_wachsen). Die 6 px waren
#: zuvor die Reserve dieses Tests (Nachbesserung Runde 2): der runde Rand der Pille schneidet auf
#: Buchstabenhoehe schon vor dem rechten Feldrand ein (~117 px bei 150 px Feldbreite), und Segoe UI
#: ist nicht exakt Liberation Sans. Ohne diese 6 px (Budget 150 - 32 = 118) haette die ungerasterte
#: Naeherung aus Runde 1 (RAQM) "Fehler, siehe Konsole" mit 116,3 px noch durchgelassen; gerastert
#: (BASIC, wie Tk/GDI, so wie die Tabelle unten) sind es 119 px, das scheitert schon an 118.
_FELD_BREITE_PX = overlay._W_MIN - overlay._TEXT_X - overlay._TEXT_RAND

#: Zusatz, den wf/overlay.py an manche badge_*-Texte anhaengt (tick(), _elapsed_pct()): ein
#: zweistelliger Prozentsatz vor badge_listening/_cleaning/_translating (Verarbeitung), die
#: verstrichene Zeit hinter badge_recording. "60:00" statt "0:00" (Nachbesserung Runde 2): bei
#: config.yaml audio.max_seconds = 3600 ist das der unguenstigste Fall, nicht "0:00". Alle
#: anderen badge_*-Schluessel erscheinen unveraendert.
_AFFIXE: dict[str, tuple[str, str]] = {
    "badge_listening": ("95 %  ", ""),
    "badge_cleaning": ("95 %  ", ""),
    "badge_translating": ("95 %  ", ""),
    "badge_recording": ("", " 60:00"),
}

#: Pixelbreite in Segoe UI 9 pt, pro Zeichen: eine echte Schriftdatei gibt es auf den CI-Runnern
#: nicht verlaesslich, deshalb hier als Daten mitgeliefert statt eine Schrift zur Testzeit zu
#: laden. Gemessen 24.09.2026 mit PIL, Liberation Sans 12 px (metrisch nah an Segoe UI 9 pt bei
#: 96 dpi), Layout.BASIC statt des Standard-RAQM-Layouts: Windows zeichnet Text unter Tk ueber
#: GDI mit ganzzahligen Zeichenvorschueben (kein Sub-Pixel-Kerning), genau das liefert BASIC -
#: RAQM lag bei denselben Texten bis 3,6 px darunter (Nachbesserung Runde 2, vom Pruefer belegt).
#: Mit BASIC ist das Aufsummieren pro Zeichen exakt gleich der Breite des ganzen Strings (0 px
#: Abweichung, keine Kerning-Anpassungen zwischen Zeichenpaaren in diesem Layout) - nachgemessen
#: an allen Werten unten und in wf/i18n.py TABLE["de"].
_ZEICHENBREITE: dict[str, int] = {
    ' ': 3, '%': 11, '+': 7, ',': 3, '-': 4, '.': 3, '0': 7, '5': 7,
    '6': 7, '9': 7, ':': 3, 'A': 8, 'B': 8, 'E': 8, 'F': 7, 'K': 8,
    'S': 8, 'V': 8, 'a': 7, 'b': 7, 'c': 6, 'd': 7, 'e': 7, 'f': 3,
    'g': 7, 'h': 7, 'i': 3, 'j': 3, 'k': 6, 'l': 3, 'm': 10, 'n': 7,
    'o': 7, 'p': 7, 'r': 4, 's': 6, 't': 3, 'u': 7, 'v': 6, 'z': 6,
    'ä': 7, 'ü': 7,
}
#: Ersatzwert fuer ein Zeichen, das (noch) nicht in _ZEICHENBREITE steht: nicht das breiteste
#: HEUTE benutzte Zeichen (das war in Runde 1 der Fehler - 10,7 lag unter 'W', '@', '…' und '—'),
#: sondern breiter als jedes Zeichen, das in deutschem Text vorkommt (mit BASIC gemessen: '@'/'…'/
#: '—' bei 12 px), damit ein kuenftig neu eingefuegtes Zeichen nicht zu knapp durchrutscht. Die
#: Schrift selbst hat breitere Zeichen (bis 16 px, z. B. 'Ǆ' oder 'Ѿ'), aber keins davon kommt
#: in deutschem Text vor (nachgemessen 24.09.2026, Arbeitspaket 3).
_UNBEKANNTES_ZEICHEN = 13


def _breite(text: str) -> int:
    """Naeherung der Pixelbreite in Segoe UI 9 pt, siehe _ZEICHENBREITE."""
    return sum(_ZEICHENBREITE.get(ch, _UNBEKANNTES_ZEICHEN) for ch in text)


@pytest.mark.parametrize("key", [k for k in i18n.TABLE["de"] if k.startswith("badge_")])
def test_deutsche_badge_texte_passen_ins_anzeigefeld(key):
    """Nachbesserung Arbeitspaket 2, Runde 1 (24.09.2026): mehrere deutsche badge_*-Texte waren
    breiter als das Feld und wurden am rechten Rand abgeschnitten (u. a. "Zwischenablage gesperrt",
    "Bereit - Strg+V (angehaengt)", "loslassen fuer den Ausschnitt"). Nur Deutsch: fuer laengere
    Texte der anderen Sprachen waechst das Feld seit Arbeitspaket 3 mit (wf/overlay.py fit_label),
    deutsche sollen in die Mindestbreite passen."""
    prefix, suffix = _AFFIXE.get(key, ("", ""))
    text = prefix + i18n.TABLE["de"][key] + suffix
    breite = _breite(text)
    assert breite <= _FELD_BREITE_PX, f"{text!r} ~{breite} px, Feld hat {_FELD_BREITE_PX} px"


#: Werte, die tatsaechlich einmal im Code standen und zu breit waren - der Test oben darf sie nie
#: wieder durchlassen. Nachweis fuer den Pruefer (Nachbesserung Runde 2, 24.09.2026): mit der
#: Runde-1-Naeherung (RAQM, Budget 118) bestand "Fehler, siehe Konsole" noch mit 116,3 px, obwohl
#: dieselbe Schriftdatei gerastert (BASIC, wie Tk/GDI) 119 px daraus macht - ueber jedes Feld.
_BEKANNTE_ZU_BREITE_TEXTE = (
    "Fehler, siehe Konsole",          # Runde 1, badge_error_console: 119 px gerastert
    "Bereit - Strg+V (angehängt)",    # Runde 1, badge_ready_appended
    "Zwischenablage gesperrt",        # Runde 1, badge_clipboard_locked
    "loslassen für den Ausschnitt",   # vor Runde 1, badge_snip_arm
)


@pytest.mark.parametrize("text", _BEKANNTE_ZU_BREITE_TEXTE)
def test_breitentest_erkennt_bekannte_zu_breite_texte(text):
    """Belegt, dass _breite()/_FELD_BREITE_PX tatsaechlich etwas ablehnen, nicht nur Kosmetik
    sind: alle vier Beispiele haben frueher wirklich in wf/i18n.py TABLE["de"] gestanden."""
    assert _breite(text) > _FELD_BREITE_PX, f"{text!r} haette abgelehnt werden muessen"


def test_budget_ist_genau_die_grenze_zum_wachsen():
    """Ein deutscher Text, der den Breitentest besteht, laesst das Feld nicht wachsen; ein Pixel
    mehr schon. So prueft der Test gegen die Mindestbreite des mitwachsenden Felds."""
    assert overlay.badge_width(_FELD_BREITE_PX) == overlay._W_MIN == 150
    assert overlay.badge_width(_FELD_BREITE_PX + 1) == overlay._W_MIN + 1


# --- set_language / t --------------------------------------------------------------------------
def test_umschalten_wirkt_sofort(sprache):
    assert i18n.set_language("ru") == "ru" and i18n.current() == "ru"
    assert i18n.t("menu_quit") == i18n.TABLE["ru"]["menu_quit"]


def test_unbekannte_sprache_faellt_auf_englisch(sprache):
    assert i18n.set_language("gibtsnicht") == "en"
    assert i18n.current() == "en" and i18n.t("menu_quit") == "Quit"


def test_platzhalter_werden_gefuellt(sprache):
    i18n.set_language("it")
    assert i18n.t("note_no_history_yet", file="x.log") == "Ancora nessun registro, x.log compare con la prima dettatura."
    assert i18n.t("note_no_history_yet", falsch="x") == i18n.TABLE["it"]["note_no_history_yet"]   # kein Absturz


def test_unbekannter_schluessel_und_fehlende_zeile(sprache, monkeypatch):
    assert i18n.t("gibtsnicht") == "gibtsnicht"
    i18n.set_language("de")
    monkeypatch.delitem(i18n.TABLE["de"], "menu_open_log")
    assert i18n.t("menu_open_log") == "Open the log"            # fehlt eine Zeile: Englisch


def test_label():
    assert i18n.label("ru") == "Русский" and i18n.label("xx") == "xx"


# --- resolve / detect_system_language ----------------------------------------------------------
@pytest.mark.parametrize("einstellung", ["auto", "", None, "system", " AUTO "])
def test_auto_nimmt_die_systemsprache(monkeypatch, einstellung):
    monkeypatch.setattr(i18n, "detect_system_language", lambda: "es")
    assert i18n.resolve(einstellung) == "es"


@pytest.mark.parametrize("einstellung, erwartet", [("it", "it"), ("IT", "it"), (" de ", "de"), ("xx", "en")])
def test_fester_code_sticht_auto(monkeypatch, einstellung, erwartet):
    monkeypatch.setattr(i18n, "detect_system_language", lambda: "es")
    assert i18n.resolve(einstellung) == erwartet


def _windows_meldet(monkeypatch, lcid, gebietsschema="ja-JP"):
    """Windows-Attrappe: lcid = Sprache der Oberflaeche (GetUserDefaultUILanguage), gebietsschema
    = Benutzer-Gebietsschema, also Zahlen-/Datumsformat (GetUserDefaultLocaleName; "" = Fehler)."""
    def gebietsschema_name(puffer, laenge):
        puffer.value = gebietsschema
        return len(gebietsschema) + 1 if gebietsschema else 0

    kernel32 = types.SimpleNamespace(GetUserDefaultUILanguage=lambda: lcid,
                                     GetUserDefaultLocaleName=gebietsschema_name)
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(kernel32=kernel32), raising=False)


@pytest.fixture
def ohne_getdefaultlocale(monkeypatch):
    """locale.getdefaultlocale() ist seit Python 3.11 veraltet, i18n fragt es seit 24.09.2026 nicht
    mehr. pytest.fail wirft keine Exception-Unterklasse: kein `except Exception` verschluckt es."""
    def veraltet(*args, **kwargs):
        pytest.fail("locale.getdefaultlocale() ist veraltet und darf nicht mehr gerufen werden")

    monkeypatch.setattr(locale, "getdefaultlocale", veraltet, raising=False)


@pytest.mark.parametrize("lcid, erwartet", [(0x0407, "de"), (0x0C07, "de"), (0x0409, "en"),
                                            (0x0419, "ru"), (0x0C0A, "es"), (0x0410, "it")])
def test_systemsprache_aus_windows(monkeypatch, ohne_getdefaultlocale, lcid, erwartet):
    """Die Oberflaechensprache gewinnt, auch gegen ein anderes unterstuetztes Gebietsschema."""
    _windows_meldet(monkeypatch, lcid, "de-DE" if erwartet == "it" else "it-IT")
    assert i18n.detect_system_language() == erwartet


@pytest.mark.parametrize("gebietsschema, erwartet", [
    ("it-IT", "it"), ("de-AT", "de"), ("es-MX", "es"), ("ja-JP", "en"), ("et-EE", "en"), ("", "en"),
])
def test_systemsprache_unbekannt_dann_gebietsschema_dann_englisch(monkeypatch, ohne_getdefaultlocale,
                                                                  gebietsschema, erwartet):
    """Oberflaeche in einer nicht unterstuetzten Sprache: unter Windows entscheidet das Benutzer-
    Gebietsschema (dieselbe Quelle wie frueher getdefaultlocale), sonst Englisch. locale.getlocale()
    bleibt unter Windows aussen vor: sein "Estonian_Estonia" ginge sonst als "es" durch."""
    _windows_meldet(monkeypatch, 0x0411, gebietsschema)         # Japanisch: nicht unterstuetzt
    monkeypatch.setattr(locale, "getlocale", lambda *args: ("Estonian_Estonia", "1257"))
    assert i18n.detect_system_language() == erwartet


def test_systemsprache_ohne_windows(monkeypatch, ohne_getdefaultlocale):
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(), raising=False)
    monkeypatch.setattr(locale, "getlocale", lambda *args: ("ru_RU", "UTF-8"))
    assert i18n.detect_system_language() == "ru"
    monkeypatch.setattr(locale, "getlocale", lambda *args: (None, None))
    assert i18n.detect_system_language() == "en"

    def unbekannt(*args):
        raise ValueError("unknown locale: xx")

    monkeypatch.setattr(locale, "getlocale", unbekannt)
    assert i18n.detect_system_language() == "en"


def test_systemsprache_ohne_deprecation_warnung(monkeypatch):
    """Mit dem echten locale-Modul (ohne Windows-Weg) keine DeprecationWarning mehr. Vorher kam
    sie von locale.getdefaultlocale(), dessen Entfernung fuer Python 3.15 angekuendigt ist."""
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(), raising=False)
    with warnings.catch_warnings(record=True) as warnungen:
        warnings.simplefilter("always")
        assert i18n.detect_system_language() in i18n.TABLE
    assert not [w for w in warnungen if issubclass(w.category, DeprecationWarning)]
