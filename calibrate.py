"""Kalibrierung mit der eigenen Stimme: Begriffe vorlesen -> sehen, was Whisper schreibt -> Alias bestaetigen.

Ablauf (Konsole):
  py whisperflow.py --calibrate
  1. Das Programm zeigt eine Runde mit ~6 Begriffen (Mitarbeiter-Vornamen, Raeume, Systeme).
  2. Rechte Strg halten, die Begriffe der Reihe nach vorlesen (gern in einem Satz), loslassen.
  3. Es zeigt das ROHE Whisper-Ergebnis (ohne LLM) und markiert je Begriff: TREFFER / FEHLT.
     Fuer jeden fehlenden Begriff schlaegt es das aehnlichste gehoerte Wort als Alias vor.
  4. Du antwortest je Vorschlag: j (uebernehmen) / n (nicht) / eigene Schreibweise eintippen.
     Bestaetigte Aliase landen sofort in aliases.txt (ab dem naechsten App-Start aktiv).
  5. Enter = naechste Runde, q = Ende. Protokoll: calibration/kalibrierung-JJJJ-MM-TT.md

Kein Modell-Training (das braeuchte Stunden GPU-Zeit und viele Stunden Audio); der Hebel ist
Whisper-Prompt + deterministische Alias-Regeln, das ist reproduzierbar und sofort wirksam.
"""
from __future__ import annotations

import difflib
import re
import sys
import threading
import time
from datetime import date
from pathlib import Path

import numpy as np

from wf import aliases as aliases_mod
from wf import audio as audio_mod
from wf import config as config_mod
from wf import stt as stt_mod
from wf.hotkey import HoldToTalk

ROOT = Path(__file__).resolve().parent
_WORD_RX = re.compile(r"[\wäöüÄÖÜß'\-\.]+")


def _norm(s: str) -> str:
    return s.lower().replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")


def _present(term: str, text: str) -> bool:
    return _norm(term) in _norm(text)


def _closest(term: str, text: str) -> str | None:
    """Aehnlichstes Wort (oder Zwei-Wort-Folge) im gehoerten Text."""
    words = _WORD_RX.findall(text)
    cands = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
    cands = [c.strip(".,;:!?") for c in cands]
    m = difflib.get_close_matches(_norm(term), [_norm(c) for c in cands], n=1, cutoff=0.55)
    if not m:
        return None
    for c in cands:
        if _norm(c) == m[0]:
            return c
    return None


def _append_alias(path: Path, target: str, variant: str) -> bool:
    """Alias-Zeile ergaenzen. Verwirft Unsinn: leer, gleich dem Ziel, mehr als 3 Woerter, Kommas/Gleichheits-
    zeichen (z.B. wenn ein fremder Text ins Eingabefeld getippt wurde, Vorfall Kalibrierung 05.09.2026)."""
    variant = variant.strip().strip(".,;:!?").strip()
    if (not variant or variant.lower() == target.lower() or len(variant.split()) > 3
            or "," in variant or "=" in variant):
        print(f"     (discarded, not a useful alias: {variant!r})")
        return False
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for i, line in enumerate(lines):
        if line.strip().lower().startswith(target.lower() + " ="):
            existing = [v.strip() for v in line.split("=", 1)[1].split(",") if v.strip()]
            if variant.lower() in {e.lower() for e in existing}:
                return True
            lines[i] = f"{target} = " + ", ".join(existing + [variant])
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return True
    lines.append(f"{target} = {variant}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


def section_terms(cfg: dict, name: str) -> list[str]:
    """Begriffe aus EINEM Abschnitt von dictionary.txt. Abschnitte sind die Kommentarzeilen
    `# === NAME ===`; `name` matcht als Teilstring, Gross/Klein egal (z.B. "englisch").
    Leere Liste, wenn kein Abschnitt passt."""
    pfad = ROOT / cfg.get("dictionary_path", "dictionary.txt")
    if not pfad.exists():
        return []
    treffer: list[str] = []
    drin = False
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        z = zeile.strip()
        if z.startswith("#"):
            if "===" in z:
                drin = name.strip().lower() in z.lower()
            continue
        if drin and z:
            treffer.append(z)
    return treffer


def run_calibration(cfg: dict, nur: str = "") -> int:
    base = config_mod.load_dictionary(cfg)
    first, _full = config_mod.load_employee_names(cfg)
    terms = [t for t in first if t not in base] + base
    if nur:
        # Nur einen Abschnitt ueben (z.B. die englischen Begriffe) — 6 Runden statt 30.
        gewaehlt = section_terms(cfg, nur)
        if not gewaehlt:
            print(f"[calibrate] Kein Abschnitt in dictionary.txt passt zu {nur!r}. "
                  f"Abschnitte sind die Zeilen '# === NAME ==='.")
            return 2
        terms = gewaehlt
        print(f"[calibrate] Nur Abschnitt {nur!r}: {len(terms)} Begriffe")
    alias_path = config_mod.load_aliases_path(cfg)
    fixer = aliases_mod.AliasFixer(aliases_mod.load_aliases(alias_path))
    seed = config_mod.dictionary_prompt_seed(base + [n for n in first if n not in base])
    tr = stt_mod.Transcriber(cfg, initial_prompt=seed)
    print("[calibrate] loading the speech model ...")
    tr.warmup()
    rec = audio_mod.Recorder(samplerate=16000, channels=1,
                             device=cfg.get("audio", {}).get("input_device"), max_seconds=60)
    key = cfg.get("hotkey", {}).get("key", "ctrl_r")
    done = threading.Event()
    got: dict = {}

    def on_press():
        rec.start(); print("   [recording ... release the key to evaluate]", flush=True)

    def on_release():
        got["arr"] = rec.stop(); done.set()

    hk = HoldToTalk(key, on_press, on_release)
    hk.start()
    log = ROOT / "calibration" / f"kalibrierung-{date.today().isoformat()}.md"
    log.parent.mkdir(exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"\n## Lauf {time.strftime('%H:%M')} — Modell {tr.model_size}\n\n")
    per_round = 6
    rounds = [terms[i:i + per_round] for i in range(0, len(terms), per_round)]
    print(f"\n=== Calibration: {len(terms)} terms in {len(rounds)} rounds. Hold '{key}' and read the "
          f"terms out loud (a sentence is fine). Enter = next, q = quit ===\n")
    hits = misses = added = 0
    for ri, batch in enumerate(rounds, 1):
        print(f"--- round {ri}/{len(rounds)}: " + "  |  ".join(batch))
        done.clear(); got.clear()
        while not done.wait(0.2):
            pass
        arr: np.ndarray = got.get("arr", np.zeros(0, dtype=np.float32))
        res = tr.transcribe(arr)
        raw = res["text"]
        fixed, applied = fixer.fix(raw)
        print(f"   Whisper: {raw!r}")
        if applied:
            print(f"   after aliases: {fixed!r}")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"- Runde {ri}: {', '.join(batch)}\n  - gehoert: `{raw}`\n")
        for term in batch:
            if _present(term, fixed):
                hits += 1
                print(f"   ✔ {term}")
                continue
            misses += 1
            cand = _closest(term, raw)
            if cand and _norm(cand) != _norm(term):
                ans = input(f"   ✘ {term} fehlt. Gehoert: {cand!r}. Alias '{term} = {cand}' uebernehmen? [j/n/eigene]: ").strip()
            else:
                ans = input(f"   ✘ {term} fehlt, kein aehnliches Wort gefunden. Gehoerte Variante eintippen (leer = ueberspringen): ").strip()
                cand = None
            variant = None
            if ans.lower() == "j" and cand:
                variant = cand
            elif ans.lower() in ("", "n"):
                variant = None
            else:
                variant = ans
            if variant and _append_alias(alias_path, term, variant):
                fixer = aliases_mod.AliasFixer(aliases_mod.load_aliases(alias_path))
                added += 1
                print(f"     -> aliases.txt: {term} = {variant}")
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(f"  - Alias: {term} = {variant}\n")
            else:
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(f"  - FEHLT ohne Alias: {term}\n")
        nxt = input("   [Enter = naechste Runde, w = Runde wiederholen, q = Ende] ").strip().lower()
        if nxt == "q":
            break
        if nxt == "w":
            rounds.insert(ri, batch)
    hk.stop()
    summary = f"hits {hits}, missed {misses}, new aliases {added}. Log: {log}"
    print("\n=== " + summary + " ===")
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"\n**Ergebnis:** {summary}\n")
    print("New aliases take effect the next time the tray app starts (shortcut / start-whisperflow.bat).")
    return 0
