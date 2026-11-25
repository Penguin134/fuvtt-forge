extends RefCounted
## Fu vtt 原生可选插件 SDK：character_roster（左侧角色栏配置与成员组件 comp_character_roster_member）
##
## 对应官方源码：modules/character_roster/feature.gd、comp_character_roster_member.gd、
## scenes/entities/board_token.gd（仅限 unit 且非 map，且与 scene_box 互斥）。

const MODULE_ID: String = "character_roster"
const MODULE_VERSION: int = 1
const COMP_SCHEMA_VERSION: int = 1
const COMP_ROSTER_MEMBER_SCRIPT: String = "res://modules/character_roster/comp_character_roster_member.gd"
const MAX_KNOWN_BY_STRING: int = 128

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


func _bounded_cloner() -> Variant:
	return _load_util_script("bounded_cloner.gd")


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


func default_state() -> Dictionary:
	return {"auto_join": false}


func default_member_state() -> Dictionary:
	return {
		"schema_version": COMP_SCHEMA_VERSION,
		"known_by": {},
	}


func make_member_state(known_by: Dictionary = {}) -> Dictionary:
	var kb_budget: Array = [16384, false]
	var clean_kb: Dictionary = _safe_clone_dict(known_by, 0, [], kb_budget)
	if bool(kb_budget[1]):
		return {}
	return {
		"schema_version": COMP_SCHEMA_VERSION,
		"known_by": clean_kb,
	}


func validate_state(state_var: Variant) -> Dictionary:
	if not (state_var is Dictionary):
		return {"ok": false, "reason": "invalid_character_roster_state_type"}
	var state: Dictionary = state_var as Dictionary
	if state.is_empty():
		return {"ok": true, "data": default_state()}
	if state.size() != 1 or not state.has("auto_join"):
		return {"ok": false, "reason": "invalid_character_roster_keys"}
	var aj: Variant = state["auto_join"]
	if not (aj is bool):
		return {"ok": false, "reason": "invalid_auto_join_type"}
	return {"ok": true, "data": {"auto_join": bool(aj)}}


func validate_member_state(state_var: Variant, entity: Dictionary = {}, parked: bool = false) -> Dictionary:
	if not (state_var is Dictionary):
		return {"ok": false, "reason": "invalid_roster_member_state_type"}
	var state: Dictionary = state_var as Dictionary
	var clean_state: Dictionary = {}

	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	if state.is_empty():
		clean_state = default_member_state()
	else:
		for raw_k: Variant in state.keys():
			if not (raw_k is String) or not (str(raw_k) in ["schema_version", "known_by"]):
				return {"ok": false, "reason": "unknown_roster_member_key:" + str(raw_k)}
		var sv_parsed: Dictionary = val_u.parse_int_val(state.get("schema_version", COMP_SCHEMA_VERSION))
		if not bool(sv_parsed["ok"]) or int(sv_parsed["value"]) != COMP_SCHEMA_VERSION:
			return {"ok": false, "reason": "invalid_schema_version"}
		var kb_v: Variant = state.get("known_by", {})
		if not (kb_v is Dictionary):
			return {"ok": false, "reason": "invalid_known_by_type"}
		var kb: Dictionary = kb_v as Dictionary
		var clean_kb: Dictionary = {}
		for raw_pk: Variant in kb.keys():
			if not (raw_pk is String):
				return {"ok": false, "reason": "invalid_known_by_key_type"}
			var pk: String = str(raw_pk)
			if pk.strip_edges().is_empty() or pk.length() > MAX_KNOWN_BY_STRING or bool(valid_u.has_control_chars(pk, false)):
				return {"ok": false, "reason": "invalid_known_by_key"}
			var pv_v: Variant = kb[raw_pk]
			if not (pv_v is String):
				return {"ok": false, "reason": "invalid_known_by_value_type"}
			var pv: String = str(pv_v)
			if pv.strip_edges().is_empty() or pv.length() > MAX_KNOWN_BY_STRING or bool(valid_u.has_control_chars(pv, false)):
				return {"ok": false, "reason": "invalid_known_by_value"}
			clean_kb[pk] = pv
		clean_state = {
			"schema_version": COMP_SCHEMA_VERSION,
			"known_by": clean_kb,
		}

	if not entity.is_empty():
		if not parked and not bool(valid_u.is_unit_host(entity)):
			return {"ok": false, "reason": "character_roster_member_requires_unit_host"}
		var comps_var: Variant = entity.get("components", [])
		if comps_var is Array:
			for raw_c: Variant in comps_var as Array:
				if raw_c is Dictionary:
					var scr: String = str((raw_c as Dictionary).get("script", ""))
					if str(valid_u.component_id_from_script(scr)) == "scene_box":
						return {"ok": false, "reason": "component_conflict_with_scene_box:character_roster_member"}

	return {"ok": true, "data": clean_state}


func configure_character_roster(state: Dictionary) -> Dictionary:
	var gate: Dictionary = _check_gate("configure_character_roster")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var checked: Dictionary = validate_state(state)
	if not bool(checked.get("ok", false)):
		var reason: String = str(checked.get("reason", "invalid_character_roster_state"))
		_warn("character_roster 配置校验失败：%s" % reason)
		return {"ok": false, "reason": reason}

	var normalized: Dictionary = checked["data"] as Dictionary
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, normalized))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"config": normalized,
		"enabled": bool(gate.get("enabled", false)),
		"policy": str(gate.get("policy", "preserve")),
		"preserved": not bool(gate.get("enabled", false)),
	}


func set_auto_join(auto_join: bool) -> Dictionary:
	return configure_character_roster({"auto_join": auto_join})


func set_state(state: Dictionary) -> Dictionary:
	return configure_character_roster(state)


func attach_character_roster_member(
	entity_id: String,
	state: Dictionary = {},
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_character_roster_member")
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

	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var checked: Dictionary = validate_member_state(state, entity, effective_parked)
	if not bool(checked.get("ok", false)):
		var reason: String = str(checked.get("reason", "invalid_roster_member_state"))
		_warn("无法挂载 character_roster_member 组件（%s）：%s" % [entity_id, reason])
		return {"ok": false, "reason": reason}

	var clean_state: Dictionary = checked["data"] as Dictionary
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_ROSTER_MEMBER_SCRIPT,
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


func attach_roster_member(
	entity_id: String,
	state: Dictionary = {},
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	return attach_character_roster_member(entity_id, state, parked, manual)


func get_state() -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {}
	if wb.has_method("get_module_state"):
		return wb.get_module_state(MODULE_ID)
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("get_module_state"):
		return adapter.get_module_state(wb.get_world(), MODULE_ID)
	return {}


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


## 保持白盒测试兼容性：委托 utils/bounded_cloner.gd 执行无记忆化轻量有界字典深拷贝。
func _safe_clone_dict(d: Dictionary, depth: int = 0, stack: Array = [], budget: Array = []) -> Dictionary:
	return _bounded_cloner().simple_clone_dict(d, depth, stack, budget)
