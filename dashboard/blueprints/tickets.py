"""Dashboard routes for ticket inspection."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, time
from typing import Any, TypeVar, cast

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask.typing import ResponseReturnValue

from bot.config import settings
from bot.database.models.ticket_models import TicketStatus, TicketType
from bot.services.ticket_service import TicketService
from dashboard.security import (
    SESSION_GUILD_ID_KEY,
    current_user_id,
    login_required,
    validate_csrf,
)

tickets_blueprint = Blueprint("tickets", __name__, url_prefix="/dashboard/tickets")
T = TypeVar("T")


@tickets_blueprint.get("")
@login_required
def list_tickets() -> ResponseReturnValue:
    """Render ticket search and status filters."""

    guild_id = _resolve_guild_id()
    status = _parse_status(request.args.get("status"))
    ticket_type = _parse_ticket_type(request.args.get("type"))
    created_after = _parse_date_start(request.args.get("date_from"))
    created_before = _parse_date_end(request.args.get("date_to"))
    search = request.args.get("q", "").strip() or None
    tickets = _run_async(
        _ticket_service().list_tickets(
            guild_id=guild_id,
            status=status,
            ticket_type=ticket_type,
            created_after=created_after,
            created_before=created_before,
            search=search,
            limit=100,
        ),
    )
    return render_template(
        "tickets.html",
        tickets=tickets,
        guild_id=guild_id,
        selected_status=status.value if status else "",
        selected_type=ticket_type.value if ticket_type else "",
        date_from=request.args.get("date_from", ""),
        date_to=request.args.get("date_to", ""),
        search=search or "",
        statuses=TicketStatus,
        ticket_types=TicketType,
    )


@tickets_blueprint.post("/<int:ticket_id>/close")
@login_required
def close_ticket(ticket_id: int) -> ResponseReturnValue:
    """Close a ticket directly from the Dashboard list."""

    validate_csrf()
    actor_user_id = current_user_id()
    closed = _run_async(
        _ticket_service().close_ticket(
            ticket_id=ticket_id,
            actor_user_id=actor_user_id,
            reason="Fechado diretamente pela Dashboard.",
        ),
    )
    _run_async(
        _ticket_service().log_action(
            ticket_id=ticket_id,
            actor_user_id=actor_user_id,
            action="ticket_closed_dashboard",
            details="Ticket fechado diretamente pela Dashboard.",
            payload={
                "ticket_id": closed.id,
                "ticket_type": closed.ticket_type.value,
                "status": closed.status.value,
            },
        ),
    )
    flash(f"Ticket #{ticket_id:04d} fechado.", "success")
    return redirect(url_for("tickets.list_tickets", guild_id=_resolve_guild_id()))


def _parse_status(raw_status: str | None) -> TicketStatus | None:
    if not raw_status:
        return None
    try:
        return TicketStatus(raw_status)
    except ValueError:
        return None


def _parse_ticket_type(raw_type: str | None) -> TicketType | None:
    if not raw_type:
        return None
    try:
        return TicketType(raw_type)
    except ValueError:
        return None


def _parse_date_start(raw_date: str | None) -> datetime | None:
    if not raw_date:
        return None
    try:
        return datetime.combine(
            datetime.strptime(raw_date, "%Y-%m-%d").date(),
            time.min,
            tzinfo=UTC,
        )
    except ValueError:
        return None


def _parse_date_end(raw_date: str | None) -> datetime | None:
    if not raw_date:
        return None
    try:
        return datetime.combine(
            datetime.strptime(raw_date, "%Y-%m-%d").date(),
            time.max,
            tzinfo=UTC,
        )
    except ValueError:
        return None


def _resolve_guild_id() -> int:
    raw_guild_id = request.args.get("guild_id") or session.get(SESSION_GUILD_ID_KEY)
    if raw_guild_id is None:
        raw_guild_id = settings.tars_guild_id
    guild_id = int(str(raw_guild_id or 0))
    if guild_id:
        session[SESSION_GUILD_ID_KEY] = guild_id
    return guild_id


def _ticket_service() -> TicketService:
    return cast(TicketService, current_app.extensions["ticket_service"])


def _run_async(awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)
