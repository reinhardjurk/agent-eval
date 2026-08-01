# agent-eval

Systematische Evaluation eines Multi-Agenten-**Sprachassistenten**: Wie wirken sich
**Modell**, **Agenten-Konfiguration (Agent Cards)**, **Tool-Konfiguration (MCP)** und
**Initialkontext** auf **Qualität, Antwortzeit und Tokenverbrauch** aus?

Jede Untersuchung ist ein Experiment: **Konfiguration × Testszenario → Metriken.**
Ein LLM-basierter User-Simulator führt Multi-Turn-Gespräche gegen den Assistenten,
alle Schritte werden nach [Langfuse](https://langfuse.com) getraced, die Bewertung
läuft automatisiert über deterministische Checks (Ground Truth = Mock-Tool-Log)
plus LLM-as-a-Judge.

```
Konfiguration (configs/*.yaml)          Szenario (scenarios/*.yaml)
  Modell, Agent Cards, MCP-Tools,         Persona, Ziel, Verhalten,
  Kontext, Sampling                       Erfolgskriterien
        │                                       │
        ▼                                       ▼
   ┌─────────────────────── Runner ────────────────────────┐
   │  User-Simulator ⇄ Orchestrator ⇄ Sub-Agenten ⇄ Mock- │
   │  (LLM, Persona)    (Concierge)    (Agent Cards)  MCP  │
   └───────┬──────────────────────────────┬────────────────┘
           │ Traces, Generations,         │ Tool-Log
           │ Latenz/TTFT, Tokens          │ (Ground Truth)
           ▼                              ▼
        Langfuse                 Checks + LLM-Judge → Scores
           │                              │
           └────────────► results.json + summary.md ◄──────
```

> 📘 **Ausführliche Schritt-für-Schritt-Anleitung** — inklusive Vergleichs-Workflows
> für Konfigurationen und Szenarien: [docs/ANLEITUNG.md](docs/ANLEITUNG.md)
> 🔧 **Technische Dokumentation** — Architektur, Komponenten, Datenformate,
> Erweiterungspunkte: [docs/TECHNIK.md](docs/TECHNIK.md)

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env      # Keys eintragen, dann: export $(grep -v '^#' .env | xargs)
```

**Ohne API-Key testen** (kompletter Pipeline-Durchstich mit Fake-LLM):

```bash
python -m agent_eval run --config configs/baseline.yaml --reps 1 --fake
```

**Echter Lauf** (Baseline, 3 Wiederholungen pro Szenario):

```bash
python -m agent_eval run --config configs/baseline.yaml
```

**Konfigurationen vergleichen:**

```bash
python -m agent_eval run --config configs/baseline.yaml
python -m agent_eval run --config configs/haiku-full-context.yaml
python -m agent_eval report results/baseline-opus5/results.json results/haiku-full-context/results.json
```

## Konfigurationsraum

Jede Dimension ist ein versioniertes Artefakt — Änderungen daran sind per Git-Diff
nachvollziehbar und per CI regressionsgetestet:

| Dimension | Ort | Beispiele für Variation |
|---|---|---|
| Modell | `configs/*.yaml` → `model` | `claude-opus-5` vs. `claude-haiku-4-5` |
| Agent Cards | `cards/*.json` | Beschreibungen (steuern das Routing!), Tool-Zugriff, Modell-Override pro Agent |
| MCP-Tools | `mcp/*.yaml` + `configs` → `mcp.tools` | Tool-Beschreibungen, Untermengen von Tools |
| Initialkontext | `configs` → `context` | System-Prompt-Varianten, `customer_context: none/minimal/full` |
| Sampling | `configs` → `sampling` | `max_tokens`, `effort` (Latenz-Hebel; von Haiku 4.5 nicht unterstützt) |

### Andere Modelle einstellen

Das Modell wird an drei Stellen konfiguriert: `model` (Assistent), `simulator.model`
und `judge.model` in der Experiment-YAML; zusätzlich kann jede Agent Card per
`"model": "..."` das Modell für einen einzelnen Agenten überschreiben. Simulator
und Judge bei Vergleichen **konstant halten**, sonst variieren Kunde und Bewerter mit.
Neue Modelle in `PRICES` ([report.py](src/agent_eval/report.py)) eintragen, damit die
Kostenschätzung stimmt.

### Lokale Modelle über Ollama

Modellnamen mit dem Präfix `ollama/` laufen gegen einen lokalen Ollama-Server statt
gegen die Claude API — siehe [configs/ollama-qwen.yaml](configs/ollama-qwen.yaml):

```bash
pip install -e ".[ollama]"
ollama pull qwen3:14b            # Modell mit Tool-Calling-Support waehlen!
python -m agent_eval run --config configs/ollama-qwen.yaml
```

Der Adapter ([ollama_llm.py](src/agent_eval/ollama_llm.py)) übersetzt Tool-Calls
zwischen Anthropic- und Ollama-Format; Server-Adresse via `OLLAMA_HOST`
(Default `http://localhost:11434`). Hinweise:

- Simulator und Judge bleiben standardmäßig auf Claude (fairer Vergleich) —
  dafür wird weiterhin `ANTHROPIC_API_KEY` benötigt. Rein lokal: `simulator.model`
  ebenfalls auf `ollama/...` setzen und mit `--no-judge` starten.
- Der Judge selbst unterstützt nur Claude-Modelle.
- Lokale Kosten werden als 0 gerechnet; Latenzen sind hardwareabhängig und mit
  API-Latenzen nur eingeschränkt vergleichbar.
- Schwaches Tool-Calling kleiner Modelle ist ein Messergebnis, kein Harness-Fehler.

## Metriken

| Achse | Was gemessen wird |
|---|---|
| Qualität | Erfolgsquote der deterministischen Checks (richtiges Tool, richtige Argumente, verbotene Tools, Erwähnungen), Judge-Scores: Zielerreichung, Faithfulness (Halluzinationen ggü. Tool-Log), Gesprächsführung, Voice-Eignung |
| Latenz | Turn-Latenz p50/p95 und **Time-to-First-Token** p50/p95 (gefühlte Latenz am Telefon) |
| Verbrauch | Input-/Output-Tokens pro Konversation, geschätzte Kosten in USD |

## Langfuse

Ohne `LANGFUSE_*`-Keys läuft alles trotzdem (Tracing wird still deaktiviert).
Mit Keys bekommt jede Konversation einen Trace mit verschachtelten Spans
(Orchestrator → Agent → Tool-Call), Generations mit Token-Usage sowie Scores
(`checks_passed`, `goal_achieved`, `faithfulness`, …). Filtern/Vergleichen im UI
über die Trace-Metadaten `config_id`, `model`, `scenario` und die Tags.

Zwei Betriebsarten:

- **Langfuse Cloud** (schnellster Start): Projekt auf https://cloud.langfuse.com anlegen, Keys in `.env`.
- **Self-hosted**: offizielles Compose-Setup verwenden —
  ```bash
  git clone https://github.com/langfuse/langfuse.git && cd langfuse && docker compose up
  ```
  dann `LANGFUSE_HOST=http://localhost:3000`.

## GitHub Actions

`.github/workflows/eval.yml` enthält zwei Jobs:

- **smoke** — läuft bei jedem PR, der Prompts/Cards/Configs/Tools/Szenarien/Code
  ändert. Braucht keine Secrets: `pytest` + Fake-Modus-Durchstich.
- **eval** — echter Messlauf gegen die Claude API (1 Wiederholung pro Szenario),
  Ergebnisse als Markdown-Tabelle im Job-Summary und als Artefakt. Läuft nur,
  wenn das Repo-Secret `ANTHROPIC_API_KEY` gesetzt ist; manuell mit eigener
  Config/Wiederholungszahl über *Run workflow* (workflow_dispatch) startbar.

Benötigte Repo-Secrets: `ANTHROPIC_API_KEY`, optional `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`.

## Zweite Domäne: In-Car-Sprachassistent (Automotive)

Neben der Telco-Domäne gibt es eine komplette Fahrzeug-Domäne (Assistent „Nova":
Navigation, Entertainment, Klima) mit eigenen Agent Cards, Tools
([mcp/car-server.yaml](mcp/car-server.yaml)) und Config
([configs/auto-baseline.yaml](configs/auto-baseline.yaml)).

Die Dialogszenarien dafür erzeugt ein Generator — Menge, Seed und Domänen konfigurierbar:

```bash
python -m agent_eval.scenario_gen --count 20 --out scenarios/auto --seed 42
python -m agent_eval.scenario_gen --count 6 --domains klima,kombi
python -m agent_eval run --config configs/auto-baseline.yaml --scenarios scenarios/auto
```

Der Generator kombiniert Dialog-Blueprints (z. B. Reichweitenangst, beschlagene
Scheibe, Klimazonen-Streit auf Langstrecke, Erstes-Date-Kombiauftrag) mit Persona-
und Eigenheiten-Pools; gleiche Seeds erzeugen identische Sets (reproduzierbare
Messreihen). Ein committetes Grundset von 12 Dialogen liegt unter
[scenarios/auto/](scenarios/auto/). `kombi`-Szenarien erwarten mehrere Tool-Aufrufe
über Agentengrenzen hinweg und testen damit gezielt das Routing des Orchestrators.

## Neues Szenario anlegen

`scenarios/<name>.yaml` — Persona/Ziel/Verhalten steuern den User-Simulator,
`opening_message` fixiert den ersten Kundensatz (reduziert Varianz),
`success_criteria` definieren die deterministischen Checks gegen das Tool-Log:

```yaml
id: mein-szenario
persona: "…"
goal: "…"
constraints: "…"
opening_message: "…"
max_turns: 8
success_criteria:
  tool_calls:
    - tool: create_complaint
      with_args: {invoice_id: "R-2024-*"}   # fnmatch-Muster
  forbidden_tools: [update_address]
  assistant_mentions: ["Ticket"]            # Regex auf Assistententext
```

## Methodik-Hinweise

- **Wiederholungen**: LLMs sind nichtdeterministisch — pro Zelle mindestens 3 Läufe,
  Mittelwert *und* Streuung betrachten.
- **Nicht das volle Kreuzprodukt** fahren: erst eine Dimension variieren (Screening),
  dann nur interessante Kombinationen kreuzen.
- **Mock-MCP mit fixen Fixtures** (`fixtures/crm.json`) hält das Backend deterministisch —
  gemessen werden Konfigurationsunterschiede, nicht Backend-Rauschen.
- **Voice**: Die Dialoglogik wird textbasiert getestet; TTFT ist der Proxy für die
  gefühlte Telefon-Latenz. Eine echte Audio-Pipeline (ASR/TTS) misst man separat.

## Roadmap / Erweiterungen

- Anbindung eines echten Assistenten statt des eingebauten Referenz-Assistenten
  (Interface: `respond(user_text) -> TurnResult` in `src/agent_eval/assistant.py`)
- Echte MCP-Server (stdio/HTTP) statt In-Process-Mocks
- Langfuse Datasets/Experiments für Vergleichsansichten direkt im UI
- Latenzbudgets als harte Checks (z.B. TTFT p95 < 1,5 s)
- Kalibrierung des Judges gegen manuell annotierte Gespräche
