"""Authentication routes for the private Dashboard."""

from __future__ import annotations

import logging
import secrets
from urllib.error import URLError

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask.typing import ResponseReturnValue

from bot.config import settings
from bot.logger import logger
from dashboard.discord_oauth import (
    DiscordOAuthError,
    build_authorization_url,
    exchange_code_for_token,
    fetch_current_user,
    oauth_is_configured,
)
from dashboard.security import SESSION_USER_ID_KEY, validate_csrf

auth_blueprint = Blueprint("auth", __name__)
audit_logger = logging.getLogger("tars.dashboard.audit")


@auth_blueprint.get("/login")
def login() -> ResponseReturnValue:
    """Render the owner login screen."""

    return render_template(
        "login.html",
        oauth_ready=oauth_is_configured(),
        owner_user_id=settings.tars_owner_user_id,
    )


@auth_blueprint.post("/login")
def start_login() -> ResponseReturnValue:
    """Start Discord OAuth login for the Dashboard owner."""

    validate_csrf()
    if not oauth_is_configured():
        audit_logger.warning(
            "dashboard_oauth_not_configured owner_set=%s client_id_set=%s "
            "client_secret_set=%s redirect_uri_set=%s secret_key_set=%s",
            bool(settings.tars_owner_user_id),
            bool(settings.discord_oauth_client_id),
            bool(settings.discord_oauth_client_secret),
            bool(settings.discord_oauth_redirect_uri),
            bool(settings.dashboard_secret_key),
        )
        flash("OAuth do Discord ainda não está configurado no .env.", "error")
        return redirect(url_for("auth.login"))

    state = secrets.token_urlsafe(32)
    session["discord_oauth_state"] = state
    audit_logger.info(
        "dashboard_oauth_start host=%s redirect_uri=%s state_created=%s",
        request.host,
        settings.discord_oauth_redirect_uri,
        True,
    )
    return redirect(build_authorization_url(state))


@auth_blueprint.get("/auth/discord/callback")
def discord_callback() -> ResponseReturnValue:
    """Handle the Discord OAuth callback and enforce owner-only access."""

    expected_state = session.pop("discord_oauth_state", "")
    state = request.args.get("state", "")
    code = request.args.get("code", "")
    if not expected_state or not secrets.compare_digest(expected_state, state):
        audit_logger.warning(
            "dashboard_oauth_invalid_state host=%s has_session_cookie=%s "
            "expected_state_present=%s callback_state_present=%s state_matches=%s",
            request.host,
            "session" in request.cookies,
            bool(expected_state),
            bool(state),
            bool(expected_state and secrets.compare_digest(expected_state, state)),
        )
        flash("Sessão OAuth inválida. Faça login novamente.", "error")
        return redirect(url_for("auth.login"))

    if not code:
        audit_logger.warning("dashboard_oauth_missing_code host=%s", request.host)
        flash("Discord não retornou o código de autenticação.", "error")
        return redirect(url_for("auth.login"))

    try:
        access_token = exchange_code_for_token(code)
        discord_user = fetch_current_user(access_token)
    except (DiscordOAuthError, URLError, TimeoutError) as exc:
        logger.exception("Discord OAuth login failed")
        audit_logger.warning(
            "discord_oauth_failed host=%s redirect_uri=%s error=%s",
            request.host,
            settings.discord_oauth_redirect_uri,
            exc,
        )
        flash("Não foi possível autenticar com o Discord agora.", "error")
        return redirect(url_for("auth.login"))

    user_id = int(str(discord_user["id"]))
    if not settings.tars_owner_user_id or user_id != settings.tars_owner_user_id:
        audit_logger.warning(
            "dashboard_access_denied user_id=%s owner_user_id=%s",
            user_id,
            settings.tars_owner_user_id,
        )
        session.clear()
        return redirect(url_for("auth.access_denied"))

    session[SESSION_USER_ID_KEY] = user_id
    audit_logger.info("dashboard_login_success user_id=%s", user_id)
    return redirect(url_for("config.dashboard"))


@auth_blueprint.post("/logout")
def logout() -> ResponseReturnValue:
    """End the current Dashboard session."""

    validate_csrf()
    user_id = session.get(SESSION_USER_ID_KEY)
    session.clear()
    audit_logger.info("dashboard_logout user_id=%s", user_id)
    return redirect(url_for("auth.login"))


@auth_blueprint.get("/access-denied")
def access_denied() -> ResponseReturnValue:
    """Render the access denied screen."""

    return render_template("access_denied.html")
