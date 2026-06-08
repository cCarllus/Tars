"""XP listeners, rank commands and admin controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bot.database.models.core_models import DEFAULT_LEVELUP_MESSAGE
from bot.database.models.level_models import UserLevelModel, XPGainResult
from bot.database.models.log_models import LogCategory
from bot.logger import logger
from bot.services.log_service import log_service
from bot.services.xp_service import XPService
from bot.utils.locks import lock_registry
from bot.utils.xp_utils import (
    create_daily_embed,
    create_leaderboard_embed,
    create_level_up_embed,
    create_rank_embed,
    create_xp_audit_embed,
    create_xp_error_embed,
    has_xp_staff_role,
    resolve_xp_admin_permission,
    validate_xp_add_limit,
    validate_xp_set_limit,
    xp_progress_for_level,
)

VOICE_XP_TICK_SECONDS = 60


@dataclass
class VoiceXPState:
    """Tracked voice state used for periodic XP awards."""

    channel_id: int
    last_awarded_at: datetime


class LevelsCog(commands.Cog):
    """Award XP from real activity and expose level commands."""

    xp = app_commands.Group(
        name="xp",
        description="Administração de XP e níveis.",
        guild_only=True,
    )

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the levels cog."""

        self.bot = bot
        self.service = XPService()
        self._voice_sessions: dict[tuple[int, int], VoiceXPState] = {}
        self._voice_xp_loop.start()

    async def cog_unload(self) -> None:
        """Stop the voice XP loop when the cog unloads."""

        self._voice_xp_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Track members that were already in voice when the bot connected."""

        now = datetime.now(tz=timezone.utc)  # noqa: UP017
        for guild in self.bot.guilds:
            for channel in [*guild.voice_channels, *guild.stage_channels]:
                for member in channel.members:
                    if member.bot:
                        continue
                    self._voice_sessions.setdefault(
                        (guild.id, member.id),
                        VoiceXPState(channel_id=channel.id, last_awarded_at=now),
                    )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Award message XP while ignoring bots and DMs."""

        if message.guild is None or message.author.bot:
            return

        async with lock_registry.user(message.author.id):
            result = await self.service.add_message_xp(
                guild_id=message.guild.id,
                user_id=message.author.id,
                channel_id=message.channel.id,
                content=message.content,
                created_at=message.created_at,
            )

        if isinstance(message.author, discord.Member):
            await self._handle_level_up(
                member=message.author,
                result=result,
                channel=message.channel,
            )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Award voice XP when a member leaves or moves channels."""

        if member.bot or before.channel == after.channel:
            return

        key = (member.guild.id, member.id)
        now = datetime.now(tz=timezone.utc)  # noqa: UP017
        if before.channel is not None and key in self._voice_sessions:
            state = self._voice_sessions.pop(key)
            await self._award_voice_minutes(
                member=member,
                channel=before.channel,
                minutes=completed_voice_minutes(state.last_awarded_at, now),
            )

        if after.channel is not None:
            self._voice_sessions[key] = VoiceXPState(
                channel_id=after.channel.id,
                last_awarded_at=now,
            )

    @tasks.loop(seconds=VOICE_XP_TICK_SECONDS)
    async def _voice_xp_loop(self) -> None:
        """Award voice XP periodically while members stay connected."""

        if not self.bot.is_ready():
            return

        now = datetime.now(tz=timezone.utc)  # noqa: UP017
        for key, state in list(self._voice_sessions.items()):
            guild_id, user_id = key
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                self._voice_sessions.pop(key, None)
                continue

            member = guild.get_member(user_id)
            if member is None or member.bot or member.voice is None:
                self._voice_sessions.pop(key, None)
                continue

            channel = member.voice.channel
            if channel is None:
                self._voice_sessions.pop(key, None)
                continue

            if channel.id != state.channel_id:
                self._voice_sessions[key] = VoiceXPState(
                    channel_id=channel.id,
                    last_awarded_at=now,
                )
                continue

            minutes = completed_voice_minutes(state.last_awarded_at, now)
            if minutes < 1:
                continue

            await self._award_voice_minutes(
                member=member,
                channel=channel,
                minutes=minutes,
            )
            state.last_awarded_at += timedelta(minutes=minutes)

    @_voice_xp_loop.before_loop
    async def _before_voice_xp_loop(self) -> None:
        """Wait until Discord is ready before awarding voice XP."""

        await self.bot.wait_until_ready()

    @app_commands.command(name="rank", description="Mostra seu card de rank.")
    @app_commands.describe(user="Membro que você quer consultar.")
    async def rank(
        self,
        interaction: discord.Interaction,
        user: discord.Member | None = None,
    ) -> None:
        """Show a rank card with XP, level and leaderboard position."""

        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só funciona dentro do servidor.",
                ephemeral=True,
            )
            return

        member = user or interaction.user
        record = await self.service.get_user_level(
            guild_id=interaction.guild.id,
            user_id=member.id,
        )
        rank_position = await self.service.get_user_rank(
            guild_id=interaction.guild.id,
            user_id=member.id,
        )
        config = await self.service.config_service.get_config(interaction.guild.id)
        _level, xp_in_level, xp_needed = xp_progress_for_level(
            record.xp,
            quadratic=config.leveling.level_formula_quadratic,
            linear=config.leveling.level_formula_linear,
            constant=config.leveling.level_formula_constant,
        )
        await interaction.response.send_message(
            embed=create_rank_embed(
                user=member,
                record=record,
                rank_position=rank_position,
                xp_in_level=xp_in_level,
                xp_needed=xp_needed,
            ),
        )

    @app_commands.command(
        name="leaderboard",
        description="Mostra o top 10 global ou semanal de XP.",
    )
    @app_commands.choices(
        periodo=[
            app_commands.Choice(name="Global", value="global"),
            app_commands.Choice(name="Semanal", value="weekly"),
        ],
    )
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        periodo: app_commands.Choice[str],
    ) -> None:
        """Show the global or weekly top 10 leaderboard."""

        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só funciona dentro do servidor.",
                ephemeral=True,
            )
            return

        weekly = periodo.value == "weekly"
        records = await self.service.get_leaderboard(
            guild_id=interaction.guild.id,
            limit=10,
            weekly=weekly,
        )
        title = "Leaderboard semanal" if weekly else "Leaderboard global"
        await interaction.response.send_message(
            embed=create_leaderboard_embed(
                title=title,
                lines=self._format_leaderboard(
                    interaction.guild,
                    records,
                    weekly,
                ),
            ),
        )

    @app_commands.command(name="daily", description="Resgata seu XP diário.")
    async def daily(self, interaction: discord.Interaction) -> None:
        """Claim the daily XP reward with streak bonus."""

        if interaction.guild is None or not isinstance(
            interaction.user,
            discord.Member,
        ):
            await interaction.response.send_message(
                "Esse comando só funciona dentro do servidor.",
                ephemeral=True,
            )
            return

        async with lock_registry.user(interaction.user.id):
            result = await self.service.claim_daily(
                guild_id=interaction.guild.id,
                user_id=interaction.user.id,
            )

        if result.ignored_reason == "daily_already_claimed":
            await interaction.response.send_message(
                embed=create_xp_error_embed("Você já resgatou o daily hoje."),
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=create_daily_embed(
                xp_awarded=result.xp_awarded,
                streak=result.user_level.daily_streak,
            ),
        )
        await self._handle_level_up(member=interaction.user, result=result)

    @xp.command(name="add", description="Adiciona XP a um membro.")
    @app_commands.describe(user="Membro alvo.", amount="Quantidade de XP.")
    async def xp_add(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        amount: int,
    ) -> None:
        """Add XP to a member through an admin command."""

        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só funciona dentro do servidor.",
                ephemeral=True,
            )
            return

        config = await self.service.config_service.get_config(interaction.guild.id)
        permission = resolve_xp_admin_permission(
            user_id=interaction.user.id,
            has_staff_permission=has_xp_staff_role(
                interaction.user,
                config.leveling.xp_staff_role_ids,
            ),
            configured_owner_user_id=config.leveling.xp_owner_user_id,
        )
        denial_reason = validate_xp_add_limit(
            amount=amount,
            permission=permission,
            staff_max_xp_per_command=config.leveling.staff_max_xp_per_command,
        )
        if denial_reason:
            await interaction.response.send_message(
                embed=create_xp_error_embed(denial_reason),
                ephemeral=True,
            )
            return

        result = await self.service.add_xp(
            guild_id=interaction.guild.id,
            user_id=user.id,
            amount=amount,
        )
        await interaction.response.send_message(
            embed=create_xp_audit_embed(
                actor=interaction.user,
                target=user,
                action="XP adicionado",
                detail=(
                    f"+{result.xp_awarded} XP; "
                    f"nível atual {result.user_level.level}"
                ),
                actor_label=permission.actor_label,
            ),
            ephemeral=True,
        )
        await self._log_xp_admin_action(
            guild=interaction.guild,
            actor=interaction.user,
            target=user,
            action="XP add",
            detail=f"+{result.xp_awarded} XP",
            actor_label=permission.actor_label,
        )
        await self._handle_level_up(member=user, result=result)

    @xp.command(name="set", description="Define o nível de um membro.")
    @app_commands.describe(user="Membro alvo.", level="Nível desejado.")
    async def xp_set(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        level: int,
    ) -> None:
        """Set a member level through an admin command."""

        if interaction.guild is None:
            await interaction.response.send_message(
                "Esse comando só funciona dentro do servidor.",
                ephemeral=True,
            )
            return

        config = await self.service.config_service.get_config(interaction.guild.id)
        permission = resolve_xp_admin_permission(
            user_id=interaction.user.id,
            has_staff_permission=has_xp_staff_role(
                interaction.user,
                config.leveling.xp_staff_role_ids,
            ),
            configured_owner_user_id=config.leveling.xp_owner_user_id,
        )
        denial_reason = validate_xp_set_limit(
            level=level,
            permission=permission,
            staff_max_set_level=config.leveling.staff_max_set_level,
        )
        if denial_reason:
            await interaction.response.send_message(
                embed=create_xp_error_embed(denial_reason),
                ephemeral=True,
            )
            return

        record = await self.service.set_user_level(
            guild_id=interaction.guild.id,
            user_id=user.id,
            level=level,
        )
        await interaction.response.send_message(
            embed=create_xp_audit_embed(
                actor=interaction.user,
                target=user,
                action="Nível definido",
                detail=f"nível {record.level}",
                actor_label=permission.actor_label,
            ),
            ephemeral=True,
        )
        await self._log_xp_admin_action(
            guild=interaction.guild,
            actor=interaction.user,
            target=user,
            action="XP set",
            detail=f"nível {record.level}",
            actor_label=permission.actor_label,
        )

    async def _handle_level_up(
        self,
        *,
        member: discord.Member,
        result: XPGainResult,
        channel: discord.abc.Messageable | None = None,
    ) -> None:
        if not result.leveled_up:
            return

        await self._grant_role_rewards(member, result.user_level.level)
        config = await self.service.config_service.get_config(member.guild.id)
        if not config.leveling.levelup_enabled:
            return

        target_channel = self._resolve_levelup_channel(
            guild=member.guild,
            configured_channel_id=config.leveling.levelup_channel_id,
            fallback_channel=channel,
        )
        if target_channel is None:
            return

        try:
            description = format_levelup_message(
                template=config.leveling.levelup_message,
                user_mention=member.mention,
                display_name=member.display_name,
                level=result.user_level.level,
                xp=result.user_level.xp,
                server_name=member.guild.name,
                mention_enabled=config.leveling.levelup_mention,
            )
        except (KeyError, ValueError):
            logger.exception(
                "Invalid level-up template guild_id=%s user_id=%s",
                member.guild.id,
                member.id,
            )
            description = format_levelup_message(
                template=DEFAULT_LEVELUP_MESSAGE,
                user_mention=member.mention,
                display_name=member.display_name,
                level=result.user_level.level,
                xp=result.user_level.xp,
                server_name=member.guild.name,
                mention_enabled=config.leveling.levelup_mention,
            )

        content = levelup_notification_content(
            user_mention=member.mention,
            mention_enabled=config.leveling.levelup_mention,
        )
        message = await target_channel.send(
            content=content,
            allowed_mentions=discord.AllowedMentions(
                users=config.leveling.levelup_mention,
            ),
            embed=create_level_up_embed(
                member=member,
                level=result.user_level.level,
                xp=result.user_level.xp,
                description=description,
            ),
        )
        try:
            await message.add_reaction("🎉")
        except discord.HTTPException:
            logger.exception(
                "Failed to add level-up reaction guild_id=%s user_id=%s",
                member.guild.id,
                member.id,
            )
        await log_service.record_system_event(
            guild=member.guild,
            guild_id=member.guild.id,
            event_type="level_up",
            title="Level up",
            description=(
                f"{member.mention} subiu para o nível {result.user_level.level}."
            ),
            payload={
                "level": result.user_level.level,
                "xp": result.user_level.xp,
            },
            actor_user_id=member.id,
            target_user_id=member.id,
            category=LogCategory.XP_ECONOMY,
            color=0x2ECC71,
        )

    def _resolve_levelup_channel(
        self,
        *,
        guild: discord.Guild,
        configured_channel_id: int | None,
        fallback_channel: discord.abc.Messageable | None,
    ) -> discord.abc.Messageable | None:
        if configured_channel_id is not None:
            configured_channel = guild.get_channel(configured_channel_id)
            if isinstance(configured_channel, discord.abc.Messageable):
                return configured_channel
            logger.warning(
                (
                    "Configured level-up channel is unavailable; using fallback "
                    "guild_id=%s channel_id=%s"
                ),
                guild.id,
                configured_channel_id,
            )
        else:
            logger.warning(
                "Level-up channel is not configured; using fallback guild_id=%s",
                guild.id,
            )

        if fallback_channel is not None:
            return fallback_channel
        if isinstance(guild.system_channel, discord.abc.Messageable):
            return guild.system_channel
        return None

    async def _award_voice_minutes(
        self,
        *,
        member: discord.Member,
        channel: discord.abc.Connectable,
        minutes: int,
    ) -> None:
        if minutes < 1:
            return

        participant_count = _voice_participant_count(channel)
        async with lock_registry.user(member.id):
            result = await self.service.add_voice_xp(
                guild_id=member.guild.id,
                user_id=member.id,
                voice_minutes=minutes,
                participant_count=participant_count,
            )
        await self._handle_level_up(member=member, result=result)

    async def _grant_role_rewards(self, member: discord.Member, level: int) -> None:
        rewards = await self.service.list_earned_rewards(
            guild_id=member.guild.id,
            level=level,
        )
        roles = [
            role
            for reward in rewards
            if (role := member.guild.get_role(reward.role_id)) is not None
            and role not in member.roles
        ]
        if not roles:
            return

        try:
            await member.add_roles(*roles, reason="Recompensa automática por nível")
        except discord.HTTPException:
            logger.exception(
                "Failed to grant level rewards guild_id=%s user_id=%s",
                member.guild.id,
                member.id,
            )

    async def _log_xp_admin_action(
        self,
        *,
        guild: discord.Guild,
        actor: discord.abc.User,
        target: discord.abc.User,
        action: str,
        detail: str,
        actor_label: str,
    ) -> None:
        logger.info(
            (
                "XP admin action guild_id=%s actor_id=%s target_id=%s "
                "action=%s detail=%s role=%s"
            ),
            guild.id,
            actor.id,
            target.id,
            action,
            detail,
            actor_label,
        )
        await log_service.record_system_event(
            guild=guild,
            guild_id=guild.id,
            event_type="xp_admin_action",
            title="Comando administrativo de XP",
            description=f"{actor.mention} executou {action} em {target.mention}.",
            payload={"action": action, "detail": detail, "actor_label": actor_label},
            actor_user_id=actor.id,
            target_user_id=target.id,
            category=LogCategory.XP_ECONOMY,
            color=0x3498DB,
        )

    def _format_leaderboard(
        self,
        guild: discord.Guild,
        records: list[UserLevelModel],
        weekly: bool,
    ) -> list[str]:
        if not records:
            return []

        lines: list[str] = []
        for index, record in enumerate(records, start=1):
            member = guild.get_member(record.user_id)
            display_name = (
                member.display_name if member else f"Usuário {record.user_id}"
            )
            xp_value = record.weekly_xp if weekly else record.xp
            badge = _leaderboard_badge(index)
            lines.append(
                f"{badge} **{display_name}** • nível {record.level} • `{xp_value} XP`",
            )
        return lines


def _voice_participant_count(channel: discord.abc.Connectable) -> int:
    members = getattr(channel, "members", [])
    return max(1, len([member for member in members if not member.bot]))


def format_levelup_message(
    *,
    template: str,
    user_mention: str,
    display_name: str,
    level: int,
    xp: int,
    server_name: str,
    mention_enabled: bool,
) -> str:
    """Render a level-up announcement template with supported placeholders."""

    user_value = user_mention if mention_enabled else display_name
    return template.format(
        user=user_value,
        member=user_value,
        level=level,
        xp=xp,
        server=server_name,
    )


def levelup_notification_content(
    *,
    user_mention: str,
    mention_enabled: bool,
) -> str | None:
    """Return message content used solely to trigger a user mention."""

    if not mention_enabled:
        return None
    return user_mention


def completed_voice_minutes(started_at: datetime, ended_at: datetime) -> int:
    """Return full completed voice minutes between two timestamps."""

    return max(0, int((ended_at - started_at).total_seconds() // 60))


def _leaderboard_badge(position: int) -> str:
    badges = {1: "🥇", 2: "🥈", 3: "🥉"}
    return badges.get(position, f"`#{position}`")


async def setup(bot: commands.Bot) -> None:
    """Load the levels cog."""

    await bot.add_cog(LevelsCog(bot))
