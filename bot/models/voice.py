"""Voice domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class VoiceSession:
    """Persisted private voice session."""

    id: int
    guild_id: int
    owner_id: int
    channel_id: int
    created_at: datetime
    last_updated: datetime
