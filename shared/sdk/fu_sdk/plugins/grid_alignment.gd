extends RefCounted
## Fu vtt 原生可选插件 SDK：grid_alignment（网格与地图对齐 fus.grid_alignment.config v1）
##
## 对应官方源码：modules/grid_alignment/feature_grid_alignment.gd、grid_network.gd、
## scenes/candidates/grid_alignment/grid_config.gd（line_width 严格范围 [0.5, 4.0]，offset [-1e6, 1e6]）。

const MODULE_ID: String = "grid_alignment"
const MODULE_VERSION: int = 1
const SCHEMA: String = "fus.grid_alignment.config"
const VERSION: int = 1

const MIN_CELL_SIZE: float = 8.0
const MAX_CELL_SIZE: float = 4096.0
const MAX_OFFSET: float = 1000000.0
const MIN_LINE_WIDTH: float = 0.5
const MAX_LINE_WIDTH: float = 4.0

const FIELDS: Array[String] = [
	"schema",
	"version",
	"cell_size",
	"offset",
	"color",
	"line_width",
	"snap_enabled",
	"snap_strength",
]

const EDITABLE_FIELDS: Array[String] = [
	"cell_size",
	"offset",
	"color",
	"line_width",
	"snap_enabled",
	"snap_strength",
]

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


func default_config() -> Dictionary:
	return {
		"schema": SCHEMA,
		"version": VERSION,
		"cell_size": 64.0,
		"offset": [0.0, 0.0],
		"color": [0.5, 0.55, 0.65, 0.7],
		"line_width": 1.0,
		"snap_enabled": true,
		"snap_strength": 0.1,
	}


func make_config(
	cell_size: float = 64.0,
	snap_enabled: bool = true,
	offset: Vector2 = Vector2.ZERO,
	color: Color = Color(0.5, 0.55, 0.65, 0.7),
	line_width: float = 1.0,
	snap_strength: float = 0.1
) -> Dictionary:
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("make_grid_alignment_state"):
		return adapter.make_grid_alignment_state(
			cell_size,
			snap_enabled,
			offset,
			color,
			line_width,
			snap_strength
		)
	var safe_ox: float = clampf(offset.x if is_finite(offset.x) else 0.0, -MAX_OFFSET, MAX_OFFSET)
	var safe_oy: float = clampf(offset.y if is_finite(offset.y) else 0.0, -MAX_OFFSET, MAX_OFFSET)
	return {
		"schema": SCHEMA,
		"version": VERSION,
		"cell_size": clampf(cell_size if is_finite(cell_size) else 64.0, MIN_CELL_SIZE, MAX_CELL_SIZE),
		"offset": [safe_ox, safe_oy],
		"color": [
			clampf(color.r if is_finite(color.r) else 0.5, 0.0, 1.0),
			clampf(color.g if is_finite(color.g) else 0.55, 0.0, 1.0),
			clampf(color.b if is_finite(color.b) else 0.65, 0.0, 1.0),
			clampf(color.a if is_finite(color.a) else 0.7, 0.0, 1.0),
		],
		"line_width": clampf(line_width if is_finite(line_width) else 1.0, MIN_LINE_WIDTH, MAX_LINE_WIDTH),
		"snap_enabled": snap_enabled,
		"snap_strength": clampf(snap_strength if is_finite(snap_strength) else 0.1, 0.0, 1.0),
	}


func validate_config(state: Dictionary, allow_empty: bool = true) -> Dictionary:
	if state.is_empty() and allow_empty:
		return {"ok": true, "reason": "", "data": default_config()}
	if state.size() != FIELDS.size():
		return {"ok": false, "reason": "grid_config_fields_invalid"}
	for key: Variant in state.keys():
		if not (key is String) or not (str(key) in FIELDS):
			return {"ok": false, "reason": "grid_config_fields_invalid"}
	var schema_v: Variant = state.get("schema", null)
	if not (schema_v is String) or str(schema_v) != SCHEMA:
		return {"ok": false, "reason": "grid_config_schema_unsupported"}
	var ver_v: Variant = state.get("version", null)
	if not (ver_v is int) or int(ver_v) != VERSION:
		return {"ok": false, "reason": "grid_config_version_unsupported"}
	if not _number_in(state.get("cell_size", null), MIN_CELL_SIZE, MAX_CELL_SIZE):
		return {"ok": false, "reason": "grid_cell_size_invalid"}
	if not _number_array(state.get("offset", null), 2, -MAX_OFFSET, MAX_OFFSET):
		return {"ok": false, "reason": "grid_offset_invalid"}
	if not _number_array(state.get("color", null), 4, 0.0, 1.0):
		return {"ok": false, "reason": "grid_color_invalid"}
	if not _number_in(state.get("line_width", null), MIN_LINE_WIDTH, MAX_LINE_WIDTH):
		return {"ok": false, "reason": "grid_line_width_invalid"}
	if not (state.get("snap_enabled", null) is bool):
		return {"ok": false, "reason": "grid_snap_enabled_invalid"}
	if not _number_in(state.get("snap_strength", null), 0.0, 1.0):
		return {"ok": false, "reason": "grid_snap_strength_invalid"}

	var off: Array = state["offset"] as Array
	var col: Array = state["color"] as Array
	return {
		"ok": true,
		"reason": "",
		"data": {
			"schema": SCHEMA,
			"version": VERSION,
			"cell_size": float(state["cell_size"]),
			"offset": [float(off[0]), float(off[1])],
			"color": [float(col[0]), float(col[1]), float(col[2]), float(col[3])],
			"line_width": float(state["line_width"]),
			"snap_enabled": bool(state["snap_enabled"]),
			"snap_strength": float(state["snap_strength"]),
		},
	}


func configure_grid(
	cell_size: float = 64.0,
	snap_enabled: bool = true,
	offset: Vector2 = Vector2.ZERO,
	color: Color = Color(0.5, 0.55, 0.65, 0.7),
	line_width: float = 1.0,
	snap_strength: float = 0.1
) -> Dictionary:
	var gate: Dictionary = _check_gate("configure_grid")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}
	var cfg: Dictionary = make_config(cell_size, snap_enabled, offset, color, line_width, snap_strength)
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, cfg))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"config": cfg,
		"enabled": bool(gate.get("enabled", false)),
		"policy": str(gate.get("policy", "preserve")),
	}


func configure_grid_alignment(
	state_or_cell_size: Variant = 64.0,
	snap_enabled: bool = true,
	offset: Vector2 = Vector2.ZERO,
	color: Color = Color(0.5, 0.55, 0.65, 0.7),
	line_width: float = 1.0,
	snap_strength: float = 0.1
) -> Dictionary:
	if state_or_cell_size is Dictionary:
		return _configure_from_dict(state_or_cell_size as Dictionary, "configure_grid_alignment")
	if state_or_cell_size is int or state_or_cell_size is float:
		return configure_grid(
			float(state_or_cell_size),
			snap_enabled,
			offset,
			color,
			line_width,
			snap_strength
		)
	var gate: Dictionary = _check_gate("configure_grid_alignment")
	if not bool(gate.get("ok", true)):
		return gate
	return {"ok": false, "reason": "grid_config_fields_invalid"}


func set_config(state: Dictionary) -> Dictionary:
	return _configure_from_dict(state, "set_config")


func _configure_from_dict(raw_state: Dictionary, action: String) -> Dictionary:
	var gate: Dictionary = _check_gate(action)
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	for raw_k: Variant in raw_state.keys():
		if not (raw_k is String) or not (str(raw_k) in FIELDS):
			return {"ok": false, "reason": "grid_config_fields_invalid"}

	var val_u: Variant = _value_utils()
	var merged: Dictionary = default_config()
	for raw_k: Variant in raw_state.keys():
		var k: String = str(raw_k)
		var v: Variant = raw_state[raw_k]
		if k == "version":
			var vp: Dictionary = val_u.parse_int_val(v)
			merged["version"] = int(vp["value"]) if bool(vp["ok"]) else v
		elif k == "offset":
			if v is Vector2:
				var v2: Vector2 = v as Vector2
				merged["offset"] = [v2.x, v2.y]
			elif v is Array:
				merged["offset"] = (v as Array).duplicate()
			else:
				merged["offset"] = v
		elif k == "color":
			merged["color"] = val_u.coerce_color_array(v)
		else:
			merged[k] = v

	var checked: Dictionary = validate_config(merged, false)
	if not bool(checked.get("ok", false)):
		return checked
	var normalized: Dictionary = checked["data"] as Dictionary
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, normalized))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"config": normalized,
		"enabled": bool(gate.get("enabled", false)),
		"policy": str(gate.get("policy", "preserve")),
	}


func patch_config(patch: Dictionary) -> Dictionary:
	var gate: Dictionary = _check_gate("patch_config")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	for raw_k: Variant in patch.keys():
		if not (raw_k is String) or not (str(raw_k) in EDITABLE_FIELDS):
			return {"ok": false, "reason": "grid_config_field_not_editable"}

	var current: Dictionary = get_config()
	if current.is_empty():
		current = default_config()
	var cfg_budget: Array = [4096, false]
	var proposed: Dictionary = _safe_clone_dict(current, 0, [], cfg_budget)
	if bool(cfg_budget[1]):
		return {"ok": false, "reason": "grid_config_too_large"}
	var val_u: Variant = _value_utils()
	for k: Variant in patch.keys():
		var val: Variant = patch[k]
		if k == "offset" and val is Vector2:
			var v2: Vector2 = val as Vector2
			proposed["offset"] = [v2.x, v2.y]
		elif k == "color":
			proposed["color"] = val_u.coerce_color_array(val)
		else:
			proposed[k] = val

	var checked: Dictionary = validate_config(proposed, false)
	if not bool(checked.get("ok", false)):
		return checked
	var normalized: Dictionary = checked["data"] as Dictionary
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, normalized))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"config": normalized,
		"enabled": bool(gate.get("enabled", false)),
		"policy": str(gate.get("policy", "preserve")),
	}


func get_config() -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {}
	if wb.has_method("get_module_state"):
		return wb.get_module_state(MODULE_ID)
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("get_module_state"):
		return adapter.get_module_state(wb.get_world(), MODULE_ID)
	return {}


func _number_in(value: Variant, minimum: float, maximum: float) -> bool:
	if not (value is int or value is float):
		return false
	var f: float = float(value)
	return is_finite(f) and f >= minimum and f <= maximum


func _number_array(value: Variant, count: int, minimum: float, maximum: float) -> bool:
	if not (value is Array) or (value as Array).size() != count:
		return false
	for item: Variant in value as Array:
		if not _number_in(item, minimum, maximum):
			return false
	return true


func _get_adapter() -> RefCounted:
	var wb: RefCounted = _wb()
	if wb != null and wb.has_method("get_adapter"):
		return wb.get_adapter()
	return null


func _check_gate(action: String) -> Dictionary:
	if _module_registry != null:
		return _module_registry.check_and_warn(MODULE_ID, action)
	return {"ok": true, "enabled": false, "policy": "preserve", "skipped": false}


## 保持白盒测试兼容性：委托 utils/bounded_cloner.gd 执行无记忆化轻量有界字典深拷贝。
func _safe_clone_dict(d: Dictionary, depth: int = 0, stack: Array = [], budget: Array = []) -> Dictionary:
	return _bounded_cloner().simple_clone_dict(d, depth, stack, budget)
