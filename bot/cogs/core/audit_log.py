"""Core audit-log maintenance for server behavior."""

from __future__ import annotations

from discord.ext import commands

from bot.services.audit_log_service import AuditLogService


class CoreAuditLog(commands.Cog):
    """Maintain core audit-log channel setup.

    Rich event logging lives in ``bot.cogs.logging.logging_cog``.
    """

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


async def setup(bot: commands.Bot) -> None:
    """Load the core audit log cog."""

    await bot.add_cog(CoreAuditLog(bot))
