"""Qualitaetsbewertung: deterministische Checks (Ground Truth aus dem Tool-Log)
und LLM-as-a-Judge mit fester Rubrik und strukturiertem Output."""

from __future__ import annotations

import fnmatch
import json
import re

from pydantic import BaseModel, Field

from .config import Scenario
from .mock_tools import ToolCall

# ------------------------------------------------------------ deterministisch


def _arg_matches(value, patterns) -> bool:
    """fnmatchcase auf lowercase: case-insensitiv und plattformunabhaengig.
    Eine Muster-Liste ist ODER-verknuepft (ein Treffer genuegt)."""
    candidates = patterns if isinstance(patterns, list) else [patterns]
    haystack = str(value).lower()
    return any(fnmatch.fnmatchcase(haystack, p.lower()) for p in candidates)


def _result_is_error(result: str) -> bool:
    try:
        parsed = json.loads(result)
    except (ValueError, TypeError):
        return False
    return isinstance(parsed, dict) and "error" in parsed


def deterministic_checks(scenario: Scenario, transcript: list[dict],
                         calls: list[ToolCall]) -> list[dict]:
    checks: list[dict] = []
    crit = scenario.success_criteria

    for expected in crit.tool_calls:
        matched = False
        detail = f"kein Aufruf von {expected.tool}"
        for call in calls:
            if call.tool != expected.tool:
                continue
            mismatches = [
                f"{key}={call.args.get(key)!r} != Muster {patterns!r}"
                for key, patterns in expected.with_args.items()
                if not _arg_matches(call.args.get(key, ""), patterns)
            ]
            if mismatches:
                detail = f"{expected.tool} aufgerufen, aber: {'; '.join(mismatches)}"
                continue
            if expected.result_ok and _result_is_error(call.result):
                detail = (f"{expected.tool} passend aufgerufen, aber das Tool lieferte "
                          f"einen Fehler: {call.result[:120]}")
                continue  # ein spaeterer Aufruf kann noch erfolgreich sein
            matched = True
            detail = f"{expected.tool} korrekt aufgerufen"
            break
        checks.append({"name": f"tool_called:{expected.tool}", "passed": matched,
                       "detail": detail})

    for forbidden in crit.forbidden_tools:
        hit = any(c.tool == forbidden for c in calls)
        checks.append({
            "name": f"tool_not_called:{forbidden}",
            "passed": not hit,
            "detail": "faelschlich aufgerufen" if hit else "ok",
        })

    assistant_text = " ".join(m["text"] for m in transcript if m["role"] == "assistant")
    for pattern in crit.assistant_mentions:
        found = re.search(pattern, assistant_text, re.IGNORECASE) is not None
        checks.append({
            "name": f"assistant_mentions:{pattern}",
            "passed": found,
            "detail": "gefunden" if found else "nicht im Assistententext gefunden",
        })

    checks.append({
        "name": "within_max_turns",
        "passed": sum(1 for m in transcript if m["role"] == "assistant") <= scenario.max_turns,
        "detail": f"max_turns={scenario.max_turns}",
    })
    return checks


# ------------------------------------------------------------------ LLM-Judge


class JudgeScores(BaseModel):
    goal_achieved: bool = Field(description="Wurde das Kundenanliegen vollstaendig erledigt?")
    faithfulness: int = Field(description="1-5: Sind alle Faktenaussagen des Assistenten durch "
                                          "Tool-Ergebnisse gedeckt? 5 = vollstaendig gedeckt, "
                                          "1 = klare Halluzination.")
    conversation_quality: int = Field(description="1-5: Gespraechsfuehrung — zielgerichtet, "
                                                  "keine unnoetigen Schleifen, gute Rueckfragen.")
    voice_suitability: int = Field(description="1-5: Eignung fuer Sprachausgabe — kurze Saetze, "
                                               "keine Aufzaehlungen/Sonderzeichen, aussprechbare "
                                               "Zahlen.")
    comment: str = Field(description="Kurze Begruendung, max. 3 Saetze.")


JUDGE_SYSTEM = """Du bist ein strenger Evaluator fuer Kundenservice-Dialoge eines SPRACH-Assistenten (Telefonie, Text-to-Speech).
Bewerte ausschliesslich anhand des Transkripts und des Tool-Logs. Das Tool-Log ist die Ground Truth:
jede Faktaussage des Assistenten (Betraege, Ticketnummern, Zusagen) muss durch ein Tool-Ergebnis gedeckt sein.
Sei kritisch: im Zweifel schlechter bewerten."""


def run_judge(client, model: str, scenario: Scenario, transcript: list[dict],
              calls: list[ToolCall]) -> dict | None:
    convo = "\n".join(
        f"{'Kunde' if m['role'] == 'customer' else 'Assistent'}: {m['text']}"
        for m in transcript
    )
    tool_log = "\n".join(
        f"- [{c.agent}] {c.tool}({c.args}) -> {c.result}" for c in calls
    ) or "(keine Tool-Aufrufe)"

    user = (
        f"# Szenario\nSetting: {scenario.setting}\nZiel des Kunden: {scenario.goal}\n"
        f"Persona: {scenario.persona}\n\n"
        f"# Transkript\n{convo}\n\n# Tool-Log (Ground Truth)\n{tool_log}"
    )
    try:
        response = client.messages.parse(
            model=model,
            max_tokens=1024,
            system=JUDGE_SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_format=JudgeScores,
        )
        parsed = response.parsed_output
        return parsed.model_dump() if parsed else None
    except Exception as exc:
        print(f"[judge] Bewertung fehlgeschlagen: {exc}")
        return None
