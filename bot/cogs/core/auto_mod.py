"""Auto-moderation Discord event handlers."""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.services.auto_mod_service import AutoModService


class AutoMod(commands.Cog):
    """Apply Dashboard-configured moderation rules to messages."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the cog."""

        self.bot = bot
        self.service = AutoModService()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Moderate incoming guild messages."""

        await self.service.handle_message(message)


async def setup(bot: commands.Bot) -> None:
    """Load the auto-mod cog."""

    await bot.add_cog(AutoMod(bot))
