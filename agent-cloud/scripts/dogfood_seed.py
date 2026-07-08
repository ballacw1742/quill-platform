"""dogfood_seed — provision Charles as tenant #1 with a real working agent.

Phase E (cutover staging). This is the one-command recipe CUTOVER.md §12
points at. It is **idempotent** and **safe to re-run**: it reuses the same
provisioning path as a first chat (seeds `personal` + `quill`), optionally
sets a tenant budget override, and creates one real working dogfood agent via
the authoritative Agent Builder CRUD core (`app.agents.create_agent`) — so
the agent goes through the exact same validation the web builder uses, not
raw SQL.

Design intent (design doc §7 Phase E — "Axe → tenant #1, the permanent
dogfood"):
  - Tenant #1 is Charles's personal tenant (default `user-charles`).
  - It gets the two seeds plus a purpose-built "dogfood" agent with memory on
    and the read-only Quill tools, ready to actually use.

Safety:
  - `--dry-run` prints the exact plan and makes **zero** writes (no DB
    connection is even required to reason about the plan; migrations still
    run to make the report honest about the schema, but nothing is inserted).
  - Nothing here flips any go-live switch. Provisioning a tenant is not
    "cutover" — see CUTOVER.md §13. The parent runs this consciously; this
    sprint only tests it dry-run / local.

Usage:
    python -m scripts.dogfood_seed --tenant user-charles [--dry-run]
        [--budget 50] [--agent-id dogfood] [--model claude-fable-5]

Run it with the agent-cloud venv from the agent-cloud/ directory, e.g.:
    .venv/bin/python -m scripts.dogfood_seed --tenant user-charles --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

# The dogfood agent definition. Memory on (auto_recall) so it behaves like the
# personal seed; read-only Quill tools so it can actually answer portfolio
# questions on day one; a modest budget well under the personal tenant cap.
DOGFOOD_AGENT = {
    "agent_id": "dogfood",
    "system_prompt": (
        "You are Charles's dogfood agent on Quill Agent Cloud — tenant #1, "
        "the permanent test of the platform. Be direct, concise, and honest. "
        "You have long-term memory and read-only access to Quill portfolio "
        "data. Never claim a write happened; write tools queue an approval "
        "for a human. When something about the platform is broken or "
        "surprising, say so plainly so it can be fixed."
    ),
    "model": "claude-fable-5",
    "tools": [
        "get_time",
        "memory_save",
        "memory_search",
    ],
    "memory_policy": "auto_recall",
    "budget_monthly_usd": 5.0,
}


def _out(obj: dict) -> None:
    print(json.dumps(obj, indent=2, default=str))


def build_plan(tenant: str, agent_id: str, model: str, budget: float | None) -> dict:
    """The plan is pure data — safe to print in dry-run without any DB."""
    agent = {**DOGFOOD_AGENT, "agent_id": agent_id, "model": model}
    return {
        "tenant": tenant,
        "steps": [
            {
                "step": "provision tenant + seed agents",
                "detail": f"seeds 'personal' + 'quill' for {tenant} (idempotent)",
            },
            *(
                [
                    {
                        "step": "set tenant budget override",
                        "detail": f"agentcloud_tenants.budget_monthly_usd = {budget}",
                    }
                ]
                if budget is not None
                else []
            ),
            {
                "step": "create dogfood agent",
                "detail": f"create '{agent_id}' (idempotent — skipped if it exists)",
                "agent": agent,
            },
        ],
        "activates_go_live": False,
        "note": (
            "Provisioning tenant #1 is NOT cutover. Retiring OpenClaw is a "
            "separate deliberate decision (CUTOVER.md §13)."
        ),
    }


async def run(
    tenant: str,
    agent_id: str,
    model: str,
    budget: float | None,
    dry_run: bool,
) -> None:
    plan = build_plan(tenant, agent_id, model, budget)

    if dry_run:
        _out({"dry_run": True, "plan": plan})
        return

    # Imports are deferred so --dry-run needs no DB / app config at all.
    from app.db import engine, tenant_session  # noqa: PLC0415
    from app.migrations import run_migrations  # noqa: PLC0415
    from app.orchestrator import UnknownAgentError, _prepare  # noqa: PLC0415
    from app.agents import AgentConflictError, create_agent  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    results: list[dict] = []
    await run_migrations(engine)

    # 1. Provision tenant + seeds (reuse the first-chat provisioning path).
    try:
        await _prepare(tenant, "personal", None, "dogfood-seed")
    except UnknownAgentError:
        pass
    results.append({"step": "provision", "ok": True, "tenant": tenant})

    # 2. Optional tenant budget override. The tenant row already exists (step
    #    1 provisioned it), so this is a plain idempotent UPDATE — no INSERT
    #    needed, which also sidesteps the created_at NOT-NULL default that
    #    only Postgres fills server-side.
    if budget is not None:
        async with tenant_session(tenant) as db:
            res = await db.execute(
                text(
                    "UPDATE agentcloud_tenants SET budget_monthly_usd = :b "
                    "WHERE tenant_id = :t"
                ),
                {"b": budget, "t": tenant},
            )
        results.append(
            {
                "step": "budget",
                "ok": res.rowcount == 1,
                "budget_monthly_usd": budget,
            }
        )

    # 3. Create the dogfood agent through the authoritative CRUD core.
    agent = {**DOGFOOD_AGENT, "agent_id": agent_id, "model": model}
    try:
        detail = await create_agent(tenant, agent)
        results.append({"step": "agent", "ok": True, "created": detail["agent_id"]})
    except AgentConflictError:
        # Idempotent: the dogfood agent already exists — that's success.
        results.append({"step": "agent", "ok": True, "already_exists": agent_id})

    await engine.dispose()
    _out({"dry_run": False, "tenant": tenant, "results": results})


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="dogfood_seed")
    ap.add_argument("--tenant", default="user-charles")
    ap.add_argument("--agent-id", dest="agent_id", default="dogfood")
    ap.add_argument("--model", default="claude-fable-5")
    ap.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Optional tenant budget override (USD/mo). Omit to keep config default.",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    asyncio.run(
        run(args.tenant, args.agent_id, args.model, args.budget, args.dry_run)
    )


if __name__ == "__main__":
    main()
