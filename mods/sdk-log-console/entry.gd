extends RefCounted

const _SDK_PACKAGED_REL_PATH: String = "lib/fu_sdk/v1.gd"
const _SDK_DEV_REL_PATH: String = "../../shared/sdk/fu_sdk/v1.gd"

const _MAX_CHECKLIST_ROWS: int = 32
const _MAX_DRAWING_ITEMS: int = 16
const _MAX_STORED_LOG_ROWS: int = 64
const _DEFAULT_AUDIT_MODULES: Array[String] = [
	"simple_fog",
	"campaign_time",
	"checklist",
	"drawing",
]


func _load_sdk_script() -> Script:
	var self_script := get_script() as Script
	if self_script == null or self_script.resource_path.is_empty():
		return null
	var base_dir: String = self_script.resource_path.split("::")[0].get_base_dir()
	var packaged_path: String = base_dir.path_join(_SDK_PACKAGED_REL_PATH)
	if FileAccess.file_exists(packaged_path) or ResourceLoader.exists(packaged_path):
		return load(packaged_path) as Script
	var dev_path: String = base_dir.path_join(_SDK_DEV_REL_PATH).simplify_path()
	if FileAccess.file_exists(dev_path) or ResourceLoader.exists(dev_path):
		return load(dev_path) as Script
	return null


func _create_sdk() -> RefCounted:
	var sdk_script: Script = _load_sdk_script()
	if sdk_script == null:
		return null
	return sdk_script.new()


func _coerce_bool(value: Variant, fallback: bool) -> bool:
	match typeof(value):
		TYPE_BOOL:
			return value == true
		TYPE_INT:
			return int(value) != 0
		TYPE_FLOAT:
			var f: float = float(value)
			if is_nan(f):
				return fallback
			return f != 0.0
		TYPE_STRING:
			var norm: String = str(value).strip_edges().to_lower()
			match norm:
				"true", "1", "yes", "on":
					return true
				"false", "0", "no", "off":
					return false
				_:
					return fallback
		_:
			return fallback


func _coerce_string(value: Variant, fallback: String = "") -> String:
	if value is String:
		return value as String
	if value is StringName:
		return String(value)
	return fallback


func _coerce_modules_option(value: Variant, fallback: String) -> Variant:
	if value is Array:
		return _parse_module_list(value)
	if value is String or value is StringName:
		return str(value).strip_edges()
	return fallback


func _sanitize_options(raw_options: Variant) -> Dictionary:
	var opts: Dictionary = raw_options if (raw_options is Dictionary) else {}
	return {
		"enabled_modules": _coerce_modules_option(opts.get("enabled_modules", ""), ""),
		"audit_modules": _coerce_modules_option(opts.get("audit_modules", "simple_fog,campaign_time,checklist,drawing"), "simple_fog,campaign_time,checklist,drawing"),
		"disabled_policy": _coerce_string(opts.get("disabled_policy", "preserve"), "preserve").strip_edges().to_lower(),
		"min_level": _coerce_string(opts.get("min_level", "debug"), "debug").strip_edges().to_lower(),
		"forward_reports": _coerce_bool(opts.get("forward_reports", true), true),
		"emit_debug": _coerce_bool(opts.get("emit_debug", true), true),
		"emit_in_world": _coerce_bool(opts.get("emit_in_world", true), true),
		"stress_warnings": _coerce_bool(opts.get("stress_warnings", false), false),
	}


func _parse_module_list(raw_value: Variant) -> Array[String]:
	var out: Array[String] = []
	var seen: Dictionary = {}
	if raw_value is Array:
		for item: Variant in raw_value as Array:
			var mid: String = _coerce_string(item, "").strip_edges().to_lower()
			if not mid.is_empty() and not seen.has(mid):
				seen[mid] = true
				out.append(mid)
	elif raw_value is String or raw_value is StringName:
		var csv: String = str(raw_value)
		for part: String in csv.split(",", false):
			var mid: String = part.strip_edges().to_lower()
			if not mid.is_empty() and not seen.has(mid):
				seen[mid] = true
				out.append(mid)
	return out


func _parse_min_level(level_name: String, logger: RefCounted) -> int:
	var norm: String = level_name.strip_edges().to_lower()
	match norm:
		"error", "err", "40":
			return int(logger.LEVEL_ERROR)
		"warning", "warn", "30":
			return int(logger.LEVEL_WARNING)
		"info", "20":
			return int(logger.LEVEL_INFO)
		_:
			return int(logger.LEVEL_DEBUG)


func _sanitize_utf8_bytes(raw_bytes: PackedByteArray) -> PackedByteArray:
	var n: int = raw_bytes.size()
	var out: PackedByteArray = PackedByteArray()
	var copied_up_to: int = 0
	var dirty: bool = false
	var i: int = 0
	while i < n:
		var b0: int = raw_bytes[i]
		if b0 == 0:
			if not dirty:
				dirty = true
				out = raw_bytes.slice(0, i)
			elif i > copied_up_to:
				out.append_array(raw_bytes.slice(copied_up_to, i))
			i += 1
			copied_up_to = i
			continue
		if b0 < 0x80:
			i += 1
			continue
		var seq_len: int = 0
		if b0 >= 0xC2 and b0 <= 0xDF:
			if i + 1 < n and (raw_bytes[i + 1] & 0xC0) == 0x80:
				seq_len = 2
		elif b0 >= 0xE0 and b0 <= 0xEF:
			if i + 2 < n:
				var b1: int = raw_bytes[i + 1]
				var b2: int = raw_bytes[i + 2]
				if (b1 & 0xC0) == 0x80 and (b2 & 0xC0) == 0x80:
					if (b0 == 0xE0 and b1 < 0xA0) or (b0 == 0xED and b1 > 0x9F):
						seq_len = 0
					else:
						seq_len = 3
		elif b0 >= 0xF0 and b0 <= 0xF4:
			if i + 3 < n:
				var b1: int = raw_bytes[i + 1]
				var b2: int = raw_bytes[i + 2]
				var b3: int = raw_bytes[i + 3]
				if (b1 & 0xC0) == 0x80 and (b2 & 0xC0) == 0x80 and (b3 & 0xC0) == 0x80:
					if (b0 == 0xF0 and b1 < 0x90) or (b0 == 0xF4 and b1 > 0x8F):
						seq_len = 0
					else:
						seq_len = 4
		if seq_len > 0:
			i += seq_len
			continue
		if not dirty:
			dirty = true
			out = raw_bytes.slice(0, i)
		elif i > copied_up_to:
			out.append_array(raw_bytes.slice(copied_up_to, i))
		out.append(0xEF)
		out.append(0xBF)
		out.append(0xBD)
		i += 1
		copied_up_to = i
	if not dirty:
		return raw_bytes
	if copied_up_to < n:
		out.append_array(raw_bytes.slice(copied_up_to, n))
	return out


func _strip_json_nul_escapes(text: String) -> String:
	if text.find("\\") == -1:
		return text
	var out: String = ""
	var n: int = text.length()
	var copied_up_to: int = 0
	var i: int = 0
	while i < n:
		if text.unicode_at(i) == 92:
			if i + 1 < n:
				var next_ch: int = text.unicode_at(i + 1)
				if next_ch == 92:
					i += 2
					continue
				if (next_ch == 117 or next_ch == 85) and i + 5 < n:
					if text.substr(i + 2, 4) == "0000":
						out += text.substr(copied_up_to, i - copied_up_to)
						i += 6
						copied_up_to = i
						continue
		i += 1
	if copied_up_to == 0:
		return text
	if copied_up_to < n:
		out += text.substr(copied_up_to, n - copied_up_to)
	return out


func _read_utf8_text(path: String) -> Dictionary:
	if path.is_empty() or not FileAccess.file_exists(path):
		return {"exists": false, "bytes": 0, "text": ""}
	var f: FileAccess = FileAccess.open(path, FileAccess.READ)
	if f == null:
		return {"exists": false, "bytes": 0, "text": ""}
	var length: int = maxi(0, int(f.get_length()))
	var text: String = ""
	if length > 0:
		var raw_bytes: PackedByteArray = f.get_buffer(length)
		var clean_bytes: PackedByteArray = _sanitize_utf8_bytes(raw_bytes)
		text = clean_bytes.get_string_from_utf8()
	f.close()
	return {"exists": true, "bytes": length, "text": text}


func _count_non_empty_lines(text: String) -> int:
	var count: int = 0
	for raw_line: String in text.split("\n", true):
		var clean_line: String = raw_line.replace("\r", "").strip_edges()
		if not clean_line.is_empty():
			count += 1
	return count


func _strip_nul(text: String) -> String:
	var has_nul: bool = false
	for i: int in range(text.length()):
		if text.unicode_at(i) == 0:
			has_nul = true
			break
	if not has_nul:
		return text
	var out: String = ""
	for i: int in range(text.length()):
		if text.unicode_at(i) != 0:
			out += text.substr(i, 1)
	return out


func _sanitize_single_line(text: String, max_len: int) -> String:
	var clean: String = _strip_nul(text).replace("\r", " ").replace("\n", " ").strip_edges()
	if clean.length() > max_len:
		clean = clean.left(max_len).strip_edges()
	return clean


func _emit_error_safely(logger: RefCounted, source: String, message: String, context: Dictionary = {}) -> Dictionary:
	if logger == null:
		return {}
	var prev_emit: bool = bool(logger.is_emit_to_engine())
	logger.set_emit_to_engine(false)
	var entry: Dictionary = logger.error(source, message, context)
	logger.set_emit_to_engine(prev_emit)
	return entry


func _replay_log_line(logger: RefCounted, line: String, line_num: int, emit_debug: bool) -> void:
	var clean: String = line.replace("\r", "").strip_edges()
	if clean.is_empty():
		return
	var upper: String = clean.to_upper()
	var ctx: Dictionary = {"line": line_num}
	if upper.begins_with("DEBUG") or upper.begins_with("[DEBUG]"):
		if emit_debug:
			logger.debug("log_input", clean, ctx)
	elif upper.begins_with("WARNING") or upper.begins_with("WARN") or upper.begins_with("[WARNING]") or upper.begins_with("[WARN]"):
		logger.warn("log_input", clean, ctx)
	elif upper.begins_with("ERROR") or upper.begins_with("ERR") or upper.begins_with("[ERROR]"):
		_emit_error_safely(logger, "log_input", clean, ctx)
	elif upper.begins_with("INFO") or upper.begins_with("[INFO]"):
		logger.info("log_input", clean, ctx)
	else:
		logger.info("log_input", clean, ctx)


func _coerce_level_string(raw_level: Variant, fallback: String = "info") -> String:
	match typeof(raw_level):
		TYPE_INT:
			return String.num_int64(int(raw_level))
		TYPE_FLOAT:
			var f: float = float(raw_level)
			if is_nan(f) or is_inf(f):
				return fallback
			return String.num_int64(int(round(f)))
		TYPE_STRING, TYPE_STRING_NAME:
			var s: String = str(raw_level).strip_edges().to_lower()
			return s if not s.is_empty() else fallback
		_:
			return fallback


func _replay_json_entry(logger: RefCounted, item: Variant, idx: int, emit_debug: bool) -> void:
	if item is String:
		_replay_log_line(logger, str(item), idx + 1, emit_debug)
		return
	if not (item is Dictionary):
		return
	var d: Dictionary = item as Dictionary
	var raw_lvl: Variant = d.get("level", null)
	if raw_lvl == null:
		raw_lvl = d.get("level_name", "info")
	var lvl: String = _coerce_level_string(raw_lvl, "info")
	var src: String = _coerce_string(d.get("source", "json_input"), "json_input").strip_edges()
	if src.is_empty():
		src = "json_input"
	var msg: String = _coerce_string(d.get("message", d.get("msg", "")), "")
	if msg.is_empty():
		msg = JSON.stringify(d)
	var raw_ctx: Variant = d.get("context", {})
	var ctx: Dictionary = raw_ctx as Dictionary if (raw_ctx is Dictionary) else {}
	match lvl:
		"debug", "10":
			if emit_debug:
				logger.debug(src, msg, ctx)
		"warning", "warn", "30":
			logger.warn(src, msg, ctx)
		"error", "err", "40":
			_emit_error_safely(logger, src, msg, ctx)
		_:
			logger.info(src, msg, ctx)


func inspect_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:
	var sdk: RefCounted = _create_sdk()
	if sdk == null:
		return {"ok": false, "reason": "fu_sdk_not_found"}
	var clean_options: Dictionary = _sanitize_options(options)
	var session = sdk.create_session(host, clean_options)
	if session.is_cancelled():
		return session.err_cancelled()

	session.report_progress("正在检查诊断输入文件...")
	var file_info: Dictionary = _read_utf8_text(path)
	var exists: bool = bool(file_info.get("exists", false))
	var text: String = str(file_info.get("text", ""))
	var decoded_bytes: int = text.to_utf8_buffer().size() if exists else 0
	var records_count: int = 0
	var text_count: int = 0
	var unsupported_count: int = 0
	var display_name: String = ""

	if exists and not text.strip_edges().is_empty():
		var ext: String = path.get_extension().strip_edges().to_lower()
		var parser := JSON.new()
		var json_candidate: String = _strip_json_nul_escapes(text)
		if parser.parse(json_candidate) == OK:
			var parsed: Variant = parser.data
			if parsed is Dictionary:
				var pd: Dictionary = parsed as Dictionary
				display_name = _coerce_string(pd.get("name", ""), "").strip_edges()
				var entries_var: Variant = pd.get("entries", null)
				if entries_var is Array:
					records_count = (entries_var as Array).size()
					text_count = records_count
				else:
					records_count = pd.size()
			elif parsed is Array:
				records_count = (parsed as Array).size()
				text_count = records_count
			else:
				records_count = 1
		else:
			records_count = _count_non_empty_lines(text)
			text_count = records_count
			if ext == "json":
				unsupported_count = 1

	return session.ok_inspect(
		path,
		{
			"records": records_count,
			"text": text_count,
			"unsupported": unsupported_count,
		},
		{},
		decoded_bytes,
		display_name
	)


func prepare_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:
	var sdk: RefCounted = _create_sdk()
	if sdk == null:
		return {"ok": false, "reason": "fu_sdk_not_found"}
	var clean_options: Dictionary = _sanitize_options(options)
	var session = sdk.create_session(host, clean_options)
	if session.is_cancelled():
		return session.err_cancelled()

	var builder = sdk.create_world_builder(session, 150.0)
	var init_res: Dictionary = builder.setup(session, 150.0)
	if not bool(init_res.get("ok", false)):
		return init_res

	var logger: RefCounted = session.get_logger()
	var min_level: int = _parse_min_level(str(clean_options.get("min_level", "debug")), logger)
	logger.set_min_level(min_level)
	var forward_reports: bool = bool(clean_options.get("forward_reports", true))
	logger.attach_import_host(host, forward_reports)

	session.report_progress("正在初始化 SDK 日志控制台与 R2 模块审计...")

	var live_entries: Array[Dictionary] = []
	var sub_token: int = int(logger.subscribe(func(entry: Dictionary) -> void:
		live_entries.append(entry)
	))

	var emit_debug: bool = bool(clean_options.get("emit_debug", true))
	var emit_in_world: bool = bool(clean_options.get("emit_in_world", true))
	var stress_warnings: bool = bool(clean_options.get("stress_warnings", false))
	var disabled_policy: String = str(clean_options.get("disabled_policy", "preserve"))
	if disabled_policy != "skip":
		disabled_policy = "preserve"

	var enabled_list: Array[String] = _parse_module_list(clean_options.get("enabled_modules", ""))
	var audit_list: Array[String] = _parse_module_list(clean_options.get("audit_modules", ""))
	if audit_list.is_empty():
		audit_list = _DEFAULT_AUDIT_MODULES.duplicate()

	var records_count: int = 0
	var input_kind: String = "empty"

	var file_info: Dictionary = _read_utf8_text(path)
	var exists: bool = bool(file_info.get("exists", false))
	var raw_bytes: int = int(file_info.get("bytes", 0))
	var raw_text: String = str(file_info.get("text", ""))

	if not exists or raw_bytes <= 0 or raw_text.strip_edges().is_empty():
		input_kind = "empty_or_missing"
		logger.warn(
			"sdk_log_console",
			"输入文件为空或不存在，已继续执行默认 SDK 模块诊断审计。",
			{"path": path.get_file() if not path.is_empty() else ""}
		)
	else:
		var parser := JSON.new()
		var json_candidate: String = _strip_json_nul_escapes(raw_text)
		if parser.parse(json_candidate) == OK:
			var parsed: Variant = parser.data
			if parsed is Dictionary:
				input_kind = "json"
				var pd: Dictionary = parsed as Dictionary
				if pd.has("emit_debug"):
					emit_debug = _coerce_bool(pd.get("emit_debug"), emit_debug)
				if pd.has("emit_in_world"):
					emit_in_world = _coerce_bool(pd.get("emit_in_world"), emit_in_world)
				if pd.has("disabled_policy"):
					var json_pol: String = _coerce_string(pd.get("disabled_policy"), disabled_policy).strip_edges().to_lower()
					if json_pol == "skip" or json_pol == "preserve":
						disabled_policy = json_pol
				if pd.has("enabled_modules"):
					enabled_list = _parse_module_list(pd.get("enabled_modules"))
				if pd.has("audit_modules"):
					var parsed_audit: Array[String] = _parse_module_list(pd.get("audit_modules"))
					if not parsed_audit.is_empty():
						audit_list = parsed_audit
				if _coerce_string(pd.get("mode", ""), "").strip_edges().to_lower() == "stress_warnings":
					stress_warnings = true

				var entries_var: Variant = pd.get("entries", null)
				if entries_var is Array:
					var entries_arr: Array = entries_var as Array
					records_count = entries_arr.size()
					for i: int in range(entries_arr.size()):
						_replay_json_entry(logger, entries_arr[i], i, emit_debug)
				else:
					records_count = pd.size()
					if emit_debug:
						logger.debug(
							"sdk_log_console",
							"已解析诊断配置 JSON（%d 个键）。" % pd.size(),
							{"keys": pd.size()}
						)
			elif parsed is Array:
				input_kind = "json_array"
				var arr: Array = parsed as Array
				records_count = arr.size()
				for i: int in range(arr.size()):
					_replay_json_entry(logger, arr[i], i, emit_debug)
			else:
				input_kind = "json_scalar"
				records_count = 1
				logger.info("sdk_log_console", "已读取标量 JSON 输入：" + str(parsed))
		else:
			var ext: String = path.get_extension().strip_edges().to_lower()
			if ext == "json":
				input_kind = "corrupt_json"
				logger.warn(
					"sdk_log_console",
					"JSON 解析失败，已降级为逐行文本日志回放。",
					{"file": path.get_file()}
				)
			else:
				input_kind = "log_text"
			var lines: PackedStringArray = raw_text.split("\n", true)
			for i: int in range(lines.size()):
				var clean_line: String = lines[i].replace("\r", "").strip_edges()
				if not clean_line.is_empty():
					records_count += 1
					_replay_log_line(logger, clean_line, i + 1, emit_debug)

	if not enabled_list.is_empty():
		builder.set_enabled_modules(enabled_list)
	builder.set_disabled_module_policy(disabled_policy)

	var registry: RefCounted = builder.get_module_registry()
	if emit_debug and registry != null:
		var catalog_list: Array = registry.list_modules(true)
		logger.debug(
			"sdk_log_console",
			"ModuleRegistry 已就绪：共 %d 个原生/候选模块，未启用策略=%s。" % [catalog_list.size(), disabled_policy],
			{"catalog_size": catalog_list.size(), "disabled_policy": disabled_policy}
		)

	var audited_summary: Dictionary = {}
	for mid: String in audit_list:
		var check_res: Dictionary = {}
		if registry != null:
			check_res = registry.check_and_warn(mid, "console_audit")
		var psdk: RefCounted = builder.get_plugin_sdk(mid)
		var avail: Dictionary = psdk.get_availability() if (psdk != null and psdk.has_method("get_availability")) else {}
		var status_str: String = str(check_res.get("status", avail.get("status", "unknown")))
		var is_en: bool = bool(check_res.get("enabled", false))
		audited_summary[mid] = {
			"status": status_str,
			"enabled": is_en,
			"has_sdk": psdk != null,
		}
		logger.info(
			"sdk_log_console",
			"模块审计 [%s]：status=%s, enabled=%s, policy=%s" % [mid, status_str, str(is_en), disabled_policy],
			{"module_id": mid, "status": status_str, "enabled": is_en}
		)

	if stress_warnings:
		for w_idx: int in range(1, 121):
			logger.warn(
				"sdk_log_console",
				"压力警告 #%03d" % w_idx,
				{"index": w_idx}
			)

	var board_entries: Array = logger.get_entries(0, 0, 0)
	var checklist_written: int = 0
	var drawing_written: int = 0

	if emit_in_world:
		var cl: RefCounted = builder.checklist()
		if cl != null:
			var max_cl: int = mini(board_entries.size(), _MAX_CHECKLIST_ROWS)
			for i: int in range(max_cl):
				var entry: Dictionary = board_entries[i] as Dictionary
				var lvl_name: String = str(entry.get("level_name", "INFO"))
				var src_name: String = str(entry.get("source", "sdk"))
				var raw_msg: String = str(entry.get("message", ""))
				var title: String = _sanitize_single_line("[%s][%s] %s" % [lvl_name, src_name, raw_msg], int(cl.MAX_TITLE))
				if title.is_empty():
					title = "[%s] log #%d" % [lvl_name, i + 1]
				var desc: String = _strip_nul(raw_msg).left(int(cl.MAX_DESCRIPTION))
				var row: Dictionary = cl.make_row(title, {
					"description": desc,
					"category": lvl_name.left(int(cl.MAX_CATEGORY)),
					"audience": "gm",
					"source": "",
					"manual": false,
					"done": int(entry.get("level", 20)) < int(logger.LEVEL_WARNING),
					"order": i + 1,
				})
				var cl_res: Dictionary = cl.add_row("", row)
				if bool(cl_res.get("skipped", false)):
					break
				if bool(cl_res.get("ok", false)):
					checklist_written += 1

		var dr: RefCounted = builder.drawing()
		var floor_uid: String = builder.get_active_floor_uid()
		if dr != null and not floor_uid.is_empty():
			var max_dr: int = mini(board_entries.size(), _MAX_DRAWING_ITEMS)
			var xf: Transform2D = dr.make_text_transform(Vector2.ZERO, 0.0, Vector2.ONE)
			for i: int in range(max_dr):
				var entry: Dictionary = board_entries[i] as Dictionary
				var lvl_val: int = int(entry.get("level", 20))
				var lvl_name: String = str(entry.get("level_name", "INFO"))
				var src_name: String = str(entry.get("source", "sdk"))
				var msg_txt: String = _sanitize_single_line("[%s][%s] %s" % [lvl_name, src_name, str(entry.get("message", ""))], 240)
				if msg_txt.is_empty():
					msg_txt = "[%s] log #%d" % [lvl_name, i + 1]
				var col: Color = Color(0.18, 0.24, 0.30, 1.0)
				if lvl_val >= int(logger.LEVEL_ERROR):
					col = Color(0.82, 0.16, 0.16, 1.0)
				elif lvl_val >= int(logger.LEVEL_WARNING):
					col = Color(0.85, 0.52, 0.08, 1.0)
				elif lvl_val <= int(logger.LEVEL_DEBUG):
					col = Color(0.45, 0.50, 0.56, 1.0)
				var item: Dictionary = dr.make_text_item(
					floor_uid,
					Vector2(64.0, 64.0 + float(i) * 34.0),
					msg_txt,
					col,
					"sans",
					18,
					xf,
					"world",
					i + 1,
					"sdk_log_console"
				)
				var dr_res: Dictionary = dr.add_world_text(item)
				if bool(dr_res.get("skipped", false)):
					break
				if bool(dr_res.get("ok", false)):
					drawing_written += 1

	var all_entries: Array = logger.get_entries(0, 0, 0)
	var warn_entries: Array = logger.get_warnings(0)
	var stored_tail: Array = []
	var start_idx: int = maxi(0, all_entries.size() - _MAX_STORED_LOG_ROWS)
	for i: int in range(start_idx, all_entries.size()):
		var ent: Dictionary = all_entries[i] as Dictionary
		stored_tail.append({
			"seq": int(ent.get("seq", 0)),
			"level": int(ent.get("level", 0)),
			"level_name": str(ent.get("level_name", "")),
			"source": str(ent.get("source", "")),
			"message": str(ent.get("message", "")).left(256),
		})

	builder.set_module_state("sdk_log_console", 1, {
		"input_kind": input_kind,
		"disabled_policy": disabled_policy,
		"audited_modules": audited_summary,
		"total_entries": all_entries.size(),
		"warning_count": warn_entries.size(),
		"live_subscribed_count": live_entries.size(),
		"host_warning_count": int(logger.get_host_warning_count()),
		"host_warning_chars": int(logger.get_host_warning_chars()),
		"checklist_rows": checklist_written,
		"drawing_items": drawing_written,
		"entries_tail": stored_tail,
	})

	if not builder.finish_geometry_preview():
		logger.unsubscribe(sub_token)
		return session.err_cancelled() if session.is_cancelled() else session.err_failed("几何预览未能完成，请重试。")

	session.report_progress("SDK 日志控制台诊断完成（日志 %d 条，警告 %d 条）。" % [all_entries.size(), warn_entries.size()])
	logger.unsubscribe(sub_token)
	return builder.build_result(records_count, 0)
