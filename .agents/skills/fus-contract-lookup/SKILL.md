---
name: fus-contract-lookup
description: >-
  Read-only workflow and file index for verifying Fu vtt host contracts, native
  plugin schemas, component constraints, and Steam Playtest version deltas
  against <FUS_REPO_DIR> and fuvtt_cli.py inspect-client. Activate this skill
  before designing or debugging shared/sdk modules, native plugin SDKs, or
  mods/<mod-name> host integrations.
---

# Fu vtt 官方源码与宿主契约只读速查手册 (`fus-contract-lookup`)

在封装原生插件 SDK、排查宿主拒收存档或评估新插件能力可行性前，执行本流程直接从 `<FUS_REPO_DIR>`（配置于 `.env.local`，**严格只读**）与 `inspect-client` 提取真值，避免猜测式编码与多轮返工。

## 1. 安全红线

- **绝对只读**：仅允许执行 `git -C <FUS_REPO_DIR> status --short`、`log`、`show`、`grep` 或只读文件读取；**严禁**对 `<FUS_REPO_DIR>` 执行任何写操作、`git checkout`、`reset` 或创建临时文件。
- **路径脱敏**：写入本仓库任何代码、测试或 `.md` 文档时，一律使用 `<FUS_REPO_DIR>`、`<FUVTT_INSTALL_DIR>`、`<GODOT_BIN>` 占位符，严禁硬编码本机绝对路径。

## 2. 标准四步核查流

### Step 1：双源版本基线与增量巡检
1. 读取本地 `.env.local` 获取 `FUS_REPO_DIR` 与 `FUS_SOURCE_REF`。
2. 运行客户端契约巡检，快速识别本地 Steam 客户端 PCK（如 `v0.0.61+`）与 `<FUS_REPO_DIR>` Git 源码之间的差异及 Playtest 临时门控：
   ```powershell
   python shared/tools/fuvtt_cli.py inspect-client --source git
   ```
3. 如装有本地客户端，可追加执行 `python shared/tools/fuvtt_cli.py inspect-client` 对照 PCK 字节码监控清单。

### Step 2：按问题域直达 `<FUS_REPO_DIR>` 真值文件

| 待核实问题 | `<FUS_REPO_DIR>` 必查源码路径 | 重点核对项 |
| :--- | :--- | :--- |
| **插件包清单门禁与可配项** | `services/plugins/PluginPackageJob.cs`、`services/plugins/PluginPackageJob.Probe.cs` | `schema`（`fus.session-plugin.v1`）、`settings` 类型/数量上限、`import_extensions`、ZIP 条目限制 |
| **插件执行线程与运行时 UI 边界** | `scenes/session/plugins/plugin_import.gd`、`scenes/app/app.gd`、`scenes/session/session_screen.gd`、`scenes/desktop/layout/desktop_panel_host.gd` | `RefCounted` 强制要求、`WorkerThreadPool` 后台线程约束、`$SessionPlugins` 生命周期、`DesktopFeatureCatalog.trusted_entries()` 面板白名单 |
| **导入桥接回调、进度与警告上限** | `scenes/session/plugins/import_bridge.gd`、`scenes/session/plugins/import_confirmation.gd` | `host.warn` 条数上限（`100`）、`metadata.notes` 字符上限（`7000`）、`inspect_import` 12 项必填 `counts` 键 |
| **原生模块总表、启用态与依赖** | `scenes/extension/desktop_feature_catalog.gd`、`scenes/extension/feature_manager.gd` | 正式目录模块 ID、核心 vs 可选分类、`requires` 前置模块依赖（如 `portal -> areas`）、未入目录 `scenes/candidates/**` 模块 |
| **实体组件前缀、`parked`/`manual` 与互斥** | `scenes/entities/board_token.gd`、`scenes/entities/entity_state_codec.gd` | `components[0..1]`（`visual`/`permission`）前缀不变量、`parked`/`manual` 合法性（`manual` 依赖 `parked == true`）、`SCENE_BOX_CONFLICTS` 互斥表、`unit`-only 或 `map`/障碍物排斥规则 |
| **世界模块全局体积预算** | `scenes/systems/world/world_module_state.gd`、`scenes/systems/world/scene_repository.gd` | `16 MiB / 24 MiB / 30 MiB` 标量成本表、`MAX_SCENES = 64`、楼层归属划分 |
| **具体原生插件数据结构与校验器** | `modules/<module_id>/**` 或 `scenes/candidates/<module_id>/**` | 模块 `schema_version` 历史迁移、组件脚本精确 `res://` 路径、单模块容量上限与校验函数 |

### Step 3：单插件封装前 6 项必提清单（防返工检查单）
在编写 `shared/sdk/fu_sdk/plugins/<module_id>.gd` 前，必须从上述源码中摘出以下 6 项精确参数：
1. **目录归属与门控状态**：属于核心默认、世界/玩法可选、未入目录候选（`scenes/candidates/`），还是当前 Steam Playtest 临时屏蔽模块。
2. **精确 Schema 与历史版本迁移**：`version` / `schema_version` 号段及旧版默认值迁移逻辑（如 `v1 -> v2` 数值折算）。
3. **严格 `typeof` 契约**：逐字段确认宿主持久化校验要求 `TYPE_INT`、`TYPE_FLOAT`、`Color`（含 alpha 约束如 `a == 1.0`）还是特定二进制魔数头（如 `"SFH2"`），以便在 SDK 入口做 JSON 浮点归一、在落盘层严格保真。
4. **最大合法容量常量（`MAX_*`）**：确认最大条目数/字符数/顶点数，确保 SDK 有界深拷贝节点预算能完整容纳满载合法数据而不发生静默截断。
5. **实体宿主类型与组件冲突**：确认组件是否仅允许挂载于 `unit`、是否排斥 `map`/`obstacle`/矢量图形、是否与 `scene_box` / `image_flip` / `area` 双向互斥（含 `parked` 态）。
6. **扩展标签或枚举白名单**：如宏事件枚举、`^mod:[A-Za-z0-9_.:-]+$` 自定义标签正则、字体名枚举等。

### Step 4：闭环校验与源码零污染确认
1. 运行静态校验与真机无头验收（注意调用 `<GODOT_BIN>` 的命令须在终端工具中设置 `BypassSandbox: true`）：
   ```powershell
   python shared/tools/fuvtt_cli.py validate --all --include-template
   python shared/tools/fuvtt_cli.py verify-host _template
   ```
2. 确认官方源码仓保持零改动：
   ```powershell
   git -C <FUS_REPO_DIR> status --short
   ```
   输出必须为空。
