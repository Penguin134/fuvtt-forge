extends RefCounted
## Fu vtt 原生可选插件 SDK：portal（传送门与配对端点 comp_portal）
##
## 对应官方源码：modules/portal/feature_portal.gd、comp_portal.gd、
## scenes/board/networking/steam_lobby.gd、scenes/entities/board_token.gd。

const MODULE_ID: String = "portal"
const COMP_PORTAL_SCRIPT: String = "res://modules/portal/comp_portal.gd"
const COMP_AREA_SCRIPT: String = "res://modules/areas/comp_area.gd"
const COMP_SCENE_BOX_SCRIPT: String = "res://modules/scene_box/comp_scene_box.gd"

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
		"requires": ["areas"],
	}


func is_valid_pair_key(pair_key: Variant) -> bool:
	if not (pair_key is String):
		return false
	var key: String = str(pair_key)
	if key.is_empty():
		return true
	return bool(_validation_utils().is_valid_uid(key))


func normalize_pair_key(pair_key: String) -> String:
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("make_portal_state"):
		return str(adapter.make_portal_state(pair_key).get("pair_key", ""))
	var valid_u: Variant = _validation_utils()
	var clean: String = str(valid_u.strip_control_and_edges(pair_key))
	if clean.is_empty():
		return ""
	if bool(valid_u.is_valid_uid(clean)):
		return clean
	return ("fu_sdk:portal:" + clean).sha256_text().left(32)


func make_portal_state(pair_key: String = "") -> Dictionary:
	return {"pair_key": normalize_pair_key(pair_key)}


func validate_portal_state(state: Dictionary, entity: Dictionary = {}) -> Dictionary:
	var errors: Array[String] = []
	for raw_k: Variant in state.keys():
		if not (raw_k is String) or str(raw_k) != "pair_key":
			errors.append("unknown_portal_key:" + str(raw_k))
	if state.has("pair_key"):
		if not is_valid_pair_key(state["pair_key"]):
			errors.append("invalid_pair_key")

	if not entity.is_empty():
		var valid_u: Variant = _validation_utils()
		var comps_var: Variant = entity.get("components", [])
		if comps_var is Array:
			for raw_c: Variant in comps_var as Array:
				if raw_c is Dictionary:
					var scr: String = str((raw_c as Dictionary).get("script", ""))
					if str(valid_u.component_id_from_script(scr)) == "scene_box":
						errors.append("component_conflict_with_scene_box:portal")
						break

	return {"ok": errors.is_empty(), "errors": errors}


func attach_portal(
	entity_id: String,
	pair_key: String = "",
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_portal")
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

	var val_res: Dictionary = validate_portal_state(make_portal_state(pair_key), entity)
	if not bool(val_res.get("ok", false)):
		var err_list: Array = val_res.get("errors", [])
		var reason: String = str(err_list[0]) if not err_list.is_empty() else "invalid_portal_host"
		_warn("无法挂载传送门组件（%s）：%s" % [entity_id, reason])
		return {"ok": false, "reason": reason}

	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var state: Dictionary = make_portal_state(pair_key)
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_PORTAL_SCRIPT,
		state,
		effective_parked,
		effective_manual
	))
	if not ok:
		return {"ok": false, "reason": "attach_component_failed"}

	if not _is_operational_area_endpoint(entity) and _log_bus != null:
		_log_bus.debug(MODULE_ID, "实体 '%s' 尚无 area 区域图形或 comp_area 组件；运行时传送门激活需具备有效区域端点。" % entity_id)

	return {
		"ok": true,
		"entity_id": entity_id,
		"pair_key": str(state["pair_key"]),
		"parked": effective_parked,
		"manual": effective_manual,
	}


func link_pair(
	entity_a: String,
	entity_b: String,
	pair_key: String = "",
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("link_pair")
	if not bool(gate.get("ok", true)):
		return gate
	if manual and not parked:
		return {"ok": false, "reason": "manual_requires_parked"}
	if entity_a.is_empty() or entity_b.is_empty() or entity_a == entity_b:
		return {"ok": false, "reason": "invalid_portal_pair_entities"}
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var ent_a: Dictionary = _lookup_entity(entity_a)
	var ent_b: Dictionary = _lookup_entity(entity_b)
	if ent_a.is_empty() or ent_b.is_empty():
		return {"ok": false, "reason": "entity_not_found"}

	var raw_key: String = pair_key if not pair_key.strip_edges().is_empty() else ("fu_sdk:portal_pair:%s:%s" % [entity_a, entity_b])
	var state: Dictionary = make_portal_state(raw_key)
	var val_a: Dictionary = validate_portal_state(state, ent_a)
	if not bool(val_a.get("ok", false)):
		return {"ok": false, "reason": str((val_a.get("errors", ["invalid_endpoint_a"]) as Array)[0])}
	var val_b: Dictionary = validate_portal_state(state, ent_b)
	if not bool(val_b.get("ok", false)):
		return {"ok": false, "reason": str((val_b.get("errors", ["invalid_endpoint_b"]) as Array)[0])}

	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false

	var ok_a: bool = bool(wb.attach_component(
		entity_a,
		COMP_PORTAL_SCRIPT,
		state,
		effective_parked,
		effective_manual
	))
	var ok_b: bool = bool(wb.attach_component(
		entity_b,
		COMP_PORTAL_SCRIPT,
		state,
		effective_parked,
		effective_manual
	))
	if not ok_a or not ok_b:
		return {"ok": false, "reason": "attach_component_failed"}

	return {
		"ok": true,
		"entity_a": entity_a,
		"entity_b": entity_b,
		"pair_key": str(state["pair_key"]),
		"parked": effective_parked,
		"manual": effective_manual,
	}


func _is_operational_area_endpoint(entity: Dictionary) -> bool:
	var comps_var: Variant = entity.get("components", [])
	if not (comps_var is Array) or (comps_var as Array).is_empty():
		return false
	var has_active_area: bool = false
	var has_area_visual: bool = false
	var comps: Array = comps_var as Array
	if comps[0] is Dictionary:
		var v_state: Variant = (comps[0] as Dictionary).get("state", null)
		if v_state is Dictionary:
			var vd: Variant = (v_state as Dictionary).get("vector_drawing", null)
			if vd is Dictionary:
				var src: Variant = (vd as Dictionary).get("source", null)
				if src is Dictionary and str((src as Dictionary).get("kind", "")) == "area":
					has_area_visual = true
	var valid_u: Variant = _validation_utils()
	for raw_c: Variant in comps:
		if raw_c is Dictionary:
			var c: Dictionary = raw_c as Dictionary
			if str(valid_u.component_id_from_script(str(c.get("script", "")))) == "area":
				var ast: Variant = c.get("state", null)
				if ast is Dictionary and not bool((ast as Dictionary).get("removed", false)):
					has_active_area = true
	return has_area_visual and has_active_area


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
