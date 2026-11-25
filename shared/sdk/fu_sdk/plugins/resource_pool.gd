extends RefCounted
## Fu vtt 原生可选插件 SDK：resource_pool（通用资源定义与实体资源池组件 comp_resource_pool）
##
## 对应官方源码：scenes/candidates/resource_pool/feature_resource_pool.gd、
## comp_resource_pool.gd、resource_model.gd、resource_cost.gd、scenes/entities/board_token.gd。

const MODULE_ID: String = "resource_pool"
const MODULE_VERSION: int = 1
const SCHEMA_VERSION: int = 1
const COMP_RESOURCE_POOL_SCRIPT: String = "res://scenes/candidates/resource_pool/comp_resource_pool.gd"

const LIMIT: int = 256
const MAX_VALUE: float = 1000000000.0
const MAX_NAME_LENGTH: int = 160
const MAX_SOURCE_LENGTH: int = 128
const MAX_KEY_LENGTH: int = 64
const MAX_RECEIPTS: int = 64
const MAX_COST_ROUND: int = 999999999999

const DISPLAY_MODES: Array[String] = ["bar", "number", "count"]
const VISIBILITY_MODES: Array[String] = ["public", "controllers", "host"]
const DEFINITION_KEYS: Array[String] = ["id", "source", "name", "maximum", "color", "display", "visibility"]
const RECEIPT_STATUSES: Array[String] = ["paid", "cancelled", "undone"]

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
	return {
		"schema_version": SCHEMA_VERSION,
		"definitions": {},
	}


func default_component_state() -> Dictionary:
	return {
		"schema_version": SCHEMA_VERSION,
		"values": {},
	}


func is_valid_resource_id(raw_id: Variant) -> bool:
	if not (raw_id is String):
		return false
	var id: String = str(raw_id)
	if id.is_empty() or id.length() > MAX_SOURCE_LENGTH + 1 + MAX_KEY_LENGTH:
		return false
	var colon: int = id.find(":")
	if colon <= 0 or colon != id.rfind(":"):
		return false
	var src: String = id.substr(0, colon)
	var key: String = id.substr(colon + 1)
	return _is_valid_source(src) and _is_valid_key(key)


func make_definition(
	key_or_id: String,
	name: String,
	maximum: float,
	color_hex: String = "#4d8ae6ff",
	display: String = "bar",
	visibility: String = "public"
) -> Dictionary:
	var clean_id: String = key_or_id.strip_edges()
	var src: String = MODULE_ID
	if clean_id.contains(":"):
		var colon: int = clean_id.find(":")
		src = clean_id.substr(0, colon)
	else:
		clean_id = MODULE_ID + ":" + clean_id
	var clean_color: String = color_hex.strip_edges().to_lower()
	return {
		"id": clean_id,
		"source": src,
		"name": name.strip_edges(),
		"maximum": float(_value_utils().coerce_float(maximum, 0.0, false)),
		"color": clean_color,
		"display": display.strip_edges(),
		"visibility": visibility.strip_edges(),
	}


func validate_definition(raw: Variant, expected_id: String = "", required_source: String = "") -> Dictionary:
	if not (raw is Dictionary):
		return {"ok": false, "reason": "invalid_definition_type"}
	var d: Dictionary = raw as Dictionary
	if d.size() != DEFINITION_KEYS.size():
		return {"ok": false, "reason": "invalid_definition_keys"}
	for k: String in DEFINITION_KEYS:
		if not d.has(k):
			return {"ok": false, "reason": "missing_definition_key:" + k}

	var id_v: Variant = d["id"]
	var src_v: Variant = d["source"]
	if not (id_v is String) or not (src_v is String):
		return {"ok": false, "reason": "invalid_definition_id_type"}
	var id: String = str(id_v)
	var src: String = str(src_v)
	if not is_valid_resource_id(id):
		return {"ok": false, "reason": "invalid_resource_id"}
	if not expected_id.is_empty() and id != expected_id:
		return {"ok": false, "reason": "resource_id_key_mismatch"}
	if not required_source.is_empty() and src != required_source:
		return {"ok": false, "reason": "invalid_resource_source"}
	if not id.begins_with(src + ":"):
		return {"ok": false, "reason": "resource_source_prefix_mismatch"}

	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	var name_v: Variant = d["name"]
	if not (name_v is String):
		return {"ok": false, "reason": "invalid_resource_name_type"}
	var raw_name: String = str(name_v)
	var trimmed_name: String = raw_name.strip_edges()
	if trimmed_name.is_empty() or raw_name.length() > MAX_NAME_LENGTH or bool(valid_u.has_control_chars(raw_name, false)):
		return {"ok": false, "reason": "invalid_resource_name"}

	var max_v: Variant = d["maximum"]
	if not (max_v is int or max_v is float):
		return {"ok": false, "reason": "invalid_resource_maximum_type"}
	var max_f: float = float(max_v)
	if not is_finite(max_f) or max_f < 0.0 or max_f > MAX_VALUE:
		return {"ok": false, "reason": "invalid_resource_maximum_range"}

	var col_v: Variant = d["color"]
	if not (col_v is String) or not bool(val_u.is_hex8_color(str(col_v))):
		return {"ok": false, "reason": "invalid_resource_color"}

	var disp_v: Variant = d["display"]
	if not (disp_v is String) or not (str(disp_v) in DISPLAY_MODES):
		return {"ok": false, "reason": "invalid_resource_display"}

	var vis_v: Variant = d["visibility"]
	if not (vis_v is String) or not (str(vis_v) in VISIBILITY_MODES):
		return {"ok": false, "reason": "invalid_resource_visibility"}

	return {
		"ok": true,
		"data": {
			"id": id,
			"source": src,
			"name": trimmed_name,
			"maximum": max_f,
			"color": str(col_v).to_lower(),
			"display": str(disp_v),
			"visibility": str(vis_v),
		},
	}


func validate_definitions_state(state_var: Variant) -> Dictionary:
	if not (state_var is Dictionary):
		return {"ok": false, "reason": "invalid_resource_pool_state_type"}
	var state: Dictionary = state_var as Dictionary
	if state.is_empty():
		return {"ok": true, "data": default_state()}
	var has_stamps: bool = state.has("adjustment_stamps")
	var expected_size: int = 3 if has_stamps else 2
	if state.size() != expected_size or not state.has("schema_version") or not state.has("definitions"):
		return {"ok": false, "reason": "invalid_resource_pool_envelope"}

	var sv_parsed: Dictionary = _value_utils().parse_int_val(state["schema_version"])
	if not bool(sv_parsed["ok"]) or int(sv_parsed["value"]) != SCHEMA_VERSION:
		return {"ok": false, "reason": "invalid_schema_version"}

	var defs_v: Variant = state["definitions"]
	if not (defs_v is Dictionary):
		return {"ok": false, "reason": "invalid_definitions_type"}
	var defs: Dictionary = defs_v as Dictionary
	if defs.size() > LIMIT:
		return {"ok": false, "reason": "definitions_limit_exceeded"}

	var clean_defs: Dictionary = {}
	for raw_id: Variant in defs.keys():
		if not (raw_id is String):
			return {"ok": false, "reason": "invalid_definition_key_type"}
		var id: String = str(raw_id)
		var def_res: Dictionary = validate_definition(defs[raw_id], id, MODULE_ID)
		if not bool(def_res.get("ok", false)):
			return def_res
		clean_defs[id] = def_res["data"]

	var clean_state: Dictionary = {
		"schema_version": SCHEMA_VERSION,
		"definitions": clean_defs,
	}
	if has_stamps:
		var valid_u: Variant = _validation_utils()
		var stamps_v: Variant = state["adjustment_stamps"]
		if not (stamps_v is Dictionary):
			return {"ok": false, "reason": "invalid_adjustment_stamps_type"}
		var stamps: Dictionary = stamps_v as Dictionary
		var clean_stamps: Dictionary = {}
		for raw_sid: Variant in stamps.keys():
			if not (raw_sid is String) or not clean_defs.has(str(raw_sid)):
				return {"ok": false, "reason": "unknown_adjustment_stamp_definition"}
			var stamp_val: Variant = stamps[raw_sid]
			if not (stamp_val is String) or not bool(valid_u.is_valid_uid(str(stamp_val))):
				return {"ok": false, "reason": "invalid_adjustment_stamp_id"}
			clean_stamps[str(raw_sid)] = str(stamp_val)
		clean_state["adjustment_stamps"] = clean_stamps

	return {"ok": true, "data": clean_state}


func validate_state(state_var: Variant) -> Dictionary:
	return validate_definitions_state(state_var)


func validate_component_state(state_var: Variant, entity: Dictionary = {}) -> Dictionary:
	if not (state_var is Dictionary):
		return {"ok": false, "reason": "invalid_resource_pool_comp_type"}
	var state: Dictionary = state_var as Dictionary
	var clean_state: Dictionary = {}

	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	if state.is_empty():
		clean_state = default_component_state()
	else:
		if state.has("presentation"):
			return {"ok": false, "reason": "ephemeral_presentation_not_persisted"}
		for raw_k: Variant in state.keys():
			if not (raw_k is String) or not (str(raw_k) in ["schema_version", "values", "cost_round", "cost_receipts"]):
				return {"ok": false, "reason": "unknown_resource_pool_comp_key:" + str(raw_k)}
		if not state.has("schema_version") or not state.has("values"):
			return {"ok": false, "reason": "missing_resource_pool_comp_keys"}
		var sv_comp: Dictionary = val_u.parse_int_val(state["schema_version"])
		if not bool(sv_comp["ok"]) or int(sv_comp["value"]) != SCHEMA_VERSION:
			return {"ok": false, "reason": "invalid_schema_version"}
		var vals_v: Variant = state["values"]
		if not (vals_v is Dictionary):
			return {"ok": false, "reason": "invalid_values_type"}
		var vals: Dictionary = vals_v as Dictionary
		if vals.size() > LIMIT:
			return {"ok": false, "reason": "values_limit_exceeded"}

		var clean_vals: Dictionary = {}
		for raw_rid: Variant in vals.keys():
			if not is_valid_resource_id(raw_rid):
				return {"ok": false, "reason": "invalid_resource_id"}
			var entry_v: Variant = vals[raw_rid]
			if not (entry_v is Dictionary):
				return {"ok": false, "reason": "invalid_resource_value_type"}
			var entry: Dictionary = entry_v as Dictionary
			if entry.size() != 2 or not entry.has("current") or not entry.has("maximum"):
				return {"ok": false, "reason": "invalid_resource_value_keys"}
			var cur_v: Variant = entry["current"]
			var max_v: Variant = entry["maximum"]
			if not (cur_v is int or cur_v is float) or not (max_v is int or max_v is float):
				return {"ok": false, "reason": "invalid_resource_number_type"}
			var cur_f: float = float(cur_v)
			var max_f: float = float(max_v)
			if not is_finite(cur_f) or not is_finite(max_f):
				return {"ok": false, "reason": "non_finite_resource_number"}
			if cur_f < 0.0 or max_f < 0.0 or cur_f > max_f or max_f > MAX_VALUE:
				return {"ok": false, "reason": "resource_value_out_of_bounds"}
			clean_vals[str(raw_rid)] = {
				"current": cur_f,
				"maximum": max_f,
			}

		clean_state = {
			"schema_version": SCHEMA_VERSION,
			"values": clean_vals,
		}
		if state.has("cost_round"):
			var cr_parsed: Dictionary = val_u.parse_int_val(state["cost_round"])
			if not bool(cr_parsed["ok"]) or int(cr_parsed["value"]) < 0 or int(cr_parsed["value"]) > MAX_COST_ROUND:
				return {"ok": false, "reason": "invalid_cost_round"}
			if int(cr_parsed["value"]) > 0:
				clean_state["cost_round"] = int(cr_parsed["value"])
		if state.has("cost_receipts"):
			var rec_v: Variant = state["cost_receipts"]
			if not (rec_v is Dictionary) or (rec_v as Dictionary).size() > MAX_RECEIPTS:
				return {"ok": false, "reason": "invalid_cost_receipts"}
			var recs: Dictionary = rec_v as Dictionary
			var clean_recs: Dictionary = {}
			for raw_rk: Variant in recs.keys():
				if not (raw_rk is String) or str(raw_rk).length() > 156 or not _is_valid_cost_receipt_key(str(raw_rk)):
					return {"ok": false, "reason": "invalid_cost_receipt_key"}
				var rv: Variant = recs[raw_rk]
				if not (rv is Array) or (rv as Array).size() != 2:
					return {"ok": false, "reason": "invalid_cost_receipt_value"}
				var arr: Array = rv as Array
				if not (arr[0] is String) or str(arr[0]).is_empty() or str(arr[0]).length() > 128:
					return {"ok": false, "reason": "invalid_cost_receipt_author"}
				if not (arr[1] is String) or not (str(arr[1]) in RECEIPT_STATUSES):
					return {"ok": false, "reason": "invalid_cost_receipt_status"}
				clean_recs[str(raw_rk)] = [str(arr[0]), str(arr[1])]
			clean_state["cost_receipts"] = clean_recs

	if not entity.is_empty():
		var comps_var: Variant = entity.get("components", [])
		if comps_var is Array:
			for raw_c: Variant in comps_var as Array:
				if raw_c is Dictionary:
					var scr: String = str((raw_c as Dictionary).get("script", ""))
					if str(valid_u.component_id_from_script(scr)) == "scene_box":
						return {"ok": false, "reason": "component_conflict_with_scene_box:resource_pool"}

	return {"ok": true, "data": clean_state}


func make_entity_state(values: Dictionary = {}) -> Dictionary:
	var val_u: Variant = _value_utils()
	var clean_vals: Dictionary = {}
	for raw_k: Variant in values.keys():
		var rid: String = str(raw_k)
		var v: Variant = values[raw_k]
		if v is Dictionary:
			var vd: Dictionary = v as Dictionary
			clean_vals[rid] = {
				"current": float(val_u.coerce_float(vd.get("current", 0.0), 0.0, false)),
				"maximum": float(val_u.coerce_float(vd.get("maximum", 0.0), 0.0, false)),
			}
	return {
		"schema_version": SCHEMA_VERSION,
		"values": clean_vals,
	}


func configure_resource_pool(state: Dictionary) -> Dictionary:
	var gate: Dictionary = _check_gate("configure_resource_pool")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var checked: Dictionary = validate_definitions_state(state)
	if not bool(checked.get("ok", false)):
		var reason: String = str(checked.get("reason", "invalid_resource_pool_state"))
		_warn("resource_pool 配置校验失败：%s" % reason)
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


func set_state(state: Dictionary) -> Dictionary:
	return configure_resource_pool(state)


func define_resource(
	key_or_id: String,
	name: String,
	maximum: float,
	color_hex: String = "#4d8ae6ff",
	display: String = "bar",
	visibility: String = "public"
) -> Dictionary:
	var gate: Dictionary = _check_gate("define_resource")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var raw_def: Dictionary = make_definition(key_or_id, name, maximum, color_hex, display, visibility)
	var def_checked: Dictionary = validate_definition(raw_def, str(raw_def["id"]), MODULE_ID)
	if not bool(def_checked.get("ok", false)):
		return def_checked

	var current: Dictionary = get_state()
	if current.is_empty():
		current = default_state()
	var raw_defs: Variant = current.get("definitions", null)
	var defs: Dictionary = {}
	if raw_defs == null:
		if current.has("definitions"):
			return {"ok": false, "reason": "invalid_resource_pool_definitions"}
	elif not (raw_defs is Dictionary):
		return {"ok": false, "reason": "invalid_resource_pool_definitions"}
	else:
		var defs_budget: Array = [16384, false]
		defs = _safe_clone_dict(raw_defs as Dictionary, 0, [], defs_budget)
		if bool(defs_budget[1]):
			return {"ok": false, "reason": "resource_pool_state_too_large"}
	var rid: String = str(raw_def["id"])
	if not defs.has(rid) and defs.size() >= LIMIT:
		return {"ok": false, "reason": "definitions_limit_exceeded"}
	defs[rid] = def_checked["data"]
	var next_state: Dictionary = {"schema_version": SCHEMA_VERSION, "definitions": defs}
	if current.has("adjustment_stamps"):
		var raw_stamps: Variant = current["adjustment_stamps"]
		if not (raw_stamps is Dictionary):
			return {"ok": false, "reason": "invalid_adjustment_stamps_type"}
		var stamps_budget: Array = [16384, false]
		next_state["adjustment_stamps"] = _safe_clone_dict(raw_stamps as Dictionary, 0, [], stamps_budget)
		if bool(stamps_budget[1]):
			return {"ok": false, "reason": "resource_pool_state_too_large"}
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, next_state))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"definition": def_checked["data"],
		"enabled": bool(gate.get("enabled", false)),
	}


func attach_resource_pool(
	entity_id: String,
	state: Dictionary = {},
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_resource_pool")
	if not bool(gate.get("ok", true)):
		return gate
	return _attach_resource_pool_impl(entity_id, state, parked, manual, gate)


func _attach_resource_pool_impl(
	entity_id: String,
	state: Dictionary,
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

	var checked: Dictionary = validate_component_state(state, entity)
	if not bool(checked.get("ok", false)):
		var reason: String = str(checked.get("reason", "invalid_resource_pool_comp_state"))
		_warn("无法挂载 resource_pool 组件（%s）：%s" % [entity_id, reason])
		return {"ok": false, "reason": reason}

	var clean_state: Dictionary = checked["data"] as Dictionary
	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_RESOURCE_POOL_SCRIPT,
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


func set_entity_resource(
	entity_id: String,
	resource_id: String,
	current: float,
	maximum: float = -1.0,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("set_entity_resource")
	if not bool(gate.get("ok", true)):
		return gate
	if manual and not parked:
		return {"ok": false, "reason": "manual_requires_parked"}
	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	var cur_val: float = float(val_u.coerce_float(current, 0.0, false))
	var max_val: float = cur_val if maximum == -1.0 else float(val_u.coerce_float(maximum, 0.0, false))
	var entity: Dictionary = _lookup_entity(entity_id)
	var existing_values: Dictionary = {}
	if not entity.is_empty():
		var comps_var: Variant = entity.get("components", [])
		if comps_var is Array:
			for raw_c: Variant in comps_var as Array:
				if raw_c is Dictionary and str(valid_u.component_id_from_script(str((raw_c as Dictionary).get("script", "")))) == "resource_pool":
					var st_var: Variant = (raw_c as Dictionary).get("state", {})
					if st_var is Dictionary and (st_var as Dictionary).get("values", null) is Dictionary:
						var vals_budget: Array = [16384, false]
						existing_values = _safe_clone_dict((st_var as Dictionary)["values"] as Dictionary, 0, [], vals_budget)
						if bool(vals_budget[1]):
							return {"ok": false, "reason": "resource_pool_state_too_large"}
	existing_values[resource_id] = {"current": cur_val, "maximum": max_val}
	return _attach_resource_pool_impl(entity_id, {"schema_version": SCHEMA_VERSION, "values": existing_values}, parked, manual, gate)


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


func _is_valid_source(src: String) -> bool:
	if src.is_empty() or src.length() > MAX_SOURCE_LENGTH:
		return false
	var parts: PackedStringArray = src.split(".")
	for part: String in parts:
		if part.is_empty():
			return false
		var first: int = part.unicode_at(0)
		if first < 97 or first > 122:
			return false
		for i: int in range(1, part.length()):
			var c: int = part.unicode_at(i)
			var ok: bool = (c >= 97 and c <= 122) or (c >= 48 and c <= 57) or c == 95
			if not ok:
				return false
	return true


func _is_valid_key(key: String) -> bool:
	if key.is_empty() or key.length() > MAX_KEY_LENGTH:
		return false
	var first: int = key.unicode_at(0)
	if not ((first >= 97 and first <= 122) or (first >= 48 and first <= 57)):
		return false
	for i: int in range(1, key.length()):
		var c: int = key.unicode_at(i)
		var ok: bool = (c >= 97 and c <= 122) or (c >= 48 and c <= 57) or c == 95 or c == 45
		if not ok:
			return false
	return true


func _is_valid_cost_receipt_key(rk: String) -> bool:
	var parts: PackedStringArray = rk.split(".")
	if parts.size() != 4:
		return false
	var valid_u: Variant = _validation_utils()
	if not bool(valid_u.is_valid_uid(parts[0])):
		return false
	if parts[1].is_empty() or not parts[1].is_valid_int() or int(parts[1]) < 0:
		return false
	if not bool(valid_u.is_valid_uid(parts[2])):
		return false
	return bool(valid_u.is_valid_hex64(parts[3], false))


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


## 保持白盒测试兼容性：委托 utils/bounded_cloner.gd 执行无记忆化轻量有界字典深拷贝（维持 dag24 耗尽检测）。
func _safe_clone_dict(d: Dictionary, depth: int = 0, stack: Array = [], budget: Array = []) -> Dictionary:
	return _bounded_cloner().simple_clone_dict(d, depth, stack, budget)
