"""Game deal aggregation using CheapShark and IsThereAnyDeal."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bot.logger import logger

CHEAPSHARK_DEALS_URL = "https://www.cheapshark.com/api/1.0/deals"
CHEAPSHARK_REDIRECT_URL = "https://www.cheapshark.com/redirect"
ITAD_DEALS_URL = "https://api.isthereanydeal.com/deals/v2"
DEFAULT_COUNTRY = "BR"
DEFAULT_TIMEOUT_SECONDS = 12
MIN_SIGNIFICANT_DISCOUNT_PERCENT = 75
MAX_BEST_DEALS = 8
STEAM_ITAD_SHOP_ID = 61
EPIC_ITAD_SHOP_ID = 16
BR_STEAM_EPIC_SHOPS = f"{STEAM_ITAD_SHOP_ID},{EPIC_ITAD_SHOP_ID}"
CHEAPSHARK_ALLOWED_STORE_IDS = {"1", "25"}
ITAD_CONFIG_MISSING_FAILURE = "itad_config_missing"

CHEAPSHARK_STORE_NAMES = {
    "1": "Steam",
    "7": "GOG",
    "11": "Humble Store",
    "15": "Fanatical",
    "23": "GameBillet",
    "24": "Voidu",
    "25": "Epic",
    "27": "Gamesplanet",
    "30": "IndieGala",
    "32": "AllYouPlay",
    "33": "DLGamer",
}

QueryValue = str | int | float | bool | Sequence[int]


class JsonFetcher(Protocol):
    """Async JSON fetcher used by the service."""

    async def __call__(self, url: str, params: Mapping[str, QueryValue]) -> object:
        """Return decoded JSON for the given URL and query params."""


@dataclass(frozen=True)
class GameDeal:
    """Normalized deal returned by any supported game promo API."""

    source: str
    external_id: str
    title: str
    store: str
    current_price: Decimal
    original_price: Decimal
    discount_percent: int
    currency: str
    url: str
    image_url: str | None = None
    expires_at: datetime | None = None
    historical_low: bool = False

    @property
    def is_free(self) -> bool:
        """Return whether the deal is currently free."""

        return self.current_price <= Decimal("0.01")

    @property
    def cache_key(self) -> str:
        """Return a stable key for duplicate suppression."""

        normalized_title = " ".join(self.title.casefold().split())
        normalized_store = " ".join(self.store.casefold().split())
        return f"{normalized_title}:{normalized_store}:{self.current_price}"


@dataclass(frozen=True)
class GamePromoSummary:
    """Combined promotion result ready for Discord presentation."""

    free_epic: list[GameDeal]
    best_deals: list[GameDeal]
    generated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    partial_failures: list[str] = field(default_factory=list)

    @property
    def has_deals(self) -> bool:
        """Return whether the summary contains any promotion."""

        return bool(self.free_epic or self.best_deals)


class GameDealsService:
    """Fetch and combine game promotions from CheapShark and ITAD."""

    def __init__(
        self,
        *,
        itad_api_key: str,
        itad_client_id: str = "",
        country: str = DEFAULT_COUNTRY,
        fetcher: JsonFetcher | None = None,
    ) -> None:
        """Initialize the deal aggregation service."""

        self._itad_api_key = itad_api_key
        self._itad_client_id = itad_client_id
        self._country = country
        self._fetcher = fetcher or self._fetch_json

    async def fetch_promos(self) -> GamePromoSummary:
        """Fetch and combine current Brazilian Steam and Epic promotions."""

        logger.info(
            "Fetching game promotions action=games_promo_fetch source=all",
            extra={"action": "games_promo_fetch", "source": "all"},
        )

        cheap_task = self._fetch_cheapshark_deals()
        itad_task = self._fetch_itad_best_deals()
        epic_task = self._fetch_itad_epic_free_games()
        results = await asyncio.gather(
            cheap_task,
            itad_task,
            epic_task,
            return_exceptions=True,
        )

        failures: list[str] = []
        cheap_deals = self._unwrap_deals_result(results[0], "cheapshark", failures)
        itad_deals = self._unwrap_deals_result(results[1], "itad", failures)
        free_epic = self._unwrap_deals_result(results[2], "itad_epic", failures)
        best_deals = self._select_best_deals(itad_deals, free_epic)

        logger.info(
            "Fetched game promotions action=games_promo_fetch success=True "
            "cheapshark_count=%s itad_count=%s epic_free_count=%s failures=%s",
            len(cheap_deals),
            len(itad_deals),
            len(free_epic),
            ",".join(failures) or "none",
            extra={
                "action": "games_promo_fetch",
                "success": True,
                "cheapshark_count": len(cheap_deals),
                "itad_count": len(itad_deals),
                "epic_free_count": len(free_epic),
                "failures": failures,
            },
        )

        return GamePromoSummary(
            free_epic=free_epic,
            best_deals=best_deals,
            partial_failures=failures,
        )

    def select_automatic_deals(self, summary: GamePromoSummary) -> list[GameDeal]:
        """Return deals relevant enough for automatic posting."""

        candidates = [
            *summary.free_epic,
            *[
                deal
                for deal in summary.best_deals
                if deal.discount_percent >= MIN_SIGNIFICANT_DISCOUNT_PERCENT
                or deal.historical_low
            ],
        ]
        return self._dedupe_deals(candidates)[:MAX_BEST_DEALS]

    async def _fetch_cheapshark_deals(self) -> list[GameDeal]:
        payload = await self._fetcher(
            CHEAPSHARK_DEALS_URL,
            {
                "sortBy": "Savings",
                "desc": 1,
                "pageSize": 12,
                "lowerPrice": 0,
            },
        )
        if not isinstance(payload, list):
            msg = "CheapShark returned an unexpected payload"
            raise GameDealsServiceError(msg)

        deals = [self._parse_cheapshark_deal(item) for item in payload]
        return [
            deal
            for deal in deals
            if deal is not None and deal.external_id and _is_steam_or_epic(deal.store)
        ]

    async def _fetch_itad_best_deals(self) -> list[GameDeal]:
        if not self._itad_api_key:
            logger.warning(
                "Skipping ITAD deals fetch because ITAD_API_KEY is not configured",
                extra={"action": "games_promo_fetch", "source": "itad"},
            )
            msg = "ITAD_API_KEY is required for Brazilian Steam and Epic deals"
            raise GameDealsConfigurationError(msg)

        payload = await self._fetcher(
            ITAD_DEALS_URL,
            {
                "key": self._itad_api_key,
                "country": self._country,
                "limit": 12,
                "sort": "-cut",
                "nondeals": "false",
                "shops": BR_STEAM_EPIC_SHOPS,
            },
        )
        return self._parse_itad_deals_payload(payload)

    async def _fetch_itad_epic_free_games(self) -> list[GameDeal]:
        if not self._itad_api_key:
            msg = "ITAD_API_KEY is required for Brazilian Epic free games"
            raise GameDealsConfigurationError(msg)

        payload = await self._fetcher(
            ITAD_DEALS_URL,
            {
                "key": self._itad_api_key,
                "country": self._country,
                "limit": 40,
                "sort": "price",
                "nondeals": "false",
                "shops": str(EPIC_ITAD_SHOP_ID),
            },
        )
        deals = self._parse_itad_deals_payload(payload)
        return [deal for deal in deals if deal.is_free and _is_epic_store(deal.store)]

    async def _fetch_json(
        self,
        url: str,
        params: Mapping[str, QueryValue],
    ) -> object:
        return await asyncio.to_thread(self._fetch_json_sync, url, params)

    def _fetch_json_sync(
        self,
        url: str,
        params: Mapping[str, QueryValue],
    ) -> object:
        query = urlencode(params, doseq=True)
        request = Request(
            f"{url}?{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": "TarsDiscordBot/1.0",
            },
        )
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))

    def _parse_cheapshark_deal(self, item: object) -> GameDeal | None:
        if not isinstance(item, dict):
            return None

        title = _string_value(item.get("title"))
        deal_id = _string_value(item.get("dealID"))
        if not title or not deal_id:
            return None

        sale_price = _decimal_value(item.get("salePrice"))
        normal_price = _decimal_value(item.get("normalPrice"))
        discount = _int_percent(item.get("savings"))
        store_id = _string_value(item.get("storeID"))

        store = CHEAPSHARK_STORE_NAMES.get(store_id, f"Loja {store_id}")
        if store_id not in CHEAPSHARK_ALLOWED_STORE_IDS:
            return None

        return GameDeal(
            source="cheapshark",
            external_id=deal_id,
            title=title,
            store=store,
            current_price=sale_price,
            original_price=normal_price,
            discount_percent=discount,
            currency="USD",
            url=f"{CHEAPSHARK_REDIRECT_URL}?dealID={deal_id}",
            image_url=_string_value(item.get("thumb")) or None,
        )

    def _parse_itad_deals_payload(self, payload: object) -> list[GameDeal]:
        if not isinstance(payload, dict) or not isinstance(payload.get("list"), list):
            msg = "ITAD returned an unexpected payload"
            raise GameDealsServiceError(msg)

        deals = [self._parse_itad_deal(item) for item in payload["list"]]
        return [deal for deal in deals if deal is not None]

    def _parse_itad_deal(self, item: object) -> GameDeal | None:
        if not isinstance(item, dict):
            return None

        deal = item.get("deal")
        if not isinstance(deal, dict):
            return None

        title = _string_value(item.get("title"))
        external_id = _string_value(item.get("id"))
        if not title or not external_id:
            return None

        price = _money_value(deal.get("price"))
        regular = _money_value(deal.get("regular"))
        history_low = _money_value(deal.get("historyLow"))
        shop = deal.get("shop")
        shop_name = _string_value(shop.get("name")) if isinstance(shop, dict) else ""
        assets = item.get("assets")
        image_url = ""
        if isinstance(assets, dict):
            image_url = (
                _string_value(assets.get("banner300"))
                or _string_value(assets.get("boxart"))
                or _string_value(assets.get("banner145"))
            )

        if not _is_steam_or_epic(shop_name):
            return None

        return GameDeal(
            source="itad",
            external_id=external_id,
            title=title,
            store=shop_name or "Loja",
            current_price=price.amount,
            original_price=regular.amount,
            discount_percent=_int_percent(deal.get("cut")),
            currency=price.currency or regular.currency or self._country,
            url=_string_value(deal.get("url")),
            image_url=image_url or None,
            expires_at=_datetime_value(deal.get("expiry")),
            historical_low=(
                history_low.amount > Decimal("0") and price.amount <= history_low.amount
            ),
        )

    def _unwrap_deals_result(
        self,
        result: object,
        source: str,
        failures: list[str],
    ) -> list[GameDeal]:
        if isinstance(result, Exception):
            failure = (
                ITAD_CONFIG_MISSING_FAILURE
                if isinstance(result, GameDealsConfigurationError)
                else source
            )
            if failure not in failures:
                failures.append(failure)
            logger.warning(
                "Game promo source failed action=games_promo_fetch source=%s "
                "error=%s",
                source,
                type(result).__name__,
                exc_info=result,
                extra={
                    "action": "games_promo_fetch",
                    "source": source,
                    "success": False,
                    "error": type(result).__name__,
                },
            )
            return []

        if not isinstance(result, list):
            failures.append(source)
            return []

        return result

    def _select_best_deals(
        self,
        deals: list[GameDeal],
        free_epic: list[GameDeal],
    ) -> list[GameDeal]:
        free_keys = {deal.cache_key for deal in free_epic}
        paid_deals = [deal for deal in deals if deal.cache_key not in free_keys]
        ranked = sorted(
            self._dedupe_deals(paid_deals),
            key=lambda deal: (
                deal.historical_low,
                deal.discount_percent,
                deal.original_price - deal.current_price,
            ),
            reverse=True,
        )
        return ranked[:MAX_BEST_DEALS]

    def _dedupe_deals(self, deals: list[GameDeal]) -> list[GameDeal]:
        selected: dict[str, GameDeal] = {}
        for deal in deals:
            current = selected.get(deal.cache_key)
            if current is None or self._is_better_deal(deal, current):
                selected[deal.cache_key] = deal
        return list(selected.values())

    def _is_better_deal(self, candidate: GameDeal, current: GameDeal) -> bool:
        return (
            candidate.historical_low,
            candidate.discount_percent,
            candidate.original_price - candidate.current_price,
        ) > (
            current.historical_low,
            current.discount_percent,
            current.original_price - current.current_price,
        )


class GameDealsServiceError(RuntimeError):
    """Raised when a promo source returns an invalid response."""


class GameDealsConfigurationError(GameDealsServiceError):
    """Raised when a required promo source configuration is missing."""


@dataclass(frozen=True)
class MoneyValue:
    """Normalized money value from API payloads."""

    amount: Decimal
    currency: str


def _money_value(value: object) -> MoneyValue:
    if not isinstance(value, dict):
        return MoneyValue(amount=Decimal("0"), currency="")

    return MoneyValue(
        amount=_decimal_value(value.get("amount")),
        currency=_string_value(value.get("currency")),
    )


def _string_value(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _decimal_value(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _int_percent(value: object) -> int:
    return int(_decimal_value(value).quantize(Decimal("1")))


def _datetime_value(value: object) -> datetime | None:
    text = _string_value(value)
    if not text:
        return None

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_steam_or_epic(store: str) -> bool:
    normalized = store.casefold()
    return "steam" in normalized or "epic" in normalized


def _is_epic_store(store: str) -> bool:
    return "epic" in store.casefold()
