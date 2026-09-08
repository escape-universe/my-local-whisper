"""Treue-Regeln fuers Aufraeumen (08.09.2026, Astra-Review Punkt 3 + der Nutzer: „Texte sollen so ankommen,
wie ich sie spreche").

Das Aufraeum-Modell darf glaetten (Fuellwoerter weg, Zahlen als Ziffern, Satzzeichen), aber NICHT den
Inhalt aendern. Diese Pruefungen sind deterministisch und laufen NACH dem Modell; schlaegt eine an,
bleibt der Rohtext (lieber ungeputzt als falsch). Belegter Fall: „fuenfundsiebzig" -> „75k".

Regeln:
  1. Zahlen: Jede Ziffern-Zahl im Ergebnis muss im Rohtext vorkommen (als Ziffer oder als deutsches
     Zahlwort). Weglassen ist erlaubt (Selbstkorrektur „50, nein 75" -> „75"), Erfinden nicht.
     Suffixe wie „75k"/„2 Mio" zaehlen als eigene Zahl (75000) -> nur ok, wenn „tausend"/„Millionen"
     auch gesagt wurde.
  2. URLs, E-Mail-Adressen, @-Handles aus dem Rohtext muessen unveraendert im Ergebnis stehen.
  3. Auslassung: Das Ergebnis darf nicht auf weniger als `min_ratio` der Roh-Woerter schrumpfen
     (Fuellwoerter und Wiederholungen machen normal 10-30 % aus). Default 0.5.
"""
from __future__ import annotations

import re

_UNITS = {
    "null": 0, "ein": 1, "eins": 1, "eine": 1, "einen": 1, "einem": 1, "einer": 1, "zwei": 2, "zwo": 2,
    "drei": 3, "vier": 4, "fuenf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
    "elf": 11, "zwoelf": 12, "dreizehn": 13, "vierzehn": 14, "fuenfzehn": 15, "sechzehn": 16,
    "siebzehn": 17, "achtzehn": 18, "neunzehn": 19,
}
_TENS = {"zwanzig": 20, "dreissig": 30, "vierzig": 40, "fuenfzig": 50, "sechzig": 60, "siebzig": 70,
         "achtzig": 80, "neunzig": 90}
_ORDINALS = {"erstens": 1, "zweitens": 2, "drittens": 3, "viertens": 4, "fuenftens": 5, "sechstens": 6,
             "siebtens": 7, "achtens": 8, "neuntens": 9, "zehntens": 10,
             "erste": 1, "ersten": 1, "erster": 1, "zweite": 2, "zweiten": 2, "dritte": 3, "dritten": 3,
             "vierte": 4, "vierten": 4, "fuenfte": 5, "fuenften": 5, "sechste": 6, "siebte": 7, "achte": 8,
             "neunte": 9, "zehnte": 10, "elfte": 11, "zwoelfte": 12}
_SCALE_WORDS = {"hundert": 100, "tausend": 1000, "million": 1_000_000, "millionen": 1_000_000,
                "milliarde": 1_000_000_000, "milliarden": 1_000_000_000}
_SUFFIX = {"k": 1000, "tsd": 1000, "tsd.": 1000, "mio": 1_000_000, "mio.": 1_000_000, "mrd": 1_000_000_000, "mrd.": 1_000_000_000}

_TOKEN_RX = re.compile(r"[a-zäöüß]+|\d+", re.IGNORECASE)
_URL_RX = re.compile(r"(?:https?://\S+|www\.\S+|[\w.+-]+@[\w-]+\.[\w.-]+|(?<!\w)@\w{3,})", re.IGNORECASE)
_DIGIT_RX = re.compile(r"(?<![\w.])(\d{1,3}(?:[.\s]\d{3})+|\d+)(?:[,.](\d+))?\s*(k|tsd\.?|mio\.?|mrd\.?)?(?![\w])", re.IGNORECASE)


def _ascii(s: str) -> str:
    return s.lower().replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")


def _parse_number_word(word: str) -> int | None:
    """Ein zusammengesetztes deutsches Zahlwort -> int (bis Millionen). None wenn kein Zahlwort."""
    w = _ascii(word)
    if w in _ORDINALS:
        return _ORDINALS[w]
    if w in _SCALE_WORDS:
        return _SCALE_WORDS[w]
    total = 0
    current = 0
    rest = w
    progressed = True
    while rest and progressed:
        progressed = False
        for scale in ("millionen", "million", "tausend", "hundert"):
            if rest.startswith(scale):
                current = (current or 1) * _SCALE_WORDS[scale]
                total += current
                current = 0
                rest = rest[len(scale):]
                progressed = True
                break
        if progressed:
            continue
        # Einer + "und" + Zehner  (fuenfundsiebzig)
        m = re.match(r"^(ein|eins|zwei|zwo|drei|vier|fuenf|sechs|sieben|acht|neun)und(zwanzig|dreissig|vierzig|fuenfzig|sechzig|siebzig|achtzig|neunzig)", rest)
        if m:
            current += _UNITS[m.group(1)] + _TENS[m.group(2)]
            rest = rest[m.end():]
            progressed = True
            continue
        for tens, v in _TENS.items():
            if rest.startswith(tens):
                current += v
                rest = rest[len(tens):]
                progressed = True
                break
        if progressed:
            continue
        for unit in sorted(_UNITS, key=len, reverse=True):
            if rest.startswith(unit):
                current += _UNITS[unit]
                rest = rest[len(unit):]
                progressed = True
                break
    if rest:
        return None
    return total + current


def numbers_in(text: str) -> set[int]:
    """Alle Zahlen eines Texts als Werte: Ziffern (inkl. Suffix k/Mio) und Zahlwoerter.
    Dezimalzahlen liefern Vor- und Nachkommateil getrennt (3,50 -> {3, 50})."""
    out: set[int] = set()
    for m in _DIGIT_RX.finditer(text):
        base = int(re.sub(r"[.\s]", "", m.group(1)))
        suf = (m.group(3) or "").lower()
        if suf:
            out.add(base * _SUFFIX.get(suf, 1))
        else:
            out.add(base)
        if m.group(2):
            out.add(int(m.group(2)))
    for tok in _TOKEN_RX.findall(text):
        if tok.isdigit():
            continue
        v = _parse_number_word(tok)
        if v is not None:
            out.add(v)
    return out


def digit_numbers_in(text: str) -> set[int]:
    """Nur die als ZIFFERN geschriebenen Zahlen (die hat das Modell aktiv gesetzt)."""
    out: set[int] = set()
    for m in _DIGIT_RX.finditer(text):
        base = int(re.sub(r"[.\s]", "", m.group(1)))
        suf = (m.group(3) or "").lower()
        out.add(base * _SUFFIX.get(suf, 1) if suf else base)
        if m.group(2):
            out.add(int(m.group(2)))
    return out


def check(raw: str, cleaned: str, min_ratio: float = 0.5) -> str:
    """'' = in Ordnung, sonst Begruendung (Aufrufer nimmt dann den Rohtext)."""
    raw = raw or ""
    cleaned = cleaned or ""
    # 1) Zahlen
    allowed = numbers_in(raw)
    for n in digit_numbers_in(cleaned):
        if n not in allowed:
            # Uhrzeiten/Prozente/Jahreszahlen sind auch nur ok, wenn gesagt; keine Ausnahme.
            return f"Zahl {n} steht nicht im Gesprochenen"
    # 2) URLs / Mails / Handles
    low = cleaned.lower()
    for tok in _URL_RX.findall(raw):
        if tok.lower().rstrip(".,") not in low:
            return f"Adresse/Handle {tok!r} fehlt oder wurde veraendert"
    # 3) Auslassung
    rw = len(raw.split())
    cw = len(cleaned.split())
    if rw >= 8 and cw < rw * min_ratio:
        return f"Ergebnis zu kurz ({cw} von {rw} Woertern)"
    return ""
