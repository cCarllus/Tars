"""Authentication and CSRF helpers for the private Dashboard."""

from __future__ import annotations

import functools
import secrets
from collections.abc import Callable
from typing import Any, TypeVar, cast

from flask import abort, redirect, request, session, url_for

from bot.config import settings

CSRF_SESSION_KEY = "_csrf_token"
SESSION_USER_ID_KEY = "discord_user_id"
SESSION_GUILD_ID_KEY = "dashboard_guild_id"

T = TypeVar("T", bound=Callable[..., Any])


def csrf_token() -> str:
    """Return the current CSRF token, creating one when needed."""

    token = session.get(CSRF_SESSION_KEY)
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def validate_csrf() -> None:
    """Abort the request when the submitted CSRF token is invalid."""

    submitted = request.form.get("csrf_token", "")
    expected = session.get(CSRF_SESSION_KEY, "")
    if not (
        isinstance(expected, str)
        and submitted
        and secrets.compare_digest(submitted, expected)
    ):
        abort(400, description="Token CSRF inválido.")


def login_required(view: T) -> T:
    """Require an authenticated Discord owner session."""

    @functools.wraps(view)
    def wrapped(*args: object, **kwargs: object) -> object:
        user_id = current_user_id()
        if user_id is None:
            return redirect(url_for("auth.login"))

        if not settings.tars_owner_user_id or user_id != settings.tars_owner_user_id:
            return redirect(url_for("auth.access_denied"))

        return view(*args, **kwargs)

    return cast(T, wrapped)


def current_user_id() -> int | None:
    """Return the authenticated Discord user ID from the session."""

    raw_user_id = session.get(SESSION_USER_ID_KEY)
    if raw_user_id is None:
        return None
    return int(str(raw_user_id))
