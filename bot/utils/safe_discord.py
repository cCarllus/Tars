"""Safe wrappers for Discord API operations."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any, TypeVar

import discord

from bot.logger import logger

DEFAULT_RETRIES = 4
DEFAULT_TIMEOUT_SECONDS = 12.0
BASE_BACKOFF_SECONDS = 0.5
MAX_BACKOFF_SECONDS = 8.0

T = TypeVar("T")


async def safe_send_message(
    channel: discord.abc.Messageable,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    reason: str = "send_message",
) -> discord.Message:
    """Send a message with retry, timeout and latency logging."""

    kwargs: dict[str, Any] = {}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view

    return await _run_discord_operation(
        action=reason,
        operation=lambda: channel.send(**kwargs),
    )


async def safe_create_voice_channel(
    guild: discord.Guild,
    *,
    name: str,
    category: discord.CategoryChannel | None,
    overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite],
    reason: str,
) -> discord.VoiceChannel:
    """Create a voice channel with retry, timeout and latency logging."""

    return await _run_discord_operation(
        action="create_voice_channel",
        operation=lambda: guild.create_voice_channel(
            name=name,
            category=category,
            overwrites=overwrites,
            reason=reason,
        ),
        guild_id=guild.id,
    )


async def safe_move_member(
    member: discord.Member,
    channel: discord.VoiceChannel | None,
    *,
    reason: str,
) -> None:
    """Move a member with retry, timeout and latency logging."""

    await _run_discord_operation(
        action="move_member",
        operation=lambda: member.move_to(channel, reason=reason),
        guild_id=member.guild.id,
        user_id=member.id,
    )


async def safe_edit_channel_permissions(
    channel: discord.abc.GuildChannel,
    target: discord.Role | discord.Member,
    *,
    overwrite: discord.PermissionOverwrite,
    reason: str,
) -> None:
    """Edit channel permissions with retry, timeout and latency logging."""

    await _run_discord_operation(
        action="edit_channel_permissions",
        operation=lambda: channel.set_permissions(
            target,
            overwrite=overwrite,
            reason=reason,
        ),
        guild_id=channel.guild.id,
    )


async def safe_edit_voice_channel(
    channel: discord.VoiceChannel,
    *,
    name: str | None = None,
    user_limit: int | None = None,
    reason: str,
) -> None:
    """Edit voice channel metadata with retry, timeout and latency logging."""

    if name is None and user_limit is None:
        return

    operation: Callable[[], Awaitable[Any]]
    if name is not None and user_limit is not None:

        def operation() -> Awaitable[Any]:
            return channel.edit(name=name, user_limit=user_limit, reason=reason)

    elif name is not None:

        def operation() -> Awaitable[Any]:
            return channel.edit(name=name, reason=reason)

    else:
        assert user_limit is not None

        def operation() -> Awaitable[Any]:
            return channel.edit(user_limit=user_limit, reason=reason)

    await _run_discord_operation(
        action="edit_voice_channel",
        operation=operation,
        guild_id=channel.guild.id,
    )


async def safe_delete_channel(
    channel: discord.abc.GuildChannel,
    *,
    reason: str,
) -> bool:
    """Delete a channel with retry, timeout and latency logging."""

    async def operation() -> bool:
        try:
            await channel.delete(reason=reason)
        except discord.NotFound as exc:
            if _is_unknown_channel(exc):
                logger.info(
                    "Discord channel %s already deleted; treating delete as success",
                    channel.id,
                )
                return False
            raise
        return True

    return await _run_discord_operation(
        action="delete_channel",
        operation=operation,
        guild_id=channel.guild.id,
    )


async def safe_send_dm(
    member: discord.Member,
    *,
    content: str | None = None,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
) -> discord.Message:
    """Send a direct message with retry, timeout and latency logging."""

    kwargs: dict[str, Any] = {}
    if content is not None:
        kwargs["content"] = content
    if embed is not None:
        kwargs["embed"] = embed
    if view is not None:
        kwargs["view"] = view

    return await _run_discord_operation(
        action="send_dm",
        operation=lambda: member.send(**kwargs),
        guild_id=member.guild.id,
        user_id=member.id,
    )


async def safe_add_role(
    member: discord.Member,
    role: discord.Role,
    *,
    reason: str,
) -> None:
    """Assign a role with retry, timeout and latency logging."""

    await _run_discord_operation(
        action="add_role",
        operation=lambda: member.add_roles(role, reason=reason),
        guild_id=member.guild.id,
        user_id=member.id,
    )


async def safe_delete_message(
    message: discord.Message,
    *,
    reason: str,
) -> bool:
    """Delete a message with retry, timeout and latency logging."""

    async def operation() -> bool:
        try:
            await message.delete()
        except discord.NotFound as exc:
            if _is_unknown_message(exc):
                logger.info(
                    "Discord message %s already deleted; treating delete as success",
                    message.id,
                )
                return False
            raise
        return True

    return await _run_discord_operation(
        action=reason,
        operation=operation,
        guild_id=message.guild.id if message.guild else None,
        user_id=message.author.id if message.author else None,
    )


async def _run_discord_operation(
    *,
    action: str,
    operation: Callable[[], Awaitable[T]],
    guild_id: int | None = None,
    user_id: int | None = None,
    retries: int = DEFAULT_RETRIES,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> T:
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        started = monotonic()
        try:
            result = await asyncio.wait_for(operation(), timeout=timeout_seconds)
        except discord.RateLimited as exc:
            last_error = exc
            await _sleep_before_retry(exc.retry_after, attempt=attempt, action=action)
        except (TimeoutError, discord.HTTPException) as exc:
            last_error = exc
            if attempt >= retries or not _can_retry(exc):
                _log_operation_failure(
                    action=action,
                    guild_id=guild_id,
                    user_id=user_id,
                    duration_ms=_duration_ms(started),
                    exc=exc,
                )
                raise
            await _sleep_before_retry(None, attempt=attempt, action=action)
        else:
            logger.info(
                "Discord API action=%s success=True guild_id=%s user_id=%s "
                "duration_ms=%.2f",
                action,
                guild_id,
                user_id,
                _duration_ms(started),
            )
            return result

    if last_error is None:
        msg = f"Discord operation {action} failed without an exception"
        raise RuntimeError(msg)

    raise last_error


def _can_retry(exc: Exception) -> bool:
    if isinstance(exc, asyncio.TimeoutError):
        return True

    if isinstance(exc, discord.HTTPException):
        status = getattr(exc, "status", None)
        return status is None or status == 429 or status >= 500

    return False


def _is_unknown_channel(exc: discord.NotFound) -> bool:
    return getattr(exc, "code", None) == 10003


def _is_unknown_message(exc: discord.NotFound) -> bool:
    return getattr(exc, "code", None) == 10008


async def _sleep_before_retry(
    retry_after: float | None,
    *,
    attempt: int,
    action: str,
) -> None:
    if retry_after is None:
        retry_after = min(
            MAX_BACKOFF_SECONDS,
            BASE_BACKOFF_SECONDS * (2 ** max(0, attempt - 1)),
        )

    delay = retry_after + random.uniform(0.0, 0.25)
    logger.warning(
        "Retrying Discord API action=%s attempt=%s delay=%.2f",
        action,
        attempt,
        delay,
    )
    await asyncio.sleep(delay)


def _log_operation_failure(
    *,
    action: str,
    guild_id: int | None,
    user_id: int | None,
    duration_ms: float,
    exc: Exception,
) -> None:
    logger.error(
        "Discord API action=%s success=False guild_id=%s user_id=%s "
        "duration_ms=%.2f error=%s",
        action,
        guild_id,
        user_id,
        duration_ms,
        type(exc).__name__,
        exc_info=True,
    )


def _duration_ms(started: float) -> float:
    return (monotonic() - started) * 1000
