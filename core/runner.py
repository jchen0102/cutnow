"""解法执行器：按声明顺序跑 op，记录每步结果；闸门未确认则不执行。"""
import json, os, time
from . import ops
from . import solution as S


class GateDeclined(Exception):
    pass


def _default_inputs(sol, overrides):
    out = {}
    for k, spec in sol["inputs"].items():
        out[k] = (overrides or {}).get(k) or spec.get("default")
        if spec.get("required") and not out[k]:
            raise ValueError(f"缺少输入：{k}（{spec.get('type')}）")
    return out


def run(sol, root, overrides=None, yes=False, allow_caps=("",), on_log=print):
    inputs = _default_inputs(sol, overrides)
    ctx = {
        "root": root,
        "solution": sol,
        "inputs": inputs,
        "edl": {
            "version": 1,
            "id": sol["id"],
            "output": sol.get("output", {"width": 1280, "height": 720, "fps": 30}),
            "assets": [
                {"id": "src", "path": inputs.get("source")},
                {"id": "music", "path": inputs.get("music")},
            ],
        },
        "log": [],
    }
    ctx["edl"]["assets"] = [a for a in ctx["edl"]["assets"] if a["path"]]

    for i, st in enumerate(sol["steps"]):
        name = st["op"]
        sid = st.get("id") or name
        cap = st.get("capability", "")
        if cap and cap not in allow_caps:
            if st.get("optional", True):
                ctx["log"].append({"id": sid, "op": name, "skipped": f"缺少能力 {cap}"})
                on_log(f"  [{i+1}/{len(sol['steps'])}] {sid:12} 跳过（需要 {cap}）")
                continue
            raise RuntimeError(f"步骤 {sid} 需要能力 {cap}，当前未授权")

        if st.get("gate") and not yes:
            ans = input(f"  [{i+1}/{len(sol['steps'])}] {sid} 需要确认，继续？[Y/n] ").strip().lower()
            if ans not in ("", "y", "yes"):
                raise GateDeclined(f"第 {i+1} 步 {sid} 被拒绝")

        t0 = time.time()
        result = ops.get(name)(ctx, st.get("params") or {})
        dt = round(time.time() - t0, 2)
        ctx["log"].append({"id": sid, "op": name, "params": st.get("params"),
                           "result": result, "seconds": dt})
        on_log(f"  [{i+1}/{len(sol['steps'])}] {sid:12} {dt:>6.2f}s  {json.dumps(result, ensure_ascii=False)[:110]}")

    return ctx
