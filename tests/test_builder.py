from pathlib import Path

import pytest

from src.builder import build, read_target
from src.errors import ApiError, Forbidden, NotAdministrator
from src.plan import build_plan
from src.template import load_template
from tests.fakes import BOT_ID, GUILD_ID, FakeApi, server_state

FIXTURE = Path(__file__).parent / "fixtures" / "template.json"


def _setup():
    api = FakeApi(server_state())
    target = read_target(api, GUILD_ID)
    plan = build_plan(load_template(FIXTURE).source, target)
    api.calls.clear()
    return api, target, plan


def _quiet(line):
    pass


def test_read_target():
    api = FakeApi(server_state())
    target = read_target(api, GUILD_ID)
    assert (target.name, target.bot_top_position, target.premium_tier) == ("Copy", 2, 0)
    assert target.bot_top_role_id == "901"
    assert [c["id"] for c in target.channels] == ["910", "911", "912", "913"]
    assert api.calls == [("GET", "/users/@me", None), ("GET", f"/guilds/{GUILD_ID}", None),
                         ("GET", f"/guilds/{GUILD_ID}/channels", None),
                         ("GET", f"/guilds/{GUILD_ID}/members/{BOT_ID}", None)]


def test_read_target_requires_administrator():
    state = server_state()
    state[f"/guilds/{GUILD_ID}"]["roles"][1]["permissions"] = "0"   # the bot's own role
    with pytest.raises(NotAdministrator):
        read_target(FakeApi(state), GUILD_ID)


def test_build_runs_steps_in_order_and_wires_new_ids():
    api, target, plan = _setup()
    lines = []
    result = build(api, target, plan, out=lines.append)
    g = GUILD_ID
    assert [(method, path) for method, path, _ in api.calls] == [
        ("DELETE", "/channels/911"), ("DELETE", "/channels/913"),
        ("DELETE", "/channels/910"), ("DELETE", "/channels/912"),
        ("DELETE", f"/guilds/{g}/roles/902"),
        ("PATCH", f"/guilds/{g}/roles/{g}"),
        ("POST", f"/guilds/{g}/roles"), ("POST", f"/guilds/{g}/roles"),
        *[("POST", f"/guilds/{g}/channels")] * 9,
        ("PATCH", f"/guilds/{g}"),
    ]
    assert api.calls[5][2] == {"permissions": "1071698660929"}
    assert ("PATCH", f"/guilds/{g}/roles") not in [(m, p) for m, p, _ in api.calls]
    posts = {body["name"]: body for method, path, body in api.calls
             if method == "POST" and path.endswith("/channels")}
    assert posts["Info"]["permission_overwrites"] == [{"id": g, "type": 0, "allow": "0", "deny": "2048"}]
    assert posts["👋-welcome"]["parent_id"] == "new3"
    assert posts["👋-welcome"]["permission_overwrites"] == [{"id": "new1", "type": 0, "allow": "2048", "deny": "0"}]
    assert posts["AFK"]["parent_id"] == "new4"
    assert posts["help"]["permission_overwrites"] == [
        {"id": g, "type": 0, "allow": "0", "deny": "2048"},
        {"id": "new2", "type": 0, "allow": "2048", "deny": "0"}]
    settings = api.calls[-1][2]
    assert (settings["afk_channel_id"], settings["system_channel_id"]) == ("new11", "new8")
    assert dict(result.done) == {"channels deleted": 4, "roles deleted": 1, "roles created": 2,
                                 "channels created": 9}
    assert result.adjustments == []
    assert result.role_ids == {0: g, 1: "new2", 2: "new1"}
    assert result.channel_ids == {3: "new3", 7: "new4", 9: "new5", 1: "new6", 2: "new7",
                                  4: "new8", 5: "new9", 6: "new10", 8: "new11"}
    assert '[create roles 2/2] "Member"' in lines
    assert '[create channels 9/9] "AFK"' in lines


def test_forum_refused_is_created_as_text():
    api, target, plan = _setup()
    api.fail_once(lambda method, path, body: method == "POST" and body.get("type") == 15,
                  ApiError(400, 50024, "Cannot execute action on this channel type"))
    result = build(api, target, plan, out=_quiet)
    attempts = [body for method, path, body in api.calls if method == "POST" and body.get("name") == "help"]
    assert [body["type"] for body in attempts] == [15, 0]
    assert "available_tags" not in attempts[1]
    assert result.adjustments == ['channel "help": Discord refused type 15; created as text']
    assert result.done["channels created"] == 9
    assert result.channel_ids[6] == "new10"


def test_forum_not_retried_for_other_errors():
    api, target, plan = _setup()
    api.fail_once(lambda method, path, body: method == "POST" and body.get("type") == 15,
                  Forbidden(403, 50013, "Missing Permissions"))
    with pytest.raises(Forbidden):
        build(api, target, plan, out=_quiet)


def test_unexpected_error_stops_with_progress_summary():
    api, target, plan = _setup()
    api.fail_once(lambda method, path, body: method == "POST" and body.get("name") == "rules",
                  ApiError(400, 50035, "Invalid Form Body"))
    lines = []
    with pytest.raises(ApiError):
        build(api, target, plan, out=lines.append)
    assert lines[-2] == ("Stopped. Done so far: 4 channels deleted, 1 roles deleted, "
                         "2 roles created, 6 channels created")
    assert lines[-1] == "Re-run to wipe and rebuild."
