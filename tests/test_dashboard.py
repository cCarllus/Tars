"""Tests for the private Flask Dashboard."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from bot.config import settings
from bot.database.models.ticket_models import TicketType
from bot.services.core_config_service import CoreConfigService
from bot.services.leveling_service import LevelingService
from bot.services.ticket_service import TicketService
from bot.services.xp_service import XPService
from dashboard.app import create_app


def test_dashboard_requires_owner_session(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Ensure unauthenticated users cannot view the Dashboard."""

    _configure_dashboard_settings(monkeypatch)
    app = create_app(CoreConfigService(tmp_path / "tars.sqlite3"))
    app.config.update(TESTING=True)

    response = app.test_client().get("/dashboard")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")

    client = app.test_client()
    _authenticate_client(client)
    authenticated_response = client.get("/dashboard")

    assert authenticated_response.status_code == 200
    assert b"TARS Dashboard" in authenticated_response.data


def test_dashboard_saves_config_through_core_service(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Ensure Dashboard form submissions persist the shared bot config."""

    _configure_dashboard_settings(monkeypatch)
    database_path = tmp_path / "tars.sqlite3"
    service = CoreConfigService(database_path)
    app = create_app(service)
    app.config.update(TESTING=True)
    client = app.test_client()
    _authenticate_client(client)

    response = client.post("/dashboard", data=_dashboard_payload())

    loaded = asyncio.run(service.get_config(123))
    audit_events = asyncio.run(service.list_dashboard_audit_events(guild_id=123))

    assert response.status_code == 302
    assert loaded.welcome.channel_id == 10
    assert loaded.welcome.message_template == "Olá {member}, bem-vindo ao {server}."
    assert loaded.leave.enabled is False
    assert loaded.logs.channel_id == 11
    assert int(loaded.logs.detail_level) == 3
    assert loaded.auto_role.role_id == 12
    assert loaded.auto_mod.block_links is False
    assert loaded.auto_mod.allowed_links == ()
    assert loaded.auto_mod.blocked_words == ("spam", "phishing")
    assert loaded.leveling.message_xp == 25
    assert loaded.leveling.level_xp_factor == 200
    assert loaded.leveling.levelup_channel_id == 44
    assert loaded.leveling.levelup_enabled is True
    assert loaded.leveling.levelup_mention is False
    assert loaded.leveling.levelup_message == "{user} subiu para {level} com {xp} XP."
    assert loaded.leveling.xp_owner_user_id == 399757244138520576
    assert loaded.leveling.xp_staff_role_ids == (987654321, 123456789)
    assert loaded.leveling.staff_max_set_level == 15
    assert loaded.leveling.staff_max_xp_per_command == 5000
    assert loaded.tickets.triage_channel_id == 30
    assert loaded.tickets.staff_role_ids == (31, 32)
    assert loaded.tickets.judge_role_ids == (31, 32)
    assert loaded.tickets.admin_role_ids == ()
    assert loaded.tickets.create_voice_channel is False
    assert loaded.tickets.tribunal_majority_votes == 2
    assert loaded.tickets.rate_limit_ticket_count == 2
    assert loaded.tickets.rate_limit_window_seconds == 3600
    assert loaded.tickets.transcript_channel_id == 33
    assert loaded.tickets.dm_notifications_enabled is True
    assert audit_events[0]["event_type"] == "dashboard_config_updated"


def test_leveling_service_reads_dashboard_xp_config(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Ensure XP gains use values saved by the Dashboard."""

    _configure_dashboard_settings(monkeypatch)
    database_path = tmp_path / "tars.sqlite3"
    config_service = CoreConfigService(database_path)
    app = create_app(config_service)
    app.config.update(TESTING=True)
    client = app.test_client()
    _authenticate_client(client)
    client.post("/dashboard", data=_dashboard_payload())

    leveling = LevelingService(database_path, config_service=config_service)
    record = asyncio.run(
        leveling.add_message_xp(
            guild_id=123,
            user_id=7,
            created_at=datetime.now(tz=timezone.utc),  # noqa: UP017
        ),
    )

    assert record is not None
    assert record.xp == 25
    assert record.level == 0


def test_levels_dashboard_saves_levelup_settings(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Ensure the Levels page persists dedicated level-up announcement settings."""

    _configure_dashboard_settings(monkeypatch)
    database_path = tmp_path / "tars.sqlite3"
    config_service = CoreConfigService(database_path)
    levels_service = XPService(database_path, config_service=config_service)
    app = create_app(config_service, levels_service=levels_service)
    app.config.update(TESTING=True)
    client = app.test_client()
    _authenticate_client(client)

    page_response = client.get("/dashboard/levels?guild_id=123")
    save_response = client.post(
        "/dashboard/levels/settings?guild_id=123",
        data={
            "csrf_token": "csrf-token",
            "leveling_levelup_channel_id": "777",
            "leveling_levelup_enabled": "0",
            "leveling_levelup_mention": "0",
            "leveling_levelup_message": "{user} chegou ao nível {level} no {server}.",
        },
    )
    loaded = asyncio.run(config_service.get_config(123))

    assert page_response.status_code == 200
    assert b"An\xc3\xbancios de Level Up" in page_response.data
    assert save_response.status_code == 302
    assert loaded.leveling.levelup_channel_id == 777
    assert loaded.leveling.levelup_enabled is False
    assert loaded.leveling.levelup_mention is False
    assert loaded.leveling.levelup_message == (
        "{user} chegou ao nível {level} no {server}."
    )


def test_dashboard_lists_tickets_with_filters(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Ensure the Dashboard can inspect persisted tickets."""

    _configure_dashboard_settings(monkeypatch)
    database_path = tmp_path / "tars.sqlite3"
    ticket_service = TicketService(database_path)
    ticket = asyncio.run(
        ticket_service.create_ticket(
            guild_id=123,
            ticket_type=TicketType.REPORT,
            creator_user_id=7,
            target_user_id=8,
            description="denúncia com provas",
            anonymous_report=False,
            expiration_hours=72,
            archive_after_hours=24,
        ),
    )
    app = create_app(
        CoreConfigService(database_path),
        ticket_service=ticket_service,
    )
    app.config.update(TESTING=True)
    client = app.test_client()
    _authenticate_client(client)

    response = client.get("/dashboard/tickets?status=open&q=provas")

    assert response.status_code == 200
    assert f"#{ticket.id:04d}".encode() in response.data
    assert b"den\xc3\xbancia com provas" in response.data
    assert b"report" in response.data

    close_response = client.post(
        f"/dashboard/tickets/{ticket.id}/close?guild_id=123",
        data={"csrf_token": "csrf-token"},
    )
    closed = asyncio.run(ticket_service.get_ticket(ticket.id))
    action_logs = asyncio.run(ticket_service.list_action_logs(ticket.id))

    assert close_response.status_code == 302
    assert closed is not None
    assert closed.close_reason == "Fechado diretamente pela Dashboard."
    assert action_logs[0].action == "ticket_closed_dashboard"


def _configure_dashboard_settings(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "tars_owner_user_id", 42)
    monkeypatch.setattr(settings, "tars_guild_id", 123)
    monkeypatch.setattr(settings, "dashboard_secret_key", "test-secret")
    monkeypatch.setattr(settings, "discord_oauth_client_id", "client-id")
    monkeypatch.setattr(settings, "discord_oauth_client_secret", "client-secret")


def _authenticate_client(client: Any) -> None:
    with client.session_transaction() as flask_session:
        flask_session["discord_user_id"] = 42
        flask_session["_csrf_token"] = "csrf-token"


def _dashboard_payload() -> dict[str, str]:
    return {
        "csrf_token": "csrf-token",
        "guild_id": "123",
        "owner_user_id": "42",
        "welcome_enabled": "1",
        "welcome_channel_id": "10",
        "welcome_embed_color": "#2ecc71",
        "welcome_message_template": "Olá {member}, bem-vindo ao {server}.",
        "leave_channel_id": "20",
        "leave_embed_color": "#e74c3c",
        "leave_message_template": "{member} saiu do {server}.",
        "logs_channel_id": "11",
        "logs_detail_level": "3",
        "auto_role_enabled": "1",
        "auto_role_id": "12",
        "auto_mod_enabled": "1",
        "auto_mod_block_links": "1",
        "auto_mod_dm_owner_on_action": "1",
        "auto_mod_blocked_words": "spam\nphishing",
        "auto_mod_allowed_links": "example.com",
        "leveling_enabled": "1",
        "leveling_message_xp": "25",
        "leveling_message_cooldown_seconds": "30",
        "leveling_voice_xp_per_minute": "8",
        "leveling_level_xp_factor": "200",
        "leveling_levelup_channel_id": "44",
        "leveling_levelup_enabled": "1",
        "leveling_levelup_mention": "0",
        "leveling_levelup_message": "{user} subiu para {level} com {xp} XP.",
        "leveling_xp_owner_user_id": "399757244138520576",
        "leveling_xp_staff_role_ids": "987654321\n123456789\n987654321",
        "leveling_staff_max_set_level": "15",
        "leveling_staff_max_xp_per_command": "5000",
        "tickets_triage_channel_id": "30",
        "tickets_transcript_channel_id": "33",
        "tickets_staff_role_ids": "31\n32\n31",
        "tickets_ticket_expiration_hours": "72",
        "tickets_archive_after_hours": "24",
        "tickets_tribunal_majority_votes": "2",
        "tickets_anonymous_reports_enabled": "1",
        "tickets_dm_notifications_enabled": "1",
        "tickets_rate_limit_ticket_count": "2",
        "tickets_rate_limit_window_minutes": "60",
    }
