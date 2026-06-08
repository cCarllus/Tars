"""XP calculation, permission and embed helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

import discord
from discord import app_commands

from bot.database.models.core_models import (
    DEFAULT_STAFF_MAX_SET_LEVEL,
    DEFAULT_STAFF_MAX_XP_PER_COMMAND,
    DEFAULT_XP_OWNER_USER_ID,
)
from bot.database.models.level_models import UserLevelModel

DEFAULT_FORMULA_QUADRATIC = 5
DEFAULT_FORMULA_LINEAR = 50
DEFAULT_FORMULA_CONSTANT = 100
XP_COLOR_GOLD = 0xF5C542
XP_COLOR_PURPLE = 0x7C3AED
XP_COLOR_DARK_BLUE = 0x111827
XP_COLOR_GREEN = 0x22C55E
XP_COLOR_ERROR = 0xEF4444
LEVEL_UP_THUMBNAIL_URL = "https://media.giphy.com/media/26tOZ42Mg6pbTUPHW/giphy.gif"
PROGRESS_BAR_SIZE = 16
T = TypeVar("T")


@dataclass(frozen=True)
class XPAdminPermission:
    """Resolved XP admin permission for a Discord user."""

    allowed: bool
    is_owner: bool
    actor_label: str
    denial_reason: str | None = None


def xp_required_for_next_level(
    level: int,
    *,
    quadratic: int = DEFAULT_FORMULA_QUADRATIC,
    linear: int = DEFAULT_FORMULA_LINEAR,
    constant: int = DEFAULT_FORMULA_CONSTANT,
) -> int:
    """Return the XP needed to move from ``level`` to ``level + 1``."""

    normalized_level = max(0, level)
    return (
        max(0, quadratic) * (normalized_level**2)
        + max(0, linear) * normalized_level
        + max(1, constant)
    )


def total_xp_required_for_level(
    level: int,
    *,
    quadratic: int = DEFAULT_FORMULA_QUADRATIC,
    linear: int = DEFAULT_FORMULA_LINEAR,
    constant: int = DEFAULT_FORMULA_CONSTANT,
) -> int:
    """Return cumulative XP required to reach ``level``."""

    return sum(
        xp_required_for_next_level(
            current_level,
            quadratic=quadratic,
            linear=linear,
            constant=constant,
        )
        for current_level in range(max(0, level))
    )


def calculate_level_from_xp(
    xp: int,
    *,
    quadratic: int = DEFAULT_FORMULA_QUADRATIC,
    linear: int = DEFAULT_FORMULA_LINEAR,
    constant: int = DEFAULT_FORMULA_CONSTANT,
) -> int:
    """Calculate the level reached by a total XP amount."""

    remaining_xp = max(0, xp)
    level = 0
    while remaining_xp >= xp_required_for_next_level(
        level,
        quadratic=quadratic,
        linear=linear,
        constant=constant,
    ):
        remaining_xp -= xp_required_for_next_level(
            level,
            quadratic=quadratic,
            linear=linear,
            constant=constant,
        )
        level += 1
    return level


def xp_progress_for_level(
    xp: int,
    *,
    quadratic: int = DEFAULT_FORMULA_QUADRATIC,
    linear: int = DEFAULT_FORMULA_LINEAR,
    constant: int = DEFAULT_FORMULA_CONSTANT,
) -> tuple[int, int, int]:
    """Return ``(level, xp_in_level, xp_needed_for_next_level)``."""

    level = calculate_level_from_xp(
        xp,
        quadratic=quadratic,
        linear=linear,
        constant=constant,
    )
    level_floor = total_xp_required_for_level(
        level,
        quadratic=quadratic,
        linear=linear,
        constant=constant,
    )
    return (
        level,
        max(0, xp - level_floor),
        xp_required_for_next_level(
            level,
            quadratic=quadratic,
            linear=linear,
            constant=constant,
        ),
    )


def clamp_xp_range(minimum: int, maximum: int) -> tuple[int, int]:
    """Normalize an XP range while preserving non-negative values."""

    lower = max(0, minimum)
    upper = max(0, maximum)
    if upper < lower:
        return upper, lower
    return lower, upper


def deterministic_xp_from_range(minimum: int, maximum: int) -> int:
    """Return a stable XP amount inside a configured range."""

    lower, _upper = clamp_xp_range(minimum, maximum)
    return lower


def hash_message_content(content: str) -> str:
    """Return a stable hash used for repeated-message spam checks."""

    normalized = " ".join(content.casefold().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_owner_or_staff() -> Callable[[T], T]:
    """Return an app command check for XP owner or staff visibility."""

    async def predicate(interaction: discord.Interaction) -> bool:
        permissions = resolve_xp_admin_permission(
            user_id=interaction.user.id,
            has_staff_permission=False,
        )
        return permissions.allowed

    return app_commands.check(predicate)


def resolve_xp_admin_permission(
    *,
    user_id: int,
    has_staff_permission: bool,
    configured_owner_user_id: int = DEFAULT_XP_OWNER_USER_ID,
) -> XPAdminPermission:
    """Resolve whether a user can run XP admin commands."""

    if user_id in {DEFAULT_XP_OWNER_USER_ID, configured_owner_user_id}:
        return XPAdminPermission(allowed=True, is_owner=True, actor_label="Owner")

    if has_staff_permission:
        return XPAdminPermission(allowed=True, is_owner=False, actor_label="Staff")

    return XPAdminPermission(
        allowed=False,
        is_owner=False,
        actor_label="Usuário",
        denial_reason="Apenas o Owner ou staff autorizado pode usar esse comando.",
    )


def validate_xp_add_limit(
    *,
    amount: int,
    permission: XPAdminPermission,
    staff_max_xp_per_command: int = DEFAULT_STAFF_MAX_XP_PER_COMMAND,
) -> str | None:
    """Return an error message when an XP add request exceeds permissions."""

    if not permission.allowed:
        return permission.denial_reason
    if amount < 0:
        return "A quantidade de XP não pode ser negativa."
    if permission.is_owner:
        return None
    if amount > staff_max_xp_per_command:
        return (
            "Staff comum só pode adicionar até "
            f"{staff_max_xp_per_command} XP por comando."
        )
    return None


def validate_xp_set_limit(
    *,
    level: int,
    permission: XPAdminPermission,
    staff_max_set_level: int = DEFAULT_STAFF_MAX_SET_LEVEL,
) -> str | None:
    """Return an error message when a level set request exceeds permissions."""

    if not permission.allowed:
        return permission.denial_reason
    if level < 0:
        return "O nível não pode ser negativo."
    if permission.is_owner:
        return None
    if level > staff_max_set_level:
        return f"Staff comum só pode definir nível até {staff_max_set_level}."
    return None


def create_xp_embed(
    *,
    title: str,
    description: str,
    color: int,
    thumbnail_url: str | None = None,
    image_url: str | None = None,
) -> discord.Embed:
    """Create a consistently styled XP embed."""

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color(color),
    )
    embed.set_footer(text="TARS XP System")
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    if image_url:
        embed.set_image(url=image_url)
    return embed


def create_rank_embed(
    *,
    user: discord.abc.User,
    record: UserLevelModel,
    rank_position: int | None,
    xp_in_level: int,
    xp_needed: int,
) -> discord.Embed:
    """Create a premium rank card embed."""

    progress_percent = 0 if xp_needed <= 0 else xp_in_level / xp_needed
    rank_text = f"#{rank_position}" if rank_position is not None else "Sem rank"
    embed = create_xp_embed(
        title=f"Rank Card • {user.display_name}",
        description=(
            f"{user.mention}\n\n"
            f"{_progress_bar(progress_percent)} **{progress_percent:.0%}**"
        ),
        color=XP_COLOR_PURPLE,
        thumbnail_url=user.display_avatar.url,
    )
    embed.add_field(name="Nível", value=f"**{record.level}**", inline=True)
    embed.add_field(
        name="XP",
        value=f"**{xp_in_level} / {xp_needed}**",
        inline=True,
    )
    embed.add_field(name="Leaderboard", value=f"**{rank_text}**", inline=True)
    embed.add_field(name="XP total", value=f"`{record.xp}`", inline=True)
    embed.add_field(name="Mensagens", value=f"`{record.messages_count}`", inline=True)
    embed.add_field(name="Voz", value=f"`{record.voice_minutes} min`", inline=True)
    return embed


def create_level_up_embed(
    *,
    member: discord.Member,
    level: int,
    xp: int,
    description: str,
) -> discord.Embed:
    """Create a premium level-up announcement embed."""

    embed = create_xp_embed(
        title="Level Up! ✨",
        description=f"{description}\n\nNovo nível: **{level}** • XP total: `{xp}`",
        color=XP_COLOR_GOLD,
        thumbnail_url=member.display_avatar.url,
        image_url=LEVEL_UP_THUMBNAIL_URL,
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    return embed


def create_daily_embed(*, xp_awarded: int, streak: int) -> discord.Embed:
    """Create a daily reward embed."""

    return create_xp_embed(
        title="Daily resgatado",
        description=(
            f"Você recebeu **{xp_awarded} XP**.\n" f"Streak atual: **{streak} dia(s)**."
        ),
        color=XP_COLOR_GREEN,
    )


def create_leaderboard_embed(
    *,
    title: str,
    lines: list[str],
) -> discord.Embed:
    """Create a styled leaderboard embed."""

    return create_xp_embed(
        title=title,
        description="\n".join(lines) if lines else "Ainda não há XP registrado.",
        color=XP_COLOR_GOLD,
    )


def create_xp_audit_embed(
    *,
    actor: discord.abc.User,
    target: discord.abc.User,
    action: str,
    detail: str,
    actor_label: str,
) -> discord.Embed:
    """Create an audit embed for XP admin actions."""

    return create_xp_embed(
        title=f"Auditoria XP • {action}",
        description=(
            f"Executor: {actor.mention} (`{actor.id}`)\n"
            f"Perfil: **{actor_label}**\n"
            f"Alvo: {target.mention} (`{target.id}`)\n"
            f"Detalhe: **{detail}**"
        ),
        color=XP_COLOR_DARK_BLUE,
    )


def create_xp_error_embed(description: str) -> discord.Embed:
    """Create a consistent XP error embed."""

    return create_xp_embed(
        title="Ação bloqueada",
        description=description,
        color=XP_COLOR_ERROR,
    )


def _progress_bar(progress: float) -> str:
    normalized = min(1.0, max(0.0, progress))
    filled = round(normalized * PROGRESS_BAR_SIZE)
    empty = PROGRESS_BAR_SIZE - filled
    return f"`{'▰' * filled}{'▱' * empty}`"


def has_any_xp_staff_role(
    *,
    member_role_ids: tuple[int, ...],
    configured_staff_role_ids: tuple[int, ...],
) -> bool:
    """Return whether any member role is configured for XP admin."""

    if not configured_staff_role_ids:
        return False
    return bool(set(member_role_ids).intersection(configured_staff_role_ids))


def has_xp_staff_role(
    user: discord.abc.User,
    configured_staff_role_ids: tuple[int, ...],
) -> bool:
    """Return whether a Discord user has a configured XP staff role."""

    roles = getattr(user, "roles", ())
    member_role_ids = tuple(int(role.id) for role in roles)
    return has_any_xp_staff_role(
        member_role_ids=member_role_ids,
        configured_staff_role_ids=configured_staff_role_ids,
    )
