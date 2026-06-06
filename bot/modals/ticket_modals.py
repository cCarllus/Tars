"""Discord modals for ticket workflows."""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

import discord

from bot.modals.proof_modal import TicketProofModal
from bot.utils.embed import error_embed

USER_ID_PATTERN = re.compile(r"\d{15,25}")
__all__ = ["TicketParticipantModal", "TicketProofModal"]


@runtime_checkable
class TicketParticipantHandler(Protocol):
    """Cog methods required by participant modals."""

    async def handle_add_ticket_participant(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
        user_id: int,
    ) -> None:
        """Add a user to a ticket."""

    async def handle_remove_ticket_participant(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
        user_id: int,
    ) -> None:
        """Remove a user from a ticket."""


class TicketParticipantModal(discord.ui.Modal):
    """Collect a Discord user ID or mention for participant changes."""

    user_reference = discord.ui.TextInput[discord.ui.Modal](
        label="ID ou menção do usuário",
        min_length=15,
        max_length=64,
        required=True,
    )

    def __init__(self, *, ticket_id: int, action: str) -> None:
        """Initialize the participant modal."""

        title = "Adicionar pessoa ao caso"
        if action == "remove":
            title = "Remover pessoa do caso"
        super().__init__(title=title)
        self.ticket_id = ticket_id
        self.action = action

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Dispatch the participant change to the ticket cog."""

        match = USER_ID_PATTERN.search(str(self.user_reference.value))
        if match is None:
            await interaction.response.send_message(
                embed=error_embed("Informe um ID ou menção válida do Discord."),
                ephemeral=True,
            )
            return

        handler = _participant_handler(interaction)
        if handler is None:
            await interaction.response.send_message(
                embed=error_embed("Sistema de tickets indisponível no momento."),
                ephemeral=True,
            )
            return

        user_id = int(match.group(0))
        if self.action == "remove":
            await handler.handle_remove_ticket_participant(
                interaction,
                self.ticket_id,
                user_id,
            )
            return

        await handler.handle_add_ticket_participant(
            interaction,
            self.ticket_id,
            user_id,
        )


def _participant_handler(
    interaction: discord.Interaction,
) -> TicketParticipantHandler | None:
    get_cog = getattr(interaction.client, "get_cog", None)
    handler = get_cog("TicketCog") if callable(get_cog) else None
    if isinstance(handler, TicketParticipantHandler):
        return handler
    return None
