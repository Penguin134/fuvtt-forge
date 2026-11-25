"""Tier 4: 18 Realistic Multi-Feature End-to-End Application Scenario Tests (6 Workflows)."""

from __future__ import annotations

import json
import unittest

from .assertions import (
    assert_build_artifact_bundles_sdk,
    assert_case_passed,
    assert_entity_has_component,
    assert_logbus_entry_schema,
    assert_no_local_paths_in_text,
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
    is_git_ignored,
    list_git_tracked,
    load_workspace_config,
    run_fuvtt_cli,
    run_fuvtt_cli_isolated_mods,
    run_git_readonly,
    write_utf8_no_bom_lf,
)
from .tier1_features import (
    HEX32_A,
    HEX32_B,
    _valid_campaign_time_state,
    _valid_dice_state,
    _valid_dnd_opportunity_state,
    _valid_drawing_state,
    _valid_initiative_state,
    _valid_resource_pool_defs,
    _valid_simple_fog_state,
)


def _checklist_50_rows() -> dict:
    rows = {}
    for i in range(50):
        rows[f"{i:032x}"] = {
            "title": f"Objective #{i + 1}",
            "description": f"Step {i + 1} in dungeon",
            "category": "Campaign",
            "audience": "all",
            "player_id": "",
            "entity_id": "",
            "source": "mod:e2e",
            "manual": False,
            "done": (i % 3 == 0),
            "archived": False,
            "order": i + 1,
            "last_motion": "",
        }
    return {"schema": 2, "rows": rows}


class Tier4ScenarioTests(unittest.TestCase):
    """18 application-level E2E tests across all 6 real-world workflows."""

    session: E2ESession
    batch: SdkBatchSummary
    _cases_built: bool = False

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = E2ESession(name_prefix="tier4")
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

        pool_defs = _valid_resource_pool_defs()
        pool_defs["definitions"]["resource_pool:spell_1"] = {
            "id": "resource_pool:spell_1",
            "source": "resource_pool",
            "name": "Level 1 Slots",
            "maximum": 4.0,
            "color": "#3366EEFF",
            "display": "count",
            "visibility": "controllers",
        }
        backpack_16 = {
            "revision": HEX32_A,
            "slots": {str(i): {"name": f"Gear_{i}", "note": "5e", "qty": 1} for i in range(16)},
        }

        cases: list[SdkProbeCaseSpec] = [
            SdkProbeCaseSpec(
                "t4_s01_dungeon",
                "scenario_run",
                {"scenario": "dungeon_crawl", "fog_state": _valid_simple_fog_state(with_exploration=True)},
                enabled_modules=["scene_box", "portal", "simple_fog", "grid_alignment"],
            ),
            SdkProbeCaseSpec(
                "t4_s02_dnd5e",
                "scenario_run",
                {
                    "scenario": "dnd5e_combat",
                    "dice_state": _valid_dice_state(expr="burst(2d6)"),
                    "pool_defs": pool_defs,
                    "init_state": _valid_initiative_state(phase="active"),
                    "backpack_state": backpack_16,
                    "follow_state": {"target_id": HEX32_A, "controller_id": "p1", "engaged": True, "follow_distance": 16.0},
                },
                enabled_modules=["backpack", "resource_pool", "character_roster", "candidate_initiative", "follow", "drag_movement", "dice"],
            ),
            SdkProbeCaseSpec(
                "t4_s03_migration",
                "scenario_run",
                {
                    "scenario": "playtest_migration",
                    "campaign_time": _valid_campaign_time_state(),
                    "dnd_opportunity": _valid_dnd_opportunity_state(2014),
                },
                enabled_modules=[],
                disabled_policy="preserve",
            ),
            SdkProbeCaseSpec(
                "t4_s04_skip",
                "scenario_run",
                {
                    "scenario": "strict_skip_audit",
                    "fog_state": _valid_simple_fog_state(),
                    "campaign_time": _valid_campaign_time_state(),
                    "dnd_opportunity": _valid_dnd_opportunity_state(2014),
                },
                enabled_modules=[],
                disabled_policy="skip",
            ),
            SdkProbeCaseSpec(
                "t4_s05_scale",
                "scenario_run",
                {
                    "scenario": "large_world_stress",
                    "drawing_state": _valid_drawing_state(with_text=True),
                    "checklist_state": _checklist_50_rows(),
                    "omit_world_dump": True,
                },
                enabled_modules=["drawing", "checklist", "areas", "image_flip"],
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

    # --- Workflow 1: Multi-Scene Dungeon Crawl Import ---
    def test_t4_s01_01_dungeon_crawl_scenes_portals_and_obstacles(self) -> None:
        d = self._data("t4_s01_dungeon")
        sb = assert_world_module_entry(self, d["world"], "scene_box")
        self.assertEqual(len(sb["scenes"]), 2)
        portal_ents = [
            e for e in d["world"]["entity_state"]["entities"]
            if any(c.get("script") == "res://modules/portal/comp_portal.gd" for c in e["components"])
        ]
        self.assertEqual(len(portal_ents), 2)
        portal_warns = [
            entry for entry in d.get("log_entries", [])
            if entry.get("level_name") == "WARNING"
            and isinstance(entry.get("context"), dict)
            and entry["context"].get("module_id") == "portal"
        ]
        self.assertGreaterEqual(len(portal_warns), 2)
        self.assertIn("areas", portal_warns[0]["context"].get("missing_requires", []))

    def test_t4_s01_02_dungeon_crawl_simple_fog_vision_light_and_grid(self) -> None:
        d = self._data("t4_s01_dungeon")
        fog = assert_world_module_entry(self, d["world"], "simple_fog")
        self.assertTrue(bytes(fog.get("exploration", b"")).startswith(b"SFH2"))
        assert_world_module_entry(self, d["world"], "grid_alignment")

    def test_t4_s01_03_dungeon_crawl_world_v3_and_var_to_bytes_roundtrip(self) -> None:
        d = self._data("t4_s01_dungeon")
        assert_world_v3_invariants(self, d["world"], "t4_s01_03")
        self.assertEqual(d.get("roundtrip_diff"), "")

    # --- Workflow 2: D&D 5e Party & Combat Encounter Setup ---
    def test_t4_s02_01_dnd5e_party_units_backpack_and_resource_pools(self) -> None:
        d = self._data("t4_s02_dnd5e")
        rp = assert_world_module_entry(self, d["world"], "resource_pool")
        self.assertIn("resource_pool:hp", rp["definitions"])
        self.assertIn("resource_pool:spell_1", rp["definitions"])
        cr = assert_world_module_entry(self, d["world"], "character_roster")
        self.assertIs(cr.get("auto_join"), True)
        hero0 = d["world"]["entity_state"]["entities"][0]
        bp = assert_entity_has_component(self, hero0, "res://modules/backpack/comp_backpack.gd")
        self.assertEqual(len(bp["state"]["slots"]), 16)

    def test_t4_s02_02_dnd5e_active_initiative_follow_drag_and_dice(self) -> None:
        d = self._data("t4_s02_dnd5e")
        init_st = assert_world_module_entry(self, d["world"], "candidate_initiative")
        self.assertEqual(init_st.get("world_id"), "world_e2e_1")
        self.assertEqual(init_st.get("phase"), "active")
        self.assertEqual(init_st.get("round"), 1)
        fam4 = d["world"]["entity_state"]["entities"][4]
        follow_comp = assert_entity_has_component(self, fam4, "res://modules/follow/comp_follow.gd")
        self.assertEqual(follow_comp["state"].get("target_id"), HEX32_A)
        self.assertIs(follow_comp["state"].get("engaged"), True)
        dm_st = assert_world_module_entry(self, d["world"], "drag_movement")
        self.assertEqual(dm_st.get("version"), 2)
        dice_st = assert_world_module_entry(self, d["world"], "dice")
        self.assertEqual(dice_st["workspace"]["combos"][0]["expr"], "burst(2d6)")

    def test_t4_s02_03_dnd5e_encounter_world_invariants_and_roundtrip(self) -> None:
        d = self._data("t4_s02_dnd5e")
        assert_world_v3_invariants(self, d["world"], "t4_s02_03")
        self.assertEqual(d.get("roundtrip_diff"), "")
        self.assertEqual(len(d["world"]["entity_state"]["entities"]), 5)

    # --- Workflow 3: Playtest v0.0.61/v0.0.62 Save Migration ---
    def test_t4_s03_01_playtest_migration_blocked_modules_preserved(self) -> None:
        d = self._data("t4_s03_migration")
        assert_world_module_entry(self, d["world"], "campaign_time")
        assert_world_module_entry(self, d["world"], "dnd_opportunity")
        assert_r2_warning_present(self, d.get("log_entries", []), "campaign_time", status="playtest_blocked", policy="preserve")
        assert_r2_warning_present(self, d.get("log_entries", []), "dnd_opportunity", status="playtest_blocked", policy="preserve")

    def test_t4_s03_02_playtest_migration_candidate_and_disabled_parked_manual(self) -> None:
        d = self._data("t4_s03_migration")
        ent = d["world"]["entity_state"]["entities"][0]
        assert_entity_has_component(self, ent, "res://scenes/candidates/entity_notes/comp_entity_note.gd", parked=True)
        assert_entity_has_component(self, ent, "res://modules/areas/comp_area.gd", parked=True, manual=True)
        assert_r2_warning_present(self, d.get("log_entries", []), "entity_notes", status="uncatalogued_candidate")

    def test_t4_s03_03_playtest_migration_host_bridge_warnings_and_roundtrip(self) -> None:
        d = self._data("t4_s03_migration")
        assert_world_v3_invariants(self, d["world"], "t4_s03_03")
        self.assertEqual(d.get("roundtrip_diff"), "")
        self.assertGreaterEqual(len(d.get("host_warnings", [])), 3)

    # --- Workflow 4: Strict "skip" Policy & Console Mod Diagnostic Pipeline ---
    def test_t4_s04_01_console_mod_packaged_and_git_tracked(self) -> None:
        assert self.session.build_dir is not None and self.session.cache_dir is not None
        self.assertFalse(is_git_ignored("mods/sdk-log-console/plugin.json"))
        tracked = list_git_tracked("mods/sdk-log-console/")
        self.assertIn("mods/sdk-log-console/entry.gd", tracked)
        res = run_fuvtt_cli(["build", "sdk-log-console"], build_dir=self.session.build_dir, cache_dir=self.session.cache_dir)
        self.assertEqual(res.returncode, 0, res.stderr)
        assert_build_artifact_bundles_sdk(self, self.session.build_dir, "sdk-log-console")

    def test_t4_s04_02_console_mod_verify_host_and_logbus_pipeline(self) -> None:
        assert self.session.build_dir is not None and self.session.cache_dir is not None and self.session.run_dir is not None
        diag_sample = self.session.run_dir / "t4_diag.json"
        diag_sample.write_text(json.dumps({"audit_modules": ["simple_fog", "campaign_time"], "emit_debug": True}), encoding="utf-8")
        res = run_fuvtt_cli(
            ["verify-host", "sdk-log-console", "--sample", str(diag_sample)],
            build_dir=self.session.build_dir,
            cache_dir=self.session.cache_dir,
        )
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")

    def test_t4_s04_03_strict_skip_policy_prevents_disabled_world_pollution(self) -> None:
        d = self._data("t4_s04_skip")
        self.assertEqual(d["world"]["modules"]["entries"], {})
        for e in d.get("log_entries", []):
            assert_logbus_entry_schema(self, e)
        assert_r2_warning_present(self, d.get("log_entries", []), "simple_fog", policy="skip")
        assert_r2_warning_present(self, d.get("log_entries", []), "campaign_time", policy="skip")

    # --- Workflow 5: Large-World Scale, Drawing Text & Quota Guard Stress ---
    def test_t4_s05_01_large_world_300_entities_4_floors_scale(self) -> None:
        d = self._data("t4_s05_scale")
        self.assertGreaterEqual(int(d.get("entity_count", 0)), 301)
        self.assertEqual(int(d.get("floor_count", 0)), 4)

    def test_t4_s05_02_large_world_50_checklist_rows_and_quota_guard(self) -> None:
        d = self._data("t4_s05_scale")
        self.assertIn("drawing", d.get("module_keys", []))
        self.assertIn("checklist", d.get("module_keys", []))
        self.assertIs(d.get("can_fit_oversized"), False)

    def test_t4_s05_03_large_world_roundtrip_and_zero_leak_logs(self) -> None:
        d = self._data("t4_s05_scale")
        self.assertEqual(d.get("roundtrip_diff"), "")
        self.assertGreater(int(d.get("serialized_bytes", 0)), 0)
        self.assertLess(int(d.get("serialized_bytes", 0)), 32 * 1024 * 1024)

    # --- Workflow 6: Full End-to-End Synthetic Consumer Mod Lifecycle ---
    def test_t4_s06_01_synthetic_mod_init_and_author_multi_sdk_entry(self) -> None:
        iso_cfg = self.session.make_isolated_config()
        res = run_fuvtt_cli_isolated_mods(
            ["init", "campaign-importer-e2e", "--name", "Campaign E2E", "--ext", "json"],
            iso_cfg=iso_cfg,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        entry_gd = """extends RefCounted

const _SDK_PACKAGED_REL_PATH: String = "lib/fu_sdk/v1.gd"

func _load_sdk_script() -> Script:
\tvar self_script := get_script() as Script
\tvar base_dir: String = self_script.resource_path.split("::")[0].get_base_dir()
\treturn load(base_dir.path_join(_SDK_PACKAGED_REL_PATH)) as Script

func inspect_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:
\tvar sdk: RefCounted = _load_sdk_script().new()
\tvar session = sdk.create_session(host, options)
\treturn session.ok_inspect(path, {"records": 2}, {})

func prepare_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:
\tvar sdk: RefCounted = _load_sdk_script().new()
\tvar session = sdk.create_session(host, options)
\tvar logger = session.get_logger()
\tlogger.attach_import_host(host)
\tlogger.info("campaign_e2e", "Starting full lifecycle import", {"path": path})
\tvar builder = sdk.create_world_builder(session, 150.0)
\tbuilder.set_enabled_modules(["scene_box", "simple_fog", "grid_alignment"])
\tif builder.get_plugin_sdk("scene_box") == null:
\t\treturn session.err_failed("missing_scene_box_sdk")
\tbuilder.configure_entry_scene("Overworld", "1F", "")
\tbuilder.configure_grid_alignment(64.0)
\tvar tok_id: String = builder.add_token("pc_1", "Wizard", Vector2(100, 100), Vector2(64, 64), "")
\tbuilder.attach_unit_marker(tok_id)
\tbuilder.attach_simple_vision(tok_id, 480.0)
\tbuilder.finish_geometry_preview()
\treturn builder.build_result(2, 0)
"""
        write_utf8_no_bom_lf(iso_cfg.mods_dir / "campaign-importer-e2e" / "entry.gd", entry_gd)
        self.assertTrue((iso_cfg.mods_dir / "campaign-importer-e2e" / "entry.gd").is_file())

    def test_t4_s06_02_synthetic_mod_validate_build_and_verify_host(self) -> None:
        iso_cfg = self.session.make_isolated_config()
        if not (iso_cfg.mods_dir / "campaign-importer-e2e").is_dir():
            self.test_t4_s06_01_synthetic_mod_init_and_author_multi_sdk_entry()
        for cmd in (["validate", "campaign-importer-e2e"], ["build", "campaign-importer-e2e"], ["verify-host", "campaign-importer-e2e"]):
            res = run_fuvtt_cli_isolated_mods(cmd, iso_cfg=iso_cfg)
            self.assertEqual(res.returncode, 0, f"{cmd} failed:\n{res.stdout}\n{res.stderr}")

    def test_t4_s06_03_workspace_env_and_fus_repo_clean_audit(self) -> None:
        self.assertFalse((WORKSPACE_ROOT / "mods" / "campaign-importer-e2e").exists())
        assert_no_local_paths_in_text(self, (WORKSPACE_ROOT / "AGENTS.md").read_text(encoding="utf-8"), label="AGENTS.md")
        cfg = load_workspace_config()
        repo = cfg.resolve_fus_repo_dir()
        proc = run_git_readonly(["status", "-s"], repo_dir=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "", f"<FUS_REPO_DIR> dirty: {proc.stdout}")
