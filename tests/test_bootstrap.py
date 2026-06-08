"""Smoke tests for project bootstrap behavior."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import discord
import pytest
from pytest import MonkeyPatch


def test_discover_cogs_starts_empty(monkeypatch: MonkeyPatch) -> None:
    """Ensure the bot discovers the configured cog modules."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.main import discover_cogs

    cogs = discover_cogs()

    assert cogs == [
        "bot.cogs.core.audit_log",
        "bot.cogs.core.auto_mod",
        "bot.cogs.core.welcome_leave",
        "bot.cogs.games.promo_tracker",
        "bot.cogs.levels.levels_cog",
        "bot.cogs.tickets.ticket_cog",
        "bot.cogs.voice.private_voice_calls",
    ]


def test_settings_default_command_prefix(monkeypatch: MonkeyPatch) -> None:
    """Ensure settings keep the documented default command prefix."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.config import get_settings

    get_settings.cache_clear()
    loaded_settings = get_settings()

    assert loaded_settings.command_prefix == "/"


def test_settings_default_global_command_channel(monkeypatch: MonkeyPatch) -> None:
    """Ensure settings keep the documented global command channel."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.config import get_settings

    get_settings.cache_clear()
    loaded_settings = get_settings()

    assert loaded_settings.global_command_channel_id == 1498085284410298590


def test_settings_default_private_voice_hub(monkeypatch: MonkeyPatch) -> None:
    """Ensure settings keep the documented private voice hub channel."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.config import get_settings

    get_settings.cache_clear()
    loaded_settings = get_settings()

    assert loaded_settings.private_voice_hub_id == 1498213727932256308


def test_settings_default_promo_channel(monkeypatch: MonkeyPatch) -> None:
    """Ensure settings keep the documented promotions channel."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.config import get_settings

    get_settings.cache_clear()
    loaded_settings = get_settings()

    assert loaded_settings.promo_channel_id == 1498085291506794549


def test_private_voice_manager_builds_specified_call_name(
    monkeypatch: MonkeyPatch,
) -> None:
    """Ensure temporary calls use the name format required by the spec."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.utils.private_voice_manager import PrivateVoiceManager

    manager = PrivateVoiceManager(hub_channel_id=1498213727932256308)
    member = cast(discord.Member, SimpleNamespace(display_name="Ana   Maria"))

    assert manager.build_private_call_name(member) == "Call Privada - Ana Maria"


def test_private_voice_manager_validates_user_limit(monkeypatch: MonkeyPatch) -> None:
    """Ensure user limits match Discord voice channel bounds."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.utils.private_voice_manager import PrivateVoiceManager

    manager = PrivateVoiceManager(hub_channel_id=1498213727932256308)

    assert manager.validate_user_limit("0") == 0
    assert manager.validate_user_limit("99") == 99
    with pytest.raises(ValueError, match="entre 0 e 99"):
        manager.validate_user_limit("100")


def test_rate_limiter_rejects_excessive_action(monkeypatch: MonkeyPatch) -> None:
    """Ensure action buckets reject requests after the configured limit."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.utils.rate_limiter import RateLimiter, RateLimitRule

    limiter = RateLimiter(
        action_rules={
            "test_action": {
                "global": RateLimitRule(limit=1, window_seconds=60),
            },
        },
    )

    first_result = asyncio.run(limiter.check(action="test_action"))
    second_result = asyncio.run(limiter.check(action="test_action"))

    assert first_result.allowed is True
    assert second_result.allowed is False
    assert second_result.scope == "global:0"


def test_rate_limiter_can_reset_one_bucket(monkeypatch: MonkeyPatch) -> None:
    """Ensure lifecycle cleanup can release a user's creation cooldown."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.utils.rate_limiter import RateLimiter, RateLimitRule

    limiter = RateLimiter(
        action_rules={
            "test_action": {
                "global": RateLimitRule(limit=10, window_seconds=60),
                "user": RateLimitRule(limit=1, window_seconds=60),
            },
        },
    )

    first_result = asyncio.run(limiter.check(action="test_action", user_id=123))
    blocked_result = asyncio.run(limiter.check(action="test_action", user_id=123))
    asyncio.run(
        limiter.reset(action="test_action", scope="user", identifier=123),
    )
    released_result = asyncio.run(limiter.check(action="test_action", user_id=123))

    assert first_result.allowed is True
    assert blocked_result.allowed is False
    assert blocked_result.scope == "user:123"
    assert released_result.allowed is True


def test_sqlite_database_persists_voice_sessions(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Ensure active voice sessions are persisted and removable."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.utils.database import SQLiteDatabase

    database_path = tmp_path / "tars.sqlite3"
    db = SQLiteDatabase(database_path)

    asyncio.run(
        db.upsert_voice_session(
            guild_id=123,
            owner_id=456,
            channel_id=789,
        ),
    )
    sessions = asyncio.run(db.list_voice_sessions())

    assert len(sessions) == 1
    assert sessions[0].guild_id == 123
    assert sessions[0].owner_id == 456
    assert sessions[0].channel_id == 789

    asyncio.run(db.delete_voice_session_by_channel(789))

    assert asyncio.run(db.list_voice_sessions()) == []


def test_private_voice_manager_skips_duplicate_delete(
    monkeypatch: MonkeyPatch,
) -> None:
    """Ensure concurrent delete requests for the same call are idempotent."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.utils import private_voice_manager
    from bot.utils.database import SQLiteDatabase
    from bot.utils.private_voice_manager import PrivateVoiceManager

    class FakeDatabase:
        def __init__(self) -> None:
            self.deleted_channels: list[int] = []
            self.actions: list[dict[str, object]] = []

        async def initialize(self) -> None:
            return None

        async def delete_voice_session_by_channel(self, channel_id: int) -> None:
            self.deleted_channels.append(channel_id)

        async def log_action(self, **kwargs: object) -> None:
            self.actions.append(kwargs)

    class FakeQueue:
        def __init__(self) -> None:
            self.submitted_actions: list[str] = []

        async def submit(
            self,
            *,
            action: str,
            operation: Callable[[], Awaitable[bool]],
        ) -> bool:
            self.submitted_actions.append(action)
            return await operation()

    async def safe_delete_channel(_channel: object, *, reason: str) -> bool:
        await asyncio.sleep(0.01)
        return True

    fake_database = FakeDatabase()
    fake_queue = FakeQueue()
    monkeypatch.setattr(private_voice_manager, "discord_api_queue", fake_queue)
    monkeypatch.setattr(
        private_voice_manager,
        "safe_delete_channel",
        safe_delete_channel,
    )

    manager = PrivateVoiceManager(
        hub_channel_id=1498213727932256308,
        db=cast(SQLiteDatabase, fake_database),
    )
    guild = SimpleNamespace(id=123)
    channel = cast(discord.VoiceChannel, SimpleNamespace(id=789, guild=guild))
    guild.get_channel = lambda channel_id: channel if channel_id == channel.id else None
    manager._register_call(guild_id=guild.id, owner_id=456, channel_id=channel.id)

    async def run_deletes() -> list[bool]:
        return list(
            await asyncio.gather(
                manager.delete_call(channel=channel, reason="teste"),
                manager.delete_call(channel=channel, reason="teste duplicado"),
            ),
        )

    results = asyncio.run(run_deletes())

    assert sorted(results) == [False, True]
    assert fake_queue.submitted_actions == ["delete_private_voice_call"]
    assert fake_database.deleted_channels == [channel.id]
    assert not manager.is_private_call(channel.id)
