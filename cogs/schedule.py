import discord
from discord.ext import commands

class Agenda(commands.Cog):
    def __init__(self, client):
        self.client = client

    @commands.command(name="agenda", help="Lista de tarefas publicas de todos os usuários")
    async def personal_list(self, ctx):
        with open('files/list.txt') as f:
            lines = f.readlines()

        list_embed = discord.Embed(title="AGENDA PÚBLICA", description="⬇️⬇️⬇️", color=0x22408a)
        for count, line in enumerate(lines, 1):
            list_embed.add_field(name=f"**{count}**", value=f"{line}", inline=False)
        list_embed.set_footer(text="Adicione uma anotação digitando `$adicionar [anotação]` e para remover `$remover [id]`")
        await ctx.channel.send(embed=list_embed)

    @commands.command(name="adicionar")
    async def add_argument_to_list(self, ctx, content):
        with open('files/list.txt', 'a') as f:
            f.write(f"{content} | {ctx.author.mention}\n")
        await ctx.channel.send(f"**{content}** foi adicionado à sua agenda!")

    @commands.command(name="remover")
    async def remove_argument_from_list(self, ctx, numInt: int):
        with open("files/list.txt", "r") as delete_line:
            lines = delete_line.readlines()

        id = numInt - 1
        del lines[id]

        with open("files/list.txt", "w") as line_d:
            line_d.writelines(lines)

        await ctx.channel.send(f"O índice `{numInt}` foi excluído da agenda.")

async def setup(client):
    await client.add_cog(Agenda(client))
