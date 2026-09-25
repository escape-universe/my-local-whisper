"""wf/tray.py: der Tooltip-Text (_tooltip_title) - Produktname, Zustand aus i18n, Umschalt-Modus,
Zielsprache, Zusatz. Reine Funktion, extra dafuer aus set_state() herausgezogen (Arbeitspaket 2,
24.09.2026): vorher trug der Tooltip den alten Namen "whisperflow-local" und dahinter das interne
englische Zustandswort, unuebersetzt, auch in der deutschen Oberflaeche.

Der Menue-Aufbau selbst (Beschriftungen, Haken, Klicks) steht schon in tests/test_attrappen.py
(test_tray_menue_laesst_sich_auslesen_und_klicken); hier der Tooltip und die Eintraege aus
Arbeitspaket 7 ("Einstellungen", "Mit Windows starten")."""
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


def test_run_gibt_setup_an_pystray_weiter(attrappen, monkeypatch):
    """Arbeitspaket 4: die Start-Meldung ("Aufraeum-Modell nicht erreichbar") darf erst kommen,
    wenn das Icon wirklich im Tray sichtbar ist - das ist pystrays setup-Callback (in echtem
    pystray in einem eigenen Thread aufgerufen), nicht ein fest verdrahtetes sleep()."""
    if "pystray" not in attrappen:
        pytest.skip("echtes pystray installiert")
    monkeypatch.setattr(i18n, "_current", "en")
    t = tray.Tray(lambda on: None, lambda: None)
    aufgerufen = []
    t.run(setup=lambda icon: aufgerufen.append(icon))
    assert aufgerufen == [t._icon]
    assert t._icon.running                          # run() selbst lief trotzdem normal durch


def test_eigener_setup_laesst_das_icon_trotzdem_sichtbar_werden(attrappen):
    """Nachbesserung Arbeitspaket 4, Runde 1 (B3): ein EIGENER setup-Callback ersetzt pystrays
    Standardweg komplett - der setzt sonst icon.visible = True. Ohne das Nachholen in Tray.run()
    waere das Tray-Symbol nie erschienen, sobald es beim Start etwas zu melden gibt (genau der
    Neu-Nutzer-Fall: Ollama laeuft nicht). Belegt durch die pystray-Attrappe, die visible wie das
    echte pystray nur im Standardweg (kein eigener setup) automatisch setzt."""
    if "pystray" not in attrappen:
        pytest.skip("echtes pystray installiert")
    t = tray.Tray(lambda on: None, lambda: None)
    assert t._icon.visible is False                 # vor run(): wie im echten pystray
    aufgerufen = []
    t.run(setup=lambda icon: aufgerufen.append(icon.visible))   # visible schon True, WENN setup laeuft
    assert t._icon.visible is True
    assert aufgerufen == [True]


def test_run_ohne_setup_bleibt_wie_bisher(attrappen):
    if "pystray" not in attrappen:
        pytest.skip("echtes pystray installiert")
    t = tray.Tray(lambda on: None, lambda: None)
    t.run()
    assert t._icon.running
    assert t._icon.visible is True


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


# --- Einstellungen und Autostart im Menue (Arbeitspaket 7, 25.09.2026) ---------------------------
def _eintrag(t, text):
    return next(m for m in t._icon.menu.items if m.text == text)


def test_menue_hat_einstellungen_und_autostart_vor_beenden(attrappen):
    if "pystray" not in attrappen:
        pytest.skip("echtes pystray installiert")
    t = tray.Tray(lambda on: None, lambda: None)
    texte = [m.text for m in t._icon.menu.items]
    assert texte[-5:] == ["- - - -", "Settings", "Start with Windows", "- - - -", "Quit"]
    assert _eintrag(t, "Start with Windows").checked is False     # ohne Rueckfrage: kein Haken
    _eintrag(t, "Settings")(t._icon)                                # ohne Rueckruf: kein Absturz
    _eintrag(t, "Start with Windows")(t._icon)


@pytest.mark.parametrize("code", [c for c, _ in i18n.LANGUAGES])
def test_neue_eintraege_in_jeder_sprache(code, attrappen, monkeypatch):
    if "pystray" not in attrappen:
        pytest.skip("echtes pystray installiert")
    monkeypatch.setattr(i18n, "_current", code)
    t = tray.Tray(lambda on: None, lambda: None)
    texte = [m.text for m in t._icon.menu.items]
    assert i18n.TABLE[code]["menu_settings"] in texte and i18n.TABLE[code]["menu_autostart"] in texte


def test_einstellungen_klick_ruft_die_app(attrappen):
    if "pystray" not in attrappen:
        pytest.skip("echtes pystray installiert")
    aufrufe = []
    t = tray.Tray(lambda on: None, lambda: None, on_open_settings=lambda: aufrufe.append("einstellungen"))
    _eintrag(t, "Settings")(t._icon)
    assert aufrufe == ["einstellungen"]


def test_autostart_haken_zeigt_den_echten_stand_und_schaltet_um(attrappen):
    """Der Haken fragt autostart_enabled (gibt es die Verknuepfung?), ein Klick schaltet auf das
    Gegenteil und zeichnet das Menue neu."""
    if "pystray" not in attrappen:
        pytest.skip("echtes pystray installiert")
    stand = {"an": False}
    geschaltet = []

    def schalten(an):
        geschaltet.append(an)
        stand["an"] = an

    t = tray.Tray(lambda on: None, lambda: None, on_set_autostart=schalten,
                  autostart_enabled=lambda: stand["an"])
    eintrag = _eintrag(t, "Start with Windows")
    assert eintrag.checked is False
    eintrag(t._icon)
    assert geschaltet == [True] and eintrag.checked is True
    vorher = t._icon.menu_updates
    stand["an"] = False                              # Verknuepfung von aussen geloescht
    assert eintrag.checked is False                  # kein gemerkter Zustand
    eintrag(t._icon)
    assert geschaltet == [True, True] and t._icon.menu_updates == vorher + 1


def test_autostart_haken_bei_fehler_in_der_abfrage_aus(attrappen):
    if "pystray" not in attrappen:
        pytest.skip("echtes pystray installiert")

    def kaputt():
        raise OSError("kein Zugriff")

    t = tray.Tray(lambda on: None, lambda: None, autostart_enabled=kaputt)
    assert _eintrag(t, "Start with Windows").checked is False
