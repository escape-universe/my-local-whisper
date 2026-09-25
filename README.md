# my-local-whisper

**Dictation on Windows that never leaves your machine.** Hold a key, speak, release — the cleaned-up text appears at your cursor or on your clipboard. Speech recognition and text clean-up both run locally on your own GPU.

It dictates, it cleans up, and it translates: **English and German are equally at home**, and Spanish, Italian and Russian come out of the translation mode. Nothing here is an English-only afterthought — it runs Whisper `large-v3-turbo` rather than a small English model, keeps your own vocabulary file, and umlauts stay umlauts, so German comes out as well as English does.

*Deutsche Fassung weiter unten ↓*

> **Ears, eyes and mouth should run locally and fast on your own device** — for data that stays
> yours and an approach that works everywhere, instead of external software that was never adapted
> to you. The point is to raise the speed of input and handling when working with agents: our human
> output — fingers, voice, eyes — has to be as fast as it possibly can.
>
> That is what this repository is really about — the reasoning is in
> **[the idea behind it](docs/IDEA.md), worth reading before the code.** The software here is one
> implementation, for one person, on Windows, in 2026, and it will age; the idea will not. Anyone can
> rebuild it in an afternoon with a coding agent, fitted to their own hands —
> [`docs/AGENT-BUILD-GUIDE.md`](docs/AGENT-BUILD-GUIDE.md) is written to be handed straight to yours,
> including the mistakes we already paid for.

![Dictating into Notepad: a spoken sentence full of filler words appears as clean text](docs/demo.gif)

*Real recording, nothing sped up: hold the key, speak, release — about five seconds later the cleaned-up text is in the editor. [Same demo as a 50-second video with sound](docs/demo.mp4), including English, German and technical terms.*

---

## What it does

- **Hold to talk** (default: right Ctrl), or **toggle mode** for long stretches — press once to start, press again to stop.
- **Recording starts the instant you press.** The microphone stream stays open, and a 0.6 second pre-roll keeps what you said just before the key went down — no more swallowed first word. The badge only turns red once audio really arrives, so what you see is what is being recorded.
- **Up to 60 minutes in one go.** Transcription runs while you are still speaking, cut at pauses. After you stop you wait about 5 seconds, whether you spoke for 10 seconds or 20 minutes.
- **Clean-up, not answers.** A small local language model removes filler words, adds punctuation and applies spoken self-corrections ("make that seventy-five" after "fifty"). It never answers your text — a dictated question stays a question.
- **It stays faithful to what you said.** Clean-up models like to be helpful, and helpful is wrong here: ours once turned "seventy-five" into "75k". A guard checks the result afterwards — every digit must have been spoken, addresses and URLs must survive unchanged, nothing may be dropped wholesale. If a rule trips, you get the raw transcript instead of a polished lie.
- **Screenshots, from the same tool.** Tap **AltGr + Shift** together (AltGr is the right Alt key): the screen freezes, you drag a rectangle, and the cutout is on the clipboard and saved as a PNG (`data/images`, kept 14 days, "Open the images" in the tray). Press **Enter** instead of dragging for the whole monitor. The freeze happens *before* the selection window opens, so **open drop-down menus and tooltips are in the picture** — the thing the Windows Snipping Tool cannot do, because it takes the focus away from the menu and the menu closes. AltGr alone still types `@ € | { }`; only adding Shift on top triggers the shot. The previous default, the right Shift key alone, used to fire on every capital letter for anyone who types capitals with it; see Configuration below for how to go back to it, or to a hold instead of a tap.
- **Appending.** Off by default (`ui.append_within_s: 0`): every dictation stands on its own. Set it to a number of seconds and a dictation that follows a clipboard-only one within that window is appended to it, so one Ctrl+V brings both. Never after an automatic paste.
- **Translation mode.** Tray menu → "Translate into" (English, German, Spanish, Italian, Russian). Dictate in your language, get the other one out. Off after every start, so normal dictation is never a surprise.
- **Your own vocabulary, in two tiers.** Terms in `dictionary.txt`, misheard spellings in `aliases.txt`. With `--calibrate` you read your terms out loud once and confirm what Whisper makes of them. Whisper's prompt only holds about 224 tokens and silently drops the tail of a longer list, so everything below the `# === NUR-CLEANUP` marker line goes to the clean-up model only. The app prints the size of each tier at startup.
- **Pasting that stays out of the way.** If a text field has focus, the text is pasted directly; otherwise it waits on the clipboard until you press Ctrl+V wherever you want it.
- **A badge at the mouse pointer** showing recording time, progress and the result; it grows with the text, up to a limit, and trims anything longer with "…" instead of cutting it off wordlessly. Click-through, never steals focus. **The moment you release, it shows a grey stop square and "recording off", plus a short beep** - so you know the microphone is off without looking at anything (`ui.beep_on_stop: false` turns that beep off; a different, lower beep follows only if something then goes wrong).
- **It can tell you why it felt slow.** Started without a console, the app writes `data/app.log` (a timestamp per line; whenever it passes 2 MB, at startup or while the app runs, it is cut back to its newest whole lines, at most 1 MB). Every dictation leaves a `[timing]` line there: key->stop, stop->badge, waiting, transcription, clean-up, total. Guessing about latency is then unnecessary - the numbers are in the file.
- **It speaks your language.** The interface — tray menu, notifications, the badge — ships in English, German, Russian, Spanish and Italian. On the first start it follows your Windows display language, so it is already in your language when you install it, and you can switch it any time under *Language* in the tray. Adding another one is a single block in [`wf/i18n.py`](wf/i18n.py); the self-test then checks that no line is missing.
- **Your last dictations are one click away.** Every delivered text is also written to a local log; the tray menu opens it, so a text you lost from the clipboard is never gone. The log is kept for 14 days by default and never leaves the machine.

## What it does not do

- **Windows only.** Pasting and window detection use Windows APIs (UI Automation, SendInput).
- **It is not faster than the cloud services.** The gain is privacy, accuracy in the language you actually speak, and zero running cost — not speed. On an RTX 2080 Super, a 13-second dictation takes about 2.3 seconds.
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
py whisperflow.py --doctor
py whisperflow.py
```

`requirements.txt` installs everything the app needs on Windows, including `uiautomation` (paste detection) and `psutil`. With an NVIDIA GPU, also run `py -m pip install -r requirements-gpu.txt`: it adds the CUDA libraries (cuBLAS, cuDNN) as pip packages. Without it, `stt.device: auto` still works if CUDA/cuDNN are already installed system-wide; otherwise it falls back to the CPU on its own.

Run `py whisperflow.py --doctor` before the first real start: it checks Python, the installed packages, `config.yaml`, your dictionary/alias files, the microphone, the GPU libraries, whether the Whisper model is already on this machine (with its `tokenizer.json`), and the clean-up and translation model, one `[OK]`/`[WARN]`/`[FAIL]` line each, with a fix where it can name one. A `[FAIL]` means that part will not work yet. A `[WARN]` is informational and never stops the app from starting, for example no GPU found (runs on the CPU instead), the translation model not pulled yet (translation mode will not work until you pull it), or the clean-up model unreachable (you get the raw transcript until Ollama is running).

On the first real run Whisper downloads its model (once, about 1.5 GB). After that a tray icon sits in the notification area: blue means ready.

**Start it automatically:** right-click the tray icon and turn on **"Start with Windows"**. That adds a shortcut to your own Startup folder, no administrator rights needed, so pasting into ordinary applications keeps working (admin rights would block that). Turning it off removes the shortcut again. The shortcut only starts my-local-whisper itself, not Ollama; whether Ollama also starts with Windows is set by its own installer, check the Startup tab of the Windows Task Manager if you are not sure.

If you used to register `start-whisperflow-silent.vbs` as a logon task in Task Scheduler, remove that task once "Start with Windows" is on; otherwise both start at every logon. If the old script comes second, it force-stops the running copy and starts its own. If it comes first, the newer, direct start simply notices the app is already running and closes itself (see the table below). Either way exactly one copy keeps running, but the old script also used to start Ollama itself, which the new shortcut does not (see above); keep that in mind if you drop the old script and Ollama does not start on its own.

## Using it

| Action | What happens |
|---|---|
| Hold right Ctrl, speak, release | Text is transcribed, cleaned up and delivered |
| Double beep | Text was pasted directly |
| Single beep | Text is on the clipboard, Ctrl+V pastes it |
| A longer, lower beep | Something failed, details are in the tray note (not the same as the short beep right on release, see above) |
| Release and immediately press again | Start over — the previous recording is dropped, however long it was (`ui.discard_only_if_shorter_than_s` brings back the old length limit) |
| Tap AltGr + Shift | Screenshot: the screen freezes, drag a rectangle (Enter = whole monitor, Esc cancels) |
| Right-click the tray icon | Active (untick to pause), toggle mode, translation target, interface language, copy last text, open the log, open the images, Settings, Start with Windows, quit |
| Start `py whisperflow.py` or the Startup shortcut while it is already running | A short message says so; the new start closes itself, the running one is left untouched |
| Double-click `start-whisperflow.bat` while it is already running | It stops the running copy first, then starts its own |

## Configuration

Everything is documented in [`config.yaml`](config.yaml): key, microphone, model, language-model endpoint, paste method, on-screen badge. Restart after changing it.

Your own changes belong in `config.local.yaml`, not in `config.yaml` itself: tray icon → **Settings** creates it (from [`config.local.example.yaml`](config.local.example.yaml)) and opens it in your editor. It is layered over `config.yaml` at startup, so a later `git pull` never collides with your settings, and the console names which keys it overrides (never the values, they can be personal). Restart the app after saving (tray → Quit, then start it again). Point `dictionary_path`/`aliases_path` there at your own copies (e.g. `dictionary.local.txt`) to keep your vocabulary out of `git pull` too.

For example, to go back to the previous screenshot key (the right Shift key alone) instead of AltGr+Shift, add this to `config.local.yaml`, indented the same way `config.local.example.yaml` shows it:

```yaml
snip:
  key: "shift_r"
```

On a layout where AltGr+Shift+letter already types a character of its own (Polish, for example), use `hold` instead of `tap`:

```yaml
snip:
  mode: "hold"
```

The combination then has to be held for `hold_ms` (450 ms by default) and fires when you let go of it; another key or a mouse click in between cancels it, the same as with a single key.

Throughout this README a dotted name such as `ui.beep_on_stop` or `snip.key` is shorthand for a nested path, not something to type as one flat line: in `config.local.yaml` it belongs indented under its section, as in the two examples above. A flat line such as `snip.key: "shift_r"` changes nothing (`config.yaml` has no key by that literal name, so the console only warns "sets keys that config.yaml does not have").

The language model does not have to run on the same machine — any OpenAI-compatible endpoint on your own network works, for example a `llama.cpp` server on a stronger box (`llm.base_url`).

One thing worth knowing: use **`127.0.0.1`, not `localhost`**. On Windows, `localhost` tries IPv6 first and runs into a timeout, which costs about 2 seconds per clean-up.

## Checking that it works

```
py whisperflow.py --doctor        # check the setup: packages, microphone, GPU, Ollama
py whisperflow.py --selftest      # deterministic tests, no microphone needed
py whisperflow.py --list-devices  # list microphones
py manual_inject_test.py          # test pasting live (opens Notepad)
py whisperflow.py --calibrate     # tune the vocabulary with your own voice
py whisperflow.py --clean-text "um so the budget more like seventy five"   # clean-up stage only
```

Or double-click `testen-konsole.bat`: that runs the app with a visible console, so every dictation shows you the raw transcript, the cleaned text, the timings and whether a faithfulness rule tripped. `kalibrieren.bat` does the same for calibration.

`--doctor` and `--selftest` are not the same thing: `--doctor` checks whether *your* setup is ready (packages, microphone, GPU, Ollama) and prints one line per check; `--selftest` proves the app's own logic against real Windows APIs (clipboard, pasting into a real program, a screenshot) and needs Windows to run at all.

For development, without Windows: `pip install -r requirements-dev.txt` and `python -m pytest -q` run the full logic test suite (config, clean-up, aliases, hotkey debounce, i18n and more) anywhere, including a plain Linux shell or CI; `ruff check --select E9,F63,F7,F82 .` catches syntax errors and undefined names the same way. In Windows PowerShell that comma-separated list needs quotes (`--select "E9,F63,F7,F82"`), otherwise PowerShell splits it into several arguments; Git Bash or the CI runner take it as written. `--selftest` itself still needs a real Windows machine.

## Privacy

Audio stays in memory and is discarded after processing — nothing is recorded to disk. The delivered text is appended to `data/history.log` for 14 days so you can get it back; old entries are removed at startup and, while the app keeps running, with the first dictation of each day (not continuously, and not while it sits idle). Set `ui.history_file: null` to switch that off. Started without a console, every dictation also leaves a short preview (up to 120 characters of the cleaned text; the whole text if it could not be placed on the clipboard) in `data/app.log`, for diagnosing timing. Whenever that file grows past 2 MB (checked at startup and after every line while the app keeps running), it is cut back to its newest whole lines, at most 1 MB; `ui.history_file: null` does not affect it. Outbound connections: the Whisper model is downloaded from Hugging Face once, on the first start, and again only when you switch `stt.model` to a model that is not downloaded yet (or to finish an interrupted download); after that it loads from the local cache. One exception: if the model's folder has no `tokenizer.json`, faster-whisper fetches the tokenizer from Hugging Face at every start; the "speech model" line of `py whisperflow.py --doctor` shows whether that applies on your machine. Apart from that, the only connection is the call to the language model at the address you set in `config.yaml`. With `127.0.0.1` there and `--doctor` reporting that the speech model loads without internet, no byte leaves the machine.

## Language of the source

The interface comes in five languages (see above); the configuration file and this README are English. The app's own console lines are English, except some reasons they quote (why a text was not pasted, why a recording was dropped, why the faithfulness guard tripped) and messages shown in the interface language; those can still be German. Also still German: **comments and docstrings inside the code**, the self-test's own labels (`selftest.py`), the calibration questions (`--calibrate`; yes and no work in both languages there: `j`/`ja`/`y`/`yes`, `n`/`nein`/`no`), `manual_inject_test.py`, and the `.bat` helper scripts. This started as a personal tool; it is on the list, and does not change how the program behaves.

## Licence

MIT — see [LICENSE](LICENSE). Free to use, change and pass on, without warranty.

Built at [Escape Universe](https://escapeuniverse.de), Nienburg / Hannover / Leipzig.

---

# my-local-whisper (deutsch)

> **Ohren, Augen und Mund sollen lokal und schnell auf dem eigenen Gerät laufen** — für Daten, die
> bei dir bleiben, und einen Ansatz, der überall funktioniert, statt fremder Software, die nie auf
> dich zugeschnitten war. Der Punkt ist, Eingabe und Verarbeitung im Arbeiten mit Agenten schneller
> zu machen: Finger, Stimme und Augen sind unsere menschliche Ausgabeseite, und die muss so schnell
> sein wie irgend möglich.
>
> Darum geht es hier eigentlich — die Begründung steht in
> **[der Idee dahinter](docs/IDEA.md), lesenswert vor dem Code.** Die Software ist eine Umsetzung von
> vielen und altert; die Idee nicht. Nachbauen dauert mit einem Coding-Agenten einen Nachmittag —
> [`docs/AGENT-BUILD-GUIDE.md`](docs/AGENT-BUILD-GUIDE.md) ist dafür geschrieben, genau dem gegeben
> zu werden, samt der Fehler, die wir schon bezahlt haben.

**Diktieren unter Windows, ohne dass etwas den Rechner verlässt.** Taste halten, sprechen, loslassen — der bereinigte Text landet am Cursor oder in der Zwischenablage. Spracherkennung und Textbereinigung laufen lokal auf deiner Grafikkarte.

Es diktiert, räumt auf und übersetzt: **Deutsch und Englisch sind gleichermaßen zu Hause**, dazu Spanisch, Italienisch und Russisch im Übersetzungsmodus. Deutsch ist dabei kein Anhängsel: Whisper `large-v3-turbo` statt eines englischen Kleinmodells, eigenes Wörterbuch für Namen und Fachbegriffe, Umlaute bleiben Umlaute.

![Diktat in Notepad: ein gesprochener Satz mit Füllwörtern erscheint als sauberer Text](docs/demo-de.gif)

*Echte Aufnahme, nichts beschleunigt: Taste halten, sprechen, loslassen — rund fünf Sekunden später steht der bereinigte Text im Editor. [Dieselbe Demo als 50-Sekunden-Video mit Ton](docs/demo.mp4).*

### Was es kann

- **Bildschirmfotos aus demselben Werkzeug.** AltGr und Umschalt zusammen antippen: der Bildschirm friert ein, du ziehst einen Rahmen, das Bild liegt in der Zwischenablage und als PNG im Ordner (`data/images`, 14 Tage). Enter statt Rahmen = ganzer Monitor. Weil VOR der Auswahl eingefroren wird, sind **aufgeklappte Menüs mit auf dem Bild** — genau das, was das Windows-Snipping-Tool nicht kann. AltGr allein tippt weiterhin `@ € | { }`; erst Umschalt obendrauf löst das Bildschirmfoto aus. Der bisherige Standard, die rechte Umschalt-Taste allein, löste bei jeder Großschreibung mit ihr aus; wie du das zurückstellst oder die Taste stattdessen hältst statt sie zu tippen, steht unten bei Einstellungen.

- **Halten und sprechen** (Standard: rechte Strg-Taste) oder **Umschalt-Modus** für lange Reden: einmal drücken an, nochmal drücken aus.
- **Bis 60 Minuten am Stück.** Die Transkription läuft schon während du sprichst, geschnitten an Sprechpausen. Nach dem Stoppen wartest du rund 5 Sekunden, egal ob du 10 Sekunden oder 20 Minuten geredet hast.
- **Aufnahme startet sofort beim Drücken.** Das Mikrofon bleibt bereit, 0,6 Sekunden Vorlauf fangen ab, was knapp vor dem Tastendruck gesagt wurde. Kein verschlucktes erstes Wort mehr. Das rote Feld erscheint erst, wenn wirklich Ton ankommt.
- **Aufräumen statt Antworten.** Ein kleines lokales Sprachmodell entfernt Füllwörter, setzt Satzzeichen und wendet gesprochene Selbstkorrekturen an. Es beantwortet deinen Text nicht: eine diktierte Frage bleibt eine Frage.
- **Treue zum Gesagten.** Aufräum-Modelle wollen gefallen, und genau das ist hier falsch: unseres machte aus „fünfundsiebzig" einmal „75k". Ein Wächter prüft das Ergebnis danach. Jede Ziffer muss gesagt worden sein, Adressen bleiben unverändert, nichts darf einfach wegfallen. Greift eine Regel, bekommst du den Rohtext statt einer geglätteten Behauptung.
- **Anhängen.** Standardmäßig aus (`ui.append_within_s: 0`), jedes Diktat steht für sich. Mit einer Sekundenzahl dort wird ein Diktat angehängt, wenn es innerhalb dieser Zeit auf eines folgt, das nur in der Zwischenablage liegt. Ein Strg+V bringt dann beides. Nie nach automatischem Einfügen.
- **Übersetzen.** Tray-Menü → „Übersetzen in" (Englisch, Deutsch, Spanisch, Italienisch, Russisch). Nach jedem Start wieder aus.
- **Eigenes Vokabular in zwei Stufen.** Begriffe in `dictionary.txt`, Hörfehler in `aliases.txt`, Feinschliff mit `--calibrate`. Whispers Prompt fasst nur rund 224 Tokens und lässt den Rest einer längeren Liste stillschweigend weg, deshalb geht alles unterhalb der Markerzeile `# === NUR-CLEANUP` nur noch ans Aufräum-Modell.
- **Einfügen, das nicht stört.** Textfeld im Fokus: wird direkt eingefügt. Sonst liegt der Text in der Zwischenablage und du drückst Strg+V, wo du willst.
- **Ein Anzeigefeld am Mauszeiger** zeigt Aufnahmezeit, Fortschritt und Ergebnis; es wächst mit dem Text, bis zu einer Grenze, und kürzt Längeres mit „…" statt es wortlos abzuschneiden. Klickdurchlässig, nimmt nie den Fokus. **Im Moment des Loslassens zeigt es ein graues Stopp-Quadrat und „Aufnahme aus", dazu einen kurzen Ton** - so weißt du ohne Hinsehen, dass das Mikrofon aus ist (`ui.beep_on_stop: false` schaltet diesen Ton ab; ein anderer, tieferer Ton kommt erst, wenn danach etwas schiefgeht).
- **Sagt dir, warum es sich langsam anfühlte.** Ohne Konsole gestartet, schreibt die App `data/app.log` (eine Zeitangabe je Zeile; übersteigt sie 2 MB, beim Start oder während die App läuft, bleiben nur ihre jüngsten ganzen Zeilen, höchstens 1 MB). Jedes Diktat hinterlässt dort eine `[timing]`-Zeile: Taste->Stopp, Stopp->Anzeige, Warten, Transkription, Aufräumen, gesamt. Raten über die Geschwindigkeit erübrigt sich damit, die Zahlen stehen in der Datei.
- **Spricht deine Sprache.** Die Oberfläche — Tray-Menü, Meldungen, Anzeigefeld — gibt es auf Englisch, Deutsch, Russisch, Spanisch und Italienisch. Beim ersten Start richtet sie sich nach der Windows-Anzeigesprache, ist also sofort richtig, und im Tray unter *Sprache* jederzeit umstellbar. Eine weitere Sprache ist ein Block in [`wf/i18n.py`](wf/i18n.py), der Selbsttest prüft dann auf Vollständigkeit.
- **Die letzten Diktate ein Klick entfernt.** Jeder gelieferte Text landet zusätzlich in einer lokalen Log-Datei, das Tray-Menü öffnet sie. Was aus der Zwischenablage verschwunden ist, ist damit nicht weg. Standard: 14 Tage, verlässt den Rechner nie.

### Was es nicht kann

Nur Windows. Nicht schneller als die Cloud-Dienste (der Gewinn ist Datenschutz, Genauigkeit in deiner Sprache und null laufende Kosten). Ohne NVIDIA-Grafikkarte deutlich langsamer. Kein Support-Versprechen.

### Voraussetzungen

Windows 10/11, Python 3.11+, [Ollama](https://ollama.com), empfohlen eine NVIDIA-Karte mit mindestens 6 GB Speicher.

### Installation

```
git clone https://github.com/escape-universe/my-local-whisper.git
cd my-local-whisper
py -m pip install -r requirements.txt
ollama pull qwen2.5:3b-instruct
py whisperflow.py --doctor
py whisperflow.py
```

`requirements.txt` installiert alles, was unter Windows gebraucht wird, auch `uiautomation` (erkennt das fokussierte Textfeld) und `psutil`. Mit einer NVIDIA-Karte zusätzlich `py -m pip install -r requirements-gpu.txt`: das bringt die CUDA-Bibliotheken (cuBLAS, cuDNN) als Pip-Pakete mit. Ohne diese Datei läuft `stt.device: auto` trotzdem, wenn CUDA/cuDNN schon systemweit installiert sind; sonst weicht es von selbst auf die CPU aus.

`py whisperflow.py --doctor` vor dem ersten echten Start prüft Python, die installierten Pakete, `config.yaml`, die Wörterbuch-Dateien, das Mikrofon, die GPU-Bibliotheken, ob das Whisper-Modell schon auf dem Rechner liegt (samt `tokenizer.json`), sowie das Aufräum- und das Übersetzungsmodell, je eine Zeile `[OK]`/`[WARN]`/`[FAIL]`, mit einer Abhilfe, wo sich eine nennen lässt. `[FAIL]` heißt, dieser Teil funktioniert noch nicht. `[WARN]` ist nur ein Hinweis und hält die App nie vom Start ab, zum Beispiel keine Grafikkarte gefunden (läuft dann auf der CPU), das Übersetzungsmodell noch nicht mit `ollama pull` geholt (Übersetzen geht erst danach), oder das Aufräum-Modell nicht erreichbar (du bekommst den Rohtext, bis Ollama läuft).

Beim ersten echten Start lädt Whisper einmalig rund 1,5 GB. Danach liegt unten rechts ein Tray-Icon, blau heißt bereit.

**Automatisch starten:** Tray-Symbol rechtsklicken und **„Mit Windows starten"** anhaken. Das legt eine Verknüpfung im eigenen Autostart-Ordner an, ohne Administratorrechte (die würden das Einfügen in normale Programme blockieren). Ausschalten entfernt die Verknüpfung wieder. Die Verknüpfung startet nur my-local-whisper selbst, nicht Ollama; ob Ollama ebenfalls mit Windows startet, legt dessen eigener Installer fest, im Zweifel im Task-Manager unter Autostart nachsehen.

Wer bisher `start-whisperflow-silent.vbs` als Anmelde-Aufgabe in der Aufgabenplanung eingetragen hatte, sollte diese Aufgabe entfernen, sobald „Mit Windows starten" an ist; sonst starten beide bei jeder Anmeldung. Kommt das alte Skript als zweites dran, beendet es die laufende Kopie gewaltsam und startet seine eigene. Kommt es zuerst, meldet sich der direkte Start danach nur noch als „läuft bereits" und beendet sich (siehe Tabelle unten). So oder so läuft am Ende genau eine Kopie, aber das alte Skript startete bisher auch Ollama mit, was die neue Verknüpfung nicht tut (siehe oben); wer das alte Skript entfernt, sollte das im Blick behalten, falls Ollama nicht von selbst startet.

### Bedienung

| Aktion | Was passiert |
|---|---|
| Rechte Strg-Taste halten, sprechen, loslassen | Text wird transkribiert, bereinigt und zugestellt |
| Doppelter Ton | Text wurde direkt eingefügt |
| Einzelner Ton | Text liegt in der Zwischenablage, Strg+V fügt ein |
| Ein längerer, tieferer Ton | Etwas ist fehlgeschlagen, Details stehen in der Tray-Meldung (nicht derselbe Ton wie der kurze beim Loslassen, siehe oben) |
| Loslassen und sofort erneut drücken | Neu anfangen: die vorige Aufnahme wird verworfen, egal wie lang sie war (`ui.discard_only_if_shorter_than_s` bringt die alte Längengrenze zurück) |
| AltGr + Umschalt antippen | Bildschirmfoto: der Bildschirm friert ein, Rahmen ziehen (Enter = ganzer Monitor, Esc bricht ab) |
| Tray-Symbol rechtsklicken | Aktiv (Haken raus = Pause), Umschalt-Modus, Übersetzungsziel, Oberflächensprache, letzten Text kopieren, Verlauf öffnen, Bilder öffnen, Einstellungen, Mit Windows starten, beenden |
| `py whisperflow.py` oder die Autostart-Verknüpfung ein zweites Mal starten | Eine kurze Meldung sagt das; der neue Start beendet sich, der laufende bleibt unberührt |
| `start-whisperflow.bat` doppelklicken, während die App schon läuft | Beendet erst die laufende Kopie, startet dann seine eigene |

### Einstellungen

Alles kommentiert in [`config.yaml`](config.yaml) (auf Englisch).

Eigene Änderungen gehören in `config.local.yaml`, nicht in `config.yaml` selbst: Tray-Symbol → **Einstellungen** legt sie an (aus [`config.local.example.yaml`](config.local.example.yaml)) und öffnet sie im Editor. Sie liegt beim Start über `config.yaml`, ein späteres `git pull` kollidiert also nie mit den eigenen Werten, und die Konsole nennt, welche Schlüssel sie überschreibt (nie die Werte, die können persönlich sein). Nach dem Speichern die App neu starten (Tray → Beenden, dann wieder starten). Eigenes Vokabular über `dictionary_path`/`aliases_path` dort auf eigene Kopien zeigen lassen (z. B. `dictionary.local.txt`), dann bleibt auch das vom `git pull` unberührt.

Zum Beispiel, um wieder die alte Bildschirmfoto-Taste zu bekommen (die rechte Umschalt-Taste allein) statt AltGr+Umschalt, das hier in `config.local.yaml` eintragen, eingerückt genau wie in `config.local.example.yaml`:

```yaml
snip:
  key: "shift_r"
```

Tippt dein Tastaturlayout mit AltGr+Umschalt+Buchstabe schon ein eigenes Zeichen (zum Beispiel Polnisch), `hold` statt `tap` verwenden:

```yaml
snip:
  mode: "hold"
```

Die Kombination muss dann `hold_ms` lang gehalten werden (Standard 450 ms) und löst beim Loslassen aus; eine andere Taste oder ein Mausklick dazwischen bricht ab, genau wie bei einer einzelnen Taste.

Ein Punktname wie `ui.beep_on_stop` oder `snip.key` steht in dieser README für einen verschachtelten Pfad, nicht für eine flache Zeile: in `config.local.yaml` gehört er eingerückt unter seinen Abschnitt, wie in den beiden Beispielen oben. Eine flache Zeile wie `snip.key: "shift_r"` ändert nichts (`config.yaml` kennt keinen Schlüssel mit genau diesem Namen, die Konsole warnt dann nur „sets keys that config.yaml does not have").

Das Sprachmodell muss nicht auf demselben Rechner laufen: jeder OpenAI-kompatible Endpunkt im eigenen Netzwerk geht, zum Beispiel ein `llama.cpp`-Server auf einer stärkeren Maschine (`llm.base_url`).

Wichtig: als Adresse für das Sprachmodell **`127.0.0.1` statt `localhost`** eintragen, sonst kostet ein IPv6-Timeout rund 2 Sekunden pro Diktat.

### Funktioniert es?

```
py whisperflow.py --doctor        # Einrichtung prüfen: Pakete, Mikrofon, GPU, Ollama
py whisperflow.py --selftest      # deterministische Tests, kein Mikrofon nötig
py whisperflow.py --list-devices  # Mikrofone auflisten
py manual_inject_test.py          # Einfügen live testen (öffnet Notepad)
py whisperflow.py --calibrate     # Vokabular mit der eigenen Stimme abstimmen
py whisperflow.py --clean-text "ähm also das budget eher fünfundsiebzig"   # nur die Aufräum-Stufe
```

Oder **`testen-konsole.bat`** doppelklicken: startet das Programm mit sichtbarer Konsole und zeigt zu jedem Diktat Rohtext, bereinigten Text, Zeiten und ob ein Treue-Wächter angesprungen ist. **`kalibrieren.bat`** macht dasselbe für die Kalibrierung mit der eigenen Stimme.

`--doctor` und `--selftest` sind zweierlei: `--doctor` prüft, ob die eigene Einrichtung bereit ist (Pakete, Mikrofon, GPU, Ollama) und druckt je Prüfpunkt eine Zeile; `--selftest` beweist, dass die Logik der App gegen echte Windows-APIs stimmt (Zwischenablage, Einfügen in ein echtes Programm, ein Bildschirmfoto), und braucht dafür Windows.

Für die Entwicklung, ohne Windows: `pip install -r requirements-dev.txt` und `python -m pytest -q` lassen die Logik-Tests überall laufen, auch in einer reinen Linux-Shell oder in CI; `ruff check --select E9,F63,F7,F82 .` findet Syntaxfehler und nicht definierte Namen auf demselben Weg. In der Windows-PowerShell braucht diese Kommaliste Anführungszeichen (`--select "E9,F63,F7,F82"`), sonst zerlegt PowerShell sie in mehrere Argumente; Git Bash oder der CI-Runner nehmen sie so, wie sie dasteht. `--selftest` selbst braucht weiterhin einen echten Windows-Rechner.

### Datenschutz

Audio bleibt im Arbeitsspeicher und wird danach verworfen, es wird nichts aufgezeichnet. Der gelieferte Text steht 14 Tage lokal in `data/history.log`; alte Einträge fallen beim Start weg und, solange die App läuft, mit dem ersten Diktat jedes Tages (nicht laufend, und nicht, während sie nur untätig weiterläuft). `ui.history_file: null` schaltet das ab. Ohne Konsole gestartet, landet außerdem von jedem Diktat eine kurze Vorschau (bis 120 Zeichen des bereinigten Texts; der ganze Text, wenn er nicht in die Zwischenablage gelegt werden konnte) in `data/app.log`, zur Fehlersuche bei der Geschwindigkeit. Wächst diese Datei über 2 MB (geprüft beim Start und, solange die App läuft, nach jeder Zeile), bleiben nur ihre jüngsten ganzen Zeilen, höchstens 1 MB; `ui.history_file: null` hat darauf keinen Einfluss. Ausgehende Verbindungen: Das Whisper-Modell wird einmal von Hugging Face heruntergeladen, beim ersten Start, und danach nur, wenn du `stt.model` auf ein Modell umstellst, das noch nicht heruntergeladen ist (oder um einen abgebrochenen Download zu beenden); danach kommt es aus dem lokalen Cache. Eine Ausnahme: Liegt im Ordner des Modells keine `tokenizer.json`, holt faster-whisper den Tokenizer bei jedem Start von Hugging Face; ob das auf deinem Rechner zutrifft, zeigt `py whisperflow.py --doctor` in der Zeile „speech model …“. Abgesehen davon gibt es nur den Aufruf des Sprachmodells unter der Adresse aus `config.yaml`. Steht dort `127.0.0.1` und meldet `--doctor`, dass das Whisper-Modell ohne Internet lädt, verlässt kein Byte den Rechner.

### Sprache im Quelltext

Die Oberfläche gibt es in fünf Sprachen (siehe oben), Konfiguration und diese Datei sind englisch. Die eigenen Konsolenzeilen der App sind englisch, außer bei manchen Begründungen, die sie zitieren (warum ein Text nicht eingefügt wurde, warum eine Aufnahme verworfen wurde, warum der Treue-Wächter angesprungen ist) und bei Meldungen in der eingestellten Oberflächensprache; die können weiterhin deutsch sein. Ebenfalls noch deutsch: **die Kommentare und Docstrings im Code**, die eigenen Beschriftungen des Selbsttests (`selftest.py`), die Rückfragen der Kalibrierung (`--calibrate`; Ja und Nein gehen dort in beiden Sprachen: `j`/`ja`/`y`/`yes`, `n`/`nein`/`no`), `manual_inject_test.py` und die `.bat`-Hilfsskripte. Das Werkzeug ist als persönliches Projekt entstanden; das steht auf der Liste und ändert nichts am Verhalten.

### Lizenz

MIT, siehe [LICENSE](LICENSE). Entstanden bei [Escape Universe](https://escapeuniverse.de) in Nienburg, Hannover und Leipzig.
