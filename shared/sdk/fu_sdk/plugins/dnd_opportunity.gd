extends RefCounted
## Fu vtt 原生可选插件 SDK：dnd_opportunity（D&D 角色卡与百科，Steam Playtest v0.0.61–v0.0.62 暂不可用但保留存档数据）
##
## 对应官方源码：modules/dnd_opportunity/feature.gd、characters/cards.gd、
## reactions_2014.gd、health_2014.gd、exploration/exploration.gd、rest/workflow.gd、
## commerce/{equipment,trade}.gd、scenes/extension/module_configuration.gd。
##
## 说明：角色卡结构校验完整覆盖 id/edition("2014")/owner/access/revision/birth(64hex)/
## entity/offered/form/steps/prepared/work/notes 与 2014|2024 opportunity_edition、
## 5 种持久化包络形态；不复制官方数千行 D&D 2014 职业法表推导表。

const MODULE_ID: String = "dnd_opportunity"
const MODULE_VERSION: int = 1

const EDITIONS: Array[int] = [2014, 2024]
const MAX_CARDS: int = 64
const MAX_EXPLORATION: int = 128
const MAX_DELIVERIES: int = 64
const MAX_LIMIT: int = 256
const MAX_NOTES: int = 32
const MAX_CLONE_VISITS: int = 262144
const MAX_CARD_CLONE_VISITS: int = 65536
const MAX_SHARED_UNFOLD: int = 8192
const NOTE_KINDS: Array[String] = ["inventory", "hp_change", "slot_spend", "cross_module"]
const FORM_JOBS: Array[String] = ["fighter", "rogue", "cleric", "wizard", "ranger"]
const FORM_SOURCES: Array[String] = ["manual_total", "base_plus_race", "standard_array", "point_buy"]
const CARD_KEYS: Array[String] = [
	"id", "edition", "owner", "access", "revision", "birth",
	"form", "steps", "prepared", "offered", "entity", "work", "notes",
]
const FORM_KEYS: Array[String] = [
	"name", "job", "race", "background", "source", "scores",
	"skills", "replace", "expert", "enemy", "terrain",
]
const ENCOUNTER_KEYS: Array[String] = [
	"profiles", "actions", "effects", "turns", "marks", "refills", "combat",
]

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
		"playtest_blocked": true,
		"status": "playtest_blocked",
		"enabled": false,
	}


func default_state(edition: int = 2014) -> Dictionary:
	var safe_edition: int = edition if edition in EDITIONS else 2014
	var sheets: Dictionary = {
		"schema": 1,
		"cards": {},
	}
	if safe_edition != 2014:
		sheets["opportunity_edition"] = safe_edition
	return {
		"combined": 1,
		"sheets": sheets,
		"encounter": {},
	}


func validate_card(card_id: Variant, card_var: Variant) -> Dictionary:
	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	if not (card_id is String) or not bool(valid_u.is_valid_uid(str(card_id))):
		return {"ok": false, "reason": "invalid_dnd_card_id"}
	var cid: String = str(card_id)
	if not (card_var is Dictionary):
		return {"ok": false, "reason": "invalid_dnd_card_type"}
	if _has_cycle(card_var, 0, [], [MAX_CARD_CLONE_VISITS]):
		return {"ok": false, "reason": "cyclic_dnd_opportunity_state"}
	var row: Dictionary = card_var as Dictionary
	if row.size() != CARD_KEYS.size():
		return {"ok": false, "reason": "invalid_dnd_card_keys"}
	for rk: String in CARD_KEYS:
		if not row.has(rk):
			return {"ok": false, "reason": "missing_dnd_card_key:" + rk}

	if not (row["id"] is String) or str(row["id"]) != cid:
		return {"ok": false, "reason": "dnd_card_id_mismatch"}
	if not (row["edition"] is String) or str(row["edition"]) != "2014":
		return {"ok": false, "reason": "invalid_dnd_card_edition"}

	var owner_v: Variant = row["owner"]
	if not (owner_v is String):
		return {"ok": false, "reason": "invalid_dnd_card_owner_type"}
	var owner_s: String = str(owner_v)
	if owner_s != "host" and not bool(valid_u.is_valid_uid(owner_s)):
		return {"ok": false, "reason": "invalid_dnd_card_owner"}

	if not (row["access"] is bool):
		return {"ok": false, "reason": "invalid_dnd_card_access"}
	var rev_p: Dictionary = val_u.parse_int_val(row["revision"])
	if not bool(rev_p["ok"]) or int(rev_p["value"]) < 1:
		return {"ok": false, "reason": "invalid_dnd_card_revision"}
	if not (row["birth"] is String) or not bool(valid_u.is_valid_hex64(str(row["birth"]), false)):
		return {"ok": false, "reason": "invalid_dnd_card_birth"}

	var entity_v: Variant = row["entity"]
	if not (entity_v is String):
		return {"ok": false, "reason": "invalid_dnd_card_entity_type"}
	var entity_s: String = str(entity_v)
	if not entity_s.is_empty() and not bool(valid_u.is_valid_uid(entity_s)):
		return {"ok": false, "reason": "invalid_dnd_card_entity"}

	if not (row["steps"] is Array) or (row["steps"] as Array).size() > 5:
		return {"ok": false, "reason": "invalid_dnd_card_steps"}
	var steps: Array = row["steps"] as Array
	var clean_steps: Array = []
	var card_clone_budget: Array = [MAX_CARD_CLONE_VISITS, false]
	for raw_step: Variant in steps:
		if not (raw_step is Dictionary):
			return {"ok": false, "reason": "invalid_dnd_card_step"}
		var st_copy: Dictionary = _safe_clone_dict(raw_step as Dictionary, 0, [], card_clone_budget)
		if bool(card_clone_budget[1]):
			return {"ok": false, "reason": "dnd_opportunity_state_too_large"}
		if st_copy.has("asi"):
			var asi_p: Dictionary = val_u.parse_int_val(st_copy["asi"])
			if not bool(asi_p["ok"]):
				return {"ok": false, "reason": "invalid_dnd_card_step_asi"}
			st_copy["asi"] = int(asi_p["value"])
		clean_steps.append(st_copy)

	if not (row["prepared"] is Array):
		return {"ok": false, "reason": "invalid_dnd_card_prepared"}
	if not (row["work"] is Array):
		return {"ok": false, "reason": "invalid_dnd_card_work"}

	var offered_p: Dictionary = val_u.parse_int_val(row["offered"])
	if not bool(offered_p["ok"]) or int(offered_p["value"]) < maxi(1, steps.size()) or int(offered_p["value"]) > 5:
		return {"ok": false, "reason": "invalid_dnd_card_offered"}

	var notes_v: Variant = row["notes"]
	if not (notes_v is Dictionary) or (notes_v as Dictionary).size() > MAX_NOTES:
		return {"ok": false, "reason": "invalid_dnd_card_notes"}
	var notes: Dictionary = notes_v as Dictionary
	for nk: Variant in notes.keys():
		if not (nk is String) or not (notes[nk] is Dictionary):
			return {"ok": false, "reason": "invalid_dnd_card_note_entry"}
		var note: Dictionary = notes[nk] as Dictionary
		if note.size() != 3 or not note.has("source") or not note.has("kind") or not note.has("description"):
			return {"ok": false, "reason": "invalid_dnd_card_note_keys"}
		if not (note["kind"] is String) or not (str(note["kind"]) in NOTE_KINDS):
			return {"ok": false, "reason": "invalid_dnd_card_note_kind"}
		if not (note["source"] is String) or str(note["source"]).is_empty() or str(note["source"]).length() > 64:
			return {"ok": false, "reason": "invalid_dnd_card_note_source"}
		if not (note["description"] is String) or str(note["description"]).is_empty() or str(note["description"]).length() > 160:
			return {"ok": false, "reason": "invalid_dnd_card_note_description"}
		if str(nk) != str(note["source"]) + "/" + str(note["kind"]):
			return {"ok": false, "reason": "dnd_card_note_key_mismatch"}

	var form_v: Variant = row["form"]
	if not (form_v is Dictionary):
		return {"ok": false, "reason": "invalid_dnd_card_form_type"}
	var form: Dictionary = form_v as Dictionary
	if form.size() != FORM_KEYS.size():
		return {"ok": false, "reason": "invalid_dnd_card_form_keys"}
	for fk: String in FORM_KEYS:
		if not form.has(fk):
			return {"ok": false, "reason": "missing_dnd_card_form_key:" + fk}
	if not (form["name"] is String) or str(form["name"]).strip_edges().is_empty() or str(form["name"]).length() > 32:
		return {"ok": false, "reason": "invalid_dnd_card_form_name"}
	if not (form["job"] is String) or not (str(form["job"]) in FORM_JOBS):
		return {"ok": false, "reason": "invalid_dnd_card_form_job"}
	if not (form["source"] is String) or not (str(form["source"]) in FORM_SOURCES):
		return {"ok": false, "reason": "invalid_dnd_card_form_source"}
	if not (form["scores"] is Array) or (form["scores"] as Array).size() != 6:
		return {"ok": false, "reason": "invalid_dnd_card_form_scores"}
	var clean_scores: Array[int] = []
	for sc: Variant in form["scores"] as Array:
		var sc_p: Dictionary = val_u.parse_int_val(sc)
		if not bool(sc_p["ok"]) or int(sc_p["value"]) < 3 or int(sc_p["value"]) > 20:
			return {"ok": false, "reason": "invalid_dnd_card_form_score_range"}
		clean_scores.append(int(sc_p["value"]))
	if not (form["skills"] is Array) or not (form["replace"] is Dictionary) or not (form["expert"] is Array):
		return {"ok": false, "reason": "invalid_dnd_card_form_proficiencies"}
	if not (form["enemy"] is String) or not (form["terrain"] is String):
		return {"ok": false, "reason": "invalid_dnd_card_form_ranger_fields"}

	var clean_card: Dictionary = _safe_clone_dict(row, 0, [], card_clone_budget)
	if bool(card_clone_budget[1]):
		return {"ok": false, "reason": "dnd_opportunity_state_too_large"}
	clean_card["revision"] = int(rev_p["value"])
	clean_card["offered"] = int(offered_p["value"])
	clean_card["steps"] = clean_steps
	(clean_card["form"] as Dictionary)["scores"] = clean_scores
	return {"ok": true, "data": clean_card}


func validate_encounter(encounter_var: Variant) -> Dictionary:
	if not (encounter_var is Dictionary):
		return {"ok": false, "reason": "invalid_dnd_encounter_type"}
	if _has_cycle(encounter_var, 0, [], [MAX_CLONE_VISITS]):
		return {"ok": false, "reason": "cyclic_dnd_opportunity_state"}
	var enc: Dictionary = encounter_var as Dictionary
	if enc.is_empty():
		return {"ok": true, "data": {}}
	if enc.size() != ENCOUNTER_KEYS.size():
		return {"ok": false, "reason": "invalid_dnd_encounter_keys"}
	for ek: String in ENCOUNTER_KEYS:
		if not enc.has(ek):
			return {"ok": false, "reason": "missing_dnd_encounter_key:" + ek}
	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	for dict_k: String in ["profiles", "actions", "effects", "turns", "marks", "refills"]:
		var sub_v: Variant = enc[dict_k]
		if not (sub_v is Dictionary) or (sub_v as Dictionary).size() > MAX_LIMIT:
			return {"ok": false, "reason": "invalid_dnd_encounter_section:" + dict_k}
		for sub_id: Variant in (sub_v as Dictionary).keys():
			if not (sub_id is String) or not bool(valid_u.is_valid_uid(str(sub_id))):
				return {"ok": false, "reason": "invalid_dnd_encounter_id:" + dict_k}
	if not (enc["combat"] is String):
		return {"ok": false, "reason": "invalid_dnd_encounter_combat"}

	var enc_clone_budget: Array = [MAX_CLONE_VISITS, false]
	var clean_profiles: Dictionary = {}
	var raw_profiles: Dictionary = enc["profiles"] as Dictionary
	for pid: Variant in raw_profiles.keys():
		var p_var: Variant = raw_profiles[pid]
		if not (p_var is Dictionary):
			return {"ok": false, "reason": "invalid_dnd_encounter_profile"}
		var p: Dictionary = p_var as Dictionary
		if not p.has("ac") or not p.has("bonus") or not p.has("shield") or not (p["shield"] is bool):
			return {"ok": false, "reason": "invalid_dnd_encounter_profile"}
		var pac_p: Dictionary = val_u.parse_int_val(p["ac"])
		var pbon_p: Dictionary = val_u.parse_int_val(p["bonus"])
		if not bool(pac_p["ok"]) or not bool(pbon_p["ok"]):
			return {"ok": false, "reason": "invalid_dnd_encounter_profile"}
		var clean_p: Dictionary = _safe_clone_dict(p, 0, [], enc_clone_budget)
		if bool(enc_clone_budget[1]):
			return {"ok": false, "reason": "dnd_opportunity_state_too_large"}
		clean_p["ac"] = int(pac_p["value"])
		clean_p["bonus"] = int(pbon_p["value"])
		clean_p["shield"] = bool(p["shield"])
		clean_profiles[str(pid)] = clean_p

	var clean_turns: Dictionary = {}
	var raw_turns: Dictionary = enc["turns"] as Dictionary
	for tid: Variant in raw_turns.keys():
		var turn_p: Dictionary = val_u.parse_int_val(raw_turns[tid])
		if not bool(turn_p["ok"]) or int(turn_p["value"]) < 1:
			return {"ok": false, "reason": "invalid_dnd_encounter_turn"}
		clean_turns[str(tid)] = int(turn_p["value"])

	var clean_actions: Dictionary = {}
	var raw_actions: Dictionary = enc["actions"] as Dictionary
	var req_action_keys: Array[String] = [
		"id", "caster", "target", "kind", "request", "stage",
		"original", "outcome", "ticket", "by", "turn",
	]
	var action_stages: Array[String] = [
		"rolling", "offer", "paying", "paid", "done", "manual", "expired", "declined", "refused",
	]
	for aid: Variant in raw_actions.keys():
		var act_var: Variant = raw_actions[aid]
		if not (act_var is Dictionary):
			return {"ok": false, "reason": "invalid_dnd_encounter_action"}
		var act: Dictionary = act_var as Dictionary
		for ak: String in req_action_keys:
			if not act.has(ak):
				return {"ok": false, "reason": "missing_dnd_encounter_action_key:" + ak}
		var aid_s: String = str(aid)
		if not (act["id"] is String) or str(act["id"]) != aid_s:
			return {"ok": false, "reason": "invalid_dnd_encounter_action_id"}
		if not (act["caster"] is String) or not bool(valid_u.is_valid_uid(str(act["caster"]))):
			return {"ok": false, "reason": "invalid_dnd_encounter_action_caster"}
		if not (act["target"] is String) or not bool(valid_u.is_valid_uid(str(act["target"]))):
			return {"ok": false, "reason": "invalid_dnd_encounter_action_target"}
		if not (act["kind"] is String) or not (str(act["kind"]) in ["attack", "missile", "opportunity"]):
			return {"ok": false, "reason": "invalid_dnd_encounter_action_kind"}
		if not (act["by"] is String) or not (act["turn"] is String):
			return {"ok": false, "reason": "invalid_dnd_encounter_action_meta"}
		if not (act["request"] is String) or str(act["request"]) != "wf-" + aid_s:
			return {"ok": false, "reason": "invalid_dnd_encounter_action_request"}
		if not (act["original"] is Dictionary) or not (act["outcome"] is Dictionary) or not (act["ticket"] is Dictionary):
			return {"ok": false, "reason": "invalid_dnd_encounter_action_payload"}
		if not (act["stage"] is String) or not (str(act["stage"]) in action_stages):
			return {"ok": false, "reason": "invalid_dnd_encounter_action_stage"}
		var a_ac_p: Dictionary = val_u.parse_int_val(act.get("ac", null))
		var a_bon_p: Dictionary = val_u.parse_int_val(act.get("bonus", null))
		if not bool(a_ac_p["ok"]) or int(a_ac_p["value"]) < 0 or int(a_ac_p["value"]) > 100 \
				or not bool(a_bon_p["ok"]) or absi(int(a_bon_p["value"])) > 100:
			return {"ok": false, "reason": "invalid_dnd_encounter_action_stats"}
		var clean_act: Dictionary = _safe_clone_dict(act, 0, [], enc_clone_budget)
		if bool(enc_clone_budget[1]):
			return {"ok": false, "reason": "dnd_opportunity_state_too_large"}
		clean_act["ac"] = int(a_ac_p["value"])
		clean_act["bonus"] = int(a_bon_p["value"])
		var orig: Dictionary = clean_act["original"] as Dictionary
		if not orig.is_empty() and str(orig.get("kind", "")) != "magic_missile":
			var ot_p: Dictionary = val_u.parse_int_val(orig.get("total", null))
			var of_p: Dictionary = val_u.parse_int_val(orig.get("face", null))
			var ob_p: Dictionary = val_u.parse_int_val(orig.get("base_ac", null))
			if not bool(ot_p["ok"]) or not bool(of_p["ok"]) or int(of_p["value"]) < 1 or int(of_p["value"]) > 20 \
					or not bool(ob_p["ok"]) or int(ob_p["value"]) != int(a_ac_p["value"]):
				return {"ok": false, "reason": "invalid_dnd_encounter_action_original"}
			orig["total"] = int(ot_p["value"])
			orig["face"] = int(of_p["value"])
			orig["base_ac"] = int(ob_p["value"])
		var tkt: Dictionary = clean_act["ticket"] as Dictionary
		if not tkt.is_empty():
			var tkt_costs: Variant = tkt.get("costs", null)
			if tkt_costs is Dictionary:
				for ck: Variant in (tkt_costs as Dictionary).keys():
					var cv_p: Dictionary = val_u.parse_int_val((tkt_costs as Dictionary)[ck])
					if bool(cv_p["ok"]):
						(tkt_costs as Dictionary)[ck] = int(cv_p["value"])
		if clean_act.has("health") and clean_act["health"] is Dictionary:
			var act_h: Dictionary = clean_act["health"] as Dictionary
			for hk: String in ["die", "modifier"]:
				if act_h.has(hk):
					var hk_p: Dictionary = val_u.parse_int_val(act_h[hk])
					if bool(hk_p["ok"]):
						act_h[hk] = int(hk_p["value"])
			if act_h.get("authority", null) is Dictionary:
				var auth_d: Dictionary = act_h["authority"] as Dictionary
				if auth_d.has("revision"):
					var ar_p: Dictionary = val_u.parse_int_val(auth_d["revision"])
					if bool(ar_p["ok"]):
						auth_d["revision"] = int(ar_p["value"])
		clean_actions[aid_s] = clean_act

	var clean_effects: Dictionary = _safe_clone_dict(enc["effects"] as Dictionary, 0, [], enc_clone_budget)
	if bool(enc_clone_budget[1]):
		return {"ok": false, "reason": "dnd_opportunity_state_too_large"}
	var clean_marks: Dictionary = _safe_clone_dict(enc["marks"] as Dictionary, 0, [], enc_clone_budget)
	if bool(enc_clone_budget[1]):
		return {"ok": false, "reason": "dnd_opportunity_state_too_large"}
	var clean_refills: Dictionary = _safe_clone_dict(enc["refills"] as Dictionary, 0, [], enc_clone_budget)
	if bool(enc_clone_budget[1]):
		return {"ok": false, "reason": "dnd_opportunity_state_too_large"}

	return {
		"ok": true,
		"data": {
			"profiles": clean_profiles,
			"actions": clean_actions,
			"effects": clean_effects,
			"turns": clean_turns,
			"marks": clean_marks,
			"refills": clean_refills,
			"combat": str(enc["combat"]),
		},
	}


func validate_state(state_var: Variant) -> Dictionary:
	if not (state_var is Dictionary):
		return {"ok": false, "reason": "invalid_dnd_opportunity_state_type"}
	if _has_cycle(state_var, 0, [], [MAX_CLONE_VISITS]):
		return {"ok": false, "reason": "cyclic_dnd_opportunity_state"}
	var state: Dictionary = state_var as Dictionary
	if state.is_empty():
		return {"ok": true, "data": {}, "empty": true}

	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	# Parse 5 envelope shapes matching modules/dnd_opportunity/feature.gd:_sections
	var sheets: Dictionary = {}
	var encounter: Dictionary = {}
	var health: Dictionary = {}
	var is_combined: bool = state.has("combined")
	var combined_ver: int = 0

	if is_combined:
		var comb_p: Dictionary = val_u.parse_int_val(state.get("combined", null))
		if bool(comb_p["ok"]) and int(comb_p["value"]) == 2 and state.size() == 4 and state.get("health", null) is Dictionary and state.get("sheets", null) is Dictionary and state.get("encounter", null) is Dictionary:
			combined_ver = 2
			sheets = state["sheets"] as Dictionary
			encounter = state["encounter"] as Dictionary
			health = state["health"] as Dictionary
		elif bool(comb_p["ok"]) and int(comb_p["value"]) == 1 and state.size() == 3 and state.get("sheets", null) is Dictionary and state.get("encounter", null) is Dictionary:
			combined_ver = 1
			sheets = state["sheets"] as Dictionary
			encounter = state["encounter"] as Dictionary
		else:
			return {"ok": false, "reason": "invalid_dnd_combined_envelope"}
	else:
		var is_sheets_shape: bool = (
			state.has("cards")
			or state.has("exploration")
			or state.has("rests")
			or state.has("deliveries")
			or state.has("commerce")
			or state.has("opportunity_edition")
		)
		if is_sheets_shape:
			sheets = state
		else:
			encounter = state

	var enc_res: Dictionary = validate_encounter(encounter)
	if not bool(enc_res.get("ok", false)):
		return enc_res

	var clean_health: Dictionary = {}
	if not health.is_empty():
		if health.size() != 2 or not (health.get("bindings", null) is Dictionary) or not (health.get("events", null) is Dictionary):
			return {"ok": false, "reason": "invalid_dnd_health_keys"}
		var h_binds: Dictionary = health["bindings"] as Dictionary
		var h_events: Dictionary = health["events"] as Dictionary
		if h_binds.size() > MAX_LIMIT or h_events.size() > MAX_LIMIT:
			return {"ok": false, "reason": "dnd_health_limit_exceeded"}
		var health_budget: Array = [MAX_CLONE_VISITS, false]
		var clean_binds: Dictionary = {}
		for bid: Variant in h_binds.keys():
			if not (bid is String) or not bool(valid_u.is_valid_uid(str(bid))) or not (h_binds[bid] is Dictionary):
				return {"ok": false, "reason": "invalid_dnd_health_binding"}
			var b: Dictionary = _safe_clone_dict(h_binds[bid] as Dictionary, 0, [], health_budget)
			if bool(health_budget[1]):
				return {"ok": false, "reason": "dnd_opportunity_state_too_large"}
			for bik: String in ["die", "modifier", "applied_level"]:
				if b.has(bik):
					var bi_p: Dictionary = val_u.parse_int_val(b[bik])
					if not bool(bi_p["ok"]):
						return {"ok": false, "reason": "invalid_dnd_health_binding_int:" + bik}
					b[bik] = int(bi_p["value"])
			clean_binds[str(bid)] = b
		var clean_hevents: Dictionary = {}
		for hid: Variant in h_events.keys():
			if not (hid is String) or not bool(valid_u.is_valid_uid(str(hid))) or not (h_events[hid] is Dictionary):
				return {"ok": false, "reason": "invalid_dnd_health_event"}
			var ev: Dictionary = _safe_clone_dict(h_events[hid] as Dictionary, 0, [], health_budget)
			if bool(health_budget[1]):
				return {"ok": false, "reason": "dnd_opportunity_state_too_large"}
			if ev.has("missiles"):
				var mis_p: Dictionary = val_u.parse_int_val(ev["missiles"])
				if not bool(mis_p["ok"]):
					return {"ok": false, "reason": "invalid_dnd_health_event_missiles"}
				ev["missiles"] = int(mis_p["value"])
			if ev.get("authority", null) is Dictionary:
				var h_auth: Dictionary = ev["authority"] as Dictionary
				if h_auth.has("revision"):
					var har_p: Dictionary = val_u.parse_int_val(h_auth["revision"])
					if not bool(har_p["ok"]):
						return {"ok": false, "reason": "invalid_dnd_health_event_revision"}
					h_auth["revision"] = int(har_p["value"])
			clean_hevents[str(hid)] = ev
		clean_health = {"bindings": clean_binds, "events": clean_hevents}

	# Validate sheets sub-section
	var sheet_copy_budget: Array = [MAX_CLONE_VISITS, false]
	var sheet_copy: Dictionary = _safe_clone_dict(sheets, 0, [], sheet_copy_budget)
	if bool(sheet_copy_budget[1]):
		return {"ok": false, "reason": "dnd_opportunity_state_too_large"}
	var clean_rests: Variant = null
	if sheet_copy.has("exploration"):
		var exp_v: Variant = sheet_copy["exploration"]
		if not (exp_v is Dictionary) or (exp_v as Dictionary).size() > MAX_EXPLORATION:
			return {"ok": false, "reason": "invalid_dnd_exploration"}
		for ek: Variant in (exp_v as Dictionary).keys():
			if not (ek is String) or not bool(valid_u.is_valid_uid(str(ek))):
				return {"ok": false, "reason": "invalid_dnd_exploration_id"}
		sheet_copy.erase("exploration")

	if sheet_copy.has("rests"):
		var rst_v: Variant = sheet_copy["rests"]
		if not (rst_v is Dictionary):
			return {"ok": false, "reason": "invalid_dnd_rests"}
		var rsts: Dictionary = rst_v as Dictionary
		var norm_rsts: Dictionary = {}
		var rests_budget: Array = [MAX_CLONE_VISITS, false]
		for rk: Variant in rsts.keys():
			if not (rk is String) or not bool(valid_u.is_valid_uid(str(rk))):
				return {"ok": false, "reason": "invalid_dnd_rest_id"}
			var r_var: Variant = rsts[rk]
			if not (r_var is Dictionary):
				return {"ok": false, "reason": "invalid_dnd_rest_entry"}
			var r_copy: Dictionary = _safe_clone_dict(r_var as Dictionary, 0, [], rests_budget)
			if bool(rests_budget[1]):
				return {"ok": false, "reason": "dnd_opportunity_state_too_large"}
			for rik: String in ["start", "level", "con", "faces", "hp_max", "qualified", "finish", "benefit", "duration", "card_revision"]:
				if r_copy.has(rik):
					var ri_p: Dictionary = val_u.parse_int_val(r_copy[rik])
					if not bool(ri_p["ok"]):
						return {"ok": false, "reason": "invalid_dnd_rest_int:" + rik}
					r_copy[rik] = int(ri_p["value"])
			if r_copy.has("start_hp") and r_copy["start_hp"] != null:
				var shp_p: Dictionary = val_u.parse_int_val(r_copy["start_hp"])
				if not bool(shp_p["ok"]):
					return {"ok": false, "reason": "invalid_dnd_rest_start_hp"}
				r_copy["start_hp"] = int(shp_p["value"])
			if r_copy.get("events", null) is Array:
				for rev_v: Variant in r_copy["events"] as Array:
					if rev_v is Dictionary and (rev_v as Dictionary).has("minute"):
						var rm_p: Dictionary = val_u.parse_int_val((rev_v as Dictionary)["minute"])
						if not bool(rm_p["ok"]):
							return {"ok": false, "reason": "invalid_dnd_rest_event_minute"}
						(rev_v as Dictionary)["minute"] = int(rm_p["value"])
			if r_copy.get("slots", null) is Array:
				var r_slots: Array = r_copy["slots"] as Array
				for s_i: int in range(r_slots.size()):
					var rs_p: Dictionary = val_u.parse_int_val(r_slots[s_i])
					if not bool(rs_p["ok"]):
						return {"ok": false, "reason": "invalid_dnd_rest_slot"}
					r_slots[s_i] = int(rs_p["value"])
			if r_copy.get("claims", null) is Dictionary:
				var claims_d: Dictionary = r_copy["claims"] as Dictionary
				for ck: Variant in claims_d.keys():
					if claims_d[ck] is Dictionary:
						var cl: Dictionary = claims_d[ck] as Dictionary
						if cl.has("face"):
							var cf_p: Dictionary = val_u.parse_int_val(cl["face"])
							if not bool(cf_p["ok"]):
								return {"ok": false, "reason": "invalid_dnd_rest_claim_face"}
							cl["face"] = int(cf_p["value"])
						if cl.get("slots", null) is Array:
							var cslots: Array = cl["slots"] as Array
							for cs_i: int in range(cslots.size()):
								var cs_p: Dictionary = val_u.parse_int_val(cslots[cs_i])
								if not bool(cs_p["ok"]):
									return {"ok": false, "reason": "invalid_dnd_rest_claim_slot"}
								cslots[cs_i] = int(cs_p["value"])
						if cl.get("review", null) is Dictionary and (cl["review"] as Dictionary).has("minute"):
							var crm_p: Dictionary = val_u.parse_int_val((cl["review"] as Dictionary)["minute"])
							if not bool(crm_p["ok"]):
								return {"ok": false, "reason": "invalid_dnd_rest_review_minute"}
							(cl["review"] as Dictionary)["minute"] = int(crm_p["value"])
			norm_rsts[str(rk)] = r_copy
		clean_rests = norm_rsts
		sheet_copy.erase("rests")

	if sheet_copy.has("deliveries"):
		var del_v: Variant = sheet_copy["deliveries"]
		if not (del_v is Dictionary) or (del_v as Dictionary).size() > MAX_DELIVERIES:
			return {"ok": false, "reason": "invalid_dnd_deliveries"}
		for dk: Variant in (del_v as Dictionary).keys():
			if not (dk is String) or not bool(valid_u.is_valid_uid(str(dk))):
				return {"ok": false, "reason": "invalid_dnd_delivery_id"}
		sheet_copy.erase("deliveries")

	if sheet_copy.has("commerce"):
		var com_v: Variant = sheet_copy["commerce"]
		if not (com_v is Dictionary):
			return {"ok": false, "reason": "invalid_dnd_commerce"}
		var com: Dictionary = com_v as Dictionary
		if not com.is_empty():
			if com.size() != 2 or not (com.get("wallets", null) is Dictionary) or not (com.get("orders", null) is Dictionary):
				return {"ok": false, "reason": "invalid_dnd_commerce_keys"}
			if (com["wallets"] as Dictionary).size() > 65 or (com["orders"] as Dictionary).size() > 128:
				return {"ok": false, "reason": "dnd_commerce_limit_exceeded"}
		sheet_copy.erase("commerce")

	var ed_p: Dictionary = val_u.parse_int_val(sheet_copy.get("opportunity_edition", 2014))
	if not bool(ed_p["ok"]) or not (int(ed_p["value"]) in EDITIONS):
		return {"ok": false, "reason": "invalid_opportunity_edition"}
	var edition_val: int = int(ed_p["value"])
	sheet_copy.erase("opportunity_edition")

	var clean_cards: Dictionary = {}
	var has_cards_block: bool = not sheet_copy.is_empty()
	if has_cards_block:
		if sheet_copy.size() != 2 or not sheet_copy.has("schema") or not sheet_copy.has("cards"):
			return {"ok": false, "reason": "invalid_dnd_cards_envelope"}
		var cs_p: Dictionary = val_u.parse_int_val(sheet_copy["schema"])
		if not bool(cs_p["ok"]) or int(cs_p["value"]) != 1:
			return {"ok": false, "reason": "invalid_dnd_cards_schema"}
		var cards_v: Variant = sheet_copy["cards"]
		if not (cards_v is Dictionary) or (cards_v as Dictionary).size() > MAX_CARDS:
			return {"ok": false, "reason": "dnd_cards_limit_exceeded"}
		var cards: Dictionary = cards_v as Dictionary
		for cid: Variant in cards.keys():
			var c_res: Dictionary = validate_card(cid, cards[cid])
			if not bool(c_res.get("ok", false)):
				return c_res
			clean_cards[str(cid)] = c_res["data"]

	var clean_sheets_budget: Array = [MAX_CLONE_VISITS, false]
	var clean_sheets: Dictionary = _safe_clone_dict(sheets, 0, [], clean_sheets_budget)
	if bool(clean_sheets_budget[1]):
		return {"ok": false, "reason": "dnd_opportunity_state_too_large"}
	if clean_rests != null:
		clean_sheets["rests"] = clean_rests
	if clean_sheets.has("opportunity_edition"):
		clean_sheets["opportunity_edition"] = edition_val
	if has_cards_block:
		clean_sheets["schema"] = 1
		clean_sheets["cards"] = clean_cards

	var clean_out: Dictionary = {}
	if is_combined:
		clean_out = {
			"combined": combined_ver,
			"sheets": clean_sheets,
			"encounter": enc_res["data"],
		}
		if combined_ver == 2:
			clean_out["health"] = clean_health
	else:
		if sheets.is_empty():
			clean_out = enc_res["data"]
		else:
			clean_out = clean_sheets

	return {"ok": true, "data": clean_out}


func configure_dnd_opportunity(state: Dictionary) -> Dictionary:
	var gate: Dictionary = _check_gate("configure_dnd_opportunity")
	if not bool(gate.get("ok", true)):
		return gate
	return _configure_dnd_opportunity_impl(state, gate)


func _configure_dnd_opportunity_impl(state: Dictionary, gate: Dictionary) -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var checked: Dictionary = validate_state(state)
	if not bool(checked.get("ok", false)):
		var reason: String = str(checked.get("reason", "invalid_dnd_opportunity_state"))
		_warn("dnd_opportunity 配置校验失败：%s" % reason)
		return {"ok": false, "reason": reason}

	var normalized: Dictionary = checked["data"] as Dictionary
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, normalized))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"config": normalized,
		"enabled": bool(gate.get("enabled", false)),
		"status": str(gate.get("status", "playtest_blocked")),
		"policy": str(gate.get("policy", "preserve")),
		"preserved": true,
	}


func set_edition(edition: int) -> Dictionary:
	var gate: Dictionary = _check_gate("set_edition")
	if not bool(gate.get("ok", true)):
		return gate
	if not (edition in EDITIONS):
		return {"ok": false, "reason": "invalid_opportunity_edition"}
	var current: Dictionary = get_state()
	if current.is_empty():
		return _configure_dnd_opportunity_impl(default_state(edition), gate)
	var state_budget: Array = [MAX_CLONE_VISITS, false]
	var next: Dictionary = _safe_clone_dict(current, 0, [], state_budget)
	if bool(state_budget[1]):
		return {"ok": false, "reason": "dnd_opportunity_state_too_large"}
	if next.has("combined") and next.get("sheets", null) is Dictionary:
		(next["sheets"] as Dictionary)["opportunity_edition"] = edition
	elif next.has("cards") or next.has("opportunity_edition") or next.has("exploration") or next.has("rests") or next.has("deliveries") or next.has("commerce"):
		next["opportunity_edition"] = edition
	else:
		next = default_state(edition)
	return _configure_dnd_opportunity_impl(next, gate)


func set_state(state: Dictionary) -> Dictionary:
	return configure_dnd_opportunity(state)


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


func _get_adapter() -> RefCounted:
	var wb: RefCounted = _wb()
	if wb != null and wb.has_method("get_adapter"):
		return wb.get_adapter()
	return null


func _check_gate(action: String) -> Dictionary:
	if _module_registry != null:
		return _module_registry.check_and_warn(MODULE_ID, action)
	return {
		"ok": true,
		"enabled": false,
		"status": "playtest_blocked",
		"policy": "preserve",
		"skipped": false,
	}


func _warn(message: String) -> void:
	if _log_bus != null:
		_log_bus.warn(MODULE_ID, message)
	else:
		push_warning("[FuSdk/WARNING][%s] %s" % [MODULE_ID, message])


## 保持白盒测试兼容性：委托 utils/bounded_cloner.gd 执行嵌套容器环检测。
func _has_cycle(v: Variant, depth: int = 0, stack: Array = [], budget: Array = []) -> bool:
	return bool(_bounded_cloner().has_cycle(v, depth, stack, budget, MAX_CLONE_VISITS))


## 保持白盒测试兼容性：委托 utils/bounded_cloner.gd 执行 DnD 字典有界深拷贝。
func _safe_clone_dict(d: Dictionary, depth: int = 0, stack: Array = [], budget: Array = []) -> Dictionary:
	return _bounded_cloner().dnd_clone_dict(d, depth, stack, budget, MAX_CLONE_VISITS, MAX_SHARED_UNFOLD)
