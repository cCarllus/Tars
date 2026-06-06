"""Form parsing helpers for Dashboard configuration updates."""

from __future__ import annotations

import re
from dataclasses import dataclass

from werkzeug.datastructures import MultiDict

from bot.database.models.core_models import (
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
            message_xp=_non_negative_int(
                form,
                "leveling_message_xp",
                "XP por mensagem",
            ),
            message_cooldown_seconds=_non_negative_int(
                form,
                "leveling_message_cooldown_seconds",
                "Cooldown de XP",
            ),
            voice_xp_per_minute=_non_negative_int(
                form,
                "leveling_voice_xp_per_minute",
                "XP por minuto em voz",
            ),
            level_xp_factor=max(
                1,
                _non_negative_int(form, "leveling_level_xp_factor", "Fator de nível"),
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


def _checkbox(form: MultiDict[str, str], key: str, *, default: bool = False) -> bool:
    if key not in form:
        return default
    return form.get(key) in {"1", "on", "true", "True"}


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


def _non_negative_int(form: MultiDict[str, str], key: str, label: str) -> int:
    value = _required_int(form, key, label)
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
