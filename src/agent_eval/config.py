"""Konfigurationsschemata und Lader.

Alle Pfade in YAML/JSON-Dateien sind relativ zur Projektwurzel (dem Verzeichnis,
das configs/, cards/, prompts/, mcp/, fixtures/ und scenarios/ enthaelt).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class SamplingConfig(BaseModel):
    max_tokens: int = 1024
    # output_config.effort; None = nicht setzen (Pflicht fuer Modelle ohne effort-Support, z.B. Haiku 4.5)
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None


class MCPSelection(BaseModel):
    server: str
    tools: list[str] | None = None  # None = alle Tools des Servers


class ContextConfig(BaseModel):
    system_prompt: str
    customer_context: Literal["none", "minimal", "full"] = "minimal"


class ModelRef(BaseModel):
    model: str = "claude-opus-5"


class ExperimentConfig(BaseModel):
    id: str
    model: str
    agents: list[str]
    mcp: list[MCPSelection]
    context: ContextConfig
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)
    simulator: ModelRef = Field(default_factory=ModelRef)
    judge: ModelRef = Field(default_factory=ModelRef)
    repetitions: int = 3


class ToolDef(BaseModel):
    name: str
    description: str
    input_schema: dict
    handler: str

    def to_anthropic(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class MCPServerConfig(BaseModel):
    name: str
    fixtures: str
    tools: list[ToolDef]


class AgentCard(BaseModel):
    name: str
    description: str
    system_prompt: str
    tools: list[str]
    model: str | None = None


class ToolCallCheck(BaseModel):
    tool: str
    with_args: dict[str, str] = Field(default_factory=dict)  # Werte sind fnmatch-Muster


class SuccessCriteria(BaseModel):
    tool_calls: list[ToolCallCheck] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    assistant_mentions: list[str] = Field(default_factory=list)  # Regex, case-insensitive


class Scenario(BaseModel):
    id: str
    persona: str
    goal: str
    constraints: str = ""
    opening_message: str
    max_turns: int = 10
    success_criteria: SuccessCriteria = Field(default_factory=SuccessCriteria)


@dataclass
class ResolvedExperiment:
    root: Path
    config: ExperimentConfig
    cards: list[AgentCard]
    card_prompts: dict[str, str]          # card.name -> Prompt-Text
    concierge_prompt: str
    tools_by_agent: dict[str, list[ToolDef]]
    fixtures: dict


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_experiment(config_path: Path) -> ResolvedExperiment:
    config_path = config_path.resolve()
    root = config_path.parent.parent
    cfg = ExperimentConfig(**_load_yaml(config_path))

    selected: dict[str, ToolDef] = {}
    fixtures: dict = {}
    for sel in cfg.mcp:
        server = MCPServerConfig(**_load_yaml(root / sel.server))
        fixtures = json.loads((root / server.fixtures).read_text(encoding="utf-8"))
        for tool in server.tools:
            if sel.tools is None or tool.name in sel.tools:
                selected[tool.name] = tool

    cards: list[AgentCard] = []
    card_prompts: dict[str, str] = {}
    tools_by_agent: dict[str, list[ToolDef]] = {}
    for card_path in cfg.agents:
        card = AgentCard(**json.loads((root / card_path).read_text(encoding="utf-8")))
        cards.append(card)
        card_prompts[card.name] = (root / card.system_prompt).read_text(encoding="utf-8")
        tools_by_agent[card.name] = [selected[n] for n in card.tools if n in selected]

    concierge = (root / cfg.context.system_prompt).read_text(encoding="utf-8")
    return ResolvedExperiment(
        root=root,
        config=cfg,
        cards=cards,
        card_prompts=card_prompts,
        concierge_prompt=concierge,
        tools_by_agent=tools_by_agent,
        fixtures=fixtures,
    )


def load_scenarios(path: Path) -> list[Scenario]:
    path = path.resolve()
    files = sorted(path.glob("*.yaml")) if path.is_dir() else [path]
    return [Scenario(**_load_yaml(f)) for f in files]
