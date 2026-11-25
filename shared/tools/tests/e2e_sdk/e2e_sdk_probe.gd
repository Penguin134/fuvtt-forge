extends SceneTree

## Fu vtt Opaque-Box E2E Batch Probe for Modular Native-Plugin SDK, R2/R3 APIs & Console Mod.
## Executes inside isolated headless Godot 4.8-beta1 Mono against packaged ZIP `res://pkg`.

const _COMP_VISUAL_SCRIPT: String = "res://scenes/entities/components/comp_visual.gd"
const _COMP_PERMISSION_SCRIPT: String = "res://scenes/entities/components/comp_permission.gd"
const _COMP_UNIT_SCRIPT: String = "res://scenes/entities/components/comp_unit.gd"
const _COMP_OBSTACLE_SCRIPT: String = "res://modules/obstacle_authoring/comp_obstacle.gd"
const _COMP_SCENE_BOX_SCRIPT: String = "res://modules/scene_box/comp_scene_box.gd"
const _COMP_PORTAL_SCRIPT: String = "res://modules/portal/comp_portal.gd"
const _COMP_SIMPLE_VISION_SCRIPT: String = "res://modules/simple_fog/comp_simple_vision.gd"
const _COMP_SIMPLE_LIGHT_SCRIPT: String = "res://modules/simple_fog/comp_simple_light.gd"
const _COMP_IMAGE_FLIP_SCRIPT: String = "res://modules/image_flip/comp_image_flip.gd"
const _COMP_DRAG_SPEED_SCRIPT: String = "res://modules/drag_movement/comp_drag_speed.gd"
const _COMP_ENTITY_INK_SCRIPT: String = "res://modules/drawing/comp_entity_ink.gd"
const _COMP_AREA_SCRIPT: String = "res://modules/areas/comp_area.gd"
const _COMP_ENTITY_NOTE_SCRIPT: String = "res://scenes/candidates/entity_notes/comp_entity_note.gd"
const _COMP_RESOURCE_POOL_SCRIPT: String = "res://scenes/candidates/resource_pool/comp_resource_pool.gd"
const _COMP_ROSTER_MEMBER_SCRIPT: String = "res://modules/character_roster/comp_character_roster_member.gd"
const _COMP_BACKPACK_SCRIPT: String = "res://modules/backpack/comp_backpack.gd"
const _COMP_FOLLOW_SCRIPT: String = "res://modules/follow/comp_follow.gd"
const _COMP_INITIATIVE_SCRIPT: String = "res://scenes/candidates/initiative/components/comp_initiative.gd"

const _MAX_WORLD_BYTES: int = 32 * 1024 * 1024
const _RESERVED_LIFECYCLE_METHODS: Dictionary = {
	"_init": true,
	"configure": true,
	"is_enabled": true,
	"get_availability": true,
	"get_module_id": true,
}


class MockHost:
	extends RefCounted

	var root: Variant = null
	var cache: String = ""
	var destination: String = ""
	var file: String = ""
	var settings: Dictionary = {}
	var expected_sha256: String = ""

	var cancel_policy: String = "never"
	var _cancelled: bool = false
	var progress_log: Array[String] = []
	var warnings: Array[String] = []
	var archived_urls: Array[String] = []
	var preview_started: bool = false
	var preview_entities_count: int = 0
	var geometry_sealed: bool = false

	func _init(case_cfg: Dictionary = {}) -> void:
		var cdir: String = String(case_cfg.get("case_dir", ""))
		root = cdir.path_join("root")
		cache = cdir.path_join("cache")
		destination = cdir.path_join("dest")
		cancel_policy = String(case_cfg.get("cancel_policy", "never"))
		if cancel_policy == "immediate":
			_cancelled = true
		var opts: Variant = case_cfg.get("options", {})
		if opts is Dictionary:
			settings = (opts as Dictionary).duplicate(true)

	func cancelled() -> bool:
		return _cancelled

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
		archived_urls.append(url)
		if url.is_empty():
			return {"ok": false, "reason": "empty_url", "reference": ""}
		var ref_id: String = url.sha256_text()
		return {
			"ok": true,
			"reference": "asset://%s.png" % ref_id,
			"size": Vector2(256.0, 256.0),
			"bytes": 1024,
		}

	func begin_preview(_total: int, _bounds: Rect2) -> void:
		preview_started = true

	func preview_entity(_entity: Dictionary, _kind: String) -> void:
		preview_entities_count += 1

	func finish_geometry_preview() -> bool:
		geometry_sealed = true
		return true

	func inspect_source(path: String) -> Dictionary:
		var sha: String = FileAccess.get_sha256(path) if FileAccess.file_exists(path) else ""
		return {"ok": true, "sha256": sha, "counts": {"records": 0, "unsupported": 0}}

	func decode_source(path: String) -> Dictionary:
		var sha: String = FileAccess.get_sha256(path) if FileAccess.file_exists(path) else ""
		return {
			"ok": true,
			"document": {"source": {"sha256": sha}},
			"scene_items": [],
			"walls": [],
			"doors": [],
		}


class MockSharedAssetStore:
	extends RefCounted

	var rev_num: int = 0
	var records: Dictionary = {}
	var adopted_assets: Array[String] = []
	var shared_assets: Array[String] = []
	var write_calls: int = 0
	var open_ok: bool = true

	func current_revision() -> String:
		return "rev_%d" % rev_num

	func OpenLibrary(_global_root: String) -> String:
		return JSON.stringify({"ok": open_ok, "reason": "" if open_ok else "open_failed"})

	func ReadLibraryRecords(_global_root: String) -> Dictionary:
		return {
			"ok": true,
			"revision": current_revision(),
			"records": records.duplicate(),
		}

	func WriteLibraryRecord(
		_global_root: String,
		rec_id: String,
		expected_bytes: PackedByteArray,
		desired_bytes: PackedByteArray,
		rev: String
	) -> String:
		var current_bytes: PackedByteArray = records.get(rec_id, PackedByteArray())
		if rev != current_revision() or current_bytes != expected_bytes:
			return JSON.stringify({"ok": false, "reason": "cas_conflict"})
		write_calls += 1
		if desired_bytes.is_empty():
			records.erase(rec_id)
		else:
			records[rec_id] = desired_bytes
		rev_num += 1
		return JSON.stringify({"ok": true, "revision": current_revision()})

	func AdoptLibraryAsset(_global_root: String, _global_dest: String, sprite_ref: String) -> String:
		adopted_assets.append(sprite_ref)
		return JSON.stringify({"ok": true})

	func ShareLibraryAsset(_global_root: String, sprite_ref: String) -> String:
		shared_assets.append(sprite_ref)
		return JSON.stringify({"ok": true})

	func decode_records() -> Dictionary:
		var out: Dictionary = {}
		for k: Variant in records.keys():
			out[str(k)] = bytes_to_var(records[k] as PackedByteArray)
		return out


class CancelAfterCallsMockHost:
	extends MockHost

	var cancel_on_call: int = 0
	var _cancel_calls: int = 0

	func _init(case_cfg: Dictionary = {}) -> void:
		super._init(case_cfg)

	func cancelled() -> bool:
		_cancel_calls += 1
		if _cancelled:
			return true
		if cancel_on_call > 0 and _cancel_calls >= cancel_on_call:
			return true
		return false


func _initialize() -> void:
	call_deferred(&"_run")


func _run() -> void:
	var args: Dictionary = _parse_args(OS.get_cmdline_user_args())
	var pkg_root: String = String(args.get("pkg-root", "res://pkg")).strip_edges()
	var batch_in_path: String = String(args.get("batch-in", "")).strip_edges()
	var batch_out_path: String = String(args.get("batch-out", "")).strip_edges()

	var batch_summary: Dictionary = {
		"ok": false,
		"godot_version": Engine.get_version_info(),
		"loaded_scripts": [],
		"compile_failures": [],
		"sdk_loaded": false,
		"sdk_version": "",
		"completed_case_ids": [],
		"error": "",
	}

	if pkg_root.is_empty() or batch_in_path.is_empty() or batch_out_path.is_empty():
		batch_summary["error"] = "missing_cli_args"
		_write_json_file(batch_out_path, batch_summary)
		quit(2)
		return

	var loaded_scripts: Array[String] = []
	var compile_failures: Array[String] = []
	var gd_files: PackedStringArray = _collect_gd_files(pkg_root)
	if gd_files.is_empty():
		compile_failures.append("no_gd_files_in_pkg_root")
	for gd_path: String in gd_files:
		var res: Resource = load(gd_path)
		if res == null or not (res is Script):
			compile_failures.append("failed_to_load_gd:" + gd_path)
		else:
			loaded_scripts.append(gd_path)

	batch_summary["loaded_scripts"] = loaded_scripts
	batch_summary["compile_failures"] = compile_failures

	var sdk_path: String = pkg_root.path_join("lib/fu_sdk/v1.gd")
	var sdk_script: Script = load(sdk_path) as Script if FileAccess.file_exists(sdk_path) else null
	if sdk_script == null or not sdk_script.can_instantiate():
		batch_summary["error"] = "fu_sdk_v1_not_loadable:" + sdk_path
		_write_json_file(batch_out_path, batch_summary)
		quit(3)
		return

	batch_summary["sdk_loaded"] = true
	batch_summary["sdk_version"] = str(sdk_script.get("SDK_VERSION"))

	if not FileAccess.file_exists(batch_in_path):
		batch_summary["error"] = "batch_in_missing"
		_write_json_file(batch_out_path, batch_summary)
		quit(4)
		return

	var batch_in_var: Variant = JSON.parse_string(FileAccess.get_file_as_string(batch_in_path))
	if not (batch_in_var is Dictionary):
		batch_summary["error"] = "batch_in_invalid_json"
		_write_json_file(batch_out_path, batch_summary)
		quit(5)
		return

	var batch_in: Dictionary = batch_in_var as Dictionary
	var out_dir: String = String(batch_in.get("out_dir", "")).strip_edges()
	var cases_var: Variant = batch_in.get("cases", [])
	if not (cases_var is Array) or out_dir.is_empty():
		batch_summary["error"] = "batch_in_missing_cases_or_out_dir"
		_write_json_file(batch_out_path, batch_summary)
		quit(6)
		return

	DirAccess.make_dir_recursive_absolute(out_dir)
	var completed_ids: Array[String] = []
	for raw_case: Variant in cases_var as Array:
		if not (raw_case is Dictionary):
			continue
		var case_cfg: Dictionary = raw_case as Dictionary
		var case_id: String = String(case_cfg.get("case_id", "unknown"))
		print("=== E2E_CASE_START %s ===" % case_id)

		var case_out: Dictionary = _execute_case(pkg_root, sdk_script, case_cfg)
		var safe_out: Variant = _to_json_safe(case_out)
		_write_json_file(out_dir.path_join(case_id + ".json"), safe_out)
		completed_ids.append(case_id)

		print("=== E2E_CASE_END %s ===" % case_id)

	batch_summary["completed_case_ids"] = completed_ids
	batch_summary["ok"] = compile_failures.is_empty()
	_write_json_file(batch_out_path, batch_summary)
	quit(0 if compile_failures.is_empty() else 1)


func _execute_case(pkg_root: String, sdk_script: Script, case_cfg: Dictionary) -> Dictionary:
	var case_id: String = String(case_cfg.get("case_id", "unknown"))
	var op: String = String(case_cfg.get("op", ""))
	var raw_params: Variant = case_cfg.get("params", {})
	var params: Dictionary = _decode_special_inputs(raw_params) as Dictionary if raw_params is Dictionary else {}
	var raw_opts: Variant = case_cfg.get("options", {})
	var options: Dictionary = _decode_special_inputs(raw_opts) as Dictionary if raw_opts is Dictionary else {}
	var enabled_modules: Array = case_cfg.get("enabled_modules", []) as Array if case_cfg.get("enabled_modules") is Array else []
	var disabled_policy: String = String(case_cfg.get("disabled_policy", "preserve"))

	var gd_failures: Array[String] = []
	var host := MockHost.new(case_cfg)
	var sdk: RefCounted = sdk_script.new()
	var data: Dictionary = {}
	var ok: bool = false

	match op:
		"baseline_v13":
			ok = _op_baseline_v13(sdk, sdk_script, host, options, data, gd_failures)
		"logbus_test":
			ok = _op_logbus_test(pkg_root, sdk, host, options, params, data, gd_failures)
		"registry_inspect":
			ok = _op_registry_inspect(pkg_root, sdk, host, options, enabled_modules, disabled_policy, params, data, gd_failures)
		"parked_manual":
			ok = _op_parked_manual(sdk, host, options, enabled_modules, disabled_policy, params, data, gd_failures)
		"plugin_lifecycle":
			ok = _op_plugin_lifecycle(pkg_root, sdk, host, options, enabled_modules, disabled_policy, params, data, gd_failures)
		"plugin_domain":
			ok = _op_plugin_domain(pkg_root, sdk, host, options, enabled_modules, disabled_policy, params, data, gd_failures)
		"conflict_matrix":
			ok = _op_conflict_matrix(pkg_root, sdk, host, options, enabled_modules, disabled_policy, params, data, gd_failures)
		"world_quota":
			ok = _op_world_quota(sdk, host, options, params, data, gd_failures)
		"console_mod_probe":
			ok = _op_console_mod_probe(pkg_root, host, options, params, data, gd_failures)
		"scenario_run":
			ok = _op_scenario_run(pkg_root, sdk, host, options, enabled_modules, disabled_policy, params, data, gd_failures)
		_:
			gd_failures.append("unknown_probe_op:" + op)

	data["host_warnings"] = host.warnings.duplicate()
	data["host_progress"] = host.progress_log.duplicate()
	host = null
	sdk = null

	return {
		"case_id": case_id,
		"ok": ok and gd_failures.is_empty(),
		"data": data,
		"gd_check_failures": gd_failures,
	}


func _new_builder(sdk: RefCounted, host: MockHost, options: Dictionary, enabled_modules: Array, disabled_policy: String, gd_failures: Array[String]) -> Dictionary:
	var session: Variant = sdk.call("create_session", host, options)
	var builder: Variant = sdk.call("create_world_builder", session, 150.0)
	var init_res: Dictionary = builder.call("setup", session, 150.0)
	if not bool(init_res.get("ok", false)):
		gd_failures.append("builder_setup_failed:" + str(init_res))
	if not enabled_modules.is_empty():
		if not (builder as Object).has_method("set_enabled_modules"):
			gd_failures.append("missing_world_builder_method:set_enabled_modules")
		else:
			builder.call("set_enabled_modules", enabled_modules)
	if disabled_policy != "preserve":
		if not (builder as Object).has_method("set_disabled_module_policy"):
			gd_failures.append("missing_world_builder_method:set_disabled_module_policy")
		else:
			builder.call("set_disabled_module_policy", disabled_policy)
	return {"session": session, "builder": builder}


func _op_baseline_v13(sdk: RefCounted, sdk_script: Script, host: MockHost, options: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var session: Variant = sdk.call("create_session", host, options)
	var builder: Variant = sdk.call("create_world_builder", session, 150.0)
	var f2: String = str(builder.call("add_floor", "2F", Color.WHITE, false))
	var tok: String = str(builder.call("add_token", "hero_1", "Hero", Vector2(150.0, 150.0), Vector2(150.0, 150.0), ""))
	var res: Dictionary = builder.call("build_result", 1, 0)
	var world: Dictionary = res.get("world", {})
	var roundtrip_diff: String = _roundtrip_world(world, data, gd_failures)
	data["sdk_version"] = str(sdk_script.get("SDK_VERSION"))
	data["floor2_uid"] = f2
	data["token_id"] = tok
	data["roundtrip_diff"] = roundtrip_diff
	data["world"] = world
	return bool(res.get("ok", false)) and roundtrip_diff.is_empty()


func _op_logbus_test(pkg_root: String, sdk: RefCounted, host: MockHost, options: Dictionary, params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var bus_path: String = pkg_root.path_join("lib/fu_sdk/logging/log_bus.gd")
	if not FileAccess.file_exists(bus_path):
		gd_failures.append("missing_sdk_file:" + bus_path)
		return false
	if not (sdk as Object).has_method("create_logger"):
		gd_failures.append("missing_sdk_method:FuSdk.create_logger")
		return false

	var sub_op: String = String(params.get("sub_op", "basic"))
	var logger: Variant = sdk.call("create_logger")
	if logger == null:
		gd_failures.append("FuSdk.create_logger returned null")
		return false

	var lobj: Object = logger as Object
	for req_m: String in ["debug", "info", "warn", "error", "log", "set_min_level", "get_min_level", "subscribe", "unsubscribe", "get_entries", "get_warnings", "clear", "attach_import_host", "set_emit_to_engine"]:
		if not lobj.has_method(req_m):
			gd_failures.append("missing_logbus_method:" + req_m)
			return false

	# Keep engine clean during negative LogBus.error() tests
	lobj.call("set_emit_to_engine", false)

	if sub_op == "constants":
		var bus_script: Script = load(bus_path) as Script
		data["LEVEL_DEBUG"] = bus_script.get("LEVEL_DEBUG") if bus_script != null else logger.get("LEVEL_DEBUG")
		data["LEVEL_INFO"] = bus_script.get("LEVEL_INFO") if bus_script != null else logger.get("LEVEL_INFO")
		data["LEVEL_WARNING"] = bus_script.get("LEVEL_WARNING") if bus_script != null else logger.get("LEVEL_WARNING")
		data["LEVEL_ERROR"] = bus_script.get("LEVEL_ERROR") if bus_script != null else logger.get("LEVEL_ERROR")
		return true

	if sub_op == "emit_and_schema":
		lobj.call("debug", "mod.a", "dbg msg", {"k": 1})
		lobj.call("info", "mod.a", "info msg", {})
		lobj.call("warn", "mod.b", "warn msg", {"module_id": "portal"})
		lobj.call("error", "mod.c", "err msg", {"code": 500})
		lobj.call("log", 20, "mod.d", "direct log", {"direct": true})
		data["entries"] = lobj.call("get_entries", 0, 0, 0)
		data["warnings"] = lobj.call("get_warnings", 0)
		return true

	if sub_op == "query_and_clear":
		lobj.call("debug", "s1", "d1", {})
		lobj.call("info", "s1", "i1", {})
		lobj.call("warn", "s2", "w1", {})
		lobj.call("error", "s3", "e1", {})
		var all_entries: Array = lobj.call("get_entries", 0, 0, 0)
		var first_seq: int = int((all_entries[0] as Dictionary).get("seq", 0)) if not all_entries.is_empty() else 0
		data["all_count"] = all_entries.size()
		data["warn_and_above"] = lobj.call("get_entries", 30, 0, 0)
		data["since_first"] = lobj.call("get_entries", 0, first_seq, 0)
		data["limited_2"] = lobj.call("get_entries", 0, 0, 2)
		data["warnings_since"] = lobj.call("get_warnings", first_seq)
		lobj.call("clear")
		data["after_clear_count"] = (lobj.call("get_entries", 0, 0, 0) as Array).size()
		return true

	if sub_op == "pubsub":
		var received_a: Array = []
		var received_b: Array = []
		var tok_a: int = int(lobj.call("subscribe", func(entry: Dictionary) -> void: received_a.append(entry)))
		var tok_b: int = int(lobj.call("subscribe", func(entry: Dictionary) -> void: received_b.append(entry)))
		lobj.call("info", "pub", "first", {})
		var unsub_ok: bool = bool(lobj.call("unsubscribe", tok_a))
		var unsub_again: bool = bool(lobj.call("unsubscribe", tok_a))
		var unsub_bad: bool = bool(lobj.call("unsubscribe", -999))
		lobj.call("warn", "pub", "second", {})
		data["tok_a"] = tok_a
		data["tok_b"] = tok_b
		data["unsub_ok"] = unsub_ok
		data["unsub_again"] = unsub_again
		data["unsub_bad"] = unsub_bad
		data["received_a"] = received_a
		data["received_b"] = received_b
		return true

	if sub_op == "session_builder_host":
		var session: Variant = sdk.call("create_session", host, options)
		var builder: Variant = sdk.call("create_world_builder", session, 150.0)
		if not (session as Object).has_method("get_logger"):
			gd_failures.append("missing_method:ImportSession.get_logger")
			return false
		if not (builder as Object).has_method("get_logger"):
			gd_failures.append("missing_method:WorldBuilder.get_logger")
			return false
		var slog: Object = session.call("get_logger") as Object
		var blog: Object = builder.call("get_logger") as Object
		if slog == null or blog == null:
			gd_failures.append("session_or_builder_logger_null")
			return false
		slog.call("set_emit_to_engine", false)
		slog.call("info", "session", "suppressed default info", {})
		data["progress_before_opt_in"] = host.progress_log.duplicate()
		data["before_forward_count"] = host.progress_log.size()
		slog.call("attach_import_host", host, true)
		slog.call("info", "session", "progress hello", {})
		slog.call("warn", "session", "warning hello", {})
		slog.call("warn", "session", "warning hello", {})
		session.call("report_progress", "direct session report")
		data["same_logger"] = (slog == blog)
		data["entries"] = blog.call("get_entries", 0, 0, 0)
		return true

	if sub_op == "min_level":
		lobj.call("set_min_level", 30)
		data["min_level"] = lobj.call("get_min_level")
		var sub_hits: Array = []
		lobj.call("subscribe", func(e: Dictionary) -> void: sub_hits.append(e))
		lobj.call("debug", "f", "skip dbg", {})
		lobj.call("info", "f", "skip info", {})
		lobj.call("warn", "f", "keep warn", {})
		lobj.call("error", "f", "keep err", {})
		data["entries"] = lobj.call("get_entries", 0, 0, 0)
		data["sub_hits"] = sub_hits
		return true

	if sub_op == "ring_buffer_overflow":
		var total: int = int(params.get("count", 1500))
		for i: int in range(total):
			lobj.call("debug", "stress", "entry_%d" % i, {"i": i})
		var entries: Array = lobj.call("get_entries", 0, 0, 0)
		data["returned_count"] = entries.size()
		data["first_seq"] = int((entries[0] as Dictionary).get("seq", 0)) if not entries.is_empty() else 0
		data["last_seq"] = int((entries[entries.size() - 1] as Dictionary).get("seq", 0)) if not entries.is_empty() else 0
		return entries.size() > 0 and entries.size() <= total

	if sub_op == "host_cap_100_7000":
		lobj.call("attach_import_host", host)
		var pad: String = "x".repeat(200)
		for i: int in range(125):
			lobj.call("warn", "cap", "warn_%03d_%s" % [i, pad], {})
		var all_e: Array = lobj.call("get_entries", 0, 0, 0)
		var total_warn_chars: int = 0
		for w: String in host.warnings:
			total_warn_chars += w.length()
		data["bus_count"] = all_e.size()
		data["host_warn_count"] = host.warnings.size()
		data["host_warn_total_chars"] = total_warn_chars
		return all_e.size() == 125

	gd_failures.append("unknown_logbus_sub_op:" + sub_op)
	return false


func _op_registry_inspect(
	pkg_root: String,
	sdk: RefCounted,
	host: MockHost,
	options: Dictionary,
	enabled_modules: Array,
	disabled_policy: String,
	params: Dictionary,
	data: Dictionary,
	gd_failures: Array[String]
) -> bool:
	var reg_path: String = pkg_root.path_join("lib/fu_sdk/plugins/module_registry.gd")
	if not FileAccess.file_exists(reg_path):
		gd_failures.append("missing_sdk_file:" + reg_path)
		return false
	var ctx: Dictionary = _new_builder(sdk, host, options, enabled_modules, disabled_policy, gd_failures)
	if not gd_failures.is_empty():
		return false
	var builder: Object = ctx["builder"] as Object
	if not builder.has_method("get_module_registry"):
		gd_failures.append("missing_world_builder_method:get_module_registry")
		return false
	var reg: Variant = builder.call("get_module_registry")
	if reg == null:
		gd_failures.append("get_module_registry returned null")
		return false
	var robj: Object = reg as Object

	var action: String = String(params.get("action", "catalog"))
	if action == "catalog":
		var query_ids: Array = params.get("query_ids", []) as Array if params.get("query_ids") is Array else []
		var avail_map: Dictionary = {}
		var enabled_map: Dictionary = {}
		var sdk_present_map: Dictionary = {}
		for raw_id: Variant in query_ids:
			var mid: String = String(raw_id)
			var psdk: Variant = builder.call("get_plugin_sdk", mid) if builder.has_method("get_plugin_sdk") else null
			sdk_present_map[mid] = (psdk != null)
			enabled_map[mid] = builder.call("is_module_enabled", mid) if builder.has_method("is_module_enabled") else false
			if psdk != null and (psdk as Object).has_method("get_availability"):
				avail_map[mid] = (psdk as Object).call("get_availability")
			elif robj.has_method("get_module_entry"):
				avail_map[mid] = robj.call("get_module_entry", mid)
			elif robj.has_method("get_availability"):
				avail_map[mid] = robj.call("get_availability", mid)
			elif robj.has_method("get_module_availability"):
				avail_map[mid] = robj.call("get_module_availability", mid)
		var listed: Variant = robj.call("list_modules", true) if robj.has_method("list_modules") else []
		data["avail_map"] = avail_map
		data["enabled_map"] = enabled_map
		data["sdk_present_map"] = sdk_present_map
		data["listed_modules"] = listed
		data["world"] = builder.call("get_world")
		return true

	if action == "toggle_and_disable_core":
		var core_id: String = String(params.get("core_id", "feature_networking"))
		var opt_id: String = String(params.get("opt_id", "backpack"))
		var res_core_off: Variant = builder.call("set_module_enabled", core_id, false) if builder.has_method("set_module_enabled") else null
		var core_still_on: bool = bool(builder.call("is_module_enabled", core_id)) if builder.has_method("is_module_enabled") else false
		var res_opt_on: Variant = builder.call("set_module_enabled", opt_id, true) if builder.has_method("set_module_enabled") else null
		var opt_on: bool = bool(builder.call("is_module_enabled", opt_id)) if builder.has_method("is_module_enabled") else false
		data["res_core_off"] = res_core_off
		data["core_still_on"] = core_still_on
		data["res_opt_on"] = res_opt_on
		data["opt_on"] = opt_on
		return true

	if action == "invalid_policy_and_unknown":
		var bad_pol: Variant = builder.call("set_disabled_module_policy", "bogus_policy") if builder.has_method("set_disabled_module_policy") else null
		var unknown_sdk: Variant = builder.call("get_plugin_sdk", "nonexistent_mod_xyz") if builder.has_method("get_plugin_sdk") else "MISSING_METHOD"
		var unknown_avail: Variant = robj.call("get_module_entry", "nonexistent_mod_xyz") if robj.has_method("get_module_entry") else {}
		var unknown_status: String = str(robj.call("get_module_status", "nonexistent_mod_xyz")) if robj.has_method("get_module_status") else ""
		data["bad_policy_res"] = bad_pol
		data["unknown_sdk_is_null"] = (unknown_sdk == null)
		data["unknown_avail"] = unknown_avail
		data["unknown_status"] = unknown_status
		return true

	if action == "stateless_optional_no_world_write":
		var query_ids_so: Array = params.get("query_ids", []) as Array if params.get("query_ids") is Array else []
		var enabled_map_so: Dictionary = {}
		var sdk_is_null_map_so: Dictionary = {}
		var avail_map_so: Dictionary = {}
		for raw_id: Variant in query_ids_so:
			var mid: String = String(raw_id)
			enabled_map_so[mid] = builder.call("is_module_enabled", mid) if builder.has_method("is_module_enabled") else false
			var psdk_so: Variant = builder.call("get_plugin_sdk", mid) if builder.has_method("get_plugin_sdk") else "MISSING_METHOD"
			sdk_is_null_map_so[mid] = (psdk_so == null)
			avail_map_so[mid] = robj.call("get_module_entry", mid) if robj.has_method("get_module_entry") else {}
		var world_so: Dictionary = builder.call("get_world")
		data["enabled_map"] = enabled_map_so
		data["sdk_is_null_map"] = sdk_is_null_map_so
		data["avail_map"] = avail_map_so
		data["world"] = world_so
		data["roundtrip_diff"] = _roundtrip_world(world_so, data, gd_failures)
		return true

	if action == "stateless_get_plugin_sdk":
		var query_ids_sg: Array = params.get("query_ids", []) as Array if params.get("query_ids") is Array else []
		var sdk_is_null_map_sg: Dictionary = {}
		var sdk_create_is_null_map_sg: Dictionary = {}
		var avail_map_sg: Dictionary = {}
		for raw_id: Variant in query_ids_sg:
			var mid: String = String(raw_id)
			var psdk_sg: Variant = builder.call("get_plugin_sdk", mid) if builder.has_method("get_plugin_sdk") else "MISSING_METHOD"
			var created_sg: Variant = sdk.call("create_plugin_sdk", mid, builder) if (sdk as Object).has_method("create_plugin_sdk") else "MISSING_METHOD"
			sdk_is_null_map_sg[mid] = (psdk_sg == null)
			sdk_create_is_null_map_sg[mid] = (created_sg == null)
			avail_map_sg[mid] = robj.call("get_module_entry", mid) if robj.has_method("get_module_entry") else {}
		data["sdk_is_null_map"] = sdk_is_null_map_sg
		data["sdk_create_is_null_map"] = sdk_create_is_null_map_sg
		data["avail_map"] = avail_map_sg
		return true

	if action == "policy_switch_mid_session":
		var session: Object = ctx["session"] as Object
		var blog: Object = builder.call("get_logger") as Object if builder.has_method("get_logger") else null
		if blog != null:
			blog.call("set_emit_to_engine", false)
		builder.call("set_disabled_module_policy", "skip")
		var psdk_grid: Object = builder.call("get_plugin_sdk", "grid_alignment") as Object
		var r1: Variant = _invoke_plugin_domain(psdk_grid, builder, "grid_alignment", "configure", {"cell_size": 64.0}, gd_failures)
		builder.call("set_disabled_module_policy", "preserve")
		var r2: Variant = _invoke_plugin_domain(psdk_grid, builder, "grid_alignment", "configure", {"cell_size": 64.0}, gd_failures)
		var world: Dictionary = builder.call("get_world")
		data["r1"] = r1
		data["r2"] = r2
		data["world"] = world
		data["log_entries"] = blog.call("get_entries", 0, 0, 0) if blog != null else []
		data["roundtrip_diff"] = _roundtrip_world(world, data, gd_failures)
		return true

	gd_failures.append("unknown_registry_action:" + action)
	return false


func _builder_attach_supports_manual(builder: Object) -> bool:
	for m: Dictionary in builder.get_method_list():
		if String(m.get("name", "")) == "attach_component":
			var args: Array = m.get("args", []) as Array
			return args.size() >= 5
	return false


func _attach_comp_with_flags(builder: Object, entity_id: String, script_path: String, state: Dictionary, parked: bool, manual: bool, gd_failures: Array[String]) -> bool:
	if builder.has_method("park_component") and parked:
		return bool(builder.call("park_component", entity_id, script_path, state, manual))
	if _builder_attach_supports_manual(builder):
		return bool(builder.call("attach_component", entity_id, script_path, state, parked, manual))
	gd_failures.append("missing_manual_park_support:attach_component_5th_arg_or_park_component")
	return false


func _op_parked_manual(
	sdk: RefCounted,
	host: MockHost,
	options: Dictionary,
	enabled_modules: Array,
	disabled_policy: String,
	params: Dictionary,
	data: Dictionary,
	gd_failures: Array[String]
) -> bool:
	var ctx: Dictionary = _new_builder(sdk, host, options, enabled_modules, disabled_policy, gd_failures)
	if not gd_failures.is_empty():
		return false
	var builder: Object = ctx["builder"] as Object
	var sub_op: String = String(params.get("sub_op", "valid"))
	var tok_id: String = str(builder.call("add_token", "p_tok", "Hero", Vector2(100, 100), Vector2(64, 64), ""))

	if sub_op == "unparked":
		var ok_u: bool = bool(builder.call("attach_component", tok_id, _COMP_AREA_SCRIPT, {"removed": false, "radius_in_cells": 2.0}, false))
		var world_u: Dictionary = builder.call("get_world")
		data["attached"] = ok_u
		data["world"] = world_u
		data["roundtrip_diff"] = _roundtrip_world(world_u, data, gd_failures)
		return ok_u

	if sub_op == "parked_auto":
		var ok_pa: bool = _attach_comp_with_flags(builder, tok_id, _COMP_AREA_SCRIPT, {"removed": false, "radius_in_cells": 2.0}, true, false, gd_failures)
		var world_pa: Dictionary = builder.call("get_world")
		data["attached"] = ok_pa
		data["world"] = world_pa
		data["roundtrip_diff"] = _roundtrip_world(world_pa, data, gd_failures)
		return ok_pa

	if sub_op == "parked_manual":
		var ok_pm: bool = _attach_comp_with_flags(builder, tok_id, _COMP_AREA_SCRIPT, {"removed": false, "radius_in_cells": 3.0}, true, true, gd_failures)
		var world_pm: Dictionary = builder.call("get_world")
		data["attached"] = ok_pm
		data["world"] = world_pm
		data["roundtrip_diff"] = _roundtrip_world(world_pm, data, gd_failures)
		return ok_pm

	if sub_op == "manual_without_parked":
		if not _builder_attach_supports_manual(builder):
			gd_failures.append("missing_manual_park_support:attach_component_5th_arg")
			return false
		var ok_bad: bool = bool(builder.call("attach_component", tok_id, _COMP_AREA_SCRIPT, {"removed": false, "radius_in_cells": 2.0}, false, true))
		var world_bad: Dictionary = builder.call("get_world")
		data["attached"] = ok_bad
		data["world"] = world_bad
		data["roundtrip_diff"] = _roundtrip_world(world_bad, data, gd_failures)
		return true

	if sub_op == "park_required_rejected":
		var ok_vis: bool = _attach_comp_with_flags(builder, tok_id, _COMP_VISUAL_SCRIPT, {}, true, false, gd_failures)
		var ok_perm: bool = _attach_comp_with_flags(builder, tok_id, _COMP_PERMISSION_SCRIPT, {}, true, false, gd_failures)
		var world_r: Dictionary = builder.call("get_world")
		data["ok_vis"] = ok_vis
		data["ok_perm"] = ok_perm
		data["world"] = world_r
		return true

	if sub_op == "park_missing_entity_or_empty_script":
		var ok_missing: bool = _attach_comp_with_flags(builder, "nonexistent_ent_999", _COMP_AREA_SCRIPT, {}, true, true, gd_failures)
		var ok_empty: bool = _attach_comp_with_flags(builder, tok_id, "", {}, true, false, gd_failures)
		data["ok_missing"] = ok_missing
		data["ok_empty"] = ok_empty
		return true

	if sub_op == "multi_parked":
		var ok1: bool = _attach_comp_with_flags(builder, tok_id, _COMP_AREA_SCRIPT, {"removed": false, "radius_in_cells": 1.0}, true, false, gd_failures)
		var ok2: bool = _attach_comp_with_flags(builder, tok_id, _COMP_PORTAL_SCRIPT, {"pair_key": "0123456789abcdef0123456789abcdef"}, true, true, gd_failures)
		var ok3: bool = _attach_comp_with_flags(builder, tok_id, _COMP_FOLLOW_SCRIPT, {"target_id": "", "controller_id": "p1", "engaged": false, "follow_distance": 16.0}, true, false, gd_failures)
		var world_m: Dictionary = builder.call("get_world")
		data["oks"] = [ok1, ok2, ok3]
		data["world"] = world_m
		data["roundtrip_diff"] = _roundtrip_world(world_m, data, gd_failures)
		return ok1 and ok2 and ok3

	gd_failures.append("unknown_parked_sub_op:" + sub_op)
	return false


func _require_plugin_sdk(pkg_root: String, builder: Object, module_id: String, gd_failures: Array[String]) -> Object:
	var ppath: String = pkg_root.path_join("lib/fu_sdk/plugins").path_join(module_id + ".gd")
	if not FileAccess.file_exists(ppath):
		gd_failures.append("missing_plugin_script:" + ppath)
		return null
	if not builder.has_method("get_plugin_sdk"):
		gd_failures.append("missing_world_builder_method:get_plugin_sdk")
		return null
	var psdk_var: Variant = builder.call("get_plugin_sdk", module_id)
	if psdk_var == null or not (psdk_var is Object):
		gd_failures.append("null_plugin_sdk:" + module_id)
		return null
	var psdk: Object = psdk_var as Object
	if str(psdk.get("MODULE_ID")) != module_id:
		gd_failures.append("module_id_mismatch:%s!=%s" % [str(psdk.get("MODULE_ID")), module_id])
	for m: String in ["configure", "is_enabled", "get_availability"]:
		if not psdk.has_method(m):
			gd_failures.append("missing_plugin_lifecycle_method:%s.%s" % [module_id, m])
	var domain_ms: Array[String] = _get_domain_methods(psdk)
	if domain_ms.is_empty():
		gd_failures.append("no_domain_methods_on_plugin_sdk:" + module_id)
	return psdk


func _get_domain_methods(psdk: Object) -> Array[String]:
	var out: Array[String] = []
	var scr: Script = psdk.get_script() as Script
	if scr == null:
		return out
	for m: Dictionary in scr.get_script_method_list():
		var mname: String = String(m.get("name", ""))
		if mname.is_empty() or mname.begins_with("_") or _RESERVED_LIFECYCLE_METHODS.has(mname):
			continue
		out.append(mname)
	return out


func _op_plugin_lifecycle(
	pkg_root: String,
	sdk: RefCounted,
	host: MockHost,
	options: Dictionary,
	enabled_modules: Array,
	disabled_policy: String,
	params: Dictionary,
	data: Dictionary,
	gd_failures: Array[String]
) -> bool:
	var ctx: Dictionary = _new_builder(sdk, host, options, enabled_modules, disabled_policy, gd_failures)
	if not gd_failures.is_empty():
		return false
	var builder: Object = ctx["builder"] as Object
	var module_id: String = String(params.get("module_id", ""))
	var psdk: Object = _require_plugin_sdk(pkg_root, builder, module_id, gd_failures)
	if psdk == null or not gd_failures.is_empty():
		return false
	data["module_id"] = str(psdk.get("MODULE_ID"))
	data["is_enabled"] = bool(psdk.call("is_enabled"))
	data["availability"] = psdk.call("get_availability")
	data["domain_methods"] = _get_domain_methods(psdk)
	return true


func _find_matching_method(psdk: Object, candidates: Array[String]) -> String:
	for name: String in candidates:
		if name.begins_with("_") or _RESERVED_LIFECYCLE_METHODS.has(name):
			continue
		if psdk.has_method(name):
			return name
	return ""


func _is_arg_type_compatible(val: Variant, expected_type: int, exact_only: bool = false) -> bool:
	if expected_type == TYPE_NIL:
		return true
	var actual_type: int = typeof(val)
	if actual_type == expected_type:
		return true
	if not exact_only and (expected_type == TYPE_INT or expected_type == TYPE_FLOAT) and (actual_type == TYPE_INT or actual_type == TYPE_FLOAT):
		return true
	return false


func _call_adaptive(psdk: Object, method_name: String, arg_variants: Array, gd_failures: Array[String]) -> Variant:
	var method_info: Dictionary = {}
	for m: Dictionary in psdk.get_method_list():
		if String(m.get("name", "")) == method_name:
			method_info = m
			break
	if method_info.is_empty():
		gd_failures.append("method_not_found_in_list:" + method_name)
		return {"ok": false, "reason": "method_not_found"}
	var args_meta: Array = method_info.get("args", []) as Array
	var total_args: int = args_meta.size()
	var def_count: int = (method_info.get("default_args", []) as Array).size()
	var min_args: int = total_args - def_count
	for exact_pass: bool in [true, false]:
		for variant: Array in arg_variants:
			if variant.size() < min_args or variant.size() > total_args:
				continue
			var types_ok: bool = true
			for idx: int in range(variant.size()):
				var exp_type: int = int((args_meta[idx] as Dictionary).get("type", TYPE_NIL))
				if not _is_arg_type_compatible(variant[idx], exp_type, exact_pass):
					types_ok = false
					break
			if types_ok:
				return psdk.callv(method_name, variant)
	gd_failures.append("incompatible_arg_types:%s.%s" % [str(psdk.get("MODULE_ID")), method_name])
	return {"ok": false, "reason": "incompatible_arg_types"}


func _call_psdk_method(psdk: Object, candidates: Array[String], arg_variants: Array, gd_failures: Array[String]) -> Variant:
	var found: String = _find_matching_method(psdk, candidates)
	if found.is_empty():
		gd_failures.append("missing_domain_method:%s.%s" % [str(psdk.get("MODULE_ID")), "/".join(candidates)])
		return null
	return _call_adaptive(psdk, found, arg_variants, gd_failures)


func _invoke_plugin_domain(
	psdk: Object,
	_builder: Object,
	module_id: String,
	action: String,
	payload: Dictionary,
	gd_failures: Array[String]
) -> Variant:
	if psdk == null:
		gd_failures.append("null_psdk_for_domain:" + module_id)
		return {"ok": false}

	# Match natural contract method names per module without accepting empty or lifecycle stubs.
	var method_map: Dictionary = {
		"portal:attach": ["attach_portal", "set_portal", "attach"],
		"grid_alignment:configure": ["configure_grid_alignment", "set_grid_alignment", "set_config", "set_state"],
		"simple_fog:configure": ["configure_fog", "configure_simple_fog", "set_fog_config", "set_config", "set_state"],
		"simple_fog:vision": ["attach_simple_vision", "attach_vision"],
		"simple_fog:light": ["attach_simple_light", "attach_light"],
		"image_flip:attach": ["attach_image_flip", "set_image_flip", "attach"],
		"drag_movement:configure": ["configure_drag_movement", "set_default_speed", "set_drag_movement", "set_config", "set_state"],
		"drag_movement:attach": ["attach_drag_speed", "set_drag_speed", "attach"],
		"drawing:configure": ["configure_drawing", "set_drawing_state", "set_strokes", "set_state"],
		"drawing:attach": ["attach_entity_ink", "set_entity_ink", "attach"],
		"areas:attach": ["attach_area", "set_area", "attach"],
		"entity_notes:attach": ["attach_entity_note", "attach_note", "set_entity_note", "attach"],
		"checklist:configure": ["configure_checklist", "set_checklist_state", "set_rows", "set_state"],
		"resource_pool:configure": ["configure_resource_pool", "set_definitions", "set_resource_pool_state", "set_state"],
		"resource_pool:attach": ["attach_resource_pool", "set_entity_resource_pool", "attach"],
		"character_roster:configure": ["configure_character_roster", "set_auto_join", "set_character_roster_state", "set_state"],
		"character_roster:attach": ["attach_character_roster_member", "attach_roster_member", "attach"],
		"backpack:attach": ["attach_backpack", "set_backpack", "attach"],
		"follow:attach": ["attach_follow", "set_follow", "attach"],
		"candidate_initiative:configure": ["configure_initiative", "set_initiative_state", "set_encounter", "set_state"],
		"candidate_initiative:attach": ["attach_initiative", "set_entity_initiative", "attach"],
		"dice:configure": ["configure_dice", "set_dice_state", "set_workspace", "set_state"],
		"dice:validate_expression": ["validate_expression", "parse_expression", "evaluate_expression", "save_combo", "add_combo"],
		"campaign_time:configure": ["configure_campaign_time", "set_campaign_time", "set_time_state", "set_state"],
		"dnd_opportunity:configure": ["configure_dnd_opportunity", "set_dnd_opportunity", "set_opportunity_state", "set_state"],
	}
	var key: String = "%s:%s" % [module_id, action]
	var candidates: Array[String] = []
	for c: String in method_map.get(key, []):
		candidates.append(c)

	var found: String = _find_matching_method(psdk, candidates)
	if found.is_empty():
		var dm: Array[String] = _get_domain_methods(psdk)
		gd_failures.append("missing_domain_method:%s(%s) available=%s" % [module_id, action, str(dm)])
		return {"ok": false}

	var eid: String = String(payload.get("entity_id", ""))
	if action == "attach":
		var state_d: Dictionary = payload.get("state", {}) as Dictionary if payload.get("state") is Dictionary else payload
		if module_id == "portal":
			return _call_adaptive(psdk, found, [
				[eid, str(state_d.get("pair_key", ""))],
				[eid, state_d],
			], gd_failures)
		if module_id == "image_flip":
			return _call_adaptive(psdk, found, [
				[eid, bool(state_d.get("horizontal", false)), bool(state_d.get("vertical", false))],
				[eid, state_d],
			], gd_failures)
		if module_id == "areas":
			return _call_adaptive(psdk, found, [
				[eid, float(state_d.get("radius_in_cells", 1.0)), bool(state_d.get("removed", false))],
				[eid, state_d],
			], gd_failures)
		if module_id == "drag_movement":
			return _call_adaptive(psdk, found, [
				[eid, float(state_d.get("speed", 64.0))],
				[eid, state_d],
			], gd_failures)
		return _call_adaptive(psdk, found, [[eid, state_d], [eid]], gd_failures)

	if module_id == "simple_fog" and action == "vision":
		var rad_v: float = float(payload.get("radius", 400.0))
		var ang_v: float = float(payload.get("view_angle", 360.0))
		var req_l: bool = bool(payload.get("requires_light", false))
		var en_v: bool = bool(payload.get("enabled", true))
		return _call_adaptive(psdk, found, [
			[eid, rad_v, ang_v, req_l, en_v],
			[eid, rad_v, ang_v],
			[eid, payload],
		], gd_failures)

	if module_id == "simple_fog" and action == "light":
		var rad_l: float = float(payload.get("radius", 320.0))
		var ang_l: float = float(payload.get("view_angle", 120.0))
		var en_l: bool = bool(payload.get("enabled", true))
		return _call_adaptive(psdk, found, [
			[eid, rad_l, ang_l, en_l],
			[eid, rad_l, ang_l],
			[eid, payload],
		], gd_failures)

	if module_id == "dice" and action == "validate_expression":
		var raw_expr: String = String(payload.get("expr", ""))
		if found == "save_combo" or found == "add_combo":
			return _call_adaptive(psdk, found, [
				[String(payload.get("id", "0123456789abcdef01234567")), "TestCombo", raw_expr, ""],
				["TestCombo", raw_expr, ""],
				[raw_expr, false],
			], gd_failures)
		return _call_adaptive(psdk, found, [
			[raw_expr, false],
			[raw_expr],
		], gd_failures)

	var cfg_state: Dictionary = payload.get("state", payload) as Dictionary
	if module_id == "grid_alignment":
		var off_a: Array = cfg_state.get("offset", [0.0, 0.0]) as Array if cfg_state.get("offset") is Array else [0.0, 0.0]
		var col_a: Array = cfg_state.get("color", [0.5, 0.55, 0.65, 0.7]) as Array if cfg_state.get("color") is Array else [0.5, 0.55, 0.65, 0.7]
		var off_v := Vector2(float(off_a[0]), float(off_a[1]))
		var col_v := Color(float(col_a[0]), float(col_a[1]), float(col_a[2]), float(col_a[3]))
		return _call_adaptive(psdk, found, [
			[cfg_state],
			[float(cfg_state.get("cell_size", 64.0)), bool(cfg_state.get("snap_enabled", true)), off_v, col_v, float(cfg_state.get("line_width", 1.0)), float(cfg_state.get("snap_strength", 0.1))],
		], gd_failures)
	return _call_adaptive(psdk, found, [[cfg_state]], gd_failures)


func _op_plugin_domain(
	pkg_root: String,
	sdk: RefCounted,
	host: MockHost,
	options: Dictionary,
	enabled_modules: Array,
	disabled_policy: String,
	params: Dictionary,
	data: Dictionary,
	gd_failures: Array[String]
) -> bool:
	var ctx: Dictionary = _new_builder(sdk, host, options, enabled_modules, disabled_policy, gd_failures)
	if not gd_failures.is_empty():
		return false
	var builder: Object = ctx["builder"] as Object
	var session: Object = ctx["session"] as Object
	var blog: Object = builder.call("get_logger") as Object if builder.has_method("get_logger") else null
	if blog != null:
		blog.call("set_emit_to_engine", false)

	var module_id: String = String(params.get("module_id", ""))
	var psdk: Object = _require_plugin_sdk(pkg_root, builder, module_id, gd_failures)
	if psdk == null or not gd_failures.is_empty():
		return false

	var sub_op: String = String(params.get("sub_op", "happy"))
	var result_val: Variant = null

	match module_id:
		"feature_edit_mode":
			if sub_op == "attach_unit":
				var obj_id: String = str(builder.call("add_object_sprite", "obj_1", "Guard", Vector2(100, 100), Vector2(64, 64), ""))
				var att_res: Variant = psdk.call("attach_unit_marker", obj_id)
				data["raw_result"] = att_res
				result_val = bool((att_res as Dictionary).get("ok", false)) if att_res is Dictionary else bool(att_res)
				data["entity_id"] = obj_id
			elif sub_op == "add_token":
				var tok_id: String = str(builder.call("add_token", "tok_1", "Hero", Vector2(120, 120), Vector2(64, 64), ""))
				var is_u: bool = bool(psdk.call("is_unit", tok_id))
				var perm_state: Dictionary = psdk.call("make_permission_state", "", [], false, true)
				var perm_ok: bool = bool(psdk.call("set_entity_permissions", tok_id, perm_state))
				var tok_ent: Dictionary = builder.call("get_entity", tok_id)
				var val_u: Dictionary = psdk.call("validate_unit_entity", tok_ent)
				data["entity_id"] = tok_id
				data["is_unit"] = is_u
				data["perm_ok"] = perm_ok
				data["validate_unit"] = val_u
				result_val = (not tok_id.is_empty()) and is_u and perm_ok and bool(val_u.get("ok", false))
			elif sub_op == "reject_map":
				var map_id: String = str(builder.call("add_map_tile", "map_1", "Map", Vector2(0, 0), Vector2(512, 512), ""))
				var map_ent: Dictionary = builder.call("get_entity", map_id)
				if not map_ent.is_empty():
					map_ent["entity_type"] = "map"
				var psdk_res: Variant = psdk.call("attach_unit_marker", map_id)
				data["psdk_result"] = psdk_res
				data["entity_id"] = map_id
				result_val = bool((psdk_res as Dictionary).get("ok", false)) if psdk_res is Dictionary else bool(psdk_res)
			elif sub_op == "reject_unknown":
				var unk_res: Variant = psdk.call("attach_unit_marker", "missing_999")
				data["psdk_result"] = unk_res
				result_val = bool((unk_res as Dictionary).get("ok", false)) if unk_res is Dictionary else bool(unk_res)
			elif sub_op == "dup_attach":
				var obj_d: String = str(builder.call("add_object_sprite", "obj_d", "Dup", Vector2(10, 10), Vector2(64, 64), ""))
				var r1_d: Variant = psdk.call("attach_unit_marker", obj_d)
				var r2_d: Variant = psdk.call("attach_unit_marker", obj_d)
				var first_ok: bool = bool((r1_d as Dictionary).get("ok", false)) if r1_d is Dictionary else bool(r1_d)
				var second_ok: bool = bool((r2_d as Dictionary).get("ok", false)) if r2_d is Dictionary else bool(r2_d)
				data["first_ok"] = first_ok
				data["second_ok"] = second_ok
				result_val = first_ok
		"feature_floor_system":
			if sub_op == "add_and_activate":
				var f2: String = str(psdk.call("add_floor", "2F", Color(0.2, 0.4, 0.6), true))
				data["floor_uid"] = f2
				data["active_floor_uid"] = str(psdk.call("get_active_floor_uid"))
				result_val = not f2.is_empty()
			elif sub_op == "rename":
				var f_rn: String = str(psdk.call("add_floor", "Old", Color.WHITE, false))
				var rn_ok: bool = bool(psdk.call("rename_floor", f_rn, "NewFloor"))
				data["floor_uid"] = f_rn
				result_val = rn_ok
			elif sub_op == "active_membership":
				var f_act: String = str(psdk.call("add_floor", "Basement", Color.WHITE, false))
				var sw_ok: bool = bool(psdk.call("set_active_floor", f_act))
				var eid_f: String = str(builder.call("add_token", "b_tok", "Rat", Vector2(50, 50), Vector2(64, 64), ""))
				data["floor_uid"] = f_act
				data["entity_id"] = eid_f
				result_val = sw_ok and not eid_f.is_empty()
			elif sub_op == "cap_512":
				var ok_count: int = 1
				for i: int in range(511):
					if not str(psdk.call("add_floor", "F_%d" % (i + 2), Color.WHITE, false)).is_empty():
						ok_count += 1
				var overflow_f: String = str(psdk.call("add_floor", "F_513", Color.WHITE, false))
				data["ok_count"] = ok_count
				data["overflow_floor"] = overflow_f
				result_val = overflow_f.is_empty()
			elif sub_op == "unknown_floor_or_sanitize":
				var bad_act: bool = bool(psdk.call("set_active_floor", "00000000000000000000000000000000"))
				var bad_rn: bool = bool(psdk.call("rename_floor", "00000000000000000000000000000000", "X"))
				var ctrl_f: String = str(psdk.call("add_floor", "\ufeffFloor\n\t" + "A".repeat(120), Color.WHITE, false))
				var blank_f: String = str(psdk.call("add_floor", "   ", Color.WHITE, false))
				data["bad_act"] = bad_act
				data["bad_rn"] = bad_rn
				data["ctrl_f"] = ctrl_f
				data["blank_f"] = blank_f
				result_val = (not bad_act) and (not bad_rn)
		"feature_layer_stack":
			if sub_op == "add_area_layer":
				var luid: String = str(psdk.call("add_layer", "Zones", "area", "all"))
				data["layer_uid"] = luid
				result_val = not luid.is_empty()
			elif sub_op == "players_layer_viewers":
				var luid_p: String = str(psdk.call("add_layer", "GM Secret", "entity", "players", "", ["p1", "p2"], true, false, true))
				data["layer_uid"] = luid_p
				result_val = not luid_p.is_empty()
			elif sub_op == "layer_override":
				var psdk_f_ov: Object = _require_plugin_sdk(pkg_root, builder, "feature_floor_system", gd_failures)
				var f_ov: String = str(psdk_f_ov.call("add_floor", "2F", Color.WHITE, false)) if psdk_f_ov != null else ""
				var l_ov: String = str(psdk.call("add_layer", "Custom2F", "entity", "all", f_ov))
				var e_ov: String = str(builder.call("add_token", "ov_tok", "Ghost", Vector2(50, 50), Vector2(64, 64), "", 0.0, Vector2.ONE, false, 32.0, false, {}, l_ov))
				data["floor_uid"] = f_ov
				data["layer_uid"] = l_ov
				data["entity_id"] = e_ov
				result_val = not e_ov.is_empty()
			elif sub_op == "cap_256_per_floor":
				var count_l: int = 3
				for i: int in range(253):
					if not str(psdk.call("add_layer", "L_%d" % i, "area", "all")).is_empty():
						count_l += 1
				var overflow_l: String = str(psdk.call("add_layer", "L_257", "area", "all"))
				data["count_l"] = count_l
				data["overflow_l"] = overflow_l
				result_val = overflow_l.is_empty()
			elif sub_op == "cap_4096_total":
				var psdk_fl4k: Object = _require_plugin_sdk(pkg_root, builder, "feature_floor_system", gd_failures)
				if psdk_fl4k == null:
					return false
				var f0_uid: String = str(psdk_fl4k.call("get_active_floor_uid"))
				var floor_uids_4k: Array[String] = [f0_uid]
				for fi: int in range(16):
					floor_uids_4k.append(str(psdk_fl4k.call("add_floor", "F4K_%d" % (fi + 1), Color.WHITE, false)))
				# 17 floors * 3 default layers = 51 layers.
				# Add 253 on floors 0..14 (3795), 250 on floor 15, 0 on floor 16 => 4096 total.
				for f_idx: int in range(16):
					var to_add: int = 253 if f_idx < 15 else 250
					var target_fuid: String = floor_uids_4k[f_idx]
					for li: int in range(to_add):
						psdk.call("add_layer", "L_%d_%d" % [f_idx, li], "area", "all", target_fuid)
				var f16_uid: String = floor_uids_4k[16]
				var target_before: Array = psdk.call("get_floor_layers", f16_uid)
				var overflow_4k: String = str(psdk.call("add_layer", "L_4097", "area", "all", f16_uid))
				var total_4k: int = 0
				var world_4k: Dictionary = builder.call("get_world")
				for lf_row: Variant in world_4k.get("catalog", {}).get("layers", {}).get("floors", []) as Array:
					if lf_row is Dictionary:
						total_4k += ((lf_row as Dictionary).get("layers", []) as Array).size()
				data["total_layers"] = total_4k
				data["target_floor_layer_count"] = target_before.size()
				data["overflow_l"] = overflow_4k
				result_val = (total_4k == 4096) and overflow_4k.is_empty()
			elif sub_op == "bad_kind_and_access":
				var bad_kind_l: String = str(psdk.call("add_layer", "BadKind", "bogus_kind", "all"))
				var bad_access_l: String = str(psdk.call("add_layer", "BadAccess", "entity", "bogus_access"))
				data["bad_kind_l"] = bad_kind_l
				data["bad_access_l"] = bad_access_l
				result_val = bad_kind_l.is_empty() and bad_access_l.is_empty()
			elif sub_op == "players_empty_viewers":
				var players_empty: String = str(psdk.call("add_layer", "EmptyPlayers", "entity", "players", "", []))
				var ent_luid_p: String = str(psdk.call("get_layer_uid", "entity"))
				var set_access_empty_ok: bool = bool(psdk.call("set_layer_access", ent_luid_p, "players", []))
				data["players_empty"] = players_empty
				data["set_access_empty_ok"] = set_access_empty_ok
				result_val = players_empty.is_empty() and (not set_access_empty_ok)
			elif sub_op == "viewers_cap_128_and_160":
				var valid_140: Array = []
				for i: int in range(140):
					valid_140.append("v_%03d" % i)
				var capped_128_l: String = str(psdk.call("add_layer", "ManyValidViewers", "entity", "players", "", valid_140))
				var overlong_l: String = str(psdk.call("add_layer", "OverlongViewer", "entity", "players", "", ["v_ok", "x".repeat(180)]))
				data["capped_128_l"] = capped_128_l
				data["overlong_l"] = overlong_l
				result_val = (not capped_128_l.is_empty()) and (not overlong_l.is_empty())
		"feature_obstacle_authoring":
			var sq := [Vector2(-50, -50), Vector2(50, -50), Vector2(50, 50), Vector2(-50, 50)]
			if sub_op == "wall_and_air":
				var wid: String = str(psdk.call("add_wall", "w1", "Wall", Vector2(0, 0), [sq]))
				var aid: String = str(psdk.call("add_air_cutout", "a1", "Air", Vector2(100, 0), [sq]))
				data["ids"] = [wid, aid]
				result_val = (not wid.is_empty()) and (not aid.is_empty())
			elif sub_op == "door_window_glass":
				var did: String = str(psdk.call("add_door", "d1", "Door", Vector2(0, 0), [sq], true))
				var winid: String = str(psdk.call("add_window", "win1", "Win", Vector2(100, 0), [sq], false))
				var gid: String = str(psdk.call("add_glass_wall", "g1", "Glass", Vector2(200, 0), [sq]))
				data["ids"] = [did, winid, gid]
				result_val = (not did.is_empty()) and (not winid.is_empty()) and (not gid.is_empty())
			elif sub_op == "segments":
				var sw: String = str(psdk.call("add_segment_wall", "sw1", "SWall", Vector2(0, 0), Vector2(200, 0)))
				var sd: String = str(psdk.call("add_segment_door", "sd1", "SDoor", Vector2(0, 100), Vector2(200, 100)))
				var swin: String = str(psdk.call("add_segment_window", "swin1", "SWin", Vector2(0, 200), Vector2(200, 200)))
				var sg: String = str(psdk.call("add_segment_glass_wall", "sg1", "SGlass", Vector2(0, 300), Vector2(200, 300)))
				data["ids"] = [sw, sd, swin, sg]
				result_val = (not sw.is_empty()) and (not sd.is_empty()) and (not swin.is_empty()) and (not sg.is_empty())
			elif sub_op == "degenerate_or_nan":
				var degen_id: String = str(psdk.call("add_wall", "deg", "Degen", Vector2.ZERO, [[Vector2.ZERO, Vector2(10, 0)]]))
				var nan_id: String = str(psdk.call("add_segment_wall", "nanw", "NanW", Vector2(NAN, 0), Vector2(100, 0)))
				var zero_id: String = str(psdk.call("add_segment_wall", "zw", "ZeroW", Vector2(10, 10), Vector2(10, 10)))
				data["degen_id"] = degen_id
				data["nan_id"] = nan_id
				data["zero_id"] = zero_id
				result_val = degen_id.is_empty() and nan_id.is_empty() and zero_id.is_empty()
			elif sub_op == "large_1e7_or_bad_kind":
				var big_id: String = str(psdk.call("add_segment_wall", "bigw", "BigW", Vector2(1e7, 1e7), Vector2(1e7 + 200.0, 1e7)))
				data["big_id"] = big_id
				result_val = not big_id.is_empty()
			elif sub_op == "bad_kind_and_role":
				var poly_bad_id: String = str(psdk.call("add_polygon_obstacle", "badk", "BadK", Vector2.ZERO, [sq], "laser_beam"))
				var o_id: String = str(builder.call("add_object_sprite", "obs_obj", "Crate", Vector2(10, 10), Vector2(64, 64), ""))
				var attach_bad_res: Variant = psdk.call("attach_obstacle", o_id, "laser_beam")
				data["poly_bad_id"] = poly_bad_id
				data["attach_bad_res"] = attach_bad_res
				result_val = attach_bad_res is Dictionary and not bool((attach_bad_res as Dictionary).get("ok", true))
		"feature_entity_library":
			var lib_cdir: String = String(params.get("case_dir", ""))
			if lib_cdir.is_empty():
				lib_cdir = str(host.root).get_base_dir()
			var lib_root: String = lib_cdir.path_join("lib_root")
			var lib_dest: String = lib_root.path_join("sessions").path_join("import_" + "a".repeat(32))
			DirAccess.make_dir_recursive_absolute(lib_dest)
			var lib_host := MockHost.new({"case_dir": lib_cdir})
			lib_host.root = lib_root
			lib_host.destination = lib_dest
			var store := MockSharedAssetStore.new()
			var lib_w: Object = psdk.call("get_writer") as Object
			if lib_w == null:
				gd_failures.append("feature_entity_library_writer_null")
				return false
			lib_w.call("set_shared_asset_store", store, true)
			data["writer_present"] = true
			data["psdk_methods"] = _get_domain_methods(psdk)
			var valid_sprite: String = "asset://" + "a".repeat(64) + ".png"

			if sub_op == "register_unit":
				var tpl: Dictionary = psdk.call("build_template_data", "goblin_1", "Goblin", valid_sprite, Vector2(64, 64), true, Color.WHITE, "npc", "monsters", {"custom": 1})
				var reg_u: Dictionary = psdk.call("register_entries", "ns_e2e", [{"id": "goblin_1", "name": "Goblin", "folder_name": "Monsters/LowCR", "sprite_ref": valid_sprite, "size_world": Vector2(64, 64), "create_preset": false}], lib_host, session, true)
				data["can_write"] = bool(psdk.call("can_write_library", lib_host))
				data["template_keys"] = tpl.keys()
				data["reg_result"] = reg_u
				data["decoded_records"] = store.decode_records()
				data["adopted_assets"] = store.adopted_assets.duplicate()
				data["shared_assets"] = store.shared_assets.duplicate()
				result_val = bool(reg_u.get("ok", false)) and int(reg_u.get("count", 0)) == 1
			elif sub_op == "register_preset_enabled" or sub_op == "register_preset_disabled_warn":
				var p_entry := {"id": "scout_1", "name": "Scout", "folder_name": "Heroes", "sprite_ref": "asset://" + "b".repeat(64) + ".png", "vision_radius": 320.0, "vision_angle": 360.0}
				var insp: Dictionary = psdk.call("inspect_preset_components", p_entry)
				var reg_p: Dictionary = psdk.call("register_presets", "ns_e2e", [p_entry], lib_host, session)
				data["inspect_res"] = insp
				data["reg_result"] = reg_p
				data["decoded_records"] = store.decode_records()
				result_val = bool(reg_p.get("ok", false)) and int(reg_p.get("count", 0)) == 1
			elif sub_op == "template_and_validate_preset":
				var tpl_u: Dictionary = psdk.call("build_template_data", "u1", "Unit1", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", {"extra": {"v": 1}})
				var tpl_o: Dictionary = psdk.call("build_template_data", "o1", "Obj1", "", Vector2(32, 32), false, Color(0.5, 0.5, 0.5, 1.0), "prop", "props", {})
				var bad_tpl: Dictionary = psdk.call("build_template_data", "b1", "Tiny", "", Vector2(2, 2))
				var core_snap := {"snapshot": {"entities": [{"components": [{"script": _COMP_VISUAL_SCRIPT}, {"script": _COMP_PERMISSION_SCRIPT}, {"script": _COMP_UNIT_SCRIPT}]}]}}
				var dis_snap := {"snapshot": {"entities": [{"components": [{"script": _COMP_VISUAL_SCRIPT}, {"script": _COMP_PERMISSION_SCRIPT}, {"script": _COMP_SIMPLE_VISION_SCRIPT}]}]}}
				data["no_favorites_api"] = (not psdk.has_method("set_favorite")) and (not psdk.has_method("get_favorites"))
				data["tpl_unit"] = tpl_u
				data["tpl_obj"] = tpl_o
				data["bad_tpl"] = bad_tpl
				data["val_core_ok"] = psdk.call("validate_preset_components", core_snap)
				data["val_disabled_res"] = psdk.call("validate_preset_components", dis_snap)
				result_val = bool(data["no_favorites_api"])
			elif sub_op == "invalid_4gate":
				var bad_specs: Array = [
					{"tag": "wrong_parent", "root": lib_root, "dest": lib_root.path_join("other/import_" + "a".repeat(32))},
					{"tag": "missing_32hex", "root": lib_root, "dest": lib_root.path_join("sessions/import_short")},
					{"tag": "mismatched_root", "root": lib_cdir.path_join("other_root"), "dest": lib_dest},
					{"tag": "empty_root", "root": "", "dest": lib_dest},
				]
				var can_writes: Dictionary = {}
				var reg_results: Dictionary = {}
				for spec_d: Variant in bad_specs:
					var sd: Dictionary = spec_d as Dictionary
					var tag: String = String(sd["tag"])
					var bh := MockHost.new({"case_dir": lib_cdir})
					bh.root = sd["root"]
					bh.destination = sd["dest"]
					can_writes[tag] = bool(psdk.call("can_write_library", bh))
					reg_results[tag] = psdk.call("register_entries", "ns_bad", [{"id": "x", "name": "X"}], bh, session, true)
				data["can_writes"] = can_writes
				data["reg_results"] = reg_results
				data["store_record_count"] = store.records.size()
				result_val = store.records.is_empty()
			elif sub_op == "preset_multi_disabled_skip_and_preserve":
				var m_entry := {"id": "multi_p", "name": "MultiWarn", "vision_radius": 240.0, "components": [_COMP_PORTAL_SCRIPT, _COMP_AREA_SCRIPT]}
				var insp_m: Dictionary = psdk.call("inspect_preset_components", m_entry)
				builder.call("set_disabled_module_policy", "preserve")
				var reg_pres: Dictionary = psdk.call("register_presets", "ns_p", [m_entry], lib_host, session)
				var store_skip := MockSharedAssetStore.new()
				lib_w.call("set_shared_asset_store", store_skip, true)
				builder.call("set_disabled_module_policy", "skip")
				var reg_sk: Dictionary = psdk.call("register_presets", "ns_s", [m_entry], lib_host, session)
				data["inspect_res"] = insp_m
				data["reg_preserve"] = reg_pres
				data["reg_skip"] = reg_sk
				data["decoded_skip_records"] = store_skip.decode_records()
				result_val = bool(reg_pres.get("ok", false)) and bool(reg_sk.get("ok", false))
			elif sub_op == "bad_sprite_refs":
				var bad_sprites: Array = [
					{"id": "s0", "name": "Empty", "sprite_ref": "", "create_preset": false},
					{"id": "s1", "name": "User", "sprite_ref": "user://illegal.png", "create_preset": false},
					{"id": "s2", "name": "Res", "sprite_ref": "res://icon.svg", "create_preset": false},
					{"id": "s3", "name": "Short", "sprite_ref": "asset://short.png", "create_preset": false},
					{"id": "s4", "name": "Svg", "sprite_ref": "asset://" + "a".repeat(64) + ".svg", "create_preset": false},
				]
				var reg_spr: Dictionary = psdk.call("register_entries", "ns_spr", bad_sprites, lib_host, session, true)
				data["reg_result"] = reg_spr
				data["adopted_assets"] = store.adopted_assets.duplicate()
				data["decoded_records"] = store.decode_records()
				result_val = int(reg_spr.get("count", 0)) == 5 and store.adopted_assets.is_empty()
			elif sub_op == "idempotent_reregister":
				var idem_entries := [{"id": "idem_1", "name": "Idem", "folder_name": "Shared", "create_preset": false}]
				var r1_i: Dictionary = psdk.call("register_entries", "ns_idem", idem_entries, lib_host, session, true)
				data["reg_1"] = r1_i
				data["write_calls_1"] = store.write_calls
				data["rev_1"] = store.current_revision()
				data["keys_1"] = store.records.keys()
				var r2_i: Dictionary = psdk.call("register_entries", "ns_idem", idem_entries, lib_host, session, true)
				data["reg_2"] = r2_i
				data["write_calls_2"] = store.write_calls
				data["rev_2"] = store.current_revision()
				data["keys_2"] = store.records.keys()
				result_val = (store.write_calls == int(data["write_calls_1"]))
			elif sub_op == "rollback_on_cancel":
				store.records["pre_existing_001"] = var_to_bytes({"id": "pre_existing_001", "name": "Keep"})
				var rb_entries := [{"id": "rb_1", "name": "RB1", "create_preset": false}, {"id": "rb_2", "name": "RB2", "create_preset": false}]
				psdk.call("register_entries", "ns_rb", rb_entries, lib_host, session, true)
				data["count_before_rb"] = store.records.size()
				psdk.call("rollback_last_registration")
				data["keys_after_rb"] = store.records.keys()

				var store2 := MockSharedAssetStore.new()
				lib_w.call("set_shared_asset_store", store2, true)
				var chost := CancelAfterCallsMockHost.new({"case_dir": lib_cdir})
				chost.root = lib_root
				chost.destination = lib_dest
				chost.cancel_on_call = 4
				var csess: Variant = sdk.call("create_session", chost, options)
				var cancel_res: Dictionary = psdk.call("register_entries", "ns_can", [{"id": "c1", "name": "C1", "folder_name": "CancelFolder", "create_preset": false}], chost, csess, true)
				data["cancel_res"] = cancel_res
				data["cancel_write_calls"] = store2.write_calls
				data["keys_after_cancel"] = store2.records.keys()
				result_val = not bool(cancel_res.get("ok", true))
			elif sub_op == "mixed_presets_enabled_disabled":
				var e_ok := {"id": "p_ok", "name": "EnabledScout", "vision_radius": 320.0}
				var e_warn := {"id": "p_warn", "name": "DisabledPortalArea", "vision_radius": 0.0, "components": [_COMP_PORTAL_SCRIPT, _COMP_AREA_SCRIPT]}
				var reg_mix: Dictionary = psdk.call("register_presets", "ns_mix", [e_ok, e_warn], lib_host, session)
				data["reg_result"] = reg_mix
				data["decoded_records"] = store.decode_records()
				result_val = int(reg_mix.get("count", 0)) == 2
			else:
				gd_failures.append("unknown_entity_library_sub_op:" + sub_op)
		"scene_box":
			if sub_op == "scenes_v2":
				var esuid: String = str(_call_psdk_method(psdk, ["configure_entry_scene"], [["Tavern", "1F", ""]], gd_failures))
				var dsuid: String = str(_call_psdk_method(psdk, ["add_scene"], [["Crypt", "B1", Color(0.2, 0.2, 0.3), "", false]], gd_failures))
				data["entry_scene_uid"] = esuid
				data["dungeon_scene_uid"] = dsuid
				result_val = (not esuid.is_empty()) and (not dsuid.is_empty())
			elif sub_op == "scene_box_entity":
				_call_psdk_method(psdk, ["configure_entry_scene"], [["Tavern", "1F", ""]], gd_failures)
				var dsuid2: String = str(_call_psdk_method(psdk, ["add_scene"], [["Crypt", "B1", Color.WHITE, "", false]], gd_failures))
				var cov: String = "asset://%s.png" % ("a".repeat(64))
				var bid: String = str(_call_psdk_method(psdk, ["add_scene_box"], [["box_1", "Crypt Door", Vector2(100, 100), dsuid2, 1.5, cov, "visited_unlock", true, [], false, false, ""]], gd_failures))
				data["box_id"] = bid
				result_val = not bid.is_empty()
			elif sub_op == "attach_and_view":
				_call_psdk_method(psdk, ["configure_entry_scene"], [["Tavern", "1F", ""]], gd_failures)
				var dsuid3: String = str(_call_psdk_method(psdk, ["add_scene"], [["Crypt", "B1", Color.WHITE, "", false]], gd_failures))
				var prop_id: String = str(builder.call("add_object_sprite", "prop_1", "Trapdoor", Vector2(50, 50), Vector2(64, 64), ""))
				var att_res: Variant = _call_psdk_method(psdk, ["attach_scene_box"], [[prop_id, dsuid3]], gd_failures)
				var att_ok: bool = bool((att_res as Dictionary).get("ok", false)) if att_res is Dictionary else bool(att_res)
				var view_ok: bool = bool(_call_psdk_method(psdk, ["set_scene_host_view"], [[dsuid3, Vector2(200, 150), Vector2(1.2, 1.2), ""]], gd_failures))
				var cov2: String = "asset://%s.webp" % ("b".repeat(64))
				var cov_ok: bool = bool(_call_psdk_method(psdk, ["set_scene_cover_asset"], [[dsuid3, cov2]], gd_failures))
				data["entity_id"] = prop_id
				result_val = att_ok and view_ok and cov_ok
			elif sub_op == "cap_64_and_last_floor":
				_call_psdk_method(psdk, ["configure_entry_scene"], [["S0", "F0", ""]], gd_failures)
				var last_s: String = ""
				for i: int in range(1, 64):
					last_s = str(_call_psdk_method(psdk, ["add_scene"], [["S_%d" % i, "F_%d" % i, Color.WHITE, "", false]], gd_failures))
				var over_s: String = str(_call_psdk_method(psdk, ["add_scene"], [["S_64", "F_64", Color.WHITE, "", false]], gd_failures))
				var f0_list_v: Variant = _call_psdk_method(psdk, ["get_scene_floor_uids"], [[last_s]], gd_failures)
				var f0_list: Array = f0_list_v as Array if f0_list_v is Array else []
				var entry_s_uid: String = str(_call_psdk_method(psdk, ["get_entry_scene_uid"], [[]], gd_failures))
				var move_last_ok: bool = bool(_call_psdk_method(psdk, ["move_floor_to_scene"], [[f0_list[0], entry_s_uid, false]], gd_failures)) if not f0_list.is_empty() else true
				data["last_s"] = last_s
				data["over_s"] = over_s
				data["move_last_ok"] = move_last_ok
				result_val = (not last_s.is_empty()) and over_s.is_empty() and (not move_last_ok)
			elif sub_op == "clamp_and_bad_cover":
				var es4: String = str(_call_psdk_method(psdk, ["configure_entry_scene"], [["Main", "1F", "user://bad.png"]], gd_failures))
				var ds4: String = str(_call_psdk_method(psdk, ["add_scene"], [["Sub", "1F", Color.WHITE, "", false]], gd_failures))
				var small_box: String = str(_call_psdk_method(psdk, ["add_scene_box"], [["b_sm", "Small", Vector2(10, 10), ds4, 0.1]], gd_failures))
				var big_box: String = str(_call_psdk_method(psdk, ["add_scene_box"], [["b_lg", "Big", Vector2(200, 10), ds4, 20.0]], gd_failures))
				data["entry_scene_uid"] = es4
				data["small_box"] = small_box
				data["big_box"] = big_box
				result_val = (not small_box.is_empty()) and (not big_box.is_empty())
		"portal":
			if sub_op == "missing_entity":
				result_val = _invoke_plugin_domain(psdk, builder, "portal", "attach", {"entity_id": "nonexistent_portal_999", "state": {"pair_key": "missing"}}, gd_failures)
			else:
				var p1: String = str(builder.call("add_object_sprite", "p1", "StairUp", Vector2(50, 50), Vector2(64, 64), ""))
				var p2: String = str(builder.call("add_object_sprite", "p2", "StairDown", Vector2(250, 50), Vector2(64, 64), ""))
				var key_arg: String = String(params.get("pair_key", "stairs_1f_2f"))
				var r_p1: Variant = _invoke_plugin_domain(psdk, builder, "portal", "attach", {"entity_id": p1, "state": {"pair_key": key_arg}}, gd_failures)
				var r_p2: Variant = _invoke_plugin_domain(psdk, builder, "portal", "attach", {"entity_id": p2, "state": {"pair_key": key_arg}}, gd_failures)
				var ok_p1: bool = bool((r_p1 as Dictionary).get("ok", false)) if r_p1 is Dictionary else bool(r_p1)
				var ok_p2: bool = bool((r_p2 as Dictionary).get("ok", false)) if r_p2 is Dictionary else bool(r_p2)
				data["entity_ids"] = [p1, p2]
				data["raw_results"] = [r_p1, r_p2]
				result_val = [ok_p1, ok_p2]
		"grid_alignment":
			var cs: float = float(params.get("cell_size", 64.0))
			var snap_en: bool = bool(params.get("snap_enabled", true))
			var off_arr: Array = params.get("offset", [0.0, 0.0]) as Array if params.get("offset") is Array else [0.0, 0.0]
			var col_arr: Array = params.get("color", [0.5, 0.55, 0.65, 0.7]) as Array if params.get("color") is Array else [0.5, 0.55, 0.65, 0.7]
			var lw: float = float(params.get("line_width", 1.0))
			var ss: float = float(params.get("snap_strength", 0.1))
			result_val = _invoke_plugin_domain(psdk, builder, "grid_alignment", "configure", {
				"cell_size": cs,
				"snap_enabled": snap_en,
				"offset": [float(off_arr[0]), float(off_arr[1])],
				"color": [float(col_arr[0]), float(col_arr[1]), float(col_arr[2]), float(col_arr[3])],
				"line_width": lw,
				"snap_strength": ss,
			}, gd_failures)
		"simple_fog":
			if sub_op == "vision_and_light":
				var t_id: String = str(builder.call("add_token", "t_fog", "Scout", Vector2(100, 100), Vector2(64, 64), ""))
				var res_v: Variant = _invoke_plugin_domain(psdk, builder, "simple_fog", "vision", {"entity_id": t_id, "radius": float(params.get("radius", 400.0)), "view_angle": float(params.get("view_angle", 360.0))}, gd_failures)
				var ok_v: bool = bool((res_v as Dictionary).get("ok", false)) if res_v is Dictionary else bool(res_v)
				var l_id: String = ""
				var ok_l: bool = false
				if psdk.has_method("add_point_light"):
					l_id = str(psdk.call("add_point_light", "l_fog", Vector2(200, 200), 320.0, 120.0, "Torch"))
					ok_l = not l_id.is_empty()
				else:
					l_id = str(builder.call("add_object_sprite", "l_fog", "Torch", Vector2(200, 200), Vector2(32, 32), ""))
					var res_l: Variant = _invoke_plugin_domain(psdk, builder, "simple_fog", "light", {"entity_id": l_id, "radius": 320.0, "view_angle": 120.0}, gd_failures)
					ok_l = bool((res_l as Dictionary).get("ok", false)) if res_l is Dictionary else bool(res_l)
				data["token_id"] = t_id
				data["light_id"] = l_id
				data["vision_result"] = res_v
				result_val = ok_v and ok_l
			else:
				result_val = _invoke_plugin_domain(psdk, builder, "simple_fog", "configure", params.get("state", {}), gd_failures)
		"dice":
			if sub_op == "validate_live_expression":
				data["adv_res"] = _invoke_plugin_domain(psdk, builder, "dice", "validate_expression", {"expr": "adv(1d20)"}, gd_failures)
				data["dis_res"] = _invoke_plugin_domain(psdk, builder, "dice", "validate_expression", {"expr": "dis(1d20)"}, gd_failures)
				data["burst_res"] = _invoke_plugin_domain(psdk, builder, "dice", "validate_expression", {"expr": "burst(2d6)"}, gd_failures)
				result_val = data["adv_res"]
			else:
				result_val = _invoke_plugin_domain(psdk, builder, "dice", String(params.get("action", "configure")), params, gd_failures)
		_:
			# Generic per-plugin SDK domain invocation
			var act: String = String(params.get("action", "configure"))
			if act == "attach":
				var p_copy: Dictionary = params.duplicate(true)
				var eid_g: String = String(params.get("entity_id", ""))
				if eid_g.is_empty():
					var make_unit: bool = bool(params.get("as_unit", true))
					eid_g = str(builder.call("add_token" if make_unit else "add_object_sprite", "ent_1", "Actor", Vector2(100, 100), Vector2(64, 64), ""))
					if make_unit:
						builder.call("attach_unit_marker", eid_g)
				p_copy["entity_id"] = eid_g
				data["entity_id"] = eid_g
				result_val = _invoke_plugin_domain(psdk, builder, module_id, "attach", p_copy, gd_failures)
			else:
				result_val = _invoke_plugin_domain(psdk, builder, module_id, act, params, gd_failures)

	var world: Dictionary = builder.call("get_world")
	data["result"] = result_val
	data["is_enabled"] = bool(psdk.call("is_enabled"))
	data["availability"] = psdk.call("get_availability")
	data["world"] = world
	data["log_entries"] = blog.call("get_entries", 0, 0, 0) if blog != null else []
	data["roundtrip_diff"] = _roundtrip_world(world, data, gd_failures)
	return gd_failures.is_empty()


func _op_conflict_matrix(
	pkg_root: String,
	sdk: RefCounted,
	host: MockHost,
	options: Dictionary,
	enabled_modules: Array,
	disabled_policy: String,
	params: Dictionary,
	data: Dictionary,
	gd_failures: Array[String]
) -> bool:
	var ctx: Dictionary = _new_builder(sdk, host, options, enabled_modules, disabled_policy, gd_failures)
	if not gd_failures.is_empty():
		return false
	var builder: Object = ctx["builder"] as Object
	var blog: Object = builder.call("get_logger") as Object if builder.has_method("get_logger") else null
	if blog != null:
		blog.call("set_emit_to_engine", false)

	var pair: String = String(params.get("pair", ""))
	if pair == "image_flip_then_obstacle":
		var e: String = str(builder.call("add_object_sprite", "e1", "Obj", Vector2(50, 50), Vector2(64, 64), ""))
		var p_flip: Object = _require_plugin_sdk(pkg_root, builder, "image_flip", gd_failures)
		if p_flip == null:
			return false
		var first_res: Variant = _invoke_plugin_domain(p_flip, builder, "image_flip", "attach", {"entity_id": e, "state": {"horizontal": true, "vertical": false}}, gd_failures)
		var second_res: Variant = builder.call("attach_component", e, _COMP_OBSTACLE_SCRIPT, {"role": "wall", "shape_mode": "manual"}, false)
		data["first"] = first_res
		data["second"] = second_res
	elif pair == "obstacle_then_image_flip":
		var sq := [Vector2(-40, -40), Vector2(40, -40), Vector2(40, 40), Vector2(-40, 40)]
		var obs_id: String = str(builder.call("add_wall", "w1", "Wall", Vector2(0, 0), [sq]))
		var p_flip2: Object = _require_plugin_sdk(pkg_root, builder, "image_flip", gd_failures)
		if p_flip2 == null:
			return false
		var second_f: Variant = _invoke_plugin_domain(p_flip2, builder, "image_flip", "attach", {"entity_id": obs_id, "state": {"horizontal": true, "vertical": false}}, gd_failures)
		data["first"] = not obs_id.is_empty()
		data["second"] = second_f
	elif pair == "image_flip_then_area":
		var e2: String = str(builder.call("add_object_sprite", "e2", "Obj", Vector2(50, 50), Vector2(64, 64), ""))
		var pf: Object = _require_plugin_sdk(pkg_root, builder, "image_flip", gd_failures)
		var pa: Object = _require_plugin_sdk(pkg_root, builder, "areas", gd_failures)
		if pf == null or pa == null:
			return false
		data["first"] = _invoke_plugin_domain(pf, builder, "image_flip", "attach", {"entity_id": e2, "state": {"horizontal": true, "vertical": false}}, gd_failures)
		data["second"] = _invoke_plugin_domain(pa, builder, "areas", "attach", {"entity_id": e2, "state": {"removed": false, "radius_in_cells": 2.0}}, gd_failures)
	elif pair == "area_then_image_flip":
		var e3: String = str(builder.call("add_object_sprite", "e3", "Obj", Vector2(50, 50), Vector2(64, 64), ""))
		var pf2: Object = _require_plugin_sdk(pkg_root, builder, "image_flip", gd_failures)
		var pa2: Object = _require_plugin_sdk(pkg_root, builder, "areas", gd_failures)
		if pf2 == null or pa2 == null:
			return false
		data["first"] = _invoke_plugin_domain(pa2, builder, "areas", "attach", {"entity_id": e3, "state": {"removed": false, "radius_in_cells": 2.0}}, gd_failures)
		data["second"] = _invoke_plugin_domain(pf2, builder, "image_flip", "attach", {"entity_id": e3, "state": {"horizontal": true, "vertical": false}}, gd_failures)
	elif pair == "scene_box_conflicts":
		var p_sb: Object = _require_plugin_sdk(pkg_root, builder, "scene_box", gd_failures)
		if p_sb == null:
			return false
		_call_psdk_method(p_sb, ["configure_entry_scene"], [["S0", "1F", ""]], gd_failures)
		var s1: String = str(_call_psdk_method(p_sb, ["add_scene"], [["S1", "1F", Color.WHITE, "", false]], gd_failures))
		var sb_id: String = str(_call_psdk_method(p_sb, ["add_scene_box"], [["sb1", "Box", Vector2(100, 100), s1]], gd_failures))
		var target_mod: String = String(params.get("target_module", ""))
		var target_state: Dictionary = params.get("state", {}) as Dictionary if params.get("state") is Dictionary else {}
		if target_mod == "unit":
			var p_ed: Object = _require_plugin_sdk(pkg_root, builder, "feature_edit_mode", gd_failures)
			if p_ed == null:
				return false
			data["second"] = p_ed.call("attach_unit_marker", sb_id)
		elif target_mod == "portal":
			var p_por: Object = _require_plugin_sdk(pkg_root, builder, "portal", gd_failures)
			if p_por == null:
				return false
			data["second"] = _invoke_plugin_domain(p_por, builder, "portal", "attach", {"entity_id": sb_id, "state": {"pair_key": "pair_x"}}, gd_failures)
		elif target_mod == "simple_vision":
			var p_fog_v: Object = _require_plugin_sdk(pkg_root, builder, "simple_fog", gd_failures)
			if p_fog_v == null:
				return false
			data["second"] = _invoke_plugin_domain(p_fog_v, builder, "simple_fog", "vision", {"entity_id": sb_id, "radius": 300.0, "view_angle": 360.0}, gd_failures)
		elif target_mod == "simple_light":
			var p_fog_l: Object = _require_plugin_sdk(pkg_root, builder, "simple_fog", gd_failures)
			if p_fog_l == null:
				return false
			data["second"] = _invoke_plugin_domain(p_fog_l, builder, "simple_fog", "light", {"entity_id": sb_id, "radius": 300.0, "view_angle": 360.0}, gd_failures)
		elif target_mod == "obstacle":
			var p_obs: Object = _require_plugin_sdk(pkg_root, builder, "feature_obstacle_authoring", gd_failures)
			if p_obs == null:
				return false
			data["second"] = p_obs.call("attach_obstacle", sb_id, "object")
		else:
			var p_tgt: Object = _require_plugin_sdk(pkg_root, builder, target_mod, gd_failures)
			if p_tgt == null:
				return false
			data["second"] = _invoke_plugin_domain(p_tgt, builder, target_mod, "attach", {"entity_id": sb_id, "state": target_state}, gd_failures)
	elif pair == "scene_box_on_map":
		var p_sb_m: Object = _require_plugin_sdk(pkg_root, builder, "scene_box", gd_failures)
		if p_sb_m == null:
			return false
		_call_psdk_method(p_sb_m, ["configure_entry_scene"], [["S0", "1F", ""]], gd_failures)
		var s_m: String = str(_call_psdk_method(p_sb_m, ["add_scene"], [["S1", "1F", Color.WHITE, "", false]], gd_failures))
		var map_id: String = str(builder.call("add_map_tile", "m1", "Map", Vector2(0, 0), Vector2(512, 512), ""))
		var map_ent_sb: Dictionary = builder.call("get_entity", map_id)
		if not map_ent_sb.is_empty():
			map_ent_sb["entity_type"] = "map"
		data["second"] = _call_psdk_method(p_sb_m, ["attach_scene_box"], [[map_id, s_m]], gd_failures)
	elif pair == "unit_only_on_non_unit_or_map":
		var mod_u: String = String(params.get("target_module", "backpack"))
		var p_u: Object = _require_plugin_sdk(pkg_root, builder, mod_u, gd_failures)
		if p_u == null:
			return false
		var obj_id: String = str(builder.call("add_object_sprite", "obj_nu", "Chest", Vector2(10, 10), Vector2(64, 64), ""))
		var map_id2: String = str(builder.call("add_map_tile", "map_nu", "Map", Vector2(0, 0), Vector2(512, 512), ""))
		var map_ent_u: Dictionary = builder.call("get_entity", map_id2)
		if not map_ent_u.is_empty():
			map_ent_u["entity_type"] = "map"
		var st_u: Dictionary = params.get("state", {}) as Dictionary if params.get("state") is Dictionary else {}
		data["on_non_unit"] = _invoke_plugin_domain(p_u, builder, mod_u, "attach", {"entity_id": obj_id, "state": st_u}, gd_failures)
		data["on_map"] = _invoke_plugin_domain(p_u, builder, mod_u, "attach", {"entity_id": map_id2, "state": st_u}, gd_failures)
	elif pair == "initiative_on_obstacle_and_wall":
		var p_obs_i: Object = _require_plugin_sdk(pkg_root, builder, "feature_obstacle_authoring", gd_failures)
		var p_init_i: Object = _require_plugin_sdk(pkg_root, builder, "candidate_initiative", gd_failures)
		if p_obs_i == null or p_init_i == null:
			return false
		var sq_i := [Vector2(-40, -40), Vector2(40, -40), Vector2(40, 40), Vector2(-40, 40)]
		var wall_id: String = str(p_obs_i.call("add_wall", "w_init", "Wall", Vector2.ZERO, [sq_i]))
		var obj_obs: String = str(builder.call("add_object_sprite", "obj_obs", "Crate", Vector2(80, 80), Vector2(64, 64), ""))
		p_obs_i.call("attach_obstacle", obj_obs, "object")
		var init_st := {"count": 10, "modifier": 0, "active": false, "defeated": false, "rolled": false}
		data["on_wall"] = _invoke_plugin_domain(p_init_i, builder, "candidate_initiative", "attach", {"entity_id": wall_id, "state": init_st}, gd_failures)
		data["on_obstacle"] = _invoke_plugin_domain(p_init_i, builder, "candidate_initiative", "attach", {"entity_id": obj_obs, "state": init_st}, gd_failures)
	elif pair == "valid_full_unit_stack":
		var hero: String = str(builder.call("add_token", "hero_full", "Paladin", Vector2(100, 100), Vector2(64, 64), ""))
		builder.call("attach_unit_marker", hero)
		builder.call("attach_simple_vision", hero, 400.0)
		builder.call("attach_simple_light", hero, 200.0)
		for mid_req: String in ["image_flip", "drag_movement", "drawing", "resource_pool", "character_roster", "backpack", "follow", "candidate_initiative"]:
			var pm: Object = _require_plugin_sdk(pkg_root, builder, mid_req, gd_failures)
			if pm == null:
				return false
			_invoke_plugin_domain(pm, builder, mid_req, "attach", {"entity_id": hero, "state": params.get(mid_req, {})}, gd_failures)
		data["entity_id"] = hero
	else:
		gd_failures.append("unknown_conflict_pair:" + pair)
		return false

	var world: Dictionary = builder.call("get_world")
	data["world"] = world
	data["roundtrip_diff"] = _roundtrip_world(world, data, gd_failures)
	return gd_failures.is_empty()


func _op_world_quota(sdk: RefCounted, host: MockHost, options: Dictionary, params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var ctx: Dictionary = _new_builder(sdk, host, options, [], "preserve", gd_failures)
	if not gd_failures.is_empty():
		return false
	var builder: Object = ctx["builder"] as Object
	var sub_op: String = String(params.get("sub_op", "max_128_entries"))
	if sub_op == "max_128_entries":
		var ok_cnt: int = 0
		for i: int in range(128):
			if bool(builder.call("set_module_state", "custom_mod_%03d" % i, 1, {"i": i})):
				ok_cnt += 1
		var overflow_ok: bool = bool(builder.call("set_module_state", "custom_mod_128", 1, {"i": 128}))
		data["ok_count"] = ok_cnt
		data["overflow_ok"] = overflow_ok
		data["world"] = builder.call("get_world")
		return ok_cnt == 128 and (not overflow_ok)

	if sub_op == "oversized_16mib":
		var big_str: String = "A".repeat(17 * 1024 * 1024)
		var can_fit: bool = bool(builder.call("can_fit_module_state", "big_mod", 1, {"blob": big_str}))
		var set_ok: bool = bool(builder.call("set_module_state", "big_mod", 1, {"blob": big_str}))
		data["can_fit"] = can_fit
		data["set_ok"] = set_ok
		return (not can_fit) and (not set_ok)

	gd_failures.append("unknown_quota_op:" + sub_op)
	return false


func _op_console_mod_probe(pkg_root: String, host: MockHost, options: Dictionary, params: Dictionary, data: Dictionary, gd_failures: Array[String]) -> bool:
	var entry_path: String = pkg_root.path_join("entry.gd")
	if not FileAccess.file_exists(entry_path):
		gd_failures.append("missing_entry_gd:" + entry_path)
		return false
	var entry_scr: Script = load(entry_path) as Script
	if entry_scr == null or not entry_scr.can_instantiate():
		gd_failures.append("entry_not_instantiable:" + entry_path)
		return false
	var plugin: RefCounted = entry_scr.new() as RefCounted
	var sample_path: String = String(params.get("sample_path", ""))
	var inspect_res: Variant = plugin.call("inspect_import", sample_path, options.duplicate(true), host)
	var prepare_res: Variant = plugin.call("prepare_import", sample_path, options.duplicate(true), host)
	data["inspect_result"] = inspect_res
	data["prepare_result"] = prepare_res
	if prepare_res is Dictionary and bool((prepare_res as Dictionary).get("ok", false)):
		var world: Dictionary = (prepare_res as Dictionary).get("world", {})
		data["roundtrip_diff"] = _roundtrip_world(world, data, gd_failures)
	return gd_failures.is_empty()


func _op_scenario_run(
	pkg_root: String,
	sdk: RefCounted,
	host: MockHost,
	options: Dictionary,
	enabled_modules: Array,
	disabled_policy: String,
	params: Dictionary,
	data: Dictionary,
	gd_failures: Array[String]
) -> bool:
	var ctx: Dictionary = _new_builder(sdk, host, options, enabled_modules, disabled_policy, gd_failures)
	if not gd_failures.is_empty():
		return false
	var builder: Object = ctx["builder"] as Object
	var blog: Object = builder.call("get_logger") as Object if builder.has_method("get_logger") else null
	if blog != null:
		blog.call("set_emit_to_engine", false)

	var scenario: String = String(params.get("scenario", ""))
	match scenario:
		"dungeon_crawl":
			for mid: String in ["scene_box", "portal", "simple_fog", "grid_alignment", "feature_obstacle_authoring"]:
				if _require_plugin_sdk(pkg_root, builder, mid, gd_failures) == null:
					return false
			builder.configure_entry_scene("Tavern", "1F", "")
			var f2: String = str(builder.call("add_floor", "2F", Color.WHITE, false))
			var crypt: String = str(builder.call("add_scene", "Crypt", "B1", Color(0.2, 0.2, 0.3), "", false))
			builder.call("add_scene_box", "sb_crypt", "To Crypt", Vector2(300, 100), crypt)
			var p1: String = str(builder.call("add_object_sprite", "st_up", "Stairs 1F", Vector2(100, 100), Vector2(64, 64), ""))
			var l2: String = str(builder.call("get_layer_uid", "entity", f2))
			var p2: String = str(builder.call("add_object_sprite", "st_dn", "Stairs 2F", Vector2(100, 100), Vector2(64, 64), "", 0.0, Vector2.ONE, false, l2))
			builder.call("attach_portal", p1, "tavern_stairs")
			builder.call("attach_portal", p2, "tavern_stairs")
			var hero: String = str(builder.call("add_token", "hero_dc", "Ranger", Vector2(150, 150), Vector2(64, 64), ""))
			builder.call("attach_simple_vision", hero, 480.0, 360.0)
			builder.call("add_point_light", "torch_1", Vector2(200, 150), 320.0)
			var sq := [Vector2(-50, -50), Vector2(50, -50), Vector2(50, 50), Vector2(-50, 50)]
			builder.call("add_wall", "w_dc", "StoneWall", Vector2(0, 0), [sq])
			builder.call("add_door", "d_dc", "OakDoor", Vector2(120, 0), [sq], false)
			builder.call("configure_grid_alignment", 64.0, true, Vector2.ZERO, Color(0.5, 0.5, 0.5, 0.7), 1.0, 0.1)
			var pfog: Object = builder.call("get_plugin_sdk", "simple_fog") as Object
			_invoke_plugin_domain(pfog, builder, "simple_fog", "configure", params.get("fog_state", {}), gd_failures)
		"dnd5e_combat":
			for mid: String in ["backpack", "resource_pool", "character_roster", "candidate_initiative", "follow", "drag_movement", "dice"]:
				if _require_plugin_sdk(pkg_root, builder, mid, gd_failures) == null:
					return false
			var heroes: Array[String] = []
			for i: int in range(4):
				var hid: String = str(builder.call("add_token", "pc_%d" % i, "Hero_%d" % i, Vector2(100 * i, 100), Vector2(64, 64), ""))
				builder.call("attach_unit_marker", hid)
				heroes.append(hid)
			var fam: String = str(builder.call("add_token", "fam_1", "Owl", Vector2(80, 140), Vector2(32, 32), ""))
			builder.call("attach_unit_marker", fam)
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "character_roster"), builder, "character_roster", "configure", {"auto_join": true}, gd_failures)
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "drag_movement"), builder, "drag_movement", "configure", {"version": 2, "speed": 64.0}, gd_failures)
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "dice"), builder, "dice", "configure", params.get("dice_state", {}), gd_failures)
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "resource_pool"), builder, "resource_pool", "configure", params.get("pool_defs", {}), gd_failures)
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "candidate_initiative"), builder, "candidate_initiative", "configure", params.get("init_state", {}), gd_failures)
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "backpack"), builder, "backpack", "attach", {"entity_id": heroes[0], "state": params.get("backpack_state", {})}, gd_failures)
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "follow"), builder, "follow", "attach", {"entity_id": fam, "state": params.get("follow_state", {})}, gd_failures)
			data["hero_ids"] = heroes
		"playtest_migration":
			for mid: String in ["campaign_time", "dnd_opportunity", "entity_notes", "simple_fog"]:
				if _require_plugin_sdk(pkg_root, builder, mid, gd_failures) == null:
					return false
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "campaign_time"), builder, "campaign_time", "configure", params.get("campaign_time", {}), gd_failures)
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "dnd_opportunity"), builder, "dnd_opportunity", "configure", params.get("dnd_opportunity", {}), gd_failures)
			var note_ent: String = str(builder.call("add_token", "note_tok", "Signpost", Vector2(50, 50), Vector2(64, 64), ""))
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "entity_notes"), builder, "entity_notes", "attach", {"entity_id": note_ent, "state": {"schema_version": 1, "text": "Legacy note", "keep_screen_size": true, "is_pin": true}}, gd_failures)
			_attach_comp_with_flags(builder, note_ent, _COMP_AREA_SCRIPT, {"removed": false, "radius_in_cells": 2.0}, true, true, gd_failures)
		"strict_skip_audit":
			for mid: String in ["simple_fog", "portal", "campaign_time", "dnd_opportunity", "entity_notes"]:
				if _require_plugin_sdk(pkg_root, builder, mid, gd_failures) == null:
					return false
			var tok_s: String = str(builder.call("add_token", "sk_tok", "Hero", Vector2(10, 10), Vector2(64, 64), ""))
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "simple_fog"), builder, "simple_fog", "configure", params.get("fog_state", {}), gd_failures)
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "campaign_time"), builder, "campaign_time", "configure", params.get("campaign_time", {}), gd_failures)
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "dnd_opportunity"), builder, "dnd_opportunity", "configure", params.get("dnd_opportunity", {}), gd_failures)
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "entity_notes"), builder, "entity_notes", "attach", {"entity_id": tok_s, "state": {"schema_version": 1, "text": "Skipped", "keep_screen_size": true, "is_pin": true}}, gd_failures)
		"large_world_stress":
			for mid: String in ["drawing", "checklist", "areas", "image_flip"]:
				if _require_plugin_sdk(pkg_root, builder, mid, gd_failures) == null:
					return false
			var floor_uids: Array[String] = [str(builder.call("get_active_floor_uid"))]
			for fi: int in range(3):
				floor_uids.append(str(builder.call("add_floor", "Floor_%d" % (fi + 2), Color.WHITE, false)))
			for idx: int in range(300):
				var fuid: String = floor_uids[idx % floor_uids.size()]
				var luid: String = str(builder.call("get_layer_uid", "entity", fuid))
				builder.call("add_token", "ent_%03d" % idx, "NPC_%d" % idx, Vector2((idx % 20) * 150.0, (idx / 20) * 150.0), Vector2(64, 64), "", 0.0, Vector2.ONE, false, 32.0, false, {}, luid)
			builder.call("add_segment_wall", "w_1e6", "FarWall", Vector2(1e6, 1e6), Vector2(1e6 + 300.0, 1e6))
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "drawing"), builder, "drawing", "configure", params.get("drawing_state", {}), gd_failures)
			_invoke_plugin_domain(builder.call("get_plugin_sdk", "checklist"), builder, "checklist", "configure", params.get("checklist_state", {}), gd_failures)
			var big_blob := {"blob": "B".repeat(17 * 1024 * 1024)}
			data["can_fit_oversized"] = bool(builder.call("can_fit_module_state", "oversized_probe", 1, big_blob))
		"multi_floor_layer_override_areas_ink":
			var p_fl: Object = _require_plugin_sdk(pkg_root, builder, "feature_floor_system", gd_failures)
			var p_ly: Object = _require_plugin_sdk(pkg_root, builder, "feature_layer_stack", gd_failures)
			var p_ar: Object = _require_plugin_sdk(pkg_root, builder, "areas", gd_failures)
			var p_dr: Object = _require_plugin_sdk(pkg_root, builder, "drawing", gd_failures)
			if p_fl == null or p_ly == null or p_ar == null or p_dr == null:
				return false
			var f2_uid: String = str(p_fl.call("add_floor", "2F", Color.WHITE, false))
			var f3_uid: String = str(p_fl.call("add_floor", "3F", Color.WHITE, false))
			var l2_area: String = str(p_ly.call("add_layer", "AuraLayer2F", "area", "all", f2_uid))
			var l3_ink: String = str(p_ly.call("add_layer", "InkLayer3F", "entity", "all", f3_uid))
			var e_area: String = str(builder.call("add_object_sprite", "ar_ent", "Aura", Vector2(50, 50), Vector2(64, 64), "", 0.0, Vector2.ONE, false, l2_area))
			var e_ink: String = str(builder.call("add_object_sprite", "ink_ent", "PaintedProp", Vector2(150, 50), Vector2(64, 64), "", 0.0, Vector2.ONE, false, l3_ink))
			_invoke_plugin_domain(p_ar, builder, "areas", "attach", {"entity_id": e_area, "state": {"removed": false, "radius_in_cells": 3.0}}, gd_failures)
			_invoke_plugin_domain(p_dr, builder, "drawing", "attach", {"entity_id": e_ink, "state": params.get("ink_state", {"revision": "", "strokes": []})}, gd_failures)
			data["area_entity_id"] = e_area
			data["area_layer_uid"] = l2_area
			data["ink_entity_id"] = e_ink
			data["ink_layer_uid"] = l3_ink
		_:
			gd_failures.append("unknown_scenario:" + scenario)
			return false

	var world: Dictionary = builder.call("get_world")
	data["roundtrip_diff"] = _roundtrip_world(world, data, gd_failures)
	data["entity_count"] = (world.get("entity_state", {}).get("entities", []) as Array).size()
	data["floor_count"] = (world.get("catalog", {}).get("floors", []) as Array).size()
	data["log_entries"] = blog.call("get_entries", 0, 0, 0) if blog != null else []
	if not bool(params.get("omit_world_dump", false)):
		data["world"] = world
	else:
		data["module_keys"] = (world.get("modules", {}).get("entries", {}) as Dictionary).keys()
	return gd_failures.is_empty()


func _roundtrip_world(world: Dictionary, data: Dictionary, gd_failures: Array[String]) -> String:
	var encoded: PackedByteArray = var_to_bytes(world)
	data["serialized_bytes"] = encoded.size()
	if encoded.is_empty():
		gd_failures.append("var_to_bytes(world) returned empty")
		return "empty"
	if encoded.size() > _MAX_WORLD_BYTES:
		gd_failures.append("var_to_bytes(world) > 32 MiB")
		return "too_large"
	var decoded: Variant = bytes_to_var(encoded)
	if not (decoded is Dictionary):
		gd_failures.append("bytes_to_var did not restore Dictionary")
		return "not_dict"
	var diff_msg: String = _find_diff(world, decoded, "$")
	if not diff_msg.is_empty():
		gd_failures.append("var_to_bytes roundtrip mismatch: " + diff_msg)
	return diff_msg


func _find_diff(a: Variant, b: Variant, path: String) -> String:
	if typeof(a) != typeof(b):
		return "%s type mismatch (%s vs %s)" % [path, type_string(typeof(a)), type_string(typeof(b))]
	if a is Dictionary:
		var da: Dictionary = a as Dictionary
		var db: Dictionary = b as Dictionary
		if da.size() != db.size():
			return "%s dict size mismatch (%d vs %d)" % [path, da.size(), db.size()]
		for k: Variant in da.keys():
			if not db.has(k):
				return "%s missing key %s" % [path, str(k)]
			var sub: String = _find_diff(da[k], db[k], path + "." + str(k))
			if not sub.is_empty():
				return sub
		return ""
	if a is Array:
		var aa: Array = a as Array
		var ab: Array = b as Array
		if aa.size() != ab.size():
			return "%s array size mismatch (%d vs %d)" % [path, aa.size(), ab.size()]
		for i: int in range(aa.size()):
			var sub: String = _find_diff(aa[i], ab[i], "%s[%d]" % [path, i])
			if not sub.is_empty():
				return sub
		return ""
	if a is float:
		var fa: float = float(a)
		var fb: float = float(b)
		if is_nan(fa) and is_nan(fb):
			return ""
		if not is_equal_approx(fa, fb):
			return "%s float mismatch" % path
		return ""
	if a != b:
		return "%s value mismatch" % path
	return ""


func _decode_special_inputs(val: Variant) -> Variant:
	if val is Dictionary:
		var d: Dictionary = val as Dictionary
		if d.has("__gd_type"):
			var t: String = String(d.get("__gd_type", ""))
			if t == "float":
				var sv: String = String(d.get("value", "0"))
				if sv == "NaN":
					return NAN
				if sv == "Inf":
					return INF
				if sv == "-Inf":
					return -INF
			elif t == "PackedByteArray":
				var raw_b: Array = d.get("bytes", []) as Array
				var pba := PackedByteArray()
				for item: Variant in raw_b:
					pba.append(int(item) & 0xFF)
				return pba
			elif t == "Vector2":
				return Vector2(float(_decode_special_inputs(d.get("x", 0.0))), float(_decode_special_inputs(d.get("y", 0.0))))
			elif t == "Color":
				return Color(
					float(_decode_special_inputs(d.get("r", 0.0))),
					float(_decode_special_inputs(d.get("g", 0.0))),
					float(_decode_special_inputs(d.get("b", 0.0))),
					float(_decode_special_inputs(d.get("a", 1.0)))
				)
			elif t == "PackedVector2Array":
				var pv2 := PackedVector2Array()
				for pt: Variant in d.get("points", []) as Array:
					if pt is Array and (pt as Array).size() >= 2:
						pv2.append(Vector2(float(_decode_special_inputs(pt[0])), float(_decode_special_inputs(pt[1]))))
				return pv2
			elif t == "PackedFloat32Array":
				var pf32 := PackedFloat32Array()
				for v: Variant in d.get("values", []) as Array:
					pf32.append(float(_decode_special_inputs(v)))
				return pf32
			elif t == "PackedInt32Array":
				var pi32 := PackedInt32Array()
				for v: Variant in d.get("values", []) as Array:
					pi32.append(int(v))
				return pi32
		var out_d: Dictionary = {}
		for k: Variant in d.keys():
			out_d[k] = _decode_special_inputs(d[k])
		return out_d
	if val is Array:
		var out_a: Array = []
		for item: Variant in val as Array:
			out_a.append(_decode_special_inputs(item))
		return out_a
	return val


func _safe_float(v: float) -> Variant:
	if is_nan(v):
		return "__NAN__"
	if is_inf(v):
		return "__INF__" if v > 0.0 else "__-INF__"
	return v


func _to_json_safe(val: Variant) -> Variant:
	match typeof(val):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_STRING:
			return val
		TYPE_FLOAT:
			return _safe_float(float(val))
		TYPE_VECTOR2:
			var v2: Vector2 = val as Vector2
			return {"__gd_type": "Vector2", "x": _safe_float(v2.x), "y": _safe_float(v2.y)}
		TYPE_COLOR:
			var col: Color = val as Color
			return {"__gd_type": "Color", "r": _safe_float(col.r), "g": _safe_float(col.g), "b": _safe_float(col.b), "a": _safe_float(col.a)}
		TYPE_PACKED_VECTOR2_ARRAY:
			var pts: Array = []
			for pt: Vector2 in val as PackedVector2Array:
				pts.append([_safe_float(pt.x), _safe_float(pt.y)])
			return {"__gd_type": "PackedVector2Array", "points": pts}
		TYPE_PACKED_BYTE_ARRAY:
			var barray: Array = []
			for b: int in val as PackedByteArray:
				barray.append(b)
			return {"__gd_type": "PackedByteArray", "bytes": barray}
		TYPE_PACKED_STRING_ARRAY:
			var out_s: Array = []
			for s: String in val as PackedStringArray:
				out_s.append(s)
			return out_s
		TYPE_PACKED_FLOAT32_ARRAY:
			var out_f: Array = []
			for f: float in val as PackedFloat32Array:
				out_f.append(_safe_float(f))
			return out_f
		TYPE_PACKED_FLOAT64_ARRAY:
			var out_f64: Array = []
			for f64: float in val as PackedFloat64Array:
				out_f64.append(_safe_float(f64))
			return out_f64
		TYPE_PACKED_INT32_ARRAY:
			var out_i32: Array = []
			for n: int in val as PackedInt32Array:
				out_i32.append(n)
			return out_i32
		TYPE_PACKED_INT64_ARRAY:
			var out_i64: Array = []
			for n64: int in val as PackedInt64Array:
				out_i64.append(n64)
			return out_i64
		TYPE_ARRAY:
			var out_arr: Array = []
			for item: Variant in val as Array:
				out_arr.append(_to_json_safe(item))
			return out_arr
		TYPE_DICTIONARY:
			var src_d: Dictionary = val as Dictionary
			var out_d: Dictionary = {}
			for k: Variant in src_d.keys():
				out_d[str(k)] = _to_json_safe(src_d[k])
			return out_d
		_:
			return str(val)


func _collect_gd_files(root_dir: String) -> PackedStringArray:
	var out := PackedStringArray()
	var stack := PackedStringArray([root_dir])
	while not stack.is_empty():
		var current: String = stack[stack.size() - 1]
		stack.resize(stack.size() - 1)
		var dir: DirAccess = DirAccess.open(current)
		if dir == null:
			continue
		dir.list_dir_begin()
		while true:
			var name: String = dir.get_next()
			if name.is_empty():
				break
			if name in [".", ".."]:
				continue
			var child: String = current.path_join(name)
			if dir.current_is_dir():
				stack.append(child)
			elif name.ends_with(".gd"):
				out.append(child)
		dir.list_dir_end()
	out.sort()
	return out


func _parse_args(arguments: PackedStringArray) -> Dictionary:
	var out: Dictionary = {}
	for arg: String in arguments:
		if not arg.begins_with("--") or not arg.contains("="):
			continue
		var sep: int = arg.find("=")
		out[arg.substr(2, sep - 2)] = arg.substr(sep + 1)
	return out


func _write_json_file(path: String, data: Variant) -> void:
	if path.is_empty():
		return
	var f: FileAccess = FileAccess.open(path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(data, "\t") + "\n")
		f.close()
