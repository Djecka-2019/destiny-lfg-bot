import re
from datetime import datetime, timedelta

import discord

from bungie import get_activity_completions
from constants import DUNGEON_MAX, NEWBIE_THRESHOLD, RAID_MAX, SHERPA_THRESHOLD
from database import delete_session, get_discord_profile, lfg_sessions, upsert_session
from embeds import build_lfg_embed, build_profile_embed


class LFGView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="➕ Приєднатись / Вийти",
        style=discord.ButtonStyle.green,
        custom_id="lfg:join_toggle",
        emoji="🎮",
    )
    async def join_toggle(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()

        msg_id = str(interaction.message.id)
        session = lfg_sessions.get(msg_id)
        if not session:
            await interaction.followup.send("Ця активність більше не активна.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        members: list = session["members"]
        reserves: list = session.setdefault("reserves", [])

        promoted_id: str | None = None

        if user_id in members:
            members.remove(user_id)
            joined = False
            if reserves:
                promoted_id = reserves.pop(0)
                members.append(promoted_id)
        elif user_id in reserves:
            reserves.remove(user_id)
            joined = False
        else:
            if len(members) >= session["capacity"]:
                reserves.append(user_id)
                joined = None
            else:
                members.append(user_id)
                joined = True

        await upsert_session(msg_id, session)
        await interaction.message.edit(embed=build_lfg_embed(session), view=self)

        thread_id = session.get("thread_id")
        if thread_id:
            thread = interaction.guild.get_thread(int(thread_id))
            if thread:
                if joined is True:
                    await thread.send(
                        f"🟢 {interaction.user.mention} **приєднався(-лась)** до активності!"
                    )
                elif joined is None:
                    await thread.send(
                        f"⏳ {interaction.user.mention} **доданий(-на) до запасних** (місць немає)."
                    )
                else:
                    await thread.send(
                        f"🔴 {interaction.user.mention} **покинув(-ла)** активність."
                    )
                if promoted_id:
                    promoted = interaction.guild.get_member(int(promoted_id))
                    name = promoted.mention if promoted else f"<@{promoted_id}>"
                    await thread.send(
                        f"🟢 {name} **переміщений(-на) із запасних** до основного складу!"
                    )

        if joined is None:
            await interaction.followup.send(
                "⏳ Місця заповнені — тебе додано до запасних.", ephemeral=True
            )

    @discord.ui.button(
        label="Статистика команди",
        style=discord.ButtonStyle.blurple,
        custom_id="lfg:stats",
        emoji="📊",
    )
    async def team_stats(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        msg_id = str(interaction.message.id)
        session = lfg_sessions.get(msg_id)
        if not session:
            await interaction.followup.send("Активність не знайдена.", ephemeral=True)
            return

        activity = session["activity"]
        lines: list[str] = []

        for member_id in session["members"]:
            profile = await get_discord_profile(member_id)
            if not profile:
                lines.append(f"<@{member_id}>: акаунт не прив'язано")
                continue
            membership_type, membership_id, bungie_name = profile
            completions = await get_activity_completions(membership_type, membership_id)
            count = completions.get(activity, 0)
            total = sum(completions.values())
            if count >= SHERPA_THRESHOLD:
                tag = "  🎓 Шерпа"
            elif count < NEWBIE_THRESHOLD:
                tag = "  🆕 Новачок"
            else:
                tag = ""
            lines.append(
                f"<@{member_id}> `{bungie_name}` — **{count}** закриттів{tag}"
                f"  *(всього: {total})*"
            )

        is_raid = session["activity_type"] == "raid"
        color = discord.Color.from_rgb(255, 185, 0) if is_raid else discord.Color.from_rgb(130, 50, 210)
        embed = discord.Embed(
            title=f"📊 Статистика команди — {activity}",
            description="\n".join(lines) or "Немає даних",
            color=color,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Закрити збір",
        style=discord.ButtonStyle.red,
        custom_id="lfg:close",
        emoji="🔒",
    )
    async def close_lfg(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()

        msg_id = str(interaction.message.id)
        session = lfg_sessions.get(msg_id)
        if not session:
            await interaction.followup.send("Ця активність вже не активна.", ephemeral=True)
            return

        if str(interaction.user.id) != session["leader_id"]:
            await interaction.followup.send(
                "❌ Лише організатор може закрити збір.", ephemeral=True
            )
            return

        for item in self.children:
            item.disabled = True

        await interaction.message.edit(embed=build_lfg_embed(session, closed=True), view=self)

        thread_id = session.get("thread_id")
        if thread_id:
            thread = interaction.guild.get_thread(int(thread_id))
            if thread:
                await thread.send("🔒 **Збір закрито організатором.**")
                try:
                    await thread.edit(archived=True, locked=True)
                except discord.HTTPException:
                    pass

        del lfg_sessions[msg_id]
        await delete_session(msg_id)


class ActivitySelect(discord.ui.Select):
    def __init__(self, activities: list[str], activity_type: str) -> None:
        self._activities = activities
        self._activity_type = activity_type
        emoji = "⚔️" if activity_type == "raid" else "🗡️"
        options = [
            discord.SelectOption(label=name, value=str(i), emoji=emoji)
            for i, name in enumerate(activities)
        ]
        label = "рейд" if activity_type == "raid" else "данж"
        super().__init__(
            placeholder=f"Оберіть {label}...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        idx = int(self.values[0])
        activity_name = self._activities[idx]
        await interaction.response.send_modal(LFGModal(activity_name, self._activity_type))


class ActivitySelectView(discord.ui.View):
    def __init__(self, activities: list[str], activity_type: str) -> None:
        super().__init__(timeout=120)
        self.add_item(ActivitySelect(activities, activity_type))


class LFGModal(discord.ui.Modal, title="Налаштування збору"):
    time_input = discord.ui.TextInput(
        label="Час початку (ГГ:ХХ)",
        placeholder="Наприклад: 20:00",
        min_length=4,
        max_length=5,
        required=True,
    )
    description_input = discord.ui.TextInput(
        label="Опис / вимоги (необов'язково)",
        style=discord.TextStyle.paragraph,
        placeholder="Наприклад: потрібен досвід, мікрофон обов'язковий...",
        required=False,
        max_length=500,
    )

    def __init__(self, activity_name: str, activity_type: str) -> None:
        super().__init__()
        self._activity_name = activity_name
        self._activity_type = activity_type

    async def on_submit(self, interaction: discord.Interaction) -> None:
        time_str = self.time_input.value.strip()

        if not re.match(r"^\d{1,2}:\d{2}$", time_str):
            await interaction.response.send_message(
                "❌ Невірний формат часу! Введіть час у форматі ГГ:ХХ (наприклад: 20:00)",
                ephemeral=True,
            )
            return

        h, m = map(int, time_str.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            await interaction.response.send_message(
                "❌ Невірний час! Години: 00–23, хвилини: 00–59",
                ephemeral=True,
            )
            return

        time_str = f"{h:02d}:{m:02d}"
        capacity = RAID_MAX if self._activity_type == "raid" else DUNGEON_MAX
        leader_id = str(interaction.user.id)
        description = self.description_input.value.strip()

        now = datetime.now().astimezone()
        scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if scheduled <= now:
            scheduled += timedelta(days=1)

        ts = int(scheduled.timestamp())
        display_time = f"<t:{ts}:t>"

        session: dict = {
            "activity":      self._activity_name,
            "activity_type": self._activity_type,
            "time":          time_str,
            "description":   description,
            "leader_id":     leader_id,
            "leader_name":   interaction.user.display_name,
            "members":       [leader_id],
            "reserves":      [],
            "capacity":      capacity,
            "thread_id":     None,
            "guild_id":      str(interaction.guild_id),
            "channel_id":    str(interaction.channel_id),
            "scheduled_at":  scheduled.isoformat(),
            "reminder_sent": False,
        }

        view = LFGView()
        await interaction.response.send_message(embed=build_lfg_embed(session), view=view)
        message = await interaction.original_response()

        activity_label = "Рейд" if self._activity_type == "raid" else "Данж"
        try:
            thread = await message.create_thread(
                name=f"[{activity_label}] {self._activity_name} о {time_str}",
                auto_archive_duration=1440,
            )
            await thread.send(
                f"🎮 **Збір відкрито!** {interaction.user.mention} організує "
                f"**{self._activity_name}** о {display_time}.\n"
                f"Натисніть **➕ Приєднатись / Вийти** під повідомленням, щоб долучитися. "
                f"Тут можна обговорювати активність."
            )
            session["thread_id"] = str(thread.id)
        except discord.HTTPException as e:
            print(f"Не вдалося створити гілку: {e}")

        msg_id = str(message.id)
        lfg_sessions[msg_id] = session
        await upsert_session(msg_id, session)
