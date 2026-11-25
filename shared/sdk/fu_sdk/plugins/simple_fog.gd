extends RefCounted
## Fu vtt 原生可选插件 SDK：simple_fog（简易迷雾 fog_config.gd v2、exploration 历史、视野与光源组件）
##
## 对应官方源码：modules/simple_fog/feature_simple_fog.gd、fog_config.gd、
## comp_simple_vision.gd、comp_simple_light.gd、native/SimpleVisionKernel.History.cs。

const MODULE_ID: String = "simple_fog"
const MODULE_VERSION: int = 1
const FOG_CONFIG_VERSION: int = 2
const MAX_VIEWERS: int = 128

const COMP_SIMPLE_VISION_SCRIPT: String = "res://modules/simple_fog/comp_simple_vision.gd"
const COMP_SIMPLE_LIGHT_SCRIPT: String = "res://modules/simple_fog/comp_simple_light.gd"
const COMP_SCENE_BOX_SCRIPT: String = "res://modules/scene_box/comp_scene_box.gd"

const EFFECT_IDS: Array[int] = [0, 1, 2, 4, 6]
const SHADOW_FILTERS: Array[int] = [0, 1, 2]
const MAX_EXPLORATION_COMPRESSED_BYTES: int = 4 * 1024 * 1024
const MAX_EXPLORATION_UNCOMPRESSED_BYTES: int = 64 * 1024 * 1024

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


func default_fog_config() -> Dictionary:
	return {
		"version": FOG_CONFIG_VERSION,
		"unseen_color": Color.BLACK,
		"visible_tint": Color.TRANSPARENT,
		"unseen_effect": 0,
		"visible_effect": 0,
		"history_enabled": false,
		"history_color": Color(0.0, 0.0, 0.0, 0.55),
		"history_effect": 0,
		"dm_opacity": 0.30,
		"vision_threshold": 0.5,
		"vision_feather": 0.04,
		"shadow_filter": 0,
		"shadow_smooth": 0.0,
		"hide_unseen_entities": true,
	}


func coerce_color(raw: Variant, fallback: Color = Color.BLACK) -> Dictionary:
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("coerce_color_value"):
		return adapter.coerce_color_value(raw, fallback)
	return _value_utils().coerce_color_value(raw, fallback)


func is_valid_exploration_bytes(blob: Variant) -> bool:
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("is_valid_simple_fog_exploration"):
		return bool(adapter.is_valid_simple_fog_exploration(blob))
	if not (blob is PackedByteArray):
		return false
	var bytes: PackedByteArray = blob as PackedByteArray
	if bytes.is_empty():
		return true
	if bytes.size() <= 8 or bytes.size() > MAX_EXPLORATION_COMPRESSED_BYTES:
		return false
	if bytes[0] != 0x53 or bytes[1] != 0x46 or bytes[2] != 0x48 or bytes[3] != 0x32:
		return false
	if bytes[7] >= 128:
		return false
	var raw_len: int = int(bytes[4]) | (int(bytes[5]) << 8) | (int(bytes[6]) << 16) | (int(bytes[7]) << 24)
	return raw_len >= 1 and raw_len <= MAX_EXPLORATION_UNCOMPRESSED_BYTES


func validate_fog_config(state: Dictionary, coerce_inputs: bool = true) -> Dictionary:
	var result: Dictionary = default_fog_config()
	for raw_k: Variant in state.keys():
		if not (raw_k is String):
			return {"ok": false, "reason": "unknown_fog_config_key_type"}
		var k_str: String = raw_k as String
		if k_str == "exploration":
			continue
		if not result.has(k_str):
			return {"ok": false, "reason": "unknown_fog_config_key:" + k_str}
		result[k_str] = state[raw_k]

	var val_u: Variant = _value_utils()
	var ver_v: Variant = result.get("version", null)
	if coerce_inputs:
		var ver_p: Dictionary = val_u.parse_int_val(ver_v)
		if not bool(ver_p["ok"]) or not (int(ver_p["value"]) in [1, 2]):
			return {"ok": false, "reason": "invalid_fog_config_version"}
	else:
		if not (ver_v is int) or not (int(ver_v) in [1, 2]):
			return {"ok": false, "reason": "invalid_fog_config_version"}
	result["version"] = FOG_CONFIG_VERSION

	if not (result.get("hide_unseen_entities", null) is bool) or not (result.get("history_enabled", null) is bool):
		return {"ok": false, "reason": "invalid_fog_config_bool"}

	for ekey: String in ["unseen_effect", "visible_effect", "history_effect"]:
		var ev: Variant = result.get(ekey, null)
		if coerce_inputs:
			var ev_p: Dictionary = val_u.parse_int_val(ev)
			if not bool(ev_p["ok"]) or not (int(ev_p["value"]) in EFFECT_IDS):
				return {"ok": false, "reason": "invalid_fog_effect:" + ekey}
			result[ekey] = int(ev_p["value"])
		else:
			if not (ev is int) or not (int(ev) in EFFECT_IDS):
				return {"ok": false, "reason": "invalid_fog_effect:" + ekey}

	for ckey: String in ["unseen_color", "visible_tint", "history_color"]:
		var raw_c: Variant = result.get(ckey, null)
		if coerce_inputs:
			var coerced: Dictionary = coerce_color(raw_c)
			if not bool(coerced.get("ok", false)):
				return {"ok": false, "reason": "invalid_fog_color:" + ckey}
			result[ckey] = coerced["color"]
		else:
			if not (raw_c is Color):
				return {"ok": false, "reason": "invalid_fog_color_type:" + ckey}
			var c: Color = raw_c as Color
			for ch: float in [c.r, c.g, c.b, c.a]:
				if not is_finite(ch) or ch < 0.0 or ch > 1.0:
					return {"ok": false, "reason": "invalid_fog_color_channel:" + ckey}

	var uc: Color = result["unseen_color"] as Color
	if uc.a != 1.0:
		return {"ok": false, "reason": "unseen_color_alpha_must_be_one"}

	for fkey: String in ["dm_opacity", "vision_threshold", "vision_feather", "shadow_smooth"]:
		var fv: Variant = result.get(fkey, null)
		if coerce_inputs:
			if not (fv is int or fv is float):
				return {"ok": false, "reason": "invalid_fog_float_type:" + fkey}
			var cast_f: float = float(fv)
			if not is_finite(cast_f):
				return {"ok": false, "reason": "non_finite_fog_float:" + fkey}
			result[fkey] = cast_f
		else:
			if not (fv is float) or not is_finite(float(fv)):
				return {"ok": false, "reason": "invalid_fog_float:" + fkey}

	var dm_op: float = float(result["dm_opacity"])
	var v_thr: float = float(result["vision_threshold"])
	var v_fea: float = float(result["vision_feather"])
	var s_smo: float = float(result["shadow_smooth"])
	if dm_op < 0.01 or dm_op > 1.0:
		return {"ok": false, "reason": "dm_opacity_out_of_range"}
	if v_thr < 0.0 or v_thr > 1.0:
		return {"ok": false, "reason": "vision_threshold_out_of_range"}
	if v_fea < 0.0 or v_fea > 0.5:
		return {"ok": false, "reason": "vision_feather_out_of_range"}
	if s_smo < 0.0 or s_smo > 16.0:
		return {"ok": false, "reason": "shadow_smooth_out_of_range"}

	var sf: Variant = result.get("shadow_filter", null)
	if coerce_inputs:
		var sf_p: Dictionary = val_u.parse_int_val(sf)
		if not bool(sf_p["ok"]) or not (int(sf_p["value"]) in SHADOW_FILTERS):
			return {"ok": false, "reason": "invalid_shadow_filter"}
		result["shadow_filter"] = int(sf_p["value"])
	else:
		if not (sf is int) or not (int(sf) in SHADOW_FILTERS):
			return {"ok": false, "reason": "invalid_shadow_filter"}

	if state.has("exploration"):
		var raw_exp: Variant = state.get("exploration")
		if not is_valid_exploration_bytes(raw_exp):
			return {"ok": false, "reason": "invalid_exploration_bytes"}
		var exp_bytes: PackedByteArray = raw_exp as PackedByteArray
		if not exp_bytes.is_empty():
			result["exploration"] = exp_bytes.duplicate()

	return {"ok": true, "data": result}


func make_fog_config(
	overrides: Dictionary = {},
	exploration: PackedByteArray = PackedByteArray()
) -> Dictionary:
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("make_simple_fog_world_state"):
		return adapter.make_simple_fog_world_state(overrides, exploration)
	var val_u: Variant = _value_utils()
	var result: Dictionary = default_fog_config()
	for raw_key: Variant in overrides.keys():
		if not (raw_key is String):
			continue
		var key: String = raw_key as String
		if key == "exploration":
			continue
		if not result.has(key):
			continue
		var val: Variant = overrides[raw_key]
		match key:
			"version":
				result["version"] = FOG_CONFIG_VERSION
			"unseen_color":
				var uc: Dictionary = coerce_color(val, Color.BLACK)
				if bool(uc.get("ok", false)) and (uc["color"] as Color).a == 1.0:
					result["unseen_color"] = uc["color"]
			"visible_tint":
				var vt: Dictionary = coerce_color(val, Color.TRANSPARENT)
				if bool(vt.get("ok", false)):
					result["visible_tint"] = vt["color"]
			"history_color":
				var hc: Dictionary = coerce_color(val, Color(0.0, 0.0, 0.0, 0.55))
				if bool(hc.get("ok", false)):
					result["history_color"] = hc["color"]
			"unseen_effect", "visible_effect", "history_effect":
				var ef_p: Dictionary = val_u.parse_int_val(val)
				if bool(ef_p["ok"]) and int(ef_p["value"]) in EFFECT_IDS:
					result[key] = int(ef_p["value"])
			"history_enabled", "hide_unseen_entities":
				if val is bool:
					result[key] = val
			"dm_opacity":
				if val is int or val is float:
					var f_dm: float = float(val)
					result["dm_opacity"] = clampf(f_dm if is_finite(f_dm) else 0.30, 0.01, 1.0)
			"vision_threshold":
				if val is int or val is float:
					var f_vt: float = float(val)
					result["vision_threshold"] = clampf(f_vt if is_finite(f_vt) else 0.5, 0.0, 1.0)
			"vision_feather":
				if val is int or val is float:
					var f_vf: float = float(val)
					result["vision_feather"] = clampf(f_vf if is_finite(f_vf) else 0.04, 0.0, 0.5)
			"shadow_filter":
				var sf_m: Dictionary = val_u.parse_int_val(val)
				if bool(sf_m["ok"]) and int(sf_m["value"]) in SHADOW_FILTERS:
					result["shadow_filter"] = int(sf_m["value"])
			"shadow_smooth":
				if val is int or val is float:
					var f_ss: float = float(val)
					result["shadow_smooth"] = clampf(f_ss if is_finite(f_ss) else 0.0, 0.0, 16.0)
	var eff_blob: PackedByteArray = exploration
	if eff_blob.is_empty() and overrides.has("exploration") and overrides["exploration"] is PackedByteArray:
		eff_blob = overrides["exploration"] as PackedByteArray
	if not eff_blob.is_empty() and is_valid_exploration_bytes(eff_blob):
		result["exploration"] = eff_blob.duplicate()
	return result


func configure_fog(
	overrides: Dictionary = {},
	exploration: PackedByteArray = PackedByteArray()
) -> Dictionary:
	var gate: Dictionary = _check_gate("configure_fog")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var cloned_res: Dictionary = _bounded_cloner().clone_fog_overrides(overrides, 0, [], [4096])
	if not bool(cloned_res.get("ok", false)):
		return {"ok": false, "reason": str(cloned_res.get("reason", "invalid_fog_config"))}
	var merged: Dictionary = cloned_res["value"] as Dictionary
	if not exploration.is_empty():
		merged["exploration"] = exploration.duplicate()
	var checked: Dictionary = validate_fog_config(merged, true)
	if not bool(checked.get("ok", false)):
		return checked
	var normalized: Dictionary = checked["data"] as Dictionary
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, normalized))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"config": normalized,
		"enabled": bool(gate.get("enabled", false)),
		"policy": str(gate.get("policy", "preserve")),
	}


func get_fog_config() -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {}
	if wb.has_method("get_module_state"):
		return wb.get_module_state(MODULE_ID)
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("get_module_state"):
		return adapter.get_module_state(wb.get_world(), MODULE_ID)
	return {}


func make_vision_state(
	radius: float = 640.0,
	view_angle_deg: float = 360.0,
	requires_light: bool = false,
	enabled: bool = true
) -> Dictionary:
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("make_simple_vision_state"):
		return adapter.make_simple_vision_state(radius, view_angle_deg, requires_light, enabled)
	return {
		"enabled": enabled,
		"requires_light": requires_light,
		"radius": maxf(0.0, float(radius) if is_finite(radius) else 640.0),
		"view_angle": clampf(float(view_angle_deg) if is_finite(view_angle_deg) else 360.0, 0.0, 360.0),
	}


func make_light_state(
	radius: float = 640.0,
	view_angle_deg: float = 360.0,
	enabled: bool = true
) -> Dictionary:
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("make_simple_light_state"):
		return adapter.make_simple_light_state(radius, view_angle_deg, enabled)
	return {
		"enabled": enabled,
		"requires_light": false,
		"radius": maxf(0.0, float(radius) if is_finite(radius) else 640.0),
		"view_angle": clampf(float(view_angle_deg) if is_finite(view_angle_deg) else 360.0, 0.0, 360.0),
	}


func validate_vision_state(state: Dictionary, entity: Dictionary = {}) -> Dictionary:
	var errors: Array[String] = []
	var allowed: Array[String] = ["enabled", "requires_light", "radius", "view_angle"]
	for raw_k: Variant in state.keys():
		if not (raw_k is String):
			errors.append("unknown_vision_key_type")
			continue
		var k_str: String = raw_k as String
		if not (k_str in allowed):
			errors.append("unknown_vision_key:" + k_str)
	if state.has("enabled") and not (state["enabled"] is bool):
		errors.append("invalid_enabled_type")
	if state.has("requires_light") and not (state["requires_light"] is bool):
		errors.append("invalid_requires_light_type")
	if state.has("radius"):
		var rv: Variant = state["radius"]
		if not (rv is float) or not is_finite(float(rv)) or float(rv) < 0.0:
			errors.append("invalid_radius")
	if state.has("view_angle"):
		var av: Variant = state["view_angle"]
		if not (av is float) or not is_finite(float(av)) or float(av) < 0.0 or float(av) > 360.0:
			errors.append("invalid_view_angle")
	if not entity.is_empty() and _has_scene_box(entity):
		errors.append("component_conflict_with_scene_box:simple_vision")
	return {"ok": errors.is_empty(), "errors": errors}


func validate_light_state(state: Dictionary, entity: Dictionary = {}) -> Dictionary:
	var res: Dictionary = validate_vision_state(state, {})
	var errors: Array[String] = res.get("errors", []) as Array[String]
	if not entity.is_empty() and _has_scene_box(entity):
		errors.append("component_conflict_with_scene_box:simple_light")
	return {"ok": errors.is_empty(), "errors": errors}


func attach_vision(
	entity_id: String,
	radius: float = 640.0,
	view_angle_deg: float = 360.0,
	requires_light: bool = false,
	enabled: bool = true,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_vision")
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
	if _has_scene_box(entity):
		_warn("实体已有 scene_box 组件，禁止同时挂载 simple_vision：" + entity_id)
		return {"ok": false, "reason": "component_conflict_with_scene_box:simple_vision"}

	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var state: Dictionary = make_vision_state(radius, view_angle_deg, requires_light, enabled)
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_SIMPLE_VISION_SCRIPT,
		state,
		effective_parked,
		effective_manual
	))
	if not ok:
		return {"ok": false, "reason": "attach_component_failed"}
	return {"ok": true, "entity_id": entity_id, "parked": effective_parked, "manual": effective_manual}


func attach_light(
	entity_id: String,
	radius: float = 640.0,
	view_angle_deg: float = 360.0,
	enabled: bool = true,
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_light")
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
	if _has_scene_box(entity):
		_warn("实体已有 scene_box 组件，禁止同时挂载 simple_light：" + entity_id)
		return {"ok": false, "reason": "component_conflict_with_scene_box:simple_light"}

	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var state: Dictionary = make_light_state(radius, view_angle_deg, enabled)
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_SIMPLE_LIGHT_SCRIPT,
		state,
		effective_parked,
		effective_manual
	))
	if not ok:
		return {"ok": false, "reason": "attach_component_failed"}
	return {"ok": true, "entity_id": entity_id, "parked": effective_parked, "manual": effective_manual}


func add_point_light(
	source_id: String,
	center_src: Vector2,
	radius_world: float,
	view_angle_deg: float = 360.0,
	name: String = "Light",
	hidden: bool = false,
	enabled: bool = true,
	size_src: Vector2 = Vector2(32.0, 32.0),
	layer_uid_override: String = "",
	parked: bool = false,
	manual: bool = false
) -> String:
	var gate: Dictionary = _check_gate("add_point_light")
	if not bool(gate.get("ok", true)):
		return ""
	if manual and not parked:
		_warn("simple_fog.add_point_light: manual=true 必须配合 parked=true 使用。")
		return ""
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	var final_name: String = name if not name.strip_edges().is_empty() else "Light"
	var entity_id: String = str(wb.add_object_sprite(
		source_id,
		final_name,
		center_src,
		size_src,
		"",
		0.0,
		Vector2.ONE,
		hidden,
		layer_uid_override,
		false
	))
	if entity_id.is_empty():
		return ""
	wb.suppress_entity_fallback_box(entity_id)
	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	var state: Dictionary = make_light_state(radius_world, view_angle_deg, enabled)
	wb.attach_component(
		entity_id,
		COMP_SIMPLE_LIGHT_SCRIPT,
		state,
		effective_parked,
		effective_manual
	)
	return entity_id


func _has_scene_box(entity: Dictionary) -> bool:
	var valid_u: Variant = _validation_utils()
	var comps_var: Variant = entity.get("components", [])
	if comps_var is Array:
		for raw_c: Variant in comps_var as Array:
			if raw_c is Dictionary:
				var scr: String = str((raw_c as Dictionary).get("script", ""))
				if str(valid_u.component_id_from_script(scr)) == "scene_box":
					return true
	return false


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
