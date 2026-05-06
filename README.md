# Destiny LFG Bot

A Discord bot for organizing Destiny 2 raid and dungeon groups (LFG — Looking For Group). Built for Ukrainian-speaking communities.

## Features

- Create LFG posts for raids and dungeons via slash commands
- Join/leave buttons with automatic reserve queue and promotion
- Per-session discussion threads with join/leave announcements
- 15-minute DM reminder before activity starts
- Team stats: completion counts and Sherpa/newbie tags for each member
- Player profiles linked to Bungie accounts with full raid/dungeon history
- Activity images fetched from the Bungie manifest at startup

## Slash Commands

| Command | Description |
|---|---|
| `/пошук-рейдів` | Create a raid LFG post |
| `/пошук-данжів` | Create a dungeon LFG post |
| `/додати-аккаунт` | Link your Bungie account to Discord |
| `/профіль` | View raid/dungeon completion stats |

## Setup

### Prerequisites

- Docker and Docker Compose
- A [Discord bot token](https://discord.com/developers/applications)
- A [Bungie API key](https://www.bungie.net/en/Application)

### Running on a VPS

```bash
git clone <repo-url>
cd destiny-lfg-bot

cp .env.example .env
nano .env   # fill in your tokens

docker compose up -d
```

The SQLite database persists in a Docker volume (`bot-data`) across restarts.

### Updating

```bash
git pull
docker compose up -d --build
```

### Local development

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# fill in .env

python src/bot.py
```

## Environment Variables

| Variable | Description |
|---|---|
| `DISCORD_TOKEN` | Bot token from the Discord Developer Portal |
| `BUNGIE_API_KEY` | API key from bungie.net/en/Application |
| `GUILD_ID` | Discord server ID for instant command sync (optional) |

## Project Structure

```
bot.py              — Entry point: DestinyBot class, startup hooks
constants.py        — Activity lists, thresholds, capacity limits
database.py         — SQLite helpers: sessions and player profiles
bungie.py           — Bungie API: manifest fetch, player search, stats
embeds.py           — Discord embed builders
views.py            — UI components: buttons, dropdowns, modal
commands.py         — Slash command definitions
tasks.py            — Background loop: 15-minute activity reminders
find_activities.py  — Diagnostic script to verify Bungie manifest matching
```

## Diagnostics

To verify that all activity names resolve correctly against the Bungie manifest:

```bash
python src/find_activities.py
```
