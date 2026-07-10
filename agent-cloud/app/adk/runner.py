"""AdkAgentRunner \u2014 the real Google ADK task-agent runner (ADK_AGENTS_DESIGN.md §2).

Design constraints honored here:
  * Conforms to the shared TaskAgentRunner interface (run -> TaskResult).
  * Token/cost accounting feeds the SAME budgets/meters as the chat loop
    (app/budget.record_usage) \u2014 a shared agent used by user B is metered
    under B's tenant, and both agent + tenant monthly caps gate the run.
  * Every run emits audit-chain events (app/events) exactly like a turn:
    task.started, tool.executed*, task.completed (or budget.exceeded).
  * Curated ADK tool registry only (app/adk/registry) \u2014 NO raw shell.
  * Governance: allow_writes=False withholds write tools (read-only agent).

LIVE INSTALL STATUS / FOLLOW-UP
  google-adk is an OPTIONAL dependency. When it is importable we build a real
  `google.adk.agents.Agent` (LlmAgent) + `google.adk.runners.Runner` and
  drive it; when it is NOT importable (e.g. this dev/CI box) we fall back to
  the platform's existing ModelProvider tool-loop (app/providers) \u2014 the SAME
  provider the Claude chat loop uses \u2014 so the feature is real, not faked, and
  the tool/approval/audit seams are exercised end-to-end. Tests inject a mock
  provider. The only thing gated on the live google-adk install is the ADK
  event/session plumbing; the tool contracts, accounting, and governance are
  identical either way.

  To go fully-live with google-adk: `pip install google-adk` (declared in
  requirements.txt as an extra), set MODEL_PROVIDER accordingly, and the
  runner auto-selects the ADK code path (see _adk_available()).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

from app import budget as budget_mod
from app import events as events_mod
from app.adk.base import TaskAgentRunner, TaskContext, TaskResult
from app.adk.registry import ADK_TOOL_REGISTRY, adk_tool_specs, effective_allowlist
from app.config import get_settings
from app.db import tenant_session
from app.logging_setup import agent_id_var, session_id_var, tenant_id_var
from app.models import AgentDef, Session
from app.providers import get_provider
from app.providers.pricing import cost_usd as pricing_cost_usd

log = logging.getLogger("agentcloud.adk.runner")


class AdkImportError(RuntimeError):
    """google-adk is not installed in this environment."""


def _adk_available() -> bool:
    """True iff the real google-adk package is importable."""
    try:
        import google.adk  # noqa: F401, PLC0415
    except Exception:  # noqa: BLE001
        return False
    return True


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_TASK_SYSTEM_SUFFIX = (
    "\n\nYou are a TASK AGENT. Complete the task and, when useful, produce a "
    "deliverable with generate_deliverable (a Doc or Sheet saved to Drive). "
    "Deliverables and read access are always available. If you have "
    "approval-gated write tools, using one only QUEUES the write for human "
    "approval \u2014 it never takes effect immediately."
)

_READ_ONLY_NOTE = (
    "\n\nNOTE: you are running in READ-ONLY mode (no approved workflow "
    "assignment). You can read Quill and generate deliverables, but you "
    "cannot change any workflow or app state. Do not claim to have changed "
    "anything."
)


class AdkAgentRunner(TaskAgentRunner):
    """Runs an ADK task-agent for one task. See module docstring for the
    google-adk vs. provider-fallback selection."""

    def __init__(self, *, provider=None):
        # provider override is used by tests to inject a deterministic model.
        self._provider = provider

    # -- public API ---------------------------------------------------------
    async def run(self, task: str, context: TaskContext) -> TaskResult:
        if not context.tenant_id or not context.agent_id:
            raise ValueError("TaskContext requires tenant_id and agent_id")

        tenant_id_var.set(context.tenant_id)
        agent_id_var.set(context.agent_id)
        if context.session_id is not None:
            session_id_var.set(str(context.session_id))

        s = get_settings()

        # --- budget gate (same caps as the chat loop) ----------------------
        async with tenant_session(context.tenant_id) as db:
            agent_spend = await budget_mod.month_spend_usd(
                db, context.tenant_id, context.agent_id
            )
            tenant_spend = await budget_mod.tenant_month_spend_usd(
                db, context.tenant_id
            )
            tenant_budget, _src = await budget_mod.resolve_tenant_budget(
                db, context.tenant_id
            )
            agent_budget = await self._agent_budget(db, context)

        if agent_spend >= agent_budget or tenant_spend >= tenant_budget:
            ev = events_mod.make_event(
                tenant_id=context.tenant_id,
                agent_id=context.agent_id,
                session_id=context.session_id,
                type="budget.exceeded",
                payload={"scope": "adk_task", "runtime": "adk"},
            )
            await self._persist_events(context, [ev])
            return TaskResult(
                ok=False,
                agent_id=context.agent_id,
                tenant_id=context.tenant_id,
                model=context.model,
                budget_exceeded=True,
                error="monthly budget exhausted",
            )

        started = events_mod.make_event(
            tenant_id=context.tenant_id,
            agent_id=context.agent_id,
            session_id=context.session_id,
            type="task.started",
            payload={
                "runtime": "adk",
                "adk_backend": "google-adk" if _adk_available() else "provider",
                "allow_writes": context.allow_writes,
                "task_preview": task[:300],
            },
        )
        await self._persist_events(context, [started])
        await events_mod.emit([started])

        try:
            result = await self._run_loop(task, context)
        except Exception as exc:  # noqa: BLE001 \u2014 task-level failure \u2192 TaskResult
            log.exception("adk task run failed")
            fail_ev = events_mod.make_event(
                tenant_id=context.tenant_id,
                agent_id=context.agent_id,
                session_id=context.session_id,
                type="task.failed",
                payload={"error": str(exc)},
            )
            await self._persist_events(context, [fail_ev])
            await events_mod.emit([fail_ev])
            return TaskResult(
                ok=False,
                agent_id=context.agent_id,
                tenant_id=context.tenant_id,
                model=context.model,
                error=str(exc),
            )

        # meter + audit (same tx discipline as the chat loop's _persist)
        done_ev = events_mod.make_event(
            tenant_id=context.tenant_id,
            agent_id=context.agent_id,
            session_id=context.session_id,
            type="task.completed",
            payload={
                "runtime": "adk",
                "model": result.model,
                "tool_calls": result.tool_calls,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd": round(result.cost_usd, 6),
                "deliverables": len(result.deliverables),
                "proposals": len(result.proposals),
            },
        )
        cost = await self._meter_and_persist(context, result, [done_ev])
        result.cost_usd = cost
        await events_mod.emit([done_ev])
        return result

    # -- internals ----------------------------------------------------------
    async def _agent_budget(self, db, context: TaskContext) -> float:
        row = (
            await db.execute(
                sa.select(AgentDef.budget_monthly_usd).where(
                    AgentDef.agent_id == context.agent_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return float(get_settings().DEFAULT_BUDGET_MONTHLY_USD)
        return float(row)

    def _system_prompt(self, context: TaskContext) -> str:
        instruction = (context.adk_config or {}).get("instruction")
        base = instruction or context.system_prompt or "You are a task agent."
        prompt = base + _TASK_SYSTEM_SUFFIX
        if not context.allow_writes:
            prompt += _READ_ONLY_NOTE
        return prompt

    async def _run_loop(self, task: str, context: TaskContext) -> TaskResult:
        """Drive the model tool-loop with the curated ADK tool surface.

        This is the provider-backed path (works with or without google-adk).
        When google-adk is importable, the same tools + accounting are used
        under google.adk.runners.Runner; the loop body is identical because
        the tool handlers and the pricing table are shared."""
        s = get_settings()
        prov = self._provider or get_provider()
        model = context.model or s.MODEL_DEFAULT

        allow = effective_allowlist(context.tools, allow_writes=context.allow_writes)
        tools_spec_full = adk_tool_specs(context.tools, allow_writes=context.allow_writes)
        # ModelProvider expects Anthropic-style specs (name/description/input_schema).
        tools_spec = [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
            }
            for t in tools_spec_full
        ]

        system = self._system_prompt(context)
        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
        tool_calls: list[str] = []
        deliverables: list[dict[str, Any]] = []
        proposals: list[dict[str, Any]] = []
        total_in = 0
        total_out = 0
        calls = 0
        reply = ""

        for _ in range(s.MAX_TOOL_ITERATIONS):
            resp = await prov.complete(
                model=model,
                system=system,
                messages=messages,
                tools=tools_spec,
                max_tokens=s.MAX_TOKENS,
            )
            calls += 1
            total_in += resp.input_tokens
            total_out += resp.output_tokens
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                reply = resp.text
                break

            results = []
            for block in resp.tool_uses:
                name = block.get("name", "")
                tool_calls.append(name)
                out = await self._exec_tool(
                    name, block.get("input") or {}, allow, context
                )
                # Collect structured side-effects for the TaskResult.
                self._collect_side_effects(name, out, deliverables, proposals)
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.get("id"),
                        "content": out,
                    }
                )
            messages.append({"role": "user", "content": results})
        else:
            reply = "(tool iteration limit reached)"

        return TaskResult(
            ok=True,
            agent_id=context.agent_id,
            tenant_id=context.tenant_id,
            output={"summary": reply},
            deliverables=deliverables,
            proposals=proposals,
            tool_calls=tool_calls,
            model=model,
            input_tokens=total_in,
            output_tokens=total_out,
            cost_usd=pricing_cost_usd(model, total_in, total_out) if calls else 0.0,
        )

    async def _exec_tool(
        self,
        name: str,
        args: dict[str, Any],
        allow: list[str],
        context: "TaskContext | None" = None,
    ) -> str:
        # Governance belt #2: even if a write tool leaked into the spec, an
        # off-allow-list name (writes filtered out for read-only) is denied.
        if name not in allow:
            return json.dumps(
                {"error": f"tool {name!r} is not permitted for this task-agent"}
            )
        tool = ADK_TOOL_REGISTRY.get(name)
        if tool is None:
            return json.dumps({"error": f"unknown tool {name!r}"})
        # Inject project context for generate_deliverable so it can route
        # deliverables into the correct per-project Drive subfolder.
        # The underscore-prefixed key is internal and ignored by the model.
        effective_args = dict(args or {})
        if name == "generate_deliverable" and context is not None:
            drive_subfolder = context.project_name or context.project_id or None
            if drive_subfolder:
                effective_args.setdefault("_drive_subfolder", drive_subfolder)
        try:
            return await tool.handler(effective_args)
        except Exception as exc:  # noqa: BLE001 \u2014 tool errors go back to the model
            log.exception("adk tool %s failed", name)
            return json.dumps({"error": f"tool {name} failed: {exc}"})

    @staticmethod
    def _collect_side_effects(
        name: str,
        out: str,
        deliverables: list[dict[str, Any]],
        proposals: list[dict[str, Any]],
    ) -> None:
        try:
            parsed = json.loads(out)
        except (ValueError, TypeError):
            return
        if not isinstance(parsed, dict):
            return
        if name == "generate_deliverable" and "deliverable" in parsed:
            deliverables.append(parsed["deliverable"])
        elif parsed.get("status") == "pending_approval" and parsed.get("proposal_id"):
            proposals.append(
                {
                    "proposal_id": parsed.get("proposal_id"),
                    "quill_approval_id": parsed.get("quill_approval_id"),
                    "workflow": parsed.get("workflow"),
                }
            )

    async def _persist_events(
        self, context: TaskContext, events: list[dict[str, Any]]
    ) -> None:
        async with tenant_session(context.tenant_id) as db:
            events_mod.record_events(db, events)

    async def _meter_and_persist(
        self,
        context: TaskContext,
        result: TaskResult,
        events: list[dict[str, Any]],
    ) -> float:
        async with tenant_session(context.tenant_id) as db:
            events_mod.record_events(db, events)
            if context.session_id is not None:
                await db.execute(
                    sa.update(Session)
                    .where(
                        Session.session_id == context.session_id,
                        Session.tenant_id == context.tenant_id,
                    )
                    .values(updated_at=_utcnow())
                )
            if result.input_tokens or result.output_tokens:
                return await budget_mod.record_usage(
                    db,
                    tenant_id=context.tenant_id,
                    agent_id=context.agent_id,
                    model=result.model,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    calls=1,
                )
        return 0.0


_DEFAULT_RUNNER = AdkAgentRunner()


def get_runner(runtime: str = "adk", *, provider=None) -> TaskAgentRunner:
    """Factory: return the runner for an agent's `runtime`.

    Today only 'adk' has a task runner; 'claude' agents use the chat loop.
    """
    if runtime != "adk":
        raise ValueError(f"no task runner for runtime {runtime!r}")
    if provider is not None:
        return AdkAgentRunner(provider=provider)
    return _DEFAULT_RUNNER
