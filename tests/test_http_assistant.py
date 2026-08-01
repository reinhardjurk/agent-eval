"""Tests fuer den HTTP-Adapter — gegen einen lokalen In-Process-Server."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agent_eval.config import AssistantConfig, load_experiment
from agent_eval.http_assistant import HttpAssistant
from agent_eval.mock_tools import MockToolRuntime
from agent_eval.tracing import Tracer

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RECEIVED: list[dict] = []


class _StubHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        RECEIVED.append({"path": self.path, "body": request,
                         "auth": self.headers.get("Authorization")})
        response = {
            "reply": f"Antwort auf: {request['message']}",
            "tool_calls": [
                {"tool": "create_complaint",
                 "args": {"invoice_id": "R-2024-002"},
                 "result": {"status": "angelegt", "ticket": "REKLA-0001"},
                 "agent": "extern-billing"},
                {"tool": "kaputt", "args": {}, "result": {"error": "nope"}},
            ],
            "usage": {"input_tokens": 42, "output_tokens": 7},
            "ttft_s": 0.33,
        }
        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def stub_url():
    RECEIVED.clear()
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/chat"
    server.shutdown()


def test_respond_maps_contract(stub_url, monkeypatch):
    monkeypatch.setenv("STUB_TOKEN", "geheim")
    cfg = AssistantConfig(type="http", url=stub_url, auth_env="STUB_TOKEN")
    runtime = MockToolRuntime({})
    assistant = HttpAssistant(cfg, runtime, Tracer(enabled=False), model_label="extern/x")

    turn = assistant.respond("Hallo, ich habe eine Reklamation.")

    assert turn.text.startswith("Antwort auf:")
    assert turn.input_tokens == 42 and turn.output_tokens == 7
    assert turn.ttft_s == 0.33 and turn.api_calls == 1
    # Tool-Log gefuellt, dict-Results serialisiert
    assert [c.tool for c in runtime.calls] == ["create_complaint", "kaputt"]
    assert json.loads(runtime.calls[0].result)["ticket"] == "REKLA-0001"
    # Request-Seite des Vertrags: session_id stabil, turn zaehlt, Bearer gesetzt
    assistant.respond("Zweite Nachricht")
    bodies = [r["body"] for r in RECEIVED]
    assert bodies[0]["turn"] == 1 and bodies[1]["turn"] == 2
    assert bodies[0]["session_id"] == bodies[1]["session_id"]
    assert RECEIVED[0]["auth"] == "Bearer geheim"


def test_http_config_loads():
    exp = load_experiment(ROOT / "configs" / "extern-http.yaml")
    assert exp.config.assistant.type == "http"
    assert exp.config.assistant.url
    assert exp.cards == [] and exp.concierge_prompt == ""


def test_http_config_requires_url(tmp_path):
    bad = tmp_path / "configs"
    bad.mkdir()
    (bad / "x.yaml").write_text(
        "id: x\nmodel: extern/x\nassistant:\n  type: http\n", encoding="utf-8")
    with pytest.raises(ValueError, match="assistant.url"):
        load_experiment(bad / "x.yaml")
