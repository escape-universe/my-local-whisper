"""wf/lang.py: deterministischer DE/EN-Pruefer, Sprach-Guard, Schriftsystem-Pruefung, Namen."""
from __future__ import annotations

import pytest

from wf import lang

DE = "wir haben das nicht gemacht und das ist auch gut"
EN = "we have not done that and it is fine for us"


@pytest.mark.parametrize("text, erwartet", [
    (DE, "de"),
    (EN, "en"),
    ("ok gut", ""),                                          # zu kurz (< 4 Woerter)
    ("Besprechungsraum Leipzig Hannover Nienburg", ""),      # kein Stoppwort
    ("the und is die and ist", ""),                          # kein klarer Vorsprung
    ("", ""),
    (None, ""),
])
def test_sniff_de_en(text, erwartet):
    assert lang.sniff_de_en(text) == erwartet


def test_sprachwechsel_en_rein_de_raus():
    assert lang.switched_language("en", "we should move the meeting to tomorrow morning",
                                  "wir sollten das Treffen auf morgen früh verschieben")


def test_gleiche_sprache_ist_kein_wechsel():
    assert not lang.switched_language("de", "wir sollten das treffen auf morgen verschieben und das ist gut",
                                      "Wir sollten das Treffen auf morgen verschieben, und das ist gut.")


def test_unklarer_kurztext_loest_nicht_aus():
    assert not lang.switched_language("de", "Besprechungsraum Leipzig", "Besprechungsraum Leipzig")


def test_whispers_sprache_kippt_ein_klares_ergebnis_nicht():
    """Bestehendes Verhalten: sind Ein- und Ausgabe erkennbar gleich, zaehlt Whispers Erkennung
    nicht (hier falsch 'en' bei deutschem Text) -> kein Wechsel."""
    assert not lang.switched_language("en", DE, "Wir haben das nicht gemacht, und das ist auch gut.")


@pytest.mark.parametrize("ziel, text, falsch", [
    ("it", "我可以给你们预定", True),                          # gemessen 08.09.2026
    ("it", "Abbiamo due gruppi liberi sabato.", False),
    ("ru", "We have two groups free.", True),
    ("ru", "У нас есть две свободные группы.", False),
    ("de", "У нас есть две свободные группы.", True),         # ueberwiegend Kyrillisch
    ("en", 'He said "Спасибо" and left the room.', False),    # kurzes Zitat ist in Ordnung
    ("fr", "Nous avons deux groupes.", False),                # keine Zielsprache: keine Aussage
    ("fr", "我可以", True),                                   # CJK ist nie richtig
    ("it", "", False),
])
def test_wrong_script(ziel, text, falsch):
    assert lang.wrong_script(ziel, text) is falsch


def test_sprachnamen():
    assert lang.name_en("de") == "German" and lang.name_en("IT") == "Italian"
    assert lang.name_en("xx") == "xx" and lang.name_en("") == "the source language"
    assert lang.name_native("ru") == "Русский" and lang.name_native("fr") == "French"
    assert lang.name_native("") == "?"
    assert [code for code, _ in lang.TARGETS] == ["en", "de", "es", "it", "ru"]
