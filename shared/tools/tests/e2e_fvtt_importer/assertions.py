"""Opaque-box Fu VTT Practice v3 invariant checkers and query helpers."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
import re
from typing import Any
import unittest

from .harness import GdPackedVector2ArraySummary, GdVector2, ProbeCaseResult


_UID_RE = re.compile(r"^[0-9a-f]{32}$")
_MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
_ALLOWED_LAYER_KINDS = frozenset({"map", "entity", "obstacle", "area"})
_ALLOWED_ACCESS = frozenset({"all", "host", "players"})
_OBSTACLE_KINDS = frozenset({"wall", "air", "door", "window", "glass"})
_ALLOWED_ASSET_EXTS = frozenset({"png", "jpg", "jpeg", "webp", "bmp"})
_ALLOWED_RES_EXTS = frozenset({"png", "jpg", "jpeg", "webp", "bmp", "svg"})
_INSPECT_COUNT_KEYS = (
    "records",
    "images",
    "selected_images",
    "maps",
    "characters",
    "objects",
    "text",
    "drawings",
    "walls",
    "doors",
    "hidden",
    "unsupported",
)


def _has_control_chars(s: str) -> bool:
    return any((ord(ch) < 32) or (127 <= ord(ch) <= 159) for ch in s)


def _is_finite_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _vec2_xy(v: Any) -> tuple[float, float] | None:
    if isinstance(v, GdVector2):
        return (v.x, v.y)
    if isinstance(v, (tuple, list)) and len(v) == 2:
        return (float(v[0]), float(v[1]))
    if isinstance(v, dict) and "x" in v and "y" in v:
        return (float(v["x"]), float(v["y"]))
    return None


def assert_case_clean(tc: unittest.TestCase, result: ProbeCaseResult) -> None:
    """Assert the case completed in Godot with zero log errors and zero GDScript invariant failures."""
    tc.assertTrue(
        result.completed,
        f"[{result.case_id}] Probe did not complete (timed_out={result.timed_out}, exit_code={result.exit_code}, logs={result.log_errors})",
    )
    tc.assertEqual(
        result.log_errors,
        [],
        f"[{result.case_id}] Godot log/stderr errors detected: {result.log_errors}",
    )
    tc.assertEqual(
        result.gd_check_failures,
        [],
        f"[{result.case_id}] GDScript Practice invariant failures: {result.gd_check_failures}",
    )


def assert_valid_inspect_ok(
    tc: unittest.TestCase,
    result: ProbeCaseResult,
    source_path: Path | str,
) -> dict[str, Any]:
    """Verify ImportConfirmation contract on a successful `inspect_import()` call."""
    tc.assertTrue(result.completed, f"[{result.case_id}] did not complete")
    tc.assertEqual(result.log_errors, [], f"[{result.case_id}] log errors: {result.log_errors}")
    res = result.inspect_result
    tc.assertIsInstance(res, dict, f"[{result.case_id}] inspect_result must be dict")
    assert isinstance(res, dict)
    tc.assertIs(res.get("ok"), True, f"[{result.case_id}] inspect_import failed: {res}")

    name = res.get("name")
    tc.assertIsInstance(name, str)
    tc.assertTrue(bool(str(name).strip()), f"[{result.case_id}] inspect_import.name is empty")

    src = Path(source_path)
    expected_sha = hashlib.sha256(src.read_bytes()).hexdigest()
    sha = res.get("sha256")
    tc.assertEqual(sha, expected_sha, f"[{result.case_id}] sha256 mismatch")

    src_bytes = res.get("source_bytes")
    tc.assertIsInstance(src_bytes, int)
    tc.assertEqual(src_bytes, src.stat().st_size, f"[{result.case_id}] source_bytes mismatch")

    dec_bytes = res.get("decoded_bytes")
    tc.assertIsInstance(dec_bytes, int)
    tc.assertGreaterEqual(dec_bytes, 0)

    uniq_imgs = res.get("unique_images")
    tc.assertIsInstance(uniq_imgs, int)
    tc.assertGreaterEqual(uniq_imgs, 0)

    counts = res.get("counts")
    tc.assertIsInstance(counts, dict)
    assert isinstance(counts, dict)
    for k in _INSPECT_COUNT_KEYS:
        tc.assertIn(k, counts, f"[{result.case_id}] inspect_import.counts missing key {k!r}")
        v = counts[k]
        tc.assertTrue(isinstance(v, int) and not isinstance(v, bool) and v >= 0, f"counts[{k}] invalid: {v!r}")

    tc.assertIsInstance(res.get("assets"), dict)
    return res


def assert_valid_inspect_fail(tc: unittest.TestCase, result: ProbeCaseResult) -> dict[str, Any]:
    """Verify clean failure return on `inspect_import()` with zero Godot runtime errors."""
    tc.assertTrue(result.completed, f"[{result.case_id}] crashed/timed out instead of returning ok=false")
    tc.assertEqual(result.log_errors, [], f"[{result.case_id}] Godot log errors: {result.log_errors}")
    res = result.inspect_result
    tc.assertIsInstance(res, dict)
    assert isinstance(res, dict)
    tc.assertIs(res.get("ok"), False, f"[{result.case_id}] expected ok=False, got {res}")
    reason = res.get("reason")
    tc.assertIsInstance(reason, str)
    tc.assertTrue(bool(str(reason).strip()), f"[{result.case_id}] failure reason must be non-empty")
    return res


def assert_valid_prepare_fail(tc: unittest.TestCase, result: ProbeCaseResult) -> dict[str, Any]:
    """Verify clean failure return on `prepare_import()` with zero Godot runtime errors."""
    tc.assertTrue(result.completed, f"[{result.case_id}] crashed/timed out instead of returning ok=false")
    tc.assertEqual(result.log_errors, [], f"[{result.case_id}] Godot log errors: {result.log_errors}")
    res = result.prepare_result
    tc.assertIsInstance(res, dict)
    assert isinstance(res, dict)
    tc.assertIs(res.get("ok"), False, f"[{result.case_id}] expected prepare ok=False, got {res}")
    reason = res.get("reason")
    tc.assertIsInstance(reason, str)
    tc.assertTrue(bool(str(reason).strip()), f"[{result.case_id}] prepare failure reason must be non-empty")
    return res


def assert_valid_sprite_path(tc: unittest.TestCase, sp: Any, ctx: str = "") -> None:
    tc.assertIsInstance(sp, str, f"{ctx} sprite_path must be str")
    assert isinstance(sp, str)
    if sp == "":
        return
    tc.assertFalse(sp.startswith("user://"), f"{ctx} forbidden user:// sprite_path: {sp}")
    tc.assertFalse(sp.startswith("file://"), f"{ctx} forbidden file:// sprite_path: {sp}")
    if sp.startswith("asset://"):
        body = sp[len("asset://") :]
        tc.assertFalse(".." in body or "/" in body or "\\" in body, f"{ctx} invalid asset:// path: {sp}")
        ext = body.rsplit(".", 1)[-1].lower() if "." in body else ""
        tc.assertIn(ext, _ALLOWED_ASSET_EXTS, f"{ctx} disallowed asset:// ext: {sp}")
    elif sp.startswith("res://"):
        tc.assertNotIn("..", sp)
        ext = sp.rsplit(".", 1)[-1].lower() if "." in sp else ""
        tc.assertIn(ext, _ALLOWED_RES_EXTS, f"{ctx} disallowed res:// ext: {sp}")
    else:
        tc.fail(f"{ctx} unarchived/unsafe sprite_path: {sp!r}")


def assert_valid_practice_world_v3(
    tc: unittest.TestCase,
    result: ProbeCaseResult,
    *,
    max_entities: int = 10000,
) -> dict[str, Any]:
    """Verify `prepare_import()` succeeded and satisfies all `fus.practice.world` v3 invariants."""
    assert_case_clean(tc, result)
    res = result.prepare_result
    tc.assertIsInstance(res, dict, f"[{result.case_id}] prepare_result must be dict")
    assert isinstance(res, dict)
    tc.assertIs(res.get("ok"), True, f"[{result.case_id}] prepare_import failed: {res}")

    counts = res.get("counts")
    tc.assertIsInstance(counts, dict)
    assert isinstance(counts, dict)
    for k in ("entities", "assets", "source_records", "merged_walls"):
        tc.assertIn(k, counts, f"[{result.case_id}] prepare_import.counts missing {k!r}")
        v = counts[k]
        tc.assertTrue(isinstance(v, int) and not isinstance(v, bool) and v >= 0)

    world = res.get("world")
    tc.assertIsInstance(world, dict)
    assert isinstance(world, dict)
    tc.assertEqual(world.get("format"), "fus.practice.world")
    tc.assertEqual(world.get("version"), 3)

    catalog = world.get("catalog")
    tc.assertIsInstance(catalog, dict)
    assert isinstance(catalog, dict)
    floors = catalog.get("floors")
    tc.assertIsInstance(floors, list)
    assert isinstance(floors, list)
    tc.assertTrue(1 <= len(floors) <= 512, f"floor count out of 1..512: {len(floors)}")

    floor_uids: set[str] = set()
    for f in floors:
        tc.assertIsInstance(f, dict)
        fuid = f.get("floor_uid", "")
        tc.assertRegex(fuid, _UID_RE, f"invalid floor_uid: {fuid!r}")
        tc.assertNotIn(fuid, floor_uids, f"duplicate floor_uid: {fuid!r}")
        floor_uids.add(fuid)
        fname = f.get("name", "")
        tc.assertIsInstance(fname, str)
        tc.assertTrue(1 <= len(fname) <= 96, f"floor name len out of 1..96: {fname!r}")
        tc.assertEqual(fname, fname.strip(), f"floor name untrimmed: {fname!r}")
        tc.assertFalse(_has_control_chars(fname), f"floor name has control chars: {fname!r}")

    tc.assertIn(catalog.get("active_floor_uid"), floor_uids)

    layers_root = catalog.get("layers")
    tc.assertIsInstance(layers_root, dict)
    assert isinstance(layers_root, dict)
    tc.assertEqual(layers_root.get("schema"), "fus.floor_layers.v2")
    layer_floors = layers_root.get("floors")
    tc.assertIsInstance(layer_floors, list)
    assert isinstance(layer_floors, list)

    layer_owner: dict[str, str] = {}
    total_layers = 0
    for lf in layer_floors:
        tc.assertIsInstance(lf, dict)
        lfuid = lf.get("floor_uid")
        tc.assertIn(lfuid, floor_uids)
        flayers = lf.get("layers")
        tc.assertIsInstance(flayers, list)
        tc.assertTrue(1 <= len(flayers) <= 256)
        for layer in flayers:
            total_layers += 1
            luid = layer.get("layer_uid", "")
            tc.assertRegex(luid, _UID_RE)
            tc.assertNotIn(luid, layer_owner)
            tc.assertIn(layer.get("kind"), _ALLOWED_LAYER_KINDS)
            tc.assertIsInstance(layer.get("locked"), bool)
            access = layer.get("access")
            tc.assertIn(access, _ALLOWED_ACCESS)
            viewers = layer.get("viewers", [])
            tc.assertIsInstance(viewers, list)
            tc.assertEqual(access == "players", len(viewers) > 0)
            layer_owner[luid] = lfuid
    tc.assertTrue(1 <= total_layers <= 4096)

    es = world.get("entity_state")
    tc.assertIsInstance(es, dict)
    assert isinstance(es, dict)
    tc.assertEqual(es.get("version"), 3)
    entities = es.get("entities")
    tc.assertIsInstance(entities, list)
    assert isinstance(entities, list)
    tc.assertLessEqual(len(entities), max_entities)

    entity_ids: set[str] = set()
    for idx, ent in enumerate(entities):
        tc.assertIsInstance(ent, dict)
        eid = ent.get("id", "")
        tc.assertTrue(isinstance(eid, str) and eid != "", f"entity[{idx}] invalid id")
        tc.assertNotIn(eid, entity_ids, f"duplicate entity id: {eid!r}")
        entity_ids.add(eid)

        xf = ent.get("xform")
        tc.assertIsInstance(xf, dict)
        pos = _vec2_xy(xf.get("pos"))
        tc.assertIsNotNone(pos, f"entity[{idx}].xform.pos invalid")
        assert pos is not None
        tc.assertTrue(_is_finite_num(pos[0]) and _is_finite_num(pos[1]))
        tc.assertTrue(_is_finite_num(xf.get("rot")))
        scale = _vec2_xy(xf.get("scale"))
        tc.assertIsNotNone(scale, f"entity[{idx}].xform.scale invalid")
        assert scale is not None
        tc.assertTrue(_is_finite_num(scale[0]) and _is_finite_num(scale[1]))
        tc.assertGreater(abs(scale[0]), 1e-6)
        tc.assertGreater(abs(scale[1]), 1e-6)

        esize = _vec2_xy(ent.get("entity_size"))
        tc.assertIsNotNone(esize)
        assert esize is not None
        tc.assertGreaterEqual(esize[0], 4.0)
        tc.assertGreaterEqual(esize[1], 4.0)

        fp = ent.get("footprint_radius")
        tc.assertTrue(_is_finite_num(fp) and 0.5 <= float(fp) <= 4096.0)

        props = ent.get("properties")
        if isinstance(props, dict) and "z_index" in props:
            z_val = props["z_index"]
            tc.assertTrue(
                _is_finite_num(z_val) and float(z_val) == 0.0,
                f"entity[{idx}] non-canonical z_index: {z_val!r}",
            )

        comps = ent.get("components")
        tc.assertIsInstance(comps, list)
        tc.assertGreaterEqual(len(comps), 2)
        tc.assertEqual(comps[0].get("script"), "res://scenes/entities/components/comp_visual.gd")
        tc.assertEqual(comps[1].get("script"), "res://scenes/entities/components/comp_permission.gd")

        vstate = comps[0].get("state", {})
        tc.assertIsInstance(vstate, dict)
        assert_valid_sprite_path(tc, vstate.get("sprite_path", ""), f"entity[{idx}]")

        if "vector_drawing" in vstate:
            vd = vstate["vector_drawing"]
            tc.assertIsInstance(vd, dict)
            tc.assertEqual(vd.get("schema"), 1)
            fsize = vd.get("font_size", 24.0)
            tc.assertTrue(_is_finite_num(fsize) and 1.0 <= float(fsize) <= 4096.0)
            tc.assertLessEqual(len(str(vd.get("text", ""))), 65536)
            verts = vd.get("vertices", [])
            if isinstance(verts, GdPackedVector2ArraySummary):
                v_size = verts.size
            elif isinstance(verts, list):
                v_size = len(verts)
            else:
                v_size = 0
            tc.assertLessEqual(v_size, 600000)
            tc.assertEqual(v_size % 3, 0)
            paths = vd.get("paths", [])
            tc.assertIsInstance(paths, list)
            tc.assertLessEqual(len(paths), 8192)
            src = vd.get("source", {})
            kind = src.get("kind", "") if isinstance(src, dict) else ""
            total_pts = 0
            for p_idx, ring in enumerate(paths):
                r_size = ring.size if isinstance(ring, GdPackedVector2ArraySummary) else (len(ring) if isinstance(ring, list) else 0)
                total_pts += r_size
                if kind in _OBSTACLE_KINDS:
                    tc.assertGreaterEqual(
                        r_size,
                        3,
                        f"entity[{idx}] obstacle ({kind}) path[{p_idx}] has < 3 vertices",
                    )
            if kind in _OBSTACLE_KINDS:
                tc.assertLessEqual(
                    total_pts,
                    200000,
                    f"entity[{idx}] obstacle ({kind}) total path points > 200000: {total_pts}",
                )
            tc.assertLessEqual(
                v_size + total_pts,
                800000,
                f"entity[{idx}] vector_drawing combined vertices + path points > 800000: {v_size + total_pts}",
            )

        etype = ent.get("entity_type", "")
        for comp in comps[2:]:
            cscript = comp.get("script", "")
            cstate = comp.get("state", {})
            if cscript.endswith("comp_unit.gd"):
                tc.assertNotEqual(etype, "map")
                tc.assertEqual(cstate.get("schema_version"), 1)
            elif cscript.endswith("comp_simple_vision.gd") or cscript.endswith("comp_simple_light.gd"):
                rad = cstate.get("radius", -1.0)
                ang = cstate.get("view_angle", -1.0)
                tc.assertTrue(_is_finite_num(rad) and float(rad) >= 0.0)
                tc.assertTrue(_is_finite_num(ang) and 0.0 <= float(ang) <= 360.0)

    members = world.get("members")
    tc.assertIsInstance(members, list)
    assert isinstance(members, list)
    for m in members:
        meid = m.get("entity_id")
        mfuid = m.get("floor_uid")
        mluid = m.get("layer_uid")
        tc.assertIn(meid, entity_ids)
        tc.assertIn(mfuid, floor_uids)
        tc.assertEqual(layer_owner.get(mluid), mfuid)

    if "modules" in world:
        mods = world["modules"]
        tc.assertIsInstance(mods, dict)
        tc.assertEqual(mods.get("version"), 2)
        entries = mods.get("entries")
        tc.assertIsInstance(entries, dict)
        tc.assertLessEqual(len(entries), 128)
        for mid, entry in entries.items():
            tc.assertRegex(mid, _MODULE_ID_RE)
            tc.assertIsInstance(entry, dict)
            tc.assertGreater(int(entry.get("version", 0)), 0)
            tc.assertIsInstance(entry.get("state"), dict)

    return world


# ---------------------------------------------------------------------------
# Opaque-Box World Inspection Helpers
# ---------------------------------------------------------------------------

def get_floors(world: dict[str, Any]) -> list[dict[str, Any]]:
    return list(world["catalog"]["floors"])


def get_floor_by_name(world: dict[str, Any], name: str) -> dict[str, Any] | None:
    for f in get_floors(world):
        if f.get("name") == name:
            return f
    return None


def get_floor_layers(world: dict[str, Any], floor_uid: str) -> list[dict[str, Any]]:
    for lf in world["catalog"]["layers"]["floors"]:
        if lf.get("floor_uid") == floor_uid:
            return list(lf.get("layers", []))
    return []


def get_layer_kind_map(world: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for lf in world["catalog"]["layers"]["floors"]:
        for layer in lf.get("layers", []):
            out[layer["layer_uid"]] = layer["kind"]
    return out


def get_member_map(world: dict[str, Any]) -> dict[str, tuple[str, str]]:
    return {m["entity_id"]: (m["floor_uid"], m["layer_uid"]) for m in world.get("members", [])}


def get_entities(world: dict[str, Any]) -> list[dict[str, Any]]:
    return list(world["entity_state"]["entities"])


def get_entities_on_floor(
    world: dict[str, Any],
    floor_uid: str,
    *,
    layer_kind: str | None = None,
) -> list[dict[str, Any]]:
    member_map = get_member_map(world)
    kind_map = get_layer_kind_map(world)
    out: list[dict[str, Any]] = []
    for ent in get_entities(world):
        loc = member_map.get(ent["id"])
        if loc is None:
            continue
        fuid, luid = loc
        if fuid != floor_uid:
            continue
        if layer_kind is not None and kind_map.get(luid) != layer_kind:
            continue
        out.append(ent)
    return out


def get_entities_by_layer_kind(world: dict[str, Any], layer_kind: str) -> list[dict[str, Any]]:
    member_map = get_member_map(world)
    kind_map = get_layer_kind_map(world)
    out: list[dict[str, Any]] = []
    for ent in get_entities(world):
        loc = member_map.get(ent["id"])
        if loc is not None and kind_map.get(loc[1]) == layer_kind:
            out.append(ent)
    return out


def get_component(entity: dict[str, Any], script_suffix: str) -> dict[str, Any] | None:
    for comp in entity.get("components", []):
        if str(comp.get("script", "")).endswith(script_suffix):
            return comp
    return None


def get_obstacle_entities(
    world: dict[str, Any],
    *,
    floor_uid: str | None = None,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    ents = get_entities_on_floor(world, floor_uid, layer_kind="obstacle") if floor_uid else get_entities_by_layer_kind(world, "obstacle")
    if kind is None:
        return ents
    out: list[dict[str, Any]] = []
    for ent in ents:
        vd = ent["components"][0]["state"].get("vector_drawing", {})
        src = vd.get("source", {})
        if isinstance(src, dict) and src.get("kind") == kind:
            out.append(ent)
    return out


def get_unit_entities(world: dict[str, Any], *, floor_uid: str | None = None) -> list[dict[str, Any]]:
    ents = get_entities_on_floor(world, floor_uid, layer_kind="entity") if floor_uid else get_entities_by_layer_kind(world, "entity")
    return [
        e for e in ents
        if e.get("entity_type") == "unit" and get_component(e, "comp_unit.gd") is not None
    ]


def _walk_matching_dicts(obj: Any, target_name_cf: str, out: list[dict[str, Any]]) -> None:
    if isinstance(obj, dict):
        n = obj.get("name")
        if isinstance(n, str) and n.strip().casefold() == target_name_cf:
            out.append(obj)
        for k, v in obj.items():
            if isinstance(k, str) and k.strip().casefold() == target_name_cf and isinstance(v, dict):
                out.append(v)
            _walk_matching_dicts(v, target_name_cf, out)
    elif isinstance(obj, list):
        for item in obj:
            _walk_matching_dicts(item, target_name_cf, out)


def find_actor_records(world: dict[str, Any], actor_name: str) -> list[dict[str, Any]]:
    """Opaque-box lookup for structured actor metadata in `world.modules` or entities."""
    target_cf = actor_name.strip().casefold()
    matches: list[dict[str, Any]] = []

    modules_entries = world.get("modules", {}).get("entries", {})
    for mid, mentry in modules_entries.items():
        if mid == "grid_alignment":
            continue
        _walk_matching_dicts(mentry.get("state", {}), target_cf, matches)

    for ent in get_entities(world):
        dname = str(ent.get("display_name", "")).strip().casefold()
        if dname == target_cf or target_cf in dname:
            matches.append(ent)
            continue
        note_comp = get_component(ent, "comp_entity_note.gd")
        if note_comp is not None:
            ntext = str(note_comp.get("state", {}).get("text", "")).casefold()
            if target_cf in ntext:
                matches.append(ent)
    return matches


def _collect_stat_candidates(obj: Any, stat_keys: tuple[str, ...], out: list[Any]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in stat_keys:
                out.append(v)
            _collect_stat_candidates(v, stat_keys, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_stat_candidates(item, stat_keys, out)


def _num_matches(cand: Any, expected: int | float) -> bool:
    if isinstance(cand, (int, float)) and not isinstance(cand, bool):
        return abs(float(cand) - float(expected)) < 1e-4
    if isinstance(cand, str):
        s = cand.strip()
        if "/" in s and isinstance(expected, (int, float)):
            parts = s.split("/")
            if len(parts) == 2:
                try:
                    return abs(float(parts[0]) / float(parts[1]) - float(expected)) < 1e-4
                except (ValueError, ZeroDivisionError):
                    pass
        try:
            return abs(float(s) - float(expected)) < 1e-4
        except ValueError:
            return False
    if isinstance(cand, dict):
        for subk in ("value", "flat", "effective", "computed", "max", "total"):
            if subk in cand and _num_matches(cand[subk], expected):
                return True
    return False


def assert_actor_preserved(
    tc: unittest.TestCase,
    world: dict[str, Any],
    actor_name: str,
    *,
    expected_ac: int | float | None = None,
    expected_hp: int | float | None = None,
    expected_level: int | float | None = None,
    expected_cr: int | float | None = None,
    require_unit_entity: bool = False,
) -> list[dict[str, Any]]:
    """Verify an actor's presence (and optional core stats) across modules/entities without private key coupling."""
    if require_unit_entity:
        unit_hits = [
            u for u in get_unit_entities(world)
            if actor_name.strip().casefold() in str(u.get("display_name", "")).strip().casefold()
        ]
        tc.assertTrue(
            len(unit_hits) >= 1,
            f"Expected at least one unit entity matching {actor_name!r}; units={[u.get('display_name') for u in get_unit_entities(world)]}",
        )

    records = find_actor_records(world, actor_name)
    tc.assertTrue(len(records) >= 1, f"Actor {actor_name!r} not found in world.modules or entities")

    def _check_stat(stat_keys: tuple[str, ...], text_pattern: str, expected: int | float, label: str) -> None:
        cands: list[Any] = []
        for rec in records:
            _collect_stat_candidates(rec, stat_keys, cands)
        if any(_num_matches(c, expected) for c in cands):
            return
        # Fallback: check comp_entity_note or string fields
        rx = re.compile(text_pattern, re.IGNORECASE)
        for rec in records:
            if rx.search(str(rec)):
                return
        tc.fail(f"Actor {actor_name!r} missing expected {label}={expected!r}; candidates={cands!r}, records={records!r}")

    if expected_ac is not None:
        _check_stat(("ac", "armor_class", "ac_value", "effective_ac"), rf"\bAC\s*[:=]\s*{re.escape(str(expected_ac))}\b", expected_ac, "AC")
    if expected_hp is not None:
        _check_stat(("hp", "hp_value", "hp_max", "hit_points"), rf"\bHP\s*[:=]\s*{re.escape(str(expected_hp))}\b", expected_hp, "HP")
    if expected_level is not None:
        _check_stat(("level", "cr_or_level"), rf"\b(?:level|lv|lvl)\s*[:=]\s*{re.escape(str(expected_level))}\b", expected_level, "level")
    if expected_cr is not None:
        _check_stat(("cr", "cr_or_level", "challenge"), rf"\bCR\s*[:=]\s*{re.escape(str(expected_cr))}\b", expected_cr, "CR")

    return records
