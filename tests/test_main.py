import io
import json
import shutil
import sys
from pathlib import Path

import pytest

import src.main as cli
from src.errors import (ApiError, Forbidden, InvalidToken, NetworkError, NotAdministrator, NotFound,
                        RateLimited)
from tests.fakes import BOT_ID, GUILD_ID, FakeApi, make_token, server_state

FIXTURE = Path(__file__).parent / "fixtures" / "template.json"
INVITE = f"https://discord.com/oauth2/authorize?client_id={BOT_ID}&scope=bot&permissions=8"


class FakeStdin:
    def __init__(self, tty):
        self.tty = tty

    def isatty(self):
        return self.tty


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setenv("BOT_TOKEN", make_token())
    template = tmp_path / "template.json"
    shutil.copy(FIXTURE, template)
    api = FakeApi(server_state())
    monkeypatch.setattr(cli, "open_api", lambda token: api)
    return api, template


def _run(template, *extra, typed="Copy", tty=True):
    return cli.main(["--template", str(template), "--guild", GUILD_ID, *extra],
                    input_fn=lambda prompt: typed, stdin=FakeStdin(tty))


def test_invite_prints_link(env, capsys):
    assert cli.main(["--invite"]) == 0
    assert capsys.readouterr().out.strip() == INVITE


def test_dry_run_changes_nothing(env, capsys):
    api, template = env
    assert _run(template, "--dry-run") == 0
    out = capsys.readouterr().out
    assert api.writes() == []
    assert not template.with_name("template.id-map.json").exists()
    assert "Will delete: 4 channels, 1 roles" in out
    assert '+ forum "help" in "Info"' in out
    assert "Dry run — nothing was changed." in out


def test_dry_run_survives_non_utf8_stdout(env, monkeypatch):
    api, template = env
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp1252"))
    assert _run(template, "--dry-run") == 0
    sys.stdout.flush()
    assert '+ text "?-welcome"' in raw.getvalue().decode("cp1252")


def test_build_after_typing_the_name(env, capsys):
    api, template = env
    assert _run(template) == 0
    assert len(api.writes()) == 19
    out = capsys.readouterr().out
    assert "Done: 4 channels deleted, 1 roles deleted, 2 roles created, 9 channels created" in out
    id_map_file = template.with_name("template.id-map.json")
    assert f"ID map written to {id_map_file}" in out
    id_map = json.loads(id_map_file.read_text(encoding="utf-8"))
    assert id_map["by_old_id"]["305"] == "new11"   # the AFK channel
    assert id_map["guild"] == {"old": "100", "new": GUILD_ID}


def test_build_without_source_ids_writes_no_map(env, capsys):
    api, template = env
    data = json.loads(template.read_text(encoding="utf-8"))
    del data["source_ids"]
    template.write_text(json.dumps(data), encoding="utf-8")
    assert _run(template) == 0
    assert "No ID map: this template has no source_ids" in capsys.readouterr().out
    assert not template.with_name("template.id-map.json").exists()


def test_name_mismatch_changes_nothing(env, capsys):
    api, template = env
    assert _run(template, typed="copy") == 1
    assert api.writes() == []
    assert "Server name didn't match — nothing was changed" in capsys.readouterr().err


def test_refuses_without_a_terminal(env, capsys):
    api, template = env
    assert _run(template, tty=False) == 1
    assert api.writes() == []
    assert "Refusing to wipe without an interactive confirmation" in capsys.readouterr().err


def test_bad_template_makes_no_requests(env, capsys):
    api, template = env
    template.write_text("{}", encoding="utf-8")
    assert _run(template) == 1
    assert api.calls == []
    assert "Template error:" in capsys.readouterr().err


def test_missing_token(env, monkeypatch, capsys):
    monkeypatch.delenv("BOT_TOKEN")
    assert cli.main(["--invite"]) == 1
    assert "Config error: BOT_TOKEN missing" in capsys.readouterr().err


@pytest.mark.parametrize("error, message", [
    (InvalidToken(), "BOT_TOKEN is invalid — check .env"),
    (NotFound(404, 10004, "Unknown Guild"), f"The bot isn't in server {GUILD_ID} — invite it: {INVITE}"),
    (Forbidden(403, 50001, "Missing Access"), f"The bot isn't in server {GUILD_ID} — invite it: {INVITE}"),
    (Forbidden(403, 50013, "Missing Permissions"),
     f"The bot needs Administrator in server {GUILD_ID} — re-invite it: {INVITE}"),
    (NotAdministrator(GUILD_ID), f"The bot needs Administrator in server {GUILD_ID} — re-invite it: {INVITE}"),
    (RateLimited("GET /users/@me"), "Rate limited by Discord too many times — wait and re-run"),
    (NetworkError("GET /users/@me: ConnectTimeout"), "Network error talking to Discord — re-run"),
    (ApiError(400, 50035, "Invalid Form Body"), "Discord API error 400 (50035): Invalid Form Body"),
])
def test_errors_map_to_messages(env, capsys, error, message):
    api, template = env
    api.fail_once(lambda method, path, body: True, error)
    assert _run(template, "--dry-run") == 1
    assert message in capsys.readouterr().err


def test_guild_must_be_numeric(capsys):
    with pytest.raises(SystemExit) as info:
        cli.parse_args(["--template", "t.json", "--guild", "https://discord.com/channels/1/2"])
    assert info.value.code == 2
    assert "Copy Server ID" in capsys.readouterr().err


def test_template_needs_guild():
    with pytest.raises(SystemExit) as info:
        cli.parse_args(["--template", "t.json"])
    assert info.value.code == 2
