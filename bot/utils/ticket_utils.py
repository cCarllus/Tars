"""Ticket presentation, transcript and anti-abuse helpers."""

from __future__ import annotations

from collections.abc import Sequence
from io import BytesIO

import discord

from bot.database.models.ticket_models import (
    TicketModel,
    TicketProofModel,
    TicketType,
)

REPORT_COLOR = discord.Color.red()
SUPPORT_COLOR = discord.Color.blue()
TRIBUNAL_COLOR = discord.Color.gold()
TICKET_DEFAULT_THUMBNAIL_URL = "https://cdn-icons-png.flaticon.com/512/4712/4712109.png"
TRANSCRIPT_MESSAGE_LIMIT = 1000


def create_ticket_embed(
    ticket: TicketModel,
    *,
    title: str,
    description: str | None = None,
    variant: TicketType | str | None = None,
    fields: Sequence[tuple[str, str, bool]] = (),
    proofs: Sequence[TicketProofModel] = (),
    thumbnail_url: str | None = TICKET_DEFAULT_THUMBNAIL_URL,
) -> discord.Embed:
    """Build the standard TARS ticket embed.

    Args:
        ticket: Ticket used to fill footer and default visual theme.
        title: Main embed title.
        description: Optional body text.
        variant: Visual theme. Ticket types use support/report colors and
            ``"tribunal"`` uses the Tribunal color.
        fields: Extra fields as ``(name, value, inline)`` tuples.
        proofs: Proofs rendered in the standard proof-history field.
        thumbnail_url: Optional thumbnail URL. Pass ``None`` to omit it.

    Returns:
        A configured Discord embed with ticket footer, timestamp and fields.
    """

    embed = discord.Embed(
        title=title,
        description=description,
        color=_ticket_color(ticket.ticket_type if variant is None else variant),
        timestamp=ticket.updated_at,
    )
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    embed.set_footer(text=f"TARS Tickets | Ticket #{ticket.id:04d}")

    base_fields = (
        ("Status", ticket.status.value, True),
        ("Tipo", _ticket_type_label(ticket.ticket_type), True),
        ("Criador", _creator_label(ticket), True),
    )
    for name, value, inline in (*base_fields, *fields):
        embed.add_field(name=name, value=_truncate_field(value), inline=inline)

    if proofs:
        embed.add_field(
            name="Histórico de provas",
            value=_truncate_field(render_proof_summary(proofs)),
            inline=False,
        )
    return embed


def create_transcript_file(
    *,
    ticket: TicketModel,
    transcript_text: str,
) -> discord.File:
    """Create a Discord file object for a ticket transcript."""

    buffer = BytesIO(transcript_text.encode("utf-8"))
    return discord.File(buffer, filename=f"ticket-{ticket.id:04d}-transcript.txt")


async def build_ticket_transcript(
    *,
    ticket: TicketModel,
    channel: discord.TextChannel,
    proofs: Sequence[TicketProofModel] = (),
) -> str:
    """Build a plain-text transcript from a private ticket channel.

    Args:
        ticket: Ticket associated with the channel.
        channel: Private text channel to read.
        proofs: Persisted proof records appended before message history.

    Returns:
        UTF-8 friendly plain-text transcript content.
    """

    lines = [
        f"TARS Ticket #{ticket.id:04d}",
        f"Tipo: {_ticket_type_label(ticket.ticket_type)}",
        f"Status: {ticket.status.value}",
        f"Criador: {ticket.creator_user_id}",
        f"Alvo: {ticket.target_user_id or 'Nenhum'}",
        f"Criado em: {ticket.created_at.isoformat()}",
        f"Fechado em: {ticket.closed_at.isoformat() if ticket.closed_at else 'N/A'}",
        f"Motivo de fechamento: {ticket.close_reason or 'N/A'}",
        "",
        "=== Provas Registradas ===",
        render_proof_summary(proofs) if proofs else "Nenhuma prova registrada.",
        "",
        "=== Historico do Canal ===",
    ]

    messages = [
        message
        async for message in channel.history(
            limit=TRANSCRIPT_MESSAGE_LIMIT,
            oldest_first=True,
        )
    ]
    for message in messages:
        timestamp = message.created_at.isoformat()
        author = f"{message.author} ({message.author.id})"
        content = message.content or "[sem texto]"
        lines.append(f"[{timestamp}] {author}: {content}")
        for attachment in message.attachments:
            lines.append(f"  Anexo: {attachment.url}")

    if not messages:
        lines.append("Nenhuma mensagem encontrada no canal.")

    return "\n".join(lines)


def render_proof_summary(proofs: Sequence[TicketProofModel], *, limit: int = 5) -> str:
    """Render a compact proof history for embeds and transcripts."""

    if not proofs:
        return "Nenhuma prova registrada."

    visible = proofs[-limit:]
    lines: list[str] = []
    for proof in visible:
        parts = [f"#{proof.id} por <@{proof.actor_user_id}>"]
        if proof.links:
            parts.append(f"{len(proof.links)} link(s)")
        if proof.attachment_urls:
            parts.append(f"{len(proof.attachment_urls)} anexo(s)")
        lines.append(f"- {' | '.join(parts)}: {proof.description}")

    hidden_count = len(proofs) - len(visible)
    if hidden_count > 0:
        lines.append(f"... e mais {hidden_count} registro(s).")
    return "\n".join(lines)


def ticket_rate_limit_message(limit: int, window_seconds: int) -> str:
    """Return a PT-BR description for the ticket creation limit."""

    hours = window_seconds / 3600
    if hours.is_integer():
        window_label = f"{int(hours)} hora(s)"
    else:
        window_label = f"{int(window_seconds / 60)} minuto(s)"
    return f"Limite: {limit} ticket(s) a cada {window_label}."


def _ticket_color(variant: TicketType | str) -> discord.Color:
    if variant == TicketType.REPORT or str(variant) == TicketType.REPORT.value:
        return REPORT_COLOR
    if variant == TicketType.SUPPORT or str(variant) == TicketType.SUPPORT.value:
        return SUPPORT_COLOR
    if str(variant) == "tribunal":
        return TRIBUNAL_COLOR
    return discord.Color.blue()


def _ticket_type_label(ticket_type: TicketType) -> str:
    return "Suporte" if ticket_type == TicketType.SUPPORT else "Denuncia"


def _creator_label(ticket: TicketModel) -> str:
    if ticket.anonymous_report:
        return "Anonimo"
    return f"<@{ticket.creator_user_id}>"


def _truncate_field(value: str, *, limit: int = 1024) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."
