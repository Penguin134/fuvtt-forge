"""Opaque-box 4-tier E2E test entrypoint for `mods/fvtt-world-importer/` (`fvtt_world_importer`).

Usage:
  python shared/tools/tests/test_e2e_fvtt_world_importer.py --smoke -v
  python shared/tools/tests/test_e2e_fvtt_world_importer.py --tier 1 -v
  python shared/tools/tests/test_e2e_fvtt_world_importer.py --tier 1 2
  python -m unittest discover -s shared/tools/tests
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import unittest

TESTS_DIR = Path(__file__).resolve().parent
TOOLS_DIR = TESTS_DIR.parent
for p in (str(TESTS_DIR), str(TOOLS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from e2e_fvtt_importer.tier0_smoke import Tier0HarnessSmokeTests  # noqa: E402
from e2e_fvtt_importer.tier1_features import Tier1FeatureTests  # noqa: E402
from e2e_fvtt_importer.tier2_boundaries import Tier2BoundaryTests  # noqa: E402
from e2e_fvtt_importer.tier3_combinations import Tier3CombinationTests  # noqa: E402
from e2e_fvtt_importer.tier4_workloads import Tier4WorkloadTests  # noqa: E402


_TIER_CLASSES: dict[int, type[unittest.TestCase]] = {
    0: Tier0HarnessSmokeTests,
    1: Tier1FeatureTests,
    2: Tier2BoundaryTests,
    3: Tier3CombinationTests,
    4: Tier4WorkloadTests,
}


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: str) -> unittest.TestSuite:
    """Custom unittest loader supporting optional `FUVTT_E2E_TIERS` env var (defaults to all 0..4)."""
    raw_env = os.environ.get("FUVTT_E2E_TIERS", "").strip()
    if raw_env:
        selected = sorted({int(x.strip()) for x in raw_env.split(",") if x.strip()})
    else:
        selected = [0, 1, 2, 3, 4]

    suite = unittest.TestSuite()
    for tier_num in selected:
        cls = _TIER_CLASSES.get(tier_num)
        if cls is not None:
            suite.addTests(loader.loadTestsFromTestCase(cls))
    return suite


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--smoke", action="store_true", help="Run Tier 0 harness & probe smoke checks only.")
    parser.add_argument(
        "--tier",
        nargs="+",
        type=int,
        action="append",
        default=[],
        help="Select E2E tier(s) 1..4 to execute (always includes Tier 0 smoke).",
    )
    known, remaining = parser.parse_known_args(argv)

    if known.smoke:
        selected = [0]
    elif known.tier:
        tiers = {t for group in known.tier for t in group}
        selected = sorted({0} | tiers)
    else:
        selected = [0, 1, 2, 3, 4]

    os.environ["FUVTT_E2E_TIERS"] = ",".join(str(t) for t in selected)
    program = unittest.main(
        module=__name__,
        argv=[sys.argv[0], *remaining],
        exit=False,
    )
    return 0 if program.result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(_main())
