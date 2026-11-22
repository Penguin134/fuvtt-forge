"""Tier 1: 40 Isolated Happy-Path Feature Tests (`T1-F1-01` .. `T1-F8-05`)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest
import zipfile

from fuvtt_devtools.deployer import compute_directory_file_hashes, sync_mod
from fuvtt_devtools.env_config import WorkspaceConfig
from fuvtt_devtools.host_verifier import verify_mod_with_host
from fuvtt_devtools.packager import build_mod
from fuvtt_devtools.validator import NON_RUNTIME_FILENAMES, UTF8_BOM, validate_mod_dir, validate_zip_archive

from . import DEFAULT_OPTIONS
from .assertions import (
    assert_actor_preserved,
    assert_valid_inspect_ok,
    assert_valid_practice_world_v3,
    get_component,
    get_entities,
    get_entities_by_layer_kind,
    get_entities_on_floor,
    get_floor_by_name,
    get_floor_layers,
    get_floors,
    get_obstacle_entities,
    get_unit_entities,
)
from .fixtures import (
    build_v14_world,
    build_v9_world,
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
)
from .harness import (
    BatchExecutionSummary,
    MOD_NAME,
    ProbeCaseSpec,
    ProbeSession,
    WORKSPACE_ROOT,
)


class Tier1FeatureTests(unittest.TestCase):
    """40 isolated opaque-box happy-path tests covering Features F1..F8."""

    session: ProbeSession
    batch: BatchExecutionSummary
    sample_paths: dict[str, Path]

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = ProbeSession(name_prefix="tier1")
        cls.session.setup(require_godot=True)
        assert cls.session.fixture_dir is not None
        fdir = cls.session.fixture_dir
        cls.sample_paths = {}
        cases: list[ProbeCaseSpec] = []

        png = make_png_bytes(8, 8)
        webp = make_webp_bytes()

        # --- F2 fixtures ---
        w_f2_01 = fdir / "f2_01_src"
        build_v9_world(
            w_f2_01,
            world_json=make_v9_world_json(name="w_f2_01", title="Depth0 Zip"),
            scenes=[make_v9_scene("s1", "Depth0 Scene")],
            actors=[make_v9_actor("a1", "Goblin", actor_type="npc")],
        )
        p_f2_01 = pack_world_zip(w_f2_01, fdir / "t1_f2_01.zip", depth=0)
        cls.sample_paths["t1_f2_01"] = p_f2_01
        cases.append(ProbeCaseSpec("t1_f2_01", p_f2_01.as_posix(), DEFAULT_OPTIONS))

        w_f2_02 = fdir / "my_world"
        build_v9_world(
            w_f2_02,
            world_json=make_v9_world_json(name="my_world", title="Depth1 Zip"),
            scenes=[make_v9_scene("s1", "Depth1 Scene", img="worlds/my_world/scenes/bg.png")],
            assets={"scenes/bg.png": png},
        )
        p_f2_02 = pack_world_zip(w_f2_02, fdir / "t1_f2_02.zip", depth=1, root_name="my_world")
        cls.sample_paths["t1_f2_02"] = p_f2_02
        cases.append(ProbeCaseSpec("t1_f2_02", p_f2_02.as_posix(), DEFAULT_OPTIONS))

        w_f2_03 = fdir / "cjk_src"
        build_v9_world(
            w_f2_03,
            world_json=make_v9_world_json(name="博得之门", title="测试战役"),
            scenes=[make_v9_scene("s1", "翠绿营地", img="worlds/博得之门/scenes/地图.png")],
            assets={"scenes/地图.png": png},
        )
        p_f2_03 = pack_world_zip(w_f2_03, fdir / "测试世界包.zip", depth=1, root_name="博得之门")
        cls.sample_paths["t1_f2_03"] = p_f2_03
        cases.append(ProbeCaseSpec("t1_f2_03", p_f2_03.as_posix(), DEFAULT_OPTIONS))

        w_f2_04 = fdir / "v14zip_src"
        build_v14_world(
            w_f2_04,
            world_json=make_v14_world_json(world_id="v14zip", title="V14 Zip"),
            scenes=[make_v9_scene("s1", "V14 Zip Scene", img="worlds/v14zip/scenes/bg.png")],
            actors=[make_v9_actor("a1", "V14 Ranger", actor_type="character", level=4)],
            assets={"scenes/bg.png": png},
        )
        p_f2_04 = pack_world_zip(w_f2_04, fdir / "t1_f2_04.zip", depth=1, root_name="v14zip")
        cls.sample_paths["t1_f2_04"] = p_f2_04
        cases.append(ProbeCaseSpec("t1_f2_04", p_f2_04.as_posix(), DEFAULT_OPTIONS))

        w_f2_05 = fdir / "w1_src"
        build_v9_world(
            w_f2_05,
            world_json=make_v9_world_json(name="w1", title="Mixed Paths"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Mixed Path Scene",
                    img="worlds/w1/scenes/map.png",
                    tokens=[make_v9_token("tok1", "Scout", actor_id="a1", img="scenes/token.png")],
                )
            ],
            actors=[make_v9_actor("a1", "Scout", actor_type="npc", img="scenes/token.png")],
            assets={"scenes/map.png": png, "scenes/token.png": png},
        )
        p_f2_05 = pack_world_zip(w_f2_05, fdir / "t1_f2_05.zip", depth=1, root_name="w1")
        cls.sample_paths["t1_f2_05"] = p_f2_05
        cases.append(ProbeCaseSpec("t1_f2_05", p_f2_05.as_posix(), DEFAULT_OPTIONS))

        # --- F3 fixtures ---
        p_f3_01 = build_v9_world(
            fdir / "f3_01_v9dir",
            world_json=make_v9_world_json(name="v9dir", title="V9 Dir"),
            scenes=[make_v9_scene("s1", "V9 Dir Scene")],
            actors=[make_v9_actor("a1", "Aria", actor_type="character", level=3)],
        )
        cls.sample_paths["t1_f3_01"] = p_f3_01
        cases.append(ProbeCaseSpec("t1_f3_01", p_f3_01.as_posix(), DEFAULT_OPTIONS))

        p_f3_02 = build_v14_world(
            fdir / "f3_02_v14dir",
            world_json=make_v14_world_json(world_id="v14dir", title="V14 Dir"),
            scenes=[make_v9_scene("s1", "LevelDB Scene")],
            actors=[make_v9_actor("a1", "LevelDB Orc", actor_type="npc", cr=2)],
        )
        cls.sample_paths["t1_f3_02"] = p_f3_02
        cases.append(ProbeCaseSpec("t1_f3_02", p_f3_02.as_posix(), DEFAULT_OPTIONS))

        p_f3_03 = build_v14_world(
            fdir / "f3_03_dual",
            world_json=make_v14_world_json(world_id="dual", title="Dual Format"),
            scenes=[make_v9_scene("s1", "Dual One"), make_v9_scene("s2", "Dual Two", active=False)],
            actors=[
                make_v9_actor("a1", "Dual PC", actor_type="character"),
                make_v9_actor("a2", "Dual NPC", actor_type="npc"),
            ],
            also_nedb=True,
        )
        cls.sample_paths["t1_f3_03"] = p_f3_03
        cases.append(ProbeCaseSpec("t1_f3_03", p_f3_03.as_posix(), DEFAULT_OPTIONS))

        p_f3_04 = build_v9_world(
            fdir / "f3_04_folders",
            world_json=make_v9_world_json(name="f304", title="Folders World"),
            folders=[make_folder("f1", "Bosses", "Actor"), make_folder("f2", "Chapter 1", "Scene")],
            scenes=[make_v9_scene("s1", "Boss Lair", folder="f2")],
            actors=[make_v9_actor("a1", "Dragon", actor_type="npc", folder="f1", cr=12)],
        )
        cls.sample_paths["t1_f3_04"] = p_f3_04
        cases.append(ProbeCaseSpec("t1_f3_04", p_f3_04.as_posix(), DEFAULT_OPTIONS))

        p_f3_05 = build_v9_world(
            fdir / "f3_05_smoke_meta",
            world_json=make_v9_world_json(name="smoke", title="Smoke Campaign", background="worlds/smoke/splash.png"),
            scenes=[make_v9_scene("s1", "Campaign Start")],
            actors=[make_v9_actor("a1", "Hero", actor_type="character")],
            assets={"splash.png": png},
        )
        cls.sample_paths["t1_f3_05"] = p_f3_05
        cases.append(ProbeCaseSpec("t1_f3_05", p_f3_05.as_posix(), DEFAULT_OPTIONS))

        # --- F4 fixtures ---
        p_f4_01 = build_v9_world(
            fdir / "f4_01_keep",
            world_json=make_v9_world_json(name="w", title="Keep World"),
            scenes=[make_v9_scene("s1", "Elturel Keep", active=True, width=3000, height=2100, grid=150, grid_type=1, img="worlds/w/keep.png")],
            assets={"keep.png": png},
        )
        cls.sample_paths["t1_f4_01"] = p_f4_01
        cases.append(ProbeCaseSpec("t1_f4_01", p_f4_01.as_posix(), DEFAULT_OPTIONS))

        p_f4_02 = build_v9_world(
            fdir / "f4_02_multi",
            world_json=make_v9_world_json(name="w", title="Multi Floor"),
            scenes=[
                make_v9_scene("s1", "Floor A", active=False),
                make_v9_scene("s2", "Floor B", active=True),
            ],
        )
        cls.sample_paths["t1_f4_02"] = p_f4_02
        cases.append(ProbeCaseSpec("t1_f4_02", p_f4_02.as_posix(), DEFAULT_OPTIONS))

        p_f4_03 = build_v9_world(
            fdir / "f4_03_tiles",
            world_json=make_v9_world_json(name="w", title="Tiles"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Tile Room",
                    width=1500,
                    height=1500,
                    grid=150,
                    tiles=[
                        make_tile("t1", "worlds/w/rug.png", x=300, y=450, width=300, height=300, rotation=90),
                        make_tile("t2", "worlds/w/table.png", x=600, y=600, width=150, height=150, rotation=0),
                    ],
                )
            ],
            assets={"rug.png": png, "table.png": png},
        )
        cls.sample_paths["t1_f4_03"] = p_f4_03
        cases.append(ProbeCaseSpec("t1_f4_03", p_f4_03.as_posix(), DEFAULT_OPTIONS))

        p_f4_04 = build_v9_world(
            fdir / "f4_04_fg",
            world_json=make_v9_world_json(name="w", title="Foreground"),
            scenes=[make_v9_scene("s1", "Layered Roof", img="worlds/w/bg.png", foreground="worlds/w/roof.png")],
            assets={"bg.png": png, "roof.png": png},
        )
        cls.sample_paths["t1_f4_04"] = p_f4_04
        cases.append(ProbeCaseSpec("t1_f4_04", p_f4_04.as_posix(), DEFAULT_OPTIONS))

        p_f4_05 = build_v9_world(
            fdir / "f4_05_no_scenes",
            world_json=make_v9_world_json(name="w", title="No Scenes"),
            scenes=[make_v9_scene("s1", "Skipped Scene", img="worlds/w/keep.png")],
            actors=[make_v9_actor("pc1", "Alden", actor_type="character", level=2)],
            assets={"keep.png": png},
        )
        cls.sample_paths["t1_f4_05"] = p_f4_05
        cases.append(
            ProbeCaseSpec(
                "t1_f4_05",
                p_f4_05.as_posix(),
                {**DEFAULT_OPTIONS, "import_scenes": False, "import_characters": True},
            )
        )

        # --- F5 fixtures ---
        p_f5_01 = build_v9_world(
            fdir / "f5_01_pc",
            world_json=make_v9_world_json(name="w", title="PC Placed"),
            scenes=[make_v9_scene("s1", "Camp", tokens=[make_v9_token("tok1", "Lyra", actor_id="pc1", x=450, y=450, disposition=1)])],
            actors=[
                make_v9_actor(
                    "pc1",
                    "Lyra",
                    actor_type="character",
                    ac_flat=16,
                    ac_calc="flat",
                    hp_value=38,
                    hp_max=38,
                    level=5,
                    abilities={"str": 10, "dex": 16, "con": 14, "int": 12, "wis": 13, "cha": 8},
                )
            ],
        )
        cls.sample_paths["t1_f5_01"] = p_f5_01
        cases.append(ProbeCaseSpec("t1_f5_01", p_f5_01.as_posix(), DEFAULT_OPTIONS))

        p_f5_02 = build_v9_world(
            fdir / "f5_02_unplaced_pc",
            world_json=make_v9_world_json(name="w", title="Unplaced PC"),
            scenes=[],
            actors=[make_v9_actor("pc1", "Thorin", actor_type="character", ac_flat=18, ac_calc="flat", hp_value=45, hp_max=45, level=4)],
        )
        cls.sample_paths["t1_f5_02"] = p_f5_02
        cases.append(ProbeCaseSpec("t1_f5_02", p_f5_02.as_posix(), DEFAULT_OPTIONS))

        p_f5_03 = build_v9_world(
            fdir / "f5_03_three_pcs",
            world_json=make_v9_world_json(name="w", title="Three PCs"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Party Map",
                    tokens=[
                        make_v9_token("t1", "PC1", actor_id="p1", x=150, y=150, disposition=1),
                        make_v9_token("t2", "PC2", actor_id="p2", x=300, y=150, disposition=1),
                        make_v9_token("t3", "PC3", actor_id="p3", x=450, y=150, disposition=1),
                    ],
                )
            ],
            actors=[
                make_v9_actor("p1", "PC1", actor_type="character", ac_flat=14, hp_value=20, hp_max=20, level=2),
                make_v9_actor("p2", "PC2", actor_type="character", ac_flat=16, hp_value=32, hp_max=32, level=4),
                make_v9_actor("p3", "PC3", actor_type="character", ac_flat=19, hp_value=50, hp_max=50, level=6),
            ],
        )
        cls.sample_paths["t1_f5_03"] = p_f5_03
        cases.append(ProbeCaseSpec("t1_f5_03", p_f5_03.as_posix(), DEFAULT_OPTIONS))

        p_f5_04 = build_v9_world(
            fdir / "f5_04_scale",
            world_json=make_v9_world_json(name="w", title="Large PC"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Arena",
                    grid=150,
                    tokens=[
                        make_v9_token("t_small", "Halfling", actor_id="p_small", x=150, y=150, width=1, height=1, disposition=1),
                        make_v9_token("t_big", "Goliath", actor_id="p_big", x=450, y=450, width=2, height=2, scale=1.0, disposition=1),
                    ],
                )
            ],
            actors=[
                make_v9_actor("p_small", "Halfling", actor_type="character"),
                make_v9_actor("p_big", "Goliath", actor_type="character", token_width=2, token_height=2, token_scale=1.5),
            ],
        )
        cls.sample_paths["t1_f5_04"] = p_f5_04
        cases.append(ProbeCaseSpec("t1_f5_04", p_f5_04.as_posix(), DEFAULT_OPTIONS))

        p_f5_05 = build_v9_world(
            fdir / "f5_05_vision",
            world_json=make_v9_world_json(name="w", title="Vision PC"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Dark Cavern",
                    grid=150,
                    grid_distance=5,
                    tokens=[make_v9_token("t1", "Elrond", actor_id="p1", vision=True, dim_sight=60, bright_sight=30, sight_angle=120, disposition=1)],
                )
            ],
            actors=[make_v9_actor("p1", "Elrond", actor_type="character")],
        )
        cls.sample_paths["t1_f5_05"] = p_f5_05
        cases.append(ProbeCaseSpec("t1_f5_05", p_f5_05.as_posix(), DEFAULT_OPTIONS))

        # --- F6 fixtures ---
        p_f6_01 = build_v9_world(
            fdir / "f6_01_npc",
            world_json=make_v9_world_json(name="w", title="NPC Placed"),
            scenes=[make_v9_scene("s1", "Ambush", tokens=[make_v9_token("t1", "Goblin", actor_id="n1")])],
            actors=[make_v9_actor("n1", "Goblin", actor_type="npc", ac_flat=15, ac_calc="natural", hp_value=7, hp_max=7, cr=0.25)],
        )
        cls.sample_paths["t1_f6_01"] = p_f6_01
        cases.append(ProbeCaseSpec("t1_f6_01", p_f6_01.as_posix(), DEFAULT_OPTIONS))

        p_f6_02 = build_v9_world(
            fdir / "f6_02_unplaced_npc",
            world_json=make_v9_world_json(name="w", title="Unplaced NPC"),
            scenes=[make_v9_scene("s1", "Empty Lake", tokens=[])],
            actors=[
                make_v9_actor(
                    "n1",
                    "Aboleth",
                    actor_type="npc",
                    ac_flat=17,
                    ac_calc="natural",
                    hp_value=135,
                    hp_max=135,
                    cr=10,
                    biography="<p>Ancient aberration</p>",
                )
            ],
        )
        cls.sample_paths["t1_f6_02"] = p_f6_02
        cases.append(ProbeCaseSpec("t1_f6_02", p_f6_02.as_posix(), DEFAULT_OPTIONS))

        p_f6_03 = build_v9_world(
            fdir / "f6_03_folders_npcs",
            world_json=make_v9_world_json(name="w", title="Monster Folders"),
            folders=[make_folder("f_low", "Low CR", "Actor"), make_folder("f_high", "Bosses", "Actor")],
            scenes=[make_v9_scene("s1", "Bestiary")],
            actors=[
                make_v9_actor("n1", "Imp", actor_type="npc", folder="f_low", cr=1, ac_flat=13, hp_value=10, hp_max=10),
                make_v9_actor("n2", "Cultist", actor_type="npc", folder="f_low", cr=0.125, ac_flat=12, hp_value=9, hp_max=9),
                make_v9_actor("n3", "Pit Fiend", actor_type="npc", folder="f_high", cr=20, ac_flat=19, hp_value=300, hp_max=300),
            ],
        )
        cls.sample_paths["t1_f6_03"] = p_f6_03
        cases.append(ProbeCaseSpec("t1_f6_03", p_f6_03.as_posix(), DEFAULT_OPTIONS))

        p_f6_04 = build_v9_world(
            fdir / "f6_04_vehicle",
            world_json=make_v9_world_json(name="w", title="War Machine"),
            scenes=[make_v9_scene("s1", "Avernus Plains", tokens=[make_v9_token("t1", "Demon Grinder", actor_id="vm1")])],
            actors=[
                make_v9_actor(
                    "vm1",
                    "Demon Grinder",
                    actor_type="npc",
                    ac_flat=19,
                    ac_calc="flat",
                    hp_value=200,
                    hp_max=200,
                    cr=0,
                    extra_details={"type": {"value": "custom", "custom": "vehicle (40,000 lb.)"}},
                )
            ],
        )
        cls.sample_paths["t1_f6_04"] = p_f6_04
        cases.append(ProbeCaseSpec("t1_f6_04", p_f6_04.as_posix(), DEFAULT_OPTIONS))

        p_f6_05 = build_v9_world(
            fdir / "f6_05_mixed",
            world_json=make_v9_world_json(name="w", title="Mixed Encounter"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Skirmish",
                    tokens=[
                        make_v9_token("t_pc", "Kaelen", actor_id="pc1", x=150, y=150, disposition=1),
                        make_v9_token("t_npc", "Bugbear", actor_id="npc1", x=450, y=150, disposition=-1),
                    ],
                )
            ],
            actors=[
                make_v9_actor("pc1", "Kaelen", actor_type="character", ac_flat=17, hp_value=30, hp_max=30, level=3),
                make_v9_actor("npc1", "Bugbear", actor_type="npc", ac_flat=16, hp_value=27, hp_max=27, cr=1),
            ],
        )
        cls.sample_paths["t1_f6_05"] = p_f6_05
        cases.append(ProbeCaseSpec("t1_f6_05", p_f6_05.as_posix(), DEFAULT_OPTIONS))

        # --- F7 fixtures ---
        p_f7_01 = build_v9_world(
            fdir / "f7_01_walls",
            world_json=make_v9_world_json(name="w", title="Walls"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Wall Room",
                    walls=[
                        make_wall("w1", [100, 100, 500, 100]),
                        make_wall("w2", [500, 100, 500, 400]),
                    ],
                )
            ],
        )
        cls.sample_paths["t1_f7_01"] = p_f7_01
        cases.append(ProbeCaseSpec("t1_f7_01", p_f7_01.as_posix(), DEFAULT_OPTIONS))

        p_f7_02 = build_v9_world(
            fdir / "f7_02_doors",
            world_json=make_v9_world_json(name="w", title="Doors"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Door Hall",
                    walls=[
                        make_wall("d1", [100, 100, 200, 100], door=1, ds=0),
                        make_wall("d2", [200, 100, 300, 100], door=1, ds=1),
                    ],
                )
            ],
        )
        cls.sample_paths["t1_f7_02"] = p_f7_02
        cases.append(ProbeCaseSpec("t1_f7_02", p_f7_02.as_posix(), DEFAULT_OPTIONS))

        p_f7_03 = build_v9_world(
            fdir / "f7_03_window",
            world_json=make_v9_world_json(name="w", title="Window"),
            scenes=[make_v9_scene("s1", "Glass Hall", walls=[make_wall("win1", [100, 200, 250, 200], door=0, move=20, sight=0, light=0)])],
        )
        cls.sample_paths["t1_f7_03"] = p_f7_03
        cases.append(ProbeCaseSpec("t1_f7_03", p_f7_03.as_posix(), DEFAULT_OPTIONS))

        p_f7_04 = build_v9_world(
            fdir / "f7_04_lights",
            world_json=make_v9_world_json(name="w", title="Lights"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Torch Room",
                    grid=150,
                    grid_distance=5,
                    lights=[
                        make_light("l1", 300, 300, bright=20, dim=40, angle=360),
                        make_light("l2", 600, 300, bright=15, dim=30, angle=90),
                    ],
                )
            ],
        )
        cls.sample_paths["t1_f7_04"] = p_f7_04
        cases.append(ProbeCaseSpec("t1_f7_04", p_f7_04.as_posix(), DEFAULT_OPTIONS))

        p_f7_05 = build_v9_world(
            fdir / "f7_05_grid",
            world_json=make_v9_world_json(name="w", title="Grid"),
            scenes=[make_v9_scene("s1", "Grid Room", grid_type=1, grid=100, shift_x=15, shift_y=25, grid_color="#336699", grid_alpha=0.4)],
        )
        cls.sample_paths["t1_f7_05"] = p_f7_05
        cases.append(ProbeCaseSpec("t1_f7_05", p_f7_05.as_posix(), DEFAULT_OPTIONS))

        # --- F8 fixtures ---
        p_f8_01 = build_v9_world(
            fdir / "f8_01_skip_items",
            world_json=make_v9_world_json(name="w", title="Skip Items"),
            scenes=[make_v9_scene("s1", "Wizard Tower", tokens=[make_v9_token("t1", "Morden", actor_id="pc1", disposition=1)])],
            actors=[
                make_v9_actor(
                    "pc1",
                    "Morden",
                    actor_type="character",
                    items=[
                        {"_id": "sp1", "name": "Fireball", "type": "spell"},
                        {"_id": "wp1", "name": "Longsword", "type": "weapon"},
                    ],
                )
            ],
            items=[
                {"_id": "i1", "name": "Magic Missile", "type": "spell"},
                {"_id": "i2", "name": "Healing Potion", "type": "consumable"},
            ],
        )
        cls.sample_paths["t1_f8_01"] = p_f8_01
        cases.append(ProbeCaseSpec("t1_f8_01", p_f8_01.as_posix(), DEFAULT_OPTIONS))

        p_f8_02 = build_v9_world(
            fdir / "f8_02_skip_extra_dbs",
            world_json=make_v9_world_json(name="w", title="Extra DBs"),
            scenes=[make_v9_scene("s1", "Main Hall")],
            actors=[make_v9_actor("a1", "Guard", actor_type="npc")],
            extra_dbs={
                "journal.db": [{"_id": "j1", "name": "Secret Diary"}],
                "macros.db": [{"_id": "m1", "name": "Attack Macro"}],
                "tables.db": [{"_id": "tb1", "name": "Loot Table"}],
                "playlists.db": [{"_id": "pl1", "name": "Battle Music"}],
                "combats.db": [{"_id": "cb1", "name": "Encounter 1"}],
                "cards.db": [{"_id": "cd1", "name": "Deck of Many"}],
            },
        )
        cls.sample_paths["t1_f8_02"] = p_f8_02
        cases.append(ProbeCaseSpec("t1_f8_02", p_f8_02.as_posix(), DEFAULT_OPTIONS))

        p_f8_03 = build_v9_world(
            fdir / "f8_03_local_assets",
            world_json=make_v9_world_json(name="w", title="Local Images"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Asset Map",
                    img="scenes/map.png",
                    tokens=[make_v9_token("t1", "Hero", actor_id="pc1", img="tokens/hero.webp", disposition=1)],
                )
            ],
            actors=[make_v9_actor("pc1", "Hero", actor_type="character", img="tokens/hero.webp")],
            assets={"scenes/map.png": png, "tokens/hero.webp": webp},
        )
        cls.sample_paths["t1_f8_03"] = p_f8_03
        cases.append(ProbeCaseSpec("t1_f8_03", p_f8_03.as_posix(), DEFAULT_OPTIONS))

        p_f8_04 = build_v9_world(
            fdir / "f8_04_remote_url",
            world_json=make_v9_world_json(name="w", title="Remote URL"),
            scenes=[make_v9_scene("s1", "Avernus Map", img="https://example.com/avernus_map.png")],
        )
        cls.sample_paths["t1_f8_04"] = p_f8_04
        cases.append(
            ProbeCaseSpec(
                "t1_f8_04",
                p_f8_04.as_posix(),
                {**DEFAULT_OPTIONS, "proxy": "http://127.0.0.1:7890"},
                archive_policy="mock_ok",
            )
        )

        p_f8_05 = build_v9_world(
            fdir / "f8_05_options_parity",
            world_json=make_v9_world_json(name="w", title="Options Parity"),
            scenes=[make_v9_scene("s1", "Parity Room", tokens=[make_v9_token("t1", "Goblin", actor_id="n1")])],
            actors=[make_v9_actor("n1", "Goblin", actor_type="npc")],
        )
        cls.sample_paths["t1_f8_05"] = p_f8_05
        cases.append(ProbeCaseSpec("t1_f8_05_empty_opts", p_f8_05.as_posix(), {}))
        cases.append(ProbeCaseSpec("t1_f8_05_default_opts", p_f8_05.as_posix(), dict(DEFAULT_OPTIONS)))

        cls.batch = cls.session.run_batch(cases, timeout_seconds=120)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.session.cleanup()

    # -----------------------------------------------------------------------
    # F1: Plugin Manifest, Build & Validate
    # -----------------------------------------------------------------------

    def test_t1_f1_01_validate_cli_contract(self) -> None:
        cfg = self.session.cfg
        report = validate_mod_dir(cfg.mods_dir / MOD_NAME, mod_name=MOD_NAME, sdk_dir=cfg.sdk_dir)
        self.assertTrue(report.ok, f"validate_mod_dir errors: {report.errors}")
        self.assertEqual(report.errors, [])
        self.assertGreaterEqual(report.runtime_file_count, 2)
        self.assertGreater(report.estimated_bytes, 0)

    def test_t1_f1_02_plugin_json_schema_and_settings(self) -> None:
        pjson_path = self.session.cfg.mods_dir / MOD_NAME / "plugin.json"
        raw = pjson_path.read_bytes()
        self.assertFalse(raw.startswith(UTF8_BOM), "plugin.json must not have UTF-8 BOM")
        data = json.loads(raw.decode("utf-8"))
        self.assertEqual(data["schema"], "fus.session-plugin.v1")
        self.assertEqual(data["host_api"], 1)
        self.assertEqual(data["scope"], "session")
        self.assertEqual(data["id"], "fvtt_world_importer")
        self.assertEqual(data["entry"], "entry.gd")
        self.assertEqual(data["import_extensions"], ["zip", "json"])
        by_id = {s["id"]: s for s in data["settings"]}
        self.assertEqual(
            set(by_id.keys()),
            {"proxy", "import_scenes", "import_characters", "import_monsters", "include_hidden", "skip_missing_assets"},
        )
        self.assertEqual((by_id["proxy"]["type"], by_id["proxy"]["default"]), ("string", ""))
        for bkey in ("import_scenes", "import_characters", "import_monsters", "include_hidden", "skip_missing_assets"):
            self.assertEqual((by_id[bkey]["type"], by_id[bkey]["default"]), ("bool", True))

    def test_t1_f1_03_build_zip_and_exclusions(self) -> None:
        artifact = build_mod(MOD_NAME, config=self.session.cfg, bump_dev=False)
        self.assertEqual(validate_zip_archive(artifact.zip_path), [])
        bm = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
        with zipfile.ZipFile(artifact.zip_path, "r") as zf:
            names = set(zf.namelist())
            for req in ("plugin.json", "entry.gd", "lib/fu_sdk/v1.gd", "lib/fu_sdk/adapters/host_v1_adapter.gd"):
                self.assertIn(req, names)
            for excluded in NON_RUNTIME_FILENAMES:
                self.assertNotIn(excluded, names)
            self.assertFalse(any("tests/" in n for n in names))
            for fname, expected_sha in bm["file_hashes"].items():
                self.assertEqual(hashlib.sha256(zf.read(fname)).hexdigest(), expected_sha)

    def test_t1_f1_04_verify_host_with_minimal_world_json(self) -> None:
        assert self.session.run_dir is not None
        iso_cfg = WorkspaceConfig(
            workspace_root=WORKSPACE_ROOT.resolve(),
            mods_dir=self.session.cfg.mods_dir,
            sdk_dir=self.session.cfg.sdk_dir,
            build_dir=(self.session.run_dir / "iso_build").resolve(),
            cache_dir=(self.session.run_dir / "iso_cache").resolve(),
            fuvtt_install_dir=self.session.cfg.fuvtt_install_dir,
            fus_repo_dir=self.session.cfg.fus_repo_dir,
            fus_source_ref=self.session.cfg.fus_source_ref,
            godot_bin=self.session.godot_bin,
        )
        vres = verify_mod_with_host(MOD_NAME, config=iso_cfg, sample_path=self.sample_paths["t1_f3_01"])
        self.assertTrue(vres.ok, f"verify-host failed: failures={vres.failures}, logs={vres.log_errors}")
        self.assertEqual(vres.log_errors, [])
        self.assertGreater(vres.serialized_bytes, 0)
        report = json.loads(vres.report_path.read_text(encoding="utf-8"))
        self.assertTrue(report["inspect_summary"]["ok"])
        self.assertIn("unsupported", report["inspect_summary"]["counts"])

    def test_t1_f1_05_sync_into_isolated_session_plugins(self) -> None:
        assert self.session.run_dir is not None
        sp_dir = self.session.run_dir / "session_plugins"
        sres = sync_mod(MOD_NAME, target_dir=sp_dir, config=self.session.cfg, allow_same_version=True)
        self.assertTrue(sres.registry_path.is_file())
        reg = json.loads(sres.registry_path.read_text(encoding="utf-8"))
        entry = reg["plugins"]["fvtt_world_importer"]
        self.assertEqual(entry["sha256"], sres.sha256)
        self.assertEqual(entry["directory"], f"packages/fvtt_world_importer/{sres.sha256}")
        self.assertTrue(entry["enabled"])
        self.assertEqual(entry["file_hashes"], compute_directory_file_hashes(sres.package_dir))
        self.assertEqual(entry["settings"], DEFAULT_OPTIONS)

    # -----------------------------------------------------------------------
    # F2: .zip World Archive Ingestion
    # -----------------------------------------------------------------------

    def test_t1_f2_01_depth0_zip(self) -> None:
        res = self.batch.results["t1_f2_01"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f2_01"])
        self.assertGreaterEqual(ins["counts"]["maps"], 1)
        self.assertGreaterEqual(ins["counts"]["records"], 2)
        self.assertGreater(ins["decoded_bytes"], 0)
        world = assert_valid_practice_world_v3(self, res)
        self.assertIsNotNone(get_floor_by_name(world, "Depth0 Scene"))

    def test_t1_f2_02_depth1_zip_with_local_asset(self) -> None:
        res = self.batch.results["t1_f2_02"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f2_02"])
        self.assertGreaterEqual(ins["counts"]["maps"], 1)
        self.assertGreaterEqual(ins["counts"]["images"], 1)
        world = assert_valid_practice_world_v3(self, res)
        self.assertIsNotNone(get_floor_by_name(world, "Depth1 Scene"))
        self.assertFalse(any("bg.png" in w for w in res.host_trace.get("warnings", [])))

    def test_t1_f2_03_non_ascii_cjk_zip(self) -> None:
        res = self.batch.results["t1_f2_03"]
        assert_valid_inspect_ok(self, res, self.sample_paths["t1_f2_03"])
        world = assert_valid_practice_world_v3(self, res)
        self.assertIsNotNone(get_floor_by_name(world, "翠绿营地"))

    def test_t1_f2_04_v14_leveldb_only_zip(self) -> None:
        res = self.batch.results["t1_f2_04"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f2_04"])
        self.assertGreaterEqual(ins["counts"]["maps"], 1)
        self.assertGreaterEqual(ins["counts"]["characters"] + ins["counts"]["objects"], 1)
        world = assert_valid_practice_world_v3(self, res)
        self.assertIsNotNone(get_floor_by_name(world, "V14 Zip Scene"))
        assert_actor_preserved(self, world, "V14 Ranger", expected_level=4)

    def test_t1_f2_05_mixed_worlds_and_relative_paths_in_zip(self) -> None:
        res = self.batch.results["t1_f2_05"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f2_05"])
        self.assertGreaterEqual(ins["counts"]["images"], 2)
        world = assert_valid_practice_world_v3(self, res)
        self.assertIsNotNone(get_floor_by_name(world, "Mixed Path Scene"))
        warnings = " ".join(res.host_trace.get("warnings", []))
        self.assertNotIn("map.png", warnings)
        self.assertNotIn("token.png", warnings)

    # -----------------------------------------------------------------------
    # F3: Unpacked Directory Ingestion
    # -----------------------------------------------------------------------

    def test_t1_f3_01_unpacked_v9_dir(self) -> None:
        res = self.batch.results["t1_f3_01"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f3_01"])
        self.assertGreaterEqual(ins["decoded_bytes"], ins["source_bytes"])
        self.assertGreaterEqual(ins["counts"]["maps"], 1)
        self.assertGreaterEqual(ins["counts"]["characters"], 1)
        world = assert_valid_practice_world_v3(self, res)
        self.assertIsNotNone(get_floor_by_name(world, "V9 Dir Scene"))

    def test_t1_f3_02_unpacked_v14_leveldb_dir(self) -> None:
        res = self.batch.results["t1_f3_02"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f3_02"])
        self.assertGreaterEqual(ins["counts"]["maps"], 1)
        self.assertGreaterEqual(ins["counts"]["characters"] + ins["counts"]["objects"], 1)
        world = assert_valid_practice_world_v3(self, res)
        self.assertIsNotNone(get_floor_by_name(world, "LevelDB Scene"))
        assert_actor_preserved(self, world, "LevelDB Orc", expected_cr=2)

    def test_t1_f3_03_dual_format_no_double_counting(self) -> None:
        res = self.batch.results["t1_f3_03"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f3_03"])
        self.assertEqual(ins["counts"]["maps"], 2, "Dual NeDB+LevelDB dir must not double-count scenes")
        world = assert_valid_practice_world_v3(self, res)
        names = [f["name"] for f in get_floors(world)]
        self.assertIn("Dual One", names)
        self.assertIn("Dual Two", names)
        self.assertEqual(len(get_floors(world)), 2)

    def test_t1_f3_04_folders_db_resolution(self) -> None:
        res = self.batch.results["t1_f3_04"]
        assert_valid_inspect_ok(self, res, self.sample_paths["t1_f3_04"])
        world = assert_valid_practice_world_v3(self, res)
        self.assertIsNotNone(get_floor_by_name(world, "Boss Lair"))
        assert_actor_preserved(self, world, "Dragon", expected_cr=12)

    def test_t1_f3_05_world_json_title_and_background(self) -> None:
        res = self.batch.results["t1_f3_05"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f3_05"])
        self.assertGreaterEqual(ins["counts"]["records"], 2)
        world = assert_valid_practice_world_v3(self, res)
        self.assertIsNotNone(get_floor_by_name(world, "Campaign Start"))
        self.assertFalse(any("splash.png" in w for w in res.host_trace.get("warnings", [])))

    # -----------------------------------------------------------------------
    # F4: Scene -> Floor / Layer / Map / Tile Mapping
    # -----------------------------------------------------------------------

    def test_t1_f4_01_single_active_scene_floor_and_layers(self) -> None:
        res = self.batch.results["t1_f4_01"]
        world = assert_valid_practice_world_v3(self, res)
        fl = get_floor_by_name(world, "Elturel Keep")
        self.assertIsNotNone(fl)
        assert fl is not None
        self.assertEqual(world["catalog"]["active_floor_uid"], fl["floor_uid"])
        kinds = {l["kind"] for l in get_floor_layers(world, fl["floor_uid"])}
        self.assertTrue({"map", "entity", "obstacle"}.issubset(kinds))
        map_ents = get_entities_on_floor(world, fl["floor_uid"], layer_kind="map")
        self.assertGreaterEqual(len(map_ents), 1)
        self.assertIn(map_ents[0].get("entity_type"), ("map", "object"))
        self.assertTrue(bool(str(map_ents[0].get("display_name", "")).strip()))

    def test_t1_f4_02_multi_scene_floors_and_active_uid(self) -> None:
        res = self.batch.results["t1_f4_02"]
        world = assert_valid_practice_world_v3(self, res)
        fa = get_floor_by_name(world, "Floor A")
        fb = get_floor_by_name(world, "Floor B")
        self.assertIsNotNone(fa)
        self.assertIsNotNone(fb)
        assert fa is not None and fb is not None
        self.assertNotEqual(fa["floor_uid"], fb["floor_uid"])
        self.assertEqual(world["catalog"]["active_floor_uid"], fb["floor_uid"])
        for fl in (fa, fb):
            self.assertTrue({"map", "entity", "obstacle"}.issubset({l["kind"] for l in get_floor_layers(world, fl["floor_uid"])}))

    def test_t1_f4_03_scene_tiles_rotation_and_canonical_z(self) -> None:
        res = self.batch.results["t1_f4_03"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f4_03"])
        self.assertGreaterEqual(ins["counts"]["objects"] + ins["counts"]["maps"], 2)
        world = assert_valid_practice_world_v3(self, res)
        fl = get_floor_by_name(world, "Tile Room")
        self.assertIsNotNone(fl)
        assert fl is not None
        ents = get_entities_on_floor(world, fl["floor_uid"])
        rotated = [e for e in ents if abs(float(e["xform"]["rot"])) > 0.5]
        self.assertGreaterEqual(len(rotated), 1, "Expected 90-deg tile to have non-zero rotation")

    def test_t1_f4_04_scene_background_and_foreground_order(self) -> None:
        res = self.batch.results["t1_f4_04"]
        world = assert_valid_practice_world_v3(self, res)
        fl = get_floor_by_name(world, "Layered Roof")
        self.assertIsNotNone(fl)
        assert fl is not None
        map_ents = get_entities_on_floor(world, fl["floor_uid"], layer_kind="map")
        self.assertGreaterEqual(len(map_ents), 2, "Expected both background and foreground entities on map layer")

    def test_t1_f4_05_import_scenes_false_toggle(self) -> None:
        res = self.batch.results["t1_f4_05"]
        world = assert_valid_practice_world_v3(self, res)
        self.assertEqual(len(get_entities_by_layer_kind(world, "map")), 0)
        assert_actor_preserved(self, world, "Alden", expected_level=2)

    # -----------------------------------------------------------------------
    # F5: Character Resource Creation
    # -----------------------------------------------------------------------

    def test_t1_f5_01_placed_character_token_and_stats(self) -> None:
        res = self.batch.results["t1_f5_01"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f5_01"])
        self.assertGreaterEqual(ins["counts"]["characters"], 1)
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(
            self,
            world,
            "Lyra",
            expected_ac=16,
            expected_hp=38,
            expected_level=5,
            require_unit_entity=True,
        )

    def test_t1_f5_02_unplaced_standalone_character(self) -> None:
        res = self.batch.results["t1_f5_02"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f5_02"])
        self.assertGreaterEqual(ins["counts"]["characters"], 1)
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(self, world, "Thorin", expected_ac=18, expected_hp=45, expected_level=4)

    def test_t1_f5_03_three_distinct_characters(self) -> None:
        res = self.batch.results["t1_f5_03"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f5_03"])
        self.assertGreaterEqual(ins["counts"]["characters"], 3)
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(self, world, "PC1", expected_ac=14, expected_hp=20, expected_level=2, require_unit_entity=True)
        assert_actor_preserved(self, world, "PC2", expected_ac=16, expected_hp=32, expected_level=4, require_unit_entity=True)
        assert_actor_preserved(self, world, "PC3", expected_ac=19, expected_hp=50, expected_level=6, require_unit_entity=True)

    def test_t1_f5_04_character_token_2x2_size_scaling(self) -> None:
        res = self.batch.results["t1_f5_04"]
        world = assert_valid_practice_world_v3(self, res)
        units = {u["display_name"]: u for u in get_unit_entities(world)}
        self.assertIn("Halfling", units)
        self.assertIn("Goliath", units)
        small_area = units["Halfling"]["entity_size"].x * units["Halfling"]["entity_size"].y
        big_area = units["Goliath"]["entity_size"].x * units["Goliath"]["entity_size"].y
        self.assertGreater(big_area, small_area)

    def test_t1_f5_05_character_token_vision(self) -> None:
        res = self.batch.results["t1_f5_05"]
        world = assert_valid_practice_world_v3(self, res)
        units = [u for u in get_unit_entities(world) if "Elrond" in u.get("display_name", "")]
        self.assertGreaterEqual(len(units), 1)
        vis = get_component(units[0], "comp_simple_vision.gd")
        self.assertIsNotNone(vis)
        assert vis is not None
        self.assertTrue(vis["state"]["enabled"])
        self.assertGreater(float(vis["state"]["radius"]), 0.0)

    # -----------------------------------------------------------------------
    # F6: Monster / NPC Resource Creation
    # -----------------------------------------------------------------------

    def test_t1_f6_01_placed_npc_token_and_stats(self) -> None:
        res = self.batch.results["t1_f6_01"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f6_01"])
        self.assertGreaterEqual(ins["counts"]["characters"] + ins["counts"]["objects"], 1)
        self.assertGreaterEqual(ins["counts"]["records"], 2)
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(self, world, "Goblin", expected_ac=15, expected_hp=7, expected_cr=0.25, require_unit_entity=True)

    def test_t1_f6_02_unplaced_standalone_npc(self) -> None:
        res = self.batch.results["t1_f6_02"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f6_02"])
        self.assertGreaterEqual(ins["counts"]["characters"] + ins["counts"]["objects"], 1)
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(self, world, "Aboleth", expected_ac=17, expected_hp=135, expected_cr=10)

    def test_t1_f6_03_three_npcs_across_folders(self) -> None:
        res = self.batch.results["t1_f6_03"]
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(self, world, "Imp", expected_ac=13, expected_hp=10, expected_cr=1)
        assert_actor_preserved(self, world, "Cultist", expected_ac=12, expected_hp=9, expected_cr=0.125)
        assert_actor_preserved(self, world, "Pit Fiend", expected_ac=19, expected_hp=300, expected_cr=20)

    def test_t1_f6_04_custom_vehicle_npc(self) -> None:
        res = self.batch.results["t1_f6_04"]
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(self, world, "Demon Grinder", expected_ac=19, expected_hp=200, require_unit_entity=True)

    def test_t1_f6_05_mixed_pc_and_npc_scene(self) -> None:
        res = self.batch.results["t1_f6_05"]
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(self, world, "Kaelen", expected_ac=17, expected_hp=30, expected_level=3, require_unit_entity=True)
        assert_actor_preserved(self, world, "Bugbear", expected_ac=16, expected_hp=27, expected_cr=1, require_unit_entity=True)

    # -----------------------------------------------------------------------
    # F7: Walls, Doors, Windows, Lights & Grid
    # -----------------------------------------------------------------------

    def test_t1_f7_01_two_point_walls_to_polygon_obstacles(self) -> None:
        res = self.batch.results["t1_f7_01"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f7_01"])
        self.assertGreaterEqual(ins["counts"]["walls"], 2)
        world = assert_valid_practice_world_v3(self, res)
        walls = get_obstacle_entities(world, kind="wall")
        self.assertGreaterEqual(len(walls), 1)
        for w in walls:
            paths = w["components"][0]["state"]["vector_drawing"]["paths"]
            self.assertGreaterEqual(len(paths), 1)
            for ring in paths:
                self.assertGreaterEqual(len(ring), 3)

    def test_t1_f7_02_closed_and_open_doors(self) -> None:
        res = self.batch.results["t1_f7_02"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f7_02"])
        self.assertGreaterEqual(ins["counts"]["doors"], 2)
        world = assert_valid_practice_world_v3(self, res)
        doors = get_obstacle_entities(world, kind="door")
        self.assertGreaterEqual(len(doors), 2)
        open_states = {bool(d["components"][0]["state"]["vector_drawing"]["source"].get("open")) for d in doors}
        self.assertEqual(open_states, {False, True})

    def test_t1_f7_03_window_barrier(self) -> None:
        res = self.batch.results["t1_f7_03"]
        world = assert_valid_practice_world_v3(self, res)
        windows = get_obstacle_entities(world, kind="window")
        self.assertGreaterEqual(len(windows), 1)

    def test_t1_f7_04_scene_lights(self) -> None:
        res = self.batch.results["t1_f7_04"]
        world = assert_valid_practice_world_v3(self, res)
        light_comps = [
            get_component(e, "comp_simple_light.gd")
            for e in get_entities(world)
            if get_component(e, "comp_simple_light.gd") is not None
        ]
        self.assertGreaterEqual(len(light_comps), 2)
        angles = {round(float(c["state"]["view_angle"]), 1) for c in light_comps if c is not None}
        self.assertIn(360.0, angles)
        self.assertIn(90.0, angles)
        for c in light_comps:
            assert c is not None
            self.assertTrue(c["state"]["enabled"])
            self.assertGreater(float(c["state"]["radius"]), 0.0)

    def test_t1_f7_05_square_grid_alignment(self) -> None:
        res = self.batch.results["t1_f7_05"]
        world = assert_valid_practice_world_v3(self, res)
        fl = get_floor_by_name(world, "Grid Room")
        self.assertIsNotNone(fl)
        entries = world.get("modules", {}).get("entries", {})
        self.assertIn("grid_alignment", entries, "Expected grid_alignment module for square grid scene")
        ga = entries["grid_alignment"]
        self.assertEqual(ga["version"], 1)
        st = ga["state"]
        self.assertEqual(st.get("schema"), "fus.grid_alignment.config")
        self.assertTrue(8.0 <= float(st["cell_size"]) <= 4096.0)
        self.assertTrue(0.5 <= float(st["line_width"]) <= 4.0)
        self.assertTrue(0.0 <= float(st["snap_strength"]) <= 1.0)

    # -----------------------------------------------------------------------
    # F8: Unsupported Resource Filtering, Asset Archival & Resilience
    # -----------------------------------------------------------------------

    def test_t1_f8_01_skip_spells_and_equipment_resources(self) -> None:
        res = self.batch.results["t1_f8_01"]
        world = assert_valid_practice_world_v3(self, res)
        names = {str(e.get("display_name", "")) for e in get_entities(world)}
        for skipped in ("Fireball", "Longsword", "Magic Missile", "Healing Potion"):
            self.assertNotIn(skipped, names)
        assert_actor_preserved(self, world, "Morden", require_unit_entity=True)

    def test_t1_f8_02_skip_non_scene_actor_collections(self) -> None:
        res = self.batch.results["t1_f8_02"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f8_02"])
        self.assertGreaterEqual(ins["counts"]["maps"], 1)
        world = assert_valid_practice_world_v3(self, res)
        names = {str(e.get("display_name", "")) for e in get_entities(world)}
        for skipped in ("Secret Diary", "Attack Macro", "Loot Table", "Battle Music", "Encounter 1", "Deck of Many"):
            self.assertNotIn(skipped, names)

    def test_t1_f8_03_local_png_and_webp_safe_sprite_path(self) -> None:
        res = self.batch.results["t1_f8_03"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f8_03"])
        self.assertGreaterEqual(ins["counts"]["images"], 2)
        world = assert_valid_practice_world_v3(self, res)
        fl = get_floor_by_name(world, "Asset Map")
        self.assertIsNotNone(fl)
        self.assertGreaterEqual(len(get_unit_entities(world)), 1)

    def test_t1_f8_04_remote_https_url_archive_image(self) -> None:
        res = self.batch.results["t1_f8_04"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t1_f8_04"])
        self.assertIn("https://example.com/avernus_map.png", ins["assets"])
        self.assertGreaterEqual(ins["unique_images"], 1)
        world = assert_valid_practice_world_v3(self, res)
        self.assertIn("https://example.com/avernus_map.png", res.host_trace.get("archived_urls", []))
        reqs = res.host_trace.get("archived_requests", [])
        self.assertTrue(any(r.get("proxy") == "http://127.0.0.1:7890" for r in reqs))
        map_ents = get_entities_by_layer_kind(world, "map")
        self.assertGreaterEqual(len(map_ents), 1)
        sp = map_ents[0]["components"][0]["state"].get("sprite_path", "")
        self.assertTrue(sp.startswith("asset://"), f"Expected remote archived sprite_path asset://..., got {sp!r}")

    def test_t1_f8_05_empty_options_vs_explicit_defaults_parity(self) -> None:
        r_empty = self.batch.results["t1_f8_05_empty_opts"]
        r_def = self.batch.results["t1_f8_05_default_opts"]
        w_empty = assert_valid_practice_world_v3(self, r_empty)
        w_def = assert_valid_practice_world_v3(self, r_def)
        self.assertEqual(len(get_floors(w_empty)), len(get_floors(w_def)))
        self.assertEqual(len(get_entities(w_empty)), len(get_entities(w_def)))
        self.assertGreaterEqual(len(get_unit_entities(w_empty)), 1)
