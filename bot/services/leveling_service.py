"""Compatibility wrapper for the new XP service."""

from __future__ import annotations

from datetime import datetime

from bot.database.models.level_models import XPGainResult
from bot.services.xp_service import XPService, xp_service
from bot.utils.xp_utils import calculate_level_from_xp


class LevelingService(XPService):
    """Backward-compatible service name for older imports."""

    async def add_message_xp(
        self,
        *,
        guild_id: int,
        user_id: int,
        created_at: datetime | None = None,
        channel_id: int | None = None,
        content: str = "",
    ) -> XPGainResult:
        """Award message XP using legacy optional arguments."""

        return await super().add_message_xp(
            guild_id=guild_id,
            user_id=user_id,
            channel_id=channel_id,
            content=content,
            created_at=created_at,
        )

    async def add_voice_xp(
        self,
        *,
        guild_id: int,
        user_id: int,
        voice_seconds: int | None = None,
        voice_minutes: int | None = None,
        participant_count: int = 1,
    ) -> XPGainResult:
        """Award voice XP using legacy seconds or new minute values."""

        completed_minutes = (
            max(0, voice_seconds) // 60
            if voice_seconds is not None
            else max(0, voice_minutes or 0)
        )
        return await super().add_voice_xp(
            guild_id=guild_id,
            user_id=user_id,
            voice_minutes=completed_minutes,
            participant_count=participant_count,
        )


def calculate_level(xp: int) -> int:
    """Return the level for a total XP value."""

    return calculate_level_from_xp(xp)


leveling_service = xp_service
