"""Games promo tracker cog."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import settings
from bot.logger import logger
from bot.services.game_deals_service import (
    ITAD_CONFIG_MISSING_FAILURE,
    GameDealsService,
)
from bot.tasks.promo_checker import PromoChecker
from bot.utils.embed import error_embed
from bot.utils.game_deals_cache import GameDealsCache
from bot.utils.promo_embeds import PromoDealsView, build_games_promo_embed
from bot.utils.safe_discord import safe_send_message

PROMO_CACHE_PATH = "bot/database/games_promo_cache.json"


class GamesPromoTracker(commands.Cog):
    """Expose manual and automatic game promotion tracking."""

    games_group = app_commands.Group(
        name="games",
        description="Comandos de jogos.",
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the promo tracker cog."""

        self.bot = bot
        self.service = GameDealsService(
            itad_api_key=settings.itad_api_key,
            itad_client_id=settings.itad_client_id,
        )
        self.cache = GameDealsCache(PROMO_CACHE_PATH)
        self.checker = PromoChecker(
            bot=bot,
            service=self.service,
            cache=self.cache,
        )

    async def cog_load(self) -> None:
        """Start the automatic promo checker."""

        self.checker.start()

    async def cog_unload(self) -> None:
        """Stop the automatic promo checker."""

        await self.checker.stop()

    @games_group.command(
        name="promo",
        description="Mostra as melhores promoções de jogos do momento.",
    )
    async def games_promo(self, interaction: discord.Interaction) -> None:
        """Send a visual summary of current game promotions."""

        if not self._is_promo_channel(interaction.channel_id):
            await interaction.response.send_message(
                embed=error_embed(
                    "Esse comando só funciona no canal #・promocoes.",
                    title="Canal incorreto",
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        summary = await self.service.fetch_promos()

        if ITAD_CONFIG_MISSING_FAILURE in summary.partial_failures:
            await interaction.followup.send(
                "Não consigo consultar promoções reais da Steam/Epic Brasil "
                "porque `ITAD_API_KEY` não está configurada no `.env`.",
                ephemeral=True,
            )
            return

        embed = build_games_promo_embed(summary)
        view = PromoDealsView([*summary.free_epic, *summary.best_deals])

        if not isinstance(interaction.channel, discord.abc.Messageable):
            await interaction.followup.send(
                "Não consegui publicar as promoções neste canal.",
                ephemeral=True,
            )
            return

        await safe_send_message(
            interaction.channel,
            embed=embed,
            view=view,
            reason="send_games_promo_manual",
        )
        await interaction.followup.send(
            "Promoções publicadas neste canal.",
            ephemeral=True,
        )
        logger.info(
            "Manual game promotions posted action=games_promo_manual "
            "channel_id=%s user_id=%s",
            interaction.channel_id,
            interaction.user.id if interaction.user else None,
            extra={
                "action": "games_promo_manual",
                "success": True,
                "channel_id": interaction.channel_id,
                "user_id": interaction.user.id if interaction.user else None,
            },
        )

    def _is_promo_channel(self, channel_id: int | None) -> bool:
        return channel_id == settings.promo_channel_id


async def setup(bot: commands.Bot) -> None:
    """Load the games promo tracker cog."""

    await bot.add_cog(GamesPromoTracker(bot))
