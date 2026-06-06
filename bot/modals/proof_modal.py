"""Modal for adding proof to tickets."""

from __future__ import annotations

from typing import cast

import discord

from bot.services.ticket_service import TicketService, ticket_service_singleton
from bot.utils.safe_discord import safe_send_message
from bot.utils.ticket_utils import create_ticket_embed


class TicketProofModal(discord.ui.Modal):
    """Collect a proof description and one-link-per-line references."""

    description = discord.ui.TextInput[discord.ui.Modal](
        label="Descrição da prova",
        style=discord.TextStyle.long,
        min_length=3,
        max_length=1200,
        required=True,
    )
    links = discord.ui.TextInput[discord.ui.Modal](
        label="Links (um por linha)",
        style=discord.TextStyle.long,
        min_length=0,
        max_length=1000,
        required=False,
        placeholder="https://exemplo.com/prova.png",
    )

    def __init__(
        self,
        *,
        ticket_id: int,
        service: TicketService | None = None,
    ) -> None:
        """Initialize the proof modal.

        Args:
            ticket_id: Ticket that will receive the proof record.
            service: Optional service override used by tests.
        """

        super().__init__(title=f"Adicionar provas ao Ticket #{ticket_id:04d}")
        self.ticket_id = ticket_id
        self.service = service or ticket_service_singleton

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Persist proof and post a visible summary in the ticket channel."""

        ticket = await self.service.get_ticket(self.ticket_id)
        if ticket is None:
            await interaction.response.send_message(
                "Ticket não encontrado.",
                ephemeral=True,
            )
            return

        proof_links = _split_links(str(self.links.value))
        proof = await self.service.add_proof(
            ticket_id=self.ticket_id,
            actor_user_id=interaction.user.id,
            description=str(self.description.value),
            links=proof_links,
        )
        proofs = await self.service.list_proofs(self.ticket_id)

        await interaction.response.send_message(
            "Provas adicionadas ao histórico do ticket.",
            ephemeral=True,
        )
        if interaction.channel is not None:
            await safe_send_message(
                cast(discord.abc.Messageable, interaction.channel),
                embed=create_ticket_embed(
                    ticket,
                    title=f"Provas adicionadas #{ticket.id:04d}",
                    description=proof.description,
                    fields=(
                        (
                            "Links",
                            "\n".join(proof.links) if proof.links else "Nenhum",
                            False,
                        ),
                    ),
                    proofs=proofs,
                ),
                reason="send_ticket_proof_summary",
            )


def _split_links(raw_links: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(line.strip() for line in raw_links.splitlines() if line.strip()),
    )
