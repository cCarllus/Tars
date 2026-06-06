"""Discord modals for ticket workflows."""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

import discord

from bot.services.ticket_service import TicketService, ticket_service_singleton
from bot.utils.embed import error_embed, success_embed

USER_ID_PATTERN = re.compile(r"\d{15,25}")


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


class TicketProofModal(discord.ui.Modal):
    """Collect proof or extra context for a ticket."""

    proof = discord.ui.TextInput[discord.ui.Modal](
        label="Provas ou contexto",
        style=discord.TextStyle.long,
        min_length=3,
        max_length=1500,
        required=True,
    )

    def __init__(
        self,
        *,
        ticket_id: int,
        service: TicketService | None = None,
    ) -> None:
        """Initialize the proof modal."""

        super().__init__(title=f"Adicionar provas ao Ticket #{ticket_id:04d}")
        self.ticket_id = ticket_id
        self.service = service or ticket_service_singleton

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Persist the submitted proof and acknowledge the user."""

        await self.service.add_proof(
            ticket_id=self.ticket_id,
            actor_user_id=interaction.user.id,
            proof=str(self.proof.value),
        )
        await interaction.response.send_message(
            embed=success_embed("Provas adicionadas ao histórico do ticket."),
            ephemeral=True,
        )


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
