"""Duenner LLM-Wrapper: Streaming-Aufruf mit Latenz-, TTFT- und Token-Messung.

FakeLLM liefert deterministische Antworten ohne API-Aufruf, damit der gesamte
Pipeline-Durchstich (Runner, Checks, Report, CI) ohne API-Key testbar ist.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from types import SimpleNamespace


@dataclass
class LLMResult:
    message: object          # anthropic Message (oder Fake-Aequivalent)
    latency_s: float
    ttft_s: float | None     # Zeit bis zum ersten Text-Delta innerhalb dieses Aufrufs
    input_tokens: int
    output_tokens: int


class LLM:
    def __init__(self, client, model: str, max_tokens: int = 1024, effort: str | None = None):
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort

    def complete(self, system: str, messages: list, tools: list | None = None) -> LLMResult:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}

        t0 = time.perf_counter()
        ttft: float | None = None
        with self.client.messages.stream(**kwargs) as stream:
            for event in stream:
                if (
                    ttft is None
                    and event.type == "content_block_delta"
                    and getattr(event.delta, "type", "") == "text_delta"
                ):
                    ttft = time.perf_counter() - t0
            message = stream.get_final_message()
        latency = time.perf_counter() - t0

        usage = message.usage
        input_tokens = (
            usage.input_tokens
            + (getattr(usage, "cache_read_input_tokens", 0) or 0)
            + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        )
        return LLMResult(message, latency, ttft, input_tokens, usage.output_tokens)


class FakeLLM:
    """Gibt immer denselben Text zurueck; keine Tool-Aufrufe, keine API."""

    def __init__(self, text: str, model: str = "fake-model"):
        self.text = text
        self.model = model

    def complete(self, system: str, messages: list, tools: list | None = None) -> LLMResult:
        message = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text)],
            stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=25, output_tokens=12),
        )
        return LLMResult(message, latency_s=0.01, ttft_s=0.005, input_tokens=25, output_tokens=12)


def extract_text(message) -> str:
    return "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
