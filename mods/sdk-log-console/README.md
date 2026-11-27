# SDK Log Console (`mods/sdk-log-console/`)

> **Fu vtt `fus.desktop-module.v1`（`scope: "hybrid"`）双栖开发者控制台示例插件：局外 `.json`/`.log` 会话诊断 + 局内纯本机设置页与悬浮终端窗口**

---

## 1. 概述与双栖设计定位

`sdk-log-console`（插件 ID：`sdk_log_console`，局内模块 ID：`mod.sdk_log_console`）同时实现两条互补的激活轨道，互不冲突且各自可独立验收：

1. **局外会话导入轨（`entry.gd` + `fu_sdk/v1.gd`）**：
   - 继承 `RefCounted`，由开桌页 `PluginImport` 在后台工作线程运行 `inspect_import` 与 `prepare_import`。
   - 订阅 R3 `LogBus`（`ImportSession.get_logger()`）与 R2 `ModuleRegistry`（`WorldBuilder.get_module_registry()`），支持 `.json` 与 `.log` 诊断输入、原生模块审计（`simple_fog,campaign_time,checklist,drawing`）、`preserve` / `skip` 策略，并将摘要写入 `world.modules.entries["sdk_log_console"]`（`version: 1`）。
2. **局内纯本机桌面控制台轨（`mods/sdk_log_console/` + `fu_runtime/v2.gd`）**：
   - 在 `plugin.json` 中以 `"schema": "fus.desktop-module.v1"`、`"host_api": 2`、`"scope": "hybrid"` 声明 `"modules": [{"id": "mod.sdk_log_console", "local_only": true, "network_version": 0, ...}]`（纯 `.zip` 分发，不含 `pack_file`）。
   - 入口 `res://mods/sdk_log_console/module.tscn`（`module.gd` 继承 `ExtensionBase`）在世界内纯本机启动：零网络动作/投影注册、不阻塞房间联机握手；注册 `ui.module_settings` 设置页（`console_settings_page.tscn`）用于开关与配置悬浮终端控制台窗口（`console_floating_window.tscn`）。
   - 为避免与 `FeatureManager` 对 `world.modules.entries[module_id]` 的状态恢复冲突，局内模块使用独立 ID `mod.sdk_log_console`，在 GM 模式下通过 `DesktopApiHelper.read_saved_module_entry("sdk_log_console")` 只读回显局外导入的诊断历史。

---

## 2. 清单与双轨接口（`plugin.json`）

- `schema`: `"fus.desktop-module.v1"`、`host_api`: `2`、`scope`: `"hybrid"`、`id`: `"sdk_log_console"`、`entry`: `"entry.gd"`
- `import_extensions`: `["json", "log"]`、`import_action_label`: `"运行 SDK 日志控制台诊断"`
- `modules[0]`：`id: "mod.sdk_log_console"`、`entry_scene: "res://mods/sdk_log_console/module.tscn"`、`version: 1`、`network_version: 0`、`local_only: true`、`isolated_lifecycle: true`
- `settings`（局外导入配置，严格仅使用 `"bool"` 与 `"string"`，共 8 项）：

| `id` | `type` | `default` | 说明 |
|---|---|---|---|
| `enabled_modules` | `"string"` | `""` | 逗号分隔声明启用的可选模块 ID（如 `simple_fog,checklist,drawing`） |
| `audit_modules` | `"string"` | `"simple_fog,campaign_time,checklist,drawing"` | 逗号分隔需要执行可用性审计的模块 ID |
| `disabled_policy` | `"string"` | `"preserve"` | 未启用模块写入策略：`"preserve"` 或 `"skip"` |
| `min_level` | `"string"` | `"debug"` | `LogBus` 最低采集级别：`debug` / `info` / `warning` / `error` |
| `forward_reports` | `"bool"` | `true` | 是否将 `DEBUG`/`INFO` 日志同步转发至 `host.report` |
| `emit_debug` | `"bool"` | `true` | 是否输出调试级详细日志 |
| `emit_in_world` | `"bool"` | `true` | 是否在输出世界中写入 `checklist` 与 `drawing`（`text_ink`）日志看板 |
| `stress_warnings` | `"bool"` | `false` | 触发 120 条唯一警告以验证 `LogBus` 与宿主 `100 条 / 7000 字符`上限保护 |

---

## 3. 局外输入输出与局内终端能力

### 局外导入（`entry.gd`）

- **`.json` 诊断描述文件**（示例见 `examples/sample_diagnostic.json`）与 **`.log` 纯文本日志文件**（逐行解析 `DEBUG` / `INFO` / `WARN` / `WARNING` / `ERROR`），对空文件与损坏 JSON 安全降级且不触发 `push_error()`。
- 通过 `host.report(...)`、`host.warn(...)`（受 `100` 条 / `7000` 字符上限保护）、Godot 控制台流与可选世界内 `checklist` + `drawing` 看板输出，并将结构化摘要持久化至 `world.modules.entries["sdk_log_console"]`。

### 局内设置页与悬浮终端窗口（`mods/sdk_log_console/`）

- **设置页（`ui.module_settings` -> `console_settings_page.tscn`）**：提供开启/关闭悬浮终端控制台窗口、切换最低采集级别（`DEBUG`/`INFO`/`WARNING`/`ERROR`）、配置单条日志最大长度 `SpinBox`（默认 `2048` 字符，`0` 为不截断，支持非破坏性实时折叠/展开）、HookBus 捕获开关、引擎日志采集开关、GM 导入历史回显开关、清空缓冲与实时诊断摘要。
- **悬浮终端窗口（`console_floating_window.tscn`）**：
  - 因宿主 `FeatureManager._begin_optional_now()` 在可选模块 `_on_register()` 期间启用 `ctx._staged = true`（此时 `ctx.get_screen_host()` 依契约返回 `null`），模块通过 `ExtensionBase._defer_registered(&"_on_deferred_mount")` 推迟至暂存发布完成后自动挂载并默认显示（同时在 `set_console_visible(true)` 中保留按需挂载兜底）：优先经 `screen_host.mount_floating_panel(panel)` 挂载到桌面 `FloatingLayer/Panels`（自动阻断穿透点击并在 `LineEdit` 聚焦时让出快捷键），在无头测试环境回退 `SlotHelper.mount_node(screen_host, panel)`，并在 `_on_unregister()` 中同步移除并释放节点（`ObjectDB` 零泄漏）。
  - 采用 macOS Terminal 深色高对比纯白字体与扁平控件覆写（隔离宿主 `"wood"` 复合主题级联），支持标题栏拖拽、关闭按钮、级别下拉筛选、关键字实时过滤、`RichTextLabel` 彩色日志渲染与本地诊断命令：`help`、`status`、`clear`、`level <debug|info|warning|error>`、`maxlen <0|64..16384>`、`hooks`、`engine`、`imported`、`entities`。
  - **可选宿主数据源**：通过 `HookHelper` 订阅常用世界 `HookIds` 与自定义 `mod.sdk_log_console.diagnostic`；通过 `context.consume_service("debug_hooks")` 读取内置计数器快照；通过安全探测 `/root/DevTools._engine_logger.capture()` 增量采集引擎日志（`LogBus` 配置 `emit_to_engine: false` 以避免自身日志形成反馈环）。

---

## 4. `<FUS_REPO_DIR>` 源码级宿主契约实证（`v0.0.60` 限制与 `v0.0.65` 双栖演进）

经对官方只读基准仓库 `<FUS_REPO_DIR>`（现役 `Practice` 主线 `codex/v065-unified-20261125` / Steam Playtest `v0.0.65`，对照历史基准 `v0.0.60`）逐文件只读核实：

1. **为什么 `entry.gd` 轨道仍严格受限于 `RefCounted`（不得直接挂载桌面 UI）**：
   - `<FUS_REPO_DIR>/services/plugins/PluginPackageJob.cs`（`ValidateManifest` 与 `EnsureMountPack`）对旧版 `fus.session-plugin.v1` 仅允许单 `.gd` 入口、`settings`（`<= 32` 项且仅限 `"bool"` / `"string"`）与 `import_extensions`；在双栖 `fus.desktop-module.v1` 下，仅通过 `IsModNamespacePath` 过滤 `mods/<id>/` 与 `external_modules/<id>/` 子树并用 `ProjectSettings.load_resource_pack(...)` 挂载为桌面资源包，同时将包根 `entry.gd` 保留给开桌页导入器。
   - `<FUS_REPO_DIR>/services/plugins/session_plugins.gd` 与 `<FUS_REPO_DIR>/scenes/app/app.gd` 仍将 `$SessionPlugins` 绑定到开桌页 `_session.bind_plugins($SessionPlugins)`，由 `<FUS_REPO_DIR>/scenes/session/session_screen.gd`、`session_plugin_actions.gd` 与 `session_plugin_drop.gd` 提供文件导入入口与配置。
   - `<FUS_REPO_DIR>/scenes/session/plugins/plugin_import.gd` 强制检查导入入口为 `RefCounted` 并通过 `WorkerThreadPool.add_task(...)` 在后台线程执行 `inspect_import` / `prepare_import`，因此 `entry.gd` 本身绝不能操作场景树或挂载任何桌面节点。
2. **为什么 `fus.desktop-module.v1`（`scope: "hybrid"`）允许纯本机在世界内挂载设置页与悬浮终端**：
   - `<FUS_REPO_DIR>/scenes/desktop/desktop_screen.gd` 与 `<FUS_REPO_DIR>/scenes/extension/feature_manager.gd` 在 `v0.0.65` 已支持加载外部纯 ZIP 桌面模块（`local_only: true`、`network_version: 0`），且 `NetworkModuleContract` 与 `FeatureManager` 会将 `local_only` 模块排除出联机版本清单与房间握手检查。
   - `<FUS_REPO_DIR>/scenes/desktop/layout/desktop_panel_host.gd` 对应的 `ui.desktop_panels` 槽位仅承载侧栏标签页，而 `ui.module_settings`（`ModuleSettingsHost`）与 `WorldInputArea.mount_floating_panel(...)` 专门允许 `ExtensionBase` 提供方注册设置页（`Control` 根、实现 `bind_provider` / `refresh` / `deactivate`）并在桌面悬浮层安全挂载独立可拖动面板。
   - `<FUS_REPO_DIR>/services/debug_tools.gd` 仍将 `F3` 调试界面门禁在 `OS.is_debug_build()`，但无论调试或发布构建都会通过 `<FUS_REPO_DIR>/services/diagnostic_logger.gd` 挂载 `_engine_logger`；同时检索 `load_resource_pack` 与 `ISteamUGC` 可确认，外部包挂载统一经 `PluginPackageJob.cs` 与 `session_plugins.gd` 的 ZIP 挂载管线完成（仍不存在未经清单声明的任意 UGC 动态脚本加载器）。

因此，`sdk-log-console` 以**`entry.gd`（局外 `RefCounted` 导入器）+ `mod.sdk_log_console`（局内 `local_only` `ExtensionBase` 设置页与悬浮终端）**的双轨结构，成为官方契约完整支持、可通过 `fuvtt_cli.py validate / build / verify-host` 独立验收的标准混合插件范例。
