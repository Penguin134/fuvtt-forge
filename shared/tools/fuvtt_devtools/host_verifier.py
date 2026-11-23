"""Godot 4.8-beta1 Mono Headless plugin verification harness (`verify-host` subcommand).

Runs an isolated headless Godot probe project inside `build/<mod-name>/verify_evidence/<run-id>/`,
compiling every `.gd` script in the packaged ZIP, instantiating `entry.gd`, driving
`inspect_import()` and `prepare_import()` through a faithful Practice `MockHostBridge`,
and verifying world schema invariants + real Godot `bytes_to_var(var_to_bytes(world))` roundtrip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping
import uuid

from .deployer import _load_or_build_artifact, safe_extract_zip
from .env_config import WorkspaceConfig, load_config
from .validator import resolve_target_mods


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

	# 3. Call inspect_import()
	var inspect_raw: Variant = plugin_obj.call("inspect_import", sample_path, options.duplicate(true), host)
	_expect(inspect_raw is Dictionary, "inspect_import returns Dictionary")
	if inspect_raw is Dictionary:
		var inspect_res: Dictionary = inspect_raw as Dictionary
		_expect(bool(inspect_res.get("ok", false)),
				"inspect_import ok == true (reason=%s)" % str(inspect_res.get("reason", "")))
		var sha_str: String = String(inspect_res.get("sha256", ""))
		var expected_sha: String = FileAccess.get_sha256(sample_path)
		_expect(sha_str.length() == 64 and sha_str == expected_sha,
				"inspect_import returns 64-hex sha256 matching sample file")
		var counts_v: Variant = inspect_res.get("counts", null)
		_expect(counts_v is Dictionary and (counts_v as Dictionary).has("unsupported"),
				"inspect_import returns counts Dictionary with unsupported key")
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

	report_data["warnings"] = host.warnings
	_write_and_exit(report_path, report_data)


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

		# Transform finiteness & non-zero scale
		var xform_v: Variant = ent.get("xform", null)
		_expect(xform_v is Dictionary, "entity[%d].xform is Dictionary" % idx)
		if xform_v is Dictionary:
			var xf: Dictionary = xform_v as Dictionary
			var pos_v: Variant = xf.get("pos", null)
			var rot_v: Variant = xf.get("rot", null)
			var scale_v: Variant = xf.get("scale", null)
			_expect(pos_v is Vector2 and is_finite((pos_v as Vector2).x) and is_finite((pos_v as Vector2).y),
					"entity[%d].xform.pos is finite Vector2" % idx)
			_expect((rot_v is float or rot_v is int) and is_finite(float(rot_v)),
					"entity[%d].xform.rot is finite number" % idx)
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
				var c_script: String = String(cdict.get("script", ""))
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
		_expect(mods_v is Dictionary and int((mods_v as Dictionary).get("version", -1)) == 2
				and (mods_v as Dictionary).get("entries", null) is Dictionary,
				"world.modules has version == 2 and entries Dictionary")
		if mods_v is Dictionary and (mods_v as Dictionary).get("entries", null) is Dictionary:
			_expect(var_to_bytes(mods_v).size() <= 24 * 1024 * 1024,
					"world.modules var_to_bytes <= 24 MiB")
			var entries_dict: Dictionary = (mods_v as Dictionary)["entries"] as Dictionary
			for mid: Variant in entries_dict.keys():
				var entry_v: Variant = entries_dict[mid]
				if entry_v is Dictionary and (entry_v as Dictionary).get("state", null) is Dictionary:
					_expect(var_to_bytes((entry_v as Dictionary)["state"]).size() <= 16 * 1024 * 1024,
							"world.modules.entries.%s var_to_bytes <= 16 MiB" % str(mid))
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
        exts = plugin_manifest.get("import_extensions") or ["fusdemo"]
        first_ext = str(exts[0]) if isinstance(exts, list) and exts else "fusdemo"
        sample_dir = evidence_dir / "sample"
        sample_dir.mkdir(parents=True, exist_ok=True)
        effective_sample = sample_dir / f"synthetic_sample.{first_ext}"
        effective_sample.write_bytes(b'{"fu_vtt_verify_host_sample": true}\n')

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
) -> HostVerifyResult:
    """Build (if stale) and verify a plugin package inside isolated headless Godot 4.8-beta1."""
    cfg = config or load_config()
    clean_name = mod_name.strip()
    resolved_godot = cfg.resolve_godot_bin(override_bin=godot_bin)
    if runner is None and not resolved_godot.is_file():
        raise HostVerifyError(
            f"找不到 Godot 控制台可执行文件：{cfg.redact_path(resolved_godot)}。"
            " 请在 .env.local 配置 GODOT_BIN 或通过 --godot-bin 指定。"
        )

    artifact, _ = _load_or_build_artifact(clean_name, cfg)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"{stamp}_{uuid.uuid4().hex[:6]}"
    evidence_dir = (cfg.build_dir / clean_name / "verify_evidence" / run_id).resolve()
    if not evidence_dir.is_relative_to(cfg.workspace_root):
        raise HostVerifyError(f"安全边界拦截：验证证据目录越出工作区：{evidence_dir}")
    evidence_dir.mkdir(parents=True, exist_ok=True)

    paths = prepare_probe_workspace(
        zip_path=artifact.zip_path,
        plugin_manifest=artifact.plugin_manifest,
        evidence_dir=evidence_dir,
        sample_path=Path(sample_path) if sample_path is not None else None,
    )

    cmd = [
        str(resolved_godot),
        "--headless",
        "--quit",
        "--path",
        str(paths["probe_project"]),
        "--log-file",
        str(paths["godot_log"]),
        "--script",
        "res://headless_probe.gd",
        "--",
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
    exit_code, stdout_text, stderr_text, timed_out = exec_fn(
        cmd,
        cwd=paths["probe_project"],
        env=child_env,
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

    probe_ok = bool(report_payload.get("ok", False))
    overall_ok = (not timed_out) and (exit_code == 0) and probe_ok and (len(failures) == 0) and (len(log_errors) == 0)

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
        warnings=[str(w) for w in report_payload.get("warnings", [])],
        entity_count=int(report_payload.get("entity_count", 0)),
        serialized_bytes=int(report_payload.get("serialized_bytes", 0)),
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
            )
        )
    return results
