#!/usr/bin/env python3
"""cutnow —— 把一条二创拆成可复用的剪辑解法：probe / scenes / beats / plan / render / run"""
import argparse, json, os, subprocess, sys, time
from core import analyze as A, plan as P, render as R
from core import ffmpeg as F

HERE = os.path.dirname(os.path.abspath(__file__))
_CALLER_CWD = os.getcwd()      # 记录要落在用户的项目目录，不是包安装目录

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
    local = os.path.join(HERE, "solutions")
    if os.path.isdir(local):
        return local
    try:
        import solutions as pkg          # 安装后随包里的一份
        return os.path.dirname(pkg.__file__)
    except ImportError:
        return local


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
            {"id": "cards", "op": "card.bookends", "params": {"title": name.upper(), "end": "cutnow"}},
            {"id": "normalize", "op": "audio.normalize", "params": {"i": -14.0}},
            {"id": "render", "op": "render.edl", "params": {"out": f"out/{name}.mp4"}},
            {"id": "qc", "op": "qc.report", "params": {}},
        ],
        "outputs": ["mp4"], "capabilities": [],
    }
    os.makedirs(_solutions_dir(), exist_ok=True)
    json.dump(tpl, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"已创建 {path}\n下一步：cutnow solution validate {path}")
    return 0


def cmd_demo(args):
    """零素材演示：生成一段测试画面 → 跑内置 demo 解法 → 告诉用户文件在哪。"""
    import tempfile
    from core import ffmpeg as F
    work = tempfile.mkdtemp(prefix="cutnow-demo-")
    src = os.path.join(work, "demo-src.mp4")
    print("① 生成测试素材 …")
    p = F.run(["-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=9",
               "-f", "lavfi", "-i", "sine=frequency=330:duration=9",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src])
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-400:])
    out = os.path.abspath(args.out)
    print(f"② 跑内置解法 demo → {out}")
    rc = cmd_run_solution(argparse.Namespace(
        solution="demo", source=src, music=None, out=out, yes=True, json=False))
    if rc == 0 and os.path.exists(out):
        print(f"\n完成：{out}  {os.path.getsize(out)/1e6:.1f}MB")
        print("打开看看，这就是 cutnow 的产物格式（片头卡 + 三段 + 片尾卡 + 质检）。")
    return rc


def cmd_storyboard(args):
    """分镜稿直出：storyboard.json + 素材 → EDL → 成片 → 质检 → 记录。"""
    from core import builtin_ops  # noqa: F401  注册算子
    from core import ffmpeg as F, storyboard as SB, ops
    sources = []
    for chunk in args.source or []:
        sources += [c.strip() for c in chunk.split(",") if c.strip()]
    if not sources:
        raise SystemExit("需要 --source（可以给多个，用逗号分隔）")
    sources = [os.path.abspath(x) for x in sources]
    shots = SB.load(args.storyboard)
    probe = F.probe(sources[0])
    edl, warns = SB.build_edl(shots, sources, probe, title=args.title, end=args.end)
    for w in warns:
        print(f"  ! {w}")

    root = HERE
    os.chdir(root)
    out = args.out or os.path.join(os.getcwd(), "storyboard.mp4")
    # 音轨：给了音乐就用音乐，否则铺静音并说明
    total = edl["total"]
    if args.music:
        music = os.path.abspath(args.music)
        edl["assets"].append({"id": "music", "path": music})
        print(f"  音轨：{os.path.basename(music)}")
    else:
        music = os.path.join(root, "out", "storyboard_silence.m4a")
        os.makedirs(os.path.dirname(music), exist_ok=True)
        F.run(["-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=48000",
               "-t", f"{total:.3f}", "-c:a", "aac", music])
        edl["assets"].append({"id": "music", "path": music})
        print("  音轨：静音（没给 --music；分镜里的 voice 会变成字幕）")
    edl["audio"] = [{"asset": "music", "in": 0.0, "dur": total, "gain_db": 0.0}]

    ctx = {"root": root, "solution": {"id": "storyboard", "name": "分镜直出"},
           "inputs": {"source": sources[0]}, "edl": edl, "log": [], "renders": [],
           "analysis": {"probe": probe}}
    print(f"分镜 {len(shots)} 个镜头 · {total:.1f}s → {out}")
    rr = builtin_ops.render_edl(ctx, {"out": out})
    ctx["log"].append({"id": "render", "op": "render.edl", "result": rr, "seconds": 0})
    qq = builtin_ops.qc_report(ctx, {})
    ctx["log"].append({"id": "qc", "op": "qc.report", "result": qq, "seconds": 0})
    r = ctx["renders"][-1]
    print(f"成片 {out}  {r['bytes']/1e6:.1f}MB  sha256={r['sha256']}")
    if not getattr(args, "no_records", False):
        _record_run(ctx["solution"], ctx)
    return 0


def cmd_serve(args):
    import subprocess
    script = os.path.join(HERE, "workbench", "server.py")
    print(f"http://127.0.0.1:{args.port}")
    if os.path.exists(script):
        return subprocess.call([sys.executable, script, str(args.port)])
    return subprocess.call([sys.executable, "-m", "workbench.server", str(args.port)])


def _apply_text(args, sol):
    """把 --title/--sub/--end/--end-sub/--credit 注入文字卡。

    默认不出文字卡；用户给了才出。解法没有 card.bookends 时明确告知，而不是静默丢弃。
    """
    texts = {
        "title": getattr(args, "title", None),
        "sub": getattr(args, "sub", None),
        "end": getattr(args, "end", None),
        "end_sub": getattr(args, "end_sub", None),
    }
    credit = getattr(args, "credit", None)
    if credit:
        texts["end_sub"] = texts["end_sub"] or credit
    texts = {k: v for k, v in texts.items() if v}
    if not texts:
        return
    for st in sol["steps"]:
        if st["op"] == "card.bookends":
            st.setdefault("params", {}).update(texts)
            return
    print("提示：该解法没有文字卡步骤，--title/--credit 等已忽略", file=sys.stderr)


def cmd_run_solution(args):
    from core import ops, builtin_ops  # noqa: F401
    from core import solution as SOL, runner
    path = _resolve_solution(args.solution)
    sol = SOL.load(path, ops.OPS)
    _apply_text(args, sol)
    overrides = {}
    if args.source:
        overrides["source"] = os.path.abspath(args.source)
    if args.music:
        overrides["music"] = os.path.abspath(args.music)
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

    if not getattr(args, "no_manifest", False):
        mp = _write_manifest(sol, path, ctx, edl_path)
    else:
        mp = None
    if not getattr(args, "no_records", False):
        _record_run(sol, ctx, mp)
    return 0


def _record_run(sol, ctx, manifest_path=None):
    """把这次运行登记成 version + render_run；失败只警告，不影响出片。"""
    record_root = _CALLER_CWD if os.path.isdir(_CALLER_CWD) else HERE
    try:
        from core import records as REC, manifest as MF
        inputs = []
        for key, raw in (ctx.get("inputs") or {}).items():
            if not raw:
                continue
            path = raw if os.path.isabs(raw) else next(
                (c for c in (os.path.join(os.getcwd(), raw), os.path.join(HERE, raw))
                 if os.path.exists(c)), os.path.join(HERE, raw))
            if os.path.exists(path):
                ident = MF.identity(path, HERE)
                inputs.append({"id": key, "path": ident["path"],
                               "sha256": ident["sha256"], "bytes": ident["bytes"]})
        parent = REC.latest_version_id(record_root, sol["id"])
        ver = REC.create_version(record_root, ctx["edl"], inputs=inputs, solution_id=sol["id"],
                                 parent_id=parent)
        out = (ctx.get("renders") or [{}])[-1]
        qc = next((s.get("result") for s in ctx.get("log") or [] if s.get("id") == "qc"), None)
        env = MF.engine_identity()
        env["ffmpeg"] = MF.ffmpeg_identity().get("version", "")
        mref = None
        if manifest_path and os.path.isfile(manifest_path):
            mref = {"path": os.path.relpath(manifest_path, HERE),
                    "sha256": MF.identity(manifest_path, HERE)["sha256"]}
        run = REC.create_run(record_root, ver["id"],
                             output={"path": out.get("file"), "sha256": out.get("sha256"),
                                     "bytes": out.get("bytes")},
                             qc=qc, manifest=mref, environment=env)
        print(f"版本 {ver['id']} · 渲染 {run['id']}")
        print(f"  审批成片：cutnow approve {run['id']} --by <你的名字>")
    except Exception as e:
        print(f"警告：记录版本失败：{e}", file=sys.stderr)


def cmd_import(args):
    """把旧产物登记为历史版本：缺失的环境/审批/来源一律标 unknown，不猜。"""
    from core import records as REC
    from core import manifest as MF
    edl = json.load(open(args.edl, encoding="utf-8"))
    unknown = args.unknown or ["environment", "approval", "source"]
    ver = REC.create_version(HERE, edl, solution_id=args.solution or edl.get("id"),
                             change_note=args.note or "历史导入", imported=True, unknown=unknown)
    print(f"已导入版本 {ver['id']}（未知：{', '.join(ver['origin']['unknown'])}）")
    if args.output:
        ident = MF.identity(args.output, HERE, "full")
        run = REC.create_run(record_root, ver["id"], status="succeeded",
                             output={"path": ident["path"], "sha256": ident["sha256"],
                                     "bytes": ident["bytes"]},
                             environment={"unknown": True})
        print(f"  关联历史成片：{run['id']}（执行环境未知）")
    return 0


def cmd_versions(args):
    from core import records as REC
    vers = REC.list_records(HERE, "version")
    if args.json:
        print(json.dumps(vers, ensure_ascii=False, indent=2))
        return 0
    if not vers:
        print("还没有版本记录。跑一次 cutnow run 就会生成。")
        return 0
    runs = REC.list_records(HERE, "render_run")
    print(f"{'版本':28} {'解法':18} {'父版本':28} 渲染  说明")
    for v in vers:
        n = sum(1 for r in runs if r.get("version_id") == v["id"])
        print(f"{v['id']:28} {(v.get('solution_id') or '-'):18} "
              f"{(v.get('parent_id') or '-'):28} {n:>4}  {v.get('change_note') or ''}")
    return 0


def cmd_approve(args):
    from core import records as REC
    decision = "rejected" if args.reject else "approved"
    if args.script:
        rec = REC.approve_script(HERE, args.target, by=args.by, note=args.note, decision=decision)
    else:
        rec = REC.approve_output(HERE, args.target, by=args.by, note=args.note, decision=decision)
    what = "剪法（脚本）" if rec["scope"] == "script" else "成片"
    print(f"已记录{what}审批：{rec['id']} · {rec['decision']} · by {rec['by']}")
    if rec["scope"] == "output" and decision == "approved":
        print(f"  下一步：cutnow deliver {args.target} --by <交付人>")
    return 0


def cmd_deliver(args):
    from core import records as REC
    try:
        d = REC.deliver(HERE, args.run, by=args.by, channel=args.channel or "", note=args.note or "")
    except REC.DeliveryRefused as e:
        print(f"{e}", file=sys.stderr)
        return 3
    print(f"交付 {d['id']} · 版本 {d['version_id']} · 成片 {d['output_sha256'][:16]}…")
    print(f"  审计：cutnow audit {d['id']}")
    return 0


def cmd_audit(args):
    from core import records as REC
    res = REC.audit(HERE, args.delivery)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        d = res.get("delivery") or {}
        print(f"交付 {args.delivery} · 版本 {d.get('version_id', '?')} · 渲染 {d.get('run_id', '?')}")
        for c in res.get("checks") or []:
            mark = {"ok": "✓", "broken": "✗"}.get(c["status"], "?")
            detail = f"  {c['detail']}" if c.get("detail") else ""
            print(f"  {mark} {c['name']}{detail}")
        print(f"\n结论：{'链路一致' if res['conclusion'] == 'ok' else '链路不一致'}")
    return 0 if res["conclusion"] == "ok" else 3


def _write_manifest(sol, solution_path, ctx, edl_path):
    """跑完就把「这次为什么能复现」写成凭据，失败不影响出片。"""
    try:
        from core import manifest as MF
        out = (ctx.get("renders") or [{}])[-1].get("path")
        inputs = {}
        for key, raw in (ctx.get("inputs") or {}).items():
            if not raw:
                continue
            if os.path.isabs(raw):
                inputs[key] = raw
            else:
                inputs[key] = next((c for c in (os.path.join(os.getcwd(), raw),
                                                os.path.join(HERE, raw))
                                    if os.path.exists(c)), os.path.join(HERE, raw))
        mf = MF.build(solution_path, sol, inputs, ctx.get("log"), ctx["edl"],
                      edl_path, out, HERE)
        mp = os.path.join(HERE, "out", f"{sol['id']}.manifest.json")
        MF.write(mf, mp)
        print(f"凭据 {os.path.relpath(mp, HERE)}  （cutnow verify 可校验）")
        return mp
    except Exception as e:
        print(f"警告：写复现凭据失败：{e}", file=sys.stderr)
        return None


def cmd_verify(args):
    from core import manifest as MF
    res = MF.verify(args.manifest)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        m = res["manifest"]
        eng = m.get("engine") or {}
        print(f"凭据 {args.manifest}")
        print(f"  引擎   cutnow {eng.get('version')} · Python {eng.get('python')} · {eng.get('platform')}")
        for c in res["checks"]:
            mark = {"ok": "✓", "drift": "~", "broken": "✗"}.get(c["status"], "?")
            detail = f"  {c['detail']}" if c.get("detail") else ""
            print(f"  {mark} {c['name']}{detail}")
        c = res["counts"]
        verdict = {"ok": "可复现（产物与输入一致）",
                   "drift": "环境漂移（产物仍一致，但重渲可能不再逐字节相同）",
                   "broken": "承诺失效（输入 / EDL / 成片已变）"}[res["conclusion"]]
        print(f"\n结论：{verdict}  ·  ok {c['ok']} / drift {c['drift']} / broken {c['broken']}")
    return {"ok": 0, "drift": 2, "broken": 3}[res["conclusion"]]


def cmd_doctor(args):
    from core import config as C
    print("cutnow doctor\n")
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


def _run():
    ap = argparse.ArgumentParser(prog="cutnow")
    ap.add_argument("--version", action="store_true", help="显示版本")
    sub = ap.add_subparsers(dest="cmd", required=False)
    ls = sub.add_parser("list", help="列出解法与算子")
    ls.set_defaults(func=cmd_list)

    nw = sub.add_parser("new", help="新建一个解法骨架")
    nw.add_argument("name")
    nw.add_argument("--force", action="store_true")
    nw.set_defaults(func=cmd_new)

    dm = sub.add_parser("demo", help="零素材跑一条演示片")
    dm.add_argument("--out", default="cutnow-demo.mp4")
    dm.set_defaults(func=cmd_demo)

    sb = sub.add_parser("storyboard", help="分镜稿直出成片（storyboard.json → mp4）")
    sb.add_argument("storyboard", help="分镜 JSON")
    sb.add_argument("--source", action="append", help="素材，可多个（逗号分隔或重复给）")
    sb.add_argument("--music", help="配乐（不给就静音）")
    sb.add_argument("--out", help="输出路径")
    sb.add_argument("--title", help="片头标题")
    sb.add_argument("--end", help="片尾文案")
    sb.add_argument("--no-records", action="store_true", help="不登记版本/渲染记录")
    sb.set_defaults(func=cmd_storyboard)

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
    r.add_argument("--title", help="片头主标题（不给就不出文字卡）")
    r.add_argument("--sub", help="片头副标题")
    r.add_argument("--end", help="片尾主文案")
    r.add_argument("--end-sub", dest="end_sub", help="片尾副文案")
    r.add_argument("--credit", help="署名（等价于 --end-sub，写进片尾卡）")
    r.add_argument("--no-manifest", action="store_true", help="不写复现凭据")
    r.add_argument("--no-records", action="store_true", help="不登记版本/渲染记录")
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

    im = sub.add_parser("import", help="把旧 EDL/成片登记为历史版本（缺失信息标 unknown）")
    im.add_argument("edl", help="EDL 路径")
    im.add_argument("--solution", help="解法 id（默认取 EDL 的 id）")
    im.add_argument("--output", help="已有成片路径（可选）")
    im.add_argument("--note", default="", help="说明")
    im.add_argument("--unknown", action="append", help="明确缺失的信息项")
    im.set_defaults(func=cmd_import)

    vs = sub.add_parser("versions", help="列出剪辑版本与渲染次数")
    vs.add_argument("--json", action="store_true")
    vs.set_defaults(func=cmd_versions)

    apv = sub.add_parser("approve", help="审批：默认审成片（绑到具体渲染产物）")
    apv.add_argument("target", help="渲染 id（默认）或版本 id（配 --script）")
    apv.add_argument("--by", required=True, help="审批人")
    apv.add_argument("--script", action="store_true", help="审批剪法（脚本），不绑定具体成片")
    apv.add_argument("--reject", action="store_true", help="记录为驳回")
    apv.add_argument("--note", default="", help="备注")
    apv.set_defaults(func=cmd_approve)

    dv = sub.add_parser("deliver", help="交付：必须有与该成片摘要匹配的成片审批")
    dv.add_argument("run", help="渲染 id")
    dv.add_argument("--by", required=True, help="交付人")
    dv.add_argument("--channel", help="渠道，如 douyin / wechat")
    dv.add_argument("--note", default="")
    dv.set_defaults(func=cmd_deliver)

    au = sub.add_parser("audit", help="审计一条交付：版本→渲染→审批 是否对得上")
    au.add_argument("delivery")
    au.add_argument("--json", action="store_true")
    au.set_defaults(func=cmd_audit)

    vf = sub.add_parser("verify", help="校验一份复现凭据（manifest）")
    vf.add_argument("manifest", help="manifest 路径，如 out/sports-highlight.manifest.json")
    vf.add_argument("--json", action="store_true", help="打印 JSON 结果")
    vf.set_defaults(func=cmd_verify)
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
    if getattr(args, "version", False):
        from core import __version__ as v
        print(f"cutnow {v}")
        return 0
    if not getattr(args, "func", None):
        ap.print_help()
        return 2
    return args.func(args) or 0

def main():
    """控制台入口：所有错误在这里变成一句话，不甩调用栈。"""
    try:
        return _run()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"错误：{e}", file=sys.stderr)
        print("（想看调用栈就设 CUTNOW_DEBUG=1）", file=sys.stderr)
        if os.environ.get("CUTNOW_DEBUG"):
            raise
        return 1


if __name__ == "__main__":
    sys.exit(main())
