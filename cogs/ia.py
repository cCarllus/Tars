import discord
from discord.ext import commands
import google.generativeai as genai
import asyncio

class TARS(commands.Cog):
    def __init__(self, client):
        self.client = client
        self.cache = {}
        self.active_sessions = {}
        genai.configure(api_key='AIzaSyA9p3P_eWuXmOhHUseLbvvSYPtdxf-oVVU')

    async def clear_chat(self, user_id):
        if user_id in self.cache:
            del self.cache[user_id]

    async def process_message(self, message, question: str):
        user_id = message.author.id
        
        if user_id not in self.cache:
            self.cache[user_id] = ""

        prompt = f"{self.cache[user_id]}Você: {question}\nTARS: "

        model = genai.GenerativeModel("gemini-1.5-pro")
        response = model.generate_content(prompt)

        self.cache[user_id] += f"Você: {question}\nTARS: {response.text}\n"
        
        await message.reply(response.text, mention_author=True)
        await self.start_timer(message.channel, user_id)

    async def start_timer(self, channel, user_id):
        if user_id in self.active_sessions:
            self.active_sessions[user_id].cancel()

        self.active_sessions[user_id] = asyncio.create_task(self.timer_expired(channel, user_id))

    async def timer_expired(self, channel, user_id):
        await asyncio.sleep(50)
        
        if user_id in self.active_sessions:
            del self.active_sessions[user_id]

    @commands.command(name="start", help="Inicie uma conversa com TARS.")
    async def tars_start(self, ctx):
        user_id = ctx.author.id
        
        if user_id not in self.active_sessions:
            self.active_sessions[user_id] = True
            embed = discord.Embed(
                title="Conversa Iniciada",
                description="Você começou uma conversa com TARS. Pergunte o que quiser!",
                color=discord.Color.green()
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("Você já tem uma conversa ativa. Use `tars finish` para finalizar.")

    @commands.command(name="finish", help="Finalize a conversa com TARS.")
    async def tars_finish(self, ctx):
        user_id = ctx.author.id
        
        if user_id in self.active_sessions:
            del self.active_sessions[user_id]
            embed = discord.Embed(
                title="Conversa Finalizada",
                description="Você finalizou a conversa com TARS. Para continuar, use `tars start`.",
                color=discord.Color.red()
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("Você não tem uma conversa ativa.")

    @commands.Cog.listener()
    async def on_message(self, message):
        # Ignora mensagens do bot
        if message.author == self.client.user:
            return
        
        user_id = message.author.id

        if user_id in self.active_sessions:
            await self.process_message(message, message.content)

async def setup(client):
    await client.add_cog(TARS(client))
