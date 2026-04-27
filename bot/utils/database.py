"""SQLite persistence helpers for bot state."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot.config import settings
from bot.models.voice import VoiceSession

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS active_voice_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        owner_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        last_updated TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_active_voice_sessions_owner
    ON active_voice_sessions (guild_id, owner_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS command_execution_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER,
        user_id INTEGER,
        command_name TEXT NOT NULL,
        success INTEGER NOT NULL,
        duration_ms REAL,
        error TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS action_audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER,
        user_id INTEGER,
        action TEXT NOT NULL,
        success INTEGER NOT NULL,
        duration_ms REAL,
        error TEXT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rate_limit_hits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER,
        user_id INTEGER,
        action TEXT NOT NULL,
        scope TEXT NOT NULL,
        retry_after REAL NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
)


class SQLiteDatabase:
    """Small async wrapper around SQLite operations."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        """Initialize the database wrapper."""

        self.database_path = Path(database_path or settings.database_path)
        self._init_lock: asyncio.Lock | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Create required database tables once."""

        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            if self._initialized:
                return

            await asyncio.to_thread(self._initialize_sync)
            self._initialized = True

    async def upsert_voice_session(
        self,
        *,
        guild_id: int,
        owner_id: int,
        channel_id: int,
    ) -> None:
        """Create or update an active voice session."""

        await self.initialize()
        now = _utc_now()
        await asyncio.to_thread(
            self._execute,
            """
            INSERT INTO active_voice_sessions (
                guild_id,
                owner_id,
                channel_id,
                created_at,
                last_updated
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(channel_id) DO UPDATE SET
                guild_id = excluded.guild_id,
                owner_id = excluded.owner_id,
                last_updated = excluded.last_updated
            """,
            (guild_id, owner_id, channel_id, now, now),
        )

    async def delete_voice_session_by_channel(self, channel_id: int) -> None:
        """Delete an active voice session by channel ID."""

        await self.initialize()
        await asyncio.to_thread(
            self._execute,
            "DELETE FROM active_voice_sessions WHERE channel_id = ?",
            (channel_id,),
        )

    async def list_voice_sessions(self) -> list[VoiceSession]:
        """Return all persisted active voice sessions."""

        await self.initialize()
        rows = await asyncio.to_thread(
            self._fetch_all,
            """
            SELECT id, guild_id, owner_id, channel_id, created_at, last_updated
            FROM active_voice_sessions
            ORDER BY id
            """,
            (),
        )
        return [
            VoiceSession(
                id=int(row["id"]),
                guild_id=int(row["guild_id"]),
                owner_id=int(row["owner_id"]),
                channel_id=int(row["channel_id"]),
                created_at=_parse_datetime(str(row["created_at"])),
                last_updated=_parse_datetime(str(row["last_updated"])),
            )
            for row in rows
        ]

    async def log_action(
        self,
        *,
        action: str,
        success: bool,
        guild_id: int | None = None,
        user_id: int | None = None,
        duration_ms: float | None = None,
        error: str | None = None,
    ) -> None:
        """Persist an action audit entry."""

        await self.initialize()
        await asyncio.to_thread(
            self._execute,
            """
            INSERT INTO action_audit_log (
                guild_id,
                user_id,
                action,
                success,
                duration_ms,
                error,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                user_id,
                action,
                int(success),
                duration_ms,
                error,
                _utc_now(),
            ),
        )

    async def log_rate_limit_hit(
        self,
        *,
        action: str,
        scope: str,
        retry_after: float,
        guild_id: int | None = None,
        user_id: int | None = None,
    ) -> None:
        """Persist a rate limit hit."""

        await self.initialize()
        await asyncio.to_thread(
            self._execute,
            """
            INSERT INTO rate_limit_hits (
                guild_id,
                user_id,
                action,
                scope,
                retry_after,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (guild_id, user_id, action, scope, retry_after, _utc_now()),
        )

    def _initialize_sync(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)
            connection.commit()

    def _execute(self, query: str, params: Iterable[Any]) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(query, tuple(params))
            connection.commit()

    def _fetch_all(self, query: str, params: Iterable[Any]) -> list[sqlite3.Row]:
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(query, tuple(params))
            return list(cursor.fetchall())


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()  # noqa: UP017


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


database = SQLiteDatabase()
