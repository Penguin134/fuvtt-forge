"""Reusable opaque-box validators for Fu vtt Practice v3 worlds, R2 warnings, R3 LogBus, ZIP/manifest, GDScript hygiene, and R4 path compliance."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Sequence
import unittest
import zipfile

from .harness import ALL_PLUGIN_SDK_IDS, SdkProbeCaseResult


COMP_VISUAL_SCRIPT = "res://scenes/entities/components/comp_visual.gd"
COMP_PERMISSION_SCRIPT = "res://scenes/entities/components/comp_permission.gd"

UID_32_RE = re.compile(r"^[0-9a-f]{32}$")
MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")
HEX8_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{8}$")
COVER_ASSET_RE = re.compile(r"^asset://[0-9a-f]{64}\.(png|jpg|jpeg|webp|bmp)$")
LOCAL_PATH_LEAK_RE = re.compile(
    r"(?:[A-Za-z]:[/\\](?:Users|Program Files|Steam|DND|Projects|Work|home)[/\\]|/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/)"
)
CLASS_NAME_RE = re.compile(r"^\s*class_name\b", re.MULTILINE)
PRELOAD_RE = re.compile(r"\bpreload\s*\(")
SIBLING_LOAD_RE = re.compile(r"""\bload\s*\(\s*["'][^"']*\.gd["']""")

EXPECTED_MODULAR_SDK_FILES: tuple[str, ...] = (
    "v1.gd",
    "adapters/host_v1_adapter.gd",
    "logging/log_bus.gd",
    "utils/dag_cloner.gd",
    "utils/bounded_cloner.gd",
    "utils/value_utils.gd",
    "utils/validation_utils.gd",
    "plugins/module_registry.gd",
    "modules/asset_publisher.gd",
    "modules/entity_library_writer.gd",
    "modules/package_source.gd",
    "modules/snappy.gd",
    *(f"plugins/{mid}.gd" for mid in ALL_PLUGIN_SDK_IDS),
)


def strip_gdscript_comments(src: str) -> str:
    """Strip `#` line comments while keeping string literals intact enough for static hygiene scans."""
    out_lines: list[str] = []
    for line in src.splitlines():
        in_sq = False
        in_dq = False
        escaped = False
        cut = len(line)
        for idx, ch in enumerate(line):
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == "'" and not in_dq:
                in_sq = not in_sq
            elif ch == '"' and not in_sq:
                in_dq = not in_dq
            elif ch == "#" and not in_sq and not in_dq:
                cut = idx
                break
        out_lines.append(line[:cut])
    return "\n".join(out_lines)


def assert_case_clean(tc: unittest.TestCase, result: SdkProbeCaseResult) -> None:
    """Assert the Godot case completed with zero log errors and zero GDScript failures."""
    tc.assertTrue(
        result.completed,
        f"[{result.case_id}] Probe did not complete (timed_out={result.timed_out}, exit_code={result.exit_code}, logs={result.log_errors})",
    )
    tc.assertEqual(
        result.log_errors,
        [],
        f"[{result.case_id}] Unexpected Godot log/stderr errors: {result.log_errors}",
    )
    tc.assertEqual(
        result.gd_check_failures,
        [],
        f"[{result.case_id}] GDScript check failures: {result.gd_check_failures}",
    )


def assert_case_passed(tc: unittest.TestCase, result: SdkProbeCaseResult) -> dict[str, Any]:
    """Assert the Godot case completed cleanly AND `ok == True`."""
    assert_case_clean(tc, result)
    tc.assertTrue(result.ok, f"[{result.case_id}] Case returned ok=False: data={result.data}")
    return result.data


def assert_world_v3_invariants(tc: unittest.TestCase, world: dict[str, Any], ctx: str = "") -> None:
    """Validate Practice v3 world schema, components[0..1], parked/manual invariants, and modules envelope."""
    prefix = f"[{ctx}] " if ctx else ""
    tc.assertIsInstance(world, dict, f"{prefix}world must be dict")
    tc.assertEqual(world.get("format"), "fus.practice.world", f"{prefix}invalid world.format")
    tc.assertEqual(world.get("version"), 3, f"{prefix}invalid world.version")

    catalog = world.get("catalog")
    tc.assertIsInstance(catalog, dict, f"{prefix}world.catalog must be dict")
    assert isinstance(catalog, dict)
    floors = catalog.get("floors")
    tc.assertIsInstance(floors, list, f"{prefix}catalog.floors must be list")
    assert isinstance(floors, list)
    tc.assertGreaterEqual(len(floors), 1, f"{prefix}catalog.floors empty")
    tc.assertLessEqual(len(floors), 512, f"{prefix}catalog.floors > 512")

    floor_uids: set[str] = set()
    for f in floors:
        tc.assertIsInstance(f, dict)
        fuid = str(f.get("floor_uid", ""))
        tc.assertRegex(fuid, UID_32_RE, f"{prefix}invalid floor_uid: {fuid!r}")
        tc.assertNotIn(fuid, floor_uids, f"{prefix}duplicate floor_uid: {fuid}")
        floor_uids.add(fuid)

    active_floor_uid = str(catalog.get("active_floor_uid", ""))
    tc.assertIn(active_floor_uid, floor_uids, f"{prefix}active_floor_uid missing in floors")

    layers_root = catalog.get("layers")
    tc.assertIsInstance(layers_root, dict)
    assert isinstance(layers_root, dict)
    tc.assertEqual(layers_root.get("schema"), "fus.floor_layers.v2")
    layer_owner: dict[str, str] = {}
    for lf in layers_root.get("floors", []):
        lfuid = str(lf.get("floor_uid", ""))
        tc.assertIn(lfuid, floor_uids, f"{prefix}layers.floors references unknown floor {lfuid}")
        for layer in lf.get("layers", []):
            luid = str(layer.get("layer_uid", ""))
            tc.assertRegex(luid, UID_32_RE, f"{prefix}invalid layer_uid: {luid!r}")
            tc.assertIn(layer.get("kind"), {"map", "entity", "obstacle", "area"})
            tc.assertIn(layer.get("access"), {"all", "host", "players"})
            layer_owner[luid] = lfuid

    entity_state = world.get("entity_state")
    tc.assertIsInstance(entity_state, dict)
    assert isinstance(entity_state, dict)
    tc.assertEqual(entity_state.get("version"), 3)
    entities = entity_state.get("entities")
    tc.assertIsInstance(entities, list)
    assert isinstance(entities, list)
    entity_ids: set[str] = set()
    for idx, ent in enumerate(entities):
        tc.assertIsInstance(ent, dict)
        eid = str(ent.get("id", ""))
        tc.assertTrue(bool(eid), f"{prefix}entity[{idx}] empty id")
        tc.assertNotIn(eid, entity_ids, f"{prefix}duplicate entity id: {eid}")
        entity_ids.add(eid)

        comps = ent.get("components")
        tc.assertIsInstance(comps, list, f"{prefix}entity[{idx}].components must be list")
        assert isinstance(comps, list)
        tc.assertGreaterEqual(len(comps), 2, f"{prefix}entity[{idx}].components < 2")
        c0 = comps[0]
        c1 = comps[1]
        tc.assertEqual(c0.get("script"), COMP_VISUAL_SCRIPT, f"{prefix}entity[{idx}].components[0] not comp_visual")
        tc.assertEqual(c1.get("script"), COMP_PERMISSION_SCRIPT, f"{prefix}entity[{idx}].components[1] not comp_permission")
        tc.assertNotIn("parked", c0, f"{prefix}comp_visual must not be parked")
        tc.assertNotIn("manual", c0, f"{prefix}comp_visual must not have manual")
        tc.assertNotIn("parked", c1, f"{prefix}comp_permission must not be parked")
        tc.assertNotIn("manual", c1, f"{prefix}comp_permission must not have manual")

        for cidx, comp in enumerate(comps[2:], start=2):
            tc.assertIsInstance(comp, dict)
            keys = set(comp.keys())
            allowed_sets = (
                {"script", "state"},
                {"script", "state", "parked"},
                {"script", "state", "parked", "manual"},
            )
            tc.assertIn(keys, allowed_sets, f"{prefix}entity[{idx}].components[{cidx}] invalid keys: {keys}")
            if "parked" in comp:
                tc.assertIsInstance(comp["parked"], bool)
            if "manual" in comp:
                tc.assertIsInstance(comp["manual"], bool)
                if comp["manual"] is True:
                    tc.assertIs(comp.get("parked"), True, f"{prefix}manual=true requires parked=true")

    members = world.get("members")
    tc.assertIsInstance(members, list)
    assert isinstance(members, list)
    for m_idx, m in enumerate(members):
        meid = str(m.get("entity_id", ""))
        mfuid = str(m.get("floor_uid", ""))
        mluid = str(m.get("layer_uid", ""))
        tc.assertIn(meid, entity_ids, f"{prefix}members[{m_idx}] unknown entity {meid}")
        tc.assertIn(mfuid, floor_uids, f"{prefix}members[{m_idx}] unknown floor {mfuid}")
        tc.assertEqual(layer_owner.get(mluid), mfuid, f"{prefix}members[{m_idx}] layer {mluid} not on floor {mfuid}")

    if "modules" in world:
        mods = world["modules"]
        tc.assertIsInstance(mods, dict)
        tc.assertEqual(mods.get("version"), 2)
        entries = mods.get("entries")
        tc.assertIsInstance(entries, dict)
        assert isinstance(entries, dict)
        tc.assertLessEqual(len(entries), 128)
        for mid, entry in entries.items():
            tc.assertIsInstance(mid, str)
            tc.assertLessEqual(len(mid), 128)
            tc.assertRegex(mid, MODULE_ID_RE, f"{prefix}invalid module_id {mid!r}")
            tc.assertIsInstance(entry, dict)
            ver = entry.get("version")
            tc.assertTrue(isinstance(ver, int) and not isinstance(ver, bool) and ver >= 1, f"{prefix}bad module version {ver!r}")
            tc.assertIsInstance(entry.get("state"), dict, f"{prefix}module {mid} state not dict")


def assert_world_module_entry(
    tc: unittest.TestCase,
    world: dict[str, Any],
    module_id: str,
    *,
    expected_version: int = 1,
) -> dict[str, Any]:
    entries = world.get("modules", {}).get("entries", {})
    tc.assertIn(module_id, entries, f"world.modules.entries missing {module_id!r}")
    entry = entries[module_id]
    tc.assertEqual(entry.get("version"), expected_version)
    state = entry.get("state")
    tc.assertIsInstance(state, dict)
    return state


def assert_entity_has_component(
    tc: unittest.TestCase,
    entity: dict[str, Any],
    script_path: str,
    *,
    parked: bool | None = None,
    manual: bool | None = None,
) -> dict[str, Any]:
    comps = entity.get("components", [])
    matches = [(idx, c) for idx, c in enumerate(comps) if isinstance(c, dict) and c.get("script") == script_path]
    tc.assertTrue(matches, f"Entity {entity.get('id')!r} missing component {script_path!r}")
    idx, comp = matches[0]
    tc.assertGreaterEqual(idx, 2, f"Optional/non-core component {script_path!r} must be at index >= 2")
    if parked is not None:
        tc.assertIs(bool(comp.get("parked", False)), parked, f"Component {script_path!r} parked mismatch: {comp}")
    if manual is not None:
        tc.assertIs(bool(comp.get("manual", False)), manual, f"Component {script_path!r} manual mismatch: {comp}")
    return comp


def assert_r2_warning_present(
    tc: unittest.TestCase,
    warnings: Sequence[Any],
    module_id: str,
    *,
    status: str | None = None,
    policy: str | None = None,
) -> None:
    """Assert at least one R2 warning (string or LogBus dict) mentions `module_id` (and status/policy if given)."""
    rendered: list[str] = []
    for item in warnings:
        if isinstance(item, dict):
            msg = str(item.get("message", ""))
            ctx = json.dumps(item.get("context", {}), ensure_ascii=False)
            rendered.append(f"{msg} {ctx}")
        else:
            rendered.append(str(item))
    matching = [txt for txt in rendered if module_id in txt]
    tc.assertTrue(
        matching,
        f"Expected R2 warning naming module_id={module_id!r}, got warnings={rendered!r}",
    )
    if status is not None:
        tc.assertTrue(
            any(status in txt for txt in matching),
            f"Expected warning for {module_id!r} to mention status={status!r}, got {matching!r}",
        )
    if policy is not None:
        tc.assertTrue(
            any(policy in txt for txt in matching),
            f"Expected warning for {module_id!r} to mention policy={policy!r}, got {matching!r}",
        )


def assert_logbus_entry_schema(
    tc: unittest.TestCase,
    entry: dict[str, Any],
    *,
    expected_level: int | None = None,
    expected_source: str | None = None,
) -> None:
    tc.assertIsInstance(entry, dict)
    seq = entry.get("seq")
    tc.assertTrue(isinstance(seq, int) and not isinstance(seq, bool) and seq >= 1, f"bad LogBus seq: {seq!r}")
    lvl = entry.get("level")
    tc.assertIn(lvl, {10, 20, 30, 40}, f"unexpected LogBus level: {lvl!r}")
    tc.assertIsInstance(entry.get("level_name"), str)
    tc.assertTrue(bool(str(entry.get("level_name", "")).strip()))
    tc.assertIsInstance(entry.get("source"), str)
    tc.assertIsInstance(entry.get("message"), str)
    tc.assertIsInstance(entry.get("context"), dict)
    if expected_level is not None:
        tc.assertEqual(lvl, expected_level)
    if expected_source is not None:
        tc.assertEqual(entry.get("source"), expected_source)


def assert_build_artifact_bundles_sdk(
    tc: unittest.TestCase,
    build_dir: Path,
    mod_name: str,
    *,
    expected_sdk_files: Iterable[str] = EXPECTED_MODULAR_SDK_FILES,
) -> dict[str, Any]:
    mod_build = build_dir / mod_name
    manifest_path = mod_build / "build-manifest.json"
    zip_path = mod_build / f"{mod_name}.zip"
    tc.assertTrue(manifest_path.is_file(), f"Missing build-manifest.json: {manifest_path}")
    tc.assertTrue(zip_path.is_file(), f"Missing built ZIP: {zip_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tc.assertIs(manifest.get("sdk_bundled"), True, f"{mod_name} build-manifest sdk_bundled != True")
    files = manifest.get("files", [])
    tc.assertGreaterEqual(len(files), 2)
    tc.assertLessEqual(len(files), 1000)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zip_names = set(zf.namelist())
        tc.assertEqual(set(files), zip_names, f"{mod_name} manifest files differ from ZIP contents")
        for rel_sdk in expected_sdk_files:
            expected_member = f"lib/fu_sdk/{rel_sdk}"
            tc.assertIn(expected_member, zip_names, f"{mod_name} ZIP missing {expected_member}")
            expected_hash = manifest.get("file_hashes", {}).get(expected_member)
            actual_hash = hashlib.sha256(zf.read(expected_member)).hexdigest()
            tc.assertEqual(actual_hash, expected_hash, f"SHA-256 mismatch for {expected_member}")
    return manifest


def assert_gdscript_hygiene(tc: unittest.TestCase, gd_path: Path, *, sdk_root: Path | None = None) -> None:
    raw = gd_path.read_bytes()
    tc.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"UTF-8 BOM forbidden: {gd_path}")
    tc.assertNotIn(b"\r\n", raw, f"CRLF forbidden (must be LF): {gd_path}")
    text = raw.decode("utf-8")

    first_non_empty = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            first_non_empty = stripped
            break
    tc.assertEqual(first_non_empty, "extends RefCounted", f"First non-empty line must be 'extends RefCounted': {gd_path}")

    stripped_comments = strip_gdscript_comments(text)
    tc.assertIsNone(CLASS_NAME_RE.search(stripped_comments), f"`class_name` forbidden in {gd_path}")
    tc.assertIsNone(PRELOAD_RE.search(stripped_comments), f"`preload(` forbidden in {gd_path}")
    tc.assertIsNone(LOCAL_PATH_LEAK_RE.search(text), f"Hardcoded local path found in {gd_path}")

    if sdk_root is not None:
        rel = gd_path.resolve().relative_to(sdk_root.resolve()).as_posix()
        if rel.startswith("modules/"):
            tc.assertIsNone(
                SIBLING_LOAD_RE.search(stripped_comments),
                f"Sibling .gd `load(` forbidden inside modules/: {gd_path}",
            )
        elif rel.startswith("utils/"):
            tc.assertIsNone(
                re.search(r"\bload\s*\(", stripped_comments),
                f"Leaf `utils/` script must not call `load(`: {gd_path}",
            )


def assert_no_local_paths_in_text(tc: unittest.TestCase, text: str, *, label: str = "") -> None:
    match = LOCAL_PATH_LEAK_RE.search(text)
    tc.assertIsNone(match, f"Hardcoded local machine path found in {label or 'text'}: {match.group(0) if match else ''}")


def is_finite_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))
