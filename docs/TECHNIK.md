# Technische Dokumentation

Architektur und Interna von **agent-eval**. Zielgruppe: Entwickler, die das
System erweitern oder den eingebauten Referenz-Assistenten durch einen echten
ersetzen wollen. Für die Bedienung siehe [ANLEITUNG.md](ANLEITUNG.md).

## 1. Systemüberblick

agent-eval führt kontrollierte Experimente über einen Multi-Agenten-Sprachassistenten
aus: **Experiment = Konfiguration × Szenario × Wiederholung → Metriken.** Alle
Einflussgrößen sind versionierte Dateien, alle Messgrößen entstehen automatisch
aus Streaming-Instrumentierung, einem Tool-Call-Log und automatisierter Bewertung.

```
                     ┌────────────────────────── runner.py ───────────────────────────┐
                     │                                                                │
 configs/*.yaml ──►  │   Schleife: Szenario × Wiederholung                            │
 scenarios/*.yaml ─► │                                                                │
                     │   ┌ simulator.py ┐      ┌──────── assistant.py ────────┐       │
                     │   │ UserSimulator │ ◄──► │ Orchestrator ──► Sub-Agenten │       │
                     │   │  (LLM, Rolle  │      │ (Concierge)     (AgentCards) │       │
                     │   │   "Kunde")    │      └───────┬──────────────┬───────┘       │
                     │   └───────────────┘              │ delegate     │ tool_use      │
                     │                                  ▼              ▼               │
                     │                            llm.py / ollama_llm.py   mock_tools  │
                     │                            (Provider-Schicht)       (Fixtures + │
                     │                                                     Call-Log)   │
                     │                                                                │
                     │   danach: evaluators.py (Checks + Judge)                       │
                     └──────┬──────────────────────────────┬──────────────────────────┘
                            │ Traces/Scores                │ RunResult-Dicts
                            ▼                              ▼
                       tracing.py ──► Langfuse        report.py ──► results.json,
                                                                    summary.md,
                                                                    GITHUB_STEP_SUMMARY
```

Das Diagramm zeigt den eingebauten Referenz-Assistenten; bei
`assistant: {type: http}` tritt an dessen Stelle der HTTP-Adapter
(Abschnitt 3.3b), der ein extern laufendes System anspricht — Simulator,
Bewertung, Tracing und Report bleiben identisch.

Zentrale Design-Entscheidungen:

- **Determinismus, wo möglich:** Tool-Backend als In-Process-Mock mit fixen
  Fixtures; Szenarien mit fixem Eröffnungssatz; Szenario-Generator seed-basiert.
  Nichtdeterminismus bleibt nur in den LLMs — dem begegnet man mit Wiederholungen.
- **Ground Truth = Tool-Log**, nicht Gesprächstext: Erfolg wird primär daran
  gemessen, ob die richtigen Tools mit den richtigen Argumenten aufgerufen wurden.
- **Alles degradiert sanft:** ohne Langfuse-Keys kein Tracing (aber voller Lauf),
  ohne API-Key Fake-Modus bzw. reine Ollama-Läufe, Judge abschaltbar.

## 2. Verzeichnisstruktur

| Pfad | Inhalt |
|---|---|
| `configs/` | Experimentkonfigurationen (je Datei eine Messzelle) |
| `cards/` | Agent Cards: Name, Beschreibung (=Routing-Prompt!), System-Prompt-Pfad, Tool-Liste, optionaler Modell-Override |
| `prompts/` | System-Prompts für Orchestratoren und Agenten |
| `mcp/` | Tool-Definitionen im MCP-Stil (Name, Beschreibung, JSON-Schema, Handler-Referenz) |
| `fixtures/` | Deterministische Datenbestände der Mock-Tools (CRM, Fahrzeug) |
| `scenarios/` | Testszenarien; Unterverzeichnisse pro Domäne/Set (`auto/`, `auto-lokal/`) |
| `src/agent_eval/` | Python-Paket (Details in Abschnitt 3) |
| `tests/` | Smoke- und Unit-Tests (laufen ohne API/Server) |
| `results/` | Laufergebnisse (gitignored) |
| `docs/experimente/` | Committete Experiment-Protokolle |
| `.github/workflows/eval.yml` | CI: Smoke-Job (ohne Secrets) + Eval-Job |

## 3. Komponenten

### 3.1 `config.py` — Schemata und Lader

Pydantic-Modelle für alle Artefakte: `ExperimentConfig`, `AgentCard`,
`MCPServerConfig`/`ToolDef`, `Scenario`/`SuccessCriteria`. `load_experiment()`
löst eine Config vollständig auf (`ResolvedExperiment`): liest Cards und Prompts,
schneidet die Tool-Menge gemäß `mcp[].tools` zu (`tools_by_agent`) und lädt die
Fixtures. Alle Pfade sind relativ zur Projektwurzel = `config_path.parent.parent`.

### 3.2 `llm.py` / `ollama_llm.py` — Provider-Schicht

Das zentrale Interface ist bewusst schmal:

```python
complete(system: str, messages: list, tools: list | None) -> LLMResult
# LLMResult: message, latency_s, ttft_s, input_tokens, output_tokens
```

Drei Implementierungen:

| Klasse | Backend | Besonderheiten |
|---|---|---|
| `LLM` | Claude API (anthropic-SDK, Streaming) | misst TTFT über das erste `text_delta`-Event; `output_config.effort` optional; zählt Cache-Tokens zum Input |
| `OllamaLLM` | lokaler Ollama-Server | übersetzt Anthropic-Blocks ↔ Ollama-Format (s.u.); `think`-Flag; Fallback Streaming→blocking und think→ohne-think |
| `FakeLLM` | keins | fixer Text, feste Pseudo-Metriken; trägt Smoke-Tests und CI ohne Secrets |

Die Provider-Weiche sitzt in `runner._build_llm()` und entscheidet am
Modellnamen-Präfix (`ollama/`). Message-Historie und Tool-Definitionen sind
überall im **Anthropic-Format** — `OllamaLLM` übersetzt an der Grenze:

- Tool-Defs: `{name, description, input_schema}` → `{type: "function", function: {..., parameters}}`
- Assistant-Blocks (`text`, `tool_use`) → `content` + `tool_calls`
- `tool_result`-Blocks → Rolle `tool` mit `tool_name` (Ollama kennt keine
  Tool-Call-IDs; `OllamaLLM` erzeugt synthetische IDs und mappt sie intern auf Namen)
- `stop_reason` wird synthetisiert (`tool_use` bei Tool-Calls, sonst `end_turn`)

**Thinking-Modelle** (qwen3, gemma4): Ollama liefert Denk-Tokens getrennt vom
`content`; bei kleinem `num_predict` kann das Denken das Kontingent aufbrauchen →
leerer Text. Deshalb akzeptiert `OllamaLLM` `think=False` (wird weggelassen, wenn
das Modell/der Server das Flag ablehnt — einmaliger Retry ohne Flag).

### 3.3 `assistant.py` — der Testkandidat

`MultiAgentAssistant` implementiert das Referenzsystem:

- **Orchestrator** ("Concierge"): führt die Kundenkonversation mit persistenter
  Historie. Seine Tools sind ausschließlich `delegate_to_<agent>`-Tools, die aus
  den Agent Cards generiert werden — **die Card-`description` ist der
  Routing-Prompt**. Schleife bis `stop_reason != "tool_use"`, max. 6 Iterationen
  pro Turn.
- **Sub-Agenten:** pro Delegation ein frischer Kontext (`task`-String als einzige
  User-Message), eigener System-Prompt aus der Card, eigene Tool-Untermenge,
  eigene Tool-Schleife (max. 8 Iterationen). Ergebnis-Text geht als `tool_result`
  an den Orchestrator zurück.
- **Kundenkontext:** `context.customer_context` (none/minimal/full) rendert einen
  Block aus dem ersten Fixture-Kunden in die System-Prompts (Telco); Domänen ohne
  `customers`-Fixture (Auto) liefern immer einen leeren Block.
- **Metriken pro Turn** (`TurnResult`): Wandzeit, Turn-TTFT (Zeit vom Turn-Start
  bis zum ersten Text-Delta über alle API-Calls des Turns), API-Call-Zahl,
  Token-Summen über Orchestrator- und Agenten-Calls.

**Anbindung eines echten Assistenten:** Der Runner benötigt nur ein Objekt mit
`respond(user_text) -> TurnResult`. Für HTTP-erreichbare Systeme existiert ein
fertiger Adapter (Abschnitt 3.3b); für andere Transporte schreibt man eine
Klasse mit derselben Signatur und erweitert die Weiche in
`runner.run_conversation()`. Einzige Zusatzanforderung für die deterministischen
Checks: Tool-Aufrufe müssen ins `MockToolRuntime`-Log laufen.

### 3.3b `http_assistant.py` — externer Assistent über HTTP

Aktiviert per `assistant: {type: http, url: ...}` in der Config (`agents`,
`mcp`, `context` entfallen dann; `model` ist nur noch Label, Konvention
`extern/<name>` → Kosten 0). Pro Konversation erzeugt der Adapter eine frische
`session_id` (UUID) — der externe Server hält den Gesprächszustand pro Session.

| Richtung | JSON |
|---|---|
| Request (POST `url`) | `{"session_id", "message", "turn"}` |
| Response | `{"reply"}` Pflicht; optional `"tool_calls": [{tool, args, result, agent}]`, `"usage": {input_tokens, output_tokens}`, `"ttft_s"` |

Verhalten: `tool_calls` werden ins Check-Log übernommen (Objekt-`result`s werden
für die `result_ok`-Prüfung JSON-serialisiert); ohne sie können tool-basierte
Checks nicht bestehen — Transkript-Checks und Judge funktionieren trotzdem.
Latenz misst der Runner als Wandzeit des POST; TTFT nur, wenn der Server
`ttft_s` selbst meldet. Optionales Bearer-Token über `assistant.auth_env`
(Name einer Env-Var). Referenzimplementierung des Vertrags:
`examples/http_assistant_stub.py`; im Fake-Modus wird immer der eingebaute
Assistent verwendet (Pipeline-Test ohne externe Systeme).

### 3.4 `mock_tools.py` — deterministisches Tool-Backend

`MockToolRuntime` hält den Fixture-Zustand (Deep Copy pro Konversation → Läufe
sind isoliert) und ein append-only `calls`-Log (`ToolCall`: agent, tool, args,
result, t). `HANDLERS` mappt Handler-Namen aus den `mcp/*.yaml` auf Python-
Funktionen `(state, args) -> JSON-String`; Fehler werden als `{"error": ...}`
zurückgegeben (nie Exceptions — das Modell soll mit Fehlern umgehen). Handler
sind bewusst streng (z. B. verlangt `add_stopover` eine aktive Route), damit
Szenarien Vorbedingungs-Logik testen können.

### 3.5 `simulator.py` — der simulierte Kunde

LLM-Rollenspiel mit Systemprompt aus Szenario-Feldern (`setting`, `persona`,
`goal`, `constraints`). Pro Zug wird das **komplette Transkript als Text**
gerendert (keine geteilte Historie mit dem Assistenten — die beiden Seiten sehen
sich nur über die ausgetauschten Äußerungen). Terminierung über die Marke
`[DONE]` am Antwortanfang; eine leere Antwort wird einmal wiederholt, danach
endet das Gespräch. Der Simulator läuft mit kleinem Token-Budget (600) und
`think=False`.

### 3.6 `evaluators.py` — Bewertung

**Deterministische Checks** gegen Szenario-`success_criteria`:

| Check | Quelle | Semantik |
|---|---|---|
| `tool_called:<name>` | Tool-Log | mind. ein Aufruf, dessen Argumente alle `with_args`-Muster erfüllen (fnmatch, case-insensitiv; Listen sind ODER-verknüpft) und der bei `result_ok: true` (Default) kein `{"error": ...}` zurückgab |
| `tool_not_called:<name>` | Tool-Log | Tool wurde nie aufgerufen |
| `assistant_mentions:<regex>` | Transkript | Regex (IGNORECASE) über alle Assistententexte |
| `within_max_turns` | Transkript | Assistenten-Turns ≤ `max_turns` |

`success = alle Checks bestanden`. **LLM-Judge**: `client.messages.parse()` mit
Pydantic-Schema `JudgeScores` (goal_achieved, faithfulness 1–5, conversation_quality,
voice_suitability, comment); Input sind Transkript + Tool-Log (als Ground Truth
deklariert). Der Judge ist Claude-only (Structured Outputs) und wird bei
Ollama-Judge-Modellen oder `--no-judge` übersprungen.

### 3.7 `tracing.py` — Langfuse

Dünner Wrapper um das Langfuse-v3-SDK (OTel-basiert), No-Op ohne
`LANGFUSE_PUBLIC_KEY`/`SECRET_KEY` oder bei Fehlern. Trace-Struktur pro Konversation:

```
Trace  <config-id>/<scenario-id>#<rep>     (metadata: config_id, model, assistant, scenario,
│                                           rep, customer_context; tags: [config-id, scenario-id])
├─ generation orchestrator                 (model, usage, in/out)
├─ span agent:<name>                       (input: task)
│   ├─ generation <agent-name>
│   └─ span tool:<tool>                    (input: args, output: result)
├─ generation user-simulator
└─ Scores: checks_passed, goal_achieved, faithfulness,
           conversation_quality, voice_suitability
```

### 3.8 `runner.py` — Orchestrierung

`run_experiment()`: Config + Szenarien laden → Anthropic-Client nur erzeugen,
wenn irgendeine Rolle ihn braucht (bei `assistant.type: http` zählen nur
Simulator und Judge) → Schleife über Szenario × Wiederholung →
`run_conversation()` → `results.json` + `summary.md` schreiben, Tabelle auf
stdout und nach `GITHUB_STEP_SUMMARY`. `run_conversation()` verdrahtet pro Lauf
frische Instanzen (Runtime mit Fixture-Kopie, Assistent gemäß `assistant.type` —
im Fake-Modus immer der eingebaute —, Simulator) und beendet die Schleife bei
`[DONE]`, leerer Simulatorantwort oder `max_turns`.

### 3.9 `report.py` — Aggregation

Preisliste `PRICES` (USD/1M Tokens, längster Modell-Präfix gewinnt, `ollama/` = 0),
Perzentile (nearest-rank), drei Renderer: `render_summary` (eine Zeile pro
Konfiguration), `render_by_scenario` (Konfiguration × Szenario) und
`render_failures` (jeder fehlgeschlagene Check mit Detail). Erfolgsquoten werden
als `k/n (%)` mit **Wilson-95%-Konfidenzintervall** ausgewiesen, Judge-Skalen als
Mittelwert±Standardabweichung — Unterschiede zwischen Konfigurationen sind erst
belastbar, wenn sich die Intervalle klar trennen.

### 3.9b `judging.py` — Judge-Betrieb und Kalibrierung

Drei Funktionen hinter den CLI-Subcommands `judge`, `label`, `calibrate`:
`judge_results()` wendet den Judge **nachträglich** auf eine gespeicherte
`results.json` an (rekonstruiert das Tool-Log, schreibt Scores und `summary.md`
zurück — Konversationen werden nicht neu gefahren). `write_label_template()`
erzeugt eine YAML-Annotationsvorlage (Transkript + leere Felder pro Lauf);
`calibrate()` vergleicht ausgefüllte Labels mit den Judge-Scores und liefert
Übereinstimmung (goal_achieved), MAE und Bias pro 1–5-Skala.

### 3.10 `scenario_gen.py` — Szenario-Generator (Automotive)

16 Blueprint-Funktionen in 4 Domänen (`navigation`, `entertainment`, `klima`,
`kombi`), kombiniert mit Persona- und Eigenheiten-Pools. `generate(count,
domains, seed)` verteilt die Menge round-robin über die Domänen, wählt Blueprints
und Parameter über `random.Random(seed)` (deterministisch) und validiert jedes
Szenario vor dem Schreiben gegen das Pydantic-Schema.

## 4. Datenformate

### 4.1 Experimentkonfiguration (`configs/*.yaml`)

```yaml
id: string                      # = Ausgabeverzeichnis + Langfuse-Tag
model: string                   # "claude-*", "ollama/<name>"; bei assistant.type http
                                #   nur Label (Konvention "extern/<name>" -> Kosten 0)
assistant:                      # optional; Default: eingebauter Referenz-Assistent
  type: builtin|http
  url: string                   # Pflicht bei http
  timeout_s: float              # Default 120
  auth_env: string              # optional: Env-Var mit Bearer-Token
agents: [pfad/zu/card.json]     # Pflicht bei builtin; Card-Beschreibung steuert Routing
mcp:                            # Pflicht bei builtin
  - server: mcp/x.yaml
    tools: [name, ...]          # optional: Untermenge; fehlt = alle
context:                        # Pflicht bei builtin; entfaellt bei http
  system_prompt: prompts/x.md
  customer_context: none|minimal|full
sampling:
  max_tokens: int               # Claude: max_tokens, Ollama: num_predict
  effort: low|...|max           # optional; nur Claude-Modelle mit effort-Support
simulator: {model: string}      # konstant halten bei Vergleichen!
judge:     {model: string}      # Claude-only
repetitions: int
```

Die Validierung erzwingt die Kombinationen: `type: http` erfordert `url`;
`type: builtin` erfordert `context` und mindestens einen `agents`-Eintrag.

### 4.2 Ergebnisdatei (`results/<id>/results.json`)

```jsonc
{
  "config": { /* vollstaendiger ExperimentConfig-Dump (Provenienz) */ },
  "runs": [{
    "scenario": "id", "rep": 1,
    "success": true,                       // alle Checks bestanden
    "checks":  [{"name", "passed", "detail"}],
    "judge":   {"goal_achieved", "faithfulness", ...} | null,
    "metrics": {
      "turns", "api_calls", "input_tokens", "output_tokens",
      "cost_usd", "duration_s",
      "turn_latencies": [s, ...],          // pro Assistenten-Turn
      "ttfts": [s, ...]                    // pro Turn, sofern Text gestreamt wurde
    },
    "transcript": [{"role": "customer|assistant", "text"}],
    "tool_calls": [{"agent", "tool", "args", "result"}]
  }]
}
```

### 4.3 Metrik-Definitionen

- **Turn-Latenz:** Wandzeit von `respond()`-Aufruf bis finaler Antworttext,
  inklusive aller Orchestrator-/Agenten-Calls und Tool-Ausführungen des Turns.
- **TTFT (Turn):** Zeit vom Turn-Start bis zum ersten Text-Delta irgendeines
  Calls in diesem Turn — Proxy für „wann hört der Nutzer das erste Wort".
  Bei Thinking-Modellen zählt die Denkzeit mit hinein (gewollt).
- **Tokens:** Summe über alle Calls des Laufs; bei Claude inkl. Cache-Lese/-Schreib-
  Tokens auf der Inputseite, bei Ollama `prompt_eval_count`/`eval_count`.
- **Kosten:** `tokens × PRICES[model]`; Schätzwert (Listenpreise, kein Caching-Rabatt).

## 5. Erweiterungspunkte

| Ziel | Vorgehen |
|---|---|
| Neuer LLM-Provider (vLLM, OpenAI-kompatibel, …) | Klasse mit `complete()`-Interface analog `OllamaLLM`, Präfix-Weiche in `runner._build_llm()` erweitern, Preis in `PRICES` |
| Echten Assistenten testen (HTTP) | fertig: `assistant: {type: http, url: ...}` — Vertrag siehe 3.3b |
| Echten Assistenten testen (anderer Transport) | Adapter mit `respond(user_text) -> TurnResult`, Weiche in `run_conversation()` erweitern (siehe 3.3) |
| Neue Domäne | Fixtures + Handler in `mock_tools.HANDLERS` + `mcp/*.yaml` + Cards + Prompts + Config; Szenarien von Hand oder eigener Generator |
| Neue Check-Art | Funktion in `evaluators.deterministic_checks()`; Schema-Feld in `SuccessCriteria` ergänzen |
| Neues Judge-Kriterium | Feld in `JudgeScores` + Score-Übertragung in `runner.run_conversation()` + Spalte in `report` |
| Echter MCP-Server statt Mock | `MockToolRuntime.execute()` durch MCP-Client-Aufruf ersetzen (stdio/HTTP); Call-Log-Schnittstelle beibehalten, sonst brechen die Checks |

## 6. CI-Pipeline

`eval.yml`, zwei Jobs: **smoke** (jeder PR auf Konfigurations-/Code-Pfade;
`pytest` + Fake-Lauf; keine Secrets nötig) und **eval** (echter Messlauf, nur
wenn `ANTHROPIC_API_KEY` als Secret existiert; Tabelle ins Job-Summary, Rohdaten
als Artefakt; manuell per `workflow_dispatch` mit Config/Reps-Eingaben).
Secrets: `ANTHROPIC_API_KEY`, optional `LANGFUSE_*`.

## 7. Bekannte Grenzen

- **Reihenfolge der Turn-Zählung:** `max_turns` zählt Assistenten-Turns; ein
  Szenario kann also `max_turns + 1` Kundenäußerungen enthalten (Eröffnung).
- **Simulator sieht nur Text:** kein geteilter Zustand mit dem Assistenten;
  Missverständnisse über Weltzustand (z. B. „läuft die Musik?") sind möglich und
  gewollt — der Assistent muss sie kommunikativ auflösen.
- **Judge/Structured Outputs nur Claude:** lokale Modelle können Testkandidat und
  Simulator sein, nicht Judge.
- **Kostenmodell statisch:** `PRICES` ist eine gepflegte Tabelle, kein API-Abruf.
- **Ein Prozess, sequenziell:** Läufe sind nicht parallelisiert; bei lokalen
  Modellen limitiert ohnehin die GPU/CPU.
