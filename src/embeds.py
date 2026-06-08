from datetime import datetime
import discord
from bungie import activity_images, commendation_defs
from constants import DUNGEONS, RAIDS, EXPERIENCED_THRESHOLD, RANDOM_RAID, RANDOM_DUNGEON

def build_lfg_embed(session: dict, closed: bool = False) -> discord.Embed:
    activity = session["activity"]
    activity_type = session["activity_type"]
    time_str = session["time"]
    description = session.get("description", "")
    if not description and activity == "Пантеон":
        description = (
            "Пантеон — це вершина рейд-активностей у Destiny 2 у форматі бос-рашу, яка вимагає від бойових груп "
            "здолати низку культових босів рейдів послідовно. Вперше представлена в оновленні «До Світла», "
            "ця активність пропонує висхідну складність, унікальні модифікатори (як-от «Класова війна» або «Застрільник») "
            "та цінні нагороди, включаючи адепт-зброю та рідкісну екзотичну зброю з рейдів."
        )
    members: list = session["members"]
    reserves: list = session.get("reserves", [])
    capacity: int = session["capacity"]
    leader_id = session["leader_id"]
    leader_name = session["leader_name"]
    member_data = session.get("member_data", {})
    options = session.get("options", [])
    votes = session.get("votes", {})

    is_raid = activity_type == "raid"
    is_pvp = activity_type == "pvp"
    
    if closed:
        color = discord.Color.dark_gray()
    elif is_raid:
        color = discord.Color.from_rgb(255, 185, 0)
    elif is_pvp:
        color = discord.Color.from_rgb(220, 20, 60)
    else:
        color = discord.Color.from_rgb(130, 50, 210)

    if is_raid:
        activity_label = "Рейд"
        emoji = "⚔️"
    elif is_pvp:
        activity_label = "PVP"
        emoji = "🔫"
    else:
        activity_label = "Данж"
        emoji = "🗡️"
    scheduled_at = session.get("scheduled_at")
    if scheduled_at:
        try:
            dt = datetime.fromisoformat(scheduled_at)
            ts = int(dt.timestamp())
            display_time = f"<t:{ts}:t> (<t:{ts}:R>)"
        except Exception:
            display_time = f"**{time_str}**"
    else:
        display_time = f"**{time_str}**"

    embed = discord.Embed(
        title=f"{emoji} {activity_label}: {activity}",
        color=color,
    )
    embed.add_field(name="⏰ Час початку", value=display_time, inline=True)
    embed.add_field(name="👥 Місця", value=f"**{len(members)}/{capacity}**", inline=True)
    embed.add_field(name="​", value="​", inline=True)

    if description:
        embed.add_field(name="📝 Опис / вимоги", value=description, inline=False)

    leader_bungie_name = session.get("leader_bungie_name")
    if leader_bungie_name and not closed:
        embed.add_field(
            name="🎮 Команда для входу",
            value=f"`/join {leader_bungie_name}`",
            inline=False,
        )

    if options:
        tally = {opt: 0 for opt in options}
        for v in votes.values():
            if v in tally:
                tally[v] += 1
        vote_lines = [f"• **{opt}**: {count} голос(ів)" for opt, count in tally.items()]
        embed.add_field(name="🗳️ Голосування за активність", value="\n".join(vote_lines), inline=False)

    def _format_member(mid, i):
        crown = " 👑" if mid == leader_id else ""
        stats = member_data.get(mid)
        stats_str = f" `[{stats}]`" if stats else ""
        return f"`{i + 1}.` <@{mid}>{crown}{stats_str}"

    slots_lines = []
    for i in range(capacity):
        if i < len(members):
            slots_lines.append(_format_member(members[i], i))
        else:
            slots_lines.append(f"`{i + 1}.` *Вільне місце*")
    embed.add_field(name="👤 Учасники", value="\n".join(slots_lines), inline=False)

    if reserves:
        reserve_lines = [_format_member(mid, i) for i, mid in enumerate(reserves)]
        embed.add_field(name="⏳ Запасні", value="\n".join(reserve_lines), inline=False)

    if closed:
        status = "🔒 Збір закрито"
    elif len(members) >= capacity:
        status = "🔴 Набір завершено"
    else:
        status = "✅ Набір відкрито"

    embed.set_footer(text=f"Організатор: {leader_name}  •  {status}")
    
    # Спеціальне зображення для голосування, рандомних рейдів та PVP
    if options or activity in (RANDOM_RAID, RANDOM_DUNGEON) or is_pvp:
        image_url = "https://images.seattletimes.com/wp-content/uploads/2025/08/08042025_Game-Destiny_2_Edge_of_Fate-1_103514.jpg?d=2040x1148"
    elif activity == "Пантеон":
        image_url = "https://static0.polygonimages.com/wordpress/wp-content/uploads/chorus/uploads/chorus_asset/file/25428395/Pantheon_Header.jpg"
    else:
        image_url = activity_images.get(activity)
        
    if image_url:
        embed.set_image(url=image_url)
    return embed

def build_commendation_embed(
    member: discord.Member, received: dict[str, int], given: int,
    emblem: dict | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏆 Похвали {member.display_name}",
        color=discord.Color.gold(),
    )
    if emblem and emblem.get("icon"):
        embed.set_thumbnail(url=emblem["icon"])
    else:
        embed.set_thumbnail(url=member.display_avatar.url)
    if emblem and emblem.get("background"):
        embed.set_image(url=emblem["background"])

    total = sum(received.values())
    if received:
        lines = [
            f"{comm['emoji']} **{comm['name_uk']}**: {received[comm['name_uk']]}"
            for comm in commendation_defs
            if received.get(comm["name_uk"], 0) > 0
        ]
        embed.add_field(name="Отримані похвали", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Отримані похвали", value="Похвал ще немає", inline=False)

    embed.set_footer(text=f"Всього отримано: {total}  •  Роздано: {given}")
    return embed


def build_profile_embed(bungie_name: str, completions: dict[str, int]) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎮 {bungie_name}",
        color=discord.Color.from_rgb(255, 185, 0),
    )
    def _lines(activity_list: list[str]) -> tuple[list[str], int]:
        lines, total = [], 0
        for name in activity_list:
            n = completions.get(name, 0)
            total += n
            exp = " ⭐" if n >= EXPERIENCED_THRESHOLD else ""
            lines.append(f"`{n}` {name}{exp}")
        return lines, total

    raid_lines, total_raids = _lines(RAIDS)
    dungeon_lines, total_dungeons = _lines(DUNGEONS)
    embed.add_field(
        name=f"⚔️ Рейди — всього: **{total_raids}**",
        value="\n".join(raid_lines),
        inline=False,
    )
    embed.add_field(
        name=f"🗡️ Данжі — всього: **{total_dungeons}**",
        value="\n".join(dungeon_lines),
        inline=False,
    )
    embed.set_footer(text=f"⭐ = Досвідчений ({EXPERIENCED_THRESHOLD}+ закриттів)")
    return embed
