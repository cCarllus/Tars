"""Discord bot entrypoint."""

import asyncio
from pathlib import Path

import discord
from discord.ext import commands

from bot.config import settings
from bot.logger import configure_logging, logger

COGS_PACKAGE = "bot.cogs"
COGS_PATH = Path(__file__).parent / "cogs"
INVITE_PERMISSIONS = discord.Permissions(
    connect=True,
    manage_messages=True,
    manage_roles=True,
    manage_channels=True,
    move_members=True,
    view_channel=True,
    send_messages=True,
    read_message_history=True,
    speak=True,
)


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

    def __init__(self, command_prefix: str, intents: discord.Intents) -> None:
        """Initialize the bot runtime state."""

        super().__init__(command_prefix=command_prefix, intents=intents)
        self._guild_commands_synced = False

    async def setup_hook(self) -> None:
        """Load cogs once before the bot connects to Discord."""

        for extension in discover_cogs():
            await self.load_extension(extension)
            logger.info("Loaded cog: %s", extension)

        command_names = ", ".join(
            f"/{command.qualified_name}" for command in self.tree.get_commands()
        )
        logger.info(
            "Registered local application commands: %s",
            command_names or "none",
        )

        synced_commands = await self.tree.sync()
        logger.info("Synced %s application commands", len(synced_commands))

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

        if not self._guild_commands_synced:
            await self.sync_guild_application_commands()
            self._guild_commands_synced = True

        self.log_application_command_invite()
        logger.info("Logged in as %s", self.user)

    async def sync_guild_application_commands(self) -> None:
        """Sync application commands to connected guilds for immediate visibility."""

        for guild in self.guilds:
            guild_object = discord.Object(id=guild.id)
            self.tree.copy_global_to(guild=guild_object)
            synced_commands = await self.tree.sync(guild=guild_object)
            logger.info(
                "Synced %s guild application commands for %s",
                len(synced_commands),
                guild.id,
            )

    def log_application_command_invite(self) -> None:
        """Log an invite URL with the scope required for slash commands."""

        if self.application_id is None:
            return

        invite_url = discord.utils.oauth_url(
            client_id=self.application_id,
            permissions=INVITE_PERMISSIONS,
            scopes=("bot", "applications.commands"),
        )
        logger.info("Invite with slash command scope: %s", invite_url)


def create_bot() -> TarsBot:
    """Create and configure the Discord bot instance."""

    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True
    intents.voice_states = True

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
