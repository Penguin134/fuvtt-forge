# Shared SDK (`fu_sdk` 防腐层共享库)

本目录承载跨插件复用的 **Fu vtt 防腐层 SDK（Anti-Corruption Layer）**，为工作区内所有 `mods/<mod-name>/` 提供稳定的跑团场景导入语义接口，彻底屏蔽宿主底层字典结构与内测期接口变动风险。

> [!WARNING]
> **Playtest 内测阶段说明**  
> 当前实测验证基线为现役 **`Practice` 主线 `v0.0.60`（Git `origin/codex/playtest-v060-20261122`，Commit `cc3d43a5`）/ Steam Playtest `v0.0.57`–`v0.0.62`**，验证日期：`2026-11-24`（`fus.session-plugin.v1` / `host_api = 1` / `fus.practice.world` v3 / `fus.floor_layers.v2` / `SceneRepository` v2；含 `v0.0.61`–`v0.0.62` `campaign_time` 与 `dnd_opportunity` Playtest 临时禁用与状态保留）。  
> 所有与客户端底层强耦合的字段名、组件脚本路径与图层结构均已收敛至 `fu_sdk/adapters/` 与 `fu_sdk/plugins/`，禁止在业务插件中直接硬编码底层世界字典。本 SDK **不适用于**旧原型线 `FUS-F2`（`v0.1.80`）。

## 1. 目录结构与职责边界

`shared/sdk/fu_sdk/` 共包含 **35 个独立 `.gd` 脚本**（全部遵循 `extends RefCounted`、UTF-8 无 BOM、LF 换行、零 `class_name`、零 `preload(` 与零本机硬编码路径），按职责分为 6 层：

- `fu_sdk/v1.gd`（`SDK_VERSION = "1.3.0"`）：面向下游插件向后兼容演进的 `v1` 稳定门面，提供外层实例工厂（含 `create_logger`、`create_module_registry`、`create_plugin_sdk`）、`coerce_*` 安全强转助手、`ImportSession` 会话上下文与 `WorldBuilder` 高阶 **场景 >> 楼层 >> 图层** / `Scene Box` / 分模块 SDK 构建器（外层通过 `_load_sdk_sub_script(...)`、内部类通过 `_load_util_script(...)` 按需加载子脚本）。
- `fu_sdk/adapters/host_v1_adapter.gd`：面向 `host_api = 1` 宿主的唯一底层适配器，负责：
  - `host.has_method(...)` 宿主能力安全嗅探（`cancelled`、`report`、`warn`、`archive_image`、`inspect_source`、`decode_source`、`empty_world`、预览回调）；
  - `inspect_import` 返回值兜底保护（自动计算 `sha256`、`source_bytes`、`decoded_bytes`、`unique_images`、`name`，并补齐包含 `"unsupported": 0` 在内的全部 12 项默认 `counts` 键）；
  - 世界字典强契约守卫：`extract_default_world_targets()` 兜底补齐 `entity_state.version = 3` 与 `modules = {"version": 2, "entries": {}}`；
  - 坐标、文本、矢量与模块预算守卫：头部 UTF-8 BOM（`0xFEFF`）剥离、`pos/rot/scale` 有限数与非零缩放守卫、`footprint_radius ∈ [0.5, 4096.0]`、`font_size ∈ [1.0, 4096.0]`、`text <= 65536`、`vertices <= 600000`、`paths <= 8192`、总点数 `<= 800000`，以及 `world.modules` 递归纯数据净化与 **`16 MiB / 24 MiB / 30 MiB`** 预算校验（对齐 `v0.0.60` `world_module_state.gd` 标量成本表）；
  - **`SceneRepository` 多场景常驻目录与 `CompSceneBox` 防腐封装**：自动维护 `world.modules.entries["scene_box"]`（`version = 1`, `schema_version = 2`, `1..64` 场景互斥划分 `<= 512` 楼层），同步 `host_active_scene_uid` 与 `catalog.active_floor_uid`，支持 `add_scene_box` / `attach_scene_box`（固定正方形 `[72.0, 256.0]`、`xform.scale = Vector2.ONE`、`CompPermission` 三态映射、`cover_asset` 正则校验）与 `BoardToken.SCENE_BOX_CONFLICTS` 互斥守卫；
  - **`sprite_path` 前置合法性拦截（拆分 `asset://` 与 `res://` 白名单）**：`ALLOWED_ASSET_IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "webp", "bmp"]`（对齐宿主 `CampaignImageFiles` / `ImageHeader`，拒收 `.svg` 与 `.gif`）、`ALLOWED_RES_IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "webp", "bmp", "svg"]`，主动拦截 `user://` 等非法路径并向 `ImportSession` 记警告；
  - **跨楼层 `layer_uid_override` 自动解析**：`WorldBuilder` 维护 `_layer_to_floor` 反向索引，跨场景/跨楼层传 `layer_uid_override` 写入实体时自动在 `world.members` 绑定图层所属真实 `floor_uid`；
  - **5 类原生障碍物、线段挤出与带孔多边形裁剪**：支持 `wall` / `air` / `door` / `window` / `glass` 全 5 类角色，提供 `extrude_segment_to_quad()` 将 2 点线段按法线挤出为带 ULP 鞋带面积校验的 4 顶点闭合多边形，自动过滤 `< 3` 点退化环防 `obstacle_shape_preparation_failed`，并对带内孔多边形先执行 `Geometry2D.clip_polygons` 切分扣洞再三角剖分，落盘时自动由宿主 `ImportBridge` 注入 `comp_obstacle.gd`；
  - **核心组件前缀不变量与 `parked`/`manual` 停放支持**：`append_entity()` 与 `append_entity_component()` 严格锁死 `components[0] = comp_visual.gd`、`components[1] = comp_permission.gd`，所有可选组件一律追加在索引 `>= 2`，并支持 `parked: bool` 与 `manual: bool`（仅当 `parked == true` 时有效，对齐 `<FUS_REPO_DIR>/scenes/entities/board_token.gd:301-368`）。
- `fu_sdk/logging/log_bus.gd`（R3 结构化日志总线）：提供 `DEBUG`/`INFO`/`WARNING`/`ERROR` 四级日志、有界环形缓冲区、顺序游标读取、实时订阅/退订机制，以及受 `100 条 / 7000 字符` 上限保护的 `ImportBridge` 宿主桥接转发。
- `fu_sdk/plugins/`（R1 & R2 原生模块注册表与 23 个独立分脚本 SDK）：
  - `plugins/module_registry.gd`：完整收录 `<FUS_REPO_DIR>` `DesktopFeatureCatalog` 的 `30` 个正式模块（`9` 核心 + `21` 可选）与 `3` 个非目录候选模块（`entity_notes`、`music_board`、`module_example`），追踪声明式启用状态、Playtest `v0.0.61`–`v0.0.62` 禁用状态（`campaign_time`、`dnd_opportunity`），并在调用未启用/被禁用/未入目录模块时执行 R2 警告与 `"preserve"` / `"skip"` 策略；
  - `plugins/<module_id>.gd`（共 **23** 个独立脚本，严禁将多个原生插件混写在同一脚本内）：每个具备 Mod 可用接口或持久化状态的原生插件独立拆分；**全部 23 个**分脚本（**5** 个核心基础模块 + **18** 个可选及候选插件分脚本）均在 `configure()` 内通过 `WeakRef`（`_world_builder_ref` + `_wb()`）持有 `WorldBuilder` 弱引用，彻底规避 `RefCounted` 循环引用（经无头实测 `ObjectDB` 泄漏增量为 `0.0`）。
- `fu_sdk/modules/`（4 个跨插件复用的纯 GDScript 功能子模块库，随 `lib/fu_sdk/` 一并自动内嵌打包，见 §3.5；内部严禁 `load()` 同级 `modules/*.gd` 或 `utils/*.gd`）：
  - `asset_publisher.gd`（图片魔数/头预检、BMP/SVG 转 PNG、`SharedAssetStore.Publish` 与 `MockHostBridge` 回退）
  - `entity_library_writer.gd`（`<root>/entity-library/` 安全四门控写入、`.revision` 链式传递与原子回滚）
  - `package_source.gd`（`.zip` 归档与解压目录清单双输入抽象读取器）
  - `snappy.gd`（纯 GDScript Snappy 块解压器）
- `fu_sdk/utils/`（4 个纯叶子级静态工具脚本，严禁声明 `class_name`、严禁调用 `preload()` 或 `load()`，仅使用 `extends RefCounted` 与 `static func`）：由 `v1.gd`、`adapters/`、`logging/` 与 `plugins/` 通过实例级 `_util_scripts` 缓存按相对路径按需加载（见 §3.8），收敛重度 DAG 深拷贝（`dag_cloner.gd`）、轻量有界深拷贝与环检测（`bounded_cloner.gd`）、基础强转与颜色规整（`value_utils.gd`）以及十六进制校验与文本清理（`validation_utils.gd`）。

## 2. 构建期自动内嵌（Vendored Bundle）与动态加载规范

由于当前客户端 `session_plugins` 运行于 `res://` 外部的独立内容寻址目录（`FUS_Data/session_plugins/packages/<id>/<sha256>/`），且不支持跨插件依赖声明：

1. **自动内嵌打包**：执行 `python shared/tools/fuvtt_cli.py build <mod-name>` 时，打包器（`packager.py` 递归 `rglob("*.gd")`）会自动将 `shared/sdk/fu_sdk/` 下**全部 35 个 `.gd` 脚本**（含 `v1.gd`、`adapters/`、`logging/log_bus.gd`、`plugins/module_registry.gd`、`plugins/*.gd`、`modules/*.gd` 与 `utils/*.gd`）注入插件归档内的 `lib/fu_sdk/` 目录，对终端玩家保持零前置依赖。
2. **禁止使用 `preload()`**：在 `res://` 之外的文件系统目录中，`preload()` 无法可靠解析相对路径，必须统一使用基于 `(get_script() as Script).resource_path.get_base_dir()` 的运行时 `load()`。
3. **优先外层实例工厂，规避 Godot 4 内部类陷阱**：在 Godot 4 中，脚本内部类（`class Inner extends RefCounted`）实例上调用 `get_script()` 可能无法获取外层 `.gd` 文件的 `resource_path`。推荐通过 `FuSdkScript.new()` 实例化外层门面并调用工厂方法（同时 SDK 内部亦已对 `FuSdkScript.ImportSession` / `FuSdkScript.WorldBuilder` 直接访问做了静态缓存与栈回退兼容）：

```gdscript
extends RefCounted

const _SDK_PACKAGED_REL_PATH := "lib/fu_sdk/v1.gd"
const _SDK_DEV_REL_PATH := "../../shared/sdk/fu_sdk/v1.gd"


func _create_sdk() -> RefCounted:
	var base_dir: String = (get_script() as Script).resource_path.split("::")[0].get_base_dir()
	var packaged_path: String = base_dir.path_join(_SDK_PACKAGED_REL_PATH)
	var sdk_path: String = packaged_path if FileAccess.file_exists(packaged_path) else base_dir.path_join(_SDK_DEV_REL_PATH).simplify_path()
	if not FileAccess.file_exists(sdk_path) and not ResourceLoader.exists(sdk_path):
		return null
	var sdk_script := load(sdk_path) as Script
	return sdk_script.new() if sdk_script != null else null
```

## 3. 核心 API 速览 (`fu_sdk/v1.gd`)

### 3.1 `FuSdk` 门面实例方法与类型强转助手
- `create_session(host: RefCounted, options: Dictionary = {}) -> ImportSession`
- `create_world_builder(session: ImportSession = null, source_units_per_cell: float = 150.0) -> WorldBuilder`
- `create_logger(options: Dictionary = {}) -> RefCounted`：实例化 `logging/log_bus.gd`（支持 `max_entries`、`min_level`、`emit_to_engine`、`host`、`forward_reports` 初始化配置）。
- `create_module_registry(log_bus: RefCounted = null, session: ImportSession = null) -> RefCounted`：实例化 `plugins/module_registry.gd`。
- `create_plugin_sdk(module_id: String, world_builder: WorldBuilder = null) -> RefCounted`：按模块 ID 加载 `plugins/<module_id>.gd`（传入 `world_builder` 时自动共享其 `ModuleRegistry` 与 `LogBus`）。
- `create_asset_publisher() -> RefCounted`：实例化 `modules/asset_publisher.gd`。
- `create_entity_library_writer() -> RefCounted`：实例化 `modules/entity_library_writer.gd`。
- `create_package_source() -> RefCounted`：实例化 `modules/package_source.gd`。
- `create_snappy_codec() -> RefCounted`：实例化 `modules/snappy.gd`。
- `coerce_bool(value: Variant, fallback: bool = false) -> bool`：安全转换 `bool` / 非零 `int` / 有限非 `NaN` `float` / `"true"/"1"/"yes"/"on"` 与 `"false"/"0"/"no"/"off"`。
- `coerce_string(value: Variant, fallback: String = "") -> String`：仅当 `typeof(value) == TYPE_STRING` 时返回原串，绝不把 `null` 转成 `"Null"`。
- `coerce_int(value: Variant, fallback: int = 0) -> int`：带 64 位有符号整数上下界检查（`-9223372036854775808..9223372036854775807`）的安全整数强转。
- `coerce_float(value: Variant, fallback: float = 0.0) -> float`：安全转换整数、有限浮点数或合法有限浮点字符串。

### 3.2 `ImportSession`
- `get_logger() -> RefCounted` / `set_logger(logger: RefCounted) -> void`：获取或替换当前会话绑定的 `LogBus` 实例（创建时自动 `attach_import_host(_host, false)`）。
- `get_bool_option(key: String, fallback: bool = false) -> bool` / `get_string_option(key: String, fallback: String = "") -> String` / `get_int_option(key: String, fallback: int = 0) -> int` / `get_float_option(key: String, fallback: float = 0.0) -> float`：类型安全的选项读取接口。
- `sanitize_options(defaults: Dictionary) -> Dictionary`：按 `defaults` 字典的值类型一次性批量清洗 `options`，彻底防止 `options = {"proxy": null}` 在读取或透传时变成 `"Null"`。
- `is_cancelled() -> bool`：检查用户是否取消导入。
- `report_progress(message: String) -> void`：向宿主汇报当前转换进度。
- `add_warning(message: String) -> void`：记录非致命警告（绑定 `LogBus` 时委托 `_log_bus.warn("session", clean_msg)`，自动兼顾环形缓冲区与宿主去重/上限保护）。
- `archive_remote_image(url: String, proxy: String = "") -> String`：按 URL 去重下载并归档外部图片，返回 `asset://` 引用（失败或非法路径自动记警告并返回 `""`；读取 `_options["proxy"]` 时已做 `typeof == TYPE_STRING` 防 `null` 守卫）。
- `validate_sprite_path(sprite_ref: String) -> String`：校验外部传入的贴图路径，拦截 `user://` 及 `asset://` 非白名单扩展名并记警告。
- `inspect_source(path: String) -> Dictionary` / `decode_source(path: String) -> Dictionary`：可选探测并调用宿主自带的 FOBR/几何解析内核。
- `ok_inspect(source_path: String, counts_override: Dictionary = {}, remote_assets: Dictionary = {}, decoded_bytes: int = -1, display_name: String = "") -> Dictionary`：构造符合宿主 `ImportBridge` 与 `import_confirmation.gd` 强校验的探测成功字典，自动注入 `sha256`、`source_bytes`、`decoded_bytes`（默认回退 `source_bytes`）、`unique_images`（`maxi(counts.images, remote_assets.size())`）与 `name`（清洗后的 `display_name` 或源文件名）。注意 `remote_assets` 仅应传入 `http://`/`https://` URL，切勿放入本地图片路径。
- `err_cancelled() -> Dictionary` / `err_failed(reason: String) -> Dictionary`：构造标准错误返回字典。

### 3.3 `WorldBuilder` — 场景 >> 楼层 >> 图层、流式预览与基础实体

> [!NOTE]
> **向后兼容**：若导入流程不调用任何场景方法，`has_scenes_configured()` 保持 `false`，不会写入 `entries["scene_box"]`，既有 `add_floor` / `add_layer` 行为 100% 兼容 `v1.2.0`（宿主载入时自动将全部楼层绑定至默认 `"主场景"`）。一旦调用 `configure_entry_scene()` 或 `add_scene()`，`add_floor()` 会自动挂入当前活动场景，`set_active_floor()` 亦会自动同步 `host_active_scene_uid`。

#### 多场景管理（`SceneRepository`，上限 `MAX_SCENES = 64`）
- `has_scenes_configured() -> bool`：检查当前世界是否已初始化多场景分区目录。
- `configure_entry_scene(scene_name = "主场景", initial_floor_name = "", cover_asset = "") -> String`：将 `empty_world()` 初始楼层绑定为入口场景（`entry_scene_uid`），可选同步重命名默认楼层并设置场景封面。
- `add_scene(scene_name, initial_floor_name = "1F", floor_color = Color(0.32, 0.56, 0.44), cover_asset = "", make_active = true) -> String`：新建独立场景并自动分配专属初始楼层及默认 `map`/`entity`/`obstacle` 三图层，返回 32 位 `scene_uid`（超过 `64` 上限返回 `""` 并告警）。
- `set_active_scene(scene_uid, floor_uid = "", mark_host_visited = true) -> bool`：同时切换 `host_active_scene_uid` 与 `catalog.active_floor_uid`（未指定 `floor_uid` 时使用目标场景的 `default_floor_uid`），确保存档恢复一致性。
- `set_entry_scene(scene_uid: String) -> bool` / `rename_scene(scene_uid: String, new_name: String) -> bool`：切换新玩家默认进入的场景或重命名场景。
- `set_scene_cover_asset(scene_uid: String, cover_asset: String) -> bool`：设置场景封面缩略图（仅接受 `""` 或已归档的 64 位小写 hex `asset://<sha256>.(png|jpg|jpeg|webp|bmp)`）。
- `set_scene_host_view(scene_uid, camera_pos_src, camera_zoom = Vector2.ONE, active_floor_uid = "") -> bool`：记录主持在该场景下的初始视角（自动换算为世界坐标）。
- `add_floor_to_scene(scene_uid, floor_name, color = Color(0.28, 0.65, 0.40), make_default = false, make_active = false) -> String`：向指定场景追加楼层。
- `set_scene_default_floor(scene_uid: String, floor_uid: String) -> bool` / `move_floor_to_scene(floor_uid: String, target_scene_uid: String, make_default = false) -> bool`：设置场景默认楼层或跨场景迁移楼层（若源场景仅剩 `<= 1` 个楼层则拒绝移动，防止出现空场景）。
- `get_entry_scene_uid() -> String` / `get_active_scene_uid() -> String` / `get_scene_uids() -> Array[String]` / `get_scene_floor_uids(scene_uid = "") -> Array[String]` / `get_scene_default_floor_uid(scene_uid = "") -> String` / `get_scene_for_floor(floor_uid = "") -> String`。
- `get_scene_layer_uid(scene_uid: String, kind: String, floor_uid: String = "") -> String` / `get_floor_layers(floor_uid: String = "") -> Array`：实现完整的 **`场景 >> 楼层 >> 图层`** 逐级查询与实体列表检索。

#### 世界与多楼层 / 4 类图层
- `setup(session: ImportSession, source_units_per_cell: float = 150.0) -> Dictionary`：初始化空白世界并校验图层契约（同时重置内置 `_entity_by_id` `O(1)` 实体索引与 `_layer_to_floor` 映射；若已在 `create_world_builder(session, units)` 中传入 `session`，重复调用不会二次触发 `empty_world()`）。
- `add_floor(name: String, color: Color = Color(0.28, 0.65, 0.40), activate: bool = false) -> String`：新增楼层并自动创建默认 `map` / `entity` / `obstacle` 三层（默认 `locked: false`），返回 32 位 `floor_uid`；若已启用多场景，自动归入当前活动场景或入口场景。
- `set_active_floor(floor_uid: String) -> bool`：切换世界活动楼层与构建器当前写入楼层；若已启用多场景，自动同步 `host_active_scene_uid`。
- `rename_floor(floor_uid: String, new_name: String) -> bool`：安全重命名已有楼层（典型场景：将 `empty_world()` 预建的 `"1F"` Floor 0 重命名为导入首张场景名），同步更新 `catalog.floors` 及 `catalog.layers.floors`（若存在 `name` 键）。
- `add_layer(name: String, kind: String = "entity", access: String = "all", floor_uid: String = "", viewers: Array = [], locked: bool = false, visible: bool = true, persistent: bool = true) -> String`：新增自定义图层（支持 `"map" | "entity" | "obstacle" | "area"` 与 `"all" | "host" | "players"` 权限策略），返回 32 位 `layer_uid`。
- `get_active_floor_uid() -> String` / `get_layer_uid(kind: String, floor_uid: String = "") -> String` / `get_source_to_world_scale() -> float` / `to_world_pos(pos_src: Vector2) -> Vector2`。

#### 流式预览与基础实体 / 场景盒子（`CompSceneBox`）
- `begin_bounds_preview(total_items: int, source_bounds: Rect2) -> void` / `finish_geometry_preview() -> bool`：控制宿主两阶段几何与实体流式预览。
- `add_map_tile(...) -> String`：向 `map` 图层添加底图贴图并返回 32 位实体 ID。
- `add_token(...) -> String`：向 `entity` 图层添加可点选角色棋子（`entity_type = "unit"`，支持可选 `footprint_radius`、`locked`、`permission_state`）。
- `add_object_sprite(...) -> String`：向 `entity` 图层添加普通道具贴图（`entity_type = "object"`）。
- `add_text_note(...) -> String` / `add_vector_drawing(...) -> String`：向 `entity` 图层添加矢量文字标签或自由矢量笔迹。
- `add_text_pin(source_id, text, center_src, name = "", keep_screen_size = true, size_src = Vector2(48.0, 60.0), hidden = false, layer_uid_override = "") -> String`：创建挂载 `comp_entity_note.gd`（`is_pin: true`）的世界文本图钉。
- `add_scene_box(source_id, name, center_src, target_scene_uid, side_cells = 1.5, cover_asset = "", preview_policy = "visited_unlock", all_players_can_enter = true, owner_player_ids = [], hidden_from_players = false, locked = false, layer_uid_override = "", parked = false, manual = false) -> String`：放置标准场景盒子实体（`entity_type = "object"`、`selectable_in_select_mode = false`、正方形边长钳位 `[72.0, 256.0]` 默认 `96.0`、`xform.scale = Vector2.ONE`、`comp_visual` + `comp_permission` + `comp_scene_box` 同步配置；`manual = true` 必须配合 `parked = true` 使用）。
- `attach_scene_box(entity_id, target_scene_uid, cover_asset = "", preview_policy = "visited_unlock", all_players_can_enter = true, owner_player_ids = [], parked = false, manual = false) -> bool`：将已有非地图/非冲突实体升级为场景盒子（自动方正化尺寸与重置单位缩放；`manual = true` 必须配合 `parked = true` 使用）。

### 3.4 `WorldBuilder` — 障碍物、组件、光照、网格与模块预算

#### 5 类原生多边形障碍物与 2 点线段自动挤出（导入落盘时由宿主自动烘焙 `comp_obstacle.gd`）
- `add_polygon_obstacle(source_id, name, center_src, polygons_src, kind = "wall", is_open_door = false, enabled = true, layer_uid_override = "") -> String`：通用多边形障碍物接口，支持 `{outer, holes}` 带孔面与原始环数组；自动过滤 `< 3` 点退化环并告警，带孔面自动裁剪扣洞后三角剖分。
- `add_wall(...) -> String` / `add_door(..., is_open = false) -> String` / `add_window(..., is_open = false) -> String` / `add_glass_wall(...) -> String` / `add_air_cutout(...) -> String`：全 5 种多边形障碍物语义快捷方法。
- `extrude_segment_to_quad(p0: Vector2, p1: Vector2, half_width: float = 6.0, min_length: float = 0.5) -> PackedVector2Array`：将 2 点线段按法线挤出为 4 顶点闭合矩形，内置有限数检查、`half_width >= 0.5` 与 `min_length` 钳位及鞋带面积校验（防御大坐标坍缩）。
- `add_segment_obstacle(source_id, name, p0_src, p1_src, half_width_src = 6.0, kind = "wall", is_open_door = false, enabled = true, layer_uid_override = "") -> String`：面向外部 VTT（如 FVTT）2 点线段墙体的专用入口——**先将 `p0_src`/`p1_src` 平移至相对 `center_src` 的局部坐标再执行挤出**，彻底避免 `1e7` 量级大坐标下 `float32` ULP 精度坍塌导致 `FobrWallKernel.AuthorReadPaths` 拒收；另提供快捷方法 `add_segment_wall(...)`、`add_segment_door(..., is_open = false)`、`add_segment_window(..., is_open = false)`、`add_segment_glass_wall(...)`。

#### 可选组件挂载、停放组件（`parked`/`manual`）、透明点光源、全局网格与模块配额校验
- `attach_component(entity_id: String, script_path: String, state: Dictionary = {}, parked: bool = false, manual: bool = false) -> bool`：基于内置 `_entity_by_id` **`O(1)` 哈希索引**（未命中时回退倒序扫描）定位实体，在数千实体大世界中高效追加可选组件至索引 `>= 2`（拒绝覆写 `[visual, permission]` 核心前缀）。当 `parked == true` 时可选携带 `manual: bool`（注意宿主 `board_token.gd:331-368` 规定 `manual` 仅允许在 `parked == true` 时出现，若 `parked == false` 则不写 `manual`）。
- `attach_parked_component(entity_id: String, script_path: String, state: Dictionary = {}, manual: bool = false) -> bool`：显式以停放态（`"parked": true`）写入可选/未启用组件，确保宿主 `EntityStateCodec` 与 `BoardToken` 完整保留并在目标模块启用时自动恢复。
- `attach_unit_marker(entity_id: String) -> bool`：挂载 `comp_unit.gd`（`{"schema_version": 1}`）。
- `attach_portal(entity_id: String, pair_key: String) -> bool`：挂载 `comp_portal.gd`（自动将非 32-hex 文本归一为 32 位小写十六进制 `pair_key`）。
- `attach_simple_vision(entity_id, radius = 640.0, view_angle_deg = 360.0, requires_light = false, enabled = true) -> bool`：挂载简易迷雾视野 `comp_simple_vision.gd`（`radius` 为 Fu VTT 世界单位）。
- `attach_simple_light(entity_id, radius = 640.0, view_angle_deg = 360.0, enabled = true) -> bool`：挂载简易迷雾光源 `comp_simple_light.gd`。
- `suppress_entity_fallback_box(entity_id: String) -> bool`：将实体的 `entity.fallback_color` 与 `components[0].state.fallback_color` 设为全透明 `Color(1, 1, 1, 0)` 并置 `show_fallback = false`，隐藏无贴图锚点的默认灰色占位方块。
- `add_point_light(source_id, center_src, radius_world, view_angle_deg = 360.0, name = "Light", hidden = false, enabled = true, size_src = Vector2(32.0, 32.0), layer_uid_override = "") -> String`：一步创建不可见纯光源锚点实体（自动抑制占位方块并挂载 `comp_simple_light.gd`）。
- `configure_grid_alignment(cell_size = 64.0, snap_enabled = true, offset = Vector2.ZERO, color = Color(0.5, 0.55, 0.65, 0.7), line_width = 1.0, snap_strength = 0.1) -> bool`：向 `world.modules.entries["grid_alignment"]`（`version = 1`）写入精确 8 键 `fus.grid_alignment.config` v1 状态。
- `set_module_state(module_id: String, version: int, state: Dictionary) -> bool`：向 `world.modules`（`version = 2`）写入受配额保护的模块纯数据（单条 `<= 16 MiB`、总限 `<= 24 MiB`，同时核验 `bounded_variant_size_estimate` 与 `var_to_bytes`）。
- `sanitize_module_data(value: Variant) -> Variant`：递归清洗模块数据（剔除 `NaN`/`Inf` 置 `0.0`、超出 32 层或非纯数据对象置 `null`、`StringName`/`NodePath` 转 `String`）。
- `can_fit_module_state(module_id: String, version: int, state: Dictionary, max_world_bytes: int = 30 * 1024 * 1024) -> bool`：预检模块写入是否同时满足单条 `<= 16 MiB`、模块区总量 `<= 24 MiB` 与整份世界 `<= max_world_bytes`（默认 `30 MiB`）上限，便于插件实施渐进裁剪。
- `build_result(source_record_count: int = 0, merged_wall_count: int = 0) -> Dictionary`：输出最终 `prepare_import` 返回字典。

### 3.5 可复用子模块库 (`fu_sdk/modules/`)

`packager.py` 在构建插件时会自动把 `shared/sdk/fu_sdk/modules/` 内全部 `.gd` 随主门面一并拷贝至归档内的 `lib/fu_sdk/modules/`。各子模块均遵循 `extends RefCounted`、零 `preload()`、零 `class_name` 约束，推荐直接通过 `FuSdk` 实例工厂创建：

#### 1. `modules/asset_publisher.gd` (`sdk.create_asset_publisher()`)
通用图片魔数/头部预检、格式转码与 `SharedAssetStore.Publish` 发布器：
- **核心能力**：在调用 Godot `Image.load_*_from_buffer()` 前完成 PNG/JPG/WebP/BMP/安全 SVG（含 XML 炸弹防护）预检，强制拦截 `.gif` 与损坏流，避免 C++ `ERROR:` 日志；自动将 `.bmp`/`.svg` 转为 `.png`；支持 `WorkerThreadPool` 并发预检（`prevalidate_local_refs`）、四门控实机发布（自动检测 `MockHostBridge` 回退 `asset://<sha256>.<ext>`）与取消回滚（`rollback_published_files`）。
- **主要方法**：`validate_and_prepare_image_bytes(raw_bytes, ext_hint = "")`、`publish_bytes(raw_bytes, ext_hint, host, session = null, cache_key = "")`、`publish_from_source(rel_path, source, host, session = null)`、`resolve_sprite_ref(ref_str, ref_info, source, host, session, options = {})`、`rollback_published_files()`、`get_published_files()`、`get_published_count()`。

```gdscript
var publisher: RefCounted = sdk.create_asset_publisher()
var pub_res: Dictionary = publisher.publish_from_source("scenes/map.webp", pkg, host, session)
if bool(pub_res.get("ok", false)):
	builder.add_map_tile("map_1", "主地图", center_src, size_src, str(pub_res["sprite_path"]))
# 若中途取消或失败：publisher.rollback_published_files()
```

#### 2. `modules/entity_library_writer.gd` (`sdk.create_entity_library_writer()`)
通用全局素材库（`<root>/entity-library/`）写入器：
- **核心能力**：内置严格四门控检测（`can_write_library(host)` 校验 `SharedAssetStore.cs` 及 `<root>/sessions/..._<32hex>`），自动构建无环目录树、调用 `AdoptLibraryAsset` + `ShareLibraryAsset` 物化缩略图、链式传递 `.revision` 幂等写入 `folder`/`unit`/`preset` 记录，并在中途取消或失败时原子回滚（`rollback_last_registration()`）。注意当导入器需适配默认未启用可选模块的场景时，可在条目中设置 `"create_preset": false` 以注册纯 `kind = "unit"` 记录（或仅保留核心组件）。
- **主要方法**：`set_shared_asset_store(store, allow_mock = false)`、`can_write_library(host)`、`register_entries(namespace_id, entries, host, session = null, enabled = true)`、`rollback_last_registration()`。

```gdscript
var lib_writer: RefCounted = sdk.create_entity_library_writer()
var lib_res: Dictionary = lib_writer.register_entries("my_importer", [
	{
		"id": "goblin_01",
		"name": "哥布林斥候",
		"folder_name": "怪物/类人生物",
		"sprite_ref": token_sprite_ref,
		"size_world": Vector2(64.0, 64.0),
		"create_preset": false,
	}
], host, session, session.get_bool_option("register_entity_library", true))
```

#### 3. `modules/package_source.gd` (`sdk.create_package_source()`)
通用双输入源（`.zip` 归档与解压目录清单 `.json`）虚拟包读取器：
- **核心能力**：统一抽象 `.zip` 压缩包（支持深度 0/1 清单探测、过滤 `__MACOSX`/`.DS_Store`/`._*` 垃圾项、大小写不敏感索引与纯 GDScript raw DEFLATE/CRC32 严校验）与已解压目录，提供安全的 UTF-8 BOM 剥离文本读取与 URL 百分号解码路径规范化。
- **主要方法**：`open_package(path, manifest_filename = "world.json", required_keys = [])`、`open_world(path)`、`has_file(rel_path)`、`read_bytes(rel_path)`、`read_text(rel_path)`、`list_files(prefix = "")`、`list_subdirs(prefix = "")`、`normalize_rel_path(raw_ref, strip_prefixes = [])`、`get_decoded_bytes_total()`、`close()`。

```gdscript
var pkg: RefCounted = sdk.create_package_source()
var open_res: Dictionary = pkg.open_package(path, "manifest.json", ["name"])
if not bool(open_res.get("ok", false)):
	return session.err_failed(str(open_res.get("reason", "open_failed")))
var manifest: Dictionary = pkg.get_manifest()
var norm_ref: Dictionary = pkg.normalize_rel_path("tokens/Goblin%20Scout.png")
pkg.close()
```

#### 4. `modules/snappy.gd` (`sdk.create_snappy_codec()`)
零外部依赖纯 GDScript Snappy 块解压器（`DEFAULT_MAX_OUTPUT_BYTES = 67108864`，即 `64 MiB`）：
- **核心能力**：完整实现 `varint32` 未压缩长度解码、全 `0..63` Literal 标签与 `1/2/4` 字节偏移拷贝，采用强制逐字节重叠 RLE 自拷贝并拦截截断与超限畸形流（适用于 LevelDB SSTable 等 Snappy 压缩格式解析）。
- **主要方法**：`get_uncompressed_length(src, max_output_bytes = 67108864) -> Dictionary`、`decompress(src, max_output_bytes = 67108864) -> Dictionary`。

```gdscript
var snappy: RefCounted = sdk.create_snappy_codec()
var dec: Dictionary = snappy.decompress(compressed_block)
if bool(dec.get("ok", false)):
	var raw_bytes: PackedByteArray = dec["data"]
```

### 3.6 R3 调试与警告日志 API (`fu_sdk/logging/log_bus.gd`)

`logging/log_bus.gd` 为 Mod 开发者与游戏内控制台日志插件提供统一的结构化日志总线（可通过 `sdk.create_logger(options)`、`session.get_logger()` 或 `builder.get_logger()` 获取）：

- **分级与上限常量**：
  - 级别常量：`LEVEL_DEBUG = 10`、`LEVEL_INFO = 20`、`LEVEL_WARNING = 30`、`LEVEL_ERROR = 40`；
  - 缓冲区与保护常量：`DEFAULT_MAX_ENTRIES = 512`、`HOST_MAX_WARNINGS = 100`、`HOST_MAX_NOTES_CHARS = 7000`、`MAX_CONTEXT_DEPTH = 32`、`MAX_CLONE_BYTES = 4 * 1024 * 1024`（`4 MiB`，委托 `utils/dag_cloner.gd` 执行单条日志上下文深拷贝，区别于适配器与重度插件默认的 `16 MiB` `DEFAULT_MAX_CLONE_BYTES`）。
- **配置与宿主桥接**：
  - `configure(max_entries = 512, min_level = LEVEL_DEBUG, emit_to_engine = true)`、`set_max_entries()` / `get_max_entries()`、`set_min_level()` / `get_min_level()`、`set_emit_to_engine()` / `is_emit_to_engine()`；
  - `attach_import_host(host, forward_reports = false)` / `detach_import_host()` / `get_import_host()` / `has_import_host()` / `get_host_warning_count()` / `get_host_warning_chars()`：将 `WARNING`/`ERROR` 自动去重转发至 `host.warn(...)`（严格遵守宿主 `100` 条与 `7000` 字符截断保护），并在 `forward_reports == true` 时将 `DEBUG`/`INFO` 转发至 `host.report(...)`。
- **写入、查询与订阅接口**：
  - 写入：`debug(source, message, context = {})`、`info(...)`、`warn(...)`、`error(...)`、`log(level, source, message, context = {})` / `log_entry(...)`（返回 `{seq, level, level_name, source, message, context, timestamp_msec}`）；
  - 实时订阅：`subscribe(callback: Callable) -> int`、`unsubscribe(token: int) -> bool`（注意在 `prepare_import` 退出前务必 `unsubscribe`，防止绑定 `Callable` 造成 `RefCounted` 引用残留）；
  - 读取与清理：`get_entries(min_level = 0, since_seq = 0, limit = 0) -> Array`、`get_warnings(since_seq = 0) -> Array`、`clear()`、`size()`、`get_last_seq()`。
- **安全回放 `ERROR` 日志模式**：当需要向 `LogBus` 记录或回放历史 `ERROR` 日志而不触发 Godot C++ 引擎 `push_error()`（否则无头 `verify-host` 会判为失败）时，可先调用 `logger.set_emit_to_engine(false)` 再写入，完成后恢复原值。

```gdscript
var logger: RefCounted = session.get_logger()
var collected: Array[Dictionary] = []
var token: int = logger.subscribe(func(entry: Dictionary) -> void:
	collected.append(entry)
)
logger.debug("importer", "开始解析场景", {"floor": "1F"})
logger.warn("importer", "跳过空路径图元")
var warnings_only: Array = logger.get_warnings()
logger.unsubscribe(token)
```

### 3.7 R2 原生插件注册表与 23 个分脚本 SDK (`plugins/module_registry.gd` & `plugins/*.gd`)

#### 1. `ModuleRegistry` 与 `WorldBuilder` R2 控制接口
`plugins/module_registry.gd` 收录 `<FUS_REPO_DIR>/scenes/extension/desktop_feature_catalog.gd` 的全部 **30 个目录模块（9 核心 + 21 可选）** 与 **3 个非目录候选模块**（共 **33** 项），并标记 Steam Playtest `v0.0.61`–`v0.0.62` 临时禁用的模块（`campaign_time`、`dnd_opportunity`）：

- **9 个核心模块（`status = "core"`，默认启用）**：`feature_networking`、`feature_component_sync`、`feature_edit_mode`、`feature_floor_system`、`feature_layer_stack`、`feature_obstacle_authoring`、`feature_debug_hooks`、`feature_component_library`、`feature_entity_library`（其中 `networking`、`component_sync`、`debug_hooks`、`component_library` 为纯元数据注册无单独写入脚本）。
- **21 个可选模块（默认 `status = "disabled"`，需在桌面/构建器显式启用）**：`campaign_time`（`playtest_blocked`）、`image_flip`、`drag_movement`、`drawing`、`areas`、`room_chat`、`checklist`、`player_cursors`、`resource_pool`、`map_fog_editor`、`grid_alignment`、`detached_sidebar`、`character_roster`、`portal`、`backpack`、`dnd_opportunity`（`playtest_blocked`）、`follow`、`simple_fog`、`dice`、`candidate_initiative`、`scene_box`（其中 `room_chat`、`player_cursors`、`map_fog_editor`、`detached_sidebar` 为无 Mod 持久化状态模块）。
- **3 个非目录候选模块（`status = "uncatalogued_candidate"`）**：`entity_notes`（提供独立 SDK，在 `v0.0.60` 客户端载入时由 `EntityStateCodec` 自动停放）、`music_board`、`module_example`（别名 `feature_module_example`）。
- **`WorldBuilder` 启用控制与策略方法**：
  - `get_module_registry() -> RefCounted`、`set_enabled_modules(ids: Array)`、`set_module_enabled(module_id, enabled)`、`is_module_enabled(module_id) -> bool`；
  - `set_disabled_module_policy(policy: String) -> bool` / `get_disabled_module_policy() -> String`：
    - `"preserve"`（默认，对齐 `<FUS_REPO_DIR>` `WorldModuleState` 与 `FeatureManager` 不透明留存及 `EntityStateCodec` `_parked` 自动恢复）：调用未启用/被禁用/候选模块 SDK 写入时，通过 `LogBus`（及 `ImportSession.add_warning` + `push_warning`）输出包含 `MODULE_ID`、状态与策略的清晰警告，并照常写入合规数据（对未入目录组件按需自动停放）；
    - `"skip"`：同样输出清晰警告，并立即跳过写入，返回 `{"ok": false, "skipped": true, "status": "<status>", "reason": "module_disabled:<id>"}`（包括 `playtest_blocked` 模块在内，均返回 `reason: "module_disabled:<id>"`，并在 `status` 与警告信息中标明 `"playtest_blocked"`，不会返回 `"module_playtest_blocked:<id>"`）。
  - `probe_feature_manager(feature_manager)`：运行时可选探测宿主 `FeatureManager` 状态；
  - `get_plugin_sdk(module_id: String) -> RefCounted`：统一工厂获取对应分脚本实例并自动调用 `inst.configure(self, _module_registry, _log_bus)` 注入 `WorldBuilder`、`ModuleRegistry` 与 `LogBus`（全部 `23` 个分脚本——含 `5` 个核心基础模块与 `18` 个可选及候选插件分脚本——均在 `configure()` 内部将 `WorldBuilder` 封装为 `WeakRef`（`_world_builder_ref` + `_wb()`），确保零 `RefCounted` 循环引用及 `ObjectDB` 增量 `0.0`）。

#### 2. 23 个独立分脚本原生插件 SDK 清单（`shared/sdk/fu_sdk/plugins/*.gd`）

| 分组 | 脚本文件 (`plugins/...`) | `WorldBuilder` 快捷入口 | 核心能力与 `<FUS_REPO_DIR>` 对应契约 |
| :--- | :--- | :--- | :--- |
| **Core (5)** | `plugins/feature_edit_mode.gd` | `builder.edit_mode()` | `comp_unit.gd` 单位标记、`is_unit`、`set_entity_flags`/`permissions`/`footprint_radius` |
| **Core** | `plugins/feature_floor_system.gd` | `builder.floor_system()` | `add_floor`、`rename_floor`、`set_active_floor`、`set_floor_color`、`reorder_floor`、`player_floor_visits` |
| **Core** | `plugins/feature_layer_stack.gd` | `builder.layer_stack()` | `fus.floor_layers.v2`：`add_layer`、`set_layer_visibility`/`locked`/`access`、`default_layer`、`editor_view` |
| **Core** | `plugins/feature_obstacle_authoring.gd` | `builder.obstacle_authoring()` | 5 类多边形障碍物、2 点线段挤出、`comp_obstacle.gd` 与形状校验 |
| **Core** | `plugins/feature_entity_library.gd` | `builder.entity_library()` | `EntityLibraryWriter` 封装、`register_entries` / `register_presets`（含未启用模块 preset 警告）与回滚 |
| **World (9)** | `plugins/scene_box.gd` | `builder.scene_box()` | `world.modules.entries["scene_box"]` v2（`MAX_SCENES = 64`）、`comp_scene_box.gd` 与 14 项冲突校验 |
| **World** | `plugins/portal.gd` | `builder.portal()` | `comp_portal.gd` 成对传送门（`pair_key` 32-hex 归一，`areas` 依赖告警） |
| **World** | `plugins/grid_alignment.gd` | `builder.grid_alignment()` | `fus.grid_alignment.config` v1（`line_width ∈ [0.5, 4.0]`、`offset ∈ [-1e6, 1e6]`、`cell_size ∈ [8, 4096]`；支持 `configure_grid` 与字典态 `configure_grid_alignment` / `set_config`） |
| **World** | `plugins/simple_fog.gd` | `builder.simple_fog()` | `fog_config.gd` v2（14 键、`EFFECT_IDS`、`SHADOW_FILTERS`，`coerce_inputs=true` 自动将 JSON 整数浮点归一为 `int`）、`"SFH2"` `exploration` 历史字节、`comp_simple_vision`/`light` |
| **World** | `plugins/image_flip.gd` | `builder.image_flip()` | `comp_image_flip.gd` 水平/垂直翻转（支持 `set_flip`、`attach_flip` 与字典/位置双态 `attach_image_flip` / `set_image_flip`）+ 与 `obstacle`/`area`/`scene_box` 双向冲突检查 |
| **World** | `plugins/drag_movement.gd` | `builder.drag_movement()` | `world.modules.entries["drag_movement"]` v2（`DEFAULT_SPEED = 64.0`；支持 `configure_default_speed` 与字典态 `configure_drag_movement`）+ `comp_drag_speed.gd` |
| **World** | `plugins/drawing.gd` | `builder.drawing()` | `world.modules.entries["drawing"]` v1（含 `v0.0.61` `text_ink.gd` `sans`/`zhuokai`、`12..256` px、`Transform2D` `affine`；支持 `configure_world_drawing` 与字典态 `configure_drawing`）+ `comp_entity_ink.gd`（`attach_entity_ink` / `set_entity_ink` 支持 `Array` 或状态 `Dictionary`） |
| **World** | `plugins/areas.gd` | `builder.areas()` | `comp_area.gd`（`fus.area.v1`、`MAX_RADIUS_IN_CELLS = 256.0`）+ 与 `image_flip`/`scene_box` 冲突校验 |
| **World (Cand)** | `plugins/entity_notes.gd` | `builder.entity_notes()` | `comp_entity_note.gd`（`MAX_TEXT_LENGTH = 32768`、图钉 `is_pin`；支持 `attach_note` 与字典/文本双态 `attach_entity_note`；`v0.0.60` `uncatalogued_candidate` 自动停放） |
| **Gameplay (9)** | `plugins/checklist.gd` | `builder.checklist()` | `world.modules.entries["checklist"]` schema 2（`MAX_ROWS = 128`、13 `RULE_EVENTS` 宏校验；**`^mod:` 来源标签默认 `allow_mod_source=true` 时放行并输出 `LogBus` 兼容性警告**，`allow_mod_source=false` 严格对齐实机宿主 `<FUS_REPO_DIR>/modules/checklist/book.gd` / `rule.gd` 仅认 `""` 或合法 `on <event>:` 宏，且 `Book.restore()` 会拒绝 `"mod:..."`） |
| **Gameplay** | `plugins/resource_pool.gd` | `builder.resource_pool()` | `world.modules.entries["resource_pool"]` v1 定义 + `comp_resource_pool.gd` |
| **Gameplay** | `plugins/character_roster.gd` | `builder.character_roster()` | `world.modules.entries["character_roster"]` v1 + `comp_character_roster_member.gd`（仅活体 `unit` 非 `map`） |
| **Gameplay** | `plugins/backpack.gd` | `builder.backpack()` | `comp_backpack.gd`（16 槽位 `"0".."15"`、`MAX_STACK = 999`、`MAX_ITEM_BYTES = 8192`、仅限 `unit`） |
| **Gameplay** | `plugins/follow.gd` | `builder.follow()` | `comp_follow.gd`（自动检测自跟随与循环跟随链） |
| **Gameplay** | `plugins/candidate_initiative.gd` | `builder.candidate_initiative()` | `world.modules.entries["candidate_initiative"]` schema 2 + `comp_initiative.gd` |
| **Gameplay** | `plugins/dice.gd` | `builder.dice()` | `world.modules.entries["dice"]` schema 5 + `dice_workspace` v4（`royal_ember_resin`/`godot_blue_cat_eye`、`adv`/`dis`/`burst` 表达式校验） |
| **Blocked** | `plugins/campaign_time.gd` | `builder.campaign_time()` | `world.modules.entries["campaign_time"]` v1（`MAX_MINUTE = 1e8`、`playtest_blocked` 告警与状态保留） |
| **Blocked** | `plugins/dnd_opportunity.gd` | `builder.dnd_opportunity()` | `world.modules.entries["dnd_opportunity"]` v1（`2014`/`2024` 版规则卡、`playtest_blocked` 告警与状态保留） |

### 3.8 公共叶子工具集 (`fu_sdk/utils/`)

> [!NOTE]
> **叶子隔离与实例级缓存约束**  
> `fu_sdk/utils/*.gd` 下全部 **4** 个脚本均受严格叶子约束：`extends RefCounted`、零 `class_name`、零 `preload()`、零 `load()`，仅提供无状态 `static func` 与轻量上下文内部类。各调用方（`v1.gd`、`adapters/`、`logging/`、`plugins/`）须通过各自实例上的 `_util_scripts: Dictionary = {}` 与 `_load_util_script(...)` 按相对路径按需加载并缓存 `Script` 句柄（绝不缓存反向 `RefCounted` 实例），而 `fu_sdk/modules/*.gd` 因自包含隔离要求保持零跨脚本 `load()`。

#### 1. `utils/dag_cloner.gd`（重度 DAG 有界深拷贝与防抖记忆化）
收敛 `host_v1_adapter.gd`、`log_bus.gd`、`module_registry.gd`、`feature_entity_library.gd`、`feature_obstacle_authoring.gd` 与 `v1.gd` 的重度有界 DAG 遍历、循环引用截断、深度折叠与防抖缓存：
- **内部类**：`DagMemoEntry`、`DagMemoBucket`、`DagTravCtx`（含 `mode: String = ""`、`nodes`、`max_nodes`、`bytes`、`max_bytes`、`max_depth`、`aborted`、`depth_clipped`、`cycle_clipped`、`limit_exceeded`）。
- **核心常量**：`MAX_CLONE_VISITS = 2097152`、`MAX_ESTIMATE_VISITS = 2097152`、`DEFAULT_MAX_CLONE_BYTES = 16 * 1024 * 1024`（`16 MiB`）、`LOG_BUS_MAX_CLONE_BYTES = 4 * 1024 * 1024`（`4 MiB`）、`DEFAULT_MAX_DEPTH = 32`、`MAX_DAG_MEMO_ENTRIES = 32`、`MAX_DAG_MEMO_HEAVY = 20`、`DAG_MEMO_RING_CAP = 12`、`DAG_MEMO_GHOST_CAP = 128`、`DAG_MEMO_GHOST_PROB_CAP = 128`、`DAG_MEMO_AGE_STEP = 256`、`DAG_MEMO_AGE_SHIFT = 8`、`DAG_MEMO_MIN_LOGICAL_NODES = 16`、`DAG_MEMO_MIN_HEIGHT = 1`、`MAX_DAG_LOGICAL_NODES_CLAMP = 1073741824`、`MAX_CLONE_SHARED_SUBTREE = 4096`、`MAX_CLONE_SHARED_UNFOLD = 8192`。
- **公共静态入口**：
  - `safe_clone_variant(value: Variant, depth: int = 0, active_stack: Array = [], visit_budget: Array = [], max_bytes: int = DEFAULT_MAX_CLONE_BYTES, max_depth: int = DEFAULT_MAX_DEPTH) -> Variant`
  - `safe_clone_node(value: Variant, depth: int, active_stack: Array, tctx: DagTravCtx) -> Variant`
  - `safe_clone_dict(raw: Dictionary, max_bytes: int = DEFAULT_MAX_CLONE_BYTES, max_depth: int = DEFAULT_MAX_DEPTH) -> Dictionary`
  - `safe_clone_validated_dict(raw: Dictionary, max_bytes: int = DEFAULT_MAX_CLONE_BYTES, initial_depth: int = 0, max_depth: int = DEFAULT_MAX_DEPTH) -> Dictionary`
  - `is_in_active_stack(target: Variant, active_stack: Array) -> bool`、`packed_array_byte_cost(value: Variant, max_allowed: int = -1) -> int`
  - 记忆化桶操作：`memo_find(tctx: DagTravCtx, is_dict: bool, sz: int, target: Variant) -> DagMemoEntry`、`memo_find_in_buckets(tctx: DagTravCtx, buckets: Dictionary, bucket_key: int, target: Variant) -> DagMemoEntry`、`memo_store(tctx: DagTravCtx, is_dict: bool, sz: int, target: Variant, height: int, size_val: int, ln: int, cloned_val: Variant = null, work_nodes: int = 1) -> void`、`memo_store_in_buckets(tctx: DagTravCtx, buckets: Dictionary, bucket_key: int, target: Variant, height: int, size_val: int, ln: int, cloned_val: Variant = null, work_nodes: int = 1) -> void`、`memo_age_entry(b: DagMemoBucket, cur: DagMemoEntry) -> void`、`memo_promote_ring_entry(tctx: DagTravCtx, b: DagMemoBucket, r_idx: int, e: DagMemoEntry) -> void`、`memo_push_ghost(b: DagMemoBucket, target_ref: Variant, height: int, hits: int = 0, work_nodes: int = 1) -> void`、`memo_push_ghost_prob(b: DagMemoBucket, target_ref: Variant, height: int, hits: int) -> void`、`memo_pop_matching_ghost(b: DagMemoBucket, target: Variant, height: int) -> int`、`memo_replace_ghost_at(b: DagMemoBucket, g_idx: int, target_ref: Variant, height: int, safe_hits: int, safe_work: int) -> void`、`memo_remove_ghost_at(b: DagMemoBucket, g_idx: int) -> void`、`memo_remove_ghost_prob_at(b: DagMemoBucket, p_idx: int) -> void`。
- **预算差异**：`log_bus.gd` 显式传入 `MAX_CLONE_BYTES = 4 * 1024 * 1024`（`4 MiB`）；`host_v1_adapter.gd`、`module_registry.gd`、`feature_entity_library.gd`、`feature_obstacle_authoring.gd` 与 `v1.gd` 保留 `16 MiB` 默认上限。

#### 2. `utils/bounded_cloner.gd`（轻量有界深拷贝、环检测与迷雾配置克隆）
收敛各分插件的 4 类轻量深拷贝与环检测策略，保持既有预算与错误语义：
- **内部类**：`FallbackCloneCtx`、`DndTravCtx`。
- **核心常量**：`MAX_DEPTH = 32`、`DEFAULT_SIMPLE_BUDGET = 4096`、`DEFAULT_FALLBACK_BUDGET = 16384`、`DRAWING_FALLBACK_BUDGET = 2097152`、`DEFAULT_DND_VISITS = 262144`、`DEFAULT_SHARED_UNFOLD = 8192`、`MEMO_BUCKET_CAP = 64`。
- **公共静态入口与行为差异**：
  - **FallbackClone（64 槽环形记忆化 + 跳过非标量键 + 复制 `Packed*Array`）**：`safe_clone_via_adapter(value: Variant, adapter: RefCounted = null, default_budget: int = DEFAULT_FALLBACK_BUDGET) -> Variant`、`bounded_fallback_clone(value: Variant, depth: int = 0, active_stack: Array = [], budget: Array = [], default_budget: int = DEFAULT_FALLBACK_BUDGET, max_shared_unfold: int = DEFAULT_SHARED_UNFOLD) -> Variant`、`bounded_fallback_clone_node(value: Variant, depth: int, active_stack: Array, budget: Array, ctx: FallbackCloneCtx, in_unfold: bool) -> Variant`、`memo_get_int(buckets: Dictionary, key: int, target: Variant) -> int`、`memo_put_int(buckets: Dictionary, key: int, target: Variant, val: int, bucket_cap: int = MEMO_BUCKET_CAP) -> void`。其中 `drawing.gd` 传入 `DRAWING_FALLBACK_BUDGET`（`2097152`），`feature_floor_system.gd` 与 `feature_layer_stack.gd` 传入 `DEFAULT_FALLBACK_BUDGET`（`16384`）。
  - **无记忆化轻量克隆**：`simple_clone_dict(d: Dictionary, depth: int = 0, stack: Array = [], budget: Array = [], duplicate_packed: bool = false) -> Dictionary`、`simple_clone_array(arr: Array, depth: int = 0, stack: Array = [], budget: Array = [], duplicate_packed: bool = false) -> Array`、`simple_clone_var(v: Variant, depth: int = 0, stack: Array = [], budget: Array = [], duplicate_packed: bool = false) -> Variant`。**刻意不启用记忆化**，以在 `[4096, false]` / `[16384, false]` / `[32768, false]`（如 `checklist.gd` 与 `backpack.gd` 使用 `[32768, false]`）下保留指数共享 DAG 预算耗尽检测（置 `budget[1] = true`），并在 `depth >= 32` 或中止前直接 `break`，严格保持**零 `null` 合成**语义（`duplicate_packed` 默认为 `false`）。
  - **DnD 环检测与容器键克隆**：`has_cycle(v: Variant, depth: int = 0, stack: Array = [], budget: Array = [], max_visits: int = DEFAULT_DND_VISITS) -> bool`、`cycle_check_height(v: Variant, depth: int, stack: Array, tctx: DndTravCtx) -> int`、`dnd_clone_dict(d: Dictionary, depth: int = 0, stack: Array = [], budget: Array = [], max_visits: int = DEFAULT_DND_VISITS, max_shared_unfold: int = DEFAULT_SHARED_UNFOLD) -> Dictionary`、`dnd_clone_var(v: Variant, depth: int = 0, stack: Array = [], budget: Array = [], max_visits: int = DEFAULT_DND_VISITS, max_shared_unfold: int = DEFAULT_SHARED_UNFOLD) -> Variant`、`dnd_clone_node(v: Variant, depth: int, stack: Array, active_budget: Array, tctx: DndTravCtx, in_unfold: bool) -> Variant`（支持字典中的嵌套容器键与 `Packed*Array.duplicate()`）。
  - **迷雾覆盖克隆**：`clone_fog_overrides(value: Variant, depth: int = 0, stack: Array = [], budget: Array = []) -> Dictionary`（用于 `simple_fog.gd`，强制要求字典键为 `String`，出错时返回 `{"ok": false, "reason": ...}`：`fog_config_too_deep`、`fog_config_too_large`、`invalid_fog_config_cycle`、`unknown_fog_config_key_type`）。

#### 3. `utils/value_utils.gd`（基础强转、64 位整型解析与颜色规整）
- **常量**：`MAX_SAFE_FLOAT_INT: float = 9007199254740991.0`、`MIN_SAFE_FLOAT_INT: float = -9007199254740991.0`。
- **公共静态入口与参数化标志**：
  - `parse_int_val(v: Variant) -> Dictionary`：仅接受 `int` 或 JS 安全整数区间内有限整数值 `float`，拒绝 `String` 与 `bool`。
  - `parse_int64_str(s: String) -> Variant`：精确解析 64 位有符号整数字符串，溢出时返回 `null`。
  - `coerce_bool(value: Variant, fallback: bool = false, strip_bom: bool = true) -> bool`：默认剥离头部 BOM 与首尾空白；`checklist.gd` 行构造显式传入 `strip_bom = false`。
  - `coerce_int(value: Variant, fallback: int = 0, strict_int64: bool = true) -> int`：默认启用 BOM 清理、64 位溢出拒收与浮点范围保护；`checklist.gd` 行构造显式传入 `strict_int64 = false`。
  - `coerce_float(value: Variant, fallback: float = 0.0, require_finite: bool = true) -> float`：默认拒绝 `NaN`/`Inf` 并回退 `fallback`；`resource_pool.gd` 显式传入 `require_finite = false`，保留非有限浮点数交由下游校验显式拒收。
  - `coerce_string(value: Variant, fallback: String = "") -> String`（严格 `TYPE_STRING`）、`as_str(value: Variant, fallback: String = "") -> String`（兼容 `String` / `StringName`）、`coerce_str_scalar(value: Variant, fallback: String = "") -> String`（兼容 `String` / `StringName` / `NodePath` / `bool` / `int` / `float`，绝不展开容器或 `Object`）。
  - 颜色工具：`is_finite_color(c: Color) -> bool`、`is_unit_color(c: Color) -> bool`、`clamp_color(c: Color, fallback: Color = Color.BLACK) -> Color`、`is_hex8_color(color_str: String) -> bool`、`coerce_color_value(raw: Variant, fallback: Color = Color.BLACK) -> Dictionary`、`coerce_color_array(raw: Variant) -> Variant`。

#### 4. `utils/validation_utils.gd`（十六进制校验、控制字符清理与宿主判断）
- **公共静态入口与参数化标志**：
  - 十六进制校验：`is_valid_hex(val: String, expected_len: int, allow_uppercase: bool = false) -> bool`、`is_valid_uid(uid: String) -> bool`（32 位小写 hex）、`is_valid_hex24(val: String) -> bool`（24 位小写 hex）、`is_valid_hex64(val: String, allow_uppercase: bool = false) -> bool`（`backpack.gd` 校验修订摘要时传 `allow_uppercase = true`；其余如 `feature_obstacle_authoring.gd`、`dice.gd`、`dnd_opportunity.gd`、`resource_pool.gd`、`scene_box.gd` 传 `false` 仅认小写）。
  - BOM / NUL / 控制字符清理与检测：`strip_leading_bom(text: String) -> String`、`strip_bom_and_edges(text: String) -> String`、`has_nul(text: String) -> bool`、`strip_nul(text: String) -> String`、`strip_control_and_edges(text: String) -> String`、`sanitize_line_text(text: String) -> String`、`has_control_chars(text: String, include_c1: bool = false) -> bool`（`feature_floor_system.gd`、`feature_layer_stack.gd`、`scene_box.gd` 传 `include_c1 = true` 同步拦截 `127..159` C1 控制字符；`character_roster.gd`、`dice.gd`、`resource_pool.gd` 传 `false`）、`has_control_except_tab(text: String) -> bool`（`dice.gd` 使用，允许 `\t`）。
  - 组件与宿主实体识别：`component_id_from_script(script_path: String) -> String`、`is_unit_host(entity: Dictionary) -> bool`。

### 3.9 控制台日志参考插件 (`mods/sdk-log-console/`)

工作区内置了纳入 Git 跟踪的 `fus.session-plugin.v1` 独立控制台日志诊断插件 **`mods/sdk-log-console/`**（清单 ID：`sdk_log_console`，支持 `.json` 与 `.log` 导入）：
- 严格遵守 `<FUS_REPO_DIR>` 源码级宿主边界（不在 `DesktopScreen` 中越权挂载运行时 UI）；
- 示范如何通过 `session.get_logger()`（`subscribe` / `unsubscribe` / `get_entries` / `get_warnings` / `attach_import_host`）与 `builder.get_module_registry()`（`check_and_warn` / `get_plugin_sdk`）审计多模块可用性、测试 `100 条 / 7000 字符` 警告上限保护、安全回放历史 `ERROR` 日志，并输出至 `host.report`、`host.warn`（`metadata.notes`）、引擎控制台流与可选的世界内 `checklist` + `drawing`（`text_ink`）看板。

## 4. 客户端版本升级与真机验证标准流程

当 Steam Playtest 推送客户端更新后，按以下四步完成零波及适配与验收：

1. **双源契约金丝雀巡检**：运行 `python shared/tools/fuvtt_cli.py inspect-client --source both`，同时比对 Steam 客户端 PCK / `Practice.dll` 与上游 Git `Practice` 分支的契约指纹。
2. **单点演进 Adapter**：若底层世界字典或宿主回调发生变更，仅修改 `shared/sdk/fu_sdk/adapters/host_v1_adapter.gd`（或新增 `host_v2_adapter.gd` 并在 `v1.gd` 按宿主特征路由），保持 `v1.gd` 对外方法签名向后兼容。
3. **一键全量重打包**：运行 `python shared/tools/fuvtt_cli.py build --all`，所有下游 `mods/*` 无需修改业务源码即可自动内嵌最新适配器并完成升级。
4. **Godot 4.8-beta1 Mono 真机无头冒烟**：运行 `python shared/tools/fuvtt_cli.py verify-host <mod-name>`，验证脚本真实编译、导入回合执行及 `bytes_to_var(var_to_bytes(world))` 二进制往返无损一致性。
