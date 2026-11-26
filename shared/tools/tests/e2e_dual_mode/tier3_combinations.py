"""Tier 3: Cross-Feature Combinatorial Integration Tests (16 cases: `t3_c01`..`t3_c16`)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest
import urllib.request
import zipfile

from .assertions import (
    EXPECTED_FU_RUNTIME_SCRIPTS,
    EXPECTED_SHARED_FU_SDK_SUBSET,
    assert_case_passed,
    assert_fu_sdk_35_invariance,
    assert_fup_archive_contract,
    assert_no_local_paths_in_text,
    assert_parity_clean,
    assert_registry_json_valid,
    assert_zip_archive_contract,
)
from .fixtures import (
    create_desktop_module_fixture,
    create_v1_session_plugin,
    create_world_plugin_fixture,
)
from .harness import (
    WORKSPACE_ROOT,
    CliRunner,
    E2ESession,
    FUSBuildParityRunner,
    GodotBatchProbe,
    ProbeCaseSpec,
    resolve_fus_repo_or_skip,
    resolve_godot_or_skip,
    write_utf8_no_bom_lf,
)


class Tier3CombinationTests(unittest.TestCase):
    """16 pairwise cross-feature and contract-parity tests (`t3_c01`..`t3_c16`)."""

    session: E2ESession
    cli: CliRunner

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = E2ESession(name_prefix="tier3")
        cls.session.setup(require_godot=False)
        cls.cli = CliRunner(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.session.cleanup()

    def _build_fup_and_extract(self, mod_name: str, pid: str) -> tuple[Path, GodotBatchProbe, Path]:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, mod_name, plugin_id=pid)
        res = self.cli.run_isolated(["build", mod_name])
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        fup_path = self.session.build_dir / mod_name / f"{mod_name}.fup"
        probe = GodotBatchProbe(self.session)
        pck_path = probe.extract_fup_pck(fup_path)
        return fup_path, probe, pck_path

    def test_t3_c01_desktop_module_overlays_mount_api_and_hooks(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "t3-c01-dm", plugin_id="t3_c01_dm")
        self.assertEqual(self.cli.run_isolated(["build", "t3-c01-dm"]).returncode, 0)
        zip_path = self.session.build_dir / "t3-c01-dm" / "t3-c01-dm.zip"

        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t3_c01",
                op="desktop_module_mount_run",
                pack_path=zip_path.resolve().as_posix(),
                params={
                    "entry_scene": "res://mods/t3_c01_dm/module.tscn",
                    "service_id": "t3_c01_dm.service",
                    "custom_hook": "mod.t3_c01_dm.burst",
                },
            )
        ])
        data = assert_case_passed(self, summary.results["t3_c01"])
        self.assertIs(data.get("pack_mounted"), True)
        self.assertIs(data.get("runtime_sdk_loaded"), True)
        self.assertIs(data.get("banner_mounted_before_unreg"), True)
        self.assertIs(data.get("banner_mounted_after_unreg"), False)
        self.assertEqual(data.get("above_overlay_count_after_unreg"), 0)
        self.assertIs(data.get("service_published"), True)
        self.assertIs(data.get("custom_emit_ok"), True)
        self.assertEqual(data.get("above_overlay_count"), 1)
        hooks_seen = [row.get("hook") for row in data.get("event_log", [])]
        self.assertIn("dice.rolled", hooks_seen)
        self.assertIn("vitals.downed", hooks_seen)
        self.assertIn("mod.t3_c01_dm.burst", hooks_seen)

    def test_t3_c02_hybrid_scope_desktop_module_local_only(self) -> None:
        godot_bin = resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_desktop_module_fixture(
            self.session.mods_dir,
            "t3-c02-hybrid",
            plugin_id="t3_c02_hybrid",
            scope="hybrid",
            local_only=True,
            network_version=0,
            hybrid_entry=True,
        )
        self.assertEqual(self.cli.run_isolated(["validate", "t3-c02-hybrid"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["build", "t3-c02-hybrid"]).returncode, 0)
        zip_path = self.session.build_dir / "t3-c02-hybrid" / "t3-c02-hybrid.zip"
        manifest = assert_zip_archive_contract(
            self,
            zip_path,
            expected_schema="fus.desktop-module.v1",
            plugin_id="t3_c02_hybrid",
            namespace_prefix="mods/t3_c02_hybrid",
        )
        self.assertEqual(manifest.get("scope"), "hybrid")
        self.assertIs(manifest["module"]["local_only"], True)
        self.assertEqual(manifest["module"]["network_version"], 0)
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = set(zf.namelist())
            self.assertIn("entry.gd", names)
            self.assertIn("lib/fu_sdk/v1.gd", names)
            self.assertFalse(any(n.lower().endswith(".pck") for n in names))
        vh = self.cli.run_isolated(["verify-host", "t3-c02-hybrid", "--godot-bin", str(godot_bin)], timeout=180)
        self.assertEqual(vh.returncode, 0, f"{vh.stdout}\n{vh.stderr}")

        # Also exercise CLI `--mode world-plugin --ext uvtt` end-to-end packaging (.fup) + default entry.gd execution
        self.assertEqual(
            self.cli.run_isolated(["init", "t3-c02-hyb-wp", "--mode", "world-plugin", "--ext", "uvtt"]).returncode,
            0,
        )
        self.assertEqual(self.cli.run_isolated(["validate", "t3-c02-hyb-wp"]).returncode, 0)
        self.assertEqual(
            self.cli.run_isolated(["build", "t3-c02-hyb-wp", "--godot-bin", str(godot_bin)], timeout=180).returncode,
            0,
        )
        fup_path = self.session.build_dir / "t3-c02-hyb-wp" / "t3-c02-hyb-wp.fup"
        fup_manifest, _fup_entries = assert_fup_archive_contract(
            self,
            fup_path,
            plugin_id="t3_c02_hyb_wp",
            pack_file="content.pck",
        )
        self.assertEqual(fup_manifest.get("scope"), "hybrid")
        self.assertEqual(fup_manifest.get("entry"), "entry.gd")
        with zipfile.ZipFile(fup_path, "r") as zf:
            fup_names = set(zf.namelist())
            self.assertIn("entry.gd", fup_names)
            self.assertIn("lib/fu_sdk/v1.gd", fup_names)
            self.assertIn("lib/fu_sdk/v1.gd", zf.read("SHA256SUMS.txt").decode("utf-8"))
        vh_wp = self.cli.run_isolated(["verify-host", "t3-c02-hyb-wp", "--godot-bin", str(godot_bin)], timeout=180)
        self.assertEqual(vh_wp.returncode, 0, f"{vh_wp.stdout}\n{vh_wp.stderr}")

    def test_t3_c03_three_overlay_bands_and_mount_node_cleanup(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t3_c03", op="overlay_and_mount_contract")])
        data = assert_case_passed(self, summary.results["t3_c03"])
        self.assertIs(data.get("slot_helper_used"), True)
        self.assertEqual(data.get("below_order"), ["OverlayLowPrio", "OverlayHighPrio"])
        self.assertEqual(data.get("above_count"), 1)
        self.assertEqual(data.get("fog_count"), 1)
        self.assertIs(data.get("mount_ok"), True)
        self.assertIs(data.get("mounted_found"), True)
        self.assertIs(data.get("after_revert_mounted_found"), False)
        self.assertEqual(data.get("after_revert_below_count"), 0)
        self.assertEqual(data.get("after_revert_above_count"), 0)
        self.assertEqual(data.get("after_revert_fog_count"), 0)

    def test_t3_c04_fup_comp_page_and_undo_redo_cycle(self) -> None:
        _, probe, pck = self._build_fup_and_extract("t3-c04-undo", "t3_c04_undo")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t3_c04",
                op="world_plugin_page_and_undo",
                pack_path=pck.resolve().as_posix(),
                params={
                    "page_scene": "res://external_modules/t3_c04_undo/comp_page.tscn",
                    "comp_path": "res://external_modules/t3_c04_undo/comp_t3_c04_undo__emitter.gd",
                },
            )
        ])
        data = assert_case_passed(self, summary.results["t3_c04"])
        self.assertIs(data.get("is_EntityComponentPage"), True)
        self.assertIs(data.get("activate_ok"), True)
        self.assertIs(data.get("configure_ok"), True)
        self.assertIs(data.get("bad_field_rejected"), True)
        self.assertIs(data.get("schema_version_mutation_rejected"), True)
        self.assertEqual(data.get("edit_signal_count"), 1)
        self.assertEqual(data.get("radius_after_edit"), 8)
        self.assertEqual(data.get("radius_after_undo"), 2)
        self.assertEqual(data.get("radius_after_redo"), 8)

    def test_t3_c05_dominance_suppression_and_public_state_masking(self) -> None:
        _, probe, pck = self._build_fup_and_extract("t3-c05-dom", "t3_c05_dom")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t3_c05",
                op="world_plugin_comp_and_disclosure",
                pack_path=pck.resolve().as_posix(),
                params={"comp_path": "res://external_modules/t3_c05_dom/comp_t3_c05_dom__emitter.gd"},
            )
        ])
        data = assert_case_passed(self, summary.results["t3_c05"])
        self.assertIs(data.get("added_ok"), True)
        self.assertIs(data.get("dom_added"), True)
        self.assertEqual(data.get("parked_after_dom"), 1)
        self.assertIs(data.get("suppressed_flag"), True)
        self.assertIs(data.get("blocked_while_suppressed"), True)
        self.assertIs(data.get("revived_ok"), True)
        self.assertEqual(data.get("public_gm", {}).get("radius_cells"), 6)
        self.assertEqual(data.get("public_peer2_unauth"), {})
        self.assertEqual(data.get("public_peer2_auth", {}).get("radius_cells"), 6)

    def test_t3_c06_world_module_state_3phase_roundtrip(self) -> None:
        _, probe, pck = self._build_fup_and_extract("t3-c06-st", "t3_c06_st")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t3_c06",
                op="world_module_state_3phase",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t3_c06_st/feature_t3_c06_st.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t3_c06"])
        self.assertIs(data.get("prep_empty_ok"), True)
        self.assertIs(data.get("prep_saved_ok"), True)
        self.assertIs(data.get("prep_bad_ok"), False)
        self.assertIs(data.get("apply_ok"), True)
        self.assertEqual(data.get("serialized"), {"version": 1, "cell_feet": 10, "show_labels": False})
        self.assertIs(data.get("roundtrip_equal"), True)
        self.assertIs(data.get("rejects_object"), True)
        self.assertIs(data.get("rejects_nan"), True)
        self.assertIs(data.get("rejects_deep"), True)

    def test_t3_c07_network_actions_projections_stage_publish_rollback(self) -> None:
        _, probe, pck = self._build_fup_and_extract("t3-c07-net", "t3_c07_net")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t3_c07",
                op="network_actions_projections",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t3_c07_net/feature_t3_c07_net.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t3_c07"])
        self.assertIs(data.get("action_id_matches_module"), True)
        self.assertIs(data.get("proj_id_matches_module"), True)
        self.assertEqual(data.get("revoked_unauth"), "permission_denied")
        self.assertEqual(data.get("revoked_auth"), "")
        self.assertIs(data.get("req_ok"), True)
        self.assertIs(data.get("bad_stage_rejected"), True)
        self.assertIs(data.get("non_owner_stage_rejected"), True)
        self.assertIs(data.get("non_owner_restore_rejected"), True)
        self.assertIs(data.get("unowned_sync_stage_rejected"), True)
        self.assertIs(data.get("unowned_sync_restore_rejected"), True)
        self.assertIs(data.get("other_owner_sync_stage_rejected"), True)
        self.assertIs(data.get("action_provider_valid"), True)
        self.assertIs(data.get("proj_provider_valid"), True)
        self.assertIs(data.get("good_stage_ok"), True)
        self.assertEqual(data.get("state_after_publish"), {"version": 1, "cell_feet": 15, "show_labels": False})
        self.assertIs(data.get("restored_ok"), True)
        self.assertEqual(data.get("state_after_restore"), {"version": 1, "cell_feet": 5, "show_labels": True})

    def test_t3_c08_all_4_ui_slots_coexist_cleanly(self) -> None:
        _, probe, pck = self._build_fup_and_extract("t3-c08-ui", "t3_c08_ui")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t3_c08",
                op="ui_slots_contract",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t3_c08_ui/feature_t3_c08_ui.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t3_c08"])
        self.assertEqual(data.get("panels_count"), 1)
        self.assertEqual(data.get("settings_count"), 1)
        self.assertEqual(data.get("mode_bar_count"), 1)
        self.assertEqual(data.get("entity_actions_count"), 1)
        self.assertIs(data.get("mode_predicate_ok"), True)
        self.assertIs(data.get("mode_on_enter_is_true"), True)
        self.assertIs(data.get("mode_active_after_enter"), True)
        self.assertIs(data.get("mode_active_after_exit"), False)
        self.assertIs(data.get("action_pred_empty"), False)
        self.assertIs(data.get("action_pred_non_empty"), True)
        self.assertIs(data.get("action_pres_enabled"), True)
        self.assertIs(data.get("action_exec_ok"), True)
        self.assertEqual(data.get("rejected_items"), [])

    def test_t3_c09_fu_runtime_and_fu_sdk_bundling_isolation(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "t3-c09-dm", plugin_id="t3_c09_dm")
        create_world_plugin_fixture(self.session.mods_dir, "t3-c09-wp", plugin_id="t3_c09_wp")
        self.assertEqual(self.cli.run_isolated(["build", "t3-c09-dm"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["build", "t3-c09-wp"]).returncode, 0)

        assert_zip_archive_contract(
            self,
            self.session.build_dir / "t3-c09-dm" / "t3-c09-dm.zip",
            expected_schema="fus.desktop-module.v1",
            plugin_id="t3_c09_dm",
            expect_sdk=True,
            namespace_prefix="mods/t3_c09_dm",
        )
        expected_sdk_paths = [
            *(f"res://external_modules/t3_c09_wp/lib/fu_runtime/{rel}" for rel in EXPECTED_FU_RUNTIME_SCRIPTS),
            *(f"res://external_modules/t3_c09_wp/lib/fu_sdk/{rel}" for rel in EXPECTED_SHARED_FU_SDK_SUBSET),
        ]
        wp_fup = self.session.build_dir / "t3-c09-wp" / "t3-c09-wp.fup"
        _, wp_entries = assert_fup_archive_contract(
            self,
            wp_fup,
            plugin_id="t3_c09_wp",
            expected_res_paths=expected_sdk_paths,
        )
        entry_paths = {str(e["res_path"]).removeprefix("res://") for e in wp_entries}
        self.assertNotIn("external_modules/t3_c09_wp/lib/fu_sdk/v1.gd", entry_paths)
        self.assertNotIn("external_modules/t3_c09_wp/lib/fu_sdk/plugins/areas.gd", entry_paths)

        probe = GodotBatchProbe(self.session)
        pck_path = probe.extract_fup_pck(wp_fup)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t3_c09",
                op="mount_and_compile_only",
                pack_path=pck_path.resolve().as_posix(),
                params={"check_paths": ["res://external_modules/t3_c09_wp/lib/fu_runtime/v2.gd"]},
            )
        ])
        compile_data = assert_case_passed(self, summary.results["t3_c09"])
        self.assertEqual(compile_data.get("loaded_count"), 1)
        assert_fu_sdk_35_invariance(self, WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk")

    def test_t3_c10_tri_schema_validate_build_sync_serve_all(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.build_dir is not None
        iso_mods = self.session.run_dir / "c10_mods"  # type: ignore[operator]
        iso_mods.mkdir(parents=True, exist_ok=True)
        create_v1_session_plugin(iso_mods, "c10-v1", plugin_id="c10_v1")
        create_desktop_module_fixture(iso_mods, "c10-dm", plugin_id="c10_dm")
        create_world_plugin_fixture(iso_mods, "c10-wp", plugin_id="c10_wp")

        self.assertEqual(self.cli.run_isolated(["validate", "--all"], mods_dir=iso_mods).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["build", "--all"], mods_dir=iso_mods).returncode, 0)
        target_dir = self.session.target_plugins_dir / "c10"  # type: ignore[operator]
        self.assertEqual(self.cli.run_isolated(["sync", "--all", "--target-dir", str(target_dir)], mods_dir=iso_mods).returncode, 0)
        assert_registry_json_valid(self, target_dir / "registry.json", ("c10_v1", "c10_dm", "c10_wp"))
        packages_dir = target_dir / "packages"
        self.assertTrue(packages_dir.is_dir())
        for pid in ("c10_v1", "c10_dm", "c10_wp"):
            self.assertTrue(any((packages_dir / p.name).is_dir() for p in packages_dir.iterdir() if pid in p.name))

        expected_meta = {
            "c10-v1": ("fus.session-plugin.v1", "zip", ".zip"),
            "c10-dm": ("fus.desktop-module.v1", "zip", ".zip"),
            "c10-wp": ("fus.plugin.v2", "fup", ".fup"),
        }
        with self.cli.isolated_serve(mods_dir=iso_mods) as (port, opener):
            with opener.open(f"http://127.0.0.1:{port}/index.json", timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                catalog = json.loads(resp.read().decode("utf-8"))
            by_mod = {row["mod_name"]: row for row in catalog.get("packages", [])}
            for mod_name, (exp_schema, exp_fmt, exp_ext) in expected_meta.items():
                self.assertIn(mod_name, by_mod)
                row = by_mod[mod_name]
                self.assertEqual(row.get("schema"), exp_schema)
                self.assertEqual(row.get("format"), exp_fmt)
                built_file = self.session.build_dir / mod_name / f"{mod_name}{exp_ext}"
                expected_sha = hashlib.sha256(built_file.read_bytes()).hexdigest()
                self.assertEqual(row.get("sha256"), expected_sha)
                with opener.open(row["url"], timeout=10) as dl:
                    self.assertEqual(dl.status, 200)
                    body = dl.read()
                self.assertEqual(hashlib.sha256(body).hexdigest(), expected_sha)

    def test_t3_c11_v1_and_v2_settings_reconciliation_across_upgrades(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.target_plugins_dir is not None
        v1_dir = create_v1_session_plugin(self.session.mods_dir, "t3-c11-v1", plugin_id="t3_c11_v1", version="1.0.0")
        v2_dir = create_world_plugin_fixture(self.session.mods_dir, "t3-c11-upg", plugin_id="t3_c11_upg", version="1.0.0")
        target_dir = self.session.target_plugins_dir / "c11"
        self.assertEqual(self.cli.run_isolated(["build", "t3-c11-v1"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["build", "t3-c11-upg"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["sync", "t3-c11-v1", "--target-dir", str(target_dir)]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["sync", "t3-c11-upg", "--target-dir", str(target_dir)]).returncode, 0)

        reg_path = target_dir / "registry.json"
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        reg["plugins"]["t3_c11_v1"]["settings"]["proxy"] = "http://127.0.0.1:7890"
        reg["plugins"]["t3_c11_upg"]["settings"]["cell_feet"] = "10"
        reg_path.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")

        m_v1 = json.loads((v1_dir / "plugin.json").read_text(encoding="utf-8"))
        m_v1["version"] = "1.1.0"
        m_v1["settings"].append({"id": "new_v1_opt", "type": "bool", "label": "New V1 Opt", "default": True})
        (v1_dir / "plugin.json").write_text(json.dumps(m_v1, indent=2) + "\n", encoding="utf-8")

        m_v2 = json.loads((v2_dir / "plugin.json").read_text(encoding="utf-8"))
        m_v2["version"] = "1.1.0"
        m_v2["settings"].append({"id": "new_opt", "type": "bool", "label": "New Opt", "default": True})
        (v2_dir / "plugin.json").write_text(json.dumps(m_v2, indent=2) + "\n", encoding="utf-8")

        self.assertEqual(self.cli.run_isolated(["build", "t3-c11-v1"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["build", "t3-c11-upg"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["sync", "t3-c11-v1", "--target-dir", str(target_dir)]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["sync", "t3-c11-upg", "--target-dir", str(target_dir)]).returncode, 0)

        reg_after = json.loads(reg_path.read_text(encoding="utf-8"))
        v1_settings = reg_after["plugins"]["t3_c11_v1"]["settings"]
        self.assertEqual(reg_after["plugins"]["t3_c11_v1"]["manifest"].get("version"), "1.1.0")
        self.assertEqual(v1_settings.get("proxy"), "http://127.0.0.1:7890")
        self.assertIs(v1_settings.get("new_v1_opt"), True)

        v2_settings = reg_after["plugins"]["t3_c11_upg"]["settings"]
        self.assertEqual(reg_after["plugins"]["t3_c11_upg"]["manifest"].get("version"), "1.1.0")
        self.assertEqual(v2_settings.get("cell_feet"), "10")
        self.assertIs(v2_settings.get("new_opt"), True)

    def test_t3_c12_mode_bar_hook_bus_and_set_mode_integration(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t3_c12", op="mode_bar_hook_bus_integration")])
        data = assert_case_passed(self, summary.results["t3_c12"])
        self.assertIs(data.get("mode_reg_ok"), True)
        self.assertEqual(data.get("mode_bar_count"), 1)
        self.assertIs(data.get("pre_hook_sub_ok"), True)
        self.assertIs(data.get("changed_hook_sub_ok"), True)
        self.assertIs(data.get("blocked_mode_result"), False)
        self.assertEqual(data.get("mode_after_blocked"), "select")
        self.assertEqual(data.get("changed_count_after_blocked"), 0)
        self.assertIs(data.get("enter_mode_result"), True)
        self.assertEqual(data.get("mode_after_enter"), "mod_t3_c12.inspect")
        self.assertIs(data.get("exit_mode_result"), True)
        self.assertEqual(data.get("mode_after_exit"), "select")
        self.assertEqual(data.get("entered_modes"), ["MockDesktop"])
        self.assertEqual(data.get("exited_modes"), ["MockDesktop"])
        self.assertEqual(data.get("changed_log"), ["select->mod_t3_c12.inspect", "mod_t3_c12.inspect->select"])
        self.assertEqual(data.get("hooks_remaining_after_revert"), 0)
        self.assertIs(data.get("emit_after_revert_ok"), False)

    def test_t3_c13_pure_zip_non_namespace_file_ignored_and_binary_blocked(self) -> None:
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        mdir_ns = create_desktop_module_fixture(
            self.session.mods_dir,
            "t3-c13-ns",
            plugin_id="t3_c13_ns",
            include_extra_non_ns_file=True,
        )
        (mdir_ns / "mods" / "t3_c13_ns" / "module.gd.uid").write_text("uid://dummy\n", encoding="utf-8")
        self.assertEqual(self.cli.run_isolated(["validate", "t3-c13-ns"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["build", "t3-c13-ns"]).returncode, 0)
        zip_path = self.session.build_dir / "t3-c13-ns" / "t3-c13-ns.zip"
        assert_zip_archive_contract(
            self,
            zip_path,
            expected_schema="fus.desktop-module.v1",
            plugin_id="t3_c13_ns",
            namespace_prefix="mods/t3_c13_ns",
        )
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = set(zf.namelist())
            self.assertNotIn("README.md", names)
            self.assertFalse(any(n.lower().endswith(".uid") for n in names))
            self.assertIn("mods/t3_c13_ns/module.tscn", names)

        mdir_bad = create_desktop_module_fixture(self.session.mods_dir, "t3-c13-bin", plugin_id="t3_c13_bin")
        (mdir_bad / "mods" / "t3_c13_bin" / "native.dll").write_bytes(b"MZ")
        val_bad = self.cli.run_isolated(["validate", "t3-c13-bin"])
        self.assertNotEqual(val_bad.returncode, 0)
        self.assertIn("unsafe_plugin_binary", val_bad.stdout + "\n" + val_bad.stderr)
        bld_bad = self.cli.run_isolated(["build", "t3-c13-bin"])
        self.assertNotEqual(bld_bad.returncode, 0)
        self.assertIn("unsafe_plugin_binary", bld_bad.stdout + "\n" + bld_bad.stderr)

    def test_t3_c14_fup_pck_cli_vs_build_world_plugin_gd_parity(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None and self.session.run_dir is not None
        mod_dir = create_world_plugin_fixture(self.session.mods_dir, "t3-c14-par", plugin_id="t3_c14_par")
        self.assertEqual(self.cli.run_isolated(["build", "t3-c14-par"]).returncode, 0)
        cli_fup = self.session.build_dir / "t3-c14-par" / "t3-c14-par.fup"

        parity = FUSBuildParityRunner(self.session).run_build_world_plugin(mod_dir, self.session.run_dir / "c14_fus_out")
        parity_res = assert_parity_clean(self, parity)
        fus_fup = Path(str(parity_res["fup_path"]))

        _, cli_entries = assert_fup_archive_contract(self, cli_fup, plugin_id="t3_c14_par")
        _, fus_entries = assert_fup_archive_contract(self, fus_fup, plugin_id="t3_c14_par")
        fus_by_path = {str(e["res_path"]).removeprefix("res://"): e for e in fus_entries}
        cli_by_path = {str(e["res_path"]).removeprefix("res://"): e for e in cli_entries}
        fus_paths = set(fus_by_path)
        cli_paths = set(cli_by_path)
        self.assertTrue(fus_paths.issubset(cli_paths), f"CLI content.pck missing entries built by FUS: {fus_paths - cli_paths}")

        sdk_prefixes = (
            "external_modules/t3_c14_par/lib/fu_runtime/",
            "external_modules/t3_c14_par/lib/fu_sdk/",
        )
        extra_cli = cli_paths - fus_paths
        non_sdk_extras = [p for p in sorted(extra_cli) if not p.startswith(sdk_prefixes)]
        self.assertEqual(non_sdk_extras, [], f"Unexpected non-SDK extra entries in CLI content.pck: {non_sdk_extras}")
        self.assertTrue(any(p.startswith(sdk_prefixes[0]) for p in extra_cli))
        self.assertTrue(any(p.startswith(sdk_prefixes[1]) for p in extra_cli))

        for shared_path in sorted(fus_paths & cli_paths):
            self.assertEqual(cli_by_path[shared_path]["size"], fus_by_path[shared_path]["size"], f"Size mismatch on {shared_path}")
            self.assertEqual(cli_by_path[shared_path]["md5"], fus_by_path[shared_path]["md5"], f"MD5 mismatch on {shared_path}")

    def test_t3_c15_inspect_client_and_verify_host_redacted_outputs(self) -> None:
        godot_bin = resolve_godot_or_skip(self.session.cfg)
        fus_repo = resolve_fus_repo_or_skip(self.session.cfg)
        insp = self.cli.run_real(["inspect-client", "--source", "git", "--fus-repo", str(fus_repo), "--git-ref", "HEAD", "--json"])
        self.assertEqual(insp.returncode, 0, insp.stderr)
        assert_no_local_paths_in_text(
            self,
            (insp.raw_stdout or insp.stdout) + "\n" + (insp.raw_stderr or insp.stderr),
            label="inspect-client",
        )
        insp_payload = json.loads(insp.stdout)
        snapshot = insp_payload.get("snapshot")
        self.assertIsInstance(snapshot, dict)
        git_src = snapshot.get("git_source")
        self.assertIsInstance(git_src, dict)
        self.assertEqual(git_src.get("repo"), "<FUS_REPO_DIR>")
        self.assertIsInstance(git_src.get("watch_files"), dict)

        vh = self.cli.run_real(["verify-host", "_template", "--godot-bin", str(godot_bin)], timeout=180)
        self.assertEqual(vh.returncode, 0, vh.stderr)
        assert_no_local_paths_in_text(
            self,
            (vh.raw_stdout or vh.stdout) + "\n" + (vh.raw_stderr or vh.stderr),
            label="verify-host",
        )
        self.assertIn("scripts=36", vh.stdout)

    def test_t3_c16_read_saved_module_entry_gm_vs_non_gm_bridge(self) -> None:
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        v1_dir = create_v1_session_plugin(self.session.mods_dir, "t3-c16-v1", plugin_id="t3_c16_v1")
        entry_gd = """extends RefCounted

func _load_sdk() -> RefCounted:
\tvar self_scr := get_script() as Script
\tvar base_dir: String = self_scr.resource_path.split("::")[0].get_base_dir()
\tvar scr := load(base_dir.path_join("lib/fu_sdk/v1.gd")) as Script
\treturn scr.new() if scr != null else null

func inspect_import(_path: String, _options: Dictionary, _host: Variant) -> Dictionary:
\treturn {"ok": true, "counts": {"records": 1, "unsupported": 0}, "assets": {}}

func prepare_import(_path: String, _options: Dictionary, host: Variant) -> Dictionary:
\tvar sdk := _load_sdk()
\tif sdk == null:
\t\treturn {"ok": false, "reason": "sdk_missing"}
\tvar session = sdk.create_session(host, {})
\tvar builder = sdk.create_world_builder(session, 150.0)
\tvar init_res: Dictionary = builder.setup(session, 150.0)
\tif not bool(init_res.get("ok", false)):
\t\treturn init_res
\tbuilder.set_module_state("mod.t3_c16_bridge", 1, {"imported": true, "nested": {"count": 3}})
\tbuilder.finish_geometry_preview()
\treturn builder.build_result(1, 0)
"""
        write_utf8_no_bom_lf(v1_dir / "entry.gd", entry_gd)
        self.assertEqual(self.cli.run_isolated(["build", "t3-c16-v1"]).returncode, 0)
        zip_path = self.session.build_dir / "t3-c16-v1" / "t3-c16-v1.zip"

        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t3_c16_gm",
                op="v1_to_desktop_saved_entry_bridge",
                pack_path=zip_path.resolve().as_posix(),
                params={"entry_path": "res://entry.gd", "module_id": "mod.t3_c16_bridge", "non_gm": False},
            ),
            ProbeCaseSpec(
                case_id="t3_c16_player",
                op="v1_to_desktop_saved_entry_bridge",
                pack_path=zip_path.resolve().as_posix(),
                params={"entry_path": "res://entry.gd", "module_id": "mod.t3_c16_bridge", "non_gm": True},
            ),
        ])
        gm_data = assert_case_passed(self, summary.results["t3_c16_gm"])
        pl_data = assert_case_passed(self, summary.results["t3_c16_player"])
        self.assertIs(gm_data.get("prep_ok"), True)
        self.assertIs(gm_data.get("is_gm"), True)
        self.assertEqual(gm_data.get("saved_entry"), {"version": 1, "state": {"imported": True, "nested": {"count": 3}}})
        self.assertIs(gm_data.get("clone_isolated"), True)
        self.assertEqual(gm_data.get("unknown_entry"), {})
        self.assertEqual(gm_data.get("empty_id_entry"), {})

        self.assertIs(pl_data.get("prep_ok"), True)
        self.assertIs(pl_data.get("is_gm"), False)
        self.assertEqual(pl_data.get("network_role"), "client")
        self.assertIs(pl_data.get("vitals", {}).get("masked"), True)
        self.assertEqual(pl_data.get("saved_entry"), {})
        self.assertEqual(pl_data.get("unknown_entry"), {})
        self.assertEqual(pl_data.get("empty_id_entry"), {})
