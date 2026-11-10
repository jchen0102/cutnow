"""真渲一条 2 秒片子：生成素材 → EDL → 渲染 → 质检。

这是 dogfooding：CI 里必须有一条真的出片，而不只是单元测试。
只依赖 ffmpeg（imageio-ffmpeg 随包提供），macOS / Linux 都能跑。
"""
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import ffmpeg as F, render as R, qc  # noqa: E402


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    src = str(d / "src.mp4")
    # 4 秒 320x180 的测试图 + 440Hz 正弦，不需要任何外部素材
    p = subprocess.run(
        [F.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=4",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src],
        capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-500:]
    music = str(d / "music.m4a")
    p = subprocess.run(
        [F.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=220:duration=8", "-c:a", "aac", music],
        capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-500:]
    return src, music


def _edl(src, music, total=2.0):
    return {
        "version": 1, "id": "smoke",
        "output": {"width": 320, "height": 180, "fps": 30},
        "cleanup": {"crop": [320, 180, 0, 0], "crop_bottom": 0},
        "assets": [{"id": "src", "path": src}, {"id": "music", "path": music}],
        "video": [{"asset": "src", "start": 0.0, "dur": total, "at": 0.0, "role": "开场"}],
        "audio": [{"asset": "music", "in": 0.0, "dur": total}],
        "subs": [{"start": 0.2, "end": 1.2, "text": "cutnow smoke"}],
        "total": total,
    }


def test_render_and_qc(clip, tmp_path):
    src, music = clip
    edl = _edl(src, music)
    out = str(tmp_path / "out.mp4")
    res = R.render(edl, str(tmp_path), out)
    assert os.path.getsize(out) > 10_000
    assert len(res["sha256"]) == 64

    rep = qc.report(out, edl, skip_subtitles=not res["subs_burned"])
    assert rep["checks"]["duration"]["ok"], rep["checks"]["duration"]
    assert rep["checks"]["subtitles"]["ok"], rep["checks"]["subtitles"]
    # 没有 drawtext 的环境会跳过字幕，但必须给出 warning，而不是静默
    if not res["subs_burned"]:
        assert res["warnings"], "跳过字幕时必须报告原因"


def test_render_is_deterministic(clip, tmp_path):
    src, music = clip
    edl = _edl(src, music)
    a = R.render(edl, str(tmp_path / "a"), str(tmp_path / "a.mp4"))["sha256"]
    b = R.render(edl, str(tmp_path / "b"), str(tmp_path / "b.mp4"))["sha256"]
    assert a == b, "同一份 EDL 渲染两次结果必须一致"
