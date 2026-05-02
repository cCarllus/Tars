"""Models for core server configuration and leveling state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Self

DEFAULT_WELCOME_COLOR = 0x2ECC71
DEFAULT_LEAVE_COLOR = 0xE74C3C


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

    def to_dict(self) -> dict[str, Any]:
        """Serialize the config for JSON persistence."""

        return {
            "channel_id": self.channel_id,
            "detail_level": int(self.detail_level),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Deserialize the config from Dashboard JSON."""

        return cls(
            channel_id=_optional_int(payload.get("channel_id")),
            detail_level=LogDetailLevel(int(payload.get("detail_level", 2))),
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
    message_xp: int = 15
    message_cooldown_seconds: int = 60
    voice_xp_per_minute: int = 5
    level_xp_factor: int = 100

    def to_dict(self) -> dict[str, Any]:
        """Serialize the config for JSON persistence."""

        return {
            "enabled": self.enabled,
            "message_xp": self.message_xp,
            "message_cooldown_seconds": self.message_cooldown_seconds,
            "voice_xp_per_minute": self.voice_xp_per_minute,
            "level_xp_factor": self.level_xp_factor,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Self:
        """Deserialize the config from Dashboard JSON."""

        return cls(
            enabled=bool(payload.get("enabled", True)),
            message_xp=max(0, int(payload.get("message_xp", 15))),
            message_cooldown_seconds=max(
                0,
                int(payload.get("message_cooldown_seconds", 60)),
            ),
            voice_xp_per_minute=max(0, int(payload.get("voice_xp_per_minute", 5))),
            level_xp_factor=max(1, int(payload.get("level_xp_factor", 100))),
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


def _parse_optional_datetime(value: object) -> datetime:
    if value:
        return datetime.fromisoformat(str(value))
    return datetime.now(tz=timezone.utc)  # noqa: UP017
