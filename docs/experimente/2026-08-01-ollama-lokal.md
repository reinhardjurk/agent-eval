# Experiment 2026-08-01: Lokale Modelle (Ollama), 5 Zellen

**Frage:** Wie schlagen sich lokale Modelle als In-Car-Assistent "Nova", und wie
wirken Agenten-Zuschnitt, Tool-Beschreibungen und System-Prompt?

**Aufbau:** Eingefrorenes Set `scenarios/auto-lokal` (6 Szenarien, Seed 7),
1 Wiederholung/Szenario, Simulator konstant `ollama/gemma4:latest` (think=off),
ohne LLM-Judge (kein API-Key; nur deterministische Checks). Zellen:
`auto-lokal-qwen` (Baseline: qwen3.6:35b-mlx, 3 Spezialagenten, volle
Tool-Beschreibungen, voller Prompt), `-llama` (llama3.2:3b), `-mono`
(1 Universalagent), `-knapp` (knappe Tool-Beschreibungen), `-minimal`
(minimaler System-Prompt).

## Befunde

1. **Modellvergleich:** qwen3.6:35b 83 % vs. llama3.2:3b 67 % Checks-Erfolg.
   llama scheiterte an beiden Medien-Szenarien (einmal gar kein play_media).
   Dafuer ist llama beim Voice-Kriterium klar vorn: TTFT p50 1,3 s vs. 15,5 s —
   qwen "verdenkt" als Thinking-Modell zweistellige Sekunden pro Turn und ist
   so fuer Sprachbedienung unbrauchbar langsam, llama liegt im nutzbaren Bereich.
2. **Agenten-Zuschnitt:** Der Universalagent (mono) erreichte dieselbe
   Erfolgsquote wie die 3 Spezialisten, aber mit ~45 % weniger Tokens und
   besserer Latenz (Delegations-Overhead). ABER: Beim Dreifachauftrag
   kombi-date liess NUR die Baseline nichts fallen; mono vergass die
   Temperatur — obwohl der Kunde sie nannte — und behauptete Vollzug.
3. **Tool-Beschreibungen (knapp) und Minimal-Prompt:** Beide Varianten fielen
   auf 67 % und liessen beim Mehrfachauftrag Teilwuensche fallen. Sorgfaeltige
   Beschreibungen/Prompts zahlen v.a. bei komplexen Auftraegen ein.
4. **Echte Fabrikation gefunden (Vorlauf, defekter Simulator):** qwen meldete
   "Die Musik ist jetzt eingeschaltet" ohne jeden Tool-Call — genau der Fall
   fuer den Faithfulness-Judge, der hier mangels API-Key aus war.
5. **Methodisches:** 4 der 8 fehlgeschlagenen Checks waren zu strenge
   Muster, keine echten Fehler (Suche nach 'Helene Fischer' statt '*atemlos*'
   findet den Song im Mock trotzdem). Lernpunkt: Medien-Checks brauchen
   ODER-Muster (Titel ODER Interpret) — mit 1 Wiederholung/Zelle sind
   Einzelbefunde ohnehin nur Hinweise, keine Beweise.

**Infrastruktur-Lernpunkt:** Thinking-Modelle (qwen3, gemma4) lieferten bei
kleinem num_predict leere Antworten (Denken frisst das Kontingent) — der
Simulator brach Gespraeche nach 1 Turn ab. Fix in ae97257: think=False fuer
den Simulator + Retry bei leerer Antwort.

## Rohdaten

## Eval-Ergebnisse

| Konfiguration | Modell | Runs | Erfolg (Checks) | Ziel erreicht (Judge) | Faithfulness | Dialog | Voice | Ø Turns | Ø Tokens in/out | Kosten $ | Turn-Latenz p50/p95 s | TTFT p50/p95 s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| auto-lokal-qwen | ollama/qwen3.6:35b-mlx | 6 | 83% | – | – | – | – | 6.3 | 27551/12757 | 0.0000 | 19.00/46.79 | 15.50/46.41 |
| auto-lokal-llama | ollama/llama3.2:3b | 6 | 67% | – | – | – | – | 5.5 | 15340/732 | 0.0000 | 1.51/2.96 | 1.29/2.77 |
| auto-lokal-qwen-mono | ollama/qwen3.6:35b-mlx | 6 | 83% | – | – | – | – | 4.8 | 14886/7398 | 0.0000 | 16.11/32.26 | 12.81/32.06 |
| auto-lokal-qwen-knapp | ollama/qwen3.6:35b-mlx | 6 | 67% | – | – | – | – | 5.2 | 13692/9569 | 0.0000 | 17.50/47.15 | 11.98/39.09 |
| auto-lokal-qwen-minimal | ollama/qwen3.6:35b-mlx | 6 | 67% | – | – | – | – | 5.3 | 17807/11600 | 0.0000 | 19.70/64.79 | 14.50/64.43 |

_Erfolg = alle deterministischen Checks bestanden. Judge-Werte 1–5 (Mittelwert), Ziel erreicht in % der Laeufe. Kosten sind Schaetzwerte auf Basis der Listenpreise._
## Ergebnisse pro Szenario

| Konfiguration | Szenario | Runs | Erfolg (Checks) | Ziel erreicht (Judge) | Ø Turns | TTFT p50 s | Ø Tokens in/out |
|---|---|---|---|---|---|---|---|
| auto-lokal-qwen | ent-musik-02 | 1 | 100% | – | 6.0 | 15.56 | 10891/8795 |
| auto-lokal-qwen | ent-musik-06 | 1 | 0% | – | 6.0 | 15.84 | 18950/7870 |
| auto-lokal-qwen | klima-scheibe-03 | 1 | 100% | – | 4.0 | 9.78 | 11726/7503 |
| auto-lokal-qwen | kombi-date-04 | 1 | 100% | – | 10.0 | 10.61 | 73798/16797 |
| auto-lokal-qwen | nav-stau-05 | 1 | 100% | – | 5.0 | 22.07 | 15486/15762 |
| auto-lokal-qwen | nav-stopp-01 | 1 | 100% | – | 7.0 | 24.86 | 34454/19817 |
| auto-lokal-llama | ent-musik-02 | 1 | 0% | – | 6.0 | 0.61 | 6211/234 |
| auto-lokal-llama | ent-musik-06 | 1 | 0% | – | 6.0 | 1.15 | 16346/615 |
| auto-lokal-llama | klima-scheibe-03 | 1 | 100% | – | 4.0 | 1.53 | 10692/566 |
| auto-lokal-llama | kombi-date-04 | 1 | 100% | – | 4.0 | 1.58 | 12298/641 |
| auto-lokal-llama | nav-stau-05 | 1 | 100% | – | 5.0 | 1.61 | 14775/716 |
| auto-lokal-llama | nav-stopp-01 | 1 | 100% | – | 8.0 | 1.75 | 31715/1619 |
| auto-lokal-qwen-mono | ent-musik-02 | 1 | 100% | – | 3.0 | 6.82 | 7753/3910 |
| auto-lokal-qwen-mono | ent-musik-06 | 1 | 100% | – | 6.0 | 15.93 | 23522/10461 |
| auto-lokal-qwen-mono | klima-scheibe-03 | 1 | 100% | – | 4.0 | 12.44 | 10296/6911 |
| auto-lokal-qwen-mono | kombi-date-04 | 1 | 0% | – | 4.0 | 6.03 | 14337/1728 |
| auto-lokal-qwen-mono | nav-stau-05 | 1 | 100% | – | 4.0 | 12.81 | 9367/5895 |
| auto-lokal-qwen-mono | nav-stopp-01 | 1 | 100% | – | 8.0 | 19.45 | 24039/15484 |
| auto-lokal-qwen-knapp | ent-musik-02 | 1 | 100% | – | 5.0 | 2.99 | 11025/5846 |
| auto-lokal-qwen-knapp | ent-musik-06 | 1 | 0% | – | 5.0 | 10.72 | 14186/3905 |
| auto-lokal-qwen-knapp | klima-scheibe-03 | 1 | 100% | – | 4.0 | 27.48 | 9905/8933 |
| auto-lokal-qwen-knapp | kombi-date-04 | 1 | 0% | – | 4.0 | 12.56 | 9725/4687 |
| auto-lokal-qwen-knapp | nav-stau-05 | 1 | 100% | – | 5.0 | 21.60 | 10757/8990 |
| auto-lokal-qwen-knapp | nav-stopp-01 | 1 | 100% | – | 8.0 | 39.09 | 26554/25053 |
| auto-lokal-qwen-minimal | ent-musik-02 | 1 | 100% | – | 4.0 | 4.43 | 6960/3222 |
| auto-lokal-qwen-minimal | ent-musik-06 | 1 | 0% | – | 6.0 | 19.66 | 17583/10674 |
| auto-lokal-qwen-minimal | klima-scheibe-03 | 1 | 100% | – | 4.0 | 11.46 | 8434/5674 |
| auto-lokal-qwen-minimal | kombi-date-04 | 1 | 0% | – | 5.0 | 7.43 | 14759/5248 |
| auto-lokal-qwen-minimal | nav-stau-05 | 1 | 100% | – | 5.0 | 19.85 | 11639/12793 |
| auto-lokal-qwen-minimal | nav-stopp-01 | 1 | 100% | – | 8.0 | 14.50 | 47468/31989 |
<details><summary>Fehlgeschlagene Checks</summary>

### auto-lokal-qwen / ent-musik-06 (Lauf 1)
- ❌ `tool_called:play_media` — play_media aufgerufen, aber: query='Helene Fischer Hit' != Muster '*atemlos*'

### auto-lokal-llama / ent-musik-02 (Lauf 1)
- ❌ `tool_called:play_media` — kein Aufruf von play_media

### auto-lokal-llama / ent-musik-06 (Lauf 1)
- ❌ `tool_called:play_media` — play_media aufgerufen, aber: query='Helene Fischer' != Muster '*atemlos*'

### auto-lokal-qwen-mono / kombi-date-04 (Lauf 1)
- ❌ `tool_called:set_temperature` — kein Aufruf von set_temperature

### auto-lokal-qwen-knapp / kombi-date-04 (Lauf 1)
- ❌ `tool_called:play_media` — play_media aufgerufen, aber: query='Chillout Musik' != Muster '*entspann*'
- ❌ `tool_called:set_temperature` — kein Aufruf von set_temperature

### auto-lokal-qwen-knapp / ent-musik-06 (Lauf 1)
- ❌ `tool_called:play_media` — play_media aufgerufen, aber: query='Helene Fischer' != Muster '*atemlos*'

### auto-lokal-qwen-minimal / kombi-date-04 (Lauf 1)
- ❌ `tool_called:play_media` — play_media aufgerufen, aber: query='Jazz' != Muster '*entspann*'

### auto-lokal-qwen-minimal / ent-musik-06 (Lauf 1)
- ❌ `tool_called:play_media` — play_media aufgerufen, aber: query='Helene Fischer' != Muster '*atemlos*'

</details>

