#!/usr/bin/env python3
"""Referenz-Server fuer den HTTP-Assistenten-Vertrag von agent-eval.

Zeigt minimal, was ein externer Assistent implementieren muss, und dient zum
Testen der Anbindung, bevor das echte System steht:

    python examples/http_assistant_stub.py 8089
    python -m agent_eval run --config configs/extern-http.yaml --reps 1 --no-judge

Der Stub haelt pro session_id eine Historie und meldet einen Demo-Tool-Call.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

SESSIONS: dict[str, list[str]] = {}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length))

        history = SESSIONS.setdefault(request["session_id"], [])
        history.append(request["message"])

        response = {
            "reply": f"Verstanden ({len(history)}. Nachricht dieser Sitzung): "
                     f"{request['message'][:80]}",
            "tool_calls": [
                {
                    "tool": "echo",
                    "args": {"text": request["message"][:40]},
                    "result": {"status": "ok"},
                    "agent": "stub",
                }
            ],
            "usage": {
                "input_tokens": sum(len(m.split()) for m in history),
                "output_tokens": 15,
            },
        }
        body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # kein Request-Log auf stderr
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8089
    print(f"Stub-Assistent lauscht auf http://localhost:{port}/chat (Strg+C beendet)")
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()
