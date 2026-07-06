"""Verify the demo dataset produces mutually consistent dashboard numbers.

Hits every module dashboard endpoint on a running API and asserts:

  1. Cross-module consistency (always, works on prod too):
       finance ARR == intelligence ARR == pipeline won value
       finance pipeline == pipeline summary active value == intelligence pipeline
       customers open tickets == intelligence open tickets
       operations open P1/P2 == intelligence active incidents
       supply-chain at-risk == intelligence at-risk equipment
       finance capex == supply-chain equipment value
  2. Absolute expected values (--strict, fresh local DB only):
       every number in scripts.seed_demo.expected_numbers()

Usage (from api/ with the API running):

    python -m scripts.verify_demo_dashboards \
        --api http://localhost:8000 \
        --email charles@quill.local --password quill-dev-password \
        [--strict]

Exit code 0 = all checks passed.
"""

from __future__ import annotations

import argparse
import json
import math
import sys

import httpx
from scripts.seed_demo import expected_numbers

FAILURES: list[str] = []


def check(label: str, actual, expected, tolerance: float = 0.01) -> None:
    ok = (
        math.isclose(float(actual), float(expected), abs_tol=tolerance)
        if isinstance(expected, (int, float)) and not isinstance(expected, bool)
        else actual == expected
    )
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label}: actual={actual} expected={expected}")
    if not ok:
        FAILURES.append(f"{label}: actual={actual} expected={expected}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--email", default="charles@quill.local")
    parser.add_argument("--password", default="quill-dev-password")
    parser.add_argument("--strict", action="store_true",
                        help="assert absolute expected numbers (fresh local DB only)")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.api, timeout=60)

    login = client.post("/v1/auth/login", json={"email": args.email, "password": args.password})
    login.raise_for_status()
    token = login.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"

    def get(path: str) -> dict:
        resp = client.get(path)
        resp.raise_for_status()
        return resp.json()

    finance = get("/v1/finance/summary")
    aging = get("/v1/finance/invoices/aging")
    pipeline = get("/v1/pipeline/summary")
    campuses = get("/v1/campuses")
    customers = get("/v1/customers/summary")
    supply = get("/v1/supply-chain/summary")
    compliance = get("/v1/compliance/summary")
    kpis = get("/v1/intelligence/kpis")
    brief = get("/v1/intelligence/brief")
    queue = get("/v1/approvals?status=pending&limit=200")
    projects = get("/v1/projects")

    print("\n=== raw module responses (dashboard JSON) ===")
    for name, payload in [
        ("finance/summary", finance), ("finance/invoices/aging", aging),
        ("pipeline/summary", pipeline), ("customers/summary", customers),
        ("supply-chain/summary", supply), ("compliance/summary", compliance),
        ("intelligence/kpis", kpis),
    ]:
        print(f"--- {name} ---")
        print(json.dumps(payload, indent=2, default=str))

    won_stage = next(s for s in pipeline["stages"] if s["stage"] == "won")

    print("\n=== cross-module consistency (valid on any DB, incl. prod) ===")
    check("finance ARR == intelligence ARR", finance["total_arr_usd"], kpis["total_arr_usd"])
    check("finance ARR == pipeline won value", finance["total_arr_usd"], won_stage["total_value_usd"])
    check("finance pipeline == pipeline active value",
          finance["total_pipeline_value_usd"], pipeline["total_active_value_usd"])
    check("finance pipeline == intelligence pipeline",
          finance["total_pipeline_value_usd"], kpis["pipeline_value_usd"])
    check("customers open tickets == intelligence open tickets",
          customers["open_tickets"], kpis["open_customer_tickets"])
    check("supply-chain at-risk == intelligence at-risk equipment",
          supply["at_risk_count"], kpis["at_risk_equipment_count"])
    check("finance capex == supply-chain equipment value",
          finance["total_capex_committed_usd"], supply["total_equipment_value_usd"])
    check("customers total == intelligence active customers",
          customers["total_customers"], kpis["active_customers"])
    ops_open_p1p2 = sum(c.get("active_p1_p2_count", 0) for c in campuses["items"])
    check("operations open P1/P2 == intelligence active incidents",
          ops_open_p1p2, kpis["active_incidents_p1_p2"])
    mw_live_total = sum((c.get("mw_live") or 0) for c in campuses["items"] if c["status"] == "live")
    check("operations mw_live == intelligence mw_live", mw_live_total, kpis["mw_live"])
    check("aging outstanding == finance outstanding",
          aging["total_outstanding_usd"], finance["total_outstanding_invoices_usd"])
    check("aging overdue count == finance overdue count",
          aging["overdue_invoices_count"], finance["overdue_invoices_count"])
    pending_demo = [i for i in queue["items"] if i["id"].startswith("demo-")]
    check("pending demo approvals >= 1 (queue alive)", len(pending_demo) >= 1, True)
    check("brief has revenue summary", bool(brief["revenue"]["summary"]), True)

    if args.strict:
        exp = expected_numbers()
        print("\n=== absolute expected numbers (fresh local DB) ===")
        for key, expected in exp["finance"].items():
            check(f"finance.{key}", finance[key], expected)
        p = exp["pipeline"]
        check("pipeline.total_active_deals", pipeline["total_active_deals"], p["total_active_deals"])
        check("pipeline.total_active_mw", pipeline["total_active_mw"], p["total_active_mw"])
        check("pipeline.total_active_value_usd", pipeline["total_active_value_usd"], p["total_active_value_usd"])
        check("pipeline.won_value_usd", won_stage["total_value_usd"], p["won_value_usd"])
        check("pipeline.win_rate_pct", pipeline["win_rate_pct"], p["win_rate_pct"])
        o = exp["operations"]
        check("operations.campuses", campuses["total"], o["campuses"])
        demo_campus = next(c for c in campuses["items"] if c["name"] == "Blue Creek Campus")
        check("operations.mw_capacity", demo_campus["mw_capacity"], o["mw_capacity"])
        check("operations.mw_live", demo_campus["mw_live"], o["mw_live"])
        check("operations.pue_current", demo_campus["pue_current"], o["pue_current"])
        check("operations.open_p1_p2", demo_campus["active_p1_p2_count"], o["open_p1_p2_incidents"])
        c = exp["customers"]
        check("customers.total_customers", customers["total_customers"], c["total_customers"])
        check("customers.open_tickets", customers["open_tickets"], c["open_tickets"])
        check("customers.has_critical_tickets", customers["has_critical_tickets"], c["has_critical_tickets"])
        for key, expected in exp["supply_chain"].items():
            check(f"supply_chain.{key}", supply[key], expected)
        for key, expected in exp["compliance"].items():
            check(f"compliance.{key}", compliance[key], expected)
        for key, expected in exp["intelligence"].items():
            check(f"intelligence.{key}", kpis[key], expected)
        check("approvals.pending_demo_items", len(pending_demo),
              exp["approvals"]["pending_demo_items"])
        demo_projects = [p_ for p_ in projects["items"] if p_["id"].startswith("demo-")]
        check("projects.demo_projects", len(demo_projects), 2)
        ridgeline = next(p_ for p_ in demo_projects if p_["name"] == "Ridgeline DC-2")
        check("projects.ridgeline_milestones", ridgeline["milestone_total"], 6)
        check("projects.ridgeline_overdue_milestones", ridgeline["milestone_overdue"], 1)

    print()
    if FAILURES:
        print(f"VERIFICATION FAILED — {len(FAILURES)} check(s):")
        for failure in FAILURES:
            print(f"  - {failure}")
        sys.exit(1)
    print("VERIFICATION PASSED — all checks green.")


if __name__ == "__main__":
    main()
