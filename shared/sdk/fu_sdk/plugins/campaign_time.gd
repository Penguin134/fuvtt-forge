extends RefCounted
## Fu vtt 原生可选插件 SDK：campaign_time（战役世界时间，Steam Playtest v0.0.61–v0.0.62 暂不可用但保留存档数据）
##
## 对应官方源码：modules/campaign_time/feature.gd、scenes/extension/module_configuration.gd、
## scenes/systems/world/world_module_state.gd。

const MODULE_ID: String = "campaign_time"
const MODULE_VERSION: int = 1
const MAX_MINUTE: int = 100000000
const EFFECT_STATUSES: Array[String] = ["active", "expired", "corrected"]

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
		"playtest_blocked": true,
		"status": "playtest_blocked",
		"enabled": false,
	}


func default_state(era: String = "") -> Dictionary:
	var clean_era: String = era.strip_edges().to_lower()
	if not bool(_validation_utils().is_valid_uid(clean_era)):
		clean_era = "fu_sdk:campaign_time:default_era".sha256_text().left(32)
	return {
		"minute": 0,
		"era": clean_era,
		"revision": 1,
		"sources": {},
		"effects": {},
	}


func make_source(fingerprint: String, minute: int) -> Dictionary:
	return {
		"fingerprint": fingerprint,
		"minute": clampi(minute, 0, MAX_MINUTE),
	}


func make_effect(until_minute: int, name: String, status: String = "active") -> Dictionary:
	return {
		"until": until_minute,
		"name": name,
		"status": status if status in EFFECT_STATUSES else "active",
	}


func validate_state(state_var: Variant) -> Dictionary:
	if not (state_var is Dictionary):
		return {"ok": false, "reason": "invalid_campaign_time_state_type"}
	var state: Dictionary = state_var as Dictionary
	if state.is_empty():
		return {"ok": true, "data": {}, "empty": true}

	for raw_k: Variant in state.keys():
		if not (raw_k is String) or not (str(raw_k) in ["minute", "era", "revision", "sources", "effects"]):
			return {"ok": false, "reason": "unknown_campaign_time_key:" + str(raw_k)}

	for req_k: String in ["minute", "era", "revision", "sources", "effects"]:
		if not state.has(req_k):
			return {"ok": false, "reason": "missing_campaign_time_key:" + req_k}

	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()

	var min_p: Dictionary = val_u.parse_int_val(state["minute"])
	if not bool(min_p["ok"]) or int(min_p["value"]) < 0 or int(min_p["value"]) > MAX_MINUTE:
		return {"ok": false, "reason": "invalid_campaign_time_minute"}
	var minute_val: int = int(min_p["value"])

	var era_v: Variant = state["era"]
	if not (era_v is String) or not bool(valid_u.is_valid_uid(str(era_v))):
		return {"ok": false, "reason": "invalid_campaign_time_era"}

	var rev_p: Dictionary = val_u.parse_int_val(state["revision"])
	if not bool(rev_p["ok"]) or int(rev_p["value"]) <= 0:
		return {"ok": false, "reason": "invalid_campaign_time_revision"}
	var revision_val: int = int(rev_p["value"])

	var sources_v: Variant = state["sources"]
	if not (sources_v is Dictionary):
		return {"ok": false, "reason": "invalid_campaign_time_sources_type"}
	var sources: Dictionary = sources_v as Dictionary
	var clean_sources: Dictionary = {}
	for raw_sid: Variant in sources.keys():
		if not (raw_sid is String) or not bool(valid_u.is_valid_uid(str(raw_sid))):
			return {"ok": false, "reason": "invalid_campaign_time_source_id"}
		var srow_v: Variant = sources[raw_sid]
		if not (srow_v is Dictionary):
			return {"ok": false, "reason": "invalid_campaign_time_source_row"}
		var srow: Dictionary = srow_v as Dictionary
		var sm_p: Dictionary = val_u.parse_int_val(srow.get("minute", null))
		if not (srow.get("fingerprint", null) is String) or not bool(sm_p["ok"]):
			return {"ok": false, "reason": "invalid_campaign_time_source_fields"}
		if bool(valid_u.has_nul(str(srow["fingerprint"]))):
			return {"ok": false, "reason": "invalid_campaign_time_source_fingerprint"}
		clean_sources[str(raw_sid)] = {
			"fingerprint": str(srow["fingerprint"]),
			"minute": int(sm_p["value"]),
		}

	var effects_v: Variant = state["effects"]
	if not (effects_v is Dictionary):
		return {"ok": false, "reason": "invalid_campaign_time_effects_type"}
	var effects: Dictionary = effects_v as Dictionary
	var clean_effects: Dictionary = {}
	for raw_eid: Variant in effects.keys():
		if not (raw_eid is String) or not bool(valid_u.is_valid_uid(str(raw_eid))):
			return {"ok": false, "reason": "invalid_campaign_time_effect_id"}
		var eid: String = str(raw_eid)
		if not clean_sources.has(eid):
			return {"ok": false, "reason": "orphan_campaign_time_effect"}
		var erow_v: Variant = effects[raw_eid]
		if not (erow_v is Dictionary):
			return {"ok": false, "reason": "invalid_campaign_time_effect_row"}
		var erow: Dictionary = erow_v as Dictionary
		var eu_p: Dictionary = val_u.parse_int_val(erow.get("until", null))
		if not bool(eu_p["ok"]) or not (erow.get("name", null) is String):
			return {"ok": false, "reason": "invalid_campaign_time_effect_fields"}
		if bool(valid_u.has_nul(str(erow["name"]))):
			return {"ok": false, "reason": "invalid_campaign_time_effect_name"}
		var st_v: Variant = erow.get("status", null)
		if not (st_v is String) or not (str(st_v) in EFFECT_STATUSES):
			return {"ok": false, "reason": "invalid_campaign_time_effect_status"}
		clean_effects[eid] = {
			"until": int(eu_p["value"]),
			"name": str(erow["name"]),
			"status": str(st_v),
		}

	return {
		"ok": true,
		"data": {
			"minute": minute_val,
			"era": str(era_v),
			"revision": revision_val,
			"sources": clean_sources,
			"effects": clean_effects,
		},
	}


func configure_campaign_time(state: Dictionary) -> Dictionary:
	var gate: Dictionary = _check_gate("configure_campaign_time")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var checked: Dictionary = validate_state(state)
	if not bool(checked.get("ok", false)):
		var reason: String = str(checked.get("reason", "invalid_campaign_time_state"))
		_warn("campaign_time 配置校验失败：%s" % reason)
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


func set_state(state: Dictionary) -> Dictionary:
	return configure_campaign_time(state)


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
