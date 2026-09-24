"""wf/i18n.py: Tabelle vollstaendig, Platzhalter heil, Umschalten, Rueckfall, Systemsprache.

Die Oberflaechensprache ist globaler Zustand. Jeder Test, der sie aendert, pinnt sie vorher mit
monkeypatch (Fixture sprache), damit sie danach wieder stimmt und kein anderer Test davon abhaengt.
Die Systemsprache wird nie echt abgefragt (unter Windows waere das GetUserDefaultUILanguage)."""
from __future__ import annotations

import ctypes
import locale
import re
import string
import types

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


# --- Breite im Anzeigefeld (wf/overlay.py: _W breit, Text beginnt bei x = 32) -------------------
#: Von wf.overlay._W abgeleitet statt fest verdrahtet, damit ein spaeteres Paket, das die
#: Feldbreite aendert (z. B. ein mitwachsendes Feld), diesen Test nicht stillschweigend
#: unwirksam macht. Reserve von 6 px zusaetzlich zu "_W minus 32 px Textanfang" (Nachbesserung
#: Runde 2, 24.09.2026): der runde Rand der Pille schneidet auf Buchstabenhoehe schon vor dem
#: rechten Feldrand ein (~117 px bei _W = 150), und Segoe UI ist nicht exakt Liberation Sans -
#: die 6 px fangen beides ab. Ohne Reserve (voll bis _W - 32) bestand "Fehler, siehe Konsole"
#: (Runde-1-Text, 119 px gerastert) den Test noch mit 1 px "Luft" nach oben.
_FELD_RESERVE_PX = 6
_FELD_BREITE_PX = overlay._W - 32 - _FELD_RESERVE_PX

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
#: sondern mindestens das breiteste Zeichen der Schrift ueberhaupt (mit BASIC gemessen: '@'/'…'/
#: '—' bei 12 px) plus etwas Luft, damit ein kuenftig neu eingefuegtes Zeichen nicht zu knapp
#: durchrutscht.
_UNBEKANNTES_ZEICHEN = 13


def _breite(text: str) -> int:
    """Naeherung der Pixelbreite in Segoe UI 9 pt, siehe _ZEICHENBREITE."""
    return sum(_ZEICHENBREITE.get(ch, _UNBEKANNTES_ZEICHEN) for ch in text)


@pytest.mark.parametrize("key", [k for k in i18n.TABLE["de"] if k.startswith("badge_")])
def test_deutsche_badge_texte_passen_ins_anzeigefeld(key):
    """Nachbesserung Arbeitspaket 2, Runde 1 (24.09.2026): mehrere deutsche badge_*-Texte waren
    breiter als das Feld und wurden am rechten Rand abgeschnitten (u. a. "Zwischenablage gesperrt",
    "Bereit - Strg+V (angehaengt)", "loslassen fuer den Ausschnitt"). Nur Deutsch: die englische
    Tabelle laeuft an einigen Stellen ebenfalls ueber - das ist ein eigenes Paket (ein
    mitwachsendes Feld statt einer festen Breite), hier bewusst nicht mitgeprueft."""
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


def _windows_meldet(monkeypatch, lcid):
    kernel32 = types.SimpleNamespace(GetUserDefaultUILanguage=lambda: lcid)
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(kernel32=kernel32), raising=False)


@pytest.mark.parametrize("lcid, erwartet", [(0x0407, "de"), (0x0C07, "de"), (0x0409, "en"),
                                            (0x0419, "ru"), (0x0C0A, "es"), (0x0410, "it")])
def test_systemsprache_aus_windows(monkeypatch, lcid, erwartet):
    _windows_meldet(monkeypatch, lcid)
    monkeypatch.setattr(locale, "getdefaultlocale", lambda: ("ja_JP", "UTF-8"))
    assert i18n.detect_system_language() == erwartet


def test_systemsprache_unbekannt_dann_locale_dann_englisch(monkeypatch):
    _windows_meldet(monkeypatch, 0x0411)                        # Japanisch: nicht unterstuetzt
    monkeypatch.setattr(locale, "getdefaultlocale", lambda: ("it_IT", "UTF-8"))
    assert i18n.detect_system_language() == "it"
    monkeypatch.setattr(locale, "getdefaultlocale", lambda: ("ja_JP", "UTF-8"))
    assert i18n.detect_system_language() == "en"


def test_systemsprache_ohne_windows(monkeypatch):
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(), raising=False)
    monkeypatch.setattr(locale, "getdefaultlocale", lambda: ("ru_RU", "UTF-8"))
    assert i18n.detect_system_language() == "ru"
    monkeypatch.setattr(locale, "getdefaultlocale", lambda: (None, None))
    assert i18n.detect_system_language() == "en"
