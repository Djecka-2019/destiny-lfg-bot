import asyncio
import os
import logging

import discord
from discord.ext import commands
from dotenv import load_dotenv

from bungie import fetch_activity_images
from commands import setup_commands
from database import init_db, lfg_sessions, load_sessions_from_db
from tasks import reminder_task, setup_tasks
from views import LFGView

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("destiny_bot")

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")


class DestinyBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        await init_db()
        await load_sessions_from_db()
        self.add_view(LFGView())
        await fetch_activity_images()
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            guild_synced = await self.tree.sync(guild=guild)
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            logger.info(f"Синхронізовано {len(guild_synced)} команд(и) для сервера {GUILD_ID}. Завантажено сесій: {len(lfg_sessions)}")
        else:
            synced = await self.tree.sync()
            logger.info(f"Синхронізовано {len(synced)} команд(и) глобально. Завантажено сесій: {len(lfg_sessions)}")

    async def on_ready(self) -> None:
        logger.info(f"✅ Бот запущено: {self.user}  (ID: {self.user.id})")
        if not reminder_task.is_running():
            reminder_task.start()


bot = DestinyBot()
setup_commands(bot)
setup_tasks(bot)

if __name__ == "__main__":
    if not TOKEN:
        logger.error("DISCORD_TOKEN не знайдено! Створіть файл .env з токеном.")
        exit(1)
    asyncio.run(bot.start(TOKEN))
