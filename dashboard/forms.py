"""Form parsing helpers for Dashboard configuration updates."""

from __future__ import annotations

import re
from dataclasses import dataclass

from werkzeug.datastructures import MultiDict

from bot.database.models.core_models import (
    DEFAULT_LEVELUP_MESSAGE,
    DEFAULT_STAFF_MAX_SET_LEVEL,
    DEFAULT_STAFF_MAX_XP_PER_COMMAND,
    DEFAULT_XP_OWNER_USER_ID,
    AutoModConfigModel,
    AutoRoleConfigModel,
    DashboardConfigModel,
    LevelingConfigModel,
    LogConfigModel,
    LogDetailLevel,
    TicketConfigModel,
    WelcomeConfigModel,
)

HEX_COLOR_PATTERN = re.compile(r"^#?[0-9a-fA-F]{6}$")


class DashboardFormError(ValueError):
    """Raised when Dashboard form data cannot be converted safely."""


@dataclass(frozen=True)
class EmbedPreview:
    """Small presentation model for welcome and leave embed previews."""

    title: str
    description: str
    color: str
    enabled: bool


def parse_dashboard_form(form: MultiDict[str, str]) -> DashboardConfigModel:
    """Convert submitted Dashboard fields into a full config model."""

    guild_id = _required_int(form, "guild_id", "ID do servidor")
    owner_user_id = _required_int(form, "owner_user_id", "ID do dono")

    ticket_role_ids = _split_int_list(form.get("tickets_staff_role_ids", ""))
    message_xp_min = _leveling_int(
        form,
        "leveling_message_xp_min",
        "leveling_message_xp",
        "XP mínimo por mensagem",
    )
    message_xp_max = _leveling_int(
        form,
        "leveling_message_xp_max",
        "leveling_message_xp",
        "XP máximo por mensagem",
    )
    voice_xp_min = _leveling_int(
        form,
        "leveling_voice_xp_min_per_minute",
        "leveling_voice_xp_per_minute",
        "XP mínimo por minuto em voz",
    )
    voice_xp_max = _leveling_int(
        form,
        "leveling_voice_xp_max_per_minute",
        "leveling_voice_xp_per_minute",
        "XP máximo por minuto em voz",
    )
    levelup_message = form.get(
        "leveling_levelup_message",
        form.get("leveling_level_up_message", DEFAULT_LEVELUP_MESSAGE),
    )
    _validate_levelup_message_template(levelup_message)

    return DashboardConfigModel(
        guild_id=guild_id,
        owner_user_id=owner_user_id,
        welcome=_parse_embed_config(form, "welcome"),
        leave=_parse_embed_config(form, "leave"),
        logs=LogConfigModel(
            channel_id=_optional_int(form.get("logs_channel_id")),
            detail_level=LogDetailLevel(
                _required_int(form, "logs_detail_level", "logs"),
            ),
        ),
        auto_role=AutoRoleConfigModel(
            role_id=_optional_int(form.get("auto_role_id")),
            enabled=_checkbox(form, "auto_role_enabled"),
        ),
        auto_mod=AutoModConfigModel(
            enabled=_checkbox(form, "auto_mod_enabled"),
            blocked_words=_split_list(form.get("auto_mod_blocked_words", "")),
            dm_owner_on_action=_checkbox(form, "auto_mod_dm_owner_on_action"),
        ),
        leveling=LevelingConfigModel(
            enabled=_checkbox(form, "leveling_enabled"),
            message_xp_min=min(message_xp_min, message_xp_max),
            message_xp_max=max(message_xp_min, message_xp_max),
            message_cooldown_seconds=_non_negative_int(
                form,
                "leveling_message_cooldown_seconds",
                "Cooldown de XP",
            ),
            voice_xp_min_per_minute=min(voice_xp_min, voice_xp_max),
            voice_xp_max_per_minute=max(voice_xp_min, voice_xp_max),
            voice_group_bonus_multiplier=max(
                1.0,
                _non_negative_float(
                    form,
                    "leveling_voice_group_bonus_multiplier",
                    "Bônus de voz em grupo",
                    default="1.5",
                ),
            ),
            daily_base_xp=_non_negative_int_default(
                form,
                "leveling_daily_base_xp",
                "XP base do daily",
                100,
            ),
            daily_streak_bonus_xp=_non_negative_int_default(
                form,
                "leveling_daily_streak_bonus_xp",
                "Bônus de streak",
                20,
            ),
            daily_max_streak=max(
                1,
                _non_negative_int_default(
                    form,
                    "leveling_daily_max_streak",
                    "Streak máximo",
                    7,
                ),
            ),
            ignored_channel_ids=_split_int_list(
                form.get("leveling_ignored_channel_ids", ""),
            ),
            level_formula_quadratic=_non_negative_int_default(
                form,
                "leveling_level_formula_quadratic",
                "Coeficiente quadrático",
                5,
            ),
            level_formula_linear=_non_negative_int_default(
                form,
                "leveling_level_formula_linear",
                "Coeficiente linear",
                50,
            ),
            level_formula_constant=max(
                1,
                _leveling_int(
                    form,
                    "leveling_level_formula_constant",
                    "leveling_level_xp_factor",
                    "Constante da fórmula",
                ),
            ),
            levelup_channel_id=_optional_int(
                form.get("leveling_levelup_channel_id"),
            ),
            levelup_enabled=_checkbox(
                form,
                "leveling_levelup_enabled",
                default=True,
            ),
            levelup_mention=_checkbox(
                form,
                "leveling_levelup_mention",
                default=True,
            ),
            levelup_message=levelup_message,
            xp_owner_user_id=_optional_int_default(
                form,
                "leveling_xp_owner_user_id",
                "Owner do XP",
                DEFAULT_XP_OWNER_USER_ID,
            ),
            xp_staff_role_ids=_split_int_list(
                form.get("leveling_xp_staff_role_ids", ""),
            ),
            staff_max_set_level=_non_negative_int_default(
                form,
                "leveling_staff_max_set_level",
                "Nível máximo para staff",
                DEFAULT_STAFF_MAX_SET_LEVEL,
            ),
            staff_max_xp_per_command=_non_negative_int_default(
                form,
                "leveling_staff_max_xp_per_command",
                "XP máximo por comando para staff",
                DEFAULT_STAFF_MAX_XP_PER_COMMAND,
            ),
        ),
        tickets=TicketConfigModel(
            triage_channel_id=_optional_int(form.get("tickets_triage_channel_id")),
            staff_role_ids=ticket_role_ids,
            judge_role_ids=ticket_role_ids,
            admin_role_ids=(),
            create_voice_channel=False,
            ticket_expiration_hours=max(
                1,
                _non_negative_int(
                    form,
                    "tickets_ticket_expiration_hours",
                    "Expiração de tickets",
                ),
            ),
            archive_after_hours=max(
                1,
                _non_negative_int(
                    form,
                    "tickets_archive_after_hours",
                    "Arquivamento de tickets",
                ),
            ),
            tribunal_majority_votes=max(
                1,
                _non_negative_int(
                    form,
                    "tickets_tribunal_majority_votes",
                    "Maioria do Tribunal",
                ),
            ),
            anonymous_reports_enabled=_checkbox(
                form,
                "tickets_anonymous_reports_enabled",
            ),
            rate_limit_ticket_count=max(
                1,
                _non_negative_int(
                    form,
                    "tickets_rate_limit_ticket_count",
                    "Limite de tickets",
                ),
            ),
            rate_limit_window_seconds=max(
                60,
                _non_negative_int(
                    form,
                    "tickets_rate_limit_window_minutes",
                    "Janela de rate limit",
                )
                * 60,
            ),
            transcript_channel_id=_optional_int(
                form.get("tickets_transcript_channel_id"),
            ),
            dm_notifications_enabled=_checkbox(
                form,
                "tickets_dm_notifications_enabled",
            ),
        ),
    )


def build_previews(config: DashboardConfigModel) -> list[EmbedPreview]:
    """Build welcome and leave preview contexts from a config."""

    return [
        _build_preview("Bem-vindo(a)", config.welcome),
        _build_preview("Membro saiu", config.leave),
    ]


def _parse_embed_config(
    form: MultiDict[str, str],
    prefix: str,
) -> WelcomeConfigModel:
    message_template = form.get(f"{prefix}_message_template", "").strip()
    _validate_message_template(message_template)
    return WelcomeConfigModel(
        channel_id=_optional_int(form.get(f"{prefix}_channel_id")),
        message_template=message_template,
        embed_color=_parse_color(form.get(f"{prefix}_embed_color", "")),
        enabled=_checkbox(form, f"{prefix}_enabled"),
    )


def _build_preview(title: str, config: WelcomeConfigModel) -> EmbedPreview:
    description = config.message_template.format(
        member="@Carllos",
        server="Servidor TARS",
    )
    return EmbedPreview(
        title=title,
        description=description,
        color=f"#{config.embed_color:06x}",
        enabled=config.enabled,
    )


def _validate_message_template(message_template: str) -> None:
    try:
        message_template.format(member="@Carllos", server="Servidor TARS")
    except (KeyError, ValueError) as exc:
        raise DashboardFormError(
            "Mensagens aceitam apenas os campos {member} e {server}.",
        ) from exc


def _validate_levelup_message_template(message_template: str) -> None:
    try:
        message_template.format(
            user="@Carllos",
            member="@Carllos",
            level=10,
            xp=1234,
            server="Servidor TARS",
        )
    except (KeyError, ValueError) as exc:
        raise DashboardFormError(
            (
                "Mensagem de level up aceita apenas os campos "
                "{user}, {member}, {level}, {xp} e {server}."
            ),
        ) from exc


def _checkbox(form: MultiDict[str, str], key: str, *, default: bool = False) -> bool:
    if key not in form:
        return default
    return any(value in {"1", "on", "true", "True"} for value in form.getlist(key))


def _optional_int(value: str | None) -> int | None:
    if value is None or value.strip() == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise DashboardFormError("IDs devem conter apenas números.") from exc


def _required_int(form: MultiDict[str, str], key: str, label: str) -> int:
    value = _optional_int(form.get(key))
    if value is None:
        raise DashboardFormError(f"{label} é obrigatório.")
    return value


def _optional_int_default(
    form: MultiDict[str, str],
    key: str,
    label: str,
    default: int,
) -> int:
    if key not in form:
        return default
    return _required_int(form, key, label)


def _non_negative_int(form: MultiDict[str, str], key: str, label: str) -> int:
    value = _required_int(form, key, label)
    if value < 0:
        raise DashboardFormError(f"{label} não pode ser negativo.")
    return value


def _non_negative_int_default(
    form: MultiDict[str, str],
    key: str,
    label: str,
    default: int,
) -> int:
    if key not in form:
        return default
    return _non_negative_int(form, key, label)


def _leveling_int(
    form: MultiDict[str, str],
    key: str,
    fallback_key: str,
    label: str,
) -> int:
    if key in form:
        return _non_negative_int(form, key, label)
    return _non_negative_int(form, fallback_key, label)


def _non_negative_float(
    form: MultiDict[str, str],
    key: str,
    label: str,
    *,
    default: str,
) -> float:
    raw_value = form.get(key, default)
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise DashboardFormError(f"{label} deve ser numérico.") from exc
    if value < 0:
        raise DashboardFormError(f"{label} não pode ser negativo.")
    return value


def _parse_color(value: str) -> int:
    normalized = value.strip()
    if not HEX_COLOR_PATTERN.fullmatch(normalized):
        raise DashboardFormError("Cores devem estar no formato #RRGGBB.")
    return int(normalized.removeprefix("#"), 16)


def _split_list(value: str) -> tuple[str, ...]:
    items = [
        item.strip()
        for chunk in value.splitlines()
        for item in chunk.split(",")
        if item.strip()
    ]
    return tuple(dict.fromkeys(items))


def _split_int_list(value: str) -> tuple[int, ...]:
    raw_items = _split_list(value)
    try:
        return tuple(dict.fromkeys(int(item) for item in raw_items))
    except ValueError as exc:
        raise DashboardFormError(
            "Listas de cargos aceitam apenas IDs numéricos.",
        ) from exc
