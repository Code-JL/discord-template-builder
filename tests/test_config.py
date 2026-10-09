import base64

import pytest

from src.config import bot_id_from_token, invite_url, load_token
from src.errors import ConfigError
from tests.fakes import BOT_ID, make_token


def test_load_token_strips_whitespace():
    assert load_token({"BOT_TOKEN": "  abc  "}) == "abc"


@pytest.mark.parametrize("env", [{}, {"BOT_TOKEN": ""}, {"BOT_TOKEN": "   "}])
def test_load_token_missing(env):
    with pytest.raises(ConfigError, match="BOT_TOKEN missing"):
        load_token(env)


def test_bot_id_from_token():
    assert bot_id_from_token(make_token()) == BOT_ID


@pytest.mark.parametrize("token", [
    "",
    "abc",
    "not base64!!.x.y",
    base64.urlsafe_b64encode(b"hello").decode() + ".x.y",
])
def test_bad_token_shape(token):
    with pytest.raises(ConfigError, match="doesn't look like a bot token"):
        bot_id_from_token(token)


def test_invite_url():
    assert invite_url(make_token()) == (
        f"https://discord.com/oauth2/authorize?client_id={BOT_ID}&scope=bot&permissions=8")
