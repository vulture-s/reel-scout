"""Source-side zh conversion: mode (s2twp / s2tw / off) + user hotwords after OpenCC."""
from __future__ import annotations

import json
import os

import pytest

from reel_scout import cli, config, inspire, zh_convert

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "docs", "zh-hotwords.example.yaml")


# ------------------------------------------------------------- parsing (no opencc)

def test_parse_yaml_and_json_forms():
    yaml_text = "# comment\n\n类型: 類型\n\"视频游戏\": '電玩'\n全形冒號：好\n"
    assert zh_convert.parse_hotwords(yaml_text) == {"类型": "類型", "视频游戏": "電玩", "全形冒號": "好"}
    assert zh_convert.parse_hotwords('{"类型": "類型"}') == {"类型": "類型"}
    assert zh_convert.parse_hotwords("") == {}


@pytest.mark.parametrize("bad", ["no separator here", ": empty key", "[1, 2]", '{"a": 1}'])
def test_parse_rejects_malformed(bad):
    with pytest.raises(ValueError):
        zh_convert.parse_hotwords(bad)


def test_example_file_parses():
    assert zh_convert.load_hotwords(EXAMPLE) == {"类型": "類型", "视频游戏": "電玩"}


@pytest.mark.parametrize("raw,mode", [("s2twp", "s2twp"), ("S2TW", "s2tw"), ("s2tw.json", "s2tw"),
                                      ("off", "off"), ("none", "off"), ("0", "off"), ("", "off")])
def test_normalize_mode(raw, mode):
    assert zh_convert.normalize_mode(raw) == mode


def test_unknown_mode_is_an_error():
    with pytest.raises(ValueError):
        zh_convert.normalize_mode("t2s")


def test_longest_match_wins_without_opencc():
    conv = zh_convert.Converter("off", {"视频": "影片", "视频游戏": "電玩"})
    assert conv.opencc is None and not conv.opencc_missing
    assert conv("看视频游戏和视频") == "看電玩和影片"


def test_off_mode_skips_opencc_but_keeps_hotwords(monkeypatch):
    monkeypatch.setattr(config, "ZH_CONVERT", "off")
    monkeypatch.setattr(config, "ZH_HOTWORDS", "")
    raw = json.dumps({"summary": "视频"}, ensure_ascii=False)
    assert inspire._analysis_for_prompt(raw) == raw
    out = inspire._analysis_for_prompt(raw, zh_mode="off", zh_hotwords=EXAMPLE)
    assert json.loads(out) == {"summary": "视频"}  # no key of the table matches 视频 alone
    out = inspire._analysis_for_prompt(json.dumps({"s": "类型"}, ensure_ascii=False), zh_hotwords=EXAMPLE)
    assert json.loads(out) == {"s": "類型"}


def test_no_opencc_warns_with_install_command_and_still_applies_hotwords(no_opencc, capsys):
    raw = json.dumps({"s": "视频游戏"}, ensure_ascii=False)
    out = inspire._analysis_for_prompt(raw, zh_mode="s2twp", zh_hotwords=EXAMPLE)
    assert json.loads(out) == {"s": "電玩"}
    err = capsys.readouterr().err
    assert "opencc not installed" in err and 'pip install "reel-scout[zh]"' in err


def test_no_opencc_in_this_environment_for_real():
    """On CI's base job (no zh extra) the fallback is the real one, not a stub."""
    if os.environ.get("REEL_SCOUT_EXPECT_NO_OPENCC") != "1":
        pytest.skip("only meaningful on the job installed without the zh extra")
    with pytest.raises(ImportError):
        import opencc  # noqa: F401  # type: ignore
    conv = zh_convert.build_converter("s2twp", "")
    assert conv.opencc_missing


# ------------------------------------------------------------- with opencc

def test_s2twp_default_and_hotwords_fix_its_swaps(need_opencc, monkeypatch):
    monkeypatch.setattr(config, "ZH_CONVERT", "s2twp")
    monkeypatch.setattr(config, "ZH_HOTWORDS", "")
    text = "这是一款视频游戏，类型是动作，软件"
    assert zh_convert.build_converter()(text) == "這是一款影片遊戲，型別是動作，軟體"
    fixed = zh_convert.build_converter(hotwords_path=EXAMPLE)(text)
    assert fixed == "這是一款電玩，類型是動作，軟體"


def test_hotword_keys_in_converted_form_also_match(need_opencc):
    conv = zh_convert.Converter("s2twp", {"型別": "類型"})
    assert conv("类型") == "類型"


def test_s2tw_is_per_character(need_opencc):
    conv = zh_convert.build_converter("s2tw", "")
    assert conv("视频游戏的类型，软件") == "視頻遊戲的類型，軟件"


def test_env_selects_mode(need_opencc, monkeypatch):
    raw = json.dumps({"s": "视频软件"}, ensure_ascii=False)
    monkeypatch.setattr(config, "ZH_HOTWORDS", "")
    monkeypatch.setattr(config, "ZH_CONVERT", "s2tw")
    assert json.loads(inspire._analysis_for_prompt(raw)) == {"s": "視頻軟件"}
    monkeypatch.setattr(config, "ZH_CONVERT", "s2twp")
    assert json.loads(inspire._analysis_for_prompt(raw)) == {"s": "影片軟體"}


def test_hotwords_never_touch_model_output_or_keys(need_opencc):
    conv = zh_convert.Converter("s2twp", {"类型": "類型"})
    tree = {"类型": "类型"}
    assert inspire._to_traditional(tree, conv) == {"类型": "類型"}


def test_cli_flags_reach_generate(monkeypatch):
    seen = {}

    def fake(conn, ref, **kw):
        seen.update(kw)
        return {"based_on": "x", "name_check": {"status": "passed", "attempts": 1}}

    monkeypatch.setattr(inspire, "generate_inspiration", fake)
    monkeypatch.setattr(cli.config, "ensure_dirs", lambda: None)
    monkeypatch.setattr("reel_scout.db.init_db", lambda *a, **k: type("C", (), {"close": lambda s: None})())
    try:
        cli.main(["inspire", "--based-on", "x", "--zh-convert", "s2tw",
                  "--zh-hotwords", EXAMPLE, "--name-retries", "5"])
    except SystemExit as e:
        assert e.code in (None, 0)
    assert seen == {"angle": "", "name_retries": 5, "zh_mode": "s2tw", "zh_hotwords": EXAMPLE}
