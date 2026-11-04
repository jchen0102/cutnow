# cutnow · Harness 插件（可选）

把 cutnow 的时间线做成 DeepSeek Harness 右侧抽屉：会话留在左边，工作台浮在右边，两者共用同一份 EDL。

## 装

```bash
# 在 Harness 的 plugin_manager 里 install_bundle，target 指向本目录
```

装完刷新页面，侧栏底部出现 `cutnow` 图标。

## 依赖

本地引擎要在跑：

```bash
cutnow serve --port 8799
```

面板和 `cutnow run` 读的是同一份 `out/current.json`，所以命令行改完，右侧 2.5 秒内自动跟上。

## 不装也行

这只是个可选前端。`cutnow` 的命令行完全不依赖它。
