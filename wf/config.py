"""S3 — Config + Dictionary Loader.

Laedt config.yaml und dictionary.txt aus dem Projekt-Root. Kein Netzwerk.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    p = path or CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(f"config.yaml nicht gefunden: {p}")
    with p.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    cfg["_root"] = str(ROOT)
    return cfg


def load_dictionary(cfg: dict[str, Any]) -> list[str]:
    """Liest dictionary.txt -> Liste von Begriffen (Kommentare/Leerzeilen raus)."""
    rel = cfg.get("dictionary_path", "dictionary.txt")
    p = ROOT / rel
    if not p.exists():
        return []
    terms: list[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line)
    # Dedupe, Reihenfolge erhalten
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def load_employee_names(cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Optionale Namensliste aus einer JSON-Datei (config.yaml: employees_from).
    Format: {"members": [{"name": "Vorname Nachname", "aktiv": true}, ...]}
    -> (vornamen, vollnamen) der aktiven Eintraege. Nicht konfiguriert oder Datei fehlt: leere Listen."""
    rel = cfg.get("employees_from")
    if not rel:
        return [], []
    p = (ROOT / rel).resolve()
    if not p.exists():
        print(f"[config] name list not found: {p} -> continuing without extra names")
        return [], []
    try:
        import json
        data = json.loads(p.read_text(encoding="utf-8"))
        members = [m for m in data.get("members", []) if m.get("aktiv") and m.get("name")]
    except Exception as e:  # noqa: BLE001
        print(f"[config] name list unreadable ({e}) -> continuing without extra names")
        return [], []
    full = [m["name"].strip() for m in members]
    first: list[str] = []
    for n in full:
        f = n.split()[0]
        if f.lower() not in {x.lower() for x in first}:
            first.append(f)
    return first, full


def load_aliases_path(cfg: dict[str, Any]) -> Path:
    return ROOT / cfg.get("aliases_path", "aliases.txt")


TIER_MARKER = "# === NUR-CLEANUP"


def load_dictionary_tiers(cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(whisper_terms, cleanup_only_terms). Whisper hat nur ~224 Tokens Prompt — alles nach der
    Markerzeile `# === NUR-CLEANUP ...` in dictionary.txt kommt nur ins LLM-Woerterbuch
    („exakt so schreiben"), nicht in den Whisper-Prompt. Seit 09.09.2026 (Wortschatz-Erweiterung)."""
    rel = cfg.get("dictionary_path", "dictionary.txt")
    p = ROOT / rel
    if not p.exists():
        return [], []
    whisper: list[str] = []
    llm_only: list[str] = []
    target = whisper
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith(TIER_MARKER):
            target = llm_only
            continue
        if not s or s.startswith("#"):
            continue
        target.append(s)
    seen: set[str] = set()
    w = [t for t in whisper if not (t.lower() in seen or seen.add(t.lower()))]
    l = [t for t in llm_only if not (t.lower() in seen or seen.add(t.lower()))]
    return w, l


def dictionary_prompt_seed(terms: list[str]) -> str:
    """faster-whisper initial_prompt: nennt die Begriffe, damit Whisper sie korrekt schreibt."""
    if not terms:
        return ""
    return "Begriffe: " + ", ".join(terms) + "."
