"""Message cleanup commands."""

import discord
from discord.ext import commands

from bot.utils.embed import error_embed, success_embed

MAX_PURGE_AMOUNT = 149
DEFAULT_PURGE_AMOUNT = 5


class Clear(commands.Cog):
    """Administrative message cleanup commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(
        name="limpar",
        help="Limpa mensagens do chat. Use: $limpar <quantidade>",
    )
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clear(
        self,
        ctx: commands.Context[commands.Bot],
        amount: int = DEFAULT_PURGE_AMOUNT,
    ) -> None:
        """Delete recent messages from the current channel."""

        if amount < 1:
            await ctx.send(embed=error_embed("Informe uma quantidade maior que zero."))
            return

        if amount > MAX_PURGE_AMOUNT:
            await ctx.send(
                embed=error_embed(
                    f"Você não pode apagar mais que {MAX_PURGE_AMOUNT} mensagens.",
                ),
            )
            return

        if not isinstance(ctx.channel, discord.TextChannel | discord.Thread):
            await ctx.send(
                embed=error_embed("Esse comando so funciona em canais de servidor."),
            )
            return

        await ctx.channel.purge(limit=amount)
        await ctx.send(
            embed=success_embed(
                f"{ctx.author.mention}, mensagens apagadas com sucesso.",
            ),
            delete_after=8,
        )

    @clear.error
    async def clear_error(
        self,
        ctx: commands.Context[commands.Bot],
        error: commands.CommandError,
    ) -> None:
        """Handle permission and argument errors for the clear command."""

        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                embed=error_embed("Você precisa da permissão de gerenciar mensagens."),
            )
            return

        if isinstance(error, commands.BotMissingPermissions):
            await ctx.send(
                embed=error_embed("Eu preciso da permissão de gerenciar mensagens."),
            )
            return

        if isinstance(error, commands.BadArgument):
            await ctx.send(embed=error_embed("Use: `$limpar <quantidade>`"))
            return

        raise error


async def setup(bot: commands.Bot) -> None:
    """Register the cog."""

    await bot.add_cog(Clear(bot))
