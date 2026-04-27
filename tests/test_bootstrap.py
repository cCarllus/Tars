"""Smoke tests for project bootstrap behavior."""

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

    assert cogs == ["bot.cogs.voice.private_voice_calls"]


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
