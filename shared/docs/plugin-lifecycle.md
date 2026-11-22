# Fu vtt 模块化插件入口、配置清单与加载生命周期规范

> [!WARNING]
> **Playtest 内测阶段免责声明**  
> 当前处于 Steam Playtest 内测阶段，后续 Mod 接口可能存在变更。本文档基于官方现役 `Practice` 主线源码（`origin/codex/fuvtt-project-sync`）与本地 Steam 客户端实测核验沉淀。  
> **实测验证基准**：现役 `Practice` 主线 `v0.0.56`（Git `282aee64`）/ Steam Playtest `v0.0.57`（Commit `3f20e8e`）  
> **底盘引擎**：`Godot Engine v4.8.beta1.mono.official` (64-bit) + `.NET 10 CoreCLR` (`Practice.dll`)  
> **验证日期**：`2026-11-22`

---

## 1. 客户端插件目录结构与挂载识别机制

现役 `Practice` 主线的外部第三方插件由 C# 核心作业 `services/plugins/PluginPackageJob.cs` 与 GDScript 服务 `services/plugins/session_plugins.gd` 驱动，采用“内容可寻址包目录 + 强校验注册表 + 后台工作线程按需实例化”架构：

### 1.1 存储根路径与核心目录布局

1. **存储根目录解析**（`services/platform_runtime.gd`、`services/storage_paths.gd`）：
   - Windows 导出客户端默认解析至 `<FUVTT_INSTALL_DIR>/FUS_Data/`（编辑器环境为工程同级 `FUS_Data/`），由 `StorageBootstrap` 从 `user://` 自动迁移；
   - macOS 使用 `user://`；
   - 自动化测试/探针带 `--suite-label=`、`--test-output=` 或 `--auto-probe=` 参数时，隔离在 `user://` 中运行，不触碰正式玩家数据。
2. **用户会话插件目录**（`<profile_root>/session_plugins/`）：
   - `registry.json`：全局会话插件注册清单（单文件上限 `2 MiB`，最多容纳 `128` 个插件），记录元数据、内容哈希、逐文件校验表、启用状态与已保存配置。
   - `operation.lock`：C# 独占文件锁（`FileShare.None`），串行化 `scan` / `verify` / `install` / `update` / `toggle` / `remove` / `settings` 全部磁盘操作。
   - `update-checks.cfg`：自动更新检查缓存（带宿主修订失效键 `UPDATE_CHECK_REVISION = "scene-structure-typed-layers-1"`）。
   - `packages/<plugin_id>/<zip_sha256>/`：内容可寻址的解压目录。
   - `cache/<plugin_id>/`：插件运行期远端图片下载缓存目录（由 `DownloadCacheJob.cs` 维护清理）。
   - `staging/<guid>/`：原子解包暂存目录，校验通过后一次性 `Directory.Move` 落位。
3. **嵌入式预装资源包**：
   - 客户端内置 PCK 路径：`res://plugin_packages/fobr-world-import.zip`。
   - 首次执行 `scan` 且请求带 `bundled_fobr: true`、注册表尚未标记 `playtest_fobr_offered: true` 时，由 `PluginPackageJob.cs` 自动解包安装 `fobr_world_import` 并将 `playtest_fobr_offered` 置为 `true`。
4. **注册表完整格式（`registry.json`）**：
   > [!CAUTION]
   > **`PluginPackageJob.ReadRegistry()` 强校验约束**：`registry.json` 中每个插件条目**必须**包含完整的 `file_hashes`（逐文件小写 SHA-256 映射）与 `settings`（键数、键名与类型须与 `manifest.settings` 严格一致），以及合法的 `directory == "packages/<id>/<sha256>"`、`sha256`（64 位小写 hex）和布尔值 `enabled`。缺少任一项都会在 `ReadRegistry()` 阶段直接抛出 `invalid_plugin_registry` 或 `invalid_plugin_settings`！
   ```json
   {
     "version": 1,
     "plugins": {
       "fobr_world_import": {
         "manifest": {
           "schema": "fus.session-plugin.v1",
           "host_api": 1,
           "scope": "session",
           "id": "fobr_world_import",
           "version": "0.5.1",
           "name": "FOBR 导入",
           "description": "将 FOBR 场景转换成独立桌面存档，保留源文件及墙体、门窗记录。",
           "entry": "entry.gd",
           "import_extensions": ["fobr"],
           "import_action_label": "导入 FOBR 文件",
           "settings": [
             {
               "id": "proxy",
               "type": "string",
               "label": "图片下载代理",
               "placeholder": "留空使用系统网络，或填写 http://127.0.0.1:7890",
               "default": ""
             }
           ]
         },
         "directory": "packages/fobr_world_import/<64位小写zip_sha256>",
         "sha256": "<64位小写zip_sha256>",
         "source_url": "",
         "enabled": true,
         "settings": {
           "proxy": ""
         },
         "file_hashes": {
           "plugin.json": "<64位小写sha256>",
           "entry.gd": "<64位小写sha256>"
         },
         "installed_at": "2026-11-20T00:00:00Z"
       }
     },
     "playtest_fobr_offered": true
   }
   ```

### 1.2 静态资源与入口相对路径解析

- `plugin.json` **必须**直接位于 ZIP 根目录（`zip.GetEntry("plugin.json")`）。
- 入口脚本 `entry` **允许使用安全子目录相对路径**（如 `"entry.gd"` 或 `"src/entry.gd"`，匹配 `^[a-zA-Z0-9_/-]+\.gd$` 且不含 `..`），并必须真实存在于 ZIP 中。
- 业务辅助脚本、防腐层 SDK（`lib/fu_sdk/`）和静态资源按相对插件目录路径引用；导入场景涉及的远端图片通过宿主桥接 `host.archive_image(url, proxy)` 统一归档为 `asset://<sha256>.<ext>`（支持 `<svg>` 自动栅格化为 PNG 并经 `SharedAssetStore.cs` 跨战役内容去重）。

---

## 2. 插件配置清单（Manifest）字段与 C# 强校验规范

插件必须在 ZIP 根目录下提供 `plugin.json`。本仓库与工具链统一要求 **UTF-8 无 BOM 编码**。

> [!NOTE]
> **UTF-8 BOM 解析真相**：经源码核实，`PluginPackageJob.cs` 在读取 `plugin.json` 与 `registry.json` 时使用 .NET `StreamReader` / `File.ReadAllText`（默认开启 BOM 检测），会自动剥离 UTF-8 BOM；但 Godot GDScript 侧文本处理及外部工具对 BOM 敏感，因此本仓库 `validator.py` 仍严格要求所有源码与清单保持 UTF-8 无 BOM。

### 2.1 清单 Schema 与完整字段定义（对照 `PluginPackageJob.ValidateManifest`）

| 字段名 | 类型 | 必需 | 源码级强校验约束 |
| :--- | :--- | :--- | :--- |
| `schema` | `string` | **硬必填** | 严格等于 `"fus.session-plugin.v1"`，否则抛 `plugin_host_api_incompatible` |
| `host_api` | `int` | **硬必填** | 严格等于 `1`，否则抛 `plugin_host_api_incompatible` |
| `scope` | `string` | **硬必填** | 严格等于 `"session"`，否则抛 `plugin_host_api_incompatible` |
| `id` | `string` | **硬必填** | 严格匹配 `^[a-z][a-z0-9_]{0,63}$`（**必须以小写字母开头，最长 64 字符**，禁止数字或下划线开头） |
| `version` | `string` | **硬必填** | 匹配 `^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9._-]+)?$` |
| `name` | `string` | **硬必填** | 长度 `1..80` 字符，界面显示的插件名称 |
| `description` | `string` | 可选 | 默认 `""`，长度上限 `2000` 字符 |
| `entry` | `string` | **硬必填** | 匹配 `^[a-zA-Z0-9_/-]+\.gd$` 且不含 `..`，允许子目录路径，且必须在 ZIP 内存在 |
| `import_extensions` | `string[]` | **硬必填** | 必须为 JSON 数组（可为空数组 `[]`），上限 **`8`** 项，每项匹配 `^[a-z0-9]{1,12}$`（不含前导点号）；缺失即抛 `invalid_plugin_extensions`。若数组为空，界面与拖拽处理器均不会为该插件生成导入入口 |
| `import_action_label` | `string` | 可选 | 导入按钮文案；缺省时 UI 回退为 `"导入 %s 文件" % ext.to_upper()` |
| `settings` | `Array<SettingItem>` | **硬必填** | 必须为 JSON 数组（可为空数组 `[]`），上限 **`32`** 项；缺失即抛 `invalid_plugin_settings` |

### 2.2 设置控件模式（`settings`）安装期硬校验与 UI 渲染

每个设置条目均为 JSON 对象：
```json
{
  "id": "proxy",
  "type": "string",
  "label": "图片下载代理",
  "placeholder": "留空使用系统网络，或填写 http://127.0.0.1:7890",
  "default": ""
}
```

- **安装期强校验（`PluginPackageJob.cs`）**：
  - `id` 必须匹配 `^[a-z][a-z0-9_]{0,63}$` 且同一插件内不重复；
  - `label` 长度 `1..80` 字符；
  - `type` **仅接受 `"bool"` 或 `"string"`**，声明任何其他类型（如 `"int"` / `"float"` / `"enum"`）在安装校验期即直接抛出 `invalid_plugin_settings` 拒装（不会进入 UI 渲染阶段）；
  - `default` 在 `type == "bool"` 时必须为原生布尔值，在 `type == "string"` 时必须为字符串且长度 `<= 2048` 字符；
  - 可选 `placeholder` 仅在 `scenes/session/plugins/plugin_panel.gd` 渲染 `LineEdit` 时消费。
- **控件渲染映射**：
  - `"bool"` → `CheckBox`（每行 2 列 `GridContainer` 排列）；
  - `"string"` → `Label` + 单行 `LineEdit`（保存时自动 `.strip_edges()`，数值参数需用 `"string"` 承载并在 GDScript 内解析校验）。

### 2.3 ZIP 归档安全与配额门禁（`PluginPackageJob.cs`）

1. **体积与数量上限**：
   - 压缩包下载与单文件上限：`64 MiB`（超限抛 `plugin_download_limit` / `plugin_expanded_limit`）；
   - ZIP 展开总大小上限：**`256 MiB`**（`plugin_expanded_limit`）；
   - ZIP 条目总数：**`2..1000`**（不足 2 项或超过 1000 项抛 `plugin_file_limit`）；
   - `plugin.json` 单文件上限：**`128 KiB`**（`plugin_manifest_limit`）；
   - 已安装插件数上限：`128`（`plugin_count_limit`），目录遍历统计上限：`20,000` 文件项。
2. **路径与符号链接防御**：
   - 严禁反斜杠 `\`、冒号 `:`、前导 `/`、`.` 或 `..` 路径段、尾随 `.` 或空格，以及大小写不敏感的重复路径（Windows 碰撞，抛 `unsafe_zip_path`）；
   - 严禁 ZIP 内包含 Unix 符号链接属性位 `((ExternalAttributes >> 16) & 0xF000) == 0xA000`（抛 `zip_link_rejected`）；
   - 磁盘读写时递归检查所有祖先路径，拒绝任何 NTFS 符号链接/联接点（`FileAttributes.ReparsePoint`，抛 `linked_plugin_path`）。

---

## 3. 按需延迟加载、防篡改校验与更新生命周期

Fu vtt 现役会话插件采用**元数据预扫描 + 导入期按需瞬态实例化**模型，不驻留于桌面房间场景树中：

```text
[客户端启动 / 进入会话管理页]
       │
       ▼
services/plugins/session_plugins.gd 调用 PluginPackageJob.Run("scan", ...)
       │  （校验 registry.json 与全包 file_hashes，不加载 entry.gd）
       ├── 首次且 bundled_fobr=true ──► 从 res://plugin_packages/fobr-world-import.zip 部署内置 FOBR
       └── enabled && available && import_extensions 非空 ──► 挂载导入按钮与原生文件拖拽
       │
[用户点击导入按钮选定文件 / 拖入支持后缀的文件]
       │  （v0.0.56 起：文件选择器由 PopupOwner 托管，选定文件后才申请导入租约）
       ▼
PluginPackageJob.Run("verify", {id, sha256}) 核验解压目录全部文件 SHA-256（防篡改）
       │
       ▼
scenes/session/plugins/plugin_import.gd 调用 load(_row.entry_path).new()
       │  （校验为 RefCounted 且含 prepare_import；投入 WorkerThreadPool 后台线程）
       ▼
调用 inspect_import(path, options, host)
       │  ├── 强读取 result.sha256 与 result.counts.unsupported
       │  └── 经 PluginPackageJob.ProbeAssets 探测未缓存远端图片字节数 → 弹窗确认
       ▼
调用 prepare_import(path, options, host)
       │  ├── host.begin_preview() / preview_entity() / finish_geometry_preview()
       │  ├── host.archive_image(url, proxy) ──► 归档至 SharedAssetStore (asset://)
       │  ├── 宿主校验 Snapshot.validate_data(world)
       │  ├── 宿主自动调用 ObstacleShapes.prepare_import(world, FobrWallKernel) 烘焙障碍物碰撞
       │  └── 归档源文件至 source-import/original.<ext> 并落盘 .world ──► 释放 RefCounted
```

### 3.1 核心生命周期接口钩子（`entry.gd`）

入口脚本必须继承自 `RefCounted`（每次导入独立实例化并运行在 `WorkerThreadPool` 后台线程，严禁依赖成员变量跨次导入保持状态），实现以下两个方法：

#### 1. `inspect_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary`
- **入参**：`path`（物理源文件路径）、`options`（当前插件配置字典深拷贝，注意可能存在 `null` 等非字符串/非布尔边界值，读取前须安全强转）、`host`（`ImportBridge` 实例）。
- **返回值强契约**（`scenes/session/plugins/import_bridge.gd` 与 `import_confirmation.gd`）：
  ```gdscript
  {
    "ok": true,
    "name": display_name,            # 推荐返回可读世界名称（实机 ImportBridge 会按选中文件名覆盖战役标题；verify-host 可读到真实名称）
    "sha256": FileAccess.get_sha256(path), # 必填！宿主直接无保护读取 result.sha256
    "source_bytes": int,             # 源文件物理字节数（import_confirmation.gd 确认面板读取）
    "decoded_bytes": int,            # 展开后的逻辑世界数据估计字节数（import_confirmation.gd 读取）
    "unique_images": int,            # 唯一图片引用数（注意实机 ImportBridge.inspect() 会被 assets.size() 覆盖）
    "counts": {
      "records": int, "images": int, "selected_images": int,
      "maps": int, "characters": int, "objects": int,
      "text": int, "drawings": int, "walls": int, "doors": int,
      "hidden": int, "unsupported": int # 必填！宿主直接无保护读取 result.counts.unsupported
    },
    "assets": { "https://...": max_pixel_count }
  }
  ```
- **`ImportBridge.inspect()` 实测关键机制（防坑）**：
  1. `ImportBridge.inspect()` 会将 `result.assets` 的**全部键**直接传给 `PluginPackageJob.ProbeAssets` 探测未缓存远端图片，并随后**用 `result.assets.size()` 覆盖 `unique_images`**！
  2. 因此**严禁将本地目录或 ZIP 内嵌图片路径放入 `result.assets`**，否则 `ProbeAssets` 会将本地图片误判为 `unknown_images`；本地图片仅应计入 `counts.images` / `counts.selected_images`，`result.assets` **只允许放入 `http://` / `https://` 远端 URL**。
  3. 若插件提供“跳过远端下载”开关（如 `download_remote_assets == false`），`inspect_import()` 应将 `result.assets` 置为空字典 `{}`，防止 `ProbeAssets` 在离线环境阻塞确认弹窗。
- 取消时检测 `host.cancelled()` 并返回 `{"ok": false, "reason": "cancelled"}`。
- 强烈建议通过防腐层 `shared/sdk/fu_sdk/v1.gd` 的 `session.ok_inspect(path, counts_override, remote_assets, decoded_bytes, display_name)` 构造返回值，自动计算 `sha256`、`source_bytes` 并补齐全部确认字段与计数键。

#### 2. `prepare_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary`
- **推荐两阶段顺序**：
  1. 调用 `host.empty_world()` 获取宿主标准世界结构（`fus.practice.world` v3 + `fus.floor_layers.v2`）。
  2. 先提交墙体/门窗/几何预览并调用 `host.finish_geometry_preview()`，再发布本地图片或通过 `host.archive_image(url, proxy)` 下载归档远端大体积图片，降低导入界面卡顿。
  3. 遇到非致命告警（如跳过退化几何、零长度门或缺失资源）调用 `host.warn(text)`（最多保留 100 条，最终写入会话备注）。
  4. 返回：
     ```gdscript
     {
       "ok": true,
       "world": world_dict,
       "counts": {
         "entities": int, "assets": int,
         "source_records": int, "merged_walls": int
       }
     }
     ```
- **`ImportBridge.run()` 实测默认行为**：
  - **战役名由选中文件名推导**：`ImportBridge.inspect()` / `run()` 会直接以选中文件名（去扩展名）作为战役标题（例如选择解压目录内的 `world.json` 时，宿主固定将活动名显示为 `"world"`）。插件应通过 `host.warn()` 告知用户，并将真实世界名称保留在 `world.modules` 与楼层名中。
  - **内置可选模块默认关闭**：`ImportBridge.run()` 硬编码设置 `metadata.module_choices = []`，因此 `grid_alignment`、`simple_fog` 等模块即使已写入配置或组件，导入后仍需 GM 在战役设置中手动开启（插件应通过 `host.warn()` 提醒）。

### 3.2 外部安装、版本比较规则与本地调试工作流

1. **原生 URL 安装与后台自动更新**（`PluginPackageJob.cs`、`session_plugins.gd`）：
   - 插件面板仅开放 `http://` 与 `https://` 直链输入框（拒绝带 `user:pass@` 凭证的 URL，60 秒超时，最多 5 次重定向）；客户端**未提供本地文件夹或本地 ZIP 文件选择对话框**。
   - `session_plugins.gd` 每 `60` 秒调度一次更新轮询：启动后强制检查一次，正常单插件检查周期 `24` 小时（`86400` 秒），失败后 `15` 分钟（`900` 秒）重试；检测到可用更新且插件空闲时自动下载并安装（核验 `expected_sha256`，若检查后远端变更则报 `plugin_update_changed`）。
   - **版本比较精确规则（防坑）**：
     - C# 内核截取 `version.Split('-', '+')[0]`（即仅解析 `major.minor.patch` 数字段）并用 `System.Version.Parse` 比较；
     - 安装/更新时：若新包数字段小于旧包，抛 **`plugin_version_older`** 拒绝；若完整版本字符串相同但 ZIP SHA-256 不同，抛 **`plugin_version_conflict`** 拒绝；
     - 自动更新检查（`CheckUpdates`）判定 `available = newNumeric > oldNumeric`——**仅修改 `-alpha.2` / `+build` 预发布或元数据后缀而未递增 `major.minor.patch` 数字段，不会触发自动更新！**（本仓库 `fuvtt_cli.py build --bump-dev` 因此直接递增 `patch` 数字段）。
2. **解压目录防篡改校验（严禁原地改文件）**：
   - 任何原地修改 `packages/<id>/<sha256>/` 内文件的行为都会在下一次 `scan` 或 `verify` 时被 `InstalledValid()` 检出并触发 `plugin_files_changed` 禁用。
3. **本仓库标准本地开发与验证三通道**：
   - **通道 A（`fuvtt_cli.py verify-host <mod>` 无头引擎冒烟）**：使用本地 `<GODOT_BIN>` 在隔离目录执行真实 GDScript 编译检查、`inspect_import`/`prepare_import` 回合冒烟与 `var_to_bytes` 往返校验。
   - **通道 B（`fuvtt_cli.py sync <mod>` 离线原子直写）**：自动计算完整 `file_hashes`、无损对齐 `settings`、补齐 `source_url` 与 `installed_at` 并执行版本冲突检查（开发期同版本重装可加 `--allow-same-version`），随后在客户端面板点击“刷新”即可生效。
   - **通道 C（`fuvtt_cli.py serve` + `build --bump-dev` 本地 HTTP 热更新）**：在 `127.0.0.1:8765` 托管 `.zip`，走 100% 原生下载与更新管线。

### 3.3 双输入源模式、本地/ZIP 资产发布与无头验证回退

1. **双输入源模式（`import_extensions: ["zip", "json"]`）**：
   - 现役 `Practice` 会话插件体系**未向外部插件开放 `FILE_MODE_OPEN_DIR` 目录选择器**，仅允许按 `import_extensions` 过滤的文件选择与拖放。
   - 若外部世界格式同时存在归档包（`.zip`）与已解压文件夹两种分发形态，推荐声明 `import_extensions: ["zip", "json"]`，引导用户选中解压目录内的清单文件（如 `world.json`）。
   - 因宿主 `plugin_import.gd` 仅校验扩展名，插件必须在打开阶段严格校验 `.json` 文件名及必需特征字段（拦截任意无关 `.json`）；读取 `.zip` 时需处理大小写敏感路径、URL 百分号编码（如 `%20`）、`__MACOSX/` / `.DS_Store` / `._*` 苹果元数据及深度 0/1 清单探测（可复用 `fu_sdk/modules/package_source.gd`）。
2. **本地/ZIP 资产发布（`SharedAssetStore.Publish` 与 `ImageHeader` 约束）**：
   - `host.archive_image(url, proxy)` 仅支持 `http://` / `https://` 远端 URL；本地目录或 `.zip` 内的图片字节流必须通过 `res://services/storage/SharedAssetStore.cs` 的 `Publish(global_dest, asset_ref, bytes)` 发布（返回 JSON 字符串，须解析确认 `ok == true`；实机 `host.destination` 经 `RootFor(dir)` 校验须位于 `sessions/桌面 ..._<32hex>` 下）。
   - **`ImageHeader` 上限与 `asset://` 扩展名白名单差异**：`ImageHeader` 硬限制 **`MAX_SIDE = 32768`**、**`MAX_PIXELS = 134217728`**（`1 <= w, h <= 32768` 且 `w * h <= 134217728`）；`CampaignImageFiles` 与 `SharedAssetStore.Publish` 对 `asset://` 引用接受 **`png`、`jpg`、`jpeg`、`webp`、`bmp`**，**明确拒绝 `.svg` 与 `.gif`**（不同于 `res://` 额外放行 `.svg`）。因此从本地或归档提取的 **`.bmp` 与 `.svg` 应先在插件内解码/栅格化并经 `save_png_to_buffer()` 统一转为 `.png`**，再行发布。
   - **前置魔数与流式头校验（杜绝 Godot `ERROR:` 日志）**：在调用 `Image.load_*_from_buffer()` 前，必须先做二进制魔数（PNG/JPG/WEBP/BMP/GIF）与图像头/流校验，探测 `<svg` 时必须使用 `.get_string_from_ascii()`（严禁对未知二进制字节调用 `.get_string_from_utf8()` 触发 `Unicode parsing error`），并直接拒收 `.gif`（`GIF8`）及损坏字节流，避免 Godot C++ 层向 stderr 打印 `ERROR:` 导致 `verify-host` 失败。
   - **自发布文件追踪与 `MockHostBridge` 回退**：`ImportBridge._created_assets` 仅追踪 `archive_image()` 创建的文件；插件直接调用 `SharedAssetStore.Publish()` 写入 `destination/assets/` 的新文件须自行记录并在用户取消或失败时清理。在 `verify-host` 的 `MockHostBridge` 无头测试环境下不存在 `SharedAssetStore.cs` 与 `host.destination`/`host.root`，插件应先嗅探 `ResourceLoader.exists("res://services/storage/SharedAssetStore.cs")` 与非空 `host.destination`，未命中时跳过写盘并返回合法 `asset://<sha256>.<ext>`（推荐直接复用 `fu_sdk/modules/asset_publisher.gd`）。

---

## 4. 数据持久化与执行安全边界

1. **全局配置层**：记录于 `FUS_Data/session_plugins/registry.json` 的 `enabled` 与 `settings`。
2. **会话存档层**：`prepare_import` 生成的世界数据存入 `<profile_root>/local_desktop/sessions/<session_uid>/*.world`（`fus.practice.world` v3），源文件保留于 `source-import/original.<ext>`，所有图片统一归档为 `asset://<sha256>.<ext>`（严禁在实体组件中写入本地 `user://` 绝对路径）。
3. **执行与算力分工**：GDScript 入口脚本运行于 Godot 4.8 客户端后台工作线程；FOBR 解码、墙体布尔切割与碰撞几何烘焙委托给 C# `FobrWallKernel` 完成。

---

## 5. 最小可运行插件示例与验证清单

### 5.1 最小目录结构
```text
my-sample-plugin/
├── plugin.json
└── entry.gd
```

### 5.2 最小合规清单（`plugin.json`，注意 `settings` 与 `import_extensions` 均为硬必填）
```json
{
  "schema": "fus.session-plugin.v1",
  "host_api": 1,
  "scope": "session",
  "id": "my_sample_plugin",
  "version": "1.0.0",
  "name": "示例插件",
  "description": "演示 Fu vtt 现役 Practice 会话导入接口的最小插件。",
  "entry": "entry.gd",
  "import_extensions": ["sample"],
  "import_action_label": "导入 Sample 文件",
  "settings": [
    {"id": "debug_mode", "type": "bool", "label": "启用详细日志", "default": false}
  ]
}
```

### 5.3 最小入口脚本（`entry.gd`）

> [!TIP]
> 生产开发推荐直接基于 `mods/_template/` 脚手架与 `shared/sdk/fu_sdk/v1.gd` 防腐层编写，无需手写底层字典。以下为不依赖 SDK 的最简裸契约实现：

```gdscript
extends RefCounted

func inspect_import(path: String, _options: Dictionary, host: RefCounted) -> Dictionary:
	if host.cancelled():
		return {"ok": false, "reason": "cancelled"}
	return {
		"ok": true,
		"sha256": FileAccess.get_sha256(path),
		"counts": {
			"records": 1, "images": 0, "selected_images": 0,
			"maps": 0, "characters": 0, "objects": 0,
			"text": 0, "drawings": 0, "walls": 0, "doors": 0,
			"hidden": 0, "unsupported": 0
		},
		"assets": {}
	}

func prepare_import(_path: String, _options: Dictionary, host: RefCounted) -> Dictionary:
	var world: Dictionary = host.empty_world()
	return {
		"ok": true,
		"world": world,
		"counts": {"entities": 0, "assets": 0, "source_records": 1, "merged_walls": 0}
	}
```

### 5.4 验证确认要点

1. 运行 `python shared/tools/fuvtt_cli.py validate <mod-name>` 与 `build <mod-name>`，确认通过全部 C# `PluginPackageJob` 等价静态门禁并生成含 `file_hashes` 的 `build-manifest.json`。
2. 运行 `python shared/tools/fuvtt_cli.py verify-host <mod-name>`，确认在 Godot 4.8-beta1 Mono 无头环境下全部 `.gd` 编译零错误、`inspect_import`/`prepare_import` 回合与 `var_to_bytes` 序列化往返通过。
3. 使用 `fuvtt_cli.py sync <mod-name>`（或 `serve` + `--bump-dev`）部署到本地客户端，在会话管理页确认导入入口、配置表单与导入落盘全流程无报错。
