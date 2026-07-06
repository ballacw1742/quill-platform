"""quill-dispatch-worker — Cloud Run service hosting the four Quill dispatch loops.

Sprint 5.5: replaces the four launchd daemons that used to run on Charles's
Mac Studio (com.quill.{contract,contract-review,classify,estimate}-dispatcher).

One container runs all four polling dispatchers as supervised asyncio tasks:

- contract          → contract-extractor  → contract_extraction.publish
- contract_review   → contract-reviewer   → contract_review.publish
- classification    → design-classifier   → aace_classification.publish
- estimator         → estimator-scheduler → cost_schedule_package.publish

State: Postgres (``RUNTIME_STATE_DATABASE_URL`` → runtime_dispatch_state
table, atomic claim semantics — see runtime/runtime/state_store.py). The
container filesystem is treated as ephemeral scratch.

Auth: X-Agent-Secret (``AGENT_SHARED_SECRET``) for every API call — the
dispatchers are service-to-service agents and never hold a human JWT.

HTTP surface (Cloud Run requires a listener on $PORT):

- ``GET /healthz``  — liveness: supervisor + per-dispatcher task state
- ``GET /statusz``  — per-dispatcher state-store summary (done/error counts)
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import FastAPI

from runtime.config import get_config

log = structlog.get_logger("quill_worker")

_RESTART_INITIAL_S = 5.0
_RESTART_MAX_S = 300.0

# dispatcher key → (factory, human label)
_DISPATCHERS: dict[str, str] = {
    "contract": "ContractDispatcher",
    "contract_review": "ContractReviewDispatcher",
    "classification": "ClassificationDispatcher",
    "estimator": "EstimatorDispatcher",
}


def _build_dispatcher(name: str) -> Any:
    """Construct a dispatcher by key. Import lazily so a broken module only
    breaks its own loop, not the whole worker."""
    if name == "contract":
        from runtime.contract_dispatcher import ContractDispatcher

        return ContractDispatcher()
    if name == "contract_review":
        from runtime.contract_review_dispatcher import ContractReviewDispatcher

        return ContractReviewDispatcher()
    if name == "classification":
        from runtime.classification_dispatcher import ClassificationDispatcher

        return ClassificationDispatcher()
    if name == "estimator":
        from runtime.estimator_dispatcher import EstimatorDispatcher

        return EstimatorDispatcher()
    raise ValueError(f"unknown dispatcher: {name}")


class DispatcherSupervisor:
    """Runs one dispatcher loop forever, restarting on crash with backoff."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.task: asyncio.Task[None] | None = None
        self.dispatcher: Any | None = None
        self.started_at: str | None = None
        self.restarts = 0
        self.last_error: str | None = None
        self.last_error_at: str | None = None
        self._stopping = False

    def start(self) -> None:
        self.task = asyncio.create_task(self._run(), name=f"dispatcher:{self.name}")

    async def stop(self) -> None:
        self._stopping = True
        if self.dispatcher is not None:
            self.dispatcher.stop()
        if self.task is not None:
            try:
                await asyncio.wait_for(self.task, timeout=20)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.task.cancel()

    async def _run(self) -> None:
        backoff = _RESTART_INITIAL_S
        while not self._stopping:
            try:
                self.dispatcher = _build_dispatcher(self.name)
                self.started_at = datetime.now(UTC).isoformat()
                log.info("worker.dispatcher_starting", dispatcher=self.name)
                await self.dispatcher.start()  # returns on .stop()
                if self._stopping:
                    log.info("worker.dispatcher_stopped", dispatcher=self.name)
                    return
                # start() returned without stop() → treat as crash-ish exit.
                raise RuntimeError("dispatcher loop exited unexpectedly")
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                self.restarts += 1
                self.last_error = str(exc)[:500]
                self.last_error_at = datetime.now(UTC).isoformat()
                log.error(
                    "worker.dispatcher_crashed",
                    dispatcher=self.name,
                    err=self.last_error,
                    restarts=self.restarts,
                    retry_in_s=backoff,
                )
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    return
                backoff = min(backoff * 2, _RESTART_MAX_S)

    def health(self) -> dict[str, Any]:
        alive = self.task is not None and not self.task.done()
        return {
            "alive": alive,
            "started_at": self.started_at,
            "restarts": self.restarts,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at,
        }


_supervisors: dict[str, DispatcherSupervisor] = {}


def _enabled_dispatchers() -> list[str]:
    raw = os.environ.get("QUILL_WORKER_DISPATCHERS", "").strip()
    if not raw:
        return list(_DISPATCHERS.keys())
    names = [n.strip() for n in raw.split(",") if n.strip()]
    unknown = [n for n in names if n not in _DISPATCHERS]
    if unknown:
        raise ValueError(f"unknown dispatchers in QUILL_WORKER_DISPATCHERS: {unknown}")
    return names


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()  # configures structlog JSON logging
    if not os.environ.get("RUNTIME_STATE_DATABASE_URL", "").strip():
        # Fail loudly at boot: on Cloud Run the filesystem is ephemeral, so
        # file-based dispatcher state would re-dispatch after every restart.
        raise RuntimeError(
            "RUNTIME_STATE_DATABASE_URL is required for quill-dispatch-worker "
            "(file-based dispatcher state is not safe on Cloud Run)"
        )
    log.info(
        "worker.boot",
        api_url=cfg.queue_api_url,
        prompts_repo=str(cfg.prompts_repo_path),
        dispatchers=_enabled_dispatchers(),
    )
    for name in _enabled_dispatchers():
        sup = DispatcherSupervisor(name)
        _supervisors[name] = sup
        sup.start()
    try:
        yield
    finally:
        log.info("worker.shutdown_begin")
        await asyncio.gather(
            *(sup.stop() for sup in _supervisors.values()),
            return_exceptions=True,
        )
        log.info("worker.shutdown_complete")


app = FastAPI(title="quill-dispatch-worker", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    details = {name: sup.health() for name, sup in _supervisors.items()}
    all_alive = bool(details) and all(d["alive"] for d in details.values())
    return {
        "status": "ok" if all_alive else "degraded",
        "service": "quill-dispatch-worker",
        "dispatchers": details,
    }


@app.get("/statusz")
async def statusz() -> dict[str, Any]:
    """State-store summaries (hits Postgres; keep off the health-check path)."""
    out: dict[str, Any] = {}
    for name, sup in _supervisors.items():
        store = getattr(sup.dispatcher, "_store", None)
        if store is None:
            out[name] = {"backend": "file"}
            continue
        try:
            out[name] = await store.status_summary()
        except Exception as exc:  # noqa: BLE001
            out[name] = {"error": str(exc)[:300]}
    return {"service": "quill-dispatch-worker", "state": out}
