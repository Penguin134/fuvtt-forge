"""Tier 0: Baseline-ready Harness, Hygiene, CLI & Headless Godot IPC Smoke Tests."""

from __future__ import annotations

import json
import unittest
import zipfile

from .assertions import (
    assert_build_artifact_bundles_sdk,
    assert_case_passed,
    assert_gdscript_hygiene,
    assert_no_local_paths_in_text,
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
)


class Tier0SmokeTests(unittest.TestCase):
    """Baseline-ready infra, GDScript hygiene, CLI, git helper, and Godot IPC smoke checks."""

    session: E2ESession
    batch: SdkBatchSummary | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = E2ESession(name_prefix="tier0")
        cls.session.setup(require_godot=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.session.cleanup()

    def test_t0_01_env_config_and_workspace_isolation(self) -> None:
        cfg = load_workspace_config()
        self.assertTrue(cfg.build_dir.is_relative_to(WORKSPACE_ROOT.resolve()))
        self.assertTrue(cfg.cache_dir.is_relative_to(WORKSPACE_ROOT.resolve()))
        assert self.session.run_dir is not None
        self.assertTrue(self.session.run_dir.is_relative_to(WORKSPACE_ROOT.resolve()))
        for sub in ("build", "cache", "mods", "probe_project", "isolated_env"):
            self.assertTrue((self.session.run_dir / sub).is_dir(), f"Missing isolated dir: {sub}")

        agents_md = WORKSPACE_ROOT / "AGENTS.md"
        assert_no_local_paths_in_text(self, agents_md.read_text(encoding="utf-8"), label="AGENTS.md")

    def test_t0_02_baseline_gdscript_hygiene(self) -> None:
        cfg = load_workspace_config()
        gd_files = sorted(cfg.sdk_dir.rglob("*.gd"))
        self.assertGreaterEqual(len(gd_files), 6)
        for gd in gd_files:
            assert_gdscript_hygiene(self, gd, sdk_root=cfg.sdk_dir)

    def test_t0_03_cli_validate_and_build_template_isolated(self) -> None:
        assert self.session.build_dir is not None and self.session.cache_dir is not None
        res_val = run_fuvtt_cli(
            ["validate", "_template"],
            build_dir=self.session.build_dir,
            cache_dir=self.session.cache_dir,
        )
        self.assertEqual(res_val.returncode, 0, f"validate _template failed: {res_val.stdout}\n{res_val.stderr}")

        res_bld = run_fuvtt_cli(
            ["build", "_template"],
            build_dir=self.session.build_dir,
            cache_dir=self.session.cache_dir,
        )
        self.assertEqual(res_bld.returncode, 0, f"build _template failed: {res_bld.stdout}\n{res_bld.stderr}")

        manifest = assert_build_artifact_bundles_sdk(
            self,
            self.session.build_dir,
            "_template",
            expected_sdk_files=("v1.gd", "adapters/host_v1_adapter.gd", "modules/snappy.gd"),
        )
        self.assertEqual(manifest.get("plugin_id"), "template_mod")

    def test_t0_04_isolated_synthetic_mod_init_validate_build(self) -> None:
        iso_cfg = self.session.make_isolated_config()
        res_init = run_fuvtt_cli_isolated_mods(
            ["init", "smoke-synthetic-mod", "--name", "Smoke Synthetic", "--ext", "json"],
            iso_cfg=iso_cfg,
        )
        self.assertEqual(res_init.returncode, 0, f"isolated init failed: {res_init.stdout}\n{res_init.stderr}")
        self.assertFalse((WORKSPACE_ROOT / "mods" / "smoke-synthetic-mod").exists(), "Real mods/ was polluted!")

        res_val = run_fuvtt_cli_isolated_mods(["validate", "smoke-synthetic-mod"], iso_cfg=iso_cfg)
        self.assertEqual(res_val.returncode, 0, f"isolated validate failed: {res_val.stdout}\n{res_val.stderr}")

        res_bld = run_fuvtt_cli_isolated_mods(["build", "smoke-synthetic-mod"], iso_cfg=iso_cfg)
        self.assertEqual(res_bld.returncode, 0, f"isolated build failed: {res_bld.stdout}\n{res_bld.stderr}")
        zip_path = iso_cfg.build_dir / "smoke-synthetic-mod" / "smoke-synthetic-mod.zip"
        self.assertTrue(zip_path.is_file())
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = set(zf.namelist())
        self.assertIn("plugin.json", names)
        self.assertIn("entry.gd", names)
        self.assertIn("lib/fu_sdk/v1.gd", names)
        manifest = json.loads((iso_cfg.build_dir / "smoke-synthetic-mod" / "build-manifest.json").read_text(encoding="utf-8"))
        self.assertIs(manifest.get("sdk_bundled"), True)

    def test_t0_05_readonly_git_helpers_and_gitignore(self) -> None:
        self.assertFalse(is_git_ignored("mods/_template/plugin.json"))
        self.assertTrue(is_git_ignored(".env.local"))
        tracked = list_git_tracked("shared/sdk/fu_sdk/")
        self.assertIn("shared/sdk/fu_sdk/v1.gd", tracked)

    def test_t0_06_godot_batch_probe_baseline_ipc_and_roundtrip(self) -> None:
        probe = GodotBatchProbe(self.session)
        probe.prepare_from_mod("_template", use_real_mods=True)
        batch = probe.run_batch([SdkProbeCaseSpec(case_id="t0_baseline_v13", op="baseline_v13")], timeout_seconds=60)
        self.assertTrue(batch.sdk_loaded)
        self.assertEqual(batch.compile_failures, [])
        self.assertEqual(batch.global_log_errors, [])
        res = batch.results["t0_baseline_v13"]
        data = assert_case_passed(self, res)
        self.assertEqual(data.get("roundtrip_diff"), "")
        self.assertGreater(int(data.get("serialized_bytes", 0)), 0)
        assert_world_v3_invariants(self, data["world"], "t0_baseline_v13")
