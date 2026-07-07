"""Maintenance CLI (run as a Cloud Run job with the same image + secrets).

Never exposed over HTTP. Subcommands:

  rls-probe [--tenant-a T --tenant-b T]
      Prove RLS from raw SQL as the app role: counts per table with the
      correct tenant GUC, the *wrong* tenant GUC, and no GUC at all.
      Wrong/no GUC must return zero rows (gate: isolation).

  set-agent --tenant T --agent A [--model M] [--budget USD] [--enabled true|false]
            [--memory-policy off|tools_only|auto_recall]
      Tweak one agent definition (model tiering / budget caps / kill switch
      / memory policy).

  list-memory --tenant T [--agent A] [--limit N]
      Show a tenant's stored memories (id, agent, kind, content, embedded?).

  seed-tenant --tenant T
      Provision a tenant + its two seed agents without a chat call.

  cleanup-smoke [--prefix smoke-]
      Delete all rows belonging to smoke test tenants (messages, sessions,
      usage, agents, tenants). Uses the admin RLS policy.

  sql --query "SELECT ..."  (admin GUC; read-only guard: SELECT-only)
      Escape hatch for verification evidence.

Usage: python -m app.admin <subcommand> [flags]
Falls back to ADMIN_CMD env (shlex-split) when no argv is given, so it can
run under `gcloud run jobs execute --update-env-vars ADMIN_CMD=...` too.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import sys

import sqlalchemy as sa
from sqlalchemy import text

from app.db import SessionLocal, admin_session, tenant_session
from app.migrations import run_migrations

TABLES = [
    "agentcloud_tenants",
    "agentcloud_agents",
    "agentcloud_sessions",
    "agentcloud_messages",
    "agentcloud_usage",
    "agentcloud_memory",
]


def _out(obj: dict) -> None:
    print(json.dumps(obj, default=str), flush=True)


async def _counts(session, label: str) -> dict:
    counts = {}
    for t in TABLES:
        counts[t] = (await session.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one()
    return {"guc": label, "counts": counts}


async def rls_probe(tenant_a: str, tenant_b: str) -> None:
    async with SessionLocal() as session:
        async with session.begin():
            who = (
                await session.execute(
                    text(
                        "SELECT current_user, "
                        "(SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user), "
                        "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user)"
                    )
                )
            ).one()
            _out(
                {
                    "current_user": who[0],
                    "rolbypassrls": who[1],
                    "rolsuper": who[2],
                }
            )
            rls = (
                await session.execute(
                    text(
                        "SELECT relname, relrowsecurity, relforcerowsecurity "
                        "FROM pg_class WHERE relname = ANY(:t)"
                    ),
                    {"t": TABLES},
                )
            ).all()
            _out({"rls_state": [dict(zip(("table", "enabled", "forced"), r)) for r in rls]})

    # correct GUC for tenant A
    async with tenant_session(tenant_a) as s:
        r = await _counts(s, f"app.tenant_id={tenant_a}")
        r["expectation"] = "tenant A rows only"
        _out(r)
    # wrong GUC (tenant B) — tenant A's rows must be invisible
    async with tenant_session(tenant_b) as s:
        r = await _counts(s, f"app.tenant_id={tenant_b}")
        r["expectation"] = "tenant B rows only (zero tenant-A leakage)"
        _out(r)
    # no GUC at all — everything must be invisible
    async with SessionLocal() as session:
        async with session.begin():
            r = await _counts(session, "none")
            r["expectation"] = "all zero"
            _out(r)
    # admin policy view (ground truth totals)
    async with admin_session() as s:
        r = await _counts(s, "app.admin=on")
        r["expectation"] = "ground truth totals"
        _out(r)
    # per-tenant breakdown under admin for the two probe tenants
    async with admin_session() as s:
        for t in ("agentcloud_sessions", "agentcloud_messages", "agentcloud_usage"):
            rows = (
                await s.execute(
                    text(
                        f"SELECT tenant_id, count(*) FROM {t} "
                        "WHERE tenant_id IN (:a, :b) GROUP BY tenant_id"
                    ),
                    {"a": tenant_a, "b": tenant_b},
                )
            ).all()
            _out({"table": t, "per_tenant": {r[0]: r[1] for r in rows}})


async def set_agent(
    tenant: str,
    agent: str,
    model: str | None,
    budget: float | None,
    enabled: str | None,
    memory_policy: str | None = None,
) -> None:
    values: dict = {}
    if model is not None:
        values["model"] = model
    if budget is not None:
        values["budget_monthly_usd"] = budget
    if enabled is not None:
        values["enabled"] = enabled.lower() in ("true", "1", "yes", "on")
    if memory_policy is not None:
        if memory_policy not in ("off", "tools_only", "auto_recall"):
            _out({"error": f"invalid memory_policy {memory_policy!r}"})
            return
        values["memory_policy"] = memory_policy
    if not values:
        _out({"error": "nothing to set"})
        return
    async with tenant_session(tenant) as s:
        res = await s.execute(
            text(
                "UPDATE agentcloud_agents SET "
                + ", ".join(f"{k} = :{k}" for k in values)
                + " WHERE tenant_id = :tenant AND agent_id = :agent"
            ),
            {**values, "tenant": tenant, "agent": agent},
        )
        _out({"updated": res.rowcount, "tenant": tenant, "agent": agent, "values": values})


async def seed_tenant(tenant: str) -> None:
    # Reuse the orchestrator provisioning path with a throwaway prepare.
    from app.orchestrator import UnknownAgentError, _prepare  # noqa: PLC0415

    try:
        await _prepare(tenant, "personal", None, "seed")
    except UnknownAgentError:
        pass
    _out({"seeded": tenant})


async def list_memory(tenant: str, agent: str | None, limit: int) -> None:
    limit = max(1, min(limit, 200))
    where = "WHERE tenant_id = :tenant"
    params: dict = {"tenant": tenant, "limit": limit}
    if agent:
        where += " AND agent_id = :agent"
        params["agent"] = agent
    async with tenant_session(tenant) as s:
        has_embedding = (
            await s.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_name = 'agentcloud_memory' AND column_name = 'embedding'"
                )
            )
        ).scalar_one()
        embedded_expr = (
            "(embedding IS NOT NULL)" if has_embedding else "FALSE"
        )
        rows = (
            await s.execute(
                text(
                    f"SELECT memory_id, agent_id, kind, content, metadata, "
                    f"created_at, last_accessed, {embedded_expr} AS embedded "
                    f"FROM agentcloud_memory {where} "
                    "ORDER BY created_at DESC LIMIT :limit"
                ),
                params,
            )
        ).all()
    _out(
        {
            "tenant": tenant,
            "agent": agent,
            "count": len(rows),
            "items": [
                dict(
                    zip(
                        (
                            "memory_id",
                            "agent_id",
                            "kind",
                            "content",
                            "metadata",
                            "created_at",
                            "last_accessed",
                            "embedded",
                        ),
                        r,
                    )
                )
                for r in rows
            ],
        }
    )


async def cleanup_smoke(prefix: str) -> None:
    if not prefix or prefix in ("%", "%%"):
        _out({"error": "refusing empty/wildcard prefix"})
        return
    like = prefix + "%"
    deleted: dict[str, int] = {}
    async with admin_session() as s:
        for t in (
            "agentcloud_messages",
            "agentcloud_sessions",
            "agentcloud_usage",
            "agentcloud_memory",
            "agentcloud_agents",
            "agentcloud_tenants",
        ):
            res = await s.execute(
                text(f"DELETE FROM {t} WHERE tenant_id LIKE :like"), {"like": like}
            )
            deleted[t] = res.rowcount
    _out({"cleanup_prefix": prefix, "deleted": deleted})


async def run_sql(query: str) -> None:
    if not query.strip().lower().startswith("select"):
        _out({"error": "sql subcommand is SELECT-only"})
        return
    async with admin_session() as s:
        rows = (await s.execute(text(query))).all()
        _out({"rows": [list(r) for r in rows[:200]], "row_count": len(rows)})


async def amain(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="agentcloud-admin")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("rls-probe")
    p.add_argument("--tenant-a", default="smoke-tenant-a")
    p.add_argument("--tenant-b", default="smoke-tenant-b")

    p = sub.add_parser("set-agent")
    p.add_argument("--tenant", required=True)
    p.add_argument("--agent", required=True)
    p.add_argument("--model")
    p.add_argument("--budget", type=float)
    p.add_argument("--enabled")
    p.add_argument("--memory-policy", dest="memory_policy")

    p = sub.add_parser("seed-tenant")
    p.add_argument("--tenant", required=True)

    p = sub.add_parser("list-memory")
    p.add_argument("--tenant", required=True)
    p.add_argument("--agent")
    p.add_argument("--limit", type=int, default=50)

    p = sub.add_parser("cleanup-smoke")
    p.add_argument("--prefix", default="smoke-")

    p = sub.add_parser("sql")
    p.add_argument("--query", required=True)

    args = parser.parse_args(argv)

    from app.db import engine  # noqa: PLC0415

    await run_migrations(engine)

    if args.cmd == "rls-probe":
        await rls_probe(args.tenant_a, args.tenant_b)
    elif args.cmd == "set-agent":
        await set_agent(
            args.tenant, args.agent, args.model, args.budget, args.enabled,
            args.memory_policy,
        )
    elif args.cmd == "list-memory":
        await list_memory(args.tenant, args.agent, args.limit)
    elif args.cmd == "seed-tenant":
        await seed_tenant(args.tenant)
    elif args.cmd == "cleanup-smoke":
        await cleanup_smoke(args.prefix)
    elif args.cmd == "sql":
        await run_sql(args.query)
    await engine.dispose()


def main() -> None:
    argv = sys.argv[1:]
    if not argv and os.environ.get("ADMIN_CMD"):
        argv = shlex.split(os.environ["ADMIN_CMD"])
    asyncio.run(amain(argv))


if __name__ == "__main__":
    main()
