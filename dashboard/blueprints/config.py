"""Configuration routes for the private Dashboard."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Coroutine
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
from bot.services.core_config_service import (
    CoreConfigService,
    DashboardAccessDeniedError,
)
from dashboard.forms import DashboardFormError, build_previews, parse_dashboard_form
from dashboard.security import (
    SESSION_GUILD_ID_KEY,
    current_user_id,
    current_user_role_ids,
    login_required,
    validate_csrf,
)

config_blueprint = Blueprint("config", __name__)
audit_logger = logging.getLogger("tars.dashboard.audit")
T = TypeVar("T")


@config_blueprint.get("/")
def index() -> ResponseReturnValue:
    """Redirect the root path into the authenticated Dashboard."""

    if current_user_id() is None:
        return redirect(url_for("auth.login"))
    return redirect(url_for("config.dashboard"))


@config_blueprint.get("/dashboard")
@login_required
def dashboard() -> ResponseReturnValue:
    """Render the Dashboard configuration form."""

    guild_id = _resolve_guild_id()
    service = _config_service()
    config = _run_async(service.get_config(guild_id))
    audit_events = _run_async(
        service.list_dashboard_audit_events(guild_id=guild_id, limit=12),
    )
    return render_template(
        "dashboard.html",
        config=config,
        previews=build_previews(config),
        audit_events=audit_events,
        owner_user_id=settings.tars_owner_user_id,
        tars_guild_id=settings.tars_guild_id,
    )


@config_blueprint.post("/dashboard")
@login_required
def save_dashboard() -> ResponseReturnValue:
    """Persist Dashboard configuration through the core service."""

    validate_csrf()
    actor_user_id = current_user_id()
    if actor_user_id is None:
        return redirect(url_for("auth.login"))

    try:
        config = parse_dashboard_form(request.form)
        _run_async(
            _config_service().save_config_from_dashboard(
                config,
                actor_user_id=actor_user_id,
                actor_role_ids=current_user_role_ids(),
            ),
        )
    except DashboardFormError as exc:
        flash(str(exc), "error")
    except DashboardAccessDeniedError:
        audit_logger.warning("dashboard_save_denied user_id=%s", actor_user_id)
        flash("Acesso negado.", "error")
    except sqlite3.OperationalError as exc:
        audit_logger.exception("dashboard_save_database_error")
        flash(f"Banco indisponível agora: {exc}. Tente novamente.", "error")
    else:
        session[SESSION_GUILD_ID_KEY] = config.guild_id
        audit_logger.info(
            "dashboard_config_saved guild_id=%s user_id=%s",
            config.guild_id,
            actor_user_id,
        )
        flash("Configurações salvas com segurança.", "success")

    return redirect(url_for("config.dashboard"))


@config_blueprint.post("/dashboard/preview")
@login_required
def preview_dashboard() -> ResponseReturnValue:
    """Render the live welcome and leave preview fragment."""

    validate_csrf()
    try:
        config = parse_dashboard_form(request.form)
        previews = build_previews(config)
    except (DashboardFormError, KeyError, ValueError) as exc:
        return render_template("partials/preview_error.html", message=str(exc))

    return render_template("partials/embed_preview.html", previews=previews)


def _resolve_guild_id() -> int:
    raw_guild_id = request.args.get("guild_id") or session.get(SESSION_GUILD_ID_KEY)
    if raw_guild_id is None:
        raw_guild_id = settings.tars_guild_id

    guild_id = int(str(raw_guild_id or 0))
    if guild_id:
        session[SESSION_GUILD_ID_KEY] = guild_id
    return guild_id


def _config_service() -> CoreConfigService:
    return cast(CoreConfigService, current_app.extensions["core_config_service"])


def _run_async(awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)
