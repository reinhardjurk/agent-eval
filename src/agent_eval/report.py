"""Aggregation und Berichte: Markdown-Vergleichstabelle pro Konfiguration.

Wird lokal auf stdout ausgegeben und in GitHub Actions automatisch an
$GITHUB_STEP_SUMMARY angehaengt.
"""

from __future__ import annotations

import os
from statistics import mean

# USD pro 1M Tokens (Input, Output) — Stand 2026-06, laengster Praefix gewinnt.
PRICES: dict[str, tuple[float, float]] = {
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def price_for(model: str) -> tuple[float, float]:
    if model.startswith("ollama/"):
        return (0.0, 0.0)  # lokale Modelle: keine API-Kosten
    best = ""
    for prefix in PRICES:
        if model.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return PRICES.get(best, (5.0, 25.0))


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = price_for(model)
    return (input_tokens * p_in + output_tokens * p_out) / 1_000_000


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))
    return ordered[idx]


def _fmt(value, spec: str = ".2f") -> str:
    return "–" if value is None else format(value, spec)


def _pct(value) -> str:
    return "–" if value is None else f"{value:.0f}%"


def _judge_mean(runs: list[dict], key: str) -> float | None:
    vals = [r["judge"][key] for r in runs if r.get("judge")]
    if not vals:
        return None
    if isinstance(vals[0], bool):
        return 100.0 * sum(vals) / len(vals)
    return mean(vals)


def render_summary(payloads: list[dict]) -> str:
    lines = [
        "## Eval-Ergebnisse",
        "",
        "| Konfiguration | Modell | Runs | Erfolg (Checks) | Ziel erreicht (Judge) | Faithfulness | Dialog | Voice | Ø Turns | Ø Tokens in/out | Kosten $ | Turn-Latenz p50/p95 s | TTFT p50/p95 s |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for payload in payloads:
        cfg = payload["config"]
        runs = payload["runs"]
        if not runs:
            continue
        n = len(runs)
        judged = [r for r in runs if r.get("success") is not None]
        success = 100.0 * sum(1 for r in judged if r["success"]) / len(judged) if judged else None
        latencies = [lat for r in runs for lat in r["metrics"]["turn_latencies"]]
        ttfts = [t for r in runs for t in r["metrics"]["ttfts"]]
        tokens_in = [r["metrics"]["input_tokens"] for r in runs]
        tokens_out = [r["metrics"]["output_tokens"] for r in runs]
        cost = sum(r["metrics"]["cost_usd"] for r in runs)

        lines.append(
            f"| {cfg['id']} | {cfg['model']} | {n} "
            f"| {_pct(success)} "
            f"| {_pct(_judge_mean(runs, 'goal_achieved'))} "
            f"| {_fmt(_judge_mean(runs, 'faithfulness'))} "
            f"| {_fmt(_judge_mean(runs, 'conversation_quality'))} "
            f"| {_fmt(_judge_mean(runs, 'voice_suitability'))} "
            f"| {mean(r['metrics']['turns'] for r in runs):.1f} "
            f"| {mean(tokens_in):.0f}/{mean(tokens_out):.0f} "
            f"| {cost:.4f} "
            f"| {_fmt(percentile(latencies, 50))}/{_fmt(percentile(latencies, 95))} "
            f"| {_fmt(percentile(ttfts, 50))}/{_fmt(percentile(ttfts, 95))} |"
        )
    lines += [
        "",
        "_Erfolg = alle deterministischen Checks bestanden. Judge-Werte 1–5 (Mittelwert), "
        "Ziel erreicht in % der Laeufe. Kosten sind Schaetzwerte auf Basis der Listenpreise._",
        "",
    ]
    return "\n".join(lines)


def render_by_scenario(payloads: list[dict]) -> str:
    """Aufschluesselung Konfiguration x Szenario — zeigt, WO eine Konfiguration
    gewinnt oder verliert, statt nur des Gesamtdurchschnitts."""
    lines = [
        "## Ergebnisse pro Szenario",
        "",
        "| Konfiguration | Szenario | Runs | Erfolg (Checks) | Ziel erreicht (Judge) | Ø Turns | TTFT p50 s | Ø Tokens in/out |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for payload in payloads:
        cfg = payload["config"]
        by_scenario: dict[str, list[dict]] = {}
        for run in payload["runs"]:
            by_scenario.setdefault(run["scenario"], []).append(run)
        for scenario_id in sorted(by_scenario):
            runs = by_scenario[scenario_id]
            judged = [r for r in runs if r.get("success") is not None]
            success = (100.0 * sum(1 for r in judged if r["success"]) / len(judged)
                       if judged else None)
            ttfts = [t for r in runs for t in r["metrics"]["ttfts"]]
            lines.append(
                f"| {cfg['id']} | {scenario_id} | {len(runs)} "
                f"| {_pct(success)} "
                f"| {_pct(_judge_mean(runs, 'goal_achieved'))} "
                f"| {mean(r['metrics']['turns'] for r in runs):.1f} "
                f"| {_fmt(percentile(ttfts, 50))} "
                f"| {mean(r['metrics']['input_tokens'] for r in runs):.0f}"
                f"/{mean(r['metrics']['output_tokens'] for r in runs):.0f} |"
            )
    lines.append("")
    return "\n".join(lines)


def render_failures(payloads: list[dict]) -> str:
    lines: list[str] = []
    for payload in payloads:
        for run in payload["runs"]:
            failed = [c for c in run["checks"] if not c["passed"]]
            if not failed:
                continue
            lines.append(f"### {payload['config']['id']} / {run['scenario']} (Lauf {run['rep']})")
            for check in failed:
                lines.append(f"- ❌ `{check['name']}` — {check['detail']}")
            lines.append("")
    if not lines:
        return ""
    return "\n".join(["<details><summary>Fehlgeschlagene Checks</summary>", "", *lines,
                      "</details>", ""])


def append_step_summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")
