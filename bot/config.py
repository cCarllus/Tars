"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import TypeAlias

OptionalString: TypeAlias = Optional[str]  # noqa: UP007


class Settings(BaseSettings):
    """Runtime settings for the Discord bot.

    Attributes:
        discord_token: Token used to authenticate with Discord.
        command_prefix: Prefix used for text commands.
        gemini_api_key: Google Gemini API key used by the AI cog.
        youtube_api_key: YouTube Data API key used by the music cog.
        spotify_client_id: Spotify client ID used by the music cog.
        spotify_client_secret: Spotify client secret used by the music cog.
        data_dir: Directory used for simple local data files.
        schedule_file: File path for the public agenda list.
        log_level: Root log level.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    discord_token: str = Field(alias="DISCORD_TOKEN")
    command_prefix: str = Field(default="$", alias="COMMAND_PREFIX")
    gemini_api_key: OptionalString = Field(default=None, alias="GEMINI_API_KEY")
    youtube_api_key: OptionalString = Field(default=None, alias="YOUTUBE_API_KEY")
    spotify_client_id: OptionalString = Field(default=None, alias="SPOTIFY_CLIENT_ID")
    spotify_client_secret: OptionalString = Field(
        default=None,
        alias="SPOTIFY_CLIENT_SECRET",
    )
    data_dir: Path = Field(default=Path("files"), alias="DATA_DIR")
    schedule_file: Path = Field(default=Path("files/list.txt"), alias="SCHEDULE_FILE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache
def get_settings() -> Settings:
    """Return cached runtime settings."""

    return Settings()


settings = get_settings()
