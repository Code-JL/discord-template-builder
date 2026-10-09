"""Pure planning: a template plus the target server's state -> the steps a build runs."""
import copy
from dataclasses import dataclass, field

CATEGORY, TEXT, VOICE, ANNOUNCEMENT, STAGE, FORUM, MEDIA = 4, 0, 2, 5, 13, 15, 16
ADMINISTRATOR = 0x8
BITRATE_MAX = {0: 96000, 1: 128000, 2: 256000, 3: 384000}
MIN_BITRATE = 8000
MAX_VOICE_USERS = 99
MAX_TAGS = 20
MAX_TEXT_TOPIC = 1024
COMMUNITY_TYPES = {ANNOUNCEMENT: TEXT, STAGE: VOICE}
FORUM_ONLY_FIELDS = ("available_tags", "default_reaction_emoji", "default_sort_order", "default_forum_layout")
OPTIONAL_CHANNEL_FIELDS = ("topic", "nsfw", "rate_limit_per_user", "bitrate", "user_limit",
                           "default_auto_archive_duration", "available_tags", "default_reaction_emoji",
                           "default_thread_rate_limit_per_user", "default_sort_order", "default_forum_layout")
GUILD_SETTINGS = ("verification_level", "default_message_notifications", "explicit_content_filter",
                  "afk_timeout", "system_channel_flags")
COMMUNITY_SETTINGS = ("description", "preferred_locale")


@dataclass
class Target:
    guild_id: str
    name: str
    features: frozenset
    premium_tier: int
    roles: list
    channels: list
    bot_top_position: int
    rules_channel_id: str | None = None
    public_updates_channel_id: str | None = None
    bot_top_role_id: str | None = None


@dataclass
class RoleStep:
    template_id: int
    payload: dict


@dataclass
class ChannelStep:
    template_id: int
    payload: dict          # parent_id and overwrite ids are still template ids
    can_fall_back: bool    # forum/media: retry as text if Discord refuses the type


@dataclass
class Plan:
    delete_channels: list = field(default_factory=list)
    delete_roles: list = field(default_factory=list)
    protected: list = field(default_factory=list)
    everyone_permissions: str | None = None
    create_roles: list = field(default_factory=list)
    create_channels: list = field(default_factory=list)
    guild_settings: dict = field(default_factory=dict)   # afk/system channel ids are template ids
    adjustments: list = field(default_factory=list)


def build_plan(source, target):
    plan = Plan()
    _plan_wipe(target, plan)
    _plan_roles(source, target, plan)
    _plan_channels(source, target, plan)
    _plan_settings(source, target, plan)
    return plan


def text_fallback(payload):
    """The payload to retry with when Discord refuses a forum or media channel."""
    fallback = {key: value for key, value in payload.items() if key not in FORUM_ONLY_FIELDS}
    fallback["type"] = TEXT
    if isinstance(fallback.get("topic"), str):
        fallback["topic"] = fallback["topic"][:MAX_TEXT_TOPIC]   # forum topics may be longer than text ones
    return fallback


def _below_bot(role, target):
    """True if the role ranks under the bot's top role (equal positions: the older role is higher)."""
    position = role.get("position", 0)
    if position != target.bot_top_position:
        return position < target.bot_top_position
    return target.bot_top_role_id is not None and int(role["id"]) > int(target.bot_top_role_id)


def _plan_wipe(target, plan):
    for role in target.roles:
        if role["id"] == target.guild_id:
            continue
        if role.get("managed"):
            plan.protected.append(f'role "{role["name"]}" (managed by an integration)')
        elif not _below_bot(role, target):
            plan.protected.append(f'role "{role["name"]}" (not below the bot\'s role)')
        else:
            plan.delete_roles.append(role)
    required = set()
    if "COMMUNITY" in target.features:
        required = {target.rules_channel_id, target.public_updates_channel_id} - {None}
    for channel in target.channels:
        if channel["id"] in required:
            plan.protected.append(f'channel "{channel["name"]}" (required by Community)')
    doomed = [c for c in target.channels if c["id"] not in required]
    plan.delete_channels = ([c for c in doomed if c.get("type") != CATEGORY]
                            + [c for c in doomed if c.get("type") == CATEGORY])


def _plan_roles(source, target, plan):
    has_icons = "ROLE_ICONS" in target.features
    for role in source["roles"]:
        if role["id"] == 0:
            plan.everyone_permissions = role["permissions"]
            continue
        payload = {"name": role["name"], "permissions": role["permissions"],
                   "color": role.get("color") or 0, "hoist": bool(role.get("hoist")),
                   "mentionable": bool(role.get("mentionable"))}
        if role.get("icon"):
            plan.adjustments.append(f'role "{role["name"]}": custom icon dropped (the image isn\'t in the template)')
        if role.get("unicode_emoji"):
            if has_icons:
                payload["unicode_emoji"] = role["unicode_emoji"]
            else:
                plan.adjustments.append(f'role "{role["name"]}": emoji icon dropped (server has no role icons)')
        plan.create_roles.append(RoleStep(role["id"], payload))
    # New roles all land at position 1 and Discord ranks equal positions by age (older is higher), so
    # creating them top to bottom sets the final order without a reorder call, which a bot may not make.
    plan.create_roles.reverse()


def _plan_channels(source, target, plan):
    channels = source["channels"]
    ordered = ([c for c in channels if c["type"] == CATEGORY]
               + [c for c in channels if c["type"] != CATEGORY])
    for channel in ordered:
        plan.create_channels.append(_channel_step(channel, target, plan.adjustments))


def _channel_step(channel, target, adjustments):
    name, kind = channel["name"], channel["type"]
    payload = {"name": name, "type": kind, "position": channel.get("position") or 0}
    if channel.get("parent_id") is not None:
        payload["parent_id"] = channel["parent_id"]
    overwrites = channel.get("permission_overwrites") or []
    payload["permission_overwrites"] = [
        {"id": o["id"], "type": 0, "allow": o.get("allow", "0"), "deny": o.get("deny", "0")}
        for o in overwrites if o.get("type", 0) == 0]
    skipped = len(overwrites) - len(payload["permission_overwrites"])
    if skipped:
        adjustments.append(f'channel "{name}": {skipped} member permission overwrite(s) skipped')
    for key in OPTIONAL_CHANNEL_FIELDS:
        if channel.get(key) is not None:
            payload[key] = copy.deepcopy(channel[key])

    if kind in COMMUNITY_TYPES and "COMMUNITY" not in target.features:
        payload["type"] = COMMUNITY_TYPES[kind]
        adjustments.append(f'channel "{name}": type {kind} needs Community; created as type {payload["type"]}')
    if payload["type"] == VOICE and payload.get("user_limit", 0) > MAX_VOICE_USERS:
        adjustments.append(f'channel "{name}": user limit {payload["user_limit"]} → {MAX_VOICE_USERS}')
        payload["user_limit"] = MAX_VOICE_USERS
    _adjust_bitrate(payload, target, adjustments)
    _adjust_forum(payload, adjustments)
    return ChannelStep(channel["id"], payload, can_fall_back=kind in (FORUM, MEDIA))


def _adjust_bitrate(payload, target, adjustments):
    if payload["type"] not in (VOICE, STAGE):
        payload.pop("bitrate", None)
        payload.pop("user_limit", None)
        return
    if "bitrate" not in payload:
        return
    wanted = payload["bitrate"]
    cap = BITRATE_MAX.get(target.premium_tier, BITRATE_MAX[0])
    payload["bitrate"] = max(MIN_BITRATE, min(wanted, cap))
    if payload["bitrate"] != wanted:
        adjustments.append(f'channel "{payload["name"]}": bitrate {wanted} → {payload["bitrate"]} '
                           f'(server boost tier {target.premium_tier})')


def _adjust_forum(payload, adjustments):
    name = payload["name"]
    tags = payload.get("available_tags")
    if tags:
        if len(tags) > MAX_TAGS:
            adjustments.append(f'channel "{name}": {len(tags) - MAX_TAGS} forum tag(s) over the limit of '
                               f'{MAX_TAGS} dropped')
            del tags[MAX_TAGS:]
        custom = [tag for tag in tags if tag.get("emoji_id") is not None]
        for tag in custom:
            tag["emoji_id"] = None
            tag["emoji_name"] = None
        if custom:
            adjustments.append(f'channel "{name}": custom emoji removed from {len(custom)} forum tag(s)')
    reaction = payload.get("default_reaction_emoji")
    if reaction and reaction.get("emoji_id") is not None:
        del payload["default_reaction_emoji"]
        adjustments.append(f'channel "{name}": custom default reaction emoji removed')


def _plan_settings(source, target, plan):
    settings = {key: source[key] for key in GUILD_SETTINGS if source.get(key) is not None}
    types = {c["id"]: c["type"] for c in source["channels"]}
    for key, wanted, label in (("afk_channel_id", VOICE, "voice"), ("system_channel_id", TEXT, "text")):
        channel_id = source.get(key)
        if channel_id is None:
            continue
        if types.get(channel_id) == wanted:
            settings[key] = channel_id
        else:
            plan.adjustments.append(f"server: {key} skipped (channel {channel_id} isn't a {label} channel)")
    for key in COMMUNITY_SETTINGS:
        if source.get(key) is None:
            continue
        if "COMMUNITY" in target.features:
            settings[key] = source[key]
        else:
            plan.adjustments.append(f"server: {key} skipped (needs Community)")
    plan.guild_settings = settings
