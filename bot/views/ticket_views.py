"""Discord UI views for tickets and Tribunal voting."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import discord

from bot.database.models.ticket_models import TribunalVoteChoice
from bot.modals.ticket_modals import TicketProofModal
from bot.utils.embed import error_embed


@runtime_checkable
class TicketInteractionHandler(Protocol):
    """Cog methods required by ticket UI views."""

    async def handle_accept_ticket(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
    ) -> None:
        """Accept a ticket from triage."""

    async def handle_close_ticket(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
    ) -> None:
        """Close a ticket from a button."""

    async def handle_escalate_ticket(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
    ) -> None:
        """Escalate a ticket to Tribunal."""

    async def handle_open_conductor_panel(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
    ) -> None:
        """Open conductor-only ticket controls."""

    async def handle_select_tribunal_targets(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
        target_user_ids: tuple[int, ...],
    ) -> None:
        """Set Tribunal targets and open voting."""

    async def handle_tribunal_vote(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
        choice: TribunalVoteChoice,
    ) -> None:
        """Record a Tribunal vote."""

    async def handle_set_ticket_participants(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
        user_ids: tuple[int, ...],
    ) -> None:
        """Replace users in a ticket with the selected list."""


class TicketTriageView(discord.ui.View):
    """Buttons displayed in the staff triage channel."""

    def __init__(self, ticket_id: int) -> None:
        """Initialize the triage view."""

        super().__init__(timeout=None)
        self.ticket_id = ticket_id

    @discord.ui.button(
        label="Aceitar",
        style=discord.ButtonStyle.success,
        custom_id="tars_ticket_accept",
    )
    async def accept(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button[TicketTriageView],
    ) -> None:
        """Accept a ticket and create private channels."""

        handler = await _handler_or_error(interaction)
        if handler is not None:
            await handler.handle_accept_ticket(interaction, self.ticket_id)

    @discord.ui.button(
        label="Fechar",
        style=discord.ButtonStyle.danger,
        custom_id="tars_ticket_close_from_triage",
    )
    async def close(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button[TicketTriageView],
    ) -> None:
        """Close a ticket from triage."""

        handler = await _handler_or_error(interaction)
        if handler is not None:
            await handler.handle_close_ticket(interaction, self.ticket_id)


class TicketPrivateView(discord.ui.View):
    """Buttons displayed inside a private ticket channel."""

    def __init__(self, *, ticket_id: int) -> None:
        """Initialize the private ticket view."""

        super().__init__(timeout=None)
        self.ticket_id = ticket_id

    @discord.ui.button(
        label="Adicionar provas",
        style=discord.ButtonStyle.secondary,
        custom_id="tars_ticket_add_proof",
    )
    async def add_proof(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button[TicketPrivateView],
    ) -> None:
        """Open a modal to collect proof."""

        await interaction.response.send_modal(
            TicketProofModal(ticket_id=self.ticket_id),
        )

    @discord.ui.button(
        label="Painel do condutor",
        style=discord.ButtonStyle.primary,
        custom_id="tars_ticket_conductor_panel",
    )
    async def conductor_panel(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button[TicketPrivateView],
    ) -> None:
        """Open conductor-only controls inside the private channel."""

        handler = await _handler_or_error(interaction)
        if handler is not None:
            await handler.handle_open_conductor_panel(interaction, self.ticket_id)


class TicketAdminView(discord.ui.View):
    """Staff-only ticket controls displayed in the triage channel."""

    def __init__(self, *, ticket_id: int, can_escalate: bool) -> None:
        """Initialize the admin ticket view."""

        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        self.add_item(TicketParticipantSelect(ticket_id))
        if not can_escalate:
            self.remove_item(self.escalate)

    @discord.ui.button(
        label="Escalar para Tribunal",
        style=discord.ButtonStyle.primary,
        custom_id="tars_ticket_escalate",
    )
    async def escalate(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button[TicketAdminView],
    ) -> None:
        """Escalate a report to Tribunal voting."""

        handler = await _handler_or_error(interaction)
        if handler is not None:
            await handler.handle_escalate_ticket(interaction, self.ticket_id)

    @discord.ui.button(
        label="Encerrar Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="tars_ticket_close_private",
    )
    async def close(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button[TicketAdminView],
    ) -> None:
        """Close a ticket from its private channel."""

        handler = await _handler_or_error(interaction)
        if handler is not None:
            await handler.handle_close_ticket(interaction, self.ticket_id)


class TicketParticipantSelect(discord.ui.UserSelect["TicketAdminView"]):
    """Select server members that should be in the ticket."""

    def __init__(self, ticket_id: int) -> None:
        """Initialize the member selector."""

        self.ticket_id = ticket_id
        super().__init__(
            placeholder="Pessoas no caso",
            min_values=0,
            max_values=10,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Replace ticket participants with selected users."""

        handler = await _handler_or_error(interaction)
        if handler is None:
            return

        await handler.handle_set_ticket_participants(
            interaction,
            self.ticket_id,
            tuple(user.id for user in self.values),
        )


class TribunalView(discord.ui.View):
    """Tribunal voting controls."""

    def __init__(self, ticket_id: int) -> None:
        """Initialize the Tribunal vote view."""

        super().__init__(timeout=None)
        self.add_item(TribunalVoteSelect(ticket_id))


class TribunalTargetView(discord.ui.View):
    """Staff-only selector for Tribunal action targets."""

    def __init__(self, ticket_id: int) -> None:
        """Initialize the target selector view."""

        super().__init__(timeout=180)
        self.add_item(TribunalTargetSelect(ticket_id))


class TribunalTargetSelect(discord.ui.UserSelect["TribunalTargetView"]):
    """Select users that can receive the Tribunal action."""

    def __init__(self, ticket_id: int) -> None:
        """Initialize the target select menu."""

        self.ticket_id = ticket_id
        super().__init__(
            placeholder="Selecione quem pode receber a ação",
            min_values=1,
            max_values=10,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Persist selected targets and open Tribunal voting."""

        handler = await _handler_or_error(interaction)
        if handler is None:
            return

        await handler.handle_select_tribunal_targets(
            interaction,
            self.ticket_id,
            tuple(user.id for user in self.values),
        )


class TribunalVoteSelect(discord.ui.Select["TribunalView"]):
    """Select menu with Tribunal decision options."""

    def __init__(self, ticket_id: int) -> None:
        """Initialize the vote select menu."""

        self.ticket_id = ticket_id
        super().__init__(
            placeholder="Registrar voto do Tribunal",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(
                    label="Absolver",
                    value=TribunalVoteChoice.ABSOLVE,
                ),
                discord.SelectOption(label="Timeout", value=TribunalVoteChoice.TIMEOUT),
                discord.SelectOption(label="Kick", value=TribunalVoteChoice.KICK),
                discord.SelectOption(
                    label="Ban temporário",
                    value=TribunalVoteChoice.TEMP_BAN,
                ),
                discord.SelectOption(
                    label="Ban permanente",
                    value=TribunalVoteChoice.PERM_BAN,
                ),
                discord.SelectOption(label="Outros", value=TribunalVoteChoice.OTHER),
            ],
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        """Persist the selected Tribunal vote."""

        handler = await _handler_or_error(interaction)
        if handler is None:
            return
        await handler.handle_tribunal_vote(
            interaction,
            self.ticket_id,
            TribunalVoteChoice(self.values[0]),
        )


async def _handler_or_error(
    interaction: discord.Interaction,
) -> TicketInteractionHandler | None:
    get_cog = getattr(interaction.client, "get_cog", None)
    handler = get_cog("TicketCog") if callable(get_cog) else None
    if isinstance(handler, TicketInteractionHandler):
        return handler

    await interaction.response.send_message(
        embed=error_embed("Sistema de tickets indisponível no momento."),
        ephemeral=True,
    )
    return None
