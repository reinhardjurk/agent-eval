"""Experiment-Runner: Konfiguration x Szenarien x Wiederholungen.

Jede Konversation wird als Langfuse-Trace erfasst (Turns, Agenten-Spans,
Generations, Tool-Calls) und anschliessend bewertet (Checks + Judge). Die
Ergebnisse landen als results.json + summary.md im Ausgabeverzeichnis.
"""

from __future__ import annotations

import copy
import json
import time
from pathlib import Path

from . import report
from .assistant import MultiAgentAssistant
from .config import ResolvedExperiment, Scenario, load_experiment, load_scenarios
from .evaluators import deterministic_checks, run_judge
from .llm import LLM, FakeLLM
from .mock_tools import MockToolRuntime
from .ollama_llm import is_ollama_model
from .simulator import UserSimulator
from .tracing import Tracer

FAKE_ASSISTANT_TEXT = ("Ich habe Ihr Anliegen aufgenommen und kuemmere mich darum. "
                       "Kann ich sonst noch etwas fuer Sie tun?")
FAKE_CUSTOMER_TEXT = "[DONE] Danke, das war alles."


def _build_llm(client, model: str, max_tokens: int, effort: str | None,
               fake: bool, fake_text: str, think: bool | None = None):
    """Provider-Weiche: "ollama/..." -> lokales Modell, sonst Claude API."""
    if fake:
        return FakeLLM(fake_text)
    if is_ollama_model(model):
        from .ollama_llm import OllamaLLM

        return OllamaLLM(model, max_tokens=max_tokens, think=think)
    return LLM(client, model, max_tokens=max_tokens, effort=effort)


def _make_llm_factory(client, exp: ResolvedExperiment, fake: bool):
    sampling = exp.config.sampling

    def make_llm(model: str):
        return _build_llm(client, model, sampling.max_tokens, sampling.effort,
                          fake, FAKE_ASSISTANT_TEXT)

    return make_llm


def run_conversation(exp: ResolvedExperiment, scenario: Scenario, rep: int, client,
                     tracer: Tracer, fake: bool, judge_enabled: bool) -> dict:
    runtime = MockToolRuntime(copy.deepcopy(exp.fixtures))
    if exp.config.assistant.type == "http" and not fake:
        from .http_assistant import HttpAssistant

        assistant = HttpAssistant(exp.config.assistant, runtime, tracer,
                                  model_label=exp.config.model)
    else:
        # fake erzwingt den eingebauten Pfad (Pipeline-Test ohne externe Systeme)
        assistant = MultiAgentAssistant(exp, _make_llm_factory(client, exp, fake),
                                        runtime, tracer)

    # Simulator: kleines Budget + think=False, damit Thinking-Modelle nicht das
    # gesamte Token-Kontingent verdenken und leere Antworten liefern
    sim_llm = _build_llm(client, exp.config.simulator.model, 600, None,
                         fake, FAKE_CUSTOMER_TEXT, think=False)
    simulator = UserSimulator(sim_llm, scenario, tracer)

    transcript: list[dict] = [{"role": "customer", "text": scenario.opening_message}]
    turn_latencies: list[float] = []
    ttfts: list[float] = []
    stats = {"calls": 0, "in": 0, "out": 0}
    user_msg = scenario.opening_message
    t0 = time.perf_counter()

    trace_name = f"{exp.config.id}/{scenario.id}#{rep}"
    metadata = {
        "config_id": exp.config.id,
        "model": exp.config.model,
        "assistant": exp.config.assistant.type,
        "scenario": scenario.id,
        "rep": rep,
        "customer_context": (exp.config.context.customer_context
                             if exp.config.context else "none"),
    }
    with tracer.conversation(trace_name, metadata=metadata,
                             tags=[exp.config.id, scenario.id],
                             input=scenario.opening_message):
        for _ in range(scenario.max_turns):
            turn = assistant.respond(user_msg)
            transcript.append({"role": "assistant", "text": turn.text})
            turn_latencies.append(turn.latency_s)
            if turn.ttft_s is not None:
                ttfts.append(turn.ttft_s)
            stats["calls"] += turn.api_calls
            stats["in"] += turn.input_tokens
            stats["out"] += turn.output_tokens

            reply, done = simulator.next_message(transcript)
            if reply:
                transcript.append({"role": "customer", "text": reply})
            if done or not reply:
                break
            user_msg = reply

        checks = deterministic_checks(scenario, transcript, runtime.calls)
        success = all(c["passed"] for c in checks)

        judge = None
        if judge_enabled and not fake and client is not None:
            judge = run_judge(client, exp.config.judge.model, scenario, transcript,
                              runtime.calls)

        tracer.score("checks_passed", 1.0 if success else 0.0)
        if judge:
            tracer.score("goal_achieved", 1.0 if judge["goal_achieved"] else 0.0,
                         comment=judge.get("comment"))
            for key in ("faithfulness", "conversation_quality", "voice_suitability"):
                tracer.score(key, float(judge[key]))
        tracer.update_trace_output(transcript[-1]["text"] if transcript else "")

    return {
        "scenario": scenario.id,
        "rep": rep,
        "success": success,
        "checks": checks,
        "judge": judge,
        "metrics": {
            "turns": len(turn_latencies),
            "api_calls": stats["calls"],
            "input_tokens": stats["in"],
            "output_tokens": stats["out"],
            "cost_usd": report.estimate_cost(exp.config.model, stats["in"], stats["out"]),
            "duration_s": round(time.perf_counter() - t0, 3),
            "turn_latencies": [round(v, 3) for v in turn_latencies],
            "ttfts": [round(v, 3) for v in ttfts],
        },
        "transcript": transcript,
        "tool_calls": [
            {"agent": c.agent, "tool": c.tool, "args": c.args, "result": c.result}
            for c in runtime.calls
        ],
    }


def run_experiment(config_path: str | Path, scenarios_path: str | Path,
                   reps: int | None = None, out_dir: str | Path | None = None,
                   fake: bool = False, judge_enabled: bool = True) -> Path:
    exp = load_experiment(Path(config_path))
    scenarios = load_scenarios(Path(scenarios_path))
    reps = reps or exp.config.repetitions

    if judge_enabled and is_ollama_model(exp.config.judge.model):
        print("[runner] Judge unterstuetzt nur Claude-Modelle – Judge wird uebersprungen. "
              "Setze judge.model auf ein Claude-Modell oder nutze --no-judge.")
        judge_enabled = False

    # Anthropic-Client nur, wenn mindestens eine Rolle ein Claude-Modell nutzt.
    client = None
    if not fake:
        models = [exp.config.simulator.model]
        if exp.config.assistant.type == "builtin":
            models.append(exp.config.model)
            models += [card.model or exp.config.model for card in exp.cards]
        if judge_enabled or any(not is_ollama_model(m) for m in models):
            import anthropic

            client = anthropic.Anthropic()

    tracer = Tracer(enabled=not fake)

    runs: list[dict] = []
    total = len(scenarios) * reps
    for scenario in scenarios:
        for rep in range(1, reps + 1):
            print(f"[{len(runs) + 1}/{total}] {exp.config.id} / {scenario.id} (Lauf {rep}) ...",
                  flush=True)
            result = run_conversation(exp, scenario, rep, client, tracer, fake, judge_enabled)
            status = "OK" if result["success"] else "FAIL"
            print(f"    -> {status}, {result['metrics']['turns']} Turns, "
                  f"{result['metrics']['input_tokens']}/{result['metrics']['output_tokens']} Tokens",
                  flush=True)
            runs.append(result)
    tracer.flush()

    out = Path(out_dir) if out_dir else Path("results") / exp.config.id
    out.mkdir(parents=True, exist_ok=True)
    payload = {"config": exp.config.model_dump(), "runs": runs}
    (out / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                      encoding="utf-8")

    summary = report.render_summary([payload]) + report.render_failures([payload])
    (out / "summary.md").write_text(summary, encoding="utf-8")
    report.append_step_summary(summary)
    print("\n" + summary)
    return out
