# Steam Playtest 内测版本变动、技术栈基准与兼容性踩坑记录

> [!WARNING]
> **Playtest 内测阶段免责声明**  
> 当前处于 Steam Playtest 内测阶段，后续 Mod 接口可能存在变更。本文档基于本地 Steam 客户端解包与官方只读源码分支核验沉淀。  
> **实测验证基准**：现役 `Practice` 主线 `v0.0.65`（Git `origin/codex/v065-unified-20261125`，`468999d4`，`2026-11-25`）/ 向下兼容 `v0.0.57`–`v0.0.62`  
> **底盘引擎**：`Godot Engine v4.8.beta1.mono.official` (64-bit) + `.NET 10 CoreCLR` (`Practice.dll`)  
> **验证日期**：`2026-11-25`

---

## 1. 官方仓库双代码线与时间线辨析（`Practice` 现役主线 vs `FUS-F2` 旧原型线）

通过只读比对官方源码仓库 `<FUS_REPO_DIR>` 全部分支与 Steam 客户端，必须首先明确**同一仓库内并存两条世代与技术栈完全相反的代码线**，开发与查阅时严禁混淆：

| 维度 | 现役生产主线：`Practice`（Steam Playtest 真实主线） | 早期已替代原型线：`FUS-F2`（仅供前瞻设计参考） |
| :--- | :--- | :--- |
| **Git 分支与时间** | `origin/codex/v065-unified-20261125`（`468999d4`，**`2026-11-25`**，`v0.0.65`）；早期同线基准为 `origin/codex/playtest-v060-20261122`（`cc3d43a5`，`v0.0.60`）与 `origin/codex/fuvtt-project-sync`（`v0.0.56`） | 远端 `origin/HEAD` 默认分支：`codex/post-dnd-followups`（`ff4a1600`，**`2026-10-06`**，回落版本 `v0.1.80`）——**早于 `Practice` 线约 1.5 个月** |
| **引擎与原生栈** | **Godot `4.8.beta1.mono`** + **`.NET 10 CoreCLR`**（`Practice.csproj` → `Practice.dll`） | **Godot `4.8-dev4` 非 Mono** + 3 个 C++ GDExtension（`native/fus_file_commit`、`fus_history_geometry`、`fus_surfacebox`）+ 独立 `.NET 8 NativeAOT` 骰子子进程 |
| **外部插件契约** | 三协议并行：**`fus.session-plugin.v1`**（局外会话导入）、**`fus.desktop-module.v1`**（局内纯本机 `.zip`）与 **`fus.plugin.v2`**（局内 `.fup` + `content.pck`），统一由 C# `PluginPackageJob.cs` 强校验 | `f2.feature_plugin.v1`（`HostBridge.API_VERSION = 7`），旧版 `FeaturePluginCatalog` 事务管理（**无法在当前客户端加载**） |
| **插件存储布局** | `FUS_Data/session_plugins/`（`registry.json` + `packages/<id>/<sha256>/` + `cache/<id>/`） | `FUS_Data/plugins/`（`plugin_manifests.json` + `plugins/<id>/` + `_generation_store/`） |
| **本仓库定位** | **唯一生产目标线**：`fu_sdk`、`fu_runtime`、`mods/_template*`、`shared/tools/` 100% 锚定此线 | **严禁生成其生产脚手架**：仅将 `dnd_sdr` 等设计归档至文档前瞻参考节，不用于当前客户端 |

> [!CAUTION]
> **官方源码仓只读红线**：通过 `.env.local` 配置 `FUS_REPO_DIR` / `FUS_SOURCE_REF=origin/codex/v065-unified-20261125` 时，所有工具与开发者仅允许执行只读查询（如 `git -C <FUS_REPO_DIR> show <ref>:<path>` 或 `git archive`），**严禁对 `<FUS_REPO_DIR>` 执行文件写入或 `git checkout`**。

---

## 2. 当前基准 Playtest 客户端与 `v0.0.53` → `v0.0.65` 演进记录

### 2.1 基准环境参数

| 配置项 | 实测具体参数 | 来源与定位依据 |
| :--- | :--- | :--- |
| **Steam App ID** | `3177780` (Fu vtt Playtest) | Steam 注册信息 |
| **Steam 线上客户端版本** | `v0.0.65`（现役统一主线，2026-11-25；前序 PCK 基线 `v0.0.60` / `cc3d43a` 为 `2,799` 项） | 解包 `<FUVTT_INSTALL_DIR>/FUS.exe` 内 `data/build_identity.json` |
| **官方源码对照基线** | `v0.0.65`（Git `468999d4`，`2026-11-25`；前序 `v0.0.60` 基线为 `cc3d43a5`） | `origin/codex/v065-unified-20261125` |
| **底盘引擎与运行时** | `Godot Engine v4.8.beta1.mono.official` + `.NET 10` (`net10.0`) | `Practice.csproj`、`Practice.runtimeconfig.json` |
| **核心 C# 业务程序集** | `data_Practice_windows_x86_64/Practice.dll` | 客户端安装目录 |
| **本地运行数据目录** | `FUS_Data/`（含 `.fus-storage.json`、`session_plugins/`、`local_desktop/`） | `services/platform_runtime.gd`、`services/storage_bootstrap.gd` |

### 2.2 `v0.0.53` (`09d01f70`) → `v0.0.56` (`282aee64`) / `v0.0.57` (`3f20e8e`) 真实变动

1. **外部插件核心契约零破坏性变更**：`services/plugins/`（`PluginPackageJob.cs`、`PluginPackageJob.Probe.cs`、`DownloadCacheJob.cs`、`session_plugins.gd`）与 `plugin_packages/fobr_world_import/`（`v0.5.1`）在 `v0.0.53` → `v0.0.56` 间代码完全一致，下游 `fus.session-plugin.v1` 插件 100% 兼容。
2. **会话导入宿主体验与健壮性改进（`scenes/session/plugins/`）**：
   - `plugin_import.gd`：文件选择框接入统一 `WindowPopupOwner`（`PopupOwner.attach`），将 `acquire_import()` 租约申请延迟至用户真正选定文件进入 `begin_file()` 后，消除打开选择器期间长期锁死插件服务的缺陷。
   - `import_bridge.gd`：`decode_source()` 新增 `skipped_point_doors` 零长度门跳过告警，失败路径补充已创建资产与目标目录清理守卫。
   - `session_plugin_drop.gd`：原生文件拖拽命中坐标改走 `DesktopToolPointer.client_to_viewport()`，修复 HiDPI / 缩放视口下的偏移。
3. **内置桌面模块扩容**：`scenes/extension/desktop_feature_catalog.gd` 由 `v0.0.53` 的 9 核心 + 13 可选扩充为 `v0.0.56` 的 9 核心 + 14 可选（新增 `map_fog_editor`）。

### 2.3 `v0.0.57` → `v0.0.60` (`cc3d43a5`, `2026-11-22`) 真实变动（场景系统上线）

1. **统一常驻多场景空间分区模型（`scenes/systems/world/scene_repository.gd` & `modules/scene_box/`）**：
   - 底层 `fus.practice.world`（`v3`）、`catalog.floors`（`<= 512`）、`fus.floor_layers.v2`、`entity_state`（`v3`）与 `members` 保持单一常驻底层不变；若未提供 `world.modules.entries["scene_box"]`，`DesktopWorldState` 自动将全部楼层绑定至默认 `"主场景"`（旧单场景存档 100% 兼容）。
   - 多场景目录（`<= 64` 场景）与楼层归属分区持久化在 **`world.modules.entries["scene_box"]`**（`version = 1`, `schema_version = 2`），且在恢复与启用期触发重要耦合：宿主通过 `scene_repository.scene_for_floor(catalog.active_floor_uid)` 反推当前场景，因此 **`catalog.active_floor_uid` 必须归属 `host_active_scene_uid`**。即使 `ImportBridge.run()` 默认设置 `module_choices = []`，`DesktopWorldState` 仍载入该目录且 `FeatureManager.capture_persistent_state()` 会在存盘时无损保留。
   - 原候选组件 `scenes/candidates/scene_box/comp_scene_box.gd` 毕业为正式模块 **`res://modules/scene_box/comp_scene_box.gd`**（固定 1:1 正方形 `[72, 256]` 默认 `96x96`，`entity_type != "map"`，联同 `BoardToken.SCENE_BOX_CONFLICTS` 14 个互斥组件及 `image_flip` vs `obstacle/area` 互斥校验）。
2. **`world.modules` 限额扩容与精确估计（`world_module_state.gd`）**：
   - 单条目上限 **`6 MiB` → `16 MiB`**，模块分区总上限 **`8 MiB` → `24 MiB`**（`.world` 整包 `LocalWorldFiles.MAX_BYTES = 32 MiB` 不变）；`_bounded()` 针对 `NIL`/`BOOL`/`INT`/`FLOAT`/`VECTOR2`/`RECT2`..`PROJECTION` 下调保守开销（`8..80 B`）。
3. **内置可选模块扩充至 30 项（`9 核心 + 21 可选`）**：
   - `DesktopFeatureCatalog` 新增/转正 `campaign_time`、`checklist`、`resource_pool`、`character_roster`、`backpack`、`dnd_opportunity` 与 **`scene_box`**（`optional_entries()` 共 21 项）。
4. **其余增量**：
   - 内置 `fobr_world_import` 升至 `v0.5.2`（`import_bridge.gd` 新增 `skipped_point_strokes` 零长度线段告警）；
   - `WorldSnapshot.prepare_catalog` 接受可选 `floor_visits` 字典；`EntityStateCodec` 允许 `parked: true` 组件附带 `manual: bool` 标志；
   - `fu_sdk` 升级至 **`v1.3.0`** 提供完整 `Scene >> Floor >> Layer` 与 `Scene Box` 接口并修复跨楼层 `layer_uid_override` 的 `world.members` 归属。

### 2.4 `v0.0.58`–`v0.0.62` Steam Playtest 补丁增量与 SDK 适配

结合 Steam Playtest（`appid=4880170`）`v0.0.57`–`v0.0.62` 更新记录核对：

1. **`v0.0.58`–`v0.0.59` 新增玩法与角色模块**：落地 `dice`（`schema_version = 5`、`dice_workspace` `v4`）、`candidate_initiative`（`schema = 2`）、`backpack`（16 槽位背包）、`resource_pool`（`v1`）、`character_roster`（`v1`）、`checklist`（`schema = 2` + 13 事件规则解析）与 `dnd_opportunity`（`v1` 2014/2024 卡片）。
2. **`v0.0.60`–`v0.0.61` 地图、迷雾与绘制增强**：`scene_box` 毕业转正；`simple_fog` 扩展 `fog_config.gd` v2 与 `"SFH2"` 探索历史字节；`drawing` 文字工具（`text_ink.gd`，支持 `sans`/`zhuokai` 与 `12..256` px、`Transform2D` `affine`）上线。
3. **`v0.0.61`–`v0.0.62` Playtest 临时屏蔽与旧存档兼容**：`campaign_time` 与 `dnd_opportunity` 在面板临时禁用（`playtest_blocked`），但保留旧存档状态不阻断进桌；`ModuleRegistry` 同步支持 `"preserve"`/`"skip"` 策略。

### 2.5 `v0.0.65` (`468999d4`, `2026-11-25`) 统一局内扩展架构上线

1. **三协议插件并行（`PluginPackageJob.cs` + `session_plugins.gd`）**：
   - 在保留 `fus.session-plugin.v1` 100% 向后兼容的基础上，正式开放 **`fus.desktop-module.v1`**（`local_only: true`、`network_version: 0`、纯 `.zip` 直挂）与 **`fus.plugin.v2`**（`.fup` 含 `content.pck` (`GDPC`) + `SHA256SUMS.txt`、支持 `local_only: false` 联机组件与持久化）。
   - `PluginPackageJob.EnsureMountPack()` 为纯 `.zip` 局内包自动合成 `cache/<id>/<sha256>.zip`，`session_plugins._sync_world_modules()` 通过 `ProjectSettings.load_resource_pack(pck_path, false)` 挂载资源并经 `DesktopFeatureCatalog.set_external_entries()` 动态注册到开桌列表（参考样本：`crit_vfx_sample` 与 `aura_rings_sample`）。
2. **`DesktopApiService`、`HookIds` 扩容与自定义命名空间事件**：
   - 暴露 `"desktop_api"` 服务（26 个只读查询与轻交互方法，含非 GM 脱敏 `read_entity_vitals` 与 GM 专用 `read_saved_module_entry`）。
   - `HookIds.TABLE` 由 48 项扩充至 **61** 项，并开放 `^(ext|mod)\.[a-z0-9_]+(\.[a-z0-9_]+)+$` 自定义命名空间事件（arity `1` `Dictionary`）。
3. **局内组件披露、撤销栈、持久化与桌面槽位**：
   - `CompBase` 支持外部注册（`comp_<plugin_id>__<name>.gd`，15 字段 `ComponentCatalog`）、`public_state(state, peer)` 联机脱敏与支配压制；`EntityComponentPage` 接入 `EditModeController` 撤销重做；
   - `WorldModuleState` 开放三阶段持久化（`prepare_module_state` / `apply_module_state` / `serialize_module_state`，`StateValue.is_data()` 深度 `<= 32`）；开放 `world.overlays`、`ExtensionContext.mount_node`、`ui.desktop_panels`、`ui.module_settings`、`ui.mode_bar`（`on_enter` 必须返回 `true`）、`ui.entity_actions`、`ui.canvas_actions`、`ui.entity_properties` 与 `network.actions`/`network.projections`（仅 `fus.plugin.v2`）。
4. **内置模块与工作区同步**：`DesktopFeatureCatalog.optional_entries()` 由 21 项增至 **26** 项（新增 `entity_box`、`avg`、`dnd_character_sheet`、`monster_compendium`、`stat_bubbles`）；本仓库同步落地 `shared/sdk/fu_runtime/`（`v2.0.0`）与 `mods/_template-desktop-module/`、`mods/_template-world-plugin/`。

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

## 4. 现役 `Practice` 扩展体系双模开放架构（`v0.0.65`）

经 `origin/codex/v065-unified-20261125`（`468999d4`）核实，现役 `Practice` 线已由早期“局外导入单轨”演进为“**局外导入 + 局内运行时双轨并行**”：

1. **局外会话导入轨（`fus.session-plugin.v1`）**：
   - 保持 `host_api = 1`、`scope = "session"`、`RefCounted` `entry.gd` 于 `WorkerThreadPool` 瞬态执行，产出 `.world` 存档；依然禁止向 `DesktopScreen` 挂载任何 UI（控制台审计继续采用 `mods/sdk-log-console/` 范式）。
2. **局内纯本机表现轨（`fus.desktop-module.v1`）与局内联机世界轨（`fus.plugin.v2`）**：
   - 由 `PluginPackageJob.cs`（含 `EnsureMountPack()`）与 `session_plugins.gd`（`ProjectSettings.load_resource_pack(pck_path, false)`）统一挂载 `res://mods/<id>/` 或 `res://external_modules/<id>/`，并经 `DesktopFeatureCatalog.set_external_entries()` 进入桌面扩展管线；
   - `fus.desktop-module.v1` 强制 `local_only: true`、`network_version: 0`，禁止注册 `network.*` 槽位且被 `NetworkModuleContract` 自动跳过；`fus.plugin.v2` 支持 `.fup`（`content.pck` + `SHA256SUMS.txt`）、`CompBase`、`WorldModuleState` 与 `network.actions`/`projections`；
   - 两类局内模块均严禁包含 `.dll`/`.exe`/`.gdextension` 等二进制及全局 `class_name`（`ISteamUGC` 仍未启用，统一通过 HTTP/HTTPS URL 或本地 `sync` 安装）。

---

## 5. 双模共享 SDK、双源金丝雀巡检与真机无头验证流程

### 5.1 构建期自动内嵌双模 SDK（`fu_sdk` + `fu_runtime`）

- **局外 `shared/sdk/fu_sdk/`（`v1.3.0`）**：保持 **35** 个 `.gd` 脚本（含 `v1.gd`、`adapters/host_v1_adapter.gd`、`logging/log_bus.gd`、`plugins/module_registry.gd`、23 个独立分脚本、`4` 个 `modules/*.gd` 与 `4` 个 `utils/*.gd`）。
- **局内 `shared/sdk/fu_runtime/`（`v2.0.0`）**：包含 `6` 个运行时脚本（`v2.gd` + 5 大 helper）与 `runtime_manifest.json`，直接通过相对路径复用 `../fu_sdk/utils/*`、`logging/log_bus.gd` 与 `plugins/module_registry.gd`，打包时注入 `<ns_root>/lib/{fu_runtime,fu_sdk}/`。

### 5.2 Steam PCK + Git 源码双源金丝雀巡检

每次 Steam 推送客户端更新或外部源码库拉取新提交后，运行：

```powershell
# 同时比对 Steam 客户端 Embedded PCK / Practice.dll 与只读 Git 源码分支指纹
python shared/tools/fuvtt_cli.py inspect-client --extract --source both
```

- **Steam 轨**监控 `data/build_identity.json`、`data_Practice_windows_x86_64/Practice.dll`、`FUS_Data/.fus-storage.json` 及 PCK 内 **52** 项基线核心/模块 `.gdc`（`CONTRACT_WATCH_FILES`）+ **12** 项 `v0.0.65` 局内模块宿主 `.gdc`（`V065_CONTRACT_WATCH_FILES`）。
- **Git 只读轨**通过 `git -C <FUS_REPO_DIR> show <FUS_SOURCE_REF>:<path>` 提取 **73** 份核心与局内契约源码（`GIT_PRACTICE_WATCH_FILES`），输出 Steam 线上版 vs Git 源码版代差报告。

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
   - Steam PCK 中逻辑脚本以 Godot 4.8 `.gdc` 字节码分发，C# 核心编入 `Practice.dll`；而通过 `.env.local` 关联的 `<FUS_REPO_DIR>` (`origin/codex/v065-unified-20261125`) 可直接只读查阅等价明文 `.gd` / `.cs` 源码。
2. **UTF-8 BOM 行为边界**：
   - C# `PluginPackageJob.cs` 读取 `plugin.json` 与 `registry.json` 时会自动剥离 UTF-8 BOM；但本仓库所有受控源码、清单与文档一律保持 **UTF-8 无 BOM**，并在插件解析未知外部文本时主动剥离首字符 `0xFEFF`。
3. **大体积几何与两阶段预览**：
   - 复杂墙体与门窗必须遵循先提交几何 + `host.finish_geometry_preview()`、再归档图片资产的顺序，并持续响应 `host.cancelled()`；避免在导入中传递 `< 3` 点的退化障碍物环（会触发宿主 `obstacle_shape_preparation_failed`）。
4. **环境配置红线**：
   - 本地客户端、官方只读源码库与 Godot 控制台路径仅在未入库的 `.env.local` 中配置（`FUVTT_INSTALL_DIR`、`FUS_REPO_DIR`、`FUS_SOURCE_REF`、`GODOT_BIN`），受控代码、脚本与文档中统一使用 `<FUVTT_INSTALL_DIR>`、`<FUS_REPO_DIR>`、`<GODOT_BIN>` 占位符，零硬编码本机路径。
5. **文档同步要求**：
   - 每次通过 `inspect-client --extract --source both` 发现契约变动并更新 `shared/docs/` 时，须同步更新文档顶部版本号、Commit 哈希与验证日期。
6. **`ImportBridge`、`asset://`、多场景恢复与素材库实机踩坑速查（`2026-11-24` 汇总）**：
   - **`inspect_import` 与 `ProbeAssets`**：`ImportBridge.inspect()` 会用 `result.assets.size()` 覆盖 `unique_images` 并将 `assets` 全量传给 `ProbeAssets`；本地/ZIP 图片绝不能放入 `result.assets`（仅放 `http://`/`https://` URL），并应提供 `source_bytes`、`decoded_bytes`、`unique_images` 与 `name`（详见 `shared/docs/plugin-lifecycle.md`）。
   - **双输入源与默认行为**：客户端未开放 `FILE_MODE_OPEN_DIR`，需要同时支持归档与目录的插件应声明 `import_extensions: ["zip", "json"]`；注意 `ImportBridge.run()` 按选中文件名（如 `world.json` → `"world"`）命名战役，且硬编码 `metadata.module_choices = []`（但 `world.modules.entries["scene_box"]` 仍会在载入/保存时被 `DesktopWorldState` / `FeatureManager` 完整保留）。
   - **多场景恢复强耦合**：当写入 `entries["scene_box"]` 时，宿主按 `scene_for_floor(catalog.active_floor_uid)` 解析初始场景；必须保证 `catalog.active_floor_uid` 归属 `host_active_scene_uid`，且场景盒子实体 `entity_type != "map"`、`xform.scale == Vector2.ONE`、无 `SCENE_BOX_CONFLICTS` 冲突组件（使用 `fu_sdk v1.3.0` 可自动满足）。
   - **`asset://` 与 `ImageHeader` 预检**：`asset://` 仅接受 `png`/`jpg`/`jpeg`/`webp`/`bmp`（限边长 `<= 32768`、总像素 `<= 134217728`），拒绝 `.svg` 与 `.gif`；解码前须做魔数与头部预检（用 `.get_string_from_ascii()` 测 `<svg`），将 `.bmp`/`.svg` 转为 `.png`、拒收 `.gif`，避免 Godot C++ `ERROR:` 日志。
   - **大坐标 ULP、透明光源与素材库隔离**：2 点线段墙体须先相对中点局部化再挤出为 `>= 3` 顶点且 `|Area| >= 1e-12` 的闭合多边形，纯光源锚点须隐藏默认 `fallback_color` 方块（详见 `shared/docs/desktop-and-scene-api.md`）；`entity-library` 写入须过四重门控并链式传递 `.revision`，`world.modules` 须受 `16 MiB / 24 MiB / 30 MiB` 渐进裁剪（详见 `shared/docs/macro-and-rules.md`）。
