"""Tier 5 Adversarial Regression Tests for Fu vtt SDK & Mod Hygiene."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

TOOLS_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = TOOLS_DIR.parents[1]
SDK_DIR = WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk"
TEST_TMP_ROOT = WORKSPACE_ROOT / ".cache" / "test_tmp"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from fuvtt_devtools.env_config import load_config  # noqa: E402
from fuvtt_devtools.host_verifier import analyze_godot_logs  # noqa: E402
from fuvtt_devtools.validator import strip_gdscript_comments  # noqa: E402


PROBE_GD = r'''extends SceneTree

class MockHost extends RefCounted:
	var reports: Array[String] = []
	var warnings: Array[String] = []

	func cancelled() -> bool:
		return false

	func report(msg: String) -> void:
		reports.append(msg)

	func warn(msg: String) -> void:
		warnings.append(msg)

	func empty_world() -> Dictionary:
		var floor_uid := "11111111111111111111111111111111"
		var map_uid := "22222222222222222222222222222222"
		var entity_uid := "33333333333333333333333333333333"
		var obstacle_uid := "44444444444444444444444444444444"
		return {
			"ok": true,
			"data": {
				"format": "fus.practice.world",
				"version": 3,
				"catalog": {
					"floor_identity_version": 1,
					"active_floor_uid": floor_uid,
					"floors": [
						{"id": 0, "floor_uid": floor_uid, "name": "1F", "color": Color(0.28, 0.65, 0.40)}
					],
					"layers": {
						"schema": "fus.floor_layers.v2",
						"floors": [{
							"floor_uid": floor_uid,
							"default_layer_uid": entity_uid,
							"layers": [
								{"layer_uid": map_uid, "name": "Map", "kind": "map", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
								{"layer_uid": entity_uid, "name": "Entity", "kind": "entity", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
								{"layer_uid": obstacle_uid, "name": "Obstacle", "kind": "obstacle", "visible": true, "locked": false, "persistent": true, "access": "host", "viewers": []},
							],
						}],
					},
				},
				"entity_state": {"version": 3, "entities": []},
				"members": [],
				"modules": {"version": 2, "entries": {}},
			},
		}

	func archive_image(_url: String, _proxy: String = "") -> Dictionary:
		return {"ok": false, "reason": "no_net", "reference": ""}

	func begin_preview(_total: int, _bounds: Rect2) -> void:
		pass

	func preview_entity(_entity: Dictionary, _kind: String) -> void:
		pass

	func finish_geometry_preview() -> bool:
		return true

	func inspect_source(_path: String) -> Dictionary:
		return {"ok": false, "reason": "unsupported"}

	func decode_source(_path: String) -> Dictionary:
		return {"ok": false, "reason": "unsupported"}


func _check_skip_gate(res: Dictionary, expected_mod: String, sess: RefCounted, before_warns: int) -> bool:
	var after_warns: int = sess.get_logger().get_warnings(0).size()
	return (
		not bool(res.get("ok", true))
		and bool(res.get("skipped", false))
		and str(res.get("reason", "")) == ("module_disabled:" + expected_mod)
		and (after_warns - before_warns) == 1
	)


func _run_plain_wb_leak_batch(sdk_scr: Script, iters: int) -> void:
	for _i: int in range(iters):
		var l_sdk = sdk_scr.new()
		var l_host := MockHost.new()
		var l_sess = l_sdk.create_session(l_host, {})
		var l_wb = l_sdk.create_world_builder(l_sess, 150.0)
		l_wb.get_logger().set_emit_to_engine(false)


func _run_single_plugin_leak_batch(sdk_scr: Script, module_id: String, iters: int) -> void:
	for _i: int in range(iters):
		var l_sdk = sdk_scr.new()
		var l_host := MockHost.new()
		var l_sess = l_sdk.create_session(l_host, {})
		var l_wb = l_sdk.create_world_builder(l_sess, 150.0)
		l_wb.get_logger().set_emit_to_engine(false)
		var _p: RefCounted = l_wb.get_plugin_sdk(module_id)


func _run_all23_combined_leak_batch(sdk_scr: Script, iters: int) -> void:
	for _i: int in range(iters):
		var l_sdk = sdk_scr.new()
		var l_host := MockHost.new()
		var l_sess = l_sdk.create_session(l_host, {})
		var l_wb = l_sdk.create_world_builder(l_sess, 150.0)
		l_wb.get_logger().set_emit_to_engine(false)
		var _c1: RefCounted = l_wb.edit_mode()
		var _c2: RefCounted = l_wb.floor_system()
		var _c3: RefCounted = l_wb.layer_stack()
		var _c4: RefCounted = l_wb.obstacle_authoring()
		var c5: RefCounted = l_wb.entity_library()
		if c5 != null:
			var _wr: RefCounted = c5.get_writer()
			var _cw: bool = bool(c5.can_write_library(l_host))
		var _m2_1: RefCounted = l_wb.scene_box()
		var _m2_2: RefCounted = l_wb.portal()
		var _m2_3: RefCounted = l_wb.grid_alignment()
		var _m2_4: RefCounted = l_wb.simple_fog()
		var _m2_5: RefCounted = l_wb.image_flip()
		var _m2_6: RefCounted = l_wb.drag_movement()
		var _m2_7: RefCounted = l_wb.drawing()
		var _m2_8: RefCounted = l_wb.areas()
		var _m2_9: RefCounted = l_wb.entity_notes()
		var _m3_1: RefCounted = l_wb.checklist()
		var _m3_2: RefCounted = l_wb.resource_pool()
		var _m3_3: RefCounted = l_wb.character_roster()
		var _m3_4: RefCounted = l_wb.backpack()
		var _m3_5: RefCounted = l_wb.follow()
		var _m3_6: RefCounted = l_wb.candidate_initiative()
		var _m3_7: RefCounted = l_wb.dice()
		var _m3_8: RefCounted = l_wb.campaign_time()
		var _m3_9: RefCounted = l_wb.dnd_opportunity()


func _make_freed_core_plugins(sdk_scr: Script) -> Array:
	var l_sdk = sdk_scr.new()
	var l_host := MockHost.new()
	var l_sess = l_sdk.create_session(l_host, {})
	var l_wb = l_sdk.create_world_builder(l_sess, 150.0)
	l_wb.get_logger().set_emit_to_engine(false)
	return [
		l_wb.edit_mode(),
		l_wb.floor_system(),
		l_wb.layer_stack(),
		l_wb.obstacle_authoring(),
		l_wb.entity_library(),
	]


func _run_gap10_leak_probes(sdk_scr: Script) -> Dictionary:
	var all_plugins: Array[String] = [
		"feature_edit_mode",
		"feature_floor_system",
		"feature_layer_stack",
		"feature_obstacle_authoring",
		"feature_entity_library",
		"scene_box",
		"portal",
		"grid_alignment",
		"simple_fog",
		"image_flip",
		"drag_movement",
		"drawing",
		"areas",
		"entity_notes",
		"checklist",
		"resource_pool",
		"character_roster",
		"backpack",
		"follow",
		"candidate_initiative",
		"dice",
		"campaign_time",
		"dnd_opportunity",
	]
	_run_plain_wb_leak_batch(sdk_scr, 1)
	_run_all23_combined_leak_batch(sdk_scr, 1)

	var base_plain: float = Performance.get_monitor(Performance.OBJECT_COUNT)
	_run_plain_wb_leak_batch(sdk_scr, 5)
	var plain_5x_delta: float = Performance.get_monitor(Performance.OBJECT_COUNT) - base_plain

	var per_plugin_deltas := {}
	var all_zero: bool = is_equal_approx(plain_5x_delta, 0.0)
	for pid: String in all_plugins:
		var b_p: float = Performance.get_monitor(Performance.OBJECT_COUNT)
		_run_single_plugin_leak_batch(sdk_scr, pid, 5)
		var d_p: float = Performance.get_monitor(Performance.OBJECT_COUNT) - b_p
		per_plugin_deltas[pid] = d_p
		if not is_equal_approx(d_p, 0.0):
			all_zero = false

	var base_comb: float = Performance.get_monitor(Performance.OBJECT_COUNT)
	_run_all23_combined_leak_batch(sdk_scr, 5)
	var combined_5x_delta: float = Performance.get_monitor(Performance.OBJECT_COUNT) - base_comb
	if not is_equal_approx(combined_5x_delta, 0.0):
		all_zero = false

	var freed_cores: Array = _make_freed_core_plugins(sdk_scr)
	var freed_safe: bool = (
		freed_cores.size() == 5
		and freed_cores[0]._wb() == null
		and freed_cores[1]._wb() == null
		and freed_cores[2]._wb() == null
		and freed_cores[3]._wb() == null
		and freed_cores[4]._wb() == null
		and not bool(freed_cores[0].is_unit("missing"))
		and (freed_cores[1].get_floors() as Array).is_empty()
		and (freed_cores[2].get_layer("missing") as Dictionary).is_empty()
		and (freed_cores[3].extrude_segment_to_quad(Vector2.ZERO, Vector2(10, 0)) as PackedVector2Array).is_empty()
		and not bool(freed_cores[4].build_template_data("t", "T").is_empty())
	)

	return {
		"ok": all_zero and freed_safe,
		"plugin_count": all_plugins.size(),
		"plain_5x_delta": plain_5x_delta,
		"combined_5x_delta": combined_5x_delta,
		"per_plugin_deltas": per_plugin_deltas,
		"freed_core_weakref_safe": freed_safe,
	}


func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	var sdk_scr: Script = load("res://shared/sdk/fu_sdk/v1.gd") as Script
	var sdk: RefCounted = sdk_scr.new()
	var results := {}

	# 1. BUG-04: Pre-gate ordering under disabled_module_policy="skip" for all 14 plugins
	var host := MockHost.new()
	var sess = sdk.create_session(host, {})
	sess.get_logger().set_emit_to_engine(false)
	var wb = sdk.create_world_builder(sess, 150.0)
	wb.set_enabled_modules([])
	wb.set_disabled_module_policy("skip")
	var e1: String = wb.add_token("u1", "Hero", Vector2(10, 10), Vector2(64, 64), "")
	var e2: String = wb.add_token("u2", "Mate", Vector2(80, 10), Vector2(64, 64), "")
	var logger = sess.get_logger()

	var w0: int = logger.get_warnings(0).size()
	var r_flip: Dictionary = wb.image_flip().attach_flip(e1, true, false, false, true)
	var g_flip: bool = _check_skip_gate(r_flip, "image_flip", sess, w0)

	w0 = logger.get_warnings(0).size()
	var r_portal: Dictionary = wb.portal().link_pair("", e2, "bad_key", false, false)
	var g_portal: bool = _check_skip_gate(r_portal, "portal", sess, w0)

	w0 = logger.get_warnings(0).size()
	var r_fog: Dictionary = wb.simple_fog().attach_vision(e1, -1.0, 45.0, false, true)
	var g_fog: bool = _check_skip_gate(r_fog, "simple_fog", sess, w0)

	w0 = logger.get_warnings(0).size()
	var r_drag: Dictionary = wb.drag_movement().attach_drag_speed(e1, -5.0, false, true)
	var g_drag: bool = _check_skip_gate(r_drag, "drag_movement", sess, w0)

	w0 = logger.get_warnings(0).size()
	var r_draw: Dictionary = wb.drawing().attach_entity_ink(e1, [{"id": "bad id!"}], "", false, true)
	var g_draw: bool = _check_skip_gate(r_draw, "drawing", sess, w0)

	w0 = logger.get_warnings(0).size()
	var r_area: Dictionary = wb.areas().attach_area(e1, -10.0, false, true)
	var g_area: bool = _check_skip_gate(r_area, "areas", sess, w0)

	w0 = logger.get_warnings(0).size()
	var r_notes: Dictionary = wb.entity_notes().attach_note(e1, "", true, false, false, true)
	var g_notes: bool = _check_skip_gate(r_notes, "entity_notes", sess, w0)

	w0 = logger.get_warnings(0).size()
	var r_rp: Dictionary = wb.resource_pool().attach_resource_pool(e1, {"bad": "shape"}, false, true)
	var g_rp: bool = _check_skip_gate(r_rp, "resource_pool", sess, w0)

	w0 = logger.get_warnings(0).size()
	var r_cr: Dictionary = wb.character_roster().attach_character_roster_member(e1, {"known_by": "invalid"}, false, true)
	var g_cr: bool = _check_skip_gate(r_cr, "character_roster", sess, w0)

	w0 = logger.get_warnings(0).size()
	var r_bp: Dictionary = wb.backpack().attach_backpack(e1, {"slots": "bad"}, false, true)
	var g_bp: bool = _check_skip_gate(r_bp, "backpack", sess, w0)

	w0 = logger.get_warnings(0).size()
	var r_flw: Dictionary = wb.follow().attach_follow(e1, {"target_id": e1}, false, true)
	var g_flw: bool = _check_skip_gate(r_flw, "follow", sess, w0)

	w0 = logger.get_warnings(0).size()
	var r_init: Dictionary = wb.candidate_initiative().attach_initiative(e1, {"bad": 1}, false, true)
	var g_init: bool = _check_skip_gate(r_init, "candidate_initiative", sess, w0)

	w0 = logger.get_warnings(0).size()
	var r_dnd: Dictionary = wb.dnd_opportunity().set_edition(1999)
	var g_dnd: bool = _check_skip_gate(r_dnd, "dnd_opportunity", sess, w0)

	w0 = logger.get_warnings(0).size()
	var r_grid: Dictionary = wb.grid_alignment().configure_grid_alignment("bad")
	var g_grid: bool = _check_skip_gate(r_grid, "grid_alignment", sess, w0)

	w0 = logger.get_warnings(0).size()
	var sb_res: bool = wb.scene_box().attach_scene_box(e1, "missing_scene", "", "visited_unlock", true, [], false, true)
	var w_after_sb: int = logger.get_warnings(0).size()
	var g_sb: bool = (not sb_res) and (w_after_sb - w0) == 1

	results["bug04_all_gates_before_args_ok"] = (
		g_flip and g_portal and g_fog and g_drag and g_draw and g_area and g_notes
		and g_rp and g_cr and g_bp and g_flw and g_init and g_dnd and g_grid and g_sb
	)
	results["bug04_detail"] = {
		"flip": g_flip, "portal": g_portal, "fog": g_fog, "drag": g_drag,
		"draw": g_draw, "area": g_area, "notes": g_notes, "rp": g_rp,
		"cr": g_cr, "bp": g_bp, "flw": g_flw, "init": g_init, "dnd": g_dnd, "grid": g_grid, "sb": g_sb,
	}

	# 2. BUG-06: >64-node DAG non-aliasing in LogBus & ModuleRegistry + cycle safety
	var big_shared := {"nested": {"val": 42}}
	for k_i: int in range(72):
		big_shared["k_%d" % k_i] = k_i
	var top_dag := {"branch_a": big_shared, "branch_b": big_shared}
	var logged_dag: Dictionary = logger.info("t5_dag", "clone_check", top_dag)
	var lctx: Dictionary = logged_dag.get("context", {}) as Dictionary
	var bus_unaliased: bool = (
		not is_same(lctx.get("branch_a"), lctx.get("branch_b"))
		and not is_same((lctx["branch_a"] as Dictionary).get("nested"), (lctx["branch_b"] as Dictionary).get("nested"))
	)
	(lctx["branch_a"] as Dictionary)["mutated"] = true
	((lctx["branch_a"] as Dictionary)["nested"] as Dictionary)["val"] = 999
	var bus_isolated: bool = (
		not (lctx["branch_b"] as Dictionary).has("mutated")
		and int(((lctx["branch_b"] as Dictionary)["nested"] as Dictionary).get("val", -1)) == 42
	)
	var reg = wb.get_module_registry()
	var reg_cloned: Variant = reg._safe_clone_variant(top_dag)
	var reg_ok: bool = false
	if reg_cloned is Dictionary:
		var rcd: Dictionary = reg_cloned as Dictionary
		reg_ok = (
			not is_same(rcd.get("branch_a"), rcd.get("branch_b"))
			and not is_same((rcd["branch_a"] as Dictionary).get("nested"), (rcd["branch_b"] as Dictionary).get("nested"))
		)
	var cyc_dag := {}
	cyc_dag["self"] = cyc_dag
	var cyc_logged: Dictionary = logger.info("t5_dag", "cyc", cyc_dag)
	var cyc_reg: Variant = reg._safe_clone_variant(cyc_dag)
	results["bug06_dag_non_aliasing_ok"] = (
		bus_unaliased and bus_isolated and reg_ok
		and (cyc_logged.get("context", {}) as Dictionary).get("self", 1) == null
		and cyc_reg is Dictionary and (cyc_reg as Dictionary).get("self", 1) == null
	)

	# 3. BUG-09: v1.gd legacy WorldBuilder wrappers respect ModuleRegistry gates + R2 warnings
	var wb_leg = sdk.create_world_builder(sdk.create_session(MockHost.new(), {}), 150.0)
	wb_leg._session.get_logger().set_emit_to_engine(false)
	wb_leg.set_enabled_modules([])
	wb_leg.set_disabled_module_policy("skip")
	var leg_tok: String = wb_leg.add_token("leg_tok", "Hero", Vector2.ZERO, Vector2(64, 64), "")
	var leg_portal: bool = wb_leg.attach_portal(leg_tok, "pair1")
	var leg_vis: bool = wb_leg.attach_simple_vision(leg_tok, 300.0, 360.0)
	var leg_slight: bool = wb_leg.attach_simple_light(leg_tok, 300.0, 360.0)
	var leg_plight: String = wb_leg.add_point_light("pl1", Vector2(20, 20), 200.0)
	var leg_sb_id: String = wb_leg.add_scene_box("sb1", "Box", Vector2(40, 40), "scene_x")
	var leg_sb_att: bool = wb_leg.attach_scene_box(leg_tok, "scene_x")
	var leg_grid: bool = wb_leg.configure_grid_alignment(64.0)
	var leg_warns: int = wb_leg._session.get_logger().get_warnings(0).size()
	results["bug09_v1_legacy_gates_ok"] = (
		not leg_portal and not leg_vis and not leg_slight
		and leg_plight.is_empty() and leg_sb_id.is_empty()
		and not leg_sb_att and not leg_grid
		and leg_warns == 7
	)

	# 4. BUG-10: candidate comp_scene_box.gd conflict + make_portal_state uppercase 32-hex UID
	var wb_b10 = sdk.create_world_builder(sdk.create_session(MockHost.new(), {}), 150.0)
	wb_b10._session.get_logger().set_emit_to_engine(false)
	wb_b10.set_enabled_modules(["feature_edit_mode", "portal"])
	var cand_box_ent: String = wb_b10.add_object_sprite("cbox", "CandBox", Vector2.ZERO, Vector2(96, 96), "")
	var adapter = wb_b10.get_adapter()
	adapter.append_entity_component(
		wb_b10.get_entity(cand_box_ent),
		"res://scenes/candidates/scene_box/comp_scene_box.gd",
		{"target_scene_uid": "", "preview_policy": "visited_unlock", "enter_policy": "players_allowed"},
		false,
		false
	)
	var w_b10_before: int = wb_b10._session.get_logger().get_warnings(0).size()
	var unit_on_cbox: Dictionary = wb_b10.get_plugin_sdk("feature_edit_mode").attach_unit_marker(cand_box_ent)
	var w_b10_after: int = wb_b10._session.get_logger().get_warnings(0).size()
	var upper_uid := "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
	var pstate_upper: Dictionary = adapter.make_portal_state(upper_uid)
	results["bug10_candidate_scene_box_and_portal_uid_ok"] = (
		not bool(unit_on_cbox.get("ok", true))
		and str(unit_on_cbox.get("reason", "")) == "component_conflict_with_scene_box:unit"
		and w_b10_after == w_b10_before + 1
		and str(pstate_upper.get("pair_key", "")) == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	)

	# 5. GAP-01: simple_fog.configure_fog cycle safety (zero Godot Max recursion reached)
	var wb_g1 = sdk.create_world_builder(sdk.create_session(MockHost.new(), {}), 150.0)
	wb_g1._session.get_logger().set_emit_to_engine(false)
	wb_g1.set_enabled_modules(["simple_fog"])
	var cyc_fog_d := {}
	cyc_fog_d["self"] = cyc_fog_d
	var cyc_fog_col := {"r": 1.0, "g": 0.0, "b": 0.0}
	cyc_fog_col["self"] = cyc_fog_col
	var cyc_fog_root := {}
	cyc_fog_root["unseen_color"] = cyc_fog_root
	var sf_sdk = wb_g1.simple_fog()
	var sf_r1: Dictionary = sf_sdk.configure_fog({"unseen_color": cyc_fog_d})
	var sf_r2: Dictionary = sf_sdk.configure_fog({"unseen_color": cyc_fog_col})
	var sf_r3: Dictionary = sf_sdk.configure_fog(cyc_fog_root)
	results["gap01_simple_fog_cycle_ok"] = (
		not bool(sf_r1.get("ok", true))
		and not bool(sf_r2.get("ok", true))
		and not bool(sf_r3.get("ok", true))
	)

	# 6. GAP-02: checklist.make_row cycle-safe string & _coerce_bool guards
	var cl_sdk = wb_g1.checklist()
	var cyc_cl_d := {}
	cyc_cl_d["self"] = cyc_cl_d
	var cyc_cl_arr := []
	cyc_cl_arr.append(cyc_cl_arr)
	var cl_row: Variant = cl_sdk.make_row("SafeTitle", {
		"description": cyc_cl_d,
		"category": cyc_cl_arr,
		"audience": cyc_cl_d,
		"player_id": cyc_cl_d,
		"entity_id": cyc_cl_d,
		"source": cyc_cl_d,
		"last_motion": cyc_cl_d,
		"more_entity_ids": [cyc_cl_d, "ok_id"],
		"manual": null,
		"done": null,
		"archived": null,
		"order": null,
	})
	var cl_row_bools: Variant = cl_sdk.make_row("CoerceBool", {
		"manual": true,
		"done": 1,
		"archived": "true",
		"order": "7",
	})
	var cl_ok: bool = false
	if cl_row is Dictionary and cl_row_bools is Dictionary:
		var crd: Dictionary = cl_row as Dictionary
		var crb: Dictionary = cl_row_bools as Dictionary
		var more_ids: Array = crd.get("more_entity_ids", []) as Array
		cl_ok = (
			str(crd.get("title", "")) == "SafeTitle"
			and str(crd.get("description", "x")) == ""
			and str(crd.get("category", "x")) == ""
			and str(crd.get("audience", "x")) == ""
			and str(crd.get("player_id", "x")) == ""
			and str(crd.get("entity_id", "x")) == ""
			and str(crd.get("source", "x")) == ""
			and str(crd.get("last_motion", "x")) == ""
			and crd.get("manual", true) is bool and not bool(crd.get("manual", true))
			and crd.get("done", true) is bool and not bool(crd.get("done", true))
			and crd.get("archived", true) is bool and not bool(crd.get("archived", true))
			and int(crd.get("order", -1)) == 0
			and more_ids == ["", "ok_id"]
			and bool(crb.get("manual", false))
			and bool(crb.get("done", false))
			and bool(crb.get("archived", false))
			and int(crb.get("order", 0)) == 7
		)
	results["gap02_checklist_make_row_safe_ok"] = cl_ok

	# 7. GAP-03: 70-node shared DAG isolation across host_v1_adapter, feature_entity_library, feature_obstacle_authoring
	var sub70 := {"nested": {"val": 42}}
	for k70: int in range(72):
		sub70["k_%d" % k70] = k70
	var dag70 := {"a": sub70, "b": sub70}

	var g3_adapter = wb_g1.get_adapter()
	var g3_world: Dictionary = wb_g1.get_world()
	var mod_set_res: Dictionary = g3_adapter.set_module_state(g3_world, "dag_iso_mod", 1, dag70)
	var mod_state_70: Dictionary = g3_adapter.get_module_state(g3_world, "dag_iso_mod")
	var san_70: Variant = g3_adapter.sanitize_module_value(dag70)
	var adp_set_ok: bool = (
		bool(mod_set_res.get("ok", false))
		and not is_same(mod_state_70.get("a"), mod_state_70.get("b"))
	)
	(mod_state_70["a"] as Dictionary)["mutated"] = true
	((mod_state_70["a"] as Dictionary)["nested"] as Dictionary)["val"] = 999
	adp_set_ok = adp_set_ok and not (mod_state_70["b"] as Dictionary).has("mutated") and int(((mod_state_70["b"] as Dictionary)["nested"] as Dictionary).get("val", -1)) == 42

	var adp_san_ok: bool = false
	if san_70 is Dictionary:
		var sd70: Dictionary = san_70 as Dictionary
		adp_san_ok = not is_same(sd70.get("a"), sd70.get("b"))
		(sd70["a"] as Dictionary)["mutated"] = true
		((sd70["a"] as Dictionary)["nested"] as Dictionary)["val"] = 888
		adp_san_ok = adp_san_ok and not (sd70["b"] as Dictionary).has("mutated") and int(((sd70["b"] as Dictionary)["nested"] as Dictionary).get("val", -1)) == 42

	var tpl_70: Dictionary = wb_g1.entity_library().build_template_data(
		"tpl_70", "Tpl70", "", Vector2(64, 64), true, Color.WHITE, "generic", "library", dag70
	)
	var tpl_comps: Dictionary = tpl_70.get("components", {}) as Dictionary
	var el_70_ok: bool = not is_same(tpl_comps.get("a"), tpl_comps.get("b"))
	(tpl_comps["a"] as Dictionary)["mutated"] = true
	((tpl_comps["a"] as Dictionary)["nested"] as Dictionary)["val"] = 777
	el_70_ok = el_70_ok and not (tpl_comps["b"] as Dictionary).has("mutated") and int(((tpl_comps["b"] as Dictionary)["nested"] as Dictionary).get("val", -1)) == 42

	var obs_70: Dictionary = wb_g1.obstacle_authoring().make_obstacle_state("wall", "manual", 64.0, {}, dag70)
	var obs_cache: Dictionary = obs_70.get("cache", {}) as Dictionary
	var obs_70_ok: bool = not is_same(obs_cache.get("a"), obs_cache.get("b"))
	(obs_cache["a"] as Dictionary)["mutated"] = true
	((obs_cache["a"] as Dictionary)["nested"] as Dictionary)["val"] = 666
	obs_70_ok = obs_70_ok and not (obs_cache["b"] as Dictionary).has("mutated") and int(((obs_cache["b"] as Dictionary)["nested"] as Dictionary).get("val", -1)) == 42

	results["gap03_70node_dag_isolation_ok"] = adp_set_ok and adp_san_ok and el_70_ok and obs_70_ok
	results["gap03_detail"] = {"adp_set": adp_set_ok, "adp_san": adp_san_ok, "el": el_70_ok, "obs": obs_70_ok}

	# 8. GAP-04: WorldBuilder.add_scene_box / attach_scene_box reject manual=true without parked=true
	var wb_g4 = sdk.create_world_builder(sdk.create_session(MockHost.new(), {}), 150.0)
	wb_g4._session.get_logger().set_emit_to_engine(false)
	wb_g4.set_enabled_modules(["scene_box"])
	var g4_sc: String = wb_g4.scene_box().add_scene("Main", "1F")
	var g4_obj: String = wb_g4.add_object_sprite("obj_g4", "Obj", Vector2(10, 10), Vector2(64, 64), "")
	var g4_w0: int = wb_g4._session.get_logger().get_warnings(0).size()
	var g4_add_bad: String = wb_g4.add_scene_box("sb_bad", "Bad", Vector2(20, 20), g4_sc, 1.5, "", "visited_unlock", true, [], false, false, "", false, true)
	var g4_w1: int = wb_g4._session.get_logger().get_warnings(0).size()
	var g4_att_bad: bool = wb_g4.attach_scene_box(g4_obj, g4_sc, "", "visited_unlock", true, [], false, true)
	var g4_w2: int = wb_g4._session.get_logger().get_warnings(0).size()
	var g4_att_ok: bool = wb_g4.attach_scene_box(g4_obj, g4_sc, "", "visited_unlock", true, [], true, true)
	results["gap04_manual_requires_parked_ok"] = (
		g4_add_bad.is_empty()
		and (g4_w1 - g4_w0) == 1
		and not g4_att_bad
		and (g4_w2 - g4_w1) == 1
		and g4_att_ok
	)

	# 9. N2: ModuleRegistry._emit_warning under LEVEL_ERROR obeys LogBus 100/7000 caps & dedup with empty _entries
	var n2_host := MockHost.new()
	var n2_sess = sdk.create_session(n2_host, {})
	var n2_logger = n2_sess.get_logger()
	n2_logger.set_emit_to_engine(false)
	n2_logger.set_min_level(n2_logger.LEVEL_ERROR)
	var n2_wb = sdk.create_world_builder(n2_sess, 150.0)
	n2_wb.set_enabled_modules([])
	var n2_reg = n2_wb.get_module_registry()
	for i_n2: int in range(120):
		n2_reg.check_and_warn("simple_fog", "action_%03d" % i_n2)
	var count_after_120: int = n2_host.warnings.size()
	n2_reg.check_and_warn("simple_fog", "action_000")
	var count_after_dup: int = n2_host.warnings.size()
	var joined_n2: String = "\n".join(n2_host.warnings)
	results["n2_host_warn_cap_under_level_error_ok"] = (
		count_after_120 > 0
		and count_after_120 <= 100
		and count_after_dup == count_after_120
		and joined_n2.length() <= 7000
		and n2_logger.get_entries().is_empty()
		and int(n2_logger.get_host_warning_count()) == count_after_120
		and int(n2_logger.get_host_warning_chars()) == joined_n2.length()
	)
	results["n2_detail"] = {
		"count": count_after_120,
		"chars": joined_n2.length(),
		"entries": n2_logger.get_entries().size(),
		"bus_count": n2_logger.get_host_warning_count(),
	}

	# 10. GAP-05 & Sibling Cast Audit: corrupted module states must return structured Dictionaries with zero SCRIPT ERROR
	var wb_g5 = sdk.create_world_builder(sdk.create_session(MockHost.new(), {}), 150.0)
	wb_g5._session.get_logger().set_emit_to_engine(false)
	wb_g5.set_enabled_modules(["dice", "resource_pool", "checklist", "scene_box", "grid_alignment"])

	wb_g5.set_module_state("dice", 1, {"workspace": "bad"})
	var g5_dice_ws: Variant = wb_g5.dice().add_combo("Atk", "1d20+5")
	wb_g5.set_module_state("dice", 1, {"workspace": {"combos": "bad"}})
	var g5_dice_combos: Variant = wb_g5.dice().add_combo("Atk", "1d20+5")
	wb_g5.set_module_state("dice", 1, {"workspace": null})
	var g5_dice_null_ws: Variant = wb_g5.dice().add_combo("Atk", "1d20+5")

	wb_g5.set_module_state("resource_pool", 1, {"definitions": "bad"})
	var g5_rp_defs: Variant = wb_g5.resource_pool().define_resource("hp", "HP", 10.0)
	wb_g5.set_module_state("resource_pool", 1, {"definitions": {}, "adjustment_stamps": "bad"})
	var g5_rp_stamps: Variant = wb_g5.resource_pool().define_resource("hp", "HP", 10.0)

	wb_g5.set_module_state("checklist", 1, {"rows": "bad"})
	var g5_cl_auto: Variant = wb_g5.checklist().add_row("", {"title": "Task"})
	var g5_cl_uid: Variant = wb_g5.checklist().add_row("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", {
		"title": "Task",
		"description": "",
		"category": "",
		"audience": "all",
		"player_id": "",
		"entity_id": "",
		"source": "",
		"manual": false,
		"done": false,
		"archived": false,
		"order": 0,
		"last_motion": "",
	})

	# Sibling 1: scene_box.validate_scene_repository with scene floor_uids="bad" + host_views active_floor_uid
	var bad_sb_world := {
		"catalog": {"floors": [{"floor_uid": "11111111111111111111111111111111"}]},
		"modules": {
			"version": 2,
			"entries": {
				"scene_box": {
					"version": 2,
					"state": {
						"schema_version": 2,
						"entry_scene_uid": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
						"scenes": [{
							"uid": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
							"name": "Main",
							"floor_uids": "bad",
						}],
						"host_views": {
							"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": {
								"active_floor_uid": "11111111111111111111111111111111",
							}
						},
					},
				}
			},
		},
	}
	var g5_sb_res: Dictionary = wb_g5.scene_box().validate_scene_repository(bad_sb_world)

	# Sibling 2: grid_alignment.patch_config with cyclic world state directly in _world
	var cyc_ga_arr := []
	cyc_ga_arr.append(cyc_ga_arr)
	wb_g5.get_world()["modules"]["entries"]["grid_alignment"] = {
		"version": 1,
		"state": {"version": 1, "cell_size": 64.0, "snap_enabled": true, "offset": cyc_ga_arr, "color": [0.5, 0.5, 0.5, 1.0], "line_width": 1.0, "snap_strength": 0.1},
	}
	var g5_ga_res: Variant = wb_g5.grid_alignment().patch_config({"snap_enabled": false})

	results["gap05_corrupted_state_casts_ok"] = (
		g5_dice_ws is Dictionary and not bool((g5_dice_ws as Dictionary).get("ok", true)) and str((g5_dice_ws as Dictionary).get("reason", "")) == "invalid_dice_workspace"
		and g5_dice_combos is Dictionary and not bool((g5_dice_combos as Dictionary).get("ok", true)) and str((g5_dice_combos as Dictionary).get("reason", "")) == "dice_workspace_combos_invalid"
		and g5_dice_null_ws is Dictionary and not bool((g5_dice_null_ws as Dictionary).get("ok", true)) and str((g5_dice_null_ws as Dictionary).get("reason", "")) == "invalid_dice_workspace"
		and g5_rp_defs is Dictionary and not bool((g5_rp_defs as Dictionary).get("ok", true)) and str((g5_rp_defs as Dictionary).get("reason", "")) == "invalid_resource_pool_definitions"
		and g5_rp_stamps is Dictionary and not bool((g5_rp_stamps as Dictionary).get("ok", true)) and str((g5_rp_stamps as Dictionary).get("reason", "")) == "invalid_adjustment_stamps_type"
		and g5_cl_auto is Dictionary and not bool((g5_cl_auto as Dictionary).get("ok", true)) and str((g5_cl_auto as Dictionary).get("reason", "")) == "invalid_checklist_rows_type"
		and g5_cl_uid is Dictionary and not bool((g5_cl_uid as Dictionary).get("ok", true)) and str((g5_cl_uid as Dictionary).get("reason", "")) == "invalid_checklist_rows_type"
		and not bool(g5_sb_res.get("ok", true))
		and g5_ga_res is Dictionary and not bool((g5_ga_res as Dictionary).get("ok", true))
	)
	results["gap05_detail"] = {
		"dice_ws": g5_dice_ws,
		"dice_combos": g5_dice_combos,
		"dice_null_ws": g5_dice_null_ws,
		"rp_defs": g5_rp_defs,
		"rp_stamps": g5_rp_stamps,
		"cl_auto": g5_cl_auto,
		"cl_uid": g5_cl_uid,
		"sb": g5_sb_res,
		"ga": g5_ga_res,
	}

	# 11. GAP-06: 24-level binary diamond DAG (25 dicts) bounded traversal & non-shared budget across 1500-key calls
	var dag24 := {"leaf": 1}
	for _d: int in range(24):
		dag24 = {"l": dag24, "r": dag24}
	var dag13 := {"leaf": 1}
	for _d13: int in range(13):
		dag13 = {"l": dag13, "r": dag13}

	var wb_g6 = sdk.create_world_builder(sdk.create_session(MockHost.new(), {}), 150.0)
	wb_g6._session.get_logger().set_emit_to_engine(false)
	wb_g6.set_enabled_modules(["dnd_opportunity", "backpack", "character_roster", "checklist", "resource_pool", "dice", "grid_alignment"])
	var g6_eid: String = wb_g6.add_token("g6_u1", "Hero", Vector2(10, 10), Vector2(64, 64), "")

	var dnd_sdk = wb_g6.dnd_opportunity()
	var t0: int = Time.get_ticks_msec()
	var g6_dnd_val: Variant = dnd_sdk.validate_state(dag24)
	var t_dnd_val: int = Time.get_ticks_msec() - t0
	var g6_dnd_arr: Variant = dnd_sdk.validate_state({"combined": 1, "sheets": {"schema": 1, "cards": {}, "extra": [dag24]}, "encounter": {}})
	var g6_dnd_nest: Variant = dnd_sdk.validate_state({"combined": 1, "sheets": {"schema": 1, "cards": {}, "extra": {"nested": dag24}}, "encounter": {}})

	t0 = Time.get_ticks_msec()
	var g6_dnd_cfg: Variant = dnd_sdk.configure_dnd_opportunity(dag24)
	var t_dnd_cfg: int = Time.get_ticks_msec() - t0

	var bp_sdk = wb_g6.backpack()
	var bp_dag_item := {"name": "P", "note": "", "qty": 1, "extra": dag24}
	var bp_dag_arr_item := {"name": "P", "note": "", "qty": 1, "extra": [dag24]}
	var bp_dag_nest_item := {"name": "P", "note": "", "qty": 1, "extra": {"nested": dag24}}
	t0 = Time.get_ticks_msec()
	var g6_bp_val: Variant = bp_sdk.validate_item(bp_dag_item)
	var t_bp_val: int = Time.get_ticks_msec() - t0

	t0 = Time.get_ticks_msec()
	var g6_bp_make: Variant = bp_sdk.make_item("P", 1, "", {"extra": dag24})
	var t_bp_make: int = Time.get_ticks_msec() - t0
	var g6_bp_make_arr: Variant = bp_sdk.make_item("P", 1, "", {"extra": [dag24]})
	var g6_bp_make_nest: Variant = bp_sdk.make_item("P", 1, "", {"extra": {"nested": dag24}})

	t0 = Time.get_ticks_msec()
	var g6_bp_add: Variant = bp_sdk.add_item(g6_eid, bp_dag_item, 0)
	var t_bp_add: int = Time.get_ticks_msec() - t0
	var g6_bp_add_arr: Variant = bp_sdk.add_item(g6_eid, bp_dag_arr_item, 0)
	var g6_bp_add_nest: Variant = bp_sdk.add_item(g6_eid, bp_dag_nest_item, 0)

	var cr_sdk = wb_g6.character_roster()
	t0 = Time.get_ticks_msec()
	var g6_cr_make: Variant = cr_sdk.make_member_state(dag24)
	var t_cr_make: int = Time.get_ticks_msec() - t0
	var g6_cr_make_arr: Variant = cr_sdk.make_member_state({"a": [dag24]})
	var g6_cr_make_nest: Variant = cr_sdk.make_member_state({"a": {"nested": dag24}})

	var cl_sdk_g6 = wb_g6.checklist()
	wb_g6.get_world()["modules"]["entries"]["checklist"] = {
		"version": 1,
		"state": {"schema": 2, "rows": dag24},
	}
	t0 = Time.get_ticks_msec()
	var g6_cl_short: Variant = cl_sdk_g6.add_row("", {"title": "T"})
	var t_cl_short: int = Time.get_ticks_msec() - t0

	var valid_cl_row: Dictionary = cl_sdk_g6.make_row("T")
	t0 = Time.get_ticks_msec()
	var g6_cl_full_24: Variant = cl_sdk_g6.add_row("", valid_cl_row)
	var t_cl_full_24: int = Time.get_ticks_msec() - t0

	var cl_clone_b24 := [32768, false]
	t0 = Time.get_ticks_msec()
	var g6_cl_clone_24: Variant = cl_sdk_g6._safe_clone_dict(dag24, 0, [], cl_clone_b24)
	var t_cl_clone_24: int = Time.get_ticks_msec() - t0

	var rp_sdk_g6 = wb_g6.resource_pool()
	wb_g6.get_world()["modules"]["entries"]["resource_pool"] = {
		"version": 1,
		"state": {"schema_version": 1, "definitions": dag24},
	}
	t0 = Time.get_ticks_msec()
	var g6_rp_def_24: Variant = rp_sdk_g6.define_resource("hp", "HP", 10.0)
	var t_rp_def_24: int = Time.get_ticks_msec() - t0

	var rp_clone_b24 := [32768, false]
	t0 = Time.get_ticks_msec()
	var g6_rp_clone_24: Variant = rp_sdk_g6._safe_clone_dict(dag24, 0, [], rp_clone_b24)
	var t_rp_clone_24: int = Time.get_ticks_msec() - t0

	# Test dag13 (exceeds 32768 visits, < MAX_MODULE_ENTRY_BYTES) end-to-end through wb.set_module_state -> get_state -> _safe_clone_var
	wb_g6.set_module_state("checklist", 1, {"schema": 2, "rows": dag13})
	t0 = Time.get_ticks_msec()
	var g6_cl_13: Variant = cl_sdk_g6.add_row("", valid_cl_row)
	var t_cl_13: int = Time.get_ticks_msec() - t0

	wb_g6.set_module_state("resource_pool", 1, {"schema_version": 1, "definitions": dag13})
	t0 = Time.get_ticks_msec()
	var g6_rp_13: Variant = rp_sdk_g6.define_resource("hp", "HP", 10.0)
	var t_rp_13: int = Time.get_ticks_msec() - t0

	wb_g6.set_module_state("dnd_opportunity", 1, {"combined": 1, "sheets": {"schema": 1, "cards": {}, "extra": dag13}, "encounter": {}})
	t0 = Time.get_ticks_msec()
	var g6_dnd_ed_13: Variant = dnd_sdk.set_edition(2024)
	var t_dnd_ed_13: int = Time.get_ticks_msec() - t0

	var max_elapsed_ms: int = maxi(
		maxi(maxi(t_dnd_val, t_dnd_cfg), maxi(t_bp_val, t_bp_make)),
		maxi(
			maxi(maxi(t_bp_add, t_cr_make), maxi(t_cl_short, t_cl_full_24)),
			maxi(maxi(t_cl_clone_24, t_rp_def_24), maxi(t_rp_clone_24, maxi(maxi(t_cl_13, t_rp_13), t_dnd_ed_13)))
		)
	)

	var shapes_ok: bool = (
		g6_dnd_val is Dictionary and not bool((g6_dnd_val as Dictionary).get("ok", true))
		and str((g6_dnd_val as Dictionary).get("reason", "")) == "invalid_dnd_encounter_keys"
		and g6_dnd_arr is Dictionary and not bool((g6_dnd_arr as Dictionary).get("ok", true))
		and str((g6_dnd_arr as Dictionary).get("reason", "")) == "dnd_opportunity_state_too_large"
		and g6_dnd_nest is Dictionary and not bool((g6_dnd_nest as Dictionary).get("ok", true))
		and str((g6_dnd_nest as Dictionary).get("reason", "")) == "dnd_opportunity_state_too_large"
		and g6_dnd_cfg is Dictionary and not bool((g6_dnd_cfg as Dictionary).get("ok", true))
		and g6_bp_val is Dictionary and not bool((g6_bp_val as Dictionary).get("ok", true))
		and g6_bp_make is Dictionary and str((g6_bp_make as Dictionary).get("name", "")) == "P" and not (g6_bp_make as Dictionary).has("extra") and not (g6_bp_make as Dictionary).has(null)
		and g6_bp_make_arr is Dictionary and str((g6_bp_make_arr as Dictionary).get("name", "")) == "P" and not (g6_bp_make_arr as Dictionary).has("extra") and not (g6_bp_make_arr as Dictionary).has(null)
		and g6_bp_make_nest is Dictionary and str((g6_bp_make_nest as Dictionary).get("name", "")) == "P" and not (g6_bp_make_nest as Dictionary).has("extra") and not (g6_bp_make_nest as Dictionary).has(null)
		and g6_bp_add is Dictionary and not bool((g6_bp_add as Dictionary).get("ok", true))
		and g6_bp_add_arr is Dictionary and not bool((g6_bp_add_arr as Dictionary).get("ok", true))
		and g6_bp_add_nest is Dictionary and not bool((g6_bp_add_nest as Dictionary).get("ok", true))
		and g6_cr_make is Dictionary and (g6_cr_make as Dictionary).is_empty()
		and g6_cr_make_arr is Dictionary and (g6_cr_make_arr as Dictionary).is_empty()
		and g6_cr_make_nest is Dictionary and (g6_cr_make_nest as Dictionary).is_empty()
		and g6_cl_short is Dictionary and not bool((g6_cl_short as Dictionary).get("ok", true))
		and g6_cl_full_24 is Dictionary and g6_cl_full_24.has("ok")
		and g6_cl_clone_24 is Dictionary and bool(cl_clone_b24[1]) and not (g6_cl_clone_24 as Dictionary).has(null)
		and g6_rp_def_24 is Dictionary and g6_rp_def_24.has("ok")
		and g6_rp_clone_24 is Dictionary and bool(rp_clone_b24[1]) and not (g6_rp_clone_24 as Dictionary).has(null)
		and g6_cl_13 is Dictionary and not bool((g6_cl_13 as Dictionary).get("ok", true)) and str((g6_cl_13 as Dictionary).get("reason", "")) == "checklist_rows_too_large"
		and g6_rp_13 is Dictionary and not bool((g6_rp_13 as Dictionary).get("ok", true)) and str((g6_rp_13 as Dictionary).get("reason", "")) == "resource_pool_state_too_large"
		and g6_dnd_ed_13 is Dictionary and not bool((g6_dnd_ed_13 as Dictionary).get("ok", true)) and str((g6_dnd_ed_13 as Dictionary).get("reason", "")) == "dnd_opportunity_state_too_large"
	)

	# Verify consecutive 1500-key normal clones do NOT share or leak budget across calls
	var dict1500 := {}
	for k15: int in range(1500):
		dict1500["k_%04d" % k15] = k15
	var seq_ok: bool = true
	for _rep: int in range(3):
		var c_dnd: Dictionary = dnd_sdk._safe_clone_dict(dict1500)
		var c_bp: Dictionary = bp_sdk.make_item("P", 1, "", dict1500)
		var c_cr: Dictionary = cr_sdk.make_member_state(dict1500)
		var c_cl: Dictionary = cl_sdk_g6._safe_clone_dict(dict1500)
		var c_rp: Dictionary = rp_sdk_g6._safe_clone_dict(dict1500)
		var c_dice: Dictionary = wb_g6.dice()._safe_clone_dict(dict1500)
		var c_ga: Dictionary = wb_g6.grid_alignment()._safe_clone_dict(dict1500)
		if (
			c_dnd.size() != 1500
			or c_bp.size() != 1503
			or (c_cr.get("known_by", {}) as Dictionary).size() != 1500
			or c_cl.size() != 1500
			or c_rp.size() != 1500
			or c_dice.size() != 1500
			or c_ga.size() != 1500
		):
			seq_ok = false
			break

	results["gap06_dag24_bounded_ok"] = shapes_ok and seq_ok and (max_elapsed_ms < 500)
	results["gap06_detail"] = {
		"shapes_ok": shapes_ok,
		"seq_ok": seq_ok,
		"max_elapsed_ms": max_elapsed_ms,
		"timings_ms": {
			"dnd_val": t_dnd_val,
			"dnd_cfg": t_dnd_cfg,
			"bp_val": t_bp_val,
			"bp_make": t_bp_make,
			"bp_add": t_bp_add,
			"cr_make": t_cr_make,
			"cl_short": t_cl_short,
			"cl_full_24": t_cl_full_24,
			"cl_clone_24": t_cl_clone_24,
			"rp_def_24": t_rp_def_24,
			"rp_clone_24": t_rp_clone_24,
			"cl_13": t_cl_13,
			"rp_13": t_rp_13,
			"dnd_ed_13": t_dnd_ed_13,
		},
		"reasons": {
			"dnd_val": (g6_dnd_val as Dictionary).get("reason", ""),
			"dnd_cfg": (g6_dnd_cfg as Dictionary).get("reason", ""),
			"bp_val": (g6_bp_val as Dictionary).get("reason", ""),
			"bp_add": (g6_bp_add as Dictionary).get("reason", ""),
			"cl_short": (g6_cl_short as Dictionary).get("reason", ""),
			"cl_13": (g6_cl_13 as Dictionary).get("reason", ""),
			"rp_13": (g6_rp_13 as Dictionary).get("reason", ""),
			"dnd_ed_13": (g6_dnd_ed_13 as Dictionary).get("reason", ""),
		},
	}

	# 12. Iteration 8 Regressions: 16-slot backpack, 256-def resource_pool, 128-row checklist, zero null-key synthesis & valid null preservation
	var wb_r8 = sdk.create_world_builder(sdk.create_session(MockHost.new(), {}), 150.0)
	wb_r8._session.get_logger().set_emit_to_engine(false)
	wb_r8.set_enabled_modules(["backpack", "resource_pool", "checklist", "character_roster", "dnd_opportunity", "dice", "grid_alignment"])
	var r8_uid: String = wb_r8.add_token("r8_u1", "PackHero", Vector2(20, 20), Vector2(64, 64), "")
	var r8_bp = wb_r8.backpack()
	var big_arr := []
	for bi: int in range(450):
		big_arr.append(bi)
	var bp_16_ok: bool = true
	for slot_i: int in range(16):
		var it: Dictionary = r8_bp.make_item("I_%02d" % slot_i, 1, "", {"arr": big_arr.duplicate()})
		var add_r: Dictionary = r8_bp.add_item(r8_uid, it, slot_i)
		if not bool(add_r.get("ok", false)):
			bp_16_ok = false
			break
	var bp_16_slots: Dictionary = {}
	for rc: Variant in wb_r8.get_entity(r8_uid).get("components", []):
		if rc is Dictionary and str((rc as Dictionary).get("script", "")).ends_with("comp_backpack.gd"):
			bp_16_slots = ((rc as Dictionary).get("state", {}) as Dictionary).get("slots", {}) as Dictionary
			# Inject oversized state directly into comp_backpack to verify fail-closed backpack_state_too_large
			((rc as Dictionary)["state"] as Dictionary)["slots"] = dag13
			break
	var bp_over_res: Dictionary = r8_bp.add_item(r8_uid, r8_bp.make_item("Overflow", 1), 0)
	results["r8_backpack_16_slots_ok"] = (
		bp_16_ok
		and bp_16_slots.size() == 16
		and not bool(bp_over_res.get("ok", true))
		and str(bp_over_res.get("reason", "")) == "backpack_state_too_large"
	)

	var r8_rp = wb_r8.resource_pool()
	var full_defs := {}
	var full_stamps := {}
	for ri: int in range(256):
		var rid: String = "resource_pool:res_%03d" % ri
		full_defs[rid] = r8_rp.make_definition(rid, "Res %d" % ri, 10.0)
		full_stamps[rid] = "%032x" % (ri + 1)
	var rp_cfg_256: Dictionary = r8_rp.configure_resource_pool({"schema_version": 1, "definitions": full_defs, "adjustment_stamps": full_stamps})
	var rp_upd_256: Dictionary = r8_rp.define_resource("res_000", "R0_updated", 20.0)
	var rp_st_after: Dictionary = r8_rp.get_state()
	results["r8_resource_pool_256_ok"] = (
		bool(rp_cfg_256.get("ok", false))
		and bool(rp_upd_256.get("ok", false))
		and is_equal_approx(float((((rp_st_after.get("definitions", {}) as Dictionary).get("resource_pool:res_000", {}) as Dictionary)).get("maximum", 0.0)), 20.0)
		and (rp_st_after.get("adjustment_stamps", {}) as Dictionary).size() == 256
	)

	var r8_cl = wb_r8.checklist()
	var cl_127_rows := {}
	var extra_ids := []
	for ei: int in range(20):
		extra_ids.append("%032x" % (ei + 1000))
	var main_eid: String = "%032x" % 999
	for ci: int in range(127):
		var cid: String = "%032x" % (ci + 1)
		cl_127_rows[cid] = r8_cl.make_row("Row %d" % ci, {"entity_id": main_eid, "more_entity_ids": extra_ids})
	var cl_cfg_127: Dictionary = r8_cl.configure_checklist({"schema": 2, "rows": cl_127_rows})
	var cl_add_128: Dictionary = r8_cl.add_row("%032x" % 128, r8_cl.make_row("Row 128", {"entity_id": main_eid, "more_entity_ids": extra_ids}))
	results["r8_checklist_128_rows_ok"] = (
		bool(cl_cfg_127.get("ok", false))
		and bool(cl_add_128.get("ok", false))
		and (r8_cl.get_state().get("rows", {}) as Dictionary).size() == 128
	)

	# Verify zero null-key synthesis / spurious null elements on budget exhaustion AND depth>=32, plus valid null value preservation
	var cloners_7: Array = [
		wb_r8.backpack(),
		wb_r8.resource_pool(),
		wb_r8.checklist(),
		wb_r8.character_roster(),
		wb_r8.dnd_opportunity(),
		wb_r8.dice(),
		wb_r8.grid_alignment(),
	]
	var deep33 := {"leaf": 1}
	for _dp: int in range(33):
		deep33 = {"n": deep33}
	var null_synth_ok: bool = true
	for cln: Variant in cloners_7:
		var small_b := [10, false]
		var out_b: Dictionary = cln._safe_clone_dict({"a": 1, "b": 2, "c": 3, "d": 4, "e": [1, 2, 3, 4]}, 0, [], small_b)
		if not bool(small_b[1]) or out_b.has(null):
			null_synth_ok = false
			break
		for ov: Variant in out_b.values():
			if ov == null:
				null_synth_ok = false
				break
			if ov is Array:
				for elem: Variant in ov as Array:
					if elem == null:
						null_synth_ok = false
						break
		var depth_b := [4096, false]
		var out_d: Dictionary = cln._safe_clone_dict(deep33, 0, [], depth_b)
		if not bool(depth_b[1]) or out_d.has(null):
			null_synth_ok = false
			break
		var cur_n: Variant = out_d
		for _step: int in range(34):
			if cur_n is Dictionary:
				if (cur_n as Dictionary).has(null):
					null_synth_ok = false
					break
				cur_n = (cur_n as Dictionary).get("n", {})
			else:
				break
		var valid_b := [64, false]
		var out_v: Dictionary = cln._safe_clone_dict({"valid_null": null, "arr_null": [1, null, 2]}, 0, [], valid_b)
		if bool(valid_b[1]) or not out_v.has("valid_null") or out_v["valid_null"] != null or (out_v["arr_null"] as Array).size() != 3 or (out_v["arr_null"] as Array)[1] != null:
			null_synth_ok = false
			break
	results["r8_zero_null_synthesis_ok"] = null_synth_ok

	# 13. Iteration 9 Regressions (GAP-07, GAP-08, GAP-09)
	var dnd_r9 = wb_r8.dnd_opportunity()
	var t_cyc0: int = Time.get_ticks_msec()
	var dag24_is_cyc: bool = bool(dnd_r9._has_cycle(dag24))
	var t_dag24_cyc_ms: int = Time.get_ticks_msec() - t_cyc0

	# True cycles (direct, nested, array, dict-key) and depth > 32
	var cyc_direct := {}
	cyc_direct["self"] = cyc_direct
	var cyc_arr := []
	cyc_arr.append(cyc_arr)
	var cyc_key_k := {}
	var cyc_key_d := {}
	cyc_key_d[cyc_key_k] = 1
	cyc_key_k["back"] = cyc_key_d
	var cyc_direct_r: Dictionary = dnd_r9.validate_state(cyc_direct)
	var cyc_nested_r: Dictionary = dnd_r9.validate_state({"combined": 1, "sheets": {"schema": 1, "cards": {}, "extra": cyc_direct}, "encounter": {}})
	var cyc_arr_r: Dictionary = dnd_r9.validate_state({"combined": 1, "sheets": {"schema": 1, "cards": {}, "extra": cyc_arr}, "encounter": {}})
	var cyc_key_r: Dictionary = dnd_r9.validate_state({"combined": 1, "sheets": {"schema": 1, "cards": {}, "extra": cyc_key_d}, "encounter": {}})
	var cyc_deep_r: Dictionary = dnd_r9.validate_state({"combined": 1, "sheets": {"schema": 1, "cards": {}, "extra": deep33}, "encounter": {}})
	var true_cycles_ok: bool = (
		not dag24_is_cyc
		and t_dag24_cyc_ms < 5
		and str(cyc_direct_r.get("reason", "")) == "cyclic_dnd_opportunity_state"
		and str(cyc_nested_r.get("reason", "")) == "cyclic_dnd_opportunity_state"
		and str(cyc_arr_r.get("reason", "")) == "cyclic_dnd_opportunity_state"
		and str(cyc_key_r.get("reason", "")) == "cyclic_dnd_opportunity_state"
		and str(cyc_deep_r.get("reason", "")) == "cyclic_dnd_opportunity_state"
	)

	# Full-capacity encounter (256 profiles + 256 actions + 256 turns) and 256 effects
	var enc_256_profiles := {}
	var enc_256_actions := {}
	var enc_256_turns := {}
	var enc_256_effects := {}
	for ei9: int in range(256):
		var e_uid: String = "%032x" % (ei9 + 1)
		var t_uid: String = "%032x" % (ei9 + 1001)
		enc_256_profiles[e_uid] = {"ac": 15, "bonus": 2, "shield": false}
		enc_256_turns[e_uid] = ei9 + 1
		enc_256_actions[e_uid] = {
			"id": e_uid,
			"caster": e_uid,
			"target": t_uid,
			"kind": "attack",
			"request": "wf-" + e_uid,
			"stage": "offer",
			"original": {"total": 18, "face": 14, "base_ac": 15},
			"outcome": {},
			"ticket": {"costs": {"reaction": 1}},
			"by": "host",
			"turn": "1",
			"ac": 15,
			"bonus": 2,
		}
		var eff_d := {}
		for ek_i: int in range(10):
			eff_d["f%d" % ek_i] = ek_i
		enc_256_effects[e_uid] = eff_d

	var enc_256_res: Dictionary = dnd_r9.validate_encounter({
		"profiles": enc_256_profiles,
		"actions": enc_256_actions,
		"effects": {},
		"turns": enc_256_turns,
		"marks": {},
		"refills": {},
		"combat": "c1",
	})
	var eff_256_res: Dictionary = dnd_r9.validate_encounter({
		"profiles": {},
		"actions": {},
		"effects": enc_256_effects,
		"turns": {},
		"marks": {},
		"refills": {},
		"combat": "c1",
	})

	# Full combined: 2 (64 cards w/ 32 notes + 256 health bindings/events + 256 encounter entries)
	var cards_64 := {}
	var birth64: String = "0".repeat(64)
	for ci9: int in range(64):
		var c_uid: String = "%032x" % (ci9 + 5000)
		var notes_32 := {}
		for ni9: int in range(32):
			var src: String = "mod_%02d" % ni9
			notes_32[src + "/inventory"] = {"source": src, "kind": "inventory", "description": "item %d" % ni9}
		cards_64[c_uid] = {
			"id": c_uid,
			"edition": "2014",
			"owner": "host",
			"access": true,
			"revision": 1,
			"birth": birth64,
			"form": {
				"name": "Hero %d" % ci9,
				"job": "fighter",
				"race": "human",
				"background": "soldier",
				"source": "standard_array",
				"scores": [15, 14, 13, 12, 10, 8],
				"skills": ["athletics"],
				"replace": {},
				"expert": [],
				"enemy": "",
				"terrain": "",
			},
			"steps": [],
			"prepared": [],
			"offered": 1,
			"entity": "",
			"work": [],
			"notes": notes_32,
		}
	var health_binds := {}
	var health_events := {}
	for hi9: int in range(256):
		var h_uid: String = "%032x" % (hi9 + 8000)
		health_binds[h_uid] = {"die": 8, "modifier": 2, "applied_level": 5}
		health_events[h_uid] = {"missiles": 3, "authority": {"revision": 1}}

	var comb2_res: Dictionary = dnd_r9.validate_state({
		"combined": 2,
		"sheets": {"schema": 1, "cards": cards_64},
		"health": {"bindings": health_binds, "events": health_events},
		"encounter": {
			"profiles": enc_256_profiles,
			"actions": enc_256_actions,
			"effects": enc_256_effects,
			"turns": enc_256_turns,
			"marks": {},
			"refills": {},
			"combat": "c2",
		},
	})
	var comb2_data: Dictionary = comb2_res.get("data", {}) as Dictionary
	var comb2_ok: bool = (
		bool(enc_256_res.get("ok", false))
		and bool(eff_256_res.get("ok", false))
		and bool(comb2_res.get("ok", false))
		and ((comb2_data.get("sheets", {}) as Dictionary).get("cards", {}) as Dictionary).size() == 64
		and ((comb2_data.get("health", {}) as Dictionary).get("bindings", {}) as Dictionary).size() == 256
		and ((comb2_data.get("health", {}) as Dictionary).get("events", {}) as Dictionary).size() == 256
		and ((comb2_data.get("encounter", {}) as Dictionary).get("actions", {}) as Dictionary).size() == 256
		and ((comb2_data.get("encounter", {}) as Dictionary).get("effects", {}) as Dictionary).size() == 256
	)

	# GAP-07: rests with 2500 claims + start preserved intact (no silent wiping), and dag13 fails closed
	var big_claims := {}
	for cli9: int in range(2500):
		big_claims["%032x" % (cli9 + 10000)] = {"face": 6, "slots": [1, 2], "review": {"minute": 10}}
	var rest_uid: String = "%032x" % 77777
	var big_rest_res: Dictionary = dnd_r9.validate_state({
		"combined": 1,
		"sheets": {
			"schema": 1,
			"cards": {},
			"rests": {
				rest_uid: {
					"claims": big_claims,
					"start": 10,
				},
			},
		},
		"encounter": {},
	})
	var br_rest_entry: Dictionary = (((big_rest_res.get("data", {}) as Dictionary).get("sheets", {}) as Dictionary).get("rests", {}) as Dictionary).get(rest_uid, {}) as Dictionary
	var dag_rest_res: Dictionary = dnd_r9.validate_state({
		"combined": 1,
		"sheets": {"schema": 1, "cards": {}, "rests": {rest_uid: {"extra": dag13}}},
		"encounter": {},
	})
	var big_health_binds := {}
	for hbi: int in range(256):
		var hb_d := {"die": 8, "modifier": 2, "applied_level": 5}
		for hk_i: int in range(20):
			hb_d["ex_%d" % hk_i] = hk_i
		big_health_binds["%032x" % (hbi + 20000)] = hb_d
	var big_health_res: Dictionary = dnd_r9.validate_state({
		"combined": 2,
		"sheets": {"schema": 1, "cards": {}},
		"health": {"bindings": big_health_binds, "events": {}},
		"encounter": {},
	})
	var big_hb_out: Dictionary = ((big_health_res.get("data", {}) as Dictionary).get("health", {}) as Dictionary).get("bindings", {}) as Dictionary
	var dag_hb_res: Dictionary = dnd_r9.validate_state({
		"combined": 2,
		"sheets": {"schema": 1, "cards": {}},
		"health": {"bindings": {rest_uid: {"die": 8, "extra": dag13}}, "events": {}},
		"encounter": {},
	})
	var dag_eff_res: Dictionary = dnd_r9.validate_encounter({
		"profiles": {},
		"actions": {},
		"effects": {rest_uid: dag13},
		"turns": {},
		"marks": {},
		"refills": {},
		"combat": "c1",
	})
	var gap07_ok: bool = (
		bool(big_rest_res.get("ok", false))
		and int(br_rest_entry.get("start", -1)) == 10
		and (br_rest_entry.get("claims", {}) as Dictionary).size() == 2500
		and not bool(dag_rest_res.get("ok", true))
		and str(dag_rest_res.get("reason", "")) == "dnd_opportunity_state_too_large"
		and bool(big_health_res.get("ok", false))
		and big_hb_out.size() == 256
		and not bool(dag_hb_res.get("ok", true))
		and str(dag_hb_res.get("reason", "")) == "dnd_opportunity_state_too_large"
		and not bool(dag_eff_res.get("ok", true))
		and str(dag_eff_res.get("reason", "")) == "dnd_opportunity_state_too_large"
	)

	# GAP-09: standalone drawing.gd (_adapter == null) dag24 speed + zero null padding in drawing, floor_system, layer_stack
	var drawing_solo = sdk.create_plugin_sdk("drawing")
	var floor_solo = sdk.create_plugin_sdk("feature_floor_system")
	var layer_solo = sdk.create_plugin_sdk("feature_layer_stack")
	var t_dr0: int = Time.get_ticks_msec()
	var solo_draw_dag: Dictionary = drawing_solo.make_world_drawing_state([dag24])
	var solo_ink_dag: Dictionary = drawing_solo.make_entity_ink_state([dag24])
	var t_dr_dag_ms: int = Time.get_ticks_msec() - t_dr0
	var solo_strokes: Array = solo_draw_dag.get("strokes", []) as Array
	var solo_ink_strokes: Array = solo_ink_dag.get("strokes", []) as Array
	var solo_null_ok: bool = true
	for se: Variant in solo_strokes + solo_ink_strokes:
		if se == null:
			solo_null_ok = false
			break
		if se is Dictionary and (se as Dictionary).has(null):
			solo_null_ok = false
			break
	for fb_cln: Variant in [drawing_solo, floor_solo, layer_solo]:
		var fb_small_b := [10, false]
		var fb_out_b: Variant = fb_cln._bounded_fallback_clone({"a": 1, "b": 2, "c": 3, "d": 4, "e": [1, 2, 3, 4]}, 0, [], fb_small_b)
		if not bool(fb_small_b[1]) or not (fb_out_b is Dictionary) or (fb_out_b as Dictionary).has(null):
			solo_null_ok = false
			break
		for fv: Variant in (fb_out_b as Dictionary).values():
			if fv == null:
				solo_null_ok = false
				break
			if fv is Array:
				for fae: Variant in fv as Array:
					if fae == null:
						solo_null_ok = false
						break
		var fb_depth_b := [4096, false]
		var fb_out_d: Variant = fb_cln._bounded_fallback_clone(deep33, 0, [], fb_depth_b)
		if not bool(fb_depth_b[1]) or not (fb_out_d is Dictionary) or (fb_out_d as Dictionary).has(null):
			solo_null_ok = false
			break
		var cur_fb: Variant = fb_out_d
		for _step_fb: int in range(34):
			if cur_fb is Dictionary:
				if (cur_fb as Dictionary).has(null):
					solo_null_ok = false
					break
				cur_fb = (cur_fb as Dictionary).get("n", {})
			else:
				break
		var fb_valid_b := [64, false]
		var fb_out_v: Variant = fb_cln._bounded_fallback_clone({"valid_null": null, "arr_null": [1, null, 2]}, 0, [], fb_valid_b)
		if bool(fb_valid_b[1]) or not (fb_out_v is Dictionary):
			solo_null_ok = false
			break
		var fb_vd: Dictionary = fb_out_v as Dictionary
		if not fb_vd.has("valid_null") or fb_vd["valid_null"] != null or (fb_vd["arr_null"] as Array).size() != 3 or (fb_vd["arr_null"] as Array)[1] != null:
			solo_null_ok = false
			break

	results["gap07_08_09_ok"] = true_cycles_ok and comb2_ok and gap07_ok and solo_null_ok and (t_dr_dag_ms < 50)
	results["gap07_08_09_detail"] = {
		"true_cycles_ok": true_cycles_ok,
		"t_dag24_cyc_ms": t_dag24_cyc_ms,
		"enc_256_ok": bool(enc_256_res.get("ok", false)),
		"enc_256_reason": enc_256_res.get("reason", ""),
		"eff_256_ok": bool(eff_256_res.get("ok", false)),
		"eff_256_reason": eff_256_res.get("reason", ""),
		"comb2_ok": comb2_ok,
		"comb2_reason": comb2_res.get("reason", ""),
		"gap07_ok": gap07_ok,
		"big_rest_ok": bool(big_rest_res.get("ok", false)),
		"returned_claims": (br_rest_entry.get("claims", {}) as Dictionary).size(),
		"returned_start": br_rest_entry.get("start", -1),
		"dag_rest_reason": dag_rest_res.get("reason", ""),
		"solo_null_ok": solo_null_ok,
		"t_dr_dag_ms": t_dr_dag_ms,
	}

	# 14. GAP-10: Zero RefCounted ObjectDB leak across all 23 plugin SDKs (individually & combined) + freed WorldBuilder WeakRef safety
	var gap10_res: Dictionary = _run_gap10_leak_probes(sdk_scr)
	results["gap10_all23_zero_leak_ok"] = bool(gap10_res.get("ok", false))
	results["gap10_detail"] = gap10_res

	var f := FileAccess.open("res://probe_results.json", FileAccess.WRITE)
	f.store_string(JSON.stringify(results))
	f.close()
	quit(0)
'''


class TestTier5Adversarial(unittest.TestCase):
    run_dir: Path | None = None
    results: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(WORKSPACE_ROOT)
        godot_bin = cfg.godot_bin
        if godot_bin is None or not godot_bin.is_file():
            raise unittest.SkipTest("GODOT_BIN not configured in .env.local; skipping headless Godot tests")

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.run_dir = TEST_TMP_ROOT / f"tier5_adv_{uuid.uuid4().hex[:10]}"
        probe_dir = cls.run_dir / "probe_proj"
        probe_dir.mkdir(parents=True, exist_ok=True)
        (probe_dir / "project.godot").write_bytes(
            b'[gd_resource type="ProjectFile" format=3]\n\nconfig_version=5\n\n[application]\nconfig/name="Tier5Adv"\n'
        )
        shutil.copytree(SDK_DIR, probe_dir / "shared" / "sdk" / "fu_sdk")
        (probe_dir / "probe.gd").write_text(PROBE_GD, encoding="utf-8", newline="\n")

        env_root = cls.run_dir / "godot_env"
        appdata = env_root / "appdata"
        localappdata = env_root / "localappdata"
        temp_dir = env_root / "temp"
        for d in (appdata, localappdata, temp_dir):
            d.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["APPDATA"] = str(appdata)
        env["LOCALAPPDATA"] = str(localappdata)
        env["TEMP"] = str(temp_dir)
        env["TMP"] = str(temp_dir)

        log_path = cls.run_dir / "godot.log"
        proc = subprocess.run(
            [
                str(godot_bin),
                "--headless",
                "--quit",
                "--path",
                str(probe_dir),
                "--log-file",
                str(log_path),
                "--script",
                "res://probe.gd",
            ],
            cwd=str(probe_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        combined = "\n".join([proc.stdout or "", proc.stderr or "", log_text])
        log_errors = analyze_godot_logs(log_text, proc.stdout or "", proc.stderr or "")
        if proc.returncode != 0:
            raise RuntimeError(f"Tier 5 Godot probe exited {proc.returncode}:\n{combined}")
        if log_errors:
            raise AssertionError(f"Tier 5 Godot probe emitted errors/leaks: {log_errors}\n{combined}")
        cls.results = json.loads((probe_dir / "probe_results.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.run_dir is not None and cls.run_dir.exists():
            shutil.rmtree(cls.run_dir, ignore_errors=True)

    def test_bug04_pre_gate_ordering_under_skip(self) -> None:
        self.assertTrue(self.results["bug04_all_gates_before_args_ok"], msg=f"detail={self.results.get('bug04_detail')}")

    def test_bug06_dag_cloner_non_aliasing_and_cycle_safe(self) -> None:
        self.assertTrue(self.results["bug06_dag_non_aliasing_ok"])

    def test_bug09_v1_legacy_wrappers_enforce_module_registry_gates(self) -> None:
        self.assertTrue(self.results["bug09_v1_legacy_gates_ok"])

    def test_bug10_candidate_scene_box_conflict_and_portal_uid_case(self) -> None:
        self.assertTrue(self.results["bug10_candidate_scene_box_and_portal_uid_ok"])

    def test_gap01_simple_fog_configure_fog_cycle_safe(self) -> None:
        self.assertTrue(self.results["gap01_simple_fog_cycle_ok"])

    def test_gap02_checklist_make_row_cycle_and_bool_coerce_safe(self) -> None:
        self.assertTrue(self.results["gap02_checklist_make_row_safe_ok"])

    def test_gap03_70node_dag_isolation_across_remaining_cloners(self) -> None:
        self.assertTrue(self.results["gap03_70node_dag_isolation_ok"], msg=f"detail={self.results.get('gap03_detail')}")

    def test_gap04_v1_scene_box_manual_requires_parked(self) -> None:
        self.assertTrue(self.results["gap04_manual_requires_parked_ok"])

    def test_n2_module_registry_level_error_obeys_log_bus_host_caps(self) -> None:
        self.assertTrue(self.results["n2_host_warn_cap_under_level_error_ok"], msg=f"detail={self.results.get('n2_detail')}")

    def test_gap05_corrupted_state_casts_return_structured_errors(self) -> None:
        self.assertTrue(self.results["gap05_corrupted_state_casts_ok"], msg=f"detail={self.results.get('gap05_detail')}")

    def test_gap06_diamond_dag24_bounded_traversal(self) -> None:
        detail = self.results.get("gap06_detail", {})
        self.assertTrue(self.results.get("gap06_dag24_bounded_ok", False), msg=f"detail={detail}")
        self.assertLess(detail.get("max_elapsed_ms", 99999), 500, msg=f"detail={detail}")

    def test_r8_backpack_16_slots_and_fail_closed_exhaustion(self) -> None:
        self.assertTrue(self.results.get("r8_backpack_16_slots_ok", False))

    def test_r8_resource_pool_256_definition_update(self) -> None:
        self.assertTrue(self.results.get("r8_resource_pool_256_ok", False))

    def test_r8_checklist_128_rows_with_more_entity_ids(self) -> None:
        self.assertTrue(self.results.get("r8_checklist_128_rows_ok", False))

    def test_r8_zero_null_synthesis_on_cloner_exhaustion_and_depth(self) -> None:
        self.assertTrue(self.results.get("r8_zero_null_synthesis_ok", False))

    def test_gap07_08_09_dnd_capacity_non_truncation_and_drawing_solo_dag24(self) -> None:
        detail = self.results.get("gap07_08_09_detail", {})
        self.assertTrue(self.results.get("gap07_08_09_ok", False), msg=f"detail={detail}")
        self.assertLess(detail.get("t_dag24_cyc_ms", 99999), 5, msg=f"detail={detail}")
        self.assertLess(detail.get("t_dr_dag_ms", 99999), 50, msg=f"detail={detail}")

    def test_gap10_all23_plugins_zero_objectdb_leak(self) -> None:
        detail = self.results.get("gap10_detail", {})
        self.assertEqual(detail.get("plugin_count"), 23, msg=f"detail={detail}")
        self.assertEqual(detail.get("plain_5x_delta"), 0.0, msg=f"detail={detail}")
        self.assertEqual(detail.get("combined_5x_delta"), 0.0, msg=f"detail={detail}")
        per_plugin = detail.get("per_plugin_deltas", {})
        self.assertEqual(len(per_plugin), 23, msg=f"detail={detail}")
        for pid, delta in per_plugin.items():
            self.assertEqual(delta, 0.0, msg=f"Plugin {pid} leaked ObjectDB objects: delta={delta}, detail={detail}")
        self.assertTrue(detail.get("freed_core_weakref_safe", False), msg=f"detail={detail}")
        self.assertTrue(self.results.get("gap10_all23_zero_leak_ok", False), msg=f"detail={detail}")

    def test_gdscript_static_hygiene_sdk_and_console_mod(self) -> None:
        targets = sorted(SDK_DIR.rglob("*.gd")) + [WORKSPACE_ROOT / "mods" / "sdk-log-console" / "entry.gd"]
        self.assertGreaterEqual(len(targets), 32)
        for p in targets:
            raw = p.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"BOM found in {p}")
            self.assertNotIn(b"\r\n", raw, f"CRLF found in {p}")
            text = raw.decode("utf-8")
            stripped = strip_gdscript_comments(text)
            non_empty = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
            self.assertTrue(non_empty and non_empty[0] == "extends RefCounted", f"Missing top extends RefCounted in {p}")
            self.assertNotIn("class_name ", stripped, f"Forbidden class_name in {p}")
            self.assertNotIn("preload(", stripped, f"Forbidden preload( in {p}")
            self.assertNotIn("d:\\dnd", text.lower(), f"Hardcoded local path in {p}")
            self.assertNotIn("c:\\users", text.lower(), f"Hardcoded user path in {p}")


if __name__ == "__main__":
    unittest.main()
