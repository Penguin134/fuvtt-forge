# 本地存储架构、FOBR 导入、内置模块与规则数据适配规范

> [!WARNING]
> **Playtest 内测阶段免责声明**  
> 当前处于 Playtest 内测阶段，后续插件与模块接口可能存在变更。本文档基于官方源码库（只读核验）与本地 Steam 客户端实际解包验证沉淀。  
> **现役实测验证基准**：`Practice` 主线 `v0.0.56`（Git `origin/codex/fuvtt-project-sync`，Commit `282aee64`，`2026-11-19`）/ Steam Playtest `v0.0.57`（Commit `3f20e8e`，`2026-11-20`）  
> **底盘引擎**：`Godot Engine v4.8.beta1.mono.official` (64-bit) + `.NET 10` CoreCLR  
> **验证日期**：`2026-11-20`

> [!IMPORTANT]
> **官方仓库双代码线辨析（防止契约混用）**  
> 官方源码库中并存两条世代相反的代码线：
> 1. **现役生产主线 `Practice`（`origin/codex/fuvtt-project-sync` / Steam `v0.0.53` → `v0.0.57`）**：基于 Godot `4.8.beta1.mono` + C# `.NET 10` 的新一代重构线，外部插件唯一合法契约为 **`fus.session-plugin.v1`（`host_api = 1`, `scope = "session"`）**；
> 2. **已替代的早期原型线 `FUS-F2`（本地检出分支 `codex/post-dnd-followups`, Commit `ff4a1600`, `2026-10-06`, 回落版本号 `v0.1.80`, Godot `4.8-dev4` 非 Mono）**：早于 `Practice` 线约 1.5 个月，包含 `dnd_sdr`、`f2.feature_plugin.v1` 与 `HostBridge API v7`，**无法在当前 Steam 客户端加载**。  
> 本文档第 1～5 节 100% 锚定**现役 `Practice` 主线**；第 6 节将旧 `FUS-F2` 线 `dnd_sdr` 的核心设计模式作为前瞻架构参考独立归档。

---

## 1. 本地存储架构与世界存档格式 (`.world` 与 `FUSPRA01`)

Fu vtt（`Practice` 线）的本地桌面世界采用强校验、增量递增的二进制 `.world` 归档格式，结合外部 JSON 快速缓存机制与跨战役共享资产库管理。

### 1.1 存储目录与文件命名约定

- **会话存储根目录**：`FUS_Data/local_desktop/sessions/<session_name>_<session_token>/`
- **存档文件命名正则**：`^[0-9]{16}-[0-9a-f]{32}\.world$`
  - 前 16 位为递增的版本序列号计数器（如 `0000000000000001`），后 32 位为该版本内容的唯一 Hash 摘要。
- **外部插件存储根目录**：`FUS_Data/session_plugins/`（含 `registry.json` 与按 `<sha256>` 隔离的解压目录，受 C# `PluginPackageJob` 校验管理）。
- **存储摘要快速缓存**：`FUS_Data/local_desktop/.storage-summaries/<session_name>.json`
  - 由 C# 底层 `Practice.SaveStorageJob` 维护，快速缓存存档文件体积、对象分布、Token 数量与时间戳。
- **导入溯源与共享资产**：外部插件导入的新桌面会在会话目录保留 `source-import/original.<ext>` 源文件副本，图片资产经 `services/storage/SharedAssetStore.cs` 以内容寻址去重并映射为 `asset://<sha256>.<ext>`。

### 1.2 64 字节二进制头部结构 (`FUSPRA01`)

每个 `.world` 文件均以固定的 64 字节专有头部起始，用于防止存档损坏与非授权篡改：

| 偏移区间 (字节) | 长度 (字节) | 数据类型 | 字段说明与取值 |
| :--- | :--- | :--- | :--- |
| `0x00 - 0x07` | 8 | ASCII | 文件魔数标识，固定为 **`FUSPRA01`** |
| `0x08 - 0x0F` | 8 | `uint64` (小端) | 存档递增序列号 (`sequence_index`，如 1, 2...) |
| `0x10 - 0x17` | 8 | `uint64` (小端) | 存储子版本号 (`sub_version`) |
| `0x18 - 0x1F` | 8 | `uint64` (小端) | 有效载荷数据长度 (`payload_length`) |
| `0x20 - 0x3F` | 32 | `byte[32]` | SHA-256 校验哈希，供底层校验器核验完整性 |

### 1.3 有效载荷结构 (`fus.practice.campaign` & `fus.practice.world`)

头部 64 字节之后为标准的 Godot 4 Variant 二进制字典（起始字节为 `1B 00 00 00`，对应 `Variant::Type::DICTIONARY = 27`），现役 `Practice` 主线顶层结构与配额规范如下：

```json
{
  "format": "fus.practice.campaign",
  "metadata": {
    "campaign_uid": "camp_e9f2a7...",
    "name": "地牢大逃亡",
    "notes": "由外部插件导入。",
    "created_at": "2026-11-20T08:00:00Z",
    "module_choices": []
  },
  "world": {
    "format": "fus.practice.world",
    "version": 3,
    "catalog": {
      "active_floor_uid": "floor_main_uid",
      "floors": [
        {"id": "floor_0", "floor_uid": "floor_main_uid", "name": "一层", "color": "#4a6b82"}
      ],
      "layers": {
        "schema": "fus.floor_layers.v2",
        "floors": [
          {
            "floor_uid": "floor_main_uid",
            "layers": [
              {"layer_uid": "l_map", "name": "地图底图", "kind": "map", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
              {"layer_uid": "l_ent", "name": "实体", "kind": "entity", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
              {"layer_uid": "l_obs", "name": "障碍物", "kind": "obstacle", "visible": true, "locked": false, "persistent": true, "access": "host", "viewers": []}
            ]
          }
        ]
      }
    },
    "entity_state": {
      "version": 3,
      "entities": [ ... ]
    },
    "members": [
      {"entity_id": "ent_01...", "floor_uid": "floor_main_uid", "layer_uid": "l_ent"}
    ],
    "modules": {
      "version": 2,
      "entries": {}
    },
    "entity_manifest": {
      "version": 1,
      "lineage": "base_lineage",
      "serial": 12,
      "entities": {}
    }
  }
}
```

- **图层类型（`fus.floor_layers.v2`）**：支持 `"map"`、`"entity"`、`"obstacle"` 与 `"area"` 四类图层，默认 `locked = false`（详见 `shared/docs/desktop-and-scene-api.md`）。
- **`world.modules` 分区配额（`world_module_state.gd`）**：当前版本为 **`version = 2`**（向下兼容 `v1`）；顶层最多 **`128`** 个模块条目，单条模块状态上限 **`6 MiB`**，整个 `modules` 分区总上限 **`8 MiB`**（整体战役封装仍受 `16 MiB` 单文件上限约束）。

---

## 2. FOBR 容器格式与现役导入桥契约 (`.fobr` 与 `FOBR1`)

现役 `Practice` 线唯一官方外部插件为 `plugin_packages/fobr_world_import/`（`version: "0.5.1"`, `schema: "fus.session-plugin.v1"`, `host_api = 1`, `scope = "session"`），由 C# 内核 `Practice.FobrWallKernel`、`ImportBridge`（`scenes/session/plugins/import_bridge.gd`）与插件 `entry.gd` 协同执行离线导入。

### 2.1 FOBR 文件物理二进制布局

```text
+──────────────────────────+──────────────────────────+──────────────────────────────────────────────+
| 0x00 - 0x04 (5 Bytes)    | 0x05 - 0x08 (4 Bytes)    | 0x09 - EOF                                   |
| ASCII Magic: "FOBR1"     | uint32 (小端序)          | GZip 压缩数据流 (RFC 1952)                   |
| 固定魔数                 | 解压后有效载荷字节大小   | 经 GZip 解压后为标准的 UTF-8 编码 JSON 字符串|
+──────────────────────────+──────────────────────────+──────────────────────────────────────────────+
```

### 2.2 解包与封装算法参考 (Python)

```python
import gzip, json, struct

def unpack_fobr(fobr_path: str) -> dict:
    with open(fobr_path, "rb") as f:
        magic = f.read(5)
        if magic != b"FOBR1":
            raise ValueError(f"Invalid FOBR magic: {magic}")
        uncompressed_size = struct.unpack("<I", f.read(4))[0]
        compressed_payload = f.read()
        json_bytes = gzip.decompress(compressed_payload)
        assert len(json_bytes) == uncompressed_size
        return json.loads(json_bytes.decode("utf-8"))

def pack_fobr(data: dict, output_path: str) -> None:
    json_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
    compressed = gzip.compress(json_bytes)
    with open(output_path, "wb") as f:
        f.write(b"FOBR1")
        f.write(struct.pack("<I", len(json_bytes)))
        f.write(compressed)
```

### 2.3 解包后的场景对象模型 (`items`)

解压出的 JSON 核心包含 `"items"` 数组及可选场景元数据：

- 支持的图元类型（`type`）：
  - `"IMAGE"`：地图底图（`layer == "MAP"`）、角色 Token（`layer == "CHARACTER"`）或物件插画；
  - `"TEXT"`：文字标签（读取 `text.style.fontSize`）；
  - `"LINE"`, `"WALL"`, `"SHAPE"`, `"CURVE"`, `"PATH"`：矢量线条、墙体多边形与手绘涂鸦。
- 常见扩展元数据：
  - `metadata["rodeo.owlbear.dynamic-fog/doors"]`：门窗多边形与开合状态；
  - `metadata["com.battle-system.smoke/blocking"]`：烟雾与遮光墙体。

### 2.4 `v0.0.53` → `v0.0.57` 宿主导入桥增量演进

`fobr_world_import v0.5.1` 的 `plugin.json` 与 `entry.gd` 在 `v0.0.53` 至 `v0.0.57` 间保持零破坏性变更，宿主 `scenes/session/plugins/` 落地了 4 项增量改进：

1. **零长度门容错告警（`import_bridge.gd`）**：`decode_source()` 新增 `skipped_point_doors` 检查，自动调用 `warn()` 提示“已跳过 N 条起点和终点重合的门记录”；桌面备注标题由“素材提示”统一泛化为“导入提示”（`import_preview.gd` 后缀同步改为“详见桌面备注”），单次导入最多保留 `100` 条警告、写入备注前截断至 `7000` 字符。
2. **SVG 栅格化与共享资产去重（`import_bridge.gd`）**：`archive_image()` 遇到 `<svg` 资产时自动调用 `Image.load_svg_from_buffer()` 转为 PNG，并通过 `SharedAssetStore.cs` 发布为共享 `asset://<sha256>.<ext>` 引用；导入失败时先检查目标目录存在性再仅清理本次创建的未发布文件。
3. **窗口所有权与延迟租约（`plugin_import.gd`）**：文件选择对话框接入统一 `WindowPopupOwner`（`PopupOwner.attach`），将插件导入租约延后至用户选定文件进入 `begin_file()` 后申请，避免取消选文件时泄漏租约。
4. **拖放坐标缩放对齐（`session_plugin_drop.gd`）**：原生文件拖放坐标改用 `DesktopToolPointer.client_to_viewport()` 统一换算。

---

## 3. 墙体几何信封 (`.fuswalls`) 与障碍物自动烘焙机制 (`ObstacleShapes`)

### 3.1 墙体几何缓存信封 (`fus.fobr-wall-envelope`)

- 文件头声明：`godot-variant-no-objects/1`，包含 `schema: "fus.fobr-wall-envelope"`、`source_sha256`、`document`（`maps` 原点与 `walls` 的 `outer`/`holes` 顶点序列）及预剖分的 `rendering` 顶点数组。

### 3.2 `ImportBridge.run()` 障碍物自动布尔切割与组件注入

在现役 `Practice` 线中，导入插件**不需要也不应当**手动预计算碰撞网格或直接伪造障碍物碰撞缓存。`ImportBridge.run()` 在通过 `Snapshot.validate_data(world)` 校验后，会自动执行 `ObstacleShapes.prepare_import(world, _geometry)`（`modules/obstacle_authoring/obstacle_shape_data.gd`）：

1. **触发条件**：遍历 `world.entity_state.entities`，读取 `comp_visual.gd` 状态中的 `vector_drawing.source.kind`；凡 `kind` 属于 **`["wall", "air", "door", "window", "glass"]`** 且尚未挂载 `comp_obstacle.gd` 的实体，宿主自动接管烘焙。
2. **C# 几何烘焙与自动组件注入**：
   - 调用 `FobrWallKernel.CollisionSource(vector.paths, row.entity_size)` 生成签名形状字典 `shape`（含 `schema = 1`, `uid` SHA-256 摘要, `paths`, `segments`, `bounds`）；
   - 自动向该实体的 `components` 末尾（索引 `>= 2`，绝不破坏 `components[0..1]` 快路径）追加 `res://modules/obstacle_authoring/comp_obstacle.gd` 组件状态；
   - 按楼层与实体 ID 排序执行确定性布尔切割：`wall` 会被同楼层活跃的 `air`/`door`/`window`/`glass` 切割，`door`/`window`/`glass` 会被同楼层活跃的 `air` 切割，结果通过 `FobrWallKernel.CollisionBoundary()` 写入 `cache`（`digest_version = 2`）。
3. **严格输入门禁（防整包失败）**：
   - `vector_drawing.paths` 中的每条轮廓环必须为 `PackedVector2Array` 且**顶点数 `>= 3`**（总环数 `<= 8192`、总点数 `<= 200000`），否则 `ObstacleShapes.valid_paths()` 校验失败并导致整个导入以 `obstacle_shape_preparation_failed` 中止；
   - `source.enabled`（布尔，缺省 `true`）控制该障碍物在烘焙期是否参与切割；
   - 离线导入仅构造纯数据实体，宿主强制设置 `metadata.module_choices = []`，不实例化任何运行时玩法模块。

---

## 4. 现役 `Practice` 线内置模块架构与规则数据现状

现役 `Practice` 线彻底采用核心底座与可选模块解耦架构，但**当前所有桌面运行时模块均为受信任的内置模块**（由 `scenes/extension/desktop_feature_catalog.gd` 代码声明，**存档不提供可执行脚本路径**），**尚未对外开放第三方运行时规则插件**。

### 4.1 内置模块清单规模（9 核心 + 14 可选，共 23 项）

- **9 项核心底座（不可停用）**：`feature_networking`、`feature_component_sync`、`feature_edit_mode`、`feature_floor_system`、`feature_layer_stack`、`feature_obstacle_authoring`、`feature_debug_hooks`、`feature_component_library`、`feature_entity_library`。
- **14 项内置可选模块（按战役显式启用，默认关闭）**：`image_flip`、`drag_movement`、`drawing`、`areas`、`room_chat`、`player_cursors`、`map_fog_editor`（`v0.0.56` 新增）、`grid_alignment`、`detached_sidebar`、`follow`、`portal`、`simple_fog`、`dice`、`initiative`。
- **统一生命周期与状态持久化**：所有可选模块继承 `ExtensionBase`，通过 `prepare_module_state()`（树外预检）、`apply_module_state()` 与 `serialize_module_state()` 将纯数据状态写入 `world.modules`（`v2`）；通过精简版 `ExtensionContext` 登记组件、服务与 UI/网络 Slot（`network.actions`、`network.projections`、`network.presentations`、`save.readiness`、`ui.mode_bar`、`ui.mode_tools`、`ui.entity_actions`、`ui.canvas_actions`、`ui.sidebar_rail`）。

### 4.2 骰子、先攻与区域模块现状

| 模块 ID | 入口与服务 | 当前能力与数据契约 | 规则插件扩展口现状 |
| :--- | :--- | :--- | :--- |
| **`dice`**（通用骰子） | `modules/dice/feature_dice.tscn` → `scenes/candidates/dice/feature_dice.gd`<br>服务：`dice.local_results` | 状态 `schema_version = 5`（归档上限 `32,768` 条 / `256` 段 / `2 MiB` 压缩，网络协议 `v3`）；`dice_expression.gd` 内置解析 `d4/d6/d8/d10/d12/d20/d100` 及外层 `adv`/`dis`（参数 `1..3`）与 `burst`（参数 `1..10`），单次最多 `20` 枚实体骰（D100 占 2 枚）；支持公开/暗骰与独立原生 3D 程序 `Desktop Dice`（Windows Job 托管）。 | **无外部修饰器钩子**；`modules/dice/README.md` 明确注明未迁入旧 Godot 托盘、Bepu 或 D&D 插件。 |
| **`initiative`**（先攻与回合） | `modules/initiative/feature_initiative.tscn` → `scenes/candidates/initiative/feature_initiative.gd`<br>服务：`initiative.manual` | 规则无关的手动先攻列表与顶部先攻条，提供合作式本地显隐筛选（`entity_hidden`、`off_floor`、`layer_hidden`），不改写底层同步投影。 | **无外部公式注入接口**。 |
| **`areas`**（区域） | `modules/areas/areas.gd`<br>服务：`areas` | 注册私有组件 `comp_area.gd`（`network_scope = "private"`）、编辑模式 `areas.edit` 与 `actor_entered`/`actor_exited` 信号；支持圆形/矩形/多边形及布尔运算（独立/并集/交集/擦除），并向 `ui.entity_actions` 注入门口靠近“开门/关门”按钮（支持 `present_during_drag` 拖拽期呈现）。 | **无 D&D 困难地形/轻重遮蔽视野规则契约**。 |

### 4.3 D&D 规则集、宏系统与角色卡当前状态

- 在现役 `Practice` 线的 `docs/TODO.md` 中，**“传送门、DND、快捷移动”仍处于“具体规则和交互待定”状态**；
- 现役客户端**尚未实装内置宏执行引擎、角色卡系统、背包/资源池系统或第三方运行时规则插件 API**；
- 当前外部开发者面向 Steam `Practice` 客户端构建扩展的唯一受支持路径，是符合 **`fus.session-plugin.v1`（`host_api = 1`, `scope = "session"`）** 的离线场景/数据导入插件（详见 `shared/docs/plugin-lifecycle.md`）。

---

## 5. 外部导入脚本执行上下文与安全隔离边界

1. **宿主上下文注入**：`ImportBridge` 调用 `entry.gd` 的 `inspect_import(path, options, host)` 与 `prepare_import(path, options, host)` 时注入受控的 `host: RefCounted` 实例。
2. **后台线程与取消响应**：导入运行于 Godot `WorkerThreadPool` 后台线程，脚本不得直接操作场景树节点，且必须在循环中周期性检查 `host.cancelled()` 并优雅退出，避免资源悬挂。
3. **两阶段预览规范**：推荐先提交墙体/门窗等几何实体并调用 `host.finish_geometry_preview()`，再逐一调用 `host.archive_image(url, proxy)` 下载/归档重型图片素材，确保预览画布第一时间呈现结构轮廓。
4. **C# 强校验与沙箱边界**：所有外部插件包在安装与读取期均经 `Practice.PluginPackageJob` 强制校验（`schema == "fus.session-plugin.v1"`、`host_api == 1`、`scope == "session"`、`settings <= 32`、`import_extensions <= 8`、ZIP 条目 `2..1000`、解压上限 `256 MiB`、逐文件 `file_hashes` SHA-256 校验）；严禁直接写入工作区/受控 `FUS_Data/` 之外的系统路径，且 `comp_visual.sprite_path` 严禁写入 `user://` 路径。

---

## 6. 前瞻架构参考：旧 FUS-F2 线 `dnd_sdr` 规则插件设计精要

> [!CAUTION]
> **严禁用于当前 Steam `Practice` 客户端！**  
> 本节内容源自已被替代的早期原型线 `FUS-F2`（`codex/post-dnd-followups`, Commit `ff4a1600`, `v0.1.80`, `plugin_packages/dnd_sdr` `v0.2.0-test.33`）。其清单格式 `f2.feature_plugin.v1`、逻辑资源桥 `HostBridge API v7` 及全部运行时 Provider 钩子在现役 `Practice` 客户端（`v0.0.56`/`v0.0.57`）中**均不存在**，切勿直接编写依赖这些接口的生产插件。本节仅提炼官方曾验证过的规则插件架构范式，供未来 `Practice` 主线开放第三方规则插件时作为前瞻设计参考。

### 6.1 统一角色卡 / 怪物数据模型与 `{base, auto, override}` 三元组
- 角色卡（`CompDndSDRCharacterCard`）与怪物（`CompDndSDRMonsterData`）共享 `SCHEMA_VERSION = 2` 统一结构，可派生数值（属性、调整值、豁免、AC、先攻、法术 DC 等）一律存为 **`{base, auto, override}`** 三元组，解析优先级严格固定为 `override > auto > base`——既保留导入原值 `base`、支持自动规则计算写入 `auto`，又允许玩家或 DM 手工覆写 `override` 而不破坏底层数据。
- 数据组件是 HP/AC 唯一权威写源；血条显示组件仅通过鸭子类型方法（`get_hp_pair()` / `get_ac_value()`）软依赖读取，插件禁用时由 `detach_provided_component()` 将状态缓存至实体元数据、重启用时按需恢复，保证零残留且不丢用户数据。

### 6.2 “一切皆背包物品”与声明式动作 (`fus.ability.v1`)
- **行动经济完全解耦为被动物品**：废弃资源定义自带的自动回满字段，改由不可删除的规则被动物品监听宿主事件（如 `DND核心` 监听 `combat.turn_start` 恢复行动/附赠/反应/移动力、`法术位恢复` 监听 `rest.long` 恢复法术位），多移动方式（步行/飞行/游泳/攀爬/掘地）建模为同组互斥的 `switchable` 被动物品。
- **两段式声明动作（`fus.ability.v1`）**：动作声明只以纯 JSON 描述 `target`（几何形状、射程、阵营、阻挡）、`costs` 与 `effects`（含 `incomplete_effects` 显式声明未自动化部分）；宿主校验生成 `ability-v1.<sha256>` 绑定令牌，强制将目标选择与二次确认置于首次资源/状态写入之前，杜绝中途取消或状态变更导致的扣费泄漏。
- **中立语义富文本呈现**：插件向背包与单实例 Tooltip 注入纯文本分段数组 `description_segments`（白名单角色 `plain`/`keyword`/`value`/`dice`/`cost`/`duration`），严禁传递任意 BBCode/HTML，彻底防止导入文本注入。

### 6.3 纯数据声明式骰子修饰器 + 唯一宿主 RNG 铁律
- 规则插件只向宿主提交**深拷贝分离的纯数据声明**（严格禁止包含 `Callable`、`Object` 或 `NodePath`），例如 `adv`/`dis` 包装器、表达式入口与白名单视觉提示 `presentation_cue`，不重复声明宿主已自带的常规骰型。
- 角色卡快捷按钮严禁直接投骰，统一调用准备态接口 `prepare_roll_expression(expr, label, options)` 将公式与 `actor`/`caster`/`anchor` 上下文装入骰子面板等待玩家二次确认；解析、校验、随机数生成与 3D 演出 100% 归宿主独占，杜绝插件侧伪造骰点或旁路 RNG。

### 6.4 乐观锁权威动作与双桶限流边界
- **中立数值动作通道（`entity_stats_action_v1`）**：UnitCard 与快捷栏的 HP/临时 HP/AC 修改不直接写组件，而是携带稳定实体网络 ID 与 `expected_revision` 乐观并发版本号提交至房主；房主统一复用中立实体权限策略校验发送者身份，冲突即拒绝并返回最新权威摘要。
- **远端角色卡导入防护**：针对 `.xlsx`/OBR JSON 解析后经 RPC 提交的整卡快照，房主按 peer 实施**两级滑动窗口限流**（预解码验证桶 `6 次/10s` 先于结构与 PNG IHDR 校验拦截畸形请求，提交重放桶 `4 次/10s` 控提交频率），并施加强制载荷上限（编码体积 `<= 1.5 MB`、嵌套深度 `<= 12`、节点数 `<= 16,000`、二进制 `<= 750 KB`、头像 PNG 尺寸与像素数上限）与幂等 replay 账本。

### 6.5 只读中立宿主服务、存储根无关路径与 FOBR 零耦合联动
- **中立服务边界**：宿主仅提供格式无关的只读解码服务（如 `xlsx_workbook_reader_v1` 仅输出工作表名、单元格值与合并区），模板坐标映射与规则解释完全留在插件内部。
- **存储根无关路径解析**：插件通过辅助脚本自身的 `resource_path` 反推安装目录根，拒绝绝对路径与 `..` 越界段，不假设安装目录一定位于 `user://`，天然兼容用户迁移数据存储目录。
- **导入器与规则集解耦**：场景导入器与宿主虚拟化层只保留规则中立的源元数据（如 `obr_bestiary_slug`/`raw`、`obr_bubbles_raw`、`obr_bound_card_id`、`fobr_actor_evidence`），不解析具体 TRPG 规则；规则插件仅在启用或实体生成时单实体物化对应规则组件，对缺失正文的引用 fail-visible 告警而不编造空数据。
