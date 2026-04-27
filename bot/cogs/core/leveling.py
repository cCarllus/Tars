"""Public leveling commands and XP event handlers."""

from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord.ext import commands

from bot.database.models.core_models import UserLevelModel
from bot.services.leveling_service import LevelingService
from bot.utils.embed import build_embed
from bot.utils.locks import lock_registry


class CoreLeveling(commands.Cog):
    """Award XP and expose public leveling commands."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the cog."""

        self.bot = bot
        self.service = LevelingService()
        self._voice_joined_at: dict[tuple[int, int], datetime] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Award message XP to guild members."""

        if message.guild is None or message.author.bot:
            return

        async with lock_registry.user(message.author.id):
            await self.service.add_message_xp(
                guild_id=message.guild.id,
                user_id=message.author.id,
                created_at=message.created_at,
            )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Award voice XP when a member leaves or moves voice channels."""

        if member.bot or before.channel == after.channel:
            return

        key = (member.guild.id, member.id)
        now = datetime.now(tz=timezone.utc)  # noqa: UP017
        if before.channel is not None and key in self._voice_joined_at:
            joined_at = self._voice_joined_at.pop(key)
            voice_seconds = int((now - joined_at).total_seconds())
            async with lock_registry.user(member.id):
                await self.service.add_voice_xp(
                    guild_id=member.guild.id,
                    user_id=member.id,
                    voice_seconds=voice_seconds,
                )

        if after.channel is not None:
            self._voice_joined_at[key] = now

    @commands.group(name="level", invoke_without_command=True)
    async def level_group(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show the caller's level using the `/level` text command."""

        if ctx.guild is None:
            await ctx.reply("Esse comando só funciona dentro do servidor.")
            return

        record = await self.service.get_user_level(
            guild_id=ctx.guild.id,
            user_id=ctx.author.id,
        )
        await ctx.reply(embed=self._build_level_embed(ctx.author, record))

    @level_group.command(name="top")  # type: ignore[arg-type]
    async def level_top(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show the public leaderboard using the `/level top` text command."""

        if ctx.guild is None:
            await ctx.reply("Esse comando só funciona dentro do servidor.")
            return

        leaderboard = await self.service.get_leaderboard(guild_id=ctx.guild.id)
        description = self._format_leaderboard(ctx.guild, leaderboard)
        await ctx.reply(
            embed=build_embed(
                title="Leaderboard TARS",
                description=description,
                color=discord.Color.gold(),
            ),
        )

    def _build_level_embed(
        self,
        user: discord.abc.User,
        record: UserLevelModel,
    ) -> discord.Embed:
        return build_embed(
            title="Seu nível",
            description=(
                f"{user.mention}\n"
                f"Nível: **{record.level}**\n"
                f"XP: **{record.xp}**"
            ),
            color=discord.Color.blurple(),
        )

    def _format_leaderboard(
        self,
        guild: discord.Guild,
        leaderboard: list[UserLevelModel],
    ) -> str:
        if not leaderboard:
            return "Ainda não há XP registrado."

        lines: list[str] = []
        for index, record in enumerate(leaderboard, start=1):
            member = guild.get_member(record.user_id)
            display_name = (
                member.display_name if member else f"Usuário {record.user_id}"
            )
            lines.append(
                f"**{index}.** {display_name} - nível {record.level}, {record.xp} XP",
            )
        return "\n".join(lines)


async def setup(bot: commands.Bot) -> None:
    """Load the leveling cog."""

    await bot.add_cog(CoreLeveling(bot))
