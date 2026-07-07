"""Memory subsystem core: save + similarity search, namespaced (tenant, agent).

Design (design doc §3.2 memory[], §3.3 memory_policy):
  - Rows live in agentcloud_memory (RLS'd like every agentcloud_* table).
  - Embeddings come from app/providers/embeddings (config-gated). Embedding
    calls are network I/O and happen OUTSIDE any DB transaction — same
    "no connection held during model calls" discipline as the orchestrator.
  - If embeddings are unavailable (no key / quota / EMBEDDING_PROVIDER=none)
    or the DB lacks pgvector, everything degrades to text search (ILIKE)
    instead of failing the turn. Vector search only ranks rows that HAVE an
    embedding; rows saved during a degraded window are still found by the
    text fallback.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import tenant_session
from app.models import MemoryRow
from app.providers.embeddings import EmbeddingUnavailableError, get_embedding_provider

log = logging.getLogger("agentcloud.memory")

MEMORY_KINDS = ("fact", "preference", "summary")


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8g}" for x in vec) + "]"


async def _embed_or_none(text_in: str) -> list[float] | None:
    """One embedding, or None (logged) when unavailable. Never raises."""
    try:
        provider = get_embedding_provider()
        return (await provider.embed([text_in]))[0]
    except EmbeddingUnavailableError as exc:
        log.warning("embeddings unavailable — degrading to text path: %s", exc)
        return None


async def _has_embedding_column(db: AsyncSession) -> bool:
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return False
    n = (
        await db.execute(
            text(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'agentcloud_memory' AND column_name = 'embedding'"
            )
        )
    ).scalar_one()
    return bool(n)


async def save_memory(
    tenant_id: str,
    agent_id: str,
    *,
    content: str,
    kind: str = "fact",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist one memory. Embeds first (no DB conn held), then one tx."""
    s = get_settings()
    content = (content or "").strip()[: s.MEMORY_CONTENT_MAX_CHARS]
    if not content:
        return {"error": "memory content is empty"}
    if kind not in MEMORY_KINDS:
        kind = "fact"

    embedding = await _embed_or_none(content)

    memory_id = uuid.uuid4()
    async with tenant_session(tenant_id) as db:
        db.add(
            MemoryRow(
                memory_id=memory_id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                kind=kind,
                content=content,
                meta=metadata or {},
            )
        )
        await db.flush()
        embedded = False
        if embedding is not None and await _has_embedding_column(db):
            await db.execute(
                text(
                    "UPDATE agentcloud_memory "
                    "SET embedding = CAST(:vec AS vector) "
                    "WHERE memory_id = :mid AND tenant_id = :tid"
                ),
                {"vec": _vector_literal(embedding), "mid": memory_id, "tid": tenant_id},
            )
            embedded = True
    return {"memory_id": str(memory_id), "kind": kind, "embedded": embedded}


def _row_dict(mid, kind, content, meta, created_at, score=None) -> dict[str, Any]:
    d: dict[str, Any] = {
        "memory_id": str(mid),
        "kind": kind,
        "content": content,
        "metadata": meta if isinstance(meta, dict) else (json.loads(meta) if meta else {}),
        "created_at": str(created_at),
    }
    if score is not None:
        d["similarity"] = round(float(score), 4)
    return d


async def search_memories(
    tenant_id: str,
    agent_id: str,
    *,
    query: str,
    top_k: int = 5,
    kind: str | None = None,
) -> dict[str, Any]:
    """Top-k memories in the (tenant, agent) namespace.

    Vector similarity (cosine) when embeddings + pgvector are available;
    otherwise ILIKE text fallback. Returns {"mode": ..., "items": [...]}.
    """
    query = (query or "").strip()
    if not query:
        return {"mode": "none", "items": [], "error": "query is empty"}
    top_k = max(1, min(int(top_k), 20))

    embedding = await _embed_or_none(query)

    async with tenant_session(tenant_id) as db:
        use_vector = embedding is not None and await _has_embedding_column(db)
        items: list[dict[str, Any]] = []
        if use_vector:
            kind_clause = "AND kind = :kind" if kind else ""
            rows = (
                await db.execute(
                    text(
                        "SELECT memory_id, kind, content, metadata, created_at, "
                        "1 - (embedding <=> CAST(:vec AS vector)) AS similarity "
                        "FROM agentcloud_memory "
                        "WHERE tenant_id = :tid AND agent_id = :aid "
                        f"AND embedding IS NOT NULL {kind_clause} "
                        "ORDER BY embedding <=> CAST(:vec AS vector) "
                        "LIMIT :k"
                    ),
                    {
                        "vec": _vector_literal(embedding),
                        "tid": tenant_id,
                        "aid": agent_id,
                        "kind": kind,
                        "k": top_k,
                    },
                )
            ).all()
            items = [_row_dict(*r) for r in rows]
            mode = "vector"
        if not use_vector or not items:
            # Text fallback: also covers rows saved without embeddings.
            q = (
                sa.select(
                    MemoryRow.memory_id,
                    MemoryRow.kind,
                    MemoryRow.content,
                    MemoryRow.meta,
                    MemoryRow.created_at,
                )
                .where(
                    MemoryRow.tenant_id == tenant_id,
                    MemoryRow.agent_id == agent_id,
                )
                .order_by(MemoryRow.updated_at.desc())
                .limit(top_k)
            )
            if kind:
                q = q.where(MemoryRow.kind == kind)
            # match any word of the query, not the exact phrase
            words = [w for w in query.split() if len(w) >= 3][:8]
            if words:
                q = q.where(
                    sa.or_(*[MemoryRow.content.ilike(f"%{w}%") for w in words])
                )
            rows = (await db.execute(q)).all()
            text_items = [_row_dict(*r) for r in rows]
            if not use_vector:
                mode = "text"
                items = text_items
            elif text_items:
                mode = "vector+text"
                seen = {i["memory_id"] for i in items}
                items += [i for i in text_items if i["memory_id"] not in seen]
                items = items[:top_k]

        if items:
            ids = [uuid.UUID(i["memory_id"]) for i in items]
            await db.execute(
                sa.update(MemoryRow)
                .where(
                    MemoryRow.tenant_id == tenant_id,
                    MemoryRow.memory_id.in_(ids),
                )
                .values(last_accessed=datetime.now(timezone.utc))
            )
    return {"mode": mode, "items": items}


async def recall_block(
    tenant_id: str, agent_id: str, message: str
) -> str:
    """Bounded auto_recall block for the system prompt ("" when nothing).

    Top MEMORY_RECALL_TOP_K memories relevant to the user message, capped at
    MEMORY_RECALL_MAX_CHARS total. Failures degrade to "" — recall must never
    break a turn.
    """
    s = get_settings()
    try:
        res = await search_memories(
            tenant_id, agent_id, query=message, top_k=s.MEMORY_RECALL_TOP_K
        )
    except Exception:  # noqa: BLE001 — recall is best-effort by design
        log.exception("auto_recall failed — continuing without memories")
        return ""
    items = res.get("items") or []
    if not items:
        return ""
    lines: list[str] = []
    used = 0
    for it in items:
        line = f"- [{it['kind']}] {it['content']}"
        remaining = s.MEMORY_RECALL_MAX_CHARS - used
        if remaining <= 0:
            break
        if len(line) > remaining:
            if not lines:  # always include (a truncated) top hit
                line = line[: max(remaining, 80)] + "…"
                lines.append(line)
            break
        lines.append(line)
        used += len(line)
    if not lines:
        return ""
    return (
        "\n\n# Relevant memories (auto-recalled; may be stale — verify when it matters)\n"
        + "\n".join(lines)
    )
