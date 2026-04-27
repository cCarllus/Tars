"""Discord event audit logging for core server behavior."""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.services.audit_log_service import AuditLogService


class CoreAuditLog(commands.Cog):
    """Capture relevant server events for configured audit logs."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the cog."""

        self.bot = bot
        self.service = AuditLogService()
        self._secured_guilds: set[int] = set()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Secure configured log channels when the bot becomes ready."""

        for guild in self.bot.guilds:
            if guild.id in self._secured_guilds:
                continue
            await self.service.ensure_log_channel_permissions(guild)
            self._secured_guilds.add(guild.id)

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """Audit deleted user messages."""

        if message.guild is None or message.author.bot:
            return

        await self.service.log_event(
            guild=message.guild,
            event_type="message_delete",
            title="Mensagem removida",
            description=f"Mensagem de {message.author.mention} removida.",
            payload={
                "message_id": message.id,
                "channel_id": message.channel.id,
                "author_id": message.author.id,
                "content": message.content[:500],
            },
            actor_user_id=message.author.id,
            target_user_id=message.author.id,
            color=discord.Color.orange(),
        )

    @commands.Cog.listener()
    async def on_member_update(
        self,
        before: discord.Member,
        after: discord.Member,
    ) -> None:
        """Audit visible member profile changes such as nickname updates."""

        if before.display_name == after.display_name:
            return

        await self.service.log_event(
            guild=after.guild,
            event_type="member_update",
            title="Perfil atualizado",
            description=(
                f"{after.mention} alterou o nome exibido de "
                f"`{before.display_name}` para `{after.display_name}`."
            ),
            payload={
                "member_id": after.id,
                "before_display_name": before.display_name,
                "after_display_name": after.display_name,
            },
            actor_user_id=after.id,
            target_user_id=after.id,
        )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Audit voice channel moves at the detailed log level."""

        if member.bot or before.channel == after.channel:
            return

        before_id = before.channel.id if before.channel else None
        after_id = after.channel.id if after.channel else None
        await self.service.log_event(
            guild=member.guild,
            event_type="voice_state_update",
            title="Voz atualizada",
            description=f"{member.mention} mudou de canal de voz.",
            payload={
                "member_id": member.id,
                "before_channel_id": before_id,
                "after_channel_id": after_id,
            },
            actor_user_id=member.id,
            target_user_id=member.id,
        )


async def setup(bot: commands.Bot) -> None:
    """Load the core audit log cog."""

    await bot.add_cog(CoreAuditLog(bot))
