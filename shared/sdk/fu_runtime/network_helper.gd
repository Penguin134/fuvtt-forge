extends RefCounted
## Fu vtt Network & WorldModuleState Persistence Runtime Helper
##
## Covers `fus.plugin.v2` `network.actions`, `network.projections`, `network.presentations`,
## `local_only` isolation enforcement, and `WorldModuleState` 3-phase persistence & quota checks.

const SLOT_NETWORK_ACTIONS: StringName = &"network.actions"
const SLOT_NETWORK_PROJECTIONS: StringName = &"network.projections"
const SLOT_NETWORK_PRESENTATIONS: StringName = &"network.presentations"

const WORLD_MODULE_VERSION: int = 2
const MAX_MODULE_ENTRIES: int = 128
const MAX_MODULE_ID_LENGTH: int = 128
const MAX_ENTRY_BYTES: int = 16 * 1024 * 1024
const MAX_TOTAL_BYTES: int = 24 * 1024 * 1024
const MAX_DATA_DEPTH: int = 32
const MAX_ACTION_REASON_LENGTH: int = 256
const MAX_NOTIFICATION_KEY_LENGTH: int = 128

const REQUIRED_ACTION_METHODS: Array[String] = [
	"network_action_valid",
	"network_action_revoked",
	"network_request",
]

const REQUIRED_PROJECTION_METHODS: Array[String] = [
	"network_projection",
	"network_cursor",
	"network_revoked",
	"validate_replica_projection",
	"capture_replica_projection",
	"stage_replica_projection",
	"publish_replica_projection",
	"restore_replica_projection",
]
const REQUIRED_PROJECTION_SIGNAL: String = "projection_changed"

const REQUIRED_PRESENTATION_METHODS: Array[String] = [
	"presentation_current",
	"receive_presentation",
]

const FU_SDK_UTILS_REL: String = "../fu_sdk/utils/"
const COMP_HELPER_REL: String = "comp_helper.gd"
const DEV_FALLBACK_UTILS_DIR: String = "shared/sdk/fu_sdk/utils/"
const DEV_FALLBACK_RUNTIME_DIR: String = "shared/sdk/fu_runtime/"

var _module_id: String = ""
var _local_only: bool = false
var _ctx_ref: WeakRef = null
var _log_ref: WeakRef = null
var _runtime_ref: WeakRef = null
var _util_scripts: Dictionary = {}
var _comp_helper_inst: RefCounted = null


func _init(
	module_id: String = "",
	local_only: bool = false,
	context: Variant = null,
	log_bus: RefCounted = null,
	runtime: RefCounted = null
) -> void:
	if log_bus != null and is_instance_valid(log_bus):
		_log_ref = weakref(log_bus)
	if runtime != null and is_instance_valid(runtime):
		_runtime_ref = weakref(runtime)
	configure(module_id, local_only, context)


func _load_script_rel(rel_path: String, fallback_sub_dir: String, file_name: String) -> Script:
	var cache_key: String = rel_path
	if _util_scripts.has(cache_key):
		return _util_scripts[cache_key] as Script
	var self_scr := get_script() as Script
	if self_scr != null and not self_scr.resource_path.is_empty():
		var base_dir: String = self_scr.resource_path.split("::")[0].get_base_dir()
		var candidate: String = base_dir.path_join(rel_path).simplify_path()
		if ResourceLoader.exists(candidate) or FileAccess.file_exists(candidate):
			var loaded := load(candidate) as Script
			if loaded != null:
				_util_scripts[cache_key] = loaded
				return loaded
	for raw_frame: Variant in get_stack():
		if raw_frame is Dictionary:
			var src_file: String = str((raw_frame as Dictionary).get("source", ""))
			if not src_file.is_empty():
				var stack_cand: String = src_file.get_base_dir().path_join(rel_path).simplify_path()
				if ResourceLoader.exists(stack_cand) or FileAccess.file_exists(stack_cand):
					var loaded_stack := load(stack_cand) as Script
					if loaded_stack != null:
						_util_scripts[cache_key] = loaded_stack
						return loaded_stack
	for fb_path: String in [
		("res://" + fallback_sub_dir).path_join(file_name),
		fallback_sub_dir.path_join(file_name),
	]:
		if ResourceLoader.exists(fb_path) or FileAccess.file_exists(fb_path):
			var loaded_fb := load(fb_path) as Script
			if loaded_fb != null:
				_util_scripts[cache_key] = loaded_fb
				return loaded_fb
	return null


func _load_util_script(file_name: String) -> Variant:
	return _load_script_rel(FU_SDK_UTILS_REL + file_name, DEV_FALLBACK_UTILS_DIR, file_name)


func _dag_cloner() -> Variant:
	return _load_util_script("dag_cloner.gd")


func _bounded_cloner() -> Variant:
	return _load_util_script("bounded_cloner.gd")


func _value_utils() -> Variant:
	return _load_util_script("value_utils.gd")


func _validation_utils() -> Variant:
	return _load_util_script("validation_utils.gd")


func _get_comp_helper() -> RefCounted:
	if _comp_helper_inst != null:
		return _comp_helper_inst
	var scr: Script = _load_script_rel(COMP_HELPER_REL, DEV_FALLBACK_RUNTIME_DIR, COMP_HELPER_REL)
	if scr != null:
		_comp_helper_inst = scr.new()
	return _comp_helper_inst


func _clean_str(raw: Variant) -> String:
	var vu: Variant = _value_utils()
	var val_u: Variant = _validation_utils()
	var s: String = str(vu.as_str(raw, "")) if vu != null else (String(raw) if (raw is String or raw is StringName) else "")
	return str(val_u.strip_bom_and_edges(s)) if val_u != null else s.strip_edges()


func _log_warn(message: String, context: Dictionary = {}) -> void:
	if _log_ref == null:
		return
	var bus: Variant = _log_ref.get_ref()
	if bus != null and is_instance_valid(bus) and bus.has_method(&"warn"):
		bus.call(&"warn", "fu_runtime.network", message, context)


func _ctx() -> Object:
	if _ctx_ref == null:
		return null
	var obj: Variant = _ctx_ref.get_ref()
	if obj == null or not is_instance_valid(obj):
		return null
	return obj as Object


func configure(module_id: String, local_only: bool = false, context: Variant = null) -> bool:
	var clean_id: String = _clean_str(module_id)
	if not clean_id.is_empty() and not is_valid_module_id(clean_id):
		_log_warn("Rejected invalid module_id in network_helper", {"module_id": clean_id})
		return false
	_module_id = clean_id
	_local_only = local_only
	if context != null:
		bind(context)
	return true


func bind(context: Variant) -> bool:
	_ctx_ref = null
	if context == null or not (context is Object) or not is_instance_valid(context):
		return false
	var obj := context as Object
	if not obj.has_method(&"register_slot_item"):
		_log_warn("Rejected invalid ExtensionContext for network_helper")
		return false
	_ctx_ref = weakref(obj)
	return true


func unbind() -> void:
	_ctx_ref = null


func is_local_only() -> bool:
	return _local_only


func get_module_id() -> String:
	return _module_id


static func is_valid_module_id(module_id: Variant) -> bool:
	if not (module_id is String):
		return false
	var s: String = module_id as String
	if s.is_empty() or s.length() > MAX_MODULE_ID_LENGTH:
		return false
	var parts: PackedStringArray = s.split(".")
	for seg: String in parts:
		if seg.is_empty():
			return false
		var first_code: int = seg.unicode_at(0)
		if first_code < 97 or first_code > 122:
			return false
		for i: int in range(1, seg.length()):
			var code: int = seg.unicode_at(i)
			var ok: bool = (code >= 97 and code <= 122) or (code >= 48 and code <= 57) or code == 95
			if not ok:
				return false
	return true


static func validate_action_provider(provider: Variant) -> Dictionary:
	var missing: Array[String] = []
	if provider == null or not (provider is Object) or not is_instance_valid(provider):
		for m: String in REQUIRED_ACTION_METHODS:
			missing.append(m)
		return {"ok": false, "missing_methods": missing}
	var obj := provider as Object
	for m: String in REQUIRED_ACTION_METHODS:
		if not obj.has_method(StringName(m)):
			missing.append(m)
	return {"ok": missing.is_empty(), "missing_methods": missing}


static func validate_projection_provider(provider: Variant) -> Dictionary:
	var missing_methods: Array[String] = []
	var missing_signals: Array[String] = []
	if provider == null or not (provider is Object) or not is_instance_valid(provider):
		for m: String in REQUIRED_PROJECTION_METHODS:
			missing_methods.append(m)
		missing_signals.append(REQUIRED_PROJECTION_SIGNAL)
		return {"ok": false, "missing_methods": missing_methods, "missing_signals": missing_signals}
	var obj := provider as Object
	for m: String in REQUIRED_PROJECTION_METHODS:
		if not obj.has_method(StringName(m)):
			missing_methods.append(m)
	if not obj.has_signal(StringName(REQUIRED_PROJECTION_SIGNAL)):
		missing_signals.append(REQUIRED_PROJECTION_SIGNAL)
	return {
		"ok": missing_methods.is_empty() and missing_signals.is_empty(),
		"missing_methods": missing_methods,
		"missing_signals": missing_signals,
	}


static func validate_presentation_provider(provider: Variant) -> Dictionary:
	var missing: Array[String] = []
	if provider == null or not (provider is Object) or not is_instance_valid(provider):
		for m: String in REQUIRED_PRESENTATION_METHODS:
			missing.append(m)
		return {"ok": false, "missing_methods": missing}
	var obj := provider as Object
	for m: String in REQUIRED_PRESENTATION_METHODS:
		if not obj.has_method(StringName(m)):
			missing.append(m)
	return {"ok": missing.is_empty(), "missing_methods": missing}


func _resolve_and_check_network_id(module_id: String) -> Dictionary:
	if _local_only:
		return {"ok": false, "reason": "local_only_network_disabled"}
	var target_id: String = _clean_str(module_id)
	if target_id.is_empty():
		target_id = _module_id
	if not is_valid_module_id(target_id):
		return {"ok": false, "reason": "invalid_module_id"}
	if not _module_id.is_empty() and target_id != _module_id:
		return {"ok": false, "reason": "module_id_mismatch"}
	return {"ok": true, "id": target_id}


func make_network_actions_spec(module_id: String = "") -> Dictionary:
	var id_res: Dictionary = _resolve_and_check_network_id(module_id)
	if not bool(id_res.get("ok", false)):
		return id_res
	return {"ok": true, "spec": {"id": str(id_res["id"])}}


func make_network_projections_spec(
	module_id: String = "",
	replica_presentation_only: bool = true,
	initial_ready_peer_local: bool = true,
	projection_ignores_entity_flags: bool = true
) -> Dictionary:
	var id_res: Dictionary = _resolve_and_check_network_id(module_id)
	if not bool(id_res.get("ok", false)):
		return id_res
	if not replica_presentation_only:
		return {"ok": false, "reason": "replica_presentation_only_required"}
	return {
		"ok": true,
		"spec": {
			"id": str(id_res["id"]),
			"replica_presentation_only": true,
			"initial_ready_peer_local": initial_ready_peer_local,
			"projection_ignores_entity_flags": projection_ignores_entity_flags,
		},
	}


func make_network_presentations_spec(module_id: String = "") -> Dictionary:
	var id_res: Dictionary = _resolve_and_check_network_id(module_id)
	if not bool(id_res.get("ok", false)):
		return id_res
	return {"ok": true, "spec": {"id": str(id_res["id"])}}


func _register_network_slot(slot_id: StringName, spec: Dictionary, provider: Object) -> Dictionary:
	var ctx: Object = _ctx()
	if ctx == null:
		return {"ok": false, "reason": "context_unavailable"}
	var spec_id: String = str(spec.get("id", ""))
	if provider.has_meta(&"module_id"):
		var owner_mod_id: String = str(provider.get_meta(&"module_id"))
		if owner_mod_id != spec_id:
			return {"ok": false, "reason": "provider_module_id_mismatch"}
	var token: Variant = ctx.call(&"register_slot_item", slot_id, spec)
	if token is Object and is_instance_valid(token):
		var tok_obj := token as Object
		if tok_obj.has_method(&"is_active") and not bool(tok_obj.call(&"is_active")):
			var reason: String = "network_slot_rejected"
			var last_rej: Variant = tok_obj.get(&"last_rejection")
			if last_rej is String and not (last_rej as String).is_empty():
				reason = last_rej as String
			else:
				var lbl: Variant = tok_obj.get(&"label")
				if lbl is String and not (lbl as String).is_empty():
					reason = lbl as String
			return {"ok": false, "reason": reason, "token": tok_obj}
		return {"ok": true, "token": tok_obj}
	return {"ok": false, "reason": "network_slot_registration_failed"}


func register_network_actions(provider: Object, module_id: String = "") -> Dictionary:
	var spec_res: Dictionary = make_network_actions_spec(module_id)
	if not bool(spec_res.get("ok", false)):
		return spec_res
	var p_check: Dictionary = validate_action_provider(provider)
	if not bool(p_check.get("ok", false)):
		return {"ok": false, "reason": "invalid_action_provider", "missing_methods": p_check["missing_methods"]}
	return _register_network_slot(SLOT_NETWORK_ACTIONS, spec_res["spec"] as Dictionary, provider)


func register_network_projections(provider: Object, module_id: String = "", options: Dictionary = {}) -> Dictionary:
	var vu: Variant = _value_utils()
	var rep_only: bool = bool(vu.coerce_bool(options.get("replica_presentation_only", true), true)) if vu != null else bool(options.get("replica_presentation_only", true))
	var init_local: bool = bool(vu.coerce_bool(options.get("initial_ready_peer_local", true), true)) if vu != null else bool(options.get("initial_ready_peer_local", true))
	var ign_flags: bool = bool(vu.coerce_bool(options.get("projection_ignores_entity_flags", true), true)) if vu != null else bool(options.get("projection_ignores_entity_flags", true))
	var spec_res: Dictionary = make_network_projections_spec(module_id, rep_only, init_local, ign_flags)
	if not bool(spec_res.get("ok", false)):
		return spec_res
	var p_check: Dictionary = validate_projection_provider(provider)
	if not bool(p_check.get("ok", false)):
		return {
			"ok": false,
			"reason": "invalid_projection_provider",
			"missing_methods": p_check["missing_methods"],
			"missing_signals": p_check["missing_signals"],
		}
	return _register_network_slot(SLOT_NETWORK_PROJECTIONS, spec_res["spec"] as Dictionary, provider)


func register_network_presentations(provider: Object, module_id: String = "") -> Dictionary:
	var spec_res: Dictionary = make_network_presentations_spec(module_id)
	if not bool(spec_res.get("ok", false)):
		return spec_res
	var p_check: Dictionary = validate_presentation_provider(provider)
	if not bool(p_check.get("ok", false)):
		return {"ok": false, "reason": "invalid_presentation_provider", "missing_methods": p_check["missing_methods"]}
	return _register_network_slot(SLOT_NETWORK_PRESENTATIONS, spec_res["spec"] as Dictionary, provider)


func estimate_bounded_bytes(value: Variant, max_bytes: int = MAX_ENTRY_BYTES, depth: int = 0) -> int:
	if max_bytes <= 0 or depth < 0 or depth > MAX_DATA_DEPTH:
		return -1
	var bc: Variant = _bounded_cloner()
	if bc != null and bool(bc.has_cycle(value, depth)):
		return -1
	var box: Array[int] = [max_bytes]
	if not _bounded_step(value, box, depth):
		return -1
	return max_bytes - box[0]


func _bounded_step(value: Variant, budget: Array[int], depth: int) -> bool:
	if depth > MAX_DATA_DEPTH:
		return false
	var dc: Variant = _dag_cloner()
	var cost: int = 16
	match typeof(value):
		TYPE_NIL:
			cost = 8
		TYPE_BOOL, TYPE_INT, TYPE_FLOAT:
			cost = 16
		TYPE_VECTOR2, TYPE_VECTOR2I:
			cost = 24
		TYPE_RECT2, TYPE_RECT2I, TYPE_VECTOR3, TYPE_VECTOR3I, TYPE_COLOR, TYPE_VECTOR4, TYPE_VECTOR4I, TYPE_PLANE, TYPE_QUATERNION:
			cost = 40
		TYPE_TRANSFORM2D, TYPE_AABB, TYPE_BASIS:
			cost = 64
		TYPE_TRANSFORM3D, TYPE_PROJECTION:
			cost = 80
		TYPE_STRING, TYPE_STRING_NAME, TYPE_NODE_PATH:
			cost = 16 + String(value).length() * 4
		TYPE_PACKED_STRING_ARRAY:
			var psa := value as PackedStringArray
			if not psa.is_empty() and depth + 1 > MAX_DATA_DEPTH:
				return false
			if dc != null:
				cost = int(dc.packed_array_byte_cost(value, budget[0]))
				if cost < 0:
					return false
			else:
				return false
		TYPE_PACKED_BYTE_ARRAY, TYPE_PACKED_INT32_ARRAY, TYPE_PACKED_FLOAT32_ARRAY, \
		TYPE_PACKED_INT64_ARRAY, TYPE_PACKED_FLOAT64_ARRAY, TYPE_PACKED_VECTOR2_ARRAY, \
		TYPE_PACKED_VECTOR3_ARRAY, TYPE_PACKED_VECTOR4_ARRAY, TYPE_PACKED_COLOR_ARRAY:
			if dc != null:
				cost = int(dc.packed_array_byte_cost(value, budget[0]))
				if cost < 0:
					return false
			else:
				return false
		TYPE_DICTIONARY:
			var d := value as Dictionary
			if d.size() > int(budget[0]) / 16:
				return false
			for k: Variant in d:
				if not _bounded_step(k, budget, depth + 1):
					return false
				if not _bounded_step(d[k], budget, depth + 1):
					return false
		TYPE_ARRAY:
			var arr := value as Array
			if arr.size() > int(budget[0]) / 16:
				return false
			for item: Variant in arr:
				if not _bounded_step(item, budget, depth + 1):
					return false
		_:
			cost = 256
	budget[0] -= cost
	return budget[0] >= 0


func _is_pure_data(value: Variant) -> bool:
	var ch: RefCounted = _get_comp_helper()
	if ch != null and ch.has_method(&"is_pure_data"):
		return bool(ch.call(&"is_pure_data", value))
	return false


func prepare_entry(module_id: String, version: Variant, state: Variant) -> Dictionary:
	var clean_id: String = _clean_str(module_id)
	if not is_valid_module_id(clean_id):
		return {"ok": false, "reason": "invalid_module_id"}

	var vu: Variant = _value_utils()
	var ver_parsed: Dictionary = vu.parse_int_val(version) if vu != null else {"ok": version is int, "value": int(version) if version is int else 0}
	if not bool(ver_parsed.get("ok", false)):
		return {"ok": false, "reason": "invalid_module_record"}
	var ver_int: int = int(ver_parsed["value"])
	if ver_int <= 0 or ver_int > 0x7fffffff:
		return {"ok": false, "reason": "invalid_module_record"}
	if not (state is Dictionary):
		return {"ok": false, "reason": "invalid_module_record"}

	var state_dict := state as Dictionary
	if estimate_bounded_bytes(state_dict, MAX_ENTRY_BYTES, 0) < 0:
		return {"ok": false, "reason": "module_entry_size_limit"}
	if not _is_pure_data(state_dict):
		return {"ok": false, "reason": "invalid_module_state"}

	var dc: Variant = _dag_cloner()
	var cloned_res: Dictionary = dc.safe_clone_validated_dict(state_dict, MAX_ENTRY_BYTES, 0, MAX_DATA_DEPTH) if dc != null else {"ok": true, "dict": state_dict.duplicate(true)}
	if not bool(cloned_res.get("ok", false)):
		return {"ok": false, "reason": "module_entry_size_limit"}

	var normalized: Dictionary = {"version": ver_int, "state": cloned_res["dict"] as Dictionary}
	var entry_bytes: int = var_to_bytes(normalized).size() + clean_id.length() * 4 + 32
	if entry_bytes > MAX_ENTRY_BYTES:
		return {"ok": false, "reason": "module_entry_size_limit"}
	return {"ok": true, "entry": normalized, "bytes": entry_bytes}


func prepare_three_phase_state(
	raw_state: Dictionary,
	expected_version: int,
	validator: Callable = Callable(),
	defaults: Dictionary = {},
	module_id: String = ""
) -> Dictionary:
	var dc: Variant = _dag_cloner()
	var vu: Variant = _value_utils()
	var effective_id: String = _clean_str(module_id)
	if effective_id.is_empty():
		effective_id = _module_id
	if not effective_id.is_empty() and not is_valid_module_id(effective_id):
		return {"ok": false, "reason": "invalid_module_id"}

	if raw_state.is_empty():
		if estimate_bounded_bytes(defaults, MAX_ENTRY_BYTES, 0) < 0:
			return {"ok": false, "reason": "module_entry_size_limit"}
		if not _is_pure_data(defaults):
			return {"ok": false, "reason": "invalid_default_module_state"}
		var def_cloned: Dictionary = dc.safe_clone_validated_dict(defaults, MAX_ENTRY_BYTES, 0, MAX_DATA_DEPTH) if dc != null else {"ok": true, "dict": defaults.duplicate(true)}
		if not bool(def_cloned.get("ok", false)):
			return {"ok": false, "reason": "module_entry_size_limit"}
		var out_default: Dictionary = def_cloned["dict"] as Dictionary
		if out_default.has("version"):
			var def_ver_res: Dictionary = vu.parse_int_val(out_default["version"]) if vu != null else {"ok": out_default["version"] is int, "value": int(out_default["version"]) if out_default["version"] is int else -1}
			if not bool(def_ver_res.get("ok", false)) or int(def_ver_res["value"]) != expected_version:
				return {"ok": false, "reason": "unsupported_module_state_version"}
		out_default["version"] = expected_version
		if estimate_bounded_bytes(out_default, MAX_ENTRY_BYTES, 0) < 0:
			return {"ok": false, "reason": "module_entry_size_limit"}
		if not _is_pure_data(out_default):
			return {"ok": false, "reason": "invalid_default_module_state"}
		if validator.is_valid():
			var dv_res: Variant = validator.call(out_default)
			if not (dv_res is Dictionary):
				return {"ok": false, "reason": "invalid_validator_response"}
			var dv_dict := dv_res as Dictionary
			if not bool(dv_dict.get("ok", false)):
				return {"ok": false, "reason": str(dv_dict.get("reason", "module_state_validation_failed"))}
			if dv_dict.has("data") and dv_dict["data"] is Dictionary:
				out_default = dv_dict["data"] as Dictionary
				if estimate_bounded_bytes(out_default, MAX_ENTRY_BYTES, 0) < 0:
					return {"ok": false, "reason": "module_entry_size_limit"}
				if not _is_pure_data(out_default):
					return {"ok": false, "reason": "invalid_default_module_state"}
		var def_check_id: String = effective_id if not effective_id.is_empty() else "module.state"
		var def_entry_check: Dictionary = prepare_entry(def_check_id, expected_version, out_default)
		if not bool(def_entry_check.get("ok", false)):
			return {"ok": false, "reason": str(def_entry_check.get("reason", "invalid_default_module_state"))}
		return {"ok": true, "data": (def_entry_check["entry"] as Dictionary)["state"]}

	var ver_res: Dictionary = vu.parse_int_val(raw_state.get("version", -1)) if vu != null else {"ok": raw_state.get("version", -1) is int, "value": int(raw_state.get("version", -1))}
	if not bool(ver_res.get("ok", false)) or int(ver_res["value"]) != expected_version:
		return {"ok": false, "reason": "unsupported_module_state_version"}

	if estimate_bounded_bytes(raw_state, MAX_ENTRY_BYTES, 0) < 0:
		return {"ok": false, "reason": "module_entry_size_limit"}
	if not _is_pure_data(raw_state):
		return {"ok": false, "reason": "invalid_module_state"}

	var cloned_res: Dictionary = dc.safe_clone_validated_dict(raw_state, MAX_ENTRY_BYTES, 0, MAX_DATA_DEPTH) if dc != null else {"ok": true, "dict": raw_state.duplicate(true)}
	if not bool(cloned_res.get("ok", false)):
		return {"ok": false, "reason": "module_entry_size_limit"}
	var clean_state: Dictionary = cloned_res["dict"] as Dictionary
	clean_state["version"] = expected_version
	if estimate_bounded_bytes(clean_state, MAX_ENTRY_BYTES, 0) < 0:
		return {"ok": false, "reason": "module_entry_size_limit"}
	if not _is_pure_data(clean_state):
		return {"ok": false, "reason": "invalid_module_state"}

	if validator.is_valid():
		var v_res: Variant = validator.call(clean_state)
		if not (v_res is Dictionary):
			return {"ok": false, "reason": "invalid_validator_response"}
		var v_dict := v_res as Dictionary
		if not bool(v_dict.get("ok", false)):
			return {"ok": false, "reason": str(v_dict.get("reason", "module_state_validation_failed"))}
		if v_dict.has("data") and v_dict["data"] is Dictionary:
			clean_state = v_dict["data"] as Dictionary
			if estimate_bounded_bytes(clean_state, MAX_ENTRY_BYTES, 0) < 0:
				return {"ok": false, "reason": "module_entry_size_limit"}
			if not _is_pure_data(clean_state):
				return {"ok": false, "reason": "invalid_module_state"}

	var check_id: String = effective_id if not effective_id.is_empty() else "module.state"
	var entry_check: Dictionary = prepare_entry(check_id, expected_version, clean_state)
	if not bool(entry_check.get("ok", false)):
		return {"ok": false, "reason": str(entry_check.get("reason", "module_entry_size_limit"))}

	return {"ok": true, "data": (entry_check["entry"] as Dictionary)["state"]}


func clone_state_isolated(state: Dictionary) -> Dictionary:
	var dc: Variant = _dag_cloner()
	if dc != null:
		return dc.safe_clone_dict(state, MAX_ENTRY_BYTES, MAX_DATA_DEPTH) as Dictionary
	return {}


static func notify_module_content_changed(world: Object, module_node: Object) -> bool:
	if world == null or not is_instance_valid(world) or module_node == null or not is_instance_valid(module_node):
		return false
	if world.has_method(&"notify_module_content_changed"):
		return bool(world.call(&"notify_module_content_changed", module_node))
	return false


static func publish_module_state(world: Object) -> bool:
	if world == null or not is_instance_valid(world):
		return false
	if world.has_method(&"publish_module_state") and world.has_method(&"module_state_revision"):
		var rev: Variant = world.call(&"module_state_revision")
		return bool(world.call(&"publish_module_state", rev))
	return false
