"""Async in-memory rate limiter for high-interaction bot actions."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from time import monotonic

from bot.logger import logger

VOICE_CREATION_ACTION = "voice_creation"
MESSAGE_SENDING_ACTION = "message_sending"


@dataclass(frozen=True)
class RateLimitRule:
    """Rate limit rule for one bucket."""

    limit: int
    window_seconds: float


@dataclass(frozen=True)
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    action: str
    scope: str
    retry_after: float = 0.0


class RateLimitExceeded(RuntimeError):
    """Raised when a rate-limited action must be rejected."""

    def __init__(self, result: RateLimitResult) -> None:
        """Initialize the exception."""

        super().__init__(
            f"Rate limit exceeded for {result.action}:{result.scope}; "
            f"retry after {result.retry_after:.2f}s"
        )
        self.result = result


class RateLimiter:
    """Sliding-window limiter with global, guild and user buckets."""

    def __init__(
        self,
        *,
        default_rule: RateLimitRule | None = None,
        action_rules: dict[str, dict[str, RateLimitRule]] | None = None,
    ) -> None:
        """Initialize the limiter."""

        self._lock = asyncio.Lock()
        self._default_rule = default_rule or RateLimitRule(limit=30, window_seconds=60)
        self._action_rules = action_rules or {
            VOICE_CREATION_ACTION: {
                "global": RateLimitRule(limit=50, window_seconds=60),
                "guild": RateLimitRule(limit=20, window_seconds=60),
                "user": RateLimitRule(limit=1, window_seconds=20),
            },
            MESSAGE_SENDING_ACTION: {
                "global": RateLimitRule(limit=120, window_seconds=60),
                "guild": RateLimitRule(limit=60, window_seconds=60),
                "user": RateLimitRule(limit=10, window_seconds=60),
            },
        }
        self._hits: dict[tuple[str, str, int], deque[float]] = defaultdict(deque)

    async def check(
        self,
        *,
        action: str,
        user_id: int | None = None,
        guild_id: int | None = None,
    ) -> RateLimitResult:
        """Check and record a rate-limited action."""

        async with self._lock:
            now = monotonic()
            checks = self._build_checks(
                action=action,
                user_id=user_id,
                guild_id=guild_id,
            )

            for scope, identifier, rule in checks:
                result = self._check_bucket(
                    action=action,
                    scope=scope,
                    identifier=identifier,
                    rule=rule,
                    now=now,
                    commit=False,
                )
                if not result.allowed:
                    logger.warning(
                        "Rate limit hit action=%s scope=%s retry_after=%.2f",
                        action,
                        result.scope,
                        result.retry_after,
                    )
                    return result

            for scope, identifier, rule in checks:
                self._check_bucket(
                    action=action,
                    scope=scope,
                    identifier=identifier,
                    rule=rule,
                    now=now,
                    commit=True,
                )

        return RateLimitResult(allowed=True, action=action, scope="all")

    def _build_checks(
        self,
        *,
        action: str,
        user_id: int | None,
        guild_id: int | None,
    ) -> list[tuple[str, int, RateLimitRule]]:
        rules = self._action_rules.get(action, {})
        checks = [("global", 0, rules.get("global", self._default_rule))]

        if guild_id is not None:
            checks.append(("guild", guild_id, rules.get("guild", self._default_rule)))

        if user_id is not None:
            checks.append(("user", user_id, rules.get("user", self._default_rule)))

        return checks

    def _check_bucket(
        self,
        *,
        action: str,
        scope: str,
        identifier: int,
        rule: RateLimitRule,
        now: float,
        commit: bool,
    ) -> RateLimitResult:
        key = (action, scope, identifier)
        hits = self._hits[key]
        cutoff = now - rule.window_seconds

        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= rule.limit:
            retry_after = max(0.0, rule.window_seconds - (now - hits[0]))
            return RateLimitResult(
                allowed=False,
                action=action,
                scope=f"{scope}:{identifier}",
                retry_after=retry_after,
            )

        if commit:
            hits.append(now)

        return RateLimitResult(
            allowed=True,
            action=action,
            scope=f"{scope}:{identifier}",
        )


rate_limiter = RateLimiter()
