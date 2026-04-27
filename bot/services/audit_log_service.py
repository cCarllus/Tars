"""Discord and Dashboard audit logging for core server events."""

from __future__ import annotations

from typing import Any

import discord

from bot.config import settings
from bot.database.models.core_models import LogDetailLevel
from bot.logger import logger
from bot.services.core_config_service import CoreConfigService, core_config_service
from bot.utils.embed import INFO_COLOR, build_embed
from bot.utils.queue_manager import discord_api_queue
from bot.utils.safe_discord import (
    safe_edit_channel_permissions,
    safe_send_dm,
    safe_send_message,
)

EVENT_DETAIL_LEVELS: dict[str, LogDetailLevel] = {
    "member_join": LogDetailLevel.BASIC,
    "member_leave": LogDetailLevel.BASIC,
    "auto_mod_action": LogDetailLevel.BASIC,
    "message_delete": LogDetailLevel.NORMAL,
    "member_update": LogDetailLevel.NORMAL,
    "voice_state_update": LogDetailLevel.DETAILED,
    "dashboard_config_updated": LogDetailLevel.DETAILED,
}


class AuditLogService:
    """Write audit events to SQLite and the configured Discord log channel."""

    def __init__(self, config_service: CoreConfigService | None = None) -> None:
        """Initialize the service."""

        self.config_service = config_service or core_config_service

    async def log_event(
        self,
        *,
        guild: discord.Guild,
        event_type: str,
        title: str,
        description: str,
        payload: dict[str, Any],
        actor_user_id: int | None = None,
        target_user_id: int | None = None,
        color: discord.Color = INFO_COLOR,
    ) -> None:
        """Persist and optionally publish an audit event."""

        required_level = EVENT_DETAIL_LEVELS.get(event_type, LogDetailLevel.DETAILED)
        await self.config_service.record_audit_event(
            guild_id=guild.id,
            event_type=event_type,
            detail_level=int(required_level),
            payload=payload,
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
        )

        config = await self.config_service.get_config(guild.id)
        if required_level > config.logs.detail_level:
            return

        if (
            config.logs.channel_id is not None
            and guild.get_channel(
                config.logs.channel_id,
            )
            is None
        ):
            await self.send_owner_alert(
                guild=guild,
                title="Canal de logs inválido",
                description=(
                    "O canal de logs configurado na Dashboard não existe mais. "
                    "Atualize a configuração para restaurar os logs no canal correto."
                ),
                color=discord.Color.red(),
            )

        channel = self._resolve_log_channel(guild, config.logs.channel_id)
        if channel is None:
            logger.warning("No audit log channel available guild_id=%s", guild.id)
            return

        embed = build_embed(title=title, description=description, color=color)
        embed.set_footer(text=f"Evento: {event_type}")
        await discord_api_queue.submit(
            action="send_core_audit_log",
            operation=lambda: safe_send_message(
                channel,
                embed=embed,
                reason="send_core_audit_log",
            ),
        )

    async def send_owner_alert(
        self,
        *,
        guild: discord.Guild,
        title: str,
        description: str,
        color: discord.Color,
    ) -> None:
        """Send a critical alert to the configured owner when possible."""

        owner = self._resolve_owner_member(guild)
        if owner is None:
            logger.warning("No owner member available for alert guild_id=%s", guild.id)
            return

        embed = build_embed(title=title, description=description, color=color)
        await discord_api_queue.submit(
            action="send_core_owner_alert",
            operation=lambda: safe_send_dm(owner, embed=embed),
        )

    async def ensure_log_channel_permissions(self, guild: discord.Guild) -> None:
        """Deny log-channel visibility to everyone except administrators."""

        config = await self.config_service.get_config(guild.id)
        channel = self._resolve_log_channel(guild, config.logs.channel_id)
        if channel is None or not isinstance(channel, discord.abc.GuildChannel):
            return

        overwrite = discord.PermissionOverwrite(view_channel=False)
        await discord_api_queue.submit(
            action="secure_core_log_channel",
            operation=lambda: safe_edit_channel_permissions(
                channel,
                guild.default_role,
                overwrite=overwrite,
                reason="Restringir logs do TARS a administradores",
            ),
        )

    def _resolve_log_channel(
        self,
        guild: discord.Guild,
        channel_id: int | None,
    ) -> discord.TextChannel | discord.Thread | None:
        if channel_id is not None:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel | discord.Thread):
                return channel

        fallback = guild.system_channel
        if isinstance(fallback, discord.TextChannel):
            return fallback
        return None

    def _resolve_owner_member(self, guild: discord.Guild) -> discord.Member | None:
        if settings.tars_owner_user_id:
            configured_owner = guild.get_member(settings.tars_owner_user_id)
            if configured_owner is not None:
                return configured_owner

        return guild.owner


def warning_payload(message: str) -> dict[str, str]:
    """Build a small payload for warning audit events."""

    return {"message": message, "severity": "warning"}


audit_log_service = AuditLogService()
