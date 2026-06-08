"""Dashboard routes for rich TARS logs."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar, cast

from flask import Blueprint, Response, current_app, render_template, request, session
from flask.typing import ResponseReturnValue

from bot.config import settings
from bot.database.models.core_models import DEFAULT_LOG_EVENT_TYPES
from bot.database.models.log_models import LogCategory, LogEventFilters
from bot.services.log_service import LogService
from dashboard.security import SESSION_GUILD_ID_KEY, login_required

logs_blueprint = Blueprint("logs", __name__, url_prefix="/dashboard/logs")
T = TypeVar("T")


@logs_blueprint.get("")
@login_required
def logs_dashboard() -> ResponseReturnValue:
    """Render the rich log history with filters."""

    filters = _parse_filters(limit=150)
    events = _run_async(_log_service().list_events(filters))
    return render_template(
        "logs.html",
        events=events,
        guild_id=filters.guild_id,
        categories=LogCategory,
        event_types=DEFAULT_LOG_EVENT_TYPES,
        selected_category=filters.category,
        selected_event_type=filters.event_type,
        selected_user_id=filters.user_id or "",
        selected_actor_user_id=filters.actor_user_id or "",
        selected_channel_id=filters.channel_id or "",
        search=filters.query,
    )


@logs_blueprint.get("/export.csv")
@login_required
def export_logs() -> Response:
    """Export filtered rich logs as CSV."""

    csv_text = _run_async(_log_service().export_events_csv(_parse_filters(limit=500)))
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=tars-logs.csv"},
    )


def _parse_filters(*, limit: int) -> LogEventFilters:
    return LogEventFilters(
        guild_id=_resolve_guild_id(),
        query=request.args.get("q", "").strip(),
        category=request.args.get("category", "").strip(),
        event_type=request.args.get("event_type", "").strip(),
        user_id=_optional_int(request.args.get("user_id")),
        actor_user_id=_optional_int(request.args.get("actor_user_id")),
        channel_id=_optional_int(request.args.get("channel_id")),
        limit=limit,
    )


def _resolve_guild_id() -> int:
    raw_guild_id = request.args.get("guild_id") or session.get(SESSION_GUILD_ID_KEY)
    if raw_guild_id is None:
        raw_guild_id = settings.tars_guild_id
    guild_id = int(str(raw_guild_id or 0))
    if guild_id:
        session[SESSION_GUILD_ID_KEY] = guild_id
    return guild_id


def _optional_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _log_service() -> LogService:
    return cast(LogService, current_app.extensions["log_service"])


def _run_async(awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)
