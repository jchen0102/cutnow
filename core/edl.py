"""EDL 读写与重排：改切点/拍数后重新计时，保证切点仍落在拍上。"""
import json, os


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(edl, path):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(edl, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def retime(edl, bpm):
    """按 beats 重算 dur/at/total，并重新排字幕（末尾 4 行 × 8 拍）。"""
    beat = 60.0 / float(bpm)
    total = 0.0
    for c in edl["video"]:
        c["dur"] = round(float(c["beats"]) * beat, 3)
        c["at"] = round(total, 3)
        total += c["dur"]
    edl["total"] = round(total, 3)
    for a in edl.get("audio", []):
        a["dur"] = edl["total"]
    span = 8 * beat
    n = len(edl.get("subs", []))
    if n:
        start = max(0.0, edl["total"] - span * n)
        for i, s in enumerate(edl["subs"]):
            s["start"] = round(start + i * span, 3)
            s["end"] = round(start + (i + 1) * span - 0.10, 3)
    return edl


def clamp_clip(edl, index, src_duration):
    """把片段的源起点限制在素材范围内。"""
    c = edl["video"][index]
    c["start"] = round(max(0.0, min(float(c["start"]), max(0.0, src_duration - c["dur"]))), 3)
    return edl
