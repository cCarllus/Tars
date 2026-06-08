"""Rich Discord event logging for TARS."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import discord
from discord.ext import commands

from bot.database.models.core_models import LogDetailLevel
from bot.database.models.log_models import LogCategory, LogEventCreate
from bot.logger import logger
from bot.services.log_service import LogService

AUDIT_LOOKBACK_SECONDS = 8


class RichLoggingCog(commands.Cog):
    """Capture Discord events and publish detailed TARS logs."""

    def __init__(self, bot: commands.Bot) -> None:
        """Initialize the rich logging cog."""

        self.bot = bot
        self.service = LogService()
        self._invite_cache: dict[int, dict[str, int]] = {}

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Warm invite caches when the bot becomes ready."""

        for guild in self.bot.guilds:
            await self._cache_invites(guild)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        """Refresh invite cache after a new invite is created."""

        if isinstance(invite.guild, discord.Guild):
            await self._cache_invites(invite.guild)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        """Refresh invite cache after an invite is deleted."""

        if isinstance(invite.guild, discord.Guild):
            await self._cache_invites(invite.guild)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Log server joins with the likely invite when available."""

        config = (await self.service.config_service.get_config(member.guild.id)).logs
        if self.service.should_ignore_member(member, config):
            return

        invite_code = await self._resolve_used_invite(member.guild)
        await self.service.emit(
            guild=member.guild,
            event=LogEventCreate(
                guild_id=member.guild.id,
                category=LogCategory.MEMBER,
                event_type="member_join",
                title="Membro entrou",
                description=f"{member.mention} entrou no servidor.",
                detail_level=int(LogDetailLevel.BASIC),
                target_user_id=member.id,
                payload={
                    "invite_code": invite_code or "Indisponível",
                    "account_created_at": member.created_at.isoformat(),
                },
                thumbnail_url=member.display_avatar.url,
            ),
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Log server leaves and likely kicks."""

        config = (await self.service.config_service.get_config(member.guild.id)).logs
        if self.service.should_ignore_member(member, config):
            return

        audit_entry = await self._latest_audit_entry(
            member.guild,
            discord.AuditLogAction.kick,
            target_user_id=member.id,
        )
        kicked = audit_entry is not None
        actor_id = audit_entry.user.id if audit_entry and audit_entry.user else None
        reason = audit_entry.reason if audit_entry else None
        await self.service.emit(
            guild=member.guild,
            event=LogEventCreate(
                guild_id=member.guild.id,
                category=LogCategory.MODERATION if kicked else LogCategory.MEMBER,
                event_type="member_kick" if kicked else "member_leave",
                title="Membro expulso" if kicked else "Membro saiu",
                description=(
                    f"{member.mention} foi expulso do servidor."
                    if kicked
                    else f"{member.mention} saiu do servidor."
                ),
                detail_level=int(LogDetailLevel.BASIC),
                actor_user_id=actor_id,
                target_user_id=member.id,
                payload={"reason": reason or "Não informado"},
                thumbnail_url=member.display_avatar.url,
            ),
        )

    @commands.Cog.listener()
    async def on_member_ban(
        self,
        guild: discord.Guild,
        user: discord.User | discord.Member,
    ) -> None:
        """Log bans with executor data when audit logs are available."""

        audit_entry = await self._latest_audit_entry(
            guild,
            discord.AuditLogAction.ban,
            target_user_id=user.id,
        )
        await self.service.emit(
            guild=guild,
            event=LogEventCreate(
                guild_id=guild.id,
                category=LogCategory.MODERATION,
                event_type="member_ban",
                title="Membro banido",
                description=f"{user.mention} foi banido do servidor.",
                detail_level=int(LogDetailLevel.BASIC),
                actor_user_id=_audit_actor_id(audit_entry),
                target_user_id=user.id,
                payload={"reason": _audit_reason(audit_entry)},
                thumbnail_url=user.display_avatar.url,
            ),
        )

    @commands.Cog.listener()
    async def on_member_unban(
        self,
        guild: discord.Guild,
        user: discord.User,
    ) -> None:
        """Log unbans with executor data when audit logs are available."""

        audit_entry = await self._latest_audit_entry(
            guild,
            discord.AuditLogAction.unban,
            target_user_id=user.id,
        )
        await self.service.emit(
            guild=guild,
            event=LogEventCreate(
                guild_id=guild.id,
                category=LogCategory.MODERATION,
                event_type="member_unban",
                title="Ban removido",
                description=f"{user.mention} teve o ban removido.",
                detail_level=int(LogDetailLevel.BASIC),
                actor_user_id=_audit_actor_id(audit_entry),
                target_user_id=user.id,
                payload={"reason": _audit_reason(audit_entry)},
                thumbnail_url=user.display_avatar.url,
            ),
        )

    @commands.Cog.listener()
    async def on_member_update(
        self,
        before: discord.Member,
        after: discord.Member,
    ) -> None:
        """Log nickname, timeout and guild-avatar changes."""

        config = (await self.service.config_service.get_config(after.guild.id)).logs
        if self.service.should_ignore_member(after, config):
            return

        if before.display_name != after.display_name:
            await self._log_member_update(
                before=before,
                after=after,
                event_type="member_nick_update",
                title="Apelido alterado",
                description=f"{after.mention} alterou o apelido.",
                payload={
                    "before": before.display_name,
                    "after": after.display_name,
                },
            )

        before_timeout = getattr(before, "timed_out_until", None)
        after_timeout = getattr(after, "timed_out_until", None)
        if before_timeout != after_timeout:
            timeout_added = after_timeout is not None and (
                before_timeout is None or after_timeout > before_timeout
            )
            audit_entry = await self._latest_audit_entry(
                after.guild,
                discord.AuditLogAction.member_update,
                target_user_id=after.id,
            )
            await self.service.emit(
                guild=after.guild,
                event=LogEventCreate(
                    guild_id=after.guild.id,
                    category=LogCategory.MODERATION,
                    event_type=(
                        "member_timeout_add"
                        if timeout_added
                        else "member_timeout_remove"
                    ),
                    title="Timeout aplicado" if timeout_added else "Timeout removido",
                    description=(
                        f"{after.mention} recebeu timeout."
                        if timeout_added
                        else f"{after.mention} teve o timeout removido."
                    ),
                    detail_level=int(LogDetailLevel.NORMAL),
                    actor_user_id=_audit_actor_id(audit_entry),
                    target_user_id=after.id,
                    payload={
                        "before": _datetime_label(before_timeout),
                        "after": _datetime_label(after_timeout),
                        "reason": _audit_reason(audit_entry),
                    },
                    thumbnail_url=after.display_avatar.url,
                ),
            )

        before_avatar_url = before.display_avatar.url
        after_avatar_url = after.display_avatar.url
        if before_avatar_url != after_avatar_url:
            await self.service.emit(
                guild=after.guild,
                event=LogEventCreate(
                    guild_id=after.guild.id,
                    category=LogCategory.PROFILE,
                    event_type="user_avatar_update",
                    title="Avatar alterado",
                    description=f"{after.mention} alterou o avatar exibido.",
                    detail_level=int(LogDetailLevel.NORMAL),
                    target_user_id=after.id,
                    payload={
                        "before": before_avatar_url,
                        "after": after_avatar_url,
                    },
                    thumbnail_url=before_avatar_url,
                    image_url=after_avatar_url,
                ),
            )

    @commands.Cog.listener()
    async def on_user_update(
        self,
        before: discord.User,
        after: discord.User,
    ) -> None:
        """Log global username and avatar changes for mutual guilds."""

        if (
            before.name == after.name
            and before.display_avatar.url == after.display_avatar.url
        ):
            return

        for guild in self.bot.guilds:
            member = guild.get_member(after.id)
            if member is None:
                continue

            config = (await self.service.config_service.get_config(guild.id)).logs
            if self.service.should_ignore_member(member, config):
                continue

            if before.name != after.name:
                await self.service.emit(
                    guild=guild,
                    event=LogEventCreate(
                        guild_id=guild.id,
                        category=LogCategory.PROFILE,
                        event_type="user_username_update",
                        title="Username alterado",
                        description=f"{after.mention} alterou o username global.",
                        detail_level=int(LogDetailLevel.NORMAL),
                        target_user_id=after.id,
                        payload={"before": before.name, "after": after.name},
                        thumbnail_url=after.display_avatar.url,
                    ),
                )

            if before.display_avatar.url != after.display_avatar.url:
                await self.service.emit(
                    guild=guild,
                    event=LogEventCreate(
                        guild_id=guild.id,
                        category=LogCategory.PROFILE,
                        event_type="user_avatar_update",
                        title="Avatar alterado",
                        description=f"{after.mention} alterou o avatar global.",
                        detail_level=int(LogDetailLevel.NORMAL),
                        target_user_id=after.id,
                        payload={
                            "before": before.display_avatar.url,
                            "after": after.display_avatar.url,
                        },
                        thumbnail_url=before.display_avatar.url,
                        image_url=after.display_avatar.url,
                    ),
                )

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Log voice channel movement and moderation state."""

        config = (await self.service.config_service.get_config(member.guild.id)).logs
        if self.service.should_ignore_member(member, config):
            return

        if before.channel != after.channel:
            before_channel = before.channel
            after_channel = after.channel
            event_type = "voice_move"
            title = "Canal de voz alterado"
            description = f"{member.mention} mudou de canal de voz."
            if before_channel is None and after_channel is not None:
                event_type = "voice_join"
                title = "Entrou em voz"
                description = f"{member.mention} entrou em {after_channel.mention}."
            elif after_channel is None and before_channel is not None:
                event_type = "voice_leave"
                title = "Saiu da voz"
                description = f"{member.mention} saiu de {before_channel.mention}."

            await self.service.emit(
                guild=member.guild,
                event=LogEventCreate(
                    guild_id=member.guild.id,
                    category=LogCategory.VOICE,
                    event_type=event_type,
                    title=title,
                    description=description,
                    detail_level=int(LogDetailLevel.DETAILED),
                    target_user_id=member.id,
                    channel_id=_voice_channel_id(before_channel, after_channel),
                    payload={
                        "before": (
                            before_channel.mention if before_channel else "Nenhum"
                        ),
                        "after": after_channel.mention if after_channel else "Nenhum",
                    },
                    thumbnail_url=member.display_avatar.url,
                ),
            )

        await self._log_voice_flag(
            member=member,
            before=before,
            after=after,
            before_value=before.mute,
            after_value=after.mute,
            add_event="voice_mute",
            remove_event="voice_unmute",
            add_title="Mute em voz",
            remove_title="Unmute em voz",
        )
        await self._log_voice_flag(
            member=member,
            before=before,
            after=after,
            before_value=before.deaf,
            after_value=after.deaf,
            add_event="voice_deafen",
            remove_event="voice_undeafen",
            add_title="Deafen em voz",
            remove_title="Undeafen em voz",
        )

    @commands.Cog.listener()
    async def on_message_edit(
        self,
        before: discord.Message,
        after: discord.Message,
    ) -> None:
        """Log message edits with before and after content."""

        if before.guild is None or before.content == after.content:
            return
        if await self.service.should_ignore_message(before):
            return

        await self.service.emit(
            guild=before.guild,
            event=LogEventCreate(
                guild_id=before.guild.id,
                category=LogCategory.MESSAGE,
                event_type="message_edit",
                title="Mensagem editada",
                description=f"Mensagem de {before.author.mention} editada.",
                detail_level=int(LogDetailLevel.NORMAL),
                actor_user_id=before.author.id,
                target_user_id=before.author.id,
                channel_id=before.channel.id,
                message_id=before.id,
                payload={
                    "before_content": before.content or "[sem conteúdo]",
                    "after_content": after.content or "[sem conteúdo]",
                    "jump_url": after.jump_url,
                },
                thumbnail_url=before.author.display_avatar.url,
            ),
        )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """Log deleted messages with content, author and channel."""

        if message.guild is None or await self.service.should_ignore_message(message):
            return

        audit_entry = await self._latest_audit_entry(
            message.guild,
            discord.AuditLogAction.message_delete,
            target_user_id=message.author.id,
        )
        await self.service.emit(
            guild=message.guild,
            event=LogEventCreate(
                guild_id=message.guild.id,
                category=LogCategory.MESSAGE,
                event_type="message_delete",
                title="Mensagem deletada",
                description=(
                    f"Mensagem de {message.author.mention} deletada em "
                    f"{_channel_label(message.channel)}."
                ),
                detail_level=int(LogDetailLevel.NORMAL),
                actor_user_id=_audit_actor_id(audit_entry) or message.author.id,
                target_user_id=message.author.id,
                channel_id=message.channel.id,
                message_id=message.id,
                payload={
                    "content": message.content or "[sem conteúdo em cache]",
                    "attachment_urls": [item.url for item in message.attachments],
                    "reason": _audit_reason(audit_entry),
                },
                thumbnail_url=message.author.display_avatar.url,
            ),
        )

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]) -> None:
        """Log message purge events."""

        if not messages or messages[0].guild is None:
            return
        guild = messages[0].guild
        channel = messages[0].channel
        for message in messages:
            if await self.service.should_ignore_message(message):
                return

        audit_entry = await self._latest_audit_entry(
            guild,
            discord.AuditLogAction.message_bulk_delete,
        )
        await self.service.emit(
            guild=guild,
            event=LogEventCreate(
                guild_id=guild.id,
                category=LogCategory.MESSAGE,
                event_type="message_bulk_delete",
                title="Mensagens deletadas em massa",
                description=(
                    f"{len(messages)} mensagens foram deletadas em "
                    f"{_channel_label(channel)}."
                ),
                detail_level=int(LogDetailLevel.NORMAL),
                actor_user_id=_audit_actor_id(audit_entry),
                channel_id=channel.id,
                payload={
                    "reason": _audit_reason(audit_entry),
                    "message_ids": [message.id for message in messages[:50]],
                },
            ),
        )

    @commands.Cog.listener()
    async def on_reaction_add(
        self,
        reaction: discord.Reaction,
        user: discord.User | discord.Member,
    ) -> None:
        """Log reaction additions."""

        await self._log_reaction(reaction, user, "reaction_add", "Reação adicionada")

    @commands.Cog.listener()
    async def on_reaction_remove(
        self,
        reaction: discord.Reaction,
        user: discord.User | discord.Member,
    ) -> None:
        """Log reaction removals."""

        await self._log_reaction(reaction, user, "reaction_remove", "Reação removida")

    async def _log_member_update(
        self,
        *,
        before: discord.Member,
        after: discord.Member,
        event_type: str,
        title: str,
        description: str,
        payload: dict[str, Any],
    ) -> None:
        audit_entry = await self._latest_audit_entry(
            after.guild,
            discord.AuditLogAction.member_update,
            target_user_id=after.id,
        )
        await self.service.emit(
            guild=after.guild,
            event=LogEventCreate(
                guild_id=after.guild.id,
                category=LogCategory.PROFILE,
                event_type=event_type,
                title=title,
                description=description,
                detail_level=int(LogDetailLevel.NORMAL),
                actor_user_id=_audit_actor_id(audit_entry) or after.id,
                target_user_id=after.id,
                payload={**payload, "reason": _audit_reason(audit_entry)},
                thumbnail_url=after.display_avatar.url,
            ),
        )

    async def _log_voice_flag(
        self,
        *,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
        before_value: bool,
        after_value: bool,
        add_event: str,
        remove_event: str,
        add_title: str,
        remove_title: str,
    ) -> None:
        if before_value == after_value:
            return

        enabled = after_value
        await self.service.emit(
            guild=member.guild,
            event=LogEventCreate(
                guild_id=member.guild.id,
                category=LogCategory.VOICE,
                event_type=add_event if enabled else remove_event,
                title=add_title if enabled else remove_title,
                description=(
                    f"{member.mention}: {'ativado' if enabled else 'removido'}."
                ),
                detail_level=int(LogDetailLevel.DETAILED),
                target_user_id=member.id,
                channel_id=_voice_channel_id(before.channel, after.channel),
                thumbnail_url=member.display_avatar.url,
            ),
        )

    async def _log_reaction(
        self,
        reaction: discord.Reaction,
        user: discord.User | discord.Member,
        event_type: str,
        title: str,
    ) -> None:
        message = reaction.message
        if message.guild is None or await self.service.should_ignore_message(message):
            return

        await self.service.emit(
            guild=message.guild,
            event=LogEventCreate(
                guild_id=message.guild.id,
                category=LogCategory.MESSAGE,
                event_type=event_type,
                title=title,
                description=(
                    f"{user.mention} "
                    f"{'adicionou' if event_type == 'reaction_add' else 'removeu'} "
                    f"`{reaction.emoji}` em uma mensagem."
                ),
                detail_level=int(LogDetailLevel.DETAILED),
                actor_user_id=user.id,
                target_user_id=message.author.id,
                channel_id=message.channel.id,
                message_id=message.id,
                payload={"jump_url": message.jump_url},
                thumbnail_url=user.display_avatar.url,
            ),
        )

    async def _latest_audit_entry(
        self,
        guild: discord.Guild,
        action: discord.AuditLogAction,
        *,
        target_user_id: int | None = None,
    ) -> discord.AuditLogEntry | None:
        if not guild.me or not guild.me.guild_permissions.view_audit_log:
            return None

        try:
            async for entry in guild.audit_logs(limit=6, action=action):
                if not _entry_is_recent(entry.created_at):
                    continue
                target = entry.target
                if (
                    target_user_id is not None
                    and getattr(target, "id", None) != target_user_id
                ):
                    continue
                return entry
        except discord.HTTPException:
            logger.exception(
                "Failed to read audit logs guild_id=%s action=%s",
                guild.id,
                action,
            )
        return None

    async def _cache_invites(self, guild: discord.Guild) -> None:
        if not guild.me or not guild.me.guild_permissions.manage_guild:
            return
        try:
            invites = await guild.invites()
        except discord.HTTPException:
            logger.exception("Failed to cache invites guild_id=%s", guild.id)
            return
        self._invite_cache[guild.id] = {
            invite.code: invite.uses or 0 for invite in invites
        }

    async def _resolve_used_invite(self, guild: discord.Guild) -> str | None:
        previous = self._invite_cache.get(guild.id, {})
        await self._cache_invites(guild)
        current = self._invite_cache.get(guild.id, {})
        for code, uses in current.items():
            if uses > previous.get(code, 0):
                return code
        return None


def _entry_is_recent(created_at: datetime) -> bool:
    now = datetime.now(tz=timezone.utc)  # noqa: UP017
    return now - created_at <= timedelta(seconds=AUDIT_LOOKBACK_SECONDS)


def _audit_actor_id(entry: discord.AuditLogEntry | None) -> int | None:
    if entry is None or entry.user is None:
        return None
    return entry.user.id


def _audit_reason(entry: discord.AuditLogEntry | None) -> str:
    if entry is None:
        return "Não disponível"
    return entry.reason or "Não informado"


def _datetime_label(value: datetime | None) -> str:
    if value is None:
        return "Nenhum"
    return value.isoformat()


def _voice_channel_id(
    before_channel: discord.VoiceChannel | discord.StageChannel | None,
    after_channel: discord.VoiceChannel | discord.StageChannel | None,
) -> int | None:
    channel = after_channel or before_channel
    return channel.id if channel else None


def _channel_label(channel: discord.abc.Messageable) -> str:
    mention = getattr(channel, "mention", None)
    if isinstance(mention, str):
        return mention
    channel_id = getattr(channel, "id", None)
    return f"`{channel_id}`" if channel_id is not None else "`canal desconhecido`"


async def setup(bot: commands.Bot) -> None:
    """Load the rich logging cog."""

    await bot.add_cog(RichLoggingCog(bot))
