"""批量跑同一个解法：转码 → 逐个执行 → 汇总质检。"""
import copy, glob, json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import ops, builtin_ops, solution as SOL, runner, ffmpeg as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)


def to_mp4(src, dst):
    if os.path.exists(dst) and os.path.getsize(dst) > 1000:
        return dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    # AVFoundation 读不了 webm：先转成 H.264 mp4，同时统一成 30fps
    p = F.run(["-y", "-i", src, "-vf", "fps=30,scale=-2:720", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "20", "-c:a", "aac", "-b:a", "128k", dst])
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-300:])
    return dst


def main(sol_path, clips, out_dir="out/batch"):
    sol0 = SOL.load(sol_path, ops.OPS)
    os.makedirs(out_dir, exist_ok=True)
    rows, t_all = [], time.time()
    for i, clip in enumerate(clips):
        mp4 = os.path.join(out_dir, f"src_{i:02d}.mp4")
        try:
            to_mp4(clip, mp4)
        except Exception as e:
            rows.append(dict(i=i, clip=os.path.basename(clip), ok=False, failed=f"TRANSCODE:{str(e)[:60]}",
                             dur=0, lufs=None, sharp=None, black=0, segs=0, secs=0))
            continue
        sol = copy.deepcopy(sol0)
        for st in sol["steps"]:
            if st["op"] == "render.edl":
                st["params"]["out"] = f"{out_dir}/{i:02d}.mp4"
        t0 = time.time()
        try:
            ctx = runner.run(sol, ROOT, overrides={"source": mp4}, yes=True, on_log=lambda *_: None)
            qc = [s for s in ctx["log"] if s["op"] == "qc.report"][0]["result"]
            sel = [s for s in ctx["log"] if s["op"] in ("select.auto", "select.action", "select.semantic")][0]["result"]
            pre = next((s["result"] for s in ctx["log"] if s["op"] == "qc.source"), {})
            if qc["pass"]:
                json.dump({"solution": sol["id"], "steps": ctx["log"]},
                          open(os.path.join(ROOT, "out", f"run_{sol['id']}.json"), "w"),
                          ensure_ascii=False, indent=1)
            rows.append(dict(i=i, clip=os.path.basename(clip), ok=qc["pass"], failed=",".join(qc["failed"]),
                             dur=qc["duration"], lufs=qc["lufs"], sharp=qc["sharpness"], black=qc["black"],
                             segs=sel["segments"], secs=round(time.time() - t0, 1),
                             sem=sel.get("sem"), pre=pre.get("verdict"), pre_p=pre.get("sport_prob"),
                             out=f"{out_dir}/{i:02d}.mp4"))
        except Exception as e:
            rows.append(dict(i=i, clip=os.path.basename(clip), ok=False, failed=f"ERROR:{str(e)[:60]}",
                             dur=0, lufs=None, sharp=None, black=0, segs=0, secs=round(time.time() - t0, 1)))
        r = rows[-1]
        print(f"{i:02d} {r['clip']:10} ok={str(r['ok']):5} segs={r['segs']:2} {r['secs']:5.1f}s {r['failed']}")
    json.dump(rows, open(os.path.join(out_dir, "rows.json"), "w"), ensure_ascii=False, indent=1)
    ok = sum(1 for r in rows if r["ok"])
    print(f"\n{ok}/{len(rows)} 通过，总耗时 {time.time() - t_all:.0f}s")
    return rows


if __name__ == "__main__":
    clips = sorted(glob.glob(sys.argv[2])) if len(sys.argv) > 2 else sorted(glob.glob("assets/batch/*.webm"))
    main(sys.argv[1] if len(sys.argv) > 1 else "solutions/sports-highlight.solution.json", clips)
