"""High-level Agent orchestrator.

`Agent.run(input_payload)` performs:

1. Hash the canonical input.
2. Build the LLM call (system = prompt body; user = JSON-encoded input).
3. Call the LLM with retries / fallback.
4. Extract JSON from the model's response.
5. Validate against the agent's output schema.
6. Hash the output.
7. Route to a Lane via the trust-tier × materiality rules.
8. (Optional) Submit to the Approval Queue API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import structlog

from runtime.agent_loader import AgentSpec, load_agent
from runtime.config import Config, get_config
from runtime.hashing import hash_input, hash_output, hash_prompt
from runtime.json_extractor import JSONExtractionError, extract_json
from runtime.lane_router import LaneDecision, route_lane
from runtime.llm_client import LLMClient, LLMError, LLMResponse
from runtime.notifications import sentry as sentry_svc
from runtime.output_normalizer import normalize_artifact_output
from runtime.queue_client import QueueClient
from runtime.validator import validate_output

log = structlog.get_logger(__name__)


@dataclass
class AgentRun:
    agent_id: str
    agent_version: str
    prompt_version_hash: str
    model_used: str
    input_payload: dict[str, Any]
    input_hash: str
    output: dict[str, Any] | None
    output_hash: str | None
    raw_text: str
    validation_ok: bool
    validation_errors: list[str]
    lane_decision: LaneDecision | None
    latency_ms: int
    tokens_used: dict[str, int]
    fell_back: bool
    approval_id: str | None = None
    submitted_payload: dict[str, Any] | None = None
    error: str | None = None
    # Sprint-4 fix #9: track Anthropic prompt-cache stats per run.
    cache_used: bool = False
    cache_hit: bool = False
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        if self.lane_decision is not None:
            d["lane_decision"] = {
                "lane": self.lane_decision.lane,
                "tier": self.lane_decision.tier,
                "reasons": list(self.lane_decision.reasons),
                "confidence": self.lane_decision.confidence,
                "cost_impact_flag": self.lane_decision.cost_impact_flag,
                "schedule_impact_flag": self.lane_decision.schedule_impact_flag,
                "safety_flag": self.lane_decision.safety_flag,
            }
        return d


class Agent:
    """A single loaded agent prompt + its runtime adapters."""

    def __init__(
        self,
        agent_id: str,
        *,
        config: Config | None = None,
        llm: LLMClient | None = None,
        queue: QueueClient | None = None,
        spec: AgentSpec | None = None,
    ) -> None:
        self.config = config or get_config()
        self.spec = spec or load_agent(agent_id, config=self.config)
        self._llm = llm or LLMClient(self.config)
        self._queue = queue  # may be None if submit_to_queue is never used
        self._owns_queue = queue is None

    @property
    def agent_id(self) -> str:
        return self.spec.agent_id

    # ------------------------------------------------------------------
    def _select_model(self, override: str | None) -> str:
        if override:
            return override
        if self.config.default_model_override:
            return self.config.default_model_override
        return self.spec.default_model

    def _build_user_message(
        self, payload: dict[str, Any], context: dict[str, Any] | None
    ) -> str:
        if context:
            envelope = {"input": payload, "context": context}
        else:
            envelope = payload
        return json.dumps(envelope, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    async def run(
        self,
        input_payload: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
        submit_to_queue: bool = True,
        workflow: str | None = None,
        priority: str = "normal",
        required_approvers: list[str] | None = None,
        model_override: str | None = None,
        prompt_cache: bool = True,
    ) -> AgentRun:
        cfg = self.config
        spec = self.spec
        sentry_svc.tag_agent(spec.agent_id)
        prompt_hash = hash_prompt(spec.system_prompt)
        in_hash = hash_input(input_payload if context is None else {"input": input_payload, "context": context})
        model = self._select_model(model_override)

        user_msg = self._build_user_message(input_payload, context)

        run_kwargs = dict(
            agent_id=spec.agent_id,
            agent_version=spec.version,
            prompt_version_hash=prompt_hash,
            model_used=model,
            input_payload=input_payload,
            input_hash=in_hash,
            output=None,
            output_hash=None,
            raw_text="",
            validation_ok=False,
            validation_errors=[],
            lane_decision=None,
            latency_ms=0,
            tokens_used={"input": 0, "output": 0},
            fell_back=False,
            cache_used=False,
            cache_hit=False,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=0,
        )

        try:
            llm_resp: LLMResponse = await self._llm.call_llm(
                model=model,
                system=spec.system_prompt,
                user=user_msg,
                upgrade_model=spec.upgrade_model,
                prompt_cache=prompt_cache,
            )
        except LLMError as e:
            log.error("agent.run.llm_fail", agent_id=spec.agent_id, err=str(e))
            run_kwargs["error"] = f"llm_error: {e}"
            return AgentRun(**run_kwargs)

        run_kwargs["raw_text"] = llm_resp.text
        run_kwargs["model_used"] = llm_resp.model_used
        run_kwargs["latency_ms"] = llm_resp.latency_ms
        run_kwargs["tokens_used"] = {
            "input": llm_resp.input_tokens,
            "output": llm_resp.output_tokens,
        }
        run_kwargs["fell_back"] = llm_resp.fell_back
        run_kwargs["cache_used"] = getattr(llm_resp, "cache_used", False)
        run_kwargs["cache_hit"] = getattr(llm_resp, "cache_hit", False)
        run_kwargs["cache_creation_input_tokens"] = getattr(
            llm_resp, "cache_creation_input_tokens", 0
        )
        run_kwargs["cache_read_input_tokens"] = getattr(
            llm_resp, "cache_read_input_tokens", 0
        )

        try:
            output = extract_json(llm_resp.text)
        except JSONExtractionError as e:
            run_kwargs["error"] = f"json_extraction: {e}"
            return AgentRun(**run_kwargs)

        # Sprint 4 (KI G.4 #5): repair known-benign output quirks (summary
        # over-length, citation purpose→kind alias, evidence category case)
        # before schema validation so real bugs still fail loudly.
        output, normalizer_fixes = normalize_artifact_output(output)
        if normalizer_fixes:
            log.info(
                "agent.run.output_normalized",
                agent_id=spec.agent_id,
                fixes=normalizer_fixes,
            )
            run_kwargs["extra"] = {"normalizer_fixes": normalizer_fixes}

        ok, errors = validate_output(output, spec.schema)
        out_hash = hash_output(output)
        run_kwargs["output"] = output
        run_kwargs["output_hash"] = out_hash
        run_kwargs["validation_ok"] = ok
        run_kwargs["validation_errors"] = errors

        if not ok:
            log.warning(
                "agent.run.invalid_output",
                agent_id=spec.agent_id,
                errors=errors[:5],
            )
            run_kwargs["error"] = "schema_validation_failed"
            return AgentRun(**run_kwargs)

        decision = route_lane(
            output=output,
            trust_tier_default=spec.trust_tier_default,
            required_approvers=required_approvers,
        )
        run_kwargs["lane_decision"] = decision

        if not submit_to_queue:
            return AgentRun(**run_kwargs)

        # Build the queue submission payload
        submit_payload = {
            "agent_id": spec.agent_id,
            "agent_version": spec.version,
            "workflow": workflow or spec.agent_id,
            "lane": decision.lane,
            "priority": priority,
            "target_system": "none",
            "payload": output,
            "agent_confidence": decision.confidence,
            "agent_reasoning": "; ".join(decision.reasons),
            "agent_model": llm_resp.model_used,
            "agent_prompt_version": prompt_hash[:16],
            "agent_input_hash": in_hash,
            "agent_output_hash": out_hash,
            "required_approvers": required_approvers or (["owner", "partner"] if decision.lane == 3 else []),
        }
        run_kwargs["submitted_payload"] = submit_payload

        queue = self._queue or QueueClient(cfg)
        try:
            created = await queue.create_approval(submit_payload)
            run_kwargs["approval_id"] = created.get("id")
            log.info(
                "agent.run.submitted",
                agent_id=spec.agent_id,
                approval_id=run_kwargs["approval_id"],
                lane=decision.lane,
            )
        except Exception as e:  # noqa: BLE001
            log.error(
                "agent.run.submit_fail",
                agent_id=spec.agent_id,
                err=str(e),
            )
            run_kwargs["error"] = f"submit_error: {e}"
        finally:
            if self._owns_queue and self._queue is None:
                # We constructed it just-in-time above; close it.
                # (We didn't store it on self to keep Agent stateless across runs.)
                await queue.aclose()

        return AgentRun(**run_kwargs)


__all__ = ["Agent", "AgentRun"]
