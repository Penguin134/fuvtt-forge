extends RefCounted
## Fu vtt 候选插件 SDK：entity_notes（未入正式目录候选模块 comp_entity_note 与自动停泊保底）
##
## 对应官方源码：scenes/candidates/entity_notes/comp_entity_note.gd、
## feature_entity_notes.gd、note_actions.gd、scenes/entities/entity_state_codec.gd。

const MODULE_ID: String = "entity_notes"
const COMP_ENTITY_NOTE_SCRIPT: String = "res://scenes/candidates/entity_notes/comp_entity_note.gd"
const SCHEMA_VERSION: int = 1
const MAX_TEXT_LENGTH: int = 32768
const STATE_FIELDS: Array[String] = ["schema_version", "text", "keep_screen_size", "is_pin"]

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
		"candidate": true,
		"status": "uncatalogued_candidate",
		"enabled": false,
	}


func make_note_state(
	text: String,
	is_pin: bool = true,
	keep_screen_size: bool = true
) -> Dictionary:
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("make_entity_note_state"):
		return adapter.make_entity_note_state(text, is_pin, keep_screen_size)
	return {
		"schema_version": SCHEMA_VERSION,
		"text": str(_validation_utils().strip_nul(text)).left(MAX_TEXT_LENGTH),
		"keep_screen_size": keep_screen_size,
		"is_pin": is_pin,
	}


func validate_note_state(state: Dictionary) -> Dictionary:
	var errors: Array[String] = []
	for raw_k: Variant in state.keys():
		if not (raw_k is String) or not (str(raw_k) in STATE_FIELDS):
			errors.append("unknown_entity_note_key:" + str(raw_k))
	if state.has("schema_version"):
		var sv: Variant = state["schema_version"]
		if not (sv is int) or int(sv) != SCHEMA_VERSION:
			errors.append("invalid_schema_version")
	if state.has("text"):
		var tv: Variant = state["text"]
		if not (tv is String) or str(tv).length() > MAX_TEXT_LENGTH:
			errors.append("invalid_note_text")
	if state.has("keep_screen_size") and not (state["keep_screen_size"] is bool):
		errors.append("invalid_keep_screen_size")
	if state.has("is_pin") and not (state["is_pin"] is bool):
		errors.append("invalid_is_pin")
	return {"ok": errors.is_empty(), "errors": errors}


func attach_note(
	entity_id: String,
	text: String,
	is_pin: bool = true,
	keep_screen_size: bool = true,
	parked: bool = true,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_note")
	if not bool(gate.get("ok", true)):
		return gate
	return _attach_note_impl(entity_id, text, is_pin, keep_screen_size, parked, manual, gate)


func _attach_note_impl(
	entity_id: String,
	text: String,
	is_pin: bool,
	keep_screen_size: bool,
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

	var state: Dictionary = make_note_state(text, is_pin, keep_screen_size)
	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_ENTITY_NOTE_SCRIPT,
		state,
		effective_parked,
		effective_manual
	))
	if not ok:
		return {"ok": false, "reason": "attach_component_failed"}
	return {
		"ok": true,
		"entity_id": entity_id,
		"parked": effective_parked,
		"manual": effective_manual,
		"status": str(gate.get("status", "uncatalogued_candidate")),
	}


func attach_entity_note(
	entity_id: String,
	text_or_state: Variant = "",
	is_pin: bool = true,
	keep_screen_size: bool = true,
	parked: bool = true,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_entity_note")
	if not bool(gate.get("ok", true)):
		return gate
	if text_or_state is String or text_or_state is StringName:
		return _attach_note_impl(entity_id, str(text_or_state), is_pin, keep_screen_size, parked, manual, gate)
	if text_or_state is Dictionary:
		var d: Dictionary = text_or_state as Dictionary
		var eff_parked: bool = parked
		var eff_manual: bool = manual
		var note_d: Dictionary = {}
		var opt_err: String = ""
		for raw_k: Variant in d.keys():
			if raw_k is String and str(raw_k) == "parked":
				if d[raw_k] is bool:
					eff_parked = bool(d[raw_k])
				else:
					opt_err = "invalid_parked"
					break
			elif raw_k is String and str(raw_k) == "manual":
				if d[raw_k] is bool:
					eff_manual = bool(d[raw_k])
				else:
					opt_err = "invalid_manual"
					break
			elif raw_k is String and str(raw_k) == "schema_version":
				var sv_p: Dictionary = _value_utils().parse_int_val(d[raw_k])
				note_d["schema_version"] = int(sv_p["value"]) if bool(sv_p["ok"]) else d[raw_k]
			else:
				note_d[raw_k] = d[raw_k]
		if eff_manual and not eff_parked:
			return {"ok": false, "reason": "manual_requires_parked"}
		if not opt_err.is_empty():
			return {"ok": false, "reason": opt_err}
		var val_res: Dictionary = validate_note_state(note_d)
		if not bool(val_res.get("ok", false)):
			var errs: Array = val_res.get("errors", []) as Array
			return {"ok": false, "reason": str(errs[0]) if not errs.is_empty() else "invalid_entity_note"}
		return _attach_note_impl(
			entity_id,
			str(note_d.get("text", "")),
			bool(note_d.get("is_pin", is_pin)),
			bool(note_d.get("keep_screen_size", keep_screen_size)),
			eff_parked,
			eff_manual,
			gate
		)
	return {"ok": false, "reason": "invalid_note_text"}


func add_text_pin(
	source_id: String,
	text: String,
	center_src: Vector2,
	name: String = "",
	keep_screen_size: bool = true,
	size_src: Vector2 = Vector2(40.0, 40.0),
	hidden: bool = false,
	layer_uid_override: String = "",
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("add_text_pin")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var clean_text: String = str(_validation_utils().strip_nul(text)).left(MAX_TEXT_LENGTH)
	var label: String = name if not name.strip_edges().is_empty() else (clean_text.left(32) if not clean_text.is_empty() else "文本图钉")
	var entity_id: String = str(wb.add_object_sprite(
		source_id,
		label,
		center_src,
		size_src,
		"",
		0.0,
		Vector2.ONE,
		hidden,
		layer_uid_override,
		false
	))
	if entity_id.is_empty():
		return {"ok": false, "reason": "add_object_sprite_failed"}

	var note_state: Dictionary = make_note_state(clean_text, true, keep_screen_size)
	var effective_parked: bool = true
	var effective_manual: bool = manual
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_ENTITY_NOTE_SCRIPT,
		note_state,
		effective_parked,
		effective_manual
	))
	if not ok:
		return {"ok": false, "reason": "attach_component_failed"}
	return {
		"ok": true,
		"entity_id": entity_id,
		"parked": effective_parked,
		"manual": effective_manual,
		"status": str(gate.get("status", "uncatalogued_candidate")),
	}


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
	return {
		"ok": true,
		"enabled": false,
		"status": "uncatalogued_candidate",
		"policy": "preserve",
		"skipped": false,
	}
