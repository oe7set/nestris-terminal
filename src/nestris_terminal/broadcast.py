"""Fan-out of JSON events to WebSocket clients (bounded queues, drop when slow)."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any

QUEUE_SIZE = 256


@dataclass(eq=False)
class Subscription:
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))


class Broadcaster:
    def __init__(self) -> None:
        self._subscribers: set[Subscription] = set()

    def subscribe(self) -> Subscription:
        sub = Subscription()
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subscribers.discard(sub)

    @property
    def count(self) -> int:
        return len(self._subscribers)

    def publish(self, event: dict[str, Any]) -> None:
        for sub in self._subscribers:
            with contextlib.suppress(asyncio.QueueFull):
                sub.queue.put_nowait(event)
