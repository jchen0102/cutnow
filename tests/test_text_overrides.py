"""文字卡与示例文案：默认不出卡、不残留示例署名、覆盖参数能注入。"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cutnow  # noqa: E402
from core import builtin_ops  # noqa: F401,E402


def _args(**kw):
    base = dict(title=None, sub=None, end=None, end_sub=None, credit=None)
    base.update(kw)
    return argparse.Namespace(**base)


def _sol_with_card():
    return {"id": "x", "steps": [{"id": "cards", "op": "card.bookends", "params": {}}]}


def test_builtin_solutions_have_no_demo_copy():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "solutions")
    for path in glob.glob(os.path.join(root, "*.solution.json")):
        raw = open(path, encoding="utf-8").read()
        for banned in ("TEARS OF STEEL", "Wikimedia", "Blender Foundation", "tos-montage"):
            assert banned not in raw, f"{os.path.basename(path)} 仍写着示例文案：{banned}"


def test_no_text_flags_means_no_cards():
    sol = _sol_with_card()
    cutnow._apply_text(_args(), sol)
    assert sol["steps"][0]["params"] == {}


def test_title_and_credit_injected():
    sol = _sol_with_card()
    cutnow._apply_text(_args(title="决赛集锦", credit="© 2026 俱乐部"), sol)
    p = sol["steps"][0]["params"]
    assert p["title"] == "决赛集锦"
    assert p["end_sub"] == "© 2026 俱乐部"


def test_credit_falls_back_to_end_sub_only():
    sol = _sol_with_card()
    cutnow._apply_text(_args(end_sub="已有署名", credit="被忽略"), sol)
    assert sol["steps"][0]["params"]["end_sub"] == "已有署名"


def test_warns_when_solution_has_no_card_step(capsys):
    sol = {"id": "x", "steps": [{"id": "render", "op": "render.edl", "params": {}}]}
    cutnow._apply_text(_args(title="会丢"), sol)
    assert "没有文字卡步骤" in capsys.readouterr().err


def test_card_bookends_noop_keeps_timeline():
    ctx = {"root": ".", "edl": {"output": {"width": 1280, "height": 720, "fps": 30},
                                "assets": [], "video": [{"asset": "src", "start": 0.0, "dur": 2.0}],
                                "total": 2.0}}
    res = builtin_ops.card_bookends(ctx, {})
    assert res == {"head": False, "tail": False, "total": 2.0}
    assert len(ctx["edl"]["video"]) == 1


def test_subtitle_noop_without_lines():
    ctx = {"edl": {}, "analysis": {"bpm": 120}}
    assert builtin_ops.subtitle_by_beat(ctx, {}) == {"lines": 0}
    assert ctx["edl"]["subs"] == []
