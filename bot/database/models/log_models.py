"""Models for rich TARS audit logs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class LogCategory(StrEnum):
    """High-level log categories used for routing and filtering."""

    MODERATION = "moderation"
    MEMBER = "member"
    MESSAGE = "message"
    PROFILE = "profile"
    VOICE = "voice"
    SYSTEM = "system"
    XP_ECONOMY = "xp_economy"


@dataclass(frozen=True)
class LogEventModel:
    """Persisted rich log event."""

    id: int
    guild_id: int
    category: LogCategory
    event_type: str
    title: str
    description: str
    detail_level: int
    actor_user_id: int | None
    target_user_id: int | None
    channel_id: int | None
    message_id: int | None
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class LogEventCreate:
    """Input model for creating a rich log event."""

    guild_id: int
    category: LogCategory
    event_type: str
    title: str
    description: str
    detail_level: int = 2
    actor_user_id: int | None = None
    target_user_id: int | None = None
    channel_id: int | None = None
    message_id: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    color: int | None = None
    thumbnail_url: str | None = None
    image_url: str | None = None


@dataclass(frozen=True)
class LogEventFilters:
    """Dashboard filters for rich log queries."""

    guild_id: int
    query: str = ""
    category: str = ""
    event_type: str = ""
    user_id: int | None = None
    actor_user_id: int | None = None
    channel_id: int | None = None
    limit: int = 100
