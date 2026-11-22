# Shared SDK (`fu_sdk` 防腐层共享库)

本目录承载跨插件复用的 **Fu vtt 防腐层 SDK（Anti-Corruption Layer）**，为工作区内所有 `mods/<mod-name>/` 提供稳定的跑团场景导入语义接口，彻底屏蔽宿主底层字典结构与内测期接口变动风险。

> [!WARNING]
> **Playtest 内测阶段说明**  
> 当前实测验证基线为现役 **`Practice` 主线 `v0.0.56`（Git `origin/codex/fuvtt-project-sync` `282aee64`）/ Steam Playtest `v0.0.57`（`3f20e8e`）**，验证日期：`2026-11-20`（`fus.session-plugin.v1` / `host_api = 1` / `fus.practice.world` v3 / `fus.floor_layers.v2`）。  
> 所有与客户端底层强耦合的字段名、组件脚本路径与图层结构均已收敛至 `fu_sdk/adapters/`，禁止在业务插件中直接硬编码底层世界字典。本 SDK **不适用于**旧原型线 `FUS-F2`（`v0.1.80`）。

## 1. 目录结构与职责边界

- `fu_sdk/v1.gd`（`SDK_VERSION = "1.1.0"`）：面向下游插件向后兼容演进的 `v1` 稳定门面（提供外层实例工厂、`ImportSession` 会话上下文与 `WorldBuilder` 高阶场景构建器）。
- `fu_sdk/adapters/host_v1_adapter.gd`：面向 `host_api = 1` 宿主的唯一底层适配器，负责：
  - `host.has_method(...)` 宿主能力安全嗅探（`cancelled`、`report`、`warn`、`archive_image`、`inspect_source`、`decode_source`、`empty_world`、预览回调）；
  - `inspect_import` 返回值兜底保护（自动计算 `FileAccess.get_sha256(source_path)` 注入必填 `"sha256"` 键，并补齐包含 `"unsupported": 0` 在内的全部 12 项默认 `counts` 键）；
  - 世界字典强契约守卫：`extract_default_world_targets()` 兜底补齐 `entity_state.version = 3` 与 `modules = {"version": 2, "entries": {}}`；
  - 坐标、文本与矢量配额守卫：头部 UTF-8 BOM（`0xFEFF`）剥离、`pos/rot/scale` 有限数与非零缩放守卫、`footprint_radius ∈ [0.5, 4096.0]`、`font_size ∈ [1.0, 4096.0]`、`text <= 65536`、`vertices <= 600000`、`paths <= 8192`、总点数 `<= 800000`；
  - **`sprite_path` 前置合法性拦截**：仅放行 `""`、`asset://<sha256>.<ext>` 或合法 `res://` 贴图，主动拦截宿主会拒收的 `user://` 路径并向 `ImportSession` 记警告；
  - **5 类原生障碍物与带孔多边形裁剪**：支持 `wall` / `air` / `door` / `window` / `glass` 全 5 类角色，自动过滤 `< 3` 点退化环防 `obstacle_shape_preparation_failed`，并对带内孔多边形先执行 `Geometry2D.clip_polygons` 切分扣洞再三角剖分，落盘时自动由宿主 `ImportBridge` 注入 `comp_obstacle.gd`；
  - **核心组件前缀不变量护栏**：`append_entity()` 与 `append_entity_component()` 严格锁死 `components[0] = comp_visual.gd`、`components[1] = comp_permission.gd`，所有可选组件一律追加在索引 `>= 2`，保障宿主 `preview_entity` 与晚加入快路径 `EntryCoreDrafts` 零破坏。

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
	var base_dir: String = (get_script() as Script).resource_path.get_base_dir()
	var packaged_path: String = base_dir.path_join(_SDK_PACKAGED_REL_PATH)
	var sdk_path: String = packaged_path if FileAccess.file_exists(packaged_path) else base_dir.path_join(_SDK_DEV_REL_PATH).simplify_path()
	if not FileAccess.file_exists(sdk_path):
		return null
	var sdk_script := load(sdk_path) as Script
	return sdk_script.new() if sdk_script != null else null
```

## 3. 核心 API 速览 (`fu_sdk/v1.gd`)

### `FuSdk` 门面实例方法
- `create_session(host: RefCounted, options: Dictionary = {}) -> ImportSession`
- `create_world_builder(session: ImportSession = null, source_units_per_cell: float = 150.0) -> WorldBuilder`

### `ImportSession`
- `is_cancelled() -> bool`：检查用户是否取消导入。
- `report_progress(message: String) -> void`：向宿主汇报当前转换进度。
- `add_warning(message: String) -> void`：记录非致命警告。
- `archive_remote_image(url: String, proxy: String = "") -> String`：按 URL 去重下载并归档外部图片，返回 `asset://` 引用（失败或非法路径自动记警告并返回 `""`）。
- `validate_sprite_path(sprite_ref: String) -> String`：校验外部传入的贴图路径，拦截 `user://` 等非法路径并记警告。
- `inspect_source(path: String) -> Dictionary` / `decode_source(path: String) -> Dictionary`：可选探测并调用宿主自带的 FOBR/几何解析内核。
- `ok_inspect(source_path: String, counts_override: Dictionary = {}, remote_assets: Dictionary = {}) -> Dictionary`：构造符合宿主 `ImportBridge` 强校验的探测成功字典。
- `err_cancelled() -> Dictionary` / `err_failed(reason: String) -> Dictionary`：构造标准错误返回字典。

### `WorldBuilder`

#### 世界与多楼层 / 4 类图层
- `setup(session: ImportSession, source_units_per_cell: float = 150.0) -> Dictionary`：初始化空白世界并校验图层契约（若已在 `create_world_builder(session, units)` 中传入 `session`，重复调用不会二次触发 `empty_world()`）。
- `add_floor(name: String, color: Color = Color(0.28, 0.65, 0.40), activate: bool = false) -> String`：新增楼层并自动创建默认 `map` / `entity` / `obstacle` 三层（默认 `locked: false`），返回 32 位 `floor_uid`。
- `set_active_floor(floor_uid: String) -> bool`：切换世界活动楼层与构建器当前写入楼层。
- `add_layer(name: String, kind: String = "entity", access: String = "all", floor_uid: String = "", viewers: Array = [], locked: bool = false, visible: bool = true, persistent: bool = true) -> String`：新增自定义图层（支持 `"map" | "entity" | "obstacle" | "area"` 与 `"all" | "host" | "players"` 权限策略），返回 32 位 `layer_uid`。
- `get_active_floor_uid() -> String` / `get_layer_uid(kind: String, floor_uid: String = "") -> String`：查询当前楼层与指定类型图层 UID。

#### 流式预览与基础实体
- `begin_bounds_preview(total_items: int, source_bounds: Rect2) -> void` / `finish_geometry_preview() -> bool`：控制宿主两阶段几何与实体流式预览。
- `add_map_tile(...) -> String`：向 `map` 图层添加底图贴图并返回 32 位实体 ID。
- `add_token(...) -> String`：向 `entity` 图层添加可点选角色棋子（`entity_type = "unit"`，支持可选 `footprint_radius`、`locked`、`permission_state`）。
- `add_object_sprite(...) -> String`：向 `entity` 图层添加普通道具贴图（`entity_type = "object"`）。
- `add_text_note(...) -> String` / `add_vector_drawing(...) -> String`：向 `entity` 图层添加矢量文字标签或自由矢量笔迹。
- `add_text_pin(source_id, text, center_src, name = "", keep_screen_size = true, size_src = Vector2(48.0, 60.0), hidden = false) -> String`：创建挂载 `comp_entity_note.gd`（`is_pin: true`）的世界文本图钉。

#### 5 类原生障碍物（导入落盘时由宿主自动烘焙 `comp_obstacle.gd`）
- `add_polygon_obstacle(source_id, name, center_src, polygons_src, kind = "wall", is_open_door = false, enabled = true, layer_uid_override = "") -> String`：通用多边形障碍物接口，支持 `{outer, holes}` 带孔面与原始环数组；自动过滤 `< 3` 点退化环并告警，带孔面自动裁剪扣洞后三角剖分。
- `add_wall(...) -> String` / `add_door(..., is_open = false) -> String` / `add_window(..., is_open = false) -> String` / `add_glass_wall(...) -> String` / `add_air_cutout(...) -> String`：全 5 种障碍物语义快捷方法。

#### 可选组件挂载与模块数据写入
- `attach_component(entity_id: String, script_path: String, state: Dictionary = {}, parked: bool = false) -> bool`：安全追加可选组件至索引 `>= 2`（拒绝覆写 `[visual, permission]` 核心前缀）。
- `attach_unit_marker(entity_id: String) -> bool`：挂载 `comp_unit.gd`（`{"schema_version": 1}`）。
- `attach_portal(entity_id: String, pair_key: String) -> bool`：挂载 `comp_portal.gd`（自动将非 32-hex 文本归一为 32 位小写十六进制 `pair_key`）。
- `attach_simple_vision(entity_id, radius = 640.0, view_angle_deg = 360.0, requires_light = false, enabled = true) -> bool`：挂载简易迷雾视野 `comp_simple_vision.gd`。
- `attach_simple_light(entity_id, radius = 640.0, view_angle_deg = 360.0, enabled = true) -> bool`：挂载简易迷雾光源 `comp_simple_light.gd`。
- `set_module_state(module_id: String, version: int, state: Dictionary) -> bool`：向 `world.modules`（`version = 2`）写入受配额保护的模块纯数据（单条 `<= 6 MiB`、总限 `<= 8 MiB`）。
- `build_result(source_record_count: int = 0, merged_wall_count: int = 0) -> Dictionary`：输出最终 `prepare_import` 返回字典。

## 4. 客户端版本升级与真机验证标准流程

当 Steam Playtest 推送客户端更新后，按以下四步完成零波及适配与验收：

1. **双源契约金丝雀巡检**：运行 `python shared/tools/fuvtt_cli.py inspect-client --source both`，同时比对 Steam 客户端 PCK / `Practice.dll` 与上游 Git `Practice` 分支的契约指纹。
2. **单点演进 Adapter**：若底层世界字典或宿主回调发生变更，仅修改 `shared/sdk/fu_sdk/adapters/host_v1_adapter.gd`（或新增 `host_v2_adapter.gd` 并在 `v1.gd` 按宿主特征路由），保持 `v1.gd` 对外方法签名向后兼容。
3. **一键全量重打包**：运行 `python shared/tools/fuvtt_cli.py build --all`，所有下游 `mods/*` 无需修改业务源码即可自动内嵌最新适配器并完成升级。
4. **Godot 4.8-beta1 Mono 真机无头冒烟**：运行 `python shared/tools/fuvtt_cli.py verify-host <mod-name>`，验证脚本真实编译、导入回合执行及 `bytes_to_var(var_to_bytes(world))` 二进制往返无损一致性。
