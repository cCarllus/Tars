"""Smoke tests for project bootstrap behavior."""

from pytest import MonkeyPatch


def test_discover_cogs_starts_empty(monkeypatch: MonkeyPatch) -> None:
    """Ensure the bot starts without custom cog modules."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.main import discover_cogs

    cogs = discover_cogs()

    assert cogs == []


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
