"""
Diagnostic script: shows which Bungie manifest names match our search terms
and what pgcrImage URLs they have.
"""

import asyncio
import os
import sys

import aiohttp
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

BUNGIE_BASE = "https://www.bungie.net"

SEARCH_TERMS = [
    # Raids
    "Vault of Glass",
    "Last Wish",
    "Garden of Salvation",
    "Deep Stone Crypt",
    "Vow of the Disciple",
    "King's Fall",
    "Root of Nightmares",
    "Crota's End",
    "Salvation's Edge",
    "The Desert Perpetual",
    # Dungeons
    "Pit of Heresy",
    "Prophecy",
    "Grasp of Avarice",
    "Duality",
    "Spire of the Watcher",
    "Ghosts of the Deep",
    "Warlord's Ruin",
    "Vesper's Host",
    "Equilibrium",
]


async def main() -> None:
    api_key = os.getenv("BUNGIE_API_KEY")
    if not api_key:
        print("❌  BUNGIE_API_KEY не знайдено в .env")
        return

    print("⏳  Завантаження маніфесту Bungie...")
    async with aiohttp.ClientSession() as http:
        async with http.get(
            f"{BUNGIE_BASE}/Platform/Destiny2/Manifest/",
            headers={"X-API-Key": api_key},
        ) as resp:
            manifest = await resp.json()

        def_path = manifest["Response"]["jsonWorldComponentContentPaths"]["en"][
            "DestinyActivityDefinition"
        ]
        print(f"⏳  Завантаження DestinyActivityDefinition ({def_path})...")

        async with http.get(f"{BUNGIE_BASE}{def_path}") as resp:
            activity_defs: dict = await resp.json(content_type=None)

    print(f"✅  Завантажено {len(activity_defs)} визначень активностей\n")

    name_index: dict[str, list[tuple[str, str]]] = {}
    for hash_key, entry in activity_defs.items():
        name: str = entry.get("displayProperties", {}).get("name", "").strip()
        pgcr: str = entry.get("pgcrImage", "").strip()
        if name:
            name_index.setdefault(name, [])
            if pgcr and "missing_icon" not in pgcr:
                name_index[name].append((pgcr, hash_key))

    print("=" * 72)
    not_found: list[str] = []

    for term in SEARCH_TERMS:
        term_lower = term.lower()

        exact = name_index.get(term)
        partial = [
            (n, imgs)
            for n, imgs in name_index.items()
            if term_lower in n.lower() and n != term
        ]

        print(f"\n🔍  '{term}'")

        if exact is not None:
            if exact:
                url = f"{BUNGIE_BASE}{exact[0][0]}"
                print(f"  ✅  Точний збіг — зображення: {url}")
            else:
                print("  ⚠️   Точний збіг знайдено, але pgcrImage порожній")
        else:
            print("  ❌  Точного збігу немає")
            not_found.append(term)

        if partial:
            print(f"  ℹ️   Часткові збіги ({len(partial)}):")
            for pname, imgs in partial[:5]:
                img_note = f"{BUNGIE_BASE}{imgs[0][0]}" if imgs else "(без зображення)"
                print(f"       • '{pname}'  →  {img_note}")

    print("\n" + "=" * 72)

    _INVALID = ("missing_icon", "placeholder.jpg")
    def _norm(s: str) -> str:
        return s.replace("’", "'").replace("‘", "'")

    en_to_image: dict[str, str] = {}
    for entry in activity_defs.values():
        n: str = _norm(entry.get("displayProperties", {}).get("name", "").strip())
        p: str = entry.get("pgcrImage", "").strip()
        if n and p and not any(m in p for m in _INVALID) and n not in en_to_image:
            en_to_image[n] = f"{BUNGIE_BASE}{p}"

    uk_names = {
        "Склеп Скла": "Vault of Glass",
        "Останнє бажання": "Last Wish",
        "Сад Порятунку": "Garden of Salvation",
        "Склеп Глибокого Каменю": "Deep Stone Crypt",
        "Обітниця послідовника": "Vow of the Disciple",
        "Падіння Короля": "King’s Fall",
        "Коріння Жахів": "Root of Nightmares",
        "Кінець Кроти": "Crota’s End",
        "Межа Спасіння": "Salvation’s Edge",
        "Піски безкінечності": "The Desert Perpetual",
        "Яма Єресі": "Pit of Heresy",
        "Пророцтво": "Prophecy",
        "Хватка Алчності": "Grasp of Avarice",
        "Двоїстість": "Duality",
        "Шпиль Спостерігача": "Spire of the Watcher",
        "Примари Глибин": "Ghosts of the Deep",
        "Руїни Варлорда": "Warlord’s Ruin",
        "Притулок Веспера": "Vesper’s Host",
        "Еквілібріум": "Equilibrium",
    }

    print("\n📊  Результат нової логіки matching у bot.py:\n")
    found = 0
    for uk, en in uk_names.items():
        url = (
            en_to_image.get(en)
            or en_to_image.get(f"{en}: Standard")
            or next((v for k, v in en_to_image.items() if k.startswith(f"{en}: ")), None)
        )
        mark = "✅" if url else "❌"
        img_short = url.rsplit("/", 1)[-1] if url else "—"
        print(f"  {mark}  {uk:<30}  {img_short}")
        if url:
            found += 1
    print(f"\n  Разом: {found}/{len(uk_names)}")


if __name__ == "__main__":
    asyncio.run(main())
