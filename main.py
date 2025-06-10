import asyncio
import disnake
from disnake import *
from disnake.ext import commands
import os
import traceback

from config import Token, Prefix
from utils.database import init_db, get_pool

activity = disnake.Game(name="Казино | .help")

intents = disnake.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    intents=intents,
    activity=activity,
    command_prefix=Prefix
)
# bot.remove_command("help")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, (commands.CommandNotFound,)):
        return

# Фоновая keep-alive задача, чтобы пул соединений не "засыпал"
async def keepalive():
    # Даем ботy время полностью стартануть
    await asyncio.sleep(5)
    pool = await get_pool()
    while True:
        try:
            async with pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1;")
        except Exception as e:
            # не даем задаче умереть
            print(f"DB keepalive error: {e}")
        # пинг каждые 2 минуты
        await asyncio.sleep(120)

for file in os.listdir('./cogs'):
    if file.endswith('.py') and file != '__init__.py':
        try:
            bot.load_extension(f"cogs.{file[:-3]}")
            print(f"{file[:-3]} Loaded successfully.")
        except:
            print(f"Unable to load {file[:-3]}.")
            print(traceback.format_exc())

@bot.event
async def on_ready():
    print('Бот готов пахать')
    await init_db()
    # Запускаем keep-alive, чтобы база не приостанавливалась
    bot.loop.create_task(keepalive())
    print('База данных определена и keep-alive запущен')

bot.run(Token)
