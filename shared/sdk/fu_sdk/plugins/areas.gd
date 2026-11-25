extends RefCounted
## Fu vtt 原生可选插件 SDK：areas（区域图层、fus.area.v1 区域图形与 comp_area 组件）
##
## 对应官方源码：modules/areas/areas.gd、comp_area.gd、
## scenes/systems/layers/layer_stack_state.gd、scenes/entities/board_token.gd。

const MODULE_ID: String = "areas"
const COMP_AREA_SCRIPT: String = "res://modules/areas/comp_area.gd"
const AREA_LAYER_KIND: String = "area"
const AREA_SCHEMA: String = "fus.area.v1"
const MAX_RADIUS_IN_CELLS: float = 256.0
const DEFAULT_FILL_COLOR: Color = Color("#55cda739")
const DEFAULT_LINE_COLOR: Color = Color("#58cba1d8")
const CONFLICT_COMPONENT_IDS: Array[String] = ["image_flip", "scene_box"]

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
	return false


func get_availability() -> Dictionary:
	if _module_registry != null:
		return _module_registry.get_module_entry(MODULE_ID)
	return {
		"id": MODULE_ID,
		"core": false,
		"status": "disabled",
		"enabled": false,
	}


func make_area_state(radius_in_cells: float = 1.0, removed: bool = false) -> Dictionary:
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("make_area_state"):
		return adapter.make_area_state(radius_in_cells, removed)
	var r: float = float(radius_in_cells) if is_finite(radius_in_cells) else 1.0
	if r <= 0.0:
		r = 1.0
	r = minf(r, MAX_RADIUS_IN_CELLS)
	return {
		"removed": removed,
		"radius_in_cells": r,
	}


func validate_area_state(state: Dictionary, entity: Dictionary = {}) -> Dictionary:
	var errors: Array[String] = []
	for raw_k: Variant in state.keys():
		if not (raw_k is String) or not (str(raw_k) in ["removed", "radius_in_cells"]):
			errors.append("unknown_area_key:" + str(raw_k))
	if state.has("removed") and not (state["removed"] is bool):
		errors.append("invalid_removed_type")
	if state.has("radius_in_cells"):
		var rv: Variant = state["radius_in_cells"]
		if not (rv is float) or not is_finite(float(rv)) or float(rv) <= 0.0 or float(rv) > MAX_RADIUS_IN_CELLS:
			errors.append("invalid_radius_in_cells")

	if not entity.is_empty():
		var valid_u: Variant = _validation_utils()
		var comps_var: Variant = entity.get("components", [])
		if comps_var is Array:
			for raw_c: Variant in comps_var as Array:
				if raw_c is Dictionary:
					var scr: String = str((raw_c as Dictionary).get("script", ""))
					var cid: String = str(valid_u.component_id_from_script(scr))
					if cid in CONFLICT_COMPONENT_IDS:
						errors.append("component_conflict_with_area:" + cid)

	return {"ok": errors.is_empty(), "errors": errors}


func attach_area(
	entity_id: String,
	radius_in_cells: float = 1.0,
	removed: bool = false,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_area")
	if not bool(gate.get("ok", true)):
		return gate
	if manual and not parked:
		return {"ok": false, "reason": "manual_requires_parked"}
	if not is_finite(radius_in_cells) or radius_in_cells <= 0.0 or radius_in_cells > MAX_RADIUS_IN_CELLS:
		return {"ok": false, "reason": "invalid_radius_in_cells"}
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return {"ok": false, "reason": "entity_not_found"}

	var state: Dictionary = make_area_state(float(radius_in_cells), removed)
	var val_res: Dictionary = validate_area_state(state, entity)
	if not bool(val_res.get("ok", false)):
		var err_list: Array = val_res.get("errors", [])
		var reason: String = str(err_list[0]) if not err_list.is_empty() else "invalid_area_host"
		_warn("无法挂载 comp_area 组件（%s）：%s" % [entity_id, reason])
		return {"ok": false, "reason": reason}

	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_AREA_SCRIPT,
		state,
		effective_parked,
		effective_manual
	))
	if not ok:
		return {"ok": false, "reason": "attach_component_failed"}
	return {
		"ok": true,
		"entity_id": entity_id,
		"radius_in_cells": float(state["radius_in_cells"]),
		"removed": removed,
		"parked": effective_parked,
		"manual": effective_manual,
	}


func add_area_layer(
	name: String = "区域",
	floor_uid: String = "",
	access: String = "host",
	viewers: Array = [],
	locked: bool = false,
	visible: bool = true,
	persistent: bool = true
) -> String:
	var gate: Dictionary = _check_gate("add_area_layer")
	if not bool(gate.get("ok", true)):
		return ""
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	var norm_access: String = access.strip_edges().to_lower()
	if not (norm_access in ["all", "host", "players"]):
		norm_access = "host"
	return str(wb.add_layer(
		name,
		AREA_LAYER_KIND,
		norm_access,
		floor_uid,
		viewers,
		locked,
		visible,
		persistent
	))


func add_area_entity(
	source_id: String,
	name: String,
	center_src: Vector2,
	size_src: Vector2,
	paths_local: Array,
	radius_in_cells: float = 1.0,
	removed: bool = false,
	floor_uid: String = "",
	layer_uid_override: String = "",
	parked: bool = false,
	manual: bool = false,
	fill_color: Color = DEFAULT_FILL_COLOR,
	line_color: Color = DEFAULT_LINE_COLOR
) -> Dictionary:
	var gate: Dictionary = _check_gate("add_area_entity")
	if not bool(gate.get("ok", true)):
		return gate
	if manual and not parked:
		return {"ok": false, "reason": "manual_requires_parked"}
	if not is_finite(radius_in_cells) or radius_in_cells <= 0.0 or radius_in_cells > MAX_RADIUS_IN_CELLS:
		return {"ok": false, "reason": "invalid_radius_in_cells"}
	if not _has_valid_area_geometry(paths_local):
		return {"ok": false, "reason": "area_geometry_invalid"}
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}
	var adapter: RefCounted = _get_adapter()
	if adapter == null:
		return {"ok": false, "reason": "host_adapter_unavailable"}

	var target_floor: String = floor_uid if not floor_uid.is_empty() else str(wb.get_active_floor_uid())
	var target_layer: String = layer_uid_override
	if not target_layer.is_empty():
		if not _is_area_layer(target_layer):
			return {"ok": false, "reason": "target_layer_must_be_area_kind"}
	else:
		target_layer = str(wb.get_layer_uid(AREA_LAYER_KIND, target_floor))
		if target_layer.is_empty():
			target_layer = str(wb.add_layer("区域", AREA_LAYER_KIND, "host", target_floor))
	if target_layer.is_empty():
		return {"ok": false, "reason": "missing_area_layer"}

	var resolved_floor: String = str(adapter.get_floor_for_layer(wb.get_world(), target_layer))
	if resolved_floor.is_empty():
		resolved_floor = target_floor

	var visual: Dictionary = adapter.make_area_region_visual(size_src, paths_local, fill_color, line_color)
	var clean_name: String = name if not name.strip_edges().is_empty() else "区域"
	var entity: Dictionary = adapter.append_entity(
		wb.get_world(),
		resolved_floor,
		target_layer,
		source_id,
		clean_name,
		center_src,
		size_src,
		0.0,
		Vector2.ONE,
		float(wb.get_source_to_world_scale()),
		visual,
		false,
		false
	)
	if entity.is_empty():
		return {"ok": false, "reason": "append_entity_failed"}

	var entity_id: String = str(entity.get("id", ""))
	var area_state: Dictionary = make_area_state(float(radius_in_cells), removed)
	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var comp_res: Dictionary = adapter.append_entity_component(
		entity,
		COMP_AREA_SCRIPT,
		area_state,
		effective_parked,
		effective_manual
	)
	if not bool(comp_res.get("ok", false)):
		var world_ref: Dictionary = wb.get_world()
		var es_var: Variant = world_ref.get("entity_state", null)
		if es_var is Dictionary and (es_var as Dictionary).get("entities", null) is Array:
			var ents: Array = (es_var as Dictionary)["entities"] as Array
			if not ents.is_empty() and ents[ents.size() - 1] is Dictionary and str((ents[ents.size() - 1] as Dictionary).get("id", "")) == entity_id:
				ents.pop_back()
		var mem_var: Variant = world_ref.get("members", null)
		if mem_var is Array:
			var mems: Array = mem_var as Array
			if not mems.is_empty() and mems[mems.size() - 1] is Dictionary and str((mems[mems.size() - 1] as Dictionary).get("entity_id", "")) == entity_id:
				mems.pop_back()
		return comp_res

	if wb.has_method("register_external_entity"):
		wb.register_external_entity(entity)

	return {
		"ok": true,
		"entity_id": entity_id,
		"layer_uid": target_layer,
		"floor_uid": resolved_floor,
		"parked": effective_parked,
		"manual": effective_manual,
	}


func _has_valid_area_geometry(paths_local: Array) -> bool:
	if paths_local.is_empty():
		return false
	for raw_ring: Variant in paths_local:
		var pts := PackedVector2Array()
		var ring_valid: bool = true
		if raw_ring is PackedVector2Array:
			for pt: Vector2 in raw_ring as PackedVector2Array:
				if not pt.is_finite():
					ring_valid = false
					break
				pts.append(pt)
		elif raw_ring is Array:
			for raw_pt: Variant in raw_ring as Array:
				var pt := Vector2.ZERO
				var ok: bool = false
				if raw_pt is Vector2:
					pt = raw_pt as Vector2
					ok = true
				elif raw_pt is Vector2i:
					var vi := raw_pt as Vector2i
					pt = Vector2(float(vi.x), float(vi.y))
					ok = true
				elif raw_pt is Array and (raw_pt as Array).size() >= 2:
					var pair := raw_pt as Array
					if (pair[0] is int or pair[0] is float) and (pair[1] is int or pair[1] is float):
						pt = Vector2(float(pair[0]), float(pair[1]))
						ok = true
				elif raw_pt is Dictionary:
					var pd := raw_pt as Dictionary
					var dx: Variant = pd.get("x", 0.0)
					var dy: Variant = pd.get("y", 0.0)
					if (dx is int or dx is float) and (dy is int or dy is float):
						pt = Vector2(float(dx), float(dy))
						ok = true
				if not ok or not pt.is_finite():
					ring_valid = false
					break
				pts.append(pt)
		else:
			ring_valid = false
		if not ring_valid or pts.size() < 3 or pts.size() > 4096:
			continue
		var bounds := Rect2(pts[0], Vector2.ZERO)
		for pt: Vector2 in pts:
			bounds = bounds.expand(pt)
		if not bounds.has_area():
			continue
		var area2: float = 0.0
		for i: int in range(pts.size()):
			var p0: Vector2 = pts[i]
			var p1: Vector2 = pts[(i + 1) % pts.size()]
			area2 += p0.x * p1.y - p1.x * p0.y
		if absf(area2) > 0.0 and not Geometry2D.triangulate_polygon(pts).is_empty():
			return true
	return false


func _is_area_layer(layer_uid: String) -> bool:
	var wb: RefCounted = _wb()
	if wb == null or layer_uid.is_empty():
		return false
	var world: Dictionary = wb.get_world()
	var cat_var: Variant = world.get("catalog", null)
	if not (cat_var is Dictionary):
		return false
	var layers_var: Variant = (cat_var as Dictionary).get("layers", null)
	if not (layers_var is Dictionary):
		return false
	var floors_var: Variant = (layers_var as Dictionary).get("floors", null)
	if not (floors_var is Array):
		return false
	for raw_f: Variant in floors_var as Array:
		if raw_f is Dictionary:
			var rows_var: Variant = (raw_f as Dictionary).get("layers", [])
			if rows_var is Array:
				for raw_l: Variant in rows_var as Array:
					if raw_l is Dictionary and str((raw_l as Dictionary).get("layer_uid", "")) == layer_uid:
						return str((raw_l as Dictionary).get("kind", "")) == AREA_LAYER_KIND
	return false


func _lookup_entity(entity_id: String) -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or entity_id.is_empty():
		return {}
	if wb.has_method("get_entity"):
		return wb.get_entity(entity_id)
	return {}


func _get_adapter() -> RefCounted:
	var wb: RefCounted = _wb()
	if wb != null and wb.has_method("get_adapter"):
		return wb.get_adapter()
	return null


func _check_gate(action: String) -> Dictionary:
	if _module_registry != null:
		return _module_registry.check_and_warn(MODULE_ID, action)
	return {"ok": true, "enabled": false, "policy": "preserve", "skipped": false}


func _warn(message: String) -> void:
	if _log_bus != null:
		_log_bus.warn(MODULE_ID, message)
	else:
		push_warning("[FuSdk/WARNING][%s] %s" % [MODULE_ID, message])
