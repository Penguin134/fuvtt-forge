# 场景地图、图层架构、战争迷雾与实体组件接口规范

> [!WARNING]
> **Playtest 内测阶段免责声明**  
> 当前处于 Playtest 内测阶段，后续 mod 接口可能存在变更。本文档基于官方源码库 `Practice` 主线（远端分支 `origin/codex/fuvtt-project-sync`）与本机 Steam 客户端实机双源核实沉淀。  
> **实测验证基准**：现役 `Practice` 主线 `v0.0.56`（Commit `282aee64`，`2026-11-19`）/ Steam Playtest 客户端 `v0.0.57`（Commit `3f20e8e`，`2026-11-20`）  
> **底盘引擎**：`Godot Engine v4.8.beta1.mono.official` (64-bit) + `.NET 10 CoreCLR`  
> **验证日期**：`2026-11-20`

---

## 1. 世界数据结构、网格坐标体系与图片金字塔

### 1.1 完整空世界 Schema (`world_defaults.gd` / `host.empty_world()`)

在现役 `Practice` 主线中，开桌、会话库与外部导入插件共享 `scenes/systems/world/world_defaults.gd` 的 `Defaults.create()`（经 `scenes/session/plugins/import_bridge.gd` 暴露为 `host.empty_world()`），返回完整结构如下：

```json
{
  "ok": true,
  "data": {
    "format": "fus.practice.world",
    "version": 3,
    "catalog": {
      "floor_identity_version": 1,
      "floors": [
        {
          "id": 0,
          "floor_uid": "<32位小写十六进制UID>",
          "name": "1F",
          "color": "Color(0.28, 0.65, 0.40)"
        }
      ],
      "layers": {
        "schema": "fus.floor_layers.v2",
        "floors": [ "..." ]
      },
      "active_floor_uid": "<32位小写十六进制UID>"
    },
    "entity_state": {
      "version": 3,
      "entities": []
    },
    "members": [],
    "modules": {
      "version": 2,
      "entries": {}
    }
  }
}
```

关键硬约束（来源 `scenes/systems/world/world_snapshot.gd` 与 `world_module_state.gd`）：
- **实体数量上限**：`MAX_ENTITIES = 10000`。
- **规范叠放顺序**：`WorldSnapshot` v2/v3 强制所有实体的 `properties.z_index == 0`（非 0 将触发 `noncanonical_entity_order` 拒收），叠放顺序完全由 `entity_state.entities` 数组顺序与所属图层顺序决定。
- **可选目录键**：`catalog` 另支持可选字段 `editor_view`（`{"layers": {<floor_uid>: <layer_uid>}, "all_unlocked": bool}`）与 `retired_layers`。
- **模块数据分区 (`world.modules`)**：`version = 2`（向下兼容 v1），最多 `128` 个模块条目，模块 ID 匹配 `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$`（最长 `128` 字符），单条 `state` 上限 **`6 MiB`**，整块 `modules` 上限 **`8 MiB`**。

### 1.2 网格比例转换常数与空间变换 (`xform`)

```gdscript
const SOURCE_UNITS_PER_CELL := 150.0  # 源场景标准网格像素分辨率 (150 DPI)
const WORLD_UNITS_PER_CELL := 64.0    # Fu vtt 世界网格基准尺寸 (64 单位/单元格)
const SOURCE_TO_WORLD := 64.0 / 150.0 # 0.4266666667
```

所有实体位姿收敛在 `xform` 字典中：
```json
{
  "pos": "Vector2(128.0, 256.0)",
  "rot": 0.0,
  "scale": "Vector2(1.0, 1.0)"
}
```
- **有限数与非零缩放硬门禁**（`scenes/entities/entity_state_codec.gd`）：`pos`、`rot`、`scale` 必须全部有限（禁止 `NaN` / `Inf`），且**严禁 `is_zero_approx(scale.x)` 或 `is_zero_approx(scale.y)`**。
- **尺寸与足迹范围**：`entity_size` 各分量须 `>= 4.0`；`footprint_radius` 须为有限浮点数且在 `[0.5, 4096.0]` 范围内（默认 `32.0`）。

### 1.3 图片金字塔（LOD）与 3D 物理骰子管线

- **大图金字塔与缓存配额**：现役 `Practice` 采用 `scenes/systems/images/image_pyramid_store.gd`、`image_pyramid_job.gd`、`scenes/entities/components/image_pyramid_view.gd` 搭配 C# `services/storage/LosslessTilePng.cs`、`DerivedCacheJob.cs`、`PlayerCacheInventory.cs`，按“概览预览 + 镜头细节瓦片”分层调度；玩家端磁盘缓存配额为 **`2 GiB`**，且磁盘缓存本身不授予读取权限。
- **3D 物理骰子与摄像机视角**：基于 Jolt Physics 的 3D 投骰管线独立运行于桌面之上；桌面摄像机视角配置按玩家/房间持久化于 `FUS_Data/camera_views_v1/`。

---

## 2. 楼层与场景图层架构 (`fus.floor_layers.v2`)

数据结构由 `catalog.layers` 统一管理（校验器：`scenes/systems/layers/layer_stack_state.gd`），当前 Schema 为 `"fus.floor_layers.v2"`（兼容读取旧 `"fus.floor_layers.v1"` 并自动补 `kind: "entity"`）。

### 2.1 配额上限与严格字段校验

- **全局配额**：`MAX_FLOORS = 512`、`MAX_LAYERS_PER_FLOOR = 256`、`MAX_TOTAL_LAYERS = 4096`、`MAX_SELECTED_VIEWERS = 128`、图层/楼层名称长度 `1..96`（去首尾空白，禁止 C0/DEL/C1 控制字符）、玩家身份键长度 `<= 160`。
- **新建默认楼层三层结构**（`LayerStackState.create_default_state()`）：

```json
{
  "schema": "fus.floor_layers.v2",
  "floors": [
    {
      "floor_uid": "<32-hex>",
      "default_layer_uid": "<sha256('fus.layer.default.v1:'+floor_uid).left(32)>",
      "layers": [
        {
          "layer_uid": "<sha256('fus.layer.map:'+floor_uid).left(32)>",
          "name": "地图底图",
          "kind": "map",
          "visible": true,
          "locked": false,
          "persistent": true,
          "access": "all",
          "viewers": []
        },
        {
          "layer_uid": "<default_layer_uid>",
          "name": "实体",
          "kind": "entity",
          "visible": true,
          "locked": false,
          "persistent": true,
          "access": "all",
          "viewers": []
        },
        {
          "layer_uid": "<sha256('fus.layer.obstacle:'+floor_uid).left(32)>",
          "name": "障碍物",
          "kind": "obstacle",
          "visible": true,
          "locked": false,
          "persistent": true,
          "access": "host",
          "viewers": []
        }
      ]
    }
  ]
}
```

> [!IMPORTANT]
> **源码级勘误**：`create_default_state()` 生成的默认三层 **`locked` 均为 `false`**（旧文档误记为 `map`/`obstacle` 默认 `true`）。`access` 合法值为 `"all"` / `"host"` / `"players"`，且仅当 `access == "players"` 时 `viewers` 必须非空（存放稳定玩家 ID 字符串，禁止临时数字 peer ID）。

### 2.2 四类图层职责与编辑模式绑定

| `kind` | 默认名称 | 默认访问策略 (`access`) | 允许编辑模式 | 承载对象与用途 |
| :--- | :--- | :--- | :--- | :--- |
| `"map"` | 地图底图 | `"all"` | 常规模式 | 静态大图贴图、环境地板、地理网格底图 |
| `"entity"` | 实体 | `"all"` | 常规模式 | 角色 Token（`unit`）、NPC、道具、文本图钉、矢量注释 |
| `"obstacle"` | 障碍物 | `"host"` | `"build"` | 墙体、空气挖空、门、窗、可见遮挡体（玻璃） |
| `"area"` | 区域（可选新建） | 按需配置 | `"areas.edit"` | 空间交互区域、临近触发范围 |

### 2.3 实体与图层绑定 (`world.members`)

实体通过顶层 `world.members` 表绑定到具体楼层与持久图层（`persistent == true`）：
```json
{
  "entity_id": "8a3f81e3...",
  "floor_uid": "<32-hex>",
  "layer_uid": "<32-hex>"
}
```

---

## 3. 障碍物几何、自动布尔烘焙与战争迷雾

### 3.1 五类原生障碍物语义 (`modules/obstacle_authoring/obstacle_document.gd`)

现役 `Practice` 统一使用 `BoardToken` + `CompVisual.vector_drawing`（`source.kind`）表达 5 类障碍物，并在渲染层由 `ObstacleDocument.COLORS` 接管配色：

| `source.kind` | 中文语义 | 支持状态标志 | 宿主编辑配色 (`ObstacleDocument.COLORS`) | 布尔切割与阻挡行为 |
| :--- | :--- | :--- | :--- | :--- |
| `"wall"` | 墙 | `enabled` | `Color(0, 1, 0, 0.7)` | 阻挡视野与移动；被同楼层 `air`/`door`/`window`/`glass` 自动切割 |
| `"air"` | 空气 | `enabled` | `Color(0.09, 0.59, 0.71, 0.7)` | 永不阻挡；从重叠的墙/门/窗/玻璃中布尔挖洞，不破坏源顶点 |
| `"door"` | 门 | `enabled`, `open` | `Color(1, 0, 1, 0.7)` | 关态阻挡视野与移动，开态 (`open=true`) 放行 |
| `"window"` | 窗 | `enabled`, `open` | `Color(0, 0, 1, 0.7)` | 关态阻挡移动、透光，开态放行 |
| `"glass"` | 可见遮挡体 | `enabled` | `Color(1, 1, 1, 0.7)` | 专用模糊着色 (`ObstacleBlur`) 与对应遮挡规则 |

### 3.2 导入期自动注入 `comp_obstacle.gd` 与 C# `FobrWallKernel` 烘焙

`ImportBridge.run()`（`scenes/session/plugins/import_bridge.gd`）在校验 `WorldSnapshot.validate_data(world)` 通过后，会自动调用 **`ObstacleShapes.prepare_import(world, _geometry)`**（`modules/obstacle_authoring/obstacle_shape_data.gd`）：
1. 扫描所有 `vector_drawing.source.kind ∈ ["wall", "air", "door", "window", "glass"]` 的实体；
2. 若实体尚未显式挂载 `res://modules/obstacle_authoring/comp_obstacle.gd`，自动调用 C# `FobrWallKernel.CollisionSource(paths, size)` 计算带 SHA-256 签名的 `shape`（`paths` + `segments` + `bounds`）并注入 `comp_obstacle.gd`；
3. 按楼层运行 `prepare_facts()`：自动用同楼层活跃的 `air`/`door`/`window`/`glass` 对 `wall`（及用 `air` 对 `door`/`window`/`glass`）执行 C# `FobrWallKernel.CollisionBoundary()` 布尔差集并写入 `cache`。
4. **严格输入前提**：`ObstacleShapes.valid_paths()` 要求**每条路径环至少 3 个顶点**（`ring.size() >= 3`）、总环数 `<= 8192`、总点数 `<= 200000`；若导入插件向障碍物写入 2 点退化线段，将导致整个导入以 `obstacle_shape_preparation_failed` 失败（`fu_sdk` v1.1 已自动过滤 `< 3` 点环并告警）。

### 3.3 双迷雾模块（互斥）

- **简易迷雾 (`modules/simple_fog/`)**：合作式本机 GPU 视野/光照显隐（挂载 `comp_simple_vision.gd` / `comp_simple_light.gd`），**不参与实体披露拦截**，操控权撤回仅收回该角色的观察源。
- **完整迷雾（与简易迷雾互斥）**：基于 `PointLight2D` / `LightOccluder2D`（R 基础视距 / G 通往亮区视线 / B 环境照明，合成 `max(R, min(G, B))`）+ 原生 C# `FogGeometryKernel*.cs` 后台计算按角色/楼层隔离的探索历史，只向玩家下发当前获准角色的匿名历史几何。

---

## 4. ECS 实体与组件（`comp_*.gd`）全量图谱

### 4.1 实体核心序列化结构 (`EntityStateCodec`, `VERSION = 3`)

```json
{
  "id": "e3b0c44298fc1c149afbf4c8996fb924",
  "display_name": "游侠埃尔隆",
  "entity_type": "unit",
  "entity_size": "Vector2(64.0, 64.0)",
  "selectable_in_select_mode": true,
  "footprint_radius": 32.0,
  "fallback_color": "Color(0.55, 0.6, 0.7, 1.0)",
  "xform": {
    "pos": "Vector2(128.0, 128.0)",
    "rot": 0.0,
    "scale": "Vector2(1.0, 1.0)"
  },
  "flags": {
    "entity_hidden": false,
    "entity_locked": false
  },
  "components": [
    {
      "script": "res://scenes/entities/components/comp_visual.gd",
      "state": { "..." }
    },
    {
      "script": "res://scenes/entities/components/comp_permission.gd",
      "state": { "..." }
    }
  ]
}
```

> [!CAUTION]
> **必须严守的两项核心不变量**：
> 1. **`components[0..1]` 固定前缀**：`ImportBridge.preview_entity` 硬编码读取 `entity.components[0].state`，且 `EntityStateCodec.EntryCoreDrafts.prefix_for` 要求前两项严格为 `[comp_visual.gd, comp_permission.gd]` 才可命中晚加入快路径；所有可选组件必须追加在索引 `>= 2`。
> 2. **`CompVisual.sprite_path` 严禁 `user://`**：`CompVisual._valid_image_path()` 仅允许空串 `""`、`asset://<sha256>.<ext>`（通过 `host.archive_image()` 归档获得）或已存在的 `res://*.{png,jpg,jpeg,webp,svg}`；传入 `user://` 将直接被 `WorldSnapshot.validate_data()` 拒收！

### 4.2 `CompVisual` 状态与 `vector_drawing` 强配额

- **贴图模式**：`{"enabled": true, "show_fallback": true, "fallback_color": Color(...), "sprite_path": "asset://<64-hex>.png", "source_info": {}}`
- **矢量与文字模式**（`scenes/entities/components/vector_drawing.gd`）：
  - `schema`: 必须为 `1`
  - `vertices`: `PackedVector2Array`，长度 `<= 600000` 且为 `3` 的倍数（三角形顶点）
  - `paths`: `Array[PackedVector2Array]`，数量 `<= 8192`，且 `vertices.size() + sum(path.size()) <= 800000`
  - `color` / `line_color`: `Color`
  - `text`: `String`，长度 `<= 65536`
  - `font_size`: `float`，有限数且在 `[1.0, 4096.0]` 范围内
  - `source`: `Dictionary`（障碍物携带 `{"kind": "wall"|"air"|"door"|"window"|"glass", "enabled": bool, "open"?: bool}`）

### 4.3 现役 `Practice` 全量 18 个 ECS 组件速查表

所有未安装或当前未启用的可选组件记录可在序列化时携带 `"parked": true`，宿主校验时将不透明保留其状态，防止数据丢失。

| # | 脚本路径 (`res://...`) | 核心持久化字段 | 职责与网络/权限说明 |
| :--- | :--- | :--- | :--- |
| 1 | `scenes/entities/components/comp_base.gd` | `serialize_state()` / `serialize_network_state()` / `serialize_snapshot_pair()` | 组件基类；支持全量/网络双快照分离与核心快路径采集 |
| 2 | `scenes/entities/components/comp_visual.gd` | `enabled`, `fallback_color`, `sprite_path`, `show_fallback`, `vector_drawing`, `source_info` | **必需核心组件**；Sprite、大图金字塔与矢量/文字渲染 |
| 3 | `scenes/entities/components/comp_permission.gd` | `owners_csv`, `gm_can_operate`, `all_players_can_operate`, `owner_peers`, `owner_player_ids` | **必需核心组件**；联机操控权威只认 `DesktopNetworkSession` 签发的 `owner_player_ids` |
| 4 | `scenes/entities/components/comp_unit.gd` | `schema_version` (`1`) | 通用单位身份标记（要求宿主 `entity_type != "map"`） |
| 5 | `modules/obstacle_authoring/comp_obstacle.gd` | `role`, `shape_mode`, `shape`, `cache`（网络版 `cache = {}`） | 墙/空气/门/窗/玻璃碰撞与布尔差集缓存；导入期自动注入 |
| 6 | `modules/simple_fog/comp_simple_vision.gd` | `enabled`, `requires_light`, `radius` (`>=0`), `view_angle` (`0..360°`) | 简易迷雾观察者（角度单位为**度**） |
| 7 | `modules/simple_fog/comp_simple_light.gd` | 继承 `comp_simple_vision.gd`（`enabled`, `radius`, `view_angle`） | 简易迷雾环境光源（不授予观察资格） |
| 8 | `modules/areas/comp_area.gd` | `removed`, `radius_in_cells` | 空间区域 / 临近交互触发范围 |
| 9 | `modules/drag_movement/comp_drag_speed.gd` | `speed` | 匀速拖拽移动速率 |
| 10 | `modules/drawing/comp_entity_ink.gd` | `serialize_state()` 自定义 | 实体表面像素墨迹（搭配 `EntityInkAtlas.cs`） |
| 11 | `modules/follow/comp_follow.gd` | `target_id`, `controller_id`, `engaged`, `follow_distance` | 单位跟随与路径轨迹 |
| 12 | `modules/image_flip/comp_image_flip.gd` | `horizontal`, `vertical` | 实体图片水平/垂直镜像翻转 |
| 13 | `modules/portal/comp_portal.gd` | `pair_key` (`""` 或 32 位小写十六进制 UID) | 成对传送门端点 |
| 14 | `scenes/candidates/entity_notes/comp_entity_note.gd` | `schema_version` (`1`), `text` (`<=32768`), `keep_screen_size`, `is_pin` | 实体备注与世界文本图钉（`is_pin=true` 启用 `PinView` 缩放不变命中） |
| 15 | `scenes/candidates/initiative/components/comp_initiative.gd` | `count`, `modifier`, `active`, `defeated`, `rolled` | 先攻条战斗轮序 |
| 16 | `scenes/candidates/resource_pool/comp_resource_pool.gd` | `schema_version`, `values: Dictionary` | 通用资源池与数值属性 |
| 17 | `scenes/candidates/scene_box/comp_scene_box.gd` | `schema_version` (`1`), `scene_uid` | 场景盒 / 嵌套场景引用 |
| 18 | `scenes/candidates/module_example/comp_example_badge.gd` | `schema_version`, `enabled`, `label` | 内置模块开发示例徽章 |

---

## 5. 联机同步架构、模块契约与权限边界

### 5.1 传输通道与原生同步分工

现役 `Practice` Wire 协议标识为 `fus-practice/38-retained-reconnect-20261107`（来源 `docs/core/network-sync.md`、`docs/core/network-transports.md`）：
- **三通道优先级（Steam 优先级 `2 -> 0 -> 1`）**：
  - 通道 `0`：`MultiplayerSynchronizer` / `MultiplayerSpawner` 原生状态同步（棋子 `native_actor_transport.gd` + 根姿态 `NativePoseSync` + 图层显隐位图 `native_layer_visibility.gd`）；
  - 通道 `1`：图片素材与超大字段 16 KiB 分块载荷（`native_field_transfer.gd`，单字段上限 `32 MiB`，收发缓冲各 `64 MiB`）；
  - 通道 `2`：离散指令、房间控制与模块动作 RPC。
- **客户端不预测写位置**：玩家仅发送移动目标，权威主机核验权限与碰撞后以 `ALWAYS` 流同步根姿态，静止 3 个物理周期后以 `ON_CHANGE` 小快照可靠收尾。

### 5.2 四大核心模块网络契约

1. **房间握手契约（`scenes/board/networking/network_module_contract.gd`）**：`VERSION = 1`，清单 `{version, campaign_uid, generation, modules: [{id, version}], world_generation?, module_generations?}`（上限 128 模块），**仅传可信模块 ID 与协议版本号，绝不携带可执行路径或主持私有状态**。标记 `isolated_lifecycle: true` 的内置模块支持 `module_patch_flow.gd` 局部热启停。
2. **动作提交（`module_action_exchange.gd`，Slot `&"network.actions"`）**：仅主机权威执行，每玩家队列限 8、总限 64、超时 5000ms；可替换瞬时目标（如匀速拖拽 `goal`）通过 `notify_module_action` 与 `network_notification_key` 去重节流。
3. **状态投影（`module_projections.gd`，Slot `&"network.projections"`）**：两阶段原子提交（`stage -> publish -> world_current`）与失败逆序回滚；仅安装侧可信声明 `replica_presentation_only: true`（迷雾/拖拽/网格/先攻/骰子）可走只读呈现快速路径，**禁止网络载荷自报资格**。
4. **即时表现层（`module_presentation_exchange.gd`，Slot `&"network.presentations"`）**：独立分块通道（单包 `<= 3 MiB`、总队列 `<= 16 MiB`、`<= 32` 任务、每帧 4 块 / 2ms 预算），每块发送前重查授权，严禁写世界状态或存档。

### 5.3 合作式视野与权限隔离边界

- **合作式显隐原则（2026-11-06 裁决）**：合作场景下实体正常下发，视觉显隐由本机迷雾负责，**不提供视野反作弊**。
- **严格保留的安全边界**：
  - **房间准入与身份权威**：仅认主持准入表签发的稳定玩家身份（`owner_player_ids`），本地缓存与历史回执不授予权限；
  - **数据隔离**：图层披露策略（`access: "host" | "players"`）、私有组件（`network_scope == "private"`）与 `parked` 停放数据严格留存完整存档，不向未授权客户端下发；
  - **纯数据边界校验**：`services/storage/native_data_validation/data_validator.gd`（底层 `fus_data_validator.dll`）与 C# `PackedValueValidation.cs`、`WorldSnapshot.validate_data()` 共同负责二进制/字典纯数据边界与防越界校验，并非客户端移动签名反作弊。

---

## 6. 附录：旧原型线 `FUS-F2` (`v0.1.80`) 架构差异备忘

> [!NOTE]
> 官方源码仓库本地默认检出分支 `codex/post-dnd-followups`（Commit `ff4a1600`，`2026-10-06`，`v0.1.80`）为**已被现役 `Practice` 替代的早期纯 GDScript + C++ 原型线**，请勿与现役 Steam `Practice` 混用：
> - 旧线存档为 `SessionSaveManager` 单文件 `var_to_bytes`，使用 `fus.floor_layers.v1`（无 `kind` 字段），将墙/门/窗/空气拆为独立 `DrawnShape`（`StaticBody2D`），其 `CompVisual` **不含 `vector_drawing` 与 `source_info`**；
> - 旧线含 29 个 `comp_*.gd`（含 `comp_air.gd`、`comp_barrier.gd`、`comp_door.gd`、`comp_faction.gd`、`comp_backpack.gd` 与 `dnd_sdr` 的 2 个组件），联机采用 `EntityReplicationPolicy` 服务端严密隐藏信息过滤、`FeatureComponentSync` Hook 自动同步与 C++ `fus_history_geometry` 分块蒙版 v5。
