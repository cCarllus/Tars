"""Smoke tests for project bootstrap behavior."""

from pytest import MonkeyPatch


def test_discover_cogs_loads_expected_modules(monkeypatch: MonkeyPatch) -> None:
    """Ensure the bot can discover the current cog modules."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.main import discover_cogs

    cogs = set(discover_cogs())

    assert "bot.cogs.admin.clear" in cogs
    assert "bot.cogs.ai.tars" in cogs
    assert "bot.cogs.music.player" in cogs
    assert "bot.cogs.schedule.agenda" in cogs


def test_settings_default_command_prefix(monkeypatch: MonkeyPatch) -> None:
    """Ensure settings keep the documented default command prefix."""

    monkeypatch.setenv("DISCORD_TOKEN", "test-token")

    from bot.config import get_settings

    get_settings.cache_clear()
    loaded_settings = get_settings()

    assert loaded_settings.command_prefix == "$"
