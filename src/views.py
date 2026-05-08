import logging
import re
from datetime import date as date_type, datetime, timedelta
import discord
from bungie import commendation_defs, get_activity_completions, get_activity_stats, get_character_emblem, search_bungie_player_by_name
from constants import DUNGEON_MAX, NEWBIE_THRESHOLD, RAID_MAX, SHERPA_THRESHOLD, TZ_KYIV, RANDOM_RAID, RANDOM_DUNGEON, RAIDS, DUNGEONS
from database import delete_session, get_discord_profile, get_ping_roles, lfg_sessions, save_commendation, upsert_session
from embeds import build_lfg_embed

logger = logging.getLogger("destiny_bot")

class CreateActivityButton(discord.ui.Button):
    def __init__(self, activity_type: str) -> None:
        label = "Створити збір на рейд" if activity_type == "raid" else "Створити збір на данж"
        emoji = "⚔️" if activity_type == "raid" else "🗡️"
        super().__init__(
            label=label,
            style=discord.ButtonStyle.blurple,
            custom_id=f"template:create:{activity_type}",
            emoji=emoji
        )
        self._activity_type = activity_type

    async def callback(self, interaction: discord.Interaction) -> None:
        activities = RAIDS if self._activity_type == "raid" else DUNGEONS
        view = ActivitySelectView(activities, self._activity_type)
        label = "рейд" if self._activity_type == "raid" else "данж"
        await interaction.response.send_message(
            f"{self.emoji} **Оберіть {label} для збору:**", view=view, ephemeral=True
        )

class TemplateView(discord.ui.View):
    def __init__(self, activity_type: str) -> None:
        super().__init__(timeout=None)
        self.add_item(CreateActivityButton(activity_type))

class LinkAccountButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Прив'язати акаунт",
            style=discord.ButtonStyle.green,
            custom_id="template:register",
            emoji="🔗"
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        from oauth import generate_auth_link
        url = await generate_auth_link(str(interaction.user.id))
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Авторизуватись через Bungie", url=url, style=discord.ButtonStyle.link))
        await interaction.response.send_message(
            "🔗 Натисніть кнопку нижче для авторизації.\n"
            "Це повідомлення бачите лише ви.",
            view=view,
            ephemeral=True
        )

class RegisterTemplateView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(LinkAccountButton())

class _CommendationChoice(discord.ui.Button):
    def __init__(self, index: int, name_uk: str, emoji: str) -> None:
        super().__init__(label=name_uk, emoji=emoji, style=discord.ButtonStyle.primary, row=0)
        self._index = index

    async def callback(self, interaction: discord.Interaction) -> None:
        view: CommendationWizardView = self.view
        teammate_id = view._teammates[view._current]
        view._commendations[teammate_id] = self._index
        comm_name = commendation_defs[self._index]["name_uk"]
        await save_commendation(view._session_id, str(interaction.user.id), teammate_id, comm_name)
        await view._advance(interaction)


class _CommendationSkip(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Пропустити", style=discord.ButtonStyle.secondary, emoji="➡️", row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view._advance(interaction)


class CommendationWizardView(discord.ui.View):
    def __init__(self, teammates: list[str], activity: str, session_id: str,
                 emblem_cache: dict[str, dict | None] | None = None) -> None:
        super().__init__(timeout=300)
        self._teammates = teammates
        self._activity = activity
        self._session_id = session_id
        self._emblem_cache: dict[str, dict | None] = emblem_cache or {}
        self._current = 0
        self._commendations: dict[str, int] = {}
        for i, comm in enumerate(commendation_defs):
            self.add_item(_CommendationChoice(i, comm["name_uk"], comm["emoji"]))
        self.add_item(_CommendationSkip())

    def build_step_embed(self) -> discord.Embed:
        teammate_id = self._teammates[self._current]
        idx = self._current + 1
        total = len(self._teammates)
        embed = discord.Embed(
            title=f"🏆 Похвали після {self._activity}",
            description=f"Оберіть похвалу для <@{teammate_id}>\n({idx} з {total})",
            color=discord.Color.gold(),
        )
        emblem = self._emblem_cache.get(teammate_id)
        if emblem:
            if emblem.get("icon"):
                embed.set_thumbnail(url=emblem["icon"])
            if emblem.get("background"):
                embed.set_image(url=emblem["background"])
        return embed

    def _build_summary_embed(self) -> discord.Embed:
        embed = discord.Embed(title="🏆 Похвали роздано!", color=discord.Color.gold())
        for tm_id, comm_idx in self._commendations.items():
            comm = commendation_defs[comm_idx]
            embed.add_field(
                name=f"{comm['emoji']} {comm['name_uk']}",
                value=f"<@{tm_id}>",
                inline=True,
            )
        if not self._commendations:
            embed.description = "Ви не роздали жодної похвали."
        return embed

    async def _advance(self, interaction: discord.Interaction) -> None:
        self._current += 1
        if self._current >= len(self._teammates):
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(embed=self._build_summary_embed(), view=self)
        else:
            await interaction.response.edit_message(embed=self.build_step_embed())


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

    @discord.ui.button(
        label="Роздати похвали",
        style=discord.ButtonStyle.blurple,
        custom_id="lfg:commend",
        emoji="🏆",
    )
    async def commend_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        msg_id = str(interaction.message.id)
        session = lfg_sessions.get(msg_id)
        if not session:
            await interaction.response.send_message("Ця активність вже не активна.", ephemeral=True)
            return

        if str(interaction.user.id) != session["leader_id"]:
            await interaction.response.send_message(
                "❌ Лише організатор може запустити роздачу похвал.", ephemeral=True
            )
            return

        all_members: list = session["members"]
        if len(all_members) < 2:
            await interaction.response.send_message(
                "ℹ️ Для похвал потрібно мінімум 2 учасники.", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"✅ Надсилаю запит на похвали {len(all_members)} учасникам...", ephemeral=True
        )

        activity = session["activity"]
        bot = interaction.client

        emblem_cache: dict[str, dict | None] = {}
        for mid in all_members:
            profile = await get_discord_profile(mid)
            if profile:
                emblem_cache[mid] = await get_character_emblem(profile[0], profile[1])

        sent, blocked = 0, 0
        for member_id in all_members:
            teammates = [m for m in all_members if m != member_id]
            try:
                user = await bot.fetch_user(int(member_id))
                view = CommendationWizardView(teammates, activity, msg_id, emblem_cache)
                await user.send(embed=view.build_step_embed(), view=view)
                sent += 1
            except discord.Forbidden:
                blocked += 1
                logger.warning(f"[commend] DM заблоковано: {member_id}")
            except Exception as e:
                logger.error(f"[commend] Помилка DM для {member_id}: {e}")

        if blocked:
            await interaction.followup.send(
                f"⚠️ {blocked} учасників мають закриті DM і не отримали запит.",
                ephemeral=True,
            )

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
        await interaction.response.edit_message(
            content="📅 **Оберіть дату збору:**",
            view=DateView(selected_activities, self._activity_type, mention=None),
        )

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
        await interaction.response.edit_message(
            content="📅 **Оберіть дату збору:**",
            view=DateView(self._activities, self._activity_type, mention=self.values[0]),
        )

class PingRoleView(discord.ui.View):
    def __init__(self, activities: list[str], activity_type: str, role_options: list[tuple[str, str]]) -> None:
        super().__init__(timeout=120)
        self._activities = activities
        self._activity_type = activity_type
        self.add_item(PingRoleSelect(activities, activity_type, role_options))

    @discord.ui.button(label="Без пінгу", style=discord.ButtonStyle.secondary, emoji="🔕")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(
            content="📅 **Оберіть дату збору:**",
            view=DateView(self._activities, self._activity_type, mention=None),
        )

_DAYS_UA = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця", "Субота", "Неділя"]
_MONTHS_UA = ["січ.", "лют.", "бер.", "квіт.", "трав.", "черв.", "лип.", "серп.", "вер.", "жовт.", "лист.", "груд."]

def _date_label(d: date_type, offset: int) -> str:
    m = _MONTHS_UA[d.month - 1]
    if offset == 0:
        return f"Сьогодні, {d.day} {m}"
    if offset == 1:
        return f"Завтра, {d.day} {m}"
    return f"{_DAYS_UA[d.weekday()]}, {d.day} {m}"


class DateButton(discord.ui.Button):
    def __init__(self, activities: list[str], activity_type: str, mention: str | None,
                 date_iso: str, label: str, primary: bool) -> None:
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary if primary else discord.ButtonStyle.secondary,
        )
        self._activities = activities
        self._activity_type = activity_type
        self._mention = mention
        self._date_iso = date_iso

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            LFGModal(self._activities, self._activity_type, self._mention, self._date_iso)
        )


class DateFutureSelect(discord.ui.Select):
    def __init__(self, activities: list[str], activity_type: str, mention: str | None) -> None:
        self._activities = activities
        self._activity_type = activity_type
        self._mention = mention

        now = datetime.now(TZ_KYIV)
        options = [
            discord.SelectOption(
                label=_date_label((now + timedelta(days=i)).date(), i),
                value=(now + timedelta(days=i)).date().isoformat(),
            )
            for i in range(2, 9)
        ]
        super().__init__(placeholder="Інша дата...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            LFGModal(self._activities, self._activity_type, self._mention, self.values[0])
        )


class DateView(discord.ui.View):
    def __init__(self, activities: list[str], activity_type: str, mention: str | None) -> None:
        super().__init__(timeout=120)
        now = datetime.now(TZ_KYIV)
        today = now.date()
        tomorrow = (now + timedelta(days=1)).date()
        self.add_item(DateButton(activities, activity_type, mention, today.isoformat(),
                                 _date_label(today, 0), primary=True))
        self.add_item(DateButton(activities, activity_type, mention, tomorrow.isoformat(),
                                 _date_label(tomorrow, 1), primary=False))
        self.add_item(DateFutureSelect(activities, activity_type, mention))


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

    def __init__(self, activities: list[str], activity_type: str,
                 mention: str | None = None, date_iso: str | None = None) -> None:
        super().__init__()
        self._activities = activities
        self._activity_type = activity_type
        self._mention = mention
        self._date_iso = date_iso

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

        if self._date_iso:
            selected_date = date_type.fromisoformat(self._date_iso)
            scheduled = now.replace(year=selected_date.year, month=selected_date.month,
                                    day=selected_date.day, hour=h, minute=m, second=0, microsecond=0)
            if scheduled <= now:
                await interaction.response.send_message(
                    "❌ Вказаний час вже минув. Оберіть пізніший час або іншу дату.",
                    ephemeral=True,
                )
                return
        else:
            scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if scheduled <= now:
                scheduled += timedelta(days=1)

        ts = int(scheduled.timestamp())
        display_time = f"<t:{ts}:f>" if scheduled.date() != now.date() else f"<t:{ts}:t>"
        options = []
        if len(self._activities) > 1:
            activity_name = "Голосування за активність"
            options = self._activities
        else:
            activity_name = self._activities[0]

        leader_profile = await get_discord_profile(leader_id)
        leader_bungie_name = leader_profile[2] if leader_profile else None

        session: dict = {
            "activity":           activity_name,
            "activity_type":      self._activity_type,
            "time":               time_str,
            "description":        description,
            "leader_id":          leader_id,
            "leader_name":        interaction.user.display_name,
            "leader_bungie_name": leader_bungie_name,
            "members":            [leader_id],
            "reserves":           [],
            "capacity":           capacity,
            "thread_id":          None,
            "guild_id":           str(interaction.guild_id),
            "channel_id":         str(interaction.channel_id),
            "scheduled_at":       scheduled.isoformat(),
            "reminder_sent":      False,
            "options":            options,
            "votes":              {},
            "member_data":        {},
            "mention":            self._mention,
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
            date_label = f" {scheduled.strftime('%d.%m')}" if scheduled.date() != now.date() else ""
            thread_name = f"[{activity_label}] {activity_name} о {time_str}{date_label}"
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
