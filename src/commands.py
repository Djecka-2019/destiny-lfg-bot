import discord
from discord import app_commands

from bungie import get_activity_completions, search_bungie_player
from constants import DUNGEONS, RAIDS
from database import get_discord_profile, save_profile
from embeds import build_profile_embed
from views import ActivitySelectView


def _parse_bungie_name(raw: str) -> tuple[str, int] | None:
    if "#" not in raw:
        return None
    name, code_str = raw.rsplit("#", 1)
    try:
        return name.strip(), int(code_str.strip())
    except ValueError:
        return None


def setup_commands(bot) -> None:
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
