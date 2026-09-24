"""wf/aliases.py: Hoerfehler -> richtige Schreibweise, an Wortgrenzen, laengste Variante zuerst."""
from __future__ import annotations

from wf import aliases, config


def _fixer(tmp_path, inhalt: str) -> aliases.AliasFixer:
    p = tmp_path / "aliases.txt"
    p.write_text(inhalt, encoding="utf-8")
    return aliases.AliasFixer(aliases.load_aliases(p))


def test_load_aliases_liest_regeln_laengste_zuerst(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("# Kommentar\n\nohne Gleichheitszeichen\n"
                 "Nextcloud = Nextclout, Next Cloud, nextcloud, , Nextcloude\n"
                 "Ollama = Olama\n", encoding="utf-8")
    paare = aliases.load_aliases(p)
    assert sorted(paare) == sorted([("Nextclout", "Nextcloud"), ("Next Cloud", "Nextcloud"),
                                    ("Nextcloude", "Nextcloud"), ("Olama", "Ollama")])
    assert [len(v) for v, _ in paare] == sorted((len(v) for v, _ in paare), reverse=True)


def test_fehlende_datei_gibt_keine_regeln(tmp_path):
    assert aliases.load_aliases(tmp_path / "fehlt.txt") == []
    assert len(aliases.AliasFixer([])) == 0


def test_ausgelieferte_aliases_wirken_an_wortgrenzen():
    """Fall aus selftest.py gegen die ausgelieferte aliases.txt."""
    paare = aliases.load_aliases(config.load_aliases_path(config.load_config()))
    assert len(paare) >= 5
    text, _ = aliases.AliasFixer(paare).fix("Lade es in Nextclout hoch, sunderbird bleibt zu. Nextclouts Ordner bleibt.")
    assert text == "Lade es in Nextcloud hoch, Thunderbird bleibt zu. Nextclouts Ordner bleibt."


def test_wortgrenzen(tmp_path):
    fx = _fixer(tmp_path, "Nextcloud = Nextclout\nTest = Tst\n")
    assert fx.fix("Nextclouts Ordner")[0] == "Nextclouts Ordner"          # Teil eines Worts: nein
    assert fx.fix("Nextclout's Ordner")[0] == "Nextcloud's Ordner"        # Apostroph: ja
    assert fx.fix("der Nextclout-Ordner")[0] == "der Nextcloud-Ordner"    # Bindestrich: ja
    assert fx.fix("Tstä äTst Tst.")[0] == "Tstä äTst Test."               # Umlaut zaehlt als Buchstabe


def test_gross_klein_egal_ziel_wie_eingetragen(tmp_path):
    fx = _fixer(tmp_path, "Nextcloud = Nextclout\n")
    assert fx.fix("nextclout, NEXTCLOUT und Nextclout")[0] == "Nextcloud, Nextcloud und Nextcloud"


def test_laengste_variante_zuerst(tmp_path):
    """Sonst machte die kurze Regel aus "Thunder Bird" erst "Donner Bird"."""
    fx = _fixer(tmp_path, "Donner = Thunder\nThunderbird = Thunder Bird\n")
    assert fx.fix("Thunder Bird und Thunder")[0] == "Thunderbird und Donner"


def test_angewandte_regeln_werden_gemeldet(tmp_path):
    """Lesbar als 'Variante->Ziel' (die Liste landet in der Konsole). Bis 24.09.2026 stand dort
    das Regex-Muster, z. B. '(?<![\\wäöüÄÖÜß])Nextclout(?![\\wäöüÄÖÜß])->Nextcloud'."""
    fx = _fixer(tmp_path, "Nextcloud = Nextclout\nOllama = Olama\n")
    text, angewandt = fx.fix("Olama und nextclout")
    assert text == "Ollama und Nextcloud"
    assert angewandt == ["Nextclout->Nextcloud", "Olama->Ollama"]     # laengste Variante zuerst
    assert fx.fix("nichts zu tun") == ("nichts zu tun", [])


def test_ziel_mit_backslash_wird_woertlich_eingesetzt(tmp_path):
    """Bis 24.09.2026 las re das Ziel als Ersetzungsmuster: "C:\\Temp" warf re.error (bad escape
    \\T), "\\1" haette eine Gruppe gesucht."""
    fx = _fixer(tmp_path, "C:\\Temp = temp ordner\nx\\1y = Gruppe eins\n")
    assert fx.fix("Leg es in den temp ordner.") == ("Leg es in den C:\\Temp.", ["temp ordner->C:\\Temp"])
    assert fx.fix("Das ist Gruppe eins.")[0] == "Das ist x\\1y."
