"""Tests for the spec 008 XP and levels system."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("DISCORD_TOKEN", "test-token")

from bot.cogs.levels.levels_cog import (
    completed_voice_minutes,
    format_levelup_message,
    levelup_notification_content,
)
from bot.database.models.core_models import DashboardConfigModel, LevelingConfigModel
from bot.services.core_config_service import CoreConfigService
from bot.services.xp_service import XPService
from bot.utils.xp_utils import (
    calculate_level_from_xp,
    has_any_xp_staff_role,
    resolve_xp_admin_permission,
    total_xp_required_for_level,
    validate_xp_add_limit,
    validate_xp_set_limit,
    xp_required_for_next_level,
)


def test_xp_utils_use_configurable_mee6_formula() -> None:
    """Ensure level math follows the configured MEE6-style formula."""

    assert xp_required_for_next_level(0) == 100
    assert xp_required_for_next_level(1) == 155
    assert total_xp_required_for_level(2) == 255
    assert calculate_level_from_xp(99) == 0
    assert calculate_level_from_xp(100) == 1
    assert calculate_level_from_xp(255) == 2
    assert xp_required_for_next_level(1, quadratic=10, linear=20, constant=30) == 60


def test_message_xp_uses_cooldown_ignored_channels_and_repeated_spam(
    tmp_path: Path,
) -> None:
    """Ensure message XP rewards real activity and blocks abuse."""

    service = _configured_service(
        tmp_path,
        LevelingConfigModel(
            message_xp_min=15,
            message_xp_max=25,
            ignored_channel_ids=(999,),
        ),
    )
    now = datetime.now(tz=timezone.utc)  # noqa: UP017

    first = asyncio.run(
        service.add_message_xp(
            guild_id=123,
            user_id=7,
            channel_id=10,
            content="olá mundo",
            created_at=now,
        ),
    )
    cooldown = asyncio.run(
        service.add_message_xp(
            guild_id=123,
            user_id=7,
            channel_id=10,
            content="outra mensagem",
            created_at=now + timedelta(seconds=10),
        ),
    )
    repeated = asyncio.run(
        service.add_message_xp(
            guild_id=123,
            user_id=7,
            channel_id=10,
            content="olá mundo",
            created_at=now + timedelta(seconds=61),
        ),
    )
    ignored_channel = asyncio.run(
        service.add_message_xp(
            guild_id=123,
            user_id=7,
            channel_id=999,
            content="mensagem válida",
            created_at=now + timedelta(seconds=122),
        ),
    )

    assert first.xp_awarded == 15
    assert first.user_level.messages_count == 1
    assert cooldown.ignored_reason == "message_cooldown"
    assert repeated.ignored_reason == "repeated_message"
    assert ignored_channel.ignored_reason == "ignored_channel"
    assert ignored_channel.user_level.xp == 15


def test_voice_daily_leaderboard_and_rewards(tmp_path: Path) -> None:
    """Ensure voice XP, daily streaks and role rewards are persisted."""

    service = _configured_service(tmp_path, LevelingConfigModel())
    now = datetime.now(tz=timezone.utc)  # noqa: UP017

    voice = asyncio.run(
        service.add_voice_xp(
            guild_id=123,
            user_id=1,
            voice_minutes=2,
            participant_count=2,
        ),
    )
    first_daily = asyncio.run(
        service.claim_daily(guild_id=123, user_id=2, claimed_at=now),
    )
    second_daily = asyncio.run(
        service.claim_daily(
            guild_id=123,
            user_id=2,
            claimed_at=now + timedelta(days=1),
        ),
    )
    blocked_daily = asyncio.run(
        service.claim_daily(
            guild_id=123,
            user_id=2,
            claimed_at=now + timedelta(days=1, minutes=5),
        ),
    )
    asyncio.run(service.set_level_reward(guild_id=123, level=1, role_id=555))
    rewards = asyncio.run(service.list_earned_rewards(guild_id=123, level=2))
    leaderboard = asyncio.run(service.get_leaderboard(guild_id=123))

    assert voice.xp_awarded == 60
    assert first_daily.xp_awarded == 100
    assert second_daily.xp_awarded == 120
    assert second_daily.user_level.daily_streak == 2
    assert blocked_daily.ignored_reason == "daily_already_claimed"
    assert rewards[0].role_id == 555
    assert [record.user_id for record in leaderboard] == [2, 1]


def test_completed_voice_minutes_only_counts_full_minutes() -> None:
    """Ensure periodic voice awards use full completed minutes."""

    now = datetime.now(tz=timezone.utc)  # noqa: UP017

    assert completed_voice_minutes(now, now + timedelta(seconds=59)) == 0
    assert completed_voice_minutes(now, now + timedelta(seconds=60)) == 1
    assert completed_voice_minutes(now, now + timedelta(seconds=125)) == 2


def test_xp_admin_permissions_limit_staff_and_allow_owner() -> None:
    """Ensure XP admin rules enforce owner god mode and staff caps."""

    owner = resolve_xp_admin_permission(
        user_id=399757244138520576,
        has_staff_permission=False,
    )
    staff = resolve_xp_admin_permission(
        user_id=7,
        has_staff_permission=True,
    )
    common = resolve_xp_admin_permission(
        user_id=8,
        has_staff_permission=False,
    )

    assert owner.allowed is True
    assert owner.is_owner is True
    assert validate_xp_set_limit(level=999, permission=owner) is None
    assert validate_xp_add_limit(amount=999_999, permission=owner) is None
    assert validate_xp_set_limit(level=-1, permission=owner) is not None
    assert validate_xp_add_limit(amount=-1, permission=owner) is not None
    assert staff.allowed is True
    assert staff.is_owner is False
    assert validate_xp_set_limit(level=15, permission=staff) is None
    assert validate_xp_set_limit(level=16, permission=staff) is not None
    assert validate_xp_add_limit(amount=5000, permission=staff) is None
    assert validate_xp_add_limit(amount=5001, permission=staff) is not None
    assert common.allowed is False
    assert validate_xp_set_limit(level=1, permission=common) is not None
    assert has_any_xp_staff_role(
        member_role_ids=(111, 222),
        configured_staff_role_ids=(333, 222),
    )
    assert not has_any_xp_staff_role(
        member_role_ids=(111, 222),
        configured_staff_role_ids=(333, 444),
    )


def test_levelup_config_defaults_aliases_and_message_formatting() -> None:
    """Ensure level-up announcement settings support defaults and placeholders."""

    default_config = LevelingConfigModel()
    legacy_config = LevelingConfigModel.from_dict(
        {"level_up_message": "{member} chegou no nível {level}."},
    )
    custom_config = LevelingConfigModel.from_dict(
        {
            "levelup_channel_id": "987",
            "levelup_enabled": False,
            "levelup_mention": False,
            "levelup_message": "{user} tem {xp} XP no {server}.",
        },
    )

    assert default_config.levelup_enabled is True
    assert default_config.levelup_mention is True
    assert legacy_config.levelup_message == "{member} chegou no nível {level}."
    assert legacy_config.level_up_message == legacy_config.levelup_message
    assert custom_config.levelup_channel_id == 987
    assert custom_config.levelup_enabled is False
    assert custom_config.levelup_mention is False
    assert (
        format_levelup_message(
            template=custom_config.levelup_message,
            user_mention="<@7>",
            display_name="Carllos",
            level=3,
            xp=255,
            server_name="TARS",
            mention_enabled=False,
        )
        == "Carllos tem 255 XP no TARS."
    )
    assert (
        levelup_notification_content(
            user_mention="<@7>",
            mention_enabled=True,
        )
        == "<@7>"
    )
    assert (
        levelup_notification_content(
            user_mention="<@7>",
            mention_enabled=False,
        )
        is None
    )


def _configured_service(
    tmp_path: Path,
    leveling_config: LevelingConfigModel,
) -> XPService:
    database_path = tmp_path / "tars.sqlite3"
    config_service = CoreConfigService(database_path)
    config = DashboardConfigModel(
        guild_id=123,
        owner_user_id=42,
        leveling=leveling_config,
    )
    asyncio.run(config_service.save_config_from_dashboard(config, actor_user_id=42))
    return XPService(database_path, config_service=config_service)
