import logging
import os
from typing import Any

import discord

from bungie import get_member_clan_ids
from database import get_all_profiles

logger = logging.getLogger("destiny_bot")

DEFAULT_ALLOWED_CLAN_IDS = ("5150843", "4867387")


def get_allowed_clan_ids() -> set[str]:
    raw = os.getenv("ALLOWED_CLAN_IDS")
    if not raw:
        return set(DEFAULT_ALLOWED_CLAN_IDS)
    clan_ids = {item.strip() for item in raw.split(",") if item.strip()}
    return clan_ids or set(DEFAULT_ALLOWED_CLAN_IDS)


async def _get_registered_role(guild: discord.Guild) -> discord.Role | None:
    role_id = os.getenv("REGISTERED_ROLE_ID")
    if not role_id:
        logger.warning("Registered Role Sync: REGISTERED_ROLE_ID is not set")
        return None

    try:
        role_id_int = int(role_id)
    except ValueError:
        logger.error(f"Registered Role Sync: invalid REGISTERED_ROLE_ID={role_id}")
        return None

    role = guild.get_role(role_id_int)
    if role:
        return role

    try:
        roles = await guild.fetch_roles()
    except Exception as e:
        logger.error(f"Registered Role Sync: failed to fetch roles: {e}")
        return None
    return discord.utils.get(roles, id=role_id_int)


async def sync_registered_role(
    member: discord.Member,
    membership_type: int,
    membership_id: str,
) -> dict[str, Any]:
    """
    Make REGISTERED_ROLE_ID match: user is linked in our DB and belongs to an allowed clan.

    If Bungie cannot be checked, leave the member unchanged to avoid accidental role churn.
    """
    role = await _get_registered_role(member.guild)
    if not role:
        return {
            "action": "skipped",
            "reason": "registered role missing",
            "role_name": None,
            "in_allowed_clan": None,
            "clan_ids": [],
        }

    clan_ids = await get_member_clan_ids(membership_type, membership_id)
    if clan_ids is None:
        return {
            "action": "skipped",
            "reason": "clan lookup failed",
            "role_name": role.name,
            "in_allowed_clan": None,
            "clan_ids": [],
        }

    allowed_clan_ids = get_allowed_clan_ids()
    in_allowed_clan = bool(clan_ids & allowed_clan_ids)
    has_role = any(current_role.id == role.id for current_role in member.roles)

    if in_allowed_clan and not has_role:
        await member.add_roles(role, reason="Registered Bungie account is in an allowed clan")
        return {
            "action": "added",
            "reason": None,
            "role_name": role.name,
            "in_allowed_clan": True,
            "clan_ids": sorted(clan_ids),
        }

    if not in_allowed_clan and has_role:
        await member.remove_roles(role, reason="Registered Bungie account is not in an allowed clan")
        return {
            "action": "removed",
            "reason": None,
            "role_name": role.name,
            "in_allowed_clan": False,
            "clan_ids": sorted(clan_ids),
        }

    return {
        "action": "kept",
        "reason": None,
        "role_name": role.name,
        "in_allowed_clan": in_allowed_clan,
        "clan_ids": sorted(clan_ids),
    }


async def sync_registered_roles_for_all(bot: discord.Client) -> dict[str, int]:
    guild_id = os.getenv("GUILD_ID")
    summary = {
        "checked": 0,
        "added": 0,
        "removed": 0,
        "kept": 0,
        "skipped": 0,
        "not_in_guild": 0,
        "errors": 0,
    }

    if not guild_id:
        logger.warning("Registered Role Sync: GUILD_ID is not set")
        return summary

    try:
        guild = bot.get_guild(int(guild_id))
        if not guild:
            guild = await bot.fetch_guild(int(guild_id))
    except Exception as e:
        logger.error(f"Registered Role Sync: failed to fetch guild: {e}")
        summary["errors"] += 1
        return summary

    profiles = await get_all_profiles()
    for profile in profiles:
        discord_id = profile["discord_id"]
        try:
            member = guild.get_member(int(discord_id))
            if not member:
                member = await guild.fetch_member(int(discord_id))

            summary["checked"] += 1
            result = await sync_registered_role(
                member,
                profile["membership_type"],
                profile["membership_id"],
            )
            action = result["action"]
            if action in ("added", "removed", "kept", "skipped"):
                summary[action] += 1
        except discord.NotFound:
            summary["not_in_guild"] += 1
        except Exception as e:
            summary["errors"] += 1
            logger.error(f"Registered Role Sync error for {discord_id}: {e}", exc_info=True)

    logger.info(f"Registered Role Sync summary: {summary}")
    return summary
