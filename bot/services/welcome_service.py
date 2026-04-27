"""Welcome, leave and auto-role behavior for core server features."""

from __future__ import annotations

import discord

from bot.database.models.core_models import WelcomeConfigModel
from bot.logger import logger
from bot.services.audit_log_service import AuditLogService, audit_log_service
from bot.services.core_config_service import CoreConfigService, core_config_service
from bot.utils.queue_manager import discord_api_queue
from bot.utils.safe_discord import safe_add_role, safe_send_message


class WelcomeService:
    """Handle member join and leave side effects."""

    def __init__(
        self,
        config_service: CoreConfigService | None = None,
        audit_service: AuditLogService | None = None,
    ) -> None:
        """Initialize the service."""

        self.config_service = config_service or core_config_service
        self.audit_service = audit_service or audit_log_service

    async def handle_member_join(self, member: discord.Member) -> None:
        """Assign auto-role and send welcome embed for a new member."""

        config = await self.config_service.get_config(member.guild.id)
        if config.auto_role.enabled and config.auto_role.role_id is not None:
            await self._assign_auto_role(member, config.auto_role.role_id)

        await self._send_member_embed(
            member=member,
            embed_config=config.welcome,
            title="Bem-vindo(a)",
            event_type="member_join",
        )
        await self.audit_service.log_event(
            guild=member.guild,
            event_type="member_join",
            title="Membro entrou",
            description=f"{member.mention} entrou no servidor.",
            payload={"member_id": member.id, "member_name": str(member)},
            target_user_id=member.id,
        )

    async def handle_member_remove(self, member: discord.Member) -> None:
        """Send leave embed for a departing member."""

        config = await self.config_service.get_config(member.guild.id)
        await self._send_member_embed(
            member=member,
            embed_config=config.leave,
            title="Membro saiu",
            event_type="member_leave",
        )
        await self.audit_service.log_event(
            guild=member.guild,
            event_type="member_leave",
            title="Membro saiu",
            description=f"{member} saiu do servidor.",
            payload={"member_id": member.id, "member_name": str(member)},
            target_user_id=member.id,
        )

    async def _assign_auto_role(self, member: discord.Member, role_id: int) -> None:
        role = member.guild.get_role(role_id)
        if role is None:
            logger.error(
                "Configured auto role does not exist guild_id=%s role_id=%s",
                member.guild.id,
                role_id,
            )
            await self.audit_service.log_event(
                guild=member.guild,
                event_type="auto_role_missing",
                title="Cargo automático não encontrado",
                description="O cargo automático configurado não existe mais.",
                payload={"role_id": role_id},
                color=discord.Color.red(),
            )
            await self.audit_service.send_owner_alert(
                guild=member.guild,
                title="Cargo automático inválido",
                description=(
                    "O cargo automático configurado na Dashboard não existe mais. "
                    "Atualize a configuração antes da próxima entrada de membro."
                ),
                color=discord.Color.red(),
            )
            return

        await discord_api_queue.submit(
            action="assign_core_auto_role",
            operation=lambda: safe_add_role(
                member,
                role,
                reason="Cargo automático configurado na Dashboard TARS",
            ),
        )

    async def _send_member_embed(
        self,
        *,
        member: discord.Member,
        embed_config: WelcomeConfigModel,
        title: str,
        event_type: str,
    ) -> None:
        if not embed_config.enabled:
            return

        channel = self._resolve_channel(member.guild, embed_config.channel_id)
        if channel is None:
            logger.warning(
                "No channel available for %s guild_id=%s",
                event_type,
                member.guild.id,
            )
            await self.audit_service.send_owner_alert(
                guild=member.guild,
                title="Canal configurado inválido",
                description=(
                    "Um canal de welcome/leave configurado na Dashboard não "
                    "existe mais e precisa ser atualizado."
                ),
                color=discord.Color.red(),
            )
            return

        description = embed_config.message_template.format(
            member=member.mention,
            server=member.guild.name,
        )
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color(embed_config.embed_color),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        await discord_api_queue.submit(
            action=f"send_core_{event_type}",
            operation=lambda: safe_send_message(
                channel,
                embed=embed,
                reason=f"send_core_{event_type}",
            ),
        )

    def _resolve_channel(
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


welcome_service = WelcomeService()
