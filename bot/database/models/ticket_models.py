"""Persistence models for tickets and Tribunal votes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class TicketType(StrEnum):
    """Supported ticket categories."""

    SUPPORT = "support"
    REPORT = "report"


class TicketStatus(StrEnum):
    """Lifecycle states for tickets."""

    OPEN = "open"
    ACCEPTED = "accepted"
    TRIBUNAL = "tribunal"
    CLOSED = "closed"


class TicketEventType(StrEnum):
    """Auditable ticket actions."""

    CREATED = "created"
    TRIAGE_POSTED = "triage_posted"
    ACCEPTED = "accepted"
    PROOF_ADDED = "proof_added"
    PARTICIPANT_ADDED = "participant_added"
    PARTICIPANT_REMOVED = "participant_removed"
    TRIBUNAL_TARGETS_SET = "tribunal_targets_set"
    ESCALATED = "escalated"
    VOTE_CAST = "vote_cast"
    DECISION_REACHED = "decision_reached"
    CLOSED = "closed"


class TribunalVoteChoice(StrEnum):
    """Allowed Tribunal decisions."""

    ABSOLVE = "absolve"
    TIMEOUT = "timeout"
    KICK = "kick"
    TEMP_BAN = "temp_ban"
    PERM_BAN = "perm_ban"
    OTHER = "other"


@dataclass(frozen=True)
class TicketModel:
    """Persisted support/report ticket."""

    id: int
    guild_id: int
    ticket_type: TicketType
    status: TicketStatus
    creator_user_id: int
    target_user_id: int | None
    description: str
    accepted_by_user_id: int | None
    triage_channel_id: int | None
    triage_message_id: int | None
    category_channel_id: int | None
    private_text_channel_id: int | None
    private_voice_channel_id: int | None
    tribunal_message_id: int | None
    decision: TribunalVoteChoice | None
    close_reason: str | None
    anonymous_report: bool
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    closed_at: datetime | None
    archive_after_hours: int


@dataclass(frozen=True)
class TicketEventModel:
    """Persisted audit event for a ticket."""

    id: int
    ticket_id: int
    actor_user_id: int | None
    event_type: TicketEventType
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class VoteModel:
    """Persisted Tribunal vote."""

    id: int
    ticket_id: int
    voter_user_id: int
    choice: TribunalVoteChoice
    reason: str | None
    created_at: datetime
