"""Central rich logging service for Discord and Dashboard audit logs."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import discord

from bot.config import settings
from bot.database.models.core_models import LogConfigModel, LogDetailLevel
from bot.database.models.log_models import (
    LogCategory,
    LogEventCreate,
    LogEventFilters,
    LogEventModel,
)
from bot.logger import logger
from bot.services.core_config_service import CoreConfigService, core_config_service
from bot.utils.queue_manager import discord_api_queue
from bot.utils.safe_discord import safe_send_message

LOG_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS log_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        event_type TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        detail_level INTEGER NOT NULL,
        actor_user_id INTEGER,
        target_user_id INTEGER,
        channel_id INTEGER,
        message_id INTEGER,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_log_events_guild_created
    ON log_events (guild_id, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_log_events_guild_category_created
    ON log_events (guild_id, category, created_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_log_events_guild_event_created
    ON log_events (guild_id, event_type, created_at)
    """,
)

LOG_FOOTER = "Feito com TARS"
WEBHOOK_NAME = "TARS Logs"
MAX_FIELD_VALUE_LENGTH = 1024
MAX_DESCRIPTION_LENGTH = 4000


class LogService:
    """Persist and dispatch rich TARS log events."""

    def __init__(
        self,
        database_path: str | Path | None = None,
        config_service: CoreConfigService | None = None,
    ) -> None:
        """Initialize the service."""

        self.database_path = Path(database_path or settings.database_path)
        self.config_service = config_service or (
            CoreConfigService(self.database_path)
            if database_path is not None
            else core_config_service
        )
        self._init_lock: asyncio.Lock | None = None
        self._initialized = False
        self._webhooks: dict[int, discord.Webhook] = {}

    async def initialize(self) -> None:
        """Create the rich log tables once."""

        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            if self._initialized:
                return
            await asyncio.to_thread(self._initialize_sync)
            self._initialized = True

    async def emit(
        self,
        *,
        guild: discord.Guild | None,
        event: LogEventCreate,
    ) -> LogEventModel | None:
        """Persist and optionally send a rich log event to Discord."""

        await self.initialize()
        config = await self.config_service.get_config(event.guild_id)
        if event.event_type not in config.logs.enabled_event_types:
            return None

        normalized = self._normalize_event(event, config.logs)
        row = await asyncio.to_thread(self._insert_event_sync, normalized)
        model = _row_to_event(row)
        await self._prune_expired(guild_id=event.guild_id, config=config.logs)

        if guild is not None and normalized.detail_level <= int(
            config.logs.detail_level
        ):
            await self._dispatch(guild=guild, event=normalized, config=config.logs)

        return model

    async def list_events(self, filters: LogEventFilters) -> list[LogEventModel]:
        """Return rich log events matching Dashboard filters."""

        await self.initialize()
        where = ["guild_id = ?"]
        params: list[Any] = [filters.guild_id]

        if filters.category:
            where.append("category = ?")
            params.append(filters.category)
        if filters.event_type:
            where.append("event_type = ?")
            params.append(filters.event_type)
        if filters.user_id is not None:
            where.append("(actor_user_id = ? OR target_user_id = ?)")
            params.extend([filters.user_id, filters.user_id])
        if filters.actor_user_id is not None:
            where.append("actor_user_id = ?")
            params.append(filters.actor_user_id)
        if filters.channel_id is not None:
            where.append("channel_id = ?")
            params.append(filters.channel_id)
        if filters.query:
            where.append(
                "(title LIKE ? OR description LIKE ? OR payload_json LIKE ?)",
            )
            search = f"%{filters.query}%"
            params.extend([search, search, search])

        params.append(max(1, min(filters.limit, 500)))
        rows = await asyncio.to_thread(
            self._fetch_all,
            f"""
            SELECT *
            FROM log_events
            WHERE {" AND ".join(where)}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        )
        return [_row_to_event(row) for row in rows]

    async def export_events_csv(self, filters: LogEventFilters) -> str:
        """Export filtered log events as CSV text."""

        events = await self.list_events(
            LogEventFilters(
                guild_id=filters.guild_id,
                query=filters.query,
                category=filters.category,
                event_type=filters.event_type,
                user_id=filters.user_id,
                actor_user_id=filters.actor_user_id,
                channel_id=filters.channel_id,
                limit=500,
            ),
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "id",
                "guild_id",
                "category",
                "event_type",
                "actor_user_id",
                "target_user_id",
                "channel_id",
                "message_id",
                "title",
                "description",
                "created_at",
                "payload_json",
            ],
        )
        for event in events:
            writer.writerow(
                [
                    event.id,
                    event.guild_id,
                    event.category.value,
                    event.event_type,
                    event.actor_user_id or "",
                    event.target_user_id or "",
                    event.channel_id or "",
                    event.message_id or "",
                    event.title,
                    event.description,
                    event.created_at.isoformat(),
                    json.dumps(event.payload, ensure_ascii=False),
                ],
            )
        return buffer.getvalue()

    async def record_system_event(
        self,
        *,
        guild: discord.Guild | None,
        guild_id: int,
        event_type: str,
        title: str,
        description: str,
        payload: dict[str, Any],
        actor_user_id: int | None = None,
        target_user_id: int | None = None,
        category: LogCategory = LogCategory.SYSTEM,
        color: int | None = None,
    ) -> LogEventModel | None:
        """Convenience wrapper for internal system integrations."""

        return await self.emit(
            guild=guild,
            event=LogEventCreate(
                guild_id=guild_id,
                category=category,
                event_type=event_type,
                title=title,
                description=description,
                detail_level=int(LogDetailLevel.NORMAL),
                actor_user_id=actor_user_id,
                target_user_id=target_user_id,
                payload=payload,
                color=color,
            ),
        )

    def should_ignore_member(
        self,
        member: discord.Member | discord.User,
        config: LogConfigModel,
    ) -> bool:
        """Return whether a member should be skipped by log filters."""

        if config.ignore_bots and member.bot:
            return True
        roles = getattr(member, "roles", ())
        role_ids = {role.id for role in roles}
        return bool(role_ids.intersection(config.ignored_role_ids))

    async def should_ignore_message(self, message: discord.Message) -> bool:
        """Return whether a message should be skipped by log filters."""

        if message.guild is None:
            return True
        config = (await self.config_service.get_config(message.guild.id)).logs
        if message.channel.id in config.ignored_channel_ids:
            return True
        author = message.author
        if isinstance(author, discord.Member | discord.User):
            return self.should_ignore_member(author, config)
        return False

    def _normalize_event(
        self,
        event: LogEventCreate,
        config: LogConfigModel,
    ) -> LogEventCreate:
        payload = dict(event.payload)
        if not config.persist_message_content:
            for key in ("content", "before_content", "after_content"):
                if key in payload:
                    payload[key] = "[conteúdo não persistido]"

        return LogEventCreate(
            guild_id=event.guild_id,
            category=event.category,
            event_type=event.event_type,
            title=event.title,
            description=_truncate(event.description, MAX_DESCRIPTION_LENGTH),
            detail_level=event.detail_level,
            actor_user_id=event.actor_user_id,
            target_user_id=event.target_user_id,
            channel_id=event.channel_id,
            message_id=event.message_id,
            payload=payload,
            color=event.color,
            thumbnail_url=event.thumbnail_url,
            image_url=event.image_url,
        )

    async def _dispatch(
        self,
        *,
        guild: discord.Guild,
        event: LogEventCreate,
        config: LogConfigModel,
    ) -> None:
        channel = self._resolve_log_channel(guild, event.category, config)
        if channel is None:
            logger.warning("No rich log channel available guild_id=%s", guild.id)
            return

        embed = self._build_embed(event)
        if config.webhooks_enabled and isinstance(channel, discord.TextChannel):
            try:
                await discord_api_queue.submit(
                    action="send_rich_log_webhook",
                    operation=lambda: self._send_with_webhook(channel, embed),
                )
                return
            except discord.HTTPException:
                logger.exception(
                    "Failed to send rich log through webhook guild_id=%s channel_id=%s",
                    guild.id,
                    channel.id,
                )

        await discord_api_queue.submit(
            action="send_rich_log",
            operation=lambda: safe_send_message(
                channel,
                embed=embed,
                reason="send_rich_log",
            ),
        )

    async def _send_with_webhook(
        self,
        channel: discord.TextChannel,
        embed: discord.Embed,
    ) -> None:
        webhook = self._webhooks.get(channel.id)
        if webhook is None:
            webhooks = await channel.webhooks()
            webhook = next(
                (item for item in webhooks if item.name == WEBHOOK_NAME),
                None,
            )
            if webhook is None:
                webhook = await channel.create_webhook(
                    name=WEBHOOK_NAME,
                    reason="Webhooks internos para logs do TARS",
                )
            self._webhooks[channel.id] = webhook

        await webhook.send(
            embed=embed,
            username=WEBHOOK_NAME,
            wait=True,
        )

    def _resolve_log_channel(
        self,
        guild: discord.Guild,
        category: LogCategory,
        config: LogConfigModel,
    ) -> discord.TextChannel | discord.Thread | None:
        category_channel_id = {
            LogCategory.MODERATION: config.moderation_channel_id,
            LogCategory.MEMBER: config.member_channel_id,
            LogCategory.MESSAGE: config.message_channel_id,
            LogCategory.PROFILE: config.profile_channel_id,
            LogCategory.VOICE: config.voice_channel_id,
            LogCategory.SYSTEM: config.system_channel_id,
            LogCategory.XP_ECONOMY: config.xp_economy_channel_id,
        }[category]
        for channel_id in (category_channel_id, config.channel_id):
            if channel_id is None:
                continue
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel | discord.Thread):
                return channel
        return None

    def _build_embed(self, event: LogEventCreate) -> discord.Embed:
        color = event.color or _default_color(event.category, event.event_type)
        embed = discord.Embed(
            title=event.title,
            description=event.description,
            color=discord.Color(color),
            timestamp=datetime.now(tz=timezone.utc),  # noqa: UP017
        )
        if event.thumbnail_url:
            embed.set_thumbnail(url=event.thumbnail_url)
        if event.image_url:
            embed.set_image(url=event.image_url)

        fields = _payload_fields(event.payload)
        id_fields = {
            "Usuário alvo": _mention_or_id(event.target_user_id),
            "Executor": _mention_or_id(event.actor_user_id),
            "Canal": f"<#{event.channel_id}>" if event.channel_id else None,
            "ID da mensagem": str(event.message_id) if event.message_id else None,
            "Evento": event.event_type,
        }
        for name, value in [*id_fields.items(), *fields]:
            if value in (None, ""):
                continue
            embed.add_field(
                name=name,
                value=_truncate(str(value), MAX_FIELD_VALUE_LENGTH),
                inline=True,
            )

        embed.set_footer(text=LOG_FOOTER)
        return embed

    async def _prune_expired(
        self,
        *,
        guild_id: int,
        config: LogConfigModel,
    ) -> None:
        cutoff = datetime.now(tz=UTC) - timedelta(days=config.retention_days)
        await asyncio.to_thread(
            self._execute,
            """
            DELETE FROM log_events
            WHERE guild_id = ? AND created_at < ?
            """,
            (guild_id, cutoff.isoformat()),
        )

    def _initialize_sync(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            for statement in LOG_SCHEMA:
                connection.execute(statement)
            connection.commit()

    def _insert_event_sync(self, event: LogEventCreate) -> sqlite3.Row:
        created_at = datetime.now(tz=timezone.utc).isoformat()  # noqa: UP017
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(
                """
                INSERT INTO log_events (
                    guild_id,
                    category,
                    event_type,
                    title,
                    description,
                    detail_level,
                    actor_user_id,
                    target_user_id,
                    channel_id,
                    message_id,
                    payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.guild_id,
                    event.category.value,
                    event.event_type,
                    event.title,
                    event.description,
                    event.detail_level,
                    event.actor_user_id,
                    event.target_user_id,
                    event.channel_id,
                    event.message_id,
                    json.dumps(event.payload, ensure_ascii=False),
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM log_events WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            connection.commit()
            if row is None:
                msg = "Inserted log event could not be fetched."
                raise RuntimeError(msg)
            return cast(sqlite3.Row, row)

    def _execute(self, query: str, params: Iterable[Any]) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(query, tuple(params))
            connection.commit()

    def _fetch_all(
        self,
        query: str,
        params: Iterable[Any],
    ) -> list[sqlite3.Row]:
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(query, tuple(params))
            return list(cursor.fetchall())


def _row_to_event(row: sqlite3.Row) -> LogEventModel:
    return LogEventModel(
        id=int(row["id"]),
        guild_id=int(row["guild_id"]),
        category=LogCategory(str(row["category"])),
        event_type=str(row["event_type"]),
        title=str(row["title"]),
        description=str(row["description"]),
        detail_level=int(row["detail_level"]),
        actor_user_id=_optional_row_int(row["actor_user_id"]),
        target_user_id=_optional_row_int(row["target_user_id"]),
        channel_id=_optional_row_int(row["channel_id"]),
        message_id=_optional_row_int(row["message_id"]),
        payload=json.loads(str(row["payload_json"])),
        created_at=datetime.fromisoformat(str(row["created_at"])),
    )


def _payload_fields(payload: dict[str, Any]) -> list[tuple[str, str]]:
    visible: list[tuple[str, str]] = []
    labels = {
        "before": "Antes",
        "after": "Depois",
        "content": "Conteúdo",
        "before_content": "Antes",
        "after_content": "Depois",
        "reason": "Motivo",
        "invite_code": "Convite",
        "attachment_urls": "Anexos",
    }
    for key, label in labels.items():
        if key not in payload or payload[key] in (None, "", []):
            continue
        value = payload[key]
        if isinstance(value, list | tuple):
            value = "\n".join(str(item) for item in value)
        visible.append((label, str(value)))
    return visible


def _default_color(category: LogCategory, event_type: str) -> int:
    if category == LogCategory.SYSTEM:
        return 0x9B59B6
    if category == LogCategory.XP_ECONOMY:
        return 0x2ECC71
    if event_type.endswith(("join", "unban", "level_up")):
        return 0x2ECC71
    if any(word in event_type for word in ("delete", "leave", "ban", "kick")):
        return 0xE74C3C
    if any(word in event_type for word in ("edit", "timeout", "mute", "deafen")):
        return 0xF1C40F
    return 0x3498DB


def _mention_or_id(user_id: int | None) -> str | None:
    if user_id is None:
        return None
    return f"<@{user_id}>\n`{user_id}`"


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _optional_row_int(value: object) -> int | None:
    if value is None:
        return None
    return int(str(value))


log_service = LogService()
