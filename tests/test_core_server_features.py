"""Tests for the TARS core server feature."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from bot.database.models.core_models import (
    AutoModConfigModel,
    DashboardConfigModel,
    LogConfigModel,
    LogDetailLevel,
)
from bot.services.auto_mod_service import AutoModService
from bot.services.core_config_service import (
    CoreConfigService,
    DashboardAccessDeniedError,
)
from bot.services.leveling_service import LevelingService


def test_core_config_service_restricts_dashboard_updates(tmp_path: Path) -> None:
    """Ensure only the configured owner can mutate Dashboard config."""

    service = CoreConfigService(tmp_path / "tars.sqlite3")
    config = DashboardConfigModel(
        guild_id=123,
        owner_user_id=42,
        logs=LogConfigModel(channel_id=999, detail_level=LogDetailLevel.DETAILED),
    )

    with pytest.raises(DashboardAccessDeniedError):
        asyncio.run(service.save_config_from_dashboard(config, actor_user_id=7))

    asyncio.run(service.save_config_from_dashboard(config, actor_user_id=42))
    loaded = asyncio.run(service.get_config(123))
    audit_events = asyncio.run(service.list_dashboard_audit_events(guild_id=123))

    assert loaded.logs.channel_id == 999
    assert loaded.logs.detail_level == LogDetailLevel.DETAILED
    assert audit_events[0]["event_type"] == "dashboard_config_updated"
    assert audit_events[0]["detail_level"] == 3


def test_leveling_service_applies_message_cooldown_and_leaderboard(
    tmp_path: Path,
) -> None:
    """Ensure XP is persisted, rate-limited and rankable."""

    service = LevelingService(tmp_path / "tars.sqlite3")
    now = datetime.now(tz=timezone.utc)  # noqa: UP017

    first = asyncio.run(
        service.add_message_xp(guild_id=123, user_id=1, created_at=now),
    )
    second = asyncio.run(
        service.add_message_xp(
            guild_id=123,
            user_id=1,
            created_at=now + timedelta(seconds=10),
        ),
    )
    third = asyncio.run(
        service.add_message_xp(
            guild_id=123,
            user_id=1,
            created_at=now + timedelta(seconds=61),
        ),
    )
    asyncio.run(service.add_voice_xp(guild_id=123, user_id=2, voice_seconds=120))

    leaderboard = asyncio.run(service.get_leaderboard(guild_id=123))

    assert first is not None
    assert second is not None
    assert third is not None
    assert first.xp == 15
    assert second.xp == 15
    assert third.xp == 30
    assert [record.user_id for record in leaderboard] == [1, 2]


def test_auto_mod_evaluates_blocked_words_and_allows_links() -> None:
    """Ensure configured moderation rules are deterministic."""

    service = AutoModService()
    config = AutoModConfigModel(
        blocked_words=("spamword",),
        block_links=True,
        allowed_links=("example.com",),
    )

    blocked_word = service.evaluate_content("isso tem spamword aqui", config)
    allowed_link = service.evaluate_content("acesse https://example.com/a", config)
    unlisted_link = service.evaluate_content("acesse https://bad.test/a", config)

    assert blocked_word.should_delete is True
    assert blocked_word.reason == "palavra bloqueada"
    assert allowed_link.should_delete is False
    assert unlisted_link.should_delete is False
