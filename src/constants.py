import zoneinfo

TZ_KYIV = zoneinfo.ZoneInfo("Europe/Kyiv")
BUNGIE_BASE = "https://www.bungie.net"
RANDOM_RAID = "Випадковий рейд"
RANDOM_DUNGEON = "Випадковий данж"

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

RAIDS = [
    RANDOM_RAID,
    "Склеп Скла",
    "Останнє бажання",
    "Сад Порятунку",
    "Склеп Глибокого Каменю",
    "Обітниця послідовника",
    "Падіння Короля",
    "Коріння Жахів",
    "Кінець Кроти",
    "Межа Спасіння",
    "Піски безкінечності",
]

DUNGEONS = [
    RANDOM_DUNGEON,
    "Яма Єресі",
    "Пророцтво",
    "Хватка Алчності",
    "Двоїстість",
    "Шпиль Спостерігача",
    "Примари Глибин",
    "Руїни Варлорда",
    "Притулок Веспера",
    "Еквілібріум",
]

RAID_MAX = 6
DUNGEON_MAX = 3
PVP_MAX = 3
EXPERIENCED_THRESHOLD = 10

import json
import os

def load_role_sync_config() -> dict:
    config_path = os.getenv("ROLE_SYNC_CONFIG", "role_sync.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading role sync config: {e}")
    return {}

ROLE_SYNC = load_role_sync_config()
