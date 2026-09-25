"""calibrate.py: die Auswertung der Antwort auf eine Alias-Rueckfrage (Arbeitspaket 9).

Befund: gefragt wurde "[j/n/eigene]", und nur "j" galt als Ja. Wer englisch "y" tippte, legte
"y" als eigene Schreibweise an ("Begriff = y" in aliases.txt), statt den Vorschlag zu
uebernehmen. Die Rueckfrage selbst (Mikrofon, Taste, input) laeuft hier nicht; geprueft wird die
reine Funktion, die aus der Antwort die zu speichernde Schreibweise macht."""
from __future__ import annotations

import pytest

import calibrate

VORSCHLAG = "Sigbee"


@pytest.mark.parametrize("antwort", ["j", "J", "ja", "Ja", "JA", "y", "Y", "yes", "Yes", "YES", " y ", "ja\n"])
def test_ja_auf_deutsch_und_englisch_uebernimmt_den_vorschlag(antwort):
    assert calibrate._antwort_auswerten(antwort, VORSCHLAG) == VORSCHLAG


@pytest.mark.parametrize("antwort", ["n", "N", "nein", "Nein", "no", "No", "NO", "", "   "])
def test_nein_auf_deutsch_und_englisch_und_leer_speichert_nichts(antwort):
    assert calibrate._antwort_auswerten(antwort, VORSCHLAG) is None


@pytest.mark.parametrize("antwort, erwartet", [
    ("Zigbee-Funk", "Zigbee-Funk"),
    ("  Sigbi ", "Sigbi"),
    ("yo", "yo"),                                  # nur die genannten Woerter zaehlen als Ja/Nein
    ("jein", "jein"),
])
def test_alles_andere_ist_die_eigene_schreibweise_wie_bisher(antwort, erwartet):
    assert calibrate._antwort_auswerten(antwort, VORSCHLAG) == erwartet


@pytest.mark.parametrize("antwort", ["j", "y", "yes", "n", "no", ""])
def test_ohne_vorschlag_wird_ja_oder_nein_kein_alias(antwort):
    """Zweite Rueckfrage ("kein aehnliches Wort gefunden, gehoerte Variante eintippen"): ein Ja
    hat nichts zu uebernehmen und wird nicht selbst zur Schreibweise ("Begriff = y")."""
    assert calibrate._antwort_auswerten(antwort, None) is None


def test_ohne_vorschlag_bleibt_die_eingetippte_variante():
    assert calibrate._antwort_auswerten("Sigbi", None) == "Sigbi"


def test_rueckfrage_zeigt_beide_sprachen():
    """Der Prompt-Text nennt Ja/Nein auf Deutsch und Englisch (Quelltext gelesen, weil die
    Rueckfrage selbst Mikrofon und Taste braucht)."""
    quelle = calibrate.Path(calibrate.__file__).read_text(encoding="utf-8")
    assert "[j/y = ja/yes, n = nein/no, oder richtige Schreibweise]" in quelle
    assert "[j/n/eigene]" not in quelle
