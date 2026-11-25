extends RefCounted
## Fu vtt 原生核心插件 SDK：feature_entity_library（实体库预设与组件可用性校验）
##
## 对应官方源码：scenes/extension/feature_entity_library.gd、
## scenes/desktop/library/entity_library_store.gd、entity_library_job.gd、board_token_factory.gd。
## 注意：官方 0.0.60 实体库无 favorites 接口；EntityLibraryStore.prepare_placement()
## 会校验 preset 快照内每个组件所属模块是否已启用，未启用则返回 preset_component_unavailable。

const MODULE_ID: String = "feature_entity_library"
const LIBRARY_RECORD_VERSION: int = 1
const MAX_CLONE_VISITS: int = 2097152
const MAX_CLONE_BYTES: int = 16 * 1024 * 1024
const MIN_ENTITY_SIZE: Vector2 = Vector2(4.0, 4.0)
const KINDS: Array[String] = ["folder", "unit", "object", "map", "preset"]
const TEMPLATE_DATA_KEYS: Array[String] = [
	"id",
	"name",
	"type",
	"category",
	"size",
	"color",
	"sprite",
	"components",
	"selectable_in_select_mode",
]

const COMP_VISUAL_SCRIPT: String = "res://scenes/entities/components/comp_visual.gd"
const COMP_PERMISSION_SCRIPT: String = "res://scenes/entities/components/comp_permission.gd"
const COMP_SIMPLE_VISION_SCRIPT: String = "res://modules/simple_fog/comp_simple_vision.gd"

var _world_builder_ref: WeakRef = null
var _module_registry: RefCounted = null
var _log_bus: RefCounted = null
var _writer: RefCounted = null
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


func _dag_cloner() -> Variant:
	return _load_util_script("dag_cloner.gd")


func _value_utils() -> Variant:
	return _load_util_script("value_utils.gd")


func _validation_utils() -> Variant:
	return _load_util_script("validation_utils.gd")


func configure(
	world_builder: RefCounted,
	module_registry: RefCounted = null,
	log_bus: RefCounted = null,
	writer: RefCounted = null
) -> void:
	_world_builder_ref = weakref(world_builder) if world_builder != null else null
	_module_registry = module_registry
	_log_bus = log_bus
	if writer != null:
		_writer = writer


func _wb() -> RefCounted:
	if _world_builder_ref == null:
		return null
	var inst: Variant = _world_builder_ref.get_ref()
	return inst as RefCounted if inst is RefCounted else null


func set_writer(writer: RefCounted) -> void:
	_writer = writer


func get_writer() -> RefCounted:
	return _writer


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


func can_write_library(host: RefCounted = null) -> bool:
	if _writer == null:
		return false
	var resolved_host: RefCounted = _resolve_host(host)
	return bool(_writer.can_write_library(resolved_host))


func build_template_data(
	id: String,
	name: String,
	sprite_ref: String = "",
	size_world: Vector2 = Vector2(64.0, 64.0),
	is_unit: bool = true,
	color: Color = Color.WHITE,
	type: String = "generic",
	category: String = "library",
	extra_components: Dictionary = {}
) -> Dictionary:
	if (
		not is_finite(size_world.x)
		or not is_finite(size_world.y)
		or size_world.x < MIN_ENTITY_SIZE.x
		or size_world.y < MIN_ENTITY_SIZE.y
	):
		return {}
	var cloned_comps: Variant = _safe_clone_variant(extra_components, 0, []) if extra_components != null else {}
	var comps: Dictionary = cloned_comps as Dictionary if cloned_comps is Dictionary else {}
	if is_unit and not comps.has("unit"):
		comps["unit"] = {}
	return {
		"id": id,
		"name": name,
		"type": type,
		"category": category,
		"size": size_world,
		"color": color,
		"sprite": sprite_ref,
		"components": comps,
		"selectable_in_select_mode": is_unit,
	}


func inspect_preset_components(entry_or_record: Dictionary) -> Dictionary:
	var unavailable: Array[Dictionary] = []
	if entry_or_record.is_empty():
		return {"ok": true, "reason": "", "unavailable": unavailable}

	var snapshot: Dictionary = {}
	if entry_or_record.has("snapshot") and entry_or_record["snapshot"] is Dictionary:
		snapshot = entry_or_record["snapshot"] as Dictionary
	elif entry_or_record.has("record") and entry_or_record["record"] is Dictionary:
		var rec: Dictionary = entry_or_record["record"] as Dictionary
		if rec.has("snapshot") and rec["snapshot"] is Dictionary:
			snapshot = rec["snapshot"] as Dictionary
	elif entry_or_record.has("entities") and entry_or_record["entities"] is Array:
		snapshot = entry_or_record

	if not snapshot.is_empty():
		var entities_var: Variant = snapshot.get("entities", [])
		if entities_var is Array:
			for raw_row: Variant in entities_var as Array:
				if not (raw_row is Dictionary):
					continue
				var comps_var: Variant = (raw_row as Dictionary).get("components", [])
				if not (comps_var is Array):
					continue
				for raw_comp: Variant in comps_var as Array:
					if not (raw_comp is Dictionary):
						continue
					var raw_scr: Variant = (raw_comp as Dictionary).get("script", "")
					var comp_script: String = str(raw_scr).strip_edges() if (raw_scr is String or raw_scr is StringName) else ""
					_check_component_script(comp_script, unavailable)
	else:
		# EntityLibraryWriter 输入条目格式
		var val_utils: Variant = _value_utils()
		var creates_preset: bool = bool(val_utils.coerce_bool(entry_or_record.get("create_preset", true), true, true))
		if creates_preset:
			var vision_radius: float = float(val_utils.coerce_float(entry_or_record.get("vision_radius", 0.0), 0.0, true))
			if is_finite(vision_radius) and vision_radius > 0.0:
				_check_component_script(COMP_SIMPLE_VISION_SCRIPT, unavailable)
			var custom_comps_var: Variant = entry_or_record.get("components", [])
			if custom_comps_var is Array:
				for raw_c: Variant in custom_comps_var as Array:
					var c_script: String = ""
					if raw_c is Dictionary:
						var raw_cs: Variant = (raw_c as Dictionary).get("script", "")
						if raw_cs is String or raw_cs is StringName:
							c_script = str(raw_cs).strip_edges()
					elif raw_c is String or raw_c is StringName:
						c_script = str(raw_c).strip_edges()
					if not c_script.is_empty():
						_check_component_script(c_script, unavailable)

	return {
		"ok": unavailable.is_empty(),
		"reason": "" if unavailable.is_empty() else "preset_component_unavailable",
		"unavailable": unavailable,
	}


func validate_preset_components(record_or_snapshot: Dictionary) -> Dictionary:
	return inspect_preset_components(record_or_snapshot)


func register_entries(
	namespace_id: String,
	entries: Array,
	host: RefCounted = null,
	session: RefCounted = null,
	enabled: bool = true
) -> Dictionary:
	var gate: Dictionary = _check_gate("register_entries")
	if not bool(gate.get("ok", true)):
		return gate
	if _writer == null:
		return {"ok": false, "count": 0, "skipped": false, "reason": "entity_library_writer_unavailable"}

	var resolved_session: RefCounted = _resolve_session(session)
	var resolved_host: RefCounted = _resolve_host(host, resolved_session)
	var policy: String = _get_disabled_policy()

	var processed_entries: Array = []
	var warned_presets: Array[Dictionary] = []
	var stripped_components: Array[Dictionary] = []
	var skipped_presets: Array[Dictionary] = []

	for raw_entry: Variant in entries:
		if not (raw_entry is Dictionary):
			processed_entries.append(raw_entry)
			continue
		var cloned_entry: Variant = _safe_clone_variant(raw_entry, 0, [])
		if not (cloned_entry is Dictionary):
			processed_entries.append({})
			continue
		var entry: Dictionary = cloned_entry as Dictionary
		var inspect_res: Dictionary = inspect_preset_components(entry)
		if bool(inspect_res.get("ok", true)):
			processed_entries.append(entry)
			continue

		var val_u: Variant = _validation_utils()
		var entry_name: String = ""
		var raw_name: Variant = entry.get("name", null)
		if raw_name is String or raw_name is StringName:
			entry_name = str(val_u.strip_bom_and_edges(str(raw_name)))
		if entry_name.is_empty():
			var raw_id: Variant = entry.get("id", null)
			if raw_id is String or raw_id is StringName:
				entry_name = str(val_u.strip_bom_and_edges(str(raw_id)))
		if entry_name.is_empty():
			entry_name = "unnamed_preset"
		var unavail_list: Array = inspect_res.get("unavailable", [])
		var mod_names: Array[String] = []
		var comp_names: Array[String] = []
		for item: Variant in unavail_list:
			if item is Dictionary:
				var d: Dictionary = item as Dictionary
				var mid: String = str(d.get("module_id", "unknown"))
				var cscr: String = str(d.get("script", ""))
				if not (mid in mod_names):
					mod_names.append(mid)
				if not cscr.is_empty() and not (cscr in comp_names):
					comp_names.append(cscr)

		var warn_msg: String = "preset_component_unavailable: 预设 '%s' 包含未启用或不可用模块（%s）的组件（%s），宿主放置时将被拒绝；当前策略='%s'。" % [
			entry_name,
			", ".join(mod_names),
			", ".join(comp_names),
			policy,
		]
		_emit_warning(warn_msg, resolved_session, {
			"reason": "preset_component_unavailable",
			"entry": entry_name,
			"modules": mod_names,
			"components": comp_names,
			"policy": policy,
		})
		warned_presets.append({
			"entry": entry_name,
			"modules": mod_names,
			"components": comp_names,
			"policy": policy,
		})

		if policy == "skip":
			if float(_value_utils().coerce_float(entry.get("vision_radius", 0.0), 0.0, true)) > 0.0 and (COMP_SIMPLE_VISION_SCRIPT in comp_names):
				entry["vision_radius"] = 0.0
				stripped_components.append({
					"entry": entry_name,
					"script": COMP_SIMPLE_VISION_SCRIPT,
					"module_id": "simple_fog",
				})
			var recheck: Dictionary = inspect_preset_components(entry)
			if not bool(recheck.get("ok", true)):
				entry["create_preset"] = false
				skipped_presets.append({
					"entry": entry_name,
					"modules": mod_names,
					"components": comp_names,
				})
		processed_entries.append(entry)

	var writer_res: Dictionary = _writer.register_entries(
		namespace_id,
		processed_entries,
		resolved_host,
		resolved_session,
		enabled
	)
	var out: Dictionary = writer_res.duplicate(true)
	out["warned_presets"] = warned_presets
	out["stripped_components"] = stripped_components
	out["skipped_presets"] = skipped_presets
	return out


func register_presets(
	namespace_id: String,
	presets: Array,
	host: RefCounted = null,
	session: RefCounted = null
) -> Dictionary:
	var prepared: Array = []
	for raw_p: Variant in presets:
		if raw_p is Dictionary:
			var cloned_p: Variant = _safe_clone_variant(raw_p, 0, [])
			if cloned_p is Dictionary:
				var d: Dictionary = cloned_p as Dictionary
				if not d.has("create_preset"):
					d["create_preset"] = true
				prepared.append(d)
			else:
				prepared.append({})
		else:
			prepared.append(raw_p)
	return register_entries(namespace_id, prepared, host, session, true)


func rollback_last_registration() -> void:
	if _writer != null:
		_writer.rollback_last_registration()


func _check_component_script(comp_script: String, unavailable: Array[Dictionary]) -> void:
	if comp_script.is_empty():
		return
	if comp_script == COMP_VISUAL_SCRIPT or comp_script == COMP_PERMISSION_SCRIPT:
		return
	if _module_registry == null:
		return
	var owner_id: String = str(_module_registry.find_module_for_component(comp_script))
	if owner_id.is_empty():
		unavailable.append({
			"script": comp_script,
			"module_id": "",
			"status": "unknown",
			"reason": "preset_component_unavailable",
		})
		return
	if not bool(_module_registry.is_module_enabled(owner_id)):
		unavailable.append({
			"script": comp_script,
			"module_id": owner_id,
			"status": str(_module_registry.get_module_status(owner_id)),
			"reason": "preset_component_unavailable",
		})


func _get_disabled_policy() -> String:
	if _module_registry != null and _module_registry.has_method("get_disabled_module_policy"):
		return str(_module_registry.get_disabled_module_policy())
	return "preserve"


func _resolve_session(explicit_session: RefCounted) -> RefCounted:
	if explicit_session != null:
		return explicit_session
	var wb: RefCounted = _wb()
	if wb != null and wb.has_method("get_session"):
		return wb.get_session()
	return null


func _resolve_host(explicit_host: RefCounted, resolved_session: RefCounted = null) -> RefCounted:
	if explicit_host != null:
		return explicit_host
	var sess: RefCounted = resolved_session if resolved_session != null else _resolve_session(null)
	if sess != null and sess.has_method("get_host"):
		return sess.get_host()
	return null


func _check_gate(action: String) -> Dictionary:
	if _module_registry != null:
		return _module_registry.check_and_warn(MODULE_ID, action)
	return {"ok": true}


func _emit_warning(
	message: String,
	session: RefCounted,
	context: Dictionary
) -> void:
	if _log_bus != null:
		_log_bus.warn(MODULE_ID, message, context)
		if not bool(_log_bus.has_import_host()) and session != null:
			var sess_logger: Variant = session.get_logger() if session.has_method("get_logger") else null
			if sess_logger != _log_bus and session.has_method("add_warning"):
				session.add_warning(message)
		return
	if session != null and session.has_method("add_warning"):
		session.add_warning(message)
	push_warning("[FuSdk/WARNING][%s] %s" % [MODULE_ID, message])


## 复用 DagCloner 对实体库模板与预设条目执行 16 MiB 有界深拷贝。
func _safe_clone_variant(
	value: Variant,
	depth: int = 0,
	active_stack: Array = [],
	visit_budget: Array = []
) -> Variant:
	return _dag_cloner().safe_clone_variant(value, depth, active_stack, visit_budget, MAX_CLONE_BYTES)
