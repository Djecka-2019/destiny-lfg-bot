import os
import logging
import random
from datetime import datetime, timedelta
import discord
from discord.ext import tasks
from constants import TZ_KYIV, RAIDS, DUNGEONS, RANDOM_RAID, RANDOM_DUNGEON
from database import lfg_sessions, upsert_session, delete_session, get_all_profiles
from embeds import build_lfg_embed
from bungie import get_sync_stats
from role_sync import sync_member_roles

logger = logging.getLogger("destiny_bot")
_bot = None

def setup_tasks(bot) -> None:
    global _bot
    _bot = bot
    reminder_task.start()
    cleanup_task.start()
    periodic_role_sync.start()

@tasks.loop(hours=6)
async def periodic_role_sync() -> None:
    """Періодично синхронізує ролі для всіх зареєстрованих користувачів."""
    if not _bot:
        return

    guild_id = os.getenv("GUILD_ID")
    if not guild_id:
        logger.warning("Periodic Sync: GUILD_ID не задано")
        return

    try:
        guild = _bot.get_guild(int(guild_id))
        if not guild:
            guild = await _bot.fetch_guild(int(guild_id))
    except Exception as e:
        logger.error(f"Periodic Sync: не вдалося отримати гільдію: {e}")
        return

    profiles = await get_all_profiles()
    logger.info(f"Periodic Sync: запуск для {len(profiles)} профілів")

    for profile in profiles:
        discord_id = profile["discord_id"]
        try:
            member = guild.get_member(int(discord_id))
            if not member:
                member = await guild.fetch_member(int(discord_id))
            
            if member:
                stats = await get_sync_stats(profile["membership_type"], profile["membership_id"])
                if stats:
                    await sync_member_roles(member, stats)
        except discord.NotFound:
            logger.info(f"Periodic Sync: користувач {discord_id} не знайдений на сервері")
        except Exception as e:
            logger.error(f"Periodic Sync error for {discord_id}: {e}")

    logger.info("Periodic Sync: завершено")

@periodic_role_sync.before_loop
async def before_periodic_sync():
    await _bot.wait_until_ready()

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
                    mention = session.get("mention")
                    if mention == "everyone":
                        mention_part = "@everyone "
                    elif mention:
                        mention_part = f"<@&{mention}> "
                    else:
                        mention_part = ""
                    
                    slots_left = session["capacity"] - len(session["members"])
                    reminder_msg = await channel.send(
                        f"📢 {mention_part}**Є вільні місця!**\n"
                        f"На **{session['activity']}** ({display_time}) залишилося **{slots_left}** місць. "
                        f"Приєднуйтесь: {msg_url}",
                        allowed_mentions=discord.AllowedMentions(everyone=True, roles=True, users=True)
                    )
                    session["reminder_msg_id"] = str(reminder_msg.id)
            except Exception as e:
                logger.error(f"[reminder] Не вдалося надіслати загальне сповіщення: {e}")

        session["reminder_sent"] = True
        await upsert_session(msg_id, session)

@tasks.loop(minutes=30)
async def cleanup_task() -> None:
    now = datetime.now(TZ_KYIV)
    logger.info(f"[cleanup] Checking for expired sessions...")
    
    deleted_count = 0
    for msg_id, session in list(lfg_sessions.items()):
        scheduled_str = session.get("scheduled_at")
        if not scheduled_str:
            continue
            
        try:
            scheduled = datetime.fromisoformat(scheduled_str)
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=TZ_KYIV)
        except ValueError:
            continue
            
        if now > scheduled + timedelta(hours=3):
            logger.info(f"[cleanup] Deleting session {msg_id} (started at {scheduled_str})")
            channel_id = session.get("channel_id")
            thread_id = session.get("thread_id")
            reminder_msg_id = session.get("reminder_msg_id")
            
            should_delete_db = True
            channel = None
            try:
                channel = await _bot.fetch_channel(int(channel_id))
            except discord.NotFound:
                logger.info(f"[cleanup] Channel {channel_id} not found, session {msg_id} will be removed from DB.")
            except discord.Forbidden:
                logger.warning(f"[cleanup] Access forbidden to channel {channel_id}, session {msg_id} will be removed from DB.")
            except Exception as e:
                logger.error(f"[cleanup] Error fetching channel {channel_id}: {e}")
                should_delete_db = False

            if channel:
                try:
                    message = await channel.fetch_message(int(msg_id))
                    await message.delete()
                except discord.NotFound:
                    pass
                except discord.Forbidden:
                    logger.warning(f"[cleanup] Forbidden to delete message {msg_id} in channel {channel_id}")
                except Exception as e:
                    logger.error(f"[cleanup] Error deleting message {msg_id}: {e}")
                    should_delete_db = False
                
                if reminder_msg_id:
                    try:
                        rem_msg = await channel.fetch_message(int(reminder_msg_id))
                        await rem_msg.delete()
                    except discord.NotFound:
                        pass
                    except discord.Forbidden:
                        logger.warning(f"[cleanup] Forbidden to delete reminder message {reminder_msg_id}")
                    except Exception as e:
                        logger.error(f"[cleanup] Error deleting reminder message {reminder_msg_id}: {e}")

            if thread_id:
                try:
                    thread = await _bot.fetch_channel(int(thread_id))
                    await thread.delete()
                except discord.NotFound:
                    pass
                except discord.Forbidden:
                    logger.warning(f"[cleanup] Forbidden to delete thread {thread_id}")
                except Exception as e:
                    logger.error(f"[cleanup] Error deleting thread {thread_id}: {e}")
            
            if should_delete_db:
                if msg_id in lfg_sessions:
                    del lfg_sessions[msg_id]
                await delete_session(msg_id)
                deleted_count += 1
            
    if deleted_count > 0:
        logger.info(f"[cleanup] Deleted {deleted_count} expired sessions.")

@reminder_task.before_loop
async def before_reminder() -> None:
    await _bot.wait_until_ready()

@cleanup_task.before_loop
async def before_cleanup() -> None:
    await _bot.wait_until_ready()
