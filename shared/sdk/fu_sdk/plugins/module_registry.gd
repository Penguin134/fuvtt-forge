extends RefCounted
## Fu vtt 原生功能模块注册表与 R2 未启用检测/警告引擎
##
## 收录官方 DesktopFeatureCatalog 全部 30 个目录模块（9 核心 + 21 可选）
## 及 3 个未入正式目录的候选模块（entity_notes / music_board / module_example），
## 提供声明式启用状态、FeatureManager 运行时快照探测、Playtest 屏蔽标识、
## 组件脚本反查与 R2 警告/策略执行（preserve vs skip）。

const POLICY_PRESERVE: String = "preserve"
const POLICY_SKIP: String = "skip"

const STATUS_CORE: String = "core"
const STATUS_ENABLED: String = "enabled"
const STATUS_DISABLED: String = "disabled"
const STATUS_PLAYTEST_BLOCKED: String = "playtest_blocked"
const STATUS_UNCALOGUED_CANDIDATE: String = "uncatalogued_candidate"
const STATUS_UNKNOWN: String = "unknown"
const MAX_CLONE_VISITS: int = 2097152
const MAX_CLONE_BYTES: int = 16 * 1024 * 1024

const PLAYTEST_BLOCKED_REASON_V061: String = "Playtest v0.0.61-v0.0.62 blocked activation while preserving saved state"

var _log_bus: RefCounted = null
var _session: RefCounted = null
var _catalog: Dictionary = {}
var _catalog_order: Array[String] = []
var _aliases: Dictionary = {}
var _component_to_module: Dictionary = {}
var _enabled_optional: Dictionary = {}
var _core_probe_disabled: Dictionary = {}
var _blocked_overrides: Dictionary = {}
var _disabled_policy: String = POLICY_PRESERVE
var _last_probe_report: Dictionary = {}
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


func _init(log_bus: RefCounted = null, session: RefCounted = null) -> void:
	_log_bus = log_bus
	_session = session
	_build_authoritative_catalog()


func configure(log_bus: RefCounted = null, session: RefCounted = null) -> void:
	_log_bus = log_bus
	_session = session


func set_logger(log_bus: RefCounted) -> void:
	_log_bus = log_bus


func get_logger() -> RefCounted:
	return _log_bus


func set_session(session: RefCounted) -> void:
	_session = session


func resolve_module_id(module_id: String) -> String:
	var clean_id: String = module_id.strip_edges().to_lower()
	if _catalog.has(clean_id):
		return clean_id
	if _aliases.has(clean_id):
		return str(_aliases[clean_id])
	return clean_id


func set_disabled_module_policy(policy: String) -> bool:
	var clean: String = policy.strip_edges().to_lower()
	if clean != POLICY_PRESERVE and clean != POLICY_SKIP:
		return false
	_disabled_policy = clean
	return true


func get_disabled_module_policy() -> String:
	return _disabled_policy


func set_enabled_modules(modules: Array) -> void:
	_enabled_optional.clear()
	_core_probe_disabled.clear()
	for raw_item: Variant in modules:
		var raw_id: String = ""
		var item_enabled: bool = true
		if raw_item is Dictionary:
			var d: Dictionary = raw_item as Dictionary
			var id_var: Variant = d.get("id", "")
			raw_id = str(id_var) if (id_var is String or id_var is StringName) else ""
			item_enabled = bool(_value_utils().coerce_bool(d.get("enabled", false), false, true))
		elif raw_item is String or raw_item is StringName:
			raw_id = str(raw_item)
		else:
			continue
		var canonical: String = resolve_module_id(raw_id)
		if canonical.is_empty() or not _catalog.has(canonical):
			continue
		var entry: Dictionary = _catalog[canonical]
		if bool(entry.get("core", false)):
			continue
		if bool(entry.get("candidate", false)):
			continue
		if item_enabled:
			_enabled_optional[canonical] = true
		else:
			_enabled_optional.erase(canonical)


func set_module_enabled(module_id: String, enabled: bool) -> bool:
	var canonical: String = resolve_module_id(module_id)
	if not _catalog.has(canonical):
		return false
	var entry: Dictionary = _catalog[canonical]
	if bool(entry.get("core", false)):
		return enabled
	if bool(entry.get("candidate", false)):
		return not enabled
	if enabled:
		_enabled_optional[canonical] = true
	else:
		_enabled_optional.erase(canonical)
	return true


func set_module_blocked(
	module_id: String,
	blocked: bool,
	reason: String = ""
) -> bool:
	var canonical: String = resolve_module_id(module_id)
	if not _catalog.has(canonical):
		return false
	var entry: Dictionary = _catalog[canonical]
	if bool(entry.get("core", false)) and blocked:
		return false
	_blocked_overrides[canonical] = {
		"blocked": blocked,
		"reason": reason.strip_edges(),
	}
	return true


func is_module_blocked(module_id: String) -> bool:
	var canonical: String = resolve_module_id(module_id)
	if not _catalog.has(canonical):
		return false
	if _blocked_overrides.has(canonical):
		return bool((_blocked_overrides[canonical] as Dictionary).get("blocked", false))
	return bool((_catalog[canonical] as Dictionary).get("playtest_blocked", false))


func get_blocked_reason(module_id: String) -> String:
	var canonical: String = resolve_module_id(module_id)
	if not _catalog.has(canonical):
		return ""
	if _blocked_overrides.has(canonical):
		var ov: Dictionary = _blocked_overrides[canonical] as Dictionary
		if not bool(ov.get("blocked", false)):
			return ""
		var ov_reason: String = str(ov.get("reason", ""))
		if not ov_reason.is_empty():
			return ov_reason
	var entry: Dictionary = _catalog[canonical] as Dictionary
	if bool(entry.get("playtest_blocked", false)):
		return str(entry.get("blocked_reason", ""))
	return ""


func is_module_enabled(module_id: String) -> bool:
	var status: String = get_module_status(module_id)
	return status == STATUS_CORE or status == STATUS_ENABLED


func get_module_status(module_id: String) -> String:
	var canonical: String = resolve_module_id(module_id)
	if not _catalog.has(canonical):
		return STATUS_UNKNOWN
	var entry: Dictionary = _catalog[canonical] as Dictionary
	if bool(entry.get("core", false)):
		if bool(_core_probe_disabled.get(canonical, false)):
			return STATUS_DISABLED
		return STATUS_CORE
	if is_module_blocked(canonical):
		return STATUS_PLAYTEST_BLOCKED
	if bool(entry.get("candidate", false)):
		return STATUS_UNCALOGUED_CANDIDATE
	if bool(_enabled_optional.get(canonical, false)):
		return STATUS_ENABLED
	return STATUS_DISABLED


func get_module_entry(module_id: String) -> Dictionary:
	var canonical: String = resolve_module_id(module_id)
	if not _catalog.has(canonical):
		return {}
	var out: Dictionary = (_catalog[canonical] as Dictionary).duplicate(true)
	out["status"] = get_module_status(canonical)
	out["enabled"] = is_module_enabled(canonical)
	out["playtest_blocked"] = is_module_blocked(canonical)
	out["blocked_reason"] = get_blocked_reason(canonical)
	return out


func list_modules(include_candidates: bool = true) -> Array:
	var out: Array = []
	for canonical: String in _catalog_order:
		var entry: Dictionary = _catalog[canonical] as Dictionary
		if not include_candidates and bool(entry.get("candidate", false)):
			continue
		out.append(get_module_entry(canonical))
	return out


func find_module_for_component(script_path: String) -> String:
	var clean: String = script_path.strip_edges()
	if clean.is_empty():
		return ""
	return str(_component_to_module.get(clean, ""))


func get_missing_dependencies(module_id: String) -> Array[String]:
	var canonical: String = resolve_module_id(module_id)
	if not _catalog.has(canonical):
		return []
	var entry: Dictionary = _catalog[canonical] as Dictionary
	var missing: Array[String] = []
	var reqs_var: Variant = entry.get("requires", [])
	if reqs_var is Array:
		for raw_req: Variant in reqs_var as Array:
			var req_id: String = resolve_module_id(str(raw_req))
			if not is_module_enabled(req_id):
				missing.append(req_id)
	return missing


func probe_feature_manager(feature_manager: Variant) -> bool:
	_last_probe_report = {}
	if feature_manager == null:
		_last_probe_report = {"ok": false, "reason": "null_feature_manager", "probed_rows": 0}
		return false

	var snap: Dictionary = {}
	var choices_arr: Array = []
	var source_kind: String = ""

	if feature_manager is Dictionary:
		var cloned_fm: Variant = _safe_clone_variant(feature_manager, 0, [])
		if cloned_fm is Dictionary:
			snap = cloned_fm as Dictionary
		source_kind = "snapshot_dict"
	elif feature_manager is Object:
		var obj: Object = feature_manager as Object
		if obj.has_method("snapshot"):
			var raw_snap: Variant = obj.call("snapshot")
			if raw_snap is Dictionary:
				var cloned_snap: Variant = _safe_clone_variant(raw_snap, 0, [])
				if cloned_snap is Dictionary:
					snap = cloned_snap as Dictionary
				source_kind = "feature_manager_snapshot"
		if snap.is_empty() and obj.has_method("module_choices"):
			var raw_choices: Variant = obj.call("module_choices")
			if raw_choices is Array:
				var cloned_choices: Variant = _safe_clone_variant(raw_choices, 0, [])
				if cloned_choices is Array:
					choices_arr = cloned_choices as Array
				source_kind = "feature_manager_choices"
	else:
		_last_probe_report = {"ok": false, "reason": "unsupported_probe_source", "probed_rows": 0}
		return false

	var rows_var: Variant = snap.get("rows", null)
	if rows_var is Array:
		var rows: Array = rows_var as Array
		_enabled_optional.clear()
		_core_probe_disabled.clear()
		var probed_ids: Array[String] = []
		for raw_row: Variant in rows:
			if not (raw_row is Dictionary):
				continue
			var row: Dictionary = raw_row as Dictionary
			var raw_row_id: Variant = row.get("id", "")
			var canonical: String = resolve_module_id(str(raw_row_id) if (raw_row_id is String or raw_row_id is StringName) else "")
			if canonical.is_empty() or not _catalog.has(canonical):
				continue
			probed_ids.append(canonical)
			var entry: Dictionary = _catalog[canonical] as Dictionary
			var val_utils: Variant = _value_utils()
			var row_enabled: bool = bool(val_utils.coerce_bool(row.get("enabled", false), false, true))
			var raw_reason: Variant = row.get("activation_blocked_reason", null)
			if not (raw_reason is String or raw_reason is StringName):
				raw_reason = row.get("blocked_reason", null)
			var blocked_reason: String = str(raw_reason).strip_edges() if (raw_reason is String or raw_reason is StringName) else ""
			var row_blocked: bool = bool(val_utils.coerce_bool(row.get("playtest_blocked", false), false, true))
			if row.has("playtest_blocked") and row_blocked:
				set_module_blocked(canonical, true, blocked_reason)
			elif not blocked_reason.is_empty():
				set_module_blocked(canonical, true, blocked_reason)
			elif (row.has("activation_blocked_reason") or row.has("blocked_reason") or row.has("playtest_blocked")) and blocked_reason.is_empty() and not row_blocked:
				set_module_blocked(canonical, false, "")

			if bool(entry.get("core", false)):
				if not row_enabled:
					_core_probe_disabled[canonical] = true
				else:
					_core_probe_disabled.erase(canonical)
			elif bool(entry.get("candidate", false)):
				pass
			else:
				if row_enabled:
					_enabled_optional[canonical] = true
				else:
					_enabled_optional.erase(canonical)

		var blockers_var: Variant = snap.get("campaign_blockers", [])
		_last_probe_report = {
			"ok": true,
			"source": source_kind,
			"probed_rows": probed_ids.size(),
			"healthy": bool(_value_utils().coerce_bool(snap.get("healthy", true), true, true)),
			"campaign_blockers": blockers_var if blockers_var is Array else [],
		}
		return true

	if source_kind == "feature_manager_choices":
		set_enabled_modules(choices_arr)
		_last_probe_report = {
			"ok": true,
			"source": source_kind,
			"probed_rows": choices_arr.size(),
			"healthy": true,
			"campaign_blockers": [],
		}
		return true

	_last_probe_report = {"ok": false, "reason": "missing_rows_or_choices", "probed_rows": 0}
	return false


func get_last_probe_report() -> Dictionary:
	var cloned: Variant = _safe_clone_variant(_last_probe_report, 0, [])
	return cloned as Dictionary if cloned is Dictionary else {}


## 复用 DagCloner 对 FeatureManager 快照及报告执行 16 MiB 有界深拷贝。
func _safe_clone_variant(
	value: Variant,
	depth: int = 0,
	active_stack: Array = [],
	visit_budget: Array = []
) -> Variant:
	return _dag_cloner().safe_clone_variant(value, depth, active_stack, visit_budget, MAX_CLONE_BYTES)


func check_and_warn(module_id: String, action: String = "") -> Dictionary:
	var canonical: String = resolve_module_id(module_id)
	var status: String = get_module_status(canonical)
	if status == STATUS_CORE or status == STATUS_ENABLED:
		var missing_deps: Array[String] = get_missing_dependencies(canonical)
		if not missing_deps.is_empty():
			var dep_msg: String = "原生模块 '%s' 已启用但依赖模块未开启（missing_requires=%s, action=%s, policy=%s）。" % [
				canonical,
				", ".join(missing_deps),
				action if not action.is_empty() else "invoke",
				_disabled_policy,
			]
			_emit_warning(dep_msg, {
				"module_id": canonical,
				"status": status,
				"policy": _disabled_policy,
				"action": action,
				"missing_requires": missing_deps,
			})
		return {
			"ok": true,
			"enabled": true,
			"module_id": canonical,
			"status": status,
			"policy": _disabled_policy,
			"skipped": false,
		}

	var action_label: String = action if not action.is_empty() else "sdk_call"
	var reason_detail: String = get_blocked_reason(canonical)
	var detail_suffix: String = ("（%s）" % reason_detail) if not reason_detail.is_empty() else ""
	var msg: String = "原生模块 '%s' 当前不可用（status=%s, policy=%s, action=%s）%s：调用将按 '%s' 策略处理。" % [
		canonical,
		status,
		_disabled_policy,
		action_label,
		detail_suffix,
		_disabled_policy,
	]
	_emit_warning(msg, {
		"module_id": canonical,
		"status": status,
		"policy": _disabled_policy,
		"action": action_label,
		"blocked_reason": reason_detail,
	})

	if _disabled_policy == POLICY_SKIP:
		return {
			"ok": false,
			"enabled": false,
			"module_id": canonical,
			"status": status,
			"policy": _disabled_policy,
			"skipped": true,
			"reason": "module_disabled:" + canonical,
			"warning": msg,
		}

	return {
		"ok": true,
		"enabled": false,
		"module_id": canonical,
		"status": status,
		"policy": _disabled_policy,
		"skipped": false,
		"warning": msg,
	}


func _emit_warning(message: String, context: Dictionary) -> void:
	if _log_bus != null:
		var logged: Dictionary = _log_bus.warn("module_registry", message, context)
		if logged.is_empty():
			var forwarded_via_bus: bool = false
			if bool(_log_bus.has_import_host()) and _log_bus.has_method("forward_host_warning"):
				_log_bus.forward_host_warning("module_registry", message)
				forwarded_via_bus = true
			if not forwarded_via_bus and _session != null:
				var sess_logger: Variant = _session.get_logger() if _session.has_method("get_logger") else null
				if (
					sess_logger != null
					and sess_logger != _log_bus
					and bool(sess_logger.has_import_host())
					and sess_logger.has_method("forward_host_warning")
				):
					sess_logger.forward_host_warning("module_registry", message)
					forwarded_via_bus = true
				elif not bool(_log_bus.has_import_host()):
					var host_obj: Variant = _session.get_host() if _session.has_method("get_host") else null
					var adp_obj: Variant = _session.get_adapter() if _session.has_method("get_adapter") else null
					if adp_obj != null and adp_obj.has_method("add_warning"):
						adp_obj.add_warning(host_obj, message)
					elif host_obj != null and host_obj.has_method("warn"):
						host_obj.warn(message)
			if bool(_log_bus.is_emit_to_engine()):
				push_warning("[FuSdk/WARNING][module_registry] " + message)
			return
		if not bool(_log_bus.has_import_host()) and _session != null:
			var sess_logger: Variant = _session.get_logger() if _session.has_method("get_logger") else null
			if sess_logger != _log_bus and _session.has_method("add_warning"):
				_session.add_warning(message)
		return
	if _session != null and _session.has_method("add_warning"):
		_session.add_warning(message)
	push_warning("[FuSdk/WARNING][module_registry] " + message)


func _register(entry: Dictionary) -> void:
	var canonical: String = str(entry["id"])
	_catalog[canonical] = entry
	_catalog_order.append(canonical)
	var aliases_var: Variant = entry.get("aliases", [])
	if aliases_var is Array:
		for raw_alias: Variant in aliases_var as Array:
			var alias_str: String = str(raw_alias).strip_edges().to_lower()
			if not alias_str.is_empty():
				_aliases[alias_str] = canonical
	var comps_var: Variant = entry.get("component_scripts", [])
	if comps_var is Array:
		for raw_comp: Variant in comps_var as Array:
			var comp_path: String = str(raw_comp).strip_edges()
			if not comp_path.is_empty():
				_component_to_module[comp_path] = canonical


func _entry(
	id: String,
	display_name: String,
	core: bool,
	default_enabled: bool,
	version: int,
	network_version: int,
	requires: Array,
	conflicts: Array,
	path: String,
	world_module_key: String = "",
	component_scripts: Array = [],
	floor_content_records: String = "",
	stateless: bool = false,
	runtime_only: bool = false,
	candidate: bool = false,
	playtest_blocked: bool = false,
	blocked_reason: String = "",
	services: Array = [],
	aliases: Array = []
) -> Dictionary:
	return {
		"id": id,
		"display_name": display_name,
		"core": core,
		"default_enabled": default_enabled,
		"version": version,
		"network_version": network_version,
		"requires": requires.duplicate(),
		"conflicts": conflicts.duplicate(),
		"path": path,
		"world_module_key": world_module_key,
		"component_scripts": component_scripts.duplicate(),
		"floor_content_records": floor_content_records,
		"stateless": stateless,
		"runtime_only": runtime_only,
		"candidate": candidate,
		"playtest_blocked": playtest_blocked,
		"blocked_reason": blocked_reason,
		"services": services.duplicate(),
		"aliases": aliases.duplicate(),
	}


func _build_authoritative_catalog() -> void:
	_catalog.clear()
	_catalog_order.clear()
	_aliases.clear()
	_component_to_module.clear()

	# 9 个核心模块（DesktopFeatureCatalog.core_entries）
	_register(_entry(
		"feature_networking", "联机桥接", true, true, 1, 0,
		[], [], "res://scenes/extension/feature_networking.tscn",
		"", [], "", true, true, false, false, "", ["net"]
	))
	_register(_entry(
		"feature_component_sync", "组件同步", true, true, 1, 0,
		["feature_networking", "feature_layer_stack"], [], "res://scenes/extension/feature_component_sync.tscn",
		"", [], "", true, true, false, false, "", ["component_sync"]
	))
	_register(_entry(
		"feature_edit_mode", "编辑模式", true, true, 1, 0,
		[], [], "res://scenes/extension/feature_edit_mode.tscn",
		"", ["res://scenes/entities/components/comp_unit.gd"], "", false, false, false, false, "", ["mode_bar"]
	))
	_register(_entry(
		"feature_floor_system", "楼层数据", true, true, 1, 0,
		[], [], "res://scenes/extension/feature_floor_system.tscn",
		"", [], "", false, false, false, false, "", ["floor_system"]
	))
	_register(_entry(
		"feature_layer_stack", "场景结构", true, true, 1, 0,
		["feature_floor_system"], [], "res://scenes/extension/feature_layer_stack.tscn",
		"", [], "", false, false, false, false, "", ["layer_stack"]
	))
	_register(_entry(
		"feature_obstacle_authoring", "障碍物编辑", true, true, 1, 0,
		["feature_edit_mode", "feature_layer_stack"], [], "res://modules/obstacle_authoring/feature_obstacle_authoring.tscn",
		"", ["res://modules/obstacle_authoring/comp_obstacle.gd"], "", false, false, false, false, "", ["obstacle_authoring"]
	))
	_register(_entry(
		"feature_debug_hooks", "事件计数", true, true, 1, 0,
		[], [], "res://scenes/extension/feature_debug_hooks.tscn",
		"", [], "", true, true, false, false, "", ["debug_hooks"]
	))
	_register(_entry(
		"feature_component_library", "组件库", true, true, 1, 0,
		["feature_edit_mode"], [], "res://scenes/extension/feature_component_library.tscn",
		"", [], "", true, true, false, false, "", ["component_brush"]
	))
	_register(_entry(
		"feature_entity_library", "实体库", true, true, 1, 0,
		["feature_edit_mode"], [], "res://scenes/extension/feature_entity_library.tscn",
		"", [], "", false, false, false, false, "", ["entity_placement"]
	))

	# 21 个可选模块（DesktopFeatureCatalog.optional_entries）
	_register(_entry(
		"campaign_time", "战役世界时间", false, false, 1, 1,
		["feature_component_sync"], [], "res://modules/campaign_time/feature.tscn",
		"campaign_time", [], "", false, false, false, true, PLAYTEST_BLOCKED_REASON_V061, []
	))
	_register(_entry(
		"image_flip", "翻转", false, false, 1, 1,
		["feature_edit_mode", "feature_component_sync"], [], "res://modules/image_flip/feature_image_flip.tscn",
		"", ["res://modules/image_flip/comp_image_flip.gd"], "", false, false, false, false, "", []
	))
	_register(_entry(
		"drag_movement", "角色拖拽（匀速）", false, false, 1, 3,
		["feature_edit_mode", "feature_component_sync", "feature_obstacle_authoring"], [], "res://modules/drag_movement/feature_drag_movement.tscn",
		"drag_movement", ["res://modules/drag_movement/comp_drag_speed.gd"], "", false, false, false, false, "", []
	))
	_register(_entry(
		"drawing", "协作绘画", false, false, 1, 10,
		["feature_layer_stack", "feature_edit_mode", "feature_component_sync"], [], "res://modules/drawing/drawing.tscn",
		"drawing", ["res://modules/drawing/comp_entity_ink.gd"], "strokes", false, false, false, false, "", []
	))
	_register(_entry(
		"areas", "区域", false, false, 1, 3,
		["feature_layer_stack", "feature_edit_mode", "feature_component_sync"], [], "res://modules/areas/areas.tscn",
		"", ["res://modules/areas/comp_area.gd"], "", false, false, false, false, "", []
	))
	_register(_entry(
		"room_chat", "聊天", false, false, 1, 4,
		["feature_component_sync", "feature_edit_mode"], [], "res://modules/room_chat/chat.tscn",
		"", [], "", true, true, false, false, "", []
	))
	_register(_entry(
		"checklist", "任务清单", false, false, 1, 1,
		["feature_component_sync"], [], "res://modules/checklist/checklist.tscn",
		"checklist", [], "", false, false, false, false, "", []
	))
	_register(_entry(
		"player_cursors", "玩家鼠标", false, false, 1, 1,
		["feature_component_sync"], [], "res://modules/player_cursors/player_cursors.tscn",
		"", [], "", true, true, false, false, "", []
	))
	_register(_entry(
		"resource_pool", "通用资源", false, false, 1, 2,
		["feature_edit_mode", "feature_component_sync"], [], "res://scenes/candidates/resource_pool/feature_resource_pool.tscn",
		"resource_pool", ["res://scenes/candidates/resource_pool/comp_resource_pool.gd"], "", false, false, false, false, "", []
	))
	_register(_entry(
		"map_fog_editor", "迷雾编辑", false, false, 1, 1,
		["feature_edit_mode", "feature_layer_stack", "feature_component_sync", "feature_obstacle_authoring"], [], "res://modules/map_fog_editor/feature_map_fog_editor.tscn",
		"", [], "", true, true, false, false, "", []
	))
	_register(_entry(
		"grid_alignment", "网格与地图对齐", false, false, 1, 1,
		["feature_edit_mode", "feature_layer_stack", "feature_component_sync"], [], "res://modules/grid_alignment/feature_grid_alignment.tscn",
		"grid_alignment", [], "", false, false, false, false, "", []
	))
	_register(_entry(
		"detached_sidebar", "独立侧栏", false, false, 1, 1,
		[], [], "res://modules/detached_sidebar/feature.tscn",
		"", [], "", true, true, false, false, "", []
	))
	_register(_entry(
		"character_roster", "左侧角色栏", false, false, 1, 1,
		["feature_component_sync", "feature_edit_mode"], [], "res://modules/character_roster/feature.tscn",
		"character_roster", ["res://modules/character_roster/comp_character_roster_member.gd"], "", false, false, false, false, "", []
	))
	_register(_entry(
		"portal", "传送门", false, false, 1, 1,
		["areas"], [], "res://modules/portal/feature_portal.tscn",
		"", ["res://modules/portal/comp_portal.gd"], "", false, false, false, false, "", []
	))
	_register(_entry(
		"backpack", "背包", false, false, 1, 3,
		["feature_edit_mode", "feature_component_sync"], [], "res://modules/backpack/feature_backpack.tscn",
		"", ["res://modules/backpack/comp_backpack.gd"], "", false, false, false, false, "", []
	))
	_register(_entry(
		"dnd_opportunity", "D&D 角色卡与百科", false, false, 1, 8,
		["drag_movement", "simple_fog"], [], "res://modules/dnd_opportunity/feature.tscn",
		"dnd_opportunity", [], "", false, false, false, true, PLAYTEST_BLOCKED_REASON_V061, []
	))
	_register(_entry(
		"follow", "跟随", false, false, 1, 1,
		["drag_movement"], [], "res://modules/follow/feature_follow.tscn",
		"", ["res://modules/follow/comp_follow.gd"], "", false, false, false, false, "", []
	))
	_register(_entry(
		"simple_fog", "简易迷雾", false, false, 1, 3,
		["feature_obstacle_authoring", "feature_component_sync", "feature_edit_mode"], [], "res://modules/simple_fog/feature_simple_fog.tscn",
		"simple_fog", ["res://modules/simple_fog/comp_simple_vision.gd", "res://modules/simple_fog/comp_simple_light.gd"], "", false, false, false, false, "", []
	))
	_register(_entry(
		"dice", "通用骰子", false, false, 1, 3,
		["feature_networking", "feature_component_sync"], [], "res://modules/dice/feature_dice.tscn",
		"dice", [], "", false, false, false, false, "", []
	))
	_register(_entry(
		"candidate_initiative", "先攻与回合", false, false, 1, 2,
		["feature_networking", "feature_component_sync", "feature_edit_mode"], [], "res://modules/initiative/feature_initiative.tscn",
		"candidate_initiative", ["res://scenes/candidates/initiative/components/comp_initiative.gd"], "", false, false, false, false, "", ["initiative.manual"]
	))
	_register(_entry(
		"scene_box", "场景盒子", false, false, 1, 1,
		["feature_edit_mode", "feature_layer_stack", "feature_component_sync"], [], "res://modules/scene_box/feature_scene_box.tscn",
		"scene_box", ["res://modules/scene_box/comp_scene_box.gd", "res://scenes/candidates/scene_box/comp_scene_box.gd"], "", false, false, false, false, "", []
	))

	# 3 个未入正式目录的候选模块（scenes/candidates/）
	_register(_entry(
		"entity_notes", "实体注释", false, false, 1, 0,
		[], [], "res://scenes/candidates/entity_notes/feature_entity_notes.tscn",
		"", ["res://scenes/candidates/entity_notes/comp_entity_note.gd"], "", false, false, true, false, "", []
	))
	_register(_entry(
		"music_board", "音乐板", false, false, 1, 0,
		[], [], "res://scenes/candidates/music_board/feature_music_board.tscn",
		"", [], "", true, true, true, false, "", ["music_board"]
	))
	_register(_entry(
		"module_example", "模块示例", false, false, 1, 0,
		["feature_edit_mode", "feature_component_library"], [], "res://scenes/candidates/module_example/feature_module_example.tscn",
		"", ["res://scenes/candidates/module_example/comp_example_badge.gd"], "", true, true, true, false, "", [], ["feature_module_example"]
	))
