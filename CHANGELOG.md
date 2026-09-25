# Changelog

Notable changes are documented here, starting with the entry below; earlier history is only in
the git log. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 2026-09-25

### Added

- `py whisperflow.py --doctor`: checks Python, the installed packages, `config.yaml`, the
  dictionary/alias files, the microphone, the GPU libraries, whether the Whisper model is already
  on the machine (with its `tokenizer.json`), and the clean-up and translation model, one
  `[OK]`/`[WARN]`/`[FAIL]` line each, with a fix where it can name one. Runs even when
  the packages it reports on are missing, and even without Windows.
- `requirements-gpu.txt`: optional CUDA libraries (cuBLAS, cuDNN) as pip packages, for GPU
  acceleration on a machine without a system-wide CUDA install.
- `config.local.yaml` (git-ignored): personal settings layered over `config.yaml` at startup, so
  a `git pull` never collides with them. `config.local.example.yaml` shows the common overrides.
  Tray icon -> "Settings" creates it from the example and opens it.
- Tray icon -> "Start with Windows": adds or removes a shortcut in the user's own Startup folder,
  no administrator rights needed.
- Single-instance guard: starting the app a second time (`py whisperflow.py` or the Startup
  shortcut) prints a short notice and closes the new one; the running instance is left untouched
  (`start-whisperflow.bat` still force-stops it first, as before).
- A startup diagnosis for the clean-up model tells "server not running" and "model not pulled"
  apart, shown in the console and as a tray note (only after a failed warm-up, never when
  clean-up is switched off).
- The screenshot key can now be a combination, not only a single key (default: AltGr+Shift).
- A portable pytest suite (600+ tests) that runs without Windows, a microphone, a GPU or Ollama,
  plus GitHub Actions CI that runs it on both Ubuntu and Windows on every push.

### Changed

- Screenshot default key: AltGr+Shift instead of the right Shift key alone. Tapping the right
  Shift key alone used to fire on every capital letter for anyone who also types capitals with
  it; the right Shift key is still available (see the Upgrade notes below for the setting).
- `requirements.txt` now includes `uiautomation` and `psutil`. `uiautomation` was missing before,
  which silently disabled automatic pasting in the default hybrid mode on a fresh install.
- `stt.device: auto` now falls back to the CPU when the CUDA libraries fail to load, instead of
  crashing.
- The German interface text is now fully German (no leftover English words), and the tray
  tooltip is translated as well.
- The on-screen badge at the mouse pointer grows with longer texts, up to a limit, then trims the
  rest with "…" instead of cutting it off wordlessly.
- History pruning (`ui.history_keep_days`) now also runs while the app keeps running for weeks,
  not only at startup.
- `state.json` and the pruned history file are now written atomically.
- The dictation key accepts any recognised key name; an unknown name now prints a warning (and
  still falls back to the right Ctrl key, as before).

### Fixed

- Privacy: no request to Hugging Face at every start any more. The Whisper model used to be
  checked against the Hub each time the app loaded it (your IP address, the time and the model
  name went out), even with the model long downloaded. It now loads from the local cache; the Hub
  is only contacted when the model is not there yet (first start, a newly chosen `stt.model`, or
  an interrupted download), with a console line saying so. One exception remains: if the model's
  folder has no `tokenizer.json`, faster-whisper fetches the tokenizer from Hugging Face at every
  start; `--doctor` shows whether that applies.
- `data/app.log` no longer grows without limit while the app keeps running for days or weeks:
  past 2 MB it is now cut back to its newest whole lines (at most 1 MB) during operation too, not
  only at startup.
- Calibration (`--calibrate`): answering `ja`, `y` or `yes` now accepts a suggested alias like `j`
  does, and `nein` or `no` skips it like `n`; typing `y` used to save "y" itself as the alias.
- A closing quote that was part of the dictated text is no longer stripped by the clean-up step
  (only a quote pair wrapping the whole answer is removed now).
- `llm.translate_keep_alive: 0` (unload the translation model at once) is honoured instead of
  being replaced by the clean-up model's own `keep_alive` value.
- A blank or non-text entry in the optional name list no longer stops the app from starting.
- The progress ring at the pointer no longer runs backwards when the time estimate is updated.
- An alias target containing a backslash no longer raises an error.
- Dictation state (the streamed chunks, the background transcriber, the window category) now
  belongs to its own recording. With `ui.discard_pending_on_new_recording: false` or
  `ui.discard_only_if_shorter_than_s` above 0, settings that keep a dictation instead of dropping
  it, pressing the key again immediately after releasing it, while the previous recording was
  still being processed, no longer drops most of that previous recording (by default, a new
  recording still starts over and discards the previous one, unchanged).

### Upgrade notes

For anyone already running an earlier copy of this app:

- `config.yaml` itself changed in this update. If you had edited your own copy of it directly
  (before `config.local.yaml` existed), `git pull` will refuse over the conflict: note your own
  values first, then either `git stash` or `git checkout -- config.yaml` to clear the local edit,
  pull, and re-enter your values in `config.local.yaml` afterwards (see below).
- Install the new packages: `py -m pip install -r requirements.txt` (adds `uiautomation` and
  `psutil`). With an NVIDIA GPU, also run `py -m pip install -r requirements-gpu.txt`.
- The screenshot key changed to AltGr+Shift. To keep the previous right-Shift behaviour, add to
  `config.local.yaml`:
  ```yaml
  snip:
    key: "shift_r"
  ```
- If you registered `start-whisperflow-silent.vbs` in Task Scheduler for autostart, remove that
  task once tray icon -> "Start with Windows" is on; leaving both in place still ends with one
  copy running, but see the README for exactly what happens with each start order, and note that
  the old script also started Ollama, which the new shortcut does not.
- Move personal settings (hotkey, microphone, model choices, vocabulary file paths) into
  `config.local.yaml` (copy the commented examples from `config.local.example.yaml`) so they
  survive `git pull`.
