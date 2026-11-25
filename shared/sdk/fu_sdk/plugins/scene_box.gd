extends RefCounted
## Fu vtt 原生可选插件 SDK：scene_box（多场景仓库 SceneRepository v2 与场景盒子组件 comp_scene_box）
##
## 对应官方源码：modules/scene_box/feature_scene_box.gd、comp_scene_box.gd、
## scenes/systems/world/scene_repository.gd、scenes/entities/board_token.gd。

const MODULE_ID: String = "scene_box"
const MODULE_VERSION: int = 1
const SCHEMA_VERSION: int = 2
const MAX_SCENES: int = 64
const MAX_VIEWERS: int = 128
const MAX_VIEWER_KEY_LENGTH: int = 128
const MAX_NAME_LENGTH: int = 96

const COMP_SCENE_BOX_SCRIPT: String = "res://modules/scene_box/comp_scene_box.gd"
const COMP_SCENE_BOX_CANDIDATE_SCRIPT: String = "res://scenes/candidates/scene_box/comp_scene_box.gd"
const COMP_SCHEMA_VERSION: int = 1

const PREVIEW_POLICIES: Array[String] = ["visited_unlock", "always_public", "cover_only"]
const ENTER_POLICIES: Array[String] = ["players_allowed", "host_only"]
const DEFAULT_SIDE_WORLD: float = 96.0
const MIN_SIDE_WORLD: float = 72.0
const MAX_SIDE_WORLD: float = 256.0
const DEFAULT_FLOOR_COLOR: Color = Color(0.32, 0.56, 0.44)

const SCENE_BOX_CONFLICTS: Array[String] = [
	"unit",
	"obstacle",
	"area",
	"image_flip",
	"portal",
	"character_roster_member",
	"initiative",
	"resource_pool",
	"backpack",
	"drag_speed",
	"follow",
	"simple_vision",
	"simple_light",
	"entity_ink",
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


func configure_entry_scene(
	scene_name: String = "主场景",
	initial_floor_name: String = "",
	cover_asset: String = ""
) -> String:
	var gate: Dictionary = _check_gate("configure_entry_scene")
	if not bool(gate.get("ok", true)):
		return ""
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	return str(wb.configure_entry_scene(scene_name, initial_floor_name, cover_asset))


func add_scene(
	scene_name: String,
	initial_floor_name: String = "1F",
	floor_color: Color = DEFAULT_FLOOR_COLOR,
	cover_asset: String = "",
	make_active: bool = true
) -> String:
	var gate: Dictionary = _check_gate("add_scene")
	if not bool(gate.get("ok", true)):
		return ""
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	return str(wb.add_scene(scene_name, initial_floor_name, floor_color, cover_asset, make_active))


func add_floor_to_scene(
	scene_uid: String,
	floor_name: String,
	color: Color = Color(0.28, 0.65, 0.40),
	make_default: bool = false,
	make_active: bool = false
) -> String:
	var gate: Dictionary = _check_gate("add_floor_to_scene")
	if not bool(gate.get("ok", true)):
		return ""
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	return str(wb.add_floor_to_scene(scene_uid, floor_name, color, make_default, make_active))


func move_floor_to_scene(
	floor_uid: String,
	target_scene_uid: String,
	make_default: bool = false
) -> bool:
	var gate: Dictionary = _check_gate("move_floor_to_scene")
	if not bool(gate.get("ok", true)):
		return false
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return false
	return bool(wb.move_floor_to_scene(floor_uid, target_scene_uid, make_default))


func set_active_scene(
	scene_uid: String,
	floor_uid: String = "",
	mark_host_visited: bool = true
) -> bool:
	var gate: Dictionary = _check_gate("set_active_scene")
	if not bool(gate.get("ok", true)):
		return false
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return false
	return bool(wb.set_active_scene(scene_uid, floor_uid, mark_host_visited))


func set_entry_scene(scene_uid: String) -> bool:
	var gate: Dictionary = _check_gate("set_entry_scene")
	if not bool(gate.get("ok", true)):
		return false
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return false
	return bool(wb.set_entry_scene(scene_uid))


func rename_scene(scene_uid: String, new_name: String) -> bool:
	var gate: Dictionary = _check_gate("rename_scene")
	if not bool(gate.get("ok", true)):
		return false
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return false
	return bool(wb.rename_scene(scene_uid, new_name))


func set_scene_default_floor(scene_uid: String, floor_uid: String) -> bool:
	var gate: Dictionary = _check_gate("set_scene_default_floor")
	if not bool(gate.get("ok", true)):
		return false
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return false
	return bool(wb.set_scene_default_floor(scene_uid, floor_uid))


func set_scene_cover_asset(scene_uid: String, cover_asset: String) -> bool:
	var gate: Dictionary = _check_gate("set_scene_cover_asset")
	if not bool(gate.get("ok", true)):
		return false
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return false
	return bool(wb.set_scene_cover_asset(scene_uid, cover_asset))


func set_scene_host_view(
	scene_uid: String,
	camera_pos_src: Vector2,
	camera_zoom: Vector2 = Vector2.ONE,
	active_floor_uid: String = ""
) -> bool:
	var gate: Dictionary = _check_gate("set_scene_host_view")
	if not bool(gate.get("ok", true)):
		return false
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return false
	return bool(wb.set_scene_host_view(scene_uid, camera_pos_src, camera_zoom, active_floor_uid))


func has_scenes_configured() -> bool:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return false
	return bool(wb.has_scenes_configured())


func get_scene_uids() -> Array[String]:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return []
	return wb.get_scene_uids()


func get_entry_scene_uid() -> String:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	return str(wb.get_entry_scene_uid())


func get_active_scene_uid() -> String:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	return str(wb.get_active_scene_uid())


func get_scene_floors(scene_uid: String = "") -> Array[String]:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return []
	return wb.get_scene_floor_uids(scene_uid)


func get_scene_floor_uids(scene_uid: String = "") -> Array[String]:
	return get_scene_floors(scene_uid)


func get_scene_default_floor_uid(scene_uid: String = "") -> String:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	return str(wb.get_scene_default_floor_uid(scene_uid))


func get_scene_for_floor(floor_uid: String = "") -> String:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	return str(wb.get_scene_for_floor(floor_uid))


func get_scene_record(scene_uid: String) -> Dictionary:
	var adapter: RefCounted = _get_adapter()
	var wb: RefCounted = _wb()
	if adapter == null or wb == null:
		return {}
	return adapter.get_scene_record(wb.get_world(), scene_uid)


func get_world_state() -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {}
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("get_module_state"):
		return adapter.get_module_state(wb.get_world(), MODULE_ID)
	return {}


func make_scene_box_state(
	target_scene_uid: String,
	preview_policy: String = "visited_unlock",
	enter_policy: String = "players_allowed",
	cover_asset: String = "",
	seed_from_visual: bool = false
) -> Dictionary:
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("make_scene_box_state"):
		var built: Dictionary = adapter.make_scene_box_state(
			target_scene_uid,
			preview_policy,
			enter_policy,
			cover_asset
		)
		if bool(built.get("ok", false)) and built.get("state", null) is Dictionary:
			(built["state"] as Dictionary)["seed_from_visual"] = seed_from_visual
		return built
	var clean_target: String = target_scene_uid.strip_edges().to_lower()
	if not clean_target.is_empty() and not bool(_validation_utils().is_valid_uid(clean_target)):
		return {"ok": false, "reason": "invalid_target_scene_uid"}
	var norm_preview: String = preview_policy.strip_edges()
	if not (norm_preview in PREVIEW_POLICIES):
		norm_preview = "visited_unlock"
	var norm_enter: String = enter_policy.strip_edges()
	if not (norm_enter in ENTER_POLICIES):
		norm_enter = "players_allowed"
	var clean_cover: String = cover_asset.strip_edges()
	var cover_sanitized: bool = false
	if not clean_cover.is_empty() and not _is_valid_cover_asset(clean_cover):
		clean_cover = ""
		cover_sanitized = true
	return {
		"ok": true,
		"cover_asset": clean_cover,
		"cover_sanitized": cover_sanitized,
		"state": {
			"schema_version": COMP_SCHEMA_VERSION,
			"target_scene_uid": clean_target,
			"preview_policy": norm_preview,
			"enter_policy": norm_enter,
			"cover_asset": clean_cover,
			"seed_from_visual": seed_from_visual,
		},
	}


func add_scene_box(
	source_id: String,
	name: String,
	center_src: Vector2,
	target_scene_uid: String,
	side_cells: float = 1.5,
	cover_asset: String = "",
	preview_policy: String = "visited_unlock",
	all_players_can_enter: bool = true,
	owner_player_ids: Array = [],
	hidden_from_players: bool = false,
	locked: bool = false,
	layer_uid_override: String = "",
	parked: bool = false,
	manual: bool = false
) -> String:
	var gate: Dictionary = _check_gate("add_scene_box")
	if not bool(gate.get("ok", true)):
		return ""
	if manual and not parked:
		_warn("scene_box.add_scene_box: manual=true 必须配合 parked=true 使用。")
		return ""
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return ""
	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	if wb.has_method("_add_scene_box_impl"):
		return str(wb._add_scene_box_impl(
			source_id,
			name,
			center_src,
			target_scene_uid,
			side_cells,
			cover_asset,
			preview_policy,
			all_players_can_enter,
			owner_player_ids,
			hidden_from_players,
			locked,
			layer_uid_override,
			effective_parked,
			effective_manual
		))
	return str(wb.add_scene_box(
		source_id,
		name,
		center_src,
		target_scene_uid,
		side_cells,
		cover_asset,
		preview_policy,
		all_players_can_enter,
		owner_player_ids,
		hidden_from_players,
		locked,
		layer_uid_override,
		effective_parked,
		effective_manual
	))


func attach_scene_box(
	entity_id: String,
	target_scene_uid: String,
	cover_asset: String = "",
	preview_policy: String = "visited_unlock",
	all_players_can_enter: bool = true,
	owner_player_ids: Array = [],
	parked: bool = false,
	manual: bool = false
) -> bool:
	var gate: Dictionary = _check_gate("attach_scene_box")
	if not bool(gate.get("ok", true)):
		return false
	if manual and not parked:
		_warn("scene_box.attach_scene_box: manual=true 必须配合 parked=true 使用。")
		return false
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return false
	var effective_parked: bool = parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = manual if (parked and manual) else false
	if wb.has_method("_attach_scene_box_impl"):
		return bool(wb._attach_scene_box_impl(
			entity_id,
			target_scene_uid,
			cover_asset,
			preview_policy,
			all_players_can_enter,
			owner_player_ids,
			effective_parked,
			effective_manual
		))
	return bool(wb.attach_scene_box(
		entity_id,
		target_scene_uid,
		cover_asset,
		preview_policy,
		all_players_can_enter,
		owner_player_ids,
		effective_parked,
		effective_manual
	))


func validate_comp_scene_box_state(state: Dictionary, entity: Dictionary = {}) -> Dictionary:
	var errors: Array[String] = []
	var allowed_keys: Array[String] = [
		"schema_version",
		"target_scene_uid",
		"preview_policy",
		"enter_policy",
		"cover_asset",
		"seed_from_visual",
	]
	for raw_k: Variant in state.keys():
		if not (raw_k is String) or not (str(raw_k) in allowed_keys):
			errors.append("unknown_scene_box_key:" + str(raw_k))

	var sv: Variant = state.get("schema_version", 1)
	if not (sv is int) or int(sv) != COMP_SCHEMA_VERSION:
		errors.append("invalid_schema_version")

	var valid_u: Variant = _validation_utils()
	var target_v: Variant = state.get("target_scene_uid", "")
	if not (target_v is String):
		errors.append("invalid_target_scene_uid_type")
	else:
		var t: String = str(target_v)
		if not t.is_empty() and not bool(valid_u.is_valid_uid(t)):
			errors.append("invalid_target_scene_uid")

	var prev_v: Variant = state.get("preview_policy", "visited_unlock")
	if not (prev_v is String) or not (str(prev_v) in PREVIEW_POLICIES):
		errors.append("invalid_preview_policy")

	var ent_v: Variant = state.get("enter_policy", "players_allowed")
	if not (ent_v is String) or not (str(ent_v) in ENTER_POLICIES):
		errors.append("invalid_enter_policy")

	var cov_v: Variant = state.get("cover_asset", "")
	if not (cov_v is String):
		errors.append("invalid_cover_asset_type")
	else:
		var c: String = str(cov_v)
		if not c.is_empty() and not _is_valid_cover_asset(c):
			errors.append("invalid_cover_asset")

	var seed_v: Variant = state.get("seed_from_visual", false)
	if not (seed_v is bool):
		errors.append("invalid_seed_from_visual")

	if not entity.is_empty():
		if str(entity.get("entity_type", "")) == "map":
			errors.append("scene_box_disallowed_on_map")
		elif str(entity.get("entity_type", "")) == "unit" or bool(entity.get("selectable_in_select_mode", false)):
			errors.append("component_conflict_with_scene_box:unit")
		var comps_var: Variant = entity.get("components", [])
		if comps_var is Array:
			for raw_c: Variant in comps_var as Array:
				if raw_c is Dictionary:
					var scr: String = str((raw_c as Dictionary).get("script", ""))
					var cid: String = str(valid_u.component_id_from_script(scr))
					if cid in SCENE_BOX_CONFLICTS:
						errors.append("component_conflict_with_scene_box:" + cid)

	return {"ok": errors.is_empty(), "errors": errors}


func validate_scene_repository(world: Dictionary = {}) -> Dictionary:
	var target_world: Dictionary = world
	var wb: RefCounted = _wb()
	if target_world.is_empty() and wb != null:
		target_world = wb.get_world()
	if target_world.is_empty():
		return {"ok": false, "errors": ["world_empty"]}

	var mods_var: Variant = target_world.get("modules", null)
	if not (mods_var is Dictionary):
		return {"ok": false, "errors": ["missing_modules"]}
	var entries_var: Variant = (mods_var as Dictionary).get("entries", null)
	if not (entries_var is Dictionary):
		return {"ok": false, "errors": ["missing_module_entries"]}
	var sb_entry_var: Variant = (entries_var as Dictionary).get(MODULE_ID, null)
	if not (sb_entry_var is Dictionary):
		return {"ok": false, "errors": ["missing_scene_box_entry"]}
	var sb_entry: Dictionary = sb_entry_var as Dictionary
	var errors: Array[String] = []
	if not (sb_entry.get("version", null) is int) or int(sb_entry.get("version", -1)) != MODULE_VERSION:
		errors.append("invalid_module_entry_version")
	var st_var: Variant = sb_entry.get("state", null)
	if not (st_var is Dictionary):
		errors.append("invalid_scene_box_state_type")
		return {"ok": false, "errors": errors}
	var st: Dictionary = st_var as Dictionary
	if st.is_empty():
		return {"ok": errors.is_empty(), "errors": errors, "empty": true}

	if not (st.get("schema_version", null) is int) or int(st.get("schema_version", -1)) != SCHEMA_VERSION:
		errors.append("invalid_schema_version")

	var valid_u: Variant = _validation_utils()
	var world_floors: Dictionary = {}
	var cat_var: Variant = target_world.get("catalog", null)
	if cat_var is Dictionary and (cat_var as Dictionary).get("floors", null) is Array:
		for raw_fl: Variant in (cat_var as Dictionary)["floors"] as Array:
			if raw_fl is Dictionary:
				var fuid: String = str((raw_fl as Dictionary).get("floor_uid", ""))
				if bool(valid_u.is_valid_uid(fuid)):
					world_floors[fuid] = true

	var scenes_var: Variant = st.get("scenes", null)
	var scene_uids: Dictionary = {}
	var claimed_floors: Dictionary = {}
	if not (scenes_var is Array) or (scenes_var as Array).is_empty() or (scenes_var as Array).size() > MAX_SCENES:
		errors.append("invalid_scenes_list")
	else:
		for raw_s: Variant in scenes_var as Array:
			if not (raw_s is Dictionary):
				errors.append("invalid_scene_row")
				continue
			var srow: Dictionary = raw_s as Dictionary
			var suid: String = str(srow.get("uid", "")) if srow.get("uid", null) is String else ""
			if not bool(valid_u.is_valid_uid(suid)) or scene_uids.has(suid):
				errors.append("invalid_or_duplicate_scene_uid:" + suid)
			else:
				scene_uids[suid] = srow
			var sname: Variant = srow.get("name", null)
			if not (sname is String) or not _is_valid_name(sname as String):
				errors.append("invalid_scene_name:" + suid)
			var sfloors_var: Variant = srow.get("floor_uids", null)
			var local_floors: Dictionary = {}
			if not (sfloors_var is Array) or (sfloors_var as Array).is_empty():
				errors.append("empty_scene_floors:" + suid)
			else:
				for raw_fu: Variant in sfloors_var as Array:
					var fu: String = str(raw_fu) if raw_fu is String else ""
					if not bool(valid_u.is_valid_uid(fu)) or claimed_floors.has(fu) or (not world_floors.is_empty() and not world_floors.has(fu)):
						errors.append("duplicate_or_invalid_scene_floor:" + fu)
					else:
						claimed_floors[fu] = suid
						local_floors[fu] = true
			if srow.has("default_floor_uid"):
				var def_f: Variant = srow.get("default_floor_uid")
				if not (def_f is String) or not local_floors.has(str(def_f)):
					errors.append("invalid_scene_default_floor:" + suid)
			if srow.has("cover_asset"):
				var cov: Variant = srow.get("cover_asset")
				if not (cov is String) or (not str(cov).is_empty() and not _is_valid_cover_asset(str(cov))):
					errors.append("invalid_scene_cover_asset:" + suid)

	if not world_floors.is_empty() and claimed_floors.size() != world_floors.size():
		errors.append("scene_floors_partition_mismatch")

	var entry_uid: String = str(st.get("entry_scene_uid", "")) if st.get("entry_scene_uid", null) is String else ""
	if not bool(valid_u.is_valid_uid(entry_uid)) or not scene_uids.has(entry_uid):
		errors.append("entry_scene_not_in_list")
	if st.has("host_active_scene_uid"):
		var active_uid: Variant = st.get("host_active_scene_uid")
		if not (active_uid is String) or (not str(active_uid).is_empty() and not scene_uids.has(str(active_uid))):
			errors.append("invalid_host_active_scene_uid")

	if st.has("visited_scenes"):
		var vis_var: Variant = st.get("visited_scenes")
		if not (vis_var is Dictionary) or (vis_var as Dictionary).size() > MAX_VIEWERS:
			errors.append("invalid_visited_scenes")
		else:
			var vis: Dictionary = vis_var as Dictionary
			for raw_vk: Variant in vis.keys():
				if not (raw_vk is String):
					errors.append("invalid_viewer_key_type")
					continue
				var vk: String = str(raw_vk)
				if vk.strip_edges().is_empty() or vk.length() > MAX_VIEWER_KEY_LENGTH or bool(valid_u.has_control_chars(vk, true)):
					errors.append("invalid_viewer_key:" + vk)
				var vlist: Variant = vis[raw_vk]
				if not (vlist is Array) or (vlist as Array).size() > MAX_SCENES:
					errors.append("invalid_viewer_scene_list:" + vk)
				else:
					for raw_vs: Variant in vlist as Array:
						if not (raw_vs is String) or not scene_uids.has(str(raw_vs)):
							errors.append("unknown_visited_scene:" + str(raw_vs))

	if st.has("host_return_stack"):
		var hrs: Variant = st.get("host_return_stack")
		if not (hrs is Array) or (hrs as Array).size() > MAX_SCENES:
			errors.append("invalid_host_return_stack")
		else:
			for raw_rs: Variant in hrs as Array:
				if not (raw_rs is String) or not scene_uids.has(str(raw_rs)):
					errors.append("unknown_return_stack_scene:" + str(raw_rs))

	if st.has("host_views"):
		var hv_var: Variant = st.get("host_views")
		if not (hv_var is Dictionary) or (hv_var as Dictionary).size() > MAX_SCENES:
			errors.append("invalid_host_views")
		else:
			var hv: Dictionary = hv_var as Dictionary
			for raw_hk: Variant in hv.keys():
				if not (raw_hk is String) or not scene_uids.has(str(raw_hk)):
					errors.append("unknown_host_view_scene:" + str(raw_hk))
					continue
				var view_var: Variant = hv[raw_hk]
				if not (view_var is Dictionary):
					errors.append("invalid_host_view_row:" + str(raw_hk))
					continue
				var view_d: Dictionary = view_var as Dictionary
				if view_d.has("camera_pos"):
					var cp: Variant = view_d["camera_pos"]
					if not (cp is Vector2) or not (cp as Vector2).is_finite():
						errors.append("invalid_host_view_camera_pos:" + str(raw_hk))
				if view_d.has("camera_zoom"):
					var cz: Variant = view_d["camera_zoom"]
					if not (cz is Vector2) or not (cz as Vector2).is_finite() or (cz as Vector2).x <= 0.0 or (cz as Vector2).y <= 0.0:
						errors.append("invalid_host_view_camera_zoom:" + str(raw_hk))
				if view_d.has("active_floor_uid"):
					var af: Variant = view_d["active_floor_uid"]
					var sdict: Dictionary = scene_uids[str(raw_hk)] as Dictionary
					var sfl_var: Variant = sdict.get("floor_uids", [])
					var sfl: Array = sfl_var as Array if sfl_var is Array else []
					if not (af is String) or not (str(af) in sfl):
						errors.append("invalid_host_view_floor:" + str(raw_hk))

	return {"ok": errors.is_empty(), "errors": errors}


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


func _is_valid_cover_asset(asset_ref: String) -> bool:
	if not asset_ref.begins_with("asset://"):
		return false
	var rest: String = asset_ref.substr(8)
	var dot_idx: int = rest.find(".")
	if dot_idx != 64:
		return false
	var digest: String = rest.substr(0, 64)
	if not bool(_validation_utils().is_valid_hex64(digest, false)):
		return false
	var ext: String = rest.substr(65)
	return ext in ["png", "jpg", "jpeg", "webp", "bmp"]


func _is_valid_name(name: String) -> bool:
	var trimmed: String = name.strip_edges()
	if trimmed.is_empty() or trimmed.length() > MAX_NAME_LENGTH or trimmed != name:
		return false
	return not bool(_validation_utils().has_control_chars(name, true))
