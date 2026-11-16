"""分镜稿 → EDL：结构正确、素材轮转、字幕切行。"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import storyboard as SB  # noqa: E402


def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_load_accepts_media_desk_shape(tmp_path):
    p = _write(tmp_path, "sb.json", {"shots": [
        {"no": 1, "shot": "中景", "voice": "第一句", "seconds": 2},
        {"no": 2, "visual": "特写", "seconds": "3.5"},
    ]})
    shots = SB.load(p)
    assert [s["seconds"] for s in shots] == [2.0, 3.5]
    assert shots[0]["role"] == "中景" and shots[0]["voice"] == "第一句"
    assert shots[1]["role"] == "特写"


def test_load_rejects_missing_seconds(tmp_path):
    p = _write(tmp_path, "bad.json", [{"role": "x"}])
    with pytest.raises(SB.StoryboardError):
        SB.load(p)


def test_build_edl_rotates_sources_and_times_subtitles(tmp_path, monkeypatch):
    a = tmp_path / "a.mp4"; a.write_bytes(b"x")
    b = tmp_path / "b.mp4"; b.write_bytes(b"x")
    from core import ffmpeg as F
    monkeypatch.setattr(F, "probe", lambda p: {"width": 640, "height": 360, "fps": 30,
                                               "duration": 10.0, "has_audio": False})
    shots = [
        {"no": 1, "role": "开场", "voice": "第一句。", "seconds": 2.0},
        {"no": 2, "role": "中景", "voice": "第二句，稍微长一点。", "seconds": 3.0},
        {"no": 3, "role": "结尾", "voice": "", "seconds": 1.5},
    ]
    edl, warns = SB.build_edl(shots, [str(a), str(b)], {"width": 640, "height": 360, "fps": 30})
    assert [x["asset"] for x in edl["video"]] == ["src", "s1", "s2"]   # 轮转
    assert [x["at"] for x in edl["video"]] == [0.0, 2.0, 5.0]
    assert edl["total"] == 6.5
    assert edl["output"] == {"width": 640, "height": 360, "fps": 30}
    assert warns == []
    # 字幕落在各自镜头的时间窗内
    assert edl["subs"] and all(0 <= s["start"] < s["end"] <= 6.5 for s in edl["subs"])


def test_wrap_warning_when_source_is_short(tmp_path, monkeypatch):
    a = tmp_path / "a.mp4"; a.write_bytes(b"x")
    from core import ffmpeg as F
    monkeypatch.setattr(F, "probe", lambda p: {"width": 320, "height": 180, "fps": 30,
                                               "duration": 3.0, "has_audio": False})
    edl, warns = SB.build_edl([{"no": 1, "role": "x", "seconds": 2.0},
                               {"no": 2, "role": "y", "seconds": 2.0}],
                              [str(a)], {"width": 320, "height": 180, "fps": 30})
    assert any("回到" in w for w in warns)
    assert all(v["start"] + v["dur"] <= 3.0 + 1e-6 for v in edl["video"])
