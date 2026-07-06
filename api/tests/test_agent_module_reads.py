"""Sprint 1 agent-auth fix: module GET routes accept X-Agent-Secret.

Deployed ADK agents authenticate with the shared agent secret
(X-Agent-Secret header). Read-only module routes must accept it via
get_current_user_or_agent; anonymous requests must still 401; write
routes must remain user-JWT-gated.
"""

from __future__ import annotations

# Register module tables on Base.metadata before the engine fixture runs.
from app import (  # noqa: F401
    models_compliance,
    models_customers,
    models_finance,
    models_operations,
    models_pipeline,
    models_projects,
    models_supply_chain,
)

from tests.conftest import agent_h

# One representative GET per module switched to get_current_user_or_agent.
MODULE_GET_ROUTES = [
    "/v1/finance/summary",
    "/v1/pipeline/summary",
    "/v1/campuses/deploy-templates",
    "/v1/customers/summary",
    "/v1/supply-chain/summary",
    "/v1/intelligence/kpis",
    "/v1/compliance/summary",
]


async def test_module_gets_accept_agent_secret(client):
    for route in MODULE_GET_ROUTES:
        r = await client.get(route, headers=agent_h())
        assert r.status_code == 200, f"{route} -> {r.status_code}: {r.text[:200]}"


async def test_module_gets_reject_anonymous(client):
    for route in MODULE_GET_ROUTES:
        r = await client.get(route)
        assert r.status_code == 401, f"{route} -> {r.status_code}"


async def test_module_gets_reject_bad_agent_secret(client):
    for route in MODULE_GET_ROUTES:
        r = await client.get(route, headers={"X-Agent-Secret": "wrong-secret"})
        assert r.status_code == 401, f"{route} -> {r.status_code}"


async def test_module_writes_reject_agent_secret(client):
    """Writes stay user-JWT-only: agent secret must NOT authorize them."""
    r = await client.post(
        "/v1/finance/budget-lines",
        json={"project_id": "x", "category": "labor", "amount": 1},
        headers=agent_h(),
    )
    assert r.status_code == 401
