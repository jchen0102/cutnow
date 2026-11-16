"""版本/审批/交付的最小闭环：P1 只证明「审批的成片 == 交付的成片」。"""
import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import records as REC  # noqa: E402


def _artifact(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p), hashlib.sha256(data).hexdigest()


def _version(root, tag, parent=None):
    return REC.create_version(
        root, {"id": tag, "video": [], "total": 1.0},
        inputs=[{"id": "source", "path": "match.mp4", "sha256": "a" * 64}],
        solution_id="sports-highlight", parent_id=parent, change_note=tag,
    )


def test_acceptance_flow(tmp_path):
    """v1 审批 → 改出 v2 → v1 审批不能用于 v2 → 审批并交付 v2 → 追到全部记录。"""
    root = str(tmp_path)
    p1, sha1 = _artifact(tmp_path, "v1.mp4", b"first cut")
    v1 = _version(root, "v1")
    run1 = REC.create_run(root, v1["id"], output={"path": p1, "sha256": sha1, "bytes": 9})
    apr1 = REC.approve_output(root, run1["id"], by="alice", note="第一条")

    p2, sha2 = _artifact(tmp_path, "v2.mp4", b"second cut")
    v2 = _version(root, "v2", parent=v1["id"])
    run2 = REC.create_run(root, v2["id"], output={"path": p2, "sha256": sha2, "bytes": 10})

    # v1 的审批不能用于 v2 的成片
    with pytest.raises(REC.DeliveryRefused):
        REC.deliver(root, run2["id"], by="bob")

    # 历史审批保持原样，不被作废
    assert REC.load(root, "approval", apr1["id"])["decision"] == "approved"
    assert REC.load(root, "approval", apr1["id"])["target"]["run_id"] == run1["id"]

    apr2 = REC.approve_output(root, run2["id"], by="alice")
    d = REC.deliver(root, run2["id"], by="bob", channel="douyin")
    assert d["approval_id"] == apr2["id"]
    assert d["output_sha256"] == sha2

    res = REC.audit(root, d["id"])
    assert res["conclusion"] == "ok", res["checks"]
    assert res["version"]["id"] == v2["id"]
    assert res["approval"]["id"] == apr2["id"]


def test_script_approval_cannot_deliver(tmp_path):
    root = str(tmp_path)
    p, sha = _artifact(tmp_path, "v.mp4", b"x")
    v = _version(root, "v1")
    run = REC.create_run(root, v["id"], output={"path": p, "sha256": sha, "bytes": 1})
    REC.approve_script(root, v["id"], by="alice")
    with pytest.raises(REC.DeliveryRefused):
        REC.deliver(root, run["id"], by="bob")


def test_delivery_audit_detects_tampered_artifact(tmp_path):
    root = str(tmp_path)
    p, sha = _artifact(tmp_path, "v.mp4", b"original")
    v = _version(root, "v1")
    run = REC.create_run(root, v["id"], output={"path": p, "sha256": sha, "bytes": 8})
    REC.approve_output(root, run["id"], by="alice")
    d = REC.deliver(root, run["id"], by="bob")
    open(p, "wb").write(b"tampered")
    res = REC.audit(root, d["id"])
    assert res["conclusion"] == "broken"
    assert next(c for c in res["checks"] if c["name"] == "artifact")["status"] == "broken"


def test_records_are_immutable(tmp_path):
    root = str(tmp_path)
    v = _version(root, "v1")
    path = os.path.join(root, ".cutnow", "versions", v["id"] + ".json")
    with pytest.raises(FileExistsError):
        REC._write_new(path, v)


def test_historical_import_marks_unknown(tmp_path):
    root = str(tmp_path)
    v = REC.create_version(root, {"id": "old", "video": [], "total": 1.0},
                           imported=True, unknown=["environment", "approval", "source"])
    assert v["origin"]["kind"] == "import"
    assert "approval" in v["origin"]["unknown"]


def test_parent_chain_and_latest(tmp_path):
    root = str(tmp_path)
    v1 = _version(root, "v1")
    v2 = _version(root, "v2", parent=v1["id"])
    assert REC.latest_version_id(root, "sports-highlight") == v2["id"]
    assert REC.load(root, "version", v2["id"])["parent_id"] == v1["id"]
