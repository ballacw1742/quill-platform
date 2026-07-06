"""Sprint 5.4 — Campus Template Automation tests.

Covers the template engine and the POST /v1/campuses/deploy-from-template
workflow: all six deployment steps, jurisdiction/region fallback variation,
precondition errors, and vendor-skip idempotency.
"""

from __future__ import annotations

import pytest
from app.models_projects import Project
from app.models_supply_chain import Vendor
from app.services.campus_template_engine import (
    TemplateResolutionError,
    catalog_summary,
    resolve_template,
)
from tests.conftest import auth_h


# ── Template engine (pure) ────────────────────────────────────────────

def test_engine_resolves_known_keys():
    t = resolve_template("hyperscale", "us-oh", "midwest")
    assert t["jurisdiction_used"] == "us-oh"
    assert t["region_used"] == "midwest"
    assert len(t["campus"]["equipment"]) > 0
    assert len(t["campus"]["monitoring_agents"]) > 0
    assert t["compliance"]["framework"] == "soc2"
    assert len(t["vendors"]) > 0


def test_engine_falls_back_to_default():
    t = resolve_template("edge", "de-hessen", "emea")
    assert t["jurisdiction_used"] == "default"
    assert t["region_used"] == "default"


def test_engine_rejects_unknown_campus_type():
    with pytest.raises(TemplateResolutionError):
        resolve_template("megascale", "us-oh", "midwest")


def test_catalog_summary_shape():
    cat = catalog_summary()
    assert {"campus_types", "jurisdictions", "regions"} <= set(cat)
    keys = [c["key"] for c in cat["campus_types"]]
    assert "hyperscale" in keys and "edge" in keys


# ── Helpers ────────────────────────────────────────────────────────────

async def _mk_project(session_maker, user_id: str, name: str = "QPB2 Build") -> str:
    async with session_maker() as s:
        p = Project(user_id=user_id, name=name, address="100 Data Dr, Columbus, OH", phase="commissioning")
        s.add(p)
        await s.commit()
        return p.id


# ── Endpoint: catalog ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deploy_templates_catalog(client, owner_token):
    _, token = owner_token
    r = await client.get("/v1/campuses/deploy-templates", headers=auth_h(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert any(c["key"] == "hyperscale" for c in body["campus_types"])
    assert any(j["key"] == "us-oh" for j in body["jurisdictions"])


# ── Endpoint: full deployment ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deploy_full_workflow_all_six_steps(client, owner_token, session_maker):
    user_id, token = owner_token
    project_id = await _mk_project(session_maker, user_id)

    r = await client.post(
        "/v1/campuses/deploy-from-template",
        headers=auth_h(token),
        json={
            "project_id": project_id,
            "name": "Columbus Campus 1",
            "campus_type": "hyperscale",
            "jurisdiction": "us-oh",
            "region": "midwest",
        },
    )
    assert r.status_code == 201, r.text
    report = r.json()

    # Report shape + all six steps created
    steps = {s["step"]: s for s in report["steps"]}
    assert set(steps) == {
        "campus", "monitoring_agents", "equipment",
        "compliance_checklist", "vendors", "dashboard_seed",
    }
    assert all(s["status"] == "created" for s in steps.values())
    campus = report["campus"]
    assert campus["project_id"] == project_id
    assert campus["mw_capacity"] == 500          # from template default
    assert campus["pue_target"] == 1.2
    assert report["template"]["jurisdiction_used"] == "us-oh"

    campus_id = campus["id"]

    # 1. Campus linked to project via GET filter (Sprint 5.1 flow)
    r = await client.get(f"/v1/campuses?project_id={project_id}", headers=auth_h(token))
    assert r.json()["total"] == 1

    # 2. Monitoring agents registered
    r = await client.get(f"/v1/campuses/{campus_id}/monitoring-agents", headers=auth_h(token))
    assert r.status_code == 200
    assert r.json()["total"] == 5

    # 3. Equipment list for the project
    r = await client.get(f"/v1/equipment?project_id={project_id}", headers=auth_h(token))
    assert r.json()["total"] == 7

    # 4. Compliance checklist for the campus with items
    r = await client.get("/v1/compliance/checklists", headers=auth_h(token))
    cls = [c for c in r.json()["items"] if c["campus_id"] == campus_id]
    assert len(cls) == 1 and cls[0]["framework"] == "soc2"
    r = await client.get(f"/v1/compliance/checklists/{cls[0]['id']}", headers=auth_h(token))
    assert len(r.json()["items"]) == 6

    # 5. Vendors created for the region
    r = await client.get("/v1/vendors", headers=auth_h(token))
    names = [v["name"] for v in r.json()["items"]]
    assert "Vertiv \u2014 Columbus" in names

    # 6. Dashboard seed metrics
    r = await client.get(f"/v1/campuses/{campus_id}/metrics", headers=auth_h(token))
    types = {m["metric_type"] for m in r.json()["items"]}
    assert {"pue", "uptime_pct", "power_mw"} <= types


@pytest.mark.asyncio
async def test_deploy_jurisdiction_region_fallback_variation(client, owner_token, session_maker):
    """Edge campus with unknown jurisdiction/region falls back to defaults and says so."""
    user_id, token = owner_token
    project_id = await _mk_project(session_maker, user_id, name="Berlin Edge POP")

    r = await client.post(
        "/v1/campuses/deploy-from-template",
        headers=auth_h(token),
        json={
            "project_id": project_id,
            "name": "Berlin Edge 1",
            "campus_type": "edge",
            "jurisdiction": "de-berlin",
            "region": "emea",
            "mw_capacity": 3.5,
        },
    )
    assert r.status_code == 201, r.text
    report = r.json()
    assert report["template"]["jurisdiction_used"] == "default"
    assert report["template"]["region_used"] == "default"
    assert report["campus"]["mw_capacity"] == 3.5   # explicit override beats template
    steps = {s["step"]: s for s in report["steps"]}
    assert "used default" in steps["compliance_checklist"]["detail"]
    assert "used default" in steps["vendors"]["detail"]
    # Edge template registers 3 agents
    assert steps["monitoring_agents"]["count"] == 3


@pytest.mark.asyncio
async def test_deploy_skips_existing_vendors(client, owner_token, session_maker):
    user_id, token = owner_token
    async with session_maker() as s:
        s.add(Vendor(name="Vertiv \u2014 Columbus", category="ups"))
        await s.commit()
    project_id = await _mk_project(session_maker, user_id, name="Columbus 2")

    r = await client.post(
        "/v1/campuses/deploy-from-template",
        headers=auth_h(token),
        json={
            "project_id": project_id,
            "name": "Columbus Campus 2",
            "campus_type": "enterprise",
            "jurisdiction": "us-oh",
            "region": "midwest",
        },
    )
    assert r.status_code == 201, r.text
    steps = {s["step"]: s for s in r.json()["steps"]}
    assert steps["vendors"]["count"] == 3   # 4 in template, 1 skipped
    assert "Vertiv" in steps["vendors"]["detail"]


@pytest.mark.asyncio
async def test_deploy_errors(client, owner_token, session_maker):
    user_id, token = owner_token

    # Unknown project -> 404 with error envelope
    r = await client.post(
        "/v1/campuses/deploy-from-template",
        headers=auth_h(token),
        json={"project_id": "nope", "name": "X", "campus_type": "edge",
              "jurisdiction": "us-oh", "region": "midwest"},
    )
    assert r.status_code == 404 and "detail" in r.json()

    # Unknown campus_type -> 422
    project_id = await _mk_project(session_maker, user_id, name="Err Project")
    r = await client.post(
        "/v1/campuses/deploy-from-template",
        headers=auth_h(token),
        json={"project_id": project_id, "name": "X", "campus_type": "megascale",
              "jurisdiction": "us-oh", "region": "midwest"},
    )
    assert r.status_code == 422 and "megascale" in r.json()["detail"]

    # Deploy once fine, second deploy for same project -> 409
    r = await client.post(
        "/v1/campuses/deploy-from-template",
        headers=auth_h(token),
        json={"project_id": project_id, "name": "X", "campus_type": "edge",
              "jurisdiction": "us-oh", "region": "midwest"},
    )
    assert r.status_code == 201
    r = await client.post(
        "/v1/campuses/deploy-from-template",
        headers=auth_h(token),
        json={"project_id": project_id, "name": "X2", "campus_type": "edge",
              "jurisdiction": "us-oh", "region": "midwest"},
    )
    assert r.status_code == 409
