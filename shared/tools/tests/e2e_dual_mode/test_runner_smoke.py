"""Pytest-discovered smoke & static-hygiene suite for `e2e_dual_mode`.

Runs Tier 0 baseline smoke checks + runner `--list`/`--dry-run` discovery verification
without executing unimplemented M1-M4 Tier 1-4 tests, keeping `pytest shared/tools/tests/`
green during parallel milestone development.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from e2e_dual_mode.assertions import (  # noqa: E402
    assert_batch_clean,
    assert_case_clean,
    assert_case_passed,
    assert_parity_clean,
    lint_doc_cli_commands,
)
from e2e_dual_mode.harness import (  # noqa: E402
    CliRunner,
    E2ESession,
    FUSBuildParityRunner,
    GodotBatchProbe,
    ProbeBatchSummary,
    ProbeCaseResult,
    ProbeCaseSpec,
    _attribute_logs_by_case,
)
from e2e_dual_mode.tier0_smoke import Tier0SmokeTests  # noqa: E402


E2E_DIR = Path(__file__).resolve().parent
RUNNER = E2E_DIR / "run_e2e.py"


class RunnerDiscoverySmokeTests(unittest.TestCase):
    """Verify `run_e2e.py --list` and `--dry-run` collect all 152 cases cleanly."""

    def test_runner_list_all_tiers_and_counts(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(RUNNER), "--tier", "0", "1", "2", "3", "4", "--list"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Total listed tests (tiers=[0, 1, 2, 3, 4]): 152", proc.stdout)

    def test_runner_dry_run_default_tiers(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(RUNNER), "--dry-run"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Total discovered tests: 147", proc.stdout)


class BatchLogAttributionAndAssertionsTests(unittest.TestCase):
    """Pure-Python regression tests for global log attribution, assertions, and batch isolation."""

    def test_attribute_logs_separates_exit_leaks_and_stderr_into_global_errors(self) -> None:
        stdout_text = (
            "=== E2E_CASE_START c1 ===\n"
            "ok\n"
            "=== E2E_CASE_END c1 ===\n"
            "WARNING: 2 ObjectDB instances leaked at exit (use --verbose to see leaked instances).\n"
        )
        godot_log_text = (
            "=== E2E_CASE_START c1 ===\n"
            "=== E2E_CASE_END c1 ===\n"
        )
        stderr_text = "ERROR: Top-level stderr failure\n"

        per_case, global_errs = _attribute_logs_by_case(stdout_text, godot_log_text, stderr_text)
        self.assertEqual(per_case.get("c1"), [])
        self.assertEqual(len(global_errs), 2)
        self.assertTrue(any("ObjectDB instances leaked at exit" in e for e in global_errs))
        self.assertTrue(any("Top-level stderr failure" in e for e in global_errs))

    def test_assert_case_clean_and_passed_reject_global_errors_compile_failures_and_exit_code(self) -> None:
        clean_res = ProbeCaseResult(
            case_id="c_ok",
            completed=True,
            crashed_or_timed_out=False,
            ok=True,
            data={"v": 1},
            gd_check_failures=[],
            log_errors=[],
            exit_code=0,
        )
        assert_case_clean(self, clean_res)
        self.assertEqual(assert_case_passed(self, clean_res), {"v": 1})

        # Non-zero exit code rejected
        bad_exit = ProbeCaseResult(
            case_id="c_exit",
            completed=True,
            crashed_or_timed_out=False,
            ok=True,
            data={},
            gd_check_failures=[],
            log_errors=[],
            exit_code=1,
        )
        with self.assertRaises(AssertionError):
            assert_case_clean(self, bad_exit)
        with self.assertRaises(AssertionError):
            assert_case_passed(self, bad_exit)

        # Result-level global_log_errors rejected
        bad_global = ProbeCaseResult(
            case_id="c_glob",
            completed=True,
            crashed_or_timed_out=False,
            ok=True,
            data={},
            gd_check_failures=[],
            log_errors=[],
            global_log_errors=["WARNING: 1 ObjectDB instances leaked at exit"],
        )
        with self.assertRaises(AssertionError):
            assert_case_clean(self, bad_global)
        with self.assertRaises(AssertionError):
            assert_case_passed(self, bad_global)

        # Result-level compile_failures rejected
        bad_compile = ProbeCaseResult(
            case_id="c_comp",
            completed=True,
            crashed_or_timed_out=False,
            ok=True,
            data={},
            gd_check_failures=[],
            log_errors=[],
            compile_failures=["res://broken.gd:1: Parse Error"],
        )
        with self.assertRaises(AssertionError):
            assert_case_clean(self, bad_compile)
        with self.assertRaises(AssertionError):
            assert_case_passed(self, bad_compile)

        # Summary-level global_log_errors / compile_failures rejected even if clean_res lacks them
        bad_summary = ProbeBatchSummary(
            loaded_scripts=[],
            compile_failures=[],
            global_log_errors=["ERROR: stderr boom"],
            results={"c_ok": clean_res},
        )
        with self.assertRaises(AssertionError):
            assert_case_clean(self, clean_res, summary=bad_summary)
        with self.assertRaises(AssertionError):
            assert_case_passed(self, clean_res, summary=bad_summary)
        with self.assertRaises(AssertionError):
            assert_batch_clean(self, bad_summary)

    def test_mocked_run_batch_propagates_global_errors_and_uses_monotonic_batch_dirs(self) -> None:
        session = E2ESession(name_prefix="smoke_mock")
        session.setup(require_godot=False)
        try:
            seen_sub_ids: list[str] = []

            def _fake_invoke(
                probe_self: GodotBatchProbe,
                sub_id: str,
                cases: list[ProbeCaseSpec],
                *,
                timeout_seconds: int,
            ) -> tuple[int, bool, dict[str, object], str, str, str, Path]:
                del timeout_seconds
                seen_sub_ids.append(sub_id)
                assert probe_self.session.run_dir is not None
                out_dir = probe_self.session.run_dir / "batches" / sub_id / "out"
                out_dir.mkdir(parents=True, exist_ok=True)
                for c in cases:
                    (out_dir / f"{c.case_id}.json").write_text(
                        json.dumps({"ok": True, "data": {"id": c.case_id}, "gd_check_failures": []}),
                        encoding="utf-8",
                    )
                stdout_txt = (
                    f"=== E2E_CASE_START {cases[0].case_id} ===\n"
                    f"=== E2E_CASE_END {cases[0].case_id} ===\n"
                    "WARNING: 1 ObjectDB instances leaked at exit\n"
                )
                return (
                    0,
                    False,
                    {"loaded_scripts": [], "compile_failures": ["res://bad.gd: compile failed"]},
                    stdout_txt,
                    "",
                    "",
                    out_dir,
                )

            probe1 = GodotBatchProbe(session)
            probe1.staged = True
            probe2 = GodotBatchProbe(session)
            probe2.staged = True

            with mock.patch.object(GodotBatchProbe, "_invoke_godot", autospec=True, side_effect=_fake_invoke):
                s1 = probe1.run_batch([ProbeCaseSpec(case_id="m1", op="noop")])
                s2 = probe2.run_batch([ProbeCaseSpec(case_id="m2", op="noop")])

            self.assertEqual(seen_sub_ids, ["b000", "b001"])
            r1 = s1.results["m1"]
            self.assertTrue(any("ObjectDB instances leaked at exit" in e for e in r1.global_log_errors))
            self.assertEqual(r1.compile_failures, ["res://bad.gd: compile failed"])
            with self.assertRaises(AssertionError):
                assert_case_passed(self, r1)
            with self.assertRaises(AssertionError):
                assert_batch_clean(self, s2)
        finally:
            session.cleanup()

    def test_assert_parity_clean_accepts_clean_and_rejects_log_errors_or_bad_status(self) -> None:
        clean = {
            "returncode": 0,
            "log_errors": [],
            "result": {"ok": True, "mode": "zip_direct"},
            "stdout": "",
            "stderr": "",
        }
        self.assertEqual(assert_parity_clean(self, clean, expected_mode="zip_direct"), {"ok": True, "mode": "zip_direct"})

        for bad in (
            {**clean, "log_errors": ["WARNING: 1 ObjectDB instances leaked at exit"]},
            {**clean, "log_errors": ["SCRIPT ERROR: bad script"]},
            {**clean, "returncode": 1},
            {**clean, "result": {"ok": False}},
            {**clean, "result": {"ok": True, "mode": "pck"}},
        ):
            with self.assertRaises(AssertionError):
                assert_parity_clean(self, bad, expected_mode="zip_direct")

    def test_fus_build_parity_runner_captures_log_errors_monotonic_logs_and_timeout(self) -> None:
        session = E2ESession(name_prefix="smoke_parity")
        session.setup(require_godot=False)
        try:
            assert session.run_dir is not None
            fake_fus = session.run_dir / "fake_fus"
            (fake_fus / "tools").mkdir(parents=True, exist_ok=True)
            (fake_fus / "tools" / "build_world_plugin.gd").write_text("extends SceneTree\n", encoding="utf-8")
            fake_godot = session.run_dir / "godot_console.exe"
            fake_godot.write_bytes(b"")
            src_mod = session.run_dir / "src_mod"
            src_mod.mkdir(parents=True, exist_ok=True)
            out_dir = session.run_dir / "out_parity"

            calls: list[list[str]] = []

            def _fake_run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(list(cmd))
                log_idx = cmd.index("--log-file") + 1
                log_path = Path(cmd[log_idx])
                if len(calls) == 1:
                    log_path.write_text("SCRIPT ERROR: leak in build_world_plugin\n", encoding="utf-8")
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        stdout='{"ok": true, "mode": "zip_direct"}\nWARNING: 1 ObjectDB instances leaked at exit\n',
                        stderr="",
                    )
                raise subprocess.TimeoutExpired(cmd=cmd, timeout=5, output="", stderr="timed out")

            runner = FUSBuildParityRunner(session)
            with (
                mock.patch("e2e_dual_mode.harness.resolve_fus_repo_or_skip", return_value=fake_fus),
                mock.patch("e2e_dual_mode.harness.resolve_godot_or_skip", return_value=fake_godot),
                mock.patch("e2e_dual_mode.harness.subprocess.run", side_effect=_fake_run),
            ):
                p1 = runner.run_build_world_plugin(src_mod, out_dir)
                p2 = runner.run_build_world_plugin(src_mod, out_dir, timeout_seconds=5)

            self.assertEqual(p1["returncode"], 0)
            self.assertTrue(any("SCRIPT ERROR" in e for e in p1["log_errors"]))
            self.assertTrue(any("ObjectDB instances leaked at exit" in e for e in p1["log_errors"]))
            with self.assertRaises(AssertionError):
                assert_parity_clean(self, p1)

            self.assertEqual(p2["returncode"], 124)
            self.assertTrue(any("timed out" in e for e in p2["log_errors"]))
            with self.assertRaises(AssertionError):
                assert_parity_clean(self, p2)

            self.assertNotEqual(p1["log_file"], p2["log_file"])
            self.assertIn("p000", str(p1["log_file"]))
            self.assertIn("p001", str(p2["log_file"]))
        finally:
            session.cleanup()

    def test_cli_result_preserves_raw_output_while_redacting_stdout_stderr(self) -> None:
        session = E2ESession(name_prefix="smoke_cli_raw")
        session.setup(require_godot=False)
        try:
            assert session.run_dir is not None
            fake_fus = (session.run_dir / "SecretFusRepo").resolve()
            fake_fus.mkdir(parents=True, exist_ok=True)
            session.cfg = session.cfg.__class__(
                workspace_root=session.cfg.workspace_root,
                mods_dir=session.cfg.mods_dir,
                sdk_dir=session.cfg.sdk_dir,
                build_dir=session.cfg.build_dir,
                cache_dir=session.cfg.cache_dir,
                fuvtt_install_dir=session.cfg.fuvtt_install_dir,
                fuvtt_mods_subdir=session.cfg.fuvtt_mods_subdir,
                fus_repo_dir=fake_fus,
                fus_source_ref=session.cfg.fus_source_ref,
                godot_bin=session.cfg.godot_bin,
            )
            cli = CliRunner(session)
            leaked_out = f"using {fake_fus}\\tools\\build.gd\n"
            leaked_err = f"err {fake_fus}/file.gd\n"

            with mock.patch(
                "e2e_dual_mode.harness.subprocess.run",
                return_value=subprocess.CompletedProcess(["python"], 0, stdout=leaked_out, stderr=leaked_err),
            ):
                r_real = cli.run_real(["validate", "_template"])
                r_iso = cli.run_isolated(["validate", "_template"])

            for res in (r_real, r_iso):
                self.assertEqual(res.raw_stdout, leaked_out)
                self.assertEqual(res.raw_stderr, leaked_err)
                self.assertIn("<FUS_REPO_DIR>", res.stdout)
                self.assertIn("<FUS_REPO_DIR>", res.stderr)
                self.assertNotIn("SecretFusRepo", res.stdout)
                self.assertNotIn("SecretFusRepo", res.stderr)
        finally:
            session.cleanup()


class LintDocCliCommandsTests(unittest.TestCase):
    """Regression tests for multi-line `\\` continuations and `|` / `||` / `&&` / `;` chains."""

    VALID_FLAGS: dict[str, set[str]] = {
        "init": {"--mode", "--name", "--help"},
        "validate": {"--all", "--include-template", "--help"},
        "build": {"--no-sdk", "--help"},
    }

    def test_multiline_backslash_bogus_flag_rejected_and_valid_accepted(self) -> None:
        bad_doc = (
            "```bash\n"
            "python shared/tools/fuvtt_cli.py init my-mod \\\n"
            "  --bogus-multiline-flag\n"
            "```\n"
        )
        with self.assertRaises(AssertionError):
            lint_doc_cli_commands(self, bad_doc, self.VALID_FLAGS, label="multiline_bad")

        good_doc = (
            "```bash\n"
            "python shared/tools/fuvtt_cli.py init my-mod \\\n"
            "  --mode desktop-module \\\n"
            "  --name Demo\n"
            "```\n"
        )
        checked = lint_doc_cli_commands(self, good_doc, self.VALID_FLAGS, label="multiline_good")
        self.assertEqual(checked, 1)

    def test_pipe_and_or_chains_do_not_misattribute_flags(self) -> None:
        pipe_doc = "```bash\npython shared/tools/fuvtt_cli.py init my-mod | grep --color=never ok\n```\n"
        self.assertEqual(
            lint_doc_cli_commands(self, pipe_doc, self.VALID_FLAGS, label="pipe_valid"),
            1,
        )

        or_doc = (
            "```bash\n"
            "python shared/tools/fuvtt_cli.py validate my-mod || python shared/tools/fuvtt_cli.py init my-mod --mode desktop-module\n"
            "```\n"
        )
        self.assertEqual(
            lint_doc_cli_commands(self, or_doc, self.VALID_FLAGS, label="or_valid"),
            2,
        )

        or_bad = (
            "```bash\n"
            "python shared/tools/fuvtt_cli.py validate my-mod || python shared/tools/fuvtt_cli.py init my-mod --bogus-or-flag\n"
            "```\n"
        )
        with self.assertRaises(AssertionError):
            lint_doc_cli_commands(self, or_bad, self.VALID_FLAGS, label="or_bad")

    def test_even_trailing_backslashes_not_joined_as_continuation(self) -> None:
        doc = (
            "```powershell\n"
            "echo C:\\\\path\\\\\n"
            "python shared/tools/fuvtt_cli.py init my-mod --mode desktop-module\n"
            "```\n"
        )
        self.assertEqual(
            lint_doc_cli_commands(self, doc, self.VALID_FLAGS, label="even_bs"),
            1,
        )
