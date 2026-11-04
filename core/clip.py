"""极简 CLIP（ONNX）：给画面打语义分，用于选段与素材准入。"""
import os, sys
import numpy as np

from .config import clip_dir

MODEL_DIR = str(clip_dir())
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

_sess = {}


def _ort():
    try:
        import onnxruntime as ort
    except ImportError as e:
        raise RuntimeError("CLIP 需要 onnxruntime：pip install 'vcut[clip]'") from e
    return ort


def _session(kind):
    if kind in _sess:
        return _sess[kind]
    ort = _ort()
    # CoreML 在 text 模型上会崩（embedding 维度超限），统一走 CPU；ViT-B/32 单图约 40ms，够用
    prov = ["CPUExecutionProvider"]
    p = os.path.join(MODEL_DIR, f"{kind}_model.onnx")
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    _sess[kind] = ort.InferenceSession(p, sess_options=so, providers=prov)
    return _sess[kind]


def _tok():
    if "tok" in _sess:
        return _sess["tok"]
    try:
        from tokenizers import Tokenizer
    except ImportError as e:
        raise RuntimeError("CLIP 需要 tokenizers：pip install 'vcut[clip]'") from e
    _sess["tok"] = Tokenizer.from_file(os.path.join(MODEL_DIR, "tokenizer.json"))
    return _sess["tok"]


def encode_text(prompts, batch=16):
    s = _session("text")
    names = [i.name for i in s.get_inputs()]
    tok = _tok()
    out = []
    for i in range(0, len(prompts), batch):
        chunk = prompts[i:i + batch]
        enc = [tok.encode(p) for p in chunk]
        maxlen = max(len(e.ids) for e in enc)
        ids = np.zeros((len(chunk), maxlen), dtype=np.int64)
        mask = np.zeros((len(chunk), maxlen), dtype=np.int64)
        for j, e in enumerate(enc):
            ids[j, :len(e.ids)] = e.ids
            mask[j, :len(e.ids)] = 1
        feed = {"input_ids": ids, "attention_mask": mask}
        feed = {k: v for k, v in feed.items() if k in names}
        res = s.run(None, feed)
        emb = res[0]
        if emb.ndim == 3:            # last_hidden_state → 取 EOS（最大 id 位置）
            emb = emb[np.arange(len(chunk)), np.argmax(ids, axis=1)]
        out.append(emb)
    e = np.concatenate(out).astype(np.float32)
    return e / np.maximum(np.linalg.norm(e, axis=-1, keepdims=True), 1e-8)


def encode_images(images):
    """images: list of HxWx3 uint8 RGB."""
    s = _session("vision")
    names = [i.name for i in s.get_inputs()]
    x = np.stack([((im.astype(np.float32) / 255.0 - MEAN) / STD).transpose(2, 0, 1) for im in images]).astype(np.float32)
    res = s.run(None, {"pixel_values": x} if "pixel_values" in names else {names[0]: x})
    e = res[0]
    if e.ndim == 3:
        e = e[:, 0]
    e = e.astype(np.float32)
    return e / np.maximum(np.linalg.norm(e, axis=-1, keepdims=True), 1e-8)


def similarity(image_embs, prompt_sets):
    """prompt_sets: {label: [prompts]} → 每张图在每个 label 上的概率（softmax over labels）。"""
    labels = list(prompt_sets)
    text = np.concatenate([encode_text(prompt_sets[k]) for k in labels])
    with np.errstate(all="ignore"):
        sims = np.nan_to_num(image_embs @ text.T, nan=0.0, posinf=1.0, neginf=-1.0)   # (N, sum prompts)
    logits = sims * 100.0
    probs = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs /= probs.sum(axis=1, keepdims=True)
    out, i = [], 0
    for k in labels:
        n = len(prompt_sets[k])
        out.append(probs[:, i:i + n].sum(axis=1))
        i += n
    return np.stack(out, axis=1), labels
