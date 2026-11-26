"""Tier 2: Boundary & Negative/Rejection Tests (34 cases: 2 per feature across #1-#17)."""

from __future__ import annotations

import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
import zipfile

from .assertions import (
    CLASS_NAME_RE,
    LOCAL_PATH_LEAK_RE,
    PRELOAD_RE,
    assert_case_clean,
    assert_fup_archive_contract,
    assert_gdscript_hygiene,
    assert_no_local_paths_in_text,
    assert_zip_archive_contract,
    lint_doc_cli_commands,
)
from .fixtures import (
    corrupt_fup_pck,
    create_desktop_module_fixture,
    create_v1_session_plugin,
    create_world_plugin_fixture,
)
from .harness import (
    TOOLS_DIR,
    WORKSPACE_ROOT,
    CliRunner,
    E2ESession,
    GodotBatchProbe,
    ProbeCaseSpec,
    resolve_godot_or_skip,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Tier2BoundaryTests(unittest.TestCase):
    """34 negative, boundary & rejection tests (`t2_f01_01`..`t2_f17_02`)."""

    session: E2ESession
    cli: CliRunner

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = E2ESession(name_prefix="tier2")
        cls.session.setup(require_godot=False)
        cls.cli = CliRunner(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.session.cleanup()

    # #1
    def test_t2_f01_01_v1_rejects_host_api_2_or_scope_desktop(self) -> None:
        assert self.session.mods_dir is not None
        create_v1_session_plugin(self.session.mods_dir, "t2-f01-bad-api", host_api=2, scope="desktop")
        res = self.cli.run_isolated(["validate", "t2-f01-bad-api"])
        self.assertNotEqual(res.returncode, 0, "v1 with host_api=2/scope=desktop must fail validate")

    def test_t2_f01_02_v1_rejects_entry_extending_node2d(self) -> None:
        assert self.session.mods_dir is not None
        create_v1_session_plugin(self.session.mods_dir, "t2-f01-bad-base", extends_base="Node2D")
        res = self.cli.run_isolated(["validate", "t2-f01-bad-base"])
        self.assertNotEqual(res.returncode, 0, "v1 entry.gd extending Node2D must fail validate")

    # #2
    def test_t2_f02_01_inspect_client_missing_fus_repo_fails_cleanly(self) -> None:
        assert self.session.run_dir is not None
        missing_repo = self.session.run_dir / "nonexistent_fus_repo"
        res = self.cli.run_real(["inspect-client", "--source", "git", "--fus-repo", str(missing_repo)])
        self.assertNotEqual(res.returncode, 0)

    def test_t2_f02_02_v1_verify_host_flags_missing_unsupported_or_bad_asset_url(self) -> None:
        godot_bin = resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None
        create_v1_session_plugin(
            self.session.mods_dir,
            "t2-f02-bad-insp",
            bad_inspect_missing_unsupported=True,
            bad_asset_url=True,
        )
        res = self.cli.run_isolated(["verify-host", "t2-f02-bad-insp", "--godot-bin", str(godot_bin)], timeout=180)
        self.assertNotEqual(res.returncode, 0, "verify-host must reject missing counts.unsupported / ftp asset URL")

    # #3
    def test_t2_f03_01_hygiene_detector_rejects_class_name_and_preload(self) -> None:
        assert self.session.run_dir is not None
        bad_gd = self.session.run_dir / "bad_runtime_leaf.gd"
        bad_gd.write_text("extends RefCounted\nclass_name BadLeaf\nconst X = preload(\"res://foo.gd\")\n", encoding="utf-8")
        with self.assertRaises(AssertionError):
            assert_gdscript_hygiene(self, bad_gd, require_extends_refcounted=True, forbid_class_name=True, forbid_preload=True)
        self.assertIsNotNone(CLASS_NAME_RE.search(bad_gd.read_text(encoding="utf-8")))
        self.assertIsNotNone(PRELOAD_RE.search(bad_gd.read_text(encoding="utf-8")))

    def test_t2_f03_02_object_count_catches_unfreed_nodes(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([
            ProbeCaseSpec(case_id="t2_f03_02", op="fu_runtime_leak_check", params={"create_cycle": True})
        ])
        res = summary.results["t2_f03_02"]
        assert_case_clean(self, res)
        self.assertGreater(float(res.data.get("delta", 0.0)), 0.0)

    # #4
    def test_t2_f04_01_desktop_module_rejects_pack_file_or_bad_entry_scene(self) -> None:
        assert self.session.mods_dir is not None
        create_desktop_module_fixture(
            self.session.mods_dir,
            "t2-f04-pck",
            plugin_id="t2_f04_pck",
            pack_file="content.pck",
            entry_scene_override="res://other_ns/module.tscn",
        )
        res = self.cli.run_isolated(["validate", "t2-f04-pck"])
        self.assertNotEqual(res.returncode, 0, "fus.desktop-module.v1 with pack_file / outside entry_scene must fail")

    def test_t2_f04_02_desktop_module_rejects_foreign_module_id_or_over_16_modules(self) -> None:
        assert self.session.mods_dir is not None
        create_desktop_module_fixture(
            self.session.mods_dir,
            "t2-f04-foreign",
            plugin_id="t2_f04_foreign",
            module_id="other_plugin.sub",
            use_plural_modules=True,
        )
        res = self.cli.run_isolated(["validate", "t2-f04-foreign"])
        self.assertNotEqual(res.returncode, 0, "Foreign module.id must fail validate")

        mod_over = create_world_plugin_fixture(self.session.mods_dir, "t2-f04-over16", plugin_id="t2_f04_over16", module_count=17)
        res_over = self.cli.run_isolated(["validate", "t2-f04-over16"])
        self.assertNotEqual(res_over.returncode, 0, f">16 modules in {mod_over.name} must fail validate")

    # #5
    def test_t2_f05_01_desktop_api_masks_vitals_for_unauth_non_gm(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([
            ProbeCaseSpec(case_id="t2_f05_01", op="desktop_api_contract", params={"non_gm": True})
        ])
        res = summary.results["t2_f05_01"]
        assert_case_clean(self, res)
        self.assertTrue(res.ok)
        vitals = res.data.get("vitals", {})
        self.assertIs(res.data.get("can_command_self"), False)
        self.assertIs(vitals.get("masked"), True)
        self.assertEqual(vitals.get("source_kind"), "stat_bubble")
        self.assertNotIn("hp_cur", vitals)
        self.assertNotIn("hp", vitals)
        self.assertNotIn("ac", vitals)

    def test_t2_f05_02_desktop_api_blocks_non_gm_saved_entry_and_inf_camera(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([
            ProbeCaseSpec(case_id="t2_f05_02", op="desktop_api_contract", params={"non_gm": True})
        ])
        res = summary.results["t2_f05_02"]
        assert_case_clean(self, res)
        self.assertEqual(res.data.get("saved_entry"), {})
        self.assertIs(res.data.get("focus_bad_inf"), False)

    # #6
    def test_t2_f06_01_hook_bus_rejects_malformed_and_unknown_hooks(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t2_f06_01", op="hook_bus_contract")])
        res = summary.results["t2_f06_01"]
        assert_case_clean(self, res)
        self.assertIs(res.data.get("r_bad_upper_ok"), False)
        self.assertIs(res.data.get("r_bad_two_ok"), False)

    def test_t2_f06_02_hook_bus_blocks_emit_while_publishing_or_inactive(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t2_f06_02", op="hook_bus_contract")])
        res = summary.results["t2_f06_02"]
        assert_case_clean(self, res)
        self.assertIs(res.data.get("emitted_while_pub"), False)
        self.assertIs(res.data.get("emitted_after_revert"), False)

    # #7
    def test_t2_f07_01_world_overlays_rejects_invalid_band(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t2_f07_01", op="overlay_and_mount_contract")])
        res = summary.results["t2_f07_01"]
        assert_case_clean(self, res)
        self.assertIs(res.data.get("bad_band_ok"), False)

    def test_t2_f07_02_mount_node_rejects_parented_or_outside_target(self) -> None:
        probe = GodotBatchProbe(self.session)
        summary = probe.run_batch([ProbeCaseSpec(case_id="t2_f07_02", op="overlay_and_mount_contract")])
        res = summary.results["t2_f07_02"]
        assert_case_clean(self, res)
        self.assertIs(res.data.get("already_parented_ok"), False)
        self.assertIs(res.data.get("outside_target_ok"), False)

    # #8
    def test_t2_f08_01_desktop_module_rejects_local_only_false_or_net_ver_1(self) -> None:
        assert self.session.mods_dir is not None
        create_desktop_module_fixture(
            self.session.mods_dir,
            "t2-f08-bad-net",
            plugin_id="t2_f08_bad_net",
            local_only=False,
            network_version=1,
        )
        res = self.cli.run_isolated(["validate", "t2-f08-bad-net"])
        self.assertNotEqual(res.returncode, 0, "fus.desktop-module.v1 with local_only=false/network_version=1 must fail")

    def test_t2_f08_02_v2_non_local_rejects_missing_network_version(self) -> None:
        assert self.session.mods_dir is not None
        create_world_plugin_fixture(
            self.session.mods_dir,
            "t2-f08-no-nver",
            plugin_id="t2_f08_no_nver",
            local_only=False,
            network_version=None,
        )
        res = self.cli.run_isolated(["validate", "t2-f08-no-nver"])
        self.assertNotEqual(res.returncode, 0, "Non-local fus.plugin.v2 omitting network_version must fail validate")

    # #9
    def test_t2_f09_01_fup_rejects_corrupted_pck_or_bad_sha256sums(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None and self.session.run_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t2-f09-cor", plugin_id="t2_f09_cor")
        self.assertEqual(self.cli.run_isolated(["build", "t2-f09-cor"]).returncode, 0)
        good_fup = self.session.build_dir / "t2-f09-cor" / "t2-f09-cor.fup"

        bad_magic_fup = corrupt_fup_pck(good_fup, self.session.run_dir / "bad_magic.fup", bad_magic=True)
        bad_sums_fup = corrupt_fup_pck(good_fup, self.session.run_dir / "bad_sums.fup", bad_sums=True)

        from fuvtt_devtools.validator import validate_zip_archive
        bad_magic_errs = validate_zip_archive(bad_magic_fup)
        self.assertTrue(
            any("invalid_plugin_pack" in err for err in bad_magic_errs),
            f"validate_zip_archive must reject bad GDPC magic in .fup: {bad_magic_errs}",
        )
        bad_sums_errs = validate_zip_archive(bad_sums_fup)
        self.assertTrue(
            any("SHA256SUMS.txt" in err for err in bad_sums_errs),
            f"validate_zip_archive must reject corrupted SHA256SUMS.txt in .fup: {bad_sums_errs}",
        )

        with self.assertRaises(AssertionError):
            assert_fup_archive_contract(self, bad_magic_fup, plugin_id="t2_f09_cor")
        with self.assertRaises(AssertionError):
            assert_fup_archive_contract(self, bad_sums_fup, plugin_id="t2_f09_cor")

    def test_t2_f09_02_fup_rejects_missing_content_pck(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None and self.session.run_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t2-f09-mis", plugin_id="t2_f09_mis")
        self.assertEqual(self.cli.run_isolated(["build", "t2-f09-mis"]).returncode, 0)
        good_fup = self.session.build_dir / "t2-f09-mis" / "t2-f09-mis.fup"
        missing_pck_fup = corrupt_fup_pck(good_fup, self.session.run_dir / "missing_pck.fup", missing_pck=True)

        from fuvtt_devtools.validator import validate_zip_archive
        missing_errs = validate_zip_archive(missing_pck_fup)
        self.assertTrue(
            any("plugin_pack_missing" in err for err in missing_errs),
            f"validate_zip_archive must reject missing content.pck in .fup: {missing_errs}",
        )
        with self.assertRaises(AssertionError):
            assert_fup_archive_contract(self, missing_pck_fup, plugin_id="t2_f09_mis")

    # #10
    def test_t2_f10_01_comp_rejects_bad_filename_or_reserved_id(self) -> None:
        assert self.session.mods_dir is not None
        godot_bin = resolve_godot_or_skip(self.session.cfg)

        # (a) Valid comp_ filename, but reserved core component id "visual"
        create_world_plugin_fixture(
            self.session.mods_dir,
            "t2-f10-resv",
            plugin_id="t2_f10_resv",
            comp_filename_override="comp_visual.gd",
            comp_id_override="visual",
        )
        res_resv = self.cli.run_isolated(["validate", "t2-f10-resv"])
        self.assertEqual(res_resv.returncode, 0, res_resv.stderr)
        self.assertEqual(self.cli.run_isolated(["build", "t2-f10-resv"]).returncode, 0)
        vh_resv = self.cli.run_isolated(["verify-host", "t2-f10-resv", "--godot-bin", str(godot_bin)])
        self.assertNotEqual(vh_resv.returncode, 0, "Reserved component id 'visual' must be rejected")
        self.assertIn("reserved core component: visual", vh_resv.stdout + "\n" + vh_resv.stderr)

        # (b) Matching id/filename, but filename lacks required `comp_` prefix
        create_world_plugin_fixture(
            self.session.mods_dir,
            "t2-f10-pfx",
            plugin_id="t2_f10_pfx",
            comp_filename_override="my_comp.gd",
            comp_id_override="my_comp",
        )
        res_pfx = self.cli.run_isolated(["validate", "t2-f10-pfx"])
        self.assertEqual(res_pfx.returncode, 0, res_pfx.stderr)
        self.assertEqual(self.cli.run_isolated(["build", "t2-f10-pfx"]).returncode, 0)
        vh_pfx = self.cli.run_isolated(["verify-host", "t2-f10-pfx", "--godot-bin", str(godot_bin)])
        self.assertNotEqual(vh_pfx.returncode, 0, "Component filename missing `comp_` prefix must be rejected")
        self.assertIn("filename begins with comp_: my_comp.gd", vh_pfx.stdout + "\n" + vh_pfx.stderr)

    def test_t2_f10_02_comp_missing_public_state_detected(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t2-f10-nopub", plugin_id="t2_f10_nopub", omit_public_state=True)
        self.assertEqual(self.cli.run_isolated(["build", "t2-f10-nopub"]).returncode, 0)
        fup_path = self.session.build_dir / "t2-f10-nopub" / "t2-f10-nopub.fup"
        probe = GodotBatchProbe(self.session)
        pck = probe.extract_fup_pck(fup_path)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t2_f10_02",
                op="world_plugin_comp_and_disclosure",
                pack_path=pck.resolve().as_posix(),
                params={"comp_path": "res://external_modules/t2_f10_nopub/comp_t2_f10_nopub__emitter.gd"},
            )
        ])
        res = summary.results["t2_f10_02"]
        assert_case_clean(self, res)
        self.assertIs(res.data.get("has_public_state"), False)

    # #11
    def test_t2_f11_01_page_not_extending_entity_component_page_rejected(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t2-f11-badpg", plugin_id="t2_f11_badpg", bad_page_base=True)
        self.assertEqual(self.cli.run_isolated(["build", "t2-f11-badpg"]).returncode, 0)
        fup_path = self.session.build_dir / "t2-f11-badpg" / "t2-f11-badpg.fup"
        probe = GodotBatchProbe(self.session)
        pck = probe.extract_fup_pck(fup_path)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t2_f11_01",
                op="world_plugin_page_and_undo",
                pack_path=pck.resolve().as_posix(),
                params={
                    "page_scene": "res://external_modules/t2_f11_badpg/comp_page.tscn",
                    "comp_path": "res://external_modules/t2_f11_badpg/comp_t2_f11_badpg__emitter.gd",
                },
            )
        ])
        res = summary.results["t2_f11_01"]
        assert_case_clean(self, res)
        self.assertIs(res.data.get("is_EntityComponentPage"), False)

    def test_t2_f11_02_configure_components_rejects_non_editable_field(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t2-f11-noed", plugin_id="t2_f11_noed")
        self.assertEqual(self.cli.run_isolated(["build", "t2-f11-noed"]).returncode, 0)
        fup_path = self.session.build_dir / "t2-f11-noed" / "t2-f11-noed.fup"
        probe = GodotBatchProbe(self.session)
        pck = probe.extract_fup_pck(fup_path)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t2_f11_02",
                op="world_plugin_page_and_undo",
                pack_path=pck.resolve().as_posix(),
                params={
                    "page_scene": "res://external_modules/t2_f11_noed/comp_page.tscn",
                    "comp_path": "res://external_modules/t2_f11_noed/comp_t2_f11_noed__emitter.gd",
                },
            )
        ])
        res = summary.results["t2_f11_02"]
        assert_case_clean(self, res)
        self.assertIs(res.data.get("bad_field_rejected"), True)
        self.assertIs(res.data.get("schema_version_mutation_rejected"), True)

    # #12
    def test_t2_f12_01_state_value_rejects_object_nan_and_depth_over_32(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t2-f12-badst", plugin_id="t2_f12_badst")
        self.assertEqual(self.cli.run_isolated(["build", "t2-f12-badst"]).returncode, 0)
        fup_path = self.session.build_dir / "t2-f12-badst" / "t2-f12-badst.fup"
        probe = GodotBatchProbe(self.session)
        pck = probe.extract_fup_pck(fup_path)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t2_f12_01",
                op="world_module_state_3phase",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t2_f12_badst/feature_t2_f12_badst.tscn"},
            )
        ])
        res = summary.results["t2_f12_01"]
        assert_case_clean(self, res)
        self.assertIs(res.data.get("rejects_object"), True)
        self.assertIs(res.data.get("rejects_nan"), True)
        self.assertIs(res.data.get("rejects_deep"), True)

    def test_t2_f12_02_prepare_module_state_bad_version_returns_ok_false(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t2-f12-ver", plugin_id="t2_f12_ver")
        self.assertEqual(self.cli.run_isolated(["build", "t2-f12-ver"]).returncode, 0)
        fup_path = self.session.build_dir / "t2-f12-ver" / "t2-f12-ver.fup"
        probe = GodotBatchProbe(self.session)
        pck = probe.extract_fup_pck(fup_path)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t2_f12_02",
                op="world_module_state_3phase",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t2_f12_ver/feature_t2_f12_ver.tscn"},
            )
        ])
        res = summary.results["t2_f12_02"]
        assert_case_clean(self, res)
        self.assertIs(res.data.get("prep_bad_ok"), False)

    # #13
    def test_t2_f13_01_network_slot_id_mismatch_detected(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(
            self.session.mods_dir,
            "t2-f13-misid",
            plugin_id="t2_f13_misid",
            slot_module_id_override="t2_f13_misid.wrong_sub",
        )
        self.assertEqual(self.cli.run_isolated(["build", "t2-f13-misid"]).returncode, 0)
        fup_path = self.session.build_dir / "t2-f13-misid" / "t2-f13-misid.fup"
        probe = GodotBatchProbe(self.session)
        pck = probe.extract_fup_pck(fup_path)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t2_f13_01",
                op="network_actions_projections",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t2_f13_misid/feature_t2_f13_misid.tscn"},
            )
        ])
        res = summary.results["t2_f13_01"]
        assert_case_clean(self, res)
        self.assertIs(res.data.get("action_id_matches_module"), False)
        self.assertIs(res.data.get("proj_id_matches_module"), False)

    def test_t2_f13_02_network_action_revoked_and_non_owner_stage_rejected(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t2-f13-rev", plugin_id="t2_f13_rev")
        self.assertEqual(self.cli.run_isolated(["build", "t2-f13-rev"]).returncode, 0)
        fup_path = self.session.build_dir / "t2-f13-rev" / "t2-f13-rev.fup"
        probe = GodotBatchProbe(self.session)
        pck = probe.extract_fup_pck(fup_path)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t2_f13_02",
                op="network_actions_projections",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t2_f13_rev/feature_t2_f13_rev.tscn"},
            )
        ])
        res = summary.results["t2_f13_02"]
        assert_case_clean(self, res)
        self.assertEqual(res.data.get("revoked_unauth"), "permission_denied")
        self.assertIs(res.data.get("bad_stage_rejected"), True)
        self.assertIs(res.data.get("non_owner_stage_rejected"), True)
        self.assertIs(res.data.get("non_owner_restore_rejected"), True)
        self.assertIs(res.data.get("unowned_sync_stage_rejected"), True)
        self.assertIs(res.data.get("unowned_sync_restore_rejected"), True)
        self.assertIs(res.data.get("other_owner_sync_stage_rejected"), True)
        self.assertIs(res.data.get("good_stage_ok"), True)
        self.assertIs(res.data.get("restored_ok"), True)

    # #14
    def test_t2_f14_01_ui_mode_bar_on_enter_null_not_true(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t2-f14-null", plugin_id="t2_f14_null", bad_mode_on_enter_null=True)
        self.assertEqual(self.cli.run_isolated(["build", "t2-f14-null"]).returncode, 0)
        fup_path = self.session.build_dir / "t2-f14-null" / "t2-f14-null.fup"
        probe = GodotBatchProbe(self.session)
        pck = probe.extract_fup_pck(fup_path)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t2_f14_01",
                op="ui_slots_contract",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t2_f14_null/feature_t2_f14_null.tscn"},
            )
        ])
        res = summary.results["t2_f14_01"]
        assert_case_clean(self, res)
        self.assertIs(res.data.get("mode_on_enter_is_true"), False)

    def test_t2_f14_02_ui_entity_action_id_without_dot_rejected(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "t2-f14-nodot", plugin_id="t2_f14_nodot", bad_action_id_no_dot=True)
        self.assertEqual(self.cli.run_isolated(["build", "t2-f14-nodot"]).returncode, 0)
        fup_path = self.session.build_dir / "t2-f14-nodot" / "t2-f14-nodot.fup"
        probe = GodotBatchProbe(self.session)
        pck = probe.extract_fup_pck(fup_path)
        summary = probe.run_batch([
            ProbeCaseSpec(
                case_id="t2_f14_02",
                op="ui_slots_contract",
                pack_path=pck.resolve().as_posix(),
                params={"feature_scene": "res://external_modules/t2_f14_nodot/feature_t2_f14_nodot.tscn"},
            )
        ])
        res = summary.results["t2_f14_02"]
        assert_case_clean(self, res)
        self.assertIn("t2_f14_nodot_toggle", res.data.get("rejected_items", []))

    # #15
    def test_t2_f15_01_sync_rejects_version_downgrade_and_same_version_conflict(self) -> None:
        assert self.session.mods_dir is not None and self.session.target_plugins_dir is not None
        mod_dir = create_desktop_module_fixture(self.session.mods_dir, "t2-f15-ver", plugin_id="t2_f15_ver", version="1.1.0")
        target_dir = self.session.target_plugins_dir / "f15_01"
        self.assertEqual(self.cli.run_isolated(["build", "t2-f15-ver"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["sync", "t2-f15-ver", "--target-dir", str(target_dir)]).returncode, 0)

        # Same version different hash without --allow-same-version -> fail
        (mod_dir / "mods" / "t2_f15_ver" / "extra.txt").write_text("changed\n", encoding="utf-8")
        self.assertEqual(self.cli.run_isolated(["build", "t2-f15-ver"]).returncode, 0)
        conflict = self.cli.run_isolated(["sync", "t2-f15-ver", "--target-dir", str(target_dir)])
        self.assertNotEqual(conflict.returncode, 0, "Same version SHA mismatch without --allow-same-version must fail")

        # Downgrade 1.1.0 -> 1.0.0 -> fail
        m = json.loads((mod_dir / "plugin.json").read_text(encoding="utf-8"))
        m["version"] = "1.0.0"
        (mod_dir / "plugin.json").write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(self.cli.run_isolated(["build", "t2-f15-ver"]).returncode, 0)
        downgrade = self.cli.run_isolated(["sync", "t2-f15-ver", "--allow-same-version", "--target-dir", str(target_dir)])
        self.assertNotEqual(downgrade.returncode, 0, "Version downgrade 1.1.0 -> 1.0.0 must fail")

    def test_t2_f15_02_serve_blocks_traversal_and_verify_host_fails_broken_gd(self) -> None:
        godot_bin = resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None
        mod_dir = create_desktop_module_fixture(self.session.mods_dir, "t2-f15-broken", plugin_id="t2_f15_broken")
        (mod_dir / "mods" / "t2_f15_broken" / "module.gd").write_text("extends ExtensionBase\nfunc broken(:\n", encoding="utf-8")
        vh = self.cli.run_isolated(["verify-host", "t2-f15-broken", "--godot-bin", str(godot_bin)], timeout=180)
        self.assertNotEqual(vh.returncode, 0, "verify-host must fail on broken GDScript syntax")

        # Also test serve path traversal 404
        create_desktop_module_fixture(self.session.mods_dir, "t2-f15-srv", plugin_id="t2_f15_srv")
        self.assertEqual(self.cli.run_isolated(["build", "t2-f15-srv"]).returncode, 0)
        with self.cli.isolated_serve() as (port, opener):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                opener.open(f"http://127.0.0.1:{port}/../plugin.json", timeout=2)
            self.assertEqual(ctx.exception.code, 404)

    # #16
    def test_t2_f16_01_rejects_forbidden_binaries_and_global_class_name(self) -> None:
        assert self.session.mods_dir is not None
        for ext in (".dll", ".exe", ".sh", ".ps1"):
            mname = f"t2-f16-bin-{ext.lstrip('.')}"
            pid = f"t2_f16_bin_{ext.lstrip('.')}"
            mdir = create_desktop_module_fixture(self.session.mods_dir, mname, plugin_id=pid)
            (mdir / "mods" / pid / f"payload{ext}").write_bytes(b"MZ")
            res = self.cli.run_isolated(["validate", mname])
            self.assertNotEqual(res.returncode, 0, f"Forbidden binary {ext} must be rejected")

        mdir_cls = create_desktop_module_fixture(self.session.mods_dir, "t2-f16-cls", plugin_id="t2_f16_cls")
        (mdir_cls / "mods" / "t2_f16_cls" / "bad_cls.gd").write_text("extends RefCounted\nclass_name GlobalLeak\n", encoding="utf-8")
        res_cls = self.cli.run_isolated(["validate", "t2-f16-cls"])
        self.assertNotEqual(res_cls.returncode, 0, "Global class_name in module .gd must be rejected")

    def test_t2_f16_02_rejects_utf8_bom_and_zip_traversal(self) -> None:
        assert self.session.mods_dir is not None and self.session.run_dir is not None
        mdir_bom = create_desktop_module_fixture(self.session.mods_dir, "t2-f16-bom", plugin_id="t2_f16_bom")
        gd = mdir_bom / "mods" / "t2_f16_bom" / "module.gd"
        gd.write_bytes(b"\xef\xbb\xbf" + gd.read_bytes())
        res_bom = self.cli.run_isolated(["validate", "t2-f16-bom"])
        self.assertNotEqual(res_bom.returncode, 0, "UTF-8 BOM must be rejected")

        # 1. Manifest entry_scene traversal rejected by CLI validate
        create_desktop_module_fixture(
            self.session.mods_dir,
            "t2-f16-trav",
            plugin_id="t2_f16_trav",
            entry_scene_override="res://mods/t2_f16_trav/../../evil.tscn",
        )
        res_trav = self.cli.run_isolated(["validate", "t2-f16-trav"])
        self.assertNotEqual(res_trav.returncode, 0, "entry_scene '..' traversal must fail validate")

        # 2. Malicious ZIP archive with '..' traversal and symlink rejected by devtools + assertions
        from fuvtt_devtools.deployer import DeployError, safe_extract_zip
        from fuvtt_devtools.validator import validate_zip_archive

        bad_zip = self.session.run_dir / "bad_traversal_and_symlink.zip"
        with zipfile.ZipFile(bad_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("plugin.json", json.dumps({"schema": "fus.desktop-module.v1", "id": "bad_zip"}))
            zf.writestr("../escape.txt", b"escape")
            sym_info = zipfile.ZipInfo("mods/bad_sym")
            sym_info.create_system = 3
            sym_info.external_attr = 0o120777 << 16
            zf.writestr(sym_info, b"../target")

        zip_errs = validate_zip_archive(bad_zip)
        self.assertTrue(
            any("unsafe_zip_path" in e for e in zip_errs) and any("zip_link_rejected" in e for e in zip_errs),
            f"validate_zip_archive failed to reject traversal/symlink: {zip_errs}",
        )
        with self.assertRaises(DeployError):
            safe_extract_zip(bad_zip, self.session.run_dir / "bad_extract_dst")
        with self.assertRaises(AssertionError):
            assert_zip_archive_contract(
                self,
                bad_zip,
                expected_schema="fus.desktop-module.v1",
                plugin_id="bad_zip",
                expect_sdk=False,
            )

        # 3. Raw Central Directory + Local File Header backslash entry (cannot rely on ZipFile.writestr,
        # which normalizes '\' -> '/' via ZipInfo._sanitize_filename).
        raw_bs_zip = self.session.run_dir / "bad_raw_backslash.zip"
        with zipfile.ZipFile(raw_bs_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            pj_info = zipfile.ZipInfo("plugin.json", date_time=(2026, 1, 1, 0, 0, 0))
            zf.writestr(pj_info, json.dumps({"schema": "fus.desktop-module.v1", "id": "bad_bs"}))
            bs_info = zipfile.ZipInfo("mods_bad_bs.txt", date_time=(2026, 1, 1, 0, 0, 0))
            zf.writestr(bs_info, b"bs")

        raw_bytes = raw_bs_zip.read_bytes()
        self.assertEqual(raw_bytes.count(b"mods_bad_bs.txt"), 2, "Expected LFH + CD occurrences of mods_bad_bs.txt")
        raw_bs_zip.write_bytes(raw_bytes.replace(b"mods_bad_bs.txt", b"mods\\bad_bs.txt"))

        with zipfile.ZipFile(raw_bs_zip, "r") as zf:
            self.assertIsNone(zf.testzip())
            non_manifest = [i for i in zf.infolist() if i.filename != "plugin.json"]
            self.assertEqual(len(non_manifest), 1)
            self.assertEqual(non_manifest[0].orig_filename, "mods\\bad_bs.txt")
            self.assertEqual(non_manifest[0].filename, "mods/bad_bs.txt")

        with self.assertRaisesRegex(AssertionError, r"backslash"):
            assert_zip_archive_contract(
                self,
                raw_bs_zip,
                expected_schema="fus.desktop-module.v1",
                plugin_id="bad_bs",
                expect_sdk=False,
            )

    # #17
    def test_t2_f17_01_doc_linter_rejects_hardcoded_local_paths(self) -> None:
        assert self.session.run_dir is not None
        leak_samples = {
            "leak_win.md": "Install path: " + "".join(["C:", "\\", "Users", "\\", "sample_dev", "\\", "FUS"]) + "\n",
            "leak_x86.md": "Godot path: " + "".join(["C:", "\\", "Program Files (x86)", "\\", "Steam", "\\", "Godot.exe"]) + "\n",
            "leak_steamlib.md": "Steam path: " + "".join(["D:", "\\", "SteamLibrary", "\\", "steamapps", "\\", "common"]) + "\n",
            "leak_posix.md": "Repo path: " + "/".join(["", "home", "sample_dev", "fuvtt-forge"]) + "\n",
            "leak_opt.md": "Tool path: " + "/".join(["", "opt", "godot", "godot4"]) + "\n",
            "leak_volumes.md": "Mac path: " + "/".join(["", "Volumes", "WorkDisk", "FUS"]) + "\n",
        }
        for fname, content in leak_samples.items():
            leak_doc = self.session.run_dir / fname
            leak_doc.write_text(content, encoding="utf-8")
            with self.assertRaises(AssertionError, msg=f"Expected local path leak failure for {fname}"):
                assert_no_local_paths_in_text(self, leak_doc.read_text(encoding="utf-8"), label=fname)

        clean_doc = self.session.run_dir / "clean_doc.md"
        clean_doc.write_text(
            "Use `<FUS_REPO_DIR>`, `<FUVTT_INSTALL_DIR>`, and `<GODOT_BIN>`.\n",
            encoding="utf-8",
        )
        assert_no_local_paths_in_text(self, clean_doc.read_text(encoding="utf-8"), label=clean_doc.name)

    def test_t2_f17_02_doc_linter_catches_unknown_cli_flag(self) -> None:
        root_help = self.cli.run_real(["--help"])
        self.assertEqual(root_help.returncode, 0, root_help.stderr)

        valid_flags: dict[str, set[str]] = {}
        for subcmd in ("init", "validate", "build", "sync", "serve", "inspect-client", "verify-host"):
            self.assertIn(subcmd, root_help.stdout)
            sub_help = self.cli.run_real([subcmd, "--help"])
            self.assertEqual(sub_help.returncode, 0, f"{subcmd} --help failed: {sub_help.stderr}")
            valid_flags[subcmd] = set(re.findall(r"--[a-z0-9][a-z0-9-]*", sub_help.stdout))

        valid_doc = (
            "Run `python shared/tools/fuvtt_cli.py init my-mod --mode desktop-module`.\n"
            "```bash\n"
            "python shared/tools/fuvtt_cli.py validate my-mod && python shared/tools/fuvtt_cli.py build my-mod --no-sdk\n"
            "python shared/tools/fuvtt_cli.py init my-mod \\\n"
            "  --mode desktop-module\n"
            "python shared/tools/fuvtt_cli.py init my-mod | grep --color=never ok\n"
            "python shared/tools/fuvtt_cli.py validate my-mod || python shared/tools/fuvtt_cli.py init my-mod --mode desktop-module\n"
            "```\n"
        )
        checked = lint_doc_cli_commands(self, valid_doc, valid_flags, label="valid_doc", require_known_subcommand=True)
        self.assertEqual(checked, 7)

        with self.assertRaises(AssertionError):
            lint_doc_cli_commands(
                self,
                "```bash\npython shared/tools/fuvtt_cli.py init my-mod --nonexistent-flag-xyz\n```\n",
                valid_flags,
                label="bad_flag_fence",
                require_known_subcommand=True,
            )
        with self.assertRaises(AssertionError):
            lint_doc_cli_commands(
                self,
                "```bash\npython shared/tools/fuvtt_cli.py init my-mod \\\n  --bogus-multiline-flag\n```\n",
                valid_flags,
                label="bad_multiline_flag_fence",
                require_known_subcommand=True,
            )
        with self.assertRaises(AssertionError):
            lint_doc_cli_commands(
                self,
                "```bash\npython shared/tools/fuvtt_cli.py validate my-mod || python shared/tools/fuvtt_cli.py init my-mod --bogus-or-flag\n```\n",
                valid_flags,
                label="bad_or_chain_flag_fence",
                require_known_subcommand=True,
            )
        with self.assertRaises(AssertionError):
            lint_doc_cli_commands(
                self,
                "Use `python shared/tools/fuvtt_cli.py unknown-cmd my-mod`.\n",
                valid_flags,
                label="bad_subcmd_inline",
                require_known_subcommand=True,
            )
