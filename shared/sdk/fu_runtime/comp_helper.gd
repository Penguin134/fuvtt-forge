extends RefCounted
## Fu vtt CompBase, Disclosure, StateValue & EditModeController Runtime Helper
##
## Covers `fus.plugin.v2` component naming (`comp_<id>.gd`), 15-field
## `register_component` validation, `StateValue.is_data()` pure-data checking,
## `public_state` peer disclosure helpers, dominance/suppression/exclusion checks,
## and `EntityComponentPage` / `EditModeController` undo payload builders.

const ALLOWED_NETWORK_SCOPES: Array[String] = ["private", "shared", "peer"]
const REQUIRED_COMPONENTS: Array[String] = ["visual", "permission"]
const MAX_DATA_DEPTH: int = 32

const FU_SDK_UTILS_REL: String = "../fu_sdk/utils/"
const DEV_FALLBACK_UTILS_DIR: String = "shared/sdk/fu_sdk/utils/"

var _ctx_ref: WeakRef = null
var _log_ref: WeakRef = null
var _runtime_ref: WeakRef = null
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


func _value_utils() -> Variant:
	return _load_util_script("value_utils.gd")


func _validation_utils() -> Variant:
	return _load_util_script("validation_utils.gd")


func _bounded_cloner() -> Variant:
	return _load_util_script("bounded_cloner.gd")


func _dag_cloner() -> Variant:
	return _load_util_script("dag_cloner.gd")


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
		bus.call(&"warn", "fu_runtime.comp", message, context)


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
	if not obj.has_method(&"register_component"):
		_log_warn("Rejected invalid ExtensionContext for comp_helper")
		return false
	_ctx_ref = weakref(obj)
	return true


func unbind() -> void:
	_ctx_ref = null


func component_id_from_script(script_path: String) -> String:
	var val_u: Variant = _validation_utils()
	if val_u != null:
		return str(val_u.component_id_from_script(script_path))
	var base: String = script_path.get_file().get_basename()
	return base.substr(5) if base.begins_with("comp_") else base


static func _is_lower_ident(seg: String) -> bool:
	if seg.is_empty():
		return false
	for idx: int in range(seg.length()):
		var code: int = seg.unicode_at(idx)
		var ok: bool = (code >= 97 and code <= 122) or (code >= 48 and code <= 57) or code == 95
		if not ok:
			return false
	return true


func make_namespaced_comp_id(plugin_id: String, comp_name: String) -> String:
	var clean_plugin: String = _clean_str(plugin_id).to_lower()
	var clean_name: String = _clean_str(comp_name).to_lower()
	if not _is_lower_ident(clean_plugin) or not _is_lower_ident(clean_name):
		return ""
	return clean_plugin + "__" + clean_name


func is_valid_component_script_path(path: String, expected_id: String = "") -> bool:
	var clean_path: String = _clean_str(path)
	if not clean_path.begins_with("res://") or not clean_path.ends_with(".gd"):
		return false
	if "\\" in clean_path:
		return false
	var val_u: Variant = _validation_utils()
	if val_u != null and bool(val_u.has_control_chars(clean_path)):
		return false
	var rel: String = clean_path.substr(6)
	var segments: PackedStringArray = rel.split("/", true)
	if segments.is_empty():
		return false
	for seg: String in segments:
		if seg.is_empty() or seg == "." or seg == ".." or seg.ends_with(".") or seg.ends_with(" "):
			return false
	var fname: String = clean_path.get_file()
	if not fname.begins_with("comp_"):
		return false
	var extracted: String = component_id_from_script(clean_path)
	if extracted.is_empty() or extracted in REQUIRED_COMPONENTS:
		return false
	if not expected_id.is_empty() and extracted != expected_id:
		return false
	return true


func make_component_spec(
	id: String,
	path: String,
	scene: Variant,
	options: Dictionary = {}
) -> Dictionary:
	var vu: Variant = _value_utils()
	var clean_id: String = _clean_str(id)
	var clean_path: String = _clean_str(path)
	if clean_id.is_empty():
		return {"ok": false, "reason": "empty_component_id"}
	if clean_id in REQUIRED_COMPONENTS:
		return {"ok": false, "reason": "required_component_id_forbidden"}
	if not is_valid_component_script_path(clean_path, clean_id):
		return {"ok": false, "reason": "component_path_id_mismatch"}
	if not (scene is PackedScene) or not (scene as PackedScene).can_instantiate():
		return {"ok": false, "reason": "component_scene_invalid"}

	var version: int = int(vu.coerce_int(options.get("version", 1), 1)) if vu != null else int(options.get("version", 1))
	if version < 1:
		return {"ok": false, "reason": "invalid_component_version"}

	var network_scope: String = _clean_str(options.get("network_scope", "private"))
	if network_scope.is_empty():
		network_scope = "private"
	if not (network_scope in ALLOWED_NETWORK_SCOPES):
		return {"ok": false, "reason": "invalid_network_scope"}

	var initial_ready_peer_local: bool = bool(vu.coerce_bool(options.get("initial_ready_peer_local", false), false)) if vu != null else bool(options.get("initial_ready_peer_local", false))
	var projection_ignores_entity_flags: bool = bool(vu.coerce_bool(options.get("projection_ignores_entity_flags", false), false)) if vu != null else bool(options.get("projection_ignores_entity_flags", false))
	var entity_local_membership: bool = bool(vu.coerce_bool(options.get("entity_local_membership", false), false)) if vu != null else bool(options.get("entity_local_membership", false))
	var entity_local_content: bool = bool(vu.coerce_bool(options.get("entity_local_content", false), false)) if vu != null else bool(options.get("entity_local_content", false))
	var recipient_component_rows: bool = bool(vu.coerce_bool(options.get("recipient_component_rows", false), false)) if vu != null else bool(options.get("recipient_component_rows", false))
	var library_visible: bool = bool(vu.coerce_bool(options.get("library_visible", true), true)) if vu != null else bool(options.get("library_visible", true))

	if entity_local_content and network_scope != "peer":
		return {"ok": false, "reason": "entity_local_content_requires_peer_scope"}
	if recipient_component_rows and not entity_local_content:
		return {"ok": false, "reason": "recipient_component_rows_requires_entity_local_content"}

	var label: String = _clean_str(options.get("label", clean_id))
	if label.is_empty():
		label = clean_id
	var description: String = _clean_str(options.get("description", ""))

	var prepare_world: Callable = Callable()
	if options.has("prepare_world") and options["prepare_world"] != null:
		if not (options["prepare_world"] is Callable):
			return {"ok": false, "reason": "invalid_prepare_world_callable"}
		prepare_world = options["prepare_world"] as Callable
		if prepare_world != Callable() and not prepare_world.is_valid():
			return {"ok": false, "reason": "invalid_prepare_world_callable"}

	var accepts_world_delta: Callable = Callable()
	if options.has("accepts_world_delta") and options["accepts_world_delta"] != null:
		if not (options["accepts_world_delta"] is Callable):
			return {"ok": false, "reason": "invalid_accepts_world_delta_callable"}
		accepts_world_delta = options["accepts_world_delta"] as Callable
		if accepts_world_delta != Callable() and not accepts_world_delta.is_valid():
			return {"ok": false, "reason": "invalid_accepts_world_delta_callable"}

	var spec: Dictionary = {
		"id": clean_id,
		"path": clean_path,
		"scene": scene,
		"version": version,
		"label": label,
		"description": description,
		"network_scope": network_scope,
		"initial_ready_peer_local": initial_ready_peer_local,
		"projection_ignores_entity_flags": projection_ignores_entity_flags,
		"entity_local_membership": entity_local_membership,
		"entity_local_content": entity_local_content,
		"recipient_component_rows": recipient_component_rows,
		"library_visible": library_visible,
		"prepare_world": prepare_world,
		"accepts_world_delta": accepts_world_delta,
	}
	return {"ok": true, "spec": spec}


func register_component(id: String, path: String, scene: Variant, options: Dictionary = {}) -> Dictionary:
	var built: Dictionary = make_component_spec(id, path, scene, options)
	if not bool(built.get("ok", false)):
		return built
	var ctx: Object = _ctx()
	if ctx == null:
		return {"ok": false, "reason": "context_unavailable"}
	var token: Variant = ctx.call(&"register_component", built["spec"] as Dictionary)
	if token is Object and is_instance_valid(token):
		var tok_obj := token as Object
		if tok_obj.has_method(&"is_active") and not bool(tok_obj.call(&"is_active")):
			var reason: String = "component_registration_rejected"
			var last_rej: Variant = tok_obj.get(&"last_rejection")
			if last_rej is String and not (last_rej as String).is_empty():
				reason = last_rej as String
			else:
				var lbl: Variant = tok_obj.get(&"label")
				if lbl is String and not (lbl as String).is_empty():
					reason = lbl as String
			return {"ok": false, "reason": reason, "token": tok_obj}
		return {"ok": true, "token": tok_obj}
	return {"ok": false, "reason": "component_registration_failed"}


func is_pure_data(value: Variant, depth: int = 0) -> bool:
	if depth < 0 or depth > MAX_DATA_DEPTH:
		return false
	var bc: Variant = _bounded_cloner()
	if bc != null and bool(bc.has_cycle(value, depth)):
		return false
	var dict_memo: Dictionary = {}
	var arr_memo: Dictionary = {}
	return _pure_data_height(value, depth, dict_memo, arr_memo, bc) >= 0


func _pure_data_height(
	value: Variant,
	depth: int,
	dict_memo: Dictionary,
	arr_memo: Dictionary,
	bc: Variant
) -> int:
	if depth > MAX_DATA_DEPTH:
		return -1
	match typeof(value):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_STRING, TYPE_STRING_NAME, TYPE_NODE_PATH, \
		TYPE_VECTOR2I, TYPE_VECTOR3I, TYPE_VECTOR4I, TYPE_RECT2I, \
		TYPE_PACKED_BYTE_ARRAY, TYPE_PACKED_INT32_ARRAY, TYPE_PACKED_INT64_ARRAY, TYPE_PACKED_STRING_ARRAY:
			return 0
		TYPE_FLOAT:
			return 0 if is_finite(float(value)) else -1
		TYPE_VECTOR2:
			return 0 if (value as Vector2).is_finite() else -1
		TYPE_VECTOR3:
			return 0 if (value as Vector3).is_finite() else -1
		TYPE_VECTOR4:
			return 0 if (value as Vector4).is_finite() else -1
		TYPE_QUATERNION:
			return 0 if (value as Quaternion).is_finite() else -1
		TYPE_COLOR:
			var vu: Variant = _value_utils()
			var c := value as Color
			var ok_c: bool = bool(vu.is_finite_color(c)) if vu != null else (is_finite(c.r) and is_finite(c.g) and is_finite(c.b) and is_finite(c.a))
			return 0 if ok_c else -1
		TYPE_RECT2:
			var r2 := value as Rect2
			return 0 if (r2.position.is_finite() and r2.size.is_finite()) else -1
		TYPE_AABB:
			var ab := value as AABB
			return 0 if (ab.position.is_finite() and ab.size.is_finite()) else -1
		TYPE_TRANSFORM2D:
			var t2 := value as Transform2D
			return 0 if (t2.x.is_finite() and t2.y.is_finite() and t2.origin.is_finite()) else -1
		TYPE_PLANE:
			var pl := value as Plane
			return 0 if (pl.normal.is_finite() and is_finite(pl.d)) else -1
		TYPE_BASIS:
			var b := value as Basis
			return 0 if (b.x.is_finite() and b.y.is_finite() and b.z.is_finite()) else -1
		TYPE_TRANSFORM3D:
			if depth >= MAX_DATA_DEPTH:
				return -1
			var t3 := value as Transform3D
			var ok_t3: bool = t3.basis.x.is_finite() and t3.basis.y.is_finite() and t3.basis.z.is_finite() and t3.origin.is_finite()
			return 1 if ok_t3 else -1
		TYPE_PROJECTION:
			var pr := value as Projection
			return 0 if (pr.x.is_finite() and pr.y.is_finite() and pr.z.is_finite() and pr.w.is_finite()) else -1
		TYPE_DICTIONARY:
			var d := value as Dictionary
			if d.is_empty():
				return 0
			if depth == MAX_DATA_DEPTH:
				return -1
			var d_sz: int = d.size()
			if bc != null:
				var cached_h: int = int(bc.memo_get_int(dict_memo, d_sz, d))
				if cached_h >= 0:
					return cached_h if depth + cached_h <= MAX_DATA_DEPTH else -1
			var max_h: int = 0
			for k: Variant in d:
				if k is String:
					max_h = maxi(max_h, 1)
				else:
					var kh: int = _pure_data_height(k, depth + 1, dict_memo, arr_memo, bc)
					if kh < 0:
						return -1
					max_h = maxi(max_h, 1 + kh)
				var vh: int = _pure_data_height(d[k], depth + 1, dict_memo, arr_memo, bc)
				if vh < 0:
					return -1
				max_h = maxi(max_h, 1 + vh)
			if bc != null:
				bc.memo_put_int(dict_memo, d_sz, d, max_h)
			return max_h
		TYPE_ARRAY:
			var arr := value as Array
			if arr.is_empty():
				return 0
			if depth == MAX_DATA_DEPTH:
				return -1
			var a_sz: int = arr.size()
			if bc != null:
				var cached_ha: int = int(bc.memo_get_int(arr_memo, a_sz, arr))
				if cached_ha >= 0:
					return cached_ha if depth + cached_ha <= MAX_DATA_DEPTH else -1
			var max_ha: int = 0
			for item: Variant in arr:
				var ih: int = _pure_data_height(item, depth + 1, dict_memo, arr_memo, bc)
				if ih < 0:
					return -1
				max_ha = maxi(max_ha, 1 + ih)
			if bc != null:
				bc.memo_put_int(arr_memo, a_sz, arr, max_ha)
			return max_ha
		TYPE_PACKED_FLOAT32_ARRAY:
			var pf32 := value as PackedFloat32Array
			if pf32.is_empty():
				return 0
			if depth == MAX_DATA_DEPTH:
				return -1
			for f: float in pf32:
				if not is_finite(f):
					return -1
			return 1
		TYPE_PACKED_FLOAT64_ARRAY:
			var pf64 := value as PackedFloat64Array
			if pf64.is_empty():
				return 0
			if depth == MAX_DATA_DEPTH:
				return -1
			for f: float in pf64:
				if not is_finite(f):
					return -1
			return 1
		TYPE_PACKED_VECTOR2_ARRAY:
			var pv2 := value as PackedVector2Array
			if pv2.is_empty():
				return 0
			if depth == MAX_DATA_DEPTH:
				return -1
			for v: Vector2 in pv2:
				if not v.is_finite():
					return -1
			return 1
		TYPE_PACKED_VECTOR3_ARRAY:
			var pv3 := value as PackedVector3Array
			if pv3.is_empty():
				return 0
			if depth == MAX_DATA_DEPTH:
				return -1
			for v: Vector3 in pv3:
				if not v.is_finite():
					return -1
			return 1
		TYPE_PACKED_VECTOR4_ARRAY:
			var pv4 := value as PackedVector4Array
			if pv4.is_empty():
				return 0
			if depth == MAX_DATA_DEPTH:
				return -1
			for v: Vector4 in pv4:
				if not v.is_finite():
					return -1
			return 1
		TYPE_PACKED_COLOR_ARRAY:
			var pc := value as PackedColorArray
			if pc.is_empty():
				return 0
			if depth == MAX_DATA_DEPTH:
				return -1
			var vu_c: Variant = _value_utils()
			for c_item: Color in pc:
				var ok: bool = bool(vu_c.is_finite_color(c_item)) if vu_c != null else (is_finite(c_item.r) and is_finite(c_item.g) and is_finite(c_item.b) and is_finite(c_item.a))
				if not ok:
					return -1
			return 1
		_:
			return -1


func build_public_state(
	state: Dictionary,
	peer: int,
	defaults: Dictionary = {},
	permission_check: Callable = Callable(),
	secret_field: String = "dm_secret",
	sanitizer: Callable = Callable()
) -> Dictionary:
	if not is_pure_data(defaults) or not is_pure_data(state):
		return {}
	var dc: Variant = _dag_cloner()
	var merged: Dictionary
	var clean_state: Dictionary
	if dc != null:
		var def_res: Dictionary = dc.safe_clone_validated_dict(defaults, 16 * 1024 * 1024, 0, MAX_DATA_DEPTH)
		if not bool(def_res.get("ok", false)):
			return {}
		var state_res: Dictionary = dc.safe_clone_validated_dict(state, 16 * 1024 * 1024, 0, MAX_DATA_DEPTH)
		if not bool(state_res.get("ok", false)):
			return {}
		merged = def_res["dict"] as Dictionary
		clean_state = state_res["dict"] as Dictionary
	else:
		merged = defaults.duplicate(true)
		clean_state = state.duplicate(true)
	for k: Variant in clean_state:
		merged[k] = clean_state[k]
	if peer != 1 and not secret_field.is_empty() and bool(merged.get(secret_field, false)):
		var allowed: bool = false
		if permission_check.is_valid():
			allowed = bool(permission_check.call(peer))
		if not allowed:
			return {}
	if sanitizer.is_valid():
		var sanitized: Variant = sanitizer.call(merged, peer)
		if not (sanitized is Dictionary):
			return {}
		merged = sanitized as Dictionary
	if merged.is_empty() or not is_pure_data(merged):
		return {}
	if dc != null:
		var merged_res: Dictionary = dc.safe_clone_validated_dict(merged, 16 * 1024 * 1024, 0, MAX_DATA_DEPTH)
		if not bool(merged_res.get("ok", false)):
			return {}
		merged = merged_res["dict"] as Dictionary
	return merged


static func can_peer_command_token(token: Object, peer: int) -> bool:
	if token == null or not is_instance_valid(token):
		return false
	if not token.has_method(&"get_component_by_id"):
		return false
	var perm: Variant = token.call(&"get_component_by_id", "permission")
	if perm is Object and is_instance_valid(perm):
		var p_obj := perm as Object
		if p_obj.has_method(&"can_command"):
			return bool(p_obj.call(&"can_command", peer))
	return false


static func matches_selector(comp_id: String, tags: PackedStringArray, selector: String) -> bool:
	if selector == "*":
		return true
	if selector.begins_with("tag:"):
		var tag_name: String = selector.substr(4)
		return tag_name in tags
	return comp_id == selector


static func does_suppress(
	dominator_id: String,
	dominator_rules: PackedStringArray,
	dominator_allowlist: PackedStringArray,
	target_id: String,
	target_tags: PackedStringArray
) -> bool:
	if target_id.is_empty() or target_id in REQUIRED_COMPONENTS or target_id == dominator_id:
		return false
	for allow_sel: String in dominator_allowlist:
		if matches_selector(target_id, target_tags, allow_sel):
			return false
	for rule_sel: String in dominator_rules:
		if matches_selector(target_id, target_tags, rule_sel):
			return true
	return false


static func _to_packed_strings(raw: Variant) -> PackedStringArray:
	if raw is PackedStringArray:
		return raw as PackedStringArray
	var out := PackedStringArray()
	if raw is Array:
		for item: Variant in raw as Array:
			if item is String or item is StringName:
				out.append(String(item))
	return out


static func has_symmetric_conflict(spec_a: Dictionary, spec_b: Dictionary) -> bool:
	var id_a: String = str(spec_a.get("id", ""))
	var id_b: String = str(spec_b.get("id", ""))
	if id_a.is_empty() or id_b.is_empty() or id_a == id_b:
		return false

	var grp_a: String = str(spec_a.get("exclusive_group", ""))
	var grp_b: String = str(spec_b.get("exclusive_group", ""))
	if not grp_a.is_empty() and grp_a == grp_b:
		return true

	var tags_a: PackedStringArray = _to_packed_strings(spec_a.get("tags", []))
	var tags_b: PackedStringArray = _to_packed_strings(spec_b.get("tags", []))
	var conf_a: PackedStringArray = _to_packed_strings(spec_a.get("conflicts_with_components", []))
	var conf_b: PackedStringArray = _to_packed_strings(spec_b.get("conflicts_with_components", []))

	for sel_a: String in conf_a:
		if matches_selector(id_b, tags_b, sel_a):
			return true
	for sel_b: String in conf_b:
		if matches_selector(id_a, tags_a, sel_b):
			return true

	var prio_a: int = int(spec_a.get("dominance_priority", 0))
	var prio_b: int = int(spec_b.get("dominance_priority", 0))
	if prio_a == prio_b:
		var sup_a: PackedStringArray = _to_packed_strings(spec_a.get("suppresses_components", []))
		var allow_a: PackedStringArray = _to_packed_strings(spec_a.get("suppression_allowlist", []))
		var sup_b: PackedStringArray = _to_packed_strings(spec_b.get("suppresses_components", []))
		var allow_b: PackedStringArray = _to_packed_strings(spec_b.get("suppression_allowlist", []))
		if does_suppress(id_a, sup_a, allow_a, id_b, tags_b) and does_suppress(id_b, sup_b, allow_b, id_a, tags_a):
			return true
	return false


static func collect_active_components(targets: Array, component_id: String) -> Array:
	if targets.is_empty() or component_id.is_empty():
		return []
	var comps: Array = []
	for raw_tok: Variant in targets:
		if not (raw_tok is Node) or not is_instance_valid(raw_tok):
			return []
		var tok := raw_tok as Node
		if not tok.is_inside_tree() or not tok.has_method(&"get_component_by_id"):
			return []
		var comp_var: Variant = tok.call(&"get_component_by_id", component_id)
		if not (comp_var is Object) or not is_instance_valid(comp_var):
			return []
		var comp := comp_var as Object
		var ctx_var: Variant = comp.get(&"ctx")
		if ctx_var is Object and is_instance_valid(ctx_var):
			var ctx_obj := ctx_var as Object
			if ctx_obj.has_method(&"is_active") and not bool(ctx_obj.call(&"is_active")):
				return []
		elif comp.has_method(&"is_inside_tree") and not bool(comp.call(&"is_inside_tree")):
			return []
		comps.append(comp)
	return comps


static func make_field_edit_payload(
	targets: Array,
	components: Array,
	field: String,
	before_values: Array,
	value: Variant = null,
	values: Array = []
) -> Dictionary:
	var payload: Dictionary = {
		"targets": targets.duplicate(),
		"components": components.duplicate(),
		"field": field,
		"before": before_values.duplicate(),
	}
	if not values.is_empty():
		payload["values"] = values.duplicate()
	else:
		payload["value"] = value
	return payload


static func make_numeric_edit_payload(
	targets: Array,
	components: Array,
	field: String,
	before_values: Array,
	phase: StringName,
	owner: Object,
	token: int,
	values: Array = [],
	response: Dictionary = {}
) -> Dictionary:
	var payload: Dictionary = {
		"phase": phase,
		"owner": owner,
		"token": token,
		"field": field,
		"response": response,
	}
	if phase == &"begin":
		payload["targets"] = targets.duplicate()
		payload["components"] = components.duplicate()
		payload["before"] = before_values.duplicate()
	if not values.is_empty():
		payload["values"] = values.duplicate()
	return payload
