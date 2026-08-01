"""Tests fuer Check-Semantik (ODER-Muster, result_ok) und Report-Statistik."""

from agent_eval.config import Scenario
from agent_eval.evaluators import deterministic_checks
from agent_eval.mock_tools import ToolCall
from agent_eval.report import wilson_interval


def _scenario(criteria: dict) -> Scenario:
    return Scenario(id="t", persona="p", goal="g", opening_message="o",
                    max_turns=5, success_criteria=criteria)


def _call(tool: str, args: dict, result: str = '{"status": "ok"}') -> ToolCall:
    return ToolCall(agent="a", tool=tool, args=args, result=result)


def _check(scenario, calls, name):
    return next(c for c in deterministic_checks(scenario, [], calls) if c["name"] == name)


def test_or_patterns_match_any():
    sc = _scenario({"tool_calls": [
        {"tool": "play_media", "with_args": {"query": ["*atemlos*", "*helene*"]}}]})
    # Interpret-Suche statt Titel: zweites Muster greift
    ok = _check(sc, [_call("play_media", {"query": "Helene Fischer"})],
                "tool_called:play_media")
    assert ok["passed"]
    # gar kein Treffer
    fail = _check(sc, [_call("play_media", {"query": "Beethoven"})],
                  "tool_called:play_media")
    assert not fail["passed"]


def test_single_pattern_still_works():
    sc = _scenario({"tool_calls": [
        {"tool": "create_complaint", "with_args": {"invoice_id": "R-2024-*"}}]})
    ok = _check(sc, [_call("create_complaint", {"invoice_id": "r-2024-002"})],
                "tool_called:create_complaint")
    assert ok["passed"]  # case-insensitiv


def test_result_ok_rejects_tool_errors():
    sc = _scenario({"tool_calls": [{"tool": "update_address", "with_args": {}}]})
    err_call = _call("update_address", {"customer_id": "KD-9999"},
                     result='{"error": "Kunde KD-9999 nicht gefunden."}')
    fail = _check(sc, [err_call], "tool_called:update_address")
    assert not fail["passed"]
    assert "Fehler" in fail["detail"]
    # spaeterer erfolgreicher Aufruf rettet den Check
    ok = _check(sc, [err_call, _call("update_address", {"customer_id": "KD-1001"})],
                "tool_called:update_address")
    assert ok["passed"]


def test_result_ok_false_checks_attempt_only():
    sc = _scenario({"tool_calls": [{"tool": "update_address", "result_ok": False}]})
    err_call = _call("update_address", {}, result='{"error": "kaputt"}')
    ok = _check(sc, [err_call], "tool_called:update_address")
    assert ok["passed"]


def test_wilson_interval():
    lo, hi = wilson_interval(5, 6)
    assert 0 < lo < 5 / 6 * 100 < hi < 100
    lo0, hi0 = wilson_interval(0, 6)
    assert lo0 == 0.0 and 0 < hi0 < 60
    assert wilson_interval(0, 0) == (0.0, 100.0)
