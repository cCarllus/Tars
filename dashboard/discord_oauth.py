"""Discord OAuth2 client helpers for Dashboard authentication."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bot.config import settings

DISCORD_AUTHORIZATION_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = "https://discord.com/api/oauth2/token"
DISCORD_USER_URL = "https://discord.com/api/users/@me"
OAUTH_TIMEOUT_SECONDS = 10
DISCORD_API_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "TARS-Dashboard/0.1",
}


class DiscordOAuthError(RuntimeError):
    """Raised when Discord OAuth authentication fails."""


def oauth_is_configured() -> bool:
    """Return whether the required OAuth settings are available."""

    return bool(
        settings.discord_oauth_client_id
        and settings.discord_oauth_client_secret
        and settings.discord_oauth_redirect_uri
        and settings.dashboard_secret_key
        and settings.tars_owner_user_id
    )


def build_authorization_url(state: str) -> str:
    """Build the Discord authorization URL for the owner login flow."""

    query = urlencode(
        {
            "client_id": settings.discord_oauth_client_id,
            "redirect_uri": settings.discord_oauth_redirect_uri,
            "response_type": "code",
            "scope": "identify",
            "state": state,
            "prompt": "none",
        },
    )
    return f"{DISCORD_AUTHORIZATION_URL}?{query}"


def exchange_code_for_token(code: str) -> str:
    """Exchange an OAuth code for an access token."""

    payload = urlencode(
        {
            "client_id": settings.discord_oauth_client_id,
            "client_secret": settings.discord_oauth_client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.discord_oauth_redirect_uri,
        },
    ).encode("utf-8")
    request = Request(
        DISCORD_TOKEN_URL,
        data=payload,
        headers={
            **DISCORD_API_HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=OAUTH_TIMEOUT_SECONDS) as response:
            token_payload = _read_json_response(response.read())
    except HTTPError as exc:
        raise DiscordOAuthError(_format_discord_http_error(exc)) from exc

    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise DiscordOAuthError("Discord não retornou um token de acesso.")
    return access_token


def fetch_current_user(access_token: str) -> dict[str, Any]:
    """Fetch the authenticated Discord user payload."""

    request = Request(
        DISCORD_USER_URL,
        headers={
            **DISCORD_API_HEADERS,
            "Authorization": f"Bearer {access_token}",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=OAUTH_TIMEOUT_SECONDS) as response:
            user_payload = _read_json_response(response.read())
    except HTTPError as exc:
        raise DiscordOAuthError(_format_discord_http_error(exc)) from exc

    if not isinstance(user_payload.get("id"), str):
        raise DiscordOAuthError("Discord não retornou um usuário válido.")
    return user_payload


def _read_json_response(raw_body: bytes) -> dict[str, Any]:
    payload = json.loads(raw_body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise DiscordOAuthError("Resposta inválida recebida do Discord.")
    return payload


def _format_discord_http_error(exc: HTTPError) -> str:
    raw_body = exc.read().decode("utf-8", errors="replace")
    safe_body = raw_body[:500] if raw_body else "<sem corpo>"
    return f"Discord HTTP {exc.code}: {safe_body}"
