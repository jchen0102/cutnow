"""素材分析：镜头切分、音频解码、节拍估计、逐帧特征聚合。"""
import json, re, subprocess
import numpy as np
from . import ffmpeg as F


# ---------- 音频 ----------

class NoAudioError(RuntimeError):
    """源文件没有音轨。"""


def decode_audio(path: str, sr: int = 22050) -> np.ndarray:
    p = subprocess.run([F.ffmpeg(), "-hide_banner", "-nostdin", "-i", path,
                        "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
                       capture_output=True)
    if p.returncode != 0:
        msg = p.stderr.decode("utf-8", "ignore")
        if "does not contain any stream" in msg or "Output file #0 does not contain" in msg:
            raise NoAudioError(f"{path} 没有音轨")
        raise RuntimeError(msg[-800:])
    return np.frombuffer(p.stdout, dtype=np.float32)


def _stft_mag(x, n_fft=1024, hop=512):
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x)))
    n = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(n_fft)[None, :]
    return np.abs(np.fft.rfft(frames, axis=1))


def onset_envelope(x, n_fft=1024, hop=512):
    S = _stft_mag(x, n_fft, hop)
    d = np.diff(S, axis=0, prepend=S[:1])
    flux = np.maximum(d, 0).sum(axis=1)
    flux = flux - flux.mean()
    flux = np.maximum(flux, 0)
    return flux / (flux.max() + 1e-9), hop


def estimate_beat(x, sr=22050, bpm_range=(70, 190)):
    """自相关估 tempo + 梳状滤波定相位，返回 (bpm, beat_times_sec)。"""
    env, hop = onset_envelope(x)
    fps = sr / hop
    e = env - env.mean()
    ac = np.correlate(e, e, "full")[len(e) - 1:]
    lo = int(fps * 60 / bpm_range[1]); hi = int(fps * 60 / bpm_range[0])
    lag = lo + int(np.argmax(ac[lo:hi]))
    bpm = 60 * fps / lag

    # 相位：在 [0, lag) 内找使节拍点能量和最大的偏移
    best, best_off = -1, 0
    for off in range(lag):
        idx = np.arange(off, len(env), lag).astype(int)
        s = env[idx].sum()
        if s > best:
            best, best_off = s, off
    beats = np.arange(best_off, len(env), lag) / fps
    return round(bpm, 2), beats


def loudest_window(x, sr, dur):
    """能量最大的 dur 秒窗口起点（用于自动取副歌）。"""
    win = int(sr * dur)
    if len(x) <= win:
        return 0.0
    step = int(sr * 0.5)
    frames = 1 + (len(x) - win) // step
    idx = np.arange(win)[None, :] + step * np.arange(frames)[:, None]
    energy = (x[idx] ** 2).mean(axis=1)
    # 平滑，避免选到单次爆炸音
    k = max(1, int(2 / 0.5))
    sm = np.convolve(energy, np.ones(k) / k, mode="same")
    return float(np.argmax(sm) * step / sr)


# ---------- 视频 ----------

def scenes(path: str, threshold: float = 0.3):
    """ffmpeg scene 检测，返回 [(start, end)]。"""
    p = F.run(["-i", path, "-filter_complex", f"select='gt(scene,{threshold})',showinfo",
               "-f", "null", "-"])
    cuts = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", p.stderr)]
    dur = F.probe(path)["duration"]
    pts = [0.0] + [c for c in cuts if 0.3 < c < dur - 0.3]
    out = []
    for i, s in enumerate(pts):
        e = pts[i + 1] if i + 1 < len(pts) else dur
        if e - s >= 0.35:
            out.append((round(s, 3), round(e, 3)))
    return out


def load_features(path: str):
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def aggregate(rows, start, end):
    sel = [r for r in rows if start <= r["t"] < end]
    if not sel:
        return {"n": 0, "luma": 0, "motion": 0, "face_area": 0, "faces": 0}
    return {
        "n": len(sel),
        "luma": float(np.mean([r["luma"] for r in sel])),
        "motion": float(np.mean([r["motion"] for r in sel])),
        "face_area": float(np.max([r["face_area"] for r in sel])),
        "faces": float(np.mean([r["faces"] for r in sel])),
    }
