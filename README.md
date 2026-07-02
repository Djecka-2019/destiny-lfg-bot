# Destiny LFG Bot

A Discord bot for organizing Destiny 2 raid, dungeon, and PvP groups (LFG — Looking For Group). Built for Ukrainian-speaking communities.

## Features

- Create LFG posts for raids, dungeons, and PvP via slash commands
- Join/leave buttons with automatic reserve queue and promotion
- Per-session discussion threads with join/leave announcements
- 15-minute DM reminder before activity starts
- Team stats: completion counts and Sherpa/newbie tags for each member
- Player profiles linked to Bungie accounts via OAuth — full raid/dungeon history
- Registered role assignment gated by configured Bungie clan membership
- Commendation system: give and track post-activity praise
- Automatic Discord role assignment based on Bungie stats (raids, GMs, Trials, PvP rank, Gambit resets)
- Persistent template buttons for channels (admins post once, players click anytime)
- Ping role management for activity notifications
- Activity images fetched from the Bungie manifest at startup

## Slash Commands

### Activity organization

| Command | Description |
|---|---|
| `/lfg-raid` | Create a raid LFG post (6 slots) |
| `/lfg-dungeon` | Create a dungeon LFG post (3 slots) |
| `/lfg-pvp` | Create a PvP LFG post (3 slots) |

### Profile & stats

| Command | Description |
|---|---|
| `/add-account` | Link your Bungie account via OAuth |
| `/register` / `/oauth` | Aliases for `/add-account` |
| `/profile [member] [bungie_name]` | View raid/dungeon completion stats |
| `/commendations [member]` | View received and given commendations |
| `/sync-roles` / `/sync` | Update your Discord roles based on Bungie stats |

### Admin commands

| Command | Description |
|---|---|
| `/template <type> [channel] [title] [description]` | Post a persistent LFG button in a channel |
| `/register-template [channel] [title] [description]` | Post a persistent account-registration button |
| `/sync-registered-role` | Sync the registered role for linked users based on configured clan membership |
| `/ping-roles add <role>` | Allow a role to be pinged in LFG posts |
| `/ping-roles remove <role>` | Remove a role from the ping list |
| `/ping-roles everyone <true\|false>` | Enable or disable @everyone pings |
| `/ping-roles list` | Show configured ping roles |

### General

| Command | Description |
|---|---|
| `/help` | Show bot capabilities and command overview |

## Setup

### Prerequisites

- Docker and Docker Compose
- A [Discord bot token](https://discord.com/developers/applications)
- A [Bungie API key and OAuth app](https://www.bungie.net/en/Application) (Confidential Client type, redirect URL pointing to your server's `/callback` endpoint)

### Running on a VPS

```bash
git clone <repo-url>
cd destiny-lfg-bot

cp .env.example .env
nano .env   # fill in your tokens

docker compose up -d
```

The SQLite database persists in a Docker volume (`bot-data`) across restarts.

The OAuth callback server listens on `OAUTH_PORT` (default `8080`). Set your Bungie app's redirect URL to `http://<your-server-ip>:8080/callback`.

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
| `BUNGIE_CLIENT_ID` | OAuth client ID from the Bungie application page |
| `BUNGIE_CLIENT_SECRET` | OAuth client secret from the Bungie application page |
| `OAUTH_PORT` | Port for the OAuth callback HTTP server (default: `8080`) |
| `GUILD_ID` | Discord server ID for instant command sync and role assignment |
| `REGISTERED_ROLE_ID` | Role ID to assign to linked users only when they are in an allowed Bungie clan |
| `REGISTRATION_LOG_CHANNEL_ID` | Channel ID where new registration embeds are posted |
| `ALLOWED_CLAN_IDS` | Comma-separated Bungie clan IDs allowed to receive `REGISTERED_ROLE_ID` (default: `5150843,4867387`) |
| `ROLE_SYNC_CONFIG` | Path to the role sync JSON config file (default: `role_sync.json`) |

## Role Sync

The registered role is assigned only to linked users who are currently in one of the configured Bungie clans, and is periodically rechecked for linked users only. Admins can run `/sync-registered-role` to force that check.

Stat roles are assigned automatically when a user links their account and on demand via `/sync-roles`. Configure thresholds in `role_sync.json`:

```json
{
  "raids":     { "clears":   [{ "threshold": 100, "role_id": "..." }, ...] },
  "strikes":   { "gms":      [{ "threshold": 50,  "role_id": "..." }, ...] },
  "trials":    { "flawless": [{ "threshold": 10,  "role_id": "..." }, ...] },
  "pvp_comp":  { "ranks":    [{ "threshold": 5500,"role_id": "..." }, ...] },
  "gambit":    { "resets":   [{ "threshold": 5,   "role_id": "..." }, ...] }
}
```

Entries are evaluated highest-threshold-first; only the best matching tier is granted per category.

## Project Structure

```
bot.py              — Entry point: DestinyBot class, startup hooks
constants.py        — Activity lists, thresholds, capacity limits, role sync config loader
database.py         — SQLite helpers: sessions, player profiles, commendations, ping roles
bungie.py           — Bungie API: manifest fetch, player search, stats, OAuth exchange
embeds.py           — Discord embed builders
views.py            — UI components: buttons, dropdowns, modals, template views
commands.py         — Slash command definitions
tasks.py            — Background loop: 15-minute activity reminders
oauth.py            — Bungie OAuth flow: state management, callback HTTP server, role sync on login
role_sync.py        — Discord role assignment logic based on Bungie stats
find_activities.py  — Diagnostic script to verify Bungie manifest matching
```

## Diagnostics

To verify that all activity names resolve correctly against the Bungie manifest:

```bash
python src/find_activities.py
```
