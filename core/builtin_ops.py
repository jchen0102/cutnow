"""内置算子：把已有能力包成可被解法引用的 op。"""
import json, os
from . import ffmpeg as F
from . import analyze as A
from . import render as R
from . import ops


def _ctx_path(ctx, key, default):
    return ctx["inputs"].get(key) or os.path.join(ctx["root"], default)


@ops.register("analyze.standard", "探测素材 + 切镜头 + 逐帧特征 + 节拍/副歌",
              inputs=["source"], outputs=["analysis"])
def analyze_standard(ctx, params):
    src = _ctx_path(ctx, "source", "assets/src_jam.mp4")
    info = F.probe(src)
    scenes = A.scenes(src, params.get("scene_threshold", 0.2))
    feat_spec = params.get("features", "out/features_jam.jsonl")
    if feat_spec == "auto":
        import hashlib, subprocess as _sp
        tag = hashlib.sha1((src + str(os.path.getmtime(src))).encode()).hexdigest()[:10]
        feat_path = os.path.join(ctx["root"], "out", f"features_{tag}.jsonl")
        if not os.path.exists(feat_path):
            exe = os.path.join(ctx["root"], "tools", "features")
            _sp.run([exe, src, feat_path, str(params.get("sample", 0.5))], check=True)
    else:
        feat_path = os.path.join(ctx["root"], feat_spec)
    rows = A.load_features(feat_path) if os.path.exists(feat_path) else []
    music = _ctx_path(ctx, "music", "assets/beat_it.m4a")
    x = A.decode_audio(music)
    bpm, beats = A.estimate_beat(x, 22050)
    chorus = A.loudest_window(x, 22050, params.get("chorus_window", 26.0))
    ctx["analysis"] = {"probe": info, "scenes": scenes, "rows": rows,
                       "bpm": bpm, "beats": [float(b) for b in beats],
                       "chorus_start": round(chorus, 3), "music_duration": len(x) / 22050}
    return {"scenes": len(scenes), "features": len(rows), "bpm": bpm, "chorus_start": ctx["analysis"]["chorus_start"]}


@ops.register("select.shots", "选定镜头并按拍数排出时间线",
              inputs=["analysis"], outputs=["video", "total"])
def select_shots(ctx, params):
    a = ctx["analysis"]
    beat = 60.0 / a["bpm"]
    shots = params.get("shots") or []
    if not shots:
        raise ops.OpError("select.shots 需要 params.shots=[[源起点, 拍数], ...]")
    video, t = [], 0.0
    for i, item in enumerate(shots):
        start, beats = float(item[0]), int(item[1])
        role = "冷开场" if i == 0 else ("收尾" if i == len(shots) - 1 else "发展")
        dur = round(beats * beat, 3)
        video.append({"asset": "src", "start": round(start, 3), "dur": dur,
                      "at": round(t, 3), "role": role, "beats": beats})
        t += dur
    ctx["edl"]["video"] = video
    ctx["edl"]["total"] = round(t, 3)
    return {"segments": len(video), "total": ctx["edl"]["total"]}


@ops.register("audio.chorus", "把音乐对齐到能量最大窗口", inputs=["music"], outputs=["audio"])
def audio_chorus(ctx, params):
    a = ctx["analysis"]
    total = ctx["edl"]["total"]
    start = params.get("in")
    if start in (None, "auto"):
        start = a["chorus_start"]
    ctx["edl"]["audio"] = [{"asset": "music", "in": round(float(start), 3),
                            "dur": total, "gain_db": 0.0}]
    return {"in": ctx["edl"]["audio"][0]["in"], "dur": total}


@ops.register("subtitle.by_beat", "按小节均分字幕轴", outputs=["subs"])
def subtitle_by_beat(ctx, params):
    lines = params.get("lines") or []
    if not lines:
        ctx["edl"]["subs"] = []
        return {"lines": 0}
    beat = 60.0 / ctx["analysis"]["bpm"]
    total = ctx["edl"]["total"]
    span = params.get("beats_per_line", 8) * beat
    start = max(0.0, total - span * len(lines))
    ctx["edl"]["subs"] = [{"start": round(start + i * span, 3),
                           "end": round(start + (i + 1) * span - 0.10, 3), "text": t}
                          for i, t in enumerate(lines)]
    return {"lines": len(lines), "span": round(span, 3), "start": round(start, 3)}


@ops.register("cleanup.crop", "裁掉黑边与自带硬字幕（模糊背景补画幅）", outputs=["cleanup"])
def cleanup_crop(ctx, params):
    crop = params.get("crop")
    if crop in ("auto", "full"):
        pr = ctx["analysis"]["probe"]
        crop = [pr["width"], pr["height"], 0, 0]
    if not crop or len(crop) != 4:
        raise ops.OpError("cleanup.crop 需要 params.crop=[w,h,x,y] 或 \"full\"")
    ctx["edl"]["cleanup"] = {"crop": [int(v) for v in crop],
                             "crop_bottom": int(params.get("crop_bottom", 0))}
    return ctx["edl"]["cleanup"]


@ops.register("render.edl", "EDL → mp4，返回 sha256", outputs=["mp4"])
def render_edl(ctx, params):
    out = params.get("out") or f"out/{ctx['solution']['id']}.mp4"
    path = os.path.join(ctx["root"], out)
    edl = ctx["edl"]
    res = R.render(edl, os.path.join(ctx["root"], "out", "work"), path,
                   crf=params.get("crf", 20), preset=params.get("preset", "medium"))
    rec = {"file": out, "sha256": res["sha256"], "bytes": res["bytes"], "path": res["path"]}
    ctx.setdefault("renders", []).append(rec)
    return rec


# ---------- 口播类算子（S2） ----------

@ops.register("analyze.media", "只做素材侧分析：探测 + 切镜头 + 逐帧特征（不需要音乐）",
              inputs=["source"], outputs=["analysis"])
def analyze_media(ctx, params):
    src = _ctx_path(ctx, "source", "assets/src_jam.mp4")
    info = F.probe(src)
    scenes = A.scenes(src, params.get("scene_threshold", 0.3))
    ctx["analysis"] = {"probe": info, "scenes": scenes, "bpm": None}
    return {"duration": info["duration"], "scenes": len(scenes),
            "size": [info["width"], info["height"]]}


@ops.register("transcribe.whisper", "whisper.cpp 语音转写（中文）", inputs=["source"], outputs=["transcript"])
def transcribe_whisper(ctx, params):
    src = _ctx_path(ctx, "source", "")
    wav = os.path.join(ctx["root"], params.get("wav", "out/talk/asr.wav"))
    os.makedirs(os.path.dirname(wav), exist_ok=True)
    F.run(["-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", wav])
    from . import config as C
    cli = params.get("cli") or C.whisper_cli()
    model = params.get("model") or str(C.whisper_model())
    base = os.path.join(ctx["root"], params.get("base", "out/talk/asr"))
    import subprocess
    if os.path.exists(base + ".json") and not params.get("force"):
        data = json.load(open(base + ".json", encoding="utf-8"))
        segs = [{"start": round(t["offsets"]["from"] / 1000.0, 2),
                 "end": round(t["offsets"]["to"] / 1000.0, 2),
                 "text": (t.get("text") or "").strip()}
                for t in data.get("transcription", []) if (t.get("text") or "").strip()]
        ctx["transcript"] = segs
        return {"segments": len(segs), "cached": True}
    argv = [cli, "-m", model, "-f", wav, "-l", "zh", "-oj", "-of", base]
    if params.get("no_gpu", True):
        argv.append("-ng")      # Metal 后端在这台机器上编译 shader 失败，走 CPU
    p = subprocess.run(argv, capture_output=True, text=True)
    if p.returncode != 0:
        raise ops.OpError(f"whisper 失败：{p.stderr[-400:]}")
    with open(base + ".json", encoding="utf-8") as fh:
        data = json.load(fh)
    segs = []
    for t in data.get("transcription", []):
        off = t.get("offsets") or {}
        text = (t.get("text") or "").strip()
        if not text:
            continue
        segs.append({"start": round(off.get("from", 0) / 1000.0, 2),
                     "end": round(off.get("to", 0) / 1000.0, 2), "text": text})
    ctx["transcript"] = segs
    return {"segments": len(segs), "chars": sum(len(s["text"]) for s in segs)}


def _split_sentences(segs, max_chars=14):
    """把 ASR 段切成短句：先按标点/空格分词，再合并到不超过 max_chars，时间按字数比例分配。"""
    import re
    out = []
    for seg in segs:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        pieces = re.findall(r"[^\s，。！？、；,.!?;]+[，。！？、；,.!?;]?", text)
        merged, buf = [], ""
        for p in pieces:
            while len(p) > max_chars:            # 超长无标点：硬切
                if buf:
                    merged.append(buf); buf = ""
                merged.append(p[:max_chars]); p = p[max_chars:]
            if len(buf) + len(p) <= max_chars:
                buf += p
            else:
                if buf:
                    merged.append(buf)
                buf = p
        if buf:
            merged.append(buf)
        if not merged:
            merged = [text]
        span = max(0.6, float(seg["end"]) - float(seg["start"]))
        total_chars = sum(len(m) for m in merged) or 1
        t = float(seg["start"])
        for m in merged:
            d = span * len(m) / total_chars
            out.append({"start": round(t, 2), "end": round(t + d, 2), "text": m.strip()})
            t += d
    return out


@ops.register("cut.by_sentence", "按句挑选高信息密度的连续段，产出镜头与字幕",
              inputs=["transcript"], outputs=["video", "subs"])
def cut_by_sentence(ctx, params):
    raw = ctx.get("transcript") or []
    target = float(params.get("target_seconds", 15))
    filler = tuple(params.get("filler", ["嗯", "啊", "那个", "就是", "然后呢"]))
    segs = _split_sentences(raw, int(params.get("max_chars", 14)))
    cand = [s for s in segs if len(s["text"]) >= params.get("min_chars", 4)
            and not s["text"].strip("，。！？ ").startswith(filler)]
    if not cand:
        raise ops.OpError("没有可用句子")

    # 滑窗：按"实际成片时长"累计（含每段 0.24s 补白与 1.2s 下限），不超过 target
    dur_of = lambda s: max(1.2, s["end"] - s["start"] + 0.24)
    best, best_score = None, -1
    for i in range(len(cand)):
        total, j = 0.0, i
        while j < len(cand) and total + dur_of(cand[j]) <= target:
            total += dur_of(cand[j])
            j += 1
        if j == i:
            continue
        chars = sum(len(cand[k]["text"]) for k in range(i, j))
        if chars > best_score:
            best, best_score = (i, j), chars
    if not best:
        raise ops.OpError("找不到合适片段")

    chosen = cand[best[0]:best[1]]
    video, subs, t = [], [], 0.0
    for k, s in enumerate(chosen):
        dur = round(max(1.2, s["end"] - s["start"] + 0.24), 3)
        role = "开场" if k == 0 else ("收尾" if k == len(chosen) - 1 else "正文")
        video.append({"asset": "src", "start": round(max(0.0, s["start"] - 0.1), 3),
                      "dur": dur, "at": round(t, 3), "role": role})
        subs.append({"start": round(t + 0.1, 3), "end": round(t + dur - 0.05, 3), "text": s["text"]})
        t += dur
    ctx["edl"]["video"] = video
    ctx["edl"]["subs"] = subs
    ctx["edl"]["total"] = round(t, 3)
    return {"segments": len(video), "total": ctx["edl"]["total"], "chars": best_score}


@ops.register("audio.from_clips", "把所选镜头的原声拼成一条音轨（口播用）", outputs=["audio"])
def audio_from_clips(ctx, params):
    src = _ctx_path(ctx, "source", "")
    out = os.path.join(ctx["root"], params.get("out", "out/talk_audio.m4a"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    parts, labels = [], []
    for i, c in enumerate(ctx["edl"]["video"]):
        parts.append(f"[0:a]atrim=start={c['start']:.3f}:duration={c['dur']:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[a{i}]")
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]"
    p = F.run(["-y", "-i", src, "-filter_complex", graph, "-map", "[out]",
               "-c:a", "aac", "-b:a", "160k", out])
    if p.returncode != 0:
        raise ops.OpError(p.stderr[-400:])
    ctx["edl"]["assets"] = [a for a in ctx["edl"]["assets"] if a["id"] != "music"]
    ctx["edl"]["assets"].append({"id": "music", "path": os.path.relpath(out, ctx["root"])})
    ctx["edl"]["audio"] = [{"asset": "music", "in": 0.0, "dur": ctx["edl"]["total"], "gain_db": 0.0}]
    return {"file": os.path.relpath(out, ctx["root"]), "dur": ctx["edl"]["total"]}


@ops.register("frame.vertical", "切成竖版画幅（前景按高度铺满，两侧模糊填充）", outputs=["output"])
def frame_vertical(ctx, params):
    w = int(params.get("width", 720)); h = int(params.get("height", 1280))
    src = ctx["analysis"]["probe"]
    ctx["edl"]["output"] = {"width": w, "height": h, "fps": int(params.get("fps", 30))}
    ctx["edl"]["cleanup"] = {"crop": [src["width"], src["height"], 0, 0], "crop_bottom": 0}
    return ctx["edl"]["output"]


@ops.register("qc.report", "成片质检：时长/黑帧/响度/字幕溢出/清晰度", outputs=["qc"])
def qc_report(ctx, params):
    from . import qc
    renders = ctx.get("renders") or []
    path = params.get("file") or (renders[-1]["path"] if renders else None)
    if not path:
        raise ops.OpError("qc.report 需要先渲染（params.file 或上游 render.edl）")
    if not os.path.isabs(path):
        path = os.path.join(ctx["root"], path)
    ignore, t = [], 0.0
    for c in ctx["edl"].get("video", []):
        if str(c.get("asset", "")).startswith("card"):
            ignore.append((max(0.0, t - 0.4), t + c["dur"] + 0.4))
        t += c["dur"]
    subs_burned = True
    if ctx.get("renders"):
        subs_burned = ctx["renders"][-1].get("subs_burned", True)
    rep = qc.report(path, ctx["edl"], params.get("thresholds"), ignore=ignore,
                    skip_subtitles=not subs_burned)
    ctx["qc"] = rep
    return {"pass": rep["pass"], "failed": rep["failed"],
            "duration": rep["checks"]["duration"]["value"],
            "lufs": rep["checks"]["loudness"]["lufs"],
            "sharpness": rep["checks"]["sharpness"]["laplacian_var"],
            "black": rep["checks"]["black_frames"]["count"],
            "subs_limit": rep["checks"]["subtitles"]["max_chars_per_line"]}


@ops.register("audio.normalize", "把音轨响度归一到 -14 LUFS（短内容常见标准）", outputs=["audio"])
def audio_normalize(ctx, params):
    target = params.get("i", -14.0)
    tp = params.get("tp", -1.5)
    assets = {a["id"]: a["path"] for a in ctx["edl"]["assets"]}
    src = assets.get("music")
    if not src:
        raise ops.OpError("没有音轨可归一（缺 music 资产）")
    src_abs = os.path.join(ctx["root"], src)
    out = os.path.join(ctx["root"], params.get("out", "out/norm_audio.m4a"))
    p = F.run(["-y", "-i", src_abs, "-af", f"loudnorm=I={target}:TP={tp}:LRA=11",
               "-c:a", "aac", "-b:a", "192k", out])
    if p.returncode != 0:
        raise ops.OpError(p.stderr[-400:])
    ctx["edl"]["assets"] = [a for a in ctx["edl"]["assets"] if a["id"] != "music"]
    ctx["edl"]["assets"].append({"id": "music", "path": os.path.relpath(out, ctx["root"])})
    ctx["edl"]["audio"] = [{"asset": "music", "in": 0.0, "dur": ctx["edl"]["total"], "gain_db": 0.0}]
    return {"file": os.path.relpath(out, ctx["root"]), "target_lufs": target}


@ops.register("select.auto", "自动选段：按运动/色彩/主体打分，卡点成片（无需人工给镜头）",
              inputs=["analysis"], outputs=["video", "total"])
def select_auto(ctx, params):
    from . import plan as P
    a = ctx["analysis"]
    beat = 60.0 / a["bpm"]
    target = float(params.get("target_seconds", 12))
    beats = tuple(params.get("beats", (4, 8, 12)))
    gap = float(params.get("gap", 25.0))
    cands = P.candidates(a["scenes"], a["rows"], beat, beats=beats, regions=None)
    if not cands:
        raise ops.OpError("没有可用候选窗口")
    chosen, _ = P.pick(cands, target, beat, gap=gap)
    video, t = [], 0.0
    for i, c in enumerate(chosen):
        role = "开场" if i == 0 else ("收尾" if i == len(chosen) - 1 else "高光")
        video.append({"asset": "src", "start": c["start"], "dur": round(c["beats"] * beat, 3),
                      "at": round(t, 3), "role": role, "beats": c["beats"], "score": c["score"]})
        t += c["beats"] * beat
    ctx["edl"]["video"] = video
    ctx["edl"]["total"] = round(t, 3)
    return {"segments": len(video), "total": ctx["edl"]["total"],
            "avg_score": round(sum(c["score"] for c in chosen) / len(chosen), 3)}


@ops.register("select.action", "按音频能量+运动+主体选段，切点落在镜头边界（适合体育/动作素材）",
              inputs=["analysis"], outputs=["video", "total"])
def select_action(ctx, params):
    from . import action as ACT
    a = ctx["analysis"]
    env, hop = ACT.audio_env(ctx["inputs"]["source"])
    beat = 60.0 / a["bpm"]
    target = float(params.get("target_seconds", 12))
    cands = ACT.scene_candidates(a["scenes"], a["rows"], env, hop, beat,
                                 beats=tuple(params.get("beats", (4, 8, 12))))
    if not cands:
        raise ops.OpError("没有可用候选窗口")
    motions = sorted(c["motion"] for c in cands)
    audios = sorted(c["audio_peak"] for c in cands)
    p75 = motions[int(len(motions) * 0.75)] if motions else 20.0
    p60 = audios[int(len(audios) * 0.60)] if audios else 0.3
    for c in cands:
        c["score"] = ACT.score_action(c, p75, p60)
    chosen, used = ACT.pick_action(cands, target, beat)
    if not chosen:
        raise ops.OpError("选不出窗口")
    video, t = [], 0.0
    for i, c in enumerate(chosen):
        role = "开场" if i == 0 else ("收尾" if i == len(chosen) - 1 else "高光")
        video.append({"asset": "src", "start": c["start"], "dur": round(c["beats"] * beat, 3),
                      "at": round(t, 3), "role": role, "beats": c["beats"], "score": c["score"]})
        t += c["beats"] * beat
    ctx["edl"]["video"] = video
    ctx["edl"]["total"] = round(t, 3)
    mean_motion = sum(c["motion"] for c in chosen) / len(chosen)
    mean_audio = sum(c["audio_peak"] for c in chosen) / len(chosen)
    lift_m = round(mean_motion / max(1e-6, sum(motions) / len(motions)), 2)
    lift_a = round(mean_audio / max(1e-6, sum(audios) / len(audios)), 2)
    return {"segments": len(video), "total": ctx["edl"]["total"],
            "motion_lift": lift_m, "audio_lift": lift_a,
            "avg_score": round(sum(c["score"] for c in chosen) / len(chosen), 3)}


_SPORT_PROMPTS = {
    "sport": ["a sports match", "players competing in a sport", "a football game",
              "athletes playing a game", "a basketball game in progress", "a player scoring a point"],
    "crowd": ["a crowd walking on a street", "people shopping outdoors", "tourists walking"],
    "interview": ["a person talking to the camera", "an interview", "a person sitting and speaking"],
    "other": ["an empty room", "a screen recording", "a landscape", "text on a screen"],
}


@ops.register("qc.source", "素材准入：判断这段素材值不值得剪（语义）", inputs=["source"], outputs=["precheck"])
def qc_source(ctx, params):
    from . import clip as C, frames as FR
    src = ctx["inputs"].get("source")
    fps = float(params.get("fps", 1.0))
    times, imgs = FR.grab(src, fps=fps)
    if len(imgs) == 0:
        raise ops.OpError("抽帧失败")
    probs, labels = C.similarity(C.encode_images(list(imgs)), _SPORT_PROMPTS)
    idx = labels.index("sport")
    per_frame = probs[:, idx]
    mean_p = float(probs[:, idx].mean())
    verdict = "ok" if mean_p >= float(params.get("min_sport", 0.35)) else "weak"
    if verdict == "weak" and params.get("strict"):
        raise ops.OpError(f"素材不合格：sport_prob={mean_p:.3f} < {params.get('min_sport', 0.35)}")
    ctx["precheck"] = {"sport_prob": round(mean_p, 3), "verdict": verdict, "frames": len(imgs)}
    return {"sport_prob": round(mean_p, 3), "verdict": verdict, "frames": len(imgs),
            "top": round(float(per_frame.max()), 3)}


@ops.register("select.semantic", "语义选段：CLIP 判断“这是不是比赛”，再用运动/音量排序",
              inputs=["analysis"], outputs=["video", "total"])
def select_semantic(ctx, params):
    from . import action as ACT, clip as C, frames as FR
    a = ctx["analysis"]
    src = ctx["inputs"]["source"]
    env, hop = ACT.audio_env(src)
    beat = 60.0 / a["bpm"]
    target = float(params.get("target_seconds", 12))
    cands = ACT.scene_candidates(a["scenes"], a["rows"], env, hop, beat,
                                 beats=tuple(params.get("beats", (4, 8, 12))))
    if not cands:
        raise ops.OpError("没有可用候选窗口")
    motions = sorted(c["motion"] for c in cands)
    audios = sorted(c["audio_peak"] for c in cands)
    p75 = motions[int(len(motions) * 0.75)] if motions else 20.0
    p60 = audios[int(len(audios) * 0.60)] if audios else 0.3
    for c in cands:
        c["action"] = ACT.score_action(c, p75, p60)

    # 先按运动/音量筛出一批候选，再用 CLIP 打分（省算力）
    # 候选全量打语义分（抽帧只做一次，CLIP 单帧 ~5ms，不必再截断）
    pool = cands
    times, imgs = FR.grab(src, fps=float(params.get("fps", 2.0)))
    if len(imgs) == 0:
        raise ops.OpError("抽帧失败")
    probs, labels = C.similarity(C.encode_images(list(imgs)), _SPORT_PROMPTS)
    idx = labels.index("sport")
    for c in pool:
        inside = [i for i, t in enumerate(times) if c["start"] <= t < c["start"] + c["dur"]]
        c["sem"] = float(probs[inside, idx].mean()) if inside else 0.0
        c["score"] = round(0.6 * c["sem"] + 0.4 * c["action"], 4)

    qualified = [p for p in pool if p["sem"] >= float(params.get("min_sem", 0.25))]
    if not qualified:
        raise ops.OpError(f"没有语义合格的镜头（最高 sem={max(p['sem'] for p in pool):.2f}）")
    chosen, used = ACT.pick_action(qualified, target, beat)
    total = sum(c["beats"] for c in chosen) * beat
    if total < float(params.get("min_total", 4.0)):
        raise ops.OpError(f"可用镜头不足：仅 {total:.1f}s")
    video, t = [], 0.0
    for i, c in enumerate(chosen):
        role = "开场" if i == 0 else ("收尾" if i == len(chosen) - 1 else "高光")
        video.append({"asset": "src", "start": c["start"], "dur": round(c["beats"] * beat, 3),
                      "at": round(t, 3), "role": role, "beats": c["beats"], "score": c["score"]})
        t += c["beats"] * beat
    ctx["edl"]["video"] = video
    ctx["edl"]["total"] = round(t, 3)
    return {"segments": len(video), "total": ctx["edl"]["total"],
            "sem": round(float(sum(c["sem"] for c in chosen) / len(chosen)), 3),
            "audit": [round(c["sem"], 2) for c in chosen]}


def _card(ctx, text, dur, name, sub=""):
    """生成一张纯色文字卡（带淡入淡出），返回相对路径。"""
    W = ctx["edl"]["output"]["width"]; H = ctx["edl"]["output"]["height"]
    FPS = ctx["edl"]["output"].get("fps", 30)
    from .render import font
    fp = font()
    out = os.path.join(ctx["root"], "out", "cards", f"{name}.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    main_size = int(H * 0.085)
    sub_size = int(H * 0.040)
    vf = (f"drawtext=fontfile='{fp}':text='{text}':fontcolor=white:fontsize={main_size}:"
          f"x=(w-text_w)/2:y=(h-text_h)/2-{int(H*0.03)}"
          + (f",drawtext=fontfile='{fp}':text='{sub}':fontcolor=0xBBBBBB:fontsize={sub_size}:"
             f"x=(w-text_w)/2:y=(h-text_h)/2+{int(H*0.06)}" if sub else "")
          + f",fade=t=in:st=0:d=0.25,fade=t=out:st={max(0.1, dur-0.35):.2f}:d=0.35")
    p = F.run(["-y", "-f", "lavfi", "-i", f"color=c=0x111114:s={W}x{H}:d={dur}:r={FPS}",
               "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
               "-pix_fmt", "yuv420p", out])
    if p.returncode != 0:
        raise ops.OpError(p.stderr[-400:])
    return os.path.relpath(out, ctx["root"])


@ops.register("card.bookends", "加片头/片尾文字卡（自动重排时间线与总长）", outputs=["video", "total"])
def card_bookends(ctx, params):
    head = params.get("title")
    tail = params.get("end")
    dur_h = float(params.get("head_dur", 1.6))
    dur_t = float(params.get("tail_dur", 2.0))
    if head:
        path = _card(ctx, head, dur_h, "title", params.get("sub", ""))
        ctx["edl"]["assets"] = [a for a in ctx["edl"]["assets"] if a["id"] != "card_title"]
        ctx["edl"]["assets"].append({"id": "card_title", "path": path})
        ctx["edl"]["video"].insert(0, {"asset": "card_title", "start": 0.0, "dur": dur_h,
                                       "at": 0.0, "role": "片头"})
    if tail:
        path = _card(ctx, tail, dur_t, "end", params.get("end_sub", ""))
        ctx["edl"]["assets"] = [a for a in ctx["edl"]["assets"] if a["id"] != "card_end"]
        ctx["edl"]["assets"].append({"id": "card_end", "path": path})
        ctx["edl"]["video"].append({"asset": "card_end", "start": 0.0, "dur": dur_t,
                                    "at": 0.0, "role": "片尾"})
    t = 0.0
    for c in ctx["edl"]["video"]:
        c["at"] = round(t, 3)
        t += c["dur"]
    ctx["edl"]["total"] = round(t, 3)
    return {"head": bool(head), "tail": bool(tail), "total": ctx["edl"]["total"]}
