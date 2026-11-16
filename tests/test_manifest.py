"""复现凭据的测试：好的凭据要 ok，动过的要 broken，环境变了要 drift。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import manifest as MF  # noqa: E402


def _build(tmp_path, src=b"source-bytes", out=b"rendered-bytes"):
    src_p = tmp_path / "src.mp4"
    src_p.write_bytes(src)
    out_p = tmp_path / "out.mp4"
    out_p.write_bytes(out)
    sol_p = tmp_path / "s.solution.json"
    sol_p.write_bytes(b'{"id": "x", "steps": []}')
    edl = {"version": 1, "id": "x", "video": [{"start": 0, "dur": 1}], "total": 1.0}
    edl_p = tmp_path / "edl_x.json"
    edl_p.write_text(json.dumps(edl), encoding="utf-8")
    m = MF.build(
        str(sol_p), {"id": "x"}, {"source": str(src_p)},
        [{"id": "render", "op": "render.edl", "params": {"crf": 20}}],
        edl, str(edl_p), str(out_p), str(tmp_path),
    )
    mp = tmp_path / "x.manifest.json"
    MF.write(m, str(mp))
    return mp, src_p, out_p, edl_p


def _check(res, name):
    return next(c for c in res["checks"] if c["name"] == name)


def test_identity_relative_and_deterministic(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"x" * 100)
    a = MF.identity(str(f), str(tmp_path))
    b = MF.identity(str(f), str(tmp_path))
    assert a["path"] == "a.bin"
    assert a["sha256"] == b["sha256"]
    assert a["hash_mode"] == "full"


def test_quick_mode_is_stable_and_marked(tmp_path):
    f = tmp_path / "big.bin"
    f.write_bytes(b"y" * 4096)
    a = MF.identity(str(f), str(tmp_path), "quick")
    b = MF.identity(str(f), str(tmp_path), "quick")
    assert a["hash_mode"] == "quick"
    assert a["sha256"] == b["sha256"]


def test_verify_ok(tmp_path):
    mp, *_ = _build(tmp_path)
    res = MF.verify(str(mp))
    assert res["conclusion"] == "ok", res["checks"]
    assert _check(res, "output")["status"] == "ok"


def test_tampered_output_is_broken(tmp_path):
    mp, _src, out, _edl = _build(tmp_path)
    out.write_bytes(b"different-bytes")
    res = MF.verify(str(mp))
    assert res["conclusion"] == "broken"
    assert _check(res, "output")["status"] == "broken"


def test_tampered_input_is_broken(tmp_path):
    mp, src, _out, _edl = _build(tmp_path)
    src.write_bytes(b"other-source")
    res = MF.verify(str(mp))
    assert res["conclusion"] == "broken"
    assert _check(res, "input.source")["status"] == "broken"


def test_missing_input_is_broken(tmp_path):
    mp, src, _out, _edl = _build(tmp_path)
    src.unlink()
    res = MF.verify(str(mp))
    assert res["conclusion"] == "broken"
    assert _check(res, "input.source")["detail"] == "素材不在了"


def test_tampered_edl_is_broken(tmp_path):
    mp, _src, _out, edl = _build(tmp_path)
    edl.write_text(json.dumps({"version": 1, "id": "x", "video": [], "total": 2.0}), encoding="utf-8")
    res = MF.verify(str(mp))
    assert res["conclusion"] == "broken"
    assert _check(res, "edl")["status"] == "broken"


def test_engine_version_change_is_drift(tmp_path):
    mp, _src, _out, _edl = _build(tmp_path)
    data = json.loads(mp.read_text(encoding="utf-8"))
    data["engine"]["version"] = "0.0.0-other"
    mp.write_text(json.dumps(data), encoding="utf-8")
    res = MF.verify(str(mp))
    assert res["conclusion"] == "drift"
    assert _check(res, "engine.version")["status"] == "drift"


def test_json_serializable(tmp_path):
    mp, *_ = _build(tmp_path)
    json.dumps(MF.verify(str(mp)), ensure_ascii=False)
