"""一次 ffmpeg 调用把整段素材抽成小帧序列，供语义打分复用。"""
import subprocess
import numpy as np
from . import ffmpeg as F


def grab(path, fps=2.0, size=224, limit=1200):
    """返回 (times[], frames[])；frames 为 HxWx3 uint8 RGB。"""
    cmd = [F.ffmpeg(), "-hide_banner", "-nostdin", "-i", path,
           "-vf", f"fps={fps},scale={size}:{size}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    p = subprocess.run(cmd, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "ignore")[-500:])
    buf = np.frombuffer(p.stdout, dtype=np.uint8)
    n = len(buf) // (size * size * 3)
    n = min(n, limit)
    frames = buf[: n * size * size * 3].reshape(n, size, size, 3)
    times = [i / fps for i in range(n)]
    return times, frames
