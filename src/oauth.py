import os
import logging
import secrets
from aiohttp import web
from bungie import exchange_code, get_bungie_memberships, get_sync_stats
from database import get_and_delete_oauth_state, save_oauth_state, save_profile
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
        role_id = os.getenv("REGISTERED_ROLE_ID")
        role_assigned = False
        synced_role_names = []

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
                    
                    # Надаємо основну роль реєстрації
                    if role_id:
                        role = guild.get_role(int(role_id))
                        if not role:
                            logger.warning(f"OAuth: Role {role_id} not found in cache, fetching all roles...")
                            roles = await guild.fetch_roles()
                            role = discord.utils.get(roles, id=int(role_id))

                        if member and role:
                            await member.add_roles(role)
                            role_assigned = True
                            logger.info(f"OAuth: надано основну роль {role.name} користувачу {discord_id}")
                        else:
                            if not role:
                                logger.error(f"OAuth: Role {role_id} not found even after fetch")
                            if not member:
                                logger.error(f"OAuth: Member {discord_id} is None during role assignment")
                    else:
                        logger.warning("OAuth: REGISTERED_ROLE_ID is not set in .env")
                    
                    # Синхронізуємо ролі за статистикою
                    stats = await get_sync_stats(player["membership_type"], player["membership_id"])
                    if stats and member:
                        synced_role_names = await sync_member_roles(member, stats)
                        if synced_role_names:
                            logger.info(f"OAuth: синхронізовано додаткові ролі для {discord_id}: {synced_role_names}")
                else:
                    logger.error(f"OAuth: Could not find guild {guild_id}")

            except Exception as e:
                logger.error(f"OAuth: помилка при наданні ролей: {e}", exc_info=True)

        try:
            user = await _bot.fetch_user(int(discord_id))
            msgs = []
            if role_assigned:
                msgs.append("Тобі надано роль зареєстрованого користувача.")
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
