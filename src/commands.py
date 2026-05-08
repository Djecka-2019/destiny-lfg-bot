import discord
from discord import app_commands
from bungie import get_activity_completions, get_character_emblem, search_bungie_player
from constants import DUNGEONS, RAIDS
from database import add_ping_role, get_commendation_stats, get_commendations_given_count, get_discord_profile, get_ping_roles, remove_ping_role, save_profile
from embeds import build_commendation_embed, build_profile_embed, build_lfg_embed
from oauth import generate_auth_link
from views import ActivitySelectView, TemplateView, RegisterTemplateView

class _OAuthLinkView(discord.ui.View):
    def __init__(self, url: str) -> None:
        super().__init__()
        self.add_item(discord.ui.Button(label="Авторизуватись через Bungie", url=url, style=discord.ButtonStyle.link))


ping_group = app_commands.Group(
    name="ping-roles",
    description="Керування ролями, які можна пінгувати при створенні збору",
    default_permissions=discord.Permissions(manage_guild=True),
)

@ping_group.command(name="add", description="Додати роль до списку пінгу")
@app_commands.describe(role="Роль для дозволу пінгу")
async def ping_add(interaction: discord.Interaction, role: discord.Role) -> None:
    await add_ping_role(str(interaction.guild_id), str(role.id))
    await interaction.response.send_message(
        f"✅ Роль {role.mention} додана до списку пінгу.", ephemeral=True
    )

@ping_group.command(name="remove", description="Видалити роль зі списку пінгу")
@app_commands.describe(role="Роль для видалення")
async def ping_remove(interaction: discord.Interaction, role: discord.Role) -> None:
    removed = await remove_ping_role(str(interaction.guild_id), str(role.id))
    if removed:
        await interaction.response.send_message(
            f"✅ Роль {role.mention} видалена зі списку пінгу.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"ℹ️ Роль {role.mention} не знайдена у списку.", ephemeral=True
        )

@ping_group.command(name="everyone", description="Увімкнути або вимкнути пінг @everyone")
@app_commands.describe(enabled="True — дозволити, False — заборонити")
async def ping_everyone(interaction: discord.Interaction, enabled: bool) -> None:
    if enabled:
        await add_ping_role(str(interaction.guild_id), "everyone")
        await interaction.response.send_message("✅ Пінг @everyone увімкнено.", ephemeral=True)
    else:
        removed = await remove_ping_role(str(interaction.guild_id), "everyone")
        msg = "✅ Пінг @everyone вимкнено." if removed else "ℹ️ Пінг @everyone вже був вимкнений."
        await interaction.response.send_message(msg, ephemeral=True)

@ping_group.command(name="list", description="Показати налаштовані ролі для пінгу")
async def ping_list(interaction: discord.Interaction) -> None:
    roles = await get_ping_roles(str(interaction.guild_id))
    if not roles:
        await interaction.response.send_message(
            "ℹ️ Ролі не налаштовані. Додайте через `/ping-roles add`.",
            ephemeral=True,
        )
        return
    lines = []
    for rid in roles:
        if rid == "everyone":
            lines.append("• @everyone")
        else:
            role = interaction.guild.get_role(int(rid))
            lines.append(f"• {role.mention}" if role else f"• <видалена роль {rid}>")
    await interaction.response.send_message(
        "📢 **Ролі для пінгу:**\n" + "\n".join(lines), ephemeral=True
    )

def _parse_bungie_name(raw: str) -> tuple[str, int] | None:
    if "#" not in raw:
        return None
    name, code_str = raw.rsplit("#", 1)
    try:
        return name.strip(), int(code_str.strip())
    except ValueError:
        return None

def setup_commands(bot) -> None:
    @bot.tree.command(name="help", description="Інформація про можливості бота та доступні команди")
    async def help_command(interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Довідка по роботі з Destiny LFG",
            description=(
                "Цей бот допомагає організовувати рейди та данжі, відстежувати статистику "
                "гравців та автоматизувати нагадування про збори."
            ),
            color=discord.Color.blue()
        )

        embed.add_field(
            name="⚔️ Організація зборів",
            value=(
                "`/lfg-raid` — Створити збір на рейд (6 місць).\n"
                "`/lfg-dungeon` — Створити збір на данж (3 місця).\n"
                "`/lfg-pvp` — Створити збір на PVP (3 місця).\n"
                "Бот автоматично створить гілку для обговорення та надішле нагадування за 15 хвилин."
            ),
            inline=False
        )

        embed.add_field(
            name="📊 Профіль та статистика",
            value=(
                "`/add-account` — Прив'язати Bungie Name до вашого Discord.\n"
                "`/register` / `/oauth` — Аліаси для реєстрації.\n"
                "`/profile` — Переглянути вашу статистику проходжень.\n"
                "`/commendations` — Переглянути отримані похвали (своїх або іншого гравця)."
            ),
            inline=False
        )

        embed.add_field(
            name="⚙️ Налаштування (для адмінів)",
            value=(
                "`/template` — Створити постійну кнопку для зборів у каналі.\n"
                "`/register-template` — Створити кнопку для прив'язки акаунту.\n"
                "`/ping-roles list` — Переглянути ролі для сповіщень.\n"
                "`/ping-roles add` — Додати роль для пінгу."
            ),
            inline=False
        )

        embed.set_footer(text="Бот працює за київським часом (GMT+3).")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="lfg-raid", description="Створити збір на рейд в Destiny 2")
    async def search_raids(interaction: discord.Interaction) -> None:
        view = ActivitySelectView(RAIDS, "raid")
        await interaction.response.send_message(
            "⚔️ **Оберіть рейд для збору:**", view=view, ephemeral=True
        )

    @bot.tree.command(name="lfg-dungeon", description="Створити збір на данж в Destiny 2")
    async def search_dungeons(interaction: discord.Interaction) -> None:
        view = ActivitySelectView(DUNGEONS, "dungeon")
        await interaction.response.send_message(
            "🗡️ **Оберіть данж для збору:**", view=view, ephemeral=True
        )

    @bot.tree.command(name="lfg-pvp", description="Створити збір на PVP в Destiny 2")
    async def search_pvp(interaction: discord.Interaction) -> None:
        # Для PVP ми пропускаємо вибір активності і йдемо одразу до ролей/дати
        from views import DateView, PingRoleView
        from database import get_ping_roles
        
        selected_activities = ["PVP"]
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
                view = PingRoleView(selected_activities, "pvp", role_options)
                await interaction.response.send_message(
                    content="📢 **Оберіть роль для пінгу або пропустіть:**",
                    view=view,
                    ephemeral=True
                )
                return
        await interaction.response.send_message(
            content="📅 **Оберіть дату збору:**",
            view=DateView(selected_activities, "pvp", mention=None),
            ephemeral=True
        )

    @bot.tree.command(name="template", description="Надіслати шаблонне повідомлення з кнопкою для створення збору")
    @app_commands.describe(
        type="Тип активності (рейд, данж або пвп)",
        channel="Канал, куди надіслати повідомлення (за замовчуванням — поточний)",
        title="Заголовок ембеду",
        description="Опис ембеду",
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="Raid", value="raid"),
        app_commands.Choice(name="Dungeon", value="dungeon"),
        app_commands.Choice(name="PVP", value="pvp"),
    ])
    @app_commands.checks.has_permissions(manage_channels=True)
    async def send_template(
        interaction: discord.Interaction,
        type: str,
        channel: discord.TextChannel | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> None:
        target_channel = channel or interaction.channel
        view = TemplateView(type)
        
        if type == "raid":
            embed_title = title or "⚔️ Організація рейдів"
            color = discord.Color.from_rgb(255, 185, 0)
        elif type == "dungeon":
            embed_title = title or "🗡️ Організація данжів"
            color = discord.Color.from_rgb(130, 50, 210)
        else:
            embed_title = title or "🔫 Організація PVP"
            color = discord.Color.from_rgb(220, 20, 60)
        
        default_desc = (
            "Бажаєте зібрати команду для спільного проходження? Натисніть кнопку нижче!\n\n"
            "**Як це працює:**\n"
            "1. Натисніть на кнопку під цим повідомленням.\n"
            "2. Оберіть активність у меню (для рейдів/данжів).\n"
            "3. Вкажіть час та додаткову інформацію.\n"
            "4. Бот створить збір та окрему гілку для обговорення."
        )
        embed_description = description or default_desc
        
        embed = discord.Embed(
            title=embed_title,
            description=embed_description,
            color=color
        )
        
        # Використовуємо Sweeper Bot для всіх прев'ю
        image_url = "https://www.bungie.net/img/theme/bungienet/bgs/bg_error_sweeperbot.jpg"
        embed.set_image(url=image_url)
        embed.set_footer(text="Destiny LFG • Натисніть кнопку для старту")

        try:
            await target_channel.send(embed=embed, view=view)
            await interaction.response.send_message(f"✅ Шаблон надіслано у {target_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Помилка: {e}", ephemeral=True)

    @bot.tree.command(name="add-account", description="Прив'яжіть ваш акаунт Bungie до Discord через OAuth")
    async def link_account(interaction: discord.Interaction) -> None:
        url = await generate_auth_link(str(interaction.user.id))
        await interaction.response.send_message(
            f"🔗 Натисніть кнопку нижче, щоб авторизуватися через Bungie.\n"
            f"Після авторизації акаунт буде автоматично прив'язано до вашого Discord.",
            view=_OAuthLinkView(url),
            ephemeral=True,
        )

    @bot.tree.command(name="register", description="Alias for /add-account")
    async def register_alias(interaction: discord.Interaction) -> None:
        await link_account(interaction)

    @bot.tree.command(name="oauth", description="Alias for /add-account")
    async def oauth_alias(interaction: discord.Interaction) -> None:
        await link_account(interaction)

    @bot.tree.command(name="register-template", description="Надіслати повідомлення з кнопкою для реєстрації")
    @app_commands.describe(
        channel="Канал, куди надіслати повідомлення (за замовчуванням — поточний)",
        title="Заголовок ембеду",
        description="Опис ембеду",
    )
    @app_commands.checks.has_permissions(manage_channels=True)
    async def send_register_template(
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> None:
        target_channel = channel or interaction.channel
        view = RegisterTemplateView()
        
        embed_title = title or "🔗 Реєстрація Bungie акаунту"
        
        default_desc = (
            "Вітаємо у нашій спільноті! Для отримання доступу до всіх функцій бота "
            "та сервера, необхідно прив'язати ваш Bungie акаунт.\n\n"
            "**Після реєстрації ви отримаєте:**\n"
            "• Роль зареєстрованого користувача.\n"
            "• Можливість створювати збори на рейди та данжі.\n"
            "• Автоматичне відображення вашої статистики у зборах."
        )
        embed_description = description or default_desc
        
        embed = discord.Embed(
            title=embed_title,
            description=embed_description,
            color=discord.Color.blue()
        )
        
        # Використовуємо зображення з логотипом Bungie/Destiny
        embed.set_image(url="https://www.bungie.net/common/destiny2_content/icons/870634288017351b.jpg")
        embed.set_footer(text="Destiny LFG • Натисніть кнопку для авторизації")

        try:
            await target_channel.send(embed=embed, view=view)
            await interaction.response.send_message(f"✅ Шаблон реєстрації надіслано у {target_channel.mention}", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Помилка: {e}", ephemeral=True)

    @bot.tree.command(name="sync-roles", description="Оновити свої ролі на основі статистики Bungie")
    async def sync_roles_command(interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        
        result = await get_discord_profile(str(interaction.user.id))
        if not result:
            await interaction.followup.send(
                "❌ Спочатку прив'яжіть акаунт через `/add-account`.",
                ephemeral=True,
            )
            return
            
        from bungie import get_sync_stats
        from role_sync import sync_member_roles
        
        membership_type, membership_id, _ = result
        stats = await get_sync_stats(membership_type, membership_id)
        
        if not stats:
            await interaction.followup.send("❌ Не вдалося отримати вашу статистику Bungie.", ephemeral=True)
            return
            
        synced_roles = await sync_member_roles(interaction.user, stats)
        
        if synced_roles:
            role_list = ", ".join(synced_roles)
            await interaction.followup.send(f"✅ Ваші ролі оновлено! Отримано: **{role_list}**", ephemeral=True)
        else:
            await interaction.followup.send("✅ Ваші ролі вже відповідають статистиці.", ephemeral=True)

    @bot.tree.command(name="sync", description="Alias for /sync-roles")
    async def sync_alias(interaction: discord.Interaction) -> None:
        await sync_roles_command(interaction)

    @bot.tree.command(name="profile", description="Переглянути статистику Destiny 2")
    @app_commands.describe(
        member="Discord користувач (необов'язково)",
        bungie_name="Bungie name у форматі Ім'я#1234 (якщо не прив'язано)",
    )
    async def show_profile(
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        bungie_name: str | None = None,
    ) -> None:
        await interaction.response.defer()
        membership_type: int
        membership_id: str
        bname: str

        if member:
            result = await get_discord_profile(str(member.id))
            if not result:
                await interaction.followup.send(
                    f"❌ {member.mention} ще не прив'язав Bungie акаунт. "
                    "Попросіть їх використати `/add-account`.",
                    ephemeral=True,
                )
                return
            membership_type, membership_id, bname = result
        elif bungie_name:
            parsed = _parse_bungie_name(bungie_name)
            if not parsed:
                await interaction.followup.send("❌ Формат: `Ім'я#1234`", ephemeral=True)
                return
            player = await search_bungie_player(*parsed)
            if not player:
                await interaction.followup.send(
                    f"❌ Гравця `{bungie_name}` не знайдено", ephemeral=True
                )
                return
            membership_type = player["membership_type"]
            membership_id   = player["membership_id"]
            bname           = player["bungie_name"]
        else:
            result = await get_discord_profile(str(interaction.user.id))
            if not result:
                await interaction.followup.send(
                    "❌ Спочатку прив'яжіть акаунт через `/add-account` або вкажіть `bungie_name`.",
                    ephemeral=True,
                )
                return
            membership_type, membership_id, bname = result

        completions = await get_activity_completions(membership_type, membership_id)
        await interaction.followup.send(embed=build_profile_embed(bname, completions))

    @bot.tree.command(name="commendations", description="Переглянути статистику похвал гравця")
    @app_commands.describe(member="Discord користувач (необов'язково, за замовчуванням — ви)")
    async def show_commendations(
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        await interaction.response.defer()
        target = member or interaction.user
        received = await get_commendation_stats(str(target.id))
        given = await get_commendations_given_count(str(target.id))
        emblem = None
        profile = await get_discord_profile(str(target.id))
        if profile:
            emblem = await get_character_emblem(profile[0], profile[1])
        await interaction.followup.send(embed=build_commendation_embed(target, received, given, emblem))

    bot.tree.add_command(ping_group)
