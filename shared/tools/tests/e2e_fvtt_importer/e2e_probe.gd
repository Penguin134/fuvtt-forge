extends SceneTree

## Fu vtt Opaque-Box E2E Batch Probe for `fvtt-world-importer`.
## Runs inside isolated headless Godot 4.8-beta1 Mono against packaged ZIP `res://pkg`.

const _COMP_VISUAL_SCRIPT: String = "res://scenes/entities/components/comp_visual.gd"
const _COMP_PERMISSION_SCRIPT: String = "res://scenes/entities/components/comp_permission.gd"
const _COMP_UNIT_SCRIPT: String = "res://scenes/entities/components/comp_unit.gd"
const _COMP_SIMPLE_VISION_SCRIPT: String = "res://modules/simple_fog/comp_simple_vision.gd"
const _COMP_SIMPLE_LIGHT_SCRIPT: String = "res://modules/simple_fog/comp_simple_light.gd"

const _VALID_LAYER_KINDS: Array[String] = ["map", "entity", "obstacle", "area"]
const _VALID_ACCESS_POLICIES: Array[String] = ["all", "host", "players"]
const _OBSTACLE_KINDS: Array[String] = ["wall", "air", "door", "window", "glass"]
const _ALLOWED_ASSET_IMAGE_EXTS: Array[String] = ["png", "jpg", "jpeg", "webp", "bmp"]
const _ALLOWED_RES_IMAGE_EXTS: Array[String] = ["png", "jpg", "jpeg", "webp", "bmp", "svg"]
const _INSPECT_COUNT_KEYS: Array[String] = [
	"records",
	"images",
	"selected_images",
	"maps",
	"characters",
	"objects",
	"text",
	"drawings",
	"walls",
	"doors",
	"hidden",
	"unsupported",
]

const _MAX_FLOORS: int = 512
const _MAX_LAYERS_PER_FLOOR: int = 256
const _MAX_TOTAL_LAYERS: int = 4096
const _MAX_ENTITIES: int = 10000
const _MAX_MODULE_ENTRIES: int = 128
const _MAX_MODULE_ENTRY_BYTES: int = 6 * 1024 * 1024
const _MAX_MODULE_TOTAL_BYTES: int = 8 * 1024 * 1024
const _MAX_WORLD_BYTES: int = 32 * 1024 * 1024
const _MAX_VECTOR_VERTICES: int = 600000
const _MAX_VECTOR_PATHS: int = 8192
const _MAX_VECTOR_TOTAL_POINTS: int = 800000
const _MAX_OBSTACLE_TOTAL_POINTS: int = 200000
const _MAX_VECTOR_TEXT_LENGTH: int = 65536


class E2EHostBridge:
	extends RefCounted

	# Public ImportBridge properties (`scenes/session/plugins/import_bridge.gd`)
	var root: Variant = null
	var cache: String = ""
	var destination: String = ""
	var file: String = ""
	var settings: Dictionary = {}
	var expected_sha256: String = ""

	# Probe configuration & runtime trace
	var phase: String = "init"
	var cancel_policy: String = "never"
	var archive_policy: String = "mock_ok"
	var _cancel_triggered: bool = false

	var call_sequence: Array[String] = []
	var progress_log: Array[String] = []
	var warnings: Array[String] = []
	var archived_urls: Array[String] = []
	var archived_requests: Array[Dictionary] = []
	var preview_started: bool = false
	var preview_total: int = 0
	var preview_bounds: Rect2 = Rect2()
	var preview_entities_count: int = 0
	var geometry_sealed: bool = false

	func _init(case_cfg: Dictionary = {}) -> void:
		cache = String(case_cfg.get("cache_dir", ""))
		destination = String(case_cfg.get("destination_dir", ""))
		file = String(case_cfg.get("sample_path", ""))
		expected_sha256 = String(case_cfg.get("expected_sha256", ""))
		var s_var: Variant = case_cfg.get("settings", {})
		if s_var is Dictionary:
			settings = (s_var as Dictionary).duplicate(true)
		cancel_policy = String(case_cfg.get("cancel_policy", "never"))
		archive_policy = String(case_cfg.get("archive_policy", "mock_ok"))
		if cancel_policy == "immediate":
			_cancel_triggered = true

	func cancelled() -> bool:
		if cancel_policy == "immediate":
			return true
		if cancel_policy == "on_prepare_start" and phase == "prepare":
			_cancel_triggered = true
		return _cancel_triggered

	func report(text: String) -> void:
		call_sequence.append("report")
		progress_log.append(text)
		if cancel_policy == "on_inspect_report" and phase == "inspect":
			_cancel_triggered = true
		elif cancel_policy == "on_prepare_report" and phase == "prepare":
			_cancel_triggered = true

	func warn(text: String) -> void:
		call_sequence.append("warn")
		warnings.append(text)

	func empty_world() -> Dictionary:
		call_sequence.append("empty_world")
		if cancel_policy == "on_empty_world" and phase == "prepare":
			_cancel_triggered = true
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

	func archive_image(url: String, proxy: String = "") -> Dictionary:
		call_sequence.append("archive_image")
		archived_urls.append(url)
		if cancel_policy == "on_archive_image" and phase == "prepare":
			_cancel_triggered = true

		var clean_url: String = url.strip_edges()
		if clean_url.is_empty():
			var empty_res := {"ok": false, "reason": "empty_url", "reference": ""}
			archived_requests.append({"url": url, "proxy": proxy, "ok": false, "reason": "empty_url", "reference": ""})
			return empty_res

		var lower_url: String = clean_url.to_lower()
		var is_http: bool = lower_url.begins_with("http://") or lower_url.begins_with("https://")
		if not is_http:
			archived_requests.append({"url": url, "proxy": proxy, "ok": false, "reason": "invalid_plugin_url", "reference": ""})
			return {"ok": false, "reason": "invalid_plugin_url", "reference": ""}

		if archive_policy == "fail_all" or archive_policy == "fail_urls":
			var reason: String = "offline_blocked" if archive_policy == "fail_urls" else "source_download_failed"
			archived_requests.append({"url": url, "proxy": proxy, "ok": false, "reason": reason, "reference": ""})
			return {"ok": false, "reason": reason, "reference": ""}

		var ref_id: String = clean_url.sha256_text()
		var ref_path: String = "asset://%s.png" % ref_id
		archived_requests.append({"url": url, "proxy": proxy, "ok": true, "reason": "", "reference": ref_path})
		return {
			"ok": true,
			"reference": ref_path,
			"size": Vector2(256.0, 256.0),
			"bytes": 1024,
		}

	func begin_preview(total: int, bounds: Rect2) -> void:
		call_sequence.append("begin_preview")
		preview_started = true
		preview_total = total
		preview_bounds = bounds
		if cancel_policy == "on_begin_preview" and phase == "prepare":
			_cancel_triggered = true

	func preview_entity(_entity: Dictionary, _kind: String) -> void:
		call_sequence.append("preview_entity")
		preview_entities_count += 1
		if cancel_policy == "on_preview_entity" and phase == "prepare":
			_cancel_triggered = true

	func finish_geometry_preview() -> bool:
		call_sequence.append("finish_geometry_preview")
		if cancel_policy == "on_finish_geometry_preview" and phase == "prepare":
			_cancel_triggered = true
			return false
		geometry_sealed = true
		return true

	func inspect_source(path: String) -> Dictionary:
		call_sequence.append("inspect_source")
		var sha: String = FileAccess.get_sha256(path) if FileAccess.file_exists(path) else ""
		return {
			"ok": true,
			"sha256": sha,
			"counts": {"records": 0, "unsupported": 0},
		}

	func decode_source(path: String) -> Dictionary:
		call_sequence.append("decode_source")
		var sha: String = FileAccess.get_sha256(path) if FileAccess.file_exists(path) else ""
		return {
			"ok": true,
			"document": {"source": {"sha256": sha}},
			"scene_items": [],
			"walls": [],
			"doors": [],
		}

	func to_trace_dict() -> Dictionary:
		return {
			"call_sequence": call_sequence,
			"progress_log": progress_log,
			"warnings": warnings,
			"archived_urls": archived_urls,
			"archived_requests": archived_requests,
			"preview_started": preview_started,
			"preview_total": preview_total,
			"preview_bounds": preview_bounds,
			"preview_entities_count": preview_entities_count,
			"geometry_sealed": geometry_sealed,
			"cancel_triggered": _cancel_triggered,
		}


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
		"entry_valid": false,
		"completed_case_ids": [],
		"error": "",
	}

	if pkg_root.is_empty() or batch_in_path.is_empty() or batch_out_path.is_empty():
		batch_summary["error"] = "missing_cli_args"
		_write_json_file(batch_out_path, batch_summary)
		quit(2)
		return

	# 1. Compile check every .gd file under pkg_root
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

	# 2. Load plugin.json & entry script
	var manifest_path: String = pkg_root.path_join("plugin.json")
	var manifest_var: Variant = JSON.parse_string(FileAccess.get_file_as_string(manifest_path))
	if not (manifest_var is Dictionary):
		batch_summary["error"] = "invalid_plugin_json"
		_write_json_file(batch_out_path, batch_summary)
		quit(3)
		return

	var manifest: Dictionary = manifest_var as Dictionary
	var entry_rel: String = String(manifest.get("entry", "entry.gd"))
	var entry_script: Script = load(pkg_root.path_join(entry_rel)) as Script
	if entry_script == null or not entry_script.can_instantiate():
		batch_summary["error"] = "entry_script_not_instantiable:" + entry_rel
		_write_json_file(batch_out_path, batch_summary)
		quit(4)
		return

	var probe_obj: Variant = entry_script.new()
	var is_valid_entry: bool = (
		probe_obj is RefCounted
		and (probe_obj as RefCounted).has_method("inspect_import")
		and (probe_obj as RefCounted).has_method("prepare_import")
	)
	probe_obj = null
	batch_summary["entry_valid"] = is_valid_entry
	if not is_valid_entry:
		batch_summary["error"] = "entry_contract_invalid"
		_write_json_file(batch_out_path, batch_summary)
		quit(5)
		return

	# 3. Read batch_in.json
	if not FileAccess.file_exists(batch_in_path):
		batch_summary["error"] = "batch_in_missing:" + batch_in_path
		_write_json_file(batch_out_path, batch_summary)
		quit(6)
		return

	var batch_in_var: Variant = JSON.parse_string(FileAccess.get_file_as_string(batch_in_path))
	if not (batch_in_var is Dictionary):
		batch_summary["error"] = "batch_in_invalid_json"
		_write_json_file(batch_out_path, batch_summary)
		quit(7)
		return

	var batch_in: Dictionary = batch_in_var as Dictionary
	var out_dir: String = String(batch_in.get("out_dir", "")).strip_edges()
	var cases_var: Variant = batch_in.get("cases", [])
	if not (cases_var is Array) or out_dir.is_empty():
		batch_summary["error"] = "batch_in_missing_cases_or_out_dir"
		_write_json_file(batch_out_path, batch_summary)
		quit(8)
		return

	DirAccess.make_dir_recursive_absolute(out_dir)

	var completed_ids: Array[String] = []
	for raw_case: Variant in cases_var as Array:
		if not (raw_case is Dictionary):
			continue
		var case_cfg: Dictionary = raw_case as Dictionary
		var case_id: String = String(case_cfg.get("case_id", "unknown"))
		print("=== E2E_CASE_START %s ===" % case_id)

		var case_out: Dictionary = _execute_case(entry_script, case_cfg)
		var max_vdump: int = int(case_cfg.get("max_vertex_dump", 4096))
		var safe_out: Variant = _to_json_safe(case_out, max_vdump, "")
		var case_out_path: String = out_dir.path_join(case_id + ".json")
		_write_json_file(case_out_path, safe_out)
		completed_ids.append(case_id)

		print("=== E2E_CASE_END %s ===" % case_id)

	batch_summary["completed_case_ids"] = completed_ids
	batch_summary["ok"] = compile_failures.is_empty()
	_write_json_file(batch_out_path, batch_summary)
	quit(0 if compile_failures.is_empty() else 1)


func _execute_case(entry_script: Script, case_cfg: Dictionary) -> Dictionary:
	var case_id: String = String(case_cfg.get("case_id", "unknown"))
	var sample_path: String = String(case_cfg.get("sample_path", ""))
	var run_inspect: bool = bool(case_cfg.get("run_inspect", true))
	var run_prepare: bool = bool(case_cfg.get("run_prepare", true))
	var skip_deep_diff: bool = bool(case_cfg.get("skip_deep_diff", false))

	var raw_opts: Variant = case_cfg.get("options", {})
	var base_options: Dictionary = _decode_special_inputs(raw_opts) as Dictionary if raw_opts is Dictionary else {}

	var host := E2EHostBridge.new(case_cfg)
	var plugin_obj: RefCounted = entry_script.new() as RefCounted

	var gd_failures: Array[String] = []
	var inspect_res: Variant = null
	var prepare_res: Variant = null
	var inspect_ms: float = 0.0
	var prepare_ms: float = 0.0
	var prepare_meta: Dictionary = {
		"serialized_bytes": 0,
		"modules_var_bytes": 0,
		"modules_max_entry_var_bytes": 0,
		"modules_bounded_bytes": 0,
		"modules_max_entry_bounded_bytes": 0,
	}

	if run_inspect:
		host.phase = "inspect"
		var t0: int = Time.get_ticks_usec()
		inspect_res = plugin_obj.call("inspect_import", sample_path, base_options.duplicate(true), host)
		inspect_ms = float(Time.get_ticks_usec() - t0) / 1000.0
		if not (inspect_res is Dictionary):
			gd_failures.append("inspect_import did not return Dictionary")
		elif bool((inspect_res as Dictionary).get("ok", false)):
			_validate_inspect_ok(inspect_res as Dictionary, sample_path, gd_failures)

	if run_prepare:
		host.phase = "prepare"
		var t1: int = Time.get_ticks_usec()
		prepare_res = plugin_obj.call("prepare_import", sample_path, base_options.duplicate(true), host)
		prepare_ms = float(Time.get_ticks_usec() - t1) / 1000.0
		if not (prepare_res is Dictionary):
			gd_failures.append("prepare_import did not return Dictionary")
		elif bool((prepare_res as Dictionary).get("ok", false)):
			_validate_prepare_ok(prepare_res as Dictionary, gd_failures, prepare_meta, skip_deep_diff)

	var host_trace: Dictionary = host.to_trace_dict()
	plugin_obj = null
	host = null

	return {
		"case_id": case_id,
		"inspect_result": inspect_res,
		"prepare_result": prepare_res,
		"inspect_ms": inspect_ms,
		"prepare_ms": prepare_ms,
		"prepare_meta": prepare_meta,
		"host_trace": host_trace,
		"gd_check_failures": gd_failures,
	}


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


func _validate_inspect_ok(res: Dictionary, sample_path: String, failures: Array[String]) -> void:
	if not (res.get("name", null) is String) or String(res.get("name", "")).strip_edges().is_empty():
		failures.append("inspect_import.name must be non-empty String")
	var sha_str: String = String(res.get("sha256", ""))
	if sha_str.length() != 64:
		failures.append("inspect_import.sha256 must be 64 hex chars")
	elif FileAccess.file_exists(sample_path):
		var expected_sha: String = FileAccess.get_sha256(sample_path)
		if sha_str != expected_sha:
			failures.append("inspect_import.sha256 mismatch")

	if not (res.get("source_bytes", null) is int) or int(res.get("source_bytes", -1)) < 0:
		failures.append("inspect_import.source_bytes must be int >= 0")
	if not (res.get("decoded_bytes", null) is int) or int(res.get("decoded_bytes", -1)) < 0:
		failures.append("inspect_import.decoded_bytes must be int >= 0")
	if not (res.get("unique_images", null) is int) or int(res.get("unique_images", -1)) < 0:
		failures.append("inspect_import.unique_images must be int >= 0")
	if not (res.get("assets", null) is Dictionary):
		failures.append("inspect_import.assets must be Dictionary")

	var counts_v: Variant = res.get("counts", null)
	if not (counts_v is Dictionary):
		failures.append("inspect_import.counts must be Dictionary")
		return
	var counts: Dictionary = counts_v as Dictionary
	for req_key: String in _INSPECT_COUNT_KEYS:
		if not counts.has(req_key):
			failures.append("inspect_import.counts missing key: " + req_key)
		elif not (counts[req_key] is int) or int(counts[req_key]) < 0:
			failures.append("inspect_import.counts[%s] must be int >= 0" % req_key)


func _validate_prepare_ok(
	res: Dictionary,
	failures: Array[String],
	meta: Dictionary,
	skip_deep_diff: bool
) -> void:
	var counts_v: Variant = res.get("counts", null)
	if not (counts_v is Dictionary):
		failures.append("prepare_import.counts must be Dictionary")
	else:
		var counts: Dictionary = counts_v as Dictionary
		for req_key: String in ["entities", "assets", "source_records", "merged_walls"]:
			if not counts.has(req_key) or not (counts[req_key] is int) or int(counts[req_key]) < 0:
				failures.append("prepare_import.counts[%s] invalid" % req_key)

	var world_v: Variant = res.get("world", null)
	if not (world_v is Dictionary):
		failures.append("prepare_import.world must be Dictionary")
		return
	var world: Dictionary = world_v as Dictionary

	_validate_world_v3(world, failures, meta)

	var encoded: PackedByteArray = var_to_bytes(world)
	meta["serialized_bytes"] = encoded.size()
	if encoded.is_empty():
		failures.append("var_to_bytes(world) returned empty bytes")
	elif encoded.size() > _MAX_WORLD_BYTES:
		failures.append("var_to_bytes(world) exceeds 32 MiB limit: %d" % encoded.size())
	else:
		var decoded: Variant = bytes_to_var(encoded)
		if not (decoded is Dictionary):
			failures.append("bytes_to_var(encoded) did not restore Dictionary")
		elif not skip_deep_diff:
			var diff_msg: String = _find_diff(world, decoded, "$")
			if not diff_msg.is_empty():
				failures.append("var_to_bytes roundtrip mismatch: " + diff_msg)


func _validate_world_v3(world: Dictionary, failures: Array[String], meta: Dictionary) -> void:
	if String(world.get("format", "")) != "fus.practice.world":
		failures.append("world.format != 'fus.practice.world'")
	if not (world.get("version", null) is int) or int(world.get("version", -1)) != 3:
		failures.append("world.version != 3")

	var catalog_v: Variant = world.get("catalog", null)
	if not (catalog_v is Dictionary):
		failures.append("world.catalog is not Dictionary")
		return
	var catalog: Dictionary = catalog_v as Dictionary

	var floor_uids: Dictionary = {}
	var floors_v: Variant = catalog.get("floors", null)
	if not (floors_v is Array) or (floors_v as Array).is_empty() or (floors_v as Array).size() > _MAX_FLOORS:
		failures.append("catalog.floors must have 1..512 floors")
	else:
		for raw_f: Variant in floors_v as Array:
			if not (raw_f is Dictionary):
				failures.append("catalog.floors entry is not Dictionary")
				continue
			var f: Dictionary = raw_f as Dictionary
			var fuid: String = String(f.get("floor_uid", ""))
			if not _is_valid_uid(fuid) or floor_uids.has(fuid):
				failures.append("invalid or duplicate catalog.floors[].floor_uid: " + fuid)
			floor_uids[fuid] = true
			var fname: String = String(f.get("name", ""))
			if fname.is_empty() or fname.length() > 96 or fname != fname.strip_edges() or _has_control_chars(fname):
				failures.append("invalid floor name: " + fname)

	var active_fuid: String = String(catalog.get("active_floor_uid", ""))
	if not floor_uids.has(active_fuid):
		failures.append("active_floor_uid not found in catalog.floors: " + active_fuid)

	var layers_v: Variant = catalog.get("layers", null)
	var layer_owner: Dictionary = {}
	if not (layers_v is Dictionary):
		failures.append("catalog.layers is not Dictionary")
	else:
		var layers_root: Dictionary = layers_v as Dictionary
		if String(layers_root.get("schema", "")) != "fus.floor_layers.v2":
			failures.append("catalog.layers.schema != 'fus.floor_layers.v2'")
		var lfloors_v: Variant = layers_root.get("floors", null)
		if not (lfloors_v is Array):
			failures.append("catalog.layers.floors is not Array")
		else:
			var total_layers: int = 0
			for raw_lf: Variant in lfloors_v as Array:
				if not (raw_lf is Dictionary):
					failures.append("layers.floors entry is not Dictionary")
					continue
				var lf: Dictionary = raw_lf as Dictionary
				var lfuid: String = String(lf.get("floor_uid", ""))
				if not floor_uids.has(lfuid):
					failures.append("layers.floors floor_uid unknown: " + lfuid)
				var llist_v: Variant = lf.get("layers", null)
				if not (llist_v is Array) or (llist_v as Array).is_empty() or (llist_v as Array).size() > _MAX_LAYERS_PER_FLOOR:
					failures.append("floor layers count out of 1..256: " + lfuid)
					continue
				for raw_l: Variant in llist_v as Array:
					total_layers += 1
					if not (raw_l is Dictionary):
						failures.append("layer row is not Dictionary")
						continue
					var l: Dictionary = raw_l as Dictionary
					var luid: String = String(l.get("layer_uid", ""))
					var lkind: String = String(l.get("kind", ""))
					var laccess: String = String(l.get("access", ""))
					if not _is_valid_uid(luid) or layer_owner.has(luid):
						failures.append("invalid or duplicate layer_uid: " + luid)
					if not (lkind in _VALID_LAYER_KINDS):
						failures.append("invalid layer kind: " + lkind)
					if not (l.get("locked", null) is bool):
						failures.append("layer.locked is not bool")
					if not (laccess in _VALID_ACCESS_POLICIES):
						failures.append("invalid layer.access: " + laccess)
					else:
						var viewers_v: Variant = l.get("viewers", [])
						var has_viewers: bool = viewers_v is Array and not (viewers_v as Array).is_empty()
						if (laccess == "players") != has_viewers:
							failures.append("layer access/viewers mismatch: " + luid)
					layer_owner[luid] = lfuid
			if total_layers < 1 or total_layers > _MAX_TOTAL_LAYERS:
				failures.append("total_layers out of 1..4096: %d" % total_layers)

	var es_v: Variant = world.get("entity_state", null)
	var entity_ids: Dictionary = {}
	if not (es_v is Dictionary):
		failures.append("world.entity_state is not Dictionary")
	else:
		var es: Dictionary = es_v as Dictionary
		if not (es.get("version", null) is int) or int(es.get("version", -1)) != 3:
			failures.append("entity_state.version != 3")
		var ents_v: Variant = es.get("entities", null)
		if not (ents_v is Array) or (ents_v as Array).size() > _MAX_ENTITIES:
			failures.append("entity_state.entities invalid or > 10000")
		else:
			var ents: Array = ents_v as Array
			for idx: int in range(ents.size()):
				var raw_e: Variant = ents[idx]
				if not (raw_e is Dictionary):
					failures.append("entity[%d] not Dictionary" % idx)
					continue
				var ent: Dictionary = raw_e as Dictionary
				var eid: String = String(ent.get("id", ""))
				if eid.is_empty() or entity_ids.has(eid):
					failures.append("entity[%d] missing or duplicate id" % idx)
				entity_ids[eid] = true
				_validate_entity(ent, idx, failures)

	var members_v: Variant = world.get("members", null)
	if not (members_v is Array):
		failures.append("world.members is not Array")
	else:
		for m_idx: int in range((members_v as Array).size()):
			var raw_m: Variant = (members_v as Array)[m_idx]
			if not (raw_m is Dictionary):
				failures.append("members[%d] not Dictionary" % m_idx)
				continue
			var m: Dictionary = raw_m as Dictionary
			var meid: String = String(m.get("entity_id", ""))
			var mfuid: String = String(m.get("floor_uid", ""))
			var mluid: String = String(m.get("layer_uid", ""))
			if not entity_ids.has(meid):
				failures.append("members[%d].entity_id missing: %s" % [m_idx, meid])
			if not floor_uids.has(mfuid):
				failures.append("members[%d].floor_uid missing: %s" % [m_idx, mfuid])
			elif String(layer_owner.get(mluid, "")) != mfuid:
				failures.append("members[%d].layer_uid not on floor: %s" % [m_idx, mluid])

	if world.has("modules"):
		var mods_v: Variant = world.get("modules", null)
		if not (mods_v is Dictionary):
			failures.append("world.modules is not Dictionary")
		else:
			var mods: Dictionary = mods_v as Dictionary
			if not (mods.get("version", null) is int) or int(mods.get("version", -1)) != 2:
				failures.append("world.modules.version != 2")
			var entries_v: Variant = mods.get("entries", null)
			if not (entries_v is Dictionary):
				failures.append("world.modules.entries is not Dictionary")
			else:
				var entries: Dictionary = entries_v as Dictionary
				if entries.size() > _MAX_MODULE_ENTRIES:
					failures.append("world.modules.entries > 128")
				var mod_var_bytes: int = var_to_bytes(mods).size()
				meta["modules_var_bytes"] = mod_var_bytes
				if mod_var_bytes > _MAX_MODULE_TOTAL_BYTES:
					failures.append("world.modules var_to_bytes exceeds 8 MiB: %d" % mod_var_bytes)
				var max_entry_var: int = 0
				var total_bounded: int = 0
				var max_entry_bounded: int = 0
				var id_re := RegEx.new()
				id_re.compile("^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$")
				for k: Variant in entries.keys():
					var mid: String = String(k)
					if not (k is String) or id_re.search(mid) == null or mid.length() > 128:
						failures.append("invalid module_id: " + mid)
					var entry_v: Variant = entries[k]
					if not (entry_v is Dictionary):
						failures.append("module entry not Dictionary: " + mid)
						continue
					var entry_d: Dictionary = entry_v as Dictionary
					if not (entry_d.get("version", null) is int) or int(entry_d.get("version", 0)) <= 0:
						failures.append("module entry version <= 0: " + mid)
					if not (entry_d.get("state", null) is Dictionary):
						failures.append("module entry state not Dictionary: " + mid)
					else:
						var ev_bytes: int = var_to_bytes(entry_d["state"]).size()
						if ev_bytes > max_entry_var:
							max_entry_var = ev_bytes
						if ev_bytes > _MAX_MODULE_ENTRY_BYTES:
							failures.append("module entry var_to_bytes > 6 MiB: " + mid)
						var b_est: int = _bounded_size_estimate(entry_d["state"])
						total_bounded += b_est
						if b_est > max_entry_bounded:
							max_entry_bounded = b_est
						if b_est > _MAX_MODULE_ENTRY_BYTES:
							failures.append("module entry bounded estimate > 6 MiB: " + mid)
				meta["modules_max_entry_var_bytes"] = max_entry_var
				meta["modules_bounded_bytes"] = total_bounded
				meta["modules_max_entry_bounded_bytes"] = max_entry_bounded
				if total_bounded > _MAX_MODULE_TOTAL_BYTES:
					failures.append("world.modules bounded estimate > 8 MiB: %d" % total_bounded)


func _validate_entity(ent: Dictionary, idx: int, failures: Array[String]) -> void:
	var xform_v: Variant = ent.get("xform", null)
	if not (xform_v is Dictionary):
		failures.append("entity[%d].xform not Dictionary" % idx)
	else:
		var xf: Dictionary = xform_v as Dictionary
		var pos_v: Variant = xf.get("pos", null)
		var rot_v: Variant = xf.get("rot", null)
		var scale_v: Variant = xf.get("scale", null)
		if not (pos_v is Vector2) or not is_finite((pos_v as Vector2).x) or not is_finite((pos_v as Vector2).y):
			failures.append("entity[%d].xform.pos not finite Vector2" % idx)
		if not (rot_v is float or rot_v is int) or not is_finite(float(rot_v)):
			failures.append("entity[%d].xform.rot not finite number" % idx)
		if not (scale_v is Vector2):
			failures.append("entity[%d].xform.scale not Vector2" % idx)
		else:
			var sv: Vector2 = scale_v as Vector2
			if not is_finite(sv.x) or not is_finite(sv.y) or is_zero_approx(sv.x) or is_zero_approx(sv.y):
				failures.append("entity[%d].xform.scale invalid: %s" % [idx, str(sv)])

	var size_v: Variant = ent.get("entity_size", null)
	if not (size_v is Vector2) or not is_finite((size_v as Vector2).x) or not is_finite((size_v as Vector2).y):
		failures.append("entity[%d].entity_size not finite Vector2" % idx)
	elif (size_v as Vector2).x < 4.0 or (size_v as Vector2).y < 4.0:
		failures.append("entity[%d].entity_size < (4,4)" % idx)

	var fp_v: Variant = ent.get("footprint_radius", null)
	if not (fp_v is float or fp_v is int) or not is_finite(float(fp_v)) or float(fp_v) < 0.5 or float(fp_v) > 4096.0:
		failures.append("entity[%d].footprint_radius out of [0.5, 4096.0]" % idx)

	if ent.has("properties") and ent["properties"] is Dictionary:
		var props: Dictionary = ent["properties"] as Dictionary
		if props.has("z_index"):
			var z: Variant = props["z_index"]
			if (typeof(z) not in [TYPE_INT, TYPE_FLOAT]) or not is_finite(float(z)) or float(z) != 0.0:
				failures.append("entity[%d].properties.z_index != 0" % idx)

	var comps_v: Variant = ent.get("components", null)
	if not (comps_v is Array) or (comps_v as Array).size() < 2:
		failures.append("entity[%d].components < 2" % idx)
		return
	var comps: Array = comps_v as Array
	var c0: Dictionary = comps[0] as Dictionary if comps[0] is Dictionary else {}
	var c1: Dictionary = comps[1] as Dictionary if comps[1] is Dictionary else {}
	if String(c0.get("script", "")) != _COMP_VISUAL_SCRIPT:
		failures.append("entity[%d].components[0] not comp_visual.gd" % idx)
	if String(c1.get("script", "")) != _COMP_PERMISSION_SCRIPT:
		failures.append("entity[%d].components[1] not comp_permission.gd" % idx)

	var vstate_v: Variant = c0.get("state", {})
	if vstate_v is Dictionary:
		_validate_visual_state(vstate_v as Dictionary, idx, failures)

	var etype: String = String(ent.get("entity_type", ""))
	for cidx: int in range(2, comps.size()):
		if not (comps[cidx] is Dictionary):
			failures.append("entity[%d].components[%d] not Dictionary" % [idx, cidx])
			continue
		var cdict: Dictionary = comps[cidx] as Dictionary
		var cscript: String = String(cdict.get("script", ""))
		var cstate_v: Variant = cdict.get("state", {})
		var cstate: Dictionary = cstate_v as Dictionary if cstate_v is Dictionary else {}
		if cscript == _COMP_UNIT_SCRIPT:
			if etype == "map":
				failures.append("entity[%d] map entity cannot have comp_unit.gd" % idx)
			if int(cstate.get("schema_version", -1)) != 1:
				failures.append("entity[%d] comp_unit schema_version != 1" % idx)
		elif cscript == _COMP_SIMPLE_VISION_SCRIPT or cscript == _COMP_SIMPLE_LIGHT_SCRIPT:
			var rad: float = float(cstate.get("radius", -1.0))
			var ang: float = float(cstate.get("view_angle", -1.0))
			if not is_finite(rad) or rad < 0.0:
				failures.append("entity[%d] vision/light radius < 0" % idx)
			if not is_finite(ang) or ang < 0.0 or ang > 360.0:
				failures.append("entity[%d] vision/light view_angle out of 0..360" % idx)


func _validate_visual_state(vstate: Dictionary, idx: int, failures: Array[String]) -> void:
	var sp: String = String(vstate.get("sprite_path", ""))
	if not sp.is_empty():
		if sp.begins_with("user://") or sp.begins_with("file://"):
			failures.append("entity[%d] forbidden sprite_path: %s" % [idx, sp])
		elif sp.begins_with("asset://"):
			var body: String = sp.substr(8)
			var dot_i: int = body.rfind(".")
			var ext: String = body.substr(dot_i + 1).to_lower() if dot_i > 0 else ""
			if body.contains("..") or body.contains("/") or body.contains("\\") or not (ext in _ALLOWED_ASSET_IMAGE_EXTS):
				failures.append("entity[%d] invalid asset:// sprite_path: %s" % [idx, sp])
		elif sp.begins_with("res://"):
			var ext_r: String = sp.get_extension().to_lower()
			if sp.contains("..") or not (ext_r in _ALLOWED_RES_IMAGE_EXTS):
				failures.append("entity[%d] invalid res:// sprite_path: %s" % [idx, sp])
		else:
			failures.append("entity[%d] unarchived relative/raw sprite_path: %s" % [idx, sp])

	if not vstate.has("vector_drawing"):
		return
	var vd_v: Variant = vstate.get("vector_drawing", null)
	if not (vd_v is Dictionary):
		failures.append("entity[%d].vector_drawing not Dictionary" % idx)
		return
	var vd: Dictionary = vd_v as Dictionary
	if int(vd.get("schema", -1)) != 1:
		failures.append("entity[%d].vector_drawing.schema != 1" % idx)
	var font_size: float = float(vd.get("font_size", 24.0))
	if not is_finite(font_size) or font_size < 1.0 or font_size > 4096.0:
		failures.append("entity[%d].vector_drawing.font_size out of 1..4096" % idx)
	var txt: String = String(vd.get("text", ""))
	if txt.length() > _MAX_VECTOR_TEXT_LENGTH:
		failures.append("entity[%d].vector_drawing.text > 65536" % idx)

	var v_size: int = 0
	var verts_v: Variant = vd.get("vertices", PackedVector2Array())
	if verts_v is PackedVector2Array:
		v_size = (verts_v as PackedVector2Array).size()
		if v_size > _MAX_VECTOR_VERTICES or (v_size % 3) != 0:
			failures.append("entity[%d].vector_drawing.vertices invalid size: %d" % [idx, v_size])

	var total_pts: int = 0
	var paths_v: Variant = vd.get("paths", [])
	if paths_v is Array:
		var paths: Array = paths_v as Array
		if paths.size() > _MAX_VECTOR_PATHS:
			failures.append("entity[%d].vector_drawing.paths > 8192" % idx)
		var src_v: Variant = vd.get("source", {})
		var kind: String = String((src_v as Dictionary).get("kind", "")) if src_v is Dictionary else ""
		for p_idx: int in range(paths.size()):
			var ring: Variant = paths[p_idx]
			var r_size: int = (ring as PackedVector2Array).size() if ring is PackedVector2Array else (
				(ring as Array).size() if ring is Array else 0
			)
			total_pts += r_size
			if kind in _OBSTACLE_KINDS and r_size < 3:
				failures.append("entity[%d] obstacle (%s) path[%d] has < 3 vertices" % [idx, kind, p_idx])
		if kind in _OBSTACLE_KINDS and total_pts > _MAX_OBSTACLE_TOTAL_POINTS:
			failures.append("entity[%d] obstacle (%s) total path points > 200000" % [idx, kind])
	if v_size + total_pts > _MAX_VECTOR_TOTAL_POINTS:
		failures.append("entity[%d] vector_drawing combined vertices + path points > 800000" % idx)


func _bounded_size_estimate(val: Variant, depth: int = 0) -> int:
	if depth > 32:
		return 16
	if val is String:
		return 16 + (val as String).length() * 4
	if val is Dictionary:
		var total: int = 16
		var d: Dictionary = val as Dictionary
		for k: Variant in d.keys():
			total += _bounded_size_estimate(k, depth + 1) + _bounded_size_estimate(d[k], depth + 1)
		return total
	if val is Array:
		var total_a: int = 16
		for item: Variant in val as Array:
			total_a += _bounded_size_estimate(item, depth + 1)
		return total_a
	return 16


func _is_valid_uid(value: String) -> bool:
	if value.length() != 32:
		return false
	for i: int in 32:
		var c: int = value.unicode_at(i)
		if not ((c >= 48 and c <= 57) or (c >= 97 and c <= 102)):
			return false
	return true


func _has_control_chars(value: String) -> bool:
	for i: int in value.length():
		var c: int = value.unicode_at(i)
		if c < 32 or (c >= 127 and c <= 159):
			return true
	return false


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
			return "%s float mismatch (%s vs %s)" % [path, str(a), str(b)]
		return ""
	if a != b:
		return "%s value mismatch (%s vs %s)" % [path, str(a), str(b)]
	return ""


func _safe_float(v: float) -> Variant:
	if is_nan(v):
		return "__NAN__"
	if is_inf(v):
		return "__INF__" if v > 0.0 else "__-INF__"
	return v


func _to_json_safe(val: Variant, max_vertex_dump: int, key_hint: String) -> Variant:
	match typeof(val):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_STRING:
			return val
		TYPE_FLOAT:
			return _safe_float(float(val))
		TYPE_VECTOR2:
			var v2: Vector2 = val as Vector2
			return {"__gd_type": "Vector2", "x": _safe_float(v2.x), "y": _safe_float(v2.y)}
		TYPE_VECTOR2I:
			var v2i: Vector2i = val as Vector2i
			return {"__gd_type": "Vector2i", "x": v2i.x, "y": v2i.y}
		TYPE_RECT2:
			var r2: Rect2 = val as Rect2
			return {
				"__gd_type": "Rect2",
				"x": _safe_float(r2.position.x),
				"y": _safe_float(r2.position.y),
				"w": _safe_float(r2.size.x),
				"h": _safe_float(r2.size.y),
			}
		TYPE_COLOR:
			var col: Color = val as Color
			return {
				"__gd_type": "Color",
				"r": _safe_float(col.r),
				"g": _safe_float(col.g),
				"b": _safe_float(col.b),
				"a": _safe_float(col.a),
			}
		TYPE_PACKED_VECTOR2_ARRAY:
			var pva: PackedVector2Array = val as PackedVector2Array
			if max_vertex_dump >= 0 and key_hint == "vertices" and pva.size() > max_vertex_dump:
				var all_finite: bool = true
				var sample: Array = []
				var cap: int = mini(pva.size(), 12)
				for i: int in range(pva.size()):
					var pt: Vector2 = pva[i]
					if not is_finite(pt.x) or not is_finite(pt.y):
						all_finite = false
					if i < cap:
						sample.append([_safe_float(pt.x), _safe_float(pt.y)])
				return {
					"__gd_type": "PackedVector2Array_summary",
					"size": pva.size(),
					"all_finite": all_finite,
					"sample": sample,
				}
			var pts: Array = []
			for pt: Vector2 in pva:
				pts.append([_safe_float(pt.x), _safe_float(pt.y)])
			return {"__gd_type": "PackedVector2Array", "points": pts}
		TYPE_PACKED_STRING_ARRAY:
			var out_s: Array = []
			for s: String in val as PackedStringArray:
				out_s.append(s)
			return out_s
		TYPE_PACKED_INT32_ARRAY:
			var out_i: Array = []
			for n: int in val as PackedInt32Array:
				out_i.append(n)
			return out_i
		TYPE_PACKED_FLOAT32_ARRAY:
			var out_f: Array = []
			for f: float in val as PackedFloat32Array:
				out_f.append(_safe_float(f))
			return out_f
		TYPE_ARRAY:
			var out_arr: Array = []
			for item: Variant in val as Array:
				out_arr.append(_to_json_safe(item, max_vertex_dump, ""))
			return out_arr
		TYPE_DICTIONARY:
			var src_d: Dictionary = val as Dictionary
			var out_d: Dictionary = {}
			for k: Variant in src_d.keys():
				var ks: String = str(k)
				out_d[ks] = _to_json_safe(src_d[k], max_vertex_dump, ks)
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
