extends RefCounted
## Fu vtt 原生可选插件 SDK：backpack（仅限单位实体的 16 格背包组件 comp_backpack）
##
## 对应官方源码：modules/backpack/feature_backpack.gd、comp_backpack.gd、
## bag_rules.gd、scenes/entities/board_token.gd（仅限 unit，与 scene_box 互斥）。

const MODULE_ID: String = "backpack"
const COMP_BACKPACK_SCRIPT: String = "res://modules/backpack/comp_backpack.gd"

const SLOT_COUNT: int = 16
const MAX_STACK: int = 999
const MAX_NAME_LENGTH: int = 48
const MAX_NOTE_LENGTH: int = 160
const MAX_RECEIPTS: int = 256
const MAX_ITEM_BYTES: int = 8192

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
		"revision": "",
		"slots": {},
	}


func make_item(
	name: String,
	qty: int = 1,
	note: String = "",
	extra_fields: Dictionary = {}
) -> Dictionary:
	var extra_budget: Array = [16384, false]
	var item: Dictionary = _safe_clone_dict(extra_fields, 0, [], extra_budget)
	if bool(extra_budget[1]):
		item = {}
	item["name"] = name
	item["note"] = note
	item["qty"] = qty
	return item


func validate_item(item_var: Variant) -> Dictionary:
	if not (item_var is Dictionary):
		return {"ok": false, "reason": "invalid_backpack_item_type"}
	var item: Dictionary = item_var as Dictionary
	if not item.has("name") or not item.has("note") or not item.has("qty"):
		return {"ok": false, "reason": "missing_backpack_item_keys"}

	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	var name_v: Variant = item["name"]
	if not (name_v is String):
		return {"ok": false, "reason": "invalid_item_name_type"}
	var name_s: String = str(name_v)
	if name_s.strip_edges().is_empty() or name_s.length() > MAX_NAME_LENGTH or bool(valid_u.has_nul(name_s)):
		return {"ok": false, "reason": "invalid_item_name"}

	var note_v: Variant = item["note"]
	if not (note_v is String):
		return {"ok": false, "reason": "invalid_item_note_type"}
	var note_s: String = str(note_v)
	if note_s.length() > MAX_NOTE_LENGTH or bool(valid_u.has_nul(note_s)):
		return {"ok": false, "reason": "invalid_item_note"}

	var qty_parsed: Dictionary = val_u.parse_int_val(item["qty"])
	if not bool(qty_parsed["ok"]) or int(qty_parsed["value"]) < 1 or int(qty_parsed["value"]) > MAX_STACK:
		return {"ok": false, "reason": "invalid_item_qty"}

	if item.size() > 3:
		var val_budget: Array = [16384, false]
		for raw_k: Variant in item.keys():
			if not (raw_k is String):
				return {"ok": false, "reason": "invalid_item_extra_key"}
			var k_str: String = str(raw_k)
			if not (k_str in ["name", "note", "qty"]) and not _is_valid_data_value(item[raw_k], 0, [], val_budget):
				return {"ok": false, "reason": "invalid_item_extra_value"}

	var clone_budget: Array = [16384, false]
	var clean_item: Dictionary = _safe_clone_dict(item, 0, [], clone_budget)
	if bool(clone_budget[1]):
		return {"ok": false, "reason": "backpack_item_too_large"}
	clean_item["qty"] = int(qty_parsed["value"])
	if clean_item.size() > 3 and var_to_bytes(clean_item).size() > MAX_ITEM_BYTES:
		return {"ok": false, "reason": "backpack_item_size_exceeded"}

	return {"ok": true, "data": clean_item}


func validate_state(state_var: Variant, entity: Dictionary = {}, parked: bool = false) -> Dictionary:
	if not (state_var is Dictionary):
		return {"ok": false, "reason": "invalid_backpack_state_type"}
	var state: Dictionary = state_var as Dictionary
	var clean_state: Dictionary = {}

	var valid_u: Variant = _validation_utils()
	if state.is_empty():
		clean_state = default_state()
	else:
		var has_receipts: bool = state.has("receipts")
		var expected_size: int = 2 + (1 if has_receipts else 0)
		if state.size() != expected_size or not state.has("slots") or not state.has("revision"):
			return {"ok": false, "reason": "invalid_backpack_keys"}

		var rev_v: Variant = state["revision"]
		if not (rev_v is String):
			return {"ok": false, "reason": "invalid_backpack_revision_type"}
		var rev: String = str(rev_v)
		if not rev.is_empty() and not bool(valid_u.is_valid_uid(rev)):
			return {"ok": false, "reason": "invalid_backpack_revision"}

		var slots_v: Variant = state["slots"]
		if not (slots_v is Dictionary):
			return {"ok": false, "reason": "invalid_backpack_slots_type"}
		var slots: Dictionary = slots_v as Dictionary
		if slots.size() > SLOT_COUNT:
			return {"ok": false, "reason": "backpack_slots_limit_exceeded"}

		var clean_slots: Dictionary = {}
		for raw_slot: Variant in slots.keys():
			if not (raw_slot is String):
				return {"ok": false, "reason": "invalid_backpack_slot_key_type"}
			var sk: String = str(raw_slot)
			if not sk.is_valid_int():
				return {"ok": false, "reason": "invalid_backpack_slot_key"}
			var idx: int = sk.to_int()
			if idx < 0 or idx >= SLOT_COUNT or str(idx) != sk:
				return {"ok": false, "reason": "invalid_backpack_slot_index"}
			var item_res: Dictionary = validate_item(slots[raw_slot])
			if not bool(item_res.get("ok", false)):
				return item_res
			clean_slots[sk] = item_res["data"]

		clean_state = {
			"revision": rev,
			"slots": clean_slots,
		}
		if has_receipts:
			var rec_v: Variant = state["receipts"]
			if not (rec_v is Dictionary) or (rec_v as Dictionary).size() > MAX_RECEIPTS:
				return {"ok": false, "reason": "invalid_backpack_receipts"}
			var recs: Dictionary = rec_v as Dictionary
			var clean_recs: Dictionary = {}
			for raw_rk: Variant in recs.keys():
				if not (raw_rk is String) or not bool(valid_u.is_valid_uid(str(raw_rk))):
					return {"ok": false, "reason": "invalid_backpack_receipt_key"}
				var rv: Variant = recs[raw_rk]
				if not (rv is String) or not bool(valid_u.is_valid_hex64(str(rv), true)):
					return {"ok": false, "reason": "invalid_backpack_receipt_digest"}
				clean_recs[str(raw_rk)] = str(rv).to_lower()
			clean_state["receipts"] = clean_recs

	if not entity.is_empty():
		if not parked and not bool(valid_u.is_unit_host(entity)):
			return {"ok": false, "reason": "backpack_requires_unit_host"}
		var comps_var: Variant = entity.get("components", [])
		if comps_var is Array:
			for raw_c: Variant in comps_var as Array:
				if raw_c is Dictionary:
					var scr: String = str((raw_c as Dictionary).get("script", ""))
					if str(valid_u.component_id_from_script(scr)) == "scene_box":
						return {"ok": false, "reason": "component_conflict_with_scene_box:backpack"}

	return {"ok": true, "data": clean_state}


func attach_backpack(
	entity_id: String,
	state: Dictionary = {},
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_backpack")
	if not bool(gate.get("ok", true)):
		return gate
	return _attach_backpack_impl(entity_id, state, parked, manual, gate)


func _attach_backpack_impl(
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

	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var checked: Dictionary = validate_state(state, entity, effective_parked)
	if not bool(checked.get("ok", false)):
		var reason: String = str(checked.get("reason", "invalid_backpack_state"))
		_warn("无法挂载 backpack 组件（%s）：%s" % [entity_id, reason])
		return {"ok": false, "reason": reason}

	var clean_state: Dictionary = checked["data"] as Dictionary
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_BACKPACK_SCRIPT,
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


func set_backpack(
	entity_id: String,
	state: Dictionary = {},
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	return attach_backpack(entity_id, state, parked, manual)


func add_item(
	entity_id: String,
	item: Dictionary,
	slot_index: int = -1,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("add_item")
	if not bool(gate.get("ok", true)):
		return gate
	if manual and not parked:
		return {"ok": false, "reason": "manual_requires_parked"}
	if slot_index < -1 or slot_index >= SLOT_COUNT:
		return {"ok": false, "reason": "invalid_backpack_slot_index"}
	var item_res: Dictionary = validate_item(item)
	if not bool(item_res.get("ok", false)):
		return item_res
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return {"ok": false, "reason": "entity_not_found"}

	var valid_u: Variant = _validation_utils()
	var current_state: Dictionary = default_state()
	var comps_var: Variant = entity.get("components", [])
	if comps_var is Array:
		for raw_c: Variant in comps_var as Array:
			if raw_c is Dictionary and str(valid_u.component_id_from_script(str((raw_c as Dictionary).get("script", "")))) == "backpack":
				var st_var: Variant = (raw_c as Dictionary).get("state", {})
				if st_var is Dictionary and not (st_var as Dictionary).is_empty():
					var st_budget: Array = [32768, false]
					current_state = _safe_clone_dict(st_var as Dictionary, 0, [], st_budget)
					if bool(st_budget[1]):
						return {"ok": false, "reason": "backpack_state_too_large"}
				break

	var raw_slots: Variant = current_state.get("slots", {})
	var slots: Dictionary = {}
	if raw_slots is Dictionary:
		var slots_budget: Array = [32768, false]
		slots = _safe_clone_dict(raw_slots as Dictionary, 0, [], slots_budget)
		if bool(slots_budget[1]):
			return {"ok": false, "reason": "backpack_state_too_large"}
	var target_idx: int = slot_index
	if target_idx == -1:
		for i: int in range(SLOT_COUNT):
			if not slots.has(str(i)):
				target_idx = i
				break
	if target_idx < 0 or target_idx >= SLOT_COUNT:
		return {"ok": false, "reason": "backpack_full_or_invalid_slot"}
	slots[str(target_idx)] = item_res["data"]
	current_state["slots"] = slots
	return _attach_backpack_impl(entity_id, current_state, parked, manual, gate)


func _lookup_entity(entity_id: String) -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or entity_id.is_empty():
		return {}
	if wb.has_method("get_entity"):
		return wb.get_entity(entity_id)
	return {}


func _check_gate(action: String) -> Dictionary:
	if _module_registry != null:
		return _module_registry.check_and_warn(MODULE_ID, action)
	return {"ok": true, "enabled": false, "policy": "preserve", "skipped": false}


func _warn(message: String) -> void:
	if _log_bus != null:
		_log_bus.warn(MODULE_ID, message)
	else:
		push_warning("[FuSdk/WARNING][%s] %s" % [MODULE_ID, message])


func _is_valid_data_value(value: Variant, depth: int, active_stack: Array = [], budget: Array = []) -> bool:
	var active_budget: Array = budget if not budget.is_empty() else [4096]
	if depth > 32:
		return false
	if int(active_budget[0]) <= 0:
		return false
	active_budget[0] = int(active_budget[0]) - 1
	match typeof(value):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_STRING, TYPE_STRING_NAME, TYPE_NODE_PATH, \
		TYPE_VECTOR2I, TYPE_VECTOR3I, TYPE_VECTOR4I, TYPE_RECT2I, \
		TYPE_PACKED_BYTE_ARRAY, TYPE_PACKED_INT32_ARRAY, TYPE_PACKED_INT64_ARRAY, TYPE_PACKED_STRING_ARRAY:
			return true
		TYPE_FLOAT:
			return is_finite(float(value))
		TYPE_VECTOR2:
			return (value as Vector2).is_finite()
		TYPE_VECTOR3:
			return (value as Vector3).is_finite()
		TYPE_VECTOR4:
			return (value as Vector4).is_finite()
		TYPE_QUATERNION:
			return (value as Quaternion).is_finite()
		TYPE_COLOR:
			var col: Color = value as Color
			return is_finite(col.r) and is_finite(col.g) and is_finite(col.b) and is_finite(col.a)
		TYPE_RECT2:
			var r2: Rect2 = value as Rect2
			return r2.position.is_finite() and r2.size.is_finite()
		TYPE_AABB:
			var ab: AABB = value as AABB
			return ab.position.is_finite() and ab.size.is_finite()
		TYPE_TRANSFORM2D:
			var t2: Transform2D = value as Transform2D
			return t2.x.is_finite() and t2.y.is_finite() and t2.origin.is_finite()
		TYPE_PLANE:
			var pl: Plane = value as Plane
			return pl.normal.is_finite() and is_finite(pl.d)
		TYPE_BASIS:
			var bs: Basis = value as Basis
			return bs.x.is_finite() and bs.y.is_finite() and bs.z.is_finite()
		TYPE_TRANSFORM3D:
			var t3: Transform3D = value as Transform3D
			return t3.basis.x.is_finite() and t3.basis.y.is_finite() and t3.basis.z.is_finite() and t3.origin.is_finite()
		TYPE_PROJECTION:
			var pr: Projection = value as Projection
			return pr.x.is_finite() and pr.y.is_finite() and pr.z.is_finite() and pr.w.is_finite()
		TYPE_DICTIONARY:
			var d: Dictionary = value as Dictionary
			for s: Variant in active_stack:
				if is_same(s, d):
					return false
			if depth == 32:
				return d.is_empty()
			active_stack.append(d)
			for k: Variant in d.keys():
				if not _is_valid_data_value(k, depth + 1, active_stack, active_budget) or not _is_valid_data_value(d[k], depth + 1, active_stack, active_budget):
					active_stack.pop_back()
					return false
			active_stack.pop_back()
			return true
		TYPE_ARRAY:
			var arr: Array = value as Array
			for s: Variant in active_stack:
				if is_same(s, arr):
					return false
			if depth == 32:
				return arr.is_empty()
			active_stack.append(arr)
			for item: Variant in arr:
				if not _is_valid_data_value(item, depth + 1, active_stack, active_budget):
					active_stack.pop_back()
					return false
			active_stack.pop_back()
			return true
		TYPE_PACKED_FLOAT32_ARRAY:
			if depth == 32 and not (value as PackedFloat32Array).is_empty():
				return false
			for f: float in value as PackedFloat32Array:
				if not is_finite(f):
					return false
			return true
		TYPE_PACKED_FLOAT64_ARRAY:
			if depth == 32 and not (value as PackedFloat64Array).is_empty():
				return false
			for f: float in value as PackedFloat64Array:
				if not is_finite(f):
					return false
			return true
		TYPE_PACKED_VECTOR2_ARRAY:
			if depth == 32 and not (value as PackedVector2Array).is_empty():
				return false
			for v: Vector2 in value as PackedVector2Array:
				if not v.is_finite():
					return false
			return true
		TYPE_PACKED_VECTOR3_ARRAY:
			if depth == 32 and not (value as PackedVector3Array).is_empty():
				return false
			for v: Vector3 in value as PackedVector3Array:
				if not v.is_finite():
					return false
			return true
		TYPE_PACKED_VECTOR4_ARRAY:
			if depth == 32 and not (value as PackedVector4Array).is_empty():
				return false
			for v: Vector4 in value as PackedVector4Array:
				if not v.is_finite():
					return false
			return true
		TYPE_PACKED_COLOR_ARRAY:
			if depth == 32 and not (value as PackedColorArray).is_empty():
				return false
			for c: Color in value as PackedColorArray:
				if not (is_finite(c.r) and is_finite(c.g) and is_finite(c.b) and is_finite(c.a)):
					return false
			return true
	return false


## 保持白盒测试兼容性：委托 utils/bounded_cloner.gd 执行无记忆化轻量有界字典深拷贝。
func _safe_clone_dict(d: Dictionary, depth: int = 0, stack: Array = [], budget: Array = []) -> Dictionary:
	return _bounded_cloner().simple_clone_dict(d, depth, stack, budget)
