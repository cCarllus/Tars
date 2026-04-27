"""Discord embeds and link buttons for game promotions."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import discord

from bot.services.game_deals_service import (
    ITAD_CONFIG_MISSING_FAILURE,
    GameDeal,
    GamePromoSummary,
)

PROMO_COLOR = discord.Color.from_rgb(255, 118, 35)
MAX_BUTTON_DEALS = 5
MAX_FIELD_VALUE_LENGTH = 1024


def build_games_promo_embed(summary: GamePromoSummary) -> discord.Embed:
    """Build the manual `/games promo` embed."""

    description = "Resumo das melhores promoções encontradas agora."
    if ITAD_CONFIG_MISSING_FAILURE in summary.partial_failures:
        description += (
            "\nNão consegui consultar Steam/Epic Brasil porque a chave ITAD "
            "não está configurada."
        )
    elif summary.partial_failures:
        description += "\nAlgumas fontes falharam, então usei os dados disponíveis."

    embed = discord.Embed(
        title="🔥 Promoções do Momento",
        description=description,
        color=PROMO_COLOR,
        timestamp=summary.generated_at,
    )
    _add_deals_fields(embed, free_epic=summary.free_epic, best_deals=summary.best_deals)
    _set_first_image(embed, [*summary.free_epic, *summary.best_deals])
    embed.set_footer(text="Dados: IsThereAnyDeal Brasil (Steam/Epic)")
    return embed


def build_automatic_promo_embed(deals: list[GameDeal]) -> discord.Embed:
    """Build an embed for automatic promotion posts."""

    embed = discord.Embed(
        title="🔥 Promoções do Momento",
        description="Novas promoções relevantes detectadas automaticamente.",
        color=PROMO_COLOR,
        timestamp=datetime.now(tz=UTC),
    )

    free_epic = [
        deal for deal in deals if deal.is_free and "epic" in deal.store.casefold()
    ]
    best_deals = [deal for deal in deals if deal not in free_epic]
    _add_deals_fields(embed, free_epic=free_epic, best_deals=best_deals)
    _set_first_image(embed, deals)
    embed.set_footer(text="Dados: IsThereAnyDeal Brasil (Steam/Epic)")
    return embed


class PromoDealsView(discord.ui.View):
    """Link buttons for promotion offers."""

    def __init__(self, deals: list[GameDeal]) -> None:
        """Create offer buttons for the first visible deals."""

        super().__init__(timeout=None)
        for deal in deals[:MAX_BUTTON_DEALS]:
            if not deal.url:
                continue

            self.add_item(
                discord.ui.Button(
                    label=_button_label(deal),
                    style=discord.ButtonStyle.link,
                    url=deal.url,
                ),
            )


def _add_deals_fields(
    embed: discord.Embed,
    *,
    free_epic: list[GameDeal],
    best_deals: list[GameDeal],
) -> None:
    if free_epic:
        embed.add_field(
            name="🎁 Grátis na Epic",
            value=_format_deals(free_epic),
            inline=False,
        )

    embed.add_field(
        name="🔥 Melhores Ofertas",
        value=_format_deals(best_deals) if best_deals else "Nenhuma oferta encontrada.",
        inline=False,
    )


def _format_deals(deals: list[GameDeal]) -> str:
    lines = [_format_deal(index, deal) for index, deal in enumerate(deals, start=1)]
    value = "\n\n".join(lines)
    if len(value) <= MAX_FIELD_VALUE_LENGTH:
        return value
    return f"{value[: MAX_FIELD_VALUE_LENGTH - 1]}…"


def _format_deal(index: int, deal: GameDeal) -> str:
    badges = []
    if deal.discount_percent > 0:
        badges.append(f"🟢 -{deal.discount_percent}%")
    if deal.historical_low:
        badges.append("Historical Low")

    expires_at = _format_expiry(deal.expires_at)
    if expires_at:
        badges.append(f"termina {expires_at}")

    price = _format_price_line(deal)
    details = " · ".join(badges)
    link = f" · [Ver oferta]({deal.url})" if deal.url else ""
    suffix = f"\n{details}" if details else ""
    return f"**{index}. {deal.title}** ({deal.store})\n{price}{suffix}{link}"


def _format_price_line(deal: GameDeal) -> str:
    if deal.is_free:
        return "Grátis"

    current = _format_money(deal.current_price, deal.currency)
    if deal.original_price > deal.current_price:
        original = _format_money(deal.original_price, deal.currency)
        return f"{current} ~~{original}~~"
    return current


def _format_money(value: Decimal, currency: str) -> str:
    prefix = {
        "BRL": "R$",
        "USD": "US$",
        "EUR": "€",
    }.get(currency.upper(), currency.upper())
    return f"{prefix} {value:.2f}".strip()


def _format_expiry(expires_at: datetime | None) -> str:
    if expires_at is None:
        return ""

    local_expiry = expires_at.astimezone(UTC)
    return local_expiry.strftime("%d/%m %H:%M UTC")


def _set_first_image(embed: discord.Embed, deals: list[GameDeal]) -> None:
    image_url = next((deal.image_url for deal in deals if deal.image_url), None)
    if image_url:
        embed.set_thumbnail(url=image_url)


def _button_label(deal: GameDeal) -> str:
    store = deal.store.casefold()
    if "steam" in store:
        return "Steam"
    if "epic" in store:
        return "Epic"
    return "Ver Oferta"
