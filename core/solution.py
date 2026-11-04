"""解法（solution）加载与校验：声明式，不含可执行代码。"""
import json, os

STEP_KEYS = {"id", "op", "params", "gate", "optional", "capability"}
GATES = {None, "confirm", "pick"}
CAPS = {"", "cloud", "gpu", "paid"}


class SolutionError(Exception):
    pass


def _load_raw(path):
    ext = os.path.splitext(path)[1].lower()
    with open(path, encoding="utf-8") as fh:
        if ext in (".json",):
            return json.load(fh)
        if ext in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError:
                raise SolutionError("读 .yaml 需要 pyyaml；当前环境没有，请用 .json")
            return yaml.safe_load(fh)
    raise SolutionError(f"不认识的解法扩展名：{ext}")


def validate(sol, ops):
    errs = []
    for k in ("id", "name", "inputs", "steps"):
        if k not in sol:
            errs.append(f"缺少字段 {k}")
    if errs:
        return errs

    if not isinstance(sol["inputs"], dict) or not sol["inputs"]:
        errs.append("inputs 必须是非空对象")
    else:
        for iid, spec in sol["inputs"].items():
            if not isinstance(spec, dict) or "type" not in spec:
                errs.append(f"input {iid} 缺少 type")

    kind = sol.get("output_kind", "mp4")
    if kind not in ("suggestion", "timeline", "mp4"):
        errs.append("output_kind 只能是 suggestion / timeline / mp4")

    seen = set()
    for i, st in enumerate(sol["steps"]):
        where = f"steps[{i}]"
        if not isinstance(st, dict):
            errs.append(f"{where} 必须是对象"); continue
        unknown = set(st) - STEP_KEYS
        if unknown:
            errs.append(f"{where} 有未知字段 {sorted(unknown)}")
        if "op" not in st:
            errs.append(f"{where} 缺少 op"); continue
        if st["op"] not in ops:
            errs.append(f"{where} 引用了未注册的 op：{st['op']}")
        sid = st.get("id") or st["op"]
        if sid in seen:
            errs.append(f"{where} id 重复：{sid}")
        seen.add(sid)
        g = st.get("gate")
        if g not in GATES:
            errs.append(f"{where} gate 只能是 {sorted(x for x in GATES if x)}")
        c = st.get("capability", "")
        if c not in CAPS:
            errs.append(f"{where} capability 只能是 {sorted(x for x in CAPS if x)}")
    return errs


def load(path, ops):
    sol = _load_raw(path)
    errs = validate(sol, ops)
    if errs:
        raise SolutionError("；".join(errs))
    sol["_path"] = path
    return sol


def discover(dirs):
    out = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith((".solution.json", ".solution.yaml", ".solution.yml")):
                out.append(os.path.join(d, fn))
    return out
