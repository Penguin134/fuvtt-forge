extends RefCounted
## Fu vtt 原生可选插件 SDK：drag_movement（角色匀速拖拽模块配置 v2 与实体速度组件 comp_drag_speed）
##
## 对应官方源码：modules/drag_movement/feature_drag_movement.gd、comp_drag_speed.gd、
## scenes/entities/board_token.gd（comp_drag_speed 与 scene_box 互斥）。

const MODULE_ID: String = "drag_movement"
const MODULE_VERSION: int = 1
const STATE_VERSION: int = 2
const DEFAULT_SPEED: float = 64.0
const V1_LEGACY_DEFAULT_SPEED: float = 256.0
const COMP_DRAG_SPEED_SCRIPT: String = "res://modules/drag_movement/comp_drag_speed.gd"

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


func default_world_config() -> Dictionary:
	return {
		"version": STATE_VERSION,
		"speed": DEFAULT_SPEED,
	}


func make_world_config(speed: float = DEFAULT_SPEED, version: int = STATE_VERSION) -> Dictionary:
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("make_drag_movement_world_state"):
		return adapter.make_drag_movement_world_state(speed, version)
	var safe_speed: float = maxf(0.0, float(speed) if is_finite(speed) else DEFAULT_SPEED)
	if version == 1 and is_equal_approx(safe_speed, V1_LEGACY_DEFAULT_SPEED):
		safe_speed = DEFAULT_SPEED
	return {
		"version": STATE_VERSION,
		"speed": safe_speed,
	}


func validate_world_config(state: Dictionary) -> Dictionary:
	if state.is_empty():
		return {"ok": true, "data": default_world_config(), "reason": ""}
	for raw_k: Variant in state.keys():
		if not (raw_k is String) or not (str(raw_k) in ["version", "speed"]):
			return {"ok": false, "data": {}, "reason": "drag_configuration_invalid"}
	var ver_p: Dictionary = _value_utils().parse_int_val(state.get("version", STATE_VERSION))
	if not bool(ver_p["ok"]) or not (int(ver_p["value"]) in [1, 2]):
		return {"ok": false, "data": {}, "reason": "drag_configuration_invalid"}
	var ver: int = int(ver_p["value"])
	var spd_v: Variant = state.get("speed", DEFAULT_SPEED)
	if not (spd_v is int or spd_v is float):
		return {"ok": false, "data": {}, "reason": "drag_configuration_invalid"}
	var spd: float = float(spd_v)
	if not is_finite(spd) or spd < 0.0:
		return {"ok": false, "data": {}, "reason": "drag_configuration_invalid"}
	if ver == 1 and is_equal_approx(spd, V1_LEGACY_DEFAULT_SPEED):
		spd = DEFAULT_SPEED
	return {
		"ok": true,
		"data": {
			"version": STATE_VERSION,
			"speed": spd,
		},
		"reason": "",
	}


func configure_default_speed(speed: float = DEFAULT_SPEED, version: int = STATE_VERSION) -> Dictionary:
	var gate: Dictionary = _check_gate("configure_default_speed")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var checked: Dictionary = validate_world_config({"version": version, "speed": speed})
	if not bool(checked.get("ok", false)):
		return {"ok": false, "reason": str(checked.get("reason", "drag_configuration_invalid"))}
	var normalized: Dictionary = checked["data"] as Dictionary
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, normalized))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"config": normalized,
		"enabled": bool(gate.get("enabled", false)),
		"policy": str(gate.get("policy", "preserve")),
	}


func configure_drag_movement(
	state_or_speed: Variant = DEFAULT_SPEED,
	version: int = STATE_VERSION
) -> Dictionary:
	if state_or_speed is int or state_or_speed is float:
		return configure_default_speed(float(state_or_speed), version)
	var gate: Dictionary = _check_gate("configure_drag_movement")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}
	if not (state_or_speed is Dictionary):
		return {"ok": false, "reason": "drag_configuration_invalid"}

	var checked: Dictionary = validate_world_config(state_or_speed as Dictionary)
	if not bool(checked.get("ok", false)):
		return {"ok": false, "reason": str(checked.get("reason", "drag_configuration_invalid"))}
	var normalized: Dictionary = checked["data"] as Dictionary
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, normalized))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"config": normalized,
		"enabled": bool(gate.get("enabled", false)),
		"policy": str(gate.get("policy", "preserve")),
	}


func get_world_config() -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {}
	if wb.has_method("get_module_state"):
		return wb.get_module_state(MODULE_ID)
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("get_module_state"):
		return adapter.get_module_state(wb.get_world(), MODULE_ID)
	return {}


func make_speed_state(speed: float = DEFAULT_SPEED) -> Dictionary:
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("make_drag_speed_state"):
		return adapter.make_drag_speed_state(speed)
	return {
		"speed": maxf(0.0, float(speed) if is_finite(speed) else DEFAULT_SPEED),
	}


func validate_speed_state(state: Dictionary, entity: Dictionary = {}) -> Dictionary:
	var errors: Array[String] = []
	for raw_k: Variant in state.keys():
		if not (raw_k is String) or str(raw_k) != "speed":
			errors.append("unknown_drag_speed_key:" + str(raw_k))
	if not state.has("speed"):
		errors.append("missing_speed")
	else:
		var spd_v: Variant = state["speed"]
		if not (spd_v is float) or not is_finite(float(spd_v)) or float(spd_v) < 0.0:
			errors.append("invalid_drag_speed")

	if not entity.is_empty():
		var valid_u: Variant = _validation_utils()
		var comps_var: Variant = entity.get("components", [])
		if comps_var is Array:
			for raw_c: Variant in comps_var as Array:
				if raw_c is Dictionary:
					var scr: String = str((raw_c as Dictionary).get("script", ""))
					var cid: String = str(valid_u.component_id_from_script(scr))
					if cid == "scene_box":
						errors.append("component_conflict_with_scene_box:drag_speed")
						break

	return {"ok": errors.is_empty(), "errors": errors}


func set_entity_speed(
	entity_id: String,
	speed: float = DEFAULT_SPEED,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("set_entity_speed")
	if not bool(gate.get("ok", true)):
		return gate
	if manual and not parked:
		return {"ok": false, "reason": "manual_requires_parked"}
	if not is_finite(speed) or speed < 0.0:
		return {"ok": false, "reason": "invalid_drag_speed"}
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return {"ok": false, "reason": "entity_not_found"}

	var state: Dictionary = make_speed_state(float(speed))
	var val_res: Dictionary = validate_speed_state(state, entity)
	if not bool(val_res.get("ok", false)):
		var err_list: Array = val_res.get("errors", [])
		var reason: String = str(err_list[0]) if not err_list.is_empty() else "invalid_drag_speed"
		_warn("无法挂载 drag_speed 组件（%s）：%s" % [entity_id, reason])
		return {"ok": false, "reason": reason}

	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_DRAG_SPEED_SCRIPT,
		state,
		effective_parked,
		effective_manual
	))
	if not ok:
		return {"ok": false, "reason": "attach_component_failed"}
	return {
		"ok": true,
		"entity_id": entity_id,
		"speed": float(state["speed"]),
		"parked": effective_parked,
		"manual": effective_manual,
	}


func attach_drag_speed(
	entity_id: String,
	speed: float = DEFAULT_SPEED,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	return set_entity_speed(entity_id, speed, parked, manual)


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
