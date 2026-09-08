"""S10 — Sprache: Namen, Zielsprachen und ein deterministischer DE/EN-Pruefer.

Zweck (08.09.2026): Der Cleanup hat Englisch still ins Deutsche uebersetzt, obwohl im
Prompt "Do NOT translate" steht — ein 3B-Modell kippt in die Sprache seiner Beispiele.
Die Sprache wird deshalb NICHT mehr dem Modell ueberlassen: Whisper erkennt sie, wir
geben sie hart vor und pruefen die Ausgabe deterministisch nach. Weicht sie ab, gilt
der Rohtext (lieber ungeputzt als in der falschen Sprache).
"""
from __future__ import annotations

import re

# Zielsprachen des Uebersetzungsmodus (Entscheidung 08.09.2026). Reihenfolge = Tray-Menue.
# Beschriftung = der Sprachname in der Sprache selbst. So passt das Menue zu jeder
# Oberflaechensprache, ohne eine eigene Uebersetzungstabelle pro Sprache (09.09.2026).
TARGETS: list[tuple[str, str]] = [
    ("en", "English"),
    ("de", "Deutsch"),
    ("es", "Español"),
    ("it", "Italiano"),
    ("ru", "Русский"),
]

_NAMES = {
    "de": "German", "en": "English", "es": "Spanish", "it": "Italian", "ru": "Russian",
    "fr": "French", "nl": "Dutch", "pl": "Polish", "tr": "Turkish", "pt": "Portuguese",
}

_NAMES_NATIVE = dict(TARGETS)


def name_en(code: str) -> str:
    """Sprachname fuer den Prompt (englisch, weil das Modell so am zuverlaessigsten folgt)."""
    return _NAMES.get((code or "").lower(), (code or "the source language"))


def name_native(code: str) -> str:
    """Sprachname in der Sprache selbst — fuer Tray-Menue und Meldungen."""
    return _NAMES_NATIVE.get((code or "").lower(), _NAMES.get((code or "").lower(), code or "?"))


# --- Deterministischer Guard: hat die Ausgabe die Sprache gewechselt? -------------
# Absichtlich nur DE vs. EN. Das ist der Fall, der real auftrat (der Nutzer diktiert DE/EN),
# und nur dort ist eine Stoppwort-Zaehlung ohne Zusatzpaket verlaesslich. Bei allem
# anderen gibt der Pruefer "unbekannt" zurueck und der Guard greift NICHT — ein
# Pruefwerkzeug, das raet, waere schlimmer als keines.
_DE = {"der", "die", "das", "und", "ist", "nicht", "ich", "wir", "auf", "mit", "für", "fuer",
       "eine", "einen", "einem", "dass", "noch", "auch", "aber", "wenn", "wird", "sind",
       "kann", "koennen", "können", "haben", "hat", "sich", "dem", "den", "zum", "zur",
       "vom", "bei", "nach", "über", "ueber", "schon", "immer", "sehr", "mal", "geht"}
_EN = {"the", "and", "is", "not", "you", "we", "on", "with", "for", "a", "an", "that",
       "still", "also", "but", "if", "will", "are", "can", "have", "has", "it", "to",
       "of", "in", "at", "this", "there", "would", "could", "should", "about", "from"}

_WORD_RX = re.compile(r"[a-zA-ZäöüÄÖÜßáéíóúàèìòùñçâêîôûšžčć]+")


def sniff_de_en(text: str) -> str:
    """'de' | 'en' | '' (unbekannt/zu kurz/andere Sprache). Rein deterministisch."""
    words = [w.lower() for w in _WORD_RX.findall(text or "")]
    if len(words) < 4:
        return ""
    de = sum(1 for w in words if w in _DE)
    en = sum(1 for w in words if w in _EN)
    if de == 0 and en == 0:
        return ""
    # Klarer Vorsprung noetig (>=2 Treffer UND doppelt so viele) — sonst lieber "unbekannt".
    if de >= 2 and de >= en * 2:
        return "de"
    if en >= 2 and en >= de * 2:
        return "en"
    return ""


# --- Schriftsystem-Pruefung fuer den Uebersetzungsmodus --------------------------
# Gemessen 08.09.2026: qwen2.5:3b lieferte bei Ziel "Italienisch" einen chinesischen Satz.
# Das ist kein Stil-, sondern ein Totalausfall — und deterministisch erkennbar, weil das
# Schriftsystem nicht passt. Die Pruefung sagt NICHT, ob die Uebersetzung gut ist; sie
# faengt nur den Fall "voellig andere Schrift" ab.
_CJK_RX = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
_CYR_RX = re.compile(r"[Ѐ-ӿ]")
_LATIN_RX = re.compile(r"[a-zA-ZäöüÄÖÜßáéíóúàèìòùñç]")


def wrong_script(target: str, text: str) -> bool:
    """True, wenn der Text offensichtlich nicht im Schriftsystem der Zielsprache steht."""
    if not text:
        return False
    code = (target or "").lower()
    if _CJK_RX.search(text):
        return True                      # keine unserer Zielsprachen nutzt CJK
    if code == "ru":
        return not _CYR_RX.search(text)  # Russisch ohne ein einziges kyrillisches Zeichen
    if code in ("en", "de", "es", "it"):
        # Ein paar kyrillische Zeichen koennen ein Zitat sein; ueberwiegt Kyrillisch, ist es falsch.
        return len(_CYR_RX.findall(text)) > len(_LATIN_RX.findall(text))
    return False


def switched_language(source_lang: str, before: str, after: str) -> bool:
    """True nur bei einem BELEGTEN Sprachwechsel DE<->EN zwischen Ein- und Ausgabe.

    Beide Seiten muessen erkennbar sein und sich unterscheiden. Alles Unklare gilt als
    "kein Wechsel" — der Guard soll Uebersetzungen fangen, nicht Umlaute oder Fachwoerter.
    """
    a = sniff_de_en(before)
    b = sniff_de_en(after)
    if not a or not b:
        return False
    if a != b:
        return True
    # Zusatzprobe gegen Whispers Erkennung, falls die eindeutig DE/EN war.
    src = (source_lang or "").lower()
    return bool(src in ("de", "en") and b != src and a == src)
