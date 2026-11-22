"""Tier 3: 10 Cross-Feature Pairwise Combinatorial Tests (`T3-PW-01` .. `T3-PW-10`, 112/112 pairs)."""

from __future__ import annotations

from pathlib import Path
import unittest

from . import DEFAULT_OPTIONS
from .assertions import (
    assert_actor_preserved,
    assert_valid_inspect_ok,
    assert_valid_practice_world_v3,
    find_actor_records,
    get_component,
    get_entities,
    get_entities_by_layer_kind,
    get_obstacle_entities,
    get_unit_entities,
)
from .fixtures import (
    build_v14_world,
    build_v9_world,
    make_light,
    make_png_bytes,
    make_tile,
    make_v14_world_json,
    make_v9_actor,
    make_v9_scene,
    make_v9_token,
    make_v9_world_json,
    make_wall,
    pack_world_zip,
)
from .harness import BatchExecutionSummary, ProbeCaseSpec, ProbeSession


# (case_id, source_kind, fvtt_version, import_scenes, import_characters, import_monsters, include_hidden, skip_missing_assets, scene_features)
_PAIRWISE_ROWS: tuple[tuple[str, str, str, bool, bool, bool, bool, bool, str], ...] = (
    ("t3_pw_01", "zip", "v9",  True,  True,  True,  True,  True,  "full"),
    ("t3_pw_02", "zip", "v9",  False, True,  False, False, False, "minimal"),
    ("t3_pw_03", "zip", "v14", True,  False, True,  False, False, "minimal"),
    ("t3_pw_04", "zip", "v14", False, False, False, True,  True,  "full"),
    ("t3_pw_05", "dir", "v9",  True,  False, False, True,  False, "minimal"),
    ("t3_pw_06", "dir", "v9",  False, False, True,  False, True,  "full"),
    ("t3_pw_07", "dir", "v14", True,  True,  False, False, True,  "full"),
    ("t3_pw_08", "dir", "v14", False, True,  True,  True,  False, "minimal"),
    ("t3_pw_09", "zip", "v14", True,  True,  True,  True,  True,  "minimal"),
    ("t3_pw_10", "dir", "v14", True,  True,  True,  True,  False, "full"),
)


def _verify_100_percent_pairwise_coverage() -> None:
    covered: set[tuple[int, int, object, object]] = set()
    for row in _PAIRWISE_ROWS:
        axes = row[1:]
        for i in range(len(axes)):
            for j in range(i + 1, len(axes)):
                covered.add((i, j, axes[i], axes[j]))
    assert len(covered) == 28 * 4, f"Expected 112/112 pairs, got {len(covered)}"


class Tier3CombinationTests(unittest.TestCase):
    """10 pairwise tests covering 100% (112/112) 2-way interactions across 8 binary axes."""

    session: ProbeSession
    batch: BatchExecutionSummary
    sample_paths: dict[str, Path]

    @classmethod
    def setUpClass(cls) -> None:
        _verify_100_percent_pairwise_coverage()
        cls.session = ProbeSession(name_prefix="tier3")
        cls.session.setup(require_godot=True)
        assert cls.session.fixture_dir is not None
        fdir = cls.session.fixture_dir
        cls.sample_paths = {}
        cases: list[ProbeCaseSpec] = []
        png = make_png_bytes(8, 8)

        for cid, src_kind, ver, imp_sc, imp_ch, imp_mo, inc_hid, skip_miss, feat in _PAIRWISE_ROWS:
            wid = f"{cid}_w"
            is_full = feat == "full"

            tokens = [
                make_v9_token("tok_pc", "HeroPC", actor_id="pc1", img="worlds/%s/pc.png" % wid, x=150, y=150, hidden=False, disposition=1),
                make_v9_token("tok_pc_h", "HiddenPC", actor_id="pc2", img="worlds/%s/pc.png" % wid, x=250, y=150, hidden=True, disposition=1),
                make_v9_token("tok_npc", "GoblinNPC", actor_id="npc1", img="worlds/%s/npc.png" % wid, x=450, y=150, hidden=False, disposition=-1),
                make_v9_token("tok_npc_h", "HiddenNPC", actor_id="npc2", img="worlds/%s/npc.png" % wid, x=550, y=150, hidden=True, disposition=-1),
            ]
            if is_full:
                scene = make_v9_scene(
                    "s1",
                    "PW Full Scene",
                    grid_type=1,
                    grid=150,
                    img=f"worlds/{wid}/scenes/Map%20BG.png",
                    tokens=tokens,
                    tiles=[
                        make_tile("tl1", f"worlds/{wid}/tile.png", hidden=False),
                        make_tile("tl2", f"worlds/{wid}/tile.png", hidden=True),
                    ],
                    walls=[
                        make_wall("w1", [100, 100, 400, 100]),
                        make_wall("d_c", [400, 100, 500, 100], door=1, ds=0),
                        make_wall("d_o", [500, 100, 600, 100], door=1, ds=1),
                        make_wall("win1", [100, 200, 250, 200], door=0, move=20, sight=0, light=0),
                    ],
                    lights=[
                        make_light("lt1", 200, 200, hidden=False),
                        make_light("lt2", 400, 200, hidden=True),
                    ],
                )
                extra_tile = [make_tile("tl_remote", "https://example.com/pw_remote.png", hidden=False)]
                scene["tiles"].extend(extra_tile)
                assets = {
                    "scenes/Map BG.png": png,
                    "tile.png": png,
                    "pc.png": png,
                    "npc.png": png,
                }
                npc1_img = "assets/srd5e/missing.png" if skip_miss else f"worlds/{wid}/npc.png"
                if skip_miss:
                    scene["tokens"][2]["img"] = npc1_img
            else:
                scene = make_v9_scene(
                    "s1",
                    "PW Minimal Scene",
                    grid_type=0,
                    grid=100,
                    img=f"worlds/{wid}/bg.png",
                    tokens=tokens,
                )
                assets = {
                    "bg.png": png,
                    "pc.png": png,
                    "npc.png": png,
                }
                npc1_img = f"worlds/{wid}/npc.png"

            actors = [
                make_v9_actor("pc1", "HeroPC", actor_type="character", img=f"worlds/{wid}/pc.png", ac_flat=16, hp_value=30, hp_max=30, level=4),
                make_v9_actor("pc2", "HiddenPC", actor_type="character", img=f"worlds/{wid}/pc.png", ac_flat=15, hp_value=24, hp_max=24, level=3),
                make_v9_actor("npc1", "GoblinNPC", actor_type="npc", img=npc1_img, ac_flat=14, hp_value=12, hp_max=12, cr=0.5),
                make_v9_actor("npc2", "HiddenNPC", actor_type="npc", img=f"worlds/{wid}/npc.png", ac_flat=17, hp_value=45, hp_max=45, cr=2),
            ]

            wdir = fdir / f"{cid}_dir"
            if ver == "v9":
                wj_path = build_v9_world(
                    wdir,
                    world_json=make_v9_world_json(name=wid, title=f"PW {cid}"),
                    scenes=[scene],
                    actors=actors,
                    assets=assets,
                )
            else:
                wj_path = build_v14_world(
                    wdir,
                    world_json=make_v14_world_json(world_id=wid, title=f"PW {cid}"),
                    scenes=[scene],
                    actors=actors,
                    assets=assets,
                )

            sample_path = pack_world_zip(wdir, fdir / f"{cid}.zip", depth=1, root_name=wid) if src_kind == "zip" else wj_path
            cls.sample_paths[cid] = sample_path
            opts = {
                **DEFAULT_OPTIONS,
                "import_scenes": imp_sc,
                "import_characters": imp_ch,
                "import_monsters": imp_mo,
                "include_hidden": inc_hid,
                "skip_missing_assets": skip_miss,
            }
            cases.append(ProbeCaseSpec(cid, sample_path.as_posix(), opts, archive_policy="mock_ok"))

        cls.batch = cls.session.run_batch(cases, timeout_seconds=120)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.session.cleanup()

    def _assert_pw_row(self, row_idx: int) -> None:
        cid, _src, _ver, imp_sc, imp_ch, imp_mo, inc_hid, skip_miss, feat = _PAIRWISE_ROWS[row_idx]
        res = self.batch.results[cid]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths[cid])
        self.assertGreater(ins["decoded_bytes"], 0, f"{cid}: expected decoded_bytes > 0")
        self.assertGreaterEqual(ins["counts"]["records"], 5, f"{cid}: expected >= 5 FVTT source records")
        self.assertGreaterEqual(
            ins["counts"]["images"],
            5 if feat == "full" else 3,
            f"{cid}: expected pre-filter unique image refs in inspect_import.counts",
        )
        if feat == "full":
            self.assertGreaterEqual(ins["counts"]["walls"], 1, f"{cid}: expected >= 1 wall in full scene")
            self.assertGreaterEqual(ins["counts"]["doors"], 1, f"{cid}: expected >= 1 door in full scene")
        world = assert_valid_practice_world_v3(self, res)

        # Scene toggle
        map_ents = get_entities_by_layer_kind(world, "map")
        obs_ents = get_obstacle_entities(world)
        if imp_sc:
            self.assertGreaterEqual(len(map_ents), 1, f"{cid}: expected map entity when import_scenes=True")
            if feat == "full":
                self.assertGreaterEqual(len(obs_ents), 3, f"{cid}: expected walls/doors/windows on full scene")
                lights = [e for e in get_entities(world) if get_component(e, "comp_simple_light.gd") is not None]
                self.assertGreaterEqual(len(lights), 1, f"{cid}: expected light entity")
                if not skip_miss:
                    bad_warns = [
                        w for w in res.host_trace.get("warnings", [])
                        if any(tok in w.lower() for tok in ("missing", "not found", "pw_remote", "map bg", "tile.png", "pc.png", "npc.png", "fail", "error"))
                    ]
                    self.assertEqual(bad_warns, [], f"{cid}: unexpected asset/error warnings when all assets exist: {bad_warns}")
        else:
            self.assertEqual(len(map_ents), 0, f"{cid}: expected 0 map entities when import_scenes=False")
            self.assertEqual(len(obs_ents), 0, f"{cid}: expected 0 obstacles when import_scenes=False")

        unit_names = {u["display_name"] for u in get_unit_entities(world)}
        if imp_ch:
            assert_actor_preserved(self, world, "HeroPC", expected_ac=16, expected_hp=30, expected_level=4, require_unit_entity=imp_sc)
            if imp_sc:
                if inc_hid:
                    self.assertIn("HiddenPC", unit_names)
                else:
                    self.assertNotIn("HiddenPC", unit_names)
        else:
            self.assertNotIn("HeroPC", unit_names)
            self.assertEqual(find_actor_records(world, "HeroPC"), [])

        if imp_mo:
            assert_actor_preserved(self, world, "GoblinNPC", expected_ac=14, expected_hp=12, expected_cr=0.5, require_unit_entity=imp_sc)
            if imp_sc:
                if inc_hid:
                    self.assertIn("HiddenNPC", unit_names)
                else:
                    self.assertNotIn("HiddenNPC", unit_names)
        else:
            self.assertNotIn("GoblinNPC", unit_names)
            self.assertEqual(find_actor_records(world, "GoblinNPC"), [])

        if feat == "full" and imp_sc:
            remote_maps = [e for e in map_ents if str(e["components"][0]["state"].get("sprite_path", "")).startswith("asset://")]
            self.assertGreaterEqual(len(remote_maps), 1, f"{cid}: expected remote URL archived to asset://")

    def test_t3_pw_01(self) -> None:
        self._assert_pw_row(0)

    def test_t3_pw_02(self) -> None:
        self._assert_pw_row(1)

    def test_t3_pw_03(self) -> None:
        self._assert_pw_row(2)

    def test_t3_pw_04(self) -> None:
        self._assert_pw_row(3)

    def test_t3_pw_05(self) -> None:
        self._assert_pw_row(4)

    def test_t3_pw_06(self) -> None:
        self._assert_pw_row(5)

    def test_t3_pw_07(self) -> None:
        self._assert_pw_row(6)

    def test_t3_pw_08(self) -> None:
        self._assert_pw_row(7)

    def test_t3_pw_09(self) -> None:
        self._assert_pw_row(8)

    def test_t3_pw_10(self) -> None:
        self._assert_pw_row(9)
