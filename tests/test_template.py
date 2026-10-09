import json
import re
from pathlib import Path

import pytest

from src.errors import TemplateError
from src.template import load_template

FIXTURE = Path(__file__).parent / "fixtures" / "template.json"


def _source():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["serialized_source_guild"]


def _write(tmp_path, source=None, raw=None):
    path = tmp_path / "t.json"
    text = raw if raw is not None else json.dumps({"serialized_source_guild": source})
    path.write_text(text, encoding="utf-8")
    return path


def _rejected(tmp_path, source, message):
    with pytest.raises(TemplateError, match=re.escape(message)):
        load_template(_write(tmp_path, source))


def _write_file(tmp_path, data):
    path = tmp_path / "t.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_exporter_fixture_loads():
    template = load_template(FIXTURE)
    assert len(template.source["roles"]) == 3
    assert len(template.source["channels"]) == 9
    assert template.source_guild_id == "100"
    assert template.source_ids["roles"] == {0: "100", 1: "201", 2: "202"}
    assert template.source_ids["channels"][8] == "305"


def test_template_without_source_ids(tmp_path):
    template = load_template(_write(tmp_path, _source()))
    assert (template.source_guild_id, template.source_ids) == (None, None)


@pytest.mark.parametrize("source_ids, message", [
    ("nope", "source_ids must be an object"),
    ({"roles": {"99": "123"}}, "source_ids.roles: '99' is not a role in the template"),
    ({"channels": {"x": "123"}}, "source_ids.channels: 'x' is not a channel in the template"),
    ({"channels": {"1": "abc"}}, "source_ids.channels.1: 'abc' is not a Discord ID"),
])
def test_bad_source_ids_rejected(tmp_path, source_ids, message):
    data = {"serialized_source_guild": _source(), "source_ids": source_ids}
    with pytest.raises(TemplateError, match=re.escape(message)):
        load_template(_write_file(tmp_path, data))


def test_missing_file(tmp_path):
    with pytest.raises(TemplateError, match="file not found"):
        load_template(tmp_path / "nope.json")


@pytest.mark.parametrize("raw, message", [
    ("not json", "can't read"),
    ("[]", "no serialized_source_guild"),
    ('{"x": 1}', "no serialized_source_guild"),
])
def test_unreadable_or_wrong_shape(tmp_path, raw, message):
    with pytest.raises(TemplateError, match=message):
        load_template(_write(tmp_path, raw=raw))


@pytest.mark.parametrize("mutate, message", [
    (lambda s: s.update(roles={}), "roles and channels must both be lists"),
    (lambda s: s["roles"].append(dict(s["roles"][1])), "duplicate role id 1"),
    (lambda s: s["channels"][0].update(id="1"), "every channel needs an integer id"),
    (lambda s: s["channels"][0].update(id=True), "every channel needs an integer id"),
    (lambda s: s["roles"][1].pop("name"), "role 1 has no name"),
    (lambda s: s["channels"][3].update(parent_id=1), 'channel "👋-welcome": parent_id 1 is not a category'),
    (lambda s: s["channels"][2].update(parent_id=7), 'category "Info" has a parent_id'),
    (lambda s: s["channels"][3]["permission_overwrites"].append({"id": 42, "type": 0}),
     'channel "👋-welcome": permission overwrite for unknown role 42'),
    (lambda s: s.update(afk_channel_id=99), "afk_channel_id 99 is not a channel in the template"),
])
def test_broken_templates_rejected(tmp_path, mutate, message):
    source = _source()
    mutate(source)
    _rejected(tmp_path, source, message)


def test_member_overwrite_with_unknown_id_is_allowed(tmp_path):
    source = _source()
    source["channels"][0]["permission_overwrites"].append({"id": 777, "type": 1, "allow": "0", "deny": "0"})
    load_template(_write(tmp_path, source))


def test_too_many_roles(tmp_path):
    source = _source()
    source["roles"] = [{"id": i, "name": f"r{i}", "permissions": "0"} for i in range(251)]
    _rejected(tmp_path, source, "251 roles; Discord allows 250")


def test_too_many_channels(tmp_path):
    source = _source()
    source["channels"] = [{"id": i, "type": 0, "name": f"c{i}"} for i in range(1, 502)]
    _rejected(tmp_path, source, "501 channels; Discord allows 500")


def test_too_many_channels_in_one_category(tmp_path):
    source = _source()
    source["channels"] = [{"id": 1, "type": 4, "name": "big"}] + [
        {"id": i, "type": 0, "name": f"c{i}", "parent_id": 1} for i in range(2, 53)]
    _rejected(tmp_path, source, 'category "big" has 51 channels; Discord allows 50')
