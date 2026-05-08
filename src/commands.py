import discord
from discord import app_commands
from bungie import get_activity_completions, get_character_emblem, search_bungie_player
from constants import DUNGEONS, RAIDS
from database import add_ping_role, get_commendation_stats, get_commendations_given_count, get_discord_profile, get_ping_roles, remove_ping_role, save_profile
from embeds import build_commendation_embed, build_profile_embed, build_lfg_embed
from views import ActivitySelectView

ping_group = app_commands.Group(
    name="пінг-ролі",
    description="Керування ролями для пінгу при створенні збору",
    default_permissions=discord.Permissions(manage_guild=True),
)

@ping_group.command(name="додати", description="Додати роль до списку пінгу")
@app_commands.describe(роль="Роль, яку можна пінгувати при створенні збору")
async def ping_add(interaction: discord.Interaction, роль: discord.Role) -> None:
    await add_ping_role(str(interaction.guild_id), str(роль.id))
    await interaction.response.send_message(
        f"✅ Роль {роль.mention} додано до списку пінгу.", ephemeral=True
    )

@ping_group.command(name="видалити", description="Видалити роль зі списку пінгу")
@app_commands.describe(роль="Роль для видалення")
async def ping_remove(interaction: discord.Interaction, роль: discord.Role) -> None:
    removed = await remove_ping_role(str(interaction.guild_id), str(роль.id))
    if removed:
        await interaction.response.send_message(
            f"✅ Роль {роль.mention} видалено зі списку пінгу.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"ℹ️ Роль {роль.mention} не знайдена у списку.", ephemeral=True
        )

@ping_group.command(name="everyone", description="Увімкнути або вимкнути пінг @everyone")
@app_commands.describe(ввімкнути="True — дозволити, False — заборонити")
async def ping_everyone(interaction: discord.Interaction, ввімкнути: bool) -> None:
    if ввімкнути:
        await add_ping_role(str(interaction.guild_id), "everyone")
        await interaction.response.send_message("✅ Пінг @everyone увімкнено.", ephemeral=True)
    else:
        removed = await remove_ping_role(str(interaction.guild_id), "everyone")
        msg = "✅ Пінг @everyone вимкнено." if removed else "ℹ️ Пінг @everyone вже був вимкнений."
        await interaction.response.send_message(msg, ephemeral=True)

@ping_group.command(name="список", description="Показати налаштовані ролі для пінгу")
async def ping_list(interaction: discord.Interaction) -> None:
    roles = await get_ping_roles(str(interaction.guild_id))
    if not roles:
        await interaction.response.send_message(
            "ℹ️ Жодної ролі не налаштовано. Додайте через `/пінг-ролі додати`.",
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
    @bot.tree.command(name="допомога", description="Інформація про можливості бота та доступні команди")
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
                "`/пошук-рейдів` — Створити збір на рейд (6 місць).\n"
                "`/пошук-данжів` — Створити збір на данж (3 місця).\n"
                "При виборі можна обрати **декілька активностей** для голосування або "
                "**випадковий рейд**, який буде визначено ботом перед початком.\n"
                "Бот автоматично створить гілку для обговорення та надішле нагадування за 15 хвилин."
            ),
            inline=False
        )

        embed.add_field(
            name="📊 Профіль та статистика",
            value=(
                "`/додати-аккаунт` — Прив'язати Bungie Name до вашого Discord.\n"
                "`/профіль` — Переглянути вашу статистику проходжень.\n"
                "`/похвали` — Переглянути отримані похвали (своїх або іншого гравця).\n"
                "Статистика (кількість проходжень / шерпи) автоматично відображається "
                "біля вашого ніка в списку учасників збору."
            ),
            inline=False
        )

        embed.add_field(
            name="⚙️ Налаштування (для адмінів)",
            value=(
                "`/пінг-ролі список` — Переглянути ролі для сповіщень.\n"
                "`/пінг-ролі додати` — Додати роль, яку можна пінгувати при створенні збору.\n"
                "`/пінг-ролі everyone` — Дозволити або заборонити пінг @everyone."
            ),
            inline=False
        )

        embed.set_footer(text="Бот працює за київським часом (GMT+3).")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="пошук-рейдів", description="Створити збір на рейд в Destiny 2")
    async def search_raids(interaction: discord.Interaction) -> None:
        view = ActivitySelectView(RAIDS, "raid")
        await interaction.response.send_message(
            "⚔️ **Оберіть рейд для збору:**", view=view, ephemeral=True
        )

    @bot.tree.command(name="пошук-данжів", description="Створити збір на данж в Destiny 2")
    async def search_dungeons(interaction: discord.Interaction) -> None:
        view = ActivitySelectView(DUNGEONS, "dungeon")
        await interaction.response.send_message(
            "🗡️ **Оберіть данж для збору:**", view=view, ephemeral=True
        )

    @bot.tree.command(name="додати-аккаунт", description="Прив'яжіть ваш акаунт Bungie до Discord")
    @app_commands.describe(bungie_name="Ваш Bungie name у форматі Ім'я#1234")
    async def link_account(interaction: discord.Interaction, bungie_name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        parsed = _parse_bungie_name(bungie_name)
        if not parsed:
            await interaction.followup.send("❌ Формат: `Ім'я#1234`", ephemeral=True)
            return
        player = await search_bungie_player(*parsed)
        if not player:
            await interaction.followup.send(
                f"❌ Гравця `{bungie_name}` не знайдено на Bungie.\n"
                "Перевірте ім'я та код (приклад: `Guardian#1234`)",
                ephemeral=True,
            )
            return
        await save_profile(
            str(interaction.user.id),
            player["membership_type"],
            player["membership_id"],
            player["bungie_name"],
        )
        await interaction.followup.send(
            f"✅ Акаунт **{player['bungie_name']}** прив'язано до вашого Discord!",
            ephemeral=True,
        )

    @bot.tree.command(name="профіль", description="Переглянути статистику Destiny 2")
    @app_commands.describe(
        гравець="Discord користувач (необов'язково)",
        bungie_name="Bungie name у форматі Ім'я#1234 (якщо не прив'язано)",
    )
    async def show_profile(
        interaction: discord.Interaction,
        гравець: discord.Member | None = None,
        bungie_name: str | None = None,
    ) -> None:
        await interaction.response.defer()
        membership_type: int
        membership_id: str
        bname: str

        if гравець:
            result = await get_discord_profile(str(гравець.id))
            if not result:
                await interaction.followup.send(
                    f"❌ {гравець.mention} ще не прив'язав Bungie акаунт. "
                    "Попросіть їх використати `/додати-аккаунт`.",
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
                    "❌ Спочатку прив'яжіть акаунт через `/додати-аккаунт` або вкажіть `bungie_name`.",
                    ephemeral=True,
                )
                return
            membership_type, membership_id, bname = result

        completions = await get_activity_completions(membership_type, membership_id)
        await interaction.followup.send(embed=build_profile_embed(bname, completions))

    @bot.tree.command(name="похвали", description="Переглянути статистику похвал гравця")
    @app_commands.describe(гравець="Discord користувач (необов'язково, за замовчуванням — ви)")
    async def show_commendations(
        interaction: discord.Interaction,
        гравець: discord.Member | None = None,
    ) -> None:
        await interaction.response.defer()
        target = гравець or interaction.user
        received = await get_commendation_stats(str(target.id))
        given = await get_commendations_given_count(str(target.id))
        emblem = None
        profile = await get_discord_profile(str(target.id))
        if profile:
            emblem = await get_character_emblem(profile[0], profile[1])
        await interaction.followup.send(embed=build_commendation_embed(target, received, given, emblem))

    bot.tree.add_command(ping_group)
