"""Read the target server, then run a Plan: wipe, then create, mapping template ids to new ids."""
from collections import Counter
from dataclasses import dataclass

from src.errors import ApiError, NotAdministrator, NotFound
from src.plan import ADMINISTRATOR, Target, text_fallback


@dataclass
class BuildResult:
    done: Counter          # e.g. {"channels created": 9, ...}, in the order things happened
    adjustments: list      # changes decided during the build (forum refused -> text)
    role_ids: dict         # template role id -> new role id (0 -> the guild id)
    channel_ids: dict      # template channel id -> new channel id


def read_target(api, guild_id):
    """Fetch what a build needs to know about the server; require Administrator."""
    bot = api.get("/users/@me")
    guild = api.get(f"/guilds/{guild_id}")
    channels = api.get(f"/guilds/{guild_id}/channels")
    member = api.get(f"/guilds/{guild_id}/members/{bot['id']}")
    roles = {role["id"]: role for role in guild["roles"]}
    held = [role_id for role_id in [guild_id, *member.get("roles", [])] if role_id in roles]
    if not any(int(roles[role_id].get("permissions", "0")) & ADMINISTRATOR for role_id in held):
        raise NotAdministrator(guild_id)
    mine = [roles[role_id] for role_id in member.get("roles", []) if role_id in roles]
    top = min(mine, key=lambda r: (-r.get("position", 0), int(r["id"])), default=None)
    return Target(guild_id=guild_id, name=guild["name"], features=frozenset(guild.get("features", [])),
                  premium_tier=guild.get("premium_tier", 0), roles=guild["roles"], channels=channels,
                  bot_top_position=top.get("position", 0) if top else 0,
                  bot_top_role_id=top["id"] if top else None, rules_channel_id=guild.get("rules_channel_id"),
                  public_updates_channel_id=guild.get("public_updates_channel_id"))


def build(api, target, plan, out=print, on_created=None):
    return Builder(api, target, plan, out, on_created).run()


class Builder:
    def __init__(self, api, target, plan, out=print, on_created=None):
        self.api = api
        self.on_created = on_created
        self.plan = plan
        self.out = out
        self.guild = target.guild_id
        self.role_ids = {0: target.guild_id}   # template role 0 is @everyone, whose id is the guild id
        self.channel_ids = {}
        self.done = Counter()
        self.adjustments = []

    def run(self):
        try:
            self._delete_channels()
            self._delete_roles()
            self._update_everyone()
            self._create_roles()
            self._create_channels()
            if self.on_created:
                self.on_created(self._result())
            self._update_settings()
        except BaseException:   # Ctrl-C too: say where the build stopped
            self.out("Stopped. Done so far: " + (", ".join(f"{n} {what}" for what, n in self.done.items())
                                                 or "nothing"))
            self.out("Re-run to wipe and rebuild.")
            raise
        return self._result()

    def _result(self):
        return BuildResult(self.done, self.adjustments, self.role_ids, self.channel_ids)

    def _progress(self, section, i, total, name, already_gone=False):
        self.out(f'[{section} {i}/{total}] "{name}"' + (" (already gone)" if already_gone else ""))

    def _delete(self, path):
        """Delete; True if it was already gone (404), which counts as deleted."""
        try:
            self.api.delete(path)
        except NotFound:
            return True
        return False

    def _delete_channels(self):
        channels = self.plan.delete_channels
        for i, channel in enumerate(channels, 1):
            gone = self._delete(f"/channels/{channel['id']}")
            self._progress("delete channels", i, len(channels), channel["name"], gone)
            self.done["channels deleted"] += 1

    def _delete_roles(self):
        roles = self.plan.delete_roles
        for i, role in enumerate(roles, 1):
            gone = self._delete(f"/guilds/{self.guild}/roles/{role['id']}")
            self._progress("delete roles", i, len(roles), role["name"], gone)
            self.done["roles deleted"] += 1

    def _update_everyone(self):
        if self.plan.everyone_permissions is None:
            return
        self.api.patch(f"/guilds/{self.guild}/roles/{self.guild}",
                       {"permissions": self.plan.everyone_permissions})
        self.out("[roles] @everyone permissions set")

    def _create_roles(self):
        steps = self.plan.create_roles
        for i, step in enumerate(steps, 1):
            created = self.api.post(f"/guilds/{self.guild}/roles", step.payload)
            self.role_ids[step.template_id] = created["id"]
            self._progress("create roles", i, len(steps), step.payload["name"])
            self.done["roles created"] += 1

    def _create_channels(self):
        steps = self.plan.create_channels
        for i, step in enumerate(steps, 1):
            payload = self._resolve(step.payload)
            try:
                created = self.api.post(f"/guilds/{self.guild}/channels", payload)
            except ApiError as e:
                if not (step.can_fall_back and e.status == 400):
                    raise
                created = self.api.post(f"/guilds/{self.guild}/channels", text_fallback(payload))
                self.adjustments.append(
                    f'channel "{payload["name"]}": Discord refused type {payload["type"]} ({e.message}); '
                    'created as text')
            self.channel_ids[step.template_id] = created["id"]
            self._progress("create channels", i, len(steps), payload["name"])
            self.done["channels created"] += 1

    def _resolve(self, payload):
        """Swap template ids for the new real ids created earlier in this build."""
        resolved = dict(payload)
        if "parent_id" in resolved:
            resolved["parent_id"] = self.channel_ids[resolved["parent_id"]]
        resolved["permission_overwrites"] = [dict(o, id=self.role_ids[o["id"]])
                                             for o in payload.get("permission_overwrites", [])]
        return resolved

    def _update_settings(self):
        settings = dict(self.plan.guild_settings)
        for key in ("afk_channel_id", "system_channel_id"):
            if key in settings:
                settings[key] = self.channel_ids[settings[key]]
        if settings:
            self.api.patch(f"/guilds/{self.guild}", settings)
            self.out("[settings] server settings updated")
