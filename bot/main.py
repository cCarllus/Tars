"""Discord bot entrypoint."""

import asyncio
from pathlib import Path

import discord
from discord.ext import commands

from bot.config import settings
from bot.logger import configure_logging, logger

COGS_PACKAGE = "bot.cogs"
COGS_PATH = Path(__file__).parent / "cogs"


def discover_cogs() -> list[str]:
    """Return import paths for every cog module under bot/cogs."""

    cogs: list[str] = []
    for file_path in sorted(COGS_PATH.rglob("*.py")):
        if file_path.name == "__init__.py":
            continue

        relative_path = file_path.relative_to(COGS_PATH).with_suffix("")
        module_path = ".".join(relative_path.parts)
        cogs.append(f"{COGS_PACKAGE}.{module_path}")

    return cogs


class TarsBot(commands.Bot):
    """Discord bot configured for the Tars project."""

    async def setup_hook(self) -> None:
        """Load cogs once before the bot connects to Discord."""

        for extension in discover_cogs():
            await self.load_extension(extension)
            logger.info("Loaded cog: %s", extension)

    async def on_ready(self) -> None:
        """Log readiness and update bot presence."""

        if self.user is None:
            logger.info("Bot connected, but user information is unavailable")
            return

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{settings.command_prefix}help",
            ),
        )
        logger.info("Logged in as %s", self.user)


def create_bot() -> TarsBot:
    """Create and configure the Discord bot instance."""

    intents = discord.Intents.default()
    intents.message_content = True

    bot = TarsBot(command_prefix=settings.command_prefix, intents=intents)
    bot.remove_command("help")
    return bot


async def async_main() -> None:
    """Start the bot."""

    configure_logging()

    bot = create_bot()
    async with bot:
        await bot.start(settings.discord_token)


def main() -> None:
    """Run the Discord bot process."""

    asyncio.run(async_main())


if __name__ == "__main__":
    main()
