# Discord Economy + Shop Bot (Python, SQLite, discord.py)

## Features
- Economy configurable (messages, voice minutes, invites)
- Shop: view/buy + admin add/remove/setprice
- Logs channel for purchases and invites
- SQLite storage, no external DB

## Local run
1. Python 3.10+
2. `pip install -r requirements.txt`
3. Set `DISCORD_TOKEN` env var (Bot token)
4. Enable intents in Discord Developer Portal:
   - SERVER MEMBERS INTENT
   - MESSAGE CONTENT INTENT
   - Presence not required
5. `python bot.py`

## Railway deploy
1. Create new project from GitHub repo
2. Add environment variable:
   - `DISCORD_TOKEN` = your bot token
3. Set Start Command: `python bot.py`
4. Deploy

## Permissions needed
- Manage Server Invites (to read invite uses for rewards)
- Read Messages / Message Content (for message rewards)
- Send Messages / Embed Links
- View Channels
- Connect/Read Voice States (for voice-minute tracking)

## Slash commands
- `/balance` — show your balance
- `/shop` — browse items
- `/buy item:<name>` — purchase item

Admin-only:
- `/shop_add name:<str> price:<int> description:<str?>`
- `/shop_remove name:<str>`
- `/shop_setprice name:<str> price:<int>`
- `/config_message threshold:<int> reward:<int>`
- `/config_voice reward_per_min:<int>`
- `/config_invite reward:<int>`
- `/logs_set channel:<#channel>`

## Notes
- Voice minutes are credited every minute while connected, and once on disconnect.
- Message rewards trigger when a user reaches the configured threshold; counter resets after reward.
- Invite rewards use live invite usage comparison; if bot cannot view invites, no reward is granted.
