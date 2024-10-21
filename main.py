import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True

client = commands.Bot(command_prefix='$', intents=intents)
client.remove_command('help')

# Carrega as cogs
@client.event
async def on_ready():
    print('Logged on as {0}!'.format(client.user))
    await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="your commands"))
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py'):
            await client.load_extension(f'cogs.{filename[:-3]}')
    print('All cogs loaded!')

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    await client.process_commands(message)

client.run(DISCORD_TOKEN)
