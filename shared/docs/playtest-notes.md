# Steam Playtest 内测版本变动、技术栈基准与兼容性踩坑记录

> [!WARNING]
> **Playtest 内测阶段免责声明**  
> 当前处于 Steam Playtest 内测阶段，后续 Mod 接口可能存在变更。本文档基于本地 Steam 客户端解包与官方只读源码分支核验沉淀。  
> **实测验证基准**：现役 `Practice` 主线 `v0.0.56`（Git `282aee64`，`2026-11-19`）/ Steam Playtest `v0.0.57`（Commit `3f20e8e`，`2026-11-20`）  
> **底盘引擎**：`Godot Engine v4.8.beta1.mono.official` (64-bit) + `.NET 10 CoreCLR` (`Practice.dll`)  
> **验证日期**：`2026-11-20`

---

## 1. 官方仓库双代码线与时间线辨析（`Practice` 现役主线 vs `FUS-F2` 旧原型线）

通过只读比对官方源码仓库 `<FUS_REPO_DIR>` 全部分支与 Steam 客户端，必须首先明确**同一仓库内并存两条世代与技术栈完全相反的代码线**，开发与查阅时严禁混淆：

| 维度 | 现役生产主线：`Practice`（Steam Playtest 真实主线） | 早期已替代原型线：`FUS-F2`（仅供前瞻设计参考） |
| :--- | :--- | :--- |
| **Git 分支与时间** | `origin/codex/fuvtt-project-sync`（`282aee64`，**`2026-11-19`**，`v0.0.56`）及 `origin/codex/fuvtt-v056-map-editors`；本机 Steam 已更新至同线 **`v0.0.57`（`3f20e8e`，`2026-11-20`）** | 本地检出 `HEAD`：`codex/post-dnd-followups`（`ff4a1600`，**`2026-10-06`**，回落版本 `v0.1.80`）——**早于 `Practice` 线约 1.5 个月** |
| **引擎与原生栈** | **Godot `4.8.beta1.mono`** + **`.NET 10 CoreCLR`**（`Practice.csproj` → `Practice.dll`） | **Godot `4.8-dev4` 非 Mono** + 3 个 C++ GDExtension（`native/fus_file_commit`、`fus_history_geometry`、`fus_surfacebox`）+ 独立 `.NET 8 NativeAOT` 骰子子进程 |
| **外部插件契约** | **`fus.session-plugin.v1`**（`host_api = 1`，`scope = "session"`），离线 `RefCounted` 会话导入器，由 C# `services/plugins/PluginPackageJob.cs` 强校验 | `f2.feature_plugin.v1`（`HostBridge.API_VERSION = 7`），支持外部运行时桌面 `FeatureBase`（如 `plugin_packages/dnd_sdr`），全 GDScript `FeaturePluginCatalog` 事务管理 |
| **插件存储布局** | `FUS_Data/session_plugins/`（`registry.json` + `packages/<id>/<zip_sha256>/` + `cache/<id>/`） | `FUS_Data/plugins/`（`plugin_manifests.json` + `plugins/<id>/` + `_generation_store/`） |
| **本仓库定位** | **唯一生产目标线**：`fu_sdk`、`mods/_template/`、`shared/tools/` 100% 锚定此线 | **严禁生成其生产脚手架**：仅将 `dnd_sdr` 等精华设计归档至文档前瞻参考节，不用于当前 Steam 客户端 |

> [!CAUTION]
> **官方源码仓只读红线**：通过 `.env.local` 配置 `FUS_REPO_DIR` / `FUS_SOURCE_REF=origin/codex/fuvtt-project-sync` 时，所有工具与开发者仅允许执行只读查询（如 `git -C <FUS_REPO_DIR> show <ref>:<path>`），**严禁对 `<FUS_REPO_DIR>` 执行文件写入或 `git checkout`**。

---

## 2. 当前基准 Playtest 客户端与 `v0.0.53` → `v0.0.57` 演进记录

### 2.1 基准环境参数

| 配置项 | 实测具体参数 | 来源与定位依据 |
| :--- | :--- | :--- |
| **Steam App ID** | `3177780` (Fu vtt Playtest) | Steam 注册信息 |
| **Steam 线上客户端版本** | `v0.0.57`（Commit `3f20e8e`，`2026-11-20`） | 解包 `<FUVTT_INSTALL_DIR>/FUS.exe` 内 `data/build_identity.json` |
| **官方源码对照基线** | `v0.0.56`（Git `282aee64`，`2026-11-19`） | `origin/codex/fuvtt-project-sync` |
| **底盘引擎与运行时** | `Godot Engine v4.8.beta1.mono.official` + `.NET 10` (`net10.0`) | `Practice.csproj`、`Practice.runtimeconfig.json` |
| **核心 C# 业务程序集** | `data_Practice_windows_x86_64/Practice.dll` | 客户端安装目录 |
| **本地运行数据目录** | `FUS_Data/`（含 `.fus-storage.json`、`session_plugins/`、`local_desktop/`） | `services/platform_runtime.gd`、`services/storage_bootstrap.gd` |

### 2.2 `v0.0.53` (`09d01f70`) → `v0.0.56` (`282aee64`) / `v0.0.57` (`3f20e8e`) 真实变动

1. **外部插件核心契约零破坏性变更**：`services/plugins/`（`PluginPackageJob.cs`、`PluginPackageJob.Probe.cs`、`DownloadCacheJob.cs`、`session_plugins.gd`）与 `plugin_packages/fobr_world_import/`（`v0.5.1`）在 `v0.0.53` → `v0.0.56` 间代码完全一致，下游 `fus.session-plugin.v1` 插件 100% 兼容。
2. **会话导入宿主体验与健壮性改进（`scenes/session/plugins/`）**：
   - `plugin_import.gd`：文件选择框接入统一 `WindowPopupOwner`（`PopupOwner.attach`），将 `acquire_import()` 租约申请延迟至用户真正选定文件进入 `begin_file()` 后，消除打开选择器期间长期锁死插件服务的缺陷。
   - `import_bridge.gd`：`decode_source()` 新增 `skipped_point_doors` 零长度门跳过告警，失败路径补充已创建资产与目标目录清理守卫。
   - `session_plugin_drop.gd`：原生文件拖拽命中坐标改走 `DesktopToolPointer.client_to_viewport()`，修复 HiDPI / 缩放视口下的偏移。
3. **内置桌面模块扩容（9 核心 + 14 可选，共 23 项）**：
   - `scenes/extension/desktop_feature_catalog.gd` 由 `v0.0.53` 的 **9 核心 + 13 可选** 扩充为 `v0.0.56` 的 **9 核心 + 14 可选**：新增第 14 个内置可选模块 **`map_fog_editor`**（`res://modules/map_fog_editor/feature_map_fog_editor.tscn`，并在 `Practice.csproj` 编入 `modules/map_fog_editor/*.cs`）。
   - `room_chat` 网络协议版本由 `3` 升至 `4`；`drag_movement` 显示名调整为 `"角色拖拽（匀速）"`。

---

## 3. 引擎架构、.NET 10 与 Embedded PCK 解包机制

### 3.1 底盘引擎与原生依赖

1. **Godot 4.8 Beta1 Mono + .NET 10 CoreCLR**：
   - `Practice.csproj` 基于 `Godot.NET.Sdk/4.8.0-beta.1`、`net10.0` 编译，将 `platform/{windows,macos}/*.cs`、`services/plugins/*.cs`、`services/storage/*.cs`、`scenes/session_tools/fobr_wall/*.cs`、`tools/fobr_wall/vendor/Clipper2/*.cs`、`modules/simple_fog/native/*.cs`、`modules/drawing/*.cs`、`modules/map_fog_editor/*.cs` 统一打包为 `Practice.dll`。
2. **其他原生组件**：
   - **GodotSteam GDExtension**：`libgodotsteam.windows.template_debug.x86_64.dll` + `steam_api64.dll`。
   - **独立 3D 骰子程序**：`DesktopDice/DesktopDice.exe`（由宿主经桥接进程拉起）。

### 3.2 嵌入式 PCK（Embedded PCK）通用解包公式

Fu vtt 将游戏工程资源以 Godot 4 Embedded PCK 格式追加在 `FUS.exe` PE 文件尾部（未分发独立 `.pck`）。尾部最后 12 字节为小端序 `uint64` 的 `PCK_DATA_LEN` + 4 字节 ASCII 魔数 `GDPC`：

$$\text{PCK\_START} = \text{FILE\_SIZE} - 12 - \text{PCK\_DATA\_LEN}$$
$$\text{Physical File Offset} = \text{PCK\_START} + \text{FILE\_BASE} + \text{ENTRY\_OFFSET}$$

- 工程内直接使用 `shared/tools/fuvtt_devtools/client_inspector.py` 中的 `parse_embedded_pck_stream` 即可免外部工具流式读取或解包任意版本 `FUS.exe`（无需硬编码特定版本的偏移量；早期 `v0.0.53` 样本中 PCK 约 33.96 MiB / 2,144 条目，随版本更新动态变化）。

---

## 4. 现役 `Practice` 扩展体系“内外双轨隔离”现状

经 `origin/codex/fuvtt-project-sync` 源码与 `docs/extension-source.json` 核实，现役 `Practice` 线从早期 FUS 快照精简移植了 `ExtensionBase` / `ExtensionContext` / `SlotRegistry` / `HookBus` / `DesktopFeatureCatalog` 底座，但仍保持严格的**“内外双轨隔离”**：

1. **外部唯一开放动态加载轨（`session_plugins`）**：
   - 契约固定为 `fus.session-plugin.v1`（`host_api = 1`、`scope = "session"`），挂载于 `FUS_Data/session_plugins/`。
   - 仅在会话管理页触发导入时于 `WorkerThreadPool` 瞬态实例化 `RefCounted`，产出静态 `.world` 存档后即释放。
2. **内部桌面运行时模块底座（`DesktopFeatureCatalog`，静态封闭）**：
   - `scenes/extension/desktop_feature_catalog.gd` 硬编码 **9 核心 + 14 可选** 内置模块（`res://modules/...`），不扫描任何外部目录。
   - 全仓 `ProjectSettings.load_resource_pack` 调用次数为 **0**，不支持第三方 `.pck` 动态挂载。
3. **Steam 创意工坊（`ISteamUGC`）与联机模块白名单**：
   - `scenes/board/networking/steam_runtime.gd` 仅封装账号、好友、大厅与 `SteamMultiplayerPeer` P2P 传输，**`ISteamUGC` 相关调用为 0**。
   - 桌面联机虽已内置 `network.actions`、`network.projections`、`network.presentations` 三套结构化通道，但 `scenes/board/networking/network_module_contract.gd` 在握手与存档预检阶段强校验模块 ID 与 `network_version` 均须命中 `DesktopFeatureCatalog.optional_entries()` 及 `ResourceLoader.exists(path)`，第三方无法注册自定义运行时模块或网络协议。

---

## 5. 防腐层 SDK、双源金丝雀巡检与真机无头验证流程

### 5.1 构建期自动内嵌防腐层（`shared/sdk/fu_sdk/`）

- 由于无创意工坊前置依赖机制，所有业务插件统一面向 `shared/sdk/fu_sdk/v1.gd` 编程；`fuvtt_cli.py build` 在打包期自动将 `shared/sdk/fu_sdk/` 嵌入每个插件 ZIP 的 `lib/fu_sdk/`。
- 当宿主升级底层格式时，仅需单点修改 `shared/sdk/fu_sdk/adapters/host_v1_adapter.gd` 并运行 `build --all`。

### 5.2 Steam PCK + Git 源码双源金丝雀巡检

每次 Steam 推送客户端更新或外部源码库拉取新提交后，运行：

```powershell
# 同时比对 Steam 客户端 Embedded PCK / Practice.dll 与只读 Git 源码分支指纹
python shared/tools/fuvtt_cli.py inspect-client --extract --source both
```

- **Steam 轨**监控 `data/build_identity.json`、`data_Practice_windows_x86_64/Practice.dll`、`FUS_Data/.fus-storage.json` 及 PCK 内关键 `.gdc`（含 `session_plugins.gdc`、`plugin_import.gdc`、`import_bridge.gdc`、`session_plugin_drop.gdc`、`storage_paths.gdc`、`storage_bootstrap.gdc`、`obstacle_shape_data.gdc`、`world_defaults.gdc`）。
- **Git 只读轨**通过 `git -C <FUS_REPO_DIR> show <FUS_SOURCE_REF>:<path>` 提取 `Practice.csproj`、`PluginPackageJob.cs`、`session_plugins.gd`、`import_bridge.gd`、`desktop_feature_catalog.gd`、`fobr_world_import/plugin.json` 等源码指纹，直接输出 Steam 线上版 vs Git 源码版代差报告。

### 5.3 Godot 4.8-beta1 Mono 真机无头冒烟验证（`verify-host`）

配置 `.env.local` 中的 `GODOT_BIN=<GODOT_BIN>` 后，可执行真实引擎级无头闭环验证：

```powershell
python shared/tools/fuvtt_cli.py verify-host <mod-name>
```

- 子进程 `APPDATA` / `LOCALAPPDATA` / `TEMP` 与日志全部隔离在 `build/<mod-name>/verify_evidence/<run-id>/` 内，绝不污染系统用户目录或真实存档；
- 自动执行包内全部 `.gd` 脚本真实编译检查、`entry.gd` 的 `inspect_import()` + `prepare_import()` 完整回合冒烟、世界结构不变量校验以及 Godot 原生 `bytes_to_var(var_to_bytes(world))` 往返一致性检查。

---

## 6. 已知限制、兼容性踩坑与环境配置规范

1. **GDScript 字节码（`.gdc`）与 C# 程序集（`Practice.dll`）**：
   - Steam PCK 中逻辑脚本以 Godot 4.8 `.gdc` 字节码分发，C# 核心编入 `Practice.dll`；而通过 `.env.local` 关联的 `<FUS_REPO_DIR>` (`origin/codex/fuvtt-project-sync`) 可直接只读查阅等价明文 `.gd` / `.cs` 源码。
2. **UTF-8 BOM 行为边界**：
   - C# `PluginPackageJob.cs` 读取 `plugin.json` 与 `registry.json` 时会自动剥离 UTF-8 BOM；但本仓库所有受控源码、清单与文档一律保持 **UTF-8 无 BOM**，并在插件解析未知外部文本时主动剥离首字符 `0xFEFF`。
3. **大体积几何与两阶段预览**：
   - 复杂墙体与门窗必须遵循先提交几何 + `host.finish_geometry_preview()`、再归档图片资产的顺序，并持续响应 `host.cancelled()`；避免在导入中传递 `< 3` 点的退化障碍物环（会触发宿主 `obstacle_shape_preparation_failed`）。
4. **环境配置红线**：
   - 本地客户端、官方只读源码库与 Godot 控制台路径仅在未入库的 `.env.local` 中配置（`FUVTT_INSTALL_DIR`、`FUS_REPO_DIR`、`FUS_SOURCE_REF`、`GODOT_BIN`），受控代码、脚本与文档中统一使用 `<FUVTT_INSTALL_DIR>`、`<FUS_REPO_DIR>`、`<GODOT_BIN>` 占位符，零硬编码本机路径。
5. **文档同步要求**：
   - 每次通过 `inspect-client --extract --source both` 发现契约变动并更新 `shared/docs/` 时，须同步更新文档顶部版本号、Commit 哈希与验证日期。
