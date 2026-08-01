"""Ollama-Provider fuer lokale Modelle.

Implementiert dieselbe complete()-Schnittstelle wie LLM und uebersetzt zwischen
dem Anthropic-Message-Format (Content-Blocks, tool_use/tool_result) und dem
Ollama-Chat-Format (tool_calls, Rolle "tool").

Modellnamen tragen das Praefix "ollama/", z.B. "ollama/qwen3:14b".
Der Server wird ueber OLLAMA_HOST erreicht (Default: http://localhost:11434).
Benoetigt das Extra:  pip install -e ".[ollama]"
"""

from __future__ import annotations

import os
import time
import uuid
from types import SimpleNamespace

from .llm import LLMResult

PREFIX = "ollama/"


def is_ollama_model(model: str) -> bool:
    return model.startswith(PREFIX)


def _field(obj, name: str, default=None):
    """Ollama liefert je nach Version dicts oder Pydantic-Objekte."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def to_ollama_tools(tools: list[dict] | None) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools or []
    ]


def to_ollama_messages(system: str, messages: list, tool_names: dict[str, str]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}]
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        if m["role"] == "assistant":
            text = "".join(_field(b, "text", "") or "" for b in content
                           if _field(b, "type") == "text")
            calls = [
                {"function": {"name": _field(b, "name"),
                              "arguments": dict(_field(b, "input") or {})}}
                for b in content if _field(b, "type") == "tool_use"
            ]
            msg: dict = {"role": "assistant", "content": text}
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
        else:  # user-Turn mit tool_result-Blocks
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    out.append({
                        "role": "tool",
                        "tool_name": tool_names.get(b.get("tool_use_id", ""), "tool"),
                        "content": str(b.get("content", "")),
                    })
    return out


class OllamaLLM:
    def __init__(self, model: str, max_tokens: int = 1024, host: str | None = None,
                 think: bool | None = None):
        import ollama  # lazy: nur noetig, wenn wirklich ein ollama/-Modell laeuft

        self.model = model  # inkl. Praefix, fuer Tracing/Report
        self._name = model[len(PREFIX):] if model.startswith(PREFIX) else model
        self._client = ollama.Client(host=host or os.environ.get("OLLAMA_HOST"))
        self.max_tokens = max_tokens
        # think=False schaltet das interne Denken von Thinking-Modellen (qwen3,
        # gemma4, ...) ab — wichtig fuer Rollen mit kleinem Token-Budget, sonst
        # frisst das Denken das num_predict-Kontingent und der Text bleibt leer.
        # None = Flag nicht senden (Default des Modells).
        self.think = think
        self._tool_names: dict[str, str] = {}  # synthetische tool_use-IDs -> Tool-Name

    def complete(self, system: str, messages: list, tools: list | None = None) -> LLMResult:
        payload_msgs = to_ollama_messages(system, messages, self._tool_names)
        payload_tools = to_ollama_tools(tools) if tools else None
        options = {"num_predict": self.max_tokens}

        t0 = time.perf_counter()
        try:
            text, calls, tokens_in, tokens_out, ttft = self._run(
                payload_msgs, payload_tools, options, t0, self.think)
        except Exception:
            if self.think is None:
                raise
            # Modell/Server akzeptiert das think-Flag nicht -> dauerhaft weglassen
            self.think = None
            text, calls, tokens_in, tokens_out, ttft = self._run(
                payload_msgs, payload_tools, options, t0, None)
        latency = time.perf_counter() - t0

        blocks: list = []
        if text:
            blocks.append(SimpleNamespace(type="text", text=text))
        for call in calls:
            fn = _field(call, "function")
            name = _field(fn, "name") or "unknown"
            tool_id = f"call_{uuid.uuid4().hex[:8]}"  # Ollama kennt keine tool_use-IDs
            self._tool_names[tool_id] = name
            blocks.append(SimpleNamespace(type="tool_use", id=tool_id, name=name,
                                          input=dict(_field(fn, "arguments") or {})))

        message = SimpleNamespace(
            content=blocks or [SimpleNamespace(type="text", text="")],
            stop_reason="tool_use" if calls else "end_turn",
            usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out),
        )
        return LLMResult(message, latency, ttft, tokens_in, tokens_out)

    def _run(self, msgs, tools, options, t0, think):
        try:
            return self._stream(msgs, tools, options, t0, think)
        except Exception:
            # Aeltere Ollama-Versionen streamen nicht mit Tools -> blockierender Aufruf
            text, calls, tokens_in, tokens_out = self._blocking(msgs, tools, options, think)
            return text, calls, tokens_in, tokens_out, None

    def _stream(self, msgs, tools, options, t0, think):
        text_parts: list[str] = []
        calls: list = []
        tokens_in = tokens_out = 0
        ttft: float | None = None
        kwargs = {"model": self._name, "messages": msgs, "stream": True, "options": options}
        if tools:
            kwargs["tools"] = tools
        if think is not None:
            kwargs["think"] = think
        for chunk in self._client.chat(**kwargs):
            msg = _field(chunk, "message")
            delta = _field(msg, "content") or ""
            if delta:
                if ttft is None:
                    ttft = time.perf_counter() - t0
                text_parts.append(delta)
            calls.extend(_field(msg, "tool_calls") or [])
            if _field(chunk, "done"):
                tokens_in = _field(chunk, "prompt_eval_count") or 0
                tokens_out = _field(chunk, "eval_count") or 0
        return "".join(text_parts), calls, tokens_in, tokens_out, ttft

    def _blocking(self, msgs, tools, options, think=None):
        kwargs = {"model": self._name, "messages": msgs, "stream": False, "options": options}
        if tools:
            kwargs["tools"] = tools
        if think is not None:
            kwargs["think"] = think
        resp = self._client.chat(**kwargs)
        msg = _field(resp, "message")
        return (
            _field(msg, "content") or "",
            list(_field(msg, "tool_calls") or []),
            _field(resp, "prompt_eval_count") or 0,
            _field(resp, "eval_count") or 0,
        )
