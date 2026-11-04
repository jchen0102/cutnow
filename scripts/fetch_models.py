#!/usr/bin/env python3
"""按需下载可选模型到缓存目录（默认 ~/.cache/vcut）。"""
import argparse, os, sys, urllib.request
from pathlib import Path

CACHE = Path(os.environ.get("VCUT_CACHE") or (Path.home() / ".cache" / "vcut"))
CLIP_BASE = "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main"
CLIP_FILES = ["onnx/vision_model.onnx", "onnx/text_model.onnx", "tokenizer.json"]
WHISPER_BASE = "https://hf-mirror.com/ggerganov/whisper.cpp/resolve/main"


def fetch(url, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file() and dst.stat().st_size > 1024:
        print(f"  skip {dst.name} ({dst.stat().st_size/1e6:.0f}MB)")
        return
    print(f"  ↓ {dst.name}")
    with urllib.request.urlopen(url, timeout=120) as r, open(dst, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r    {done/1e6:6.1f}/{total/1e6:6.1f} MB", end="")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", action="store_true", help="CLIP 语义模型（选段/准入，约 600MB）")
    ap.add_argument("--whisper", default=None, choices=["base", "small", "medium"],
                    help="whisper 中文模型（口播解法）")
    a = ap.parse_args()
    if not a.clip and not a.whisper:
        ap.print_help()
        return 1
    if a.clip:
        print("CLIP →", CACHE / "clip")
        for f in CLIP_FILES:
            fetch(f"{CLIP_BASE}/{f}", CACHE / "clip" / Path(f).name)
    if a.whisper:
        name = f"ggml-{a.whisper}.bin"
        print("whisper →", CACHE / "whisper")
        fetch(f"{WHISPER_BASE}/{name}", CACHE / "whisper" / name)
    print("完成。跑 `vcut doctor` 确认。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
