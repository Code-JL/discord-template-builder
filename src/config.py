import base64
import os
import re

from src.errors import ConfigError

INVITE_URL = "https://discord.com/oauth2/authorize?client_id={bot_id}&scope=bot&permissions=8"


def load_token(env=None):
    env = os.environ if env is None else env
    token = (env.get("BOT_TOKEN") or "").strip()
    if not token:
        raise ConfigError("BOT_TOKEN missing — add it to .env (see .env.example)")
    return token


def bot_id_from_token(token):
    """A bot token's first segment is the bot's user id, base64url-encoded without padding."""
    first = token.split(".")[0]
    try:
        decoded = base64.urlsafe_b64decode(first + "=" * (-len(first) % 4)).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        decoded = ""
    if not re.fullmatch(r"[0-9]{15,21}", decoded):
        raise ConfigError("BOT_TOKEN doesn't look like a bot token")
    return decoded


def invite_url(token):
    return INVITE_URL.format(bot_id=bot_id_from_token(token))
