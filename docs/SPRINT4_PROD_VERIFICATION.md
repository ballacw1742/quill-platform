# Sprint 4 — Post-merge prod verification (for the orchestrator)

Run AFTER merging `sprint4-ai-daemons` to `main` and after CI
`backend-deploy.yml` finishes deploying `quill-agents`.

The four dispatcher daemons already run on Charles's Mac Studio as
LaunchAgents (`com.quill.{contract,contract-review,classify,estimate}-dispatcher`),
pointed at prod, idle-polling until prod has work + the new blob endpoints.

```bash
PROD=https://quill-agents-894031978246.us-central1.run.app
S=$(cat ~/.openclaw/quill-daemons/.agent_secret)   # never inline secrets
```

## 0) Confirm the new blob routes deployed

```bash
curl -s -H "X-Agent-Secret: $S" "$PROD/v1/contracts/00000000-0000-0000-0000-000000000000/extracted/x"
# BEFORE merge: {"detail":"Not Found"}   (no route)
# AFTER  merge: {"detail":"contract not found"}   (route live)
curl -s -H "X-Agent-Secret: $S" "$PROD/v1/estimates/00000000-0000-0000-0000-000000000000/extracted/x"
# AFTER merge: {"detail":"upload not found"}
```

## 1) Owner JWT (DEV_AUTH_FALLBACK=true on prod; stored JWT may be stale — re-login)

```bash
PW=$(cat ~/.openclaw/quill-daemons/.owner_pw)
TOK=$(curl -s -X POST "$PROD/v1/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"<OWNER_EMAIL>\",\"password\":\"$PW\"}" | jq -r .access_token)
```

## 2) Daemon logs to watch (local Mac Studio)

```bash
tail -f ~/Library/Logs/quill/contract-dispatcher.log \
        ~/Library/Logs/quill/contract-review-dispatcher.log \
        ~/Library/Logs/quill/classify-dispatcher.log \
        ~/Library/Logs/quill/estimate-dispatcher.log
```

Healthy idle = 200s on the `?status=` list polls. During a gate run expect:
`*_blob_not_found` (local miss) → `GET $PROD/.../extracted/<file> 200`
(new endpoint) → `*.running_agent` → `*.dispatched` with an approval id.
A single `json_extraction` failure + automatic retry from contract-extractor
is a known quirk (KNOWN_ISSUES Sprint 4 #5), not a regression.

## 3) Gate A on prod (name artifacts `smoke-…`; append-only)

```bash
UP=$(curl -s -X POST "$PROD/v1/contracts/upload" -H "Authorization: Bearer $TOK" \
  -F 'files=@smoke-prod-subcontract.pdf;type=application/pdf' \
  -F 'project_label=smoke-prod-gateA' | jq -r .upload_id)
watch -n5 "curl -s -H \"Authorization: Bearer $TOK\" $PROD/v1/contracts/$UP/status | jq .status"
# status=extracted → contract daemon fires. Find + approve the extraction item:
curl -s -H "Authorization: Bearer $TOK" \
  "$PROD/v1/approvals?workflow=contract_extraction.publish&status=pending&limit=50" | jq '.items[].id'
curl -s -X POST "$PROD/v1/approvals/<ID>/decide" -H "Authorization: Bearer $TOK" \
  -H 'Content-Type: application/json' -d '{"decision":"approve","auth_assertion":"dev-fallback"}'
# reviewer daemon then fires (needs extracted_fields — stamped by the fix in
# this branch). Approve workflow=contract_review.publish the same way. Then:
curl -s -H "Authorization: Bearer $TOK" "$PROD/v1/contracts/$UP" \
  | jq '{status, review_artifact_id, extracted_fields: (.extracted_fields != null)}'
curl -s -H "Authorization: Bearer $TOK" "$PROD/v1/contracts/$UP/reviews" | jq .
# PASS: status=reviewed, review_artifact_id set, reviews.total >= 1
```

## 4) Gate B on prod

```bash
UP=$(curl -s -X POST "$PROD/v1/estimates/upload" -H "Authorization: Bearer $TOK" \
  -F 'files=@smoke-prod-site-plan.pdf;type=application/pdf' \
  -F 'files=@smoke-prod-model.ifc;type=application/octet-stream' \
  -F 'project_label=smoke-prod-gateB' | jq -r .upload_id)
# status → queued → classify daemon → approve workflow=aace_classification.publish
# then:
curl -s -X POST "$PROD/v1/estimates/$UP/start_estimation" -H "Authorization: Bearer $TOK"
# estimator daemon (opus-4-7, ~2 min) → approve workflow=cost_schedule_package.publish
curl -s -H "Authorization: Bearer $TOK" "$PROD/v1/estimates/$UP/export?format=xer" | head -3
# PASS: first line starts with ERMHDR
```

Ready-made drivers (edit `BASE`/creds): `~/.openclaw/quill-daemons/gates/gate_a.py`
and `gate_b.py` — they ran these exact sequences against the local boot.

## Caveats for prod

- **Prod blob persistence:** Cloud Run has no GCS volume; extraction blobs
  live on the instance's local disk. If the instance recycles between
  extraction and daemon fetch, the blob endpoint 404s and the daemon
  falls back / retries. If Gate A/B on prod hits persistent
  `extracted text not found`, re-POST `dispatch_extraction` or re-upload.
- **pypdf on prod:** verify contract PDF extraction reaches
  `status=extracted` on prod; `pypdf` is missing from pyproject (KNOWN_ISSUES
  Sprint 4 #6). If prod says "all files failed text extraction", add
  `pypdf` + `python-docx` to pyproject deps and redeploy.
- **Daemon repoint after merge:** LaunchAgents run out of
  `~/.openclaw/quill-daemons/env.sh` → `QUILL_REPO=` the sprint4 worktree.
  After merge, either keep the worktree or repoint `QUILL_REPO` to
  `quill-platform` (main) and `launchctl kickstart -k` the four services.
- **Test runs write daemon markers:** running `pytest api/tests` from the
  repo the daemons point at drops priority markers in `_state/*_requests/`
  that reference non-existent prod rows → harmless 404 retry loops.
  Clean with `rm -f _state/*_requests/*.json`.
