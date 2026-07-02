import os
import logging
import secrets
import discord
from aiohttp import web
from bungie import exchange_code, get_bungie_memberships, get_sync_stats
from database import get_and_delete_oauth_state, save_oauth_state, save_profile
from registration_sync import sync_registered_role
from role_sync import sync_member_roles

logger = logging.getLogger("destiny_bot")

_bot = None


def build_auth_url(state: str) -> str:
    client_id = os.getenv("BUNGIE_CLIENT_ID")
    return (
        f"https://www.bungie.net/en/OAuth/Authorize"
        f"?client_id={client_id}&response_type=code&state={state}"
    )


async def generate_auth_link(discord_id: str) -> str:
    state = secrets.token_urlsafe(32)
    await save_oauth_state(state, discord_id)
    return build_auth_url(state)


async def _callback(request: web.Request) -> web.Response:
    code = request.query.get("code")
    state = request.query.get("state")

    if not code or not state:
        return web.Response(
            text=_html("❌ Помилка", "Відсутній code або state у запиті."),
            content_type="text/html",
            status=400,
        )

    discord_id = await get_and_delete_oauth_state(state)
    if not discord_id:
        return web.Response(
            text=_html("❌ Помилка", "Посилання застаріло або недійсне.<br>Спробуйте <b>/add-account</b> ще раз."),
            content_type="text/html",
            status=400,
        )

    tokens = await exchange_code(code)
    if not tokens:
        return web.Response(
            text=_html("❌ Помилка", "Не вдалося обмінути код авторизації.<br>Спробуйте <b>/add-account</b> ще раз."),
            content_type="text/html",
            status=500,
        )

    access_token = tokens.get("access_token")
    player = await get_bungie_memberships(access_token)
    if not player:
        return web.Response(
            text=_html("❌ Помилка", "Не вдалося отримати дані акаунту Bungie."),
            content_type="text/html",
            status=500,
        )

    await save_profile(discord_id, player["membership_type"], player["membership_id"], player["bungie_name"])
    logger.info(f"OAuth: прив'язано {player['bungie_name']} → Discord {discord_id}")

    if _bot:
        guild_id = os.getenv("GUILD_ID")
        registered_role_result = None
        synced_role_names = []
        member = None

        if guild_id:
            try:
                guild = _bot.get_guild(int(guild_id))
                if not guild:
                    logger.warning(f"OAuth: Guild {guild_id} not found in cache, fetching...")
                    guild = await _bot.fetch_guild(int(guild_id))

                if guild:
                    member = await guild.fetch_member(int(discord_id))
                    if not member:
                        logger.error(f"OAuth: Member {discord_id} not found in guild {guild_id}")
                    
                    if member:
                        registered_role_result = await sync_registered_role(
                            member,
                            player["membership_type"],
                            player["membership_id"],
                        )
                    
                    # Синхронізуємо ролі за статистикою
                    stats = await get_sync_stats(player["membership_type"], player["membership_id"])
                    if stats and member:
                        synced_role_names = await sync_member_roles(member, stats)
                        if synced_role_names:
                            logger.info(f"OAuth: синхронізовано додаткові ролі для {discord_id}: {synced_role_names}")
                    await _send_registration_log(
                        guild,
                        member,
                        discord_id,
                        player,
                        registered_role_result,
                        synced_role_names,
                    )
                else:
                    logger.error(f"OAuth: Could not find guild {guild_id}")

            except Exception as e:
                logger.error(f"OAuth: помилка при наданні ролей: {e}", exc_info=True)

        try:
            user = await _bot.fetch_user(int(discord_id))
            msgs = []
            if registered_role_result:
                action = registered_role_result.get("action")
                role_name = registered_role_result.get("role_name")
                in_allowed_clan = registered_role_result.get("in_allowed_clan")
                if action == "added" and role_name:
                    msgs.append(f"Тобі надано роль **{role_name}**, бо ти є в дозволеному клані.")
                elif in_allowed_clan is False:
                    msgs.append("Роль зареєстрованого користувача видається тільки учасникам дозволених кланів.")
            if synced_role_names:
                role_list = ", ".join(synced_role_names)
                msgs.append(f"Також на основі твоєї статистики Bungie тобі надано ролі: **{role_list}**.")
            
            final_msg = " ".join(msgs)
            await user.send(f"✅ Акаунт **{player['bungie_name']}** успішно прив'язано до вашого Discord! {final_msg}")
        except Exception as e:
            logger.warning(f"Не вдалося надіслати DM користувачу {discord_id}: {e}")

    return web.Response(
        text=_html(
            "✅ Успішно!",
            f"Акаунт <b>{player['bungie_name']}</b> прив'язано до вашого Discord.<br>Можете закрити цю сторінку.",
        ),
        content_type="text/html",
    )


async def _send_registration_log(
    guild: discord.Guild,
    member: discord.Member | None,
    discord_id: str,
    player: dict,
    registered_role_result: dict | None,
    synced_role_names: list[str],
) -> None:
    channel_id = os.getenv("REGISTRATION_LOG_CHANNEL_ID")
    if not channel_id:
        return

    try:
        channel = guild.get_channel(int(channel_id))
        if not channel and _bot:
            channel = await _bot.fetch_channel(int(channel_id))
    except Exception as e:
        logger.warning(f"Registration log: failed to resolve channel {channel_id}: {e}")
        return

    if not channel:
        logger.warning(f"Registration log: channel {channel_id} not found")
        return

    roles_given: list[str] = []
    roles_removed: list[str] = []
    clan_status = "Not checked"
    registered_role_status = "Not checked"

    if registered_role_result:
        action = registered_role_result.get("action")
        role_name = registered_role_result.get("role_name")
        in_allowed_clan = registered_role_result.get("in_allowed_clan")
        reason = registered_role_result.get("reason")
        clan_ids = registered_role_result.get("clan_ids", [])

        if in_allowed_clan is True:
            clan_status = "In an allowed clan"
        elif in_allowed_clan is False:
            clan_status = "Not in an allowed clan"
        elif reason:
            clan_status = f"Skipped: {reason}"

        if clan_ids:
            clan_status = f"{clan_status} ({', '.join(clan_ids)})"

        if action == "added" and role_name:
            roles_given.append(role_name)
            registered_role_status = f"Added {role_name}"
        elif action == "removed" and role_name:
            roles_removed.append(role_name)
            registered_role_status = f"Removed {role_name}"
        elif action == "kept" and role_name:
            registered_role_status = f"Kept {role_name}"
        elif reason:
            registered_role_status = f"Skipped: {reason}"

    roles_given.extend(synced_role_names)

    embed = discord.Embed(
        title="New Bungie Registration",
        color=discord.Color.green(),
    )
    discord_value = f"<@{discord_id}> (`{discord_id}`)"
    if member:
        discord_value = f"{member.mention} (`{member.id}`)"
    embed.add_field(name="Discord", value=discord_value, inline=False)
    embed.add_field(name="Bungie", value=player["bungie_name"], inline=False)
    embed.add_field(name="Clan Status", value=clan_status, inline=False)
    embed.add_field(name="Registered Role", value=registered_role_status, inline=False)
    embed.add_field(name="Roles Given", value=", ".join(roles_given) if roles_given else "None", inline=False)
    if roles_removed:
        embed.add_field(name="Roles Removed", value=", ".join(roles_removed), inline=False)

    try:
        await channel.send(embed=embed)
    except Exception as e:
        logger.warning(f"Registration log: failed to send embed: {e}")


def _html(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="uk">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      font-family: sans-serif;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
      background: #1a1a2e;
    }}
    .card {{
      background: #16213e;
      color: #fff;
      padding: 2rem 3rem;
      border-radius: 12px;
      text-align: center;
      max-width: 420px;
      box-shadow: 0 4px 24px rgba(0,0,0,0.4);
    }}
    h2 {{ margin-top: 0; font-size: 1.5rem; }}
    p {{ color: #ccc; line-height: 1.6; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>{title}</h2>
    <p>{body}</p>
  </div>
</body>
</html>"""


async def start_oauth_server(bot) -> None:
    global _bot
    _bot = bot
    port = int(os.getenv("OAUTH_PORT", "8080"))
    app = web.Application()
    app.router.add_get("/callback", _callback)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"OAuth callback сервер запущено на порту {port}")
