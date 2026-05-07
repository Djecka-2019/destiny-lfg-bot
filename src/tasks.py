import logging
from datetime import datetime, timedelta

import discord
from discord.ext import tasks

from constants import TZ_KYIV
from database import lfg_sessions, upsert_session

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

        logger.info(f"[reminder] Надсилаю нагадування для {session['activity']} ({msg_id}), початок о {scheduled_str}")

        guild_id   = session.get("guild_id")
        channel_id = session.get("channel_id")
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

        session["reminder_sent"] = True
        await upsert_session(msg_id, session)


@reminder_task.before_loop
async def before_reminder() -> None:
    await _bot.wait_until_ready()
