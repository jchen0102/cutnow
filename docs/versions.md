# 版本 / 渲染 / 审批 / 交付

P1 只承诺一件事：**审批的成片和交付的成片能对上号**。批量收益、跨机复现、通用依赖图都不在本轮范围。

## 四类对象

| 对象 | 记录什么 | 关键约束 |
|---|---|---|
| `version` | 内联 EDL + `edl_sha256`、输入素材指纹、`parent_id`、`change_note`、来源 | 不可变；改剪法必须产生新版本 |
| `render_run` | 对应 `version_id`、执行环境、状态、成片 `sha256`、QC、manifest 引用 | 同一版本可多次渲染（失败/重试/换环境） |
| `approval` | `by` / `created_at` / `decision` / `scope` / `target` / `note` | `scope=output` 绑 `run_id + output_sha256`；`scope=script` 只绑 `version_id + edl_sha256` |
| `delivery` | 实际交付的 `output_sha256`、`run_id`、`version_id`、`approval_id`、渠道 | 必须匹配一条 `scope=output` 的通过记录 |

### 为什么审批要分两种作用域

只绑 `version_id` 不够：同一个版本可能渲染多次（失败重试、换机器重渲、参数微调），
"这条剪法我认可"和"这个文件我认可"是两件事。审批成片必须落到具体产物：

```
approval(scope=output).target = {run_id, version_id, output_sha256}
```

`approve --script` 则只表达"剪法通过"，**不能**用于 `deliver`。

### 历史审批不作废

v1 通过后改成 v2：v1 的审批保持 `approved`，v2 是"尚未审批"，不存在"v1 审批失效"这种状态。
上游事件被纠正时，后续用 `needs_review` 标记（字段预留，第一版未启用通用依赖图）。

## 存储与完整性

```
.cutnow/
  versions/ver_*.json      # 不可变，O_EXCL 写入
  runs/run_*.json
  approvals/apr_*.json
  deliveries/dlv_*.json
  ledger.jsonl             # 每行 {id, kind, sha256, at}，追加 + flock
```

- 每条记录自带 `record_sha256`（去掉该字段后的规范化 JSON 摘要）；
- `audit` 会重算记录摘要、比对账本、核对引用链，并在文件仍存在时重算成片摘要；
- 记录只追加不修改；改写记录会让 `audit` 报 `broken`。

## 增量迁移

- **不动 `out/`**：现有 EDL、成片、manifest 保持原样；
- 新运行自动写 `version + render_run`（`--no-records` 可关）；
- 旧产物登记为历史导入，缺失项**不猜**：

  ```bash
  cutnow import out/edl_old.json --output out/old.mp4 --note "2026-10 归档"
  # 已导入版本 ver_...（未知：approval, environment, source）
  ```

  `origin.kind = "import"`，`origin.unknown` 明确列出缺失项（`environment` / `approval` / `source`），
  关联的历史成片以「执行环境未知」登记，仍可审批与交付，但审计会诚实说明环境不可考；
- 工作台后续再读这些记录，第一阶段不要求它适配。

## 第一轮验收（可用 CLI 复现）

```bash
cutnow run sports --source match.mp4          # 生成 v1 + run1
cutnow approve <run1> --by alice              # 审批成片
cutnow run sports --source match.mp4          # 生成 v2 + run2
cutnow deliver <run2> --by bob                # 应被拒绝
cutnow approve <run2> --by alice
cutnow deliver <run2> --by bob --channel douyin
cutnow audit <delivery_id>                    # 链路一致 = 10 项全 ok
```

已覆盖的测试：`tests/test_records.py`（v1 审批不能用于 v2、脚本审批不能交付、产物被篡改后
`audit` 报 broken、记录不可覆盖、历史导入标记 unknown、父版本链）。

## 本轮明确不做

- 批量变体的收益度量（业务验证，另行实验）；
- 跨机器逐字节复现（`verify` 只做留存完整性）；
- 通用依赖图 / 影响面分析（先记录显式引用，等真实需求）；
- 权限模型（目前 `--by` 是自由文本，没有身份校验）。
