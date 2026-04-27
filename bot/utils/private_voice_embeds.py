"""Embeds used by the private voice call feature."""

from __future__ import annotations

import discord

PRIVATE_CALL_EMBED_COLOR = discord.Color(0x5865F2)
PRIVATE_CALL_CONTROL_TITLE = "⚙️ Configuração da Call Privada"


def build_private_voice_control_embed(
    *,
    owner: discord.Member,
    channel: discord.VoiceChannel,
) -> discord.Embed:
    """Build the owner control embed for a private voice channel.

    Args:
        owner: Member that owns the temporary call.
        channel: Temporary voice channel.

    Returns:
        Configured Discord embed for the private call controls.
    """

    embed = discord.Embed(
        title=PRIVATE_CALL_CONTROL_TITLE,
        description=(
            f"Dono: {owner.mention}\n"
            f"Canal: {channel.mention}\n\n"
            "Use os botões abaixo para configurar sua call privada."
        ),
        color=PRIVATE_CALL_EMBED_COLOR,
    )
    embed.set_footer(text="A call será deletada automaticamente quando ficar vazia.")
    return embed


def build_private_voice_invite_embed(
    *,
    owner: discord.Member,
    channel: discord.VoiceChannel,
) -> discord.Embed:
    """Build the direct-message invite embed for a private call."""

    return discord.Embed(
        title="Convite para call privada",
        description=(
            f"{owner.mention} convidou você para entrar na call " f"**{channel.name}**."
        ),
        color=PRIVATE_CALL_EMBED_COLOR,
    )
