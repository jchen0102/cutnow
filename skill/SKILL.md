---
name: cutnow
description: 用确定性剪辑引擎给视频做卡点混剪、赛事集锦、口播切片。当你需要把长素材剪成 10–20 秒成片、需要可复现的渲染结果、或需要检查一条片子能不能交付时使用。
---

# cutnow

确定性剪辑引擎。解法（solution）是 JSON 数据，算子是代码，EDL 是契约。

## 什么时候用它

- 用户有一堆素材，要剪成 10–20 秒的成片（集锦、切片、混剪）；
- 用户要求"同样的片子再出一版"或"改一刀看看"——只有 EDL 能做到；
- 用户要检查一条片子能不能发（时长/黑帧/响度/字幕/清晰度）。

**不要**用它做：调色、转场、多轨、换脸（引擎没有这些能力，不要假装有）。

## 安装

```bash
pip install cutnow
cutnow doctor          # 先跑这个，缺什么它会说
```

`doctor` 报告 `missing` 的先解决；`optional`（CLIP / whisper）缺了会自动降级，不必强求。

## 四个内置解法

| 解法 | 什么时候用 | 额外依赖 |
|---|---|---|
| `film-montage` | 一段长片 + 一首歌，要卡点混剪 | 无 |
| `sports-highlight` | 比赛/运动素材，要集锦 | CLIP（可选） |
| `talk-highlight` | 口播/访谈，要竖版切片带字幕 | whisper（可选） |
| `mj-remake` | 已有原片+歌，要卡点重剪 | 无 |

## 怎么跑

```bash
cutnow list                                   # 看有哪些解法和算子
cutnow run sports --source match.mp4 --out out.mp4
cutnow run talk   --source talk.mp4  --out out.mp4 --yes
```

- `--yes` 跳过人工闸门（只在你能承担后果时用）；
- 不给 `--out` 就用解法里的默认路径；
- 失败时**不要猜**：把 stderr 原文贴给用户，或先跑 `cutnow doctor`。

## 分镜直出（有稿子的情况）

如果用户给的是分镜/脚本而不是素材，用这个，不要先跑分析：

```bash
cutnow storyboard 分镜.json --source 素材.mp4 --out 成片.mp4
```

分镜格式（media-desk 的六格分镜可以直接用）：

```json
{"shots": [{"no": 1, "shot": "中景", "voice": "口播文字", "seconds": 3}]}
```

- `seconds` 必填；`voice` 会切成字幕；没给 `--music` 就铺静音轨；
- 素材可以有多个，按顺序轮转分配镜头。

## 读懂输出

每一步会打印 `op 名称 / 耗时 / 返回摘要`。最关键的是最后两行：

```
[9/9] qc    1.2s  {"pass": true, "failed": [], "duration": 10.4, "lufs": -12.6, ...}
成片 out/x.mp4  4.1MB  sha256=5e403e57...
```

- `pass: false` 时**不要交付**，把 `failed` 里的项告诉用户；
- `sha256` 是产物指纹：同一 EDL 在同一环境下应当得到同样的 sha；跨环境不保证。

每次运行还会写 `out/<solution>.manifest.json`（引擎/ffmpeg/字体/输入/EDL/成片六类身份）。
用户问"这份归档还能不能确认没被动过"时：

```bash
cutnow verify out/<solution>.manifest.json
# 0 归档完整 / 2 环境漂移（文件仍一致）/ 3 输入、EDL 或成片已变
```

`verify` 只证明**留存文件与当时一致、工具链是否漂移**，不证明"重新渲染一定逐字节相同"。
**不要**在 `broken` 时声称可复现；**不要**手工改 manifest 来"通过"校验。

## 加一个新解法

```bash
cutnow new my-recipe                  # 生成骨架
cutnow solution validate solutions/my-recipe.solution.json
```

规则：

- 只能引用已注册的算子（未知算子在校验期就被拒）；
- `gate: confirm` 表示这一步必须人点头——花钱、不可逆的动作都要加；
- `capability: cloud` 表示需要外部服务，未授权时会跳过而不是硬跑。

## 常见失败

| 现象 | 原因 | 处理 |
|---|---|---|
| `找不到输入 source` | 素材路径不对 | 用 `--source` 给绝对路径 |
| `未注册的 op` | 解法引用了不存在的算子 | 跑 `cutnow list` 看可用算子 |
| `素材不合格：sport_prob=…` | 准入判断这段不是比赛 | 换素材，或调低 `min_sport` |
| `没有语义合格的镜头` | 素材里没找到可用窗口 | 换素材或关掉 CLIP 走规则 |
