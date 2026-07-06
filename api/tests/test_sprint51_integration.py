"""Sprint 5.1 — Cross-module integration boundary tests.

Exercises the 5 integration flows end-to-end through the real HTTP routes:
  1. Project → Campus graduation (POST /v1/campuses + ?project_id filter)
  2. Deal Won → Customer auto-promotion (PATCH /v1/deals/{id} stage=won)
  3. Campus ↔ Customer link (PATCH /v1/customers/{id} campus_id + ?campus_id filter)
  4. Supply chain capex → Finance summary (capex_equipment_usd)
  5. Contract obligations → Compliance upcoming deadlines (GET /v1/compliance/upcoming)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from app.models import Contract
from app.models_compliance import ContractObligation
from app.models_operations import Campus
from app.models_pipeline import Account, Deal
from app.models_supply_chain import Equipment
from tests.conftest import auth_h


@pytest.mark.asyncio
async def test_integration_1_campus_project_filter(client, owner_token):
    _, token = owner_token
    r = await client.post(
        "/v1/campuses",
        headers=auth_h(token),
        json={"name": "QPB1", "project_id": "proj-1", "mw_capacity": 0, "status": "commissioning"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["project_id"] == "proj-1"

    r = await client.get("/v1/campuses?project_id=proj-1", headers=auth_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["project_id"] == "proj-1"

    # A project with no campus yet returns an empty list (drives the Go Live button).
    r = await client.get("/v1/campuses?project_id=nonexistent", headers=auth_h(token))
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_integration_2_deal_won_promotes_account(client, owner_token, session_maker):
    _, token = owner_token
    async with session_maker() as s:
        acct = Account(name="Acme AI", type="prospect")
        s.add(acct)
        await s.flush()
        deal = Deal(account_id=acct.id, name="Acme 50MW", stage="negotiating")
        s.add(deal)
        await s.commit()
        acct_id, deal_id = acct.id, deal.id

    r = await client.patch(f"/v1/deals/{deal_id}", headers=auth_h(token), json={"stage": "won"})
    assert r.status_code == 200, r.text

    async with session_maker() as s:
        acct = await s.get(Account, acct_id)
        assert acct.type == "customer"


@pytest.mark.asyncio
async def test_integration_3_campus_customer_link(client, owner_token, session_maker):
    _, token = owner_token
    async with session_maker() as s:
        acct = Account(name="CustCo", type="customer")
        s.add(acct)
        await s.commit()
        acct_id = acct.id

    # Assign a campus to the customer.
    r = await client.patch(f"/v1/customers/{acct_id}", headers=auth_h(token), json={"campus_id": "camp-9"})
    assert r.status_code == 200, r.text
    assert r.json()["campus_id"] == "camp-9"

    # Operations can look up the customer served by a campus.
    r = await client.get("/v1/customers?campus_id=camp-9", headers=auth_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == acct_id

    # Unlinked campus → nobody served.
    r = await client.get("/v1/customers?campus_id=other", headers=auth_h(token))
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_integration_4_equipment_capex(client, owner_token, session_maker):
    _, token = owner_token
    async with session_maker() as s:
        s.add(Equipment(name="Generator", category="generator", quantity=2, unit_cost_usd=100.0, status="ordered"))
        s.add(Equipment(name="UPS", category="ups", quantity=1, unit_cost_usd=500.0, status="not_ordered"))
        await s.commit()

    r = await client.get("/v1/finance/summary", headers=auth_h(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert "capex_equipment_usd" in data
    # Only the ordered equipment counts: 2 * 100 = 200. The not_ordered UPS is excluded.
    assert data["capex_equipment_usd"] == 200.0


@pytest.mark.asyncio
async def test_integration_4_equipment_capex_defaults_zero(client, owner_token):
    _, token = owner_token
    r = await client.get("/v1/finance/summary", headers=auth_h(token))
    assert r.status_code == 200, r.text
    assert r.json()["capex_equipment_usd"] == 0.0


@pytest.mark.asyncio
async def test_integration_5_upcoming_deadlines(client, owner_token, session_maker):
    _, token = owner_token
    today = datetime.now(UTC).date()
    async with session_maker() as s:
        s.add(ContractObligation(title="Renew SLA", obligation_type="other",
                                 due_date=today + timedelta(days=10), status="open"))
        s.add(ContractObligation(title="Far Off", obligation_type="other",
                                 due_date=today + timedelta(days=90), status="open"))
        s.add(Contract(project_label="MSA Acme", status="reviewed",
                       expiration_date=datetime.now(UTC) + timedelta(days=5)))
        await s.commit()

    r = await client.get("/v1/compliance/upcoming", headers=auth_h(token))
    assert r.status_code == 200, r.text
    body = r.json()
    items = body["items"]
    titles = [i["title"] for i in items]

    assert "Renew SLA" in titles       # obligation due in 10d
    assert "MSA Acme" in titles        # contract expiring in 5d
    assert "Far Off" not in titles     # 90d out — outside the 30d window

    # Sorted ascending by due_date: contract (5d) before obligation (10d).
    assert items[0]["title"] == "MSA Acme"

    # Exact response shape per the integration contract.
    for i in items:
        assert set(i.keys()) == {"source", "id", "title", "due_date", "status"}
    sources = {i["source"] for i in items}
    assert sources <= {"checklist", "contract"}
