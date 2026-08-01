"""Judge-Betrieb und Kalibrierung.

Drei Werkzeuge rund um den LLM-Judge:

1. judge_results():  Judge NACHTRAEGLICH auf gespeicherte Laeufe anwenden —
   Konversationen muessen nicht neu gefahren werden (wichtig fuer teure lokale
   Laeufe, die ohne API-Key entstanden sind).
2. write_label_template():  YAML-Vorlage fuer manuelle Annotation erzeugen.
3. calibrate():  manuelle Labels gegen die Judge-Scores stellen — Übereinstimmung
   bei goal_achieved, mittlerer absoluter Fehler und Bias der 1-5-Skalen.
   Erst wenn diese Werte akzeptabel sind, sollte man Judge-Zahlen trauen.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean

import yaml

from . import report
from .config import load_scenarios
from .evaluators import run_judge
from .mock_tools import ToolCall

SCALE_FIELDS = ["faithfulness", "conversation_quality", "voice_suitability"]


def _run_key(run: dict) -> str:
    return f"{run['scenario']}#{run['rep']}"


def _render_transcript(run: dict) -> str:
    return "\n".join(
        f"{'Kunde' if m['role'] == 'customer' else 'Assistent'}: {m['text']}"
        for m in run["transcript"]
    )


def judge_results(results_path: Path, scenarios_path: Path, model: str | None = None) -> int:
    """Bewertet alle Laeufe einer results.json und schreibt sie (samt summary.md) zurueck."""
    import anthropic

    results_path = Path(results_path)
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    scenarios = {s.id: s for s in load_scenarios(Path(scenarios_path))}
    client = anthropic.Anthropic()
    model = model or (payload["config"].get("judge") or {}).get("model") or "claude-opus-5"

    judged = 0
    for run in payload["runs"]:
        scenario = scenarios.get(run["scenario"])
        if scenario is None:
            print(f"[judge] Szenario {run['scenario']} nicht in {scenarios_path} – uebersprungen")
            continue
        calls = [ToolCall(agent=c["agent"], tool=c["tool"], args=c["args"], result=c["result"])
                 for c in run["tool_calls"]]
        result = run_judge(client, model, scenario, run["transcript"], calls)
        if result is not None:
            run["judge"] = result
            judged += 1

    results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    summary = report.render_summary([payload]) + report.render_failures([payload])
    (results_path.parent / "summary.md").write_text(summary, encoding="utf-8")
    print(f"[judge] {judged}/{len(payload['runs'])} Laeufe mit {model} bewertet -> "
          f"{results_path} aktualisiert\n")
    print(summary)
    return judged


def write_label_template(results_path: Path, out_path: Path) -> Path:
    """Erzeugt eine YAML-Vorlage: pro Lauf das Transkript plus leere Bewertungsfelder."""
    payload = json.loads(Path(results_path).read_text(encoding="utf-8"))
    entries = [
        {
            "run": _run_key(run),
            "transcript": _render_transcript(run),
            "goal_achieved": None,          # true/false eintragen
            "faithfulness": None,           # 1-5
            "conversation_quality": None,   # 1-5
            "voice_suitability": None,      # 1-5
        }
        for run in payload["runs"]
    ]
    out_path = Path(out_path)
    out_path.write_text(yaml.safe_dump(entries, allow_unicode=True, sort_keys=False,
                                       width=100), encoding="utf-8")
    print(f"[label] Vorlage mit {len(entries)} Laeufen: {out_path}\n"
          f"        Felder ausfuellen, dann: python -m agent_eval calibrate "
          f"--results {results_path} --labels {out_path}")
    return out_path


def calibrate(results_path: Path, labels_path: Path) -> dict:
    """Vergleicht manuelle Labels mit den Judge-Scores derselben Laeufe."""
    payload = json.loads(Path(results_path).read_text(encoding="utf-8"))
    labels = yaml.safe_load(Path(labels_path).read_text(encoding="utf-8")) or []
    runs_by_key = {_run_key(r): r for r in payload["runs"]}

    pairs = []
    for entry in labels:
        run = runs_by_key.get(entry.get("run", ""))
        if run and run.get("judge"):
            pairs.append((entry, run["judge"]))

    stats: dict = {"paare": len(pairs)}

    goal = [(bool(e["goal_achieved"]), bool(j["goal_achieved"]))
            for e, j in pairs if e.get("goal_achieved") is not None]
    if goal:
        agree = sum(1 for human, judge in goal if human == judge)
        stats["goal_achieved"] = {"n": len(goal), "uebereinstimmung_pct":
                                  round(100 * agree / len(goal), 1)}

    for field in SCALE_FIELDS:
        vals = [(float(e[field]), float(j[field]))
                for e, j in pairs if e.get(field) is not None]
        if vals:
            stats[field] = {
                "n": len(vals),
                "mae": round(mean(abs(h - j) for h, j in vals), 2),
                "bias": round(mean(j - h for h, j in vals), 2),  # >0: Judge zu milde
            }

    print(f"[calibrate] {stats['paare']} Laeufe mit Label UND Judge-Score verglichen")
    if "goal_achieved" in stats:
        g = stats["goal_achieved"]
        print(f"  goal_achieved:        {g['uebereinstimmung_pct']} % Uebereinstimmung "
              f"(n={g['n']})")
    for field in SCALE_FIELDS:
        if field in stats:
            s = stats[field]
            print(f"  {field:21s} MAE={s['mae']}  Bias={s['bias']:+.2f} (n={s['n']}) "
                  f"{'(Judge milder als Mensch)' if s['bias'] > 0 else ''}")
    if not goal and not any(f in stats for f in SCALE_FIELDS):
        print("  Keine ausgefuellten Labels gefunden – Felder in der YAML eintragen.")
    return stats
