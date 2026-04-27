"""Welcome, leave and auto-role Discord event handlers."""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.services.welcome_service import WelcomeService


class WelcomeLeave(commands.Cog):
    """Handle configured member lifecycle events."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the cog."""

        self.bot = bot
        self.service = WelcomeService()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Process member join events through the configured service."""

        await self.service.handle_member_join(member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Process member leave events through the configured service."""

        await self.service.handle_member_remove(member)


async def setup(bot: commands.Bot) -> None:
    """Load the welcome and leave cog."""

    await bot.add_cog(WelcomeLeave(bot))
