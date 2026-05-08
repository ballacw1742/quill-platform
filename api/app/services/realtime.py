"""In-process pub-sub for real-time approval notifications.

Sprint 1 keeps this single-process. Sprint 4+ will swap to Redis pub/sub.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


class Broadcaster:
    """Tiny fan-out queue. Each subscriber gets its own asyncio.Queue."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue[str]) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    async def publish(self, event: dict[str, Any]) -> None:
        msg = json.dumps(event, default=str)
        async with self._lock:
            dead: list[asyncio.Queue[str]] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                self._subscribers.discard(q)


broadcaster = Broadcaster()
