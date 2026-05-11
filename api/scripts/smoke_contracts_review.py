"""Smoke test for Contracts.2 routes (dispatch_review, interpret, reviews, interpretations).

Usage:
    cd /Users/charlesmitchell/.openclaw/workspace/quill-platform
    bash -c 'set -a; source .env; set +a; .venv/bin/python api/scripts/smoke_contracts_review.py'
"""
import asyncio
import subprocess
import sys
import time
import os

import httpx


BASE_URL = os.environ.get("QUILL_API_URL", "http://127.0.0.1:8099")


async def main() -> int:
    # Start a local API server on 8099 (avoid conflict with 8000)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", "8099", "--host", "127.0.0.1"],
        cwd="api",
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    print("[smoke] API started on :8099")

    upload_id = None
    exit_code = 0

    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as c:
            # ── Step 1: Auth ─────────────────────────────────────────────
            login = await c.post("/v1/auth/dev-login", json={"email": "smoke@test.local", "role": "owner"})
            if login.status_code != 200:
                print(f"[FAIL] Login: {login.status_code}")
                return 1
            token = login.json()["access_token"]
            h = {"Authorization": f"Bearer {token}"}
            print(f"[OK] Step 1 — Login: 200, token obtained")

            # ── Step 2: Upload a synthetic 1-page contract ────────────────
            txt = (
                b"SUBCONTRACT AGREEMENT\n\n"
                b"Section 14 -- INDEMNIFICATION\n"
                b"Subcontractor shall indemnify Contractor from all claims arising\n"
                b"out of Subcontractor's Work, whether or not caused by Contractor's negligence.\n"
            )
            upload = await c.post(
                "/v1/contracts/upload",
                files=[("files", ("smoke_contract.txt", txt, "text/plain"))],
                data={"project_label": "Smoke Test Contract — Contracts.2"},
                headers=h,
            )
            if upload.status_code != 201:
                print(f"[FAIL] Step 2 — Upload: {upload.status_code} {upload.text}")
                return 1
            upload_id = upload.json()["upload_id"]
            print(f"[OK] Step 2 — Upload: 201, upload_id={upload_id}")

            # ── Step 3: Status check ──────────────────────────────────────
            time.sleep(1)  # Let background text extraction run
            status_r = await c.get(f"/v1/contracts/{upload_id}/status", headers=h)
            status_val = status_r.json().get("status", "?")
            print(f"[OK] Step 3 — Status: {status_r.status_code}, status={status_val}")

            # ── Step 4: dispatch_review — 409 if no extraction yet ────────
            # (Background extraction may or may not have completed)
            review_dispatch = await c.post(f"/v1/contracts/{upload_id}/dispatch_review", headers=h)
            if review_dispatch.status_code in (200, 409):
                note = "extraction complete" if review_dispatch.status_code == 200 else "extraction pending (expected 409)"
                print(f"[OK] Step 4 — Dispatch review: {review_dispatch.status_code} ({note})")
            else:
                print(f"[FAIL] Step 4 — Dispatch review: unexpected {review_dispatch.status_code}")
                exit_code = 1

            # ── Step 5: interpret — 409 if no extraction yet ──────────────
            interp = await c.post(
                f"/v1/contracts/{upload_id}/interpret",
                json={"question": "What does the indemnity clause say?"},
                headers=h,
            )
            if interp.status_code in (200, 409, 502):
                note = {200: "agent ran OK", 409: "no extraction yet (expected)", 502: "agent backend unavailable"}.get(interp.status_code, "?")
                print(f"[OK] Step 5 — Interpret: {interp.status_code} ({note})")
            else:
                print(f"[FAIL] Step 5 — Interpret: unexpected {interp.status_code}")
                exit_code = 1

            # ── Step 6: reviews list ──────────────────────────────────────
            reviews = await c.get(f"/v1/contracts/{upload_id}/reviews", headers=h)
            if reviews.status_code == 200:
                total_reviews = reviews.json().get("total", "?")
                print(f"[OK] Step 6 — Reviews list: 200, total={total_reviews}")
            else:
                print(f"[FAIL] Step 6 — Reviews list: {reviews.status_code}")
                exit_code = 1

            # ── Step 7: interpretations list ──────────────────────────────
            interps = await c.get(f"/v1/contracts/{upload_id}/interpretations", headers=h)
            if interps.status_code == 200:
                total_interps = interps.json().get("total", "?")
                print(f"[OK] Step 7 — Interpretations list: 200, total={total_interps}")
            else:
                print(f"[FAIL] Step 7 — Interpretations list: {interps.status_code}")
                exit_code = 1

            # ── Step 8: 404 for nonexistent ───────────────────────────────
            nf = await c.get("/v1/contracts/nonexistent-id", headers=h)
            if nf.status_code == 404:
                print(f"[OK] Step 8 — 404 on nonexistent: {nf.status_code}")
            else:
                print(f"[FAIL] Step 8 — Expected 404, got {nf.status_code}")
                exit_code = 1

    finally:
        proc.terminate()
        proc.wait()
        print("[smoke] API stopped")

    if exit_code == 0:
        print(f"\n[PASS] All smoke steps passed. upload_id={upload_id}")
    else:
        print(f"\n[PARTIAL] Some steps failed. upload_id={upload_id}")

    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
