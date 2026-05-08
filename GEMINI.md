# Destiny LFG Bot - Project Instructions

## ⚔️ LFG Template System
The bot uses a template-based system for creating LFGs. Instead of users typing slash commands directly in public channels, administrators should post pinned "Template" messages.

### Commands:
- `/шаблон тип:[Рейд/Данж] [канал:#channel]`
  - Posts a persistent embed with a button to start the creation flow.
  - Sends a clean message (no interaction header) to the target channel.
- `/шаблон-реєстрації [канал:#channel]`
  - Posts an onboarding message with a "Link Account" button.
  - Automatically assigns the role defined in `REGISTERED_ROLE_ID` upon successful linking.

## 🧹 Automatic Maintenance
- **Cleanup Task**: The bot automatically deletes LFG messages and their discussion threads **3 hours after the scheduled start time**.
- **Frequency**: The cleanup task runs every 30 minutes.

## ⚙️ Configuration (.env)
- `GUILD_ID`: The ID of the main server where roles are assigned.
- `REGISTERED_ROLE_ID`: The ID of the role given to users after they link their Bungie account.
- `OAUTH_PORT`: The port for the OAuth callback server (default: 8080).

## 🚀 Persistent Views
All template buttons are persistent. They are registered in `src/bot.py` within the `setup_hook` method to ensure they work after a bot restart.
