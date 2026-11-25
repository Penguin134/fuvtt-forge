"""Tier 3: 35 Pairwise Conflict Matrix, Cross-Module Combination & Tooling/Console Integration Tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest
import zipfile

from .assertions import (
    assert_build_artifact_bundles_sdk,
    assert_case_passed,
    assert_entity_has_component,
    assert_logbus_entry_schema,
    assert_r2_warning_present,
    assert_world_module_entry,
    assert_world_v3_invariants,
)
from .harness import (
    E2ESession,
    GodotBatchProbe,
    SdkBatchSummary,
    SdkProbeCaseSpec,
    WORKSPACE_ROOT,
    load_workspace_config,
    run_fuvtt_cli,
    run_fuvtt_cli_isolated_mods,
    write_utf8_no_bom_lf,
)
from .tier1_features import (
    HEX32_A,
    HEX32_B,
    _valid_campaign_time_state,
    _valid_checklist_state,
    _valid_dnd_opportunity_state,
    _valid_drawing_state,
    _valid_entity_ink_stroke,
    _valid_initiative_state,
    _valid_resource_pool_defs,
    _valid_simple_fog_state,
)


def _rejected(val: object) -> bool:
    if val is False:
        return True
    if isinstance(val, dict) and val.get("ok") is False:
        return True
    return False


class Tier3CombinationTests(unittest.TestCase):
    """35 pairwise conflict-matrix, mixed enablement/policy, and CLI/console integration tests."""

    session: E2ESession
    batch: SdkBatchSummary
    _cases_built: bool = False

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = E2ESession(name_prefix="tier3")
        cls.session.setup(require_godot=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.session.cleanup()

    @classmethod
    def _ensure_godot_batch(cls) -> SdkBatchSummary:
        if cls._cases_built:
            return cls.batch
        probe = GodotBatchProbe(cls.session)
        probe.prepare_from_mod("_template", use_real_mods=True)

        full_unit_params = {
            "pair": "valid_full_unit_stack",
            "image_flip": {"horizontal": True, "vertical": False},
            "drag_movement": {"speed": 64.0},
            "drawing": {"revision": HEX32_A, "strokes": [_valid_entity_ink_stroke()]},
            "resource_pool": {"schema_version": 1, "values": {}},
            "character_roster": {"schema_version": 1, "known_by": {"p1": HEX32_A}},
            "backpack": {"revision": "", "slots": {"0": {"name": "Dagger", "note": "", "qty": 1}}},
            "follow": {"target_id": "", "controller_id": "p1", "engaged": False, "follow_distance": 16.0},
            "candidate_initiative": {"count": 15, "modifier": 2, "active": False, "defeated": False, "rolled": True},
        }

        cases: list[SdkProbeCaseSpec] = [
            SdkProbeCaseSpec("t3_01", "conflict_matrix", {"pair": "image_flip_then_obstacle"}, enabled_modules=["image_flip"]),
            SdkProbeCaseSpec("t3_02", "conflict_matrix", {"pair": "obstacle_then_image_flip"}, enabled_modules=["image_flip"]),
            SdkProbeCaseSpec("t3_03", "conflict_matrix", {"pair": "image_flip_then_area"}, enabled_modules=["image_flip", "areas"]),
            SdkProbeCaseSpec("t3_04", "conflict_matrix", {"pair": "area_then_image_flip"}, enabled_modules=["image_flip", "areas"]),
            SdkProbeCaseSpec("t3_05", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "unit"}, enabled_modules=["scene_box"]),
            SdkProbeCaseSpec("t3_06a", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "obstacle"}, enabled_modules=["scene_box"]),
            SdkProbeCaseSpec("t3_06b", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "areas", "state": {"removed": False, "radius_in_cells": 1.0}}, enabled_modules=["scene_box", "areas"]),
            SdkProbeCaseSpec("t3_07a", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "image_flip", "state": {"horizontal": True, "vertical": False}}, enabled_modules=["scene_box", "image_flip"]),
            SdkProbeCaseSpec("t3_07b", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "portal"}, enabled_modules=["scene_box", "portal"]),
            SdkProbeCaseSpec("t3_08a", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "character_roster", "state": {"schema_version": 1, "known_by": {}}}, enabled_modules=["scene_box", "character_roster"]),
            SdkProbeCaseSpec("t3_08b", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "candidate_initiative", "state": {"count": 10, "modifier": 0, "active": False, "defeated": False, "rolled": False}}, enabled_modules=["scene_box", "candidate_initiative"]),
            SdkProbeCaseSpec("t3_09a", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "resource_pool", "state": {"schema_version": 1, "values": {}}}, enabled_modules=["scene_box", "resource_pool"]),
            SdkProbeCaseSpec("t3_09b", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "backpack", "state": {"revision": "", "slots": {}}}, enabled_modules=["scene_box", "backpack"]),
            SdkProbeCaseSpec("t3_10a", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "drag_movement", "state": {"speed": 64.0}}, enabled_modules=["scene_box", "drag_movement"]),
            SdkProbeCaseSpec("t3_10b", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "follow", "state": {"target_id": "", "controller_id": "", "engaged": False, "follow_distance": 16.0}}, enabled_modules=["scene_box", "follow"]),
            SdkProbeCaseSpec("t3_11a", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "simple_vision"}, enabled_modules=["scene_box", "simple_fog"]),
            SdkProbeCaseSpec("t3_11b", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "simple_light"}, enabled_modules=["scene_box", "simple_fog"]),
            SdkProbeCaseSpec("t3_12", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "drawing", "state": {"revision": "", "strokes": []}}, enabled_modules=["scene_box", "drawing"]),
            SdkProbeCaseSpec("t3_13", "conflict_matrix", {"pair": "scene_box_on_map"}, enabled_modules=["scene_box"]),
            SdkProbeCaseSpec("t3_14", "conflict_matrix", {"pair": "unit_only_on_non_unit_or_map", "target_module": "backpack", "state": {"revision": "", "slots": {}}}, enabled_modules=["backpack"]),
            SdkProbeCaseSpec("t3_15", "conflict_matrix", {"pair": "unit_only_on_non_unit_or_map", "target_module": "character_roster", "state": {"schema_version": 1, "known_by": {}}}, enabled_modules=["character_roster"]),
            SdkProbeCaseSpec("t3_16", "conflict_matrix", {"pair": "initiative_on_obstacle_and_wall"}, enabled_modules=["candidate_initiative"]),
            SdkProbeCaseSpec("t3_17", "conflict_matrix", {"pair": "unit_only_on_non_unit_or_map", "target_module": "candidate_initiative", "state": {"count": 10, "modifier": 0, "active": False, "defeated": False, "rolled": False}}, enabled_modules=["candidate_initiative"]),
            SdkProbeCaseSpec(
                "t3_18",
                "conflict_matrix",
                full_unit_params,
                enabled_modules=["simple_fog", "image_flip", "drag_movement", "drawing", "resource_pool", "character_roster", "backpack", "follow", "candidate_initiative"],
            ),
            SdkProbeCaseSpec(
                "t3_19",
                "scenario_run",
                {
                    "scenario": "playtest_migration",
                    "campaign_time": _valid_campaign_time_state(),
                    "dnd_opportunity": _valid_dnd_opportunity_state(),
                },
                enabled_modules=["scene_box", "simple_fog", "drawing"],
                disabled_policy="preserve",
            ),
            SdkProbeCaseSpec(
                "t3_20",
                "scenario_run",
                {
                    "scenario": "strict_skip_audit",
                    "fog_state": _valid_simple_fog_state(),
                    "campaign_time": _valid_campaign_time_state(),
                    "dnd_opportunity": _valid_dnd_opportunity_state(),
                },
                enabled_modules=["scene_box", "drawing"],
                disabled_policy="skip",
            ),
            SdkProbeCaseSpec(
                "t3_21",
                "plugin_domain",
                {"module_id": "feature_entity_library", "sub_op": "mixed_presets_enabled_disabled"},
                enabled_modules=["simple_fog"],
            ),
            SdkProbeCaseSpec(
                "t3_22",
                "scenario_run",
                {"scenario": "dungeon_crawl", "fog_state": _valid_simple_fog_state(with_exploration=True)},
                enabled_modules=["scene_box", "portal", "simple_fog", "grid_alignment"],
            ),
            SdkProbeCaseSpec("t3_23", "parked_manual", {"sub_op": "multi_parked"}),
            SdkProbeCaseSpec(
                "t3_24",
                "scenario_run",
                {"scenario": "multi_floor_layer_override_areas_ink", "ink_state": {"revision": HEX32_A, "strokes": [_valid_entity_ink_stroke()]}},
                enabled_modules=["areas", "drawing"],
            ),
            SdkProbeCaseSpec("t3_26", "logbus_test", {"sub_op": "session_builder_host"}),
            SdkProbeCaseSpec("t3_27", "logbus_test", {"sub_op": "query_and_clear"}),
            SdkProbeCaseSpec(
                "t3_28",
                "plugin_domain",
                {"module_id": "checklist", "action": "configure", "state": _valid_checklist_state(audience="gm", entity_id=HEX32_A, more_entity_ids=[HEX32_B])},
                enabled_modules=["checklist"],
            ),
            SdkProbeCaseSpec(
                "t3_30",
                "plugin_domain",
                {"module_id": "drawing", "action": "configure", "state": _valid_drawing_state(with_text=True)},
                enabled_modules=["drawing", "grid_alignment"],
            ),
        ]

        cls.batch = probe.run_batch(cases, timeout_seconds=180)
        cls._cases_built = True
        return cls.batch

    def _data(self, case_id: str) -> dict:
        batch = self._ensure_godot_batch()
        self.assertEqual(batch.compile_failures, [], f"Compile failures: {batch.compile_failures}")
        self.assertEqual(batch.global_log_errors, [], f"Global Godot log errors: {batch.global_log_errors}")
        return assert_case_passed(self, batch.results[case_id])

    # --- Conflict matrix tests (18 cases) ---
    def test_t3_01_conflict_image_flip_then_obstacle(self) -> None:
        d = self._data("t3_01")
        self.assertTrue(_rejected(d.get("second")))

    def test_t3_02_conflict_obstacle_then_image_flip(self) -> None:
        d = self._data("t3_02")
        self.assertTrue(_rejected(d.get("second")))

    def test_t3_03_conflict_image_flip_then_area(self) -> None:
        d = self._data("t3_03")
        self.assertTrue(_rejected(d.get("second")))

    def test_t3_04_conflict_area_then_image_flip(self) -> None:
        d = self._data("t3_04")
        self.assertTrue(_rejected(d.get("second")))

    def test_t3_05_conflict_scene_box_then_unit(self) -> None:
        d = self._data("t3_05")
        self.assertTrue(_rejected(d.get("second")))

    def test_t3_06_conflict_scene_box_then_obstacle_and_area(self) -> None:
        self.assertTrue(_rejected(self._data("t3_06a").get("second")))
        self.assertTrue(_rejected(self._data("t3_06b").get("second")))

    def test_t3_07_conflict_scene_box_then_image_flip_and_portal(self) -> None:
        self.assertTrue(_rejected(self._data("t3_07a").get("second")))
        self.assertTrue(_rejected(self._data("t3_07b").get("second")))

    def test_t3_08_conflict_scene_box_then_character_roster_and_initiative(self) -> None:
        self.assertTrue(_rejected(self._data("t3_08a").get("second")))
        self.assertTrue(_rejected(self._data("t3_08b").get("second")))

    def test_t3_09_conflict_scene_box_then_resource_pool_and_backpack(self) -> None:
        self.assertTrue(_rejected(self._data("t3_09a").get("second")))
        self.assertTrue(_rejected(self._data("t3_09b").get("second")))

    def test_t3_10_conflict_scene_box_then_drag_speed_and_follow(self) -> None:
        self.assertTrue(_rejected(self._data("t3_10a").get("second")))
        self.assertTrue(_rejected(self._data("t3_10b").get("second")))

    def test_t3_11_conflict_scene_box_then_simple_vision_and_light(self) -> None:
        self.assertTrue(_rejected(self._data("t3_11a").get("second")))
        self.assertTrue(_rejected(self._data("t3_11b").get("second")))

    def test_t3_12_conflict_scene_box_then_entity_ink(self) -> None:
        self.assertTrue(_rejected(self._data("t3_12").get("second")))

    def test_t3_13_conflict_scene_box_on_map_entity(self) -> None:
        self.assertTrue(_rejected(self._data("t3_13").get("second")))

    def test_t3_14_conflict_backpack_on_map_and_non_unit(self) -> None:
        d = self._data("t3_14")
        self.assertTrue(_rejected(d.get("on_non_unit")))
        self.assertTrue(_rejected(d.get("on_map")))

    def test_t3_15_conflict_character_roster_on_map_and_non_unit(self) -> None:
        d = self._data("t3_15")
        self.assertTrue(_rejected(d.get("on_non_unit")))
        self.assertTrue(_rejected(d.get("on_map")))

    def test_t3_16_conflict_initiative_on_obstacle_and_wall(self) -> None:
        d = self._data("t3_16")
        self.assertTrue(_rejected(d.get("on_wall")))
        self.assertTrue(_rejected(d.get("on_obstacle")))

    def test_t3_17_conflict_initiative_on_map_and_non_unit(self) -> None:
        d = self._data("t3_17")
        self.assertTrue(_rejected(d.get("on_non_unit")))
        self.assertTrue(_rejected(d.get("on_map")))

    def test_t3_18_valid_unit_stack_with_all_compatible_components(self) -> None:
        d = self._data("t3_18")
        assert_world_v3_invariants(self, d["world"], "t3_18")
        self.assertEqual(d.get("roundtrip_diff"), "")
        ent = d["world"]["entity_state"]["entities"][0]
        self.assertGreaterEqual(len(ent["components"]), 12)

    # --- Mixed enablement, policy, multi-scene, LogBus, CLI, Console mod (17 cases) ---
    def test_t3_19_mixed_enablement_preserve_policy(self) -> None:
        d = self._data("t3_19")
        assert_world_v3_invariants(self, d["world"], "t3_19")
        assert_world_module_entry(self, d["world"], "campaign_time")
        assert_world_module_entry(self, d["world"], "dnd_opportunity")
        assert_r2_warning_present(self, d.get("log_entries", []), "campaign_time")
        assert_r2_warning_present(self, d.get("log_entries", []), "dnd_opportunity")
        assert_r2_warning_present(self, d.get("log_entries", []), "entity_notes")

    def test_t3_20_mixed_enablement_skip_policy(self) -> None:
        d = self._data("t3_20")
        entries = d["world"]["modules"]["entries"]
        self.assertNotIn("simple_fog", entries)
        self.assertNotIn("campaign_time", entries)
        self.assertNotIn("dnd_opportunity", entries)
        assert_r2_warning_present(self, d.get("log_entries", []), "simple_fog", policy="skip")

    def test_t3_21_entity_library_preset_mixed_enabled_disabled_modules(self) -> None:
        d = self._data("t3_21")
        reg = d.get("reg_result", {})
        self.assertIs(reg.get("ok"), True)
        self.assertEqual(reg.get("count"), 2)
        self.assertEqual(len(reg.get("warned_presets", [])), 1)
        assert_r2_warning_present(self, d.get("log_entries", []), "portal")
        assert_r2_warning_present(self, d.get("log_entries", []), "areas")
        self.assertEqual(len(d.get("decoded_records", {})), 2)

    def test_t3_22_multi_scene_multi_floor_cross_floor_portals_and_fog(self) -> None:
        d = self._data("t3_22")
        assert_world_v3_invariants(self, d["world"], "t3_22")
        assert_world_module_entry(self, d["world"], "scene_box")
        assert_world_module_entry(self, d["world"], "simple_fog")
        assert_world_module_entry(self, d["world"], "grid_alignment")

    def test_t3_23_parked_auto_vs_manual_across_disabled_optional_modules(self) -> None:
        d = self._data("t3_23")
        ent = d["world"]["entity_state"]["entities"][0]
        assert_entity_has_component(self, ent, "res://modules/areas/comp_area.gd", parked=True, manual=False)
        assert_entity_has_component(self, ent, "res://modules/portal/comp_portal.gd", parked=True, manual=True)
        assert_entity_has_component(self, ent, "res://modules/follow/comp_follow.gd", parked=True, manual=False)

    def test_t3_24_multi_floor_layer_override_with_areas_and_entity_ink(self) -> None:
        d = self._data("t3_24")
        assert_world_v3_invariants(self, d["world"], "t3_24")
        self.assertEqual(d.get("roundtrip_diff"), "")
        self.assertGreaterEqual(int(d.get("floor_count", 0)), 3)
        members = {m["entity_id"]: m for m in d["world"]["members"]}
        self.assertEqual(members[d["area_entity_id"]]["layer_uid"], d["area_layer_uid"])
        self.assertEqual(members[d["ink_entity_id"]]["layer_uid"], d["ink_layer_uid"])
        ents = {e["id"]: e for e in d["world"]["entity_state"]["entities"]}
        assert_entity_has_component(self, ents[d["area_entity_id"]], "res://modules/areas/comp_area.gd")
        assert_entity_has_component(self, ents[d["ink_entity_id"]], "res://modules/drawing/comp_entity_ink.gd")

    def test_t3_25_logbus_subscriber_captures_r2_warnings_from_disabled_plugins(self) -> None:
        d = self._data("t3_19")
        warnings = [e for e in d.get("log_entries", []) if e.get("level") == 30]
        self.assertGreaterEqual(len(warnings), 3)
        for w in warnings:
            assert_logbus_entry_schema(self, w, expected_level=30)

    def test_t3_26_logbus_import_session_host_bridge_warn_dedup_and_report(self) -> None:
        d = self._data("t3_26")
        self.assertIs(d.get("same_logger"), True)
        self.assertEqual(d.get("progress_before_opt_in"), [])
        self.assertEqual(d.get("before_forward_count"), 0)
        self.assertIn("progress hello", " ".join(d.get("host_progress", [])))
        self.assertEqual(len(d.get("host_warnings", [])), 1)
        self.assertIn("warning hello", d["host_warnings"][0])

    def test_t3_27_logbus_reader_since_seq_cursor_streaming(self) -> None:
        d = self._data("t3_27")
        self.assertEqual(len(d.get("since_first", [])), 3)
        self.assertEqual(len(d.get("limited_2", [])), 2)

    def test_t3_28_checklist_plus_entity_linkage(self) -> None:
        d = self._data("t3_28")
        st = assert_world_module_entry(self, d["world"], "checklist")
        row = st["rows"][HEX32_A]
        self.assertEqual(row["entity_id"], HEX32_A)
        self.assertEqual(row["more_entity_ids"], [HEX32_B])

    def test_t3_29_simple_fog_plus_obstacle_doors_and_vision_light(self) -> None:
        d = self._data("t3_22")
        assert_world_module_entry(self, d["world"], "simple_fog")
        ents = d["world"]["entity_state"]["entities"]
        all_scripts = {c.get("script") for e in ents for c in e.get("components", [])}
        self.assertIn("res://modules/simple_fog/comp_simple_vision.gd", all_scripts)
        self.assertIn("res://modules/simple_fog/comp_simple_light.gd", all_scripts)
        obs_kinds = {
            e["components"][0].get("state", {}).get("vector_drawing", {}).get("source", {}).get("kind")
            for e in ents
            if e.get("components")
        }
        self.assertIn("wall", obs_kinds)
        self.assertIn("door", obs_kinds)

    def test_t3_30_drawing_world_strokes_text_plus_grid_alignment(self) -> None:
        d = self._data("t3_30")
        st = assert_world_module_entry(self, d["world"], "drawing")
        self.assertEqual(len(st["strokes"]), 2)

    def test_t3_31_cli_build_then_extract_vendored_sdk_equals_shared_sdk(self) -> None:
        assert self.session.build_dir is not None and self.session.cache_dir is not None
        res = run_fuvtt_cli(["build", "_template"], build_dir=self.session.build_dir, cache_dir=self.session.cache_dir)
        self.assertEqual(res.returncode, 0, res.stderr)
        cfg = load_workspace_config()
        manifest = assert_build_artifact_bundles_sdk(self, self.session.build_dir, "_template")
        zip_path = self.session.build_dir / "_template" / "_template.zip"
        with zipfile.ZipFile(zip_path, "r") as zf:
            for src_gd in sorted(cfg.sdk_dir.rglob("*.gd")):
                rel = src_gd.relative_to(cfg.sdk_dir).as_posix()
                member = f"lib/fu_sdk/{rel}"
                self.assertEqual(
                    hashlib.sha256(zf.read(member)).hexdigest(),
                    hashlib.sha256(src_gd.read_bytes()).hexdigest(),
                    f"Vendored SDK mismatch for {member}",
                )
        self.assertTrue(manifest["sdk_bundled"])

    def test_t3_32_console_mod_with_logbus_options_and_sample_import(self) -> None:
        assert self.session.run_dir is not None
        sample = self.session.run_dir / "t3_32_sample.json"
        sample.write_text(json.dumps({"hello": "console"}), encoding="utf-8")
        probe = GodotBatchProbe(self.session)
        probe.prepare_from_mod("sdk-log-console", use_real_mods=True)
        b = probe.run_batch([SdkProbeCaseSpec("t3_32", "console_mod_probe", {"sample_path": sample.as_posix()})], timeout_seconds=90)
        self.assertEqual(b.compile_failures, [])
        self.assertEqual(b.global_log_errors, [])
        d = assert_case_passed(self, b.results["t3_32"])
        self.assertIs(d["inspect_result"]["ok"], True)
        self.assertIs(d["prepare_result"]["ok"], True)
        self.assertTrue(d.get("host_progress"))
        assert_world_v3_invariants(self, d["prepare_result"]["world"], "t3_32")

    def test_t3_33_console_mod_verify_host_with_custom_sample_file(self) -> None:
        assert self.session.run_dir is not None and self.session.build_dir is not None and self.session.cache_dir is not None
        sample = self.session.run_dir / "t3_33_sample.log"
        sample.write_text("DEBUG init\nWARN disabled module test\n", encoding="utf-8")
        res = run_fuvtt_cli(
            ["verify-host", "sdk-log-console", "--sample", str(sample)],
            build_dir=self.session.build_dir,
            cache_dir=self.session.cache_dir,
        )
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")

    def test_t3_34_synthetic_mod_using_multiple_plugin_sdks_build_and_verify_host(self) -> None:
        iso_cfg = self.session.make_isolated_config()
        r_init = run_fuvtt_cli_isolated_mods(["init", "multi-sdk-consumer", "--ext", "json"], iso_cfg=iso_cfg)
        self.assertEqual(r_init.returncode, 0, r_init.stderr)

        custom_entry = """extends RefCounted

const _SDK_PACKAGED_REL_PATH: String = "lib/fu_sdk/v1.gd"

func _load_sdk_script() -> Script:
\tvar self_script := get_script() as Script
\tvar base_dir: String = self_script.resource_path.split("::")[0].get_base_dir()
\treturn load(base_dir.path_join(_SDK_PACKAGED_REL_PATH)) as Script

func inspect_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:
\tvar sdk: RefCounted = _load_sdk_script().new()
\tvar session = sdk.create_session(host, options)
\treturn session.ok_inspect(path, {"records": 1}, {})

func prepare_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:
\tvar sdk: RefCounted = _load_sdk_script().new()
\tvar session = sdk.create_session(host, options)
\tvar logger = session.get_logger()
\tlogger.attach_import_host(host)
\tlogger.debug("consumer", "start prepare", {"path": path})
\tvar builder = sdk.create_world_builder(session, 150.0)
\tbuilder.set_enabled_modules(["grid_alignment", "portal"])
\tvar grid_sdk = builder.get_plugin_sdk("grid_alignment")
\tvar portal_sdk = builder.get_plugin_sdk("portal")
\tvar fog_sdk = builder.get_plugin_sdk("simple_fog")
\tif grid_sdk == null or portal_sdk == null or fog_sdk == null:
\t\treturn session.err_failed("missing_plugin_sdk")
\tbuilder.configure_grid_alignment(64.0)
\tvar t1: String = builder.add_token("t1", "Hero", Vector2(50, 50), Vector2(64, 64), "")
\tbuilder.attach_portal(t1, "p_key")
\tbuilder.finish_geometry_preview()
\treturn builder.build_result(1, 0)
"""
        write_utf8_no_bom_lf(iso_cfg.mods_dir / "multi-sdk-consumer" / "entry.gd", custom_entry)
        r_val = run_fuvtt_cli_isolated_mods(["validate", "multi-sdk-consumer"], iso_cfg=iso_cfg)
        self.assertEqual(r_val.returncode, 0, f"{r_val.stdout}\n{r_val.stderr}")
        r_bld = run_fuvtt_cli_isolated_mods(["build", "multi-sdk-consumer"], iso_cfg=iso_cfg)
        self.assertEqual(r_bld.returncode, 0, f"{r_bld.stdout}\n{r_bld.stderr}")
        r_ver = run_fuvtt_cli_isolated_mods(["verify-host", "multi-sdk-consumer"], iso_cfg=iso_cfg)
        self.assertEqual(r_ver.returncode, 0, f"{r_ver.stdout}\n{r_ver.stderr}")

    def test_t3_35_playtest_blocked_plus_candidate_preserve_roundtrip_world_v3(self) -> None:
        d = self._data("t3_19")
        assert_world_v3_invariants(self, d["world"], "t3_35")
        self.assertEqual(d.get("roundtrip_diff"), "")
