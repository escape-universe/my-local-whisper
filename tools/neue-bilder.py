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
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = ROOT / "data" / "_zuletzt-angesehen.json"


def ordner(cfg_pfad: Path | None = None) -> Path:
    """Bilder-Ordner aus config.yaml lesen (Standard data/bilder)."""
    p = cfg_pfad or (ROOT / "config.yaml")
    ziel = "data/bilder"
    try:
        import yaml
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        ziel = ((cfg.get("snip") or {}).get("folder") or ziel)
    except Exception:  # noqa: BLE001  (ohne yaml/Datei bleibt der Standard)
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
    ap = argparse.ArgumentParser(description="Neue Bildschirmfotos auflisten")
    ap.add_argument("--minuten", type=float, default=None, help="Rueckschau in Minuten")
    ap.add_argument("--seit", default=None, help="ISO-Zeitpunkt, z.B. 2026-09-10T13:00:00")
    ap.add_argument("--max", type=int, default=3, help="hoechstens so viele Bilder nennen (Standard 3)")
    ap.add_argument("--warten", type=float, default=0, help="so viele Sekunden auf ein neues Bild warten")
    ap.add_argument("--alle", action="store_true", help="ganzer Ordner, ohne Zeitgrenze")
    ap.add_argument("--merken", action="store_true", help="Zeitstempel setzen (bis hier gesehen)")
    a = ap.parse_args()

    folder = ordner()
    if a.alle:
        seit = 0.0
        woher = "ganzer Ordner"
    elif a.seit:
        try:
            seit = datetime.fromisoformat(a.seit).timestamp()
        except ValueError:
            print("FEHLER: --seit braucht einen ISO-Zeitpunkt wie 2026-09-10T13:00:00")
            return 1
        woher = "seit %s" % a.seit
    elif a.minuten is not None:
        seit = time.time() - a.minuten * 60
        woher = "letzte %g Minuten" % a.minuten
    else:
        m = marker_lesen()
        standard = time.time() - 600
        seit = max(m, standard)
        woher = "seit dem letzten Ansehen" if m > standard else "letzte 10 Minuten"

    treffer = bilder_seit(folder, seit)
    if not treffer and a.warten > 0:
        ziel = time.time() + a.warten
        print("WARTE auf ein neues Bild (bis zu %g s) — jetzt den Ausschnitt machen ..." % a.warten)
        while time.time() < ziel and not treffer:
            time.sleep(0.5)
            treffer = bilder_seit(folder, seit)

    if not treffer:
        print("KEINE neuen Bilder (%s) in %s" % (woher, folder))
        return 3

    zuviel = max(0, len(treffer) - a.max) if a.max > 0 else 0
    zeigen = treffer[-a.max:] if a.max > 0 else treffer
    print("%d neue(s) Bild(er) (%s) in %s" % (len(treffer), woher, folder))
    jetzt = time.time()
    for f in zeigen:
        st = f.stat()
        print("BILD\t%s\t%s\tvor %d s\t%s\t%d KB" % (
            f, datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            int(jetzt - st.st_mtime), masse(f), st.st_size // 1024))
    if zuviel:
        print("HINWEIS: %d aeltere Bilder im Zeitraum nicht genannt (--max %d). "
              "Nur bei Bedarf mit hoeherem --max erneut aufrufen." % (zuviel, a.max))
    if a.merken:
        marker_setzen(treffer[-1].stat().st_mtime)
    return 0


if __name__ == "__main__":
    sys.exit(main())
