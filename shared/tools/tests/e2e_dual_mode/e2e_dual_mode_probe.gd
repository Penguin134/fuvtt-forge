extends SceneTree

## Fu vtt Opaque-Box E2E Batch Probe for Dual-Mode SDK (`fu_runtime` + `fu_sdk`),
## `fus.desktop-module.v1` (.zip), and `fus.plugin.v2` (content.pck).

class MockDesktopApi:
	extends RefCounted

	var _desktop: Node
	var _gm: bool = true
	var _peer_id: int = 1
	var _player_id: String = "host"
	var _mode: String = ""
	var _cam_pos: Vector2 = Vector2.ZERO
	var _cam_zoom: Vector2 = Vector2.ONE
	var _entities: Array = []
	var _selected: Array = []
	var _saved_module_entries: Dictionary = {}
	var _vitals_by_id: Dictionary = {}
	var _commandable_ids: Dictionary = {}
	var _rolls: Array = []
	var _mode_change_cb: Callable = Callable()

	func _init(desktop_node: Node) -> void:
		_desktop = desktop_node

	func get_desktop() -> Node:
		return _desktop

	func is_gm() -> bool:
		return _gm

	func network_role() -> String:
		return "host" if _gm else "client"

	func local_peer_id() -> int:
		return _peer_id

	func local_player_id() -> String:
		return _player_id

	func joined_players() -> Array[Dictionary]:
		return [{"peer_id": 1, "name": "GM"}, {"peer_id": 2, "name": "Player2"}]

	func can_command_entity(entity_or_id: Variant, peer: int = 0) -> bool:
		var tok: Variant = null
		if entity_or_id is String or entity_or_id is StringName:
			tok = find_entity(String(entity_or_id))
		elif entity_or_id is Node and is_instance_valid(entity_or_id):
			tok = entity_or_id
		if tok == null:
			return false
		var eid := _entity_id(tok)
		if eid.is_empty():
			return false
		var effective_peer: int = peer if peer > 0 else _peer_id
		if effective_peer == 1 and _gm:
			return true
		var allowed: Variant = _commandable_ids.get(eid, false)
		if allowed is Array:
			return effective_peer in (allowed as Array)
		if allowed is Dictionary:
			return bool((allowed as Dictionary).get(effective_peer, false))
		return bool(allowed)

	func active_scene_uid() -> String:
		return "scene_main_uid"

	func active_scene_name() -> String:
		return "Main Tavern"

	func active_floor_uid() -> String:
		return "floor_1f_uid"

	func active_floor_id() -> int:
		return 0

	func world_units_per_cell() -> float:
		return 64.0

	func screen_to_world(screen_pos: Vector2) -> Vector2:
		return (screen_pos / maxf(0.01, _cam_zoom.x)) + _cam_pos

	func world_to_screen(world_pos: Vector2) -> Vector2:
		return (world_pos - _cam_pos) * _cam_zoom

	func camera_position() -> Vector2:
		return _cam_pos

	func camera_zoom() -> Vector2:
		return _cam_zoom

	func focus_camera(world_pos: Vector2) -> bool:
		if not is_finite(world_pos.x) or not is_finite(world_pos.y):
			return false
		_cam_pos = world_pos
		return true

	func focus_entity(entity: Variant) -> bool:
		if entity is String or entity is StringName:
			var found: Variant = find_entity(String(entity))
			if found is Node2D:
				return focus_camera((found as Node2D).global_position)
			return false
		if entity is Node2D:
			return focus_camera((entity as Node2D).global_position)
		return false

	func current_mode() -> String:
		return _mode

	func set_mode(new_mode: String) -> bool:
		if _mode_change_cb.is_valid():
			var ok: bool = bool(_mode_change_cb.call(_mode, new_mode))
			if not ok:
				return false
		_mode = new_mode
		return true

	func find_entity(entity_id: String) -> Variant:
		for e: Variant in _entities:
			if _entity_id(e) == entity_id:
				return e
		return null

	func get_entities(_active_floor_only: bool = true) -> Array:
		return _entities.duplicate()

	func selected_entities() -> Array:
		return _selected.duplicate()

	func read_entity_vitals(entity: Variant) -> Dictionary:
		var eid := _entity_id(entity)
		var base: Dictionary = _vitals_by_id.get(eid, {"name": eid, "source_kind": "stat_bubble", "hp_cur": 20, "hp_max": 20, "ac": 16, "shield": 0, "hp_locked": false})
		var hp_locked := bool(base.get("hp_locked", false))
		if not _gm and not can_command_entity(entity) and hp_locked:
			return {"ok": true, "masked": true, "entity_id": eid, "name": String(base.get("name", eid)), "source_kind": String(base.get("source_kind", "stat_bubble"))}
		var out := base.duplicate(true)
		out["ok"] = true
		out["masked"] = false
		out["entity_id"] = eid
		return out

	func request_roll(expr: String, label: String = "", visibility: String = "public") -> Dictionary:
		if expr.strip_edges().is_empty():
			return {"ok": false, "reason": "empty_expr"}
		var rec := {"ok": true, "request_id": "roll_%d" % (_rolls.size() + 1), "expr": expr, "label": label, "visibility": visibility, "total": 20}
		_rolls.append(rec)
		return rec

	func read_saved_module_entry(module_id: String) -> Dictionary:
		if not _gm:
			return {}
		return (_saved_module_entries.get(module_id, {}) as Dictionary).duplicate(true)

	func _entity_id(entity: Variant) -> String:
		if entity is String or entity is StringName:
			return String(entity)
		if entity is Node:
			return String((entity as Node).get_meta(&"net_id", (entity as Node).name))
		return ""


class MockHostRuntime:
	extends Node

	var _desktop: Node
	var _services: Dictionary = {}
	var _hooks: Dictionary = {}
	var _publishing: bool = false
	var _slots: Dictionary = {
		&"world.overlays": [],
		&"network.actions": [],
		&"network.projections": [],
		&"ui.desktop_panels": [],
		&"ui.module_settings": [],
		&"ui.mode_bar": [],
		&"ui.entity_actions": [],
	}
	var _components: Dictionary = {}
	var _rejected_items: Array[String] = []
	var _mounted_overlay_nodes: Array[Node] = []
	var _applying_projection: bool = false
	var _projection_write_owner: Variant = null

	func _init(desktop_node: Node) -> void:
		_desktop = desktop_node

	func get_desktop() -> Node:
		return _desktop

	func configuration_is_publishing() -> bool:
		return _publishing

	func publish_service(service_id: String, provider: Variant) -> void:
		_services[service_id] = provider

	func consume_service(service_id: String) -> Variant:
		return _services.get(service_id, null)

	func begin_projection_write(owner: Variant) -> void:
		_applying_projection = true
		_projection_write_owner = owner

	func end_projection_write() -> void:
		_applying_projection = false
		_projection_write_owner = null

	func owns_module_projection_write(module_node: Variant) -> bool:
		return _applying_projection and module_node != null and _projection_write_owner == module_node

	func register_component(spec: Dictionary, _ctx: ExtensionContext) -> Dictionary:
		var cid := String(spec.get("id", ""))
		var path := String(spec.get("path", ""))
		if cid.is_empty() or cid in ["visual", "permission"]:
			return {"ok": false, "reason": "component_descriptor_invalid"}
		if not path.get_file().begins_with("comp_"):
			return {"ok": false, "reason": "component_descriptor_invalid"}
		var ns := String(spec.get("network_scope", "private"))
		if ns not in ["private", "shared", "peer"]:
			return {"ok": false, "reason": "component_descriptor_invalid"}
		if bool(spec.get("entity_local_content", false)) and ns != "peer":
			return {"ok": false, "reason": "component_descriptor_invalid"}
		_components[cid] = spec
		return {"ok": true, "id": cid}

	func register_slot_item(slot_id: StringName, spec: Dictionary, _ctx: ExtensionContext) -> Dictionary:
		if slot_id == &"world.overlays":
			var band := String(spec.get("band", ""))
			if band not in ["below_entities", "above_entities", "above_fog"]:
				_rejected_items.append(String(spec.get("id", "unknown")))
				var bad_node: Variant = spec.get("node", null)
				if bad_node is Node and is_instance_valid(bad_node):
					(bad_node as Node).free()
				return {"ok": false, "reason": "invalid_overlay_band"}
			var node: Node = null
			if spec.has("node") and spec["node"] is Node:
				node = spec["node"] as Node
			elif spec.has("factory") and (spec["factory"] as Callable).is_valid():
				node = (spec["factory"] as Callable).call() as Node
			elif spec.has("scene") and spec["scene"] is PackedScene:
				node = (spec["scene"] as PackedScene).instantiate()
			if node == null:
				return {"ok": false, "reason": "overlay_node_missing"}
			if node.has_method(&"bind_provider") and spec.has("provider"):
				var bound: Variant = node.call(&"bind_provider", spec["provider"])
				if bound != true:
					_rejected_items.append(String(spec.get("id", "")))
					node.free()
					return {"ok": false, "reason": "bind_provider_rejected"}
			var band_map := {
				"below_entities": "World/WorldOverlayBelowEntities",
				"above_entities": "World/WorldOverlayAboveEntities",
				"above_fog": "WorldOverlayAboveFogLayer/WorldOverlayAboveFog",
			}
			var target := _desktop.get_node_or_null(String(band_map[band]))
			if target != null:
				target.add_child(node)
				_mounted_overlay_nodes.append(node)
				# Sort ascending by priority
				var arr: Array = _slots[slot_id] as Array
				arr.append(spec)
				arr.sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return int(a.get("priority", 0)) < int(b.get("priority", 0)))
				_reorder_band(target, arr, band)
			return {"ok": true}

		if slot_id in [&"ui.desktop_panels", &"ui.module_settings", &"ui.mode_bar", &"ui.entity_actions"]:
			if slot_id in [&"ui.desktop_panels", &"ui.module_settings"]:
				var ps := spec.get("scene", null) as PackedScene
				if ps != null:
					var inst := ps.instantiate()
					if inst.has_method(&"bind_provider"):
						if inst.call(&"bind_provider", spec.get("provider", null)) != true:
							inst.free()
							_rejected_items.append(String(spec.get("id", "")))
							return {"ok": false, "reason": "bind_provider_rejected"}
					inst.free()
			if slot_id in [&"ui.mode_bar", &"ui.entity_actions"]:
				var sid := String(spec.get("id", ""))
				if not sid.contains("."):
					_rejected_items.append(sid)
					return {"ok": false, "reason": "id_missing_dot"}
			if not _slots.has(slot_id):
				_slots[slot_id] = []
			(_slots[slot_id] as Array).append(spec)
			# Descending priority sort for UI slots
			(_slots[slot_id] as Array).sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return int(a.get("priority", 0)) > int(b.get("priority", 0)))
			return {"ok": true}

		if not _slots.has(slot_id):
			_slots[slot_id] = []
		(_slots[slot_id] as Array).append(spec)
		return {"ok": true}

	func _reorder_band(target: Node, specs: Array, band: String) -> void:
		var order_idx := 0
		for sp: Dictionary in specs:
			if String(sp.get("band", "")) != band:
				continue
			var n: Variant = sp.get("node", null)
			if n is Node and (n as Node).get_parent() == target:
				target.move_child(n as Node, order_idx)
				order_idx += 1

	func subscribe_hook(hook_id: StringName, callback: Callable, priority: int, owner_ctx: ExtensionContext) -> Dictionary:
		if not HookIds.is_registered(hook_id):
			return {"ok": false, "reason": "hook_unknown:" + String(hook_id)}
		if not _hooks.has(hook_id):
			_hooks[hook_id] = []
		(_hooks[hook_id] as Array).append({"cb": callback, "priority": priority, "ctx": weakref(owner_ctx)})
		(_hooks[hook_id] as Array).sort_custom(func(a: Dictionary, b: Dictionary) -> bool: return int(a["priority"]) > int(b["priority"]))
		return {"ok": true, "hook": String(hook_id)}

	func unsubscribe_context(owner_ctx: ExtensionContext) -> void:
		for hk: Variant in _hooks.keys():
			var kept: Array = []
			for row: Dictionary in (_hooks[hk] as Array):
				var cref := row["ctx"] as WeakRef
				if cref != null and cref.get_ref() == owner_ctx:
					continue
				kept.append(row)
			_hooks[hk] = kept

	func emit_hook(hook_id: StringName, args: Array = []) -> bool:
		if _publishing:
			return false
		if not HookIds.is_registered(hook_id):
			return false
		var expected := HookIds.expected_arity(hook_id)
		if expected >= 0 and args.size() != expected:
			return false
		var cancellable := HookIds.is_cancellable(hook_id)
		var rows: Array = (_hooks.get(hook_id, []) as Array).duplicate()
		for row: Dictionary in rows:
			var cref := row["ctx"] as WeakRef
			var cobj := cref.get_ref() as ExtensionContext if cref != null else null
			if cobj == null or not cobj.is_active():
				continue
			var cb := row["cb"] as Callable
			if not cb.is_valid():
				continue
			var res: Variant = cb.callv(args)
			if cancellable and res is bool and res == false:
				return false
		return true

	func cleanup_all() -> void:
		for n: Node in _mounted_overlay_nodes:
			if is_instance_valid(n):
				if n.has_method(&"deactivate"):
					n.call(&"deactivate")
				if n.get_parent() != null:
					n.get_parent().remove_child(n)
				n.free()
		_mounted_overlay_nodes.clear()
		_services.clear()
		_hooks.clear()
		_components.clear()
		_applying_projection = false
		_projection_write_owner = null


class MockV1ImportHost:
	extends RefCounted

	var root: String = ""
	var cache: String = ""
	var destination: String = ""
	var file: String = ""
	var settings: Dictionary = {}
	var expected_sha256: String = ""
	var progress_log: Array[String] = []
	var warnings: Array[String] = []

	func cancelled() -> bool:
		return false

	func report(text: String) -> void:
		progress_log.append(text)

	func warn(text: String) -> void:
		warnings.append(text)

	func empty_world() -> Dictionary:
		var floor_uid: String = "fus.floor.mock.1f".sha256_text().left(32)
		var entity_uid: String = ("fus.layer.default.v1:" + floor_uid).sha256_text().left(32)
		var map_uid: String = ("fus.layer.map:" + floor_uid).sha256_text().left(32)
		var obstacle_uid: String = ("fus.layer.obstacle:" + floor_uid).sha256_text().left(32)
		return {
			"ok": true,
			"data": {
				"format": "fus.practice.world",
				"version": 3,
				"catalog": {
					"floor_identity_version": 1,
					"floors": [
						{
							"id": 0,
							"floor_uid": floor_uid,
							"name": "1F",
							"color": Color(0.28, 0.65, 0.40),
						},
					],
					"layers": {
						"schema": "fus.floor_layers.v2",
						"floors": [
							{
								"floor_uid": floor_uid,
								"default_layer_uid": entity_uid,
								"layers": [
									{
										"layer_uid": map_uid,
										"name": "地图底图",
										"kind": "map",
										"visible": true,
										"locked": false,
										"persistent": true,
										"access": "all",
										"viewers": [],
									},
									{
										"layer_uid": entity_uid,
										"name": "实体",
										"kind": "entity",
										"visible": true,
										"locked": false,
										"persistent": true,
										"access": "all",
										"viewers": [],
									},
									{
										"layer_uid": obstacle_uid,
										"name": "障碍物",
										"kind": "obstacle",
										"visible": true,
										"locked": false,
										"persistent": true,
										"access": "host",
										"viewers": [],
									},
								],
							},
						],
					},
					"active_floor_uid": floor_uid,
				},
				"entity_state": {
					"version": 3,
					"entities": [],
				},
				"members": [],
				"modules": {
					"version": 2,
					"entries": {},
				},
			},
		}

	func archive_image(url: String, _proxy: String = "") -> Dictionary:
		if url.is_empty():
			return {"ok": false, "reason": "empty_url", "reference": ""}
		return {"ok": true, "reference": "asset://mock_%s.png" % url.sha256_text().left(16), "size": Vector2(256.0, 256.0), "bytes": 1024}

	func begin_preview(_total: int, _bounds: Rect2) -> void:
		pass

	func preview_entity(_entity: Dictionary, _kind: String) -> void:
		pass

	func finish_geometry_preview() -> bool:
		return true


func _initialize() -> void:
	call_deferred(&"_run")


func _run() -> void:
	var args := _parse_args(OS.get_cmdline_user_args())
	var batch_in_path := String(args.get("batch-in", "")).strip_edges()
	var batch_out_path := String(args.get("batch-out", "")).strip_edges()

	var summary: Dictionary = {
		"ok": false,
		"loaded_scripts": [],
		"compile_failures": [],
		"completed_case_ids": [],
		"error": "",
	}
	if batch_in_path.is_empty() or batch_out_path.is_empty():
		summary["error"] = "missing_cli_args"
		_write_json_file(batch_out_path, summary)
		quit(2)
		return

	var batch_in_var: Variant = JSON.parse_string(FileAccess.get_file_as_string(batch_in_path))
	if not (batch_in_var is Dictionary):
		summary["error"] = "batch_in_invalid_json"
		_write_json_file(batch_out_path, summary)
		quit(3)
		return

	var batch_in := batch_in_var as Dictionary
	var out_dir := String(batch_in.get("out_dir", "")).strip_edges()
	var cases_var: Variant = batch_in.get("cases", [])
	DirAccess.make_dir_recursive_absolute(out_dir)

	var completed: Array[String] = []
	for raw_case: Variant in (cases_var as Array):
		if not (raw_case is Dictionary):
			continue
		var case_cfg := raw_case as Dictionary
		var cid := String(case_cfg.get("case_id", "unknown"))
		print("=== E2E_CASE_START %s ===" % cid)
		var out_payload: Dictionary = await _execute_case(case_cfg)
		_write_json_file(out_dir.path_join(cid + ".json"), _to_json_safe(out_payload))
		completed.append(cid)
		print("=== E2E_CASE_END %s ===" % cid)

	summary["completed_case_ids"] = completed
	summary["ok"] = true
	_write_json_file(batch_out_path, summary)
	quit(0)


func _execute_case(case_cfg: Dictionary) -> Dictionary:
	var cid := String(case_cfg.get("case_id", "unknown"))
	var op := String(case_cfg.get("op", ""))
	var pack_path := String(case_cfg.get("pack_path", "")).strip_edges()
	var sdk_root := String(case_cfg.get("sdk_root", "")).strip_edges()
	if sdk_root.is_empty():
		sdk_root = "res://sdk_stage/fu_runtime/v2.gd"
	var params: Dictionary = _decode_special(case_cfg.get("params", {})) as Dictionary if case_cfg.get("params") is Dictionary else {}
	var gd_failures: Array[String] = []
	var data: Dictionary = {}
	var ok := false

	if not pack_path.is_empty():
		var mounted := ProjectSettings.load_resource_pack(pack_path, false)
		data["pack_mounted"] = mounted
		if not mounted:
			gd_failures.append("failed_to_mount_pack:" + pack_path)

	match op:
		"fu_runtime_load_and_reuse":
			ok = _op_fu_runtime_load_and_reuse(sdk_root, params, data, gd_failures)
		"fu_runtime_leak_check":
			ok = _op_fu_runtime_leak_check(sdk_root, params, data, gd_failures)
		"desktop_api_contract":
			ok = _op_desktop_api_contract(sdk_root, params, data, gd_failures)
		"hook_bus_contract":
			ok = _op_hook_bus_contract(sdk_root, params, data, gd_failures)
		"overlay_and_mount_contract":
			ok = await _op_overlay_and_mount_contract(sdk_root, params, data, gd_failures)
		"desktop_module_mount_run":
			ok = await _op_desktop_module_mount_run(params, data, gd_failures)
		"world_plugin_comp_and_disclosure":
			ok = _op_world_plugin_comp_and_disclosure(params, data, gd_failures)
		"world_plugin_page_and_undo":
			ok = _op_world_plugin_page_and_undo(params, data, gd_failures)
		"world_module_state_3phase":
			ok = _op_world_module_state_3phase(sdk_root, params, data, gd_failures)
		"network_actions_projections":
			ok = await _op_network_actions_projections(sdk_root, params, data, gd_failures)
		"ui_slots_contract":
			ok = await _op_ui_slots_contract(sdk_root, params, data, gd_failures)
		"mount_and_compile_only":
			ok = _op_mount_and_compile_only(params, data, gd_failures)
		"fu_runtime_network_local_only_guard":
			ok = await _op_fu_runtime_network_local_only_guard(sdk_root, data, gd_failures)
		"fu_runtime_comp_helper_contract":
			ok = await _op_fu_runtime_comp_helper_contract(sdk_root, data, gd_failures)
		"fu_runtime_comp_edit_payloads":
			ok = _op_fu_runtime_comp_edit_payloads(sdk_root, data, gd_failures)
		"fu_runtime_slot_helper_ui_4_slots":
			ok = await _op_fu_runtime_slot_helper_ui_4_slots(sdk_root, data, gd_failures)
		"mode_bar_hook_bus_integration":
			ok = await _op_mode_bar_hook_bus_integration(sdk_root, data, gd_failures)
		"v1_to_desktop_saved_entry_bridge":
			ok = _op_v1_to_desktop_saved_entry_bridge(sdk_root, params, data, gd_failures)
		_:
			gd_failures.append("unknown_op:" + op)

	return {
		"case_id": cid,
		"ok": ok and gd_failures.is_empty(),
		"data": data,
		"gd_check_failures": gd_failures,
	}


func _build_mock_desktop_tree() -> Dictionary:
	var desktop := Node2D.new()
	desktop.name = "MockDesktop"
	var world := Node2D.new()
	world.name = "World"
	var below := Node2D.new()
	below.name = "WorldOverlayBelowEntities"
	below.z_index = -10
	var above := Node2D.new()
	above.name = "WorldOverlayAboveEntities"
	above.z_index = 20
	world.add_child(below)
	world.add_child(above)
	desktop.add_child(world)
	var fog_layer := CanvasLayer.new()
	fog_layer.name = "WorldOverlayAboveFogLayer"
	fog_layer.layer = 22
	var above_fog := Control.new()
	above_fog.name = "WorldOverlayAboveFog"
	fog_layer.add_child(above_fog)
	desktop.add_child(fog_layer)

	var rt := MockHostRuntime.new(desktop)
	rt.name = "ExtensionRuntime"
	desktop.add_child(rt)
	var api := MockDesktopApi.new(desktop)
	rt.publish_service("desktop_api", api)
	rt.publish_service("component_sync", rt)
	root.add_child(desktop)
	return {"desktop": desktop, "world": world, "rt": rt, "api": api}


func _free_mock_desktop_tree(env: Dictionary) -> void:
	var rt := env["rt"] as MockHostRuntime
	rt.cleanup_all()
	var desktop := env["desktop"] as Node
	if is_instance_valid(desktop):
		if desktop.get_parent() != null:
			desktop.get_parent().remove_child(desktop)
		desktop.free()


func _load_v2_sdk(sdk_root: String, gd_failures: Array[String]) -> RefCounted:
	if not (ResourceLoader.exists(sdk_root) or FileAccess.file_exists(sdk_root)):
		gd_failures.append("fu_runtime_v2_missing:" + sdk_root)
		return null
	var scr := load(sdk_root) as Script
	if scr == null or not scr.can_instantiate():
		gd_failures.append("fu_runtime_v2_uninstantiable:" + sdk_root)
		return null
	var inst := scr.new() as RefCounted
	if inst == null:
		gd_failures.append("fu_runtime_v2_new_null")
	return inst


func _op_fu_runtime_load_and_reuse(sdk_root: String, _params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var sdk := _load_v2_sdk(sdk_root, gd_failures)
	if sdk == null:
		return false
	data["sdk_version"] = str(sdk.get("SDK_VERSION"))
	var utils_ok := true
	for uname: String in ["dag_cloner", "bounded_cloner", "value_utils", "validation_utils"]:
		var u: Variant = sdk.call("get_util_script", uname) if sdk.has_method(&"get_util_script") else null
		if u == null:
			utils_ok = false
			gd_failures.append("missing_util_script:" + uname)
	var logger: Variant = sdk.call("create_logger") if sdk.has_method(&"create_logger") else null
	var reg: Variant = sdk.call("create_module_registry") if sdk.has_method(&"create_module_registry") else null
	data["utils_ok"] = utils_ok
	data["logger_ok"] = (logger != null)
	data["registry_ok"] = (reg != null)
	if logger == null:
		gd_failures.append("create_logger_null")
	if reg == null:
		gd_failures.append("create_module_registry_null")
	for mname: String in ["create_desktop_api_helper", "create_hook_helper", "create_slot_helper", "create_comp_helper", "create_network_helper"]:
		if not sdk.has_method(mname):
			gd_failures.append("missing_v2_factory:" + mname)
		else:
			var helper: Variant = sdk.call(mname)
			if helper == null:
				gd_failures.append("null_helper_from:" + mname)
	return gd_failures.is_empty()


func _op_fu_runtime_leak_check(sdk_root: String, params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var sdk := _load_v2_sdk(sdk_root, gd_failures)
	if sdk == null:
		return false
	var create_cycle := bool(params.get("create_cycle", false))
	if not create_cycle:
		# Warm lazy _sub_script_cache on sdk before sampling baseline OBJECT_COUNT
		for mname: String in ["create_desktop_api_helper", "create_hook_helper", "create_slot_helper", "create_comp_helper", "create_network_helper"]:
			var warm: Variant = sdk.call(mname)
			warm = null
	var before := Performance.get_monitor(Performance.OBJECT_COUNT)
	var temp_leaks: Array[Node] = []
	if create_cycle:
		var a := Node.new()
		var b := Node.new()
		a.set_meta(&"peer", b)
		b.set_meta(&"peer", a)
		temp_leaks.append(a)
		temp_leaks.append(b)
		data["leaked_intentional"] = true
	else:
		for _i: int in range(5):
			var d: Variant = sdk.call("create_desktop_api_helper")
			var h: Variant = sdk.call("create_hook_helper")
			var s: Variant = sdk.call("create_slot_helper")
			var c: Variant = sdk.call("create_comp_helper")
			var n: Variant = sdk.call("create_network_helper")
			d = null
			h = null
			s = null
			c = null
			n = null
	var after := Performance.get_monitor(Performance.OBJECT_COUNT)
	for leak_n: Node in temp_leaks:
		leak_n.remove_meta(&"peer")
		leak_n.free()
	temp_leaks.clear()
	data["before_objects"] = before
	data["after_objects"] = after
	data["delta"] = after - before
	if create_cycle:
		return (after - before) > 0.0
	return is_equal_approx(after - before, 0.0)


func _op_desktop_api_contract(sdk_root: String, params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var sdk := _load_v2_sdk(sdk_root, gd_failures)
	if sdk == null:
		return false
	var env := _build_mock_desktop_tree()
	var rt := env["rt"] as MockHostRuntime
	var api := env["api"] as MockDesktopApi
	var tok := BoardToken.new()
	tok.name = "Hero"
	tok.set_meta(&"net_id", "ent_hero_1")
	api._entities.append(tok)
	api._selected.append(tok)
	api._vitals_by_id["ent_hero_1"] = {"name": "Hero", "source_kind": "stat_bubble", "hp_cur": 18, "hp_max": 24, "ac": 17, "shield": 2, "hp_locked": true}
	api._saved_module_entries["mod.test_demo"] = {"version": 1, "state": {"imported": true}}

	var as_non_gm := bool(params.get("non_gm", false))
	if as_non_gm:
		api._gm = false
		api._peer_id = 2
		api._player_id = "peer_2"

	var ext_ctx := ExtensionContext.new(null, rt)
	var helper: Variant = sdk.call("create_desktop_api_helper", ext_ctx)
	if helper == null:
		gd_failures.append("create_desktop_api_helper_null")
		tok.free()
		_free_mock_desktop_tree(env)
		return false

	var hobj := helper as Object
	data["is_gm"] = hobj.call("is_gm")
	data["network_role"] = hobj.call("network_role")
	data["local_peer_id"] = hobj.call("local_peer_id")
	data["local_player_id"] = hobj.call("local_player_id")
	data["joined_players"] = hobj.call("joined_players")
	data["active_scene_uid"] = hobj.call("active_scene_uid")
	data["active_scene_name"] = hobj.call("active_scene_name")
	data["active_floor_uid"] = hobj.call("active_floor_uid")
	data["active_floor_id"] = hobj.call("active_floor_id")
	data["world_units_per_cell"] = hobj.call("world_units_per_cell")
	data["vitals"] = hobj.call("read_entity_vitals", tok)
	data["can_command_self"] = hobj.call("can_command_entity", tok)
	data["can_command_by_id"] = hobj.call("can_command_entity", "ent_hero_1")
	data["can_command_peer2"] = hobj.call("can_command_entity", tok, 2)
	data["can_command_unknown"] = hobj.call("can_command_entity", "ent_missing")
	data["saved_entry"] = hobj.call("read_saved_module_entry", "mod.test_demo")
	data["roll_res"] = hobj.call("request_roll", "1d20+5", "Strike")
	data["focus_bad_inf"] = hobj.call("focus_camera", Vector2(INF, 0.0))
	data["focus_ok"] = hobj.call("focus_camera", Vector2(128.0, 256.0))
	data["cam_pos"] = hobj.call("camera_position")
	data["cam_zoom"] = hobj.call("camera_zoom")
	data["found_entity"] = (hobj.call("find_entity", "ent_hero_1") == tok)
	data["entity_count"] = (hobj.call("get_entities", true) as Array).size()
	data["selected_count"] = (hobj.call("selected_entities") as Array).size()
	hobj.call("set_mode", "select")
	data["current_mode"] = hobj.call("current_mode")

	ext_ctx.revert_all()
	tok.free()
	_free_mock_desktop_tree(env)
	return gd_failures.is_empty()


func _hook_sub_ok(val: Variant) -> bool:
	if val == null:
		return false
	if val is Dictionary:
		return bool((val as Dictionary).get("ok", false))
	if val is Object:
		var obj := val as Object
		if not is_instance_valid(obj):
			return false
		if obj.has_method(&"is_active"):
			return bool(obj.call(&"is_active"))
		return true
	if val is bool:
		return val == true
	return false


func _hook_emit_ok(val: Variant) -> bool:
	if val == null:
		return false
	if val is Dictionary:
		var d := val as Dictionary
		return bool(d.get("ok", false)) and bool(d.get("emitted", false))
	if val is bool:
		return val == true
	return false


func _op_hook_bus_contract(sdk_root: String, _params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var sdk := _load_v2_sdk(sdk_root, gd_failures)
	if sdk == null:
		return false
	var env := _build_mock_desktop_tree()
	var rt := env["rt"] as MockHostRuntime
	var ext_ctx := ExtensionContext.new(null, rt)
	var helper: Variant = sdk.call("create_hook_helper", ext_ctx)
	if helper == null:
		gd_failures.append("create_hook_helper_null")
		_free_mock_desktop_tree(env)
		return false
	var hobj := helper as Object

	var order: Array[String] = []
	var r_lo: Variant = hobj.call("subscribe", &"dice.rolled", func(p: Dictionary) -> void: order.append("lo:" + str(p.get("tag", ""))), 10)
	var r_hi: Variant = hobj.call("subscribe", &"dice.rolled", func(p: Dictionary) -> void: order.append("hi:" + str(p.get("tag", ""))), 50)
	var r_custom: Variant = hobj.call("subscribe", &"mod.demo_fx.burst", func(p: Dictionary) -> void: order.append("custom:" + str(p.get("v", ""))), 0)
	var r_bad_upper: Variant = hobj.call("subscribe", &"mod.Bad.ev", func(_p: Dictionary) -> void: pass, 0)
	var r_bad_two: Variant = hobj.call("subscribe", &"mod.onlytwo", func(_p: Dictionary) -> void: pass, 0)

	data["r_lo_ok"] = _hook_sub_ok(r_lo)
	data["r_hi_ok"] = _hook_sub_ok(r_hi)
	data["r_custom_ok"] = _hook_sub_ok(r_custom)
	data["r_bad_upper_ok"] = _hook_sub_ok(r_bad_upper)
	data["r_bad_two_ok"] = _hook_sub_ok(r_bad_two)

	var emitted_builtin: Variant = hobj.call("emit", &"dice.rolled", [{"tag": "n20"}])
	var emitted_custom: Variant = hobj.call("emit", &"mod.demo_fx.burst", [{"v": "ok"}])

	rt._publishing = true
	var emitted_while_pub: Variant = hobj.call("emit", &"mod.demo_fx.burst", [{"v": "blocked"}])
	rt._publishing = false

	ext_ctx.revert_all()
	var emitted_after_revert: Variant = hobj.call("emit", &"mod.demo_fx.burst", [{"v": "after"}])

	data["order"] = order
	data["emitted_builtin"] = _hook_emit_ok(emitted_builtin)
	data["emitted_custom"] = _hook_emit_ok(emitted_custom)
	data["emitted_while_pub"] = _hook_emit_ok(emitted_while_pub)
	data["emitted_after_revert"] = _hook_emit_ok(emitted_after_revert)
	if hobj.has_method(&"is_custom_namespaced"):
		data["valid_mod_hook"] = bool(hobj.call("is_custom_namespaced", &"mod.alpha_1.event_a"))
		data["valid_ext_hook"] = bool(hobj.call("is_custom_namespaced", &"ext.alpha_1.sub.ev"))
		data["invalid_upper_hook"] = bool(hobj.call("is_custom_namespaced", &"mod.Alpha.ev"))
		data["invalid_two_seg"] = bool(hobj.call("is_custom_namespaced", &"mod.onlytwo"))
	else:
		gd_failures.append("missing_hook_helper_is_custom_namespaced")

	_free_mock_desktop_tree(env)
	return gd_failures.is_empty()


func _op_overlay_and_mount_contract(sdk_root: String, _params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var sdk := _load_v2_sdk(sdk_root, gd_failures)
	if sdk == null:
		return false
	var env := _build_mock_desktop_tree()
	var desktop := env["desktop"] as Node
	var rt := env["rt"] as MockHostRuntime
	var ext_ctx := ExtensionContext.new(null, rt)
	var sh_var: Variant = sdk.call("create_slot_helper", ext_ctx)
	if sh_var == null:
		gd_failures.append("create_slot_helper_null")
		_free_mock_desktop_tree(env)
		return false
	var sh := sh_var as Object
	data["slot_helper_used"] = true

	var n_high := Node2D.new()
	n_high.name = "OverlayHighPrio"
	var n_low := Node2D.new()
	n_low.name = "OverlayLowPrio"
	var n_above := Node2D.new()
	n_above.name = "OverlayAbove"
	var n_fog := Control.new()
	n_fog.name = "OverlayFog"

	var r_high: Dictionary = sh.call("register_world_overlay", "o_high", "below_entities", {"priority": 20, "node": n_high})
	var r_low: Dictionary = sh.call("register_world_overlay", "o_low", "below_entities", {"priority": 5, "node": n_low})
	var r_above: Dictionary = sh.call("register_world_overlay", "o_above", "above_entities", {"priority": 10, "node": n_above})
	var r_fog: Dictionary = sh.call("register_world_overlay", "o_fog", "above_fog", {"priority": 10, "node": n_fog})
	if not bool(r_high.get("ok", false)) or not bool(r_low.get("ok", false)) or not bool(r_above.get("ok", false)) or not bool(r_fog.get("ok", false)):
		gd_failures.append("slot_helper_register_world_overlay_failed")

	var bad_band_node := Node2D.new()
	var bad_res: Dictionary = sh.call("register_world_overlay", "o_bad", "under_map", {"priority": 1, "node": bad_band_node})
	if is_instance_valid(bad_band_node) and bad_band_node.get_parent() == null:
		bad_band_node.free()

	var below_node := desktop.get_node("World/WorldOverlayBelowEntities")
	var child_names: Array[String] = []
	for ch: Node in below_node.get_children():
		child_names.append(ch.name)
	data["below_order"] = child_names
	data["above_count"] = desktop.get_node("World/WorldOverlayAboveEntities").get_child_count()
	data["fog_count"] = desktop.get_node("WorldOverlayAboveFogLayer/WorldOverlayAboveFog").get_child_count()
	data["bad_band_ok"] = bool(bad_res.get("ok", false))

	var custom := CanvasLayer.new()
	custom.name = "CustomMountedLayer"
	var m_res: Dictionary = sh.call("mount_node", desktop, custom)
	data["mount_ok"] = bool(m_res.get("ok", false))
	data["mounted_found"] = (desktop.get_node_or_null("CustomMountedLayer") != null)
	var dup_res: Dictionary = sh.call("mount_node", desktop, custom)
	data["already_parented_ok"] = bool(dup_res.get("ok", false))

	var orphan := Node2D.new()
	var outside := Node2D.new()
	var out_res: Dictionary = sh.call("mount_node", outside, orphan)
	data["outside_target_ok"] = bool(out_res.get("ok", false))
	orphan.free()
	outside.free()

	ext_ctx.revert_all()
	data["after_revert_mounted_found"] = (desktop.get_node_or_null("CustomMountedLayer") != null)
	rt.cleanup_all()
	# Process deferred queue_free
	await process_frame
	data["after_revert_below_count"] = below_node.get_child_count()
	data["after_revert_above_count"] = desktop.get_node("World/WorldOverlayAboveEntities").get_child_count()
	data["after_revert_fog_count"] = desktop.get_node("WorldOverlayAboveFogLayer/WorldOverlayAboveFog").get_child_count()

	_free_mock_desktop_tree(env)
	return gd_failures.is_empty()


func _op_desktop_module_mount_run(params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var entry_scene_path := String(params.get("entry_scene", ""))
	var service_id := String(params.get("service_id", ""))
	var custom_hook := StringName(String(params.get("custom_hook", "")))
	if entry_scene_path.is_empty() or not ResourceLoader.exists(entry_scene_path):
		gd_failures.append("entry_scene_missing:" + entry_scene_path)
		return false

	var scene := load(entry_scene_path) as PackedScene
	if scene == null:
		gd_failures.append("entry_scene_load_failed:" + entry_scene_path)
		return false
	var inst := scene.instantiate()
	if not (inst is ExtensionBase):
		gd_failures.append("entry_root_not_ExtensionBase")
		inst.free()
		return false

	var env := _build_mock_desktop_tree()
	var desktop := env["desktop"] as Node
	var rt := env["rt"] as MockHostRuntime
	desktop.add_child(inst)
	var ext_ctx := ExtensionContext.new(inst, rt)
	(inst as ExtensionBase).register_with_context(ext_ctx)

	if not service_id.is_empty():
		var svc: Variant = rt.consume_service(service_id)
		data["service_published"] = (svc == inst)
	if inst.has_method(&"get_runtime_sdk"):
		var rt_sdk: Variant = inst.call(&"get_runtime_sdk")
		data["runtime_sdk_loaded"] = (rt_sdk != null)
	var banner_before := false
	for ch: Node in desktop.get_children():
		if ch.name.begins_with("FxBannerLayer_"):
			banner_before = true
			break
	data["banner_mounted_before_unreg"] = banner_before
	if not String(custom_hook).is_empty() and inst.has_method(&"emit_custom_burst"):
		data["custom_emit_ok"] = bool(inst.call(&"emit_custom_burst", "probe_test"))
	rt.emit_hook(&"dice.rolled", [{"is_nat20": true, "total": 25}])
	rt.emit_hook(&"vitals.downed", [{"entity_id": "ent_1"}])
	if inst.has_method(&"get_event_log"):
		data["event_log"] = inst.call(&"get_event_log")
	data["above_overlay_count"] = desktop.get_node("World/WorldOverlayAboveEntities").get_child_count()

	(inst as ExtensionBase).unregister_with_context()
	desktop.remove_child(inst)
	inst.free()
	var banner_after := false
	for ch: Node in desktop.get_children():
		if ch.name.begins_with("FxBannerLayer_"):
			banner_after = true
			break
	data["banner_mounted_after_unreg"] = banner_after
	rt.cleanup_all()
	await process_frame
	data["above_overlay_count_after_unreg"] = desktop.get_node("World/WorldOverlayAboveEntities").get_child_count()
	_free_mock_desktop_tree(env)
	return gd_failures.is_empty()


func _op_world_plugin_comp_and_disclosure(params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var comp_path := String(params.get("comp_path", ""))
	if comp_path.is_empty() or not ResourceLoader.exists(comp_path):
		gd_failures.append("comp_script_missing:" + comp_path)
		return false
	var comp_scr := load(comp_path) as Script
	if comp_scr == null:
		gd_failures.append("comp_script_load_failed:" + comp_path)
		return false

	var tok := BoardToken.new()
	tok.name = "Paladin"
	var perm := CompPermission.new()
	perm.name = "permission"
	tok.add_component(perm)

	var c := comp_scr.new() as CompBase
	if c == null:
		gd_failures.append("comp_not_CompBase")
		tok.free()
		return false

	data["id_from_path"] = CompBase.id_from_path(comp_path)
	data["has_public_state"] = c.has_method(&"public_state")
	data["tags"] = Array(c.component_tags())

	c.set("radius_cells", 6)
	c.set("dm_secret", true)
	var added := tok.add_component(c)
	data["added_ok"] = added

	if c.has_method(&"public_state"):
		var st: Dictionary = c.serialize_state()
		data["public_gm"] = c.call(&"public_state", st, 1)
		data["public_peer2_unauth"] = c.call(&"public_state", st, 2)
		perm.commanders.append(2)
		data["public_peer2_auth"] = c.call(&"public_state", st, 2)

	# Test dominant suppression + automatic revival
	var dom_scr := GDScript.new()
	dom_scr.source_code = "extends CompBase\nfunc suppresses_components() -> PackedStringArray:\n\treturn PackedStringArray(['*'])\nfunc dominance_priority() -> int:\n\treturn 100\n"
	dom_scr.take_over_path("res://fus_host_shims/_temp_dom_%d.gd" % Time.get_ticks_usec())
	dom_scr.reload()
	var dom := dom_scr.new() as CompBase
	var dom_added := tok.add_component(dom)
	data["dom_added"] = dom_added
	data["parked_after_dom"] = tok.parked_component_count()
	data["suppressed_flag"] = tok.is_component_suppressed(c.get_comp_id())

	# Attempt to attach another suppressed comp while dominant is active
	var extra := comp_scr.new() as CompBase
	var rej_before := tok.component_pair_rejections
	var blocked := tok.add_component(extra)
	if not blocked:
		extra.free()
	data["blocked_while_suppressed"] = (not blocked) and (tok.component_pair_rejections > rej_before)

	# Purge dominant -> aura revives with radius_cells == 6
	var purged := tok.purge_component_by_id(dom.get_comp_id())
	var revived := tok.get_component_by_id(c.get_comp_id())
	data["revived_ok"] = purged and revived != null and int(revived.get("radius_cells")) == 6 and tok.parked_component_count() == 0

	tok.cleanup_all_components()
	tok.free()
	return gd_failures.is_empty()


func _op_world_plugin_page_and_undo(params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var page_scene_path := String(params.get("page_scene", ""))
	var comp_path := String(params.get("comp_path", ""))
	var p_scene := load(page_scene_path) as PackedScene
	if p_scene == null:
		gd_failures.append("page_scene_load_failed:" + page_scene_path)
		return false
	var page_inst := p_scene.instantiate()
	var is_valid_page := (page_inst is EntityComponentPage)
	data["is_EntityComponentPage"] = is_valid_page
	if not is_valid_page:
		page_inst.free()
		return true

	var tok := BoardToken.new()
	var editor := EditModeController.new()
	var act_ok := editor.components_request([tok], comp_path, &"activate")
	data["activate_ok"] = act_ok
	var cid := CompBase.id_from_path(comp_path)
	var comp := tok.get_component_by_id(cid)
	var page := page_inst as EntityComponentPage
	page.component_id = cid

	var captured_edits: Array[Dictionary] = []
	page.edit_requested.connect(func(kind: StringName, payload: Dictionary) -> void:
		captured_edits.append({"kind": String(kind), "payload": payload})
	)
	page.bind_entities([tok] as Array[BoardToken])
	if page.has_method(&"emit_radius_edit"):
		page.call(&"emit_radius_edit", 8)
	data["edit_signal_count"] = captured_edits.size()

	var prev_st: Dictionary = comp.serialize_state()
	var next_st: Dictionary = prev_st.duplicate(true)
	next_st["radius_cells"] = 8
	var cfg_ok := editor.configure_components([tok], comp_path, [{"state": prev_st}], [{"state": next_st}], Callable(), "host", false)
	data["configure_ok"] = cfg_ok
	data["radius_after_edit"] = int(comp.get("radius_cells"))
	editor.undo()
	data["radius_after_undo"] = int(comp.get("radius_cells"))
	editor.redo()
	data["radius_after_redo"] = int(comp.get("radius_cells"))

	# Bad non-editable field test
	var bad_st: Dictionary = prev_st.duplicate(true)
	bad_st["non_editable_field"] = 99
	data["bad_field_rejected"] = not editor.configure_components([tok], comp_path, [{"state": prev_st}], [{"state": bad_st}], Callable(), "host", false)

	# Bad schema_version mutation test
	var cur_st: Dictionary = comp.serialize_state()
	var bad_sv_st: Dictionary = cur_st.duplicate(true)
	bad_sv_st["schema_version"] = int(cur_st.get("schema_version", 1)) + 1
	data["schema_version_mutation_rejected"] = not editor.configure_components([tok], comp_path, [{"state": cur_st}], [{"state": bad_sv_st}], Callable(), "host", false)

	page.free()
	editor.free()
	tok.cleanup_all_components()
	tok.free()
	return gd_failures.is_empty()


func _op_world_module_state_3phase(sdk_root: String, params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var feature_scene_path := String(params.get("feature_scene", ""))
	var f_scene := load(feature_scene_path) as PackedScene
	if f_scene == null:
		gd_failures.append("feature_scene_load_failed:" + feature_scene_path)
		return false
	var inst := f_scene.instantiate() as ExtensionBase
	var prep_empty: Dictionary = inst.call(&"prepare_module_state", {})
	var prep_saved: Dictionary = inst.call(&"prepare_module_state", {"version": 1, "cell_feet": 10, "show_labels": false})
	var prep_bad: Dictionary = inst.call(&"prepare_module_state", {"version": 999})
	var apply_ok := bool(inst.call(&"apply_module_state", {"version": 1, "cell_feet": 10, "show_labels": false}))
	var ser: Dictionary = inst.call(&"serialize_module_state")
	var raw_bytes := var_to_bytes(ser)
	var restored: Variant = bytes_to_var(raw_bytes)

	data["prep_empty_ok"] = bool(prep_empty.get("ok", false))
	data["prep_saved_ok"] = bool(prep_saved.get("ok", false))
	data["prep_bad_ok"] = bool(prep_bad.get("ok", false))
	data["apply_ok"] = apply_ok
	data["serialized"] = ser
	data["roundtrip_equal"] = (restored == ser)

	# Also check fu_runtime comp_helper.is_pure_data against Object / NAN / depth > 32
	var sdk := _load_v2_sdk(sdk_root, gd_failures)
	if sdk != null:
		var ch: Variant = sdk.call("create_comp_helper")
		if ch != null and (ch as Object).has_method(&"is_pure_data"):
			var ch_obj := ch as Object
			var dummy := RefCounted.new()
			data["rejects_object"] = not bool(ch_obj.call(&"is_pure_data", dummy))
			data["rejects_nan"] = not bool(ch_obj.call(&"is_pure_data", NAN))
			var deep: Dictionary = {}
			var cur := deep
			for _d: int in range(36):
				var nxt: Dictionary = {}
				cur["n"] = nxt
				cur = nxt
			data["rejects_deep"] = not bool(ch_obj.call(&"is_pure_data", deep))
		else:
			gd_failures.append("comp_helper_missing_is_pure_data")

	inst.free()
	return gd_failures.is_empty()


func _op_network_actions_projections(sdk_root: String, params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var feature_scene_path := String(params.get("feature_scene", ""))
	var f_scene := load(feature_scene_path) as PackedScene
	if f_scene == null:
		gd_failures.append("feature_scene_load_failed:" + feature_scene_path)
		return false
	var inst := f_scene.instantiate() as ExtensionBase
	var env := _build_mock_desktop_tree()
	var rt := env["rt"] as MockHostRuntime
	(env["desktop"] as Node).add_child(inst)
	var ext_ctx := ExtensionContext.new(inst, rt)
	inst.register_with_context(ext_ctx)

	var actions: Array = rt._slots[&"network.actions"]
	var projs: Array = rt._slots[&"network.projections"]
	var mod_id := String(inst.get_meta(&"module_id", ""))
	data["action_id_matches_module"] = (not actions.is_empty() and String((actions[0] as Dictionary).get("id", "")) == mod_id)
	data["proj_id_matches_module"] = (not projs.is_empty() and String((projs[0] as Dictionary).get("id", "")) == mod_id)

	var revoked_unauth := String(inst.call(&"network_action_revoked", 2, {"op": "set_radius", "radius_cells": 4, "commanded": false}))
	var revoked_auth := String(inst.call(&"network_action_revoked", 2, {"op": "set_radius", "radius_cells": 4, "commanded": true}))
	var req_res: Dictionary = inst.call(&"network_request", 1, {"op": "set_radius", "radius_cells": 4})

	var proj_payload: Dictionary = inst.call(&"network_projection", 2, {}, true)
	var cursor: Dictionary = inst.call(&"network_cursor", proj_payload)
	var staged_payload: Dictionary = proj_payload.duplicate(true)
	staged_payload["settings"] = {"version": 1, "cell_feet": 15, "show_labels": false}
	var checked: Dictionary = inst.call(&"validate_replica_projection", staged_payload, inst)
	var prev_snap: Dictionary = inst.call(&"capture_replica_projection")
	var bad_stage := bool(inst.call(&"stage_replica_projection", staged_payload, checked, null))
	var rogue_writer := ExtensionBase.new()
	var non_owner_stage := bool(inst.call(&"stage_replica_projection", staged_payload, checked, rogue_writer))
	var non_owner_restore := bool(inst.call(&"restore_replica_projection", prev_snap, rogue_writer))
	rogue_writer.free()
	var unowned_sync_stage := bool(inst.call(&"stage_replica_projection", staged_payload, checked, rt))
	var unowned_sync_restore := bool(inst.call(&"restore_replica_projection", prev_snap, rt))
	var other_owner := ExtensionBase.new()
	rt.begin_projection_write(other_owner)
	var other_owner_sync_stage := bool(inst.call(&"stage_replica_projection", staged_payload, checked, rt))
	rt.end_projection_write()
	other_owner.free()

	rt.begin_projection_write(inst)
	var good_stage := bool(inst.call(&"stage_replica_projection", staged_payload, checked, rt))
	inst.call(&"publish_replica_projection", rt)
	var state_after_publish: Dictionary = inst.call(&"serialize_module_state")
	var restored_ok := bool(inst.call(&"restore_replica_projection", prev_snap, rt))
	var state_after_restore: Dictionary = inst.call(&"serialize_module_state")
	rt.end_projection_write()

	data["revoked_unauth"] = revoked_unauth
	data["revoked_auth"] = revoked_auth
	data["req_ok"] = bool(req_res.get("ok", false))
	data["cursor_rev"] = int(cursor.get("revision", -1))
	data["bad_stage_rejected"] = not bad_stage
	data["non_owner_stage_rejected"] = not non_owner_stage
	data["non_owner_restore_rejected"] = not non_owner_restore
	data["unowned_sync_stage_rejected"] = not unowned_sync_stage
	data["unowned_sync_restore_rejected"] = not unowned_sync_restore
	data["other_owner_sync_stage_rejected"] = not other_owner_sync_stage
	data["good_stage_ok"] = good_stage
	data["state_after_publish"] = state_after_publish
	data["restored_ok"] = restored_ok
	data["state_after_restore"] = state_after_restore

	if not sdk_root.is_empty() and (ResourceLoader.exists(sdk_root) or FileAccess.file_exists(sdk_root)):
		var sdk := _load_v2_sdk(sdk_root, gd_failures)
		if sdk != null and sdk.has_method(&"create_network_helper"):
			var nh: Variant = sdk.call("create_network_helper", mod_id, false, ext_ctx)
			data["network_helper_ok"] = (nh != null)
			if nh != null:
				var nh_obj := nh as Object
				var act_val: Dictionary = nh_obj.call("validate_action_provider", inst)
				var prj_val: Dictionary = nh_obj.call("validate_projection_provider", inst)
				data["action_provider_valid"] = bool(act_val.get("ok", false))
				data["proj_provider_valid"] = bool(prj_val.get("ok", false))

	inst.unregister_with_context()
	(env["desktop"] as Node).remove_child(inst)
	inst.free()
	rt.cleanup_all()
	await process_frame
	_free_mock_desktop_tree(env)
	return gd_failures.is_empty()


func _op_ui_slots_contract(_sdk_root: String, params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var feature_scene_path := String(params.get("feature_scene", ""))
	var f_scene := load(feature_scene_path) as PackedScene
	if f_scene == null:
		gd_failures.append("feature_scene_load_failed:" + feature_scene_path)
		return false
	var inst := f_scene.instantiate() as ExtensionBase
	var env := _build_mock_desktop_tree()
	var rt := env["rt"] as MockHostRuntime
	(env["desktop"] as Node).add_child(inst)
	var ext_ctx := ExtensionContext.new(inst, rt)
	inst.register_with_context(ext_ctx)

	data["panels_count"] = (rt._slots[&"ui.desktop_panels"] as Array).size()
	data["settings_count"] = (rt._slots[&"ui.module_settings"] as Array).size()
	data["mode_bar_count"] = (rt._slots[&"ui.mode_bar"] as Array).size()
	data["entity_actions_count"] = (rt._slots[&"ui.entity_actions"] as Array).size()
	data["rejected_items"] = rt._rejected_items.duplicate()

	if not (rt._slots[&"ui.mode_bar"] as Array).is_empty():
		var m_spec := (rt._slots[&"ui.mode_bar"] as Array)[0] as Dictionary
		data["mode_predicate_ok"] = bool((m_spec["predicate"] as Callable).call(env["desktop"]))
		var enter_res: Variant = (m_spec["on_enter"] as Callable).call(env["desktop"])
		data["mode_on_enter_is_true"] = (enter_res == true)
		data["mode_active_after_enter"] = bool(inst.get("_mode_active"))
		(m_spec["on_exit"] as Callable).call(env["desktop"])
		data["mode_active_after_exit"] = bool(inst.get("_mode_active"))

	if not (rt._slots[&"ui.entity_actions"] as Array).is_empty():
		var a_spec := (rt._slots[&"ui.entity_actions"] as Array)[0] as Dictionary
		var dummy_tok := BoardToken.new()
		data["action_pred_empty"] = bool((a_spec["predicate"] as Callable).call(env["desktop"], []))
		data["action_pred_non_empty"] = bool((a_spec["predicate"] as Callable).call(env["desktop"], [dummy_tok]))
		var pres_res: Variant = (a_spec["presentation"] as Callable).call(env["desktop"], [dummy_tok])
		data["action_pres_enabled"] = (pres_res is Dictionary and bool((pres_res as Dictionary).get("enabled", false)))
		data["action_exec_ok"] = bool((a_spec["execute"] as Callable).call(env["desktop"], [dummy_tok]))
		dummy_tok.free()

	inst.unregister_with_context()
	(env["desktop"] as Node).remove_child(inst)
	inst.free()
	rt.cleanup_all()
	await process_frame
	_free_mock_desktop_tree(env)
	return gd_failures.is_empty()


func _op_mount_and_compile_only(params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var paths: Array = params.get("check_paths", []) as Array if params.get("check_paths") is Array else []
	var loaded := 0
	for p: Variant in paths:
		var sp := String(p)
		if not ResourceLoader.exists(sp):
			gd_failures.append("missing_res:" + sp)
			continue
		var r: Resource = load(sp)
		if r == null:
			gd_failures.append("load_failed:" + sp)
		else:
			loaded += 1
	data["loaded_count"] = loaded
	return gd_failures.is_empty()


func _op_fu_runtime_network_local_only_guard(sdk_root: String, data: Dictionary, gd_failures: Array[String]) -> bool:
	var sdk := _load_v2_sdk(sdk_root, gd_failures)
	if sdk == null:
		return false
	var env := _build_mock_desktop_tree()
	var rt := env["rt"] as MockHostRuntime
	var ext_ctx := ExtensionContext.new(null, rt)

	var nh_local: Variant = sdk.call("create_network_helper", "mod.t1_f08", true, ext_ctx)
	if nh_local == null:
		gd_failures.append("create_network_helper_local_null")
		_free_mock_desktop_tree(env)
		return false
	var nh_l := nh_local as Object
	data["is_local_only"] = bool(nh_l.call("is_local_only"))
	var act_local: Dictionary = nh_l.call("make_network_actions_spec")
	var prj_local: Dictionary = nh_l.call("make_network_projections_spec")
	var prov := Node.new()
	var reg_local: Dictionary = nh_l.call("register_network_actions", prov)
	data["local_actions_ok"] = bool(act_local.get("ok", false))
	data["local_actions_reason"] = String(act_local.get("reason", ""))
	data["local_projs_ok"] = bool(prj_local.get("ok", false))
	data["local_projs_reason"] = String(prj_local.get("reason", ""))
	data["local_reg_ok"] = bool(reg_local.get("ok", false))

	var nh_net: Variant = sdk.call("create_network_helper", "t1_f08.core", false, ext_ctx)
	var nh_n := nh_net as Object
	var act_net: Dictionary = nh_n.call("make_network_actions_spec")
	var prj_net: Dictionary = nh_n.call("make_network_projections_spec")
	data["net_actions_ok"] = bool(act_net.get("ok", false))
	data["net_actions_id"] = String((act_net.get("spec", {}) as Dictionary).get("id", ""))
	data["net_projs_ok"] = bool(prj_net.get("ok", false))
	data["net_projs_replica_only"] = bool((prj_net.get("spec", {}) as Dictionary).get("replica_presentation_only", false))

	prov.free()
	ext_ctx.revert_all()
	rt.cleanup_all()
	await process_frame
	_free_mock_desktop_tree(env)
	return gd_failures.is_empty()


func _op_fu_runtime_comp_helper_contract(sdk_root: String, data: Dictionary, gd_failures: Array[String]) -> bool:
	var sdk := _load_v2_sdk(sdk_root, gd_failures)
	if sdk == null:
		return false
	var env := _build_mock_desktop_tree()
	var rt := env["rt"] as MockHostRuntime
	var ext_ctx := ExtensionContext.new(null, rt)
	var ch_var: Variant = sdk.call("create_comp_helper", ext_ctx)
	if ch_var == null:
		gd_failures.append("create_comp_helper_null")
		_free_mock_desktop_tree(env)
		return false
	var ch := ch_var as Object

	var ns_id: String = String(ch.call("make_namespaced_comp_id", "t1_f10", "emitter"))
	data["namespaced_comp_id"] = ns_id

	var ps := PackedScene.new()
	var dummy_node := Node.new()
	dummy_node.name = "CompDummy"
	ps.pack(dummy_node)
	dummy_node.free()

	var spec_res: Dictionary = ch.call(
		"make_component_spec",
		ns_id,
		"res://external_modules/t1_f10/comp_t1_f10__emitter.gd",
		ps,
		{"network_scope": "shared", "label": "Emitter"}
	)
	data["spec_ok"] = bool(spec_res.get("ok", false))
	var spec: Dictionary = spec_res.get("spec", {}) as Dictionary
	data["spec_field_count"] = spec.size()
	data["spec_id"] = String(spec.get("id", ""))

	var bad_reserved: Dictionary = ch.call("make_component_spec", "visual", "res://external_modules/t1_f10/comp_visual.gd", ps)
	var bad_peer_scope: Dictionary = ch.call(
		"make_component_spec",
		ns_id,
		"res://external_modules/t1_f10/comp_t1_f10__emitter.gd",
		ps,
		{"network_scope": "shared", "entity_local_content": true}
	)
	data["reserved_rejected"] = not bool(bad_reserved.get("ok", false))
	data["peer_scope_rejected"] = not bool(bad_peer_scope.get("ok", false))

	var reg_res: Dictionary = ch.call(
		"register_component",
		ns_id,
		"res://external_modules/t1_f10/comp_t1_f10__emitter.gd",
		ps,
		{"network_scope": "shared", "label": "Emitter"}
	)
	data["register_ok"] = bool(reg_res.get("ok", false))

	var pub_unauth: Dictionary = ch.call(
		"build_public_state",
		{"radius_cells": 6, "dm_secret": true},
		2,
		{"radius_cells": 2},
		func(_p: int) -> bool: return false
	)
	var pub_gm: Dictionary = ch.call(
		"build_public_state",
		{"radius_cells": 6, "dm_secret": true},
		1,
		{"radius_cells": 2},
		func(_p: int) -> bool: return false
	)
	data["pub_unauth_masked"] = pub_unauth.is_empty()
	data["pub_gm_radius"] = int(pub_gm.get("radius_cells", -1))

	ext_ctx.revert_all()
	rt.cleanup_all()
	await process_frame
	_free_mock_desktop_tree(env)
	return gd_failures.is_empty()


func _op_fu_runtime_comp_edit_payloads(sdk_root: String, data: Dictionary, gd_failures: Array[String]) -> bool:
	var sdk := _load_v2_sdk(sdk_root, gd_failures)
	if sdk == null:
		return false
	var ch_var: Variant = sdk.call("create_comp_helper")
	if ch_var == null:
		gd_failures.append("create_comp_helper_null")
		return false
	var ch := ch_var as Object
	var tok := BoardToken.new()
	var comp := CompBase.new()
	var page := EntityComponentPage.new()

	var field_p: Dictionary = ch.call("make_field_edit_payload", [tok], [comp], "radius_cells", [2], 8)
	var num_begin: Dictionary = ch.call("make_numeric_edit_payload", [tok], [comp], "radius_cells", [2], &"begin", page, 42, [6])
	var num_end: Dictionary = ch.call("make_numeric_edit_payload", [tok], [comp], "radius_cells", [2], &"end", page, 42, [8])

	data["field_ok"] = (
		String(field_p.get("field", "")) == "radius_cells"
		and int(field_p.get("value", -1)) == 8
		and (field_p.get("targets", []) as Array).size() == 1
		and (field_p.get("components", []) as Array).size() == 1
	)
	data["num_begin_ok"] = (
		StringName(num_begin.get("phase", &"")) == &"begin"
		and int(num_begin.get("token", -1)) == 42
		and (num_begin.get("before", []) as Array) == [2]
		and (num_begin.get("values", []) as Array) == [6]
	)
	data["num_end_ok"] = (
		StringName(num_end.get("phase", &"")) == &"end"
		and not num_end.has("targets")
		and (num_end.get("values", []) as Array) == [8]
	)

	page.free()
	comp.free()
	tok.free()
	return gd_failures.is_empty()


func _op_fu_runtime_slot_helper_ui_4_slots(sdk_root: String, data: Dictionary, gd_failures: Array[String]) -> bool:
	var sdk := _load_v2_sdk(sdk_root, gd_failures)
	if sdk == null:
		return false
	var env := _build_mock_desktop_tree()
	var rt := env["rt"] as MockHostRuntime
	var ext_ctx := ExtensionContext.new(null, rt)
	var sh_var: Variant = sdk.call("create_slot_helper", ext_ctx)
	if sh_var == null:
		gd_failures.append("create_slot_helper_null")
		_free_mock_desktop_tree(env)
		return false
	var sh := sh_var as Object

	var panel_ps := PackedScene.new()
	var ctrl := Control.new()
	ctrl.name = "SlotPanel"
	panel_ps.pack(ctrl)
	ctrl.free()

	var provider := Node.new()
	var r_panel: Dictionary = sh.call("register_desktop_panel", "t1_f14.panel", "Panel", panel_ps, provider, {"priority": 10})
	var r_settings: Dictionary = sh.call("register_module_settings", "t1_f14.settings", "Settings", panel_ps, provider, {"priority": 10})
	var on_enter := func(_d: Node) -> bool: return true
	var on_exit := func(_d: Node) -> void: pass
	var mode_pred := func(_d: Node) -> bool: return true
	var r_mode: Dictionary = sh.call("register_mode_bar", "t1_f14.inspect", "Inspect", on_enter, on_exit, mode_pred)
	var bad_builtin_mode: Dictionary = sh.call("make_mode_bar_spec", "select", "Select", on_enter, on_exit, mode_pred)

	var act_exec := func(_d: Node, _t: Array) -> bool: return true
	var act_pred := func(_d: Node, _t: Array) -> bool: return true
	var r_action: Dictionary = sh.call("register_entity_action", "t1_f14.toggle", "Toggle", act_exec, act_pred)
	var bad_nodot_action: Dictionary = sh.call("make_entity_action_spec", "nodot", "NoDot", act_exec, act_pred)

	data["panel_reg_ok"] = bool(r_panel.get("ok", false))
	data["settings_reg_ok"] = bool(r_settings.get("ok", false))
	data["mode_reg_ok"] = bool(r_mode.get("ok", false))
	data["action_reg_ok"] = bool(r_action.get("ok", false))
	data["bad_builtin_mode_rejected"] = not bool(bad_builtin_mode.get("ok", false))
	data["bad_nodot_action_rejected"] = not bool(bad_nodot_action.get("ok", false))
	data["panels_count"] = (rt._slots[&"ui.desktop_panels"] as Array).size()
	data["settings_count"] = (rt._slots[&"ui.module_settings"] as Array).size()
	data["mode_bar_count"] = (rt._slots[&"ui.mode_bar"] as Array).size()
	data["entity_actions_count"] = (rt._slots[&"ui.entity_actions"] as Array).size()

	provider.free()
	ext_ctx.revert_all()
	rt.cleanup_all()
	await process_frame
	_free_mock_desktop_tree(env)
	return gd_failures.is_empty()


func _op_mode_bar_hook_bus_integration(sdk_root: String, data: Dictionary, gd_failures: Array[String]) -> bool:
	var sdk := _load_v2_sdk(sdk_root, gd_failures)
	if sdk == null:
		return false
	var env := _build_mock_desktop_tree()
	var desktop := env["desktop"] as Node
	var rt := env["rt"] as MockHostRuntime
	var api := env["api"] as MockDesktopApi
	api._mode = "select"

	var ext_ctx := ExtensionContext.new(null, rt)
	var sh_var: Variant = sdk.call("create_slot_helper", ext_ctx)
	var hh_var: Variant = sdk.call("create_hook_helper", ext_ctx)
	var dapi_var: Variant = sdk.call("create_desktop_api_helper", ext_ctx)
	if sh_var == null or hh_var == null or dapi_var == null:
		gd_failures.append("create_runtime_helpers_failed")
		_free_mock_desktop_tree(env)
		return false
	var sh := sh_var as Object
	var hh := hh_var as Object
	var dapi := dapi_var as Object

	var entered_modes: Array[String] = []
	var exited_modes: Array[String] = []
	var on_enter := func(d: Node) -> bool:
		entered_modes.append(d.name)
		return true
	var on_exit := func(d: Node) -> void:
		exited_modes.append(d.name)
	var pred := func(_d: Node) -> bool:
		return true
	var reg_mode: Dictionary = sh.call("register_mode_bar", "mod_t3_c12.inspect", "Inspect Mode", on_enter, on_exit, pred)
	data["mode_reg_ok"] = bool(reg_mode.get("ok", false))
	data["mode_bar_count"] = (rt._slots[&"ui.mode_bar"] as Array).size()

	var pre_log: Array[String] = []
	var changed_log: Array[String] = []
	var pre_tok: Variant = hh.call("subscribe", &"mode.pre_change", func(old_m: String, new_m: String) -> bool:
		pre_log.append(old_m + "->" + new_m)
		return new_m != "blocked_mode", 10)
	var chg_tok: Variant = hh.call("subscribe", &"mode.changed", func(old_m: String, new_m: String) -> void:
		changed_log.append(old_m + "->" + new_m), 0)
	data["pre_hook_sub_ok"] = _hook_sub_ok(pre_tok)
	data["changed_hook_sub_ok"] = _hook_sub_ok(chg_tok)

	api._mode_change_cb = func(old_m: String, new_m: String) -> bool:
		if not rt.emit_hook(&"mode.pre_change", [old_m, new_m]):
			return false
		for item: Variant in rt._slots.get(&"ui.mode_bar", []):
			if item is Dictionary:
				var sp := item as Dictionary
				if String(sp.get("id", "")) == old_m:
					var exit_cb := sp.get("on_exit", Callable()) as Callable
					if exit_cb.is_valid():
						exit_cb.call(desktop)
				if String(sp.get("id", "")) == new_m:
					var enter_cb := sp.get("on_enter", Callable()) as Callable
					if enter_cb.is_valid() and not bool(enter_cb.call(desktop)):
						return false
		rt.emit_hook(&"mode.changed", [old_m, new_m])
		return true

	data["blocked_mode_result"] = bool(dapi.call("set_mode", "blocked_mode"))
	data["mode_after_blocked"] = String(dapi.call("current_mode"))
	data["changed_count_after_blocked"] = changed_log.size()

	data["enter_mode_result"] = bool(dapi.call("set_mode", "mod_t3_c12.inspect"))
	data["mode_after_enter"] = String(dapi.call("current_mode"))

	data["exit_mode_result"] = bool(dapi.call("set_mode", "select"))
	data["mode_after_exit"] = String(dapi.call("current_mode"))
	data["entered_modes"] = entered_modes
	data["exited_modes"] = exited_modes
	data["pre_log"] = pre_log
	data["changed_log"] = changed_log

	ext_ctx.revert_all()
	var pre_rem: int = (rt._hooks.get(&"mode.pre_change", []) as Array).size()
	var chg_rem: int = (rt._hooks.get(&"mode.changed", []) as Array).size()
	data["hooks_remaining_after_revert"] = pre_rem + chg_rem
	var emit_after_rev: Dictionary = hh.call("emit", &"mode.changed", ["select", "edit"])
	data["emit_after_revert_ok"] = _hook_emit_ok(emit_after_rev)

	rt.cleanup_all()
	await process_frame
	_free_mock_desktop_tree(env)
	return gd_failures.is_empty()


func _op_v1_to_desktop_saved_entry_bridge(sdk_root: String, params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var entry_path := String(params.get("entry_path", "res://entry.gd")).strip_edges()
	var module_id := String(params.get("module_id", "mod.t3_c16_bridge")).strip_edges()
	if not (ResourceLoader.exists(entry_path) or FileAccess.file_exists(entry_path)):
		gd_failures.append("v1_entry_missing:" + entry_path)
		return false
	var entry_scr := load(entry_path) as Script
	if entry_scr == null or not entry_scr.can_instantiate():
		gd_failures.append("v1_entry_load_failed:" + entry_path)
		return false
	var entry_inst: Variant = entry_scr.new()
	if not (entry_inst is RefCounted):
		gd_failures.append("v1_entry_not_RefCounted")
		if entry_inst is Node:
			(entry_inst as Node).free()
		return false

	var v1_host := MockV1ImportHost.new()
	var prep_res: Dictionary = (entry_inst as RefCounted).call(&"prepare_import", "", {}, v1_host)
	data["prep_ok"] = bool(prep_res.get("ok", false))
	if not bool(prep_res.get("ok", false)):
		gd_failures.append("v1_prepare_import_failed:" + str(prep_res.get("reason", "")))
		return false

	var world_dict: Dictionary = prep_res.get("world", {}) as Dictionary
	var modules_block: Dictionary = world_dict.get("modules", {}) as Dictionary
	var entries_block: Dictionary = modules_block.get("entries", {}) as Dictionary

	var sdk := _load_v2_sdk(sdk_root, gd_failures)
	if sdk == null:
		return false
	var env := _build_mock_desktop_tree()
	var rt := env["rt"] as MockHostRuntime
	var api := env["api"] as MockDesktopApi
	api._saved_module_entries = entries_block.duplicate(true)

	var tok := BoardToken.new()
	tok.name = "Hero"
	tok.set_meta(&"net_id", "ent_hero_1")
	api._entities.append(tok)
	api._vitals_by_id["ent_hero_1"] = {"name": "Hero", "source_kind": "stat_bubble", "hp_cur": 18, "hp_max": 24, "ac": 17, "shield": 2, "hp_locked": true}

	if bool(params.get("non_gm", false)):
		api._gm = false
		api._peer_id = 2
		api._player_id = "peer_2"

	var ext_ctx := ExtensionContext.new(null, rt)
	var helper: Variant = sdk.call("create_desktop_api_helper", ext_ctx)
	if helper == null:
		gd_failures.append("create_desktop_api_helper_null")
		tok.free()
		_free_mock_desktop_tree(env)
		return false
	var hobj := helper as Object

	data["is_gm"] = hobj.call("is_gm")
	data["network_role"] = hobj.call("network_role")
	data["vitals"] = hobj.call("read_entity_vitals", tok)
	var saved: Dictionary = hobj.call("read_saved_module_entry", module_id)
	data["saved_entry"] = saved.duplicate(true)
	if not saved.is_empty():
		saved["version"] = 999
		if saved.get("state") is Dictionary:
			(saved["state"] as Dictionary)["mutated"] = true
	var reread: Dictionary = hobj.call("read_saved_module_entry", module_id)
	data["clone_isolated"] = (reread == (data["saved_entry"] as Dictionary))
	data["unknown_entry"] = hobj.call("read_saved_module_entry", "mod.does_not_exist")
	data["empty_id_entry"] = hobj.call("read_saved_module_entry", "")

	ext_ctx.revert_all()
	tok.free()
	_free_mock_desktop_tree(env)
	return gd_failures.is_empty()


func _parse_args(argv: PackedStringArray) -> Dictionary:
	var out: Dictionary = {}
	for raw: String in argv:
		if raw.begins_with("--"):
			var eq := raw.find("=")
			if eq > 2:
				out[raw.substr(2, eq - 2)] = raw.substr(eq + 1)
			else:
				out[raw.substr(2)] = "1"
	return out


func _decode_special(val: Variant) -> Variant:
	if val is Dictionary:
		var d := val as Dictionary
		var gdt := str(d.get("__gd_type", ""))
		if gdt == "float":
			var fv := str(d.get("value", ""))
			if fv == "NaN":
				return NAN
			if fv == "Inf":
				return INF
			if fv == "-Inf":
				return -INF
		var out: Dictionary = {}
		for k: Variant in d.keys():
			out[k] = _decode_special(d[k])
		return out
	if val is Array:
		var arr: Array = []
		for item: Variant in val as Array:
			arr.append(_decode_special(item))
		return arr
	return val


func _to_json_safe(val: Variant) -> Variant:
	if val is float:
		var f := float(val)
		if is_nan(f):
			return "__NAN__"
		if is_inf(f):
			return "__INF__" if f > 0.0 else "__-INF__"
		return f
	if val is Vector2:
		var v := val as Vector2
		return {"__gd_type": "Vector2", "x": _to_json_safe(v.x), "y": _to_json_safe(v.y)}
	if val is Color:
		var c := val as Color
		return {"__gd_type": "Color", "r": _to_json_safe(c.r), "g": _to_json_safe(c.g), "b": _to_json_safe(c.b), "a": _to_json_safe(c.a)}
	if val is PackedByteArray:
		var bytes: Array[int] = []
		for b: int in val as PackedByteArray:
			bytes.append(b)
		return {"__gd_type": "PackedByteArray", "bytes": bytes}
	if val is Array or val is PackedStringArray:
		var arr: Array = []
		for item: Variant in val:
			arr.append(_to_json_safe(item))
		return arr
	if val is Dictionary:
		var out: Dictionary = {}
		for k: Variant in (val as Dictionary).keys():
			out[str(k)] = _to_json_safe((val as Dictionary)[k])
		return out
	return val


func _write_json_file(path: String, data: Variant) -> void:
	if path.is_empty():
		return
	var fa := FileAccess.open(path, FileAccess.WRITE)
	if fa != null:
		fa.store_string(JSON.stringify(data, "\t") + "\n")
		fa.close()
