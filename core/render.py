"""EDL → ffmpeg filtergraph → mp4。
构图：裁掉原片黑边与自带硬字幕 → 前景按高度铺满，背景用同一画面放大模糊填充 16:9。"""
import json, os, subprocess
from . import ffmpeg as F

FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
]

def font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return ""

def _txt(path, text):
    open(path, "w", encoding="utf-8").write(text)
    return path

def build(edl, workdir, out_path, crf=20, preset="medium", threads=2, blur=18, replacements=None):
    os.makedirs(workdir, exist_ok=True)
    W, H, FPS = edl["output"]["width"], edl["output"]["height"], edl["output"]["fps"]
    cw, ch, cx, cy = edl["cleanup"]["crop"]
    assets = {a["id"]: a["path"] for a in edl["assets"]}
    total = float(edl["total"])
    replacements = replacements or {}
    extra_inputs = [replacements[i] for i in sorted(replacements)]

    # 视频源：src 固定为 input 0，其余素材（片头/片尾卡）依次追加
    order = ["src"] + sorted(k for k in assets if k not in ("src", "music"))
    card_offset = 2 + len(extra_inputs)
    vidx = {k: card_offset + j for j, k in enumerate(order[1:]) if assets.get(k)}
    card_inputs = [assets[k] for k in order[1:] if assets.get(k)]

    parts, labels = [], []
    for i, c in enumerate(edl["video"]):
        aid = c.get("asset", "src")
        if aid != "src" and aid in vidx:
            k = vidx[aid]
            # 卡片类素材：已经是目标画幅，直接规格化
            parts.append(
                f"[{k}:v]trim=start={c['start']:.3f}:duration={c['dur']:.3f},setpts=PTS-STARTPTS,"
                f"scale={W}:{H},setsar=1,fps={FPS},format=yuv420p[v{i}]")
            labels.append(f"[v{i}]")
            continue
        if i in replacements:
            # 已替换：素材是外部模型重绘好的 16:9 片段，直接规格化，不再走裁边/模糊背景
            k = 2 + sorted(replacements).index(i)
            parts.append(
                f"[{k}:v]trim=start=0:duration={c['dur']:.3f},setpts=PTS-STARTPTS,"
                f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                f"setsar=1,fps={FPS},format=yuv420p[v{i}]")
            labels.append(f"[v{i}]")
            continue
        parts.append(
            f"[0:v]trim=start={c['start']:.3f}:duration={c['dur']:.3f},setpts=PTS-STARTPTS,"
            f"crop={cw}:{ch}:{cx}:{cy},split=2[fg{i}][bg{i}]")
        parts.append(
            f"[bg{i}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur={blur}:2[bgb{i}]")
        parts.append(f"[fg{i}]scale=-2:{H}:flags=lanczos[fgs{i}]")
        parts.append(
            f"[bgb{i}][fgs{i}]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS},format=yuv420p[v{i}]")
        labels.append(f"[v{i}]")
    parts.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0,setsar=1[vc]")

    vout = "[vc]"
    warnings = []
    subs = edl.get("subs") or []
    fp = font()
    if subs and not fp:
        warnings.append("找不到中文字体，字幕已跳过")
        subs = []
    elif subs and not F.has_filter("drawtext"):
        warnings.append("当前 ffmpeg 不带 drawtext（libfreetype），字幕已跳过")
        subs = []
    if subs:
        chain = []
        for i, s in enumerate(subs):
            tf = _txt(os.path.join(workdir, f"cue_{i}.txt"), s["text"])
            size = min(int(H * 0.058), int(W * 0.055))   # 窄画幅按宽度收敛，避免字幕溢出
            size = max(18, size)
            chain.append(
                f"drawtext=fontfile='{fp}':textfile='{tf}':fontcolor=white:fontsize={size}:"
                f"borderw=2:bordercolor=black:box=1:boxcolor=black@0.35:boxborderw=12:"
                f"x=(w-text_w)/2:y=h-{int(H*0.105)}:"
                f"enable='between(t,{s['start']:.3f},{s['end']:.3f})'")
        parts.append("[vc]" + ",".join(chain) + "[vsub]")
        vout = "[vsub]"

    a = edl["audio"][0]
    fade = min(0.8, total / 8)
    parts.append(
        f"[1:a]atrim=start={a['in']:.3f}:duration={total:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d={fade:.2f},afade=t=out:st={total-1.0:.3f}:d=1.0[aout]")

    graph = ";".join(parts)
    cmd = [F.ffmpeg(), "-y", "-hide_banner", "-nostdin", "-loglevel", "error",
           "-i", assets["src"], "-i", assets["music"]]
    for p in extra_inputs:
        cmd += ["-i", p]
    for p in card_inputs:
        cmd += ["-i", p]
    cmd += ["-filter_complex", graph, "-map", vout, "-map", "[aout]",
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
           "-pix_fmt", "yuv420p", "-r", str(FPS), "-threads", str(threads),
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-movflags", "+faststart",
           "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
           "-map_metadata", "-1", out_path]
    return cmd, graph, warnings

def render(edl, workdir, out_path, **kw):
    cmd, graph, warnings = build(edl, workdir, out_path, **kw)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-2500:])
    return {"path": out_path, "sha256": F.sha256(out_path), "bytes": os.path.getsize(out_path),
            "graph_chars": len(graph), "warnings": warnings,
            "subs_burned": bool((edl.get("subs") or []) and not warnings)}
