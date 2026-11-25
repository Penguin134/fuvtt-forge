"""Tests for FuSdk M2: 9 Optional/Candidate World Plugin SDKs (#10-#18) & Cross-Track Fixes."""

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

M2_PLUGIN_IDS = (
    "scene_box",
    "portal",
    "grid_alignment",
    "simple_fog",
    "image_flip",
    "drag_movement",
    "drawing",
    "areas",
    "entity_notes",
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


class TestFuSdkM2PurePython(unittest.TestCase):
    """Pure-Python structural, hygiene, non-duplication, and packager checks for M2."""

    def test_m2_plugin_files_exist_hygiene_and_no_dag_memo_duplication(self) -> None:
        cfg = load_config(_WORKSPACE_ROOT)
        forbidden_locals: list[str] = []
        for candidate in (cfg.fuvtt_install_dir, cfg.fus_repo_dir, cfg.godot_bin):
            if candidate is not None:
                forbidden_locals.append(str(candidate))
                forbidden_locals.append(candidate.as_posix())

        for mod_id in M2_PLUGIN_IDS:
            fpath = SDK_DIR / "plugins" / f"{mod_id}.gd"
            self.assertTrue(fpath.is_file(), f"Missing M2 plugin script: {fpath}")
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

    def test_packager_bundles_all_m2_plugin_scripts(self) -> None:
        case_dir = TEST_TMP_ROOT / f"m2_pack_{uuid.uuid4().hex[:10]}"
        try:
            ws = case_dir / "ws"
            mods_dir = ws / "mods"
            mod_dir = mods_dir / "sample-m2-mod"
            sdk_copy = ws / "shared" / "sdk" / "fu_sdk"
            build_dir = ws / "build"
            shutil.copytree(_WORKSPACE_ROOT / "mods" / "_template", mod_dir)
            shutil.copytree(SDK_DIR, sdk_copy)

            manifest_path = mod_dir / "plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["id"] = "sample_m2_mod"
            manifest["name"] = "Sample M2 Mod"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

            cfg = WorkspaceConfig(
                workspace_root=ws,
                mods_dir=mods_dir,
                sdk_dir=sdk_copy,
                build_dir=build_dir,
                cache_dir=ws / ".cache",
            )
            res = build_mod("sample-m2-mod", config=cfg)
            self.assertTrue(res.zip_path.is_file())
            with zipfile.ZipFile(res.zip_path, "r") as zf:
                names = set(zf.namelist())
            for mod_id in M2_PLUGIN_IDS:
                self.assertIn(f"lib/fu_sdk/plugins/{mod_id}.gd", names)
        finally:
            shutil.rmtree(case_dir, ignore_errors=True)


PROBE_GD = r'''extends SceneTree

class MockHost extends RefCounted:
	var reports: Array[String] = []
	var warnings: Array[String] = []
	var preview_started: bool = false
	var preview_ended: bool = false
	var previewed: Array = []

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

	func begin_preview(_items: int, _bounds: Rect2) -> void:
		preview_started = true

	func end_preview() -> void:
		preview_ended = true

	func preview_entity(entity: Dictionary, kind: String) -> void:
		previewed.append({"id": str(entity.get("id", "")), "kind": kind})


func _find_comp(entity: Dictionary, script_suffix: String) -> Dictionary:
	var comps: Array = entity.get("components", [])
	for raw_c: Variant in comps:
		if raw_c is Dictionary and str((raw_c as Dictionary).get("script", "")).ends_with(script_suffix):
			return raw_c as Dictionary
	return {}


func _run_m2_leak_batch(sdk_scr: Script, iters: int) -> void:
	for _i: int in range(iters):
		var l_sdk = sdk_scr.new()
		var l_host := MockHost.new()
		var l_sess = l_sdk.create_session(l_host, {})
		var l_wb = l_sdk.create_world_builder(l_sess, 150.0)
		l_wb.get_logger().set_emit_to_engine(false)
		var _p1 = l_wb.scene_box()
		var _p2 = l_wb.portal()
		var _p3 = l_wb.grid_alignment()
		var _p4 = l_wb.simple_fog()
		var _p5 = l_wb.image_flip()
		var _p6 = l_wb.drag_movement()
		var _p7 = l_wb.drawing()
		var _p8 = l_wb.areas()
		var _p9 = l_wb.entity_notes()


func _init() -> void:
	var sdk_scr := load("res://shared/sdk/fu_sdk/v1.gd") as Script
	var sdk = sdk_scr.new()
	var results := {}

	# ------------------------------------------------------------------
	# 1. Discovery, Accessors, Standalone Factory
	# ------------------------------------------------------------------
	var host := MockHost.new()
	var sess = sdk.create_session(host, {})
	var b = sdk.create_world_builder(sess, 150.0)
	b.get_logger().set_emit_to_engine(false)

	var m2_ids: Array[String] = [
		"scene_box", "portal", "grid_alignment", "simple_fog",
		"image_flip", "drag_movement", "drawing", "areas", "entity_notes",
	]
	var accessors := {
		"scene_box": b.scene_box(),
		"portal": b.portal(),
		"grid_alignment": b.grid_alignment(),
		"simple_fog": b.simple_fog(),
		"image_flip": b.image_flip(),
		"drag_movement": b.drag_movement(),
		"drawing": b.drawing(),
		"areas": b.areas(),
		"entity_notes": b.entity_notes(),
	}
	var discovery_ok: bool = true
	for mid: String in m2_ids:
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
	results["entity_notes_status"] = str(b.entity_notes().get_availability().get("status", ""))

	# ------------------------------------------------------------------
	# 2. R2 Disabled Warnings: preserve vs skip + portal missing areas + scene_box auto-park
	# ------------------------------------------------------------------
	var h_r2 := MockHost.new()
	var s_r2 = sdk.create_session(h_r2, {})
	var b_r2 = sdk.create_world_builder(s_r2, 150.0)
	b_r2.get_logger().set_emit_to_engine(false)

	var tok_r2: String = b_r2.add_token("tok_r2", "Guard", Vector2(150, 150), Vector2(100, 100), "")
	# Disabled under preserve: emits warning & auto-parks component
	var flip_pres: Dictionary = b_r2.image_flip().set_flip(tok_r2, true, false)
	var flip_comp_pres: Dictionary = _find_comp(b_r2.get_entity(tok_r2), "comp_image_flip.gd")
	var sb_dis_entry: String = b_r2.scene_box().configure_entry_scene("DisabledMain", "1F")
	var sb_dis_box_id: String = b_r2.scene_box().add_scene_box("sb_dis", "DisabledBox", Vector2(300, 300), sb_dis_entry)
	var sb_dis_comp: Dictionary = _find_comp(b_r2.get_entity(sb_dis_box_id), "comp_scene_box.gd")
	var sb_dis_manual_bad: bool = b_r2.scene_box().attach_scene_box(tok_r2, sb_dis_entry, "", "visited_unlock", true, [], false, true)
	var warn_count_pres: int = b_r2.get_logger().get_warnings().size()
	var host_warn_pres: int = h_r2.warnings.size()

	# Disabled under skip: emits warning & skips write
	b_r2.set_disabled_module_policy("skip")
	var grid_skip: Dictionary = b_r2.grid_alignment().configure_grid(64.0, true, Vector2.ZERO, Color.WHITE, 2.0, 0.5)
	var has_grid_after_skip: bool = not b_r2.get_module_state("grid_alignment").is_empty()
	var speed_skip: Dictionary = b_r2.drag_movement().set_entity_speed(tok_r2, 96.0)
	var speed_comp_after_skip: Dictionary = _find_comp(b_r2.get_entity(tok_r2), "comp_drag_speed.gd")
	var sb_skip_id: String = b_r2.scene_box().add_scene_box("sb_skip", "SkippedBox", Vector2(400, 400), sb_dis_entry)

	# Portal enabled without areas -> missing_requires warning
	b_r2.set_disabled_module_policy("preserve")
	b_r2.set_enabled_modules(["portal"])
	var tok_p1: String = b_r2.add_token("tok_p1", "Gate1", Vector2(200, 200), Vector2(64, 64), "")
	var warns_before_portal: int = b_r2.get_logger().get_warnings().size()
	var portal_no_areas: Dictionary = b_r2.portal().attach_portal(tok_p1, "door_alpha")
	var has_areas_req_warn: bool = false
	for w_entry: Variant in b_r2.get_logger().get_warnings():
		if w_entry is Dictionary and str((w_entry as Dictionary).get("message", "")).contains("areas"):
			has_areas_req_warn = true
	results["r2_preserve_ok"] = (
		bool(flip_pres.get("ok", false))
		and bool(flip_pres.get("parked", false))
		and not bool(flip_pres.get("manual", true))
		and bool(flip_comp_pres.get("parked", false))
		and not flip_comp_pres.has("manual")
		and not sb_dis_entry.is_empty()
		and not sb_dis_box_id.is_empty()
		and bool(sb_dis_comp.get("parked", false))
		and not sb_dis_comp.has("manual")
		and not sb_dis_manual_bad
		and warn_count_pres >= 3
		and host_warn_pres >= 3
	)
	results["r2_skip_ok"] = (
		not bool(grid_skip.get("ok", true))
		and bool(grid_skip.get("skipped", false))
		and str(grid_skip.get("reason", "")) == "module_disabled:grid_alignment"
		and not has_grid_after_skip
		and not bool(speed_skip.get("ok", true))
		and bool(speed_skip.get("skipped", false))
		and speed_comp_after_skip.is_empty()
		and sb_skip_id.is_empty()
	)
	results["portal_missing_areas_warn_ok"] = (
		bool(portal_no_areas.get("ok", false))
		and not bool(portal_no_areas.get("parked", true))
		and b_r2.get_logger().get_warnings().size() > warns_before_portal
		and has_areas_req_warn
	)

	# ------------------------------------------------------------------
	# 3. Enable all 9 optional modules on main builder b
	# ------------------------------------------------------------------
	b.set_enabled_modules([
		"scene_box", "portal", "grid_alignment", "simple_fog",
		"image_flip", "drag_movement", "drawing", "areas",
	])

	# 3A. Cross-track fix: comp_unit rejects entity_type == "map"
	var map_id: String = b.add_map_tile("map_01", "DungeonMap", Vector2.ZERO, Vector2(1500, 1500), "")
	b.get_entity(map_id)["entity_type"] = "map"
	var unit_on_map_wb: bool = b.attach_unit_marker(map_id)
	var unit_on_map_em: Dictionary = b.edit_mode().attach_unit_marker(map_id)
	var unit_on_map_adp: Dictionary = b.get_adapter().append_entity_component(b.get_entity(map_id), b.get_adapter().COMP_UNIT_SCRIPT, {"schema_version": 1}, false)
	results["comp_unit_map_rejected"] = (
		not unit_on_map_wb
		and not bool(unit_on_map_em.get("ok", true))
		and str(unit_on_map_em.get("reason", "")) == "unit_disallowed_on_map"
		and not bool(unit_on_map_adp.get("ok", true))
		and str(unit_on_map_adp.get("reason", "")) == "unit_disallowed_on_map"
	)

	# 3B. grid_alignment cross-track fix ([0.5, 4.0] line_width, [-1e6, 1e6] offset)
	var ga = b.grid_alignment()
	var ga_adp_low: Dictionary = b.get_adapter().make_grid_alignment_state(64.0, true, Vector2(-2000000.0, 2000000.0), Color(0.2, 0.3, 0.4, 0.8), 0.1, 0.5)
	var ga_adp_high: Dictionary = b.get_adapter().make_grid_alignment_state(64.0, true, Vector2.ZERO, Color.WHITE, 32.0, 0.5)
	var ga_cfg_res: Dictionary = ga.configure_grid(128.0, true, Vector2(12.0, -24.0), Color(0.1, 0.2, 0.3, 0.9), 0.2, 0.4)
	var ga_patch_bad_lw: Dictionary = ga.patch_config({"line_width": 4.01})
	var ga_patch_bad_key: Dictionary = ga.patch_config({"schema": "other"})
	var ga_patch_ok: Dictionary = ga.patch_config({"line_width": 3.5, "snap_strength": 0.75})
	var ga_val_empty_false: Dictionary = ga.validate_config({}, false)
	var ga_val_empty_true: Dictionary = ga.validate_config({}, true)
	var ga_val_low: Dictionary = ga.validate_config(ga.make_config(64.0, true, Vector2.ZERO, Color.WHITE, 1.0, 0.1), false)
	var ga_bad_lw_low: Dictionary = ga.default_config()
	ga_bad_lw_low["line_width"] = 0.49
	var ga_val_bad_lw_low: Dictionary = ga.validate_config(ga_bad_lw_low, false)
	results["grid_alignment_ok"] = (
		is_equal_approx(float(ga_adp_low["line_width"]), 0.5)
		and is_equal_approx(float(ga_adp_high["line_width"]), 4.0)
		and is_equal_approx(float(ga_adp_low["offset"][0]), -1000000.0)
		and is_equal_approx(float(ga_adp_low["offset"][1]), 1000000.0)
		and bool(ga_cfg_res.get("ok", false))
		and is_equal_approx(float(ga_cfg_res["config"]["line_width"]), 0.5)
		and not bool(ga_patch_bad_lw.get("ok", true))
		and str(ga_patch_bad_lw.get("reason", "")) == "grid_line_width_invalid"
		and not bool(ga_patch_bad_key.get("ok", true))
		and str(ga_patch_bad_key.get("reason", "")) == "grid_config_field_not_editable"
		and bool(ga_patch_ok.get("ok", false))
		and is_equal_approx(float(ga.get_config().get("line_width", 0.0)), 3.5)
		and not bool(ga_val_empty_false.get("ok", true))
		and bool(ga_val_empty_true.get("ok", false))
		and bool(ga_val_low.get("ok", false))
		and not bool(ga_val_bad_lw_low.get("ok", true))
	)

	# 3C. simple_fog cross-track fix (4-float RGBA coercion, strict floats, SFH2, vision/light)
	var sf = b.simple_fog()
	var valid_sfh2 := PackedByteArray([0x53, 0x46, 0x48, 0x32, 0x10, 0x00, 0x00, 0x00, 0x00, 0x01])
	var bad_sfh2_magic := PackedByteArray([0x53, 0x46, 0x48, 0x31, 0x10, 0x00, 0x00, 0x00])
	var bad_sfh2_rawlen := PackedByteArray([0x53, 0x46, 0x48, 0x32, 0x00, 0x00, 0x00, 0x00])
	var sf_cfg_res: Dictionary = sf.configure_fog({
		"version": 1,
		"unseen_color": [0.05, 0.05, 0.1, 1.0],
		"visible_tint": [0.2, 0.4, 0.6, 0.25],
		"history_color": "#8c000000",
		"unseen_effect": 2,
		"visible_effect": 4,
		"history_effect": 6,
		"history_enabled": true,
		"dm_opacity": 1,
		"vision_threshold": 0,
		"vision_feather": 0.12,
		"shadow_filter": 2,
		"shadow_smooth": 4,
		"hide_unseen_entities": false,
	}, valid_sfh2)
	var sf_stored: Dictionary = sf.get_fog_config()
	var sf_bad_alpha: Dictionary = sf.validate_fog_config({"unseen_color": [0.0, 0.0, 0.0, 0.99]})
	var sf_bad_eff: Dictionary = sf.validate_fog_config({"unseen_effect": 3})
	var sf_bad_filter: Dictionary = sf.validate_fog_config({"shadow_filter": 3})
	var sf_bad_op: Dictionary = sf.validate_fog_config({"dm_opacity": 0.005})
	var sf_bad_fea: Dictionary = sf.validate_fog_config({"vision_feather": 0.6})
	var sf_bad_smo: Dictionary = sf.validate_fog_config({"shadow_smooth": 16.5})
	var sf_bad_exp: Dictionary = sf.validate_fog_config({"exploration": bad_sfh2_magic})
	var sf_empty_exp: Dictionary = sf.validate_fog_config({"exploration": PackedByteArray()})
	var light_id: String = sf.add_point_light("torch_1", Vector2(300, 300), 480.0, 180.0, "Torch")
	var light_ent: Dictionary = b.get_entity(light_id)
	var tok_vis: String = b.add_token("hero_vis", "Hero", Vector2(450, 450), Vector2(100, 100), "")
	var vis_res: Dictionary = sf.attach_vision(tok_vis, 640.0, 120.0, true, true)
	results["simple_fog_ok"] = (
		bool(sf_cfg_res.get("ok", false))
		and int(sf_stored.get("version", 0)) == 2
		and sf_stored.get("unseen_color", null) is Color
		and sf_stored.get("visible_tint", null) is Color
		and sf_stored.get("history_color", null) is Color
		and typeof(sf_stored.get("dm_opacity", null)) == TYPE_FLOAT
		and typeof(sf_stored.get("vision_threshold", null)) == TYPE_FLOAT
		and typeof(sf_stored.get("shadow_smooth", null)) == TYPE_FLOAT
		and sf_stored.has("exploration")
		and not bool(sf_bad_alpha.get("ok", true))
		and not bool(sf_bad_eff.get("ok", true))
		and not bool(sf_bad_filter.get("ok", true))
		and not bool(sf_bad_op.get("ok", true))
		and not bool(sf_bad_fea.get("ok", true))
		and not bool(sf_bad_smo.get("ok", true))
		and not bool(sf_bad_exp.get("ok", true))
		and not sf.is_valid_exploration_bytes(bad_sfh2_rawlen)
		and bool(sf_empty_exp.get("ok", false))
		and not (sf_empty_exp["data"] as Dictionary).has("exploration")
		and not light_id.is_empty()
		and is_equal_approx((light_ent.get("fallback_color", Color.WHITE) as Color).a, 0.0)
		and not _find_comp(light_ent, "comp_simple_light.gd").is_empty()
		and bool(vis_res.get("ok", false))
		and not _find_comp(b.get_entity(tok_vis), "comp_simple_vision.gd").is_empty()
	)

	# 3D. scene_box (SceneRepository v2, comp_scene_box, square [72,256], 14 conflicts, no map)
	var sb = b.scene_box()
	var entry_suid: String = sb.configure_entry_scene("Overworld", "Ground")
	var sub_suid: String = sb.add_scene("Crypt", "B1", Color(0.2, 0.2, 0.3), "", false)
	var cover_ok: String = "asset://%s.png" % ("c".repeat(64))
	var box_id: String = sb.add_scene_box("box_crypt", "To Crypt", Vector2(600, 600), sub_suid, 0.5, cover_ok, "always_public", false, ["p1"])
	var box_ent: Dictionary = b.get_entity(box_id)
	var box_sz: Vector2 = box_ent.get("entity_size", Vector2.ZERO)
	var sb_repo_val: Dictionary = sb.validate_scene_repository()
	var sb_attach_map: bool = sb.attach_scene_box(map_id, sub_suid)
	var sb_conflict_unit: bool = sb.attach_scene_box(tok_vis, sub_suid)  # has simple_vision
	var sb_comp_bad_uid: Dictionary = sb.validate_comp_scene_box_state({"schema_version": 1, "target_scene_uid": "A".repeat(32)})
	results["scene_box_ok"] = (
		not entry_suid.is_empty()
		and not sub_suid.is_empty()
		and sb.get_scene_uids().size() == 2
		and not box_id.is_empty()
		and is_equal_approx(box_sz.x, 72.0)
		and is_equal_approx(box_sz.y, 72.0)
		and bool(sb_repo_val.get("ok", false))
		and not sb_attach_map
		and not sb_conflict_unit
		and not bool(sb_comp_bad_uid.get("ok", true))
		and sb.SCENE_BOX_CONFLICTS.size() == 14
	)

	# 3E. areas + portal + image_flip conflicts
	var ar = b.areas()
	var pt = b.portal()
	var fl = b.image_flip()
	var area_layer_uid: String = ar.add_area_layer("Portals", b.get_active_floor_uid(), "host")
	var def_layer_for_floor: String = ""
	for raw_fl_row: Variant in b.get_world()["catalog"]["layers"]["floors"]:
		if raw_fl_row is Dictionary and str((raw_fl_row as Dictionary).get("floor_uid", "")) == b.get_active_floor_uid():
			def_layer_for_floor = str((raw_fl_row as Dictionary).get("default_layer_uid", ""))
	var area_set_def_blocked: bool = b.layer_stack().set_default_layer(b.get_active_floor_uid(), area_layer_uid)

	var poly_rect: Array = [PackedVector2Array([Vector2(-32, -32), Vector2(32, -32), Vector2(32, 32), Vector2(-32, 32)])]
	var a1_res: Dictionary = ar.add_area_entity("area_a", "PortalA", Vector2(100, 100), Vector2(64, 64), poly_rect, 2.5, false, "", area_layer_uid)
	var a2_res: Dictionary = ar.add_area_entity("area_b", "PortalB", Vector2(500, 500), Vector2(64, 64), poly_rect, 256.0, false, "", area_layer_uid)
	var a_bad_zero: Dictionary = ar.attach_area(tok_vis, 0.0)
	var a_bad_high: Dictionary = ar.attach_area(tok_vis, 256.1)
	var a_bad_int_val: Dictionary = ar.validate_area_state({"removed": false, "radius_in_cells": 1})
	var a1_id: String = str(a1_res.get("entity_id", ""))
	var a2_id: String = str(a2_res.get("entity_id", ""))
	var a1_ent: Dictionary = b.get_entity(a1_id)
	var a1_vd: Dictionary = a1_ent["components"][0]["state"]["vector_drawing"]

	var pair_res: Dictionary = pt.link_pair(a1_id, a2_id)
	var pt_bad_upper: Dictionary = pt.validate_portal_state({"pair_key": "A".repeat(32)})
	var pt_on_box: Dictionary = pt.attach_portal(box_id, "x")

	var flip_on_area: Dictionary = fl.set_flip(a1_id, true, false)
	var flip_on_box: Dictionary = fl.set_flip(box_id, true, false)
	var obs_tok_id: String = b.add_token("obs_flip", "ObstacleProp", Vector2(50, 50), Vector2(64, 64), "")
	var obs_att_res: Dictionary = b.obstacle_authoring().attach_obstacle(obs_tok_id, "object", "manual", 64.0)
	var flip_on_wall: Dictionary = fl.set_flip(obs_tok_id, true, false)
	var tok_flip: String = b.add_token("tok_flip", "Crate", Vector2(250, 250), Vector2(64, 64), "")
	var flip_ok_res: Dictionary = fl.set_flip(tok_flip, true, true)
	var area_on_flipped: Dictionary = ar.attach_area(tok_flip, 1.5)
	var obs_on_flipped: Dictionary = b.obstacle_authoring().attach_obstacle(tok_flip, "object", "manual", 64.0)
	results["areas_portal_flip_ok"] = (
		not area_layer_uid.is_empty()
		and def_layer_for_floor != area_layer_uid
		and not area_set_def_blocked
		and bool(a1_res.get("ok", false))
		and bool(a2_res.get("ok", false))
		and not bool(a_bad_zero.get("ok", true))
		and not bool(a_bad_high.get("ok", true))
		and not bool(a_bad_int_val.get("ok", true))
		and str(a1_vd.get("source", {}).get("kind", "")) == "area"
		and str(a1_vd.get("source", {}).get("schema", "")) == "fus.area.v1"
		and bool(pair_res.get("ok", false))
		and str(_find_comp(b.get_entity(a1_id), "comp_portal.gd")["state"]["pair_key"]) == str(_find_comp(b.get_entity(a2_id), "comp_portal.gd")["state"]["pair_key"])
		and not bool(pt_bad_upper.get("ok", true))
		and not bool(pt_on_box.get("ok", true))
		and not bool(flip_on_area.get("ok", true))
		and not bool(flip_on_box.get("ok", true))
		and bool(obs_att_res.get("ok", false))
		and not bool(flip_on_wall.get("ok", true))
		and bool(flip_ok_res.get("ok", false))
		and not bool(area_on_flipped.get("ok", true))
		and not bool(obs_on_flipped.get("ok", true))
	)

	# 3F. drag_movement (v1 256 -> 64 migration, v2 256 kept, comp_drag_speed)
	var dm = b.drag_movement()
	var dm_v1_mig: Dictionary = dm.validate_world_config({"version": 1, "speed": 256.0})
	var dm_v2_keep: Dictionary = dm.validate_world_config({"version": 2, "speed": 256.0})
	var dm_neg: Dictionary = dm.validate_world_config({"version": 2, "speed": -1.0})
	var dm_cfg_res: Dictionary = dm.configure_default_speed(256.0, 1)
	var dm_spd_int_val: Dictionary = dm.validate_speed_state({"speed": 64})
	var dm_spd_ok: Dictionary = dm.set_entity_speed(tok_vis, 96.0)
	var dm_spd_box: Dictionary = dm.set_entity_speed(box_id, 96.0)
	results["drag_movement_ok"] = (
		bool(dm_v1_mig.get("ok", false))
		and int(dm_v1_mig["data"]["version"]) == 2
		and is_equal_approx(float(dm_v1_mig["data"]["speed"]), 64.0)
		and bool(dm_v2_keep.get("ok", false))
		and is_equal_approx(float(dm_v2_keep["data"]["speed"]), 256.0)
		and not bool(dm_neg.get("ok", true))
		and bool(dm_cfg_res.get("ok", false))
		and is_equal_approx(float(dm.get_world_config().get("speed", 0.0)), 64.0)
		and not bool(dm_spd_int_val.get("ok", true))
		and bool(dm_spd_ok.get("ok", false))
		and not bool(dm_spd_box.get("ok", true))
	)

	# 3G. drawing (world strokes + text_ink affine + visible + comp_entity_ink)
	var dr = b.drawing()
	var active_fl: String = b.get_active_floor_uid()
	var stroke1: Dictionary = dr.make_stroke_item(active_fl, [Vector2(0, 0), Vector2(64, 64)], Color.RED, 8.0, "round", "world", 1)
	var xf_txt: Transform2D = dr.make_text_transform(Vector2(10, 20), 0.25, Vector2(1.2, 1.2))
	var txt1: Dictionary = dr.make_text_item(active_fl, Vector2(100, 100), "Danger!", Color.YELLOW, "zhuokai", 42, xf_txt, "world", 2)
	var dr_cfg_ok: Dictionary = dr.configure_world_drawing([stroke1, txt1], true)
	var dr_state_vis: Dictionary = dr.get_world_drawing_state()
	var dr_cfg_hidden: Dictionary = dr.configure_world_drawing([stroke1], false)
	var dr_state_hid: Dictionary = dr.get_world_drawing_state()
	var dr_add_txt: Dictionary = dr.add_world_text(txt1)

	var bad_txt_rot: Dictionary = txt1.duplicate(true)
	bad_txt_rot["rotation"] = 0.5
	var bad_txt_fs_float: Dictionary = txt1.duplicate(true)
	bad_txt_fs_float["font_size"] = 42.0
	var bad_txt_blank: Dictionary = dr.make_text_item(active_fl, Vector2(0, 0), "   ")
	var bad_stroke_life: Dictionary = stroke1.duplicate(true)
	bad_stroke_life["life"] = 5

	var e_stroke: Dictionary = dr.make_entity_stroke([Vector2(0.1, 0.1), Vector2(0.8, 0.8)], Color.CYAN, 0.02, 0.9)
	var e_ink_ok: Dictionary = dr.attach_entity_ink(tok_vis, [e_stroke], "a".repeat(32))
	var e_ink_box: Dictionary = dr.attach_entity_ink(box_id, [e_stroke], "")
	var e_ink_bad_w: Dictionary = dr.validate_entity_ink_state({"strokes": [{"id": "a".repeat(32), "erase": false, "color": Color.BLACK, "width": 0.2, "opacity": 1.0, "points": PackedVector2Array([Vector2(0.5, 0.5)])}], "revision": ""})
	results["drawing_ok"] = (
		bool(dr_cfg_ok.get("ok", false))
		and not dr_state_vis.has("visible")
		and bool(dr_cfg_hidden.get("ok", false))
		and dr_state_hid.get("visible", null) == false
		and bool(dr_add_txt.get("ok", false))
		and (dr.get_world_drawing_state()["strokes"] as Array).size() == 2
		and not txt1.has("rotation")
		and not txt1.has("scale")
		and txt1.get("affine", null) is Transform2D
		and not bool(dr.validate_ink_row(bad_txt_rot, true).get("ok", true))
		and not bool(dr.validate_ink_row(bad_txt_fs_float, true).get("ok", true))
		and not bool(dr.validate_ink_row(bad_txt_blank, true).get("ok", true))
		and not bool(dr.validate_ink_row(bad_stroke_life, true).get("ok", true))
		and bool(e_ink_ok.get("ok", false))
		and not bool(e_ink_box.get("ok", true))
		and not bool(e_ink_bad_w.get("ok", true))
	)

	# 3H. entity_notes (candidate warning + auto-park + 32768 limit + skip)
	var en = b.entity_notes()
	var warns_before_en: int = b.get_logger().get_warnings().size()
	var en_pin_res: Dictionary = en.add_text_pin("pin_1", "Secret Trap", Vector2(200, 200))
	var en_pin_ent: Dictionary = b.get_entity(str(en_pin_res.get("entity_id", "")))
	var en_comp: Dictionary = _find_comp(en_pin_ent, "comp_entity_note.gd")
	var en_over_len: Dictionary = en.validate_note_state({"schema_version": 1, "text": "x".repeat(32769)})
	var en_trunc_state: Dictionary = en.make_note_state("y".repeat(32800))
	b.set_disabled_module_policy("skip")
	var en_skip_res: Dictionary = en.attach_note(tok_vis, "Skipped")
	b.set_disabled_module_policy("preserve")
	results["entity_notes_ok"] = (
		not en.is_enabled()
		and b.get_logger().get_warnings().size() > warns_before_en
		and bool(en_pin_res.get("ok", false))
		and bool(en_pin_res.get("parked", false))
		and not bool(en_pin_res.get("manual", true))
		and bool(en_comp.get("parked", false))
		and not en_comp.has("manual")
		and str(en_comp["state"]["text"]) == "Secret Trap"
		and not bool(en_over_len.get("ok", true))
		and str(en_trunc_state["text"]).length() == 32768
		and not bool(en_skip_res.get("ok", true))
		and bool(en_skip_res.get("skipped", false))
	)

	# ------------------------------------------------------------------
	# 4. var_to_bytes / bytes_to_var lossless roundtrip
	# ------------------------------------------------------------------
	var built_world: Dictionary = b.build_result()
	var world_bytes: PackedByteArray = var_to_bytes(built_world["world"])
	var decoded_world: Variant = bytes_to_var(world_bytes)
	var rt_ok: bool = (
		bool(built_world.get("ok", false))
		and world_bytes.size() > 0
		and decoded_world is Dictionary
		and (decoded_world as Dictionary).get("modules", {}).get("entries", {}).has("scene_box")
		and (decoded_world as Dictionary).get("modules", {}).get("entries", {}).has("grid_alignment")
		and (decoded_world as Dictionary).get("modules", {}).get("entries", {}).has("simple_fog")
		and (decoded_world as Dictionary).get("modules", {}).get("entries", {}).has("drag_movement")
		and (decoded_world as Dictionary).get("modules", {}).get("entries", {}).has("drawing")
	)
	results["roundtrip_ok"] = rt_ok

	# ------------------------------------------------------------------
	# 5. Iteration 2 Challenger Regression Assertions (7 findings)
	# ------------------------------------------------------------------
	# 5.1 RefCounted WeakRef cycle leak check across all 9 M2 accessors (20 & 40 iterations)
	_run_m2_leak_batch(sdk_scr, 2)
	var obj_base: float = Performance.get_monitor(Performance.OBJECT_COUNT)
	_run_m2_leak_batch(sdk_scr, 20)
	var obj_after_20: float = Performance.get_monitor(Performance.OBJECT_COUNT)
	_run_m2_leak_batch(sdk_scr, 40)
	var obj_after_40: float = Performance.get_monitor(Performance.OBJECT_COUNT)
	results["leak_20_delta"] = obj_after_20 - obj_base
	results["leak_40_delta"] = obj_after_40 - obj_after_20
	results["ref_cycle_leak_zero_ok"] = (
		is_equal_approx(obj_after_20 - obj_base, 0.0)
		and is_equal_approx(obj_after_40 - obj_after_20, 0.0)
	)

	# 5.2 simple_fog unseen_color.a == 1.0 exact check (reject 0.999995) & 8-byte SFH2 rejection
	var sf_999995_coerced: Dictionary = sf.validate_fog_config({"unseen_color": [0.1, 0.2, 0.3, 0.999995]}, true)
	var sf_999995_strict: Dictionary = sf.validate_fog_config({"unseen_color": Color(0.1, 0.2, 0.3, 0.999995)}, false)
	var sf_999995_adp: Dictionary = b.get_adapter().make_simple_fog_world_state({"unseen_color": [0.1, 0.2, 0.3, 0.999995]})
	var sfh2_hdr_only := PackedByteArray([0x53, 0x46, 0x48, 0x32, 0x10, 0x00, 0x00, 0x00])
	var sf_hdr_only_val: Dictionary = sf.validate_fog_config({"exploration": sfh2_hdr_only})
	results["simple_fog_strict_alpha_and_sfh2_ok"] = (
		not bool(sf_999995_coerced.get("ok", true))
		and not bool(sf_999995_strict.get("ok", true))
		and (sf_999995_adp["unseen_color"] as Color) == Color.BLACK
		and not sf.is_valid_exploration_bytes(sfh2_hdr_only)
		and not b.get_adapter().is_valid_simple_fog_exploration(sfh2_hdr_only)
		and not bool(sf_hdr_only_val.get("ok", true))
	)

	# 5.3 simple_fog standalone vs bound make_fog_config parity + add_point_light manual warn
	var st_sf = sdk.create_plugin_sdk("simple_fog")
	var partial_override := {"unseen_color": [0.1, 0.2, 0.3, 0.5], "dm_opacity": 0.8}
	var st_fog_cfg: Dictionary = st_sf.make_fog_config(partial_override)
	var bd_fog_cfg: Dictionary = sf.make_fog_config(partial_override)
	var warns_before_light_manual: int = b.get_logger().get_warnings().size()
	var bad_light_manual: String = sf.add_point_light("bad_light", Vector2(10, 10), 200.0, 360.0, "BadLight", false, true, Vector2(32, 32), "", false, true)
	results["simple_fog_standalone_parity_and_warn_ok"] = (
		is_equal_approx(float(st_fog_cfg.get("dm_opacity", 0.0)), 0.8)
		and is_equal_approx(float(bd_fog_cfg.get("dm_opacity", 0.0)), 0.8)
		and (st_fog_cfg.get("unseen_color", null) as Color) == Color.BLACK
		and (bd_fog_cfg.get("unseen_color", null) as Color) == Color.BLACK
		and bad_light_manual.is_empty()
		and b.get_logger().get_warnings().size() > warns_before_light_manual
	)

	# 5.4 drawing sequential add_world_stroke / add_world_text default order & id + strict validation
	var h_dr := MockHost.new()
	var s_dr = sdk.create_session(h_dr, {})
	var b_dr = sdk.create_world_builder(s_dr, 150.0)
	b_dr.get_logger().set_emit_to_engine(false)
	b_dr.set_enabled_modules(["drawing"])
	var dr2 = b_dr.drawing()
	var fl_dr: String = b_dr.get_active_floor_uid()
	var s_def_1: Dictionary = dr2.make_stroke_item(fl_dr, [Vector2(0, 0), Vector2(32, 32)])
	var s_def_2: Dictionary = dr2.make_stroke_item(fl_dr, [Vector2(64, 64), Vector2(96, 96)])
	var t_def_1: Dictionary = dr2.make_text_item(fl_dr, Vector2(10, 10), "NoteA")
	var t_def_2: Dictionary = dr2.make_text_item(fl_dr, Vector2(10, 10), "NoteA")
	var r_s1: Dictionary = dr2.add_world_stroke(s_def_1)
	var r_s2: Dictionary = dr2.add_world_stroke(s_def_2)
	var r_t1: Dictionary = dr2.add_world_text(t_def_1)
	var r_t2: Dictionary = dr2.add_world_text(t_def_2)
	var dr2_rows: Array = dr2.get_world_drawing_state().get("strokes", [])
	var dup_order_val: Dictionary = dr2.validate_world_drawing_state({"version": 1, "strokes": [s_def_1, s_def_2]})
	var dup_id_s := s_def_2.duplicate(true)
	dup_id_s["order"] = 2
	dup_id_s["id"] = s_def_1["id"]
	var dup_id_val: Dictionary = dr2.validate_world_drawing_state({"version": 1, "strokes": [s_def_1, dup_id_s]})
	results["drawing_sequential_default_order_ok"] = (
		bool(r_s1.get("ok", false)) and int(r_s1.get("order", 0)) == 1
		and bool(r_s2.get("ok", false)) and int(r_s2.get("order", 0)) == 2
		and bool(r_t1.get("ok", false)) and int(r_t1.get("order", 0)) == 3
		and bool(r_t2.get("ok", false)) and int(r_t2.get("order", 0)) == 4
		and dr2_rows.size() == 4
		and str(r_s1.get("id", "")) != str(r_s2.get("id", ""))
		and str(r_t1.get("id", "")) != str(r_t2.get("id", ""))
		and str(s_def_1["id"]) != str(s_def_2["id"])
		and not bool(dup_order_val.get("ok", true))
		and not bool(dup_id_val.get("ok", true))
	)

	# 5.5 drawing standalone make_world_drawing_state at full 5120-item host capacity (4096 strokes + 1024 text)
	var st_dr = sdk.create_plugin_sdk("drawing")
	var items_5120: Array = []
	var base_pts := PackedVector2Array([Vector2(0, 0), Vector2(16, 16)])
	var base_prs := PackedFloat32Array([1.0, 1.0])
	var t_pts := PackedVector2Array([Vector2(20, 20)])
	var t_prs := PackedFloat32Array([1.0])
	for idx_s: int in range(4096):
		var ord_s: int = idx_s + 1
		items_5120.append({
			"id": ("%032x" % ord_s),
			"floor": fl_dr,
			"coords": "world",
			"tool": "round",
			"points": base_pts,
			"pressure": base_prs,
			"color": Color.BLACK,
			"width": 6.0,
			"opacity": 1.0,
			"hardness": 1.0,
			"filled": false,
			"life": 0,
			"owner": "host",
			"order": ord_s,
		})
	for idx_t: int in range(1024):
		var ord_t: int = 4097 + idx_t
		items_5120.append({
			"id": ("%032x" % ord_t),
			"floor": fl_dr,
			"coords": "world",
			"tool": "text",
			"points": t_pts,
			"pressure": t_prs,
			"color": Color.BLACK,
			"width": 42.0,
			"opacity": 1.0,
			"hardness": 1.0,
			"filled": false,
			"life": 0,
			"owner": "host",
			"order": ord_t,
			"text": "T",
			"font": "zhuokai",
			"font_size": 42,
		})
	var state_5120: Dictionary = st_dr.make_world_drawing_state(items_5120, true)
	var val_5120: Dictionary = st_dr.validate_world_drawing_state(state_5120)
	results["drawing_standalone_5120_ok"] = (
		(state_5120.get("strokes", []) as Array).size() == 5120
		and bool(val_5120.get("ok", false))
	)

	# 5.6 areas add_area_entity rejects empty/degenerate paths_local with zero orphan entities
	var ent_count_before_area_err: int = (b.get_world()["entity_state"]["entities"] as Array).size()
	var ar_empty_res: Dictionary = ar.add_area_entity("bad_area_empty", "EmptyArea", Vector2(100, 100), Vector2(64, 64), [], 1.0, false, "", area_layer_uid)
	var ar_collinear_res: Dictionary = ar.add_area_entity(
		"bad_area_collinear",
		"CollinearArea",
		Vector2(100, 100),
		Vector2(64, 64),
		[PackedVector2Array([Vector2(0, 0), Vector2(10, 0), Vector2(20, 0)])],
		1.0,
		false,
		"",
		area_layer_uid
	)
	var ent_count_after_area_err: int = (b.get_world()["entity_state"]["entities"] as Array).size()
	results["areas_empty_paths_rejected_no_orphan_ok"] = (
		not bool(ar_empty_res.get("ok", true))
		and str(ar_empty_res.get("reason", "")) == "area_geometry_invalid"
		and not bool(ar_collinear_res.get("ok", true))
		and str(ar_collinear_res.get("reason", "")) == "area_geometry_invalid"
		and ent_count_after_area_err == ent_count_before_area_err
	)

	# 5.7 M6 API-ergonomics aliases & JSON integral-float coercion regression checks
	var ga_dict_ok: Dictionary = ga.configure_grid_alignment({
		"version": 1.0,
		"cell_size": 96.0,
		"offset": Vector2(10.0, -20.0),
		"color": "#ff804080",
		"line_width": 2.0,
		"snap_enabled": false,
		"snap_strength": 0.6,
	})
	var ga_set_cfg_ok: Dictionary = ga.set_config({"cell_size": 128.0})
	var ga_bad_cell: Dictionary = ga.configure_grid_alignment({"cell_size": 4.0})
	var ga_bad_lw_hi: Dictionary = ga.configure_grid_alignment({"line_width": 0.25})
	var ga_bad_off: Dictionary = ga.configure_grid_alignment({"offset": [2000000.0, 0.0]})
	var ga_bad_ver_flt: Dictionary = ga.configure_grid_alignment({"version": 1.5})
	var ga_pos_ok: Dictionary = ga.configure_grid_alignment(64.0, true, Vector2.ZERO, Color.WHITE, 1.5, 0.2)

	var sf_json_ok: Dictionary = sf.validate_fog_config({
		"version": 2.0,
		"unseen_effect": 2.0,
		"visible_effect": 0.0,
		"history_effect": 6.0,
		"shadow_filter": 1.0,
	}, true)
	var sf_strict_ver: Dictionary = sf.validate_fog_config({"version": 2.0}, false)
	var sf_strict_eff: Dictionary = sf.validate_fog_config({"unseen_effect": 2.0}, false)
	var sf_strict_flt: Dictionary = sf.validate_fog_config({"shadow_filter": 1.0}, false)
	var sf_nonint_ver: Dictionary = sf.validate_fog_config({"version": 2.5}, true)
	var sf_nonint_eff: Dictionary = sf.validate_fog_config({"unseen_effect": 2.5}, true)
	var sf_nonint_flt: Dictionary = sf.validate_fog_config({"shadow_filter": 1.5}, true)
	var sf_make_flt: Dictionary = sf.make_fog_config({"history_effect": 4.0, "shadow_filter": 2.0})

	var tok_fl2: String = b.add_token("tok_fl2", "Flipper", Vector2(280, 280), Vector2(64, 64), "")
	var tok_fl3: String = b.add_token("tok_fl3", "FlipperPos", Vector2(290, 290), Vector2(64, 64), "")
	var fl_dict_ok: Dictionary = fl.attach_image_flip(tok_fl2, {"horizontal": true, "vertical": false})
	var fl_pos_ok: Dictionary = fl.set_image_flip(tok_fl3, false, true)
	var fl_bad_key: Dictionary = fl.attach_image_flip(tok_fl2, {"unknown_k": true})

	var dm_dict_ok: Dictionary = dm.configure_drag_movement({"version": 2.0, "speed": 144.0})
	var dm_dict_v1_ok: Dictionary = dm.configure_drag_movement({"version": 1.0, "speed": 256.0})
	var dm_pos_ok: Dictionary = dm.configure_drag_movement(112.0, 2)
	var dm_bad_ver: Dictionary = dm.configure_drag_movement({"version": 2.5, "speed": 64.0})

	var s1_json: Dictionary = stroke1.duplicate(true)
	s1_json["order"] = 1.0
	s1_json["life"] = 0.0
	var t1_json: Dictionary = txt1.duplicate(true)
	t1_json["order"] = 2.0
	t1_json["life"] = 0.0
	t1_json["font_size"] = 24.0
	var t1_bad_fs: Dictionary = txt1.duplicate(true)
	t1_bad_fs["font_size"] = 42.5
	var dr_dict_ok: Dictionary = dr.configure_drawing({"version": 1.0, "visible": true, "strokes": [s1_json, t1_json]})
	var dr_bad_ver: Dictionary = dr.configure_drawing({"version": 1.5, "strokes": []})
	var dr_bad_fs: Dictionary = dr.configure_drawing({"version": 1.0, "strokes": [t1_bad_fs]})
	var e_stroke_flt: Dictionary = e_stroke.duplicate(true)
	e_stroke_flt["margin"] = 8.0
	var tok_ink2: String = b.add_token("tok_ink2", "Painter", Vector2(310, 310), Vector2(64, 64), "")
	var e_ink_dict_ok: Dictionary = dr.attach_entity_ink(tok_ink2, {"revision": "b".repeat(32), "strokes": [e_stroke_flt]})
	var e_ink_comp_stored: Dictionary = _find_comp(b.get_entity(tok_ink2), "comp_entity_ink.gd")

	var tok_note2: String = b.add_token("tok_note2", "Noted", Vector2(340, 340), Vector2(64, 64), "")
	var tok_note3: String = b.add_token("tok_note3", "NotedStr", Vector2(350, 350), Vector2(64, 64), "")
	var en_dict_ok: Dictionary = en.attach_entity_note(tok_note2, {"schema_version": 1.0, "text": "JSON Note", "is_pin": true, "keep_screen_size": false})
	var en_str_ok: Dictionary = en.attach_entity_note(tok_note3, "String Note", false, true)
	var en_bad_ver: Dictionary = en.attach_entity_note(tok_note2, {"schema_version": 1.5, "text": "Bad"})
	var en_comp_stored: Dictionary = _find_comp(b.get_entity(tok_note2), "comp_entity_note.gd")

	results["m6_ergonomics_and_coercion_ok"] = (
		bool(ga_dict_ok.get("ok", false))
		and typeof(ga_dict_ok["config"]["version"]) == TYPE_INT
		and int(ga_dict_ok["config"]["version"]) == 1
		and is_equal_approx(float(ga_dict_ok["config"]["cell_size"]), 96.0)
		and bool(ga_set_cfg_ok.get("ok", false))
		and is_equal_approx(float(ga_set_cfg_ok["config"]["cell_size"]), 128.0)
		and not bool(ga_bad_cell.get("ok", true))
		and not bool(ga_bad_lw_hi.get("ok", true))
		and not bool(ga_bad_off.get("ok", true))
		and not bool(ga_bad_ver_flt.get("ok", true))
		and bool(ga_pos_ok.get("ok", false))
		and bool(sf_json_ok.get("ok", false))
		and typeof(sf_json_ok["data"]["version"]) == TYPE_INT
		and typeof(sf_json_ok["data"]["unseen_effect"]) == TYPE_INT
		and typeof(sf_json_ok["data"]["history_effect"]) == TYPE_INT
		and typeof(sf_json_ok["data"]["shadow_filter"]) == TYPE_INT
		and not bool(sf_strict_ver.get("ok", true))
		and not bool(sf_strict_eff.get("ok", true))
		and not bool(sf_strict_flt.get("ok", true))
		and not bool(sf_nonint_ver.get("ok", true))
		and not bool(sf_nonint_eff.get("ok", true))
		and not bool(sf_nonint_flt.get("ok", true))
		and typeof(sf_make_flt.get("history_effect", null)) == TYPE_INT
		and int(sf_make_flt.get("history_effect", 0)) == 4
		and typeof(sf_make_flt.get("shadow_filter", null)) == TYPE_INT
		and int(sf_make_flt.get("shadow_filter", 0)) == 2
		and bool(fl_dict_ok.get("ok", false))
		and bool(fl_dict_ok.get("horizontal", false))
		and not bool(fl_dict_ok.get("vertical", true))
		and bool(fl_pos_ok.get("ok", false))
		and not bool(fl_pos_ok.get("horizontal", true))
		and bool(fl_pos_ok.get("vertical", false))
		and not bool(fl_bad_key.get("ok", true))
		and bool(dm_dict_ok.get("ok", false))
		and typeof(dm_dict_ok["config"]["version"]) == TYPE_INT
		and int(dm_dict_ok["config"]["version"]) == 2
		and is_equal_approx(float(dm_dict_ok["config"]["speed"]), 144.0)
		and bool(dm_dict_v1_ok.get("ok", false))
		and is_equal_approx(float(dm_dict_v1_ok["config"]["speed"]), 64.0)
		and bool(dm_pos_ok.get("ok", false))
		and is_equal_approx(float(dm_pos_ok["config"]["speed"]), 112.0)
		and not bool(dm_bad_ver.get("ok", true))
		and bool(dr_dict_ok.get("ok", false))
		and typeof(dr_dict_ok["state"]["version"]) == TYPE_INT
		and typeof((dr_dict_ok["state"]["strokes"] as Array)[0]["order"]) == TYPE_INT
		and typeof((dr_dict_ok["state"]["strokes"] as Array)[1]["font_size"]) == TYPE_INT
		and not bool(dr_bad_ver.get("ok", true))
		and not bool(dr_bad_fs.get("ok", true))
		and not bool(dr.validate_ink_row(bad_txt_fs_float, true).get("ok", true))
		and bool(e_ink_dict_ok.get("ok", false))
		and typeof((e_ink_comp_stored["state"]["strokes"] as Array)[0]["margin"]) == TYPE_INT
		and bool(en_dict_ok.get("ok", false))
		and bool(en_dict_ok.get("parked", false))
		and typeof(en_comp_stored["state"]["schema_version"]) == TYPE_INT
		and str(en_comp_stored["state"]["text"]) == "JSON Note"
		and bool(en_str_ok.get("ok", false))
		and not bool(en_bad_ver.get("ok", true))
	)

	# 5.8 M6 Tier 2 regression checks: scene_box.get_scene_floor_uids, image_flip drawing/gate, grid_alignment.patch_config color
	var sb_floors_alias: Array[String] = sb.get_scene_floors(entry_suid)
	var sb_floor_uids: Array[String] = sb.get_scene_floor_uids(entry_suid)
	var wb_floor_uids: Array[String] = b.get_scene_floor_uids(entry_suid)

	var wall_poly := [PackedVector2Array([Vector2(-40, -40), Vector2(40, -40), Vector2(40, 40), Vector2(-40, 40)])]
	var wall_eid: String = b.add_wall("wall_flip_reg", "WallFlip", Vector2(700, 100), wall_poly)
	var flip_on_add_wall: Dictionary = fl.attach_image_flip(wall_eid, {"horizontal": true, "vertical": false})
	var flip_val_wall: Dictionary = fl.validate_flip_state({"horizontal": true, "vertical": false}, b.get_entity(wall_eid))
	var flip_adp_wall: Dictionary = b.get_adapter().append_entity_component(b.get_entity(wall_eid), fl.COMP_IMAGE_FLIP_SCRIPT, {"horizontal": true, "vertical": false}, false)
	var area_visual_only := {
		"id": "area_vis_only",
		"components": [{
			"script": b.get_adapter().COMP_VISUAL_SCRIPT,
			"state": {"vector_drawing": {"source": {"kind": "area"}}},
		}],
	}
	var flip_val_area_vis: Dictionary = fl.validate_flip_state({"horizontal": true, "vertical": false}, area_visual_only)
	var flip_adp_area_vis: Dictionary = b.get_adapter().append_entity_component(area_visual_only, fl.COMP_IMAGE_FLIP_SCRIPT, {"horizontal": true, "vertical": false}, false)
	var spriteless_tok_id: String = b.add_token("tok_flip_spriteless", "Spriteless", Vector2(750, 100), Vector2(64, 64), "")
	var flip_spriteless_ok: Dictionary = fl.attach_image_flip(spriteless_tok_id, {"horizontal": true, "vertical": false})

	var h_fl_gate := MockHost.new()
	var s_fl_gate = sdk.create_session(h_fl_gate, {})
	var b_fl_gate = sdk.create_world_builder(s_fl_gate, 150.0)
	b_fl_gate.get_logger().set_emit_to_engine(false)
	var tok_fl_gate: String = b_fl_gate.add_token("tok_fg", "GateTok", Vector2(100, 100), Vector2(64, 64), "")
	b_fl_gate.set_disabled_module_policy("skip")
	var w_before_skip: int = b_fl_gate.get_logger().get_warnings().size()
	var fl_gate_skip_bad_dict: Dictionary = b_fl_gate.image_flip().attach_image_flip(tok_fl_gate, {"bad_key": 1})
	var fl_gate_skip_manual: Dictionary = b_fl_gate.image_flip().set_flip(tok_fl_gate, true, false, false, true)
	var w_after_skip: int = b_fl_gate.get_logger().get_warnings().size()
	b_fl_gate.set_disabled_module_policy("preserve")
	var w_before_pres: int = b_fl_gate.get_logger().get_warnings().size()
	var fl_gate_pres_bad_dict: Dictionary = b_fl_gate.image_flip().attach_image_flip(tok_fl_gate, {"bad_key": 1})
	var fl_gate_pres_valid_dict: Dictionary = b_fl_gate.image_flip().attach_image_flip(tok_fl_gate, {"horizontal": true, "vertical": false})
	var w_after_pres: int = b_fl_gate.get_logger().get_warnings().size()

	var ga_patch_html: Dictionary = ga.patch_config({"color": "#ff0000"})
	var ga_patch_arr3: Dictionary = ga.patch_config({"color": [0.25, 0.5, 0.75]})
	var ga_patch_dict: Dictionary = ga.patch_config({"color": {"r": 0.1, "g": 0.2, "b": 0.3, "a": 0.4}})
	var ga_patch_col: Dictionary = ga.patch_config({"color": Color(0.2, 0.4, 0.6, 0.8)})
	var ga_patch_bad_col: Dictionary = ga.patch_config({"color": "not_a_color"})

	results["m6_tier2_fixes_ok"] = (
		not sb_floor_uids.is_empty()
		and sb_floor_uids == sb_floors_alias
		and sb_floor_uids == wb_floor_uids
		and not wall_eid.is_empty()
		and not bool(flip_on_add_wall.get("ok", true))
		and str(flip_on_add_wall.get("reason", "")) == "component_conflict_with_image_flip:obstacle"
		and not bool(flip_val_wall.get("ok", true))
		and not bool(flip_adp_wall.get("ok", true))
		and str(flip_adp_wall.get("reason", "")) == "component_conflict_with_image_flip"
		and not bool(flip_val_area_vis.get("ok", true))
		and "component_conflict_with_image_flip:area" in (flip_val_area_vis.get("errors", []) as Array)
		and not bool(flip_adp_area_vis.get("ok", true))
		and bool(flip_spriteless_ok.get("ok", false))
		and not bool(fl_gate_skip_bad_dict.get("ok", true))
		and bool(fl_gate_skip_bad_dict.get("skipped", false))
		and str(fl_gate_skip_bad_dict.get("reason", "")) == "module_disabled:image_flip"
		and not bool(fl_gate_skip_manual.get("ok", true))
		and bool(fl_gate_skip_manual.get("skipped", false))
		and str(fl_gate_skip_manual.get("reason", "")) == "module_disabled:image_flip"
		and (w_after_skip - w_before_skip) == 2
		and not bool(fl_gate_pres_bad_dict.get("ok", true))
		and str(fl_gate_pres_bad_dict.get("reason", "")) == "unknown_image_flip_key:bad_key"
		and bool(fl_gate_pres_valid_dict.get("ok", false))
		and bool(fl_gate_pres_valid_dict.get("parked", false))
		and (w_after_pres - w_before_pres) == 2
		and bool(ga_patch_html.get("ok", false))
		and is_equal_approx(float(ga_patch_html["config"]["color"][0]), 1.0)
		and bool(ga_patch_arr3.get("ok", false))
		and is_equal_approx(float(ga_patch_arr3["config"]["color"][3]), 1.0)
		and bool(ga_patch_dict.get("ok", false))
		and is_equal_approx(float(ga_patch_dict["config"]["color"][3]), 0.4)
		and bool(ga_patch_col.get("ok", false))
		and is_equal_approx(float(ga_patch_col["config"]["color"][1]), 0.4)
		and not bool(ga_patch_bad_col.get("ok", true))
	)

	# 5.9 Regression: scene_box entity rejects simple_fog.attach_vision and simple_fog.attach_light
	var sf_on_box_vision: Dictionary = sf.attach_vision(box_id, 300.0, 360.0)
	var sf_on_box_light: Dictionary = sf.attach_light(box_id, 300.0, 360.0)
	var box_after_sf: Dictionary = b.get_entity(box_id)
	results["scene_box_simple_fog_conflicts_ok"] = (
		not bool(sf_on_box_vision.get("ok", true))
		and str(sf_on_box_vision.get("reason", "")) == "component_conflict_with_scene_box:simple_vision"
		and not bool(sf_on_box_light.get("ok", true))
		and str(sf_on_box_light.get("reason", "")) == "component_conflict_with_scene_box:simple_light"
		and _find_comp(box_after_sf, "comp_simple_vision.gd").is_empty()
		and _find_comp(box_after_sf, "comp_simple_light.gd").is_empty()
	)

	# 5.10 Tier 5 Adversarial Regressions: BUG-01, BUG-07, drawing.set_entity_ink
	var sdk_t5 = sdk_scr.new()
	var host_t5 := MockHost.new()
	var sess_t5 = sdk_t5.create_session(host_t5, {})
	sess_t5.get_logger().set_emit_to_engine(false)
	var wb_t5 = sdk_t5.create_world_builder(sess_t5, 150.0)
	wb_t5.set_enabled_modules(["scene_box", "drawing", "areas", "feature_edit_mode"])
	wb_t5.set_disabled_module_policy("preserve")
	var sc_t5: String = str(wb_t5.scene_box().add_scene("Crypt", "B1", Color.DARK_SLATE_BLUE, "", false))
	var hero_t5: String = wb_t5.add_token("hero_t5", "Hero", Vector2(100, 100), Vector2(64, 64), "")
	wb_t5.attach_unit_marker(hero_t5)
	var sb_on_unit_parked: bool = wb_t5.scene_box().attach_scene_box(hero_t5, sc_t5, "", "visited_unlock", true, [], true, false)
	var hero_t5_ent: Dictionary = wb_t5.get_entity(hero_t5)
	var spr_t5: String = wb_t5.add_object_sprite("spr_t5", "Crate", Vector2(200, 100), Vector2(40, 80), "", 0.0, Vector2(1.5, 2.0), true)
	var spr_t5_before: Dictionary = wb_t5.get_entity(spr_t5).duplicate(true)
	var sb_on_spr_parked: bool = wb_t5.scene_box().attach_scene_box(spr_t5, sc_t5, "", "visited_unlock", true, [], true, false)
	var spr_t5_after: Dictionary = wb_t5.get_entity(spr_t5)
	results["tier5_bug01_scene_box_parked_ok"] = (
		not sb_on_unit_parked
		and _find_comp(hero_t5_ent, "comp_scene_box.gd").is_empty()
		and sb_on_spr_parked
		and spr_t5_after.get("entity_size") == spr_t5_before.get("entity_size")
		and spr_t5_after.get("selectable_in_select_mode") == spr_t5_before.get("selectable_in_select_mode")
		and (spr_t5_after.get("xform", {}) as Dictionary).get("scale") == (spr_t5_before.get("xform", {}) as Dictionary).get("scale")
		and ((spr_t5_after["components"][0] as Dictionary)["state"] as Dictionary).get("visible") == ((spr_t5_before["components"][0] as Dictionary)["state"] as Dictionary).get("visible")
		and not _find_comp(spr_t5_after, "comp_scene_box.gd").is_empty()
	)

	var wb_t5_area = sdk_t5.create_world_builder(sdk_t5.create_session(MockHost.new(), {}), 150.0)
	wb_t5_area.set_enabled_modules(["areas"])
	var area_add_res: Dictionary = wb_t5_area.areas().add_area_entity(
		"area_t5", "Zone", Vector2.ZERO, Vector2(64, 64), [[Vector2(0, 0), Vector2(64, 0), Vector2(64, 64)]], 1.0
	)
	var setup_after_area: Dictionary = wb_t5_area.setup(wb_t5_area._session, 150.0)
	results["tier5_bug07_areas_wb_setup_ok"] = (
		bool(area_add_res.get("ok", false))
		and int(wb_t5_area.get_entity_count()) == 1
		and not bool(setup_after_area.get("ok", true))
		and str(setup_after_area.get("reason", "")) == "world_builder_already_has_entities"
		and wb_t5_area.get_world()["entity_state"]["entities"].size() == 1
	)

	var ink_t5_ent: String = wb_t5.add_object_sprite("ink_t5", "NotePad", Vector2(300, 100), Vector2(64, 64), "")
	var ink_stroke: Dictionary = wb_t5.drawing().make_entity_stroke([Vector2(0.1, 0.1), Vector2(0.8, 0.8)], Color.CYAN, 0.02, 0.9)
	var set_ink_ok: Dictionary = wb_t5.drawing().set_entity_ink(ink_t5_ent, [ink_stroke])
	var set_ink_bad: Dictionary = wb_t5.drawing().set_entity_ink(ink_t5_ent, [{"id": "bad id!"}])
	var ink_comp_t5: Dictionary = _find_comp(wb_t5.get_entity(ink_t5_ent), "comp_entity_ink.gd")
	results["tier5_drawing_set_entity_ink_ok"] = (
		bool(set_ink_ok.get("ok", false))
		and not ink_comp_t5.is_empty()
		and ((ink_comp_t5.get("state", {}) as Dictionary).get("strokes", []) as Array).size() == 1
		and not bool(set_ink_bad.get("ok", true))
	)

	var f := FileAccess.open("res://probe_results.json", FileAccess.WRITE)
	f.store_string(JSON.stringify(results))
	f.close()
	quit(0)
'''


class TestFuSdkM2HeadlessGodot(unittest.TestCase):
    """Real headless Godot verification for all 9 M2 optional/candidate plugins."""

    run_dir: Path | None = None
    results: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_WORKSPACE_ROOT)
        godot_bin = cfg.godot_bin
        if godot_bin is None or not godot_bin.is_file():
            raise unittest.SkipTest("GODOT_BIN not configured in .env.local; skipping headless Godot tests")

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.run_dir = TEST_TMP_ROOT / f"fu_sdk_m2_{uuid.uuid4().hex[:10]}"
        probe_dir = cls.run_dir / "probe_proj"
        probe_dir.mkdir(parents=True, exist_ok=True)
        (probe_dir / "project.godot").write_bytes(
            b'[gd_resource type="ProjectFile" format=3]\n\nconfig_version=5\n\n[application]\nconfig/name="FuSdkM2Probe"\n'
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
            raise RuntimeError(f"Godot M2 probe exited {proc.returncode}:\n{combined}")
        if cls.log_errors:
            raise AssertionError(f"Godot M2 probe emitted errors/leaks: {cls.log_errors}\n{combined}")

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

    def test_discovery_and_lifecycle(self) -> None:
        self.assertTrue(self.results["discovery_ok"])
        self.assertEqual(self.results["entity_notes_status"], "uncatalogued_candidate")

    def test_r2_warnings_preserve_skip_and_portal_requires_areas(self) -> None:
        self.assertTrue(self.results["r2_preserve_ok"])
        self.assertTrue(self.results["r2_skip_ok"])
        self.assertTrue(self.results["portal_missing_areas_warn_ok"])

    def test_comp_unit_map_rejection(self) -> None:
        self.assertTrue(self.results["comp_unit_map_rejected"])

    def test_grid_alignment_bounds_cross_track_fix(self) -> None:
        self.assertTrue(self.results["grid_alignment_ok"])

    def test_simple_fog_coercion_bounds_and_sfh2(self) -> None:
        self.assertTrue(self.results["simple_fog_ok"])

    def test_scene_box_repository_and_component(self) -> None:
        self.assertTrue(self.results["scene_box_ok"])

    def test_areas_portal_and_image_flip_conflicts(self) -> None:
        self.assertTrue(self.results["areas_portal_flip_ok"])

    def test_drag_movement_v1_migration_and_component(self) -> None:
        self.assertTrue(self.results["drag_movement_ok"])

    def test_drawing_world_text_ink_and_entity_ink(self) -> None:
        self.assertTrue(self.results["drawing_ok"])

    def test_entity_notes_candidate_auto_park(self) -> None:
        self.assertTrue(self.results["entity_notes_ok"])

    def test_world_var_to_bytes_roundtrip(self) -> None:
        self.assertTrue(self.results["roundtrip_ok"])

    def test_ref_cycle_zero_object_leak(self) -> None:
        self.assertEqual(self.results["leak_20_delta"], 0.0)
        self.assertEqual(self.results["leak_40_delta"], 0.0)
        self.assertTrue(self.results["ref_cycle_leak_zero_ok"])

    def test_simple_fog_strict_alpha_and_sfh2_min_len(self) -> None:
        self.assertTrue(self.results["simple_fog_strict_alpha_and_sfh2_ok"])

    def test_simple_fog_standalone_parity_and_manual_warn(self) -> None:
        self.assertTrue(self.results["simple_fog_standalone_parity_and_warn_ok"])

    def test_drawing_sequential_default_order_and_id(self) -> None:
        self.assertTrue(self.results["drawing_sequential_default_order_ok"])

    def test_drawing_standalone_5120_capacity(self) -> None:
        self.assertTrue(self.results["drawing_standalone_5120_ok"])

    def test_areas_empty_paths_rejected_no_orphan(self) -> None:
        self.assertTrue(self.results["areas_empty_paths_rejected_no_orphan_ok"])

    def test_m6_ergonomics_aliases_and_json_float_coercion(self) -> None:
        self.assertTrue(self.results["m6_ergonomics_and_coercion_ok"])

    def test_m6_tier2_contract_fixes_regression(self) -> None:
        self.assertTrue(self.results["m6_tier2_fixes_ok"])

    def test_scene_box_rejects_simple_fog_attach_vision_and_light(self) -> None:
        self.assertTrue(self.results["scene_box_simple_fog_conflicts_ok"])

    def test_tier5_bug01_scene_box_parked_no_unit_and_no_host_mutation(self) -> None:
        self.assertTrue(self.results["tier5_bug01_scene_box_parked_ok"])

    def test_tier5_bug07_areas_add_area_entity_blocks_destructive_re_setup(self) -> None:
        self.assertTrue(self.results["tier5_bug07_areas_wb_setup_ok"])

    def test_tier5_drawing_set_entity_ink(self) -> None:
        self.assertTrue(self.results["tier5_drawing_set_entity_ink_ok"])


if __name__ == "__main__":
    unittest.main()
