extends RefCounted
## Fu vtt 原生可选插件 SDK：checklist（任务清单模块配置 schema v2 与 13 事件宏规则校验）
##
## 对应官方源码：modules/checklist/checklist.gd、book.gd、rule.gd、editor.gd。

const MODULE_ID: String = "checklist"
const MODULE_VERSION: int = 1
const SCHEMA_VERSION: int = 2
const MAX_ROWS: int = 128
const MAX_ORDER: int = 100000

const MAX_TITLE: int = 96
const MAX_DESCRIPTION: int = 512
const MAX_CATEGORY: int = 48
const MAX_PLAYER_ID: int = 128
const MAX_ENTITY_ID: int = 128
const MAX_SOURCE: int = 2048
const MAX_LAST_MOTION: int = 128

const AUDIENCES: Array[String] = ["all", "player", "gm"]
const REQUIRED_ROW_KEYS: Array[String] = [
	"title",
	"description",
	"category",
	"audience",
	"player_id",
	"entity_id",
	"source",
	"manual",
	"done",
	"archived",
	"order",
	"last_motion",
]

const RULE_EVENTS: Dictionary = {
	"entity.motion_committed": ["event.cause", "event.player_id", "event.entity_id", "task.player_id", "task.entity_id"],
	"camera.navigated": ["event.kind"],
	"mode.changed": ["event.old", "event.new"],
	"selection.changed": ["event.count", "event.entity_id", "event.entity_name", "task.entity_id"],
	"comp.added": ["event.comp_id", "event.entity_id", "event.entity_name", "task.entity_id"],
	"comp.removed": ["event.comp_id", "event.entity_id", "event.entity_name", "task.entity_id"],
	"comp.state_changed": ["event.comp_id", "event.entity_id", "event.entity_name", "task.entity_id"],
	"drawing.stroke_committed": ["event.op", "event.coords", "event.tool"],
	"ui.panel_opened": ["event.panel_id", "event.source", "event.tab_id"],
	"entity.spawned": ["event.entity_id", "event.entity_name", "event.entity_type", "task.entity_id"],
	"floor.changed": ["event.floor_uid", "event.floor_name"],
	"module.toggled": ["event.module_id", "event.enabled"],
	"portal.teleported": ["event.entity_id", "event.entity_name", "task.entity_id"],
}

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


func default_row() -> Dictionary:
	return {
		"title": "",
		"description": "",
		"category": "",
		"audience": "all",
		"player_id": "",
		"entity_id": "",
		"source": "",
		"manual": false,
		"done": false,
		"archived": false,
		"order": 0,
		"last_motion": "",
	}


func default_state() -> Dictionary:
	return {
		"schema": SCHEMA_VERSION,
		"rows": {},
	}


func make_row(title: String, opts: Dictionary = {}) -> Dictionary:
	var val_u: Variant = _value_utils()
	var row: Dictionary = default_row()
	row["title"] = title
	if opts.has("description"):
		row["description"] = str(val_u.coerce_str_scalar(opts["description"], ""))
	if opts.has("category"):
		row["category"] = str(val_u.coerce_str_scalar(opts["category"], ""))
	if opts.has("audience"):
		row["audience"] = str(val_u.coerce_str_scalar(opts["audience"], ""))
	if opts.has("player_id"):
		row["player_id"] = str(val_u.coerce_str_scalar(opts["player_id"], ""))
	if opts.has("entity_id"):
		row["entity_id"] = str(val_u.coerce_str_scalar(opts["entity_id"], ""))
	if opts.has("source"):
		row["source"] = str(val_u.coerce_str_scalar(opts["source"], ""))
	if opts.has("manual"):
		row["manual"] = bool(val_u.coerce_bool(opts["manual"], false, false))
	if opts.has("done"):
		row["done"] = bool(val_u.coerce_bool(opts["done"], false, false))
	if opts.has("archived"):
		row["archived"] = bool(val_u.coerce_bool(opts["archived"], false, false))
	if opts.has("order"):
		row["order"] = int(val_u.coerce_int(opts["order"], 0, false))
	if opts.has("last_motion"):
		row["last_motion"] = str(val_u.coerce_str_scalar(opts["last_motion"], ""))
	if opts.has("more_entity_ids") and opts["more_entity_ids"] is Array:
		var more: Array = []
		for item: Variant in opts["more_entity_ids"] as Array:
			more.append(str(val_u.coerce_str_scalar(item, "")))
		row["more_entity_ids"] = more
	return row


func validate_macro(source: String) -> Dictionary:
	if source.length() > MAX_SOURCE:
		return {"ok": false, "reason": "checklist_macro_too_long"}
	if bool(_validation_utils().has_nul(source)):
		return {"ok": false, "reason": "checklist_macro_nul"}
	if source.strip_edges().is_empty():
		return {"ok": true, "ops": []}

	var lines: PackedStringArray = source.split("\n")
	var blocks: Array = []
	var current_block: Dictionary = {}
	var current_has_complete: bool = false
	var pending_if: Array = []
	var has_pending_if: bool = false
	var pending_indent: int = 0

	for index: int in range(lines.size()):
		var raw: String = lines[index].replace("\r", "").replace("\t", "    ")
		var clause: String = raw.strip_edges()
		if clause.is_empty():
			continue
		var indent: int = raw.length() - raw.strip_edges(true, false).length()
		if indent == 0:
			if has_pending_if:
				return _rule_error(index + 1, "if 分支缺少 return 或 task.complete_once()。")
			if not current_block.is_empty():
				if not current_has_complete:
					return _rule_error(index + 1, "事件 %s 需要一个完整的 task.complete_once() 动作。" % str(current_block["event"]))
				blocks.append(current_block)
				current_block = {}
				current_has_complete = false
			if not clause.begins_with("on ") or not clause.ends_with(":"):
				return _rule_error(index + 1, "首行应为 on <事件名>:")
			var event_name: String = clause.substr(3, clause.length() - 4).strip_edges()
			if not RULE_EVENTS.has(event_name):
				return _rule_error(index + 1, "不支持的事件名：%s" % event_name)
			current_block = {"event": event_name, "steps": []}
			continue
		if current_block.is_empty():
			return _rule_error(index + 1, "首行应为 on <事件名>:")
		if has_pending_if:
			if indent <= pending_indent:
				return _rule_error(index + 1, "请把动作缩进在上一条 if 下面。")
			has_pending_if = false
			if clause == "return":
				(current_block["steps"] as Array).append({"type": "return_if", "or_branches": pending_if})
			elif clause == "task.complete_once()":
				(current_block["steps"] as Array).append({"type": "complete_if", "or_branches": pending_if})
				current_has_complete = true
			else:
				return _rule_error(index + 1, "if 下面只能写 return 或 task.complete_once()。")
			pending_if = []
		elif clause.begins_with("if ") and clause.ends_with(":"):
			var expr: String = clause.substr(3, clause.length() - 4).strip_edges()
			var ev_fields: Array = RULE_EVENTS[current_block["event"]] as Array
			var parsed_cond: Dictionary = _parse_rule_condition(expr, ev_fields, index + 1)
			if not bool(parsed_cond.get("ok", false)):
				return parsed_cond
			pending_if = parsed_cond["or_branches"] as Array
			has_pending_if = true
			pending_indent = indent
		elif clause == "task.complete_once()":
			(current_block["steps"] as Array).append({"type": "complete"})
			current_has_complete = true
		else:
			return _rule_error(index + 1, "未知语句。可使用 if、return 或 task.complete_once()。")

	if has_pending_if:
		return _rule_error(lines.size(), "if 语句缺少后续动作。")
	if not current_block.is_empty():
		if not current_has_complete:
			return _rule_error(lines.size(), "规则需要一个完整的 task.complete_once() 动作。")
		blocks.append(current_block)
	if blocks.is_empty():
		return _rule_error(1, "规则需要一个完整的 task.complete_once() 动作。")
	return {"ok": true, "ops": blocks}


func validate_row(row_var: Variant, allow_mod_source: bool = true) -> Dictionary:
	if not (row_var is Dictionary):
		return {"ok": false, "reason": "invalid_row_type"}
	var row: Dictionary = row_var as Dictionary
	var expected_size: int = REQUIRED_ROW_KEYS.size() + (1 if row.has("more_entity_ids") else 0)
	if row.size() != expected_size:
		return {"ok": false, "reason": "invalid_row_keys"}
	for req_k: String in REQUIRED_ROW_KEYS:
		if not row.has(req_k):
			return {"ok": false, "reason": "missing_row_key:" + req_k}

	var limits: Dictionary = {
		"title": MAX_TITLE,
		"description": MAX_DESCRIPTION,
		"category": MAX_CATEGORY,
		"player_id": MAX_PLAYER_ID,
		"entity_id": MAX_ENTITY_ID,
		"source": MAX_SOURCE,
		"last_motion": MAX_LAST_MOTION,
	}
	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	for k: Variant in limits.keys():
		var ks: String = str(k)
		var val: Variant = row.get(ks, null)
		if not (val is String):
			return {"ok": false, "reason": "invalid_string_field:" + ks}
		var s: String = str(val)
		if s.length() > int(limits[ks]) or bool(valid_u.has_nul(s)):
			return {"ok": false, "reason": "text_limit_exceeded:" + ks}

	var title: String = str(row["title"])
	var category: String = str(row["category"])
	if title.strip_edges().is_empty() or title.contains("\n") or title.contains("\r"):
		return {"ok": false, "reason": "invalid_title"}
	if category.contains("\n") or category.contains("\r"):
		return {"ok": false, "reason": "invalid_category"}

	var audience: Variant = row.get("audience", null)
	if not (audience is String) or not (str(audience) in AUDIENCES):
		return {"ok": false, "reason": "invalid_audience"}

	var order_parsed: Dictionary = val_u.parse_int_val(row.get("order", null))
	if not bool(order_parsed["ok"]) or absi(int(order_parsed["value"])) > MAX_ORDER:
		return {"ok": false, "reason": "invalid_order"}
	var order_val: int = int(order_parsed["value"])

	for bk: String in ["manual", "done", "archived"]:
		if not (row.get(bk, null) is bool):
			return {"ok": false, "reason": "invalid_bool_field:" + bk}

	var done: bool = bool(row["done"])
	var archived: bool = bool(row["archived"])
	if archived and not done:
		return {"ok": false, "reason": "archived_requires_done"}

	var player_id: String = str(row["player_id"])
	if str(audience) == "player" and player_id.strip_edges().is_empty():
		return {"ok": false, "reason": "player_audience_requires_player_id"}

	var entity_id: String = str(row["entity_id"])
	if row.has("more_entity_ids"):
		var extra_v: Variant = row.get("more_entity_ids", null)
		if entity_id.is_empty() or not (extra_v is Array):
			return {"ok": false, "reason": "invalid_more_entity_ids"}
		var extra: Array = extra_v as Array
		if extra.size() > MAX_ROWS - 1:
			return {"ok": false, "reason": "more_entity_ids_limit_exceeded"}
		var seen: Dictionary = {entity_id: true}
		for member: Variant in extra:
			if not (member is String) or not bool(valid_u.is_valid_uid(str(member))) or seen.has(str(member)):
				return {"ok": false, "reason": "invalid_more_entity_member"}
			seen[str(member)] = true

	var src: String = str(row["source"])
	if not src.strip_edges().is_empty():
		if _is_mod_source_tag(src):
			if not allow_mod_source:
				return _rule_error(1, "首行应为 on <事件名>:")
		else:
			var macro_res: Dictionary = validate_macro(src)
			if not bool(macro_res.get("ok", false)):
				return macro_res

	var clean_row: Dictionary = {
		"title": title,
		"description": str(row["description"]),
		"category": category,
		"audience": str(audience),
		"player_id": player_id,
		"entity_id": entity_id,
		"source": src,
		"manual": bool(row["manual"]),
		"done": done,
		"archived": archived,
		"order": order_val,
		"last_motion": str(row["last_motion"]),
	}
	if row.has("more_entity_ids"):
		var more_out: Array[String] = []
		for member: Variant in row["more_entity_ids"] as Array:
			more_out.append(str(member))
		clean_row["more_entity_ids"] = more_out
	return {"ok": true, "data": clean_row}


func validate_state(state_var: Variant, allow_mod_source: bool = true) -> Dictionary:
	if not (state_var is Dictionary):
		return {"ok": false, "reason": "invalid_checklist_state_type"}
	var state: Dictionary = state_var as Dictionary
	if state.is_empty():
		return {"ok": true, "data": default_state()}
	if state.size() != 2 or not state.has("schema") or not state.has("rows"):
		return {"ok": false, "reason": "invalid_checklist_envelope"}
	var schema_parsed: Dictionary = _value_utils().parse_int_val(state["schema"])
	if not bool(schema_parsed["ok"]) or not (int(schema_parsed["value"]) in [1, 2]):
		return {"ok": false, "reason": "invalid_checklist_schema"}
	var rows_v: Variant = state["rows"]
	if not (rows_v is Dictionary):
		return {"ok": false, "reason": "invalid_checklist_rows_type"}
	var rows: Dictionary = rows_v as Dictionary
	if rows.size() > MAX_ROWS:
		return {"ok": false, "reason": "checklist_rows_limit_exceeded"}

	var valid_u: Variant = _validation_utils()
	var clean_rows: Dictionary = {}
	for raw_id: Variant in rows.keys():
		if not (raw_id is String) or not bool(valid_u.is_valid_uid(str(raw_id))):
			return {"ok": false, "reason": "invalid_checklist_row_id"}
		var row_res: Dictionary = validate_row(rows[raw_id], allow_mod_source)
		if not bool(row_res.get("ok", false)):
			return row_res
		clean_rows[str(raw_id)] = row_res["data"]

	return {
		"ok": true,
		"data": {
			"schema": SCHEMA_VERSION,
			"rows": clean_rows,
		},
	}


func configure_checklist(state: Dictionary, allow_mod_source: bool = true) -> Dictionary:
	var gate: Dictionary = _check_gate("configure_checklist")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var checked: Dictionary = validate_state(state, allow_mod_source)
	if not bool(checked.get("ok", false)):
		var reason: String = str(checked.get("reason", "invalid_checklist_state"))
		_warn("checklist 配置校验失败：%s" % reason)
		return {"ok": false, "reason": reason}

	var normalized: Dictionary = checked["data"] as Dictionary
	if _log_bus != null:
		var norm_rows: Dictionary = normalized.get("rows", {}) as Dictionary
		for rk: Variant in norm_rows.keys():
			var r_dict: Variant = norm_rows[rk]
			if r_dict is Dictionary and _is_mod_source_tag(str((r_dict as Dictionary).get("source", ""))):
				_log_bus.warn(MODULE_ID, "checklist row 使用了兼容标记 'mod:<tag>'；官方宿主 Book.restore()/Rule.parse() 仅接受 '' 或 'on <event>:' 规则。")
				break
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, normalized))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"config": normalized,
		"enabled": bool(gate.get("enabled", false)),
		"policy": str(gate.get("policy", "preserve")),
		"preserved": not bool(gate.get("enabled", false)),
	}


func set_state(state: Dictionary) -> Dictionary:
	return configure_checklist(state)


func add_row(row_id: String, row: Dictionary, allow_mod_source: bool = true) -> Dictionary:
	var gate: Dictionary = _check_gate("add_row")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var current: Dictionary = get_state()
	if current.is_empty():
		current = default_state()
	var raw_rows: Variant = current.get("rows", null)
	if raw_rows == null:
		if current.has("rows"):
			return {"ok": false, "reason": "invalid_checklist_rows_type"}
		raw_rows = {}
	elif not (raw_rows is Dictionary):
		return {"ok": false, "reason": "invalid_checklist_rows_type"}
	var rows_dict: Dictionary = raw_rows as Dictionary

	var clean_id: String = row_id.strip_edges().to_lower()
	if clean_id.is_empty():
		var cur_count: int = rows_dict.size()
		clean_id = ("fu_sdk:checklist:%d:%s" % [cur_count, str(_value_utils().coerce_str_scalar(row.get("title", ""), ""))]).sha256_text().left(32)
	if not bool(_validation_utils().is_valid_uid(clean_id)):
		return {"ok": false, "reason": "invalid_checklist_row_id"}
	var row_res: Dictionary = validate_row(row, allow_mod_source)
	if not bool(row_res.get("ok", false)):
		return row_res

	var clean_row: Dictionary = row_res["data"] as Dictionary
	if _log_bus != null and _is_mod_source_tag(str(clean_row.get("source", ""))):
		_log_bus.warn(MODULE_ID, "checklist row 使用了兼容标记 'mod:<tag>'；官方宿主 Book.restore()/Rule.parse() 仅接受 '' 或 'on <event>:' 规则。")

	var clone_budget: Array = [32768, false]
	var rows: Dictionary = _safe_clone_dict(rows_dict, 0, [], clone_budget)
	if bool(clone_budget[1]):
		return {"ok": false, "reason": "checklist_rows_too_large"}
	if not rows.has(clean_id) and rows.size() >= MAX_ROWS:
		return {"ok": false, "reason": "checklist_rows_limit_exceeded"}
	rows[clean_id] = clean_row
	var next_state: Dictionary = {"schema": SCHEMA_VERSION, "rows": rows}
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, next_state))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"row_id": clean_id,
		"row": clean_row,
		"enabled": bool(gate.get("enabled", false)),
	}


func add_task(row_id: String, row: Dictionary) -> Dictionary:
	return add_row(row_id, row)


func get_state() -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {}
	if wb.has_method("get_module_state"):
		return wb.get_module_state(MODULE_ID)
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("get_module_state"):
		return adapter.get_module_state(wb.get_world(), MODULE_ID)
	return {}


func _parse_rule_condition(expr: String, fields: Array, line_no: int) -> Dictionary:
	if expr.is_empty():
		return _rule_error(line_no, "if 条件不能为空。")
	var or_parts: Array[String] = _split_outside_quotes(expr, " or ")
	var or_branches: Array = []
	for or_part: String in or_parts:
		var and_parts: Array[String] = _split_outside_quotes(or_part, " and ")
		var terms: Array = []
		for raw_term: String in and_parts:
			var parsed_term: Dictionary = _parse_rule_term(raw_term.strip_edges(), fields, line_no)
			if not bool(parsed_term.get("ok", false)):
				return parsed_term
			terms.append(parsed_term["term"])
		if terms.is_empty():
			return _rule_error(line_no, "if 条件格式有误。")
		or_branches.append(terms)
	return {"ok": true, "or_branches": or_branches}


func _parse_rule_term(term: String, fields: Array, line_no: int) -> Dictionary:
	if term.is_empty():
		return _rule_error(line_no, "比较条件不能为空。")
	for op: String in ["!=", "==", ">="]:
		var pos: int = _find_outside_quotes(term, op)
		if pos <= 0:
			continue
		if _find_outside_quotes(term.substr(pos + op.length()), op) >= 0:
			return _rule_error(line_no, "每个比较条件只能出现一次 %s。" % op)
		var lhs: String = term.substr(0, pos).strip_edges()
		var rhs: String = term.substr(pos + op.length()).strip_edges()
		if not (lhs in fields):
			return _rule_error(line_no, "不支持的字段：%s" % lhs)
		if rhs in fields:
			return {"ok": true, "term": {"left": lhs, "op": op, "rhs_field": rhs, "literal": "", "has_literal": false}}
		if rhs.length() >= 2 and rhs.begins_with("\"") and rhs.ends_with("\""):
			var inner: String = rhs.substr(1, rhs.length() - 2)
			if inner.length() > 64 or inner.contains("\"") or inner.contains("\\") or inner.contains("\n") or inner.contains("\r"):
				return _rule_error(line_no, "字符串常量不能包含引号、反斜杠或超过 64 个字符。")
			if op == ">=" and not inner.is_valid_float():
				return _rule_error(line_no, "使用 >= 比较时右侧应为数字字符串。")
			return {"ok": true, "term": {"left": lhs, "op": op, "rhs_field": "", "literal": inner, "has_literal": true}}
		return _rule_error(line_no, "暂不支持这个比较写法：%s" % term)
	return _rule_error(line_no, "只支持 ==、!= 或 >= 条件判断。")


func _split_outside_quotes(text: String, delim: String) -> Array[String]:
	var result: Array[String] = []
	var start: int = 0
	var in_quotes: bool = false
	var i: int = 0
	while i <= text.length() - delim.length():
		var ch: String = text.substr(i, 1)
		if ch == "\"":
			in_quotes = not in_quotes
			i += 1
			continue
		if not in_quotes and text.substr(i, delim.length()) == delim:
			result.append(text.substr(start, i - start))
			i += delim.length()
			start = i
			continue
		i += 1
	result.append(text.substr(start))
	return result


func _find_outside_quotes(text: String, needle: String) -> int:
	var in_quotes: bool = false
	for i: int in range(text.length() - needle.length() + 1):
		if text.substr(i, 1) == "\"":
			in_quotes = not in_quotes
		elif not in_quotes and text.substr(i, needle.length()) == needle:
			return i
	return -1


func _rule_error(line_number: int, message: String) -> Dictionary:
	return {"ok": false, "reason": "第 %d 行：%s" % [line_number, message]}


func _get_adapter() -> RefCounted:
	var wb: RefCounted = _wb()
	if wb != null and wb.has_method("get_adapter"):
		return wb.get_adapter()
	return null


func _check_gate(action: String) -> Dictionary:
	if _module_registry != null:
		return _module_registry.check_and_warn(MODULE_ID, action)
	return {"ok": true, "enabled": false, "policy": "preserve", "skipped": false}


func _warn(message: String) -> void:
	if _log_bus != null:
		_log_bus.warn(MODULE_ID, message)
	else:
		push_warning("[FuSdk/WARNING][%s] %s" % [MODULE_ID, message])


func _is_mod_source_tag(src: String) -> bool:
	if not src.begins_with("mod:") or src.length() <= 4:
		return false
	for i: int in range(4, src.length()):
		var c: int = src.unicode_at(i)
		var ok: bool = (
			(c >= 65 and c <= 90)
			or (c >= 97 and c <= 122)
			or (c >= 48 and c <= 57)
			or c == 95 or c == 46 or c == 58 or c == 45
		)
		if not ok:
			return false
	return true


## 保持白盒测试兼容性：委托 utils/bounded_cloner.gd 执行无记忆化轻量有界字典深拷贝（维持 dag24 耗尽检测）。
func _safe_clone_dict(d: Dictionary, depth: int = 0, stack: Array = [], budget: Array = []) -> Dictionary:
	return _bounded_cloner().simple_clone_dict(d, depth, stack, budget)
