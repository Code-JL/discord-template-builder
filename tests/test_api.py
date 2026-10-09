import json

import pytest
import requests

from src.api import API_BASE, USER_AGENT, DiscordApi
from src.errors import ApiError, Forbidden, InvalidToken, NetworkError, NotFound, RateLimited

TOKEN = "secret.token.value"


class FakeResponse:
    def __init__(self, status, body=None, headers=None, text=None):
        self.status_code = status
        self.headers = headers or {}
        self.text = text if text is not None else ("" if body is None else json.dumps(body))
        self.content = self.text.encode()

    def json(self):
        return json.loads(self.text)


class FakeSession:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make(*outcomes):
    session = FakeSession(*outcomes)
    sleeps = []
    return DiscordApi(TOKEN, session=session, sleep=sleeps.append), session, sleeps


def test_get_sends_bot_auth_and_parses_json():
    api, session, sleeps = make(FakeResponse(200, {"id": "1"}))
    assert api.get("/users/@me") == {"id": "1"}
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("GET", API_BASE + "/users/@me")
    assert kwargs["headers"] == {"Authorization": f"Bot {TOKEN}", "User-Agent": USER_AGENT}
    assert kwargs["json"] is None
    assert kwargs["timeout"] == 30
    assert sleeps == []


def test_writes_carry_audit_reason_and_body():
    api, session, _ = make(FakeResponse(201, {"id": "5"}))
    assert api.post("/guilds/1/roles", {"name": "x"}) == {"id": "5"}
    _, _, kwargs = session.calls[0]
    assert kwargs["headers"]["X-Audit-Log-Reason"] == "discord-template-builder"
    assert kwargs["json"] == {"name": "x"}


def test_no_content_returns_none():
    api, _, _ = make(FakeResponse(204))
    assert api.delete("/channels/1") is None


def test_waits_when_bucket_is_empty():
    headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset-After": "1.5"}
    api, _, sleeps = make(FakeResponse(200, {}, headers=headers))
    api.get("/x")
    assert sleeps == [1.5]


@pytest.mark.parametrize("body", [{"retry_after": 0.25, "global": False}, {"retry_after": 0.25, "global": True}])
def test_429_waits_and_retries(body):
    api, session, sleeps = make(FakeResponse(429, body), FakeResponse(200, {"ok": True}))
    assert api.get("/x") == {"ok": True}
    assert sleeps == [0.25]
    assert len(session.calls) == 2


def test_gives_up_after_five_429s():
    api, session, sleeps = make(*[FakeResponse(429, {"retry_after": 1}) for _ in range(5)])
    with pytest.raises(RateLimited):
        api.get("/x")
    assert len(session.calls) == 5
    assert sleeps == [1.0] * 4


def test_server_error_retried_once():
    api, _, sleeps = make(FakeResponse(502, text="bad gateway"), FakeResponse(200, {}))
    assert api.get("/x") == {}
    assert sleeps == [2.0]


def test_server_error_twice_raises():
    api, _, _ = make(FakeResponse(500, text="x"), FakeResponse(500, text="x"))
    with pytest.raises(ApiError) as info:
        api.get("/x")
    assert info.value.status == 500


def test_network_error_retried_once():
    api, _, sleeps = make(requests.Timeout("slow"), FakeResponse(200, {}))
    assert api.get("/x") == {}
    assert sleeps == [2.0]


def test_network_error_twice_raises():
    api, _, _ = make(requests.ConnectionError("down"), requests.ConnectionError("down"))
    with pytest.raises(NetworkError):
        api.get("/x")


@pytest.mark.parametrize("status, error_type", [
    (401, InvalidToken), (403, Forbidden), (404, NotFound), (400, ApiError)])
def test_status_errors_never_contain_the_token(status, error_type):
    api, _, _ = make(FakeResponse(status, {"code": 50013, "message": "Missing Permissions"}))
    with pytest.raises(error_type) as info:
        api.get("/x")
    assert TOKEN not in str(info.value)


def test_forbidden_carries_discord_code():
    api, _, _ = make(FakeResponse(403, {"code": 50001, "message": "Missing Access"}))
    with pytest.raises(Forbidden) as info:
        api.get("/guilds/1")
    assert (info.value.code, info.value.message) == (50001, "Missing Access")


def test_field_errors_are_summarised_and_truncated():
    body = {"code": 50035, "message": "Invalid Form Body",
            "errors": {"name": {"_errors": [{"code": "BASE_TYPE_REQUIRED", "message": "x" * 500}]}}}
    api, _, _ = make(FakeResponse(400, body))
    with pytest.raises(ApiError) as info:
        api.post("/x", {})
    assert info.value.code == 50035
    assert info.value.message.startswith("Invalid Form Body {")
    assert len(info.value.message) <= 300


def test_non_json_error_body():
    api, _, _ = make(FakeResponse(400, text="<html>nope</html>"))
    with pytest.raises(ApiError) as info:
        api.get("/x")
    assert (info.value.code, info.value.message) == (0, "<html>nope</html>")
