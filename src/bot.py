import asyncio
import os
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv
from bungie import fetch_activity_images, fetch_commendation_defs
from commands import setup_commands
from database import init_db, lfg_sessions, load_sessions_from_db
from oauth import start_oauth_server
from tasks import reminder_task, cleanup_task, setup_tasks
from views import LFGView, TemplateView, RegisterTemplateView

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
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        await init_db()
        await load_sessions_from_db()
        
        @self.tree.error
        async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
            if isinstance(error, discord.app_commands.MissingPermissions):
                await interaction.response.send_message(
                    f"❌ У вас недостатньо прав для цієї команди. Потрібно: `{', '.join(error.missing_permissions)}`",
                    ephemeral=True
                )
            elif isinstance(error, discord.app_commands.BotMissingPermissions):
                await interaction.response.send_message(
                    f"❌ У бота недостатньо прав для цієї команди. Потрібно: `{', '.join(error.missing_permissions)}`",
                    ephemeral=True
                )
            else:
                logger.error(f"App Command Error: {error}", exc_info=error)
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Виникла неочікувана помилка при виконанні команди.", ephemeral=True)

        self.add_view(LFGView())
        for session in lfg_sessions.values():
            self.add_view(LFGView(session))
        
        self.add_view(TemplateView("raid"))
        self.add_view(TemplateView("dungeon"))
        self.add_view(TemplateView("pvp"))
        self.add_view(RegisterTemplateView())

        await fetch_activity_images()
        await fetch_commendation_defs()
        await start_oauth_server(self)
        setup_tasks(self)
        synced = await self.tree.sync()
        logger.info(f"Синхронізовано {len(synced)} команд(и) глобально. Завантажено сесій: {len(lfg_sessions)}")
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            guild_synced = await self.tree.sync(guild=guild)
            logger.info(f"Також синхронізовано {len(guild_synced)} команд(и) для сервера {GUILD_ID}")

    async def on_ready(self) -> None:
        logger.info(f"✅ Бот запущено: {self.user}  (ID: {self.user.id})")

bot = DestinyBot()
setup_commands(bot)

if __name__ == "__main__":
    if not TOKEN:
        logger.error("DISCORD_TOKEN не знайдено! Створіть файл .env з токеном.")
        exit(1)
    asyncio.run(bot.start(TOKEN))
