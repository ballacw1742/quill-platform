"""Smoke-test helper: POST a sample approval to a running API."""

from __future__ import annotations

import os
import sys

import httpx

API = os.environ.get("QUILL_API", "http://localhost:8000")
SECRET = os.environ.get("AGENT_SHARED_SECRET", "dev-agent-secret-change-me")

PAYLOAD = {
    "agent_id": "rfi-triage",
    "agent_version": "0.1.0",
    "workflow": "rfi.classify",
    "lane": 2,
    "priority": "normal",
    "target_system": "procore",
    "api_call": "POST /procore/projects/1/rfis/SMOKE/classify",
    "agent_confidence": 0.81,
    "agent_reasoning": "Smoke-test classification request.",
    "payload": {"rfi_id": "RFI-SMOKE-0001", "category": "MEP"},
    "source_artifacts": [{"kind": "rfi", "ref": "RFI-SMOKE-0001"}],
    "citations": [{"source_type": "procore_rfi", "source_id": "RFI-SMOKE-0001"}],
}


def main() -> int:
    headers = {"X-Agent-Secret": SECRET, "Content-Type": "application/json"}
    r = httpx.post(f"{API}/v1/approvals", json=PAYLOAD, headers=headers, timeout=10)
    if r.status_code >= 300:
        print(f"FAILED {r.status_code}: {r.text}")
        return 1
    item = r.json()
    print(f"OK created approval id={item['id']} status={item['status']} lane={item['lane']}")

    listing = httpx.get(f"{API}/v1/approvals?limit=5", timeout=10).json()
    print(f"queue depth (pending): {listing.get('total')}")
    print(f"first item: {listing['items'][0]['id'] if listing['items'] else 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
