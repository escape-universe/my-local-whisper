# my-local-whisper

**Dictation on Windows that never leaves your machine.** Hold a key, speak, release — the cleaned-up text appears at your cursor or on your clipboard. Speech recognition and text clean-up both run locally on your own GPU.

Built with **German dictation** as the first-class case (Whisper `large-v3-turbo` instead of a small English-only model, your own vocabulary file, umlauts stay umlauts) — it works just as well for English.

*Deutsche Fassung weiter unten ↓*

---

## What it does

- **Hold to talk** (default: right Ctrl), or **toggle mode** for long stretches — press once to start, press again to stop.
- **Up to 60 minutes in one go.** Transcription runs while you are still speaking, cut at pauses. After you stop you wait about 5 seconds, whether you spoke for 10 seconds or 20 minutes.
- **Clean-up, not answers.** A small local language model removes filler words, adds punctuation and applies spoken self-corrections ("make that seventy-five" after "fifty"). It never answers your text — a dictated question stays a question.
- **Your own vocabulary.** Terms in `dictionary.txt`, misheard spellings in `aliases.txt`. With `--calibrate` you read your terms out loud once and confirm what Whisper makes of them.
- **Pasting that stays out of the way.** If a text field has focus, the text is pasted directly; otherwise it waits on the clipboard until you press Ctrl+V wherever you want it.
- **A badge at the mouse pointer** showing recording time, progress and the result. Click-through, never steals focus.

## What it does not do

- **Windows only.** Pasting and window detection use Windows APIs (UI Automation, SendInput).
- **It is not faster than the cloud services.** The gain is privacy, German quality and zero running cost — not speed. On an RTX 2080 Super, a 13-second dictation takes about 2.3 seconds.
- **Without an NVIDIA GPU** it falls back to the CPU and gets noticeably slower. A smaller model (`stt.model: "small"`) helps and costs accuracy.
- **No support promise.** This was built for one person's own use and is shared because it may be useful to others. Issues and pull requests are welcome; answers may take a while.

## Requirements

- Windows 10 or 11
- Python 3.11 or newer
- [Ollama](https://ollama.com) with a small model for the clean-up: `ollama pull qwen2.5:3b-instruct`
- Recommended: an NVIDIA GPU with at least 6 GB of memory (`large-v3-turbo` uses about 1.6 GB, the language model about 2.1 GB)

## Install

```
git clone https://github.com/escape-universe/my-local-whisper.git
cd my-local-whisper
py -m pip install -r requirements.txt
ollama pull qwen2.5:3b-instruct
py whisperflow.py
```

On the first run Whisper downloads its model (once, about 1.5 GB). After that a tray icon sits in the notification area: blue means ready.

**Start it automatically:** register `start-whisperflow-silent.vbs` as a logon task in Task Scheduler — **without** administrator rights, otherwise Windows blocks pasting into ordinary applications.

## Using it

| Action | What happens |
|---|---|
| Hold right Ctrl, speak, release | Text is transcribed, cleaned up and delivered |
| Double beep | Text was pasted directly |
| Single beep | Text is on the clipboard, Ctrl+V pastes it |
| Low beep | Something failed, details are in the tray note |
| Release and immediately press again | Start over (short recordings are dropped, long ones are still delivered) |
| Right-click the tray icon | Toggle mode, copy last text, quit |

## Configuration

Everything is documented in [`config.yaml`](config.yaml): key, microphone, model, language-model endpoint, paste method, on-screen badge. Restart after changing it.

The language model does not have to run on the same machine — any OpenAI-compatible endpoint on your own network works, for example a `llama.cpp` server on a stronger box (`llm.base_url`).

One thing worth knowing: use **`127.0.0.1`, not `localhost`**. On Windows, `localhost` tries IPv6 first and runs into a timeout, which costs about 2 seconds per clean-up.

## Checking that it works

```
py whisperflow.py --selftest      # deterministic tests, no microphone needed
py whisperflow.py --list-devices  # list microphones
py manual_inject_test.py          # test pasting live (opens Notepad)
py whisperflow.py --calibrate     # tune the vocabulary with your own voice
```

## Privacy

Audio stays in memory and is discarded after processing — nothing is recorded to disk. The delivered text is appended to `data/history.log` for 14 days so you can get it back; set `ui.history_file: null` to switch that off. There are exactly two outbound connections: the one-time model download on first run, and the call to the language model at the address you set in `config.yaml`. With `127.0.0.1` there, no byte leaves the machine.

## Language of the source

The interface, the configuration file and this README are English. **Comments and docstrings inside the code are still German**, as are the labels of the self-test — this started as a personal tool. That is on the list; it does not affect how the program behaves.

## Licence

MIT — see [LICENSE](LICENSE). Free to use, change and pass on, without warranty.

Built at [Escape Universe](https://escapeuniverse.de), Nienburg / Hannover / Leipzig.

---

# my-local-whisper (deutsch)

**Diktieren unter Windows, ohne dass etwas den Rechner verlässt.** Taste halten, sprechen, loslassen — der bereinigte Text landet am Cursor oder in der Zwischenablage. Spracherkennung und Textbereinigung laufen lokal auf deiner Grafikkarte.

Gebaut für **deutsche Diktate**: Whisper `large-v3-turbo` statt eines englischen Kleinmodells, eigenes Wörterbuch für Namen und Fachbegriffe, Umlaute bleiben Umlaute. Für Englisch funktioniert es genauso.

### Was es kann

- **Halten und sprechen** (Standard: rechte Strg-Taste) oder **Umschalt-Modus** für lange Reden: einmal drücken an, nochmal drücken aus.
- **Bis 60 Minuten am Stück.** Die Transkription läuft schon während du sprichst, geschnitten an Sprechpausen. Nach dem Stoppen wartest du rund 5 Sekunden, egal ob du 10 Sekunden oder 20 Minuten geredet hast.
- **Aufräumen statt Antworten.** Ein kleines lokales Sprachmodell entfernt Füllwörter, setzt Satzzeichen und wendet gesprochene Selbstkorrekturen an. Es beantwortet deinen Text nicht: eine diktierte Frage bleibt eine Frage.
- **Eigenes Vokabular.** Begriffe in `dictionary.txt`, Hörfehler in `aliases.txt`, Feinschliff mit `--calibrate`.
- **Einfügen, das nicht stört.** Textfeld im Fokus: wird direkt eingefügt. Sonst liegt der Text in der Zwischenablage und du drückst Strg+V, wo du willst.

### Was es nicht kann

Nur Windows. Nicht schneller als die Cloud-Dienste (der Gewinn ist Datenschutz, deutsche Qualität und null laufende Kosten). Ohne NVIDIA-Grafikkarte deutlich langsamer. Kein Support-Versprechen.

### Installation

```
git clone https://github.com/escape-universe/my-local-whisper.git
cd my-local-whisper
py -m pip install -r requirements.txt
ollama pull qwen2.5:3b-instruct
py whisperflow.py
```

Voraussetzungen: Windows 10/11, Python 3.11+, [Ollama](https://ollama.com), empfohlen eine NVIDIA-Karte mit mindestens 6 GB Speicher. Beim ersten Start lädt Whisper einmalig rund 1,5 GB. Danach liegt unten rechts ein Tray-Icon, blau heißt bereit.

**Automatisch starten:** `start-whisperflow-silent.vbs` in der Aufgabenplanung als Anmelde-Aufgabe eintragen, **ohne** Administratorrechte — sonst blockiert Windows das Einfügen in normale Programme.

### Einstellungen

Alles kommentiert in [`config.yaml`](config.yaml) (auf Englisch). Wichtig: als Adresse für das Sprachmodell **`127.0.0.1` statt `localhost`** eintragen, sonst kostet ein IPv6-Timeout rund 2 Sekunden pro Diktat.

### Datenschutz

Audio bleibt im Arbeitsspeicher und wird danach verworfen, es wird nichts aufgezeichnet. Der gelieferte Text steht 14 Tage lokal in `data/history.log` (abschaltbar mit `ui.history_file: null`). Ausgehende Verbindungen gibt es zwei: der einmalige Modell-Download und der Aufruf des Sprachmodells unter der Adresse aus `config.yaml`. Steht dort `127.0.0.1`, verlässt kein Byte den Rechner.

### Sprache im Quelltext

Oberfläche, Konfiguration und diese Datei sind englisch. **Die Kommentare im Code sind noch deutsch**, ebenso die Beschriftungen der Selbsttests — das Werkzeug ist als persönliches Projekt entstanden. Steht auf der Liste, ändert am Verhalten nichts.

### Lizenz

MIT, siehe [LICENSE](LICENSE). Entstanden bei [Escape Universe](https://escapeuniverse.de) in Nienburg, Hannover und Leipzig.
