"""Models for core server configuration and leveling state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Self

DEFAULT_WELCOME_COLOR = 0x2ECC71
DEFAULT_LEAVE_COLOR = 0xE74C3C
DEFAULT_XP_OWNER_USER_ID = 399757244138520576
DEFAULT_STAFF_MAX_SET_LEVEL = 15
DEFAULT_STAFF_MAX_XP_PER_COMMAND = 5000
DEFAULT_LEVELUP_MESSAGE = (
    "🎉 {user} subiu para o **nível {level}**! " "Parabéns! Continue evoluindo!"
)
DEFAULT_LOG_RETENTION_DAYS = 90
DEFAULT_LOG_EVENT_TYPES = (
    "member_join",
    "member_leave",
    "member_ban",
    "member_unban",
    "member_kick",
    "member_timeout_add",
    "member_timeout_remove",
    "member_nick_update",
    "user_avatar_update",
    "user_username_update",
    "voice_join",
    "voice_leave",
    "voice_move",
    "voice_mute",
    "voice_unmute",
    "voice_deafen",
    "voice_undeafen",
    "message_edit",
    "message_delete",
    "message_bulk_delete",
    "reaction_add",
    "reaction_remove",
    "ticket_created",
    "ticket_closed",
    "ticket_closed_dashboard",
    "ticket_escalated",
    "ticket_expired",
    "tribunal_vote",
    "tribunal_decision",
    "level_up",
    "xp_admin_action",
    "economy_action",
    "admin_command",
)


class LogDetailLevel(IntEnum):
    """Supported Discord channel audit-log detail levels."""

    BASIC = 1
    NORMAL = 2
    DETAILED = 3


@dataclass(frozen=True)
class WelcomeConfigModel:
    """Configurable embed behavior for member welcome or leave messages."""

    channel_id: int | None = None
    message_template: str = "Bem-vindo(a), {member}, ao {server}."
    embed_color: int = DEFAULT_WELCOME_COLOR
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize the config for JSON persistence."""

        return {
            "channel_id": self.channel_id,
            "message_template": self.message_template,
            "embed_color": self.embed_color,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Deserialize the config from Dashboard JSON."""

        return cls(
            channel_id=_optional_int(payload.get("channel_id")),
            message_template=str(
                payload.get("message_template", cls.message_template),
            ),
            embed_color=int(payload.get("embed_color", DEFAULT_WELCOME_COLOR)),
            enabled=bool(payload.get("enabled", True)),
        )


@dataclass(frozen=True)
class LogConfigModel:
    """Configurable audit-log channel behavior."""

    channel_id: int | None = None
    detail_level: LogDetailLevel = LogDetailLevel.NORMAL
    moderation_channel_id: int | None = None
    member_channel_id: int | None = None
    message_channel_id: int | None = None
    profile_channel_id: int | None = None
    voice_channel_id: int | None = None
    system_channel_id: int | None = None
    xp_economy_channel_id: int | None = None
    enabled_event_types: tuple[str, ...] = DEFAULT_LOG_EVENT_TYPES
    ignore_bots: bool = True
    ignored_role_ids: tuple[int, ...] = field(default_factory=tuple)
    ignored_channel_ids: tuple[int, ...] = field(default_factory=tuple)
    retention_days: int = DEFAULT_LOG_RETENTION_DAYS
    persist_message_content: bool = True
    webhooks_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize the config for JSON persistence."""

        return {
            "channel_id": self.channel_id,
            "detail_level": int(self.detail_level),
            "moderation_channel_id": self.moderation_channel_id,
            "member_channel_id": self.member_channel_id,
            "message_channel_id": self.message_channel_id,
            "profile_channel_id": self.profile_channel_id,
            "voice_channel_id": self.voice_channel_id,
            "system_channel_id": self.system_channel_id,
            "xp_economy_channel_id": self.xp_economy_channel_id,
            "enabled_event_types": list(self.enabled_event_types),
            "ignore_bots": self.ignore_bots,
            "ignored_role_ids": list(self.ignored_role_ids),
            "ignored_channel_ids": list(self.ignored_channel_ids),
            "retention_days": self.retention_days,
            "persist_message_content": self.persist_message_content,
            "webhooks_enabled": self.webhooks_enabled,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Deserialize the config from Dashboard JSON."""

        return cls(
            channel_id=_optional_int(payload.get("channel_id")),
            detail_level=LogDetailLevel(int(payload.get("detail_level", 2))),
            moderation_channel_id=_optional_int(payload.get("moderation_channel_id")),
            member_channel_id=_optional_int(payload.get("member_channel_id")),
            message_channel_id=_optional_int(payload.get("message_channel_id")),
            profile_channel_id=_optional_int(payload.get("profile_channel_id")),
            voice_channel_id=_optional_int(payload.get("voice_channel_id")),
            system_channel_id=_optional_int(payload.get("system_channel_id")),
            xp_economy_channel_id=_optional_int(payload.get("xp_economy_channel_id")),
            enabled_event_types=_log_event_tuple(
                payload.get("enabled_event_types", DEFAULT_LOG_EVENT_TYPES),
            ),
            ignore_bots=bool(payload.get("ignore_bots", True)),
            ignored_role_ids=_int_tuple(payload.get("ignored_role_ids", [])),
            ignored_channel_ids=_int_tuple(payload.get("ignored_channel_ids", [])),
            retention_days=max(
                1,
                int(payload.get("retention_days", DEFAULT_LOG_RETENTION_DAYS)),
            ),
            persist_message_content=bool(payload.get("persist_message_content", True)),
            webhooks_enabled=bool(payload.get("webhooks_enabled", False)),
        )


@dataclass(frozen=True)
class AutoRoleConfigModel:
    """Configurable auto-role behavior for new members."""

    role_id: int | None = None
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize the config for JSON persistence."""

        return {
            "role_id": self.role_id,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Deserialize the config from Dashboard JSON."""

        return cls(
            role_id=_optional_int(payload.get("role_id")),
            enabled=bool(payload.get("enabled", True)),
        )


@dataclass(frozen=True)
class AutoModConfigModel:
    """Configurable automatic moderation behavior."""

    enabled: bool = True
    blocked_words: tuple[str, ...] = field(default_factory=tuple)
    block_links: bool = False
    allowed_links: tuple[str, ...] = field(default_factory=tuple)
    dm_owner_on_action: bool = True

    def __post_init__(self) -> None:
        """Keep link moderation disabled while preserving old config fields."""

        object.__setattr__(self, "block_links", False)
        object.__setattr__(self, "allowed_links", ())

    def to_dict(self) -> dict[str, Any]:
        """Serialize the config for JSON persistence."""

        return {
            "enabled": self.enabled,
            "blocked_words": list(self.blocked_words),
            "block_links": self.block_links,
            "allowed_links": list(self.allowed_links),
            "dm_owner_on_action": self.dm_owner_on_action,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Deserialize the config from Dashboard JSON."""

        return cls(
            enabled=bool(payload.get("enabled", True)),
            blocked_words=tuple(
                str(word).lower() for word in payload.get("blocked_words", [])
            ),
            block_links=bool(payload.get("block_links", False)),
            allowed_links=tuple(
                str(link).lower() for link in payload.get("allowed_links", [])
            ),
            dm_owner_on_action=bool(payload.get("dm_owner_on_action", True)),
        )


@dataclass(frozen=True)
class LevelingConfigModel:
    """Configurable XP behavior for the public leveling feature."""

    enabled: bool = True
    message_xp_min: int = 15
    message_xp_max: int = 25
    message_cooldown_seconds: int = 60
    voice_xp_min_per_minute: int = 20
    voice_xp_max_per_minute: int = 30
    voice_group_bonus_multiplier: float = 1.5
    daily_base_xp: int = 100
    daily_streak_bonus_xp: int = 20
    daily_max_streak: int = 7
    ignored_channel_ids: tuple[int, ...] = field(default_factory=tuple)
    level_formula_quadratic: int = 5
    level_formula_linear: int = 50
    level_formula_constant: int = 100
    levelup_channel_id: int | None = None
    levelup_enabled: bool = True
    levelup_mention: bool = True
    levelup_message: str = DEFAULT_LEVELUP_MESSAGE
    xp_owner_user_id: int = DEFAULT_XP_OWNER_USER_ID
    xp_staff_role_ids: tuple[int, ...] = field(default_factory=tuple)
    staff_max_set_level: int = DEFAULT_STAFF_MAX_SET_LEVEL
    staff_max_xp_per_command: int = DEFAULT_STAFF_MAX_XP_PER_COMMAND

    def to_dict(self) -> dict[str, Any]:
        """Serialize the config for JSON persistence."""

        return {
            "enabled": self.enabled,
            "message_xp_min": self.message_xp_min,
            "message_xp_max": self.message_xp_max,
            "message_cooldown_seconds": self.message_cooldown_seconds,
            "voice_xp_min_per_minute": self.voice_xp_min_per_minute,
            "voice_xp_max_per_minute": self.voice_xp_max_per_minute,
            "voice_group_bonus_multiplier": self.voice_group_bonus_multiplier,
            "daily_base_xp": self.daily_base_xp,
            "daily_streak_bonus_xp": self.daily_streak_bonus_xp,
            "daily_max_streak": self.daily_max_streak,
            "ignored_channel_ids": list(self.ignored_channel_ids),
            "level_formula_quadratic": self.level_formula_quadratic,
            "level_formula_linear": self.level_formula_linear,
            "level_formula_constant": self.level_formula_constant,
            "levelup_channel_id": self.levelup_channel_id,
            "levelup_enabled": self.levelup_enabled,
            "levelup_mention": self.levelup_mention,
            "levelup_message": self.levelup_message,
            "level_up_message": self.levelup_message,
            "xp_owner_user_id": self.xp_owner_user_id,
            "xp_staff_role_ids": list(self.xp_staff_role_ids),
            "staff_max_set_level": self.staff_max_set_level,
            "staff_max_xp_per_command": self.staff_max_xp_per_command,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Deserialize the config from Dashboard JSON."""

        message_xp = payload.get("message_xp")
        voice_xp = payload.get("voice_xp_per_minute")
        return cls(
            enabled=bool(payload.get("enabled", True)),
            message_xp_min=max(
                0,
                int(payload.get("message_xp_min", message_xp or 15)),
            ),
            message_xp_max=max(
                0,
                int(payload.get("message_xp_max", message_xp or 25)),
            ),
            message_cooldown_seconds=max(
                0,
                int(payload.get("message_cooldown_seconds", 60)),
            ),
            voice_xp_min_per_minute=max(
                0,
                int(payload.get("voice_xp_min_per_minute", voice_xp or 20)),
            ),
            voice_xp_max_per_minute=max(
                0,
                int(payload.get("voice_xp_max_per_minute", voice_xp or 30)),
            ),
            voice_group_bonus_multiplier=max(
                1.0,
                float(payload.get("voice_group_bonus_multiplier", 1.5)),
            ),
            daily_base_xp=max(0, int(payload.get("daily_base_xp", 100))),
            daily_streak_bonus_xp=max(
                0,
                int(payload.get("daily_streak_bonus_xp", 20)),
            ),
            daily_max_streak=max(1, int(payload.get("daily_max_streak", 7))),
            ignored_channel_ids=_int_tuple(payload.get("ignored_channel_ids", [])),
            level_formula_quadratic=max(
                0,
                int(payload.get("level_formula_quadratic", 5)),
            ),
            level_formula_linear=max(0, int(payload.get("level_formula_linear", 50))),
            level_formula_constant=max(
                1,
                int(payload.get("level_formula_constant", 100)),
            ),
            levelup_channel_id=_optional_int(payload.get("levelup_channel_id")),
            levelup_enabled=bool(payload.get("levelup_enabled", True)),
            levelup_mention=bool(payload.get("levelup_mention", True)),
            levelup_message=str(
                payload.get("levelup_message")
                or payload.get("level_up_message")
                or DEFAULT_LEVELUP_MESSAGE,
            ),
            xp_owner_user_id=int(
                payload.get("xp_owner_user_id", DEFAULT_XP_OWNER_USER_ID),
            ),
            xp_staff_role_ids=_int_tuple(payload.get("xp_staff_role_ids", [])),
            staff_max_set_level=max(
                0,
                int(payload.get("staff_max_set_level", DEFAULT_STAFF_MAX_SET_LEVEL)),
            ),
            staff_max_xp_per_command=max(
                0,
                int(
                    payload.get(
                        "staff_max_xp_per_command",
                        DEFAULT_STAFF_MAX_XP_PER_COMMAND,
                    ),
                ),
            ),
        )

    @property
    def message_xp(self) -> int:
        """Return the minimum message XP for legacy callers."""

        return self.message_xp_min

    @property
    def voice_xp_per_minute(self) -> int:
        """Return the minimum voice XP for legacy callers."""

        return self.voice_xp_min_per_minute

    @property
    def level_xp_factor(self) -> int:
        """Return the default formula constant for legacy callers."""

        return self.level_formula_constant

    @property
    def level_up_message(self) -> str:
        """Return the level-up template for legacy callers."""

        return self.levelup_message


@dataclass(frozen=True)
class TicketConfigModel:
    """Dashboard-owned configuration for tickets and Tribunal workflows."""

    triage_channel_id: int | None = None
    staff_role_ids: tuple[int, ...] = field(default_factory=tuple)
    judge_role_ids: tuple[int, ...] = field(default_factory=tuple)
    admin_role_ids: tuple[int, ...] = field(default_factory=tuple)
    create_voice_channel: bool = False
    ticket_expiration_hours: int = 72
    archive_after_hours: int = 24
    tribunal_majority_votes: int = 3
    anonymous_reports_enabled: bool = False
    rate_limit_ticket_count: int = 2
    rate_limit_window_seconds: int = 3600
    transcript_channel_id: int | None = None
    dm_notifications_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize the config for JSON persistence."""

        return {
            "triage_channel_id": self.triage_channel_id,
            "staff_role_ids": list(self.staff_role_ids),
            "judge_role_ids": list(self.judge_role_ids),
            "admin_role_ids": list(self.admin_role_ids),
            "create_voice_channel": self.create_voice_channel,
            "ticket_expiration_hours": self.ticket_expiration_hours,
            "archive_after_hours": self.archive_after_hours,
            "tribunal_majority_votes": self.tribunal_majority_votes,
            "anonymous_reports_enabled": self.anonymous_reports_enabled,
            "rate_limit_ticket_count": self.rate_limit_ticket_count,
            "rate_limit_window_seconds": self.rate_limit_window_seconds,
            "transcript_channel_id": self.transcript_channel_id,
            "dm_notifications_enabled": self.dm_notifications_enabled,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Deserialize the ticket config from Dashboard JSON."""

        return cls(
            triage_channel_id=_optional_int(payload.get("triage_channel_id")),
            staff_role_ids=_int_tuple(payload.get("staff_role_ids", [])),
            judge_role_ids=_int_tuple(payload.get("judge_role_ids", [])),
            admin_role_ids=_int_tuple(payload.get("admin_role_ids", [])),
            create_voice_channel=bool(payload.get("create_voice_channel", False)),
            ticket_expiration_hours=max(
                1,
                int(payload.get("ticket_expiration_hours", 72)),
            ),
            archive_after_hours=max(1, int(payload.get("archive_after_hours", 24))),
            tribunal_majority_votes=max(
                1,
                int(payload.get("tribunal_majority_votes", 3)),
            ),
            anonymous_reports_enabled=bool(
                payload.get("anonymous_reports_enabled", False),
            ),
            rate_limit_ticket_count=max(
                1,
                int(payload.get("rate_limit_ticket_count", 2)),
            ),
            rate_limit_window_seconds=max(
                60,
                int(payload.get("rate_limit_window_seconds", 3600)),
            ),
            transcript_channel_id=_optional_int(payload.get("transcript_channel_id")),
            dm_notifications_enabled=bool(
                payload.get("dm_notifications_enabled", True),
            ),
        )


@dataclass(frozen=True)
class DashboardConfigModel:
    """Full guild configuration controlled by the Dashboard."""

    guild_id: int
    owner_user_id: int
    welcome: WelcomeConfigModel = field(default_factory=WelcomeConfigModel)
    leave: WelcomeConfigModel = field(
        default_factory=lambda: WelcomeConfigModel(
            message_template="{member} saiu do servidor.",
            embed_color=DEFAULT_LEAVE_COLOR,
        ),
    )
    logs: LogConfigModel = field(default_factory=LogConfigModel)
    auto_role: AutoRoleConfigModel = field(default_factory=AutoRoleConfigModel)
    auto_mod: AutoModConfigModel = field(default_factory=AutoModConfigModel)
    leveling: LevelingConfigModel = field(default_factory=LevelingConfigModel)
    tickets: TicketConfigModel = field(default_factory=TicketConfigModel)
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc),  # noqa: UP017
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the config for JSON persistence."""

        return {
            "guild_id": self.guild_id,
            "owner_user_id": self.owner_user_id,
            "welcome": self.welcome.to_dict(),
            "leave": self.leave.to_dict(),
            "logs": self.logs.to_dict(),
            "auto_role": self.auto_role.to_dict(),
            "auto_mod": self.auto_mod.to_dict(),
            "leveling": self.leveling.to_dict(),
            "tickets": self.tickets.to_dict(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def default(cls, *, guild_id: int, owner_user_id: int) -> Self:
        """Build the default persisted config for a guild."""

        return cls(guild_id=guild_id, owner_user_id=owner_user_id)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Deserialize the config from Dashboard JSON."""

        return cls(
            guild_id=int(payload["guild_id"]),
            owner_user_id=int(payload.get("owner_user_id", 0)),
            welcome=WelcomeConfigModel.from_dict(payload.get("welcome", {})),
            leave=WelcomeConfigModel.from_dict(payload.get("leave", {})),
            logs=LogConfigModel.from_dict(payload.get("logs", {})),
            auto_role=AutoRoleConfigModel.from_dict(payload.get("auto_role", {})),
            auto_mod=AutoModConfigModel.from_dict(payload.get("auto_mod", {})),
            leveling=LevelingConfigModel.from_dict(payload.get("leveling", {})),
            tickets=TicketConfigModel.from_dict(payload.get("tickets", {})),
            updated_at=_parse_optional_datetime(payload.get("updated_at")),
        )


@dataclass(frozen=True)
class UserLevelModel:
    """Persisted leveling state for a guild member."""

    guild_id: int
    user_id: int
    xp: int
    level: int
    message_count: int
    voice_seconds: int
    updated_at: datetime


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(str(value))


def _int_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(int(str(item)) for item in value if str(item).strip())


def _log_event_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return DEFAULT_LOG_EVENT_TYPES
    events = tuple(str(item).strip() for item in value if str(item).strip())
    return events or DEFAULT_LOG_EVENT_TYPES


def _parse_optional_datetime(value: object) -> datetime:
    if value:
        return datetime.fromisoformat(str(value))
    return datetime.now(tz=timezone.utc)  # noqa: UP017
