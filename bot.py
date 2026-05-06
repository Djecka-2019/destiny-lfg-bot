import asyncio
import json
import os
import re
from datetime import datetime, timedelta

import aiohttp
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
BUNGIE_BASE = "https://www.bungie.net"

ACTIVITY_EN_NAMES: dict[str, str] = {
    "Склеп Скла": "Vault of Glass",
    "Останнє бажання": "Last Wish",
    "Сад Порятунку": "Garden of Salvation",
    "Склеп Глибокого Каменю": "Deep Stone Crypt",
    "Обітниця послідовника": "Vow of the Disciple",
    "Падіння Короля": "King's Fall",
    "Коріння Жахів": "Root of Nightmares",
    "Кінець Кроти": "Crota's End",
    "Межа Спасіння": "Salvation's Edge",
    "Піски безкінечності": "The Desert Perpetual",
    "Яма Єресі": "Pit of Heresy",
    "Пророцтво": "Prophecy",
    "Хватка Алчності": "Grasp of Avarice",
    "Двоїстість": "Duality",
    "Шпиль Спостерігача": "Spire of the Watcher",
    "Примари Глибин": "Ghosts of the Deep",
    "Руїни Варлорда": "Warlord's Ruin",
    "Притулок Веспера": "Vesper's Host",
    "Еквілібріум": "Equilibrium",
}

activity_images: dict[str, str] = {}

RAIDS = [
    "Склеп Скла",  # Vault of Glass
    "Останнє бажання",  # Last Wish
    "Сад Порятунку",  # Garden of Salvation
    "Склеп Глибокого Каменю",  # Deep Stone Crypt
    "Обітниця послідовника",  # Vow of the Disciple
    "Падіння Короля",  # King's Fall
    "Коріння Жахів",  # Root of Nightmares
    "Кінець Кроти",  # Crota's End
    "Межа Спасіння",  # Salvation's Edge
    "Піски безкінечності"  # Desert Perpetual
]

DUNGEONS = [
    "Яма Єресі",  # Pit of Heresy
    "Пророцтво",  # Prophecy
    "Хватка Алчності",  # Grasp of Avarice
    "Двоїстість",  # Duality
    "Шпиль Спостерігача",  # Spire of the Watcher
    "Примари Глибин",  # Ghosts of the Deep
    "Руїни Варлорда",  # Warlord's Ruin
    "Притулок Веспера",  # Vesper's Host
    "Еквілібріум"  # Equilibrium
]

RAID_MAX = 6
DUNGEON_MAX = 3
DB_FILE = "lfg_sessions.db"

# In-memory cache: message_id (str) → session dict.
# Populated from DB at startup; DB is the source of truth on disk.
lfg_sessions: dict[str, dict] = {}


async def fetch_activity_images() -> None:
    api_key = os.getenv("BUNGIE_API_KEY")
    if not api_key:
        print("⚠️  BUNGIE_API_KEY не задано — прев'ю активностей вимкнено")
        return

    headers = {"X-API-Key": api_key}
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as http:
        try:
            async with http.get(
                f"{BUNGIE_BASE}/Platform/Destiny2/Manifest/", headers=headers
            ) as resp:
                if resp.status != 200:
                    print(f"⚠️  Bungie Manifest HTTP {resp.status}")
                    return
                manifest = await resp.json()
        except Exception as e:
            print(f"⚠️  Не вдалося отримати маніфест Bungie: {e}")
            return

        try:
            def_path = manifest["Response"]["jsonWorldComponentContentPaths"]["en"][
                "DestinyActivityDefinition"
            ]
        except KeyError:
            print("⚠️  Несподівана структура маніфесту Bungie")
            return

        try:
            async with http.get(f"{BUNGIE_BASE}{def_path}") as resp:
                if resp.status != 200:
                    print(f"⚠️  DestinyActivityDefinition HTTP {resp.status}")
                    return
                activity_defs: dict = await resp.json(content_type=None)
        except Exception as e:
            print(f"⚠️  Не вдалося завантажити DestinyActivityDefinition: {e}")
            return

    _INVALID = ("missing_icon", "placeholder.jpg")

    en_to_image: dict[str, str] = {}
    for entry in activity_defs.values():
        en_name: str = entry.get("displayProperties", {}).get("name", "").strip()
        pgcr: str = entry.get("pgcrImage", "").strip()
        valid = bool(pgcr) and not any(m in pgcr for m in _INVALID)
        if en_name and valid and en_name not in en_to_image:
            en_to_image[en_name] = f"{BUNGIE_BASE}{pgcr}"

    found = 0
    for uk_name, en_name in ACTIVITY_EN_NAMES.items():
        url = en_to_image.get(en_name)
        if not url:
            url = en_to_image.get(f"{en_name}: Standard")
        if not url:
            prefix = f"{en_name}: "
            url = next(
                (img for n, img in en_to_image.items() if n.startswith(prefix)),
                None,
            )
        if url:
            activity_images[uk_name] = url
            found += 1

    print(f"Прев’ю активностей: {found}/{len(ACTIVITY_EN_NAMES)} знайдено")


async def init_db() -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                message_id    TEXT PRIMARY KEY,
                activity      TEXT NOT NULL,
                activity_type TEXT NOT NULL,
                time_str      TEXT NOT NULL,
                description   TEXT NOT NULL DEFAULT '',
                leader_id     TEXT NOT NULL,
                leader_name   TEXT NOT NULL,
                capacity      INTEGER NOT NULL,
                thread_id     TEXT,
                members       TEXT NOT NULL DEFAULT '[]',
                guild_id      TEXT,
                channel_id    TEXT,
                scheduled_at  TEXT,
                reminder_sent INTEGER NOT NULL DEFAULT 0
            )
        """)
        for col, typedef in [
            ("guild_id",      "TEXT"),
            ("channel_id",    "TEXT"),
            ("scheduled_at",  "TEXT"),
            ("reminder_sent", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                await db.execute(f"ALTER TABLE sessions ADD COLUMN {col} {typedef}")
            except aiosqlite.OperationalError:
                pass  # Column already exists
        await db.commit()


async def load_sessions_from_db() -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM sessions") as cursor:
            async for row in cursor:
                lfg_sessions[row["message_id"]] = {
                    "activity":      row["activity"],
                    "activity_type": row["activity_type"],
                    "time":          row["time_str"],
                    "description":   row["description"],
                    "leader_id":     row["leader_id"],
                    "leader_name":   row["leader_name"],
                    "capacity":      row["capacity"],
                    "thread_id":     row["thread_id"],
                    "members":       json.loads(row["members"]),
                    "guild_id":      row["guild_id"],
                    "channel_id":    row["channel_id"],
                    "scheduled_at":  row["scheduled_at"],
                    "reminder_sent": bool(row["reminder_sent"]),
                }


async def upsert_session(message_id: str, session: dict) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute(
            """
            INSERT INTO sessions
                (message_id, activity, activity_type, time_str, description,
                 leader_id, leader_name, capacity, thread_id, members,
                 guild_id, channel_id, scheduled_at, reminder_sent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                thread_id     = excluded.thread_id,
                members       = excluded.members,
                reminder_sent = excluded.reminder_sent
            """,
            (
                message_id,
                session["activity"],
                session["activity_type"],
                session["time"],
                session.get("description", ""),
                session["leader_id"],
                session["leader_name"],
                session["capacity"],
                session.get("thread_id"),
                json.dumps(session["members"]),
                session.get("guild_id"),
                session.get("channel_id"),
                session.get("scheduled_at"),
                int(session.get("reminder_sent", False)),
            ),
        )
        await db.commit()


async def delete_session(message_id: str) -> None:
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("DELETE FROM sessions WHERE message_id = ?", (message_id,))
        await db.commit()

def build_lfg_embed(session: dict, closed: bool = False) -> discord.Embed:
    activity = session["activity"]
    activity_type = session["activity_type"]
    time_str = session["time"]
    description = session.get("description", "")
    members: list = session["members"]
    capacity: int = session["capacity"]
    leader_id = session["leader_id"]
    leader_name = session["leader_name"]

    is_raid = activity_type == "raid"
    if closed:
        color = discord.Color.dark_gray()
    elif is_raid:
        color = discord.Color.from_rgb(255, 185, 0)
    else:
        color = discord.Color.from_rgb(130, 50, 210)

    activity_label = "Рейд" if is_raid else "Данж"
    emoji = "⚔️" if is_raid else "🗡️"

    embed = discord.Embed(
        title=f"{emoji} {activity_label}: {activity}",
        color=color,
    )
    embed.add_field(name="⏰ Час початку", value=f"**{time_str}**", inline=True)
    embed.add_field(name="👥 Місця", value=f"**{len(members)}/{capacity}**", inline=True)
    embed.add_field(name="​", value="​", inline=True)

    if description:
        embed.add_field(name="📝 Опис / вимоги", value=description, inline=False)

    slots_lines = []
    for i in range(capacity):
        if i < len(members):
            mid = members[i]
            crown = " 👑" if mid == leader_id else ""
            slots_lines.append(f"`{i + 1}.` <@{mid}>{crown}")
        else:
            slots_lines.append(f"`{i + 1}.` *Вільне місце*")
    embed.add_field(name="👤 Учасники", value="\n".join(slots_lines), inline=False)

    if closed:
        status = "🔒 Збір закрито"
    elif len(members) >= capacity:
        status = "🔴 Набір завершено"
    else:
        status = "✅ Набір відкрито"

    embed.set_footer(text=f"Організатор: {leader_name}  •  {status}")

    image_url = activity_images.get(activity)
    if image_url:
        embed.set_image(url=image_url)

    return embed

class LFGView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="➕ Приєднатись / Вийти",
        style=discord.ButtonStyle.green,
        custom_id="lfg:join_toggle",
        emoji="🎮",
    )
    async def join_toggle(
            self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()

        msg_id = str(interaction.message.id)
        session = lfg_sessions.get(msg_id)
        if not session:
            await interaction.followup.send("Ця активність більше не активна.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        members: list = session["members"]

        if user_id in members:
            members.remove(user_id)
            joined = False
        else:
            if len(members) >= session["capacity"]:
                await interaction.followup.send("❌ Немає вільних місць!", ephemeral=True)
                return
            members.append(user_id)
            joined = True

        await upsert_session(msg_id, session)

        await interaction.message.edit(embed=build_lfg_embed(session), view=self)

        thread_id = session.get("thread_id")
        if thread_id:
            thread = interaction.guild.get_thread(int(thread_id))
            if thread:
                if joined:
                    await thread.send(
                        f"🟢 {interaction.user.mention} **приєднався(-лась)** до активності!"
                    )
                else:
                    await thread.send(
                        f"🔴 {interaction.user.mention} **покинув(-ла)** активність."
                    )

    @discord.ui.button(
        label="Закрити збір",
        style=discord.ButtonStyle.red,
        custom_id="lfg:close",
        emoji="🔒",
    )
    async def close_lfg(
            self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()

        msg_id = str(interaction.message.id)
        session = lfg_sessions.get(msg_id)
        if not session:
            await interaction.followup.send("Ця активність вже не активна.", ephemeral=True)
            return

        if str(interaction.user.id) != session["leader_id"]:
            await interaction.followup.send(
                "❌ Лише організатор може закрити збір.", ephemeral=True
            )
            return

        for item in self.children:
            item.disabled = True

        await interaction.message.edit(embed=build_lfg_embed(session, closed=True), view=self)

        thread_id = session.get("thread_id")
        if thread_id:
            thread = interaction.guild.get_thread(int(thread_id))
            if thread:
                await thread.send("🔒 **Збір закрито організатором.**")
                try:
                    await thread.edit(archived=True, locked=True)
                except discord.HTTPException:
                    pass

        del lfg_sessions[msg_id]
        await delete_session(msg_id)

class ActivitySelect(discord.ui.Select):
    def __init__(self, activities: list[str], activity_type: str) -> None:
        self._activities = activities
        self._activity_type = activity_type
        emoji = "⚔️" if activity_type == "raid" else "🗡️"
        options = [
            discord.SelectOption(label=name, value=str(i), emoji=emoji)
            for i, name in enumerate(activities)
        ]
        label = "рейд" if activity_type == "raid" else "данж"
        super().__init__(
            placeholder=f"Оберіть {label}...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        idx = int(self.values[0])
        activity_name = self._activities[idx]
        await interaction.response.send_modal(LFGModal(activity_name, self._activity_type))


class ActivitySelectView(discord.ui.View):
    def __init__(self, activities: list[str], activity_type: str) -> None:
        super().__init__(timeout=120)
        self.add_item(ActivitySelect(activities, activity_type))

class LFGModal(discord.ui.Modal, title="Налаштування збору"):
    time_input = discord.ui.TextInput(
        label="Час початку (ГГ:ХХ)",
        placeholder="Наприклад: 20:00",
        min_length=4,
        max_length=5,
        required=True,
    )
    description_input = discord.ui.TextInput(
        label="Опис / вимоги (необов'язково)",
        style=discord.TextStyle.paragraph,
        placeholder="Наприклад: потрібен досвід, мікрофон обов'язковий...",
        required=False,
        max_length=500,
    )

    def __init__(self, activity_name: str, activity_type: str) -> None:
        super().__init__()
        self._activity_name = activity_name
        self._activity_type = activity_type

    async def on_submit(self, interaction: discord.Interaction) -> None:
        time_str = self.time_input.value.strip()

        if not re.match(r"^\d{1,2}:\d{2}$", time_str):
            await interaction.response.send_message(
                "❌ Невірний формат часу! Введіть час у форматі ГГ:ХХ (наприклад: 20:00)",
                ephemeral=True,
            )
            return

        h, m = map(int, time_str.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            await interaction.response.send_message(
                "❌ Невірний час! Години: 00–23, хвилини: 00–59",
                ephemeral=True,
            )
            return

        time_str = f"{h:02d}:{m:02d}"
        capacity = RAID_MAX if self._activity_type == "raid" else DUNGEON_MAX
        leader_id = str(interaction.user.id)
        description = self.description_input.value.strip()

        now = datetime.now()
        scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if scheduled <= now:
            scheduled += timedelta(days=1)

        session: dict = {
            "activity":      self._activity_name,
            "activity_type": self._activity_type,
            "time":          time_str,
            "description":   description,
            "leader_id":     leader_id,
            "leader_name":   interaction.user.display_name,
            "members":       [leader_id],
            "capacity":      capacity,
            "thread_id":     None,
            "guild_id":      str(interaction.guild_id),
            "channel_id":    str(interaction.channel_id),
            "scheduled_at":  scheduled.isoformat(),
            "reminder_sent": False,
        }

        view = LFGView()
        await interaction.response.send_message(embed=build_lfg_embed(session), view=view)
        message = await interaction.original_response()

        activity_label = "Рейд" if self._activity_type == "raid" else "Данж"
        try:
            thread = await message.create_thread(
                name=f"[{activity_label}] {self._activity_name} о {time_str}",
                auto_archive_duration=1440,
            )
            await thread.send(
                f"🎮 **Збір відкрито!** {interaction.user.mention} організує "
                f"**{self._activity_name}** о **{time_str}**.\n"
                f"Натисніть **➕ Приєднатись / Вийти** під повідомленням, щоб долучитися. "
                f"Тут можна обговорювати активність."
            )
            session["thread_id"] = str(thread.id)
        except discord.HTTPException as e:
            print(f"Не вдалося створити гілку: {e}")

        msg_id = str(message.id)
        lfg_sessions[msg_id] = session
        await upsert_session(msg_id, session)

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
        synced = await self.tree.sync()
        print(f"Синхронізовано {len(synced)} команд(и). Завантажено сесій: {len(lfg_sessions)}")

    async def on_ready(self) -> None:
        print(f"✅ Бот запущено: {self.user}  (ID: {self.user.id})")
        if not reminder_task.is_running():
            reminder_task.start()


bot = DestinyBot()


@tasks.loop(minutes=1)
async def reminder_task() -> None:
    now = datetime.now()
    window = timedelta(minutes=15)

    for msg_id, session in list(lfg_sessions.items()):
        if session.get("reminder_sent"):
            continue
        scheduled_str = session.get("scheduled_at")
        if not scheduled_str:
            continue

        try:
            scheduled = datetime.fromisoformat(scheduled_str)
        except ValueError:
            continue

        time_left = scheduled - now
        if not (timedelta(0) <= time_left <= window):
            continue

        guild_id   = session.get("guild_id")
        channel_id = session.get("channel_id")
        msg_url = (
            f"https://discord.com/channels/{guild_id}/{channel_id}/{msg_id}"
            if guild_id and channel_id else None
        )

        is_raid = session["activity_type"] == "raid"
        color = discord.Color.from_rgb(255, 185, 0) if is_raid else discord.Color.from_rgb(130, 50, 210)
        embed = discord.Embed(
            title="🔔 Нагадування про активність!",
            description=(
                f"За **15 хвилин** починається "
                f"**{session['activity']}** о **{session['time']}**!"
            ),
            color=color,
        )
        if msg_url:
            embed.add_field(name="Посилання", value=f"[Перейти до збору]({msg_url})", inline=False)

        for member_id in session["members"]:
            try:
                user = await bot.fetch_user(int(member_id))
                await user.send(embed=embed)
            except discord.Forbidden:
                pass  # User has DMs closed
            except Exception as e:
                print(f"Помилка нагадування для {member_id}: {e}")

        session["reminder_sent"] = True
        await upsert_session(msg_id, session)


@reminder_task.before_loop
async def before_reminder() -> None:
    await bot.wait_until_ready()


@bot.tree.command(name="пошук-рейдів", description="Створити збір на рейд в Destiny 2")
async def search_raids(interaction: discord.Interaction) -> None:
    view = ActivitySelectView(RAIDS, "raid")
    await interaction.response.send_message(
        "⚔️ **Оберіть рейд для збору:**", view=view, ephemeral=True
    )


@bot.tree.command(name="пошук-данжів", description="Створити збір на данж в Destiny 2")
async def search_dungeons(interaction: discord.Interaction) -> None:
    view = ActivitySelectView(DUNGEONS, "dungeon")
    await interaction.response.send_message(
        "🗡️ **Оберіть данж для збору:**", view=view, ephemeral=True
    )


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN не знайдено! Створіть файл .env з токеном.")
    asyncio.run(bot.start(TOKEN))
