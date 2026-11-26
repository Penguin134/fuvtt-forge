"""Tier 1: Per-Feature Functional Acceptance Tests (85 cases: 5 per feature across #1-#17)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
import zipfile

from .assertions import (
    EXPECTED_FU_SDK_35_FILES,
    EXPECTED_SHARED_FU_SDK_SUBSET,
    assert_case_passed,
    assert_fu_sdk_35_invariance,
    assert_fup_archive_contract,
    assert_gdscript_hygiene,
    assert_no_local_paths_in_text,
    assert_parity_clean,
    assert_registry_json_valid,
    assert_zip_archive_contract,
    lint_doc_cli_commands,
)
from .fixtures import (
    create_desktop_module_fixture,
    create_v1_session_plugin,
    create_world_plugin_fixture,
)
from .harness import (
    TOOLS_DIR,
    WORKSPACE_ROOT,
    CliRunner,
    E2ESession,
    FUSBuildParityRunner,
    GodotBatchProbe,
    ProbeCaseSpec,
    resolve_fus_repo_or_skip,
    resolve_godot_or_skip,
    resolve_wiki_dir,
    run_git_readonly,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Tier1FeatureTests(unittest.TestCase):
    """85 isolated happy-path feature tests (`t1_f01_01`..`t1_f17_05`)."""

    session: E2ESession
    cli: CliRunner

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = E2ESession(name_prefix="tier1")
        cls.session.setup(require_godot=False)
        cls.cli = CliRunner(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.session.cleanup()

    # =========================================================================
    # Feature #1: fus.session-plugin.v1 Backward Compatibility
    # =========================================================================
    def test_t1_f01_01_v1_validate_template_and_log_console(self) -> None:
        for mod_name in ("_template", "sdk-log-console"):
            res = self.cli.run_real(["validate", mod_name])
            self.assertEqual(res.returncode, 0, f"validate {mod_name} failed:\n{res.stdout}\n{res.stderr}")

    def test_t1_f01_02_v1_build_bundles_35_fu_sdk_scripts(self) -> None:
        res = self.cli.run_real(["build", "_template"])
        self.assertEqual(res.returncode, 0, res.stderr)
        assert self.session.build_dir is not None
        zip_path = self.session.build_dir / "_template" / "_template.zip"
        manifest = json.loads((self.session.build_dir / "_template" / "build-manifest.json").read_text(encoding="utf-8"))
        self.assertIs(manifest.get("sdk_bundled"), True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = set(zf.namelist())
            for rel in EXPECTED_FU_SDK_35_FILES:
                member = f"lib/fu_sdk/{rel}"
                self.assertIn(member, names, f"Missing {member} in v1 ZIP")
                src_sha = hashlib.sha256((WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk" / rel).read_bytes()).hexdigest()
                zip_sha = hashlib.sha256(zf.read(member)).hexdigest()
                self.assertEqual(zip_sha, src_sha, f"SHA mismatch for {member}")

    def test_t1_f01_03_v1_verify_host_passes(self) -> None:
        godot_bin = resolve_godot_or_skip(self.session.cfg)
        for mod_name in ("_template", "sdk-log-console"):
            res = self.cli.run_real(["verify-host", mod_name, "--godot-bin", str(godot_bin)], timeout=180)
            self.assertEqual(res.returncode, 0, f"verify-host {mod_name} failed:\n{res.stdout}\n{res.stderr}")

    def test_t1_f01_04_init_default_creates_v1_scaffold(self) -> None:
        res = self.cli.run_isolated(["init", "t1-v1-default", "--name", "T1 V1 Default", "--ext", "dd2vtt"])
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        assert self.session.mods_dir is not None
        manifest = json.loads((self.session.mods_dir / "t1-v1-default" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("schema"), "fus.session-plugin.v1")
        self.assertEqual(manifest.get("host_api"), 1)
        self.assertEqual(manifest.get("scope"), "session")
        val = self.cli.run_isolated(["validate", "t1-v1-default"])
        self.assertEqual(val.returncode, 0, val.stdout)

    def test_t1_f01_05_fu_sdk_35_scripts_intact(self) -> None:
        assert_fu_sdk_35_invariance(self, WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk")

    # =========================================================================
    # Feature #2: fus.session-plugin.v1 Archive Overview Deltas
    # =========================================================================
    def test_t1_f02_01_inspect_client_git_v0065(self) -> None:
        fus_repo = resolve_fus_repo_or_skip(self.session.cfg)
        res = self.cli.run_real(
            ["inspect-client", "--source", "git", "--fus-repo", str(fus_repo), "--git-ref", "HEAD", "--json"]
        )
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        payload = json.loads(res.stdout)
        snapshot = payload.get("snapshot", {})
        git_src = snapshot.get("git_source", {})
        self.assertTrue(bool(git_src), f"Missing snapshot.git_source payload: {payload.keys()}")
        self.assertTrue(bool(git_src.get("commit")), f"Missing commit in snapshot.git_source: {git_src}")
        self.assertTrue(bool(git_src.get("version")), f"Missing version in snapshot.git_source: {git_src}")

    def test_t1_f02_02_client_inspector_tracks_inworld_git_watch_files(self) -> None:
        fus_repo = resolve_fus_repo_or_skip(self.session.cfg)
        res = self.cli.run_real(
            ["inspect-client", "--source", "git", "--fus-repo", str(fus_repo), "--git-ref", "HEAD", "--json"]
        )
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        payload = json.loads(res.stdout)
        watch_files = payload.get("snapshot", {}).get("git_source", {}).get("watch_files", {})
        for rel in (
            "services/plugins/PluginPackageJob.cs",
            "services/plugins/session_plugins.gd",
            "scenes/extension/desktop_api_service.gd",
            "scenes/extension/hook_ids.gd",
            "scenes/desktop/modules/world_overlay_host.gd",
        ):
            self.assertIn(rel, watch_files, f"inspect-client git_source.watch_files missing {rel}")
            self.assertIs(watch_files[rel].get("exists"), True, f"{rel} not found at FUS HEAD")
            self.assertTrue(bool(watch_files[rel].get("sha256")), f"{rel} missing sha256")

    def test_t1_f02_03_client_inspector_tracks_inworld_pck_watch_files(self) -> None:
        from fuvtt_devtools.client_inspector import CONTRACT_WATCH_FILES, V065_CONTRACT_WATCH_FILES

        all_pck_watched = set(CONTRACT_WATCH_FILES) | set(V065_CONTRACT_WATCH_FILES)
        for gdc in (
            "scenes/extension/desktop_api_service.gdc",
            "scenes/extension/hook_ids.gdc",
            "scenes/desktop/modules/world_overlay_host.gdc",
        ):
            self.assertIn(gdc, all_pck_watched, f"client_inspector watch lists missing {gdc}")

    def test_t1_f02_04_v1_import_bridge_12_counts_verified(self) -> None:
        godot_bin = resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None
        create_v1_session_plugin(self.session.mods_dir, "t1-f02-v1-mod")
        res = self.cli.run_isolated(["verify-host", "t1-f02-v1-mod", "--godot-bin", str(godot_bin)], timeout=180)
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")

    def test_t1_f02_05_fus_plugin_package_job_overview_contract(self) -> None:
        fus_repo = resolve_fus_repo_or_skip(self.session.cfg)
        proc = run_git_readonly(["show", "HEAD:services/plugins/PluginPackageJob.cs"], repo_dir=fus_repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("fus.desktop-module.v1", proc.stdout)
        self.assertIn("fus.plugin.v2", proc.stdout)
        self.assertIn("EnsureMountPack", proc.stdout)

    # =========================================================================
    # Feature #3: Runtime SDK Reuse & Leaf Hygiene
    # =========================================================================
    def test_t1_f03_01_fu_runtime_gdscript_hygiene(self) -> None:
        rt_dir = WORKSPACE_ROOT / "shared" / "sdk" / "fu_runtime"
        gd_files = sorted(rt_dir.glob("*.gd"))
        self.assertGreaterEqual(len(gd_files), 6, "Expected >= 6 scripts in shared/sdk/fu_runtime/")
        for gd in gd_files:
            assert_gdscript_hygiene(self, gd, require_extends_refcounted=True, forbid_class_name=True, forbid_preload=True)

    def test_t1_f03_02_fu_runtime_loads_and_reuses_fu_sdk_from_source(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f03_02", op="fu_runtime_load_and_reuse")])
        data = assert_case_passed(self, summary.results["t1_f03_02"])
        self.assertTrue(data.get("utils_ok"))
        self.assertTrue(data.get("logger_ok"))
        self.assertTrue(data.get("registry_ok"))

    def test_t1_f03_03_packaged_module_resolves_lib_fu_runtime_and_fu_sdk(self) -> None:
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "t1-f03-pkg", plugin_id="t1_f03_pkg", use_fu_runtime=True)
        b_res = self.cli.run_isolated(["build", "t1-f03-pkg"])
        self.assertEqual(b_res.returncode, 0, f"{b_res.stdout}\n{b_res.stderr}")
        zip_path = self.session.build_dir / "t1-f03-pkg" / "t1-f03-pkg.zip"
        assert_zip_archive_contract(self, zip_path, expected_schema="fus.desktop-module.v1", plugin_id="t1_f03_pkg", expect_sdk=True, namespace_prefix="mods/t1_f03_pkg")

        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f03_03",
                op="desktop_module_mount_run",
                pack_path=zip_path.resolve().as_posix(),
                params={"entry_scene": "res://mods/t1_f03_pkg/module.tscn", "service_id": "t1_f03_pkg.service"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f03_03"])
        self.assertTrue(data.get("runtime_sdk_loaded"), "Mounted desktop module failed to instantiate lib/fu_runtime/v2.gd")

    def test_t1_f03_04_runtime_manifest_json_valid(self) -> None:
        rt_dir = WORKSPACE_ROOT / "shared" / "sdk" / "fu_runtime"
        sdk_dir = WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk"
        manifest = json.loads((rt_dir / "runtime_manifest.json").read_text(encoding="utf-8"))
        for rel in manifest.get("runtime_scripts", []):
            self.assertTrue((rt_dir / rel).is_file(), f"runtime_manifest missing runtime_script: {rel}")
        for rel in manifest.get("shared_fu_sdk_scripts", []):
            self.assertTrue((sdk_dir / rel).is_file(), f"runtime_manifest missing shared_fu_sdk_script: {rel}")
        for req in EXPECTED_SHARED_FU_SDK_SUBSET:
            self.assertIn(req, manifest.get("shared_fu_sdk_scripts", []))

    def test_t1_f03_05_fu_runtime_zero_object_leak(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f03_05", op="fu_runtime_leak_check")])
        data = assert_case_passed(self, summary.results["t1_f03_05"])
        self.assertEqual(float(data.get("delta", -1.0)), 0.0)

    # =========================================================================
    # Feature #4: fus.desktop-module.v1 Pure-ZIP Manifest & Module Entry
    # =========================================================================
    def test_t1_f04_01_desktop_module_validate_singular(self) -> None:
        assert self.session.mods_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "t1-f04-single", plugin_id="t1_f04_single")
        res = self.cli.run_isolated(["validate", "t1-f04-single"])
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")

    def test_t1_f04_02_desktop_module_plural_external_modules_no_settings(self) -> None:
        assert self.session.mods_dir is not None
        create_desktop_module_fixture(
            self.session.mods_dir,
            "t1-f04-plural",
            plugin_id="t1_f04_plural",
            ns_dir="external_modules",
            use_plural_modules=True,
            omit_settings=True,
        )
        res = self.cli.run_isolated(["validate", "t1-f04-plural"])
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")

    def test_t1_f04_03_desktop_module_build_deterministic_zip(self) -> None:
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "t1-f04-build", plugin_id="t1_f04_build")
        res = self.cli.run_isolated(["build", "t1-f04-build"])
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        zip_path = self.session.build_dir / "t1-f04-build" / "t1-f04-build.zip"
        assert_zip_archive_contract(self, zip_path, expected_schema="fus.desktop-module.v1", plugin_id="t1_f04_build", expect_sdk=True, namespace_prefix="mods/t1_f04_build")

    def test_t1_f04_04_desktop_module_build_no_sdk(self) -> None:
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "t1-f04-nosdk", plugin_id="t1_f04_nosdk", use_fu_runtime=False)
        res = self.cli.run_isolated(["build", "t1-f04-nosdk", "--no-sdk"])
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        zip_path = self.session.build_dir / "t1-f04-nosdk" / "t1-f04-nosdk.zip"
        assert_zip_archive_contract(self, zip_path, expected_schema="fus.desktop-module.v1", plugin_id="t1_f04_nosdk", expect_sdk=False, namespace_prefix="mods/t1_f04_nosdk")

    def test_t1_f04_05_desktop_module_build_world_plugin_parity(self) -> None:
        assert self.session.mods_dir is not None and self.session.run_dir is not None
        mod_dir = create_desktop_module_fixture(self.session.mods_dir, "t1-f04-parity", plugin_id="t1_f04_parity")
        parity = FUSBuildParityRunner(self.session).run_build_world_plugin(mod_dir, self.session.run_dir / "parity_zip_out")
        assert_parity_clean(self, parity, expected_mode="zip_direct")

    # =========================================================================
    # Feature #5: desktop_api Service Wrapper & Helpers
    # =========================================================================
    def test_t1_f05_01_desktop_api_identity_and_role(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f05_01", op="desktop_api_contract")])
        data = assert_case_passed(self, summary.results["t1_f05_01"])
        self.assertIs(data.get("is_gm"), True)
        self.assertEqual(data.get("network_role"), "host")
        self.assertEqual(data.get("local_peer_id"), 1)
        self.assertEqual(data.get("local_player_id"), "host")
        self.assertEqual(len(data.get("joined_players", [])), 2)

    def test_t1_f05_02_desktop_api_scene_floor_grid(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f05_02", op="desktop_api_contract")])
        data = assert_case_passed(self, summary.results["t1_f05_02"])
        self.assertEqual(data.get("active_scene_uid"), "scene_main_uid")
        self.assertEqual(data.get("active_scene_name"), "Main Tavern")
        self.assertEqual(data.get("active_floor_uid"), "floor_1f_uid")
        self.assertEqual(data.get("active_floor_id"), 0)
        self.assertAlmostEqual(float(data.get("world_units_per_cell", 0.0)), 64.0)

    def test_t1_f05_03_desktop_api_camera_and_mode(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f05_03", op="desktop_api_contract")])
        data = assert_case_passed(self, summary.results["t1_f05_03"])
        self.assertIs(data.get("focus_ok"), True)
        self.assertEqual(data.get("cam_pos"), (128.0, 256.0))
        self.assertEqual(data.get("cam_zoom"), (1.0, 1.0))
        self.assertEqual(data.get("current_mode"), "select")

    def test_t1_f05_04_desktop_api_entities_and_gm_vitals(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f05_04", op="desktop_api_contract")])
        data = assert_case_passed(self, summary.results["t1_f05_04"])
        self.assertIs(data.get("found_entity"), True)
        self.assertEqual(data.get("entity_count"), 1)
        self.assertEqual(data.get("selected_count"), 1)
        self.assertIs(data.get("can_command_self"), True)
        self.assertIs(data.get("can_command_by_id"), True)
        self.assertIs(data.get("can_command_peer2"), False)
        self.assertIs(data.get("can_command_unknown"), False)
        vitals = data.get("vitals", {})
        self.assertIs(vitals.get("masked"), False)
        self.assertEqual(vitals.get("source_kind"), "stat_bubble")
        self.assertEqual(vitals.get("hp_cur"), 18)
        self.assertNotIn("hp", vitals)

    def test_t1_f05_05_desktop_api_roll_and_saved_module_entry(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f05_05", op="desktop_api_contract")])
        data = assert_case_passed(self, summary.results["t1_f05_05"])
        self.assertIs(data.get("roll_res", {}).get("ok"), True)
        self.assertEqual(data.get("saved_entry", {}).get("version"), 1)

    # =========================================================================
    # Feature #6: HookBus & Namespaced Custom Hooks
    # =========================================================================
    def test_t1_f06_01_hook_helper_builtin_and_custom_constants(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f06_01", op="hook_bus_contract")])
        data = assert_case_passed(self, summary.results["t1_f06_01"])
        self.assertIs(data.get("r_lo_ok"), True)
        self.assertIs(data.get("r_custom_ok"), True)

    def test_t1_f06_02_hook_priority_ordering(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f06_02", op="hook_bus_contract")])
        data = assert_case_passed(self, summary.results["t1_f06_02"])
        order = data.get("order", [])
        self.assertEqual(order[:2], ["hi:n20", "lo:n20"])

    def test_t1_f06_03_custom_namespaced_hook_emit_and_receive(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f06_03", op="hook_bus_contract")])
        data = assert_case_passed(self, summary.results["t1_f06_03"])
        self.assertIs(data.get("emitted_custom"), True)
        self.assertIn("custom:ok", data.get("order", []))

    def test_t1_f06_04_hook_auto_unsubscribe_on_revert(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f06_04", op="hook_bus_contract")])
        data = assert_case_passed(self, summary.results["t1_f06_04"])
        self.assertIs(data.get("emitted_after_revert"), False)

    def test_t1_f06_05_custom_hook_id_validation(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f06_05", op="hook_bus_contract")])
        data = assert_case_passed(self, summary.results["t1_f06_05"])
        self.assertIs(data.get("valid_mod_hook"), True)
        self.assertIs(data.get("valid_ext_hook"), True)
        self.assertIs(data.get("invalid_upper_hook"), False)
        self.assertIs(data.get("invalid_two_seg"), False)

    # =========================================================================
    # Feature #7: world.overlays & ExtensionContext.mount_node
    # =========================================================================
    def test_t1_f07_01_world_overlays_below_entities_band(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f07_01", op="overlay_and_mount_contract")])
        data = assert_case_passed(self, summary.results["t1_f07_01"])
        self.assertIs(data.get("slot_helper_used"), True)
        self.assertEqual(len(data.get("below_order", [])), 2)

    def test_t1_f07_02_world_overlays_above_entities_and_above_fog_bands(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f07_02", op="overlay_and_mount_contract")])
        data = assert_case_passed(self, summary.results["t1_f07_02"])
        self.assertIs(data.get("slot_helper_used"), True)
        self.assertEqual(data.get("above_count"), 1)
        self.assertEqual(data.get("fog_count"), 1)

    def test_t1_f07_03_world_overlays_ascending_priority_order(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f07_03", op="overlay_and_mount_contract")])
        data = assert_case_passed(self, summary.results["t1_f07_03"])
        self.assertIs(data.get("slot_helper_used"), True)
        self.assertEqual(data.get("below_order"), ["OverlayLowPrio", "OverlayHighPrio"])

    def test_t1_f07_04_context_mount_node_attaches_under_desktop(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f07_04", op="overlay_and_mount_contract")])
        data = assert_case_passed(self, summary.results["t1_f07_04"])
        self.assertIs(data.get("slot_helper_used"), True)
        self.assertIs(data.get("mount_ok"), True)
        self.assertIs(data.get("mounted_found"), True)

    def test_t1_f07_05_revert_unmounts_and_frees_all_nodes(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f07_05", op="overlay_and_mount_contract")])
        data = assert_case_passed(self, summary.results["t1_f07_05"])
        self.assertIs(data.get("slot_helper_used"), True)
        self.assertIs(data.get("after_revert_mounted_found"), False)
        self.assertEqual(data.get("after_revert_below_count"), 0)

    # =========================================================================
    # Feature #8: local_only Network Isolation & Enforcement
    # =========================================================================
    def test_t1_f08_01_validator_accepts_local_only_net0_desktop_module(self) -> None:
        assert self.session.mods_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "t1-f08-local", plugin_id="t1_f08_local", local_only=True, network_version=0)
        res = self.cli.run_isolated(["validate", "t1-f08-local"])
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_t1_f08_02_fus_supported_versions_skips_net0(self) -> None:
        fus_repo = resolve_fus_repo_or_skip(self.session.cfg)
        proc = run_git_readonly(["show", "HEAD:scenes/board/networking/network_module_contract.gd"], repo_dir=fus_repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("local_only", proc.stdout)
        self.assertIn("protocol is int and protocol > 0", proc.stdout)

    def test_t1_f08_03_fus_campaign_supported_allows_local_only(self) -> None:
        fus_repo = resolve_fus_repo_or_skip(self.session.cfg)
        proc = run_git_readonly(["show", "HEAD:scenes/board/networking/network_module_contract.gd"], repo_dir=fus_repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("campaign_supported", proc.stdout)

    def test_t1_f08_04_fus_replica_manifest_excludes_local_only(self) -> None:
        fus_repo = resolve_fus_repo_or_skip(self.session.cfg)
        proc = run_git_readonly(["show", "HEAD:scenes/extension/module_replica_lifecycle.gd"], repo_dir=fus_repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("local_only", proc.stdout)

    def test_t1_f08_05_runtime_network_helper_enforces_local_only_guard(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f08_05", op="fu_runtime_network_local_only_guard")])
        data = assert_case_passed(self, summary.results["t1_f08_05"])
        self.assertIs(data.get("is_local_only"), True)
        self.assertIs(data.get("local_actions_ok"), False)
        self.assertEqual(data.get("local_actions_reason"), "local_only_network_disabled")
        self.assertIs(data.get("local_projs_ok"), False)
        self.assertEqual(data.get("local_projs_reason"), "local_only_network_disabled")
        self.assertIs(data.get("local_reg_ok"), False)
        self.assertIs(data.get("net_actions_ok"), True)
        self.assertEqual(data.get("net_actions_id"), "t1_f08.core")
        self.assertIs(data.get("net_projs_ok"), True)
        self.assertIs(data.get("net_projs_replica_only"), True)

    # =========================================================================
    # Feature #9: fus.plugin.v2 .fup + content.pck Packaging
    # =========================================================================
    def test_t1_f09_01_v2_validate_accepts_world_plugin(self) -> None:
        assert self.session.mods_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t1-f09-val", plugin_id="t1_f09_val")
        res = self.cli.run_isolated(["validate", "t1-f09-val"])
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")

    def test_t1_f09_02_v2_build_emits_fup_pck_and_sha256sums(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t1-f09-bld", plugin_id="t1_f09_bld")
        res = self.cli.run_isolated(["build", "t1-f09-bld"])
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        fup_path = self.session.build_dir / "t1-f09-bld" / "t1-f09-bld.fup"
        manifest, entries = assert_fup_archive_contract(
            self,
            fup_path,
            plugin_id="t1_f09_bld",
            expected_res_paths=(
                "res://external_modules/t1_f09_bld/feature_t1_f09_bld.tscn",
                "res://external_modules/t1_f09_bld/lib/fu_runtime/v2.gd",
            ),
        )
        self.assertEqual(manifest.get("pack_file"), "content.pck")
        self.assertGreater(len(entries), 0)

    def test_t1_f09_03_v2_sha256sums_verified_against_bytes(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t1-f09-sums", plugin_id="t1_f09_sums")
        res = self.cli.run_isolated(["build", "t1-f09-sums"])
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        fup_path = self.session.build_dir / "t1-f09-sums" / "t1-f09-sums.fup"
        assert_fup_archive_contract(self, fup_path, plugin_id="t1_f09_sums")

    def test_t1_f09_04_v2_content_pck_mounts_in_godot(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t1-f09-mnt", plugin_id="t1_f09_mnt")
        res = self.cli.run_isolated(["build", "t1-f09-mnt"])
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        fup_path = self.session.build_dir / "t1-f09-mnt" / "t1-f09-mnt.fup"

        probe = GodotBatchProbe(self.session)
        pck_path = probe.extract_fup_pck(fup_path)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f09_04",
                op="mount_and_compile_only",
                pack_path=pck_path.resolve().as_posix(),
                params={
                    "check_paths": [
                        "res://external_modules/t1_f09_mnt/feature_t1_f09_mnt.tscn",
                        "res://external_modules/t1_f09_mnt/comp_t1_f09_mnt__emitter.gd",
                        "res://external_modules/t1_f09_mnt/lib/fu_runtime/v2.gd",
                    ]
                },
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f09_04"])
        self.assertEqual(data.get("loaded_count"), 3)

    def test_t1_f09_05_v2_pck_less_fallback_and_parity(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None and self.session.run_dir is not None
        mod_dir = create_world_plugin_fixture(self.session.mods_dir, "t1-f09-par", plugin_id="t1_f09_par", pack_file="")
        self.assertEqual(self.cli.run_isolated(["validate", "t1-f09-par"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["build", "t1-f09-par"]).returncode, 0)
        zip_path = self.session.build_dir / "t1-f09-par" / "t1-f09-par.zip"
        assert_zip_archive_contract(
            self,
            zip_path,
            expected_schema="fus.plugin.v2",
            plugin_id="t1_f09_par",
            expect_sdk=True,
            namespace_prefix="external_modules/t1_f09_par",
        )
        with zipfile.ZipFile(zip_path, "r") as zf:
            self.assertFalse(any(n.lower().endswith(".pck") for n in zf.namelist()), "PCK-less v2 ZIP must not contain .pck")

        parity = FUSBuildParityRunner(self.session).run_build_world_plugin(mod_dir, self.session.run_dir / "parity_zip_v2_out")
        assert_parity_clean(self, parity, expected_mode="zip_direct")

        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f09_05",
                op="mount_and_compile_only",
                pack_path=zip_path.resolve().as_posix(),
                params={
                    "check_paths": [
                        "res://external_modules/t1_f09_par/feature_t1_f09_par.tscn",
                        "res://external_modules/t1_f09_par/lib/fu_runtime/v2.gd",
                    ]
                },
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f09_05"])
        self.assertEqual(data.get("loaded_count"), 2)

    # =========================================================================
    # Feature #10: CompBase & Component Disclosure (public_state)
    # =========================================================================
    def _build_and_extract_v2(self, mod_name: str, pid: str) -> tuple[GodotBatchProbe, Path]:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, mod_name, plugin_id=pid)
        res = self.cli.run_isolated(["build", mod_name])
        self.assertEqual(res.returncode, 0, f"{res.stdout}\n{res.stderr}")
        fup_path = self.session.build_dir / mod_name / f"{mod_name}.fup"
        probe = GodotBatchProbe(self.session)
        pck_path = probe.extract_fup_pck(fup_path)
        return probe, pck_path

    def test_t1_f10_01_comp_base_naming_and_id_from_path(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f10-comp", "t1_f10_comp")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f10_01",
                op="world_plugin_comp_and_disclosure",
                pack_path=pck.resolve().as_posix(),
                params={"comp_path": "res://external_modules/t1_f10_comp/comp_t1_f10_comp__emitter.gd"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f10_01"])
        self.assertEqual(data.get("id_from_path"), "t1_f10_comp__emitter")

    def test_t1_f10_02_comp_helper_spec_builder(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f10_02", op="fu_runtime_comp_helper_contract")])
        data = assert_case_passed(self, summary.results["t1_f10_02"])
        self.assertEqual(data.get("namespaced_comp_id"), "t1_f10__emitter")
        self.assertIs(data.get("spec_ok"), True)
        self.assertEqual(data.get("spec_field_count"), 15)
        self.assertEqual(data.get("spec_id"), "t1_f10__emitter")
        self.assertIs(data.get("reserved_rejected"), True)
        self.assertIs(data.get("peer_scope_rejected"), True)
        self.assertIs(data.get("register_ok"), True)
        self.assertIs(data.get("pub_unauth_masked"), True)
        self.assertEqual(data.get("pub_gm_radius"), 6)

    def test_t1_f10_03_public_state_masks_dm_secret_for_unauth_peer(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f10-pub", "t1_f10_pub")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f10_03",
                op="world_plugin_comp_and_disclosure",
                pack_path=pck.resolve().as_posix(),
                params={"comp_path": "res://external_modules/t1_f10_pub/comp_t1_f10_pub__emitter.gd"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f10_03"])
        self.assertIs(data.get("has_public_state"), True)
        self.assertEqual(data.get("public_gm", {}).get("radius_cells"), 6)
        self.assertEqual(data.get("public_peer2_unauth"), {})
        self.assertEqual(data.get("public_peer2_auth", {}).get("radius_cells"), 6)

    def test_t1_f10_04_component_tags_declared(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f10-tags", "t1_f10_tags")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f10_04",
                op="world_plugin_comp_and_disclosure",
                pack_path=pck.resolve().as_posix(),
                params={"comp_path": "res://external_modules/t1_f10_tags/comp_t1_f10_tags__emitter.gd"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f10_04"])
        self.assertIn("aura", data.get("tags", []))

    def test_t1_f10_05_dominant_suppression_parks_and_revives(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f10-dom", "t1_f10_dom")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f10_05",
                op="world_plugin_comp_and_disclosure",
                pack_path=pck.resolve().as_posix(),
                params={"comp_path": "res://external_modules/t1_f10_dom/comp_t1_f10_dom__emitter.gd"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f10_05"])
        self.assertIs(data.get("dom_added"), True)
        self.assertEqual(data.get("parked_after_dom"), 1)
        self.assertIs(data.get("suppressed_flag"), True)
        self.assertIs(data.get("blocked_while_suppressed"), True)
        self.assertIs(data.get("revived_ok"), True)

    # =========================================================================
    # Feature #11: EntityComponentPage & EditModeController Undo
    # =========================================================================
    def test_t1_f11_01_page_extends_entity_component_page(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f11-pg", "t1_f11_pg")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f11_01",
                op="world_plugin_page_and_undo",
                pack_path=pck.resolve().as_posix(),
                params={
                    "page_scene": "res://external_modules/t1_f11_pg/comp_page.tscn",
                    "comp_path": "res://external_modules/t1_f11_pg/comp_t1_f11_pg__emitter.gd",
                },
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f11_01"])
        self.assertIs(data.get("is_EntityComponentPage"), True)

    def test_t1_f11_02_page_bind_entities_and_activate(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f11-bind", "t1_f11_bind")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f11_02",
                op="world_plugin_page_and_undo",
                pack_path=pck.resolve().as_posix(),
                params={
                    "page_scene": "res://external_modules/t1_f11_bind/comp_page.tscn",
                    "comp_path": "res://external_modules/t1_f11_bind/comp_t1_f11_bind__emitter.gd",
                },
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f11_02"])
        self.assertIs(data.get("activate_ok"), True)

    def test_t1_f11_03_page_emits_edit_requested_signal(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f11-sig", "t1_f11_sig")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f11_03",
                op="world_plugin_page_and_undo",
                pack_path=pck.resolve().as_posix(),
                params={
                    "page_scene": "res://external_modules/t1_f11_sig/comp_page.tscn",
                    "comp_path": "res://external_modules/t1_f11_sig/comp_t1_f11_sig__emitter.gd",
                },
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f11_03"])
        self.assertEqual(data.get("edit_signal_count"), 1)

    def test_t1_f11_04_comp_helper_edit_payload_helpers(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f11_04", op="fu_runtime_comp_edit_payloads")])
        data = assert_case_passed(self, summary.results["t1_f11_04"])
        self.assertIs(data.get("field_ok"), True)
        self.assertIs(data.get("num_begin_ok"), True)
        self.assertIs(data.get("num_end_ok"), True)

    def test_t1_f11_05_configure_components_undo_and_redo(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f11-undo", "t1_f11_undo")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f11_05",
                op="world_plugin_page_and_undo",
                pack_path=pck.resolve().as_posix(),
                params={
                    "page_scene": "res://external_modules/t1_f11_undo/comp_page.tscn",
                    "comp_path": "res://external_modules/t1_f11_undo/comp_t1_f11_undo__emitter.gd",
                },
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f11_05"])
        self.assertIs(data.get("configure_ok"), True)
        self.assertEqual(data.get("radius_after_edit"), 8)
        self.assertEqual(data.get("radius_after_undo"), 2)
        self.assertEqual(data.get("radius_after_redo"), 8)

    # =========================================================================
    # Feature #12: WorldModuleState 3-Phase Persistence
    # =========================================================================
    def test_t1_f12_01_prepare_module_state_empty_defaults(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f12-emp", "t1_f12_emp")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f12_01",
                op="world_module_state_3phase",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f12_emp/feature_t1_f12_emp.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f12_01"])
        self.assertIs(data.get("prep_empty_ok"), True)

    def test_t1_f12_02_prepare_module_state_saved_data(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f12-sav", "t1_f12_sav")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f12_02",
                op="world_module_state_3phase",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f12_sav/feature_t1_f12_sav.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f12_02"])
        self.assertIs(data.get("prep_saved_ok"), True)

    def test_t1_f12_03_apply_module_state_updates_runtime(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f12-app", "t1_f12_app")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f12_03",
                op="world_module_state_3phase",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f12_app/feature_t1_f12_app.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f12_03"])
        self.assertIs(data.get("apply_ok"), True)
        self.assertEqual(data.get("serialized", {}).get("cell_feet"), 10)

    def test_t1_f12_04_serialize_module_state_var_to_bytes_roundtrip(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f12-rt", "t1_f12_rt")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f12_04",
                op="world_module_state_3phase",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f12_rt/feature_t1_f12_rt.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f12_04"])
        self.assertIs(data.get("roundtrip_equal"), True)

    def test_t1_f12_05_fu_runtime_reuses_value_utils_for_state_check(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f12-val", "t1_f12_val")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f12_05",
                op="world_module_state_3phase",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f12_val/feature_t1_f12_val.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f12_05"])
        self.assertIs(data.get("rejects_object"), True)
        self.assertIs(data.get("rejects_nan"), True)

    # =========================================================================
    # Feature #13: network.actions & network.projections
    # =========================================================================
    def test_t1_f13_01_network_spec_id_equals_module_id(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f13-id", "t1_f13_id")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f13_01",
                op="network_actions_projections",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f13_id/feature_t1_f13_id.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f13_01"])
        self.assertIs(data.get("action_id_matches_module"), True)
        self.assertIs(data.get("proj_id_matches_module"), True)
        self.assertIs(data.get("network_helper_ok"), True)
        self.assertIs(data.get("action_provider_valid"), True)
        self.assertIs(data.get("proj_provider_valid"), True)

    def test_t1_f13_02_network_actions_3_methods(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f13-act", "t1_f13_act")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f13_02",
                op="network_actions_projections",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f13_act/feature_t1_f13_act.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f13_02"])
        self.assertEqual(data.get("revoked_auth"), "")
        self.assertIs(data.get("req_ok"), True)

    def test_t1_f13_03_network_projections_8_methods(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f13-prj", "t1_f13_prj")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f13_03",
                op="network_actions_projections",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f13_prj/feature_t1_f13_prj.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f13_03"])
        self.assertGreaterEqual(int(data.get("cursor_rev", 0)), 1)

    def test_t1_f13_04_replica_stage_and_publish(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f13-pub", "t1_f13_pub")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f13_04",
                op="network_actions_projections",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f13_pub/feature_t1_f13_pub.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f13_04"])
        self.assertIs(data.get("good_stage_ok"), True)

    def test_t1_f13_05_replica_restore_rollback(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f13-rst", "t1_f13_rst")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f13_05",
                op="network_actions_projections",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f13_rst/feature_t1_f13_rst.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f13_05"])
        self.assertIs(data.get("restored_ok"), True)

    # =========================================================================
    # Feature #14: UI Slots (desktop_panels, module_settings, mode_bar, entity_actions)
    # =========================================================================
    def test_t1_f14_01_ui_desktop_panels_slot(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f14-pan", "t1_f14_pan")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f14_01",
                op="ui_slots_contract",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f14_pan/feature_t1_f14_pan.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f14_01"])
        self.assertEqual(data.get("panels_count"), 1)

    def test_t1_f14_02_ui_module_settings_slot(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f14-set", "t1_f14_set")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f14_02",
                op="ui_slots_contract",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f14_set/feature_t1_f14_set.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f14_02"])
        self.assertEqual(data.get("settings_count"), 1)

    def test_t1_f14_03_ui_mode_bar_on_enter_returns_true(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f14-mod", "t1_f14_mod")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f14_03",
                op="ui_slots_contract",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f14_mod/feature_t1_f14_mod.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f14_03"])
        self.assertEqual(data.get("mode_bar_count"), 1)
        self.assertIs(data.get("mode_on_enter_is_true"), True)

    def test_t1_f14_04_ui_entity_actions_slot(self) -> None:
        probe, pck = self._build_and_extract_v2("t1-f14-act", "t1_f14_act")
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t1_f14_04",
                op="ui_slots_contract",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t1_f14_act/feature_t1_f14_act.tscn"},
            )
        ])
        data = assert_case_passed(self, summary.results["t1_f14_04"])
        self.assertEqual(data.get("entity_actions_count"), 1)
        self.assertEqual(data.get("rejected_items"), [])

    def test_t1_f14_05_slot_helper_supports_all_4_ui_slots(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t1_f14_05", op="fu_runtime_slot_helper_ui_4_slots")])
        data = assert_case_passed(self, summary.results["t1_f14_05"])
        self.assertIs(data.get("panel_reg_ok"), True)
        self.assertIs(data.get("settings_reg_ok"), True)
        self.assertIs(data.get("mode_reg_ok"), True)
        self.assertIs(data.get("action_reg_ok"), True)
        self.assertIs(data.get("bad_builtin_mode_rejected"), True)
        self.assertIs(data.get("bad_nodot_action_rejected"), True)
        self.assertEqual(data.get("panels_count"), 1)
        self.assertEqual(data.get("settings_count"), 1)
        self.assertEqual(data.get("mode_bar_count"), 1)
        self.assertEqual(data.get("entity_actions_count"), 1)

    # =========================================================================
    # Feature #15: CLI init, serve, sync, verify-host Dual-Mode
    # =========================================================================
    def test_t1_f15_01_cli_init_desktop_module_and_world_plugin(self) -> None:
        for mod_name, mode, expected_schema in (
            ("t1-init-dm", "desktop-module", "fus.desktop-module.v1"),
            ("t1-init-wp", "world-plugin", "fus.plugin.v2"),
        ):
            res = self.cli.run_isolated(["init", mod_name, "--mode", mode])
            self.assertEqual(res.returncode, 0, f"init --mode {mode} failed:\n{res.stdout}\n{res.stderr}")
            assert self.session.mods_dir is not None
            manifest = json.loads((self.session.mods_dir / mod_name / "plugin.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest.get("schema"), expected_schema)
            v = self.cli.run_isolated(["validate", mod_name])
            self.assertEqual(v.returncode, 0, f"validate after init --mode {mode} failed:\n{v.stdout}\n{v.stderr}")

    def test_t1_f15_02_cli_sync_zip_and_fup(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.target_plugins_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "t1-f15-dm", plugin_id="t1_f15_dm")
        create_world_plugin_fixture(self.session.mods_dir, "t1-f15-wp", plugin_id="t1_f15_wp")

        target_dir = self.session.target_plugins_dir / "f15_02"
        for mod_name in ("t1-f15-dm", "t1-f15-wp"):
            b = self.cli.run_isolated(["build", mod_name])
            self.assertEqual(b.returncode, 0, f"{b.stdout}\n{b.stderr}")
            s = self.cli.run_isolated(["sync", mod_name, "--target-dir", str(target_dir)])
            self.assertEqual(s.returncode, 0, f"sync {mod_name} failed:\n{s.stdout}\n{s.stderr}")

        reg = assert_registry_json_valid(self, target_dir / "registry.json", ("t1_f15_dm", "t1_f15_wp"))
        self.assertIn("t1_f15_wp", reg["plugins"])

    def test_t1_f15_03_cli_sync_dry_run_and_allow_same_version_fup(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.target_plugins_dir is not None
        mod_dir = create_world_plugin_fixture(self.session.mods_dir, "t1-f15-same", plugin_id="t1_f15_same")
        target_dir = self.session.target_plugins_dir / "f15_03"
        self.assertEqual(self.cli.run_isolated(["build", "t1-f15-same"]).returncode, 0)
        dry = self.cli.run_isolated(["sync", "t1-f15-same", "--dry-run", "--target-dir", str(target_dir)])
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertFalse((target_dir / "registry.json").exists(), "sync --dry-run must not write registry.json")

        self.assertEqual(self.cli.run_isolated(["sync", "t1-f15-same", "--target-dir", str(target_dir)]).returncode, 0)
        # Mutate script content slightly without bumping version
        extra_file = mod_dir / "external_modules" / "t1_f15_same" / "extra_note.txt"
        extra_file.write_text("v1-updated\n", encoding="utf-8")
        self.assertEqual(self.cli.run_isolated(["build", "t1-f15-same"]).returncode, 0)
        res_same = self.cli.run_isolated(["sync", "t1-f15-same", "--allow-same-version", "--target-dir", str(target_dir)])
        self.assertEqual(res_same.returncode, 0, f"{res_same.stdout}\n{res_same.stderr}")

    def test_t1_f15_04_cli_serve_serves_index_zip_and_fup(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "t1-f15-srv-dm", plugin_id="t1_f15_srv_dm")
        create_world_plugin_fixture(self.session.mods_dir, "t1-f15-srv-wp", plugin_id="t1_f15_srv_wp")
        self.assertEqual(self.cli.run_isolated(["build", "t1-f15-srv-dm"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["build", "t1-f15-srv-wp"]).returncode, 0)

        with self.cli.isolated_serve() as (port, opener):
            with opener.open(f"http://127.0.0.1:{port}/index.json", timeout=2) as resp:
                idx_data = json.loads(resp.read().decode("utf-8"))
            pkg_names = {row.get("mod_name") for row in idx_data.get("packages", [])}
            self.assertIn("t1-f15-srv-dm", pkg_names)
            self.assertIn("t1-f15-srv-wp", pkg_names)
            with opener.open(f"http://127.0.0.1:{port}/t1-f15-srv-dm.zip", timeout=2) as r_zip:
                self.assertEqual(r_zip.status, 200)
                self.assertIn("no-store", (r_zip.headers.get("Cache-Control") or "").lower())
                self.assertTrue(bool(r_zip.headers.get("X-Plugin-SHA256")))
            with opener.open(f"http://127.0.0.1:{port}/t1-f15-srv-wp.fup", timeout=2) as r_fup:
                self.assertEqual(r_fup.status, 200)
                self.assertIn("no-store", (r_fup.headers.get("Cache-Control") or "").lower())
                self.assertTrue(bool(r_fup.headers.get("X-Plugin-SHA256")))

    def test_t1_f15_05_cli_verify_host_inworld_mods(self) -> None:
        godot_bin = resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "t1-f15-vh-dm", plugin_id="t1_f15_vh_dm")
        create_world_plugin_fixture(self.session.mods_dir, "t1-f15-vh-wp", plugin_id="t1_f15_vh_wp")
        for mod_name in ("t1-f15-vh-dm", "t1-f15-vh-wp"):
            vh = self.cli.run_isolated(["verify-host", mod_name, "--godot-bin", str(godot_bin)], timeout=180)
            self.assertEqual(vh.returncode, 0, f"verify-host {mod_name} failed:\n{vh.stdout}\n{vh.stderr}")

    # =========================================================================
    # Feature #16: Security & Archive Hardening
    # =========================================================================
    def test_t1_f16_01_clean_utf8_lf_within_archive_bounds(self) -> None:
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "t1-f16-clean", plugin_id="t1_f16_clean")
        res = self.cli.run_isolated(["build", "t1-f16-clean"])
        self.assertEqual(res.returncode, 0, res.stderr)
        zip_path = self.session.build_dir / "t1-f16-clean" / "t1-f16-clean.zip"
        self.assertLessEqual(zip_path.stat().st_size, 64 * 1024 * 1024)

    def test_t1_f16_02_distinct_case_paths_allowed(self) -> None:
        assert self.session.mods_dir is not None
        mod_dir = create_desktop_module_fixture(self.session.mods_dir, "t1-f16-case", plugin_id="t1_f16_case")
        (mod_dir / "mods" / "t1_f16_case" / "asset_a.txt").write_text("a\n", encoding="utf-8")
        (mod_dir / "mods" / "t1_f16_case" / "asset_b.txt").write_text("b\n", encoding="utf-8")
        res = self.cli.run_isolated(["validate", "t1-f16-case"])
        self.assertEqual(res.returncode, 0, res.stdout)

    def test_t1_f16_03_deterministic_builds_identical_sha256(self) -> None:
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "t1-f16-det", plugin_id="t1_f16_det")
        self.assertEqual(self.cli.run_isolated(["build", "t1-f16-det"]).returncode, 0)
        zip_path = self.session.build_dir / "t1-f16-det" / "t1-f16-det.zip"
        sha1 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        time.sleep(0.05)
        self.assertEqual(self.cli.run_isolated(["build", "t1-f16-det"]).returncode, 0)
        sha2 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        self.assertEqual(sha1, sha2)

    def test_t1_f16_04_registry_atomic_write_preserves_user_settings_and_backup(self) -> None:
        assert self.session.mods_dir is not None and self.session.target_plugins_dir is not None and self.session.cache_dir is not None
        mod_dir = create_desktop_module_fixture(self.session.mods_dir, "t1-f16-reg", plugin_id="t1_f16_reg", version="1.0.0")
        target_dir = self.session.target_plugins_dir / "f16_04"
        self.assertEqual(self.cli.run_isolated(["build", "t1-f16-reg"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["sync", "t1-f16-reg", "--target-dir", str(target_dir)]).returncode, 0)

        reg_path = target_dir / "registry.json"
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        reg["plugins"]["t1_f16_reg"]["settings"]["enable_fx"] = False
        reg_path.write_text(json.dumps(reg, indent=2) + "\n", encoding="utf-8")

        manifest = json.loads((mod_dir / "plugin.json").read_text(encoding="utf-8"))
        manifest["version"] = "1.1.0"
        (mod_dir / "plugin.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(self.cli.run_isolated(["build", "t1-f16-reg"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["sync", "t1-f16-reg", "--target-dir", str(target_dir)]).returncode, 0)

        reg_after = json.loads(reg_path.read_text(encoding="utf-8"))
        self.assertIs(reg_after["plugins"]["t1_f16_reg"]["settings"]["enable_fx"], False)
        backups = list((self.session.cache_dir / "registry_backups").glob("registry_*.json"))
        self.assertTrue(backups, "Expected registry backup in .cache/registry_backups/")

    def test_t1_f16_05_cli_output_redacts_local_paths(self) -> None:
        res = self.cli.run_real(["validate", "_template"])
        self.assertEqual(res.returncode, 0)
        assert_no_local_paths_in_text(
            self,
            (res.raw_stdout or res.stdout) + "\n" + (res.raw_stderr or res.stderr),
            label="cli output",
        )

    # =========================================================================
    # Feature #17: Docs & Tutorial Wiki Synchronization
    # =========================================================================
    def test_t1_f17_01_repo_readmes_cover_all_3_schemas(self) -> None:
        for rel in ("README.md", "AGENTS.md", "shared/sdk/README.md", "shared/tools/README.md"):
            p = WORKSPACE_ROOT / rel
            self.assertTrue(p.is_file(), f"Missing {rel}")
        root_readme = (WORKSPACE_ROOT / "README.md").read_text(encoding="utf-8")
        sdk_readme = (WORKSPACE_ROOT / "shared" / "sdk" / "README.md").read_text(encoding="utf-8")
        tools_readme = (WORKSPACE_ROOT / "shared" / "tools" / "README.md").read_text(encoding="utf-8")
        combined = root_readme + "\n" + sdk_readme + "\n" + tools_readme
        for schema in ("fus.session-plugin.v1", "fus.desktop-module.v1", "fus.plugin.v2"):
            self.assertIn(schema, combined, f"Repo READMEs missing schema {schema}")
        self.assertIn("fu_runtime", sdk_readme, "shared/sdk/README.md must document fu_runtime")

    def test_t1_f17_02_shared_docs_cover_inworld_contracts(self) -> None:
        docs_dir = WORKSPACE_ROOT / "shared" / "docs"
        combined = "\n".join(p.read_text(encoding="utf-8") for p in sorted(docs_dir.glob("*.md")))
        for token in ("fus.desktop-module.v1", "fus.plugin.v2", "desktop_api", "world.overlays", "public_state", "WorldModuleState", "network.actions"):
            self.assertIn(token, combined, f"shared/docs/*.md missing contract keyword {token}")

    def test_t1_f17_03_wiki_has_inworld_docs_and_no_broken_links(self) -> None:
        wiki_dir = resolve_wiki_dir()
        if not wiki_dir.is_dir():
            if os.environ.get("FUVTT_E2E_REQUIRE_GODOT") == "1" or os.environ.get("FUVTT_E2E_REQUIRE_WIKI") == "1":
                self.fail(f"Required Wiki directory not present: {self.session.cfg.redact_path(wiki_dir)}")
            raise unittest.SkipTest("Wiki dir not present")
        self.assertFalse((wiki_dir / ".meta").exists(), "Wiki must not contain .meta/ directory")
        nested_mds = [
            str(p.relative_to(wiki_dir))
            for p in wiki_dir.rglob("*.md")
            if ".git" not in p.parts and len(p.relative_to(wiki_dir).parts) > 1
        ]
        self.assertEqual(nested_mds, [], f"Wiki .md files must be flat at root: {nested_mds}")
        md_files = sorted(wiki_dir.glob("*.md"))
        stems = {p.stem for p in md_files}
        self.assertIn("Home", stems)
        self.assertIn("_Sidebar", stems)
        self.assertIn("Guide-Hybrid-Dual-Activation", stems)
        combined = "\n".join(p.read_text(encoding="utf-8") for p in md_files)
        self.assertIn("fus.desktop-module.v1", combined, "Wiki must document fus.desktop-module.v1")
        self.assertIn("fus.plugin.v2", combined, "Wiki must document fus.plugin.v2")
        self.assertIn("sdk_log_console", combined, "Wiki must document sdk_log_console")
        self.assertIn("mod.sdk_log_console", combined, "Wiki must document mod.sdk_log_console")
        mediawiki_re = re.compile(r"\[\[([^\]]+)\]\]")
        md_link_re = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
        hardcoded_wiki_re = re.compile(r"https?://github\.com/[^/\s)]+/[^/\s)]+/wiki(?:/[^\s)]*)?", re.IGNORECASE)
        for md in md_files:
            in_fence = False
            for line_no, raw_line in enumerate(md.read_text(encoding="utf-8").splitlines(), start=1):
                if raw_line.lstrip(" ").startswith(("```", "~~~")):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                self.assertIsNone(
                    mediawiki_re.search(raw_line),
                    f"MediaWiki [[...]] link found in {md.name}:L{line_no}",
                )
                self.assertIsNone(
                    hardcoded_wiki_re.search(raw_line),
                    f"Hardcoded GitHub Wiki URL found in {md.name}:L{line_no}",
                )
                for _label, raw_target in md_link_re.findall(raw_line):
                    target = raw_target.strip().split()[0]
                    if target.startswith(("http://", "https://", "mailto:", "#")):
                        continue
                    slug_part = target.split("#", 1)[0]
                    if not slug_part:
                        continue
                    self.assertFalse(
                        slug_part.endswith(".md"),
                        f"Intra-Wiki link '{target}' must not include .md in {md.name}:L{line_no}",
                    )
                    self.assertNotIn(
                        "/",
                        slug_part,
                        f"Intra-Wiki link '{target}' must not contain '/' in {md.name}:L{line_no}",
                    )
                    self.assertIn(
                        slug_part,
                        stems,
                        f"Broken Wiki link '{target}' in {md.name}:L{line_no}",
                    )

    def test_t1_f17_04_documented_cli_flags_match_help(self) -> None:
        help_res = self.cli.run_real(["init", "--help"])
        self.assertEqual(help_res.returncode, 0)
        self.assertIn("--mode", help_res.stdout)
        tools_readme = (WORKSPACE_ROOT / "shared" / "tools" / "README.md").read_text(encoding="utf-8")
        self.assertIn("--mode", tools_readme)
        # Verify every fuvtt_cli.py <subcmd> --flag across repo docs & Wiki matches live --help
        valid_flags: dict[str, set[str]] = {}
        for subcmd in ("init", "validate", "build", "sync", "serve", "inspect-client", "verify-host"):
            sub_help = self.cli.run_real([subcmd, "--help"])
            self.assertEqual(sub_help.returncode, 0, f"{subcmd} --help failed")
            valid_flags[subcmd] = set(re.findall(r"--[a-z0-9][a-z0-9-]*", sub_help.stdout))
        doc_files: list[Path] = [
            WORKSPACE_ROOT / "README.md",
            WORKSPACE_ROOT / "shared" / "tools" / "README.md",
            *sorted((WORKSPACE_ROOT / "shared" / "docs").glob("*.md")),
        ]
        wiki_dir = resolve_wiki_dir()
        if wiki_dir.is_dir():
            doc_files.extend(sorted(wiki_dir.glob("*.md")))
        elif os.environ.get("FUVTT_E2E_REQUIRE_GODOT") == "1" or os.environ.get("FUVTT_E2E_REQUIRE_WIKI") == "1":
            self.fail(f"Required Wiki directory not present: {self.session.cfg.redact_path(wiki_dir)}")

        checked_cmds = 0
        for doc_path in doc_files:
            checked_cmds += lint_doc_cli_commands(
                self,
                doc_path.read_text(encoding="utf-8"),
                valid_flags,
                label=doc_path.name,
                require_known_subcommand=True,
            )
        self.assertGreater(checked_cmds, 0, "Expected at least one documented fuvtt_cli.py command")

    def test_t1_f17_05_docs_have_zero_local_path_leaks(self) -> None:
        scan_files: list[Path] = [
            WORKSPACE_ROOT / "README.md",
            WORKSPACE_ROOT / "AGENTS.md",
            WORKSPACE_ROOT / "shared" / "sdk" / "README.md",
            WORKSPACE_ROOT / "shared" / "sdk" / "AGENTS.md",
            WORKSPACE_ROOT / "shared" / "tools" / "README.md",
            *sorted((WORKSPACE_ROOT / "shared" / "docs").glob("*.md")),
        ]
        for tmpl_dir in sorted((WORKSPACE_ROOT / "mods").glob("_template*")):
            if tmpl_dir.is_dir():
                scan_files.extend(sorted(tmpl_dir.rglob("*.md")))
        wiki_dir = resolve_wiki_dir()
        if wiki_dir.is_dir():
            scan_files.extend(sorted(wiki_dir.glob("*.md")))
        elif os.environ.get("FUVTT_E2E_REQUIRE_GODOT") == "1" or os.environ.get("FUVTT_E2E_REQUIRE_WIKI") == "1":
            self.fail(f"Required Wiki directory not present: {self.session.cfg.redact_path(wiki_dir)}")
        for md in scan_files:
            assert_no_local_paths_in_text(self, md.read_text(encoding="utf-8"), label=md.name)
