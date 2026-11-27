extends PanelContainer

const _FILTER_ORDER: Array[String] = ["all", "debug", "info", "warning", "error"]
const _FILTER_LABELS: Array[String] = ["ALL", "DEBUG", "INFO", "WARNING", "ERROR"]
const _MSG_WHITE_HEX: String = "#f5f5f7"
const _SEQ_MUTED_HEX: String = "#98989d"
const _SOURCE_CYAN_HEX: String = "#64d2ff"
const _EMPTY_HINT_HEX: String = "#aeaeb2"

var _provider_ref: WeakRef = null
var _dragging: bool = false
var _drag_offset: Vector2 = Vector2.ZERO
var _level_filter: String = "all"
var _search_query: String = ""
var _rendered_text: String = ""
var _console_open: bool = true
var _ui_wired: bool = false


func _ready() -> void:
	_wire_ui()
	visible = _console_open
	refresh_logs()


func _exit_tree() -> void:
	deactivate()


func _wire_ui() -> void:
	if _ui_wired:
		return
	_ui_wired = true

	var header := get_node_or_null("%HeaderBar") as Control
	if header != null and not header.gui_input.is_connected(_on_header_gui_input):
		header.gui_input.connect(_on_header_gui_input)

	var close_btn := get_node_or_null("%CloseButton") as Button
	if close_btn != null and not close_btn.pressed.is_connected(_on_close_pressed):
		close_btn.pressed.connect(_on_close_pressed)

	var lvl_opt := get_node_or_null("%LevelFilterOption") as OptionButton
	if lvl_opt != null:
		if lvl_opt.item_count == 0:
			for lbl: String in _FILTER_LABELS:
				lvl_opt.add_item(lbl)
		if not lvl_opt.item_selected.is_connected(_on_level_filter_selected):
			lvl_opt.item_selected.connect(_on_level_filter_selected)

	var search_in := get_node_or_null("%SearchInput") as LineEdit
	if search_in != null and not search_in.text_changed.is_connected(_on_search_changed):
		search_in.text_changed.connect(_on_search_changed)

	var ingest_btn := get_node_or_null("%IngestButton") as Button
	if ingest_btn != null and not ingest_btn.pressed.is_connected(_on_ingest_pressed):
		ingest_btn.pressed.connect(_on_ingest_pressed)

	var clr_btn := get_node_or_null("%ClearButton") as Button
	if clr_btn != null and not clr_btn.pressed.is_connected(_on_clear_pressed):
		clr_btn.pressed.connect(_on_clear_pressed)

	var cmd_in := get_node_or_null("%CommandInput") as LineEdit
	if cmd_in != null and not cmd_in.text_submitted.is_connected(_on_command_submitted):
		cmd_in.text_submitted.connect(_on_command_submitted)

	var run_btn := get_node_or_null("%RunCommandButton") as Button
	if run_btn != null and not run_btn.pressed.is_connected(_on_run_command_pressed):
		run_btn.pressed.connect(_on_run_command_pressed)


func bind_provider(provider: Object) -> bool:
	deactivate()
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
			refresh_logs()
		return false
	_provider_ref = weakref(provider)
	var logs_cb := Callable(self, &"refresh_logs")
	if provider.has_signal(&"logs_changed") and not provider.is_connected(&"logs_changed", logs_cb):
		provider.connect(&"logs_changed", logs_cb)
	var state_cb := Callable(self, &"_on_provider_state_changed")
	if provider.has_signal(&"console_state_changed") and not provider.is_connected(&"console_state_changed", state_cb):
		provider.connect(&"console_state_changed", state_cb)
	refresh_logs()
	return true


func _provider() -> Object:
	if _provider_ref == null:
		return null
	var obj: Variant = _provider_ref.get_ref()
	if obj == null or not is_instance_valid(obj):
		return null
	return obj as Object


func deactivate() -> void:
	_dragging = false
	var p := _provider()
	if p != null:
		var logs_cb := Callable(self, &"refresh_logs")
		if p.has_signal(&"logs_changed") and p.is_connected(&"logs_changed", logs_cb):
			p.disconnect(&"logs_changed", logs_cb)
		var state_cb := Callable(self, &"_on_provider_state_changed")
		if p.has_signal(&"console_state_changed") and p.is_connected(&"console_state_changed", state_cb):
			p.disconnect(&"console_state_changed", state_cb)
	_provider_ref = null


func set_console_open(open: bool) -> void:
	_console_open = open
	visible = open
	if not open:
		_dragging = false
	else:
		if is_inside_tree():
			move_to_front()
		refresh_logs()


func is_console_open() -> bool:
	return _console_open and visible


func set_filter(level_filter: String = "all", search_query: String = "") -> void:
	var clean_lvl: String = level_filter.strip_edges().to_lower()
	if not (clean_lvl in _FILTER_ORDER):
		clean_lvl = "all"
	_level_filter = clean_lvl
	_search_query = search_query.strip_edges()
	var lvl_opt := get_node_or_null("%LevelFilterOption") as OptionButton
	if lvl_opt != null:
		var idx: int = _FILTER_ORDER.find(_level_filter)
		if idx >= 0 and idx < lvl_opt.item_count:
			lvl_opt.select(idx)
	var search_in := get_node_or_null("%SearchInput") as LineEdit
	if search_in != null and search_in.text != _search_query:
		search_in.text = _search_query
	refresh_logs()


func get_rendered_log_text() -> String:
	var log_rt := get_node_or_null("%LogOutput") as RichTextLabel
	if is_node_ready() and log_rt != null:
		var parsed: String = log_rt.get_parsed_text()
		if not parsed.is_empty():
			return parsed
	return _rendered_text


func refresh_logs() -> void:
	var p := _provider()
	var filtered: Array = []
	var total_count: int = 0
	var max_chars: int = 2048
	if p != null:
		if p.has_method(&"get_max_message_chars"):
			max_chars = int(p.call(&"get_max_message_chars"))
		if p.has_method(&"get_console_entries"):
			var f_var: Variant = p.call(&"get_console_entries", _level_filter, _search_query)
			if f_var is Array:
				filtered = f_var as Array
			var all_var: Variant = p.call(&"get_console_entries", "all", "")
			if all_var is Array:
				total_count = (all_var as Array).size()

	var bb_lines: Array[String] = []
	var plain_lines: Array[String] = []
	for item: Variant in filtered:
		if not (item is Dictionary):
			continue
		var entry := item as Dictionary
		var seq: int = int(entry.get("seq", 0))
		var lvl: String = str(entry.get("level_name", "INFO")).to_upper()
		var src: String = str(entry.get("source", "sdk"))
		var msg: String = str(entry.get("message", ""))
		if max_chars > 0 and msg.length() > max_chars:
			msg = msg.left(max_chars) + "..."
		var plain_line: String = "#%03d [%s][%s] %s" % [seq, lvl, src, msg]
		plain_lines.append(plain_line)
		var color_hex: String = _color_for_level(lvl)
		bb_lines.append("[color=%s]#%03d[/color] [color=%s][%s][/color][color=%s][%s][/color] [color=%s]%s[/color]" % [
			_SEQ_MUTED_HEX,
			seq,
			color_hex,
			_escape_bbcode(lvl),
			_SOURCE_CYAN_HEX,
			_escape_bbcode(src),
			_MSG_WHITE_HEX,
			_escape_bbcode(msg),
		])

	if plain_lines.is_empty():
		var empty_msg: String = "(暂无匹配日志，可输入 help 查看本地诊断命令)"
		plain_lines.append(empty_msg)
		bb_lines.append("[color=%s]%s[/color]" % [_EMPTY_HINT_HEX, _escape_bbcode(empty_msg)])

	_rendered_text = "\n".join(plain_lines)
	var log_rt := get_node_or_null("%LogOutput") as RichTextLabel
	if is_node_ready() and log_rt != null:
		log_rt.text = "\n".join(bb_lines)

	var stats_lbl := get_node_or_null("%StatsLabel") as Label
	if is_node_ready() and stats_lbl != null:
		stats_lbl.text = "%d / %d entries" % [filtered.size(), total_count]


func _color_for_level(lvl: String) -> String:
	match lvl:
		"ERROR":
			return "#ff453a"
		"WARNING":
			return "#ffd60a"
		"INFO":
			return "#32d74b"
		_:
			return "#5ac8fa"


func _escape_bbcode(text: String) -> String:
	return text.replace("[", "[lb]")


func _on_provider_state_changed() -> void:
	var p := _provider()
	if p != null and p.has_method(&"is_console_visible"):
		set_console_open(bool(p.call(&"is_console_visible")))


func _on_close_pressed() -> void:
	var p := _provider()
	if p != null and p.has_method(&"set_console_visible"):
		p.call(&"set_console_visible", false)
	else:
		set_console_open(false)


func _on_level_filter_selected(index: int) -> void:
	if index < 0 or index >= _FILTER_ORDER.size():
		return
	_level_filter = _FILTER_ORDER[index]
	refresh_logs()


func _on_search_changed(new_text: String) -> void:
	_search_query = new_text.strip_edges()
	refresh_logs()


func _on_ingest_pressed() -> void:
	var p := _provider()
	if p != null:
		if p.has_method(&"ingest_engine_logger"):
			p.call(&"ingest_engine_logger")
		if p.has_method(&"ingest_imported_history"):
			p.call(&"ingest_imported_history")
	refresh_logs()


func _on_clear_pressed() -> void:
	var p := _provider()
	if p != null and p.has_method(&"clear_console"):
		p.call(&"clear_console")
	refresh_logs()


func _on_command_submitted(raw_cmd: String) -> void:
	_execute_command_text(raw_cmd)


func _on_run_command_pressed() -> void:
	var cmd_in := get_node_or_null("%CommandInput") as LineEdit
	if cmd_in != null:
		_execute_command_text(cmd_in.text)


func _execute_command_text(raw_cmd: String) -> void:
	var trimmed: String = raw_cmd.strip_edges()
	var cmd_in := get_node_or_null("%CommandInput") as LineEdit
	if cmd_in != null:
		cmd_in.clear()
	if trimmed.is_empty():
		return
	var p := _provider()
	if p != null and p.has_method(&"run_console_command"):
		p.call(&"run_console_command", trimmed)
	refresh_logs()


func _on_header_gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton:
		var mb := event as InputEventMouseButton
		if mb.button_index == MOUSE_BUTTON_LEFT:
			if mb.pressed:
				_dragging = true
				_drag_offset = get_global_mouse_position() - global_position
				accept_event()
			else:
				_dragging = false
				accept_event()
	elif event is InputEventMouseMotion and _dragging:
		var target_pos: Vector2 = get_global_mouse_position() - _drag_offset
		var bounds_rect: Rect2 = get_viewport_rect()
		var parent_ctrl := get_parent() as Control
		if is_instance_valid(parent_ctrl):
			var parent_rect: Rect2 = parent_ctrl.get_global_rect()
			if parent_rect.size.x > 1.0 and parent_rect.size.y > 1.0:
				bounds_rect = parent_rect
		if bounds_rect.size.x > 1.0 and bounds_rect.size.y > 1.0:
			var max_x: float = maxf(bounds_rect.position.x, bounds_rect.end.x - size.x)
			var max_y: float = maxf(bounds_rect.position.y, bounds_rect.end.y - size.y)
			target_pos.x = clampf(target_pos.x, bounds_rect.position.x, max_x)
			target_pos.y = clampf(target_pos.y, bounds_rect.position.y, max_y)
		global_position = target_pos
		accept_event()
