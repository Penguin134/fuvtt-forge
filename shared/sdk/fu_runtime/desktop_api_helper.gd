extends RefCounted
## Fu vtt DesktopApiService Safe Runtime Wrapper
##
## Wraps `context.consume_service("desktop_api")` with WeakRef lifecycle safety,
## null/unmounted degradation, vitals masking normalization, and isolated dict cloning.

const DEFAULT_CELL_SIZE: float = 64.0
const FU_SDK_UTILS_REL: String = "../fu_sdk/utils/"
const DEV_FALLBACK_UTILS_DIR: String = "shared/sdk/fu_sdk/utils/"

var _ctx_ref: WeakRef = null
var _api_ref: WeakRef = null
var _log_ref: WeakRef = null
var _runtime_ref: WeakRef = null
var _util_scripts: Dictionary = {}


func _init(context_or_api: Variant = null, log_bus: RefCounted = null, runtime: RefCounted = null) -> void:
	if log_bus != null and is_instance_valid(log_bus):
		_log_ref = weakref(log_bus)
	if runtime != null and is_instance_valid(runtime):
		_runtime_ref = weakref(runtime)
	if context_or_api != null:
		bind(context_or_api)


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


func _value_utils() -> Variant:
	return _load_util_script("value_utils.gd")


func _validation_utils() -> Variant:
	return _load_util_script("validation_utils.gd")


func _dag_cloner() -> Variant:
	return _load_util_script("dag_cloner.gd")


func _log_warn(message: String, context: Dictionary = {}) -> void:
	if _log_ref == null:
		return
	var bus: Variant = _log_ref.get_ref()
	if bus != null and is_instance_valid(bus) and bus.has_method(&"warn"):
		bus.call(&"warn", "fu_runtime.desktop_api", message, context)


func _ctx() -> Object:
	if _ctx_ref == null:
		return null
	var obj: Variant = _ctx_ref.get_ref()
	if obj == null or not is_instance_valid(obj):
		return null
	return obj as Object


func _context_allows_service(ctx: Object) -> bool:
	if ctx == null or not is_instance_valid(ctx):
		return false
	if ctx.has_method(&"is_active") and not bool(ctx.call(&"is_active")):
		if ctx.has_method(&"can_initialize"):
			return bool(ctx.call(&"can_initialize"))
		return false
	if ctx.has_method(&"can_initialize"):
		return bool(ctx.call(&"can_initialize"))
	return true


func bind(context_or_api: Variant) -> bool:
	unbind()
	if context_or_api == null or not (context_or_api is Object) or not is_instance_valid(context_or_api):
		return false
	var obj := context_or_api as Object
	if obj.has_method(&"consume_service"):
		_ctx_ref = weakref(obj)
		if _context_allows_service(obj):
			var svc: Variant = obj.call(&"consume_service", "desktop_api")
			if svc is Object and is_instance_valid(svc):
				_api_ref = weakref(svc)
				return true
		return false
	if obj.has_method(&"is_gm") or obj.has_method(&"get_desktop"):
		_api_ref = weakref(obj)
		return true
	_log_warn("Rejected invalid desktop_api bind target")
	return false


func unbind() -> void:
	_ctx_ref = null
	_api_ref = null


func get_api() -> Object:
	var ctx: Object = _ctx()
	if ctx != null:
		if not _context_allows_service(ctx):
			return null
		if _api_ref != null:
			var cached: Variant = _api_ref.get_ref()
			if cached != null and is_instance_valid(cached):
				return cached as Object
		var svc: Variant = ctx.call(&"consume_service", "desktop_api")
		if svc is Object and is_instance_valid(svc):
			_api_ref = weakref(svc)
			return svc as Object
		return null
	if _api_ref != null:
		var raw: Variant = _api_ref.get_ref()
		if raw != null and is_instance_valid(raw):
			return raw as Object
	return null


func is_available() -> bool:
	return get_api() != null


func get_desktop() -> Node:
	var api: Object = get_api()
	if api == null or not api.has_method(&"get_desktop"):
		return null
	var d: Variant = api.call(&"get_desktop")
	if d is Node and is_instance_valid(d):
		return d as Node
	return null


func is_gm() -> bool:
	var api: Object = get_api()
	if api == null or not api.has_method(&"is_gm"):
		return false
	var vu: Variant = _value_utils()
	var res: Variant = api.call(&"is_gm")
	return bool(vu.coerce_bool(res, false)) if vu != null else bool(res)


func network_role() -> String:
	var api: Object = get_api()
	if api == null or not api.has_method(&"network_role"):
		return "solo"
	var vu: Variant = _value_utils()
	var raw: Variant = api.call(&"network_role")
	var role: String = str(vu.as_str(raw, "solo")) if vu != null else str(raw)
	return role if not role.is_empty() else "solo"


func local_peer_id() -> int:
	var api: Object = get_api()
	if api == null or not api.has_method(&"local_peer_id"):
		return 1
	var vu: Variant = _value_utils()
	var raw: Variant = api.call(&"local_peer_id")
	return int(vu.coerce_int(raw, 1)) if vu != null else int(raw)


func local_player_id() -> String:
	var api: Object = get_api()
	if api == null or not api.has_method(&"local_player_id"):
		return ""
	var vu: Variant = _value_utils()
	var raw: Variant = api.call(&"local_player_id")
	return str(vu.as_str(raw, "")) if vu != null else str(raw)


func joined_players() -> Array[Dictionary]:
	var out: Array[Dictionary] = []
	var api: Object = get_api()
	if api == null or not api.has_method(&"joined_players"):
		return out
	var raw: Variant = api.call(&"joined_players")
	if not (raw is Array):
		return out
	var dc: Variant = _dag_cloner()
	for item: Variant in raw as Array:
		if item is Dictionary:
			var cloned: Dictionary = dc.safe_clone_dict(item as Dictionary) if dc != null else (item as Dictionary).duplicate(true)
			out.append(cloned)
	return out


func can_command_entity(entity_or_id: Variant, peer: int = 0) -> bool:
	var api: Object = get_api()
	if api == null or not api.has_method(&"can_command_entity"):
		return false
	if entity_or_id == null:
		return false
	if entity_or_id is Object and not is_instance_valid(entity_or_id):
		return false
	return bool(api.call(&"can_command_entity", entity_or_id, peer))


func active_scene_uid() -> String:
	var api: Object = get_api()
	if api == null or not api.has_method(&"active_scene_uid"):
		return ""
	var vu: Variant = _value_utils()
	var raw: Variant = api.call(&"active_scene_uid")
	return str(vu.as_str(raw, "")) if vu != null else str(raw)


func active_scene_name() -> String:
	var api: Object = get_api()
	if api == null or not api.has_method(&"active_scene_name"):
		return ""
	var vu: Variant = _value_utils()
	var raw: Variant = api.call(&"active_scene_name")
	return str(vu.as_str(raw, "")) if vu != null else str(raw)


func active_floor_uid() -> String:
	var api: Object = get_api()
	if api == null or not api.has_method(&"active_floor_uid"):
		return ""
	var vu: Variant = _value_utils()
	var raw: Variant = api.call(&"active_floor_uid")
	return str(vu.as_str(raw, "")) if vu != null else str(raw)


func active_floor_id() -> int:
	var api: Object = get_api()
	if api == null or not api.has_method(&"active_floor_id"):
		return -1
	var vu: Variant = _value_utils()
	var raw: Variant = api.call(&"active_floor_id")
	return int(vu.coerce_int(raw, -1)) if vu != null else int(raw)


func world_units_per_cell() -> float:
	var api: Object = get_api()
	if api == null or not api.has_method(&"world_units_per_cell"):
		return DEFAULT_CELL_SIZE
	var vu: Variant = _value_utils()
	var raw: Variant = api.call(&"world_units_per_cell")
	var cs: float = float(vu.coerce_float(raw, DEFAULT_CELL_SIZE)) if vu != null else float(raw)
	if is_finite(cs) and cs >= 8.0:
		return cs
	return DEFAULT_CELL_SIZE


func screen_to_world(screen_pos: Vector2) -> Vector2:
	var api: Object = get_api()
	if api == null or not api.has_method(&"screen_to_world"):
		return screen_pos
	var res: Variant = api.call(&"screen_to_world", screen_pos)
	return res as Vector2 if res is Vector2 else screen_pos


func world_to_screen(world_pos: Vector2) -> Vector2:
	var api: Object = get_api()
	if api == null or not api.has_method(&"world_to_screen"):
		return world_pos
	var res: Variant = api.call(&"world_to_screen", world_pos)
	return res as Vector2 if res is Vector2 else world_pos


func camera_position() -> Vector2:
	var api: Object = get_api()
	if api == null or not api.has_method(&"camera_position"):
		return Vector2.ZERO
	var res: Variant = api.call(&"camera_position")
	return res as Vector2 if res is Vector2 else Vector2.ZERO


func camera_zoom() -> Vector2:
	var api: Object = get_api()
	if api == null or not api.has_method(&"camera_zoom"):
		return Vector2.ONE
	var res: Variant = api.call(&"camera_zoom")
	return res as Vector2 if res is Vector2 else Vector2.ONE


func focus_camera(world_pos: Vector2) -> bool:
	if not world_pos.is_finite():
		_log_warn("Rejected non-finite camera focus position")
		return false
	var api: Object = get_api()
	if api == null or not api.has_method(&"focus_camera"):
		return false
	return bool(api.call(&"focus_camera", world_pos))


func focus_entity(entity_id: String) -> bool:
	var val_u: Variant = _validation_utils()
	var clean_id: String = str(val_u.strip_bom_and_edges(entity_id)) if val_u != null else entity_id.strip_edges()
	if clean_id.is_empty():
		return false
	var api: Object = get_api()
	if api == null or not api.has_method(&"focus_entity"):
		return false
	return bool(api.call(&"focus_entity", clean_id))


func current_mode() -> String:
	var api: Object = get_api()
	if api == null or not api.has_method(&"current_mode"):
		return ""
	var vu: Variant = _value_utils()
	var raw: Variant = api.call(&"current_mode")
	return str(vu.as_str(raw, "")) if vu != null else str(raw)


func set_mode(mode_id: String) -> bool:
	var val_u: Variant = _validation_utils()
	var clean_id: String = str(val_u.strip_bom_and_edges(mode_id)) if val_u != null else mode_id.strip_edges()
	if clean_id.is_empty():
		return false
	var api: Object = get_api()
	if api == null or not api.has_method(&"set_mode"):
		return false
	return bool(api.call(&"set_mode", clean_id))


func find_entity(entity_id: String) -> Object:
	var val_u: Variant = _validation_utils()
	var clean_id: String = str(val_u.strip_bom_and_edges(entity_id)) if val_u != null else entity_id.strip_edges()
	if clean_id.is_empty():
		return null
	var api: Object = get_api()
	if api == null or not api.has_method(&"find_entity"):
		return null
	var tok: Variant = api.call(&"find_entity", clean_id)
	if tok is Object and is_instance_valid(tok):
		return tok as Object
	return null


func get_entities(active_floor_only: bool = true) -> Array:
	var out: Array = []
	var api: Object = get_api()
	if api == null or not api.has_method(&"get_entities"):
		return out
	var raw: Variant = api.call(&"get_entities", active_floor_only)
	if not (raw is Array):
		return out
	for item: Variant in raw as Array:
		if item is Object and is_instance_valid(item):
			out.append(item)
	return out


func selected_entities() -> Array:
	var out: Array = []
	var api: Object = get_api()
	if api == null or not api.has_method(&"selected_entities"):
		return out
	var raw: Variant = api.call(&"selected_entities")
	if not (raw is Array):
		return out
	for item: Variant in raw as Array:
		if item is Object and is_instance_valid(item):
			out.append(item)
	return out


func read_entity_vitals(entity_or_id: Variant) -> Dictionary:
	var api: Object = get_api()
	if api == null or not api.has_method(&"read_entity_vitals"):
		return {"ok": false, "reason": "desktop_api_unavailable"}
	if entity_or_id == null:
		return {"ok": false, "reason": "entity_unavailable"}
	if entity_or_id is Object and not is_instance_valid(entity_or_id):
		return {"ok": false, "reason": "entity_unavailable"}
	var raw: Variant = api.call(&"read_entity_vitals", entity_or_id)
	if not (raw is Dictionary):
		return {"ok": false, "reason": "invalid_vitals_response"}
	var dc: Variant = _dag_cloner()
	var out: Dictionary = dc.safe_clone_dict(raw as Dictionary) if dc != null else (raw as Dictionary).duplicate(true)
	if bool(out.get("ok", false)) and not out.has("masked"):
		out["masked"] = false
	return out


static func is_vitals_masked(vitals: Dictionary) -> bool:
	return bool(vitals.get("masked", false))


func request_roll(expression: String, label: String = "") -> Dictionary:
	var val_u: Variant = _validation_utils()
	var clean_expr: String = str(val_u.strip_bom_and_edges(expression)) if val_u != null else expression.strip_edges()
	if clean_expr.is_empty():
		return {"ok": false, "reason": "empty_expression"}
	var clean_label: String = str(val_u.strip_bom_and_edges(label)) if val_u != null else label.strip_edges()
	var api: Object = get_api()
	if api == null or not api.has_method(&"request_roll"):
		return {"ok": false, "reason": "desktop_api_unavailable"}
	var raw: Variant = api.call(&"request_roll", clean_expr, clean_label)
	if not (raw is Dictionary):
		return {"ok": false, "reason": "invalid_roll_response"}
	var dc: Variant = _dag_cloner()
	return dc.safe_clone_dict(raw as Dictionary) if dc != null else (raw as Dictionary).duplicate(true)


func read_saved_module_entry(module_id: String) -> Dictionary:
	var val_u: Variant = _validation_utils()
	var clean_id: String = str(val_u.strip_bom_and_edges(module_id)) if val_u != null else module_id.strip_edges()
	if clean_id.is_empty():
		return {}
	var api: Object = get_api()
	if api == null or not api.has_method(&"read_saved_module_entry"):
		return {}
	if not is_gm():
		return {}
	var raw: Variant = api.call(&"read_saved_module_entry", clean_id)
	if not (raw is Dictionary):
		return {}
	var dc: Variant = _dag_cloner()
	return dc.safe_clone_dict(raw as Dictionary) if dc != null else (raw as Dictionary).duplicate(true)
