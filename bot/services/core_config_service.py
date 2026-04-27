"""Dashboard-backed configuration persistence for core server features."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bot.config import settings
from bot.database.models.core_models import DashboardConfigModel
from bot.logger import logger

CORE_CONFIG_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS core_guild_configs (
        guild_id INTEGER PRIMARY KEY,
        owner_user_id INTEGER NOT NULL,
        config_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS core_audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        actor_user_id INTEGER,
        target_user_id INTEGER,
        event_type TEXT NOT NULL,
        detail_level INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_core_audit_events_guild_created
    ON core_audit_events (guild_id, created_at)
    """,
)


class DashboardAccessDeniedError(PermissionError):
    """Raised when a non-owner attempts to alter Dashboard configuration."""


class CoreConfigService:
    """Load, validate and persist Dashboard-owned guild configuration."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        """Initialize the service."""

        self.database_path = Path(database_path or settings.database_path)
        self._init_lock: asyncio.Lock | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Create required core tables once."""

        if self._init_lock is None:
            self._init_lock = asyncio.Lock()

        async with self._init_lock:
            if self._initialized:
                return

            await asyncio.to_thread(self._initialize_sync)
            self._initialized = True

    async def get_config(self, guild_id: int) -> DashboardConfigModel:
        """Return the Dashboard configuration for a guild."""

        await self.initialize()
        row = await asyncio.to_thread(
            self._fetch_one,
            """
            SELECT config_json
            FROM core_guild_configs
            WHERE guild_id = ?
            """,
            (guild_id,),
        )
        if row is None:
            return DashboardConfigModel.default(
                guild_id=guild_id,
                owner_user_id=settings.tars_owner_user_id,
            )

        payload = json.loads(str(row["config_json"]))
        return DashboardConfigModel.from_dict(payload)

    async def save_config_from_dashboard(
        self,
        config: DashboardConfigModel,
        *,
        actor_user_id: int,
    ) -> None:
        """Persist a complete Dashboard configuration atomically.

        Args:
            config: Full replacement configuration submitted by the Dashboard.
            actor_user_id: Discord user ID that submitted the change.

        Raises:
            DashboardAccessDeniedError: If the actor is not the configured owner.
        """

        await self.initialize()
        configured_owner_id = config.owner_user_id or settings.tars_owner_user_id
        if configured_owner_id and actor_user_id != configured_owner_id:
            msg = "Apenas o dono configurado pode alterar a Dashboard."
            raise DashboardAccessDeniedError(msg)

        updated_at = datetime.now(tz=timezone.utc)  # noqa: UP017
        payload = {
            **config.to_dict(),
            "owner_user_id": configured_owner_id,
            "updated_at": updated_at.isoformat(),
        }
        audit_payload = {
            "message": (
                "Configuração do Core alterada por Dono em "
                f"{updated_at.date().isoformat()}"
            ),
            "changed_by": actor_user_id,
        }
        await asyncio.to_thread(
            self._save_config_transaction_sync,
            config.guild_id,
            configured_owner_id,
            actor_user_id,
            json.dumps(payload, ensure_ascii=False),
            updated_at.isoformat(),
            json.dumps(audit_payload, ensure_ascii=False),
        )
        logger.info(
            "Core Dashboard config updated guild_id=%s actor_user_id=%s",
            config.guild_id,
            actor_user_id,
        )

    async def record_audit_event(
        self,
        *,
        guild_id: int,
        event_type: str,
        detail_level: int,
        payload: dict[str, Any],
        actor_user_id: int | None = None,
        target_user_id: int | None = None,
    ) -> None:
        """Persist an internal audit event for Dashboard search/export."""

        await self.initialize()
        await asyncio.to_thread(
            self._execute,
            """
            INSERT INTO core_audit_events (
                guild_id,
                actor_user_id,
                target_user_id,
                event_type,
                detail_level,
                payload_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                actor_user_id,
                target_user_id,
                event_type,
                detail_level,
                json.dumps(payload, ensure_ascii=False),
                datetime.now(tz=timezone.utc).isoformat(),  # noqa: UP017
            ),
        )

    async def list_dashboard_audit_events(
        self,
        *,
        guild_id: int,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return detailed audit events for the Dashboard."""

        await self.initialize()
        rows = await asyncio.to_thread(
            self._fetch_all,
            """
            SELECT id, guild_id, actor_user_id, target_user_id, event_type,
                   detail_level, payload_json, created_at
            FROM core_audit_events
            WHERE guild_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (guild_id, limit),
        )
        return [
            {
                "id": int(row["id"]),
                "guild_id": int(row["guild_id"]),
                "actor_user_id": row["actor_user_id"],
                "target_user_id": row["target_user_id"],
                "event_type": str(row["event_type"]),
                "detail_level": int(row["detail_level"]),
                "payload": json.loads(str(row["payload_json"])),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def _initialize_sync(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path) as connection:
            for statement in CORE_CONFIG_SCHEMA:
                connection.execute(statement)
            connection.commit()

    def _save_config_transaction_sync(
        self,
        guild_id: int,
        owner_user_id: int,
        updated_by: int,
        config_json: str,
        updated_at: str,
        audit_payload_json: str,
    ) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("BEGIN")
            connection.execute(
                """
                INSERT INTO core_guild_configs (
                    guild_id,
                    owner_user_id,
                    config_json,
                    updated_at,
                    updated_by
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    owner_user_id = excluded.owner_user_id,
                    config_json = excluded.config_json,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (guild_id, owner_user_id, config_json, updated_at, updated_by),
            )
            connection.execute(
                """
                INSERT INTO core_audit_events (
                    guild_id,
                    actor_user_id,
                    target_user_id,
                    event_type,
                    detail_level,
                    payload_json,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    updated_by,
                    None,
                    "dashboard_config_updated",
                    3,
                    audit_payload_json,
                    updated_at,
                ),
            )
            connection.commit()

    def _execute(self, query: str, params: Iterable[Any]) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(query, tuple(params))
            connection.commit()

    def _fetch_one(
        self,
        query: str,
        params: Iterable[Any],
    ) -> sqlite3.Row | None:
        rows = self._fetch_all(query, params)
        return rows[0] if rows else None

    def _fetch_all(
        self,
        query: str,
        params: Iterable[Any],
    ) -> list[sqlite3.Row]:
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            cursor = connection.execute(query, tuple(params))
            return list(cursor.fetchall())


core_config_service = CoreConfigService()
