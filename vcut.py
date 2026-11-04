#!/usr/bin/env python3
"""vcut —— 自动剪辑流水线：probe / scenes / beats / plan / render / run"""
import argparse, json, os, subprocess, sys, time
from core import analyze as A, plan as P, render as R
from core import ffmpeg as F

HERE = os.path.dirname(os.path.abspath(__file__))

def load(p): return json.load(open(p, encoding="utf-8"))
def dump(o, p):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def get_asset(rec, aid):
    return next(a["path"] for a in rec["assets"] if a["id"] == aid)

def ensure_features(video, out, interval=0.5):
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        return out
    exe = os.path.join(HERE, "tools", "features")
    subprocess.run([exe, video, out, str(interval)], check=True)
    return out

def cmd_run(args):
    t0 = time.time()
    rec = load(args.recipe)
    src, mus = get_asset(rec, "src"), get_asset(rec, "music")
    os.chdir(HERE)

    print(f"[1/5] probe {src}")
    info = F.probe(src)
    print(f"      {info['width']}x{info['height']} {info['fps']}fps {info['duration']}s")

    print("[2/5] 镜头切分 + 逐帧特征")
    sc = A.scenes(src, rec.get("scene_threshold", 0.3))
    feat_path = ensure_features(src, os.path.join(HERE, "out", "features_jam.jsonl"))
    rows = A.load_features(feat_path)
    print(f"      {len(sc)} 个镜头, {len(rows)} 帧特征")

    print("[3/5] 节拍 + 副歌定位")
    x = A.decode_audio(mus)
    bpm, beats = A.estimate_beat(x, 22050)
    chorus = A.loudest_window(x, 22050, rec["target_seconds"] + 4)
    music_info = {"bpm": bpm, "beats": [round(float(b), 3) for b in beats],
                  "chorus_start": round(chorus, 3), "duration": len(x) / 22050}
    print(f"      {bpm} BPM, 副歌窗口 {chorus:.1f}s")

    print("[4/5] 规划 EDL")
    edl = P.build_edl(rec, sc, rows, music_info)
    edl_path = os.path.join(HERE, "out", f"edl_{rec['id']}.json")
    dump(edl, edl_path)
    print(f"      {len(edl['video'])} 段 / {edl['total']}s → {edl_path}")
    for c in edl["video"]:
        print(f"      {c['at']:>6.2f}s  ←  {c['start']:>7.2f}s  {c['dur']:.2f}s  {c['role']:<4} {c['beats']:>2}拍 score={c['score']}")

    print("[5/5] 渲染")
    out = args.out or os.path.join(HERE, "out", f"{rec['id']}{args.suffix}.mp4")
    res = R.render(edl, os.path.join(HERE, "out", "work"), out,
                   crf=args.crf, preset=args.preset, threads=args.threads)
    print(f"      {res['path']}  {res['bytes']/1e6:.1f}MB  sha256={res['sha256'][:16]}…")
    print(f"完成，用时 {time.time()-t0:.1f}s")
    if args.report:
        dump({"recipe": rec, "source": info, "music": {k: v for k, v in music_info.items() if k != "beats"},
              "edl": edl_path, "render": res, "scenes": len(sc), "features": len(rows)},
             os.path.join(HERE, "out", "report.json"))
    return 0

def cmd_replace(args):
    """导出待替换镜头包 / 回填外部模型产出的片段。"""
    import shutil
    from core import ffmpeg as FF
    here = HERE
    rec = load(args.recipe)
    edl = load(os.path.join(here, "out", f"edl_{rec['id']}.json"))
    rep_dir = os.path.join(here, "out", "replace")

    if args.action == "export":
        os.makedirs(rep_dir, exist_ok=True)
        src = os.path.join(here, get_asset(rec, "src"))
        shots = []
        for i, c in enumerate(edl["video"]):
            out = os.path.join(rep_dir, f"shot_{i:02d}.mp4")
            FF.run(["-y", "-loglevel", "error", "-ss", f"{c['start']:.3f}", "-i", src,
                    "-t", f"{c['dur']:.3f}", "-an", "-c:v", "libx264", "-crf", "16",
                    "-preset", "veryfast", "-pix_fmt", "yuv420p", out])
            shots.append({"index": i, "source_start": c["start"], "duration": c["dur"],
                          "file": os.path.relpath(out, here), "role": c.get("role")})
        spec = {
            "edl": os.path.relpath(os.path.join(here, "out", f"edl_{rec['id']}.json"), here),
            "reference_image": rec.get("replace", {}).get("ref"),
            "prompt": rec.get("replace", {}).get("prompt", ""),
            "return_spec": {"aspect": "16:9", "min_duration": max(c["dur"] for c in edl["video"]),
                            "format": "mp4 / h264", "note": "时长可长于目标，回填时会裁到拍点长度"},
            "shots": shots,
        }
        dump(spec, os.path.join(rep_dir, "shots.json"))
        print(f"导出 {len(shots)} 个镜头 → {rep_dir}")
        for s_ in shots:
            print(f"  shot_{s_['index']:02d}  {s_['source_start']:>7.2f}s  {s_['duration']:.2f}s  {s_['role']}")
        print(f"提示词：{spec['prompt']}")
        return 0

    # fill
    idx = args.index
    dst = os.path.join(rep_dir, f"filled_{idx:02d}.mp4")
    os.makedirs(rep_dir, exist_ok=True)
    shutil.copyfile(args.file, dst)
    reg_path = os.path.join(here, "out", "replacements.json")
    reg = load(reg_path) if os.path.exists(reg_path) else {}
    reg[str(idx)] = os.path.relpath(dst, here)
    dump(reg, reg_path)
    print(f"回填 clip {idx} ← {args.file}")
    print(f"当前已回填：{sorted(map(int, reg))}")

    if not args.render:
        return 0
    repl = {int(k): os.path.join(here, v) for k, v in reg.items()}
    out = args.out or os.path.join(here, "out", f"{rec['id']}-replaced.mp4")
    from core import render as R
    res = R.render(edl, os.path.join(here, "out", "work"), out, replacements=repl)
    print(f"重渲完成 {res['path']}  {res['bytes']/1e6:.1f}MB  sha={res['sha256'][:12]}…")
    return 0


def _solutions_dir():
    return os.path.join(HERE, "solutions")


def _resolve_solution(name):
    """接受解法名（可缩写）或路径。"""
    if os.path.sep in name or name.endswith(".json"):
        return name if os.path.isabs(name) else os.path.join(HERE, name)
    import glob
    for p in sorted(glob.glob(os.path.join(_solutions_dir(), "*.solution.json"))):
        base = os.path.basename(p).replace(".solution.json", "")
        if name in (base, base.split("-")[0]):
            return p
    raise SystemExit(f"找不到解法 {name!r}；可用：{', '.join(_solution_names())}")


def _solution_names():
    import glob
    return [os.path.basename(p).replace(".solution.json", "")
            for p in sorted(glob.glob(os.path.join(_solutions_dir(), "*.solution.json")))]


def cmd_list(args):
    from core import ops, builtin_ops  # noqa: F401
    print("解法：")
    for p in sorted(__import__("glob").glob(os.path.join(_solutions_dir(), "*.solution.json"))):
        try:
            from core import solution as SOL
            sol = SOL.load(p, ops.OPS)
            print(f"  {sol['id']:18} {sol['name']:12} {sol.get('output_kind','mp4'):9} {len(sol['steps'])} 步")
        except Exception as e:
            print(f"  ! {os.path.basename(p)}  {e}")
    print(f"\n算子 {len(ops.OPS)} 个：{', '.join(ops.names())}")
    return 0


def cmd_new(args):
    name = args.name
    path = os.path.join(_solutions_dir(), f"{name}.solution.json")
    if os.path.exists(path) and not args.force:
        raise SystemExit(f"{path} 已存在（加 --force 覆盖）")
    tpl = {
        "id": name, "name": name, "description": "一句话说明这个解法做什么",
        "inputs": {"source": {"type": "video", "required": True},
                   "music": {"type": "audio", "required": True}},
        "output": {"width": 1280, "height": 720, "fps": 30, "container": "mp4"},
        "output_kind": "mp4",
        "steps": [
            {"id": "analyze", "op": "analyze.standard", "params": {"features": "auto"}},
            {"id": "shots", "op": "select.action", "gate": "confirm", "params": {"target_seconds": 12}},
            {"id": "audio", "op": "audio.chorus", "params": {"in": "auto"}},
            {"id": "cards", "op": "card.bookends", "params": {"title": name.upper(), "end": "vcut"}},
            {"id": "normalize", "op": "audio.normalize", "params": {"i": -14.0}},
            {"id": "render", "op": "render.edl", "params": {"out": f"out/{name}.mp4"}},
            {"id": "qc", "op": "qc.report", "params": {}},
        ],
        "outputs": ["mp4"], "capabilities": [],
    }
    os.makedirs(_solutions_dir(), exist_ok=True)
    json.dump(tpl, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"已创建 {path}\n下一步：python -m vcut solution validate {path}")
    return 0


def cmd_serve(args):
    import subprocess
    script = os.path.join(HERE, "workbench", "server.py")
    if not os.path.exists(script):
        raise SystemExit("workbench 不在这个发行版里（见 contrib/）")
    print(f"http://127.0.0.1:{args.port}")
    return subprocess.call([sys.executable, script, str(args.port)])


def cmd_run_solution(args):
    from core import ops, builtin_ops  # noqa: F401
    from core import solution as SOL, runner
    path = _resolve_solution(args.solution)
    sol = SOL.load(path, ops.OPS)
    overrides = {}
    if args.source:
        overrides["source"] = args.source
    if args.music:
        overrides["music"] = args.music
    if args.out:
        for st in sol["steps"]:
            if st["op"] == "render.edl":
                st["params"]["out"] = args.out
    print(f"解法 {sol['id']} · {sol['name']} · {len(sol['steps'])} 步")
    os.chdir(HERE)
    ctx = runner.run(sol, HERE, overrides=overrides, yes=args.yes, on_log=print)
    edl_path = os.path.join(HERE, "out", f"edl_{sol['id']}.json")
    os.makedirs(os.path.dirname(edl_path), exist_ok=True)
    json.dump(ctx["edl"], open(edl_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump({"edl": os.path.relpath(edl_path, HERE), "solution": sol["id"]},
              open(os.path.join(HERE, "out", "current.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if args.json:
        print(json.dumps({"solution": sol["id"], "steps": ctx["log"]}, ensure_ascii=False))
    for r in ctx.get("renders", []):
        print(f"成片 {r['file']}  {r['bytes']/1e6:.1f}MB  sha256={r['sha256']}")
    return 0


def cmd_doctor(args):
    from core import config as C
    print("vcut doctor\n")
    rows = C.doctor()
    width = max(len(r[0]) for r in rows)
    bad = 0
    for name, status, detail in rows:
        mark = {"ok": "✓", "optional": "○", "missing": "✗"}.get(status, "?")
        if status == "missing":
            bad += 1
        print(f"  {mark} {name.ljust(width)}  {detail}")
    print()
    print("全部就绪。" if bad == 0 else f"有 {bad} 项缺失，见上面提示。")
    return 0 if bad == 0 else 1


def cmd_solution(args):
    root = HERE
    os.chdir(root)
    from core import ops, builtin_ops  # noqa: F401  注册内置算子
    from core import solution as SOL, runner

    if args.action == "list":
        paths = SOL.discover([os.path.join(root, "solutions")])
        print(f"{len(paths)} 个解法：")
        for p in paths:
            try:
                sol = SOL.load(p, ops.OPS)
                print(f"  {sol['id']:16} {sol['name']:12} {sol.get('output_kind','mp4'):10} ({len(sol['steps'])} 步)")
            except SOL.SolutionError as e:
                print(f"  ! {os.path.basename(p)}  校验失败：{e}")
        print(f"\n可用算子 {len(ops.OPS)} 个：{', '.join(ops.names())}")
        return 0

    if args.action == "validate":
        try:
            sol = SOL.load(args.path, ops.OPS)
        except SOL.SolutionError as e:
            print(f"校验失败：{e}")
            return 1
        print(f"OK  {sol['id']} / {sol['name']} / {len(sol['steps'])} 步")
        for st in sol["steps"]:
            print(f"  - {st.get('id', st['op']):12} {st['op']:20} {('闸门:' + st['gate']) if st.get('gate') else ''}")
        return 0

    sol = SOL.load(args.path, ops.OPS)
    print(f"解法 {sol['id']} · {sol['name']} · {len(sol['steps'])} 步")
    overrides = {}
    for kv in (args.input or []):
        k, _, v = kv.partition("=")
        overrides[k] = v
    ctx = runner.run(sol, root, overrides=overrides, yes=args.yes,
                     allow_caps=("",) + tuple(args.allow or []), on_log=print)
    edl_path = os.path.join(root, "out", f"edl_{sol['id']}.json")
    json.dump(ctx["edl"], open(edl_path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump({"edl": os.path.relpath(edl_path, root), "solution": sol["id"], "at": time.strftime("%H:%M:%S")},
              open(os.path.join(root, "out", "current.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    log_path = os.path.join(root, "out", f"run_{sol['id']}.json")
    json.dump({"solution": sol["id"], "steps": ctx["log"]}, open(log_path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"EDL → {edl_path}\n日志 → {log_path}")
    for r in ctx.get("renders", []):
        print(f"成片 {r['file']}  {r['bytes']/1e6:.1f}MB  sha256={r['sha256']}")
    return 0


def cmd_swap(args):
    try:
        from core import swap as S
    except ImportError:
        print("本地换脸模块不随开源版发布（合规原因）。接口仍在：core/ops.py 注册一个 op 即可接入你自己的实现。")
        return 2
    r = S.swap_video(args.input, args.face, args.out,
                     scope=args.scope, max_seconds=args.seconds)
    print(f"完成 {r['path']}  {r['bytes']/1e6:.1f}MB  替换 {r['swaps']} 张脸 / {r['frames']} 帧")
    print(f"sha256={r['sha256'][:16]}…")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="vcut")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="列出解法与算子")
    ls.set_defaults(func=cmd_list)

    nw = sub.add_parser("new", help="新建一个解法骨架")
    nw.add_argument("name")
    nw.add_argument("--force", action="store_true")
    nw.set_defaults(func=cmd_new)

    sv = sub.add_parser("serve", help="启动本地工作台")
    sv.add_argument("--port", type=int, default=8799)
    sv.set_defaults(func=cmd_serve)

    r = sub.add_parser("run", help="跑一个解法")
    r.add_argument("solution", help="解法名（可缩写）或 .solution.json 路径")
    r.add_argument("--source", help="素材路径（覆盖解法默认值）")
    r.add_argument("--music", help="音乐路径")
    r.add_argument("--out", help="输出文件")
    r.add_argument("--yes", action="store_true", help="跳过人工闸门（复现用）")
    r.add_argument("--json", action="store_true", help="打印 JSON 结果（给脚本/agent 用）")
    r.set_defaults(func=cmd_run_solution)

    rr = sub.add_parser("run-recipe", help="跑旧的 recipe 流水线")
    rr.add_argument("recipe")
    rr.add_argument("--out")
    rr.add_argument("--suffix", default="")
    rr.add_argument("--crf", type=int, default=20)
    rr.add_argument("--preset", default="medium")
    rr.add_argument("--threads", type=int, default=2)
    rr.add_argument("--report", action="store_true")
    rr.set_defaults(func=cmd_run)
    sw = sub.add_parser("swap", help="本地换脸")
    sw.add_argument("--in", dest="input", required=True)
    sw.add_argument("--face", required=True, help="源人脸图片")
    sw.add_argument("--out", required=True)
    sw.add_argument("--scope", default="largest", choices=["largest", "all"])
    sw.add_argument("--seconds", type=float, default=None)
    sw.set_defaults(func=cmd_swap)
    doc = sub.add_parser("doctor", help="自检环境（ffmpeg / 模型 / 字体）")
    doc.set_defaults(func=cmd_doctor)
    so = sub.add_parser("solution", help="解法：列出 / 校验 / 执行")
    so.add_argument("action", choices=["list", "validate", "run"])
    so.add_argument("path", nargs="?")
    so.add_argument("--yes", action="store_true", help="跳过人工闸门（复现用）")
    so.add_argument("--allow", action="append", help="允许的能力，如 cloud/gpu/paid")
    so.add_argument("--input", action="append", help="覆盖输入，如 --input source=assets/x.mp4")
    so.set_defaults(func=cmd_solution)
    rp = sub.add_parser("replace", help="换人：导出待替换镜头 / 回填")
    rp.add_argument("action", choices=["export", "fill"])
    rp.add_argument("--recipe", default="recipes/mj_highlight.json")
    rp.add_argument("--index", type=int, default=0)
    rp.add_argument("--file")
    rp.add_argument("--out")
    rp.add_argument("--render", action="store_true", help="回填后立即重渲")
    rp.set_defaults(func=cmd_replace)
    args = ap.parse_args()
    sys.exit(args.func(args))

if __name__ == "__main__":
    main()
