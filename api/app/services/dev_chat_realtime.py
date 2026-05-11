"""Dev Chat in-process pub-sub broadcaster (Sprint DC.1).

Mirrors app.services.realtime.Broadcaster but is a separate instance
so dev-chat WS traffic doesn't pollute the approvals channel.

Usage:
    from app.services.dev_chat_realtime import dev_chat_broadcaster

    # Publish from route/service:
    await dev_chat_broadcaster.publish({"type": "task_started", ...})

    # Subscribe from WS handler:
    q = await dev_chat_broadcaster.subscribe()
    msg = await q.get()  # JSON string
    await dev_chat_broadcaster.unsubscribe(q)
"""

from __future__ import annotations

from app.services.realtime import Broadcaster

# Module-level singleton — shared across all workers in the same process.
dev_chat_broadcaster: Broadcaster = Broadcaster()
