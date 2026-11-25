extends RefCounted
## Fu vtt 共享结构化调试与警告日志总线 (R3 LogBus)
##
## 提供分级日志（DEBUG/INFO/WARNING/ERROR）、有界环形缓冲区、
## 顺序游标读取与回调订阅机制（面向游戏内控制台插件与 Mod 排障），
## 并支持将日志安全同步到 Godot 控制台及 ImportBridge 宿主（受 100 条 / 7000 字符上限保护）。

const LEVEL_DEBUG: int = 10
const LEVEL_INFO: int = 20
const LEVEL_WARNING: int = 30
const LEVEL_ERROR: int = 40

const DEFAULT_MAX_ENTRIES: int = 512
const HOST_MAX_WARNINGS: int = 100
const HOST_MAX_NOTES_CHARS: int = 7000
const MAX_CONTEXT_DEPTH: int = 32
const MAX_CLONE_VISITS: int = 2097152
const MAX_CLONE_BYTES: int = 4 * 1024 * 1024
const MAX_NOTIFY_DEPTH: int = 32

var _entries: Array[Dictionary] = []
var _max_entries: int = DEFAULT_MAX_ENTRIES
var _min_level: int = LEVEL_DEBUG
var _next_seq: int = 1
var _subscribers: Dictionary = {}
var _next_token: int = 1
var _emit_to_engine: bool = true
var _notify_depth: int = 0

var _host: RefCounted = null
var _forward_reports_to_host: bool = false
var _host_warn_seen: Dictionary = {}
var _host_warn_count: int = 0
var _host_warn_chars: int = 0
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


func _validation_utils() -> Variant:
	return _load_util_script("validation_utils.gd")


func configure(
	max_entries: int = DEFAULT_MAX_ENTRIES,
	min_level: int = LEVEL_DEBUG,
	emit_to_engine: bool = true
) -> void:
	set_max_entries(max_entries)
	set_min_level(min_level)
	set_emit_to_engine(emit_to_engine)


func set_max_entries(max_entries: int) -> void:
	_max_entries = maxi(1, max_entries)
	while _entries.size() > _max_entries:
		_entries.pop_front()


func get_max_entries() -> int:
	return _max_entries


func set_min_level(level: int) -> void:
	_min_level = level


func get_min_level() -> int:
	return _min_level


func set_emit_to_engine(enabled: bool) -> void:
	_emit_to_engine = enabled


func is_emit_to_engine() -> bool:
	return _emit_to_engine


func attach_import_host(host: RefCounted, forward_reports: bool = false) -> void:
	if host != _host:
		_host = host
		_host_warn_seen.clear()
		_host_warn_count = 0
		_host_warn_chars = 0
	_forward_reports_to_host = forward_reports


func detach_import_host() -> void:
	_host = null
	_forward_reports_to_host = false
	_host_warn_seen.clear()
	_host_warn_count = 0
	_host_warn_chars = 0


func get_import_host() -> RefCounted:
	return _host


func has_import_host() -> bool:
	return _host != null


func get_host_warning_count() -> int:
	return _host_warn_count


func get_host_warning_chars() -> int:
	return _host_warn_chars


func debug(source: String, message: String, context: Dictionary = {}) -> Dictionary:
	return log_entry(LEVEL_DEBUG, source, message, context)


func info(source: String, message: String, context: Dictionary = {}) -> Dictionary:
	return log_entry(LEVEL_INFO, source, message, context)


func warn(source: String, message: String, context: Dictionary = {}) -> Dictionary:
	return log_entry(LEVEL_WARNING, source, message, context)


func error(source: String, message: String, context: Dictionary = {}) -> Dictionary:
	return log_entry(LEVEL_ERROR, source, message, context)


func log(level: int, source: String, message: String, context: Dictionary = {}) -> Dictionary:
	return log_entry(level, source, message, context)


func log_entry(level: int, source: String, message: String, context: Dictionary = {}) -> Dictionary:
	if level < _min_level:
		return {}

	var vu: Variant = _validation_utils()
	var clean_source: String = str(vu.sanitize_line_text(source)).strip_edges()
	if clean_source.is_empty():
		clean_source = "sdk"
	var clean_message: String = str(vu.sanitize_line_text(message))
	var safe_context: Dictionary = _safe_clone_dict(context) if context != null else {}

	var seq: int = _next_seq
	_next_seq += 1

	var entry: Dictionary = {
		"seq": seq,
		"level": level,
		"level_name": _level_name(level),
		"source": clean_source,
		"message": clean_message,
		"context": safe_context,
		"timestamp_msec": Time.get_ticks_msec(),
	}

	if _entries.size() >= _max_entries:
		_entries.pop_front()
	_entries.append(entry)

	var formatted: String = _format_entry(entry)
	if _emit_to_engine:
		if level >= LEVEL_ERROR:
			push_error(formatted)
		elif level >= LEVEL_WARNING:
			push_warning(formatted)
		else:
			print(formatted)

	_forward_to_host(level, clean_source, clean_message, formatted)
	_notify_subscribers(entry)
	return _clone_entry(entry)


func subscribe(callback: Callable) -> int:
	if not callback.is_valid() or callback.get_argument_count() != 1:
		return -1
	var obj: Object = callback.get_object()
	var mname: String = String(callback.get_method())
	if obj != null and not mname.is_empty() and mname != "<anonymous lambda>":
		var expected_total_args: int = 1 + callback.get_bound_arguments_count()
		for minfo: Dictionary in obj.get_method_list():
			if str(minfo.get("name", "")) != mname:
				continue
			var margs: Variant = minfo.get("args", [])
			if margs is Array:
				var args_arr: Array = margs as Array
				if args_arr.size() >= expected_total_args and not args_arr.is_empty():
					var first_arg: Variant = args_arr[0]
					if first_arg is Dictionary:
						var arg_type: int = int((first_arg as Dictionary).get("type", TYPE_NIL))
						if arg_type != TYPE_NIL and arg_type != TYPE_DICTIONARY:
							return -1
			break
	var token: int = _next_token
	_next_token += 1
	_subscribers[token] = callback
	return token


func unsubscribe(token: int) -> bool:
	if not _subscribers.has(token):
		return false
	_subscribers.erase(token)
	return true


func get_entries(min_level: int = 0, since_seq: int = 0, limit: int = 0) -> Array:
	var out: Array = []
	for raw_entry: Dictionary in _entries:
		var entry_seq: int = int(raw_entry.get("seq", 0))
		if entry_seq <= since_seq:
			continue
		if int(raw_entry.get("level", 0)) < min_level:
			continue
		out.append(_clone_entry(raw_entry))
		if limit > 0 and out.size() >= limit:
			break
	return out


func get_warnings(since_seq: int = 0) -> Array:
	return get_entries(LEVEL_WARNING, since_seq, 0)


func clear() -> void:
	_entries.clear()


func size() -> int:
	return _entries.size()


func get_last_seq() -> int:
	return _next_seq - 1


func _level_name(level: int) -> String:
	if level >= LEVEL_ERROR:
		return "ERROR"
	if level >= LEVEL_WARNING:
		return "WARNING"
	if level >= LEVEL_INFO:
		return "INFO"
	return "DEBUG"


func _format_entry(entry: Dictionary) -> String:
	var level_name: String = str(entry.get("level_name", "INFO"))
	var src: String = str(entry.get("source", "sdk"))
	var msg: String = str(entry.get("message", ""))
	return "[FuSdk/%s][%s] %s" % [level_name, src, msg]


func forward_host_warning(source: String, message: String) -> bool:
	if _host == null or not _host.has_method("warn"):
		return false
	var vu: Variant = _validation_utils()
	var clean_source: String = str(vu.sanitize_line_text(source)).strip_edges()
	if clean_source.is_empty():
		clean_source = "sdk"
	var clean_message: String = str(vu.sanitize_line_text(message))
	return _emit_host_warning(clean_source, clean_message)


func _emit_host_warning(clean_source: String, clean_message: String) -> bool:
	if _host == null or not _host.has_method("warn"):
		return false
	var host_msg: String = clean_message if clean_source == "session" else ("[%s] %s" % [clean_source, clean_message])
	if host_msg.is_empty():
		return false
	if _host_warn_seen.has(host_msg):
		return false
	if _host_warn_count >= HOST_MAX_WARNINGS:
		return false
	var sep_len: int = 1 if _host_warn_count > 0 else 0
	var remaining: int = HOST_MAX_NOTES_CHARS - _host_warn_chars - sep_len
	if remaining <= 0:
		return false
	var emit_msg: String = host_msg
	if emit_msg.length() > remaining:
		emit_msg = emit_msg.left(remaining)
	if _host_warn_seen.has(emit_msg):
		return false
	_host_warn_seen[host_msg] = true
	_host_warn_seen[emit_msg] = true
	_host_warn_count += 1
	_host_warn_chars += sep_len + emit_msg.length()
	_host.warn(emit_msg)
	return true


func _forward_to_host(
	level: int,
	clean_source: String,
	clean_message: String,
	formatted: String
) -> void:
	if _host == null:
		return
	if level >= LEVEL_WARNING:
		_emit_host_warning(clean_source, clean_message)
	elif _forward_reports_to_host and _host.has_method("report"):
		var report_msg: String = clean_message if clean_source == "session" else formatted
		_host.report(report_msg)


func _notify_subscribers(entry: Dictionary) -> void:
	if _subscribers.is_empty() or _notify_depth >= MAX_NOTIFY_DEPTH:
		return
	_notify_depth += 1
	var tokens: Array = _subscribers.keys().duplicate()
	for raw_token: Variant in tokens:
		if not _subscribers.has(raw_token):
			continue
		var cb_var: Variant = _subscribers[raw_token]
		if cb_var is Callable:
			var cb: Callable = cb_var as Callable
			if cb.is_valid() and cb.get_argument_count() == 1:
				cb.call(_clone_entry(entry))
	_notify_depth -= 1


func _clone_entry(raw_entry: Dictionary) -> Dictionary:
	var raw_ctx: Variant = raw_entry.get("context", {})
	var safe_ctx: Dictionary = _safe_clone_dict(raw_ctx as Dictionary) if raw_ctx is Dictionary else {}
	return {
		"seq": int(raw_entry.get("seq", 0)),
		"level": int(raw_entry.get("level", LEVEL_INFO)),
		"level_name": str(raw_entry.get("level_name", "INFO")),
		"source": str(raw_entry.get("source", "sdk")),
		"message": str(raw_entry.get("message", "")),
		"context": safe_ctx,
		"timestamp_msec": int(raw_entry.get("timestamp_msec", 0)),
	}


## 复用 DagCloner 进行日志上下文深拷贝（严格保留 LogBus 4 MiB 单条负载上限）。
func _safe_clone_dict(raw: Dictionary) -> Dictionary:
	return _dag_cloner().safe_clone_dict(raw, MAX_CLONE_BYTES, MAX_CONTEXT_DEPTH)
