"""Tests fuer den Automotive-Szenario-Generator."""

from agent_eval.config import load_scenarios
from agent_eval.mock_tools import HANDLERS
from agent_eval.scenario_gen import BLUEPRINTS, generate, write_scenarios

ALL_DOMAINS = list(BLUEPRINTS)


def test_generate_count_and_schema(tmp_path):
    scenarios = generate(count=14, domains=ALL_DOMAINS, seed=1)
    assert len(scenarios) == 14
    paths = write_scenarios(scenarios, tmp_path)
    assert len(paths) == 14

    loaded = load_scenarios(tmp_path)
    assert len(loaded) == 14
    for scenario in loaded:
        assert scenario.opening_message.strip()
        assert scenario.success_criteria.tool_calls, scenario.id


def test_generated_tools_exist():
    scenarios = generate(count=30, domains=ALL_DOMAINS, seed=7)
    for data in scenarios:
        for check in data["success_criteria"]["tool_calls"]:
            assert check["tool"] in HANDLERS, f"unbekanntes Tool {check['tool']}"
        for tool in data["success_criteria"].get("forbidden_tools", []):
            assert tool in HANDLERS


def test_deterministic_with_seed():
    a = generate(count=10, domains=ALL_DOMAINS, seed=42)
    b = generate(count=10, domains=ALL_DOMAINS, seed=42)
    assert a == b
    c = generate(count=10, domains=ALL_DOMAINS, seed=43)
    assert a != c


def test_domain_filter():
    scenarios = generate(count=6, domains=["klima"], seed=3)
    assert all(s["id"].startswith("klima-") for s in scenarios)
