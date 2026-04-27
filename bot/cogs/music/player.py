"""Music playback commands."""

import asyncio
import re
from dataclasses import dataclass
from typing import Literal, TypedDict

import discord
import googleapiclient.discovery
import spotipy
import yt_dlp as youtube_dl
from discord.ext import commands
from spotipy.oauth2 import SpotifyClientCredentials

from bot.config import settings
from bot.logger import logger
from bot.utils.embed import build_embed, error_embed

YOUTUBE_URL_REGEX = re.compile(
    r"(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/.+$",
)
SPOTIFY_URL_REGEX = re.compile(r"https://open\.spotify\.com/track/\w+")
RETRY_DELAY_SECONDS = 2
MAX_RETRIES = 2


class FFmpegOptions(TypedDict, total=False):
    """Keyword options accepted by discord.FFmpegPCMAudio."""

    before_options: str
    options: str


FFMPEG_OPTIONS: FFmpegOptions = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}
YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
}

SourceType = Literal["youtube", "spotify"]


@dataclass(slots=True)
class QueueItem:
    """Resolved audio item waiting to be played."""

    request: str
    source_type: SourceType
    source_ref: str


class YTDLSource(discord.PCMVolumeTransformer[discord.AudioSource]):
    """Discord audio source created from yt-dlp stream metadata."""

    def __init__(
        self,
        source: discord.AudioSource,
        *,
        data: dict[str, object],
        volume: float = 0.5,
    ) -> None:
        super().__init__(source, volume)
        self.data = data
        self.title = str(data.get("title") or "")
        self.webpage_url = str(data.get("webpage_url") or "")

    @classmethod
    async def from_url(cls, url: str) -> "YTDLSource":
        """Create an audio source from a YouTube URL."""

        data = await asyncio.to_thread(
            lambda: youtube_dl.YoutubeDL(YDL_OPTIONS).extract_info(
                url,
                download=False,
            ),
        )
        if "entries" in data:
            data = data["entries"][0]

        return cls(discord.FFmpegPCMAudio(data["url"], **FFMPEG_OPTIONS), data=data)


def is_youtube_url(query: str) -> bool:
    """Return whether a query is a YouTube URL."""

    return YOUTUBE_URL_REGEX.match(query) is not None


def is_spotify_url(query: str) -> bool:
    """Return whether a query is a Spotify track URL."""

    return SPOTIFY_URL_REGEX.match(query) is not None


class MusicPlayer:
    """Manage playback state for a single guild."""

    def __init__(self) -> None:
        self.queue: list[QueueItem] = []
        self.is_playing = False
        self.voice_client: discord.VoiceClient | None = None
        self.ctx: commands.Context[commands.Bot] | None = None
        self.max_retries = MAX_RETRIES

    async def _get_video_url_from_search(self, query: str) -> str | None:
        """Search YouTube and return the first video URL."""

        if not settings.youtube_api_key:
            logger.warning("YOUTUBE_API_KEY is not configured")
            return None

        def search() -> str | None:
            youtube = googleapiclient.discovery.build(
                "youtube",
                "v3",
                developerKey=settings.youtube_api_key,
            )
            request = youtube.search().list(
                part="snippet",
                maxResults=1,
                q=query,
                type="video",
            )
            response = request.execute()
            items = response.get("items", [])
            if not items:
                return None
            video_id = items[0]["id"]["videoId"]
            return f"https://www.youtube.com/watch?v={video_id}"

        return await asyncio.to_thread(search)

    async def _get_spotify_audio_url(self, url: str) -> str | None:
        """Return the Spotify track preview URL when available."""

        if not settings.spotify_client_id or not settings.spotify_client_secret:
            logger.warning("Spotify credentials are not configured")
            return None

        track_id = url.split("/")[-1].split("?")[0]

        def get_preview_url() -> str | None:
            spotify = spotipy.Spotify(
                auth_manager=SpotifyClientCredentials(
                    client_id=settings.spotify_client_id,
                    client_secret=settings.spotify_client_secret,
                ),
            )
            track_info = spotify.track(track_id)
            preview_url = track_info.get("preview_url")
            return str(preview_url) if preview_url else None

        try:
            return await asyncio.to_thread(get_preview_url)
        except Exception:
            logger.exception("Failed to fetch Spotify track preview")
            return None

    async def _resolve_request(self, query: str) -> QueueItem | None:
        """Resolve a user query into a playable queue item."""

        if is_spotify_url(query):
            playable_url = await self._get_spotify_audio_url(query)
            if not playable_url:
                return None
            return QueueItem(query, "spotify", playable_url)

        youtube_url = query
        if not is_youtube_url(query):
            found_url = await self._get_video_url_from_search(query)
            if not found_url:
                return None
            youtube_url = found_url

        return QueueItem(query, "youtube", youtube_url)

    async def _create_audio_source(
        self,
        item: QueueItem,
    ) -> tuple[discord.AudioSource, str | None]:
        """Create a Discord audio source from a queue item."""

        if item.source_type == "spotify":
            return discord.FFmpegPCMAudio(item.source_ref, **FFMPEG_OPTIONS), None

        source = await YTDLSource.from_url(item.source_ref)
        return source, source.title

    async def _start_item(
        self,
        item: QueueItem,
        ctx: commands.Context[commands.Bot] | None,
        *,
        announce: bool,
        retries_left: int | None = None,
    ) -> None:
        """Start playback for a resolved queue item."""

        if ctx and (not self.voice_client or not self.voice_client.is_connected()):
            if not isinstance(ctx.author, discord.Member):
                raise commands.CommandError("User is not a guild member")

            if not ctx.author.voice or not ctx.author.voice.channel:
                raise commands.CommandError("User is not connected to a voice channel")
            self.voice_client = await ctx.author.voice.channel.connect()

        if not self.voice_client:
            raise commands.CommandError("Voice client is unavailable")

        source, title = await self._create_audio_source(item)
        retries_left = self.max_retries if retries_left is None else retries_left

        self.is_playing = True
        self.voice_client.play(
            source,
            after=lambda error: self._after_play(error, item, retries_left),
        )

        if announce and ctx:
            display = title or item.request
            await ctx.send(
                embed=build_embed(
                    title="Tocar Musica",
                    description=f"Tocando: {display}",
                    color=discord.Color.green(),
                ),
            )

    async def _retry_item(self, item: QueueItem, retries_left: int) -> None:
        """Retry a YouTube item after a stream error."""

        await asyncio.sleep(RETRY_DELAY_SECONDS)
        try:
            await self._start_item(
                item,
                ctx=None,
                announce=False,
                retries_left=retries_left,
            )
        except Exception:
            logger.exception("Failed to reload audio stream")
            await self._advance_queue()

    async def _advance_queue(self) -> None:
        """Advance to the next queue item or disconnect when empty."""

        if self.queue:
            next_item = self.queue.pop(0)
            try:
                await self._start_item(next_item, ctx=self.ctx, announce=True)
            except Exception:
                logger.exception("Failed to play next queue item")
                await self._advance_queue()
            return

        self.is_playing = False
        if self.voice_client:
            await self.voice_client.disconnect()
            self.voice_client = None

    async def play(self, ctx: commands.Context[commands.Bot], query: str) -> None:
        """Resolve and play or enqueue a user music request."""

        self.ctx = ctx
        queue_item = await self._resolve_request(query)

        if not queue_item:
            await ctx.send(embed=error_embed("Nao consegui obter a musica."))
            return

        if self.is_playing:
            self.queue.append(queue_item)
            await ctx.send(
                embed=build_embed(
                    title="Adicionado",
                    description=f"Adicionado a fila: {queue_item.request}",
                    color=discord.Color.blue(),
                ),
            )
            return

        try:
            await self._start_item(queue_item, ctx=ctx, announce=True)
        except Exception:
            logger.exception("Failed to start playback")
            self.is_playing = False
            await ctx.send(embed=error_embed("Nao consegui tocar essa musica."))

    def _after_play(
        self,
        error: Exception | None,
        item: QueueItem,
        retries_left: int,
    ) -> None:
        """Handle Discord voice player completion callbacks."""

        if not self.voice_client:
            return

        if error:
            logger.warning("Audio playback error: %s", error)
            if item.source_type == "youtube" and retries_left > 0:
                asyncio.run_coroutine_threadsafe(
                    self._retry_item(item, retries_left - 1),
                    self.voice_client.loop,
                )
                return

        asyncio.run_coroutine_threadsafe(
            self._advance_queue(),
            self.voice_client.loop,
        )

    def pause(self) -> bool:
        """Pause the current track."""

        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            return True
        return False

    def resume(self) -> bool:
        """Resume the current paused track."""

        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            return True
        return False

    def skip(self) -> bool:
        """Skip the current track."""

        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
            return True
        return False


class Music(commands.Cog):
    """Music playback commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.players: dict[int, MusicPlayer] = {}

    def _get_player(self, guild_id: int) -> MusicPlayer:
        """Return a guild-scoped music player."""

        if guild_id not in self.players:
            self.players[guild_id] = MusicPlayer()
        return self.players[guild_id]

    @commands.command(
        name="play",
        help="Busca e toca videos do YouTube ou Spotify. Use: $play <termo ou URL>",
    )
    async def play_command(
        self,
        ctx: commands.Context[commands.Bot],
        *,
        query: str,
    ) -> None:
        """Play or enqueue a music request."""

        if ctx.guild is None:
            await ctx.send(embed=error_embed("Esse comando so funciona em servidor."))
            return

        if not isinstance(ctx.author, discord.Member):
            await ctx.send(embed=error_embed("Esse comando so funciona em servidor."))
            return

        if not ctx.author.voice:
            await ctx.send(
                embed=error_embed(
                    "Voce precisa estar em um canal de voz para usar este comando.",
                ),
            )
            return

        await self._get_player(ctx.guild.id).play(ctx, query)

    @commands.command(name="pause", help="Pausa a musica atual.")
    async def pause(self, ctx: commands.Context[commands.Bot]) -> None:
        """Pause the current track."""

        if ctx.guild and self._get_player(ctx.guild.id).pause():
            await ctx.send(
                embed=build_embed(
                    title="Musica Pausada",
                    description="A musica atual foi pausada.",
                    color=discord.Color.yellow(),
                ),
            )
            return

        await ctx.send(embed=error_embed("Nao ha musica tocando no momento."))

    @commands.command(name="resume", help="Retoma a musica pausada.")
    async def resume(self, ctx: commands.Context[commands.Bot]) -> None:
        """Resume the paused track."""

        if ctx.guild and self._get_player(ctx.guild.id).resume():
            await ctx.send(
                embed=build_embed(
                    title="Musica Retomada",
                    description="A musica pausada foi retomada.",
                    color=discord.Color.green(),
                ),
            )
            return

        await ctx.send(embed=error_embed("Nao ha musica pausada no momento."))

    @commands.command(name="skip", help="Pula a musica atual.")
    async def skip(self, ctx: commands.Context[commands.Bot]) -> None:
        """Skip the current track."""

        if ctx.guild and self._get_player(ctx.guild.id).skip():
            await ctx.send(
                embed=build_embed(
                    title="Musica Pulada",
                    description="A musica atual foi pulada.",
                    color=discord.Color.blue(),
                ),
            )
            return

        await ctx.send(embed=error_embed("Nao ha musica tocando no momento."))

    @commands.command(name="queue", help="Exibe a lista de espera de musicas.")
    async def queue(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show the current queue."""

        if ctx.guild is None:
            await ctx.send(embed=error_embed("Esse comando so funciona em servidor."))
            return

        player = self._get_player(ctx.guild.id)
        if player.queue:
            queue_list = "\n".join(item.request for item in player.queue)
            await ctx.send(
                embed=build_embed(
                    title="Lista de Espera",
                    description=queue_list,
                    color=discord.Color.blue(),
                ),
            )
            return

        await ctx.send(
            embed=build_embed(
                title="Lista de Espera Vazia",
                description="A lista de espera esta vazia.",
                color=discord.Color.blue(),
            ),
        )


async def setup(bot: commands.Bot) -> None:
    """Register the cog."""

    await bot.add_cog(Music(bot))
