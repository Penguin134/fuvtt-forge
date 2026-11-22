# Shared SDK (`fu_sdk` 防腐层共享库)

本目录承载跨插件复用的 **Fu vtt 防腐层 SDK（Anti-Corruption Layer）**，为工作区内所有 `mods/<mod-name>/` 提供稳定的跑团场景导入语义接口，彻底屏蔽宿主底层字典结构与内测期接口变动风险。

> [!WARNING]
> **Playtest 内测阶段说明**  
> 当前实测验证基线为现役 **`Practice` 主线 `v0.0.56`（Git `origin/codex/fuvtt-project-sync` `282aee64`）/ Steam Playtest `v0.0.57`（`3f20e8e`）**，验证日期：`2026-11-22`（`fus.session-plugin.v1` / `host_api = 1` / `fus.practice.world` v3 / `fus.floor_layers.v2`）。  
> 所有与客户端底层强耦合的字段名、组件脚本路径与图层结构均已收敛至 `fu_sdk/adapters/`，禁止在业务插件中直接硬编码底层世界字典。本 SDK **不适用于**旧原型线 `FUS-F2`（`v0.1.80`）。

## 1. 目录结构与职责边界

- `fu_sdk/v1.gd`（`SDK_VERSION = "1.2.0"`）：面向下游插件向后兼容演进的 `v1` 稳定门面（提供外层实例工厂、`coerce_*` 安全强转助手、`ImportSession` 会话上下文与 `WorldBuilder` 高阶场景构建器）。
- `fu_sdk/adapters/host_v1_adapter.gd`：面向 `host_api = 1` 宿主的唯一底层适配器，负责：
  - `host.has_method(...)` 宿主能力安全嗅探（`cancelled`、`report`、`warn`、`archive_image`、`inspect_source`、`decode_source`、`empty_world`、预览回调）；
  - `inspect_import` 返回值兜底保护（自动计算 `sha256`、`source_bytes`、`decoded_bytes`、`unique_images`、`name`，并补齐包含 `"unsupported": 0` 在内的全部 12 项默认 `counts` 键）；
  - 世界字典强契约守卫：`extract_default_world_targets()` 兜底补齐 `entity_state.version = 3` 与 `modules = {"version": 2, "entries": {}}`；
  - 坐标、文本、矢量与模块预算守卫：头部 UTF-8 BOM（`0xFEFF`）剥离、`pos/rot/scale` 有限数与非零缩放守卫、`footprint_radius ∈ [0.5, 4096.0]`、`font_size ∈ [1.0, 4096.0]`、`text <= 65536`、`vertices <= 600000`、`paths <= 8192`、总点数 `<= 800000`，以及 `world.modules` 递归纯数据净化与 `6 MiB / 8 MiB / 30 MiB` 预算校验；
  - **`sprite_path` 前置合法性拦截（拆分 `asset://` 与 `res://` 白名单）**：`ALLOWED_ASSET_IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "webp", "bmp"]`（对齐宿主 `CampaignImageFiles` / `ImageHeader`，拒收 `.svg` 与 `.gif`）、`ALLOWED_RES_IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "webp", "bmp", "svg"]`，主动拦截 `user://` 等非法路径并向 `ImportSession` 记警告；
  - **5 类原生障碍物、线段挤出与带孔多边形裁剪**：支持 `wall` / `air` / `door` / `window` / `glass` 全 5 类角色，提供 `extrude_segment_to_quad()` 将 2 点线段按法线挤出为带 ULP 鞋带面积校验的 4 顶点闭合多边形，自动过滤 `< 3` 点退化环防 `obstacle_shape_preparation_failed`，并对带内孔多边形先执行 `Geometry2D.clip_polygons` 切分扣洞再三角剖分，落盘时自动由宿主 `ImportBridge` 注入 `comp_obstacle.gd`；
  - **核心组件前缀不变量护栏**：`append_entity()` 与 `append_entity_component()` 严格锁死 `components[0] = comp_visual.gd`、`components[1] = comp_permission.gd`，所有可选组件一律追加在索引 `>= 2`，保障宿主 `preview_entity` 与晚加入快路径 `EntryCoreDrafts` 零破坏。
- `fu_sdk/modules/`：跨插件复用的纯 GDScript 功能子模块库（随 `lib/fu_sdk/` 一并自动内嵌打包，见 §3.5）：
  - `asset_publisher.gd`（图片魔数/头预检、BMP/SVG 转 PNG、`SharedAssetStore.Publish` 与 `MockHostBridge` 回退）
  - `entity_library_writer.gd`（`<root>/entity-library/` 安全四门控写入、`.revision` 链式传递与原子回滚）
  - `package_source.gd`（`.zip` 归档与解压目录清单双输入抽象读取器）
  - `snappy.gd`（纯 GDScript Snappy 块解压器）

## 2. 构建期自动内嵌（Vendored Bundle）与动态加载规范

由于当前客户端 `session_plugins` 运行于 `res://` 外部的独立内容寻址目录（`FUS_Data/session_plugins/packages/<id>/<sha256>/`），且不支持跨插件依赖声明：

1. **自动内嵌打包**：执行 `python shared/tools/fuvtt_cli.py build <mod-name>` 时，打包器会自动将 `shared/sdk/fu_sdk/` 注入插件归档内的 `lib/fu_sdk/` 目录，对终端玩家保持零前置依赖。
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
- `create_asset_publisher() -> RefCounted`：实例化 `modules/asset_publisher.gd`。
- `create_entity_library_writer() -> RefCounted`：实例化 `modules/entity_library_writer.gd`。
- `create_package_source() -> RefCounted`：实例化 `modules/package_source.gd`。
- `create_snappy_codec() -> RefCounted`：实例化 `modules/snappy.gd`。
- `coerce_bool(value: Variant, fallback: bool = false) -> bool`：安全转换 `bool` / 非零 `int` / 有限非 `NaN` `float` / `"true"/"1"/"yes"/"on"` 与 `"false"/"0"/"no"/"off"`。
- `coerce_string(value: Variant, fallback: String = "") -> String`：仅当 `typeof(value) == TYPE_STRING` 时返回原串，绝不把 `null` 转成 `"Null"`。
- `coerce_int(value: Variant, fallback: int = 0) -> int`：带 64 位有符号整数上下界检查（`-9223372036854775808..9223372036854775807`）的安全整数强转。
- `coerce_float(value: Variant, fallback: float = 0.0) -> float`：安全转换整数、有限浮点数或合法有限浮点字符串。

### 3.2 `ImportSession`
- `get_bool_option(key: String, fallback: bool = false) -> bool` / `get_string_option(key: String, fallback: String = "") -> String` / `get_int_option(key: String, fallback: int = 0) -> int` / `get_float_option(key: String, fallback: float = 0.0) -> float`：类型安全的选项读取接口。
- `sanitize_options(defaults: Dictionary) -> Dictionary`：按 `defaults` 字典的值类型一次性批量清洗 `options`，彻底防止 `options = {"proxy": null}` 在读取或透传时变成 `"Null"`。
- `is_cancelled() -> bool`：检查用户是否取消导入。
- `report_progress(message: String) -> void`：向宿主汇报当前转换进度。
- `add_warning(message: String) -> void`：记录非致命警告。
- `archive_remote_image(url: String, proxy: String = "") -> String`：按 URL 去重下载并归档外部图片，返回 `asset://` 引用（失败或非法路径自动记警告并返回 `""`；读取 `_options["proxy"]` 时已做 `typeof == TYPE_STRING` 防 `null` 守卫）。
- `validate_sprite_path(sprite_ref: String) -> String`：校验外部传入的贴图路径，拦截 `user://` 及 `asset://` 非白名单扩展名并记警告。
- `inspect_source(path: String) -> Dictionary` / `decode_source(path: String) -> Dictionary`：可选探测并调用宿主自带的 FOBR/几何解析内核。
- `ok_inspect(source_path: String, counts_override: Dictionary = {}, remote_assets: Dictionary = {}, decoded_bytes: int = -1, display_name: String = "") -> Dictionary`：构造符合宿主 `ImportBridge` 与 `import_confirmation.gd` 强校验的探测成功字典，自动注入 `sha256`、`source_bytes`、`decoded_bytes`（默认回退 `source_bytes`）、`unique_images`（`maxi(counts.images, remote_assets.size())`）与 `name`（清洗后的 `display_name` 或源文件名）。注意 `remote_assets` 仅应传入 `http://`/`https://` URL，切勿放入本地图片路径。
- `err_cancelled() -> Dictionary` / `err_failed(reason: String) -> Dictionary`：构造标准错误返回字典。

### 3.3 `WorldBuilder` — 楼层、图层、流式预览与基础实体

#### 世界与多楼层 / 4 类图层
- `setup(session: ImportSession, source_units_per_cell: float = 150.0) -> Dictionary`：初始化空白世界并校验图层契约（同时重置内置 `_entity_by_id` `O(1)` 实体索引；若已在 `create_world_builder(session, units)` 中传入 `session`，重复调用不会二次触发 `empty_world()`）。
- `add_floor(name: String, color: Color = Color(0.28, 0.65, 0.40), activate: bool = false) -> String`：新增楼层并自动创建默认 `map` / `entity` / `obstacle` 三层（默认 `locked: false`），返回 32 位 `floor_uid`。
- `set_active_floor(floor_uid: String) -> bool`：切换世界活动楼层与构建器当前写入楼层。
- `rename_floor(floor_uid: String, new_name: String) -> bool`：安全重命名已有楼层（典型场景：将 `empty_world()` 预建的 `"1F"` Floor 0 重命名为导入首张场景名），同步更新 `catalog.floors` 及 `catalog.layers.floors`（若存在 `name` 键）。
- `add_layer(name: String, kind: String = "entity", access: String = "all", floor_uid: String = "", viewers: Array = [], locked: bool = false, visible: bool = true, persistent: bool = true) -> String`：新增自定义图层（支持 `"map" | "entity" | "obstacle" | "area"` 与 `"all" | "host" | "players"` 权限策略），返回 32 位 `layer_uid`。
- `get_active_floor_uid() -> String` / `get_layer_uid(kind: String, floor_uid: String = "") -> String`：查询当前楼层与指定类型图层 UID。

#### 流式预览与基础实体
- `begin_bounds_preview(total_items: int, source_bounds: Rect2) -> void` / `finish_geometry_preview() -> bool`：控制宿主两阶段几何与实体流式预览。
- `add_map_tile(...) -> String`：向 `map` 图层添加底图贴图并返回 32 位实体 ID。
- `add_token(...) -> String`：向 `entity` 图层添加可点选角色棋子（`entity_type = "unit"`，支持可选 `footprint_radius`、`locked`、`permission_state`）。
- `add_object_sprite(...) -> String`：向 `entity` 图层添加普通道具贴图（`entity_type = "object"`）。
- `add_text_note(...) -> String` / `add_vector_drawing(...) -> String`：向 `entity` 图层添加矢量文字标签或自由矢量笔迹。
- `add_text_pin(source_id, text, center_src, name = "", keep_screen_size = true, size_src = Vector2(48.0, 60.0), hidden = false, layer_uid_override = "") -> String`：创建挂载 `comp_entity_note.gd`（`is_pin: true`）的世界文本图钉。

### 3.4 `WorldBuilder` — 障碍物、组件、光照、网格与模块预算

#### 5 类原生多边形障碍物与 2 点线段自动挤出（导入落盘时由宿主自动烘焙 `comp_obstacle.gd`）
- `add_polygon_obstacle(source_id, name, center_src, polygons_src, kind = "wall", is_open_door = false, enabled = true, layer_uid_override = "") -> String`：通用多边形障碍物接口，支持 `{outer, holes}` 带孔面与原始环数组；自动过滤 `< 3` 点退化环并告警，带孔面自动裁剪扣洞后三角剖分。
- `add_wall(...) -> String` / `add_door(..., is_open = false) -> String` / `add_window(..., is_open = false) -> String` / `add_glass_wall(...) -> String` / `add_air_cutout(...) -> String`：全 5 种多边形障碍物语义快捷方法。
- `extrude_segment_to_quad(p0: Vector2, p1: Vector2, half_width: float = 6.0, min_length: float = 0.5) -> PackedVector2Array`：将 2 点线段按法线挤出为 4 顶点闭合矩形，内置有限数检查、`half_width >= 0.5` 与 `min_length` 钳位及鞋带面积校验（防御大坐标坍缩）。
- `add_segment_obstacle(source_id, name, p0_src, p1_src, half_width_src = 6.0, kind = "wall", is_open_door = false, enabled = true, layer_uid_override = "") -> String`：面向外部 VTT（如 FVTT）2 点线段墙体的专用入口——**先将 `p0_src`/`p1_src` 平移至相对 `center_src` 的局部坐标再执行挤出**，彻底避免 `1e7` 量级大坐标下 `float32` ULP 精度坍塌导致 `FobrWallKernel.AuthorReadPaths` 拒收；另提供快捷方法 `add_segment_wall(...)`、`add_segment_door(..., is_open = false)`、`add_segment_window(..., is_open = false)`、`add_segment_glass_wall(...)`。

#### 可选组件挂载、透明点光源、全局网格与模块配额校验
- `attach_component(entity_id: String, script_path: String, state: Dictionary = {}, parked: bool = false) -> bool`：基于内置 `_entity_by_id` **`O(1)` 哈希索引**（未命中时回退倒序扫描）定位实体，在数千实体大世界中高效追加可选组件至索引 `>= 2`（拒绝覆写 `[visual, permission]` 核心前缀）。
- `attach_unit_marker(entity_id: String) -> bool`：挂载 `comp_unit.gd`（`{"schema_version": 1}`）。
- `attach_portal(entity_id: String, pair_key: String) -> bool`：挂载 `comp_portal.gd`（自动将非 32-hex 文本归一为 32 位小写十六进制 `pair_key`）。
- `attach_simple_vision(entity_id, radius = 640.0, view_angle_deg = 360.0, requires_light = false, enabled = true) -> bool`：挂载简易迷雾视野 `comp_simple_vision.gd`（`radius` 为 Fu VTT 世界单位）。
- `attach_simple_light(entity_id, radius = 640.0, view_angle_deg = 360.0, enabled = true) -> bool`：挂载简易迷雾光源 `comp_simple_light.gd`。
- `suppress_entity_fallback_box(entity_id: String) -> bool`：将实体的 `entity.fallback_color` 与 `components[0].state.fallback_color` 设为全透明 `Color(1, 1, 1, 0)` 并置 `show_fallback = false`，隐藏无贴图锚点的默认灰色占位方块。
- `add_point_light(source_id, center_src, radius_world, view_angle_deg = 360.0, name = "Light", hidden = false, enabled = true, size_src = Vector2(32.0, 32.0), layer_uid_override = "") -> String`：一步创建不可见纯光源锚点实体（自动抑制占位方块并挂载 `comp_simple_light.gd`）。
- `configure_grid_alignment(cell_size = 64.0, snap_enabled = true, offset = Vector2.ZERO, color = Color(0.5, 0.55, 0.65, 0.7), line_width = 1.0, snap_strength = 0.1) -> bool`：向 `world.modules.entries["grid_alignment"]`（`version = 1`）写入精确 8 键 `fus.grid_alignment.config` v1 状态。
- `set_module_state(module_id: String, version: int, state: Dictionary) -> bool`：向 `world.modules`（`version = 2`）写入受配额保护的模块纯数据（单条 `<= 6 MiB`、总限 `<= 8 MiB`）。
- `sanitize_module_data(value: Variant) -> Variant`：递归清洗模块数据（剔除 `NaN`/`Inf` 置 `0.0`、超出 32 层或非纯数据对象置 `null`、`StringName`/`NodePath` 转 `String`）。
- `can_fit_module_state(module_id: String, version: int, state: Dictionary, max_world_bytes: int = 30 * 1024 * 1024) -> bool`：预检模块写入是否同时满足单条 `<= 6 MiB`、模块区总量 `<= 8 MiB` 与整份世界 `<= max_world_bytes`（默认 `30 MiB`）上限，便于插件实施渐进裁剪。
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

## 4. 客户端版本升级与真机验证标准流程

当 Steam Playtest 推送客户端更新后，按以下四步完成零波及适配与验收：

1. **双源契约金丝雀巡检**：运行 `python shared/tools/fuvtt_cli.py inspect-client --source both`，同时比对 Steam 客户端 PCK / `Practice.dll` 与上游 Git `Practice` 分支的契约指纹。
2. **单点演进 Adapter**：若底层世界字典或宿主回调发生变更，仅修改 `shared/sdk/fu_sdk/adapters/host_v1_adapter.gd`（或新增 `host_v2_adapter.gd` 并在 `v1.gd` 按宿主特征路由），保持 `v1.gd` 对外方法签名向后兼容。
3. **一键全量重打包**：运行 `python shared/tools/fuvtt_cli.py build --all`，所有下游 `mods/*` 无需修改业务源码即可自动内嵌最新适配器并完成升级。
4. **Godot 4.8-beta1 Mono 真机无头冒烟**：运行 `python shared/tools/fuvtt_cli.py verify-host <mod-name>`，验证脚本真实编译、导入回合执行及 `bytes_to_var(var_to_bytes(world))` 二进制往返无损一致性。
