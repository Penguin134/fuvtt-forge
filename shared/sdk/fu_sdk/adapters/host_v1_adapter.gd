extends RefCounted
## Fu vtt Host API v1 底层防腐适配器 (Practice / Steam Playtest v0.0.60, cc3d43a5 / fus.floor_layers.v2 / SceneRepository v2)
##
## 唯一允许感知宿主底层字典结构、组件脚本路径与图层 UID 规则的适配层。
## 当后续 Playtest 客户端调整底层结构时，仅需在此目录演进 Adapter，保持上层 v1.gd 契约稳定。

const HOST_API_VERSION: int = 1
const WORLD_FORMAT: String = "fus.practice.world"
const WORLD_VERSION: int = 3
const ENTITY_STATE_VERSION: int = 3
const MODULE_STATE_VERSION: int = 2
const FLOOR_LAYERS_SCHEMA: String = "fus.floor_layers.v2"

const COMP_VISUAL_SCRIPT: String = "res://scenes/entities/components/comp_visual.gd"
const COMP_PERMISSION_SCRIPT: String = "res://scenes/entities/components/comp_permission.gd"
const COMP_UNIT_SCRIPT: String = "res://scenes/entities/components/comp_unit.gd"
const COMP_OBSTACLE_SCRIPT: String = "res://modules/obstacle_authoring/comp_obstacle.gd"
const COMP_ENTITY_NOTE_SCRIPT: String = "res://scenes/candidates/entity_notes/comp_entity_note.gd"
const COMP_PORTAL_SCRIPT: String = "res://modules/portal/comp_portal.gd"
const COMP_SIMPLE_VISION_SCRIPT: String = "res://modules/simple_fog/comp_simple_vision.gd"
const COMP_SIMPLE_LIGHT_SCRIPT: String = "res://modules/simple_fog/comp_simple_light.gd"
const COMP_SCENE_BOX_SCRIPT: String = "res://modules/scene_box/comp_scene_box.gd"
const COMP_IMAGE_FLIP_SCRIPT: String = "res://modules/image_flip/comp_image_flip.gd"
const COMP_DRAG_SPEED_SCRIPT: String = "res://modules/drag_movement/comp_drag_speed.gd"
const COMP_ENTITY_INK_SCRIPT: String = "res://modules/drawing/comp_entity_ink.gd"
const COMP_AREA_SCRIPT: String = "res://modules/areas/comp_area.gd"
const COMP_RESOURCE_POOL_SCRIPT: String = "res://scenes/candidates/resource_pool/comp_resource_pool.gd"
const COMP_ROSTER_MEMBER_SCRIPT: String = "res://modules/character_roster/comp_character_roster_member.gd"
const COMP_BACKPACK_SCRIPT: String = "res://modules/backpack/comp_backpack.gd"
const COMP_FOLLOW_SCRIPT: String = "res://modules/follow/comp_follow.gd"
const COMP_INITIATIVE_SCRIPT: String = "res://scenes/candidates/initiative/components/comp_initiative.gd"

const GRID_MIN_CELL_SIZE: float = 8.0
const GRID_MAX_CELL_SIZE: float = 4096.0
const GRID_MAX_OFFSET: float = 1000000.0
const GRID_MIN_LINE_WIDTH: float = 0.5
const GRID_MAX_LINE_WIDTH: float = 4.0

const SIMPLE_FOG_MAX_COMPRESSED_BYTES: int = 4 * 1024 * 1024
const SIMPLE_FOG_MAX_UNCOMPRESSED_BYTES: int = 64 * 1024 * 1024
const AREA_MAX_RADIUS_IN_CELLS: float = 256.0
const DEFAULT_AREA_FILL_COLOR: Color = Color("#55cda739")
const DEFAULT_AREA_LINE_COLOR: Color = Color("#58cba1d8")

const SCENE_BOX_MODULE_ID: String = "scene_box"
const SCENE_BOX_MODULE_VERSION: int = 1
const SCENE_BOX_SCHEMA_VERSION: int = 2
const MAX_SCENES: int = 64
const MAX_SCENE_VIEWERS: int = 128
const MAX_SCENE_VIEWER_KEY_LENGTH: int = 128
const DEFAULT_SCENE_FLOOR_COLOR: Color = Color(0.32, 0.56, 0.44)
const SCENE_BOX_PREVIEW_POLICIES: Array[String] = ["visited_unlock", "always_public", "cover_only"]
const SCENE_BOX_ENTER_POLICIES: Array[String] = ["players_allowed", "host_only"]
const SCENE_BOX_DEFAULT_SIDE_WORLD: float = 96.0
const SCENE_BOX_MIN_SIDE_WORLD: float = 72.0
const SCENE_BOX_MAX_SIDE_WORLD: float = 256.0
const SCENE_BOX_CONFLICT_COMPONENT_IDS: Array[String] = [
	"unit", "obstacle", "area", "image_flip", "portal",
	"character_roster_member", "initiative", "resource_pool", "backpack",
	"drag_speed", "follow", "simple_vision", "simple_light", "entity_ink",
]

const DEFAULT_LAYER_KINDS: Array[String] = ["map", "entity", "obstacle"]
const LAYER_KINDS: Array[String] = ["map", "entity", "obstacle", "area"]
const LAYER_ACCESS_POLICIES: Array[String] = ["all", "host", "players"]
const OBSTACLE_KINDS: Array[String] = ["wall", "air", "door", "window", "glass"]
const ALLOWED_ASSET_IMAGE_EXTENSIONS: Array[String] = ["png", "jpg", "jpeg", "webp", "bmp"]
const ALLOWED_RES_IMAGE_EXTENSIONS: Array[String] = ["png", "jpg", "jpeg", "webp", "bmp", "svg"]

const MAX_FLOORS: int = 512
const MAX_LAYERS_PER_FLOOR: int = 256
const MAX_TOTAL_LAYERS: int = 4096
const MAX_SELECTED_VIEWERS: int = 128
const MAX_NAME_LENGTH: int = 96
const MAX_VIEWER_KEY_LENGTH: int = 160

const MAX_VECTOR_VERTICES: int = 600000
const MAX_VECTOR_PATHS: int = 8192
const MAX_VECTOR_TOTAL_POINTS: int = 800000
const MAX_VECTOR_TEXT_LENGTH: int = 65536
const MIN_FONT_SIZE: float = 1.0
const MAX_FONT_SIZE: float = 4096.0

const MAX_NOTE_TEXT_LENGTH: int = 32768
const MAX_MODULE_ENTRIES: int = 128
const MAX_MODULE_ID_LENGTH: int = 128
const MAX_MODULE_ENTRY_BYTES: int = 16 * 1024 * 1024
const MAX_MODULE_TOTAL_BYTES: int = 24 * 1024 * 1024
const MAX_WORLD_BUDGET_BYTES: int = 30 * 1024 * 1024
const MAX_CLONE_VISITS: int = 2097152
const MAX_ESTIMATE_VISITS: int = 2097152
const MAX_DAG_LOGICAL_NODES_CLAMP: int = 1073741824
const MAX_CLONE_SHARED_SUBTREE: int = 4096
const MAX_CLONE_SHARED_UNFOLD: int = 8192

var _util_scripts: Dictionary = {}


## 按相对路径动态加载并缓存 utils/*.gd 叶子工具脚本（仅保存在当前实例上，不产生跨对象循环引用）。
func _load_util_script(file_name: String) -> Variant:
	if _util_scripts.has(file_name):
		return _util_scripts[file_name]
	var rel_from_subdir: String = "../utils/" + file_name
	var self_scr := get_script() as Script
	if self_scr != null and not self_scr.resource_path.is_empty():
		var base_dir: String = self_scr.resource_path.split("::")[0].get_base_dir()
		var candidate: String = base_dir.path_join(rel_from_subdir).simplify_path()
		if FileAccess.file_exists(candidate) or ResourceLoader.exists(candidate):
			var loaded := load(candidate) as Script
			if loaded != null:
				_util_scripts[file_name] = loaded
				return loaded
	for raw_frame: Variant in get_stack():
		if raw_frame is Dictionary:
			var src_file: String = str((raw_frame as Dictionary).get("source", ""))
			if not src_file.is_empty():
				var stack_cand: String = src_file.get_base_dir().path_join(rel_from_subdir).simplify_path()
				if FileAccess.file_exists(stack_cand) or ResourceLoader.exists(stack_cand):
					var loaded_stack := load(stack_cand) as Script
					if loaded_stack != null:
						_util_scripts[file_name] = loaded_stack
						return loaded_stack
	for fb_path: String in [
		"res://shared/sdk/fu_sdk/utils/" + file_name,
		"shared/sdk/fu_sdk/utils/" + file_name,
	]:
		if FileAccess.file_exists(fb_path) or ResourceLoader.exists(fb_path):
			var loaded_fb := load(fb_path) as Script
			if loaded_fb != null:
				_util_scripts[file_name] = loaded_fb
				return loaded_fb
	return null


func _dag_cloner() -> Variant:
	return _load_util_script("dag_cloner.gd")


func _value_utils() -> Variant:
	return _load_util_script("value_utils.gd")


func _validation_utils() -> Variant:
	return _load_util_script("validation_utils.gd")

const DEFAULT_SOURCE_UNITS_PER_CELL: float = 150.0
const WORLD_UNITS_PER_CELL: float = 64.0
const MIN_ENTITY_SIZE: Vector2 = Vector2(4.0, 4.0)
const MIN_FOOTPRINT_RADIUS: float = 0.5
const MAX_FOOTPRINT_RADIUS: float = 4096.0
const DEFAULT_FOOTPRINT_RADIUS: float = 32.0
const DEFAULT_ID_NAMESPACE: String = "fu_sdk"

const DEFAULT_FLOOR_COLOR: Color = Color(0.28, 0.65, 0.40)
const DEFAULT_ENTITY_FALLBACK_COLOR: Color = Color(0.55, 0.6, 0.7)
const DEFAULT_SPRITE_FALLBACK_COLOR: Color = Color(0.6, 0.6, 0.65)
const DEFAULT_WALL_COLOR: Color = Color(0.086, 0.227, 0.275, 1.0)
const DEFAULT_LINE_COLOR: Color = Color(0.086, 0.227, 0.275)
const DEFAULT_DOOR_CLOSED_COLOR: Color = Color(0.91, 0.57, 0.15, 1.0)
const DEFAULT_DOOR_OPEN_COLOR: Color = Color(0.91, 0.57, 0.15, 0.6)
const DEFAULT_WINDOW_CLOSED_COLOR: Color = Color(0.22, 0.56, 0.92, 0.9)
const DEFAULT_WINDOW_OPEN_COLOR: Color = Color(0.22, 0.56, 0.92, 0.45)
const DEFAULT_GLASS_COLOR: Color = Color(0.86, 0.92, 0.98, 0.75)
const DEFAULT_AIR_COLOR: Color = Color(0.09, 0.59, 0.71, 0.7)

const DEFAULT_INSPECT_COUNTS: Dictionary = {
	"records": 0,
	"images": 0,
	"selected_images": 0,
	"maps": 0,
	"characters": 0,
	"objects": 0,
	"text": 0,
	"drawings": 0,
	"walls": 0,
	"doors": 0,
	"hidden": 0,
	"unsupported": 0,
}


func sanitize_text(value: String) -> String:
	# 剥离头部 UTF-8 BOM (0xFEFF)，与内置插件 _text() 及存档重载解码行为保持一致。
	return str(_validation_utils().strip_leading_bom(value))


func _as_string(value: Variant, fallback: String = "") -> String:
	return str(_value_utils().as_str(value, fallback))


func _strip_bom_and_edges(value: String) -> String:
	return str(_validation_utils().strip_bom_and_edges(value))


func sanitize_catalog_name(value: String, fallback: String = "未命名") -> String:
	var cleaned: String = sanitize_text(value)
	var out: String = ""
	for index: int in cleaned.length():
		var code: int = cleaned.unicode_at(index)
		if code < 32 or (code >= 127 and code <= 159):
			continue
		out += cleaned.substr(index, 1)
	out = out.strip_edges().left(MAX_NAME_LENGTH).strip_edges()
	return out if not out.is_empty() else fallback


func sanitize_viewer_key(value: String, max_len: int = MAX_VIEWER_KEY_LENGTH) -> String:
	for index: int in value.length():
		var code: int = value.unicode_at(index)
		if code < 32 or (code >= 127 and code <= 159):
			return ""
	var cleaned: String = value
	while true:
		var next_cleaned: String = sanitize_text(cleaned).strip_edges()
		if next_cleaned == cleaned:
			break
		cleaned = next_cleaned
	if cleaned.is_empty() or cleaned.length() > max_len:
		return ""
	return cleaned


func is_valid_uid(value: String) -> bool:
	return bool(_validation_utils().is_valid_uid(value))


func is_valid_module_id(module_id: String) -> bool:
	if module_id.is_empty() or module_id.length() > MAX_MODULE_ID_LENGTH:
		return false
	var regex := RegEx.new()
	if regex.compile("^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$") != OK:
		return false
	return regex.search(module_id) != null


func sanitize_finite_float(value: float, fallback: float = 0.0) -> float:
	return value if is_finite(value) else fallback


func sanitize_finite_vec2(value: Vector2, fallback: Vector2 = Vector2.ZERO) -> Vector2:
	return Vector2(
		value.x if is_finite(value.x) else fallback.x,
		value.y if is_finite(value.y) else fallback.y
	)


func sanitize_nonzero_scale(value: Vector2, fallback: Vector2 = Vector2.ONE) -> Vector2:
	var sx: float = value.x if is_finite(value.x) and not is_zero_approx(value.x) else fallback.x
	var sy: float = value.y if is_finite(value.y) and not is_zero_approx(value.y) else fallback.y
	if is_zero_approx(sx):
		sx = 1.0
	if is_zero_approx(sy):
		sy = 1.0
	return Vector2(sx, sy)


func sanitize_footprint_radius(value: float) -> float:
	if not is_finite(value):
		return DEFAULT_FOOTPRINT_RADIUS
	return clampf(value, MIN_FOOTPRINT_RADIUS, MAX_FOOTPRINT_RADIUS)


func coerce_bool(value: Variant, fallback: bool = false) -> bool:
	return bool(_value_utils().coerce_bool(value, fallback, true))


func coerce_string(value: Variant, fallback: String = "") -> String:
	return str(_value_utils().coerce_string(value, fallback))


func coerce_int(value: Variant, fallback: int = 0) -> int:
	return int(_value_utils().coerce_int(value, fallback, true))


func coerce_float(value: Variant, fallback: float = 0.0) -> float:
	return float(_value_utils().coerce_float(value, fallback, true))


func is_valid_sprite_path(path: String) -> bool:
	# 对齐 Practice CampaignImageFiles / ImageHeader 与 CompVisual._valid_image_path：
	# asset:// 仅允许 png/jpg/jpeg/webp/bmp（拒绝 svg/gif）；res:// 允许 png/jpg/jpeg/webp/bmp/svg；严禁 user://。
	var clean: String = sanitize_text(path).strip_edges()
	if clean.is_empty():
		return true
	if clean.begins_with("user://"):
		return false
	if clean.begins_with("asset://"):
		var body: String = clean.substr(8)
		if body.is_empty() or body.contains("..") or body.contains("/") or body.contains("\\"):
			return false
		var dot_idx: int = body.rfind(".")
		if dot_idx <= 0 or dot_idx >= body.length() - 1:
			return false
		var ext: String = body.substr(dot_idx + 1).to_lower()
		return ext in ALLOWED_ASSET_IMAGE_EXTENSIONS
	if clean.begins_with("res://"):
		if clean.contains(".."):
			return false
		var ext: String = clean.get_extension().to_lower()
		return ext in ALLOWED_RES_IMAGE_EXTENSIONS
	return false


func sanitize_sprite_path(path: String) -> Dictionary:
	var clean: String = sanitize_text(path).strip_edges()
	if is_valid_sprite_path(clean):
		return {"ok": true, "path": clean, "rejected": ""}
	return {"ok": false, "path": "", "rejected": clean}


func is_valid_asset_reference(ref_str: String) -> bool:
	var clean: String = sanitize_text(ref_str).strip_edges()
	if not clean.begins_with("asset://"):
		return false
	var regex := RegEx.new()
	if regex.compile("^asset://[0-9a-f]{64}\\.(png|jpg|jpeg|webp|bmp)$") != OK:
		return false
	return regex.search(clean) != null


func sanitize_cover_asset(ref_str: String) -> Dictionary:
	var clean: String = sanitize_text(ref_str).strip_edges()
	if clean.is_empty():
		return {"ok": true, "cover_asset": "", "sanitized": false}
	if is_valid_asset_reference(clean):
		return {"ok": true, "cover_asset": clean, "sanitized": false}
	return {
		"ok": false,
		"cover_asset": "",
		"sanitized": true,
		"reason": "invalid_cover_asset",
		"rejected": clean,
	}


func compute_source_to_world_scale(source_units_per_cell: float = DEFAULT_SOURCE_UNITS_PER_CELL) -> float:
	var safe_units: float = source_units_per_cell if is_finite(source_units_per_cell) else DEFAULT_SOURCE_UNITS_PER_CELL
	return WORLD_UNITS_PER_CELL / maxf(0.0001, safe_units)


func is_cancelled(host: RefCounted) -> bool:
	if host != null and host.has_method("cancelled"):
		return coerce_bool(host.cancelled(), false)
	return false


func report_progress(host: RefCounted, message: String) -> void:
	if host != null and host.has_method("report"):
		host.report(sanitize_text(message))


func add_warning(host: RefCounted, message: String) -> void:
	if host != null and host.has_method("warn"):
		host.warn(sanitize_text(message))


func archive_image(host: RefCounted, url: String, proxy: String = "") -> Dictionary:
	if url.is_empty():
		return {"ok": false, "reason": "empty_url", "reference": ""}
	if host != null and host.has_method("archive_image"):
		var raw_res: Variant = host.archive_image(url, proxy)
		if raw_res is Dictionary:
			return raw_res
		return {"ok": false, "reason": "invalid_archive_response", "reference": ""}
	return {"ok": false, "reason": "archive_image_unavailable", "reference": ""}


func inspect_source(host: RefCounted, path: String) -> Dictionary:
	if host != null and host.has_method("inspect_source"):
		var raw_res: Variant = host.inspect_source(path)
		if raw_res is Dictionary:
			return raw_res
		return {"ok": false, "reason": "invalid_inspect_source_response"}
	return {"ok": false, "reason": "inspect_source_unavailable"}


func decode_source(host: RefCounted, path: String) -> Dictionary:
	if host != null and host.has_method("decode_source"):
		var raw_res: Variant = host.decode_source(path)
		if raw_res is Dictionary:
			return raw_res
		return {"ok": false, "reason": "invalid_decode_source_response"}
	return {"ok": false, "reason": "decode_source_unavailable"}


func begin_preview(host: RefCounted, total_items: int, source_bounds: Rect2, source_to_world: float) -> void:
	if host != null and host.has_method("begin_preview"):
		var safe_scale: float = sanitize_finite_float(source_to_world, compute_source_to_world_scale())
		var safe_pos: Vector2 = sanitize_finite_vec2(source_bounds.position)
		var safe_size: Vector2 = sanitize_finite_vec2(source_bounds.size)
		var world_pos: Vector2 = sanitize_finite_vec2(safe_pos * safe_scale, Vector2.ZERO)
		var world_size: Vector2 = sanitize_finite_vec2(safe_size * safe_scale, Vector2.ZERO)
		var world_bounds := Rect2(world_pos, world_size)
		host.begin_preview(maxi(0, total_items), world_bounds)


func preview_entity(host: RefCounted, entity: Dictionary, preview_kind: String) -> void:
	if host != null and host.has_method("preview_entity"):
		host.preview_entity(entity, preview_kind)


func finish_geometry_preview(host: RefCounted) -> bool:
	if host != null and host.has_method("finish_geometry_preview"):
		return coerce_bool(host.finish_geometry_preview(), false)
	return true


func build_inspect_ok(
	source_path: String,
	counts_override: Dictionary = {},
	remote_assets: Dictionary = {},
	decoded_bytes: int = -1,
	display_name: String = ""
) -> Dictionary:
	var file_sha256: String = ""
	var source_bytes: int = 0
	if not source_path.is_empty() and FileAccess.file_exists(source_path):
		file_sha256 = FileAccess.get_sha256(source_path)
		var f: FileAccess = FileAccess.open(source_path, FileAccess.READ)
		if f != null:
			source_bytes = maxi(0, int(f.get_length()))
			f.close()

	var counts: Dictionary = DEFAULT_INSPECT_COUNTS.duplicate()
	for raw_key: Variant in counts_override.keys():
		if not (raw_key is String or raw_key is StringName):
			continue
		var key_name: String = str(raw_key)
		counts[key_name] = coerce_int(counts_override[raw_key], 0)

	var final_decoded_bytes: int = decoded_bytes if decoded_bytes >= 0 else source_bytes
	var unique_images: int = maxi(int(counts.get("images", 0)), remote_assets.size())
	var clean_name: String = sanitize_catalog_name(display_name, "")
	if clean_name.is_empty() and not source_path.is_empty():
		clean_name = sanitize_catalog_name(source_path.get_file().get_basename(), "")

	return {
		"ok": true,
		"name": clean_name,
		"sha256": file_sha256,
		"source_bytes": source_bytes,
		"decoded_bytes": final_decoded_bytes,
		"unique_images": unique_images,
		"counts": counts,
		"assets": remote_assets.duplicate(),
	}


func build_cancelled() -> Dictionary:
	return {"ok": false, "reason": "cancelled"}


func build_failed(reason: String) -> Dictionary:
	var cleaned: String = sanitize_text(reason)
	return {
		"ok": false,
		"reason": cleaned if not cleaned.is_empty() else "import_failed",
	}


func extract_default_world_targets(world: Dictionary) -> Dictionary:
	var catalog_var: Variant = world.get("catalog", {})
	if not (catalog_var is Dictionary):
		return build_failed("invalid_world_catalog")
	var catalog: Dictionary = catalog_var

	var layers_root_var: Variant = catalog.get("layers", {})
	if not (layers_root_var is Dictionary):
		return build_failed("invalid_world_layers")
	var layers_root: Dictionary = layers_root_var

	var schema_name: String = _as_string(layers_root.get("schema", ""))
	if schema_name != FLOOR_LAYERS_SCHEMA:
		return build_failed("请更新本地程序后使用此版场景结构导入。")

	var floors_var: Variant = layers_root.get("floors", [])
	if not (floors_var is Array) or (floors_var as Array).is_empty():
		return build_failed("missing_world_floors")
	var floors: Array = floors_var

	var floor_uid: String = _as_string(catalog.get("active_floor_uid", ""))
	var target_floor: Dictionary = {}
	for raw_floor: Variant in floors:
		if raw_floor is Dictionary:
			var floor_dict: Dictionary = raw_floor
			if not floor_uid.is_empty() and _as_string(floor_dict.get("floor_uid", "")) == floor_uid:
				target_floor = floor_dict
				break
	if target_floor.is_empty() and floors[0] is Dictionary:
		target_floor = floors[0]
		if floor_uid.is_empty():
			floor_uid = _as_string(target_floor.get("floor_uid", ""))
	if floor_uid.is_empty():
		return build_failed("missing_default_floor_uid")

	var layer_rows_var: Variant = target_floor.get("layers", [])
	if not (layer_rows_var is Array):
		return build_failed("invalid_floor_layers")

	var layer_map: Dictionary = {}
	for raw_layer: Variant in layer_rows_var as Array:
		if raw_layer is Dictionary:
			var layer_row: Dictionary = raw_layer
			var layer_kind: String = _as_string(layer_row.get("kind", ""))
			var layer_uid: String = _as_string(layer_row.get("layer_uid", ""))
			if not layer_kind.is_empty() and not layer_uid.is_empty() and not layer_map.has(layer_kind):
				layer_map[layer_kind] = layer_uid

	for required_kind: String in DEFAULT_LAYER_KINDS:
		if not layer_map.has(required_kind):
			return build_failed("missing_required_layer:" + required_kind)

	# 对齐 EntityStateCodec._valid_snapshot (entity_state_codec.gd:6,391-392)：
	# 兜底实体状态字典必须补齐 "version": 3。
	if not (world.get("entity_state", null) is Dictionary):
		world["entity_state"] = {"version": ENTITY_STATE_VERSION, "entities": []}
	else:
		var entity_state: Dictionary = world["entity_state"]
		if not (entity_state.get("version", null) is int):
			entity_state["version"] = ENTITY_STATE_VERSION
		if not (entity_state.get("entities", null) is Array):
			entity_state["entities"] = []

	if not (world.get("members", null) is Array):
		world["members"] = []

	# 对齐 WorldModuleState.empty() (world_module_state.gd:5,13)：
	# 兜底模块分区必须包含 "version": 2 与 "entries": {}。
	if not (world.get("modules", null) is Dictionary):
		world["modules"] = {"version": MODULE_STATE_VERSION, "entries": {}}
	else:
		var modules_dict: Dictionary = world["modules"]
		if not (modules_dict.get("version", null) is int):
			modules_dict["version"] = MODULE_STATE_VERSION
		if not (modules_dict.get("entries", null) is Dictionary):
			modules_dict["entries"] = {}

	return {
		"ok": true,
		"world": world,
		"floor_uid": floor_uid,
		"layers": layer_map,
	}


func init_empty_world(host: RefCounted) -> Dictionary:
	if host == null or not host.has_method("empty_world"):
		return build_failed("host_empty_world_unavailable")

	var raw_initial: Variant = host.empty_world()
	if not (raw_initial is Dictionary):
		return build_failed("invalid_empty_world_response")

	var initial: Dictionary = raw_initial
	if not coerce_bool(initial.get("ok", false), false):
		var err_out: Dictionary = initial.duplicate(false)
		err_out["ok"] = false
		var raw_reason: Variant = err_out.get("reason", null)
		if not (raw_reason is String or raw_reason is StringName) or str(raw_reason).is_empty():
			err_out["reason"] = "empty_world_failed"
		return err_out

	var raw_world: Variant = initial.get("data", {})
	if not (raw_world is Dictionary):
		return build_failed("missing_world_data")

	return extract_default_world_targets(raw_world as Dictionary)


func create_floor(
	world: Dictionary,
	floor_name: String,
	color: Color = DEFAULT_FLOOR_COLOR,
	floor_uid_override: String = ""
) -> Dictionary:
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return build_failed("invalid_world_catalog")
	var catalog: Dictionary = catalog_var

	var floors_var: Variant = catalog.get("floors", null)
	var layers_root_var: Variant = catalog.get("layers", null)
	if not (floors_var is Array) or not (layers_root_var is Dictionary):
		return build_failed("invalid_world_layers")
	var floors: Array = floors_var
	var layers_root: Dictionary = layers_root_var
	var layer_floors_var: Variant = layers_root.get("floors", null)
	if not (layer_floors_var is Array):
		return build_failed("invalid_layer_floors")
	var layer_floors: Array = layer_floors_var

	if floors.size() >= MAX_FLOORS:
		return build_failed("floor_limit_exceeded")
	if _count_total_layers(layer_floors) + DEFAULT_LAYER_KINDS.size() > MAX_TOTAL_LAYERS:
		return build_failed("layer_limit_exceeded")

	var existing_floor_uids: Dictionary = {}
	for raw_floor: Variant in floors:
		if raw_floor is Dictionary:
			var existing_fuid: String = _as_string((raw_floor as Dictionary).get("floor_uid", ""))
			if not existing_fuid.is_empty():
				existing_floor_uids[existing_fuid] = true

	var next_id: int = floors.size()
	var clean_name: String = sanitize_catalog_name(floor_name, "%dF" % (next_id + 1))
	var floor_uid: String = floor_uid_override.strip_edges().to_lower()
	if floor_uid.is_empty():
		var attempt: int = 0
		while true:
			var seed_text: String = "fu_sdk:floor:%d:%s:%d" % [next_id, clean_name, attempt]
			var candidate: String = seed_text.sha256_text().left(32)
			if not existing_floor_uids.has(candidate):
				floor_uid = candidate
				break
			attempt += 1
	elif not is_valid_uid(floor_uid) or existing_floor_uids.has(floor_uid):
		return build_failed("invalid_or_duplicate_floor_uid")

	var existing_layer_uids: Dictionary = _collect_layer_uids(layer_floors)
	var default_entity_uid: String = ("fus.layer.default.v1:" + floor_uid).sha256_text().left(32)
	var map_uid: String = ("fus.layer.map:" + floor_uid).sha256_text().left(32)
	var obstacle_uid: String = ("fus.layer.obstacle:" + floor_uid).sha256_text().left(32)
	for uid_check: String in [default_entity_uid, map_uid, obstacle_uid]:
		if existing_layer_uids.has(uid_check):
			return build_failed("duplicate_layer_uid")

	var floor_layers: Array = [
		{
			"layer_uid": map_uid,
			"name": "地图底图",
			"kind": "map",
			"visible": true,
			"locked": false,
			"persistent": true,
			"access": "all",
			"viewers": [],
		},
		{
			"layer_uid": default_entity_uid,
			"name": "实体",
			"kind": "entity",
			"visible": true,
			"locked": false,
			"persistent": true,
			"access": "all",
			"viewers": [],
		},
		{
			"layer_uid": obstacle_uid,
			"name": "障碍物",
			"kind": "obstacle",
			"visible": true,
			"locked": false,
			"persistent": true,
			"access": "host",
			"viewers": [],
		},
	]

	floors.append({
		"id": next_id,
		"floor_uid": floor_uid,
		"name": clean_name,
		"color": color,
	})
	layer_floors.append({
		"floor_uid": floor_uid,
		"default_layer_uid": default_entity_uid,
		"layers": floor_layers,
	})

	return {
		"ok": true,
		"id": next_id,
		"floor_uid": floor_uid,
		"name": clean_name,
		"layers": {
			"map": map_uid,
			"entity": default_entity_uid,
			"obstacle": obstacle_uid,
		},
	}


func set_active_floor(world: Dictionary, floor_uid: String) -> Dictionary:
	if floor_uid.is_empty():
		return build_failed("unknown_floor_uid")
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return build_failed("invalid_world_catalog")
	var catalog: Dictionary = catalog_var
	var floors_var: Variant = catalog.get("floors", null)
	if not (floors_var is Array):
		return build_failed("missing_world_floors")
	for raw_floor: Variant in floors_var as Array:
		if raw_floor is Dictionary and _as_string((raw_floor as Dictionary).get("floor_uid", "")) == floor_uid:
			catalog["active_floor_uid"] = floor_uid
			return {"ok": true, "floor_uid": floor_uid}
	return build_failed("unknown_floor_uid")


func rename_floor(world: Dictionary, floor_uid: String, new_name: String) -> Dictionary:
	if floor_uid.is_empty():
		return build_failed("unknown_floor_uid")
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return build_failed("invalid_world_catalog")
	var catalog: Dictionary = catalog_var
	var floors_var: Variant = catalog.get("floors", null)
	if not (floors_var is Array):
		return build_failed("missing_world_floors")

	var clean_name: String = sanitize_catalog_name(new_name, "1F")
	var found: bool = false
	for raw_floor: Variant in floors_var as Array:
		if raw_floor is Dictionary:
			var fd: Dictionary = raw_floor as Dictionary
			if _as_string(fd.get("floor_uid", "")) == floor_uid:
				fd["name"] = clean_name
				found = true
				break
	if not found:
		return build_failed("unknown_floor_uid")

	var layers_root_var: Variant = catalog.get("layers", null)
	if layers_root_var is Dictionary:
		var layer_floors_var: Variant = (layers_root_var as Dictionary).get("floors", null)
		if layer_floors_var is Array:
			for raw_lf: Variant in layer_floors_var as Array:
				if raw_lf is Dictionary:
					var lfd: Dictionary = raw_lf as Dictionary
					if _as_string(lfd.get("floor_uid", "")) == floor_uid and lfd.has("name"):
						lfd["name"] = clean_name
						break

	return {"ok": true, "floor_uid": floor_uid, "name": clean_name}


func get_floor_layer_map(world: Dictionary, floor_uid: String) -> Dictionary:
	if floor_uid.is_empty():
		return {}
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return {}
	var layers_root_var: Variant = (catalog_var as Dictionary).get("layers", null)
	if not (layers_root_var is Dictionary):
		return {}
	var layer_floors_var: Variant = (layers_root_var as Dictionary).get("floors", null)
	if not (layer_floors_var is Array):
		return {}
	for raw_floor: Variant in layer_floors_var as Array:
		if raw_floor is Dictionary and _as_string((raw_floor as Dictionary).get("floor_uid", "")) == floor_uid:
			var layer_map: Dictionary = {}
			var rows_var: Variant = (raw_floor as Dictionary).get("layers", [])
			if rows_var is Array:
				for raw_layer: Variant in rows_var as Array:
					if raw_layer is Dictionary:
						var layer_row: Dictionary = raw_layer
						var k: String = _as_string(layer_row.get("kind", ""))
						var uid: String = _as_string(layer_row.get("layer_uid", ""))
						if not k.is_empty() and not uid.is_empty() and not layer_map.has(k):
							layer_map[k] = uid
			return layer_map
	return {}


func get_floor_for_layer(world: Dictionary, layer_uid: String) -> String:
	if layer_uid.is_empty():
		return ""
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return ""
	var layers_root_var: Variant = (catalog_var as Dictionary).get("layers", null)
	if not (layers_root_var is Dictionary):
		return ""
	var layer_floors_var: Variant = (layers_root_var as Dictionary).get("floors", null)
	if not (layer_floors_var is Array):
		return ""
	for raw_floor: Variant in layer_floors_var as Array:
		if not (raw_floor is Dictionary):
			continue
		var floor_dict: Dictionary = raw_floor as Dictionary
		var fuid: String = _as_string(floor_dict.get("floor_uid", ""))
		var rows_var: Variant = floor_dict.get("layers", [])
		if rows_var is Array:
			for raw_layer: Variant in rows_var as Array:
				if raw_layer is Dictionary and _as_string((raw_layer as Dictionary).get("layer_uid", "")) == layer_uid:
					return fuid
	return ""


func get_floor_layers(world: Dictionary, floor_uid: String) -> Array:
	if floor_uid.is_empty():
		return []
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return []
	var layers_root_var: Variant = (catalog_var as Dictionary).get("layers", null)
	if not (layers_root_var is Dictionary):
		return []
	var layer_floors_var: Variant = (layers_root_var as Dictionary).get("floors", null)
	if not (layer_floors_var is Array):
		return []
	for raw_floor: Variant in layer_floors_var as Array:
		if raw_floor is Dictionary and _as_string((raw_floor as Dictionary).get("floor_uid", "")) == floor_uid:
			var rows_var: Variant = (raw_floor as Dictionary).get("layers", [])
			if rows_var is Array:
				var cloned_rows: Variant = _safe_clone_variant(rows_var, 0, [], [])
				return cloned_rows as Array if cloned_rows is Array else []
			return []
	return []


func has_scene_repository_state(world: Dictionary) -> bool:
	var st: Dictionary = _get_scene_box_state_read(world)
	if st.is_empty():
		return false
	var scenes_var: Variant = st.get("scenes", null)
	return scenes_var is Array and not (scenes_var as Array).is_empty()


func ensure_scene_repository_state(
	world: Dictionary,
	entry_name: String = "主场景",
	cover_asset: String = "",
	entry_uid_override: String = ""
) -> Dictionary:
	var floor_uids: Array[String] = _extract_world_floor_uids(world)
	if floor_uids.is_empty():
		return build_failed("empty_world_floors")

	var modules_dict: Dictionary = _ensure_world_modules_dict(world)
	var entries: Dictionary = modules_dict["entries"]
	var existing_state: Dictionary = _get_scene_box_state_read(world)

	if existing_state.is_empty() or not (existing_state.get("scenes", null) is Array) or (existing_state["scenes"] as Array).is_empty():
		var clean_name: String = sanitize_catalog_name(entry_name, "主场景")
		var cover_check: Dictionary = sanitize_cover_asset(cover_asset)
		var safe_cover: String = str(cover_check["cover_asset"])

		var entry_uid: String = entry_uid_override.strip_edges().to_lower()
		if entry_uid.is_empty():
			entry_uid = ("fu_sdk:scene:entry:%s:%s" % [floor_uids[0], clean_name]).sha256_text().left(32)
		elif not is_valid_uid(entry_uid):
			return build_failed("invalid_entry_scene_uid")

		var floor_list: Array = []
		for fuid: String in floor_uids:
			floor_list.append(fuid)

		var cat_var: Variant = world.get("catalog", null)
		var active_floor: String = _as_string((cat_var as Dictionary).get("active_floor_uid", "")) if cat_var is Dictionary else ""
		var default_floor: String = active_floor if active_floor in floor_list else str(floor_list[0])
		if active_floor.is_empty() and cat_var is Dictionary:
			(cat_var as Dictionary)["active_floor_uid"] = default_floor

		var state: Dictionary = {
			"schema_version": SCENE_BOX_SCHEMA_VERSION,
			"entry_scene_uid": entry_uid,
			"host_active_scene_uid": entry_uid,
			"scenes": [
				{
					"uid": entry_uid,
					"name": clean_name,
					"floor_uids": floor_list,
					"default_floor_uid": default_floor,
					"cover_asset": safe_cover,
				},
			],
			"visited_scenes": {
				"host": [entry_uid],
			},
			"host_return_stack": [],
			"host_views": {},
		}
		entries[SCENE_BOX_MODULE_ID] = {
			"version": SCENE_BOX_MODULE_VERSION,
			"state": state,
		}
		return {
			"ok": true,
			"entry_scene_uid": entry_uid,
			"host_active_scene_uid": entry_uid,
			"default_floor_uid": default_floor,
			"cover_sanitized": bool(cover_check["sanitized"]),
		}

	# 若已初始化，则仅将尚未归属任何场景的新增楼层纳入入口场景（对齐 SceneRepository.reconcile_floors）。
	var scenes: Array = existing_state["scenes"]
	var entry_uid_cur: String = _as_string(existing_state.get("entry_scene_uid", ""))
	var entry_row: Dictionary = _find_scene_row(scenes, entry_uid_cur)
	if entry_row.is_empty():
		if not (scenes[0] is Dictionary):
			return build_failed("invalid_scene_box_state")
		entry_row = scenes[0] as Dictionary
		entry_uid_cur = _as_string(entry_row.get("uid", ""))
		existing_state["entry_scene_uid"] = entry_uid_cur

	var claimed: Dictionary = {}
	for raw_scene: Variant in scenes:
		if raw_scene is Dictionary:
			var sf_var: Variant = (raw_scene as Dictionary).get("floor_uids", [])
			if sf_var is Array:
				for fv: Variant in sf_var as Array:
					var fuid_s: String = _as_string(fv)
					if not fuid_s.is_empty():
						claimed[fuid_s] = true

	var entry_floors_var: Variant = entry_row.get("floor_uids", [])
	var entry_floors: Array = entry_floors_var if entry_floors_var is Array else []
	entry_row["floor_uids"] = entry_floors
	for fuid: String in floor_uids:
		if not claimed.has(fuid):
			entry_floors.append(fuid)
			claimed[fuid] = true

	var active_scene_cur: String = _as_string(existing_state.get("host_active_scene_uid", ""))
	if _find_scene_row(scenes, active_scene_cur).is_empty():
		active_scene_cur = entry_uid_cur
		existing_state["host_active_scene_uid"] = active_scene_cur

	_mark_host_scene_visited(existing_state, entry_uid_cur)
	_mark_host_scene_visited(existing_state, active_scene_cur)
	var entry_def_floor: String = _as_string(entry_row.get("default_floor_uid", ""))
	if entry_def_floor.is_empty():
		entry_def_floor = floor_uids[0]
	return {
		"ok": true,
		"entry_scene_uid": entry_uid_cur,
		"host_active_scene_uid": active_scene_cur,
		"default_floor_uid": entry_def_floor,
		"cover_sanitized": false,
	}


func configure_entry_scene_state(
	world: Dictionary,
	entry_name: String = "主场景",
	cover_asset: String = "",
	entry_uid_override: String = ""
) -> Dictionary:
	var ensure_res: Dictionary = ensure_scene_repository_state(world, entry_name, cover_asset, entry_uid_override)
	if not bool(ensure_res.get("ok", false)):
		return ensure_res
	var state: Dictionary = _get_scene_box_state_read(world)
	var scenes_var: Variant = state.get("scenes", null)
	var scenes: Array = scenes_var if scenes_var is Array else []
	var entry_uid: String = _as_string(state.get("entry_scene_uid", ""))
	var row: Dictionary = _find_scene_row(scenes, entry_uid)
	var cover_sanitized: bool = bool(ensure_res.get("cover_sanitized", false))
	if not row.is_empty():
		var fb_name: String = _as_string(row.get("name", "主场景"), "主场景")
		if fb_name.is_empty():
			fb_name = "主场景"
		var clean_name: String = sanitize_catalog_name(entry_name, fb_name)
		row["name"] = clean_name
		if not cover_asset.is_empty():
			var cover_check: Dictionary = sanitize_cover_asset(cover_asset)
			row["cover_asset"] = str(cover_check["cover_asset"])
			cover_sanitized = cover_sanitized or bool(cover_check["sanitized"])
	var active_suid: String = _as_string(state.get("host_active_scene_uid", entry_uid), entry_uid)
	if active_suid.is_empty():
		active_suid = entry_uid
	return {
		"ok": true,
		"entry_scene_uid": entry_uid,
		"host_active_scene_uid": active_suid,
		"default_floor_uid": _as_string(row.get("default_floor_uid", "")) if not row.is_empty() else "",
		"cover_sanitized": cover_sanitized,
	}


func create_scene(
	world: Dictionary,
	scene_name: String,
	initial_floor_name: String = "1F",
	floor_color: Color = DEFAULT_SCENE_FLOOR_COLOR,
	cover_asset: String = "",
	make_active: bool = false,
	scene_uid_override: String = "",
	floor_uid_override: String = ""
) -> Dictionary:
	var ensure_res: Dictionary = ensure_scene_repository_state(world)
	if not bool(ensure_res.get("ok", false)):
		return ensure_res

	var state: Dictionary = _get_scene_box_state_read(world)
	var scenes_var: Variant = state.get("scenes", null)
	if not (scenes_var is Array):
		return build_failed("invalid_scene_box_state")
	var scenes: Array = scenes_var as Array
	if scenes.size() >= MAX_SCENES:
		return build_failed("scene_limit_exceeded")

	var existing_scene_uids: Dictionary = {}
	for raw_scene: Variant in scenes:
		if raw_scene is Dictionary:
			var existing_suid: String = _as_string((raw_scene as Dictionary).get("uid", ""))
			if not existing_suid.is_empty():
				existing_scene_uids[existing_suid] = true

	var clean_scene_name: String = sanitize_catalog_name(scene_name, "场景 %d" % (scenes.size() + 1))
	var explicit_uid: String = scene_uid_override.strip_edges().to_lower()
	if not explicit_uid.is_empty() and (not is_valid_uid(explicit_uid) or existing_scene_uids.has(explicit_uid)):
		return build_failed("invalid_or_duplicate_scene_uid")

	var floor_res: Dictionary = create_floor(world, initial_floor_name, floor_color, floor_uid_override)
	if not bool(floor_res.get("ok", false)):
		return floor_res

	var floor_uid: String = str(floor_res["floor_uid"])
	var scene_uid: String = explicit_uid
	if scene_uid.is_empty():
		var attempt: int = 0
		while true:
			var seed_text: String = "fu_sdk:scene:%s:%s:%d:%d" % [floor_uid, clean_scene_name, scenes.size(), attempt]
			var candidate: String = seed_text.sha256_text().left(32)
			if not existing_scene_uids.has(candidate):
				scene_uid = candidate
				break
			attempt += 1

	var cover_check: Dictionary = sanitize_cover_asset(cover_asset)
	var safe_cover: String = str(cover_check["cover_asset"])
	scenes.append({
		"uid": scene_uid,
		"name": clean_scene_name,
		"floor_uids": [floor_uid],
		"default_floor_uid": floor_uid,
		"cover_asset": safe_cover,
	})

	if make_active:
		var act_res: Dictionary = set_active_scene(world, scene_uid, floor_uid, true)
		if not bool(act_res.get("ok", false)):
			return act_res

	var floor_layers: Dictionary = (floor_res["layers"] as Dictionary).duplicate()
	return {
		"ok": true,
		"scene_uid": scene_uid,
		"floor_uid": floor_uid,
		"name": clean_scene_name,
		"layers": floor_layers,
		"layers_by_kind": floor_layers,
		"cover_sanitized": bool(cover_check["sanitized"]),
	}


func add_floor_to_scene(
	world: Dictionary,
	scene_uid: String,
	floor_name: String,
	color: Color = DEFAULT_FLOOR_COLOR,
	make_default: bool = false,
	make_active: bool = false,
	floor_uid_override: String = ""
) -> Dictionary:
	if not has_scene_repository_state(world):
		return build_failed("scene_repository_not_initialized")
	var state: Dictionary = _get_scene_box_state_read(world)
	var scenes_var: Variant = state.get("scenes", null)
	var scenes: Array = scenes_var if scenes_var is Array else []
	var row: Dictionary = _find_scene_row(scenes, scene_uid)
	if row.is_empty():
		return build_failed("unknown_scene_uid")

	var floor_res: Dictionary = create_floor(world, floor_name, color, floor_uid_override)
	if not bool(floor_res.get("ok", false)):
		return floor_res

	var floor_uid: String = str(floor_res["floor_uid"])
	var floor_list_var: Variant = row.get("floor_uids", null)
	var floor_list: Array = floor_list_var if floor_list_var is Array else []
	if not (floor_list_var is Array):
		row["floor_uids"] = floor_list
	if not (floor_uid in floor_list):
		floor_list.append(floor_uid)
	if make_default or _as_string(row.get("default_floor_uid", "")).is_empty():
		row["default_floor_uid"] = floor_uid

	if make_active:
		var act_res: Dictionary = set_active_scene(world, scene_uid, floor_uid, true)
		if not bool(act_res.get("ok", false)):
			return act_res

	var floor_layers: Dictionary = (floor_res["layers"] as Dictionary).duplicate()
	return {
		"ok": true,
		"scene_uid": scene_uid,
		"floor_uid": floor_uid,
		"name": str(floor_res["name"]),
		"layers": floor_layers,
		"layers_by_kind": floor_layers,
	}


func attach_existing_floor_to_scene(
	world: Dictionary,
	scene_uid: String,
	floor_uid: String,
	make_default: bool = false
) -> Dictionary:
	if not has_scene_repository_state(world):
		return build_failed("scene_repository_not_initialized")
	if not is_valid_uid(floor_uid) or not (floor_uid in _extract_world_floor_uids(world)):
		return build_failed("unknown_floor_uid")

	var state: Dictionary = _get_scene_box_state_read(world)
	var scenes_var: Variant = state.get("scenes", null)
	var scenes: Array = scenes_var if scenes_var is Array else []
	var target_row: Dictionary = _find_scene_row(scenes, scene_uid)
	if target_row.is_empty():
		return build_failed("unknown_scene_uid")

	var prev_owner_uid: String = get_scene_for_floor(world, floor_uid)
	if prev_owner_uid == scene_uid:
		if make_default:
			target_row["default_floor_uid"] = floor_uid
		return {"ok": true, "scene_uid": scene_uid, "floor_uid": floor_uid, "moved": false}

	if not prev_owner_uid.is_empty():
		var prev_row: Dictionary = _find_scene_row(scenes, prev_owner_uid)
		if not prev_row.is_empty():
			var prev_floors_var: Variant = prev_row.get("floor_uids", null)
			var prev_floors: Array = prev_floors_var if prev_floors_var is Array else []
			if prev_floors.size() <= 1:
				return build_failed("cannot_empty_source_scene")
			prev_floors.erase(floor_uid)
			if _as_string(prev_row.get("default_floor_uid", "")) == floor_uid:
				prev_row["default_floor_uid"] = _as_string(prev_floors[0])
			var views_var: Variant = state.get("host_views", null)
			if views_var is Dictionary and (views_var as Dictionary).has(prev_owner_uid):
				var vrow_var: Variant = (views_var as Dictionary)[prev_owner_uid]
				if vrow_var is Dictionary and _as_string((vrow_var as Dictionary).get("active_floor_uid", "")) == floor_uid:
					(vrow_var as Dictionary)["active_floor_uid"] = _as_string(prev_row.get("default_floor_uid", ""))

	var target_floors_var: Variant = target_row.get("floor_uids", null)
	var target_floors: Array = target_floors_var if target_floors_var is Array else []
	if not (target_floors_var is Array):
		target_row["floor_uids"] = target_floors
	if not (floor_uid in target_floors):
		target_floors.append(floor_uid)
	if make_default or _as_string(target_row.get("default_floor_uid", "")).is_empty():
		target_row["default_floor_uid"] = floor_uid

	var cat_cur_var: Variant = world.get("catalog", null)
	var cur_active_floor: String = _as_string((cat_cur_var as Dictionary).get("active_floor_uid", "")) if cat_cur_var is Dictionary else ""
	if cur_active_floor == floor_uid:
		state["host_active_scene_uid"] = scene_uid
		_mark_host_scene_visited(state, scene_uid)

	return {"ok": true, "scene_uid": scene_uid, "floor_uid": floor_uid, "moved": true}


func set_active_scene(
	world: Dictionary,
	scene_uid: String,
	floor_uid: String = "",
	mark_host_visited: bool = true
) -> Dictionary:
	if not has_scene_repository_state(world):
		return build_failed("scene_repository_not_initialized")
	var state: Dictionary = _get_scene_box_state_read(world)
	var scenes_var: Variant = state.get("scenes", null)
	var scenes: Array = scenes_var if scenes_var is Array else []
	var row: Dictionary = _find_scene_row(scenes, scene_uid)
	if row.is_empty():
		return build_failed("unknown_scene_uid")

	var scene_floors_var: Variant = row.get("floor_uids", null)
	var scene_floors: Array = scene_floors_var if scene_floors_var is Array else []
	if scene_floors.is_empty():
		return build_failed("empty_scene_floors")

	var target_floor: String = floor_uid.strip_edges()
	if target_floor.is_empty():
		target_floor = _as_string(row.get("default_floor_uid", ""))
		if target_floor.is_empty() or not (target_floor in scene_floors):
			target_floor = _as_string(scene_floors[0])
	elif not (target_floor in scene_floors):
		return build_failed("floor_not_in_scene")

	var floor_set_res: Dictionary = set_active_floor(world, target_floor)
	if not bool(floor_set_res.get("ok", false)):
		return floor_set_res

	state["host_active_scene_uid"] = scene_uid
	if mark_host_visited:
		_mark_host_scene_visited(state, scene_uid)

	return {"ok": true, "scene_uid": scene_uid, "floor_uid": target_floor}


func set_entry_scene(world: Dictionary, scene_uid: String) -> Dictionary:
	if not has_scene_repository_state(world):
		return build_failed("scene_repository_not_initialized")
	var state: Dictionary = _get_scene_box_state_read(world)
	var scenes_var: Variant = state.get("scenes", null)
	var scenes: Array = scenes_var if scenes_var is Array else []
	if _find_scene_row(scenes, scene_uid).is_empty():
		return build_failed("unknown_scene_uid")
	state["entry_scene_uid"] = scene_uid
	_mark_host_scene_visited(state, scene_uid)
	return {"ok": true, "entry_scene_uid": scene_uid}


func rename_scene(world: Dictionary, scene_uid: String, new_name: String) -> Dictionary:
	if not has_scene_repository_state(world):
		return build_failed("scene_repository_not_initialized")
	var state: Dictionary = _get_scene_box_state_read(world)
	var row: Dictionary = _find_scene_row(state.get("scenes", []), scene_uid)
	if row.is_empty():
		return build_failed("unknown_scene_uid")
	var fb_name: String = _as_string(row.get("name", "场景"), "场景")
	if fb_name.is_empty():
		fb_name = "场景"
	var clean_name: String = sanitize_catalog_name(new_name, fb_name)
	row["name"] = clean_name
	return {"ok": true, "scene_uid": scene_uid, "name": clean_name}


func set_scene_default_floor(world: Dictionary, scene_uid: String, floor_uid: String) -> Dictionary:
	if not has_scene_repository_state(world):
		return build_failed("scene_repository_not_initialized")
	var state: Dictionary = _get_scene_box_state_read(world)
	var row: Dictionary = _find_scene_row(state.get("scenes", []), scene_uid)
	if row.is_empty():
		return build_failed("unknown_scene_uid")
	var flist_var: Variant = row.get("floor_uids", null)
	var flist: Array = flist_var if flist_var is Array else []
	if not (floor_uid in flist):
		return build_failed("floor_not_in_scene")
	row["default_floor_uid"] = floor_uid
	return {"ok": true, "scene_uid": scene_uid, "default_floor_uid": floor_uid}


func set_scene_cover_asset(world: Dictionary, scene_uid: String, cover_asset: String) -> Dictionary:
	if not has_scene_repository_state(world):
		return build_failed("scene_repository_not_initialized")
	var state: Dictionary = _get_scene_box_state_read(world)
	var row: Dictionary = _find_scene_row(state.get("scenes", []), scene_uid)
	if row.is_empty():
		return build_failed("unknown_scene_uid")
	var cover_check: Dictionary = sanitize_cover_asset(cover_asset)
	var safe_cover: String = str(cover_check["cover_asset"])
	row["cover_asset"] = safe_cover
	return {
		"ok": true,
		"scene_uid": scene_uid,
		"cover_asset": safe_cover,
		"cover_sanitized": bool(cover_check["sanitized"]),
	}


func set_scene_host_view(
	world: Dictionary,
	scene_uid: String,
	camera_pos: Vector2,
	camera_zoom: Vector2 = Vector2.ONE,
	active_floor_uid: String = ""
) -> Dictionary:
	if not has_scene_repository_state(world):
		return build_failed("scene_repository_not_initialized")
	var state: Dictionary = _get_scene_box_state_read(world)
	var row: Dictionary = _find_scene_row(state.get("scenes", []), scene_uid)
	if row.is_empty():
		return build_failed("unknown_scene_uid")
	if not is_finite(camera_pos.x) or not is_finite(camera_pos.y):
		return build_failed("invalid_camera_pos")
	if not is_finite(camera_zoom.x) or not is_finite(camera_zoom.y) or camera_zoom.x <= 0.0 or camera_zoom.y <= 0.0:
		return build_failed("invalid_camera_zoom")

	var view_dict: Dictionary = {
		"camera_pos": camera_pos,
		"camera_zoom": camera_zoom,
	}
	var clean_af: String = active_floor_uid.strip_edges()
	if not clean_af.is_empty():
		var flist_var: Variant = row.get("floor_uids", null)
		var flist: Array = flist_var if flist_var is Array else []
		if not (clean_af in flist):
			return build_failed("floor_not_in_scene")
		view_dict["active_floor_uid"] = clean_af

	if not (state.get("host_views", null) is Dictionary):
		state["host_views"] = {}
	(state["host_views"] as Dictionary)[scene_uid] = view_dict
	return {"ok": true, "scene_uid": scene_uid}


func get_scene_uids(world: Dictionary) -> Array[String]:
	var out: Array[String] = []
	var state: Dictionary = _get_scene_box_state_read(world)
	var scenes_var: Variant = state.get("scenes", [])
	if scenes_var is Array:
		for raw_scene: Variant in scenes_var as Array:
			if raw_scene is Dictionary:
				var suid: String = _as_string((raw_scene as Dictionary).get("uid", ""))
				if not suid.is_empty():
					out.append(suid)
	return out


func get_entry_scene_uid(world: Dictionary) -> String:
	var state: Dictionary = _get_scene_box_state_read(world)
	return _as_string(state.get("entry_scene_uid", ""))


func get_active_scene_uid(world: Dictionary) -> String:
	var state: Dictionary = _get_scene_box_state_read(world)
	return _as_string(state.get("host_active_scene_uid", ""))


func get_scene_floors(world: Dictionary, scene_uid: String) -> Array[String]:
	var out: Array[String] = []
	var state: Dictionary = _get_scene_box_state_read(world)
	var row: Dictionary = _find_scene_row(state.get("scenes", []), scene_uid)
	if not row.is_empty():
		var flist_var: Variant = row.get("floor_uids", [])
		if flist_var is Array:
			for fv: Variant in flist_var as Array:
				var fuid: String = _as_string(fv)
				if not fuid.is_empty():
					out.append(fuid)
	return out


func get_scene_default_floor_uid(world: Dictionary, scene_uid: String) -> String:
	var state: Dictionary = _get_scene_box_state_read(world)
	var row: Dictionary = _find_scene_row(state.get("scenes", []), scene_uid)
	if row.is_empty():
		return ""
	var def_f: String = _as_string(row.get("default_floor_uid", ""))
	var flist_var: Variant = row.get("floor_uids", null)
	var flist: Array = flist_var if flist_var is Array else []
	if not def_f.is_empty() and def_f in flist:
		return def_f
	return _as_string(flist[0]) if not flist.is_empty() else ""


func get_scene_for_floor(world: Dictionary, floor_uid: String) -> String:
	if floor_uid.is_empty():
		return ""
	var state: Dictionary = _get_scene_box_state_read(world)
	var scenes_var: Variant = state.get("scenes", [])
	if scenes_var is Array:
		for raw_scene: Variant in scenes_var as Array:
			if raw_scene is Dictionary:
				var row: Dictionary = raw_scene as Dictionary
				var flist_var: Variant = row.get("floor_uids", [])
				if flist_var is Array and floor_uid in (flist_var as Array):
					return _as_string(row.get("uid", ""))
	return ""


func get_scene_record(world: Dictionary, scene_uid: String) -> Dictionary:
	var state: Dictionary = _get_scene_box_state_read(world)
	var row: Dictionary = _find_scene_row(state.get("scenes", []), scene_uid)
	return _safe_clone_dict(row) if not row.is_empty() else {}


func _ensure_world_modules_dict(world: Dictionary) -> Dictionary:
	if not (world.get("modules", null) is Dictionary):
		world["modules"] = {"version": MODULE_STATE_VERSION, "entries": {}}
	var modules_dict: Dictionary = world["modules"]
	if not (modules_dict.get("version", null) is int):
		modules_dict["version"] = MODULE_STATE_VERSION
	if not (modules_dict.get("entries", null) is Dictionary):
		modules_dict["entries"] = {}
	return modules_dict


func _get_scene_box_state_read(world: Dictionary) -> Dictionary:
	var mods_var: Variant = world.get("modules", null)
	if not (mods_var is Dictionary):
		return {}
	var entries_var: Variant = (mods_var as Dictionary).get("entries", null)
	if not (entries_var is Dictionary):
		return {}
	var entry_var: Variant = (entries_var as Dictionary).get(SCENE_BOX_MODULE_ID, null)
	if not (entry_var is Dictionary):
		return {}
	var state_var: Variant = (entry_var as Dictionary).get("state", null)
	return state_var as Dictionary if state_var is Dictionary else {}


func _extract_world_floor_uids(world: Dictionary) -> Array[String]:
	var out: Array[String] = []
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return out
	var floors_var: Variant = (catalog_var as Dictionary).get("floors", null)
	if not (floors_var is Array):
		return out
	for raw_floor: Variant in floors_var as Array:
		if raw_floor is Dictionary:
			var fuid: String = _as_string((raw_floor as Dictionary).get("floor_uid", ""))
			if is_valid_uid(fuid) and not (fuid in out):
				out.append(fuid)
	return out


func _find_scene_row(scenes_var: Variant, scene_uid: String) -> Dictionary:
	if scene_uid.is_empty() or not (scenes_var is Array):
		return {}
	for raw_scene: Variant in scenes_var as Array:
		if raw_scene is Dictionary and _as_string((raw_scene as Dictionary).get("uid", "")) == scene_uid:
			return raw_scene as Dictionary
	return {}


func _mark_host_scene_visited(state: Dictionary, scene_uid: String) -> void:
	if scene_uid.is_empty():
		return
	if not (state.get("visited_scenes", null) is Dictionary):
		state["visited_scenes"] = {}
	var visited_dict: Dictionary = state["visited_scenes"]
	if not (visited_dict.get("host", null) is Array):
		visited_dict["host"] = []
	var host_list: Array = visited_dict["host"]
	if not (scene_uid in host_list) and host_list.size() < MAX_SCENES:
		host_list.append(scene_uid)


func create_layer(
	world: Dictionary,
	floor_uid: String,
	layer_name: String,
	kind: String = "entity",
	access: String = "all",
	viewers: Array = [],
	locked: bool = false,
	visible: bool = true,
	persistent: bool = true
) -> Dictionary:
	var normalized_kind: String = kind.strip_edges().to_lower()
	if not (normalized_kind in LAYER_KINDS):
		return build_failed("unknown_layer_kind:" + kind)
	var normalized_access: String = access.strip_edges().to_lower()
	if not (normalized_access in LAYER_ACCESS_POLICIES):
		return build_failed("unknown_layer_access:" + access)

	var clean_viewers: Array = []
	var seen_viewers: Dictionary = {}
	for raw_viewer: Variant in viewers:
		if not (raw_viewer is String):
			continue
		var viewer_key: String = sanitize_viewer_key(raw_viewer as String, MAX_VIEWER_KEY_LENGTH)
		if viewer_key.is_empty() or seen_viewers.has(viewer_key):
			continue
		seen_viewers[viewer_key] = true
		clean_viewers.append(viewer_key)
		if clean_viewers.size() >= MAX_SELECTED_VIEWERS:
			break
	clean_viewers.sort()

	if (normalized_access == "players") != (not clean_viewers.is_empty()):
		return build_failed("invalid_layer_viewers_for_access")

	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return build_failed("invalid_world_catalog")
	var layers_root_var: Variant = (catalog_var as Dictionary).get("layers", null)
	if not (layers_root_var is Dictionary):
		return build_failed("invalid_world_layers")
	var layer_floors_var: Variant = (layers_root_var as Dictionary).get("floors", null)
	if not (layer_floors_var is Array):
		return build_failed("invalid_layer_floors")
	var layer_floors: Array = layer_floors_var

	if _count_total_layers(layer_floors) >= MAX_TOTAL_LAYERS:
		return build_failed("layer_limit_exceeded")

	var target_floor: Dictionary = {}
	for raw_floor: Variant in layer_floors:
		if raw_floor is Dictionary and _as_string((raw_floor as Dictionary).get("floor_uid", "")) == floor_uid:
			target_floor = raw_floor
			break
	if target_floor.is_empty():
		return build_failed("unknown_floor_uid")

	var rows_var: Variant = target_floor.get("layers", null)
	if not (rows_var is Array):
		return build_failed("invalid_floor_layers")
	var rows: Array = rows_var
	if rows.size() >= MAX_LAYERS_PER_FLOOR:
		return build_failed("floor_layer_limit_exceeded")

	var clean_name: String = sanitize_catalog_name(layer_name, "图层")
	var existing_uids: Dictionary = _collect_layer_uids(layer_floors)
	var layer_uid: String = ""
	var attempt: int = 0
	while true:
		var seed_text: String = "fu_sdk:layer:%s:%s:%s:%d:%d" % [floor_uid, normalized_kind, clean_name, rows.size(), attempt]
		var candidate: String = seed_text.sha256_text().left(32)
		if not existing_uids.has(candidate):
			layer_uid = candidate
			break
		attempt += 1

	rows.append({
		"layer_uid": layer_uid,
		"name": clean_name,
		"kind": normalized_kind,
		"visible": visible,
		"locked": locked,
		"persistent": persistent,
		"access": normalized_access,
		"viewers": clean_viewers,
	})

	return {
		"ok": true,
		"layer_uid": layer_uid,
		"floor_uid": floor_uid,
		"kind": normalized_kind,
		"name": clean_name,
	}


func make_vector_drawing(source_meta: Dictionary = {}) -> Dictionary:
	return {
		"schema": 1,
		"vertices": PackedVector2Array(),
		"paths": [],
		"color": Color.TRANSPARENT,
		"line_color": DEFAULT_LINE_COLOR,
		"text": "",
		"font_size": 24.0,
		"source": _safe_clone_dict(source_meta),
	}


func make_sprite_visual(
	sprite_ref: String,
	fallback_color: Color = DEFAULT_SPRITE_FALLBACK_COLOR,
	source_info: Dictionary = {}
) -> Dictionary:
	var checked: Dictionary = sanitize_sprite_path(sprite_ref)
	return {
		"enabled": true,
		"show_fallback": true,
		"fallback_color": fallback_color,
		"sprite_path": str(checked["path"]),
		"source_info": _safe_clone_dict(source_info),
	}


func make_text_visual(text: String, font_size: float = 24.0) -> Dictionary:
	var drawing: Dictionary = make_vector_drawing({})
	drawing["text"] = sanitize_text(text).left(MAX_VECTOR_TEXT_LENGTH)
	drawing["font_size"] = clampf(sanitize_finite_float(font_size, 24.0), MIN_FONT_SIZE, MAX_FONT_SIZE)
	return {
		"enabled": true,
		"show_fallback": true,
		"fallback_color": DEFAULT_SPRITE_FALLBACK_COLOR,
		"sprite_path": "",
		"source_info": {},
		"vector_drawing": drawing,
	}


func extrude_segment_to_quad(
	p0: Vector2,
	p1: Vector2,
	half_width: float = 6.0,
	min_length: float = 0.5
) -> PackedVector2Array:
	if (
		not is_finite(p0.x)
		or not is_finite(p0.y)
		or not is_finite(p1.x)
		or not is_finite(p1.y)
		or not is_finite(half_width)
		or not is_finite(min_length)
	):
		return PackedVector2Array()
	var half_w: float = maxf(0.5, half_width)
	var min_len: float = maxf(1e-6, min_length)
	var seg: Vector2 = p1 - p0
	if not is_finite(seg.x) or not is_finite(seg.y):
		return PackedVector2Array()
	var seg_len: float = seg.length()
	if not is_finite(seg_len) or seg_len < min_len or is_zero_approx(seg_len):
		return PackedVector2Array()
	var dir: Vector2 = seg / seg_len
	if not is_finite(dir.x) or not is_finite(dir.y) or dir.length_squared() < 0.5:
		return PackedVector2Array()
	var n: Vector2 = Vector2(-dir.y, dir.x) * half_w
	if not is_finite(n.x) or not is_finite(n.y):
		return PackedVector2Array()
	var q0: Vector2 = p0 + n
	var q1: Vector2 = p1 + n
	var q2: Vector2 = p1 - n
	var q3: Vector2 = p0 - n
	if (
		not is_finite(q0.x) or not is_finite(q0.y)
		or not is_finite(q1.x) or not is_finite(q1.y)
		or not is_finite(q2.x) or not is_finite(q2.y)
		or not is_finite(q3.x) or not is_finite(q3.y)
	):
		return PackedVector2Array()
	if q0 == q1 or q1 == q2 or q2 == q3 or q3 == q0 or q0 == q2 or q1 == q3:
		return PackedVector2Array()
	# 平移等价鞋带面积校验（防御大坐标 float32 ULP 坍缩导致的零面积退化）
	var area: float = absf((q1 - q0).cross(q2 - q0) + (q2 - q0).cross(q3 - q0)) * 0.5
	if not is_finite(area) or area <= 1e-6:
		return PackedVector2Array()
	return PackedVector2Array([q0, q1, q2, q3])


func make_polygon_obstacle_visual(
	polygons_src: Array,
	kind: String = "wall",
	is_open_door: bool = false,
	enabled: bool = true
) -> Dictionary:
	var normalized_kind: String = kind.strip_edges().to_lower()
	if not (normalized_kind in OBSTACLE_KINDS):
		normalized_kind = "wall"

	var source_meta: Dictionary = {
		"kind": normalized_kind,
		"enabled": enabled,
	}
	if normalized_kind in ["door", "window"]:
		source_meta["open"] = is_open_door

	var drawing: Dictionary = make_vector_drawing(source_meta)
	var obstacle_color: Color = _preview_color_for_obstacle(normalized_kind, is_open_door)
	if normalized_kind == "wall":
		drawing["line_color"] = DEFAULT_LINE_COLOR
		drawing["color"] = DEFAULT_WALL_COLOR
	else:
		drawing["line_color"] = obstacle_color
		drawing["color"] = obstacle_color

	var faces: Array = []
	var all_rings: Array = []
	var skipped_rings: int = 0

	for raw_poly: Variant in polygons_src:
		if raw_poly is Dictionary:
			var face_dict: Dictionary = raw_poly
			var outer_pts: Array = _extract_vec2_ring(face_dict.get("outer", []))
			if not _is_valid_polygon_ring_pts(outer_pts):
				skipped_rings += 1
				continue
			var valid_holes: Array = []
			var holes_var: Variant = face_dict.get("holes", [])
			if holes_var is Array:
				for raw_hole: Variant in holes_var as Array:
					var hole_pts: Array = _extract_vec2_ring(raw_hole)
					if not _is_valid_polygon_ring_pts(hole_pts):
						skipped_rings += 1
						continue
					valid_holes.append(hole_pts)
					all_rings.append(hole_pts)
			all_rings.append(outer_pts)
			faces.append({"outer": outer_pts, "holes": valid_holes})
		else:
			var ring_pts: Array = _extract_vec2_ring(raw_poly)
			if not _is_valid_polygon_ring_pts(ring_pts):
				skipped_rings += 1
				continue
			all_rings.append(ring_pts)
			faces.append({"outer": ring_pts, "holes": []})

	var size: Vector2 = MIN_ENTITY_SIZE
	for raw_ring: Variant in all_rings:
		var pts_list: Array = raw_ring
		for raw_pt: Variant in pts_list:
			var pt: Vector2 = raw_pt
			var doubled: Vector2 = Vector2(absf(pt.x), absf(pt.y)) * 2.0
			if not is_finite(doubled.x) or not is_finite(doubled.y):
				size = Vector2(INF, INF)
				break
			size = size.max(doubled)
		if not is_finite(size.x) or not is_finite(size.y):
			break

	if not is_finite(size.x) or not is_finite(size.y):
		faces.clear()
		all_rings.clear()
		size = MIN_ENTITY_SIZE

	var paths_arr: Array = drawing["paths"]
	var vertices_arr: PackedVector2Array = drawing["vertices"]
	var total_points: int = 0
	var truncated: bool = false

	# 1. 先按配额写入归一化路径（每个环点数均 >= 3，满足 ObstacleShapes.valid_paths）
	for raw_face: Variant in faces:
		var face: Dictionary = raw_face
		var face_rings: Array = [face["outer"]]
		face_rings.append_array(face["holes"] as Array)
		for raw_ring: Variant in face_rings:
			var pts_list: Array = raw_ring
			if paths_arr.size() >= MAX_VECTOR_PATHS or total_points + pts_list.size() > MAX_VECTOR_TOTAL_POINTS:
				truncated = true
				break
			var normalized_ring := _normalize_ring(pts_list, size)
			paths_arr.append(normalized_ring)
			total_points += normalized_ring.size()
		if truncated:
			break

	# 2. 三角剖分：存在内孔时先通过 Geometry2D.clip_polygons（内孔自动切分）扣除内孔再剖分
	for raw_face: Variant in faces:
		var face: Dictionary = raw_face
		var normalized_outer: PackedVector2Array = _normalize_ring(face["outer"] as Array, size)
		var normalized_holes: Array = []
		for raw_hole: Variant in face["holes"] as Array:
			normalized_holes.append(_normalize_ring(raw_hole as Array, size))

		var simple_pieces: Array = _subtract_holes_for_triangulation(normalized_outer, normalized_holes)
		for raw_piece: Variant in simple_pieces:
			var piece: PackedVector2Array = raw_piece
			if piece.size() < 3:
				continue
			var tri_indices: PackedInt32Array = Geometry2D.triangulate_polygon(piece)
			if tri_indices.is_empty() or tri_indices.size() % 3 != 0:
				continue
			var tri_count: int = tri_indices.size() / 3
			for t: int in tri_count:
				if vertices_arr.size() + 3 > MAX_VECTOR_VERTICES or total_points + 3 > MAX_VECTOR_TOTAL_POINTS:
					truncated = true
					break
				vertices_arr.append(piece[tri_indices[t * 3]])
				vertices_arr.append(piece[tri_indices[t * 3 + 1]])
				vertices_arr.append(piece[tri_indices[t * 3 + 2]])
				total_points += 3
			if truncated:
				break
		if truncated:
			break

	drawing["vertices"] = vertices_arr
	return {
		"size": size,
		"skipped_rings": skipped_rings,
		"valid_face_count": faces.size(),
		"truncated": truncated,
		"visual": {
			"enabled": true,
			"show_fallback": false,
			"vector_drawing": drawing,
		},
	}


func make_custom_drawing_visual(
	size_src: Vector2,
	paths_local: Array,
	fill_color: Color = Color.TRANSPARENT,
	line_color: Color = DEFAULT_LINE_COLOR
) -> Dictionary:
	var safe_size: Vector2 = sanitize_finite_vec2(size_src, MIN_ENTITY_SIZE)
	var clamped_size := Vector2(maxf(MIN_ENTITY_SIZE.x, safe_size.x), maxf(MIN_ENTITY_SIZE.y, safe_size.y))
	var drawing: Dictionary = make_vector_drawing({})
	drawing["color"] = fill_color
	drawing["line_color"] = line_color

	var paths_arr: Array = drawing["paths"]
	var vertices_arr: PackedVector2Array = drawing["vertices"]
	var total_points: int = 0

	for raw_path: Variant in paths_local:
		var pts: Array = _extract_vec2_ring(raw_path)
		if pts.is_empty():
			continue
		if paths_arr.size() >= MAX_VECTOR_PATHS or total_points + pts.size() > MAX_VECTOR_TOTAL_POINTS:
			break
		var normalized_ring := _normalize_ring(pts, clamped_size)
		paths_arr.append(normalized_ring)
		total_points += normalized_ring.size()
		if fill_color.a > 0.0 and normalized_ring.size() >= 3:
			var tri_indices: PackedInt32Array = Geometry2D.triangulate_polygon(normalized_ring)
			if tri_indices.size() >= 3 and tri_indices.size() % 3 == 0:
				var tri_count: int = tri_indices.size() / 3
				for t: int in tri_count:
					if vertices_arr.size() + 3 > MAX_VECTOR_VERTICES or total_points + 3 > MAX_VECTOR_TOTAL_POINTS:
						break
					vertices_arr.append(normalized_ring[tri_indices[t * 3]])
					vertices_arr.append(normalized_ring[tri_indices[t * 3 + 1]])
					vertices_arr.append(normalized_ring[tri_indices[t * 3 + 2]])
					total_points += 3

	drawing["vertices"] = vertices_arr
	return {
		"enabled": true,
		"show_fallback": true,
		"fallback_color": DEFAULT_SPRITE_FALLBACK_COLOR,
		"sprite_path": "",
		"source_info": {},
		"vector_drawing": drawing,
	}


func make_permission_state(
	owners_csv: String = "",
	owner_player_ids: Array = [],
	all_players_can_operate: bool = false,
	gm_can_operate: bool = true
) -> Dictionary:
	var val_u: Variant = _validation_utils()
	var ids := PackedStringArray()
	var seen: Dictionary = {}
	for raw_id: Variant in owner_player_ids:
		if not (raw_id is String or raw_id is StringName):
			continue
		var clean_id: String = _strip_bom_and_edges(str(val_u.strip_nul(str(raw_id))))
		if not clean_id.is_empty() and not seen.has(clean_id):
			seen[clean_id] = true
			ids.append(clean_id)
	return {
		"owners_csv": _strip_bom_and_edges(str(val_u.strip_nul(owners_csv))),
		"gm_can_operate": gm_can_operate,
		"all_players_can_operate": all_players_can_operate,
		"owner_peers": PackedInt32Array(),
		"owner_player_ids": ids,
	}


func make_entity_note_state(
	text: String,
	is_pin: bool = true,
	keep_screen_size: bool = true
) -> Dictionary:
	return {
		"schema_version": 1,
		"text": sanitize_text(text).left(MAX_NOTE_TEXT_LENGTH),
		"keep_screen_size": keep_screen_size,
		"is_pin": is_pin,
	}


func make_unit_marker_state() -> Dictionary:
	return {"schema_version": 1}


func make_portal_state(pair_key: String) -> Dictionary:
	var clean: String = sanitize_text(pair_key).strip_edges()
	var normalized_key: String = ""
	if not clean.is_empty():
		var lower_clean: String = clean.to_lower()
		normalized_key = lower_clean if is_valid_uid(lower_clean) else ("fu_sdk:portal:" + clean).sha256_text().left(32)
	return {"pair_key": normalized_key}


func make_simple_vision_state(
	radius: float = 640.0,
	view_angle_deg: float = 360.0,
	requires_light: bool = false,
	enabled: bool = true
) -> Dictionary:
	return {
		"enabled": enabled,
		"requires_light": requires_light,
		"radius": maxf(0.0, sanitize_finite_float(radius, 640.0)),
		"view_angle": clampf(sanitize_finite_float(view_angle_deg, 360.0), 0.0, 360.0),
	}


func make_simple_light_state(
	radius: float = 640.0,
	view_angle_deg: float = 360.0,
	enabled: bool = true
) -> Dictionary:
	return {
		"enabled": enabled,
		"requires_light": false,
		"radius": maxf(0.0, sanitize_finite_float(radius, 640.0)),
		"view_angle": clampf(sanitize_finite_float(view_angle_deg, 360.0), 0.0, 360.0),
	}


func make_grid_alignment_state(
	cell_size: float = 64.0,
	snap_enabled: bool = true,
	offset: Vector2 = Vector2.ZERO,
	color: Color = Color(0.5, 0.55, 0.65, 0.7),
	line_width: float = 1.0,
	snap_strength: float = 0.1
) -> Dictionary:
	var raw_offset: Vector2 = sanitize_finite_vec2(offset, Vector2.ZERO)
	var safe_offset := Vector2(
		clampf(raw_offset.x, -GRID_MAX_OFFSET, GRID_MAX_OFFSET),
		clampf(raw_offset.y, -GRID_MAX_OFFSET, GRID_MAX_OFFSET)
	)
	return {
		"schema": "fus.grid_alignment.config",
		"version": 1,
		"cell_size": clampf(sanitize_finite_float(cell_size, 64.0), GRID_MIN_CELL_SIZE, GRID_MAX_CELL_SIZE),
		"offset": [safe_offset.x, safe_offset.y],
		"color": [
			clampf(sanitize_finite_float(color.r, 0.5), 0.0, 1.0),
			clampf(sanitize_finite_float(color.g, 0.55), 0.0, 1.0),
			clampf(sanitize_finite_float(color.b, 0.65), 0.0, 1.0),
			clampf(sanitize_finite_float(color.a, 0.7), 0.0, 1.0),
		],
		"line_width": clampf(sanitize_finite_float(line_width, 1.0), GRID_MIN_LINE_WIDTH, GRID_MAX_LINE_WIDTH),
		"snap_enabled": snap_enabled,
		"snap_strength": clampf(sanitize_finite_float(snap_strength, 0.1), 0.0, 1.0),
	}


func get_module_state(world: Dictionary, module_id: String) -> Dictionary:
	var clean_id: String = sanitize_text(module_id).strip_edges()
	if clean_id.is_empty():
		return {}
	var mods_var: Variant = world.get("modules", null)
	if not (mods_var is Dictionary):
		return {}
	var entries_var: Variant = (mods_var as Dictionary).get("entries", null)
	if not (entries_var is Dictionary):
		return {}
	var entry_var: Variant = (entries_var as Dictionary).get(clean_id, null)
	if not (entry_var is Dictionary):
		return {}
	var st_var: Variant = (entry_var as Dictionary).get("state", null)
	return _safe_clone_dict(st_var as Dictionary) if st_var is Dictionary else {}


func coerce_color_value(raw: Variant, fallback: Color = Color.BLACK) -> Dictionary:
	return _value_utils().coerce_color_value(raw, fallback)


func is_valid_simple_fog_exploration(blob: Variant) -> bool:
	if not (blob is PackedByteArray):
		return false
	var bytes: PackedByteArray = blob as PackedByteArray
	if bytes.is_empty():
		return true
	if bytes.size() <= 8 or bytes.size() > SIMPLE_FOG_MAX_COMPRESSED_BYTES:
		return false
	if bytes[0] != 0x53 or bytes[1] != 0x46 or bytes[2] != 0x48 or bytes[3] != 0x32:
		return false
	if bytes[7] >= 128:
		return false
	var raw_len: int = int(bytes[4]) | (int(bytes[5]) << 8) | (int(bytes[6]) << 16) | (int(bytes[7]) << 24)
	return raw_len >= 1 and raw_len <= SIMPLE_FOG_MAX_UNCOMPRESSED_BYTES


func make_simple_fog_world_state(
	overrides: Dictionary = {},
	exploration: PackedByteArray = PackedByteArray()
) -> Dictionary:
	var result: Dictionary = {
		"version": 2,
		"unseen_color": Color.BLACK,
		"visible_tint": Color.TRANSPARENT,
		"unseen_effect": 0,
		"visible_effect": 0,
		"history_enabled": false,
		"history_color": Color(0.0, 0.0, 0.0, 0.55),
		"history_effect": 0,
		"dm_opacity": 0.30,
		"vision_threshold": 0.5,
		"vision_feather": 0.04,
		"shadow_filter": 0,
		"shadow_smooth": 0.0,
		"hide_unseen_entities": true,
	}
	for raw_key: Variant in overrides.keys():
		var key: String = str(raw_key)
		if key == "exploration":
			continue
		if not result.has(key):
			continue
		var val: Variant = overrides[raw_key]
		match key:
			"version":
				result["version"] = 2
			"unseen_color":
				var uc: Dictionary = coerce_color_value(val, Color.BLACK)
				if bool(uc.get("ok", false)) and (uc["color"] as Color).a == 1.0:
					result["unseen_color"] = uc["color"]
			"visible_tint":
				var vt: Dictionary = coerce_color_value(val, Color.TRANSPARENT)
				if bool(vt.get("ok", false)):
					result["visible_tint"] = vt["color"]
			"history_color":
				var hc: Dictionary = coerce_color_value(val, Color(0.0, 0.0, 0.0, 0.55))
				if bool(hc.get("ok", false)):
					result["history_color"] = hc["color"]
			"unseen_effect", "visible_effect", "history_effect":
				var ef_val: Variant = val
				if ef_val is float:
					var ef_f: float = float(ef_val)
					if is_finite(ef_f) and ef_f == floor(ef_f) and ef_f >= -9007199254740991.0 and ef_f <= 9007199254740991.0:
						ef_val = int(ef_f)
				if ef_val is int and int(ef_val) in [0, 1, 2, 4, 6]:
					result[key] = int(ef_val)
			"history_enabled", "hide_unseen_entities":
				if val is bool:
					result[key] = val
			"dm_opacity":
				if val is int or val is float:
					result["dm_opacity"] = clampf(sanitize_finite_float(float(val), 0.30), 0.01, 1.0)
			"vision_threshold":
				if val is int or val is float:
					result["vision_threshold"] = clampf(sanitize_finite_float(float(val), 0.5), 0.0, 1.0)
			"vision_feather":
				if val is int or val is float:
					result["vision_feather"] = clampf(sanitize_finite_float(float(val), 0.04), 0.0, 0.5)
			"shadow_filter":
				var sf_val: Variant = val
				if sf_val is float:
					var sf_f: float = float(sf_val)
					if is_finite(sf_f) and sf_f == floor(sf_f) and sf_f >= -9007199254740991.0 and sf_f <= 9007199254740991.0:
						sf_val = int(sf_f)
				if sf_val is int and int(sf_val) in [0, 1, 2]:
					result["shadow_filter"] = int(sf_val)
			"shadow_smooth":
				if val is int or val is float:
					result["shadow_smooth"] = clampf(sanitize_finite_float(float(val), 0.0), 0.0, 16.0)
	var eff_blob: PackedByteArray = exploration
	if eff_blob.is_empty() and overrides.has("exploration") and overrides["exploration"] is PackedByteArray:
		eff_blob = overrides["exploration"] as PackedByteArray
	if not eff_blob.is_empty() and is_valid_simple_fog_exploration(eff_blob):
		result["exploration"] = eff_blob.duplicate()
	return result


func make_image_flip_state(horizontal: bool = false, vertical: bool = false) -> Dictionary:
	return {
		"horizontal": horizontal,
		"vertical": vertical,
	}


func make_drag_movement_world_state(speed: float = 64.0, version: int = 2) -> Dictionary:
	var safe_speed: float = maxf(0.0, sanitize_finite_float(speed, 64.0))
	if version == 1 and is_equal_approx(safe_speed, 256.0):
		safe_speed = 64.0
	return {
		"version": 2,
		"speed": safe_speed,
	}


func make_drag_speed_state(speed: float = 64.0) -> Dictionary:
	return {
		"speed": maxf(0.0, sanitize_finite_float(speed, 64.0)),
	}


func make_area_state(radius_in_cells: float = 1.0, removed: bool = false) -> Dictionary:
	var r: float = sanitize_finite_float(radius_in_cells, 1.0)
	if r <= 0.0:
		r = 1.0
	r = minf(r, AREA_MAX_RADIUS_IN_CELLS)
	return {
		"removed": removed,
		"radius_in_cells": r,
	}


func make_area_region_visual(
	size_src: Vector2,
	paths_local: Array,
	fill_color: Color = DEFAULT_AREA_FILL_COLOR,
	line_color: Color = DEFAULT_AREA_LINE_COLOR
) -> Dictionary:
	var visual: Dictionary = make_custom_drawing_visual(size_src, paths_local, fill_color, line_color)
	visual["show_fallback"] = false
	var vd: Dictionary = visual["vector_drawing"] as Dictionary
	vd["font_size"] = 16.0
	vd["source"] = {
		"kind": "area",
		"schema": "fus.area.v1",
	}
	return visual


func append_entity(
	world: Dictionary,
	floor_uid: String,
	layer_uid: String,
	source_id: String,
	label: String,
	center_src: Vector2,
	size_src: Vector2,
	rotation_rad: float,
	scale: Vector2,
	source_to_world: float,
	visual: Dictionary,
	is_unit: bool,
	hidden: bool,
	id_namespace: String = DEFAULT_ID_NAMESPACE,
	footprint_radius: float = DEFAULT_FOOTPRINT_RADIUS,
	locked: bool = false,
	permission_state: Dictionary = {}
) -> Dictionary:
	var ns: String = id_namespace if not id_namespace.is_empty() else DEFAULT_ID_NAMESPACE
	var entity_id: String = (ns + ":" + source_id).sha256_text().left(32)
	var clean_label: String = sanitize_text(label)
	var display_name: String = clean_label if not clean_label.is_empty() else "未命名物品"
	var safe_size: Vector2 = sanitize_finite_vec2(size_src, MIN_ENTITY_SIZE)
	var clamped_size := Vector2(maxf(MIN_ENTITY_SIZE.x, safe_size.x), maxf(MIN_ENTITY_SIZE.y, safe_size.y))
	var safe_center: Vector2 = sanitize_finite_vec2(center_src, Vector2.ZERO)
	var safe_rot: float = sanitize_finite_float(rotation_rad, 0.0)
	var safe_factor: float = sanitize_finite_float(source_to_world, compute_source_to_world_scale())
	if is_zero_approx(safe_factor) or not Vector2(safe_factor, safe_factor).is_finite():
		safe_factor = compute_source_to_world_scale()
	var safe_scale: Vector2 = sanitize_nonzero_scale(scale, Vector2.ONE)
	var world_scale: Vector2 = sanitize_nonzero_scale(safe_scale * safe_factor, Vector2(safe_factor, safe_factor))
	var scaled_pos: Vector2 = safe_center * safe_factor
	if not scaled_pos.is_finite() or not world_scale.is_finite():
		return {}
	var safe_footprint: float = sanitize_footprint_radius(footprint_radius)

	var safe_visual: Dictionary = _safe_clone_dict(visual)
	if safe_visual.has("sprite_path"):
		var checked_sprite: Dictionary = sanitize_sprite_path(_as_string(safe_visual.get("sprite_path", "")))
		safe_visual["sprite_path"] = str(checked_sprite["path"])

	var fallback_col: Color = DEFAULT_ENTITY_FALLBACK_COLOR
	var raw_fallback: Variant = safe_visual.get("fallback_color", null)
	if raw_fallback is Color:
		fallback_col = raw_fallback

	# 严守宿主双不变量：
	# 1. ImportBridge.preview_entity 硬编码读取 entity.components[0].state 作为视觉组件；
	# 2. EntityStateCodec.EntryCoreDrafts.prefix_for 要求 components[0..1] 为 [visual, permission]。
	var entity: Dictionary = {
		"id": entity_id,
		"display_name": display_name,
		"entity_type": "unit" if is_unit else "object",
		"entity_size": clamped_size,
		"selectable_in_select_mode": is_unit,
		"footprint_radius": safe_footprint,
		"fallback_color": fallback_col,
		"xform": {
			"pos": scaled_pos,
			"rot": safe_rot,
			"scale": world_scale,
		},
		"flags": {
			"entity_hidden": hidden,
			"entity_locked": locked,
		},
		"components": [
			{"script": COMP_VISUAL_SCRIPT, "state": safe_visual},
			{"script": COMP_PERMISSION_SCRIPT, "state": _safe_clone_dict(permission_state)},
		],
	}

	if not (world.get("entity_state", null) is Dictionary):
		world["entity_state"] = {"version": ENTITY_STATE_VERSION, "entities": []}
	else:
		var entity_state: Dictionary = world["entity_state"]
		if not (entity_state.get("version", null) is int):
			entity_state["version"] = ENTITY_STATE_VERSION
		if not (entity_state.get("entities", null) is Array):
			entity_state["entities"] = []
	if not (world.get("members", null) is Array):
		world["members"] = []

	var entities_list: Array = (world["entity_state"] as Dictionary)["entities"]
	entities_list.append(entity)

	var members_list: Array = world["members"]
	members_list.append({
		"entity_id": entity_id,
		"floor_uid": floor_uid,
		"layer_uid": layer_uid,
	})

	return entity


func find_entity_by_id(world: Dictionary, entity_id: String) -> Dictionary:
	if entity_id.is_empty():
		return {}
	var entity_state_var: Variant = world.get("entity_state", null)
	if not (entity_state_var is Dictionary):
		return {}
	var entities_var: Variant = (entity_state_var as Dictionary).get("entities", null)
	if not (entities_var is Array):
		return {}
	var ents: Array = entities_var as Array
	for i: int in range(ents.size() - 1, -1, -1):
		var raw_entity: Variant = ents[i]
		if raw_entity is Dictionary and _as_string((raw_entity as Dictionary).get("id", "")) == entity_id:
			return raw_entity as Dictionary
	return {}


func suppress_entity_fallback_box(entity: Dictionary) -> bool:
	if entity.is_empty():
		return false
	var transparent := Color(1.0, 1.0, 1.0, 0.0)
	entity["fallback_color"] = transparent
	var comps_var: Variant = entity.get("components", null)
	if comps_var is Array and not (comps_var as Array).is_empty():
		var c0_var: Variant = (comps_var as Array)[0]
		if c0_var is Dictionary:
			var state_var: Variant = (c0_var as Dictionary).get("state", null)
			if state_var is Dictionary:
				var st: Dictionary = state_var as Dictionary
				st["fallback_color"] = transparent
				st["show_fallback"] = false
				return true
	return false


func _entity_component_ids(entity: Dictionary) -> Dictionary:
	var ids: Dictionary = {}
	var components_var: Variant = entity.get("components", null)
	if components_var is Array:
		var val_u: Variant = _validation_utils()
		for raw_comp: Variant in components_var as Array:
			if raw_comp is Dictionary:
				var scr: String = _as_string((raw_comp as Dictionary).get("script", ""))
				var cid: String = str(val_u.component_id_from_script(scr))
				if not cid.is_empty():
					ids[cid] = true
	return ids


func _visual_drawing_kind(entity: Dictionary) -> String:
	var components_var: Variant = entity.get("components", null)
	if not (components_var is Array):
		return ""
	var val_u: Variant = _validation_utils()
	for raw_comp: Variant in components_var as Array:
		if raw_comp is Dictionary:
			var c: Dictionary = raw_comp as Dictionary
			if str(val_u.component_id_from_script(_as_string(c.get("script", "")))) == "visual":
				var st_var: Variant = c.get("state", null)
				if st_var is Dictionary:
					var vd_var: Variant = (st_var as Dictionary).get("vector_drawing", null)
					if vd_var is Dictionary:
						var src_var: Variant = (vd_var as Dictionary).get("source", null)
						if src_var is Dictionary:
							return _as_string((src_var as Dictionary).get("kind", ""))
	return ""


func _permits_entity_component(entity: Dictionary, comp_id: String, parked: bool = false) -> Dictionary:
	var existing_ids: Dictionary = _entity_component_ids(entity)
	var etype: String = _as_string(entity.get("entity_type", ""))
	if comp_id == "unit" and not parked and etype == "map":
		return build_failed("unit_disallowed_on_map")
	if comp_id == "scene_box":
		if etype == "map":
			return build_failed("scene_box_disallowed_on_map")
		if etype == "unit" or bool(entity.get("selectable_in_select_mode", false)):
			return build_failed("component_conflict_with_scene_box:unit")
		for conflict_id: String in SCENE_BOX_CONFLICT_COMPONENT_IDS:
			if existing_ids.has(conflict_id):
				return build_failed("component_conflict_with_scene_box:" + conflict_id)
		return {"ok": true}
	if comp_id in SCENE_BOX_CONFLICT_COMPONENT_IDS and existing_ids.has("scene_box"):
		return build_failed("component_conflict_with_scene_box:" + comp_id)
	if comp_id == "image_flip":
		var vis_kind: String = _visual_drawing_kind(entity)
		if existing_ids.has("obstacle") or existing_ids.has("area") or vis_kind in OBSTACLE_KINDS or vis_kind == "area":
			return build_failed("component_conflict_with_image_flip")
	if comp_id in ["obstacle", "area"] and existing_ids.has("image_flip"):
		return build_failed("component_conflict_with_image_flip")
	if not parked and comp_id in ["character_roster_member", "backpack", "initiative"] and not bool(_validation_utils().is_unit_host(entity)):
		return build_failed(comp_id + "_requires_unit_host")
	if not parked and comp_id == "initiative":
		if existing_ids.has("obstacle") or existing_ids.has("wall") or existing_ids.has("map"):
			return build_failed("initiative_disallowed_on_obstacle")
		if _visual_drawing_kind(entity) in OBSTACLE_KINDS:
			return build_failed("initiative_disallowed_on_obstacle")
	if not parked and comp_id in ["obstacle", "wall", "map"] and existing_ids.has("initiative"):
		return build_failed("initiative_disallowed_on_obstacle")
	return {"ok": true}


## 复用 DagCloner 进行有界深拷贝（保留 16 MiB 单模块上限与 depth=32 折叠语义）。
func _safe_clone_dict(raw: Dictionary) -> Dictionary:
	return _dag_cloner().safe_clone_dict(raw, MAX_MODULE_ENTRY_BYTES)


## 按指定初始深度与字节预算校验并深拷贝模块/组件字典。
func _safe_clone_validated_dict(
	raw: Dictionary,
	max_bytes: int = MAX_MODULE_ENTRY_BYTES,
	initial_depth: int = 0
) -> Dictionary:
	return _dag_cloner().safe_clone_validated_dict(raw, max_bytes, initial_depth)


## 复用 DagCloner 深拷贝任意 Variant（保留 16 MiB 单模块上限）。
func _safe_clone_variant(value: Variant, depth: int = 0, active_stack: Array = [], visit_budget: Array = []) -> Variant:
	return _dag_cloner().safe_clone_variant(value, depth, active_stack, visit_budget, MAX_MODULE_ENTRY_BYTES)


func is_valid_state_data(
	value: Variant,
	depth: int = 0,
	active_stack: Array = [],
	max_depth: int = 32,
	ctx: Dictionary = {}
) -> bool:
	var dc: Variant = _dag_cloner()
	var tctx: Variant
	var sync_ctx: bool = not ctx.is_empty()
	var raw_tctx: Variant = ctx.get("_trav_ctx", null) if sync_ctx else null
	if sync_ctx and raw_tctx != null and is_instance_of(raw_tctx, dc.DagTravCtx) and raw_tctx.mode == "validate":
		tctx = raw_tctx
		if ctx.has("nodes"):
			tctx.nodes = int(ctx["nodes"])
		if ctx.has("max_nodes"):
			tctx.max_nodes = int(ctx["max_nodes"])
	else:
		tctx = dc.DagTravCtx.new()
		tctx.mode = "validate"
		tctx.max_nodes = MAX_ESTIMATE_VISITS
		tctx.max_bytes = MAX_MODULE_ENTRY_BYTES
		if sync_ctx:
			tctx.nodes = int(ctx.get("nodes", 0))
			tctx.max_nodes = int(ctx.get("max_nodes", MAX_ESTIMATE_VISITS))
			tctx.last_logical_nodes = int(ctx.get("last_logical_nodes", 1))
			ctx["_trav_ctx"] = tctx
	var h: int = _validate_state_data_height(value, depth, active_stack, max_depth, tctx)
	if sync_ctx:
		ctx["nodes"] = tctx.nodes
		ctx["last_logical_nodes"] = tctx.last_logical_nodes
	return h >= 0


func _validate_state_data_height(
	value: Variant,
	depth: int,
	active_stack: Array,
	max_depth: int,
	tctx: Variant
) -> int:
	var dc: Variant = _dag_cloner()
	tctx.nodes += 1
	if tctx.nodes > tctx.max_nodes:
		return -1
	if depth > max_depth:
		return -1
	tctx.last_logical_nodes = 1
	match typeof(value):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_STRING, TYPE_STRING_NAME, TYPE_NODE_PATH, \
		TYPE_VECTOR2I, TYPE_VECTOR3I, TYPE_VECTOR4I, TYPE_RECT2I, \
		TYPE_PACKED_BYTE_ARRAY, TYPE_PACKED_INT32_ARRAY, TYPE_PACKED_INT64_ARRAY, TYPE_PACKED_STRING_ARRAY:
			return 0
		TYPE_FLOAT:
			return 0 if is_finite(float(value)) else -1
		TYPE_VECTOR2:
			return 0 if (value as Vector2).is_finite() else -1
		TYPE_VECTOR3:
			return 0 if (value as Vector3).is_finite() else -1
		TYPE_VECTOR4:
			return 0 if (value as Vector4).is_finite() else -1
		TYPE_QUATERNION:
			return 0 if (value as Quaternion).is_finite() else -1
		TYPE_COLOR:
			var c: Color = value as Color
			return 0 if (is_finite(c.r) and is_finite(c.g) and is_finite(c.b) and is_finite(c.a)) else -1
		TYPE_RECT2:
			var r: Rect2 = value as Rect2
			return 0 if (r.position.is_finite() and r.size.is_finite()) else -1
		TYPE_AABB:
			var a: AABB = value as AABB
			return 0 if (a.position.is_finite() and a.size.is_finite()) else -1
		TYPE_TRANSFORM2D:
			var t2: Transform2D = value as Transform2D
			return 0 if (t2.x.is_finite() and t2.y.is_finite() and t2.origin.is_finite()) else -1
		TYPE_PLANE:
			var pl: Plane = value as Plane
			return 0 if (pl.normal.is_finite() and is_finite(pl.d)) else -1
		TYPE_BASIS:
			var b: Basis = value as Basis
			return 0 if (b.x.is_finite() and b.y.is_finite() and b.z.is_finite()) else -1
		TYPE_TRANSFORM3D:
			var t3: Transform3D = value as Transform3D
			return 0 if (t3.basis.x.is_finite() and t3.basis.y.is_finite() and t3.basis.z.is_finite() and t3.origin.is_finite()) else -1
		TYPE_PROJECTION:
			var pr: Projection = value as Projection
			return 0 if (pr.x.is_finite() and pr.y.is_finite() and pr.z.is_finite() and pr.w.is_finite()) else -1
		TYPE_DICTIONARY:
			var d: Dictionary = value as Dictionary
			if dc.is_in_active_stack(d, active_stack):
				return -1
			if depth == max_depth:
				tctx.last_logical_nodes = 1
				return 0 if d.is_empty() else -1
			var d_sz: int = d.size()
			if d_sz > 0:
				var m: Variant = dc.memo_find(tctx, true, d_sz, d)
				if m != null:
					var mh: int = m.height
					if depth + mh > max_depth:
						return -1
					tctx.last_logical_nodes = m.logical_nodes
					return mh
			var start_nodes_vd: int = tctx.nodes
			active_stack.append(d)
			tctx.frame_seq += 1
			var fid: int = tctx.frame_seq
			tctx.active_frames.append(fid)
			tctx.live_frames[fid] = true
			var max_h: int = 0
			var logical_nodes: int = 1
			var d_keys_v: Array = d.keys()
			var has_d_vals_v: bool = d_sz > 4
			var d_vals_v: Array = d.values() if has_d_vals_v else []
			for k_idx_v: int in range(d_sz):
				var k: Variant = d_keys_v[k_idx_v]
				var scalar_kv: bool = false
				if k is String:
					scalar_kv = true
					max_h = maxi(max_h, 1)
				else:
					scalar_kv = (k is StringName or k is NodePath or k is int or k is float or k is bool or k == null)
					var kh: int = _validate_state_data_height(k, depth + 1, active_stack, max_depth, tctx)
					if kh < 0:
						tctx.live_frames.erase(fid)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return -1
					max_h = maxi(max_h, 1 + kh)
					logical_nodes = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes + tctx.last_logical_nodes)
				var val_v: Variant
				if has_d_vals_v:
					val_v = d_vals_v[k_idx_v]
				elif scalar_kv:
					val_v = d[k]
				else:
					d_vals_v = d.values()
					has_d_vals_v = true
					val_v = d_vals_v[k_idx_v]
				var vt: int = typeof(val_v)
				if vt == TYPE_NIL or vt == TYPE_BOOL or vt == TYPE_INT or vt == TYPE_STRING or vt == TYPE_STRING_NAME or vt == TYPE_NODE_PATH:
					tctx.nodes += 1
					if tctx.nodes > tctx.max_nodes or depth + 1 > max_depth:
						tctx.live_frames.erase(fid)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return -1
					max_h = maxi(max_h, 1)
					logical_nodes = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes + 1)
				else:
					var vh: int = _validate_state_data_height(val_v, depth + 1, active_stack, max_depth, tctx)
					if vh < 0:
						tctx.live_frames.erase(fid)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return -1
					max_h = maxi(max_h, 1 + vh)
					logical_nodes = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes + tctx.last_logical_nodes)
			tctx.live_frames.erase(fid)
			tctx.active_frames.pop_back()
			active_stack.pop_back()
			dc.memo_store(tctx, true, d_sz, d, max_h, 0, logical_nodes, null, maxi(1, tctx.nodes - start_nodes_vd))
			tctx.last_logical_nodes = logical_nodes
			return max_h
		TYPE_ARRAY:
			var arr: Array = value as Array
			if dc.is_in_active_stack(arr, active_stack):
				return -1
			if depth == max_depth:
				tctx.last_logical_nodes = 1
				return 0 if arr.is_empty() else -1
			var a_sz: int = arr.size()
			if a_sz > 0:
				var ma: Variant = dc.memo_find(tctx, false, a_sz, arr)
				if ma != null:
					var mh: int = ma.height
					if depth + mh > max_depth:
						return -1
					tctx.last_logical_nodes = ma.logical_nodes
					return mh
			var start_nodes_va: int = tctx.nodes
			active_stack.append(arr)
			tctx.frame_seq += 1
			var fid_a: int = tctx.frame_seq
			tctx.active_frames.append(fid_a)
			tctx.live_frames[fid_a] = true
			var max_ha: int = 0
			var logical_nodes_a: int = 1
			for item: Variant in arr:
				var it: int = typeof(item)
				if it == TYPE_NIL or it == TYPE_BOOL or it == TYPE_INT or it == TYPE_STRING or it == TYPE_STRING_NAME or it == TYPE_NODE_PATH:
					tctx.nodes += 1
					if tctx.nodes > tctx.max_nodes or depth + 1 > max_depth:
						tctx.live_frames.erase(fid_a)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return -1
					max_ha = maxi(max_ha, 1)
					logical_nodes_a = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_a + 1)
				else:
					var ih: int = _validate_state_data_height(item, depth + 1, active_stack, max_depth, tctx)
					if ih < 0:
						tctx.live_frames.erase(fid_a)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return -1
					max_ha = maxi(max_ha, 1 + ih)
					logical_nodes_a = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_a + tctx.last_logical_nodes)
			tctx.live_frames.erase(fid_a)
			tctx.active_frames.pop_back()
			active_stack.pop_back()
			dc.memo_store(tctx, false, a_sz, arr, max_ha, 0, logical_nodes_a, null, maxi(1, tctx.nodes - start_nodes_va))
			tctx.last_logical_nodes = logical_nodes_a
			return max_ha
		TYPE_PACKED_FLOAT32_ARRAY:
			var pf32: PackedFloat32Array = value as PackedFloat32Array
			if depth == max_depth and not pf32.is_empty():
				return -1
			for f: float in pf32:
				if not is_finite(f):
					return -1
			return 0 if pf32.is_empty() else 1
		TYPE_PACKED_FLOAT64_ARRAY:
			var pf64: PackedFloat64Array = value as PackedFloat64Array
			if depth == max_depth and not pf64.is_empty():
				return -1
			for f: float in pf64:
				if not is_finite(f):
					return -1
			return 0 if pf64.is_empty() else 1
		TYPE_PACKED_VECTOR2_ARRAY:
			var pv2: PackedVector2Array = value as PackedVector2Array
			if depth == max_depth and not pv2.is_empty():
				return -1
			for v2: Vector2 in pv2:
				if not v2.is_finite():
					return -1
			return 0 if pv2.is_empty() else 1
		TYPE_PACKED_VECTOR3_ARRAY:
			var pv3: PackedVector3Array = value as PackedVector3Array
			if depth == max_depth and not pv3.is_empty():
				return -1
			for v3: Vector3 in pv3:
				if not v3.is_finite():
					return -1
			return 0 if pv3.is_empty() else 1
		TYPE_PACKED_VECTOR4_ARRAY:
			var pv4: PackedVector4Array = value as PackedVector4Array
			if depth == max_depth and not pv4.is_empty():
				return -1
			for v4: Vector4 in pv4:
				if not v4.is_finite():
					return -1
			return 0 if pv4.is_empty() else 1
		TYPE_PACKED_COLOR_ARRAY:
			var pc: PackedColorArray = value as PackedColorArray
			if depth == max_depth and not pc.is_empty():
				return -1
			for c: Color in pc:
				if not is_finite(c.r) or not is_finite(c.g) or not is_finite(c.b) or not is_finite(c.a):
					return -1
			return 0 if pc.is_empty() else 1
		_:
			return -1


func append_entity_component(
	entity: Dictionary,
	script_path: String,
	state: Dictionary = {},
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	if manual and not parked:
		return build_failed("manual_requires_parked")
	if entity.is_empty():
		return build_failed("entity_not_found")
	var clean_script: String = sanitize_text(script_path).strip_edges()
	if not clean_script.begins_with("res://") or not clean_script.ends_with(".gd") or clean_script.contains(".."):
		return build_failed("invalid_component_script_path")
	if clean_script == COMP_VISUAL_SCRIPT or clean_script == COMP_PERMISSION_SCRIPT:
		return build_failed("core_component_slot_reserved")

	var components_var: Variant = entity.get("components", null)
	if not (components_var is Array) or (components_var as Array).size() < 2:
		return build_failed("invalid_core_components_prefix")
	var components: Array = components_var
	var first_script: String = _as_string((components[0] as Dictionary).get("script", "")) if components[0] is Dictionary else ""
	var second_script: String = _as_string((components[1] as Dictionary).get("script", "")) if components[1] is Dictionary else ""
	if first_script != COMP_VISUAL_SCRIPT or second_script != COMP_PERMISSION_SCRIPT:
		return build_failed("core_components_prefix_corrupted")

	var val_u: Variant = _validation_utils()
	var comp_id: String = str(val_u.component_id_from_script(clean_script))
	if comp_id.is_empty() or comp_id == "visual" or comp_id == "permission":
		return build_failed("invalid_component_id")

	var pair_check: Dictionary = _permits_entity_component(entity, comp_id, parked)
	if not bool(pair_check.get("ok", false)):
		return pair_check

	if not is_valid_state_data(state, 6):
		return build_failed("invalid_component_state")
	var pre_bounded: int = bounded_variant_size_estimate(state, 6, [], MAX_MODULE_ENTRY_BYTES)
	if pre_bounded < 0 or pre_bounded > MAX_MODULE_ENTRY_BYTES:
		return build_failed("component_state_size_limit")
	if var_to_bytes(state).size() > MAX_MODULE_ENTRY_BYTES:
		return build_failed("component_state_size_limit")

	var clone_res: Dictionary = _safe_clone_validated_dict(state, MAX_MODULE_ENTRY_BYTES, 6)
	if not bool(clone_res.get("ok", false)):
		return build_failed("component_state_size_limit")
	var copied_state: Dictionary = clone_res["dict"] as Dictionary

	var record: Dictionary = {
		"script": clean_script,
		"state": copied_state,
	}
	if parked:
		record["parked"] = true
		if manual:
			record["manual"] = true

	# 仅允许在索引 >= 2 更新或追加，绝不破坏 components[0..1] == [visual, permission] 不变量。
	for idx: int in range(2, components.size()):
		if components[idx] is Dictionary:
			var existing_script: String = _as_string((components[idx] as Dictionary).get("script", ""))
			if existing_script == clean_script or str(val_u.component_id_from_script(existing_script)) == comp_id:
				components[idx] = record
				return {"ok": true, "index": idx, "replaced": true}

	components.append(record)
	return {"ok": true, "index": components.size() - 1, "replaced": false}


func make_scene_box_state(
	target_scene_uid: String,
	preview_policy: String = "visited_unlock",
	enter_policy: String = "players_allowed",
	cover_asset: String = ""
) -> Dictionary:
	var clean_target: String = sanitize_text(target_scene_uid).strip_edges().to_lower()
	if not clean_target.is_empty() and not is_valid_uid(clean_target):
		return build_failed("invalid_target_scene_uid")

	var clean_preview: String = preview_policy.strip_edges()
	var norm_preview: String = clean_preview if clean_preview in SCENE_BOX_PREVIEW_POLICIES else "visited_unlock"

	var clean_enter: String = enter_policy.strip_edges()
	var norm_enter: String = clean_enter if clean_enter in SCENE_BOX_ENTER_POLICIES else "players_allowed"

	var cover_check: Dictionary = sanitize_cover_asset(cover_asset)
	var safe_cover: String = str(cover_check["cover_asset"])

	return {
		"ok": true,
		"cover_asset": safe_cover,
		"cover_sanitized": bool(cover_check["sanitized"]),
		"state": {
			"schema_version": 1,
			"target_scene_uid": clean_target,
			"preview_policy": norm_preview,
			"enter_policy": norm_enter,
			"cover_asset": safe_cover,
			"seed_from_visual": false,
		},
	}


func _resolve_scene_box_permissions(
	all_players_can_enter: bool,
	owner_player_ids: Array
) -> Dictionary:
	var perm_state: Dictionary = make_permission_state("", owner_player_ids, all_players_can_enter, true)
	var clean_owners: PackedStringArray = perm_state["owner_player_ids"]
	var enter_policy: String = "players_allowed" if (all_players_can_enter or not clean_owners.is_empty()) else "host_only"
	return {
		"permission_state": perm_state,
		"enter_policy": enter_policy,
	}


func append_scene_box_entity(
	world: Dictionary,
	floor_uid: String,
	layer_uid: String,
	source_id: String,
	label: String,
	center_world: Vector2,
	target_scene_uid: String,
	side_world: float = SCENE_BOX_DEFAULT_SIDE_WORLD,
	cover_asset: String = "",
	preview_policy: String = "visited_unlock",
	all_players_can_enter: bool = true,
	owner_player_ids: Array = [],
	hidden_from_players: bool = false,
	locked: bool = false,
	rotation_rad: float = 0.0,
	id_namespace: String = DEFAULT_ID_NAMESPACE,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	if manual and not parked:
		return build_failed("manual_requires_parked")
	if floor_uid.is_empty() or layer_uid.is_empty():
		return build_failed("missing_target_floor_or_layer")

	var clean_target: String = sanitize_text(target_scene_uid).strip_edges().to_lower()
	if not clean_target.is_empty() and not is_valid_uid(clean_target):
		return build_failed("invalid_target_scene_uid")
	if not clean_target.is_empty() and has_scene_repository_state(world):
		if not (clean_target in get_scene_uids(world)):
			return build_failed("unknown_target_scene_uid")

	var perm_bundle: Dictionary = _resolve_scene_box_permissions(all_players_can_enter, owner_player_ids)
	var box_built: Dictionary = make_scene_box_state(
		clean_target,
		preview_policy,
		str(perm_bundle["enter_policy"]),
		cover_asset
	)
	if not bool(box_built.get("ok", false)):
		return box_built

	var resolved_floor: String = get_floor_for_layer(world, layer_uid)
	var target_floor: String = resolved_floor if not resolved_floor.is_empty() else floor_uid

	var safe_side: float = clampf(
		side_world if is_finite(side_world) else SCENE_BOX_DEFAULT_SIDE_WORLD,
		SCENE_BOX_MIN_SIDE_WORLD,
		SCENE_BOX_MAX_SIDE_WORLD
	)
	var safe_cover: String = str(box_built["cover_asset"])
	var visual: Dictionary = make_sprite_visual(safe_cover, DEFAULT_SPRITE_FALLBACK_COLOR, {})
	var clean_label: String = label if not sanitize_text(label).strip_edges().is_empty() else "场景盒子"
	if not is_finite(center_world.x) or not is_finite(center_world.y):
		return build_failed("non_finite_center_world")

	var entity: Dictionary = append_entity(
		world,
		target_floor,
		layer_uid,
		source_id,
		clean_label,
		center_world,
		Vector2(safe_side, safe_side),
		rotation_rad,
		Vector2.ONE,
		1.0,
		visual,
		false,
		hidden_from_players,
		id_namespace,
		DEFAULT_FOOTPRINT_RADIUS,
		locked,
		perm_bundle["permission_state"] as Dictionary
	)
	if entity.is_empty():
		return build_failed("append_entity_failed")

	var comp_res: Dictionary = append_entity_component(entity, COMP_SCENE_BOX_SCRIPT, box_built["state"] as Dictionary, parked, manual)
	if not bool(comp_res.get("ok", false)):
		return comp_res

	return {
		"ok": true,
		"entity_id": _as_string(entity.get("id", "")),
		"entity": entity,
		"cover_asset": safe_cover,
		"cover_sanitized": bool(box_built["cover_sanitized"]),
	}


func attach_scene_box_to_entity(
	world: Dictionary,
	entity_id: String,
	target_scene_uid: String,
	cover_asset: String = "",
	preview_policy: String = "visited_unlock",
	all_players_can_enter: bool = true,
	owner_player_ids: Array = [],
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	if manual and not parked:
		return build_failed("manual_requires_parked")
	var entity: Dictionary = find_entity_by_id(world, entity_id)
	if entity.is_empty():
		return build_failed("entity_not_found")

	var pair_check: Dictionary = _permits_entity_component(entity, "scene_box", parked)
	if not bool(pair_check.get("ok", false)):
		return pair_check

	var clean_target: String = sanitize_text(target_scene_uid).strip_edges().to_lower()
	if not clean_target.is_empty() and not is_valid_uid(clean_target):
		return build_failed("invalid_target_scene_uid")
	if not clean_target.is_empty() and has_scene_repository_state(world):
		if not (clean_target in get_scene_uids(world)):
			return build_failed("unknown_target_scene_uid")

	var perm_bundle: Dictionary = _resolve_scene_box_permissions(all_players_can_enter, owner_player_ids)
	var box_built: Dictionary = make_scene_box_state(
		clean_target,
		preview_policy,
		str(perm_bundle["enter_policy"]),
		cover_asset
	)
	if not bool(box_built.get("ok", false)):
		return box_built

	var safe_cover: String = str(box_built["cover_asset"])
	if not parked:
		var cur_size: Vector2 = sanitize_finite_vec2(entity.get("entity_size", Vector2(SCENE_BOX_DEFAULT_SIDE_WORLD, SCENE_BOX_DEFAULT_SIDE_WORLD)), Vector2(SCENE_BOX_DEFAULT_SIDE_WORLD, SCENE_BOX_DEFAULT_SIDE_WORLD))
		var sq_side: float = clampf(maxf(cur_size.x, cur_size.y), SCENE_BOX_MIN_SIDE_WORLD, SCENE_BOX_MAX_SIDE_WORLD)
		entity["entity_size"] = Vector2(sq_side, sq_side)
		entity["selectable_in_select_mode"] = false
		if entity.get("xform", null) is Dictionary:
			(entity["xform"] as Dictionary)["scale"] = Vector2.ONE

		var components_var: Variant = entity.get("components", null)
		if not (components_var is Array) or (components_var as Array).size() < 2:
			return build_failed("invalid_core_components_prefix")
		var components: Array = components_var

		if not safe_cover.is_empty() and components[0] is Dictionary:
			var c0_state_var: Variant = (components[0] as Dictionary).get("state", null)
			if c0_state_var is Dictionary:
				(c0_state_var as Dictionary)["sprite_path"] = safe_cover
		if components[1] is Dictionary:
			(components[1] as Dictionary)["state"] = (perm_bundle["permission_state"] as Dictionary).duplicate(true)

	var comp_res: Dictionary = append_entity_component(entity, COMP_SCENE_BOX_SCRIPT, box_built["state"] as Dictionary, parked, manual)
	if not bool(comp_res.get("ok", false)):
		return comp_res

	return {
		"ok": true,
		"entity_id": entity_id,
		"cover_asset": safe_cover,
		"cover_sanitized": bool(box_built["cover_sanitized"]),
	}


func sanitize_module_value(v: Variant, depth: int = 0, active_stack: Array = [], visit_budget: Array = []) -> Variant:
	var max_nodes: int = MAX_CLONE_VISITS
	if not visit_budget.is_empty():
		max_nodes = mini(MAX_CLONE_VISITS, maxi(0, int(visit_budget[0])))
	var dc: Variant = _dag_cloner()
	var tctx: Variant = dc.DagTravCtx.new()
	tctx.max_nodes = max_nodes
	tctx.max_bytes = MAX_MODULE_ENTRY_BYTES
	var out: Variant = _sanitize_module_node(v, depth, active_stack, tctx)
	if not visit_budget.is_empty():
		visit_budget[0] = maxi(0, max_nodes - tctx.nodes)
	if tctx.aborted:
		if v is Dictionary:
			return {}
		if v is Array:
			return []
		return null
	return out


func _sanitize_module_node(v: Variant, depth: int, active_stack: Array, tctx: Variant) -> Variant:
	var dc: Variant = _dag_cloner()
	if tctx.aborted:
		return null
	tctx.nodes += 1
	if tctx.nodes > tctx.max_nodes:
		tctx.aborted = true
		return null
	if depth > 32:
		tctx.depth_clipped = true
		tctx.cycle_clipped = false
		tctx.last_height = 0
		tctx.last_bytes = 8
		tctx.last_logical_nodes = 1
		return null
	match typeof(v):
		TYPE_NIL:
			tctx.bytes += 8
			if tctx.bytes > tctx.max_bytes:
				tctx.aborted = true
				return null
			tctx.depth_clipped = false
			tctx.cycle_clipped = false
			tctx.last_height = 0
			tctx.last_bytes = 8
			tctx.last_logical_nodes = 1
			return null
		TYPE_BOOL, TYPE_INT:
			tctx.bytes += 16
			if tctx.bytes > tctx.max_bytes:
				tctx.aborted = true
				return null
			tctx.depth_clipped = false
			tctx.cycle_clipped = false
			tctx.last_height = 0
			tctx.last_bytes = 16
			tctx.last_logical_nodes = 1
			return v
		TYPE_STRING:
			var sc: int = 16 + (v as String).length() * 4
			tctx.bytes += sc
			if tctx.bytes > tctx.max_bytes:
				tctx.aborted = true
				return null
			tctx.depth_clipped = false
			tctx.cycle_clipped = false
			tctx.last_height = 0
			tctx.last_bytes = sc
			tctx.last_logical_nodes = 1
			return v
		TYPE_STRING_NAME, TYPE_NODE_PATH:
			var s: String = str(v)
			var sc2: int = 16 + s.length() * 4
			tctx.bytes += sc2
			if tctx.bytes > tctx.max_bytes:
				tctx.aborted = true
				return null
			tctx.depth_clipped = false
			tctx.cycle_clipped = false
			tctx.last_height = 0
			tctx.last_bytes = sc2
			tctx.last_logical_nodes = 1
			return s
		TYPE_FLOAT:
			tctx.bytes += 16
			if tctx.bytes > tctx.max_bytes:
				tctx.aborted = true
				return null
			tctx.depth_clipped = false
			tctx.cycle_clipped = false
			tctx.last_height = 0
			tctx.last_bytes = 16
			tctx.last_logical_nodes = 1
			var f: float = float(v)
			return f if is_finite(f) else 0.0
		TYPE_ARRAY:
			var arr: Array = v as Array
			if dc.is_in_active_stack(arr, active_stack):
				tctx.depth_clipped = false
				tctx.cycle_clipped = true
				tctx.last_height = 0
				tctx.last_bytes = 8
				tctx.last_logical_nodes = 1
				return null
			if depth == 32:
				tctx.depth_clipped = not arr.is_empty()
				tctx.cycle_clipped = false
				tctx.bytes += 16
				if tctx.bytes > tctx.max_bytes:
					tctx.aborted = true
					return null
				tctx.last_height = 0
				tctx.last_bytes = 16
				tctx.last_logical_nodes = 1
				return []
			var allow_memo_a: bool = true
			var try_clipped_memo_a: bool = true
			var a_sz: int = arr.size()
			if a_sz > 0:
				var ma: Variant = dc.memo_find(tctx, false, a_sz, arr)
				if ma != null:
					var mha: int = ma.height
					var mba: int = ma.size
					var mlna: int = ma.logical_nodes
					if depth + mha <= 32:
						try_clipped_memo_a = false
						if tctx.bytes + mba > tctx.max_bytes or tctx.nodes + 1 > tctx.max_nodes:
							tctx.aborted = true
							return null
						if mlna <= MAX_CLONE_SHARED_SUBTREE and tctx.shared_unfold + mlna <= MAX_CLONE_SHARED_UNFOLD:
							tctx.shared_unfold += mlna
							allow_memo_a = false
						else:
							tctx.bytes += mba
							tctx.depth_clipped = false
							tctx.cycle_clipped = false
							tctx.last_height = mha
							tctx.last_bytes = mba
							tctx.last_logical_nodes = mlna
							return ma.cloned
					else:
						allow_memo_a = false
				if try_clipped_memo_a:
					var mca: Variant = dc.memo_find_in_buckets(tctx, tctx.clipped_arr_buckets, (a_sz << 6) | (depth & 0x3f), arr)
					if mca != null:
						if tctx.bytes + mca.size > tctx.max_bytes or tctx.nodes + 1 > tctx.max_nodes:
							tctx.aborted = true
							return null
						tctx.bytes += mca.size
						tctx.depth_clipped = true
						tctx.cycle_clipped = false
						tctx.last_height = mca.height
						tctx.last_bytes = mca.size
						tctx.last_logical_nodes = mca.logical_nodes
						return mca.cloned
			tctx.bytes += 16
			if tctx.bytes > tctx.max_bytes:
				tctx.aborted = true
				return null
			var rem_a: int = tctx.max_bytes - tctx.bytes
			if a_sz > rem_a / 8:
				tctx.aborted = true
				return null
			var start_nodes_sa: int = tctx.nodes
			active_stack.append(arr)
			tctx.frame_seq += 1
			var fid_a: int = tctx.frame_seq
			tctx.active_frames.append(fid_a)
			tctx.live_frames[fid_a] = true
			var out_arr: Array = []
			out_arr.resize(a_sz)
			var max_ha: int = 0
			var total_ba: int = 16
			var logical_nodes_a: int = 1
			var any_depth_clipped_a: bool = false
			var any_cycle_a: bool = false
			for idx: int in range(a_sz):
				var item: Variant = arr[idx]
				var it: int = typeof(item)
				if it == TYPE_NIL or it == TYPE_BOOL or it == TYPE_INT or it == TYPE_FLOAT or it == TYPE_STRING or it == TYPE_STRING_NAME or it == TYPE_NODE_PATH:
					tctx.nodes += 1
					if tctx.nodes > tctx.max_nodes:
						tctx.aborted = true
						tctx.live_frames.erase(fid_a)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return null
					var sval: Variant = item
					var ic_fast: int = 8
					if it == TYPE_STRING:
						ic_fast = 16 + (item as String).length() * 4
					elif it == TYPE_STRING_NAME or it == TYPE_NODE_PATH:
						var s_item: String = str(item)
						sval = s_item
						ic_fast = 16 + s_item.length() * 4
					elif it == TYPE_FLOAT:
						var fi: float = float(item)
						sval = fi if is_finite(fi) else 0.0
						ic_fast = 16
					elif it != TYPE_NIL:
						ic_fast = 16
					tctx.bytes += ic_fast
					if tctx.bytes > tctx.max_bytes:
						tctx.aborted = true
						tctx.live_frames.erase(fid_a)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return null
					out_arr[idx] = sval
					total_ba += ic_fast
					max_ha = maxi(max_ha, 1)
					logical_nodes_a = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_a + 1)
				else:
					tctx.depth_clipped = false
					tctx.cycle_clipped = false
					var ci: Variant = _sanitize_module_node(item, depth + 1, active_stack, tctx)
					if tctx.aborted:
						tctx.live_frames.erase(fid_a)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return null
					any_depth_clipped_a = any_depth_clipped_a or tctx.depth_clipped
					any_cycle_a = any_cycle_a or tctx.cycle_clipped
					out_arr[idx] = ci
					total_ba += tctx.last_bytes
					max_ha = maxi(max_ha, 1 + tctx.last_height)
					logical_nodes_a = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_a + tctx.last_logical_nodes)
			tctx.live_frames.erase(fid_a)
			tctx.active_frames.pop_back()
			active_stack.pop_back()
			if not any_cycle_a:
				if any_depth_clipped_a:
					dc.memo_store_in_buckets(tctx, tctx.clipped_arr_buckets, (a_sz << 6) | (depth & 0x3f), arr, max_ha, total_ba, logical_nodes_a, out_arr, maxi(1, tctx.nodes - start_nodes_sa))
				elif allow_memo_a:
					dc.memo_store(tctx, false, a_sz, arr, max_ha, total_ba, logical_nodes_a, out_arr, maxi(1, tctx.nodes - start_nodes_sa))
			tctx.depth_clipped = any_depth_clipped_a
			tctx.cycle_clipped = any_cycle_a
			tctx.last_height = max_ha
			tctx.last_bytes = total_ba
			tctx.last_logical_nodes = logical_nodes_a
			return out_arr
		TYPE_DICTIONARY:
			var d: Dictionary = v as Dictionary
			if dc.is_in_active_stack(d, active_stack):
				tctx.depth_clipped = false
				tctx.cycle_clipped = true
				tctx.last_height = 0
				tctx.last_bytes = 8
				tctx.last_logical_nodes = 1
				return null
			if depth == 32:
				tctx.depth_clipped = not d.is_empty()
				tctx.cycle_clipped = false
				tctx.bytes += 16
				if tctx.bytes > tctx.max_bytes:
					tctx.aborted = true
					return null
				tctx.last_height = 0
				tctx.last_bytes = 16
				tctx.last_logical_nodes = 1
				return {}
			var allow_memo_d: bool = true
			var try_clipped_memo_d: bool = true
			var d_sz: int = d.size()
			if d_sz > 0:
				var md: Variant = dc.memo_find(tctx, true, d_sz, d)
				if md != null:
					var mhd: int = md.height
					var mbd: int = md.size
					var mlnd: int = md.logical_nodes
					if depth + mhd <= 32:
						try_clipped_memo_d = false
						if tctx.bytes + mbd > tctx.max_bytes or tctx.nodes + 1 > tctx.max_nodes:
							tctx.aborted = true
							return null
						if mlnd <= MAX_CLONE_SHARED_SUBTREE and tctx.shared_unfold + mlnd <= MAX_CLONE_SHARED_UNFOLD:
							tctx.shared_unfold += mlnd
							allow_memo_d = false
						else:
							tctx.bytes += mbd
							tctx.depth_clipped = false
							tctx.cycle_clipped = false
							tctx.last_height = mhd
							tctx.last_bytes = mbd
							tctx.last_logical_nodes = mlnd
							return md.cloned
					else:
						allow_memo_d = false
				if try_clipped_memo_d:
					var mcd: Variant = dc.memo_find_in_buckets(tctx, tctx.clipped_dict_buckets, (d_sz << 6) | (depth & 0x3f), d)
					if mcd != null:
						if tctx.bytes + mcd.size > tctx.max_bytes or tctx.nodes + 1 > tctx.max_nodes:
							tctx.aborted = true
							return null
						tctx.bytes += mcd.size
						tctx.depth_clipped = true
						tctx.cycle_clipped = false
						tctx.last_height = mcd.height
						tctx.last_bytes = mcd.size
						tctx.last_logical_nodes = mcd.logical_nodes
						return mcd.cloned
			tctx.bytes += 16
			if tctx.bytes > tctx.max_bytes:
				tctx.aborted = true
				return null
			var rem_d: int = tctx.max_bytes - tctx.bytes
			if d_sz > rem_d / 16:
				tctx.aborted = true
				return null
			var start_nodes_sd: int = tctx.nodes
			active_stack.append(d)
			tctx.frame_seq += 1
			var fid_d: int = tctx.frame_seq
			tctx.active_frames.append(fid_d)
			tctx.live_frames[fid_d] = true
			var out_dict: Dictionary = {}
			var max_hd: int = 0
			var total_bd: int = 16
			var logical_nodes_d: int = 1
			var any_depth_clipped_d: bool = false
			var any_cycle_d: bool = false
			var d_keys_s: Array = d.keys()
			var d_vals_s: Array = []
			var has_d_vals_s: bool = false
			for k_idx_s: int in range(d_keys_s.size()):
				var k: Variant = d_keys_s[k_idx_s]
				var kt: int = typeof(k)
				var ks: String = ""
				var scalar_ks: bool = false
				if kt == TYPE_STRING:
					scalar_ks = true
					ks = k as String
				elif kt == TYPE_NIL or kt == TYPE_BOOL or kt == TYPE_INT or kt == TYPE_FLOAT or kt == TYPE_STRING_NAME or kt == TYPE_NODE_PATH:
					scalar_ks = true
					ks = str(k)
				elif kt == TYPE_DICTIONARY or kt == TYPE_ARRAY:
					if dc.is_in_active_stack(k, active_stack):
						any_cycle_d = true
						continue
					tctx.depth_clipped = false
					tctx.cycle_clipped = false
					var sk: Variant = _sanitize_module_node(k, depth + 1, active_stack, tctx)
					if tctx.aborted:
						tctx.live_frames.erase(fid_d)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return null
					any_depth_clipped_d = any_depth_clipped_d or tctx.depth_clipped
					any_cycle_d = any_cycle_d or tctx.cycle_clipped
					var sk_bytes: int = tctx.last_bytes
					max_hd = maxi(max_hd, 1 + tctx.last_height)
					logical_nodes_d = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_d + tctx.last_logical_nodes)
					if sk_bytes > 4096:
						continue
					ks = str(sk)
				elif kt == TYPE_OBJECT or kt == TYPE_CALLABLE or kt == TYPE_SIGNAL or kt == TYPE_RID or kt >= TYPE_PACKED_BYTE_ARRAY:
					continue
				else:
					ks = str(k)
				var kc: int = 16 + ks.length() * 4
				tctx.bytes += kc
				if tctx.bytes > tctx.max_bytes:
					tctx.aborted = true
					tctx.live_frames.erase(fid_d)
					tctx.active_frames.pop_back()
					active_stack.pop_back()
					return null
				max_hd = maxi(max_hd, 1)
				var val_v: Variant
				if scalar_ks:
					val_v = d[k]
				else:
					if not has_d_vals_s:
						d_vals_s = d.values()
						has_d_vals_s = true
					val_v = d_vals_s[k_idx_s]
				var vt: int = typeof(val_v)
				var cv: Variant
				var vc: int = 0
				if vt == TYPE_NIL or vt == TYPE_BOOL or vt == TYPE_INT or vt == TYPE_FLOAT or vt == TYPE_STRING or vt == TYPE_STRING_NAME or vt == TYPE_NODE_PATH:
					tctx.nodes += 1
					if tctx.nodes > tctx.max_nodes:
						tctx.aborted = true
						tctx.live_frames.erase(fid_d)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return null
					if vt == TYPE_NIL:
						cv = null
						vc = 8
					elif vt == TYPE_STRING:
						cv = val_v
						vc = 16 + (val_v as String).length() * 4
					elif vt == TYPE_STRING_NAME or vt == TYPE_NODE_PATH:
						var s_val: String = str(val_v)
						cv = s_val
						vc = 16 + s_val.length() * 4
					elif vt == TYPE_FLOAT:
						var fv: float = float(val_v)
						cv = fv if is_finite(fv) else 0.0
						vc = 16
					else:
						cv = val_v
						vc = 16
					tctx.bytes += vc
					if tctx.bytes > tctx.max_bytes:
						tctx.aborted = true
						tctx.live_frames.erase(fid_d)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return null
					max_hd = maxi(max_hd, 1)
					logical_nodes_d = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_d + 1)
				else:
					tctx.depth_clipped = false
					tctx.cycle_clipped = false
					cv = _sanitize_module_node(val_v, depth + 1, active_stack, tctx)
					if tctx.aborted:
						tctx.live_frames.erase(fid_d)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return null
					any_depth_clipped_d = any_depth_clipped_d or tctx.depth_clipped
					any_cycle_d = any_cycle_d or tctx.cycle_clipped
					vc = tctx.last_bytes
					max_hd = maxi(max_hd, 1 + tctx.last_height)
					logical_nodes_d = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_d + tctx.last_logical_nodes)
				total_bd += kc + vc
				out_dict[ks] = cv
			tctx.live_frames.erase(fid_d)
			tctx.active_frames.pop_back()
			active_stack.pop_back()
			if not any_cycle_d:
				if any_depth_clipped_d:
					dc.memo_store_in_buckets(tctx, tctx.clipped_dict_buckets, (d_sz << 6) | (depth & 0x3f), d, max_hd, total_bd, logical_nodes_d, out_dict, maxi(1, tctx.nodes - start_nodes_sd))
				elif allow_memo_d:
					dc.memo_store(tctx, true, d_sz, d, max_hd, total_bd, logical_nodes_d, out_dict, maxi(1, tctx.nodes - start_nodes_sd))
			tctx.depth_clipped = any_depth_clipped_d
			tctx.cycle_clipped = any_cycle_d
			tctx.last_height = max_hd
			tctx.last_bytes = total_bd
			tctx.last_logical_nodes = logical_nodes_d
			return out_dict
		_:
			tctx.bytes += 8
			if tctx.bytes > tctx.max_bytes:
				tctx.aborted = true
				return null
			tctx.depth_clipped = false
			tctx.cycle_clipped = false
			tctx.last_height = 0
			tctx.last_bytes = 8
			tctx.last_logical_nodes = 1
			return null


func bounded_variant_size_estimate(
	val: Variant,
	depth: int = 0,
	active_stack: Array = [],
	max_bytes: int = MAX_MODULE_TOTAL_BYTES,
	max_depth: int = 32,
	ctx: Dictionary = {}
) -> int:
	var dc: Variant = _dag_cloner()
	var tctx: Variant
	var sync_ctx: bool = not ctx.is_empty()
	var raw_tctx: Variant = ctx.get("_trav_ctx", null) if sync_ctx else null
	if sync_ctx and raw_tctx != null and is_instance_of(raw_tctx, dc.DagTravCtx) and raw_tctx.mode == "estimate":
		tctx = raw_tctx
		if ctx.has("nodes"):
			tctx.nodes = int(ctx["nodes"])
		if ctx.has("max_nodes"):
			tctx.max_nodes = int(ctx["max_nodes"])
		if ctx.has("bytes"):
			tctx.bytes = int(ctx["bytes"])
		if ctx.has("max_bytes"):
			tctx.max_bytes = int(ctx["max_bytes"])
		if ctx.has("limit_exceeded"):
			tctx.limit_exceeded = bool(ctx["limit_exceeded"])
	else:
		tctx = dc.DagTravCtx.new()
		tctx.mode = "estimate"
		tctx.max_nodes = MAX_ESTIMATE_VISITS
		tctx.max_bytes = max_bytes
		if sync_ctx:
			tctx.nodes = int(ctx.get("nodes", 0))
			tctx.max_nodes = int(ctx.get("max_nodes", MAX_ESTIMATE_VISITS))
			tctx.bytes = int(ctx.get("bytes", 0))
			tctx.max_bytes = int(ctx.get("max_bytes", max_bytes))
			tctx.last_height = int(ctx.get("last_height", 0))
			tctx.last_logical_nodes = int(ctx.get("last_logical_nodes", 1))
			tctx.limit_exceeded = bool(ctx.get("limit_exceeded", false))
			ctx["_trav_ctx"] = tctx
	var out_size: int = _bounded_variant_size_node(val, depth, active_stack, max_depth, tctx)
	if sync_ctx:
		ctx["nodes"] = tctx.nodes
		ctx["bytes"] = tctx.bytes
		ctx["limit_exceeded"] = tctx.limit_exceeded
		ctx["last_height"] = tctx.last_height
		ctx["last_logical_nodes"] = tctx.last_logical_nodes
	return out_size


func _bounded_variant_size_node(
	val: Variant,
	depth: int,
	active_stack: Array,
	max_depth: int,
	tctx: Variant
) -> int:
	var dc: Variant = _dag_cloner()
	tctx.nodes += 1
	if tctx.nodes > tctx.max_nodes:
		return -1
	if depth > max_depth:
		return -1
	var leaf_cost: int = -1
	match typeof(val):
		TYPE_NIL:
			leaf_cost = 8
		TYPE_BOOL, TYPE_INT, TYPE_FLOAT:
			leaf_cost = 16
		TYPE_VECTOR2, TYPE_VECTOR2I:
			leaf_cost = 24
		TYPE_RECT2, TYPE_RECT2I, TYPE_VECTOR3, TYPE_VECTOR3I, TYPE_COLOR, TYPE_VECTOR4, TYPE_VECTOR4I, TYPE_PLANE, TYPE_QUATERNION:
			leaf_cost = 40
		TYPE_TRANSFORM2D, TYPE_AABB, TYPE_BASIS:
			leaf_cost = 64
		TYPE_TRANSFORM3D, TYPE_PROJECTION:
			leaf_cost = 80
		TYPE_STRING, TYPE_STRING_NAME:
			leaf_cost = 16 + str(val).length() * 4
		TYPE_NODE_PATH:
			leaf_cost = 32 + str(val).length() * 8
		TYPE_PACKED_BYTE_ARRAY:
			leaf_cost = 16 + (val as PackedByteArray).size()
		TYPE_PACKED_INT32_ARRAY:
			leaf_cost = 16 + (val as PackedInt32Array).size() * 4
		TYPE_PACKED_FLOAT32_ARRAY:
			leaf_cost = 16 + (val as PackedFloat32Array).size() * 4
		TYPE_PACKED_INT64_ARRAY:
			leaf_cost = 16 + (val as PackedInt64Array).size() * 8
		TYPE_PACKED_FLOAT64_ARRAY:
			leaf_cost = 16 + (val as PackedFloat64Array).size() * 8
		TYPE_PACKED_VECTOR2_ARRAY:
			leaf_cost = 16 + (val as PackedVector2Array).size() * 16
		TYPE_PACKED_VECTOR3_ARRAY:
			leaf_cost = 16 + (val as PackedVector3Array).size() * 24
		TYPE_PACKED_VECTOR4_ARRAY:
			leaf_cost = 16 + (val as PackedVector4Array).size() * 32
		TYPE_PACKED_COLOR_ARRAY:
			leaf_cost = 16 + (val as PackedColorArray).size() * 32
		TYPE_PACKED_STRING_ARRAY:
			var total_ps: int = 16
			tctx.bytes += 16
			if tctx.bytes > tctx.max_bytes:
				tctx.limit_exceeded = true
				return -1
			for s: String in val as PackedStringArray:
				var scost: int = 16 + s.length() * 4
				total_ps += scost
				tctx.bytes += scost
				if tctx.bytes > tctx.max_bytes:
					tctx.limit_exceeded = true
					return -1
			tctx.last_height = 0
			tctx.last_logical_nodes = 1
			return total_ps
		TYPE_DICTIONARY:
			var d: Dictionary = val as Dictionary
			if dc.is_in_active_stack(d, active_stack):
				return -1
			if depth == max_depth:
				if not d.is_empty():
					return -1
				tctx.bytes += 16
				if tctx.bytes > tctx.max_bytes:
					tctx.limit_exceeded = true
					return -1
				tctx.last_height = 0
				tctx.last_logical_nodes = 1
				return 16
			var d_sz: int = d.size()
			if d_sz > 0:
				var md: Variant = dc.memo_find(tctx, true, d_sz, d)
				if md != null:
					var mh: int = md.height
					var ms: int = md.size
					if depth + mh > max_depth:
						return -1
					if tctx.bytes + ms > tctx.max_bytes:
						tctx.limit_exceeded = true
						return -1
					tctx.bytes += ms
					tctx.last_height = mh
					tctx.last_logical_nodes = md.logical_nodes
					return ms
			var total_d: int = 16
			tctx.bytes += 16
			if tctx.bytes > tctx.max_bytes:
				tctx.limit_exceeded = true
				return -1
			var rem_d: int = tctx.max_bytes - tctx.bytes
			if d_sz > rem_d / 16:
				tctx.limit_exceeded = true
				return -1
			var start_nodes_bd: int = tctx.nodes
			active_stack.append(d)
			tctx.frame_seq += 1
			var fid: int = tctx.frame_seq
			tctx.active_frames.append(fid)
			tctx.live_frames[fid] = true
			var max_hd: int = 0
			var logical_nodes_d: int = 1
			var d_keys_b: Array = d.keys()
			var has_d_vals_b: bool = d_sz > 4
			var d_vals_b: Array = d.values() if has_d_vals_b else []
			for k_idx_b: int in range(d_sz):
				var k: Variant = d_keys_b[k_idx_b]
				var kc: int = 0
				var scalar_kb: bool = false
				if k is String:
					scalar_kb = true
					kc = 16 + (k as String).length() * 4
					tctx.bytes += kc
					if tctx.bytes > tctx.max_bytes:
						tctx.live_frames.erase(fid)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						tctx.limit_exceeded = true
						return -1
					max_hd = maxi(max_hd, 1)
				else:
					scalar_kb = (k is StringName or k is NodePath or k is int or k is float or k is bool or k == null)
					kc = _bounded_variant_size_node(k, depth + 1, active_stack, max_depth, tctx)
					if kc < 0:
						tctx.live_frames.erase(fid)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return -1
					max_hd = maxi(max_hd, 1 + tctx.last_height)
					logical_nodes_d = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_d + tctx.last_logical_nodes)
				var val_v: Variant
				if has_d_vals_b:
					val_v = d_vals_b[k_idx_b]
				elif scalar_kb:
					val_v = d[k]
				else:
					d_vals_b = d.values()
					has_d_vals_b = true
					val_v = d_vals_b[k_idx_b]
				var vt: int = typeof(val_v)
				var vc: int = 0
				if vt == TYPE_NIL or vt == TYPE_BOOL or vt == TYPE_INT or vt == TYPE_FLOAT or vt == TYPE_STRING:
					tctx.nodes += 1
					if tctx.nodes > tctx.max_nodes or depth + 1 > max_depth:
						tctx.live_frames.erase(fid)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return -1
					if vt == TYPE_NIL:
						vc = 8
					elif vt == TYPE_STRING:
						vc = 16 + (val_v as String).length() * 4
					else:
						vc = 16
					tctx.bytes += vc
					if tctx.bytes > tctx.max_bytes:
						tctx.live_frames.erase(fid)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						tctx.limit_exceeded = true
						return -1
					max_hd = maxi(max_hd, 1)
					logical_nodes_d = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_d + 1)
				else:
					vc = _bounded_variant_size_node(val_v, depth + 1, active_stack, max_depth, tctx)
					if vc < 0:
						tctx.live_frames.erase(fid)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return -1
					max_hd = maxi(max_hd, 1 + tctx.last_height)
					logical_nodes_d = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_d + tctx.last_logical_nodes)
				total_d += kc + vc
			tctx.live_frames.erase(fid)
			tctx.active_frames.pop_back()
			active_stack.pop_back()
			tctx.last_height = max_hd
			tctx.last_logical_nodes = logical_nodes_d
			dc.memo_store(tctx, true, d_sz, d, max_hd, total_d, logical_nodes_d, null, maxi(1, tctx.nodes - start_nodes_bd))
			return total_d
		TYPE_ARRAY:
			var arr: Array = val as Array
			if dc.is_in_active_stack(arr, active_stack):
				return -1
			if depth == max_depth:
				if not arr.is_empty():
					return -1
				tctx.bytes += 16
				if tctx.bytes > tctx.max_bytes:
					tctx.limit_exceeded = true
					return -1
				tctx.last_height = 0
				tctx.last_logical_nodes = 1
				return 16
			var a_sz: int = arr.size()
			if a_sz > 0:
				var ma: Variant = dc.memo_find(tctx, false, a_sz, arr)
				if ma != null:
					var mh: int = ma.height
					var ms: int = ma.size
					if depth + mh > max_depth:
						return -1
					if tctx.bytes + ms > tctx.max_bytes:
						tctx.limit_exceeded = true
						return -1
					tctx.bytes += ms
					tctx.last_height = mh
					tctx.last_logical_nodes = ma.logical_nodes
					return ms
			var total_a: int = 16
			tctx.bytes += 16
			if tctx.bytes > tctx.max_bytes:
				tctx.limit_exceeded = true
				return -1
			var rem_a: int = tctx.max_bytes - tctx.bytes
			if a_sz > rem_a / 8:
				tctx.limit_exceeded = true
				return -1
			var start_nodes_va: int = tctx.nodes
			active_stack.append(arr)
			tctx.frame_seq += 1
			var fid_a: int = tctx.frame_seq
			tctx.active_frames.append(fid_a)
			tctx.live_frames[fid_a] = true
			var max_ha: int = 0
			var logical_nodes_a: int = 1
			for item: Variant in arr:
				var it: int = typeof(item)
				var ic: int = 0
				if it == TYPE_NIL or it == TYPE_BOOL or it == TYPE_INT or it == TYPE_FLOAT or it == TYPE_STRING:
					tctx.nodes += 1
					if tctx.nodes > tctx.max_nodes or depth + 1 > max_depth:
						tctx.live_frames.erase(fid_a)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return -1
					if it == TYPE_NIL:
						ic = 8
					elif it == TYPE_STRING:
						ic = 16 + (item as String).length() * 4
					else:
						ic = 16
					tctx.bytes += ic
					if tctx.bytes > tctx.max_bytes:
						tctx.live_frames.erase(fid_a)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						tctx.limit_exceeded = true
						return -1
					max_ha = maxi(max_ha, 1)
					logical_nodes_a = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_a + 1)
				else:
					ic = _bounded_variant_size_node(item, depth + 1, active_stack, max_depth, tctx)
					if ic < 0:
						tctx.live_frames.erase(fid_a)
						tctx.active_frames.pop_back()
						active_stack.pop_back()
						return -1
					max_ha = maxi(max_ha, 1 + tctx.last_height)
					logical_nodes_a = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_a + tctx.last_logical_nodes)
				total_a += ic
			tctx.live_frames.erase(fid_a)
			tctx.active_frames.pop_back()
			active_stack.pop_back()
			tctx.last_height = max_ha
			tctx.last_logical_nodes = logical_nodes_a
			dc.memo_store(tctx, false, a_sz, arr, max_ha, total_a, logical_nodes_a, null, maxi(1, tctx.nodes - start_nodes_va))
			return total_a
		_:
			leaf_cost = 256
	tctx.bytes += leaf_cost
	if tctx.bytes > tctx.max_bytes:
		tctx.limit_exceeded = true
		return -1
	tctx.last_height = 0
	tctx.last_logical_nodes = 1
	return leaf_cost


func can_fit_module_state(
	world: Dictionary,
	module_id: String,
	version: int,
	state: Dictionary,
	max_world_bytes: int = MAX_WORLD_BUDGET_BYTES
) -> bool:
	var clean_id: String = sanitize_text(module_id).strip_edges()
	if not is_valid_module_id(clean_id):
		return false
	if version <= 0 or version > 0x7fffffff:
		return false
	if not is_valid_state_data(state, 3):
		return false
	var entry_bounded: int = bounded_variant_size_estimate(state, 3, [], MAX_MODULE_ENTRY_BYTES)
	if entry_bounded < 0 or entry_bounded > MAX_MODULE_ENTRY_BYTES:
		return false
	var entry_var_bytes: int = var_to_bytes(state).size()
	if entry_var_bytes > MAX_MODULE_ENTRY_BYTES:
		return false

	var mods_var: Variant = world.get("modules", {})
	var mods_copy: Dictionary = (mods_var as Dictionary).duplicate(false) if (mods_var is Dictionary) else {"version": MODULE_STATE_VERSION, "entries": {}}
	if not mods_copy.has("version"):
		mods_copy["version"] = MODULE_STATE_VERSION
	var raw_entries_copy: Variant = mods_copy.get("entries", {})
	var entries_copy: Dictionary = (raw_entries_copy as Dictionary).duplicate(false) if (raw_entries_copy is Dictionary) else {}
	if not entries_copy.has(clean_id) and entries_copy.size() >= MAX_MODULE_ENTRIES:
		return false

	var new_entry: Dictionary = {"version": version, "state": state}
	entries_copy[clean_id] = new_entry
	mods_copy["entries"] = entries_copy

	var total_bounded: int = bounded_variant_size_estimate(mods_copy, 0, [], MAX_MODULE_TOTAL_BYTES)
	if total_bounded < 0 or total_bounded > MAX_MODULE_TOTAL_BYTES:
		return false
	if total_bounded > (MAX_MODULE_TOTAL_BYTES * 3) / 4 and var_to_bytes(mods_copy).size() > MAX_MODULE_TOTAL_BYTES:
		return false

	if max_world_bytes > 0:
		var world_scan_budget: int = maxi(max_world_bytes * 4, MAX_MODULE_TOTAL_BYTES * 2)
		var world_ctx: Dictionary = {
			"nodes": 0,
			"max_nodes": MAX_ESTIMATE_VISITS,
			"bytes": 0,
			"max_bytes": world_scan_budget,
			"last_height": 0,
			"last_logical_nodes": 1,
			"limit_exceeded": false,
		}
		var world_bounded: int = bounded_variant_size_estimate(world, 0, [], world_scan_budget, 128, world_ctx)
		if world_bounded < 0:
			return false
		if world_bounded + entry_bounded + 512 > max_world_bytes:
			var cur_world_bytes: int = var_to_bytes(world).size()
			var prev_entry_bytes: int = 0
			var envelope_overhead: int = 0
			var raw_mods: Variant = world.get("modules", null)
			var raw_entries: Variant = (raw_mods as Dictionary).get("entries", null) if (raw_mods is Dictionary) else null
			if raw_entries is Dictionary and (raw_entries as Dictionary).has(clean_id):
				var prev_raw: Variant = (raw_entries as Dictionary)[clean_id]
				if bounded_variant_size_estimate(prev_raw, 2, [], MAX_MODULE_TOTAL_BYTES * 2, 128) < 0:
					return false
				prev_entry_bytes = var_to_bytes(prev_raw).size()
			elif raw_mods is Dictionary and raw_entries is Dictionary:
				envelope_overhead = var_to_bytes(clean_id).size()
			else:
				envelope_overhead = var_to_bytes({"modules": {"version": MODULE_STATE_VERSION, "entries": {clean_id: null}}}).size() - 12
			var new_entry_bytes: int = var_to_bytes(new_entry).size()
			if cur_world_bytes - prev_entry_bytes + new_entry_bytes + envelope_overhead > max_world_bytes:
				return false

	return true


func set_module_state(
	world: Dictionary,
	module_id: String,
	version: int,
	state: Dictionary
) -> Dictionary:
	var clean_id: String = sanitize_text(module_id).strip_edges()
	if not is_valid_module_id(clean_id):
		return build_failed("invalid_module_id:" + clean_id)
	if version <= 0 or version > 0x7fffffff:
		return build_failed("invalid_module_version")

	if not is_valid_state_data(state, 3):
		return build_failed("invalid_module_state")
	var entry_ctx: Dictionary = {
		"nodes": 0,
		"max_nodes": MAX_ESTIMATE_VISITS,
		"bytes": 0,
		"max_bytes": MAX_MODULE_ENTRY_BYTES,
		"last_height": 0,
		"last_logical_nodes": 1,
		"limit_exceeded": false,
	}
	var pre_bounded: int = bounded_variant_size_estimate(state, 3, [], MAX_MODULE_ENTRY_BYTES, 32, entry_ctx)
	if pre_bounded < 0:
		if bool(entry_ctx.get("limit_exceeded", false)):
			return build_failed("module_entry_size_limit")
		return build_failed("invalid_module_state")
	if pre_bounded > MAX_MODULE_ENTRY_BYTES:
		return build_failed("module_entry_size_limit")

	if not (world.get("modules", null) is Dictionary):
		world["modules"] = {"version": MODULE_STATE_VERSION, "entries": {}}
	var modules_dict: Dictionary = world["modules"]
	if not (modules_dict.get("entries", null) is Dictionary):
		modules_dict["entries"] = {}
	var entries: Dictionary = modules_dict["entries"]
	if not entries.has(clean_id) and entries.size() >= MAX_MODULE_ENTRIES:
		return build_failed("module_entries_limit_exceeded")

	if var_to_bytes(state).size() > MAX_MODULE_ENTRY_BYTES:
		return build_failed("module_entry_size_limit")
	var clone_res: Dictionary = _safe_clone_validated_dict(state, MAX_MODULE_ENTRY_BYTES, 3)
	if not bool(clone_res.get("ok", false)):
		return build_failed("module_entry_size_limit")
	var copied_state: Dictionary = clone_res["dict"] as Dictionary

	var prev_present: bool = entries.has(clean_id)
	var prev_value: Variant = entries.get(clean_id, null)
	entries[clean_id] = {
		"version": version,
		"state": copied_state,
	}
	var skip_total_scan: bool = (
		entries.size() == 1
		and modules_dict.size() == 2
		and modules_dict.get("version", null) is int
	)
	var total_failed: bool = false
	if not skip_total_scan:
		var total_bounded: int = bounded_variant_size_estimate(modules_dict, 0, [], MAX_MODULE_TOTAL_BYTES)
		if total_bounded < 0 or total_bounded > MAX_MODULE_TOTAL_BYTES:
			total_failed = true
		elif total_bounded > (MAX_MODULE_TOTAL_BYTES * 3) / 4 and var_to_bytes(modules_dict).size() > MAX_MODULE_TOTAL_BYTES:
			total_failed = true
	if total_failed:
		if prev_present:
			entries[clean_id] = prev_value
		else:
			entries.erase(clean_id)
		return build_failed("module_state_size_limit")

	return {"ok": true, "module_id": clean_id, "version": version}


func build_prepare_ok(
	world: Dictionary,
	asset_count: int,
	source_record_count: int = 0,
	merged_wall_count: int = 0
) -> Dictionary:
	var entity_state_var: Variant = world.get("entity_state", null)
	var entities_var: Variant = (entity_state_var as Dictionary).get("entities", []) if entity_state_var is Dictionary else []
	var entity_total: int = (entities_var as Array).size() if entities_var is Array else 0
	return {
		"ok": true,
		"world": world,
		"counts": {
			"entities": entity_total,
			"assets": maxi(0, asset_count),
			"source_records": maxi(0, source_record_count),
			"merged_walls": maxi(0, merged_wall_count),
		},
	}


func _preview_color_for_obstacle(kind: String, is_open: bool) -> Color:
	match kind:
		"door":
			return DEFAULT_DOOR_OPEN_COLOR if is_open else DEFAULT_DOOR_CLOSED_COLOR
		"window":
			return DEFAULT_WINDOW_OPEN_COLOR if is_open else DEFAULT_WINDOW_CLOSED_COLOR
		"glass":
			return DEFAULT_GLASS_COLOR
		"air":
			return DEFAULT_AIR_COLOR
		_:
			return DEFAULT_WALL_COLOR


func _normalize_ring(pts_list: Array, size: Vector2) -> PackedVector2Array:
	var normalized_ring := PackedVector2Array()
	for raw_pt: Variant in pts_list:
		var pt: Vector2 = raw_pt
		normalized_ring.append(pt / size)
	return normalized_ring


func _subtract_holes_for_triangulation(outer: PackedVector2Array, holes: Array) -> Array:
	var pieces: Array = [outer]
	if holes.is_empty():
		return pieces

	for raw_hole: Variant in holes:
		var hole: PackedVector2Array = raw_hole
		if hole.size() < 3:
			continue
		var next_pieces: Array = []
		for raw_piece: Variant in pieces:
			var piece: PackedVector2Array = raw_piece
			if piece.size() < 3:
				continue
			next_pieces.append_array(_clip_piece_with_hole_simple(piece, hole, 0))
		pieces = next_pieces
		if pieces.is_empty():
			break

	return pieces


func _clip_piece_with_hole_simple(piece: PackedVector2Array, hole: PackedVector2Array, depth: int) -> Array:
	var clipped: Array = Geometry2D.clip_polygons(piece, hole)
	var simple_out: Array = []
	var has_interior_hole: bool = false
	for raw_poly: Variant in clipped:
		if not (raw_poly is PackedVector2Array):
			continue
		var poly: PackedVector2Array = raw_poly
		if poly.size() < 3:
			continue
		if Geometry2D.is_polygon_clockwise(poly):
			has_interior_hole = true
		else:
			simple_out.append(poly)

	if not has_interior_hole:
		return simple_out
	if depth >= 4:
		return simple_out

	# 内孔未触及外边界时，沿内孔包围盒中线切分多边形后再执行 clip_polygons，
	# 使内孔变为外边界凹口，从而产出可直接 triangulate_polygon 的无孔简单多边形。
	var piece_bounds: Rect2 = _ring_bounds(piece)
	var hole_bounds: Rect2 = _ring_bounds(hole)
	var pad: float = maxf(piece_bounds.size.x, piece_bounds.size.y) + 4.0
	var split_boxes: Array = []
	if depth % 2 == 0:
		var split_x: float = hole_bounds.position.x + hole_bounds.size.x * 0.5
		split_boxes.append(PackedVector2Array([
			Vector2(piece_bounds.position.x - pad, piece_bounds.position.y - pad),
			Vector2(split_x, piece_bounds.position.y - pad),
			Vector2(split_x, piece_bounds.end.y + pad),
			Vector2(piece_bounds.position.x - pad, piece_bounds.end.y + pad),
		]))
		split_boxes.append(PackedVector2Array([
			Vector2(split_x, piece_bounds.position.y - pad),
			Vector2(piece_bounds.end.x + pad, piece_bounds.position.y - pad),
			Vector2(piece_bounds.end.x + pad, piece_bounds.end.y + pad),
			Vector2(split_x, piece_bounds.end.y + pad),
		]))
	else:
		var split_y: float = hole_bounds.position.y + hole_bounds.size.y * 0.5
		split_boxes.append(PackedVector2Array([
			Vector2(piece_bounds.position.x - pad, piece_bounds.position.y - pad),
			Vector2(piece_bounds.end.x + pad, piece_bounds.position.y - pad),
			Vector2(piece_bounds.end.x + pad, split_y),
			Vector2(piece_bounds.position.x - pad, split_y),
		]))
		split_boxes.append(PackedVector2Array([
			Vector2(piece_bounds.position.x - pad, split_y),
			Vector2(piece_bounds.end.x + pad, split_y),
			Vector2(piece_bounds.end.x + pad, piece_bounds.end.y + pad),
			Vector2(piece_bounds.position.x - pad, piece_bounds.end.y + pad),
		]))

	var result: Array = []
	for raw_box: Variant in split_boxes:
		var box: PackedVector2Array = raw_box
		var halves: Array = Geometry2D.intersect_polygons(piece, box)
		for raw_half: Variant in halves:
			if not (raw_half is PackedVector2Array):
				continue
			var half: PackedVector2Array = raw_half
			if half.size() < 3 or Geometry2D.is_polygon_clockwise(half):
				continue
			result.append_array(_clip_piece_with_hole_simple(half, hole, depth + 1))
	return result


func _ring_bounds(ring: PackedVector2Array) -> Rect2:
	if ring.is_empty():
		return Rect2()
	var bounds := Rect2(ring[0], Vector2.ZERO)
	for i: int in range(1, ring.size()):
		bounds = bounds.expand(ring[i])
	return bounds


func _collect_layer_uids(layer_floors: Array) -> Dictionary:
	var uids: Dictionary = {}
	for raw_floor: Variant in layer_floors:
		if raw_floor is Dictionary:
			var rows_var: Variant = (raw_floor as Dictionary).get("layers", [])
			if rows_var is Array:
				for raw_layer: Variant in rows_var as Array:
					if raw_layer is Dictionary:
						var uid: String = _as_string((raw_layer as Dictionary).get("layer_uid", ""))
						if not uid.is_empty():
							uids[uid] = true
	return uids


func _count_total_layers(layer_floors: Array) -> int:
	var total: int = 0
	for raw_floor: Variant in layer_floors:
		if raw_floor is Dictionary:
			var rows_var: Variant = (raw_floor as Dictionary).get("layers", [])
			if rows_var is Array:
				total += (rows_var as Array).size()
	return total


func _is_valid_polygon_ring_pts(pts_list: Array) -> bool:
	var n: int = pts_list.size()
	if n < 3:
		return false
	var origin: Vector2 = pts_list[0] as Vector2
	var shifted := PackedVector2Array()
	shifted.resize(n)
	for i: int in range(n):
		var pt: Vector2 = pts_list[i] as Vector2
		if not is_finite(pt.x) or not is_finite(pt.y):
			return false
		var doubled: Vector2 = pt * 2.0
		if not is_finite(doubled.x) or not is_finite(doubled.y):
			return false
		var rel: Vector2 = pt - origin
		if not is_finite(rel.x) or not is_finite(rel.y):
			return false
		shifted[i] = rel
	var area2: float = 0.0
	for i: int in range(n):
		var a: Vector2 = shifted[i]
		var b: Vector2 = shifted[(i + 1) % n]
		if a.is_equal_approx(b):
			return false
		area2 += float(a.x) * float(b.y) - float(b.x) * float(a.y)
	var area: float = absf(area2) * 0.5
	if not is_finite(area) or area <= 1e-6:
		return false
	if Geometry2D.triangulate_polygon(shifted).is_empty():
		return false
	if n <= 256:
		for i: int in range(n):
			var a1: Vector2 = shifted[i]
			var a2: Vector2 = shifted[(i + 1) % n]
			for j: int in range(i + 2, n):
				if i == 0 and j == n - 1:
					continue
				var b1: Vector2 = shifted[j]
				var b2: Vector2 = shifted[(j + 1) % n]
				if Geometry2D.segment_intersects_segment(a1, a2, b1, b2) != null:
					return false
	return true


func _extract_vec2_ring(raw_ring: Variant) -> Array:
	var result: Array = []
	if raw_ring is PackedVector2Array:
		for pt: Vector2 in raw_ring as PackedVector2Array:
			if is_finite(pt.x) and is_finite(pt.y):
				result.append(pt)
	elif raw_ring is Array:
		for raw_pt: Variant in raw_ring as Array:
			var pt: Vector2 = Vector2.ZERO
			var ok: bool = false
			if raw_pt is Vector2:
				pt = raw_pt
				ok = true
			elif raw_pt is Vector2i:
				var vi: Vector2i = raw_pt
				pt = Vector2(float(vi.x), float(vi.y))
				ok = true
			elif raw_pt is Array and (raw_pt as Array).size() >= 2:
				var pair: Array = raw_pt
				var px: Variant = pair[0]
				var py: Variant = pair[1]
				if (px is int or px is float) and (py is int or py is float):
					pt = Vector2(float(px), float(py))
					ok = true
			elif raw_pt is Dictionary:
				var pt_dict: Dictionary = raw_pt
				var dx: Variant = pt_dict.get("x", 0.0)
				var dy: Variant = pt_dict.get("y", 0.0)
				if (dx is int or dx is float) and (dy is int or dy is float):
					pt = Vector2(float(dx), float(dy))
					ok = true
			if ok and is_finite(pt.x) and is_finite(pt.y):
				result.append(pt)
	return result
