#!/usr/bin/env python3
"""cutnow 工作台：本地 HTTP 服务，把 EDL 画成可操作的时间线。无第三方依赖。"""
import json, os, re, subprocess, sys, threading, time, mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from core import edl as E, render as R, ffmpeg as F, qc as QC
from core import records as REC

RECIPE = os.path.join(ROOT, "recipes", "mj_highlight.json")
EDL_DEFAULT = os.path.join(ROOT, "out", "edl_mj-highlight.json")
CURRENT = os.path.join(ROOT, "out", "current.json")


def edl_path():
    cur = read_json(CURRENT, {}) or {}
    p = cur.get("edl")
    if p:
        fp = os.path.join(ROOT, p) if not os.path.isabs(p) else p
        if os.path.exists(fp):
            return fp
    return EDL_DEFAULT
REPL = os.path.join(ROOT, "out", "replacements.json")
VERS = os.path.join(ROOT, "out", "versions.json")
THUMBS = os.path.join(ROOT, "out", "thumbs")

STATE = {"job": {"status": "idle", "log": "", "file": None, "started": None}}
LOCK = threading.Lock()


def read_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def write_json(p, obj):
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def recipe():
    return read_json(RECIPE, {})


def decisions():
    """把一次解法运行的判断摊开：准入结论、选段结果、每步耗时、批量结果。"""
    import glob
    runs = sorted(glob.glob(os.path.join(ROOT, "out", "run_*.json")), key=os.path.getmtime, reverse=True)
    run = read_json(runs[0], {}) or {} if runs else {}
    steps = run.get("steps") or []
    pre = next((st.get("result") for st in steps if st.get("op") == "qc.source"), None)
    sel = next((st.get("result") for st in steps if str(st.get("op", "")).startswith("select.")), None)
    batch = read_json(os.path.join(ROOT, "out", "batch", "rows.json"), []) or []
    return {"solution": run.get("solution"), "steps": steps, "precheck": pre,
            "selection": sel, "batch": batch, "edl": os.path.basename(edl_path()),
            "source": (os.path.basename(str(runs[0])) if runs else None)}


def edl():
    return read_json(edl_path(), {})


def bpm():
    r = read_json(os.path.join(ROOT, "out", "beats.json"), {})
    return float(r.get("bpm") or 136.0)


def src_path():
    rec = recipe()
    a = next(x for x in rec["assets"] if x["id"] == "src")
    return os.path.join(ROOT, a["path"])


def edl_options():
    """out/ 下所有可切的 EDL，按修改时间倒序。"""
    rows = []
    for name in os.listdir(os.path.join(ROOT, "out")):
        if not (name.startswith("edl_") and name.endswith(".json")):
            continue
        p = os.path.join(ROOT, "out", name)
        try:
            e = read_json(p, {}) or {}
        except Exception:
            continue
        rows.append({"file": name, "id": (e.get("id") or name[4:-5]),
                     "total": e.get("total"), "clips": len(e.get("video") or []),
                     "mtime": os.path.getmtime(p)})
    rows.sort(key=lambda r: -r["mtime"])
    return rows


def current_source():
    try:
        e = edl()
        return next((a.get("path") for a in e.get("assets", []) if a.get("id") == "src"), "")
    except Exception:
        return ""


def state():
    e, r = edl(), recipe()
    repl = read_json(REPL, {}) or {}
    vers = read_json(VERS, []) or []
    cur_edl = os.path.basename(edl_path())
    cur_meta = read_json(CURRENT, {}) or {}
    cur_name = (cur_meta.get("solution") or "").replace("-", " ")
    clips = []
    for i, c in enumerate(e.get("video", [])):
        clips.append({**c, "index": i, "replaced": str(i) in repl,
                      "thumb": f"/api/thumb?i={i}"})
    return {
        "title": cur_name or r.get("title") or "未命名",
        "edl": cur_edl,
        "id": r.get("id"),
        "bpm": bpm(),
        "prompt": (r.get("replace") or {}).get("prompt", ""),
        "clips": clips,
        "ops": e.get("ops", []),
        "total": e.get("total"),
        "output": e.get("output"),
        "subs": e.get("subs", []),
        "versions": vers,
        "vertical": (e.get("output") or {}).get("height", 0) > (e.get("output") or {}).get("width", 1),
        "qc": (vers[-1].get("qc") if vers else None) or STATE["job"].get("qc"),
        "solution": (read_json(CURRENT, {}) or {}).get("solution"),
        "source": current_source(),
        "edl_options": edl_options(),
        "subs_text": " / ".join(x.get("text", "") for x in (e.get("subs") or [])),
        "job": STATE["job"],
    }


def run_render(label=None):
    e = edl()
    repl_raw = read_json(REPL, {}) or {}
    repl = {int(k): os.path.join(ROOT, v) for k, v in repl_raw.items()}
    n = len(read_json(VERS, []) or []) + 1
    out_rel = f"out/v{n}.mp4"
    out = os.path.join(ROOT, out_rel)
    STATE["job"] = {"status": "running", "log": "渲染中…", "file": None, "started": time.time()}
    try:
        res = R.render(e, os.path.join(ROOT, "out", "work"), out, replacements=repl, loudnorm=-14.0)
        vers = read_json(VERS, []) or []
        entry = {"id": f"v{n}", "file": out_rel, "url": f"/media/{os.path.basename(out_rel)}",
                 "sha": res["sha256"][:12], "bytes": res["bytes"],
                 "at": time.strftime("%H:%M:%S"), "label": label or f"v{n}",
                 "replaced": sorted(repl.keys())}
        try:
            from core import manifest as MF
            ident = MF.identity(src_path(), ROOT, "quick")
            ver = REC.create_version(
                ROOT, e, solution_id=(read_json(CURRENT, {}) or {}).get("solution") or "workbench",
                inputs=[{"id": "source", "path": ident["path"],
                         "sha256": ident["sha256"], "bytes": ident["bytes"]}])
            run = REC.create_run(ROOT, ver["id"], output={"path": out_rel, "sha256": res["sha256"],
                                                         "bytes": res["bytes"]},
                                 environment={"engine": "cutnow-workbench"})
            entry["version_id"], entry["run_id"] = ver["id"], run["id"]
        except Exception as ex:
            entry["record_error"] = str(ex)[:200]
        vers.append(entry)
        try:
            # 清晰度阈值随输出高度缩放：720p 基准 15，竖版 1920 高约 2.1
            h = (e.get("output") or {}).get("height") or 720
            sharp_min = max(1.0, 15.0 * (720.0 / h) ** 2)
            report = QC.report(out, e, thresholds={"sharp_min": round(sharp_min, 2)},
                               skip_subtitles=not res.get("subs_burned", True))
        except Exception as qex:
            report = {"pass": None, "failed": [], "error": str(qex)[:200]}
        entry["qc"] = report
        write_json(VERS, vers)
        STATE["job"] = {"status": "done", "log": f"{n} 完成", "file": out_rel, "version": f"v{n}",
                        "elapsed": round(time.time() - STATE["job"]["started"], 1),
                        "qc": entry.get("qc")}
    except Exception as ex:
        STATE["job"] = {"status": "error", "log": str(ex)[-600:], "file": None}


def records_view():
    """审批台：每次渲染一行，回答「这版谁审的、能不能发」。"""
    vers = REC.list_records(ROOT, "version")
    runs = REC.list_records(ROOT, "render_run")
    dlvs = REC.list_records(ROOT, "delivery")
    labels = {v.get("version_id"): v.get("id")
              for v in (read_json(VERS, []) or []) if v.get("version_id")}
    items = []
    for r in sorted(runs, key=lambda x: x.get("seq", 0), reverse=True):
        ver = next((v for v in vers if v["id"] == r.get("version_id")), None)
        apr = REC.matching_output_approval(ROOT, r)
        dlv = next((d for d in dlvs if d.get("run_id") == r["id"]), None)
        status = "delivered" if dlv else ("approved" if apr else "unapproved")
        items.append({
            "run_id": r["id"],
            "version_id": r.get("version_id"),
            "label": labels.get(r.get("version_id")) or (ver or {}).get("change_note") or r["id"][-6:],
            "at": (r.get("created_at") or "")[11:19],
            "sha": ((r.get("output") or {}).get("sha256") or "")[:12],
            "bytes": (r.get("output") or {}).get("bytes") or 0,
            "status": status,
            "approver": (apr or {}).get("by"),
            "delivery": (dlv or {}).get("id"),
        })
    return {"items": items}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype=None, download=None):
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        size = os.path.getsize(path)
        ctype = ctype or mimetypes.guess_type(path)[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        code = 200
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
                code = 206
        with open(path, "rb") as fh:
            fh.seek(start)
            data = fh.read(end - start + 1)
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Access-Control-Allow-Origin", "*")
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        p = u.path
        if p == "/":
            return self._file(os.path.join(HERE, "static", "index.html"), "text/html; charset=utf-8")
        if p.startswith("/static/"):
            return self._file(os.path.join(HERE, "static", p[8:]))
        if p == "/favicon.ico":
            return self._send(204, b"")
        if p == "/api/decisions":
            return self._send(200, decisions())
        if p == "/api/state":
            return self._send(200, state())
        if p == "/api/records":
            return self._send(200, records_view())
        if p == "/api/thumb":
            i = int((q.get("i") or ["0"])[0])
            e = edl(); c = e["video"][i]
            name = f"c{i}_{int(c['start']*10)}.jpg"
            fp = os.path.join(THUMBS, name)
            if not os.path.exists(fp):
                subprocess.run([F.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                                "-ss", f"{c['start']:.2f}", "-i", src_path(), "-frames:v", "1",
                                "-vf", "scale=240:-2", fp], capture_output=True)
            return self._file(fp, "image/jpeg")
        if p == "/api/poster":
            vers = read_json(VERS, []) or []
            if not vers:
                return self._send(404, {"error": "no version"})
            fp = os.path.join(ROOT, "out", "thumbs", "poster.jpg")
            if not os.path.exists(fp):
                subprocess.run([F.ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                                "-ss", "7.2", "-i", os.path.join(ROOT, vers[-1]["file"]),
                                "-frames:v", "1", "-vf", "scale=960:540", fp], capture_output=True)
            return self._file(fp, "image/jpeg")
        if p.startswith("/media/"):
            return self._file(os.path.join(ROOT, "out", os.path.basename(p)))
        return self._send(404, {"error": "no route"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if u.path == "/api/clip":
            e = edl()
            i = int(body["index"])
            if i >= len(e["video"]):
                return self._send(400, {"error": "bad index"})
            c = e["video"][i]
            if "beats" in body:
                c["beats"] = max(2, min(int(body["beats"]), 24))
            if "start" in body:
                c["start"] = round(float(body["start"]), 3)
            E.clamp_clip(e, i, F.probe(src_path())["duration"])
            E.retime(e, bpm())
            E.save(e, edl_path())
            return self._send(200, state())
        if u.path == "/api/switch":
            name = str(body.get("edl") or "")
            path = os.path.join(ROOT, "out", os.path.basename(name))
            if not (name.startswith("edl_") and os.path.isfile(path)):
                return self._send(400, {"error": "没有这份 EDL"})
            sol = os.path.basename(name)[4:-5]
            write_json(CURRENT, {"edl": f"out/{os.path.basename(name)}", "solution": sol})
            return self._send(200, state())
        if u.path == "/api/aspect":
            e = edl()
            vertical = bool(body.get("vertical"))
            e["output"]["width"], e["output"]["height"] = (1080, 1920) if vertical else (1280, 720)
            E.save(e, edl_path())
            return self._send(200, state())
        if u.path == "/api/subs":
            from core import builtin_ops  # noqa: F401
            from core import ops
            e = edl()
            raw = (body.get("text") or "").strip()
            lines = [x.strip() for x in re.split(r"[\n/|、,，]+", raw) if x.strip()] if raw else []
            ctx = {"root": ROOT, "edl": e, "analysis": {"bpm": bpm()}, "inputs": {}, "log": []}
            ops.get("subtitle.by_beat")(ctx, {"lines": lines, "beats_per_line": int(body.get("beats_per_line") or 6)})
            E.save(e, edl_path())
            return self._send(200, state())
        if u.path == "/api/reselect":
            from core import builtin_ops  # noqa: F401
            from core import ops
            e = edl()
            cur = read_json(CURRENT, {}) or {}
            sol_path = os.path.join(ROOT, "solutions", f"{cur.get('solution') or 'film-montage'}.solution.json")
            sol = read_json(sol_path, {}) or {}
            src = e["assets"][0]["path"] if e.get("assets") else None
            inputs = {"source": src, "music": next((a["path"] for a in e.get("assets", []) if a["id"] == "music"), None)}
            ctx = {"root": ROOT, "edl": e, "solution": sol, "inputs": inputs, "log": []}
            try:
                ops.get("analyze.standard")(ctx, {"features": "auto", "scene_threshold": 0.25})
                target = float(body.get("target_seconds") or e.get("total") or 12)
                ops.get("select.auto")(ctx, {"target_seconds": target})
            except Exception as ex:
                return self._send(500, {"error": f"重新选段失败：{ex}"})
            e["subs"] = []          # 旧字幕时间轴作废
            E.save(e, edl_path())
            return self._send(200, state())
        if u.path == "/api/approve":
            by = (body.get("by") or "工作台").strip() or "工作台"
            try:
                REC.approve_output(ROOT, body.get("run_id"), by=by, note=body.get("note") or "")
            except REC.RecordError as ex:
                return self._send(400, {"error": str(ex)})
            return self._send(200, records_view())
        if u.path == "/api/deliver":
            by = (body.get("by") or "工作台").strip() or "工作台"
            try:
                REC.deliver(ROOT, body.get("run_id"), by=by)
            except REC.DeliveryRefused as ex:
                return self._send(409, {"error": str(ex)})
            return self._send(200, records_view())
        if u.path == "/api/render":
            with LOCK:
                if STATE["job"]["status"] == "running":
                    return self._send(409, {"error": "已有渲染在跑"})
                threading.Thread(target=run_render, args=(body.get("label"),), daemon=True).start()
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "no route"})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    os.makedirs(THUMBS, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"workbench → http://127.0.0.1:{port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
