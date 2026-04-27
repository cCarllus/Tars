"""Helpers for consistent Discord embeds."""

import discord

ERROR_COLOR = discord.Color.red()
INFO_COLOR = discord.Color.blue()
SUCCESS_COLOR = discord.Color.green()
WARNING_COLOR = discord.Color.yellow()


def build_embed(
    title: str,
    description: str,
    color: discord.Color = INFO_COLOR,
) -> discord.Embed:
    """Build a standard embed.

    Args:
        title: Embed title.
        description: Embed description.
        color: Embed accent color.

    Returns:
        Configured Discord embed.
    """

    return discord.Embed(title=title, description=description, color=color)


def error_embed(description: str, title: str = "Erro") -> discord.Embed:
    """Build an error embed."""

    return build_embed(title=title, description=description, color=ERROR_COLOR)


def success_embed(description: str, title: str = "Sucesso") -> discord.Embed:
    """Build a success embed."""

    return build_embed(title=title, description=description, color=SUCCESS_COLOR)
