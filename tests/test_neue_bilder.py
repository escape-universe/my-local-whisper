"""tools/neue-bilder.py: der Standard-Bilderordner muss zu config.yaml passen (Arbeitspaket 6)."""
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
