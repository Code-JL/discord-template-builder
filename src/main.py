import argparse
import json
import re
import sys

from dotenv import load_dotenv

from src.api import DiscordApi
from src.builder import build, read_target
from src.config import invite_url, load_token
from src.errors import (ApiError, ConfigError, ConfirmationFailed, Forbidden, InvalidToken, NetworkError,
                        NotAdministrator, NotFound, NotInServer, RateLimited, TemplateError)
from src.idmap import id_map_path, make_id_map, write_id_map
from src.plan import build_plan
from src.template import load_template

MISSING_ACCESS = 50001
TYPE_NAMES = {0: "text", 2: "voice", 4: "category", 5: "announcement", 13: "stage", 15: "forum", 16: "media"}


def _server_id(value):
    if not re.fullmatch(r"[0-9]{1,20}", value):
        raise argparse.ArgumentTypeError(
            f"{value!r} is not a server ID. In Discord, enable Developer Mode, "
            "right-click the server and choose Copy Server ID.")
    return value


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Build a Discord server from a discord-template-export template.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--invite", action="store_true", help="print the link that invites the bot (Administrator)")
    mode.add_argument("--template", metavar="PATH", help="template.json to build from")
    parser.add_argument("--guild", type=_server_id, metavar="ID", help="server to wipe and build into")
    parser.add_argument("--dry-run", action="store_true", help="show the plan without changing anything")
    args = parser.parse_args(argv)
    if args.template and not args.guild:
        parser.error("--template needs --guild")
    return args


def open_api(token):
    return DiscordApi(token)


def confirm(name, input_fn, stdin):
    if not stdin.isatty():
        raise ConfirmationFailed("Refusing to wipe without an interactive confirmation")
    try:
        typed = input_fn(f'Type the server name "{name}" to continue: ')
    except (EOFError, KeyboardInterrupt):
        raise ConfirmationFailed("Cancelled — nothing was changed") from None
    if typed.strip() != name:
        raise ConfirmationFailed("Server name didn't match — nothing was changed")


def print_plan(target, plan, detailed, out=print):
    out(f'Server: "{target.name}" ({target.guild_id})')
    out(f"Will delete: {len(plan.delete_channels)} channels, {len(plan.delete_roles)} roles")
    out(f"Will create: {len(plan.create_roles)} roles, {len(plan.create_channels)} channels")
    if detailed:
        for channel in plan.delete_channels:
            out(f'  - channel "{channel["name"]}"')
        for role in plan.delete_roles:
            out(f'  - role "{role["name"]}"')
        for step in plan.create_roles:
            out(f'  + role "{step.payload["name"]}"')
        names = {step.template_id: step.payload["name"] for step in plan.create_channels}
        for step in plan.create_channels:
            payload = step.payload
            where = f' in "{names[payload["parent_id"]]}"' if "parent_id" in payload else ""
            out(f'  + {TYPE_NAMES.get(payload["type"], payload["type"])} "{payload["name"]}"{where}')
    for item in plan.protected:
        out(f"  kept: {item}")
    for item in plan.adjustments:
        out(f"  adjusted: {item}")


def _run(args, input_fn, stdin):
    token = load_token()
    if args.invite:
        print(invite_url(token))
        return 0
    template = load_template(args.template)   # before any request
    api = open_api(token)
    try:
        target = read_target(api, args.guild)
    except NotFound:
        raise NotInServer(args.guild) from None
    except Forbidden as e:
        # Only reading the server says anything about membership; build-time errors stay plain API errors.
        if e.code == MISSING_ACCESS:
            raise NotInServer(args.guild) from None
        raise NotAdministrator(args.guild) from None
    plan = build_plan(template.source, target)
    print_plan(target, plan, detailed=args.dry_run)
    if args.dry_run:
        print("Dry run — nothing was changed.")
        return 0
    confirm(target.name, input_fn, stdin)
    status = [0]

    def save_id_map(result):
        # Called as soon as everything is created, so a late failure still leaves the map.
        id_map = make_id_map(template, target.guild_id, result)
        if id_map is None:
            print("No ID map: this template has no source_ids "
                  "(re-export it with the current discord-template-export).")
            return
        path = id_map_path(args.template)
        try:
            write_id_map(id_map, path)
        except OSError as e:
            print(f"Couldn't write {path} ({e}). The ID map is printed below — save it:")
            print(json.dumps(id_map, indent=2, ensure_ascii=False))
            status[0] = 1
        else:
            print(f"ID map written to {path}")

    result = build(api, target, plan, on_created=save_id_map)
    print("Done: " + ", ".join(f"{n} {what}" for what, n in result.done.items()))
    for item in plan.protected:
        print(f"  kept: {item}")
    for item in plan.adjustments + result.adjustments:
        print(f"  adjusted: {item}")
    print("Tip: Server Settings → Server Template → Generate makes an official discord.new link from this server.")
    return status[0]


def _invite_hint():
    try:
        return invite_url(load_token())
    except ConfigError:
        return "run --invite"


def main(argv=None, input_fn=input, stdin=None):
    args = parse_args(argv)
    # Channel and role names are full of emoji; never crash printing them.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    load_dotenv()
    try:
        return _run(args, input_fn, stdin or sys.stdin)
    except ConfigError as e:
        message = f"Config error: {e}"
    except TemplateError as e:
        message = f"Template error: {e}"
    except ConfirmationFailed as e:
        message = str(e)
    except InvalidToken:
        message = "BOT_TOKEN is invalid — check .env"
    except NotAdministrator:
        message = f"The bot needs Administrator in server {args.guild} — re-invite it: {_invite_hint()}"
    except NotInServer:
        message = f"The bot isn't in server {args.guild} — invite it: {_invite_hint()}"
    except RateLimited:
        message = "Rate limited by Discord too many times — wait and re-run"
    except NetworkError:
        message = "Network error talking to Discord — re-run"
    except ApiError as e:
        message = f"Discord API error {e.status} ({e.code}): {e.message}"
    except KeyboardInterrupt:
        message = "Interrupted — re-run to wipe and rebuild"
    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
