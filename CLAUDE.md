# CLAUDE.md

**my-local-whisper**: Diktat und Bildschirmfotos unter Windows, komplett lokal. Taste halten,
sprechen, loslassen: faster-whisper transkribiert, ein lokales Sprachmodell (Ollama) räumt auf,
der Text landet am Cursor oder in der Zwischenablage.

## Prüfen

```
python3 -m pip install -r requirements-dev.txt   # nur leichte Pakete, kein Windows, keine GPU
ruff check --select E9,F63,F7,F82 .              # Namens-Scan: Syntaxfehler, nicht definierte Namen
python3 -m pytest -q                             # Logik-Tests, laufen überall (CI: Ubuntu + Windows)
```

- `tests/conftest.py` ersetzt pynput, sounddevice, pywin32, pystray und uiautomation durch
  Attrappen, wenn sie fehlen. Tests reden nie mit dem Netz, auch nicht mit Ollama: HTTP-Aufrufe
  per monkeypatch ersetzen (Beispiel: `tests/test_cleanup.py`).
- Die Windows-Vollprüfung ist `py whisperflow.py --selftest` (Zwischenablage, Einfügen in echte
  Programme, Bildschirmfoto). Sie läuft nur am Windows-Rechner, nicht in der Cloud.
- Tastatur-Hooks, Mikrofon, GPU und Zwischenablage laufen hier nicht live: die Logik mit Attrappen
  testen und ausdrücklich als „nicht live geprüft“ melden.

## Konventionen im Code

- Kommentare und Docstrings deutsch. Entscheidungen und Messungen mit Datum und Grund, z. B.
  `# Gemessen 05.09.2026: 2,9 s -> 0,8 s pro Cleanup.`
- Konsolen-Ausgaben (`print`) englisch: sie liest, wer einen Fehler sucht, nicht der Nutzer.
- Alles, was der Nutzer sieht (Tray-Menü, Meldungen, Anzeigefeld), kommt aus `wf/i18n.py`, in
  allen fünf Sprachen (de, en, ru, es, it) mit denselben Platzhaltern.
- Jede Einstellung wird in `config.yaml` dokumentiert (Kommentar direkt daneben).
- Neue Tests einmal am alten Stand rot sehen, dann grün. Auf Bedingungen warten statt auf feste
  `sleep`s.

## Arbeitsweise

Code-Änderungen laufen über den Skill `worker-pruefer` (`.claude/skills/worker-pruefer/SKILL.md`):
ein Worker setzt um, ein Prüfer mit einem anderen Modell gibt frei, niemand nimmt die eigene
Arbeit ab.
