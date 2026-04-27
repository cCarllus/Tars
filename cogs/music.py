import os
import re
import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
import googleapiclient.discovery
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

YOUTUBE_URL_REGEX = r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/.+$'
SPOTIFY_URL_REGEX = r'https://open\.spotify\.com/track/\w+'

RETRY_DELAY_SECONDS = 2
MAX_RETRIES = 2

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True
}

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.webpage_url = data.get('webpage_url')

    @classmethod
    async def from_url(cls, url, *, loop=None):
        loop = loop or asyncio.get_running_loop()
        data = await loop.run_in_executor(
            None,
            lambda: youtube_dl.YoutubeDL(YDL_OPTIONS).extract_info(url, download=False)
        )
        if 'entries' in data:
            data = data['entries'][0]
        return cls(discord.FFmpegPCMAudio(data['url'], **FFMPEG_OPTIONS), data=data)

def is_youtube_url(query: str) -> bool:
    """Verifica se a string é uma URL do YouTube"""
    return re.match(YOUTUBE_URL_REGEX, query) is not None

def is_spotify_url(query: str) -> bool:
    """Verifica se a string é uma URL do Spotify"""
    return re.match(SPOTIFY_URL_REGEX, query) is not None

def get_video_url_from_search(query: str):
    """Busca um vídeo no YouTube e retorna a URL do primeiro resultado"""
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=os.getenv('YOUTUBE_API_KEY'))

    request = youtube.search().list(
        part="snippet",
        maxResults=1,
        q=query,
        type="video"
    )
    response = request.execute()
    
    if response['items']:
        video = response['items'][0]
        video_id = video['id']['videoId']
        return f"https://www.youtube.com/watch?v={video_id}"
    else:
        return None

def get_spotify_audio_url(url):
    # Extraia o ID da faixa da URL
    track_id = url.split("/")[-1].split("?")[0]  # Obtém a parte do ID

    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=os.getenv('SPOTIFY_CLIENT_ID'), client_secret=os.getenv('SPOTIFY_CLIENT_SECRET')))
    
    try:
        track_info = sp.track(track_id)
        # Verifica se a chave 'preview_url' está presente
        if 'preview_url' in track_info:
            return track_info['preview_url']  # Retorna a URL de pré-visualização do Spotify
        else:
            raise ValueError("Esta faixa não possui uma URL de pré-visualização.")
    except Exception as e:
        print(f"Erro ao obter informações da faixa: {e}")
        return None


class MusicPlayer:
    """Classe para gerenciar a reprodução de música"""
    def __init__(self):
        self.queue = []
        self.is_playing = False
        self.voice_client = None
        self.ctx = None
        self.max_retries = MAX_RETRIES

    def _make_queue_item(self, request, source_type, source_ref):
        return {
            "request": request,
            "source_type": source_type,
            "source_ref": source_ref
        }

    def _resolve_request(self, url):
        if is_spotify_url(url):
            playable_url = get_spotify_audio_url(url)
            if not playable_url:
                return None
            return self._make_queue_item(url, "spotify", playable_url)

        youtube_url = url
        if not is_youtube_url(url):
            youtube_url = get_video_url_from_search(url)
        if not youtube_url:
            return None
        return self._make_queue_item(url, "youtube", youtube_url)

    async def _create_audio_source(self, item):
        if item["source_type"] == "spotify":
            return discord.FFmpegPCMAudio(item["source_ref"], **FFMPEG_OPTIONS), None
        source = await YTDLSource.from_url(item["source_ref"])
        return source, source.title

    async def _start_item(self, item, ctx, *, announce, retries_left=None):
        if ctx and (not self.voice_client or not self.voice_client.is_connected()):
            self.voice_client = await ctx.author.voice.channel.connect()

        source, title = await self._create_audio_source(item)
        retries_left = self.max_retries if retries_left is None else retries_left

        self.is_playing = True
        self.voice_client.play(
            source,
            after=lambda e: self._after_play(e, item, retries_left)
        )

        if announce and ctx:
            display = title or item["request"]
            await ctx.send(
                embed=discord.Embed(
                    title="🎶 Tocar Música",
                    description=f"Tocando: {display}",
                    color=discord.Color.green()
                )
            )

    async def _retry_item(self, item, retries_left):
        await asyncio.sleep(RETRY_DELAY_SECONDS)
        try:
            await self._start_item(item, ctx=None, announce=False, retries_left=retries_left)
        except Exception as e:
            print(f"Falha ao recarregar stream: {e}")
            await self._advance_queue()

    async def _advance_queue(self):
        if self.queue:
            next_item = self.queue.pop(0)
            try:
                await self._start_item(next_item, ctx=self.ctx, announce=True)
            except Exception as e:
                print(f"Erro ao tocar próximo item: {e}")
                await self._advance_queue()
        else:
            self.is_playing = False
            if self.voice_client:
                await self.voice_client.disconnect()

    async def play(self, ctx, url):
        """Inicia a reprodução da música"""
        if ctx:
            self.ctx = ctx
        try:
            queue_item = self._resolve_request(url)
        except Exception as e:
            print(f"Erro ao resolver a música: {e}")
            queue_item = None

        if not queue_item:
            await ctx.send(embed=discord.Embed(title="❌ Erro", description="Não consegui obter a música.", color=discord.Color.red()))
            return

        if self.is_playing:
            self.queue.append(queue_item)
            await ctx.send(embed=discord.Embed(title="✅ Adicionado", description=f"Adicionado à fila: {queue_item['request']}", color=discord.Color.blue()))
            return
        try:
            await self._start_item(queue_item, ctx=ctx, announce=True)
        except Exception as e:
            print(f"Erro ao iniciar reprodução: {e}")
            self.is_playing = False
            await ctx.send(embed=discord.Embed(title="❌ Erro", description="Não consegui tocar essa música.", color=discord.Color.red()))

    def _after_play(self, error, item, retries_left):
        if error:
            print(f"Erro detectado, recarregando stream... {error}")
            if item["source_type"] == "youtube" and retries_left > 0:
                asyncio.run_coroutine_threadsafe(
                    self._retry_item(item, retries_left - 1),
                    self.voice_client.loop
                )
                return
        asyncio.run_coroutine_threadsafe(self._advance_queue(), self.voice_client.loop)

    def pause(self):
        """Pausa a música atual"""
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            return True
        return False

    def resume(self):
        """Retoma a música atual"""
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            return True
        return False

    def skip(self):
        """Pula a música atual"""
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
            return True
        return False

music_player = MusicPlayer()

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='play', help='Busca e toca vídeos do YouTube ou Spotify. Use: !play <termo ou URL>')
    async def play_command(self, ctx, *, query: str):
        if ctx.author.voice:  # Verifica se o usuário está em um canal de voz
            await music_player.play(ctx, query)
        else:
            embed = discord.Embed(title="⚠️ Erro", description="Você precisa estar em um canal de voz para usar este comando!", color=discord.Color.red())
            await ctx.send(embed=embed)

    @commands.command(name='pause', help='Pausa a música atual.')
    async def pause(self, ctx):
        if music_player.pause():
            embed = discord.Embed(title="⏸️ Música Pausada", description="A música atual foi pausada.", color=discord.Color.yellow())
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(title="❌ Erro", description="Não há música tocando no momento.", color=discord.Color.red())
            await ctx.send(embed=embed)

    @commands.command(name='resume', help='Retoma a música pausada.')
    async def resume(self, ctx):
        if music_player.resume():
            embed = discord.Embed(title="▶️ Música Retomada", description="A música pausada foi retomada.", color=discord.Color.green())
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(title="❌ Erro", description="Não há música pausada no momento.", color=discord.Color.red())
            await ctx.send(embed=embed)

    @commands.command(name='skip', help='Pula a música atual.')
    async def skip(self, ctx):
        if music_player.skip():
            embed = discord.Embed(title="⏭️ Música Pulada", description="A música atual foi pulada.", color=discord.Color.blue())
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(title="❌ Erro", description="Não há música tocando no momento.", color=discord.Color.red())
            await ctx.send(embed=embed)

    @commands.command(name='queue', help='Exibe a lista de espera de músicas.')
    async def queue(self, ctx):
        if music_player.queue:
            queue_list = "\n".join(item["request"] for item in music_player.queue)
            embed = discord.Embed(title="🎶 Lista de Espera", description=queue_list, color=discord.Color.blue())
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(title="🔇 Lista de Espera Vazia", description="A lista de espera está vazia.", color=discord.Color.blue())
            await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Music(bot))
