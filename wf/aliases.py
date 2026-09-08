"""Deterministische Nach-Korrektur: Hoer-Fehler -> richtige Schreibweise (aliases.txt).

Whisper schreibt Eigennamen phonetisch ("Nextclout", "Next Cloud" statt "Nextcloud"). Statt das dem LLM zu
ueberlassen (nicht reproduzierbar), steht jede bekannte Verwechslung als Zeile in aliases.txt:

    Nextcloud = Nextclout, Next Cloud, Nextcloude, Nexcloud

Links die richtige Form, rechts die gehoerten Varianten (Komma-getrennt). Ersetzt wird nur an
Wortgrenzen, unabhaengig von Gross-/Kleinschreibung; Bindestrich-Anhaengsel bleiben erhalten
("nextclouts" wird NICHT ersetzt, "Nextclout's" schon zu "Nextcloud's"). Reihenfolge: laengste Varianten zuerst.
Die Datei waechst durch die Kalibrierung (whisperflow.py --calibrate) oder von Hand.
"""
from __future__ import annotations

import re
from pathlib import Path


def load_aliases(path: Path) -> list[tuple[str, str]]:
    """-> [(gehoerte_variante, richtige_form), ...], laengste Varianten zuerst."""
    if not path.exists():
        return []
    pairs: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        target, _, variants = line.partition("=")
        target = target.strip()
        for v in variants.split(","):
            v = v.strip()
            if v and v.lower() != target.lower():
                pairs.append((v, target))
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


class AliasFixer:
    def __init__(self, pairs: list[tuple[str, str]]):
        self.pairs = pairs
        self._rx: list[tuple[re.Pattern[str], str]] = []
        for variant, target in pairs:
            # Wortgrenze ohne \b-Probleme bei Umlauten: Lookarounds auf Buchstaben/Ziffern
            pat = re.compile(r"(?<![\wäöüÄÖÜß])" + re.escape(variant) + r"(?![\wäöüÄÖÜß])", re.IGNORECASE)
            self._rx.append((pat, target))

    def fix(self, text: str) -> tuple[str, list[str]]:
        """-> (korrigierter Text, Liste der angewandten Ersetzungen 'Variante->Ziel')."""
        applied: list[str] = []
        for pat, target in self._rx:
            new, n = pat.subn(target, text)
            if n:
                applied.append(f"{pat.pattern}->{target}")
                text = new
        return text, applied

    def __len__(self) -> int:
        return len(self.pairs)
