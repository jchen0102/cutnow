# vcut · 本地自动剪辑流水线

输入一份 `recipe`（原片 + 音乐 + 目标时长），输出 **EDL（可读的剪辑决策）+ mp4 成片**。
同一份 EDL 渲染两次，字节完全一致——这是"自动化"和"动画演示"的分界线。

## 快速开始

```bash
python3 vcut.py run recipes/mj_highlight.json --report
# → out/edl_mj-highlight.json / out/mj-highlight.mp4 / out/report.json
```

依赖：Python 3.9+、numpy、ffmpeg（自动使用 `imageio-ffmpeg` 静态包，无需 Homebrew）。
`tools/features` 为 Swift 编译产物（Vision 人脸/人体 + 亮度/饱和度/梯度），首次运行前编译：

```bash
swiftc -O -module-cache-path /tmp/mc -o tools/features tools/features.swift
```

## 流水线

```
probe ─▶ scene_split ─▶ features(Vision) ─▶ plan ─▶ EDL ─▶ ffmpeg ─▶ mp4
                                              │
                        beats(BPM/相位) ──────┤
                        loudest_window ──────┘
```

| 阶段 | 做什么 | 产出 |
|---|---|---|
| probe | 时长/分辨率/帧率/音轨 | 素材事实 |
| scene_split | ffmpeg scene 分数切镜头 | 镜头边界 |
| features | 每 0.5s 采样：亮度、帧间运动、饱和度、梯度、人脸数/面积、人体面积 | JSONL |
| beats | STFT 起音包络 → 自相关定 tempo → 梳状滤波定相位 | BPM + 拍点 |
| loudest_window | 音频能量最大窗口 = 副歌 | 音乐入点 |
| plan | 候选窗口打分 → 结构选段 → 拍数吸附 | EDL |
| render | 裁黑边/去硬字幕 → 模糊背景补 16:9 → 拍点拼接 → 字幕 → 混音 | mp4 |

## EDL 结构（节选）

```json
{
  "output": {"width": 1280, "height": 720, "fps": 30},
  "cleanup": {"crop": [632, 408, 108, 0]},
  "video": [{"asset": "src", "start": 16.4, "dur": 3.529, "at": 0.0, "role": "冷开场", "beats": 8}],
  "audio": [{"asset": "music", "in": 68.0, "dur": 17.647}],
  "subs":  [{"start": 3.5, "end": 7.0, "text": "老板说今晚不准提前下班"}],
  "ops":   [{"op": "beat_slot", "params": {"bpm": 136.0}, "evidence": "…"}]
}
```

`ops` 是决策日志：每个自动动作带参数和证据，便于回看"为什么切在这"。

## 两种选片模式

- **pinned（默认）**：`recipe.shots = [[源起点, 拍数], …]`，人工给镜头（等价于教程里手动拆镜头），其余全自动。
- **auto**：`recipe.regions = [[起, 止], …]` 或留空，按 `运动 0.36 / 饱和 0.28 / 主体 0.20 / 清晰度 0.16` 打分选窗口，含冷开场与收尾规则。

## 确定性

```
$ python3 -c "…render twice…"
sha_A 25726f7b539d749c9a46565bbcbe151438fb279e80eea932be9316cbd9ff4dba
sha_B 25726f7b539d749c9a46565bbcbe151438fb279e80eea932be9316cbd9ff4dba
identical: True
```

靠 `-fflags +bitexact -flags:v/a +bitexact -map_metadata -1` + 固定 `-threads`。

## 已知限制（重要）

1. **源素材只有 480p**：B 站匿名访问上限 480p，输出 720p 为上采样；登录后同一 EDL 可换 1080p 源。
2. **不做人物身份识别**：只有人脸/人体检测，没有"这是谁"。所以自动选片分不清主唱与观众，演示版用 `shots` 人工给镜头。
3. **字幕轴按小节均分**，不是语音对齐：原片是纯音乐现场，没有可 ASR 的语音。
4. **换人、改词翻唱不在本流水线内**：那两步需要 Updream（付费账号）与 YUE2（本地大模型），本仓库只覆盖确定性剪辑部分。
5. **版权**：原片与音乐来自 B 站公开视频，仅作内部演示，不可对外发布。

## 下一步

- 用 ASR（whisper.cpp）把"口播粗剪"接进来：句边界切点、口水/静音剔除、字幕对齐。
- 加身份一致性：人脸聚类或参考图匹配，替代人工给镜头。
- 竖版 9:16：主体跟踪 + 自动重构景，替代固定居中。
- Web 壳：时间线视图读取同一份 EDL，做"接受/拒绝单条 op"。

## 换人（replace op）

```
vcut replace export            # 产出 out/replace/shot_XX.mp4 + shots.json + README
  ↓ 云端/本地视频模型：参考角色图 + 单镜头 → 返回 16:9 片段
vcut replace fill --index 0 --file returned.mp4 --render
```

设计：**换人是 EDL 里的一个 op，不是流水线的一个分支**。
- 未回填的镜头走本地确定性路径（裁边、模糊背景、卡点、字幕）；
- 已回填的镜头直接规格化后接入同一条 concat，字幕与音轨不变；
- 所以"换 1 个镜头"和"换 5 个镜头"是同一条命令，最终成片始终可播放、可回归。

## 解法（solution）——S1

一条二创 = 一份声明，引擎不变。

```bash
python3 vcut.py solution list                                  # 列出解法与可用算子
python3 vcut.py solution validate solutions/mj-remake.solution.json
python3 vcut.py solution run solutions/mj-remake.solution.json --yes
```

`--yes` 跳过人工闸门（复现用）；不带则逐步确认。`--allow cloud` 才放行声明了云端能力的步骤。

### 结构

```json
{
  "id": "mj-remake", "name": "热点原片换人",
  "inputs": { "source": {"type":"video","default":"assets/src_jam.mp4"} },
  "steps": [
    {"id":"analyze","op":"analyze.standard","params":{}},
    {"id":"shots","op":"select.shots","gate":"confirm","params":{"shots":[[16.4,8]]}},
    {"id":"render","op":"render.edl","params":{"out":"out/x.mp4"}}
  ]
}
```

- **op 必须已注册**（`core/ops.py` + `core/builtin_ops.py`），未知 op 在校验期就被拒；
- **gate** 只有 `confirm` / `pick`，其余一律非法；
- **capability** 声明外部依赖（cloud/gpu/paid），未授权时跳过或报错，不会跑到一半失败。

### S1 验收（已完成）

声明式执行与旧流水线**渲染结果字节一致**：

```
旧：sha256=25726f7b539d749c9a46565bbcbe151438fb279e80eea932be9316cbd9ff4dba
新：sha256=25726f7b539d749c9a46565bbcbe151438fb279e80eea932be9316cbd9ff4dba
```
