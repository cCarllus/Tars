"""Automatic moderation checks for the core server feature."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import discord

from bot.database.models.core_models import AutoModConfigModel
from bot.services.audit_log_service import AuditLogService, audit_log_service
from bot.services.core_config_service import CoreConfigService, core_config_service
from bot.utils.queue_manager import discord_api_queue
from bot.utils.safe_discord import safe_delete_message

LINK_PREFIXES = ("http://", "https://")


@dataclass(frozen=True)
class AutoModResult:
    """Result of an automatic moderation check."""

    should_delete: bool
    reason: str | None = None


class AutoModService:
    """Execute configured moderation rules in the background."""

    def __init__(
        self,
        config_service: CoreConfigService | None = None,
        audit_service: AuditLogService | None = None,
    ) -> None:
        """Initialize the service."""

        self.config_service = config_service or core_config_service
        self.audit_service = audit_service or audit_log_service

    async def handle_message(self, message: discord.Message) -> AutoModResult:
        """Apply auto-mod rules to a Discord message."""

        if message.guild is None or message.author.bot:
            return AutoModResult(should_delete=False)

        config = await self.config_service.get_config(message.guild.id)
        result = self.evaluate_content(message.content, config.auto_mod)
        if not result.should_delete:
            return result

        await discord_api_queue.submit(
            action="delete_auto_mod_message",
            operation=lambda: safe_delete_message(
                message,
                reason="delete_auto_mod_message",
            ),
        )
        await self.audit_service.log_event(
            guild=message.guild,
            event_type="auto_mod_action",
            title="Auto-moderação aplicada",
            description=(
                f"Mensagem de {message.author.mention} removida: {result.reason}."
            ),
            payload={
                "channel_id": message.channel.id,
                "message_id": message.id,
                "reason": result.reason,
            },
            actor_user_id=message.author.id,
            target_user_id=message.author.id,
            color=discord.Color.orange(),
        )
        return result

    def evaluate_content(
        self,
        content: str,
        config: AutoModConfigModel,
    ) -> AutoModResult:
        """Evaluate configured text rules without touching Discord."""

        if not config.enabled:
            return AutoModResult(should_delete=False)

        normalized = content.casefold()
        for word in config.blocked_words:
            if word.casefold() in normalized:
                return AutoModResult(
                    should_delete=True,
                    reason="palavra bloqueada",
                )

        if config.block_links and self._has_blocked_link(normalized, config):
            return AutoModResult(should_delete=True, reason="link não permitido")

        return AutoModResult(should_delete=False)

    def _has_blocked_link(
        self,
        normalized_content: str,
        config: AutoModConfigModel,
    ) -> bool:
        tokens = normalized_content.split()
        allowed_domains = tuple(domain.casefold() for domain in config.allowed_links)
        for token in tokens:
            if not token.startswith(LINK_PREFIXES):
                continue

            hostname = urlparse(token).hostname or ""
            is_allowed = any(
                hostname == domain or hostname.endswith(f".{domain}")
                for domain in allowed_domains
            )
            if not is_allowed:
                return True
        return False


auto_mod_service = AutoModService()
