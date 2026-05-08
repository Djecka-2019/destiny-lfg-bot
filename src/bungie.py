import os
import logging
import aiohttp
from constants import ACTIVITY_EN_NAMES, BUNGIE_BASE

logger = logging.getLogger("destiny_bot")
activity_images: dict[str, str] = {}
activity_hashes: dict[str, set[int]] = {}

commendation_defs: list[dict] = [
    {"name_uk": "Обізнаний",          "emoji": "🔵", "color": (66, 133, 244),  "icon_url": None},
    {"name_uk": "Самовідданий",        "emoji": "🟠", "color": (255, 127, 0),   "icon_url": None},
    {"name_uk": "Душа компанії",       "emoji": "🌟", "color": (255, 185, 0),   "icon_url": None},
    {"name_uk": "Найкраще вдягнений",  "emoji": "🌸", "color": (220, 150, 220), "icon_url": None},
    {"name_uk": "Надійний",            "emoji": "🟢", "color": (52, 168, 83),   "icon_url": None},
]

_COMMENDATION_EN_NAMES = ["Knowledgeable", "Selfless", "Bring the Fun", "Best Dressed", "Reliable"]

async def fetch_activity_images() -> None:
    api_key = os.getenv("BUNGIE_API_KEY")
    if not api_key:
        logger.warning("BUNGIE_API_KEY не задано — прев'ю активностей вимкнено")
        return

    headers = {"X-API-Key": api_key}
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as http:
        try:
            async with http.get(
                f"{BUNGIE_BASE}/Platform/Destiny2/Manifest/", headers=headers
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"Bungie Manifest HTTP {resp.status}")
                    return
                manifest = await resp.json()
        except Exception as e:
            logger.error(f"Не вдалося отримати маніфест Bungie: {e}")
            return

        try:
            def_path = manifest["Response"]["jsonWorldComponentContentPaths"]["en"][
                "DestinyActivityDefinition"
            ]
        except KeyError:
            logger.warning("Несподівана структура маніфесту Bungie")
            return

        try:
            async with http.get(f"{BUNGIE_BASE}{def_path}") as resp:
                if resp.status != 200:
                    logger.warning(f"DestinyActivityDefinition HTTP {resp.status}")
                    return
                activity_defs: dict = await resp.json(content_type=None)
        except Exception as e:
            logger.error(f"Не вдалося завантажити DestinyActivityDefinition: {e}")
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

    logger.info(f"Прев'ю активностей: {found}/{len(ACTIVITY_EN_NAMES)} знайдено")
    en_to_uk = {en: uk for uk, en in ACTIVITY_EN_NAMES.items()}
    for hash_str, entry in activity_defs.items():
        en_name: str = entry.get("displayProperties", {}).get("name", "").strip()
        base_name = en_name.split(": ")[0] if ": " in en_name else en_name
        uk_name = en_to_uk.get(base_name)
        if uk_name:
            activity_hashes.setdefault(uk_name, set())
            try:
                activity_hashes[uk_name].add(int(hash_str))
            except ValueError:
                pass

    total_hashes = sum(len(v) for v in activity_hashes.values())
    logger.info(f"Хеші активностей: {total_hashes} варіантів для {len(activity_hashes)} активностей")

async def search_bungie_player(display_name: str, display_name_code: int) -> dict | None:
    api_key = os.getenv("BUNGIE_API_KEY")
    if not api_key:
        return None
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
        try:
            async with http.post(
                f"{BUNGIE_BASE}/Platform/Destiny2/SearchDestinyPlayerByBungieName/-1/",
                headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                json={"displayName": display_name, "displayNameCode": display_name_code},
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except Exception:
            return None
    players = data.get("Response", [])
    if not players:
        return None
    p = players[0]
    code = p.get("bungieGlobalDisplayNameCode", display_name_code)
    name = p.get("bungieGlobalDisplayName", display_name)
    return {
        "membership_type": p["membershipType"],
        "membership_id":   p["membershipId"],
        "bungie_name":     f"{name}#{code:04d}",
    }

async def search_bungie_player_by_name(name: str) -> dict | None:
    api_key = os.getenv("BUNGIE_API_KEY")
    if not api_key:
        return None
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
        try:
            async with http.get(
                f"{BUNGIE_BASE}/Platform/Destiny2/SearchDestinyPlayer/-1/{name}/",
                headers={"X-API-Key": api_key}
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except Exception:
            return None
    players = data.get("Response", [])
    if not players:
        return None
    p = players[0]
    return {
        "membership_type": p["membershipType"],
        "membership_id":   p["membershipId"],
        "bungie_name":     p.get("bungieGlobalDisplayName", name),
    }

async def get_character_emblem(membership_type: int, membership_id: str) -> dict[str, str] | None:
    api_key = os.getenv("BUNGIE_API_KEY")
    if not api_key:
        return None
    headers = {"X-API-Key": api_key}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
        try:
            async with http.get(
                f"{BUNGIE_BASE}/Platform/Destiny2/{membership_type}/Profile/{membership_id}/?components=200",
                headers=headers,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except Exception:
            return None
    characters = data.get("Response", {}).get("characters", {}).get("data", {})
    if not characters:
        return None
    latest = max(characters.values(), key=lambda c: c.get("dateLastPlayed", ""))
    icon = latest.get("emblemPath", "")
    background = latest.get("emblemBackgroundPath", "")
    if not icon and not background:
        return None
    return {
        "icon":       f"{BUNGIE_BASE}{icon}"       if icon       else None,
        "background": f"{BUNGIE_BASE}{background}" if background else None,
    }


async def get_activity_stats(membership_type: int, membership_id: str, activity_name: str) -> tuple[int, int]:
    api_key = os.getenv("BUNGIE_API_KEY")
    if not api_key or not activity_hashes or activity_name not in activity_hashes:
        return 0, 0

    hashes = activity_hashes[activity_name]
    headers = {"X-API-Key": api_key}
    timeout = aiohttp.ClientTimeout(total=15)

    async with aiohttp.ClientSession(timeout=timeout) as http:
        try:
            async with http.get(
                f"{BUNGIE_BASE}/Platform/Destiny2/{membership_type}/Profile/{membership_id}/?components=100",
                headers=headers,
            ) as resp:
                if resp.status != 200: return 0, 0
                profile_data = await resp.json()
        except Exception: return 0, 0

        char_ids: list[str] = list(profile_data.get("Response", {}).get("profile", {}).get("data", {}).get("characterIds", []))
        if not char_ids: return 0, 0

        total_completions = 0
        total_sherpas = 0
        for char_id in char_ids:
            try:
                async with http.get(
                    f"{BUNGIE_BASE}/Platform/Destiny2/{membership_type}/Account/{membership_id}/Character/{char_id}/Stats/AggregateActivityStats/",
                    headers=headers,
                ) as resp:
                    if resp.status == 200:
                        stats = await resp.json()
                        for act in stats.get("Response", {}).get("activities", []):
                            if act.get("activityHash", 0) in hashes:
                                val = act.get("values", {}).get("activityCompletions", {}).get("basic", {}).get("value", 0)
                                total_completions += int(val)
            except Exception: continue
    return total_completions, total_sherpas

async def fetch_commendation_defs() -> None:
    api_key = os.getenv("BUNGIE_API_KEY")
    if not api_key:
        logger.warning("BUNGIE_API_KEY не задано — іконки похвал вимкнено")
        return

    headers = {"X-API-Key": api_key}
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as http:
        try:
            async with http.get(f"{BUNGIE_BASE}/Platform/Destiny2/Manifest/", headers=headers) as resp:
                if resp.status != 200:
                    logger.warning(f"Bungie Manifest HTTP {resp.status} (для похвал)")
                    return
                manifest = await resp.json()
        except Exception as e:
            logger.error(f"Не вдалося отримати маніфест Bungie для похвал: {e}")
            return

        try:
            def_path = manifest["Response"]["jsonWorldComponentContentPaths"]["en"]["DestinyCommendationDefinition"]
        except KeyError:
            logger.warning("DestinyCommendationDefinition не знайдено в маніфесті — іконки недоступні")
            return

        try:
            async with http.get(f"{BUNGIE_BASE}{def_path}") as resp:
                if resp.status != 200:
                    logger.warning(f"DestinyCommendationDefinition HTTP {resp.status}")
                    return
                raw = await resp.json(content_type=None)
        except Exception as e:
            logger.error(f"Не вдалося завантажити DestinyCommendationDefinition: {e}")
            return

    en_to_icon: dict[str, str] = {}
    for entry in raw.values():
        name = entry.get("displayProperties", {}).get("name", "").strip()
        icon = entry.get("displayProperties", {}).get("icon", "").strip()
        if name and icon:
            en_to_icon[name] = f"{BUNGIE_BASE}{icon}"

    found = 0
    for i, en_name in enumerate(_COMMENDATION_EN_NAMES):
        icon_url = en_to_icon.get(en_name)
        if icon_url:
            commendation_defs[i]["icon_url"] = icon_url
            found += 1

    logger.info(f"Іконки похвал: {found}/{len(_COMMENDATION_EN_NAMES)} знайдено")


async def exchange_code(code: str) -> dict | None:
    client_id = os.getenv("BUNGIE_CLIENT_ID")
    client_secret = os.getenv("BUNGIE_CLIENT_SECRET")
    if not client_id or not client_secret:
        logger.error("BUNGIE_CLIENT_ID або BUNGIE_CLIENT_SECRET не задано")
        return None
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
        try:
            async with http.post(
                f"{BUNGIE_BASE}/platform/app/oauth/token/",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as resp:
                if resp.status != 200:
                    logger.error(f"OAuth token exchange HTTP {resp.status}: {await resp.text()}")
                    return None
                return await resp.json()
        except Exception as e:
            logger.error(f"Помилка при обміні OAuth коду: {e}")
            return None


async def get_bungie_memberships(access_token: str) -> dict | None:
    api_key = os.getenv("BUNGIE_API_KEY")
    if not api_key:
        return None
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
        try:
            async with http.get(
                f"{BUNGIE_BASE}/Platform/User/GetMembershipsForCurrentUser/",
                headers={
                    "X-API-Key": api_key,
                    "Authorization": f"Bearer {access_token}",
                },
            ) as resp:
                if resp.status != 200:
                    logger.error(f"GetMembershipsForCurrentUser HTTP {resp.status}")
                    return None
                data = await resp.json()
        except Exception as e:
            logger.error(f"Помилка при отриманні memberships: {e}")
            return None

    response = data.get("Response", {})
    memberships = response.get("destinyMemberships", [])
    if not memberships:
        return None

    primary_id = response.get("primaryMembershipId")
    membership = next((m for m in memberships if m["membershipId"] == primary_id), memberships[0])

    bungie_net_user = response.get("bungieNetUser", {})
    name = bungie_net_user.get("cachedBungieGlobalDisplayName", "")
    code = bungie_net_user.get("cachedBungieGlobalDisplayNameCode", 0)
    bungie_name = f"{name}#{code:04d}" if name else membership.get("displayName", "Unknown")

    return {
        "membership_type": membership["membershipType"],
        "membership_id":   membership["membershipId"],
        "bungie_name":     bungie_name,
    }


async def get_activity_completions(membership_type: int, membership_id: str) -> dict[str, int]:
    api_key = os.getenv("BUNGIE_API_KEY")
    if not api_key or not activity_hashes:
        return {}

    headers = {"X-API-Key": api_key}
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        try:
            async with http.get(
                f"{BUNGIE_BASE}/Platform/Destiny2/{membership_type}/Profile/{membership_id}/?components=100",
                headers=headers,
            ) as resp:
                if resp.status != 200: return {}
                profile_data = await resp.json()
        except Exception: return {}

        char_ids: list[str] = list(profile_data.get("Response", {}).get("profile", {}).get("data", {}).get("characterIds", []))
        if not char_ids: return {}

        hash_completions: dict[int, int] = {}
        for char_id in char_ids:
            try:
                async with http.get(
                    f"{BUNGIE_BASE}/Platform/Destiny2/{membership_type}/Account/{membership_id}/Character/{char_id}/Stats/AggregateActivityStats/",
                    headers=headers,
                ) as resp:
                    if resp.status == 200:
                        stats = await resp.json()
                        for act in stats.get("Response", {}).get("activities", []):
                            h: int = act.get("activityHash", 0)
                            n: int = int(act.get("values", {}).get("activityCompletions", {}).get("basic", {}).get("value", 0))
                            if h and n:
                                hash_completions[h] = hash_completions.get(h, 0) + n
            except Exception: continue

    return {
        uk: total
        for uk, hashes in activity_hashes.items()
        if (total := sum(hash_completions.get(h, 0) for h in hashes)) > 0
    }

async def get_sync_stats(membership_type: int, membership_id: str) -> dict[str, int]:
    """Отримує статистику для синхронізації ролей (метрики та прогрес)."""
    api_key = os.getenv("BUNGIE_API_KEY")
    if not api_key:
        return {}

    headers = {"X-API-Key": api_key}
    # 202: CharacterProgressions, 1100: Metrics
    url = f"{BUNGIE_BASE}/Platform/Destiny2/{membership_type}/Profile/{membership_id}/?components=202,1100"
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
        try:
            async with http.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()
        except Exception as e:
            logger.error(f"Помилка при отриманні статистики для синхронізації: {e}")
            return {}

    response = data.get("Response", {})
    metrics = response.get("metrics", {}).get("data", {}).get("metrics", {})
    
    # Метрики (lifetime)
    # 3423710777: Total Raid Completions
    # 2643509121: Grandmaster Nightfall Completions
    # 1765245062: Trials Flawless Tickets
    # 1356024107: Gambit Infamy Resets (lifetime)
    
    def get_metric(m_hash: int) -> int:
        m = metrics.get(str(m_hash), {})
        return m.get("objectiveProgress", {}).get("progress", 0)

    stats = {
        "raids": get_metric(3423710777),
        "gms": get_metric(2643509121),
        "trials": get_metric(1765245062),
        "gambit_resets": get_metric(1356024107),
    }

    # ПВП Ранг (Competitive Division)
    # Шукаємо прогрес на персонажах
    char_progressions = response.get("characterProgressions", {}).get("data", {})
    max_pvp_rank = 0
    for char_id in char_progressions:
        progressions = char_progressions[char_id].get("progressions", {})
        # 3696598664: Competitive Division (Glory/Rank)
        comp_prog = progressions.get("3696598664", {})
        rank = comp_prog.get("currentProgress", 0)
        if rank > max_pvp_rank:
            max_pvp_rank = rank
    
    stats["pvp_rank"] = max_pvp_rank
    return stats

