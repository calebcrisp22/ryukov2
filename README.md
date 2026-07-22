# DOKKAEBI Discord Bot 🔫💎

A fully-featured Discord account generator bot built with Python and discord.py.

---

## Features

| Command | Description | Permission |
|---|---|---|
| `/generate` | Generate a Free or Premium account from stock | Everyone / Subscribers |
| `/viewstock` | View current stock counts | Everyone |
| `/addstock` | Add accounts to stock (one per line) | Admin |
| `/clearstock` | Clear all stock in a category | Admin |
| `/edit` | Edit a specific stock item by line number | Admin |
| `/viewdropstock` | View drop stock count | Everyone |
| `/adddropstock` | Add accounts to drop stock | Admin |
| `/dropstart` | Start the periodic account drop | Admin |
| `/dropstop` | Stop the running drop | Admin |
| `/dropstatus` | Check drop status and stock | Everyone |
| `/dropcooldown` | View or set drop interval (seconds) | Admin to set |
| `/setcooldown` | Set the generate command cooldown | Admin |
| `/setchannel` | Configure drop / gen-log / vouch / log channels | Admin |
| `/checkchannel` | View all configured channels | Everyone |
| `/setsubscription` | Set a user's subscription tier | Admin |
| `/checksub` | Check a user's subscription | Everyone |
| `/vouch` | Vouch for another user | Everyone |
| `/invites` | Check invite count | Everyone |
| `/createinvite` | Create a server invite link | Everyone |
| `/inviteleaderboard` | Top inviters leaderboard | Everyone |
| `/refreshinvites` | Refresh the invite cache | Admin |
| `/messages` | Check message count | Everyone |

---

## Setup

### 1. Prerequisites

- Python 3.11+
- A Discord bot token from the [Discord Developer Portal](https://discord.com/developers/applications)

### 2. Enable Bot Intents

In the Discord Developer Portal → your app → **Bot**:
- ✅ **Server Members Intent**
- ✅ **Message Content Intent**

### 3. Bot Permissions

When inviting the bot, make sure it has:
- `Manage Channels`
- `Create Instant Invite`
- `Send Messages`
- `Embed Links`
- `Read Message History`
- `View Channels`

Or just grant it **Administrator** for simplicity.

### 4. Install & Run

```bash
# Clone the repo
git clone https://github.com/yourusername/dokkaebi-bot.git
cd dokkaebi-bot

# Install dependencies
pip install -r requirements.txt

# Set your token
cp .env.example .env
# Edit .env and paste your DISCORD_BOT_TOKEN

# Run the bot
python bot.py
```

### 5. Environment Variable

| Variable | Description |
|---|---|
| `DISCORD_BOT_TOKEN` | Your Discord bot token |

---

## Usage Guide

### Adding Stock

```
/addstock category:Premium accounts:user1:pass1
user2:pass2
user3:pass3
```

Each line becomes one account entry.

### Running a Drop

1. `/adddropstock accounts:...` — add accounts to the drop queue
2. `/setchannel channel_type:drop channel:#drops` — set the drop channel
3. `/dropcooldown seconds:30` — set drop interval
4. `/dropstart` — start the drop

### Subscription Tiers

- **Free** — can use `/generate category:Free`
- **Premium** — can use both Free and Premium generate

Set with `/setsubscription user:@User tier:Premium`

---

## Data Storage

All data is stored locally in `dokkaebi.db` (SQLite). No external database required.

---

## License

MIT
