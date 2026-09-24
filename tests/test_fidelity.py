"""wf/fidelity.py: die Faelle aus selftest.py, als pytest. Nur das bestehende Verhalten wird
festgehalten (24.09.2026); bekannte Schwaechen des Treue-Waechters behebt ein eigenes Paket."""
from __future__ import annotations

import pytest

from wf import fidelity as fd

LANG_ROH = ("also ähm ich wollte fragen ob wir ähm vielleicht am samstag noch einen raum frei haben "
            "für sechs personen und ob das ähm auch mit kindern geht")


@pytest.mark.parametrize("text, zahl", [
    ("das budget eher fünfundsiebzig euro", 75),
    ("zweihundertdreiundvierzig Gäste", 243),
    ("dreitausendfünfhundert", 3500),
])
def test_zahlwoerter(text, zahl):
    assert zahl in fd.numbers_in(text)


def test_ziffern_mit_suffix_dezimal_und_tausenderpunkt():
    assert 75000 in fd.digit_numbers_in("eher 75k") and 75 not in fd.digit_numbers_in("eher 75k")
    assert {3, 50} <= fd.digit_numbers_in("3,50 Euro")
    assert 1250 in fd.digit_numbers_in("1.250 Bewertungen")


@pytest.mark.parametrize("roh, bereinigt", [
    ("das budget eher fünfundsiebzig euro", "Das Budget eher 75 Euro."),
    ("fünfzig nein fünfundsiebzig", "75."),                              # Selbstkorrektur
    ("um vierzehn uhr dreißig", "Um 14:30."),
    ("erstens das und zweitens jenes", "1. Das und 2. jenes."),
    ("ein ticket bitte", "1 Ticket bitte."),
    ("schick es an info@example.com", "Schick es an info@example.com."),
    (LANG_ROH, "Ich wollte fragen, ob wir am Samstag noch einen Raum für 6 Personen frei haben "
               "und ob das auch mit Kindern geht."),                     # normale Kuerzung
], ids=["ziffern", "selbstkorrektur", "uhrzeit", "aufzaehlung", "ein-ticket", "mail-erhalten", "kuerzung"])
def test_erlaubt(roh, bereinigt):
    assert fd.check(roh, bereinigt) == ""


@pytest.mark.parametrize("roh, bereinigt, grund", [
    ("das budget eher fünfundsiebzig", "Das Budget eher 75k.", "Zahl 75000"),
    ("schick es an info@example.com", "Schick es an info@example.org.", "info@example.com"),
    (LANG_ROH, "Raum frei?", "zu kurz"),
], ids=["erfundene-zahl", "mail-veraendert", "auslassung"])
def test_abgelehnt(roh, bereinigt, grund):
    assert grund in fd.check(roh, bereinigt)


def test_min_ratio_null_schaltet_die_laengenpruefung_ab():
    """config.yaml: fidelity_min_ratio 0 = Laengenpruefung aus."""
    assert fd.check(LANG_ROH, "Raum frei?", 0) == ""
