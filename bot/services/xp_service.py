"""Persistence and business rules for XP, levels and role rewards."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from bot.config import settings
from bot.database.models.core_models import LevelingConfigModel
from bot.database.models.level_models import (
    LevelRewardModel,
    UserLevelModel,
    XPGainResult,
)
from bot.services.core_config_service import CoreConfigService, core_config_service
from bot.utils.xp_utils import (
    calculate_level_from_xp,
    deterministic_xp_from_range,
    hash_message_content,
    total_xp_required_for_level,
)

LEVELS_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS user_levels (
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        xp INTEGER NOT NULL DEFAULT 0,
        level INTEGER NOT NULL DEFAULT 0,
        messages_count INTEGER NOT NULL DEFAULT 0,
        voice_minutes INTEGER NOT NULL DEFAULT 0,
        daily_streak INTEGER NOT NULL DEFAULT 0,
        last_daily TEXT,
        weekly_xp INTEGER NOT NULL DEFAULT 0,
        last_message_xp_at TEXT,
        last_message_hash TEXT,
        repeated_message_count INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (guild_id, user_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_levels_leaderboard
    ON user_levels (guild_id, xp DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_user_levels_weekly_leaderboard
    ON user_levels (guild_id, weekly_xp DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS level_rewards (
        guild_id INTEGER NOT NULL,
        level INTEGER NOT NULL,
        role_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (guild_id, level, role_id)
    )
    """,
)

ACTIVITY_TICKET_CREATED_XP = 50
ACTIVITY_TICKET_CLOSED_XP = 75
ACTIVITY_TRIBUNAL_PARTICIPATION_XP = 60


class XPService:
    """Manage XP gain, level calculation, leaderboards and rewards."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        config_service: CoreConfigService | None = None,
    ) -> None:
        """Initialize the service with SQLite persistence."""

        self.database_path = Path(database_path or settings.database_path)
        self.config_service = config_service or (
            CoreConfigService(self.database_path)
            if database_path is not None
            else core_config_service
        )
        self._init_lock: asyncio.Lock | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Create all XP-related tables once."""

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
        channel_id: int | None = None,
        content: str = "",
        created_at: datetime | None = None,
    ) -> XPGainResult:
        """Award message XP after cooldown, ignored-channel and spam checks."""

        await self.initialize()
        config = await self._get_config(guild_id)
        current = await self.get_user_level(guild_id=guild_id, user_id=user_id)
        if not config.enabled:
            return _ignored_result(current, "xp_disabled")

        if channel_id in config.ignored_channel_ids:
            return _ignored_result(current, "ignored_channel")

        now = created_at or _utc_now()
        row = await self._fetch_user_row(guild_id=guild_id, user_id=user_id)
        if row is not None and row["last_message_xp_at"]:
            last_message = datetime.fromisoformat(str(row["last_message_xp_at"]))
            elapsed = (now - last_message).total_seconds()
            if elapsed < config.message_cooldown_seconds:
                return _ignored_result(current, "message_cooldown")

        message_hash = hash_message_content(content) if content.strip() else None
        if (
            message_hash is not None
            and row is not None
            and row["last_message_hash"] == message_hash
        ):
            return _ignored_result(current, "repeated_message")

        xp_delta = deterministic_xp_from_range(
            config.message_xp_min,
            config.message_xp_max,
        )
        return await self._apply_xp(
            guild_id=guild_id,
            user_id=user_id,
            xp_delta=xp_delta,
            config=config,
            message_delta=1,
            voice_minutes_delta=0,
            daily_streak=None,
            last_daily=None,
            last_message_xp_at=now,
            last_message_hash=message_hash,
        )

    async def add_voice_xp(
        self,
        *,
        guild_id: int,
        user_id: int,
        voice_minutes: int,
        participant_count: int = 1,
    ) -> XPGainResult:
        """Award voice XP by completed minute with a group-call bonus."""

        await self.initialize()
        config = await self._get_config(guild_id)
        current = await self.get_user_level(guild_id=guild_id, user_id=user_id)
        if not config.enabled:
            return _ignored_result(current, "xp_disabled")

        completed_minutes = max(0, voice_minutes)
        if completed_minutes == 0:
            return _ignored_result(current, "voice_too_short")

        xp_per_minute = deterministic_xp_from_range(
            config.voice_xp_min_per_minute,
            config.voice_xp_max_per_minute,
        )
        xp_delta = completed_minutes * xp_per_minute
        if participant_count >= 2:
            xp_delta = int(xp_delta * config.voice_group_bonus_multiplier)

        return await self._apply_xp(
            guild_id=guild_id,
            user_id=user_id,
            xp_delta=xp_delta,
            config=config,
            message_delta=0,
            voice_minutes_delta=completed_minutes,
            daily_streak=None,
            last_daily=None,
            last_message_xp_at=None,
            last_message_hash=None,
        )

    async def claim_daily(
        self,
        *,
        guild_id: int,
        user_id: int,
        claimed_at: datetime | None = None,
    ) -> XPGainResult:
        """Claim the daily XP reward with a streak bonus up to seven days."""

        await self.initialize()
        config = await self._get_config(guild_id)
        current = await self.get_user_level(guild_id=guild_id, user_id=user_id)
        if not config.enabled:
            return _ignored_result(current, "xp_disabled")

        today = (claimed_at or _utc_now()).date()
        if current.last_daily == today:
            return _ignored_result(current, "daily_already_claimed")

        if current.last_daily == today - timedelta(days=1):
            streak = min(current.daily_streak + 1, config.daily_max_streak)
        else:
            streak = 1

        xp_delta = config.daily_base_xp + (
            max(0, streak - 1) * config.daily_streak_bonus_xp
        )
        return await self._apply_xp(
            guild_id=guild_id,
            user_id=user_id,
            xp_delta=xp_delta,
            config=config,
            message_delta=0,
            voice_minutes_delta=0,
            daily_streak=streak,
            last_daily=today,
            last_message_xp_at=None,
            last_message_hash=None,
        )

    async def add_xp(
        self,
        *,
        guild_id: int,
        user_id: int,
        amount: int,
    ) -> XPGainResult:
        """Add an administrative XP adjustment to a member."""

        config = await self._get_config(guild_id)
        return await self._apply_xp(
            guild_id=guild_id,
            user_id=user_id,
            xp_delta=amount,
            config=config,
            message_delta=0,
            voice_minutes_delta=0,
            daily_streak=None,
            last_daily=None,
            last_message_xp_at=None,
            last_message_hash=None,
        )

    async def set_user_level(
        self,
        *,
        guild_id: int,
        user_id: int,
        level: int,
    ) -> UserLevelModel:
        """Set a member to the cumulative XP floor for a level."""

        config = await self._get_config(guild_id)
        target_xp = total_xp_required_for_level(
            max(0, level),
            quadratic=config.level_formula_quadratic,
            linear=config.level_formula_linear,
            constant=config.level_formula_constant,
        )
        await self.initialize()
        row = await asyncio.to_thread(
            self._set_user_xp_sync,
            guild_id,
            user_id,
            target_xp,
            max(0, level),
        )
        return _row_to_user_level(row)

    async def reward_ticket_created(
        self,
        *,
        guild_id: int,
        user_id: int,
    ) -> XPGainResult:
        """Reward a user for creating an accepted ticket."""

        return await self.add_xp(
            guild_id=guild_id,
            user_id=user_id,
            amount=ACTIVITY_TICKET_CREATED_XP,
        )

    async def reward_ticket_closed(
        self,
        *,
        guild_id: int,
        user_id: int,
    ) -> XPGainResult:
        """Reward a conductor for closing a handled ticket."""

        return await self.add_xp(
            guild_id=guild_id,
            user_id=user_id,
            amount=ACTIVITY_TICKET_CLOSED_XP,
        )

    async def reward_tribunal_participation(
        self,
        *,
        guild_id: int,
        user_id: int,
    ) -> XPGainResult:
        """Reward a judge or participant for Tribunal activity."""

        return await self.add_xp(
            guild_id=guild_id,
            user_id=user_id,
            amount=ACTIVITY_TRIBUNAL_PARTICIPATION_XP,
        )

    async def get_user_level(self, *, guild_id: int, user_id: int) -> UserLevelModel:
        """Return a persisted user level or an empty in-memory record."""

        await self.initialize()
        row = await self._fetch_user_row(guild_id=guild_id, user_id=user_id)
        if row is not None:
            return _row_to_user_level(row)

        return UserLevelModel(
            guild_id=guild_id,
            user_id=user_id,
            xp=0,
            level=0,
            messages_count=0,
            voice_minutes=0,
            daily_streak=0,
            weekly_xp=0,
            updated_at=_utc_now(),
        )

    async def get_user_rank(
        self,
        *,
        guild_id: int,
        user_id: int,
        weekly: bool = False,
    ) -> int | None:
        """Return a member's leaderboard position."""

        leaderboard = await self.get_leaderboard(
            guild_id=guild_id,
            limit=1000,
            weekly=weekly,
        )
        for index, record in enumerate(leaderboard, start=1):
            if record.user_id == user_id:
                return index
        return None

    async def get_leaderboard(
        self,
        *,
        guild_id: int,
        limit: int = 10,
        weekly: bool = False,
    ) -> list[UserLevelModel]:
        """Return the global or weekly leaderboard for a guild."""

        await self.initialize()
        order_column = "weekly_xp" if weekly else "xp"
        rows = await asyncio.to_thread(
            self._fetch_all,
            f"""
            SELECT guild_id, user_id, xp, level, messages_count, voice_minutes,
                   daily_streak, last_daily, weekly_xp, last_message_xp_at,
                   updated_at
            FROM user_levels
            WHERE guild_id = ?
            ORDER BY {order_column} DESC, updated_at ASC
            LIMIT ?
            """,
            (guild_id, max(1, limit)),
        )
        return [_row_to_user_level(row) for row in rows]

    async def get_guild_stats(self, *, guild_id: int) -> dict[str, int]:
        """Return aggregate XP statistics for the Dashboard."""

        await self.initialize()
        row = await asyncio.to_thread(
            self._fetch_one,
            """
            SELECT
                COUNT(*) AS members_count,
                COALESCE(SUM(xp), 0) AS total_xp,
                COALESCE(SUM(messages_count), 0) AS messages_count,
                COALESCE(SUM(voice_minutes), 0) AS voice_minutes
            FROM user_levels
            WHERE guild_id = ?
            """,
            (guild_id,),
        )
        if row is None:
            return {
                "members_count": 0,
                "total_xp": 0,
                "messages_count": 0,
                "voice_minutes": 0,
            }
        return {
            "members_count": int(row["members_count"]),
            "total_xp": int(row["total_xp"]),
            "messages_count": int(row["messages_count"]),
            "voice_minutes": int(row["voice_minutes"]),
        }

    async def set_level_reward(
        self,
        *,
        guild_id: int,
        level: int,
        role_id: int,
    ) -> None:
        """Persist a role reward for a level."""

        await self.initialize()
        await asyncio.to_thread(
            self._execute,
            """
            INSERT INTO level_rewards (guild_id, level, role_id, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, level, role_id) DO NOTHING
            """,
            (guild_id, max(0, level), role_id, _utc_now().isoformat()),
        )

    async def delete_level_reward(
        self,
        *,
        guild_id: int,
        level: int,
        role_id: int,
    ) -> None:
        """Delete a configured level role reward."""

        await self.initialize()
        await asyncio.to_thread(
            self._execute,
            """
            DELETE FROM level_rewards
            WHERE guild_id = ? AND level = ? AND role_id = ?
            """,
            (guild_id, level, role_id),
        )

    async def list_level_rewards(self, *, guild_id: int) -> list[LevelRewardModel]:
        """Return all role rewards for a guild."""

        await self.initialize()
        rows = await asyncio.to_thread(
            self._fetch_all,
            """
            SELECT guild_id, level, role_id
            FROM level_rewards
            WHERE guild_id = ?
            ORDER BY level ASC, role_id ASC
            """,
            (guild_id,),
        )
        return [
            LevelRewardModel(
                guild_id=int(row["guild_id"]),
                level=int(row["level"]),
                role_id=int(row["role_id"]),
            )
            for row in rows
        ]

    async def list_earned_rewards(
        self,
        *,
        guild_id: int,
        level: int,
    ) -> list[LevelRewardModel]:
        """Return role rewards earned up to a level."""

        await self.initialize()
        rows = await asyncio.to_thread(
            self._fetch_all,
            """
            SELECT guild_id, level, role_id
            FROM level_rewards
            WHERE guild_id = ? AND level <= ?
            ORDER BY level ASC, role_id ASC
            """,
            (guild_id, level),
        )
        return [
            LevelRewardModel(
                guild_id=int(row["guild_id"]),
                level=int(row["level"]),
                role_id=int(row["role_id"]),
            )
            for row in rows
        ]

    async def _apply_xp(
        self,
        *,
        guild_id: int,
        user_id: int,
        xp_delta: int,
        config: LevelingConfigModel,
        message_delta: int,
        voice_minutes_delta: int,
        daily_streak: int | None,
        last_daily: date | None,
        last_message_xp_at: datetime | None,
        last_message_hash: str | None,
    ) -> XPGainResult:
        await self.initialize()
        previous = await self.get_user_level(guild_id=guild_id, user_id=user_id)
        row = await asyncio.to_thread(
            self._apply_xp_sync,
            guild_id,
            user_id,
            xp_delta,
            config,
            message_delta,
            voice_minutes_delta,
            daily_streak,
            last_daily,
            last_message_xp_at,
            last_message_hash,
        )
        user_level = _row_to_user_level(row)
        return XPGainResult(
            user_level=user_level,
            xp_awarded=max(0, xp_delta),
            previous_level=previous.level,
            leveled_up=user_level.level > previous.level,
        )

    async def _get_config(self, guild_id: int) -> LevelingConfigModel:
        dashboard_config = await self.config_service.get_config(guild_id)
        return dashboard_config.leveling

    async def _fetch_user_row(
        self,
        *,
        guild_id: int,
        user_id: int,
    ) -> sqlite3.Row | None:
        return await asyncio.to_thread(
            self._fetch_one,
            """
            SELECT guild_id, user_id, xp, level, messages_count, voice_minutes,
                   daily_streak, last_daily, weekly_xp, last_message_xp_at,
                   updated_at, last_message_hash
            FROM user_levels
            WHERE guild_id = ? AND user_id = ?
            """,
            (guild_id, user_id),
        )

    def _initialize_sync(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            for statement in LEVELS_SCHEMA:
                connection.execute(statement)
            connection.commit()

    def _apply_xp_sync(
        self,
        guild_id: int,
        user_id: int,
        xp_delta: int,
        config: LevelingConfigModel,
        message_delta: int,
        voice_minutes_delta: int,
        daily_streak: int | None,
        last_daily: date | None,
        last_message_xp_at: datetime | None,
        last_message_hash: str | None,
    ) -> sqlite3.Row:
        now = _utc_now().isoformat()
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT xp, messages_count, voice_minutes, daily_streak, weekly_xp
                FROM user_levels
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            ).fetchone()
            current_xp = int(row["xp"]) if row else 0
            new_xp = max(0, current_xp + xp_delta)
            new_level = calculate_level_from_xp(
                new_xp,
                quadratic=config.level_formula_quadratic,
                linear=config.level_formula_linear,
                constant=config.level_formula_constant,
            )
            values = (
                guild_id,
                user_id,
                new_xp,
                new_level,
                (int(row["messages_count"]) if row else 0) + message_delta,
                (int(row["voice_minutes"]) if row else 0) + voice_minutes_delta,
                (
                    daily_streak
                    if daily_streak is not None
                    else (int(row["daily_streak"]) if row else 0)
                ),
                last_daily.isoformat() if last_daily else None,
                (int(row["weekly_xp"]) if row else 0) + max(0, xp_delta),
                last_message_xp_at.isoformat() if last_message_xp_at else None,
                last_message_hash,
                0,
                now,
            )
            connection.execute(
                """
                INSERT INTO user_levels (
                    guild_id, user_id, xp, level, messages_count, voice_minutes,
                    daily_streak, last_daily, weekly_xp, last_message_xp_at,
                    last_message_hash, repeated_message_count, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    xp = excluded.xp,
                    level = excluded.level,
                    messages_count = excluded.messages_count,
                    voice_minutes = excluded.voice_minutes,
                    daily_streak = excluded.daily_streak,
                    last_daily = COALESCE(excluded.last_daily, user_levels.last_daily),
                    weekly_xp = excluded.weekly_xp,
                    last_message_xp_at = COALESCE(
                        excluded.last_message_xp_at,
                        user_levels.last_message_xp_at
                    ),
                    last_message_hash = COALESCE(
                        excluded.last_message_hash,
                        user_levels.last_message_hash
                    ),
                    repeated_message_count = excluded.repeated_message_count,
                    updated_at = excluded.updated_at
                """,
                values,
            )
            connection.commit()
            return cast(
                sqlite3.Row,
                connection.execute(
                    """
                    SELECT guild_id, user_id, xp, level, messages_count, voice_minutes,
                           daily_streak, last_daily, weekly_xp, last_message_xp_at,
                           updated_at
                    FROM user_levels
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (guild_id, user_id),
                ).fetchone(),
            )

    def _set_user_xp_sync(
        self,
        guild_id: int,
        user_id: int,
        xp: int,
        level: int,
    ) -> sqlite3.Row:
        now = _utc_now().isoformat()
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute(
                """
                INSERT INTO user_levels (
                    guild_id, user_id, xp, level, messages_count, voice_minutes,
                    daily_streak, weekly_xp, repeated_message_count, updated_at
                )
                VALUES (?, ?, ?, ?, 0, 0, 0, ?, 0, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET
                    xp = excluded.xp,
                    level = excluded.level,
                    weekly_xp = excluded.weekly_xp,
                    updated_at = excluded.updated_at
                """,
                (guild_id, user_id, max(0, xp), max(0, level), max(0, xp), now),
            )
            connection.commit()
            return cast(
                sqlite3.Row,
                connection.execute(
                    """
                    SELECT guild_id, user_id, xp, level, messages_count, voice_minutes,
                           daily_streak, last_daily, weekly_xp, last_message_xp_at,
                           updated_at
                    FROM user_levels
                    WHERE guild_id = ? AND user_id = ?
                    """,
                    (guild_id, user_id),
                ).fetchone(),
            )

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


def _ignored_result(user_level: UserLevelModel, reason: str) -> XPGainResult:
    return XPGainResult(
        user_level=user_level,
        xp_awarded=0,
        previous_level=user_level.level,
        leveled_up=False,
        ignored_reason=reason,
    )


def _row_to_user_level(row: sqlite3.Row) -> UserLevelModel:
    last_daily = row["last_daily"]
    last_message_xp_at = row["last_message_xp_at"]
    return UserLevelModel(
        guild_id=int(row["guild_id"]),
        user_id=int(row["user_id"]),
        xp=int(row["xp"]),
        level=int(row["level"]),
        messages_count=int(row["messages_count"]),
        voice_minutes=int(row["voice_minutes"]),
        daily_streak=int(row["daily_streak"]),
        weekly_xp=int(row["weekly_xp"]),
        last_daily=date.fromisoformat(str(last_daily)) if last_daily else None,
        last_message_xp_at=(
            datetime.fromisoformat(str(last_message_xp_at))
            if last_message_xp_at
            else None
        ),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
    )


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)  # noqa: UP017


xp_service = XPService()
