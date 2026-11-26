extends RefCounted
## Fu vtt HookIds & HookBus Runtime Helper
##
## Mirrors all 61 built-in `HookIds.TABLE` contracts (`cancellable`, `arity`),
## validates custom namespaced hooks (`^(ext|mod)\.[a-z0-9_]+(\.[a-z0-9_]+)+$`, <= 128 chars),
## and guards `subscribe_hook` / `emit_hook` calls against `ExtensionContext`.

const MAX_HOOK_ID_LENGTH: int = 128
const MAX_BUILTIN_ARITY: int = 6

const FU_SDK_UTILS_REL: String = "../fu_sdk/utils/"
const DEV_FALLBACK_UTILS_DIR: String = "shared/sdk/fu_sdk/utils/"

const BUILTIN_HOOKS: Dictionary = {
	# === entity (9) ===
	&"entity.spawned": {"cancellable": false, "arity": 1},
	&"entity.removed": {"cancellable": false, "arity": 1},
	&"entity.trashed": {"cancellable": false, "arity": 1},
	&"entity.restored": {"cancellable": false, "arity": 1},
	&"entity.property_changed": {"cancellable": false, "arity": 4},
	&"entity.moved": {"cancellable": false, "arity": 3},
	&"entity.motion_committed": {"cancellable": false, "arity": 1},
	&"entity.selected": {"cancellable": false, "arity": 1},
	&"entity.deselected": {"cancellable": false, "arity": 1},
	# === comp (3) ===
	&"comp.added": {"cancellable": false, "arity": 2},
	&"comp.removed": {"cancellable": false, "arity": 2},
	&"comp.state_changed": {"cancellable": false, "arity": 2},
	# === mode (2) ===
	&"mode.pre_change": {"cancellable": true, "arity": 2},
	&"mode.changed": {"cancellable": false, "arity": 2},
	# === selection (1) ===
	&"selection.changed": {"cancellable": false, "arity": 1},
	# === viewpoint (1) ===
	&"viewpoint.changed": {"cancellable": false, "arity": 1},
	# === input (3) ===
	&"input.mouse_button": {"cancellable": true, "arity": 1},
	&"input.mouse_motion": {"cancellable": true, "arity": 1},
	&"input.key": {"cancellable": true, "arity": 1},
	# === frame (2) ===
	&"frame.process": {"cancellable": false, "arity": 1},
	&"frame.physics": {"cancellable": false, "arity": 1},
	# === room (4) ===
	&"room.player_joined": {"cancellable": false, "arity": 2},
	&"room.player_left": {"cancellable": false, "arity": 1},
	&"room.player_connection_info_changed": {"cancellable": false, "arity": 2},
	&"room.permission_changed": {"cancellable": false, "arity": 3},
	# === save (4) ===
	&"save.pre_capture": {"cancellable": false, "arity": 1},
	&"save.post_capture": {"cancellable": false, "arity": 1},
	&"save.pre_restore": {"cancellable": false, "arity": 1},
	&"save.post_restore": {"cancellable": false, "arity": 1},
	# === palette (2) ===
	&"palette.armed": {"cancellable": false, "arity": 2},
	&"palette.placed": {"cancellable": false, "arity": 1},
	# === combat (4) ===
	&"combat.round_start": {"cancellable": false, "arity": 1},
	&"combat.round_end": {"cancellable": false, "arity": 1},
	&"combat.turn_start": {"cancellable": false, "arity": 2},
	&"combat.turn_end": {"cancellable": false, "arity": 2},
	# === area & door (4) ===
	&"area.enter": {"cancellable": false, "arity": 1},
	&"area.exit": {"cancellable": false, "arity": 1},
	&"area.stay_tick": {"cancellable": false, "arity": 1},
	&"door.toggled": {"cancellable": false, "arity": 1},
	# === portal & trap (2) ===
	&"portal.teleported": {"cancellable": false, "arity": 1},
	&"trap.triggered": {"cancellable": false, "arity": 1},
	# === transform (1) ===
	&"transform.changed": {"cancellable": false, "arity": 1},
	# === rest (2) ===
	&"rest.short": {"cancellable": false, "arity": 1},
	&"rest.long": {"cancellable": false, "arity": 1},
	# === camera (1) ===
	&"camera.navigated": {"cancellable": false, "arity": 1},
	# === drawing (1) ===
	&"drawing.stroke_committed": {"cancellable": false, "arity": 1},
	# === ui (1) ===
	&"ui.panel_opened": {"cancellable": false, "arity": 1},
	# === floor, module, scene, entity_box (5) ===
	&"floor.changed": {"cancellable": false, "arity": 1},
	&"module.toggled": {"cancellable": false, "arity": 1},
	&"scene.switched": {"cancellable": false, "arity": 1},
	&"scene.created": {"cancellable": false, "arity": 1},
	&"entity_box.acted": {"cancellable": false, "arity": 1},
	# === dice (1) ===
	&"dice.rolled": {"cancellable": false, "arity": 1},
	# === combat_lifecycle (2) ===
	&"combat.started": {"cancellable": false, "arity": 1},
	&"combat.ended": {"cancellable": false, "arity": 1},
	# === vitals (2) ===
	&"vitals.changed": {"cancellable": false, "arity": 1},
	&"vitals.downed": {"cancellable": false, "arity": 1},
	# === chat, avg, checklist (4) ===
	&"chat.message_received": {"cancellable": false, "arity": 1},
	&"avg.stage_changed": {"cancellable": false, "arity": 1},
	&"avg.dialogue_shown": {"cancellable": false, "arity": 1},
	&"checklist.completed": {"cancellable": false, "arity": 1},
}

var _ctx_ref: WeakRef = null
var _log_ref: WeakRef = null
var _runtime_ref: WeakRef = null
var _tokens: Array = []
var _util_scripts: Dictionary = {}


func _init(context: Variant = null, log_bus: RefCounted = null, runtime: RefCounted = null) -> void:
	if log_bus != null and is_instance_valid(log_bus):
		_log_ref = weakref(log_bus)
	if runtime != null and is_instance_valid(runtime):
		_runtime_ref = weakref(runtime)
	if context != null:
		bind(context)


func _load_util_script(file_name: String) -> Variant:
	if _util_scripts.has(file_name):
		return _util_scripts[file_name]
	var rel_path: String = FU_SDK_UTILS_REL + file_name
	var self_scr := get_script() as Script
	if self_scr != null and not self_scr.resource_path.is_empty():
		var base_dir: String = self_scr.resource_path.split("::")[0].get_base_dir()
		var candidate: String = base_dir.path_join(rel_path).simplify_path()
		if ResourceLoader.exists(candidate) or FileAccess.file_exists(candidate):
			var loaded := load(candidate) as Script
			if loaded != null:
				_util_scripts[file_name] = loaded
				return loaded
	for raw_frame: Variant in get_stack():
		if raw_frame is Dictionary:
			var src_file: String = str((raw_frame as Dictionary).get("source", ""))
			if not src_file.is_empty():
				var stack_cand: String = src_file.get_base_dir().path_join(rel_path).simplify_path()
				if ResourceLoader.exists(stack_cand) or FileAccess.file_exists(stack_cand):
					var loaded_stack := load(stack_cand) as Script
					if loaded_stack != null:
						_util_scripts[file_name] = loaded_stack
						return loaded_stack
	for fb_path: String in [
		("res://" + DEV_FALLBACK_UTILS_DIR).path_join(file_name),
		DEV_FALLBACK_UTILS_DIR.path_join(file_name),
	]:
		if ResourceLoader.exists(fb_path) or FileAccess.file_exists(fb_path):
			var loaded_fb := load(fb_path) as Script
			if loaded_fb != null:
				_util_scripts[file_name] = loaded_fb
				return loaded_fb
	return null


func _bounded_cloner() -> Variant:
	return _load_util_script("bounded_cloner.gd")


func _validation_utils() -> Variant:
	return _load_util_script("validation_utils.gd")


func _log_error(message: String, context: Dictionary = {}) -> void:
	if _log_ref == null:
		return
	var bus: Variant = _log_ref.get_ref()
	if bus != null and is_instance_valid(bus) and bus.has_method(&"error"):
		bus.call(&"error", "fu_runtime.hooks", message, context)


func _log_warn(message: String, context: Dictionary = {}) -> void:
	if _log_ref == null:
		return
	var bus: Variant = _log_ref.get_ref()
	if bus != null and is_instance_valid(bus) and bus.has_method(&"warn"):
		bus.call(&"warn", "fu_runtime.hooks", message, context)


func _ctx() -> Object:
	if _ctx_ref == null:
		return null
	var obj: Variant = _ctx_ref.get_ref()
	if obj == null or not is_instance_valid(obj):
		return null
	return obj as Object


func bind(context: Variant) -> bool:
	unbind()
	if context == null or not (context is Object) or not is_instance_valid(context):
		return false
	var obj := context as Object
	if not obj.has_method(&"subscribe_hook") or not obj.has_method(&"emit_hook"):
		_log_warn("Rejected invalid ExtensionContext for hook_helper")
		return false
	_ctx_ref = weakref(obj)
	return true


func unbind() -> void:
	revert_tracked()
	_ctx_ref = null


static func is_builtin_hook(hook_id: StringName) -> bool:
	return BUILTIN_HOOKS.has(hook_id)


static func is_custom_namespaced(hook_id: StringName) -> bool:
	var text: String = String(hook_id)
	if not (text.begins_with("ext.") or text.begins_with("mod.")):
		return false
	if text.length() > MAX_HOOK_ID_LENGTH:
		return false
	var parts: PackedStringArray = text.split(".")
	if parts.size() < 3:
		return false
	for idx: int in range(1, parts.size()):
		var seg: String = parts[idx]
		if seg.is_empty():
			return false
		for ch_idx: int in range(seg.length()):
			var code: int = seg.unicode_at(ch_idx)
			var ok: bool = (code >= 97 and code <= 122) or (code >= 48 and code <= 57) or code == 95
			if not ok:
				return false
	return true


static func is_registered_hook(hook_id: StringName) -> bool:
	return is_builtin_hook(hook_id) or is_custom_namespaced(hook_id)


static func expected_arity(hook_id: StringName) -> int:
	if BUILTIN_HOOKS.has(hook_id):
		var info: Dictionary = BUILTIN_HOOKS[hook_id] as Dictionary
		return int(info.get("arity", -1))
	if is_custom_namespaced(hook_id):
		return 1
	return -1


static func is_cancellable(hook_id: StringName) -> bool:
	if not BUILTIN_HOOKS.has(hook_id):
		return false
	var info: Dictionary = BUILTIN_HOOKS[hook_id] as Dictionary
	return bool(info.get("cancellable", false))


func build_custom_hook_id(prefix: String, plugin_id: String, event_name: String) -> StringName:
	var val_u: Variant = _validation_utils()
	var clean_prefix: String = (str(val_u.strip_bom_and_edges(prefix)) if val_u != null else prefix.strip_edges()).to_lower()
	var clean_plugin: String = (str(val_u.strip_bom_and_edges(plugin_id)) if val_u != null else plugin_id.strip_edges()).to_lower()
	var clean_event: String = (str(val_u.strip_bom_and_edges(event_name)) if val_u != null else event_name.strip_edges()).to_lower()
	if clean_prefix != "ext" and clean_prefix != "mod":
		_log_warn("Invalid custom hook prefix", {"prefix": clean_prefix})
		return &""
	if clean_plugin.is_empty() or clean_event.is_empty():
		_log_warn("Empty plugin_id or event_name for custom hook")
		return &""
	var candidate := StringName(clean_prefix + "." + clean_plugin + "." + clean_event)
	if not is_custom_namespaced(candidate):
		_log_warn("Custom hook ID violates naming rules", {"hook_id": String(candidate)})
		return &""
	return candidate


func _callable_accepts_arity(callback: Callable, want_arity: int) -> bool:
	var total_args: int = callback.get_argument_count()
	if total_args < want_arity:
		return false
	if not callback.is_custom():
		var target_obj: Object = callback.get_object()
		var method_name: String = String(callback.get_method())
		if is_instance_valid(target_obj) and not method_name.is_empty():
			var bound_cnt: int = callback.get_bound_arguments_count()
			for md: Dictionary in target_obj.get_method_list():
				if String(md.get("name", "")) == method_name:
					var args_arr: Array = md.get("args", []) as Array
					var def_arr: Array = md.get("default_args", []) as Array
					var req_args: int = maxi(0, args_arr.size() - def_arr.size() - bound_cnt)
					return want_arity >= req_args and want_arity <= total_args
	return true


func subscribe(hook_id: StringName, callback: Callable, priority: int = 0) -> Variant:
	var ctx: Object = _ctx()
	if ctx == null:
		_log_error("Cannot subscribe hook without active ExtensionContext", {"hook_id": String(hook_id)})
		return null
	if not is_registered_hook(hook_id):
		_log_error("Unknown or invalid hook_id", {"hook_id": String(hook_id)})
		return null
	if not callback.is_valid():
		_log_error("Invalid callback for hook subscribe", {"hook_id": String(hook_id)})
		return null
	var want_arity: int = expected_arity(hook_id)
	if want_arity < 0 or want_arity > MAX_BUILTIN_ARITY:
		_log_error("Invalid expected arity for hook", {"hook_id": String(hook_id), "arity": want_arity})
		return null
	if not _callable_accepts_arity(callback, want_arity):
		_log_error("Hook callback arity mismatch", {
			"hook_id": String(hook_id),
			"expected_arity": want_arity,
			"actual_arity": callback.get_argument_count(),
		})
		return null
	var token: Variant = ctx.call(&"subscribe_hook", hook_id, callback, priority)
	if token is Object and is_instance_valid(token):
		var tok_obj := token as Object
		var active: bool = true
		if tok_obj.has_method(&"is_active"):
			active = bool(tok_obj.call(&"is_active"))
		if active:
			_tokens.append(tok_obj)
		else:
			_log_warn("Hook subscription rejected by ExtensionContext", {"hook_id": String(hook_id)})
		return tok_obj
	return null


func emit(hook_id: StringName, arguments: Array = []) -> Dictionary:
	var ctx: Object = _ctx()
	if ctx == null:
		return {"ok": false, "reason": "context_unavailable"}
	if not is_registered_hook(hook_id):
		return {"ok": false, "reason": "hook_unknown"}
	var want_arity: int = expected_arity(hook_id)
	if arguments.size() != want_arity:
		return {"ok": false, "reason": "hook_arity_mismatch", "expected": want_arity, "actual": arguments.size()}
	if is_custom_namespaced(hook_id):
		if not (arguments[0] is Dictionary):
			return {"ok": false, "reason": "custom_hook_requires_dictionary_payload"}
		var bc: Variant = _bounded_cloner()
		if bc != null and bool(bc.has_cycle(arguments[0])):
			return {"ok": false, "reason": "payload_cycle_or_depth_exceeded"}
	var emitted: bool = bool(ctx.call(&"emit_hook", hook_id, arguments))
	return {"ok": true, "emitted": emitted}


func emit_custom(hook_id: StringName, payload: Dictionary = {}) -> Dictionary:
	if not is_custom_namespaced(hook_id):
		return {"ok": false, "reason": "invalid_custom_hook_id"}
	return emit(hook_id, [payload])


func revert_tracked() -> void:
	var idx: int = _tokens.size() - 1
	while idx >= 0:
		var tok: Variant = _tokens[idx]
		if tok is Object and is_instance_valid(tok) and (tok as Object).has_method(&"revert"):
			(tok as Object).call(&"revert")
		idx -= 1
	_tokens.clear()
