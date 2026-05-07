import logging
import re
from datetime import datetime, timedelta
import discord
from bungie import get_activity_completions, get_activity_stats, search_bungie_player_by_name
from constants import DUNGEON_MAX, NEWBIE_THRESHOLD, RAID_MAX, SHERPA_THRESHOLD, TZ_KYIV, RANDOM_RAID, RANDOM_DUNGEON
from database import delete_session, get_discord_profile, get_ping_roles, lfg_sessions, upsert_session
from embeds import build_lfg_embed

logger = logging.getLogger("destiny_bot")

class VoteButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Проголосувати",
            style=discord.ButtonStyle.blurple,
            custom_id="lfg:vote",
            emoji="🗳️"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        msg_id = str(interaction.message.id)
        session = lfg_sessions.get(msg_id)
        if not session or not session.get("options"):
            await interaction.response.send_message("Голосування неактивне для цього збору.", ephemeral=True)
            return
        user_id = str(interaction.user.id)
        if user_id not in session["members"] and user_id not in session.get("reserves", []):
            await interaction.response.send_message("Тільки учасники збору можуть голосувати.", ephemeral=True)
            return
        view = VoteSelectView(msg_id, session["options"])
        await interaction.response.send_message("Оберіть активність, за яку хочете проголосувати:", view=view, ephemeral=True)

class LFGView(discord.ui.View):
    def __init__(self, session: dict = None) -> None:
        super().__init__(timeout=None)
        if session and session.get("options"):
            self.add_item(VoteButton())

    async def _update_member_stats(self, interaction: discord.Interaction, session: dict, user_id: str) -> None:
        if user_id in session.get("member_data", {}):
            return
        
        profile = await get_discord_profile(user_id)
        membership_type = None
        membership_id = None

        if profile:
            membership_type, membership_id, _ = profile
        else:
            member = interaction.guild.get_member(int(user_id))
            if member:
                search_names = [member.display_name, member.name]
                for name in search_names:
                    result = await search_bungie_player_by_name(name)
                    if result:
                        membership_type = result["membership_type"]
                        membership_id = result["membership_id"]
                        break
        
        if not membership_type:
            session.setdefault("member_data", {})[user_id] = "—"
            return

        activity = session["activity"]
        if activity in (RANDOM_RAID, RANDOM_DUNGEON) or session.get("options"):
            session.setdefault("member_data", {})[user_id] = "?"
            return

        comp, sherpa = await get_activity_stats(membership_type, membership_id, activity)
        session.setdefault("member_data", {})[user_id] = f"{comp} / {sherpa}"

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
                await self._update_member_stats(interaction, session, promoted_id)
        elif user_id in reserves:
            reserves.remove(user_id)
            joined = False
        else:
            if len(members) >= session["capacity"]:
                reserves.append(user_id)
                joined = None
                await self._update_member_stats(interaction, session, user_id)
            else:
                members.append(user_id)
                joined = True
                await self._update_member_stats(interaction, session, user_id)

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
            discord.SelectOption(label=name, value=name, emoji=emoji)
            for name in activities
        ]
        label = "рейд(і)" if activity_type == "raid" else "данж(і)"
        super().__init__(
            placeholder=f"Оберіть {label} (можна декілька для голосування)...",
            min_values=1,
            max_values=5,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_activities = self.values
        ping_role_ids = await get_ping_roles(str(interaction.guild_id))
        if ping_role_ids:
            role_options: list[tuple[str, str]] = []
            for rid in ping_role_ids:
                if rid == "everyone":
                    role_options.append(("everyone", "@everyone"))
                else:
                    role = interaction.guild.get_role(int(rid))
                    if role:
                        role_options.append((str(role.id), role.name))
            if role_options:
                view = PingRoleView(selected_activities, self._activity_type, role_options)
                await interaction.response.edit_message(
                    content="📢 **Оберіть роль для пінгу або пропустіть:**",
                    view=view,
                )
                return
        await interaction.response.send_modal(LFGModal(selected_activities, self._activity_type))

class ActivitySelectView(discord.ui.View):
    def __init__(self, activities: list[str], activity_type: str) -> None:
        super().__init__(timeout=120)
        self.add_item(ActivitySelect(activities, activity_type))

class VoteSelect(discord.ui.Select):
    def __init__(self, msg_id: str, options: list[str]) -> None:
        self._msg_id = msg_id
        super().__init__(
            placeholder="Оберіть ваш варіант...",
            options=[discord.SelectOption(label=opt, value=opt) for opt in options]
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        session = lfg_sessions.get(self._msg_id)
        if not session:
            await interaction.response.send_message("Збір не знайдено.", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        votes = session.setdefault("votes", {})
        votes[user_id] = self.values[0]
        await upsert_session(self._msg_id, session)
        try:
            msg = await interaction.channel.fetch_message(int(self._msg_id))
            await msg.edit(embed=build_lfg_embed(session))
        except Exception:
            pass
        await interaction.response.send_message(f"✅ Ваш голос за **{self.values[0]}** прийнято!", ephemeral=True)

class VoteSelectView(discord.ui.View):
    def __init__(self, msg_id: str, options: list[str]) -> None:
        super().__init__(timeout=60)
        self.add_item(VoteSelect(msg_id, options))

class PingRoleSelect(discord.ui.Select):
    def __init__(self, activities: list[str], activity_type: str, role_options: list[tuple[str, str]]) -> None:
        self._activities = activities
        self._activity_type = activity_type
        options = [
            discord.SelectOption(
                label=label,
                value=value,
                emoji="📢" if value == "everyone" else "🏷️",
            )
            for value, label in role_options
        ]
        super().__init__(placeholder="Оберіть роль для пінгу...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            LFGModal(self._activities, self._activity_type, mention=self.values[0])
        )

class PingRoleView(discord.ui.View):
    def __init__(self, activities: list[str], activity_type: str, role_options: list[tuple[str, str]]) -> None:
        super().__init__(timeout=120)
        self._activities = activities
        self._activity_type = activity_type
        self.add_item(PingRoleSelect(activities, activity_type, role_options))

    @discord.ui.button(label="Без пінгу", style=discord.ButtonStyle.secondary, emoji="🔕")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(
            LFGModal(self._activities, self._activity_type, mention=None)
        )

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

    def __init__(self, activities: list[str], activity_type: str, mention: str | None = None) -> None:
        super().__init__()
        self._activities = activities
        self._activity_type = activity_type
        self._mention = mention

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
            )
            return

        time_str = f"{h:02d}:{m:02d}"
        capacity = RAID_MAX if self._activity_type == "raid" else DUNGEON_MAX
        leader_id = str(interaction.user.id)
        description = self.description_input.value.strip()
        now = datetime.now(TZ_KYIV)
        scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if scheduled <= now:
            scheduled += timedelta(days=1)

        ts = int(scheduled.timestamp())
        display_time = f"<t:{ts}:t>"
        options = []
        if len(self._activities) > 1:
            activity_name = "Голосування за активність"
            options = self._activities
        else:
            activity_name = self._activities[0]

        session: dict = {
            "activity":      activity_name,
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
            "options":       options,
            "votes":         {},
            "member_data":   {},
        }
        view = LFGView(session)
        await view._update_member_stats(interaction, session, leader_id)

        mention_content = None

        if self._mention == "everyone":
            mention_content = "@everyone"
        elif self._mention:
            mention_content = f"<@&{self._mention}>"
        await interaction.response.send_message(
            content=mention_content, embed=build_lfg_embed(session), view=view
        )
        message = await interaction.original_response()
        activity_label = "Рейд" if self._activity_type == "raid" else "Данж"
        try:
            thread_name = f"[{activity_label}] {activity_name} о {time_str}"
            if len(thread_name) > 100: thread_name = thread_name[:97] + "..."
            thread = await message.create_thread(
                name=thread_name,
                auto_archive_duration=1440,
            )
            await thread.send(
                f"🎮 **Збір відкрито!** {interaction.user.mention} організує "
                f"**{activity_name}** о {display_time}.\n"
                f"Натисніть **➕ Приєднатись / Вийти** під повідомленням, щоб долучитися. "
                f"Тут можна обговорювати активність."
            )
            session["thread_id"] = str(thread.id)
        except discord.HTTPException as e:
            logger.error(f"Не вдалося створити гілку: {e}")
        msg_id = str(message.id)
        lfg_sessions[msg_id] = session
        await upsert_session(msg_id, session)
