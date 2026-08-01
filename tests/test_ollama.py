"""Tests fuer den Ollama-Formatadapter — rein lokal, ohne Server und ohne
ollama-Paket (die Uebersetzungsfunktionen sind pure functions)."""

from types import SimpleNamespace

from agent_eval.ollama_llm import is_ollama_model, to_ollama_messages, to_ollama_tools
from agent_eval.report import estimate_cost


def test_model_prefix():
    assert is_ollama_model("ollama/qwen3:14b")
    assert not is_ollama_model("claude-opus-5")


def test_tool_translation():
    tools = [{"name": "get_customer", "description": "Stammdaten",
              "input_schema": {"type": "object", "properties": {}}}]
    out = to_ollama_tools(tools)
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "get_customer"
    assert out[0]["function"]["parameters"] == {"type": "object", "properties": {}}


def test_message_translation_roundtrip():
    # Anthropic-Historie: User-Text, Assistant mit Text + tool_use, tool_result
    history = [
        {"role": "user", "content": "Hallo"},
        {"role": "assistant", "content": [
            SimpleNamespace(type="text", text="Moment bitte."),
            SimpleNamespace(type="tool_use", id="call_abc", name="get_customer",
                            input={"customer_id": "KD-1001"}),
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_abc", "content": '{"name": "Erika"}'},
        ]},
    ]
    out = to_ollama_messages("Systemprompt", history, tool_names={"call_abc": "get_customer"})

    assert out[0] == {"role": "system", "content": "Systemprompt"}
    assert out[1] == {"role": "user", "content": "Hallo"}
    assert out[2]["role"] == "assistant"
    assert out[2]["content"] == "Moment bitte."
    assert out[2]["tool_calls"][0]["function"]["name"] == "get_customer"
    assert out[2]["tool_calls"][0]["function"]["arguments"] == {"customer_id": "KD-1001"}
    assert out[3] == {"role": "tool", "tool_name": "get_customer",
                      "content": '{"name": "Erika"}'}


def test_ollama_models_are_free():
    assert estimate_cost("ollama/qwen3:14b", 100_000, 50_000) == 0.0
