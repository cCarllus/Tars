"""Reusable validation helpers for Discord command handlers."""

from __future__ import annotations

from bot.config import settings


def is_global_command_channel(channel_id: int | None) -> bool:
    """Return whether a channel is allowed to run generation commands.

    Args:
        channel_id: Discord channel identifier from an interaction or message.

    Returns:
        True when the channel matches the configured global command channel.
    """

    return channel_id == settings.global_command_channel_id


def global_command_channel_mention() -> str:
    """Return the configured global command channel as a Discord mention."""

    return f"<#{settings.global_command_channel_id}>"
