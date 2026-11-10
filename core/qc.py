"""成片客观质检：交付前跑一遍，别靠"看起来还行"。"""
import os, re, subprocess, sys
from . import ffmpeg as F




def _run(args):
    return subprocess.run([F.ffmpeg(), "-hide_banner", "-nostdin", *args],
                          capture_output=True, text=True)


def duration(path):
    return F.probe(path)["duration"]


def black_frames(path, d=0.2, pix_th=0.10):
    p = _run(["-i", path, "-vf", f"blackdetect=d={d}:pix_th={pix_th}", "-an", "-f", "null", "-"])
    segs = re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", p.stderr)
    return [{"start": float(a), "end": float(b)} for a, b in segs]


def loudness(path):
    p = _run(["-i", path, "-af", "ebur128=framelog=verbose", "-f", "null", "-"])
    m = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", p.stderr)
    tp = re.findall(r"Peak:\s*(-?[\d.]+)\s*dBFS", p.stderr)
    return {"integrated_lufs": float(m[-1]) if m else None,
            "true_peak_dbfs": float(tp[-1]) if tp else None}


def sharpness(path, points=(0.2, 0.5, 0.8)):
    """拉普拉斯方差（越大越清晰）；opencv 不可用就返回 None。"""
    try:
        import cv2
    except Exception:
        return None
    total = duration(path)
    cap = cv2.VideoCapture(path)
    vals = []
    for f in points:
        cap.set(cv2.CAP_PROP_POS_MSEC, f * total * 1000)
        ok, frame = cap.read()
        if not ok:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        vals.append(round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 2))
    cap.release()
    return round(sum(vals) / len(vals), 2) if vals else None


def subtitle_fit(edl):
    """按当前字号估算每行最多能放多少字。"""
    w = edl["output"]["width"]; h = edl["output"]["height"]
    font = max(18, min(int(h * 0.058), int(w * 0.055)))   # 与 render 的字号规则保持一致
    limit = max(4, int(w * 0.92 / font))
    worst = max((len(s["text"]) for s in edl.get("subs", [])), default=0)
    return {"max_chars_per_line": limit, "longest_cue": worst,
            "overflow": worst > limit}


def report(path, edl, thresholds=None, ignore=None, skip_subtitles=False):
    th = {"duration_tolerance": 0.15, "black_max": 0.5,
          "lufs_min": -26.0, "lufs_max": -10.0, "sharp_min": 30.0}
    th.update(thresholds or {})

    ignore = ignore or []
    dur = duration(path)
    expect = float(edl.get("total") or 0)
    blacks = black_frames(path)
    def _covered(b):
        span = max(1e-6, b["end"] - b["start"])
        cover = sum(max(0.0, min(b["end"], z) - max(b["start"], a)) for a, z in ignore)
        return cover / span >= 0.8
    blacks = [b for b in blacks if not _covered(b)]
    loud = loudness(path)
    sharp = sharpness(path, points=(0.35, 0.5, 0.65))
    subs = subtitle_fit(edl)
    if skip_subtitles:
        subs = {"max_chars_per_line": subs["max_chars_per_line"], "longest_cue": subs["longest_cue"],
                "overflow": False, "skipped": True}

    checks = {
        "duration": {"value": round(dur, 3), "expect": expect,
                     "ok": abs(dur - expect) <= th["duration_tolerance"]},
        "black_frames": {"count": len(blacks),
                         "ok": all(b["end"] - b["start"] <= th["black_max"] for b in blacks),
                         "segments": blacks[:5]},
        "loudness": {"lufs": loud["integrated_lufs"],
                     "ok": loud["integrated_lufs"] is None or th["lufs_min"] <= loud["integrated_lufs"] <= th["lufs_max"]},
        "subtitles": {**subs, "ok": not subs["overflow"]},
        "sharpness": {"laplacian_var": sharp,
                      "ok": sharp is None or sharp >= th["sharp_min"]},
    }
    failed = [k for k, v in checks.items() if not v["ok"]]
    return {"file": path, "pass": not failed, "failed": failed, "thresholds": th, "checks": checks}
