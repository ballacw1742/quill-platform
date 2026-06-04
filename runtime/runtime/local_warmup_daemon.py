"""Background keep-alive ping daemon for the local LLM.

Ollama unloads idle models after a few minutes by default. The first call
after unload pays a 15-20s cold-start penalty. This daemon hits ``/api/generate``
with an empty prompt and ``keep_alive=30m`` on a short cadence (default 60s)
so the model stays resident.

Run via:

    quill-runtime local warmup --model gemma4:12b-mlx --interval 60

Or import and run programmatically::

    from runtime.local_warmup_daemon import run_forever
    asyncio.run(run_forever(model="gemma4:12b-mlx", interval_s=60))
"""

from __future__ import annotations

import asyncio
import signal
from typing import Optional

import structlog

from runtime.local_llm_client import LocalLLMClient

log = structlog.get_logger(__name__)


async def run_forever(
    *,
    model: Optional[str] = None,
    interval_s: float = 60.0,
    client: Optional[LocalLLMClient] = None,
) -> None:
    """Ping the local model every ``interval_s`` until the process is killed."""
    client = client or LocalLLMClient()
    stop = asyncio.Event()

    def _handle_signal(*_args: object) -> None:
        log.info("local_warmup.shutdown_signal")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:  # pragma: no cover - non-Unix
            pass

    log.info("local_warmup.start", model=model or client.cfg.default_model, interval_s=interval_s)
    while not stop.is_set():
        await client.warmup(model)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except asyncio.TimeoutError:
            continue
    log.info("local_warmup.stopped")


__all__ = ["run_forever"]
