"""Temporary private voice call cog."""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.logger import logger
from bot.utils.private_voice_embeds import build_private_voice_control_embed
from bot.utils.private_voice_manager import PrivateVoiceManager
from bot.utils.private_voice_view import PrivateVoiceControlView
from bot.utils.queue_manager import discord_api_queue
from bot.utils.rate_limiter import RateLimitExceeded
from bot.utils.safe_discord import safe_send_message


class PrivateVoiceCalls(commands.Cog):
    """Create and manage temporary private voice calls from a hub channel."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the private voice calls cog."""

        self.bot = bot
        self.manager = PrivateVoiceManager()
        self._sessions_reconciled = False

    async def cog_load(self) -> None:
        """Initialize dependencies used by the cog."""

        await self.manager.initialize()
        await discord_api_queue.start()

    async def cog_unload(self) -> None:
        """Stop background queue workers when the cog unloads."""

        await discord_api_queue.stop()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Recover or remove persisted private voice sessions on startup."""

        if self._sessions_reconciled:
            return

        await self.manager.reconcile_voice_sessions(self.bot.guilds)
        self._sessions_reconciled = True

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Create private calls from the hub and delete empty temporary calls."""

        await self._handle_hub_join(member=member, before=before, after=after)
        await self._handle_private_call_leave(before=before, after=after)

    async def _handle_hub_join(
        self,
        *,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot or before.channel == after.channel:
            return

        if not isinstance(after.channel, discord.VoiceChannel):
            return

        if not self.manager.is_hub_channel(after.channel):
            return

        try:
            channel, created = await self.manager.get_or_create_private_call(
                member=member,
                hub_channel=after.channel,
            )
            await self.manager.move_member_to_call(member=member, channel=channel)

            if created:
                await self._send_control_message(owner=member, channel=channel)
        except discord.Forbidden:
            logger.exception(
                "Missing permissions while creating private voice call for %s",
                member.id,
            )
        except RateLimitExceeded:
            logger.warning(
                "Rate limited private voice call creation for member %s in guild %s",
                member.id,
                member.guild.id,
            )
        except discord.HTTPException:
            logger.exception("Discord API error while creating private voice call")

    async def _handle_private_call_leave(
        self,
        *,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if before.channel == after.channel:
            return

        if not isinstance(before.channel, discord.VoiceChannel):
            return

        try:
            await self.manager.delete_if_empty(before.channel)
        except discord.Forbidden:
            logger.exception(
                "Missing permissions while deleting private voice call %s",
                before.channel.id,
            )
        except discord.NotFound:
            logger.info(
                "Private voice call %s was already deleted before leave cleanup",
                before.channel.id,
            )
        except discord.HTTPException:
            logger.exception(
                "Discord API error while deleting private voice call %s",
                before.channel.id,
            )

    async def _send_control_message(
        self,
        *,
        owner: discord.Member,
        channel: discord.VoiceChannel,
    ) -> None:
        embed = build_private_voice_control_embed(owner=owner, channel=channel)
        view = PrivateVoiceControlView(
            manager=self.manager,
            channel=channel,
            owner=owner,
        )
        await discord_api_queue.submit(
            action="send_private_voice_control_message",
            operation=lambda: safe_send_message(
                channel,
                content=f"{owner.mention}, sua call privada foi criada.",
                embed=embed,
                view=view,
                reason="send_private_voice_control_message",
            ),
        )


async def setup(bot: commands.Bot) -> None:
    """Load the private voice calls cog."""

    await bot.add_cog(PrivateVoiceCalls(bot))
