"""Public agenda commands."""

from pathlib import Path

import discord
from discord.ext import commands

from bot.config import settings
from bot.utils.embed import error_embed, success_embed


class Agenda(commands.Cog):
    """Commands for a simple public agenda backed by a text file."""

    def __init__(self, bot: commands.Bot, agenda_path: Path | None = None) -> None:
        self.bot = bot
        self.agenda_path = agenda_path or settings.schedule_file

    def _read_items(self) -> list[str]:
        """Read agenda items from disk."""

        self.agenda_path.parent.mkdir(parents=True, exist_ok=True)
        self.agenda_path.touch(exist_ok=True)
        return self.agenda_path.read_text(encoding="utf-8").splitlines()

    def _write_items(self, items: list[str]) -> None:
        """Write agenda items to disk."""

        content = "\n".join(items)
        if content:
            content += "\n"
        self.agenda_path.write_text(content, encoding="utf-8")

    @commands.command(
        name="agenda",
        help="Lista tarefas publicas de todos os usuarios.",
    )
    async def personal_list(self, ctx: commands.Context[commands.Bot]) -> None:
        """Send the public agenda to the current channel."""

        items = self._read_items()
        embed = discord.Embed(
            title="AGENDA PUBLICA",
            description="Sem anotacoes por enquanto." if not items else "Abaixo:",
            color=0x22408A,
        )

        for index, item in enumerate(items, start=1):
            embed.add_field(name=f"**{index}**", value=item, inline=False)

        footer = "Use $adicionar [anotacao] para adicionar e $remover [id]."
        embed.set_footer(text=footer)
        await ctx.channel.send(embed=embed)

    @commands.command(name="adicionar")
    async def add_argument_to_list(
        self,
        ctx: commands.Context[commands.Bot],
        *,
        content: str,
    ) -> None:
        """Add an item to the public agenda."""

        item = f"{content.strip()} | {ctx.author.mention}"
        items = self._read_items()
        items.append(item)
        self._write_items(items)

        await ctx.channel.send(embed=success_embed(f"**{content}** foi adicionado."))

    @commands.command(name="remover")
    async def remove_argument_from_list(
        self,
        ctx: commands.Context[commands.Bot],
        item_id: int,
    ) -> None:
        """Remove an item from the public agenda by its 1-based index."""

        items = self._read_items()
        index = item_id - 1

        if index < 0 or index >= len(items):
            await ctx.channel.send(embed=error_embed("Indice invalido."))
            return

        removed_item = items.pop(index)
        self._write_items(items)

        await ctx.channel.send(
            embed=success_embed(f"O indice `{item_id}` foi excluido: {removed_item}"),
        )


async def setup(bot: commands.Bot) -> None:
    """Register the cog."""

    await bot.add_cog(Agenda(bot))
