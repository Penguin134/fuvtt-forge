extends RefCounted
## Fu vtt 原生核心插件 SDK：feature_floor_system（楼层数据与探索记录）
##
## 对应官方源码：scenes/extension/feature_floor_system.gd、
## scenes/systems/floors/floor_snapshot_identity.gd、floor_exploration.gd、world_snapshot.gd。
## 注意：官方 catalog.floors[i] 仅允许精确 4 键 ["id", "floor_uid", "name", "color"]，严禁添加 elevation 字段。

const MODULE_ID: String = "feature_floor_system"
const FLOOR_IDENTITY_VERSION: int = 1
const MAX_FLOORS: int = 512
const MAX_NAME_LENGTH: int = 96
const UI_RENAME_MAX_LENGTH: int = 24
const MAX_PLAYER_ID_LENGTH: int = 128
const DEFAULT_FLOOR_COLOR: Color = Color(0.28, 0.65, 0.40)

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


func add_floor(
	name: String,
	color: Color = DEFAULT_FLOOR_COLOR,
	activate: bool = false
) -> String:
	var gate: Dictionary = _check_gate("add_floor")
	if not bool(gate.get("ok", true)):
		return ""
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	var safe_color: Color = color if bool(_value_utils().is_finite_color(color)) else DEFAULT_FLOOR_COLOR
	return str(wb.add_floor(name, safe_color, activate))


func set_active_floor(floor_uid: String) -> bool:
	var gate: Dictionary = _check_gate("set_active_floor")
	if not bool(gate.get("ok", true)):
		return false
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return false
	return bool(wb.set_active_floor(floor_uid))


func rename_floor(floor_uid: String, new_name: String) -> bool:
	var gate: Dictionary = _check_gate("rename_floor")
	if not bool(gate.get("ok", true)):
		return false
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return false
	var clean_name: String = str(_validation_utils().strip_leading_bom(new_name))
	if not _is_valid_name(clean_name):
		return false
	if clean_name.length() > UI_RENAME_MAX_LENGTH and _log_bus != null:
		_log_bus.debug(MODULE_ID, "楼层名称超过交互 UI 建议上限（%d > %d 字符），快照保留至 %d 字符上限。" % [
			clean_name.length(),
			UI_RENAME_MAX_LENGTH,
			MAX_NAME_LENGTH,
		])
	return bool(wb.rename_floor(floor_uid, clean_name))


func set_floor_color(floor_uid: String, color: Color) -> bool:
	var gate: Dictionary = _check_gate("set_floor_color")
	if not bool(gate.get("ok", true)):
		return false
	var val_u: Variant = _value_utils()
	if floor_uid.is_empty() or not bool(val_u.is_finite_color(color)):
		return false
	var world: Dictionary = _get_world()
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return false
	var floors_var: Variant = (catalog_var as Dictionary).get("floors", null)
	if not (floors_var is Array):
		return false
	for raw_floor: Variant in floors_var as Array:
		if raw_floor is Dictionary and str(val_u.as_str((raw_floor as Dictionary).get("floor_uid", ""))) == floor_uid:
			(raw_floor as Dictionary)["color"] = color
			return true
	return false


func reorder_floor(floor_uid: String, target_index: int) -> bool:
	var gate: Dictionary = _check_gate("reorder_floor")
	if not bool(gate.get("ok", true)):
		return false
	if floor_uid.is_empty():
		return false
	var world: Dictionary = _get_world()
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return false
	var floors_var: Variant = (catalog_var as Dictionary).get("floors", null)
	if not (floors_var is Array):
		return false
	var val_u: Variant = _value_utils()
	var floors: Array = floors_var
	var current_index: int = -1
	for i: int in range(floors.size()):
		if floors[i] is Dictionary and str(val_u.as_str((floors[i] as Dictionary).get("floor_uid", ""))) == floor_uid:
			current_index = i
			break
	if current_index < 0:
		return false
	var clamped_target: int = clampi(target_index, 0, floors.size() - 1)
	if clamped_target != current_index:
		var moved: Variant = floors[current_index]
		floors.remove_at(current_index)
		floors.insert(clamped_target, moved)
	for i: int in range(floors.size()):
		if floors[i] is Dictionary:
			(floors[i] as Dictionary)["id"] = i
	return true


func get_active_floor_uid() -> String:
	var wb: RefCounted = _wb()
	if wb == null:
		return ""
	return str(wb.get_active_floor_uid())


func get_floors() -> Array:
	var world: Dictionary = _get_world()
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return []
	var floors_var: Variant = (catalog_var as Dictionary).get("floors", null)
	if floors_var is Array:
		return _safe_clone_array(floors_var as Array)
	return []


func get_floor(floor_uid: String) -> Dictionary:
	if floor_uid.is_empty():
		return {}
	var world: Dictionary = _get_world()
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return {}
	var floors_var: Variant = (catalog_var as Dictionary).get("floors", null)
	if not (floors_var is Array):
		return {}
	var val_u: Variant = _value_utils()
	for raw_floor: Variant in floors_var as Array:
		if raw_floor is Dictionary and str(val_u.as_str((raw_floor as Dictionary).get("floor_uid", ""))) == floor_uid:
			return _safe_clone_dict(raw_floor as Dictionary)
	return {}


func set_player_floor_visits(player_id: String, floor_uids: Array) -> bool:
	var gate: Dictionary = _check_gate("set_player_floor_visits")
	if not bool(gate.get("ok", true)):
		return false
	var clean_pid: String = _normalize_player_id(player_id)
	if clean_pid.is_empty():
		return false
	var world: Dictionary = _get_world()
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return false
	var catalog: Dictionary = catalog_var

	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	var known_floors: Dictionary = {}
	var floors_var: Variant = catalog.get("floors", [])
	if floors_var is Array:
		for raw_floor: Variant in floors_var as Array:
			if raw_floor is Dictionary:
				var fuid: String = str(val_u.as_str((raw_floor as Dictionary).get("floor_uid", "")))
				if not fuid.is_empty():
					known_floors[fuid] = true

	var clean_uids: Array[String] = []
	var seen: Dictionary = {}
	for raw_uid: Variant in floor_uids:
		var uid: String = str(raw_uid).strip_edges().to_lower() if (raw_uid is String or raw_uid is StringName) else ""
		if not bool(valid_u.is_valid_uid(uid)) or not known_floors.has(uid) or seen.has(uid):
			return false
		seen[uid] = true
		clean_uids.append(uid)
		if clean_uids.size() > MAX_FLOORS:
			return false

	if not (catalog.get("floor_visits", null) is Dictionary):
		catalog["floor_visits"] = {}
	var visits: Dictionary = catalog["floor_visits"]
	visits[clean_pid] = clean_uids
	return true


func get_player_floor_visits(player_id: String) -> Array:
	var clean_pid: String = _normalize_player_id(player_id)
	if clean_pid.is_empty():
		return []
	var world: Dictionary = _get_world()
	var catalog_var: Variant = world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return []
	var visits_var: Variant = (catalog_var as Dictionary).get("floor_visits", null)
	if not (visits_var is Dictionary):
		return []
	var row_var: Variant = (visits_var as Dictionary).get(clean_pid, [])
	if row_var is Array:
		return _safe_clone_array(row_var as Array)
	return []


func validate_floors(world: Dictionary = {}) -> Dictionary:
	var target_world: Dictionary = world if not world.is_empty() else _get_world()
	var errors: Array[String] = []
	if target_world.is_empty():
		return {"ok": false, "errors": ["world_empty"]}

	var catalog_var: Variant = target_world.get("catalog", null)
	if not (catalog_var is Dictionary):
		return {"ok": false, "errors": ["invalid_world_catalog"]}
	var catalog: Dictionary = catalog_var

	var fiv: Variant = catalog.get("floor_identity_version", null)
	if not (fiv is int) or int(fiv) != FLOOR_IDENTITY_VERSION:
		errors.append("invalid_floor_identity_version")

	var floors_var: Variant = catalog.get("floors", null)
	if not (floors_var is Array):
		errors.append("missing_floors_array")
		return {"ok": false, "errors": errors}
	var floors: Array = floors_var
	if floors.is_empty() or floors.size() > MAX_FLOORS:
		errors.append("invalid_floors_count")

	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	var seen_uids: Dictionary = {}
	for idx: int in range(floors.size()):
		var raw_floor: Variant = floors[idx]
		if not (raw_floor is Dictionary):
			errors.append("invalid_floor_row:%d" % idx)
			continue
		var row: Dictionary = raw_floor as Dictionary
		if row.size() != 4 or not row.has("id") or not row.has("floor_uid") or not row.has("name") or not row.has("color"):
			errors.append("invalid_floor_keys:%d" % idx)
		if not (row.get("id", null) is int) or int(row.get("id", -1)) != idx:
			errors.append("floor_id_index_mismatch:%d" % idx)
		var raw_fuid: Variant = row.get("floor_uid", "")
		var fuid: String = str(raw_fuid) if (raw_fuid is String or raw_fuid is StringName) else ""
		if not bool(valid_u.is_valid_uid(fuid)) or seen_uids.has(fuid):
			errors.append("invalid_or_duplicate_floor_uid:%d" % idx)
		else:
			seen_uids[fuid] = true
		var fname: Variant = row.get("name", null)
		if not (fname is String) or not _is_valid_name(fname as String):
			errors.append("invalid_floor_name:%d" % idx)
		var fcol: Variant = row.get("color", null)
		if not (fcol is Color) or not bool(val_u.is_finite_color(fcol as Color)):
			errors.append("invalid_floor_color:%d" % idx)

	if catalog.has("active_floor_uid"):
		var raw_act_uid: Variant = catalog.get("active_floor_uid", "")
		var active_uid: String = str(raw_act_uid) if (raw_act_uid is String or raw_act_uid is StringName) else ""
		if not seen_uids.has(active_uid):
			errors.append("invalid_active_floor_uid")

	if catalog.has("floor_visits"):
		var visits_var: Variant = catalog.get("floor_visits", null)
		if not (visits_var is Dictionary):
			errors.append("invalid_floor_visits_type")
		else:
			var visits: Dictionary = visits_var as Dictionary
			for raw_pid: Variant in visits.keys():
				if not (raw_pid is String):
					errors.append("invalid_floor_visits_player_key")
					continue
				var pid: String = str(raw_pid)
				if pid.is_empty() or pid.length() > MAX_PLAYER_ID_LENGTH or bool(valid_u.has_control_chars(pid, true)):
					errors.append("invalid_floor_visits_player_id:" + pid)
				var list_var: Variant = visits[raw_pid]
				if not (list_var is Array) or (list_var as Array).size() > MAX_FLOORS:
					errors.append("invalid_floor_visits_list:" + pid)
					continue
				for raw_vuid: Variant in list_var as Array:
					var vuid: String = str(raw_vuid) if (raw_vuid is String or raw_vuid is StringName) else ""
					if not seen_uids.has(vuid):
						errors.append("unknown_visited_floor_uid:" + vuid)

	return {
		"ok": errors.is_empty(),
		"errors": errors,
	}


func _get_world() -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null:
		return {}
	return wb.get_world()


func _normalize_player_id(raw: String) -> String:
	var trimmed: String = raw.strip_edges()
	if trimmed.is_empty() or trimmed.length() > MAX_PLAYER_ID_LENGTH or bool(_validation_utils().has_control_chars(trimmed, true)):
		return ""
	return trimmed


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


func _safe_clone_array(raw: Array) -> Array:
	var cloned: Variant = _safe_clone_via_adapter(raw)
	return cloned as Array if cloned is Array else []


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
