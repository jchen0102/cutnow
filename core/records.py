"""版本 / 渲染 / 审批 / 交付四类记录：回答「审的是哪一版、交的是哪一版」。

设计约束（P1 只承诺这一条）：

  * `version` 不可变：EDL 内联存一份 + 摘要；改剪法必须产生新版本，不覆盖旧版本。
  * `render_run` 是一次执行：同一版本可以渲染多次（失败、换环境、重试）。
  * `approval` 分两种作用域：
      - scope="output" 绑到具体渲染产物（run_id + output_sha256），
      - scope="script" 只绑到版本（version_id + edl_sha256）。
    审批成片必须走前者，否则 v1 的审批会被误用到 v2 上。
  * `delivery` 必须引用一条与「实际交付成片 sha」匹配的 output 审批。

记录只追加、不修改：写入用 O_EXCL，已存在即报错；`ledger.jsonl` 记录每条的摘要，
`audit` 时逐条重算并与账本比对。
"""
import hashlib
import json
import os
import time
import uuid

BASE = ".cutnow"
LEDGER = "ledger.jsonl"
DIRS = {"version": "versions", "render_run": "runs", "approval": "approvals", "delivery": "deliveries"}
SCHEMAS = {
    "version": "cutnow.version/1",
    "render_run": "cutnow.render_run/1",
    "approval": "cutnow.approval/1",
    "delivery": "cutnow.delivery/1",
}


class RecordError(Exception):
    pass


class DeliveryRefused(RecordError):
    pass


# ---------- 基础 ----------

def _base(root):
    return os.path.join(os.path.abspath(root), BASE)


def _dir(root, kind):
    return os.path.join(_base(root), DIRS[kind])


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def new_id(prefix):
    return f"{prefix}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{uuid.uuid4().hex[:6]}"


def digest(obj):
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def seal(record):
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    body["record_sha256"] = digest(record)
    return body


def _write_new(path, record):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    except Exception:
        raise
    return path


def _ledger(root, record):
    path = os.path.join(_base(root), LEDGER)
    line = json.dumps({"id": record["id"], "kind": record["kind"],
                       "sha256": record["record_sha256"], "at": record["created_at"]},
                      ensure_ascii=False)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        try:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _save(root, kind, record):
    record["seq"] = time.time_ns()      # 同一秒内的稳定顺序
    record = seal(record)
    path = os.path.join(_dir(root, kind), record["id"] + ".json")
    _write_new(path, record)
    _ledger(root, record)
    return record


def load(root, kind, rid):
    path = os.path.join(_dir(root, kind), rid + ".json")
    if not os.path.isfile(path):
        raise RecordError(f"找不到 {kind} 记录：{rid}")
    with open(path, encoding="utf-8") as fh:
        rec = json.load(fh)
    body = {k: v for k, v in rec.items() if k != "record_sha256"}
    if rec.get("record_sha256") != digest(body):
        raise RecordError(f"{rid} 的记录摘要不匹配（文件被改过）")
    return rec


def list_records(root, kind):
    d = _dir(root, kind)
    if not os.path.isdir(d):
        return []
    out = []
    for name in sorted(os.listdir(d)):
        if not name.endswith(".json"):
            continue
        try:
            out.append(load(root, kind, name[:-5]))
        except RecordError:
            continue
    return out


# ---------- 写入四类记录 ----------

def create_version(root, edl, inputs=None, solution_id=None, parent_id=None,
                   change_note="", imported=False, unknown=None):
    rec = {
        "schema": SCHEMAS["version"],
        "kind": "version",
        "id": new_id("ver"),
        "created_at": _now(),
        "solution_id": solution_id,
        "parent_id": parent_id,
        "change_note": change_note,
        "edl": edl,
        "edl_sha256": digest(edl),
        "inputs": inputs or [],
        "event_refs": [],
        "origin": {"kind": "import" if imported else "run",
                   "unknown": sorted(unknown or [])},
    }
    return _save(root, "version", rec)


def create_run(root, version_id, status="succeeded", output=None, qc=None,
               manifest=None, environment=None, error=None):
    rec = {
        "schema": SCHEMAS["render_run"],
        "kind": "render_run",
        "id": new_id("run"),
        "created_at": _now(),
        "version_id": version_id,
        "status": status,
        "environment": environment or {},
        "output": output,
        "qc": qc,
        "manifest": manifest,
        "error": error,
    }
    return _save(root, "render_run", rec)


def approve_output(root, run_id, by, note="", decision="approved"):
    run = load(root, "render_run", run_id)
    if run.get("status") != "succeeded" or not (run.get("output") or {}).get("sha256"):
        raise RecordError("只能审批渲染成功的成片；这次运行没有产物摘要")
    rec = {
        "schema": SCHEMAS["approval"],
        "kind": "approval",
        "id": new_id("apr"),
        "created_at": _now(),
        "decision": decision,
        "scope": "output",
        "target": {"kind": "render_run", "run_id": run_id,
                   "version_id": run["version_id"],
                   "output_sha256": run["output"]["sha256"]},
        "by": by,
        "note": note,
    }
    return _save(root, "approval", rec)


def approve_script(root, version_id, by, note="", decision="approved"):
    ver = load(root, "version", version_id)
    rec = {
        "schema": SCHEMAS["approval"],
        "kind": "approval",
        "id": new_id("apr"),
        "created_at": _now(),
        "decision": decision,
        "scope": "script",
        "target": {"kind": "version", "version_id": version_id,
                   "edl_sha256": ver["edl_sha256"]},
        "by": by,
        "note": note,
    }
    return _save(root, "approval", rec)


def matching_output_approval(root, run):
    sha = (run.get("output") or {}).get("sha256")
    if not sha:
        return None
    for a in list_records(root, "approval"):
        t = a.get("target") or {}
        if (a.get("scope") == "output" and a.get("decision") == "approved"
                and t.get("run_id") == run["id"] and t.get("output_sha256") == sha):
            return a
    return None


def deliver(root, run_id, by, channel="", note=""):
    run = load(root, "render_run", run_id)
    if run.get("status") != "succeeded" or not (run.get("output") or {}).get("sha256"):
        raise DeliveryRefused("这次渲染没有可用产物，不能交付")
    approval = matching_output_approval(root, run)
    # 审批之后成片被改过 / 被删掉，都不许交付：交付的是文件，不是记录
    path = (run.get("output") or {}).get("path")
    if path:
        path = path if os.path.isabs(path) else os.path.join(os.path.abspath(root), path)
        if not os.path.isfile(path):
            raise DeliveryRefused("拒绝交付：成片文件不在了，无法确认交付内容")
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() != run["output"]["sha256"]:
            raise DeliveryRefused("拒绝交付：成片在审批后被改动过（摘要不一致）")
    if not approval:
        raise DeliveryRefused(
            "拒绝交付：没有与本次成片摘要匹配的「成片审批」。\n"
            "  别的版本（或另一次渲染）的审批不能用于这一次交付；"
            "请先执行 cutnow approve run %s --by <审批人>。" % run_id)
    rec = {
        "schema": SCHEMAS["delivery"],
        "kind": "delivery",
        "id": new_id("dlv"),
        "created_at": _now(),
        "version_id": run["version_id"],
        "run_id": run_id,
        "output_sha256": run["output"]["sha256"],
        "output_path": run["output"].get("path"),
        "approval_id": approval["id"],
        "by": by,
        "channel": channel,
        "note": note,
    }
    return _save(root, "delivery", rec)


# ---------- 查询 / 审计 ----------

def latest_version_id(root, solution_id=None):
    versions = list_records(root, "version")
    if solution_id:
        versions = [v for v in versions if v.get("solution_id") == solution_id]
    versions.sort(key=lambda v: (v.get("seq") or 0, v["id"]))
    return versions[-1]["id"] if versions else None


def audit(root, delivery_id):
    """从交付追到版本/渲染/审批，逐条校验摘要与引用一致性。"""
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "status": "ok" if ok else "broken", "detail": detail})

    try:
        delivery = load(root, "delivery", delivery_id)
    except RecordError as e:
        return {"conclusion": "broken", "checks": [{"name": "delivery", "status": "broken", "detail": str(e)}]}

    try:
        version = load(root, "version", delivery["version_id"])
        run = load(root, "render_run", delivery["run_id"])
        approval = load(root, "approval", delivery["approval_id"])
    except RecordError as e:
        add("chain", False, str(e))
        return {"conclusion": "broken", "checks": checks, "delivery": delivery}

    add("delivery.sha", True, delivery.get("record_sha256", ""))
    add("version.sha", version.get("edl_sha256") == digest(version.get("edl")),
        version.get("edl_sha256", ""))
    add("run.version", run.get("version_id") == version["id"], run.get("version_id", ""))
    add("delivery.run", delivery.get("run_id") == run["id"], delivery.get("run_id", ""))
    out_sha = (run.get("output") or {}).get("sha256")
    add("delivery.output", delivery.get("output_sha256") == out_sha,
        "交付摘要必须等于此次渲染产物摘要")
    target = approval.get("target") or {}
    add("approval.scope", approval.get("scope") == "output", approval.get("scope", ""))
    add("approval.run", target.get("run_id") == run["id"], target.get("run_id", ""))
    add("approval.output", target.get("output_sha256") == out_sha,
        "审批绑定的成片必须就是交付的成片")

    path = delivery.get("output_path")
    if path and not os.path.isabs(path):
        path = os.path.join(os.path.abspath(root), path)
    if path and os.path.isfile(path):
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        add("artifact", h.hexdigest() == out_sha, "交付文件当前摘要")
    else:
        add("artifact", False, "交付文件不在了，只能核对记录链")

    ledger_ok = True
    ledger_path = os.path.join(_base(root), LEDGER)
    if os.path.isfile(ledger_path):
        seen = {}
        with open(ledger_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    ledger_ok = False
                    continue
                seen[e.get("id")] = e.get("sha256")
        for rec in (delivery, version, run, approval):
            ledger_ok = ledger_ok and seen.get(rec["id"]) == rec.get("record_sha256")
        add("ledger", ledger_ok, "账本摘要与记录一致")
    else:
        add("ledger", False, "缺少 ledger.jsonl")

    conclusion = "ok" if all(c["status"] == "ok" for c in checks) else "broken"
    return {"conclusion": conclusion, "checks": checks,
            "delivery": delivery, "version": version, "run": run, "approval": approval}
