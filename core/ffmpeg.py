"""ffmpeg 定位与薄封装。"""
import os, subprocess, json, re, sys

from .config import ffmpeg  # noqa: F401  统一由 config 解析（env > PATH > imageio_ffmpeg）

def run(args, capture=True):
    p = subprocess.run([ffmpeg(), "-hide_banner", "-nostdin", *args],
                       capture_output=capture, text=True)
    return p

def probe(path: str) -> dict:
    """时长/分辨率/帧率/是否有音轨。"""
    p = run(["-i", path])
    err = p.stderr
    dur = 0.0
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", err)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    v = re.search(r"Video: .*?, (\d+)x(\d+)", err)
    f = re.search(r"(\d+(?:\.\d+)?) fps", err)
    has_audio = "Audio:" in err
    return {"path": path, "duration": round(dur, 3),
            "width": int(v.group(1)) if v else None,
            "height": int(v.group(2)) if v else None,
            "fps": float(f.group(1)) if f else None,
            "has_audio": has_audio}

def sha256(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
