"""Tier 0: Harness, Build, Compile, LevelDB Self-Check, and Godot IPC Smoke Tests."""

from __future__ import annotations

import json
import unittest
import zipfile

from . import DEFAULT_OPTIONS
from .assertions import (
    assert_case_clean,
    assert_valid_inspect_ok,
    assert_valid_practice_world_v3,
)
from .fixtures import (
    build_v9_world,
    decode_leveldb_collection,
    make_png_bytes,
    make_v9_world_json,
    make_webp_bytes,
    snappy_compress,
    snappy_decompress,
    write_leveldb_collection,
)
from .harness import (
    BatchExecutionSummary,
    ProbeCaseSpec,
    ProbeSession,
    build_and_validate_plugin,
)


class Tier0HarnessSmokeTests(unittest.TestCase):
    """Verifies build, packaging, fixture roundtrips, and headless Godot IPC (passes on M1)."""

    session: ProbeSession
    batch: BatchExecutionSummary
    sample_world_json = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = ProbeSession(name_prefix="tier0")
        cls.session.setup(require_godot=True)
        assert cls.session.fixture_dir is not None

        wdir = cls.session.fixture_dir / "smoke_world"
        cls.sample_world_json = build_v9_world(
            wdir,
            world_json=make_v9_world_json(name="smoke", title="Smoke Test"),
        )

        cases = [
            ProbeCaseSpec(
                case_id="t0_baseline",
                sample_path=cls.sample_world_json.as_posix(),
                options=dict(DEFAULT_OPTIONS),
            ),
            ProbeCaseSpec(
                case_id="t0_cancel_immediate",
                sample_path=cls.sample_world_json.as_posix(),
                options={"import_scenes": float("nan"), "proxy": float("inf")},
                cancel_policy="immediate",
            ),
        ]
        cls.batch = cls.session.run_batch(cases, timeout_seconds=60)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.session.cleanup()

    def test_t0_01_static_validate_and_build_zip(self) -> None:
        _, artifact = build_and_validate_plugin()
        self.assertTrue(artifact.zip_path.is_file())
        with zipfile.ZipFile(artifact.zip_path, "r") as zf:
            names = set(zf.namelist())
        self.assertIn("plugin.json", names)
        self.assertIn("entry.gd", names)
        self.assertIn("lib/fu_sdk/v1.gd", names)

    def test_t0_02_leveldb_snappy_and_image_fixtures_self_check(self) -> None:
        png = make_png_bytes(4, 4)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        webp = make_webp_bytes()
        self.assertEqual(webp[:4], b"RIFF")
        self.assertEqual(webp[8:16], b"WEBPVP8L")

        # Snappy compress/decompress roundtrip on repetitive JSON
        sample_json = (json.dumps({"_id": "abc", "name": "Goblin", "tags": ["npc", "npc", "npc"]}) * 15).encode("utf-8")
        compressed = snappy_compress(sample_json)
        self.assertLess(len(compressed), len(sample_json))
        self.assertEqual(snappy_decompress(compressed), sample_json)

        # LevelDB .ldb + .log WAL Put/Delete roundtrip
        assert self.session.fixture_dir is not None
        coll = self.session.fixture_dir / "selfcheck_ldb"
        write_leveldb_collection(
            coll,
            ldb_records=[
                (b"!scenes!s1", 1, 1, b'{"_id":"s1","name":"Base"}'),
                (b"!scenes!s2", 2, 1, b'{"_id":"s2","name":"ToDelete"}'),
            ],
            wal_batches=[
                (
                    10,
                    [
                        ("put", b"!scenes!s1", b'{"_id":"s1","name":"WAL_Updated"}'),
                        ("delete", b"!scenes!s2", b""),
                        ("put", b"!scenes!s3", b'{"_id":"s3","name":"WAL_Added"}'),
                    ],
                )
            ],
        )
        decoded = decode_leveldb_collection(coll)
        self.assertEqual(decoded[b"!scenes!s1"], b'{"_id":"s1","name":"WAL_Updated"}')
        self.assertEqual(decoded[b"!scenes!s3"], b'{"_id":"s3","name":"WAL_Added"}')
        self.assertNotIn(b"!scenes!s2", decoded)

    def test_t0_03_godot_probe_compiles_all_packaged_gdscripts(self) -> None:
        self.assertEqual(self.batch.compile_failures, [])
        self.assertTrue(self.batch.entry_valid)
        self.assertGreaterEqual(len(self.batch.loaded_scripts), 3)
        self.assertEqual(self.batch.global_log_errors, [])

    def test_t0_04_godot_probe_baseline_inspect_and_prepare_ipc(self) -> None:
        res = self.batch.results["t0_baseline"]
        assert_case_clean(self, res)
        assert_valid_inspect_ok(self, res, self.sample_world_json)
        assert_valid_practice_world_v3(self, res)
        self.assertGreater(res.prepare_meta.get("serialized_bytes", 0), 0)

    def test_t0_05_godot_probe_cancel_and_special_float_options(self) -> None:
        res = self.batch.results["t0_cancel_immediate"]
        assert_case_clean(self, res)
        self.assertEqual(res.inspect_result, {"ok": False, "reason": "cancelled"})
        self.assertEqual(res.prepare_result, {"ok": False, "reason": "cancelled"})
