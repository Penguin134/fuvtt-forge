"""Tier 2: 45 Boundary, Corner, Negative & Hostile-Input Tests (`T2-F1-01` .. `T2-F8-07`)."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import unittest
import zipfile

from fuvtt_devtools.packager import build_mod
from fuvtt_devtools.validator import UTF8_BOM, strip_gdscript_comments, validate_mod_dir, validate_zip_archive

from . import DEFAULT_OPTIONS
from .assertions import (
    assert_actor_preserved,
    assert_case_clean,
    assert_valid_inspect_fail,
    assert_valid_inspect_ok,
    assert_valid_practice_world_v3,
    assert_valid_prepare_fail,
    find_actor_records,
    get_component,
    get_entities,
    get_entities_by_layer_kind,
    get_floors,
    get_obstacle_entities,
    get_unit_entities,
)
from .fixtures import (
    build_v14_world,
    build_v9_world,
    make_armor_item,
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
from .harness import (
    BatchExecutionSummary,
    MOD_NAME,
    ProbeCaseSpec,
    ProbeSession,
)


def _copy_mod_to(src_mod_dir: Path, dst_mod_dir: Path) -> None:
    if dst_mod_dir.exists():
        shutil.rmtree(dst_mod_dir)
    shutil.copytree(src_mod_dir, dst_mod_dir)


class Tier2BoundaryTests(unittest.TestCase):
    """45 boundary, corner-case, negative, and resilience tests across F1..F8."""

    session: ProbeSession
    batch: BatchExecutionSummary
    sample_paths: dict[str, Path]

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = ProbeSession(name_prefix="tier2")
        cls.session.setup(require_godot=True)
        assert cls.session.fixture_dir is not None
        fdir = cls.session.fixture_dir
        cls.sample_paths = {}
        cases: list[ProbeCaseSpec] = []
        png = make_png_bytes(4, 4)

        def add_case(
            cid: str,
            path: Path,
            opts: dict | None = None,
            *,
            run_inspect: bool = True,
            run_prepare: bool = True,
            cancel_policy: str = "never",
            archive_policy: str = "mock_ok",
        ) -> None:
            cls.sample_paths[cid] = path
            cases.append(
                ProbeCaseSpec(
                    case_id=cid,
                    sample_path=path.as_posix(),
                    options=DEFAULT_OPTIONS if opts is None else opts,
                    run_inspect=run_inspect,
                    run_prepare=run_prepare,
                    cancel_policy=cancel_policy,
                    archive_policy=archive_policy,
                )
            )

        # --- F2 ZIP boundaries ---
        src_valid = fdir / "valid_zip_base"
        build_v9_world(
            src_valid,
            world_json=make_v9_world_json(name="valid", title="Valid"),
            scenes=[make_v9_scene("s1", "Base Scene")],
        )
        full_zip = pack_world_zip(src_valid, fdir / "full_valid.zip", depth=0)
        raw_zip = full_zip.read_bytes()
        trunc_zip = fdir / "t2_f2_01_trunc.zip"
        trunc_zip.write_bytes(raw_zip[: len(raw_zip) // 2])
        add_case("t2_f2_01_trunc", trunc_zip)

        corrupt_crc = fdir / "t2_f2_01_crc.zip"
        corrupt_buf = bytearray(raw_zip)
        mid_off = min(len(corrupt_buf) - 30, 45)
        corrupt_buf[mid_off] ^= 0xFF
        corrupt_buf[mid_off + 1] ^= 0x55
        corrupt_crc.write_bytes(bytes(corrupt_buf))
        add_case("t2_f2_01_crc", corrupt_crc)

        fake_txt = fdir / "t2_f2_02_txt.zip"
        fake_txt.write_bytes(b"not a zip archive at all\n")
        add_case("t2_f2_02_txt", fake_txt)

        fake_png = fdir / "t2_f2_02_png.zip"
        fake_png.write_bytes(png)
        add_case("t2_f2_02_png", fake_png)

        add_case("t2_f2_03_d0", full_zip)
        d1_zip = pack_world_zip(src_valid, fdir / "t2_f2_03_d1.zip", depth=1, root_name="sub")
        add_case("t2_f2_03_d1", d1_zip)
        d2_zip = pack_world_zip(src_valid, fdir / "t2_f2_03_d2.zip", depth=2, root_name="a/b")
        add_case("t2_f2_03_d2", d2_zip)

        no_wj_dir = fdir / "no_wj_dir"
        build_v9_world(no_wj_dir, world_json=None, scenes=[make_v9_scene("s1", "Orphan")])
        no_wj_zip = pack_world_zip(no_wj_dir, fdir / "t2_f2_04_nowj.zip", depth=0)
        add_case("t2_f2_04", no_wj_zip)

        junk_zip = pack_world_zip(
            src_valid,
            fdir / "t2_f2_05_junk.zip",
            depth=1,
            root_name="myworld",
            macosx_junk=True,
            ds_store=True,
        )
        add_case("t2_f2_05", junk_zip)

        ambig_zip = pack_world_zip(
            src_valid,
            fdir / "t2_f2_06_ambig.zip",
            depth=1,
            root_name="a",
            extra_entries={"b/world.json": json.dumps(make_v9_world_json(name="b")).encode("utf-8")},
        )
        add_case("t2_f2_06_ambig", ambig_zip)

        trav_dir = fdir / "trav_dir"
        build_v9_world(
            trav_dir,
            world_json=make_v9_world_json(name="trav", title="Traversal"),
            scenes=[make_v9_scene("s1", "Traversal Scene", img="../../etc/passwd")],
        )
        trav_zip = pack_world_zip(trav_dir, fdir / "t2_f2_06_trav.zip", depth=0)
        add_case("t2_f2_06_trav", trav_zip)

        # --- F3 Dir boundaries ---
        missing_wj = fdir / "missing_dir" / "world.json"
        add_case("t2_f3_01_missing", missing_wj)
        empty_dir = fdir / "empty_dir"
        empty_dir.mkdir(parents=True, exist_ok=True)
        add_case("t2_f3_01_dir", empty_dir)

        bad_trunc = fdir / "f3_02_trunc" / "world.json"
        bad_trunc.parent.mkdir(parents=True, exist_ok=True)
        bad_trunc.write_bytes(b'{ "name": "broken", ')
        add_case("t2_f3_02_trunc", bad_trunc)

        bad_arr = fdir / "f3_02_arr" / "world.json"
        bad_arr.parent.mkdir(parents=True, exist_ok=True)
        bad_arr.write_bytes(b'["not", "an", "object"]')
        add_case("t2_f3_02_arr", bad_arr)

        bad_empty = fdir / "f3_02_empty" / "world.json"
        bad_empty.parent.mkdir(parents=True, exist_ok=True)
        bad_empty.write_bytes(b"")
        add_case("t2_f3_02_empty", bad_empty)

        p_f3_03a = build_v9_world(
            fdir / "f3_03_partial_db",
            world_json=make_v9_world_json(name="p3", title="Partial DB"),
            scenes=[make_v9_scene("s1", "Good Scene")],
            raw_db_lines={"scenes.db": [b'{"_id":"bad","name":']},
        )
        add_case("t2_f3_03_partial", p_f3_03a)

        p_f3_03b = build_v9_world(
            fdir / "f3_03_garbage_db",
            world_json=make_v9_world_json(name="g3", title="Garbage DB"),
            raw_db_lines={"scenes.db": [b"\x00\xff\xfe\x80not_json"]},
        )
        add_case("t2_f3_03_garbage", p_f3_03b)

        p_f3_04a = build_v9_world(
            fdir / "f3_04_empty_dbs",
            world_json=make_v9_world_json(name="e0", title="Empty World"),
        )
        add_case("t2_f3_04_empty_dbs", p_f3_04a)

        p_f3_04b = build_v9_world(
            fdir / "f3_04_nodata",
            world_json=make_v9_world_json(name="e1", title="No Data Dir"),
            create_data_dir=False,
        )
        add_case("t2_f3_04_nodata", p_f3_04b)

        p_f3_05 = build_v9_world(
            fdir / "f3_05_tombstones",
            world_json=make_v9_world_json(name="tomb", title="Tombstones"),
            scenes=[
                make_v9_scene("s1", "Old Name", active=False),
                make_v9_scene("s2", "Deleted Scene", active=False),
                make_v9_scene("s1", "Updated Name", active=True),
                {"_id": "s2", "$$deleted": True},
            ],
            actors=[
                make_v9_actor("a1", "Old Hero", actor_type="character", level=1),
                make_v9_actor("a2", "Deleted Hero", actor_type="character", level=1),
                make_v9_actor("a1", "Updated Hero", actor_type="character", level=7),
                {"_id": "a2", "$$deleted": True},
            ],
        )
        add_case("t2_f3_05", p_f3_05)

        s1_wal = {
            "_id": "s1",
            "name": "WAL Updated",
            "active": True,
            "navigation": True,
            "width": 3000,
            "height": 2100,
            "padding": 0.0,
            "shiftX": 0,
            "shiftY": 0,
            "grid": {"size": 150, "type": 1, "distance": 5, "units": "ft", "color": "#000000", "alpha": 0.2},
            "levels": ["lvl1"],
            "initialLevel": "lvl1",
        }
        l1_wal = {"_id": "lvl1", "name": "Level 1", "background": {"src": "worlds/v14/wal.png"}, "foreground": None}
        p_f3_06 = build_v14_world(
            fdir / "f3_06_wal",
            world_json=make_v14_world_json(world_id="v14", title="WAL World"),
            scenes=[
                make_v9_scene("s1", "Base", active=False, img="worlds/v14/base.png"),
                make_v9_scene("s2", "ToBeDeleted", active=False, img="worlds/v14/base.png"),
            ],
            scene_wal_ops=[
                (
                    100,
                    [
                        ("put", b"!scenes!s1", json.dumps(s1_wal).encode("utf-8")),
                        ("put", b"!scenes.levels!s1.lvl1", json.dumps(l1_wal).encode("utf-8")),
                        ("delete", b"!scenes!s2", b""),
                    ],
                )
            ],
            assets={"base.png": png, "wal.png": png},
        )
        add_case("t2_f3_06", p_f3_06)

        # --- F4 Scene boundaries ---
        p_f4_01 = build_v9_world(
            fdir / "f4_01_gridless",
            world_json=make_v9_world_json(name="w", title="Gridless"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Gridless Map",
                    grid_type=0,
                    grid=0,
                    tiles=[make_tile("t1", "worlds/w/t.png")],
                    tokens=[make_v9_token("tok1", "Scout", actor_id="a1")],
                )
            ],
            actors=[make_v9_actor("a1", "Scout", actor_type="npc")],
            assets={"t.png": png},
        )
        add_case("t2_f4_01", p_f4_01)

        p_f4_02 = build_v9_world(
            fdir / "f4_02_tiny",
            world_json=make_v9_world_json(name="w", title="Tiny Dims"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Tiny Map",
                    width=0,
                    height=-10,
                    tiles=[make_tile("t1", "worlds/w/t.png", width=1, height=2)],
                    tokens=[make_v9_token("tok1", "ZeroScale", actor_id="a1", scale=0.0)],
                )
            ],
            actors=[make_v9_actor("a1", "ZeroScale", actor_type="npc")],
            assets={"t.png": png},
        )
        add_case("t2_f4_02", p_f4_02)

        p_f4_03 = build_v9_world(
            fdir / "f4_03_long_name",
            world_json=make_v9_world_json(name="w", title="Long Name"),
            scenes=[make_v9_scene("s1", "\x01\t  " + ("A" * 140) + "\n\x7f")],
        )
        add_case("t2_f4_03", p_f4_03)

        p_f4_04 = build_v9_world(
            fdir / "f4_04_null_img",
            world_json=make_v9_world_json(name="w", title="Null Img"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Overlapping Tiles",
                    img=None,
                    tiles=[
                        make_tile("t1", "worlds/w/a.png", z=10),
                        make_tile("t2", "worlds/w/b.png", z=5),
                        make_tile("t3", "worlds/w/c.png", z=20),
                    ],
                )
            ],
            assets={"a.png": png, "b.png": png, "c.png": png},
        )
        add_case("t2_f4_04", p_f4_04)

        p_f4_05 = build_v9_world(
            fdir / "f4_05_no_active",
            world_json=make_v9_world_json(name="w", title="All Inactive"),
            scenes=[
                make_v9_scene("s1", "First Inactive", active=False),
                make_v9_scene("s2", "Second Inactive", active=False),
            ],
        )
        add_case("t2_f4_05", p_f4_05)

        # --- F5 Character boundaries ---
        p_f5_01 = build_v9_world(
            fdir / "f5_01_armor_ac",
            world_json=make_v9_world_json(name="w", title="Armor AC"),
            scenes=[make_v9_scene("s1", "Barracks", tokens=[make_v9_token("t1", "Fighter", actor_id="pc1", disposition=1)])],
            actors=[
                make_v9_actor(
                    "pc1",
                    "Fighter",
                    actor_type="character",
                    abilities={"str": 16, "dex": 16, "con": 14, "int": 10, "wis": 10, "cha": 10},
                    ac_flat=None,
                    ac_calc="default",
                    items=[
                        make_armor_item("i1", "Half Plate", armor_type="medium", armor_value=15, dex_cap=2, equipped=True),
                        make_armor_item("i2", "Shield", armor_type="shield", armor_value=2, dex_cap=None, equipped=True),
                        make_armor_item("i3", "Plate", armor_type="heavy", armor_value=18, dex_cap=0, equipped=False),
                    ],
                )
            ],
        )
        add_case("t2_f5_01", p_f5_01)

        p_f5_02 = build_v9_world(
            fdir / "f5_02_unarmored_ac",
            world_json=make_v9_world_json(name="w", title="Unarmored AC"),
            scenes=[make_v9_scene("s1", "Tavern", tokens=[make_v9_token("t1", "Rogue", actor_id="pc1", disposition=1)])],
            actors=[
                make_v9_actor(
                    "pc1",
                    "Rogue",
                    actor_type="character",
                    abilities={"str": 10, "dex": 16, "con": 12, "int": 12, "wis": 10, "cha": 14},
                    ac_flat=None,
                    ac_calc="default",
                    items=[{"_id": "wp1", "name": "Dagger", "type": "weapon"}],
                )
            ],
        )
        add_case("t2_f5_02", p_f5_02)

        p_f5_03 = build_v9_world(
            fdir / "f5_03_skeleton_pc",
            world_json=make_v9_world_json(name="w", title="Minimal PC"),
            scenes=[make_v9_scene("s1", "Blank Map", tokens=[make_v9_token("t1", "Blank PC", actor_id="min_pc", disposition=1)])],
            actors=[{"_id": "min_pc", "name": "Blank PC", "type": "character"}],
        )
        add_case("t2_f5_03", p_f5_03)

        p_f5_04 = build_v9_world(
            fdir / "f5_04_no_chars",
            world_json=make_v9_world_json(name="w", title="Filter Chars"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Bridge",
                    tokens=[
                        make_v9_token("t1", "HeroPC", actor_id="pc1", disposition=1),
                        make_v9_token("t2", "TrollNPC", actor_id="npc1", disposition=-1),
                    ],
                )
            ],
            actors=[
                make_v9_actor("pc1", "HeroPC", actor_type="character"),
                make_v9_actor("npc1", "TrollNPC", actor_type="npc"),
            ],
        )
        add_case("t2_f5_04", p_f5_04, {**DEFAULT_OPTIONS, "import_characters": False, "import_monsters": True})

        v14_pc = {
            "_id": "pc_v14",
            "name": "V14 Paladin",
            "type": "character",
            "img": "worlds/w/pc.png",
            "system": {
                "abilities": {"str": {"value": 18}, "dex": {"value": 9}, "con": {"value": 14}, "int": {"value": 10}, "wis": {"value": 12}, "cha": {"value": 16}},
                "attributes": {"hp": {"value": 22, "max": 22}, "ac": {"flat": 18, "calc": "flat"}},
                "details": {"level": 3},
            },
            "prototypeToken": {"name": "V14 Paladin", "texture": {"src": "worlds/w/pc.png"}, "width": 1, "height": 1},
        }
        p_f5_05 = build_v14_world(
            fdir / "f5_05_v14_nomod",
            world_json=make_v14_world_json(world_id="w", title="V14 Omitted Mod"),
            scenes=[make_v9_scene("s1", "Shrine", tokens=[make_v9_token("t1", "V14 Paladin", actor_id="pc_v14", img="worlds/w/pc.png", disposition=1)])],
            actors=[v14_pc],
            assets={"pc.png": png},
        )
        add_case("t2_f5_05", p_f5_05)

        # --- F6 Monster boundaries ---
        p_f6_01 = build_v9_world(
            fdir / "f6_01_dangling",
            world_json=make_v9_world_json(name="w", title="Dangling Tokens"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Broken Tokens",
                    tokens=[
                        make_v9_token("tok_bad", "Mystery Cultist", actor_id="nonexistent_id_123", img="worlds/w/t1.png"),
                        make_v9_token("tok_null", "Stray Imp", actor_id=None, img="worlds/w/t2.png"),
                    ],
                )
            ],
            assets={"t1.png": png, "t2.png": png},
        )
        add_case("t2_f6_01", p_f6_01)

        p_f6_02 = build_v9_world(
            fdir / "f6_02_npc_ac",
            world_json=make_v9_world_json(name="w", title="NPC AC"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Guardhouse",
                    tokens=[
                        make_v9_token("t1", "Knight", actor_id="n1"),
                        make_v9_token("t2", "Wyvern", actor_id="n2"),
                    ],
                )
            ],
            actors=[
                make_v9_actor(
                    "n1",
                    "Knight",
                    actor_type="npc",
                    abilities={"str": 16, "dex": 16, "con": 14, "int": 10, "wis": 11, "cha": 12},
                    ac_flat=None,
                    ac_calc="default",
                    items=[make_armor_item("a1", "Plate", armor_type="heavy", armor_value=18, dex_cap=0, equipped=True)],
                ),
                make_v9_actor("n2", "Wyvern", actor_type="npc", ac_flat=17, ac_calc="natural"),
            ],
        )
        add_case("t2_f6_02", p_f6_02)

        p_f6_03 = build_v9_world(
            fdir / "f6_03_weird_cr",
            world_json=make_v9_world_json(name="w", title="Fractional CR"),
            scenes=[make_v9_scene("s1", "Crypt", tokens=[make_v9_token("t1", "Stirge", actor_id="n1")])],
            actors=[
                make_v9_actor(
                    "n1",
                    "Stirge",
                    actor_type="npc",
                    cr="1/4",
                    hp_value=None,
                    hp_max=12,
                    biography="<p><b>Boss</b> &amp; minion</p>",
                )
            ],
        )
        add_case("t2_f6_03", p_f6_03)

        add_case("t2_f6_04", p_f5_04, {**DEFAULT_OPTIONS, "import_monsters": False, "import_characters": True})

        p_f6_05 = build_v9_world(
            fdir / "f6_05_multi_tok",
            world_json=make_v9_world_json(name="w", title="Kobold Pack"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Tunnel",
                    tokens=[
                        make_v9_token("k_a", "Kobold A", actor_id="k1", x=150, y=150),
                        make_v9_token("k_b", "Kobold B", actor_id="k1", x=300, y=150),
                        make_v9_token("k_c", "Kobold C", actor_id="k1", x=450, y=150),
                    ],
                )
            ],
            actors=[make_v9_actor("k1", "Kobold", actor_type="npc", ac_flat=12, hp_value=5, hp_max=5, cr=0.125)],
        )
        add_case("t2_f6_05", p_f6_05)

        # --- F7 Geometry, Light & Hidden boundaries ---
        p_f7_01 = build_v9_world(
            fdir / "f7_01_2pt",
            world_json=make_v9_world_json(name="w", title="2pt Walls"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Lines",
                    walls=[
                        make_wall("w1", [0, 0, 300, 0]),
                        make_wall("w2", [100, 100, 250, 400]),
                    ],
                )
            ],
        )
        add_case("t2_f7_01", p_f7_01)

        p_f7_02 = build_v9_world(
            fdir / "f7_02_zero_len",
            world_json=make_v9_world_json(name="w", title="Zero Len"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Degenerate",
                    walls=[
                        make_wall("z_wall", [200, 200, 200, 200], door=0),
                        make_wall("z_door", [300, 300, 300, 300], door=1),
                        make_wall("ok_wall", [0, 0, 100, 0], door=0),
                    ],
                )
            ],
        )
        add_case("t2_f7_02", p_f7_02)

        p_f7_03 = build_v9_world(
            fdir / "f7_03_matrix",
            world_json=make_v9_world_json(name="w", title="Wall Matrix"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Matrix",
                    walls=[
                        make_wall("sec", [0, 0, 100, 0], door=2, ds=0),
                        make_wall("eth", [0, 100, 100, 100], door=0, move=0, sight=0, light=0),
                        make_wall("d_closed", [0, 200, 100, 200], door=1, ds=0),
                        make_wall("d_open", [0, 300, 100, 300], door=1, ds=1),
                    ],
                )
            ],
        )
        add_case("t2_f7_03", p_f7_03)

        p_f7_04 = build_v9_world(
            fdir / "f7_04_lights",
            world_json=make_v9_world_json(name="w", title="Extreme Lights"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Clamped Lights",
                    lights=[
                        make_light("l1", 100, 100, bright=0, dim=0, angle=0),
                        make_light("l2", 200, 100, bright=20, dim=30, angle=720),
                        make_light("l3", 300, 100, bright=15, dim=25, angle=-30),
                        make_light("l4", 400, 100, bright=-10, dim=-5, angle=90),
                    ],
                )
            ],
        )
        add_case("t2_f7_04", p_f7_04)

        p_f7_05 = build_v9_world(
            fdir / "f7_05_hidden",
            world_json=make_v9_world_json(name="w", title="Hidden Toggle"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Stealth Room",
                    tokens=[
                        make_v9_token("t_vis", "Visible Orc", actor_id="n1", hidden=False),
                        make_v9_token("t_hid", "Hidden Assassin", actor_id="n2", hidden=True),
                    ],
                    tiles=[
                        make_tile("tl_vis", "worlds/w/a.png", hidden=False),
                        make_tile("tl_hid", "worlds/w/b.png", hidden=True),
                    ],
                    lights=[
                        make_light("l_vis", 150, 150, hidden=False),
                        make_light("l_hid", 300, 150, hidden=True),
                    ],
                    walls=[make_wall("sec_door", [0, 0, 100, 0], door=2, ds=0)],
                )
            ],
            actors=[
                make_v9_actor("n1", "Visible Orc", actor_type="npc"),
                make_v9_actor("n2", "Hidden Assassin", actor_type="npc"),
            ],
            assets={"a.png": png, "b.png": png},
        )
        add_case("t2_f7_05_hide", p_f7_05, {**DEFAULT_OPTIONS, "include_hidden": False})
        add_case("t2_f7_05_show", p_f7_05, {**DEFAULT_OPTIONS, "include_hidden": True})

        p_f7_06 = build_v9_world(
            fdir / "f7_06_hex",
            world_json=make_v9_world_json(name="w", title="Hex Tiny Grid"),
            scenes=[make_v9_scene("s1", "Hex Map", grid_type=2, grid=2)],
        )
        add_case("t2_f7_06", p_f7_06)

        # --- F8 Unsupported, Asset & Resilience boundaries ---
        p_f8_01 = build_v9_world(
            fdir / "f8_01_url_encoded",
            world_json=make_v9_world_json(name="w", title="URL Encoded"),
            scenes=[make_v9_scene("s1", "Encoded Scene", img="worlds/w/scenes/Side%20View%20%281%29.png")],
            assets={"scenes/Side View (1).png": png},
        )
        add_case("t2_f8_01", p_f8_01)

        p_f8_02 = build_v9_world(
            fdir / "f8_02_missing_srd",
            world_json=make_v9_world_json(name="w", title="Missing SRD"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Missing Assets",
                    img="worlds/other/missing.png",
                    tokens=[make_v9_token("t1", "SRD Goblin", actor_id="n1", img="assets/srd5e/tokens/goblin.png")],
                )
            ],
            actors=[make_v9_actor("n1", "SRD Goblin", actor_type="npc", img="assets/srd5e/tokens/goblin.png")],
        )
        add_case("t2_f8_02", p_f8_02, {**DEFAULT_OPTIONS, "skip_missing_assets": True})
        add_case("t2_f8_03", p_f8_02, {**DEFAULT_OPTIONS, "skip_missing_assets": False}, run_inspect=False)

        p_f8_04 = build_v9_world(
            fdir / "f8_04_url_fail",
            world_json=make_v9_world_json(name="w", title="Remote Fail"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Remote Fail Map",
                    img="http://example.com/a.png",
                    tokens=[make_v9_token("t1", "Remote Monster", actor_id="n1", img="https://example.com/b.png")],
                )
            ],
            actors=[make_v9_actor("n1", "Remote Monster", actor_type="npc", img="https://example.com/b.png")],
        )
        add_case("t2_f8_04_skip", p_f8_04, {**DEFAULT_OPTIONS, "skip_missing_assets": True}, archive_policy="fail_all")
        add_case("t2_f8_04_strict", p_f8_04, {**DEFAULT_OPTIONS, "skip_missing_assets": False}, run_inspect=False, archive_policy="fail_all")

        p_f8_05 = build_v9_world(
            fdir / "f8_05_unsafe_refs",
            world_json=make_v9_world_json(name="w", title="Unsafe Refs"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "Unsafe Map",
                    img="user://secret.png",
                    tokens=[
                        make_v9_token("t1", "FileTok", actor_id="n1", img="file:///C:/secret.png"),
                        make_v9_token("t2", "TravTok", actor_id="n1", img="../../outside.png"),
                    ],
                )
            ],
            actors=[make_v9_actor("n1", "Imp", actor_type="npc", img="user://actor_secret.png")],
        )
        add_case("t2_f8_05", p_f8_05, {**DEFAULT_OPTIONS, "skip_missing_assets": True})

        hostile_opts = {
            "import_scenes": "false",
            "import_characters": 0,
            "import_monsters": None,
            "include_hidden": [],
            "skip_missing_assets": {},
            "proxy": 12345,
            "extra_nan": float("nan"),
            "extra_inf": float("inf"),
        }
        add_case("t2_f8_06", p_f5_04, hostile_opts)

        add_case("t2_f8_07_inspect", p_f5_04, DEFAULT_OPTIONS, run_prepare=False, cancel_policy="immediate")
        add_case("t2_f8_07_prepare_start", p_f5_04, DEFAULT_OPTIONS, cancel_policy="on_prepare_start")
        add_case("t2_f8_07_prepare_mid", p_f5_04, DEFAULT_OPTIONS, cancel_policy="on_prepare_report")

        cls.batch = cls.session.run_batch(cases, timeout_seconds=120)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.session.cleanup()

    # -----------------------------------------------------------------------
    # F1 Boundaries (5)
    # -----------------------------------------------------------------------

    def test_t2_f1_01_utf8_bom_rejected(self) -> None:
        assert self.session.run_dir is not None
        real_mod = self.session.cfg.mods_dir / MOD_NAME
        for f in real_mod.rglob("*"):
            if f.is_file() and f.suffix.lower() in (".json", ".gd", ".md"):
                self.assertFalse(f.read_bytes().startswith(UTF8_BOM), f"Real file has BOM: {f}")

        # BOM in plugin.json
        bad_mod = self.session.run_dir / "tmp_mods" / "bom-json"
        _copy_mod_to(real_mod, bad_mod)
        pj = bad_mod / "plugin.json"
        pj.write_bytes(UTF8_BOM + pj.read_bytes())
        rep1 = validate_mod_dir(bad_mod, mod_name=MOD_NAME, sdk_dir=self.session.cfg.sdk_dir)
        self.assertFalse(rep1.ok)
        self.assertTrue(any("BOM" in e for e in rep1.errors))

        # BOM in entry.gd
        bad_mod2 = self.session.run_dir / "tmp_mods" / "bom-gd"
        _copy_mod_to(real_mod, bad_mod2)
        eg = bad_mod2 / "entry.gd"
        eg.write_bytes(UTF8_BOM + eg.read_bytes())
        rep2 = validate_mod_dir(bad_mod2, mod_name=MOD_NAME, sdk_dir=self.session.cfg.sdk_dir)
        self.assertFalse(rep2.ok)
        self.assertTrue(any("BOM" in e for e in rep2.errors))

    def test_t2_f1_02_invalid_setting_types_rejected(self) -> None:
        assert self.session.run_dir is not None
        real_mod = self.session.cfg.mods_dir / MOD_NAME
        for bad_type, bad_default in (("int", 10), ("enum", "a")):
            bad_mod = self.session.run_dir / "tmp_mods" / f"bad_setting_{bad_type}"
            _copy_mod_to(real_mod, bad_mod)
            pj = bad_mod / "plugin.json"
            data = json.loads(pj.read_text(encoding="utf-8"))
            data["settings"][0]["type"] = bad_type
            data["settings"][0]["default"] = bad_default
            pj.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
            rep = validate_mod_dir(bad_mod, mod_name=MOD_NAME, sdk_dir=self.session.cfg.sdk_dir)
            self.assertFalse(rep.ok)
            self.assertTrue(any("invalid_plugin_settings" in e for e in rep.errors))

    def test_t2_f1_03_invalid_import_extensions_rejected(self) -> None:
        assert self.session.run_dir is not None
        real_mod = self.session.cfg.mods_dir / MOD_NAME
        bad_lists = [[], [".zip"], ["ZIP"], [f"ext{i}" for i in range(9)]]
        for idx, exts in enumerate(bad_lists):
            bad_mod = self.session.run_dir / "tmp_mods" / f"bad_ext_{idx}"
            _copy_mod_to(real_mod, bad_mod)
            pj = bad_mod / "plugin.json"
            data = json.loads(pj.read_text(encoding="utf-8"))
            data["import_extensions"] = exts
            pj.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
            rep = validate_mod_dir(bad_mod, mod_name=MOD_NAME, sdk_dir=self.session.cfg.sdk_dir)
            self.assertFalse(rep.ok, f"Expected failure for import_extensions={exts!r}")

    def test_t2_f1_04_missing_hook_file_limit_and_zip_traversal_rejected(self) -> None:
        assert self.session.run_dir is not None
        real_mod = self.session.cfg.mods_dir / MOD_NAME

        # (a) Missing inspect_import
        m_a = self.session.run_dir / "tmp_mods" / "no_hook"
        _copy_mod_to(real_mod, m_a)
        (m_a / "entry.gd").write_bytes(b"extends RefCounted\nfunc prepare_import(p,o,h):\n\treturn {}\n")
        self.assertFalse(validate_mod_dir(m_a, mod_name=MOD_NAME, sdk_dir=self.session.cfg.sdk_dir).ok)

        # (b) > 1000 files
        m_b = self.session.run_dir / "tmp_mods" / "too_many_files"
        _copy_mod_to(real_mod, m_b)
        extra_dir = m_b / "assets" / "spam"
        extra_dir.mkdir(parents=True, exist_ok=True)
        for i in range(1002):
            (extra_dir / f"f{i:04d}.txt").write_bytes(b"x")
        self.assertFalse(validate_mod_dir(m_b, mod_name=MOD_NAME, sdk_dir=self.session.cfg.sdk_dir).ok)

        # (c) Case collision + (d) ../ traversal inside ZIP
        bad_zip = self.session.run_dir / "bad_case_trav.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("plugin.json", "{}")
            zf.writestr("Src/a.gd", "extends RefCounted\n")
            zf.writestr("src/a.gd", "extends RefCounted\n")
            zf.writestr("../evil.gd", "extends RefCounted\n")
        errs = validate_zip_archive(bad_zip)
        self.assertTrue(len(errs) >= 2, f"Expected collision + traversal errors, got {errs}")

    def test_t2_f1_05_package_quotas_and_zero_preload(self) -> None:
        artifact = build_mod(MOD_NAME, config=self.session.cfg, bump_dev=False)
        pjson_bytes = (self.session.cfg.mods_dir / MOD_NAME / "plugin.json").stat().st_size
        self.assertLessEqual(pjson_bytes, 128 * 1024)
        self.assertLessEqual(artifact.zip_size_bytes, 64 * 1024 * 1024)
        with zipfile.ZipFile(artifact.zip_path, "r") as zf:
            infos = zf.infolist()
            self.assertTrue(2 <= len(infos) <= 1000)
            self.assertLessEqual(sum(m.file_size for m in infos), 256 * 1024 * 1024)
            for m in infos:
                if m.filename.endswith(".gd"):
                    stripped = strip_gdscript_comments(zf.read(m).decode("utf-8"))
                    self.assertNotIn("preload(", stripped, f"Forbidden preload() in {m.filename}")

    # -----------------------------------------------------------------------
    # F2 .zip Boundaries (6)
    # -----------------------------------------------------------------------

    def test_t2_f2_01_corrupt_truncated_and_crc_zip(self) -> None:
        for cid in ("t2_f2_01_trunc", "t2_f2_01_crc"):
            res = self.batch.results[cid]
            assert_valid_inspect_fail(self, res)
            assert_valid_prepare_fail(self, res)

    def test_t2_f2_02_non_zip_disguised_as_zip(self) -> None:
        for cid in ("t2_f2_02_txt", "t2_f2_02_png"):
            res = self.batch.results[cid]
            assert_valid_inspect_fail(self, res)
            assert_valid_prepare_fail(self, res)

    def test_t2_f2_03_zip_depth_0_1_pass_depth_2_fail(self) -> None:
        for cid in ("t2_f2_03_d0", "t2_f2_03_d1"):
            res = self.batch.results[cid]
            assert_valid_inspect_ok(self, res, self.sample_paths[cid])
            world = assert_valid_practice_world_v3(self, res)
            self.assertGreaterEqual(len(get_floors(world)), 1)
        res_d2 = self.batch.results["t2_f2_03_d2"]
        assert_valid_inspect_fail(self, res_d2)
        assert_valid_prepare_fail(self, res_d2)

    def test_t2_f2_04_zip_missing_world_json(self) -> None:
        res = self.batch.results["t2_f2_04"]
        assert_valid_inspect_fail(self, res)
        assert_valid_prepare_fail(self, res)

    def test_t2_f2_05_zip_filters_macosx_and_ds_store(self) -> None:
        res = self.batch.results["t2_f2_05"]
        assert_valid_inspect_ok(self, res, self.sample_paths["t2_f2_05"])
        world = assert_valid_practice_world_v3(self, res)
        self.assertTrue(any(f["name"] == "Base Scene" for f in get_floors(world)))

    def test_t2_f2_06_ambiguous_root_and_path_traversal_ref(self) -> None:
        res_ambig = self.batch.results["t2_f2_06_ambig"]
        assert_case_clean(self, res_ambig)
        # Either fails cleanly with reason, or warns & picks deterministically
        if res_ambig.prepare_result and res_ambig.prepare_result.get("ok"):
            assert_valid_practice_world_v3(self, res_ambig)
        else:
            assert_valid_prepare_fail(self, res_ambig)

        res_trav = self.batch.results["t2_f2_06_trav"]
        world_trav = assert_valid_practice_world_v3(self, res_trav)
        self.assertTrue(any(f["name"] == "Traversal Scene" for f in get_floors(world_trav)))

    # -----------------------------------------------------------------------
    # F3 Unpacked Dir Boundaries (6)
    # -----------------------------------------------------------------------

    def test_t2_f3_01_missing_world_json_and_empty_dir(self) -> None:
        for cid in ("t2_f3_01_missing", "t2_f3_01_dir"):
            res = self.batch.results[cid]
            assert_valid_inspect_fail(self, res)
            assert_valid_prepare_fail(self, res)

    def test_t2_f3_02_invalid_world_json_variants(self) -> None:
        for cid in ("t2_f3_02_trunc", "t2_f3_02_arr", "t2_f3_02_empty"):
            res = self.batch.results[cid]
            assert_valid_inspect_fail(self, res)
            assert_valid_prepare_fail(self, res)

    def test_t2_f3_03_truncated_and_garbage_db_lines(self) -> None:
        res_p = self.batch.results["t2_f3_03_partial"]
        assert_case_clean(self, res_p)
        if res_p.prepare_result and res_p.prepare_result.get("ok"):
            world = assert_valid_practice_world_v3(self, res_p)
            self.assertGreaterEqual(len(res_p.host_trace.get("warnings", [])), 1)
            self.assertTrue(any(f["name"] == "Good Scene" for f in get_floors(world)))
        else:
            assert_valid_prepare_fail(self, res_p)

        res_g = self.batch.results["t2_f3_03_garbage"]
        assert_case_clean(self, res_g)
        if res_g.prepare_result and res_g.prepare_result.get("ok"):
            assert_valid_practice_world_v3(self, res_g)
            self.assertGreaterEqual(len(res_g.host_trace.get("warnings", [])), 1)
        else:
            assert_valid_prepare_fail(self, res_g)

    def test_t2_f3_04_empty_world_zero_scenes_zero_actors(self) -> None:
        res_empty = self.batch.results["t2_f3_04_empty_dbs"]
        ins = assert_valid_inspect_ok(self, res_empty, self.sample_paths["t2_f3_04_empty_dbs"])
        self.assertEqual(ins["counts"]["maps"], 0)
        self.assertEqual(ins["counts"]["characters"], 0)
        self.assertEqual(ins["counts"]["walls"], 0)
        self.assertEqual(ins["counts"]["doors"], 0)
        world = assert_valid_practice_world_v3(self, res_empty)
        self.assertEqual(len(get_entities(world)), 0)

        res_nodata = self.batch.results["t2_f3_04_nodata"]
        assert_case_clean(self, res_nodata)
        if res_nodata.inspect_result and res_nodata.inspect_result.get("ok"):
            ins_nd = assert_valid_inspect_ok(self, res_nodata, self.sample_paths["t2_f3_04_nodata"])
            self.assertEqual(ins_nd["counts"]["maps"], 0)
            self.assertEqual(ins_nd["counts"]["characters"], 0)
            if res_nodata.prepare_result and res_nodata.prepare_result.get("ok"):
                w_nd = assert_valid_practice_world_v3(self, res_nodata)
                self.assertEqual(len(get_entities(w_nd)), 0)
            else:
                assert_valid_prepare_fail(self, res_nodata)
        else:
            assert_valid_inspect_fail(self, res_nodata)
            assert_valid_prepare_fail(self, res_nodata)

    def test_t2_f3_05_nedb_deleted_tombstones_and_duplicate_id_last_wins(self) -> None:
        res = self.batch.results["t2_f3_05"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t2_f3_05"])
        self.assertEqual(ins["counts"]["maps"], 1)
        self.assertEqual(ins["counts"]["characters"], 1)
        world = assert_valid_practice_world_v3(self, res)
        floor_names = [f["name"] for f in get_floors(world)]
        self.assertIn("Updated Name", floor_names)
        self.assertNotIn("Old Name", floor_names)
        self.assertNotIn("Deleted Scene", floor_names)
        assert_actor_preserved(self, world, "Updated Hero", expected_level=7)

    def test_t2_f3_06_leveldb_wal_overwrite_and_tombstone_delete(self) -> None:
        res = self.batch.results["t2_f3_06"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t2_f3_06"])
        self.assertEqual(ins["counts"]["maps"], 1)
        world = assert_valid_practice_world_v3(self, res)
        floor_names = [f["name"] for f in get_floors(world)]
        self.assertIn("WAL Updated", floor_names)
        self.assertNotIn("Base", floor_names)
        self.assertNotIn("ToBeDeleted", floor_names)

    # -----------------------------------------------------------------------
    # F4 Scene Boundaries (5)
    # -----------------------------------------------------------------------

    def test_t2_f4_01_gridless_zero_grid_no_div_by_zero(self) -> None:
        res = self.batch.results["t2_f4_01"]
        world = assert_valid_practice_world_v3(self, res)
        self.assertGreaterEqual(len(get_entities(world)), 1)

    def test_t2_f4_02_zero_negative_dims_and_zero_scale(self) -> None:
        res = self.batch.results["t2_f4_02"]
        world = assert_valid_practice_world_v3(self, res)
        self.assertGreaterEqual(len(get_entities(world)), 1)

    def test_t2_f4_03_long_and_control_char_scene_name_clamped(self) -> None:
        res = self.batch.results["t2_f4_03"]
        world = assert_valid_practice_world_v3(self, res)
        floors = get_floors(world)
        self.assertTrue(any(f["name"].startswith("AAAA") and len(f["name"]) == 96 for f in floors))

    def test_t2_f4_04_null_img_and_overlapping_tiles_canonical_z(self) -> None:
        res = self.batch.results["t2_f4_04"]
        world = assert_valid_practice_world_v3(self, res)
        self.assertGreaterEqual(len(get_entities(world)), 3)

    def test_t2_f4_05_all_inactive_scenes_fallback_active_floor(self) -> None:
        res = self.batch.results["t2_f4_05"]
        world = assert_valid_practice_world_v3(self, res)
        floors = get_floors(world)
        self.assertEqual(len(floors), 2)
        self.assertEqual({f["name"] for f in floors}, {"First Inactive", "Second Inactive"})

    # -----------------------------------------------------------------------
    # F5 Character Boundaries (5)
    # -----------------------------------------------------------------------

    def test_t2_f5_01_equipped_half_plate_plus_shield_ac_19(self) -> None:
        res = self.batch.results["t2_f5_01"]
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(self, world, "Fighter", expected_ac=19, require_unit_entity=True)

    def test_t2_f5_02_unarmored_default_ac_13(self) -> None:
        res = self.batch.results["t2_f5_02"]
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(self, world, "Rogue", expected_ac=13, require_unit_entity=True)

    def test_t2_f5_03_minimal_skeleton_character(self) -> None:
        res = self.batch.results["t2_f5_03"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t2_f5_03"])
        self.assertGreaterEqual(ins["counts"]["characters"], 1)
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(self, world, "Blank PC", require_unit_entity=True)

    def test_t2_f5_04_import_characters_false_isolation(self) -> None:
        res = self.batch.results["t2_f5_04"]
        world = assert_valid_practice_world_v3(self, res)
        unit_names = {u["display_name"] for u in get_unit_entities(world)}
        self.assertIn("TrollNPC", unit_names)
        self.assertNotIn("HeroPC", unit_names)

    def test_t2_f5_05_v14_omitted_mod_and_prototype_token_src(self) -> None:
        res = self.batch.results["t2_f5_05"]
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(self, world, "V14 Paladin", expected_ac=18, expected_hp=22, expected_level=3, require_unit_entity=True)

    # -----------------------------------------------------------------------
    # F6 Monster Boundaries (5)
    # -----------------------------------------------------------------------

    def test_t2_f6_01_dangling_and_null_actor_id_tokens(self) -> None:
        res = self.batch.results["t2_f6_01"]
        world = assert_valid_practice_world_v3(self, res)
        unit_names = {u["display_name"] for u in get_unit_entities(world)}
        self.assertIn("Mystery Cultist", unit_names)
        self.assertIn("Stray Imp", unit_names)

    def test_t2_f6_02_npc_heavy_armor_default_vs_natural_ac(self) -> None:
        res = self.batch.results["t2_f6_02"]
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(self, world, "Knight", expected_ac=18, require_unit_entity=True)
        assert_actor_preserved(self, world, "Wyvern", expected_ac=17, require_unit_entity=True)

    def test_t2_f6_03_fractional_cr_string_and_null_hp(self) -> None:
        res = self.batch.results["t2_f6_03"]
        world = assert_valid_practice_world_v3(self, res)
        assert_actor_preserved(self, world, "Stirge", expected_cr=0.25, require_unit_entity=True)

    def test_t2_f6_04_import_monsters_false_isolation(self) -> None:
        res = self.batch.results["t2_f6_04"]
        world = assert_valid_practice_world_v3(self, res)
        unit_names = {u["display_name"] for u in get_unit_entities(world)}
        self.assertIn("HeroPC", unit_names)
        self.assertNotIn("TrollNPC", unit_names)

    def test_t2_f6_05_multiple_tokens_linked_to_same_npc(self) -> None:
        res = self.batch.results["t2_f6_05"]
        world = assert_valid_practice_world_v3(self, res)
        units = get_unit_entities(world)
        self.assertEqual(len(units), 3)
        positions = {(round(u["xform"]["pos"].x, 2), round(u["xform"]["pos"].y, 2)) for u in units}
        self.assertEqual(len(positions), 3)

    # -----------------------------------------------------------------------
    # F7 Walls, Doors, Lights & Visibility Boundaries (6)
    # -----------------------------------------------------------------------

    def test_t2_f7_01_2pt_walls_extruded_to_min_3_vertices(self) -> None:
        res = self.batch.results["t2_f7_01"]
        world = assert_valid_practice_world_v3(self, res)
        walls = get_obstacle_entities(world, kind="wall")
        self.assertGreaterEqual(len(walls), 1)

    def test_t2_f7_02_zero_length_wall_and_door_safety(self) -> None:
        res = self.batch.results["t2_f7_02"]
        world = assert_valid_practice_world_v3(self, res)
        self.assertGreaterEqual(len(get_obstacle_entities(world, kind="wall")), 1)

    def test_t2_f7_03_wall_flag_matrix(self) -> None:
        res = self.batch.results["t2_f7_03"]
        world = assert_valid_practice_world_v3(self, res)
        doors = get_obstacle_entities(world, kind="door")
        self.assertGreaterEqual(len(doors), 2)
        open_flags = {bool(d["components"][0]["state"]["vector_drawing"]["source"].get("open")) for d in doors}
        self.assertEqual(open_flags, {False, True})
        # Secret door (door=2) maps to kind="door" (not "wall"), and ethereal line (move=0,sight=0,light=0) must not create a blocking wall
        self.assertGreaterEqual(len(doors), 3)
        walls = get_obstacle_entities(world, kind="wall")
        self.assertEqual(len(walls), 0)

    def test_t2_f7_04_extreme_light_angles_and_negative_radius(self) -> None:
        res = self.batch.results["t2_f7_04"]
        world = assert_valid_practice_world_v3(self, res)
        lights = [
            get_component(e, "comp_simple_light.gd")
            for e in get_entities(world)
            if get_component(e, "comp_simple_light.gd") is not None
        ]
        self.assertGreaterEqual(len(lights), 1)

    def test_t2_f7_05_include_hidden_toggle(self) -> None:
        r_hide = self.batch.results["t2_f7_05_hide"]
        ins = assert_valid_inspect_ok(self, r_hide, self.sample_paths["t2_f7_05_hide"])
        self.assertGreaterEqual(ins["counts"]["hidden"], 3)
        w_hide = assert_valid_practice_world_v3(self, r_hide)

        r_show = self.batch.results["t2_f7_05_show"]
        w_show = assert_valid_practice_world_v3(self, r_show)

        self.assertNotIn("Hidden Assassin", {u["display_name"] for u in get_unit_entities(w_hide)})
        show_units = {u["display_name"]: u for u in get_unit_entities(w_show)}
        self.assertIn("Hidden Assassin", show_units)
        self.assertTrue(show_units["Hidden Assassin"].get("flags", {}).get("entity_hidden"))
        self.assertGreater(len(get_entities(w_show)), len(get_entities(w_hide)))

    def test_t2_f7_06_hex_and_tiny_grid_clamping(self) -> None:
        res = self.batch.results["t2_f7_06"]
        world = assert_valid_practice_world_v3(self, res)
        floors = get_floors(world)
        self.assertTrue(any(f["name"] == "Hex Map" for f in floors))
        ga = world.get("modules", {}).get("entries", {}).get("grid_alignment")
        if ga is not None:
            st = ga["state"]
            self.assertTrue(8.0 <= float(st["cell_size"]) <= 4096.0)
            self.assertTrue(0.5 <= float(st["line_width"]) <= 4.0)
            self.assertTrue(0.0 <= float(st["snap_strength"]) <= 1.0)

    # -----------------------------------------------------------------------
    # F8 Asset, Options & Cancel Boundaries (7)
    # -----------------------------------------------------------------------

    def test_t2_f8_01_url_encoded_asset_paths(self) -> None:
        res = self.batch.results["t2_f8_01"]
        ins = assert_valid_inspect_ok(self, res, self.sample_paths["t2_f8_01"])
        self.assertGreaterEqual(ins["counts"]["images"], 1)
        assert_valid_practice_world_v3(self, res)
        self.assertFalse(any("Side View (1).png" in w or "Side%20View" in w for w in res.host_trace.get("warnings", [])))

    def test_t2_f8_02_missing_srd_assets_with_skip_true(self) -> None:
        res = self.batch.results["t2_f8_02"]
        assert_valid_inspect_ok(self, res, self.sample_paths["t2_f8_02"])
        world = assert_valid_practice_world_v3(self, res)
        self.assertGreaterEqual(len(res.host_trace.get("warnings", [])), 1)
        self.assertGreaterEqual(len(get_unit_entities(world)), 1)

    def test_t2_f8_03_missing_srd_assets_with_skip_false_aborts(self) -> None:
        res = self.batch.results["t2_f8_03"]
        assert_valid_prepare_fail(self, res)

    def test_t2_f8_04_remote_archive_image_failure_modes(self) -> None:
        r_skip = self.batch.results["t2_f8_04_skip"]
        ins = assert_valid_inspect_ok(self, r_skip, self.sample_paths["t2_f8_04_skip"])
        self.assertIn("http://example.com/a.png", ins["assets"])
        self.assertIn("https://example.com/b.png", ins["assets"])
        world = assert_valid_practice_world_v3(self, r_skip)
        self.assertGreaterEqual(len(r_skip.host_trace.get("warnings", [])), 1)
        map_ents = get_entities_by_layer_kind(world, "map")
        self.assertGreaterEqual(len(map_ents), 1)
        self.assertEqual(map_ents[0]["components"][0]["state"].get("sprite_path", ""), "")

        r_strict = self.batch.results["t2_f8_04_strict"]
        assert_valid_prepare_fail(self, r_strict)

    def test_t2_f8_05_unsafe_user_file_traversal_refs_sanitized(self) -> None:
        res = self.batch.results["t2_f8_05"]
        world = assert_valid_practice_world_v3(self, res)
        self.assertGreaterEqual(len(get_unit_entities(world)), 1)

    def test_t2_f8_06_hostile_options_coercion(self) -> None:
        res = self.batch.results["t2_f8_06"]
        assert_valid_inspect_ok(self, res, self.sample_paths["t2_f8_06"])
        world = assert_valid_practice_world_v3(self, res)
        # import_scenes="false" -> 0 map entities; import_characters=0 -> HeroPC excluded; import_monsters=None -> True (TrollNPC kept)
        self.assertEqual(len(get_entities_by_layer_kind(world, "map")), 0)
        unit_names = {u["display_name"] for u in get_unit_entities(world)}
        self.assertNotIn("HeroPC", unit_names)
        self.assertEqual(find_actor_records(world, "HeroPC"), [])
        assert_actor_preserved(self, world, "TrollNPC", require_unit_entity=False)

    def test_t2_f8_07_host_cancelled_in_inspect_and_prepare(self) -> None:
        r_ins = self.batch.results["t2_f8_07_inspect"]
        assert_case_clean(self, r_ins)
        self.assertEqual(r_ins.inspect_result, {"ok": False, "reason": "cancelled"})

        for cid in ("t2_f8_07_prepare_start", "t2_f8_07_prepare_mid"):
            r_prep = self.batch.results[cid]
            assert_case_clean(self, r_prep)
            self.assertEqual(r_prep.prepare_result, {"ok": False, "reason": "cancelled"})
