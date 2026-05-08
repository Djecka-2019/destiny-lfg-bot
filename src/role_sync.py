import logging
import discord
from constants import ROLE_SYNC

logger = logging.getLogger("destiny_bot")

async def sync_member_roles(member: discord.Member, stats: dict[str, int]) -> list[str]:
    """
    Синхронізує ролі учасника на основі його статистики Bungie.
    Повертає список назв наданих ролей.
    """
    if not stats:
        return []

    added_roles = []
    guild = member.guild
    
    # Збираємо всі ролі, які бот може контролювати (ті, що в ROLE_SYNC)
    controlled_role_ids = set()
    for category in ROLE_SYNC.values():
        for subcat in category.values():
            for entry in subcat:
                controlled_role_ids.add(int(entry["role_id"]))

    current_role_ids = {role.id for role in member.roles}
    to_add = set()
    to_remove = set()

    # 1. Gambit Resets
    gambit_resets = stats.get("gambit_resets", 0)
    best_gambit_role = None
    gambit_cfg = ROLE_SYNC.get("gambit", {}).get("resets", [])
    for entry in gambit_cfg:
        threshold = entry["threshold"]
        rid = entry["role_id"]
        if gambit_resets >= threshold:
            best_gambit_role = int(rid)
            break
    
    for entry in gambit_cfg:
        rid_int = int(entry["role_id"])
        if rid_int == best_gambit_role:
            if rid_int not in current_role_ids:
                to_add.add(rid_int)
        elif rid_int in current_role_ids:
            to_remove.add(rid_int)

    # 2. Strikes (GMs)
    gms = stats.get("gms", 0)
    best_gm_role = None
    strikes_cfg = ROLE_SYNC.get("strikes", {}).get("gms", [])
    for entry in strikes_cfg:
        threshold = entry["threshold"]
        rid = entry["role_id"]
        if gms >= threshold:
            best_gm_role = int(rid)
            break
    
    for entry in strikes_cfg:
        rid_int = int(entry["role_id"])
        if rid_int == best_gm_role:
            if rid_int not in current_role_ids:
                to_add.add(rid_int)
        elif rid_int in current_role_ids:
            to_remove.add(rid_int)

    # 3. Raids
    raids = stats.get("raids", 0)
    best_raid_role = None
    raids_cfg = ROLE_SYNC.get("raids", {}).get("clears", [])
    for entry in raids_cfg:
        threshold = entry["threshold"]
        rid = entry["role_id"]
        if raids >= threshold:
            best_raid_role = int(rid)
            break
    
    for entry in raids_cfg:
        rid_int = int(entry["role_id"])
        if rid_int == best_raid_role:
            if rid_int not in current_role_ids:
                to_add.add(rid_int)
        elif rid_int in current_role_ids:
            to_remove.add(rid_int)

    # 4. Trials (Flawless)
    trials = stats.get("trials", 0)
    best_trials_role = None
    trials_cfg = ROLE_SYNC.get("trials", {}).get("flawless", [])
    for entry in trials_cfg:
        threshold = entry["threshold"]
        rid = entry["role_id"]
        if trials >= threshold:
            best_trials_role = int(rid)
            break
    
    for entry in trials_cfg:
        rid_int = int(entry["role_id"])
        if rid_int == best_trials_role:
            if rid_int not in current_role_ids:
                to_add.add(rid_int)
        elif rid_int in current_role_ids:
            to_remove.add(rid_int)

    # 5. PvP Rank (Comp)
    pvp_rank = stats.get("pvp_rank", 0)
    best_pvp_role = None
    pvp_cfg = ROLE_SYNC.get("pvp_comp", {}).get("ranks", [])
    for entry in pvp_cfg:
        threshold = entry["threshold"]
        rid = entry["role_id"]
        if pvp_rank >= threshold:
            best_pvp_role = int(rid)
            break
    
    for entry in pvp_cfg:
        rid_int = int(entry["role_id"])
        if rid_int == best_pvp_role:
            if rid_int not in current_role_ids:
                to_add.add(rid_int)
        elif rid_int in current_role_ids:
            to_remove.add(rid_int)

    # Застосовуємо зміни
    try:
        roles_to_add = [guild.get_role(rid) for rid in to_add if guild.get_role(rid)]
        roles_to_remove = [guild.get_role(rid) for rid in to_remove if guild.get_role(rid)]
        
        if roles_to_add:
            await member.add_roles(*roles_to_add)
            added_roles.extend([r.name for r in roles_to_add])
            
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove)
            
        if roles_to_add or roles_to_remove:
            logger.info(f"Синхронізовано ролі для {member.display_name}: +{len(to_add)}, -{len(to_remove)}")
            
    except Exception as e:
        logger.error(f"Помилка при застосуванні ролей для {member.display_name}: {e}")

    return added_roles
