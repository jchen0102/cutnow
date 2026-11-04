"""剪辑规划：候选窗口 → 打分 → 结构选段（冷开场/中段/收尾）→ 卡点 EDL。

打分只看可测的东西：运动能量、色彩饱和度、主体占比（Vision 人体）、清晰度（梯度）、过暗惩罚。
不做"人物/观众"的语义分类——那需要身份或场景模型，此处不假装有。
"""
import json


def score(f):
    motion = min(f["motion"] / 30.0, 1.0)
    sat = min(f["sat"] / 110.0, 1.0)
    subject = min(f.get("human_area", 0.0) / 0.12, 1.0)
    sharp = min(f.get("edge", 0.0) / 12.0, 1.0)
    base = 0.36 * motion + 0.28 * sat + 0.20 * subject + 0.16 * sharp
    dark = 1.0 if f["luma"] >= 35 else 0.5 + 0.5 * (f["luma"] / 35.0)
    nf = f.get("med_faces", 0)
    crowd = 1.0 if nf <= 1 else (0.85 if nf <= 2 else (0.55 if nf <= 4 else 0.35))
    return round(base * dark * crowd, 4)


def window_stats(rows, s, e):
    sel = [r for r in rows if s <= r["t"] < e]
    if not sel:
        return None
    n = len(sel)
    avg = lambda k: sum(r.get(k, 0) for r in sel) / n
    med_faces = sorted(r["faces"] for r in sel)[n // 2]
    return {"n": n, "luma": avg("luma"), "motion": avg("motion"), "sat": avg("sat"),
            "edge": avg("edge"), "human_area": avg("human_area"),
            "face_area": sorted(r["face_area"] for r in sel)[n // 2],
            "med_faces": med_faces}


def candidates(scenes, rows, beat, beats=(4, 8, 12), regions=None):
    out = []
    for s, e in scenes:
        if regions:
            keep = [(max(s, a), min(e, b)) for a, b in regions if min(e, b) > max(s, a)]
            if not keep:
                continue
        for b in beats:
            L = b * beat
            for rs, re_ in (keep if regions else [(s, e)]):
              t = rs
              while t + L <= re_ + 1e-6:
                st = window_stats(rows, t, t + L)
                if st:
                    out.append({"start": round(t, 2), "beats": b, "dur": round(L, 3),
                                "score": score(st), "feat": st})
                t += 0.5
        if regions:
            continue
        for b in beats:
            L = b * beat
            t = s
            while t + L <= e + 1e-6:
                st = window_stats(rows, t, t + L)
                if st:
                    out.append({"start": round(t, 2), "beats": b, "dur": round(L, 3),
                                "score": score(st), "feat": st})
                t += 0.5
    return out


def _free(c, chosen, min_gap):
    return all(abs(c["start"] - u["start"]) >= min_gap for u in chosen)


def pick(cands, total, beat, open_window=32.0, tail_window=90.0, gap=25.0):
    target_beats = int(round(total / beat / 2)) * 2
    chosen = []

    # 1. 冷开场：原片开头（第一个镜头跨度内）的最高分位置
    head = [c for c in cands if c["start"] < open_window]
    if head:
        b = 8 if target_beats >= 24 else 4
        pool = [c for c in head if c["beats"] == b] or head
        chosen.append(max(pool, key=lambda c: c["score"]))

    # 2. 收尾：末尾段最高分
    last_start = max(c["start"] for c in cands)
    tail = [c for c in cands if c["start"] > last_start - tail_window and _free(c, chosen, 20)]
    if tail:
        chosen.append(max(tail, key=lambda c: c["score"]))

    # 3. 中段：主体镜头为主、人群镜头作反应插入（配额 4:1）
    used = sum(c["beats"] for c in chosen)
    pattern = [12, 8, 4, 8, 4, 8, 4, 4]
    i = 0
    single = sorted([c for c in cands if c["feat"].get("med_faces", 0) <= 1], key=lambda c: -c["score"])
    crowd = sorted([c for c in cands if c["feat"].get("med_faces", 0) > 1], key=lambda c: -c["score"])
    pool = single
    while used < target_beats and i < len(pattern):
        b = pattern[i]
        if used + b > target_beats:
            b = target_beats - used
        use_crowd = (len(chosen) % 5 == 0) and crowd          # 每 5 段插一个反应镜头
        src_pool = crowd if use_crowd else pool
        cand = [c for c in src_pool if c["beats"] == b and _free(c, chosen, gap)]
        if not cand:
            cand = [c for c in pool if c["beats"] == b and _free(c, chosen, gap)]
        if cand:
            chosen.append(cand[0]); used += b; i += 1
        else:
            i += 1
            if i >= len(pattern) and used < target_beats:
                # 放宽间隔再试一轮
                cand = [c for c in pool if c["beats"] == 4 and _free(c, chosen, 8.0)]
                if not cand:
                    break
                chosen.append(cand[0]); used += 4; i = len(pattern) - 1

    chosen.sort(key=lambda c: c["start"])
    return chosen, sum(c["beats"] for c in chosen)


def build_edl(recipe, scenes, rows, music_info):
    beat = 60.0 / music_info["bpm"]
    cands = []
    if recipe.get("shots"):
        chosen = [{"start": s, "beats": b, "dur": round(b * beat, 3), "score": None,
                   "feat": window_stats(rows, s, s + b * beat) or {}}
                  for s, b in recipe["shots"]]
    else:
        cands = candidates(scenes, rows, beat, regions=recipe.get("regions"))
        chosen, _ = pick(cands, recipe["target_seconds"], beat,
                         gap=6.0 if recipe.get("regions") else 25.0)

    video, t_in = [], 0.0
    for i, c in enumerate(chosen):
        role = "冷开场" if i == 0 else ("收尾" if i == len(chosen) - 1 else "发展")
        video.append({"asset": "src", "start": c["start"], "dur": round(c["beats"] * beat, 3),
                      "at": round(t_in, 3), "role": role, "beats": c["beats"],
                      "score": c["score"],
                      "feat": {k: round(v, 3) for k, v in (c["feat"] or {}).items() if isinstance(v, (int, float))}})
        t_in += c["dur"]
    total = round(t_in, 3)

    music = [{"asset": "music", "in": round(music_info["chorus_start"], 3), "dur": total, "gain_db": 0.0}]
    subs = plan_subs(recipe, total, beat)

    ops = [
        {"op": "scene_split", "params": {"threshold": recipe["scene_threshold"]},
         "evidence": f"{len(scenes)} 个镜头边界（ffmpeg scene 分数）"},
        {"op": "window_scoring",
         "params": {"motion": 0.36, "sat": 0.28, "subject": 0.20, "sharp": 0.16},
         "evidence": (f"{len(cands)} 个候选窗口；Vision 人体 + 帧间运动 + 饱和度 + 梯度"
                      if cands else "人工指定镜头（pinned），未启用自动候选")},
        {"op": "shot_list",
         "params": {"mode": "pinned" if recipe.get("shots") else "auto",
                    "cold_open": None if recipe.get("shots") else "前 32s 最高分",
                    "middle": None if recipe.get("shots") else "分数排序 + 间隔 ≥25s"},
         "evidence": f"{len(video)} 段，共 {total}s"},
        {"op": "beat_slot", "params": {"bpm": music_info["bpm"],
                                       "beats": [v["beats"] for v in video]},
         "evidence": "时长按拍数切分（12/8/4 拍混排），切点落在节拍上"},
        {"op": "music_chorus", "params": {"method": "loudest_window", "window": total},
         "evidence": f"能量最大窗口起点 {round(music_info['chorus_start'], 2)}s"},
        {"op": "mask_source_subs", "params": {"crop_bottom_px": recipe["cleanup"]["crop_bottom"]},
         "evidence": "原片自带中英双语硬字幕，裁掉底部字幕条"},
        {"op": "subtitle_cues", "params": {"template": "tutorial_rewrite", "lines": len(subs)},
         "evidence": "教程样片的中文改词，每 2 小节一行"},
    ]
    return {"version": 1, "id": recipe["id"], "output": recipe["output"],
            "cleanup": recipe["cleanup"], "assets": recipe["assets"],
            "video": video, "audio": music, "subs": subs, "ops": ops, "total": total}


def plan_subs(recipe, total, beat):
    lines = recipe.get("subtitle_lines") or []
    if not lines:
        return []
    span = 8 * beat
    start = max(0.0, total - span * len(lines))
    return [{"start": round(start + i * span, 3),
             "end": round(start + (i + 1) * span - 0.10, 3), "text": t}
            for i, t in enumerate(lines)]
