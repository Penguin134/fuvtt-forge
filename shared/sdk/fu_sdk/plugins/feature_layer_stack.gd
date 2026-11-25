extends RefCounted
## Fu vtt 原生核心插件 SDK：feature_layer_stack（场景图层栈 fus.floor_layers.v2）
##
## 对应官方源码：scenes/extension/feature_layer_stack.gd、
## scenes/systems/layers/layer_stack_state.gd、world_snapshot.gd。

const MODULE_ID: String = "feature_layer_stack"
const SCHEMA: String = "fus.floor_layers.v2"
const LEGACY_SCHEMA: String = "fus.floor_layers.v1"
const DEFAULT_KINDS: Array[String] = ["map", "entity", "obstacle"]
const KINDS: Array[String] = ["map", "entity", "obstacle", "area"]
const ACCESS_POLICIES: Array[String] = ["all", "host", "players"]

const MAX_FLOORS: int = 512
const MAX_LAYERS_PER_FLOOR: int = 256
const MAX_TOTAL_LAYERS: int = 4096
const MAX_SELECTED_VIEWERS: int = 128
const MAX_NAME_LENGTH: int = 96
const MAX_VIEWER_KEY_LENGTH: int = 160

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
	return true


func get_availability() -> Dictionary:
	if _module_registry != null:
		return _module_registry.get_module_entry(MODULE_ID)
	return {
		"id": MODULE_ID,
		"core": true,
		"status": "core",
		"enabled": true,
	}


func add_layer(
	name: String,
	kind: String = "entity",
	access: String = "all",
	floor_uid: String = "",
	viewers: Array = [],
	locked: bool = false,
	visible: bool = true,
	persistent: bool = true
) -> String:
	var gate: Dictionary = _check_gate("add_layer")
	if not bool(gate.get("ok", true)):
		return ""
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	var normalized_access: String = access.strip_edges().to_lower()
	if not (normalized_access in ACCESS_POLICIES):
		return ""
	if not _validate_viewers_input(viewers):
		return ""
	var clean_viewers: Array = _sanitize_viewers(viewers)
	if (normalized_access == "players") != (not clean_viewers.is_empty()):
		return ""
	return str(wb.add_layer(name, kind, normalized_access, floor_uid, clean_viewers, locked, visible, persistent))


func get_layer_uid(kind: String, floor_uid: String = "") -> String:
	var wb: RefCounted = _wb()
	if wb == null:
		return ""
	return str(wb.get_layer_uid(kind, floor_uid))


func get_floor_layers(floor_uid: String = "") -> Array:
	var wb: RefCounted = _wb()
	if wb == null:
		return []
	return wb.get_floor_layers(floor_uid)


func get_layer(layer_uid: String) -> Dictionary:
	var found: Dictionary = _find_layer_ref(layer_uid)
	if found.is_empty():
		return {}
	return _safe_clone_dict(found["layer"] as Dictionary)


func set_layer_visibility(layer_uid: String, visible: bool) -> bool:
	var gate: Dictionary = _check_gate("set_layer_visibility")
	if not bool(gate.get("ok", true)):
		return false
	var found: Dictionary = _find_layer_ref(layer_uid)
	if found.is_empty():
		return false
	(found["layer"] as Dictionary)["visible"] = visible
	return true


func set_layer_locked(layer_uid: String, locked: bool) -> bool:
	var gate: Dictionary = _check_gate("set_layer_locked")
	if not bool(gate.get("ok", true)):
		return false
	var found: Dictionary = _find_layer_ref(layer_uid)
	if found.is_empty():
		return false
	(found["layer"] as Dictionary)["locked"] = locked
	return true


func rename_layer(layer_uid: String, new_name: String) -> bool:
	var gate: Dictionary = _check_gate("rename_layer")
	if not bool(gate.get("ok", true)):
		return false
	var clean_name: String = str(_validation_utils().strip_leading_bom(new_name))
	if not _is_valid_name(clean_name):
		return false
	var found: Dictionary = _find_layer_ref(layer_uid)
	if found.is_empty():
		return false
	(found["layer"] as Dictionary)["name"] = clean_name
	return true


func set_layer_access(
	layer_uid: String,
	access: String,
	viewers: Array = []
) -> bool:
	var gate: Dictionary = _check_gate("set_layer_access")
	if not bool(gate.get("ok", true)):
		return false
	var normalized_access: String = access.strip_edges().to_lower()
	if not (normalized_access in ACCESS_POLICIES):
		return false

	if not _validate_viewers_input(viewers):
		return false
	var clean_viewers: Array = _sanitize_viewers(viewers)
	if (normalized_access == "players") != (not clean_viewers.is_empty()):
		return false

	var found: Dictionary = _find_layer_ref(layer_uid)
	if found.is_empty():
		return false
	var floor_entry: Dictionary = found["floor"] as Dictionary
	var layer: Dictionary = found["layer"] as Dictionary
	if str(_value_utils().as_str(floor_entry.get("default_layer_uid", ""))) == layer_uid and normalized_access != "all":
		return false

	layer["access"] = normalized_access
	layer["viewers"] = clean_viewers
	return true


func set_default_layer(floor_uid: String, layer_uid: String) -> bool:
	var gate: Dictionary = _check_gate("set_default_layer")
	if not bool(gate.get("ok", true)):
		return false
	if floor_uid.is_empty() or layer_uid.is_empty():
		return false
	var world: Dictionary = _get_world()
	var layers_root: Dictionary = _get_layers_root(world)
	if layers_root.is_empty():
		return false
	var floors_var: Variant = layers_root.get("floors", [])
	if not (floors_var is Array):
		return false
	var val_u: Variant = _value_utils()
	for raw_floor: Variant in floors_var as Array:
		if not (raw_floor is Dictionary):
			continue
		var floor_entry: Dictionary = raw_floor as Dictionary
		if str(val_u.as_str(floor_entry.get("floor_uid", ""))) != floor_uid:
			continue
		var rows_var: Variant = floor_entry.get("layers", [])
		if not (rows_var is Array):
			return false
		for raw_layer: Variant in rows_var as Array:
			if not (raw_layer is Dictionary):
				continue
			var layer: Dictionary = raw_layer as Dictionary
			if str(val_u.as_str(layer.get("layer_uid", ""))) != layer_uid:
				continue
			if not (layer.get("persistent", null) is bool and layer.get("persistent", false) == true):
				return false
			if str(val_u.as_str(layer.get("access", ""))) != "all":
				return false
			var lkind: String = str(val_u.as_str(layer.get("kind", "")))
			if not (lkind in KINDS) or lkind == "area":
				return false
			floor_entry["default_layer_uid"] = layer_uid
			return true
	return false


func set_editor_view(
	floor_uid: String,
	layer_uid: String,
	all_unlocked: bool = false
) -> bool:
	var gate: Dictionary = _check_gate("set_editor_view")
	if not bool(gate.get("ok", true)):
		return false
	if floor_uid.is_empty() or layer_uid.is_empty():
		return false
	var world: Dictionary = _get_world()
	if world.is_empty():
		return false
	var found: Dictionary = _find_layer_ref(layer_uid)
	if found.is_empty():
		return false
	var owner_floor: Dictionary = found["floor"] as Dictionary
	if str(_value_utils().as_str(owner_floor.get("floor_uid", ""))) != floor_uid:
		return false
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return false
	var catalog: Dictionary = catalog_var
	if not (catalog.get("editor_view", null) is Dictionary):
		catalog["editor_view"] = {"layers": {}, "all_unlocked": all_unlocked}
	var ev: Dictionary = catalog["editor_view"]
	if not (ev.get("layers", null) is Dictionary):
		ev["layers"] = {}
	(ev["layers"] as Dictionary)[floor_uid] = layer_uid
	ev["all_unlocked"] = all_unlocked
	return true


func validate_layer_catalog(world: Dictionary = {}) -> Dictionary:
	var target_world: Dictionary = world if not world.is_empty() else _get_world()
	var errors: Array[String] = []
	if target_world.is_empty():
		return {"ok": false, "errors": ["world_empty"]}
	var catalog_var: Variant = target_world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return {"ok": false, "errors": ["invalid_world_catalog"]}
	var catalog: Dictionary = catalog_var

	var layers_root_var: Variant = catalog.get("layers", null)
	if not (layers_root_var is Dictionary):
		return {"ok": false, "errors": ["missing_layers_catalog"]}
	var layers_root: Dictionary = layers_root_var

	if layers_root.size() != 2 or not layers_root.has("schema") or not layers_root.has("floors"):
		errors.append("invalid_layers_root_keys")
	var schema_var: Variant = layers_root.get("schema", null)
	if not (schema_var is String) or str(schema_var) != SCHEMA:
		errors.append("invalid_layers_schema")

	var layer_floors_var: Variant = layers_root.get("floors", null)
	if not (layer_floors_var is Array):
		errors.append("missing_layer_floors")
		return {"ok": false, "errors": errors}
	var layer_floors: Array = layer_floors_var
	if layer_floors.is_empty() or layer_floors.size() > MAX_FLOORS:
		errors.append("invalid_layer_floors_count")

	var known_world_floors: Dictionary = {}
	var world_floors_var: Variant = catalog.get("floors", [])
	if world_floors_var is Array:
		for wf: Variant in world_floors_var as Array:
			if wf is Dictionary:
				var fuid_var: Variant = (wf as Dictionary).get("floor_uid", null)
				if fuid_var is String and not str(fuid_var).is_empty():
					known_world_floors[str(fuid_var)] = true

	var valid_u: Variant = _validation_utils()
	var seen_floor_uids: Dictionary = {}
	var seen_layer_uids: Dictionary = {}
	var layer_floor_map: Dictionary = {}
	var total_layers: int = 0

	for f_idx: int in range(layer_floors.size()):
		var raw_floor: Variant = layer_floors[f_idx]
		if not (raw_floor is Dictionary):
			errors.append("invalid_layer_floor_row:%d" % f_idx)
			continue
		var frow: Dictionary = raw_floor as Dictionary
		if frow.size() != 3 or not frow.has("floor_uid") or not frow.has("default_layer_uid") or not frow.has("layers"):
			errors.append("invalid_layer_floor_keys:%d" % f_idx)
		var raw_fuid: Variant = frow.get("floor_uid", null)
		var fuid: String = str(raw_fuid) if raw_fuid is String else ""
		if not bool(valid_u.is_valid_uid(fuid)) or seen_floor_uids.has(fuid):
			errors.append("invalid_or_duplicate_layer_floor_uid:%d" % f_idx)
		else:
			seen_floor_uids[fuid] = true
		if not known_world_floors.is_empty() and not known_world_floors.has(fuid):
			errors.append("orphan_layer_floor_uid:" + fuid)

		var rows_var: Variant = frow.get("layers", null)
		if not (rows_var is Array):
			errors.append("missing_floor_layers_array:" + fuid)
			continue
		var rows: Array = rows_var
		if rows.is_empty() or rows.size() > MAX_LAYERS_PER_FLOOR:
			errors.append("invalid_floor_layers_count:" + fuid)

		var raw_def_uid: Variant = frow.get("default_layer_uid", null)
		var default_uid: String = str(raw_def_uid) if raw_def_uid is String else ""
		var found_default: Dictionary = {}

		for l_idx: int in range(rows.size()):
			total_layers += 1
			var raw_layer: Variant = rows[l_idx]
			if not (raw_layer is Dictionary):
				errors.append("invalid_layer_row:%s:%d" % [fuid, l_idx])
				continue
			var lrow: Dictionary = raw_layer as Dictionary
			if (
				lrow.size() != 8
				or not lrow.has("layer_uid")
				or not lrow.has("name")
				or not lrow.has("kind")
				or not lrow.has("visible")
				or not lrow.has("locked")
				or not lrow.has("persistent")
				or not lrow.has("access")
				or not lrow.has("viewers")
			):
				errors.append("invalid_layer_keys:%s:%d" % [fuid, l_idx])

			var raw_luid: Variant = lrow.get("layer_uid", null)
			var luid: String = str(raw_luid) if raw_luid is String else ""
			if not bool(valid_u.is_valid_uid(luid)) or seen_layer_uids.has(luid):
				errors.append("invalid_or_duplicate_layer_uid:" + luid)
			else:
				seen_layer_uids[luid] = true
				layer_floor_map[luid] = fuid

			var lname: Variant = lrow.get("name", null)
			if not (lname is String) or not _is_valid_name(lname as String):
				errors.append("invalid_layer_name:" + luid)

			var raw_lkind: Variant = lrow.get("kind", null)
			var lkind: String = str(raw_lkind) if raw_lkind is String else ""
			if not (lkind in KINDS):
				errors.append("invalid_layer_kind:" + luid)

			if not (lrow.get("visible", null) is bool) or not (lrow.get("locked", null) is bool) or not (lrow.get("persistent", null) is bool):
				errors.append("invalid_layer_bools:" + luid)

			var raw_laccess: Variant = lrow.get("access", null)
			var laccess: String = str(raw_laccess) if raw_laccess is String else ""
			if not (laccess in ACCESS_POLICIES):
				errors.append("invalid_layer_access:" + luid)

			var lviewers_var: Variant = lrow.get("viewers", null)
			if not (lviewers_var is Array):
				errors.append("invalid_layer_viewers_type:" + luid)
			else:
				var lviewers: Array = lviewers_var as Array
				if lviewers.size() > MAX_SELECTED_VIEWERS:
					errors.append("layer_viewers_limit_exceeded:" + luid)
				if (laccess == "players") != (not lviewers.is_empty()):
					errors.append("invalid_layer_viewers_for_access:" + luid)
				var seen_v: Dictionary = {}
				for raw_v: Variant in lviewers:
					var vs: String = str(raw_v) if raw_v is String else ""
					if (
						not (raw_v is String)
						or str(valid_u.strip_leading_bom(vs)) != vs
						or vs.strip_edges().is_empty()
						or vs != vs.strip_edges()
						or vs.length() > MAX_VIEWER_KEY_LENGTH
						or bool(valid_u.has_control_chars(vs, true))
						or seen_v.has(vs)
					):
						errors.append("invalid_layer_viewer_entry:" + luid)
					else:
						seen_v[vs] = true

			if luid == default_uid:
				found_default = lrow

		if found_default.is_empty():
			errors.append("missing_default_layer:" + fuid)
		else:
			if not (found_default.get("persistent", null) is bool and found_default.get("persistent", false) == true):
				errors.append("default_layer_not_persistent:" + fuid)
			if str(found_default.get("access", "")) != "all":
				errors.append("default_layer_access_not_all:" + fuid)
			if str(found_default.get("kind", "")) == "area":
				errors.append("default_layer_cannot_be_area:" + fuid)

	if total_layers > MAX_TOTAL_LAYERS:
		errors.append("total_layer_limit_exceeded")

	for known_fuid: Variant in known_world_floors.keys():
		if not seen_floor_uids.has(known_fuid):
			errors.append("missing_layer_floor_for:" + str(known_fuid))

	if catalog.has("editor_view"):
		var ev_var: Variant = catalog.get("editor_view", null)
		if not (ev_var is Dictionary):
			errors.append("invalid_editor_view_type")
		else:
			var ev: Dictionary = ev_var as Dictionary
			if not (ev.get("all_unlocked", null) is bool) or not (ev.get("layers", null) is Dictionary):
				errors.append("invalid_editor_view_keys")
			else:
				var ev_layers: Dictionary = ev["layers"]
				for raw_efuid: Variant in ev_layers.keys():
					if not (raw_efuid is String) or not (ev_layers[raw_efuid] is String):
						errors.append("invalid_editor_view_layer_type")
						continue
					var efuid: String = str(raw_efuid)
					var eluid: String = str(ev_layers[raw_efuid])
					if efuid.is_empty() or eluid.is_empty() or not layer_floor_map.has(eluid) or str(layer_floor_map.get(eluid, "")) != efuid:
						errors.append("invalid_editor_view_layer:" + efuid)

	return {
		"ok": errors.is_empty(),
		"errors": errors,
	}


func _get_world() -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null:
		return {}
	return wb.get_world()


func _get_layers_root(world: Dictionary) -> Dictionary:
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return {}
	var layers_var: Variant = (catalog_var as Dictionary).get("layers", null)
	if layers_var is Dictionary:
		return layers_var as Dictionary
	return {}


func _find_layer_ref(layer_uid: String) -> Dictionary:
	if layer_uid.is_empty():
		return {}
	var world: Dictionary = _get_world()
	var layers_root: Dictionary = _get_layers_root(world)
	if layers_root.is_empty():
		return {}
	var floors_var: Variant = layers_root.get("floors", [])
	if not (floors_var is Array):
		return {}
	var val_u: Variant = _value_utils()
	for raw_floor: Variant in floors_var as Array:
		if not (raw_floor is Dictionary):
			continue
		var floor_entry: Dictionary = raw_floor as Dictionary
		var rows_var: Variant = floor_entry.get("layers", [])
		if not (rows_var is Array):
			continue
		for raw_layer: Variant in rows_var as Array:
			if raw_layer is Dictionary and str(val_u.as_str((raw_layer as Dictionary).get("layer_uid", ""))) == layer_uid:
				return {"floor": floor_entry, "layer": raw_layer}
	return {}


func _sanitize_viewer_key(value: String) -> String:
	var valid_u: Variant = _validation_utils()
	if bool(valid_u.has_control_chars(value, true)):
		return ""
	var cleaned: String = str(valid_u.strip_bom_and_edges(value))
	if cleaned.is_empty() or cleaned.length() > MAX_VIEWER_KEY_LENGTH:
		return ""
	return cleaned


func _validate_viewers_input(viewers: Array) -> bool:
	for raw_v: Variant in viewers:
		if not (raw_v is String):
			return false
		if _sanitize_viewer_key(raw_v as String).is_empty():
			return false
	return true


func _sanitize_viewers(viewers: Array) -> Array:
	var clean_viewers: Array = []
	var seen: Dictionary = {}
	for raw_v: Variant in viewers:
		if not (raw_v is String):
			continue
		var vs: String = _sanitize_viewer_key(raw_v as String)
		if vs.is_empty() or seen.has(vs):
			continue
		seen[vs] = true
		clean_viewers.append(vs)
		if clean_viewers.size() >= MAX_SELECTED_VIEWERS:
			break
	clean_viewers.sort()
	return clean_viewers


func _is_valid_name(name: String) -> bool:
	var valid_u: Variant = _validation_utils()
	if str(valid_u.strip_leading_bom(name)) != name:
		return false
	var trimmed: String = name.strip_edges()
	if trimmed.is_empty() or trimmed.length() > MAX_NAME_LENGTH or trimmed != name:
		return false
	return not bool(valid_u.has_control_chars(name, true))


func _check_gate(action: String) -> Dictionary:
	if _module_registry != null:
		return _module_registry.check_and_warn(MODULE_ID, action)
	return {"ok": true}


func _safe_clone_dict(raw: Dictionary) -> Dictionary:
	var cloned: Variant = _safe_clone_via_adapter(raw)
	return cloned as Dictionary if cloned is Dictionary else {}


## 优先委托适配器深拷贝；缺失时回退至 BoundedCloner 默认预算（16384）。
func _safe_clone_via_adapter(value: Variant) -> Variant:
	var wb: RefCounted = _wb()
	var adapter: RefCounted = wb.get_adapter() if (wb != null and wb.has_method("get_adapter")) else null
	var bc: Variant = _bounded_cloner()
	return bc.safe_clone_via_adapter(value, adapter, bc.DEFAULT_FALLBACK_BUDGET)


## 保持白盒测试兼容性：委托 utils/bounded_cloner.gd 执行 16384 默认预算回退克隆。
func _bounded_fallback_clone(value: Variant, depth: int = 0, active_stack: Array = [], budget: Array = []) -> Variant:
	var bc: Variant = _bounded_cloner()
	return bc.bounded_fallback_clone(value, depth, active_stack, budget, bc.DEFAULT_FALLBACK_BUDGET)
