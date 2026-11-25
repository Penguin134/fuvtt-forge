extends RefCounted
## Fu vtt 原生核心插件 SDK：feature_edit_mode（编辑模式 / 单位标记与权限）
##
## 对应官方源码：scenes/extension/feature_edit_mode.gd、
## scenes/entities/components/comp_unit.gd、comp_permission.gd、board_token.gd。

const MODULE_ID: String = "feature_edit_mode"
const COMP_UNIT_SCRIPT: String = "res://scenes/entities/components/comp_unit.gd"
const COMP_VISUAL_SCRIPT: String = "res://scenes/entities/components/comp_visual.gd"
const COMP_PERMISSION_SCRIPT: String = "res://scenes/entities/components/comp_permission.gd"
const COMP_SCENE_BOX_SCRIPT: String = "res://modules/scene_box/comp_scene_box.gd"
const COMP_SCENE_BOX_CANDIDATE_SCRIPT: String = "res://scenes/candidates/scene_box/comp_scene_box.gd"

const MIN_FOOTPRINT_RADIUS: float = 0.5
const MAX_FOOTPRINT_RADIUS: float = 4096.0
const DEFAULT_FOOTPRINT_RADIUS: float = 32.0
const MIN_ENTITY_SIZE: Vector2 = Vector2(4.0, 4.0)

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


func make_unit_state() -> Dictionary:
	return {"schema_version": 1}


func make_permission_state(
	owners_csv: String = "",
	owner_player_ids: Array = [],
	all_players_can_operate: bool = false,
	gm_can_operate: bool = true
) -> Dictionary:
	var wb: RefCounted = _wb()
	if wb != null and wb.has_method("get_adapter"):
		var adapter: RefCounted = wb.get_adapter()
		if adapter != null and adapter.has_method("make_permission_state"):
			return adapter.make_permission_state(
				owners_csv,
				owner_player_ids,
				all_players_can_operate,
				gm_can_operate
			)
	var valid_u: Variant = _validation_utils()
	var ids := PackedStringArray()
	var seen: Dictionary = {}
	for raw_id: Variant in owner_player_ids:
		if not (raw_id is String or raw_id is StringName):
			continue
		var clean_id: String = str(valid_u.strip_bom_and_edges(valid_u.strip_nul(str(raw_id))))
		if not clean_id.is_empty() and not seen.has(clean_id):
			seen[clean_id] = true
			ids.append(clean_id)
	return {
		"owners_csv": str(valid_u.strip_bom_and_edges(valid_u.strip_nul(owners_csv))),
		"gm_can_operate": gm_can_operate,
		"all_players_can_operate": all_players_can_operate,
		"owner_peers": PackedInt32Array(),
		"owner_player_ids": ids,
	}


func attach_unit_marker(
	entity_id: String,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_unit_marker")
	if not bool(gate.get("ok", true)):
		return gate
	if manual and not parked:
		return {"ok": false, "reason": "manual_requires_parked"}
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return {"ok": false, "reason": "entity_not_found"}
	if str(entity.get("entity_type", "")) == "map":
		_warn("无法为地图实体挂载 comp_unit（comp_unit.supports_host 禁止 entity_type == 'map'）：" + entity_id)
		return {"ok": false, "reason": "unit_disallowed_on_map"}
	if _has_component_script(entity, COMP_SCENE_BOX_SCRIPT) or _has_component_script(entity, COMP_SCENE_BOX_CANDIDATE_SCRIPT):
		_warn("实体已有 scene_box 组件，禁止同时挂载 unit：" + entity_id)
		return {"ok": false, "reason": "component_conflict_with_scene_box:unit"}

	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_UNIT_SCRIPT,
		make_unit_state(),
		parked,
		manual
	))
	if not ok:
		return {"ok": false, "reason": "attach_component_failed"}
	if not parked:
		entity["selectable_in_select_mode"] = true
	return {"ok": true, "entity_id": entity_id, "parked": parked, "manual": manual}


func mark_as_unit(
	entity_id: String,
	parked: bool = false,
	manual: bool = false
) -> bool:
	return bool(attach_unit_marker(entity_id, parked, manual).get("ok", false))


func is_unit(entity_id: String) -> bool:
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return false
	var sel_var: Variant = entity.get("selectable_in_select_mode", null)
	if sel_var is bool and sel_var == true:
		return true
	var val_u: Variant = _value_utils()
	var comps_var: Variant = entity.get("components", [])
	if comps_var is Array:
		for raw_comp: Variant in comps_var as Array:
			if raw_comp is Dictionary:
				var comp: Dictionary = raw_comp as Dictionary
				var scr_var: Variant = comp.get("script", "")
				if (scr_var is String or scr_var is StringName) and str(scr_var) == COMP_UNIT_SCRIPT and not bool(val_u.coerce_bool(comp.get("parked", false), false, true)):
					return true
	return false


func set_entity_flags(
	entity_id: String,
	hidden: bool = false,
	locked: bool = false
) -> bool:
	var gate: Dictionary = _check_gate("set_entity_flags")
	if not bool(gate.get("ok", true)):
		return false
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return false
	var flags_var: Variant = entity.get("flags", null)
	if not (flags_var is Dictionary):
		entity["flags"] = {}
	var flags: Dictionary = entity["flags"]
	flags["entity_hidden"] = hidden
	flags["entity_locked"] = locked
	return true


func set_entity_permissions(entity_id: String, permission_state: Dictionary) -> bool:
	var gate: Dictionary = _check_gate("set_entity_permissions")
	if not bool(gate.get("ok", true)):
		return false
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return false
	var comps_var: Variant = entity.get("components", null)
	if not (comps_var is Array) or (comps_var as Array).size() < 2:
		return false
	var comps: Array = comps_var
	if not (comps[1] is Dictionary):
		return false
	var perm_rec: Dictionary = comps[1] as Dictionary
	var perm_scr: Variant = perm_rec.get("script", "")
	if not (perm_scr is String or perm_scr is StringName) or str(perm_scr) != COMP_PERMISSION_SCRIPT:
		return false
	if bool(_value_utils().coerce_bool(perm_rec.get("parked", false), false, true)):
		return false

	var normalized: Dictionary = _normalize_permission_state(permission_state)
	perm_rec["state"] = normalized
	return true


func set_footprint_radius(entity_id: String, radius: float) -> bool:
	var gate: Dictionary = _check_gate("set_footprint_radius")
	if not bool(gate.get("ok", true)):
		return false
	if not is_finite(radius) or radius < MIN_FOOTPRINT_RADIUS or radius > MAX_FOOTPRINT_RADIUS:
		return false
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return false
	entity["footprint_radius"] = radius
	return true


func set_selectable_in_select_mode(entity_id: String, selectable: bool) -> bool:
	var gate: Dictionary = _check_gate("set_selectable_in_select_mode")
	if not bool(gate.get("ok", true)):
		return false
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return false
	if selectable and str(entity.get("entity_type", "")) == "map":
		return false
	entity["selectable_in_select_mode"] = selectable
	return true


func validate_unit_entity(entity: Dictionary) -> Dictionary:
	var errors: Array[String] = []
	if entity.is_empty():
		return {"ok": false, "errors": ["entity_empty"]}

	var etype: String = str(entity.get("entity_type", ""))
	if etype == "map":
		errors.append("unit_disallowed_on_map")

	var size_var: Variant = entity.get("entity_size", null)
	if not (size_var is Vector2):
		errors.append("invalid_entity_size")
	else:
		var sz: Vector2 = size_var as Vector2
		if not is_finite(sz.x) or not is_finite(sz.y) or sz.x < MIN_ENTITY_SIZE.x or sz.y < MIN_ENTITY_SIZE.y:
			errors.append("entity_size_below_minimum")

	var fp_var: Variant = entity.get("footprint_radius", null)
	if not (fp_var is float):
		errors.append("invalid_footprint_radius_type")
	else:
		var fp: float = float(fp_var)
		if not is_finite(fp) or fp < MIN_FOOTPRINT_RADIUS or fp > MAX_FOOTPRINT_RADIUS:
			errors.append("footprint_radius_out_of_range")

	var comps_var: Variant = entity.get("components", null)
	var has_live_unit: bool = false
	if not (comps_var is Array) or (comps_var as Array).size() < 2:
		errors.append("invalid_core_components_prefix")
	else:
		var val_u: Variant = _value_utils()
		var comps: Array = comps_var
		var c0: Dictionary = comps[0] if comps[0] is Dictionary else {}
		var c1: Dictionary = comps[1] if comps[1] is Dictionary else {}
		var c0_scr: Variant = c0.get("script", "")
		var c1_scr: Variant = c1.get("script", "")
		if not (c0_scr is String or c0_scr is StringName) or str(c0_scr) != COMP_VISUAL_SCRIPT or bool(val_u.coerce_bool(c0.get("parked", false), false, true)):
			errors.append("invalid_visual_prefix")
		if not (c1_scr is String or c1_scr is StringName) or str(c1_scr) != COMP_PERMISSION_SCRIPT or bool(val_u.coerce_bool(c1.get("parked", false), false, true)):
			errors.append("invalid_permission_prefix")
		else:
			var pstate_var: Variant = c1.get("state", null)
			if not (pstate_var is Dictionary):
				errors.append("invalid_permission_state")
			else:
				var pstate: Dictionary = pstate_var as Dictionary
				for pkey: String in ["owners_csv", "gm_can_operate", "all_players_can_operate", "owner_peers", "owner_player_ids"]:
					if not pstate.has(pkey):
						errors.append("missing_permission_key:" + pkey)
		var has_scene_box: bool = false
		var has_unit: bool = false
		for raw_c: Variant in comps:
			if not (raw_c is Dictionary):
				continue
			var c: Dictionary = raw_c as Dictionary
			var scr_v: Variant = c.get("script", "")
			var scr: String = str(scr_v) if (scr_v is String or scr_v is StringName) else ""
			if scr == COMP_SCENE_BOX_SCRIPT or scr == COMP_SCENE_BOX_CANDIDATE_SCRIPT:
				has_scene_box = true
			if scr == COMP_UNIT_SCRIPT:
				has_unit = true
				if not bool(val_u.coerce_bool(c.get("parked", false), false, true)):
					has_live_unit = true
				var st_var: Variant = c.get("state", {})
				var sv: Variant = (st_var as Dictionary).get("schema_version", null) if st_var is Dictionary else null
				if not (st_var is Dictionary) or not (sv is int) or int(sv) != 1:
					errors.append("invalid_unit_schema_version")
			if bool(val_u.coerce_bool(c.get("manual", false), false, true)) and not bool(val_u.coerce_bool(c.get("parked", false), false, true)):
				errors.append("manual_requires_parked")
		if has_unit and has_scene_box:
			errors.append("component_conflict_with_scene_box:unit")

	var sel_var: Variant = entity.get("selectable_in_select_mode", null)
	if not (sel_var is bool):
		errors.append("invalid_selectable_in_select_mode")
	if not (sel_var is bool and sel_var == true) and not has_live_unit:
		errors.append("entity_not_unit_eligible")

	return {
		"ok": errors.is_empty(),
		"errors": errors,
	}


func _normalize_permission_state(raw: Dictionary) -> Dictionary:
	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	var raw_owners: Variant = raw.get("owners_csv", "")
	var owners_csv: String = str(valid_u.strip_bom_and_edges(valid_u.strip_nul(str(raw_owners)))) if (raw_owners is String or raw_owners is StringName) else ""
	var gm_can_operate: bool = bool(val_u.coerce_bool(raw.get("gm_can_operate", true), true, true))
	var all_players_can_operate: bool = bool(val_u.coerce_bool(raw.get("all_players_can_operate", false), false, true))

	var owner_peers := PackedInt32Array()
	var raw_peers: Variant = raw.get("owner_peers", PackedInt32Array())
	if raw_peers is PackedInt32Array or raw_peers is Array:
		for p: Variant in raw_peers:
			if p is int:
				owner_peers.append(int(p))
			elif p is float and is_finite(float(p)):
				owner_peers.append(int(p))

	var owner_player_ids := PackedStringArray()
	var seen_ids: Dictionary = {}
	var raw_ids: Variant = raw.get("owner_player_ids", PackedStringArray())
	if raw_ids is PackedStringArray or raw_ids is Array:
		for raw_id: Variant in raw_ids:
			if not (raw_id is String or raw_id is StringName):
				continue
			var cid: String = str(valid_u.strip_bom_and_edges(valid_u.strip_nul(str(raw_id))))
			if not cid.is_empty() and not seen_ids.has(cid):
				seen_ids[cid] = true
				owner_player_ids.append(cid)

	return {
		"owners_csv": owners_csv,
		"gm_can_operate": gm_can_operate,
		"all_players_can_operate": all_players_can_operate,
		"owner_peers": owner_peers,
		"owner_player_ids": owner_player_ids,
	}


func _lookup_entity(entity_id: String) -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or entity_id.is_empty():
		return {}
	if wb.has_method("get_entity"):
		return wb.get_entity(entity_id)
	return {}


func _has_component_script(entity: Dictionary, target_script: String) -> bool:
	var comps_var: Variant = entity.get("components", [])
	if comps_var is Array:
		for raw_comp: Variant in comps_var as Array:
			if raw_comp is Dictionary and str((raw_comp as Dictionary).get("script", "")) == target_script:
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
