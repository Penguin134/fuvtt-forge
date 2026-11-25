"""Tests for FuSdk M3: 9 Gameplay Optional Plugin SDKs (#19-#27)."""

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

M3_PLUGIN_IDS = (
    "checklist",
    "resource_pool",
    "character_roster",
    "backpack",
    "follow",
    "candidate_initiative",
    "dice",
    "campaign_time",
    "dnd_opportunity",
)

HARDCODED_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[/\\](?:Users|Program Files|Steam|DND|Projects|Work|home)[/\\]|/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/)"
)

FORBIDDEN_DAG_MEMO_SYMBOLS = (
    "_DagMemoEntry",
    "_DagMemoBucket",
    "_DagTravCtx",
)

FORBIDDEN_DUPLICATED_HELPERS = (
    "class _FallbackCloneCtx",
    "class _DndTravCtx",
    "func _parse_int_val(",
    "func _is_valid_uid(",
    "func _is_valid_hex24(",
    "func _is_valid_hex64(",
    "func _has_nul(",
    "func _strip_nul(",
    "func _strip_leading_bom(",
    "func _strip_control_and_edges(",
    "func _has_control_chars(",
    "func _has_control_except_tab(",
    "func _component_id_from_script(",
    "func _is_unit_host(",
    "func _to_bool(",
    "func _coerce_int(",
    "func _coerce_bool(",
    "func _coerce_float(",
    "func _coerce_str(",
    "func _coerce_color_array(",
    "func _clamp_color(",
    "func _is_unit_color(",
    "func _is_hex8_color(",
    "func _safe_clone_fog_overrides(",
)


class TestFuSdkM3PurePython(unittest.TestCase):
    """Pure-Python structural, hygiene, non-duplication, and packager checks for M3."""

    def test_m3_plugin_files_exist_hygiene_and_no_dag_memo_duplication(self) -> None:
        cfg = load_config(_WORKSPACE_ROOT)
        forbidden_locals: list[str] = []
        for candidate in (cfg.fuvtt_install_dir, cfg.fus_repo_dir, cfg.godot_bin):
            if candidate is not None:
                forbidden_locals.append(str(candidate))
                forbidden_locals.append(candidate.as_posix())

        for mod_id in M3_PLUGIN_IDS:
            fpath = SDK_DIR / "plugins" / f"{mod_id}.gd"
            self.assertTrue(fpath.is_file(), f"Missing M3 plugin script: {fpath}")
            raw = fpath.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"{mod_id}.gd must not have UTF-8 BOM")
            self.assertNotIn(b"\r", raw, f"{mod_id}.gd must use LF-only line endings")
            text = raw.decode("utf-8")
            self.assertTrue(
                text.startswith("extends RefCounted\n"),
                f"{mod_id}.gd must start with `extends RefCounted`",
            )
            self.assertNotIn("preload(", text, f"{mod_id}.gd must not call preload()")
            self.assertIsNone(
                re.search(r"(?m)^\s*class_name\b", text),
                f"{mod_id}.gd must not declare class_name",
            )
            self.assertIsNone(
                HARDCODED_PATH_RE.search(text),
                f"{mod_id}.gd appears to contain a hardcoded machine-local path",
            )
            for local_str in forbidden_locals:
                if local_str:
                    self.assertNotIn(local_str, text, f"{mod_id}.gd leaks local environment path")
            self.assertIn(f'const MODULE_ID: String = "{mod_id}"', text)
            self.assertIn("WeakRef", text, f"{mod_id}.gd must use WeakRef for WorldBuilder")
            self.assertIn("func _load_util_script(", text, f"{mod_id}.gd must use _load_util_script")
            for sym in FORBIDDEN_DAG_MEMO_SYMBOLS:
                self.assertNotIn(sym, text, f"{mod_id}.gd must not duplicate {sym}")
            for helper_sig in FORBIDDEN_DUPLICATED_HELPERS:
                self.assertNotIn(helper_sig, text, f"{mod_id}.gd must not re-declare duplicated helper {helper_sig}")

    def test_v1_exposes_all_m3_typed_accessors(self) -> None:
        v1_text = (SDK_DIR / "v1.gd").read_text(encoding="utf-8")
        for mod_id in M3_PLUGIN_IDS:
            self.assertIn(f"func {mod_id}() -> RefCounted:", v1_text)
            self.assertIn(f'return get_plugin_sdk("{mod_id}")', v1_text)

    def test_packager_bundles_all_m3_plugin_scripts(self) -> None:
        case_dir = TEST_TMP_ROOT / f"m3_pack_{uuid.uuid4().hex[:10]}"
        try:
            ws = case_dir / "ws"
            mods_dir = ws / "mods"
            mod_dir = mods_dir / "sample-m3-mod"
            sdk_copy = ws / "shared" / "sdk" / "fu_sdk"
            build_dir = ws / "build"
            shutil.copytree(_WORKSPACE_ROOT / "mods" / "_template", mod_dir)
            shutil.copytree(SDK_DIR, sdk_copy)

            manifest_path = mod_dir / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["id"] = "sample_m3_mod"
            manifest["name"] = "Sample M3 Mod"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            cfg = WorkspaceConfig(
                workspace_root=ws,
                mods_dir=mods_dir,
                sdk_dir=sdk_copy,
                build_dir=build_dir,
                cache_dir=ws / ".cache",
            )
            res = build_mod("sample-m3-mod", config=cfg)
            self.assertTrue(res.zip_path.is_file())
            with zipfile.ZipFile(res.zip_path, "r") as zf:
                names = set(zf.namelist())
            for mod_id in M3_PLUGIN_IDS:
                self.assertIn(f"lib/fu_sdk/plugins/{mod_id}.gd", names)
        finally:
            shutil.rmtree(case_dir, ignore_errors=True)


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


func _find_comp(entity: Dictionary, script_suffix: String) -> Dictionary:
	var comps: Array = entity.get("components", [])
	for raw_c: Variant in comps:
		if raw_c is Dictionary and str((raw_c as Dictionary).get("script", "")).ends_with(script_suffix):
			return raw_c as Dictionary
	return {}


func _run_m3_leak_batch(sdk_scr: Script, iters: int) -> void:
	for _i: int in range(iters):
		var l_sdk = sdk_scr.new()
		var l_host := MockHost.new()
		var l_sess = l_sdk.create_session(l_host, {})
		var l_wb = l_sdk.create_world_builder(l_sess, 150.0)
		l_wb.get_logger().set_emit_to_engine(false)
		var _p1 = l_wb.checklist()
		var _p2 = l_wb.resource_pool()
		var _p3 = l_wb.character_roster()
		var _p4 = l_wb.backpack()
		var _p5 = l_wb.follow()
		var _p6 = l_wb.candidate_initiative()
		var _p7 = l_wb.dice()
		var _p8 = l_wb.campaign_time()
		var _p9 = l_wb.dnd_opportunity()


func _make_valid_card(cid: String, edition: String = "2014") -> Dictionary:
	return {
		"id": cid,
		"edition": edition,
		"owner": "host",
		"access": true,
		"revision": 1,
		"birth": "a".repeat(64),
		"form": {
			"name": "Hero",
			"job": "fighter",
			"race": "丘陵矮人",
			"background": "士兵",
			"source": "manual_total",
			"scores": [16, 10, 16, 10, 12, 8],
			"skills": ["特技", "察觉"],
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
		"notes": {},
	}


func _init() -> void:
	var sdk_scr := load("res://shared/sdk/fu_sdk/v1.gd") as Script
	var sdk = sdk_scr.new()
	var results := {}

	var hex_a := "a".repeat(32)
	var hex_b := "b".repeat(32)
	var hex_c := "c".repeat(32)
	var hex24_a := "d".repeat(24)
	var hex64_a := "e".repeat(64)

	# ------------------------------------------------------------------
	# 1. Discovery, Accessors, Standalone Factory, Playtest-Blocked Status
	# ------------------------------------------------------------------
	var host := MockHost.new()
	var sess = sdk.create_session(host, {})
	var b = sdk.create_world_builder(sess, 150.0)
	b.get_logger().set_emit_to_engine(false)

	var m3_ids: Array[String] = [
		"checklist", "resource_pool", "character_roster", "backpack",
		"follow", "candidate_initiative", "dice", "campaign_time", "dnd_opportunity",
	]
	var accessors := {
		"checklist": b.checklist(),
		"resource_pool": b.resource_pool(),
		"character_roster": b.character_roster(),
		"backpack": b.backpack(),
		"follow": b.follow(),
		"candidate_initiative": b.candidate_initiative(),
		"dice": b.dice(),
		"campaign_time": b.campaign_time(),
		"dnd_opportunity": b.dnd_opportunity(),
	}
	var discovery_ok: bool = true
	for mid: String in m3_ids:
		var p = accessors[mid]
		var st_p = sdk.create_plugin_sdk(mid)
		var bound_p = sdk.create_plugin_sdk(mid, b)
		if p == null or st_p == null or bound_p != p:
			discovery_ok = false
			break
		if str(p.MODULE_ID) != mid or str(st_p.MODULE_ID) != mid:
			discovery_ok = false
			break
		if p.is_enabled():
			discovery_ok = false
			break
		var av: Dictionary = p.get_availability()
		if str(av.get("id", "")) != mid:
			discovery_ok = false
			break
	results["discovery_ok"] = discovery_ok
	results["campaign_time_status"] = str(b.campaign_time().get_availability().get("status", ""))
	results["dnd_opportunity_status"] = str(b.dnd_opportunity().get_availability().get("status", ""))

	# ------------------------------------------------------------------
	# 2. Freed WorldBuilder WeakRef Safety
	# ------------------------------------------------------------------
	var freed_p_list: Array = []
	if true:
		var tmp_host := MockHost.new()
		var tmp_sess = sdk.create_session(tmp_host, {})
		var tmp_wb = sdk.create_world_builder(tmp_sess, 150.0)
		tmp_wb.get_logger().set_emit_to_engine(false)
		for mid: String in m3_ids:
			freed_p_list.append(tmp_wb.get_plugin_sdk(mid))
	var freed_safe: bool = true
	for fp: Variant in freed_p_list:
		var fobj: RefCounted = fp as RefCounted
		if fobj.has_method("get_state") and not (fobj.call("get_state") as Dictionary).is_empty():
			freed_safe = false
		var res_cfg: Variant = null
		if fobj.has_method("set_state"):
			res_cfg = fobj.call("set_state", {})
		elif fobj.has_method("attach_backpack"):
			res_cfg = fobj.call("attach_backpack", "missing", {})
		elif fobj.has_method("attach_follow"):
			res_cfg = fobj.call("attach_follow", "missing", {})
		if not (res_cfg is Dictionary) or bool((res_cfg as Dictionary).get("ok", true)):
			freed_safe = false
	results["freed_wb_safe_ok"] = freed_safe

	# ------------------------------------------------------------------
	# 3. R2 Disabled & Playtest-Blocked Warnings (preserve vs skip)
	# ------------------------------------------------------------------
	var h_r2 := MockHost.new()
	var s_r2 = sdk.create_session(h_r2, {})
	var b_r2 = sdk.create_world_builder(s_r2, 150.0)
	b_r2.get_logger().set_emit_to_engine(false)
	var tok_r2: String = b_r2.add_token("tok_r2", "Guard", Vector2(150, 150), Vector2(64, 64), "")
	var bp_pres: Dictionary = b_r2.backpack().attach_backpack(tok_r2, {"revision": "", "slots": {"0": {"name": "Rope", "note": "", "qty": 1}}})
	var bp_comp_pres: Dictionary = _find_comp(b_r2.get_entity(tok_r2), "comp_backpack.gd")
	var ct_pres: Dictionary = b_r2.campaign_time().configure_campaign_time({"minute": 100, "era": hex_a, "revision": 1, "sources": {}, "effects": {}})
	var dnd_pres: Dictionary = b_r2.dnd_opportunity().configure_dnd_opportunity(b_r2.dnd_opportunity().default_state(2024))
	var warn_pres_count: int = b_r2.get_logger().get_warnings().size()

	b_r2.set_disabled_module_policy("skip")
	var chk_skip: Dictionary = b_r2.checklist().configure_checklist({"schema": 2, "rows": {}})
	var ct_skip: Dictionary = b_r2.campaign_time().configure_campaign_time({"minute": 100, "era": hex_a, "revision": 1, "sources": {}, "effects": {}})
	var dnd_skip: Dictionary = b_r2.dnd_opportunity().configure_dnd_opportunity(b_r2.dnd_opportunity().default_state(2014))
	var follow_skip: Dictionary = b_r2.follow().attach_follow(tok_r2, b_r2.follow().default_state())
	results["r2_preserve_ok"] = (
		bool(bp_pres.get("ok", false))
		and bool(bp_pres.get("parked", false))
		and bool(bp_comp_pres.get("parked", false))
		and not bp_comp_pres.has("manual")
		and bool(ct_pres.get("ok", false))
		and str(ct_pres.get("status", "")) == "playtest_blocked"
		and bool(dnd_pres.get("ok", false))
		and str(dnd_pres.get("status", "")) == "playtest_blocked"
		and b_r2.get_module_state("campaign_time").get("minute", -1) == 100
		and b_r2.get_module_state("dnd_opportunity").get("sheets", {}).get("opportunity_edition", 0) == 2024
		and warn_pres_count >= 3
		and h_r2.warnings.size() >= 3
	)
	results["r2_skip_ok"] = (
		not bool(chk_skip.get("ok", true))
		and bool(chk_skip.get("skipped", false))
		and str(chk_skip.get("reason", "")) == "module_disabled:checklist"
		and b_r2.get_module_state("checklist").is_empty()
		and not bool(ct_skip.get("ok", true))
		and bool(ct_skip.get("skipped", false))
		and not bool(dnd_skip.get("ok", true))
		and bool(dnd_skip.get("skipped", false))
		and not bool(follow_skip.get("ok", true))
		and bool(follow_skip.get("skipped", false))
		and _find_comp(b_r2.get_entity(tok_r2), "comp_follow.gd").is_empty()
	)

	# ------------------------------------------------------------------
	# 4. Enable non-blocked optional modules on main builder b
	# ------------------------------------------------------------------
	b.set_enabled_modules([
		"checklist", "resource_pool", "character_roster", "backpack",
		"follow", "candidate_initiative", "dice", "scene_box",
	])

	var tok_unit: String = b.add_token("hero_u", "Paladin", Vector2(100, 100), Vector2(64, 64), "")
	var tok_target: String = b.add_token("hero_t", "Cleric", Vector2(200, 100), Vector2(64, 64), "")
	var obj_non_unit: String = b.add_object_sprite("crate_nu", "Crate", Vector2(300, 100), Vector2(64, 64), "")
	var map_id: String = b.add_map_tile("map_m3", "MapTile", Vector2.ZERO, Vector2(512, 512), "")
	b.get_entity(map_id)["entity_type"] = "map"
	var sq := [Vector2(-32, -32), Vector2(32, -32), Vector2(32, 32), Vector2(-32, 32)]
	var wall_id: String = b.add_wall("wall_m3", "Wall", Vector2(400, 100), [sq])
	var obs_obj_id: String = b.add_object_sprite("obs_obj", "Pillar", Vector2(500, 100), Vector2(64, 64), "")
	b.obstacle_authoring().attach_obstacle(obs_obj_id, "object")
	b.scene_box().configure_entry_scene("Overworld", "1F")
	var sub_scene: String = b.scene_box().add_scene("Crypt", "B1", Color.WHITE, "", false)
	var box_id: String = b.scene_box().add_scene_box("sb_m3", "DoorBox", Vector2(600, 100), sub_scene)

	# 4A. #19 checklist
	var ck = b.checklist()
	var ck_macro_ok: Dictionary = ck.validate_macro("on entity.motion_committed:\n    if event.cause == \"player_move\":\n        task.complete_once()")
	var ck_macro_bad_ev: Dictionary = ck.validate_macro("on unknown.event:\n    task.complete_once()")
	var ck_macro_bad_no_complete: Dictionary = ck.validate_macro("on camera.navigated:\n    if event.kind == \"pan\":\n        return")
	var ck_row_v1: Dictionary = ck.make_row("Scout", {"audience": "player", "player_id": "p1", "entity_id": hex_b, "more_entity_ids": [hex_c], "source": "on mode.changed:\n    task.complete_once()"})
	var ck_cfg_ok: Dictionary = ck.configure_checklist({"schema": 1, "rows": {hex_a: ck_row_v1}})
	var ck_bad_arch: Dictionary = ck.validate_row(ck.make_row("BadArch", {"archived": true, "done": false}))
	var ck_bad_more: Dictionary = ck.validate_row(ck.make_row("BadMore", {"entity_id": "", "more_entity_ids": [hex_b]}))
	var ck_bad_multiline: Dictionary = ck.validate_row(ck.make_row("Line1\nLine2"))
	results["checklist_ok"] = (
		bool(ck_macro_ok.get("ok", false))
		and not bool(ck_macro_bad_ev.get("ok", true))
		and not bool(ck_macro_bad_no_complete.get("ok", true))
		and bool(ck_cfg_ok.get("ok", false))
		and int(ck.get_state().get("schema", 0)) == 2
		and not bool(ck_bad_arch.get("ok", true))
		and not bool(ck_bad_more.get("ok", true))
		and not bool(ck_bad_multiline.get("ok", true))
	)

	# 4B. #20 resource_pool
	var rp = b.resource_pool()
	var rp_def_res: Dictionary = rp.define_resource("hp", "Hit Points", 100.0, "#CC2222FF", "bar", "public")
	var rp_bad_src: Dictionary = rp.validate_definitions_state({"schema_version": 1, "definitions": {"dnd5e:hp": rp.make_definition("dnd5e:hp", "HP", 50.0)}})
	var rp_bad_stamp: Dictionary = rp.validate_definitions_state({"schema_version": 1, "definitions": {}, "adjustment_stamps": {"resource_pool:hp": hex_a}})
	var rp_att_ok: Dictionary = rp.set_entity_resource(tok_unit, "resource_pool:hp", 42.0, 100.0)
	var rp_att_gt: Dictionary = rp.attach_resource_pool(tok_unit, {"schema_version": 1, "values": {"resource_pool:hp": {"current": 101.0, "maximum": 100.0}}})
	var rp_att_pres: Dictionary = rp.validate_component_state({"schema_version": 1, "values": {}, "presentation": {}})
	var rp_att_box: Dictionary = rp.attach_resource_pool(box_id, rp.default_component_state())
	results["resource_pool_ok"] = (
		bool(rp_def_res.get("ok", false))
		and not bool(rp_bad_src.get("ok", true))
		and not bool(rp_bad_stamp.get("ok", true))
		and bool(rp_att_ok.get("ok", false))
		and not bool(rp_att_gt.get("ok", true))
		and not bool(rp_att_pres.get("ok", true))
		and not bool(rp_att_box.get("ok", true))
	)

	# 4C. #21 character_roster
	var cr = b.character_roster()
	var cr_cfg_ok: Dictionary = cr.set_auto_join(true)
	var cr_att_ok: Dictionary = cr.attach_character_roster_member(tok_unit, {"schema_version": 1, "known_by": {"p1": hex_a}})
	var cr_att_nu: Dictionary = cr.attach_character_roster_member(obj_non_unit, {})
	var cr_att_map: Dictionary = cr.attach_character_roster_member(map_id, {})
	var cr_att_box: Dictionary = cr.attach_character_roster_member(box_id, {})
	var cr_bad_kb: Dictionary = cr.attach_character_roster_member(tok_unit, {"schema_version": 1, "known_by": {"": hex_a}})
	results["character_roster_ok"] = (
		bool(cr_cfg_ok.get("ok", false))
		and bool(cr.get_state().get("auto_join", false))
		and bool(cr_att_ok.get("ok", false))
		and not bool(cr_att_nu.get("ok", true))
		and not bool(cr_att_map.get("ok", true))
		and not bool(cr_att_box.get("ok", true))
		and not bool(cr_bad_kb.get("ok", true))
	)

	# 4D. #22 backpack
	var bp = b.backpack()
	var bp_att_ok: Dictionary = bp.attach_backpack(tok_unit, {"revision": hex_a, "slots": {"0": bp.make_item("Longsword", 1, "+1")}, "receipts": {hex_b: hex64_a}})
	var bp_add_ok: Dictionary = bp.add_item(tok_unit, bp.make_item("Potion", 3, "Heal"), 15)
	var bp_bad_slot00: Dictionary = bp.validate_state({"revision": "", "slots": {"00": bp.make_item("X")}})
	var bp_bad_qty: Dictionary = bp.validate_state({"revision": "", "slots": {"0": bp.make_item("X", 1000)}})
	var bp_att_nu: Dictionary = bp.attach_backpack(obj_non_unit, {})
	var bp_att_map: Dictionary = bp.attach_backpack(map_id, {})
	var bp_att_box: Dictionary = bp.attach_backpack(box_id, {})
	results["backpack_ok"] = (
		bool(bp_att_ok.get("ok", false))
		and bool(bp_add_ok.get("ok", false))
		and (_find_comp(b.get_entity(tok_unit), "comp_backpack.gd")["state"]["slots"] as Dictionary).size() == 2
		and not bool(bp_bad_slot00.get("ok", true))
		and not bool(bp_bad_qty.get("ok", true))
		and not bool(bp_att_nu.get("ok", true))
		and not bool(bp_att_map.get("ok", true))
		and not bool(bp_att_box.get("ok", true))
	)

	# 4E. #23 follow
	var fw = b.follow()
	var fw_att_ok: Dictionary = fw.set_follow_target(tok_unit, tok_target, 24.0, true, "p1")
	var fw_cycle: Dictionary = fw.set_follow_target(tok_target, tok_unit, 16.0, true, "p1")
	var fw_self: Dictionary = fw.set_follow_target(tok_unit, tok_unit, 16.0, true)
	var fw_bad_int: Dictionary = fw.validate_state({"target_id": "", "controller_id": "", "engaged": false, "follow_distance": 16})
	var fw_bad_neg: Dictionary = fw.validate_state({"target_id": "", "controller_id": "", "engaged": false, "follow_distance": -0.1})
	var fw_att_box: Dictionary = fw.attach_follow(box_id, {})
	results["follow_ok"] = (
		bool(fw_att_ok.get("ok", false))
		and not bool(fw_cycle.get("ok", true))
		and str(fw_cycle.get("reason", "")) == "follow_cycle"
		and not bool(fw_self.get("ok", true))
		and not bool(fw_bad_int.get("ok", true))
		and not bool(fw_bad_neg.get("ok", true))
		and not bool(fw_att_box.get("ok", true))
	)

	# 4F. #24 candidate_initiative
	var ci = b.candidate_initiative()
	var warns_before_ci: int = b.get_logger().get_warnings().size()
	var ci_cfg_ok: Dictionary = ci.configure_initiative({
		"schema": 2,
		"world_id": "non_campaign_wid",
		"phase": "active",
		"members": [{"entity_id": tok_unit, "tie_order": 0}],
		"current_id": tok_unit,
		"round": 1,
		"generation": 1,
		"revision": 1,
		"settings": {"descending": true, "starting_round": 1, "show_bar": true},
	})
	var ci_warns_after: int = b.get_logger().get_warnings().size()
	var ci_bad_s2_init: Dictionary = ci.validate_state({
		"schema": 2,
		"world_id": "campaign:" + hex_a,
		"phase": "active",
		"members": [{"entity_id": tok_unit, "initiative": 12, "tie_order": 0}],
		"current_id": tok_unit,
		"round": 1,
	})
	var ci_att_ok: Dictionary = ci.attach_combatant(tok_unit, 18, 3, true, false, true)
	var ci_att_nu: Dictionary = ci.attach_combatant(obj_non_unit, 10)
	var ci_att_map: Dictionary = ci.attach_combatant(map_id, 10)
	var ci_att_wall: Dictionary = ci.attach_combatant(wall_id, 10)
	var ci_att_obs: Dictionary = ci.attach_combatant(obs_obj_id, 10)
	var ci_att_box: Dictionary = ci.attach_combatant(box_id, 10)
	var ci_bad_bounds: Dictionary = ci.validate_component_state({"count": 10000, "modifier": 0})
	results["candidate_initiative_ok"] = (
		bool(ci_cfg_ok.get("ok", false))
		and ci_warns_after > warns_before_ci
		and not bool(ci_bad_s2_init.get("ok", true))
		and bool(ci_att_ok.get("ok", false))
		and not bool(ci_att_nu.get("ok", true))
		and not bool(ci_att_map.get("ok", true))
		and not bool(ci_att_wall.get("ok", true))
		and not bool(ci_att_obs.get("ok", true))
		and not bool(ci_att_box.get("ok", true))
		and not bool(ci_bad_bounds.get("ok", true))
	)

	# 4G. #25 dice
	var dc = b.dice()
	var dc_adv_blocked: Dictionary = dc.validate_expression("adv(1d20)", false)
	var dc_adv_legacy: Dictionary = dc.validate_expression("adv(1d20)", true)
	var dc_burst_ok: Dictionary = dc.validate_expression("burst(2d6+3, 2)", false)
	var dc_11d100_bad: Dictionary = dc.validate_expression("11d100", false)
	var dc_state_ok: Dictionary = dc.default_state("world_m3")
	(dc_state_ok["workspace"]["combos"] as Array).append(dc.make_combo("Fireball", "8d6", "Lv3", hex24_a))
	var dc_cfg_ok: Dictionary = dc.configure_dice(dc_state_ok)
	var dc_bad_pres: Dictionary = dc.validate_workspace({"schema_version": 4, "simple_result": true, "animate": true, "combos": [], "hidden_history_count": 0, "draft": "", "visibility": "public", "theme_id": "royal_ember_resin"}, 0)
	var dc_bad_hid: Dictionary = dc.validate_workspace({"schema_version": 4, "simple_result": false, "animate": true, "combos": [], "hidden_history_count": 1, "draft": "", "visibility": "public", "theme_id": "royal_ember_resin"}, 0)
	results["dice_ok"] = (
		not bool(dc_adv_blocked.get("ok", true))
		and str(dc_adv_blocked.get("reason", "")) == "dice_rule_unavailable"
		and bool(dc_adv_legacy.get("ok", false))
		and bool(dc_burst_ok.get("ok", false))
		and not bool(dc_11d100_bad.get("ok", true))
		and bool(dc_cfg_ok.get("ok", false))
		and not bool(dc_bad_pres.get("ok", true))
		and not bool(dc_bad_hid.get("ok", true))
	)

	# 4H. #26 campaign_time & #27 dnd_opportunity standalone vs bound validation
	var ct = b.campaign_time()
	var st_ct = sdk.create_plugin_sdk("campaign_time")
	var ct_valid_state := {"minute": 100000000, "era": hex_a, "revision": 2, "sources": {hex_b: ct.make_source("dawn", 0)}, "effects": {hex_b: ct.make_effect(1440, "Bless", "active")}}
	var ct_cfg_ok: Dictionary = ct.configure_campaign_time(ct_valid_state)
	var ct_over_min: Dictionary = st_ct.validate_state({"minute": 100000001, "era": hex_a, "revision": 1, "sources": {}, "effects": {}})
	var ct_orphan_eff: Dictionary = st_ct.validate_state({"minute": 10, "era": hex_a, "revision": 1, "sources": {}, "effects": {hex_b: ct.make_effect(20, "X", "active")}})
	results["campaign_time_ok"] = (
		bool(ct_cfg_ok.get("ok", false))
		and not bool(ct_over_min.get("ok", true))
		and not bool(ct_orphan_eff.get("ok", true))
	)

	var dnd = b.dnd_opportunity()
	var st_dnd = sdk.create_plugin_sdk("dnd_opportunity")
	var dnd_valid_2024 := {
		"combined": 2,
		"sheets": {"schema": 1, "opportunity_edition": 2024, "cards": {hex_a: _make_valid_card(hex_a, "2014")}},
		"encounter": {"profiles": {}, "actions": {}, "effects": {}, "turns": {}, "marks": {}, "refills": {}, "combat": ""},
		"health": {"bindings": {}, "events": {}},
	}
	var dnd_cfg_ok: Dictionary = dnd.configure_dnd_opportunity(dnd_valid_2024)
	var dnd_bad_card_ed: Dictionary = st_dnd.validate_state({"combined": 1, "sheets": {"schema": 1, "cards": {hex_a: _make_valid_card(hex_a, "2024")}}, "encounter": {}})
	var dnd_bad_uncomb: Dictionary = st_dnd.validate_state({"schema": 1})
	results["dnd_opportunity_ok"] = (
		bool(dnd_cfg_ok.get("ok", false))
		and not bool(dnd_bad_card_ed.get("ok", true))
		and not bool(dnd_bad_uncomb.get("ok", true))
	)

	# ------------------------------------------------------------------
	# 5. var_to_bytes / bytes_to_var lossless roundtrip
	# ------------------------------------------------------------------
	var built: Dictionary = b.build_result()
	var encoded: PackedByteArray = var_to_bytes(built["world"])
	var decoded: Variant = bytes_to_var(encoded)
	var entries: Dictionary = (decoded as Dictionary).get("modules", {}).get("entries", {}) if decoded is Dictionary else {}
	results["roundtrip_ok"] = (
		bool(built.get("ok", false))
		and encoded.size() > 0
		and decoded is Dictionary
		and entries.has("checklist")
		and entries.has("resource_pool")
		and entries.has("character_roster")
		and entries.has("candidate_initiative")
		and entries.has("dice")
		and entries.has("campaign_time")
		and entries.has("dnd_opportunity")
	)

	# ------------------------------------------------------------------
	# 6. Iteration 2 Remediation Regressions
	# ------------------------------------------------------------------
	var reg := {}
	var obj_nu_park_bp: String = b.add_object_sprite("nu_park_bp", "CrateParkBP", Vector2(700, 100), Vector2(64, 64), "")
	var obj_nu_park_cr: String = b.add_object_sprite("nu_park_cr", "CrateParkCR", Vector2(750, 100), Vector2(64, 64), "")
	var bp_park_nu: Dictionary = bp.attach_backpack(obj_nu_park_bp, {}, true, false)
	var bp_live_nu: Dictionary = bp.attach_backpack(obj_non_unit, {}, false, false)
	var bp_park_box: Dictionary = bp.attach_backpack(box_id, {}, true, false)
	var cr_park_nu: Dictionary = cr.attach_character_roster_member(obj_nu_park_cr, {}, true, false)
	var cr_live_nu: Dictionary = cr.attach_character_roster_member(obj_non_unit, {}, false, false)
	var cr_park_box: Dictionary = cr.attach_character_roster_member(box_id, {}, true, false)
	var st_bp = sdk.create_plugin_sdk("backpack")
	var bp_extra_nan: Dictionary = st_bp.validate_item(st_bp.make_item("Relic", 1, "", {"x": NAN}))
	var bp_extra_inf: Dictionary = st_bp.validate_item(st_bp.make_item("Relic", 1, "", {"x": INF}))
	var bp_extra_obj: Dictionary = st_bp.validate_item(st_bp.make_item("Relic", 1, "", {"x": RefCounted.new()}))
	var bp_extra_cb: Dictionary = st_bp.validate_item(st_bp.make_item("Relic", 1, "", {"x": Callable(b, "build_result")}))
	var bp_add_neg2: Dictionary = bp.add_item(tok_unit, bp.make_item("Coin", 1), -2)
	var bp_add_slot16: Dictionary = bp.add_item(tok_unit, bp.make_item("Coin", 1), 16)
	reg["backpack_and_roster_parked_ok"] = (
		bool(bp_park_nu.get("ok", false))
		and bool(bp_park_nu.get("parked", false))
		and not bool(bp_live_nu.get("ok", true))
		and str(bp_live_nu.get("reason", "")) == "backpack_requires_unit_host"
		and not bool(bp_park_box.get("ok", true))
		and bool(cr_park_nu.get("ok", false))
		and bool(cr_park_nu.get("parked", false))
		and not bool(cr_live_nu.get("ok", true))
		and str(cr_live_nu.get("reason", "")) == "character_roster_member_requires_unit_host"
		and not bool(cr_park_box.get("ok", true))
		and not bool(bp_extra_nan.get("ok", true))
		and not bool(bp_extra_inf.get("ok", true))
		and not bool(bp_extra_obj.get("ok", true))
		and not bool(bp_extra_cb.get("ok", true))
		and not bool(bp_add_neg2.get("ok", true))
		and not bool(bp_add_slot16.get("ok", true))
	)

	var tok_f1: String = b.add_token("f1", "F1", Vector2(800, 100), Vector2(64, 64), "")
	var tok_f2: String = b.add_token("f2", "F2", Vector2(850, 100), Vector2(64, 64), "")
	var tok_f3: String = b.add_token("f3", "F3", Vector2(900, 100), Vector2(64, 64), "")
	var tok_f4: String = b.add_token("f4", "F4", Vector2(950, 100), Vector2(64, 64), "")
	var fw_neg_dist: Dictionary = fw.set_follow_target(tok_f1, tok_f2, -5.0, true)
	var fw_nan_dist: Dictionary = fw.set_follow_target(tok_f1, tok_f2, NAN, true)
	var fw_def_ok: Dictionary = fw.set_follow_target(tok_f1, tok_f2)
	var fw_uneng_1: Dictionary = fw.set_follow_target(tok_f3, tok_f4, 16.0, false)
	var fw_uneng_cyc: Dictionary = fw.set_follow_target(tok_f4, tok_f3, 16.0, false)
	var fw_asym_cyc: Dictionary = fw.set_follow_target(tok_f4, tok_f3, 16.0, true)
	reg["follow_distance_and_cycles_ok"] = (
		not bool(fw_neg_dist.get("ok", true))
		and str(fw_neg_dist.get("reason", "")) == "invalid_follow_distance"
		and not bool(fw_nan_dist.get("ok", true))
		and str(fw_nan_dist.get("reason", "")) == "invalid_follow_distance"
		and bool(fw_def_ok.get("ok", false))
		and is_equal_approx(float((fw_def_ok.get("state", {}) as Dictionary).get("follow_distance", 0.0)), 16.0)
		and bool(fw_uneng_1.get("ok", false))
		and not bool(fw_uneng_cyc.get("ok", true))
		and str(fw_uneng_cyc.get("reason", "")) == "follow_cycle"
		and not bool(fw_asym_cyc.get("ok", true))
		and str(fw_asym_cyc.get("reason", "")) == "follow_cycle"
	)

	var rp_nan_max: Dictionary = rp.set_entity_resource(tok_unit, "resource_pool:mana", 10.0, NAN)
	var rp_neg5_max: Dictionary = rp.set_entity_resource(tok_unit, "resource_pool:mana", 10.0, -5.0)
	var rp_def_max: Dictionary = rp.set_entity_resource(tok_unit, "resource_pool:mana", 10.0)
	reg["resource_pool_strict_max_ok"] = (
		not bool(rp_nan_max.get("ok", true))
		and not bool(rp_neg5_max.get("ok", true))
		and bool(rp_def_max.get("ok", false))
		and is_equal_approx(float(((rp_def_max.get("state", {}) as Dictionary).get("values", {}) as Dictionary).get("resource_pool:mana", {}).get("maximum", 0.0)), 10.0)
	)

	var ck_ret: Dictionary = ck.validate_row(ck.make_row("A", {"source": "return"}))
	var ck_bad: Dictionary = ck.validate_row(ck.make_row("A", {"source": "bad macro"}))
	var ck_mod_t: Dictionary = ck.validate_row(ck.make_row("A", {"source": "mod:test"}))
	var ck_mod_e: Dictionary = ck.validate_row(ck.make_row("A", {"source": "mod:e2e"}))
	reg["checklist_narrow_source_ok"] = (
		not bool(ck_ret.get("ok", true))
		and not bool(ck_bad.get("ok", true))
		and bool(ck_mod_t.get("ok", false))
		and bool(ck_mod_e.get("ok", false))
	)

	var dice_json_str: String = JSON.stringify({
		"schema_version": 5,
		"history": {
			"schema": "fus.candidate.dice.history.v1",
			"world_id": "world_m3",
			"records": [{
				"request_id": "req-1",
				"epoch": 1,
				"world_id": "world_m3",
				"created_at_unix": 1700000000,
				"presentation": "presented",
				"presentation_detail": "",
				"result": {
					"schema": "fus.candidate.dice.result.v1",
					"request_id": "req-1",
					"epoch": 1,
					"origin": "candidate_local",
					"expr": "1d6+2",
					"dice": [{"type": "d6", "value": 4, "subtract": false, "loser": false, "set": 0, "burst": false}],
					"total": 6,
					"modifier": 2,
					"winner_idx": -1,
					"adv_kind": "",
					"set_count": 1,
				},
			}],
		},
		"workspace": {"schema_version": 4, "simple_result": true, "animate": false, "combos": [], "hidden_history_count": 0, "draft": "", "visibility": "public", "theme_id": "royal_ember_resin"},
		"ownership": [{"id": "req-1", "owner": "host", "name": "GM", "request_id": "req-1", "visibility": "public", "label": ""}],
		"archive": {},
	})
	var dice_parsed: Variant = JSON.parse_string(dice_json_str)
	var dice_norm_res: Dictionary = dc.validate_state(dice_parsed)
	var dice_norm_ok: bool = bool(dice_norm_res.get("ok", false))
	if dice_norm_ok:
		var nr: Dictionary = ((dice_norm_res["data"] as Dictionary)["history"] as Dictionary)["records"][0] as Dictionary
		var nres: Dictionary = nr["result"] as Dictionary
		var ndie: Dictionary = (nres["dice"] as Array)[0] as Dictionary
		dice_norm_ok = (
			typeof(nr["epoch"]) == TYPE_INT
			and typeof(nr["created_at_unix"]) == TYPE_INT
			and typeof(nres["epoch"]) == TYPE_INT
			and typeof(nres["total"]) == TYPE_INT
			and typeof(nres["modifier"]) == TYPE_INT
			and typeof(nres["winner_idx"]) == TYPE_INT
			and typeof(nres["set_count"]) == TYPE_INT
			and typeof(ndie["value"]) == TYPE_INT
			and typeof(ndie["set"]) == TYPE_INT
		)
	var dice_bad_total_state: Variant = JSON.parse_string(dice_json_str)
	(dice_bad_total_state["history"]["records"][0]["result"] as Dictionary)["total"] = 9999999
	var dice_bad_die_state: Variant = JSON.parse_string(dice_json_str)
	((dice_bad_die_state["history"]["records"][0]["result"]["dice"] as Array)[0] as Dictionary)["value"] = 999
	var dice_sum_mismatch: Variant = JSON.parse_string(dice_json_str)
	(dice_sum_mismatch["history"]["records"][0]["result"] as Dictionary)["total"] = 5
	reg["dice_history_norm_and_bounds_ok"] = (
		dice_norm_ok
		and not bool(dc.validate_state(dice_bad_total_state).get("ok", true))
		and not bool(dc.validate_state(dice_bad_die_state).get("ok", true))
		and not bool(dc.validate_state(dice_sum_mismatch).get("ok", true))
	)

	var dnd_json_str: String = JSON.stringify({
		"combined": 2,
		"sheets": {
			"schema": 1,
			"cards": {hex_a: _make_valid_card(hex_a, "2014")},
			"rests": {
				hex_b: {
					"card": hex_a, "kind": "short", "phase": "open", "claims": {}, "sources": {},
					"start": 100, "level": 1, "con": 2, "faces": 10, "hp_max": 12,
					"qualified": -1, "finish": -1, "benefit": -1, "duration": 60,
					"era": hex_a, "job": "fighter", "owner": "host", "entity": "", "binding": "",
					"events": [{"op": "short", "minute": 100, "by": "host", "note": ""}],
					"slots": [], "start_hp": 12,
				}
			},
		},
		"encounter": {
			"profiles": {hex_a: {"ac": 15, "bonus": 4, "shield": true}},
			"actions": {
				hex_b: {
					"id": hex_b, "caster": hex_a, "target": hex_c, "kind": "attack",
					"request": "wf-" + hex_b, "stage": "done",
					"original": {"kind": "attack", "total": 19, "face": 15, "base_ac": 15},
					"outcome": {"ok": true}, "ticket": {}, "by": "host", "turn": hex_c + "/1",
					"ac": 15, "bonus": 4,
				}
			},
			"effects": {},
			"turns": {hex_a: 2},
			"marks": {},
			"refills": {},
			"combat": hex_c,
		},
		"health": {
			"bindings": {hex_a: {"hp": "resource_pool:hp", "temp": "resource_pool:temp", "card": hex_a, "generation": hex_b, "die": 10, "modifier": 2}},
			"events": {},
		},
	})
	var dnd_parsed: Variant = JSON.parse_string(dnd_json_str)
	var dnd_norm_res: Dictionary = st_dnd.validate_state(dnd_parsed)
	var dnd_norm_ok: bool = bool(dnd_norm_res.get("ok", false))
	if dnd_norm_ok:
		var dd: Dictionary = dnd_norm_res["data"] as Dictionary
		var denc: Dictionary = dd["encounter"] as Dictionary
		var dprof: Dictionary = (denc["profiles"] as Dictionary)[hex_a] as Dictionary
		var dact: Dictionary = (denc["actions"] as Dictionary)[hex_b] as Dictionary
		var dorig: Dictionary = dact["original"] as Dictionary
		var dhbind: Dictionary = ((dd["health"] as Dictionary)["bindings"] as Dictionary)[hex_a] as Dictionary
		var drest: Dictionary = ((dd["sheets"] as Dictionary)["rests"] as Dictionary)[hex_b] as Dictionary
		dnd_norm_ok = (
			typeof(dprof["ac"]) == TYPE_INT
			and typeof(dprof["bonus"]) == TYPE_INT
			and typeof((denc["turns"] as Dictionary)[hex_a]) == TYPE_INT
			and typeof(dact["ac"]) == TYPE_INT
			and typeof(dact["bonus"]) == TYPE_INT
			and typeof(dorig["total"]) == TYPE_INT
			and typeof(dorig["face"]) == TYPE_INT
			and typeof(dorig["base_ac"]) == TYPE_INT
			and typeof(dhbind["die"]) == TYPE_INT
			and typeof(drest["start"]) == TYPE_INT
			and typeof(drest["start_hp"]) == TYPE_INT
		)
	reg["dnd_encounter_int_norm_ok"] = dnd_norm_ok

	var ci_s2_init_reason: String = str(ci_bad_s2_init.get("reason", ""))
	var ci_nested_leg: Dictionary = ci.validate_state({
		"schema": 2,
		"world_id": "campaign:" + hex_a,
		"phase": "idle",
		"members": [],
		"current_id": "",
		"round": 0,
		"legacy": {
			"schema": 1,
			"world_id": "campaign:" + hex_a,
			"phase": "idle",
			"members": [],
			"current_id": "",
			"round": 0,
			"legacy": {
				"schema": 1,
				"world_id": "campaign:" + hex_a,
				"phase": "idle",
				"members": [],
				"current_id": "",
				"round": 0,
			},
		},
	})
	reg["candidate_initiative_fixes_ok"] = (
		ci_s2_init_reason == "schema2_forbids_member_initiative"
		and not bool(ci_nested_leg.get("ok", true))
		and str(ci_nested_leg.get("reason", "")).contains("nested_legacy_forbidden")
	)
	results["regressions"] = reg

	# ------------------------------------------------------------------
	# 7. RefCounted WeakRef cycle leak check across all 9 M3 accessors
	# ------------------------------------------------------------------
	_run_m3_leak_batch(sdk_scr, 2)
	var obj_base: float = Performance.get_monitor(Performance.OBJECT_COUNT)
	_run_m3_leak_batch(sdk_scr, 20)
	var obj_after_20: float = Performance.get_monitor(Performance.OBJECT_COUNT)
	_run_m3_leak_batch(sdk_scr, 40)
	var obj_after_40: float = Performance.get_monitor(Performance.OBJECT_COUNT)
	results["leak_20_delta"] = obj_after_20 - obj_base
	results["leak_40_delta"] = obj_after_40 - obj_after_20
	results["ref_cycle_leak_zero_ok"] = (
		is_equal_approx(obj_after_20 - obj_base, 0.0)
		and is_equal_approx(obj_after_40 - obj_after_20, 0.0)
	)

	# ------------------------------------------------------------------
	# 8. Tier 5 Adversarial Regressions: BUG-02, BUG-03, BUG-05, BUG-08
	# ------------------------------------------------------------------
	var sdk_t5 = sdk_scr.new()
	var host_t5 := MockHost.new()
	var sess_t5 = sdk_t5.create_session(host_t5, {})
	sess_t5.get_logger().set_emit_to_engine(false)
	var wb_t5 = sdk_t5.create_world_builder(sess_t5, 150.0)
	wb_t5.set_enabled_modules(["candidate_initiative", "checklist", "resource_pool", "backpack", "character_roster", "dnd_opportunity"])
	wb_t5.set_disabled_module_policy("preserve")
	var spr_init: String = wb_t5.add_object_sprite("spr_init", "Prop", Vector2(10, 10), Vector2(64, 64), "")
	var init_live_fail: Dictionary = wb_t5.candidate_initiative().attach_initiative(spr_init, {}, false, false)
	var init_parked_ok: Dictionary = wb_t5.candidate_initiative().attach_initiative(spr_init, {}, true, false)

	var wb_t5_pres = sdk_t5.create_world_builder(sdk_t5.create_session(MockHost.new(), {}), 150.0)
	wb_t5_pres.get_logger().set_emit_to_engine(false)
	wb_t5_pres.set_enabled_modules([])
	wb_t5_pres.set_disabled_module_policy("preserve")
	var spr_init_pres: String = wb_t5_pres.add_object_sprite("spr_init_p", "PropP", Vector2(20, 20), Vector2(64, 64), "")
	var init_pres_auto_park: Dictionary = wb_t5_pres.candidate_initiative().attach_initiative(spr_init_pres, {}, false, false)
	results["tier5_bug02_initiative_parked_ok"] = (
		not bool(init_live_fail.get("ok", true))
		and str(init_live_fail.get("reason", "")) == "initiative_requires_unit_host"
		and bool(init_parked_ok.get("ok", false))
		and bool(init_parked_ok.get("parked", false))
		and bool(init_pres_auto_park.get("ok", false))
		and bool(init_pres_auto_park.get("parked", false))
	)

	var cl_t5 = wb_t5.checklist()
	var cl_event_ok: Dictionary = cl_t5.validate_row(cl_t5.make_row("RuleRow", {"source": "on mode.changed:\n\ttask.complete_once()"}), false)
	var cl_mod_strict_rej: Dictionary = cl_t5.validate_row(cl_t5.make_row("Legacy", {"source": "mod:test"}), false)
	var cl_w_before: int = sess_t5.get_logger().get_warnings(0).size()
	var cl_mod_compat_ok: Dictionary = cl_t5.add_row("", cl_t5.make_row("CompatRow", {"source": "mod:test"}))
	var cl_w_after: int = sess_t5.get_logger().get_warnings(0).size()
	results["tier5_bug03_checklist_rule_source_ok"] = (
		bool(cl_event_ok.get("ok", false))
		and not bool(cl_mod_strict_rej.get("ok", true))
		and str(cl_mod_strict_rej.get("reason", "")).contains("on <事件名>:")
		and bool(cl_mod_compat_ok.get("ok", false))
		and (cl_w_after - cl_w_before) == 1
	)

	var cyc_d := {}
	cyc_d["self"] = cyc_d
	var row_null_ord: Dictionary = cl_t5.make_row("NullOrder", {"order": null})
	var rp_null_curr: Dictionary = wb_t5.resource_pool().make_entity_state({"resource_pool:hp": {"current": null, "maximum": 10.0}})
	var bp_cyc_item: Dictionary = wb_t5.backpack().make_item("CycSword", 1, "", {"extra": cyc_d})
	var cr_cyc_res: Dictionary = wb_t5.character_roster().make_member_state(cyc_d)
	var dnd_cyc_res: Dictionary = wb_t5.dnd_opportunity().validate_state(cyc_d)
	results["tier5_bug05_null_and_cycle_safe_ok"] = (
		row_null_ord is Dictionary and int(row_null_ord.get("order", -1)) == 0
		and rp_null_curr is Dictionary and is_equal_approx(float((((rp_null_curr.get("values", {}) as Dictionary).get("resource_pool:hp", {}) as Dictionary)).get("current", -1.0)), 0.0)
		and bp_cyc_item is Dictionary and str(bp_cyc_item.get("name", "")) == "CycSword"
		and cr_cyc_res is Dictionary
		and dnd_cyc_res is Dictionary
		and not bool(dnd_cyc_res.get("ok", true))
		and str(dnd_cyc_res.get("reason", "")) == "cyclic_dnd_opportunity_state"
	)

	var dice_w_before: int = wb_t5_pres._session.get_logger().get_warnings(0).size()
	var dice_combo_res: Dictionary = wb_t5_pres.dice().add_combo("Slash", "2d6")
	var dice_w_after: int = wb_t5_pres._session.get_logger().get_warnings(0).size()
	results["tier5_bug08_dice_single_warning_ok"] = (
		bool(dice_combo_res.get("ok", false))
		and (dice_w_after - dice_w_before) == 1
	)

	var f := FileAccess.open("res://probe_results.json", FileAccess.WRITE)
	f.store_string(JSON.stringify(results))
	f.close()
	quit(0)
'''


class TestFuSdkM3HeadlessGodot(unittest.TestCase):
    """Real headless Godot verification for all 9 M3 gameplay optional plugins."""

    run_dir: Path | None = None
    results: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_WORKSPACE_ROOT)
        godot_bin = cfg.godot_bin
        if godot_bin is None or not godot_bin.is_file():
            raise unittest.SkipTest("GODOT_BIN not configured in .env.local; skipping headless Godot tests")

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.run_dir = TEST_TMP_ROOT / f"fu_sdk_m3_{uuid.uuid4().hex[:10]}"
        probe_dir = cls.run_dir / "probe_proj"
        probe_dir.mkdir(parents=True, exist_ok=True)
        (probe_dir / "project.godot").write_bytes(
            b'[gd_resource type="ProjectFile" format=3]\n\nconfig_version=5\n\n[application]\nconfig/name="FuSdkM3Probe"\n'
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
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
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
            creationflags=creationflags,
        )
        log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        combined = "\n".join([proc.stdout or "", proc.stderr or "", log_text])
        cls.log_errors = analyze_godot_logs(log_text, proc.stdout or "", proc.stderr or "")
        if proc.returncode != 0:
            raise RuntimeError(f"Godot M3 probe exited {proc.returncode}:\n{combined}")
        if cls.log_errors:
            raise AssertionError(f"Godot M3 probe emitted errors/leaks: {cls.log_errors}\n{combined}")

        res_file = probe_dir / "probe_results.json"
        if not res_file.is_file():
            raise RuntimeError(f"Missing probe_results.json; output:\n{combined}")
        cls.results = json.loads(res_file.read_text(encoding="utf-8"))

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

    def test_discovery_and_playtest_blocked_availability(self) -> None:
        self.assertTrue(self.results["discovery_ok"])
        self.assertEqual(self.results["campaign_time_status"], "playtest_blocked")
        self.assertEqual(self.results["dnd_opportunity_status"], "playtest_blocked")

    def test_freed_world_builder_weakref_safety(self) -> None:
        self.assertTrue(self.results["freed_wb_safe_ok"])

    def test_r2_warnings_preserve_and_skip_policies(self) -> None:
        self.assertTrue(self.results["r2_preserve_ok"])
        self.assertTrue(self.results["r2_skip_ok"])

    def test_checklist_schema_and_macro_dsl(self) -> None:
        self.assertTrue(self.results["checklist_ok"])

    def test_resource_pool_definitions_and_component(self) -> None:
        self.assertTrue(self.results["resource_pool_ok"])

    def test_character_roster_unit_host_and_known_by(self) -> None:
        self.assertTrue(self.results["character_roster_ok"])

    def test_backpack_slots_receipts_and_unit_host(self) -> None:
        self.assertTrue(self.results["backpack_ok"])

    def test_follow_distance_cycle_and_conflicts(self) -> None:
        self.assertTrue(self.results["follow_ok"])

    def test_candidate_initiative_phases_bounds_and_host_exclusions(self) -> None:
        self.assertTrue(self.results["candidate_initiative_ok"])

    def test_dice_expressions_workspace_and_archive(self) -> None:
        self.assertTrue(self.results["dice_ok"])

    def test_campaign_time_bounds_and_orphan_effects(self) -> None:
        self.assertTrue(self.results["campaign_time_ok"])

    def test_dnd_opportunity_editions_envelopes_and_cards(self) -> None:
        self.assertTrue(self.results["dnd_opportunity_ok"])

    def test_world_var_to_bytes_roundtrip(self) -> None:
        self.assertTrue(self.results["roundtrip_ok"])

    def test_ref_cycle_zero_object_leak(self) -> None:
        self.assertEqual(self.results["leak_20_delta"], 0.0)
        self.assertEqual(self.results["leak_40_delta"], 0.0)
        self.assertTrue(self.results["ref_cycle_leak_zero_ok"])

    def test_iteration2_remediation_regressions(self) -> None:
        reg = self.results["regressions"]
        self.assertTrue(reg["backpack_and_roster_parked_ok"])
        self.assertTrue(reg["follow_distance_and_cycles_ok"])
        self.assertTrue(reg["resource_pool_strict_max_ok"])
        self.assertTrue(reg["checklist_narrow_source_ok"])
        self.assertTrue(reg["dice_history_norm_and_bounds_ok"])
        self.assertTrue(reg["dnd_encounter_int_norm_ok"])
        self.assertTrue(reg["candidate_initiative_fixes_ok"])

    def test_tier5_bug02_candidate_initiative_parked_on_non_unit(self) -> None:
        self.assertTrue(self.results["tier5_bug02_initiative_parked_ok"])

    def test_tier5_bug03_checklist_rule_source_compat_and_strict_mode(self) -> None:
        self.assertTrue(self.results["tier5_bug03_checklist_rule_source_ok"])

    def test_tier5_bug05_null_casts_and_cyclic_inputs_no_engine_errors(self) -> None:
        self.assertTrue(self.results["tier5_bug05_null_and_cycle_safe_ok"])

    def test_tier5_bug08_dice_add_combo_single_r2_warning(self) -> None:
        self.assertTrue(self.results["tier5_bug08_dice_single_warning_ok"])


if __name__ == "__main__":
    unittest.main()
