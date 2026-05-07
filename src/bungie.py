import os
import logging
import aiohttp
from constants import ACTIVITY_EN_NAMES, BUNGIE_BASE

logger = logging.getLogger("destiny_bot")
activity_images: dict[str, str] = {}
activity_hashes: dict[str, set[int]] = {}

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

