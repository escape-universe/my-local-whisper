"""wf/config.py: config.yaml laden, zweistufiges Woerterbuch, Prompt-Seed, optionale Namensliste,
und seit Arbeitspaket 7 die eigene config.local.yaml darueber (Zusammenfuehrung, Fehlermeldungen,
Startzeile, Vorlage config.local.example.yaml, Anlegen fuer Tray -> Einstellungen)."""
from __future__ import annotations

import json
import re

import pytest
import yaml

from wf import config


def _datei(tmp_path, name: str, inhalt: str):
    p = tmp_path / name
    p.write_text(inhalt, encoding="utf-8")
    return p


# --- load_config -------------------------------------------------------------------------------
def test_load_config_liest_die_ausgelieferte_config_yaml():
    cfg = config.load_config()
    assert cfg["_root"] == str(config.ROOT)
    for abschnitt in ("hotkey", "audio", "stt", "llm", "inject", "ui", "snip"):
        assert isinstance(cfg[abschnitt], dict), abschnitt


def test_load_config_mit_eigenem_pfad(tmp_path):
    p = _datei(tmp_path, "c.yaml", "llm:\n  model: x\n  keep_alive: -1\n")
    assert config.load_config(p) == {"llm": {"model": "x", "keep_alive": -1}, "_root": str(config.ROOT)}


def test_load_config_leere_datei_gibt_nur_root(tmp_path):
    assert config.load_config(_datei(tmp_path, "leer.yaml", "")) == {"_root": str(config.ROOT)}


def test_load_config_fehlende_datei(tmp_path):
    with pytest.raises(FileNotFoundError, match="gibtsnicht.yaml"):
        config.load_config(tmp_path / "gibtsnicht.yaml")


# --- load_dictionary_tiers ---------------------------------------------------------------------
def test_marker_trennt_whisper_stufe_von_cleanup_stufe(tmp_path):
    """Fall aus selftest.py: Kommentare und Leerzeilen raus, Duplikat raus, Marker trennt."""
    p = _datei(tmp_path, "d.txt", "# Kommentar\nAlpha\nBeta\nAlpha\n\n"
               "# === NUR-CLEANUP (nur fuers Aufraeum-Modell)\n# noch ein Kommentar\nGamma\nDelta\n")
    assert config.load_dictionary_tiers({"dictionary_path": str(p)}) == (["Alpha", "Beta"], ["Gamma", "Delta"])


def test_duplikate_ohne_gross_klein_und_ueber_beide_stufen(tmp_path):
    """Die erste Nennung gewinnt; ein Begriff aus der Whisper-Stufe kommt nicht nochmal in die
    Cleanup-Stufe (sonst stuende er doppelt im LLM-Woerterbuch)."""
    p = _datei(tmp_path, "d.txt", "Nextcloud\nnextcloud\n  Ollama  \n"
               "   # === NUR-CLEANUP\nOLLAMA\nGrafana\ngrafana\nZigbee\n")
    assert config.load_dictionary_tiers({"dictionary_path": str(p)}) == (["Nextcloud", "Ollama"], ["Grafana", "Zigbee"])


def test_ohne_marker_ist_alles_whisper_stufe(tmp_path):
    p = _datei(tmp_path, "d.txt", "Alpha\n# Kommentar\nBeta\n")
    assert config.load_dictionary_tiers({"dictionary_path": str(p)}) == (["Alpha", "Beta"], [])


def test_fehlendes_woerterbuch_gibt_leere_stufen(tmp_path):
    assert config.load_dictionary_tiers({"dictionary_path": str(tmp_path / "fehlt.txt")}) == ([], [])


def test_ausgeliefertes_woerterbuch_hat_zwei_getrennte_stufen():
    whisper, nur_cleanup = config.load_dictionary_tiers(config.load_config())
    assert whisper, "Whisper-Stufe leer"
    assert not {t.lower() for t in whisper} & {t.lower() for t in nur_cleanup}


# --- dictionary_prompt_seed --------------------------------------------------------------------
def test_prompt_seed():
    assert config.dictionary_prompt_seed([]) == ""
    assert config.dictionary_prompt_seed(["Nextcloud", "Leipzig"]) == "Begriffe: Nextcloud, Leipzig."


# --- load_employee_names -----------------------------------------------------------------------
def _namen(tmp_path, daten) -> tuple[list[str], list[str]]:
    p = _datei(tmp_path, "team.json", daten if isinstance(daten, str) else json.dumps(daten))
    return config.load_employee_names({"employees_from": str(p)})


@pytest.mark.parametrize("cfg", [{}, {"employees_from": None}, {"employees_from": ""}])
def test_namensliste_nicht_eingerichtet(cfg):
    assert config.load_employee_names(cfg) == ([], [])


def test_namensliste_datei_fehlt(tmp_path, capsys):
    assert config.load_employee_names({"employees_from": str(tmp_path / "fehlt.json")}) == ([], [])
    assert "name list not found" in capsys.readouterr().out


@pytest.mark.parametrize("inhalt", ["{kaputt", "", '["kein", "objekt"]', '{"members": ["Anna"]}'])
def test_namensliste_kaputt_gibt_leere_listen(tmp_path, capsys, inhalt):
    assert _namen(tmp_path, inhalt) == ([], [])
    assert "name list unreadable" in capsys.readouterr().out


def test_namensliste_nur_aktive_vornamen_ohne_doppelte(tmp_path):
    daten = {"members": [
        {"name": " Anna Muster ", "aktiv": True},
        {"name": "Ben Beispiel", "aktiv": False},
        {"name": "anna Anders", "aktiv": True},
        {"aktiv": True},
        {"name": "Cem Test", "aktiv": True},
    ]}
    assert _namen(tmp_path, daten) == (["Anna", "Cem"], ["Anna Muster", "anna Anders", "Cem Test"])


@pytest.mark.parametrize("eintrag", [{"name": "   ", "aktiv": True}, {"name": 123, "aktiv": True}])
def test_namensliste_mit_kaputtem_eintrag_stuerzt_nicht_ab(tmp_path, capsys, eintrag):
    """Bis 24.09.2026 brach ein solcher Eintrag den App-Start ab (IndexError/AttributeError hinter
    dem try). Jetzt: Eintrag ueberspringen, eine Konsolenzeile, der Rest der Liste gilt."""
    daten = {"members": [{"name": "Anna Muster", "aktiv": True}, eintrag, {"name": "Cem Test", "aktiv": True}]}
    assert _namen(tmp_path, daten) == (["Anna", "Cem"], ["Anna Muster", "Cem Test"])
    assert capsys.readouterr().out == "[config] name list: skipped 1 active entry without a usable name\n"


def test_namensliste_mehrere_kaputte_eintraege_eine_zeile(tmp_path, capsys):
    daten = {"members": [{"name": "   ", "aktiv": True}, {"name": ["Anna"], "aktiv": True},
                         {"name": "Ben Beispiel", "aktiv": True}, {"name": 7, "aktiv": True},
                         {"name": "   ", "aktiv": False}]}
    assert _namen(tmp_path, daten) == (["Ben"], ["Ben Beispiel"])
    assert capsys.readouterr().out.splitlines() == ["[config] name list: skipped 3 active entries without a usable name"]


# --- config.local.yaml ueber config.yaml (Arbeitspaket 7, 25.09.2026) ---------------------------
BASIS = """\
hotkey:
  key: "ctrl_r"
  mode: "hold"
audio:
  input_device: null
  samplerate: 16000
context:
  app_categories:
    slack: "chat"
    outlook: "email"
liste: [1, 2, 3]
dictionary_path: "dictionary.txt"
"""


def _paar(tmp_path, lokal: str | None):
    """config.yaml (BASIS) und daneben, falls lokal nicht None, config.local.yaml."""
    basis = _datei(tmp_path, "config.yaml", BASIS)
    if lokal is not None:
        _datei(tmp_path, "config.local.yaml", lokal)
    return basis


def test_ohne_lokale_datei_bleibt_alles_wie_bisher(tmp_path):
    cfg = config.load_config(_paar(tmp_path, None))
    assert "_local" not in cfg and cfg["hotkey"] == {"key": "ctrl_r", "mode": "hold"}
    assert config.local_summary_lines(cfg) == []


def test_verschachtelt_zusammengefuehrt_liste_und_werte_ersetzt(tmp_path):
    lokal = ('hotkey:\n  key: "f8"\ncontext:\n  app_categories:\n    slack: "email"\n    zoom: "chat"\n'
             "liste: [9]\ndictionary_path: \"C:/Eigenes/woerter.txt\"\n")
    cfg = config.load_config(_paar(tmp_path, lokal))
    assert cfg["hotkey"] == {"key": "f8", "mode": "hold"}                 # mode bleibt aus config.yaml
    assert cfg["context"]["app_categories"] == {"slack": "email", "outlook": "email", "zoom": "chat"}
    assert cfg["liste"] == [9]                                             # Liste ersetzt, nicht angehaengt
    assert cfg["dictionary_path"] == "C:/Eigenes/woerter.txt"
    assert cfg["audio"] == {"input_device": None, "samplerate": 16000}    # nicht genannt: unveraendert
    assert cfg["_local"]["changed"] == ["hotkey.key", "context.app_categories.slack", "liste",
                                        "dictionary_path"]
    assert cfg["_local"]["new"] == ["context.app_categories.zoom"]


@pytest.mark.parametrize("inhalt", ["", "\n\n", "# nur ein Kommentar\n#hotkey:\n#  key: f8\n"])
def test_leere_oder_nur_kommentierte_datei_aendert_nichts(tmp_path, inhalt):
    (tmp_path / "ohne").mkdir()
    ohne = config.load_config(_paar(tmp_path / "ohne", None))
    mit = config.load_config(_paar(tmp_path, inhalt))
    assert {k: v for k, v in mit.items() if k != "_local"} == ohne
    assert mit["_local"] == {"file": "config.local.yaml", "changed": [], "new": []}
    assert config.local_summary_lines(mit) == [
        "[config] config.local.yaml found, but it sets nothing (it is empty or only has comments)"]


def test_abschnitt_mit_nur_auskommentierten_zeilen_aendert_nichts(tmp_path):
    """YAML liest "hotkey:" mit nur auskommentierten Zeilen darunter als null. Ersetzt das den
    Abschnitt, stuerzt die App an cfg["hotkey"].get(...) ab - also: leerer Abschnitt = keine Aenderung."""
    cfg = config.load_config(_paar(tmp_path, 'hotkey:\n  # key: "f8"\naudio:\n  input_device: 2\n'))
    assert cfg["hotkey"] == {"key": "ctrl_r", "mode": "hold"}
    assert cfg["audio"]["input_device"] == 2
    assert cfg["_local"]["changed"] == ["audio.input_device"]


@pytest.mark.parametrize("lokal, art", [("hotkey: f8\n", "a single value"), ("audio: [1, 2]\n", "a list")])
def test_abschnitt_durch_einzelwert_ersetzt_ist_ein_klarer_fehler(tmp_path, lokal, art):
    with pytest.raises(config.ConfigError) as fehler:
        config.load_config(_paar(tmp_path, lokal))
    text = str(fehler.value)
    assert text.startswith("config.local.yaml: '") and art in text


@pytest.mark.parametrize("kaputt, zeile, anfang", [
    ('hotkey:\n  key: "f8"\n mode: toggle\n', 3, ""),        # Einrueckung verrutscht
    ("audio:\n\tinput_device: 2\n", 2, ""),                  # Tabulator statt Leerzeichen
    # Anfuehrungszeichen nicht geschlossen: YAML merkt es erst am Dateiende (Zeile 3), die Meldung
    # nennt zusaetzlich die Zeile, in der es anfing.
    ('hotkey:\n  key: "f8\n', 3, "(while scanning a quoted scalar in line 2)"),
])
def test_kaputte_datei_nennt_datei_und_zeile(tmp_path, kaputt, zeile, anfang):
    with pytest.raises(config.ConfigError) as fehler:
        config.load_config(_paar(tmp_path, kaputt))
    text = str(fehler.value)
    assert text.startswith(f"config.local.yaml, line {zeile}, column ")
    assert anfang in text
    assert "delete it to use config.yaml alone" in text               # die Abhilfe steht dabei
    assert isinstance(fehler.value, ValueError)                      # kein YAML-Fehlertyp nach aussen


def test_kaputte_config_yaml_selbst_ebenso(tmp_path):
    with pytest.raises(config.ConfigError, match=r"^c\.yaml, line 2, column \d+: .* -> fix the file$"):
        config.load_config(_datei(tmp_path, "c.yaml", "a:\n\tb: 1\n"))


@pytest.mark.parametrize("inhalt", ["- eine\n- liste\n", "nur text\n"])
def test_lokale_datei_ohne_schluessel_ist_ein_fehler(tmp_path, inhalt):
    with pytest.raises(config.ConfigError, match=r"^config\.local\.yaml: expected settings as 'key: value'"):
        config.load_config(_paar(tmp_path, inhalt))


def test_nicht_utf8_ist_ein_klarer_fehler(tmp_path):
    """Aeltere Windows-Editoren speichern ANSI (cp1252): ein Umlaut darin ist kein UTF-8."""
    _paar(tmp_path, None)
    (tmp_path / "config.local.yaml").write_bytes("audio:\n  input_device: \"Mikro Büro\"\n".encode("cp1252"))
    with pytest.raises(config.ConfigError, match=r"^config\.local\.yaml: not UTF-8 text"):
        config.load_config(tmp_path / "config.yaml")


def test_protokollzeile_nennt_schluessel_ohne_werte(tmp_path):
    lokal = ('audio:\n  input_device: "Geheimes Headset 4711"\nhotkey:\n  key: "f8"\n'
             'dictionary_path: "C:/Users/max/privat.txt"\nhotkee:\n  key: "f9"\n')
    zeilen = config.local_summary_lines(config.load_config(_paar(tmp_path, lokal)))
    assert zeilen == [
        "[config] config.local.yaml overrides: audio.input_device, hotkey.key, dictionary_path",
        "[config] config.local.yaml sets keys that config.yaml does not have (typo?): hotkee"]
    for wert in ("Geheimes Headset", "4711", "f8", "f9", "privat", "C:/"):
        assert all(wert not in z for z in zeilen), wert


def test_standardpfad_nimmt_local_config_path(tmp_path, monkeypatch):
    """Ohne eigenen Pfad: die config.yaml des Projekts und LOCAL_CONFIG_PATH (in allen Tests eine
    Datei, die es nicht gibt, siehe tests/conftest.py - hier ausdruecklich eine eigene)."""
    assert not config.LOCAL_CONFIG_PATH.exists()
    assert "_local" not in config.load_config()
    lokal = _datei(tmp_path, "config.local.yaml", "llm:\n  model: eigenes-modell\n")
    monkeypatch.setattr(config, "LOCAL_CONFIG_PATH", lokal)
    cfg = config.load_config()
    assert cfg["llm"]["model"] == "eigenes-modell" and cfg["llm"]["base_url"]   # Rest aus config.yaml
    assert cfg["_local"]["changed"] == ["llm.model"]


def test_merge_veraendert_die_eingaben_nicht():
    basis = {"a": {"b": 1, "c": 2}}
    lokal = {"a": {"b": 5}}
    ergebnis, geaendert, neu = config.merge(basis, lokal)
    assert ergebnis == {"a": {"b": 5, "c": 2}} and geaendert == ["a.b"] and neu == []
    assert basis == {"a": {"b": 1, "c": 2}} and lokal == {"a": {"b": 5}}


# --- Vorlage config.local.example.yaml -------------------------------------------------------------
_BEISPIELZEILE = re.compile(r"^# ( *[a-z_]+:(?: .*)?)$")


def _beispiele() -> dict:
    """Die auskommentierten Beispiele der Vorlage, einkommentiert: Zeilen '# key: ...' bzw.
    '#   key: ...' (Erklaertext beginnt nie mit einem kleingeschriebenen Schluessel und Doppelpunkt)."""
    text = config.LOCAL_EXAMPLE_PATH.read_text(encoding="utf-8")
    zeilen = [m.group(1) for z in text.splitlines() if (m := _BEISPIELZEILE.match(z))]
    return yaml.safe_load("\n".join(zeilen))


def test_vorlage_unveraendert_kopiert_aendert_nichts(tmp_path):
    (tmp_path / "config.local.yaml").write_text(config.LOCAL_EXAMPLE_PATH.read_text(encoding="utf-8"),
                                                encoding="utf-8")
    (tmp_path / "config.yaml").write_text(config.CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    cfg = config.load_config(tmp_path / "config.yaml")
    assert cfg["_local"]["changed"] == [] and cfg["_local"]["new"] == []
    assert "nach config.local.yaml kopieren" in config.LOCAL_EXAMPLE_PATH.read_text(encoding="utf-8")


def test_vorlage_zeigt_die_verlangten_beispiele_und_alle_passen_zu_config_yaml():
    beispiele = _beispiele()
    assert {"hotkey", "snip", "audio", "dictionary_path", "aliases_path", "stt", "llm"} <= set(beispiele)
    assert "key" in beispiele["hotkey"] and "key" in beispiele["snip"]
    assert "input_device" in beispiele["audio"] and "model" in beispiele["llm"]
    ausgeliefert = config.load_config()
    _, geaendert, neu = config.merge(ausgeliefert, beispiele)
    assert neu == []                                  # kein Beispiel mit einem Schluessel, den es nicht gibt
    assert geaendert == ["hotkey.key", "snip.key", "audio.input_device", "dictionary_path",
                         "aliases_path", "stt.model", "llm.model"]


def test_vorlagen_taste_ist_ein_gueltiger_diktat_tastenname(capsys):
    from wf import hotkey
    hotkey.resolve_key(_beispiele()["hotkey"]["key"])
    assert "WARNING" not in capsys.readouterr().out


# --- ensure_local_config (Tray -> Einstellungen) ---------------------------------------------------
def test_legt_config_local_aus_der_vorlage_an(tmp_path):
    vorlage = _datei(tmp_path, "vorlage.yaml", "# Beispiel\n# hotkey:\n#   key: f8\n")
    ziel = tmp_path / "config.local.yaml"
    assert config.ensure_local_config(ziel, vorlage) == (ziel, True)
    assert ziel.read_text(encoding="utf-8") == vorlage.read_text(encoding="utf-8")


def test_vorhandene_config_local_bleibt_unberuehrt(tmp_path):
    vorlage = _datei(tmp_path, "vorlage.yaml", "# Vorlage\n")
    ziel = _datei(tmp_path, "config.local.yaml", "hotkey:\n  key: f8\n")
    assert config.ensure_local_config(ziel, vorlage) == (ziel, False)
    assert ziel.read_text(encoding="utf-8") == "hotkey:\n  key: f8\n"


def test_ohne_vorlage_eine_kopfzeile(tmp_path):
    ziel, neu = config.ensure_local_config(tmp_path / "config.local.yaml", tmp_path / "fehlt.yaml")
    assert neu and ziel.read_text(encoding="utf-8").startswith("# my-local-whisper")
    assert yaml.safe_load(ziel.read_text(encoding="utf-8")) is None      # aendert nichts
