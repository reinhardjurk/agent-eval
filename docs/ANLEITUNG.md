# Anleitung: agent-eval benutzen

Diese Anleitung führt einmal durch den kompletten Arbeitszyklus: Einrichten →
Lauf ausführen → Ergebnisse lesen → **Konfigurationen und Szenarien vergleichen** →
eigene Varianten anlegen.

---

## 1. Einrichten

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

In `.env` mindestens `ANTHROPIC_API_KEY` eintragen (Langfuse-Keys sind optional;
rein lokale Ollama-Läufe mit Ollama-Simulator und `--no-judge` kommen ganz ohne
Key aus), dann in die Shell laden:

```bash
export $(grep -v '^#' .env | xargs)
```

**Funktionstest ohne API-Key** — läuft komplett offline mit einem Fake-LLM und
prüft nur die Pipeline, nicht die Qualität:

```bash
python -m agent_eval run --config configs/baseline.yaml --reps 1 --fake
```

---

## 2. Einen Lauf ausführen

```bash
python -m agent_eval run --config configs/baseline.yaml
```

Was dabei passiert: Für jedes Szenario in `scenarios/` (Default) wird `repetitions`-mal
(aus der Config, überschreibbar mit `--reps N`) ein komplettes Multi-Turn-Gespräch
geführt — der User-Simulator spielt den Kunden, der Assistent delegiert an seine
Agenten, die Mock-Tools loggen jeden Aufruf. Danach laufen die deterministischen
Checks und der LLM-Judge; alles wird nach Langfuse getraced (falls Keys gesetzt).

Wichtige Optionen:

| Option | Wirkung |
|---|---|
| `--scenarios <pfad>` | Szenario-Datei **oder** -Verzeichnis (Default: `scenarios/`). Auto-Domäne: `--scenarios scenarios/auto` |
| `--reps N` | Wiederholungen pro Szenario (überschreibt die Config) |
| `--out <dir>` | Ausgabeverzeichnis (Default: `results/<config-id>/`) |
| `--no-judge` | LLM-Judge überspringen (schneller/billiger, nur Checks) |
| `--fake` | Kein API-Aufruf, Pipeline-Test |

Die beiden Domänen laufen getrennt — Config und Szenarien müssen zusammenpassen:

```bash
# Telco ("Aria")
python -m agent_eval run --config configs/baseline.yaml --scenarios scenarios

# Automotive ("Nova")
python -m agent_eval run --config configs/auto-baseline.yaml --scenarios scenarios/auto
```

### Alle Befehle im Überblick

| Befehl | Zweck | Details |
|---|---|---|
| `python -m agent_eval run` | Experiment ausführen | Abschnitt 2 |
| `python -m agent_eval report [--by-scenario]` | Ergebnisse mergen und vergleichen | Abschnitte 4–5 |
| `python -m agent_eval judge` | LLM-Judge nachträglich auf gespeicherte Läufe anwenden | Abschnitt 5b |
| `python -m agent_eval label` | YAML-Vorlage für manuelle Annotation erzeugen | Abschnitt 5b |
| `python -m agent_eval calibrate` | Judge-Scores gegen manuelle Labels stellen | Abschnitt 5b |
| `python -m agent_eval.scenario_gen` | Automotive-Szenarien generieren (Menge/Seed/Domänen) | Abschnitt 7 |

---

## 3. Ergebnisse lesen

Jeder Lauf schreibt nach `results/<config-id>/`:

- **`summary.md`** — die Kennzahlentabelle (auch auf stdout) plus alle
  fehlgeschlagenen Checks mit Begründung.
- **`results.json`** — Rohdaten: pro Lauf das komplette Transkript, das Tool-Log,
  alle Checks, Judge-Scores und Metriken; dazu der vollständige Config-Dump
  (Provenienz: welcher Lauf entstand aus welcher Konfiguration).

Die Spalten der Tabelle:

| Spalte | Bedeutung |
|---|---|
| Erfolg (Checks) | `k/n (%)`: Läufe, in denen **alle** deterministischen Checks bestanden — richtiges Tool, richtige Argumente (Muster-Listen = ODER) und ein erfolgreiches Tool-Ergebnis (`result_ok`), keine verbotenen Tools. Die harte Metrik |
| 95%-CI | Wilson-Konfidenzintervall der Erfolgsquote — bei kleinem n breit; Unterschiede zwischen Konfigurationen erst ernst nehmen, wenn sich die Intervalle klar trennen |
| Ziel erreicht (Judge) | LLM-Judge: wurde das Kundenanliegen erledigt? (in % der Läufe) |
| Faithfulness | 1–5 als Mittel±SD: sind Faktenaussagen durch Tool-Ergebnisse gedeckt? Niedrig = Halluzination |
| Dialog / Voice | 1–5 als Mittel±SD: Gesprächsführung / Eignung für Sprachausgabe |
| Turn-Latenz p50/p95 | Dauer eines kompletten Assistenten-Turns (inkl. aller Agenten- und Tool-Schritte) |
| TTFT p50/p95 | Time-to-First-Token — der Proxy für die **gefühlte** Latenz am Telefon/im Auto |
| Ø Tokens, Kosten | Verbrauch pro Konversation, Kosten geschätzt nach Listenpreisen |

**Bei der Fehlersuche** immer in dieser Reihenfolge lesen: fehlgeschlagene Checks in
`summary.md` → zugehöriges Transkript und Tool-Log in `results.json` → (falls
Langfuse aktiv) den Trace öffnen, um zu sehen, an welcher Stelle — Orchestrator-
Routing, Agenten-Toolwahl oder Argumente — es gescheitert ist.

---

## 4. Konfigurationen vergleichen

Das ist der Kern-Workflow des Systems. Drei Schritte:

**Schritt 1 — Vergleichskonfiguration anlegen.** Kopie der Baseline, **genau eine
Dimension ändern**, sprechend benennen:

```bash
cp configs/baseline.yaml configs/sonnet5.yaml
```

```yaml
# configs/sonnet5.yaml — nur diese zwei Zeilen ändern:
id: sonnet5
model: claude-sonnet-5
```

Wichtig: `simulator.model` und `judge.model` unverändert lassen! Sonst vergleichst
du nicht nur Assistenten, sondern auch unterschiedliche Kunden und Bewerter.

**Schritt 2 — beide Zellen mit identischen Bedingungen laufen lassen** (gleiche
Szenarien, gleiche Wiederholungszahl, mindestens 3 wegen Nichtdeterminismus):

```bash
python -m agent_eval run --config configs/baseline.yaml --reps 3
python -m agent_eval run --config configs/sonnet5.yaml  --reps 3
```

**Schritt 3 — Vergleichsreport erzeugen:**

```bash
python -m agent_eval report \
    results/baseline-opus5/results.json \
    results/sonnet5/results.json
```

Das ergibt **eine** Tabelle mit einer Zeile pro Konfiguration — Qualität, Latenz
und Kosten direkt nebeneinander. Genauso vergleichst du drei oder fünf Zellen:
einfach mehr `results.json`-Pfade anhängen.

Dasselbe Muster für die anderen Dimensionen:

| Fragestellung | Was du variierst |
|---|---|
| Modellvergleich | `model:` (siehe oben) |
| Kontexteffekt | `context.customer_context: none/minimal/full` |
| Prompt-Variante | neue Datei `prompts/concierge-v2.md`, Config zeigt darauf |
| Tool-Beschreibungen | Kopie von `mcp/crm-server.yaml` mit anderen Beschreibungen |
| Tool-Untermenge | `mcp: [{server: ..., tools: [get_customer, get_invoices]}]` |
| Agenten-Zuschnitt | andere/mehr/weniger Cards in `agents:` |
| Latenz-Hebel | `sampling.effort: low` vs. `medium` |
| Lokal vs. API | `model: ollama/qwen3:14b` (siehe README, Abschnitt Ollama) |

**Interpretationsregeln:** Der Report nimmt dir die Rauschabschätzung ab: Die
Spalte **95%-CI** zeigt das Wilson-Konfidenzintervall der Erfolgsquote — solange
sich die Intervalle zweier Konfigurationen überlappen, ist der Unterschied nicht
belastbar (bei n=6 überlappt fast alles; im Zweifel Wiederholungen erhöhen).
Judge-Skalen tragen ±SD als Streumaß. Latenz-Perzentile zwischen lokalen
Modellen und API nicht direkt vergleichen (Hardware!), und Kosten von
`ollama/`- und `extern/`-Modellen sind immer 0.

---

## 5. Szenarien vergleichen

Zwei verschiedene Fragen, zwei Werkzeuge:

**a) „In welchen Szenarien versagt eine Konfiguration?"** — die Aufschlüsselung
pro Szenario:

```bash
python -m agent_eval report --by-scenario \
    results/baseline-opus5/results.json \
    results/sonnet5/results.json
```

Das ergibt zusätzlich eine Tabelle Konfiguration × Szenario. Typisches Muster:
Gesamt-Erfolgsquoten sehen ähnlich aus, aber das kleine Modell bricht genau bei
den `kombi-*`-Szenarien (Mehrfach-Delegation) ein, während einfache Einzelaufträge
funktionieren — das siehst du nur in dieser Ansicht. Darunter listet der Report
jeden fehlgeschlagenen Check mit Szenario und Laufnummer.

**b) „Welche Szenario-Art ist generell schwer?"** — gezielt Teilmengen laufen lassen:

```bash
# nur ein Szenario, dafür oft (Stabilität einer Problemstelle messen)
python -m agent_eval run --config configs/baseline.yaml \
    --scenarios scenarios/rechnungs-reklamation.yaml --reps 10

# nur eine Domänen-Teilmenge (Auto: nur Klima + Kombi generieren und testen)
python -m agent_eval.scenario_gen --count 10 --domains klima,kombi --out scenarios/auto-schwer
python -m agent_eval run --config configs/auto-baseline.yaml --scenarios scenarios/auto-schwer
```

In **Langfuse** geht dieselbe Analyse interaktiv: jeder Trace trägt die Tags
`<config-id>` und `<scenario-id>` sowie Metadaten (`config_id`, `model`,
`scenario`, `rep`). Nach Szenario filtern, Scores (`checks_passed`,
`goal_achieved`, `faithfulness`) danebenlegen, und per Klick in den Trace die
fehlgeschlagene Stelle im Gesprächsverlauf ansehen.

---

## 5b. Judge nachträglich anwenden und kalibrieren

Der Judge lässt sich **nachträglich** auf gespeicherte Läufe anwenden — z. B. auf
lokale Ollama-Läufe, die ohne API-Key entstanden sind (Konversationen werden
nicht neu gefahren, nur bewertet):

```bash
python -m agent_eval judge --results results/auto-lokal-qwen/results.json \
    --scenarios scenarios/auto-lokal
```

Das schreibt die Judge-Scores in die `results.json` zurück und aktualisiert die
`summary.md`.

**Kalibrierung** — bevor du Judge-Zahlen für Entscheidungen nutzt, prüfe einmal,
wie gut der Judge mit deinem Urteil übereinstimmt:

```bash
# 1. Annotations-Vorlage erzeugen (Transkript + leere Bewertungsfelder pro Lauf)
python -m agent_eval label --results results/baseline-opus5/results.json

# 2. labels.yaml von Hand ausfuellen (goal_achieved: true/false, Skalen 1-5)

# 3. Uebereinstimmung messen
python -m agent_eval calibrate --results results/baseline-opus5/results.json \
    --labels results/baseline-opus5/labels.yaml
```

Ausgegeben werden Übereinstimmung bei `goal_achieved` (%), mittlerer absoluter
Fehler (MAE) und Bias pro 1–5-Skala (Bias > 0 = Judge milder als du). Richtwert:
ab ~85–90 % Zielerreichungs-Übereinstimmung und MAE ≲ 0,7 sind die Judge-Zahlen
für Vergleiche brauchbar; darunter Rubrik im Judge-Prompt schärfen und erneut messen.

## 6. Eigene Konfiguration anlegen — Checkliste

1. `cp configs/baseline.yaml configs/<name>.yaml`
2. `id:` auf den Dateinamen setzen (bestimmt `results/<id>/` und die Langfuse-Tags)
3. Genau **eine** Dimension ändern (sonst weißt du nachher nicht, was gewirkt hat)
4. Bei geänderten Artefakten: neue Datei statt Edit der alten (`prompts/...-v2.md`),
   damit alte Experimente reproduzierbar bleiben
5. Validieren ohne Kosten: `python -m agent_eval run --config configs/<name>.yaml --reps 1 --fake`
6. Stolperfalle: `sampling.effort` wird von `claude-haiku-4-5` nicht unterstützt
   (Zeile weglassen); bei `ollama/`-Modellen wird es ignoriert
7. Neues Modell? Preise in `PRICES` (`src/agent_eval/report.py`) ergänzen
8. Committen — der PR-Smoke-Test validiert die Config automatisch

## 6b. Echten Assistenten anbinden (HTTP)

Der eingebaute Assistent ist nur der Referenz-Testkandidat — dein eigenes System
bindest du über HTTP an. Es muss einen einzigen Endpoint implementieren
(Vertrag: Docstring in [http_assistant.py](../src/agent_eval/http_assistant.py),
lauffähige Referenz: [examples/http_assistant_stub.py](../examples/http_assistant_stub.py)):

- **Request** vom Runner: `{"session_id": "<uuid>", "message": "<Kundentext>", "turn": 1}` —
  die `session_id` ist pro Konversation stabil, dein Server hält den Gesprächszustand.
- **Response**: `{"reply": "..."}` ist Pflicht. Optional: `tool_calls`
  (`[{tool, args, result, agent}]` — **nötig, damit die deterministischen Checks
  greifen**), `usage` (Tokens) und `ttft_s`.

Konfiguration ([configs/extern-http.yaml](../configs/extern-http.yaml) als Vorlage):

```yaml
id: mein-assistent-v1
model: extern/mein-assistent      # Label; Präfix extern/ ⇒ Kosten 0
assistant:
  type: http
  url: http://localhost:8080/chat
  # auth_env: MEIN_TOKEN          # Env-Var mit Bearer-Token, falls nötig
simulator: {model: claude-opus-5}
judge:     {model: claude-opus-5}
```

`agents`, `mcp` und `context` entfallen — das externe System bringt seine eigenen mit.
Verdrahtung sofort testen, ohne dass dein Assistent schon existiert:

```bash
python examples/http_assistant_stub.py 8089        # Terminal 1
python -m agent_eval run --config configs/extern-http.yaml --reps 1 --no-judge
```

Hinweise: Die Turn-Latenz ist die Wandzeit des HTTP-Aufrufs; TTFT gibt es nur,
wenn dein Server `ttft_s` selbst misst und meldet. Szenarien müssen zu den Tools
passen, die dein System tatsächlich meldet (`tool_calls[].tool`).

## 7. Eigene Szenarien anlegen

Entweder von Hand (Format siehe README, „Neues Szenario anlegen") oder für die
Auto-Domäne generieren:

```bash
python -m agent_eval.scenario_gen --count 20 --out scenarios/auto --seed 42
```

Regeln für gute Szenarien: `opening_message` fixieren (reduziert Varianz),
Erfolgskriterien **gegen das Tool-Log** formulieren (nicht gegen Formulierungen),
`with_args`-Muster tolerant halten (`"R-2024-*"`, `"*bella*"` — Matching ist
case-insensitiv), und auch Negativ-Szenarien einplanen (`forbidden_tools`:
was der Assistent gerade *nicht* tun soll).

Zwei Check-Feinheiten:

- **ODER-Muster:** Ein `with_args`-Wert darf eine Liste sein — ein Treffer genügt.
  Beispiel Mediensuche, bei der Titel *oder* Interpret zählt:
  ```yaml
  - tool: play_media
    with_args:
      query: ["*atemlos*", "*helene*", "*fischer*"]
  ```
- **`result_ok`** (Default `true`): Der passende Aufruf muss auch *erfolgreich*
  sein — liefert das Tool `{"error": ...}`, zählt der Check als nicht bestanden.
  `result_ok: false` prüft nur den Versuch (z. B. wenn das Szenario gerade das
  Fehlerhandling testen soll).

Gleicher `--seed` ⇒ identisches Set. Für Vergleiche gilt: **Szenarien-Set
einfrieren** (committen) und alle Konfigurationen gegen dasselbe Set messen —
niemals Set und Konfiguration gleichzeitig ändern.

## 8. Vergleich in der CI

Der Workflow (`.github/workflows/eval.yml`) macht bei jedem PR den Smoke-Test und
— wenn `ANTHROPIC_API_KEY` als Repo-Secret gesetzt ist — einen echten Messlauf
(1 Wiederholung), dessen Tabelle im Job-Summary erscheint und dessen Rohdaten als
Artefakt `eval-results` herunterladbar sind. Manuell mit anderer Config starten:
GitHub → Actions → „Eval" → *Run workflow* → Config-Pfad und Wiederholungen angeben.

So wird jeder Prompt-/Card-/Tool-PR automatisch zum Mini-Experiment: Tabelle im
PR ansehen, mit dem letzten Baseline-Lauf vergleichen, erst dann mergen.

## 9. Häufige Probleme

| Symptom | Ursache / Lösung |
|---|---|
| `400` mit Hinweis auf `effort`/`output_config` | Modell unterstützt kein `effort` (z. B. Haiku) → Zeile aus `sampling` entfernen |
| Abbruch beim Start: API-Key | `ANTHROPIC_API_KEY` nicht exportiert (`.env` wird nicht automatisch geladen) |
| `Connection refused` bei `ollama/`-Modell | `ollama serve` läuft nicht bzw. `OLLAMA_HOST` falsch; Modell mit `ollama pull` holen |
| Judge-Spalten zeigen `–` | Lauf mit `--no-judge` oder `--fake`, oder Judge-Aufruf fehlgeschlagen (stdout prüfen); nachträglich bewerten: `python -m agent_eval judge` |
| Check-Detail „Tool lieferte einen Fehler" | Der Aufruf passte, aber das Tool gab `{"error": ...}` zurück — Standardverhalten (`result_ok: true`). Soll nur der Versuch zählen, im Szenario `result_ok: false` setzen |
| HTTP-Assistent: Checks scheitern trotz korrekter Antworten | Externes System liefert kein `tool_calls`-Feld — ohne Tool-Log keine tool-basierten Checks (Abschnitt 6b) |
| Keine Traces in Langfuse | `LANGFUSE_*`-Keys fehlen/falsch — der Runner läuft dann bewusst ohne Tracing weiter |
| Ergebnisse schwanken stark | Normal bei kleinen N — Wiederholungen erhöhen, Streuung mitbetrachten |
