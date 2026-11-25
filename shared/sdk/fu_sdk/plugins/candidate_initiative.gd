extends RefCounted
## Fu vtt 原生可选插件 SDK：candidate_initiative（先攻与回合模块配置 schema v2 与 comp_initiative 组件）
##
## 对应官方源码：scenes/candidates/initiative/feature_initiative.gd、initiative_state.gd、
## components/comp_initiative.gd、scenes/entities/board_token.gd。

const MODULE_ID: String = "candidate_initiative"
const MODULE_VERSION: int = 1
const SCHEMA_VERSION: int = 2
const COMP_INITIATIVE_SCRIPT: String = "res://scenes/candidates/initiative/components/comp_initiative.gd"

const PHASES: Array[String] = ["idle", "preparing", "active", "ended"]
const OBSTACLE_DRAWING_KINDS: Array[String] = ["wall", "air", "door", "window", "glass"]
const MAX_MEMBERS: int = 1000
const MAX_INITIATIVE: int = 9999
const MAX_MODIFIER: int = 999
const MAX_ROUND: int = 1000000000
const MAX_STARTING_ROUND: int = 99
const MAX_COUNTER: int = 9007199254740991
const MAX_WORLD_ID_LENGTH: int = 256

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


func default_settings() -> Dictionary:
	return {
		"descending": true,
		"starting_round": 1,
		"show_bar": true,
	}


func default_state(world_id: String = "world") -> Dictionary:
	return {
		"schema": SCHEMA_VERSION,
		"world_id": world_id,
		"phase": "idle",
		"members": [],
		"current_id": "",
		"round": 0,
		"generation": 1,
		"revision": 0,
		"settings": default_settings(),
	}


func default_component_state() -> Dictionary:
	return {
		"count": 0,
		"modifier": 0,
		"active": true,
		"defeated": false,
		"rolled": false,
	}


func make_combatant_state(
	count: int = 0,
	modifier: int = 0,
	active: bool = true,
	defeated: bool = false,
	rolled: bool = false
) -> Dictionary:
	return {
		"count": clampi(count, -MAX_INITIATIVE, MAX_INITIATIVE),
		"modifier": clampi(modifier, -MAX_MODIFIER, MAX_MODIFIER),
		"active": active,
		"defeated": defeated,
		"rolled": rolled,
	}


func validate_state(state_var: Variant, in_legacy: bool = false) -> Dictionary:
	if not (state_var is Dictionary):
		return {"ok": false, "reason": "invalid_initiative_state_type"}
	var state: Dictionary = state_var as Dictionary
	if state.is_empty():
		return {"ok": true, "data": {}, "empty": true}
	if in_legacy and (state.has("legacy") or state.has("legacy_imported")):
		return {"ok": false, "reason": "nested_legacy_forbidden"}

	var allowed_top: Array[String] = [
		"schema", "world_id", "phase", "members", "current_id",
		"round", "generation", "revision", "settings", "legacy", "legacy_imported",
	]
	for raw_k: Variant in state.keys():
		if not (raw_k is String) or not (str(raw_k) in allowed_top):
			return {"ok": false, "reason": "unknown_initiative_key:" + str(raw_k)}

	for req_k: String in ["schema", "world_id", "phase", "members", "current_id", "round"]:
		if not state.has(req_k):
			return {"ok": false, "reason": "missing_initiative_key:" + req_k}

	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()

	var schema_parsed: Dictionary = val_u.parse_int_val(state["schema"])
	if not bool(schema_parsed["ok"]) or not (int(schema_parsed["value"]) in [1, 2]):
		return {"ok": false, "reason": "invalid_initiative_schema"}
	var schema_ver: int = int(schema_parsed["value"])

	var wid_v: Variant = state["world_id"]
	if not (wid_v is String):
		return {"ok": false, "reason": "invalid_world_id_type"}
	var wid: String = str(wid_v)
	if wid.strip_edges().is_empty() or wid.length() > MAX_WORLD_ID_LENGTH or bool(valid_u.has_nul(wid)):
		return {"ok": false, "reason": "invalid_world_id"}

	var phase_v: Variant = state["phase"]
	if not (phase_v is String) or not (str(phase_v) in PHASES):
		return {"ok": false, "reason": "invalid_initiative_phase"}
	var phase: String = str(phase_v)

	var round_parsed: Dictionary = val_u.parse_int_val(state["round"])
	if not bool(round_parsed["ok"]) or int(round_parsed["value"]) < 0 or int(round_parsed["value"]) > MAX_ROUND:
		return {"ok": false, "reason": "invalid_initiative_round"}
	var round_num: int = int(round_parsed["value"])

	var cur_v: Variant = state["current_id"]
	if not (cur_v is String) or str(cur_v).length() > MAX_WORLD_ID_LENGTH:
		return {"ok": false, "reason": "invalid_current_id"}
	var current_id: String = str(cur_v)

	var members_v: Variant = state["members"]
	if not (members_v is Array):
		return {"ok": false, "reason": "invalid_members_type"}
	var members: Array = members_v as Array
	if members.size() > MAX_MEMBERS:
		return {"ok": false, "reason": "members_limit_exceeded"}

	var seen_ids: Dictionary = {}
	var clean_members: Array = []
	for idx: int in range(members.size()):
		var raw_m: Variant = members[idx]
		if not (raw_m is Dictionary):
			return {"ok": false, "reason": "invalid_member_row"}
		var m: Dictionary = raw_m as Dictionary
		if schema_ver == 2 and m.has("initiative"):
			return {"ok": false, "reason": "schema2_forbids_member_initiative"}
		var expected_m_size: int = 3 if schema_ver == 1 else 2
		if m.size() != expected_m_size:
			return {"ok": false, "reason": "invalid_member_keys"}
		if not m.has("entity_id") or not m.has("tie_order"):
			return {"ok": false, "reason": "missing_member_keys"}
		if schema_ver == 1 and not m.has("initiative"):
			return {"ok": false, "reason": "missing_member_initiative"}

		var eid_v: Variant = m["entity_id"]
		if not (eid_v is String):
			return {"ok": false, "reason": "invalid_member_entity_id_type"}
		var eid: String = str(eid_v)
		if eid.strip_edges().is_empty() or eid.length() > MAX_WORLD_ID_LENGTH or seen_ids.has(eid):
			return {"ok": false, "reason": "duplicate_or_empty_member_entity_id"}
		seen_ids[eid] = true

		var to_parsed: Dictionary = val_u.parse_int_val(m["tie_order"])
		if not bool(to_parsed["ok"]) or int(to_parsed["value"]) < 0 or int(to_parsed["value"]) >= MAX_MEMBERS or int(to_parsed["value"]) != idx:
			return {"ok": false, "reason": "invalid_member_tie_order"}

		var clean_m: Dictionary = {"entity_id": eid, "tie_order": int(to_parsed["value"])}
		if schema_ver == 1:
			var init_parsed: Dictionary = val_u.parse_int_val(m["initiative"])
			if not bool(init_parsed["ok"]) or absi(int(init_parsed["value"])) > MAX_INITIATIVE:
				return {"ok": false, "reason": "invalid_member_initiative"}
			clean_m["initiative"] = int(init_parsed["value"])
		clean_members.append(clean_m)

	if phase == "idle":
		if not clean_members.is_empty() or round_num != 0 or not current_id.is_empty():
			return {"ok": false, "reason": "invalid_idle_phase_invariants"}
	elif phase == "preparing":
		if round_num != 0 or not current_id.is_empty():
			return {"ok": false, "reason": "invalid_preparing_phase_invariants"}
	elif phase == "active":
		if round_num < 1 or current_id.is_empty() or not seen_ids.has(current_id):
			return {"ok": false, "reason": "invalid_active_phase_invariants"}
	elif phase == "ended":
		if round_num < 1 or not current_id.is_empty():
			return {"ok": false, "reason": "invalid_ended_phase_invariants"}

	var generation: int = 1
	if state.has("generation"):
		var gen_parsed: Dictionary = val_u.parse_int_val(state["generation"])
		if not bool(gen_parsed["ok"]) or int(gen_parsed["value"]) < 0 or int(gen_parsed["value"]) > MAX_COUNTER:
			return {"ok": false, "reason": "invalid_generation"}
		generation = int(gen_parsed["value"])

	var revision: int = 0
	if state.has("revision"):
		var rev_parsed: Dictionary = val_u.parse_int_val(state["revision"])
		if not bool(rev_parsed["ok"]) or int(rev_parsed["value"]) < 0 or int(rev_parsed["value"]) > MAX_COUNTER:
			return {"ok": false, "reason": "invalid_revision"}
		revision = int(rev_parsed["value"])

	var clean_settings: Dictionary = default_settings()
	if state.has("settings"):
		var set_v: Variant = state["settings"]
		if not (set_v is Dictionary):
			return {"ok": false, "reason": "invalid_settings_type"}
		var set_d: Dictionary = set_v as Dictionary
		if set_d.size() != 3 or not set_d.has("descending") or not set_d.has("starting_round") or not set_d.has("show_bar"):
			return {"ok": false, "reason": "invalid_settings_keys"}
		if not (set_d["descending"] is bool) or not (set_d["show_bar"] is bool):
			return {"ok": false, "reason": "invalid_settings_bool"}
		var sr_parsed: Dictionary = val_u.parse_int_val(set_d["starting_round"])
		if not bool(sr_parsed["ok"]) or int(sr_parsed["value"]) < 1 or int(sr_parsed["value"]) > MAX_STARTING_ROUND:
			return {"ok": false, "reason": "invalid_starting_round"}
		clean_settings = {
			"descending": bool(set_d["descending"]),
			"starting_round": int(sr_parsed["value"]),
			"show_bar": bool(set_d["show_bar"]),
		}

	var out: Dictionary = {
		"schema": schema_ver,
		"world_id": wid,
		"phase": phase,
		"members": clean_members,
		"current_id": current_id,
		"round": round_num,
		"generation": generation,
		"revision": revision,
		"settings": clean_settings,
	}

	if state.has("legacy_imported"):
		if not (state["legacy_imported"] is bool):
			return {"ok": false, "reason": "invalid_legacy_imported"}
		out["legacy_imported"] = bool(state["legacy_imported"])
	if state.has("legacy"):
		var leg_v: Variant = state["legacy"]
		if not (leg_v is Dictionary):
			return {"ok": false, "reason": "invalid_legacy_type"}
		var leg_d: Dictionary = leg_v as Dictionary
		var leg_schema: Dictionary = val_u.parse_int_val(leg_d.get("schema", 0))
		if not bool(leg_schema["ok"]) or int(leg_schema["value"]) != 1:
			return {"ok": false, "reason": "invalid_legacy_schema"}
		var leg_res: Dictionary = validate_state(leg_d, true)
		if not bool(leg_res.get("ok", false)):
			return {"ok": false, "reason": "invalid_legacy_state:" + str(leg_res.get("reason", ""))}
		out["legacy"] = leg_res["data"]

	return {"ok": true, "data": out}


func validate_component_state(state_var: Variant, entity: Dictionary = {}, parked: bool = false) -> Dictionary:
	if not (state_var is Dictionary):
		return {"ok": false, "reason": "invalid_comp_initiative_type"}
	var state: Dictionary = state_var as Dictionary
	var clean_state: Dictionary = {}
	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()

	if state.is_empty():
		clean_state = default_component_state()
	else:
		var allowed_keys: Array[String] = ["count", "modifier", "active", "defeated", "rolled"]
		for raw_k: Variant in state.keys():
			if not (raw_k is String) or not (str(raw_k) in allowed_keys):
				return {"ok": false, "reason": "unknown_comp_initiative_key:" + str(raw_k)}

		var cnt_parsed: Dictionary = val_u.parse_int_val(state.get("count", 0))
		if not bool(cnt_parsed["ok"]) or absi(int(cnt_parsed["value"])) > MAX_INITIATIVE:
			return {"ok": false, "reason": "invalid_initiative_count"}

		var mod_parsed: Dictionary = val_u.parse_int_val(state.get("modifier", 0))
		if not bool(mod_parsed["ok"]) or absi(int(mod_parsed["value"])) > MAX_MODIFIER:
			return {"ok": false, "reason": "invalid_initiative_modifier"}

		for bk: String in ["active", "defeated", "rolled"]:
			if state.has(bk) and not (state[bk] is bool):
				return {"ok": false, "reason": "invalid_initiative_bool:" + bk}

		clean_state = {
			"count": int(cnt_parsed["value"]),
			"modifier": int(mod_parsed["value"]),
			"active": bool(state.get("active", true)),
			"defeated": bool(state.get("defeated", false)),
			"rolled": bool(state.get("rolled", false)),
		}

	if not entity.is_empty():
		if not parked and not bool(valid_u.is_unit_host(entity)):
			return {"ok": false, "reason": "initiative_requires_unit_host"}
		var comps_var: Variant = entity.get("components", [])
		if comps_var is Array:
			for raw_c: Variant in comps_var as Array:
				if raw_c is Dictionary:
					var c: Dictionary = raw_c as Dictionary
					var cid: String = str(valid_u.component_id_from_script(str(c.get("script", ""))))
					if cid == "scene_box":
						return {"ok": false, "reason": "component_conflict_with_scene_box:initiative"}
					if not parked and cid in ["obstacle", "wall", "map"]:
						return {"ok": false, "reason": "initiative_disallowed_on_obstacle"}
					if not parked and cid == "visual":
						var st_var: Variant = c.get("state", null)
						if st_var is Dictionary:
							var vd_var: Variant = (st_var as Dictionary).get("vector_drawing", null)
							if vd_var is Dictionary:
								var src_var: Variant = (vd_var as Dictionary).get("source", null)
								if src_var is Dictionary and str((src_var as Dictionary).get("kind", "")) in OBSTACLE_DRAWING_KINDS:
									return {"ok": false, "reason": "initiative_disallowed_on_obstacle"}

	return {"ok": true, "data": clean_state}


func configure_initiative(state: Dictionary) -> Dictionary:
	var gate: Dictionary = _check_gate("configure_initiative")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var checked: Dictionary = validate_state(state)
	if not bool(checked.get("ok", false)):
		var reason: String = str(checked.get("reason", "invalid_initiative_state"))
		_warn("candidate_initiative 配置校验失败：%s" % reason)
		return {"ok": false, "reason": reason}

	var normalized: Dictionary = checked["data"] as Dictionary
	var wid: String = str(normalized.get("world_id", ""))
	if not wid.is_empty() and (not wid.begins_with("campaign:") or not bool(_validation_utils().is_valid_uid(wid.substr(9)))):
		_warn("candidate_initiative.world_id='%s' 非 'campaign:<32hex>' 格式；宿主 apply_module_state 要求匹配战役 UID，跨战役导入建议同时为单位实体挂载 comp_initiative 组件。" % wid)

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


func configure_encounter(state: Dictionary) -> Dictionary:
	return configure_initiative(state)


func set_state(state: Dictionary) -> Dictionary:
	return configure_initiative(state)


func attach_initiative(
	entity_id: String,
	state: Dictionary = {},
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_initiative")
	if not bool(gate.get("ok", true)):
		return gate
	if manual and not parked:
		return {"ok": false, "reason": "manual_requires_parked"}
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return {"ok": false, "reason": "entity_not_found"}

	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var checked: Dictionary = validate_component_state(state, entity, effective_parked)
	if not bool(checked.get("ok", false)):
		var reason: String = str(checked.get("reason", "invalid_comp_initiative_state"))
		_warn("无法挂载 initiative 组件（%s）：%s" % [entity_id, reason])
		return {"ok": false, "reason": reason}

	var clean_state: Dictionary = checked["data"] as Dictionary
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_INITIATIVE_SCRIPT,
		clean_state,
		effective_parked,
		effective_manual
	))
	if not ok:
		return {"ok": false, "reason": "attach_component_failed"}
	return {
		"ok": true,
		"entity_id": entity_id,
		"state": clean_state,
		"parked": effective_parked,
		"manual": effective_manual,
	}


func attach_combatant(
	entity_id: String,
	count: int = 0,
	modifier: int = 0,
	active: bool = true,
	defeated: bool = false,
	rolled: bool = false,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	return attach_initiative(
		entity_id,
		make_combatant_state(count, modifier, active, defeated, rolled),
		parked,
		manual
	)


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


func _lookup_entity(entity_id: String) -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or entity_id.is_empty():
		return {}
	if wb.has_method("get_entity"):
		return wb.get_entity(entity_id)
	return {}


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
