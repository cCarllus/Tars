"""Persistent cache for automatic game promotion posts."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bot.services.game_deals_service import GameDeal

MAX_CACHE_KEYS = 1000
MAX_AUTOMATIC_POSTS_PER_DAY = 4


@dataclass
class GameDealsCacheData:
    """Serialized cache data."""

    posted_deal_keys: list[str] = field(default_factory=list)
    daily_post_counts: dict[str, int] = field(default_factory=dict)


class GameDealsCache:
    """JSON-backed cache for duplicate suppression and daily post limits."""

    def __init__(self, path: str | Path) -> None:
        """Initialize the cache path."""

        self._path = Path(path)
        self._lock = asyncio.Lock()

    async def filter_unposted(self, deals: list[GameDeal]) -> list[GameDeal]:
        """Return only deals that were not posted before."""

        async with self._lock:
            data = await self._load_data()
            posted = set(data.posted_deal_keys)
            return [deal for deal in deals if deal.cache_key not in posted]

    async def can_post_today(self) -> bool:
        """Return whether the automatic task can post again today."""

        async with self._lock:
            data = await self._load_data()
            return (
                data.daily_post_counts.get(_today_key(), 0)
                < MAX_AUTOMATIC_POSTS_PER_DAY
            )

    async def mark_posted(self, deals: list[GameDeal]) -> None:
        """Mark deals as posted and increment today's automatic post count."""

        async with self._lock:
            data = await self._load_data()
            posted = [*data.posted_deal_keys, *[deal.cache_key for deal in deals]]
            data.posted_deal_keys = list(dict.fromkeys(posted))[-MAX_CACHE_KEYS:]

            today = _today_key()
            data.daily_post_counts = {
                day: count
                for day, count in data.daily_post_counts.items()
                if day >= today
            }
            data.daily_post_counts[today] = data.daily_post_counts.get(today, 0) + 1

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
        return GameDealsCacheData(
            posted_deal_keys=[
                str(value)
                for value in posted
                if isinstance(value, str) and value.strip()
            ],
            daily_post_counts=_daily_post_counts(counts),
        )

    async def _save_data(self, data: GameDealsCacheData) -> None:
        await asyncio.to_thread(self._save_data_sync, data)

    def _save_data_sync(self, data: GameDealsCacheData) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "posted_deal_keys": data.posted_deal_keys,
            "daily_post_counts": data.daily_post_counts,
        }
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _today_key() -> str:
    return datetime.now(tz=UTC).date().isoformat()


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
