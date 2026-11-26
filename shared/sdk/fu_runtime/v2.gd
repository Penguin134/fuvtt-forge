extends RefCounted
## Fu vtt In-World Runtime SDK Facade (v2)
##
## Unified entry point for both `fus.desktop-module.v1` (`local_only` pure-ZIP modules)
## and `fus.plugin.v2` (`.fup` + `content.pck` networked world plugins).
##
## Resolves sibling helpers and shared `../fu_sdk/` modules dynamically from the
## script's own directory so identical relative `load()` paths work in both the
## monorepo (`shared/sdk/fu_runtime/`) and bundled modules (`<namespace_root>/lib/fu_runtime/`).

const SDK_VERSION: String = "2.0.0"
const RUNTIME_SCHEMA_DESKTOP: String = "fus.desktop-module.v1"
const RUNTIME_SCHEMA_WORLD: String = "fus.plugin.v2"

const DESKTOP_API_HELPER_REL: String = "desktop_api_helper.gd"
const HOOK_HELPER_REL: String = "hook_helper.gd"
const SLOT_HELPER_REL: String = "slot_helper.gd"
const COMP_HELPER_REL: String = "comp_helper.gd"
const NETWORK_HELPER_REL: String = "network_helper.gd"

const LOG_BUS_REL_PATH: String = "../fu_sdk/logging/log_bus.gd"
const MODULE_REGISTRY_REL_PATH: String = "../fu_sdk/plugins/module_registry.gd"
const DAG_CLONER_REL_PATH: String = "../fu_sdk/utils/dag_cloner.gd"
const BOUNDED_CLONER_REL_PATH: String = "../fu_sdk/utils/bounded_cloner.gd"
const VALUE_UTILS_REL_PATH: String = "../fu_sdk/utils/value_utils.gd"
const VALIDATION_UTILS_REL_PATH: String = "../fu_sdk/utils/validation_utils.gd"

const DEV_FALLBACK_RUNTIME_DIR: String = "shared/sdk/fu_runtime/"
const DEV_FALLBACK_FU_SDK_DIR: String = "shared/sdk/fu_sdk/"

var _sub_script_cache: Dictionary = {}
var _logger: RefCounted = null
var _module_registry: RefCounted = null


func _load_relative_script(rel_path: String) -> Script:
	var clean_rel: String = rel_path.strip_edges()
	if clean_rel.is_empty():
		return null
	if _sub_script_cache.has(clean_rel):
		return _sub_script_cache[clean_rel] as Script

	var self_scr := get_script() as Script
	if self_scr != null and not self_scr.resource_path.is_empty():
		var base_dir: String = self_scr.resource_path.split("::")[0].get_base_dir()
		var candidate: String = base_dir.path_join(clean_rel).simplify_path()
		if ResourceLoader.exists(candidate) or FileAccess.file_exists(candidate):
			var loaded := load(candidate) as Script
			if loaded != null:
				_sub_script_cache[clean_rel] = loaded
				return loaded

	for raw_frame: Variant in get_stack():
		if raw_frame is Dictionary:
			var src_file: String = str((raw_frame as Dictionary).get("source", ""))
			if not src_file.is_empty():
				var stack_cand: String = src_file.get_base_dir().path_join(clean_rel).simplify_path()
				if ResourceLoader.exists(stack_cand) or FileAccess.file_exists(stack_cand):
					var loaded_stack := load(stack_cand) as Script
					if loaded_stack != null:
						_sub_script_cache[clean_rel] = loaded_stack
						return loaded_stack

	var fb_candidates: Array[String] = []
	if clean_rel.begins_with("../fu_sdk/"):
		var sdk_sub: String = clean_rel.trim_prefix("../fu_sdk/")
		fb_candidates.append(("res://" + DEV_FALLBACK_FU_SDK_DIR).path_join(sdk_sub))
		fb_candidates.append(DEV_FALLBACK_FU_SDK_DIR.path_join(sdk_sub))
	else:
		fb_candidates.append(("res://" + DEV_FALLBACK_RUNTIME_DIR).path_join(clean_rel))
		fb_candidates.append(DEV_FALLBACK_RUNTIME_DIR.path_join(clean_rel))

	for fb_path: String in fb_candidates:
		if ResourceLoader.exists(fb_path) or FileAccess.file_exists(fb_path):
			var loaded_fb := load(fb_path) as Script
			if loaded_fb != null:
				_sub_script_cache[clean_rel] = loaded_fb
				return loaded_fb

	return null


func get_util_script(util_name: String) -> Script:
	match util_name.strip_edges().to_lower():
		"dag_cloner":
			return _load_relative_script(DAG_CLONER_REL_PATH)
		"bounded_cloner":
			return _load_relative_script(BOUNDED_CLONER_REL_PATH)
		"value_utils":
			return _load_relative_script(VALUE_UTILS_REL_PATH)
		"validation_utils":
			return _load_relative_script(VALIDATION_UTILS_REL_PATH)
		_:
			return null


func create_logger(options: Dictionary = {}) -> RefCounted:
	var scr: Script = _load_relative_script(LOG_BUS_REL_PATH)
	if scr == null:
		return null
	var logger: RefCounted = scr.new()
	if not options.is_empty():
		var max_entries: int = coerce_int(options.get("max_entries", logger.DEFAULT_MAX_ENTRIES), logger.DEFAULT_MAX_ENTRIES)
		var min_level: int = coerce_int(options.get("min_level", logger.LEVEL_DEBUG), logger.LEVEL_DEBUG)
		var emit_to_engine: bool = coerce_bool(options.get("emit_to_engine", true), true)
		logger.configure(max_entries, min_level, emit_to_engine)
		var host_var: Variant = options.get("host", null)
		if host_var is RefCounted:
			logger.attach_import_host(host_var as RefCounted, coerce_bool(options.get("forward_reports", false), false))
	return logger


func get_logger() -> RefCounted:
	if _logger == null:
		_logger = create_logger()
	return _logger


func set_logger(logger: RefCounted) -> void:
	_logger = logger
	if _module_registry != null and _module_registry.has_method(&"set_logger"):
		_module_registry.set_logger(logger)


func create_module_registry(log_bus: RefCounted = null) -> RefCounted:
	var scr: Script = _load_relative_script(MODULE_REGISTRY_REL_PATH)
	if scr == null:
		return null
	var resolved_bus: RefCounted = log_bus if log_bus != null else _logger
	return scr.new(resolved_bus, null)


func get_module_registry() -> RefCounted:
	if _module_registry == null:
		_module_registry = create_module_registry(get_logger())
	return _module_registry


func create_desktop_api_helper(context_or_api: Variant = null, log_bus: RefCounted = null) -> RefCounted:
	var scr: Script = _load_relative_script(DESKTOP_API_HELPER_REL)
	if scr == null:
		return null
	var bus: RefCounted = log_bus if log_bus != null else _logger
	return scr.new(context_or_api, bus, self)


func create_hook_helper(context: Variant = null, log_bus: RefCounted = null) -> RefCounted:
	var scr: Script = _load_relative_script(HOOK_HELPER_REL)
	if scr == null:
		return null
	var bus: RefCounted = log_bus if log_bus != null else _logger
	return scr.new(context, bus, self)


func create_slot_helper(context: Variant = null, log_bus: RefCounted = null) -> RefCounted:
	var scr: Script = _load_relative_script(SLOT_HELPER_REL)
	if scr == null:
		return null
	var bus: RefCounted = log_bus if log_bus != null else _logger
	return scr.new(context, bus, self)


func create_comp_helper(context: Variant = null, log_bus: RefCounted = null) -> RefCounted:
	var scr: Script = _load_relative_script(COMP_HELPER_REL)
	if scr == null:
		return null
	var bus: RefCounted = log_bus if log_bus != null else _logger
	return scr.new(context, bus, self)


func create_network_helper(
	module_id: String = "",
	local_only: bool = false,
	context: Variant = null,
	log_bus: RefCounted = null
) -> RefCounted:
	var scr: Script = _load_relative_script(NETWORK_HELPER_REL)
	if scr == null:
		return null
	var bus: RefCounted = log_bus if log_bus != null else _logger
	return scr.new(module_id, local_only, context, bus, self)


# --- Pass-throughs to shared fu_sdk/utils/* ---

func coerce_bool(value: Variant, fallback: bool = false, strip_bom: bool = true) -> bool:
	var vu: Variant = get_util_script("value_utils")
	if vu != null:
		return bool(vu.coerce_bool(value, fallback, strip_bom))
	if typeof(value) == TYPE_BOOL:
		return value == true
	return fallback


func coerce_int(value: Variant, fallback: int = 0, strict_int64: bool = true) -> int:
	var vu: Variant = get_util_script("value_utils")
	if vu != null:
		return int(vu.coerce_int(value, fallback, strict_int64))
	if typeof(value) == TYPE_INT:
		return int(value)
	return fallback


func coerce_float(value: Variant, fallback: float = 0.0, require_finite: bool = true) -> float:
	var vu: Variant = get_util_script("value_utils")
	if vu != null:
		return float(vu.coerce_float(value, fallback, require_finite))
	if typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT:
		var f: float = float(value)
		return f if (not require_finite or is_finite(f)) else fallback
	return fallback


func coerce_string(value: Variant, fallback: String = "") -> String:
	var vu: Variant = get_util_script("value_utils")
	if vu != null:
		return str(vu.coerce_string(value, fallback))
	if typeof(value) == TYPE_STRING:
		return value as String
	return fallback


func as_str(value: Variant, fallback: String = "") -> String:
	var vu: Variant = get_util_script("value_utils")
	if vu != null:
		return str(vu.as_str(value, fallback))
	if value is String:
		return value as String
	if value is StringName:
		return String(value)
	return fallback


func coerce_color_value(raw: Variant, fallback: Color = Color.BLACK) -> Dictionary:
	var vu: Variant = get_util_script("value_utils")
	if vu != null:
		return vu.coerce_color_value(raw, fallback) as Dictionary
	return {"ok": false, "color": fallback}


func is_valid_uid(uid: String) -> bool:
	var val_u: Variant = get_util_script("validation_utils")
	if val_u != null:
		return bool(val_u.is_valid_uid(uid))
	return false


func is_valid_hex64(val: String, allow_uppercase: bool = false) -> bool:
	var val_u: Variant = get_util_script("validation_utils")
	if val_u != null:
		return bool(val_u.is_valid_hex64(val, allow_uppercase))
	return false


func component_id_from_script(script_path: String) -> String:
	var val_u: Variant = get_util_script("validation_utils")
	if val_u != null:
		return str(val_u.component_id_from_script(script_path))
	return ""


func sanitize_line_text(text: String) -> String:
	var val_u: Variant = get_util_script("validation_utils")
	if val_u != null:
		return str(val_u.sanitize_line_text(text))
	return text.replace("\r", "")


func safe_clone_dict(raw: Dictionary, max_bytes: int = 16 * 1024 * 1024, max_depth: int = 32) -> Dictionary:
	var dc: Variant = get_util_script("dag_cloner")
	if dc != null:
		return dc.safe_clone_dict(raw, max_bytes, max_depth) as Dictionary
	return {}


func has_cycle(value: Variant, depth: int = 0) -> bool:
	var bc: Variant = get_util_script("bounded_cloner")
	if bc != null:
		return bool(bc.has_cycle(value, depth))
	return false
