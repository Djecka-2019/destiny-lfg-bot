import logging
import random
from datetime import datetime, timedelta
import discord
from discord.ext import tasks
from constants import TZ_KYIV, RAIDS, DUNGEONS, RANDOM_RAID, RANDOM_DUNGEON
from database import lfg_sessions, upsert_session, get_ping_roles
from embeds import build_lfg_embed

logger = logging.getLogger("destiny_bot")
_bot = None

def setup_tasks(bot) -> None:
    global _bot
    _bot = bot

@tasks.loop(minutes=1)
async def reminder_task() -> None:
    now = datetime.now(TZ_KYIV)
    window = timedelta(minutes=15)
    logger.debug(f"[reminder] tick {now.strftime('%H:%M:%S')}, сесій: {len(lfg_sessions)}")

    for msg_id, session in list(lfg_sessions.items()):
        if session.get("reminder_sent"):
            continue
        scheduled_str = session.get("scheduled_at")
        if not scheduled_str:
            logger.warning(f"[reminder] {msg_id}: немає scheduled_at")
            continue

        try:
            scheduled = datetime.fromisoformat(scheduled_str)
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=TZ_KYIV)
        except ValueError:
            continue

        time_left = scheduled - now
        if not (timedelta(0) <= time_left <= window):
            continue

        activity = session["activity"]
        options = session.get("options", [])
        
        if activity in (RANDOM_RAID, RANDOM_DUNGEON):
            pool = [r for r in (RAIDS if activity == RANDOM_RAID else DUNGEONS) if r not in (RANDOM_RAID, RANDOM_DUNGEON)]
            session["activity"] = random.choice(pool)
            logger.info(f"[reminder] {msg_id}: Випадково обрано {session['activity']}")
        elif options:
            votes = session.get("votes", {})
            if votes:
                tally = {}
                for v in votes.values():
                    tally[v] = tally.get(v, 0) + 1
                winner = max(tally, key=tally.get)
                session["activity"] = winner
                logger.info(f"[reminder] {msg_id}: Результат голосування — {winner}")
            else:
                session["activity"] = random.choice(options)
                logger.info(f"[reminder] {msg_id}: Голосів немає, обрано випадково — {session['activity']}")
            session["options"] = []

        logger.info(f"[reminder] Надсилаю нагадування для {session['activity']} ({msg_id}), початок о {scheduled_str}")
        guild_id   = session.get("guild_id")
        channel_id = session.get("channel_id")
        
        try:
            channel = await _bot.fetch_channel(int(channel_id))
            message = await channel.fetch_message(int(msg_id))
            await message.edit(embed=build_lfg_embed(session))
        except Exception as e:
            logger.error(f"[reminder] Не вдалося оновити повідомлення {msg_id}: {e}")

        msg_url = (
            f"https://discord.com/channels/{guild_id}/{channel_id}/{msg_id}"
            if guild_id and channel_id else None
        )
        ts = int(scheduled.timestamp())
        display_time = f"<t:{ts}:t>"
        is_raid = session["activity_type"] == "raid"
        color = discord.Color.from_rgb(255, 185, 0) if is_raid else discord.Color.from_rgb(130, 50, 210)
        embed = discord.Embed(
            title="🔔 Нагадування про активність!",
            description=(
                f"За **15 хвилин** починається "
                f"**{session['activity']}** о {display_time}!"
            ),
            color=color,
        )
        if msg_url:
            embed.add_field(name="Посилання", value=f"[Перейти до збору]({msg_url})", inline=False)

        for member_id in session["members"]:
            try:
                user = await _bot.fetch_user(int(member_id))
                await user.send(embed=embed)
                logger.info(f"[reminder] DM надіслано → {user}")
            except discord.Forbidden:
                logger.warning(f"[reminder] {member_id}: DM заблоковано (privacy settings)")
            except Exception as e:
                logger.error(f"[reminder] {member_id}: помилка — {e}")

        if len(session["members"]) < session["capacity"]:
            try:
                channel = await _bot.fetch_channel(int(channel_id))
                if channel:
                    mention_part = ""
                    ping_role_ids = await get_ping_roles(guild_id)
                    if ping_role_ids:
                        if "everyone" in ping_role_ids:
                            mention_part = "@everyone "
                        else:
                            mention_part = " ".join([f"<@&{rid}>" for rid in ping_role_ids if rid != "everyone"]) + " "
                    
                    slots_left = session["capacity"] - len(session["members"])
                    await channel.send(
                        f"📢 {mention_part}**Є вільні місця!**\n"
                        f"На **{session['activity']}** ({display_time}) залишилося **{slots_left}** місць. "
                        f"Приєднуйтесь: {msg_url}"
                    )
            except Exception as e:
                logger.error(f"[reminder] Не вдалося надіслати загальне сповіщення: {e}")

        session["reminder_sent"] = True
        await upsert_session(msg_id, session)

@reminder_task.before_loop
async def before_reminder() -> None:
    await _bot.wait_until_ready()
