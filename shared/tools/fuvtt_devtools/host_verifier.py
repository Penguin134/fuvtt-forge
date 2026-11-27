"""Godot 4.8-beta1 Mono Headless plugin verification harness (`verify-host` subcommand).

Runs an isolated headless Godot probe project inside `build/<mod-name>/verify_evidence/<run-id>/`,
compiling every `.gd` script in the packaged ZIP, instantiating `entry.gd`, driving
`inspect_import()` and `prepare_import()` through a faithful Practice `MockHostBridge`,
and verifying world schema invariants + real Godot `bytes_to_var(var_to_bytes(world))` roundtrip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
from typing import Any, Callable, Mapping
import uuid
import zipfile

from .deployer import _load_or_build_artifact, safe_extract_zip
from .env_config import ConfigError, WorkspaceConfig, load_config
from .packager import _extract_pack_file
from .validator import INWORLD_SCHEMAS, extract_module_namespace_roots, resolve_target_mods
from .win32_wid_host import HiddenWin32WindowHost, Win32WidError, build_wid_godot_args


ERROR_LOG_RE = re.compile(
    r"(?m)^(SCRIPT ERROR:|ERROR:|FATAL:|Unicode parsing error(?:[,:]|$)|Parse Error:)"
)
LEAK_LOG_RE = re.compile(
    r"(?m)^WARNING:.*(ObjectDB.*leaked at exit|resources still in use at exit)"
)

PROBE_PROJECT_GODOT = """config_version=5

[application]

config/name="FuVTT_VerifyHostProbe"
config/features=PackedStringArray("4.8", "GL Compatibility")
"""

HEADLESS_PROBE_GD = r'''extends SceneTree

## Fu vtt Monorepo `verify-host` isolated headless verification probe.
## Aligned with Practice host (`fus.session-plugin.v1` / `fus.practice.world` v3 / `fus.floor_layers.v2`).

const _COMP_VISUAL_SCRIPT: String = "res://scenes/entities/components/comp_visual.gd"
const _COMP_PERMISSION_SCRIPT: String = "res://scenes/entities/components/comp_permission.gd"
const _COMP_SCENE_BOX_SCRIPT: String = "res://modules/scene_box/comp_scene_box.gd"
const _VALID_LAYER_KINDS: Array[String] = ["map", "entity", "obstacle", "area"]
const _OBSTACLE_KINDS: Array[String] = ["wall", "air", "door", "window", "glass"]
const _SCENE_BOX_PREVIEW_POLICIES: Array[String] = ["visited_unlock", "always_public", "cover_only"]
const _SCENE_BOX_ENTER_POLICIES: Array[String] = ["players_allowed", "host_only"]
const _SCENE_BOX_CONFLICTS: Array[String] = [
	"unit", "obstacle", "area", "image_flip", "portal",
	"character_roster_member", "initiative", "resource_pool", "backpack",
	"drag_speed", "follow", "simple_vision", "simple_light", "entity_ink",
]

var _passed_checks: int = 0
var _failures: Array[String] = []
var _loaded_scripts: Array[String] = []


class MockHostBridge:
	extends RefCounted

	var root: String = ""
	var cache: String = ""
	var destination: String = ""
	var file: String = ""
	var settings: Dictionary = {}
	var expected_sha256: String = ""
	var progress_log: Array[String] = []
	var warnings: Array[String] = []
	var archived_urls: Array[String] = []
	var preview_started: bool = false
	var preview_entities_count: int = 0
	var geometry_sealed: bool = false

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
		archived_urls.append(url)
		if url.is_empty():
			return {"ok": false, "reason": "empty_url", "reference": ""}
		var ref_id: String = url.sha256_text().left(16)
		return {
			"ok": true,
			"reference": "asset://mock_%s.png" % ref_id,
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
		return {
			"ok": true,
			"sha256": sha,
			"counts": {"records": 0, "unsupported": 0},
		}

	func decode_source(path: String) -> Dictionary:
		var sha: String = FileAccess.get_sha256(path) if FileAccess.file_exists(path) else ""
		return {
			"ok": true,
			"document": {"source": {"sha256": sha}},
			"scene_items": [],
			"walls": [],
			"doors": [],
		}


func _initialize() -> void:
	call_deferred(&"_run")


func _run() -> void:
	var args: Dictionary = _parse_args(OS.get_cmdline_user_args())
	var pkg_root: String = String(args.get("pkg-root", "res://pkg")).strip_edges()
	var sample_path: String = String(args.get("sample", "")).strip_edges()
	var report_path: String = String(args.get("report", "")).strip_edges()

	var report_data: Dictionary = {
		"ok": false,
		"godot_version": Engine.get_version_info(),
		"passed_checks": 0,
		"failures": [],
		"loaded_scripts": [],
		"warnings": [],
		"entity_count": 0,
		"serialized_bytes": 0,
		"inspect_summary": {},
		"prepare_counts": {},
		"sdk_probe": {
			"sdk_bundled": false,
			"sdk_version": "",
			"log_bus_ok": false,
			"module_registry_ok": false,
			"plugin_sdks_resolved": 0,
		},
	}

	_expect(not pkg_root.is_empty(), "pkg-root argument provided")
	_expect(not sample_path.is_empty() and FileAccess.file_exists(sample_path),
			"sample file exists: " + sample_path)

	# 1. Recursively load() every .gd file in the packaged ZIP to catch compile/parse errors
	var gd_files: PackedStringArray = _collect_gd_files(pkg_root)
	_expect(not gd_files.is_empty(), "packaged plugin contains at least one .gd script")
	for gd_path: String in gd_files:
		var res: Resource = load(gd_path)
		if res == null or not (res is Script):
			_fail("failed to compile/load GDScript: " + gd_path)
		else:
			_loaded_scripts.append(gd_path)
			var gname: StringName = (res as Script).get_global_name()
			_expect(gname == &"", "No global class_name allowed in plugin script: " + gd_path)
			_passed_checks += 1

	# 2. Parse plugin.json & instantiate entry script
	var manifest_path: String = pkg_root.path_join("plugin.json")
	var manifest_var: Variant = JSON.parse_string(FileAccess.get_file_as_string(manifest_path))
	_expect(manifest_var is Dictionary, "plugin.json parses as Dictionary")
	if not (manifest_var is Dictionary):
		_write_and_exit(report_path, report_data)
		return
	var manifest: Dictionary = manifest_var as Dictionary
	var entry_rel: String = String(manifest.get("entry", "entry.gd"))
	var entry_script: Script = load(pkg_root.path_join(entry_rel)) as Script
	_expect(entry_script != null and entry_script.can_instantiate(),
			"entry script loads and can instantiate: " + entry_rel)
	if entry_script == null:
		_write_and_exit(report_path, report_data)
		return

	var plugin_instance: Variant = entry_script.new()
	_expect(plugin_instance is RefCounted, "entry script extends RefCounted")
	if not (plugin_instance is RefCounted):
		_write_and_exit(report_path, report_data)
		return

	var plugin_obj: RefCounted = plugin_instance as RefCounted
	_expect(plugin_obj.has_method("inspect_import"), "entry exposes inspect_import()")
	_expect(plugin_obj.has_method("prepare_import"), "entry exposes prepare_import()")

	# Build default options from manifest.settings
	var options: Dictionary = {}
	for raw_field: Variant in manifest.get("settings", []) as Array:
		if raw_field is Dictionary:
			var field: Dictionary = raw_field as Dictionary
			var key: String = String(field.get("id", ""))
			if not key.is_empty():
				options[key] = field.get("default")

	var host := MockHostBridge.new()
	host.file = sample_path
	host.settings = options.duplicate(true)
	host.expected_sha256 = FileAccess.get_sha256(sample_path) if FileAccess.file_exists(sample_path) else ""

	# 3. Call inspect_import()
	var inspect_raw: Variant = plugin_obj.call("inspect_import", sample_path, options.duplicate(true), host)
	_expect(inspect_raw is Dictionary, "inspect_import returns Dictionary")
	if inspect_raw is Dictionary:
		var inspect_res: Dictionary = inspect_raw as Dictionary
		_expect(bool(inspect_res.get("ok", false)),
				"inspect_import ok == true (reason=%s)" % str(inspect_res.get("reason", "")))
		var name_v: Variant = inspect_res.get("name", null)
		_expect(name_v is String, "inspect_import returns name String")
		var src_bytes_v: Variant = inspect_res.get("source_bytes", null)
		_expect(typeof(src_bytes_v) == TYPE_INT and int(src_bytes_v) >= 0,
				"inspect_import returns non-negative int source_bytes")
		var dec_bytes_v: Variant = inspect_res.get("decoded_bytes", null)
		_expect(typeof(dec_bytes_v) == TYPE_INT and int(dec_bytes_v) >= 0,
				"inspect_import returns non-negative int decoded_bytes")
		var uniq_img_v: Variant = inspect_res.get("unique_images", null)
		_expect(typeof(uniq_img_v) == TYPE_INT and int(uniq_img_v) >= 0,
				"inspect_import returns non-negative int unique_images")
		var assets_v: Variant = inspect_res.get("assets", null)
		_expect(assets_v is Dictionary, "inspect_import returns assets Dictionary")
		var sha_str: String = String(inspect_res.get("sha256", ""))
		var expected_sha: String = FileAccess.get_sha256(sample_path)
		_expect(sha_str.length() == 64 and sha_str == expected_sha,
				"inspect_import returns 64-hex sha256 matching sample file")
		var counts_v: Variant = inspect_res.get("counts", null)
		_expect(counts_v is Dictionary, "inspect_import returns counts Dictionary")
		if counts_v is Dictionary:
			var counts_d: Dictionary = counts_v as Dictionary
			for req_ck: String in [
				"records", "images", "selected_images", "maps", "characters",
				"objects", "text", "drawings", "walls", "doors", "hidden", "unsupported",
			]:
				_expect(counts_d.has(req_ck) and typeof(counts_d.get(req_ck)) == TYPE_INT and int(counts_d.get(req_ck)) >= 0,
						"inspect_import counts has non-negative int '%s'" % req_ck)
		report_data["inspect_summary"] = {
			"ok": bool(inspect_res.get("ok", false)),
			"sha256": sha_str,
			"counts": counts_v if counts_v is Dictionary else {},
		}

	# 4. Call prepare_import()
	var prepare_raw: Variant = plugin_obj.call("prepare_import", sample_path, options.duplicate(true), host)
	_expect(prepare_raw is Dictionary, "prepare_import returns Dictionary")
	if prepare_raw is Dictionary:
		var prepare_res: Dictionary = prepare_raw as Dictionary
		_expect(bool(prepare_res.get("ok", false)),
				"prepare_import ok == true (reason=%s)" % str(prepare_res.get("reason", "")))
		var prepare_counts: Variant = prepare_res.get("counts", {})
		if prepare_counts is Dictionary:
			report_data["prepare_counts"] = prepare_counts
		var world_raw: Variant = prepare_res.get("world", null)
		_expect(world_raw is Dictionary, "prepare_import returns world Dictionary")
		if world_raw is Dictionary:
			var world: Dictionary = world_raw as Dictionary
			_validate_world_invariants(world, report_data)
			if String(manifest.get("id", "")) == "sdk_log_console":
				_expect(host.progress_log.size() > 0, "sdk_log_console emits host.report progress entries")
				var mods_dict: Variant = world.get("modules", {})
				var entries_dict: Variant = (mods_dict as Dictionary).get("entries", {}) if mods_dict is Dictionary else {}
				_expect(entries_dict is Dictionary and (entries_dict as Dictionary).has("sdk_log_console"),
						"sdk_log_console writes world.modules.entries.sdk_log_console")
			# 5. Real Godot binary serialization roundtrip (`var_to_bytes` -> `bytes_to_var`)
			var encoded: PackedByteArray = var_to_bytes(world)
			_expect(encoded.size() > 0, "var_to_bytes(world) succeeds without object errors")
			report_data["serialized_bytes"] = encoded.size()
			var decoded: Variant = bytes_to_var(encoded)
			_expect(decoded is Dictionary, "bytes_to_var(encoded) restores Dictionary")
			if decoded is Dictionary:
				var diff_msg: String = _find_diff(world, decoded, "$")
				_expect(diff_msg.is_empty(),
						"bytes_to_var(var_to_bytes(world)) lossless roundtrip" + (": " + diff_msg if not diff_msg.is_empty() else ""))

	# 6. Enforce ImportBridge host warning caps (100 entries / 7000 joined chars)
	_expect(host.warnings.size() <= 100,
			"host.warnings count <= 100 (actual=%d)" % host.warnings.size())
	var joined_warnings: String = "\n".join(host.warnings)
	_expect(joined_warnings.length() <= 7000,
			"host.warnings joined char length <= 7000 (actual=%d)" % joined_warnings.length())

	# 7. Probe bundled modular FuSdk (LogBus / ModuleRegistry / 23 plugin SDKs / R2 policies)
	if FileAccess.file_exists(pkg_root.path_join("lib/fu_sdk/v1.gd")):
		_probe_bundled_modular_sdk(pkg_root, report_data)

	report_data["warnings"] = host.warnings
	_write_and_exit(report_path, report_data)


func _probe_bundled_modular_sdk(pkg_root: String, report_data: Dictionary) -> void:
	var sdk_path: String = pkg_root.path_join("lib/fu_sdk/v1.gd")
	var sdk_scr: Script = load(sdk_path) as Script
	_expect(sdk_scr != null and sdk_scr.can_instantiate(), "bundled lib/fu_sdk/v1.gd loads and instantiates")
	if sdk_scr == null:
		return

	var sdk: RefCounted = sdk_scr.new()
	var sdk_ver: String = str(sdk_scr.SDK_VERSION)
	_expect(not sdk_ver.is_empty(), "FuSdk.SDK_VERSION is non-empty")

	var probe_host := MockHostBridge.new()
	var logger: RefCounted = sdk.create_logger({"emit_to_engine": false})
	_expect(logger != null, "sdk.create_logger returns LogBus instance")
	var log_bus_ok: bool = false
	if logger != null:
		var observed_seqs: Array[int] = []
		var sub_cb := func(entry: Dictionary) -> void:
			observed_seqs.append(int(entry.get("seq", 0)))
		var token: int = int(logger.subscribe(sub_cb))
		logger.debug("verify_probe", "probe debug message", {"phase": "debug"})
		logger.warn("verify_probe", "probe warning message", {"phase": "warn"})
		var entries: Array = logger.get_entries()
		var warns: Array = logger.get_warnings()
		var unsub_ok: bool = bool(logger.unsubscribe(token))
		log_bus_ok = (
			int(logger.LEVEL_DEBUG) == 10
			and int(logger.LEVEL_INFO) == 20
			and int(logger.LEVEL_WARNING) == 30
			and int(logger.LEVEL_ERROR) == 40
			and observed_seqs.size() == 2
			and entries.size() >= 2
			and warns.size() >= 1
			and unsub_ok
		)
	_expect(log_bus_ok, "bundled LogBus debug/warn/subscribe/get_entries/get_warnings/unsubscribe works")

	var probe_session = sdk.create_session(probe_host, {})
	var reg: RefCounted = sdk.create_module_registry(logger, probe_session)
	_expect(reg != null, "sdk.create_module_registry returns ModuleRegistry instance")
	var module_registry_ok: bool = false
	if reg != null:
		var catalog_list: Array = reg.list_modules(true)
		var edit_enabled: bool = bool(reg.is_module_enabled("feature_edit_mode"))
		var fog_enabled: bool = bool(reg.is_module_enabled("simple_fog"))
		var ct_status: String = str(reg.get_module_status("campaign_time"))
		var dnd_status: String = str(reg.get_module_status("dnd_opportunity"))
		module_registry_ok = (
			catalog_list.size() >= 33
			and edit_enabled
			and (not fog_enabled)
			and ct_status == "playtest_blocked"
			and dnd_status == "playtest_blocked"
		)
	_expect(module_registry_ok, "bundled ModuleRegistry catalog (>=33), core/disabled/playtest_blocked statuses verified")

	var wb = sdk.create_world_builder(probe_session, 150.0)
	var wb_init: Dictionary = wb.setup(probe_session, 150.0)
	_expect(bool(wb_init.get("ok", false)), "bundled probe WorldBuilder.setup succeeds")

	var plugin_ids: Array[String] = [
		"feature_edit_mode", "feature_floor_system", "feature_layer_stack",
		"feature_obstacle_authoring", "feature_entity_library",
		"scene_box", "portal", "grid_alignment", "simple_fog",
		"image_flip", "drag_movement", "drawing", "areas", "entity_notes",
		"checklist", "resource_pool", "character_roster", "backpack",
		"follow", "candidate_initiative", "dice", "campaign_time", "dnd_opportunity",
	]
	var resolved_count: int = 0
	for mid: String in plugin_ids:
		var psdk: Variant = wb.get_plugin_sdk(mid)
		if psdk is RefCounted and String((psdk as RefCounted).MODULE_ID) == mid:
			resolved_count += 1
	_expect(resolved_count == 23,
			"all 23 modular plugin SDKs resolve via WorldBuilder.get_plugin_sdk() (resolved=%d)" % resolved_count)

	if bool(wb_init.get("ok", false)) and resolved_count == 23:
		var wb_logger: RefCounted = wb.get_logger()
		if wb_logger != null:
			wb_logger.set_emit_to_engine(false)
		wb.set_disabled_module_policy("preserve")
		var preserve_res: Dictionary = wb.simple_fog().configure_fog({"history_enabled": true})
		var preserve_warns: int = probe_host.warnings.size()
		_expect(bool(preserve_res.get("ok", false)) and preserve_warns >= 1,
				"R2 preserve policy emits warning and writes disabled simple_fog state")
		wb.set_disabled_module_policy("skip")
		var skip_res: Dictionary = wb.checklist().add_task("", wb.checklist().make_row("Skipped Task"))
		_expect(not bool(skip_res.get("ok", true)) and bool(skip_res.get("skipped", false))
				and probe_host.warnings.size() > preserve_warns,
				"R2 skip policy emits warning and skips disabled checklist write")

	report_data["sdk_probe"] = {
		"sdk_bundled": true,
		"sdk_version": sdk_ver,
		"log_bus_ok": log_bus_ok,
		"module_registry_ok": module_registry_ok,
		"plugin_sdks_resolved": resolved_count,
	}


func _validate_world_invariants(world: Dictionary, report_data: Dictionary) -> void:
	_expect(String(world.get("format", "")) == "fus.practice.world",
			"world.format == 'fus.practice.world'")
	_expect(int(world.get("version", -1)) == 3, "world.version == 3")

	var catalog_v: Variant = world.get("catalog", null)
	_expect(catalog_v is Dictionary, "world.catalog is Dictionary")
	if not (catalog_v is Dictionary):
		return
	var catalog: Dictionary = catalog_v as Dictionary

	var layers_v: Variant = catalog.get("layers", null)
	_expect(layers_v is Dictionary, "world.catalog.layers is Dictionary")
	if not (layers_v is Dictionary):
		return
	var layers_root: Dictionary = layers_v as Dictionary
	_expect(String(layers_root.get("schema", "")) == "fus.floor_layers.v2",
			"world.catalog.layers.schema == 'fus.floor_layers.v2'")

	var floor_uids: Dictionary = {}
	var layer_owner_by_uid: Dictionary = {}
	var layer_floors_v: Variant = layers_root.get("floors", [])
	_expect(layer_floors_v is Array and not (layer_floors_v as Array).is_empty() and (layer_floors_v as Array).size() <= 512,
			"layer catalog has 1..512 floors")
	if layer_floors_v is Array:
		for raw_floor: Variant in layer_floors_v as Array:
			if not (raw_floor is Dictionary):
				_fail("layer floor row is not Dictionary")
				continue
			var fdict: Dictionary = raw_floor as Dictionary
			var fuid: String = String(fdict.get("floor_uid", ""))
			_expect(not fuid.is_empty() and not floor_uids.has(fuid), "unique non-empty floor_uid: " + fuid)
			floor_uids[fuid] = true
			var flayers_v: Variant = fdict.get("layers", [])
			_expect(flayers_v is Array and not (flayers_v as Array).is_empty() and (flayers_v as Array).size() <= 256,
					"floor has 1..256 layers")
			if flayers_v is Array:
				for raw_layer: Variant in flayers_v as Array:
					if not (raw_layer is Dictionary):
						_fail("layer row is not Dictionary")
						continue
					var ldict: Dictionary = raw_layer as Dictionary
					var luid: String = String(ldict.get("layer_uid", ""))
					var lkind: String = String(ldict.get("kind", ""))
					_expect(not luid.is_empty() and not layer_owner_by_uid.has(luid), "unique non-empty layer_uid: " + luid)
					_expect(lkind in _VALID_LAYER_KINDS, "valid layer kind: " + lkind)
					_expect(ldict.get("locked", null) is bool, "layer.locked is bool")
					layer_owner_by_uid[luid] = fuid

	var es_v: Variant = world.get("entity_state", null)
	_expect(es_v is Dictionary, "world.entity_state is Dictionary")
	if not (es_v is Dictionary):
		return
	var es: Dictionary = es_v as Dictionary
	_expect(int(es.get("version", -1)) == 3, "world.entity_state.version == 3")
	var entities_v: Variant = es.get("entities", null)
	_expect(entities_v is Array and (entities_v as Array).size() <= 10000,
			"world.entity_state.entities is Array (<= 10000)")
	if not (entities_v is Array):
		return
	var entities: Array = entities_v as Array
	report_data["entity_count"] = entities.size()

	var entity_ids: Dictionary = {}
	for idx: int in range(entities.size()):
		var raw_ent: Variant = entities[idx]
		if not (raw_ent is Dictionary):
			_fail("entity[%d] is not Dictionary" % idx)
			continue
		var ent: Dictionary = raw_ent as Dictionary
		var eid: String = String(ent.get("id", ""))
		_expect(not eid.is_empty() and not entity_ids.has(eid), "entity[%d] has unique non-empty id" % idx)
		entity_ids[eid] = true
		if ent.has("properties"):
			var ent_props_v: Variant = ent.get("properties", null)
			_expect(ent_props_v is Dictionary, "entity[%d].properties is Dictionary" % idx)
			if ent_props_v is Dictionary and (ent_props_v as Dictionary).has("z_index"):
				var z_idx_v: Variant = (ent_props_v as Dictionary).get("z_index")
				_expect(typeof(z_idx_v) == TYPE_INT and int(z_idx_v) == 0,
						"entity[%d].properties.z_index == 0" % idx)

		var esize_v: Variant = ent.get("entity_size", null)
		_expect(
			esize_v is Vector2
			and is_finite((esize_v as Vector2).x)
			and is_finite((esize_v as Vector2).y)
			and (esize_v as Vector2).x >= 4.0
			and (esize_v as Vector2).y >= 4.0,
			"entity[%d].entity_size is finite Vector2 >= (4, 4)" % idx
		)
		_expect(
			ent.get("selectable_in_select_mode", null) is bool,
			"entity[%d].selectable_in_select_mode is bool" % idx
		)
		var fpr_v: Variant = ent.get("footprint_radius", null)
		_expect(
			typeof(fpr_v) == TYPE_FLOAT
			and is_finite(float(fpr_v))
			and float(fpr_v) >= 0.5
			and float(fpr_v) <= 4096.0,
			"entity[%d].footprint_radius is TYPE_FLOAT finite in [0.5, 4096.0]" % idx
		)
		_expect(
			ent.get("fallback_color", null) is Color,
			"entity[%d].fallback_color is Color" % idx
		)

		# Transform finiteness & non-zero scale
		var xform_v: Variant = ent.get("xform", null)
		_expect(xform_v is Dictionary, "entity[%d].xform is Dictionary" % idx)
		if xform_v is Dictionary:
			var xf: Dictionary = xform_v as Dictionary
			_expect(
				xf.size() == 3 and xf.has("pos") and xf.has("rot") and xf.has("scale"),
				"entity[%d].xform has exact keys [pos, rot, scale]" % idx
			)
			var pos_v: Variant = xf.get("pos", null)
			var rot_v: Variant = xf.get("rot", null)
			var scale_v: Variant = xf.get("scale", null)
			_expect(pos_v is Vector2 and is_finite((pos_v as Vector2).x) and is_finite((pos_v as Vector2).y),
					"entity[%d].xform.pos is finite Vector2" % idx)
			_expect(rot_v is float and is_finite(rot_v as float),
					"entity[%d].xform.rot is TYPE_FLOAT finite" % idx)
			_expect(
				scale_v is Vector2
				and is_finite((scale_v as Vector2).x)
				and is_finite((scale_v as Vector2).y)
				and not is_zero_approx((scale_v as Vector2).x)
				and not is_zero_approx((scale_v as Vector2).y),
				"entity[%d].xform.scale is finite non-zero Vector2" % idx
			)

		# components[0..1] fast-path invariant + scene_box/manual component checks
		var comps_v: Variant = ent.get("components", null)
		_expect(comps_v is Array and (comps_v as Array).size() >= 2,
				"entity[%d].components has >= 2 entries" % idx)
		if comps_v is Array and (comps_v as Array).size() >= 2:
			var comps: Array = comps_v as Array
			var c0: Dictionary = comps[0] as Dictionary if comps[0] is Dictionary else {}
			var c1: Dictionary = comps[1] as Dictionary if comps[1] is Dictionary else {}
			_expect(String(c0.get("script", "")) == _COMP_VISUAL_SCRIPT,
					"entity[%d].components[0] is comp_visual.gd" % idx)
			_expect(String(c1.get("script", "")) == _COMP_PERMISSION_SCRIPT,
					"entity[%d].components[1] is comp_permission.gd" % idx)
			var vstate_v: Variant = c0.get("state", {})
			if vstate_v is Dictionary:
				_validate_visual_state(vstate_v as Dictionary, idx)
			var comp_ids: Dictionary = {}
			var scene_box_state: Dictionary = {}
			var has_scene_box_comp: bool = false
			for c_idx: int in range(comps.size()):
				var cdict_v: Variant = comps[c_idx]
				_expect(cdict_v is Dictionary, "entity[%d].components[%d] is Dictionary" % [idx, c_idx])
				if not (cdict_v is Dictionary):
					continue
				var cdict: Dictionary = cdict_v as Dictionary
				var c_script_v: Variant = cdict.get("script", null)
				var c_script: String = c_script_v as String if c_script_v is String else ""
				_expect(
					c_script_v is String and c_script.begins_with("res://") and c_script.ends_with(".gd"),
					"entity[%d].components[%d].script is res://...*.gd String" % [idx, c_idx]
				)
				var c_state_v: Variant = cdict.get("state", null)
				var expected_keys: int = 2 + int(cdict.has("parked")) + int(cdict.has("manual"))
				_expect(cdict.has("script") and cdict.has("state") and cdict.size() == expected_keys,
						"entity[%d].components[%d] has exact allowed keys" % [idx, c_idx])
				if cdict.has("parked"):
					_expect(cdict.get("parked") is bool, "entity[%d].components[%d].parked is bool" % [idx, c_idx])
				if cdict.has("manual"):
					_expect(cdict.get("manual") is bool and bool(cdict.get("parked", false)),
							"entity[%d].components[%d].manual requires parked == true" % [idx, c_idx])
				_expect(c_state_v is Dictionary, "entity[%d].components[%d].state is Dictionary" % [idx, c_idx])
				var cid: String = _probe_component_id(c_script)
				if not cid.is_empty():
					_expect(not comp_ids.has(cid),
							"entity[%d].components[%d] unique component_id '%s'" % [idx, c_idx, cid])
					comp_ids[cid] = true
				if c_script == _COMP_SCENE_BOX_SCRIPT and c_state_v is Dictionary:
					has_scene_box_comp = true
					scene_box_state = c_state_v as Dictionary
			if has_scene_box_comp:
				_expect(String(ent.get("entity_type", "")) != "map",
						"entity[%d] with comp_scene_box is not entity_type == 'map'" % idx)
				for conflict_cid: String in _SCENE_BOX_CONFLICTS:
					_expect(not comp_ids.has(conflict_cid),
							"entity[%d] comp_scene_box has no conflict with '%s'" % [idx, conflict_cid])
				_validate_comp_scene_box_state(scene_box_state, idx)

	# Members graph check
	var members_v: Variant = world.get("members", null)
	_expect(members_v is Array, "world.members is Array")
	if members_v is Array:
		_expect((members_v as Array).size() == entities.size(),
				"world.members.size() == entities.size()")
		for m_idx: int in range((members_v as Array).size()):
			var raw_m: Variant = (members_v as Array)[m_idx]
			if not (raw_m is Dictionary):
				_fail("members[%d] is not Dictionary" % m_idx)
				continue
			var mdict: Dictionary = raw_m as Dictionary
			var meid: String = String(mdict.get("entity_id", ""))
			var mfuid: String = String(mdict.get("floor_uid", ""))
			var mluid: String = String(mdict.get("layer_uid", ""))
			_expect(entity_ids.has(meid), "members[%d].entity_id exists in entity_state" % m_idx)
			_expect(floor_uids.has(mfuid), "members[%d].floor_uid exists in catalog" % m_idx)
			_expect(layer_owner_by_uid.get(mluid, "") == mfuid,
					"members[%d].layer_uid belongs to floor_uid" % m_idx)

	var scene_uids_map: Dictionary = {}
	if world.has("modules"):
		var mods_v: Variant = world.get("modules", null)
		_expect(mods_v is Dictionary
				and (mods_v as Dictionary).size() == 2
				and typeof((mods_v as Dictionary).get("version", null)) == TYPE_INT
				and int((mods_v as Dictionary).get("version", -1)) == 2
				and (mods_v as Dictionary).get("entries", null) is Dictionary,
				"world.modules has exact keys [version, entries] with version == 2")
		if mods_v is Dictionary and (mods_v as Dictionary).get("entries", null) is Dictionary:
			_expect(var_to_bytes(mods_v).size() <= 24 * 1024 * 1024,
					"world.modules var_to_bytes <= 24 MiB")
			var entries_dict: Dictionary = (mods_v as Dictionary)["entries"] as Dictionary
			_expect(entries_dict.size() <= 128,
					"world.modules.entries.size() <= 128")
			var mod_id_re := RegEx.new()
			mod_id_re.compile("^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$")
			for mid: Variant in entries_dict.keys():
				var mid_str: String = String(mid) if (mid is String or mid is StringName) else ""
				_expect((mid is String or mid is StringName) and mid_str.length() > 0 and mid_str.length() <= 128
						and mod_id_re.search(mid_str) != null,
						"world.modules.entries key '%s' is valid module_id" % str(mid))
				var entry_v: Variant = entries_dict[mid]
				_expect(entry_v is Dictionary, "world.modules.entries.%s is Dictionary" % mid_str)
				if entry_v is Dictionary:
					var ed: Dictionary = entry_v as Dictionary
					_expect(ed.size() == 2 and ed.has("version") and ed.has("state"),
							"world.modules.entries.%s has exact keys [version, state]" % mid_str)
					_expect(typeof(ed.get("version", null)) == TYPE_INT and int(ed.get("version", 0)) >= 1,
							"world.modules.entries.%s.version is int >= 1" % mid_str)
					_expect(ed.get("state", null) is Dictionary,
							"world.modules.entries.%s.state is Dictionary" % mid_str)
					if ed.get("state", null) is Dictionary:
						_expect(var_to_bytes(ed["state"]).size() <= 16 * 1024 * 1024,
								"world.modules.entries.%s var_to_bytes <= 16 MiB" % mid_str)
			if entries_dict.has("scene_box"):
				scene_uids_map = _validate_scene_box_module(entries_dict["scene_box"], catalog, floor_uids)

	if not scene_uids_map.is_empty():
		for idx: int in range(entities.size()):
			var raw_ent: Variant = entities[idx]
			if not (raw_ent is Dictionary):
				continue
			for raw_comp: Variant in (raw_ent as Dictionary).get("components", []) as Array:
				if raw_comp is Dictionary and String((raw_comp as Dictionary).get("script", "")) == _COMP_SCENE_BOX_SCRIPT:
					var st_v: Variant = (raw_comp as Dictionary).get("state", null)
					if st_v is Dictionary:
						var t_uid: String = String((st_v as Dictionary).get("target_scene_uid", ""))
						if not t_uid.is_empty():
							_expect(scene_uids_map.has(t_uid),
									"entity[%d] comp_scene_box.target_scene_uid exists in scene_box.scenes" % idx)


func _probe_component_id(script_path: String) -> String:
	var base: String = script_path.get_file().get_basename()
	return base.substr(5) if base.begins_with("comp_") else base


func _is_valid_hex32(val: String) -> bool:
	if val.length() != 32:
		return false
	for i: int in range(32):
		var c: int = val.unicode_at(i)
		if not ((c >= 48 and c <= 57) or (c >= 97 and c <= 102)):
			return false
	return true


func _is_valid_cover_asset(val: String) -> bool:
	if val.is_empty():
		return true
	var rx := RegEx.new()
	if rx.compile("^asset://[0-9a-f]{64}\\.(png|jpg|jpeg|webp|bmp)$") != OK:
		return false
	return rx.search(val) != null


func _validate_comp_scene_box_state(st: Dictionary, ent_idx: int) -> void:
	_expect(st.get("schema_version", null) is int and int(st.get("schema_version", 0)) == 1,
			"entity[%d] comp_scene_box.schema_version == 1" % ent_idx)
	var t_uid: Variant = st.get("target_scene_uid", "")
	_expect(t_uid is String and (String(t_uid).is_empty() or _is_valid_hex32(String(t_uid))),
			"entity[%d] comp_scene_box.target_scene_uid is '' or 32-hex" % ent_idx)
	var prev_pol: Variant = st.get("preview_policy", "visited_unlock")
	_expect(prev_pol is String and String(prev_pol) in _SCENE_BOX_PREVIEW_POLICIES,
			"entity[%d] comp_scene_box.preview_policy is valid" % ent_idx)
	var enter_pol: Variant = st.get("enter_policy", "players_allowed")
	_expect(enter_pol is String and String(enter_pol) in _SCENE_BOX_ENTER_POLICIES,
			"entity[%d] comp_scene_box.enter_policy is valid" % ent_idx)
	var cov: Variant = st.get("cover_asset", "")
	_expect(cov is String and _is_valid_cover_asset(String(cov)),
			"entity[%d] comp_scene_box.cover_asset is '' or valid asset://" % ent_idx)


func _validate_scene_box_module(entry_v: Variant, catalog: Dictionary, catalog_floor_uids: Dictionary) -> Dictionary:
	var scene_uids: Dictionary = {}
	_expect(entry_v is Dictionary, "scene_box module entry is Dictionary")
	if not (entry_v is Dictionary):
		return scene_uids
	var entry: Dictionary = entry_v as Dictionary
	_expect(entry.get("version", null) is int and int(entry.get("version", 0)) == 1,
			"scene_box module entry.version == 1")
	var st_v: Variant = entry.get("state", null)
	_expect(st_v is Dictionary, "scene_box module entry.state is Dictionary")
	if not (st_v is Dictionary):
		return scene_uids
	var st: Dictionary = st_v as Dictionary
	_expect(st.get("schema_version", null) is int and int(st.get("schema_version", 0)) == 2,
			"scene_box.state.schema_version == 2")

	var entry_uid: String = String(st.get("entry_scene_uid", ""))
	var host_active_uid: String = String(st.get("host_active_scene_uid", ""))
	_expect(_is_valid_hex32(entry_uid), "scene_box.entry_scene_uid is 32-hex")
	_expect(_is_valid_hex32(host_active_uid), "scene_box.host_active_scene_uid is 32-hex")

	var scenes_v: Variant = st.get("scenes", null)
	_expect(scenes_v is Array and not (scenes_v as Array).is_empty() and (scenes_v as Array).size() <= 64,
			"scene_box.scenes has 1..64 entries")
	if not (scenes_v is Array):
		return scene_uids

	var claimed_floors: Dictionary = {}
	var scene_floors_map: Dictionary = {}
	for s_idx: int in range((scenes_v as Array).size()):
		var raw_s: Variant = (scenes_v as Array)[s_idx]
		_expect(raw_s is Dictionary, "scene_box.scenes[%d] is Dictionary" % s_idx)
		if not (raw_s is Dictionary):
			continue
		var srow: Dictionary = raw_s as Dictionary
		var suid: String = String(srow.get("uid", ""))
		var sname: String = String(srow.get("name", "")).strip_edges()
		_expect(_is_valid_hex32(suid) and not scene_uids.has(suid),
				"scene_box.scenes[%d] has unique 32-hex uid" % s_idx)
		_expect(not sname.is_empty() and sname.length() <= 96,
				"scene_box.scenes[%d] has valid non-empty name" % s_idx)
		scene_uids[suid] = true

		var fl_v: Variant = srow.get("floor_uids", null)
		_expect(fl_v is Array and not (fl_v as Array).is_empty(),
				"scene_box.scenes[%d].floor_uids is non-empty Array" % s_idx)
		var this_floors: Dictionary = {}
		if fl_v is Array:
			for fv: Variant in fl_v as Array:
				var fuid: String = String(fv)
				_expect(_is_valid_hex32(fuid) and catalog_floor_uids.has(fuid) and not claimed_floors.has(fuid),
						"scene_box.scenes[%d] floor_uid '%s' exists and is globally disjoint" % [s_idx, fuid])
				claimed_floors[fuid] = suid
				this_floors[fuid] = true
		scene_floors_map[suid] = this_floors

		var def_f: String = String(srow.get("default_floor_uid", ""))
		_expect(this_floors.has(def_f),
				"scene_box.scenes[%d].default_floor_uid belongs to its floor_uids" % s_idx)
		var cov: Variant = srow.get("cover_asset", "")
		_expect(cov is String and _is_valid_cover_asset(String(cov)),
				"scene_box.scenes[%d].cover_asset is valid" % s_idx)

	for cf_uid: Variant in catalog_floor_uids.keys():
		_expect(claimed_floors.has(String(cf_uid)),
				"catalog floor '%s' is claimed by a scene_box scene" % String(cf_uid))

	_expect(scene_uids.has(entry_uid), "scene_box.entry_scene_uid exists in scenes")
	_expect(scene_uids.has(host_active_uid), "scene_box.host_active_scene_uid exists in scenes")

	var active_floor: String = String(catalog.get("active_floor_uid", ""))
	if scene_floors_map.has(host_active_uid):
		var active_scene_floors: Dictionary = scene_floors_map[host_active_uid] as Dictionary
		_expect(active_scene_floors.has(active_floor),
				"catalog.active_floor_uid belongs to scene_box.host_active_scene_uid")
	return scene_uids


func _validate_visual_state(vstate: Dictionary, ent_idx: int) -> void:
	var sprite_path: String = String(vstate.get("sprite_path", ""))
	if not sprite_path.is_empty():
		_expect(not sprite_path.begins_with("user://")
				and (sprite_path.begins_with("asset://") or sprite_path.begins_with("res://")),
				"entity[%d] sprite_path forbids user:// and uses asset:// or res://" % ent_idx)

	if not vstate.has("vector_drawing"):
		return
	var vd_v: Variant = vstate.get("vector_drawing", null)
	_expect(vd_v is Dictionary, "entity[%d].vector_drawing is Dictionary" % ent_idx)
	if not (vd_v is Dictionary):
		return
	var vd: Dictionary = vd_v as Dictionary
	var font_size: float = float(vd.get("font_size", 24.0))
	_expect(is_finite(font_size) and font_size >= 1.0 and font_size <= 4096.0,
			"entity[%d].vector_drawing.font_size within 1..4096" % ent_idx)
	var txt: String = String(vd.get("text", ""))
	_expect(txt.length() <= 65536, "entity[%d].vector_drawing.text <= 65536 chars" % ent_idx)

	var verts_v: Variant = vd.get("vertices", PackedVector2Array())
	if verts_v is PackedVector2Array:
		_expect((verts_v as PackedVector2Array).size() <= 600000,
				"entity[%d].vector_drawing.vertices <= 600000" % ent_idx)
	var paths_v: Variant = vd.get("paths", [])
	if paths_v is Array:
		var paths: Array = paths_v as Array
		_expect(paths.size() <= 8192, "entity[%d].vector_drawing.paths <= 8192" % ent_idx)
		var src_v: Variant = vd.get("source", {})
		var kind: String = String((src_v as Dictionary).get("kind", "")) if src_v is Dictionary else ""
		if kind in _OBSTACLE_KINDS:
			for p_idx: int in range(paths.size()):
				var ring: Variant = paths[p_idx]
				var ring_size: int = (ring as PackedVector2Array).size() if ring is PackedVector2Array else (
					(ring as Array).size() if ring is Array else 0
				)
				_expect(ring_size >= 3,
						"entity[%d] obstacle (%s) path[%d] has >= 3 vertices" % [ent_idx, kind, p_idx])


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
		if not is_equal_approx(float(a), float(b)):
			return "%s float mismatch (%s vs %s)" % [path, str(a), str(b)]
		return ""
	if a != b:
		return "%s value mismatch (%s vs %s)" % [path, str(a), str(b)]
	return ""


func _collect_gd_files(root_dir: String) -> PackedStringArray:
	var out := PackedStringArray()
	var stack := PackedStringArray([root_dir])
	while not stack.is_empty():
		var current: String = stack[stack.size() - 1]
		stack.resize(stack.size() - 1)
		var dir: DirAccess = DirAccess.open(current)
		if dir == null:
			_fail("cannot open directory: " + current)
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


func _expect(condition: bool, message: String) -> void:
	if condition:
		_passed_checks += 1
		return
	_fail(message)


func _fail(message: String) -> void:
	_failures.append(message)
	push_error("FUVTT_VERIFY_HOST CHECK_FAIL: " + message)


func _write_and_exit(report_path: String, report_data: Dictionary) -> void:
	report_data["ok"] = _failures.is_empty()
	report_data["passed_checks"] = _passed_checks
	report_data["failures"] = _failures
	report_data["loaded_scripts"] = _loaded_scripts
	if not report_path.is_empty():
		var f: FileAccess = FileAccess.open(report_path, FileAccess.WRITE)
		if f != null:
			f.store_string(JSON.stringify(report_data, "\t") + "\n")
			f.close()
	if _failures.is_empty():
		print("FUVTT_VERIFY_HOST PASS checks=%d scripts=%d entities=%d bytes=%d" % [
			_passed_checks, _loaded_scripts.size(), int(report_data.get("entity_count", 0)),
			int(report_data.get("serialized_bytes", 0)),
		])
		quit(0)
	else:
		print("FUVTT_VERIFY_HOST FAIL checks=%d failures=%d" % [_passed_checks, _failures.size()])
		quit(1)
'''

_INWORLD_HOST_SHIMS: dict[str, tuple[str, str]] = {
    "token.gd": (
        "ExtToken",
        r'''extends RefCounted
class_name ExtToken

var label: String = ""
var _callback: Callable = Callable()
var _active: bool = true


static func make(callback: Callable, token_label: String = "") -> ExtToken:
	var tok := ExtToken.new()
	tok.label = token_label
	tok._callback = callback
	return tok


func is_active() -> bool:
	return _active


func revert() -> void:
	if not _active:
		return
	_active = false
	var cb := _callback
	_callback = Callable()
	if cb.is_valid():
		cb.call()
''',
    ),
    "hook_ids.gd": (
        "HookIds",
        r'''extends RefCounted
class_name HookIds

const TABLE: Dictionary = {
	&"entity.spawned": {"cancellable": false, "args": ["entity:BoardToken"]},
	&"entity.removed": {"cancellable": false, "args": ["entity:BoardToken"]},
	&"entity.trashed": {"cancellable": false, "args": ["entity:Node"]},
	&"entity.restored": {"cancellable": false, "args": ["entity:Node"]},
	&"entity.property_changed": {"cancellable": false, "args": ["entity:BoardToken", "prop:String", "old:Variant", "new:Variant"]},
	&"entity.moved": {"cancellable": false, "args": ["entity:BoardToken", "from:Vector2", "to:Vector2"]},
	&"entity.motion_committed": {"cancellable": false, "args": ["event:Dictionary"]},
	&"entity.selected": {"cancellable": false, "args": ["entity:BoardToken"]},
	&"entity.deselected": {"cancellable": false, "args": ["entity:BoardToken"]},
	&"comp.added": {"cancellable": false, "args": ["host:Node", "comp:CompBase"]},
	&"comp.removed": {"cancellable": false, "args": ["host:Node", "comp:CompBase"]},
	&"comp.state_changed": {"cancellable": false, "args": ["host:Node", "comp:CompBase"]},
	&"mode.pre_change": {"cancellable": true, "args": ["old:String", "new:String"]},
	&"mode.changed": {"cancellable": false, "args": ["old:String", "new:String"]},
	&"selection.changed": {"cancellable": false, "args": ["selected:Array"]},
	&"viewpoint.changed": {"cancellable": false, "args": ["peer_id:int"]},
	&"input.mouse_button": {"cancellable": true, "args": ["event:InputEventMouseButton"]},
	&"input.mouse_motion": {"cancellable": true, "args": ["event:InputEventMouseMotion"]},
	&"input.key": {"cancellable": true, "args": ["event:InputEventKey"]},
	&"frame.process": {"cancellable": false, "args": ["delta:float"]},
	&"frame.physics": {"cancellable": false, "args": ["delta:float"]},
	&"room.player_joined": {"cancellable": false, "args": ["peer_id:int", "info:Dictionary"]},
	&"room.player_left": {"cancellable": false, "args": ["peer_id:int"]},
	&"room.player_connection_info_changed": {"cancellable": false, "args": ["peer_id:int", "info:Dictionary"]},
	&"room.permission_changed": {"cancellable": false, "args": ["host:Node", "peer:int", "granted:bool"]},
	&"save.pre_capture": {"cancellable": false, "args": ["snapshot:Dictionary"]},
	&"save.post_capture": {"cancellable": false, "args": ["snapshot:Dictionary"]},
	&"save.pre_restore": {"cancellable": false, "args": ["snapshot:Dictionary"]},
	&"save.post_restore": {"cancellable": false, "args": ["snapshot:Dictionary"]},
	&"palette.armed": {"cancellable": false, "args": ["id:String", "kind:String"]},
	&"palette.placed": {"cancellable": false, "args": ["placed_node:Node"]},
	&"combat.round_start": {"cancellable": false, "args": ["combat:Object"]},
	&"combat.round_end": {"cancellable": false, "args": ["combat:Object"]},
	&"combat.turn_start": {"cancellable": false, "args": ["combat:Object", "actor:Node"]},
	&"combat.turn_end": {"cancellable": false, "args": ["combat:Object", "actor:Node"]},
	&"area.enter": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"area.exit": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"area.stay_tick": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"door.toggled": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"portal.teleported": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"trap.triggered": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"transform.changed": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"rest.short": {"cancellable": false, "args": ["actor:Node"]},
	&"rest.long": {"cancellable": false, "args": ["actor:Node"]},
	&"camera.navigated": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"drawing.stroke_committed": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"ui.panel_opened": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"floor.changed": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"module.toggled": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"scene.switched": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"scene.created": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"entity_box.acted": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"dice.rolled": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"combat.started": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"combat.ended": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"vitals.changed": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"vitals.downed": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"chat.message_received": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"avg.stage_changed": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"avg.dialogue_shown": {"cancellable": false, "args": ["payload:Dictionary"]},
	&"checklist.completed": {"cancellable": false, "args": ["payload:Dictionary"]},
}


static func is_custom_namespaced(hook_id: StringName) -> bool:
	var text := String(hook_id)
	if not (text.begins_with("ext.") or text.begins_with("mod.")):
		return false
	var parts := text.split(".")
	if parts.size() < 3 or text.length() > 128:
		return false
	for idx: int in range(1, parts.size()):
		var seg: String = parts[idx]
		if seg.is_empty():
			return false
		for ch: String in seg:
			var code: int = ch.unicode_at(0)
			var ok: bool = (code >= 97 and code <= 122) or (code >= 48 and code <= 57) or code == 95
			if not ok:
				return false
	return true


static func expected_arity(hook_id: StringName) -> int:
	if TABLE.has(hook_id):
		return ((TABLE[hook_id] as Dictionary)["args"] as Array).size()
	if is_custom_namespaced(hook_id):
		return 1
	return -1


static func is_registered(hook_id: StringName) -> bool:
	return TABLE.has(hook_id) or is_custom_namespaced(hook_id)


static func is_cancellable(hook_id: StringName) -> bool:
	var info: Dictionary = TABLE.get(hook_id, {})
	return bool(info.get("cancellable", false))
''',
    ),
    "hook_bus.gd": (
        "HookBus",
        r'''extends Node
class_name HookBus

var _next_id: int = 1
var _subs: Dictionary = {}
var subscribed_ids: Array[String] = []


func subscribe(hook_id: StringName, callback: Callable, priority: int = 0) -> int:
	var sid := _next_id
	_next_id += 1
	var list: Array = _subs.get(hook_id, [])
	list.append({"id": sid, "cb": callback, "priority": priority})
	_subs[hook_id] = list
	if not (String(hook_id) in subscribed_ids):
		subscribed_ids.append(String(hook_id))
	return sid


func unsubscribe(hook_id: StringName, sid: int) -> void:
	if not _subs.has(hook_id):
		return
	var list: Array = _subs[hook_id]
	for idx: int in range(list.size() - 1, -1, -1):
		if int((list[idx] as Dictionary).get("id", -1)) == sid:
			list.remove_at(idx)
	if list.is_empty():
		_subs.erase(hook_id)


func emit_hook(hook_id: StringName, arguments: Array = []) -> bool:
	if not _subs.has(hook_id):
		return true
	var list: Array = (_subs[hook_id] as Array).duplicate()
	for entry: Dictionary in list:
		var cb: Callable = entry.get("cb", Callable())
		if cb.is_valid():
			var ret: Variant = cb.callv(arguments)
			if HookIds.is_cancellable(hook_id) and ret is bool and not bool(ret):
				return false
	return true


func clear_all() -> void:
	_subs.clear()
''',
    ),
    "slot_registry.gd": (
        "SlotRegistry",
        r'''extends Node
class_name SlotRegistry

var _next_id: int = 1
var _slots: Dictionary = {}


func register_item(slot_id: StringName, spec: Dictionary) -> int:
	var iid := _next_id
	_next_id += 1
	var arr: Array = _slots.get(slot_id, [])
	arr.append({"id": iid, "spec": spec})
	_slots[slot_id] = arr
	return iid


func unregister_item(slot_id: StringName, item_id: int) -> void:
	if not _slots.has(slot_id):
		return
	var arr: Array = _slots[slot_id]
	for idx: int in range(arr.size() - 1, -1, -1):
		if int((arr[idx] as Dictionary).get("id", -1)) == item_id:
			arr.remove_at(idx)


func get_items(slot_id: StringName) -> Array[Dictionary]:
	var out: Array[Dictionary] = []
	for entry: Variant in _slots.get(slot_id, []):
		if entry is Dictionary:
			out.append(entry as Dictionary)
	return out


func has_slot(slot_id: StringName) -> bool:
	return _slots.has(slot_id) and not (_slots[slot_id] as Array).is_empty()


func all_slot_ids() -> Array[StringName]:
	var out: Array[StringName] = []
	for k: Variant in _slots.keys():
		out.append(StringName(k))
	return out


func clear_all() -> void:
	_slots.clear()
''',
    ),
    "state_value.gd": (
        "StateValue",
        r'''extends RefCounted
class_name StateValue


static func is_data(value: Variant, depth: int = 0) -> bool:
	if depth > 32:
		return false
	match typeof(value):
		TYPE_NIL, TYPE_BOOL, TYPE_INT, TYPE_STRING, TYPE_STRING_NAME, TYPE_NODE_PATH:
			return true
		TYPE_FLOAT:
			return is_finite(value)
		TYPE_VECTOR2, TYPE_VECTOR3, TYPE_VECTOR4, TYPE_QUATERNION:
			return value.is_finite()
		TYPE_VECTOR2I, TYPE_VECTOR3I, TYPE_VECTOR4I, TYPE_RECT2I:
			return true
		TYPE_COLOR:
			return is_finite(value.r) and is_finite(value.g) and is_finite(value.b) and is_finite(value.a)
		TYPE_RECT2, TYPE_AABB:
			return value.position.is_finite() and value.size.is_finite()
		TYPE_TRANSFORM2D:
			return value.x.is_finite() and value.y.is_finite() and value.origin.is_finite()
		TYPE_DICTIONARY:
			if depth == 32:
				return value.is_empty()
			for key: Variant in value:
				if not (key is String) and not is_data(key, depth + 1):
					return false
				if not is_data(value[key], depth + 1):
					return false
			return true
		TYPE_ARRAY:
			if depth == 32:
				return value.is_empty()
			for item: Variant in value:
				if not is_data(item, depth + 1):
					return false
			return true
		TYPE_PACKED_BYTE_ARRAY, TYPE_PACKED_INT32_ARRAY, TYPE_PACKED_INT64_ARRAY, TYPE_PACKED_STRING_ARRAY:
			return true
		TYPE_PACKED_FLOAT32_ARRAY, TYPE_PACKED_FLOAT64_ARRAY, TYPE_PACKED_VECTOR2_ARRAY, TYPE_PACKED_VECTOR3_ARRAY, TYPE_PACKED_VECTOR4_ARRAY, TYPE_PACKED_COLOR_ARRAY:
			for item: Variant in value:
				if not is_data(item, depth + 1):
					return false
			return true
	return false
''',
    ),
    "desktop_api_service.gd": (
        "DesktopApiService",
        r'''extends RefCounted
class_name DesktopApiService

const DEFAULT_CELL_SIZE := 64.0

var _desktop_ref: WeakRef
var _cam_pos: Vector2 = Vector2.ZERO
var _cam_zoom: Vector2 = Vector2.ONE
var _mode: String = "select"


func _init(desktop: Node = null) -> void:
	_desktop_ref = weakref(desktop) if is_instance_valid(desktop) else null


func get_desktop() -> Node:
	var d: Node = _desktop_ref.get_ref() as Node if _desktop_ref != null else null
	return d if is_instance_valid(d) and d.is_inside_tree() and not d.is_queued_for_deletion() else null


func is_gm() -> bool:
	var d := get_desktop()
	return d != null and d.has_method(&"can_author_world") and bool(d.call(&"can_author_world"))


func network_role() -> String:
	return "solo"


func local_peer_id() -> int:
	return 1


func local_player_id() -> String:
	return "host"


func joined_players() -> Array[Dictionary]:
	return []


func can_command_entity(_entity_or_id: Variant, _peer: int = 0) -> bool:
	return is_gm()


func active_scene_uid() -> String:
	return "scene_probe_01"


func active_scene_name() -> String:
	return "Probe Scene"


func active_floor_uid() -> String:
	return "floor_probe_01"


func active_floor_id() -> int:
	return 0


func world_units_per_cell() -> float:
	return DEFAULT_CELL_SIZE


func screen_to_world(screen_pos: Vector2) -> Vector2:
	return screen_pos + _cam_pos


func world_to_screen(world_pos: Vector2) -> Vector2:
	return world_pos - _cam_pos


func camera_position() -> Vector2:
	return _cam_pos


func camera_zoom() -> Vector2:
	return _cam_zoom


func focus_camera(world_pos: Vector2) -> bool:
	if not world_pos.is_finite():
		return false
	_cam_pos = world_pos
	return true


func focus_entity(entity_id: String) -> bool:
	return not entity_id.is_empty()


func current_mode() -> String:
	return _mode


func set_mode(mode_id: String) -> bool:
	if mode_id.is_empty():
		return false
	_mode = mode_id
	return true


func find_entity(_entity_id: String) -> BoardToken:
	return null


func get_entities(_active_floor_only: bool = true) -> Array[BoardToken]:
	return []


func selected_entities() -> Array[BoardToken]:
	return []


func read_entity_vitals(_entity_or_id: Variant) -> Dictionary:
	return {"ok": false, "reason": "no_vitals_provider"}


func request_roll(_expression: String, _label: String = "") -> Dictionary:
	return {"ok": false, "reason": "dice_module_inactive"}


func read_saved_module_entry(_module_id: String) -> Dictionary:
	return {}
''',
    ),
    "board_token.gd": (
        "BoardToken",
        r'''extends Node2D
class_name BoardToken

var entity_id: String = "tok_probe_01"
var display_name: String = "ProbeToken"
var selectable_in_select_mode: bool = true


func get_component_by_id(_comp_id: String) -> Node:
	return null
''',
    ),
    "comp_permission.gd": (
        "CompPermission",
        r'''extends CompBase
class_name CompPermission

var _owner_peers: PackedInt32Array = PackedInt32Array()
var _owner_player_ids: PackedStringArray = PackedStringArray()


func can_command(_peer: int) -> bool:
	return true


func can_command_in(_peer: int, _net: Object) -> bool:
	return true


func has_owner_identity(identity: String) -> bool:
	return identity in _owner_player_ids
''',
    ),
    "edit_mode_controller.gd": (
        "EditModeController",
        r'''extends Node
class_name EditModeController

var requests: Array[Dictionary] = []


func components_request(targets: Array[BoardToken], path: String, action: StringName, _guard: Callable = Callable(), _receipt: Variant = null) -> bool:
	requests.append({"targets": targets, "path": path, "action": action})
	return true
''',
    ),
    "desktop_network_session.gd": (
        "DesktopNetworkSession",
        r'''extends Node
class_name DesktopNetworkSession


static func _valid_identity(value: Variant) -> bool:
	return value is String and not String(value).is_empty()


func local_peer_id() -> int:
	return 1


func can_author_world() -> bool:
	return true


func module_lifecycle_context() -> Dictionary:
	return {"role": "solo", "local_peer_id": 1}
''',
    ),
    "extension_base.gd": (
        "ExtensionBase",
        r'''extends Node2D
class_name ExtensionBase

var ctx: ExtensionContext
var _registered: bool = false
var _retiring: bool = false
var _extension_deferred_epoch: int = 0
var _activation_pending: bool = false
var _activation_error: String = ""
var _pending_deferred_queue: Array[Dictionary] = []


func _ready() -> void:
	if _registered or _retiring:
		return
	var runtime := ExtensionContext.runtime_for(self)
	if runtime != null and runtime.has_method(&"accepting_registrations") and not bool(runtime.call(&"accepting_registrations")):
		return
	ctx = ExtensionContext.create_for(self)
	if ctx == null or not ctx.can_initialize():
		return
	_extension_deferred_epoch += 1
	_activation_pending = false
	_activation_error = ""
	_registered = true
	_on_register(ctx)


func _exit_tree() -> void:
	deregister_now()
	request_ready()


func supports_warm_scene_hibernation() -> bool:
	return false


func deregister_now() -> void:
	if _retiring:
		return
	_retiring = true
	_extension_deferred_epoch += 1
	_activation_pending = false
	_pending_deferred_queue.clear()
	if _registered:
		_registered = false
		_on_unregister()
	if ctx != null:
		ctx.revert_all()
		ctx = null
	_retiring = false


func _defer_registered(method: StringName, arguments: Array = []) -> void:
	var ctx_id: int = ctx.get_instance_id() if ctx != null else 0
	var item := {
		"epoch": _extension_deferred_epoch,
		"ctx_id": ctx_id,
		"method": method,
		"args": arguments.duplicate(),
		"done": false,
	}
	_pending_deferred_queue.append(item)
	call_deferred(&"_run_deferred_item", item)


func _run_deferred_item(item: Dictionary) -> void:
	if bool(item.get("done", false)):
		return
	item["done"] = true
	_pending_deferred_queue.erase(item)
	_run_deferred_registration(
		int(item.get("epoch", -1)),
		int(item.get("ctx_id", 0)),
		item.get("method", &"") as StringName,
		item.get("args", []) as Array
	)


func flush_deferred_registrations() -> void:
	var snapshot: Array[Dictionary] = _pending_deferred_queue.duplicate()
	_pending_deferred_queue.clear()
	for item: Dictionary in snapshot:
		if not bool(item.get("done", false)):
			item["done"] = true
			_run_deferred_registration(
				int(item.get("epoch", -1)),
				int(item.get("ctx_id", 0)),
				item.get("method", &"") as StringName,
				item.get("args", []) as Array
			)


func _run_deferred_registration(epoch: int, ctx_id: int, method: StringName, arguments: Array) -> void:
	if epoch != _extension_deferred_epoch or not _registered or is_queued_for_deletion() or ctx == null or ctx.get_instance_id() != ctx_id or not ctx.can_initialize() or ctx._quiescent:
		return
	callv(method, arguments)


func _on_register(_context: ExtensionContext) -> void:
	pass


func _on_unregister() -> void:
	pass


func serialize_module_state() -> Dictionary:
	return {}


func prepare_module_state(state: Dictionary) -> Dictionary:
	return {"ok": state.is_empty(), "reason": "unsupported_module_state" if not state.is_empty() else ""}


func apply_module_state(state: Dictionary) -> bool:
	return state.is_empty()


func hold_activation() -> Dictionary:
	if not _registered or ctx == null or not ctx.can_initialize():
		return {}
	_activation_pending = true
	return {"context": ctx, "epoch": _extension_deferred_epoch}


func finish_activation(ticket: Dictionary, accepted: bool, reason: String = "") -> bool:
	if not _registered or ctx == null or not ctx.can_initialize() or ticket.get("context") != ctx or ticket.get("epoch") != _extension_deferred_epoch:
		return false
	_activation_pending = false
	_activation_error = "" if accepted else (reason if not reason.is_empty() else "module_initialization_failed")
	return true


func activation_status() -> Dictionary:
	return {"pending": _activation_pending, "reason": _activation_error}
''',
    ),
    "extension_context.gd": (
        "ExtensionContext",
        r'''extends RefCounted
class_name ExtensionContext

var owner: Node
var slots: SlotRegistry
var hooks: HookBus
var last_rejection: String = ""

var _runtime_ref: WeakRef
var _owner_id: int = 0
var _generation: int = 0
var _closed: bool = false
var _staged: bool = false
var _quiescent: bool = false
var _tokens: Array[ExtToken] = []


static func create_for(ext_owner: Node) -> ExtensionContext:
	var runtime := runtime_for(ext_owner)
	return runtime.call(&"create_context", ext_owner) as ExtensionContext if runtime != null else null


static func runtime_for(node: Node) -> Node:
	var ancestor := node
	while is_instance_valid(ancestor):
		if ancestor.has_method(&"get_extension_runtime"):
			return ancestor.call(&"get_extension_runtime") as Node
		ancestor = ancestor.get_parent()
	return null


func _bind(ext_owner: Node, runtime: Node, generation: int, staged: bool = false) -> void:
	owner = ext_owner
	_owner_id = owner.get_instance_id()
	_runtime_ref = weakref(runtime)
	_generation = generation
	_staged = staged
	slots = runtime.get_node("SlotRegistry") as SlotRegistry
	hooks = runtime.get_node("HookBus") as HookBus


func is_active() -> bool:
	return not _staged and not _quiescent and can_initialize()


func can_initialize() -> bool:
	var runtime := _runtime()
	return not _closed and is_instance_valid(runtime)


func _can_register() -> bool:
	return not _closed and not _quiescent and can_initialize()


func publish() -> bool:
	if not can_initialize():
		return false
	_staged = false
	return true


func quiesce(value: bool) -> void:
	_quiescent = value


func runtime_node() -> Node:
	return _runtime()


func source_id() -> String:
	return String(owner.get_meta(&"module_id", "")) if is_instance_valid(owner) else ""


func get_screen_host() -> Control:
	var rt := _runtime()
	return rt.call(&"get_screen_host") as Control if is_active() and rt != null and rt.has_method(&"get_screen_host") else null


func revert_all() -> void:
	if _closed:
		return
	_closed = true
	while not _tokens.is_empty():
		var token: ExtToken = _tokens.pop_back()
		token.revert()
	owner = null
	slots = null
	hooks = null


func register_slot_item(slot_id: StringName, spec: Dictionary) -> ExtToken:
	if not _can_register() or not is_instance_valid(slots):
		return ExtToken.make(Callable(), "rejected_slot")
	var stamped := spec.duplicate(true)
	stamped["source"] = source_id()
	stamped["provider"] = owner
	var item_id := slots.register_item(slot_id, stamped)
	var registry_ref: WeakRef = weakref(slots)
	var tok := ExtToken.make(func() -> void:
		var reg := registry_ref.get_ref() as SlotRegistry
		if is_instance_valid(reg):
			reg.unregister_item(slot_id, item_id), "slot:%s#%d" % [slot_id, item_id])
	_tokens.append(tok)
	return tok


func subscribe_hook(hook_id: StringName, callback: Callable, priority: int = 0) -> ExtToken:
	if not _can_register() or not is_instance_valid(hooks):
		return ExtToken.make(Callable(), "rejected_hook")
	var sid := hooks.subscribe(hook_id, callback, priority)
	var bus_ref: WeakRef = weakref(hooks)
	var tok := ExtToken.make(func() -> void:
		var b := bus_ref.get_ref() as HookBus
		if is_instance_valid(b):
			b.unsubscribe(hook_id, sid), "hook:%s#%d" % [hook_id, sid])
	_tokens.append(tok)
	return tok


func emit_hook(hook_id: StringName, arguments: Array = []) -> bool:
	return hooks.emit_hook(hook_id, arguments) if is_active() and is_instance_valid(hooks) else false


func subscribe_signal(target: Object, signal_id: StringName, callback: Callable) -> ExtToken:
	if not _can_register() or not is_instance_valid(target) or not target.has_signal(signal_id) or not callback.is_valid():
		return ExtToken.make(Callable(), "rejected_signal")
	if not target.is_connected(signal_id, callback):
		target.connect(signal_id, callback)
	var t_ref: WeakRef = weakref(target)
	var tok := ExtToken.make(func() -> void:
		var obj := t_ref.get_ref() as Object
		if is_instance_valid(obj) and obj.is_connected(signal_id, callback):
			obj.disconnect(signal_id, callback), "signal:" + String(signal_id))
	_tokens.append(tok)
	return tok


func publish_service(service_id: String, service: Object) -> ExtToken:
	var rt := _runtime()
	if not _can_register() or rt == null or service_id.is_empty() or not is_instance_valid(service):
		return ExtToken.make(Callable(), "rejected_service")
	rt.call(&"publish_service_entry", service_id, service)
	var rt_ref: WeakRef = weakref(rt)
	var tok := ExtToken.make(func() -> void:
		var r := rt_ref.get_ref() as Node
		if is_instance_valid(r):
			r.call(&"unpublish_service_entry", service_id, service), "service:" + service_id)
	_tokens.append(tok)
	return tok


func consume_service(service_id: String) -> Object:
	var rt := _runtime()
	return rt.call(&"consume_service_entry", service_id) as Object if can_initialize() and rt != null else null


func register_component(spec: Dictionary) -> ExtToken:
	var rt := _runtime()
	if not _can_register() or rt == null:
		return ExtToken.make(Callable(), "rejected_component")
	var cid: int = int(rt.call(&"register_component_spec", spec, self))
	var rt_ref: WeakRef = weakref(rt)
	var tok := ExtToken.make(func() -> void:
		var r := rt_ref.get_ref() as Node
		if is_instance_valid(r):
			r.call(&"unregister_component_spec", cid), "comp#%d" % cid)
	_tokens.append(tok)
	return tok


func add_revert(callback: Callable, label: String = "custom") -> ExtToken:
	if not _can_register():
		return ExtToken.make(Callable(), label)
	var tok := ExtToken.make(callback, label)
	_tokens.append(tok)
	return tok


func mount_node(parent: Node, child: Node, index: int = -1) -> ExtToken:
	var rt := _runtime()
	var desktop: Node = rt.call(&"get_desktop") as Node if is_instance_valid(rt) else null
	if not _can_register() or not is_instance_valid(desktop) or not is_instance_valid(parent) or not is_instance_valid(child) or child.get_parent() != null or not (parent == desktop or desktop.is_ancestor_of(parent)):
		return ExtToken.make(Callable(), "mount_node_invalid")
	parent.add_child(child)
	if index >= 0 and index < parent.get_child_count():
		parent.move_child(child, index)
	var child_ref: WeakRef = weakref(child)
	var tok := ExtToken.make(func() -> void:
		var node := child_ref.get_ref() as Node
		if is_instance_valid(node):
			if node.has_method(&"deactivate"):
				node.call(&"deactivate")
			if node.get_parent() != null:
				node.get_parent().remove_child(node)
			node.free(), "mount_node:" + String(child.name))
	_tokens.append(tok)
	return tok


func _runtime() -> Node:
	return _runtime_ref.get_ref() as Node if _runtime_ref != null else null
''',
    ),
    "comp_base.gd": (
        "CompBase",
        r'''extends ExtensionBase
class_name CompBase

var _extra_state: Dictionary = {}
var _applying_state: bool = false
var _entity_local_content_notice: bool = false


static func id_from_path(path: String) -> String:
	return path.get_file().get_basename().trim_prefix("comp_")


func is_runtime_derived() -> bool:
	return false


func get_comp_id() -> String:
	return id_from_path(get_script().resource_path)


func default_node_name() -> String:
	return get_script().resource_path.get_file().get_basename().to_pascal_case()


func supports_host(_host: Node) -> bool:
	return true


func component_tags() -> PackedStringArray:
	return PackedStringArray()


func exclusive_group() -> String:
	return ""


func conflicts_with_components() -> PackedStringArray:
	return PackedStringArray()


func suppresses_components() -> PackedStringArray:
	return PackedStringArray()


func suppression_allowlist() -> PackedStringArray:
	return PackedStringArray()


func dominance_priority() -> int:
	return 0


func editable_fields() -> Array[String]:
	return []


func supports_partial_property_selection() -> bool:
	return true


func preset_field_resets() -> Variant:
	return null


func _exported_field_types() -> Dictionary:
	var fields := {}
	var scr: Script = get_script() as Script
	while scr != null:
		for prop: Dictionary in scr.get_script_property_list():
			var usage := int(prop.get("usage", 0))
			if (usage & PROPERTY_USAGE_STORAGE) != 0 and (usage & PROPERTY_USAGE_SCRIPT_VARIABLE) != 0:
				var pname := String(prop.get("name", ""))
				if not pname.begins_with("_"):
					fields[pname] = int(prop.get("type", TYPE_NIL))
		scr = scr.get_base_script()
	return fields


func accepts_state(state: Dictionary) -> bool:
	if not StateValue.is_data(state):
		return false
	var fields := _exported_field_types()
	for k: Variant in state:
		if not (k is String):
			return false
		if fields.has(k) and int(fields[k]) != TYPE_NIL and typeof(state[k]) != int(fields[k]):
			return false
	return true


func apply_state(state: Dictionary) -> bool:
	if not accepts_state(state):
		return false
	var fields := _exported_field_types()
	var values := state.duplicate(true)
	_applying_state = true
	for k: String in values:
		if fields.has(k):
			set(k, values[k])
		else:
			_extra_state[k] = values[k]
	_applying_state = false
	notify_data_changed()
	return true


func replace_state(state: Dictionary) -> bool:
	if not accepts_state(state):
		return false
	_extra_state.clear()
	return apply_state(state)


func serialize_state() -> Dictionary:
	var fields := _exported_field_types()
	var state := _extra_state.duplicate(true)
	for f: String in fields:
		state[f] = get(f)
	return state.duplicate(true)


func serialize_network_state() -> Dictionary:
	return serialize_state()


func get_comp_page_scene() -> String:
	return ""


func get_comp_quick_page_scene() -> String:
	return ""


func notify_data_changed() -> void:
	_entity_local_content_notice = false


func notify_entity_local_content_changed() -> void:
	_entity_local_content_notice = true
''',
    ),
    "entity_component_page.gd": (
        "EntityComponentPage",
        r'''extends VBoxContainer
class_name EntityComponentPage

signal edit_requested(action: StringName, payload: Dictionary)
signal editing_started

var component_id: String = ""


func bind_entities(_entities: Array[BoardToken]) -> void:
	pass


func refresh() -> void:
	pass


func cancel_edit() -> void:
	pass


func has_draft() -> bool:
	return false
''',
    ),
}

_SHIM_BASE_CLASSES: dict[str, str] = {
    "ExtToken": "RefCounted",
    "HookIds": "RefCounted",
    "HookBus": "Node",
    "SlotRegistry": "Node",
    "StateValue": "RefCounted",
    "DesktopApiService": "RefCounted",
    "BoardToken": "Node2D",
    "CompPermission": "CompBase",
    "EditModeController": "Node",
    "DesktopNetworkSession": "Node",
    "ExtensionBase": "Node2D",
    "ExtensionContext": "RefCounted",
    "CompBase": "ExtensionBase",
    "EntityComponentPage": "VBoxContainer",
}

INWORLD_HEADLESS_PROBE_GD = r'''extends SceneTree

## Fu vtt Monorepo `verify-host` isolated headless verification probe for in-world modules
## (`fus.desktop-module.v1` and `fus.plugin.v2`).

var _passed_checks: int = 0
var _failures: Array[String] = []
var _warnings: Array[String] = []
var _loaded_scripts: Array[String] = []
var _sdk_probe: Dictionary = {}


class _MockRuntime:
	extends Node

	var slots: SlotRegistry
	var hooks: HookBus
	var _desktop_ref: WeakRef
	var _screen_host: Control
	var _services: Dictionary = {}
	var _components: Array[Dictionary] = []
	var _next_comp_id: int = 1
	var _gen: int = 1
	var _registration_stage: bool = false

	func setup(desktop: Node, screen_host: Control) -> void:
		_desktop_ref = weakref(desktop)
		_screen_host = screen_host
		slots = SlotRegistry.new()
		slots.name = "SlotRegistry"
		add_child(slots)
		hooks = HookBus.new()
		hooks.name = "HookBus"
		add_child(hooks)

	func get_desktop() -> Node:
		return _desktop_ref.get_ref() as Node if _desktop_ref != null else null

	func get_screen_host() -> Control:
		return _screen_host

	func accepting_registrations() -> bool:
		return true

	func create_context(ext_owner: Node) -> ExtensionContext:
		var ctx := ExtensionContext.new()
		var staged: bool = _registration_stage and not bool(ext_owner.get_meta(&"module_core", false))
		ctx._bind(ext_owner, self, _gen, staged)
		return ctx

	func publish_service_entry(service_id: String, service: Object) -> void:
		_services[service_id] = service

	func unpublish_service_entry(service_id: String, service: Object) -> void:
		if _services.get(service_id) == service:
			_services.erase(service_id)

	func consume_service_entry(service_id: String) -> Object:
		return _services.get(service_id, null) as Object

	func register_component_spec(spec: Dictionary, _ctx: ExtensionContext) -> int:
		var cid := _next_comp_id
		_next_comp_id += 1
		var copy := spec.duplicate(true)
		copy["_cid"] = cid
		_components.append(copy)
		return cid

	func unregister_component_spec(cid: int) -> void:
		for idx: int in range(_components.size() - 1, -1, -1):
			if int((_components[idx] as Dictionary).get("_cid", -1)) == cid:
				_components.remove_at(idx)

	func get_registered_components() -> Array[Dictionary]:
		return _components.duplicate(true)


class _MockDesktop:
	extends Node2D

	var _runtime: _MockRuntime
	var _network_session: DesktopNetworkSession

	func set_runtime(rt: _MockRuntime) -> void:
		_runtime = rt

	func get_extension_runtime() -> Node:
		return _runtime

	func set_network_session(net: DesktopNetworkSession) -> void:
		_network_session = net

	func get_network_session() -> DesktopNetworkSession:
		return _network_session

	func can_author_world() -> bool:
		return _network_session != null and _network_session.can_author_world()


class _HybridMockHostBridge:
	extends RefCounted

	var root: String = ""
	var cache: String = ""
	var destination: String = ""
	var file: String = ""
	var settings: Dictionary = {}
	var expected_sha256: String = ""
	var progress_log: Array[String] = []
	var warnings: Array[String] = []
	var archived_urls: Array[String] = []
	var preview_started: bool = false
	var preview_entities_count: int = 0
	var geometry_sealed: bool = false

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
					"floors": [{"id": 0, "floor_uid": floor_uid, "name": "1F", "color": Color(0.28, 0.65, 0.40)}],
					"layers": {
						"schema": "fus.floor_layers.v2",
						"floors": [{
							"floor_uid": floor_uid,
							"default_layer_uid": entity_uid,
							"layers": [
								{"layer_uid": map_uid, "name": "地图底图", "kind": "map", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
								{"layer_uid": entity_uid, "name": "实体", "kind": "entity", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
								{"layer_uid": obstacle_uid, "name": "障碍物", "kind": "obstacle", "visible": true, "locked": false, "persistent": true, "access": "host", "viewers": []},
							],
						}],
					},
					"active_floor_uid": floor_uid,
				},
				"entity_state": {"version": 3, "entities": []},
				"members": [],
				"modules": {"version": 2, "entries": {}},
			},
		}

	func archive_image(url: String, _proxy: String = "") -> Dictionary:
		archived_urls.append(url)
		if url.is_empty():
			return {"ok": false, "reason": "empty_url", "reference": ""}
		var ref_id: String = url.sha256_text().left(16)
		return {"ok": true, "reference": "asset://mock_%s.png" % ref_id, "size": Vector2(256.0, 256.0), "bytes": 1024}

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
		return {"ok": true, "document": {"source": {"sha256": sha}}, "scene_items": [], "walls": [], "doors": []}


func _check(cond: bool, msg: String) -> void:
	if cond:
		_passed_checks += 1
	else:
		_failures.append(msg)


func _collect_gd_recursive(dir_path: String, out: Array[String]) -> void:
	var d := DirAccess.open(dir_path)
	if d == null:
		return
	d.list_dir_begin()
	var entry := d.get_next()
	while not entry.is_empty():
		if not entry.begins_with("."):
			var full := dir_path.path_join(entry)
			if d.current_is_dir():
				_collect_gd_recursive(full, out)
			elif entry.ends_with(".gd"):
				out.append(full)
		entry = d.get_next()
	d.list_dir_end()


func _is_ident_char(c: String) -> bool:
	if c.is_empty():
		return false
	var code := c.unicode_at(0)
	return (code >= 48 and code <= 57) or (code >= 65 and code <= 90) or (code >= 97 and code <= 122) or code == 95


func _strip_gd_comments(src: String) -> String:
	var tq_d := "\"".repeat(3)
	var tq_s := "'".repeat(3)
	var out_lines: Array[String] = []
	var in_multiline := ""
	var normalized := src.replace("\r\n", "\n").replace("\r", "\n")

	for line: String in normalized.split("\n"):
		var i := 0
		var n := line.length()
		var buf := ""
		var in_single_quote := ""

		while i < n:
			if not in_multiline.is_empty():
				if line[i] == "\\" and i + 1 < n:
					i += 2
					continue
				if line.substr(i, 3) == in_multiline:
					buf += in_multiline
					i += 3
					in_multiline = ""
				else:
					i += 1
				continue

			if not in_single_quote.is_empty():
				var ch := line[i]
				if ch == "\\" and i + 1 < n:
					i += 2
					continue
				if ch == in_single_quote:
					buf += ch
					in_single_quote = ""
				i += 1
				continue

			var ch := line[i]
			if ch == "r" and (i == 0 or not _is_ident_char(line[i - 1])):
				var sub4 := line.substr(i, 4)
				if sub4 == "r" + tq_d or sub4 == "r" + tq_s:
					in_multiline = line.substr(i + 1, 3)
					buf += sub4
					i += 4
					continue
				if i + 1 < n and (line[i + 1] == "\"" or line[i + 1] == "'"):
					in_single_quote = line[i + 1]
					buf += line.substr(i, 2)
					i += 2
					continue

			var sub3 := line.substr(i, 3)
			if sub3 == tq_d or sub3 == tq_s:
				in_multiline = sub3
				buf += in_multiline
				i += 3
				continue

			if ch == "\"" or ch == "'":
				in_single_quote = ch
				buf += ch
				i += 1
				continue

			if ch == "#":
				break

			buf += ch
			i += 1

		out_lines.append(buf)

	return "\n".join(out_lines)


func _initialize() -> void:
	var pkg_root := "res://pkg"
	var pkg_archive := ""
	var sample_path := ""
	var report_path := ""
	var ui_screenshot_path := ""
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with("--pkg-root="):
			pkg_root = arg.trim_prefix("--pkg-root=")
		elif arg.begins_with("--pkg-archive="):
			pkg_archive = arg.trim_prefix("--pkg-archive=")
		elif arg.begins_with("--sample="):
			sample_path = arg.trim_prefix("--sample=")
		elif arg.begins_with("--report="):
			report_path = arg.trim_prefix("--report=")
		elif arg.begins_with("--ui-screenshot="):
			ui_screenshot_path = arg.trim_prefix("--ui-screenshot=")

	call_deferred(&"_run_probe", pkg_root, pkg_archive, sample_path, report_path, ui_screenshot_path)


func _run_probe(pkg_root: String, pkg_archive: String, sample_path: String, report_path: String, ui_screenshot_path: String = "") -> void:
	var manifest_path := pkg_root.path_join("plugin.json")
	var manifest: Dictionary = {}
	if FileAccess.file_exists(manifest_path):
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(manifest_path))
		if parsed is Dictionary:
			manifest = parsed as Dictionary
	_check(not manifest.is_empty(), "plugin.json parsed inside probe workspace")

	var plugin_id := String(manifest.get("id", ""))
	var schema := String(manifest.get("schema", ""))
	var raw_pf: Variant = manifest.get("pack_file", "")
	var pf_str := String(raw_pf) if raw_pf != null else ""
	var raw_pck: Variant = manifest.get("pck", "")
	var pck_str := String(raw_pck) if raw_pck != null else ""
	var pack_file := pf_str if not pf_str.is_empty() else pck_str

	var mount_target := pkg_archive
	if not pack_file.is_empty():
		var pck_res := pkg_root.path_join(pack_file)
		_check(FileAccess.file_exists(pck_res), "pack_file exists in unpacked archive: " + pack_file)
		if FileAccess.file_exists(pck_res):
			var hdr := FileAccess.get_file_as_bytes(pck_res).slice(0, 4)
			_check(hdr == PackedByteArray([0x47, 0x44, 0x50, 0x43]), "pack_file starts with GDPC magic")
			mount_target = ProjectSettings.globalize_path(pck_res)

	_check(not mount_target.is_empty() and FileAccess.file_exists(mount_target), "mount pack path exists on disk")
	if not mount_target.is_empty() and FileAccess.file_exists(mount_target):
		var mounted := ProjectSettings.load_resource_pack(mount_target, false)
		_check(mounted, "ProjectSettings.load_resource_pack succeeded for " + schema)

	var ns_roots: Array[String] = []
	for base_ns: String in ["mods/" + plugin_id, "external_modules/" + plugin_id]:
		var res_ns := "res://" + base_ns
		if DirAccess.dir_exists_absolute(res_ns):
			ns_roots.append(res_ns)
	_check(not ns_roots.is_empty(), "mounted namespace root exists under res://mods/ or res://external_modules/")

	var class_name_re := RegEx.create_from_string("(?m)(?:^|;)\\s*class_name\\b")
	for ns_dir: String in ns_roots:
		var gd_files: Array[String] = []
		_collect_gd_recursive(ns_dir, gd_files)
		gd_files.sort()
		for gd_path: String in gd_files:
			var res: Resource = load(gd_path)
			_check(res is Script, "GDScript compiled cleanly: " + gd_path)
			if res is Script:
				_loaded_scripts.append(gd_path)
				var gname: StringName = (res as Script).get_global_name()
				_check(gname == &"", "No global class_name allowed in external module script: " + gd_path)
			if FileAccess.file_exists(gd_path):
				var stripped := _strip_gd_comments(FileAccess.get_file_as_string(gd_path))
				_check(class_name_re.search(stripped) == null, "No class_name declaration in source: " + gd_path)

	# Hybrid importer entry.gd contract check if manifest.entry is non-empty
	var raw_entry: Variant = manifest.get("entry", "")
	var entry_rel := String(raw_entry) if raw_entry != null else ""
	if not entry_rel.is_empty():
		var entry_res := pkg_root.path_join(entry_rel)
		if not FileAccess.file_exists(entry_res) and not ResourceLoader.exists(entry_res):
			entry_res = "res://" + entry_rel
		_check(FileAccess.file_exists(entry_res) or ResourceLoader.exists(entry_res), "Hybrid entry script exists: " + entry_rel)
		var entry_scr := load(entry_res) as Script
		_check(entry_scr != null and entry_scr.can_instantiate(), "Hybrid entry script loads and instantiates: " + entry_rel)
		if entry_scr != null:
			_loaded_scripts.append(entry_res)
			_check(entry_scr.get_global_name() == &"", "No global class_name allowed in hybrid entry script: " + entry_rel)
			var entry_inst: Variant = entry_scr.new()
			_check(entry_inst is RefCounted, "Hybrid entry script extends RefCounted: " + entry_rel)
			if entry_inst is RefCounted:
				var entry_obj := entry_inst as RefCounted
				_check(entry_obj.has_method(&"inspect_import"), "Hybrid entry implements inspect_import: " + entry_rel)
				_check(entry_obj.has_method(&"prepare_import"), "Hybrid entry implements prepare_import: " + entry_rel)
				if entry_obj.has_method(&"inspect_import") and entry_obj.has_method(&"prepare_import"):
					_check(not sample_path.is_empty() and FileAccess.file_exists(sample_path), "Hybrid sample file exists: " + sample_path)
					var options: Dictionary = {}
					for raw_field: Variant in manifest.get("settings", []) as Array:
						if raw_field is Dictionary:
							var field := raw_field as Dictionary
							var key := String(field.get("id", ""))
							if not key.is_empty():
								options[key] = field.get("default")
					var hybrid_host := _HybridMockHostBridge.new()
					hybrid_host.file = sample_path
					hybrid_host.settings = options.duplicate(true)
					hybrid_host.expected_sha256 = FileAccess.get_sha256(sample_path) if FileAccess.file_exists(sample_path) else ""
					var insp_raw: Variant = entry_obj.call(&"inspect_import", sample_path, options.duplicate(true), hybrid_host)
					_check(
						insp_raw is Dictionary and bool((insp_raw as Dictionary).get("ok", false)),
						"Hybrid entry inspect_import ok == true (reason=%s)" % [str((insp_raw as Dictionary).get("reason", "")) if insp_raw is Dictionary else "non_dict"],
					)
					var prep_raw: Variant = entry_obj.call(&"prepare_import", sample_path, options.duplicate(true), hybrid_host)
					_check(
						prep_raw is Dictionary and bool((prep_raw as Dictionary).get("ok", false)),
						"Hybrid entry prepare_import ok == true (reason=%s)" % [str((prep_raw as Dictionary).get("reason", "")) if prep_raw is Dictionary else "non_dict"],
					)
			elif entry_inst is Node:
				(entry_inst as Node).free()

	# Probe bundled fu_runtime/v2.gd if present
	for ns_dir: String in ns_roots:
		var rt_v2 := ns_dir.path_join("lib/fu_runtime/v2.gd")
		if FileAccess.file_exists(rt_v2) or ResourceLoader.exists(rt_v2):
			var rt_script := load(rt_v2) as Script
			_check(rt_script != null, "fu_runtime/v2.gd compiled cleanly")
			if rt_script != null:
				var rt_inst: Variant = rt_script.new()
				_check(rt_inst != null, "fu_runtime/v2.gd instantiated cleanly")
				_sdk_probe["runtime_v2_path"] = rt_v2
				_sdk_probe["sdk_version"] = str(rt_inst.get("SDK_VERSION")) if rt_inst != null else ""

	# Setup mock desktop hierarchy
	var desktop := _MockDesktop.new()
	desktop.name = "DesktopScreen"
	var world := Node2D.new()
	world.name = "World"
	for overlay_name: String in ["WorldOverlayBelowEntities", "WorldOverlayAboveEntities", "WorldOverlayAboveFog"]:
		var ov := Node2D.new()
		ov.name = overlay_name
		world.add_child(ov)
	desktop.add_child(world)

	var screen_host := Control.new()
	screen_host.name = "ScreenHost"
	if not ui_screenshot_path.is_empty():
		var bg_rect := ColorRect.new()
		bg_rect.name = "TabletopBackdrop"
		bg_rect.color = Color(0.15, 0.13, 0.11, 1.0)
		bg_rect.position = Vector2.ZERO
		bg_rect.size = Vector2(1440.0, 820.0)
		desktop.add_child(bg_rect)
		screen_host.position = Vector2.ZERO
		screen_host.size = Vector2(1440.0, 820.0)
		var sh_gd := GDScript.new()
		sh_gd.source_code = "extends Control\nfunc mount_floating_panel(panel: Control) -> bool:\n\tif panel == null:\n\t\treturn false\n\tif panel.get_parent() != self:\n\t\tadd_child(panel)\n\treturn true\n"
		sh_gd.reload()
		screen_host.set_script(sh_gd)
	desktop.add_child(screen_host)

	var runtime := _MockRuntime.new()
	runtime.name = "ExtensionRuntime"
	desktop.add_child(runtime)
	desktop.set_runtime(runtime)
	var net_session := DesktopNetworkSession.new()
	net_session.name = "NetworkSession"
	desktop.add_child(net_session)
	desktop.set_network_session(net_session)

	var features := Node2D.new()
	features.name = "Features"
	runtime.add_child(features)

	root.add_child(desktop)
	runtime.setup(desktop, screen_host)
	var api_service := DesktopApiService.new(desktop)
	runtime.publish_service_entry("desktop_api", api_service)

	# Instantiate each module entry_scene
	var raw_mods: Variant = manifest.get("modules", [])
	if (not (raw_mods is Array) or (raw_mods as Array).is_empty()) and manifest.get("module") is Dictionary:
		raw_mods = [manifest.get("module")]

	var mod_instances: Array[Node] = []
	var mod_id_by_instance: Dictionary = {}
	if raw_mods is Array:
		for mod_entry: Variant in (raw_mods as Array):
			if not (mod_entry is Dictionary):
				continue
			var mdict := mod_entry as Dictionary
			var raw_mid: Variant = mdict.get("id", "")
			var mid := String(raw_mid) if raw_mid != null else ""
			var raw_es: Variant = mdict.get("entry_scene", "")
			var es_str := String(raw_es) if raw_es != null else ""
			var raw_path: Variant = mdict.get("path", "")
			var path_str := String(raw_path) if raw_path != null else ""
			var scene_path := es_str if not es_str.is_empty() else path_str
			_check(ResourceLoader.exists(scene_path), "entry_scene exists in mounted resource pack: " + scene_path)
			var packed := load(scene_path) as PackedScene
			_check(packed != null, "entry_scene loaded as PackedScene: " + scene_path)
			if packed != null:
				var inst := packed.instantiate()
				_check(inst is ExtensionBase, "entry_scene root extends ExtensionBase: " + scene_path)
				if inst is ExtensionBase:
					inst.set_meta(&"module_id", mid)
					inst.set_meta(&"module_core", false)
					runtime._registration_stage = true
					features.add_child(inst)
					runtime._registration_stage = false
					mod_instances.append(inst)
					mod_id_by_instance[inst] = mid
					var eb := inst as ExtensionBase
					_check(eb.ctx != null and not eb.ctx.is_active() and eb.ctx.get_screen_host() == null, "Optional module ctx is staged during _on_register for " + mid)
					if eb.ctx != null:
						eb.ctx.publish()
					eb.flush_deferred_registrations()
					_check(eb.ctx != null and eb.ctx.is_active(), "ExtensionBase registered active ctx after publish for " + mid)
					var state_dict: Dictionary = eb.serialize_module_state()
					_check(StateValue.is_data(state_dict), "serialize_module_state returns pure StateValue data")
					var raw_bytes := var_to_bytes(state_dict)
					_check(raw_bytes.size() > 0, "var_to_bytes roundtrip succeeds for module state")
					var prep: Variant = eb.prepare_module_state({})
					_check(prep is Dictionary, "prepare_module_state returns Dictionary")
					var applied: Variant = eb.apply_module_state({})
					_check(applied is bool, "apply_module_state returns bool")
				elif inst != null:
					inst.free()

	# Validate HookBus subscriptions
	for subscribed_id: String in runtime.hooks.subscribed_ids:
		_check(
			HookIds.is_registered(StringName(subscribed_id)),
			"Subscribed hook_id is registered or valid ext/mod namespace: " + subscribed_id,
		)

	# Validate SlotRegistry items
	var owned_overlay_nodes: Array[Node] = []
	for slot_item: Dictionary in runtime.slots.get_items(&"world.overlays"):
		var spec: Dictionary = slot_item.get("spec", {})
		var band := String(spec.get("band", ""))
		_check(band in ["below_entities", "above_entities", "above_fog"], "world.overlays band valid: " + band)
		var provider: Object = spec.get("provider", null)
		var ov_node: Node = null
		if spec.get("factory") is Callable and (spec.get("factory") as Callable).is_valid():
			ov_node = (spec.get("factory") as Callable).call() as Node
		elif spec.get("scene") is PackedScene:
			ov_node = (spec.get("scene") as PackedScene).instantiate()
		elif spec.get("node") is Node:
			ov_node = spec.get("node") as Node
			if is_instance_valid(ov_node) and ov_node.get_parent() == null:
				owned_overlay_nodes.append(ov_node)
		if ov_node != null:
			_check(ov_node is CanvasItem, "world.overlays instance is CanvasItem")
			if ov_node.has_method(&"bind_provider") and provider != null:
				_check(bool(ov_node.call(&"bind_provider", provider)), "world.overlays bind_provider returns true")
			if ov_node.get_parent() == null and not (spec.get("node") is Node):
				ov_node.free()

	for slot_key: StringName in [&"ui.desktop_panels", &"ui.module_settings"]:
		for slot_item: Dictionary in runtime.slots.get_items(slot_key):
			var spec: Dictionary = slot_item.get("spec", {})
			var provider: Object = spec.get("provider", null)
			var scene_obj: PackedScene = spec.get("scene") as PackedScene
			_check(scene_obj != null, String(slot_key) + " provides PackedScene")
			if scene_obj != null:
				var ctrl := scene_obj.instantiate()
				_check(ctrl is Control, String(slot_key) + " scene root is Control")
				if ctrl.has_method(&"bind_provider") and provider != null:
					_check(bool(ctrl.call(&"bind_provider", provider)), String(slot_key) + " bind_provider returns true")
				_check(ctrl.has_method(&"deactivate"), String(slot_key) + " implements deactivate()")
				if ctrl.has_method(&"deactivate"):
					ctrl.call(&"deactivate")
				ctrl.free()

	for slot_item: Dictionary in runtime.slots.get_items(&"ui.mode_bar"):
		var spec: Dictionary = slot_item.get("spec", {})
		var mode_id := String(spec.get("id", ""))
		_check("." in mode_id, "ui.mode_bar id is dotted: " + mode_id)
		_check(spec.get("on_enter") is Callable and (spec.get("on_enter") as Callable).is_valid(), "ui.mode_bar has valid on_enter Callable")

	for slot_item: Dictionary in runtime.slots.get_items(&"ui.entity_actions"):
		var spec: Dictionary = slot_item.get("spec", {})
		var act_id := String(spec.get("id", ""))
		_check("." in act_id, "ui.entity_actions id is dotted: " + act_id)
		_check(spec.get("predicate") is Callable and spec.get("execute") is Callable, "ui.entity_actions has predicate and execute Callables")

	for slot_item: Dictionary in runtime.slots.get_items(&"network.actions"):
		var spec: Dictionary = slot_item.get("spec", {})
		var provider: Object = spec.get("provider", null)
		var owner_mid := String(mod_id_by_instance.get(provider, String(spec.get("source", ""))))
		_check(String(spec.get("id", "")) == owner_mid, "network.actions spec.id matches module_id")
		if provider != null:
			_check(provider.has_method(&"network_action_valid"), "network.actions provider implements network_action_valid")
			_check(provider.has_method(&"network_action_revoked"), "network.actions provider implements network_action_revoked")
			_check(provider.has_method(&"network_request") or provider.has_method(&"network_request_async"), "network.actions provider implements network_request")

	for slot_item: Dictionary in runtime.slots.get_items(&"network.projections"):
		var spec: Dictionary = slot_item.get("spec", {})
		var provider: Object = spec.get("provider", null)
		var owner_mid := String(mod_id_by_instance.get(provider, String(spec.get("source", ""))))
		_check(String(spec.get("id", "")) == owner_mid, "network.projections spec.id matches module_id")
		if provider != null:
			_check(provider.has_signal(&"projection_changed"), "network.projections provider declares projection_changed signal")
			for mname: String in [
				"network_projection", "network_cursor", "network_revoked",
				"validate_replica_projection", "capture_replica_projection",
				"stage_replica_projection", "publish_replica_projection", "restore_replica_projection",
			]:
				_check(provider.has_method(StringName(mname)), "network.projections provider implements " + mname)

	# Validate registered components
	for comp_spec: Dictionary in runtime.get_registered_components():
		var cpath := String(comp_spec.get("path", ""))
		var cid := String(comp_spec.get("id", ""))
		_check(
			cpath.begins_with("res://mods/" + plugin_id + "/") or cpath.begins_with("res://external_modules/" + plugin_id + "/"),
			"component path inside plugin namespace: " + cpath,
		)
		_check(not (cid in ["visual", "permission"]), "component id is not a reserved core component: " + cid)
		_check(cpath.get_file().begins_with("comp_"), "component filename begins with comp_: " + cpath.get_file())
		_check(cid == CompBase.id_from_path(cpath), "component spec.id matches CompBase.id_from_path: " + cid)
		var raw_comp: Object = null
		var comp_node: CompBase = null
		if comp_spec.get("scene") is PackedScene:
			raw_comp = (comp_spec.get("scene") as PackedScene).instantiate()
			comp_node = raw_comp as CompBase
		elif ResourceLoader.exists(cpath):
			var cscr := load(cpath) as Script
			if cscr != null:
				raw_comp = cscr.new()
				comp_node = raw_comp as CompBase
		_check(comp_node is CompBase, "component instantiates as CompBase: " + cid)
		if raw_comp != null and comp_node == null and raw_comp is Node:
			(raw_comp as Node).free()
		if comp_node != null:
			var ser: Dictionary = comp_node.serialize_state()
			_check(StateValue.is_data(ser), "component serialize_state is StateValue data: " + cid)
			_check(comp_node.accepts_state(ser), "component accepts its own serialized state: " + cid)
			var nscope := String(comp_spec.get("network_scope", "shared"))
			if nscope in ["shared", "peer"]:
				_check(comp_node.has_method(&"public_state"), "shared/peer component implements public_state(state, peer): " + cid)
				if comp_node.has_method(&"public_state"):
					var pub: Variant = comp_node.call(&"public_state", ser, 2)
					_check(pub is Dictionary and comp_node.accepts_state(pub as Dictionary), "public_state returns accepted Dictionary: " + cid)
			var page_path := comp_node.get_comp_page_scene()
			if not page_path.is_empty():
				var pscene := load(page_path) as PackedScene
				_check(pscene != null, "component page scene loads: " + page_path)
				if pscene != null:
					var page := pscene.instantiate()
					_check(page is EntityComponentPage, "component page extends EntityComponentPage: " + page_path)
					if page is EntityComponentPage:
						(page as EntityComponentPage).bind_entities([])
					page.free()
			comp_node.free()

	if not ui_screenshot_path.is_empty():
		_capture_inworld_ui_and_finish(
			schema,
			report_path,
			ui_screenshot_path,
			desktop,
			screen_host,
			runtime,
			api_service,
			mod_instances,
			owned_overlay_nodes,
		)
		return

	_teardown_and_finish_inworld(
		schema,
		report_path,
		desktop,
		runtime,
		api_service,
		mod_instances,
		owned_overlay_nodes,
		"",
	)


func _capture_inworld_ui_and_finish(
	schema: String,
	report_path: String,
	ui_screenshot_path: String,
	desktop: Node,
	screen_host: Control,
	runtime: Node,
	api_service: Object,
	mod_instances: Array[Node],
	owned_overlay_nodes: Array[Node],
) -> void:
	for mod_node: Node in mod_instances:
		if mod_node.has_method(&"_on_custom_diagnostic"):
			mod_node.call(&"_on_custom_diagnostic", {"level": "debug", "source": "sdk.probe", "message": "Rendered inside hidden Win32 --wid viewport"})
			mod_node.call(&"_on_custom_diagnostic", {"level": "warning", "source": "theme.audit", "message": "Checking console readability in --ui-wid mode"})
			mod_node.call(&"_on_custom_diagnostic", {"level": "error", "source": "sample.alert", "message": "Sample diagnostic error entry"})
		if mod_node.has_method(&"run_console_command"):
			mod_node.call(&"run_console_command", "status")

	var preview_pages: Array[Control] = []
	var preview_frames: Array[Control] = []
	var slots_obj: Variant = runtime.get("slots")
	if slots_obj is Object and (slots_obj as Object).has_method(&"get_items"):
		for slot_item: Dictionary in (slots_obj as Object).call(&"get_items", &"ui.module_settings"):
			var spec: Dictionary = slot_item.get("spec", {})
			var pscene := spec.get("scene") as PackedScene
			var prov: Object = spec.get("provider", null)
			if pscene == null:
				continue
			var pinst := pscene.instantiate()
			if not (pinst is Control):
				if pinst != null:
					pinst.free()
				continue
			var pctrl := pinst as Control
			var frame := PanelContainer.new()
			frame.position = Vector2(792.0, 48.0)
			frame.size = Vector2(608.0, 724.0)
			var margin := MarginContainer.new()
			margin.add_theme_constant_override("margin_left", 14)
			margin.add_theme_constant_override("margin_top", 12)
			margin.add_theme_constant_override("margin_right", 14)
			margin.add_theme_constant_override("margin_bottom", 12)
			frame.add_child(margin)
			margin.add_child(pctrl)
			screen_host.add_child(frame)
			if pctrl.has_method(&"bind_provider") and prov != null:
				pctrl.call(&"bind_provider", prov)
			preview_pages.append(pctrl)
			preview_frames.append(frame)
			break

	for _frame_idx: int in range(4):
		await process_frame
	RenderingServer.force_draw(false)
	var vtex: ViewportTexture = root.get_texture()
	var img: Image = vtex.get_image() if vtex != null else null
	_check(img != null and not img.is_empty(), "Captured non-empty Viewport image in --ui-wid mode")
	var saved_ok := false
	if img != null and not img.is_empty():
		saved_ok = img.save_png(ui_screenshot_path) == OK
	_check(saved_ok, "Saved --ui-wid PNG screenshot: " + ui_screenshot_path.get_file())

	for pg: Control in preview_pages:
		if is_instance_valid(pg) and pg.has_method(&"deactivate"):
			pg.call(&"deactivate")
	for fr: Control in preview_frames:
		if is_instance_valid(fr):
			if fr.get_parent() != null:
				fr.get_parent().remove_child(fr)
			fr.free()

	_teardown_and_finish_inworld(
		schema,
		report_path,
		desktop,
		runtime,
		api_service,
		mod_instances,
		owned_overlay_nodes,
		ui_screenshot_path if saved_ok else "",
	)


func _teardown_and_finish_inworld(
	schema: String,
	report_path: String,
	desktop: Node,
	runtime: Node,
	api_service: Object,
	mod_instances: Array[Node],
	owned_overlay_nodes: Array[Node],
	saved_screenshot: String,
) -> void:
	# Clean teardown (zero ObjectDB leaks; synchronous for `--headless --quit`)
	for inst: Node in mod_instances:
		if is_instance_valid(inst) and inst is ExtensionBase:
			(inst as ExtensionBase).deregister_now()
			if inst.get_parent() != null:
				inst.get_parent().remove_child(inst)
			inst.free()
	for ov_owned: Node in owned_overlay_nodes:
		if is_instance_valid(ov_owned):
			if ov_owned.get_parent() != null:
				ov_owned.get_parent().remove_child(ov_owned)
			ov_owned.free()
	runtime.call(&"unpublish_service_entry", "desktop_api", api_service)
	api_service = null
	if desktop.get_parent() != null:
		desktop.get_parent().remove_child(desktop)
	desktop.free()

	var report_data := {
		"ok": _failures.is_empty(),
		"schema": schema,
		"passed_checks": _passed_checks,
		"loaded_scripts": _loaded_scripts,
		"failures": _failures,
		"warnings": _warnings,
		"entity_count": mod_instances.size(),
		"serialized_bytes": 0,
		"sdk_probe": _sdk_probe,
		"display_driver": DisplayServer.get_name(),
	}
	if not saved_screenshot.is_empty():
		report_data["ui_screenshot"] = saved_screenshot
	if not report_path.is_empty():
		var f := FileAccess.open(report_path, FileAccess.WRITE)
		if f != null:
			f.store_string(JSON.stringify(report_data, "  ") + "\n")
			f.close()

	if _failures.is_empty():
		print("FUVTT_VERIFY_HOST PASS checks=%d scripts=%d entities=%d bytes=0" % [
			_passed_checks, _loaded_scripts.size(), mod_instances.size(),
		])
		quit(0)
	else:
		print("FUVTT_VERIFY_HOST FAIL checks=%d failures=%d" % [_passed_checks, _failures.size()])
		quit(1)
'''

FUS_HOST_PROBE_GD = r'''extends SceneTree

## Optional host-level contract verification executed against a disposable read-only staged copy
## of `<FUS_REPO_DIR>` (`DesktopFeatureCatalog` + `NetworkModuleContract` + `DesktopScreen`).

var _passed_checks: int = 0
var _failures: Array[String] = []


func _check(cond: bool, msg: String) -> void:
	if cond:
		_passed_checks += 1
	else:
		_failures.append(msg)


func _initialize() -> void:
	var pkg_archive := ""
	var pck_path := ""
	var manifest_path := ""
	var report_path := ""
	var ui_screenshot_path := ""
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with("--pkg-archive="):
			pkg_archive = arg.trim_prefix("--pkg-archive=")
		elif arg.begins_with("--pck-path="):
			pck_path = arg.trim_prefix("--pck-path=")
		elif arg.begins_with("--manifest="):
			manifest_path = arg.trim_prefix("--manifest=")
		elif arg.begins_with("--report="):
			report_path = arg.trim_prefix("--report=")
		elif arg.begins_with("--ui-screenshot="):
			ui_screenshot_path = arg.trim_prefix("--ui-screenshot=")
	call_deferred(&"_run_host_probe", pkg_archive, pck_path, manifest_path, report_path, ui_screenshot_path)


func _run_host_probe(pkg_archive: String, pck_path: String, manifest_path: String, report_path: String, ui_screenshot_path: String = "") -> void:
	var manifest: Dictionary = {}
	if not manifest_path.is_empty() and FileAccess.file_exists(manifest_path):
		var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(manifest_path))
		if parsed is Dictionary:
			manifest = parsed as Dictionary
	_check(not manifest.is_empty(), "FUS host probe parsed plugin.json")

	var mount_file := pck_path if not pck_path.is_empty() else pkg_archive
	var mounted := ProjectSettings.load_resource_pack(mount_file, false)
	_check(mounted, "FUS host mounted resource pack: " + mount_file.get_file())

	var raw_mods: Variant = manifest.get("modules", [])
	if (not (raw_mods is Array) or (raw_mods as Array).is_empty()) and manifest.get("module") is Dictionary:
		raw_mods = [manifest.get("module")]

	var ext_entries: Array[Dictionary] = []
	var choices: Array[Dictionary] = []
	var net_rows: Array[Dictionary] = []
	if raw_mods is Array:
		for item: Variant in (raw_mods as Array):
			if not (item is Dictionary):
				continue
			var m := item as Dictionary
			var raw_mid: Variant = m.get("id", "")
			var mid := String(raw_mid) if raw_mid != null else ""
			var raw_es: Variant = m.get("entry_scene", "")
			var es_str := String(raw_es) if raw_es != null else ""
			var raw_path: Variant = m.get("path", "")
			var path_str := String(raw_path) if raw_path != null else ""
			var scene_path := es_str if not es_str.is_empty() else path_str
			var raw_dn: Variant = m.get("display_name", "")
			var dn_str := String(raw_dn) if raw_dn != null else ""
			var raw_name: Variant = m.get("name", "")
			var name_str := String(raw_name) if raw_name != null else ""
			var display_name := dn_str if not dn_str.is_empty() else (name_str if not name_str.is_empty() else mid)
			var raw_local: Variant = m.get("local_only", false)
			var local_only := bool(raw_local) if raw_local != null else false
			var raw_ver: Variant = m.get("version", 1)
			var mod_ver := int(raw_ver) if raw_ver != null else 1
			var raw_net_ver: Variant = m.get("network_version", null)
			var net_ver := int(raw_net_ver) if raw_net_ver != null else (0 if local_only else 1)
			var raw_iso: Variant = m.get("isolated_lifecycle", true)
			var reqs: Variant = m.get("requires", [])
			var confs: Variant = m.get("conflicts", [])
			var supps: Variant = m.get("suppresses", [])
			var raw_desc: Variant = m.get("description", "")
			var raw_dis: Variant = m.get("disable_effect", "")
			ext_entries.append({
				"id": mid,
				"display_name": display_name,
				"path": scene_path,
				"version": mod_ver,
				"network_version": net_ver,
				"local_only": local_only,
				"isolated_lifecycle": bool(raw_iso) if raw_iso != null else true,
				"requires": reqs if reqs is Array else [],
				"conflicts": confs if confs is Array else [],
				"suppresses": supps if supps is Array else [],
				"description": String(raw_desc) if raw_desc != null else "",
				"disable_effect": String(raw_dis) if raw_dis != null else "",
			})
			choices.append({"id": mid, "enabled": true})
			if not local_only and net_ver > 0:
				net_rows.append({"id": mid, "version": net_ver})

	var CatalogScript := load("res://scenes/extension/desktop_feature_catalog.gd") as Script
	var NetContractScript := load("res://scenes/board/networking/network_module_contract.gd") as Script
	var ModuleConfigScript := load("res://scenes/extension/module_configuration.gd") as Script
	_check(CatalogScript != null and NetContractScript != null and ModuleConfigScript != null, "Loaded FUS DesktopFeatureCatalog, NetworkModuleContract & ModuleConfiguration")

	if CatalogScript != null and NetContractScript != null and ModuleConfigScript != null:
		CatalogScript.call(&"set_external_entries", ext_entries)
		var opt_ids: Array[String] = []
		for row: Dictionary in CatalogScript.call(&"optional_entries"):
			opt_ids.append(String(row.get("id", "")))
		for e: Dictionary in ext_entries:
			_check(String(e["id"]) in opt_ids, "DesktopFeatureCatalog registered external module: " + String(e["id"]))
		if not net_rows.is_empty():
			_check(bool(NetContractScript.call(&"valid_modules", net_rows)), "NetworkModuleContract.valid_modules accepts plugin modules")
		_check(bool(NetContractScript.call(&"campaign_supported", choices, {})), "NetworkModuleContract.campaign_supported accepts plugin modules")
		var wb_res: Variant = ModuleConfigScript.call(&"check_change", CatalogScript.call(&"trusted_entries"), [], choices)
		_check(wb_res is Dictionary and bool((wb_res as Dictionary).get("ok", false)), "ModuleConfiguration.check_change accepts plugin modules")

	# Instantiate real FUS ExtensionRuntime + DesktopApiService (pure-GDScript host path)
	var rt_scene := load("res://scenes/extension/extension_runtime.tscn") as PackedScene
	var api_script := load("res://scenes/extension/desktop_api_service.gd") as Script
	_check(rt_scene != null and api_script != null, "Loaded FUS extension_runtime.tscn & desktop_api_service.gd")
	if rt_scene != null and api_script != null:
		var desktop := Node2D.new()
		desktop.name = "DesktopScreen"
		var world := Node2D.new()
		world.name = "World"
		for overlay_name: String in ["WorldOverlayBelowEntities", "WorldOverlayAboveEntities", "WorldOverlayAboveFog"]:
			var ov := Node2D.new()
			ov.name = overlay_name
			world.add_child(ov)
		desktop.add_child(world)
		if not ui_screenshot_path.is_empty():
			var bg_rect := ColorRect.new()
			bg_rect.name = "TabletopBackdrop"
			bg_rect.color = Color(0.15, 0.13, 0.11, 1.0)
			bg_rect.position = Vector2.ZERO
			bg_rect.size = Vector2(2560.0, 1440.0)
			desktop.add_child(bg_rect)
		var screen_host := Control.new()
		screen_host.name = "ScreenHost"
		var sh_gd := GDScript.new()
		sh_gd.source_code = "extends Control\nfunc mount_floating_panel(panel: Control) -> bool:\n\tif panel == null:\n\t\treturn false\n\tif panel.get_parent() != self:\n\t\tadd_child(panel)\n\treturn true\n"
		sh_gd.reload()
		screen_host.set_script(sh_gd)
		if not ui_screenshot_path.is_empty():
			screen_host.position = Vector2.ZERO
			screen_host.size = Vector2(1440.0, 820.0)
			var base_theme := load("res://themes/main_menu_theme.tres") as Theme
			var wood_theme := load("res://themes/menu_packs/wood_game.tres") as Theme
			if base_theme != null:
				var comp_theme := base_theme.duplicate(false) as Theme
				if wood_theme != null:
					comp_theme.merge_with(wood_theme)
				screen_host.theme = comp_theme
				_check(screen_host.theme != null, "FUS host mounted composite wood_game.tres theme onto ScreenHost")
		desktop.add_child(screen_host)

		var runtime := rt_scene.instantiate()
		var net_script := load("res://scenes/board/networking/network_session.gd") as Script
		var net_session: Node = net_script.new() as Node if net_script != null else null
		if net_session != null:
			net_session.name = "NetworkSession"
			desktop.add_child(net_session)
		# Attach minimal get_extension_runtime() and get_network_session() wrapper script on desktop node
		var host_gd := GDScript.new()
		if net_session != null:
			host_gd.source_code = "extends Node2D\nvar _rt: Node\nvar _net: DesktopNetworkSession\nfunc get_extension_runtime() -> Node:\n\treturn _rt\nfunc get_network_session() -> DesktopNetworkSession:\n\treturn _net\nfunc can_author_world() -> bool:\n\treturn _net != null and _net.can_author_world()\n"
		else:
			host_gd.source_code = "extends Node2D\nvar _rt: Node\nvar _net: Node\nfunc get_extension_runtime() -> Node:\n\treturn _rt\nfunc get_network_session() -> Node:\n\treturn _net\nfunc can_author_world() -> bool:\n\treturn true\n"
		host_gd.reload()
		desktop.set_script(host_gd)
		desktop.set("_rt", runtime)
		desktop.set("_net", net_session)
		desktop.add_child(runtime)
		runtime.bind_desktop(desktop, screen_host)
		root.add_child(desktop)

		var api_service: Object = api_script.new(desktop)
		var host_owner := ExtensionBase.new()
		host_owner.name = "HostApiProvider"
		runtime.get_node("Features").add_child(host_owner)
		if host_owner.ctx != null:
			host_owner.ctx.publish_service("desktop_api", api_service)

		var features_node := runtime.get_node("Features")
		var mounted_mods: Array[Node] = []
		for e: Dictionary in ext_entries:
			var pscene := load(String(e["path"])) as PackedScene
			_check(pscene != null, "FUS host loaded module entry_scene: " + String(e["path"]))
			if pscene != null:
				var inst := pscene.instantiate()
				_check(inst is ExtensionBase, "Module root is FUS ExtensionBase: " + String(e["id"]))
				if inst is ExtensionBase:
					inst.set_meta(&"module_id", String(e["id"]))
					inst.set_meta(&"module_core", false)
					var staged_started: bool = runtime.has_method(&"begin_registration_stage") and bool(runtime.call(&"begin_registration_stage", inst))
					features_node.add_child(inst)
					var eb := inst as ExtensionBase
					if staged_started:
						_check(eb.ctx != null and not eb.ctx.is_active() and eb.ctx.get_screen_host() == null, "FUS ExtensionRuntime gated get_screen_host() while staged for " + String(e["id"]))
						_check(bool(runtime.call(&"finish_registration_stage", true)), "FUS ExtensionRuntime published staged module " + String(e["id"]))
					if eb.has_method(&"_on_deferred_mount"):
						eb.call(&"_on_deferred_mount")
					mounted_mods.append(inst)
					_check(eb.ctx != null and eb.ctx.is_active(), "FUS ExtensionRuntime granted active ExtensionContext to " + String(e["id"]))
		if not ui_screenshot_path.is_empty():
			_capture_fus_ui_and_finish(
				report_path,
				ui_screenshot_path,
				CatalogScript,
				desktop,
				screen_host,
				runtime,
				host_owner,
				api_service,
				mounted_mods,
			)
			return

		_teardown_fus_host(CatalogScript, desktop, runtime, host_owner, mounted_mods)
		api_service = null

	_write_fus_report_and_quit(report_path, "")


func _capture_fus_ui_and_finish(
	report_path: String,
	ui_screenshot_path: String,
	CatalogScript: Script,
	desktop: Node,
	screen_host: Control,
	runtime: Node,
	host_owner: ExtensionBase,
	api_service: Object,
	mounted_mods: Array[Node],
) -> void:
	for mod_node: Node in mounted_mods:
		if mod_node.has_method(&"_on_hook_1"):
			mod_node.call(&"_on_hook_1", {
				"actor_name": "主持",
				"d20_values": [],
				"dice": [{"burst": false, "loser": false, "set": 0, "subtract": false, "type": "d6", "value": 4}],
				"expr": "1d6",
				"is_nat1": false,
				"is_nat20": false,
				"label": "",
				"modifier": 0,
				"total": 4,
			}, "dice.rolled")
		if mod_node.has_method(&"_on_custom_diagnostic"):
			mod_node.call(&"_on_custom_diagnostic", {"level": "debug", "source": "sdk.probe", "message": "Mounted composite wood_game.tres theme under hidden Win32 --wid host"})
			mod_node.call(&"_on_custom_diagnostic", {"level": "warning", "source": "theme.audit", "message": "Checking RichTextLabel & Label contrast against dark console surface"})
			mod_node.call(&"_on_custom_diagnostic", {"level": "error", "source": "sample.alert", "message": "Sample error diagnostic line (zero network side effects)"})
		if mod_node.has_method(&"run_console_command"):
			mod_node.call(&"run_console_command", "status")

	var preview_pages: Array[Control] = []
	var preview_frames: Array[Control] = []
	var slot_reg_ui := runtime.get_node_or_null("SlotRegistry")
	if slot_reg_ui != null and slot_reg_ui.has_method(&"get_items"):
		for raw_item: Variant in slot_reg_ui.call(&"get_items", &"ui.module_settings"):
			if not (raw_item is Dictionary):
				continue
			var spec_v: Variant = (raw_item as Dictionary).get("spec", {})
			if not (spec_v is Dictionary):
				continue
			var spec_d := spec_v as Dictionary
			var pscene_ui := spec_d.get("scene") as PackedScene
			var prov_ui: Object = spec_d.get("provider", null)
			if pscene_ui == null:
				continue
			var page_inst := pscene_ui.instantiate()
			if not (page_inst is Control):
				if page_inst != null:
					page_inst.free()
				continue
			var page_ctrl := page_inst as Control
			var frame := PanelContainer.new()
			frame.name = "ModuleSettingsPreview"
			frame.theme_type_variation = &"FramePanel"
			frame.position = Vector2(792.0, 48.0)
			frame.size = Vector2(608.0, 724.0)
			var margin := MarginContainer.new()
			margin.add_theme_constant_override("margin_left", 14)
			margin.add_theme_constant_override("margin_top", 12)
			margin.add_theme_constant_override("margin_right", 14)
			margin.add_theme_constant_override("margin_bottom", 12)
			frame.add_child(margin)
			var col := VBoxContainer.new()
			col.add_theme_constant_override("separation", 10)
			margin.add_child(col)
			var hdr := Label.new()
			hdr.theme_type_variation = &"SectionTitle"
			hdr.add_theme_font_size_override("font_size", 20)
			var raw_lbl: Variant = spec_d.get("label", spec_d.get("title", "模块设置"))
			hdr.text = "模块设置 · " + (String(raw_lbl) if raw_lbl != null else "模块设置")
			col.add_child(hdr)
			col.add_child(HSeparator.new())
			col.add_child(page_ctrl)
			screen_host.add_child(frame)
			if page_ctrl.has_method(&"bind_provider") and prov_ui != null:
				page_ctrl.call(&"bind_provider", prov_ui)
			preview_pages.append(page_ctrl)
			preview_frames.append(frame)
			break

	for _frame_idx: int in range(4):
		await process_frame
	RenderingServer.force_draw(false)
	var vtex: ViewportTexture = root.get_texture()
	var img: Image = vtex.get_image() if vtex != null else null
	_check(img != null and not img.is_empty(), "FUS host captured non-empty Viewport image in --ui-wid mode")
	var saved_ok := false
	if img != null and not img.is_empty():
		saved_ok = img.save_png(ui_screenshot_path) == OK
	_check(saved_ok, "FUS host saved --ui-wid PNG screenshot: " + ui_screenshot_path.get_file())

	for pg: Control in preview_pages:
		if is_instance_valid(pg) and pg.has_method(&"deactivate"):
			pg.call(&"deactivate")
	for fr: Control in preview_frames:
		if is_instance_valid(fr):
			if fr.get_parent() != null:
				fr.get_parent().remove_child(fr)
			fr.free()

	_teardown_fus_host(CatalogScript, desktop, runtime, host_owner, mounted_mods)
	api_service = null
	_write_fus_report_and_quit(report_path, ui_screenshot_path if saved_ok else "")


func _teardown_fus_host(
	CatalogScript: Script,
	desktop: Node,
	runtime: Node,
	host_owner: ExtensionBase,
	mounted_mods: Array[Node],
) -> void:
	# Capture unparented world.overlays "node" items before deregister_now() removes SlotRegistry entries
	var owned_overlay_nodes: Array[Node] = []
	var slot_reg := runtime.get_node_or_null("SlotRegistry")
	if slot_reg != null and slot_reg.has_method(&"get_items"):
		for slot_item: Variant in slot_reg.call(&"get_items", &"world.overlays"):
			if slot_item is Dictionary:
				var spec: Variant = (slot_item as Dictionary).get("spec", {})
				if spec is Dictionary:
					var ov_raw: Variant = (spec as Dictionary).get("node", null)
					if ov_raw is Node:
						var ov_node := ov_raw as Node
						if is_instance_valid(ov_node) and ov_node.get_parent() == null and not owned_overlay_nodes.has(ov_node):
							owned_overlay_nodes.append(ov_node)
	for inst: Node in mounted_mods:
		if is_instance_valid(inst) and inst is ExtensionBase:
			(inst as ExtensionBase).deregister_now()
			if inst.get_parent() != null:
				inst.get_parent().remove_child(inst)
			inst.free()
	for ov_node: Node in owned_overlay_nodes:
		if is_instance_valid(ov_node):
			if ov_node.has_method(&"deactivate"):
				ov_node.call(&"deactivate")
			if ov_node.get_parent() != null:
				ov_node.get_parent().remove_child(ov_node)
			ov_node.free()
	host_owner.deregister_now()
	if host_owner.get_parent() != null:
		host_owner.get_parent().remove_child(host_owner)
	host_owner.free()
	if CatalogScript != null:
		var empty_entries: Array[Dictionary] = []
		CatalogScript.call(&"set_external_entries", empty_entries)
	if desktop.get_parent() != null:
		desktop.get_parent().remove_child(desktop)
	desktop.free()


func _write_fus_report_and_quit(report_path: String, saved_screenshot: String) -> void:
	var out := {
		"ok": _failures.is_empty(),
		"passed_checks": _passed_checks,
		"failures": _failures,
		"display_driver": DisplayServer.get_name(),
	}
	if not saved_screenshot.is_empty():
		out["ui_screenshot"] = saved_screenshot
	if not report_path.is_empty():
		var f := FileAccess.open(report_path, FileAccess.WRITE)
		if f != null:
			f.store_string(JSON.stringify(out, "  ") + "\n")
			f.close()
	print("FUS_HOST_PROBE %s checks=%d failures=%d" % ["PASS" if _failures.is_empty() else "FAIL", _passed_checks, _failures.size()])
	quit(0 if _failures.is_empty() else 1)
'''


class HostVerifyError(RuntimeError):
    """Raised when verify-host setup, sandbox boundary, or Godot binary resolution fails."""


@dataclass(frozen=True)
class HostVerifyResult:
    """Outcome of a single `verify-host` execution."""

    mod_name: str
    plugin_id: str
    version: str
    ok: bool
    exit_code: int
    timed_out: bool
    evidence_dir: Path
    report_path: Path
    godot_log_path: Path
    passed_checks: int
    loaded_scripts: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    log_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    entity_count: int = 0
    serialized_bytes: int = 0
    sdk_probe: dict[str, Any] = field(default_factory=dict)
    schema: str = "fus.session-plugin.v1"
    host_contract_probe: dict[str, Any] = field(default_factory=dict)
    ui_screenshot_path: Path | None = None
    ui_wid_telemetry: dict[str, Any] = field(default_factory=dict)


def analyze_godot_logs(*log_texts: str) -> list[str]:
    """Scan stdout/stderr/godot.log for engine errors, script errors, parse errors, or exit leaks."""
    findings: list[str] = []
    combined = "\n".join(text for text in log_texts if text)
    for line in combined.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if ERROR_LOG_RE.match(stripped) or LEAK_LOG_RE.match(stripped):
            if stripped not in findings:
                findings.append(stripped)
    return findings


def _write_utf8_no_bom(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n")
    path.write_bytes(normalized.encode("utf-8"))


def _render_global_script_class_cache() -> str:
    entries: list[str] = []
    for fname, (cls_name, _) in _INWORLD_HOST_SHIMS.items():
        base_cls = _SHIM_BASE_CLASSES.get(cls_name, "RefCounted")
        entries.append(
            "{\n"
            f'"base": &"{base_cls}",\n'
            f'"class": &"{cls_name}",\n'
            '"icon": "",\n'
            '"is_abstract": false,\n'
            '"is_tool": false,\n'
            '"language": &"GDScript",\n'
            f'"path": "res://_host_shims/{fname}"\n'
            "}"
        )
    return "list=[\n" + ",\n".join(entries) + "\n]\n"


def _minimal_fvtt_world_json_bytes() -> bytes:
    payload = {
        "fu_vtt_verify_host_sample": True,
        "id": "verify_host_sample",
        "name": "verify_host_sample",
        "title": "Verify Host Sample",
        "system": "dnd5e",
        "coreVersion": "10.291",
        "version": "10.291",
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_synthetic_sample(sample_dir: Path, plugin_manifest: Mapping[str, Any]) -> Path:
    """Create a deterministic synthetic sample matching the plugin's primary import extension."""
    sample_dir.mkdir(parents=True, exist_ok=True)
    exts = [
        str(e).strip().lstrip(".").lower()
        for e in (plugin_manifest.get("import_extensions") or [])
        if str(e).strip().lstrip(".")
    ]
    first_ext = exts[0] if exts else "fusdemo"

    if first_ext == "zip":
        effective_sample = sample_dir / "synthetic_sample.zip"
        with zipfile.ZipFile(effective_sample, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("world.json", _minimal_fvtt_world_json_bytes())
            zf.writestr("data/scenes.db", b"")
            zf.writestr("data/actors.db", b"")
            zf.writestr("sample.json", b'{"fu_vtt_verify_host_sample": true}\n')
        return effective_sample

    if first_ext == "fup":
        effective_sample = sample_dir / "synthetic_sample.fup"
        fup_manifest = (
            json.dumps(
                {
                    "schema": "fus.session-plugin.v1",
                    "id": "synthetic_sample",
                    "version": "0.1.0",
                    "name": "Synthetic Sample",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
        with zipfile.ZipFile(effective_sample, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("plugin.json", fup_manifest)
            zf.writestr("sample.json", b'{"fu_vtt_verify_host_sample": true}\n')
        return effective_sample

    if first_ext == "json" and str(plugin_manifest.get("id") or "") == "fvtt_world_importer":
        effective_sample = sample_dir / "world.json"
        effective_sample.write_bytes(_minimal_fvtt_world_json_bytes())
        data_dir = sample_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "scenes.db").write_bytes(b"")
        (data_dir / "actors.db").write_bytes(b"")
        return effective_sample

    effective_sample = sample_dir / f"synthetic_sample.{first_ext}"
    effective_sample.write_bytes(b'{"fu_vtt_verify_host_sample": true}\n')
    return effective_sample


def prepare_probe_workspace(
    *,
    zip_path: Path,
    plugin_manifest: Mapping[str, Any],
    evidence_dir: Path,
    sample_path: Path | None = None,
) -> dict[str, Path]:
    """Create isolated probe project, isolated profile dirs, unpacked package, and sample file."""
    probe_project = evidence_dir / "probe_project"
    pkg_dir = probe_project / "pkg"
    env_root = evidence_dir / "isolated_env"
    appdata = env_root / "appdata"
    localappdata = env_root / "localappdata"
    temp_dir = env_root / "temp"
    for directory in (probe_project, appdata, localappdata, temp_dir):
        directory.mkdir(parents=True, exist_ok=True)

    _write_utf8_no_bom(probe_project / "project.godot", PROBE_PROJECT_GODOT)
    _write_utf8_no_bom(probe_project / "headless_probe.gd", HEADLESS_PROBE_GD)
    safe_extract_zip(zip_path, pkg_dir)

    if sample_path is not None:
        resolved_sample = sample_path.expanduser().resolve()
        if not resolved_sample.is_file():
            raise HostVerifyError(f"指定的测试样本文件不存在：{resolved_sample}")
        effective_sample = resolved_sample
    else:
        effective_sample = _write_synthetic_sample(evidence_dir / "sample", plugin_manifest)

    return {
        "probe_project": probe_project,
        "pkg_dir": pkg_dir,
        "appdata": appdata,
        "localappdata": localappdata,
        "temp": temp_dir,
        "sample": effective_sample,
        "godot_log": evidence_dir / "godot.log",
        "stdout_log": evidence_dir / "stdout.log",
        "stderr_log": evidence_dir / "stderr.log",
        "report_json": evidence_dir / "verify-report.json",
    }


def prepare_inworld_probe_workspace(
    *,
    archive_path: Path,
    plugin_manifest: Mapping[str, Any],
    evidence_dir: Path,
    sample_path: Path | None = None,
) -> dict[str, Path]:
    """Create isolated probe project with `_host_shims/`, class cache, and `inworld_probe.gd`."""
    probe_project = evidence_dir / "probe_project"
    pkg_dir = probe_project / "pkg"
    shims_dir = probe_project / "_host_shims"
    godot_dir = probe_project / ".godot"
    env_root = evidence_dir / "isolated_env"
    appdata = env_root / "appdata"
    localappdata = env_root / "localappdata"
    temp_dir = env_root / "temp"
    for directory in (probe_project, shims_dir, godot_dir, appdata, localappdata, temp_dir):
        directory.mkdir(parents=True, exist_ok=True)

    _write_utf8_no_bom(probe_project / "project.godot", PROBE_PROJECT_GODOT)
    _write_utf8_no_bom(probe_project / "inworld_probe.gd", INWORLD_HEADLESS_PROBE_GD)
    for fname, (_, code) in _INWORLD_HOST_SHIMS.items():
        _write_utf8_no_bom(shims_dir / fname, code)
    _write_utf8_no_bom(godot_dir / "global_script_class_cache.cfg", _render_global_script_class_cache())
    safe_extract_zip(archive_path, pkg_dir)

    out: dict[str, Path] = {
        "probe_project": probe_project,
        "pkg_dir": pkg_dir,
        "shims_dir": shims_dir,
        "appdata": appdata,
        "localappdata": localappdata,
        "temp": temp_dir,
        "godot_log": evidence_dir / "godot.log",
        "stdout_log": evidence_dir / "stdout.log",
        "stderr_log": evidence_dir / "stderr.log",
        "report_json": evidence_dir / "verify-report.json",
    }
    raw_entry = plugin_manifest.get("entry")
    has_hybrid = (isinstance(raw_entry, str) and raw_entry != "") or bool(plugin_manifest.get("import_extensions"))
    if sample_path is not None:
        resolved_sample = sample_path.expanduser().resolve()
        if not resolved_sample.is_file():
            raise HostVerifyError(f"指定的测试样本文件不存在：{resolved_sample}")
        out["sample"] = resolved_sample
    elif has_hybrid:
        out["sample"] = _write_synthetic_sample(evidence_dir / "sample", plugin_manifest)
    return out


def _patch_staged_fus_pure_gdscript(stage_dir: Path) -> None:
    """Strip `[dotnet]`/`"C#"` and C#-dependent autoloads from the disposable staged copy."""
    pg_path = stage_dir / "project.godot"
    if pg_path.is_file():
        lines = pg_path.read_text(encoding="utf-8-sig").splitlines()
        out_lines: list[str] = []
        skip_section = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("["):
                skip_section = stripped == "[dotnet]"
                if skip_section:
                    continue
            if skip_section:
                continue
            if stripped.startswith(("PlatformRuntime=", "DevTools=")):
                continue
            cleaned_line = (
                line.replace(', "C#"', "")
                .replace('"C#", ', "")
                .replace('"C#"', "")
                .replace('"res://addons/practice_toolchain/plugin.cfg"', "")
            )
            out_lines.append(cleaned_line)
        _write_utf8_no_bom(pg_path, "\n".join(out_lines) + "\n")

    sv_path = stage_dir / "scenes" / "entities" / "state_value.gd"
    if sv_path.is_file():
        sv_text = sv_path.read_text(encoding="utf-8-sig")
        sv_text = sv_text.replace(
            'load("res://services/storage/PackedValueValidation.cs").new() if ClassDB.class_exists("CSharpScript") else null',
            "null",
        )
        _write_utf8_no_bom(sv_path, sv_text)


def _try_build_staged_csharp(stage_dir: Path, cache_dir: Path, *, timeout_seconds: int = 120) -> bool:
    """Attempt offline `dotnet build` on the disposable staged `Practice.csproj` using local NuGet cache."""
    csproj = stage_dir / "Practice.csproj"
    if not csproj.is_file() or shutil.which("dotnet") is None:
        return False
    nuget_cache = Path.home() / ".nuget" / "packages"
    if not nuget_cache.is_dir():
        return False
    dotnet_home = (cache_dir / "dotnet_home").resolve()
    dotnet_home.mkdir(parents=True, exist_ok=True)
    build_env = dict(os.environ)
    build_env["DOTNET_CLI_HOME"] = str(dotnet_home)
    build_env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    build_env["DOTNET_NOLOGO"] = "1"
    build_env["NUGET_PACKAGES"] = str(nuget_cache)
    try:
        proc = subprocess.run(
            ["dotnet", "build", "Practice.csproj", "--source", str(nuget_cache), "-v:q"],
            cwd=str(stage_dir),
            env=build_env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _stage_fus_repo_readonly(
    fus_repo_dir: Path,
    cache_dir: Path,
    *,
    godot_exe: Path,
    env: Mapping[str, str],
    exec_fn: Callable[..., tuple[int, str, str, bool]],
    timeout_seconds: int,
) -> Path:
    """Create or reuse a disposable read-only copy of `fus_repo_dir` under `.cache/fus_host_stage/`."""
    if not fus_repo_dir.is_dir() or not (fus_repo_dir / "project.godot").is_file():
        raise HostVerifyError(f"官方 FUS 只读仓无效（缺少 project.godot）：{fus_repo_dir}")

    stage_key = "local"
    use_git_archive = False
    if (fus_repo_dir / ".git").exists():
        rev_proc = subprocess.run(
            ["git", "-C", str(fus_repo_dir), "rev-parse", "--short=12", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if rev_proc.returncode == 0 and rev_proc.stdout.strip():
            stage_key = rev_proc.stdout.strip()
            use_git_archive = True

    stage_dir = (cache_dir / "fus_host_stage" / f"{stage_key}_v3").resolve()
    if not stage_dir.is_relative_to(cache_dir.resolve()):
        raise HostVerifyError(f"安全边界拦截：FUS 暂存目录越出 .cache：{stage_dir}")

    ready_marker = stage_dir / ".fuvtt_stage_ready"
    if not ready_marker.is_file():
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
        stage_dir.mkdir(parents=True, exist_ok=True)
        if use_git_archive:
            arch_proc = subprocess.run(
                ["git", "-C", str(fus_repo_dir), "archive", "--format=tar", "HEAD"],
                capture_output=True,
                timeout=60,
            )
            if arch_proc.returncode != 0:
                raise HostVerifyError(
                    f"无法从只读 FUS 仓库导出 git archive：{arch_proc.stderr.decode('utf-8', errors='replace')}"
                )
            with tarfile.open(fileobj=io.BytesIO(arch_proc.stdout), mode="r:") as tf:
                for member in tf.getmembers():
                    if member.name.startswith("/") or ".." in Path(member.name).parts:
                        continue
                    if member.issym() or member.islnk():
                        continue
                    target = (stage_dir / member.name).resolve()
                    if not target.is_relative_to(stage_dir):
                        continue
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        extracted = tf.extractfile(member)
                        if extracted is not None:
                            target.write_bytes(extracted.read())
        else:
            shutil.copytree(
                fus_repo_dir,
                stage_dir,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(".git", ".godot", "build", "test-results"),
            )

        cs_built = _try_build_staged_csharp(stage_dir, cache_dir, timeout_seconds=timeout_seconds)
        if not cs_built:
            _patch_staged_fus_pure_gdscript(stage_dir)
        # Warm-import resources once inside the disposable stage directory
        import_cmd = [
            str(godot_exe),
            "--headless",
            "--editor",
            "--import",
            "--quit",
            "--path",
            str(stage_dir),
        ]
        exec_fn(import_cmd, cwd=stage_dir, env=env, timeout_seconds=timeout_seconds)
        _write_utf8_no_bom(ready_marker, f"staged={stage_key}\ncsharp={cs_built}\n")

    return stage_dir


def _exec_godot_with_optional_wid(
    *,
    godot_exe: Path,
    base_args_after_mode: list[str],
    user_args: list[str],
    cwd: Path,
    env: Mapping[str, str],
    exec_fn: Callable[..., tuple[int, str, str, bool]],
    use_real_wid_window: bool,
    ui_wid: bool,
    timeout_seconds: int,
) -> tuple[int, str, str, bool, dict[str, Any]]:
    """Run Godot either in fast `--headless --quit` mode or inside a hidden Win32 `--wid` host."""
    if not ui_wid:
        cmd = [str(godot_exe), "--headless", "--quit", *base_args_after_mode, "--", *user_args]
        rc, out, err, timed_out = exec_fn(cmd, cwd=cwd, env=env, timeout_seconds=timeout_seconds)
        return rc, out, err, timed_out, {}

    if not use_real_wid_window:
        wid_flags = build_wid_godot_args(65536, width=1440, height=820, quit_after=1200)
        cmd = [str(godot_exe), *wid_flags, *base_args_after_mode, "--", *user_args]
        rc, out, err, timed_out = exec_fn(cmd, cwd=cwd, env=env, timeout_seconds=timeout_seconds)
        return rc, out, err, timed_out, {
            "hwnd": 65536,
            "width": 1440,
            "height": 820,
            "focus_unchanged": True,
            "parent_visible": False,
            "mocked": True,
        }

    with HiddenWin32WindowHost(width=1440, height=820) as wid_host:
        wid_flags = list(wid_host.build_godot_args(quit_after=1200))
        cmd = [str(godot_exe), *wid_flags, *base_args_after_mode, "--", *user_args]
        rc, out, err, timed_out = exec_fn(cmd, cwd=cwd, env=env, timeout_seconds=timeout_seconds)
        tel = wid_host.snapshot_telemetry()
        telemetry_dict: dict[str, Any] = {
            "hwnd": tel.hwnd,
            "width": tel.width,
            "height": tel.height,
            "foreground_before": tel.foreground_before,
            "foreground_after": tel.foreground_after,
            "focus_unchanged": tel.focus_unchanged,
            "parent_visible": tel.parent_visible,
        }
    return rc, out, err, timed_out, telemetry_dict


def _run_staged_fus_host_probe(
    *,
    fus_repo_dir: Path,
    cfg: WorkspaceConfig,
    godot_exe: Path,
    artifact: Any,
    evidence_dir: Path,
    child_env: Mapping[str, str],
    exec_fn: Callable[..., tuple[int, str, str, bool]],
    timeout_seconds: int,
    ui_wid: bool = False,
    use_real_wid_window: bool = True,
) -> tuple[dict[str, Any], list[str], list[str], Path | None, dict[str, Any]]:
    """Run host-level verification against a disposable staged copy of `<FUS_REPO_DIR>`."""
    stage_dir = _stage_fus_repo_readonly(
        fus_repo_dir,
        cfg.cache_dir,
        godot_exe=godot_exe,
        env=child_env,
        exec_fn=exec_fn,
        timeout_seconds=timeout_seconds,
    )
    probe_script = evidence_dir / "fus_host_probe.gd"
    report_json = evidence_dir / "fus-host-report.json"
    godot_log = evidence_dir / "fus_host.log"
    manifest_copy = evidence_dir / "fus_host_manifest.json"
    screenshot_file = evidence_dir / "ui_wid_screenshot.png"
    _write_utf8_no_bom(probe_script, FUS_HOST_PROBE_GD)
    _write_utf8_no_bom(
        manifest_copy,
        json.dumps(artifact.plugin_manifest, ensure_ascii=False, indent=2) + "\n",
    )

    pck_arg = ""
    if getattr(artifact, "pck_path", None) is not None and Path(artifact.pck_path).is_file():
        pck_arg = Path(artifact.pck_path).resolve().as_posix()

    base_args = [
        "--path",
        str(stage_dir),
        "--log-file",
        str(godot_log),
        "--script",
        str(probe_script.resolve()),
    ]
    user_args = [
        f"--pkg-archive={artifact.zip_path.resolve().as_posix()}",
        f"--pck-path={pck_arg}",
        f"--manifest={manifest_copy.resolve().as_posix()}",
        f"--report={report_json.resolve().as_posix()}",
    ]
    if ui_wid:
        user_args.append(f"--ui-screenshot={screenshot_file.resolve().as_posix()}")

    exit_code, stdout_text, stderr_text, timed_out, wid_tel = _exec_godot_with_optional_wid(
        godot_exe=godot_exe,
        base_args_after_mode=base_args,
        user_args=user_args,
        cwd=stage_dir,
        env=child_env,
        exec_fn=exec_fn,
        use_real_wid_window=use_real_wid_window,
        ui_wid=ui_wid,
        timeout_seconds=timeout_seconds,
    )
    _write_utf8_no_bom(evidence_dir / "fus_host_stdout.log", stdout_text)
    _write_utf8_no_bom(evidence_dir / "fus_host_stderr.log", stderr_text)
    host_log_text = godot_log.read_text(encoding="utf-8", errors="replace") if godot_log.is_file() else ""
    host_log_errors = analyze_godot_logs(host_log_text, stdout_text, stderr_text)

    host_failures: list[str] = []
    payload: dict[str, Any] = {}
    if report_json.is_file():
        try:
            parsed = json.loads(report_json.read_text(encoding="utf-8-sig"))
            if isinstance(parsed, dict):
                payload = parsed
            else:
                host_failures.append("fus-host-report.json 顶层结构不是 JSON Object。")
        except (OSError, ValueError) as exc:
            host_failures.append(f"fus-host-report.json 解析失败：{exc}")
    else:
        host_failures.append("FUS 宿主探针未生成 fus-host-report.json。")

    if timed_out:
        host_failures.append(f"FUS 宿主探针超时（>{timeout_seconds}s）。")
    if exit_code != 0:
        host_failures.append(f"FUS 宿主探针返回非零退出码：{exit_code}。")
    for item in payload.get("failures", []):
        host_failures.append(str(item))

    resolved_shot: Path | None = None
    if ui_wid:
        if wid_tel.get("parent_visible"):
            host_failures.append("Win32 --wid 隐藏宿主窗口意外可见 (parent_visible == True)。")
        if screenshot_file.is_file() and screenshot_file.stat().st_size > 0:
            resolved_shot = screenshot_file
        elif use_real_wid_window:
            host_failures.append("FUS --ui-wid 渲染未生成有效的 ui_wid_screenshot.png。")

    payload["exit_code"] = exit_code
    payload["timed_out"] = timed_out
    payload["stage_dir"] = str(stage_dir)
    if wid_tel:
        payload["ui_wid_telemetry"] = wid_tel
    return payload, host_failures, host_log_errors, resolved_shot, wid_tel


def _default_godot_runner(
    cmd: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: int,
) -> tuple[int, str, str, bool]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=dict(env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.returncode, proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
        err = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")
        return 124, out, err, True
    except OSError as exc:
        raise HostVerifyError(f"无法启动 Godot 无头进程：{exc}") from exc


def verify_mod_with_host(
    mod_name: str,
    config: WorkspaceConfig | None = None,
    *,
    sample_path: Path | str | None = None,
    godot_bin: Path | str | None = None,
    timeout_seconds: int = 120,
    runner: Callable[..., tuple[int, str, str, bool]] | None = None,
    fus_repo: Path | str | None = None,
    ui_wid: bool = False,
) -> HostVerifyResult:
    """Build (if stale) and verify a plugin package inside isolated headless or `--wid` Godot 4.8-beta1."""
    cfg = config or load_config()
    clean_name = mod_name.strip()
    resolved_godot = cfg.resolve_godot_bin(override_bin=godot_bin)
    if runner is None and not resolved_godot.is_file():
        raise HostVerifyError(
            f"找不到 Godot 控制台可执行文件：{cfg.redact_path(resolved_godot)}。"
            " 请在 .env.local 配置 GODOT_BIN 或通过 --godot-bin 指定。"
        )

    artifact, _ = _load_or_build_artifact(clean_name, cfg, godot_bin=godot_bin)
    schema = str(artifact.plugin_manifest.get("schema") or "fus.session-plugin.v1")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"{stamp}_{uuid.uuid4().hex[:6]}"
    evidence_dir = (cfg.build_dir / clean_name / "verify_evidence" / run_id).resolve()
    if not evidence_dir.is_relative_to(cfg.workspace_root):
        raise HostVerifyError(f"安全边界拦截：验证证据目录越出工作区：{evidence_dir}")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    has_fus_repo = fus_repo is not None and bool(str(fus_repo).strip())
    inworld_wid_direct = bool(ui_wid and (schema in INWORLD_SCHEMAS) and (not has_fus_repo))
    primary_shot_file = evidence_dir / "ui_wid_screenshot.png"

    if schema in INWORLD_SCHEMAS:
        paths = prepare_inworld_probe_workspace(
            archive_path=artifact.zip_path,
            plugin_manifest=artifact.plugin_manifest,
            evidence_dir=evidence_dir,
            sample_path=Path(sample_path) if sample_path is not None else None,
        )
        base_args = [
            "--path",
            str(paths["probe_project"]),
            "--log-file",
            str(paths["godot_log"]),
            "--script",
            "res://inworld_probe.gd",
        ]
        user_args = [
            "--pkg-root=res://pkg",
            f"--pkg-archive={artifact.zip_path.resolve().as_posix()}",
            f"--report={paths['report_json'].as_posix()}",
        ]
        if "sample" in paths:
            user_args.append(f"--sample={paths['sample'].as_posix()}")
        if inworld_wid_direct:
            user_args.append(f"--ui-screenshot={primary_shot_file.resolve().as_posix()}")
    else:
        paths = prepare_probe_workspace(
            zip_path=artifact.zip_path,
            plugin_manifest=artifact.plugin_manifest,
            evidence_dir=evidence_dir,
            sample_path=Path(sample_path) if sample_path is not None else None,
        )
        base_args = [
            "--path",
            str(paths["probe_project"]),
            "--log-file",
            str(paths["godot_log"]),
            "--script",
            "res://headless_probe.gd",
        ]
        user_args = [
            "--pkg-root=res://pkg",
            f"--sample={paths['sample'].as_posix()}",
            f"--report={paths['report_json'].as_posix()}",
        ]

    child_env = dict(os.environ)
    child_env["APPDATA"] = str(paths["appdata"])
    child_env["LOCALAPPDATA"] = str(paths["localappdata"])
    child_env["TEMP"] = str(paths["temp"])
    child_env["TMP"] = str(paths["temp"])
    child_env["GODOT_SILENCE_ROOT_WARNING"] = "1"

    exec_fn = runner or _default_godot_runner
    exit_code, stdout_text, stderr_text, timed_out, ui_wid_telemetry = _exec_godot_with_optional_wid(
        godot_exe=resolved_godot,
        base_args_after_mode=base_args,
        user_args=user_args,
        cwd=paths["probe_project"],
        env=child_env,
        exec_fn=exec_fn,
        use_real_wid_window=(runner is None),
        ui_wid=inworld_wid_direct,
        timeout_seconds=timeout_seconds,
    )

    _write_utf8_no_bom(paths["stdout_log"], stdout_text)
    _write_utf8_no_bom(paths["stderr_log"], stderr_text)
    godot_log_text = (
        paths["godot_log"].read_text(encoding="utf-8", errors="replace")
        if paths["godot_log"].is_file()
        else ""
    )

    log_errors = analyze_godot_logs(godot_log_text, stdout_text, stderr_text)

    report_payload: dict[str, Any] = {}
    failures: list[str] = []
    if paths["report_json"].is_file():
        try:
            parsed = json.loads(paths["report_json"].read_text(encoding="utf-8-sig"))
            if isinstance(parsed, dict):
                report_payload = parsed
            else:
                failures.append("verify-report.json 顶层结构不是 JSON Object。")
        except (OSError, ValueError) as exc:
            failures.append(f"verify-report.json 解析失败：{exc}")
    else:
        failures.append("无头探针未生成 verify-report.json（可能发生启动崩溃或编译失败）。")

    if timed_out:
        failures.append(f"Godot 无头校验超时（>{timeout_seconds}s）。")
    if exit_code != 0:
        failures.append(f"Godot 无头进程返回非零退出码：{exit_code}。")

    for rep_fail in report_payload.get("failures", []):
        failures.append(str(rep_fail))

    ui_screenshot_path: Path | None = None
    if inworld_wid_direct:
        if ui_wid_telemetry.get("parent_visible"):
            failures.append("Win32 --wid 隐藏宿主窗口意外可见 (parent_visible == True)。")
        if primary_shot_file.is_file() and primary_shot_file.stat().st_size > 0:
            ui_screenshot_path = primary_shot_file
        elif runner is None:
            failures.append("局内 --ui-wid 渲染未生成有效的 ui_wid_screenshot.png。")

    host_contract_probe: dict[str, Any] = {}
    if has_fus_repo:
        override_repo = None if str(fus_repo).strip().lower() == "auto" else fus_repo
        try:
            resolved_fus_repo = cfg.resolve_fus_repo_dir(override_repo=override_repo)
        except ConfigError as exc:
            raise HostVerifyError(str(exc)) from exc
        if schema in INWORLD_SCHEMAS:
            host_contract_probe, host_failures, host_log_errors, fus_shot, fus_tel = _run_staged_fus_host_probe(
                fus_repo_dir=resolved_fus_repo,
                cfg=cfg,
                godot_exe=resolved_godot,
                artifact=artifact,
                evidence_dir=evidence_dir,
                child_env=child_env,
                exec_fn=exec_fn,
                timeout_seconds=timeout_seconds,
                ui_wid=ui_wid,
                use_real_wid_window=(runner is None),
            )
            failures.extend(host_failures)
            log_errors.extend(host_log_errors)
            if fus_shot is not None:
                ui_screenshot_path = fus_shot
            if fus_tel:
                ui_wid_telemetry = fus_tel

    warnings_list = [str(w) for w in report_payload.get("warnings", [])]
    if ui_wid and schema not in INWORLD_SCHEMAS:
        warnings_list.append("纯局外插件 (fus.session-plugin.v1) 无局内桌面 UI，已自动跳过 --ui-wid 视口截图。")

    probe_ok = bool(report_payload.get("ok", False))
    host_ok = bool(host_contract_probe.get("ok", True)) if host_contract_probe else True
    overall_ok = (
        (not timed_out)
        and (exit_code == 0)
        and probe_ok
        and host_ok
        and (len(failures) == 0)
        and (len(log_errors) == 0)
    )

    return HostVerifyResult(
        mod_name=clean_name,
        plugin_id=artifact.plugin_id,
        version=artifact.version,
        ok=overall_ok,
        exit_code=exit_code,
        timed_out=timed_out,
        evidence_dir=evidence_dir,
        report_path=paths["report_json"],
        godot_log_path=paths["godot_log"],
        passed_checks=int(report_payload.get("passed_checks", 0)),
        loaded_scripts=[str(x) for x in report_payload.get("loaded_scripts", [])],
        failures=failures,
        log_errors=log_errors,
        warnings=warnings_list,
        entity_count=int(report_payload.get("entity_count", 0)),
        serialized_bytes=int(report_payload.get("serialized_bytes", 0)),
        sdk_probe=(
            dict(report_payload["sdk_probe"])
            if isinstance(report_payload.get("sdk_probe"), dict)
            else {}
        ),
        schema=schema,
        host_contract_probe=host_contract_probe,
        ui_screenshot_path=ui_screenshot_path,
        ui_wid_telemetry=ui_wid_telemetry,
    )


def verify_mods_with_host(
    config: WorkspaceConfig | None = None,
    *,
    mod_name: str | None = None,
    select_all: bool = False,
    include_template: bool = False,
    sample_path: Path | str | None = None,
    godot_bin: Path | str | None = None,
    timeout_seconds: int = 120,
    runner: Callable[..., tuple[int, str, str, bool]] | None = None,
    fus_repo: Path | str | None = None,
    ui_wid: bool = False,
) -> list[HostVerifyResult]:
    """Run `verify_mod_with_host` across one or multiple selected mods."""
    cfg = config or load_config()
    targets = resolve_target_mods(
        cfg,
        mod_name=mod_name,
        select_all=select_all,
        include_template=include_template,
    )
    results: list[HostVerifyResult] = []
    for name in targets:
        results.append(
            verify_mod_with_host(
                name,
                config=cfg,
                sample_path=sample_path,
                godot_bin=godot_bin,
                timeout_seconds=timeout_seconds,
                runner=runner,
                fus_repo=fus_repo,
                ui_wid=ui_wid,
            )
        )
    return results
