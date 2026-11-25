extends RefCounted
## Fu vtt 原生可选插件 SDK：image_flip（图片水平/垂直翻转组件 comp_image_flip）
##
## 对应官方源码：modules/image_flip/feature_image_flip.gd、comp_image_flip.gd、
## scenes/entities/board_token.gd（与 obstacle、area、scene_box 互斥）。

const MODULE_ID: String = "image_flip"
const COMP_IMAGE_FLIP_SCRIPT: String = "res://modules/image_flip/comp_image_flip.gd"
const CONFLICT_COMPONENT_IDS: Array[String] = ["obstacle", "area", "scene_box"]

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


func make_flip_state(horizontal: bool = false, vertical: bool = false) -> Dictionary:
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("make_image_flip_state"):
		return adapter.make_image_flip_state(horizontal, vertical)
	return {
		"horizontal": horizontal,
		"vertical": vertical,
	}


func validate_flip_state(state: Dictionary, entity: Dictionary = {}) -> Dictionary:
	var errors: Array[String] = []
	var allowed: Array[String] = ["horizontal", "vertical"]
	for raw_k: Variant in state.keys():
		if not (raw_k is String) or not (str(raw_k) in allowed):
			errors.append("unknown_image_flip_key:" + str(raw_k))
	if state.has("horizontal") and not (state["horizontal"] is bool):
		errors.append("invalid_horizontal_type")
	if state.has("vertical") and not (state["vertical"] is bool):
		errors.append("invalid_vertical_type")

	if not entity.is_empty():
		var valid_u: Variant = _validation_utils()
		var comps_var: Variant = entity.get("components", [])
		if comps_var is Array:
			for raw_c: Variant in comps_var as Array:
				if raw_c is Dictionary:
					var c_dict: Dictionary = raw_c as Dictionary
					var scr: String = str(c_dict.get("script", ""))
					var cid: String = str(valid_u.component_id_from_script(scr))
					if cid in CONFLICT_COMPONENT_IDS:
						var err_tag: String = "component_conflict_with_image_flip:" + cid
						if not (err_tag in errors):
							errors.append(err_tag)
					elif cid == "visual":
						var st_var: Variant = c_dict.get("state", null)
						if st_var is Dictionary:
							var vd_var: Variant = (st_var as Dictionary).get("vector_drawing", null)
							if vd_var is Dictionary:
								var src_var: Variant = (vd_var as Dictionary).get("source", null)
								if src_var is Dictionary:
									var vkind: String = str((src_var as Dictionary).get("kind", ""))
									if vkind in ["wall", "air", "door", "window", "glass"]:
										var obs_err: String = "component_conflict_with_image_flip:obstacle"
										if not (obs_err in errors):
											errors.append(obs_err)
									elif vkind == "area":
										var area_err: String = "component_conflict_with_image_flip:area"
										if not (area_err in errors):
											errors.append(area_err)

	return {"ok": errors.is_empty(), "errors": errors}


func set_flip(
	entity_id: String,
	horizontal: bool = false,
	vertical: bool = false,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("set_flip")
	if not bool(gate.get("ok", true)):
		return gate
	return _apply_flip(entity_id, horizontal, vertical, parked, manual, gate)


func _apply_flip(
	entity_id: String,
	horizontal: bool,
	vertical: bool,
	parked: bool,
	manual: bool,
	gate: Dictionary
) -> Dictionary:
	if manual and not parked:
		return {"ok": false, "reason": "manual_requires_parked"}
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return {"ok": false, "reason": "entity_not_found"}

	var state: Dictionary = make_flip_state(horizontal, vertical)
	var val_res: Dictionary = validate_flip_state(state, entity)
	if not bool(val_res.get("ok", false)):
		var err_list: Array = val_res.get("errors", [])
		var reason: String = str(err_list[0]) if not err_list.is_empty() else "component_conflict_with_image_flip"
		_warn("无法挂载 image_flip 组件（%s）：%s" % [entity_id, reason])
		return {"ok": false, "reason": reason}

	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_IMAGE_FLIP_SCRIPT,
		state,
		effective_parked,
		effective_manual
	))
	if not ok:
		return {"ok": false, "reason": "attach_component_failed"}
	return {
		"ok": true,
		"entity_id": entity_id,
		"horizontal": horizontal,
		"vertical": vertical,
		"parked": effective_parked,
		"manual": effective_manual,
	}


func attach_flip(
	entity_id: String,
	horizontal: bool = false,
	vertical: bool = false,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	return set_flip(entity_id, horizontal, vertical, parked, manual)


func attach_image_flip(
	entity_id: String,
	horizontal_or_state: Variant = false,
	vertical: bool = false,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	if horizontal_or_state is bool:
		return set_flip(entity_id, bool(horizontal_or_state), vertical, parked, manual)
	var gate: Dictionary = _check_gate("attach_image_flip")
	if not bool(gate.get("ok", true)):
		return gate
	if horizontal_or_state is Dictionary:
		var d: Dictionary = horizontal_or_state as Dictionary
		for raw_k: Variant in d.keys():
			if not (raw_k is String) or not (str(raw_k) in ["horizontal", "vertical", "parked", "manual"]):
				return {"ok": false, "reason": "unknown_image_flip_key:" + str(raw_k)}
		var h_v: Variant = d.get("horizontal", false)
		var v_v: Variant = d.get("vertical", false)
		if not (h_v is bool):
			return {"ok": false, "reason": "invalid_horizontal_type"}
		if not (v_v is bool):
			return {"ok": false, "reason": "invalid_vertical_type"}
		var eff_parked: bool = parked
		if d.has("parked"):
			if not (d["parked"] is bool):
				return {"ok": false, "reason": "invalid_parked_type"}
			eff_parked = bool(d["parked"])
		var eff_manual: bool = manual
		if d.has("manual"):
			if not (d["manual"] is bool):
				return {"ok": false, "reason": "invalid_manual_type"}
			eff_manual = bool(d["manual"])
		return _apply_flip(entity_id, bool(h_v), bool(v_v), eff_parked, eff_manual, gate)
	return {"ok": false, "reason": "invalid_horizontal_type"}


func set_image_flip(
	entity_id: String,
	horizontal_or_state: Variant = false,
	vertical: bool = false,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	return attach_image_flip(entity_id, horizontal_or_state, vertical, parked, manual)


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
