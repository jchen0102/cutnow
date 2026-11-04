"""运动素材的选段信号：音频能量 + 画面运动 + 主体占比 + 场景对齐。"""
import numpy as np
from . import analyze as A


def audio_env(path, hop=0.1, sr=22050):
    """整段音频的短时能量包络（0-1 归一化）。"""
    x = A.decode_audio(path, sr)
    if x is None or len(x) == 0:
        return None, sr
    n = int(hop * sr)
    frames = len(x) // n
    if frames < 2:
        return None, sr
    e = np.array([float(np.sqrt(np.mean(x[i * n:(i + 1) * n] ** 2))) for i in range(frames)])
    hi = np.percentile(e, 95) or 1.0
    return np.clip(e / hi, 0, 1), hop


def env_stats(env, hop, s, e):
    if env is None:
        return 0.0, 0.0
    a, b = int(s / hop), int(e / hop)
    seg = env[max(0, a):max(1, b)]
    if len(seg) == 0:
        return 0.0, 0.0
    return float(np.mean(seg)), float(np.percentile(seg, 90))


def scene_candidates(scenes, rows, env, hop, beat, beats=(4, 8, 12), pad=0.15):
    """在场景内部平铺开窗：切点对齐镜头边界与前一个窗尾，长镜头也能被多次使用。"""
    out = []
    for s, e in scenes:
        span = e - s
        if span < 1.2:
            continue
        for b in beats:
            L = b * beat
            if L > span + 0.45:
                continue
            k = 0
            while True:
                st = s + pad + k * L
                if st + L > e + 0.45:
                    break
                k += 1
                rows_in = [r for r in rows if st <= r["t"] < st + L]
                if len(rows_in) < 2:
                    continue
                n = len(rows_in)
                avg = lambda key: sum(r.get(key, 0) for r in rows_in) / n
                a_mean, a_p90 = env_stats(env, hop, st, st + L)
                out.append({"start": round(st, 2), "beats": b, "dur": round(L, 3),
                            "scene": (s, e),
                            "motion": avg("motion"),
                            "motion_min": min(r.get("motion", 0) for r in rows_in),
                            "human": avg("human_area"), "luma": avg("luma"), "edge": avg("edge"),
                            "audio": a_mean, "audio_peak": a_p90})
    return out


def score_action(c, clip_p75_motion=20.0, clip_p60_audio=0.3):
    motion = min(c["motion"] / max(clip_p75_motion * 1.6, 1e-6), 1.0)
    sustain = min(c["motion_min"] / max(clip_p75_motion * 0.6, 1e-6), 1.0)
    audio = min(c["audio_peak"] / max(clip_p60_audio * 1.8, 1e-6), 1.0)
    human = min(c["human"] / 0.10, 1.0)
    dark = 1.0 if c["luma"] >= 35 else max(0.4, c["luma"] / 35.0)
    base = 0.34 * motion + 0.16 * sustain + 0.30 * audio + 0.12 * human + 0.08 * min(c["edge"] / 14.0, 1.0)
    return round(base * dark, 4)


def pick_action(cands, target, beat, gap_ratio=1.15):
    """贪心：分数最高优先，窗口之间至少隔 1.4 个窗长，避免同一段反复用。"""
    chosen, used = [], 0.0
    target_beats = max(2, int(round(target / beat)))
    for c in sorted(cands, key=lambda x: -x.get("score", x.get("action", 0.0))):
        if used >= target_beats:
            break
        if any(abs(c["start"] - o["start"]) < max(c["dur"], o["dur"]) * gap_ratio for o in chosen):
            continue
        same = [o for o in chosen if o["scene"] == c["scene"]]
        span = c["scene"][1] - c["scene"][0]
        cap = max(2, int(span / max(c["dur"], 0.5)))
        if len(same) >= cap:
            continue
        chosen.append(c)
        used += c["beats"]
    chosen.sort(key=lambda c: c["start"])
    return chosen, used
