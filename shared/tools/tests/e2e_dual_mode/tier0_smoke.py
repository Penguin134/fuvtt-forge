"""Tier 0: Baseline-ready Env, Isolation, v1 Compat, Hygiene & Suite Discovery Smoke Tests (5 cases)."""

from __future__ import annotations

import json
import unittest
import zipfile

from .assertions import (
    assert_fu_sdk_35_invariance,
    assert_fus_repo_clean,
    assert_gdscript_hygiene,
    assert_no_local_paths_in_text,
)
from .harness import (
    WORKSPACE_ROOT,
    CliRunner,
    E2ESession,
    resolve_godot_or_skip,
)


class Tier0SmokeTests(unittest.TestCase):
    """5 baseline smoke checks guaranteed to pass without unimplemented M1-M4 deliverables."""

    session: E2ESession

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = E2ESession(name_prefix="tier0")
        cls.session.setup(require_godot=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.session.cleanup()

    def test_t0_01_env_config_and_isolation_paths(self) -> None:
        cfg = self.session.cfg
        self.assertTrue(cfg.build_dir.is_relative_to(WORKSPACE_ROOT.resolve()))
        self.assertTrue(cfg.cache_dir.is_relative_to(WORKSPACE_ROOT.resolve()))
        assert self.session.run_dir is not None
        self.assertTrue(self.session.run_dir.is_relative_to(WORKSPACE_ROOT.resolve()))
        for sub in ("build", "cache", "mods", "probe_project", "extracted", "target_plugins", "isolated_env"):
            self.assertTrue((self.session.run_dir / sub).is_dir(), f"Missing isolated dir: {sub}")
        assert_fu_sdk_35_invariance(self, cfg.sdk_dir)

    def test_t0_02_cli_help_and_baseline_v1_validate_build(self) -> None:
        cli = CliRunner(self.session)
        help_res = cli.run_real(["--help"])
        self.assertEqual(help_res.returncode, 0, help_res.stderr)
        for subcmd in ("init", "validate", "build", "sync", "serve", "inspect-client", "verify-host"):
            self.assertIn(subcmd, help_res.stdout)

        for mod_name in ("_template", "sdk-log-console"):
            v_res = cli.run_real(["validate", mod_name])
            self.assertEqual(v_res.returncode, 0, f"validate {mod_name} failed:\n{v_res.stdout}\n{v_res.stderr}")
            b_res = cli.run_real(["build", mod_name])
            self.assertEqual(b_res.returncode, 0, f"build {mod_name} failed:\n{b_res.stdout}\n{b_res.stderr}")
            assert self.session.build_dir is not None
            zip_path = self.session.build_dir / mod_name / f"{mod_name}.zip"
            self.assertTrue(zip_path.is_file(), f"Missing built v1 ZIP: {zip_path}")
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = set(zf.namelist())
                self.assertIn("plugin.json", names)
                self.assertIn("entry.gd", names)
                self.assertIn("lib/fu_sdk/v1.gd", names)

    def test_t0_03_v1_verify_host_template_and_log_console(self) -> None:
        godot_bin = resolve_godot_or_skip(self.session.cfg)
        cli = CliRunner(self.session)
        for mod_name in ("_template", "sdk-log-console"):
            vh = cli.run_real(["verify-host", mod_name, "--godot-bin", str(godot_bin)], timeout=180)
            self.assertEqual(vh.returncode, 0, f"verify-host {mod_name} failed:\n{vh.stdout}\n{vh.stderr}")
            assert self.session.build_dir is not None
            report_path = self.session.build_dir / mod_name / "verify_evidence"
            reports = list(report_path.glob("*/verify-report.json"))
            self.assertTrue(reports, f"Missing verify-report.json for {mod_name}")
            rep = json.loads(reports[-1].read_text(encoding="utf-8"))
            self.assertIs(rep.get("ok"), True, f"verify-report ok != True for {mod_name}: {rep}")

    def test_t0_04_e2e_dual_mode_hygiene_and_fus_repo_readonly(self) -> None:
        pkg_dir = WORKSPACE_ROOT / "shared" / "tools" / "tests" / "e2e_dual_mode"
        for py_file in sorted(pkg_dir.glob("*.py")):
            raw = py_file.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"UTF-8 BOM in {py_file.name}")
            self.assertNotIn(b"\r\n", raw, f"CRLF in {py_file.name}")
            text = raw.decode("utf-8")
            assert_no_local_paths_in_text(self, text, label=py_file.name)

        for gd_file in sorted(pkg_dir.glob("*.gd")):
            assert_gdscript_hygiene(self, gd_file, require_extends_refcounted=False, forbid_class_name=True, forbid_preload=False)

        assert_fus_repo_clean(self, self.session.cfg.fus_repo_dir)

    def test_t0_05_tier1_to_tier4_discovery_and_counts(self) -> None:
        from .tier1_features import Tier1FeatureTests
        from .tier2_boundaries import Tier2BoundaryTests
        from .tier3_combinations import Tier3CombinationTests
        from .tier4_scenarios import Tier4ScenarioTests

        loader = unittest.TestLoader()
        t1 = loader.loadTestsFromTestCase(Tier1FeatureTests).countTestCases()
        t2 = loader.loadTestsFromTestCase(Tier2BoundaryTests).countTestCases()
        t3 = loader.loadTestsFromTestCase(Tier3CombinationTests).countTestCases()
        t4 = loader.loadTestsFromTestCase(Tier4ScenarioTests).countTestCases()
        self.assertEqual(t1, 85, f"Expected 85 Tier 1 cases (5x17), got {t1}")
        self.assertEqual(t2, 34, f"Expected 34 Tier 2 cases (2x17), got {t2}")
        self.assertEqual(t3, 16, f"Expected 16 Tier 3 cases, got {t3}")
        self.assertEqual(t4, 12, f"Expected 12 Tier 4 cases, got {t4}")
        self.assertEqual(t1 + t2 + t3 + t4, 147)
