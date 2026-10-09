# Discord Template Builder

Builds a Discord server from a `template.json` made by
[discord-template-export](https://github.com/Code-JL/discord-template-export):
roles, categories, channels, permission overrides and server settings. A bot
you own does the work through Discord's bot API.

Discord can't import template files itself: its official templates only exist
as `discord.new/...` links generated from a live server. This tool rebuilds the
server; afterwards you can generate an official link from it.

## Warning

A build **wipes the target server first**: every channel, and every role below
the bot's role, is deleted. Build into a new, empty server. The tool shows how
much it will delete (the dry run lists every name) and makes you type the
server's name before it changes anything.

## Requirements

- Python 3.13 or 3.14
- A Discord bot you own (free, setup below)
- A new server you own, to build into
- A `template.json` from discord-template-export

## Setup

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows (Git Bash)
source .venv/bin/activate          # macOS/Linux
pip install -r requirements.txt
cp .env.example .env
```

### Create the bot

1. Open <https://discord.com/developers/applications> and click **New Application**.
2. In the **Bot** tab, click **Reset Token** and put the token in `.env` as
   `BOT_TOKEN=...`. Treat it like a password; `.env` is gitignored.
3. No privileged intents are needed.

### Invite it to your new server

1. In Discord, create a server: **+** → **Create My Own**.
2. Run `python -m src.main --invite`, open the link, pick the new server, keep
   **Administrator** ticked and click **Authorize**.
3. Settings → Advanced → **Developer Mode** on; right-click the server →
   **Copy Server ID**.
4. Leave the bot's role where Discord puts it. The builder creates every role
   below it, in the template's order. If you ever kick and re-invite the bot,
   drag its role back to the top of the role list before building.

## Usage

```bash
python -m src.main --template templates/my-server.json --guild <server id> --dry-run
python -m src.main --template templates/my-server.json --guild <server id>
```

- The **dry run** lists every channel and role it would delete and create, and
  every adjustment, without changing anything. Check it for channels you don't
  want (bot counters such as `Members: 142`, temporary voice rooms) and delete
  them from the template file first. If you delete the AFK or system channel,
  or a whole category, also remove the references to it (the error message
  names them).
- The **real run** asks you to type the server's name. Run it in a normal
  terminal; it refuses to run when it can't ask.
- It prints a line per step. A server with ~120 channels and ~70 roles takes
  about 2 minutes, because Discord rate-limits channel and role creation.
- If it stops partway, re-run it: it wipes the partial build and starts again.

Put templates in `templates/` (gitignored) so real server data never gets committed.

## ID map

Every build creates new IDs for every role and channel. If your other bots
store channel or role IDs in their config, a successful build writes
`<template name>.id-map.json` next to the template:

```json
{
  "guild":    {"old": "...", "new": "..."},
  "roles":    [{"name": "Moderators", "old": "...", "new": "..."}],
  "channels": [{"name": "announcements", "type": 0, "old": "...", "new": "..."}],
  "by_old_id": {"<old id>": "<new id>"}
}
```

Use `by_old_id` to find-and-replace old IDs in a bot's config. Apply `by_old_id`
to a copy of your bot's original config each time — after a rebuild the new IDs
change again. Templates
exported before discord-template-export recorded `source_ids` get no map;
re-export them.

## What gets adjusted

Everything below is listed in the dry run and in the final report.

- **Voice bitrate** is capped to what the server's boost level allows
  (96 kbps unboosted, 128 / 256 / 384 kbps at levels 1 / 2 / 3).
- **Role icons**: custom images are always dropped (the template doesn't
  contain them); emoji icons are kept only if the server has role icons
  (boost level 2).
- **Custom emoji** in forum tags and default reactions are removed; they belong
  to the original server. Unicode emoji are kept.
- **Announcement and stage channels** become text and voice channels unless
  the server has Community enabled.
- **Forum channels** work on any server; if Discord ever refuses one, it's
  created as a text channel instead.
- **Description and language** are only set on Community servers.
- **Per-member permission overrides** are skipped (the template doesn't carry them).

Never deleted: `@everyone` (its permissions are replaced), roles managed by bots
or boosts, roles above the bot's role, and the rules/updates channels of a
Community server.

## After the build

- Re-invite your bots (MEE6 and the like); they aren't part of a template.
- Server Settings → **Server Template** → **Generate** gives you an official
  `discord.new/...` link for more copies.

Not included: messages, members, emojis, stickers, server icon and banner.

## Tests

```bash
pytest
```

The tests use fake Discord responses and never contact Discord.

## Project layout

```
src/
  main.py       commands, dry run, confirmation, error messages
  config.py     BOT_TOKEN from .env; bot id and invite link from the token
  template.py   load and check template.json
  plan.py       what to delete, create and adjust (no network)
  idmap.py      old ID → new ID map written after a build
  builder.py    reads the server, runs the plan, maps old ids to new ones
  api.py        Discord bot API client with rate-limit handling
  errors.py     error types
tests/          pytest suite + sample template
```

## License

[MIT](LICENSE)
