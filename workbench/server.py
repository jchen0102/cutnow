#!/usr/bin/env python3
"""vcut 工作台：本地 HTTP 服务，把 EDL 画成可操作的时间线。无第三方依赖。"""
import json, os, re, subprocess, sys, threading, time, mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from core import edl as E, render as R, ffmpeg as F

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


def state():
    e, r = edl(), recipe()
    repl = read_json(REPL, {}) or {}
    vers = read_json(VERS, []) or []
    cur_edl = os.path.basename(edl_path())
    clips = []
    for i, c in enumerate(e.get("video", [])):
        clips.append({**c, "index": i, "replaced": str(i) in repl,
                      "thumb": f"/api/thumb?i={i}"})
    return {
        "title": r.get("title", "未命名"),
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
        res = R.render(e, os.path.join(ROOT, "out", "work"), out, replacements=repl)
        vers = read_json(VERS, []) or []
        vers.append({"id": f"v{n}", "file": out_rel, "url": f"/media/{os.path.basename(out_rel)}",
                     "sha": res["sha256"][:12], "bytes": res["bytes"],
                     "at": time.strftime("%H:%M:%S"), "label": label or f"v{n}",
                     "replaced": sorted(repl.keys())})
        write_json(VERS, vers)
        STATE["job"] = {"status": "done", "log": f"{n} 完成", "file": out_rel, "version": f"v{n}",
                        "elapsed": round(time.time() - STATE["job"]["started"], 1)}
    except Exception as ex:
        STATE["job"] = {"status": "error", "log": str(ex)[-600:], "file": None}


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
