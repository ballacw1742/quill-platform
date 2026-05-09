"""Autodesk Platform Services (APS) client — Phase G.4.

Thin async client over the Autodesk Platform Services Model Derivative
API. Used by RvtExtractor to extract metadata + quantities from RVT
files without requiring Revit / Windows.

API docs: https://aps.autodesk.com/en/docs/model-derivative/v2/reference/

Auth model: 2-legged OAuth (client_credentials). The client reads
APS_CLIENT_ID + APS_CLIENT_SECRET from the environment. If either is
missing, `is_available` is False and callers should short-circuit with
a friendly 'not_configured' message rather than failing.

This module is intentionally light on ceremony — the heavy lifting is
keeping URN encoding, scope strings, and content types right. All HTTP
calls go through httpx.AsyncClient so callers can mock cleanly.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("quill.aps")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
APS_BASE = "https://developer.api.autodesk.com"
AUTH_URL = f"{APS_BASE}/authentication/v2/token"
OSS_BUCKETS_URL = f"{APS_BASE}/oss/v2/buckets"  # POST to create bucket
MD_JOB_URL = f"{APS_BASE}/modelderivative/v2/designdata/job"
MD_MANIFEST_URL = f"{APS_BASE}/modelderivative/v2/designdata/{{urn}}/manifest"
MD_METADATA_URL = f"{APS_BASE}/modelderivative/v2/designdata/{{urn}}/metadata"
MD_PROPERTIES_URL = (
    f"{APS_BASE}/modelderivative/v2/designdata/{{urn}}/metadata/{{guid}}/properties"
)

# Scopes needed for upload + Model Derivative
APS_SCOPES = "data:read data:write data:create bucket:create bucket:read"

# Default bucket key (per-account; APS allows arbitrary keys but they must
# be globally unique). We derive a deterministic key from the client_id so
# repeated runs reuse the same bucket.
DEFAULT_BUCKET_PREFIX = "quill-estimates-"


@dataclass
class APSToken:
    access_token: str
    expires_at: float  # epoch seconds

    @property
    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - 30.0)  # 30s safety margin


def _b64url_no_pad(s: str | bytes) -> str:
    if isinstance(s, str):
        s = s.encode("utf-8")
    return base64.urlsafe_b64encode(s).rstrip(b"=").decode("ascii")


class APSClient:
    """Async APS Model Derivative client.

    Usage:
        client = APSClient()
        if not client.is_available:
            ...handle not_configured...
        await client.authenticate()
        urn = await client.upload(rvt_bytes, "model.rvt")
        await client.start_translation(urn)
        await client.poll_translation(urn, timeout_s=60)
        elements = await client.get_metadata(urn)
        quantities = await client.get_quantities(urn)
    """

    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        bucket_key: str | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self.client_id = client_id or os.environ.get("APS_CLIENT_ID") or ""
        self.client_secret = (
            client_secret or os.environ.get("APS_CLIENT_SECRET") or ""
        )
        self.bucket_key = bucket_key or self._default_bucket_key()
        self.timeout_s = timeout_s
        self._token: APSToken | None = None

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------
    @property
    def is_available(self) -> bool:
        return bool(self.client_id) and bool(self.client_secret)

    def _default_bucket_key(self) -> str:
        # APS bucket keys must be lowercase + globally unique.
        cid = (os.environ.get("APS_CLIENT_ID") or "anon").lower()
        # Take first 16 chars of client_id; bucket key length cap is 128.
        suffix = "".join(c for c in cid if c.isalnum())[:16] or "default"
        return f"{DEFAULT_BUCKET_PREFIX}{suffix}"

    # ------------------------------------------------------------------
    # HTTP plumbing
    # ------------------------------------------------------------------
    def _http(self):  # -> httpx.AsyncClient
        # Lazy import keeps httpx out of the hot path for non-RVT users.
        import httpx  # type: ignore

        return httpx.AsyncClient(timeout=self.timeout_s)

    # ------------------------------------------------------------------
    # 2-legged OAuth
    # ------------------------------------------------------------------
    async def authenticate(self) -> str:
        """Acquire a 2-legged OAuth token. Returns the access_token string.

        Caches the token until it's near expiry. Raises RuntimeError on
        non-2xx responses with the APS error body included.
        """
        if not self.is_available:
            raise RuntimeError(
                "APS not configured: APS_CLIENT_ID + APS_CLIENT_SECRET required"
            )
        if self._token and not self._token.is_expired:
            return self._token.access_token

        async with self._http() as http:
            resp = await http.post(
                AUTH_URL,
                data={
                    "grant_type": "client_credentials",
                    "scope": APS_SCOPES,
                },
                auth=(self.client_id, self.client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"APS auth failed ({resp.status_code}): {resp.text[:300]}"
                )
            body = resp.json()
        access_token = body["access_token"]
        expires_in = float(body.get("expires_in", 3600))
        self._token = APSToken(
            access_token=access_token,
            expires_at=time.time() + expires_in,
        )
        return access_token

    async def _bearer_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        token = await self.authenticate()
        h = {"Authorization": f"Bearer {token}"}
        if extra:
            h.update(extra)
        return h

    # ------------------------------------------------------------------
    # Bucket / Object upload
    # ------------------------------------------------------------------
    async def _ensure_bucket(self) -> None:
        """Create the bucket if it doesn't exist. APS returns 409 if it
        already exists, which we treat as success."""
        headers = await self._bearer_headers({"Content-Type": "application/json"})
        body = {"bucketKey": self.bucket_key, "policyKey": "transient"}
        async with self._http() as http:
            resp = await http.post(OSS_BUCKETS_URL, json=body, headers=headers)
            if resp.status_code in (200, 201):
                return
            if resp.status_code == 409:
                return
            raise RuntimeError(
                f"APS bucket create failed ({resp.status_code}): {resp.text[:300]}"
            )

    async def upload(self, file_bytes: bytes, filename: str) -> str:
        """Upload `file_bytes` to APS OSS and return the URN
        (b64url-encoded `urn:adsk.objects:os.object:{bucket}/{filename}`).
        """
        if not self.is_available:
            raise RuntimeError("APS not configured")
        await self._ensure_bucket()

        # Use the simple PUT upload for files <100MB. For larger files,
        # APS requires resumable uploads (out of scope for v0.1; RVTs
        # under 100MB are common for floor-level models).
        safe_name = filename.replace("/", "_")
        url = f"{OSS_BUCKETS_URL}/{self.bucket_key}/objects/{safe_name}"
        headers = await self._bearer_headers(
            {"Content-Type": "application/octet-stream"}
        )
        async with self._http() as http:
            resp = await http.put(url, content=file_bytes, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"APS upload failed ({resp.status_code}): {resp.text[:300]}"
                )
            body = resp.json()
        # APS returns objectId like 'urn:adsk.objects:os.object:bucket/file'.
        object_id = body.get("objectId") or body.get("object_id") or ""
        if not object_id:
            raise RuntimeError("APS upload returned no objectId")
        urn = _b64url_no_pad(object_id)
        return urn

    # ------------------------------------------------------------------
    # Model Derivative — translation
    # ------------------------------------------------------------------
    async def start_translation(self, urn: str) -> dict[str, Any]:
        """Kick off an SVF2 translation job for the URN."""
        if not self.is_available:
            raise RuntimeError("APS not configured")
        headers = await self._bearer_headers(
            {"Content-Type": "application/json", "x-ads-force": "true"}
        )
        body = {
            "input": {"urn": urn},
            "output": {
                "formats": [{"type": "svf2", "views": ["2d", "3d"]}],
            },
        }
        async with self._http() as http:
            resp = await http.post(MD_JOB_URL, json=body, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"APS translation start failed ({resp.status_code}): "
                    f"{resp.text[:300]}"
                )
            return resp.json()

    async def poll_translation(
        self, urn: str, *, timeout_s: float = 60.0, interval_s: float = 3.0
    ) -> str:
        """Poll the manifest until status is 'success' or 'failed', or until
        timeout_s elapses. Returns the final status string.
        """
        if not self.is_available:
            raise RuntimeError("APS not configured")
        deadline = time.time() + timeout_s
        url = MD_MANIFEST_URL.format(urn=urn)
        last_status = "pending"
        while True:
            headers = await self._bearer_headers()
            async with self._http() as http:
                resp = await http.get(url, headers=headers)
                if resp.status_code >= 400:
                    raise RuntimeError(
                        f"APS manifest poll failed ({resp.status_code}): "
                        f"{resp.text[:300]}"
                    )
                manifest = resp.json()
            last_status = manifest.get("status", "pending")
            if last_status in ("success", "failed", "timeout"):
                if last_status != "success":
                    raise RuntimeError(
                        f"APS translation ended with status={last_status}"
                    )
                return last_status
            if time.time() >= deadline:
                raise TimeoutError(
                    f"APS translation polling timed out after {timeout_s}s "
                    f"(last status={last_status})"
                )
            await asyncio.sleep(interval_s)

    # ------------------------------------------------------------------
    # Model Derivative — metadata + quantities
    # ------------------------------------------------------------------
    async def get_metadata(self, urn: str) -> dict[str, Any]:
        """Pull the model's view list + the element list from the default
        view. Returns a dict shaped like:
            { views: [{guid, role, name}], elements: [{objectid, name, ...}] }
        """
        if not self.is_available:
            raise RuntimeError("APS not configured")
        headers = await self._bearer_headers()
        url = MD_METADATA_URL.format(urn=urn)
        async with self._http() as http:
            resp = await http.get(url, headers=headers)
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"APS metadata failed ({resp.status_code}): {resp.text[:300]}"
                )
            views = (resp.json().get("data", {}) or {}).get("metadata", []) or []
        # Pick the first 3D view if present, else the first view of any kind.
        view_guid = None
        for v in views:
            if (v.get("role") or "").lower() == "3d":
                view_guid = v.get("guid")
                break
        if not view_guid and views:
            view_guid = views[0].get("guid")

        elements: list[dict[str, Any]] = []
        if view_guid:
            url2 = MD_PROPERTIES_URL.format(urn=urn, guid=view_guid)
            async with self._http() as http:
                resp = await http.get(url2, headers=headers)
                if resp.status_code in (200, 202):
                    payload = resp.json() or {}
                    elements = (
                        (payload.get("data") or {}).get("collection") or []
                    )

        return {"views": views, "elements": elements}

    async def get_quantities(self, urn: str) -> dict[str, Any]:
        """Roll up quantity properties (Length, Area, Volume, Count) from
        the element list. Best-effort: if the model has no quantity
        parameters, returns an empty dict.
        """
        meta = await self.get_metadata(urn)
        elements = meta.get("elements") or []
        rollup: dict[str, float] = {}
        for el in elements:
            props = el.get("properties") or {}
            # Revit quantity parameters live under common dimension groups
            # like "Dimensions", "Quantities", or category-specific names.
            for group_name, group in props.items():
                if not isinstance(group, dict):
                    continue
                for k, v in group.items():
                    if not isinstance(v, (int, float)):
                        continue
                    key = f"{group_name}::{k}"
                    rollup[key] = rollup.get(key, 0.0) + float(v)
        # Round for readability
        return {k: round(v, 3) for k, v in rollup.items()}


__all__ = ["APSClient", "APSToken"]
