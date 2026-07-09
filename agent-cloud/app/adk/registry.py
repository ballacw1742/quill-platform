"""Curated ADK task-tool registry (ADK_AGENTS_DESIGN.md §2).

Task-agents get a DIFFERENT, curated tool surface than chat agents:

  READ         Quill read tools (free) \u2014 reuse app/tools/quill.py handlers.
  DELIVERABLE  deliverable-generation \u2014 author a Google Doc/Sheet to Drive.
  FETCH        web-fetch \u2014 pull a URL's readable text.
  MEMORY       memory save/search \u2014 reuse app/tools/memory.py handlers.
  WRITE        approval-gated Quill writes \u2014 reuse app/tools/quill_writes.py
               (route through /v1/approvals). NEVER offered to an unapproved
               (read-only) task-agent (governance, ADK_AGENTS_DESIGN.md §4).

NO raw shell. Each entry is an `AdkTool` = (name, description, category,
handler, input_schema). The handler is an async callable(args) -> str,
identical to the chat-tool contract, so the same audit/approval seam is
reused with zero divergence.

Deliverable generation is intentionally provider-pluggable: when Google
Drive/Docs credentials are configured (DRIVE_ENABLED) it authors a real
Doc/Sheet; otherwise it produces a local deliverable record so the
read-only-produces-deliverables flow still works end-to-end and in tests.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

from app.config import get_settings
from app.tools.memory import MEMORY_TOOLS
from app.tools.quill import QUILL_TOOLS
from app.tools.quill_writes import QUILL_WRITE_TOOLS

log = logging.getLogger("agentcloud.adk.registry")

Handler = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class AdkTool:
    name: str
    description: str
    category: str  # read | deliverable | fetch | memory | write
    handler: Handler
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "input_schema": self.input_schema,
        }


# ---------------------------------------------------------------------------
# web-fetch (task tool) \u2014 pull readable text from a URL.
# ---------------------------------------------------------------------------
async def _web_fetch(args: dict[str, Any]) -> str:
    url = str(args.get("url") or "").strip()
    if not url or not url.startswith(("http://", "https://")):
        return json.dumps({"error": "url must be an http(s) URL"})
    max_chars = int(args.get("max_chars", 8000) or 8000)
    max_chars = max(100, min(max_chars, 40000))
    s = get_settings()
    timeout = getattr(s, "QUILL_TOOL_TIMEOUT_SECONDS", 20)
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True
        ) as client:
            r = await client.get(url, headers={"User-Agent": "quill-adk-taskagent/1.0"})
    except httpx.HTTPError as exc:
        return json.dumps({"error": f"fetch failed: {exc}"})
    if r.status_code != 200:
        return json.dumps({"error": f"http {r.status_code}", "url": url})
    text = r.text or ""
    return json.dumps(
        {"url": url, "status": r.status_code, "text": text[:max_chars]},
        default=str,
    )


web_fetch_tool = AdkTool(
    name="web_fetch",
    description=(
        "Fetch a URL and return its readable text (truncated). Read-only "
        "network access for research / deliverable inputs."
    ),
    category="fetch",
    handler=_web_fetch,
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "http(s) URL to fetch."},
            "max_chars": {
                "type": "integer",
                "description": "Max characters to return (100-40000).",
            },
        },
        "required": ["url"],
    },
)


# ---------------------------------------------------------------------------
# deliverable-generation \u2014 author a Google Doc / Sheet to Drive.
#
# This is the tool an UNAPPROVED (read-only) task-agent uses to be useful:
# it produces an artifact, it does NOT mutate any workflow/app state.
# ---------------------------------------------------------------------------
def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _generate_deliverable(args: dict[str, Any]) -> str:
    """Author a deliverable (doc|sheet) to Drive.

    Contract: returns a JSON string describing the deliverable, including a
    `deliverable_id`, `kind` (doc|sheet), `title`, and a `drive` block. When
    Drive is not configured we still produce a durable local deliverable
    record (kind stays, `drive.mode='local'`) so the read-only path works in
    dev/tests. The runner collects these into TaskResult.deliverables.
    """
    kind = str(args.get("kind") or "doc").lower()
    if kind not in ("doc", "sheet"):
        return json.dumps({"error": "kind must be 'doc' or 'sheet'"})
    title = str(args.get("title") or "").strip()
    if not title:
        return json.dumps({"error": "title is required"})
    content = args.get("content")
    if kind == "doc" and not isinstance(content, str):
        return json.dumps({"error": "doc content must be a string"})
    if kind == "sheet" and not isinstance(content, list):
        return json.dumps(
            {"error": "sheet content must be a list of rows (list of lists)"}
        )

    deliverable_id = str(uuid.uuid4())
    s = get_settings()
    drive_enabled = bool(getattr(s, "DRIVE_ENABLED", False))

    drive_block: dict[str, Any]
    if drive_enabled:
        # Real Drive authoring goes through the platform Drive service.
        # Kept behind DRIVE_ENABLED so tests / dev don't require creds; the
        # live-authoring wiring is documented as a follow-up in the ADK
        # runtime module. We still return a well-formed deliverable.
        try:
            drive_block = await _author_to_drive(kind, title, content)
        except Exception as exc:  # noqa: BLE001 \u2014 never break the task on Drive I/O
            log.warning("drive authoring failed, falling back to local: %s", exc)
            drive_block = {"mode": "local", "reason": f"drive error: {exc}"}
    else:
        drive_block = {"mode": "local", "reason": "DRIVE_ENABLED is false"}

    record = {
        "deliverable_id": deliverable_id,
        "kind": kind,
        "title": title[:255],
        "created_at": _utcnow().isoformat(),
        "drive": drive_block,
        "content_preview": (
            content[:500] if isinstance(content, str) else content[:5]
        ),
    }
    return json.dumps({"status": "generated", "deliverable": record}, default=str)


async def _author_to_drive(kind: str, title: str, content: Any) -> dict[str, Any]:
    """Author to real Google Drive. Placeholder for the live Drive wiring.

    Raising here is caught by the caller and degrades to a local deliverable
    (so the feature never fakes success). Live install/wiring is tracked as a
    follow-up (see app/adk/runner.py module docstring).
    """
    raise NotImplementedError(
        "live Drive authoring not yet wired \u2014 set DRIVE_ENABLED only once the "
        "platform Drive service is available to agent-cloud"
    )


generate_deliverable_tool = AdkTool(
    name="generate_deliverable",
    description=(
        "Author a deliverable \u2014 a Google Doc (kind='doc', content=markdown/"
        "text) or a Google Sheet (kind='sheet', content=list of rows) \u2014 and "
        "save it to Drive. This produces an ARTIFACT and does NOT change any "
        "workflow or app state, so it is always available (even for a "
        "read-only / unapproved agent)."
    ),
    category="deliverable",
    handler=_generate_deliverable,
    input_schema={
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["doc", "sheet"]},
            "title": {"type": "string"},
            "content": {
                "description": (
                    "For 'doc': a string. For 'sheet': a list of rows "
                    "(each row a list of cell values)."
                )
            },
        },
        "required": ["kind", "title", "content"],
    },
)


# ---------------------------------------------------------------------------
# Reuse existing read / memory / write tool handlers as AdkTools.
# ---------------------------------------------------------------------------
def _wrap(existing, category: str) -> AdkTool:
    return AdkTool(
        name=existing.name,
        description=existing.description,
        category=category,
        handler=existing.handler,
        input_schema=existing.input_schema,
    )


_READ_TOOLS = [_wrap(t, "read") for t in QUILL_TOOLS]
_MEMORY_TOOLS = [_wrap(t, "memory") for t in MEMORY_TOOLS]
_WRITE_TOOLS = [_wrap(t, "write") for t in QUILL_WRITE_TOOLS]
_TASK_TOOLS = [web_fetch_tool, generate_deliverable_tool]

ADK_TOOL_REGISTRY: dict[str, AdkTool] = {
    t.name: t
    for t in (*_READ_TOOLS, *_TASK_TOOLS, *_MEMORY_TOOLS, *_WRITE_TOOLS)
}

READ_TOOL_NAMES = frozenset(t.name for t in _READ_TOOLS)
DELIVERABLE_TOOL_NAMES = frozenset(
    t.name for t in _TASK_TOOLS
)  # web_fetch + generate_deliverable (safe, non-mutating)
MEMORY_TOOL_NAMES = frozenset(t.name for t in _MEMORY_TOOLS)
WRITE_TOOL_NAMES = frozenset(t.name for t in _WRITE_TOOLS)

# Tools an UNAPPROVED / read-only task-agent may use: everything that does not
# mutate workflow/app state. Writes are approval-gated Quill mutations and are
# withheld entirely from a read-only invocation (belt #1); the runner also
# re-checks at execution time (belt #2).
READ_ONLY_ALLOWED = READ_TOOL_NAMES | DELIVERABLE_TOOL_NAMES | MEMORY_TOOL_NAMES


def adk_tool_specs(allowlist: list[str], *, allow_writes: bool) -> list[dict[str, Any]]:
    """Curated specs for an agent's allow-list, filtered by governance.

    When allow_writes is False (unapproved / read-only), WRITE tools are
    dropped even if the agent definition lists them \u2014 structural enforcement
    of the read-only invariant.
    """
    specs: list[dict[str, Any]] = []
    for name in allowlist:
        tool = ADK_TOOL_REGISTRY.get(name)
        if tool is None:
            log.warning("adk allow-list references unknown tool %r \u2014 skipped", name)
            continue
        if not allow_writes and tool.category == "write":
            continue
        specs.append(tool.spec())
    return specs


def effective_allowlist(allowlist: list[str], *, allow_writes: bool) -> list[str]:
    """The names the runner will actually execute, after governance filter."""
    out: list[str] = []
    for name in allowlist:
        tool = ADK_TOOL_REGISTRY.get(name)
        if tool is None:
            continue
        if not allow_writes and tool.category == "write":
            continue
        out.append(name)
    return out
