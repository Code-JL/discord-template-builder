import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from src.errors import TemplateError

CATEGORY = 4
MAX_ROLES = 250
MAX_CHANNELS = 500
MAX_PER_CATEGORY = 50
SNOWFLAKE = re.compile(r"[0-9]{1,20}")


@dataclass
class Template:
    source: dict                  # the validated serialized_source_guild
    source_guild_id: str | None   # the original server's id, if recorded
    source_ids: dict | None       # {"roles": {template id: original id}, "channels": {...}}, if recorded


def load_template(path):
    """Read a discord-template-export template.json and validate it."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TemplateError(f"file not found: {path}") from None
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise TemplateError(f"can't read {path}: {e}") from None
    source = data.get("serialized_source_guild") if isinstance(data, dict) else None
    if not isinstance(source, dict):
        raise TemplateError("no serialized_source_guild — is this a discord-template-export template.json?")
    validate(source)
    guild_id = data.get("source_guild_id")
    guild_id = guild_id if isinstance(guild_id, str) and SNOWFLAKE.fullmatch(guild_id) else None
    return Template(source, guild_id, _source_ids(data.get("source_ids"), source))


def _source_ids(raw, source):
    """Validate the exporter's template-id -> original-id map; None if the file has none."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TemplateError("source_ids must be an object")
    known = {"roles": {r["id"] for r in source["roles"]}, "channels": {c["id"] for c in source["channels"]}}
    result = {}
    for kind in ("roles", "channels"):
        mapping = raw.get(kind) or {}
        if not isinstance(mapping, dict):
            raise TemplateError(f"source_ids.{kind} must be an object")
        converted = {}
        for key, original in mapping.items():
            if not (isinstance(key, str) and re.fullmatch(r"[0-9]+", key) and int(key) in known[kind]):
                raise TemplateError(f"source_ids.{kind}: {key!r} is not a {kind[:-1]} in the template")
            if not (isinstance(original, str) and SNOWFLAKE.fullmatch(original)):
                raise TemplateError(f"source_ids.{kind}.{key}: {original!r} is not a Discord ID")
            converted[int(key)] = original
        result[kind] = converted
    return result


def validate(source):
    roles, channels = source.get("roles"), source.get("channels")
    if not isinstance(roles, list) or not isinstance(channels, list):
        raise TemplateError("roles and channels must both be lists")
    if len(roles) > MAX_ROLES:
        raise TemplateError(f"{len(roles)} roles; Discord allows {MAX_ROLES}")
    if len(channels) > MAX_CHANNELS:
        raise TemplateError(f"{len(channels)} channels; Discord allows {MAX_CHANNELS}")
    role_ids = _unique_ids(roles, "role")
    channel_ids = _unique_ids(channels, "channel")
    for role in roles:
        for key in ("name", "permissions"):
            if key not in role:
                raise TemplateError(f"role {role['id']} has no {key}")
    _check_channels(channels, role_ids)
    for key in ("afk_channel_id", "system_channel_id"):
        value = source.get(key)
        if value is not None and value not in channel_ids:
            raise TemplateError(f"{key} {value} is not a channel in the template")


def _unique_ids(items, kind):
    ids = set()
    for item in items:
        item_id = item.get("id") if isinstance(item, dict) else None
        # bool is an int subclass; True must not pass as id 1.
        if not isinstance(item_id, int) or isinstance(item_id, bool):
            raise TemplateError(f"every {kind} needs an integer id, got {item!r:.80}")
        if item_id in ids:
            raise TemplateError(f"duplicate {kind} id {item_id}")
        ids.add(item_id)
    return ids


def _check_channels(channels, role_ids):
    for channel in channels:
        for key in ("type", "name"):
            if key not in channel:
                raise TemplateError(f"channel {channel['id']} has no {key}")
    categories = {c["id"]: c["name"] for c in channels if c["type"] == CATEGORY}
    children = Counter()
    for channel in channels:
        name, parent = channel["name"], channel.get("parent_id")
        if channel["type"] == CATEGORY and parent is not None:
            raise TemplateError(f'category "{name}" has a parent_id')
        if parent is not None and parent not in categories:
            raise TemplateError(f'channel "{name}": parent_id {parent} is not a category in the template')
        if parent is not None:
            children[parent] += 1
        for overwrite in channel.get("permission_overwrites") or []:
            if overwrite.get("type", 0) == 0 and overwrite.get("id") not in role_ids:
                raise TemplateError(
                    f'channel "{name}": permission overwrite for unknown role {overwrite.get("id")}')
    for parent, count in children.items():
        if count > MAX_PER_CATEGORY:
            raise TemplateError(
                f'category "{categories[parent]}" has {count} channels; Discord allows {MAX_PER_CATEGORY}')
