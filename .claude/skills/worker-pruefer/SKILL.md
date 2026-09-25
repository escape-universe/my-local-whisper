---
name: worker-pruefer
description: Code-Änderungen mit zwei verschiedenen Modellen im Vier-Augen-Prinzip, gebaut für Cloud-Sitzungen (ohne Astra, ohne lokale Werkzeuge). Ein Worker setzt um, ein Prüfer mit dem jeweils anderen Modell gibt frei, die Rollen wechseln pro Arbeitspaket, und die Hauptsitzung nimmt nie selbst ab. Nutze diesen Skill für jede Code-Änderung in diesem Repository, die mehr als eine Kleinigkeit ist (Features, Fehlerbehebungen, Refactorings, „verbessere die App“), und immer, wenn der Nutzer „Worker und Prüfer“, „Vier-Augen“, „gegenseitig prüfen“ oder „nicht selbst abnehmen“ sagt. Nicht für reine Fragen, Erklärungen oder einen einzelnen Tippfehler.
---

# Worker & Prüfer

**Grundsatz: Niemand nimmt seine eigene Arbeit ab.** Wer Code schreibt, gibt ihn nicht frei.
Freigeben darf nur ein Prüfer, der mit einem *anderen* Modell läuft als der Worker. Die
Hauptsitzung (du, der Orchestrator) plant und koordiniert. Sie gibt nie selbst frei, und sie
überstimmt kein Prüfer-Urteil.

## Rollen

| Rolle | Wer | Darf | Darf nicht |
|---|---|---|---|
| Orchestrator | die Hauptsitzung | planen, Pakete schneiden, Agents starten, Urteile weitergeben, **nach Freigabe** committen und pushen | freigeben, ein Urteil umdeuten oder überstimmen, „sieht gut aus“ selbst entscheiden |
| Worker | Agent `worker` (`.claude/agents/worker.md`) | Code und Tests ändern, Tests laufen lassen | committen, pushen, sich selbst freigeben |
| Prüfer | Agent `pruefer` (`.claude/agents/pruefer.md`) | lesen, Tests und Lint laufen lassen, in einer Kopie außerhalb des Repos experimentieren | Dateien im Repository ändern, gefundene Fehler selbst beheben |

## Modelle und Rotation

Die zwei Modelle sind Werte für den `model`-Parameter des Agent-Tools:

- **Modell A = `opus`**
- **Modell B = `sonnet`**

Rotation, damit sich die beiden abwechseln und keins immer nur baut oder immer nur abnimmt:

| Paket | Worker | Prüfer |
|---|---|---|
| 1, 3, 5, … | A | B |
| 2, 4, 6, … | B | A |

Regeln:

1. **Bei jedem Agent-Aufruf `model` ausdrücklich setzen.** Ohne `model` erbt der Agent das
   Modell der Hauptsitzung, und dann können Worker und Prüfer dasselbe Modell sein.
2. Innerhalb eines Pakets bleiben die Rollen fest: Nachbesserungen macht derselbe Worker,
   die Nachprüfung derselbe Prüfer (beide mit `SendMessage` fortsetzen, dann kennen sie den
   Verlauf). Fehlt `SendMessage`: einen frischen Agenten mit demselben Modell starten und ihm
   den bisherigen Bericht bzw. das bisherige Urteil sowie die Blocker wörtlich mitgeben. Rollen
   und Rotation bleiben dabei unverändert.
3. Ändert der Orchestrator ausnahmsweise selbst Code, zählt das als Worker-Arbeit mit dem
   Modell der Hauptsitzung. Der Prüfer muss dann das andere Modell sein. In Cloud-Sitzungen
   verrät `get_session` (claude-code-remote) das Modell der Hauptsitzung.
4. `haiku` ist nie Prüfer. Ein anderes Paar nur, wenn der Nutzer es ausdrücklich will.
   Worker und Prüfer sind nie dasselbe Modell.

## Ablauf

### 0. Vorbereitung
- Test- und Lint-Befehle aus `CLAUDE.md` holen (sonst README). Einmal laufen lassen: Ist der
  Ausgangszustand grün? Wenn nicht, das zuerst dem Nutzer sagen, bevor gebaut wird.
- Basis-Commit merken: `git rev-parse HEAD`. Alle Prüfungen vergleichen gegen diesen Stand.

### 1. Plan
Die Aufgabe in **Arbeitspakete** schneiden. Ein Paket ergibt einen prüfbaren Commit. Pro Paket
festhalten:
- Ziel (ein Satz)
- Abnahmekriterien (prüfbar formuliert, z. B. „Test X scheitert am alten Stand und besteht am neuen“)
- betroffene Dateien (Startpunkt, nicht abschließend)
- Nicht-Ziele (was ausdrücklich NICHT angefasst wird)

Pakete, die dieselben Dateien ändern, laufen nacheinander. Unabhängige Pakete dürfen parallel
laufen, dann aber jeweils mit `isolation: "worktree"`, damit sie sich nicht gegenseitig die Tests
kaputt machen.

### 2. Worker
Agent-Tool: `subagent_type: "worker"`, `model` laut Rotation. Vorlage:

```
Arbeitspaket <n>: <Titel>
Ziel: <ein Satz>
Abnahmekriterien:
- ...
Betroffene Dateien (Startpunkt): ...
Nicht-Ziele: ...
Basis-Commit: <sha>. Nicht committen, nicht pushen.
Tests/Lint: <Befehle aus CLAUDE.md>
Ein anderes Modell prüft deine Arbeit unabhängig. Es sieht nur den Diff und deinen Bericht.
```

### 3. Prüfer
Agent-Tool: `subagent_type: "pruefer"`, das **andere** Modell. Vorlage:

```
Prüfe Arbeitspaket <n>: <Titel>.
Ziel und Abnahmekriterien: <wie beim Worker, wörtlich>
Nicht-Ziele: <wörtlich>
Basis-Commit: <sha>. Änderungen: `git status --short`, `git diff <sha>`, neue Dateien ganz lesen.
Tests/Lint: <Befehle>
Bericht des Workers (Behauptungen, ungeprüft):
<Bericht wörtlich>
```

Gib dem Prüfer die Abnahmekriterien **wörtlich**, nicht deine Zusammenfassung davon, sonst prüft
er deine Deutung statt der Aufgabe.

**Kontrolle nach jeder Prüfung:** Den Stand vor dem Prüfer-Aufruf merken (`git status --short`,
`git diff --stat`). Danach vergleichen: Hat sich etwas geändert, hat der Prüfer gegen seine Rolle
verstoßen. Dann gilt das Urteil nicht. Die Änderung wird dem Nutzer gemeldet und die Prüfung mit
einem frischen Prüfer wiederholt.

### Ersatzweg: wenn `worker` oder `pruefer` „not found“ meldet
Claude Code lädt die Rollen aus `.claude/agents/` nur **beim Start einer Sitzung**. Wurde der
Ordner erst in dieser Sitzung angelegt, geändert oder das Repository nachträglich geklont, meldet
das Agent-Tool „Agent type not found“. Dann gilt:
- `subagent_type: "general-purpose"` nehmen, `model` wie gehabt laut Rotation.
- Den Inhalt der Rollendatei (`.claude/agents/worker.md` bzw. `pruefer.md`, ohne den Kopf
  zwischen den `---`-Zeilen) wörtlich an den Anfang des Prompts stellen, danach den Auftrag.
- Der Prüfer hat auf diesem Weg technisch auch Schreibrechte. Die Regel „nichts ändern“ gilt
  trotzdem, und die Kontrolle oben wird hier besonders wichtig.

### 4. Urteil
- **FREIGEGEBEN**: Der Orchestrator committet genau diesen Stand. Vorher zeigt
  `git log <basis>..HEAD` nur die eigenen Commits des Orchestrators. Hat ein Worker doch selbst
  committet, ist das ein Rollenverstoß: Das wird dem Nutzer gemeldet, und der Commit wird nicht
  einfach übernommen. Die Commit-Nachricht sagt, was und warum, und endet mit
  `Geprüft: Prüfer hat freigegeben (Runde <r>).` Danach kommt das nächste Paket.
- **Modellnamen:** Sie gehören nicht in Commit-Nachrichten, nicht in den Code der Anwendung und
  nicht in deren Doku (README, Kommentare). Ausgenommen sind die Werkzeug-Dateien unter
  `.claude/` (dieser Skill und die beiden Rollen), weil sie die Rotation festlegen müssen, und
  Zuordnungszeilen, die die Umgebung oder der Nutzer für jeden Commit vorschreibt (z. B.
  `Co-Authored-By: … <Modellname>`). Die bleiben, wie vorgeschrieben; die Regel gilt für den
  beschreibenden Text der Commit-Nachricht.
- **NICHT FREIGEGEBEN**: Die Blocker gehen **unverändert** an denselben Worker (`SendMessage`;
  ist es nicht verfügbar, gilt der Ersatzweg aus Regel 2 der Rotation). Danach prüft derselbe
  Prüfer erneut (`SendMessage`, dieselbe Ausnahme): die alten Blocker und alles, was sich
  seitdem geändert hat.
- **Höchstens 3 Nachbesserungsrunden** pro Paket. Danach wird gestoppt und der Nutzer gefragt,
  als Multiple-Choice mit Empfehlung: weiter nachbessern / so übernehmen und den Blocker als
  bekannt markieren / Paket verwerfen.

### 5. Widerspruch
Hält der Worker einen Blocker für falsch, begründet er das mit einem Beleg (Test, Befehl, Zitat
aus Code oder Doku). Darüber entscheidet der Prüfer, nicht der Orchestrator. Bleibt es strittig,
wird der Nutzer gefragt.

### 6. Schlussprüfung
Wenn alle Pakete freigegeben sind, prüfen **zwei frische Prüfer parallel** den Gesamt-Diff
(`git diff <basis>..HEAD`): einer mit Modell A, einer mit Modell B. Ihr Auftrag sind die
Wechselwirkungen zwischen den Paketen, Doku gegen Code und die Frage, ob der Gesamtstand hält,
was die Aufgabe verlangt. **Beide müssen freigeben.**

Findet einer der beiden einen Blocker:
1. Ein Worker mit dem Modell, das den betroffenen Code *nicht* gebaut hat, behebt ihn. Dieses
   Modell heißt hier X.
2. **Die Nachprüfung macht der Schluss-Prüfer mit dem anderen Modell (nicht X).** Nur seine
   Freigabe zählt für diese Korrektur. Vorrang hat immer: Wer korrigiert hat, prüft die
   Korrektur nicht.
3. Hatte der meldende Prüfer selbst das Modell X, bestätigt er zusätzlich nur, dass sein Blocker
   erledigt ist. Das ist keine Freigabe.
4. Auch hier gilt: höchstens 3 Nachbesserungsrunden, danach wird der Nutzer gefragt (wie in
   Schritt 4).

### 7. Push und Bericht
- Gepusht werden nur freigegebene Commits, auf den Branch, den die Sitzung vorgibt.
- Nach jedem Push den CI-Lauf ansehen (GitHub Actions, alle Jobs der Matrix). Ist er rot, ist das
  Beheben ein eigenes Arbeitspaket, bevor irgendetwas als fertig gemeldet wird. Eine
  Windows-Simulation im Container ersetzt den echten Windows-Runner nicht. (Hintergrund: CI war
  über fünf Pakete rot, weil nur lokal unter Linux geprüft wurde.)
- Bericht an den Nutzer mit Kurzfassung zuerst, dann eine Tabelle:

  | Paket | Worker | Prüfer | Runden | Urteil |
  |---|---|---|---|---|

  Darunter kommen die nicht blockierenden Hinweise und alles, was **hier nicht live prüfbar** war
  (z. B. Windows-Tastatur, Mikrofon, GPU). Das muss der Nutzer selbst testen, also als kurze
  Checkliste. Welches Modell welches Paket gebaut und geprüft hat, steht nur in diesem
  Chat-Bericht, nicht im Repository (siehe Schritt 4, „Modellnamen“).

## Cloud-Hinweise
- Der Skill braucht nur das Agent-Tool, git und die Tests im Container. Er kommt ohne Astra, ohne
  Cowork-Dateien und ohne den Rechner des Nutzers aus.
- Windows-Teile (Tastatur-Hooks, Zwischenablage, Mikrofon, GPU) laufen hier nicht live. Die Logik
  wird mit Attrappen getestet, der Rest per sorgfältigem Lesen geprüft und im Bericht als „nicht
  live geprüft“ markiert. Das allein ist kein Blocker.
- Der Container ist flüchtig: Jedes freigegebene Paket wird sofort committet. Bei langen
  Sitzungen dürfen freigegebene Commits auch zwischendurch gepusht werden.
- In einem anderen Repository nutzen: den Ordner `.claude/` (Skill und beide Agents) mitkopieren
  und in dessen `CLAUDE.md` die Test-Befehle eintragen.
