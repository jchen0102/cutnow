"""P1 验收：版本、审批、交付能对上号。

场景（评审指定）：
  生成 v1 → 审批成片 → 修改生成 v2 → 阻止把 v1 的审批用于 v2 → 审批并交付 v2 → 查到交付的全部记录
"""
import hashlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import records as REC  # noqa: E402


def _edl(total, first=0.0):
    return {"id": "demo", "total": total,
            "video": [{"asset": "src", "start": first, "dur": total}]}


def _artifact(root, name, payload):
    path = os.path.join(root, name)
    with open(path, "wb") as fh:
        fh.write(payload)
    return {"path": path, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}


def test_approval_is_bound_to_the_artifact_not_the_version(tmp_path):
    root = str(tmp_path)

    # 1) v1 + 渲染 + 审批成片
    v1 = REC.create_version(root, _edl(6.0), solution_id="demo", change_note="初版")
    r1 = REC.create_run(root, v1["id"], output=_artifact(root, "v1.mp4", b"v1-bytes"),
                        qc={"pass": True})
    a1 = REC.approve_output(root, r1["id"], by="alice", note="可以发")

    # 2) 改剪法 → 新版本；v1 及其审批保持原样
    v2 = REC.create_version(root, _edl(8.0, first=2.0), parent_id=v1["id"],
                            solution_id="demo", change_note="多两秒")
    r2 = REC.create_run(root, v2["id"], output=_artifact(root, "v2.mp4", b"v2-bytes"),
                        qc={"pass": True})
    assert REC.load(root, "approval", a1["id"])["decision"] == "approved"
    assert REC.load(root, "version", v1["id"])["edl_sha256"] == v1["edl_sha256"]
    assert v2["parent_id"] == v1["id"]

    # 3) v1 的审批不能用于 v2 的交付
    with pytest.raises(REC.DeliveryRefused):
        REC.deliver(root, r2["id"], by="alice")

    # 4) 审批 v2 之后才能交付
    a2 = REC.approve_output(root, r2["id"], by="bob", note="新版通过")
    d = REC.deliver(root, r2["id"], by="bob", channel="douyin")
    assert d["approval_id"] == a2["id"]
    assert d["version_id"] == v2["id"]

    # 5) 审计能查到完整链路
    res = REC.audit(root, d["id"])
    assert res["conclusion"] == "ok", res
    names = {c["name"] for c in res["checks"]}
    assert {"version.sha", "delivery.run", "delivery.output", "approval.output", "artifact"} <= names


def test_delivery_refuses_after_the_artifact_changes(tmp_path):
    root = str(tmp_path)
    v = REC.create_version(root, _edl(4.0), solution_id="demo")
    art = _artifact(root, "x.mp4", b"original")
    r = REC.create_run(root, v["id"], output=art)
    REC.approve_output(root, r["id"], by="alice")

    with open(art["path"], "wb") as fh:          # 审批后替换成片
        fh.write(b"tampered")

    with pytest.raises(REC.DeliveryRefused):
        REC.deliver(root, r["id"], by="alice")
    assert REC.audit(root, "dlv_missing")["conclusion"] == "broken"


def test_script_approval_cannot_authorize_a_delivery(tmp_path):
    root = str(tmp_path)
    v = REC.create_version(root, _edl(5.0), solution_id="demo")
    r = REC.create_run(root, v["id"], output=_artifact(root, "y.mp4", b"y"))
    REC.approve_script(root, v["id"], by="alice")     # 只审了剪法

    with pytest.raises(REC.DeliveryRefused):
        REC.deliver(root, r["id"], by="alice")
