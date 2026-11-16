<div align="center">

# cutnow

**A deterministic editing engine that agents can drive and humans can audit.**

[![ci](https://github.com/jchen0102/cutnow/actions/workflows/ci.yml/badge.svg)](https://github.com/jchen0102/cutnow/actions/workflows/ci.yml)
[![pypi](https://img.shields.io/pypi/v/cutnow.svg)](https://pypi.org/project/cutnow/)
[![python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://pypi.org/project/cutnow/)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[中文](README.zh-CN.md) · [Docs](docs/) · [Examples](solutions/) · [Agent skill](skill/SKILL.md) · [速查](dist/cutnow-lite.md)

</div>

> You have the footage. You have the track. And every week you rebuild the same fifteen-second cut
> by hand — then nobody can tell you why last week's version felt better.

![cutnow demo](docs/images/demo.gif)

```bash
pip install cutnow
cutnow doctor            # what's missing, and how to fix it
cutnow demo              # no footage needed: renders cutnow-demo.mp4 in ~5s
cutnow run sports --source match.mp4 --out highlight.mp4
```

That is a 10-second vertical-ready highlight cut on the beat, with title and end cards baked in —
no timeline app, no render queue, no manual keyframes.

---

## Why not "one-click AI video"?

Most tools give you a **finished file**. You cannot change one cut without starting over, and you
cannot ask *why* that cut is there.

cutnow gives you an **edit decision list (EDL)** — a plain JSON timeline you can read, diff and
rewrite — plus the engine that turns it into a video, byte-for-byte reproducibly.

| Typical tool | cutnow |
|---|---|
| "AI edited your video" | every cut has a score and a reason |
| change = re-generate everything | change one line, re-render in seconds |
| one workflow per product | a new recipe is a JSON file, engine untouched |
| output only | output + EDL + QC report |

## Concepts

```
Solution (solution.json)   what a recipe does: which ops, in what order, where a human must confirm
      ↓
Op     (core/builtin_ops)  one deterministic job: cut, beat-align, score, subtitle, render, QC
      ↓
EDL    (out/edl_*.json)    the decision list: source in-point, duration, position, audio, subtitles
```

Three ideas, and that's the whole system: **solutions are data, ops are code, the EDL is the contract.**

## Retention integrity, checkable

Every run writes `out/<solution>.manifest.json`: a snapshot of what produced the file — engine /
Python / ffmpeg / font identity, input hashes, EDL digest and the output `sha256`.

```bash
cutnow verify out/sports-highlight.manifest.json
# 0 = 归档完整   2 = 环境漂移（文件仍一致）   3 = 输入 / EDL / 成片已变
```

**Scope, stated plainly:** `verify` answers *"is this archive still the run it claims to be, and
has the toolchain drifted?"* It does **not** re-render, so it cannot prove that a fresh render would
be byte-identical — that is a stronger and separate claim, tested separately.

Paths are stored relative to the project root, so a run folder can be moved or archived and still
be audited later.

## Version → approval → delivery

`cutnow run` also records a `version` (immutable EDL) and a `render_run` (environment, output sha,
QC). Approval is explicit and **scoped**: approving an *output* binds to that exact render artifact,
so an approval for v1 can never be reused for v2 — even when both renders are byte-identical.

```bash
cutnow approve <run_id> --by alice      # 审成片；--script 只审剪法
cutnow deliver <run_id> --by bob        # 没有匹配的成片审批就拒绝
cutnow audit <delivery_id>              # 版本 → 渲染 → 审批 → 交付 逐项核对
```

Schema, immutability rules and the incremental migration path: [docs/versions.md](docs/versions.md).

## Built-in solutions

| Solution | Input | Output | Needs |
|---|---|---|---|
| `film-montage` | one long video + music | ~20s beat-cut montage with title/end cards | — |
| `sports-highlight` | match footage | ~12s highlight, cuts land on shot boundaries | CLIP *(optional, degrades gracefully)* |
| `talk-highlight` | talking-head video | ~15s vertical clip with aligned subtitles | whisper.cpp *(optional)* |
| `mj-remake` | source video + track | beat-cut re-edit | — |

```bash
cutnow list                 # solutions + ops
cutnow run film --source movie.mov --out montage.mp4
cutnow run talk --source talk.mp4 --out clip.mp4
```

## How it decides (and shows you)

A real run, 9 stock clips, fully unattended, **0 tokens**:

```
9 sources → 4 rejected by the pre-check → 5 rendered → 5/5 pass QC → 86s total
```

The pre-check is not a vibe: it samples frames and asks a CLIP model whether this looks like a
match at all.

```
sport_prob 0.994 → keep      (beach volleyball)
sport_prob 0.093 → reject    (people walking down a street)
```

Then selection scores every candidate window on **semantic match + motion + audio energy**, keeps
cuts on shot boundaries, and renders. Finally QC blocks anything that would ship broken:

```
duration 10.40s ✓   black frames 0 ✓   −12.6 LUFS ✓   subtitle fit 12/16 ✓   sharpness 314 ✓
```

![timeline](docs/images/timeline.png)

*The optional local workbench (`cutnow serve`): shots, beat grid, versions, and the same EDL the CLI writes.*

## Write your own solution

```bash
cutnow new my-recipe                      # scaffolds solutions/my-recipe.solution.json
cutnow solution validate solutions/my-recipe.solution.json
cutnow run my-recipe --source in.mp4 --out out.mp4
```

```json
{
  "id": "my-recipe",
  "inputs": { "source": { "type": "video", "required": true } },
  "steps": [
    { "op": "analyze.standard", "params": { "features": "auto" } },
    { "op": "select.action", "gate": "confirm", "params": { "target_seconds": 12 } },
    { "op": "card.bookends", "params": { "title": "MY FILM", "end": "cutnow" } },
    { "op": "render.edl", "params": { "out": "out/my-recipe.mp4" } },
    { "op": "qc.report", "params": {} }
  ]
}
```

Unknown ops and invalid gates are rejected at **validation** time — a solution cannot execute code
you did not review. `"gate": "confirm"` stops for a human before a costly or irreversible step.

## Ops

| Group | Ops |
|---|---|
| Analyze | `analyze.standard` `analyze.media` |
| Select | `select.shots` `select.auto` `select.action` `select.semantic` |
| Speech | `transcribe.whisper` `cut.by_sentence` |
| Audio | `audio.chorus` `audio.from_clips` `audio.normalize` |
| Text & framing | `subtitle.by_beat` `card.bookends` `frame.vertical` `cleanup.crop` |
| Output | `render.edl` `qc.report` `qc.source` |

## Install

```bash
pip install cutnow          # or: pipx install cutnow
cutnow doctor               # ffmpeg / models / fonts, with what to do about each
```

ffmpeg ships with the package via `imageio-ffmpeg`, so a fresh install already renders.
Optional extras:

```bash
pip install "cutnow[clip]"     # semantic selection (~600MB of ONNX models)
pip install "cutnow[qc]"       # sharpness metric via OpenCV
python scripts/fetch_models.py --clip --whisper small
```

Everything optional degrades: without CLIP, selection falls back to motion + audio rules; without
whisper, the talk solution reports what is missing instead of producing a broken file.

## CLI

```
cutnow list                       # solutions and ops
cutnow run <solution>             # --source, --music, --out, --yes, --json
cutnow new <name>                 # scaffold a solution
cutnow solution validate <path>
cutnow serve [--port 8799]
cutnow storyboard story.json --source clips/*.mp4 --out cut.mp4   # storyboard → film, no analysis        # local timeline workbench
cutnow doctor
```

## Repository layout

```
cutnow.py        CLI
core/            engine: ops, solutions, EDL, render, QC, config
solutions/       built-in recipes (data only)
recipes/         legacy single-pass recipe format
workbench/       optional local HTTP timeline (stdlib only)
contrib/         optional integrations (Harness plugin, …)
docs/            images and notes
```

## Limitations

Honest list, so nobody is surprised:

- **No transitions, grading, or multi-track.** Cuts are hard cuts; that is the current engine.
- **Face swap and face-identity modules are not included** (compliance). Interfaces exist; the
  implementations are intentionally absent.
- **Deterministic, not tasteful.** QC guarantees the file is shippable, not that the edit is good.
- **No cloud APIs.** No keys, no per-call cost, no rate limits — and no generative model either.

## Roadmap

- [x] EDL + deterministic render + QC gate
- [x] Solution manifests with validation and human gates
- [x] Semantic source pre-check and shot selection (CLIP)
- [ ] Proposal layer: `plan → diff → apply` instead of direct edits
- [ ] Cross-fades and simple grading
- [ ] Batch runner with a single report (in `contrib/` today)

## Credits

Demo footage: *Tears of Steel* © Blender Foundation, [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/).
Built on ffmpeg, [CLIP](https://github.com/openai/CLIP) (via ONNX), and
[whisper.cpp](https://github.com/ggerganov/whisper.cpp).

## License

MIT — see [LICENSE](LICENSE).
