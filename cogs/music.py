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

    async def play(self, ctx, url):
        """Inicia a reprodução da música"""
        if not self.is_playing:
            self.voice_client = await ctx.author.voice.channel.connect()
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'extractaudio': True,
            'audioformat': 'mp3',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True
        }

        if is_youtube_url(url):
            with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                audio_url = info['url']
        elif is_spotify_url(url):
            audio_url = get_spotify_audio_url(url)
        else:
            audio_url = None

        if audio_url:
            self.queue.append(audio_url)
            if not self.is_playing:
                self.is_playing = True
                self.voice_client.play(discord.FFmpegPCMAudio(audio_url), after=self.play_next)
                await ctx.send(embed=discord.Embed(title="🎶 Tocar Música", description=f"Tocando: {url}", color=discord.Color.green()))
        else:
            await ctx.send(embed=discord.Embed(title="❌ Erro", description="Não consegui obter a música.", color=discord.Color.red()))

    def play_next(self, error):
        """Toca a próxima música na fila, se existir"""
        if self.queue:
            next_url = self.queue.pop(0)
            asyncio.run_coroutine_threadsafe(self.play(self.voice_client.channel.guild, next_url), self.voice_client.loop)
        else:
            self.is_playing = False
            asyncio.run_coroutine_threadsafe(self.voice_client.disconnect(), self.voice_client.loop)

    def pause(self):
        """Pausa a música atual"""
        if self.voice_client.is_playing():
            self.voice_client.pause()
            return True
        return False

    def resume(self):
        """Retoma a música atual"""
        if self.voice_client.is_paused():
            self.voice_client.resume()
            return True
        return False

    def skip(self):
        """Pula a música atual"""
        if self.voice_client.is_playing():
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
            queue_list = "\n".join(music_player.queue)
            embed = discord.Embed(title="🎶 Lista de Espera", description=queue_list, color=discord.Color.blue())
            await ctx.send(embed=embed)
        else:
            embed = discord.Embed(title="🔇 Lista de Espera Vazia", description="A lista de espera está vazia.", color=discord.Color.blue())
            await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Music(bot))
