#!/usr/bin/env python3
"""Dedicated opaque-box E2E test runner for Dual-Mode Fu vtt SDK, CLI, Templates & Wiki.

Usage:
  python shared/tools/tests/e2e_dual_mode/run_e2e.py --list
  python shared/tools/tests/e2e_dual_mode/run_e2e.py --dry-run
  python shared/tools/tests/e2e_dual_mode/run_e2e.py --smoke --require-godot -v
  python shared/tools/tests/e2e_dual_mode/run_e2e.py --tier 1 2 3 4 --require-godot
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fnmatch
import json
import os
from pathlib import Path
import re
import sys
import unittest
from typing import Sequence


E2E_DIR = Path(__file__).resolve().parent
TESTS_DIR = E2E_DIR.parent
TOOLS_DIR = TESTS_DIR.parent
WORKSPACE_ROOT = TOOLS_DIR.parents[1]

for _p in (str(TESTS_DIR), str(TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from e2e_dual_mode.harness import WORKSPACE_ROOT as HARNESS_WS_ROOT, load_workspace_config  # noqa: E402
from e2e_dual_mode.tier0_smoke import Tier0SmokeTests  # noqa: E402
from e2e_dual_mode.tier1_features import Tier1FeatureTests  # noqa: E402
from e2e_dual_mode.tier2_boundaries import Tier2BoundaryTests  # noqa: E402
from e2e_dual_mode.tier3_combinations import Tier3CombinationTests  # noqa: E402
from e2e_dual_mode.tier4_scenarios import Tier4ScenarioTests  # noqa: E402


TIER_CLASSES: dict[int, tuple[str, type[unittest.TestCase]]] = {
    0: ("Tier 0: Baseline Infra, Hygiene, CLI & v1 Compat Smoke", Tier0SmokeTests),
    1: ("Tier 1: Per-Feature Functional Acceptance (#1-#17)", Tier1FeatureTests),
    2: ("Tier 2: Boundary & Negative/Rejection Matrix (#1-#17)", Tier2BoundaryTests),
    3: ("Tier 3: Cross-Feature Combinatorial Integration", Tier3CombinationTests),
    4: ("Tier 4: Real-World End-to-End & Shadow Host-Load Workflows", Tier4ScenarioTests),
}


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


def _iter_tests(suite: unittest.TestSuite) -> list[unittest.TestCase]:
    out: list[unittest.TestCase] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            out.extend(_iter_tests(item))
        else:
            out.append(item)
    return out


def _matches_pattern(test_id: str, pattern: str | None) -> bool:
    if not pattern:
        return True
    pat = pattern.strip()
    if not pat:
        return True
    terms = [t.strip() for t in re.split(r"\s+or\s+", pat) if t.strip()]
    tid_lower = test_id.lower()
    for term in terms:
        if any(ch in term for ch in ("*", "?", "[")):
            if fnmatch.fnmatch(tid_lower, term.lower()):
                return True
        elif term.lower() in tid_lower:
            return True
    return False


def _collect_suite(selected_tiers: list[int], pattern: str | None) -> tuple[unittest.TestSuite, dict[int, list[str]]]:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    by_tier: dict[int, list[str]] = {}
    for tier_num in selected_tiers:
        _, cls = TIER_CLASSES[tier_num]
        raw_tier_suite = loader.loadTestsFromTestCase(cls)
        matched_ids: list[str] = []
        filtered = unittest.TestSuite()
        for tc in _iter_tests(raw_tier_suite):
            tid = tc.id()
            if _matches_pattern(tid, pattern):
                filtered.addTest(tc)
                matched_ids.append(tid)
        by_tier[tier_num] = matched_ids
        if matched_ids:
            suite.addTest(filtered)
    return suite, by_tier


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_e2e.py",
        description="Opaque-box 4-tier E2E test runner for Fu vtt Dual-Mode SDK, CLI, Templates & Wiki.",
    )
    parser.add_argument(
        "--tier",
        nargs="+",
        type=int,
        action="append",
        choices=(0, 1, 2, 3, 4),
        default=[],
        help="Select tier(s) 0..4 to run (default: 1 2 3 4).",
    )
    parser.add_argument("--smoke", action="store_true", help="Run Tier 0 baseline smoke checks only.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify config, workspace boundaries, and test discovery without executing tests.",
    )
    parser.add_argument("--list", action="store_true", help="List all matching test IDs grouped by tier and exit 0.")
    parser.add_argument(
        "--require-godot",
        action="store_true",
        help="Fail loudly if GODOT_BIN is unavailable or any test is skipped.",
    )
    parser.add_argument(
        "--require-fus-mirror",
        action="store_true",
        help="Fail loudly if FUS_REPO_DIR or dotnet CLI is unavailable for shadow host-load tests.",
    )
    parser.add_argument(
        "--keep-evidence",
        action="store_true",
        help="Preserve .cache/test_tmp/e2e_dual_mode/<run_id>/ artifacts after run.",
    )
    parser.add_argument("-k", "--pattern", default=None, help="Filter test IDs by substring or glob pattern.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose unittest output.")
    parser.add_argument("--json-report", metavar="PATH", help="Write structured JSON report (inside workspace).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.smoke and args.tier:
        print("[ERROR] --smoke cannot be combined with --tier.", file=sys.stderr)
        return 2

    if args.smoke:
        selected_tiers = [0]
    elif args.tier:
        selected_tiers = sorted({t for grp in args.tier for t in grp})
    else:
        selected_tiers = [1, 2, 3, 4]

    try:
        cfg = load_workspace_config()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Failed to load workspace config: {exc}", file=sys.stderr)
        return 1

    report_path: Path | None = None
    if args.json_report:
        cand = Path(args.json_report)
        if not cand.is_absolute():
            cand = (WORKSPACE_ROOT / cand).resolve()
        else:
            cand = cand.resolve()
        if not cand.is_relative_to(HARNESS_WS_ROOT.resolve()):
            print(f"[ERROR] --json-report path must stay inside workspace: {cfg.redact_path(cand)}", file=sys.stderr)
            return 2
        report_path = cand

    suite, by_tier = _collect_suite(selected_tiers, args.pattern)
    total_count = sum(len(v) for v in by_tier.values())

    if args.list:
        for t in selected_tiers:
            title, _ = TIER_CLASSES[t]
            ids = by_tier.get(t, [])
            print(f"=== {title} ({len(ids)} tests) ===")
            for tid in ids:
                print(f"  {tid}")
        print(f"Total listed tests (tiers={selected_tiers}): {total_count}")
        return 0

    if args.dry_run:
        godot_status = "configured" if (cfg.godot_bin and cfg.godot_bin.is_file()) else "missing"
        fus_status = "configured" if (cfg.fus_repo_dir and cfg.fus_repo_dir.is_dir()) else "missing"
        print(f"[DRY-RUN] workspace={cfg.workspace_root.name}, godot={godot_status}, fus_repo={fus_status}")
        for t in selected_tiers:
            title, _ = TIER_CLASSES[t]
            print(f"[DRY-RUN] {title}: {len(by_tier.get(t, []))} tests")
        print(f"[DRY-RUN] Total discovered tests: {total_count}")
        if args.pattern and total_count == 0:
            print(f"[ERROR] No tests matched pattern -k {args.pattern!r} in tiers {selected_tiers}.", file=sys.stderr)
            return 2
        if args.require_godot and godot_status != "configured":
            print("[ERROR] --require-godot specified but GODOT_BIN is missing.", file=sys.stderr)
            return 1
        if args.require_fus_mirror and fus_status != "configured":
            print("[ERROR] --require-fus-mirror specified but FUS_REPO_DIR is missing.", file=sys.stderr)
            return 1
        return 0

    if total_count == 0:
        msg = (
            f"[ERROR] No tests matched pattern -k {args.pattern!r} in tiers {selected_tiers}."
            if args.pattern
            else f"[ERROR] Zero tests collected for tiers {selected_tiers}."
        )
        print(msg, file=sys.stderr)
        return 2

    if args.require_godot:
        os.environ["FUVTT_E2E_REQUIRE_GODOT"] = "1"
    if args.require_fus_mirror:
        os.environ["FUVTT_E2E_REQUIRE_FUS_MIRROR"] = "1"
    if args.keep_evidence:
        os.environ["FUVTT_E2E_KEEP_EVIDENCE"] = "1"

    runner = unittest.TextTestRunner(
        stream=sys.stdout,
        verbosity=2 if args.verbose else 1,
    )
    result = runner.run(suite)

    skipped_count = len(result.skipped)
    require_no_skips = args.require_godot or args.require_fus_mirror
    passed = result.wasSuccessful() and result.testsRun > 0 and (not require_no_skips or skipped_count == 0)

    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tiers": selected_tiers,
            "total": result.testsRun,
            "failures": [
                {"test": tc.id(), "trace": cfg.redact_path(tb)}
                for tc, tb in result.failures
            ],
            "errors": [
                {"test": tc.id(), "trace": cfg.redact_path(tb)}
                for tc, tb in result.errors
            ],
            "skipped": [
                {"test": tc.id(), "reason": cfg.redact_path(reason)}
                for tc, reason in result.skipped
            ],
            "ok": passed,
        }
        report_path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    if require_no_skips and skipped_count > 0:
        flags = []
        if args.require_godot:
            flags.append("--require-godot")
        if args.require_fus_mirror:
            flags.append("--require-fus-mirror")
        print(f"[ERROR] {' / '.join(flags)} failed due to {skipped_count} skipped test(s).", file=sys.stderr)
        return 1

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
