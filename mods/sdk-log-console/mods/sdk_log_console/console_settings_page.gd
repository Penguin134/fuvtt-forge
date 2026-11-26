extends VBoxContainer

const _LEVEL_ORDER: Array[String] = ["debug", "info", "warning", "error"]
const _LEVEL_LABELS: Array[String] = ["DEBUG", "INFO", "WARNING", "ERROR"]

var _provider_ref: WeakRef = null
var _syncing: bool = false
var _ui_wired: bool = false


func _ready() -> void:
	_wire_ui()
	refresh()


func _exit_tree() -> void:
	_unbind_provider()


func _wire_ui() -> void:
	if _ui_wired:
		return
	_ui_wired = true
	var lvl_opt := get_node_or_null("%MinLevelOption") as OptionButton
	if lvl_opt != null:
		if lvl_opt.item_count == 0:
			for lbl: String in _LEVEL_LABELS:
				lvl_opt.add_item(lbl)
		if not lvl_opt.item_selected.is_connected(_on_min_level_selected):
			lvl_opt.item_selected.connect(_on_min_level_selected)

	var vis_chk := get_node_or_null("%ConsoleVisibleCheck") as CheckButton
	if vis_chk != null and not vis_chk.toggled.is_connected(_on_console_visible_toggled):
		vis_chk.toggled.connect(_on_console_visible_toggled)

	var tog_btn := get_node_or_null("%ToggleConsoleButton") as Button
	if tog_btn != null and not tog_btn.pressed.is_connected(_on_toggle_console_pressed):
		tog_btn.pressed.connect(_on_toggle_console_pressed)

	var hooks_chk := get_node_or_null("%CaptureHooksCheck") as CheckButton
	if hooks_chk != null and not hooks_chk.toggled.is_connected(_on_capture_hooks_toggled):
		hooks_chk.toggled.connect(_on_capture_hooks_toggled)

	var eng_chk := get_node_or_null("%CaptureEngineCheck") as CheckButton
	if eng_chk != null and not eng_chk.toggled.is_connected(_on_capture_engine_toggled):
		eng_chk.toggled.connect(_on_capture_engine_toggled)

	var imp_chk := get_node_or_null("%CaptureImportedCheck") as CheckButton
	if imp_chk != null and not imp_chk.toggled.is_connected(_on_capture_imported_toggled):
		imp_chk.toggled.connect(_on_capture_imported_toggled)

	var clr_btn := get_node_or_null("%ClearLogsButton") as Button
	if clr_btn != null and not clr_btn.pressed.is_connected(_on_clear_logs_pressed):
		clr_btn.pressed.connect(_on_clear_logs_pressed)

	var ref_btn := get_node_or_null("%RefreshStatusButton") as Button
	if ref_btn != null and not ref_btn.pressed.is_connected(_on_refresh_status_pressed):
		ref_btn.pressed.connect(_on_refresh_status_pressed)


func bind_provider(provider: Object) -> bool:
	_unbind_provider()
	var valid_provider: bool = false
	if provider != null and is_instance_valid(provider):
		var ctx_var: Variant = provider.get(&"ctx")
		if ctx_var is Object and is_instance_valid(ctx_var):
			var ctx_obj := ctx_var as Object
			var active_ok: bool = ctx_obj.has_method(&"is_active") and bool(ctx_obj.call(&"is_active"))
			var init_ok: bool = ctx_obj.has_method(&"can_initialize") and bool(ctx_obj.call(&"can_initialize"))
			valid_provider = active_ok or init_ok
	if not valid_provider:
		if is_node_ready():
			refresh()
		return false
	_provider_ref = weakref(provider)
	_connect_provider_signals(provider)
	if is_node_ready():
		refresh()
	return true


func _provider() -> Object:
	if _provider_ref == null:
		return null
	var obj: Variant = _provider_ref.get_ref()
	if obj == null or not is_instance_valid(obj):
		return null
	return obj as Object


func _connect_provider_signals(p: Object) -> void:
	if p == null or not is_instance_valid(p):
		return
	var refresh_cb := Callable(self, &"refresh")
	if p.has_signal(&"console_state_changed") and not p.is_connected(&"console_state_changed", refresh_cb):
		p.connect(&"console_state_changed", refresh_cb)
	if p.has_signal(&"logs_changed") and not p.is_connected(&"logs_changed", refresh_cb):
		p.connect(&"logs_changed", refresh_cb)


func _disconnect_provider_signals() -> void:
	var p := _provider()
	if p != null:
		var refresh_cb := Callable(self, &"refresh")
		if p.has_signal(&"console_state_changed") and p.is_connected(&"console_state_changed", refresh_cb):
			p.disconnect(&"console_state_changed", refresh_cb)
		if p.has_signal(&"logs_changed") and p.is_connected(&"logs_changed", refresh_cb):
			p.disconnect(&"logs_changed", refresh_cb)


func _unbind_provider() -> void:
	_disconnect_provider_signals()
	_provider_ref = null


func deactivate() -> void:
	_disconnect_provider_signals()


func refresh() -> void:
	if not is_node_ready():
		return
	var p := _provider()
	if p != null:
		_connect_provider_signals(p)
	_syncing = true
	var console_open: bool = false
	var min_lvl: String = "debug"
	var cap_hooks: bool = true
	var cap_engine: bool = true
	var cap_imported: bool = true
	var status_text: String = "模块未绑定或已停用。"

	if p != null:
		if p.has_method(&"is_console_visible"):
			console_open = bool(p.call(&"is_console_visible"))
		if p.has_method(&"get_min_level"):
			min_lvl = str(p.call(&"get_min_level")).to_lower()
		if p.has_method(&"get_capture_config"):
			var cfg_var: Variant = p.call(&"get_capture_config")
			if cfg_var is Dictionary:
				var cfg := cfg_var as Dictionary
				cap_hooks = bool(cfg.get("capture_hooks", true))
				cap_engine = bool(cfg.get("capture_engine", true))
				cap_imported = bool(cfg.get("capture_imported", true))
		if p.has_method(&"get_status_summary"):
			var sum_var: Variant = p.call(&"get_status_summary")
			if sum_var is Dictionary:
				var st := sum_var as Dictionary
				status_text = (
					"模块: %s (local_only=%s, net_ver=%s)\n"
					+ "窗口: %s | 缓存日志: %d 条 | 最低级别: %s\n"
					+ "角色: %s (GM=%s) | 实体数: %d | 引擎日志增量: %d | 导入历史: %d 条"
				) % [
					str(st.get("module_id", "mod.sdk_log_console")),
					str(st.get("local_only", true)),
					str(st.get("network_version", 0)),
					"开启" if console_open else "关闭",
					int(st.get("entry_count", 0)),
					min_lvl.to_upper(),
					str(st.get("network_role", "solo")),
					str(st.get("is_gm", false)),
					int(st.get("entity_count", 0)),
					int(st.get("engine_lines", 0)),
					int(st.get("imported_entries", 0)),
				]

	var vis_chk := get_node_or_null("%ConsoleVisibleCheck") as CheckButton
	if vis_chk != null:
		vis_chk.set_pressed_no_signal(console_open)
		vis_chk.disabled = (p == null)

	var tog_btn := get_node_or_null("%ToggleConsoleButton") as Button
	if tog_btn != null:
		tog_btn.disabled = (p == null)
		tog_btn.text = "关闭控制台窗口" if console_open else "打开控制台窗口"

	var lvl_opt := get_node_or_null("%MinLevelOption") as OptionButton
	if lvl_opt != null:
		var idx: int = _LEVEL_ORDER.find(min_lvl)
		if idx < 0:
			idx = 0
		if idx < lvl_opt.item_count:
			lvl_opt.select(idx)
		lvl_opt.disabled = (p == null)

	var hooks_chk := get_node_or_null("%CaptureHooksCheck") as CheckButton
	if hooks_chk != null:
		hooks_chk.set_pressed_no_signal(cap_hooks)
		hooks_chk.disabled = (p == null)

	var eng_chk := get_node_or_null("%CaptureEngineCheck") as CheckButton
	if eng_chk != null:
		eng_chk.set_pressed_no_signal(cap_engine)
		eng_chk.disabled = (p == null)

	var imp_chk := get_node_or_null("%CaptureImportedCheck") as CheckButton
	if imp_chk != null:
		imp_chk.set_pressed_no_signal(cap_imported)
		imp_chk.disabled = (p == null)

	var clr_btn := get_node_or_null("%ClearLogsButton") as Button
	if clr_btn != null:
		clr_btn.disabled = (p == null)

	var ref_btn := get_node_or_null("%RefreshStatusButton") as Button
	if ref_btn != null:
		ref_btn.disabled = (p == null)

	var sum_lbl := get_node_or_null("%StatusSummaryLabel") as Label
	if sum_lbl != null:
		sum_lbl.text = status_text

	_syncing = false


func _on_console_visible_toggled(enabled: bool) -> void:
	if _syncing:
		return
	var p := _provider()
	if p != null and p.has_method(&"set_console_visible"):
		p.call(&"set_console_visible", enabled)
	refresh()


func _on_toggle_console_pressed() -> void:
	if _syncing:
		return
	var p := _provider()
	if p != null and p.has_method(&"toggle_console"):
		p.call(&"toggle_console")
	refresh()


func _on_min_level_selected(index: int) -> void:
	if _syncing:
		return
	if index < 0 or index >= _LEVEL_ORDER.size():
		return
	var p := _provider()
	if p != null and p.has_method(&"set_min_level"):
		p.call(&"set_min_level", _LEVEL_ORDER[index])
	refresh()


func _on_capture_hooks_toggled(enabled: bool) -> void:
	if _syncing:
		return
	var p := _provider()
	if p != null and p.has_method(&"set_capture_flag"):
		p.call(&"set_capture_flag", "capture_hooks", enabled)
	refresh()


func _on_capture_engine_toggled(enabled: bool) -> void:
	if _syncing:
		return
	var p := _provider()
	if p != null and p.has_method(&"set_capture_flag"):
		p.call(&"set_capture_flag", "capture_engine", enabled)
	refresh()


func _on_capture_imported_toggled(enabled: bool) -> void:
	if _syncing:
		return
	var p := _provider()
	if p != null and p.has_method(&"set_capture_flag"):
		p.call(&"set_capture_flag", "capture_imported", enabled)
	refresh()


func _on_clear_logs_pressed() -> void:
	if _syncing:
		return
	var p := _provider()
	if p != null and p.has_method(&"clear_console"):
		p.call(&"clear_console")
	refresh()


func _on_refresh_status_pressed() -> void:
	if _syncing:
		return
	var p := _provider()
	if p != null:
		if p.has_method(&"ingest_engine_logger"):
			p.call(&"ingest_engine_logger")
		if p.has_method(&"ingest_imported_history"):
			p.call(&"ingest_imported_history")
	refresh()
