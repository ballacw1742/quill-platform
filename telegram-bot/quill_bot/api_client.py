"""Typed HTTP client for the Quill Approval Queue API.

Sibling to runtime/queue_client.py but tuned for bot needs:
  - admin reads/writes (the bot acts on Charles's behalf)
  - human-friendly response shapes (we already json-decode + light-massage)
  - small surface area (only the methods the bot commands need)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from quill_bot.config import BotConfig

log = logging.getLogger("quill.bot.api_client")


class QuillAPIError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


class QuillAPIClient:
    def __init__(
        self,
        config: BotConfig,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=config.quill_api_url, timeout=timeout
        )

    async def __aenter__(self) -> "QuillAPIClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ------------------------------------------------------------------
    def _admin(self) -> dict[str, str]:
        return {
            "X-Admin": self.config.quill_admin_secret,
            "Content-Type": "application/json",
        }

    def _agent(self) -> dict[str, str]:
        return {
            "X-Agent-Secret": self.config.quill_agent_secret,
            "Authorization": f"Bearer {self.config.quill_agent_secret}",
            "Content-Type": "application/json",
        }

    async def _req(
        self,
        method: str,
        path: str,
        *,
        admin: bool = False,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        headers = self._admin() if admin else self._agent()
        try:
            resp = await self._client.request(
                method, path, json=json, params=params, headers=headers
            )
        except httpx.HTTPError as e:
            raise QuillAPIError(0, f"network error: {e}") from e
        if resp.status_code >= 400:
            raise QuillAPIError(resp.status_code, resp.text)
        if resp.status_code == 204:
            return None
        return resp.json()

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------
    async def list_pending(
        self,
        *,
        lane: int | None = None,
        limit: int = 5,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"status": "pending", "limit": limit, "offset": offset}
        if lane is not None:
            params["lane"] = lane
        return await self._req("GET", "/v1/approvals", params=params)

    async def get_approval(self, approval_id: str) -> dict[str, Any]:
        return await self._req("GET", f"/v1/approvals/{approval_id}")

    async def cancel(self, approval_id: str, reason: str | None = None) -> dict[str, Any]:
        body = {"reason": reason} if reason else None
        return await self._req(
            "PATCH", f"/v1/approvals/{approval_id}/cancel", json=body
        )

    # ------------------------------------------------------------------
    # Estimates (Phase G)
    # ------------------------------------------------------------------
    async def get_estimate_status(self, upload_id: str) -> dict[str, Any]:
        """GET /v1/estimates/{upload_id}/status — returns the StatusOut JSON.

        Read-only; never starts or modifies an estimation run.
        """
        return await self._req("GET", f"/v1/estimates/{upload_id}/status")

    async def list_estimates(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent Documents that belong to the estimates pipeline.

        The API does not currently expose a dedicated estimates-list
        endpoint; we filter the Documents list by artifact_type. Two types
        are relevant:
          - ``aace_classification`` (drawings-classifier output)
          - ``cost_schedule_package`` (estimator-scheduler output)

        We ask for ``limit`` of each and merge by created_at desc, then
        truncate to ``limit`` total. If the API rejects the artifact_type
        filter, fall back to fetching the most recent unfiltered slice and
        filtering client-side.
        """
        merged: list[dict[str, Any]] = []
        for at in ("aace_classification", "cost_schedule_package"):
            try:
                resp = await self._req(
                    "GET",
                    "/v1/documents",
                    params={"artifact_type": at, "limit": limit, "offset": 0},
                )
            except QuillAPIError as e:
                if e.status in (400, 422):
                    # API doesn't accept artifact_type filter — fall back
                    # to fetching the most recent slice once and filtering
                    # client-side; do this only for the first miss.
                    resp = await self._req(
                        "GET", "/v1/documents", params={"limit": 200, "offset": 0}
                    )
                    items_all = (
                        resp.get("items", []) if isinstance(resp, dict) else resp
                    ) or []
                    return [
                        it
                        for it in items_all
                        if it.get("artifact_type")
                        in ("aace_classification", "cost_schedule_package")
                    ][:limit]
                raise
            items = (
                resp.get("items", []) if isinstance(resp, dict) else resp
            ) or []
            merged.extend(items)

        # Sort by created_at desc, fall back to id for stability when the
        # field is absent or equal.
        merged.sort(
            key=lambda d: (d.get("created_at") or "", d.get("id") or ""),
            reverse=True,
        )
        return merged[:limit]

    # ------------------------------------------------------------------
    # Health + scheduler
    # ------------------------------------------------------------------
    async def health(self) -> dict[str, Any]:
        return await self._req("GET", "/v1/admin/health")

    async def scheduler_heartbeat(self, jobs: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._req(
            "POST",
            "/v1/admin/scheduler/jobs/heartbeat",
            admin=True,
            json={"jobs": jobs},
        )

    # ------------------------------------------------------------------
    # User pairing (admin)
    # ------------------------------------------------------------------
    async def pair_user_telegram(
        self, email: str, chat_id: str, telegram_username: str | None = None
    ) -> dict[str, Any]:
        """Pair a Telegram chat_id to a Quill user, by email.

        Bot validates the `/start <code>` HMAC itself (see pairing.py) and
        only after the code is verified does it hit this endpoint with the
        resolved email.
        """
        return await self._req(
            "POST",
            "/v1/admin/users/telegram_pair",
            admin=True,
            json={
                "email": email,
                "chat_id": chat_id,
                "telegram_username": telegram_username,
            },
        )
