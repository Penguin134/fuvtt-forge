extends RefCounted
## Fu vtt Slot Registry & UI/Overlay Runtime Helper
##
## Provides spec builders, pre-registration validators, and ExtensionContext
## wrappers for `world.overlays`, `ui.desktop_panels`, `ui.module_settings`,
## `ui.mode_bar`, `ui.entity_actions`, `ui.canvas_actions`, `ui.entity_properties`,
## and `ExtensionContext.mount_node`.

const SLOT_WORLD_OVERLAYS: StringName = &"world.overlays"
const SLOT_DESKTOP_PANELS: StringName = &"ui.desktop_panels"
const SLOT_MODULE_SETTINGS: StringName = &"ui.module_settings"
const SLOT_MODE_BAR: StringName = &"ui.mode_bar"
const SLOT_ENTITY_ACTIONS: StringName = &"ui.entity_actions"
const SLOT_CANVAS_ACTIONS: StringName = &"ui.canvas_actions"
const SLOT_ENTITY_PROPERTIES: StringName = &"ui.entity_properties"

const OVERLAY_BANDS: Array[String] = ["below_entities", "above_entities", "above_fog"]
const ACTION_SURFACES: Array[String] = ["action_bar", "context_wheel"]
const BUILTIN_MODES: Array[String] = ["select", "edit", "build"]

const MAX_ACTION_LABEL_LENGTH: int = 80
const MAX_WHEEL_INDEX: int = 31
const MAX_CANVAS_WHEEL_SLOT: int = 7
const MAX_ENTITY_ACTION_ITEMS: int = 256

const FU_SDK_UTILS_REL: String = "../fu_sdk/utils/"
const DEV_FALLBACK_UTILS_DIR: String = "shared/sdk/fu_sdk/utils/"

var _ctx_ref: WeakRef = null
var _log_ref: WeakRef = null
var _runtime_ref: WeakRef = null
var _util_scripts: Dictionary = {}


func _init(context: Variant = null, log_bus: RefCounted = null, runtime: RefCounted = null) -> void:
	if log_bus != null and is_instance_valid(log_bus):
		_log_ref = weakref(log_bus)
	if runtime != null and is_instance_valid(runtime):
		_runtime_ref = weakref(runtime)
	if context != null:
		bind(context)


func _load_util_script(file_name: String) -> Variant:
	if _util_scripts.has(file_name):
		return _util_scripts[file_name]
	var rel_path: String = FU_SDK_UTILS_REL + file_name
	var self_scr := get_script() as Script
	if self_scr != null and not self_scr.resource_path.is_empty():
		var base_dir: String = self_scr.resource_path.split("::")[0].get_base_dir()
		var candidate: String = base_dir.path_join(rel_path).simplify_path()
		if ResourceLoader.exists(candidate) or FileAccess.file_exists(candidate):
			var loaded := load(candidate) as Script
			if loaded != null:
				_util_scripts[file_name] = loaded
				return loaded
	for raw_frame: Variant in get_stack():
		if raw_frame is Dictionary:
			var src_file: String = str((raw_frame as Dictionary).get("source", ""))
			if not src_file.is_empty():
				var stack_cand: String = src_file.get_base_dir().path_join(rel_path).simplify_path()
				if ResourceLoader.exists(stack_cand) or FileAccess.file_exists(stack_cand):
					var loaded_stack := load(stack_cand) as Script
					if loaded_stack != null:
						_util_scripts[file_name] = loaded_stack
						return loaded_stack
	for fb_path: String in [
		("res://" + DEV_FALLBACK_UTILS_DIR).path_join(file_name),
		DEV_FALLBACK_UTILS_DIR.path_join(file_name),
	]:
		if ResourceLoader.exists(fb_path) or FileAccess.file_exists(fb_path):
			var loaded_fb := load(fb_path) as Script
			if loaded_fb != null:
				_util_scripts[file_name] = loaded_fb
				return loaded_fb
	return null


func _value_utils() -> Variant:
	return _load_util_script("value_utils.gd")


func _validation_utils() -> Variant:
	return _load_util_script("validation_utils.gd")


func _clean_str(raw: Variant) -> String:
	var vu: Variant = _value_utils()
	var val_u: Variant = _validation_utils()
	var s: String = str(vu.as_str(raw, "")) if vu != null else (String(raw) if (raw is String or raw is StringName) else "")
	return str(val_u.strip_bom_and_edges(s)) if val_u != null else s.strip_edges()


func _vu_int(raw: Variant, fallback: int) -> int:
	var vu: Variant = _value_utils()
	return int(vu.coerce_int(raw, fallback)) if vu != null else fallback


func _vu_bool(raw: Variant, fallback: bool) -> bool:
	var vu: Variant = _value_utils()
	return bool(vu.coerce_bool(raw, fallback)) if vu != null else fallback


func _log_warn(message: String, context: Dictionary = {}) -> void:
	if _log_ref == null:
		return
	var bus: Variant = _log_ref.get_ref()
	if bus != null and is_instance_valid(bus) and bus.has_method(&"warn"):
		bus.call(&"warn", "fu_runtime.slots", message, context)


func _ctx() -> Object:
	if _ctx_ref == null:
		return null
	var obj: Variant = _ctx_ref.get_ref()
	if obj == null or not is_instance_valid(obj):
		return null
	return obj as Object


func bind(context: Variant) -> bool:
	unbind()
	if context == null or not (context is Object) or not is_instance_valid(context):
		return false
	var obj := context as Object
	if not obj.has_method(&"register_slot_item"):
		_log_warn("Rejected invalid ExtensionContext for slot_helper")
		return false
	_ctx_ref = weakref(obj)
	return true


func unbind() -> void:
	_ctx_ref = null


static func safe_mode_enter_result(accepted: Variant) -> bool:
	return typeof(accepted) == TYPE_BOOL and accepted == true


static func validate_panel_node(node: Variant, require_deactivate: bool = true) -> Dictionary:
	if node == null or not (node is Control) or not is_instance_valid(node):
		return {"ok": false, "reason": "panel_root_must_be_control"}
	var ctrl := node as Control
	if not ctrl.has_method(&"bind_provider"):
		return {"ok": false, "reason": "missing_bind_provider"}
	if require_deactivate and not ctrl.has_method(&"deactivate"):
		return {"ok": false, "reason": "missing_deactivate"}
	return {"ok": true}


func make_world_overlay_spec(id: String, band: String = "below_entities", options: Dictionary = {}) -> Dictionary:
	var clean_id: String = _clean_str(id)
	if clean_id.is_empty():
		return {"ok": false, "reason": "empty_overlay_id"}
	var clean_band: String = _clean_str(band)
	if clean_band.is_empty():
		clean_band = "below_entities"
	if not (clean_band in OVERLAY_BANDS):
		return {"ok": false, "reason": "invalid_overlay_band"}

	var scene_var: Variant = options.get("scene", null)
	if options.has("factory") and options["factory"] != null:
		if not (options["factory"] is Callable):
			return {"ok": false, "reason": "invalid_overlay_factory"}
		var fac_cb: Callable = options["factory"] as Callable
		if fac_cb != Callable() and not fac_cb.is_valid():
			return {"ok": false, "reason": "invalid_overlay_factory"}
	var factory_var: Variant = options.get("factory", Callable())
	var node_var: Variant = options.get("node", null)
	var has_scene: bool = scene_var is PackedScene and (scene_var as PackedScene).can_instantiate()
	var has_factory: bool = factory_var is Callable and (factory_var as Callable).is_valid()
	var has_node: bool = node_var is CanvasItem and is_instance_valid(node_var) and (node_var as Node).get_parent() == null

	if not has_scene and not has_factory and not has_node:
		return {"ok": false, "reason": "missing_overlay_source"}

	var spec: Dictionary = {
		"id": clean_id,
		"band": clean_band,
		"priority": _vu_int(options.get("priority", 0), 0),
	}
	if has_scene:
		spec["scene"] = scene_var
	elif has_factory:
		spec["factory"] = factory_var
	elif has_node:
		spec["node"] = node_var
	return {"ok": true, "spec": spec}


func make_desktop_panel_spec(
	id: String,
	label: String,
	scene: Variant,
	provider: Object,
	options: Dictionary = {}
) -> Dictionary:
	var clean_id: String = _clean_str(id)
	var clean_label: String = _clean_str(label)
	if clean_id.is_empty():
		return {"ok": false, "reason": "empty_panel_id"}
	if clean_label.is_empty():
		return {"ok": false, "reason": "empty_panel_label"}
	if not (scene is PackedScene) or not (scene as PackedScene).can_instantiate():
		return {"ok": false, "reason": "invalid_panel_scene"}
	if provider == null or not is_instance_valid(provider):
		return {"ok": false, "reason": "invalid_provider"}

	var spec: Dictionary = {
		"id": clean_id,
		"label": clean_label,
		"scene": scene,
		"provider": provider,
		"priority": _vu_int(options.get("priority", 0), 0),
		"dm_only": _vu_bool(options.get("dm_only", false), false),
	}
	if options.has("tab_scene") and options["tab_scene"] != null:
		var tab_scene: Variant = options["tab_scene"]
		if not (tab_scene is PackedScene) or not (tab_scene as PackedScene).can_instantiate():
			return {"ok": false, "reason": "invalid_tab_scene"}
		spec["tab_scene"] = tab_scene
	return {"ok": true, "spec": spec}


func make_module_settings_spec(
	id: String,
	label: String,
	scene: Variant,
	provider: Object,
	options: Dictionary = {}
) -> Dictionary:
	var clean_id: String = _clean_str(id)
	var clean_label: String = _clean_str(label)
	if clean_id.is_empty():
		return {"ok": false, "reason": "empty_settings_id"}
	if clean_label.is_empty():
		clean_label = clean_id
	if not (scene is PackedScene) or not (scene as PackedScene).can_instantiate():
		return {"ok": false, "reason": "invalid_settings_scene"}
	if provider == null or not is_instance_valid(provider):
		return {"ok": false, "reason": "invalid_provider"}

	var spec: Dictionary = {
		"id": clean_id,
		"label": clean_label,
		"scene": scene,
		"provider": provider,
		"priority": _vu_int(options.get("priority", 0), 0),
		"dm_only": _vu_bool(options.get("dm_only", false), false),
	}
	return {"ok": true, "spec": spec}


func make_mode_bar_spec(
	id: String,
	label: String,
	on_enter: Callable,
	on_exit: Callable,
	predicate: Callable,
	options: Dictionary = {}
) -> Dictionary:
	var clean_id: String = _clean_str(id)
	var clean_label: String = _clean_str(label)
	if clean_id.is_empty():
		return {"ok": false, "reason": "empty_mode_id"}
	if clean_id in BUILTIN_MODES:
		return {"ok": false, "reason": "builtin_mode_id_forbidden"}
	if not clean_id.contains("."):
		return {"ok": false, "reason": "mode_id_requires_dot_namespace"}
	if clean_label.is_empty():
		return {"ok": false, "reason": "empty_mode_label"}
	if not on_enter.is_valid() or not on_exit.is_valid() or not predicate.is_valid():
		return {"ok": false, "reason": "invalid_mode_callbacks"}

	var spec: Dictionary = {
		"id": clean_id,
		"label": clean_label,
		"on_enter": on_enter,
		"on_exit": on_exit,
		"predicate": predicate,
		"tooltip": _clean_str(options.get("tooltip", "")),
		"priority": _vu_int(options.get("priority", 0), 0),
		"dm_only": _vu_bool(options.get("dm_only", false), false),
		"player_visible": _vu_bool(options.get("player_visible", false), false),
		"entity_editing": _vu_bool(options.get("entity_editing", false), false),
		"show_layer_details": _vu_bool(options.get("show_layer_details", false), false),
		"active_module_layer": _clean_str(options.get("active_module_layer", "")),
	}
	if options.has("selection_filter") and options["selection_filter"] != null:
		if not (options["selection_filter"] is Callable):
			return {"ok": false, "reason": "invalid_selection_filter"}
		var sf: Callable = options["selection_filter"] as Callable
		if sf != Callable():
			if not sf.is_valid():
				return {"ok": false, "reason": "invalid_selection_filter"}
			spec["selection_filter"] = sf
	if options.has("pick_boundary") and options["pick_boundary"] != null:
		if not (options["pick_boundary"] is Callable):
			return {"ok": false, "reason": "invalid_pick_boundary"}
		var pb: Callable = options["pick_boundary"] as Callable
		if pb != Callable():
			if not pb.is_valid():
				return {"ok": false, "reason": "invalid_pick_boundary"}
			spec["pick_boundary"] = pb
	return {"ok": true, "spec": spec}


func make_entity_action_spec(
	id: String,
	label: String,
	execute: Callable,
	predicate: Callable,
	options: Dictionary = {}
) -> Dictionary:
	var clean_id: String = _clean_str(id)
	var clean_label: String = _clean_str(label)
	if clean_id.is_empty() or not clean_id.contains("."):
		return {"ok": false, "reason": "action_id_requires_dot_namespace"}
	if clean_label.is_empty() or clean_label.length() > MAX_ACTION_LABEL_LENGTH:
		return {"ok": false, "reason": "invalid_action_label"}
	if not execute.is_valid() or not predicate.is_valid():
		return {"ok": false, "reason": "invalid_action_callbacks"}

	var surfaces: Array[String] = []
	if options.has("surfaces"):
		var raw_surfaces: Variant = options["surfaces"]
		if not (raw_surfaces is Array) or (raw_surfaces as Array).is_empty():
			return {"ok": false, "reason": "invalid_surfaces"}
		for item: Variant in raw_surfaces as Array:
			var s: String = _clean_str(item)
			if not (s in ACTION_SURFACES):
				return {"ok": false, "reason": "unsupported_surface"}
			if not (s in surfaces):
				surfaces.append(s)
	else:
		surfaces = ["action_bar", "context_wheel"]

	var wheel_ring: int = _vu_int(options.get("wheel_ring", 2), 2)
	var wheel_slot: int = _vu_int(options.get("wheel_slot", 0), 0)
	if wheel_ring < 0 or wheel_ring > MAX_WHEEL_INDEX:
		return {"ok": false, "reason": "wheel_ring_out_of_range"}
	if wheel_slot < 0 or wheel_slot > MAX_WHEEL_INDEX:
		return {"ok": false, "reason": "wheel_slot_out_of_range"}

	var spec: Dictionary = {
		"id": clean_id,
		"label": clean_label,
		"execute": execute,
		"predicate": predicate,
		"tooltip": _clean_str(options.get("tooltip", "")),
		"priority": _vu_int(options.get("priority", 0), 0),
		"dm_only": _vu_bool(options.get("dm_only", true), true),
		"surfaces": surfaces,
		"wheel_ring": wheel_ring,
		"wheel_slot": wheel_slot,
		"danger": _vu_bool(options.get("danger", false), false),
		"present_during_drag": _vu_bool(options.get("present_during_drag", false), false),
	}
	if options.has("shortcut_key"):
		var sc: int = _vu_int(options["shortcut_key"], -1)
		if sc < KEY_SPACE or sc > KEY_Z:
			return {"ok": false, "reason": "shortcut_key_out_of_range"}
		spec["shortcut_key"] = sc
	if options.has("presentation") and options["presentation"] != null:
		if not (options["presentation"] is Callable):
			return {"ok": false, "reason": "invalid_presentation_callback"}
		var pres: Callable = options["presentation"] as Callable
		if pres != Callable():
			if not pres.is_valid():
				return {"ok": false, "reason": "invalid_presentation_callback"}
			spec["presentation"] = pres
	if options.has("target_matches") and options["target_matches"] != null:
		if not (options["target_matches"] is Callable):
			return {"ok": false, "reason": "invalid_target_matches_callback"}
		var tm: Callable = options["target_matches"] as Callable
		if tm != Callable():
			if not tm.is_valid():
				return {"ok": false, "reason": "invalid_target_matches_callback"}
			spec["target_matches"] = tm
	return {"ok": true, "spec": spec}


func make_canvas_action_spec(
	id: String,
	label: String,
	execute: Callable,
	predicate: Callable,
	options: Dictionary = {}
) -> Dictionary:
	var clean_id: String = _clean_str(id)
	var clean_label: String = _clean_str(label)
	if clean_id.is_empty() or not clean_id.contains("."):
		return {"ok": false, "reason": "action_id_requires_dot_namespace"}
	if clean_label.is_empty() or clean_label.length() > MAX_ACTION_LABEL_LENGTH:
		return {"ok": false, "reason": "invalid_action_label"}
	if not execute.is_valid() or not predicate.is_valid():
		return {"ok": false, "reason": "invalid_action_callbacks"}
	var wheel_ring: int = _vu_int(options.get("wheel_ring", 1), 1)
	var wheel_slot: int = _vu_int(options.get("wheel_slot", 0), 0)
	if wheel_ring != 1 and wheel_ring != 2:
		return {"ok": false, "reason": "canvas_wheel_ring_out_of_range"}
	if wheel_slot < 0 or wheel_slot > MAX_CANVAS_WHEEL_SLOT:
		return {"ok": false, "reason": "canvas_wheel_slot_out_of_range"}
	var spec: Dictionary = {
		"id": clean_id,
		"label": clean_label,
		"execute": execute,
		"predicate": predicate,
		"tooltip": _clean_str(options.get("tooltip", "")),
		"priority": _vu_int(options.get("priority", 0), 0),
		"wheel_ring": wheel_ring,
		"wheel_slot": wheel_slot,
	}
	return {"ok": true, "spec": spec}


func make_entity_properties_spec(
	id: String,
	scene: Variant,
	provider: Object,
	options: Dictionary = {}
) -> Dictionary:
	var clean_id: String = _clean_str(id)
	if clean_id.is_empty():
		return {"ok": false, "reason": "empty_entity_properties_id"}
	if not (scene is PackedScene) or not (scene as PackedScene).can_instantiate():
		return {"ok": false, "reason": "invalid_entity_properties_scene"}
	if provider == null or not is_instance_valid(provider):
		return {"ok": false, "reason": "invalid_provider"}
	return {
		"ok": true,
		"spec": {
			"id": clean_id,
			"label": _clean_str(options.get("label", clean_id)),
			"scene": scene,
			"provider": provider,
			"priority": _vu_int(options.get("priority", 0), 0),
		},
	}


func _register_built_spec(slot_id: StringName, built: Dictionary) -> Dictionary:
	if not bool(built.get("ok", false)):
		return built
	var ctx: Object = _ctx()
	if ctx == null:
		return {"ok": false, "reason": "context_unavailable"}
	var spec: Dictionary = built["spec"] as Dictionary
	var token: Variant = ctx.call(&"register_slot_item", slot_id, spec)
	if token is Object and is_instance_valid(token):
		var tok_obj := token as Object
		if tok_obj.has_method(&"is_active") and not bool(tok_obj.call(&"is_active")):
			var reason: String = "slot_registration_rejected"
			var last_rej: Variant = tok_obj.get(&"last_rejection")
			if last_rej is String and not (last_rej as String).is_empty():
				reason = last_rej as String
			else:
				var lbl: Variant = tok_obj.get(&"label")
				if lbl is String and not (lbl as String).is_empty():
					reason = lbl as String
			return {"ok": false, "reason": reason, "token": tok_obj}
		return {"ok": true, "token": tok_obj}
	return {"ok": false, "reason": "slot_registration_failed"}


func register_world_overlay(id: String, band: String = "below_entities", options: Dictionary = {}) -> Dictionary:
	return _register_built_spec(SLOT_WORLD_OVERLAYS, make_world_overlay_spec(id, band, options))


func register_desktop_panel(
	id: String,
	label: String,
	scene: Variant,
	provider: Object,
	options: Dictionary = {}
) -> Dictionary:
	return _register_built_spec(SLOT_DESKTOP_PANELS, make_desktop_panel_spec(id, label, scene, provider, options))


func register_module_settings(
	id: String,
	label: String,
	scene: Variant,
	provider: Object,
	options: Dictionary = {}
) -> Dictionary:
	return _register_built_spec(SLOT_MODULE_SETTINGS, make_module_settings_spec(id, label, scene, provider, options))


func register_mode_bar(
	id: String,
	label: String,
	on_enter: Callable,
	on_exit: Callable,
	predicate: Callable,
	options: Dictionary = {}
) -> Dictionary:
	return _register_built_spec(SLOT_MODE_BAR, make_mode_bar_spec(id, label, on_enter, on_exit, predicate, options))


func register_entity_action(
	id: String,
	label: String,
	execute: Callable,
	predicate: Callable,
	options: Dictionary = {}
) -> Dictionary:
	return _register_built_spec(SLOT_ENTITY_ACTIONS, make_entity_action_spec(id, label, execute, predicate, options))


func register_canvas_action(
	id: String,
	label: String,
	execute: Callable,
	predicate: Callable,
	options: Dictionary = {}
) -> Dictionary:
	return _register_built_spec(SLOT_CANVAS_ACTIONS, make_canvas_action_spec(id, label, execute, predicate, options))


func register_entity_properties(
	id: String,
	scene: Variant,
	provider: Object,
	options: Dictionary = {}
) -> Dictionary:
	return _register_built_spec(SLOT_ENTITY_PROPERTIES, make_entity_properties_spec(id, scene, provider, options))


func mount_node(parent: Node, child: Node, index: int = -1) -> Dictionary:
	var ctx: Object = _ctx()
	if ctx == null or not ctx.has_method(&"mount_node"):
		return {"ok": false, "reason": "context_unavailable"}
	if parent == null or not is_instance_valid(parent):
		return {"ok": false, "reason": "invalid_parent_node"}
	if child == null or not is_instance_valid(child):
		return {"ok": false, "reason": "invalid_child_node"}
	if child.get_parent() != null:
		return {"ok": false, "reason": "child_already_parented"}
	var token: Variant = ctx.call(&"mount_node", parent, child, index)
	if token is Object and is_instance_valid(token):
		var tok_obj := token as Object
		if tok_obj.has_method(&"is_active") and not bool(tok_obj.call(&"is_active")):
			var reason: String = "mount_node_rejected"
			var last_rej: Variant = tok_obj.get(&"last_rejection")
			if last_rej is String and not (last_rej as String).is_empty():
				reason = last_rej as String
			else:
				var lbl: Variant = tok_obj.get(&"label")
				if lbl is String and not (lbl as String).is_empty():
					reason = lbl as String
			return {"ok": false, "reason": reason, "token": tok_obj}
		return {"ok": true, "token": tok_obj}
	return {"ok": false, "reason": "mount_node_failed"}
