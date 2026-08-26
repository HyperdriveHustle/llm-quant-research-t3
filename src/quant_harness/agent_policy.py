from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from .model import ArkModelClient
from .tool_gateway import ModelUsage


@dataclass(frozen=True)
class PolicyTurn:
    action_text: str
    usage: ModelUsage
    response_id: str | None = None


class AgentPolicy(Protocol):
    def next_action(self, state_view: dict) -> PolicyTurn: ...


class GLMAgentPolicy:
    SYSTEM_PROMPT = """You are an autonomous quantitative factor researcher.
You control the research loop. Return exactly one JSON action and no markdown.

Allowed actions:
- propose: register a falsifiable hypothesis and initial Qlib formulas.
- evaluate: choose registered factor IDs and a permitted search window alias.
- refine: create child formulas from a registered parent factor.
- pivot: close/suspend a hypothesis and open a different mechanism.
- stop: either submit evidence-backed factors or conclude no_discovery.

Before propose/evaluate/refine/pivot, state expected_observation and decision_rule.
Never invent IDs. Use only IDs shown in state. Never request hidden/test data,
paths, URLs, code execution, shell, SQL or verifier access.
Evaluation truth comes only from Harness observations.
Reference factors under hypothesis_id hyp_seed_pool may be evaluated and used as
refine parents, but cannot be submitted unchanged. A submit must cite successful
Experiment IDs for every submitted non-reference Factor ID.
You may continue for a long trajectory; stop when evidence supports submission
or no supported discovery remains.

The common envelope is:
{"schema_version":"0.2","action_id":"unique-id","action":"...",
"reason":"...","hypothesis_id":"hyp_... when required",
"expected_observation":"required except stop",
"decision_rule":"required except stop","arguments":{...}}

propose arguments = {"hypothesis":{"title":"...","mechanism":"...",
"predicted_direction":1 or -1,"falsification_rule":"..."},
"candidates":[{"name":"...","expression":"Qlib formula",
"direction":1 or -1,"rationale":"..."}]}
evaluate arguments = {"factor_ids":["registered-id"],
"window_alias":"allowed alias"}
refine arguments = {"parent_factor_id":"registered-id",
"edit_type":"parameter|structural|normalization|interaction|ablation",
"change_summary":"...","candidates":[candidate objects]}
pivot arguments = {"from_hypothesis_id":"active-id",
"closure_status":"rejected|suspended|inconclusive","closure_reason":"...",
"new_hypothesis":hypothesis object,"candidates":[candidate objects]}
stop arguments = {"mode":"submit|no_discovery","factor_ids":[],
"evidence_ids":[],"limitations":["..."],"conclusion":"..."}"""

    def __init__(
        self,
        client: ArkModelClient,
        *,
        temperature: float,
        max_output_tokens: int | None = None,
    ):
        self.client = client
        self.temperature = float(temperature)
        self.max_output_tokens = max_output_tokens

    def next_action(self, state_view: dict) -> PolicyTurn:
        response = self.client.generate(
            system_prompt=self.SYSTEM_PROMPT,
            prompt=json.dumps(state_view, ensure_ascii=False, separators=(",", ":")),
            temperature=self.temperature,
            json_output=True,
            max_output_tokens=self.max_output_tokens,
        )
        return PolicyTurn(
            action_text=response.text,
            usage=ModelUsage(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                model_calls=response.attempts,
            ),
            response_id=response.response_id,
        )


class ScriptedPolicy:
    """Deterministic policy used by unit and smoke tests."""

    def __init__(self, actions: list[dict]):
        self.actions = list(actions)
        self.index = 0

    def next_action(self, state_view: dict) -> PolicyTurn:
        if self.index >= len(self.actions):
            raise RuntimeError("scripted policy exhausted")
        action = self.actions[self.index]
        self.index += 1
        return PolicyTurn(
            action_text=json.dumps(action),
            usage=ModelUsage(input_tokens=1, output_tokens=1),
            response_id=f"scripted_{self.index}",
        )
