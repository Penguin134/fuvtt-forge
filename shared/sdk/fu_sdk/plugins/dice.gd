extends RefCounted
## Fu vtt 原生可选插件 SDK：dice（通用骰子模块配置 schema v5、工作区 v4 与表达式校验）
##
## 对应官方源码：scenes/candidates/dice/feature_dice.gd、model/dice_expression.gd、
## model/dice_workspace.gd、model/dice_result_service.gd、
## modules/dice/dice_authority.gd、dice_history_archive.gd。

const MODULE_ID: String = "dice"
const MODULE_VERSION: int = 1
const SCHEMA_VERSION: int = 5
const WORKSPACE_SCHEMA_VERSION: int = 4
const HISTORY_SCHEMA: String = "fus.candidate.dice.history.v1"
const RESULT_SCHEMA: String = "fus.candidate.dice.result.v1"

const DICE_TYPES: Dictionary = {
	"d4": 4,
	"d6": 6,
	"d8": 8,
	"d10": 10,
	"d12": 12,
	"d20": 20,
	"d100": 100,
}
const THEMES: Array[String] = ["royal_ember_resin", "godot_blue_cat_eye"]
const VISIBILITIES: Array[String] = ["public", "private"]
const PRESENTATIONS: Array[String] = ["queued", "presenting", "presented", "failed", "cancelled", "skipped"]
const RESULT_KEYS: Array[String] = [
	"schema", "request_id", "epoch", "origin", "expr",
	"dice", "total", "modifier", "winner_idx", "adv_kind", "set_count",
]
const DIE_KEYS: Array[String] = ["type", "value", "subtract", "loser", "set", "burst"]

const MAX_INPUT_LENGTH: int = 256
const MAX_PHYSICAL_DICE: int = 20
const MAX_MODIFIER: int = 9999
const MAX_TOTAL: int = 999999
const MAX_COMBOS: int = 32
const MAX_HISTORY: int = 512
const MAX_HISTORY_PHYSICAL_DICE: int = 1024
const MAX_EPOCH: int = 2147483647
const MAX_CREATED_AT_UNIX: int = 4102444800
const MAX_SEGMENTS: int = 256
const MAX_PACKED_BYTES: int = 2 * 1024 * 1024
const MAX_SEGMENT_BYTES: int = 512 * 1024
const MAX_TOTAL_RECORDS: int = 32768

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


func default_workspace(
	animate: bool = false,
	simple_result: bool = true,
	visibility: String = "public",
	theme_id: String = "royal_ember_resin",
	draft: String = ""
) -> Dictionary:
	var use_simple: bool = simple_result and (not animate)
	return {
		"schema_version": WORKSPACE_SCHEMA_VERSION,
		"simple_result": use_simple,
		"animate": animate,
		"combos": [],
		"hidden_history_count": 0,
		"draft": draft.left(MAX_INPUT_LENGTH),
		"visibility": visibility if visibility in VISIBILITIES else "public",
		"theme_id": theme_id if theme_id in THEMES else "royal_ember_resin",
	}


func default_state(world_id: String = "world") -> Dictionary:
	return {
		"schema_version": SCHEMA_VERSION,
		"history": {
			"schema": HISTORY_SCHEMA,
			"world_id": world_id,
			"records": [],
		},
		"workspace": default_workspace(),
		"ownership": [],
		"archive": {},
	}


func make_combo(
	name: String,
	expr: String,
	label: String = "",
	combo_id: String = ""
) -> Dictionary:
	var cid: String = combo_id.strip_edges().to_lower()
	if cid.is_empty():
		cid = ("fu_sdk:dice:combo:%s:%s" % [name, expr]).sha256_text().left(24)
	return {
		"id": cid,
		"name": name,
		"expr": expr,
		"label": label,
	}


func validate_expression(raw: String, allow_legacy: bool = false) -> Dictionary:
	if raw.is_empty() or raw.length() > MAX_INPUT_LENGTH:
		return _expr_fail("expression_length", "请输入 1～256 个字符的骰子表达式。")
	if bool(_validation_utils().has_control_except_tab(raw)):
		return _expr_fail("expression_control_chars", "表达式包含非法控制字符。")
	var text: String = raw.to_lower().replace("（", "(").replace("）", ")").replace("，", ",")
	text = text.replace(" ", "").replace("\t", "")
	var wrapper: String = ""
	var parameter: int = 1
	if text.contains("(") or text.contains(")"):
		var outer := RegEx.new()
		outer.compile("^(adv|dis|burst)\\(([^()]+)\\)\\z")
		var matched: RegExMatch = outer.search(text)
		if matched == null:
			return _expr_fail("wrapper_unsupported", "仅支持骰子加减和 burst 连爆。")
		wrapper = matched.get_string(1)
		if wrapper != "burst" and not allow_legacy:
			return _expr_fail("dice_rule_unavailable", "通用骰子不支持这项规则。")
		text = matched.get_string(2)
		if text.contains(","):
			var pieces: PackedStringArray = text.split(",")
			if pieces.size() != 2 or not _is_digits(pieces[1]) or pieces[1].length() > 2:
				return _expr_fail("wrapper_parameter", "包装器参数必须是范围内的正整数。")
			parameter = int(pieces[1])
			text = pieces[0]
		var max_param: int = 10 if wrapper == "burst" else 3
		if parameter < 1 or parameter > max_param:
			return _expr_fail("wrapper_parameter", "超出此表达式的投掷次数上限。")

	var exact := RegEx.new()
	exact.compile("^[+\\-]?(?:[0-9]*d(?:[0-9]+|%)|[0-9]+)(?:[+\\-](?:[0-9]*d(?:[0-9]+|%)|[0-9]+))*\\z")
	if exact.search(text) == null:
		return _expr_fail("expression_malformed", "表达式格式错误。示例：2d6+1d20+5。")

	var terms := RegEx.new()
	terms.compile("([+\\-]?)(?:([0-9]*)d([0-9]+|%)|([0-9]+))")
	var groups: Array[Dictionary] = []
	var modifier: int = 0
	var physical: int = 0
	for matched_term: RegExMatch in terms.search_all(text):
		var sign_value: int = -1 if matched_term.get_string(1) == "-" else 1
		var side_text: String = matched_term.get_string(3)
		if not side_text.is_empty():
			var count_text: String = matched_term.get_string(2)
			if count_text.length() > 3 or side_text.length() > 3:
				return _expr_fail("dice_range", "骰子数量或面数超出范围。")
			var count: int = 1 if count_text.is_empty() else int(count_text)
			var kind: String = "d100" if side_text == "%" else "d%d" % int(side_text)
			if not DICE_TYPES.has(kind):
				return _expr_fail("dice_type", "只支持 D4、D6、D8、D10、D12、D20 和 D100。")
			if count < 1 or count > MAX_PHYSICAL_DICE:
				return _expr_fail("dice_count", "每组骰子数量必须为 1～20。")
			physical += count * (2 if kind == "d100" else 1)
			groups.append({"type": kind, "count": count, "sign": sign_value})
		else:
			var constant_text: String = matched_term.get_string(4)
			if constant_text.length() > 4 or int(constant_text) > MAX_MODIFIER:
				return _expr_fail("modifier_range", "常数修正值的绝对值不能超过 9999。")
			modifier += sign_value * int(constant_text)
			if absi(modifier) > MAX_MODIFIER:
				return _expr_fail("modifier_range", "累计修正值的绝对值不能超过 9999。")

	if groups.is_empty():
		return _expr_fail("dice_required", "表达式中至少需要一枚骰子。")
	var multiplier: int = parameter + 1 if not wrapper.is_empty() else 1
	if physical * multiplier > MAX_PHYSICAL_DICE:
		return _expr_fail("physical_capacity", "单次最多展示 20 枚实体骰。D100 占两枚，额外投掷和连爆也计入上限。")

	var display: String = ""
	for group: Dictionary in groups:
		if int(group["sign"]) < 0:
			display += "-"
		elif not display.is_empty():
			display += "+"
		display += "%d%s" % [int(group["count"]), str(group["type"])]
	if modifier != 0:
		display += ("+" if modifier > 0 else "") + str(modifier)
	if not wrapper.is_empty():
		display = "%s(%s%s)" % [wrapper, display, ",%d" % parameter if parameter != 1 else ""]

	return {
		"ok": true,
		"expr": display,
		"groups": groups,
		"modifier": modifier,
		"wrapper": wrapper,
		"parameter": parameter,
		"physical_budget": physical * multiplier,
	}


func parse_expression(raw: String, allow_legacy: bool = false) -> Dictionary:
	return validate_expression(raw, allow_legacy)


func validate_workspace(ws_var: Variant, total_history_count: int = 0) -> Dictionary:
	if not (ws_var is Dictionary):
		return {"ok": false, "reason": "dice_workspace_invalid_type"}
	var ws: Dictionary = ws_var as Dictionary
	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	var sv_parsed: Dictionary = val_u.parse_int_val(ws.get("schema_version", null))
	if not bool(sv_parsed["ok"]) or not (int(sv_parsed["value"]) in [1, 2, 3, 4]):
		return {"ok": false, "reason": "dice_workspace_schema_invalid"}
	var ws_ver: int = int(sv_parsed["value"])
	if ws.size() != ws_ver + 4:
		return {"ok": false, "reason": "dice_workspace_keys_invalid"}

	var req_keys: Array[String] = ["schema_version", "combos", "animate", "hidden_history_count", "draft"]
	if ws_ver >= 2:
		req_keys.append("visibility")
	if ws_ver >= 3:
		req_keys.append("theme_id")
	if ws_ver >= 4:
		req_keys.append("simple_result")
	for rk: String in req_keys:
		if not ws.has(rk):
			return {"ok": false, "reason": "dice_workspace_missing_key:" + rk}

	if not (ws["animate"] is bool):
		return {"ok": false, "reason": "dice_workspace_animate_invalid"}
	var animate: bool = bool(ws["animate"])
	var simple_result: bool = false
	if ws_ver >= 4:
		if not (ws["simple_result"] is bool):
			return {"ok": false, "reason": "dice_workspace_simple_result_invalid"}
		simple_result = bool(ws["simple_result"])
		if simple_result and animate:
			return {"ok": false, "reason": "dice_presentation_invalid"}

	var hidden_parsed: Dictionary = val_u.parse_int_val(ws["hidden_history_count"])
	if not bool(hidden_parsed["ok"]) or int(hidden_parsed["value"]) < 0 or int(hidden_parsed["value"]) > total_history_count:
		return {"ok": false, "reason": "dice_workspace_hidden_count_invalid"}
	var hidden_count: int = int(hidden_parsed["value"])

	var draft_v: Variant = ws["draft"]
	if not (draft_v is String) or str(draft_v).length() > MAX_INPUT_LENGTH or bool(valid_u.has_nul(str(draft_v))):
		return {"ok": false, "reason": "dice_workspace_draft_invalid"}

	var visibility: String = "public"
	if ws_ver >= 2:
		var vis_v: Variant = ws["visibility"]
		if not (vis_v is String) or not (str(vis_v) in VISIBILITIES):
			return {"ok": false, "reason": "dice_workspace_visibility_invalid"}
		visibility = str(vis_v)

	var theme_id: String = "royal_ember_resin"
	if ws_ver >= 3:
		var th_v: Variant = ws["theme_id"]
		if not (th_v is String) or not (str(th_v) in THEMES):
			return {"ok": false, "reason": "dice_workspace_theme_invalid"}
		theme_id = str(th_v)

	var combos_v: Variant = ws["combos"]
	if not (combos_v is Array):
		return {"ok": false, "reason": "dice_workspace_combos_invalid"}
	var combos: Array = combos_v as Array
	if combos.size() > MAX_COMBOS:
		return {"ok": false, "reason": "dice_combos_limit_exceeded"}

	var seen_combo_ids: Dictionary = {}
	var clean_combos: Array = []
	var expected_combo_keys: int = 4 if ws_ver >= 3 else 3
	for raw_c: Variant in combos:
		if not (raw_c is Dictionary):
			return {"ok": false, "reason": "dice_combo_invalid_type"}
		var c: Dictionary = raw_c as Dictionary
		if c.size() != expected_combo_keys or not c.has("id") or not c.has("name") or not c.has("expr"):
			return {"ok": false, "reason": "dice_combo_invalid_keys"}
		if ws_ver >= 3 and not c.has("label"):
			return {"ok": false, "reason": "dice_combo_missing_label"}

		var cid_v: Variant = c["id"]
		if not (cid_v is String) or not bool(valid_u.is_valid_hex24(str(cid_v))) or seen_combo_ids.has(str(cid_v)):
			return {"ok": false, "reason": "dice_combo_invalid_id"}
		seen_combo_ids[str(cid_v)] = true

		var cname_v: Variant = c["name"]
		if not (cname_v is String) or str(cname_v).is_empty() or str(cname_v).length() > 64 or bool(valid_u.has_control_chars(str(cname_v), false)):
			return {"ok": false, "reason": "dice_combo_invalid_name"}

		var clabel: String = ""
		if ws_ver >= 3:
			var cl_v: Variant = c["label"]
			if not (cl_v is String) or str(cl_v).length() > 64 or bool(valid_u.has_control_chars(str(cl_v), false)):
				return {"ok": false, "reason": "dice_combo_invalid_label"}
			clabel = str(cl_v)

		var cexpr_v: Variant = c["expr"]
		if not (cexpr_v is String):
			return {"ok": false, "reason": "dice_combo_invalid_expr_type"}
		var expr_res: Dictionary = validate_expression(str(cexpr_v), false)
		if not bool(expr_res.get("ok", false)):
			return {"ok": false, "reason": "dice_combo_invalid_expr:" + str(expr_res.get("reason", ""))}

		clean_combos.append({
			"id": str(cid_v),
			"name": str(cname_v),
			"expr": str(expr_res["expr"]),
			"label": clabel,
		})

	return {
		"ok": true,
		"data": {
			"schema_version": WORKSPACE_SCHEMA_VERSION,
			"simple_result": simple_result,
			"animate": animate,
			"combos": clean_combos,
			"hidden_history_count": hidden_count,
			"draft": str(draft_v),
			"visibility": visibility,
			"theme_id": theme_id,
		},
	}


func validate_state(state_var: Variant) -> Dictionary:
	if not (state_var is Dictionary):
		return {"ok": false, "reason": "invalid_dice_state_type"}
	var state: Dictionary = state_var as Dictionary
	if state.is_empty():
		return {"ok": true, "data": {}, "empty": true}

	var sv_parsed: Dictionary = _value_utils().parse_int_val(state.get("schema_version", null))
	if not bool(sv_parsed["ok"]) or not (int(sv_parsed["value"]) in [1, 2, 3, 4, 5]):
		return {"ok": false, "reason": "invalid_dice_schema_version"}
	var sv: int = int(sv_parsed["value"])
	var expected_sizes: Dictionary = {1: 2, 2: 3, 3: 4, 4: 4, 5: 5}
	if state.size() != int(expected_sizes[sv]):
		return {"ok": false, "reason": "invalid_dice_envelope_size"}
	if not state.has("history"):
		return {"ok": false, "reason": "missing_dice_history"}
	if sv >= 2 and not state.has("workspace"):
		return {"ok": false, "reason": "missing_dice_workspace"}
	if sv >= 3 and not state.has("ownership"):
		return {"ok": false, "reason": "missing_dice_ownership"}
	if sv >= 5 and not state.has("archive"):
		return {"ok": false, "reason": "dice_archive_missing"}

	# Validate history
	var hist_res: Dictionary = _validate_history(state["history"])
	if not bool(hist_res.get("ok", false)):
		return hist_res
	var clean_hist: Dictionary = hist_res["data"] as Dictionary
	var records: Array = clean_hist["records"] as Array
	var hist_world_id: String = str(clean_hist["world_id"])

	# Validate archive
	var archive_count: int = 0
	var clean_archive: Dictionary = {}
	if sv >= 5:
		var arch_res: Dictionary = _validate_archive(state["archive"], hist_world_id, records.size())
		if not bool(arch_res.get("ok", false)):
			return arch_res
		clean_archive = arch_res["data"] as Dictionary
		archive_count = int(arch_res.get("count", 0))

	# Validate workspace
	var total_records_count: int = records.size() + archive_count
	var clean_ws: Dictionary = default_workspace()
	if sv >= 2:
		var ws_res: Dictionary = validate_workspace(state["workspace"], total_records_count)
		if not bool(ws_res.get("ok", false)):
			return ws_res
		clean_ws = ws_res["data"] as Dictionary

	# Validate ownership
	var clean_own: Array = []
	if sv >= 3:
		var own_res: Dictionary = _validate_ownership(state["ownership"], records, sv)
		if not bool(own_res.get("ok", false)):
			return own_res
		clean_own = own_res["data"] as Array
	else:
		for raw_rec: Variant in records:
			var rec: Dictionary = raw_rec as Dictionary
			var req_id: String = str(rec["request_id"])
			clean_own.append({
				"id": req_id,
				"owner": "host",
				"name": "主持",
				"request_id": req_id,
				"visibility": "private",
				"label": "",
			})

	return {
		"ok": true,
		"data": {
			"schema_version": SCHEMA_VERSION,
			"history": clean_hist,
			"workspace": clean_ws,
			"ownership": clean_own,
			"archive": clean_archive,
		},
	}


func configure_dice(state: Dictionary) -> Dictionary:
	var gate: Dictionary = _check_gate("configure_dice")
	if not bool(gate.get("ok", true)):
		return gate
	return _configure_dice_impl(state, gate)


func _configure_dice_impl(state: Dictionary, gate: Dictionary) -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var checked: Dictionary = validate_state(state)
	if not bool(checked.get("ok", false)):
		var reason: String = str(checked.get("reason", "invalid_dice_state"))
		_warn("dice 配置校验失败：%s" % reason)
		return {"ok": false, "reason": reason}

	var normalized: Dictionary = checked["data"] as Dictionary
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
	return configure_dice(state)


func add_combo(
	name: String,
	expr: String,
	label: String = "",
	combo_id: String = ""
) -> Dictionary:
	var gate: Dictionary = _check_gate("add_combo")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var expr_res: Dictionary = validate_expression(expr, false)
	if not bool(expr_res.get("ok", false)):
		return expr_res
	var current: Dictionary = get_state()
	if current.is_empty():
		current = default_state()
	var raw_ws: Variant = current.get("workspace", null)
	var ws: Dictionary = {}
	if raw_ws == null:
		if current.has("workspace"):
			return {"ok": false, "reason": "invalid_dice_workspace"}
		ws = default_workspace()
	elif not (raw_ws is Dictionary):
		return {"ok": false, "reason": "invalid_dice_workspace"}
	else:
		var ws_budget: Array = [16384, false]
		ws = _safe_clone_dict(raw_ws as Dictionary, 0, [], ws_budget)
		if bool(ws_budget[1]):
			return {"ok": false, "reason": "dice_state_too_large"}
	var raw_combos: Variant = ws.get("combos", null)
	var combos: Array = []
	if raw_combos == null:
		if ws.has("combos"):
			return {"ok": false, "reason": "dice_workspace_combos_invalid"}
	elif not (raw_combos is Array):
		return {"ok": false, "reason": "dice_workspace_combos_invalid"}
	else:
		var combos_budget: Array = [16384, false]
		combos = _bounded_cloner().simple_clone_array(raw_combos as Array, 0, [], combos_budget)
		if bool(combos_budget[1]):
			return {"ok": false, "reason": "dice_state_too_large"}
	if combos.size() >= MAX_COMBOS:
		return {"ok": false, "reason": "dice_combos_limit_exceeded"}
	combos.append(make_combo(name, str(expr_res["expr"]), label, combo_id))
	ws["combos"] = combos
	current["workspace"] = ws
	return _configure_dice_impl(current, gate)


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


func _validate_history(hist_var: Variant) -> Dictionary:
	if not (hist_var is Dictionary):
		return {"ok": false, "reason": "dice_history_invalid_type"}
	var hist: Dictionary = hist_var as Dictionary
	if hist.size() != 3 or not hist.has("schema") or not hist.has("world_id") or not hist.has("records"):
		return {"ok": false, "reason": "dice_history_invalid_keys"}
	if not (hist["schema"] is String) or str(hist["schema"]) != HISTORY_SCHEMA:
		return {"ok": false, "reason": "dice_history_schema_mismatch"}
	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	var wid_v: Variant = hist["world_id"]
	if not (wid_v is String) or str(wid_v).length() > 128 or bool(valid_u.has_control_chars(str(wid_v), false)):
		return {"ok": false, "reason": "history_world"}
	var wid: String = str(wid_v)
	var recs_v: Variant = hist["records"]
	if not (recs_v is Array):
		return {"ok": false, "reason": "dice_history_records_type"}
	var recs: Array = recs_v as Array
	if recs.size() > MAX_HISTORY:
		return {"ok": false, "reason": "dice_history_limit_exceeded"}
	if wid.is_empty() and not recs.is_empty():
		return {"ok": false, "reason": "history_world"}

	var seen_req: Dictionary = {}
	var physical_total: int = 0
	var clean_recs: Array = []
	for raw_r: Variant in recs:
		if not (raw_r is Dictionary):
			return {"ok": false, "reason": "dice_record_invalid_type"}
		var rec: Dictionary = raw_r as Dictionary
		if rec.size() != 7:
			return {"ok": false, "reason": "dice_record_invalid_keys"}
		for rk: String in ["request_id", "epoch", "world_id", "created_at_unix", "presentation", "presentation_detail", "result"]:
			if not rec.has(rk):
				return {"ok": false, "reason": "dice_record_missing_key:" + rk}
		var req_v: Variant = rec["request_id"]
		if not (req_v is String) or not _is_valid_request_id(str(req_v)) or seen_req.has(str(req_v)):
			return {"ok": false, "reason": "dice_record_invalid_request_id"}
		var req_s: String = str(req_v)
		seen_req[req_s] = true
		var epoch_p: Dictionary = val_u.parse_int_val(rec["epoch"])
		if not bool(epoch_p["ok"]) or int(epoch_p["value"]) < 1 or int(epoch_p["value"]) > MAX_EPOCH:
			return {"ok": false, "reason": "dice_record_invalid_epoch"}
		var epoch_val: int = int(epoch_p["value"])
		if not (rec["world_id"] is String) or str(rec["world_id"]) != wid:
			return {"ok": false, "reason": "dice_record_world_mismatch"}
		var ts_p: Dictionary = val_u.parse_int_val(rec["created_at_unix"])
		if not bool(ts_p["ok"]) or int(ts_p["value"]) < 0 or int(ts_p["value"]) > MAX_CREATED_AT_UNIX:
			return {"ok": false, "reason": "dice_record_invalid_timestamp"}
		var ts_val: int = int(ts_p["value"])
		if not (rec["presentation"] is String) or not (str(rec["presentation"]) in PRESENTATIONS):
			return {"ok": false, "reason": "dice_record_invalid_presentation"}
		if not (rec["presentation_detail"] is String) or str(rec["presentation_detail"]).length() > 256:
			return {"ok": false, "reason": "dice_record_invalid_presentation_detail"}

		var res_v: Variant = rec["result"]
		if not (res_v is Dictionary):
			return {"ok": false, "reason": "dice_result_invalid_type"}
		var res: Dictionary = res_v as Dictionary
		if res.size() != RESULT_KEYS.size():
			return {"ok": false, "reason": "dice_result_invalid_keys"}
		for res_k: String in RESULT_KEYS:
			if not res.has(res_k):
				return {"ok": false, "reason": "dice_result_missing_key:" + res_k}
		if not (res["schema"] is String) or str(res["schema"]) != RESULT_SCHEMA \
				or not (res["request_id"] is String) or str(res["request_id"]) != req_s:
			return {"ok": false, "reason": "dice_result_identity_mismatch"}
		var res_epoch_p: Dictionary = val_u.parse_int_val(res["epoch"])
		if not bool(res_epoch_p["ok"]) or int(res_epoch_p["value"]) != epoch_val:
			return {"ok": false, "reason": "dice_result_epoch_mismatch"}
		if not (res["origin"] is String) or str(res["origin"]) != "candidate_local":
			return {"ok": false, "reason": "dice_result_origin_invalid"}
		if not (res["expr"] is String) or not (res["dice"] is Array):
			return {"ok": false, "reason": "dice_result_expr_or_dice_invalid"}
		var parsed_expr: Dictionary = validate_expression(str(res["expr"]), true)
		if not bool(parsed_expr.get("ok", false)) or str(parsed_expr["expr"]) != str(res["expr"]):
			return {"ok": false, "reason": "dice_result_expr_malformed"}

		var total_p: Dictionary = val_u.parse_int_val(res["total"])
		if not bool(total_p["ok"]) or absi(int(total_p["value"])) > MAX_TOTAL:
			return {"ok": false, "reason": "dice_result_total_invalid"}
		var total_val: int = int(total_p["value"])
		var mod_p: Dictionary = val_u.parse_int_val(res["modifier"])
		if not bool(mod_p["ok"]) or int(mod_p["value"]) != int(parsed_expr["modifier"]):
			return {"ok": false, "reason": "dice_result_modifier_mismatch"}
		var mod_val: int = int(mod_p["value"])
		var winner_p: Dictionary = val_u.parse_int_val(res["winner_idx"])
		if not bool(winner_p["ok"]):
			return {"ok": false, "reason": "dice_result_winner_idx_invalid"}
		var winner_val: int = int(winner_p["value"])
		if not (res["adv_kind"] is String) or not (str(res["adv_kind"]) in ["", "adv", "dis"]):
			return {"ok": false, "reason": "dice_result_adv_kind_invalid"}
		var adv_kind_s: String = str(res["adv_kind"])
		var set_count_p: Dictionary = val_u.parse_int_val(res["set_count"])
		if not bool(set_count_p["ok"]) or int(set_count_p["value"]) < 1:
			return {"ok": false, "reason": "dice_result_set_count_invalid"}
		var set_count_val: int = int(set_count_p["value"])

		var wrapper: String = str(parsed_expr["wrapper"])
		var selection: bool = wrapper in ["adv", "dis"]
		var expected_set_count: int = int(parsed_expr["parameter"]) + 1 if selection else 1
		var expected_adv_kind: String = wrapper if selection else ""
		if set_count_val != expected_set_count or adv_kind_s != expected_adv_kind:
			return {"ok": false, "reason": "dice_result_selection_mismatch"}

		var dice_arr: Array = res["dice"] as Array
		if dice_arr.is_empty() or dice_arr.size() > MAX_PHYSICAL_DICE:
			return {"ok": false, "reason": "dice_result_dice_count_invalid"}

		var offset: int = 0
		var totals: Array[int] = []
		var starts: Array[int] = []
		var physical: int = 0
		var clean_dice: Array = []
		var groups: Array = parsed_expr["groups"] as Array
		var param_i: int = int(parsed_expr["parameter"])
		for set_index: int in range(expected_set_count):
			starts.append(offset)
			var subtotal: int = mod_val
			for group_var: Variant in groups:
				var group: Dictionary = group_var as Dictionary
				var g_type: String = str(group["type"])
				var g_count: int = int(group["count"])
				var g_sign: int = int(group["sign"])
				var sides: int = int(DICE_TYPES[g_type])
				for _unused_idx: int in range(g_count):
					var chain: int = 0
					while true:
						if offset >= dice_arr.size() or not (dice_arr[offset] is Dictionary):
							return {"ok": false, "reason": "dice_die_invalid"}
						var die: Dictionary = dice_arr[offset] as Dictionary
						if die.size() != DIE_KEYS.size():
							return {"ok": false, "reason": "dice_die_invalid_keys"}
						for dk: String in DIE_KEYS:
							if not die.has(dk):
								return {"ok": false, "reason": "dice_die_missing_key:" + dk}
						if not (die["type"] is String):
							return {"ok": false, "reason": "dice_die_type_invalid"}
						var dt: String = str(die["type"])
						if not DICE_TYPES.has(dt):
							return {"ok": false, "reason": "dice_die_type_invalid"}
						var val_p: Dictionary = val_u.parse_int_val(die["value"])
						if not bool(val_p["ok"]):
							return {"ok": false, "reason": "dice_die_value_invalid"}
						var die_val: int = int(val_p["value"])
						var set_p: Dictionary = val_u.parse_int_val(die["set"])
						if not bool(set_p["ok"]):
							return {"ok": false, "reason": "dice_die_set_invalid"}
						var die_set: int = int(set_p["value"])
						if not (die["subtract"] is bool) or not (die["loser"] is bool) or not (die["burst"] is bool):
							return {"ok": false, "reason": "dice_die_flag_invalid"}
						var die_sub: bool = bool(die["subtract"])
						var die_loser: bool = bool(die["loser"])
						var die_burst: bool = bool(die["burst"])
						if dt != g_type or die_val < 1 or die_val > sides \
								or die_sub != (g_sign < 0) or die_set != set_index or die_burst != (chain > 0):
							return {"ok": false, "reason": "dice_die_roll_mismatch"}
						physical += 2 if dt == "d100" else 1
						subtotal += die_val * g_sign
						clean_dice.append({
							"type": dt,
							"value": die_val,
							"subtract": die_sub,
							"loser": die_loser,
							"set": die_set,
							"burst": die_burst,
						})
						offset += 1
						if wrapper != "burst" or die_val != sides or chain >= param_i:
							break
						chain += 1
			totals.append(subtotal)

		if offset != dice_arr.size() or physical > MAX_PHYSICAL_DICE:
			return {"ok": false, "reason": "dice_result_dice_count_invalid"}
		var best: int = 0
		for index: int in range(1, expected_set_count):
			if (wrapper == "adv" and totals[index] > totals[best]) \
					or (wrapper == "dis" and totals[index] < totals[best]):
				best = index
		for clean_die_var: Variant in clean_dice:
			var cd: Dictionary = clean_die_var as Dictionary
			if bool(cd["loser"]) != (int(cd["set"]) != best):
				return {"ok": false, "reason": "dice_die_loser_mismatch"}
		var expected_winner: int = starts[best] if selection else -1
		if total_val != totals[best] or winner_val != expected_winner:
			return {"ok": false, "reason": "dice_result_total_mismatch"}

		physical_total += physical
		if physical_total > MAX_HISTORY_PHYSICAL_DICE:
			return {"ok": false, "reason": "dice_history_physical_limit_exceeded"}
		clean_recs.append({
			"request_id": req_s,
			"epoch": epoch_val,
			"world_id": wid,
			"created_at_unix": ts_val,
			"presentation": str(rec["presentation"]),
			"presentation_detail": str(rec["presentation_detail"]),
			"result": {
				"schema": RESULT_SCHEMA,
				"request_id": req_s,
				"epoch": epoch_val,
				"origin": "candidate_local",
				"expr": str(res["expr"]),
				"dice": clean_dice,
				"total": total_val,
				"modifier": mod_val,
				"winner_idx": winner_val,
				"adv_kind": adv_kind_s,
				"set_count": set_count_val,
			},
		})

	return {
		"ok": true,
		"data": {
			"schema": HISTORY_SCHEMA,
			"world_id": wid,
			"records": clean_recs,
		},
	}


func _validate_ownership(own_var: Variant, records: Array, schema_ver: int) -> Dictionary:
	if not (own_var is Array):
		return {"ok": false, "reason": "dice_ownership_invalid"}
	var own: Array = own_var as Array
	if own.size() != records.size():
		return {"ok": false, "reason": "dice_ownership_invalid"}
	var valid_u: Variant = _validation_utils()
	var expected_keys: int = 6 if schema_ver >= 4 else 5
	var clean_own: Array = []
	var seen_ids: Dictionary = {}
	for i: int in range(own.size()):
		var item_v: Variant = own[i]
		if not (item_v is Dictionary):
			return {"ok": false, "reason": "dice_ownership_item_invalid"}
		var item: Dictionary = item_v as Dictionary
		if item.size() != expected_keys:
			return {"ok": false, "reason": "dice_ownership_keys_invalid"}
		for req_k: String in ["id", "owner", "name", "request_id", "visibility"]:
			if not item.has(req_k):
				return {"ok": false, "reason": "dice_ownership_missing:" + req_k}
		if schema_ver >= 4 and not item.has("label"):
			return {"ok": false, "reason": "dice_ownership_missing_label"}
		var rec: Dictionary = records[i] as Dictionary
		var rec_req_id: String = str(rec["request_id"])
		if not (item["request_id"] is String) or str(item["request_id"]) != rec_req_id:
			return {"ok": false, "reason": "dice_ownership_request_mismatch"}
		var owner_v: Variant = item["owner"]
		if not (owner_v is String) or not _is_valid_owner(str(owner_v)):
			return {"ok": false, "reason": "dice_ownership_owner_invalid"}
		var owner_s: String = str(owner_v)
		var expected_id: String = rec_req_id if owner_s == "host" else ("net-" + (owner_s + ":" + rec_req_id).sha256_text())
		if not (item["id"] is String) or str(item["id"]) != expected_id or seen_ids.has(expected_id):
			return {"ok": false, "reason": "dice_ownership_id_mismatch"}
		seen_ids[expected_id] = true
		if not (item["name"] is String) or str(item["name"]).is_empty() or str(item["name"]).length() > 64 or bool(valid_u.has_control_chars(str(item["name"]), false)):
			return {"ok": false, "reason": "dice_ownership_name_invalid"}
		if not (item["visibility"] is String) or not (str(item["visibility"]) in VISIBILITIES):
			return {"ok": false, "reason": "dice_ownership_visibility_invalid"}
		var lbl: String = ""
		if schema_ver >= 4:
			if not (item["label"] is String) or str(item["label"]).length() > 64 or bool(valid_u.has_control_chars(str(item["label"]), false)):
				return {"ok": false, "reason": "dice_ownership_label_invalid"}
			lbl = str(item["label"])
		clean_own.append({
			"id": expected_id,
			"owner": owner_s,
			"name": str(item["name"]),
			"request_id": rec_req_id,
			"visibility": str(item["visibility"]),
			"label": lbl,
		})
	return {"ok": true, "data": clean_own}


func _validate_archive(arch_var: Variant, hist_world_id: String, active_count: int) -> Dictionary:
	if not (arch_var is Dictionary):
		return {"ok": false, "reason": "dice_archive_invalid_type"}
	var arch: Dictionary = arch_var as Dictionary
	if arch.is_empty():
		return {"ok": true, "data": {}, "count": 0}
	if arch.size() != 3 or not arch.has("version") or not arch.has("scope") or not arch.has("segments"):
		return {"ok": false, "reason": "dice_archive_invalid_keys"}
	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	var arch_ver_p: Dictionary = val_u.parse_int_val(arch["version"])
	if not bool(arch_ver_p["ok"]) or int(arch_ver_p["value"]) != 1:
		return {"ok": false, "reason": "dice_archive_invalid_version"}
	if not (arch["scope"] is String) or str(arch["scope"]) != hist_world_id:
		return {"ok": false, "reason": "dice_archive_scope_mismatch"}
	if not (arch["segments"] is Array):
		return {"ok": false, "reason": "dice_archive_segments_type"}
	var segs: Array = arch["segments"] as Array
	if segs.size() > MAX_SEGMENTS:
		return {"ok": false, "reason": "dice_archive_segments_limit"}
	var total_packed: int = 0
	var total_count: int = 0
	var clean_segs: Array = []
	for raw_seg: Variant in segs:
		if not (raw_seg is Dictionary):
			return {"ok": false, "reason": "dice_archive_segment_type"}
		var seg: Dictionary = raw_seg as Dictionary
		if seg.size() != 4 or not seg.has("count") or not seg.has("plain_bytes") or not seg.has("digest") or not seg.has("data"):
			return {"ok": false, "reason": "dice_archive_segment_keys"}
		var scount_p: Dictionary = val_u.parse_int_val(seg["count"])
		if not bool(scount_p["ok"]) or int(scount_p["value"]) < 1 or int(scount_p["value"]) > MAX_HISTORY:
			return {"ok": false, "reason": "dice_archive_segment_count"}
		var sbytes_p: Dictionary = val_u.parse_int_val(seg["plain_bytes"])
		if not bool(sbytes_p["ok"]) or int(sbytes_p["value"]) < 1 or int(sbytes_p["value"]) > MAX_PACKED_BYTES:
			return {"ok": false, "reason": "dice_archive_segment_plain_bytes"}
		if not (seg["digest"] is String) or not bool(valid_u.is_valid_hex64(str(seg["digest"]), false)):
			return {"ok": false, "reason": "dice_archive_segment_digest"}
		if not (seg["data"] is PackedByteArray):
			return {"ok": false, "reason": "dice_archive_segment_data_type"}
		var pba: PackedByteArray = seg["data"] as PackedByteArray
		if pba.is_empty() or pba.size() > MAX_SEGMENT_BYTES:
			return {"ok": false, "reason": "dice_archive_segment_data_size"}
		total_packed += pba.size()
		total_count += int(scount_p["value"])
		if total_packed > MAX_PACKED_BYTES or (active_count + total_count) > MAX_TOTAL_RECORDS:
			return {"ok": false, "reason": "dice_archive_quota_exceeded"}
		clean_segs.append({
			"count": int(scount_p["value"]),
			"plain_bytes": int(sbytes_p["value"]),
			"digest": str(seg["digest"]),
			"data": pba.duplicate(),
		})
	return {
		"ok": true,
		"data": {
			"version": 1,
			"scope": hist_world_id,
			"segments": clean_segs,
		},
		"count": total_count,
	}


func _expr_fail(code: String, message: String) -> Dictionary:
	return {"ok": false, "reason": code, "message": message}


func _is_digits(value: String) -> bool:
	if value.is_empty():
		return false
	for i: int in range(value.length()):
		var c: int = value.unicode_at(i)
		if c < 48 or c > 57:
			return false
	return true


func _is_valid_request_id(req_id: String) -> bool:
	if req_id.is_empty() or req_id.length() > 96:
		return false
	for i: int in range(req_id.length()):
		var c: int = req_id.unicode_at(i)
		var ok: bool = (
			(c >= 48 and c <= 57)
			or (c >= 65 and c <= 90)
			or (c >= 97 and c <= 122)
			or c == 95 or c == 46 or c == 58 or c == 45
		)
		if not ok:
			return false
	return true


func _is_valid_owner(owner: String) -> bool:
	if owner.is_empty() or owner.length() > 128:
		return false
	for i: int in range(owner.length()):
		var c: int = owner.unicode_at(i)
		if c < 33 or c > 126:
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


func _warn(message: String) -> void:
	if _log_bus != null:
		_log_bus.warn(MODULE_ID, message)
	else:
		push_warning("[FuSdk/WARNING][%s] %s" % [MODULE_ID, message])


## 保持白盒测试兼容性：委托 utils/bounded_cloner.gd 执行无记忆化轻量有界字典深拷贝。
func _safe_clone_dict(d: Dictionary, depth: int = 0, stack: Array = [], budget: Array = []) -> Dictionary:
	return _bounded_cloner().simple_clone_dict(d, depth, stack, budget)
