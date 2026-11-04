"""算子注册表：解法只能引用这里已注册的 op，不能写任意代码。"""
OPS = {}


class OpError(Exception):
    pass


def register(name, description="", inputs=None, outputs=None):
    def deco(fn):
        fn.op_name = name
        fn.op_description = description
        fn.op_inputs = inputs or []
        fn.op_outputs = outputs or []
        OPS[name] = fn
        return fn
    return deco


def get(name):
    if name not in OPS:
        raise OpError(f"未注册的 op：{name}（可用：{', '.join(sorted(OPS))}）")
    return OPS[name]


def names():
    return sorted(OPS)


def describe():
    return [{"name": n, "description": OPS[n].op_description,
             "inputs": OPS[n].op_inputs, "outputs": OPS[n].op_outputs} for n in names()]
