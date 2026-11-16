"""复现凭据（manifest）：把「同一份 EDL 渲染出同一份字节」变成可验证的承诺。

manifest 记录六类身份：引擎与环境、解法、输入素材、EDL、成片、每步参数。
`cutnow verify` 逐项重算，给出三档结论：

  ok      全部一致，产物可按 manifest 复现
  drift   产物一致，但环境（引擎 / Python / ffmpeg / 字体）已变，未来可能漂移
  broken  输入、EDL 或成片本身已变 —— 复现承诺失效

约定：
  * 路径优先记为「相对 project.root」，因此凭据可随项目目录整体移动；
  * 跨机器校验时，素材与字体仍需存在，否则记为 broken / drift；
  * quick 摘要 = sha256(size + 首 4MiB + 末 4MiB)，用于超大素材，方法记在 hash_mode 里。
"""
import hashlib
import json
import os
import platform
import subprocess
import time

from . import __version__
from . import config as C

SCHEMA = "cutnow.manifest/1"
MB = 1 << 20
FULL_LIMIT = 512 * MB
QUICK_SPAN = 4 * MB


# ---------- 摘要 ----------

def _sha256_file(path, chunk=MB):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _quick_digest(path):
    size = os.path.getsize(path)
    h = hashlib.sha256()
    h.update(str(size).encode("ascii"))
    with open(path, "rb") as fh:
        h.update(fh.read(QUICK_SPAN))
        if size > QUICK_SPAN:
            fh.seek(max(0, size - QUICK_SPAN))
            h.update(fh.read(QUICK_SPAN))
    return h.hexdigest()


def digest(obj):
    """对象摘要：键序无关、空白无关，用于 EDL / 参数。"""
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def identity(path, root=None, mode="auto"):
    """文件身份：项目内记相对路径，项目外记绝对路径。"""
    abs_path = os.path.abspath(path)
    size = os.path.getsize(abs_path)
    use = mode
    if use not in ("full", "quick"):
        use = "full" if size <= FULL_LIMIT else "quick"
    sha = _sha256_file(abs_path) if use == "full" else _quick_digest(abs_path)
    shown = abs_path
    if root:
        base = os.path.abspath(root)
        if abs_path.startswith(base + os.sep):
            shown = os.path.relpath(abs_path, base)
    return {"path": shown, "bytes": size, "sha256": sha, "hash_mode": use}


def _resolve(path, root):
    if not path:
        return ""
    return path if os.path.isabs(path) else os.path.join(root, path)


# ---------- 环境 ----------

def engine_identity():
    return {
        "name": "cutnow",
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
    }


def ffmpeg_identity():
    try:
        exe = C.ffmpeg()
    except Exception:
        return {"path": "", "version": ""}
    version = ""
    try:
        out = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=10).stdout
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        version = lines[0] if lines else ""
    except Exception:
        pass
    return {"path": exe, "version": version}


def font_identity():
    try:
        from .render import font
        path = font()
    except Exception:
        path = ""
    if not path:
        return {"path": "", "bytes": 0, "sha256": ""}
    return {"path": path, "bytes": os.path.getsize(path), "sha256": _sha256_file(path)}


# ---------- 构建 / 读写 ----------

def build(solution_path, solution, inputs, steps, edl, edl_path, output, root,
          capabilities=None, warnings=None):
    base = os.path.abspath(root)
    records = []
    for key, path in (inputs or {}).items():
        if not path:
            continue
        rec = identity(path, base)
        rec["id"] = key
        records.append(rec)
    return {
        "schema": SCHEMA,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "project": {"root": base},
        "engine": engine_identity(),
        "runtime": {"ffmpeg": ffmpeg_identity(), "font": font_identity()},
        "solution": {
            "id": solution.get("id"),
            "file": identity(solution_path, base),
            "sha256": digest(solution),
        },
        "capabilities": sorted(capabilities or []),
        "inputs": records,
        "steps": [
            {"id": s.get("id"), "op": s.get("op"),
             "params_sha256": digest(s.get("params") or {}),
             "skipped": s.get("skipped") or None}
            for s in (steps or [])
        ],
        "edl": {
            "path": identity(edl_path, base)["path"] if edl_path else "",
            "sha256": digest(edl),
            "clips": len(edl.get("video") or []),
            "total": edl.get("total"),
        },
        "output": identity(output, base) if output else None,
        "warnings": sorted(warnings or []),
    }


def write(manifest, path):
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return path


def load(path):
    with open(path, encoding="utf-8") as fh:
        m = json.load(fh)
    if m.get("schema") != SCHEMA:
        raise ValueError(f"不认识的凭据版本 {m.get('schema')!r}（期望 {SCHEMA}）")
    return m


# ---------- 校验 ----------

def verify(manifest_path):
    """重算并逐项比对。返回 {conclusion, checks, manifest}。

    conclusion: ok / drift / broken；checks 每项含 name / status / expected / actual / detail。
    """
    m = load(manifest_path)
    root = (m.get("project") or {}).get("root") or os.path.dirname(os.path.abspath(manifest_path))
    checks = []

    def add(name, status, expected=None, actual=None, detail=""):
        checks.append({"name": name, "status": status,
                       "expected": expected, "actual": actual, "detail": detail})

    # 环境：漂移不等于产物变了，但会威胁未来的复现
    eng, cur = m.get("engine") or {}, engine_identity()
    for key in ("version", "python", "platform"):
        same = eng.get(key) == cur.get(key)
        add(f"engine.{key}", "ok" if same else "drift", eng.get(key), cur.get(key),
            "" if same else "环境已变，重渲可能不再逐字节一致")
    old_ff, cur_ff = (m.get("runtime") or {}).get("ffmpeg") or {}, ffmpeg_identity()
    add("runtime.ffmpeg", "ok" if old_ff.get("version") == cur_ff.get("version") else "drift",
        old_ff.get("version"), cur_ff.get("version"))
    old_font, cur_font = (m.get("runtime") or {}).get("font") or {}, font_identity()
    add("runtime.font", "ok" if old_font.get("sha256") == cur_font.get("sha256") else "drift",
        old_font.get("path"), cur_font.get("path"), "" if old_font.get("sha256") == cur_font.get("sha256") else "字体不同，字幕可能变")

    # 输入素材：变了就意味着这不是同一份输入
    for item in m.get("inputs") or []:
        path = _resolve(item.get("path"), root)
        if not path or not os.path.isfile(path):
            add(f"input.{item.get('id')}", "broken", item.get("path"), "缺失", "素材不在了")
            continue
        got = identity(path, root, item.get("hash_mode") or "auto")
        same = got["sha256"] == item.get("sha256")
        add(f"input.{item.get('id')}", "ok" if same else "broken",
            item.get("sha256"), got["sha256"], "" if same else "素材内容已变")

    # 解法：改了配方说明这是一次新运行，但产物本身还在
    sol = m.get("solution") or {}
    sol_file = _resolve((sol.get("file") or {}).get("path"), root)
    if not sol_file or not os.path.isfile(sol_file):
        add("solution", "drift", (sol.get("file") or {}).get("path"), "缺失", "解法文件不在了")
    else:
        got = identity(sol_file, root)
        same = got["sha256"] == (sol.get("file") or {}).get("sha256")
        add("solution", "ok" if same else "drift", (sol.get("file") or {}).get("sha256"),
            got["sha256"], "" if same else "解法已被修改")

    # EDL：契约的核心，变了就等于换了片子
    edl = m.get("edl") or {}
    edl_path = _resolve(edl.get("path"), root)
    if not edl_path or not os.path.isfile(edl_path):
        add("edl", "broken", edl.get("path"), "缺失", "EDL 不在了，无法证明剪法")
    else:
        try:
            with open(edl_path, encoding="utf-8") as fh:
                got = digest(json.load(fh))
        except Exception as e:
            got = f"解析失败：{e}"
        same = got == edl.get("sha256")
        add("edl", "ok" if same else "broken", edl.get("sha256"), got,
            "" if same else "EDL 内容已变，剪法不再是同一份")

    # 成片：最终承诺
    out = m.get("output") or {}
    out_path = _resolve(out.get("path"), root)
    if not out_path or not os.path.isfile(out_path):
        add("output", "broken", out.get("path"), "缺失", "成片不在了")
    else:
        got = _sha256_file(out_path)
        same = got == out.get("sha256")
        add("output", "ok" if same else "broken", out.get("sha256"), got,
            "" if same else "成片字节已变，复现失败")

    statuses = [c["status"] for c in checks]
    conclusion = "broken" if "broken" in statuses else ("drift" if "drift" in statuses else "ok")
    return {
        "conclusion": conclusion,
        "counts": {s: statuses.count(s) for s in ("ok", "drift", "broken")},
        "checks": checks,
        "manifest": m,
        "path": os.path.abspath(manifest_path),
    }
