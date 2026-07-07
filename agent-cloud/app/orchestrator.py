"""Tenant-scoped agent chat loop (the platform core).

Flow per turn:
  tx1 (tenant GUC pinned): provision tenant + seed agents, load agent
       definition, load/create session, load history, read month spend.
  [no DB connection held]  model tool-loop via the configured provider,
       allow-list-enforced tool execution, usage accumulation.
  tx2 (tenant GUC pinned): persist turns, upsert usage row, touch session.

Budget: hard monthly cap from the agent definition. Exceeding it returns a
polite refusal (budget_exceeded=True) — never a silent failure, and never a
model call.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite

from app import budget as budget_mod
from app import memory as memory_mod
from app.config import get_settings
from app.db import tenant_session
from app.logging_setup import agent_id_var, session_id_var, tenant_id_var
from app.models import AgentDef, Message, Session, Tenant
from app.providers import ModelProvider, get_provider
from app.seeds import SEED_AGENTS, seed_model_for_tenant
from app.tools import (
    MEMORY_TOOL_NAMES,
    ToolNotAllowedError,
    run_tool,
    specs_for_allowlist,
)

log = logging.getLogger("agentcloud.orchestrator")


class UnknownAgentError(LookupError):
    pass


class AgentDisabledError(PermissionError):
    pass


class SessionNotFoundError(LookupError):
    pass


@dataclass
class ChatResult:
    session_id: uuid.UUID
    reply: str
    tool_calls: list[str]
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    budget_exceeded: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": str(self.session_id),
            "reply": self.reply,
            "tool_calls": self.tool_calls,
            "model": self.model,
            "usage": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cost_usd": round(self.cost_usd, 6),
            },
            "budget_exceeded": self.budget_exceeded,
        }


@dataclass
class _TurnContext:
    session_id: uuid.UUID
    model: str
    system_prompt: str
    allowlist: list[str]
    budget_monthly_usd: float
    month_spend_usd: float
    memory_policy: str = "off"
    history: list[dict[str, Any]] = field(default_factory=list)


def _insert_ignore(model_cls, values: dict[str, Any], dialect: str):
    if dialect == "postgresql":
        return postgresql.insert(model_cls).values(**values).on_conflict_do_nothing()
    return sqlite.insert(model_cls).values(**values).on_conflict_do_nothing()


async def _prepare(
    tenant_id: str, agent_id: str, session_id: uuid.UUID | None, message: str
) -> _TurnContext:
    s = get_settings()
    async with tenant_session(tenant_id) as db:
        dialect = db.bind.dialect.name if db.bind is not None else "sqlite"

        # Provision tenant + seed the two standard agent definitions.
        await db.execute(_insert_ignore(Tenant, {"tenant_id": tenant_id}, dialect))
        seed_model = seed_model_for_tenant(tenant_id)
        for seed in SEED_AGENTS:
            await db.execute(
                _insert_ignore(
                    AgentDef,
                    {
                        "tenant_id": tenant_id,
                        "agent_id": seed.agent_id,
                        "system_prompt": seed.system_prompt.format(tenant_id=tenant_id),
                        "model": seed_model,
                        "tools": list(seed.tools),
                        "budget_monthly_usd": s.DEFAULT_BUDGET_MONTHLY_USD,
                        "enabled": True,
                        "memory_policy": seed.memory_policy,
                    },
                    dialect,
                )
            )

        agent = (
            await db.execute(
                sa.select(AgentDef).where(
                    AgentDef.tenant_id == tenant_id, AgentDef.agent_id == agent_id
                )
            )
        ).scalar_one_or_none()
        if agent is None:
            raise UnknownAgentError(
                f"agent {agent_id!r} is not defined for this tenant"
            )
        if not agent.enabled:
            raise AgentDisabledError(f"agent {agent_id!r} is disabled")

        # Session: only ever load WHERE tenant_id AND agent_id match (app-layer
        # scoping; RLS is the second belt underneath).
        if session_id is not None:
            sess = (
                await db.execute(
                    sa.select(Session).where(
                        Session.session_id == session_id,
                        Session.tenant_id == tenant_id,
                        Session.agent_id == agent_id,
                    )
                )
            ).scalar_one_or_none()
            if sess is None:
                raise SessionNotFoundError("session not found for this tenant/agent")
            sid = sess.session_id
        else:
            sid = uuid.uuid4()
            db.add(Session(session_id=sid, tenant_id=tenant_id, agent_id=agent_id))

        rows = (
            await db.execute(
                sa.select(Message.role, Message.content)
                .where(Message.tenant_id == tenant_id, Message.session_id == sid)
                .order_by(Message.message_id)
            )
        ).all()
        history = [{"role": r.role, "content": r.content} for r in rows]

        spend = await budget_mod.month_spend_usd(db, tenant_id, agent_id)

        memory_policy = agent.memory_policy or "off"
        allowlist = list(agent.tools or [])
        if memory_policy == "off":
            # policy gate on top of the allow-list: memory tools are neither
            # offered to the model nor executable when memory is off.
            allowlist = [t for t in allowlist if t not in MEMORY_TOOL_NAMES]

        return _TurnContext(
            session_id=sid,
            model=agent.model,
            system_prompt=agent.system_prompt,
            allowlist=allowlist,
            budget_monthly_usd=float(agent.budget_monthly_usd),
            month_spend_usd=spend,
            memory_policy=memory_policy,
            history=history,
        )


async def _persist(
    tenant_id: str,
    agent_id: str,
    ctx: _TurnContext,
    new_turns: list[dict[str, Any]],
    *,
    input_tokens: int,
    output_tokens: int,
    calls: int,
) -> float:
    async with tenant_session(tenant_id) as db:
        for turn in new_turns:
            db.add(
                Message(
                    session_id=ctx.session_id,
                    tenant_id=tenant_id,
                    role=turn["role"],
                    content=turn["content"],
                )
            )
        await db.execute(
            sa.update(Session)
            .where(Session.session_id == ctx.session_id, Session.tenant_id == tenant_id)
            .values(updated_at=datetime.now(timezone.utc))
        )
        if calls > 0:
            return await budget_mod.record_usage(
                db,
                tenant_id=tenant_id,
                agent_id=agent_id,
                model=ctx.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                calls=calls,
            )
    return 0.0


async def stream_turn(
    *,
    tenant_id: str,
    agent_id: str,
    message: str,
    session_id: uuid.UUID | None = None,
    use_stream: bool = True,
    provider: ModelProvider | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Core turn generator. Yields event dicts:

    {type: session}, {type: text, delta}, {type: tool, name, status},
    {type: done, **ChatResult.as_dict()}.
    """
    s = get_settings()
    tenant_id_var.set(tenant_id)
    agent_id_var.set(agent_id)

    ctx = await _prepare(tenant_id, agent_id, session_id, message)
    session_id_var.set(str(ctx.session_id))
    yield {"type": "session", "session_id": str(ctx.session_id)}

    # --- hard monthly budget cap -> polite refusal, never silent ----------
    if ctx.month_spend_usd >= ctx.budget_monthly_usd:
        refusal = budget_mod.refusal_message(ctx.month_spend_usd, ctx.budget_monthly_usd)
        log.warning(
            "budget cap hit — refusing turn",
            extra={
                "extra_fields": {
                    "month_spend_usd": ctx.month_spend_usd,
                    "budget_monthly_usd": ctx.budget_monthly_usd,
                }
            },
        )
        await _persist(
            tenant_id,
            agent_id,
            ctx,
            [
                {"role": "user", "content": message},
                {"role": "assistant", "content": [{"type": "text", "text": refusal}]},
            ],
            input_tokens=0,
            output_tokens=0,
            calls=0,
        )
        result = ChatResult(
            session_id=ctx.session_id,
            reply=refusal,
            tool_calls=[],
            model=ctx.model,
            budget_exceeded=True,
        )
        yield {"type": "text", "delta": refusal}
        yield {"type": "done", **result.as_dict()}
        return

    # --- auto_recall: inject top-k relevant memories into the system prompt.
    # Runs after the budget gate (a refused turn embeds nothing) and outside
    # any DB transaction (embedding call is network I/O; the fetch is its own
    # short tx) — the tx1 → model loop → tx2 discipline is preserved.
    system_prompt = ctx.system_prompt
    if ctx.memory_policy == "auto_recall":
        system_prompt += await memory_mod.recall_block(tenant_id, agent_id, message)

    prov = provider or get_provider()
    tools_spec = specs_for_allowlist(ctx.allowlist)
    messages = [*ctx.history, {"role": "user", "content": message}]
    new_turns: list[dict[str, Any]] = [{"role": "user", "content": message}]
    tool_calls: list[str] = []
    total_in = 0
    total_out = 0
    calls = 0
    reply = ""

    for _ in range(s.MAX_TOOL_ITERATIONS):
        if use_stream:
            resp = None
            async for ev in prov.stream(
                model=ctx.model,
                system=system_prompt,
                messages=messages,
                tools=tools_spec,
                max_tokens=s.MAX_TOKENS,
            ):
                if ev.type == "text_delta" and ev.text:
                    yield {"type": "text", "delta": ev.text}
                elif ev.type == "final":
                    resp = ev.response
            if resp is None:  # pragma: no cover — provider contract violation
                raise RuntimeError("provider stream ended without a final response")
        else:
            resp = await prov.complete(
                model=ctx.model,
                system=system_prompt,
                messages=messages,
                tools=tools_spec,
                max_tokens=s.MAX_TOKENS,
            )

        calls += 1
        total_in += resp.input_tokens
        total_out += resp.output_tokens
        messages.append({"role": "assistant", "content": resp.content})
        new_turns.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            reply = resp.text
            break

        results = []
        for block in resp.tool_uses:
            name = block.get("name", "")
            tool_calls.append(name)
            yield {"type": "tool", "name": name, "status": "start"}
            try:
                out = await run_tool(name, block.get("input") or {}, ctx.allowlist)
                status = "ok"
            except ToolNotAllowedError as exc:
                out = f'{{"error": "{exc}"}}'
                status = "denied"
            yield {"type": "tool", "name": name, "status": status}
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.get("id"),
                    "content": out,
                }
            )
        messages.append({"role": "user", "content": results})
        new_turns.append({"role": "user", "content": results})
    else:
        reply = "(tool iteration limit reached)"

    cost = await _persist(
        tenant_id,
        agent_id,
        ctx,
        new_turns,
        input_tokens=total_in,
        output_tokens=total_out,
        calls=calls,
    )

    result = ChatResult(
        session_id=ctx.session_id,
        reply=reply,
        tool_calls=tool_calls,
        model=ctx.model,
        input_tokens=total_in,
        output_tokens=total_out,
        cost_usd=cost,
    )
    log.info(
        "turn complete",
        extra={
            "extra_fields": {
                "model": ctx.model,
                "tool_calls": tool_calls,
                "input_tokens": total_in,
                "output_tokens": total_out,
                "cost_usd": round(cost, 6),
                "model_calls": calls,
            }
        },
    )
    yield {"type": "done", **result.as_dict()}


async def chat_turn(
    *,
    tenant_id: str,
    agent_id: str,
    message: str,
    session_id: uuid.UUID | None = None,
    provider: ModelProvider | None = None,
) -> ChatResult:
    """Non-streaming turn: consume the generator, return the final result."""
    done: dict[str, Any] | None = None
    async for ev in stream_turn(
        tenant_id=tenant_id,
        agent_id=agent_id,
        message=message,
        session_id=session_id,
        use_stream=False,
        provider=provider,
    ):
        if ev["type"] == "done":
            done = ev
    assert done is not None
    return ChatResult(
        session_id=uuid.UUID(done["session_id"]),
        reply=done["reply"],
        tool_calls=done["tool_calls"],
        model=done["model"],
        input_tokens=done["usage"]["input_tokens"],
        output_tokens=done["usage"]["output_tokens"],
        cost_usd=done["usage"]["cost_usd"],
        budget_exceeded=done["budget_exceeded"],
    )
