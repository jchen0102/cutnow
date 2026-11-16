"""分镜稿 → EDL。

兼容两种输入：
  1) media-desk 的六格分镜：[{"no":1,"shot":"中景","visual":"...","voice":"口播文字","seconds":5}, ...]
  2) 简化写法：[{"role":"开场","seconds":3}, ...]

设计：一个镜头 = 一段素材窗口。没有给 source 时按素材列表轮转分配，
每段从该素材的游标处往后取；素材不够长就回到 0 再取（并在 warn 里记一笔）。
"""
import json
import os


class StoryboardError(ValueError):
    pass


def load(path):
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)
    shots = raw.get("shots") if isinstance(raw, dict) else raw
    if not isinstance(shots, list) or not shots:
        raise StoryboardError("分镜里没有 shots 数组")
    out = []
    for i, s in enumerate(shots):
        if not isinstance(s, dict):
            raise StoryboardError(f"第 {i + 1} 个镜头不是对象")
        try:
            sec = float(s.get("seconds") or s.get("dur") or 0)
        except (TypeError, ValueError):
            sec = 0
        if sec <= 0:
            raise StoryboardError(f"第 {i + 1} 个镜头缺少 seconds（必须 > 0）")
        out.append({
            "no": int(s.get("no") or i + 1),
            "seconds": round(min(max(sec, 0.5), 120.0), 2),
            "role": (s.get("role") or s.get("shot") or s.get("visual") or f"镜头{i + 1}").strip(),
            "voice": (s.get("voice") or s.get("text") or "").strip(),
            "visual": (s.get("visual") or "").strip(),
            "source": s.get("source") or s.get("file") or None,
            "start": s.get("start"),
        })
    return out


def _split_voice(text, per_line=22):
    """按标点切成适合一屏的字幕行。"""
    if not text:
        return []
    parts, buf = [], ""
    for ch in text:
        buf += ch
        if ch in "，。！？；、,.!?;…" and len(buf) >= 8:
            parts.append(buf.strip())
            buf = ""
        elif len(buf) >= per_line:
            parts.append(buf.strip())
            buf = ""
    if buf.strip():
        parts.append(buf.strip())
    return [p for p in parts if p]


def build_edl(shots, sources, probe, out_spec=None, title=None, end=None):
    """sources: [abs path, ...]；probe: 第一个素材的探测结果。"""
    if not sources:
        raise StoryboardError("至少需要一个素材文件")
    width = int((out_spec or {}).get("width") or probe.get("width") or 1280)
    height = int((out_spec or {}).get("height") or probe.get("height") or 720)
    fps = int((out_spec or {}).get("fps") or probe.get("fps") or 30)

    assets, video, subs, warns = [], [], [], []
    cursors = {p: 0.0 for p in sources}
    durations = {}
    total = 0.0
    for i, sh in enumerate(shots):
        src = sh.get("source") or sources[i % len(sources)]
        if not os.path.isabs(src):
            src = os.path.join(os.getcwd(), src)
        if not os.path.exists(src):
            raise StoryboardError(f"素材不存在：{src}")
        if src not in cursors:
            cursors[src] = 0.0
        dur_src = durations.get(src)
        if dur_src is None:
            from . import ffmpeg as F
            durations[src] = dur_src = float(F.probe(src).get("duration") or 0.0)
        start = sh.get("start") if sh.get("start") is not None else cursors[src]
        start = float(start)
        if dur_src and start + sh["seconds"] > dur_src:
            if dur_src >= sh["seconds"]:
                warns.append(f"镜头 {sh.get('no', i + 1)}：素材不够，回到 {max(0.0, dur_src - sh['seconds']):.2f}s 取")
                start = max(0.0, dur_src - sh["seconds"])
            else:
                warns.append(f"镜头 {sh.get('no', i + 1)}：素材只有 {dur_src:.1f}s，短于 {sh['seconds']}s")
                start = 0.0
        cursors[src] = start + sh["seconds"]
        aid = "src" if i == 0 else f"s{i}"   # render 约定：src 是主输入
        assets.append({"id": aid, "path": src})
        video.append({"asset": aid, "start": round(start, 3), "dur": sh["seconds"],
                      "at": round(total, 3), "role": sh.get("role") or f"镜头{sh.get('no', i + 1)}"})
        lines = _split_voice(sh.get("voice") or "")
        if lines:
            span = sh["seconds"] / len(lines)
            for j, line in enumerate(lines):
                subs.append({"start": round(total + j * span + 0.1, 2),
                             "end": round(total + (j + 1) * span - 0.1, 2),
                             "text": line})
        total += sh["seconds"]

    edl = {
        "version": 1,
        "id": "storyboard",
        "output": {"width": width, "height": height, "fps": fps},
        "assets": assets,
        "video": video,
        "subs": subs,
        "total": round(total, 3),
        "cleanup": {"crop": [width, height, 0, 0], "crop_bottom": 0},
        "cards": {"head": title, "tail": end} if (title or end) else {},
    }
    return edl, warns
