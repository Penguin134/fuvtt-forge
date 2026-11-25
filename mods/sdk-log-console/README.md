# SDK Log Console (`mods/sdk-log-console/`)

> **Fu vtt `fus.session-plugin.v1` 控制台诊断与 R3 `LogBus` / R2 `ModuleRegistry` 日志消费插件**

---

## 1. 概述与设计定位

`sdk-log-console`（插件 ID：`sdk_log_console`）是基于 `shared/sdk/fu_sdk/v1.gd` 构建的独立会话级控制台日志诊断插件。它通过 `ImportSession.get_logger()`（R3 `LogBus`）与 `WorldBuilder.get_module_registry()`（R2 `ModuleRegistry` 及 M1–M3 原生插件 SDK）完成：

1. **实时订阅与缓冲区读取**：在 `prepare_import` 中通过 `logger.subscribe(...)` 实时收集结构化日志，并在退出前确保 `logger.unsubscribe(sub_token)` 防止 `RefCounted` 引用泄露，同时通过 `logger.get_entries(...)` 与 `logger.get_warnings(...)` 读取环形缓冲区结果。
2. **多格式诊断输入解析**：支持 `.json`（配置与 `entries` 数组、`"mode": "stress_warnings"`、`audit_modules`、`enabled_modules`、`disabled_policy`、`emit_debug`、`emit_in_world`）与纯文本 `.log`（逐行解析 `DEBUG`/`INFO`/`WARN`/`ERROR` 前缀），对空文件（0 字节）或损坏 JSON 均降级优雅处理且绝不触发 `push_error()`。
3. **原生模块审计与未启用警告**：审计目标原生模块（默认 `simple_fog,campaign_time,checklist,drawing`），由 `ModuleRegistry.check_and_warn(...)` 与对应插件 SDK 的 `get_availability()` 输出结构化警告（包含 `disabled` 与 Playtest `v0.0.61`–`v0.0.62` 禁用的 `playtest_blocked` 模块），并支持 `"preserve"` 与 `"skip"` 策略。
4. **验证可行的多通道输出**：通过官方宿主已验证的 4 个安全输出通道呈现控制台日志（不编造或尝试挂载未授权的桌面运行时 UI）。

---

## 2. 清单与配置项（`plugin.json`）

- `schema`: `"fus.session-plugin.v1"`、`host_api`: `1`、`scope`: `"session"`、`id`: `"sdk_log_console"`、`entry`: `"entry.gd"`
- `import_extensions`: `["json", "log"]`
- `import_action_label`: `"运行 SDK 日志控制台诊断"`
- `settings`（严格仅使用 `"bool"` 与 `"string"`，共 8 项）：

| `id` | `type` | `default` | 说明 |
|---|---|---|---|
| `enabled_modules` | `"string"` | `""` | 逗号分隔声明启用的可选模块 ID（如 `simple_fog,checklist,drawing`） |
| `audit_modules` | `"string"` | `"simple_fog,campaign_time,checklist,drawing"` | 逗号分隔需要执行可用性审计的模块 ID |
| `disabled_policy` | `"string"` | `"preserve"` | 未启用模块写入策略：`"preserve"` 或 `"skip"` |
| `min_level` | `"string"` | `"debug"` | `LogBus` 最低采集级别：`debug` / `info` / `warning` / `error` |
| `forward_reports` | `"bool"` | `true` | 是否将 `DEBUG`/`INFO` 日志同步转发至 `host.report` |
| `emit_debug` | `"bool"` | `true` | 是否输出调试级日志 |
| `emit_in_world` | `"bool"` | `true` | 是否在输出世界中写入 `checklist` 与 `drawing`（`text_ink`）日志看板 |
| `stress_warnings` | `"bool"` | `false` | 触发 120 条唯一警告以验证 `LogBus` 与宿主 `100 条 / 7000 字符`上限保护 |

---

## 3. 输入格式与输出通道

### 支持的输入文件

- **`.json` 诊断描述文件**（示例见 `examples/sample_diagnostic.json`）：可包含 `enabled_modules`、`audit_modules`、`disabled_policy`、`emit_debug`、`emit_in_world`、`mode: "stress_warnings"` 与 `entries` 数组。
- **`.log` 纯文本日志文件**：按行解析 `DEBUG` / `INFO` / `WARN` / `WARNING` / `ERROR` 前缀并回放至 `LogBus`；回放 `ERROR` 行时临时关闭 `emit_to_engine`（`logger.set_emit_to_engine(false)`）以防止触发 `push_error()` 导致无头宿主验收失败。
- **空文件 / 损坏 JSON**：在 `inspect_import` 与 `prepare_import` 中均安全降级并记录警告，不崩溃、不产生 Godot `ERROR:` 日志。

### 宿主已验证输出通道

1. **`host.report(...)`**：实时更新 `SessionScreen` 导入进度状态文本。
2. **`host.warn(...)` -> `metadata.notes` & `result.warnings`**：输出去重后的结构化警告，严格受限于宿主 `100` 条与 `7000` 字符上限保护。
3. **Godot 引擎控制台流（`print` / `push_warning`）**：由 `LogBus` 统一格式化 `[FuSdk/<LEVEL>][<source>] <message>` 输出，在开发/无头日志及客户端 `DiagnosticLogger`（`F2` 诊断导出）中可见。
4. **世界内日志看板（可选，`emit_in_world == true`）**：
   - 写入 `sdk_log_console` 模块摘要状态（`world.modules.entries["sdk_log_console"]`）。
   - 通过 `builder.checklist()` 写入日志任务条目（`source = ""`，单行标题 `<= 96` 字符）。
   - 通过 `builder.drawing()` 写入 `text_ink` 世界文本面板（`font = "sans"`，`font_size = 18`，有效 32 位十六进制 `floor_uid`）。
   - 当 `checklist` 或 `drawing` 未启用时，会自然触发 R2 警告（`"preserve"` 保留状态；`"skip"` 立即跳过不污染世界）。

---

## 4. `<FUS_REPO_DIR>` 源码级宿主限制实证（为什么无法在桌面上挂载运行时 UI 控制台）

经对官方只读基准仓库 `<FUS_REPO_DIR>`（分支 `codex/playtest-v060-20261122`，提交 `cc3d43a527b39522986004ecc0d891b20f17a2fc`，`project.godot` 版本 `config/version="0.0.60"`）逐文件只读核实，外部 `fus.session-plugin.v1` 插件**不支持**在桌面世界（`DesktopScreen`）中挂载任何运行时 `Control`、`Window`、`PopupPanel` 或 `ui.desktop_panels` 面板：

1. **Manifest 契约无 UI / 面板 / 自动加载字段**：
   - `<FUS_REPO_DIR>/services/plugins/PluginPackageJob.cs:98-116`（`ValidateManifest`）强制要求 `schema == "fus.session-plugin.v1"`、`host_api == 1`、`scope == "session"`，仅校验 `id`、`version`、`name`、`description`、`entry`（单 `.gd` 入口）、`settings`（`<= 32` 项且仅限 `"bool"` / `"string"`）与 `import_extensions`（`<= 8` 项），无任何桌面面板、场景或 autoload 扩展字段；第 `247` 与 `267` 行内联限制压缩包条目数为 `2..1000`。
2. **插件服务仅驻留于局外 `SessionScreen`，不进入 `DesktopScreen`**：
   - `<FUS_REPO_DIR>/services/plugins/session_plugins.gd:80` 明确注释：`## App 持有局外插件；开桌页只借用，不把安装服务带进世界或等待其网络检查。`
   - `<FUS_REPO_DIR>/scenes/app/app.gd:79,118,260,403-495` 仅将 `$SessionPlugins` 绑定到开桌页 `_session.bind_plugins($SessionPlugins)`，在 `_enter_desktop`（403–495 行）实例化桌面场景时完全不传入外部插件服务。
   - `<FUS_REPO_DIR>/scenes/session/session_screen.gd:42-46,72-76,475-477` 仅将插件用于 `SessionSettings`、`PluginActions` 与 `$PluginImport`。
3. **入口执行强制 `RefCounted` 且运行于 `WorkerThreadPool`**：
   - `<FUS_REPO_DIR>/scenes/session/plugins/plugin_import.gd:118-149`（`_start_inspection` / `_confirm_import`）明确检查 `if not instance is RefCounted or not instance.has_method("prepare_import"):`，若返回 `Node` 实例会直接 `instance.free()` 并拒绝；`inspect_import` 与 `prepare_import` 均通过 `WorkerThreadPool.add_task(...)` 在后台工作线程运行，无法操作场景树 UI。
   - `<FUS_REPO_DIR>/scenes/session/plugins/session_plugin_actions.gd:17,26` 与 `<FUS_REPO_DIR>/scenes/session/plugins/session_plugin_drop.gd:40-48` 规定：仅当 `import_extensions` 非空时才生成开桌页导入按钮与文件拖放入口，否则插件在 UI 中完全不可触发。
4. **`DesktopScreen` 桌面扩展与面板槽位仅限受信任内置模块**：
   - `<FUS_REPO_DIR>/scenes/desktop/desktop_screen.gd:102` 仅从内置 `FeatureCatalog.trusted_entries()` 启动 `$Extensions/FeatureManager`。
   - `<FUS_REPO_DIR>/scenes/extension/feature_manager.gd:245-246,314` 明确声明目录只能由已信任内置代码提供，存档 ID 与外部消息从不加载外部实现，未安装模块仅保留原记录而不执行实现。
   - `<FUS_REPO_DIR>/scenes/desktop/layout/desktop_panel_host.gd:94-106,159-166` 规定 `&"ui.desktop_panels"` 槽位必须同时满足：`spec.scene` 为可实例化为 `Control`（实现 `bind_provider` / `deactivate`）的 `PackedScene`、`provider is ExtensionBase`、`_runtime.is_ancestor_of(provider)` 且具备活跃 `ExtensionContext`——外部会话插件既非 `ExtensionBase` 也无场景挂载点。
5. **内置调试工具受发布构建门禁且不存在运行时 Mod 包加载器**：
   - `<FUS_REPO_DIR>/services/debug_tools.gd:120,138-143` 将 `F3` 调试工具严格门禁在 `OS.is_debug_build()`，正式 Steam Playtest 发布版不可用；`<FUS_REPO_DIR>/services/diagnostic_logger.gd` 仅将引擎日志采集入环形缓冲用于 `F2` 反馈导出。
   - `<FUS_REPO_DIR>/docs/research/session-plugins-20261025/README.md:29-35` 明确确认 `fus.session-plugin.v1` 为局外文件导入协议，不注册进 `FeatureManager` 或桌面组件库。
   - 对 `<FUS_REPO_DIR>` 执行 `git -C <FUS_REPO_DIR> grep` 检索 `load_resource_pack` 与 `ISteamUGC`，确认官方源码中不存在任何面向外部 Mod 的运行时 PCK/UGC 加载器。

因此，本插件采用宿主架构完全支持且可独立验收的替代方案：**`RefCounted` 会话插件订阅 R3 `LogBus` + R2 `ModuleRegistry` 审计 + `host.report` / `host.warn`（`metadata.notes`）/ 引擎日志流 / 可选世界内 `checklist` + `drawing` 看板**。
