"""Models for the configurable XP and levels system."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class UserLevelModel:
    """Persisted XP state for a guild member."""

    guild_id: int
    user_id: int
    xp: int
    level: int
    messages_count: int
    voice_minutes: int
    daily_streak: int
    weekly_xp: int
    updated_at: datetime
    last_daily: date | None = None
    last_message_xp_at: datetime | None = None


@dataclass(frozen=True)
class LevelRewardModel:
    """Role reward granted when a member reaches a level."""

    guild_id: int
    level: int
    role_id: int


@dataclass(frozen=True)
class XPGainResult:
    """Result of an XP grant attempt."""

    user_level: UserLevelModel
    xp_awarded: int
    previous_level: int
    leveled_up: bool
    ignored_reason: str | None = None

    @property
    def xp(self) -> int:
        """Expose total XP for legacy callers."""

        return self.user_level.xp

    @property
    def level(self) -> int:
        """Expose level for legacy callers."""

        return self.user_level.level

    @property
    def user_id(self) -> int:
        """Expose user ID for legacy callers."""

        return self.user_level.user_id
