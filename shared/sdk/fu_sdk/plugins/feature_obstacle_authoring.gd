extends RefCounted
## Fu vtt 原生核心插件 SDK：feature_obstacle_authoring（障碍物与视距遮挡编写）
##
## 对应官方源码：modules/obstacle_authoring/feature_obstacle_authoring.gd、
## comp_obstacle.gd、obstacle_shape_data.gd、scenes/entities/components/vector_drawing.gd。

const MODULE_ID: String = "feature_obstacle_authoring"
const COMP_OBSTACLE_SCRIPT: String = "res://modules/obstacle_authoring/comp_obstacle.gd"
const COMP_IMAGE_FLIP_SCRIPT: String = "res://modules/image_flip/comp_image_flip.gd"
const COMP_SCENE_BOX_SCRIPT: String = "res://modules/scene_box/comp_scene_box.gd"

const ROLES: Array[String] = ["object", "wall", "air", "door", "window", "glass"]
const DRAWING_KINDS: Array[String] = ["wall", "air", "door", "window", "glass"]
const SHAPE_MODES: Array[String] = ["manual", "drawing"]

const SHAPE_SCHEMA: int = 1
const MAX_CLONE_VISITS: int = 2097152
const MAX_CLONE_BYTES: int = 16 * 1024 * 1024
const MAX_RADIUS: float = 4096.0
const MAX_PATHS: int = 8192
const MAX_PATH_POINTS: int = 200000
const MAX_SEGMENTS: int = 400000

const DOOR_CLOSED_COLOR: Color = Color(0.91, 0.57, 0.15, 1.0)
const DOOR_OPEN_COLOR: Color = Color(0.91, 0.57, 0.15, 0.6)
const WINDOW_CLOSED_COLOR: Color = Color(0.22, 0.56, 0.92, 0.9)
const WINDOW_OPEN_COLOR: Color = Color(0.22, 0.56, 0.92, 0.45)

var _world_builder_ref: WeakRef = null
var _module_registry: RefCounted = null
var _log_bus: RefCounted = null
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


func configure(
	world_builder: RefCounted,
	module_registry: RefCounted = null,
	log_bus: RefCounted = null
) -> void:
	_world_builder_ref = weakref(world_builder) if world_builder != null else null
	_module_registry = module_registry
	_log_bus = log_bus


func _wb() -> RefCounted:
	if _world_builder_ref == null:
		return null
	var inst: Variant = _world_builder_ref.get_ref()
	return inst as RefCounted if inst is RefCounted else null


func is_enabled() -> bool:
	if _module_registry != null:
		return bool(_module_registry.is_module_enabled(MODULE_ID))
	return true


func get_availability() -> Dictionary:
	if _module_registry != null:
		return _module_registry.get_module_entry(MODULE_ID)
	return {
		"id": MODULE_ID,
		"core": true,
		"status": "core",
		"enabled": true,
	}


func add_polygon_obstacle(
	source_id: String,
	name: String,
	center_src: Vector2,
	polygons_src: Array,
	kind: String = "wall",
	is_open_door: bool = false,
	enabled: bool = true,
	layer_uid_override: String = ""
) -> String:
	var gate: Dictionary = _check_gate("add_polygon_obstacle")
	if not bool(gate.get("ok", true)):
		return ""
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	return str(wb.add_polygon_obstacle(
		source_id,
		name,
		center_src,
		polygons_src,
		kind,
		is_open_door,
		enabled,
		layer_uid_override
	))


func add_wall(
	source_id: String,
	name: String,
	center_src: Vector2,
	polygons_src: Array,
	enabled: bool = true,
	layer_uid_override: String = ""
) -> String:
	return add_polygon_obstacle(source_id, name, center_src, polygons_src, "wall", false, enabled, layer_uid_override)


func add_door(
	source_id: String,
	name: String,
	center_src: Vector2,
	polygons_src: Array,
	is_open: bool = false,
	enabled: bool = true,
	layer_uid_override: String = ""
) -> String:
	return add_polygon_obstacle(source_id, name, center_src, polygons_src, "door", is_open, enabled, layer_uid_override)


func add_window(
	source_id: String,
	name: String,
	center_src: Vector2,
	polygons_src: Array,
	is_open: bool = false,
	enabled: bool = true,
	layer_uid_override: String = ""
) -> String:
	return add_polygon_obstacle(source_id, name, center_src, polygons_src, "window", is_open, enabled, layer_uid_override)


func add_glass_wall(
	source_id: String,
	name: String,
	center_src: Vector2,
	polygons_src: Array,
	enabled: bool = true,
	layer_uid_override: String = ""
) -> String:
	return add_polygon_obstacle(source_id, name, center_src, polygons_src, "glass", false, enabled, layer_uid_override)


func add_air_cutout(
	source_id: String,
	name: String,
	center_src: Vector2,
	polygons_src: Array,
	enabled: bool = true,
	layer_uid_override: String = ""
) -> String:
	return add_polygon_obstacle(source_id, name, center_src, polygons_src, "air", false, enabled, layer_uid_override)


func extrude_segment_to_quad(
	p0: Vector2,
	p1: Vector2,
	half_width: float = 6.0,
	min_length: float = 0.5
) -> PackedVector2Array:
	var wb: RefCounted = _wb()
	if wb == null:
		return PackedVector2Array()
	return wb.extrude_segment_to_quad(p0, p1, half_width, min_length)


func add_segment_obstacle(
	source_id: String,
	name: String,
	p0_src: Vector2,
	p1_src: Vector2,
	half_width_src: float = 6.0,
	kind: String = "wall",
	is_open_door: bool = false,
	enabled: bool = true,
	layer_uid_override: String = ""
) -> String:
	var gate: Dictionary = _check_gate("add_segment_obstacle")
	if not bool(gate.get("ok", true)):
		return ""
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	return str(wb.add_segment_obstacle(
		source_id,
		name,
		p0_src,
		p1_src,
		half_width_src,
		kind,
		is_open_door,
		enabled,
		layer_uid_override
	))


func add_segment_wall(
	source_id: String,
	name: String,
	p0_src: Vector2,
	p1_src: Vector2,
	half_width_src: float = 6.0,
	enabled: bool = true,
	layer_uid_override: String = ""
) -> String:
	return add_segment_obstacle(source_id, name, p0_src, p1_src, half_width_src, "wall", false, enabled, layer_uid_override)


func add_segment_door(
	source_id: String,
	name: String,
	p0_src: Vector2,
	p1_src: Vector2,
	half_width_src: float = 6.0,
	is_open: bool = false,
	enabled: bool = true,
	layer_uid_override: String = ""
) -> String:
	return add_segment_obstacle(source_id, name, p0_src, p1_src, half_width_src, "door", is_open, enabled, layer_uid_override)


func add_segment_window(
	source_id: String,
	name: String,
	p0_src: Vector2,
	p1_src: Vector2,
	half_width_src: float = 6.0,
	is_open: bool = false,
	enabled: bool = true,
	layer_uid_override: String = ""
) -> String:
	return add_segment_obstacle(source_id, name, p0_src, p1_src, half_width_src, "window", is_open, enabled, layer_uid_override)


func add_segment_glass_wall(
	source_id: String,
	name: String,
	p0_src: Vector2,
	p1_src: Vector2,
	half_width_src: float = 6.0,
	enabled: bool = true,
	layer_uid_override: String = ""
) -> String:
	return add_segment_obstacle(source_id, name, p0_src, p1_src, half_width_src, "glass", false, enabled, layer_uid_override)


func make_circle_shape(diameter: float = 64.0) -> Dictionary:
	var safe_diameter: float = diameter if (is_finite(diameter) and diameter > 0.0) else 64.0
	var radius: float = clampf(safe_diameter * 0.5, 0.5, MAX_RADIUS)
	var final_diameter: float = radius * 2.0
	var shape: Dictionary = {
		"schema": SHAPE_SCHEMA,
		"kind": "circle",
		"radius": radius,
		"basis_size": Vector2.ONE,
		"paths": [],
		"segments": PackedVector2Array(),
		"bounds": Rect2(Vector2(-radius, -radius), Vector2(final_diameter, final_diameter)),
	}
	shape["uid"] = compute_shape_digest(shape)
	return shape


func make_polygon_shape(
	paths: Array,
	basis_size: Vector2 = Vector2(64.0, 64.0),
	segments: PackedVector2Array = PackedVector2Array()
) -> Dictionary:
	var clean_paths: Array = []
	var total_points: int = 0
	var min_pt := Vector2(INF, INF)
	var max_pt := Vector2(-INF, -INF)

	for raw_ring: Variant in paths:
		var ring := PackedVector2Array()
		var ring_valid: bool = true
		if raw_ring is PackedVector2Array:
			for pt_raw: Vector2 in raw_ring as PackedVector2Array:
				if not is_finite(pt_raw.x) or not is_finite(pt_raw.y):
					ring_valid = false
					break
				ring.append(pt_raw)
		elif raw_ring is Array:
			for p: Variant in raw_ring as Array:
				if not (p is Vector2):
					ring_valid = false
					break
				var pt_v: Vector2 = p as Vector2
				if not is_finite(pt_v.x) or not is_finite(pt_v.y):
					ring_valid = false
					break
				ring.append(pt_v)
		else:
			continue
		if not ring_valid or not _is_valid_polygon_ring(ring):
			continue
		if clean_paths.size() >= MAX_PATHS or total_points + ring.size() > MAX_PATH_POINTS:
			break
		clean_paths.append(ring)
		total_points += ring.size()
		for pt: Vector2 in ring:
			min_pt.x = minf(min_pt.x, pt.x)
			min_pt.y = minf(min_pt.y, pt.y)
			max_pt.x = maxf(max_pt.x, pt.x)
			max_pt.y = maxf(max_pt.y, pt.y)

	var bounds := Rect2(Vector2.ZERO, Vector2.ZERO)
	if is_finite(min_pt.x) and is_finite(max_pt.x):
		var span: Vector2 = max_pt - min_pt
		if not is_finite(span.x) or not is_finite(span.y):
			clean_paths.clear()
		else:
			bounds = Rect2(min_pt, span)

	var final_segments: PackedVector2Array = segments if (_valid_segments(segments) and not clean_paths.is_empty()) else PackedVector2Array()
	if final_segments.is_empty() and not clean_paths.is_empty():
		final_segments = PackedVector2Array()
		for raw_ring: Variant in clean_paths:
			var ring: PackedVector2Array = raw_ring as PackedVector2Array
			var n: int = ring.size()
			for i: int in range(n):
				if final_segments.size() + 2 > MAX_SEGMENTS:
					break
				final_segments.append(ring[i])
				final_segments.append(ring[(i + 1) % n])

	var safe_basis := Vector2(
		basis_size.x if (is_finite(basis_size.x) and basis_size.x > 0.0) else 64.0,
		basis_size.y if (is_finite(basis_size.y) and basis_size.y > 0.0) else 64.0
	)

	var shape: Dictionary = {
		"schema": SHAPE_SCHEMA,
		"kind": "polygon",
		"radius": 0.0,
		"basis_size": safe_basis,
		"paths": clean_paths,
		"segments": final_segments,
		"bounds": bounds,
	}
	shape["uid"] = compute_shape_digest(shape)
	return shape


func compute_shape_digest(shape: Dictionary) -> String:
	var schema_var: Variant = shape.get("schema")
	var kind_var: Variant = shape.get("kind")
	var radius_var: Variant = shape.get("radius")
	var basis_var: Variant = shape.get("basis_size")
	var paths_var: Variant = shape.get("paths")
	var segments_var: Variant = shape.get("segments")
	var bounds_var: Variant = shape.get("bounds")
	if not (schema_var is int):
		return ""
	if not (kind_var is String or kind_var is StringName):
		return ""
	if not (radius_var is int or radius_var is float):
		return ""
	if not (basis_var is Vector2):
		return ""
	if not (bounds_var is Rect2):
		return ""
	if not (paths_var is Array):
		return ""
	var paths_arr: Array = paths_var as Array
	if paths_arr.size() > MAX_PATHS:
		return ""
	var total_pts: int = 0
	for ring_v: Variant in paths_arr:
		if not (ring_v is PackedVector2Array):
			return ""
		total_pts += (ring_v as PackedVector2Array).size()
		if total_pts > MAX_PATH_POINTS:
			return ""
	if not (segments_var is PackedVector2Array) or (segments_var as PackedVector2Array).size() > MAX_SEGMENTS:
		return ""
	var payload: Array = [
		schema_var,
		kind_var,
		radius_var,
		basis_var,
		paths_arr,
		segments_var,
		bounds_var,
	]
	var bytes: PackedByteArray = var_to_bytes(payload)
	var hashing := HashingContext.new()
	hashing.start(HashingContext.HASH_SHA256)
	hashing.update(bytes)
	return hashing.finish().hex_encode()


func make_obstacle_state(
	role: String = "object",
	shape_mode: String = "manual",
	diameter: float = 64.0,
	shape: Dictionary = {},
	cache: Dictionary = {}
) -> Dictionary:
	var clean_role: String = role.strip_edges().to_lower()
	if not (clean_role in ROLES):
		clean_role = "object"
	var clean_mode: String = shape_mode.strip_edges().to_lower()
	if not (clean_mode in SHAPE_MODES):
		clean_mode = "manual"
	var final_shape: Dictionary = _safe_clone_dict(shape)
	if final_shape.is_empty() and clean_mode == "manual":
		final_shape = make_circle_shape(diameter)
	return {
		"role": clean_role,
		"shape_mode": clean_mode,
		"shape": final_shape,
		"cache": _safe_clone_dict(cache),
	}


func attach_obstacle(
	entity_id: String,
	role: String = "object",
	shape_mode: String = "manual",
	diameter: float = 64.0,
	parked: bool = false,
	manual_parked: bool = false,
	shape: Dictionary = {},
	cache: Dictionary = {}
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_obstacle")
	if not bool(gate.get("ok", true)):
		return gate
	if manual_parked and not parked:
		return {"ok": false, "reason": "manual_requires_parked"}

	var clean_role: String = role.strip_edges().to_lower()
	if not (clean_role in ROLES):
		return {"ok": false, "reason": "invalid_obstacle_role:" + role}
	var clean_mode: String = shape_mode.strip_edges().to_lower()
	if not (clean_mode in SHAPE_MODES):
		return {"ok": false, "reason": "invalid_shape_mode:" + shape_mode}

	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return {"ok": false, "reason": "entity_not_found"}

	if _has_component_script(entity, COMP_SCENE_BOX_SCRIPT):
		return {"ok": false, "reason": "component_conflict_with_scene_box:obstacle"}
	if _has_component_script(entity, COMP_IMAGE_FLIP_SCRIPT):
		return {"ok": false, "reason": "component_conflict_with_image_flip"}

	var final_shape: Dictionary = _safe_clone_dict(shape)
	if not shape.is_empty() and final_shape.is_empty():
		return {"ok": false, "reason": "invalid_obstacle_state", "errors": ["invalid_shape_payload"]}
	if final_shape.is_empty() and clean_mode == "manual":
		final_shape = make_circle_shape(diameter)
	var safe_cache: Dictionary = _safe_clone_dict(cache)
	if not cache.is_empty() and safe_cache.is_empty():
		return {"ok": false, "reason": "invalid_obstacle_state", "errors": ["invalid_cache_payload"]}
	var state: Dictionary = {
		"role": clean_role,
		"shape_mode": clean_mode,
		"shape": final_shape,
		"cache": safe_cache,
	}
	var check: Dictionary = validate_obstacle_state(state)
	if not bool(check.get("ok", false)):
		return {"ok": false, "reason": "invalid_obstacle_state", "errors": check.get("errors", [])}

	if clean_mode == "drawing":
		var vkind: String = _get_entity_drawing_kind(entity)
		if not (vkind in DRAWING_KINDS):
			_warn("实体 '%s' 以 drawing 模式挂载 comp_obstacle，但其 comp_visual.vector_drawing.source.kind='%s' 非障碍物绘图类型。" % [entity_id, vkind])

	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_OBSTACLE_SCRIPT,
		state,
		parked,
		manual_parked
	))
	if not ok:
		return {"ok": false, "reason": "attach_component_failed"}
	return {
		"ok": true,
		"entity_id": entity_id,
		"role": clean_role,
		"shape_mode": clean_mode,
		"parked": parked,
		"manual": parked and manual_parked,
	}


func set_door_open(entity_id: String, is_open: bool) -> bool:
	var gate: Dictionary = _check_gate("set_door_open")
	if not bool(gate.get("ok", true)):
		return false
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return false
	var visual: Dictionary = _get_visual_state(entity)
	if visual.is_empty():
		return false
	var vec_var: Variant = visual.get("vector_drawing", null)
	if not (vec_var is Dictionary):
		return false
	var vec: Dictionary = vec_var as Dictionary
	var src_var: Variant = vec.get("source", null)
	if not (src_var is Dictionary):
		return false
	var src: Dictionary = src_var as Dictionary
	var kind: String = str(_value_utils().as_str(src.get("kind", "")))
	if kind != "door" and kind != "window":
		return false
	src["open"] = is_open
	var target_color: Color
	if kind == "door":
		target_color = DOOR_OPEN_COLOR if is_open else DOOR_CLOSED_COLOR
	else:
		target_color = WINDOW_OPEN_COLOR if is_open else WINDOW_CLOSED_COLOR
	vec["color"] = target_color
	vec["line_color"] = target_color
	return true


func set_obstacle_enabled(entity_id: String, enabled: bool) -> bool:
	var gate: Dictionary = _check_gate("set_obstacle_enabled")
	if not bool(gate.get("ok", true)):
		return false
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return false
	var visual: Dictionary = _get_visual_state(entity)
	if visual.is_empty():
		return false
	var vec_var: Variant = visual.get("vector_drawing", null)
	if vec_var is Dictionary:
		var src_var: Variant = (vec_var as Dictionary).get("source", null)
		if src_var is Dictionary and str(_value_utils().as_str((src_var as Dictionary).get("kind", ""))) in DRAWING_KINDS:
			(src_var as Dictionary)["enabled"] = enabled
			return true
	if _has_component_script(entity, COMP_OBSTACLE_SCRIPT):
		visual["enabled"] = enabled
		return true
	return false


func validate_obstacle_state(state: Dictionary) -> Dictionary:
	var errors: Array[String] = []
	if state.is_empty():
		return {"ok": false, "errors": ["obstacle_state_empty"]}

	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	var role: String = str(val_u.as_str(state.get("role", "")))
	if not (role in ROLES):
		errors.append("invalid_obstacle_role:" + role)

	var shape_mode: String = str(val_u.as_str(state.get("shape_mode", "")))
	if not (shape_mode in SHAPE_MODES):
		errors.append("invalid_shape_mode:" + shape_mode)

	var shape_var: Variant = state.get("shape", null)
	if not (shape_var is Dictionary):
		errors.append("invalid_shape_type")
	else:
		var shape: Dictionary = shape_var as Dictionary
		if not shape.is_empty():
			var shape_err_start: int = errors.size()
			var schema_var: Variant = shape.get("schema", null)
			if not (schema_var is int) or int(schema_var) != SHAPE_SCHEMA:
				errors.append("invalid_shape_schema")
			var kind: String = str(val_u.as_str(shape.get("kind", "")))
			if kind != "circle" and kind != "polygon":
				errors.append("invalid_shape_kind:" + kind)
			var basis_var: Variant = shape.get("basis_size", null)
			if not (basis_var is Vector2):
				errors.append("invalid_shape_basis_size")
			else:
				var basis: Vector2 = basis_var as Vector2
				if not is_finite(basis.x) or not is_finite(basis.y) or basis.x <= 0.0 or basis.y <= 0.0:
					errors.append("invalid_shape_basis_size")
			var paths_var: Variant = shape.get("paths", null)
			if not (paths_var is Array) or not _valid_paths(paths_var as Array):
				errors.append("invalid_shape_paths")
			elif kind == "polygon" and (paths_var as Array).is_empty():
				errors.append("empty_polygon_paths")
			var segs_var: Variant = shape.get("segments", null)
			if not _valid_segments(segs_var):
				errors.append("invalid_shape_segments")
			var bounds_var: Variant = shape.get("bounds", null)
			if not (bounds_var is Rect2) or not _is_finite_rect2(bounds_var as Rect2):
				errors.append("invalid_shape_bounds")
			var rad_var: Variant = shape.get("radius", null)
			if not (rad_var is float):
				errors.append("invalid_shape_radius_type")
			else:
				var r: float = float(rad_var)
				if not is_finite(r) or r < 0.0:
					errors.append("invalid_shape_radius")
				elif kind == "circle" and (r <= 0.0 or r > MAX_RADIUS):
					errors.append("circle_radius_out_of_range")
			var uid: Variant = shape.get("uid", null)
			# 沿用原 _is_valid_sha256 严格小写 [0-9a-f]{64} 契约（strict lowercase SHA-256 hex）
			if not (uid is String) or not bool(valid_u.is_valid_hex64(uid as String, false)):
				errors.append("invalid_shape_uid")
			elif errors.size() == shape_err_start:
				var expected_uid: String = compute_shape_digest(shape)
				if str(uid) != expected_uid:
					errors.append("shape_digest_mismatch")

	var cache_var: Variant = state.get("cache", {})
	if not (cache_var is Dictionary):
		errors.append("invalid_cache_type")
	else:
		var cache: Dictionary = cache_var as Dictionary
		if not cache.is_empty():
			var ckey: Variant = cache.get("key", null)
			# 沿用原 _is_valid_sha256 严格小写 [0-9a-f]{64} 契约（strict lowercase SHA-256 hex）
			if not (ckey is String) or not bool(valid_u.is_valid_hex64(ckey as String, false)):
				errors.append("invalid_cache_key")
			var cpaths: Variant = cache.get("paths", null)
			if not (cpaths is Array) or not _valid_paths(cpaths as Array):
				errors.append("invalid_cache_paths")
			var csegs: Variant = cache.get("segments", null)
			if not _valid_segments(csegs):
				errors.append("invalid_cache_segments")
			var dver: Variant = cache.get("digest_version", 1)
			if not (dver is int) or not (int(dver) in [1, 2]):
				errors.append("invalid_cache_digest_version")

	return {
		"ok": errors.is_empty(),
		"errors": errors,
	}


func _valid_paths(paths: Array) -> bool:
	if paths.size() > MAX_PATHS:
		return false
	var points: int = 0
	for ring: Variant in paths:
		if not (ring is PackedVector2Array):
			return false
		var r: PackedVector2Array = ring as PackedVector2Array
		if not _is_valid_polygon_ring(r):
			return false
		points += r.size()
		if points > MAX_PATH_POINTS:
			return false
	return true


func _is_valid_polygon_ring(ring: PackedVector2Array) -> bool:
	var n: int = ring.size()
	if n < 3:
		return false
	var origin: Vector2 = ring[0]
	var shifted := PackedVector2Array()
	shifted.resize(n)
	for i: int in range(n):
		var pt: Vector2 = ring[i]
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


## 复用 DagCloner 对障碍物形状与缓存字典执行 16 MiB 有界深拷贝。
func _safe_clone_dict(raw: Dictionary) -> Dictionary:
	return _dag_cloner().safe_clone_dict(raw, MAX_CLONE_BYTES)


func _valid_segments(segs: Variant) -> bool:
	if not (segs is PackedVector2Array):
		return false
	var arr: PackedVector2Array = segs as PackedVector2Array
	if arr.size() % 2 != 0 or arr.size() > MAX_SEGMENTS:
		return false
	for pt: Vector2 in arr:
		if not is_finite(pt.x) or not is_finite(pt.y):
			return false
	return true


func _is_finite_rect2(rect: Rect2) -> bool:
	return (
		is_finite(rect.position.x)
		and is_finite(rect.position.y)
		and is_finite(rect.size.x)
		and is_finite(rect.size.y)
	)


func _lookup_entity(entity_id: String) -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or entity_id.is_empty():
		return {}
	if wb.has_method("get_entity"):
		return wb.get_entity(entity_id)
	return {}


func _get_visual_state(entity: Dictionary) -> Dictionary:
	var comps_var: Variant = entity.get("components", [])
	if comps_var is Array and not (comps_var as Array).is_empty():
		var c0: Variant = (comps_var as Array)[0]
		if c0 is Dictionary:
			var st: Variant = (c0 as Dictionary).get("state", null)
			if st is Dictionary:
				return st as Dictionary
	return {}


func _get_entity_drawing_kind(entity: Dictionary) -> String:
	var visual: Dictionary = _get_visual_state(entity)
	var vec: Variant = visual.get("vector_drawing", null)
	if vec is Dictionary:
		var src: Variant = (vec as Dictionary).get("source", null)
		if src is Dictionary:
			return str(_value_utils().as_str((src as Dictionary).get("kind", "")))
	return ""


func _has_component_script(entity: Dictionary, target_script: String) -> bool:
	var comps_var: Variant = entity.get("components", [])
	if comps_var is Array:
		var val_u: Variant = _value_utils()
		for raw_comp: Variant in comps_var as Array:
			if raw_comp is Dictionary and str(val_u.as_str((raw_comp as Dictionary).get("script", ""))) == target_script:
				return true
	return false


func _check_gate(action: String) -> Dictionary:
	if _module_registry != null:
		return _module_registry.check_and_warn(MODULE_ID, action)
	return {"ok": true}


func _warn(message: String) -> void:
	if _log_bus != null:
		_log_bus.warn(MODULE_ID, message)
	else:
		push_warning("[FuSdk/WARNING][%s] %s" % [MODULE_ID, message])
