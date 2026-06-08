"""Dashboard routes for XP configuration, leaderboards and rewards."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Coroutine
from dataclasses import replace
from typing import Any, TypeVar, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
from bot.services.xp_service import XPService
from dashboard.forms import DashboardFormError, parse_dashboard_form
from dashboard.security import (
    SESSION_GUILD_ID_KEY,
    current_user_id,
    current_user_role_ids,
    login_required,
    validate_csrf,
)

levels_blueprint = Blueprint("levels", __name__, url_prefix="/dashboard/levels")
T = TypeVar("T")
DISCORD_GUILD_CHANNELS_URL = "https://discord.com/api/guilds/{guild_id}/channels"
DISCORD_API_TIMEOUT_SECONDS = 5
TEXT_CHANNEL_TYPES = {0, 5}
logger = logging.getLogger(__name__)


@levels_blueprint.get("")
@login_required
def levels_dashboard() -> ResponseReturnValue:
    """Render XP leaderboard, statistics and role rewards."""

    guild_id = _resolve_guild_id()
    service = _levels_service()
    config = _run_async(_config_service().get_config(guild_id))
    leaderboard = _run_async(service.get_leaderboard(guild_id=guild_id, limit=10))
    weekly_leaderboard = _run_async(
        service.get_leaderboard(guild_id=guild_id, limit=10, weekly=True),
    )
    stats = _run_async(service.get_guild_stats(guild_id=guild_id))
    rewards = _run_async(service.list_level_rewards(guild_id=guild_id))
    return render_template(
        "levels.html",
        guild_id=guild_id,
        config=config,
        channel_options=_level_channel_options(guild_id, config),
        leaderboard=leaderboard,
        weekly_leaderboard=weekly_leaderboard,
        stats=stats,
        rewards=rewards,
    )


@levels_blueprint.post("/settings")
@login_required
def save_level_settings() -> ResponseReturnValue:
    """Persist level-up announcement settings from the Levels page."""

    validate_csrf()
    actor_user_id = current_user_id()
    if actor_user_id is None:
        return redirect(url_for("auth.login"))

    guild_id = _resolve_guild_id()
    config_service = _config_service()
    current_config = _run_async(config_service.get_config(guild_id))
    form_data = request.form.copy()
    _hydrate_level_settings_form(form_data, current_config)

    try:
        parsed_config = parse_dashboard_form(form_data)
        updated_config = replace(current_config, leveling=parsed_config.leveling)
        _run_async(
            config_service.save_config_from_dashboard(
                updated_config,
                actor_user_id=actor_user_id,
                actor_role_ids=current_user_role_ids(),
            ),
        )
    except (DashboardFormError, DashboardAccessDeniedError) as exc:
        flash(str(exc) or "Acesso negado.", "error")
    else:
        flash("Configurações de Level Up salvas.", "success")

    return redirect(url_for("levels.levels_dashboard", guild_id=guild_id))


@levels_blueprint.post("/rewards")
@login_required
def save_reward() -> ResponseReturnValue:
    """Create or remove a level role reward."""

    validate_csrf()
    guild_id = _resolve_guild_id()
    action = request.form.get("action", "add")
    level = int(request.form.get("level", "0"))
    role_id = int(request.form.get("role_id", "0"))
    service = _levels_service()
    if action == "delete":
        _run_async(
            service.delete_level_reward(
                guild_id=guild_id,
                level=level,
                role_id=role_id,
            ),
        )
        flash("Recompensa removida.", "success")
    else:
        _run_async(
            service.set_level_reward(
                guild_id=guild_id,
                level=level,
                role_id=role_id,
            ),
        )
        flash("Recompensa salva.", "success")
    return redirect(url_for("levels.levels_dashboard", guild_id=guild_id))


def _resolve_guild_id() -> int:
    raw_guild_id = request.args.get("guild_id") or session.get(SESSION_GUILD_ID_KEY)
    if raw_guild_id is None:
        raw_guild_id = settings.tars_guild_id
    guild_id = int(str(raw_guild_id or 0))
    if guild_id:
        session[SESSION_GUILD_ID_KEY] = guild_id
    return guild_id


def _levels_service() -> XPService:
    return cast(XPService, current_app.extensions["xp_service"])


def _config_service() -> CoreConfigService:
    return cast(CoreConfigService, current_app.extensions["core_config_service"])


def _run_async(awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _configured_channel_options(config: Any) -> list[tuple[int, str]]:
    channel_ids = [
        config.leveling.levelup_channel_id,
        config.welcome.channel_id,
        config.leave.channel_id,
        config.logs.channel_id,
        config.tickets.triage_channel_id,
        config.tickets.transcript_channel_id,
        *config.leveling.ignored_channel_ids,
    ]
    unique_channel_ids = [
        channel_id
        for channel_id in dict.fromkeys(channel_ids)
        if channel_id is not None
    ]
    return [
        (int(channel_id), f"Canal {channel_id}") for channel_id in unique_channel_ids
    ]


def _level_channel_options(guild_id: int, config: Any) -> list[tuple[int, str]]:
    configured_options = _configured_channel_options(config)
    if current_app.config.get("TESTING") or not settings.discord_token:
        return configured_options

    try:
        fetched_options = _fetch_text_channel_options(guild_id)
    except (HTTPError, URLError, TimeoutError, ValueError):
        logger.exception("Failed to fetch Discord channels guild_id=%s", guild_id)
        return configured_options

    option_by_id = dict(fetched_options)
    for channel_id, label in configured_options:
        option_by_id.setdefault(channel_id, label)
    return sorted(option_by_id.items(), key=lambda item: item[1].casefold())


def _fetch_text_channel_options(guild_id: int) -> list[tuple[int, str]]:
    request = Request(
        DISCORD_GUILD_CHANNELS_URL.format(guild_id=guild_id),
        headers={
            "Authorization": f"Bot {settings.discord_token}",
            "Accept": "application/json",
            "User-Agent": "TARS-Dashboard/0.1",
        },
        method="GET",
    )
    with urlopen(request, timeout=DISCORD_API_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(payload, list):
        raise ValueError("Discord channels response must be a list.")

    options: list[tuple[int, str]] = []
    for channel in payload:
        if (
            not isinstance(channel, dict)
            or channel.get("type") not in TEXT_CHANNEL_TYPES
        ):
            continue
        channel_id = int(str(channel["id"]))
        channel_name = str(channel.get("name") or channel_id)
        options.append((channel_id, f"#{channel_name}"))
    return options


def _hydrate_level_settings_form(form_data: Any, config: Any) -> None:
    form_data["guild_id"] = str(config.guild_id)
    form_data["owner_user_id"] = str(config.owner_user_id)
    form_data.setdefault("leveling_levelup_enabled", "0")
    form_data.setdefault("leveling_levelup_mention", "0")
    _set_default_dashboard_fields(form_data, config)


def _set_default_dashboard_fields(form_data: Any, config: Any) -> None:
    defaults = {
        "welcome_channel_id": config.welcome.channel_id,
        "welcome_embed_color": f"#{config.welcome.embed_color:06x}",
        "welcome_message_template": config.welcome.message_template,
        "leave_channel_id": config.leave.channel_id,
        "leave_embed_color": f"#{config.leave.embed_color:06x}",
        "leave_message_template": config.leave.message_template,
        "logs_channel_id": config.logs.channel_id,
        "logs_detail_level": int(config.logs.detail_level),
        "auto_role_id": config.auto_role.role_id,
        "auto_mod_blocked_words": "\n".join(config.auto_mod.blocked_words),
        "leveling_message_xp_min": config.leveling.message_xp_min,
        "leveling_message_xp_max": config.leveling.message_xp_max,
        "leveling_voice_xp_min_per_minute": config.leveling.voice_xp_min_per_minute,
        "leveling_voice_xp_max_per_minute": config.leveling.voice_xp_max_per_minute,
        "leveling_message_cooldown_seconds": config.leveling.message_cooldown_seconds,
        "leveling_voice_group_bonus_multiplier": (
            config.leveling.voice_group_bonus_multiplier
        ),
        "leveling_daily_base_xp": config.leveling.daily_base_xp,
        "leveling_daily_streak_bonus_xp": config.leveling.daily_streak_bonus_xp,
        "leveling_daily_max_streak": config.leveling.daily_max_streak,
        "leveling_ignored_channel_ids": "\n".join(
            str(channel_id) for channel_id in config.leveling.ignored_channel_ids
        ),
        "leveling_level_formula_quadratic": config.leveling.level_formula_quadratic,
        "leveling_level_formula_linear": config.leveling.level_formula_linear,
        "leveling_level_formula_constant": config.leveling.level_formula_constant,
        "leveling_xp_owner_user_id": config.leveling.xp_owner_user_id,
        "leveling_xp_staff_role_ids": "\n".join(
            str(role_id) for role_id in config.leveling.xp_staff_role_ids
        ),
        "leveling_staff_max_set_level": config.leveling.staff_max_set_level,
        "leveling_staff_max_xp_per_command": config.leveling.staff_max_xp_per_command,
        "tickets_triage_channel_id": config.tickets.triage_channel_id,
        "tickets_transcript_channel_id": config.tickets.transcript_channel_id,
        "tickets_staff_role_ids": "\n".join(
            str(role_id) for role_id in config.tickets.staff_role_ids
        ),
        "tickets_ticket_expiration_hours": config.tickets.ticket_expiration_hours,
        "tickets_archive_after_hours": config.tickets.archive_after_hours,
        "tickets_tribunal_majority_votes": config.tickets.tribunal_majority_votes,
        "tickets_rate_limit_ticket_count": config.tickets.rate_limit_ticket_count,
        "tickets_rate_limit_window_minutes": (
            config.tickets.rate_limit_window_seconds // 60
        ),
    }
    checkbox_defaults = {
        "welcome_enabled": config.welcome.enabled,
        "leave_enabled": config.leave.enabled,
        "auto_role_enabled": config.auto_role.enabled,
        "auto_mod_enabled": config.auto_mod.enabled,
        "auto_mod_dm_owner_on_action": config.auto_mod.dm_owner_on_action,
        "leveling_enabled": config.leveling.enabled,
        "tickets_anonymous_reports_enabled": config.tickets.anonymous_reports_enabled,
        "tickets_dm_notifications_enabled": config.tickets.dm_notifications_enabled,
    }
    for key, value in defaults.items():
        form_data.setdefault(key, "" if value is None else str(value))
    for key, enabled in checkbox_defaults.items():
        if enabled:
            form_data.setdefault(key, "1")
