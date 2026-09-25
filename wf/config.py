"""S3 — Config + Dictionary Loader.

Laedt config.yaml und dictionary.txt aus dem Projekt-Root. Kein Netzwerk.

Eigene Einstellungen (Arbeitspaket 7, 25.09.2026): config.yaml gehoert zum Repository. Wer sie
aendert, bekommt beim naechsten `git pull` Konflikte oder verliert seine Werte. Deshalb wird eine
config.local.yaml neben config.yaml (von git ignoriert, Vorlage: config.local.example.yaml) beim
Laden darueber gelegt, siehe merge().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.yaml"
LOCAL_NAME = "config.local.yaml"
#: Die eigenen Einstellungen zur ausgelieferten config.yaml. Die Tests lenken den Pfad auf eine
#: Datei, die es nicht gibt (tests/conftest.py), damit die persoenliche Datei sie nicht faerbt.
LOCAL_CONFIG_PATH = ROOT / LOCAL_NAME
LOCAL_EXAMPLE_PATH = ROOT / "config.local.example.yaml"


class ConfigError(ValueError):
    """Eine Einstellungsdatei laesst sich nicht verwenden. Die Meldung nennt die Datei und, wo
    YAML sie kennt, die Zeile, dazu die Abhilfe. Sie ist fuer die Konsole gedacht (englisch)."""


def _read_yaml(path: Path, hint: str) -> dict[str, Any]:
    """Eine YAML-Datei -> dict. Leer oder nur Kommentare -> {}. Kaputt -> ConfigError mit
    Dateiname, Zeile und Spalte statt eines Tracebacks aus der Tiefe von PyYAML."""
    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        wo = f", line {mark.line + 1}, column {mark.column + 1}" if mark is not None else ""
        grund = getattr(e, "problem", None) or str(e).replace("\n", " ")
        # Wo das Kaputte ANFING, z. B. ein nicht geschlossenes Anfuehrungszeichen: YAML meldet
        # den Fehler erst am Dateiende, den Anfang nur im Kontext.
        kontext, kmark = getattr(e, "context", None), getattr(e, "context_mark", None)
        if kontext and kmark is not None:
            grund += f" ({kontext} in line {kmark.line + 1})"
        raise ConfigError(f"{path.name}{wo}: {grund} -> {hint}") from e
    except UnicodeDecodeError as e:
        raise ConfigError(f"{path.name}: not UTF-8 text ({e.reason}) -> save it as UTF-8, then {hint}") from e
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name}: expected settings as 'key: value' lines, found a "
                          f"{type(data).__name__} -> {hint}")
    return data


def merge(base: dict[str, Any], local: dict[str, Any], source: str = LOCAL_NAME,
          _prefix: str = "") -> tuple[dict[str, Any], list[str], list[str]]:
    """local rekursiv ueber base legen. Rueckgabe: (Ergebnis, geaenderte Schluessel, Schluessel,
    die base nicht kennt). Schluessel als Pfad mit Punkten ("hotkey.key"), nie mit Werten.

    - Abschnitt (dict) ueber Abschnitt: zusammenfuehren, was local nicht nennt, bleibt.
    - Alles andere (Zahl, Text, Liste, null) ersetzt den Wert aus base.
    - Ausnahme: ein leerer Abschnitt in local (YAML liest "hotkey:" mit nur auskommentierten
      Zeilen darunter als null) aendert nichts. Sonst wuerde der ganze Abschnitt zu None, und
      die App stuerzte beim Start an cfg["hotkey"].get(...) ab.
    - Ein Abschnitt, den local durch einen einzelnen Wert ersetzen will ("snip: false"), ist
      ein Fehler (ConfigError): die App liest darunter einzelne Schluessel und uebersaehe den
      Wert still oder stuerzte ab.
    base und local bleiben unveraendert."""
    out = dict(base)
    geaendert: list[str] = []
    neu: list[str] = []
    for key, value in local.items():
        name = f"{_prefix}{key}"
        if key not in base:
            out[key] = value
            neu.append(name)
            continue
        alt = base[key]
        if isinstance(alt, dict):
            if value is None:
                continue
            if not isinstance(value, dict):
                art = "a list" if isinstance(value, list) else "a single value"
                raise ConfigError(f"{source}: '{name}' is a section in config.yaml (settings indented "
                                  f"below it), here it is {art} -> write it the same way as there")
            out[key], g, n = merge(alt, value, source, name + ".")
            geaendert += g
            neu += n
            continue
        out[key] = value
        geaendert.append(name)
    return out, geaendert, neu


def load_config(path: Path | None = None) -> dict[str, Any]:
    """config.yaml laden und eine config.local.yaml daneben darueberlegen (merge()).
    path = None: die config.yaml des Projekts und LOCAL_CONFIG_PATH. Mit eigenem path gilt die
    config.local.yaml im selben Ordner wie path. Was die lokale Datei setzt, steht danach in
    cfg["_local"] (nur Schluesselnamen, fuer local_summary_lines()). Kaputte Datei: ConfigError."""
    p = path or CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(f"config.yaml nicht gefunden: {p}")
    cfg = _read_yaml(p, "fix the file")
    local_path = LOCAL_CONFIG_PATH if path is None else p.with_name(LOCAL_NAME)
    if local_path.is_file():
        local = _read_yaml(local_path, f"fix the file, or delete it to use {p.name} alone")
        cfg, geaendert, neu = merge(cfg, local, local_path.name)
        cfg["_local"] = {"file": local_path.name, "changed": geaendert, "new": neu}
    cfg["_root"] = str(ROOT)
    return cfg


def local_summary_lines(cfg: dict[str, Any]) -> list[str]:
    """Konsolenzeilen beim Start: welche Schluessel config.local.yaml setzt, nur die Namen (die
    Werte koennen Persoenliches enthalten, z. B. Pfade oder Geraetenamen). Keine lokale Datei ->
    keine Zeile."""
    info = cfg.get("_local")
    if not info:
        return []
    datei = info["file"]
    if not info["changed"] and not info["new"]:
        return [f"[config] {datei} found, but it sets nothing (it is empty or only has comments)"]
    zeilen = []
    if info["changed"]:
        zeilen.append(f"[config] {datei} overrides: {', '.join(info['changed'])}")
    if info["new"]:
        zeilen.append(f"[config] {datei} sets keys that config.yaml does not have (typo?): "
                      f"{', '.join(info['new'])}")
    return zeilen


def ensure_local_config(path: Path | None = None, example: Path | None = None) -> tuple[Path, bool]:
    """Tray -> Einstellungen: (Pfad der config.local.yaml, gerade angelegt?). Fehlt sie, wird sie
    aus config.local.example.yaml angelegt (dort ist alles auskommentiert, sie aendert also
    nichts, bis man etwas einkommentiert). Fehlt auch die Vorlage, eine Kopfzeile. Eine
    vorhandene Datei bleibt unberuehrt, auch wenn sie erst zwischen Pruefen und Schreiben
    entsteht (Modus "x"). OSError geht an den Aufrufer (Meldung im Tray)."""
    p = path or LOCAL_CONFIG_PATH
    if p.exists():
        return p, False
    vorlage = example or LOCAL_EXAMPLE_PATH
    if vorlage.is_file():
        text = vorlage.read_text(encoding="utf-8")
    else:
        text = "# my-local-whisper: your own settings. Every setting is explained in config.yaml.\n"
    try:
        with p.open("x", encoding="utf-8") as fh:
            fh.write(text)
    except FileExistsError:
        return p, False
    return p, True


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
    # Ein Name aus Leerzeichen oder ein Name, der kein Text ist (z. B. 123), brach bis 24.09.2026
    # den App-Start ab (IndexError/AttributeError, diese Zeilen stehen hinter dem try). Jetzt
    # werden solche Eintraege uebersprungen, der Rest der Liste gilt.
    full = [m["name"].strip() for m in members if isinstance(m["name"], str) and m["name"].strip()]
    weg = len(members) - len(full)
    if weg:
        print(f"[config] name list: skipped {weg} active {'entry' if weg == 1 else 'entries'} without a usable name")
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
