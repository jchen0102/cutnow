"""路径与外部依赖解析：环境变量 > 缓存目录 > PATH。不写死任何绝对路径。"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CUTNOW_ROOT") or os.environ.get("VCUT_ROOT") or Path(__file__).resolve().parent.parent)

# 可选：仓库内的本地依赖目录（开发/离线环境用，等价于 pip install）
_vendor = ROOT / ".pylibs"
if _vendor.is_dir() and str(_vendor) not in sys.path:
    sys.path.insert(0, str(_vendor))
def _cache_root() -> Path:
    env = os.environ.get("CUTNOW_CACHE") or os.environ.get("VCUT_CACHE")
    if env:
        return Path(env).expanduser()
    local = ROOT / ".cache"          # 仓库内自带的缓存（开发/CI 用）
    if local.is_dir():
        return local
    return Path.home() / ".cache" / "cutnow"


CACHE = _cache_root()


def _env(name, legacy=None):
    v = os.environ.get(name) or (os.environ.get(legacy) if legacy else None)
    return Path(v).expanduser() if v else None


_FFMPEG = None
_FILTERS = {}


def _filters(exe: str):
    if exe not in _FILTERS:
        try:
            out = subprocess.run([exe, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
            _FILTERS[exe] = set(re.findall(r"^\s*\S+\s+(\w+)\s", out, re.M))
        except Exception:
            _FILTERS[exe] = set()
    return _FILTERS[exe]


def has_filter(name: str) -> bool:
    try:
        return name in _filters(ffmpeg())
    except Exception:
        return False


def _candidates():
    p = _env("CUTNOW_FFMPEG", "VCUT_FFMPEG")
    if p and p.is_file() and os.access(p, os.X_OK):
        yield str(p)
    w = shutil.which("ffmpeg")
    if w:
        yield w
    try:
        import imageio_ffmpeg  # 可选依赖
        yield imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass


def ffmpeg() -> str:
    global _FFMPEG
    if _FFMPEG:
        return _FFMPEG
    found = list(_candidates())
    if not found:
        raise RuntimeError(
            "找不到 ffmpeg。装一个（macOS: brew install ffmpeg / Linux: apt install ffmpeg），"
            "或用 CUTNOW_FFMPEG 指向可执行文件。")
    # imageio-ffmpeg 的 Linux 构建不带 libfreetype，烧不了字幕；优先带 drawtext 的
    for exe in found:
        if "drawtext" in _filters(exe):
            _FFMPEG = exe
            return exe
    _FFMPEG = found[0]
    return _FFMPEG


def clip_dir() -> Path:
    return _env("CUTNOW_CLIP_DIR", "VCUT_CLIP_DIR") or (CACHE / "clip")


def whisper_cli() -> str:
    p = _env("CUTNOW_WHISPER_CLI", "VCUT_WHISPER_CLI")
    if p and p.is_file():
        return str(p)
    local = CACHE / "whisper" / "whisper-cli"
    if local.is_file():
        return str(local)
    w = shutil.which("whisper-cli")
    if w:
        return w
    raise RuntimeError("找不到 whisper-cli：编译 whisper.cpp 或用 CUTNOW_WHISPER_CLI 指定")


def whisper_model() -> Path:
    p = _env("CUTNOW_WHISPER_MODEL", "VCUT_WHISPER_MODEL")
    if p and p.is_file():
        return p
    for name in ("ggml-small.bin", "ggml-medium.bin", "ggml-base.bin"):
        q = CACHE / "whisper" / name
        if q.is_file():
            return q
    raise RuntimeError("找不到 whisper 模型：把 ggml-*.bin 放到 %s 或用 CUTNOW_WHISPER_MODEL 指定"
                       % (CACHE / "whisper"))


def font() -> str:
    from .render import FONT_CANDIDATES
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return ""


def doctor() -> list:
    """返回 [(名称, 状态, 说明)]，供 cutnow doctor 使用。"""
    rows = []
    try:
        rows.append(("ffmpeg", "ok", ffmpeg()))
    except Exception as e:
        rows.append(("ffmpeg", "missing", str(e)))
    d = clip_dir()
    ok = (d / "vision_model.onnx").is_file() and (d / "text_model.onnx").is_file()
    rows.append(("CLIP 语义模型", "ok" if ok else "optional",
                 str(d) if ok else f"未安装（选段会降级为规则）：python3 scripts/fetch_models.py --clip"))
    try:
        rows.append(("whisper-cli", "ok", whisper_cli()))
    except Exception as e:
        rows.append(("whisper-cli", "optional", "未安装（口播解法需要）"))
    try:
        rows.append(("whisper 模型", "ok", str(whisper_model())))
    except Exception:
        rows.append(("whisper 模型", "optional", "未安装（口播解法需要）"))
    f = font()
    rows.append(("中文字体", "ok" if f else "missing", f or "没找到 PingFang/思源，字幕会缺字"))
    return rows
