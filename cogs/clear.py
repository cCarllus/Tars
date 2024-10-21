import discord
from discord.ext import commands

class Clear(commands.Cog):
    def __init__(self, client):
        self.client = client

    @commands.command(name="limpar", help="Limpa mensagens do chat. Use: !limpar <quantidade>")
    async def clear(self, ctx, max: int = 5):
        if max >= 150:
            await ctx.send(f"{ctx.author.mention} **Você não pode apagar tantas mensagens**")
        else:
            await ctx.channel.purge(limit=max)
            await ctx.send(f"👌 {ctx.author.mention} Mensagens apagadas com sucesso 👌 ")

async def setup(client):
    await client.add_cog(Clear(client))
