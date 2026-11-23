"""Comprehensive headless Godot test suite for FuSdk v1.3.0 (Scene >> Floor >> Layer & Scene Box).

Covers:
1. v1.2 backward compatibility (`has_scenes_configured() == false`, no `scene_box` entry).
2. Full `Scene >> Floor >> Layer` lifecycle (`configure_entry_scene`, `add_scene`,
   `add_floor_to_scene`, `move_floor_to_scene` + single-floor guard, `set_active_scene`,
   `set_entry_scene`, `rename_scene`, `set_scene_cover_asset`, `set_scene_host_view`,
   `get_scene_layer_uid`, `get_floor_layers`, seamless `add_floor`/`set_active_floor`
   sync, and `MAX_SCENES = 64` cap).
3. Cross-scene / cross-floor `layer_uid_override` ownership fix in `world.members`.
4. `add_scene_box` & `attach_scene_box` invariants (`96x96` default, `[72, 256]` square
   clamping, `scale == Vector2.ONE`, `CompPermission` 3-way mapping, and
   `BoardToken.SCENE_BOX_CONFLICTS` + `entity_type == "map"` rejections).
5. `SceneRepository.prepare_state()` contract equivalence + lossless `var_to_bytes`/`bytes_to_var`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid

_TESTS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _TESTS_DIR.parent
_WORKSPACE_ROOT = _TOOLS_DIR.parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from fuvtt_devtools.env_config import load_config  # noqa: E402
from fuvtt_devtools.host_verifier import analyze_godot_logs  # noqa: E402

SDK_DIR = _WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk"
TEST_TMP_ROOT = _WORKSPACE_ROOT / ".cache" / "test_tmp"


_PROBE_GD = r'''extends SceneTree

const _SDK_PATH: String = "res://shared/sdk/fu_sdk/v1.gd"
const _COMP_SCENE_BOX: String = "res://modules/scene_box/comp_scene_box.gd"
const _COMP_UNIT: String = "res://scenes/entities/components/comp_unit.gd"


class _MockHost extends RefCounted:
	var warnings: Array = []

	func cancelled() -> bool:
		return false

	func report(_msg: String) -> void:
		pass

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
								{"layer_uid": map_uid, "name": "地图底图", "kind": "map", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
								{"layer_uid": entity_uid, "name": "实体", "kind": "entity", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
								{"layer_uid": obstacle_uid, "name": "障碍物", "kind": "obstacle", "visible": true, "locked": false, "persistent": true, "access": "host", "viewers": []},
							],
						}],
					},
				},
				"entity_state": {"version": 3, "entities": []},
				"members": [],
				"modules": {"version": 2, "entries": {}},
			},
		}


func _is_hex32(val: String) -> bool:
	if val.length() != 32:
		return false
	for i: int in range(32):
		var c: int = val.unicode_at(i)
		if not ((c >= 48 and c <= 57) or (c >= 97 and c <= 102)):
			return false
	return true


func _validate_scene_repository_state(world: Dictionary) -> String:
	var entries: Dictionary = world.get("modules", {}).get("entries", {})
	if not entries.has("scene_box"):
		return "missing_scene_box"
	var sb_entry: Dictionary = entries["scene_box"]
	if int(sb_entry.get("version", -1)) != 1:
		return "bad_entry_version"
	var raw: Dictionary = sb_entry.get("state", {})
	if int(raw.get("schema_version", 0)) != 2:
		return "unsupported_scene_box_schema"
	var entry_uid := str(raw.get("entry_scene_uid", ""))
	if not _is_hex32(entry_uid):
		return "invalid_entry_scene_uid"
	var raw_scenes: Variant = raw.get("scenes", null)
	if not (raw_scenes is Array) or (raw_scenes as Array).is_empty() or (raw_scenes as Array).size() > 64:
		return "invalid_scenes_list"
	var catalog_floors := {}
	for cf: Dictionary in world.get("catalog", {}).get("floors", []):
		catalog_floors[str(cf.get("floor_uid", ""))] = true
	var seen_uids := {}
	var seen_floors := {}
	var scene_floor_map := {}
	var cover_rx := RegEx.new()
	cover_rx.compile("^asset://[0-9a-f]{64}\\.(png|jpg|jpeg|webp|bmp)$")
	for item: Variant in raw_scenes as Array:
		if not (item is Dictionary):
			return "invalid_scene_entry"
		var srow := item as Dictionary
		var suid := str(srow.get("uid", ""))
		var sname := str(srow.get("name", "")).strip_edges()
		if not _is_hex32(suid) or seen_uids.has(suid) or sname.is_empty() or sname.length() > 96:
			return "invalid_scene_identity"
		var rfloors: Variant = srow.get("floor_uids", null)
		if not (rfloors is Array) or (rfloors as Array).is_empty():
			return "invalid_scene_floors"
		var this_floors := {}
		for fv: Variant in rfloors as Array:
			var fuid := str(fv)
			if not _is_hex32(fuid) or not catalog_floors.has(fuid) or seen_floors.has(fuid):
				return "duplicate_or_invalid_scene_floor"
			seen_floors[fuid] = suid
			this_floors[fuid] = true
		var def_f := str(srow.get("default_floor_uid", ""))
		if not this_floors.has(def_f):
			return "bad_default_floor_uid"
		var cov := str(srow.get("cover_asset", ""))
		if not cov.is_empty() and cover_rx.search(cov) == null:
			return "bad_cover_asset"
		seen_uids[suid] = true
		scene_floor_map[suid] = this_floors
	if seen_floors.size() != catalog_floors.size():
		return "unpartitioned_catalog_floors"
	if not seen_uids.has(entry_uid):
		return "entry_scene_not_in_list"
	var host_active := str(raw.get("host_active_scene_uid", ""))
	if not seen_uids.has(host_active):
		return "host_active_scene_not_in_list"
	var active_fl := str(world.get("catalog", {}).get("active_floor_uid", ""))
	if not (scene_floor_map[host_active] as Dictionary).has(active_fl):
		return "active_floor_not_in_host_active_scene"
	var vis: Variant = raw.get("visited_scenes", {})
	if not (vis is Dictionary) or (vis as Dictionary).size() > 128:
		return "invalid_visited_scenes"
	var views: Variant = raw.get("host_views", {})
	if not (views is Dictionary) or (views as Dictionary).size() > 64:
		return "invalid_host_views"
	for vk: Variant in (views as Dictionary).keys():
		if not seen_uids.has(str(vk)):
			return "unknown_view_scene_uid"
		var vrow := (views as Dictionary)[vk] as Dictionary
		if vrow.has("camera_pos") and not (vrow["camera_pos"] is Vector2 and (vrow["camera_pos"] as Vector2).is_finite()):
			return "invalid_view_camera_pos"
		if vrow.has("camera_zoom") and not (vrow["camera_zoom"] is Vector2 and (vrow["camera_zoom"] as Vector2).is_finite()):
			return "invalid_view_camera_zoom"
	return ""


func _find_diff(a: Variant, b: Variant, p: String) -> String:
	if typeof(a) != typeof(b):
		return "%s type mismatch" % p
	if a is Dictionary:
		var da := a as Dictionary
		var db := b as Dictionary
		if da.size() != db.size():
			return "%s dict size mismatch" % p
		for k: Variant in da.keys():
			if not db.has(k):
				return "%s missing key %s" % [p, str(k)]
			var sub := _find_diff(da[k], db[k], p + "." + str(k))
			if not sub.is_empty():
				return sub
		return ""
	if a is Array:
		var aa := a as Array
		var ab := b as Array
		if aa.size() != ab.size():
			return "%s array size mismatch" % p
		for i: int in range(aa.size()):
			var sub := _find_diff(aa[i], ab[i], "%s[%d]" % [p, i])
			if not sub.is_empty():
				return sub
		return ""
	if a is float:
		if not is_equal_approx(float(a), float(b)):
			return "%s float mismatch" % p
		return ""
	if a != b:
		return "%s value mismatch" % p
	return ""


func _member_floor_for(world: Dictionary, eid: String) -> String:
	for m: Variant in world.get("members", []):
		if m is Dictionary and str((m as Dictionary).get("entity_id", "")) == eid:
			return str((m as Dictionary).get("floor_uid", ""))
	return ""


func _find_entity(world: Dictionary, eid: String) -> Dictionary:
	for e: Variant in world.get("entity_state", {}).get("entities", []):
		if e is Dictionary and str((e as Dictionary).get("id", "")) == eid:
			return e as Dictionary
	return {}


func _write_json(path: String, payload: Dictionary) -> void:
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(payload))
		f.close()


func _initialize() -> void:
	var out_path := ""
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with("--out="):
			out_path = arg.substr(6)
	if out_path.is_empty():
		quit(2)
		return

	var sdk_script := load(_SDK_PATH) as Script
	if sdk_script == null:
		_write_json(out_path, {"ok": false, "reason": "failed_to_load_sdk"})
		quit(1)
		return
	var sdk: RefCounted = sdk_script.new()
	var results: Dictionary = {}

	# -------------------------------------------------------------------------
	# 1. Backward compatibility (v1.2 mode without scene calls)
	# -------------------------------------------------------------------------
	var h_compat := _MockHost.new()
	var s_compat = sdk.create_session(h_compat, {})
	var b_compat = sdk.create_world_builder(s_compat, 150.0)
	var compat_has_before: bool = b_compat.has_scenes_configured()
	var compat_fl2: String = b_compat.add_floor("2F", Color.WHITE, false)
	var compat_tok: String = b_compat.add_token("c_tok", "Hero", Vector2(150, 150), Vector2(100, 100), "")
	var compat_world: Dictionary = b_compat.get_world()
	results["compat"] = {
		"sdk_version": str(sdk_script.SDK_VERSION),
		"has_before": compat_has_before,
		"has_scene_box": compat_world.get("modules", {}).get("entries", {}).has("scene_box"),
		"floors_count": compat_world["catalog"]["floors"].size(),
		"fl2_ok": not compat_fl2.is_empty(),
		"tok_ok": not compat_tok.is_empty(),
		"warn_count": h_compat.warnings.size(),
	}

	# -------------------------------------------------------------------------
	# 2. Scene >> Floor >> Layer lifecycle + cross-floor layer_uid_override + Scene Box
	# -------------------------------------------------------------------------
	var digest64 := "a".repeat(64)
	var cover_a := "asset://%s.png" % digest64
	var cover_b := "asset://%s.webp" % ("b".repeat(64))

	var h_sc := _MockHost.new()
	var s_sc = sdk.create_session(h_sc, {})
	var b_sc = sdk.create_world_builder(s_sc, 150.0)  # source_to_world = 64/150

	var entry_suid: String = b_sc.configure_entry_scene("艾尔图瑞尔", "地上广场", cover_a)
	var plaza_fuid: String = b_sc.get_scene_default_floor_uid(entry_suid)
	var warns_after_normal_cfg: int = h_sc.warnings.size()

	# Seamless add_floor attaches to current active scene (entry_suid)
	var watchtower_fuid: String = b_sc.add_floor("瞭望塔顶层", Color.WHITE, false)

	# Second independent scene
	var dungeon_suid: String = b_sc.add_scene("亡者地牢", "地牢上层", Color(0.2, 0.3, 0.4), cover_b, false)
	var b1_fuid: String = b_sc.get_scene_default_floor_uid(dungeon_suid)
	var b2_fuid: String = b_sc.add_floor_to_scene(dungeon_suid, "地牢深层", Color(0.15, 0.2, 0.3), true, false)
	var b2_area_layer: String = b_sc.add_layer("毒雾区", "area", "all", b2_fuid)
	var b2_entity_layer: String = b_sc.get_scene_layer_uid(dungeon_suid, "entity", b2_fuid)
	var b2_obstacle_layer: String = b_sc.get_scene_layer_uid(dungeon_suid, "obstacle", b2_fuid)

	# Cross-scene / cross-floor placement while entry_suid / plaza_fuid is still active!
	var active_before_cross: String = b_sc.get_active_floor_uid()
	var cross_tok_id: String = b_sc.add_token("cross_t", "DeepGhoul", Vector2(300, 300), Vector2(150, 150), "", 0.0, Vector2.ONE, false, 32.0, false, {}, b2_entity_layer)
	var cross_wall_id: String = b_sc.add_segment_wall("cross_w", "DeepWall", Vector2(0, 0), Vector2(300, 0), 6.0, true, b2_obstacle_layer)

	# Switch active scene/floor and sync check
	var set_act_res: bool = b_sc.set_active_scene(dungeon_suid, b1_fuid, true)
	var cat_active_after_scene: String = b_sc.get_world()["catalog"]["active_floor_uid"]
	var set_act_fl_res: bool = b_sc.set_active_floor(plaza_fuid)
	var active_scene_after_fl: String = b_sc.get_active_scene_uid()

	# move_floor_to_scene + single-floor scene protection
	var move_b2_ok: bool = b_sc.move_floor_to_scene(b2_fuid, entry_suid, false)
	var move_b1_last_ok: bool = b_sc.move_floor_to_scene(b1_fuid, entry_suid, false)  # must fail!
	var scene_of_b2_after: String = b_sc.get_scene_for_floor(b2_fuid)

	# rename, default floor, entry scene, host_view, invalid cover sanitization
	var third_suid: String = b_sc.add_scene("酒馆", "大厅", Color.WHITE, "", false)
	var rename_ok: bool = b_sc.rename_scene(third_suid, "精灵之歌酒馆")
	var set_def_ok: bool = b_sc.set_scene_default_floor(entry_suid, watchtower_fuid)
	var set_entry_ok: bool = b_sc.set_entry_scene(third_suid)
	var set_view_ok: bool = b_sc.set_scene_host_view(third_suid, Vector2(300.0, 150.0), Vector2(1.5, 1.5), b_sc.get_scene_default_floor_uid(third_suid))
	var valid_cov_ok: bool = b_sc.set_scene_cover_asset(third_suid, cover_b)
	var bad_cov_res_ok: bool = b_sc.set_scene_cover_asset(third_suid, "res://assets/bad.png")
	b_sc.set_scene_cover_asset(third_suid, cover_b)  # restore valid cover after sanitization check

	# Scene Box entities (all 3 permission modes + size clamping + conflict guards)
	var box_pub_id: String = b_sc.add_scene_box("box_pub", "前往地牢", Vector2(150, 300), dungeon_suid, 1.5, cover_b, "visited_unlock", true, [], false, false, "")
	var box_sel_id: String = b_sc.add_scene_box("box_sel", "VIP酒馆包厢", Vector2(450, 300), third_suid, 0.5, "", "always_public", false, ["player_1", "player_2"], false, false, "")
	var box_host_id: String = b_sc.add_scene_box("box_host", "DM密室", Vector2(600, 300), dungeon_suid, 10.0, cover_a, "cover_only", false, [], true, true, b2_entity_layer)

	# Attach to existing plain object vs conflicts
	var plain_obj_id: String = b_sc.add_object_sprite("plain_prop", "Portal Chest", Vector2(200, 200), Vector2(40, 20), "")
	var attach_plain_ok: bool = b_sc.attach_scene_box(plain_obj_id, third_suid, cover_a, "visited_unlock", true)
	var attach_unit_on_box_ok: bool = b_sc.attach_unit_marker(plain_obj_id)
	var attach_portal_on_box_ok: bool = b_sc.attach_portal(plain_obj_id, "pair_1")
	var attach_vis_on_box_ok: bool = b_sc.attach_simple_vision(plain_obj_id, 300.0)
	var attach_light_on_box_ok: bool = b_sc.attach_simple_light(plain_obj_id, 300.0)

	var hero_tok_id: String = b_sc.add_token("hero1", "Knight", Vector2(100, 100), Vector2(150, 150), "")
	b_sc.attach_unit_marker(hero_tok_id)
	var attach_box_on_unit_ok: bool = b_sc.attach_scene_box(hero_tok_id, dungeon_suid)

	var map_ent_id: String = b_sc.add_map_tile("map_tile_1", "FloorMap", Vector2(500, 500), Vector2(1000, 1000), "")
	var map_ent_dict: Dictionary = _find_entity(b_sc.get_world(), map_ent_id)
	map_ent_dict["entity_type"] = "map"
	var attach_box_on_map_ok: bool = b_sc.attach_scene_box(map_ent_id, dungeon_suid)

	var sc_world: Dictionary = b_sc.get_world()
	var repo_err: String = _validate_scene_repository_state(sc_world)
	var encoded_sc: PackedByteArray = var_to_bytes(sc_world)
	var decoded_sc: Variant = bytes_to_var(encoded_sc)
	var roundtrip_diff: String = _find_diff(sc_world, decoded_sc, "$") if decoded_sc is Dictionary else "decode_not_dict"

	var sc_state: Dictionary = sc_world["modules"]["entries"]["scene_box"]["state"]
	var view_pos: Variant = sc_state.get("host_views", {}).get(third_suid, {}).get("camera_pos", Vector2.ZERO)

	var box_pub_ent: Dictionary = _find_entity(sc_world, box_pub_id)
	var box_sel_ent: Dictionary = _find_entity(sc_world, box_sel_id)
	var box_host_ent: Dictionary = _find_entity(sc_world, box_host_id)
	var attached_plain_ent: Dictionary = _find_entity(sc_world, plain_obj_id)

	results["scenes"] = {
		"entry_suid": entry_suid,
		"dungeon_suid": dungeon_suid,
		"third_suid": third_suid,
		"warns_after_normal_cfg": warns_after_normal_cfg,
		"plaza_fuid": plaza_fuid,
		"watchtower_fuid": watchtower_fuid,
		"b1_fuid": b1_fuid,
		"b2_fuid": b2_fuid,
		"b2_area_layer_ok": not b2_area_layer.is_empty(),
		"b2_layers_count": b_sc.get_floor_layers(b2_fuid).size(),
		"active_before_cross": active_before_cross,
		"cross_tok_member_floor": _member_floor_for(sc_world, cross_tok_id),
		"cross_wall_member_floor": _member_floor_for(sc_world, cross_wall_id),
		"box_host_member_floor": _member_floor_for(sc_world, box_host_id),
		"set_act_res": set_act_res,
		"cat_active_after_scene": cat_active_after_scene,
		"set_act_fl_res": set_act_fl_res,
		"active_scene_after_fl": active_scene_after_fl,
		"move_b2_ok": move_b2_ok,
		"move_b1_last_ok": move_b1_last_ok,
		"scene_of_b2_after": scene_of_b2_after,
		"entry_floors_after_move": b_sc.get_scene_floor_uids(entry_suid),
		"rename_ok": rename_ok,
		"set_def_ok": set_def_ok,
		"set_entry_ok": set_entry_ok,
		"set_view_ok": set_view_ok,
		"view_pos_x": (view_pos as Vector2).x if view_pos is Vector2 else -1.0,
		"view_pos_y": (view_pos as Vector2).y if view_pos is Vector2 else -1.0,
		"valid_cov_ok": valid_cov_ok,
		"bad_cov_res_ok": bad_cov_res_ok,
		"box_pub_type": box_pub_ent.get("entity_type", ""),
		"box_pub_selectable": box_pub_ent.get("selectable_in_select_mode", true),
		"box_pub_size": [(box_pub_ent["entity_size"] as Vector2).x, (box_pub_ent["entity_size"] as Vector2).y],
		"box_pub_scale": [(box_pub_ent["xform"]["scale"] as Vector2).x, (box_pub_ent["xform"]["scale"] as Vector2).y],
		"box_pub_pos": [(box_pub_ent["xform"]["pos"] as Vector2).x, (box_pub_ent["xform"]["pos"] as Vector2).y],
		"box_pub_vis_sprite": box_pub_ent["components"][0]["state"].get("sprite_path", ""),
		"box_pub_perm_all": box_pub_ent["components"][1]["state"].get("all_players_can_operate", false),
		"box_pub_comp": box_pub_ent["components"][2]["state"],
		"box_sel_size": [(box_sel_ent["entity_size"] as Vector2).x, (box_sel_ent["entity_size"] as Vector2).y],
		"box_sel_perm_all": box_sel_ent["components"][1]["state"].get("all_players_can_operate", true),
		"box_sel_owners": Array(box_sel_ent["components"][1]["state"].get("owner_player_ids", PackedStringArray())),
		"box_sel_enter": box_sel_ent["components"][2]["state"].get("enter_policy", ""),
		"box_host_size": [(box_host_ent["entity_size"] as Vector2).x, (box_host_ent["entity_size"] as Vector2).y],
		"box_host_perm_all": box_host_ent["components"][1]["state"].get("all_players_can_operate", true),
		"box_host_owners_cnt": (box_host_ent["components"][1]["state"].get("owner_player_ids", PackedStringArray()) as PackedStringArray).size(),
		"box_host_enter": box_host_ent["components"][2]["state"].get("enter_policy", ""),
		"attach_plain_ok": attach_plain_ok,
		"attached_plain_size": [(attached_plain_ent["entity_size"] as Vector2).x, (attached_plain_ent["entity_size"] as Vector2).y],
		"attached_plain_scale": [(attached_plain_ent["xform"]["scale"] as Vector2).x, (attached_plain_ent["xform"]["scale"] as Vector2).y],
		"attach_unit_on_box_ok": attach_unit_on_box_ok,
		"attach_portal_on_box_ok": attach_portal_on_box_ok,
		"attach_vis_on_box_ok": attach_vis_on_box_ok,
		"attach_light_on_box_ok": attach_light_on_box_ok,
		"attach_box_on_unit_ok": attach_box_on_unit_ok,
		"attach_box_on_map_ok": attach_box_on_map_ok,
		"repo_err": repo_err,
		"roundtrip_diff": roundtrip_diff,
	}

	# -------------------------------------------------------------------------
	# 3. MAX_SCENES = 64 hard limit check
	# -------------------------------------------------------------------------
	var h_cap := _MockHost.new()
	var s_cap = sdk.create_session(h_cap, {})
	var b_cap = sdk.create_world_builder(s_cap, 150.0)
	b_cap.configure_entry_scene("Scene_0", "F0")
	var last_ok_suid := ""
	for idx: int in range(1, 64):
		last_ok_suid = b_cap.add_scene("Scene_%d" % idx, "F_%d" % idx, Color.WHITE, "", false)
	var overflow_suid: String = b_cap.add_scene("Scene_64_Overflow", "F_64", Color.WHITE, "", false)
	var cap_world: Dictionary = b_cap.get_world()
	results["cap64"] = {
		"last_ok": not last_ok_suid.is_empty(),
		"overflow_suid": overflow_suid,
		"scene_count": b_cap.get_scene_uids().size(),
		"floor_count": cap_world["catalog"]["floors"].size(),
		"repo_err": _validate_scene_repository_state(cap_world),
	}

	_write_json(out_path, {"ok": true, "results": results})
	quit(0)
'''


class TestFuSdkV13HeadlessGodot(unittest.TestCase):
    """Real headless Godot integration tests for FuSdk v1.3.0 Scene & Scene Box APIs."""

    run_dir: Path | None = None
    results: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_WORKSPACE_ROOT)
        godot_bin = cfg.godot_bin
        if godot_bin is None or not godot_bin.is_file():
            raise unittest.SkipTest("GODOT_BIN not configured in .env.local; skipping headless Godot tests")

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.run_dir = TEST_TMP_ROOT / f"fu_sdk_v1_3_{uuid.uuid4().hex[:10]}"
        probe_dir = cls.run_dir / "probe_proj"
        probe_dir.mkdir(parents=True, exist_ok=True)
        (probe_dir / "project.godot").write_bytes(
            b'config_version=5\n\n[application]\nconfig/name="fu_sdk_v1_3_test"\n'
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
        if proc.returncode != 0 or log_errors:
            redacted = cfg.redact_path(
                f"rc={proc.returncode} errors={log_errors}\nstdout={proc.stdout[-1200:]}\nstderr={proc.stderr[-1200:]}"
            )
            raise AssertionError(f"Headless Godot v1.3 probe failed:\n{redacted}")

        parsed = json.loads(out_path.read_text(encoding="utf-8"))
        if not parsed.get("ok"):
            raise AssertionError(f"Probe returned failure: {parsed}")
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

    def test_v1_2_backward_compatibility(self) -> None:
        r = self.results["compat"]
        self.assertEqual(r["sdk_version"], "1.3.0")
        self.assertFalse(r["has_before"])
        self.assertFalse(r["has_scene_box"])
        self.assertEqual(r["floors_count"], 2)
        self.assertTrue(r["fl2_ok"])
        self.assertTrue(r["tok_ok"])
        self.assertEqual(r["warn_count"], 0)

    def test_scene_floor_layer_and_cross_floor_override(self) -> None:
        r = self.results["scenes"]
        self.assertEqual(r["warns_after_normal_cfg"], 0)
        self.assertTrue(r["b2_area_layer_ok"])
        self.assertEqual(r["b2_layers_count"], 4)  # map, entity, obstacle + custom area
        self.assertEqual(r["active_before_cross"], r["plaza_fuid"])
        self.assertEqual(r["cross_tok_member_floor"], r["b2_fuid"])
        self.assertEqual(r["cross_wall_member_floor"], r["b2_fuid"])
        self.assertEqual(r["box_host_member_floor"], r["b2_fuid"])
        self.assertTrue(r["set_act_res"])
        self.assertEqual(r["cat_active_after_scene"], r["b1_fuid"])
        self.assertTrue(r["set_act_fl_res"])
        self.assertEqual(r["active_scene_after_fl"], r["entry_suid"])
        self.assertTrue(r["move_b2_ok"])
        self.assertFalse(r["move_b1_last_ok"])
        self.assertEqual(r["scene_of_b2_after"], r["entry_suid"])
        self.assertEqual(r["entry_floors_after_move"], [r["plaza_fuid"], r["watchtower_fuid"], r["b2_fuid"]])
        self.assertTrue(r["rename_ok"])
        self.assertTrue(r["set_def_ok"])
        self.assertTrue(r["set_entry_ok"])
        self.assertTrue(r["set_view_ok"])
        self.assertAlmostEqual(r["view_pos_x"], 128.0, places=3)  # 300 * (64 / 150) = 128
        self.assertAlmostEqual(r["view_pos_y"], 64.0, places=3)   # 150 * (64 / 150) = 64
        self.assertTrue(r["valid_cov_ok"])
        self.assertTrue(r["bad_cov_res_ok"])
        self.assertEqual(r["repo_err"], "")
        self.assertEqual(r["roundtrip_diff"], "")

    def test_scene_box_entities_and_conflict_guards(self) -> None:
        r = self.results["scenes"]
        self.assertEqual(r["box_pub_type"], "object")
        self.assertFalse(r["box_pub_selectable"])
        self.assertEqual(r["box_pub_size"], [96.0, 96.0])
        self.assertEqual(r["box_pub_scale"], [1.0, 1.0])
        self.assertAlmostEqual(r["box_pub_pos"][0], 64.0, places=3)   # 150 * (64/150)
        self.assertAlmostEqual(r["box_pub_pos"][1], 128.0, places=3)  # 300 * (64/150)
        self.assertTrue(r["box_pub_vis_sprite"].endswith(".webp"))
        self.assertTrue(r["box_pub_perm_all"])
        self.assertEqual(r["box_pub_comp"]["enter_policy"], "players_allowed")
        self.assertEqual(r["box_pub_comp"]["preview_policy"], "visited_unlock")
        self.assertFalse(r["box_pub_comp"]["seed_from_visual"])

        # Selected owners: all_players_can_enter=false + owner_player_ids non-empty => enter_policy='players_allowed'
        self.assertEqual(r["box_sel_size"], [72.0, 72.0])  # clamped from 0.5*64=32
        self.assertFalse(r["box_sel_perm_all"])
        self.assertEqual(r["box_sel_owners"], ["player_1", "player_2"])
        self.assertEqual(r["box_sel_enter"], "players_allowed")

        # Host only: all_players_can_enter=false + empty owners => enter_policy='host_only'
        self.assertEqual(r["box_host_size"], [256.0, 256.0])  # clamped from 10*64=640
        self.assertFalse(r["box_host_perm_all"])
        self.assertEqual(r["box_host_owners_cnt"], 0)
        self.assertEqual(r["box_host_enter"], "host_only")

        # Attach & conflict guards
        self.assertTrue(r["attach_plain_ok"])
        self.assertEqual(r["attached_plain_size"], [72.0, 72.0])  # squared from (40,20) clamped to min 72
        self.assertEqual(r["attached_plain_scale"], [1.0, 1.0])
        self.assertFalse(r["attach_unit_on_box_ok"])
        self.assertFalse(r["attach_portal_on_box_ok"])
        self.assertFalse(r["attach_vis_on_box_ok"])
        self.assertFalse(r["attach_light_on_box_ok"])
        self.assertFalse(r["attach_box_on_unit_ok"])
        self.assertFalse(r["attach_box_on_map_ok"])

    def test_max_64_scenes_cap(self) -> None:
        r = self.results["cap64"]
        self.assertTrue(r["last_ok"])
        self.assertEqual(r["overflow_suid"], "")
        self.assertEqual(r["scene_count"], 64)
        self.assertEqual(r["floor_count"], 64)
        self.assertEqual(r["repo_err"], "")


if __name__ == "__main__":
    unittest.main()
