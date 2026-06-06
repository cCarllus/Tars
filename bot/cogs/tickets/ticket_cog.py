"""Ticket and Tribunal slash commands."""

from __future__ import annotations

import asyncio
import re
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.database.models.core_models import TicketConfigModel
from bot.database.models.ticket_models import (
    TicketModel,
    TicketType,
    TribunalVoteChoice,
)
from bot.logger import logger
from bot.services.audit_log_service import audit_log_service
from bot.services.core_config_service import CoreConfigService, core_config_service
from bot.services.ticket_service import (
    TicketService,
    TicketStateError,
    TribunalService,
    ticket_service_singleton,
    tribunal_service_singleton,
)
from bot.utils.embed import ERROR_COLOR, INFO_COLOR, SUCCESS_COLOR, build_embed
from bot.utils.rate_limiter import RateLimiter, RateLimitRule, rate_limiter
from bot.utils.safe_discord import (
    safe_create_category,
    safe_create_text_channel,
    safe_create_voice_channel,
    safe_delete_channel,
    safe_delete_message,
    safe_edit_channel_permissions,
    safe_send_message,
)
from bot.views.ticket_views import (
    TicketAdminView,
    TicketPrivateView,
    TicketTriageView,
    TribunalTargetView,
    TribunalView,
)

TICKET_CREATION_ACTION = "ticket_creation"
PRIVATE_CHANNEL_REASON = "Gerenciar ticket TARS"
TRIBUNAL_TIMEOUT_HOURS = 24
TRIBUNAL_TEMP_BAN_HOURS = 24


class TicketCog(commands.Cog, name="TicketCog"):
    """Open, triage and judge support/report tickets."""

    tribunal = app_commands.Group(
        name="tribunal",
        description="Comandos manuais do Tribunal.",
        default_permissions=discord.Permissions(manage_messages=True),
    )

    def __init__(
        self,
        bot: commands.Bot,
        *,
        ticket_service: TicketService | None = None,
        tribunal_service: TribunalService | None = None,
        config_service: CoreConfigService | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        """Initialize the ticket cog."""

        self.bot = bot
        self.ticket_service = ticket_service or ticket_service_singleton
        self.tribunal_service = tribunal_service or tribunal_service_singleton
        self.config_service = config_service or core_config_service
        self.limiter = limiter or rate_limiter
        self.limiter.set_action_rules(
            TICKET_CREATION_ACTION,
            {
                "global": RateLimitRule(limit=80, window_seconds=60),
                "guild": RateLimitRule(limit=20, window_seconds=60),
                "user": RateLimitRule(limit=2, window_seconds=120),
            },
        )

    async def cog_load(self) -> None:
        """Start background ticket cleanup."""

        self.ticket_cleanup.start()

    async def cog_unload(self) -> None:
        """Stop background ticket cleanup."""

        self.ticket_cleanup.cancel()

    @app_commands.command(name="reportar", description="Abrir uma denúncia para staff.")
    @app_commands.describe(alvo="Usuário denunciado.", motivo="Motivo da denúncia.")
    @app_commands.guild_only()
    async def reportar(
        self,
        interaction: discord.Interaction,
        motivo: str,
        alvo: discord.Member | None = None,
    ) -> None:
        """Open a report ticket."""

        await self._submit_ticket(
            interaction=interaction,
            ticket_type=TicketType.REPORT,
            description=motivo,
            target=alvo,
        )

    @app_commands.command(name="suporte", description="Abrir um ticket de suporte.")
    @app_commands.describe(descricao="Descreva o problema ou pedido de suporte.")
    @app_commands.guild_only()
    async def suporte(
        self,
        interaction: discord.Interaction,
        descricao: str,
    ) -> None:
        """Open a support ticket."""

        await self._submit_ticket(
            interaction=interaction,
            ticket_type=TicketType.SUPPORT,
            description=descricao,
            target=None,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Remove private-ticket messages from users outside the case."""

        if message.guild is None or message.author.bot:
            return

        ticket = await self.ticket_service.get_ticket_by_private_channel(
            message.channel.id,
        )
        if ticket is None:
            return

        participant_ids = await self.ticket_service.list_participant_user_ids(ticket.id)
        if message.author.id in participant_ids:
            return

        await safe_delete_message(
            message,
            reason="Remover mensagem de usuário fora do caso do ticket",
        )

    @tribunal.command(name="abrir", description="Abrir um caso manual no Tribunal.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.describe(motivo="Resumo do caso manual.", alvo="Usuário envolvido.")
    @app_commands.guild_only()
    async def tribunal_abrir(
        self,
        interaction: discord.Interaction,
        motivo: str,
        alvo: discord.Member | None = None,
    ) -> None:
        """Open a manual Tribunal case."""

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                embed=build_embed(
                    "Servidor obrigatório",
                    "Esse comando só funciona dentro de um servidor.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        config = (await self.config_service.get_config(guild.id)).tickets
        if not self._member_can_manage_ticket(interaction.user, config):
            await interaction.response.send_message(
                embed=build_embed(
                    "Sem permissão",
                    "Apenas staff configurada na Dashboard pode abrir Tribunal manual.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket = await self.ticket_service.create_ticket(
            guild_id=guild.id,
            ticket_type=TicketType.REPORT,
            creator_user_id=interaction.user.id,
            description=motivo,
            target_user_id=alvo.id if alvo else None,
            anonymous_report=False,
            expiration_hours=config.ticket_expiration_hours,
            archive_after_hours=config.archive_after_hours,
        )
        accepted = await self.ticket_service.accept_ticket(
            ticket_id=ticket.id,
            staff_user_id=interaction.user.id,
        )
        tribunal_ticket = await self.ticket_service.escalate_to_tribunal(
            ticket_id=accepted.id,
            actor_user_id=interaction.user.id,
        )
        if alvo is not None:
            await self.ticket_service.set_tribunal_targets(
                ticket_id=tribunal_ticket.id,
                actor_user_id=interaction.user.id,
                target_user_ids=(alvo.id,),
            )
        await self._post_tribunal_vote(interaction, tribunal_ticket, config)
        await interaction.followup.send(
            embed=build_embed(
                "Tribunal aberto",
                f"Ticket #{tribunal_ticket.id:04d} enviado para votação.",
                SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    async def handle_accept_ticket(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
    ) -> None:
        """Accept a ticket and create private channels."""

        guild = interaction.guild
        if guild is None:
            return

        config = (await self.config_service.get_config(guild.id)).tickets
        if not self._member_can_manage_ticket(interaction.user, config):
            await interaction.response.send_message(
                embed=build_embed(
                    "Sem permissão",
                    "Apenas staff configurada pode aceitar tickets.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket = await self.ticket_service.accept_ticket(
            ticket_id=ticket_id,
            staff_user_id=interaction.user.id,
        )
        if ticket.private_text_channel_id is not None:
            await interaction.followup.send(
                embed=build_embed(
                    "Ticket já aceito",
                    f"O canal privado já existe: <#{ticket.private_text_channel_id}>.",
                    INFO_COLOR,
                ),
                ephemeral=True,
            )
            return

        try:
            channel_ticket = await self._create_private_ticket_channels(
                guild=guild,
                ticket=ticket,
                config=config,
            )
        except discord.HTTPException:
            logger.exception("Failed to create private ticket channels")
            await audit_log_service.send_owner_alert(
                guild=guild,
                title="Erro ao criar canal de ticket",
                description=(
                    f"O Ticket #{ticket.id:04d} foi aceito, mas o Discord "
                    "recusou a criação dos canais privados."
                ),
                color=ERROR_COLOR,
            )
            await interaction.followup.send(
                embed=build_embed(
                    "Erro ao criar canal",
                    "Não consegui criar os canais privados. O erro foi logado.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        await self._log_ticket_action(
            guild=guild,
            ticket=channel_ticket,
            event_type="ticket_accepted",
            title="Ticket aceito",
            description=f"Ticket #{channel_ticket.id:04d} aceito por staff.",
            actor_user_id=interaction.user.id,
        )
        await interaction.followup.send(
            embed=build_embed(
                "Ticket aceito",
                f"Canal privado criado: <#{channel_ticket.private_text_channel_id}>.",
                SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    async def handle_open_conductor_panel(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
    ) -> None:
        """Open conductor-only controls in the ticket channel."""

        ticket = await self.ticket_service.get_ticket(ticket_id)
        if ticket is None:
            await interaction.response.send_message(
                embed=build_embed(
                    "Ticket não encontrado",
                    "O ticket não existe.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        if not _user_is_ticket_conductor(interaction.user, ticket):
            await interaction.response.send_message(
                embed=build_embed(
                    "Apenas o condutor",
                    "Só quem aceitou e conduz este ticket pode abrir este painel.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        await self._send_ticket_admin_panel(interaction=interaction, ticket=ticket)

    async def handle_close_ticket(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
    ) -> None:
        """Close a ticket if the actor is configured staff."""

        guild = interaction.guild
        if guild is None:
            return

        config = (await self.config_service.get_config(guild.id)).tickets
        if not self._member_can_manage_ticket(interaction.user, config):
            await interaction.response.send_message(
                embed=build_embed(
                    "Sem permissão",
                    "Apenas staff configurada pode fechar tickets.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        existing_ticket = await self.ticket_service.get_ticket(ticket_id)
        if existing_ticket is None:
            await interaction.response.send_message(
                embed=build_embed(
                    "Ticket não encontrado",
                    "O ticket não existe.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return
        if existing_ticket.accepted_by_user_id is not None and not (
            _user_is_ticket_conductor(interaction.user, existing_ticket)
        ):
            await interaction.response.send_message(
                embed=build_embed(
                    "Apenas o condutor",
                    "Só quem aceitou e conduz este ticket pode encerrar o caso.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket = await self.ticket_service.close_ticket(
            ticket_id=ticket_id,
            actor_user_id=interaction.user.id,
            reason="Fechado manualmente pela staff.",
        )
        await self._log_ticket_action(
            guild=guild,
            ticket=ticket,
            event_type="ticket_closed",
            title="Ticket fechado",
            description=f"Ticket #{ticket.id:04d} fechado manualmente.",
            actor_user_id=interaction.user.id,
        )
        await interaction.followup.send(
            embed=build_embed(
                "Ticket fechado",
                "O ticket foi fechado e os canais privados serão removidos agora.",
                SUCCESS_COLOR,
            ),
            ephemeral=True,
        )
        await self._delete_ticket_private_channels(
            guild,
            ticket,
            reason="Fechamento imediato de ticket",
        )

    async def handle_add_ticket_participant(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
        user_id: int,
    ) -> None:
        """Add a user to a ticket private channel."""

        await self.handle_set_ticket_participants(interaction, ticket_id, (user_id,))

    async def handle_set_ticket_participants(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
        user_ids: tuple[int, ...],
    ) -> None:
        """Replace non-core participants with the selected users."""

        guild = interaction.guild
        if guild is None:
            return

        config = (await self.config_service.get_config(guild.id)).tickets
        if not self._member_can_manage_ticket(interaction.user, config):
            await interaction.response.send_message(
                embed=build_embed(
                    "Sem permissão",
                    "Apenas roles configuradas podem alterar pessoas no caso.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        ticket = await self.ticket_service.get_ticket(ticket_id)
        if ticket is None:
            await interaction.response.send_message(
                embed=build_embed(
                    "Ticket não encontrado",
                    "O ticket não existe.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        if not _user_is_ticket_conductor(interaction.user, ticket):
            await interaction.response.send_message(
                embed=build_embed(
                    "Apenas o condutor",
                    "Só quem aceitou e conduz este ticket pode alterar o caso.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        current_participant_ids = await self.ticket_service.list_participant_user_ids(
            ticket_id,
        )
        protected_ids = {
            ticket.creator_user_id,
            ticket.target_user_id,
            ticket.accepted_by_user_id,
        }
        protected_ids.discard(None)
        selected_ids = set(user_ids)
        removable_ids = current_participant_ids - protected_ids
        add_ids = selected_ids - current_participant_ids
        remove_ids = removable_ids - selected_ids

        added_mentions: list[str] = []
        missing_users: list[int] = []
        for user_id in sorted(add_ids):
            member = await _resolve_member(guild, user_id)
            if member is None:
                missing_users.append(user_id)
                continue

            await self.ticket_service.add_participant(
                ticket_id=ticket_id,
                actor_user_id=interaction.user.id,
                user_id=user_id,
            )
            await self._set_member_ticket_permissions(
                guild=guild,
                ticket=ticket,
                member=member,
                config=config,
                can_send=True,
            )
            added_mentions.append(member.mention)

        removed_mentions: list[str] = []
        skipped_messages: list[str] = []
        for user_id in sorted(remove_ids):
            member = await _resolve_member(guild, user_id)
            if member is None:
                skipped_messages.append(str(user_id))
                continue

            try:
                await self.ticket_service.remove_added_participant(
                    ticket_id=ticket_id,
                    actor_user_id=interaction.user.id,
                    user_id=user_id,
                )
            except TicketStateError:
                skipped_messages.append(member.mention)
                continue

            await self._set_member_ticket_permissions(
                guild=guild,
                ticket=ticket,
                member=member,
                config=config,
                can_send=False,
            )
            removed_mentions.append(member.mention)

        description_parts: list[str] = []
        if added_mentions:
            description_parts.append(f"Adicionados: {' '.join(added_mentions)}")
        if removed_mentions:
            description_parts.append(f"Removidos: {' '.join(removed_mentions)}")
        if not description_parts:
            description_parts.append("Pessoas no caso não foram alteradas.")
        if missing_users:
            missing_text = ", ".join(str(user_id) for user_id in missing_users)
            description_parts.append(
                f"Não encontrados: {missing_text}",
            )
        if skipped_messages:
            description_parts.append(f"Não removidos: {' '.join(skipped_messages)}")
        await interaction.response.send_message(
            embed=build_embed(
                "Pessoas no caso",
                "\n".join(description_parts),
                SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    async def handle_escalate_ticket(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
    ) -> None:
        """Open a staff-only target selector before Tribunal voting."""

        guild = interaction.guild
        if guild is None:
            return

        config = (await self.config_service.get_config(guild.id)).tickets
        if not self._member_can_manage_ticket(interaction.user, config):
            await interaction.response.send_message(
                embed=build_embed(
                    "Sem permissão",
                    "Apenas staff configurada pode escalar tickets.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        ticket = await self.ticket_service.get_ticket(ticket_id)
        if ticket is None:
            await interaction.response.send_message(
                embed=build_embed(
                    "Ticket não encontrado",
                    "O ticket não existe.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return
        if not _user_is_ticket_conductor(interaction.user, ticket):
            await interaction.response.send_message(
                embed=build_embed(
                    "Apenas o condutor",
                    "Só quem aceitou e conduz este ticket pode escalar o caso.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=build_embed(
                "Alvos do Tribunal",
                "Selecione quem pode receber a ação decidida pelo Tribunal.",
                INFO_COLOR,
            ),
            view=TribunalTargetView(ticket_id),
            ephemeral=True,
        )

    async def handle_select_tribunal_targets(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
        target_user_ids: tuple[int, ...],
    ) -> None:
        """Persist selected targets and open Tribunal voting."""

        guild = interaction.guild
        if guild is None:
            return

        config = (await self.config_service.get_config(guild.id)).tickets
        if not self._member_can_manage_ticket(interaction.user, config):
            await interaction.response.send_message(
                embed=build_embed(
                    "Sem permissão",
                    "Apenas staff configurada pode escalar tickets.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        ticket = await self.ticket_service.get_ticket(ticket_id)
        if ticket is None:
            await interaction.response.send_message(
                embed=build_embed(
                    "Ticket não encontrado",
                    "O ticket não existe.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return
        if not _user_is_ticket_conductor(interaction.user, ticket):
            await interaction.response.send_message(
                embed=build_embed(
                    "Apenas o condutor",
                    "Só quem aceitou e conduz este ticket pode escalar o caso.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.ticket_service.set_tribunal_targets(
                ticket_id=ticket_id,
                actor_user_id=interaction.user.id,
                target_user_ids=target_user_ids,
            )
            ticket = await self.ticket_service.escalate_to_tribunal(
                ticket_id=ticket_id,
                actor_user_id=interaction.user.id,
            )
        except TicketStateError as exc:
            await interaction.followup.send(
                embed=build_embed("Fluxo inválido", str(exc), ERROR_COLOR),
                ephemeral=True,
            )
            return

        await self._post_tribunal_vote(interaction, ticket, config)
        await interaction.followup.send(
            embed=build_embed(
                "Tribunal aberto",
                (
                    f"Ticket #{ticket.id:04d} enviado para votação com "
                    f"{len(target_user_ids)} alvo(s)."
                ),
                SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    async def handle_tribunal_vote(
        self,
        interaction: discord.Interaction,
        ticket_id: int,
        choice: TribunalVoteChoice,
    ) -> None:
        """Record a Tribunal vote and apply majority decisions."""

        guild = interaction.guild
        if guild is None:
            return

        config = (await self.config_service.get_config(guild.id)).tickets
        if not self._member_can_vote_tribunal(interaction.user, config):
            await interaction.response.send_message(
                embed=build_embed(
                    "Voto negado",
                    "Apenas Juiz ou Admin configurado pode votar no Tribunal.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        tally = await self.tribunal_service.cast_vote(
            ticket_id=ticket_id,
            voter_user_id=interaction.user.id,
            choice=choice,
            reason=None,
            majority_votes=config.tribunal_majority_votes,
        )

        ticket = await self.ticket_service.get_ticket(ticket_id)
        if ticket is None:
            await interaction.followup.send(
                embed=build_embed(
                    "Ticket não encontrado",
                    "O ticket não existe.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        if tally.decision_reached and tally.decision is not None:
            await self._apply_tribunal_decision(
                guild=guild,
                ticket=ticket,
                decision=tally.decision,
                actor_user_id=interaction.user.id,
            )
            message = f"Maioria alcançada: **{_decision_label(tally.decision)}**."
        else:
            rendered_counts = ", ".join(
                f"{_decision_label(decision)}: {count}"
                for decision, count in tally.counts.items()
            )
            message = rendered_counts or "Voto registrado."

        await interaction.followup.send(
            embed=build_embed("Voto registrado", message, SUCCESS_COLOR),
        )

    @tasks.loop(minutes=30)
    async def ticket_cleanup(self) -> None:
        """Auto-close expired tickets and delete archived private channels."""

        await self._close_expired_tickets()
        await self._delete_archive_ready_channels()

    @ticket_cleanup.before_loop
    async def before_ticket_cleanup(self) -> None:
        """Wait for Discord cache readiness before cleanup."""

        await self.bot.wait_until_ready()

    async def _submit_ticket(
        self,
        *,
        interaction: discord.Interaction,
        ticket_type: TicketType,
        description: str,
        target: discord.Member | None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                embed=build_embed(
                    "Servidor obrigatório",
                    "Esse comando só funciona dentro de um servidor.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        limit = await self.limiter.check(
            action=TICKET_CREATION_ACTION,
            user_id=interaction.user.id,
            guild_id=guild.id,
        )
        if not limit.allowed:
            await interaction.response.send_message(
                embed=build_embed(
                    "Calma aí",
                    f"Você pode abrir outro ticket em {limit.retry_after:.0f}s.",
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        config = (await self.config_service.get_config(guild.id)).tickets
        triage_channel = await self._resolve_triage_channel(guild, config)
        if triage_channel is None:
            await interaction.response.send_message(
                embed=build_embed(
                    "Triagem não configurada",
                    (
                        "Configure o canal de triagem de Tickets na Dashboard "
                        "antes de abrir novos casos."
                    ),
                    ERROR_COLOR,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        ticket = await self.ticket_service.create_ticket(
            guild_id=guild.id,
            ticket_type=ticket_type,
            creator_user_id=interaction.user.id,
            description=description,
            target_user_id=target.id if target else None,
            anonymous_report=(
                ticket_type == TicketType.REPORT and config.anonymous_reports_enabled
            ),
            expiration_hours=config.ticket_expiration_hours,
            archive_after_hours=config.archive_after_hours,
        )
        if config.triage_channel_id == triage_channel.id:
            await self._ensure_triage_permissions(triage_channel, config)
        message = await safe_send_message(
            triage_channel,
            embed=_ticket_triage_embed(ticket),
            view=TicketTriageView(ticket.id),
            reason="send_ticket_triage",
        )
        ticket = await self.ticket_service.mark_triage_posted(
            ticket_id=ticket.id,
            triage_channel_id=triage_channel.id,
            triage_message_id=message.id,
        )
        await self._log_ticket_action(
            guild=guild,
            ticket=ticket,
            event_type="ticket_created",
            title="Ticket criado",
            description=f"Ticket #{ticket.id:04d} enviado para triagem.",
            actor_user_id=interaction.user.id,
        )
        await interaction.followup.send(
            embed=build_embed(
                "Ticket aberto",
                f"Seu ticket #{ticket.id:04d} foi enviado para triagem da staff.",
                SUCCESS_COLOR,
            ),
            ephemeral=True,
        )

    async def _resolve_triage_channel(
        self,
        guild: discord.Guild,
        config: TicketConfigModel,
    ) -> discord.TextChannel | None:
        if config.triage_channel_id is not None:
            channel = guild.get_channel(config.triage_channel_id)
            if isinstance(channel, discord.TextChannel):
                return channel
            await audit_log_service.send_owner_alert(
                guild=guild,
                title="Canal de triagem inválido",
                description=(
                    "O canal de triagem configurado na Dashboard não existe mais."
                ),
                color=ERROR_COLOR,
            )

        if isinstance(guild.system_channel, discord.TextChannel):
            await audit_log_service.send_owner_alert(
                guild=guild,
                title="Triagem sem canal dedicado",
                description=(
                    "Configure o canal de triagem na Dashboard. O canal padrão "
                    "foi usado apenas como fallback."
                ),
                color=ERROR_COLOR,
            )
            return guild.system_channel
        return None

    async def _ensure_triage_permissions(
        self,
        channel: discord.TextChannel,
        config: TicketConfigModel,
    ) -> None:
        await safe_edit_channel_permissions(
            channel,
            channel.guild.default_role,
            overwrite=discord.PermissionOverwrite(view_channel=False),
            reason="Restringir triagem de tickets à staff",
        )
        for role_id in config.staff_role_ids + config.admin_role_ids:
            role = channel.guild.get_role(role_id)
            if role is not None:
                await safe_edit_channel_permissions(
                    channel,
                    role,
                    overwrite=discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                    ),
                    reason="Permitir triagem de tickets para staff",
                )

    async def _create_private_ticket_channels(
        self,
        *,
        guild: discord.Guild,
        ticket: TicketModel,
        config: TicketConfigModel,
    ) -> TicketModel:
        overwrites = self._private_channel_overwrites(guild, ticket, config)
        category = await safe_create_category(
            guild,
            name=f"Ticket {ticket.id:04d}",
            overwrites=overwrites,
            reason=PRIVATE_CHANNEL_REASON,
        )
        text_channel = await safe_create_text_channel(
            guild,
            name=f"ticket-{ticket.id:04d}-{_ticket_owner_slug(guild, ticket)}",
            category=category,
            overwrites=overwrites,
            reason=PRIVATE_CHANNEL_REASON,
        )
        voice_channel: discord.VoiceChannel | None = None
        if config.create_voice_channel:
            voice_channel = await safe_create_voice_channel(
                guild,
                name=f"Ticket {ticket.id:04d}",
                category=category,
                overwrites=overwrites,
                reason=PRIVATE_CHANNEL_REASON,
            )

        updated = await self.ticket_service.record_private_channels(
            ticket_id=ticket.id,
            category_channel_id=category.id,
            private_text_channel_id=text_channel.id,
            private_voice_channel_id=voice_channel.id if voice_channel else None,
        )
        await safe_send_message(
            text_channel,
            content=_ticket_mentions(ticket),
            embed=_private_ticket_embed(updated),
            view=TicketPrivateView(ticket_id=ticket.id),
            reason="send_private_ticket_intro",
        )
        return updated

    async def _send_ticket_admin_panel(
        self,
        *,
        interaction: discord.Interaction,
        ticket: TicketModel,
    ) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(
                embed=_ticket_admin_panel_embed(ticket),
                view=TicketAdminView(
                    ticket_id=ticket.id,
                    can_escalate=ticket.ticket_type == TicketType.REPORT,
                ),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=_ticket_admin_panel_embed(ticket),
            view=TicketAdminView(
                ticket_id=ticket.id,
                can_escalate=ticket.ticket_type == TicketType.REPORT,
            ),
            ephemeral=True,
        )

    def _private_channel_overwrites(
        self,
        guild: discord.Guild,
        ticket: TicketModel,
        config: TicketConfigModel,
    ) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
        blocked = discord.PermissionOverwrite(view_channel=False)
        participant_allowed = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            connect=True,
            speak=True,
        )
        staff_view_only = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=False,
            read_message_history=True,
            connect=False,
            speak=False,
        )
        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
            guild.default_role: blocked,
        }

        bot_member = guild.me
        if bot_member is not None:
            overwrites[bot_member] = participant_allowed

        for user_id in {
            ticket.creator_user_id,
            ticket.target_user_id,
            ticket.accepted_by_user_id,
        }:
            if user_id is None:
                continue
            member = guild.get_member(user_id)
            if member is not None:
                overwrites[member] = participant_allowed

        for role_id in (
            config.staff_role_ids + config.judge_role_ids + config.admin_role_ids
        ):
            role = guild.get_role(role_id)
            if role is not None:
                overwrites[role] = staff_view_only

        return overwrites

    async def _post_tribunal_vote(
        self,
        interaction: discord.Interaction,
        ticket: TicketModel,
        config: TicketConfigModel,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            return

        channel = None
        if ticket.private_text_channel_id is not None:
            channel = guild.get_channel(ticket.private_text_channel_id)
        if not isinstance(channel, discord.TextChannel):
            channel = await self._resolve_triage_channel(guild, config)
        if channel is None:
            return

        target_user_ids = await self._tribunal_target_user_ids(ticket)
        message = await safe_send_message(
            channel,
            embed=_tribunal_embed(
                ticket,
                config.tribunal_majority_votes,
                target_user_ids,
            ),
            view=TribunalView(ticket.id),
            reason="send_tribunal_vote",
        )
        await self.ticket_service.set_tribunal_message(
            ticket_id=ticket.id,
            tribunal_message_id=message.id,
        )
        await self._log_ticket_action(
            guild=guild,
            ticket=ticket,
            event_type="ticket_escalated",
            title="Ticket escalado para Tribunal",
            description=f"Ticket #{ticket.id:04d} agora aguarda votação.",
            actor_user_id=interaction.user.id,
        )

    async def _apply_tribunal_decision(
        self,
        *,
        guild: discord.Guild,
        ticket: TicketModel,
        decision: TribunalVoteChoice,
        actor_user_id: int,
    ) -> None:
        target_user_ids = await self._tribunal_target_user_ids(ticket)
        targets = [
            member
            for target_user_id in target_user_ids
            if (member := await _resolve_member(guild, target_user_id)) is not None
        ]
        reason = f"Tribunal TARS Ticket #{ticket.id:04d}: {_decision_label(decision)}"

        for target in targets:
            if decision == TribunalVoteChoice.TIMEOUT:
                await target.timeout(
                    timedelta(hours=TRIBUNAL_TIMEOUT_HOURS),
                    reason=reason,
                )
            elif decision == TribunalVoteChoice.KICK:
                await target.kick(reason=reason)
            elif decision == TribunalVoteChoice.TEMP_BAN:
                await target.ban(reason=reason, delete_message_seconds=0)
                self.bot.loop.create_task(
                    self._unban_after_temp_ban(
                        guild_id=guild.id,
                        user_id=target.id,
                        ticket_id=ticket.id,
                    ),
                )
            elif decision == TribunalVoteChoice.PERM_BAN:
                await target.ban(reason=reason, delete_message_seconds=0)

        closed = await self.ticket_service.close_ticket(
            ticket_id=ticket.id,
            actor_user_id=actor_user_id,
            reason=reason,
        )
        await self._log_ticket_action(
            guild=guild,
            ticket=closed,
            event_type="tribunal_decision",
            title="Decisão do Tribunal",
            description=reason,
            actor_user_id=actor_user_id,
        )
        await self._delete_ticket_private_channels(
            guild,
            closed,
            reason="Fechamento imediato por decisão do Tribunal",
        )

    async def _tribunal_target_user_ids(self, ticket: TicketModel) -> tuple[int, ...]:
        target_user_ids = await self.ticket_service.list_tribunal_target_user_ids(
            ticket.id,
        )
        if target_user_ids:
            return target_user_ids
        if ticket.target_user_id is not None:
            return (ticket.target_user_id,)
        return ()

    async def _close_expired_tickets(self) -> None:
        for ticket in await self.ticket_service.list_expired_tickets():
            guild = self.bot.get_guild(ticket.guild_id)
            closed = await self.ticket_service.close_ticket(
                ticket_id=ticket.id,
                actor_user_id=None,
                reason="Ticket expirado automaticamente.",
            )
            if guild is not None:
                await self._log_ticket_action(
                    guild=guild,
                    ticket=closed,
                    event_type="ticket_expired",
                    title="Ticket expirado",
                    description=f"Ticket #{ticket.id:04d} fechado por expiração.",
                    actor_user_id=None,
                )
                await self._delete_ticket_private_channels(
                    guild,
                    closed,
                    reason="Fechamento imediato de ticket expirado",
                )

    async def _delete_archive_ready_channels(self) -> None:
        for ticket in await self.ticket_service.list_archive_ready_tickets():
            guild = self.bot.get_guild(ticket.guild_id)
            if guild is None:
                continue
            await self._delete_ticket_private_channels(
                guild,
                ticket,
                reason="Arquivamento automático de ticket fechado",
            )

    async def _set_member_ticket_permissions(
        self,
        *,
        guild: discord.Guild,
        ticket: TicketModel,
        member: discord.Member,
        config: TicketConfigModel,
        can_send: bool,
    ) -> None:
        if can_send:
            overwrite = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                connect=True,
                speak=True,
            )
        elif _member_has_any_role(member, _ticket_role_ids(config)):
            overwrite = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=False,
                read_message_history=True,
                connect=False,
                speak=False,
            )
        else:
            overwrite = discord.PermissionOverwrite(view_channel=False)

        for channel_id in (
            ticket.category_channel_id,
            ticket.private_text_channel_id,
            ticket.private_voice_channel_id,
        ):
            if channel_id is None:
                continue
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.abc.GuildChannel):
                await safe_edit_channel_permissions(
                    channel,
                    member,
                    overwrite=overwrite,
                    reason="Atualizar participante do caso",
                )

    async def _delete_ticket_private_channels(
        self,
        guild: discord.Guild,
        ticket: TicketModel,
        *,
        reason: str,
    ) -> None:
        for channel_id in (
            ticket.private_voice_channel_id,
            ticket.private_text_channel_id,
            ticket.category_channel_id,
        ):
            if channel_id is None:
                continue
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.abc.GuildChannel):
                await safe_delete_channel(channel, reason=reason)
        await self.ticket_service.mark_channels_archived(ticket.id)

    async def _unban_after_temp_ban(
        self,
        *,
        guild_id: int,
        user_id: int,
        ticket_id: int,
    ) -> None:
        await asyncio.sleep(timedelta(hours=TRIBUNAL_TEMP_BAN_HOURS).total_seconds())
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return

        try:
            await guild.unban(
                discord.Object(id=user_id),
                reason=f"Fim do ban temporário do Tribunal Ticket #{ticket_id:04d}",
            )
        except discord.HTTPException:
            logger.exception(
                "Failed to unban temporary Tribunal target ticket_id=%s user_id=%s",
                ticket_id,
                user_id,
            )

    async def _log_ticket_action(
        self,
        *,
        guild: discord.Guild,
        ticket: TicketModel,
        event_type: str,
        title: str,
        description: str,
        actor_user_id: int | None,
    ) -> None:
        await audit_log_service.log_event(
            guild=guild,
            event_type=event_type,
            title=title,
            description=description,
            payload={
                "ticket_id": ticket.id,
                "ticket_type": ticket.ticket_type.value,
                "status": ticket.status.value,
                "target_user_id": ticket.target_user_id,
            },
            actor_user_id=actor_user_id,
            target_user_id=ticket.target_user_id,
            color=INFO_COLOR,
        )

    def _member_can_manage_ticket(
        self,
        user: discord.User | discord.Member,
        config: TicketConfigModel,
    ) -> bool:
        return _member_has_any_role(
            user,
            config.staff_role_ids + config.admin_role_ids,
        )

    def _member_can_vote_tribunal(
        self,
        user: discord.User | discord.Member,
        config: TicketConfigModel,
    ) -> bool:
        return _member_has_any_role(
            user,
            config.judge_role_ids + config.admin_role_ids,
        )


def _member_has_any_role(
    user: discord.User | discord.Member,
    role_ids: tuple[int, ...],
) -> bool:
    if not isinstance(user, discord.Member):
        return False
    member_role_ids = {role.id for role in user.roles}
    return bool(member_role_ids.intersection(role_ids))


def _user_is_ticket_conductor(
    user: discord.User | discord.Member,
    ticket: TicketModel,
) -> bool:
    return (
        ticket.accepted_by_user_id is not None and user.id == ticket.accepted_by_user_id
    )


def _ticket_role_ids(config: TicketConfigModel) -> tuple[int, ...]:
    return config.staff_role_ids + config.judge_role_ids + config.admin_role_ids


async def _resolve_member(
    guild: discord.Guild,
    user_id: int,
) -> discord.Member | None:
    cached = guild.get_member(user_id)
    if cached is not None:
        return cached

    try:
        return await guild.fetch_member(user_id)
    except discord.HTTPException:
        return None


def _ticket_owner_slug(guild: discord.Guild, ticket: TicketModel) -> str:
    member = guild.get_member(ticket.creator_user_id)
    raw_name = (
        member.display_name if member is not None else str(ticket.creator_user_id)
    )
    normalized = re.sub(r"[^a-z0-9-]+", "-", raw_name.lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized[:32] or str(ticket.creator_user_id)


def _ticket_mentions(ticket: TicketModel) -> str:
    mentions = [f"<@{ticket.creator_user_id}>"]
    if ticket.target_user_id is not None:
        mentions.append(f"<@{ticket.target_user_id}>")
    return f"Envolvidos no caso: {' '.join(mentions)}"


def _ticket_triage_embed(ticket: TicketModel) -> discord.Embed:
    ticket_label = "Suporte" if ticket.ticket_type == TicketType.SUPPORT else "Denúncia"
    reporter = "Anônimo" if ticket.anonymous_report else f"<@{ticket.creator_user_id}>"
    embed = build_embed(
        title=f"{ticket_label} #{ticket.id:04d}",
        description=ticket.description,
        color=INFO_COLOR,
    )
    embed.add_field(name="Criador", value=reporter, inline=True)
    embed.add_field(
        name="Alvo",
        value=f"<@{ticket.target_user_id}>" if ticket.target_user_id else "Nenhum",
        inline=True,
    )
    embed.add_field(name="Expira em", value=ticket.expires_at.strftime("%d/%m %H:%M"))
    return embed


def _private_ticket_embed(ticket: TicketModel) -> discord.Embed:
    embed = build_embed(
        title=f"Ticket #{ticket.id:04d}",
        description="Canal privado criado para triagem e resolução do caso.",
        color=SUCCESS_COLOR,
    )
    embed.add_field(name="Tipo", value=ticket.ticket_type.value, inline=True)
    embed.add_field(name="Criador", value=f"<@{ticket.creator_user_id}>", inline=True)
    embed.add_field(
        name="Alvo",
        value=f"<@{ticket.target_user_id}>" if ticket.target_user_id else "Nenhum",
        inline=True,
    )
    embed.add_field(
        name="Aceito por",
        value=(
            f"<@{ticket.accepted_by_user_id}>"
            if ticket.accepted_by_user_id
            else "Aguardando staff"
        ),
        inline=True,
    )
    embed.add_field(
        name="Condutor",
        value=(
            f"<@{ticket.accepted_by_user_id}>"
            if ticket.accepted_by_user_id
            else "Aguardando staff"
        ),
        inline=True,
    )
    return embed


def _ticket_admin_panel_embed(ticket: TicketModel) -> discord.Embed:
    embed = build_embed(
        title=f"Painel administrativo #{ticket.id:04d}",
        description=(
            "Use este painel para gerenciar participantes, escalar para Tribunal "
            "ou encerrar o caso."
        ),
        color=INFO_COLOR,
    )
    if ticket.private_text_channel_id is not None:
        embed.add_field(
            name="Canal do caso",
            value=f"<#{ticket.private_text_channel_id}>",
            inline=True,
        )
    embed.add_field(
        name="Condutor",
        value=(
            f"<@{ticket.accepted_by_user_id}>"
            if ticket.accepted_by_user_id
            else "Aguardando staff"
        ),
        inline=True,
    )
    return embed


def _tribunal_embed(
    ticket: TicketModel,
    majority_votes: int,
    target_user_ids: tuple[int, ...],
) -> discord.Embed:
    embed = build_embed(
        title=f"Tribunal #{ticket.id:04d}",
        description=ticket.description,
        color=INFO_COLOR,
    )
    embed.add_field(name="Maioria", value=f"{majority_votes} voto(s)", inline=True)
    embed.add_field(
        name="Alvos da ação",
        value=(
            " ".join(f"<@{target_user_id}>" for target_user_id in target_user_ids)
            if target_user_ids
            else "A definir"
        ),
        inline=True,
    )
    return embed


def _decision_label(decision: TribunalVoteChoice) -> str:
    labels = {
        TribunalVoteChoice.ABSOLVE: "Absolver",
        TribunalVoteChoice.TIMEOUT: "Timeout",
        TribunalVoteChoice.KICK: "Kick",
        TribunalVoteChoice.TEMP_BAN: "Ban temporário",
        TribunalVoteChoice.PERM_BAN: "Ban permanente",
        TribunalVoteChoice.OTHER: "Outros",
    }
    return labels[decision]


async def setup(bot: commands.Bot) -> None:
    """Load the ticket cog."""

    await bot.add_cog(TicketCog(bot))
