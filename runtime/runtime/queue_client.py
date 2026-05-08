"""Async HTTP client for the Approval Queue API.

Authentication: the API exposes a service-account auth path via the
`X-Agent-Secret` header (Sprint 1 mode — see api/app/security.py
:func:`require_agent_secret`). We send both `X-Agent-Secret` (canonical)
*and* `Authorization: Bearer <secret>` (forward-compatible) so the runtime
keeps working if the API later switches to a Bearer JWT for service accounts.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from runtime.config import Config, get_config

log = structlog.get_logger(__name__)


class QueueClientError(RuntimeError):
    pass


class QueueClient:
    def __init__(
        self,
        config: Config | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config or get_config()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.config.queue_api_url,
            timeout=self.config.request_timeout_s,
        )

    async def __aenter__(self) -> QueueClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        secret = self.config.agent_shared_secret
        return {
            "X-Agent-Secret": secret,
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
        }

    def _admin_headers(self) -> dict[str, str]:
        # Sprint 1 admin gate uses the same shared secret via X-Admin.
        secret = self.config.agent_shared_secret
        return {
            "X-Admin": secret,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
        admin: bool = False,
    ) -> httpx.Response:
        headers = self._admin_headers() if admin else self._headers()
        try:
            resp = await self._client.request(
                method, url, json=json, params=params, headers=headers
            )
        except httpx.HTTPError as e:
            raise QueueClientError(f"{method} {url} failed: {e}") from e
        if resp.status_code >= 400:
            raise QueueClientError(
                f"{method} {url} → HTTP {resp.status_code}: {resp.text[:500]}"
            )
        return resp

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def create_approval(self, item: dict[str, Any]) -> dict[str, Any]:
        """POST /v1/approvals — returns the created ApprovalOut as a dict.

        `item` is mapped to the API's ApprovalCreate schema; we drop unknown keys
        and provide reasonable defaults.
        """
        body = self._adapt_create_payload(item)
        resp = await self._request("POST", "/v1/approvals", json=body)
        return resp.json()

    async def get_approval(self, approval_id: str) -> dict[str, Any]:
        resp = await self._request("GET", f"/v1/approvals/{approval_id}")
        return resp.json()

    async def list_pending(
        self,
        *,
        lane: int | None = None,
        agent_id: str | None = None,
        workflow: str | None = None,
        status: str | None = "pending",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        params = {
            k: v
            for k, v in {
                "lane": lane,
                "agent_id": agent_id,
                "workflow": workflow,
                "status": status,
                "limit": limit,
                "offset": offset,
            }.items()
            if v is not None
        }
        resp = await self._request("GET", "/v1/approvals", params=params)
        return resp.json()

    async def cancel(self, approval_id: str, reason: str | None = None) -> dict[str, Any]:
        body = {"reason": reason} if reason else None
        resp = await self._request(
            "PATCH", f"/v1/approvals/{approval_id}/cancel", json=body
        )
        return resp.json()

    async def list_agents(self) -> list[dict[str, Any]]:
        resp = await self._request("GET", "/v1/agents")
        return resp.json()

    async def update_agent(self, agent_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """PATCH /v1/agents/{agent_id} — used for registry updates.

        NB: Sprint 1's admin API does not yet expose POST /v1/agents (insert).
        Registration is implicit: any agent that POSTs an approval gets a row
        auto-created by the approvals service. This method is the upsert path
        for tweaking trust tier or default lane after the fact.
        """
        resp = await self._request(
            "PATCH", f"/v1/agents/{agent_id}", json=patch, admin=True
        )
        return resp.json()

    async def health(self) -> dict[str, Any]:
        resp = await self._request("GET", "/v1/admin/health")
        return resp.json()

    # ------------------------------------------------------------------
    # Adapter — runtime payload → API ApprovalCreate
    # ------------------------------------------------------------------
    @staticmethod
    def _adapt_create_payload(item: dict[str, Any]) -> dict[str, Any]:
        """Tolerant adapter: keeps the runtime's keys but drops unknowns the API rejects."""
        allowed = {
            "agent_id",
            "agent_version",
            "workflow",
            "lane",
            "priority",
            "target_system",
            "api_call",
            "payload",
            "source_artifacts",
            "citations",
            "agent_confidence",
            "agent_reasoning",
            "agent_model",
            "agent_prompt_version",
            "agent_input_hash",
            "agent_output_hash",
            "required_approvers",
            "expires_at",
        }
        out = {k: v for k, v in item.items() if k in allowed}
        out.setdefault("agent_version", "0.0.0")
        out.setdefault("priority", "normal")
        out.setdefault("target_system", "none")
        out.setdefault("payload", {})
        return out


__all__ = ["QueueClient", "QueueClientError"]
