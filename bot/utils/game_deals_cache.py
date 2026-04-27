"""Persistent cache for automatic game promotion posts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from bot.services.game_deals_service import GameDeal

MAX_CACHE_KEYS = 1000
MAX_AUTOMATIC_POSTS_PER_ACTIVE_DAY = 1
AUTOMATIC_POST_COOLDOWN_DAYS = 2
RETAIN_DAILY_COUNT_DAYS = 30


@dataclass
class GameDealsCacheData:
    """Serialized cache data."""

    posted_deal_keys: list[str] = field(default_factory=list)
    daily_post_counts: dict[str, int] = field(default_factory=dict)
    last_automatic_post_date: str | None = None


class GameDealsCache:
    """JSON-backed cache for duplicate suppression and daily post limits."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the cache path."""

        self._path = Path(path)
        self._clock = clock or _utc_now
        self._lock = asyncio.Lock()

    async def filter_unposted(self, deals: list[GameDeal]) -> list[GameDeal]:
        """Return only deals that were not posted before."""

        async with self._lock:
            data = await self._load_data()
            posted = set(data.posted_deal_keys)
            return [deal for deal in deals if deal.cache_key not in posted]

    async def can_post_today(self) -> bool:
        """Return whether the automatic task can post in the current day."""

        async with self._lock:
            data = await self._load_data()
            today = self._today()
            if data.daily_post_counts.get(today.isoformat(), 0) >= (
                MAX_AUTOMATIC_POSTS_PER_ACTIVE_DAY
            ):
                return False

            last_post_date = _parse_date(data.last_automatic_post_date)
            if last_post_date is None:
                return True

            quiet_days = (today - last_post_date).days
            return quiet_days > AUTOMATIC_POST_COOLDOWN_DAYS

    async def mark_posted(self, deals: list[GameDeal]) -> None:
        """Mark deals as posted and increment today's automatic post count."""

        async with self._lock:
            data = await self._load_data()
            posted = [*data.posted_deal_keys, *[deal.cache_key for deal in deals]]
            data.posted_deal_keys = list(dict.fromkeys(posted))[-MAX_CACHE_KEYS:]

            today = self._today().isoformat()
            data.daily_post_counts = {
                day: count
                for day, count in data.daily_post_counts.items()
                if _is_recent_day(day, today=today)
            }
            data.daily_post_counts[today] = data.daily_post_counts.get(today, 0) + 1
            data.last_automatic_post_date = today

            await self._save_data(data)

    async def _load_data(self) -> GameDealsCacheData:
        return await asyncio.to_thread(self._load_data_sync)

    def _load_data_sync(self) -> GameDealsCacheData:
        if not self._path.exists():
            return GameDealsCacheData()

        try:
            raw_data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return GameDealsCacheData()

        if not isinstance(raw_data, dict):
            return GameDealsCacheData()

        posted = raw_data.get("posted_deal_keys", [])
        counts = raw_data.get("daily_post_counts", {})
        last_automatic_post_date = raw_data.get("last_automatic_post_date")
        parsed_counts = _daily_post_counts(counts)
        return GameDealsCacheData(
            posted_deal_keys=[
                str(value)
                for value in posted
                if isinstance(value, str) and value.strip()
            ],
            daily_post_counts=parsed_counts,
            last_automatic_post_date=_last_post_date(
                last_automatic_post_date,
                parsed_counts,
            ),
        )

    async def _save_data(self, data: GameDealsCacheData) -> None:
        await asyncio.to_thread(self._save_data_sync, data)

    def _save_data_sync(self, data: GameDealsCacheData) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "posted_deal_keys": data.posted_deal_keys,
            "daily_post_counts": data.daily_post_counts,
            "last_automatic_post_date": data.last_automatic_post_date,
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _today(self) -> date:
        return self._clock().astimezone(UTC).date()


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _dict_items(value: object) -> list[tuple[Any, Any]]:
    if not isinstance(value, dict):
        return []
    return list(value.items())


def _daily_post_counts(value: object) -> dict[str, int]:
    counts: dict[str, int] = {}
    for day, count in _dict_items(value):
        if not isinstance(day, str):
            continue

        try:
            counts[day] = int(count)
        except (TypeError, ValueError):
            continue

    return counts


def _last_post_date(value: object, counts: dict[str, int]) -> str | None:
    if isinstance(value, str) and _parse_date(value) is not None:
        return value

    posted_days = [day for day, count in counts.items() if count > 0]
    return max(posted_days, default=None)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None

    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _is_recent_day(day: str, *, today: str) -> bool:
    current_date = _parse_date(today)
    day_date = _parse_date(day)
    if current_date is None or day_date is None:
        return False

    return (current_date - day_date).days <= RETAIN_DAILY_COUNT_DAYS
