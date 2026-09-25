"""Welche Bildschirmfotos sind NEU? — der Zubringer fuer „schau dir das mal an".

Auftrag Wenn er sagt „schau dir das mal an", soll die Sitzung im Bilder-Ordner
nachsehen — aber **nur die neuen** Bilder, nicht den ganzen Ordner. Jedes gelesene Bild kostet
Kontext; alte Bilder zu lesen ist verbrannte Energie und Zeit.

Deshalb rechnet dieses Skript die Auswahl deterministisch aus und nennt nur Pfade. Gelesen wird
danach genau das, was hier steht (und hoechstens `--max` Stueck).

Aufrufe
  py tools/neue-bilder.py                     # seit dem letzten Ansehen, sonst die letzten 10 Minuten
  py tools/neue-bilder.py --minuten 30        # feste Rueckschau
  py tools/neue-bilder.py --seit 2026-09-10T13:00:00
  py tools/neue-bilder.py --warten 90         # wartet bis zu 90 s auf ein NEUES Bild
  py tools/neue-bilder.py --max 1             # nur das neueste
  py tools/neue-bilder.py --alle              # ganzer Ordner (bewusst, selten)
  py tools/neue-bilder.py --merken            # Zeitstempel setzen: „bis hier habe ich gesehen"

Ausgabe (Zeile je Bild, aeltestes zuerst):
  BILD<TAB>Pfad<TAB>JJJJ-MM-TTTHH:MM:SS<TAB>vor N s<TAB>BreitexHoehe<TAB>KB
Dazu eine Kopfzeile mit der Anzahl und, falls mehr da waren als `--max`, ein Hinweis.

Exit-Code: 0 = mindestens ein Bild gefunden · 3 = nichts Neues (kein Fehler) · 1 = Aufruffehler.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = ROOT / "data" / "_zuletzt-angesehen.json"


def _config_modul():
    """wf/config.py laden, ohne dass tools/ auf sys.path stehen muss (dieses Skript liegt nicht
    im Projekt-Root, ein normales `import wf.config` faende das Paket sonst nicht)."""
    spec = importlib.util.spec_from_file_location("wf_config_zubringer", ROOT / "wf" / "config.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def ordner(cfg_pfad: Path | None = None) -> Path:
    """Bilder-Ordner aus derselben Mischung wie die App: config.yaml, und daneben, falls
    vorhanden, eine config.local.yaml darueber (wf.config.load_config). Standard data/images.

    K1 (Schlusspruefung B2, 25.09.2026): bisher las dieser Zubringer config.yaml direkt per PyYAML
    und ignorierte config.local.yaml - dort liegen seit Arbeitspaket 7 die eigenen Einstellungen
    (wf/config.py), die App speicherte also woanders, als der Zubringer suchte. Der Docstring hier
    behauptete Gleichlauf mit der App, ohne ihn zu haben.

    cfg_pfad zeigt auf eine eigene config.yaml; die config.local.yaml im selben Ordner gilt dann
    automatisch mit (wie bei load_config(path)). Ohne PyYAML, ohne Datei oder bei kaputter
    config.yaml: wie bisher kein Absturz, Rueckfall auf data/images. Eine kaputte config.local.yaml
    waere fuer die App ein Startabbruch (whisperflow._load_config_or_explain); fuer einen
    Zubringer ist das zu viel Reaktion - eine Zeile auf stderr, dann gilt config.yaml allein."""
    ziel = "data/images"
    try:
        cfg_mod = _config_modul()
    except Exception:  # noqa: BLE001  (z. B. kein PyYAML installiert -> Standard bleibt)
        cfg_mod = None
    if cfg_mod is not None:
        try:
            cfg = cfg_mod.load_config(cfg_pfad)
            ziel = ((cfg.get("snip") or {}).get("folder") or ziel)
        except cfg_mod.ConfigError as e:
            if str(e).startswith(cfg_mod.LOCAL_NAME):
                print(f"WARNING: {e}", file=sys.stderr)
                try:
                    cfg = cfg_mod.load_config(cfg_pfad, local=False)
                    ziel = ((cfg.get("snip") or {}).get("folder") or ziel)
                except Exception:  # noqa: BLE001  (config.yaml dann ebenfalls kaputt)
                    pass
            # config.yaml selbst kaputt: wie bisher still der Standard
        except Exception:  # noqa: BLE001  (z. B. Datei fehlt)
            pass
    d = Path(ziel)
    return d if d.is_absolute() else (ROOT / d)


def marker_lesen() -> float:
    try:
        return float(json.loads(MARKER.read_text(encoding="utf-8"))["ts"])
    except Exception:  # noqa: BLE001
        return 0.0


def marker_setzen(ts: float) -> None:
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(json.dumps({"ts": ts, "zeit": datetime.fromtimestamp(ts).isoformat(timespec="seconds")}),
                      encoding="utf-8")


def bilder_seit(folder: Path, seit: float) -> list[Path]:
    if not folder.exists():
        return []
    treffer = [f for f in folder.glob("*.png") if f.stat().st_mtime > seit]
    return sorted(treffer, key=lambda f: f.stat().st_mtime)


def masse(f: Path) -> str:
    """Bildgroesse ohne das Bild zu laden (PNG-Kopf: Breite/Hoehe stehen in Byte 16..24)."""
    try:
        with f.open("rb") as fh:
            kopf = fh.read(24)
        if len(kopf) >= 24 and kopf[12:16] == b"IHDR":
            b = int.from_bytes(kopf[16:20], "big")
            h = int.from_bytes(kopf[20:24], "big")
            return "%dx%d" % (b, h)
    except OSError:
        pass
    return "?"


def main() -> int:
    ap = argparse.ArgumentParser(description="List new screenshots")
    ap.add_argument("--minuten", type=float, default=None, help="look back this many minutes")
    ap.add_argument("--seit", default=None, help="ISO timestamp, e.g. 2026-09-10T13:00:00")
    ap.add_argument("--max", type=int, default=3, help="name at most this many images (default 3)")
    ap.add_argument("--warten", type=float, default=0, help="wait this many seconds for a new image")
    ap.add_argument("--alle", action="store_true", help="whole folder, no time limit")
    ap.add_argument("--merken", action="store_true", help="set the marker (seen up to here)")
    a = ap.parse_args()

    folder = ordner()
    if a.alle:
        seit = 0.0
        woher = "whole folder"
    elif a.seit:
        try:
            seit = datetime.fromisoformat(a.seit).timestamp()
        except ValueError:
            print("ERROR: --seit needs an ISO timestamp like 2026-09-10T13:00:00")
            return 1
        woher = "since %s" % a.seit
    elif a.minuten is not None:
        seit = time.time() - a.minuten * 60
        woher = "last %g minutes" % a.minuten
    else:
        m = marker_lesen()
        standard = time.time() - 600
        seit = max(m, standard)
        woher = "since the last look" if m > standard else "last 10 minutes"

    treffer = bilder_seit(folder, seit)
    if not treffer and a.warten > 0:
        ziel = time.time() + a.warten
        print("WAITING for a new image (up to %g s) - take the screenshot now ..." % a.warten)
        while time.time() < ziel and not treffer:
            time.sleep(0.5)
            treffer = bilder_seit(folder, seit)

    if not treffer:
        print("NO new images (%s) in %s" % (woher, folder))
        return 3

    zuviel = max(0, len(treffer) - a.max) if a.max > 0 else 0
    zeigen = treffer[-a.max:] if a.max > 0 else treffer
    print("%d new image(s) (%s) in %s" % (len(treffer), woher, folder))
    jetzt = time.time()
    for f in zeigen:
        st = f.stat()
        print("BILD\t%s\t%s\tvor %d s\t%s\t%d KB" % (
            f, datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            int(jetzt - st.st_mtime), masse(f), st.st_size // 1024))
    if zuviel:
        print("NOTE: %d older images in this window not listed (--max %d). "
              "Call again with a higher --max only if you need them." % (zuviel, a.max))
    if a.merken:
        marker_setzen(treffer[-1].stat().st_mtime)
    return 0


if __name__ == "__main__":
    sys.exit(main())
