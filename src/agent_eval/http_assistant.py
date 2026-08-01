"""HTTP-Adapter: bindet einen extern laufenden Assistenten an den Runner an.

Der externe Assistent implementiert einen einzigen Endpoint (POST, JSON).
Referenzimplementierung: examples/http_assistant_stub.py

Request des Runners:
    {
      "session_id": "<uuid>",   // stabil pro Konversation; Server haelt den Zustand
      "message": "<Kundentext>",
      "turn": 1                 // 1-basierter Turn-Zaehler
    }

Erwartete Antwort:
    {
      "reply": "Antworttext",                                   // Pflicht
      "tool_calls": [                                           // optional
        {"tool": "create_complaint", "args": {...},
         "result": "{...}" | {...}, "agent": "billing"}
      ],
      "usage": {"input_tokens": 123, "output_tokens": 45},       // optional
      "ttft_s": 0.42                                             // optional
    }

Hinweise:
- "tool_calls" speist das Check-Log: ohne sie koennen tool-basierte
  Erfolgskriterien nicht bestehen (Transkript-Checks und Judge gehen trotzdem).
- "result" darf String oder Objekt sein; Objekte werden fuer die
  result_ok-Pruefung JSON-serialisiert (ein "error"-Schluessel gilt als Fehler).
- Latenz misst der Runner (Wandzeit des POST); ttft_s kann der Server melden,
  wenn er selbst streamt und es kennt — sonst bleibt TTFT leer.
"""

from __future__ import annotations

import json
import os
import time
import uuid

import httpx

from .assistant import TurnResult
from .config import AssistantConfig
from .mock_tools import MockToolRuntime, ToolCall
from .tracing import Tracer


class _UsageShim:
    """Minimales LLMResult-Aequivalent fuer tracer.generation().record()."""

    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class HttpAssistant:
    def __init__(self, cfg: AssistantConfig, runtime: MockToolRuntime, tracer: Tracer,
                 model_label: str = "extern"):
        self.url = cfg.url
        self.runtime = runtime
        self.tracer = tracer
        self.model_label = model_label
        self.session_id = str(uuid.uuid4())
        self.turn = 0
        headers = {}
        if cfg.auth_env and os.environ.get(cfg.auth_env):
            headers["Authorization"] = f"Bearer {os.environ[cfg.auth_env]}"
        self._client = httpx.Client(timeout=cfg.timeout_s, headers=headers)

    def respond(self, user_text: str) -> TurnResult:
        self.turn += 1
        payload = {"session_id": self.session_id, "message": user_text, "turn": self.turn}

        t0 = time.perf_counter()
        with self.tracer.generation("extern-assistant", self.model_label,
                                    input=user_text) as gen:
            response = self._client.post(self.url, json=payload)
            response.raise_for_status()
            data = response.json()
            usage = data.get("usage") or {}
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
            reply = str(data.get("reply", "")).strip() or "(keine Antwort)"
            gen.record(_UsageShim(input_tokens, output_tokens), output=reply)
        latency = time.perf_counter() - t0

        for tc in data.get("tool_calls") or []:
            if not isinstance(tc, dict) or not tc.get("tool"):
                continue
            result = tc.get("result", "")
            if not isinstance(result, str):
                result = json.dumps(result, ensure_ascii=False)
            call = ToolCall(agent=str(tc.get("agent", "extern")), tool=str(tc["tool"]),
                            args=dict(tc.get("args") or {}), result=result)
            self.runtime.calls.append(call)
            self.tracer.tool_call(call.agent, call.tool, call.args, call.result)

        ttft = data.get("ttft_s")
        return TurnResult(
            text=reply,
            latency_s=latency,
            ttft_s=float(ttft) if isinstance(ttft, (int, float)) else None,
            api_calls=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
