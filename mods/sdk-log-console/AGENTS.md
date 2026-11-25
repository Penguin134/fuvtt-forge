# SDK Log Console (`sdk-log-console`)

## 1. 业务目标与适用范围

- **插件目录名**：`sdk-log-console`（`kebab-case`）
- **清单插件 ID**：`sdk_log_console`（`plugin.json` 中 `id`）
- **核心目标**：接入共享 SDK R3 `LogBus` 与 R2 `ModuleRegistry`（及 M1–M3 原生插件 SDK），提供合法宿主通道上的控制台日志订阅收集、模块可用性/未启用警告审计与可选世界内日志看板输出。
- **目标宿主契约**：现役 `Practice` 主线（Steam Playtest `v0.0.60` / `<FUS_REPO_DIR>` `codex/playtest-v060-20261122`），会话导入插件（`schema: "fus.session-plugin.v1"`、`scope: "session"`、`host_api: 1`）。

## 2. 目录结构与约束

- `plugin.json`：`fus.session-plugin.v1` 清单，`import_extensions: ["json", "log"]`，`settings` 严格仅含 `"string"` 与 `"bool"` 类型。
- `entry.gd`：继承 `RefCounted`，暴露 `inspect_import(path, options, host)` 与 `prepare_import(path, options, host)`，禁止 `class_name`、`preload(`、`Control.new(`、`Window.new(`、`PopupPanel.new(` 与 `"ui.desktop_panels"`。
- `examples/sample_diagnostic.json`：安全诊断示例输入（禁止在本插件目录放置 `.log` 文件，避免被仓库全局 `*.log` 规则忽略）。
- `README.md`：完整设计说明及 `<FUS_REPO_DIR>` 源码级宿主运行时 UI 限制实证（严禁写入本机绝对路径）。

## 3. 校验、构建与验证命令

```powershell
python shared/tools/fuvtt_cli.py validate sdk-log-console
python shared/tools/fuvtt_cli.py build sdk-log-console
python shared/tools/fuvtt_cli.py verify-host sdk-log-console
python -m unittest shared/tools/tests/test_console_log_mod.py -v
```
