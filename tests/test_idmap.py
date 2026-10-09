from collections import Counter
from pathlib import Path

from src.builder import BuildResult
from src.idmap import id_map_path, make_id_map, write_id_map
from src.template import Template, load_template

FIXTURE = Path(__file__).parent / "fixtures" / "template.json"


def _result():
    return BuildResult(done=Counter(), adjustments=[],
                       role_ids={0: "900", 1: "new1", 2: "new2"},
                       channel_ids={3: "new3", 7: "new4", 9: "new5", 1: "new6", 2: "new7",
                                    4: "new8", 5: "new9", 6: "new10", 8: "new11"})


def test_id_map_from_the_exporter_fixture():
    id_map = make_id_map(load_template(FIXTURE), "900", _result())
    assert id_map["guild"] == {"old": "100", "new": "900"}
    assert id_map["roles"] == [{"name": "@everyone", "old": "100", "new": "900"},
                               {"name": "Member", "old": "201", "new": "new1"},
                               {"name": "Moderator", "old": "202", "new": "new2"}]
    assert id_map["channels"][0] == {"name": "general", "type": 0, "old": "307", "new": "new6"}
    assert id_map["channels"][7] == {"name": "AFK", "type": 2, "old": "305", "new": "new11"}
    assert id_map["by_old_id"]["305"] == "new11"
    assert id_map["by_old_id"]["100"] == "900"
    assert len(id_map["by_old_id"]) == 12   # guild and @everyone share old id 100


def test_no_source_ids_means_no_map():
    template = Template(source=load_template(FIXTURE).source, source_guild_id=None, source_ids=None)
    assert make_id_map(template, "900", _result()) is None


def test_id_map_path_sits_next_to_the_template(tmp_path):
    assert id_map_path(tmp_path / "my-server.json") == tmp_path / "my-server.id-map.json"


def test_write_id_map_is_utf8_with_lf(tmp_path):
    path = tmp_path / "m.json"
    write_id_map({"channels": [{"name": "👋-welcome"}]}, path)
    data = path.read_bytes()
    assert "👋-welcome".encode("utf-8") in data
    assert b"\\u" not in data
    assert b"\r\n" not in data
