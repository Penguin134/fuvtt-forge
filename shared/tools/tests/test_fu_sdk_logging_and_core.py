"""Tests for FuSdk M1: LogBus (R3), ModuleRegistry (R2), parked/manual, and 5 Core Plugin SDKs."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
import uuid
import zipfile

_TESTS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _TESTS_DIR.parent
_WORKSPACE_ROOT = _TOOLS_DIR.parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from fuvtt_devtools.env_config import WorkspaceConfig, load_config  # noqa: E402
from fuvtt_devtools.host_verifier import analyze_godot_logs  # noqa: E402
from fuvtt_devtools.packager import build_mod  # noqa: E402

SDK_DIR = _WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk"
TEST_TMP_ROOT = _WORKSPACE_ROOT / ".cache" / "test_tmp"

EXPECTED_CORE_MODULES = {
    "feature_networking",
    "feature_component_sync",
    "feature_edit_mode",
    "feature_floor_system",
    "feature_layer_stack",
    "feature_obstacle_authoring",
    "feature_debug_hooks",
    "feature_component_library",
    "feature_entity_library",
}

EXPECTED_OPTIONAL_MODULES = {
    "campaign_time",
    "image_flip",
    "drag_movement",
    "drawing",
    "areas",
    "room_chat",
    "checklist",
    "player_cursors",
    "resource_pool",
    "map_fog_editor",
    "grid_alignment",
    "detached_sidebar",
    "character_roster",
    "portal",
    "backpack",
    "dnd_opportunity",
    "follow",
    "simple_fog",
    "dice",
    "candidate_initiative",
    "scene_box",
}

EXPECTED_CANDIDATES = {
    "entity_notes",
    "music_board",
    "module_example",
}


class TestFuSdkM1PurePython(unittest.TestCase):
    """Pure-Python structural, catalog, and packager bundling checks for M1."""

    def test_module_registry_catalog_completeness_in_source(self) -> None:
        reg_path = SDK_DIR / "plugins" / "module_registry.gd"
        self.assertTrue(reg_path.is_file())
        text = reg_path.read_text(encoding="utf-8")
        for mod_id in EXPECTED_CORE_MODULES | EXPECTED_OPTIONAL_MODULES | EXPECTED_CANDIDATES:
            self.assertIn(f'"{mod_id}"', text, f"Missing module {mod_id} in module_registry.gd")
        self.assertIn('"feature_module_example"', text)
        self.assertEqual(len(EXPECTED_CORE_MODULES), 9)
        self.assertEqual(len(EXPECTED_OPTIONAL_MODULES), 21)
        self.assertEqual(len(EXPECTED_CANDIDATES), 3)

    def test_packager_bundles_logging_and_core_plugin_scripts(self) -> None:
        case_dir = TEST_TMP_ROOT / f"m1_pack_{uuid.uuid4().hex[:10]}"
        try:
            ws = case_dir / "ws"
            mods_dir = ws / "mods"
            mod_dir = mods_dir / "sample-m1-mod"
            sdk_copy = ws / "shared" / "sdk" / "fu_sdk"
            build_dir = ws / "build"
            shutil.copytree(_WORKSPACE_ROOT / "mods" / "_template", mod_dir)
            shutil.copytree(SDK_DIR, sdk_copy)

            manifest_path = mod_dir / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["id"] = "sample_m1_mod"
            manifest["name"] = "Sample M1 Mod"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            cfg = WorkspaceConfig(
                workspace_root=ws,
                mods_dir=mods_dir,
                sdk_dir=sdk_copy,
                build_dir=build_dir,
                cache_dir=ws / ".cache",
            )
            res = build_mod("sample-m1-mod", config=cfg)
            self.assertTrue(res.zip_path.is_file())
            with zipfile.ZipFile(res.zip_path, "r") as zf:
                names = set(zf.namelist())
            for expected_rel in (
                "lib/fu_sdk/v1.gd",
                "lib/fu_sdk/logging/log_bus.gd",
                "lib/fu_sdk/plugins/module_registry.gd",
                "lib/fu_sdk/plugins/feature_edit_mode.gd",
                "lib/fu_sdk/plugins/feature_floor_system.gd",
                "lib/fu_sdk/plugins/feature_layer_stack.gd",
                "lib/fu_sdk/plugins/feature_obstacle_authoring.gd",
                "lib/fu_sdk/plugins/feature_entity_library.gd",
            ):
                self.assertIn(expected_rel, names, f"Bundled zip missing {expected_rel}")
        finally:
            shutil.rmtree(case_dir, ignore_errors=True)


_PROBE_GD = r'''extends SceneTree

func _parse_out_arg() -> String:
	for a: String in OS.get_cmdline_user_args():
		if a.begins_with("--out="):
			return a.substr(6)
	return ""

func _write_json(path: String, data: Dictionary) -> void:
	var f := FileAccess.open(path, FileAccess.WRITE)
	f.store_string(JSON.stringify(data))
	f.close()

class MockHost extends RefCounted:
	var warnings: Array = []
	var reports: Array = []
	var root: String = ""
	var destination: String = ""
	var mock_store: RefCounted = null
	var world_data: Dictionary = {}

	func cancelled() -> bool:
		return false

	func report(msg: String) -> void:
		reports.append(msg)

	func warn(msg: String) -> void:
		warnings.append(msg)

	func empty_world() -> Dictionary:
		var fuid := "00000000000000000000000000000001"
		var map_uid := "10000000000000000000000000000001"
		var ent_uid := "20000000000000000000000000000001"
		var obs_uid := "30000000000000000000000000000001"
		world_data = {
			"format": "fus.practice.world",
			"version": 3,
			"catalog": {
				"floor_identity_version": 1,
				"active_floor_uid": fuid,
				"floors": [
					{"id": 0, "floor_uid": fuid, "name": "1F", "color": Color(0.28, 0.65, 0.40)},
				],
				"layers": {
					"schema": "fus.floor_layers.v2",
					"floors": [
						{
							"floor_uid": fuid,
							"default_layer_uid": ent_uid,
							"layers": [
								{"layer_uid": map_uid, "name": "地图底图", "kind": "map", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
								{"layer_uid": ent_uid, "name": "实体", "kind": "entity", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
								{"layer_uid": obs_uid, "name": "障碍物", "kind": "obstacle", "visible": true, "locked": false, "persistent": true, "access": "host", "viewers": []},
							],
						},
					],
				},
			},
			"entity_state": {"version": 3, "entities": []},
			"members": [],
			"modules": {"version": 2, "entries": {}},
		}
		return {"ok": true, "data": world_data}

class MockNullOkHost extends RefCounted:
	func empty_world() -> Variant:
		return JSON.parse_string('{"ok": null}')

class MockJsonNullFloorHost extends RefCounted:
	var _floor_null: bool = false
	func _init(floor_null: bool = false) -> void:
		_floor_null = floor_null
	func empty_world() -> Variant:
		var fuid_json := "null" if _floor_null else '"00000000000000000000000000000001"'
		return JSON.parse_string(
			'{"ok": true, "data": {"format": "fus.practice.world", "version": 3, "catalog": {"active_floor_uid": null, "floors": [{"id": 0, "floor_uid": %s, "name": "1F"}], "layers": {"schema": "fus.floor_layers.v2", "floors": [{"floor_uid": %s, "default_layer_uid": "20000000000000000000000000000001", "layers": [{"layer_uid": "10000000000000000000000000000001", "kind": "map"}, {"layer_uid": "20000000000000000000000000000001", "kind": "entity"}, {"layer_uid": "30000000000000000000000000000001", "kind": "obstacle"}]}]}}}}' % [fuid_json, fuid_json]
		)

class TypedSubscriberHelper extends RefCounted:
	var calls: int = 0
	func on_int(_x: int) -> void:
		calls += 1
	func on_dict(_entry: Dictionary) -> void:
		calls += 1

class MockNullRevisionStore extends RefCounted:
	var records: Dictionary = {}
	func OpenLibrary(_root: String) -> String:
		return JSON.stringify({"ok": true})
	func ReadLibraryRecords(_root: String) -> Dictionary:
		var recs := records.duplicate(true)
		recs["null_rec_id"] = null
		return {"ok": true, "records": recs, "revision": null}
	func WriteLibraryRecord(_root: String, rec_id: String, _expected: PackedByteArray, desired: PackedByteArray, _rev: String) -> String:
		records[rec_id] = desired
		return JSON.stringify({"ok": true, "revision": null})
	func AdoptLibraryAsset(_root: String, _campaign: String, _ref: String) -> String:
		return JSON.stringify({"ok": true})
	func ShareLibraryAsset(_root: String, _ref: String) -> String:
		return JSON.stringify({"ok": true})

func _make_deep_dict(levels: int, leaf: Variant = {}) -> Dictionary:
	var d: Variant = leaf
	for _i: int in range(levels):
		d = {"k": d}
	return d as Dictionary if d is Dictionary else {}

func _make_dag(levels: int, leaf: Variant = null) -> Dictionary:
	var node: Dictionary = (leaf as Dictionary).duplicate() if leaf is Dictionary else {"leaf": 1}
	for _i: int in range(levels):
		node = {"l": node, "r": node}
	return node

func _make_arr_dag(levels: int, leaf: Variant = null) -> Array:
	var node: Array = [leaf, leaf]
	for _i: int in range(levels - 1):
		node = [node, node]
	return node

func _measure_depth_rec(node: Variant, depth: int, seen_per_depth: Array) -> Dictionary:
	if not (node is Dictionary or node is Array):
		return {"max_depth": depth - 1 if depth > 0 else 0, "non_empty_at_32": false}
	if depth >= 32:
		var ne32: bool = not node.is_empty() if depth == 32 else true
		return {"max_depth": depth, "non_empty_at_32": ne32}
	var bucket: Array = seen_per_depth[depth] as Array
	for pair_v: Variant in bucket:
		var pair: Array = pair_v as Array
		if is_same(pair[0], node):
			return pair[1] as Dictionary
	var max_d: int = depth
	var ne: bool = false
	if node is Dictionary:
		var d: Dictionary = node as Dictionary
		if not d.is_empty():
			var ks: Array = d.keys()
			var vs: Array = d.values()
			for idx: int in range(ks.size()):
				var kr: Dictionary = _measure_depth_rec(ks[idx], depth + 1, seen_per_depth)
				max_d = maxi(max_d, int(kr["max_depth"]))
				ne = ne or bool(kr["non_empty_at_32"])
				var vr: Dictionary = _measure_depth_rec(vs[idx], depth + 1, seen_per_depth)
				max_d = maxi(max_d, int(vr["max_depth"]))
				ne = ne or bool(vr["non_empty_at_32"])
	else:
		var arr: Array = node as Array
		for item: Variant in arr:
			var ir: Dictionary = _measure_depth_rec(item, depth + 1, seen_per_depth)
			max_d = maxi(max_d, int(ir["max_depth"]))
			ne = ne or bool(ir["non_empty_at_32"])
	var res := {"max_depth": max_d, "non_empty_at_32": ne}
	bucket.append([node, res])
	return res

func _measure_depth_and_check_empty_32(v: Variant) -> Dictionary:
	var seen_per_depth: Array = []
	for _i: int in range(34):
		seen_per_depth.append([])
	return _measure_depth_rec(v, 0, seen_per_depth)

class MockFeatureManager extends RefCounted:
	var _rows: Array = []
	func _init(rows: Array) -> void:
		_rows = rows
	func snapshot() -> Dictionary:
		return {"rows": _rows, "healthy": true, "campaign_blockers": []}

class MockFeatureManagerChoices extends RefCounted:
	var _choices: Array = []
	func _init(choices: Array) -> void:
		_choices = choices
	func module_choices() -> Array:
		return _choices

class MockAssetStore extends RefCounted:
	var revision: int = 1
	var records: Dictionary = {}
	var write_calls: int = 0

	func OpenLibrary(_root: String) -> String:
		return JSON.stringify({"ok": true})

	func ReadLibraryRecords(_root: String) -> Dictionary:
		return {
			"ok": true,
			"records": records.duplicate(true),
			"revision": str(revision),
		}

	func WriteLibraryRecord(
		_root: String,
		rec_id: String,
		expected_bytes: PackedByteArray,
		desired_bytes: PackedByteArray,
		expected_rev: String
	) -> String:
		if expected_rev != str(revision):
			return JSON.stringify({"ok": false, "reason": "revision_mismatch"})
		var cur: PackedByteArray = records.get(rec_id, PackedByteArray())
		if cur != expected_bytes:
			return JSON.stringify({"ok": false, "reason": "expected_bytes_mismatch"})
		write_calls += 1
		if cur == desired_bytes:
			return JSON.stringify({"ok": true, "changed": false, "revision": str(revision)})
		revision += 1
		if desired_bytes.is_empty():
			records.erase(rec_id)
		else:
			records[rec_id] = desired_bytes
		return JSON.stringify({"ok": true, "changed": true, "revision": str(revision)})

	func AdoptLibraryAsset(_root: String, _campaign: String, _asset_ref: String) -> String:
		return JSON.stringify({"ok": true})

	func ShareLibraryAsset(_root: String, _asset_ref: String) -> String:
		return JSON.stringify({"ok": true})

	func Publish(dest: String, reference: String, bytes: PackedByteArray) -> String:
		var body: String = reference.substr(8)
		var assets_dir: String = dest.path_join("assets")
		DirAccess.make_dir_recursive_absolute(assets_dir)
		var fpath: String = assets_dir.path_join(body)
		var existed: bool = FileAccess.file_exists(fpath)
		var f := FileAccess.open(fpath, FileAccess.WRITE)
		if f == null:
			return JSON.stringify({"ok": false, "reason": "write_failed"})
		f.store_buffer(bytes)
		f.close()
		return JSON.stringify({"ok": true, "reused": existed, "new_bytes": 0 if existed else bytes.size()})

func _record_has_component(raw_bytes: PackedByteArray, target_script: String) -> bool:
	var decoded: Variant = bytes_to_var(raw_bytes)
	if not (decoded is Dictionary):
		return false
	var rec: Dictionary = (decoded as Dictionary).get("record", {})
	var snap: Dictionary = rec.get("snapshot", {})
	var ents: Array = snap.get("entities", [])
	if ents.is_empty() or not (ents[0] is Dictionary):
		return false
	var comps: Array = (ents[0] as Dictionary).get("components", [])
	for raw_c: Variant in comps:
		if raw_c is Dictionary and str((raw_c as Dictionary).get("script", "")) == target_script:
			return true
	return false

func _r13_check_ghost_invariants(b: RefCounted, cap: int = 128, prob_cap: int = 128) -> Array:
	var fails: Array = []
	var ghost: Array = b.ghost as Array
	var ghost_h: Array = b.ghost_h as Array
	var ghost_hits: Array = b.ghost_hits as Array
	var ghost_work: Array = b.ghost_work as Array
	var ghost_clock: Array = b.ghost_clock as Array
	var ghost_by_h: Dictionary = b.ghost_by_h as Dictionary
	if ghost.size() > cap:
		fails.append("ghost_over_cap:%d" % ghost.size())
	if ghost.size() != ghost_h.size():
		fails.append("ghost_h_len:%d!=%d" % [ghost.size(), ghost_h.size()])
	if ghost.size() != ghost_hits.size():
		fails.append("ghost_hits_len:%d!=%d" % [ghost.size(), ghost_hits.size()])
	if ghost.size() != ghost_work.size():
		fails.append("ghost_work_len:%d!=%d" % [ghost.size(), ghost_work.size()])
	if ghost.size() != ghost_clock.size():
		fails.append("ghost_clock_len:%d!=%d" % [ghost.size(), ghost_clock.size()])
	for i: int in range(ghost.size()):
		for j: int in range(i + 1, ghost.size()):
			if is_same(ghost[i], ghost[j]):
				fails.append("ghost_dup:%d,%d" % [i, j])
				break
	var by_h_total: int = 0
	var per_h_expected: Dictionary = {}
	for i: int in range(ghost.size()):
		var h: int = int(ghost_h[i])
		if not per_h_expected.has(h):
			per_h_expected[h] = []
		(per_h_expected[h] as Array).append(ghost[i])
	for h_key: Variant in ghost_by_h.keys():
		var bucket_arr: Array = ghost_by_h[h_key] as Array
		if bucket_arr.is_empty():
			fails.append("empty_ghost_by_h:%s" % str(h_key))
		by_h_total += bucket_arr.size()
	if by_h_total != ghost.size():
		fails.append("by_h_total:%d!=%d" % [by_h_total, ghost.size()])
	for h_exp: Variant in per_h_expected.keys():
		if not ghost_by_h.has(h_exp):
			fails.append("missing_h:%s" % str(h_exp))
			continue
		var exp_arr: Array = per_h_expected[h_exp] as Array
		var act_arr: Array = ghost_by_h[h_exp] as Array
		if exp_arr.size() != act_arr.size():
			fails.append("h_size:%s:%d!=%d" % [str(h_exp), exp_arr.size(), act_arr.size()])
			continue
		for j: int in range(exp_arr.size()):
			if not is_same(exp_arr[j], act_arr[j]):
				fails.append("order_mismatch:%s:%d" % [str(h_exp), j])
				break

	var ghost_prob: Array = b.ghost_prob as Array
	var ghost_prob_h: Array = b.ghost_prob_h as Array
	var ghost_prob_hits: Array = b.ghost_prob_hits as Array
	var ghost_prob_by_h: Dictionary = b.ghost_prob_by_h as Dictionary
	if ghost_prob.size() > prob_cap:
		fails.append("ghost_prob_over_cap:%d" % ghost_prob.size())
	if ghost_prob.size() != ghost_prob_h.size():
		fails.append("ghost_prob_h_len:%d!=%d" % [ghost_prob.size(), ghost_prob_h.size()])
	if ghost_prob.size() != ghost_prob_hits.size():
		fails.append("ghost_prob_hits_len:%d!=%d" % [ghost_prob.size(), ghost_prob_hits.size()])
	for i: int in range(ghost_prob.size()):
		for j: int in range(i + 1, ghost_prob.size()):
			if is_same(ghost_prob[i], ghost_prob[j]):
				fails.append("ghost_prob_dup:%d,%d" % [i, j])
				break
		for g_ref: Variant in ghost:
			if is_same(ghost_prob[i], g_ref):
				fails.append("cross_tier_dup:%d" % i)
				break
	var gp_by_h_total: int = 0
	var per_hp_expected: Dictionary = {}
	for i: int in range(ghost_prob.size()):
		var hp: int = int(ghost_prob_h[i])
		if not per_hp_expected.has(hp):
			per_hp_expected[hp] = []
		(per_hp_expected[hp] as Array).append(ghost_prob[i])
	for hp_key: Variant in ghost_prob_by_h.keys():
		var p_bucket_arr: Array = ghost_prob_by_h[hp_key] as Array
		if p_bucket_arr.is_empty():
			fails.append("empty_ghost_prob_by_h:%s" % str(hp_key))
		gp_by_h_total += p_bucket_arr.size()
	if gp_by_h_total != ghost_prob.size():
		fails.append("gp_by_h_total:%d!=%d" % [gp_by_h_total, ghost_prob.size()])
	for hp_exp: Variant in per_hp_expected.keys():
		if not ghost_prob_by_h.has(hp_exp):
			fails.append("missing_hp:%s" % str(hp_exp))
			continue
		var exp_p_arr: Array = per_hp_expected[hp_exp] as Array
		var act_p_arr: Array = ghost_prob_by_h[hp_exp] as Array
		if exp_p_arr.size() != act_p_arr.size():
			fails.append("hp_size:%s:%d!=%d" % [str(hp_exp), exp_p_arr.size(), act_p_arr.size()])
			continue
		for j: int in range(exp_p_arr.size()):
			if not is_same(exp_p_arr[j], act_p_arr[j]):
				fails.append("prob_order_mismatch:%s:%d" % [str(hp_exp), j])
				break
	if b.get("ghost_prob_cursor") != null:
		var gp_cur: int = int(b.get("ghost_prob_cursor"))
		if gp_cur < 0 or (prob_cap > 0 and gp_cur >= prob_cap):
			fails.append("ghost_prob_cursor_oob:%d" % gp_cur)
	return fails


func _init() -> void:
	var out_path := _parse_out_arg()
	var sdk_script := load("res://shared/sdk/fu_sdk/v1.gd") as Script
	var sdk = sdk_script.new()
	var dag_cloner: Variant = load("res://shared/sdk/fu_sdk/utils/dag_cloner.gd")
	var bounded_cloner: Variant = load("res://shared/sdk/fu_sdk/utils/bounded_cloner.gd")
	var value_utils: Variant = load("res://shared/sdk/fu_sdk/utils/value_utils.gd")
	var validation_utils: Variant = load("res://shared/sdk/fu_sdk/utils/validation_utils.gd")
	var results := {}

	# 1. LogBus tests
	var lb_res := {}
	var bus = sdk.create_logger({"max_entries": 5, "min_level": 10, "emit_to_engine": false})
	lb_res["const_levels_ok"] = (
		bus.LEVEL_DEBUG == 10
		and bus.LEVEL_INFO == 20
		and bus.LEVEL_WARNING == 30
		and bus.LEVEL_ERROR == 40
		and bus.DEFAULT_MAX_ENTRIES == 512
	)
	var seen_events := []
	var unsub_holder := {"token": -1, "calls_after": 0}
	var tok1: int = bus.subscribe(func(entry: Dictionary) -> void:
		seen_events.append(entry)
	)
	var tok2_box := {"id": -1}
	tok2_box["id"] = bus.subscribe(func(_entry: Dictionary) -> void:
		unsub_holder["calls_after"] += 1
		bus.unsubscribe(int(tok2_box["id"]))
	)
	bus.debug("src_a", "d1", {"k": 1})
	bus.info("src_a", "i1")
	bus.warn("src_a", "w1")
	bus.error("src_a", "e1")
	bus.debug("src_a", "d2")
	bus.info("src_a", "i2")
	bus.warn("src_a", "w2")
	lb_res["ring_size"] = bus.size()
	lb_res["last_seq"] = bus.get_last_seq()
	lb_res["seen_count"] = seen_events.size()
	lb_res["unsub_during_cb_calls"] = unsub_holder["calls_after"]
	lb_res["unsub_tok1"] = bus.unsubscribe(tok1)
	lb_res["unsub_tok1_again"] = bus.unsubscribe(tok1)
	var warns_all: Array = bus.get_warnings(0)
	lb_res["warns_count"] = warns_all.size()
	lb_res["entries_since_5"] = bus.get_entries(0, 5, 0).size()
	lb_res["entries_limit_2"] = bus.get_entries(0, 0, 2).size()

	bus.set_min_level(bus.LEVEL_WARNING)
	var filtered_out: Dictionary = bus.info("src_b", "ignored")
	lb_res["min_level_filtered"] = filtered_out.is_empty()
	bus.set_min_level(bus.LEVEL_DEBUG)
	bus.clear()
	lb_res["size_after_clear"] = bus.size()

	# Host warning dedup + 100 unique + 7000 char budget + forward_reports
	var host_cap := MockHost.new()
	var bus_host = sdk.create_logger({"emit_to_engine": false})
	bus_host.attach_import_host(host_cap, false)
	bus_host.info("session", "not_forwarded")
	lb_res["reports_when_false"] = host_cap.reports.size()
	bus_host.attach_import_host(host_cap, true)
	bus_host.info("session", "forwarded_report")
	lb_res["reports_when_true"] = host_cap.reports.size()
	bus_host.warn("session", "dup_warn")
	bus_host.warn("session", "dup_warn")
	lb_res["dedup_warn_count"] = host_cap.warnings.size()
	for i: int in range(150):
		bus_host.warn("session", "unique_warn_%03d" % i)
	lb_res["cap_100_count"] = host_cap.warnings.size()

	var host_chars := MockHost.new()
	var bus_chars = sdk.create_logger({"emit_to_engine": false})
	bus_chars.attach_import_host(host_chars, false)
	var big_msg := ""
	for _k: int in range(2500):
		big_msg += "x"
	for j: int in range(5):
		bus_chars.warn("session", "%d_%s" % [j, big_msg])
	var joined_len := "\n".join(PackedStringArray(host_chars.warnings)).length()
	lb_res["joined_len_le_7000"] = joined_len <= 7000
	lb_res["bus_retained_all_5"] = bus_chars.size() == 5
	bus_chars.detach_import_host()
	lb_res["detached_ok"] = not bus_chars.has_import_host()

	# Verify ImportSession.add_warning does not double-call host.warn
	var host_sess := MockHost.new()
	var sess = sdk.create_session(host_sess, {})
	sess.get_logger().set_emit_to_engine(false)
	sess.add_warning("single_warning_only")
	lb_res["session_host_warn_count"] = host_sess.warnings.size()
	lb_res["session_bus_warn_count"] = sess.get_logger().get_warnings().size()

	# Regression (Challenger 1 #2): create_logger with JSON null option values
	var null_opts_parsed: Variant = JSON.parse_string('{"max_entries": null, "min_level": null, "emit_to_engine": null, "forward_reports": null}')
	var null_opts: Dictionary = (null_opts_parsed as Dictionary).duplicate() if null_opts_parsed is Dictionary else {}
	var host_null_opts := MockHost.new()
	null_opts["host"] = host_null_opts
	var bus_null_opts = sdk.create_logger(null_opts)
	var null_opts_ok: bool = (
		bus_null_opts != null
		and bus_null_opts.get_max_entries() == bus_null_opts.DEFAULT_MAX_ENTRIES
		and bus_null_opts.get_min_level() == bus_null_opts.LEVEL_DEBUG
		and bus_null_opts.is_emit_to_engine()
		and bus_null_opts.has_import_host()
	)
	if bus_null_opts != null:
		bus_null_opts.set_emit_to_engine(false)
		bus_null_opts.info("session", "should_not_forward_on_null")
		null_opts_ok = null_opts_ok and host_null_opts.reports.is_empty()
	lb_res["create_logger_null_opts_ok"] = null_opts_ok

	# Regression (Iter 5 Challenger 1 #5 & #6): cyclic context + bad-arity subscriber callable
	var cyc_ctx: Dictionary = {"tag": "cyc"}
	cyc_ctx["self"] = cyc_ctx
	cyc_ctx["branch"] = cyc_ctx
	var cyc_arr: Array = []
	cyc_arr.append(cyc_arr)
	cyc_ctx["arr"] = cyc_arr
	var cyc_entry: Dictionary = bus.info("cyc_src", "cyc_msg", cyc_ctx)
	var bad_sub0: int = bus.subscribe(func() -> void: pass)
	var bad_sub2: int = bus.subscribe(func(_a: Variant, _b: Variant) -> void: pass)
	var bound_seen := []
	var bound_cb := func(entry: Dictionary, tag: String) -> void:
		bound_seen.append(str(entry.get("message", "")) + ":" + tag)
	var good_bound_sub: int = bus.subscribe(bound_cb.bind("ok"))
	bus.info("arity_src", "arity_msg")
	bus.unsubscribe(good_bound_sub)
	lb_res["cyclic_and_arity_ok"] = (
		not cyc_entry.is_empty()
		and str(cyc_entry.get("message", "")) == "cyc_msg"
		and cyc_entry.get("context", {}).get("tag", "") == "cyc"
		and cyc_entry.get("context", {}).get("self", "NOT_NULL") == null
		and bad_sub0 == -1
		and bad_sub2 == -1
		and good_bound_sub > 0
		and bound_seen == ["arity_msg:ok"]
	)

	# Iter 7 Regression 7: LogBus re-entrancy >32 & typed object-method subscriber
	var bus_re = sdk.create_logger({"max_entries": 128, "min_level": 10, "emit_to_engine": false})
	var re_state := {"count": 0}
	var re_tok: int = bus_re.subscribe(func(_entry: Dictionary) -> void:
		re_state["count"] += 1
		if int(re_state["count"]) < 50:
			bus_re.info("re_src", "re_%d" % int(re_state["count"]))
	)
	bus_re.info("re_src", "re_0")
	var re_count_after: int = int(re_state["count"])
	var re_size_after: int = bus_re.size()
	bus_re.unsubscribe(re_tok)
	var typed_helper := TypedSubscriberHelper.new()
	var sub_int_tok: int = bus_re.subscribe(Callable(typed_helper, "on_int"))
	var sub_dict_tok: int = bus_re.subscribe(Callable(typed_helper, "on_dict"))
	bus_re.info("typed_src", "typed_msg")
	lb_res["reentrancy_and_typed_sub_ok"] = (
		re_count_after == 32
		and re_size_after >= 32
		and sub_int_tok == -1
		and sub_dict_tok > 0
		and typed_helper.calls == 1
	)
	results["log_bus"] = lb_res

	# 2. ModuleRegistry & backward-compat pre-setup tests
	var mr_res := {}
	var pre_builder = sdk.create_world_builder(null, 150.0)
	pre_builder.get_logger().set_emit_to_engine(false)
	pre_builder.set_enabled_modules(["simple_fog", "drawing"])
	pre_builder.set_disabled_module_policy("preserve")
	var reg = pre_builder.get_module_registry()
	mr_res["all_count"] = reg.list_modules(true).size()
	mr_res["catalog_count"] = reg.list_modules(false).size()
	mr_res["simple_fog_enabled"] = pre_builder.is_module_enabled("simple_fog")
	mr_res["drawing_enabled"] = pre_builder.is_module_enabled("drawing")
	mr_res["portal_disabled"] = not pre_builder.is_module_enabled("portal")
	mr_res["portal_status"] = reg.get_module_status("portal")
	mr_res["campaign_status"] = reg.get_module_status("campaign_time")
	mr_res["dnd_opp_status"] = reg.get_module_status("dnd_opportunity")
	mr_res["entity_notes_status"] = reg.get_module_status("entity_notes")
	mr_res["music_board_status"] = reg.get_module_status("music_board")
	mr_res["module_example_status"] = reg.get_module_status("module_example")
	mr_res["alias_status"] = reg.get_module_status("feature_module_example")
	mr_res["alias_resolved_id"] = reg.get_module_entry("feature_module_example").get("id", "")
	mr_res["core_status"] = reg.get_module_status("feature_edit_mode")
	mr_res["core_stays_locked"] = not reg.set_module_enabled("feature_edit_mode", false) and reg.is_module_enabled("feature_edit_mode")
	mr_res["comp_lookup_fog"] = reg.find_module_for_component("res://modules/simple_fog/comp_simple_vision.gd")
	mr_res["comp_lookup_init"] = reg.find_module_for_component("res://scenes/candidates/initiative/components/comp_initiative.gd")
	mr_res["stateless_debug"] = bool(reg.get_module_entry("feature_debug_hooks").get("stateless", false))
	mr_res["stateless_chat"] = bool(reg.get_module_entry("room_chat").get("stateless", false))
	mr_res["stateless_music"] = bool(reg.get_module_entry("music_board").get("stateless", false))
	mr_res["stateless_example"] = bool(reg.get_module_entry("module_example").get("stateless", false))

	# Bind session later (fvtt-world-importer pattern)
	var host_mr := MockHost.new()
	var sess_mr = sdk.create_session(host_mr, {})
	sess_mr.get_logger().set_emit_to_engine(false)
	var setup_ok: Dictionary = pre_builder.setup(sess_mr, 150.0)
	mr_res["late_setup_ok"] = bool(setup_ok.get("ok", false))
	mr_res["preserved_simple_fog"] = pre_builder.is_module_enabled("simple_fog")
	mr_res["logger_adopted"] = pre_builder.get_logger() == sess_mr.get_logger()

	# R2 check_and_warn under preserve vs skip
	var gate_preserve: Dictionary = reg.check_and_warn("portal", "attach_portal")
	mr_res["preserve_ok"] = bool(gate_preserve.get("ok", false)) and not bool(gate_preserve.get("skipped", true))
	mr_res["preserve_warn_logged"] = sess_mr.get_logger().get_warnings().size() == 1 and host_mr.warnings.size() == 1
	mr_res["preserve_warn_names_id"] = str(gate_preserve.get("warning", "")).contains("portal")

	pre_builder.set_disabled_module_policy("skip")
	var gate_blocked: Dictionary = reg.check_and_warn("campaign_time", "set_clock")
	mr_res["skip_blocked_ok"] = not bool(gate_blocked.get("ok", true)) and bool(gate_blocked.get("skipped", false))
	mr_res["skip_blocked_reason"] = str(gate_blocked.get("reason", ""))
	var gate_cand: Dictionary = reg.check_and_warn("entity_notes", "attach_note")
	mr_res["skip_cand_ok"] = not bool(gate_cand.get("ok", true)) and bool(gate_cand.get("skipped", false))

	# Override playtest_blocked via set_module_blocked
	reg.set_module_blocked("campaign_time", false)
	reg.set_module_enabled("campaign_time", true)
	mr_res["unblocked_campaign_enabled"] = reg.is_module_enabled("campaign_time")

	# probe_feature_manager with MockFeatureManager
	var fm := MockFeatureManager.new([
		{"id": "feature_edit_mode", "enabled": true},
		{"id": "checklist", "enabled": true},
		{"id": "campaign_time", "enabled": false, "activation_blocked_reason": "blocked_v062"},
	])
	mr_res["probe_ok"] = pre_builder.probe_feature_manager(fm)
	mr_res["probed_checklist_enabled"] = pre_builder.is_module_enabled("checklist")
	mr_res["probed_simple_fog_now_off"] = not pre_builder.is_module_enabled("simple_fog")
	mr_res["probed_campaign_blocked"] = reg.get_module_status("campaign_time") == "playtest_blocked"

	# Regression: live snapshot explicitly unblocking campaign_time (both enabled=true and enabled=false)
	var fm_unblock := MockFeatureManager.new([
		{"id": "campaign_time", "enabled": true, "activation_blocked_reason": ""},
	])
	mr_res["probe_unblock_ok"] = pre_builder.probe_feature_manager(fm_unblock)
	mr_res["probed_campaign_unblocked_status"] = reg.get_module_status("campaign_time")
	mr_res["probed_campaign_unblocked_enabled"] = reg.is_module_enabled("campaign_time")

	var fm_unblock_disabled := MockFeatureManager.new([
		{"id": "campaign_time", "enabled": false, "activation_blocked_reason": ""},
	])
	mr_res["probe_unblock_disabled_ok"] = pre_builder.probe_feature_manager(fm_unblock_disabled)
	mr_res["probed_campaign_unblocked_disabled_status"] = reg.get_module_status("campaign_time")
	mr_res["probed_campaign_unblocked_disabled_enabled"] = reg.is_module_enabled("campaign_time")

	# Regression: FuSdk.create_plugin_sdk resolves module aliases consistently with WorldBuilder.get_plugin_sdk
	var sdk_alias = sdk_script.new()
	var helper_reg = sdk_alias._get_helper_registry()
	helper_reg._aliases["alias_edit_mode"] = "feature_edit_mode"
	var direct_em = sdk.create_plugin_sdk("feature_edit_mode")
	var direct_el = sdk.create_plugin_sdk("feature_entity_library")
	var bound_em = sdk.create_plugin_sdk("feature_edit_mode", pre_builder)
	var alias_em = sdk_alias.create_plugin_sdk("alias_edit_mode")
	var alias_ex_res = sdk.create_plugin_sdk("feature_module_example")
	var alias_ex_bound = sdk.create_plugin_sdk("feature_module_example", pre_builder)
	mr_res["create_plugin_sdk_alias_ok"] = (
		direct_em != null
		and str(direct_em.MODULE_ID) == "feature_edit_mode"
		and direct_el != null
		and direct_el.get_writer() != null
		and bound_em == pre_builder.edit_mode()
		and alias_em != null
		and str(alias_em.MODULE_ID) == "feature_edit_mode"
		and alias_ex_res == null
		and alias_ex_bound == null
		and helper_reg.resolve_module_id("feature_module_example") == "module_example"
	)

	# Regression (Challenger 1 #1): case normalization in ModuleRegistry & FuSdk.create_plugin_sdk / get_plugin_sdk
	var upper_em_standalone = sdk.create_plugin_sdk("  FEATURE_EDIT_MODE  ")
	var upper_em_bound = sdk.create_plugin_sdk("  FEATURE_EDIT_MODE  ", pre_builder)
	var upper_alias_standalone = sdk_alias.create_plugin_sdk("  ALIAS_EDIT_MODE  ")
	var upper_el_standalone = sdk.create_plugin_sdk("FEATURE_ENTITY_LIBRARY")
	var wb_upper_el = sdk.create_world_builder(sess_mr, 150.0)
	var upper_el_bound = sdk.create_plugin_sdk("  Feature_Entity_Library  ", wb_upper_el)
	mr_res["case_norm_ok"] = (
		reg.resolve_module_id("  FEATURE_EDIT_MODE  ") == "feature_edit_mode"
		and reg.is_module_enabled("FEATURE_EDIT_MODE")
		and reg.resolve_module_id("FEATURE_MODULE_EXAMPLE") == "module_example"
		and upper_em_standalone != null
		and str(upper_em_standalone.MODULE_ID) == "feature_edit_mode"
		and upper_em_bound == pre_builder.edit_mode()
		and upper_alias_standalone != null
		and str(upper_alias_standalone.MODULE_ID) == "feature_edit_mode"
		and sdk.create_plugin_sdk("FEATURE_MODULE_EXAMPLE") == null
		and upper_el_standalone != null
		and upper_el_standalone.get_writer() != null
		and upper_el_bound != null
		and upper_el_bound.get_writer() != null
		and upper_el_bound == wb_upper_el.entity_library()
	)

	# Regression (Challenger 1 #2): reject non-plugin script "module_registry" with zero SCRIPT ERROR
	mr_res["reject_module_registry_ok"] = (
		sdk.create_plugin_sdk("module_registry") == null
		and sdk.create_plugin_sdk("MODULE_REGISTRY") == null
		and sdk.create_plugin_sdk("module_registry", pre_builder) == null
		and pre_builder.get_plugin_sdk("module_registry") == null
		and sdk.create_plugin_sdk("nonexistent_plugin") == null
	)

	# Regression (Challenger 1 #3): JSON null activation_blocked_reason / blocked_reason treated as ""
	var fm_null_reason := MockFeatureManager.new([
		{"id": "campaign_time", "enabled": false, "activation_blocked_reason": null},
		{"id": "simple_fog", "enabled": true, "activation_blocked_reason": null},
		{"id": "dnd_opportunity", "enabled": false, "blocked_reason": null},
	])
	mr_res["probe_null_reason_ok"] = pre_builder.probe_feature_manager(fm_null_reason)
	mr_res["null_reason_campaign_status"] = reg.get_module_status("campaign_time")
	mr_res["null_reason_campaign_reason"] = reg.get_blocked_reason("campaign_time")
	mr_res["null_reason_fog_status"] = reg.get_module_status("simple_fog")
	mr_res["null_reason_fog_reason"] = reg.get_blocked_reason("simple_fog")
	mr_res["null_reason_dnd_status"] = reg.get_module_status("dnd_opportunity")
	mr_res["null_reason_dnd_reason"] = reg.get_blocked_reason("dnd_opportunity")

	# Regression (Iter 4 Challenger 1 #1 & #3): JSON.parse_string null booleans & duplicate conflicting set_enabled_modules
	var json_pb_null: Variant = JSON.parse_string('{"rows": [{"id": "areas", "enabled": true, "playtest_blocked": null, "activation_blocked_reason": null}]}')
	var pb_null_ok: bool = pre_builder.probe_feature_manager(json_pb_null)
	var pb_null_areas_enabled: bool = reg.get_module_status("areas") == "enabled"

	var json_en_null: Variant = JSON.parse_string('{"rows": [{"id": "checklist", "enabled": null, "activation_blocked_reason": null}]}')
	var en_null_ok: bool = pre_builder.probe_feature_manager(json_en_null)
	var en_null_checklist_disabled: bool = reg.get_module_status("checklist") == "disabled"

	var json_healthy_null: Variant = JSON.parse_string('{"healthy": null, "campaign_blockers": null, "rows": [{"id": "simple_fog", "enabled": true}]}')
	var healthy_null_ok: bool = pre_builder.probe_feature_manager(json_healthy_null)
	var healthy_null_report: Dictionary = reg.get_last_probe_report()
	var healthy_null_fog_enabled: bool = pre_builder.is_module_enabled("simple_fog") and bool(healthy_null_report.get("healthy", false)) and (healthy_null_report.get("campaign_blockers", null) is Array)

	var json_set_en_null: Variant = JSON.parse_string('[{"id": "simple_fog", "enabled": null}]')
	reg.set_enabled_modules(json_set_en_null as Array)
	var set_en_null_disabled: bool = not reg.is_module_enabled("simple_fog")

	var json_dup_conflict: Variant = JSON.parse_string('[{"id": "simple_fog", "enabled": true}, {"id": "SIMPLE_FOG", "enabled": false}]')
	reg.set_enabled_modules(json_dup_conflict as Array)
	var dup_conflict_disabled: bool = not reg.is_module_enabled("simple_fog")

	var json_dup_enable: Variant = JSON.parse_string('[{"id": "simple_fog", "enabled": false}, {"id": "SIMPLE_FOG", "enabled": true}]')
	reg.set_enabled_modules(json_dup_enable as Array)
	var dup_enable_enabled: bool = reg.is_module_enabled("simple_fog")

	mr_res["json_null_booleans_and_dup_ok"] = (
		pb_null_ok
		and pb_null_areas_enabled
		and en_null_ok
		and en_null_checklist_disabled
		and healthy_null_ok
		and healthy_null_fog_enabled
		and set_en_null_disabled
		and dup_conflict_disabled
		and dup_enable_enabled
	)

	# Regression: empty module_choices() clears optional modules and returns true
	var fm_empty := MockFeatureManagerChoices.new([])
	mr_res["probe_empty_choices_ok"] = pre_builder.probe_feature_manager(fm_empty)
	mr_res["probed_checklist_cleared_on_empty"] = not pre_builder.is_module_enabled("checklist")
	mr_res["probed_core_stays_on_empty"] = pre_builder.is_module_enabled("feature_edit_mode")

	# Regression: uncatalogued candidates NEVER marked enabled by set_enabled_modules / set_module_enabled
	reg.set_enabled_modules(["entity_notes", "music_board", "module_example"])
	var cand_dict_reg = sdk.create_module_registry(sess_mr.get_logger(), sess_mr)
	cand_dict_reg.set_enabled_modules([
		{"id": "entity_notes", "enabled": true},
		{"id": "music_board", "enabled": true},
		{"id": "feature_module_example", "enabled": true},
	])
	var set_cand_ret: bool = reg.set_module_enabled("entity_notes", true)
	mr_res["cand_stays_uncatalogued"] = (
		reg.get_module_status("entity_notes") == "uncatalogued_candidate"
		and not reg.is_module_enabled("entity_notes")
		and reg.get_module_status("music_board") == "uncatalogued_candidate"
		and not reg.is_module_enabled("music_board")
		and reg.get_module_status("module_example") == "uncatalogued_candidate"
		and not reg.is_module_enabled("module_example")
		and reg.get_module_status("feature_module_example") == "uncatalogued_candidate"
		and not reg.is_module_enabled("feature_module_example")
		and cand_dict_reg.get_module_status("entity_notes") == "uncatalogued_candidate"
		and cand_dict_reg.get_module_status("feature_module_example") == "uncatalogued_candidate"
		and not set_cand_ret
	)

	# Regression (Iter 5 Challenger 1 #1, #4 & Reviewer 1 BOM):
	# conflicting mixed-case probe_feature_manager rows + non-string blocked_reason + BOM _to_bool
	var dup_probe: Variant = JSON.parse_string('{"rows": [{"id": "simple_fog", "enabled": true}, {"id": "SIMPLE_FOG", "enabled": false}, {"id": "feature_edit_mode", "enabled": false}, {"id": "FEATURE_EDIT_MODE", "enabled": true}]}')
	var dup_probe_ok: bool = pre_builder.probe_feature_manager(dup_probe)
	var dup_probe_fog_off: bool = not pre_builder.is_module_enabled("simple_fog")
	var dup_probe_core_on: bool = pre_builder.is_module_enabled("feature_edit_mode")

	var weird_reason_probe: Variant = JSON.parse_string('{"rows": [{"id": "simple_fog", "enabled": true, "activation_blocked_reason": false}, {"id": "areas", "enabled": true, "activation_blocked_reason": {}}]}')
	var weird_reason_ok: bool = pre_builder.probe_feature_manager(weird_reason_probe)
	var bom_bool_ok: bool = value_utils.coerce_bool("\ufefftrue", false, true) and not value_utils.coerce_bool("  \ufefffalse", true, true)
	mr_res["probe_dup_and_weird_reason_ok"] = (
		dup_probe_ok
		and dup_probe_fog_off
		and dup_probe_core_on
		and weird_reason_ok
		and reg.get_module_status("simple_fog") == "enabled"
		and reg.get_blocked_reason("simple_fog") == ""
		and reg.get_module_status("areas") == "enabled"
		and reg.get_blocked_reason("areas") == ""
		and bom_bool_ok
	)
	results["module_registry"] = mr_res

	# 3. parked / manual & 5 Core Plugin SDKs
	var host_core := MockHost.new()
	var sess_core = sdk.create_session(host_core, {})
	sess_core.get_logger().set_emit_to_engine(false)
	var b = sdk.create_world_builder(sess_core, 150.0)
	var adapter = b.get_adapter()

	# parked / manual checks
	var pm_res := {}
	var ent_pm_id: String = b.add_object_sprite("pm_obj", "PMObj", Vector2(100, 100), Vector2(64, 64), "")
	var ok_auto_park: bool = b.attach_component(ent_pm_id, "res://modules/backpack/comp_backpack.gd", {"slots": []}, true, false)
	var ok_manual_park: bool = b.attach_parked_component(ent_pm_id, "res://modules/follow/comp_follow.gd", {"target": ""}, true)
	var bad_manual_only: bool = b.attach_component(ent_pm_id, "res://modules/portal/comp_portal.gd", {"pair_key": ""}, false, true)
	var ent_pm: Dictionary = b.get_entity(ent_pm_id)
	var pm_comps: Array = ent_pm.get("components", [])
	pm_res["ok_auto_park"] = ok_auto_park
	pm_res["ok_manual_park"] = ok_manual_park
	pm_res["bad_manual_only_rejected"] = not bad_manual_only
	pm_res["comp_count"] = pm_comps.size()
	if pm_comps.size() >= 4:
		pm_res["c2_parked"] = bool(pm_comps[2].get("parked", false))
		pm_res["c2_no_manual"] = not pm_comps[2].has("manual")
		pm_res["c2_size"] = pm_comps[2].size()
		pm_res["c3_parked"] = bool(pm_comps[3].get("parked", false))
		pm_res["c3_manual"] = bool(pm_comps[3].get("manual", false))
		pm_res["c3_size"] = pm_comps[3].size()
	var adapter_err: Dictionary = adapter.append_entity_component(ent_pm, "res://modules/portal/comp_portal.gd", {}, false, true)
	pm_res["adapter_reason"] = str(adapter_err.get("reason", ""))
	# Regression (Challenger 2 #2): reject INF/NAN in component state
	var bad_park_inf: bool = b.attach_parked_component(ent_pm_id, "res://modules/custom/comp_bad_inf.gd", {"bad": INF}, true)
	var bad_park_nan_vec: bool = b.attach_parked_component(ent_pm_id, "res://modules/custom/comp_bad_vec.gd", {"nested": [Vector2(NAN, 0)]}, false)
	var bad_live_col: bool = b.attach_component(ent_pm_id, "res://modules/custom/comp_bad_col.gd", {"c": Color(INF, 0, 0)}, false, false)
	var bad_pf_nan: bool = b.attach_parked_component(ent_pm_id, "res://modules/custom/comp_bad_pf.gd", {"pf": PackedFloat32Array([NAN])}, false)
	var adapter_inf_err: Dictionary = adapter.append_entity_component(ent_pm, "res://modules/custom/comp_bad_inf.gd", {"bad": INF}, true, false)
	pm_res["inf_nan_state_rejected"] = (
		not bad_park_inf
		and not bad_park_nan_vec
		and not bad_live_col
		and not bad_pf_nan
		and not bool(adapter_inf_err.get("ok", true))
		and str(adapter_inf_err.get("reason", "")) == "invalid_component_state"
	)
	var roundtrip = bytes_to_var(var_to_bytes(b.get_world()))
	pm_res["roundtrip_ok"] = roundtrip is Dictionary and str((roundtrip as Dictionary).get("format", "")) == "fus.practice.world"

	# Regression (Iter 5 Challenger 1 #2, #3, #5): init_empty_world ok=null, build_prepare_ok entity_state=null, cyclic set_module_state
	var null_ok_host := MockNullOkHost.new()
	var init_null_res: Dictionary = adapter.init_empty_world(null_ok_host)
	var setup_null_wb = sdk.create_world_builder(sdk.create_session(null_ok_host, {}), 150.0)
	var prep_null_es: Dictionary = adapter.build_prepare_ok(JSON.parse_string('{"entity_state": null}') as Dictionary, 2)
	var cyc_mod := {"k": 1}
	cyc_mod["self"] = cyc_mod
	cyc_mod["b"] = cyc_mod
	var cyc_mod_ok: bool = b.set_module_state("demo_cyc", 1, cyc_mod)
	var cyc_fit_ok: bool = b.can_fit_module_state("demo_cyc", 1, cyc_mod)
	pm_res["adapter_null_and_cyclic_ok"] = (
		not bool(init_null_res.get("ok", true))
		and not setup_null_wb.is_ready()
		and bool(prep_null_es.get("ok", false))
		and int(prep_null_es.get("counts", {}).get("entities", -1)) == 0
		and not cyc_mod_ok
		and not cyc_fit_ok
	)

	# Iter 7 Regression 2: v1.gd + host_v1_adapter scaled INF & entity_state: null
	var host_sc := MockHost.new()
	var sess_sc = sdk.create_session(host_sc, {})
	sess_sc.get_logger().set_emit_to_engine(false)
	var b_sc = sdk.create_world_builder(sess_sc, 0.0001)
	var inf_tok_id: String = b_sc.add_token("inf_t", "InfTok", Vector2(1e34, 0), Vector2(64, 64), "")
	var inf_obj_id: String = b_sc.add_object_sprite("inf_o", "InfObj", Vector2(1e34, 0), Vector2(64, 64), "")
	var inf_map_id: String = b_sc.add_map_tile("inf_m", "InfMap", Vector2(1e34, 0), Vector2(64, 64), "")
	var inf_box_id: String = b_sc.add_scene_box("inf_b", "InfBox", Vector2(1e34, 0), "")
	var empty_after_inf: bool = (
		b_sc.get_world()["entity_state"]["entities"].is_empty()
		and b_sc.get_world()["members"].is_empty()
	)
	var ok_tok_id: String = b_sc.add_token("ok_t", "OkTok", Vector2(10, 10), Vector2(64, 64), "")
	var ok_ent: Dictionary = b_sc.get_entity(ok_tok_id)
	var ok_pos: Vector2 = ok_ent.get("xform", {}).get("pos", Vector2(INF, INF))
	var ok_scale: Vector2 = ok_ent.get("xform", {}).get("scale", Vector2(INF, INF))
	var null_world_ent: Dictionary = adapter.append_entity(
		JSON.parse_string('{"entity_state": null, "members": null}') as Dictionary,
		"00000000000000000000000000000001",
		"20000000000000000000000000000001",
		"nw_1",
		"NullWorldEnt",
		Vector2(10, 10),
		Vector2(64, 64),
		0.0,
		Vector2.ONE,
		1.0,
		adapter.make_sprite_visual(""),
		false,
		false
	)
	pm_res["scaled_inf_and_null_world_ok"] = (
		inf_tok_id.is_empty()
		and inf_obj_id.is_empty()
		and inf_map_id.is_empty()
		and inf_box_id.is_empty()
		and empty_after_inf
		and not ok_tok_id.is_empty()
		and is_finite(ok_pos.x) and is_finite(ok_pos.y)
		and is_finite(ok_scale.x) and is_finite(ok_scale.y)
		and not null_world_ent.is_empty()
	)

	# Iter 7 Regression 3: JSON null UIDs in extract_default_world_targets & ensure_scene_repository_state
	var null_act_world: Dictionary = JSON.parse_string(
		'{"catalog": {"active_floor_uid": null, "floors": [{"id": 0, "floor_uid": "00000000000000000000000000000001", "name": "1F"}], "layers": {"schema": "fus.floor_layers.v2", "floors": [{"floor_uid": "00000000000000000000000000000001", "default_layer_uid": "20000000000000000000000000000001", "layers": [{"layer_uid": "10000000000000000000000000000001", "kind": "map"}, {"layer_uid": "20000000000000000000000000000001", "kind": "entity"}, {"layer_uid": "30000000000000000000000000000001", "kind": "obstacle"}]}]}}}'
	) as Dictionary
	var ext_null_act: Dictionary = adapter.extract_default_world_targets(null_act_world)
	var wb_null_act = sdk.create_world_builder(sdk.create_session(MockJsonNullFloorHost.new(false), {}), 150.0)
	var wb_null_f0 = sdk.create_world_builder(sdk.create_session(MockJsonNullFloorHost.new(true), {}), 150.0)
	var null_map_world: Dictionary = JSON.parse_string(
		'{"catalog": {"active_floor_uid": "00000000000000000000000000000001", "floors": [{"id": 0, "floor_uid": "00000000000000000000000000000001", "name": "1F"}], "layers": {"schema": "fus.floor_layers.v2", "floors": [{"floor_uid": "00000000000000000000000000000001", "layers": [{"kind": "map", "layer_uid": null}, {"kind": "entity", "layer_uid": "20000000000000000000000000000001"}, {"kind": "obstacle", "layer_uid": "30000000000000000000000000000001"}]}]}}}'
	) as Dictionary
	var ext_null_map: Dictionary = adapter.extract_default_world_targets(null_map_world)
	var ensure_null_w: Dictionary = JSON.parse_string(
		'{"catalog": {"active_floor_uid": null, "floors": [{"id": 0, "floor_uid": "00000000000000000000000000000001", "name": "1F"}]}}'
	) as Dictionary
	var ensure_null_res: Dictionary = adapter.ensure_scene_repository_state(ensure_null_w)
	pm_res["json_null_uid_guards_ok"] = (
		bool(ext_null_act.get("ok", false))
		and str(ext_null_act.get("floor_uid", "")) == "00000000000000000000000000000001"
		and wb_null_act.is_ready()
		and wb_null_act.get_active_floor_uid() == "00000000000000000000000000000001"
		and not wb_null_f0.is_ready()
		and not bool(ext_null_map.get("ok", true))
		and str(ext_null_map.get("reason", "")) == "missing_required_layer:map"
		and bool(ensure_null_res.get("ok", false))
		and str(ensure_null_w["catalog"].get("active_floor_uid", "")) == "00000000000000000000000000000001"
	)

	# Iter 7 Regression 4: cyclic world in can_fit_module_state, depth 29/30/40 parity, diamond DAG, coerce_* parity
	var cyc_world: Dictionary = b.get_world().duplicate(true)
	var cyc_bad := {"x": 1}
	cyc_bad["self"] = cyc_bad
	cyc_world["modules"]["entries"]["existing_bad"] = {"version": 1, "state": cyc_bad}
	var can_fit_cyc_world: bool = adapter.can_fit_module_state(cyc_world, "new_mod", 1, {"a": 1})

	var d29: Dictionary = _make_deep_dict(29)
	var d30: Dictionary = _make_deep_dict(30)
	var d40: Dictionary = _make_deep_dict(40)
	var fit_29: bool = adapter.can_fit_module_state(b.get_world(), "depth29", 1, d29)
	var set_29: Dictionary = adapter.set_module_state(b.get_world(), "depth29", 1, d29)
	var fit_30: bool = adapter.can_fit_module_state(b.get_world(), "depth30", 1, d30)
	var set_30: Dictionary = adapter.set_module_state(b.get_world(), "depth30", 1, d30)
	var fit_40: bool = adapter.can_fit_module_state(b.get_world(), "depth40", 1, d40)
	var set_40: Dictionary = adapter.set_module_state(b.get_world(), "depth40", 1, d40)

	var _warm_oa = b.obstacle_authoring()
	var dag24: Dictionary = _make_dag(24)
	var dag33: Dictionary = _make_dag(33)
	var t_dag0: int = Time.get_ticks_msec()
	var dag_est: int = adapter.bounded_variant_size_estimate(dag24)
	var dag_valid: bool = adapter.is_valid_state_data(dag24)
	var dag33_valid: bool = adapter.is_valid_state_data(dag33)
	var _dag_san: Variant = adapter.sanitize_module_value(dag24)
	var _dag_clone: Dictionary = adapter._safe_clone_dict(dag24)
	var dag_probe_ok: bool = reg.probe_feature_manager(dag24)
	var _dag_log: Dictionary = bus.info("dag_src", "dag_msg", dag24)
	var _dag_tmpl: Dictionary = b.entity_library().build_template_data("dag_u", "DagU", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", dag24)
	var _dag_obs: Dictionary = _warm_oa.make_obstacle_state("object", "manual", 64.0, dag24, dag24)
	var dag_elapsed: int = Time.get_ticks_msec() - t_dag0

	var coerce_parity_ok: bool = (
		adapter.coerce_bool("  \ufefftrue", false) == true
		and adapter.coerce_bool(&"\ufefffalse", true) == false
		and adapter.coerce_int("  \ufeff42", -1) == 42
		and adapter.coerce_int(&"\ufeff-7", 0) == -7
		and adapter.coerce_float("  \ufeff3.5", -1.0) == 3.5
		and adapter.coerce_float(&"\ufeff2.25", -1.0) == 2.25
	)
	pm_res["module_depth_dag_and_coerce_ok"] = (
		not can_fit_cyc_world
		and fit_29
		and bool(set_29.get("ok", false))
		and not fit_30
		and str(set_30.get("reason", "")) == "invalid_module_state"
		and not fit_40
		and str(set_40.get("reason", "")) == "invalid_module_state"
		and dag_est == -1
		and dag_valid
		and not dag33_valid
		and not dag_probe_ok
		and dag_elapsed < 500
		and coerce_parity_ok
	)
	results["parked_manual"] = pm_res

	# Core Plugin 1: feature_edit_mode
	var em = b.edit_mode()
	var em_res := {}
	em_res["module_id"] = em.MODULE_ID
	em_res["enabled"] = em.is_enabled()
	var obj_id: String = b.add_object_sprite("em_obj", "HeroObj", Vector2(200, 200), Vector2(64, 64), "")
	var attach_unit_res: Dictionary = em.attach_unit_marker(obj_id)
	em_res["attach_unit_ok"] = bool(attach_unit_res.get("ok", false))
	em_res["is_unit_after"] = em.is_unit(obj_id)
	em_res["flags_ok"] = em.set_entity_flags(obj_id, true, true)
	em_res["perm_ok"] = em.set_entity_permissions(obj_id, em.make_permission_state("p1", ["p1"], false, true))
	var json_perm_null: Variant = JSON.parse_string('{"owners_csv": null, "gm_can_operate": null, "all_players_can_operate": null, "owner_peers": [null, "abc", 2], "owner_player_ids": [null, "p1", 42]}')
	em_res["perm_json_null_ok"] = em.set_entity_permissions(obj_id, json_perm_null as Dictionary)
	var perm_norm_state: Dictionary = (b.get_entity(obj_id)["components"][1] as Dictionary).get("state", {})
	var make_perm_null: Dictionary = em.make_permission_state("", [null, "u1", 99])
	var adapter_perm_null: Dictionary = adapter.make_permission_state("", [null, "u2", 77])
	em_res["perm_json_null_fields_ok"] = (
		str(perm_norm_state.get("owners_csv", "BAD")) == ""
		and bool(perm_norm_state.get("gm_can_operate", false))
		and not bool(perm_norm_state.get("all_players_can_operate", true))
		and (perm_norm_state.get("owner_peers", PackedInt32Array()) as PackedInt32Array) == PackedInt32Array([2])
		and (perm_norm_state.get("owner_player_ids", PackedStringArray()) as PackedStringArray) == PackedStringArray(["p1"])
		and (make_perm_null.get("owner_player_ids", PackedStringArray()) as PackedStringArray) == PackedStringArray(["u1"])
		and (adapter_perm_null.get("owner_player_ids", PackedStringArray()) as PackedStringArray) == PackedStringArray(["u2"])
	)
	var json_owners_container: Variant = JSON.parse_string('{"owners_csv": {"bad": 1}}')
	em.set_entity_permissions(obj_id, json_owners_container as Dictionary)
	em_res["perm_owners_container_empty"] = str((b.get_entity(obj_id)["components"][1]["state"] as Dictionary).get("owners_csv", "BAD")) == ""
	em_res["perm_restore_ok"] = em.set_entity_permissions(obj_id, em.make_permission_state("p1", ["p1"], false, true))

	# Regression (Iter 5 Challenger 2 #1): JSON null parked/manual across is_unit, set_entity_permissions, validate_unit_entity
	var null_pm_ent: Dictionary = JSON.parse_string('{"entity_type": "unit", "entity_size": null, "footprint_radius": 32.0, "selectable_in_select_mode": true, "components": [{"script": "res://scenes/entities/components/comp_visual.gd", "parked": null, "manual": null}, {"script": "res://scenes/entities/components/comp_permission.gd", "parked": null, "manual": null, "state": {"owners_csv": "", "gm_can_operate": true, "all_players_can_operate": false, "owner_peers": [], "owner_player_ids": []}}, {"script": "res://scenes/entities/components/comp_unit.gd", "parked": null, "manual": null, "state": {"schema_version": 1}}]}')
	null_pm_ent["entity_size"] = Vector2(64, 64)
	null_pm_ent["components"][2]["state"]["schema_version"] = 1
	var null_pm_val: Dictionary = em.validate_unit_entity(null_pm_ent)
	var null_pm_id: String = b.add_object_sprite("em_null_pm", "NullPM", Vector2(260, 260), Vector2(64, 64), "")
	em.attach_unit_marker(null_pm_id)
	var null_pm_rec: Dictionary = b.get_entity(null_pm_id)
	null_pm_rec["selectable_in_select_mode"] = false
	null_pm_rec["components"][1]["parked"] = JSON.parse_string("null")
	null_pm_rec["components"][2]["parked"] = JSON.parse_string("null")
	em_res["parked_manual_json_null_ok"] = (
		bool(null_pm_val.get("ok", false))
		and em.is_unit(null_pm_id)
		and em.set_entity_permissions(null_pm_id, em.make_permission_state("", ["p1"]))
	)
	em_res["fp_bad_low"] = not em.set_footprint_radius(obj_id, 0.1)
	em_res["fp_bad_high"] = not em.set_footprint_radius(obj_id, 5000.0)
	em_res["fp_ok"] = em.set_footprint_radius(obj_id, 48.0)
	em_res["val_unit_ok"] = bool(em.validate_unit_entity(b.get_entity(obj_id)).get("ok", false))
	var map_id: String = b.add_map_tile("em_map", "Map", Vector2(0, 0), Vector2(300, 300), "")
	b.get_entity(map_id)["entity_type"] = "map"
	var map_unit_res: Dictionary = em.attach_unit_marker(map_id)
	em_res["map_rejected"] = not bool(map_unit_res.get("ok", true)) and str(map_unit_res.get("reason", "")) == "unit_disallowed_on_map"
	em_res["map_val_rejected"] = not bool(em.validate_unit_entity(b.get_entity(map_id)).get("ok", true))
	em_res["map_select_rejected"] = not em.set_selectable_in_select_mode(map_id, true) and em.set_selectable_in_select_mode(map_id, false)

	# Regression: int footprint_radius, non-unit / parked unit eligibility, missing permission key
	var ent_int_fp: Dictionary = b.get_entity(obj_id).duplicate(true)
	ent_int_fp["footprint_radius"] = 32
	em_res["int_fp_rejected"] = not bool(em.validate_unit_entity(ent_int_fp).get("ok", true))
	var plain_obj_id: String = b.add_object_sprite("em_plain", "Crate", Vector2(220, 220), Vector2(64, 64), "")
	em_res["non_unit_rejected"] = not bool(em.validate_unit_entity(b.get_entity(plain_obj_id)).get("ok", true))
	em.attach_unit_marker(plain_obj_id, true, false)
	em_res["parked_unit_rejected"] = not bool(em.validate_unit_entity(b.get_entity(plain_obj_id)).get("ok", true))
	var ent_bad_perm: Dictionary = b.get_entity(obj_id).duplicate(true)
	(ent_bad_perm["components"][1]["state"] as Dictionary).erase("owner_player_ids")
	em_res["missing_perm_key_rejected"] = not bool(em.validate_unit_entity(ent_bad_perm).get("ok", true))

	# Regression (Challenger 2 #1 & #4): strict int/bool checks in validate_unit_entity & WorldBuilder.attach_unit_marker on map
	var bad_sv_all_rejected: bool = true
	for bad_sv: Variant in [true, 1.5, 1.0, "1"]:
		var e_sv: Dictionary = b.get_entity(obj_id).duplicate(true)
		for comp_v: Variant in e_sv["components"]:
			if comp_v is Dictionary and str((comp_v as Dictionary).get("script", "")) == em.COMP_UNIT_SCRIPT:
				(comp_v as Dictionary)["state"]["schema_version"] = bad_sv
		if bool(em.validate_unit_entity(e_sv).get("ok", true)):
			bad_sv_all_rejected = false
	em_res["bad_schema_version_types_rejected"] = bad_sv_all_rejected
	var bad_sel_all_rejected: bool = true
	for bad_sel: Variant in [1, "true", null]:
		var e_sel: Dictionary = b.get_entity(obj_id).duplicate(true)
		if bad_sel == null:
			e_sel.erase("selectable_in_select_mode")
		else:
			e_sel["selectable_in_select_mode"] = bad_sel
		if bool(em.validate_unit_entity(e_sel).get("ok", true)):
			bad_sel_all_rejected = false
	em_res["bad_selectable_types_rejected"] = bad_sel_all_rejected
	em_res["wb_map_unit_rejected"] = not b.attach_unit_marker(map_id)
	var ok_unit_obj: String = b.add_object_sprite("em_wb_unit", "WbUnit", Vector2(240, 240), Vector2(64, 64), "")
	em_res["wb_obj_unit_ok"] = b.attach_unit_marker(ok_unit_obj)

	var box_id: String = b.add_scene_box("em_box", "Box", Vector2(300, 300), "00000000000000000000000000000001")
	var box_unit_res: Dictionary = em.attach_unit_marker(box_id)
	em_res["scene_box_rejected"] = not bool(box_unit_res.get("ok", true)) and str(box_unit_res.get("reason", "")).begins_with("component_conflict_with_scene_box")

	# Iter 7 Regression 5: feature_edit_mode BOM stripping parity
	var bom_perm_obj: String = b.add_object_sprite("em_bom_perm", "BomPerm", Vector2(280, 280), Vector2(64, 64), "")
	var bom_perm_set_ok: bool = em.set_entity_permissions(bom_perm_obj, {
		"owner_player_ids": [null, "p1", 42, "", "\ufeffp2", "  \ufeffp3"],
		"owners_csv": "  \ufeffp1,p2",
	})
	var bom_perm_stored: Dictionary = (b.get_entity(bom_perm_obj)["components"][1] as Dictionary).get("state", {})
	var bound_mk_perm: Dictionary = em.make_permission_state("  \ufeffp1,p2", [null, "p1", "\ufeffp2", "  \ufeffp3"])
	var standalone_em = sdk.create_plugin_sdk("feature_edit_mode")
	var stand_mk_perm: Dictionary = standalone_em.make_permission_state("  \ufeffp1,p2", [null, "p1", "\ufeffp2", "  \ufeffp3"])
	em_res["bom_perm_parity_ok"] = (
		bom_perm_set_ok
		and str(bom_perm_stored.get("owners_csv", "")) == "p1,p2"
		and (bom_perm_stored.get("owner_player_ids", PackedStringArray()) as PackedStringArray) == PackedStringArray(["p1", "p2", "p3"])
		and str(bound_mk_perm.get("owners_csv", "")) == "p1,p2"
		and (bound_mk_perm.get("owner_player_ids", PackedStringArray()) as PackedStringArray) == PackedStringArray(["p1", "p2", "p3"])
		and str(stand_mk_perm.get("owners_csv", "")) == "p1,p2"
		and (stand_mk_perm.get("owner_player_ids", PackedStringArray()) as PackedStringArray) == PackedStringArray(["p1", "p2", "p3"])
	)
	results["edit_mode"] = em_res

	# Core Plugin 2: feature_floor_system
	var fs = b.floor_system()
	var fs_res := {}
	var f0_uid: String = fs.get_active_floor_uid()
	var f1_uid: String = fs.add_floor("2F Basement", Color(0.5, 0.3, 0.2), true)
	fs_res["f1_created"] = not f1_uid.is_empty() and fs.get_active_floor_uid() == f1_uid
	fs_res["rename_ok"] = fs.rename_floor(f1_uid, "2F")
	fs_res["rename_rejects_empty"] = not fs.rename_floor(f1_uid, "") and not fs.rename_floor(f1_uid, "   ")
	fs_res["rename_rejects_ctrl"] = not fs.rename_floor(f1_uid, "Bad\nFloor") and not fs.rename_floor(f1_uid, "Bad\u0007Floor")
	fs_res["rename_rejects_padded"] = not fs.rename_floor(f1_uid, "  2F  ")
	fs_res["rename_rejects_over_96"] = not fs.rename_floor(f1_uid, "A".repeat(97))
	fs_res["name_unchanged_after_reject"] = str(fs.get_floor(f1_uid).get("name", "")) == "2F"
	fs_res["get_floor_unknown_empty"] = fs.get_floor("f".repeat(32)).is_empty()
	fs_res["color_ok"] = fs.set_floor_color(f1_uid, Color(0.1, 0.2, 0.3))
	fs_res["color_nan_rejected"] = not fs.set_floor_color(f1_uid, Color(NAN, 0.2, 0.3))
	fs_res["reorder_ok"] = fs.reorder_floor(f1_uid, 0)
	var floors_after: Array = fs.get_floors()
	fs_res["reordered_first_uid"] = str(floors_after[0].get("floor_uid", ""))
	fs_res["reordered_ids_ok"] = int(floors_after[0].get("id", -1)) == 0 and int(floors_after[1].get("id", -1)) == 1
	fs_res["no_elevation_key"] = not floors_after[0].has("elevation")
	fs_res["visits_ok"] = fs.set_player_floor_visits("player_1", [f0_uid, f1_uid])
	fs_res["visits_count"] = fs.get_player_floor_visits("player_1").size()
	var pid_128: String = "p".repeat(128)
	var pid_129: String = "p".repeat(129)
	fs_res["visits_128_ok"] = fs.set_player_floor_visits(pid_128, [f0_uid]) and fs.get_player_floor_visits(pid_128) == [f0_uid]
	fs_res["visits_129_rejected"] = not fs.set_player_floor_visits(pid_129, [f0_uid]) and fs.get_player_floor_visits(pid_129).is_empty()
	fs_res["visits_ctrl_rejected"] = not fs.set_player_floor_visits("bad\npid", [f0_uid])
	fs_res["visits_bad_uid_rejected"] = not fs.set_player_floor_visits("player_1", ["not_a_uid"]) and not fs.set_player_floor_visits("player_1", [f0_uid, f0_uid])
	fs_res["val_ok"] = bool(fs.validate_floors().get("ok", false))
	var bad_world: Dictionary = b.get_world().duplicate(true)
	bad_world["catalog"]["floors"][0]["elevation"] = 10.0
	fs_res["extra_elevation_rejected"] = not bool(fs.validate_floors(bad_world).get("ok", true))
	# Regression (Challenger 2 #1 & #3): strict floor_identity_version is int & BOM handling in rename_floor
	var bad_fiv_all_rejected: bool = true
	for bad_fiv: Variant in [true, 1.5, 1.0, "1"]:
		var w_fiv: Dictionary = b.get_world().duplicate(true)
		w_fiv["catalog"]["floor_identity_version"] = bad_fiv
		if bool(fs.validate_floors(w_fiv).get("ok", true)):
			bad_fiv_all_rejected = false
	fs_res["bad_floor_id_ver_types_rejected"] = bad_fiv_all_rejected
	fs_res["rename_bom_ok"] = (
		fs.rename_floor(f1_uid, "\ufeffBomFloor")
		and str(fs.get_floor(f1_uid).get("name", "")) == "BomFloor"
		and not fs.rename_floor(f1_uid, "\ufeff   ")
		and not fs.rename_floor(f1_uid, "\ufeff")
		and not fs.rename_floor(f1_uid, "  \ufeffSpBom")
		and str(fs.get_floor(f1_uid).get("name", "")) == "BomFloor"
		and fs.rename_floor(f1_uid, "2F")
	)

	# Iter 7 Regression 6a: feature_floor_system <null> UID guard
	var saved_f0_uid: Variant = b.get_world()["catalog"]["floors"][0]["floor_uid"]
	b.get_world()["catalog"]["floors"][0]["floor_uid"] = JSON.parse_string("null")
	fs_res["null_uid_rejected"] = (
		fs.get_floor("<null>").is_empty()
		and not fs.set_floor_color("<null>", Color.RED)
		and not fs.reorder_floor("<null>", 0)
	)
	b.get_world()["catalog"]["floors"][0]["floor_uid"] = saved_f0_uid
	results["floor_system"] = fs_res

	# Core Plugin 3: feature_layer_stack
	var ls = b.layer_stack()
	var ls_res := {}
	var bad_players_layer: String = ls.add_layer("BadPlayers", "entity", "players", f0_uid, [])
	var good_players_layer: String = ls.add_layer("VIP", "area", "players", f0_uid, ["p2", "p1"])
	ls_res["bad_players_rejected"] = bad_players_layer.is_empty()
	ls_res["good_players_ok"] = not good_players_layer.is_empty()
	var vip_layer: Dictionary = ls.get_layer(good_players_layer)
	ls_res["viewers_sorted"] = vip_layer.get("viewers", []) == ["p1", "p2"]
	ls_res["vis_ok"] = ls.set_layer_visibility(good_players_layer, false) and not bool(ls.get_layer(good_players_layer).get("visible", true))
	ls_res["lock_ok"] = ls.set_layer_locked(good_players_layer, true) and bool(ls.get_layer(good_players_layer).get("locked", false))
	ls_res["rename_ok"] = ls.rename_layer(good_players_layer, "VIP Area")
	ls_res["rename_rejects_invalid"] = (
		not ls.rename_layer(good_players_layer, "")
		and not ls.rename_layer(good_players_layer, "   ")
		and not ls.rename_layer(good_players_layer, "Bad\nLayer")
		and not ls.rename_layer(good_players_layer, "  VIP Area  ")
		and not ls.rename_layer(good_players_layer, "L".repeat(97))
		and str(ls.get_layer(good_players_layer).get("name", "")) == "VIP Area"
	)
	var v150: String = "v".repeat(150)
	var v160: String = "v".repeat(160)
	var v161: String = "v".repeat(161)
	var area150_uid: String = ls.add_layer("Area150", "area", "players", f0_uid, [v150])
	var area150_viewers: Array = ls.get_layer(area150_uid).get("viewers", [])
	ls_res["add_layer_150_ok"] = (
		not area150_uid.is_empty()
		and area150_viewers.size() == 1
		and str(area150_viewers[0]).length() == 150
		and area150_viewers == [v150]
	)
	var area160_uid: String = ls.add_layer("Area160", "area", "players", f0_uid, [v160])
	var area160_viewers: Array = ls.get_layer(area160_uid).get("viewers", [])
	ls_res["add_layer_160_ok"] = (
		not area160_uid.is_empty()
		and area160_viewers.size() == 1
		and str(area160_viewers[0]).length() == 160
		and area160_viewers == [v160]
	)
	var direct150_uid: String = b.add_layer("Direct150", "area", "players", f0_uid, [v150])
	ls_res["direct_add_layer_150_ok"] = (
		not direct150_uid.is_empty()
		and ls.get_layer(direct150_uid).get("viewers", []) == [v150]
	)
	ls_res["add_layer_161_rejected"] = (
		ls.add_layer("Bad161", "area", "players", f0_uid, [v161]).is_empty()
		and ls.add_layer("BadMixed161", "area", "players", f0_uid, ["p1", v161]).is_empty()
	)
	ls_res["add_layer_ctrl_rejected"] = ls.add_layer("BadCtrl", "area", "players", f0_uid, ["p1", "p2\np3"]).is_empty()
	ls_res["add_layer_empty_rejected"] = ls.add_layer("BadEmpty", "area", "players", f0_uid, ["   "]).is_empty()
	ls_res["add_layer_non_str_rejected"] = ls.add_layer("BadNonStr", "area", "players", f0_uid, [123]).is_empty()
	ls_res["access_160_ok"] = ls.set_layer_access(good_players_layer, "players", [v160]) and ls.get_layer(good_players_layer).get("viewers", []) == [v160]
	ls_res["access_161_rejected"] = not ls.set_layer_access(good_players_layer, "players", [v161]) and not ls.set_layer_access(good_players_layer, "players", ["p1", v161])
	ls_res["access_ctrl_rejected"] = not ls.set_layer_access(good_players_layer, "players", ["p1", "p2\np3"])
	ls_res["access_transitions_ok"] = (
		ls.set_layer_access(good_players_layer, "all", [])
		and str(ls.get_layer(good_players_layer).get("access", "")) == "all"
		and ls.set_layer_access(good_players_layer, "host", [])
		and str(ls.get_layer(good_players_layer).get("access", "")) == "host"
		and ls.set_layer_access(good_players_layer, "players", ["p2", "p1"])
		and ls.get_layer(good_players_layer).get("viewers", []) == ["p1", "p2"]
	)
	var def_ent_uid: String = ls.get_layer_uid("entity", f0_uid)
	ls_res["default_access_protected"] = not ls.set_layer_access(def_ent_uid, "host", [])
	ls_res["area_cannot_be_default"] = not ls.set_default_layer(f0_uid, good_players_layer)
	ls_res["editor_view_ok"] = ls.set_editor_view(f0_uid, good_players_layer, true)
	ls_res["val_ok"] = bool(ls.validate_layer_catalog().get("ok", false))
	var bad_ctrl_world: Dictionary = b.get_world().duplicate(true)
	for fl_entry: Variant in bad_ctrl_world["catalog"]["layers"]["floors"]:
		if fl_entry is Dictionary and str((fl_entry as Dictionary).get("floor_uid", "")) == f0_uid:
			for lr_entry: Variant in (fl_entry as Dictionary).get("layers", []):
				if lr_entry is Dictionary and str((lr_entry as Dictionary).get("layer_uid", "")) == good_players_layer:
					(lr_entry as Dictionary)["viewers"] = ["p1\np2"]
	ls_res["val_rejects_ctrl_viewer"] = not bool(ls.validate_layer_catalog(bad_ctrl_world).get("ok", true))
	var bad_ev_world: Dictionary = b.get_world().duplicate(true)
	bad_ev_world["catalog"]["editor_view"]["layers"] = {"": "unknown_layer"}
	ls_res["val_rejects_empty_ev_floor"] = not bool(ls.validate_layer_catalog(bad_ev_world).get("ok", true))

	# Regression (Challenger 2 #3): BOM & edge control-char parity across host_v1_adapter & feature_layer_stack
	var bel_str: String = "bad" + char(7)
	ls_res["adapter_ctrl_sanitized_empty"] = (
		adapter.sanitize_viewer_key(bel_str) == ""
		and adapter.sanitize_viewer_key("bad\n") == ""
		and adapter.sanitize_viewer_key("\tbad\t") == ""
		and adapter.sanitize_viewer_key("\t" + v160 + "\t") == ""
		and adapter.sanitize_viewer_key("  " + v160 + "  ") == v160
		and adapter.sanitize_viewer_key("\ufeff" + v160) == v160
		and adapter.sanitize_viewer_key("\ufeff   ") == ""
		and adapter.sanitize_viewer_key("  \ufeffp1") == "p1"
		and adapter.sanitize_viewer_key("  \ufeff   ") == ""
	)
	var adp_bel_res: Dictionary = adapter.create_layer(b.get_world(), f0_uid, "AdpBel", "area", "players", [bel_str])
	var adp_bom_ws_res: Dictionary = adapter.create_layer(b.get_world(), f0_uid, "AdpBomWs", "area", "players", ["\ufeff   "])
	var adp_sp_bom_ws_res: Dictionary = adapter.create_layer(b.get_world(), f0_uid, "AdpSpBomWs", "area", "players", ["  \ufeff   "])
	var adp_sp_bom_p1_res: Dictionary = adapter.create_layer(b.get_world(), f0_uid, "AdpSpBomP1", "area", "players", ["  \ufeffp1"])
	var adp_sp_bom_p1_uid: String = str(adp_sp_bom_p1_res.get("layer_uid", ""))
	ls_res["adapter_create_layer_rejects_ctrl_bom_ws"] = (
		not bool(adp_bel_res.get("ok", true))
		and not bool(adp_bom_ws_res.get("ok", true))
		and not bool(adp_sp_bom_ws_res.get("ok", true))
		and bool(adp_sp_bom_p1_res.get("ok", false))
		and ls.get_layer(adp_sp_bom_p1_uid).get("viewers", []) == ["p1"]
		and bool(ls.validate_layer_catalog().get("ok", false))
	)
	var bom160_uid: String = ls.add_layer("Bom160", "area", "players", f0_uid, ["\ufeff" + v160])
	var bom_dedup_uid: String = ls.add_layer("BomDedup", "area", "players", f0_uid, ["\ufeffp1", "p1"])
	var sp160_uid: String = ls.add_layer("Sp160", "area", "players", f0_uid, ["  " + v160 + "  "])
	var sp_bom_p1_uid: String = ls.add_layer("SpBomP1", "area", "players", f0_uid, ["  \ufeffp1"])
	ls_res["ls_bom_and_ctrl_parity_ok"] = (
		not bom160_uid.is_empty()
		and ls.get_layer(bom160_uid).get("viewers", []) == [v160]
		and not bom_dedup_uid.is_empty()
		and ls.get_layer(bom_dedup_uid).get("viewers", []) == ["p1"]
		and not sp160_uid.is_empty()
		and ls.get_layer(sp160_uid).get("viewers", []) == [v160]
		and not sp_bom_p1_uid.is_empty()
		and ls.get_layer(sp_bom_p1_uid).get("viewers", []) == ["p1"]
		and ls.add_layer("LsBomWs", "area", "players", f0_uid, ["\ufeff   "]).is_empty()
		and ls.add_layer("LsSpBomWs", "area", "players", f0_uid, ["  \ufeff   "]).is_empty()
		and ls.add_layer("LsBel", "area", "players", f0_uid, [bel_str]).is_empty()
		and ls.add_layer("LsTab160", "area", "players", f0_uid, ["\t" + v160 + "\t"]).is_empty()
		and ls.set_layer_access(good_players_layer, "players", ["  \ufeffp1", "p1"])
		and ls.get_layer(good_players_layer).get("viewers", []) == ["p1"]
		and bool(ls.validate_layer_catalog().get("ok", false))
		and not ls.set_layer_access(good_players_layer, "players", ["  \ufeff   "])
		and ls.set_layer_access(good_players_layer, "players", ["\ufeffp1", "p1"])
		and ls.get_layer(good_players_layer).get("viewers", []) == ["p1"]
		and bool(ls.validate_layer_catalog().get("ok", false))
		and ls.set_layer_access(good_players_layer, "players", ["\ufeff" + v160])
		and ls.get_layer(good_players_layer).get("viewers", []) == [v160]
		and not ls.set_layer_access(good_players_layer, "players", [bel_str])
		and not ls.set_layer_access(good_players_layer, "players", ["\t" + v160 + "\t"])
		and ls.rename_layer(good_players_layer, "\ufeffBomLayer")
		and str(ls.get_layer(good_players_layer).get("name", "")) == "BomLayer"
		and not ls.rename_layer(good_players_layer, "  \ufeffSpBom")
		and not ls.rename_layer(good_players_layer, "\ufeff   ")
		and not ls.rename_layer(good_players_layer, "\ufeff")
	)
	var bad_bom_viewer_world: Dictionary = b.get_world().duplicate(true)
	for fl_entry: Variant in bad_bom_viewer_world["catalog"]["layers"]["floors"]:
		if fl_entry is Dictionary and str((fl_entry as Dictionary).get("floor_uid", "")) == f0_uid:
			for lr_entry: Variant in (fl_entry as Dictionary).get("layers", []):
				if lr_entry is Dictionary and str((lr_entry as Dictionary).get("layer_uid", "")) == good_players_layer:
					(lr_entry as Dictionary)["viewers"] = ["\ufeffp1"]
	ls_res["val_rejects_raw_bom_viewer"] = not bool(ls.validate_layer_catalog(bad_bom_viewer_world).get("ok", true))

	# Regression (Iter 5 Reviewer 2): persistent: null in set_default_layer & validate_layer_catalog
	var persistent_null_world: Dictionary = b.get_world().duplicate(true)
	var null_val: Variant = JSON.parse_string("null")
	for fl_entry: Variant in persistent_null_world["catalog"]["layers"]["floors"]:
		if fl_entry is Dictionary and str((fl_entry as Dictionary).get("floor_uid", "")) == f0_uid:
			for lr_entry: Variant in (fl_entry as Dictionary).get("layers", []):
				if lr_entry is Dictionary and str((lr_entry as Dictionary).get("layer_uid", "")) == def_ent_uid:
					(lr_entry as Dictionary)["persistent"] = null_val
	var pnull_val_res: Dictionary = ls.validate_layer_catalog(persistent_null_world)
	var pnull_errs: Array = pnull_val_res.get("errors", [])
	var orig_def_layer_ref: Dictionary = {}
	for fl_entry: Variant in b.get_world()["catalog"]["layers"]["floors"]:
		if fl_entry is Dictionary and str((fl_entry as Dictionary).get("floor_uid", "")) == f0_uid:
			for lr_entry: Variant in (fl_entry as Dictionary).get("layers", []):
				if lr_entry is Dictionary and str((lr_entry as Dictionary).get("layer_uid", "")) == def_ent_uid:
					orig_def_layer_ref = lr_entry as Dictionary
	orig_def_layer_ref["persistent"] = null_val
	var set_def_pnull_ok: bool = ls.set_default_layer(f0_uid, def_ent_uid)
	orig_def_layer_ref["persistent"] = true
	ls_res["persistent_null_rejected"] = (
		not bool(pnull_val_res.get("ok", true))
		and ("invalid_layer_bools:" + def_ent_uid) in pnull_errs
		and ("default_layer_not_persistent:" + f0_uid) in pnull_errs
		and not set_def_pnull_ok
	)

	# Iter 7 Regression 6b: feature_layer_stack <null> UID & null kind guard
	var null_l_floor_entry: Dictionary = b.get_world()["catalog"]["layers"]["floors"][0]
	var saved_lf_uid: Variant = null_l_floor_entry["floor_uid"]
	var saved_l0_uid: Variant = null_l_floor_entry["layers"][0]["layer_uid"]
	var null_kind_luid: String = str(null_l_floor_entry["layers"][1]["layer_uid"])
	var saved_l1_kind: Variant = null_l_floor_entry["layers"][1]["kind"]
	null_l_floor_entry["floor_uid"] = JSON.parse_string("null")
	null_l_floor_entry["layers"][0]["layer_uid"] = JSON.parse_string("null")
	null_l_floor_entry["layers"][1]["kind"] = JSON.parse_string("null")
	ls_res["null_uid_and_kind_rejected"] = (
		ls.get_layer("<null>").is_empty()
		and not ls.set_layer_visibility("<null>", false)
		and not ls.set_layer_locked("<null>", true)
		and not ls.rename_layer("<null>", "X")
		and not ls.set_layer_access("<null>", "host", [])
		and not ls.set_default_layer("<null>", def_ent_uid)
		and not ls.set_default_layer(f0_uid, "<null>")
		and not ls.set_editor_view("<null>", def_ent_uid, true)
	)
	null_l_floor_entry["floor_uid"] = saved_lf_uid
	null_l_floor_entry["layers"][0]["layer_uid"] = saved_l0_uid
	var null_kind_def_rejected: bool = not ls.set_default_layer(f0_uid, null_kind_luid)
	null_l_floor_entry["layers"][1]["kind"] = saved_l1_kind
	ls_res["null_uid_and_kind_rejected"] = bool(ls_res["null_uid_and_kind_rejected"]) and null_kind_def_rejected
	results["layer_stack"] = ls_res

	# Core Plugin 4: feature_obstacle_authoring
	var oa = b.obstacle_authoring()
	var oa_res := {}
	var sq := PackedVector2Array([Vector2(-32, -32), Vector2(32, -32), Vector2(32, 32), Vector2(-32, 32)])
	var door_id: String = oa.add_door("oa_door", "OakDoor", Vector2(150, 150), [sq], false, true, ls.get_layer_uid("obstacle", f0_uid))
	oa_res["door_created"] = not door_id.is_empty()
	oa_res["door_open_ok"] = oa.set_door_open(door_id, true)
	oa_res["door_disable_ok"] = oa.set_obstacle_enabled(door_id, false)
	var door_ent: Dictionary = b.get_entity(door_id)
	var door_vec: Dictionary = door_ent["components"][0]["state"]["vector_drawing"]
	var door_src: Dictionary = door_vec["source"]
	oa_res["door_is_open"] = bool(door_src.get("open", false))
	oa_res["door_line_color_synced"] = door_vec.get("color", Color.BLACK) == oa.DOOR_OPEN_COLOR and door_vec.get("line_color", Color.BLACK) == oa.DOOR_OPEN_COLOR
	oa_res["door_is_disabled"] = not bool(door_src.get("enabled", true))
	var circle_shape: Dictionary = oa.make_circle_shape(48.0)
	var poly_shape: Dictionary = oa.make_polygon_shape([sq], Vector2(64, 64))
	oa_res["circle_uid_len"] = str(circle_shape.get("uid", "")).length()
	oa_res["poly_uid_len"] = str(poly_shape.get("uid", "")).length()
	var obs_obj_id: String = b.add_object_sprite("oa_obj", "Barrel", Vector2(400, 400), Vector2(48, 48), "")
	var attach_obs_res: Dictionary = oa.attach_obstacle(obs_obj_id, "object", "manual", 48.0, true, true)
	oa_res["attach_obs_ok"] = bool(attach_obs_res.get("ok", false)) and bool(attach_obs_res.get("manual", false))
	var valid_obs: Dictionary = oa.validate_obstacle_state(oa.make_obstacle_state("object", "manual", 48.0))
	oa_res["val_state_ok"] = bool(valid_obs.get("ok", false))
	var bad_obs_state: Dictionary = oa.make_obstacle_state("object", "manual", 48.0)
	bad_obs_state["shape"]["uid"] = "0".repeat(64)
	oa_res["bad_digest_rejected"] = not bool(oa.validate_obstacle_state(bad_obs_state).get("ok", true))
	var inf_basis_state: Dictionary = oa.make_obstacle_state("object", "manual", 48.0)
	inf_basis_state["shape"]["basis_size"] = Vector2(INF, 32.0)
	inf_basis_state["shape"]["uid"] = oa.compute_shape_digest(inf_basis_state["shape"])
	oa_res["inf_basis_rejected"] = not bool(oa.validate_obstacle_state(inf_basis_state).get("ok", true))
	var nan_rad_state: Dictionary = oa.make_obstacle_state("object", "manual", 48.0)
	nan_rad_state["shape"]["kind"] = "polygon"
	nan_rad_state["shape"]["radius"] = NAN
	nan_rad_state["shape"]["uid"] = oa.compute_shape_digest(nan_rad_state["shape"])
	oa_res["nan_radius_rejected"] = not bool(oa.validate_obstacle_state(nan_rad_state).get("ok", true))

	# Regression (Challenger 2 #1 & #2): strict shape.schema is int & INF/NAN bounds/paths/segments rejection
	var bad_schema_all_rejected: bool = true
	for bad_sc: Variant in [true, 1.5, 1.0, "1"]:
		var sc_state: Dictionary = oa.make_obstacle_state("object", "manual", 48.0)
		sc_state["shape"]["schema"] = bad_sc
		sc_state["shape"]["uid"] = oa.compute_shape_digest(sc_state["shape"])
		if bool(oa.validate_obstacle_state(sc_state).get("ok", true)):
			bad_schema_all_rejected = false
	oa_res["bad_shape_schema_types_rejected"] = bad_schema_all_rejected

	var inf_bounds_state: Dictionary = oa.make_obstacle_state("wall", "manual", 48.0)
	inf_bounds_state["shape"]["bounds"] = Rect2(INF, 0, 10, 10)
	inf_bounds_state["shape"]["uid"] = oa.compute_shape_digest(inf_bounds_state["shape"])
	var nan_bounds_state: Dictionary = oa.make_obstacle_state("wall", "manual", 48.0)
	nan_bounds_state["shape"]["bounds"] = Rect2(0, 0, NAN, 10)
	nan_bounds_state["shape"]["uid"] = oa.compute_shape_digest(nan_bounds_state["shape"])
	var nan_path_state: Dictionary = oa.make_obstacle_state("wall", "manual", 64.0, oa.make_polygon_shape([sq], Vector2(64, 64)))
	nan_path_state["shape"]["paths"] = [PackedVector2Array([Vector2(NAN, 0), Vector2(10, 0), Vector2(0, 10)])]
	nan_path_state["shape"]["uid"] = oa.compute_shape_digest(nan_path_state["shape"])
	var inf_seg_state: Dictionary = oa.make_obstacle_state("wall", "manual", 64.0, oa.make_polygon_shape([sq], Vector2(64, 64)))
	inf_seg_state["shape"]["segments"] = PackedVector2Array([Vector2(INF, 0), Vector2(10, 0)])
	inf_seg_state["shape"]["uid"] = oa.compute_shape_digest(inf_seg_state["shape"])
	var poly_nan_sanitized: Dictionary = oa.make_polygon_shape([PackedVector2Array([Vector2(NAN, 0), Vector2(10, 0), Vector2(0, 10)])])
	var poly_bad_seg_sanitized: Dictionary = oa.make_polygon_shape([sq], Vector2(64, 64), PackedVector2Array([Vector2(INF, 0), Vector2(10, 0)]))
	oa_res["inf_nan_geom_rejected"] = (
		not bool(oa.validate_obstacle_state(inf_bounds_state).get("ok", true))
		and not bool(oa.validate_obstacle_state(nan_bounds_state).get("ok", true))
		and not bool(oa.validate_obstacle_state(nan_path_state).get("ok", true))
		and not bool(oa.validate_obstacle_state(inf_seg_state).get("ok", true))
		and (poly_nan_sanitized.get("paths", []) as Array).is_empty()
		and (poly_nan_sanitized.get("segments", PackedVector2Array()) as PackedVector2Array).is_empty()
		and (poly_bad_seg_sanitized.get("segments", PackedVector2Array()) as PackedVector2Array).size() == 8
		and bool(oa.validate_obstacle_state(oa.make_obstacle_state("wall", "manual", 64.0, poly_bad_seg_sanitized)).get("ok", false))
	)
	var flip_id: String = b.add_object_sprite("oa_flip", "FlipObj", Vector2(450, 450), Vector2(48, 48), "")
	b.attach_component(flip_id, "res://modules/image_flip/comp_image_flip.gd", {}, false)
	var flip_conflict: Dictionary = oa.attach_obstacle(flip_id, "object", "manual", 48.0)
	oa_res["flip_conflict_rejected"] = not bool(flip_conflict.get("ok", true)) and str(flip_conflict.get("reason", "")) == "component_conflict_with_image_flip"
	var box_obs_conflict: Dictionary = oa.attach_obstacle(box_id, "object", "manual", 48.0)
	oa_res["scene_box_conflict_rejected"] = not bool(box_obs_conflict.get("ok", true)) and str(box_obs_conflict.get("reason", "")) == "component_conflict_with_scene_box:obstacle"
	var warn_count_before: int = sess_core.get_logger().get_warnings().size()
	var draw_obs_res: Dictionary = oa.attach_obstacle(plain_obj_id, "wall", "drawing", 48.0)
	oa_res["drawing_non_obstacle_warned"] = bool(draw_obs_res.get("ok", false)) and sess_core.get_logger().get_warnings().size() > warn_count_before

	# Regression (Iter 5 Challenger 2 #4): 3e38 overflow, identical/collinear/bowtie degenerate rejection, valid concave preserved
	var huge_poly_id: String = oa.add_wall("oa_huge", "HugePoly", Vector2.ZERO, [[Vector2(3e38, 0), Vector2(3e38, 100), Vector2(0, 100)]])
	var huge_seg_id: String = oa.add_segment_wall("oa_shuge", "HugeSeg", Vector2(3e38, 0), Vector2(3e38, 100), 6.0)
	var ident_id: String = oa.add_wall("oa_ident", "Ident", Vector2.ZERO, [[Vector2(10, 10), Vector2(10, 10), Vector2(10, 10)]])
	var collin_id: String = oa.add_wall("oa_collin", "Collin", Vector2.ZERO, [[Vector2(0, 0), Vector2(50, 0), Vector2(100, 0)]])
	var bowtie_id: String = oa.add_wall("oa_bowtie", "Bowtie", Vector2.ZERO, [[Vector2(0, 0), Vector2(100, 100), Vector2(100, 0), Vector2(0, 100)]])
	var concave_ring := [Vector2(0, 0), Vector2(100, 0), Vector2(100, 40), Vector2(40, 40), Vector2(40, 100), Vector2(0, 100)]
	var concave_id: String = oa.add_wall("oa_concave", "ConcaveL", Vector2(200, 200), [concave_ring])
	var poly_collin: Dictionary = oa.make_polygon_shape([PackedVector2Array([Vector2(0, 0), Vector2(50, 0), Vector2(100, 0)])], Vector2(0, -5))
	var poly_bowtie: Dictionary = oa.make_polygon_shape([PackedVector2Array([Vector2(0, 0), Vector2(100, 100), Vector2(100, 0), Vector2(0, 100)])])
	var poly_huge: Dictionary = oa.make_polygon_shape([PackedVector2Array([Vector2(3e38, 0), Vector2(3e38, 100), Vector2(0, 100)])])
	var poly_concave: Dictionary = oa.make_polygon_shape([PackedVector2Array(concave_ring)], Vector2(100, 100))
	oa_res["overflow_and_degenerate_rejected"] = (
		huge_poly_id.is_empty()
		and huge_seg_id.is_empty()
		and ident_id.is_empty()
		and collin_id.is_empty()
		and bowtie_id.is_empty()
		and not concave_id.is_empty()
		and (poly_collin.get("paths", []) as Array).is_empty()
		and not bool(oa.validate_obstacle_state(oa.make_obstacle_state("wall", "manual", 64.0, poly_collin)).get("ok", true))
		and (poly_bowtie.get("paths", []) as Array).is_empty()
		and (poly_huge.get("paths", []) as Array).is_empty()
		and (poly_concave.get("paths", []) as Array).size() == 1
		and bool(oa.validate_obstacle_state(oa.make_obstacle_state("wall", "manual", 64.0, poly_concave)).get("ok", false))
	)
	results["obstacle_authoring"] = oa_res

	# Core Plugin 5: feature_entity_library
	var el = b.entity_library()
	var el_res := {}
	el_res["no_favorites_api"] = not el.has_method("set_favorite") and not el.has_method("get_favorites")
	var tmpl: Dictionary = el.build_template_data("u1", "Goblin", "asset://" + "a".repeat(64) + ".png", Vector2(64, 64), true)
	el_res["template_keys_count"] = tmpl.size()
	el_res["template_bad_size_rejected"] = (
		el.build_template_data("u_small", "Tiny", "", Vector2(3.0, 64.0)).is_empty()
		and el.build_template_data("u_nan", "BadNan", "", Vector2(NAN, 64.0)).is_empty()
		and el.build_template_data("u_inf", "BadInf", "", Vector2(64.0, INF)).is_empty()
	)

	var lib_host := MockHost.new()
	lib_host.root = "user://mock_lib"
	lib_host.destination = "user://mock_lib/sessions/demo_" + "b".repeat(32)
	var lib_sess = sdk.create_session(lib_host, {})
	lib_sess.get_logger().set_emit_to_engine(false)
	var lib_builder = sdk.create_world_builder(lib_sess, 150.0)
	lib_builder.set_enabled_modules([])
	lib_builder.set_disabled_module_policy("preserve")
	var lib_el = lib_builder.entity_library()
	var store_preserve := MockAssetStore.new()
	lib_el.get_writer().set_shared_asset_store(store_preserve, true)
	var preset_entry := {
		"id": "goblin_scout",
		"name": "Goblin Scout",
		"folder_name": "Monsters",
		"sprite_ref": "asset://" + "c".repeat(64) + ".png",
		"size_world": Vector2(64, 64),
		"vision_radius": 320.0,
		"create_preset": true,
	}
	var inspect_off: Dictionary = lib_el.inspect_preset_components(preset_entry)
	el_res["inspect_off_rejected"] = not bool(inspect_off.get("ok", true)) and str(inspect_off.get("reason", "")) == "preset_component_unavailable"
	var inspect_snap_off: Dictionary = lib_el.inspect_preset_components({
		"record": {
			"kind": "preset",
			"snapshot": {
				"version": 3,
				"entities": [
					{
						"components": [
							{"script": "res://scenes/entities/components/comp_visual.gd", "state": {}},
							{"script": "res://scenes/entities/components/comp_permission.gd", "state": {}},
							{"script": "res://modules/simple_fog/comp_simple_vision.gd", "state": {}},
						]
					}
				],
			},
		}
	})
	el_res["inspect_record_snapshot_rejected"] = not bool(inspect_snap_off.get("ok", true)) and str(inspect_snap_off.get("reason", "")) == "preset_component_unavailable"

	# Safe coercion regression: string "false" create_preset & null vision_radius (zero SCRIPT ERROR)
	var inspect_str_false: Dictionary = lib_el.inspect_preset_components({
		"id": "u_str_false",
		"name": "StrFalse",
		"create_preset": "false",
		"vision_radius": 320.0,
	})
	var inspect_null_vr: Dictionary = lib_el.inspect_preset_components({
		"id": "u_null_vr",
		"name": "NullVR",
		"create_preset": true,
		"vision_radius": null,
	})
	el_res["safe_coercion_ok"] = bool(inspect_str_false.get("ok", false)) and bool(inspect_null_vr.get("ok", false))

	# Regression (Iter 5 Challenger 2 #3 & Reviewer 2): null script/name never produce "<null>" & INF in _to_bool/vision_radius
	var null_comp_entry: Variant = JSON.parse_string('{"id": null, "name": null, "kind": "preset", "vision_radius": null, "components": [{"script": null}, null, ""], "snapshot": null, "record": null}')
	var inspect_null_comp: Dictionary = lib_el.inspect_preset_components(null_comp_entry as Dictionary)
	var null_snap_entry: Variant = JSON.parse_string('{"id": null, "name": null, "kind": "preset", "record": {"snapshot": {"entities": [{"components": [{"script": null}]}]}}}')
	var inspect_null_snap: Dictionary = lib_el.inspect_preset_components(null_snap_entry as Dictionary)
	var null_name_reg_entry: Variant = JSON.parse_string('{"id": null, "name": null, "kind": "preset", "vision_radius": 320.0, "create_preset": true}')
	var store_null_name := MockAssetStore.new()
	var host_null_name := MockHost.new()
	host_null_name.root = "user://mock_lib"
	host_null_name.destination = "user://mock_lib/sessions/demo_" + "b".repeat(32)
	var sess_null_name = sdk.create_session(host_null_name, {})
	sess_null_name.get_logger().set_emit_to_engine(false)
	var wb_null_name = sdk.create_world_builder(sess_null_name, 150.0)
	wb_null_name.set_enabled_modules([])
	var el_null_name = wb_null_name.entity_library()
	el_null_name.get_writer().set_shared_asset_store(store_null_name, true)
	var reg_null_name: Dictionary = el_null_name.register_entries("test_ns_null", [null_name_reg_entry], host_null_name, sess_null_name, true)
	var warned_null_list: Array = reg_null_name.get("warned_presets", [])
	var warned_entry_name: String = str((warned_null_list[0] as Dictionary).get("entry", "")) if not warned_null_list.is_empty() else ""
	var warn_text_null: String = str(host_null_name.warnings[0]) if not host_null_name.warnings.is_empty() else ""
	var inspect_inf_vr: Dictionary = lib_el.inspect_preset_components({"id": "u_inf_vr", "name": "InfVR", "create_preset": true, "vision_radius": INF})
	el_res["null_script_name_and_inf_ok"] = (
		bool(inspect_null_comp.get("ok", false))
		and (inspect_null_comp.get("unavailable", []) as Array).is_empty()
		and bool(inspect_null_snap.get("ok", false))
		and (inspect_null_snap.get("unavailable", []) as Array).is_empty()
		and warned_entry_name == "unnamed_preset"
		and not warn_text_null.contains("<null>")
		and not value_utils.coerce_bool(INF, false, true)
		and bool(inspect_inf_vr.get("ok", false))
	)

	var preset_row_id: String = ("fus:lib:preset:%s:%s" % ["test_ns", "goblin_scout"]).sha256_text().left(32)
	var reg_preserve: Dictionary = lib_el.register_presets("test_ns", [preset_entry], lib_host, lib_sess)
	el_res["preserve_ok"] = bool(reg_preserve.get("ok", false))
	el_res["preserve_count"] = int(reg_preserve.get("count", -1))
	el_res["preserve_not_skipped"] = not bool(reg_preserve.get("skipped", true))
	el_res["preserve_warned"] = (reg_preserve.get("warned_presets", []) as Array).size() == 1
	el_res["preserve_host_warn_has_reason"] = lib_host.warnings.size() == 1 and str(lib_host.warnings[0]).contains("preset_component_unavailable")
	el_res["preserve_has_vision_comp"] = store_preserve.records.has(preset_row_id) and _record_has_component(store_preserve.records[preset_row_id], "res://modules/simple_fog/comp_simple_vision.gd")

	lib_builder.set_disabled_module_policy("skip")
	var reg_skip: Dictionary = lib_el.register_presets("test_ns", [preset_entry], lib_host, lib_sess)
	el_res["skip_ok"] = bool(reg_skip.get("ok", false))
	el_res["skip_count"] = int(reg_skip.get("count", -1))
	el_res["skip_not_skipped"] = not bool(reg_skip.get("skipped", true))
	el_res["skip_stripped_vision"] = (reg_skip.get("stripped_components", []) as Array).size() == 1
	el_res["skip_removed_vision_comp"] = store_preserve.records.has(preset_row_id) and not _record_has_component(store_preserve.records[preset_row_id], "res://modules/simple_fog/comp_simple_vision.gd")

	# Fallback create_preset = false when unstrippable inactive component (comp_backpack.gd) is present
	var store_fb := MockAssetStore.new()
	lib_el.get_writer().set_shared_asset_store(store_fb, true)
	var bp_entry := {
		"id": "pack_mule",
		"name": "Pack Mule",
		"create_preset": true,
		"components": [{"script": "res://modules/backpack/comp_backpack.gd"}],
	}
	var reg_fb: Dictionary = lib_el.register_entries("test_ns", [bp_entry], lib_host, lib_sess, true)
	var fb_unit_id: String = ("fus:lib:unit:%s:%s" % ["test_ns", "pack_mule"]).sha256_text().left(32)
	var fb_decoded: Variant = bytes_to_var(store_fb.records[fb_unit_id]) if store_fb.records.has(fb_unit_id) else {}
	el_res["fallback_unit_ok"] = (
		bool(reg_fb.get("ok", false))
		and int(reg_fb.get("count", -1)) == 1
		and not bool(reg_fb.get("skipped", true))
		and (reg_fb.get("skipped_presets", []) as Array).size() == 1
		and fb_decoded is Dictionary
		and str((fb_decoded as Dictionary).get("kind", "")) == "unit"
	)

	var lib_host2 := MockHost.new()
	lib_host2.root = "user://mock_lib"
	lib_host2.destination = "user://mock_lib/sessions/demo_" + "b".repeat(32)
	var lib_sess2 = sdk.create_session(lib_host2, {})
	lib_sess2.get_logger().set_emit_to_engine(false)
	var lib_builder2 = sdk.create_world_builder(lib_sess2, 150.0)
	lib_builder2.set_enabled_modules(["simple_fog"])
	var lib_el2 = lib_builder2.entity_library()
	var store_enabled := MockAssetStore.new()
	lib_el2.get_writer().set_shared_asset_store(store_enabled, true)
	var reg_enabled: Dictionary = lib_el2.register_presets("test_ns", [preset_entry], lib_host2, lib_sess2)
	el_res["enabled_ok"] = bool(reg_enabled.get("ok", false))
	el_res["enabled_count"] = int(reg_enabled.get("count", -1))
	el_res["enabled_not_skipped"] = not bool(reg_enabled.get("skipped", true))
	el_res["enabled_zero_warnings"] = lib_host2.warnings.size() == 0 and (reg_enabled.get("warned_presets", []) as Array).is_empty()
	el_res["enabled_has_vision_comp"] = store_enabled.records.has(preset_row_id) and _record_has_component(store_enabled.records[preset_row_id], "res://modules/simple_fog/comp_simple_vision.gd")
	lib_el2.rollback_last_registration()
	el_res["rollback_done"] = store_enabled.records.is_empty()

	# Iter 7 Regression 1: entity_library_writer + asset_publisher + package_source hardening
	var writer_r7 = lib_el.get_writer()
	var bom_writer_ok: bool = (
		writer_r7._to_bool(INF, false) == false
		and writer_r7._to_bool(-INF, false) == false
		and writer_r7._to_bool("\ufefffalse", true) == false
		and writer_r7._to_bool(&"\ufefffalse", true) == false
	)
	var host_bom := MockHost.new()
	host_bom.root = "user://mock_lib"
	host_bom.destination = "user://mock_lib/sessions/demo_" + "b".repeat(32)
	var sess_bom = sdk.create_session(host_bom, {})
	sess_bom.get_logger().set_emit_to_engine(false)
	var wb_bom = sdk.create_world_builder(sess_bom, 150.0)
	wb_bom.set_enabled_modules([])
	wb_bom.set_disabled_module_policy("preserve")
	var el_bom = wb_bom.entity_library()
	var store_bom := MockAssetStore.new()
	el_bom.get_writer().set_shared_asset_store(store_bom, true)
	var bom_reg: Dictionary = el_bom.register_entries("ns_bom", [
		{
			"id": "bom_bypass",
			"name": "\ufeff",
			"create_preset": "\ufefffalse",
			"vision_radius": "\ufeff320.0",
			"all_players_can_operate": INF,
		},
		{
			"id": "inf_perm",
			"name": "InfPerm",
			"create_preset": true,
			"all_players_can_operate": INF,
		},
	], host_bom, sess_bom, true)
	var bom_reg_warns_empty: bool = host_bom.warnings.is_empty()
	var bom_unit_id: String = ("fus:lib:unit:%s:%s" % ["ns_bom", "bom_bypass"]).sha256_text().left(32)
	var bom_preset_id: String = ("fus:lib:preset:%s:%s" % ["ns_bom", "bom_bypass"]).sha256_text().left(32)
	var inf_perm_id: String = ("fus:lib:preset:%s:%s" % ["ns_bom", "inf_perm"]).sha256_text().left(32)
	var bom_unit_dec: Variant = bytes_to_var(store_bom.records.get(bom_unit_id, PackedByteArray()))
	var inf_perm_dec: Variant = bytes_to_var(store_bom.records.get(inf_perm_id, PackedByteArray()))
	var inf_perm_all: bool = true
	if inf_perm_dec is Dictionary:
		var ents_ip: Array = (inf_perm_dec as Dictionary).get("record", {}).get("snapshot", {}).get("entities", [])
		if not ents_ip.is_empty():
			for c: Variant in (ents_ip[0] as Dictionary).get("components", []):
				if c is Dictionary and str((c as Dictionary).get("script", "")).ends_with("comp_permission.gd"):
					inf_perm_all = bool((c as Dictionary).get("state", {}).get("all_players_can_operate", true))

	var store_null_rev := MockNullRevisionStore.new()
	var writer_null_rev = sdk.create_entity_library_writer()
	writer_null_rev.set_shared_asset_store(store_null_rev, true)
	var null_rev_reg: Dictionary = writer_null_rev.register_entries("ns_null_rev", [
		{"id": "nr1", "name": "NR1", "create_preset": false}
	], host_bom, sess_bom, true)

	var pub_r7 = sdk.create_asset_publisher()
	var pub_coerce_ok: bool = (
		pub_r7._coerce_bool(INF, false) == false
		and pub_r7._coerce_bool(-INF, false) == false
		and pub_r7._coerce_bool("\ufefffalse", true) == false
		and pub_r7._coerce_bool(&"false", true) == false
	)
	var rem_null_info: Dictionary = JSON.parse_string('{"kind": "remote", "resolved_path_or_url": null, "url": "https://example.com/a.png"}') as Dictionary
	var rem_null_res: Dictionary = pub_r7.resolve_sprite_ref("https://example.com/a.png", rem_null_info, null, host_bom, sess_bom, {"download_remote_assets": false, "skip_missing_assets": "\ufefffalse"})
	var loc_null_info: Dictionary = JSON.parse_string('{"kind": "local", "resolved_path_or_url": null, "rel_path": "Images/Token Hero.png", "exists": "false"}') as Dictionary
	var loc_null_res: Dictionary = pub_r7.resolve_sprite_ref("Images/Token Hero.png", loc_null_info, null, host_bom, sess_bom, {"skip_missing_assets": "\ufefffalse"})

	var pkg_r7 = sdk.create_package_source()
	var pkg_norm_null: Dictionary = pkg_r7.normalize_rel_path("a.png", [null])
	var tmp_pkg_dir: String = OS.get_user_data_dir().path_join("r7_pkg_test")
	DirAccess.make_dir_recursive_absolute(tmp_pkg_dir)
	var tmp_pack_path: String = tmp_pkg_dir.path_join("pack.json")
	var pf := FileAccess.open(tmp_pack_path, FileAccess.WRITE)
	pf.store_string('{"id": "\\ufeff", "title": "T"}')
	pf.close()
	var pkg_bom_open: Dictionary = pkg_r7.open_package(tmp_pack_path, "pack.json", [null, "id"])
	pkg_r7.close()

	el_res["r7_modules_hardening_ok"] = (
		bom_writer_ok
		and bool(bom_reg.get("ok", false))
		and (bom_reg.get("warned_presets", []) as Array).is_empty()
		and bom_reg_warns_empty
		and store_bom.records.has(bom_unit_id)
		and not store_bom.records.has(bom_preset_id)
		and bom_unit_dec is Dictionary
		and str((bom_unit_dec as Dictionary).get("kind", "")) == "unit"
		and str((bom_unit_dec as Dictionary).get("name", "")) == "Unnamed Unit"
		and not inf_perm_all
		and bool(null_rev_reg.get("ok", false))
		and pub_coerce_ok
		and bool(rem_null_res.get("ok", false))
		and not host_bom.warnings.is_empty()
		and not str(host_bom.warnings[0]).contains("<null>")
		and not bool(loc_null_res.get("ok", true))
		and str(loc_null_res.get("reason", "")).begins_with("missing_asset:")
		and bool(pkg_norm_null.get("ok", false))
		and str(pkg_norm_null.get("rel_path", "")) == "a.png"
		and not bool(pkg_bom_open.get("ok", true))
		and str(pkg_bom_open.get("reason", "")) == "manifest_empty_key:id"
	)
	results["entity_library"] = el_res

	# Iter 8 Regression: (a) 70k/140k flat payloads, (b) memo pollution bypass + interleaved,
	# (c) dag18/dag24 < 50ms + set_module_state/obstacle guards, (d) append_entity_component depth 6 & dag24,
	# plus minor fixes (BOM-only entry_name, NUL perm, strict lowercase asset ref)
	var r8 := {}
	var wb_big = sdk.create_world_builder(sdk.create_session(MockHost.new(), {}), 150.0)
	wb_big.get_logger().set_emit_to_engine(false)
	var arr70: Array = []
	arr70.resize(70000)
	for i70: int in range(70000):
		arr70[i70] = i70
	var p_arr70: Dictionary = {"a": arr70}

	var grid140: Array = []
	grid140.resize(140000)
	for i140: int in range(140000):
		grid140[i140] = i140
	var p_grid140: Dictionary = {"grid": grid140}

	var p_dict70: Dictionary = {}
	for k70: int in range(70000):
		p_dict70["k%d" % k70] = k70

	var large_arr70_ok: bool = (
		adapter.is_valid_state_data(p_arr70, 3)
		and adapter.bounded_variant_size_estimate(p_arr70, 3, [], adapter.MAX_MODULE_ENTRY_BYTES) > 0
		and wb_big.can_fit_module_state("r8_arr70", 1, p_arr70)
		and wb_big.set_module_state("r8_arr70", 1, p_arr70)
	)
	if large_arr70_ok:
		var st_arr70: Dictionary = wb_big.get_world()["modules"]["entries"]["r8_arr70"]["state"]
		var cln_arr70: Variant = adapter._safe_clone_variant(p_arr70)
		var san_arr70: Variant = wb_big.sanitize_module_data(p_arr70)
		large_arr70_ok = (
			(st_arr70["a"] as Array).size() == 70000
			and cln_arr70 is Dictionary and ((cln_arr70 as Dictionary)["a"] as Array).size() == 70000
			and int(((cln_arr70 as Dictionary)["a"] as Array)[69999]) == 69999
			and san_arr70 is Dictionary and ((san_arr70 as Dictionary)["a"] as Array).size() == 70000
			and int(((san_arr70 as Dictionary)["a"] as Array)[69999]) == 69999
		)

	var large_grid140_ok: bool = (
		adapter.is_valid_state_data(p_grid140, 3)
		and adapter.bounded_variant_size_estimate(p_grid140, 3, [], adapter.MAX_MODULE_ENTRY_BYTES) > 0
		and wb_big.can_fit_module_state("r8_grid140", 1, p_grid140)
		and wb_big.set_module_state("r8_grid140", 1, p_grid140)
	)
	if large_grid140_ok:
		var st_grid140: Dictionary = wb_big.get_world()["modules"]["entries"]["r8_grid140"]["state"]
		var cln_grid140: Variant = adapter._safe_clone_variant(p_grid140)
		var san_grid140: Variant = wb_big.sanitize_module_data(p_grid140)
		large_grid140_ok = (
			(st_grid140["grid"] as Array).size() == 140000
			and cln_grid140 is Dictionary and ((cln_grid140 as Dictionary)["grid"] as Array).size() == 140000
			and int(((cln_grid140 as Dictionary)["grid"] as Array)[139999]) == 139999
			and san_grid140 is Dictionary and ((san_grid140 as Dictionary)["grid"] as Array).size() == 140000
			and int(((san_grid140 as Dictionary)["grid"] as Array)[139999]) == 139999
		)

	var large_dict70_ok: bool = (
		adapter.is_valid_state_data(p_dict70, 3)
		and adapter.bounded_variant_size_estimate(p_dict70, 3, [], adapter.MAX_MODULE_ENTRY_BYTES) > 0
		and wb_big.can_fit_module_state("r8_dict70", 1, p_dict70)
		and wb_big.set_module_state("r8_dict70", 1, p_dict70)
	)
	if large_dict70_ok:
		var st_dict70: Dictionary = wb_big.get_world()["modules"]["entries"]["r8_dict70"]["state"]
		var cln_dict70: Variant = adapter._safe_clone_variant(p_dict70)
		var san_dict70: Variant = wb_big.sanitize_module_data(p_dict70)
		large_dict70_ok = (
			st_dict70.size() == 70000
			and cln_dict70 is Dictionary and (cln_dict70 as Dictionary).size() == 70000
			and int((cln_dict70 as Dictionary).get("k69999", -1)) == 69999
			and san_dict70 is Dictionary and (san_dict70 as Dictionary).size() == 70000
			and int((san_dict70 as Dictionary).get("k69999", -1)) == 69999
		)
	r8["large_arr70_ok"] = large_arr70_ok
	r8["large_grid140_ok"] = large_grid140_ok
	r8["large_dict70_ok"] = large_dict70_ok

	var junk65: Array = []
	for j_i: int in range(65):
		junk65.append({"j": j_i})
	var dag15: Dictionary = _make_dag(15, {})
	var bypass15: Dictionary = {"junk": junk65, "dag": dag15}
	var bypass17: Dictionary = {"junk": junk65, "dag": _make_dag(17, {})}
	var tm0: int = Time.get_ticks_msec()
	var dag15_v: bool = adapter.is_valid_state_data(dag15, 3)
	var dag15_b: int = adapter.bounded_variant_size_estimate(dag15, 3, [], adapter.MAX_MODULE_ENTRY_BYTES)
	var tm_dag15: int = Time.get_ticks_msec() - tm0
	var tm1: int = Time.get_ticks_msec()
	var bp15_v: bool = adapter.is_valid_state_data(bypass15, 3)
	var bp15_b: int = adapter.bounded_variant_size_estimate(bypass15, 3, [], adapter.MAX_MODULE_ENTRY_BYTES)
	var tm_bp15: int = Time.get_ticks_msec() - tm1
	var tm2: int = Time.get_ticks_msec()
	var bp17_v: bool = adapter.is_valid_state_data(bypass17, 3)
	var bp17_b: int = adapter.bounded_variant_size_estimate(bypass17, 3, [], adapter.MAX_MODULE_ENTRY_BYTES)
	var tm_bp17: int = Time.get_ticks_msec() - tm2

	var size20_list: Array = []
	for s20_i: int in range(65):
		var sd := {}
		for sk_i: int in range(20):
			sd["x%d" % sk_i] = sk_i
		size20_list.append(sd)
	var dag15_sub: Dictionary = _make_dag(15, {})
	size20_list.append(dag15_sub)
	var interleaved_payload := {"a": size20_list, "b": dag15_sub}
	var tm3: int = Time.get_ticks_msec()
	var inter_v: bool = adapter.is_valid_state_data(interleaved_payload, 3)
	var inter_b: int = adapter.bounded_variant_size_estimate(interleaved_payload, 3, [], adapter.MAX_MODULE_ENTRY_BYTES)
	var tm_inter: int = Time.get_ticks_msec() - tm3

	var list_64_dag20: Array = []
	for d20_i: int in range(64):
		list_64_dag20.append(_make_dag(20, {}))
	var ring_payload := {"list": list_64_dag20, "extra": _make_dag(21, {})}
	var ctx_ring := {"nodes": 0}
	var tm4: int = Time.get_ticks_msec()
	var ring_v: bool = adapter.is_valid_state_data(ring_payload, 3, [], 32, ctx_ring)
	var tm_ring: int = Time.get_ticks_msec() - tm4
	var nodes_ring: int = int(ctx_ring.get("nodes", 0))

	# Iter 9 Regression: pattern_d (32 heavy dag24 + depth-16 trap with 33 size-20 dicts per level)
	var trap_node: Dictionary = {"leaf": 1}
	for _tl: int in range(16):
		var j33: Array = []
		for _ji: int in range(33):
			var s20 := {}
			for sk_i2: int in range(20):
				s20["k%d" % sk_i2] = sk_i2
			j33.append(s20)
		trap_node = {"l": trap_node, "j": j33, "r": trap_node}
	var h32_dag24: Array = []
	for _hi: int in range(32):
		h32_dag24.append(_make_dag(24, {}))
	var p_pattern_d := {"h": h32_dag24, "trap": trap_node}
	var ctx_pat := {"nodes": 0}
	var tm_pat0: int = Time.get_ticks_msec()
	var pat_v: bool = adapter.is_valid_state_data(p_pattern_d, 3, [], 32, ctx_pat)
	var tm_pat: int = Time.get_ticks_msec() - tm_pat0
	var nodes_pat: int = int(ctx_pat.get("nodes", 0))

	r8["memo_bypass_ok"] = (
		dag15_v and dag15_b == 2359240 and tm_dag15 < 50
		and bp15_v and bp15_b > 2359240 and tm_bp15 < 50
		and bp17_v and bp17_b > 2359240 and tm_bp17 < 50
		and inter_v and inter_b > 2359240 and tm_inter < 50
		and ring_v and nodes_ring < 100000 and tm_ring < 200
	)
	r8["pattern_d_memo_ok"] = pat_v and nodes_pat < 100000 and tm_pat < 200
	r8["memo_bypass_debug"] = [dag15_v, dag15_b, tm_dag15, bp15_v, bp15_b, tm_bp15, bp17_v, bp17_b, tm_bp17, inter_v, inter_b, tm_inter, ring_v, tm_ring, nodes_ring, pat_v, tm_pat, nodes_pat]

	var dag18: Dictionary = _make_dag(18, {})
	var dag_sub_entries: Array = []
	var sub_tok: int = bus.subscribe(func(e: Dictionary) -> void: dag_sub_entries.append(e))
	var all_dag_fast: bool = true
	for d_item: Dictionary in [dag18, dag24]:
		var tc0: int = Time.get_ticks_msec()
		var _cln_d: Variant = adapter._safe_clone_variant(d_item)
		var tc1: int = Time.get_ticks_msec()
		var _san_d: Variant = adapter.sanitize_module_value(d_item)
		var tc2: int = Time.get_ticks_msec()
		var pr_d: bool = reg.probe_feature_manager(d_item)
		var tc3: int = Time.get_ticks_msec()
		var lg_d: Dictionary = bus.info("dag_src", "dag_msg", d_item)
		var tc4: int = Time.get_ticks_msec()
		var tmpl_d: Dictionary = b.entity_library().build_template_data("dag_u", "DagU", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", d_item)
		var tc5: int = Time.get_ticks_msec()
		var obs_d: Dictionary = b.obstacle_authoring().make_obstacle_state("object", "manual", 64.0, d_item, d_item)
		var tc6: int = Time.get_ticks_msec()
		if (
			(tc1 - tc0) >= 150
			or (tc2 - tc1) >= 150
			or pr_d or (tc3 - tc2) >= 150
			or lg_d.is_empty() or (tc4 - tc3) >= 150
			or tmpl_d.is_empty() or (tc5 - tc4) >= 150
			or obs_d.is_empty() or (tc6 - tc5) >= 150
		):
			all_dag_fast = false
	var tc_get0: int = Time.get_ticks_msec()
	var _got_dag_entries: Array = bus.get_entries(0, 0, 10)
	var tc_get1: int = Time.get_ticks_msec()
	bus.unsubscribe(sub_tok)
	if (tc_get1 - tc_get0) >= 50 or dag_sub_entries.size() != 2:
		all_dag_fast = false

	var ts_mod0: int = Time.get_ticks_msec()
	var set_dag18_res: Dictionary = adapter.set_module_state(wb_big.get_world(), "r8_dag18", 1, dag18)
	var ts_mod1: int = Time.get_ticks_msec()
	r8["dag18_24_six_funcs_fast"] = all_dag_fast
	r8["set_module_state_dag18_limit"] = (
		not bool(set_dag18_res.get("ok", true))
		and str(set_dag18_res.get("reason", "")) == "module_entry_size_limit"
		and (ts_mod1 - ts_mod0) < 50
	)

	var tobs0: int = Time.get_ticks_msec()
	var att_obs_dag: Dictionary = oa.attach_obstacle(plain_obj_id, "object", "manual", 64.0, false, false, dag24)
	var tobs1: int = Time.get_ticks_msec()
	var val_obs_dag: Dictionary = oa.validate_obstacle_state({"role": "wall", "shape_mode": "manual", "shape": {"uid": "a".repeat(64), "paths": dag24}})
	var tobs2: int = Time.get_ticks_msec()
	var dig_obs_dag: String = oa.compute_shape_digest({"paths": dag24})
	var tobs3: int = Time.get_ticks_msec()
	r8["obstacle_dag_guards_ok"] = (
		not bool(att_obs_dag.get("ok", true))
		and str(att_obs_dag.get("reason", "")) == "invalid_obstacle_state"
		and (tobs1 - tobs0) < 50
		and not bool(val_obs_dag.get("ok", true))
		and (tobs2 - tobs1) < 50
		and dig_obs_dag.is_empty()
		and (tobs3 - tobs2) < 50
	)

	var wb_comp = sdk.create_world_builder(sdk.create_session(MockHost.new(), {}), 150.0)
	wb_comp.get_logger().set_emit_to_engine(false)
	var comp_eid: String = wb_comp.add_object_sprite("dag_comp", "DagComp", Vector2(100, 100), Vector2(64, 64), "")
	var bytes_before: int = var_to_bytes(wb_comp.get_world()).size()
	var comp_cnt_before: int = (wb_comp.get_entity(comp_eid)["components"] as Array).size()
	var tw0: int = Time.get_ticks_msec()
	var wb_attach_res: bool = wb_comp.attach_component(comp_eid, "res://modules/follow/comp_follow.gd", _make_dag(24), false, false)
	var tw1: int = Time.get_ticks_msec()
	var wb_parked_res: bool = wb_comp.attach_parked_component(comp_eid, "res://modules/follow/comp_follow.gd", _make_dag(24), true)
	var tw2: int = Time.get_ticks_msec()
	var adp_attach_res: Dictionary = adapter.append_entity_component(wb_comp.get_entity(comp_eid), "res://modules/follow/comp_follow.gd", _make_dag(24), false, false)
	var tw3: int = Time.get_ticks_msec()
	var bytes_after: int = var_to_bytes(wb_comp.get_world()).size()
	var comp_cnt_after: int = (wb_comp.get_entity(comp_eid)["components"] as Array).size()
	var d26_ok: bool = wb_comp.attach_component(comp_eid, "res://modules/follow/comp_follow.gd", _make_deep_dict(26), false, false)
	var d27_rejected: bool = not wb_comp.attach_component(comp_eid, "res://modules/follow/comp_follow.gd", _make_deep_dict(27), false, false)
	r8["component_dag_and_depth_ok"] = (
		not wb_attach_res and (tw1 - tw0) < 50
		and not wb_parked_res and (tw2 - tw1) < 50
		and not bool(adp_attach_res.get("ok", true))
		and str(adp_attach_res.get("reason", "")) == "component_state_size_limit"
		and (tw3 - tw2) < 50
		and bytes_after == bytes_before
		and comp_cnt_after == comp_cnt_before
		and d26_ok
		and d27_rejected
	)

	var bom_only_reg: Dictionary = lib_el.register_entries("ns_bom_only", [
		{"id": "\ufeff   ", "name": "\ufeff   ", "vision_radius": 120.0, "create_preset": true}
	], lib_host, lib_sess, true)
	var warned_bom_only: Array = bom_only_reg.get("warned_presets", []) as Array
	var perm_nul: Dictionary = adapter.make_permission_state("  \ufeffp1,p2 ", [null, "p1", "\ufeffp2", "  \ufeffp3"], false, true)
	var writer_r8 = sdk.create_entity_library_writer()
	r8["minor_polish_ok"] = (
		not warned_bom_only.is_empty()
		and str((warned_bom_only[0] as Dictionary).get("entry", "")) == "unnamed_preset"
		and validation_utils.strip_nul("p1") == "p1"
		and str(perm_nul.get("owners_csv", "")) == "p1,p2"
		and Array(perm_nul.get("owner_player_ids", PackedStringArray())) == ["p1", "p2", "p3"]
		and writer_r8._is_valid_asset_ref("asset://" + "a".repeat(64) + ".png")
		and not writer_r8._is_valid_asset_ref("asset://" + "a".repeat(64) + ".PNG")
	)

	# Iter 9 Regression: sanitize_module_value with cyclic/DAG/Object/scalar Dictionary keys
	var cyc_k := {}
	var cyc_key_dict := {}
	cyc_key_dict[cyc_k] = 1
	cyc_k["self"] = cyc_k
	var self_key_dict := {}
	self_key_dict[self_key_dict] = 1
	var dk18 := {}
	var dag18_key_dict := {}
	dag18_key_dict[dk18] = 1
	dk18["l"] = dag18["l"]
	dk18["r"] = dag18["r"]
	var dk24 := {}
	var dag24_key_dict := {}
	dag24_key_dict[dk24] = 1
	dk24["l"] = dag24["l"]
	dk24["r"] = dag24["r"]
	var dk15 := {}
	var dag15_key_dict := {}
	dag15_key_dict[dk15] = 1
	dk15["l"] = dag15["l"]
	dk15["r"] = dag15["r"]
	var obj_key := RefCounted.new()
	var scalar_and_obj_keys := {}
	scalar_and_obj_keys[42] = "i"
	scalar_and_obj_keys[true] = "b"
	scalar_and_obj_keys[&"sn"] = "sn"
	scalar_and_obj_keys[NodePath("np")] = "np"
	scalar_and_obj_keys[null] = "nil"
	scalar_and_obj_keys[obj_key] = "obj"

	var tsk0: int = Time.get_ticks_msec()
	var san_cyc_k: Variant = adapter.sanitize_module_value(cyc_key_dict)
	var tsk1: int = Time.get_ticks_msec()
	var san_self_k: Variant = adapter.sanitize_module_value(self_key_dict)
	var tsk2: int = Time.get_ticks_msec()
	var san_d18_k: Variant = adapter.sanitize_module_value(dag18_key_dict)
	var tsk3: int = Time.get_ticks_msec()
	var san_d24_k: Variant = adapter.sanitize_module_value(dag24_key_dict)
	var tsk4: int = Time.get_ticks_msec()
	var san_d15_k: Variant = adapter.sanitize_module_value(dag15_key_dict)
	var tsk5: int = Time.get_ticks_msec()
	var san_scalar_obj: Variant = adapter.sanitize_module_value(scalar_and_obj_keys)
	r8["sanitize_non_string_keys_ok"] = (
		san_cyc_k is Dictionary and (san_cyc_k as Dictionary).size() == 1 and (tsk1 - tsk0) < 150
		and san_self_k is Dictionary and (san_self_k as Dictionary).is_empty() and (tsk2 - tsk1) < 150
		and san_d18_k is Dictionary and (san_d18_k as Dictionary).is_empty() and (tsk3 - tsk2) < 150
		and san_d24_k is Dictionary and (san_d24_k as Dictionary).is_empty() and (tsk4 - tsk3) < 150
		and san_d15_k is Dictionary and (san_d15_k as Dictionary).is_empty() and (tsk5 - tsk4) < 150
		and san_scalar_obj is Dictionary
		and (san_scalar_obj as Dictionary).get("42", "") == "i"
		and (san_scalar_obj as Dictionary).get("true", "") == "b"
		and (san_scalar_obj as Dictionary).get("sn", "") == "sn"
		and (san_scalar_obj as Dictionary).get("np", "") == "np"
		and (san_scalar_obj as Dictionary).get("<null>", "") == "nil"
		and (san_scalar_obj as Dictionary).size() == 5
	)
	results["r8_bounds_and_dag"] = r8

	# Iter 8 Regression (e): asset_publisher.prevalidate_local_refs multi-item WorkerThreadPool batch
	var ap_batch := {}
	var r8_ap_dir: String = OS.get_user_data_dir().path_join("r8_ap_batch")
	DirAccess.make_dir_recursive_absolute(r8_ap_dir)
	var pf_ap := FileAccess.open(r8_ap_dir.path_join("pack.json"), FileAccess.WRITE)
	pf_ap.store_string('{"id":"r8_batch","title":"R8 Batch"}')
	pf_ap.close()
	for img_i: int in range(4):
		var im := Image.create(4 + img_i, 4 + img_i, false, Image.FORMAT_RGBA8)
		im.fill(Color(0.2 * float(img_i + 1), 0.5, 0.8, 1.0))
		var f_img := FileAccess.open(r8_ap_dir.path_join("ok_%d.png" % img_i), FileAccess.WRITE)
		f_img.store_buffer(im.save_png_to_buffer())
		f_img.close()
	var f_bad_png := FileAccess.open(r8_ap_dir.path_join("bad.png"), FileAccess.WRITE)
	f_bad_png.store_buffer(PackedByteArray([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 1, 2, 3]))
	f_bad_png.close()

	var pkg_r8 = sdk.create_package_source()
	var pkg_r8_open: Dictionary = pkg_r8.open_package(r8_ap_dir.path_join("pack.json"), "pack.json", ["id"])
	var amap_r8_var: Variant = JSON.parse_string('{"ref_ok0":{"kind":"local","resolved_path_or_url":null,"rel_path":"ok_0.png","ext":"png","exists":null,"unsafe":"false"},"ref_ok1":{"kind":"local","resolved_path_or_url":"ok_1.png","ext":"png"},"ref_ok2":{"kind":"local","rel_path":"ok_2.png","ext":"png"},"ref_ok3":{"kind":"local","rel_path":"ok_3.png","ext":"png"},"ref_missing":{"kind":"local","rel_path":"missing.png","ext":"png"},"ref_exists_false":{"kind":"local","resolved_path_or_url":null,"rel_path":"ok_1.png","ext":"png","exists":"false"},"ref_unsafe_true":{"kind":"local","rel_path":"ok_2.png","ext":"png","unsafe":"true"},"ref_bad_png":{"kind":"local","rel_path":"bad.png","ext":"png"}}')
	var amap_r8: Dictionary = amap_r8_var as Dictionary if amap_r8_var is Dictionary else {}
	var host_ap := MockHost.new()
	host_ap.root = OS.get_user_data_dir().path_join("r8_ap_host_root")
	host_ap.destination = host_ap.root.path_join("sessions/r8_" + "d".repeat(32))
	DirAccess.make_dir_recursive_absolute(host_ap.destination)
	var sess_r8 = sdk.create_session(host_ap, {"skip_missing_assets": false})
	sess_r8.get_logger().set_emit_to_engine(false)
	var pub_r8 = sdk.create_asset_publisher()
	var store_r8 := MockAssetStore.new()
	pub_r8.set_shared_asset_store(store_r8, true)
	pub_r8.prevalidate_local_refs([null, 42, "", "ref_ok0", "ref_ok1", "ref_ok2", "ref_ok3", "ref_missing", "ref_exists_false", "ref_unsafe_true", "ref_bad_png", "ref_ok0"], amap_r8, pkg_r8, sess_r8)
	var prep_count_multi: int = pub_r8._prep_cache.size()
	var cpu_cnt: int = OS.get_processor_count()
	var res_ok0: Dictionary = pub_r8.resolve_sprite_ref("ref_ok0", amap_r8["ref_ok0"] as Dictionary, pkg_r8, host_ap, sess_r8, {"skip_missing_assets": false})
	var res_ok1: Dictionary = pub_r8.resolve_sprite_ref("ref_ok1", amap_r8["ref_ok1"] as Dictionary, pkg_r8, host_ap, sess_r8, {"skip_missing_assets": false})
	var res_ok2: Dictionary = pub_r8.resolve_sprite_ref("ref_ok2", amap_r8["ref_ok2"] as Dictionary, pkg_r8, host_ap, sess_r8, {"skip_missing_assets": false})
	var res_ok3: Dictionary = pub_r8.resolve_sprite_ref("ref_ok3", amap_r8["ref_ok3"] as Dictionary, pkg_r8, host_ap, sess_r8, {"skip_missing_assets": false})
	var res_missing: Dictionary = pub_r8.resolve_sprite_ref("ref_missing", amap_r8["ref_missing"] as Dictionary, pkg_r8, host_ap, sess_r8, {"skip_missing_assets": false})
	var res_exists_false: Dictionary = pub_r8.resolve_sprite_ref("ref_exists_false", amap_r8["ref_exists_false"] as Dictionary, pkg_r8, host_ap, sess_r8, {"skip_missing_assets": false})
	var res_unsafe_true: Dictionary = pub_r8.resolve_sprite_ref("ref_unsafe_true", amap_r8["ref_unsafe_true"] as Dictionary, pkg_r8, host_ap, sess_r8, {"skip_missing_assets": false})
	var res_bad_png: Dictionary = pub_r8.resolve_sprite_ref("ref_bad_png", amap_r8["ref_bad_png"] as Dictionary, pkg_r8, host_ap, sess_r8, {"skip_missing_assets": false})
	pub_r8.prevalidate_local_refs([null, "ref_ok0", "ref_ok1"], amap_r8, pkg_r8, null)
	pub_r8.prevalidate_local_refs(["ref_ok0", "ref_ok1"], amap_r8, null, sess_r8)
	pkg_r8.close()

	ap_batch["pkg_open_ok"] = bool(pkg_r8_open.get("ok", false))
	ap_batch["prep_cache_ok"] = (prep_count_multi == 5) if cpu_cnt > 1 else true
	ap_batch["ok_refs_published"] = (
		bool(res_ok0.get("ok", false)) and str(res_ok0.get("status", "")) == "local_published"
		and str(res_ok0.get("sprite_path", "")).begins_with("asset://") and str(res_ok0.get("sprite_path", "")).ends_with(".png")
		and bool(res_ok1.get("ok", false)) and str(res_ok1.get("status", "")) == "local_published"
		and str(res_ok1.get("sprite_path", "")).begins_with("asset://") and str(res_ok1.get("sprite_path", "")).ends_with(".png")
		and bool(res_ok2.get("ok", false)) and str(res_ok2.get("status", "")) == "local_published"
		and str(res_ok2.get("sprite_path", "")).begins_with("asset://") and str(res_ok2.get("sprite_path", "")).ends_with(".png")
		and bool(res_ok3.get("ok", false)) and str(res_ok3.get("status", "")) == "local_published"
		and str(res_ok3.get("sprite_path", "")).begins_with("asset://") and str(res_ok3.get("sprite_path", "")).ends_with(".png")
	)
	ap_batch["failure_reasons_ok"] = (
		not bool(res_missing.get("ok", true)) and str(res_missing.get("reason", "")) == "file_not_found:missing.png"
		and not bool(res_exists_false.get("ok", true)) and str(res_exists_false.get("reason", "")) == "missing_asset:ref_exists_false"
		and not bool(res_unsafe_true.get("ok", true)) and str(res_unsafe_true.get("reason", "")) == "unsafe_asset_ref:ref_unsafe_true"
		and not bool(res_bad_png.get("ok", true)) and str(res_bad_png.get("reason", "")) == "truncated_png"
	)
	results["r8_asset_publisher_batch"] = ap_batch

	# Iter 10 Regression: (1) sibling _safe_clone_node + d.keys() + null-cast guards,
	# (2) bucketed two-tier memo against height-1/2/3+ ring-flush & same-size traps,
	# (3) set_module_state & append_entity_component DAG preservation + caller isolation
	var r10 := {}
	var st_bus = (load("res://shared/sdk/fu_sdk/logging/log_bus.gd") as Script).new()
	st_bus.set_emit_to_engine(false)
	var st_reg = (load("res://shared/sdk/fu_sdk/plugins/module_registry.gd") as Script).new()
	var st_el = (load("res://shared/sdk/fu_sdk/plugins/feature_entity_library.gd") as Script).new()
	var st_oa = (load("res://shared/sdk/fu_sdk/plugins/feature_obstacle_authoring.gd") as Script).new()
	var sess_noadp = sdk.ImportSession.new(null, {})

	var t_sib0: int = Time.get_ticks_msec()
	var sib_bus_c: Dictionary = bus.info("s", "cyc", cyc_key_dict)
	var sib_bus_cw: Dictionary = bus.warn("s", "cyc_w", cyc_key_dict)
	var sib_bus_d15: Dictionary = bus.info("s", "d15", dag15_key_dict)
	var sib_st_bus_c: Dictionary = st_bus.info("s", "cyc_st", cyc_key_dict)
	var sib_st_bus_d15: Dictionary = st_bus.info("s", "d15_st", dag15_key_dict)
	var sib_reg_c: bool = reg.probe_feature_manager(cyc_key_dict)
	var sib_reg_d15: bool = reg.probe_feature_manager(dag15_key_dict)
	var sib_st_reg_c: bool = st_reg.probe_feature_manager(cyc_key_dict)
	var sib_el_c: Dictionary = b.entity_library().build_template_data("cu", "CU", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", cyc_key_dict)
	var sib_el_d15: Dictionary = b.entity_library().build_template_data("d15u", "D15U", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", dag15_key_dict)
	var sib_st_el_c: Dictionary = st_el.build_template_data("cu2", "CU2", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", cyc_key_dict)
	var sib_oa_c: Dictionary = b.obstacle_authoring().make_obstacle_state("object", "manual", 64.0, cyc_key_dict, cyc_key_dict)
	var sib_oa_d15: Dictionary = b.obstacle_authoring().make_obstacle_state("object", "manual", 64.0, dag15_key_dict, dag15_key_dict)
	var sib_st_oa_c: Dictionary = st_oa.make_obstacle_state("object", "manual", 64.0, cyc_key_dict, cyc_key_dict)
	var sib_san_c: Dictionary = sess_core.sanitize_options(cyc_key_dict)
	var sib_san_d15: Dictionary = sess_core.sanitize_options(dag15_key_dict)
	var sib_ok_c: Dictionary = sess_core.ok_inspect("", cyc_key_dict)
	var sib_ok_d15: Dictionary = sess_core.ok_inspect("", dag15_key_dict)
	var sib_noadp_san: Dictionary = sess_noadp.sanitize_options(cyc_key_dict)
	var sib_noadp_ok: Dictionary = sess_noadp.ok_inspect("", cyc_key_dict)
	var sib_adp_ok_c: Dictionary = adapter.build_inspect_ok("", cyc_key_dict)
	var sib_adp_ok_d15: Dictionary = adapter.build_inspect_ok("", dag15_key_dict)
	var sib_el_host := MockHost.new()
	sib_el_host.root = "user://mock_sib_el"
	sib_el_host.destination = "user://mock_sib_el/sessions/demo_" + "e".repeat(32)
	var sib_el_sess = sdk.create_session(sib_el_host, {})
	sib_el_sess.get_logger().set_emit_to_engine(false)
	var sib_el_wb = sdk.create_world_builder(sib_el_sess, 150.0)
	var sib_el_store := MockAssetStore.new()
	var sib_el_sdk = sib_el_wb.entity_library()
	sib_el_sdk.get_writer().set_shared_asset_store(sib_el_store, true)
	var sib_reg_entries_c: Dictionary = sib_el_sdk.register_entries("ns_sib_c", [cyc_key_dict], sib_el_host, sib_el_sess, true)
	var sib_reg_presets_c: Dictionary = sib_el_sdk.register_presets("ns_sib_c", [cyc_key_dict], sib_el_host, sib_el_sess)
	var sib_elapsed: int = Time.get_ticks_msec() - t_sib0
	r10["sib_elapsed_ms"] = sib_elapsed
	var sib_tctx_adp_cln = dag_cloner.DagTravCtx.new()
	var _sib_ctx_adp_cln: Variant = dag_cloner.safe_clone_node(dag15_key_dict, 0, [], sib_tctx_adp_cln)
	var sib_tctx_adp_san = dag_cloner.DagTravCtx.new()
	var _sib_ctx_adp_san: Variant = adapter._sanitize_module_node(dag15_key_dict, 0, [], sib_tctx_adp_san)
	var sib_tctx_bus = dag_cloner.DagTravCtx.new()
	sib_tctx_bus.max_bytes = 4 * 1024 * 1024
	var _sib_ctx_bus: Variant = dag_cloner.safe_clone_node(dag15_key_dict, 0, [], sib_tctx_bus)
	var sib_tctx_reg = dag_cloner.DagTravCtx.new()
	var _sib_ctx_reg: Variant = dag_cloner.safe_clone_node(dag15_key_dict, 0, [], sib_tctx_reg)
	var sib_tctx_el = dag_cloner.DagTravCtx.new()
	var _sib_ctx_el: Variant = dag_cloner.safe_clone_node(dag15_key_dict, 0, [], sib_tctx_el)
	var sib_tctx_oa = dag_cloner.DagTravCtx.new()
	var _sib_ctx_oa: Variant = dag_cloner.safe_clone_node(dag15_key_dict, 0, [], sib_tctx_oa)
	var sib_dag15_tctx_ok: bool = (
		not sib_tctx_adp_cln.aborted and sib_tctx_adp_cln.nodes < 20000 and sib_tctx_adp_cln.shared_unfold <= 8192
		and not sib_tctx_adp_san.aborted and sib_tctx_adp_san.nodes < 20000 and sib_tctx_adp_san.shared_unfold <= 8192
		and not sib_tctx_bus.aborted and sib_tctx_bus.nodes < 20000 and sib_tctx_bus.shared_unfold <= 8192
		and not sib_tctx_reg.aborted and sib_tctx_reg.nodes < 20000 and sib_tctx_reg.shared_unfold <= 8192
		and not sib_tctx_el.aborted and sib_tctx_el.nodes < 20000 and sib_tctx_el.shared_unfold <= 8192
		and not sib_tctx_oa.aborted and sib_tctx_oa.nodes < 20000 and sib_tctx_oa.shared_unfold <= 8192
	)
	r10["sib_dag15_tctx_ok"] = sib_dag15_tctx_ok
	r10["sib_dag15_tctx_debug"] = {
		"adp_cln": [sib_tctx_adp_cln.aborted, sib_tctx_adp_cln.nodes, sib_tctx_adp_cln.shared_unfold],
		"adp_san": [sib_tctx_adp_san.aborted, sib_tctx_adp_san.nodes, sib_tctx_adp_san.shared_unfold],
		"bus": [sib_tctx_bus.aborted, sib_tctx_bus.nodes, sib_tctx_bus.shared_unfold],
		"reg": [sib_tctx_reg.aborted, sib_tctx_reg.nodes, sib_tctx_reg.shared_unfold],
		"el": [sib_tctx_el.aborted, sib_tctx_el.nodes, sib_tctx_el.shared_unfold],
		"oa": [sib_tctx_oa.aborted, sib_tctx_oa.nodes, sib_tctx_oa.shared_unfold],
	}
	r10["sibling_keys_and_casts_ok"] = (
		not sib_bus_c.is_empty()
		and not sib_bus_cw.is_empty()
		and not sib_bus_d15.is_empty()
		and not sib_st_bus_c.is_empty()
		and not sib_st_bus_d15.is_empty()
		and not sib_reg_c and not sib_reg_d15 and not sib_st_reg_c
		and sib_el_c.has("components") and sib_el_d15.has("components") and sib_st_el_c.has("components")
		and bool(sib_reg_entries_c.get("ok", false)) and bool(sib_reg_presets_c.get("ok", false))
		and not sib_oa_c.is_empty() and not sib_oa_d15.is_empty() and not sib_st_oa_c.is_empty()
		and sib_san_c.is_empty() and sib_san_d15.is_empty() and sib_noadp_san.is_empty()
		and bool(sib_ok_c.get("ok", false)) and bool(sib_ok_d15.get("ok", false))
		and bool(sib_noadp_ok.get("ok", false))
		and bool(sib_adp_ok_c.get("ok", false)) and bool(sib_adp_ok_d15.get("ok", false))
		and sib_elapsed < 500
		and sib_dag15_tctx_ok
	)

	var h12_dag24: Array = []
	for _hi12: int in range(12):
		h12_dag24.append(_make_dag(24, {}))

	# pattern_e: 12 x dag24 + depth-16 trap with 21 x {"a": [0..28]}
	var trap_e: Dictionary = {"leaf": 1}
	for _te: int in range(16):
		var j21_e: Array = []
		for _je: int in range(21):
			var arr29: Array = []
			for ae: int in range(29):
				arr29.append(ae)
			j21_e.append({"a": arr29})
		trap_e = {"l": trap_e, "j": j21_e, "r": trap_e}
	var p_pattern_e := {"h": h12_dag24, "trap": trap_e}

	# pattern_d_v2: 12 x dag24 + depth-16 trap with 21 x {"w": size_30_dict}
	var trap_dv2: Dictionary = {"leaf": 1}
	for _tdv2: int in range(16):
		var j21_dv2: Array = []
		for _jdv2: int in range(21):
			var s30 := {}
			for k30: int in range(30):
				s30["k%d" % k30] = k30
			j21_dv2.append({"w": s30})
		trap_dv2 = {"l": trap_dv2, "j": j21_dv2, "r": trap_dv2}
	var p_pattern_dv2 := {"h": h12_dag24, "trap": trap_dv2}

	# pat_h2_31: 32 x dag24 + depth-16 trap with 33 x {"_n": {"x": 1}, "k0..k27"}
	var trap_h2: Dictionary = {"leaf": 1}
	for _th2: int in range(16):
		var j33_h2: Array = []
		for _jh2: int in range(33):
			var h2d := {"_n": {"x": 1}}
			for kh2: int in range(28):
				h2d["k%d" % kh2] = kh2
			j33_h2.append(h2d)
		trap_h2 = {"l": trap_h2, "j": j33_h2, "r": trap_h2}
	var p_pat_h2_31 := {"h": h32_dag24, "trap": trap_h2}

	# ring_thrash_16: 12 x dag24 + depth-16 binary array DAG [N_{k-1}, trap_1..trap_20, N_{k-1}]
	var trap_rt: Array = [1]
	for _trt: int in range(16):
		var row_rt: Array = [trap_rt]
		for _jrt: int in range(20):
			var h2rt := {"_n": {"x": 1}}
			for krt: int in range(28):
				h2rt["k%d" % krt] = krt
			row_rt.append(h2rt)
		row_rt.append(trap_rt)
		trap_rt = row_rt
	var p_ring_thrash_16 := {"h": h12_dag24, "trap": trap_rt}

	# pat_h3_31: 32 x dag24 + depth-16 trap with 33 x {"_n": {"_m": {"x": 1}}, "k0..k26"}
	var trap_h3: Dictionary = {"leaf": 1}
	for _th3: int in range(16):
		var j33_h3: Array = []
		for _jh3: int in range(33):
			var h3d := {"_n": {"_m": {"x": 1}}}
			for kh3: int in range(27):
				h3d["k%d" % kh3] = kh3
			j33_h3.append(h3d)
		trap_h3 = {"l": trap_h3, "j": j33_h3, "r": trap_h3}
	var p_pat_h3_31 := {"h": h32_dag24, "trap": trap_h3}

	# wrapper_same_size_h3: 20 x size-3 dag24 directly on root (same live frame) + size-3 depth-20 trap + 25 x size-3 ln=17, h=6 wrapped junks
	var p_wrapper_same_size_h3 := {}
	for _hs3: int in range(20):
		var nd3: Dictionary = {"leaf": 1}
		for _lvl3: int in range(24):
			nd3 = {"l": nd3, "r": nd3, "p": 0}
		p_wrapper_same_size_h3["h%d" % _hs3] = nd3
	var trap_sz3: Dictionary = {"leaf": 1}
	for _ts3: int in range(20):
		var j25_sz3: Array = []
		for _js3: int in range(25):
			var w0 := {"_m": {"x": 1}, "a": 1, "b": 2}
			var w1 := {"_n": w0, "c": 3, "d": 4}
			var w2 := {"_o": w1, "e": 5, "f": 6}
			var w3 := {"_p": w2, "g": 7, "h": 8}
			var w4 := {"_w": w3, "i": 9, "j": 10}
			j25_sz3.append(w4)
		trap_sz3 = {"l": trap_sz3, "j": j25_sz3, "r": trap_sz3}
	p_wrapper_same_size_h3["trap"] = trap_sz3

	var ctx_pe_v := {"nodes": 0}
	var t_pe0: int = Time.get_ticks_msec()
	var pe_v: bool = adapter.is_valid_state_data(p_pattern_e, 3, [], 32, ctx_pe_v)
	var t_pe_v: int = Time.get_ticks_msec() - t_pe0
	var ctx_pe_b := {"nodes": 0}
	var t_pe1: int = Time.get_ticks_msec()
	var pe_b: int = adapter.bounded_variant_size_estimate(p_pattern_e, 3, [], 0x7fffffffffffffff, 32, ctx_pe_b)
	var t_pe_b: int = Time.get_ticks_msec() - t_pe1

	var ctx_pd2_v := {"nodes": 0}
	var t_pd20: int = Time.get_ticks_msec()
	var pd2_v: bool = adapter.is_valid_state_data(p_pattern_dv2, 3, [], 32, ctx_pd2_v)
	var t_pd2_v: int = Time.get_ticks_msec() - t_pd20
	var ctx_pd2_b := {"nodes": 0}
	var t_pd21: int = Time.get_ticks_msec()
	var pd2_b: int = adapter.bounded_variant_size_estimate(p_pattern_dv2, 3, [], 0x7fffffffffffffff, 32, ctx_pd2_b)
	var t_pd2_b: int = Time.get_ticks_msec() - t_pd21

	var ctx_ph2_v := {"nodes": 0}
	var t_ph20: int = Time.get_ticks_msec()
	var ph2_v: bool = adapter.is_valid_state_data(p_pat_h2_31, 3, [], 32, ctx_ph2_v)
	var t_ph2_v: int = Time.get_ticks_msec() - t_ph20
	var ctx_ph2_b := {"nodes": 0}
	var t_ph21: int = Time.get_ticks_msec()
	var ph2_b: int = adapter.bounded_variant_size_estimate(p_pat_h2_31, 3, [], 0x7fffffffffffffff, 32, ctx_ph2_b)
	var t_ph2_b: int = Time.get_ticks_msec() - t_ph21

	var ctx_rt_v := {"nodes": 0}
	var t_rt0: int = Time.get_ticks_msec()
	var rt_v: bool = adapter.is_valid_state_data(p_ring_thrash_16, 3, [], 32, ctx_rt_v)
	var t_rt_v: int = Time.get_ticks_msec() - t_rt0
	var ctx_rt_b := {"nodes": 0}
	var t_rt1: int = Time.get_ticks_msec()
	var rt_b: int = adapter.bounded_variant_size_estimate(p_ring_thrash_16, 3, [], 0x7fffffffffffffff, 32, ctx_rt_b)
	var t_rt_b: int = Time.get_ticks_msec() - t_rt1

	var ctx_ph3_v := {"nodes": 0}
	var t_ph30: int = Time.get_ticks_msec()
	var ph3_v: bool = adapter.is_valid_state_data(p_pat_h3_31, 3, [], 32, ctx_ph3_v)
	var t_ph3_v: int = Time.get_ticks_msec() - t_ph30
	var ctx_ph3_b := {"nodes": 0}
	var t_ph31: int = Time.get_ticks_msec()
	var ph3_b: int = adapter.bounded_variant_size_estimate(p_pat_h3_31, 3, [], 0x7fffffffffffffff, 32, ctx_ph3_b)
	var t_ph3_b: int = Time.get_ticks_msec() - t_ph31

	var ctx_ws3_v := {"nodes": 0}
	var t_ws30: int = Time.get_ticks_msec()
	var ws3_v: bool = adapter.is_valid_state_data(p_wrapper_same_size_h3, 3, [], 32, ctx_ws3_v)
	var t_ws3_v: int = Time.get_ticks_msec() - t_ws30
	var ctx_ws3_b := {"nodes": 0}
	var t_ws31: int = Time.get_ticks_msec()
	var ws3_b: int = adapter.bounded_variant_size_estimate(p_wrapper_same_size_h3, 3, [], 0x7fffffffffffffff, 32, ctx_ws3_b)
	var t_ws3_b: int = Time.get_ticks_msec() - t_ws31

	r10["trap_debug"] = {
		"pe": [pe_v, pe_b, t_pe_v, t_pe_b, int(ctx_pe_v.get("nodes", 0)), int(ctx_pe_b.get("nodes", 0))],
		"pd2": [pd2_v, pd2_b, t_pd2_v, t_pd2_b, int(ctx_pd2_v.get("nodes", 0)), int(ctx_pd2_b.get("nodes", 0))],
		"ph2": [ph2_v, ph2_b, t_ph2_v, t_ph2_b, int(ctx_ph2_v.get("nodes", 0)), int(ctx_ph2_b.get("nodes", 0))],
		"rt": [rt_v, rt_b, t_rt_v, t_rt_b, int(ctx_rt_v.get("nodes", 0)), int(ctx_rt_b.get("nodes", 0))],
		"ph3": [ph3_v, ph3_b, t_ph3_v, t_ph3_b, int(ctx_ph3_v.get("nodes", 0)), int(ctx_ph3_b.get("nodes", 0))],
		"ws3": [ws3_v, ws3_b, t_ws3_v, t_ws3_b, int(ctx_ws3_v.get("nodes", 0)), int(ctx_ws3_b.get("nodes", 0))],
	}
	r10["memo_traps_ok"] = (
		pe_v and pe_b > 0 and t_pe_v < 200 and t_pe_b < 200 and int(ctx_pe_v.get("nodes", 0)) < 100000 and int(ctx_pe_b.get("nodes", 0)) < 100000
		and pd2_v and pd2_b > 0 and t_pd2_v < 200 and t_pd2_b < 200 and int(ctx_pd2_v.get("nodes", 0)) < 100000 and int(ctx_pd2_b.get("nodes", 0)) < 100000
		and ph2_v and ph2_b > 0 and t_ph2_v < 200 and t_ph2_b < 200 and int(ctx_ph2_v.get("nodes", 0)) < 100000 and int(ctx_ph2_b.get("nodes", 0)) < 100000
		and rt_v and rt_b > 0 and t_rt_v < 200 and t_rt_b < 200 and int(ctx_rt_v.get("nodes", 0)) < 100000 and int(ctx_rt_b.get("nodes", 0)) < 100000
		and ph3_v and ph3_b > 0 and t_ph3_v < 200 and t_ph3_b < 200 and int(ctx_ph3_v.get("nodes", 0)) < 100000 and int(ctx_ph3_b.get("nodes", 0)) < 100000
		and ws3_v and ws3_b > 0 and t_ws3_v < 200 and t_ws3_b < 200 and int(ctx_ws3_v.get("nodes", 0)) < 100000 and int(ctx_ws3_b.get("nodes", 0)) < 100000
	)

	# set_module_state & append_entity_component DAG preservation + caller mutation isolation
	var wb_r10 = sdk.create_world_builder(sdk.create_session(MockHost.new(), {}), 150.0)
	wb_r10.get_logger().set_emit_to_engine(false)
	var world_r10: Dictionary = wb_r10.get_world()
	var arr_dag18: Array = _make_arr_dag(18, null)
	var arr_dag19: Array = _make_arr_dag(19, null)
	var mod_s18 := {"d": arr_dag18}
	var mod_s19 := {"d": arr_dag19}

	var t_m18_0: int = Time.get_ticks_msec()
	var res_m18: Dictionary = adapter.set_module_state(world_r10, "arr18", 1, mod_s18)
	var t_m18: int = Time.get_ticks_msec() - t_m18_0

	var world_r10_19: Dictionary = sdk.create_world_builder(sdk.create_session(MockHost.new(), {}), 150.0).get_world()
	var t_m19_0: int = Time.get_ticks_msec()
	var res_m19: Dictionary = adapter.set_module_state(world_r10_19, "arr19", 1, mod_s19)
	var t_m19: int = Time.get_ticks_msec() - t_m19_0

	var t_m2_0: int = Time.get_ticks_msec()
	var res_m2: Dictionary = adapter.set_module_state(world_r10_19, "m2", 1, {"x": 1})
	var t_m2: int = Time.get_ticks_msec() - t_m2_0

	var t_m3_0: int = Time.get_ticks_msec()
	var can_fit_m3: bool = adapter.can_fit_module_state(world_r10_19, "m3", 1, {"b": 2})
	var t_m3: int = Time.get_ticks_msec() - t_m3_0

	# Mutate caller mod_s19 & verify stored module state is isolated
	(mod_s19["d"] as Array)[0] = "MUTATED"
	var stored_d19: Array = world_r10_19["modules"]["entries"]["arr19"]["state"]["d"] as Array
	var mod_isolated: bool = not (stored_d19[0] is String)

	# append_entity_component with arr_dag19 + caller isolation + NodePath bound check
	var ent_r10_id: String = wb_r10.add_object_sprite("r10_comp", "R10Comp", Vector2(100, 100), Vector2(64, 64), "")
	var ent_r10: Dictionary = wb_r10.get_entity(ent_r10_id)
	var comp_s19 := {"d": _make_arr_dag(19, null)}
	var t_comp0: int = Time.get_ticks_msec()
	var comp_res: Dictionary = adapter.append_entity_component(ent_r10, "res://modules/follow/comp_follow.gd", comp_s19, true, false)
	var t_comp: int = Time.get_ticks_msec() - t_comp0
	(comp_s19["d"] as Array)[0] = "MUTATED_COMP"
	var stored_comp_d19: Array = ent_r10["components"][2]["state"]["d"] as Array
	var comp_isolated: bool = not (stored_comp_d19[0] is String)

	var np_dict := {NodePath("a/b/c"): NodePath("/root/Node/SubNode")}
	var np_bounded: int = adapter.bounded_variant_size_estimate(np_dict, 0, [], adapter.MAX_MODULE_ENTRY_BYTES)
	var np_var_bytes: int = var_to_bytes(np_dict).size()

	r10["dag_module_and_component_ok"] = (
		bool(res_m18.get("ok", false)) and t_m18 < 200
		and bool(res_m19.get("ok", false)) and t_m19 < 200
		and bool(res_m2.get("ok", false)) and t_m2 < 50
		and can_fit_m3 and t_m3 < 50
		and mod_isolated
		and bool(comp_res.get("ok", false)) and t_comp < 200
		and comp_isolated
		and np_bounded >= np_var_bytes
	)
	results["r10_hardening"] = r10

	# Iter 11 Regression:
	# (1) depth == 32 empty-leaf DAG (wrap11 / wrap8 / wrap14) across all 5 cloning scripts
	# (2) pure depth-clipped DAG (dag33 / nested9_dag24) across all 5 cloning scripts + create_session
	# (3) can_fit_module_state on synthetic world = {} near max_world_bytes
	var r11 := {}
	var dag17_empty: Array = _make_arr_dag(17, {})
	var wrap11: Dictionary = _make_deep_dict(11, [dag17_empty, dag17_empty, dag17_empty])
	var wrap8: Dictionary = _make_deep_dict(8, [dag17_empty, dag17_empty, dag17_empty])
	var wrap14: Dictionary = _make_deep_dict(14, [dag17_empty, dag17_empty, dag17_empty])

	var w_r11 := {}
	var t_el_mod0: int = Time.get_ticks_msec()
	var el_mod_res: Dictionary = adapter.set_module_state(w_r11, "dc11", 1, wrap11)
	var t_el_mod: int = Time.get_ticks_msec() - t_el_mod0

	var ent_r11: Dictionary = wb_r10.get_entity(ent_r10_id)
	var t_el_comp0: int = Time.get_ticks_msec()
	var el_comp_res: Dictionary = adapter.append_entity_component(ent_r11, "res://modules/follow/comp_follow.gd", wrap8, true, false)
	var t_el_comp: int = Time.get_ticks_msec() - t_el_comp0

	var t_el_bus0: int = Time.get_ticks_msec()
	var el_bus_res: Dictionary = st_bus.info("s", "dc", wrap14)
	var t_el_bus: int = Time.get_ticks_msec() - t_el_bus0

	var t_el_reg0: int = Time.get_ticks_msec()
	var el_reg_res: bool = st_reg.probe_feature_manager(wrap14)
	var t_el_reg: int = Time.get_ticks_msec() - t_el_reg0

	var t_el_tmpl0: int = Time.get_ticks_msec()
	var el_tmpl_res: Dictionary = st_el.build_template_data("dc_u", "DCU", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", wrap14)
	var t_el_tmpl: int = Time.get_ticks_msec() - t_el_tmpl0

	var t_el_obs0: int = Time.get_ticks_msec()
	var el_obs_res: Dictionary = st_oa.make_obstacle_state("object", "manual", 64.0, wrap14, {})
	var t_el_obs: int = Time.get_ticks_msec() - t_el_obs0

	var el_obs_leaf_ok: bool = false
	var el_mod_st: Variant = w_r11.get("modules", {}).get("entries", {}).get("dc11", {}).get("state", {})
	var el_comp_st: Variant = ent_r11["components"][ent_r11["components"].size() - 1].get("state", {})
	if el_mod_st is Dictionary and not (el_mod_st as Dictionary).is_empty():
		var m_mod := _measure_depth_and_check_empty_32(el_mod_st)
		var m_cmp := _measure_depth_and_check_empty_32(el_comp_st)
		var m_tmpl := _measure_depth_and_check_empty_32(el_tmpl_res.get("components", {}))
		var m_obs := _measure_depth_and_check_empty_32(el_obs_res.get("shape", {}))
		el_obs_leaf_ok = (
			int(m_mod["max_depth"]) == 29 and not bool(m_mod["non_empty_at_32"])
			and int(m_cmp["max_depth"]) == 26 and not bool(m_cmp["non_empty_at_32"])
			and int(m_tmpl["max_depth"]) == 32 and not bool(m_tmpl["non_empty_at_32"])
			and int(m_obs["max_depth"]) == 32 and not bool(m_obs["non_empty_at_32"])
		)

	r11["empty_leaf_depth32_debug"] = {
		"mod": [bool(el_mod_res.get("ok", false)), t_el_mod],
		"comp": [bool(el_comp_res.get("ok", false)), t_el_comp],
		"bus": [not el_bus_res.is_empty(), t_el_bus],
		"reg": [not el_reg_res, t_el_reg],
		"el": [el_tmpl_res.has("components"), t_el_tmpl],
		"oa": [not el_obs_res.is_empty(), t_el_obs],
		"leaves_ok": el_obs_leaf_ok,
	}
	r11["empty_leaf_depth32_fast_ok"] = (
		bool(el_mod_res.get("ok", false)) and t_el_mod < 250
		and bool(el_comp_res.get("ok", false)) and t_el_comp < 250
		and not el_bus_res.is_empty() and t_el_bus < 100
		and not el_reg_res and t_el_reg < 100
		and el_tmpl_res.has("components") and t_el_tmpl < 100
		and not el_obs_res.is_empty() and t_el_obs < 100
		and el_obs_leaf_ok
	)

	# Byte-budget-aborting DAGs (16 MiB / 4 MiB cap): expected to abort cleanly to {}
	var r11_dag33: Dictionary = _make_dag(33, {})
	var nested9_dag24: Dictionary = _make_deep_dict(9, _make_dag(24, {}))
	var clipped_ok: bool = true
	var clipped_debug: Array = []
	for p_item: Dictionary in [r11_dag33, nested9_dag24]:
		var tc0: int = Time.get_ticks_msec()
		var cln_p: Variant = adapter._safe_clone_variant(p_item)
		var dt_cln: int = Time.get_ticks_msec() - tc0

		var ts0: int = Time.get_ticks_msec()
		var san_p: Variant = adapter.sanitize_module_value(p_item)
		var dt_san: int = Time.get_ticks_msec() - ts0

		var tb0: int = Time.get_ticks_msec()
		var bus_p: Dictionary = st_bus.info("s", "clip", p_item)
		var dt_bus: int = Time.get_ticks_msec() - tb0

		var tr0: int = Time.get_ticks_msec()
		var reg_p: bool = st_reg.probe_feature_manager(p_item)
		var dt_reg: int = Time.get_ticks_msec() - tr0

		var te0: int = Time.get_ticks_msec()
		var el_p: Dictionary = st_el.build_template_data("cp_u", "CPU", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", p_item)
		var dt_el: int = Time.get_ticks_msec() - te0

		var tre0: int = Time.get_ticks_msec()
		var re_p: Dictionary = sib_el_sdk.register_entries("ns_clip", [p_item], sib_el_host, sib_el_sess, true)
		var dt_re: int = Time.get_ticks_msec() - tre0

		var trp0: int = Time.get_ticks_msec()
		var rp_p: Dictionary = sib_el_sdk.register_presets("ns_clip", [p_item], sib_el_host, sib_el_sess)
		var dt_rp: int = Time.get_ticks_msec() - trp0

		var to0: int = Time.get_ticks_msec()
		var oa_p: Dictionary = st_oa.make_obstacle_state("object", "manual", 64.0, p_item, p_item)
		var dt_oa: int = Time.get_ticks_msec() - to0

		var tcs0: int = Time.get_ticks_msec()
		var cs_p = sdk.create_session(MockHost.new(), p_item)
		var dt_cs: int = Time.get_ticks_msec() - tcs0

		clipped_debug.append([dt_cln, dt_san, dt_bus, dt_reg, dt_el, dt_re, dt_rp, dt_oa, dt_cs])
		if (
			not (cln_p is Dictionary) or dt_cln >= 100
			or not (san_p is Dictionary) or dt_san >= 100
			or bus_p.is_empty() or dt_bus >= 100
			or reg_p or dt_reg >= 100
			or not el_p.has("components") or dt_el >= 100
			or not bool(re_p.get("ok", false)) or dt_re >= 100
			or not bool(rp_p.get("ok", false)) or dt_rp >= 100
			or oa_p.is_empty() or dt_oa >= 100
			or cs_p == null or not (cs_p.get_options() is Dictionary) or dt_cs >= 100
		):
			clipped_ok = false
	r11["clipped_dag_debug"] = clipped_debug
	r11["clipped_dag_fast_ok"] = clipped_ok
	var cln_d33_sem: Variant = adapter._safe_clone_variant(r11_dag33)
	var cln_n9_sem: Variant = adapter._safe_clone_variant(nested9_dag24)
	r11["clipped_truncation_semantics_ok"] = (
		not adapter.is_valid_state_data(r11_dag33, 0)
		and not adapter.is_valid_state_data(nested9_dag24, 0)
		and cln_d33_sem is Dictionary and adapter.is_valid_state_data(cln_d33_sem, 0)
		and cln_n9_sem is Dictionary and adapter.is_valid_state_data(cln_n9_sem, 0)
	)

	var pba_fit := PackedByteArray()
	pba_fit.resize(1000)
	var st_fit := {"p": pba_fit}
	var expected_fit_bytes: int = var_to_bytes({"modules": {"version": 2, "entries": {"m": {"version": 1, "state": st_fit}}}}).size()
	var empty_mods_world := {"modules": {"version": 2, "entries": {}}}
	r11["synthetic_can_fit_ok"] = (
		adapter.can_fit_module_state({}, "m", 1, st_fit, expected_fit_bytes)
		and not adapter.can_fit_module_state({}, "m", 1, st_fit, expected_fit_bytes - 1)
		and adapter.can_fit_module_state(empty_mods_world, "m", 1, st_fit, expected_fit_bytes)
		and not adapter.can_fit_module_state(empty_mods_world, "m", 1, st_fit, expected_fit_bytes - 1)
	)
	results["r11_hardening"] = r11

	# Iter 12 Regression (Groups A, B, C, D + Explorer 1 §5.2):
	var r12 := {}

	# Group A.1: arr99_5lvl_8ary_valid32 (20 live frames + 5-lvl 8-ary trap + 13 descending-ln junks)
	var base99: Array = []
	for b99_i: int in range(99):
		base99.append(b99_i)
	var h99_list: Array = []
	for f99_i: int in range(20):
		var cur_h99: Array = base99.duplicate()
		cur_h99[0] = f99_i
		for _lvl: int in range(5):
			var nxt_h99: Array = []
			for _c: int in range(32):
				nxt_h99.append(cur_h99)
			for _pad: int in range(67):
				nxt_h99.append(_pad)
			cur_h99 = nxt_h99
		h99_list.append(cur_h99)

	var trap99_lvls: Array = [base99.duplicate()]
	for t99_l: int in range(5):
		var prev_t99: Array = trap99_lvls[trap99_lvls.size() - 1] as Array
		var row99: Array = [prev_t99]
		for jm: int in range(13):
			var sub_len: int = 70 - jm
			var sub_arr: Array = []
			for si: int in range(sub_len):
				sub_arr.append(si)
			var j_arr: Array = [sub_arr]
			for jp: int in range(98):
				j_arr.append(jp)
			row99.append(j_arr)
		for _r7: int in range(7):
			row99.append(prev_t99)
		for _p78: int in range(78):
			row99.append(_p78)
		trap99_lvls.append(row99)

	var chain99_5lvl: Dictionary = {"h": h99_list[19], "n": trap99_lvls[5]}
	for fi: int in range(18, -1, -1):
		chain99_5lvl = {"h": h99_list[fi], "n": chain99_5lvl}

	var ctx_v99_0 := {"nodes": 0}
	var t_v99_0_start: int = Time.get_ticks_msec()
	var v99_0: bool = adapter.is_valid_state_data(chain99_5lvl, 0, [], 32, ctx_v99_0)
	var dt_v99_0: int = Time.get_ticks_msec() - t_v99_0_start

	var ctx_v99_3 := {"nodes": 0}
	var t_v99_3_start: int = Time.get_ticks_msec()
	var v99_3: bool = adapter.is_valid_state_data(chain99_5lvl, 3, [], 32, ctx_v99_3)
	var dt_v99_3: int = Time.get_ticks_msec() - t_v99_3_start

	var t_sm99_big0: int = Time.get_ticks_msec()
	var sm99_big_res: Dictionary = adapter.set_module_state({}, "m_trap99_big", 1, chain99_5lvl)
	var dt_sm99_big: int = Time.get_ticks_msec() - t_sm99_big0

	# < 16 MiB 20-live-frame variant for set_module_state & append_entity_component
	var h99_small_list: Array = []
	for fs_i: int in range(20):
		var s0: Array = base99.duplicate()
		s0[0] = fs_i
		var s1: Array = []
		for _c1: int in range(8):
			s1.append(s0)
		for _p1: int in range(91):
			s1.append(_p1)
		var s2: Array = []
		for _c2: int in range(8):
			s2.append(s1)
		for _p2: int in range(91):
			s2.append(_p2)
		h99_small_list.append(s2)

	var trap99_small: Array = base99.duplicate()
	for _tsl: int in range(4):
		var r_sm: Array = [trap99_small]
		for jm2: int in range(13):
			var sub_len2: int = 50 - jm2
			var sub2: Array = []
			for si2: int in range(sub_len2):
				sub2.append(si2)
			var j2: Array = [sub2]
			for jp2: int in range(98):
				j2.append(jp2)
			r_sm.append(j2)
		r_sm.append(trap99_small)
		for _p84: int in range(84):
			r_sm.append(_p84)
		trap99_small = r_sm

	var chain99_small: Dictionary = {"h": h99_small_list[19], "n": trap99_small}
	for fi_s: int in range(18, -1, -1):
		chain99_small = {"h": h99_small_list[fi_s], "n": chain99_small}

	var t_sm99_ok0: int = Time.get_ticks_msec()
	var sm99_ok_res: Dictionary = adapter.set_module_state({}, "m_trap99_ok", 1, chain99_small)
	var dt_sm99_ok: int = Time.get_ticks_msec() - t_sm99_ok0

	# Group A.2: chain99_d26 (append_entity_component 4-level trap at initial_depth = 6)
	var chain99_4lvl: Dictionary = {"h": h99_list[19], "n": trap99_lvls[4]}
	for fi_4: int in range(18, -1, -1):
		chain99_4lvl = {"h": h99_list[fi_4], "n": chain99_4lvl}
	var ent_r12_id: String = wb_r10.add_object_sprite("r12_comp", "R12Comp", Vector2(100, 100), Vector2(64, 64), "")
	var ent_r12: Dictionary = wb_r10.get_entity(ent_r12_id)
	var t_comp99_big0: int = Time.get_ticks_msec()
	var comp99_big_res: Dictionary = adapter.append_entity_component(ent_r12, "res://modules/follow/comp_follow.gd", chain99_4lvl, true, false)
	var dt_comp99_big: int = Time.get_ticks_msec() - t_comp99_big0

	var t_comp99_ok0: int = Time.get_ticks_msec()
	var comp99_ok_res: Dictionary = adapter.append_entity_component(ent_r12, "res://modules/follow/comp_follow.gd", chain99_small, true, false)
	var dt_comp99_ok: int = Time.get_ticks_msec() - t_comp99_ok0

	r12["arr99_debug"] = {
		"v0": [v99_0, int(ctx_v99_0.get("nodes", 0)), dt_v99_0],
		"v3": [v99_3, int(ctx_v99_3.get("nodes", 0)), dt_v99_3],
		"sm_big": [sm99_big_res.get("ok", false), sm99_big_res.get("reason", ""), dt_sm99_big],
		"sm_ok": [sm99_ok_res.get("ok", false), dt_sm99_ok],
		"comp_big": [comp99_big_res.get("ok", false), comp99_big_res.get("reason", ""), dt_comp99_big],
		"comp_ok": [comp99_ok_res.get("ok", false), dt_comp99_ok],
	}
	r12["arr99_live20_ok"] = (
		v99_0 and int(ctx_v99_0.get("nodes", 0)) < 100000 and dt_v99_0 < 200
		and v99_3 and int(ctx_v99_3.get("nodes", 0)) < 100000 and dt_v99_3 < 200
		and not bool(sm99_big_res.get("ok", true)) and str(sm99_big_res.get("reason", "")) == "module_entry_size_limit" and dt_sm99_big < 200
		and bool(sm99_ok_res.get("ok", false)) and dt_sm99_ok < 200
		and not bool(comp99_big_res.get("ok", true)) and str(comp99_big_res.get("reason", "")) == "component_state_size_limit" and dt_comp99_big < 200
		and bool(comp99_ok_res.get("ok", false)) and dt_comp99_ok < 200
	)

	# Group A.3: arr15_15lvl_est128
	var base15: Array = []
	for b15_i: int in range(15):
		base15.append(b15_i)
	var big15_list: Array = []
	for f15_i: int in range(20):
		var cur15: Array = base15.duplicate()
		cur15[0] = f15_i
		for _l15: int in range(10):
			var nxt15: Array = []
			for _c15: int in range(8):
				nxt15.append(cur15)
			for _p15: int in range(7):
				nxt15.append(_p15)
			cur15 = nxt15
		big15_list.append(cur15)

	var trap15: Array = base15.duplicate()
	for _t15: int in range(15):
		var row15: Array = [trap15]
		for jm15: int in range(13):
			var sub15_len: int = 70 - jm15
			var sub15: Array = []
			for si15: int in range(sub15_len):
				sub15.append(si15)
			var j15: Array = [sub15]
			for jp15: int in range(14):
				j15.append(jp15)
			row15.append(j15)
		row15.append(trap15)
		trap15 = row15

	var chain15: Dictionary = {"h": big15_list[19], "n": trap15}
	for fi15: int in range(18, -1, -1):
		chain15 = {"h": big15_list[fi15], "n": chain15}

	var ctx_est15 := {"nodes": 0}
	var t_est15_0: int = Time.get_ticks_msec()
	var est15_val: int = adapter.bounded_variant_size_estimate(chain15, 0, [], 0x7fffffffffffffff, 128, ctx_est15)
	var dt_est15: int = Time.get_ticks_msec() - t_est15_0
	r12["arr15_debug"] = [est15_val, int(ctx_est15.get("nodes", 0)), dt_est15]
	r12["arr15_15lvl_est128_ok"] = est15_val > 0 and int(ctx_est15.get("nodes", 0)) < 100000 and dt_est15 < 200

	# Group A.4: live30_hit100_spoof_dag24, same_depth_20_big_junk, [junk_0_heavy, trap, junk_1..13, trap], 20-level [D, [D]]
	var dag24_spoof: Array = _make_arr_dag(24, 1)
	var spoof_trap: Array = base99.duplicate()
	for _st_l: int in range(15):
		var row_sp: Array = [spoof_trap]
		for jsm: int in range(33):
			var j_sp: Array = [jsm, dag24_spoof]
			for jsp_p: int in range(66):
				j_sp.append(jsp_p)
			row_sp.append(j_sp)
			row_sp.append(j_sp)
		row_sp.append(spoof_trap)
		spoof_trap = row_sp
	var live30_payload: Variant = {"h": [], "n": spoof_trap}
	for f30_i: int in range(29, -1, -1):
		var h30: Array = [f30_i, dag24_spoof]
		for _p30: int in range(66):
			h30.append(_p30)
		var h30_100: Array = []
		for _r100: int in range(100):
			h30_100.append(h30)
		live30_payload = {"h": h30_100, "n": live30_payload if f30_i < 29 else spoof_trap}
	var ctx_live30 := {"nodes": 0}
	var t_l30_0: int = Time.get_ticks_msec()
	var est_l30: int = adapter.bounded_variant_size_estimate(live30_payload, 0, [], 0x7fffffffffffffff, 128, ctx_live30)
	var dt_l30: int = Time.get_ticks_msec() - t_l30_0

	var same_depth_20: Array = []
	for sd_i: int in range(20):
		same_depth_20.append(big15_list[sd_i])
	same_depth_20.append(trap15)
	var ctx_sd20 := {"nodes": 0}
	var t_sd20_0: int = Time.get_ticks_msec()
	var est_sd20: int = adapter.bounded_variant_size_estimate(same_depth_20, 0, [], 0x7fffffffffffffff, 128, ctx_sd20)
	var dt_sd20: int = Time.get_ticks_msec() - t_sd20_0

	var trap99_j0: Array = base99.duplicate()
	var dag4_heavy: Array = _make_arr_dag(4, 1)
	for _tj0: int in range(4):
		var j0_heavy: Array = [dag4_heavy]
		for _j0p: int in range(98):
			j0_heavy.append(_j0p)
		var row_j0: Array = [j0_heavy, trap99_j0]
		for jm0: int in range(13):
			var sub0_len: int = 50 - jm0
			var sub0: Array = []
			for si0: int in range(sub0_len):
				sub0.append(si0)
			var j0_n: Array = [sub0]
			for jp0: int in range(98):
				j0_n.append(jp0)
			row_j0.append(j0_n)
		row_j0.append(trap99_j0)
		for _p83: int in range(83):
			row_j0.append(_p83)
		trap99_j0 = row_j0
	var chain99_j0: Dictionary = {"h": h99_list[19], "n": trap99_j0}
	for fi_j0: int in range(18, -1, -1):
		chain99_j0 = {"h": h99_list[fi_j0], "n": chain99_j0}
	var ctx_j0_v := {"nodes": 0}
	var t_j0_v0: int = Time.get_ticks_msec()
	var ok_j0_v: bool = adapter.is_valid_state_data(chain99_j0, 3, [], 32, ctx_j0_v)
	var dt_j0_v: int = Time.get_ticks_msec() - t_j0_v0
	var ctx_j0_b := {"nodes": 0}
	var t_j0_b0: int = Time.get_ticks_msec()
	var est_j0_b: int = adapter.bounded_variant_size_estimate(chain99_j0, 3, [], 0x7fffffffffffffff, 32, ctx_j0_b)
	var dt_j0_b: int = Time.get_ticks_msec() - t_j0_b0

	var asym_unclip: Array = [1, 2, 3, 4]
	for _au: int in range(14):
		asym_unclip = [asym_unclip, [asym_unclip]]
	var ctx_au_v := {"nodes": 0}
	var t_au_v0: int = Time.get_ticks_msec()
	var ok_au_v: bool = adapter.is_valid_state_data(asym_unclip, 0, [], 32, ctx_au_v)
	var dt_au_v: int = Time.get_ticks_msec() - t_au_v0
	var asym_unclip20: Array = asym_unclip
	for _au20: int in range(6):
		asym_unclip20 = [asym_unclip20, [asym_unclip20]]
	var ctx_au_b := {"nodes": 0}
	var t_au_b0: int = Time.get_ticks_msec()
	var est_au_b: int = adapter.bounded_variant_size_estimate(asym_unclip20, 0, [], 0x7fffffffffffffff, 128, ctx_au_b)
	var dt_au_b: int = Time.get_ticks_msec() - t_au_b0

	r12["adversarial_variants_debug"] = {
		"live30": [est_l30, int(ctx_live30.get("nodes", 0)), dt_l30],
		"sd20": [est_sd20, int(ctx_sd20.get("nodes", 0)), dt_sd20],
		"j0": [ok_j0_v, int(ctx_j0_v.get("nodes", 0)), dt_j0_v, est_j0_b, int(ctx_j0_b.get("nodes", 0)), dt_j0_b],
		"asym_dd": [ok_au_v, int(ctx_au_v.get("nodes", 0)), dt_au_v, est_au_b, int(ctx_au_b.get("nodes", 0)), dt_au_b],
	}
	r12["adversarial_variants_ok"] = (
		est_l30 > 0 and int(ctx_live30.get("nodes", 0)) < 100000 and dt_l30 < 200
		and est_sd20 > 0 and int(ctx_sd20.get("nodes", 0)) < 100000 and dt_sd20 < 200
		and ok_j0_v and int(ctx_j0_v.get("nodes", 0)) < 100000 and dt_j0_v < 200
		and est_j0_b > 0 and int(ctx_j0_b.get("nodes", 0)) < 100000 and dt_j0_b < 200
		and ok_au_v and int(ctx_au_v.get("nodes", 0)) < 100000 and dt_au_v < 200
		and est_au_b > 0 and int(ctx_au_b.get("nodes", 0)) < 100000 and dt_au_b < 200
	)

	# Group A.5: clipped_dict_buckets & clipped_arr_buckets 20-copy same_depth < 4 MiB
	var clip_d_sub: Dictionary = _make_deep_dict(12, {"x": 1, "y": 2})
	var clip_d_heavy: Array = []
	for chd_i: int in range(20):
		var hd := {"id": chd_i}
		for hk: int in range(14):
			hd["k%d" % hk] = _make_deep_dict(11, _make_dag(4, {"id": chd_i}))
		clip_d_heavy.append(hd)
	var clip_d_trap: Dictionary = clip_d_sub
	for _tdc: int in range(3):
		var td_next := {"t0": clip_d_trap, "t1": clip_d_trap}
		for jd_i: int in range(13):
			var j_dict := {"a": _make_deep_dict(10, {"len": 20 - jd_i})}
			for jdp: int in range(14):
				j_dict["p%d" % jdp] = jdp
			td_next["j%d" % jd_i] = j_dict
		clip_d_trap = td_next
	var clip_d_row: Array = []
	for _ch: int in range(20):
		clip_d_row.append(clip_d_heavy[_ch])
	for _ct: int in range(20):
		clip_d_row.append(clip_d_trap)
	var payload_clip_dict: Dictionary = _make_deep_dict(20, clip_d_row)

	var clip_a_heavy: Array = []
	for cha_i: int in range(20):
		var ha: Array = [cha_i]
		for _ak: int in range(14):
			ha.append(_make_deep_dict(11, _make_arr_dag(4, [cha_i, 1])))
		clip_a_heavy.append(ha)
	var clip_a_trap: Array = [clip_d_sub, clip_d_sub]
	for _tac: int in range(3):
		var ta_next: Array = [clip_a_trap]
		for ja_i: int in range(13):
			var j_arr_c: Array = [_make_deep_dict(10, {"len": 20 - ja_i})]
			for jap: int in range(14):
				j_arr_c.append(jap)
			ta_next.append(j_arr_c)
		ta_next.append(clip_a_trap)
		clip_a_trap = ta_next
	var clip_a_row: Array = []
	for _cah: int in range(20):
		clip_a_row.append(clip_a_heavy[_cah])
	for _cat: int in range(20):
		clip_a_row.append(clip_a_trap)
	var payload_clip_arr: Dictionary = _make_deep_dict(20, clip_a_row)

	var clip_same_depth_ok: bool = true
	for cp_item: Dictionary in [payload_clip_dict, payload_clip_arr]:
		var t_cp_c0: int = Time.get_ticks_msec()
		var cp_cln: Variant = adapter._safe_clone_variant(cp_item)
		var dt_cp_c: int = Time.get_ticks_msec() - t_cp_c0
		var t_cp_s0: int = Time.get_ticks_msec()
		var cp_san: Variant = adapter.sanitize_module_value(cp_item)
		var dt_cp_s: int = Time.get_ticks_msec() - t_cp_s0
		var t_cp_b0: int = Time.get_ticks_msec()
		var cp_bus: Dictionary = st_bus.info("s", "clip_sd", cp_item)
		var dt_cp_b: int = Time.get_ticks_msec() - t_cp_b0
		var m_cp_c := _measure_depth_and_check_empty_32(cp_cln)
		var m_cp_s := _measure_depth_and_check_empty_32(cp_san)
		var cp_ctx: Variant = cp_bus.get("context", {})
		var m_cp_b := _measure_depth_and_check_empty_32(cp_ctx)
		if (
			not (cp_cln is Dictionary) or (cp_cln as Dictionary).is_empty() or dt_cp_c >= 250
			or int(m_cp_c["max_depth"]) != 32 or bool(m_cp_c["non_empty_at_32"])
			or not (cp_san is Dictionary) or (cp_san as Dictionary).is_empty() or dt_cp_s >= 250
			or int(m_cp_s["max_depth"]) != 32 or bool(m_cp_s["non_empty_at_32"])
			or not (cp_ctx is Dictionary) or (cp_ctx as Dictionary).is_empty() or dt_cp_b >= 250
			or int(m_cp_b["max_depth"]) != 32 or bool(m_cp_b["non_empty_at_32"])
		):
			clip_same_depth_ok = false
	r12["clipped_same_depth_20copy_ok"] = clip_same_depth_ok

	# Group B: Non-byte-overflowing Depth-33 Clipped DAG Across All 9 Entrypoints
	var deep17_dag16: Dictionary = _make_deep_dict(17, _make_dag(16, {"v": 1}))
	var deep17_dag15_arr: Dictionary = _make_deep_dict(17, _make_arr_dag(15, [1, 2]))
	var nonvac_clip_ok: bool = true
	var nonvac_clip_debug: Array = []
	for nv_p: Dictionary in [deep17_dag16, deep17_dag15_arr]:
		var t0_c: int = Time.get_ticks_msec()
		var nv_cln: Variant = adapter._safe_clone_variant(nv_p)
		var dt0_c: int = Time.get_ticks_msec() - t0_c
		var m_nv_c := _measure_depth_and_check_empty_32(nv_cln)

		var t0_s: int = Time.get_ticks_msec()
		var nv_san: Variant = adapter.sanitize_module_value(nv_p)
		var dt0_s: int = Time.get_ticks_msec() - t0_s
		var m_nv_s := _measure_depth_and_check_empty_32(nv_san)

		var t0_b: int = Time.get_ticks_msec()
		var nv_bus: Dictionary = st_bus.info("s", "clip_nv", nv_p)
		var dt0_b: int = Time.get_ticks_msec() - t0_b
		var nv_bus_ctx: Variant = nv_bus.get("context", {})
		var m_nv_b := _measure_depth_and_check_empty_32(nv_bus_ctx)

		var t0_r: int = Time.get_ticks_msec()
		var nv_reg_f: bool = st_reg.probe_feature_manager(nv_p)
		var nv_reg_t: bool = st_reg.probe_feature_manager({"rows": [], "campaign_blockers": [nv_p]})
		var nv_reg_rep: Dictionary = st_reg.get_last_probe_report()
		var dt0_r: int = Time.get_ticks_msec() - t0_r
		var nv_reg_blks_var: Variant = nv_reg_rep.get("campaign_blockers", [])
		var nv_reg_blks: Array = nv_reg_blks_var as Array if nv_reg_blks_var is Array else []
		var nv_reg_blk: Variant = nv_reg_blks[0] if not nv_reg_blks.is_empty() else {}
		var m_nv_r := _measure_depth_and_check_empty_32({"k": {"k": nv_reg_blk}})

		var t0_el: int = Time.get_ticks_msec()
		var nv_el: Dictionary = st_el.build_template_data("cp_nv", "CPNV", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", nv_p)
		var dt0_el: int = Time.get_ticks_msec() - t0_el
		var nv_el_comp: Variant = nv_el.get("components", {})
		var m_nv_el := _measure_depth_and_check_empty_32(nv_el_comp)

		var t0_re: int = Time.get_ticks_msec()
		var nv_re: Dictionary = sib_el_sdk.register_entries("ns_clip_nv", [nv_p], sib_el_host, sib_el_sess, true)
		var dt0_re: int = Time.get_ticks_msec() - t0_re

		var t0_rp: int = Time.get_ticks_msec()
		var nv_rp: Dictionary = sib_el_sdk.register_presets("ns_clip_nv", [nv_p], sib_el_host, sib_el_sess)
		var dt0_rp: int = Time.get_ticks_msec() - t0_rp

		var t0_oa: int = Time.get_ticks_msec()
		var nv_oa: Dictionary = st_oa.make_obstacle_state("object", "manual", 64.0, nv_p, nv_p)
		var dt0_oa: int = Time.get_ticks_msec() - t0_oa
		var nv_oa_shape: Variant = nv_oa.get("shape", {})
		var nv_oa_cache: Variant = nv_oa.get("cache", {})
		var m_nv_oa_s := _measure_depth_and_check_empty_32(nv_oa_shape)
		var m_nv_oa_c := _measure_depth_and_check_empty_32(nv_oa_cache)

		var t0_cs: int = Time.get_ticks_msec()
		var nv_cs = sdk.create_session(MockHost.new(), nv_p)
		var dt0_cs: int = Time.get_ticks_msec() - t0_cs
		var nv_cs_opts: Dictionary = nv_cs.get_options() if nv_cs != null else {}
		var m_nv_cs := _measure_depth_and_check_empty_32(nv_cs_opts)

		nonvac_clip_debug.append([dt0_c, dt0_s, dt0_b, dt0_r, dt0_el, dt0_re, dt0_rp, dt0_oa, dt0_cs])
		if (
			not (nv_cln is Dictionary) or (nv_cln as Dictionary).is_empty() or int(m_nv_c["max_depth"]) != 32 or bool(m_nv_c["non_empty_at_32"]) or dt0_c >= 100
			or not (nv_san is Dictionary) or (nv_san as Dictionary).is_empty() or int(m_nv_s["max_depth"]) != 32 or bool(m_nv_s["non_empty_at_32"]) or dt0_s >= 100
			or not (nv_bus_ctx is Dictionary) or (nv_bus_ctx as Dictionary).is_empty() or int(m_nv_b["max_depth"]) != 32 or bool(m_nv_b["non_empty_at_32"]) or dt0_b >= 100
			or nv_reg_f or not nv_reg_t or int(m_nv_r["max_depth"]) != 32 or bool(m_nv_r["non_empty_at_32"]) or dt0_r >= 100
			or not (nv_el_comp is Dictionary) or not (nv_el_comp as Dictionary).has("k") or int(m_nv_el["max_depth"]) != 32 or bool(m_nv_el["non_empty_at_32"]) or dt0_el >= 100
			or not bool(nv_re.get("ok", false)) or dt0_re >= 100
			or not bool(nv_rp.get("ok", false)) or dt0_rp >= 100
			or not (nv_oa_shape is Dictionary) or not (nv_oa_shape as Dictionary).has("k") or int(m_nv_oa_s["max_depth"]) != 32 or bool(m_nv_oa_s["non_empty_at_32"])
			or not (nv_oa_cache is Dictionary) or not (nv_oa_cache as Dictionary).has("k") or int(m_nv_oa_c["max_depth"]) != 32 or bool(m_nv_oa_c["non_empty_at_32"]) or dt0_oa >= 100
			or nv_cs_opts.is_empty() or int(m_nv_cs["max_depth"]) != 32 or bool(m_nv_cs["non_empty_at_32"]) or dt0_cs >= 100
		):
			nonvac_clip_ok = false
	r12["nonvacuous_clipped_debug"] = nonvac_clip_debug
	r12["nonvacuous_clipped_9entrypoints_ok"] = nonvac_clip_ok

	# Group C: LogBus.info < 4 MiB Depth-32 Empty-Leaf Preservation (wrap18 + dag13_empty)
	var dag13_empty_d: Array = _make_arr_dag(13, {})
	var dag13_empty_a: Array = _make_arr_dag(13, [])
	var wrap18_d: Dictionary = _make_deep_dict(18, [dag13_empty_d, dag13_empty_d, dag13_empty_d])
	var wrap18_a: Dictionary = _make_deep_dict(18, [dag13_empty_a, dag13_empty_a, dag13_empty_a])
	var t_lb18d0: int = Time.get_ticks_msec()
	var lb18_d: Dictionary = st_bus.info("s", "dc13_d", wrap18_d)
	var dt_lb18d: int = Time.get_ticks_msec() - t_lb18d0
	var t_lb18a0: int = Time.get_ticks_msec()
	var lb18_a: Dictionary = st_bus.info("s", "dc13_a", wrap18_a)
	var dt_lb18a: int = Time.get_ticks_msec() - t_lb18a0
	var cur_d32: Variant = lb18_d.get("context", {})
	var cur_a32: Variant = lb18_a.get("context", {})
	var lb18_ok: bool = (
		cur_d32 is Dictionary and not (cur_d32 as Dictionary).is_empty() and dt_lb18d < 100
		and cur_a32 is Dictionary and not (cur_a32 as Dictionary).is_empty() and dt_lb18a < 100
	)
	if lb18_ok:
		for _h18: int in range(18):
			cur_d32 = (cur_d32 as Dictionary).get("k", null)
			cur_a32 = (cur_a32 as Dictionary).get("k", null)
		if cur_d32 is Array and not (cur_d32 as Array).is_empty() and cur_a32 is Array and not (cur_a32 as Array).is_empty():
			cur_d32 = (cur_d32 as Array)[0]
			cur_a32 = (cur_a32 as Array)[0]
			for _h13: int in range(13):
				cur_d32 = (cur_d32 as Array)[0] if (cur_d32 is Array and not (cur_d32 as Array).is_empty()) else null
				cur_a32 = (cur_a32 as Array)[0] if (cur_a32 is Array and not (cur_a32 as Array).is_empty()) else null
			lb18_ok = (cur_d32 is Dictionary and (cur_d32 as Dictionary).is_empty()) and (cur_a32 is Array and (cur_a32 as Array).is_empty())
		else:
			lb18_ok = false
	r12["logbus_depth32_empty_leaf_ok"] = lb18_ok

	# Group D: Asymmetric Depth-Clipped DAG (25_26 / 26_25 / arr_25_26 / 18_19 / 19_18)
	var dag18_leaf7: Dictionary = _make_dag(18, {"leaf": 7})
	var arr_dag18_leaf7: Array = _make_arr_dag(18, {"leaf": 7})
	var dag13_leaf7: Dictionary = _make_dag(13, {"leaf": 7})
	var asym_25_26 := {"a": _make_deep_dict(24, dag18_leaf7), "b": _make_deep_dict(25, dag18_leaf7)}
	var asym_26_25 := {"a": _make_deep_dict(25, dag18_leaf7), "b": _make_deep_dict(24, dag18_leaf7)}
	var asym_arr_25_26 := {"a": _make_deep_dict(24, arr_dag18_leaf7), "b": _make_deep_dict(25, arr_dag18_leaf7)}
	var asym_18_19 := {"a": _make_deep_dict(17, dag13_leaf7), "b": _make_deep_dict(18, dag13_leaf7)}
	var asym_19_18 := {"a": _make_deep_dict(18, dag13_leaf7), "b": _make_deep_dict(17, dag13_leaf7)}

	var asym_ok: bool = true
	for ap_idx: int in range(5):
		var ap_pay: Dictionary = [asym_25_26, asym_26_25, asym_arr_25_26, asym_18_19, asym_19_18][ap_idx]
		var ta_c0: int = Time.get_ticks_msec()
		var a_cln: Variant = adapter._safe_clone_variant(ap_pay)
		var dta_c: int = Time.get_ticks_msec() - ta_c0

		var ta_s0: int = Time.get_ticks_msec()
		var a_san: Variant = adapter.sanitize_module_value(ap_pay)
		var dta_s: int = Time.get_ticks_msec() - ta_s0

		var ta_b0: int = Time.get_ticks_msec()
		var a_bus: Dictionary = st_bus.info("s", "asym", ap_pay)
		var dta_b: int = Time.get_ticks_msec() - ta_b0
		var a_bus_ctx: Variant = a_bus.get("context", {})

		var ta_r0: int = Time.get_ticks_msec()
		var a_reg_t: bool = st_reg.probe_feature_manager({"rows": [], "campaign_blockers": [ap_pay]})
		var dta_r: int = Time.get_ticks_msec() - ta_r0
		var a_reg_blk: Variant = st_reg._last_probe_report.get("campaign_blockers", [])[0]

		var ta_el0: int = Time.get_ticks_msec()
		var a_el: Dictionary = st_el.build_template_data("asy_u", "ASYU", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", ap_pay)
		var dta_el: int = Time.get_ticks_msec() - ta_el0
		var a_el_comp: Variant = a_el.get("components", {})

		var ta_oa0: int = Time.get_ticks_msec()
		var a_oa: Dictionary = st_oa.make_obstacle_state("object", "manual", 64.0, ap_pay, {})
		var dta_oa: int = Time.get_ticks_msec() - ta_oa0
		var a_oa_shape: Variant = a_oa.get("shape", {})

		if dta_c >= 100 or dta_s >= 100 or dta_b >= 100 or not a_reg_t or dta_r >= 100 or dta_el >= 100 or dta_oa >= 100:
			asym_ok = false
			break

		var outs: Array = [a_cln, a_san, a_bus_ctx, a_el_comp, a_oa_shape]
		for out_v: Variant in outs:
			if not (out_v is Dictionary) or not (out_v as Dictionary).has("a") or not (out_v as Dictionary).has("b"):
				asym_ok = false
				break
			var ma_br := _measure_depth_and_check_empty_32({"a": (out_v as Dictionary)["a"]})
			var mb_br := _measure_depth_and_check_empty_32({"b": (out_v as Dictionary)["b"]})
			var exp_a_depth: int = 31 if ap_idx == 3 else 32
			var exp_b_depth: int = 31 if ap_idx == 4 else 32
			if int(ma_br["max_depth"]) != exp_a_depth or bool(ma_br["non_empty_at_32"]) or int(mb_br["max_depth"]) != exp_b_depth or bool(mb_br["non_empty_at_32"]):
				asym_ok = false
				break
			if ap_idx >= 3:
				# 18_19 / 19_18: shallow branch preserves {"leaf": 7}, deep branch clips to {}
				var shallow_key: String = "a" if ap_idx == 3 else "b"
				var deep_key: String = "b" if ap_idx == 3 else "a"
				var sh_node: Variant = (out_v as Dictionary)[shallow_key]
				for _h17: int in range(17):
					sh_node = (sh_node as Dictionary).get("k", null) if sh_node is Dictionary else null
				for _h13s: int in range(13):
					sh_node = (sh_node as Dictionary).get("l", null) if sh_node is Dictionary else null
				if not (sh_node is Dictionary) or int((sh_node as Dictionary).get("leaf", -1)) != 7:
					asym_ok = false
					break
				var dp_node: Variant = (out_v as Dictionary)[deep_key]
				for _h18: int in range(18):
					dp_node = (dp_node as Dictionary).get("k", null) if dp_node is Dictionary else null
				for _h13d: int in range(13):
					dp_node = (dp_node as Dictionary).get("l", null) if dp_node is Dictionary else null
				if not (dp_node is Dictionary) or not (dp_node as Dictionary).is_empty():
					asym_ok = false
					break
		# Also check a_reg_blk (which had 2 extra nesting levels from {"rows":[], "campaign_blockers":[ap_pay]})
		if not (a_reg_blk is Dictionary) or not (a_reg_blk as Dictionary).has("a") or not (a_reg_blk as Dictionary).has("b"):
			asym_ok = false
		else:
			var m_reg_blk := _measure_depth_and_check_empty_32({"r": {"c": a_reg_blk}})
			if int(m_reg_blk["max_depth"]) != 32 or bool(m_reg_blk["non_empty_at_32"]):
				asym_ok = false

	r12["asymmetric_clipped_isolation_ok"] = asym_ok
	results["r12_hardening"] = r12

	# Iter 13 Regression (Groups A-E + VALID_0HIT_GHOST141_WRAP + sibling cleanup)
	var r13 := {}
	var r13_p_e: Array = []
	for r13_pi: int in range(32):
		var r13_leaf300: Array = []
		for r13_li: int in range(300):
			r13_leaf300.append(r13_pi * 1000 + r13_li)
		var r13_arr200: Array = [r13_leaf300, r13_pi]
		for r13_ai: int in range(198):
			r13_arr200.append(r13_ai)
		r13_p_e.append(r13_arr200)
		r13_p_e.append(r13_arr200)

	var r13_trap_e: Array = []
	for _r13_ti: int in range(200):
		r13_trap_e.append(null)

	# Group A: exploit_e_10500
	var r13_seq_e_10500: Array = r13_p_e.duplicate()
	for _r13_ei: int in range(10500):
		r13_seq_e_10500.append(r13_trap_e)
	var r13_dict_e_10500 := {"p": r13_seq_e_10500}

	var r13_ctx_a_v := {"nodes": 0}
	var r13_t0: int = Time.get_ticks_msec()
	var r13_a_valid: bool = adapter.is_valid_state_data(r13_dict_e_10500, 3, [], 32, r13_ctx_a_v)
	var r13_a_v_ms: int = Time.get_ticks_msec() - r13_t0

	var r13_ctx_a_b := {"nodes": 0}
	r13_t0 = Time.get_ticks_msec()
	var r13_a_est: int = adapter.bounded_variant_size_estimate(r13_dict_e_10500, 0, [], 24 * 1024 * 1024, 128, r13_ctx_a_b)
	var r13_a_b_ms: int = Time.get_ticks_msec() - r13_t0

	var r13_p_e_fit: Array = []
	for r13_pi: int in range(32):
		var r13_fleaf300: Array = []
		for r13_li: int in range(300):
			r13_fleaf300.append(100000 + r13_pi * 1000 + r13_li)
		var r13_farr180: Array = [r13_fleaf300, r13_pi]
		for r13_ai: int in range(178):
			r13_farr180.append(r13_ai)
		r13_p_e_fit.append(r13_farr180)
		r13_p_e_fit.append(r13_farr180)
	var r13_trap_e_180: Array = []
	for _r13_ti: int in range(180):
		r13_trap_e_180.append(null)
	var r13_seq_e_10500_fit: Array = r13_p_e_fit.duplicate()
	for _r13_ei: int in range(10500):
		r13_seq_e_10500_fit.append(r13_trap_e_180)
	var r13_dict_e_10500_fit := {"p": r13_seq_e_10500_fit}

	var r13_wb_a = sdk.create_world_builder(sdk.create_session(MockHost.new(), {}), 150.0)
	r13_wb_a.get_logger().set_emit_to_engine(false)
	var r13_w_a: Dictionary = r13_wb_a.get_world()
	r13_t0 = Time.get_ticks_msec()
	var r13_a_sm: Dictionary = adapter.set_module_state(r13_w_a, "r13_exp_e", 1, r13_dict_e_10500_fit)
	var r13_a_sm_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_a_sm_sz: int = (r13_w_a.get("modules", {}).get("entries", {}).get("r13_exp_e", {}).get("state", {}).get("p", []) as Array).size()

	var r13_ent_a_id: String = r13_wb_a.add_object_sprite("r13_ent_a", "R13EntA", Vector2(100, 100), Vector2(64, 64), "")
	var r13_ent_a: Dictionary = r13_wb_a.get_entity(r13_ent_a_id)
	r13_t0 = Time.get_ticks_msec()
	var r13_a_comp: Dictionary = adapter.append_entity_component(r13_ent_a, "res://modules/follow/comp_follow.gd", r13_dict_e_10500_fit, true, false)
	var r13_a_comp_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_a_comp_sz: int = 0
	var r13_ent_a_comps: Array = r13_ent_a.get("components", [])
	if r13_ent_a_comps.size() >= 3:
		r13_a_comp_sz = ((r13_ent_a_comps[r13_ent_a_comps.size() - 1] as Dictionary).get("state", {}).get("p", []) as Array).size()

	r13["group_a_exploit_e_10500_ok"] = (
		r13_a_valid and int(r13_ctx_a_v.get("nodes", 999999)) < 100000 and r13_a_v_ms < 200
		and r13_a_est > 8000000 and int(r13_ctx_a_b.get("nodes", 999999)) < 100000 and r13_a_b_ms < 200
		and bool(r13_a_sm.get("ok", false)) and r13_a_sm_ms < 500 and r13_a_sm_sz == 10564
		and bool(r13_a_comp.get("ok", false)) and r13_a_comp_ms < 350 and r13_a_comp_sz == 10564
	)
	r13["group_a_debug"] = {
		"valid": r13_a_valid, "v_nodes": int(r13_ctx_a_v.get("nodes", -1)), "v_ms": r13_a_v_ms,
		"est": r13_a_est, "b_nodes": int(r13_ctx_a_b.get("nodes", -1)), "b_ms": r13_a_b_ms,
		"sm_ok": r13_a_sm.get("ok", false), "sm_ms": r13_a_sm_ms, "sm_sz": r13_a_sm_sz,
		"comp_ok": r13_a_comp.get("ok", false), "comp_ms": r13_a_comp_ms, "comp_sz": r13_a_comp_sz,
	}

	# Group B: exploit_f_child_1junk_fixed
	var r13_p_f: Array = []
	for r13_fi: int in range(32):
		var r13_leaf30: Array = []
		for r13_li: int in range(30):
			r13_leaf30.append(r13_fi * 100 + r13_li)
		var r13_f_arr: Array = [r13_leaf30, r13_fi]
		for r13_ai: int in range(198):
			r13_f_arr.append(r13_ai)
		r13_p_f.append(r13_f_arr)
		r13_p_f.append(r13_f_arr)
	var r13_leaf30_sub: Array = []
	for r13_li: int in range(30):
		r13_leaf30_sub.append(99000 + r13_li)
	var r13_junk_sub: Array = [r13_leaf30_sub, 999]
	for r13_ai: int in range(198):
		r13_junk_sub.append(r13_ai)
	var r13_f_sub: Array = [r13_junk_sub, r13_junk_sub]
	for _r13_si: int in range(10500):
		r13_f_sub.append(r13_trap_e)
	var r13_dict_f := {"p": r13_p_f, "sub": r13_f_sub}

	var r13_ctx_b_v := {"nodes": 0}
	r13_t0 = Time.get_ticks_msec()
	var r13_b_valid: bool = adapter.is_valid_state_data(r13_dict_f, 3, [], 32, r13_ctx_b_v)
	var r13_b_v_ms: int = Time.get_ticks_msec() - r13_t0

	var r13_ctx_b_b := {"nodes": 0}
	r13_t0 = Time.get_ticks_msec()
	var r13_b_est: int = adapter.bounded_variant_size_estimate(r13_dict_f, 0, [], 24 * 1024 * 1024, 128, r13_ctx_b_b)
	var r13_b_b_ms: int = Time.get_ticks_msec() - r13_t0

	r13["group_b_exploit_f_child_ok"] = (
		r13_b_valid and int(r13_ctx_b_v.get("nodes", 999999)) < 100000 and r13_b_v_ms < 200
		and r13_b_est > 8000000 and int(r13_ctx_b_b.get("nodes", 999999)) < 100000 and r13_b_b_ms < 200
	)
	r13["group_b_debug"] = {
		"valid": r13_b_valid, "v_nodes": int(r13_ctx_b_v.get("nodes", -1)), "v_ms": r13_b_v_ms,
		"est": r13_b_est, "b_nodes": int(r13_ctx_b_b.get("nodes", -1)), "b_ms": r13_b_b_ms,
	}

	# Group C: exploit_e_9000 & exploit_h_logbus_lt4mb across all 5 cloning scripts
	var r13_seq_e_9000: Array = r13_p_e.duplicate()
	for _r13_ei: int in range(9000):
		r13_seq_e_9000.append(r13_trap_e)
	var r13_dict_e_9000 := {"p": r13_seq_e_9000}

	var r13_seq_h: Array = r13_p_f.duplicate()
	for _r13_hi: int in range(2300):
		r13_seq_h.append(r13_trap_e)
	var r13_dict_h := {"p": r13_seq_h}

	r13_t0 = Time.get_ticks_msec()
	var r13_c_adp_pub: Variant = adapter._safe_clone_variant(r13_dict_e_9000, 0, [], [])
	var r13_c_adp_pub_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_c_adp_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_c_adp_node: Variant = dag_cloner.safe_clone_node(r13_dict_e_9000, 0, [], r13_c_adp_tctx)
	var r13_c_adp_node_ms: int = Time.get_ticks_msec() - r13_t0

	r13_t0 = Time.get_ticks_msec()
	var r13_c_san_pub: Variant = adapter.sanitize_module_value(r13_dict_e_9000, 0, [], [])
	var r13_c_san_pub_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_c_san_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_c_san_node: Variant = adapter._sanitize_module_node(r13_dict_e_9000, 0, [], r13_c_san_tctx)
	var r13_c_san_node_ms: int = Time.get_ticks_msec() - r13_t0

	r13_t0 = Time.get_ticks_msec()
	var r13_c_bus_pub: Dictionary = st_bus.info("s", "exp_h", r13_dict_h)
	var r13_c_bus_pub_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_c_bus_tctx = dag_cloner.DagTravCtx.new()
	r13_c_bus_tctx.max_bytes = 4 * 1024 * 1024
	r13_t0 = Time.get_ticks_msec()
	var r13_c_bus_node: Variant = dag_cloner.safe_clone_node(r13_dict_h, 0, [], r13_c_bus_tctx)
	var r13_c_bus_node_ms: int = Time.get_ticks_msec() - r13_t0

	r13_t0 = Time.get_ticks_msec()
	var r13_c_reg_pub_ok: bool = st_reg.probe_feature_manager({"rows": [], "campaign_blockers": [r13_dict_e_9000]})
	var r13_c_reg_rep: Dictionary = st_reg.get_last_probe_report()
	var r13_c_reg_pub_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_c_reg_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_c_reg_node: Variant = dag_cloner.safe_clone_node(r13_dict_e_9000, 0, [], r13_c_reg_tctx)
	var r13_c_reg_node_ms: int = Time.get_ticks_msec() - r13_t0

	r13_t0 = Time.get_ticks_msec()
	var r13_c_el_pub: Dictionary = st_el.build_template_data("r13_e9k", "R13E9K", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", r13_dict_e_9000)
	var r13_c_el_pub_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_c_el_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_c_el_node: Variant = dag_cloner.safe_clone_node(r13_dict_e_9000, 0, [], r13_c_el_tctx)
	var r13_c_el_node_ms: int = Time.get_ticks_msec() - r13_t0

	r13_t0 = Time.get_ticks_msec()
	var r13_c_oa_pub: Dictionary = st_oa.make_obstacle_state("object", "manual", 64.0, r13_dict_e_9000, {})
	var r13_c_oa_pub_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_c_oa_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_c_oa_node: Variant = dag_cloner.safe_clone_node(r13_dict_e_9000, 0, [], r13_c_oa_tctx)
	var r13_c_oa_node_ms: int = Time.get_ticks_msec() - r13_t0

	var r13_c_reg_blk_arr: Array = r13_c_reg_rep.get("campaign_blockers", [])
	var r13_c_reg_blk_sz: int = (r13_c_reg_blk_arr[0].get("p", []) as Array).size() if (r13_c_reg_blk_arr.size() == 1 and r13_c_reg_blk_arr[0] is Dictionary) else -1
	r13["group_c_all5_cloners_ok"] = (
		r13_c_adp_pub is Dictionary and (r13_c_adp_pub.get("p", []) as Array).size() == 9064 and r13_c_adp_pub_ms < 200
		and not r13_c_adp_tctx.aborted and r13_c_adp_tctx.nodes < 100000 and r13_c_adp_node is Dictionary and (r13_c_adp_node.get("p", []) as Array).size() == 9064 and r13_c_adp_node_ms < 200
		and r13_c_san_pub is Dictionary and (r13_c_san_pub.get("p", []) as Array).size() == 9064 and r13_c_san_pub_ms < 200
		and not r13_c_san_tctx.aborted and r13_c_san_tctx.nodes < 100000 and r13_c_san_node is Dictionary and (r13_c_san_node.get("p", []) as Array).size() == 9064 and r13_c_san_node_ms < 200
		and not r13_c_bus_pub.is_empty() and (r13_c_bus_pub.get("context", {}).get("p", []) as Array).size() == 2364 and r13_c_bus_pub_ms < 200
		and not r13_c_bus_tctx.aborted and r13_c_bus_tctx.nodes < 100000 and r13_c_bus_node is Dictionary and (r13_c_bus_node.get("p", []) as Array).size() == 2364 and r13_c_bus_node_ms < 200
		and r13_c_reg_pub_ok and r13_c_reg_blk_sz == 9064 and r13_c_reg_pub_ms < 450
		and not r13_c_reg_tctx.aborted and r13_c_reg_tctx.nodes < 100000 and r13_c_reg_node is Dictionary and (r13_c_reg_node.get("p", []) as Array).size() == 9064 and r13_c_reg_node_ms < 200
		and (r13_c_el_pub.get("components", {}).get("p", []) as Array).size() == 9064 and r13_c_el_pub_ms < 200
		and not r13_c_el_tctx.aborted and r13_c_el_tctx.nodes < 100000 and r13_c_el_node is Dictionary and (r13_c_el_node.get("p", []) as Array).size() == 9064 and r13_c_el_node_ms < 200
		and (r13_c_oa_pub.get("shape", {}).get("p", []) as Array).size() == 9064 and r13_c_oa_pub_ms < 200
		and not r13_c_oa_tctx.aborted and r13_c_oa_tctx.nodes < 100000 and r13_c_oa_node is Dictionary and (r13_c_oa_node.get("p", []) as Array).size() == 9064 and r13_c_oa_node_ms < 200
	)
	r13["group_c_debug"] = {
		"adp": [r13_c_adp_pub_ms, r13_c_adp_tctx.nodes, r13_c_adp_node_ms],
		"san": [r13_c_san_pub_ms, r13_c_san_tctx.nodes, r13_c_san_node_ms],
		"bus": [r13_c_bus_pub_ms, r13_c_bus_tctx.nodes, r13_c_bus_node_ms],
		"reg": [r13_c_reg_pub_ms, r13_c_reg_tctx.nodes, r13_c_reg_node_ms, r13_c_reg_blk_sz],
		"el": [r13_c_el_pub_ms, r13_c_el_tctx.nodes, r13_c_el_node_ms],
		"oa": [r13_c_oa_pub_ms, r13_c_oa_tctx.nodes, r13_c_oa_node_ms],
	}

	# Group D1: live30 + >128 junks on height = 1 pinned trap
	var r13_trap_100: Array = []
	for _r13_ti: int in range(100):
		r13_trap_100.append(null)
	var r13_seq_d1: Array = []
	for _r13_di: int in range(5):
		r13_seq_d1.append(r13_trap_100)
	for r13_jk: int in range(150):
		var r13_jleaf10: Array = []
		for r13_jli: int in range(10):
			r13_jleaf10.append(r13_jk * 100 + r13_jli)
		var r13_jarr: Array = [r13_jleaf10, r13_jk]
		for r13_jai: int in range(98):
			r13_jarr.append(r13_jai)
		r13_seq_d1.append(r13_jarr)
		r13_seq_d1.append(r13_trap_100)
	for _r13_di: int in range(1700):
		r13_seq_d1.append(r13_trap_100)
	var r13_payload_d1: Dictionary = {"seq": r13_seq_d1}
	for r13_fi: int in range(26, -1, -1):
		var r13_f_live: Array = []
		var r13_num_own: int = 2 if r13_fi < 6 else 1
		for r13_oi: int in range(r13_num_own):
			var r13_oleaf10: Array = []
			for r13_oli: int in range(10):
				r13_oleaf10.append(50000 + r13_fi * 100 + r13_oi * 20 + r13_oli)
			var r13_oarr: Array = [r13_oleaf10, r13_fi * 10 + r13_oi]
			for r13_oai: int in range(98):
				r13_oarr.append(r13_oai)
			r13_f_live.append(r13_oarr)
			r13_f_live.append(r13_oarr)
		r13_payload_d1 = {"own": r13_f_live, "next": r13_payload_d1}

	var r13_d1_leaf_check := func(node: Variant) -> int:
		var cur: Variant = node
		for _r13_w: int in range(27):
			if not (cur is Dictionary):
				return -1
			cur = (cur as Dictionary).get("next", null)
		if not (cur is Dictionary):
			return -1
		var seq_v: Variant = (cur as Dictionary).get("seq", null)
		return (seq_v as Array).size() if seq_v is Array else -1

	var r13_d1_ctx_v := {"nodes": 0}
	r13_t0 = Time.get_ticks_msec()
	var r13_d1_v_ok: bool = adapter.is_valid_state_data(r13_payload_d1, 0, [], 32, r13_d1_ctx_v)
	var r13_d1_v_ms: int = Time.get_ticks_msec() - r13_t0

	var r13_d1_ctx_b := {"nodes": 0}
	r13_t0 = Time.get_ticks_msec()
	var r13_d1_b_est: int = adapter.bounded_variant_size_estimate(r13_payload_d1, 0, [], 24 * 1024 * 1024, 32, r13_d1_ctx_b)
	var r13_d1_b_ms: int = Time.get_ticks_msec() - r13_t0

	var r13_d1_adp_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_d1_adp_node: Variant = dag_cloner.safe_clone_node(r13_payload_d1, 0, [], r13_d1_adp_tctx)
	var r13_d1_adp_ms: int = Time.get_ticks_msec() - r13_t0

	var r13_d1_san_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_d1_san_node: Variant = adapter._sanitize_module_node(r13_payload_d1, 0, [], r13_d1_san_tctx)
	var r13_d1_san_ms: int = Time.get_ticks_msec() - r13_t0

	r13_t0 = Time.get_ticks_msec()
	var r13_d1_bus_pub: Dictionary = st_bus.info("s", "r13_d1", r13_payload_d1)
	var r13_d1_bus_pub_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_d1_bus_tctx = dag_cloner.DagTravCtx.new()
	r13_d1_bus_tctx.max_bytes = 4 * 1024 * 1024
	r13_t0 = Time.get_ticks_msec()
	var r13_d1_bus_node: Variant = dag_cloner.safe_clone_node(r13_payload_d1, 0, [], r13_d1_bus_tctx)
	var r13_d1_bus_ms: int = Time.get_ticks_msec() - r13_t0

	r13_t0 = Time.get_ticks_msec()
	var r13_d1_reg_pub_ok: bool = st_reg.probe_feature_manager({"rows": [], "campaign_blockers": [r13_payload_d1]})
	var r13_d1_reg_rep: Dictionary = st_reg.get_last_probe_report()
	var r13_d1_reg_pub_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_d1_reg_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_d1_reg_node: Variant = dag_cloner.safe_clone_node(r13_payload_d1, 0, [], r13_d1_reg_tctx)
	var r13_d1_reg_ms: int = Time.get_ticks_msec() - r13_t0

	r13_t0 = Time.get_ticks_msec()
	var r13_d1_el_pub: Dictionary = st_el.build_template_data("r13_d1", "R13D1", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", r13_payload_d1)
	var r13_d1_el_pub_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_d1_el_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_d1_el_node: Variant = dag_cloner.safe_clone_node(r13_payload_d1, 0, [], r13_d1_el_tctx)
	var r13_d1_el_ms: int = Time.get_ticks_msec() - r13_t0

	r13_t0 = Time.get_ticks_msec()
	var r13_d1_oa_pub: Dictionary = st_oa.make_obstacle_state("object", "manual", 64.0, r13_payload_d1, {})
	var r13_d1_oa_pub_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_d1_oa_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_d1_oa_node: Variant = dag_cloner.safe_clone_node(r13_payload_d1, 0, [], r13_d1_oa_tctx)
	var r13_d1_oa_ms: int = Time.get_ticks_msec() - r13_t0

	var r13_d1_reg_blk_arr: Array = r13_d1_reg_rep.get("campaign_blockers", [])
	var r13_d1_reg_seq_sz: int = int(r13_d1_leaf_check.call(r13_d1_reg_blk_arr[0])) if r13_d1_reg_blk_arr.size() == 1 else -1
	r13["group_d_live30_junks_ok"] = (
		r13_d1_v_ok and int(r13_d1_ctx_v.get("nodes", 999999)) < 100000 and r13_d1_v_ms < 200
		and r13_d1_b_est > 0 and int(r13_d1_ctx_b.get("nodes", 999999)) < 100000 and r13_d1_b_ms < 200
		and not r13_d1_adp_tctx.aborted and r13_d1_adp_tctx.nodes < 100000 and r13_d1_adp_ms < 200 and int(r13_d1_leaf_check.call(r13_d1_adp_node)) == 2005
		and not r13_d1_san_tctx.aborted and r13_d1_san_tctx.nodes < 100000 and r13_d1_san_ms < 200 and int(r13_d1_leaf_check.call(r13_d1_san_node)) == 2005
		and not r13_d1_bus_pub.is_empty() and r13_d1_bus_pub_ms < 200 and int(r13_d1_leaf_check.call(r13_d1_bus_pub.get("context", {}))) == 2005
		and not r13_d1_bus_tctx.aborted and r13_d1_bus_tctx.nodes < 100000 and r13_d1_bus_ms < 200 and int(r13_d1_leaf_check.call(r13_d1_bus_node)) == 2005
		and r13_d1_reg_pub_ok and r13_d1_reg_seq_sz == 2005 and r13_d1_reg_pub_ms < 200
		and not r13_d1_reg_tctx.aborted and r13_d1_reg_tctx.nodes < 100000 and r13_d1_reg_ms < 200 and int(r13_d1_leaf_check.call(r13_d1_reg_node)) == 2005
		and r13_d1_el_pub_ms < 200 and int(r13_d1_leaf_check.call(r13_d1_el_pub.get("components", {}))) == 2005
		and not r13_d1_el_tctx.aborted and r13_d1_el_tctx.nodes < 100000 and r13_d1_el_ms < 200 and int(r13_d1_leaf_check.call(r13_d1_el_node)) == 2005
		and r13_d1_oa_pub_ms < 200 and int(r13_d1_leaf_check.call(r13_d1_oa_pub.get("shape", {}))) == 2005
		and not r13_d1_oa_tctx.aborted and r13_d1_oa_tctx.nodes < 100000 and r13_d1_oa_ms < 200 and int(r13_d1_leaf_check.call(r13_d1_oa_node)) == 2005
	)
	r13["group_d_live30_debug"] = {
		"v": [r13_d1_v_ok, int(r13_d1_ctx_v.get("nodes", -1)), r13_d1_v_ms],
		"b": [r13_d1_b_est, int(r13_d1_ctx_b.get("nodes", -1)), r13_d1_b_ms],
		"adp": [r13_d1_adp_tctx.nodes, r13_d1_adp_ms],
		"san": [r13_d1_san_tctx.nodes, r13_d1_san_ms],
		"bus": [r13_d1_bus_tctx.nodes, r13_d1_bus_ms, r13_d1_bus_pub_ms],
		"reg": [r13_d1_reg_tctx.nodes, r13_d1_reg_ms, r13_d1_reg_pub_ms, r13_d1_reg_seq_sz],
		"el": [r13_d1_el_tctx.nodes, r13_d1_el_ms, r13_d1_el_pub_ms],
		"oa": [r13_d1_oa_tctx.nodes, r13_d1_oa_ms, r13_d1_oa_pub_ms],
	}

	# Group D2: p_e high-hit (hits = 200) vs trap_e (< 16 MiB and < 4 MiB LogBus)
	var r13_seq_h200: Array = []
	for r13_hi: int in range(32):
		var r13_hleaf10: Array = []
		for r13_hli: int in range(10):
			r13_hleaf10.append(70000 + r13_hi * 100 + r13_hli)
		var r13_harr70: Array = [r13_hleaf10, r13_hi]
		for r13_hai: int in range(68):
			r13_harr70.append(r13_hai)
		for _r13_rep: int in range(200):
			r13_seq_h200.append(r13_harr70)
	var r13_trap_70: Array = []
	for _r13_ti: int in range(70):
		r13_trap_70.append(null)
	for _r13_ti: int in range(5000):
		r13_seq_h200.append(r13_trap_70)
	var r13_dict_h200 := {"p": r13_seq_h200}

	var r13_d2_ctx_v := {"nodes": 0}
	r13_t0 = Time.get_ticks_msec()
	var r13_d2_v_ok: bool = adapter.is_valid_state_data(r13_dict_h200, 3, [], 32, r13_d2_ctx_v)
	var r13_d2_v_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_d2_ctx_b := {"nodes": 0}
	r13_t0 = Time.get_ticks_msec()
	var r13_d2_b_est: int = adapter.bounded_variant_size_estimate(r13_dict_h200, 0, [], 24 * 1024 * 1024, 128, r13_d2_ctx_b)
	var r13_d2_b_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_d2_adp_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_d2_adp_node: Variant = dag_cloner.safe_clone_node(r13_dict_h200, 0, [], r13_d2_adp_tctx)
	var r13_d2_adp_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_d2_reg_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_d2_reg_node: Variant = dag_cloner.safe_clone_node(r13_dict_h200, 0, [], r13_d2_reg_tctx)
	var r13_d2_reg_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_d2_el_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_d2_el_node: Variant = dag_cloner.safe_clone_node(r13_dict_h200, 0, [], r13_d2_el_tctx)
	var r13_d2_el_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_d2_oa_tctx = dag_cloner.DagTravCtx.new()
	r13_t0 = Time.get_ticks_msec()
	var r13_d2_oa_node: Variant = dag_cloner.safe_clone_node(r13_dict_h200, 0, [], r13_d2_oa_tctx)
	var r13_d2_oa_ms: int = Time.get_ticks_msec() - r13_t0

	var r13_seq_h40_bus: Array = []
	for r13_bi: int in range(32):
		var r13_bleaf10: Array = []
		for r13_bli: int in range(10):
			r13_bleaf10.append(80000 + r13_bi * 100 + r13_bli)
		var r13_barr65: Array = [r13_bleaf10, r13_bi]
		for r13_bai: int in range(63):
			r13_barr65.append(r13_bai)
		for _r13_rep: int in range(40):
			r13_seq_h40_bus.append(r13_barr65)
	var r13_trap_65: Array = []
	for _r13_ti: int in range(65):
		r13_trap_65.append(null)
	for _r13_ti: int in range(3000):
		r13_seq_h40_bus.append(r13_trap_65)
	var r13_dict_h40_bus := {"p": r13_seq_h40_bus}
	r13_t0 = Time.get_ticks_msec()
	var r13_d2_bus_pub: Dictionary = st_bus.info("s", "r13_h40", r13_dict_h40_bus)
	var r13_d2_bus_pub_ms: int = Time.get_ticks_msec() - r13_t0
	var r13_d2_bus_tctx = dag_cloner.DagTravCtx.new()
	r13_d2_bus_tctx.max_bytes = 4 * 1024 * 1024
	r13_t0 = Time.get_ticks_msec()
	var r13_d2_bus_node: Variant = dag_cloner.safe_clone_node(r13_dict_h40_bus, 0, [], r13_d2_bus_tctx)
	var r13_d2_bus_ms: int = Time.get_ticks_msec() - r13_t0

	r13["group_d_high_hit_200_ok"] = (
		r13_d2_v_ok and int(r13_d2_ctx_v.get("nodes", 999999)) < 100000 and r13_d2_v_ms < 200
		and r13_d2_b_est > 0 and int(r13_d2_ctx_b.get("nodes", 999999)) < 100000 and r13_d2_b_ms < 200
		and not r13_d2_adp_tctx.aborted and r13_d2_adp_tctx.nodes < 100000 and r13_d2_adp_ms < 200 and r13_d2_adp_node is Dictionary and (r13_d2_adp_node.get("p", []) as Array).size() == 11400
		and not r13_d2_reg_tctx.aborted and r13_d2_reg_tctx.nodes < 100000 and r13_d2_reg_ms < 200 and r13_d2_reg_node is Dictionary and (r13_d2_reg_node.get("p", []) as Array).size() == 11400
		and not r13_d2_el_tctx.aborted and r13_d2_el_tctx.nodes < 100000 and r13_d2_el_ms < 200 and r13_d2_el_node is Dictionary and (r13_d2_el_node.get("p", []) as Array).size() == 11400
		and not r13_d2_oa_tctx.aborted and r13_d2_oa_tctx.nodes < 100000 and r13_d2_oa_ms < 200 and r13_d2_oa_node is Dictionary and (r13_d2_oa_node.get("p", []) as Array).size() == 11400
		and not r13_d2_bus_pub.is_empty() and (r13_d2_bus_pub.get("context", {}).get("p", []) as Array).size() == 4280 and r13_d2_bus_pub_ms < 200
		and not r13_d2_bus_tctx.aborted and r13_d2_bus_tctx.nodes < 100000 and r13_d2_bus_ms < 200 and r13_d2_bus_node is Dictionary and (r13_d2_bus_node.get("p", []) as Array).size() == 4280
	)
	r13["group_d_hit200_debug"] = {
		"v": [r13_d2_v_ok, int(r13_d2_ctx_v.get("nodes", -1)), r13_d2_v_ms],
		"b": [r13_d2_b_est, int(r13_d2_ctx_b.get("nodes", -1)), r13_d2_b_ms],
		"adp": [r13_d2_adp_tctx.nodes, r13_d2_adp_ms],
		"reg": [r13_d2_reg_tctx.nodes, r13_d2_reg_ms],
		"el": [r13_d2_el_tctx.nodes, r13_d2_el_ms],
		"oa": [r13_d2_oa_tctx.nodes, r13_d2_oa_ms],
		"bus": [r13_d2_bus_tctx.nodes, r13_d2_bus_ms, r13_d2_bus_pub_ms],
	}

	# Group D3: < 4 MiB / < 16 MiB clipped_dict_buckets & clipped_arr_buckets > 128 ghost eviction across all 5 scripts
	var r13_clip_dict_row: Array = []
	for r13_ci: int in range(32):
		var r13_sub80: Array = []
		for r13_si: int in range(80):
			r13_sub80.append(r13_ci * 100 + r13_si)
		var r13_cd: Dictionary = {"_d": _make_deep_dict(14, {"x": 1}), "sub": r13_sub80}
		for r13_ki: int in range(15):
			r13_cd["k%d" % r13_ki] = r13_ki
		r13_clip_dict_row.append(r13_cd)
		r13_clip_dict_row.append(r13_cd)
	var r13_clip_dict_trap: Dictionary = {"_d": _make_deep_dict(14, {"x": 1})}
	var r13_sub55: Array = []
	for r13_si: int in range(55):
		r13_sub55.append(r13_si)
	r13_clip_dict_trap["sub"] = r13_sub55
	for r13_ki: int in range(15):
		r13_clip_dict_trap["k%d" % r13_ki] = r13_ki
	for _r13_ti: int in range(5):
		r13_clip_dict_row.append(r13_clip_dict_trap)
	for r13_jk: int in range(140):
		var r13_sub65: Array = []
		for r13_si: int in range(65):
			r13_sub65.append(r13_jk * 100 + r13_si)
		var r13_cj: Dictionary = {"_d": _make_deep_dict(14, {"x": 1}), "sub": r13_sub65}
		for r13_ki: int in range(15):
			r13_cj["k%d" % r13_ki] = r13_ki
		r13_clip_dict_row.append(r13_cj)
		r13_clip_dict_row.append(r13_clip_dict_trap)
	for _r13_ti: int in range(1355):
		r13_clip_dict_row.append(r13_clip_dict_trap)
	var r13_payload_clip_dict: Dictionary = _make_deep_dict(18, r13_clip_dict_row)

	var r13_clip_arr_row: Array = []
	for r13_ci: int in range(32):
		var r13_asub80: Array = []
		for r13_si: int in range(80):
			r13_asub80.append(r13_ci * 100 + r13_si)
		var r13_ca: Array = [_make_deep_dict(14, {"x": 1}), r13_asub80]
		for r13_ki: int in range(15):
			r13_ca.append(r13_ki)
		r13_clip_arr_row.append(r13_ca)
		r13_clip_arr_row.append(r13_ca)
	var r13_clip_arr_trap: Array = [_make_deep_dict(14, {"x": 1}), r13_sub55]
	for r13_ki: int in range(15):
		r13_clip_arr_trap.append(r13_ki)
	for _r13_ti: int in range(5):
		r13_clip_arr_row.append(r13_clip_arr_trap)
	for r13_jk: int in range(140):
		var r13_asub65: Array = []
		for r13_si: int in range(65):
			r13_asub65.append(r13_jk * 100 + r13_si)
		var r13_caj: Array = [_make_deep_dict(14, {"x": 1}), r13_asub65]
		for r13_ki: int in range(15):
			r13_caj.append(r13_ki)
		r13_clip_arr_row.append(r13_caj)
		r13_clip_arr_row.append(r13_clip_arr_trap)
	for _r13_ti: int in range(1355):
		r13_clip_arr_row.append(r13_clip_arr_trap)
	var r13_payload_clip_arr: Dictionary = _make_deep_dict(18, r13_clip_arr_row)

	var r13_d3_ok: bool = true
	var r13_d3_debug := {}
	var r13_d3_targets: Array = [
		["adp_clone", adapter, false, 16 * 1024 * 1024],
		["adp_san", adapter, true, 16 * 1024 * 1024],
		["bus", st_bus, false, 4 * 1024 * 1024],
		["reg", st_reg, false, 16 * 1024 * 1024],
		["el", st_el, false, 16 * 1024 * 1024],
		["oa", st_oa, false, 16 * 1024 * 1024],
	]
	for r13_ent_spec: Variant in r13_d3_targets:
		var r13_spec: Array = r13_ent_spec as Array
		var r13_lbl: String = str(r13_spec[0])
		var r13_obj: RefCounted = r13_spec[1] as RefCounted
		var r13_is_san: bool = bool(r13_spec[2])
		var r13_max_b: int = int(r13_spec[3])
		var r13_td = dag_cloner.DagTravCtx.new()
		r13_td.max_bytes = r13_max_b
		r13_t0 = Time.get_ticks_msec()
		var r13_od: Variant = r13_obj._sanitize_module_node(r13_payload_clip_dict, 0, [], r13_td) if r13_is_san else dag_cloner.safe_clone_node(r13_payload_clip_dict, 0, [], r13_td)
		var r13_ms_d: int = Time.get_ticks_msec() - r13_t0
		var r13_md_d := _measure_depth_and_check_empty_32(r13_od)

		var r13_ta = dag_cloner.DagTravCtx.new()
		r13_ta.max_bytes = r13_max_b
		r13_t0 = Time.get_ticks_msec()
		var r13_oa: Variant = r13_obj._sanitize_module_node(r13_payload_clip_arr, 0, [], r13_ta) if r13_is_san else dag_cloner.safe_clone_node(r13_payload_clip_arr, 0, [], r13_ta)
		var r13_ms_a: int = Time.get_ticks_msec() - r13_t0
		var r13_md_a := _measure_depth_and_check_empty_32(r13_oa)

		var r13_row_ok: bool = (
			not r13_td.aborted and r13_td.nodes < 100000 and r13_ms_d < 200
			and not r13_td.clipped_dict_buckets.is_empty()
			and int(r13_md_d["max_depth"]) == 32 and not bool(r13_md_d["non_empty_at_32"])
			and not r13_ta.aborted and r13_ta.nodes < 100000 and r13_ms_a < 200
			and not r13_ta.clipped_arr_buckets.is_empty()
			and int(r13_md_a["max_depth"]) == 32 and not bool(r13_md_a["non_empty_at_32"])
		)
		if not r13_row_ok:
			r13_d3_ok = false
		r13_d3_debug[r13_lbl] = {
			"d": [r13_td.aborted, r13_td.nodes, r13_ms_d, r13_td.clipped_dict_buckets.size(), r13_md_d["max_depth"], r13_md_d["non_empty_at_32"]],
			"a": [r13_ta.aborted, r13_ta.nodes, r13_ms_a, r13_ta.clipped_arr_buckets.size(), r13_md_a["max_depth"], r13_md_a["non_empty_at_32"]],
		}

	# Public wrapper checks for clipped payloads
	r13_t0 = Time.get_ticks_msec()
	var r13_d3_bus_pub: Dictionary = st_bus.info("s", "r13_cd", r13_payload_clip_dict)
	var r13_d3_bus_pub_ms: int = Time.get_ticks_msec() - r13_t0
	r13_t0 = Time.get_ticks_msec()
	var r13_d3_reg_pub_ok: bool = st_reg.probe_feature_manager({"rows": [], "campaign_blockers": [r13_payload_clip_arr]})
	var r13_d3_reg_rep: Dictionary = st_reg.get_last_probe_report()
	var r13_d3_reg_pub_ms: int = Time.get_ticks_msec() - r13_t0
	r13_t0 = Time.get_ticks_msec()
	var r13_d3_el_pub: Dictionary = st_el.build_template_data("r13_cd", "R13CD", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", r13_payload_clip_dict)
	var r13_d3_el_pub_ms: int = Time.get_ticks_msec() - r13_t0
	r13_t0 = Time.get_ticks_msec()
	var r13_d3_oa_pub: Dictionary = st_oa.make_obstacle_state("object", "manual", 64.0, r13_payload_clip_arr, {})
	var r13_d3_oa_pub_ms: int = Time.get_ticks_msec() - r13_t0
	if (
		r13_d3_bus_pub.is_empty() or r13_d3_bus_pub_ms >= 200
		or not r13_d3_reg_pub_ok or r13_d3_reg_rep.get("campaign_blockers", []).is_empty() or r13_d3_reg_pub_ms >= 200
		or r13_d3_el_pub.get("components", {}).is_empty() or r13_d3_el_pub_ms >= 200
		or r13_d3_oa_pub.get("shape", {}).is_empty() or r13_d3_oa_pub_ms >= 200
	):
		r13_d3_ok = false

	# VALID_0HIT_GHOST141_WRAP (Explorer 2): 32 1-shot 0-hit heavy junks + 141 cyclic containers across 75 rounds (valid) & 60 rounds (clipped/unclipped)
	var r13_wrap_junks: Array = []
	for r13_wi: int in range(32):
		var r13_wleaf15: Array = []
		for r13_wli: int in range(15):
			r13_wleaf15.append(91000 + r13_wi * 100 + r13_wli)
		var r13_wj: Array = [r13_wleaf15, r13_wi]
		for r13_wai: int in range(198):
			r13_wj.append(r13_wai)
		r13_wrap_junks.append(r13_wj)
	var r13_pool141: Array = []
	for r13_pi: int in range(141):
		var r13_p141: Array = [[[r13_pi]]]
		for _r13_pai: int in range(199):
			r13_p141.append(null)
		r13_pool141.append(r13_p141)
	var r13_wrap_75: Array = r13_wrap_junks.duplicate()
	for _r13_rnd: int in range(75):
		for r13_p141_item: Variant in r13_pool141:
			r13_wrap_75.append(r13_p141_item)
	var r13_wrap_60: Array = r13_wrap_junks.duplicate()
	for _r13_rnd: int in range(60):
		for r13_p141_item: Variant in r13_pool141:
			r13_wrap_60.append(r13_p141_item)

	var r13_vctx_wrap := {"nodes": 0}
	var r13_wrap_valid_ok: bool = adapter.is_valid_state_data({"p": r13_wrap_75}, 3, [], 32, r13_vctx_wrap)
	var r13_wrap_unclip_tctx = dag_cloner.DagTravCtx.new()
	var r13_wrap_unclip_out: Variant = dag_cloner.safe_clone_node({"p": r13_wrap_60}, 0, [], r13_wrap_unclip_tctx)
	var r13_wrap_clip_tctx = dag_cloner.DagTravCtx.new()
	var r13_wrap_clip_out: Variant = dag_cloner.safe_clone_node(_make_deep_dict(29, r13_wrap_60), 0, [], r13_wrap_clip_tctx)
	var r13_wrap_ok: bool = (
		r13_wrap_valid_ok and int(r13_vctx_wrap.get("nodes", 9999999)) < 1900000
		and not r13_wrap_unclip_tctx.aborted and r13_wrap_unclip_out is Dictionary and r13_wrap_unclip_tctx.nodes < 1550000
		and not r13_wrap_clip_tctx.aborted and r13_wrap_clip_out is Dictionary and not r13_wrap_clip_tctx.clipped_arr_buckets.is_empty() and r13_wrap_clip_tctx.nodes < 1550000
	)
	if not r13_wrap_ok:
		r13_d3_ok = false
	r13_d3_debug["wrap141"] = {
		"valid": r13_wrap_valid_ok, "v_nodes": int(r13_vctx_wrap.get("nodes", -1)),
		"unclip": [r13_wrap_unclip_tctx.aborted, r13_wrap_unclip_tctx.nodes],
		"clip": [r13_wrap_clip_tctx.aborted, r13_wrap_clip_tctx.nodes, r13_wrap_clip_tctx.clipped_arr_buckets.size()],
	}

	r13["group_d_clipped_128_ok"] = r13_d3_ok
	r13["group_d_clipped_debug"] = r13_d3_debug

	# Group E: ghost/ghost_prob sync over >128 overflow + 1000-step randomized mixed-height stress + zero-leak checks across all traversal paths + sibling cleanup
	var r13_e_ok: bool = true
	var r13_e_fails: Array = []
	var r13_all5_objs: Array = [
		["dag_cloner", dag_cloner],
	]
	for r13_item: Variant in r13_all5_objs:
		var r13_pair: Array = r13_item as Array
		var r13_nm: String = str(r13_pair[0])
		var r13_o: Variant = r13_pair[1]

		# Overflow 200 distinct sz=50 entries (>128) + re-insert 20 ghost-resident refs
		var r13_gtctx = r13_o.DagTravCtx.new()
		var r13_pool200: Array = []
		for r13_gi: int in range(200):
			var r13_gobj := [r13_gi]
			r13_pool200.append(r13_gobj)
			r13_o.memo_store_in_buckets(r13_gtctx, r13_gtctx.arr_buckets, 50, r13_gobj, 2 + (r13_gi % 5), 64, 24, r13_gobj, 24 + (r13_gi % 17))
			var r13_gb = r13_gtctx.arr_buckets[50]
			var r13_f1: Array = _r13_check_ghost_invariants(r13_gb, 128, 128)
			if not r13_f1.is_empty():
				r13_e_ok = false
				r13_e_fails.append(r13_nm + "_ovf:" + str(r13_f1[0]))
				break
		var r13_gb_ovf = r13_gtctx.arr_buckets[50]
		if (r13_gb_ovf.ghost as Array).size() != 128:
			r13_e_ok = false
			r13_e_fails.append(r13_nm + "_ovf_sz:%d" % (r13_gb_ovf.ghost as Array).size())
		var r13_reins: Array = []
		for r13_ri: int in range(mini(20, (r13_gb_ovf.ghost as Array).size())):
			r13_reins.append([r13_gb_ovf.ghost[r13_ri], int(r13_gb_ovf.ghost_h[r13_ri])])
		for r13_rp_v: Variant in r13_reins:
			var r13_rp: Array = r13_rp_v as Array
			r13_o.memo_store_in_buckets(r13_gtctx, r13_gtctx.arr_buckets, 50, r13_rp[0], int(r13_rp[1]), 64, 24, r13_rp[0], 30)
			var r13_f2: Array = _r13_check_ghost_invariants(r13_gb_ovf, 128, 128)
			if not r13_f2.is_empty():
				r13_e_ok = false
				r13_e_fails.append(r13_nm + "_reins:" + str(r13_f2[0]))
				break

		# 1000-step deterministic LCG mixed-height (1..17) stress (pool = 250)
		var r13_stctx = r13_o.DagTravCtx.new()
		var r13_pool250: Array = []
		var r13_pool250_h: Array = []
		for r13_pi: int in range(250):
			r13_pool250.append([r13_pi])
			r13_pool250_h.append(1 + (r13_pi % 17))
		var r13_lcg: int = 1234567
		for r13_step: int in range(1000):
			r13_lcg = (r13_lcg * 1103515245 + 12345) & 0x7fffffff
			var r13_idx: int = r13_lcg % 250
			var r13_target: Variant = r13_pool250[r13_idx]
			var r13_ht: int = int(r13_pool250_h[r13_idx])
			var r13_hit = r13_o.memo_find_in_buckets(r13_stctx, r13_stctx.arr_buckets, 60, r13_target)
			if r13_hit == null:
				r13_o.memo_store_in_buckets(r13_stctx, r13_stctx.arr_buckets, 60, r13_target, r13_ht, 64, 24, r13_target, 24 + (r13_lcg % 100))
			var r13_sb = r13_stctx.arr_buckets[60]
			var r13_f3: Array = _r13_check_ghost_invariants(r13_sb, 128, 128)
			if not r13_f3.is_empty():
				r13_e_ok = false
				r13_e_fails.append(r13_nm + "_lcg_%d:%s" % [r13_step, str(r13_f3[0])])
				break
		var r13_sb_end = r13_stctx.arr_buckets[60]
		if (r13_sb_end.ghost as Array).size() != 128:
			r13_e_ok = false
			r13_e_fails.append(r13_nm + "_lcg_sz:%d" % (r13_sb_end.ghost as Array).size())

		# Dedicated ghost_prob 128-entry hits > 0 saturation check (0-hit push must not evict hits > 0)
		var r13_gp_b = r13_o.DagMemoBucket.new()
		var r13_gp_pos_pool: Array = []
		for r13_gpi: int in range(128):
			var r13_gpobj := ["gp_pos", r13_gpi]
			r13_gp_pos_pool.append(r13_gpobj)
			r13_o.memo_push_ghost_prob(r13_gp_b, r13_gpobj, 2 + (r13_gpi % 5), 1 + (r13_gpi % 3))
			var r13_f_gp0: Array = _r13_check_ghost_invariants(r13_gp_b, 128, 128)
			if not r13_f_gp0.is_empty():
				r13_e_ok = false
				r13_e_fails.append(r13_nm + "_gp_fill:%s" % str(r13_f_gp0[0]))
				break
		if (r13_gp_b.ghost_prob as Array).size() != 128 or int(r13_gp_b.ghost_prob_zero_cnt) != 0:
			r13_e_ok = false
			r13_e_fails.append(r13_nm + "_gp_sat_cnt:%d:%d" % [(r13_gp_b.ghost_prob as Array).size(), int(r13_gp_b.ghost_prob_zero_cnt)])
		var r13_gp_zero := ["gp_zero_should_skip"]
		r13_o.memo_push_ghost_prob(r13_gp_b, r13_gp_zero, 3, 0)
		var r13_f_gp1: Array = _r13_check_ghost_invariants(r13_gp_b, 128, 128)
		if not r13_f_gp1.is_empty():
			r13_e_ok = false
			r13_e_fails.append(r13_nm + "_gp_zero_inv:%s" % str(r13_f_gp1[0]))
		for r13_gpk: int in range(128):
			var r13_kept: bool = false
			for r13_cur_gp: Variant in (r13_gp_b.ghost_prob as Array):
				if is_same(r13_cur_gp, r13_gp_pos_pool[r13_gpk]):
					r13_kept = true
					break
			if not r13_kept:
				r13_e_ok = false
				r13_e_fails.append(r13_nm + "_gp_zero_evicted:%d" % r13_gpk)
				break
		for r13_cur_gp2: Variant in (r13_gp_b.ghost_prob as Array):
			if is_same(r13_cur_gp2, r13_gp_zero):
				r13_e_ok = false
				r13_e_fails.append(r13_nm + "_gp_zero_inserted")
				break
		var r13_gp_hits_pushes: Array = [
			[["gp_hit1"], 3, 1],
			[["gp_hit2"], 4, 2],
			[["gp_hit5"], 2, 5],
		]
		for r13_hp_item: Variant in r13_gp_hits_pushes:
			var r13_hp_arr: Array = r13_hp_item as Array
			r13_o.memo_push_ghost_prob(r13_gp_b, r13_hp_arr[0], int(r13_hp_arr[1]), int(r13_hp_arr[2]))
			var r13_f_gp2: Array = _r13_check_ghost_invariants(r13_gp_b, 128, 128)
			if not r13_f_gp2.is_empty():
				r13_e_ok = false
				r13_e_fails.append(r13_nm + "_gp_pos_inv:%s" % str(r13_f_gp2[0]))
				break
		var r13_gp_zero2 := ["gp_zero_after_pos"]
		r13_o.memo_push_ghost_prob(r13_gp_b, r13_gp_zero2, 4, 0)
		var r13_f_gp3: Array = _r13_check_ghost_invariants(r13_gp_b, 128, 128)
		if not r13_f_gp3.is_empty():
			r13_e_ok = false
			r13_e_fails.append(r13_nm + "_gp_zero2_inv:%s" % str(r13_f_gp3[0]))
		for r13_cur_gp3: Variant in (r13_gp_b.ghost_prob as Array):
			if is_same(r13_cur_gp3, r13_gp_zero2):
				r13_e_ok = false
				r13_e_fails.append(r13_nm + "_gp_zero2_inserted")
				break

	# Zero-leak check across shared DagCloner + adapter traversal modes
	var r13_cyc_d := {"a": 1}
	r13_cyc_d["self"] = r13_cyc_d
	var r13_cyc_a := [1]
	r13_cyc_a.append(r13_cyc_a)
	var r13_nonscalar_k := {}
	r13_nonscalar_k[[1, 2]] = {"nested": [1, 2, 3, 4]}

	var r13_leak_paths: Array = [
		["dag_clone", dag_cloner, 0],
		["adp_san", adapter, 1],
		["adp_val", adapter, 2],
		["adp_est", adapter, 3],
	]
	for r13_lp_v: Variant in r13_leak_paths:
		var r13_lp: Array = r13_lp_v as Array
		var r13_pnm: String = str(r13_lp[0])
		var r13_po: Variant = r13_lp[1]
		var r13_pmode: int = int(r13_lp[2])
		var r13_cases: Array = [
			["norm", r13_dict_h, 2097152, 16 * 1024 * 1024],
			["node_abort", r13_dict_h, 25, 16 * 1024 * 1024],
			["byte_abort", r13_dict_h, 2097152, 200],
			["nonscalar_n", r13_nonscalar_k, 3, 16 * 1024 * 1024],
			["nonscalar_b", r13_nonscalar_k, 2097152, 40],
			["cyc_d", r13_cyc_d, 2097152, 16 * 1024 * 1024],
			["cyc_a", r13_cyc_a, 2097152, 16 * 1024 * 1024],
		]
		for r13_cs_v: Variant in r13_cases:
			var r13_cs: Array = r13_cs_v as Array
			var r13_cnm: String = str(r13_cs[0])
			var r13_cval: Variant = r13_cs[1]
			var r13_lt = dag_cloner.DagTravCtx.new()
			r13_lt.max_nodes = int(r13_cs[2])
			r13_lt.max_bytes = int(r13_cs[3])
			if r13_pmode == 0:
				dag_cloner.safe_clone_node(r13_cval, 0, [], r13_lt)
			elif r13_pmode == 1:
				r13_po._sanitize_module_node(r13_cval, 0, [], r13_lt)
			elif r13_pmode == 2:
				r13_po._validate_state_data_height(r13_cval, 0, [], 32, r13_lt)
			else:
				r13_po._bounded_variant_size_node(r13_cval, 0, [], 32, r13_lt)
			if not r13_lt.live_frames.is_empty() or not r13_lt.active_frames.is_empty():
				r13_e_ok = false
				r13_e_fails.append(r13_pnm + "_" + r13_cnm + "_leak")

	# Sibling cleanup checks: ctx["_trav_ctx"] cross-mode guard + 6 replaced .duplicate(true) getters
	var r13_shared_ctx := {"nodes": 0}
	var r13_sc_v_ok: bool = adapter.is_valid_state_data(r13_dict_e_10500, 3, [], 32, r13_shared_ctx)
	r13_shared_ctx["nodes"] = 0
	var r13_sc_est: int = adapter.bounded_variant_size_estimate(r13_dict_e_10500, 0, [], 24 * 1024 * 1024, 128, r13_shared_ctx)
	if not r13_sc_v_ok or r13_sc_est <= 8000000:
		r13_e_ok = false
		r13_e_fails.append("ctx_cross_mode:%s:%d" % [str(r13_sc_v_ok), r13_sc_est])

	var r13_wb_sib = sdk.create_world_builder(sdk.create_session(MockHost.new(), {}), 150.0)
	r13_wb_sib.get_logger().set_emit_to_engine(false)
	var r13_fuid_sib: String = r13_wb_sib.get_active_floor_uid()
	var r13_luid_sib: String = r13_wb_sib.get_layer_uid("entity", r13_fuid_sib)
	r13_wb_sib.floor_system().set_player_floor_visits("p1", [r13_fuid_sib])
	var r13_fl_copy: Array = r13_wb_sib.floor_system().get_floors()
	if not r13_fl_copy.is_empty():
		(r13_fl_copy[0] as Dictionary)["name"] = "MUTATED_FLOOR"
	var r13_fl_one: Dictionary = r13_wb_sib.floor_system().get_floor(r13_fuid_sib)
	if str(r13_fl_one.get("name", "")) == "MUTATED_FLOOR":
		r13_e_ok = false
		r13_e_fails.append("get_floors_not_isolated")
	r13_fl_one["name"] = "MUTATED_ONE"
	if str(r13_wb_sib.floor_system().get_floor(r13_fuid_sib).get("name", "")) == "MUTATED_ONE":
		r13_e_ok = false
		r13_e_fails.append("get_floor_not_isolated")
	var r13_vis_copy: Array = r13_wb_sib.floor_system().get_player_floor_visits("p1")
	r13_vis_copy.append("MUTATED_VISIT")
	if r13_wb_sib.floor_system().get_player_floor_visits("p1").size() != 1:
		r13_e_ok = false
		r13_e_fails.append("get_visits_not_isolated")
	var r13_ly_copy: Dictionary = r13_wb_sib.layer_stack().get_layer(r13_luid_sib)
	r13_ly_copy["name"] = "MUTATED_LAYER"
	if str(r13_wb_sib.layer_stack().get_layer(r13_luid_sib).get("name", "")) == "MUTATED_LAYER":
		r13_e_ok = false
		r13_e_fails.append("get_layer_not_isolated")
	var r13_fls_copy: Array = adapter.get_floor_layers(r13_wb_sib.get_world(), r13_fuid_sib)
	if not r13_fls_copy.is_empty():
		(r13_fls_copy[0] as Dictionary)["name"] = "MUTATED_ADAPTER_LAYER"
	if str(r13_wb_sib.layer_stack().get_layer(r13_luid_sib).get("name", "")) == "MUTATED_ADAPTER_LAYER":
		r13_e_ok = false
		r13_e_fails.append("get_floor_layers_not_isolated")
	var r13_sib_w: Dictionary = r13_wb_sib.get_world()
	var r13_sc_init: Dictionary = adapter.ensure_scene_repository_state(r13_sib_w, "Scene 1", "", "")
	var r13_sc_uid: String = str(r13_sc_init.get("entry_scene_uid", ""))
	var r13_sc_rec: Dictionary = adapter.get_scene_record(r13_sib_w, r13_sc_uid)
	r13_sc_rec["name"] = "MUTATED_SCENE"
	if str(adapter.get_scene_record(r13_sib_w, r13_sc_uid).get("name", "")) == "MUTATED_SCENE" or str(adapter.get_scene_record(r13_sib_w, r13_sc_uid).get("name", "")) != "Scene 1":
		r13_e_ok = false
		r13_e_fails.append("get_scene_record_not_isolated")

	r13["group_e_ghost_sync_and_zero_leak_ok"] = r13_e_ok
	r13["group_e_debug"] = r13_e_fails
	results["r13_hardening"] = r13

	# 14. Direct unit tests for utils/{dag_cloner,bounded_cloner,value_utils,validation_utils}.gd
	var ures := {}

	# 14a. dag_cloner.gd: 4 MiB vs 16 MiB budget, validated dict initial_depth, packed cost, DagTravCtx mode
	var mid_bytes := PackedByteArray()
	mid_bytes.resize(5 * 1024 * 1024)
	mid_bytes.fill(0x41)
	var mid_payload := {"blob": mid_bytes}
	var bus_over_4mb: Dictionary = st_bus.info("u_4mb", "msg", mid_payload)
	var bus_ctx_over: Dictionary = bus_over_4mb.get("context", {}) as Dictionary
	var adp_under_16mb: Dictionary = adapter._safe_clone_dict(mid_payload)
	var val_d_ok: Dictionary = dag_cloner.safe_clone_validated_dict({"a": [1, 2]}, 16 * 1024 * 1024, 3)
	var val_d_bytes_fail: Dictionary = dag_cloner.safe_clone_validated_dict(mid_payload, 1024 * 1024, 3)
	var val_d_clipped: Dictionary = dag_cloner.safe_clone_validated_dict(_make_deep_dict(31, {"z": 1}), 16 * 1024 * 1024, 3)
	var dctx_mode = dag_cloner.DagTravCtx.new()
	dctx_mode.mode = "custom"
	dctx_mode.limit_exceeded = true
	ures["dag_cloner_ok"] = (
		not bus_over_4mb.is_empty() and bus_ctx_over.is_empty()
		and adp_under_16mb.has("blob") and (adp_under_16mb["blob"] as PackedByteArray).size() == 5 * 1024 * 1024
		and bool(val_d_ok.get("ok", false))
		and ((val_d_ok.get("dict", {}) as Dictionary).get("a", []) as Array) == [1, 2]
		and not bool(val_d_bytes_fail.get("ok", true))
		and bool(val_d_clipped.get("ok", false))
		and dag_cloner.packed_array_byte_cost(PackedInt32Array([1, 2, 3]), -1) == 28
		and dag_cloner.packed_array_byte_cost(PackedInt32Array([1, 2, 3]), 20) == -1
		and dctx_mode.mode == "custom" and dctx_mode.limit_exceeded
	)

	# 14b. bounded_cloner.gd: fallback, simple unmemoized (dag24 + zero null-synth), dnd cycle/keys, fog overrides
	var fb_src_packed := PackedByteArray([1, 2, 3])
	var fb_nonscalar_k := {}
	fb_nonscalar_k[{"k": 1}] = "skip"
	fb_nonscalar_k["ok"] = fb_src_packed
	var fb_cloned: Dictionary = bounded_cloner.bounded_fallback_clone(fb_nonscalar_k, 0, [], [16384, false]) as Dictionary
	var fb_packed_isolated: bool = false
	if fb_cloned.get("ok") is PackedByteArray:
		var cp_b: PackedByteArray = fb_cloned["ok"] as PackedByteArray
		cp_b[0] = 99
		fb_packed_isolated = fb_src_packed[0] == 1
	var smp_dag24 := {"leaf": 1}
	for _s_i: int in range(24):
		smp_dag24 = {"l": smp_dag24, "r": smp_dag24}
	var smp_budget := [32768, false]
	var _smp_res: Dictionary = bounded_cloner.simple_clone_dict(smp_dag24, 0, [], smp_budget, false)
	var smp_valid_null: Dictionary = bounded_cloner.simple_clone_dict({"n": null, "k": 2}, 0, [], [4096, false], false)
	var smp_packed_arr := PackedInt32Array([7, 8])
	var smp_no_dup: Variant = bounded_cloner.simple_clone_var(smp_packed_arr, 0, [], [4096, false], false)
	var smp_with_dup: Variant = bounded_cloner.simple_clone_var(smp_packed_arr, 0, [], [4096, false], true)
	var smp_dup_isolated: bool = false
	if smp_with_dup is PackedInt32Array:
		var cp_i32: PackedInt32Array = smp_with_dup as PackedInt32Array
		cp_i32[0] = 999
		smp_dup_isolated = smp_packed_arr[0] == 7 and is_same(smp_no_dup, smp_packed_arr)
	var dnd_cyc_val := {}
	dnd_cyc_val["self"] = dnd_cyc_val
	var dnd_cyc_map := {}
	dnd_cyc_map["cyc"] = dnd_cyc_val
	var dnd_nested_map := {}
	dnd_nested_map[{"nk": [1, 2]}] = {"nv": 3}
	var dnd_cloned_nested: Dictionary = bounded_cloner.dnd_clone_dict(dnd_nested_map)
	var fog_ok: Dictionary = bounded_cloner.clone_fog_overrides({"a": [1, PackedByteArray([5, 6])]})
	var fog_bad_key: Dictionary = bounded_cloner.clone_fog_overrides({123: "bad"})
	var fog_deep: Dictionary = bounded_cloner.clone_fog_overrides(_make_deep_dict(33, {"x": 1}))
	var fog_budget_zero: Dictionary = bounded_cloner.clone_fog_overrides({"a": 1}, 0, [], [0])
	var fog_cyc := {}
	fog_cyc["self"] = fog_cyc
	var fog_cyc_res: Dictionary = bounded_cloner.clone_fog_overrides(fog_cyc)
	ures["bounded_cloner_ok"] = (
		fb_cloned.size() == 1 and fb_cloned.has("ok") and fb_packed_isolated
		and bool(smp_budget[1]) and int(smp_budget[0]) <= 0
		and smp_valid_null.has("n") and smp_valid_null["n"] == null and int(smp_valid_null.get("k", 0)) == 2
		and smp_dup_isolated
		and bounded_cloner.has_cycle(dnd_cyc_map)
		and not bounded_cloner.has_cycle(dnd_nested_map)
		and dnd_cloned_nested.size() == 1
		and bool(fog_ok.get("ok", false))
		and str(fog_bad_key.get("reason", "")) == "unknown_fog_config_key_type"
		and str(fog_deep.get("reason", "")) == "fog_config_too_deep"
		and str(fog_budget_zero.get("reason", "")) == "fog_config_too_large"
		and str(fog_cyc_res.get("reason", "")) == "invalid_fog_config_cycle"
	)

	# 14c. value_utils.gd: parse_int_val, parse_int64_str, coerce_*, color helpers
	var piv_max: Dictionary = value_utils.parse_int_val(9007199254740990.0)
	var piv_min: Dictionary = value_utils.parse_int_val(-9007199254740990.0)
	var piv_int_max: Dictionary = value_utils.parse_int_val(9007199254740991)
	var piv_int_min: Dictionary = value_utils.parse_int_val(-9007199254740991)
	var piv_over: Dictionary = value_utils.parse_int_val(9007199254740992.0)
	var piv_under: Dictionary = value_utils.parse_int_val(-9007199254740992.0)
	var piv_frac: Dictionary = value_utils.parse_int_val(1.5)
	var piv_null: Dictionary = value_utils.parse_int_val(null)
	var piv_nan: Dictionary = value_utils.parse_int_val(NAN)
	var piv_inf: Dictionary = value_utils.parse_int_val(INF)
	var piv_str: Dictionary = value_utils.parse_int_val("5")
	var piv_bool: Dictionary = value_utils.parse_int_val(true)
	var i64_min: Variant = value_utils.parse_int64_str("-9223372036854775808")
	var i64_max: Variant = value_utils.parse_int64_str("9223372036854775807")
	var i64_ovf: Variant = value_utils.parse_int64_str("9223372036854775808")
	var cyc_val_d := {}
	cyc_val_d["s"] = cyc_val_d
	var col_arr_ok: Dictionary = value_utils.coerce_color_value([0.5, 0.25, 0.75], Color.BLACK)
	var col_dict_bad: Dictionary = value_utils.coerce_color_value({"r": 1.5, "g": 0.0, "b": 0.0}, Color.RED)
	var col_html_ok: Dictionary = value_utils.coerce_color_value(&"#336699cc", Color.BLACK)
	var col_unclamped: Variant = value_utils.coerce_color_array([1.5, 0.0, 0.0])
	ures["value_utils_ok"] = (
		bool(piv_max["ok"]) and int(piv_max["value"]) == 9007199254740990
		and bool(piv_min["ok"]) and int(piv_min["value"]) == -9007199254740990
		and bool(piv_int_max["ok"]) and int(piv_int_max["value"]) == 9007199254740991
		and bool(piv_int_min["ok"]) and int(piv_int_min["value"]) == -9007199254740991
		and not bool(piv_over["ok"]) and not bool(piv_under["ok"]) and not bool(piv_frac["ok"])
		and not bool(piv_null["ok"]) and not bool(piv_nan["ok"]) and not bool(piv_inf["ok"])
		and not bool(piv_str["ok"]) and not bool(piv_bool["ok"])
		and i64_min != null and int(i64_min) == (-9223372036854775807 - 1)
		and i64_max != null and int(i64_max) == 9223372036854775807
		and i64_ovf == null
		and value_utils.coerce_bool("\ufeffTRUE", false, true)
		and not value_utils.coerce_bool("\ufefftrue", false, false)
		and not value_utils.coerce_bool(NAN, false, true)
		and value_utils.coerce_bool(&"on", false, true)
		and value_utils.coerce_int("  \ufeff42 ", -1, true) == 42
		and value_utils.coerce_int("9223372036854775808", -9, true) == -9
		and value_utils.coerce_int(3.9, 0, false) == 3
		and value_utils.coerce_int(1e30, -99, false) == -99
		and value_utils.coerce_int(-1e30, -99, false) == -99
		and is_equal_approx(value_utils.coerce_float(" \ufeff2.5 ", 0.0, true), 2.5)
		and value_utils.coerce_float(INF, -1.0, true) == -1.0
		and is_nan(value_utils.coerce_float(NAN, 0.0, false))
		and value_utils.coerce_string(&"sn", "fb") == "fb"
		and value_utils.as_str(&"sn", "fb") == "sn"
		and value_utils.as_str({}, "fb") == "fb"
		and value_utils.coerce_str_scalar(cyc_val_d, "safe") == "safe"
		and value_utils.coerce_str_scalar(123, "") == "123"
		and bool(col_arr_ok["ok"]) and (col_arr_ok["color"] as Color).a == 1.0
		and not bool(col_dict_bad["ok"]) and (col_dict_bad["color"] as Color) == Color.RED
		and bool(col_html_ok["ok"])
		and col_unclamped is Array and (col_unclamped as Array).size() == 4 and float((col_unclamped as Array)[0]) == 1.5
		and value_utils.is_hex8_color("#aAbBcC12") and not value_utils.is_hex8_color("#123456")
		and value_utils.is_finite_color(Color(0.5, 0.5, 0.5, 1.0))
		and not value_utils.is_finite_color(Color(NAN, 0.0, 0.0, 1.0))
		and value_utils.is_unit_color(Color(0.1, 0.2, 0.3, 0.4))
		and not value_utils.is_unit_color(Color(1.2, 0.0, 0.0, 1.0))
		and value_utils.clamp_color(Color(1.5, -0.5, 0.5, 1.0), Color.BLACK) == Color(1.0, 0.0, 0.5, 1.0)
		and value_utils.clamp_color(Color(NAN, 0.0, 0.0, 1.0), Color.RED) == Color.RED
	)

	# 14d. validation_utils.gd: hex24/32/64, BOM, NUL, ASCII vs C1 control, tab, component_id, is_unit_host
	var c1_str: String = "x" + String.chr(133) + "y"
	var tab_str: String = "x\ty"
	var unit_ent := {"entity_type": "object", "selectable_in_select_mode": false, "components": [{"script": "res://scenes/entities/components/comp_unit.gd", "parked": false}]}
	var parked_unit_ent := {"entity_type": "object", "selectable_in_select_mode": false, "components": [{"script": "res://scenes/entities/components/comp_unit.gd", "parked": true}]}
	var map_ent := {"entity_type": "map", "selectable_in_select_mode": true, "components": []}
	ures["validation_utils_ok"] = (
		validation_utils.is_valid_hex("ab12", 4, false)
		and not validation_utils.is_valid_hex("AB12", 4, false)
		and validation_utils.is_valid_hex("AB12", 4, true)
		and validation_utils.is_valid_uid("0123456789abcdef0123456789abcdef")
		and not validation_utils.is_valid_uid("0123456789ABCDEF0123456789abcdef")
		and validation_utils.is_valid_hex24("a".repeat(24))
		and not validation_utils.is_valid_hex24("a".repeat(23))
		and validation_utils.is_valid_hex64("f".repeat(64), false)
		and not validation_utils.is_valid_hex64("F".repeat(64), false)
		and validation_utils.is_valid_hex64("F".repeat(64), true)
		and validation_utils.strip_leading_bom("\ufeff\ufeffhi") == "hi"
		and validation_utils.strip_bom_and_edges("  \ufeff  hi \ufeff ") == "hi \ufeff"
		and not validation_utils.has_nul("ab")
		and validation_utils.strip_nul("ab") == "ab"
		and validation_utils.strip_control_and_edges("\ufeff ab ") == "ab"
		and validation_utils.strip_control_and_edges(" \ufeffab ") == "\ufeffab"
		and validation_utils.sanitize_line_text("a\r\nb\r") == "a\nb"
		and not validation_utils.has_control_chars("plain_ok", false)
		and validation_utils.has_control_chars(String.chr(7), false)
		and validation_utils.has_control_chars(String.chr(127), false)
		and not validation_utils.has_control_chars(c1_str, false)
		and validation_utils.has_control_chars(c1_str, true)
		and not validation_utils.has_control_except_tab(tab_str)
		and validation_utils.has_control_except_tab("a\nb")
		and validation_utils.component_id_from_script("res://modules/portal/comp_portal.gd") == "portal"
		and validation_utils.component_id_from_script("res://x/custom.gd") == "custom"
		and validation_utils.is_unit_host(unit_ent)
		and not validation_utils.is_unit_host(parked_unit_ent)
		and not validation_utils.is_unit_host(map_ent)
	)

	# 14e. feature_obstacle_authoring strict lowercase hex64 (cache.key / shape.uid)
	var oa_lower_obs: Dictionary = st_oa.make_obstacle_state("wall", "manual", 64.0, {}, {"key": "a".repeat(64), "paths": [], "segments": PackedVector2Array(), "digest_version": 1})
	var oa_lower_chk: Dictionary = st_oa.validate_obstacle_state(oa_lower_obs)
	var oa_upper_ckey_obs: Dictionary = st_oa.make_obstacle_state("wall", "manual", 64.0, {}, {"key": "A".repeat(64), "paths": [], "segments": PackedVector2Array(), "digest_version": 1})
	var oa_upper_ckey_chk: Dictionary = st_oa.validate_obstacle_state(oa_upper_ckey_obs)
	var oa_upper_uid_obs: Dictionary = st_oa.make_obstacle_state("wall", "manual", 64.0, {}, {})
	var oa_upper_shape: Dictionary = oa_upper_uid_obs["shape"] as Dictionary
	oa_upper_shape["uid"] = str(oa_upper_shape.get("uid", "")).to_upper()
	var oa_upper_uid_chk: Dictionary = st_oa.validate_obstacle_state(oa_upper_uid_obs)
	ures["obstacle_hex64_strict_ok"] = (
		bool(oa_lower_chk.get("ok", false))
		and not bool(oa_upper_ckey_chk.get("ok", true))
		and (oa_upper_ckey_chk.get("errors", []) as Array) == ["invalid_cache_key"]
		and not bool(oa_upper_uid_chk.get("ok", true))
		and (oa_upper_uid_chk.get("errors", []) as Array) == ["invalid_shape_uid"]
	)
	results["utils_unit_tests"] = ures

	_write_json(out_path, {"ok": true, "results": results})
	quit(0)
'''


class TestFuSdkLoggingAndCoreHeadlessGodot(unittest.TestCase):
    """Real headless Godot tests for M1 LogBus, ModuleRegistry, parked/manual, and 5 Core Plugin SDKs."""

    run_dir: Path | None = None
    results: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_WORKSPACE_ROOT)
        godot_bin = cfg.godot_bin
        if godot_bin is None or not godot_bin.is_file():
            raise unittest.SkipTest("GODOT_BIN not configured in .env.local; skipping headless Godot tests")

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.run_dir = TEST_TMP_ROOT / f"fu_sdk_m1_{uuid.uuid4().hex[:10]}"
        probe_dir = cls.run_dir / "probe_proj"
        probe_dir.mkdir(parents=True, exist_ok=True)
        (probe_dir / "project.godot").write_bytes(
            b'config_version=5\n\n[application]\nconfig/name="fu_sdk_m1_test"\n'
        )
        shutil.copytree(SDK_DIR, probe_dir / "shared" / "sdk" / "fu_sdk")
        (probe_dir / "probe.gd").write_bytes(_PROBE_GD.encode("utf-8"))

        out_path = cls.run_dir / "probe_out.json"
        isolated_env = cls.run_dir / "isolated_env"
        isolated_env.mkdir(parents=True, exist_ok=True)
        godot_log = cls.run_dir / "godot.log"
        env = dict(os.environ)
        env["APPDATA"] = str(isolated_env)
        env["LOCALAPPDATA"] = str(isolated_env)
        env["TEMP"] = str(isolated_env)
        env["TMP"] = str(isolated_env)
        env["GODOT_SILENCE_ROOT_WARNING"] = "1"

        proc = subprocess.run(
            [
                str(godot_bin),
                "--headless",
                "--quit",
                "--path",
                str(probe_dir),
                "--log-file",
                str(godot_log),
                "--script",
                "res://probe.gd",
                "--",
                f"--out={out_path}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log_text = godot_log.read_text(encoding="utf-8", errors="replace") if godot_log.is_file() else ""
        log_errors = analyze_godot_logs(log_text, proc.stdout, proc.stderr)
        combined = f"{log_text}\n{proc.stdout}\n{proc.stderr}"
        if "WARNING: Reading less data than requested" in combined:
            log_errors.append("WARNING: Reading less data than requested")
        if proc.returncode != 0 or log_errors:
            redacted = cfg.redact_path(
                f"rc={proc.returncode} errors={log_errors}\n"
                f"stdout={proc.stdout[-1200:]}\nstderr={proc.stderr[-1200:]}"
            )
            raise AssertionError(f"Headless Godot M1 probe failed:\n{redacted}")

        parsed = json.loads(out_path.read_text(encoding="utf-8"))
        if not parsed.get("ok"):
            raise AssertionError(f"M1 probe returned failure: {parsed}")
        cls.results = parsed["results"]

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.run_dir is not None and cls.run_dir.exists():
            shutil.rmtree(cls.run_dir, ignore_errors=True)
        if TEST_TMP_ROOT.exists():
            try:
                if not any(TEST_TMP_ROOT.iterdir()):
                    TEST_TMP_ROOT.rmdir()
            except OSError:
                pass

    def test_log_bus_behavior_and_limits(self) -> None:
        r = self.results["log_bus"]
        self.assertTrue(r["const_levels_ok"])
        self.assertEqual(r["ring_size"], 5)
        self.assertEqual(r["last_seq"], 7)
        self.assertEqual(r["seen_count"], 7)
        self.assertEqual(r["unsub_during_cb_calls"], 1)
        self.assertTrue(r["unsub_tok1"])
        self.assertFalse(r["unsub_tok1_again"])
        self.assertEqual(r["warns_count"], 3)  # w1 (seq 3), e1 (seq 4), w2 (seq 7) remain in 5-slot ring
        self.assertEqual(r["entries_since_5"], 2)
        self.assertEqual(r["entries_limit_2"], 2)
        self.assertTrue(r["min_level_filtered"])
        self.assertEqual(r["size_after_clear"], 0)
        self.assertEqual(r["reports_when_false"], 0)
        self.assertEqual(r["reports_when_true"], 1)
        self.assertEqual(r["dedup_warn_count"], 1)
        self.assertEqual(r["cap_100_count"], 100)
        self.assertTrue(r["joined_len_le_7000"])
        self.assertTrue(r["bus_retained_all_5"])
        self.assertTrue(r["detached_ok"])
        self.assertEqual(r["session_host_warn_count"], 1)
        self.assertEqual(r["session_bus_warn_count"], 1)
        self.assertTrue(r["create_logger_null_opts_ok"])
        self.assertTrue(r["cyclic_and_arity_ok"])
        self.assertTrue(r["reentrancy_and_typed_sub_ok"])

    def test_module_registry_and_warnings(self) -> None:
        r = self.results["module_registry"]
        self.assertEqual(r["all_count"], 33)
        self.assertEqual(r["catalog_count"], 30)
        self.assertTrue(r["simple_fog_enabled"])
        self.assertTrue(r["drawing_enabled"])
        self.assertTrue(r["portal_disabled"])
        self.assertEqual(r["portal_status"], "disabled")
        self.assertEqual(r["campaign_status"], "playtest_blocked")
        self.assertEqual(r["dnd_opp_status"], "playtest_blocked")
        self.assertEqual(r["entity_notes_status"], "uncatalogued_candidate")
        self.assertEqual(r["music_board_status"], "uncatalogued_candidate")
        self.assertEqual(r["module_example_status"], "uncatalogued_candidate")
        self.assertEqual(r["alias_status"], "uncatalogued_candidate")
        self.assertEqual(r["alias_resolved_id"], "module_example")
        self.assertEqual(r["core_status"], "core")
        self.assertTrue(r["core_stays_locked"])
        self.assertEqual(r["comp_lookup_fog"], "simple_fog")
        self.assertEqual(r["comp_lookup_init"], "candidate_initiative")
        self.assertTrue(r["stateless_debug"])
        self.assertTrue(r["stateless_chat"])
        self.assertTrue(r["stateless_music"])
        self.assertTrue(r["stateless_example"])
        self.assertTrue(r["late_setup_ok"])
        self.assertTrue(r["preserved_simple_fog"])
        self.assertTrue(r["logger_adopted"])
        self.assertTrue(r["preserve_ok"])
        self.assertTrue(r["preserve_warn_logged"])
        self.assertTrue(r["preserve_warn_names_id"])
        self.assertTrue(r["skip_blocked_ok"])
        self.assertEqual(r["skip_blocked_reason"], "module_disabled:campaign_time")
        self.assertTrue(r["skip_cand_ok"])
        self.assertTrue(r["unblocked_campaign_enabled"])
        self.assertTrue(r["probe_ok"])
        self.assertTrue(r["probed_checklist_enabled"])
        self.assertTrue(r["probed_simple_fog_now_off"])
        self.assertTrue(r["probed_campaign_blocked"])
        self.assertTrue(r["probe_unblock_ok"])
        self.assertEqual(r["probed_campaign_unblocked_status"], "enabled")
        self.assertTrue(r["probed_campaign_unblocked_enabled"])
        self.assertTrue(r["probe_unblock_disabled_ok"])
        self.assertEqual(r["probed_campaign_unblocked_disabled_status"], "disabled")
        self.assertFalse(r["probed_campaign_unblocked_disabled_enabled"])
        self.assertTrue(r["create_plugin_sdk_alias_ok"])
        self.assertTrue(r["case_norm_ok"])
        self.assertTrue(r["reject_module_registry_ok"])
        self.assertTrue(r["probe_null_reason_ok"])
        self.assertEqual(r["null_reason_campaign_status"], "disabled")
        self.assertEqual(r["null_reason_campaign_reason"], "")
        self.assertEqual(r["null_reason_fog_status"], "enabled")
        self.assertEqual(r["null_reason_fog_reason"], "")
        self.assertEqual(r["null_reason_dnd_status"], "disabled")
        self.assertEqual(r["null_reason_dnd_reason"], "")
        self.assertTrue(r["probe_empty_choices_ok"])
        self.assertTrue(r["probed_checklist_cleared_on_empty"])
        self.assertTrue(r["probed_core_stays_on_empty"])
        self.assertTrue(r["cand_stays_uncatalogued"])
        self.assertTrue(r["json_null_booleans_and_dup_ok"])
        self.assertTrue(r["probe_dup_and_weird_reason_ok"])

    def test_parked_and_manual_components(self) -> None:
        r = self.results["parked_manual"]
        self.assertTrue(r["ok_auto_park"])
        self.assertTrue(r["ok_manual_park"])
        self.assertTrue(r["bad_manual_only_rejected"])
        self.assertEqual(r["comp_count"], 4)
        self.assertTrue(r["c2_parked"])
        self.assertTrue(r["c2_no_manual"])
        self.assertEqual(r["c2_size"], 3)
        self.assertTrue(r["c3_parked"])
        self.assertTrue(r["c3_manual"])
        self.assertEqual(r["c3_size"], 4)
        self.assertEqual(r["adapter_reason"], "manual_requires_parked")
        self.assertTrue(r["inf_nan_state_rejected"])
        self.assertTrue(r["roundtrip_ok"])
        self.assertTrue(r["adapter_null_and_cyclic_ok"])
        self.assertTrue(r["scaled_inf_and_null_world_ok"])
        self.assertTrue(r["json_null_uid_guards_ok"])
        self.assertTrue(r["module_depth_dag_and_coerce_ok"])

    def test_core_plugin_edit_mode(self) -> None:
        r = self.results["edit_mode"]
        self.assertEqual(r["module_id"], "feature_edit_mode")
        self.assertTrue(r["enabled"])
        self.assertTrue(r["attach_unit_ok"])
        self.assertTrue(r["is_unit_after"])
        self.assertTrue(r["flags_ok"])
        self.assertTrue(r["perm_ok"])
        self.assertTrue(r["perm_json_null_ok"])
        self.assertTrue(r["perm_json_null_fields_ok"])
        self.assertTrue(r["perm_owners_container_empty"])
        self.assertTrue(r["perm_restore_ok"])
        self.assertTrue(r["parked_manual_json_null_ok"])
        self.assertTrue(r["fp_bad_low"])
        self.assertTrue(r["fp_bad_high"])
        self.assertTrue(r["fp_ok"])
        self.assertTrue(r["val_unit_ok"])
        self.assertTrue(r["map_rejected"])
        self.assertTrue(r["map_val_rejected"])
        self.assertTrue(r["map_select_rejected"])
        self.assertTrue(r["int_fp_rejected"])
        self.assertTrue(r["non_unit_rejected"])
        self.assertTrue(r["parked_unit_rejected"])
        self.assertTrue(r["missing_perm_key_rejected"])
        self.assertTrue(r["bad_schema_version_types_rejected"])
        self.assertTrue(r["bad_selectable_types_rejected"])
        self.assertTrue(r["wb_map_unit_rejected"])
        self.assertTrue(r["wb_obj_unit_ok"])
        self.assertTrue(r["scene_box_rejected"])
        self.assertTrue(r["bom_perm_parity_ok"])

    def test_core_plugin_floor_system(self) -> None:
        r = self.results["floor_system"]
        self.assertTrue(r["f1_created"])
        self.assertTrue(r["rename_ok"])
        self.assertTrue(r["rename_rejects_empty"])
        self.assertTrue(r["rename_rejects_ctrl"])
        self.assertTrue(r["rename_rejects_padded"])
        self.assertTrue(r["rename_rejects_over_96"])
        self.assertTrue(r["name_unchanged_after_reject"])
        self.assertTrue(r["get_floor_unknown_empty"])
        self.assertTrue(r["color_ok"])
        self.assertTrue(r["color_nan_rejected"])
        self.assertTrue(r["reorder_ok"])
        self.assertEqual(r["reordered_ids_ok"], True)
        self.assertTrue(r["no_elevation_key"])
        self.assertTrue(r["visits_ok"])
        self.assertEqual(r["visits_count"], 2)
        self.assertTrue(r["visits_128_ok"])
        self.assertTrue(r["visits_129_rejected"])
        self.assertTrue(r["visits_ctrl_rejected"])
        self.assertTrue(r["visits_bad_uid_rejected"])
        self.assertTrue(r["val_ok"])
        self.assertTrue(r["extra_elevation_rejected"])
        self.assertTrue(r["bad_floor_id_ver_types_rejected"])
        self.assertTrue(r["rename_bom_ok"])
        self.assertTrue(r["null_uid_rejected"])

    def test_core_plugin_layer_stack(self) -> None:
        r = self.results["layer_stack"]
        self.assertTrue(r["bad_players_rejected"])
        self.assertTrue(r["good_players_ok"])
        self.assertTrue(r["viewers_sorted"])
        self.assertTrue(r["vis_ok"])
        self.assertTrue(r["lock_ok"])
        self.assertTrue(r["rename_ok"])
        self.assertTrue(r["rename_rejects_invalid"])
        self.assertTrue(r["add_layer_150_ok"])
        self.assertTrue(r["add_layer_160_ok"])
        self.assertTrue(r["direct_add_layer_150_ok"])
        self.assertTrue(r["add_layer_161_rejected"])
        self.assertTrue(r["add_layer_ctrl_rejected"])
        self.assertTrue(r["add_layer_empty_rejected"])
        self.assertTrue(r["add_layer_non_str_rejected"])
        self.assertTrue(r["access_160_ok"])
        self.assertTrue(r["access_161_rejected"])
        self.assertTrue(r["access_ctrl_rejected"])
        self.assertTrue(r["access_transitions_ok"])
        self.assertTrue(r["default_access_protected"])
        self.assertTrue(r["area_cannot_be_default"])
        self.assertTrue(r["editor_view_ok"])
        self.assertTrue(r["val_ok"])
        self.assertTrue(r["val_rejects_ctrl_viewer"])
        self.assertTrue(r["val_rejects_empty_ev_floor"])
        self.assertTrue(r["adapter_ctrl_sanitized_empty"])
        self.assertTrue(r["adapter_create_layer_rejects_ctrl_bom_ws"])
        self.assertTrue(r["ls_bom_and_ctrl_parity_ok"])
        self.assertTrue(r["val_rejects_raw_bom_viewer"])
        self.assertTrue(r["persistent_null_rejected"])
        self.assertTrue(r["null_uid_and_kind_rejected"])

    def test_core_plugin_obstacle_authoring(self) -> None:
        r = self.results["obstacle_authoring"]
        self.assertTrue(r["door_created"])
        self.assertTrue(r["door_open_ok"])
        self.assertTrue(r["door_disable_ok"])
        self.assertTrue(r["door_is_open"])
        self.assertTrue(r["door_line_color_synced"])
        self.assertTrue(r["door_is_disabled"])
        self.assertEqual(r["circle_uid_len"], 64)
        self.assertEqual(r["poly_uid_len"], 64)
        self.assertTrue(r["attach_obs_ok"])
        self.assertTrue(r["val_state_ok"])
        self.assertTrue(r["bad_digest_rejected"])
        self.assertTrue(r["inf_basis_rejected"])
        self.assertTrue(r["nan_radius_rejected"])
        self.assertTrue(r["bad_shape_schema_types_rejected"])
        self.assertTrue(r["inf_nan_geom_rejected"])
        self.assertTrue(r["flip_conflict_rejected"])
        self.assertTrue(r["scene_box_conflict_rejected"])
        self.assertTrue(r["drawing_non_obstacle_warned"])
        self.assertTrue(r["overflow_and_degenerate_rejected"])

    def test_core_plugin_entity_library(self) -> None:
        r = self.results["entity_library"]
        self.assertTrue(r["no_favorites_api"])
        self.assertEqual(r["template_keys_count"], 9)
        self.assertTrue(r["template_bad_size_rejected"])
        self.assertTrue(r["inspect_off_rejected"])
        self.assertTrue(r["inspect_record_snapshot_rejected"])
        self.assertTrue(r["safe_coercion_ok"])
        self.assertTrue(r["null_script_name_and_inf_ok"])
        self.assertTrue(r["preserve_ok"])
        self.assertEqual(r["preserve_count"], 1)
        self.assertTrue(r["preserve_not_skipped"])
        self.assertTrue(r["preserve_warned"])
        self.assertTrue(r["preserve_host_warn_has_reason"])
        self.assertTrue(r["preserve_has_vision_comp"])
        self.assertTrue(r["skip_ok"])
        self.assertEqual(r["skip_count"], 1)
        self.assertTrue(r["skip_not_skipped"])
        self.assertTrue(r["skip_stripped_vision"])
        self.assertTrue(r["skip_removed_vision_comp"])
        self.assertTrue(r["fallback_unit_ok"])
        self.assertTrue(r["enabled_ok"])
        self.assertEqual(r["enabled_count"], 1)
        self.assertTrue(r["enabled_not_skipped"])
        self.assertTrue(r["enabled_zero_warnings"])
        self.assertTrue(r["enabled_has_vision_comp"])
        self.assertTrue(r["rollback_done"])
        self.assertTrue(r["r7_modules_hardening_ok"])

    def test_r8_large_payloads_memo_bypass_and_dag_bounds(self) -> None:
        r = self.results["r8_bounds_and_dag"]
        self.assertTrue(r["large_arr70_ok"])
        self.assertTrue(r["large_grid140_ok"])
        self.assertTrue(r["large_dict70_ok"])
        self.assertTrue(r["memo_bypass_ok"], f"memo_bypass_debug={r.get('memo_bypass_debug')}")
        self.assertTrue(r["pattern_d_memo_ok"], f"memo_bypass_debug={r.get('memo_bypass_debug')}")
        self.assertTrue(r["dag18_24_six_funcs_fast"])
        self.assertTrue(r["set_module_state_dag18_limit"])
        self.assertTrue(r["obstacle_dag_guards_ok"])
        self.assertTrue(r["component_dag_and_depth_ok"])
        self.assertTrue(r["minor_polish_ok"])
        self.assertTrue(r["sanitize_non_string_keys_ok"])

    def test_r8_asset_publisher_prevalidate_multi_item_batch(self) -> None:
        r = self.results["r8_asset_publisher_batch"]
        self.assertTrue(r["pkg_open_ok"])
        self.assertTrue(r["prep_cache_ok"])
        self.assertTrue(r["ok_refs_published"])
        self.assertTrue(r["failure_reasons_ok"])

    def test_r10_bucketed_memo_sibling_keys_and_dag_module_state(self) -> None:
        r = self.results["r10_hardening"]
        self.assertTrue(r["sibling_keys_and_casts_ok"], msg=f"sib_elapsed_ms={r.get('sib_elapsed_ms')}")
        self.assertTrue(r["sib_dag15_tctx_ok"], msg=f"sib_dag15_tctx_debug={r.get('sib_dag15_tctx_debug')}")
        self.assertTrue(r["memo_traps_ok"], f"trap_debug={r.get('trap_debug')}")
        self.assertTrue(r["dag_module_and_component_ok"])

    def test_r11_depth32_empty_leaf_clipped_dag_and_can_fit(self) -> None:
        r = self.results["r11_hardening"]
        self.assertTrue(r["empty_leaf_depth32_fast_ok"], f"empty_leaf_debug={r.get('empty_leaf_depth32_debug')}")
        self.assertTrue(r["clipped_dag_fast_ok"], f"clipped_debug={r.get('clipped_dag_debug')}")
        self.assertTrue(r["clipped_truncation_semantics_ok"])
        self.assertTrue(r["synthetic_can_fit_ok"])

    def test_r12_memo_fair_share_work_nodes_and_nonvacuous_clipped_dags(self) -> None:
        r = self.results["r12_hardening"]
        self.assertTrue(r["arr99_live20_ok"], f"arr99_debug={r.get('arr99_debug')}")
        self.assertTrue(r["arr15_15lvl_est128_ok"], f"arr15_debug={r.get('arr15_debug')}")
        self.assertTrue(r["adversarial_variants_ok"], f"adversarial_variants_debug={r.get('adversarial_variants_debug')}")
        self.assertTrue(r["clipped_same_depth_20copy_ok"])
        self.assertTrue(r["nonvacuous_clipped_9entrypoints_ok"], f"nonvacuous_clipped_debug={r.get('nonvacuous_clipped_debug')}")
        self.assertTrue(r["logbus_depth32_empty_leaf_ok"])
        self.assertTrue(r["asymmetric_clipped_isolation_ok"])

    def test_r13_ring_heavy_pinning_clipped_ghost_and_leak_invariants(self) -> None:
        r = self.results["r13_hardening"]
        self.assertTrue(r["group_a_exploit_e_10500_ok"], f"group_a={r.get('group_a_debug')}")
        self.assertTrue(r["group_b_exploit_f_child_ok"], f"group_b={r.get('group_b_debug')}")
        self.assertTrue(r["group_c_all5_cloners_ok"], f"group_c={r.get('group_c_debug')}")
        self.assertTrue(r["group_d_live30_junks_ok"], f"group_d_live30={r.get('group_d_live30_debug')}")
        self.assertTrue(r["group_d_high_hit_200_ok"], f"group_d_hit200={r.get('group_d_hit200_debug')}")
        self.assertTrue(r["group_d_clipped_128_ok"], f"group_d_clipped={r.get('group_d_clipped_debug')}")
        self.assertTrue(r["group_e_ghost_sync_and_zero_leak_ok"], f"group_e={r.get('group_e_debug')}")

    def test_utils_modules_unit_coverage(self) -> None:
        r = self.results["utils_unit_tests"]
        self.assertTrue(r["dag_cloner_ok"])
        self.assertTrue(r["bounded_cloner_ok"])
        self.assertTrue(r["value_utils_ok"])
        self.assertTrue(r["validation_utils_ok"])
        self.assertTrue(r["obstacle_hex64_strict_ok"])


if __name__ == "__main__":
    unittest.main()
