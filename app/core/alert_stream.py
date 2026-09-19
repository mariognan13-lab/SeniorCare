"""
Real-time alert broadcast via Server-Sent Events (SSE).

Architecture
────────────
A single in-process ``AlertStreamManager`` holds a mapping

    senior_id → set[asyncio.Queue]

When an SOS state changes (trigger / accept / resolve / cancel) the service
layer calls :func:`broadcast`.  Each connected client drains their own queue
as an async generator fed to ``sse-starlette``'s ``EventSourceResponse``.

This is intentionally single-process.  It means two Railway replicas would
not share the broadcast, but for a care app the number of concurrent active
emergencies is tiny and a single replica is more than sufficient.  If
horizontal scaling becomes a requirement, the queues can be replaced by a
Redis pub/sub channel without changing the service or endpoint layer.

Thread-safety: asyncio.Queue is not thread-safe *across* event loops.  Every
call here runs in the same FastAPI event loop, so there is no cross-loop
sharing. apscheduler dispatches coroutines onto the event loop with
``asyncio.run_coroutine_threadsafe`` already, so this is safe there too.
"""

import asyncio
import json
import logging
from collections import defaultdict
from typing import AsyncIterator
from uuid import UUID

logger = logging.getLogger(__name__)

# Max events buffered per client before the oldest is dropped.  A slow
# Android reader should never miss the "resolved" event — two is fine because
# an emergency produces at most: trigger → accept → resolve (three events).
_QUEUE_MAX = 32


class AlertStreamManager:
    """Pub/sub manager for per-senior SSE streams."""

    def __init__(self) -> None:
        # senior_id (str) → set of queues, one per connected client
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    # ── Publisher ─────────────────────────────────────────────────────────────

    async def broadcast(self, senior_id: str | UUID, event: dict) -> None:
        """
        Push *event* to every client subscribed to *senior_id*.

        Never raises.  A full queue silently drops the oldest item rather than
        blocking the SOS flow or raising to the caller.
        """
        key = str(senior_id)
        queues = self._subscribers.get(key, set())
        if not queues:
            return

        payload = json.dumps(event)
        for q in list(queues):
            try:
                if q.full():
                    # Discard the oldest — the latest state always supersedes it.
                    q.get_nowait()
                q.put_nowait(payload)
            except Exception:
                logger.exception("Failed to enqueue SSE event for senior %s", key)

    # ── Subscriber ────────────────────────────────────────────────────────────

    async def subscribe(self, senior_id: str | UUID) -> AsyncIterator[str]:
        """
        Async generator that yields raw JSON strings for every broadcast.

        The caller wraps this in ``sse-starlette``'s ``ServerSentEvent`` to
        produce the ``data:`` lines the Android EventSource reads.

        Usage::

            async for payload in manager.subscribe(senior_id):
                yield ServerSentEvent(data=payload)

        The generator exits when the client disconnects (the HTTP connection is
        closed) or when a ``None`` sentinel is received, which
        :meth:`broadcast` never sends — so only an explicit call to
        :meth:`close_stream` produces it.
        """
        key = str(senior_id)
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._subscribers[key].add(q)
        logger.debug("SSE subscriber added for senior %s (%d total)", key, len(self._subscribers[key]))

        try:
            while True:
                payload = await q.get()
                if payload is None:
                    break
                yield payload
        finally:
            self._subscribers[key].discard(q)
            if not self._subscribers[key]:
                del self._subscribers[key]
            logger.debug("SSE subscriber removed for senior %s", key)

    async def close_stream(self, senior_id: str | UUID) -> None:
        """Send a sentinel to every subscriber for *senior_id* to close their stream."""
        key = str(senior_id)
        for q in list(self._subscribers.get(key, set())):
            await q.put(None)


# Module-level singleton — imported by sos_service and the SSE endpoint.
manager = AlertStreamManager()
