"""Quill mock data — synthetic feeds simulating the QPB1 hyperscale build.

Top-level surface:

* `project.QPB1` — fixed metadata describing the fictional 4-building campus.
* `seed.bootstrap()` — one-shot generator (spec corpus, subs, IMS XER, POs).
* `feeders/*` — per-domain event generators.
* `scheduler.run_forever()` — APScheduler harness wiring all feeders.
* `dispatcher.Dispatcher` — receives feeder events, drives the runtime, posts to API.
"""

from __future__ import annotations

__version__ = "0.1.0"
