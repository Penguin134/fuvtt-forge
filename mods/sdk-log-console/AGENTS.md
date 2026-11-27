# SDK Log Console (`sdk-log-console`)

## 1. 业务目标与适用范围

- **插件目录名**：`sdk-log-console`（`kebab-case`）
- **清单插件 ID**：`sdk_log_console`（`plugin.json` 顶层 `id`，同时用于局外导入写入 `world.modules.entries["sdk_log_console"]`）
- **局内模块 ID**：`mod.sdk_log_console`（`local_only: true`、`network_version: 0`、`isolated_lifecycle: true`）
- **核心目标**：
  - **局外会话导入轨（`entry.gd`）**：接入 `shared/sdk/fu_sdk/v1.gd` R3 `LogBus` 与 R2 `ModuleRegistry`，支持 `.json` / `.log` 诊断导入、模块审计与宿主安全通道输出。
  - **局内纯本机控制台轨（`mods/sdk_log_console/`）**：接入 `shared/sdk/fu_runtime/v2.gd`，在世界内以纯本机模块激活，注册 `ui.module_settings` 设置页并挂载可开关、可拖动、支持筛选/搜索与本地诊断命令的悬浮终端控制台窗口。
- **目标宿主契约**：现役 `Practice` 主线（Steam Playtest `v0.0.65` / `<FUS_REPO_DIR>` `codex/v065-unified-20261125`），双栖混合桌面模块清单（`schema: "fus.desktop-module.v1"`、`scope: "hybrid"`、`host_api: 2`，纯 `.zip` 分发，禁止 `pack_file` / `pck`）。

## 2. 目录结构与代码约束

- `plugin.json`：`fus.desktop-module.v1` 双栖清单，`scope: "hybrid"`，`import_extensions: ["json", "log"]`，`settings` 严格仅含 `"string"` 与 `"bool"` 类型；`modules[0]` 为 `mod.sdk_log_console`（`entry_scene: "res://mods/sdk_log_console/module.tscn"`，`local_only: true`，`network_version: 0`）。
- `entry.gd`：继承 `RefCounted`，暴露 `inspect_import(path, options, host)` 与 `prepare_import(path, options, host)`。
- `mods/sdk_log_console/`：局内命名空间子目录（映射至 `res://mods/sdk_log_console/*`）：
  - `module.tscn` / `module.gd`：继承 `ExtensionBase`，动态加载 `lib/fu_runtime/v2.gd`（开发回退 `../../../../shared/sdk/fu_runtime/v2.gd`），通过 `LogBus`（`emit_to_engine: false`）、`HookHelper`、`SlotHelper`、`DesktopApiHelper`（GM 读取 `read_saved_module_entry("sdk_log_console")`）与可选 `/root/DevTools._engine_logger` 采集诊断日志；`_on_unregister()` 须同步清理并 `.free()` 悬浮窗口，保证 `ObjectDB` 零泄漏。
  - `console_settings_page.tscn` / `console_settings_page.gd`：继承 `VBoxContainer`，注册至 `ui.module_settings`，使用 `WeakRef` 持有 provider，兼容未入树调用 `bind_provider` / `deactivate`。
  - `console_floating_window.tscn` / `console_floating_window.gd`：继承 `PanelContainer`，模块激活后默认开启，并因可选模块 `_on_register` 处于 `ctx._staged == true`（`ctx.get_screen_host() == null`）而经 `_defer_registered(&"_on_deferred_mount")` + `_ensure_window_mounted()` 按需挂载：优先 `screen_host.mount_floating_panel(...)`（无此方法时回退 `SlotHelper.mount_node(screen_host, ...)`）。
- **卫生铁律**：所有 `.gd` 与 `.tscn` 必须为 UTF-8 无 BOM、LF 换行；禁止 `class_name`、`preload(`、`Control.new(`、`Window.new(`、`PopupPanel.new(`、`"ui.desktop_panels"` 与任何 `network.*` 联机注册；禁止在文档与代码写入本机绝对路径。
- `examples/sample_diagnostic.json`：安全诊断示例输入（禁止在本插件目录放置 `.log` 文件，避免被仓库全局 `*.log` 规则忽略）。

## 3. 校验、构建与验证命令

*(涉及 `<GODOT_BIN>` 的命令在启用终端沙箱时须使用 `BypassSandbox: true`；桌面 UI 与木质宿主主题对比度验收加传 `--ui-wid`。)*

```powershell
python shared/tools/fuvtt_cli.py validate sdk-log-console
python shared/tools/fuvtt_cli.py build sdk-log-console
python shared/tools/fuvtt_cli.py verify-host sdk-log-console --fus-repo auto
python shared/tools/fuvtt_cli.py verify-host sdk-log-console --fus-repo auto --ui-wid
python -m unittest shared/tools/tests/test_console_log_mod.py -v
```
