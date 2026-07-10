# DRIVE_SETUP.md — Google Drive / Docs / Sheets authoring for Quill deliverables

Phase F wires real Google Drive authoring behind the `DRIVE_ENABLED` flag.
When `DRIVE_ENABLED=false` (the default) every deliverable remains a local record
and no Google credentials are required. Flip to `true` only after completing the
steps below.

---

## Prerequisites

- A Google Cloud project with billing enabled
- `gcloud` CLI (optional but convenient for some steps)
- Owner or Editor access to a Google Drive folder where deliverables will land

---

## Step 1 — Enable the required Google APIs

In the [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services** → **Library**, enable:

| API | Display name |
|-----|-------------|
| `docs.googleapis.com` | Google Docs API |
| `sheets.googleapis.com` | Google Sheets API |
| `drive.googleapis.com` | Google Drive API |

Or via `gcloud`:
```bash
gcloud services enable docs.googleapis.com sheets.googleapis.com drive.googleapis.com \
  --project YOUR_PROJECT_ID
```

---

## Step 2 — Create a service account

1. In the Console → **IAM & Admin** → **Service Accounts** → **Create Service Account**.
2. Give it a descriptive name, e.g. `quill-drive-author`.
3. Grant it **no project-level roles** — access is controlled by Drive folder sharing (Step 3).
4. Click **Done**.
5. Open the new service account → **Keys** tab → **Add Key** → **Create new key** → JSON.
6. Download the JSON key file to a secure location (e.g. `quill-drive-sa.json`).

⚠️ Treat this file as a secret — it grants write access to any Drive folder shared with the SA.

---

## Step 3 — Share a Drive folder with the service account

1. In Google Drive, create (or select) the folder where Quill deliverables should land.
2. Right-click the folder → **Share**.
3. In the **Add people and groups** field, paste the service account's email address
   (found in `quill-drive-sa.json` → `"client_email"` field, e.g. `quill-drive-author@YOUR_PROJECT.iam.gserviceaccount.com`).
4. Set the permission to **Editor**.
5. Click **Send** (no notification needed).
6. Copy the folder ID from the URL:
   `https://drive.google.com/drive/folders/`**`FOLDER_ID_HERE`**

---

## Step 4 — Configure the agent-cloud Cloud Run service

Set these environment variables on the `agent-cloud` Cloud Run service
(Console → Cloud Run → `agent-cloud` → Edit & Deploy New Revision → **Variables & Secrets**):

| Variable | Value | Notes |
|----------|-------|-------|
| `DRIVE_ENABLED` | `true` | Enables real Drive authoring |
| `DRIVE_SERVICE_ACCOUNT_JSON` | *(full JSON key content, single-line)* | See below |
| `DRIVE_FOLDER_ID` | `FOLDER_ID_HERE` (from Step 3) | Leave empty to use SA's My Drive root |

### Setting `DRIVE_SERVICE_ACCOUNT_JSON`

The value must be the **entire content of the JSON key file as a single string**
(Cloud Run env vars cannot contain literal newlines):

```bash
# Collapse to a single line and copy to clipboard
jq -c . quill-drive-sa.json | pbcopy      # macOS
jq -c . quill-drive-sa.json | xclip -sel clip  # Linux
```

Alternatively, store the key in **Secret Manager** and reference it:
```bash
gcloud secrets create quill-drive-sa-json --data-file=quill-drive-sa.json
# Then reference it as a mounted secret (not an env var) — adjust app/config.py accordingly.
```

Or via `gcloud run services update`:
```bash
SA_JSON=$(jq -c . quill-drive-sa.json)
gcloud run services update agent-cloud \
  --region us-central1 \
  --set-env-vars "DRIVE_ENABLED=true,DRIVE_FOLDER_ID=FOLDER_ID_HERE" \
  --set-env-vars "DRIVE_SERVICE_ACCOUNT_JSON=${SA_JSON}"
```

---

## Step 5 — Verify

After deploying, trigger a deliverable generation through the Quill UI or API and
check the task result. A successful Drive deliverable will have:

```json
{
  "drive": {
    "mode": "drive",
    "kind": "doc",
    "doc_id": "1BxiM...",
    "url": "https://docs.google.com/document/d/1BxiM.../edit",
    "title": "..."
  }
}
```

If `drive.mode` is still `"local"` after enabling:
- Check the Cloud Run logs for `drive authoring failed` warning lines — the reason is logged.
- Confirm `DRIVE_ENABLED=true` is set (check `/v1/health` or the service env vars).
- Confirm the service account email is shared on the folder with Editor access.
- Confirm the three APIs are enabled in the project.

---

## Security notes

- The service account has **no project-level IAM roles** — it can only write to folders
  explicitly shared with it (least privilege).
- Rotate the service account key via Console → Service Accounts → Keys → Add Key (then delete the old one).
- For production, prefer mounting the JSON via Secret Manager rather than an env var,
  to avoid the key appearing in Cloud Run's environment variable list.

---

## Local development / tests

`DRIVE_ENABLED` defaults to `false`. Tests mock `author_to_drive` and do not
require real credentials. To test the live path locally:

```bash
export DRIVE_ENABLED=true
export DRIVE_SERVICE_ACCOUNT_JSON="$(jq -c . quill-drive-sa.json)"
export DRIVE_FOLDER_ID="your-folder-id"
cd agent-cloud
.venv/bin/python -c "
import asyncio
from app.drive_author import author_to_drive
result = asyncio.run(author_to_drive('doc', 'Test Doc', 'Hello from Quill!'))
print(result)
"
```

---

*Phase F — wired in `deliverable-phase-f` branch. See `app/drive_author.py` and
`app/adk/registry.py::_author_to_drive` for the implementation.*
