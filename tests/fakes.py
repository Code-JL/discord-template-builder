"""Shared test helpers: a fake bot token, a fake server, and a recording FakeApi."""
import base64
import copy

BOT_ID = "123456789012345678"
GUILD_ID = "900"


def make_token(bot_id=BOT_ID):
    first = base64.urlsafe_b64encode(bot_id.encode()).decode().rstrip("=")
    return f"{first}.GhIjKl.fake-secret-part-for-tests"


def server_state(**guild_overrides):
    """GET responses for a fresh test server where the bot (role 901) has Administrator."""
    guild = {
        "id": GUILD_ID, "name": "Copy", "features": [], "premium_tier": 0,
        "rules_channel_id": None, "public_updates_channel_id": None,
        "roles": [
            {"id": GUILD_ID, "name": "@everyone", "position": 0, "permissions": "0", "managed": False},
            {"id": "901", "name": "Builder", "position": 2, "permissions": "8", "managed": True},
            {"id": "902", "name": "Old", "position": 1, "permissions": "0", "managed": False},
            {"id": "903", "name": "Admin", "position": 3, "permissions": "8", "managed": False},
        ],
    }
    guild.update(guild_overrides)
    return {
        "/users/@me": {"id": BOT_ID},
        f"/guilds/{GUILD_ID}": guild,
        f"/guilds/{GUILD_ID}/channels": [
            {"id": "910", "type": 4, "name": "Text Channels", "parent_id": None},
            {"id": "911", "type": 0, "name": "general", "parent_id": "910"},
            {"id": "912", "type": 4, "name": "Voice Channels", "parent_id": None},
            {"id": "913", "type": 2, "name": "General", "parent_id": "912"},
        ],
        f"/guilds/{GUILD_ID}/members/{BOT_ID}": {"roles": ["901"]},
    }


def make_target(**overrides):
    """A plan.Target matching server_state() (bot's highest role position is 2)."""
    from src.plan import Target

    state = server_state()
    values = dict(
        guild_id=GUILD_ID, name="Copy", features=frozenset(), premium_tier=0,
        roles=state[f"/guilds/{GUILD_ID}"]["roles"],
        channels=state[f"/guilds/{GUILD_ID}/channels"], bot_top_position=2,
    )
    values.update(overrides)
    return Target(**values)


class FakeApi:
    """Records every call. GETs answer from a dict; POSTs return ids new1, new2, ... in order."""

    def __init__(self, gets):
        self.gets = gets
        self.calls = []
        self.created = 0
        self.failures = []

    def fail_once(self, predicate, error):
        """The first call where predicate(method, path, body) is true raises error."""
        self.failures.append((predicate, error))

    def writes(self):
        return [call for call in self.calls if call[0] != "GET"]

    def _maybe_fail(self, method, path, body):
        for i, (predicate, error) in enumerate(self.failures):
            if predicate(method, path, body):
                del self.failures[i]
                raise error

    def get(self, path):
        self.calls.append(("GET", path, None))
        self._maybe_fail("GET", path, None)
        return copy.deepcopy(self.gets[path])

    def post(self, path, body):
        self.calls.append(("POST", path, copy.deepcopy(body)))
        self._maybe_fail("POST", path, body)
        self.created += 1
        return {"id": f"new{self.created}"}

    def patch(self, path, body):
        self.calls.append(("PATCH", path, copy.deepcopy(body)))
        self._maybe_fail("PATCH", path, body)
        return {}

    def delete(self, path):
        self.calls.append(("DELETE", path, None))
        self._maybe_fail("DELETE", path, None)
        return None
