"""Async lock registry for critical bot operations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class LockRegistry:
    """Provide reusable locks scoped by user or guild."""

    def __init__(self) -> None:
        """Initialize the registry."""

        self._registry_lock = asyncio.Lock()
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._guild_locks: dict[int, asyncio.Lock] = {}

    async def get_user_lock(self, user_id: int) -> asyncio.Lock:
        """Return the lock for user-scoped critical work."""

        async with self._registry_lock:
            return self._user_locks.setdefault(user_id, asyncio.Lock())

    async def get_guild_lock(self, guild_id: int) -> asyncio.Lock:
        """Return the lock for guild-scoped critical work."""

        async with self._registry_lock:
            return self._guild_locks.setdefault(guild_id, asyncio.Lock())

    @asynccontextmanager
    async def user(self, user_id: int) -> AsyncIterator[None]:
        """Serialize critical work for a single user."""

        lock = await self.get_user_lock(user_id)
        async with lock:
            yield

    @asynccontextmanager
    async def guild(self, guild_id: int) -> AsyncIterator[None]:
        """Serialize critical work for a single guild."""

        lock = await self.get_guild_lock(guild_id)
        async with lock:
            yield


lock_registry = LockRegistry()
