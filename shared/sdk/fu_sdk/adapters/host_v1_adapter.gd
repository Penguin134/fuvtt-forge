extends RefCounted
## Fu vtt Host API v1 底层防腐适配器 (Practice v0.0.56 / Steam v0.0.57 / fus.floor_layers.v2)
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
const MAX_MODULE_ENTRY_BYTES: int = 6 * 1024 * 1024
const MAX_MODULE_TOTAL_BYTES: int = 8 * 1024 * 1024
const MAX_WORLD_BUDGET_BYTES: int = 30 * 1024 * 1024

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
	var cleaned: String = value
	while cleaned.begins_with(char(0xfeff)):
		cleaned = cleaned.substr(1)
	return cleaned


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


func is_valid_uid(value: String) -> bool:
	if value.length() != 32:
		return false
	for index: int in 32:
		var code: int = value.unicode_at(index)
		if not ((code >= 48 and code <= 57) or (code >= 97 and code <= 102)):
			return false
	return true


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
	match typeof(value):
		TYPE_BOOL:
			return value == true
		TYPE_INT:
			return int(value) != 0
		TYPE_FLOAT:
			var num: float = float(value)
			if not is_finite(num):
				return fallback
			return num != 0.0
		TYPE_STRING:
			var normalized: String = sanitize_text(str(value)).strip_edges().to_lower()
			match normalized:
				"true", "1", "yes", "on":
					return true
				"false", "0", "no", "off":
					return false
				_:
					return fallback
		_:
			return fallback


func coerce_string(value: Variant, fallback: String = "") -> String:
	if typeof(value) == TYPE_STRING:
		return value as String
	return fallback


func _parse_int64_str(s: String) -> Variant:
	var t: String = s.strip_edges()
	if t.is_empty():
		return null
	var negative: bool = false
	var idx: int = 0
	var first_ch: int = t.unicode_at(0)
	if first_ch == 45:
		negative = true
		idx = 1
	elif first_ch == 43:
		idx = 1
	var n: int = t.length()
	if idx >= n:
		return null
	for i: int in range(idx, n):
		var c: int = t.unicode_at(i)
		if c < 48 or c > 57:
			return null
	while idx < n and t.unicode_at(idx) == 48:
		idx += 1
	if idx == n:
		return 0
	var digits: String = t.substr(idx)
	var dlen: int = digits.length()
	if dlen > 19:
		return null
	if dlen == 19:
		var limit: String = "9223372036854775808" if negative else "9223372036854775807"
		if digits > limit:
			return null
		if negative and digits == "9223372036854775808":
			return -9223372036854775807 - 1
	var mag: int = int(digits)
	return -mag if negative else mag


func coerce_int(value: Variant, fallback: int = 0) -> int:
	if value == null:
		return fallback
	var t: int = typeof(value)
	if t == TYPE_INT:
		return int(value)
	if t == TYPE_FLOAT:
		var f: float = float(value)
		if is_finite(f) and f >= -9223372036854775808.0 and f < 9223372036854775808.0:
			return int(f)
		return fallback
	if t == TYPE_STRING:
		var s: String = sanitize_text(str(value)).strip_edges()
		var parsed_i64: Variant = _parse_int64_str(s)
		if parsed_i64 != null:
			return int(parsed_i64)
		if s.is_valid_int():
			return fallback
		if s.is_valid_float():
			var fs: float = s.to_float()
			if is_finite(fs) and fs >= -9223372036854775808.0 and fs < 9223372036854775808.0:
				return int(fs)
	return fallback


func coerce_float(value: Variant, fallback: float = 0.0) -> float:
	if value == null:
		return fallback
	var t: int = typeof(value)
	if t == TYPE_INT:
		return float(value)
	if t == TYPE_FLOAT:
		var f: float = float(value)
		return f if is_finite(f) else fallback
	if t == TYPE_STRING:
		var s: String = sanitize_text(str(value)).strip_edges()
		if s.is_valid_float():
			var fs: float = s.to_float()
			if is_finite(fs):
				return fs
	return fallback


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


func compute_source_to_world_scale(source_units_per_cell: float = DEFAULT_SOURCE_UNITS_PER_CELL) -> float:
	var safe_units: float = source_units_per_cell if is_finite(source_units_per_cell) else DEFAULT_SOURCE_UNITS_PER_CELL
	return WORLD_UNITS_PER_CELL / maxf(0.0001, safe_units)


func is_cancelled(host: RefCounted) -> bool:
	if host != null and host.has_method("cancelled"):
		return bool(host.cancelled())
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
		var world_bounds := Rect2(safe_pos * safe_scale, safe_size * safe_scale)
		host.begin_preview(maxi(0, total_items), world_bounds)


func preview_entity(host: RefCounted, entity: Dictionary, preview_kind: String) -> void:
	if host != null and host.has_method("preview_entity"):
		host.preview_entity(entity, preview_kind)


func finish_geometry_preview(host: RefCounted) -> bool:
	if host != null and host.has_method("finish_geometry_preview"):
		return bool(host.finish_geometry_preview())
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
		var key_name: String = str(raw_key)
		counts[key_name] = int(counts_override[raw_key])

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

	var schema_name: String = str(layers_root.get("schema", ""))
	if schema_name != FLOOR_LAYERS_SCHEMA:
		return build_failed("请更新本地程序后使用此版场景结构导入。")

	var floors_var: Variant = layers_root.get("floors", [])
	if not (floors_var is Array) or (floors_var as Array).is_empty():
		return build_failed("missing_world_floors")
	var floors: Array = floors_var

	var floor_uid: String = str(catalog.get("active_floor_uid", ""))
	var target_floor: Dictionary = {}
	for raw_floor: Variant in floors:
		if raw_floor is Dictionary:
			var floor_dict: Dictionary = raw_floor
			if not floor_uid.is_empty() and str(floor_dict.get("floor_uid", "")) == floor_uid:
				target_floor = floor_dict
				break
	if target_floor.is_empty() and floors[0] is Dictionary:
		target_floor = floors[0]
		if floor_uid.is_empty():
			floor_uid = str(target_floor.get("floor_uid", ""))

	var layer_rows_var: Variant = target_floor.get("layers", [])
	if not (layer_rows_var is Array):
		return build_failed("invalid_floor_layers")

	var layer_map: Dictionary = {}
	for raw_layer: Variant in layer_rows_var as Array:
		if raw_layer is Dictionary:
			var layer_row: Dictionary = raw_layer
			var layer_kind: String = str(layer_row.get("kind", ""))
			var layer_uid: String = str(layer_row.get("layer_uid", ""))
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
	if not bool(initial.get("ok", false)):
		return initial

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
			existing_floor_uids[str((raw_floor as Dictionary).get("floor_uid", ""))] = true

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
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return build_failed("invalid_world_catalog")
	var catalog: Dictionary = catalog_var
	var floors_var: Variant = catalog.get("floors", null)
	if not (floors_var is Array):
		return build_failed("missing_world_floors")
	for raw_floor: Variant in floors_var as Array:
		if raw_floor is Dictionary and str((raw_floor as Dictionary).get("floor_uid", "")) == floor_uid:
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
			if str(fd.get("floor_uid", "")) == floor_uid:
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
					if str(lfd.get("floor_uid", "")) == floor_uid and lfd.has("name"):
						lfd["name"] = clean_name
						break

	return {"ok": true, "floor_uid": floor_uid, "name": clean_name}


func get_floor_layer_map(world: Dictionary, floor_uid: String) -> Dictionary:
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
		if raw_floor is Dictionary and str((raw_floor as Dictionary).get("floor_uid", "")) == floor_uid:
			var layer_map: Dictionary = {}
			var rows_var: Variant = (raw_floor as Dictionary).get("layers", [])
			if rows_var is Array:
				for raw_layer: Variant in rows_var as Array:
					if raw_layer is Dictionary:
						var layer_row: Dictionary = raw_layer
						var k: String = str(layer_row.get("kind", ""))
						var uid: String = str(layer_row.get("layer_uid", ""))
						if not k.is_empty() and not uid.is_empty() and not layer_map.has(k):
							layer_map[k] = uid
			return layer_map
	return {}


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
		var viewer_key: String = sanitize_catalog_name(str(raw_viewer), "")
		if viewer_key.is_empty() or viewer_key.length() > MAX_VIEWER_KEY_LENGTH or seen_viewers.has(viewer_key):
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
		if raw_floor is Dictionary and str((raw_floor as Dictionary).get("floor_uid", "")) == floor_uid:
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
		"source": source_meta.duplicate(true),
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
		"source_info": source_info.duplicate(true),
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
			if outer_pts.size() < 3:
				skipped_rings += 1
				continue
			var valid_holes: Array = []
			var holes_var: Variant = face_dict.get("holes", [])
			if holes_var is Array:
				for raw_hole: Variant in holes_var as Array:
					var hole_pts: Array = _extract_vec2_ring(raw_hole)
					if hole_pts.size() < 3:
						skipped_rings += 1
						continue
					valid_holes.append(hole_pts)
					all_rings.append(hole_pts)
			all_rings.append(outer_pts)
			faces.append({"outer": outer_pts, "holes": valid_holes})
		else:
			var ring_pts: Array = _extract_vec2_ring(raw_poly)
			if ring_pts.size() < 3:
				skipped_rings += 1
				continue
			all_rings.append(ring_pts)
			faces.append({"outer": ring_pts, "holes": []})

	var size: Vector2 = MIN_ENTITY_SIZE
	for raw_ring: Variant in all_rings:
		var pts_list: Array = raw_ring
		for raw_pt: Variant in pts_list:
			var pt: Vector2 = raw_pt
			size = size.max(Vector2(absf(pt.x), absf(pt.y)) * 2.0)

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
	var ids := PackedStringArray()
	var seen: Dictionary = {}
	for raw_id: Variant in owner_player_ids:
		var clean_id: String = sanitize_text(str(raw_id)).strip_edges()
		if not clean_id.is_empty() and not seen.has(clean_id):
			seen[clean_id] = true
			ids.append(clean_id)
	return {
		"owners_csv": sanitize_text(owners_csv).strip_edges(),
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
		normalized_key = clean if is_valid_uid(clean) else ("fu_sdk:portal:" + clean).sha256_text().left(32)
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
	var safe_offset: Vector2 = sanitize_finite_vec2(offset, Vector2.ZERO)
	return {
		"schema": "fus.grid_alignment.config",
		"version": 1,
		"cell_size": clampf(sanitize_finite_float(cell_size, 64.0), 8.0, 4096.0),
		"offset": [safe_offset.x, safe_offset.y],
		"color": [
			clampf(sanitize_finite_float(color.r, 0.5), 0.0, 1.0),
			clampf(sanitize_finite_float(color.g, 0.55), 0.0, 1.0),
			clampf(sanitize_finite_float(color.b, 0.65), 0.0, 1.0),
			clampf(sanitize_finite_float(color.a, 0.7), 0.0, 1.0),
		],
		"line_width": clampf(sanitize_finite_float(line_width, 1.0), 0.1, 32.0),
		"snap_enabled": snap_enabled,
		"snap_strength": clampf(sanitize_finite_float(snap_strength, 0.1), 0.0, 1.0),
	}


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
	if is_zero_approx(safe_factor):
		safe_factor = compute_source_to_world_scale()
	var safe_scale: Vector2 = sanitize_nonzero_scale(scale, Vector2.ONE)
	var world_scale: Vector2 = sanitize_nonzero_scale(safe_scale * safe_factor, Vector2(safe_factor, safe_factor))
	var safe_footprint: float = sanitize_footprint_radius(footprint_radius)

	var safe_visual: Dictionary = visual.duplicate(true)
	if safe_visual.has("sprite_path"):
		var checked_sprite: Dictionary = sanitize_sprite_path(str(safe_visual.get("sprite_path", "")))
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
			"pos": safe_center * safe_factor,
			"rot": safe_rot,
			"scale": world_scale,
		},
		"flags": {
			"entity_hidden": hidden,
			"entity_locked": locked,
		},
		"components": [
			{"script": COMP_VISUAL_SCRIPT, "state": safe_visual},
			{"script": COMP_PERMISSION_SCRIPT, "state": permission_state.duplicate(true)},
		],
	}

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
	var entity_state_var: Variant = world.get("entity_state", null)
	if not (entity_state_var is Dictionary):
		return {}
	var entities_var: Variant = (entity_state_var as Dictionary).get("entities", null)
	if not (entities_var is Array):
		return {}
	var ents: Array = entities_var as Array
	for i: int in range(ents.size() - 1, -1, -1):
		var raw_entity: Variant = ents[i]
		if raw_entity is Dictionary and str((raw_entity as Dictionary).get("id", "")) == entity_id:
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


func append_entity_component(
	entity: Dictionary,
	script_path: String,
	state: Dictionary = {},
	parked: bool = false
) -> Dictionary:
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
	var first_script: String = str((components[0] as Dictionary).get("script", "")) if components[0] is Dictionary else ""
	var second_script: String = str((components[1] as Dictionary).get("script", "")) if components[1] is Dictionary else ""
	if first_script != COMP_VISUAL_SCRIPT or second_script != COMP_PERMISSION_SCRIPT:
		return build_failed("core_components_prefix_corrupted")

	var comp_id: String = _component_id_from_script(clean_script)
	if comp_id.is_empty() or comp_id == "visual" or comp_id == "permission":
		return build_failed("invalid_component_id")

	var record: Dictionary = {
		"script": clean_script,
		"state": state.duplicate(true),
	}
	if parked:
		record["parked"] = true

	# 仅允许在索引 >= 2 更新或追加，绝不破坏 components[0..1] == [visual, permission] 不变量。
	for idx: int in range(2, components.size()):
		if components[idx] is Dictionary:
			var existing_script: String = str((components[idx] as Dictionary).get("script", ""))
			if existing_script == clean_script or _component_id_from_script(existing_script) == comp_id:
				components[idx] = record
				return {"ok": true, "index": idx, "replaced": true}

	components.append(record)
	return {"ok": true, "index": components.size() - 1, "replaced": false}


func sanitize_module_value(v: Variant, depth: int = 0) -> Variant:
	if depth > 32:
		return null
	match typeof(v):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_STRING:
			return v
		TYPE_STRING_NAME, TYPE_NODE_PATH:
			return str(v)
		TYPE_FLOAT:
			var f: float = float(v)
			return f if is_finite(f) else 0.0
		TYPE_ARRAY:
			var out_arr: Array = []
			for item: Variant in v as Array:
				out_arr.append(sanitize_module_value(item, depth + 1))
			return out_arr
		TYPE_DICTIONARY:
			var out_dict: Dictionary = {}
			var d: Dictionary = v as Dictionary
			for k: Variant in d.keys():
				var ks: String = k if (k is String) else str(k)
				out_dict[ks] = sanitize_module_value(d[k], depth + 1)
			return out_dict
		_:
			return null


func bounded_variant_size_estimate(val: Variant, depth: int = 0) -> int:
	if depth > 32:
		return -1
	match typeof(val):
		TYPE_STRING, TYPE_STRING_NAME, TYPE_NODE_PATH:
			return 16 + str(val).length() * 4
		TYPE_PACKED_BYTE_ARRAY:
			return 16 + (val as PackedByteArray).size()
		TYPE_PACKED_INT32_ARRAY:
			return 16 + (val as PackedInt32Array).size() * 4
		TYPE_PACKED_FLOAT32_ARRAY:
			return 16 + (val as PackedFloat32Array).size() * 4
		TYPE_PACKED_INT64_ARRAY:
			return 16 + (val as PackedInt64Array).size() * 8
		TYPE_PACKED_FLOAT64_ARRAY:
			return 16 + (val as PackedFloat64Array).size() * 8
		TYPE_PACKED_VECTOR2_ARRAY:
			return 16 + (val as PackedVector2Array).size() * 16
		TYPE_PACKED_VECTOR3_ARRAY:
			return 16 + (val as PackedVector3Array).size() * 24
		TYPE_PACKED_VECTOR4_ARRAY:
			return 16 + (val as PackedVector4Array).size() * 32
		TYPE_PACKED_COLOR_ARRAY:
			return 16 + (val as PackedColorArray).size() * 32
		TYPE_PACKED_STRING_ARRAY:
			if depth + 1 > 32:
				return -1
			var total_ps: int = 16
			for s: String in val as PackedStringArray:
				total_ps += 16 + s.length() * 4
			return total_ps
		TYPE_DICTIONARY:
			var total_d: int = 16
			var d: Dictionary = val as Dictionary
			for k: Variant in d.keys():
				var kc: int = bounded_variant_size_estimate(k, depth + 1)
				if kc < 0:
					return -1
				var vc: int = bounded_variant_size_estimate(d[k], depth + 1)
				if vc < 0:
					return -1
				total_d += kc + vc
			return total_d
		TYPE_ARRAY:
			var total_a: int = 16
			for item: Variant in val as Array:
				var ic: int = bounded_variant_size_estimate(item, depth + 1)
				if ic < 0:
					return -1
				total_a += ic
			return total_a
		_:
			return 256


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
	var entry_var_bytes: int = var_to_bytes(state).size()
	if entry_var_bytes > MAX_MODULE_ENTRY_BYTES:
		return false
	var entry_bounded: int = bounded_variant_size_estimate(state)
	if entry_bounded < 0 or entry_bounded > MAX_MODULE_ENTRY_BYTES:
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

	if var_to_bytes(mods_copy).size() > MAX_MODULE_TOTAL_BYTES:
		return false
	var total_bounded: int = bounded_variant_size_estimate(mods_copy)
	if total_bounded < 0 or total_bounded > MAX_MODULE_TOTAL_BYTES:
		return false

	if max_world_bytes > 0:
		var cur_world_bytes: int = var_to_bytes(world).size()
		var prev_entry_bytes: int = 0
		var real_entries: Variant = (mods_var as Dictionary).get("entries", {}) if (mods_var is Dictionary) else {}
		if real_entries is Dictionary and (real_entries as Dictionary).has(clean_id):
			prev_entry_bytes = var_to_bytes((real_entries as Dictionary)[clean_id]).size()
		var new_entry_bytes: int = var_to_bytes(new_entry).size()
		if cur_world_bytes - prev_entry_bytes + new_entry_bytes > max_world_bytes:
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

	if not (world.get("modules", null) is Dictionary):
		world["modules"] = {"version": MODULE_STATE_VERSION, "entries": {}}
	var modules_dict: Dictionary = world["modules"]
	if not (modules_dict.get("entries", null) is Dictionary):
		modules_dict["entries"] = {}
	var entries: Dictionary = modules_dict["entries"]
	if not entries.has(clean_id) and entries.size() >= MAX_MODULE_ENTRIES:
		return build_failed("module_entries_limit_exceeded")

	var copied_state: Dictionary = state.duplicate(true)
	if var_to_bytes(copied_state).size() > MAX_MODULE_ENTRY_BYTES:
		return build_failed("module_entry_size_limit")

	var prev_present: bool = entries.has(clean_id)
	var prev_value: Variant = entries.get(clean_id, null)
	entries[clean_id] = {
		"version": version,
		"state": copied_state,
	}
	if var_to_bytes(modules_dict).size() > MAX_MODULE_TOTAL_BYTES:
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
	var entities_var: Variant = world.get("entity_state", {}).get("entities", [])
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
						var uid: String = str((raw_layer as Dictionary).get("layer_uid", ""))
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


func _component_id_from_script(script_path: String) -> String:
	var base: String = script_path.get_file().get_basename()
	return base.substr(5) if base.begins_with("comp_") else base


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
				pt = Vector2(float(pair[0]), float(pair[1]))
				ok = true
			elif raw_pt is Dictionary:
				var pt_dict: Dictionary = raw_pt
				pt = Vector2(float(pt_dict.get("x", 0.0)), float(pt_dict.get("y", 0.0)))
				ok = true
			if ok and is_finite(pt.x) and is_finite(pt.y):
				result.append(pt)
	return result
