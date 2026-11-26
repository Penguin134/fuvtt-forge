extends ExtensionBase
## 外置世界模块模板主入口（fus.plugin.v2 / .fup + content.pck）
##
## 覆盖能力：
## 1. 动态加载 fu_runtime/v2.gd（优先包内 lib/fu_runtime/v2.gd，开发态回退 shared/sdk/fu_runtime/v2.gd）；
## 2. CompBase 自定义组件注册（comp_template_world_plugin__marker.gd / .tscn + EntityComponentPage 撤销栈）；
## 3. WorldModuleState 三阶段持久化（prepare_module_state / apply_module_state / serialize_module_state）；
## 4. network.actions（3 个方法）与 network.projections（projection_changed 信号 + 8 个方法），严格满足 spec.id == MODULE_ID；
## 5. 全量槽位：world.overlays、ui.desktop_panels、ui.module_settings、ui.mode_bar（on_enter 返回 true）、ui.entity_actions；
## 6. 对 %WorldState、%Entities、%EditModeController、_net、component_sync 均做安全空检查，兼顾完整宿主与 verify-host 最小化探针。

signal markers_changed
signal settings_changed
signal projection_changed(peer: int)
signal projection_data_changed(peer: int)

const PLUGIN_ID := "template_world_plugin"
const MODULE_ID := "template_world_plugin.core"
const SERVICE_ID := "template_world_plugin.service"
const COMP_ID := "template_world_plugin__marker"

const COMP_PATH := "res://external_modules/template_world_plugin/comp_template_world_plugin__marker.gd"
const COMP_SCENE_PATH := "res://external_modules/template_world_plugin/comp_template_world_plugin__marker.tscn"
const SIDEBAR_SCENE_PATH := "res://external_modules/template_world_plugin/marker_sidebar_panel.tscn"
const SETTINGS_SCENE_PATH := "res://external_modules/template_world_plugin/marker_settings_page.tscn"
const OVERLAY_SCRIPT_PATH := "res://external_modules/template_world_plugin/marker_world_overlay.gd"

const _RUNTIME_PACKAGED_REL_PATH := "lib/fu_runtime/v2.gd"
const _RUNTIME_DEV_REL_PATH := "../../../../shared/sdk/fu_runtime/v2.gd"

const STATE_VERSION: int = 1
const WORLD_UNITS_PER_CELL: float = 64.0

var _runtime_sdk: RefCounted = null
var _logger: RefCounted = null
var _api_helper: RefCounted = null
var _hook_helper: RefCounted = null
var _slot_helper: RefCounted = null
var _comp_helper: RefCounted = null
var _network_helper: RefCounted = null

var _desktop: Node = null
var _world: Node = null
var _store: Node = null
var _editor: Node = null
var _net: Node = null
var _sync: Node = null

var _inspect_mode_active: bool = false
var _default_range_cells: int = 2
var _show_labels: bool = true
var _projection_rev: int = 1
var _replica_payload: Dictionary = {}
var _watched_tokens: Dictionary = {}


func _load_runtime_sdk() -> RefCounted:
	var self_scr := get_script() as Script
	var base_dir: String = ""
	if self_scr != null and not self_scr.resource_path.is_empty():
		base_dir = self_scr.resource_path.split("::")[0].get_base_dir()

	var candidates: Array[String] = []
	if not base_dir.is_empty():
		candidates.append(base_dir.path_join(_RUNTIME_PACKAGED_REL_PATH).simplify_path())
		candidates.append(base_dir.path_join(_RUNTIME_DEV_REL_PATH).simplify_path())
	candidates.append("res://shared/sdk/fu_runtime/v2.gd")
	candidates.append("shared/sdk/fu_runtime/v2.gd")

	for path: String in candidates:
		if ResourceLoader.exists(path) or FileAccess.file_exists(path):
			var loaded := load(path) as Script
			if loaded != null:
				var inst: Variant = loaded.new()
				if inst is RefCounted:
					return inst as RefCounted
	return null


func _on_register(context: ExtensionContext) -> void:
	set_meta(&"module_id", MODULE_ID)
	_runtime_sdk = _load_runtime_sdk()
	if _runtime_sdk == null:
		push_warning("[%s] Unable to load fu_runtime/v2.gd" % PLUGIN_ID)
		return

	_logger = _runtime_sdk.call(&"create_logger", {"emit_to_engine": true}) as RefCounted
	_api_helper = _runtime_sdk.call(&"create_desktop_api_helper", context, _logger) as RefCounted
	_hook_helper = _runtime_sdk.call(&"create_hook_helper", context, _logger) as RefCounted
	_slot_helper = _runtime_sdk.call(&"create_slot_helper", context, _logger) as RefCounted
	_comp_helper = _runtime_sdk.call(&"create_comp_helper", context, _logger) as RefCounted
	_network_helper = _runtime_sdk.call(&"create_network_helper", MODULE_ID, false, context, _logger) as RefCounted

	_desktop = _api_helper.call(&"get_desktop") as Node if _api_helper != null else null
	if not is_instance_valid(_desktop) and context.has_method(&"runtime_node"):
		var rt_node: Variant = context.call(&"runtime_node")
		if rt_node is Object and (rt_node as Object).has_method(&"get_desktop"):
			_desktop = (rt_node as Object).call(&"get_desktop") as Node

	if is_instance_valid(_desktop):
		_world = _desktop.get_node_or_null("%WorldState")
		_store = _desktop.get_node_or_null("%Entities")
		_editor = _desktop.get_node_or_null("%EditModeController")
		if _desktop.has_method(&"get_network_session"):
			_net = _desktop.call(&"get_network_session") as Node
	_sync = context.consume_service("component_sync") as Node

	# 1. 发布模块服务
	context.publish_service(SERVICE_ID, self)

	# 2. 注册可选实体组件（comp_<plugin_id>__<name>.gd）
	var comp_scene := load(COMP_SCENE_PATH) as PackedScene
	if _comp_helper != null and comp_scene != null:
		var comp_res: Dictionary = _comp_helper.call(&"register_component", COMP_ID, COMP_PATH, comp_scene, {
			"version": 1,
			"label": "战术标记",
			"description": "在实体周围绘制可联机同步、可主持暗藏的范围标记。",
			"network_scope": "shared",
			"library_visible": true,
			"entity_local_membership": true,
			"initial_ready_peer_local": true,
		}) as Dictionary
		if not bool(comp_res.get("ok", false)) and _logger != null:
			_logger.call(&"warn", PLUGIN_ID, "Component registration failed", comp_res)

	# 3. 注册联机 Actions 与 Projections（spec.id 必须严格等于 MODULE_ID）
	if _network_helper != null:
		var act_res: Dictionary = _network_helper.call(&"register_network_actions", self, MODULE_ID) as Dictionary
		if not bool(act_res.get("ok", false)) and _logger != null:
			_logger.call(&"warn", PLUGIN_ID, "network.actions registration failed", act_res)
		var proj_res: Dictionary = _network_helper.call(&"register_network_projections", self, MODULE_ID, {
			"replica_presentation_only": true,
			"initial_ready_peer_local": true,
			"projection_ignores_entity_flags": true,
		}) as Dictionary
		if not bool(proj_res.get("ok", false)) and _logger != null:
			_logger.call(&"warn", PLUGIN_ID, "network.projections registration failed", proj_res)

	# 4. 注册桌面侧栏、模块设置页、模式栏、实体动作与世界覆盖层
	if _slot_helper != null:
		var sidebar_scene := load(SIDEBAR_SCENE_PATH) as PackedScene
		if sidebar_scene != null:
			_slot_helper.call(&"register_desktop_panel", PLUGIN_ID + ".panel", "战术标记", sidebar_scene, self, {
				"priority": 18,
				"dm_only": false,
			})

		var settings_scene := load(SETTINGS_SCENE_PATH) as PackedScene
		if settings_scene != null:
			_slot_helper.call(&"register_module_settings", PLUGIN_ID + ".settings", "战术标记", settings_scene, self, {
				"priority": 18,
				"dm_only": false,
			})

		_slot_helper.call(
			&"register_mode_bar",
			PLUGIN_ID + ".inspect",
			"标记检视",
			Callable(self, &"_on_mode_enter"),
			Callable(self, &"_on_mode_exit"),
			Callable(self, &"_can_enter_inspect_mode"),
			{
				"tooltip": "高亮检视当前楼层所有战术标记范围",
				"priority": -40,
				"dm_only": false,
				"player_visible": true,
				"entity_editing": false,
			}
		)

		_slot_helper.call(
			&"register_entity_action",
			PLUGIN_ID + ".toggle",
			"战术标记",
			Callable(self, &"_execute_toggle_marker"),
			Callable(self, &"_can_toggle_marker"),
			{
				"tooltip": "为选中单位挂载或停放战术标记组件",
				"priority": 36,
				"dm_only": true,
				"surfaces": ["action_bar", "context_wheel"],
				"presentation": Callable(self, &"_toggle_marker_presentation"),
			}
		)

		_slot_helper.call(&"register_world_overlay", PLUGIN_ID + ".ground_marker", "below_entities", {
			"priority": 20,
			"factory": Callable(self, &"_create_world_overlay"),
		})

	# 5. 订阅内置 HookBus 事件（精确参数个数）与可选世界视图信号
	if _hook_helper != null:
		_hook_helper.call(&"subscribe", &"entity.spawned", Callable(self, &"_on_entity_spawned"))
		_hook_helper.call(&"subscribe", &"entity.removed", Callable(self, &"_on_entity_removed"))
		_hook_helper.call(&"subscribe", &"comp.added", Callable(self, &"_on_comp_changed"))
		_hook_helper.call(&"subscribe", &"comp.removed", Callable(self, &"_on_comp_changed"))
		_hook_helper.call(&"subscribe", &"comp.state_changed", Callable(self, &"_on_comp_changed"))
		_hook_helper.call(&"subscribe", &"floor.changed", Callable(self, &"_on_floor_changed"))

	if is_instance_valid(_world) and _world.has_signal(&"view_changed"):
		context.subscribe_signal(_world, &"view_changed", Callable(self, &"_notify_markers_dirty"))

	if is_instance_valid(_store):
		for child: Node in _store.get_children():
			if child is BoardToken:
				_watch_token(child as BoardToken)
	_notify_markers_dirty()


func _on_unregister() -> void:
	_inspect_mode_active = false
	_watched_tokens.clear()
	_replica_payload.clear()
	if _hook_helper != null:
		_hook_helper.call(&"unbind")
	if _slot_helper != null:
		_slot_helper.call(&"unbind")
	if _comp_helper != null:
		_comp_helper.call(&"unbind")
	if _network_helper != null:
		_network_helper.call(&"unbind")
	if _api_helper != null:
		_api_helper.call(&"unbind")
	_hook_helper = null
	_slot_helper = null
	_comp_helper = null
	_network_helper = null
	_api_helper = null
	_logger = null
	_runtime_sdk = null
	_desktop = null
	_world = null
	_store = null
	_editor = null
	_net = null
	_sync = null


func _create_world_overlay() -> Node2D:
	var scr := load(OVERLAY_SCRIPT_PATH) as Script
	if scr == null:
		return Node2D.new()
	var inst: Variant = scr.new()
	if inst is Node2D:
		return inst as Node2D
	if inst is Node:
		(inst as Node).free()
	return Node2D.new()


func _watch_token(token: BoardToken) -> void:
	if not is_instance_valid(token) or _watched_tokens.has(token):
		return
	_watched_tokens[token] = true
	if ctx != null and ctx.can_initialize():
		ctx.subscribe_signal(token, &"transform_changed", Callable(self, &"_notify_markers_dirty"))
		ctx.subscribe_signal(token, &"flags_changed", Callable(self, &"_notify_markers_dirty"))


func _on_entity_spawned(entity: Variant) -> void:
	if entity is BoardToken:
		_watch_token(entity as BoardToken)
	_notify_markers_dirty()


func _on_entity_removed(entity: Variant) -> void:
	_watched_tokens.erase(entity)
	_notify_markers_dirty()


func _on_comp_changed(_host: Variant, comp: Variant) -> void:
	if comp is CompBase and is_instance_valid(comp):
		if (comp as CompBase).get_comp_id() == COMP_ID:
			_notify_markers_dirty()


func _on_floor_changed(_payload: Variant) -> void:
	_notify_markers_dirty()


func _notify_markers_dirty() -> void:
	markers_changed.emit()


## ui.mode_bar 回调：on_enter 必须显式返回 bool(true)
func _can_enter_inspect_mode(_desk: Node) -> bool:
	return true


func _on_mode_enter(_desk: Node) -> bool:
	_inspect_mode_active = true
	_notify_markers_dirty()
	return true


func _on_mode_exit(_desk: Node) -> void:
	_inspect_mode_active = false
	_notify_markers_dirty()


func is_inspect_mode_active() -> bool:
	return _inspect_mode_active


func can_author_world() -> bool:
	if is_instance_valid(_desktop) and _desktop.has_method(&"can_author_world"):
		return bool(_desktop.call(&"can_author_world"))
	if _api_helper != null and bool(_api_helper.call(&"is_available")):
		return bool(_api_helper.call(&"is_gm"))
	return false


## ==================== 实体动作（挂/卸组件） ====================

func _can_toggle_marker(desk: Node, targets: Array) -> bool:
	if desk != _desktop or not can_author_world() or targets.is_empty():
		return false
	for raw_tok: Variant in targets:
		if not (raw_tok is BoardToken) or not is_instance_valid(raw_tok):
			return false
		var t := raw_tok as BoardToken
		if not t.is_unit() or t.entity_locked or t.has_component_record("scene_box"):
			return false
	return true


func _toggle_marker_presentation(_desk: Node, targets: Array) -> Dictionary:
	var all_have := not targets.is_empty()
	for raw_tok: Variant in targets:
		if not (raw_tok is BoardToken) or (raw_tok as BoardToken).get_component_by_id(COMP_ID) == null:
			all_have = false
			break
	return {"label": "收起战术标记" if all_have else "添加战术标记", "enabled": true}


func _execute_toggle_marker(desk: Node, targets: Array) -> bool:
	if not _can_toggle_marker(desk, targets) or not is_instance_valid(_editor):
		return false
	if not _editor.has_method(&"components_request"):
		return false
	var all_have := true
	var typed_targets: Array[BoardToken] = []
	for raw_tok: Variant in targets:
		var tok := raw_tok as BoardToken
		typed_targets.append(tok)
		if tok == null or tok.get_component_by_id(COMP_ID) == null:
			all_have = false
	return bool(_editor.call(&"components_request", typed_targets, COMP_PATH, &"park" if all_have else &"activate"))


## ==================== 场上标记采集 ====================

func collect_active_markers() -> Array[Dictionary]:
	var out: Array[Dictionary] = []
	if ctx == null or not ctx.is_active() or not is_instance_valid(_store) or not is_instance_valid(_world):
		return out
	var active_floor: int = int(_world.call(&"active_floor_id")) if _world.has_method(&"active_floor_id") else 0
	var is_dm: bool = can_author_world()
	var local_peer: int = 1 if is_dm else (_api_helper.call(&"local_peer_id") as int if _api_helper != null else 0)
	var cell_px: float = _api_helper.call(&"world_units_per_cell") as float if _api_helper != null else WORLD_UNITS_PER_CELL

	for child: Node in _store.get_children():
		if not (child is BoardToken):
			continue
		var token := child as BoardToken
		if int(token.get_meta(&"floor_id", -1)) != active_floor or token.entity_hidden or bool(token.get_meta(&"layer_hidden", false)):
			continue
		if not token.is_visible_in_tree():
			continue
		var comp: CompBase = token.get_component_by_id(COMP_ID)
		if comp == null or comp.ctx == null or not comp.ctx.is_active():
			continue
		if bool(comp.get(&"dm_secret")) and not is_dm:
			var perm: CompPermission = token.get_component_by_id("permission") as CompPermission
			if perm == null or not perm.can_command(local_peer):
				continue
		var cells: int = int(comp.get(&"range_cells"))
		var token_radius: float = maxf(token.visual_world_size().x, token.visual_world_size().y) * 0.5
		out.append({
			"entity_id": str(token.get_meta(&"net_id", "")),
			"unit_name": token.display_name,
			"title": str(comp.get(&"marker_title")),
			"cells": cells,
			"world_pos": token.global_position,
			"radius_world": token_radius + float(cells) * cell_px,
			"color": comp.get(&"marker_color"),
		})
	return out


## ==================== 模块持久状态（WorldModuleState 三阶段持久化） ====================

func _default_module_state() -> Dictionary:
	return {
		"version": STATE_VERSION,
		"default_range_cells": 2,
		"show_labels": true,
	}


func _validate_module_state(clean_state: Dictionary) -> Dictionary:
	var cells: Variant = clean_state.get("default_range_cells", 2)
	var show: Variant = clean_state.get("show_labels", true)
	if not (cells is int) or int(cells) < 1 or int(cells) > 24:
		return {"ok": false, "reason": "invalid_default_range_cells"}
	if not (show is bool):
		return {"ok": false, "reason": "invalid_show_labels"}
	return {
		"ok": true,
		"data": {
			"version": STATE_VERSION,
			"default_range_cells": int(cells),
			"show_labels": bool(show),
		},
	}


func get_module_settings() -> Dictionary:
	return {
		"default_range_cells": _default_range_cells,
		"show_labels": _show_labels,
	}


func set_module_setting(key: String, value: Variant) -> bool:
	if not can_author_world():
		push_warning("[%s] Non-GM client cannot modify world module setting: %s" % [PLUGIN_ID, key])
		return false
	var changed := false
	match key:
		"default_range_cells":
			var cells := clampi(int(value), 1, 24)
			if _default_range_cells != cells:
				_default_range_cells = cells
				changed = true
		"show_labels":
			var sl := bool(value)
			if _show_labels != sl:
				_show_labels = sl
				changed = true
		_:
			push_warning("[%s] Unknown module setting key: %s" % [PLUGIN_ID, key])
			return false
	if changed:
		_projection_rev += 1
		if is_instance_valid(_world) and _world.has_method(&"publish_module_state") and _world.has_method(&"module_state_revision"):
			_world.call(&"publish_module_state", _world.call(&"module_state_revision"))
		if is_instance_valid(_net):
			var players_var: Variant = _net.get(&"players")
			if players_var is Array or players_var is Dictionary:
				for peer: Variant in players_var:
					projection_data_changed.emit(int(peer))
		settings_changed.emit()
		_notify_markers_dirty()
	return true


func prepare_module_state(state: Dictionary) -> Dictionary:
	if _network_helper != null:
		return _network_helper.call(
			&"prepare_three_phase_state",
			state,
			STATE_VERSION,
			Callable(self, &"_validate_module_state"),
			_default_module_state(),
			MODULE_ID
		) as Dictionary
	if state.is_empty():
		return {"ok": true, "data": _default_module_state()}
	if int(state.get("version", 0)) != STATE_VERSION:
		return {"ok": false, "reason": "unsupported_module_state_version"}
	return _validate_module_state(state)


func serialize_module_state() -> Dictionary:
	var raw: Dictionary = {
		"version": STATE_VERSION,
		"default_range_cells": _default_range_cells,
		"show_labels": _show_labels,
	}
	if _network_helper != null:
		return _network_helper.call(&"clone_state_isolated", raw) as Dictionary
	return raw.duplicate(true)


func apply_module_state(state: Dictionary) -> bool:
	var prep: Dictionary = prepare_module_state(state)
	if not bool(prep.get("ok", false)):
		return false
	var d: Dictionary = prep.get("data", {}) as Dictionary
	_default_range_cells = clampi(int(d.get("default_range_cells", 2)), 1, 24)
	_show_labels = bool(d.get("show_labels", true))
	_projection_rev += 1
	settings_changed.emit()
	_notify_markers_dirty()
	return true


## ==================== 联机动作（network.actions）与状态投影（network.projections） ====================

func network_action_valid(payload: Variant) -> bool:
	if not (payload is Dictionary) or (payload as Dictionary).size() != 3:
		return false
	var p := payload as Dictionary
	if p.get("op") != "set_range":
		return false
	var eid: Variant = p.get("entity_id")
	var cells: Variant = p.get("range_cells")
	if not (eid is String) or (eid as String).is_empty() or (eid as String).length() > 128:
		return false
	return cells is int and int(cells) >= 1 and int(cells) <= 24


func network_action_revoked(peer: int, payload: Dictionary) -> String:
	if ctx == null or not ctx.is_active() or not network_action_valid(payload):
		return "marker_action_invalid"
	if peer != 1:
		if not is_instance_valid(_net) or not _net.has_method(&"is_admitted") or not bool(_net.call(&"is_admitted", peer)):
			return "marker_peer_not_admitted"
	var token: BoardToken = _find_entity(str(payload.get("entity_id", "")))
	if token == null or token.entity_locked or token.entity_hidden:
		return "marker_target_unavailable"
	if peer != 1:
		var perm: CompPermission = token.get_component_by_id("permission") as CompPermission
		if perm == null or not perm.can_command(peer):
			return "marker_permission_denied"
	return ""


func network_request(peer: int, payload: Dictionary) -> Dictionary:
	if not can_author_world() or not network_action_revoked(peer, payload).is_empty():
		return {"ok": false, "reason": "marker_request_rejected"}
	var token: BoardToken = _find_entity(str(payload.get("entity_id", "")))
	var comp: CompBase = token.get_component_by_id(COMP_ID) if token != null else null
	if comp == null or not is_instance_valid(_editor) or not _editor.has_method(&"configure_components"):
		return {"ok": false, "reason": "marker_component_missing"}
	var registration: ExtensionContext = ctx
	var guard := func() -> bool:
		return ctx == registration and registration.is_active() and network_action_revoked(peer, payload).is_empty()
	var author: String = "" if peer == 1 else (str(_net.call(&"get_peer_stable_id", peer)) if is_instance_valid(_net) and _net.has_method(&"get_peer_stable_id") else "")
	var prev_state: Dictionary = comp.serialize_state()
	var prev: Dictionary = {"presence": "live", "state": prev_state}
	var desired_state: Dictionary = prev_state.duplicate(true)
	desired_state["range_cells"] = int(payload["range_cells"])
	var desired: Dictionary = {"presence": "live", "state": desired_state}
	var targets_arr: Array[BoardToken] = [token]
	var expected_arr: Array[Dictionary] = [prev]
	var desired_arr: Array[Dictionary] = [desired]
	var ok: bool = bool(_editor.call(&"configure_components", targets_arr, COMP_PATH, expected_arr, desired_arr, guard, author, false))
	var hist_id: int = 0
	if ok and _editor.has_method(&"author_history"):
		var hist_var: Variant = _editor.call(&"author_history", false, author)
		if hist_var is Dictionary:
			hist_id = int((hist_var as Dictionary).get("id", 0))
	return {"ok": ok, "reason": "" if ok else "marker_configure_failed", "history": hist_id}


func _find_entity(entity_id: String) -> BoardToken:
	if is_instance_valid(_sync) and _sync.has_method(&"find_entity"):
		var found: Variant = _sync.call(&"find_entity", entity_id)
		if found is BoardToken and is_instance_valid(found):
			return found as BoardToken
	if _api_helper != null:
		var api_found: Object = _api_helper.call(&"find_entity", entity_id) as Object
		if api_found is BoardToken and is_instance_valid(api_found):
			return api_found as BoardToken
	if is_instance_valid(_store):
		for ch: Node in _store.get_children():
			if ch is BoardToken and str(ch.get_meta(&"net_id", "")) == entity_id:
				return ch as BoardToken
	return null


func network_projection(_peer: int, _confirmed: Dictionary, _reset: bool) -> Dictionary:
	return {
		"version": 1,
		"revision": _projection_rev,
		"settings": serialize_module_state(),
	}


func network_cursor(payload: Dictionary) -> Dictionary:
	return {
		"version": 1,
		"revision": int(payload.get("revision", 0)),
	}


func network_revoked(peer: int, cursor: Dictionary) -> bool:
	if ctx == null or not ctx.is_active() or not is_instance_valid(_net):
		return true
	if not _net.has_method(&"is_admitted") or not bool(_net.call(&"is_admitted", peer)):
		return true
	return int(cursor.get("revision", -1)) != _projection_rev


func validate_replica_projection(payload: Dictionary, _writer: ExtensionBase) -> Dictionary:
	var ok: bool = (
		payload is Dictionary
		and payload.size() == 3
		and payload.get("version") == 1
		and payload.get("revision") is int
		and payload.get("settings") is Dictionary
		and bool(prepare_module_state(payload["settings"] as Dictionary).get("ok", false))
	)
	return {"ok": ok, "data": payload.duplicate(true) if ok else {}}


func capture_replica_projection() -> Dictionary:
	return _replica_payload.duplicate(true)


func replica_projection_matches(expected: Dictionary) -> bool:
	return _replica_payload == expected


func replica_projection_unchanged(payload: Dictionary, checked: Dictionary) -> bool:
	return bool(checked.get("ok", false)) and checked.get("data") == payload and _replica_payload == payload


func _owns_projection(writer: ExtensionBase) -> bool:
	return (
		ctx != null
		and ctx.is_active()
		and is_instance_valid(_sync)
		and writer == _sync
		and writer.has_method(&"owns_module_projection_write")
		and bool(writer.call(&"owns_module_projection_write", self))
	)


func stage_replica_projection(payload: Dictionary, checked: Dictionary, writer: ExtensionBase) -> bool:
	if not _owns_projection(writer) or not bool(checked.get("ok", false)) or checked.get("data") != payload:
		return false
	_replica_payload = payload.duplicate(true)
	return true


func publish_replica_projection(writer: ExtensionBase) -> void:
	if _owns_projection(writer) and not _replica_payload.is_empty():
		var prep: Dictionary = prepare_module_state(_replica_payload["settings"] as Dictionary)
		if bool(prep.get("ok", false)):
			var cfg: Dictionary = prep["data"] as Dictionary
			_default_range_cells = clampi(int(cfg.get("default_range_cells", 2)), 1, 24)
			_show_labels = bool(cfg.get("show_labels", true))
			settings_changed.emit()
			_notify_markers_dirty()
			projection_changed.emit(0)


func restore_replica_projection(previous: Dictionary, writer: ExtensionBase) -> bool:
	if not _owns_projection(writer):
		return false
	if not previous.is_empty() and not bool(validate_replica_projection(previous, writer).get("ok", false)):
		return false
	_replica_payload = previous.duplicate(true)
	if previous.is_empty():
		_default_range_cells = 2
		_show_labels = true
	else:
		var prep: Dictionary = prepare_module_state(previous["settings"] as Dictionary)
		if bool(prep.get("ok", false)):
			var cfg: Dictionary = prep["data"] as Dictionary
			_default_range_cells = clampi(int(cfg.get("default_range_cells", 2)), 1, 24)
			_show_labels = bool(cfg.get("show_labels", true))
	settings_changed.emit()
	_notify_markers_dirty()
	projection_changed.emit(0)
	return true
