from pathlib import Path

import pytest

from src.plan import RoleStep, build_plan, text_fallback
from src.template import load_template
from tests.fakes import GUILD_ID, make_target

FIXTURE = Path(__file__).parent / "fixtures" / "template.json"


@pytest.fixture
def source():
    return load_template(FIXTURE).source


def _minimal(channels=(), roles=(), **settings):
    source = {"roles": [{"id": 0, "name": "@everyone", "permissions": "0"}, *roles], "channels": list(channels)}
    source.update(settings)
    return source


def _payload(plan, template_id):
    return next(step.payload for step in plan.create_channels if step.template_id == template_id)


def test_wipe_deletes_channels_children_first_and_unprotected_roles(source):
    plan = build_plan(source, make_target())
    assert [c["id"] for c in plan.delete_channels] == ["911", "913", "910", "912"]
    assert [r["id"] for r in plan.delete_roles] == ["902"]
    assert plan.protected == ['role "Builder" (managed by an integration)',
                              'role "Admin" (not below the bot\'s role)']


def test_community_required_channels_are_kept(source):
    plan = build_plan(source, make_target(features=frozenset({"COMMUNITY"}), rules_channel_id="911"))
    assert "911" not in [c["id"] for c in plan.delete_channels]
    assert 'channel "general" (required by Community)' in plan.protected


def test_everyone_and_role_payloads(source):
    plan = build_plan(source, make_target())
    assert plan.everyone_permissions == "1071698660929"
    assert plan.create_roles == [
        RoleStep(2, {"name": "Moderator", "permissions": "1099511627775", "color": 15158332,
                     "hoist": True, "mentionable": True}),
        RoleStep(1, {"name": "Member", "permissions": "104324673", "color": 3447003,
                     "hoist": True, "mentionable": False}),
    ]
    assert 'role "Moderator": emoji icon dropped (server has no role icons)' in plan.adjustments


def test_roles_created_top_to_bottom(source):
    plan = build_plan(source, make_target())
    assert [s.template_id for s in plan.create_roles] == [2, 1]


def test_roles_tied_with_the_bot_are_ranked_by_age(source):
    roles = [{"id": GUILD_ID, "name": "@everyone", "position": 0},
             {"id": "901", "name": "Builder", "position": 1, "managed": True},
             {"id": "950", "name": "Newer", "position": 1},
             {"id": "800", "name": "Older", "position": 1}]
    plan = build_plan(source, make_target(roles=roles, bot_top_position=1, bot_top_role_id="901"))
    assert [r["id"] for r in plan.delete_roles] == ["950"]
    assert "role \"Older\" (not below the bot's role)" in plan.protected


def test_role_icons_kept_when_server_has_them(source):
    plan = build_plan(source, make_target(features=frozenset({"ROLE_ICONS"})))
    assert plan.create_roles[0].payload["unicode_emoji"] == "🛡️"
    assert not any("emoji icon" in a for a in plan.adjustments)


def test_custom_role_icon_always_dropped():
    source = _minimal(roles=[{"id": 1, "name": "VIP", "permissions": "0", "icon": "abc123"}])
    plan = build_plan(source, make_target(features=frozenset({"ROLE_ICONS"})))
    assert "icon" not in plan.create_roles[0].payload
    assert 'role "VIP": custom icon dropped (the image isn\'t in the template)' in plan.adjustments


def test_channels_categories_first_then_template_order(source):
    plan = build_plan(source, make_target())
    assert [s.template_id for s in plan.create_channels] == [3, 7, 9, 1, 2, 4, 5, 6, 8]


def test_channel_payloads_keep_template_ids_and_fields(source):
    plan = build_plan(source, make_target())
    assert _payload(plan, 3) == {"name": "Info", "type": 4, "position": 0,
                                 "permission_overwrites": [{"id": 0, "type": 0, "allow": "0", "deny": "2048"}]}
    assert _payload(plan, 4) == {"name": "👋-welcome", "type": 0, "position": 0, "parent_id": 3,
                                 "permission_overwrites": [{"id": 2, "type": 0, "allow": "2048", "deny": "0"}],
                                 "topic": "Say hi", "nsfw": False, "rate_limit_per_user": 0}
    assert _payload(plan, 8) == {"name": "AFK", "type": 2, "position": 0, "parent_id": 7,
                                 "permission_overwrites": [], "nsfw": False, "rate_limit_per_user": 0,
                                 "bitrate": 64000, "user_limit": 0}
    forum = next(s for s in plan.create_channels if s.template_id == 6)
    assert forum.can_fall_back is True
    assert forum.payload["available_tags"] == [
        {"name": "Solved", "moderated": True, "emoji_id": None, "emoji_name": "✅"},
        {"name": "Bug", "moderated": False, "emoji_id": None, "emoji_name": None}]
    assert "default_sort_order" not in forum.payload  # null in the template


def test_settings_keep_template_ids_and_skip_community_fields(source):
    plan = build_plan(source, make_target())
    assert plan.guild_settings == {
        "verification_level": 1, "default_message_notifications": 1, "explicit_content_filter": 2,
        "afk_timeout": 300, "system_channel_flags": 0, "afk_channel_id": 8, "system_channel_id": 4}
    assert "server: preferred_locale skipped (needs Community)" in plan.adjustments


def test_community_settings_applied_on_community_server(source):
    source["description"] = "Clan HQ"
    plan = build_plan(source, make_target(features=frozenset({"COMMUNITY"})))
    assert plan.guild_settings["description"] == "Clan HQ"
    assert plan.guild_settings["preferred_locale"] == "en-US"
    assert not any("needs Community" in a for a in plan.adjustments)


def test_afk_and_system_channels_must_have_the_right_type():
    source = _minimal(channels=[{"id": 1, "type": 0, "name": "chat"}, {"id": 2, "type": 2, "name": "lobby"}],
                      afk_channel_id=1, system_channel_id=2)
    plan = build_plan(source, make_target())
    assert "afk_channel_id" not in plan.guild_settings
    assert "system_channel_id" not in plan.guild_settings
    assert "server: afk_channel_id skipped (channel 1 isn't a voice channel)" in plan.adjustments
    assert "server: system_channel_id skipped (channel 2 isn't a text channel)" in plan.adjustments


@pytest.mark.parametrize("tier, expected", [(0, 96000), (1, 128000), (3, 384000)])
def test_bitrate_capped_by_boost_tier(tier, expected):
    source = _minimal(channels=[{"id": 1, "type": 2, "name": "Loud", "bitrate": 384000}])
    plan = build_plan(source, make_target(premium_tier=tier))
    assert plan.create_channels[0].payload["bitrate"] == expected
    notes = [a for a in plan.adjustments if "bitrate" in a]
    assert notes == ([] if expected == 384000
                     else [f'channel "Loud": bitrate 384000 → {expected} (server boost tier {tier})'])


def test_community_only_types_downgraded_without_community():
    source = _minimal(channels=[{"id": 1, "type": 5, "name": "news"},
                                {"id": 2, "type": 13, "name": "stage", "user_limit": 500}])
    plan = build_plan(source, make_target())
    news, stage = (step.payload for step in plan.create_channels)
    assert news["type"] == 0
    assert (stage["type"], stage["user_limit"]) == (2, 99)
    assert 'channel "news": type 5 needs Community; created as type 0' in plan.adjustments
    assert 'channel "stage": type 13 needs Community; created as type 2' in plan.adjustments
    assert 'channel "stage": user limit 500 → 99' in plan.adjustments


def test_community_only_types_kept_on_community_server():
    source = _minimal(channels=[{"id": 1, "type": 5, "name": "news"}])
    plan = build_plan(source, make_target(features=frozenset({"COMMUNITY"})))
    assert plan.create_channels[0].payload["type"] == 5


def test_custom_emoji_removed_from_forum_and_tags_capped():
    tags = [{"name": f"t{i}", "moderated": False, "emoji_id": None, "emoji_name": None} for i in range(22)]
    tags[0] = {"name": "pog", "moderated": False, "emoji_id": "555", "emoji_name": "pog"}
    source = _minimal(channels=[{"id": 1, "type": 15, "name": "help", "available_tags": tags,
                                 "default_reaction_emoji": {"emoji_id": "556", "emoji_name": "pepe"}}])
    plan = build_plan(source, make_target())
    payload = plan.create_channels[0].payload
    assert len(payload["available_tags"]) == 20
    assert payload["available_tags"][0] == {"name": "pog", "moderated": False, "emoji_id": None, "emoji_name": None}
    assert "default_reaction_emoji" not in payload
    assert 'channel "help": 2 forum tag(s) over the limit of 20 dropped' in plan.adjustments
    assert 'channel "help": custom emoji removed from 1 forum tag(s)' in plan.adjustments
    assert 'channel "help": custom default reaction emoji removed' in plan.adjustments
    assert tags[0]["emoji_id"] == "555"  # the template itself is not mutated


def test_member_overwrites_skipped():
    source = _minimal(channels=[{"id": 1, "type": 0, "name": "chat", "permission_overwrites": [
        {"id": 0, "type": 0, "allow": "0", "deny": "1024"},
        {"id": 777, "type": 1, "allow": "1024", "deny": "0"}]}])
    plan = build_plan(source, make_target())
    assert plan.create_channels[0].payload["permission_overwrites"] == [
        {"id": 0, "type": 0, "allow": "0", "deny": "1024"}]
    assert 'channel "chat": 1 member permission overwrite(s) skipped' in plan.adjustments


def test_text_fallback_drops_forum_fields_without_mutating():
    payload = {"name": "help", "type": 15, "topic": "t", "available_tags": [],
               "default_reaction_emoji": {"emoji_id": None, "emoji_name": "x"},
               "default_sort_order": 0, "default_forum_layout": 1, "default_thread_rate_limit_per_user": 5}
    assert text_fallback(payload) == {"name": "help", "type": 0, "topic": "t",
                                      "default_thread_rate_limit_per_user": 5}
    assert payload["type"] == 15


def test_text_fallback_truncates_topic_to_1024():
    fallback = text_fallback({"name": "help", "type": 15, "topic": "x" * 1500})
    assert fallback["topic"] == "x" * 1024
