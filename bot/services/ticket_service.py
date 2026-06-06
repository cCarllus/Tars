"""Ticket and Tribunal persistence services."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from bot.config import settings
from bot.database.models.ticket_models import (
    TicketActionLogModel,
    TicketEventModel,
    TicketEventType,
    TicketModel,
    TicketProofModel,
    TicketStatus,
    TicketType,
    TribunalVoteChoice,
    VoteModel,
)
from bot.logger import logger

TICKET_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        ticket_type TEXT NOT NULL,
        status TEXT NOT NULL,
        creator_user_id INTEGER NOT NULL,
        target_user_id INTEGER,
        description TEXT NOT NULL,
        accepted_by_user_id INTEGER,
        triage_channel_id INTEGER,
        triage_message_id INTEGER,
        category_channel_id INTEGER,
        private_text_channel_id INTEGER,
        private_voice_channel_id INTEGER,
        tribunal_message_id INTEGER,
        decision TEXT,
        close_reason TEXT,
        anonymous_report INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        closed_at TEXT,
        archive_after_hours INTEGER NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tickets_guild_status
    ON tickets (guild_id, status, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS ticket_participants (
        ticket_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (ticket_id, user_id, role),
        FOREIGN KEY (ticket_id) REFERENCES tickets(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ticket_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        actor_user_id INTEGER,
        event_type TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (ticket_id) REFERENCES tickets(id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ticket_events_ticket_created
    ON ticket_events (ticket_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS ticket_proofs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        actor_user_id INTEGER NOT NULL,
        description TEXT NOT NULL,
        links_json TEXT NOT NULL,
        attachment_urls_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (ticket_id) REFERENCES tickets(id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ticket_proofs_ticket_created
    ON ticket_proofs (ticket_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS ticket_action_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        actor_user_id INTEGER,
        action TEXT NOT NULL,
        details TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (ticket_id) REFERENCES tickets(id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ticket_action_logs_ticket_created
    ON ticket_action_logs (ticket_id, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS tribunal_votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL,
        voter_user_id INTEGER NOT NULL,
        choice TEXT NOT NULL,
        reason TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(ticket_id, voter_user_id),
        FOREIGN KEY (ticket_id) REFERENCES tickets(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tribunal_targets (
        ticket_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (ticket_id, user_id),
        FOREIGN KEY (ticket_id) REFERENCES tickets(id)
    )
    """,
)


@dataclass(frozen=True)
class VoteTally:
    """Current vote count for one Tribunal ticket."""

    counts: dict[TribunalVoteChoice, int]
    decision: TribunalVoteChoice | None
    decision_reached: bool


class TicketService:
    """Manage ticket lifecycle persistence and audit history."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        """Initialize the ticket service."""

        self.database_path = Path(database_path or settings.database_path)
        self._init_lock: asyncio.Lock | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Create required ticket tables once."""

        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            if self._initialized:
                return

            await asyncio.to_thread(self._initialize_sync)
            self._initialized = True

    async def create_ticket(
        self,
        *,
        guild_id: int,
        ticket_type: TicketType,
        creator_user_id: int,
        description: str,
        target_user_id: int | None,
        anonymous_report: bool,
        expiration_hours: int,
        archive_after_hours: int,
    ) -> TicketModel:
        """Create a ticket with participant and history records."""

        await self.initialize()
        now = _utc_now()
        expires_at = now + timedelta(hours=expiration_hours)
        ticket_id = await asyncio.to_thread(
            self._create_ticket_sync,
            guild_id,
            ticket_type.value,
            creator_user_id,
            target_user_id,
            description,
            anonymous_report,
            now.isoformat(),
            expires_at.isoformat(),
            archive_after_hours,
        )
        await self.record_event(
            ticket_id=ticket_id,
            actor_user_id=creator_user_id,
            event_type=TicketEventType.CREATED,
            payload={
                "ticket_type": ticket_type.value,
                "target_user_id": target_user_id,
                "anonymous_report": anonymous_report,
            },
        )
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            msg = f"Ticket {ticket_id} was not persisted"
            raise RuntimeError(msg)
        return ticket

    async def get_ticket(self, ticket_id: int) -> TicketModel | None:
        """Return one ticket by ID."""

        await self.initialize()
        row = await asyncio.to_thread(
            self._fetch_one,
            "SELECT * FROM tickets WHERE id = ?",
            (ticket_id,),
        )
        return _ticket_from_row(row) if row else None

    async def get_ticket_by_private_channel(
        self,
        channel_id: int,
    ) -> TicketModel | None:
        """Return the ticket that owns a private text channel."""

        await self.initialize()
        row = await asyncio.to_thread(
            self._fetch_one,
            "SELECT * FROM tickets WHERE private_text_channel_id = ?",
            (channel_id,),
        )
        return _ticket_from_row(row) if row else None

    async def list_tickets(
        self,
        *,
        guild_id: int,
        status: TicketStatus | None = None,
        ticket_type: TicketType | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        search: str | None = None,
        limit: int = 100,
    ) -> list[TicketModel]:
        """Return tickets for Dashboard filters and searches."""

        await self.initialize()
        params: list[Any] = [guild_id]
        where = ["guild_id = ?"]

        if status is not None:
            where.append("status = ?")
            params.append(status.value)

        if ticket_type is not None:
            where.append("ticket_type = ?")
            params.append(ticket_type.value)

        if created_after is not None:
            where.append("created_at >= ?")
            params.append(created_after.isoformat())

        if created_before is not None:
            where.append("created_at <= ?")
            params.append(created_before.isoformat())

        if search:
            where.append("(description LIKE ? OR CAST(id AS TEXT) LIKE ?)")
            pattern = f"%{search}%"
            params.extend([pattern, pattern])

        params.append(limit)
        rows = await asyncio.to_thread(
            self._fetch_all,
            f"""
            SELECT *
            FROM tickets
            WHERE {" AND ".join(where)}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        )
        return [_ticket_from_row(row) for row in rows]

    async def list_expired_tickets(self) -> list[TicketModel]:
        """Return non-closed tickets whose expiration time has passed."""

        await self.initialize()
        rows = await asyncio.to_thread(
            self._fetch_all,
            """
            SELECT *
            FROM tickets
            WHERE status != ? AND expires_at <= ?
            ORDER BY id ASC
            LIMIT 100
            """,
            (TicketStatus.CLOSED.value, _utc_now().isoformat()),
        )
        return [_ticket_from_row(row) for row in rows]

    async def list_archive_ready_tickets(self) -> list[TicketModel]:
        """Return closed tickets ready for private channel deletion."""

        await self.initialize()
        rows = await asyncio.to_thread(
            self._fetch_all,
            """
            SELECT *
            FROM tickets
            WHERE status = ?
              AND closed_at IS NOT NULL
              AND private_text_channel_id IS NOT NULL
            ORDER BY id ASC
            LIMIT 100
            """,
            (TicketStatus.CLOSED.value,),
        )
        now = _utc_now()
        tickets = [_ticket_from_row(row) for row in rows]
        return [
            ticket
            for ticket in tickets
            if ticket.closed_at is not None
            and ticket.closed_at + timedelta(hours=ticket.archive_after_hours) <= now
        ]

    async def mark_triage_posted(
        self,
        *,
        ticket_id: int,
        triage_channel_id: int,
        triage_message_id: int,
    ) -> TicketModel:
        """Persist the triage message location."""

        await self._update_ticket(
            ticket_id,
            """
            triage_channel_id = ?,
            triage_message_id = ?,
            updated_at = ?
            """,
            (triage_channel_id, triage_message_id, _utc_now().isoformat()),
        )
        await self.record_event(
            ticket_id=ticket_id,
            actor_user_id=None,
            event_type=TicketEventType.TRIAGE_POSTED,
            payload={
                "triage_channel_id": triage_channel_id,
                "triage_message_id": triage_message_id,
            },
        )
        return await self._require_ticket(ticket_id)

    async def accept_ticket(self, *, ticket_id: int, staff_user_id: int) -> TicketModel:
        """Mark a ticket as accepted by staff."""

        ticket = await self._require_ticket(ticket_id)
        if ticket.status not in {TicketStatus.OPEN, TicketStatus.ACCEPTED}:
            msg = "Apenas tickets abertos podem ser aceitos."
            raise TicketStateError(msg)

        await self._update_ticket(
            ticket_id,
            """
            status = ?,
            accepted_by_user_id = ?,
            updated_at = ?
            """,
            (TicketStatus.ACCEPTED.value, staff_user_id, _utc_now().isoformat()),
        )
        await self._add_participant(ticket_id, staff_user_id, "staff")
        await self.record_event(
            ticket_id=ticket_id,
            actor_user_id=staff_user_id,
            event_type=TicketEventType.ACCEPTED,
            payload={"accepted_by_user_id": staff_user_id},
        )
        return await self._require_ticket(ticket_id)

    async def record_private_channels(
        self,
        *,
        ticket_id: int,
        category_channel_id: int,
        private_text_channel_id: int,
        private_voice_channel_id: int | None,
    ) -> TicketModel:
        """Persist private channel IDs created for an accepted ticket."""

        await self._update_ticket(
            ticket_id,
            """
            category_channel_id = ?,
            private_text_channel_id = ?,
            private_voice_channel_id = ?,
            updated_at = ?
            """,
            (
                category_channel_id,
                private_text_channel_id,
                private_voice_channel_id,
                _utc_now().isoformat(),
            ),
        )
        return await self._require_ticket(ticket_id)

    async def set_private_voice_channel(
        self,
        *,
        ticket_id: int,
        private_voice_channel_id: int | None,
    ) -> TicketModel:
        """Persist or clear the optional private voice channel ID."""

        await self._update_ticket(
            ticket_id,
            "private_voice_channel_id = ?, updated_at = ?",
            (private_voice_channel_id, _utc_now().isoformat()),
        )
        return await self._require_ticket(ticket_id)

    async def add_proof(
        self,
        *,
        ticket_id: int,
        actor_user_id: int,
        description: str,
        links: tuple[str, ...] = (),
        attachment_urls: tuple[str, ...] = (),
    ) -> TicketProofModel:
        """Persist proof submitted by a ticket participant.

        Args:
            ticket_id: Ticket receiving the proof.
            actor_user_id: Discord user ID that submitted the proof.
            description: Human-readable proof context.
            links: External links supplied by the user.
            attachment_urls: Discord attachment URLs copied from the interaction.

        Returns:
            The persisted proof record.
        """

        await self.initialize()
        created_at = _utc_now().isoformat()
        proof_id = await asyncio.to_thread(
            self._insert_proof_sync,
            ticket_id,
            actor_user_id,
            description,
            links,
            attachment_urls,
            created_at,
        )
        await self.record_event(
            ticket_id=ticket_id,
            actor_user_id=actor_user_id,
            event_type=TicketEventType.PROOF_ADDED,
            payload={
                "proof_id": proof_id,
                "description": description,
                "links": list(links),
                "attachment_urls": list(attachment_urls),
            },
        )
        proof = await self.get_proof(proof_id)
        if proof is None:
            msg = f"Proof {proof_id} was not persisted"
            raise RuntimeError(msg)
        return proof

    async def get_proof(self, proof_id: int) -> TicketProofModel | None:
        """Return one proof record by ID."""

        await self.initialize()
        row = await asyncio.to_thread(
            self._fetch_one,
            "SELECT * FROM ticket_proofs WHERE id = ?",
            (proof_id,),
        )
        return _proof_from_row(row) if row else None

    async def list_proofs(self, ticket_id: int) -> list[TicketProofModel]:
        """Return all proofs submitted for a ticket."""

        await self.initialize()
        rows = await asyncio.to_thread(
            self._fetch_all,
            """
            SELECT *
            FROM ticket_proofs
            WHERE ticket_id = ?
            ORDER BY id ASC
            """,
            (ticket_id,),
        )
        return [_proof_from_row(row) for row in rows]

    async def log_action(
        self,
        *,
        ticket_id: int,
        actor_user_id: int | None,
        action: str,
        details: str,
        payload: dict[str, Any] | None = None,
    ) -> TicketActionLogModel:
        """Persist an important conductor or staff action.

        Args:
            ticket_id: Ticket receiving the log.
            actor_user_id: Discord user ID responsible for the action, if known.
            action: Stable action key for filtering and audits.
            details: User-readable action summary in PT-BR.
            payload: Optional structured context.

        Returns:
            The persisted action log record.
        """

        await self.initialize()
        created_at = _utc_now().isoformat()
        action_log_id = await asyncio.to_thread(
            self._insert_action_log_sync,
            ticket_id,
            actor_user_id,
            action,
            details,
            payload or {},
            created_at,
        )
        await self.record_event(
            ticket_id=ticket_id,
            actor_user_id=actor_user_id,
            event_type=TicketEventType.ACTION_LOGGED,
            payload={
                "action_log_id": action_log_id,
                "action": action,
                "details": details,
            },
        )
        action_log = await self.get_action_log(action_log_id)
        if action_log is None:
            msg = f"Action log {action_log_id} was not persisted"
            raise RuntimeError(msg)
        return action_log

    async def get_action_log(self, action_log_id: int) -> TicketActionLogModel | None:
        """Return one action log by ID."""

        await self.initialize()
        row = await asyncio.to_thread(
            self._fetch_one,
            "SELECT * FROM ticket_action_logs WHERE id = ?",
            (action_log_id,),
        )
        return _action_log_from_row(row) if row else None

    async def list_action_logs(self, ticket_id: int) -> list[TicketActionLogModel]:
        """Return conductor/staff action logs for one ticket."""

        await self.initialize()
        rows = await asyncio.to_thread(
            self._fetch_all,
            """
            SELECT *
            FROM ticket_action_logs
            WHERE ticket_id = ?
            ORDER BY id ASC
            """,
            (ticket_id,),
        )
        return [_action_log_from_row(row) for row in rows]

    async def count_recent_user_tickets(
        self,
        *,
        guild_id: int,
        creator_user_id: int,
        window_seconds: int,
    ) -> int:
        """Count tickets opened by one user inside a sliding time window."""

        await self.initialize()
        cutoff = _utc_now() - timedelta(seconds=window_seconds)
        row = await asyncio.to_thread(
            self._fetch_one,
            """
            SELECT COUNT(*) AS total
            FROM tickets
            WHERE guild_id = ?
              AND creator_user_id = ?
              AND created_at >= ?
            """,
            (guild_id, creator_user_id, cutoff.isoformat()),
        )
        return int(row["total"]) if row is not None else 0

    async def find_recent_similar_ticket(
        self,
        *,
        guild_id: int,
        creator_user_id: int,
        ticket_type: TicketType,
        description: str,
        window_seconds: int,
        similarity_threshold: float = 0.9,
    ) -> TicketModel | None:
        """Return a recent ticket with a highly similar description.

        The check intentionally stays simple and explainable: it compares a
        normalized description against recent tickets from the same user and
        type using exact containment plus a SequenceMatcher ratio.
        """

        await self.initialize()
        cutoff = _utc_now() - timedelta(seconds=window_seconds)
        rows = await asyncio.to_thread(
            self._fetch_all,
            """
            SELECT *
            FROM tickets
            WHERE guild_id = ?
              AND creator_user_id = ?
              AND ticket_type = ?
              AND created_at >= ?
            ORDER BY id DESC
            LIMIT 20
            """,
            (guild_id, creator_user_id, ticket_type.value, cutoff.isoformat()),
        )
        normalized = _normalize_for_similarity(description)
        if not normalized:
            return None

        for row in rows:
            candidate = _ticket_from_row(row)
            candidate_description = _normalize_for_similarity(candidate.description)
            if _descriptions_are_similar(
                normalized,
                candidate_description,
                similarity_threshold,
            ):
                return candidate
        return None

    async def escalate_to_tribunal(
        self,
        *,
        ticket_id: int,
        actor_user_id: int,
        tribunal_message_id: int | None = None,
    ) -> TicketModel:
        """Move a report ticket into Tribunal voting."""

        ticket = await self._require_ticket(ticket_id)
        if ticket.ticket_type != TicketType.REPORT:
            msg = "Apenas denúncias podem ser escaladas para Tribunal."
            raise TicketStateError(msg)
        if ticket.status == TicketStatus.CLOSED:
            msg = "Tickets fechados não podem ir para Tribunal."
            raise TicketStateError(msg)

        await self._update_ticket(
            ticket_id,
            """
            status = ?,
            tribunal_message_id = COALESCE(?, tribunal_message_id),
            updated_at = ?
            """,
            (
                TicketStatus.TRIBUNAL.value,
                tribunal_message_id,
                _utc_now().isoformat(),
            ),
        )
        await self.record_event(
            ticket_id=ticket_id,
            actor_user_id=actor_user_id,
            event_type=TicketEventType.ESCALATED,
            payload={"tribunal_message_id": tribunal_message_id},
        )
        return await self._require_ticket(ticket_id)

    async def set_tribunal_message(
        self,
        *,
        ticket_id: int,
        tribunal_message_id: int,
    ) -> TicketModel:
        """Persist the Tribunal voting message ID."""

        await self._update_ticket(
            ticket_id,
            "tribunal_message_id = ?, updated_at = ?",
            (tribunal_message_id, _utc_now().isoformat()),
        )
        return await self._require_ticket(ticket_id)

    async def close_ticket(
        self,
        *,
        ticket_id: int,
        actor_user_id: int | None,
        reason: str,
    ) -> TicketModel:
        """Close a ticket with an auditable reason."""

        now = _utc_now().isoformat()
        await self._update_ticket(
            ticket_id,
            """
            status = ?,
            close_reason = ?,
            closed_at = ?,
            updated_at = ?
            """,
            (TicketStatus.CLOSED.value, reason, now, now),
        )
        await self.record_event(
            ticket_id=ticket_id,
            actor_user_id=actor_user_id,
            event_type=TicketEventType.CLOSED,
            payload={"reason": reason},
        )
        return await self._require_ticket(ticket_id)

    async def mark_channels_archived(self, ticket_id: int) -> TicketModel:
        """Clear private channel IDs after archival deletion succeeds."""

        await self._update_ticket(
            ticket_id,
            """
            category_channel_id = NULL,
            private_text_channel_id = NULL,
            private_voice_channel_id = NULL,
            updated_at = ?
            """,
            (_utc_now().isoformat(),),
        )
        return await self._require_ticket(ticket_id)

    async def add_participant(
        self,
        *,
        ticket_id: int,
        actor_user_id: int,
        user_id: int,
    ) -> None:
        """Add a member to the private ticket conversation."""

        await self._add_participant(ticket_id, user_id, "added")
        await self.record_event(
            ticket_id=ticket_id,
            actor_user_id=actor_user_id,
            event_type=TicketEventType.PARTICIPANT_ADDED,
            payload={"participant_added": user_id},
        )

    async def remove_added_participant(
        self,
        *,
        ticket_id: int,
        actor_user_id: int,
        user_id: int,
    ) -> None:
        """Remove a non-core participant from a private ticket conversation."""

        ticket = await self._require_ticket(ticket_id)
        if user_id in {ticket.creator_user_id, ticket.target_user_id}:
            msg = "Criador e alvo do ticket não podem ser removidos do caso."
            raise TicketStateError(msg)

        await self.initialize()
        await asyncio.to_thread(
            self._execute,
            """
            DELETE FROM ticket_participants
            WHERE ticket_id = ? AND user_id = ? AND role = ?
            """,
            (ticket_id, user_id, "added"),
        )
        await self.record_event(
            ticket_id=ticket_id,
            actor_user_id=actor_user_id,
            event_type=TicketEventType.PARTICIPANT_REMOVED,
            payload={"participant_removed": user_id},
        )

    async def list_participant_user_ids(self, ticket_id: int) -> set[int]:
        """Return user IDs allowed to talk in a ticket private channel."""

        await self.initialize()
        rows = await asyncio.to_thread(
            self._fetch_all,
            """
            SELECT DISTINCT user_id
            FROM ticket_participants
            WHERE ticket_id = ?
            """,
            (ticket_id,),
        )
        return {int(row["user_id"]) for row in rows}

    async def set_tribunal_targets(
        self,
        *,
        ticket_id: int,
        actor_user_id: int,
        target_user_ids: tuple[int, ...],
    ) -> None:
        """Replace the users selected to receive Tribunal actions."""

        if not target_user_ids:
            msg = "Selecione pelo menos uma pessoa para o Tribunal."
            raise TicketStateError(msg)

        await self.initialize()
        await asyncio.to_thread(
            self._set_tribunal_targets_sync,
            ticket_id,
            tuple(dict.fromkeys(target_user_ids)),
            _utc_now().isoformat(),
        )
        await self.record_event(
            ticket_id=ticket_id,
            actor_user_id=actor_user_id,
            event_type=TicketEventType.TRIBUNAL_TARGETS_SET,
            payload={"target_user_ids": list(dict.fromkeys(target_user_ids))},
        )

    async def list_tribunal_target_user_ids(self, ticket_id: int) -> tuple[int, ...]:
        """Return users selected to receive Tribunal actions."""

        await self.initialize()
        rows = await asyncio.to_thread(
            self._fetch_all,
            """
            SELECT user_id
            FROM tribunal_targets
            WHERE ticket_id = ?
            ORDER BY user_id ASC
            """,
            (ticket_id,),
        )
        return tuple(int(row["user_id"]) for row in rows)

    async def record_event(
        self,
        *,
        ticket_id: int,
        actor_user_id: int | None,
        event_type: TicketEventType,
        payload: dict[str, Any],
    ) -> None:
        """Persist an auditable ticket event."""

        await self.initialize()
        await asyncio.to_thread(
            self._execute,
            """
            INSERT INTO ticket_events (
                ticket_id,
                actor_user_id,
                event_type,
                payload_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                actor_user_id,
                event_type.value,
                json.dumps(payload, ensure_ascii=False),
                _utc_now().isoformat(),
            ),
        )

    async def list_events(self, ticket_id: int) -> list[TicketEventModel]:
        """Return event history for one ticket."""

        await self.initialize()
        rows = await asyncio.to_thread(
            self._fetch_all,
            """
            SELECT *
            FROM ticket_events
            WHERE ticket_id = ?
            ORDER BY id ASC
            """,
            (ticket_id,),
        )
        return [_event_from_row(row) for row in rows]

    async def _require_ticket(self, ticket_id: int) -> TicketModel:
        ticket = await self.get_ticket(ticket_id)
        if ticket is None:
            msg = f"Ticket {ticket_id} não encontrado."
            raise TicketNotFoundError(msg)
        return ticket

    async def _update_ticket(
        self,
        ticket_id: int,
        set_clause: str,
        params: Iterable[Any],
    ) -> None:
        await self.initialize()
        await asyncio.to_thread(
            self._execute,
            f"UPDATE tickets SET {set_clause} WHERE id = ?",
            (*tuple(params), ticket_id),
        )

    async def _add_participant(
        self,
        ticket_id: int,
        user_id: int,
        role: str,
    ) -> None:
        await self.initialize()
        await asyncio.to_thread(
            self._execute,
            """
            INSERT OR IGNORE INTO ticket_participants (
                ticket_id,
                user_id,
                role,
                created_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (ticket_id, user_id, role, _utc_now().isoformat()),
        )

    def _initialize_sync(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            for statement in TICKET_SCHEMA:
                connection.execute(statement)
            connection.commit()

    def _create_ticket_sync(
        self,
        guild_id: int,
        ticket_type: str,
        creator_user_id: int,
        target_user_id: int | None,
        description: str,
        anonymous_report: bool,
        created_at: str,
        expires_at: str,
        archive_after_hours: int,
    ) -> int:
        with sqlite3.connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO tickets (
                    guild_id,
                    ticket_type,
                    status,
                    creator_user_id,
                    target_user_id,
                    description,
                    anonymous_report,
                    created_at,
                    updated_at,
                    expires_at,
                    archive_after_hours
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    ticket_type,
                    TicketStatus.OPEN.value,
                    creator_user_id,
                    target_user_id,
                    description,
                    int(anonymous_report),
                    created_at,
                    created_at,
                    expires_at,
                    archive_after_hours,
                ),
            )
            if cursor.lastrowid is None:
                msg = "SQLite did not return a ticket ID"
                raise RuntimeError(msg)
            ticket_id = cursor.lastrowid
            connection.execute(
                """
                INSERT INTO ticket_participants (
                    ticket_id,
                    user_id,
                    role,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (ticket_id, creator_user_id, "creator", created_at),
            )
            if target_user_id is not None:
                connection.execute(
                    """
                    INSERT INTO ticket_participants (
                        ticket_id,
                        user_id,
                        role,
                        created_at
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (ticket_id, target_user_id, "target", created_at),
                )
            connection.commit()
            return ticket_id

    def _set_tribunal_targets_sync(
        self,
        ticket_id: int,
        target_user_ids: tuple[int, ...],
        created_at: str,
    ) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN")
            connection.execute(
                "DELETE FROM tribunal_targets WHERE ticket_id = ?",
                (ticket_id,),
            )
            connection.executemany(
                """
                INSERT INTO tribunal_targets (ticket_id, user_id, created_at)
                VALUES (?, ?, ?)
                """,
                [
                    (ticket_id, target_user_id, created_at)
                    for target_user_id in target_user_ids
                ],
            )
            connection.commit()

    def _insert_proof_sync(
        self,
        ticket_id: int,
        actor_user_id: int,
        description: str,
        links: tuple[str, ...],
        attachment_urls: tuple[str, ...],
        created_at: str,
    ) -> int:
        with sqlite3.connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO ticket_proofs (
                    ticket_id,
                    actor_user_id,
                    description,
                    links_json,
                    attachment_urls_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    actor_user_id,
                    description,
                    json.dumps(list(links), ensure_ascii=False),
                    json.dumps(list(attachment_urls), ensure_ascii=False),
                    created_at,
                ),
            )
            connection.commit()
            if cursor.lastrowid is None:
                msg = "SQLite did not return a proof ID"
                raise RuntimeError(msg)
            return cursor.lastrowid

    def _insert_action_log_sync(
        self,
        ticket_id: int,
        actor_user_id: int | None,
        action: str,
        details: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> int:
        with sqlite3.connect(self.database_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO ticket_action_logs (
                    ticket_id,
                    actor_user_id,
                    action,
                    details,
                    payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ticket_id,
                    actor_user_id,
                    action,
                    details,
                    json.dumps(payload, ensure_ascii=False),
                    created_at,
                ),
            )
            connection.commit()
            if cursor.lastrowid is None:
                msg = "SQLite did not return an action log ID"
                raise RuntimeError(msg)
            return cursor.lastrowid

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


class TribunalService:
    """Manage Tribunal votes and majority decisions."""

    def __init__(self, ticket_service: TicketService | None = None) -> None:
        """Initialize the Tribunal service."""

        self.ticket_service = ticket_service or ticket_service_singleton

    async def cast_vote(
        self,
        *,
        ticket_id: int,
        voter_user_id: int,
        choice: TribunalVoteChoice,
        reason: str | None,
        majority_votes: int,
    ) -> VoteTally:
        """Create or replace a vote and return the current majority state."""

        ticket = await self.ticket_service.get_ticket(ticket_id)
        if ticket is None:
            msg = f"Ticket {ticket_id} não encontrado."
            raise TicketNotFoundError(msg)
        if ticket.status != TicketStatus.TRIBUNAL:
            msg = "Votos só são aceitos em tickets no Tribunal."
            raise TicketStateError(msg)

        now = _utc_now().isoformat()
        await self.ticket_service.initialize()
        await asyncio.to_thread(
            self.ticket_service._execute,
            """
            INSERT INTO tribunal_votes (
                ticket_id,
                voter_user_id,
                choice,
                reason,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ticket_id, voter_user_id) DO UPDATE SET
                choice = excluded.choice,
                reason = excluded.reason,
                created_at = excluded.created_at
            """,
            (ticket_id, voter_user_id, choice.value, reason, now),
        )
        await self.ticket_service.record_event(
            ticket_id=ticket_id,
            actor_user_id=voter_user_id,
            event_type=TicketEventType.VOTE_CAST,
            payload={"choice": choice.value, "reason": reason},
        )

        tally = await self.get_tally(
            ticket_id=ticket_id,
            majority_votes=majority_votes,
        )
        if tally.decision_reached and tally.decision is not None:
            await self._record_decision(ticket_id, tally.decision)
        return tally

    async def get_votes(self, ticket_id: int) -> list[VoteModel]:
        """Return votes for a Tribunal ticket."""

        await self.ticket_service.initialize()
        rows = await asyncio.to_thread(
            self.ticket_service._fetch_all,
            """
            SELECT *
            FROM tribunal_votes
            WHERE ticket_id = ?
            ORDER BY id ASC
            """,
            (ticket_id,),
        )
        return [_vote_from_row(row) for row in rows]

    async def get_tally(self, *, ticket_id: int, majority_votes: int) -> VoteTally:
        """Calculate the current Tribunal tally."""

        votes = await self.get_votes(ticket_id)
        counts = Counter(vote.choice for vote in votes)
        decision = next(
            (
                choice
                for choice, count in counts.items()
                if count >= max(1, majority_votes)
            ),
            None,
        )
        return VoteTally(
            counts=dict(counts),
            decision=decision,
            decision_reached=decision is not None,
        )

    async def _record_decision(
        self,
        ticket_id: int,
        decision: TribunalVoteChoice,
    ) -> None:
        ticket = await self.ticket_service.get_ticket(ticket_id)
        if ticket is not None and ticket.decision == decision:
            return

        await self.ticket_service._update_ticket(
            ticket_id,
            "decision = ?, updated_at = ?",
            (decision.value, _utc_now().isoformat()),
        )
        await self.ticket_service.record_event(
            ticket_id=ticket_id,
            actor_user_id=None,
            event_type=TicketEventType.DECISION_REACHED,
            payload={"decision": decision.value},
        )
        logger.info(
            "Tribunal decision reached ticket_id=%s decision=%s",
            ticket_id,
            decision,
        )


class TicketNotFoundError(LookupError):
    """Raised when a ticket ID does not exist."""


class TicketStateError(RuntimeError):
    """Raised when a transition violates the ticket lifecycle."""


def _ticket_from_row(row: sqlite3.Row) -> TicketModel:
    return TicketModel(
        id=int(row["id"]),
        guild_id=int(row["guild_id"]),
        ticket_type=TicketType(str(row["ticket_type"])),
        status=TicketStatus(str(row["status"])),
        creator_user_id=int(row["creator_user_id"]),
        target_user_id=_optional_row_int(row["target_user_id"]),
        description=str(row["description"]),
        accepted_by_user_id=_optional_row_int(row["accepted_by_user_id"]),
        triage_channel_id=_optional_row_int(row["triage_channel_id"]),
        triage_message_id=_optional_row_int(row["triage_message_id"]),
        category_channel_id=_optional_row_int(row["category_channel_id"]),
        private_text_channel_id=_optional_row_int(row["private_text_channel_id"]),
        private_voice_channel_id=_optional_row_int(row["private_voice_channel_id"]),
        tribunal_message_id=_optional_row_int(row["tribunal_message_id"]),
        decision=(
            TribunalVoteChoice(str(row["decision"]))
            if row["decision"] is not None
            else None
        ),
        close_reason=str(row["close_reason"]) if row["close_reason"] else None,
        anonymous_report=bool(row["anonymous_report"]),
        created_at=datetime.fromisoformat(str(row["created_at"])),
        updated_at=datetime.fromisoformat(str(row["updated_at"])),
        expires_at=datetime.fromisoformat(str(row["expires_at"])),
        closed_at=(
            datetime.fromisoformat(str(row["closed_at"]))
            if row["closed_at"] is not None
            else None
        ),
        archive_after_hours=int(row["archive_after_hours"]),
    )


def _event_from_row(row: sqlite3.Row) -> TicketEventModel:
    return TicketEventModel(
        id=int(row["id"]),
        ticket_id=int(row["ticket_id"]),
        actor_user_id=_optional_row_int(row["actor_user_id"]),
        event_type=TicketEventType(str(row["event_type"])),
        payload=json.loads(str(row["payload_json"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
    )


def _proof_from_row(row: sqlite3.Row) -> TicketProofModel:
    return TicketProofModel(
        id=int(row["id"]),
        ticket_id=int(row["ticket_id"]),
        actor_user_id=int(row["actor_user_id"]),
        description=str(row["description"]),
        links=tuple(str(item) for item in json.loads(str(row["links_json"]))),
        attachment_urls=tuple(
            str(item) for item in json.loads(str(row["attachment_urls_json"]))
        ),
        created_at=datetime.fromisoformat(str(row["created_at"])),
    )


def _action_log_from_row(row: sqlite3.Row) -> TicketActionLogModel:
    return TicketActionLogModel(
        id=int(row["id"]),
        ticket_id=int(row["ticket_id"]),
        actor_user_id=_optional_row_int(row["actor_user_id"]),
        action=str(row["action"]),
        details=str(row["details"]),
        payload=json.loads(str(row["payload_json"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
    )


def _vote_from_row(row: sqlite3.Row) -> VoteModel:
    return VoteModel(
        id=int(row["id"]),
        ticket_id=int(row["ticket_id"]),
        voter_user_id=int(row["voter_user_id"]),
        choice=TribunalVoteChoice(str(row["choice"])),
        reason=str(row["reason"]) if row["reason"] else None,
        created_at=datetime.fromisoformat(str(row["created_at"])),
    )


def _optional_row_int(value: object) -> int | None:
    if value is None:
        return None
    return int(str(value))


def _utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)  # noqa: UP017


def _normalize_for_similarity(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _descriptions_are_similar(
    description: str,
    candidate: str,
    threshold: float,
) -> bool:
    if not candidate:
        return False
    if description == candidate:
        return True
    if len(description) >= 12 and description in candidate:
        return True
    if len(candidate) >= 12 and candidate in description:
        return True
    return SequenceMatcher(a=description, b=candidate).ratio() >= threshold


ticket_service_singleton = TicketService()
tribunal_service_singleton = TribunalService(ticket_service_singleton)
