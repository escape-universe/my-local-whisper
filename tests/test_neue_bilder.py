"""tools/neue-bilder.py: der Bilder-Ordner muss zur wirksamen Konfiguration passen - config.yaml
(Arbeitspaket 6) und seit K1 (25.09.2026) auch einer config.local.yaml daneben (Arbeitspaket 7)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _modul():
    spec = importlib.util.spec_from_file_location("neue_bilder", ROOT / "tools" / "neue-bilder.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_standardordner_ist_data_images_wenn_snip_folder_fehlt(tmp_path):
    """Bisher fiel dieses Skript auf data/bilder zurueck (whisperflow.py ebenso), obwohl
    config.yaml selbst data/images sagt - uneinheitlich, sobald snip.folder in der geladenen
    config fehlt."""
    nb = _modul()
    ohne_folder = tmp_path / "ohne-snip-folder.yaml"
    ohne_folder.write_text("snip:\n  enabled: true\n", encoding="utf-8")
    assert nb.ordner(ohne_folder).name == "images"


def test_snip_folder_aus_der_config_hat_vorrang(tmp_path):
    nb = _modul()
    mit_folder = tmp_path / "mit-snip-folder.yaml"
    mit_folder.write_text("snip:\n  folder: data/eigener-ordner\n", encoding="utf-8")
    assert nb.ordner(mit_folder).name == "eigener-ordner"


def test_snip_folder_aus_config_local_yaml_hat_vorrang(tmp_path):
    """K1 (Schlusspruefung B2, 25.09.2026): eigene Einstellungen gehoeren seit Arbeitspaket 7 in
    config.local.yaml, nicht mehr in config.yaml selbst (wf/config.py). Bisher las ordner() nur
    config.yaml direkt und fand die Bilder nicht mehr, sobald snip.folder ausschliesslich lokal
    gesetzt war - genau das Szenario aus der Schlusspruefung: die App speichert nach
    data/meine-shots, der Zubringer suchte weiter in data/images."""
    nb = _modul()
    basis = tmp_path / "config.yaml"
    basis.write_text("snip:\n  folder: data/images\n", encoding="utf-8")
    (tmp_path / "config.local.yaml").write_text("snip:\n  folder: data/meine-shots\n", encoding="utf-8")
    assert nb.ordner(basis).name == "meine-shots"


def test_kaputte_config_local_yaml_warnt_und_faellt_auf_config_yaml_zurueck(tmp_path, capsys):
    """Eine kaputte config.local.yaml darf den Zubringer nicht abstuerzen lassen (anders als die
    App: die bricht den Start ab, siehe whisperflow._load_config_or_explain). Eine kurze Zeile auf
    stderr ist in Ordnung, dann gilt config.yaml allein weiter - kein stummes data/images."""
    nb = _modul()
    basis = tmp_path / "config.yaml"
    basis.write_text("snip:\n  folder: data/eigener-ordner\n", encoding="utf-8")
    # "snip" ist in config.yaml ein Abschnitt (dict); ein einzelner Wert darunter ist ein klarer
    # Fehler (wf/config.py merge()), unabhaengig von YAML-Syntax.
    (tmp_path / "config.local.yaml").write_text("snip: nicht-abschnitt\n", encoding="utf-8")
    assert nb.ordner(basis).name == "eigener-ordner"
    assert "config.local.yaml" in capsys.readouterr().err
