"""State and Discord operations for temporary private voice calls."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass

import discord

from bot.config import settings
from bot.logger import logger
from bot.models.voice import VoiceSession
from bot.utils.database import SQLiteDatabase, database
from bot.utils.locks import LockRegistry, lock_registry
from bot.utils.private_voice_embeds import build_private_voice_invite_embed
from bot.utils.queue_manager import discord_api_queue
from bot.utils.rate_limiter import (
    VOICE_CREATION_ACTION,
    RateLimitExceeded,
    rate_limiter,
)
from bot.utils.safe_discord import (
    safe_create_voice_channel,
    safe_delete_channel,
    safe_edit_channel_permissions,
    safe_edit_voice_channel,
    safe_move_member,
    safe_send_dm,
)

PRIVATE_CALL_TOPIC_PREFIX = "private_voice_call:owner_id="
PRIVATE_CALL_NAME_TEMPLATE = "Call Privada - {display_name}"
MAX_VOICE_CHANNEL_NAME_LENGTH = 100
MAX_VOICE_USER_LIMIT = 99


@dataclass
class PrivateVoiceCallState:
    """Runtime state for a temporary private voice call."""

    guild_id: int
    owner_id: int
    channel_id: int
    is_private: bool = True
    soundboard_enabled: bool = True
    screen_share_enabled: bool = True


class PrivateVoiceManager:
    """Manage private voice channel lifecycle and permissions."""

    def __init__(
        self,
        hub_channel_id: int | None = None,
        *,
        db: SQLiteDatabase | None = None,
        locks: LockRegistry | None = None,
    ) -> None:
        """Initialize the manager.

        Args:
            hub_channel_id: Optional override for the private voice hub channel.
            db: Optional database override for tests.
            locks: Optional lock registry override for tests.
        """

        self.hub_channel_id = hub_channel_id or settings.private_voice_hub_id
        self.database = db or database
        self.locks = locks or lock_registry
        self._calls_by_owner: dict[int, PrivateVoiceCallState] = {}
        self._owner_by_channel: dict[int, int] = {}
        self._delete_lock = asyncio.Lock()
        self._deleting_channel_ids: set[int] = set()

    async def initialize(self) -> None:
        """Initialize persistent storage for private voice calls."""

        await self.database.initialize()

    async def reconcile_voice_sessions(
        self,
        guilds: Iterable[discord.Guild],
    ) -> None:
        """Load persisted voice sessions and remove orphan database records."""

        sessions = await self.database.list_voice_sessions()
        guild_by_id = {guild.id: guild for guild in guilds}

        for session in sessions:
            guild = guild_by_id.get(session.guild_id)
            channel = (
                guild.get_channel(session.channel_id) if guild is not None else None
            )

            if isinstance(channel, discord.VoiceChannel):
                self._register_persisted_call(session)
                logger.info(
                    "Recovered private voice call %s for owner %s",
                    session.channel_id,
                    session.owner_id,
                )
                continue

            await self.database.delete_voice_session_by_channel(session.channel_id)
            logger.info("Removed orphan private voice session %s", session.channel_id)

    def is_hub_channel(self, channel: discord.abc.GuildChannel | None) -> bool:
        """Return whether a channel is the configured private voice hub."""

        return channel is not None and channel.id == self.hub_channel_id

    def is_private_call(self, channel_id: int) -> bool:
        """Return whether a channel is managed as a private voice call."""

        return channel_id in self._owner_by_channel

    def is_owner(self, *, channel_id: int, user_id: int) -> bool:
        """Return whether a user owns a managed private call."""

        return self._owner_by_channel.get(channel_id) == user_id

    def get_owner_id(self, channel_id: int) -> int | None:
        """Return the owner ID for a private call channel, when known."""

        return self._owner_by_channel.get(channel_id)

    def get_call_state(self, channel_id: int) -> PrivateVoiceCallState | None:
        """Return runtime state for a private call channel."""

        owner_id = self._owner_by_channel.get(channel_id)
        if owner_id is None:
            return None
        return self._calls_by_owner.get(owner_id)

    def private_call_marker(self, owner_id: int) -> str:
        """Return the stable private-call marker for an owner.

        Discord voice channels do not expose a topic field in discord.py 2.4,
        so the marker remains a runtime identifier for future persistence.
        """

        return f"{PRIVATE_CALL_TOPIC_PREFIX}{owner_id}"

    async def get_or_create_private_call(
        self,
        *,
        member: discord.Member,
        hub_channel: discord.VoiceChannel,
    ) -> tuple[discord.VoiceChannel, bool]:
        """Return the member's active call or create a new temporary call.

        Returns:
            A tuple with the voice channel and whether it was newly created.
        """

        async with self.locks.user(member.id):
            active_channel = self._get_active_channel_for_owner(member)
            if active_channel is not None:
                return active_channel, False

            result = await rate_limiter.check(
                action=VOICE_CREATION_ACTION,
                user_id=member.id,
                guild_id=member.guild.id,
            )
            if not result.allowed:
                await self.database.log_rate_limit_hit(
                    action=result.action,
                    scope=result.scope,
                    retry_after=result.retry_after,
                    guild_id=member.guild.id,
                    user_id=member.id,
                )
                raise RateLimitExceeded(result)

            try:
                channel = await self._create_private_call(
                    member=member,
                    hub_channel=hub_channel,
                )
                self._register_call(
                    guild_id=member.guild.id,
                    owner_id=member.id,
                    channel_id=channel.id,
                )
                await self.database.upsert_voice_session(
                    guild_id=member.guild.id,
                    owner_id=member.id,
                    channel_id=channel.id,
                )
                await self.database.log_action(
                    action="create_private_voice_call",
                    success=True,
                    guild_id=member.guild.id,
                    user_id=member.id,
                )
            except Exception as exc:
                await self.database.log_action(
                    action="create_private_voice_call",
                    success=False,
                    guild_id=member.guild.id,
                    user_id=member.id,
                    error=type(exc).__name__,
                )
                raise

            logger.info(
                "Created private voice call %s for owner %s",
                channel.id,
                member.id,
            )
            return channel, True

    async def move_member_to_call(
        self,
        *,
        member: discord.Member,
        channel: discord.VoiceChannel,
    ) -> None:
        """Move a member to a private voice call."""

        await discord_api_queue.submit(
            action="move_private_voice_member",
            operation=lambda: safe_move_member(
                member,
                channel,
                reason="Movendo para call privada temporária",
            ),
        )

    async def delete_if_empty(self, channel: discord.VoiceChannel) -> bool:
        """Delete a managed private call if it has no connected members."""

        if not self.is_private_call(channel.id):
            return False

        current_channel = channel.guild.get_channel(channel.id)
        if current_channel is None:
            return await self.delete_call(
                channel=channel,
                reason="Call privada ausente no cache",
            )

        if not isinstance(current_channel, discord.VoiceChannel):
            return False

        if current_channel.members:
            return False

        return await self.delete_call(
            channel=current_channel, reason="Call privada vazia"
        )

    async def delete_call(
        self,
        *,
        channel: discord.VoiceChannel,
        reason: str,
    ) -> bool:
        """Delete a private call and remove it from runtime state."""

        owner_id = self._owner_by_channel.get(channel.id)
        if owner_id is None or not await self._mark_channel_deletion(channel.id):
            return False

        cleanup_state = False
        try:
            current_channel = channel.guild.get_channel(channel.id)
            if current_channel is None:
                cleanup_state = True
                logger.info(
                    "Private voice call %s is already absent from Discord cache",
                    channel.id,
                )
                return False

            deleted = await discord_api_queue.submit(
                action="delete_private_voice_call",
                operation=lambda: safe_delete_channel(current_channel, reason=reason),
            )
            cleanup_state = True
            return deleted
        except Exception as exc:
            await self.database.log_action(
                action="delete_private_voice_call",
                success=False,
                guild_id=channel.guild.id,
                user_id=owner_id,
                error=type(exc).__name__,
            )
            raise
        finally:
            if cleanup_state:
                try:
                    await self._cleanup_deleted_call(
                        channel=channel,
                        owner_id=owner_id,
                        reason=reason,
                    )
                finally:
                    await self._unmark_channel_deletion(channel.id)
            else:
                await self._unmark_channel_deletion(channel.id)

    async def set_user_limit(
        self,
        *,
        channel: discord.VoiceChannel,
        limit: int,
    ) -> None:
        """Set the private call user limit."""

        await discord_api_queue.submit(
            action="set_private_voice_user_limit",
            operation=lambda: safe_edit_voice_channel(
                channel,
                user_limit=limit,
                reason="Atualizando limite de usuários da call privada",
            ),
        )

    async def rename_call(
        self,
        *,
        channel: discord.VoiceChannel,
        name: str,
    ) -> None:
        """Rename the private voice call."""

        await discord_api_queue.submit(
            action="rename_private_voice_call",
            operation=lambda: safe_edit_voice_channel(
                channel,
                name=self.sanitize_channel_name(name),
                reason="Renomeando call privada",
            ),
        )

    async def toggle_visibility(
        self,
        *,
        channel: discord.VoiceChannel,
    ) -> bool:
        """Toggle whether the private call is visible and joinable by everyone."""

        state = self.get_call_state(channel.id)
        if state is None:
            msg = f"Private voice call state not found for channel {channel.id}"
            raise ValueError(msg)

        state.is_private = not state.is_private
        overwrite = channel.overwrites_for(channel.guild.default_role)
        overwrite.update(
            view_channel=not state.is_private,
            connect=not state.is_private,
        )

        await discord_api_queue.submit(
            action="toggle_private_voice_visibility",
            operation=lambda: safe_edit_channel_permissions(
                channel,
                channel.guild.default_role,
                overwrite=overwrite,
                reason="Atualizando visibilidade da call privada",
            ),
        )
        return state.is_private

    async def toggle_soundboard(
        self,
        *,
        channel: discord.VoiceChannel,
    ) -> bool:
        """Toggle the soundboard permission for the private call."""

        state = self.get_call_state(channel.id)
        if state is None:
            msg = f"Private voice call state not found for channel {channel.id}"
            raise ValueError(msg)

        state.soundboard_enabled = not state.soundboard_enabled
        await self._set_default_permission(
            channel=channel,
            permission_name="use_soundboard",
            enabled=state.soundboard_enabled,
            reason="Atualizando soundboard da call privada",
        )
        return state.soundboard_enabled

    async def toggle_screen_share(
        self,
        *,
        channel: discord.VoiceChannel,
    ) -> bool:
        """Toggle the screen share permission for the private call."""

        state = self.get_call_state(channel.id)
        if state is None:
            msg = f"Private voice call state not found for channel {channel.id}"
            raise ValueError(msg)

        state.screen_share_enabled = not state.screen_share_enabled
        await self._set_default_permission(
            channel=channel,
            permission_name="stream",
            enabled=state.screen_share_enabled,
            reason="Atualizando screen share da call privada",
        )
        return state.screen_share_enabled

    async def invite_member(
        self,
        *,
        owner: discord.Member,
        target: discord.Member,
        channel: discord.VoiceChannel,
        invite_view: discord.ui.View,
    ) -> bool:
        """Grant channel access and DM an invite to a member."""

        await self.grant_member_access(member=target, channel=channel)

        try:
            await discord_api_queue.submit(
                action="send_private_voice_invite_dm",
                operation=lambda: safe_send_dm(
                    target,
                    embed=build_private_voice_invite_embed(
                        owner=owner, channel=channel
                    ),
                    view=invite_view,
                ),
            )
        except discord.Forbidden:
            logger.info(
                "Could not DM private voice invite to member %s for channel %s",
                target.id,
                channel.id,
            )
            return False

        return True

    async def grant_member_access(
        self,
        *,
        member: discord.Member,
        channel: discord.VoiceChannel,
    ) -> None:
        """Allow an invited member to see and connect to a private call."""

        overwrite = channel.overwrites_for(member)
        overwrite.update(
            view_channel=True,
            connect=True,
            send_messages=True,
            read_message_history=True,
        )
        await discord_api_queue.submit(
            action="grant_private_voice_access",
            operation=lambda: safe_edit_channel_permissions(
                channel,
                member,
                overwrite=overwrite,
                reason="Convidando membro para call privada",
            ),
        )

    def sanitize_channel_name(self, name: str) -> str:
        """Return a valid Discord voice channel name."""

        sanitized_name = " ".join(name.strip().split())
        if not sanitized_name:
            sanitized_name = "Call Privada"
        return sanitized_name[:MAX_VOICE_CHANNEL_NAME_LENGTH]

    def build_private_call_name(self, member: discord.Member) -> str:
        """Return the configured private call name for a member."""

        display_name = self.sanitize_channel_name(member.display_name)
        return PRIVATE_CALL_NAME_TEMPLATE.format(display_name=display_name)

    def validate_user_limit(self, raw_limit: str) -> int:
        """Parse and validate a voice channel user limit."""

        try:
            limit = int(raw_limit.strip())
        except ValueError as exc:
            msg = "O limite precisa ser um número entre 0 e 99."
            raise ValueError(msg) from exc

        if limit < 0 or limit > MAX_VOICE_USER_LIMIT:
            msg = "O limite precisa ser um número entre 0 e 99."
            raise ValueError(msg)

        return limit

    def _get_active_channel_for_owner(
        self,
        member: discord.Member,
    ) -> discord.VoiceChannel | None:
        state = self._calls_by_owner.get(member.id)
        if state is None:
            return None

        channel = member.guild.get_channel(state.channel_id)
        if isinstance(channel, discord.VoiceChannel):
            return channel

        self._calls_by_owner.pop(member.id, None)
        self._owner_by_channel.pop(state.channel_id, None)
        return None

    async def _create_private_call(
        self,
        *,
        member: discord.Member,
        hub_channel: discord.VoiceChannel,
    ) -> discord.VoiceChannel:
        channel_name = self.build_private_call_name(member)
        return await discord_api_queue.submit(
            action="create_private_voice_call",
            operation=lambda: safe_create_voice_channel(
                member.guild,
                name=channel_name,
                category=hub_channel.category,
                overwrites=self._build_initial_overwrites(member),
                reason=f"Criando call privada temporária para {member.id}",
            ),
        )

    def _register_call(self, *, guild_id: int, owner_id: int, channel_id: int) -> None:
        self._calls_by_owner[owner_id] = PrivateVoiceCallState(
            guild_id=guild_id,
            owner_id=owner_id,
            channel_id=channel_id,
        )
        self._owner_by_channel[channel_id] = owner_id

    def _register_persisted_call(self, session: VoiceSession) -> None:
        self._calls_by_owner[session.owner_id] = PrivateVoiceCallState(
            guild_id=session.guild_id,
            owner_id=session.owner_id,
            channel_id=session.channel_id,
        )
        self._owner_by_channel[session.channel_id] = session.owner_id

    def _unregister_call(self, channel_id: int) -> None:
        owner_id = self._owner_by_channel.pop(channel_id, None)
        if owner_id is not None:
            self._calls_by_owner.pop(owner_id, None)

    async def _mark_channel_deletion(self, channel_id: int) -> bool:
        async with self._delete_lock:
            if channel_id in self._deleting_channel_ids:
                logger.info(
                    "Skipping duplicate private voice call deletion for %s",
                    channel_id,
                )
                return False

            if not self.is_private_call(channel_id):
                return False

            self._deleting_channel_ids.add(channel_id)
            return True

    async def _unmark_channel_deletion(self, channel_id: int) -> None:
        async with self._delete_lock:
            self._deleting_channel_ids.discard(channel_id)

    async def _cleanup_deleted_call(
        self,
        *,
        channel: discord.VoiceChannel,
        owner_id: int | None,
        reason: str,
    ) -> None:
        self._unregister_call(channel.id)
        await self.database.delete_voice_session_by_channel(channel.id)
        await self.database.log_action(
            action="delete_private_voice_call",
            success=True,
            guild_id=channel.guild.id,
            user_id=owner_id,
        )
        logger.info("Deleted private voice call %s: %s", channel.id, reason)

    def _build_initial_overwrites(
        self,
        member: discord.Member,
    ) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
            member.guild.default_role: discord.PermissionOverwrite(
                view_channel=False,
                connect=False,
            ),
            member: discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                speak=True,
                send_messages=True,
                read_message_history=True,
            ),
        }

        bot_member = member.guild.me
        if bot_member is not None:
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                manage_channels=True,
                move_members=True,
                connect=True,
                speak=True,
                send_messages=True,
                read_message_history=True,
            )

        return overwrites

    async def _set_default_permission(
        self,
        *,
        channel: discord.VoiceChannel,
        permission_name: str,
        enabled: bool,
        reason: str,
    ) -> None:
        overwrite = channel.overwrites_for(channel.guild.default_role)
        overwrite.update(**{permission_name: None if enabled else False})
        await discord_api_queue.submit(
            action=f"set_private_voice_permission:{permission_name}",
            operation=lambda: safe_edit_channel_permissions(
                channel,
                channel.guild.default_role,
                overwrite=overwrite,
                reason=reason,
            ),
        )
