"""Smoke-Tests: validieren alle Konfigurationsartefakte und den kompletten
Pipeline-Durchstich im Fake-Modus (ohne API-Key, ohne Langfuse)."""

import json
from pathlib import Path

from agent_eval.config import load_experiment, load_scenarios
from agent_eval.runner import run_experiment

ROOT = Path(__file__).resolve().parent.parent


def test_all_configs_load():
    configs = sorted((ROOT / "configs").glob("*.yaml"))
    assert configs, "keine Konfigurationen gefunden"
    for config_path in configs:
        exp = load_experiment(config_path)
        if exp.config.assistant.type != "builtin":
            continue  # externe Assistenten brauchen keine Cards/Prompts
        assert exp.cards, config_path
        assert exp.concierge_prompt.strip()
        for card in exp.cards:
            assert exp.tools_by_agent[card.name], f"{card.name} hat keine Tools"


def test_all_scenarios_load():
    scenarios = load_scenarios(ROOT / "scenarios")
    assert len(scenarios) >= 3
    for scenario in scenarios:
        assert scenario.opening_message.strip()


def test_fake_run_end_to_end(tmp_path):
    out = run_experiment(
        ROOT / "configs" / "baseline.yaml",
        ROOT / "scenarios" / "rechnungs-reklamation.yaml",
        reps=1,
        out_dir=tmp_path,
        fake=True,
    )
    data = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert data["config"]["id"] == "baseline-opus5"
    assert len(data["runs"]) == 1
    run = data["runs"][0]
    assert "success" in run and "checks" in run and "metrics" in run
    assert run["metrics"]["turns"] >= 1
    assert (out / "summary.md").exists()
