"""Der Testkandidat: ein Multi-Agenten-Sprachassistent.

Architektur: ein Orchestrator ("Concierge") fuehrt das Kundengespraech und
delegiert fachliche Aufgaben per Tool-Call an Sub-Agenten. Jeder Sub-Agent ist
durch eine Agent Card definiert (Beschreibung, System-Prompt, Tool-Zugriff)
und fuehrt seine eigene Tool-Schleife gegen die Mock-MCP-Tools aus.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from .config import AgentCard, ResolvedExperiment
from .llm import extract_text
from .mock_tools import MockToolRuntime
from .tracing import Tracer

MAX_ORCHESTRATOR_ITERATIONS = 6
MAX_AGENT_ITERATIONS = 8


@dataclass
class TurnResult:
    text: str
    latency_s: float
    ttft_s: float | None
    api_calls: int
    input_tokens: int
    output_tokens: int


def _delegate_tool_name(card: AgentCard) -> str:
    return "delegate_to_" + card.name.replace("-", "_")


class MultiAgentAssistant:
    def __init__(self, exp: ResolvedExperiment, make_llm, runtime: MockToolRuntime,
                 tracer: Tracer):
        self.exp = exp
        self.runtime = runtime
        self.tracer = tracer
        self.messages: list = []

        self.orchestrator_llm = make_llm(exp.config.model)
        self.agent_llms = {c.name: make_llm(c.model or exp.config.model) for c in exp.cards}
        self.cards_by_tool = {_delegate_tool_name(c): c for c in exp.cards}

        self.context_block = self._customer_context_block()
        self.system = exp.concierge_prompt + self.context_block
        self.orch_tools = [
            {
                "name": _delegate_tool_name(card),
                "description": card.description,
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "Praezise Aufgabenbeschreibung inklusive aller "
                                           "bekannten Angaben (z.B. Kundennummer, Betraege).",
                        }
                    },
                    "required": ["task"],
                },
            }
            for card in exp.cards
        ]
        self.agent_tool_defs = {
            name: [t.to_anthropic() for t in tools]
            for name, tools in exp.tools_by_agent.items()
        }

    def _customer_context_block(self) -> str:
        mode = self.exp.config.context.customer_context
        if mode == "none":
            return ""
        customers = self.exp.fixtures.get("customers", {})
        if not customers:
            return ""
        first_id = next(iter(customers))
        if mode == "minimal":
            return f"\n\n# Anruferkontext\nDie Rufnummer des Anrufers ist dem Kundenkonto {first_id} zugeordnet."
        record = json.dumps(customers[first_id], ensure_ascii=False, indent=2)
        return f"\n\n# Anruferkontext\nKundendatensatz des Anrufers:\n{record}"

    # ------------------------------------------------------------------ turns

    def respond(self, user_text: str) -> TurnResult:
        self.messages.append({"role": "user", "content": user_text})
        t0 = time.perf_counter()
        self._stats = {"calls": 0, "in": 0, "out": 0}
        turn_ttft: float | None = None
        text = ""

        for _ in range(MAX_ORCHESTRATOR_ITERATIONS):
            call_start = time.perf_counter()
            with self.tracer.generation("orchestrator", self.orchestrator_llm.model,
                                        input=user_text) as gen:
                res = self.orchestrator_llm.complete(self.system, self.messages,
                                                     self.orch_tools or None)
                gen.record(res, output=extract_text(res.message))
            self._track(res)
            if turn_ttft is None and res.ttft_s is not None:
                turn_ttft = (call_start - t0) + res.ttft_s

            msg = res.message
            tool_uses = [b for b in msg.content if getattr(b, "type", "") == "tool_use"]
            self.messages.append({"role": "assistant", "content": msg.content})

            if msg.stop_reason == "tool_use" and tool_uses:
                results = []
                for tu in tool_uses:
                    card = self.cards_by_tool.get(tu.name)
                    if card is not None:
                        output = self._run_agent(card, dict(tu.input).get("task", ""))
                    else:
                        output = self.runtime.execute("concierge", tu.name, dict(tu.input))
                        self.tracer.tool_call("concierge", tu.name, dict(tu.input), output)
                    results.append({"type": "tool_result", "tool_use_id": tu.id,
                                    "content": output})
                self.messages.append({"role": "user", "content": results})
                continue

            text = extract_text(msg)
            break

        return TurnResult(
            text=text or "(keine Antwort)",
            latency_s=time.perf_counter() - t0,
            ttft_s=turn_ttft,
            api_calls=self._stats["calls"],
            input_tokens=self._stats["in"],
            output_tokens=self._stats["out"],
        )

    # ------------------------------------------------------------- sub-agents

    def _run_agent(self, card: AgentCard, task: str) -> str:
        llm = self.agent_llms[card.name]
        system = self.exp.card_prompts[card.name] + self.context_block
        tools = self.agent_tool_defs.get(card.name) or None
        messages: list = [{"role": "user", "content": task or "(keine Aufgabe uebergeben)"}]

        with self.tracer.span(f"agent:{card.name}", input=task):
            for _ in range(MAX_AGENT_ITERATIONS):
                with self.tracer.generation(card.name, llm.model, input=task) as gen:
                    res = llm.complete(system, messages, tools)
                    gen.record(res, output=extract_text(res.message))
                self._track(res)

                msg = res.message
                tool_uses = [b for b in msg.content if getattr(b, "type", "") == "tool_use"]
                if msg.stop_reason == "tool_use" and tool_uses:
                    messages.append({"role": "assistant", "content": msg.content})
                    results = []
                    for tu in tool_uses:
                        output = self.runtime.execute(card.name, tu.name, dict(tu.input))
                        self.tracer.tool_call(card.name, tu.name, dict(tu.input), output)
                        results.append({"type": "tool_result", "tool_use_id": tu.id,
                                        "content": output})
                    messages.append({"role": "user", "content": results})
                    continue
                return extract_text(msg) or "(keine Antwort des Agenten)"

        return "Der Agent konnte die Aufgabe nicht abschliessen."

    def _track(self, res):
        self._stats["calls"] += 1
        self._stats["in"] += res.input_tokens
        self._stats["out"] += res.output_tokens
