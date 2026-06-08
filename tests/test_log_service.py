"""Tests for the rich TARS log service."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from bot.database.models.core_models import DashboardConfigModel, LogConfigModel
from bot.database.models.log_models import (
    LogCategory,
    LogEventCreate,
    LogEventFilters,
)
from bot.services.core_config_service import CoreConfigService
from bot.services.log_service import LogService


def test_log_service_persists_filters_and_exports(tmp_path: Path) -> None:
    """Ensure rich log events are stored, searchable and exportable."""

    database_path = tmp_path / "tars.sqlite3"
    config_service = CoreConfigService(database_path)
    service = LogService(database_path, config_service=config_service)
    asyncio.run(
        config_service.save_config_from_dashboard(
            DashboardConfigModel(
                guild_id=123,
                owner_user_id=42,
                logs=LogConfigModel(
                    channel_id=999,
                    persist_message_content=True,
                ),
            ),
            actor_user_id=42,
        ),
    )

    event = asyncio.run(
        service.emit(
            guild=None,
            event=LogEventCreate(
                guild_id=123,
                category=LogCategory.MESSAGE,
                event_type="message_delete",
                title="Mensagem deletada",
                description="Mensagem de teste removida.",
                actor_user_id=7,
                target_user_id=8,
                channel_id=9,
                message_id=10,
                payload={"content": "conteúdo removido"},
            ),
        ),
    )
    events = asyncio.run(
        service.list_events(
            LogEventFilters(guild_id=123, query="removida", user_id=8),
        ),
    )
    csv_text = asyncio.run(service.export_events_csv(LogEventFilters(guild_id=123)))

    assert event is not None
    assert events[0].event_type == "message_delete"
    assert events[0].payload["content"] == "conteúdo removido"
    assert "message_delete" in csv_text
    assert "conteúdo removido" in csv_text


def test_log_service_respects_disabled_events_and_content_policy(
    tmp_path: Path,
) -> None:
    """Ensure disabled events are skipped and content can be redacted."""

    database_path = tmp_path / "tars.sqlite3"
    config_service = CoreConfigService(database_path)
    service = LogService(database_path, config_service=config_service)
    asyncio.run(
        config_service.save_config_from_dashboard(
            DashboardConfigModel(
                guild_id=123,
                owner_user_id=42,
                logs=LogConfigModel(
                    enabled_event_types=("message_delete",),
                    persist_message_content=False,
                ),
            ),
            actor_user_id=42,
        ),
    )

    skipped = asyncio.run(
        service.emit(
            guild=None,
            event=LogEventCreate(
                guild_id=123,
                category=LogCategory.MESSAGE,
                event_type="message_edit",
                title="Mensagem editada",
                description="Não deve entrar.",
                payload={"before_content": "antes", "after_content": "depois"},
            ),
        ),
    )
    stored = asyncio.run(
        service.emit(
            guild=None,
            event=LogEventCreate(
                guild_id=123,
                category=LogCategory.MESSAGE,
                event_type="message_delete",
                title="Mensagem deletada",
                description="Deve entrar.",
                payload={"content": "segredo"},
            ),
        ),
    )
    events = asyncio.run(service.list_events(LogEventFilters(guild_id=123)))

    assert skipped is None
    assert stored is not None
    assert len(events) == 1
    assert events[0].payload["content"] == "[conteúdo não persistido]"
