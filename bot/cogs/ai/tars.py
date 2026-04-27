"""Conversational AI commands for TARS."""

import asyncio

import discord
import google.generativeai as genai
from discord.ext import commands

from bot.config import settings
from bot.logger import logger
from bot.utils.embed import error_embed, success_embed

SESSION_TIMEOUT_SECONDS = 50
MODEL_NAME = "gemini-1.5-pro"


class Tars(commands.Cog):
    """Conversation session manager backed by Google Gemini."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.cache: dict[int, str] = {}
        self.active_sessions: dict[int, asyncio.Task[None]] = {}

        if settings.gemini_api_key:
            genai.configure(api_key=settings.gemini_api_key)

    async def cog_unload(self) -> None:
        """Cancel active session timers when the cog unloads."""

        for task in self.active_sessions.values():
            task.cancel()

    async def clear_chat(self, user_id: int) -> None:
        """Clear cached conversation history for a user."""

        self.cache.pop(user_id, None)

    async def process_message(self, message: discord.Message, question: str) -> None:
        """Send a user message to Gemini and reply with the model response."""

        if not settings.gemini_api_key:
            await message.reply(
                embed=error_embed("GEMINI_API_KEY nao esta configurada."),
                mention_author=True,
            )
            return

        user_id = message.author.id
        previous_context = self.cache.get(user_id, "")
        prompt = f"{previous_context}Voce: {question}\nTARS: "

        try:
            model = genai.GenerativeModel(MODEL_NAME)
            response = await asyncio.to_thread(model.generate_content, prompt)
        except Exception:
            logger.exception("Failed to generate Gemini response")
            await message.reply(
                embed=error_embed("Nao consegui gerar uma resposta agora."),
                mention_author=True,
            )
            return

        response_text = response.text.strip()
        self.cache[user_id] = (
            f"{previous_context}Voce: {question}\nTARS: {response_text}\n"
        )

        await message.reply(response_text, mention_author=True)
        self.start_timer(message.channel, user_id)

    def start_timer(self, channel: discord.abc.Messageable, user_id: int) -> None:
        """Restart the inactivity timer for a user session."""

        existing_task = self.active_sessions.get(user_id)
        if existing_task:
            existing_task.cancel()

        self.active_sessions[user_id] = asyncio.create_task(
            self.timer_expired(channel, user_id),
        )

    async def timer_expired(
        self,
        channel: discord.abc.Messageable,
        user_id: int,
    ) -> None:
        """Close a user session after inactivity."""

        try:
            await asyncio.sleep(SESSION_TIMEOUT_SECONDS)
            self.active_sessions.pop(user_id, None)
            self.cache.pop(user_id, None)
        except asyncio.CancelledError:
            logger.debug("Cancelled TARS session timer for user %s", user_id)

    @commands.command(name="start", help="Inicie uma conversa com TARS.")
    async def tars_start(self, ctx: commands.Context[commands.Bot]) -> None:
        """Start a conversation session with TARS."""

        user_id = ctx.author.id
        if user_id in self.active_sessions:
            await ctx.send("Voce ja tem uma conversa ativa. Use `$finish`.")
            return

        self.start_timer(ctx.channel, user_id)
        await ctx.send(
            embed=success_embed(
                "Voce comecou uma conversa com TARS. Pergunte o que quiser!",
                title="Conversa Iniciada",
            ),
        )

    @commands.command(name="finish", help="Finalize a conversa com TARS.")
    async def tars_finish(self, ctx: commands.Context[commands.Bot]) -> None:
        """Finish a conversation session with TARS."""

        user_id = ctx.author.id
        task = self.active_sessions.pop(user_id, None)
        if task is None:
            await ctx.send("Voce nao tem uma conversa ativa.")
            return

        task.cancel()
        await self.clear_chat(user_id)
        await ctx.send(
            embed=success_embed(
                "Voce finalizou a conversa com TARS. Para continuar, use `$start`.",
                title="Conversa Finalizada",
            ),
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Process regular messages while a user has an active session."""

        if message.author.bot:
            return

        if not isinstance(message.author, discord.Member):
            return

        if message.content.startswith(settings.command_prefix):
            return

        if message.author.id in self.active_sessions:
            await self.process_message(message, message.content)


async def setup(bot: commands.Bot) -> None:
    """Register the cog."""

    await bot.add_cog(Tars(bot))
