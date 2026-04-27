"""Background checker for automatic game promotion posts."""

from __future__ import annotations

import asyncio
import random

import discord
from discord.ext import commands

from bot.config import settings
from bot.logger import logger
from bot.services.game_deals_service import GameDealsService
from bot.utils.game_deals_cache import GameDealsCache
from bot.utils.promo_embeds import PromoDealsView, build_automatic_promo_embed
from bot.utils.safe_discord import safe_send_message

MIN_CHECK_INTERVAL_SECONDS = 45 * 60
MAX_CHECK_INTERVAL_SECONDS = 60 * 60


class PromoChecker:
    """Periodically post relevant game deals in the promo channel."""

    def __init__(
        self,
        *,
        bot: commands.Bot,
        service: GameDealsService,
        cache: GameDealsCache,
    ) -> None:
        """Initialize the checker dependencies."""

        self._bot = bot
        self._service = service
        self._cache = cache
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the background checker if it is not already running."""

        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="games-promo-checker")

    async def stop(self) -> None:
        """Stop the background checker."""

        if self._task is None:
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            logger.info("Games promo checker stopped")

    async def check_once(self) -> bool:
        """Run one automatic promo check and return whether a post was sent."""

        if not await self._cache.can_post_today():
            logger.info(
                "Skipping game promo automatic post: daily limit reached",
                extra={"action": "games_promo_auto", "reason": "daily_limit"},
            )
            return False

        summary = await self._service.fetch_promos()
        relevant_deals = self._service.select_automatic_deals(summary)
        unposted_deals = await self._cache.filter_unposted(relevant_deals)
        if not unposted_deals:
            logger.info(
                "Skipping game promo automatic post: no new deals",
                extra={"action": "games_promo_auto", "reason": "no_new_deals"},
            )
            return False

        channel = await self._resolve_promo_channel()
        if channel is None:
            logger.warning(
                "Skipping game promo automatic post: promo channel not found",
                extra={"action": "games_promo_auto", "reason": "channel_not_found"},
            )
            return False

        embed = build_automatic_promo_embed(unposted_deals)
        view = PromoDealsView(unposted_deals)
        await safe_send_message(
            channel,
            embed=embed,
            view=view,
            reason="send_games_promo_auto",
        )
        await self._cache.mark_posted(unposted_deals)
        logger.info(
            "Posted automatic game promotions action=games_promo_auto count=%s",
            len(unposted_deals),
            extra={
                "action": "games_promo_auto",
                "success": True,
                "deal_count": len(unposted_deals),
            },
        )
        return True

    async def _run(self) -> None:
        await self._bot.wait_until_ready()

        while not self._bot.is_closed():
            try:
                await self.check_once()
            except Exception:
                logger.exception(
                    "Unexpected error while checking game promotions",
                    extra={"action": "games_promo_auto", "success": False},
                )

            await asyncio.sleep(
                random.uniform(MIN_CHECK_INTERVAL_SECONDS, MAX_CHECK_INTERVAL_SECONDS),
            )

    async def _resolve_promo_channel(self) -> discord.abc.Messageable | None:
        channel = self._bot.get_channel(settings.promo_channel_id)
        if channel is None:
            try:
                channel = await self._bot.fetch_channel(settings.promo_channel_id)
            except discord.HTTPException:
                logger.exception("Failed to fetch promo channel")
                return None

        if isinstance(channel, discord.abc.Messageable):
            return channel
        return None
