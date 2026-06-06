"""Dashboard routes for ticket inspection."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar, cast

from flask import Blueprint, current_app, render_template, request, session
from flask.typing import ResponseReturnValue

from bot.config import settings
from bot.database.models.ticket_models import TicketStatus
from bot.services.ticket_service import TicketService
from dashboard.security import SESSION_GUILD_ID_KEY, login_required

tickets_blueprint = Blueprint("tickets", __name__, url_prefix="/dashboard/tickets")
T = TypeVar("T")


@tickets_blueprint.get("")
@login_required
def list_tickets() -> ResponseReturnValue:
    """Render ticket search and status filters."""

    guild_id = _resolve_guild_id()
    status = _parse_status(request.args.get("status"))
    search = request.args.get("q", "").strip() or None
    tickets = _run_async(
        _ticket_service().list_tickets(
            guild_id=guild_id,
            status=status,
            search=search,
            limit=100,
        ),
    )
    return render_template(
        "tickets.html",
        tickets=tickets,
        guild_id=guild_id,
        selected_status=status.value if status else "",
        search=search or "",
        statuses=TicketStatus,
    )


def _parse_status(raw_status: str | None) -> TicketStatus | None:
    if not raw_status:
        return None
    try:
        return TicketStatus(raw_status)
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
