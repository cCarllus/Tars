"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the Discord bot.

    Attributes:
        discord_token: Token used to authenticate with Discord.
        command_prefix: Prefix used for text commands.
        log_level: Root log level.
        database_path: SQLite database path.
        tars_owner_user_id: Discord user ID allowed to manage the dashboard.
        global_command_channel_id: Channel where generation commands are allowed.
        private_voice_hub_id: Voice channel that creates private calls.
        promo_channel_id: Text channel where game promotions are allowed.
        itad_api_key: API key used for IsThereAnyDeal requests.
        itad_client_id: Client ID issued by IsThereAnyDeal.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    discord_token: str = Field(alias="DISCORD_TOKEN")
    command_prefix: str = Field(default="/", alias="COMMAND_PREFIX")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    database_path: str = Field(
        default="bot/database/tars.sqlite3",
        alias="DATABASE_PATH",
    )
    tars_owner_user_id: int = Field(default=0, alias="TARS_OWNER_USER_ID")
    global_command_channel_id: int = Field(
        default=1498085284410298590,
        alias="GLOBAL_COMMAND_CHANNEL_ID",
    )
    private_voice_hub_id: int = Field(
        default=1498213727932256308,
        alias="PRIVATE_VOICE_HUB_ID",
    )
    promo_channel_id: int = Field(
        default=1498085291506794549,
        alias="PROMO_CHANNEL_ID",
    )
    itad_api_key: str = Field(default="", alias="ITAD_API_KEY")
    itad_client_id: str = Field(default="", alias="ITAD_CLIENT_ID")


@lru_cache
def get_settings() -> Settings:
    """Return cached runtime settings."""

    return Settings()


settings = get_settings()
