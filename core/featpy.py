"""纯 Python 的逐帧特征提取：不依赖 macOS Vision 二进制，Linux/Windows 也能跑。

字段与 Swift 版保持一致（t/luma/motion/faces/face_area/face_x/sat/edge/humans/human_area），
其中 faces/humans 没有检测器时为 0，human_area 用「中心区与边缘区的细节差」做代理。
"""
import json
import numpy as np
from . import frames as FR


def _saturation(img: np.ndarray) -> float:
    """RGB → 饱和度均值（0-255）。"""
    a = img.astype(np.float32)
    mx = a.max(axis=2)
    mn = a.min(axis=2)
    denom = np.where(mx <= 1e-3, 1.0, mx)
    return float(np.mean((mx - mn) / denom) * 255.0)


def _edges(gray: np.ndarray) -> float:
    """Sobel 梯度均值，量级接近 Swift 版的 edge。"""
    g = gray.astype(np.float32)
    gx = np.abs(np.diff(g, axis=1)).mean() if g.shape[1] > 1 else 0.0
    gy = np.abs(np.diff(g, axis=0)).mean() if g.shape[0] > 1 else 0.0
    return float((gx + gy) * 0.7)   # 对齐 Swift 版的 edge 量级


def _subject(gray: np.ndarray) -> float:
    """中心区细节 / 全图细节 − 1 的截断值，当作「主体占比」的代理（0-1）。"""
    h, w = gray.shape
    cy0, cy1 = int(h * 0.25), int(h * 0.75)
    cx0, cx1 = int(w * 0.25), int(w * 0.75)
    center = _edges(gray[cy0:cy1, cx0:cx1])
    whole = _edges(gray) or 1.0
    return float(max(0.0, min(1.0, (center / whole) - 1.0)))


def extract(video, out_path, interval=0.5, size=64):
    fps = 1.0 / max(0.05, float(interval))
    times, imgs = FR.grab(video, fps=fps, size=size)
    prev, rows = None, []
    for t, img in zip(times, imgs):
        gray = img.astype(np.float32).mean(axis=2)
        motion = 0.0 if prev is None else float(np.abs(gray - prev).mean() * 2.0)
        rows.append({
            "t": round(float(t), 2),
            "luma": round(float(gray.mean()), 2),
            "motion": round(motion, 2),
            "faces": 0, "face_area": 0.0, "face_x": 0.0,
            "sat": round(_saturation(img), 2),
            "edge": round(_edges(gray), 2),
            "humans": 0,
            "human_area": round(_subject(gray) * 0.25, 4),
        })
        prev = gray
    with open(out_path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows
