"""Reusable opaque-box assertions for Dual-Mode SDK, `.zip`/`.fup`/`content.pck`, `SHA256SUMS.txt`, `registry.json`, hygiene & repo isolation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any, Iterable, Mapping
import unittest
import zipfile

from .harness import ProbeBatchSummary, ProbeCaseResult


LOCAL_PATH_LEAK_RE = re.compile(
    r"(?:[A-Za-z]:[/\\](?:Users|Program Files(?: \(x86\))?|Steam|SteamLibrary|DND|Projects|Work|home|toolchains)[/\\]"
    r"|/Users/[A-Za-z0-9._-]+/"
    r"|/home/[A-Za-z0-9._-]+/"
    r"|/opt/[A-Za-z0-9._-]+"
    r"|/Volumes/[A-Za-z0-9._ -]+)"
)
CLASS_NAME_RE = re.compile(r"(?:^|;)\s*class_name\b", re.MULTILINE)
PRELOAD_RE = re.compile(r"\bpreload\s*\(")
CUSTOM_HOOK_RE = re.compile(r"^(?:ext|mod)\.[a-z0-9_]+(?:\.[a-z0-9_]+)+$")
PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}(?:\.[a-z0-9_]{1,63})*$")

FORBIDDEN_BINARY_EXTENSIONS: frozenset[str] = frozenset({
    ".dll",
    ".exe",
    ".so",
    ".dylib",
    ".gdextension",
    ".bat",
    ".cmd",
    ".ps1",
    ".sh",
})

EXPECTED_FU_SDK_35_FILES: tuple[str, ...] = (
    "adapters/host_v1_adapter.gd",
    "logging/log_bus.gd",
    "modules/asset_publisher.gd",
    "modules/entity_library_writer.gd",
    "modules/package_source.gd",
    "modules/snappy.gd",
    "plugins/areas.gd",
    "plugins/backpack.gd",
    "plugins/campaign_time.gd",
    "plugins/candidate_initiative.gd",
    "plugins/character_roster.gd",
    "plugins/checklist.gd",
    "plugins/dice.gd",
    "plugins/dnd_opportunity.gd",
    "plugins/drag_movement.gd",
    "plugins/drawing.gd",
    "plugins/entity_notes.gd",
    "plugins/feature_edit_mode.gd",
    "plugins/feature_entity_library.gd",
    "plugins/feature_floor_system.gd",
    "plugins/feature_layer_stack.gd",
    "plugins/feature_obstacle_authoring.gd",
    "plugins/follow.gd",
    "plugins/grid_alignment.gd",
    "plugins/image_flip.gd",
    "plugins/module_registry.gd",
    "plugins/portal.gd",
    "plugins/resource_pool.gd",
    "plugins/scene_box.gd",
    "plugins/simple_fog.gd",
    "utils/bounded_cloner.gd",
    "utils/dag_cloner.gd",
    "utils/validation_utils.gd",
    "utils/value_utils.gd",
    "v1.gd",
)

EXPECTED_SHARED_FU_SDK_SUBSET: tuple[str, ...] = (
    "utils/dag_cloner.gd",
    "utils/bounded_cloner.gd",
    "utils/value_utils.gd",
    "utils/validation_utils.gd",
    "logging/log_bus.gd",
    "plugins/module_registry.gd",
)

EXPECTED_FU_RUNTIME_SCRIPTS: tuple[str, ...] = (
    "v2.gd",
    "desktop_api_helper.gd",
    "hook_helper.gd",
    "slot_helper.gd",
    "comp_helper.gd",
    "network_helper.gd",
)


def strip_gdscript_comments(src: str) -> str:
    """Strip `#` line comments while keeping string literals intact."""
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
            elif ch == '"' and not in_dq:
                in_dq = not in_dq
            elif ch == "#" and not in_sq and not in_dq:
                cut = idx
                break
        out_lines.append(line[:cut])
    return "\n".join(out_lines)


def _merge_unique_strs(primary: Iterable[str], secondary: Iterable[str]) -> list[str]:
    merged = list(primary)
    for item in secondary:
        if item not in merged:
            merged.append(item)
    return merged


def assert_case_clean(
    tc: unittest.TestCase,
    result: ProbeCaseResult,
    summary: ProbeBatchSummary | None = None,
) -> None:
    global_errs = (
        _merge_unique_strs(summary.global_log_errors, result.global_log_errors)
        if summary is not None
        else list(result.global_log_errors)
    )
    comp_failures = (
        _merge_unique_strs(summary.compile_failures, result.compile_failures)
        if summary is not None
        else list(result.compile_failures)
    )
    tc.assertTrue(
        result.completed,
        f"[{result.case_id}] Probe did not complete (timed_out={result.timed_out}, exit_code={result.exit_code}, logs={result.log_errors}, global_logs={global_errs})",
    )
    tc.assertEqual(
        result.exit_code,
        0,
        f"[{result.case_id}] Godot exited with non-zero exit_code={result.exit_code} (logs={result.log_errors}, global_logs={global_errs})",
    )
    tc.assertEqual(
        result.log_errors,
        [],
        f"[{result.case_id}] Unexpected Godot log/stderr errors: {result.log_errors}",
    )
    tc.assertEqual(
        global_errs,
        [],
        f"[{result.case_id}] Unexpected global Godot log/stderr/exit-leak errors: {global_errs}",
    )
    tc.assertEqual(
        comp_failures,
        [],
        f"[{result.case_id}] Godot compile failures: {comp_failures}",
    )
    tc.assertEqual(
        result.gd_check_failures,
        [],
        f"[{result.case_id}] GDScript check failures: {result.gd_check_failures}",
    )


def assert_case_passed(
    tc: unittest.TestCase,
    result: ProbeCaseResult,
    summary: ProbeBatchSummary | None = None,
) -> dict[str, Any]:
    assert_case_clean(tc, result, summary=summary)
    tc.assertTrue(result.ok, f"[{result.case_id}] Case returned ok=False: data={result.data}")
    return result.data


def assert_batch_clean(tc: unittest.TestCase, summary: ProbeBatchSummary) -> None:
    tc.assertEqual(
        summary.global_log_errors,
        [],
        f"Unexpected global Godot log/stderr/exit-leak errors: {summary.global_log_errors}",
    )
    tc.assertEqual(
        summary.compile_failures,
        [],
        f"Godot compile failures: {summary.compile_failures}",
    )
    for res in summary.results.values():
        assert_case_clean(tc, res, summary=summary)


def assert_parity_clean(
    tc: unittest.TestCase,
    parity: Mapping[str, Any],
    *,
    expected_mode: str | None = None,
) -> dict[str, Any]:
    tc.assertEqual(
        parity.get("returncode"),
        0,
        f"FUS build_world_plugin parity failed (rc={parity.get('returncode')}): {parity.get('stderr', '')}",
    )
    tc.assertEqual(
        parity.get("log_errors"),
        [],
        f"Unexpected Godot log/stderr/exit-leak errors in FUS parity run: {parity.get('log_errors')}",
    )
    res = parity.get("result")
    tc.assertIsInstance(res, dict, f"FUS parity result must be a dict, got {type(res).__name__}: {res!r}")
    assert isinstance(res, dict)
    tc.assertIs(res.get("ok"), True, f"FUS parity result ok!=True: {res!r}")
    if expected_mode is not None:
        tc.assertEqual(res.get("mode"), expected_mode, f"Unexpected FUS parity mode: {res!r}")
    return res


def _iter_doc_cli_segments(doc_text: str) -> list[tuple[int, str]]:
    """Extract logical command segments from markdown fenced blocks and inline backticks."""
    segments: list[tuple[int, str]] = []
    in_fence = False
    cont_parts: list[str] = []
    cont_start_line = 0

    def _flush_cont() -> None:
        nonlocal cont_parts, cont_start_line
        if cont_parts:
            segments.append((cont_start_line, " ".join(cont_parts)))
            cont_parts = []
            cont_start_line = 0

    for line_no, raw_line in enumerate(doc_text.splitlines(), 1):
        if raw_line.strip().startswith("```"):
            if in_fence:
                _flush_cont()
            in_fence = not in_fence
            continue
        if in_fence:
            rstripped = raw_line.rstrip()
            trailing_bs = len(rstripped) - len(rstripped.rstrip("\\"))
            if trailing_bs % 2 == 1:
                if not cont_parts:
                    cont_start_line = line_no
                cont_parts.append(rstripped[:-1].rstrip())
            else:
                if cont_parts:
                    cont_parts.append(raw_line.strip())
                    _flush_cont()
                else:
                    segments.append((line_no, raw_line))
        else:
            for inline in re.findall(r"`([^`]+)`", raw_line):
                segments.append((line_no, inline))

    _flush_cont()
    return segments


def lint_doc_cli_commands(
    tc: unittest.TestCase,
    doc_text: str,
    valid_flags: Mapping[str, set[str]],
    *,
    label: str = "doc",
    require_known_subcommand: bool = True,
) -> int:
    """Validate `fuvtt_cli.py <subcommand> --flags` references in markdown against `--help` flags."""
    checked_cmds = 0
    for line_no, seg in _iter_doc_cli_segments(doc_text):
        for part in re.split(r"\s*(?:\|\||&&|[|;])\s*", seg):
            m = re.search(r"fuvtt_cli\.py\s+([a-z][a-z0-9-]*)\b(.*)$", part)
            if not m:
                continue
            subcmd = m.group(1)
            if subcmd not in valid_flags:
                if require_known_subcommand:
                    tc.fail(f"Unknown fuvtt_cli.py subcommand {subcmd!r} in {label}:{line_no}")
                continue
            checked_cmds += 1
            for flag in re.findall(r"--[a-z0-9][a-z0-9-]*", m.group(2)):
                tc.assertIn(
                    flag,
                    valid_flags[subcmd],
                    f"Stale/unknown flag {flag} for {subcmd} in {label}:{line_no}",
                )
    return checked_cmds


def assert_no_local_paths_in_text(tc: unittest.TestCase, text: str, *, label: str = "") -> None:
    match = LOCAL_PATH_LEAK_RE.search(text)
    tc.assertIsNone(
        match,
        f"Hardcoded local machine path found in {label or 'text'}: {match.group(0) if match else ''}",
    )


def assert_gdscript_hygiene(
    tc: unittest.TestCase,
    gd_path: Path,
    *,
    require_extends_refcounted: bool = False,
    forbid_class_name: bool = True,
    forbid_preload: bool = True,
) -> None:
    raw = gd_path.read_bytes()
    tc.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"UTF-8 BOM forbidden: {gd_path}")
    tc.assertNotIn(b"\r\n", raw, f"CRLF forbidden (must be LF): {gd_path}")
    text = raw.decode("utf-8")

    if require_extends_refcounted:
        first_non_empty = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                first_non_empty = stripped
                break
        tc.assertEqual(
            first_non_empty,
            "extends RefCounted",
            f"First non-empty line must be 'extends RefCounted': {gd_path}",
        )

    stripped_comments = strip_gdscript_comments(text)
    if forbid_class_name:
        tc.assertIsNone(CLASS_NAME_RE.search(stripped_comments), f"`class_name` forbidden in {gd_path}")
    if forbid_preload:
        tc.assertIsNone(PRELOAD_RE.search(stripped_comments), f"`preload(` forbidden in {gd_path}")
    assert_no_local_paths_in_text(tc, text, label=str(gd_path))


def assert_fu_sdk_35_invariance(tc: unittest.TestCase, sdk_dir: Path) -> None:
    actual = sorted(p.relative_to(sdk_dir).as_posix() for p in sdk_dir.rglob("*.gd"))
    tc.assertEqual(len(actual), 35, f"shared/sdk/fu_sdk must have exact 35 .gd scripts, found {len(actual)}")
    tc.assertEqual(actual, list(EXPECTED_FU_SDK_35_FILES))


def parse_standalone_pck_entries(pck_bytes: bytes) -> list[dict[str, Any]]:
    """Parse standalone Godot 4 PCK (`GDPC`) header + directory table and verify magic."""
    if len(pck_bytes) < 32:
        raise AssertionError(f"PCK too small ({len(pck_bytes)} bytes)")
    if pck_bytes[:4] != b"GDPC":
        raise AssertionError(f"Invalid PCK magic: {pck_bytes[:4]!r} != b'GDPC'")

    fmt_ver, major, minor, patch, flags = struct.unpack_from("<5I", pck_bytes, 4)
    if fmt_ver not in (2, 3, 4):
        raise AssertionError(f"Unsupported PCK format version: {fmt_ver}")

    # Godot 4 PCK header layout:
    # magic(4) + fmt(4) + maj(4) + min(4) + patch(4) + flags(4) + file_base(8) + reserved(16*4=64) = 96 bytes
    # In fmt_ver >= 3 with dir_offset, file_base is u64 at offset 24, dir_offset u64 at offset 32 (total 104 or 96)
    pos = 24
    if fmt_ver >= 2:
        _file_base = struct.unpack_from("<Q", pck_bytes, pos)[0]
        pos += 8
    if fmt_ver >= 3:
        dir_offset = struct.unpack_from("<Q", pck_bytes, pos)[0]
        pos += 8
        # Skip 16 reserved uint32s
        pos += 64
        # If PACK_DIR_AT_END_FLAG (bit 1 = 2) is set and dir_offset > 0, jump to dir_offset
        if (flags & 2) != 0 and dir_offset > 0:
            pos = dir_offset
    else:
        pos += 64

    file_count = struct.unpack_from("<I", pck_bytes, pos)[0]
    pos += 4
    entries: list[dict[str, Any]] = []
    for _ in range(file_count):
        path_len = struct.unpack_from("<I", pck_bytes, pos)[0]
        pos += 4
        raw_path = pck_bytes[pos : pos + path_len]
        pos += path_len
        res_path = raw_path.rstrip(b"\x00").decode("utf-8", errors="replace")
        offset, size = struct.unpack_from("<2Q", pck_bytes, pos)
        pos += 16
        md5_bytes = pck_bytes[pos : pos + 16]
        pos += 16
        entry_flags = struct.unpack_from("<I", pck_bytes, pos)[0]
        pos += 4
        entries.append({
            "res_path": res_path,
            "offset": offset,
            "size": size,
            "md5": md5_bytes.hex(),
            "flags": entry_flags,
        })
    return entries


def assert_zip_archive_contract(
    tc: unittest.TestCase,
    zip_path: Path,
    *,
    expected_schema: str,
    plugin_id: str,
    expect_sdk: bool = True,
    namespace_prefix: str | None = None,
    check_deterministic_ts: bool = True,
) -> dict[str, Any]:
    tc.assertTrue(zip_path.is_file(), f"Missing ZIP archive: {zip_path}")
    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = zf.infolist()
        names = {info.filename for info in infos}
        tc.assertIn("plugin.json", names, f"{zip_path} missing plugin.json")
        tc.assertGreaterEqual(len(names), 2)
        tc.assertLessEqual(len(names), 1000)

        for info in infos:
            fn = info.filename
            raw_fn = getattr(info, "orig_filename", fn)
            tc.assertNotEqual(((info.external_attr >> 16) & 0xF000), 0xA000, f"ZIP symlink rejected: {raw_fn}")
            for candidate in (raw_fn, fn) if raw_fn != fn else (fn,):
                tc.assertNotIn("\\", candidate, f"Unsafe ZIP backslash path: {candidate}")
                tc.assertNotIn(":", candidate, f"Unsafe ZIP colon/drive path: {candidate}")
                trimmed = candidate[:-1] if candidate.endswith("/") else candidate
                segments = trimmed.split("/") if trimmed else []
                tc.assertFalse(
                    candidate.startswith("/")
                    or not segments
                    or any(seg == "" or seg in (".", "..") or seg.endswith(".") or seg.endswith(" ") for seg in segments),
                    f"Unsafe ZIP path: {candidate}",
                )
            ext = Path(fn).suffix.lower()
            tc.assertNotIn(ext, FORBIDDEN_BINARY_EXTENSIONS, f"Forbidden binary in ZIP: {fn}")
            if check_deterministic_ts:
                tc.assertEqual(info.date_time, (2026, 1, 1, 0, 0, 0), f"Non-deterministic ZIP timestamp on {fn}: {info.date_time}")

        manifest = json.loads(zf.read("plugin.json").decode("utf-8"))
        tc.assertEqual(manifest.get("schema"), expected_schema)
        tc.assertEqual(manifest.get("id"), plugin_id)

        if namespace_prefix:
            if expect_sdk:
                tc.assertIn(f"{namespace_prefix}/lib/fu_runtime/v2.gd", names, f"Missing bundled fu_runtime/v2.gd in {namespace_prefix}/lib/")
                for rel_rt in EXPECTED_FU_RUNTIME_SCRIPTS:
                    tc.assertIn(f"{namespace_prefix}/lib/fu_runtime/{rel_rt}", names)
                for rel_sdk in EXPECTED_SHARED_FU_SDK_SUBSET:
                    tc.assertIn(f"{namespace_prefix}/lib/fu_sdk/{rel_sdk}", names)
            else:
                tc.assertFalse(
                    any("/lib/fu_runtime/" in n or "/lib/fu_sdk/" in n for n in names),
                    f"Expected --no-sdk to omit bundled SDK scripts, got: {sorted(names)}",
                )
    return manifest


def assert_fup_archive_contract(
    tc: unittest.TestCase,
    fup_path: Path,
    *,
    plugin_id: str,
    pack_file: str = "content.pck",
    expected_res_paths: Iterable[str] = (),
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tc.assertTrue(fup_path.is_file(), f"Missing .fup archive: {fup_path}")
    with zipfile.ZipFile(fup_path, "r") as zf:
        names = set(zf.namelist())
        tc.assertIn("plugin.json", names)
        tc.assertIn(pack_file, names)
        tc.assertIn("SHA256SUMS.txt", names)

        manifest_bytes = zf.read("plugin.json")
        pck_bytes = zf.read(pack_file)
        sums_text = zf.read("SHA256SUMS.txt").decode("utf-8")

    manifest = json.loads(manifest_bytes.decode("utf-8"))
    tc.assertEqual(manifest.get("schema"), "fus.plugin.v2")
    tc.assertEqual(manifest.get("id"), plugin_id)

    expected_manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    expected_pck_sha = hashlib.sha256(pck_bytes).hexdigest()

    parsed_sums: dict[str, str] = {}
    for line in sums_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        tc.assertEqual(len(parts), 2, f"Malformed SHA256SUMS.txt line: {line!r}")
        parsed_sums[parts[1].strip()] = parts[0].strip().lower()

    tc.assertEqual(parsed_sums.get("plugin.json"), expected_manifest_sha, "SHA256SUMS.txt plugin.json digest mismatch")
    tc.assertEqual(parsed_sums.get(pack_file), expected_pck_sha, f"SHA256SUMS.txt {pack_file} digest mismatch")

    entries = parse_standalone_pck_entries(pck_bytes)
    entry_paths = {str(e["res_path"]).removeprefix("res://") for e in entries}
    for exp in expected_res_paths:
        norm_exp = str(exp).removeprefix("res://")
        tc.assertIn(norm_exp, entry_paths, f"content.pck missing {norm_exp}; found={sorted(entry_paths)[:20]}")
    return manifest, entries


def assert_registry_json_valid(
    tc: unittest.TestCase,
    registry_path: Path,
    expected_plugin_ids: Iterable[str] = (),
) -> dict[str, Any]:
    tc.assertTrue(registry_path.is_file(), f"Missing registry.json: {registry_path}")
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    tc.assertEqual(data.get("version"), 1)
    plugins = data.get("plugins")
    tc.assertIsInstance(plugins, dict)
    assert isinstance(plugins, dict)
    for pid in expected_plugin_ids:
        tc.assertIn(pid, plugins, f"registry.json missing plugin {pid!r}")
        row = plugins[pid]
        tc.assertIsInstance(row, dict)
        tc.assertTrue(bool(row.get("sha256")), f"registry row {pid} missing sha256")
        tc.assertIsInstance(row.get("file_hashes"), dict, f"registry row {pid} missing file_hashes")
    return data
