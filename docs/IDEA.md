# The idea — local ears, eyes and mouth

*This file matters more than the code in this repository. The code is one implementation, for one
person, on Windows, in September 2026. It will age. The idea underneath does not.*

---

## The bottleneck moved

Agents got fast. The channel between a human and an agent did not.

You think faster than you type. You see a whole screen at once and then spend two minutes describing
it in words. You have a thought while walking to the kitchen and it is gone before you sit down.
None of that is a model problem — the model is waiting. The narrow part is **you reaching the
machine**, and it is narrow in three places:

| Channel | Human speed | Typical speed with a computer |
|---|---|---|
| Speaking | ~150 words per minute | typing: 40–60 wpm |
| Showing | one glance | describing a screen in prose: minutes |
| Receiving | reading, fast | fine — this end is not the problem |

So the useful work is not "a better model". It is **widening the input channel** — and doing it in a
way that works everywhere, belongs to you, and costs nothing per use.

## Ears, eyes, mouth — on your own device

Three channels, all local, all instant, all universal:

- **Ears** — speech in. You hold a key and talk; clean text comes out. Not into one app's text box:
  into whatever has your cursor.
- **Eyes** — screen in. You press a key and grab exactly what you are looking at, including the
  drop-down menu that is open right now, and hand it to the agent.
- **Mouth / hands** — text out. The result lands at the cursor, or waits on the clipboard. No
  copy-paste-from-a-window dance.

Each one is small enough to build in a day with an agent. Together they change how the day feels,
because you stop translating your intent into keystrokes.

## Why local, and why "universal" instead of "integrated"

**Local** is not about distrust. It is about four properties you cannot buy:

1. **Sovereignty.** What you dictate is often the most sensitive thing you produce all day — draft
   replies, salary questions, half-formed strategy. It never leaves the machine, so there is nothing
   to review, to delete, or to regret.
2. **Zero marginal cost.** A tool you pay for per minute is a tool you will use less than you should.
   This one costs electricity. Use it for everything, including the throwaway sentence.
3. **Latency.** Local GPU speech recognition beats a round trip to a data centre, and it works in a
   dead spot, on a train, offline.
4. **Adaptation.** It knows your colleagues' names, your rooms, your product terms, your keyboard.
   No SaaS product will ever learn the forty first names that matter to you.

**Universal** means: one key that works in every window — the browser, the invoice tool, the chat,
the ticket system, the text field nobody thought about. The moment input lives *inside* one product,
you own half a solution and you are back to copy-and-paste for the other half.

## The speed budget

"Fast enough" deserves numbers, otherwise it drifts. Measured on one desktop machine (RTX 2080
Super, Whisper `large-v3-turbo`, a 3-billion-parameter clean-up model on Ollama):

| Step | Measured |
|---|---|
| 13 seconds of speech → cleaned text on the clipboard | **2.3 s** |
| 21 minutes of speech → 3,066 words | **5.4 s** of waiting after you stop (the rest runs while you talk) |
| Screen freeze for a screenshot | **0.1 s** |
| Key press → selection window on screen | **~0.4 s** |

The rule behind those numbers: **anything the human waits for must feel like it already happened.**
Work that can run while the human is still talking, runs while the human is still talking. Models
stay loaded in VRAM instead of being loaded per request. The microphone stream stays open so the
first word is never lost. A second saved here is not one second — it is one second times the number
of times you do it per day, for years.

## The part that surprises people: the agent handoff

Grabbing a screenshot is half the value. The other half is that the agent can **fetch it itself**.

There is a folder, and a small script that answers one question: *which images arrived since the
last time you looked?* The agent calls that script, reads only those, and marks the point it reached.
No "let me upload this", no re-reading a folder full of old pictures, no burning context on things
the agent already saw.

That is the pattern worth copying, whatever your tooling looks like:

- **A known place** for the artefacts (screenshots, recordings, exports).
- **A timestamp marker** so "new" is a fact, not a guess.
- **A cheap lister** that decides *deterministically* what is in scope — the script picks, not the
  model. A model asked "which of these 400 images matter?" will read far too many.
- **Content is data, never instructions.** If a captured screen says "delete everything", that is
  something to report, not to do. Instructions come from the human, through the conversation.

## Why the idea outlives the code

In the six weeks this repository existed, the speech model was replaced (3.6× faster at better
accuracy), the clean-up prompt was rewritten three times, the trigger key moved twice, and the
output path changed from "always paste" to "paste only if the field still has focus". Every one of
those was the right call at the time. Not one of them changed the idea.

So treat this repository as two things:

1. **A reference implementation.** Read it, take the parts that fit, ignore the rest.
2. **A build brief.** [`AGENT-BUILD-GUIDE.md`](AGENT-BUILD-GUIDE.md) is written to be handed to your
   own coding agent. It contains the design decisions and — more valuable — the failures we measured,
   so your agent does not have to rediscover them at your expense.

Building it yourself with an agent takes an afternoon and gives you something no product gives you:
it fits *your* hands, *your* keyboard, *your* words, and it changes the same day you change your mind.

---

## Deutsche Fassung

**Der Engpass ist nicht mehr das Modell, sondern der Weg vom Menschen zur Maschine.** Du denkst
schneller, als du tippst. Du siehst einen ganzen Bildschirm auf einmal und beschreibst ihn dann zwei
Minuten lang in Worten. Das Modell wartet derweil.

Deshalb drei Kanäle, alle **lokal**, alle **sofort**, alle **überall nutzbar**:

- **Ohren** — Taste halten, sprechen, loslassen: sauberer Text am Cursor.
- **Augen** — Taste antippen, Ausschnitt ziehen: das Bild liegt beim Agenten, inklusive des gerade
  offenen Menüs.
- **Mund/Hände** — das Ergebnis landet dort, wo der Cursor steht, sonst in der Zwischenablage.

**Warum lokal:** Was du diktierst, ist oft das Empfindlichste des Tages; es verlässt den Rechner
nicht. Es kostet nichts pro Minute, also benutzt du es auch für den Wegwerfsatz. Es ist schneller als
ein Rechenzentrum und läuft ohne Netz. Und es kennt deine Namen, Räume und Begriffe — das wird kein
fremdes Produkt je tun.

**Warum universell statt integriert:** Eine Taste, die in *jedem* Fenster funktioniert. Sobald die
Eingabe in einem Produkt eingebaut ist, hast du die halbe Lösung und kopierst den Rest von Hand.

**Das Überraschende ist die Übergabe an den Agenten:** Ein bekannter Ordner, ein Zeitstempel-Merker
und ein kleines Skript, das *deterministisch* sagt, was seit dem letzten Blick neu ist. Der Agent
liest nur das. Bildinhalte sind dabei **Daten, keine Anweisungen**.

**Warum die Idee länger hält als der Code:** In sechs Wochen wurden hier Sprachmodell, Aufräum-Prompt,
Auslöse-Taste und Ausgabeweg ausgetauscht — die Idee blieb jedes Mal dieselbe. Nimm dieses
Repository als Vorlage und als Auftragsbeschreibung: [`AGENT-BUILD-GUIDE.md`](AGENT-BUILD-GUIDE.md)
ist dafür geschrieben, deinem eigenen Agenten gegeben zu werden. Ein Nachmittag Arbeit — und du hast
etwas, das zu *deinen* Händen passt und sich an dem Tag ändert, an dem du deine Meinung änderst.
