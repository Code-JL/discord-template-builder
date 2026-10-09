"""Old-ID -> new-ID map after a build, for reconfiguring bots that store Discord IDs."""
import json
from pathlib import Path


def make_id_map(template, target_guild_id, result):
    """The map for a finished build, or None if the template records no original ids."""
    if template.source_ids is None:
        return None
    role_names = {r["id"]: r["name"] for r in template.source["roles"]}
    channels_by_id = {c["id"]: c for c in template.source["channels"]}
    by_old = {}
    if template.source_guild_id:
        by_old[template.source_guild_id] = target_guild_id
    roles = []
    for template_id, old in template.source_ids["roles"].items():
        new = result.role_ids.get(template_id)
        if new is not None:
            roles.append({"name": role_names[template_id], "old": old, "new": new})
            by_old[old] = new
    channels = []
    for template_id, old in template.source_ids["channels"].items():
        new = result.channel_ids.get(template_id)
        if new is not None:
            channel = channels_by_id[template_id]
            channels.append({"name": channel["name"], "type": channel["type"], "old": old, "new": new})
            by_old[old] = new
    return {"guild": {"old": template.source_guild_id, "new": target_guild_id},
            "roles": roles, "channels": channels, "by_old_id": by_old}


def id_map_path(template_path):
    path = Path(template_path)
    return path.with_name(path.stem + ".id-map.json")


def write_id_map(id_map, path):
    # Explicit UTF-8 and "\n": emoji names stay readable and the file is identical on every OS.
    Path(path).write_text(json.dumps(id_map, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8", newline="\n")
