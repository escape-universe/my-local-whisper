# Build brief for an agent: local ears, eyes and mouth

> **Ears, eyes and mouth should run locally and fast on your own device** — for data that stays
> yours and an approach that works everywhere, instead of external software that was never adapted
> to you. The point is to raise the speed of input and handling when working with agents: our human
> output — fingers, voice, eyes — has to be as fast as it possibly can.

*Hand this file to your coding agent. It is written for the agent, not for a human reader. The
sentence above is the whole goal; [`IDEA.md`](IDEA.md) unpacks the why. This file is the how, plus
the mistakes we already paid for.*

---

## Your job

Build your user a local input layer: **speech in, screen in, text out**, triggered by keys that work
in every application on their machine. Do not port this repository file by file. Rebuild it for
their operating system, their hardware and their habits — then verify it with tests that fail on the
old behaviour.

Ship it in this order. Each stage is useful on its own, so the user gets value before the whole thing
exists:

1. **Ears** — key held → microphone → transcript.
2. **Mouth** — transcript → clipboard, and into the focused text field when there is one.
3. **Clean-up** — a small local model that removes filler and adds punctuation, with guards.
4. **Eyes** — key pressed → screen frozen → region selected → clipboard + file.
5. **Handoff** — a folder plus a "what is new since last time" lister the agent calls itself.
6. **Vocabulary** — the user's names and terms, in two tiers, with a calibration round.

## Step 0 — decide these with your user before writing code

Do not guess these; a wrong answer here is rework, not a tweak.

| Question | Why it matters |
|---|---|
| Which key for speech, which for screen? | Must be reachable without looking and free in daily typing. Ask what they actually use — one user typed capitals only with the *left* Shift, which made the right one free. |
| Hold-to-talk or press-to-toggle? | Hold suits short sentences, toggle suits long dictation. Offer both; remember the choice. |
| GPU or CPU? | Decides the model size and whether "fast enough" is reachable at all. |
| Which language(s) do they speak, and do they mix them? | Decides model choice and whether you need a language guard. |
| Paste directly, or wait on the clipboard? | Direct pasting is faster and occasionally lands in the wrong window. The middle road: paste only if the same text field still has focus, otherwise wait. |
| Where do files go, and for how long? | Dictation history and screenshots are sensitive. Pick a local path, a retention period, and exclude it from any cloud backup. |

## Step 1–3: speech in, text out

The architecture that survived contact with daily use:

```
key down ──► microphone (stream already open, small pre-roll ring)
                  │
                  ├─ while still speaking: cut at pauses, transcribe chunks
key up   ──► last chunk ──► transcribe ──► vocabulary fixes ──► clean-up model
                                                │
                                                ├─ guards (see below) ──► raw text if a guard trips
                                                ▼
                                   clipboard  (+ paste if the field still has focus)
```

**Keep the models resident.** Loading a speech model per dictation is the difference between 2
seconds and 12. Keep the clean-up model warm too, and unload both on exit.

**Do the work while the human is still talking.** Long dictation must not mean long waiting: cut the
audio at silences, transcribe each piece as it appears, and after the key is released only the tail
remains. Measured: 21 minutes of speech, 5.4 seconds of waiting at the end.

**The clean-up model is an editor, not an assistant.** It has exactly one job: remove filler, add
punctuation, apply spoken self-corrections. It must never answer the text. A dictated question stays
a question — say so in the prompt, and show it in a few-shot example.

## Step 4: the screen

**The one rule that makes this better than the built-in tools: freeze first, select second.**

```
key ──► capture the whole screen NOW (all monitors)  ──► hide your own overlays
    ──► show the frozen image full screen, dimmed outside the selection
    ──► user drags a rectangle (or presses Enter for the whole monitor)
    ──► crop ──► clipboard ──► file
```

Built-in snipping tools open their UI first, which takes focus, which closes any open drop-down menu
— exactly the thing people want to screenshot. Freezing first keeps open menus, tooltips and hover
states in the picture. Test it: open a context menu, freeze, close the menu, freeze again, compare
the two images in that rectangle. If they differ, the menu was captured.

## Step 5: the handoff to the agent

Build a tiny lister, not an integration:

- Input: an optional time window (`--since`, `--minutes`, `--wait`), a cap (`--max`, default 3), and
  a `--remember` flag that stores "seen up to here".
- Output: one line per file — path, timestamp, age, dimensions, size — plus a note when older files
  in the window were skipped.
- Exit codes: `0` found something, `3` nothing new (not an error), `1` bad call.

Then teach the agent one habit: **call the lister, read only what it names, mark the point.** Never
scan the folder, never read the whole history "for context". The script picks; the model does not.

## The mistakes we already paid for

This is the part worth more than the code. Each line is a measured failure, not a precaution.

### Speech and clean-up

| Symptom | Cause | Fix |
|---|---|---|
| Every request pauses ~2 s | `localhost` resolves to IPv6 first on Windows and times out | Use `127.0.0.1` everywhere |
| Model reloads every few minutes despite a keep-alive setting | keep-alive was sent to an OpenAI-compatible endpoint that ignores it | Talk to the runtime's native API, and verify with its "which models are loaded" endpoint |
| The first word is missing | The microphone stream is opened on key-down and takes up to a second | Keep the stream open permanently and keep a ~0.6 s pre-roll ring |
| Rare terms are recognised at the start of the vocabulary list but never at the end | The speech model's prompt has a hard token budget (~224) and silently truncates | Two tiers: a short list in the speech prompt, everything else only for the clean-up model. Print both sizes at startup |
| "seventy-five" became "75k"; a sentence came back half as long | The clean-up model is trained to be helpful, and helpful is wrong here | A deterministic guard after clean-up: every digit in the output must have been spoken, addresses and URLs unchanged, length not below half. On a trip, deliver the raw transcript |
| Spoken English came back as German | The clean-up model translated silently — the speech model was innocent | Pass the detected language into the prompt, use language-pure few-shot examples, and add a guard that rejects a changed language |
| Text from the previous dictation kept reappearing | An "append to the last one" convenience feature | Default to off. Every dictation stands alone unless the user asks otherwise |

### Keyboard, focus, clipboard

| Symptom | Cause | Fix |
|---|---|---|
| The app stops reacting to the key entirely | The low-level keyboard hook did slow work inline; the OS removes hooks that block | Hook only enqueues; a worker thread does the work |
| A key press is swallowed forever after one lost release | Debounce state got stuck "down" | Ask the OS whether the key is physically down; fall back to a timeout |
| Typing capitals triggers the screenshot | The trigger key is a modifier the user needs | Never suppress modifiers, and either pick a free key or require a hold with cancellation on any other key or mouse click |
| A German keyboard loses `@ € | { }` | AltGr was used as the trigger; the OS sends Ctrl+Alt for it | Never use AltGr |
| The selection overlay is visible, dragging works, but Esc and Enter go to the window behind | The window is topmost but does not own the input focus; a background process may not simply take the foreground | Attach briefly to the foreground window's input state, then set foreground / active / focus. **Test for it** — mouse interaction keeps working, so this bug hides |
| "Pasting the image does not work here" in one app but not another | Only one clipboard format was set | Set the plain bitmap format *and* PNG; different applications prefer different ones |
| Pasting text lands in the wrong window | Focus changed between the key release and the end of processing | Remember the window *and* the focused field at release time, and paste only if both still match |
| Nothing is pasted into an elevated/admin window | The OS blocks input from a lower-integrity process | Detect it, tell the user, leave the text on the clipboard — do not run the tool as admin to "fix" this |

### Screen and display

| Symptom | Cause | Fix |
|---|---|---|
| The captured image is blurry or the wrong size | The process is not DPI aware and gets a scaled copy | Set DPI awareness — per thread if a GUI in another thread would be affected |
| The selection window lands on the wrong monitor | With a monitor above or left of the primary one, the virtual desktop origin is negative | Position the window at the virtual origin and translate all coordinates by it |
| Full-screen captures are twice as big as needed | "Whole screen" meant all monitors | Default to the monitor the mouse is on; it halves the file and the tokens when an agent reads it |

### Building and shipping

| Symptom | Cause | Fix |
|---|---|---|
| A missing import crashed a path that only runs live; tests were green | Nothing exercised that path | Add a name scan across all modules (every loaded name must be imported or defined) and a headless test that calls every UI state |
| The published version was broken in ways the local one never showed | Published files were built from a curated copy | Clone your own published repository into a fresh folder and run it there — as a stranger would. This is how we found half the console output still in the wrong language, and a missing helper file |
| A test "passed" but proved nothing | It was never checked against the broken state | Calibrate every new test: break the fix on purpose once, watch the test fail, restore |
| A new test failed randomly under load | GUI timing assumptions | Wait for a condition, not for a fixed number of seconds; skip honestly with a reason rather than reporting a false failure |

## Verification: what "done" means

Not "it worked when I tried it". Make it a deterministic self-test the user can run after any change:

- **Prove the hard parts against reality**, not against mocks: paste text into a real editor and read
  it back through the OS; capture a real open menu and compare pixels; read the clipboard back.
- **Test the shipped configuration, not just the code.** A setting that silently flips back is a bug
  the code tests will not catch.
- **Every new test gets calibrated** against the old, broken state exactly once.
- **Skip honestly.** A test that cannot run right now says so, with the reason. It never silently
  passes.

## Scope discipline — what not to build

- No screenshot editor (arrows, blur, callouts). It is the request that feels natural and the one
  that costs the most for the least. Ship without it; add it only if it is asked for twice.
- No cloud sync of the captured material. The whole point is that it stays local.
- No unattended screen watching. Capture on a key press, by a human, on purpose.
- No per-application integrations. One key everywhere beats a perfect plugin for one app.

## Platform notes

This repository is Windows. The design is not. If you build elsewhere:

- **macOS:** screen capture and synthetic keyboard events need explicit user permissions
  (Screen Recording, Accessibility) — request them up front, because silent denial looks like a bug.
  Global hotkeys go through the event tap API; the clipboard holds multiple representations natively.
- **Linux:** the split matters — X11 lets you do all of this directly, Wayland deliberately does not.
  On Wayland use the portal APIs for screenshots and a compositor-supported hotkey mechanism, and
  accept that "freeze then select" has to be done through the portal's own picker on some desktops.
- Everywhere: keep the same three guarantees — local, instant, works in every window.

---

*Reference implementation: [github.com/escape-universe/my-local-whisper](https://github.com/escape-universe/my-local-whisper).
Built by one person and an agent, in use daily. Take the ideas, leave the code.*
