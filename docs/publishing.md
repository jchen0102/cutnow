# 发布流程与踩坑记录

这份文档记录 **cutnow 从本地到 GitHub Release 再到 PyPI** 的完整流程，以及实际踩过的坑。
下次发版照着做，不用重新试错。

## 一、一次发版的完整顺序

```bash
# 1. 版本号（pyproject.toml）
#    version = "0.1.1"

# 2. 提交并推送
git add -A && git commit -m "chore: 版本号 0.1.1"
git push origin main

# 3. 打 tag（tag 必须和版本号一致，PyPI 不接受重复版本）
git tag -a v0.1.1 -m "cutnow v0.1.1"
git push origin v0.1.1

# 4. GitHub 网页建 Release（选已有 tag），挂演示视频到 Attach binaries
#    5. Release 发布后，publish.yml 自动构建并上传 PyPI
```

## 二、踩过的坑

### 1. `vcut` 这个名字在 PyPI 已被占用

发布前先查：

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://pypi.org/pypi/<名字>/json
# 404 = 可用，200 = 已被占
```

### 2. GitHub 不接受密码，只接受 token 或 SSH

- **HTTPS**：必须用 Personal Access Token 当密码；账号密码会报
  `Password authentication is not supported for Git operations.`
- **classic token 长度是 40 位**（`ghp_` + 36）。粘贴成 39 位就会 401，而且报错是
  `Invalid username or token`，看不出是长度问题——先 `echo ${#TOKEN}` 验长度。
- **推送包含 `.github/workflows/**` 时，token 必须额外勾 `workflow` 权限**，否则：

  ```
  refusing to allow a Personal Access Token to create or update workflow
  `.github/workflows/ci.yml` without `workflow` scope
  ```

- **SSH**：如果机器上没有私钥文件（只有公司密钥代理），`ssh-add -l` 会显示
  `The agent has no identities.`。此时生成一把新 key 并加到 GitHub 最省事：

  ```bash
  ssh-keygen -t ed25519 -C "<邮箱>" -f .ssh/id_cutnow -N ""
  cat .ssh/id_cutnow.pub        # 贴到 github.com/settings/keys
  GIT_SSH_COMMAND="ssh -i $PWD/.ssh/id_cutnow -o IdentitiesOnly=yes" \
    git push git@github.com:<owner>/<repo>.git main
  ```

  受沙箱限制时，`known_hosts` 也要指到工作区：
  `-o UserKnownHostsFile=$PWD/.ssh/known_hosts -o StrictHostKeyChecking=accept-new`

### 3. Release 里的视频：别只拖进正文

拖进**正文框**得到的 `https://github.com/user-attachments/assets/...` 链接，在 Release 里可能是
**404**（它只在被引用的帖子里有效）。

正确做法：拖到正文下方那行 **"Attach binaries by dropping them here or selecting them."**，
GitHub 会把它挂成 Release asset，生成永久链接：

```
https://github.com/<owner>/<repo>/releases/download/v0.1.1/demo.mp4
```

验证：`curl -sIL <链接> | head -3`，要看到 `302 → 200`。

### 4. 包里的数据文件

`cutnow run <解法>` 需要 `solutions/*.json`；`cutnow serve` 需要 `workbench/`。
如果它们不在包里，`pip install` 之后一条解法都跑不了（报"找不到解法"）。

现在的做法：

- `solutions/` 和 `workbench/` 都加 `__init__.py`，列入 `packages`；
- `pyproject.toml` 里用 `[tool.setuptools.package-data]` 带上 `*.json` 和 `static/*`；
- 运行时优先用仓库目录，找不到再退回包内目录。

发版前验证（关键，别省）：

```bash
python -m build
python3 -m venv /tmp/t && /tmp/t/bin/pip install dist/*.whl
cd /tmp && /tmp/t/bin/cutnow list      # 必须列出 4 个解法
```

### 5. PyPI 用 Trusted Publishing，不用 token

`.github/workflows/publish.yml` 走 OIDC，仓库里不存任何凭据。

PyPI 侧一次性配置：

1. 登录 https://pypi.org → **Account settings → Publishing**
2. Add a new pending publisher：
   - PyPI project name：`cutnow`
   - Owner：`jchen0102`
   - Repository：`cutnow`
   - Workflow name：`publish.yml`
   - Environment：`pypi`（要和 workflow 里的 `environment: pypi` 一致）
3. 之后每次发布 Release，流水线自动上传。

### 6. Actions 的两个小坑

- **第一次 push 才会触发**，本地 commit 不算；
- 改 `.github/workflows/**` 的提交必须带 `workflow` 权限才能推上去，否则整个 push 被拒（不是只跳过一个文件）。

## 三、发布后自检清单

```bash
# 仓库
curl -s https://api.github.com/repos/<owner>/<repo> | grep -E '"(description|topics|license)"'
# Release 与资产
curl -s https://api.github.com/repos/<owner>/<repo>/releases/latest | grep -E '"(tag_name|name)"'
# README 图片
curl -s -o /dev/null -w "%{http_code}\n" https://raw.githubusercontent.com/<owner>/<repo>/main/docs/images/demo.gif
# PyPI
curl -s https://pypi.org/pypi/cutnow/json | head -c 100
```
