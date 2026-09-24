"""wf/config.py: config.yaml laden, zweistufiges Woerterbuch, Prompt-Seed, optionale Namensliste."""
from __future__ import annotations

import json

import pytest

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
