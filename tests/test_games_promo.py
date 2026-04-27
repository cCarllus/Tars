"""Tests for the Games Promo Tracker feature."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from bot.services.game_deals_service import (
    BR_STEAM_EPIC_SHOPS,
    CHEAPSHARK_DEALS_URL,
    EPIC_ITAD_SHOP_ID,
    ITAD_CONFIG_MISSING_FAILURE,
    ITAD_DEALS_URL,
    GameDeal,
    GameDealsService,
    QueryValue,
)
from bot.utils.game_deals_cache import GameDealsCache


def test_game_deals_service_combines_cheapshark_and_itad() -> None:
    """Ensure manual promos combine both sources and detect Epic free games."""

    calls: list[tuple[str, Mapping[str, QueryValue]]] = []

    async def fake_fetcher(
        url: str,
        params: Mapping[str, QueryValue],
    ) -> object:
        calls.append((url, params))
        if url == CHEAPSHARK_DEALS_URL:
            return [
                {
                    "dealID": "cheap-1",
                    "title": "Steam Deep Deal",
                    "storeID": "1",
                    "salePrice": "4.99",
                    "normalPrice": "49.99",
                    "savings": "90.00",
                    "thumb": "https://example.com/steam.jpg",
                },
            ]

        if url == ITAD_DEALS_URL and params.get("sort") == "-cut":
            return {
                "list": [
                    {
                        "id": "itad-1",
                        "title": "Historical Hit",
                        "assets": {"banner300": "https://example.com/hit.jpg"},
                        "deal": {
                            "shop": {"name": "Steam"},
                            "price": {"amount": 10.0, "currency": "BRL"},
                            "regular": {"amount": 100.0, "currency": "BRL"},
                            "cut": 90,
                            "historyLow": {"amount": 10.0, "currency": "BRL"},
                            "url": "https://itad.link/hit",
                        },
                    },
                ],
            }

        return {
            "list": [
                {
                    "id": "epic-1",
                    "title": "Epic Free Week",
                    "assets": {"boxart": "https://example.com/epic.jpg"},
                    "deal": {
                        "shop": {"name": "Epic Games Store"},
                        "price": {"amount": 0.0, "currency": "BRL"},
                        "regular": {"amount": 49.99, "currency": "BRL"},
                        "cut": 100,
                        "historyLow": {"amount": 0.0, "currency": "BRL"},
                        "url": "https://itad.link/epic",
                    },
                },
            ],
        }

    service = GameDealsService(itad_api_key="test-key", fetcher=fake_fetcher)

    summary = asyncio.run(service.fetch_promos())
    automatic_deals = service.select_automatic_deals(summary)

    assert [deal.title for deal in summary.free_epic] == ["Epic Free Week"]
    assert {deal.source for deal in summary.best_deals} == {"itad"}
    assert any(deal.historical_low for deal in summary.best_deals)
    assert [call[0] for call in calls].count(ITAD_DEALS_URL) == 2
    assert [call[0] for call in calls].count(CHEAPSHARK_DEALS_URL) == 1
    assert {deal.title for deal in automatic_deals} == {
        "Epic Free Week",
        "Historical Hit",
    }
    itad_best_call = next(
        params for _url, params in calls if params.get("sort") == "-cut"
    )
    epic_free_call = next(
        params for _url, params in calls if params.get("sort") == "price"
    )
    assert itad_best_call["country"] == "BR"
    assert itad_best_call["shops"] == BR_STEAM_EPIC_SHOPS
    assert epic_free_call["shops"] == str(EPIC_ITAD_SHOP_ID)


def test_game_deals_service_falls_back_when_one_api_fails() -> None:
    """Ensure one failing source does not block promotions from the other."""

    async def fake_fetcher(
        url: str,
        params: Mapping[str, QueryValue],
    ) -> object:
        if url == CHEAPSHARK_DEALS_URL:
            raise RuntimeError("cheapshark unavailable")

        return {
            "list": [
                {
                    "id": "itad-1",
                    "title": "ITAD Deal",
                    "deal": {
                        "shop": {"name": "Steam"},
                        "price": {"amount": 20.0, "currency": "BRL"},
                        "regular": {"amount": 80.0, "currency": "BRL"},
                        "cut": 75,
                        "historyLow": {"amount": 15.0, "currency": "BRL"},
                        "url": "https://itad.link/deal",
                    },
                },
            ],
        }

    service = GameDealsService(itad_api_key="test-key", fetcher=fake_fetcher)

    summary = asyncio.run(service.fetch_promos())

    assert summary.partial_failures == ["cheapshark"]
    assert [deal.title for deal in summary.best_deals] == ["ITAD Deal"]


def test_game_deals_service_reports_missing_itad_key() -> None:
    """Ensure missing ITAD config is explicit instead of silently empty."""

    async def fake_fetcher(
        url: str,
        params: Mapping[str, QueryValue],
    ) -> object:
        assert url == CHEAPSHARK_DEALS_URL
        return []

    service = GameDealsService(itad_api_key="", fetcher=fake_fetcher)

    summary = asyncio.run(service.fetch_promos())

    assert summary.partial_failures == [ITAD_CONFIG_MISSING_FAILURE]
    assert summary.has_deals is False


def test_game_deals_cache_prevents_duplicates_and_limits_daily_posts(
    tmp_path: Path,
) -> None:
    """Ensure automatic posts do not duplicate deals or exceed day cadence."""

    current_time = datetime(2026, 4, 1, tzinfo=UTC)
    cache = GameDealsCache(
        tmp_path / "games_promo_cache.json",
        clock=lambda: current_time,
    )
    deal = _deal("Cache Test")

    assert asyncio.run(cache.filter_unposted([deal])) == [deal]
    assert asyncio.run(cache.can_post_today()) is True

    asyncio.run(cache.mark_posted([deal]))

    assert asyncio.run(cache.filter_unposted([deal])) == []
    assert asyncio.run(cache.can_post_today()) is False

    current_time += timedelta(days=1)
    assert asyncio.run(cache.can_post_today()) is False

    current_time += timedelta(days=1)
    assert asyncio.run(cache.can_post_today()) is False

    current_time += timedelta(days=1)
    assert asyncio.run(cache.can_post_today()) is True

    asyncio.run(cache.mark_posted([_deal("Cache Test 2")]))
    assert asyncio.run(cache.can_post_today()) is False


def _deal(title: str) -> GameDeal:
    return GameDeal(
        source="test",
        external_id=title,
        title=title,
        store="Steam",
        current_price=Decimal("1.00"),
        original_price=Decimal("10.00"),
        discount_percent=90,
        currency="BRL",
        url="https://example.com/deal",
    )
