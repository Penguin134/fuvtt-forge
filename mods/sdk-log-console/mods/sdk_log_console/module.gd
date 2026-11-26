extends ExtensionBase
## SDK Log Console — 纯本机桌面开发者控制台模块（fus.desktop-module.v1 / local_only / scope: hybrid）
##
## 局外仍由包根目录 entry.gd 负责 .json/.log 会话导入与 world.modules.entries["sdk_log_console"] 持久化；
## 局内通过本模块（mod.sdk_log_console）在纯本机激活：
## 1. 动态加载 fu_runtime/v2.gd（优先包内 lib/fu_runtime/v2.gd，回退开发态 ../../../../shared/sdk/fu_runtime/v2.gd）；
## 2. 订阅 HookHelper（官方 HookIds 与自定义 mod.sdk_log_console.diagnostic）与 R3 LogBus（emit_to_engine = false）；
## 3. 注册 ui.module_settings 设置页（console_settings_page.tscn）以开关并配置悬浮终端控制台窗口；
## 4. 挂载可拖动悬浮终端窗口（console_floating_window.tscn），支持筛选、搜索、引擎日志/导入历史采集与本地命令。

signal console_state_changed
signal logs_changed

const PLUGIN_ID := "sdk_log_console"
const MODULE_ID := "mod.sdk_log_console"
const SAVED_ENTRY_ID := "sdk_log_console"
const SETTINGS_ITEM_ID := "mod.sdk_log_console.settings"
const SERVICE_ID := "mod.sdk_log_console.console"

const _RUNTIME_PACKAGED_REL_PATH := "lib/fu_runtime/v2.gd"
const _RUNTIME_DEV_REL_PATH := "../../../../shared/sdk/fu_runtime/v2.gd"
const _SETTINGS_PAGE_REL_PATH := "console_settings_page.tscn"
const _SETTINGS_PAGE_RES_PATH := "res://mods/sdk_log_console/console_settings_page.tscn"
const _WINDOW_REL_PATH := "console_floating_window.tscn"
const _WINDOW_RES_PATH := "res://mods/sdk_log_console/console_floating_window.tscn"

const _MAX_CACHED_ENTRIES: int = 512
const _ENGINE_TAIL_WINDOW: int = 64
const _LEVEL_INT_BY_NAME: Dictionary = {
	"debug": 10,
	"info": 20,
	"warning": 30,
	"error": 40,
}
const _HOOK_1_ARG_IDS: Array[StringName] = [
	&"entity.spawned",
	&"entity.removed",
	&"entity.selected",
	&"floor.changed",
	&"scene.switched",
	&"module.toggled",
	&"dice.rolled",
	&"vitals.changed",
	&"combat.started",
	&"combat.ended",
	&"chat.message_received",
]

var _runtime_sdk: RefCounted = null
var _logger: RefCounted = null
var _api_helper: RefCounted = null
var _hook_helper: RefCounted = null
var _slot_helper: RefCounted = null

var _window: Control = null
var _mounted_via_floating_panel: bool = false
var _mounted_via_slot_token: bool = false
var _log_sub_token: int = -1
var _custom_diag_hook: StringName = &""

var _console_visible: bool = false
var _min_level: String = "debug"
var _capture_hooks: bool = true
var _capture_engine: bool = true
var _capture_imported: bool = true

var _entries_cache: Array[Dictionary] = []
var _hook_counts: Dictionary = {}
var _engine_lines_ingested: int = 0
var _last_engine_line_count: int = 0
var _last_engine_entry_count: int = -1
var _last_engine_dropped: int = -1
var _last_engine_tail: PackedStringArray = PackedStringArray()
var _imported_loaded: bool = false
var _imported_entry_count: int = 0

var _settings_scene_cache: PackedScene = null
var _window_scene_cache: PackedScene = null


func _load_runtime_sdk() -> RefCounted:
	var self_scr := get_script() as Script
	var base_dir: String = ""
	if self_scr != null and not self_scr.resource_path.is_empty():
		base_dir = self_scr.resource_path.split("::")[0].get_base_dir()

	var candidates: Array[String] = []
	if not base_dir.is_empty():
		candidates.append(base_dir.path_join(_RUNTIME_PACKAGED_REL_PATH).simplify_path())
		candidates.append(base_dir.path_join(_RUNTIME_DEV_REL_PATH).simplify_path())
	candidates.append("res://shared/sdk/fu_runtime/v2.gd")
	candidates.append("shared/sdk/fu_runtime/v2.gd")

	for path: String in candidates:
		if ResourceLoader.exists(path) or FileAccess.file_exists(path):
			var loaded := load(path) as Script
			if loaded != null:
				var inst: Variant = loaded.new()
				if inst is RefCounted:
					return inst as RefCounted
	return null


func _load_local_scene(rel_path: String, fallback_res_path: String) -> PackedScene:
	var self_scr := get_script() as Script
	var candidates: Array[String] = []
	if self_scr != null and not self_scr.resource_path.is_empty():
		var base_dir: String = self_scr.resource_path.split("::")[0].get_base_dir()
		if not base_dir.is_empty():
			candidates.append(base_dir.path_join(rel_path).simplify_path())
	candidates.append(fallback_res_path)

	for path: String in candidates:
		if ResourceLoader.exists(path) or FileAccess.file_exists(path):
			var loaded := load(path)
			if loaded is PackedScene and (loaded as PackedScene).can_instantiate():
				return loaded as PackedScene
	return null


func _on_register(context: ExtensionContext) -> void:
	set_meta(&"module_id", MODULE_ID)
	_runtime_sdk = _load_runtime_sdk()
	if _runtime_sdk == null:
		push_warning("[%s] Unable to load fu_runtime/v2.gd" % PLUGIN_ID)
		return

	_logger = _runtime_sdk.call(&"create_logger", {
		"max_entries": _MAX_CACHED_ENTRIES,
		"min_level": int(_LEVEL_INT_BY_NAME.get(_min_level, 10)),
		"emit_to_engine": false,
	}) as RefCounted
	if _logger != null:
		_log_sub_token = int(_logger.call(&"subscribe", Callable(self, &"_on_log_bus_entry")))

	_api_helper = _runtime_sdk.call(&"create_desktop_api_helper", context, _logger) as RefCounted
	_hook_helper = _runtime_sdk.call(&"create_hook_helper", context, _logger) as RefCounted
	_slot_helper = _runtime_sdk.call(&"create_slot_helper", context, _logger) as RefCounted

	context.publish_service(SERVICE_ID, self)

	# 订阅世界 HookIds（arity 精确匹配）与自定义诊断 Hook
	if _hook_helper != null:
		for hook_id: StringName in _HOOK_1_ARG_IDS:
			_hook_helper.call(&"subscribe", hook_id, Callable(self, &"_on_hook_1").bind(String(hook_id)))
		_hook_helper.call(&"subscribe", &"mode.changed", Callable(self, &"_on_mode_changed"))
		_custom_diag_hook = _hook_helper.call(&"build_custom_hook_id", "mod", PLUGIN_ID, "diagnostic") as StringName
		if _custom_diag_hook != &"":
			_hook_helper.call(&"subscribe", _custom_diag_hook, Callable(self, &"_on_custom_diagnostic"))

	# 注册 ui.module_settings 设置页（允许玩家/GM 在本机打开设置页控制自己的控制台窗口）
	_settings_scene_cache = _load_local_scene(_SETTINGS_PAGE_REL_PATH, _SETTINGS_PAGE_RES_PATH)
	if _slot_helper != null and _settings_scene_cache != null:
		var reg_res: Dictionary = _slot_helper.call(
			&"register_module_settings",
			SETTINGS_ITEM_ID,
			"SDK 日志控制台",
			_settings_scene_cache,
			self,
			{"priority": 10, "dm_only": false}
		)
		if not bool(reg_res.get("ok", false)) and _logger != null:
			_logger.call(&"warn", PLUGIN_ID, "ui.module_settings registration failed", reg_res)

	# 实例化并挂载悬浮终端窗口（默认隐藏；优先 mount_floating_panel，回退 SlotHelper.mount_node）
	_window_scene_cache = _load_local_scene(_WINDOW_REL_PATH, _WINDOW_RES_PATH)
	if _window_scene_cache != null:
		var raw_win: Node = _window_scene_cache.instantiate()
		if raw_win is Control:
			_window = raw_win as Control
			if _window.has_method(&"bind_provider"):
				_window.call(&"bind_provider", self)
			if _window.has_method(&"set_console_open"):
				_window.call(&"set_console_open", false)
			var screen_host: Node = context.get_screen_host()
			if is_instance_valid(screen_host) and screen_host.has_method(&"mount_floating_panel"):
				if bool(screen_host.call(&"mount_floating_panel", _window)):
					_mounted_via_floating_panel = true
					context.add_revert(Callable(self, &"_teardown_window"), "sdk_log_console:floating_window")
			elif is_instance_valid(screen_host) and _slot_helper != null:
				var mount_res: Dictionary = _slot_helper.call(&"mount_node", screen_host, _window)
				if bool(mount_res.get("ok", false)):
					_mounted_via_slot_token = true
			if _window.get_parent() == null:
				if _window.has_method(&"deactivate"):
					_window.call(&"deactivate")
				_window.free()
				_window = null
		elif raw_win != null:
			raw_win.free()

	_emit_startup_telemetry(context)


func _teardown_window() -> void:
	if is_instance_valid(_window):
		if _window.has_method(&"deactivate"):
			_window.call(&"deactivate")
		if _window.get_parent() != null:
			_window.get_parent().remove_child(_window)
		_window.free()
	_window = null
	_mounted_via_floating_panel = false
	_mounted_via_slot_token = false


func _on_unregister() -> void:
	_teardown_window()
	if _logger != null and _log_sub_token >= 0:
		_logger.call(&"unsubscribe", _log_sub_token)
	_log_sub_token = -1
	if _hook_helper != null:
		_hook_helper.call(&"unbind")
	if _slot_helper != null:
		_slot_helper.call(&"unbind")
	if _api_helper != null:
		_api_helper.call(&"unbind")
	_hook_helper = null
	_slot_helper = null
	_api_helper = null
	_logger = null
	_runtime_sdk = null
	_settings_scene_cache = null
	_window_scene_cache = null
	_custom_diag_hook = &""
	_entries_cache.clear()
	_hook_counts.clear()
	_last_engine_line_count = 0
	_last_engine_entry_count = -1
	_last_engine_dropped = -1
	_last_engine_tail = PackedStringArray()


func _emit_startup_telemetry(context: ExtensionContext) -> void:
	var summary := get_status_summary()
	_log("info", "runtime", "SDK Log Console activated (local_only=true, role=%s, gm=%s, scene=%s, entities=%d)" % [
		str(summary.get("network_role", "solo")),
		str(summary.get("is_gm", false)),
		str(summary.get("active_scene_name", "")),
		int(summary.get("entity_count", 0)),
	], summary)

	# 可选：读取内置 debug_hooks 计数快照
	if is_instance_valid(context) and context.has_method(&"consume_service"):
		var dbg_hooks: Variant = context.call(&"consume_service", "debug_hooks")
		if dbg_hooks is Object and is_instance_valid(dbg_hooks) and (dbg_hooks as Object).has_method(&"get_counters"):
			var counters_var: Variant = (dbg_hooks as Object).call(&"get_counters")
			if counters_var is Dictionary:
				_log("debug", "debug_hooks", "debug_hooks counters snapshot: %s" % [JSON.stringify(counters_var)], counters_var as Dictionary)

	if _capture_imported:
		ingest_imported_history()
	if _capture_engine:
		ingest_engine_logger()


func _log(level_name: String, source: String, message: String, context_dict: Dictionary = {}) -> void:
	if _logger == null:
		return
	var lvl: String = level_name.strip_edges().to_lower()
	match lvl:
		"debug":
			_logger.call(&"debug", source, message, context_dict)
		"warning", "warn":
			_logger.call(&"warn", source, message, context_dict)
		"error":
			_logger.call(&"error", source, message, context_dict)
		_:
			_logger.call(&"info", source, message, context_dict)


func _on_log_bus_entry(entry: Dictionary) -> void:
	var cloned: Dictionary = _runtime_sdk.call(&"safe_clone_dict", entry) as Dictionary if _runtime_sdk != null else entry.duplicate(true)
	_entries_cache.append(cloned)
	if _entries_cache.size() > _MAX_CACHED_ENTRIES:
		_entries_cache.pop_front()
	logs_changed.emit()


func _on_hook_1(payload: Variant, hook_name: String) -> void:
	if not _capture_hooks:
		return
	_hook_counts[hook_name] = int(_hook_counts.get(hook_name, 0)) + 1
	var detail: String = ""
	if payload is Dictionary:
		detail = JSON.stringify(payload)
	else:
		detail = str(payload)
	if detail.length() > 180:
		detail = detail.left(180) + "..."
	_log("info", "hook." + hook_name, detail if not detail.is_empty() else "triggered")


func _on_mode_changed(prev_mode: Variant = null, next_mode: Variant = null) -> void:
	if not _capture_hooks:
		return
	_hook_counts["mode.changed"] = int(_hook_counts.get("mode.changed", 0)) + 1
	_log("info", "hook.mode.changed", "%s -> %s" % [str(prev_mode), str(next_mode)])


func _on_custom_diagnostic(payload: Variant) -> void:
	if not _capture_hooks:
		return
	var hook_key: String = String(_custom_diag_hook) if _custom_diag_hook != &"" else "mod.sdk_log_console.diagnostic"
	_hook_counts[hook_key] = int(_hook_counts.get(hook_key, 0)) + 1
	var lvl: String = "info"
	var src: String = hook_key
	var msg: String = ""
	if payload is Dictionary:
		var d := payload as Dictionary
		lvl = str(d.get("level", "info")).to_lower()
		src = str(d.get("source", hook_key))
		msg = str(d.get("message", JSON.stringify(d)))
	else:
		msg = str(payload)
	_log(lvl, src, msg)


func is_console_visible() -> bool:
	return _console_visible


func set_console_visible(visible: bool) -> void:
	_console_visible = visible
	if is_instance_valid(_window) and _window.has_method(&"set_console_open"):
		_window.call(&"set_console_open", visible)
	console_state_changed.emit()


func toggle_console() -> bool:
	set_console_visible(not _console_visible)
	return _console_visible


func get_floating_window() -> Control:
	return _window if is_instance_valid(_window) else null


func get_min_level() -> String:
	return _min_level


func set_min_level(level: String) -> void:
	var clean: String = level.strip_edges().to_lower()
	if not _LEVEL_INT_BY_NAME.has(clean):
		return
	_min_level = clean
	if _logger != null:
		_logger.call(&"set_min_level", int(_LEVEL_INT_BY_NAME[clean]))
	_log("info", "console.config", "min_level=%s" % clean)
	console_state_changed.emit()


func get_capture_config() -> Dictionary:
	return {
		"capture_hooks": _capture_hooks,
		"capture_engine": _capture_engine,
		"capture_imported": _capture_imported,
	}


func set_capture_flag(flag_name: String, enabled: bool) -> void:
	match flag_name:
		"capture_hooks":
			_capture_hooks = enabled
		"capture_engine":
			_capture_engine = enabled
			if enabled:
				ingest_engine_logger()
		"capture_imported":
			_capture_imported = enabled
			if enabled:
				ingest_imported_history()
		_:
			return
	_log("debug", "console.config", "%s=%s" % [flag_name, str(enabled)])
	console_state_changed.emit()


func get_console_entries(level_filter: String = "all", search_query: String = "") -> Array:
	var clean_lvl: String = level_filter.strip_edges().to_lower()
	var clean_query: String = search_query.strip_edges().to_lower()
	var out: Array = []
	for entry: Dictionary in _entries_cache:
		var lvl_name: String = str(entry.get("level_name", "INFO")).to_lower()
		if not clean_lvl.is_empty() and clean_lvl != "all" and lvl_name != clean_lvl:
			continue
		if not clean_query.is_empty():
			var hay: String = (str(entry.get("source", "")) + " " + str(entry.get("message", ""))).to_lower()
			if not hay.contains(clean_query):
				continue
		out.append(entry.duplicate(true))
	return out


func clear_console() -> void:
	_entries_cache.clear()
	if _logger != null:
		_logger.call(&"clear")
	logs_changed.emit()
	console_state_changed.emit()


func ingest_imported_history() -> int:
	if _api_helper == null or not bool(_api_helper.call(&"is_available")):
		return 0
	if not bool(_api_helper.call(&"is_gm")):
		return 0
	var saved_var: Variant = _api_helper.call(&"read_saved_module_entry", SAVED_ENTRY_ID)
	if not (saved_var is Dictionary) or (saved_var as Dictionary).is_empty():
		return 0
	var saved := saved_var as Dictionary
	var st_var: Variant = saved.get("state", {})
	if not (st_var is Dictionary):
		return 0
	var st := st_var as Dictionary
	var tail_var: Variant = st.get("entries_tail", [])
	if not (tail_var is Array):
		return 0
	var tail := tail_var as Array
	_imported_loaded = true
	_imported_entry_count = tail.size()
	_log("info", "imported.summary", "Loaded GM saved import entry '%s': total=%d, warnings=%d, tail=%d" % [
		SAVED_ENTRY_ID,
		int(st.get("total_entries", 0)),
		int(st.get("warning_count", 0)),
		tail.size(),
	])
	var added: int = 0
	for item: Variant in tail:
		if not (item is Dictionary):
			continue
		var d := item as Dictionary
		var lvl: String = str(d.get("level_name", "INFO")).to_lower()
		var src: String = "imported." + str(d.get("source", "session"))
		var msg: String = str(d.get("message", ""))
		_log(lvl, src, msg)
		added += 1
	return added


func _find_engine_overlap_start(lines: PackedStringArray) -> int:
	if _last_engine_tail.is_empty() or lines.is_empty():
		return 0
	var tail_size: int = _last_engine_tail.size()
	var tail_last: String = _last_engine_tail[tail_size - 1]
	var best_match: int = 0
	var best_end_idx: int = -1
	for end_idx: int in range(lines.size() - 1, -1, -1):
		if lines[end_idx] != tail_last:
			continue
		var max_len: int = mini(end_idx + 1, tail_size)
		var match_len: int = 1
		while match_len < max_len and lines[end_idx - match_len] == _last_engine_tail[tail_size - 1 - match_len]:
			match_len += 1
		if match_len > best_match:
			best_match = match_len
			best_end_idx = end_idx
			if best_match == tail_size:
				break
	if best_match >= 1:
		return best_end_idx + 1
	return 0


func ingest_engine_logger() -> int:
	var dev_tools := get_node_or_null("/root/DevTools")
	if not is_instance_valid(dev_tools):
		return 0
	var eng_logger: Variant = dev_tools.get(&"_engine_logger")
	if eng_logger == null or not (eng_logger is Object) or not is_instance_valid(eng_logger):
		return 0
	var logger_obj := eng_logger as Object
	if not logger_obj.has_method(&"capture"):
		return 0
	var cap_var: Variant = logger_obj.call(&"capture")
	if not (cap_var is Dictionary):
		return 0
	var cap := cap_var as Dictionary
	var raw_text: String = str(cap.get("text", ""))
	var entry_count: int = int(cap.get("lines", -1))
	var dropped: int = int(cap.get("dropped", 0))
	var lines: PackedStringArray = raw_text.split("\n", false)
	if lines.is_empty():
		_last_engine_line_count = 0
		_last_engine_entry_count = -1
		_last_engine_dropped = dropped
		_last_engine_tail = PackedStringArray()
		return 0
	var start_idx: int = 0
	if _last_engine_dropped < 0:
		start_idx = 0
	elif _last_engine_entry_count > 0 and (dropped - _last_engine_dropped) >= _last_engine_entry_count:
		start_idx = 0
	elif dropped == _last_engine_dropped and lines.size() >= _last_engine_line_count and (
		_last_engine_line_count == 0
		or (not _last_engine_tail.is_empty() and lines[_last_engine_line_count - 1] == _last_engine_tail[_last_engine_tail.size() - 1])
	):
		start_idx = _last_engine_line_count
	else:
		start_idx = _find_engine_overlap_start(lines)
	var added: int = 0
	for i: int in range(start_idx, lines.size()):
		var line: String = lines[i].strip_edges()
		if line.is_empty():
			continue
		var lvl: String = "info"
		if line.contains("SCRIPT ") or line.contains("ERROR ") or line.contains("STDERR "):
			lvl = "error"
		elif line.contains("WARNING "):
			lvl = "warning"
		_log(lvl, "engine", line)
		added += 1
	_last_engine_dropped = dropped
	_last_engine_line_count = lines.size()
	_last_engine_entry_count = entry_count
	var tail_start: int = maxi(0, lines.size() - _ENGINE_TAIL_WINDOW)
	_last_engine_tail = lines.slice(tail_start)
	_engine_lines_ingested += added
	return added


func get_status_summary() -> Dictionary:
	var is_gm_flag: bool = false
	var role: String = "solo"
	var scene_name: String = ""
	var floor_uid: String = ""
	var entity_count: int = 0
	if _api_helper != null and bool(_api_helper.call(&"is_available")):
		is_gm_flag = bool(_api_helper.call(&"is_gm"))
		role = str(_api_helper.call(&"network_role"))
		scene_name = str(_api_helper.call(&"active_scene_name"))
		floor_uid = str(_api_helper.call(&"active_floor_uid"))
		var ents: Variant = _api_helper.call(&"get_entities", true)
		if ents is Array:
			entity_count = (ents as Array).size()
	return {
		"module_id": MODULE_ID,
		"local_only": true,
		"network_version": 0,
		"console_visible": _console_visible,
		"min_level": _min_level,
		"entry_count": _entries_cache.size(),
		"is_gm": is_gm_flag,
		"network_role": role,
		"active_scene_name": scene_name,
		"active_floor_uid": floor_uid,
		"entity_count": entity_count,
		"hook_counts": _hook_counts.duplicate(),
		"engine_lines": _engine_lines_ingested,
		"imported_loaded": _imported_loaded,
		"imported_entries": _imported_entry_count,
	}


func run_console_command(command: String) -> String:
	var clean: String = command.strip_edges()
	if clean.is_empty():
		return ""
	var parts: PackedStringArray = clean.split(" ", false)
	var cmd: String = parts[0].to_lower()
	var reply: String = ""

	match cmd:
		"help", "?":
			reply = "Commands: help | status | clear | level <debug|info|warning|error> | hooks | engine | imported | entities"
			_log("info", "cmd.help", reply)
		"status":
			var st := get_status_summary()
			reply = "status: module=%s local_only=%s role=%s gm=%s entries=%d entities=%d" % [
				str(st.get("module_id", MODULE_ID)),
				str(st.get("local_only", true)),
				str(st.get("network_role", "solo")),
				str(st.get("is_gm", false)),
				int(st.get("entry_count", 0)),
				int(st.get("entity_count", 0)),
			]
			_log("info", "cmd.status", reply)
		"clear":
			clear_console()
			reply = "Console cleared."
			_log("info", "cmd.clear", reply)
		"level":
			if parts.size() >= 2 and _LEVEL_INT_BY_NAME.has(parts[1].to_lower()):
				set_min_level(parts[1].to_lower())
				reply = "min_level set to %s" % _min_level
			else:
				reply = "current min_level=%s (usage: level <debug|info|warning|error>)" % _min_level
			_log("info", "cmd.level", reply)
		"hooks":
			reply = "hook_counts=%s" % JSON.stringify(_hook_counts)
			_log("info", "cmd.hooks", reply)
		"engine":
			var n_eng: int = ingest_engine_logger()
			reply = "ingested %d new engine logger lines" % n_eng
			_log("info", "cmd.engine", reply)
		"imported":
			var n_imp: int = ingest_imported_history()
			reply = "ingested %d GM saved import entries" % n_imp
			_log("info", "cmd.imported", reply)
		"entities":
			var ents: Array = _api_helper.call(&"get_entities", true) as Array if _api_helper != null else []
			var sel: Array = _api_helper.call(&"selected_entities") as Array if _api_helper != null else []
			reply = "active_floor_entities=%d selected=%d" % [ents.size(), sel.size()]
			_log("info", "cmd.entities", reply)
		_:
			reply = "Unknown command '%s'. Type 'help' for available commands." % cmd
			_log("warning", "cmd", reply)

	return reply
