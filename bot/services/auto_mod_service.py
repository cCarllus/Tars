"""Automatic moderation checks for the core server feature."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import discord

from bot.database.models.core_models import AutoModConfigModel
from bot.logger import logger
from bot.services.audit_log_service import AuditLogService, audit_log_service
from bot.services.core_config_service import CoreConfigService, core_config_service
from bot.utils.queue_manager import discord_api_queue
from bot.utils.safe_discord import safe_delete_message

DEFAULT_BLOCKED_DOMAINS_PATH = (
    Path(__file__).resolve().parents[1] / "database" / "blocked_domains.json"
)
URL_PATTERN = re.compile(
    r"(?P<url>(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<]*)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class AutoModResult:
    """Result of an automatic moderation check."""

    should_delete: bool
    reason: str | None = None


class AutoModService:
    """Execute configured moderation rules in the background."""

    def __init__(
        self,
        config_service: CoreConfigService | None = None,
        audit_service: AuditLogService | None = None,
        blocked_domains_path: str | Path | None = None,
    ) -> None:
        """Initialize the service."""

        self.config_service = config_service or core_config_service
        self.audit_service = audit_service or audit_log_service
        self.blocked_domains_path = Path(
            blocked_domains_path or DEFAULT_BLOCKED_DOMAINS_PATH,
        )
        self._blocked_domains_mtime_ns: int | None = None
        self._blocked_domains: tuple[str, ...] = ()

    async def handle_message(self, message: discord.Message) -> AutoModResult:
        """Apply auto-mod rules to a Discord message."""

        if message.guild is None or message.author.bot:
            return AutoModResult(should_delete=False)

        config = await self.config_service.get_config(message.guild.id)
        result = self.evaluate_content(message.content, config.auto_mod)
        if not result.should_delete:
            return result

        await discord_api_queue.submit(
            action="delete_auto_mod_message",
            operation=lambda: safe_delete_message(
                message,
                reason="delete_auto_mod_message",
            ),
        )
        await self.audit_service.log_event(
            guild=message.guild,
            event_type="auto_mod_action",
            title="Auto-moderação aplicada",
            description=(
                f"Mensagem de {message.author.mention} removida: {result.reason}."
            ),
            payload={
                "channel_id": message.channel.id,
                "message_id": message.id,
                "reason": result.reason,
            },
            actor_user_id=message.author.id,
            target_user_id=message.author.id,
            color=discord.Color.orange(),
        )
        return result

    def evaluate_content(
        self,
        content: str,
        config: AutoModConfigModel,
    ) -> AutoModResult:
        """Evaluate configured text rules without touching Discord."""

        if not config.enabled:
            return AutoModResult(should_delete=False)

        normalized = content.casefold()
        for word in config.blocked_words:
            if word.casefold() in normalized:
                return AutoModResult(
                    should_delete=True,
                    reason="palavra bloqueada",
                )

        blocked_domain = self._find_blocked_domain(content)
        if blocked_domain is not None:
            return AutoModResult(
                should_delete=True,
                reason=f"domínio bloqueado ({blocked_domain})",
            )

        return AutoModResult(should_delete=False)

    def _find_blocked_domain(self, content: str) -> str | None:
        blocked_domains = self._load_blocked_domains()
        if not blocked_domains:
            return None

        for match in URL_PATTERN.finditer(content):
            domain = _normalize_domain(match.group("url"))
            if domain is not None and _is_blocked_domain(domain, blocked_domains):
                return domain

        return None

    def _load_blocked_domains(self) -> tuple[str, ...]:
        try:
            file_stat = self.blocked_domains_path.stat()
        except FileNotFoundError:
            self._blocked_domains_mtime_ns = None
            self._blocked_domains = ()
            return self._blocked_domains

        if self._blocked_domains_mtime_ns == file_stat.st_mtime_ns:
            return self._blocked_domains

        try:
            payload: object = json.loads(
                self.blocked_domains_path.read_text(encoding="utf-8"),
            )
        except json.JSONDecodeError:
            logger.exception(
                "Invalid blocked domains JSON path=%s",
                self.blocked_domains_path,
            )
            self._blocked_domains_mtime_ns = file_stat.st_mtime_ns
            self._blocked_domains = ()
            return self._blocked_domains

        self._blocked_domains_mtime_ns = file_stat.st_mtime_ns
        self._blocked_domains = _parse_blocked_domains(payload)
        return self._blocked_domains


def _parse_blocked_domains(payload: object) -> tuple[str, ...]:
    raw_domains: object
    if isinstance(payload, dict):
        raw_domains = payload.get("blocked_domains", ())
    else:
        raw_domains = payload

    if not isinstance(raw_domains, list | tuple):
        return ()

    domains: list[str] = []
    for raw_domain in raw_domains:
        if not isinstance(raw_domain, str):
            continue
        domain = _normalize_domain(raw_domain)
        if domain is not None and domain not in domains:
            domains.append(domain)

    return tuple(domains)


def _normalize_domain(value: str) -> str | None:
    raw_value = value.strip().casefold()
    if not raw_value:
        return None

    parsed = urlparse(raw_value if "://" in raw_value else f"//{raw_value}")
    if parsed.hostname is None:
        return None

    return parsed.hostname.removeprefix("www.")


def _is_blocked_domain(domain: str, blocked_domains: tuple[str, ...]) -> bool:
    return any(
        domain == blocked_domain or domain.endswith(f".{blocked_domain}")
        for blocked_domain in blocked_domains
    )


auto_mod_service = AutoModService()
