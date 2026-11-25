extends RefCounted
## Fu vtt 原生可选插件 SDK：follow（角色跟随组件 comp_follow）
##
## 对应官方源码：modules/follow/feature_follow.gd、comp_follow.gd、
## scenes/entities/board_token.gd（comp_follow 与 scene_box 互斥）。

const MODULE_ID: String = "follow"
const COMP_FOLLOW_SCRIPT: String = "res://modules/follow/comp_follow.gd"
const DEFAULT_DISTANCE: float = 16.0
const MAX_CONTROLLER_ID: int = 128

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
		"requires": ["drag_movement"],
	}


func default_state() -> Dictionary:
	return {
		"target_id": "",
		"controller_id": "",
		"engaged": false,
		"follow_distance": DEFAULT_DISTANCE,
	}


func make_follow_state(
	target_id: String = "",
	follow_distance: float = DEFAULT_DISTANCE,
	engaged: bool = false,
	controller_id: String = ""
) -> Dictionary:
	return {
		"target_id": target_id.strip_edges(),
		"controller_id": controller_id,
		"engaged": engaged,
		"follow_distance": float(follow_distance),
	}


func validate_state(
	state_var: Variant,
	entity: Dictionary = {},
	world: Dictionary = {}
) -> Dictionary:
	if not (state_var is Dictionary):
		return {"ok": false, "reason": "invalid_follow_state_type"}
	var state: Dictionary = state_var as Dictionary
	var clean_state: Dictionary = {}

	if state.is_empty():
		clean_state = default_state()
	else:
		var allowed_keys: Array[String] = ["target_id", "controller_id", "engaged", "follow_distance"]
		for raw_k: Variant in state.keys():
			if not (raw_k is String) or not (str(raw_k) in allowed_keys):
				return {"ok": false, "reason": "unknown_follow_key:" + str(raw_k)}

		var valid_u: Variant = _validation_utils()
		var tid_v: Variant = state.get("target_id", "")
		if not (tid_v is String):
			return {"ok": false, "reason": "invalid_target_id_type"}
		var tid: String = str(tid_v)
		if not tid.is_empty() and not bool(valid_u.is_valid_uid(tid)):
			return {"ok": false, "reason": "invalid_target_id"}

		var cid_v: Variant = state.get("controller_id", "")
		if not (cid_v is String):
			return {"ok": false, "reason": "invalid_controller_id_type"}
		var cid: String = str(cid_v)
		if cid.length() > MAX_CONTROLLER_ID or bool(valid_u.has_nul(cid)):
			return {"ok": false, "reason": "invalid_controller_id"}

		var eng_v: Variant = state.get("engaged", false)
		if not (eng_v is bool):
			return {"ok": false, "reason": "invalid_engaged_type"}

		var fd_v: Variant = state.get("follow_distance", DEFAULT_DISTANCE)
		if not (fd_v is float):
			return {"ok": false, "reason": "invalid_follow_distance_type"}
		var fd: float = float(fd_v)
		if not is_finite(fd) or fd < 0.0:
			return {"ok": false, "reason": "invalid_follow_distance"}

		clean_state = {
			"target_id": tid,
			"controller_id": cid,
			"engaged": bool(eng_v),
			"follow_distance": fd,
		}

	if not entity.is_empty():
		var self_id: String = str(entity.get("id", ""))
		var tid_clean: String = str(clean_state["target_id"])
		if not self_id.is_empty() and tid_clean == self_id:
			return {"ok": false, "reason": "follow_self_forbidden"}
		var valid_u: Variant = _validation_utils()
		var comps_var: Variant = entity.get("components", [])
		if comps_var is Array:
			for raw_c: Variant in comps_var as Array:
				if raw_c is Dictionary:
					var scr: String = str((raw_c as Dictionary).get("script", ""))
					if str(valid_u.component_id_from_script(scr)) == "scene_box":
						return {"ok": false, "reason": "component_conflict_with_scene_box:follow"}

	if not world.is_empty() and not str(clean_state["target_id"]).is_empty() and not entity.is_empty():
		var cycle_check: String = _detect_follow_cycle(world, str(entity.get("id", "")), str(clean_state["target_id"]))
		if not cycle_check.is_empty():
			return {"ok": false, "reason": cycle_check}

	return {"ok": true, "data": clean_state}


func attach_follow(
	entity_id: String,
	state: Dictionary = {},
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_follow")
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

	var checked: Dictionary = validate_state(state, entity, wb.get_world())
	if not bool(checked.get("ok", false)):
		var reason: String = str(checked.get("reason", "invalid_follow_state"))
		_warn("无法挂载 follow 组件（%s）：%s" % [entity_id, reason])
		return {"ok": false, "reason": reason}

	var clean_state: Dictionary = checked["data"] as Dictionary
	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_FOLLOW_SCRIPT,
		clean_state,
		effective_parked,
		effective_manual
	))
	if not ok:
		return {"ok": false, "reason": "attach_component_failed"}
	return {
		"ok": true,
		"entity_id": entity_id,
		"state": clean_state,
		"parked": effective_parked,
		"manual": effective_manual,
	}


func set_follow(
	entity_id: String,
	state: Dictionary = {},
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	return attach_follow(entity_id, state, parked, manual)


func set_follow_target(
	entity_id: String,
	target_id: String,
	follow_distance: float = DEFAULT_DISTANCE,
	engaged: bool = true,
	controller_id: String = "",
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	return attach_follow(
		entity_id,
		make_follow_state(target_id, follow_distance, engaged, controller_id),
		parked,
		manual
	)


func _detect_follow_cycle(world: Dictionary, start_id: String, next_id: String) -> String:
	if start_id.is_empty() or next_id.is_empty():
		return ""
	var ent_map: Dictionary = {}
	var es_var: Variant = world.get("entity_state", null)
	if es_var is Dictionary:
		var ents_var: Variant = (es_var as Dictionary).get("entities", null)
		if ents_var is Array:
			for raw_e: Variant in ents_var as Array:
				if raw_e is Dictionary:
					var eid: String = str((raw_e as Dictionary).get("id", ""))
					if not eid.is_empty():
						ent_map[eid] = raw_e
	var visited: Dictionary = {start_id: true}
	var cursor: String = next_id
	var hops: int = 0
	while not cursor.is_empty() and hops < 1024:
		if visited.has(cursor):
			return "follow_cycle"
		visited[cursor] = true
		var ent_var: Variant = ent_map.get(cursor, null)
		if not (ent_var is Dictionary):
			break
		var next_target: String = ""
		var valid_u: Variant = _validation_utils()
		var comps_var: Variant = (ent_var as Dictionary).get("components", [])
		if comps_var is Array:
			for raw_c: Variant in comps_var as Array:
				if raw_c is Dictionary and str(valid_u.component_id_from_script(str((raw_c as Dictionary).get("script", "")))) == "follow":
					var st_var: Variant = (raw_c as Dictionary).get("state", {})
					if st_var is Dictionary:
						next_target = str((st_var as Dictionary).get("target_id", ""))
					break
		cursor = next_target
		hops += 1
	return ""


func _lookup_entity(entity_id: String) -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or entity_id.is_empty():
		return {}
	if wb.has_method("get_entity"):
		return wb.get_entity(entity_id)
	return {}


func _check_gate(action: String) -> Dictionary:
	if _module_registry != null:
		return _module_registry.check_and_warn(MODULE_ID, action)
	return {"ok": true, "enabled": false, "policy": "preserve", "skipped": false}


func _warn(message: String) -> void:
	if _log_bus != null:
		_log_bus.warn(MODULE_ID, message)
	else:
		push_warning("[FuSdk/WARNING][%s] %s" % [MODULE_ID, message])
