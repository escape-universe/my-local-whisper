"""wf/i18n.py: Tabelle vollstaendig, Platzhalter heil, Umschalten, Rueckfall, Systemsprache.

Die Oberflaechensprache ist globaler Zustand. Jeder Test, der sie aendert, pinnt sie vorher mit
monkeypatch (Fixture sprache), damit sie danach wieder stimmt und kein anderer Test davon abhaengt.
Die Systemsprache wird nie echt abgefragt (unter Windows waere das GetUserDefaultUILanguage)."""
from __future__ import annotations

import ctypes
import locale
import string
import types

import pytest

from wf import i18n, lang


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
