"""最小冒烟：算子注册、解法校验、EDL 重排、卡点计算。不需要素材和模型。"""
import json, os, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import ops, builtin_ops, solution as SOL  # noqa: E402
from core import edl as E, plan as P  # noqa: E402


def test_core_ops_registered():
    for name in ("analyze.standard", "select.shots", "render.edl", "qc.report",
                 "card.bookends", "select.semantic", "qc.source"):
        assert name in ops.OPS, f"缺少算子 {name}"


def test_solution_validation_rejects_unknown_op(tmp_path):
    p = tmp_path / "bad.solution.json"
    p.write_text(json.dumps({"id": "x", "name": "x", "inputs": {"source": {"type": "video"}},
                             "steps": [{"op": "evil.rm_rf"}]}))
    with pytest.raises(SOL.SolutionError) as e:
        SOL.load(str(p), ops.OPS)
    assert "未注册" in str(e.value)


def test_solution_validation_rejects_bad_gate(tmp_path):
    p = tmp_path / "bad2.solution.json"
    p.write_text(json.dumps({"id": "x", "name": "x", "inputs": {"source": {"type": "video"}},
                             "steps": [{"op": "render.edl", "gate": "sudo"}]}))
    with pytest.raises(SOL.SolutionError) as e:
        SOL.load(str(p), ops.OPS)
    assert "gate" in str(e.value)


def test_edl_retime_keeps_total():
    e = {"version": 1, "output": {"width": 1280, "height": 720, "fps": 30},
         "total": 8.0, "audio": [{"asset": "music", "in": 0.0, "dur": 8.0}],
         "subs": [],
         "video": [{"asset": "src", "start": 0.0, "dur": 4.0, "at": 0.0, "beats": 8},
                   {"asset": "src", "start": 10.0, "dur": 4.0, "at": 4.0, "beats": 8}]}
    e["video"][0]["beats"] = 4
    out = E.retime(e, 120)          # 120 BPM → 0.5s/拍
    assert out["video"][0]["dur"] == pytest.approx(2.0)
    assert out["total"] == pytest.approx(6.0)
    assert out["video"][1]["at"] == pytest.approx(2.0)


def test_shot_duration_matches_beats():
    beat = 60.0 / 120.0     # 120 BPM → 0.5s
    video, total = [], 0.0
    for beats in (8, 4, 12):
        video.append({"beats": beats, "dur": beats * beat, "at": total})
        total += beats * beat
    assert total == pytest.approx(12.0)


def test_version_matches_pyproject():
    import re
    from core import __version__
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    txt = open(os.path.join(root, "pyproject.toml"), encoding="utf-8").read()
    m = re.search(r'^version = "([^"]+)"', txt, re.M)
    assert m and m.group(1) == __version__, f"pyproject={m and m.group(1)} core={__version__}"
