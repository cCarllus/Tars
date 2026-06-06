"""Tests for ticket and Tribunal services."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from bot.database.models.ticket_models import (
    TicketEventType,
    TicketStatus,
    TicketType,
    TribunalVoteChoice,
)
from bot.services.ticket_service import TicketService, TicketStateError, TribunalService


def test_ticket_service_persists_main_lifecycle(tmp_path: Path) -> None:
    """Ensure tickets persist creation, triage, acceptance and closure."""

    service = TicketService(tmp_path / "tars.sqlite3")
    ticket = asyncio.run(
        service.create_ticket(
            guild_id=123,
            ticket_type=TicketType.SUPPORT,
            creator_user_id=7,
            target_user_id=None,
            description="preciso de suporte",
            anonymous_report=False,
            expiration_hours=72,
            archive_after_hours=24,
        ),
    )
    triage = asyncio.run(
        service.mark_triage_posted(
            ticket_id=ticket.id,
            triage_channel_id=10,
            triage_message_id=11,
        ),
    )
    accepted = asyncio.run(service.accept_ticket(ticket_id=ticket.id, staff_user_id=42))
    private = asyncio.run(
        service.record_private_channels(
            ticket_id=ticket.id,
            category_channel_id=20,
            private_text_channel_id=21,
            private_voice_channel_id=None,
        ),
    )
    closed = asyncio.run(
        service.close_ticket(
            ticket_id=ticket.id,
            actor_user_id=42,
            reason="Resolvido.",
        ),
    )
    events = asyncio.run(service.list_events(ticket.id))

    assert triage.triage_channel_id == 10
    assert accepted.status == TicketStatus.ACCEPTED
    assert accepted.accepted_by_user_id == 42
    assert private.private_text_channel_id == 21
    assert closed.status == TicketStatus.CLOSED
    assert closed.close_reason == "Resolvido."
    assert [event.event_type for event in events] == [
        TicketEventType.CREATED,
        TicketEventType.TRIAGE_POSTED,
        TicketEventType.ACCEPTED,
        TicketEventType.CLOSED,
    ]


def test_tribunal_service_reaches_configured_majority(tmp_path: Path) -> None:
    """Ensure Tribunal votes are upserted and majority is persisted."""

    ticket_service = TicketService(tmp_path / "tars.sqlite3")
    tribunal_service = TribunalService(ticket_service)
    ticket = asyncio.run(
        ticket_service.create_ticket(
            guild_id=123,
            ticket_type=TicketType.REPORT,
            creator_user_id=7,
            target_user_id=8,
            description="denúncia séria",
            anonymous_report=True,
            expiration_hours=72,
            archive_after_hours=24,
        ),
    )
    asyncio.run(
        ticket_service.accept_ticket(ticket_id=ticket.id, staff_user_id=42),
    )
    asyncio.run(
        ticket_service.escalate_to_tribunal(ticket_id=ticket.id, actor_user_id=42),
    )
    asyncio.run(
        ticket_service.set_tribunal_targets(
            ticket_id=ticket.id,
            actor_user_id=42,
            target_user_ids=(8, 9, 8),
        ),
    )

    first = asyncio.run(
        tribunal_service.cast_vote(
            ticket_id=ticket.id,
            voter_user_id=100,
            choice=TribunalVoteChoice.TIMEOUT,
            reason=None,
            majority_votes=2,
        ),
    )
    second = asyncio.run(
        tribunal_service.cast_vote(
            ticket_id=ticket.id,
            voter_user_id=101,
            choice=TribunalVoteChoice.TIMEOUT,
            reason="24h",
            majority_votes=2,
        ),
    )
    decided = asyncio.run(ticket_service.get_ticket(ticket.id))
    targets = asyncio.run(ticket_service.list_tribunal_target_user_ids(ticket.id))

    assert first.decision_reached is False
    assert second.decision_reached is True
    assert second.decision == TribunalVoteChoice.TIMEOUT
    assert decided is not None
    assert decided.decision == TribunalVoteChoice.TIMEOUT
    assert targets == (8, 9)


def test_ticket_participants_can_be_added_and_removed(tmp_path: Path) -> None:
    """Ensure only added participants can be removed from a ticket."""

    service = TicketService(tmp_path / "tars.sqlite3")
    ticket = asyncio.run(
        service.create_ticket(
            guild_id=123,
            ticket_type=TicketType.REPORT,
            creator_user_id=7,
            target_user_id=8,
            description="caso com participantes",
            anonymous_report=False,
            expiration_hours=72,
            archive_after_hours=24,
        ),
    )

    asyncio.run(
        service.add_participant(
            ticket_id=ticket.id,
            actor_user_id=42,
            user_id=99,
        ),
    )
    participants = asyncio.run(service.list_participant_user_ids(ticket.id))

    assert participants == {7, 8, 99}

    asyncio.run(
        service.remove_added_participant(
            ticket_id=ticket.id,
            actor_user_id=42,
            user_id=99,
        ),
    )
    participants_after_remove = asyncio.run(
        service.list_participant_user_ids(ticket.id),
    )

    assert participants_after_remove == {7, 8}

    with pytest.raises(TicketStateError):
        asyncio.run(
            service.remove_added_participant(
                ticket_id=ticket.id,
                actor_user_id=42,
                user_id=7,
            ),
        )
