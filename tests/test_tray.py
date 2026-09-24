"""wf/tray.py: der Tooltip-Text (_tooltip_title) - Produktname, Zustand aus i18n, Umschalt-Modus,
Zielsprache, Zusatz. Reine Funktion, extra dafuer aus set_state() herausgezogen (Arbeitspaket 2,
24.09.2026): vorher trug der Tooltip den alten Namen "whisperflow-local" und dahinter das interne
englische Zustandswort, unuebersetzt, auch in der deutschen Oberflaeche.

Der Menue-Aufbau selbst (Beschriftungen, Haken, Klicks) steht schon in tests/test_attrappen.py
(test_tray_menue_laesst_sich_auslesen_und_klicken); hier nur der Tooltip."""
from __future__ import annotations

import pytest

from wf import i18n, lang, tray

_ZUSTAENDE = ("idle", "recording", "processing", "disabled")


@pytest.fixture(autouse=True)
def englisch(monkeypatch):
    monkeypatch.setattr(i18n, "_current", "en")


def test_produktname_ist_my_local_whisper():
    titel = tray._tooltip_title("idle", toggle_mode=False, translate_to="")
    assert titel.startswith("my-local-whisper")
    assert "whisperflow-local" not in titel


@pytest.mark.parametrize("code", [c for c, _ in i18n.LANGUAGES])
@pytest.mark.parametrize("zustand", _ZUSTAENDE)
def test_zustand_kommt_aus_i18n_in_jeder_sprache(code, zustand, monkeypatch):
    """Jede der fuenf Oberflaechensprachen bekommt ihr eigenes Zustandswort, nicht den internen
    englischen Code ("idle"/"recording"/"processing"/"disabled")."""
    monkeypatch.setattr(i18n, "_current", code)
    titel = tray._tooltip_title(zustand, toggle_mode=False, translate_to="")
    erwartet = i18n.TABLE[code][f"tooltip_state_{zustand}"]
    assert titel == f"my-local-whisper - {erwartet}"
    if code != "en":
        assert zustand not in titel                       # kein englischer Zustandscode uebrig


def test_umschalt_modus_haengt_an():
    titel = tray._tooltip_title("recording", toggle_mode=True, translate_to="")
    assert titel == f"my-local-whisper - {i18n.t('tooltip_state_recording')} · {i18n.t('tooltip_toggle_mode')}"


def test_zielsprache_haengt_an():
    titel = tray._tooltip_title("recording", toggle_mode=False, translate_to="it")
    assert titel == f"my-local-whisper - {i18n.t('tooltip_state_recording')} · → {lang.name_native('it')}"


def test_detail_haengt_hinten_an():
    titel = tray._tooltip_title("recording", toggle_mode=False, translate_to="", detail="3 s")
    assert titel == f"my-local-whisper - {i18n.t('tooltip_state_recording')} · 3 s"


def test_set_state_benutzt_dieselbe_funktion(attrappen, monkeypatch):
    """Gegenprobe mit dem echten Tray (pystray-Attrappe): set_state() muss wirklich bei
    icon.title landen, nicht nur die freistehende Funktion."""
    if "pystray" not in attrappen:
        pytest.skip("echtes pystray installiert")
    monkeypatch.setattr(i18n, "_current", "de")
    t = tray.Tray(lambda on: None, lambda: None)
    t.set_state("processing")
    assert t._icon.title == f"my-local-whisper - {i18n.t('tooltip_state_processing')}"
    assert "whisperflow-local" not in t._icon.title


def test_sprachwechsel_aktualisiert_den_tooltip_sofort(attrappen, monkeypatch):
    """Nachbesserung 24.09.2026: _make_ui_lang_click rief nur update_menu() auf, der Tooltip blieb
    bis zum naechsten Zustandswechsel in der alten Sprache stehen. on_set_ui_language hier wie in
    whisperflow.py._set_ui_language: es setzt i18n._current, noch bevor update_menu() laeuft."""
    if "pystray" not in attrappen:
        pytest.skip("echtes pystray installiert")
    monkeypatch.setattr(i18n, "_current", "en")
    t = tray.Tray(lambda on: None, lambda: None,
                  on_set_ui_language=lambda code: monkeypatch.setattr(i18n, "_current", code))
    t.set_state("idle")
    assert t._icon.title == f"my-local-whisper - {i18n.TABLE['en']['tooltip_state_idle']}"

    sprach_menu = t._icon.menu.items[3].submenu.items          # "Language" -> Untermenue
    deutsch = next(m for m in sprach_menu if m.text == "Deutsch")
    deutsch(t._icon)

    assert i18n.current() == "de"
    assert t._icon.title == f"my-local-whisper - {i18n.TABLE['de']['tooltip_state_idle']}"
