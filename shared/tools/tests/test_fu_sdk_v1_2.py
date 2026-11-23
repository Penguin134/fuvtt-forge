"""Comprehensive static hygiene & headless Godot test suite for FuSdk v1.2.0.

Covers:
1. `TestFuSdkStaticHygiene`: UTF-8 no BOM, LF-only, `extends RefCounted`, zero
   `preload(`, zero `class_name`, zero sibling `.gd` `load(` in `modules/`, and
   zero hardcoded machine-local paths across all `shared/sdk/fu_sdk/**/*.gd`.
2. `TestFuSdkV12HeadlessGodot`: Real headless Godot (`--headless --quit` +
   `CREATE_NO_WINDOW`) execution with isolated `APPDATA`/`LOCALAPPDATA`/`TEMP`/
   `TMP` and strict zero Godot `ERROR:` / `SCRIPT ERROR` / leak assertions,
   exercising:
   - `v1.gd` (`SDK_VERSION == "1.2.0"`, module factories, `coerce_*`,
     `ImportSession` options & `proxy: null` safety & `ok_inspect` metadata,
     `WorldBuilder` `rename_floor`, 2-pt segment extrusion including `1e7` ULP
     safety, `add_point_light` + fallback suppression, `configure_grid_alignment`,
     `sanitize_module_data` & `can_fit_module_state`, O(1) entity attach).
   - `modules/snappy.gd` (roundtrip literals + overlapping RLE copy-1/2/4,
     `get_uncompressed_length`, corrupt stream rejection).
   - `modules/package_source.gd` (dir + depth-0/1 `.zip`, macOS junk filter,
     `open_world`, `percent_decode`, `normalize_rel_path`, corrupt ZIP/JSON).
   - `modules/asset_publisher.gd` (PNG/JPEG/WebP-VP8/WebP-VP8L/BMP->PNG/SVG->PNG,
     `.gif`/corrupt/XML-bomb rejection with zero Godot `ERROR:` logs, 4-gate
     `SharedAssetStore.Publish` + rollback + `MockHostBridge` fallback).
   - `modules/entity_library_writer.gd` (4-gate checks, nested folders, `preset`
     & `unit` registration, `AdoptLibraryAsset`, `.revision` chaining,
     idempotency, `rollback_last_registration`, mid-flight cancel rollback).
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import unittest
import uuid
import zipfile
import zlib

_TESTS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _TESTS_DIR.parent
_WORKSPACE_ROOT = _TOOLS_DIR.parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from fuvtt_devtools.env_config import load_config  # noqa: E402
from fuvtt_devtools.host_verifier import analyze_godot_logs  # noqa: E402

SDK_DIR = _WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk"
TEST_TMP_ROOT = _WORKSPACE_ROOT / ".cache" / "test_tmp"

EXPECTED_SDK_FILES = (
    "v1.gd",
    "adapters/host_v1_adapter.gd",
    "modules/asset_publisher.gd",
    "modules/entity_library_writer.gd",
    "modules/package_source.gd",
    "modules/snappy.gd",
)

HARDCODED_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[/\\](?:Users|Program Files|Steam|DND|Projects|Work|home)[/\\]|/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/)"
)


def _encode_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _snappy_literal(data: bytes) -> bytes:
    n = len(data)
    assert n >= 1
    n_minus_1 = n - 1
    if n_minus_1 < 60:
        return bytes([n_minus_1 << 2]) + data
    extra = bytearray()
    val = n_minus_1
    while val > 0:
        extra.append(val & 0xFF)
        val >>= 8
    tag = (59 + len(extra)) << 2
    return bytes([tag]) + bytes(extra) + data


def _snappy_copy1(length: int, offset: int) -> bytes:
    assert 4 <= length <= 11
    assert 1 <= offset <= 2047
    tag = 1 | ((length - 4) << 2) | (((offset >> 8) & 0x07) << 5)
    return bytes([tag, offset & 0xFF])


def _snappy_copy2(length: int, offset: int) -> bytes:
    assert 1 <= length <= 64
    assert 1 <= offset <= 65535
    tag = 2 | ((length - 1) << 2)
    return bytes([tag]) + struct.pack("<H", offset)


def _snappy_copy4(length: int, offset: int) -> bytes:
    assert 1 <= length <= 64
    assert offset >= 1
    tag = 3 | ((length - 1) << 2)
    return bytes([tag]) + struct.pack("<I", offset)


def _make_png_bytes(width: int = 4, height: int = 4) -> bytes:
    def chunk(ctype: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)

    raw_rows = b"".join(b"\x00" + (b"\x20\x60\xa0\xff" * width) for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw_rows)) + chunk(b"IEND", b"")


def _make_bmp_bytes(width: int = 4, height: int = 4, bpp: int = 24, top_down: bool = False) -> bytes:
    row_stride = ((width * bpp + 31) // 32) * 4
    pixel_size = row_stride * height
    file_size = 54 + pixel_size
    bi_height = -height if top_down else height
    file_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 54)
    info_header = struct.pack("<IiiHHIIiiII", 40, width, bi_height, 1, bpp, 0, pixel_size, 2835, 2835, 0, 0)
    px = b"\x40\x80\xc0\xff" if bpp == 32 else b"\x40\x80\xc0"
    row = (px * width).ljust(row_stride, b"\x00")
    return file_header + info_header + (row * height)


def _make_animated_webp_bytes() -> bytes:
    vp8l_payload = bytes.fromhex("2f0000000007100000000100")
    vp8l_chunk = b"VP8L" + struct.pack("<I", len(vp8l_payload)) + vp8l_payload
    if len(vp8l_payload) % 2 == 1:
        vp8l_chunk += b"\x00"
    vp8x_payload = struct.pack("<B3s3s3s", 0x12, b"\x00\x00\x00", b"\x00\x00\x00", b"\x00\x00\x00")
    vp8x_chunk = b"VP8X" + struct.pack("<I", len(vp8x_payload)) + vp8x_payload
    anim_chunk = b"ANIM" + struct.pack("<I", 6) + b"\x00" * 6
    anmf_payload = (b"\x00" * 12 + struct.pack("<I", 100)) + vp8l_chunk
    anmf_chunk = b"ANMF" + struct.pack("<I", len(anmf_payload)) + anmf_payload
    body = b"WEBP" + vp8x_chunk + anim_chunk + anmf_chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _make_bad_ct_png_bytes() -> bytes:
    def chunk(ctype: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", 4, 4, 8, 99, 0, 0, 0)
    idat = zlib.compress(b"\x00" + b"\x00" * 12)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _write_test_packages(run_dir: Path, png_bytes: bytes) -> dict[str, str]:
    # 1. Unpacked generic package directory with BOM manifest
    pkg_dir = run_dir / "pkg_dir"
    (pkg_dir / "Assets" / "Maps").mkdir(parents=True, exist_ok=True)
    (pkg_dir / ".DS_Store").write_bytes(b"junk")
    (pkg_dir / "._pack.json").write_bytes(b"junk")
    manifest_dir_path = pkg_dir / "pack.json"
    manifest_dir_path.write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"id": "demo_pack", "title": "Demo Pack", "version": 1}).encode("utf-8")
    )
    (pkg_dir / "Assets" / "Maps" / "Tavern Floor.png").write_bytes(png_bytes)
    (pkg_dir / "notes.txt").write_bytes(b"\xef\xbb\xbfHello FuSDK!\n")
    (pkg_dir / "other.json").write_bytes(b'{"id": "wrong"}')

    # 2. Depth-1 ZIP archive with macOS junk & deflated/stored entries
    zip_d1 = run_dir / "pkg_depth1.zip"
    with zipfile.ZipFile(zip_d1, "w") as zf:
        zf.writestr("__MACOSX/._my_pack", b"junk")
        zf.writestr("__MACOSX/my_pack/._pack.json", b"junk")
        zf.writestr("my_pack/.DS_Store", b"junk")
        zf.writestr(
            "my_pack/pack.json",
            json.dumps({"id": "zip_pack", "title": "Zip Pack"}).encode("utf-8"),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        zf.writestr(
            "my_pack/Images/Token Hero.png",
            png_bytes,
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr(
            "my_pack/data/info.txt",
            ("Line1\nLine2 " * 40).encode("utf-8"),
            compress_type=zipfile.ZIP_DEFLATED,
        )

    # 3. Depth-0 FVTT world ZIP (valid + invalid non-FVTT world.json)
    zip_world_ok = run_dir / "fvtt_world_ok.zip"
    with zipfile.ZipFile(zip_world_ok, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "world.json",
            json.dumps({"id": "w1", "title": "My World", "system": "dnd5e", "coreVersion": "12.331"}).encode("utf-8"),
        )
        zf.writestr("map.png", png_bytes)

    zip_world_bad = run_dir / "fvtt_world_bad.zip"
    with zipfile.ZipFile(zip_world_bad, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("world.json", json.dumps({"id": "w_bad", "unrelated": 123}).encode("utf-8"))

    # 4. Corrupt ZIPs (truncated + bad CRC32)
    zip_trunc = run_dir / "corrupt_trunc.zip"
    zip_trunc.write_bytes(b"PK\x03\x04truncated_payload")

    zip_bad_crc = run_dir / "corrupt_crc.zip"
    raw_ok = bytearray(zip_world_ok.read_bytes())
    # Corrupt payload byte inside map.png (stored/deflated data right after second LFH)
    # Build a clean stored ZIP and flip 1 byte in its data so CRC32 definitely fails!
    with zipfile.ZipFile(zip_bad_crc, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("world.json", b'{"id":"crc","title":"CRC"}')
        zf.writestr("bad.txt", b"ABCDEFGHIJKLMNOP")
    bc = bytearray(zip_bad_crc.read_bytes())
    idx = bc.find(b"ABCDEFGHIJKLMNOP")
    assert idx > 0
    bc[idx] ^= 0xFF
    zip_bad_crc.write_bytes(bytes(bc))

    return {
        "pkg_dir_manifest": str(manifest_dir_path),
        "pkg_dir_wrong_json": str(pkg_dir / "other.json"),
        "zip_d1": str(zip_d1),
        "zip_world_ok": str(zip_world_ok),
        "zip_world_bad": str(zip_world_bad),
        "zip_trunc": str(zip_trunc),
        "zip_bad_crc": str(zip_bad_crc),
    }


_PROBE_GD = r'''extends SceneTree

const _SDK_PATH: String = "res://shared/sdk/fu_sdk/v1.gd"


class _MockHost extends RefCounted:
	var root: Variant = null
	var destination: String = ""
	var warnings: Array = []
	var reports: Array = []
	var archived_requests: Array = []
	var is_cancelled_flag: bool = false
	var cancel_after_writes: int = -1
	var _store_ref: RefCounted = null

	func cancelled() -> bool:
		if is_cancelled_flag:
			return true
		if cancel_after_writes >= 0 and _store_ref != null and _store_ref.write_count >= cancel_after_writes:
			return true
		return false

	func report(message: String) -> void:
		reports.append(message)

	func warn(message: String) -> void:
		warnings.append(message)

	func empty_world() -> Dictionary:
		var floor_uid := "11111111111111111111111111111111"
		var map_uid := "22222222222222222222222222222222"
		var entity_uid := "33333333333333333333333333333333"
		var obstacle_uid := "44444444444444444444444444444444"
		return {
			"ok": true,
			"data": {
				"format": "fus.practice.world",
				"version": 3,
				"catalog": {
					"active_floor_uid": floor_uid,
					"floors": [
						{"id": 0, "floor_uid": floor_uid, "name": "1F", "color": Color(0.28, 0.65, 0.40)}
					],
					"layers": {
						"schema": "fus.floor_layers.v2",
						"floors": [{
							"floor_uid": floor_uid,
							"default_layer_uid": entity_uid,
							"layers": [
								{"layer_uid": map_uid, "name": "地图底图", "kind": "map", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
								{"layer_uid": entity_uid, "name": "实体", "kind": "entity", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
								{"layer_uid": obstacle_uid, "name": "障碍物", "kind": "obstacle", "visible": true, "locked": false, "persistent": true, "access": "host", "viewers": []},
							],
						}],
					},
				},
				"entity_state": {"version": 3, "entities": []},
				"members": [],
				"modules": {"version": 2, "entries": {}},
			},
		}

	func archive_image(url: String, proxy: String = "") -> Dictionary:
		archived_requests.append({"url": url, "proxy": proxy})
		return {
			"ok": true,
			"reference": "asset://%s.png" % url.sha256_text(),
			"size": Vector2(128, 128),
			"bytes": 512,
		}

	func begin_preview(_total: int, _bounds: Rect2) -> void:
		pass

	func preview_entity(_entity: Dictionary, _kind: String) -> void:
		pass

	func finish_geometry_preview() -> bool:
		return true


class _MockSharedAssetStore extends RefCounted:
	var records: Dictionary = {}
	var rev: int = 1
	var write_count: int = 0
	var adopted: Array = []
	var shared: Array = []
	var published_paths: Array = []

	func Publish(dest: String, reference: String, bytes: PackedByteArray) -> String:
		var body := reference.substr(8)
		var assets_dir := dest.path_join("assets")
		DirAccess.make_dir_recursive_absolute(assets_dir)
		var fpath := assets_dir.path_join(body)
		var existed := FileAccess.file_exists(fpath)
		var f := FileAccess.open(fpath, FileAccess.WRITE)
		if f == null:
			return JSON.stringify({"ok": false, "reason": "write_failed"})
		f.store_buffer(bytes)
		f.close()
		published_paths.append(fpath)
		return JSON.stringify({"ok": true, "reused": existed, "new_bytes": 0 if existed else bytes.size()})

	func OpenLibrary(root: String) -> String:
		DirAccess.make_dir_recursive_absolute(root.path_join("entity-library/assets"))
		DirAccess.make_dir_recursive_absolute(root.path_join("entity-library/records"))
		return JSON.stringify({"ok": true})

	func ReadLibraryRecords(_root: String) -> Dictionary:
		return {"ok": true, "records": records.duplicate(), "revision": "rev_%d" % rev}

	func WriteLibraryRecord(_root: String, id: String, expected: PackedByteArray, desired: PackedByteArray, expected_rev: String) -> String:
		if expected_rev != ("rev_%d" % rev):
			return JSON.stringify({"ok": false, "reason": "revision_mismatch"})
		var cur: PackedByteArray = records.get(id, PackedByteArray())
		if cur != expected:
			return JSON.stringify({"ok": false, "reason": "expected_mismatch"})
		if desired.is_empty():
			records.erase(id)
		else:
			records[id] = desired
		rev += 1
		write_count += 1
		return JSON.stringify({"ok": true, "changed": true, "revision": "rev_%d" % rev})

	func AdoptLibraryAsset(_root: String, _campaign: String, reference: String) -> String:
		adopted.append(reference)
		return JSON.stringify({"ok": true})

	func ShareLibraryAsset(_root: String, reference: String) -> String:
		shared.append(reference)
		return JSON.stringify({"ok": true})


func _read_json(path: String) -> Dictionary:
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return {}
	var text := f.get_as_text()
	f.close()
	var j := JSON.new()
	if j.parse(text) == OK and j.data is Dictionary:
		return j.data as Dictionary
	return {}


func _write_json(path: String, payload: Dictionary) -> void:
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(payload))
		f.close()


func _polygon_area(ring: PackedVector2Array) -> float:
	var n: int = ring.size()
	if n < 3:
		return 0.0
	var s: float = 0.0
	for i: int in range(n):
		var a: Vector2 = ring[i]
		var b: Vector2 = ring[(i + 1) % n]
		s += a.x * b.y - b.x * a.y
	return absf(s) * 0.5


func _initialize() -> void:
	var cfg_path := ""
	var out_path := ""
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with("--cfg="):
			cfg_path = arg.substr(6)
		elif arg.begins_with("--out="):
			out_path = arg.substr(6)
	if cfg_path.is_empty() or out_path.is_empty():
		quit(2)
		return

	var cfg: Dictionary = _read_json(cfg_path)
	var run_dir: String = str(cfg.get("run_dir", ""))
	var results: Dictionary = {}

	var sdk_script := load(_SDK_PATH) as Script
	if sdk_script == null:
		_write_json(out_path, {"ok": false, "reason": "failed_to_load_v1_gd"})
		quit(1)
		return
	var sdk: RefCounted = sdk_script.new()

	# =========================================================================
	# 1. Core FuSdk v1.2.0 facade & HostV1Adapter
	# =========================================================================
	var pub_inst: RefCounted = sdk.create_asset_publisher()
	var lib_inst: RefCounted = sdk.create_entity_library_writer()
	var pkg_inst: RefCounted = sdk.create_package_source()
	var snappy_inst: RefCounted = sdk.create_snappy_codec()

	var h_core := _MockHost.new()
	var s_core = sdk.create_session(h_core, {
		"proxy": null,
		"include_hidden": "false",
		"max_items": "42",
		"scale_factor": "1.5",
		"bad_bool": NAN,
		"bad_int": "99999999999999999999999",
		"bad_float": INF,
	})
	var sanitized_opts: Dictionary = s_core.sanitize_options({
		"proxy": "",
		"include_hidden": true,
		"max_items": 10,
		"scale_factor": 2.0,
		"missing_flag": true,
	})
	var archived_ref: String = s_core.archive_remote_image("https://example.com/hero.png")
	var inspect_ok: Dictionary = s_core.ok_inspect(
		str(cfg["pkg_dir_manifest"]),
		{"maps": 2, "images": 5},
		{"https://example.com/a.png": 100},
		2048,
		"My Custom Campaign"
	)
	var inspect_legacy: Dictionary = s_core.ok_inspect(str(cfg["pkg_dir_manifest"]))

	var digest64 := "a".repeat(64)
	var sp_bmp: String = s_core.validate_sprite_path("asset://%s.bmp" % digest64)
	var sp_svg_asset: String = s_core.validate_sprite_path("asset://%s.svg" % digest64)
	var sp_svg_res: String = s_core.validate_sprite_path("res://assets/icon.svg")

	var b_core = sdk.create_world_builder(s_core, 100.0)
	var default_fuid: String = b_core.get_active_floor_uid()
	var renamed_ok: bool = b_core.rename_floor(default_fuid, "Ground Floor")
	var renamed_bad: bool = b_core.rename_floor("0".repeat(32), "Nope")

	var quad_ok: PackedVector2Array = b_core.extrude_segment_to_quad(Vector2(0, 0), Vector2(100, 0), 6.0)
	var quad_tiny: PackedVector2Array = b_core.extrude_segment_to_quad(Vector2(0, 0), Vector2(0.1, 0), 6.0)
	var wall_id: String = b_core.add_segment_wall("w1", "Wall 1", Vector2(0, 0), Vector2(200, 0), 6.0)
	var wall_huge_id: String = b_core.add_segment_wall("w_huge", "Huge Coord Wall", Vector2(1e7, 1e7), Vector2(1e7 + 200.0, 1e7), 6.0)
	var door_id: String = b_core.add_segment_door("d1", "Door 1", Vector2(0, 100), Vector2(100, 100), 6.0, true)
	var win_id: String = b_core.add_segment_window("win1", "Window 1", Vector2(0, 200), Vector2(100, 200), 6.0)
	var glass_id: String = b_core.add_segment_glass_wall("g1", "Glass 1", Vector2(0, 300), Vector2(100, 300), 6.0)
	var light_id: String = b_core.add_point_light("lt1", Vector2(50, 50), 320.0, 180.0, "Torch", false, true)
	var grid_ok: bool = b_core.configure_grid_alignment(64.0, true, Vector2(8.0, 12.0), Color(0.5, 0.55, 0.65, 0.7), 1.5, 0.2)

	var dirty_mod: Variant = b_core.sanitize_module_data({"ok_num": 1, "nan_val": NAN, "inf_val": INF, "nested": [NAN, "hi"]})
	var fit_small: bool = b_core.can_fit_module_state("demo_mod", 1, {"summary": "small"})
	var fit_huge: bool = b_core.can_fit_module_state("huge_mod", 1, {"blob": "X".repeat(5 * 1024 * 1024)})
	b_core.set_module_state("demo_mod", 1, dirty_mod as Dictionary)

	var core_world: Dictionary = b_core.get_world()
	var wall_huge_ring_area: float = 0.0
	var wall_huge_ring_pts: int = 0
	var light_fallback_alpha: float = -1.0
	var light_comp0_show_fb: Variant = null
	var light_has_simple_light: bool = false
	for ent_v: Variant in core_world["entity_state"]["entities"]:
		var ed: Dictionary = ent_v as Dictionary
		if str(ed.get("id", "")) == wall_huge_id:
			var paths: Array = ed["components"][0]["state"]["vector_drawing"]["paths"]
			if not paths.is_empty():
				var r0: PackedVector2Array = paths[0]
				wall_huge_ring_pts = r0.size()
				wall_huge_ring_area = _polygon_area(r0)
		elif str(ed.get("id", "")) == light_id:
			light_fallback_alpha = (ed.get("fallback_color", Color.WHITE) as Color).a
			light_comp0_show_fb = ed["components"][0]["state"].get("show_fallback", true)
			for comp_v: Variant in ed["components"]:
				if str((comp_v as Dictionary).get("script", "")).ends_with("comp_simple_light.gd"):
					light_has_simple_light = true

	var grid_entry: Dictionary = core_world["modules"]["entries"].get("grid_alignment", {})
	var grid_state: Dictionary = grid_entry.get("state", {})

	results["sdk_core"] = {
		"sdk_version": str(sdk_script.SDK_VERSION),
		"factories_ok": pub_inst != null and lib_inst != null and pkg_inst != null and snappy_inst != null,
		"coerce_bool_true": sdk.coerce_bool("yes", false),
		"coerce_bool_false": sdk.coerce_bool("off", true),
		"coerce_bool_nan": sdk.coerce_bool(NAN, true),
		"coerce_string_null": sdk.coerce_string(null, "fb"),
		"coerce_string_ok": sdk.coerce_string("hello", "fb"),
		"coerce_int_ok": sdk.coerce_int("-42", 0),
		"coerce_int_overflow": sdk.coerce_int("999999999999999999999", 7),
		"coerce_float_ok": sdk.coerce_float("3.25", 0.0),
		"coerce_float_nan": sdk.coerce_float(NAN, 1.5),
		"opt_proxy": s_core.get_string_option("proxy", "fallback"),
		"opt_hidden": s_core.get_bool_option("include_hidden", true),
		"opt_max_items": s_core.get_int_option("max_items", 0),
		"opt_scale": s_core.get_float_option("scale_factor", 0.0),
		"opt_bad_bool": s_core.get_bool_option("bad_bool", true),
		"opt_bad_int": s_core.get_int_option("bad_int", 99),
		"opt_bad_float": s_core.get_float_option("bad_float", 4.5),
		"sanitized_opts": sanitized_opts,
		"archived_ref_ok": archived_ref.begins_with("asset://"),
		"archived_proxy": str(h_core.archived_requests[0]["proxy"]) if not h_core.archived_requests.is_empty() else "NONE",
		"inspect_ok": {
			"ok": inspect_ok.get("ok", false),
			"name": inspect_ok.get("name", ""),
			"source_bytes": inspect_ok.get("source_bytes", -1),
			"decoded_bytes": inspect_ok.get("decoded_bytes", -1),
			"unique_images": inspect_ok.get("unique_images", -1),
		},
		"inspect_legacy_ok": bool(inspect_legacy.get("ok", false)) and int(inspect_legacy.get("source_bytes", 0)) > 0,
		"sp_bmp_ok": not sp_bmp.is_empty(),
		"sp_svg_asset_rejected": sp_svg_asset.is_empty(),
		"sp_svg_res_ok": not sp_svg_res.is_empty(),
		"renamed_ok": renamed_ok,
		"renamed_bad": renamed_bad,
		"floor0_name": str(core_world["catalog"]["floors"][0]["name"]),
		"quad_ok_size": quad_ok.size(),
		"quad_tiny_size": quad_tiny.size(),
		"seg_ids_ok": not wall_id.is_empty() and not wall_huge_id.is_empty() and not door_id.is_empty() and not win_id.is_empty() and not glass_id.is_empty(),
		"wall_huge_ring_pts": wall_huge_ring_pts,
		"wall_huge_ring_area": wall_huge_ring_area,
		"light_id_ok": not light_id.is_empty(),
		"light_fallback_alpha": light_fallback_alpha,
		"light_comp0_show_fb": light_comp0_show_fb,
		"light_has_simple_light": light_has_simple_light,
		"grid_ok": grid_ok,
		"grid_key_count": grid_state.size(),
		"grid_keys": grid_state.keys(),
		"dirty_mod_nan": (dirty_mod as Dictionary).get("nan_val", -1.0),
		"dirty_mod_inf": (dirty_mod as Dictionary).get("inf_val", -1.0),
		"fit_small": fit_small,
		"fit_huge": fit_huge,
	}

	# =========================================================================
	# 2. modules/snappy.gd
	# =========================================================================
	var sn_empty: Dictionary = snappy_inst.decompress(Marshalls.base64_to_raw(str(cfg["snappy_zero_b64"])))
	var sn_lit: Dictionary = snappy_inst.decompress(Marshalls.base64_to_raw(str(cfg["snappy_lit_b64"])))
	var sn_rle_bytes: PackedByteArray = Marshalls.base64_to_raw(str(cfg["snappy_rle_b64"]))
	var sn_rle_len: Dictionary = snappy_inst.get_uncompressed_length(sn_rle_bytes)
	var sn_rle: Dictionary = snappy_inst.decompress(sn_rle_bytes)
	var sn_copy2: Dictionary = snappy_inst.decompress(Marshalls.base64_to_raw(str(cfg["snappy_copy2_b64"])))
	var sn_copy4: Dictionary = snappy_inst.decompress(Marshalls.base64_to_raw(str(cfg["snappy_copy4_b64"])))
	var sn_bad_empty: Dictionary = snappy_inst.decompress(PackedByteArray())
	var sn_bad_varint: Dictionary = snappy_inst.decompress(PackedByteArray([0x80, 0x80, 0x80, 0x80, 0x80]))
	var sn_bad_offset: Dictionary = snappy_inst.decompress(Marshalls.base64_to_raw(str(cfg["snappy_bad_offset_b64"])))
	var sn_over_limit: Dictionary = snappy_inst.decompress(sn_rle_bytes, 4)

	results["snappy"] = {
		"zero_ok": bool(sn_empty.get("ok", false)) and (sn_empty["data"] as PackedByteArray).is_empty(),
		"lit_text": (sn_lit["data"] as PackedByteArray).get_string_from_utf8() if bool(sn_lit.get("ok", false)) else "",
		"rle_len": sn_rle_len,
		"rle_text": (sn_rle["data"] as PackedByteArray).get_string_from_utf8() if bool(sn_rle.get("ok", false)) else "",
		"copy2_text": (sn_copy2["data"] as PackedByteArray).get_string_from_utf8() if bool(sn_copy2.get("ok", false)) else "",
		"copy4_text": (sn_copy4["data"] as PackedByteArray).get_string_from_utf8() if bool(sn_copy4.get("ok", false)) else "",
		"bad_empty_ok": bool(sn_bad_empty.get("ok", true)),
		"bad_varint_ok": bool(sn_bad_varint.get("ok", true)),
		"bad_offset_ok": bool(sn_bad_offset.get("ok", true)),
		"over_limit_ok": bool(sn_over_limit.get("ok", true)),
	}

	# =========================================================================
	# 3. modules/package_source.gd
	# =========================================================================
	var dir_open: Dictionary = pkg_inst.open_package(str(cfg["pkg_dir_manifest"]), "pack.json", ["id", "title"])
	var dir_kind: String = pkg_inst.get_source_kind()
	var dir_prefix: String = pkg_inst.get_root_prefix()
	var dir_manifest: Dictionary = pkg_inst.get_manifest()
	var dir_has_ci: bool = pkg_inst.has_file("assets/maps/tavern floor.png")
	var dir_has_junk: bool = pkg_inst.has_file(".DS_Store") or pkg_inst.has_file("._pack.json")
	var dir_txt: Dictionary = pkg_inst.read_text("notes.txt")
	var dir_files: Array[String] = pkg_inst.list_files("Assets")
	var dir_decoded: int = pkg_inst.get_decoded_bytes_total()
	var norm_strip: Dictionary = pkg_inst.normalize_rel_path("worlds/demo_pack/assets/maps/Tavern%20Floor.png?v=1", ["worlds/demo_pack"])
	var norm_remote: Dictionary = pkg_inst.normalize_rel_path("https://cdn.example.com/a.webp?x=1")
	var norm_unsafe1: Dictionary = pkg_inst.normalize_rel_path("../secret.png")
	var norm_unsafe2: Dictionary = pkg_inst.normalize_rel_path("file:///etc/passwd")
	var pdec_ok: String = pkg_inst.percent_decode("Side%20View%20%E4%B8%AD%E6%96%87.png")
	var pdec_nul: String = pkg_inst.percent_decode("bad%00name.png")
	pkg_inst.close()

	var wrong_fn: Dictionary = pkg_inst.open_package(str(cfg["pkg_dir_wrong_json"]), "pack.json", ["id"])
	var missing_key: Dictionary = pkg_inst.open_package(str(cfg["pkg_dir_manifest"]), "pack.json", ["id", "nonexistent_key"])

	var zip_open: Dictionary = pkg_inst.open_package(str(cfg["zip_d1"]), "pack.json", ["id", "title"])
	var zip_kind: String = pkg_inst.get_source_kind()
	var zip_prefix: String = pkg_inst.get_root_prefix()
	var zip_files: Array[String] = pkg_inst.list_files("")
	var zip_txt: Dictionary = pkg_inst.read_text("data/info.txt")
	var zip_has_junk: bool = pkg_inst.has_file(".DS_Store") or pkg_inst.has_file("__MACOSX/._my_pack")
	var zip_decoded: int = pkg_inst.get_decoded_bytes_total()
	pkg_inst.close()

	var world_ok_res: Dictionary = pkg_inst.open_world(str(cfg["zip_world_ok"]))
	pkg_inst.close()
	var world_bad_res: Dictionary = pkg_inst.open_world(str(cfg["zip_world_bad"]))
	pkg_inst.close()
	var trunc_res: Dictionary = pkg_inst.open_package(str(cfg["zip_trunc"]), "world.json")
	var bad_crc_open: Dictionary = pkg_inst.open_package(str(cfg["zip_bad_crc"]), "world.json")
	var bad_crc_read: Dictionary = pkg_inst.read_bytes("bad.txt")
	pkg_inst.close()

	results["package_source"] = {
		"dir_ok": bool(dir_open.get("ok", false)),
		"dir_kind": dir_kind,
		"dir_prefix": dir_prefix,
		"dir_manifest_id": str(dir_manifest.get("id", "")),
		"dir_has_ci": dir_has_ci,
		"dir_has_junk": dir_has_junk,
		"dir_txt": dir_txt,
		"dir_files": dir_files,
		"dir_decoded": dir_decoded,
		"norm_strip": norm_strip,
		"norm_remote": norm_remote,
		"norm_unsafe1": norm_unsafe1,
		"norm_unsafe2": norm_unsafe2,
		"pdec_ok": pdec_ok,
		"pdec_nul": pdec_nul,
		"wrong_fn_ok": bool(wrong_fn.get("ok", true)),
		"missing_key_ok": bool(missing_key.get("ok", true)),
		"zip_ok": bool(zip_open.get("ok", false)),
		"zip_kind": zip_kind,
		"zip_prefix": zip_prefix,
		"zip_files": zip_files,
		"zip_txt_ok": bool(zip_txt.get("ok", false)) and str(zip_txt.get("text", "")).begins_with("Line1\nLine2 "),
		"zip_has_junk": zip_has_junk,
		"zip_decoded": zip_decoded,
		"world_ok": bool(world_ok_res.get("ok", false)),
		"world_bad_ok": bool(world_bad_res.get("ok", true)),
		"trunc_ok": bool(trunc_res.get("ok", true)),
		"bad_crc_open_ok": bool(bad_crc_open.get("ok", false)),
		"bad_crc_read_ok": bool(bad_crc_read.get("ok", true)),
		"bad_crc_reason": str(bad_crc_read.get("reason", "")),
	}

	# =========================================================================
	# 4. modules/asset_publisher.gd
	# =========================================================================
	var gen_img := Image.create(8, 6, false, Image.FORMAT_RGBA8)
	gen_img.fill(Color(0.2, 0.5, 0.8, 1.0))
	var valid_jpg: PackedByteArray = gen_img.save_jpg_to_buffer(0.9)
	var valid_webp_lossy: PackedByteArray = gen_img.save_webp_to_buffer(false)
	var valid_webp_lossless: PackedByteArray = gen_img.save_webp_to_buffer(true)
	var valid_png: PackedByteArray = Marshalls.base64_to_raw(str(cfg["png_b64"]))
	var valid_bmp24: PackedByteArray = Marshalls.base64_to_raw(str(cfg["bmp24_b64"]))
	var valid_bmp32_td: PackedByteArray = Marshalls.base64_to_raw(str(cfg["bmp32_td_b64"]))
	var valid_svg: PackedByteArray = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="12"><rect width="16" height="12" fill="#336699"/></svg>'.to_utf8_buffer()
	var valid_svg_ns: PackedByteArray = '<s:svg xmlns:s="http://www.w3.org/2000/svg" width="16" height="16"><s:rect width="16" height="16" fill="#336699"/></s:svg>'.to_utf8_buffer()

	var prep_png: Dictionary = pub_inst.validate_and_prepare_image_bytes(valid_png, "png")
	var prep_jpg: Dictionary = pub_inst.validate_and_prepare_image_bytes(valid_jpg, "jpeg")
	var prep_webp_vp8: Dictionary = pub_inst.validate_and_prepare_image_bytes(valid_webp_lossy, "webp")
	var prep_webp_vp8l: Dictionary = pub_inst.validate_and_prepare_image_bytes(valid_webp_lossless, "webp")
	var prep_bmp24: Dictionary = pub_inst.validate_and_prepare_image_bytes(valid_bmp24, "bmp")
	var prep_bmp32_td: Dictionary = pub_inst.validate_and_prepare_image_bytes(valid_bmp32_td, "bmp")
	var prep_svg: Dictionary = pub_inst.validate_and_prepare_image_bytes(valid_svg, "svg")
	var prep_svg_ns: Dictionary = pub_inst.validate_and_prepare_image_bytes(valid_svg_ns, "svg")

	# Rejections (must produce ZERO Godot C++ ERROR logs!)
	var gif_bytes: PackedByteArray = PackedByteArray([0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 1, 0, 1, 0, 0, 0, 0, 0x3B])
	var bad_ct_png: PackedByteArray = Marshalls.base64_to_raw(str(cfg["bad_ct_png_b64"]))
	var anim_webp: PackedByteArray = Marshalls.base64_to_raw(str(cfg["anim_webp_b64"]))
	var svg_dtd: PackedByteArray = '<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>'.to_utf8_buffer()
	var svg_cycle: PackedByteArray = '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><g id="a"><use href="#b"/></g><g id="b"><use href="#a"/></g></svg>'.to_utf8_buffer()
	var rej_gif: Dictionary = pub_inst.validate_and_prepare_image_bytes(gif_bytes, "gif")
	var rej_bad_png: Dictionary = pub_inst.validate_and_prepare_image_bytes(bad_ct_png, "png")
	var rej_trunc_png: Dictionary = pub_inst.validate_and_prepare_image_bytes(valid_png.slice(0, 20), "png")
	var rej_anim_webp: Dictionary = pub_inst.validate_and_prepare_image_bytes(anim_webp, "webp")
	var rej_svg_dtd: Dictionary = pub_inst.validate_and_prepare_image_bytes(svg_dtd, "svg")
	var rej_svg_cycle: Dictionary = pub_inst.validate_and_prepare_image_bytes(svg_cycle, "svg")
	var rej_rand: Dictionary = pub_inst.validate_and_prepare_image_bytes(PackedByteArray([1, 2, 3, 4, 5, 6, 7, 8]), "png")

	# MockHostBridge fallback (no root/destination)
	var h_mock_only := _MockHost.new()
	var s_mock_only = sdk.create_session(h_mock_only, {})
	var pub_fallback: Dictionary = pub_inst.publish_bytes(valid_png, "png", h_mock_only, s_mock_only)
	var fallback_count: int = pub_inst.get_published_count()

	# 4-gate SharedAssetStore.Publish + publish_from_source + rollback
	var pub_store := _MockSharedAssetStore.new()
	var pub_real: RefCounted = sdk.create_asset_publisher()
	pub_real.set_shared_asset_store(pub_store, true)
	var h_pub := _MockHost.new()
	var pub_root: String = run_dir.path_join("pub_root")
	var pub_dest: String = pub_root.path_join("sessions/test_session_0123456789abcdef0123456789abcdef")
	h_pub.root = pub_root
	h_pub.destination = pub_dest
	var s_pub = sdk.create_session(h_pub, {"proxy": null})
	var pub_svg_res: Dictionary = pub_real.publish_bytes(valid_svg, "svg", h_pub, s_pub, "icon.svg")

	pkg_inst.open_package(str(cfg["zip_d1"]), "pack.json")
	var pub_src_res: Dictionary = pub_real.publish_from_source("Images/Token Hero.png", pkg_inst, h_pub, s_pub)
	var res_remote: Dictionary = pub_real.resolve_sprite_ref(
		"https://example.com/map.png",
		{"kind": "remote", "url": "https://example.com/map.png"},
		pkg_inst,
		h_pub,
		s_pub,
		{"proxy": null, "download_remote_assets": true}
	)
	var res_gif_skip: Dictionary = pub_real.resolve_sprite_ref(
		"anim.gif",
		{"kind": "local", "rel_path": "anim.gif", "ext": "gif", "exists": true},
		pkg_inst,
		h_pub,
		s_pub,
		{"skip_missing_assets": true}
	)
	pkg_inst.close()

	var before_rb_count: int = pub_real.get_published_count()
	var before_rb_files: Array[String] = pub_real.get_published_files()
	var all_existed_before_rb: bool = true
	for pf: String in before_rb_files:
		if not FileAccess.file_exists(pf):
			all_existed_before_rb = false
	var rb_removed: int = pub_real.rollback_published_files()
	var after_rb_count: int = pub_real.get_published_count()
	var any_exists_after_rb: bool = false
	for pf2: String in before_rb_files:
		if FileAccess.file_exists(pf2):
			any_exists_after_rb = true

	results["asset_publisher"] = {
		"prep_png": {"ok": prep_png.get("ok"), "ext": prep_png.get("ext"), "w": prep_png.get("width"), "h": prep_png.get("height"), "conv": prep_png.get("converted")},
		"prep_jpg": {"ok": prep_jpg.get("ok"), "ext": prep_jpg.get("ext"), "w": prep_jpg.get("width"), "h": prep_jpg.get("height"), "conv": prep_jpg.get("converted")},
		"prep_webp_vp8": {"ok": prep_webp_vp8.get("ok"), "ext": prep_webp_vp8.get("ext"), "w": prep_webp_vp8.get("width"), "h": prep_webp_vp8.get("height"), "conv": prep_webp_vp8.get("converted")},
		"prep_webp_vp8l": {"ok": prep_webp_vp8l.get("ok"), "ext": prep_webp_vp8l.get("ext"), "w": prep_webp_vp8l.get("width"), "h": prep_webp_vp8l.get("height"), "conv": prep_webp_vp8l.get("converted")},
		"prep_bmp24": {"ok": prep_bmp24.get("ok"), "ext": prep_bmp24.get("ext"), "conv": prep_bmp24.get("converted"), "magic": (prep_bmp24["bytes"] as PackedByteArray).slice(0, 8).hex_encode()},
		"prep_bmp32_td": {"ok": prep_bmp32_td.get("ok"), "ext": prep_bmp32_td.get("ext"), "conv": prep_bmp32_td.get("converted")},
		"prep_svg": {"ok": prep_svg.get("ok"), "ext": prep_svg.get("ext"), "w": prep_svg.get("width"), "h": prep_svg.get("height"), "conv": prep_svg.get("converted"), "magic": (prep_svg["bytes"] as PackedByteArray).slice(0, 8).hex_encode()},
		"prep_svg_ns": {"ok": prep_svg_ns.get("ok"), "ext": prep_svg_ns.get("ext"), "conv": prep_svg_ns.get("converted")},
		"rej_gif": {"ok": rej_gif.get("ok"), "unsupported": rej_gif.get("unsupported")},
		"rej_bad_png_ok": rej_bad_png.get("ok"),
		"rej_trunc_png_ok": rej_trunc_png.get("ok"),
		"rej_anim_webp": {"ok": rej_anim_webp.get("ok"), "unsupported": rej_anim_webp.get("unsupported")},
		"rej_svg_dtd_ok": rej_svg_dtd.get("ok"),
		"rej_svg_cycle_ok": rej_svg_cycle.get("ok"),
		"rej_rand_ok": rej_rand.get("ok"),
		"fallback_ok": bool(pub_fallback.get("ok", false)) and str(pub_fallback.get("sprite_path", "")).begins_with("asset://"),
		"fallback_count": fallback_count,
		"pub_svg_ok": bool(pub_svg_res.get("ok", false)) and str(pub_svg_res.get("ext", "")) == "png",
		"pub_src_ok": bool(pub_src_res.get("ok", false)) and str(pub_src_res.get("sprite_path", "")).begins_with("asset://"),
		"res_remote_ok": bool(res_remote.get("ok", false)) and str(res_remote.get("status", "")) == "remote_archived",
		"res_remote_proxy": str(h_pub.archived_requests[0]["proxy"]) if not h_pub.archived_requests.is_empty() else "NONE",
		"res_gif_skip": res_gif_skip,
		"before_rb_count": before_rb_count,
		"all_existed_before_rb": all_existed_before_rb,
		"rb_removed": rb_removed,
		"after_rb_count": after_rb_count,
		"any_exists_after_rb": any_exists_after_rb,
	}

	# =========================================================================
	# 5. modules/entity_library_writer.gd
	# =========================================================================
	var lib_store := _MockSharedAssetStore.new()
	var h_lib_bad := _MockHost.new()
	h_lib_bad.root = run_dir.path_join("wrong_root")
	h_lib_bad.destination = run_dir.path_join("lib_root/sessions/desktop_0123456789abcdef0123456789abcdef")
	var can_no_store: bool = lib_inst.can_write_library(h_lib_bad)
	lib_inst.set_shared_asset_store(lib_store, true)
	var can_bad_root: bool = lib_inst.can_write_library(h_lib_bad)

	var h_lib_ok := _MockHost.new()
	var lib_root: String = run_dir.path_join("lib_root")
	var lib_dest: String = lib_root.path_join("sessions/桌面 2026-11-22 120000_fedcba9876543210fedcba9876543210")
	h_lib_ok.root = lib_root
	h_lib_ok.destination = lib_dest
	var can_ok: bool = lib_inst.can_write_library(h_lib_ok)

	var s_lib = sdk.create_session(h_lib_ok, {})
	var reg_disabled: Dictionary = lib_inst.register_entries("ns1", [{"id": "e1", "name": "Hero"}], h_lib_ok, s_lib, false)

	var asset_ref_valid: String = "asset://%s.png" % ("b".repeat(64))
	var entries_v1: Array = [
		{
			"id": "goblin_1",
			"name": "Goblin Scout",
			"folder_name": "Monsters/Goblins",
			"sprite_ref": asset_ref_valid,
			"footprint_radius": 28.0,
			"size_world": Vector2(64.0, 64.0),
			"scale": Vector2(1.0, 1.0),
			"all_players_can_operate": true,
			"create_preset": true,
			"vision_radius": 320.0,
			"vision_angle": 180.0,
		},
		{
			"id": "hero_unit",
			"name": "Simple Hero",
			"folder_name": "Heroes",
			"sprite_ref": "",
			"create_preset": false,
		},
	]
	var reg_v1: Dictionary = lib_inst.register_entries("ns1", entries_v1, h_lib_ok, s_lib, true)
	var v1_record_count: int = lib_store.records.size()
	var v1_rev: int = lib_store.rev
	var v1_writes: int = lib_store.write_count
	var v1_adopted_count: int = lib_store.adopted.size()
	var v1_shared_count: int = lib_store.shared.size()

	# Decode written rows to verify schemas
	var kinds_found: Dictionary = {}
	var preset_has_vision: bool = false
	var preset_allow_all: bool = false
	for rec_id: Variant in lib_store.records.keys():
		var row_v: Variant = bytes_to_var(lib_store.records[rec_id])
		if row_v is Dictionary:
			var rd: Dictionary = row_v as Dictionary
			var k: String = str(rd.get("kind", ""))
			kinds_found[k] = int(kinds_found.get(k, 0)) + 1
			if k == "preset":
				var snap: Dictionary = rd.get("record", {}).get("snapshot", {})
				var ents: Array = snap.get("entities", [])
				if not ents.is_empty():
					var e0: Dictionary = ents[0] as Dictionary
					for c: Variant in e0.get("components", []):
						var cd: Dictionary = c as Dictionary
						if str(cd.get("script", "")).ends_with("comp_permission.gd"):
							preset_allow_all = bool(cd.get("state", {}).get("all_players_can_operate", false))
						elif str(cd.get("script", "")).ends_with("comp_simple_vision.gd"):
							preset_has_vision = float(cd.get("state", {}).get("radius", 0.0)) == 320.0

	# Idempotent re-run should cause 0 additional writes
	var reg_idem: Dictionary = lib_inst.register_entries("ns1", entries_v1, h_lib_ok, s_lib, true)
	var idem_extra_writes: int = lib_store.write_count - v1_writes

	# Revision chaining update (rename Goblin Scout -> Goblin Boss) + rollback_last_registration
	var entries_v2: Array = entries_v1.duplicate(true)
	(entries_v2[0] as Dictionary)["name"] = "Goblin Boss"
	var reg_v2: Dictionary = lib_inst.register_entries("ns1", entries_v2, h_lib_ok, s_lib, true)
	var v2_rev: int = lib_store.rev
	var preset_id: String = ("fus:lib:preset:ns1:goblin_1").sha256_text().left(32)
	var v2_name: String = str((bytes_to_var(lib_store.records[preset_id]) as Dictionary).get("name", ""))
	lib_inst.rollback_last_registration()
	var after_rb_name: String = str((bytes_to_var(lib_store.records[preset_id]) as Dictionary).get("name", ""))

	# Mid-flight cancellation rollback on fresh store
	var cancel_store := _MockSharedAssetStore.new()
	var lib_cancel: RefCounted = sdk.create_entity_library_writer()
	lib_cancel.set_shared_asset_store(cancel_store, true)
	var h_cancel := _MockHost.new()
	h_cancel.root = lib_root
	h_cancel.destination = lib_dest
	h_cancel._store_ref = cancel_store
	h_cancel.cancel_after_writes = 2
	var s_cancel = sdk.create_session(h_cancel, {})
	var reg_cancel: Dictionary = lib_cancel.register_entries("ns_cancel", entries_v1, h_cancel, s_cancel, true)
	var cancel_leftover_records: int = cancel_store.records.size()

	results["entity_library"] = {
		"can_no_store": can_no_store,
		"can_bad_root": can_bad_root,
		"can_ok": can_ok,
		"reg_disabled": reg_disabled,
		"reg_v1": reg_v1,
		"v1_record_count": v1_record_count,
		"v1_rev": v1_rev,
		"adopted_count": v1_adopted_count,
		"shared_count": v1_shared_count,
		"kinds_found": kinds_found,
		"preset_has_vision": preset_has_vision,
		"preset_allow_all": preset_allow_all,
		"reg_idem_ok": bool(reg_idem.get("ok", false)) and int(reg_idem.get("count", 0)) == 2,
		"idem_extra_writes": idem_extra_writes,
		"reg_v2_ok": bool(reg_v2.get("ok", false)),
		"v2_rev_advanced": v2_rev > v1_rev,
		"v2_name": v2_name,
		"after_rb_name": after_rb_name,
		"reg_cancel": reg_cancel,
		"cancel_leftover_records": cancel_leftover_records,
	}

	_write_json(out_path, {"ok": true, "results": results})
	quit(0)
'''


class TestFuSdkStaticHygiene(unittest.TestCase):
    """Static hygiene checks across every `shared/sdk/fu_sdk/**/*.gd` script."""

    def test_all_fu_sdk_gd_files_exist_and_follow_hygiene(self) -> None:
        for rel in EXPECTED_SDK_FILES:
            fpath = SDK_DIR / rel
            self.assertTrue(fpath.is_file(), f"Missing expected SDK file: {rel}")

        cfg = load_config(_WORKSPACE_ROOT)
        forbidden_locals: list[str] = []
        for candidate in (cfg.fuvtt_install_dir, cfg.fus_repo_dir, cfg.godot_bin):
            if candidate is not None:
                forbidden_locals.append(str(candidate))
                forbidden_locals.append(candidate.as_posix())

        gd_files = sorted(SDK_DIR.rglob("*.gd"))
        self.assertGreaterEqual(len(gd_files), len(EXPECTED_SDK_FILES))

        for fpath in gd_files:
            rel = fpath.relative_to(SDK_DIR).as_posix()
            raw = fpath.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"{rel} must not have UTF-8 BOM")
            self.assertNotIn(b"\r", raw, f"{rel} must use LF-only line endings")
            text = raw.decode("utf-8")
            self.assertTrue(
                text.startswith("extends RefCounted\n"),
                f"{rel} must start with `extends RefCounted`",
            )
            self.assertNotIn("preload(", text, f"{rel} must not call preload()")
            self.assertIsNone(
                re.search(r"(?m)^\s*class_name\b", text),
                f"{rel} must not declare class_name",
            )
            self.assertIsNone(
                HARDCODED_PATH_RE.search(text),
                f"{rel} appears to contain a hardcoded machine-local path",
            )
            for local_str in forbidden_locals:
                if local_str:
                    self.assertNotIn(local_str, text, f"{rel} leaks local environment path")

            if rel.startswith("modules/"):
                for match in re.finditer(r"\bload\s*\(([^)]*)\)", text):
                    arg = match.group(1).strip()
                    self.assertTrue(
                        "SHARED_ASSET_STORE_PATH" in arg or "res://services/" in arg,
                        f"{rel} must not load sibling .gd scripts (found load({arg}))",
                    )


class TestFuSdkV12HeadlessGodot(unittest.TestCase):
    """Real headless Godot integration tests for FuSdk v1.2.0 core & modules."""

    run_dir: Path | None = None
    results: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_WORKSPACE_ROOT)
        godot_bin = cfg.godot_bin
        if godot_bin is None or not godot_bin.is_file():
            raise unittest.SkipTest("GODOT_BIN not configured in .env.local; skipping headless Godot tests")

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.run_dir = TEST_TMP_ROOT / f"fu_sdk_v1_2_{uuid.uuid4().hex[:10]}"
        probe_dir = cls.run_dir / "probe_proj"
        probe_dir.mkdir(parents=True, exist_ok=True)
        (probe_dir / "project.godot").write_bytes(
            b'config_version=5\n\n[application]\nconfig/name="fu_sdk_v1_2_test"\n'
        )

        # Mirror entire shared/sdk/fu_sdk/ tree into probe project
        sdk_dst = probe_dir / "shared" / "sdk" / "fu_sdk"
        shutil.copytree(SDK_DIR, sdk_dst)
        (probe_dir / "probe.gd").write_bytes(_PROBE_GD.encode("utf-8"))

        # Build Snappy fixtures
        lit_payload = b"Hello FuSdk v1.2.0! " * 5  # 100 bytes (> 60 -> tests l6=60)
        snappy_zero = _encode_varint(0)
        snappy_lit = _encode_varint(len(lit_payload)) + _snappy_literal(lit_payload)
        # Overlapping RLE copy-1: literal "A" + copy1(len=11, offset=1) -> "AAAAAAAAAAAA" (12 bytes)
        snappy_rle = _encode_varint(12) + _snappy_literal(b"A") + _snappy_copy1(11, 1)
        # Copy-2: literal "ABCD" + copy2(len=8, offset=4) -> "ABCDABCDABCD" (12 bytes)
        snappy_copy2 = _encode_varint(12) + _snappy_literal(b"ABCD") + _snappy_copy2(8, 4)
        # Copy-4: literal "XYZ" + copy4(len=6, offset=3) -> "XYZXYZXYZ" (9 bytes)
        snappy_copy4 = _encode_varint(9) + _snappy_literal(b"XYZ") + _snappy_copy4(6, 3)
        # Corrupt copy offset > out.size()
        snappy_bad_offset = _encode_varint(10) + _snappy_literal(b"AB") + _snappy_copy1(8, 5)

        png_bytes = _make_png_bytes(4, 4)
        bmp24_bytes = _make_bmp_bytes(4, 4, bpp=24, top_down=False)
        bmp32_td_bytes = _make_bmp_bytes(4, 4, bpp=32, top_down=True)
        pkg_paths = _write_test_packages(cls.run_dir, png_bytes)

        cfg_payload = {
            "run_dir": str(cls.run_dir),
            "snappy_zero_b64": base64.b64encode(snappy_zero).decode("ascii"),
            "snappy_lit_b64": base64.b64encode(snappy_lit).decode("ascii"),
            "snappy_rle_b64": base64.b64encode(snappy_rle).decode("ascii"),
            "snappy_copy2_b64": base64.b64encode(snappy_copy2).decode("ascii"),
            "snappy_copy4_b64": base64.b64encode(snappy_copy4).decode("ascii"),
            "snappy_bad_offset_b64": base64.b64encode(snappy_bad_offset).decode("ascii"),
            "png_b64": base64.b64encode(png_bytes).decode("ascii"),
            "bmp24_b64": base64.b64encode(bmp24_bytes).decode("ascii"),
            "bmp32_td_b64": base64.b64encode(bmp32_td_bytes).decode("ascii"),
            "bad_ct_png_b64": base64.b64encode(_make_bad_ct_png_bytes()).decode("ascii"),
            "anim_webp_b64": base64.b64encode(_make_animated_webp_bytes()).decode("ascii"),
            **pkg_paths,
        }
        cfg_path = cls.run_dir / "probe_cfg.json"
        out_path = cls.run_dir / "probe_out.json"
        cfg_path.write_bytes(json.dumps(cfg_payload).encode("utf-8"))

        isolated_env = cls.run_dir / "isolated_env"
        isolated_env.mkdir(parents=True, exist_ok=True)
        godot_log = cls.run_dir / "godot.log"
        env = dict(os.environ)
        env["APPDATA"] = str(isolated_env)
        env["LOCALAPPDATA"] = str(isolated_env)
        env["TEMP"] = str(isolated_env)
        env["TMP"] = str(isolated_env)
        env["GODOT_SILENCE_ROOT_WARNING"] = "1"

        proc = subprocess.run(
            [
                str(godot_bin),
                "--headless",
                "--quit",
                "--path",
                str(probe_dir),
                "--log-file",
                str(godot_log),
                "--script",
                "res://probe.gd",
                "--",
                f"--cfg={cfg_path}",
                f"--out={out_path}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log_text = godot_log.read_text(encoding="utf-8", errors="replace") if godot_log.is_file() else ""
        log_errors = analyze_godot_logs(log_text, proc.stdout, proc.stderr)
        combined = f"{log_text}\n{proc.stdout}\n{proc.stderr}"
        if "WARNING: Reading less data than requested" in combined:
            log_errors.append("WARNING: Reading less data than requested")
        if proc.returncode != 0 or log_errors:
            redacted = cfg.redact_path(
                f"rc={proc.returncode} errors={log_errors}\n"
                f"stdout={proc.stdout[-1200:]}\nstderr={proc.stderr[-1200:]}"
            )
            raise AssertionError(f"Headless Godot probe failed or emitted ERROR logs:\n{redacted}")

        parsed = json.loads(out_path.read_text(encoding="utf-8"))
        if not parsed.get("ok"):
            raise AssertionError(f"Probe returned failure: {parsed}")
        cls.results = parsed["results"]

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.run_dir is not None and cls.run_dir.exists():
            shutil.rmtree(cls.run_dir, ignore_errors=True)
        if TEST_TMP_ROOT.exists():
            try:
                if not any(TEST_TMP_ROOT.iterdir()):
                    TEST_TMP_ROOT.rmdir()
            except OSError:
                pass

    def test_sdk_core_v1_2_facade_and_world_builder(self) -> None:
        r = self.results["sdk_core"]
        self.assertEqual(r["sdk_version"], "1.3.0")
        self.assertTrue(r["factories_ok"])

        # Coercers & ImportSession option safety
        self.assertTrue(r["coerce_bool_true"])
        self.assertFalse(r["coerce_bool_false"])
        self.assertTrue(r["coerce_bool_nan"])
        self.assertEqual(r["coerce_string_null"], "fb")
        self.assertEqual(r["coerce_string_ok"], "hello")
        self.assertEqual(r["coerce_int_ok"], -42)
        self.assertEqual(r["coerce_int_overflow"], 7)
        self.assertAlmostEqual(r["coerce_float_ok"], 3.25)
        self.assertAlmostEqual(r["coerce_float_nan"], 1.5)

        self.assertEqual(r["opt_proxy"], "fallback")
        self.assertFalse(r["opt_hidden"])
        self.assertEqual(r["opt_max_items"], 42)
        self.assertAlmostEqual(r["opt_scale"], 1.5)
        self.assertTrue(r["opt_bad_bool"])
        self.assertEqual(r["opt_bad_int"], 99)
        self.assertAlmostEqual(r["opt_bad_float"], 4.5)
        self.assertEqual(r["sanitized_opts"]["proxy"], "")
        self.assertFalse(r["sanitized_opts"]["include_hidden"])
        self.assertEqual(r["sanitized_opts"]["max_items"], 42)
        self.assertTrue(r["sanitized_opts"]["missing_flag"])
        self.assertTrue(r["archived_ref_ok"])
        self.assertEqual(r["archived_proxy"], "")

        # ok_inspect & split sprite path whitelists
        ins = r["inspect_ok"]
        self.assertTrue(ins["ok"])
        self.assertEqual(ins["name"], "My Custom Campaign")
        self.assertGreater(ins["source_bytes"], 0)
        self.assertEqual(ins["decoded_bytes"], 2048)
        self.assertEqual(ins["unique_images"], 5)
        self.assertTrue(r["inspect_legacy_ok"])
        self.assertTrue(r["sp_bmp_ok"])
        self.assertTrue(r["sp_svg_asset_rejected"])
        self.assertTrue(r["sp_svg_res_ok"])

        # WorldBuilder: rename_floor, segment walls/doors/windows/glass + 1e7 ULP, light, grid, module budget
        self.assertTrue(r["renamed_ok"])
        self.assertFalse(r["renamed_bad"])
        self.assertEqual(r["floor0_name"], "Ground Floor")
        self.assertEqual(r["quad_ok_size"], 4)
        self.assertEqual(r["quad_tiny_size"], 0)
        self.assertTrue(r["seg_ids_ok"])
        self.assertEqual(r["wall_huge_ring_pts"], 4)
        self.assertGreater(r["wall_huge_ring_area"], 1e-6)
        self.assertTrue(r["light_id_ok"])
        self.assertAlmostEqual(r["light_fallback_alpha"], 0.0)
        self.assertFalse(r["light_comp0_show_fb"])
        self.assertTrue(r["light_has_simple_light"])
        self.assertTrue(r["grid_ok"])
        self.assertEqual(r["grid_key_count"], 8)
        self.assertEqual(r["dirty_mod_nan"], 0.0)
        self.assertEqual(r["dirty_mod_inf"], 0.0)
        self.assertTrue(r["fit_small"])
        self.assertFalse(r["fit_huge"])

    def test_module_snappy_codec(self) -> None:
        r = self.results["snappy"]
        self.assertTrue(r["zero_ok"])
        self.assertEqual(r["lit_text"], "Hello FuSdk v1.2.0! " * 5)
        self.assertTrue(r["rle_len"]["ok"])
        self.assertEqual(r["rle_len"]["length"], 12)
        self.assertEqual(r["rle_text"], "A" * 12)
        self.assertEqual(r["copy2_text"], "ABCD" * 3)
        self.assertEqual(r["copy4_text"], "XYZ" * 3)
        self.assertFalse(r["bad_empty_ok"])
        self.assertFalse(r["bad_varint_ok"])
        self.assertFalse(r["bad_offset_ok"])
        self.assertFalse(r["over_limit_ok"])

    def test_module_package_source(self) -> None:
        r = self.results["package_source"]
        self.assertTrue(r["dir_ok"])
        self.assertEqual(r["dir_kind"], "dir")
        self.assertEqual(r["dir_prefix"], "")
        self.assertEqual(r["dir_manifest_id"], "demo_pack")
        self.assertTrue(r["dir_has_ci"])
        self.assertFalse(r["dir_has_junk"])
        self.assertTrue(r["dir_txt"]["ok"])
        self.assertEqual(r["dir_txt"]["text"], "Hello FuSDK!\n")
        self.assertEqual(r["dir_files"], ["Assets/Maps/Tavern Floor.png"])
        self.assertGreater(r["dir_decoded"], 0)

        self.assertTrue(r["norm_strip"]["ok"])
        self.assertTrue(r["norm_strip"]["exists"])
        self.assertEqual(r["norm_strip"]["rel_path"], "Assets/Maps/Tavern Floor.png")
        self.assertEqual(r["norm_remote"]["kind"], "remote")
        self.assertTrue(r["norm_unsafe1"]["unsafe"])
        self.assertTrue(r["norm_unsafe2"]["unsafe"])
        self.assertEqual(r["pdec_ok"], "Side View 中文.png")
        self.assertEqual(r["pdec_nul"], "")
        self.assertFalse(r["wrong_fn_ok"])
        self.assertFalse(r["missing_key_ok"])

        self.assertTrue(r["zip_ok"])
        self.assertEqual(r["zip_kind"], "zip")
        self.assertEqual(r["zip_prefix"], "my_pack/")
        self.assertEqual(r["zip_files"], ["Images/Token Hero.png", "data/info.txt", "pack.json"])
        self.assertTrue(r["zip_txt_ok"])
        self.assertFalse(r["zip_has_junk"])
        self.assertGreater(r["zip_decoded"], 0)

        self.assertTrue(r["world_ok"])
        self.assertFalse(r["world_bad_ok"])
        self.assertFalse(r["trunc_ok"])
        self.assertTrue(r["bad_crc_open_ok"])
        self.assertFalse(r["bad_crc_read_ok"])
        self.assertIn("zip_crc32_mismatch", r["bad_crc_reason"])

    def test_module_asset_publisher(self) -> None:
        r = self.results["asset_publisher"]
        self.assertTrue(r["prep_png"]["ok"])
        self.assertEqual(r["prep_png"]["ext"], "png")
        self.assertEqual((r["prep_png"]["w"], r["prep_png"]["h"]), (4, 4))
        self.assertFalse(r["prep_png"]["conv"])

        self.assertTrue(r["prep_jpg"]["ok"])
        self.assertEqual(r["prep_jpg"]["ext"], "jpeg")
        self.assertEqual((r["prep_jpg"]["w"], r["prep_jpg"]["h"]), (8, 6))
        self.assertFalse(r["prep_jpg"]["conv"])

        self.assertTrue(r["prep_webp_vp8"]["ok"])
        self.assertEqual(r["prep_webp_vp8"]["ext"], "webp")
        self.assertTrue(r["prep_webp_vp8l"]["ok"])
        self.assertEqual(r["prep_webp_vp8l"]["ext"], "webp")

        self.assertTrue(r["prep_bmp24"]["ok"])
        self.assertEqual(r["prep_bmp24"]["ext"], "png")
        self.assertTrue(r["prep_bmp24"]["conv"])
        self.assertEqual(r["prep_bmp24"]["magic"], "89504e470d0a1a0a")
        self.assertTrue(r["prep_bmp32_td"]["ok"])
        self.assertTrue(r["prep_bmp32_td"]["conv"])

        self.assertTrue(r["prep_svg"]["ok"])
        self.assertEqual(r["prep_svg"]["ext"], "png")
        self.assertTrue(r["prep_svg"]["conv"])
        self.assertEqual((r["prep_svg"]["w"], r["prep_svg"]["h"]), (16, 12))
        self.assertEqual(r["prep_svg"]["magic"], "89504e470d0a1a0a")
        self.assertTrue(r["prep_svg_ns"]["ok"])

        self.assertFalse(r["rej_gif"]["ok"])
        self.assertTrue(r["rej_gif"]["unsupported"])
        self.assertFalse(r["rej_bad_png_ok"])
        self.assertFalse(r["rej_trunc_png_ok"])
        self.assertFalse(r["rej_anim_webp"]["ok"])
        self.assertTrue(r["rej_anim_webp"]["unsupported"])
        self.assertFalse(r["rej_svg_dtd_ok"])
        self.assertFalse(r["rej_svg_cycle_ok"])
        self.assertFalse(r["rej_rand_ok"])

        self.assertTrue(r["fallback_ok"])
        self.assertEqual(r["fallback_count"], 0)
        self.assertTrue(r["pub_svg_ok"])
        self.assertTrue(r["pub_src_ok"])
        self.assertTrue(r["res_remote_ok"])
        self.assertEqual(r["res_remote_proxy"], "")
        self.assertTrue(r["res_gif_skip"]["ok"])
        self.assertEqual(r["res_gif_skip"]["status"], "unsupported")
        self.assertEqual(r["before_rb_count"], 2)
        self.assertTrue(r["all_existed_before_rb"])
        self.assertEqual(r["rb_removed"], 2)
        self.assertEqual(r["after_rb_count"], 0)
        self.assertFalse(r["any_exists_after_rb"])

    def test_module_entity_library_writer(self) -> None:
        r = self.results["entity_library"]
        self.assertFalse(r["can_no_store"])
        self.assertFalse(r["can_bad_root"])
        self.assertTrue(r["can_ok"])
        self.assertTrue(r["reg_disabled"]["ok"])
        self.assertTrue(r["reg_disabled"]["skipped"])
        self.assertEqual(r["reg_disabled"]["count"], 0)

        self.assertTrue(r["reg_v1"]["ok"])
        self.assertFalse(r["reg_v1"]["skipped"])
        self.assertEqual(r["reg_v1"]["count"], 2)
        # 3 folders ("Monsters", "Monsters/Goblins", "Heroes") + 1 preset + 1 unit = 5 records
        self.assertEqual(r["v1_record_count"], 5)
        self.assertEqual(r["adopted_count"], 1)
        self.assertEqual(r["shared_count"], 1)
        self.assertEqual(r["kinds_found"].get("folder"), 3)
        self.assertEqual(r["kinds_found"].get("preset"), 1)
        self.assertEqual(r["kinds_found"].get("unit"), 1)
        self.assertTrue(r["preset_has_vision"])
        self.assertTrue(r["preset_allow_all"])

        self.assertTrue(r["reg_idem_ok"])
        self.assertEqual(r["idem_extra_writes"], 0)

        self.assertTrue(r["reg_v2_ok"])
        self.assertTrue(r["v2_rev_advanced"])
        self.assertEqual(r["v2_name"], "Goblin Boss")
        self.assertEqual(r["after_rb_name"], "Goblin Scout")

        self.assertFalse(r["reg_cancel"]["ok"])
        self.assertEqual(r["reg_cancel"]["reason"], "cancelled")
        self.assertEqual(r["cancel_leftover_records"], 0)


if __name__ == "__main__":
    unittest.main()
