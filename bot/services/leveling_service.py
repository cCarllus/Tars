"""XP and leaderboard persistence for the core leveling feature."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot.config import settings
from bot.database.models.core_models import LevelingConfigModel, UserLevelModel
from bot.services.core_config_service import CoreConfigService, core_config_service

LEVELING_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS core_user_levels (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        xp INTEGER NOT NULL DEFAULT 0,
        level INTEGER NOT NULL DEFAULT 0,
        message_count INTEGER NOT NULL DEFAULT 0,
        voice_seconds INTEGER NOT NULL DEFAULT 0,
        last_message_xp_at TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (guild_id, user_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_core_user_levels_leaderboard
    ON core_user_levels (guild_id, xp DESC)
    """,
)

MESSAGE_XP = 15
MESSAGE_XP_COOLDOWN_SECONDS = 60
VOICE_XP_PER_MINUTE = 5
LEVEL_XP_FACTOR = 100


class LevelingService:
    """Manage XP gain, level calculation and leaderboard queries."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        config_service: CoreConfigService | None = None,
    ) -> None:
        """Initialize the service."""

        self.database_path = Path(database_path or settings.database_path)
        self.config_service = config_service or (
            CoreConfigService(self.database_path)
            if database_path is not None
            else core_config_service
        )
        self._init_lock: asyncio.Lock | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Create required leveling tables once."""

        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            if self._initialized:
                return

            await asyncio.to_thread(self._initialize_sync)
            self._initialized = True

    async def add_message_xp(
        self,
        *,
        guild_id: int,
        user_id: int,
        created_at: datetime | None = None,
    ) -> UserLevelModel | None:
        """Add message XP if the user is outside the cooldown window."""

        await self.initialize()
        now = created_at or datetime.now(tz=timezone.utc)  # noqa: UP017
        row = await asyncio.to_thread(
            self._fetch_one,
            """
            SELECT guild_id, user_id, xp, level, message_count, voice_seconds,
                   last_message_xp_at, updated_at
            FROM core_user_levels
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        )
        if row is not None and row["last_message_xp_at"]:
            last_message = datetime.fromisoformat(str(row["last_message_xp_at"]))
            config = await self._get_leveling_config(guild_id)
            if not config.enabled:
                return _row_to_user_level(row)
            if (now - last_message).total_seconds() < config.message_cooldown_seconds:
                return _row_to_user_level(row)
        else:
            config = await self._get_leveling_config(guild_id)
            if not config.enabled:
                return None

        return await self._add_xp(
            guild_id=guild_id,
            user_id=user_id,
            xp_delta=config.message_xp,
            message_delta=1,
            voice_seconds_delta=0,
            last_message_xp_at=now,
            config=config,
        )

    async def add_voice_xp(
        self,
        *,
        guild_id: int,
        user_id: int,
        voice_seconds: int,
    ) -> UserLevelModel | None:
        """Add XP for completed voice activity."""

        if voice_seconds < 60:
            return await self.get_user_level(guild_id=guild_id, user_id=user_id)

        config = await self._get_leveling_config(guild_id)
        if not config.enabled:
            return await self.get_user_level(guild_id=guild_id, user_id=user_id)

        xp_delta = max(0, voice_seconds // 60) * config.voice_xp_per_minute
        return await self._add_xp(
            guild_id=guild_id,
            user_id=user_id,
            xp_delta=xp_delta,
            message_delta=0,
            voice_seconds_delta=voice_seconds,
            last_message_xp_at=None,
            config=config,
        )

    async def get_user_level(self, *, guild_id: int, user_id: int) -> UserLevelModel:
        """Return a user level record, creating an empty one if needed."""

        await self.initialize()
        row = await asyncio.to_thread(
            self._fetch_one,
            """
            SELECT guild_id, user_id, xp, level, message_count, voice_seconds,
                   last_message_xp_at, updated_at
            FROM core_user_levels
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        )
        if row is not None:
            return _row_to_user_level(row)

        now = datetime.now(tz=timezone.utc)  # noqa: UP017
        return UserLevelModel(
            guild_id=guild_id,
            user_id=user_id,
            xp=0,
            level=0,
            message_count=0,
            voice_seconds=0,
            updated_at=now,
        )

    async def get_leaderboard(
        self,
        *,
        guild_id: int,
        limit: int = 10,
    ) -> list[UserLevelModel]:
        """Return the top XP users for a guild."""

        await self.initialize()
        rows = await asyncio.to_thread(
            self._fetch_all,
            """
            SELECT guild_id, user_id, xp, level, message_count, voice_seconds,
                   last_message_xp_at, updated_at
            FROM core_user_levels
            WHERE guild_id = ?
            ORDER BY xp DESC, updated_at ASC
            LIMIT ?
            """,
            (guild_id, limit),
        )
        return [_row_to_user_level(row) for row in rows]

    async def _add_xp(
        self,
        *,
        guild_id: int,
        user_id: int,
        xp_delta: int,
        message_delta: int,
        voice_seconds_delta: int,
        last_message_xp_at: datetime | None,
        config: LevelingConfigModel,
    ) -> UserLevelModel:
        await self.initialize()
        now = datetime.now(tz=timezone.utc)  # noqa: UP017
        await asyncio.to_thread(
            self._execute,
            """
            INSERT INTO core_user_levels (
                guild_id,
                user_id,
                xp,
                level,
                message_count,
                voice_seconds,
                last_message_xp_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                xp = core_user_levels.xp + excluded.xp,
                level = ?,
                message_count = core_user_levels.message_count + excluded.message_count,
                voice_seconds = core_user_levels.voice_seconds + excluded.voice_seconds,
                last_message_xp_at = COALESCE(
                    excluded.last_message_xp_at,
                    core_user_levels.last_message_xp_at
                ),
                updated_at = excluded.updated_at
            """,
            (
                guild_id,
                user_id,
                xp_delta,
                calculate_level_with_factor(xp_delta, config.level_xp_factor),
                message_delta,
                voice_seconds_delta,
                last_message_xp_at.isoformat() if last_message_xp_at else None,
                now.isoformat(),
                calculate_level_for_existing_xp(
                    guild_id=guild_id,
                    user_id=user_id,
                    xp_delta=xp_delta,
                    database_path=self.database_path,
                    level_xp_factor=config.level_xp_factor,
                ),
            ),
        )
        return await self.get_user_level(guild_id=guild_id, user_id=user_id)

    async def _get_leveling_config(self, guild_id: int) -> LevelingConfigModel:
        config = await self.config_service.get_config(guild_id)
        return config.leveling

    def _initialize_sync(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            for statement in LEVELING_SCHEMA:
                connection.execute(statement)
            connection.commit()

    def _execute(self, query: str, params: Iterable[Any]) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(query, tuple(params))
            connection.commit()

    def _fetch_one(
        self,
        query: str,
        params: Iterable[Any],
    ) -> sqlite3.Row | None:
        rows = self._fetch_all(query, params)
        return rows[0] if rows else None

    def _fetch_all(
        self,
        query: str,
        params: Iterable[Any],
    ) -> list[sqlite3.Row]:
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(query, tuple(params))
            return list(cursor.fetchall())


def calculate_level(xp: int) -> int:
    """Return the display level for an XP value."""

    return max(0, xp // LEVEL_XP_FACTOR)


def calculate_level_with_factor(xp: int, level_xp_factor: int) -> int:
    """Return the display level for an XP value and configured factor."""

    return max(0, xp // max(1, level_xp_factor))


def calculate_level_for_existing_xp(
    *,
    guild_id: int,
    user_id: int,
    xp_delta: int,
    database_path: Path,
    level_xp_factor: int = LEVEL_XP_FACTOR,
) -> int:
    """Calculate the post-update level for an UPSERT statement."""

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT xp
            FROM core_user_levels
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        ).fetchone()
    current_xp = int(row[0]) if row else 0
    return calculate_level_with_factor(current_xp + xp_delta, level_xp_factor)


def _row_to_user_level(row: sqlite3.Row) -> UserLevelModel:
    return UserLevelModel(
        guild_id=int(row["guild_id"]),
        user_id=int(row["user_id"]),
        xp=int(row["xp"]),
        level=int(row["level"]),
        message_count=int(row["message_count"]),
        voice_seconds=int(row["voice_seconds"]),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


leveling_service = LevelingService()
