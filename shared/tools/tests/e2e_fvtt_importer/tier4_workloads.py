"""Tier 4: 5 Real-World Workload & Scale Scenarios (`T4-W1` .. `T4-W5`)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import unittest

from . import DEFAULT_OPTIONS
from .assertions import (
    assert_actor_preserved,
    assert_valid_inspect_ok,
    assert_valid_practice_world_v3,
    assert_valid_prepare_fail,
    get_component,
    get_entities,
    get_entities_by_layer_kind,
    get_floor_by_name,
    get_floors,
    get_obstacle_entities,
    get_unit_entities,
)
from .fixtures import (
    build_v14_world,
    build_v9_world,
    make_armor_item,
    make_folder,
    make_light,
    make_png_bytes,
    make_tile,
    make_v14_world_json,
    make_v9_actor,
    make_v9_scene,
    make_v9_token,
    make_v9_world_json,
    make_wall,
    make_webp_bytes,
    pack_world_zip,
    redact_bgdia_path,
    resolve_bgdia_dir_world_json,
    resolve_bgdia_zip_path,
)
from .harness import BatchExecutionSummary, ProbeCaseSpec, ProbeSession


class Tier4WorkloadTests(unittest.TestCase):
    """5 real-world workload scenarios including real `bgdia` dir & `.zip` parity."""

    session: ProbeSession
    batch: BatchExecutionSummary
    sample_paths: dict[str, Path]
    bgdia_dir_world_json: Path | None = None
    bgdia_zip_path: Path | None = None
    has_bgdia_dir: bool = False
    has_bgdia_zip: bool = False

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = ProbeSession(name_prefix="tier4")
        cls.session.setup(require_godot=True)
        assert cls.session.fixture_dir is not None
        fdir = cls.session.fixture_dir
        cls.sample_paths = {}
        cases: list[ProbeCaseSpec] = []

        png = make_png_bytes(8, 8)
        webp = make_webp_bytes()

        # --- W1 & W2: Real bgdia dir & .zip (read-only) ---
        cls.bgdia_dir_world_json = resolve_bgdia_dir_world_json()
        cls.bgdia_zip_path = resolve_bgdia_zip_path()
        cls.has_bgdia_dir = cls.bgdia_dir_world_json is not None and cls.bgdia_dir_world_json.is_file()
        cls.has_bgdia_zip = cls.bgdia_zip_path is not None and cls.bgdia_zip_path.is_file()
        if cls.has_bgdia_dir:
            assert cls.bgdia_dir_world_json is not None
            cls.sample_paths["t4_w1_bgdia_dir"] = cls.bgdia_dir_world_json
            cases.append(
                ProbeCaseSpec(
                    "t4_w1_bgdia_dir",
                    cls.bgdia_dir_world_json.as_posix(),
                    DEFAULT_OPTIONS,
                    archive_policy="fail_urls",
                )
            )
        if cls.has_bgdia_zip:
            assert cls.bgdia_zip_path is not None
            cls.sample_paths["t4_w2_bgdia_zip"] = cls.bgdia_zip_path
            cases.append(
                ProbeCaseSpec(
                    "t4_w2_bgdia_zip",
                    cls.bgdia_zip_path.as_posix(),
                    DEFAULT_OPTIONS,
                    archive_policy="fail_urls",
                )
            )

        # --- W3: Synthetic FVTT v9 Multi-Scene Campaign ---
        w3_path = build_v9_world(
            fdir / "t4_w3_v9_campaign",
            world_json=make_v9_world_json(name="v9camp", title="Avernus Prelude"),
            folders=[make_folder("f_pc", "Party", "Actor"), make_folder("f_mon", "Monsters", "Actor")],
            scenes=[
                make_v9_scene(
                    "sc_town",
                    "Town Square",
                    active=True,
                    width=2000,
                    height=1500,
                    grid_type=0,
                    grid=100,
                    img="worlds/v9camp/scenes/town.png",
                    tokens=[
                        make_v9_token("t_elrond", "Elrond", actor_id="pc_elrond", img="worlds/v9camp/tokens/elrond.png", x=300, y=300, disposition=1, vision=True, dim_sight=60),
                        make_v9_token("t_lyra", "Lyra", actor_id="pc_lyra", img="worlds/v9camp/tokens/lyra.png", x=450, y=300, disposition=1, vision=True, dim_sight=60),
                    ],
                ),
                make_v9_scene(
                    "sc_crypt",
                    "Crypt Level 1",
                    active=False,
                    width=2400,
                    height=1800,
                    grid_type=1,
                    grid=100,
                    grid_distance=5,
                    img="worlds/v9camp/scenes/crypt.webp",
                    tiles=[make_tile("tl_altar", "worlds/v9camp/tiles/altar.png", x=800, y=600, width=200, height=200)],
                    walls=[
                        make_wall("w1", [100, 100, 900, 100]),
                        make_wall("w2", [900, 100, 900, 700]),
                        make_wall("w3", [900, 700, 100, 700]),
                        make_wall("w4", [100, 700, 100, 100]),
                        make_wall("w5", [400, 100, 400, 300]),
                        make_wall("w6", [400, 400, 400, 700]),
                        make_wall("w7", [400, 300, 500, 300]),
                        make_wall("w8", [400, 400, 500, 400]),
                        make_wall("d_closed", [400, 300, 400, 400], door=1, ds=0),
                        make_wall("d_open", [600, 100, 700, 100], door=1, ds=1),
                        make_wall("d_secret", [200, 700, 300, 700], door=2, ds=0),
                    ],
                    lights=[
                        make_light("lt1", 300, 300, bright=20, dim=40, angle=90),
                        make_light("lt2", 700, 500, bright=20, dim=40, angle=90),
                    ],
                    tokens=[
                        make_v9_token("tc_elrond", "Elrond", actor_id="pc_elrond", img="worlds/v9camp/tokens/elrond.png", x=200, y=200, disposition=1),
                        make_v9_token("tc_lyra", "Lyra", actor_id="pc_lyra", img="worlds/v9camp/tokens/lyra.png", x=250, y=250, disposition=1),
                        make_v9_token("tc_gb1", "Goblin Boss", actor_id="npc_gboss", img="worlds/v9camp/tokens/goblin.webp", x=650, y=350, disposition=-1),
                        make_v9_token("tc_cf1", "Cult Fanatic A", actor_id="npc_cfan", img="worlds/v9camp/tokens/cultist.png", x=750, y=450, disposition=-1),
                        make_v9_token("tc_cf2", "Cult Fanatic B", actor_id="npc_cfan", img="worlds/v9camp/tokens/cultist.png", x=750, y=550, disposition=-1),
                    ],
                ),
            ],
            actors=[
                make_v9_actor(
                    "pc_elrond",
                    "Elrond",
                    actor_type="character",
                    folder="f_pc",
                    img="worlds/v9camp/tokens/elrond.png",
                    abilities={"str": 12, "dex": 16, "con": 14, "int": 12, "wis": 14, "cha": 10},
                    ac_flat=None,
                    ac_calc="default",
                    hp_value=44,
                    hp_max=44,
                    level=5,
                    items=[
                        make_armor_item("ar1", "Half Plate", armor_type="medium", armor_value=15, dex_cap=2, equipped=True),
                        make_armor_item("ar2", "Shield", armor_type="shield", armor_value=2, dex_cap=None, equipped=True),
                        {"_id": "sp1", "name": "Hunter's Mark", "type": "spell"},
                        {"_id": "cs1", "name": "Potion of Healing", "type": "consumable"},
                    ],
                ),
                make_v9_actor("pc_lyra", "Lyra", actor_type="character", folder="f_pc", img="worlds/v9camp/tokens/lyra.png", ac_flat=15, hp_value=32, hp_max=32, level=4),
                make_v9_actor("npc_gboss", "Goblin Boss", actor_type="npc", folder="f_mon", img="worlds/v9camp/tokens/goblin.webp", ac_flat=17, ac_calc="natural", hp_value=21, hp_max=21, cr=1),
                make_v9_actor(
                    "npc_cfan",
                    "Cult Fanatic",
                    actor_type="npc",
                    folder="f_mon",
                    img="worlds/v9camp/tokens/cultist.png",
                    abilities={"str": 11, "dex": 14, "con": 12, "int": 10, "wis": 13, "cha": 14},
                    ac_flat=None,
                    ac_calc="default",
                    hp_value=33,
                    hp_max=33,
                    cr=2,
                ),
            ],
            assets={
                "scenes/town.png": png,
                "scenes/crypt.webp": webp,
                "tiles/altar.png": png,
                "tokens/elrond.png": png,
                "tokens/lyra.png": png,
                "tokens/goblin.webp": webp,
                "tokens/cultist.png": png,
            },
        )
        cls.sample_paths["t4_w3"] = w3_path
        cases.append(ProbeCaseSpec("t4_w3", w3_path.as_posix(), DEFAULT_OPTIONS))

        # --- W4: Synthetic FVTT v14 LevelDB Campaign (Snappy .ldb + .log WAL) ---
        s_wal_doc = {
            "_id": "s1",
            "name": "WAL Citadel",
            "active": True,
            "navigation": True,
            "width": 2400,
            "height": 1800,
            "padding": 0.0,
            "shiftX": 0,
            "shiftY": 0,
            "grid": {"size": 120, "type": 1, "distance": 5, "units": "ft", "color": "#000000", "alpha": 0.2},
            "levels": ["lvl1"],
            "initialLevel": "lvl1",
        }
        lvl_wal_doc = {
            "_id": "lvl1",
            "name": "Level 1",
            "background": {"src": "worlds/lvl14_camp/bg.png"},
            "foreground": {"src": "worlds/lvl14_camp/fg.png"},
        }
        pc_wal_doc = {
            "_id": "pc1",
            "name": "V14 Champion",
            "type": "character",
            "img": "worlds/lvl14_camp/pc.png",
            "system": {
                "abilities": {"str": {"value": 18}, "dex": {"value": 14}, "con": {"value": 16}, "int": {"value": 10}, "wis": {"value": 12}, "cha": {"value": 10}},
                "attributes": {"hp": {"value": 52, "max": 52}, "ac": {"flat": None, "calcs": ["unarmored", "armored"]}},
                "details": {"level": 6},
            },
            "prototypeToken": {"name": "V14 Champion", "texture": {"src": "worlds/lvl14_camp/pc.png"}, "width": 1, "height": 1},
        }
        w4_path = build_v14_world(
            fdir / "t4_w4_v14_wal",
            world_json=make_v14_world_json(world_id="lvl14_camp", title="LevelDB WAL Campaign"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Stale Base Name",
                    active=False,
                    img="worlds/lvl14_camp/bg.png",
                    foreground="worlds/lvl14_camp/fg.png",
                    walls=[make_wall("w1", [100, 100, 400, 100])],
                    tokens=[
                        make_v9_token("t1", "V14 Champion", actor_id="pc1", img="worlds/lvl14_camp/pc.png", x=200, y=200, disposition=1),
                        make_v9_token("t2", "Balor", actor_id="npc1", img="worlds/lvl14_camp/npc.png", x=500, y=200, disposition=-1),
                    ],
                ),
                make_v9_scene("s_stale", "Deleted Stale Scene", active=False, img="worlds/lvl14_camp/bg.png"),
            ],
            actors=[
                make_v9_actor("pc1", "Old Champion", actor_type="character", level=1),
                make_v9_actor("npc1", "Balor", actor_type="npc", img="worlds/lvl14_camp/npc.png", ac_flat=19, hp_value=262, hp_max=262, cr=19),
            ],
            scene_wal_ops=[
                (
                    200,
                    [
                        ("put", b"!scenes!s1", json.dumps(s_wal_doc).encode("utf-8")),
                        ("put", b"!scenes.levels!s1.lvl1", json.dumps(lvl_wal_doc).encode("utf-8")),
                        ("delete", b"!scenes!s_stale", b""),
                    ],
                )
            ],
            actor_wal_ops=[
                (
                    200,
                    [
                        ("put", b"!actors!pc1", json.dumps(pc_wal_doc).encode("utf-8")),
                        (
                            "put",
                            b"!actors.items!pc1.ar1",
                            json.dumps(
                                make_armor_item(
                                    "ar1",
                                    "Half Plate",
                                    armor_type="medium",
                                    armor_value=15,
                                    dex_cap=2,
                                    equipped=True,
                                    v14=True,
                                )
                            ).encode("utf-8"),
                        ),
                        (
                            "put",
                            b"!actors.items!pc1.ar2",
                            json.dumps(
                                make_armor_item(
                                    "ar2",
                                    "Shield",
                                    armor_type="shield",
                                    armor_value=2,
                                    dex_cap=None,
                                    equipped=True,
                                    v14=True,
                                )
                            ).encode("utf-8"),
                        ),
                    ],
                )
            ],
            assets={
                "bg.png": png,
                "fg.png": png,
                "pc.png": png,
                "npc.png": png,
            },
        )
        cls.sample_paths["t4_w4"] = w4_path
        cases.append(ProbeCaseSpec("t4_w4", w4_path.as_posix(), DEFAULT_OPTIONS))

        # --- W5: Synthetic Edge-Rich Campaign ---
        w5_src = fdir / "t4_w5_src"
        build_v9_world(
            w5_src,
            world_json=make_v9_world_json(name="测试战役", title="Edge Campaign"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "龙巢遗迹",
                    img="worlds/测试战役/scenes/地图%201.webp",
                    tiles=[
                        make_tile("tl_vis", "worlds/测试战役/scenes/地图%201.webp", hidden=False),
                        make_tile("tl_hid", "assets/srd5e/missing_tile.png", hidden=True),
                    ],
                    tokens=[
                        make_v9_token("t_vis", "Visible Hero", actor_id="pc1", img="https://example.invalid/missing.png", hidden=False, disposition=1),
                        make_v9_token("t_hid", "Hidden Stalker", actor_id="npc1", img="worlds/测试战役/scenes/地图%201.webp", hidden=True, disposition=-1),
                    ],
                    lights=[
                        make_light("lt_vis", 200, 200, hidden=False),
                        make_light("lt_hid", 400, 200, hidden=True),
                    ],
                ),
                {"_id": "s_del", "$$deleted": True},
            ],
            actors=[
                make_v9_actor("pc1", "Visible Hero", actor_type="character", ac_flat=16, hp_value=28, hp_max=28, level=3),
                make_v9_actor("npc1", "Hidden Stalker", actor_type="npc", ac_flat=15, hp_value=45, hp_max=45, cr=4),
                {"_id": "a_del", "$$deleted": True},
            ],
            assets={"scenes/地图 1.webp": webp},
        )
        w5_zip = pack_world_zip(w5_src, fdir / "t4_w5_edge.zip", depth=1, root_name="测试战役")
        cls.sample_paths["t4_w5"] = w5_zip
        cases.append(ProbeCaseSpec("t4_w5_show_skip", w5_zip.as_posix(), {**DEFAULT_OPTIONS, "include_hidden": True, "skip_missing_assets": True}, archive_policy="fail_all"))
        cases.append(ProbeCaseSpec("t4_w5_hide_skip", w5_zip.as_posix(), {**DEFAULT_OPTIONS, "include_hidden": False, "skip_missing_assets": True}, archive_policy="fail_all"))
        cases.append(ProbeCaseSpec("t4_w5_strict_fail", w5_zip.as_posix(), {**DEFAULT_OPTIONS, "include_hidden": True, "skip_missing_assets": False}, run_inspect=False, archive_policy="fail_all"))

        cls.batch = cls.session.run_batch(cases, timeout_seconds=300)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.session.cleanup()

    def _require_bgdia(self, exists: bool, label: str, env_var: str) -> None:
        if not exists:
            safe_label = redact_bgdia_path(
                label,
                bgdia_dir_world_json=self.bgdia_dir_world_json,
                bgdia_zip_path=self.bgdia_zip_path,
            )
            if os.environ.get("FUVTT_E2E_ALLOW_MISSING_BGDIA") == "1":
                self.skipTest(f"{safe_label} absent and FUVTT_E2E_ALLOW_MISSING_BGDIA=1")
            self.fail(
                f"Required local reference {safe_label} missing; "
                f"set {env_var} in .env.local or environment"
            )

    def test_t4_w1_real_bgdia_unpacked_dir(self) -> None:
        self._require_bgdia(self.has_bgdia_dir, "<FUVTT_BGDIA_DIR>/world.json", "FUVTT_BGDIA_DIR")
        assert self.bgdia_dir_world_json is not None
        res = self.batch.results["t4_w1_bgdia_dir"]
        ins = assert_valid_inspect_ok(self, res, self.bgdia_dir_world_json)
        self.assertGreaterEqual(ins["counts"]["maps"], 31)
        self.assertGreaterEqual(ins["counts"]["walls"], 3734)
        self.assertGreaterEqual(ins["counts"]["doors"], 123)
        self.assertGreaterEqual(ins["counts"]["hidden"], 577)

        world = assert_valid_practice_world_v3(self, res)
        floors = get_floors(world)
        self.assertEqual(len(floors), 31)
        floor_names = {f["name"] for f in floors}
        for req_scene in (
            "Start",
            "Side View of the Scab",
            "DMG Ship Layout",
            "Baldur's Gate",
            "Elturel",
            "Dungeon of the Dead Three",
            "Wrecked Flying Fortress",
            "Under the Villa",
            "Vanthampur Villa",
            "Elfsong Tavern",
        ):
            self.assertIn(req_scene, floor_names)

        self.assertLessEqual(res.prepare_meta.get("serialized_bytes", 0), 32 * 1024 * 1024)
        self.assertLessEqual(res.prepare_meta.get("modules_max_entry_bounded_bytes", 0), 6 * 1024 * 1024)
        self.assertLessEqual(res.prepare_meta.get("modules_bounded_bytes", 0), 8 * 1024 * 1024)

        self.assertGreaterEqual(len(get_unit_entities(world)), 618)
        self.assertGreaterEqual(len(get_obstacle_entities(world, kind="door")), 123)
        self.assertGreaterEqual(len(get_obstacle_entities(world, kind="wall")), 31)
        self.assertGreaterEqual(len(res.host_trace.get("warnings", [])), 1)

        # Representative bgdia actor ground truth
        assert_actor_preserved(self, world, "Fist of Bane", expected_ac=18, expected_hp=22, expected_cr=0.5)
        assert_actor_preserved(self, world, "Horned Devil", expected_ac=18, expected_hp=178, expected_cr=11)
        assert_actor_preserved(self, world, "Skeleton", expected_hp=13, expected_cr=0.25)
        assert_actor_preserved(self, world, "Scavenger", expected_ac=20, expected_hp=150)
        assert_actor_preserved(self, world, "Demon Grinder", expected_ac=19, expected_hp=200)
        assert_actor_preserved(self, world, "Devil's Ride", expected_ac=23, expected_hp=30)
        assert_actor_preserved(self, world, "Tormentor", expected_ac=21, expected_hp=60)
        assert_actor_preserved(self, world, "Golden Doom", expected_ac=19, expected_hp=200)

        # Ensure spells/items were not materialized as entities
        entity_names = {e.get("display_name") for e in get_entities(world)}
        self.assertNotIn("Chain Mail", entity_names)
        self.assertNotIn("Fireball", entity_names)

    def test_t4_w2_real_bgdia_zip_parity(self) -> None:
        self._require_bgdia(self.has_bgdia_zip, "<FUVTT_BGDIA_ZIP>", "FUVTT_BGDIA_ZIP")
        self._require_bgdia(self.has_bgdia_dir, "<FUVTT_BGDIA_DIR>/world.json", "FUVTT_BGDIA_DIR")
        assert self.bgdia_zip_path is not None
        assert self.bgdia_dir_world_json is not None
        res_zip = self.batch.results["t4_w2_bgdia_zip"]
        res_dir = self.batch.results["t4_w1_bgdia_dir"]

        ins_zip = assert_valid_inspect_ok(self, res_zip, self.bgdia_zip_path)
        ins_dir = assert_valid_inspect_ok(self, res_dir, self.bgdia_dir_world_json)
        self.assertEqual(ins_zip["counts"]["maps"], ins_dir["counts"]["maps"])
        self.assertEqual(ins_zip["counts"]["walls"], ins_dir["counts"]["walls"])
        self.assertEqual(ins_zip["counts"]["doors"], ins_dir["counts"]["doors"])

        w_zip = assert_valid_practice_world_v3(self, res_zip)
        w_dir = assert_valid_practice_world_v3(self, res_dir)

        self.assertEqual([f["name"] for f in get_floors(w_zip)], [f["name"] for f in get_floors(w_dir)])
        self.assertGreaterEqual(len(get_unit_entities(w_zip)), 618)
        self.assertGreaterEqual(len(get_unit_entities(w_dir)), 618)
        self.assertEqual(len(get_obstacle_entities(w_zip, kind="wall")), len(get_obstacle_entities(w_dir, kind="wall")))
        self.assertEqual(len(get_obstacle_entities(w_zip, kind="door")), len(get_obstacle_entities(w_dir, kind="door")))
        for world_variant in (w_zip, w_dir):
            assert_actor_preserved(self, world_variant, "Fist of Bane", expected_ac=18, expected_hp=22, expected_cr=0.5)
            assert_actor_preserved(self, world_variant, "Demon Grinder", expected_ac=19, expected_hp=200)
            assert_actor_preserved(self, world_variant, "Skeleton", expected_hp=13, expected_cr=0.25)
            assert_actor_preserved(self, world_variant, "Horned Devil", expected_ac=18, expected_hp=178, expected_cr=11)

    def test_t4_w3_synthetic_v9_multi_scene_campaign(self) -> None:
        res = self.batch.results["t4_w3"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t4_w3"])
        self.assertGreaterEqual(ins["counts"]["maps"], 2)
        world = assert_valid_practice_world_v3(self, res)
        self.assertIsNotNone(get_floor_by_name(world, "Town Square"))
        self.assertIsNotNone(get_floor_by_name(world, "Crypt Level 1"))
        assert_actor_preserved(self, world, "Elrond", expected_ac=19, expected_hp=44, expected_level=5, require_unit_entity=True)
        assert_actor_preserved(self, world, "Lyra", expected_ac=15, expected_hp=32, expected_level=4, require_unit_entity=True)
        assert_actor_preserved(self, world, "Goblin Boss", expected_ac=17, expected_hp=21, expected_cr=1, require_unit_entity=True)
        assert_actor_preserved(self, world, "Cult Fanatic", expected_ac=12, expected_hp=33, expected_cr=2, require_unit_entity=True)
        names = {e.get("display_name") for e in get_entities(world)}
        self.assertNotIn("Hunter's Mark", names)
        self.assertNotIn("Potion of Healing", names)

    def test_t4_w4_synthetic_v14_leveldb_snappy_and_wal_campaign(self) -> None:
        res = self.batch.results["t4_w4"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t4_w4"])
        self.assertEqual(ins["counts"]["maps"], 1)
        world = assert_valid_practice_world_v3(self, res)
        floor_names = [f["name"] for f in get_floors(world)]
        self.assertIn("WAL Citadel", floor_names)
        self.assertNotIn("Stale Base Name", floor_names)
        self.assertNotIn("Deleted Stale Scene", floor_names)
        fl = get_floor_by_name(world, "WAL Citadel")
        self.assertIsNotNone(fl)
        assert fl is not None
        self.assertGreaterEqual(len(get_entities_by_layer_kind(world, "map")), 2)
        assert_actor_preserved(self, world, "V14 Champion", expected_ac=19, expected_hp=52, expected_level=6, require_unit_entity=True)
        assert_actor_preserved(self, world, "Balor", expected_ac=19, expected_hp=262, expected_cr=19, require_unit_entity=True)

    def test_t4_w5_synthetic_edge_rich_non_ascii_and_toggles(self) -> None:
        r_show = self.batch.results["t4_w5_show_skip"]
        ins = assert_valid_inspect_ok(self, r_show, self.sample_paths["t4_w5"])
        self.assertEqual(ins["counts"]["maps"], 1)
        w_show = assert_valid_practice_world_v3(self, r_show)
        self.assertIsNotNone(get_floor_by_name(w_show, "龙巢遗迹"))
        show_units = {u["display_name"]: u for u in get_unit_entities(w_show)}
        self.assertIn("Visible Hero", show_units)
        self.assertIn("Hidden Stalker", show_units)
        self.assertTrue(show_units["Hidden Stalker"].get("flags", {}).get("entity_hidden"))
        self.assertGreaterEqual(len(r_show.host_trace.get("warnings", [])), 1)
        self.assertFalse(any("地图 1.webp" in w for w in r_show.host_trace.get("warnings", [])))

        r_hide = self.batch.results["t4_w5_hide_skip"]
        w_hide = assert_valid_practice_world_v3(self, r_hide)
        hide_units = {u["display_name"] for u in get_unit_entities(w_hide)}
        self.assertIn("Visible Hero", hide_units)
        self.assertNotIn("Hidden Stalker", hide_units)

        r_fail = self.batch.results["t4_w5_strict_fail"]
        assert_valid_prepare_fail(self, r_fail)
