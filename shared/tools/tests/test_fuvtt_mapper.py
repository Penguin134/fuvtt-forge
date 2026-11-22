"""Unit and integration test suite for Milestone M4 (`fuvtt_assets.gd`, `fuvtt_mapper.gd`, `entry.gd`).

Covers:
1. `TestFuvttMapperStaticHygiene`: UTF-8 no BOM, LF-only, `extends RefCounted`, no `class_name`/`preload(`/
   cross-file `load(`/`JSON.parse_string`/machine-local paths, exact 6-setting `plugin.json` contract.
2. `TestFuvttMapperWithGodot`: Headless `GODOT_BIN` execution of `fuvtt_assets.gd`, `fuvtt_mapper.gd`, and
   `entry.gd` against synthetic and optional `bgdia` dir/zip fixtures, with isolated `APPDATA`/`LOCALAPPDATA`/
   `TEMP`/`TMP` and strict zero `ERROR:`/`Unicode parsing error`/`ObjectDB` leak checks.
3. `TestFuvttMapperPackagedHost`: `validate_mod_dir`, `build_mod`, `validate_zip_archive`, and `verify_mod_with_host`
   on synthetic v9 `.zip`, v14 `world.json`, negative samples (`corrupt.zip`, `gateway.json`), and optional `bgdia`.
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
import time
import unittest
import uuid
import zipfile
import zlib

_TESTS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _TESTS_DIR.parent
_WORKSPACE_ROOT = _TOOLS_DIR.parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from fuvtt_devtools.env_config import load_config  # noqa: E402
from fuvtt_devtools.host_verifier import analyze_godot_logs, verify_mod_with_host  # noqa: E402
from fuvtt_devtools.packager import build_mod  # noqa: E402
from fuvtt_devtools.validator import validate_mod_dir, validate_zip_archive  # noqa: E402
from e2e_fvtt_importer.fixtures import (  # noqa: E402
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
    pack_world_zip,
    redact_bgdia_path,
    resolve_bgdia_dir_world_json,
    resolve_bgdia_zip_path,
    write_json_file,
)

MOD_DIR = _WORKSPACE_ROOT / "mods" / "fvtt-world-importer"
SRC_DIR = MOD_DIR / "src"
SDK_DIR = _WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk"
TEST_TMP_ROOT = _WORKSPACE_ROOT / ".cache" / "test_tmp"

M4_GD_FILES = (
    "fuvtt_assets.gd",
    "fuvtt_mapper.gd",
)

EXPECTED_SETTING_IDS = {
    "proxy",
    "import_scenes",
    "import_characters",
    "import_monsters",
    "include_hidden",
    "skip_missing_assets",
}


def make_bmp_bytes(width: int = 2, height: int = 2, bpp: int = 24, top_down: bool = False) -> bytes:
    """Create a valid uncompressed 24-bit or 32-bit DIB BMP image (bottom-up or top-down)."""
    bytes_per_px = bpp // 8
    row_stride = ((width * bpp + 31) // 32) * 4
    pixel_size = row_stride * height
    file_size = 14 + 40 + pixel_size
    bi_height = -height if top_down else height
    file_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 54)
    info_header = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        bi_height,
        1,
        bpp,
        0,
        pixel_size,
        2835,
        2835,
        0,
        0,
    )
    px = b"\x40\x80\xc0\xff" if bpp == 32 else b"\x40\x80\xc0"
    assert len(px) == bytes_per_px
    row = (px * width).ljust(row_stride, b"\x00")
    return file_header + info_header + (row * height)


def make_bad_ct_png_bytes() -> bytes:
    """Build a PNG with valid CRC/chunks but invalid color_type=99."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 4, 4, 8, 99, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
    idat_data = zlib.compress(b"\x00" + b"\x00" * 12)
    idat_crc = zlib.crc32(b"IDAT" + idat_data) & 0xFFFFFFFF
    idat = struct.pack(">I", len(idat_data)) + b"IDAT" + idat_data + struct.pack(">I", idat_crc)
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    return sig + ihdr + idat + iend


def make_svg_bytes(width: int = 16, height: int = 16) -> bytes:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<rect width="{width}" height="{height}" fill="#336699"/></svg>'
    ).encode("ascii")


def make_os2_bmp_bytes(width: int = 2, height: int = 2) -> bytes:
    """Create a valid OS/2 v1 BMP (dib_size == 12, BITMAPCOREHEADER)."""
    row_stride = ((width * 24 + 31) // 32) * 4
    pixel_size = row_stride * height
    bf_off = 14 + 12
    file_header = struct.pack("<2sIHHI", b"BM", bf_off + pixel_size, 0, 0, bf_off)
    core_header = struct.pack("<IHHHH", 12, width, height, 1, 24)
    row = (b"\x40\x80\xc0" * width).ljust(row_stride, b"\x00")
    return file_header + core_header + (row * height)


def make_paletteless_indexed_bmp_bytes(bpp: int = 8, width: int = 2, height: int = 2) -> bytes:
    """Create an indexed BMP whose bfOffBits=54 omits its color palette."""
    row_stride = ((width * bpp + 31) // 32) * 4
    pixel_size = row_stride * height
    file_header = struct.pack("<2sIHHI", b"BM", 54 + pixel_size, 0, 0, 54)
    info_header = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        height,
        1,
        bpp,
        0,
        pixel_size,
        2835,
        2835,
        0,
        0,
    )
    return file_header + info_header + (b"\x00" * pixel_size)


def make_indexed_bmp_with_palette_bytes(bpp: int = 8, width: int = 2, height: int = 2) -> bytes:
    """Create a valid indexed BMP with a 2-entry BGRA palette (colors_used=2)."""
    row_stride = ((width * bpp + 31) // 32) * 4
    pixel_size = row_stride * height
    palette = b"\x00\x00\xff\x00" + b"\xff\x00\x00\x00"
    bf_off = 14 + 40 + len(palette)
    file_header = struct.pack("<2sIHHI", b"BM", bf_off + pixel_size, 0, 0, bf_off)
    info_header = struct.pack(
        "<IiiHHIIiiII",
        40,
        width,
        height,
        1,
        bpp,
        0,
        pixel_size,
        2835,
        2835,
        2,
        2,
    )
    return file_header + info_header + palette + (b"\x00" * pixel_size)


def make_animated_webp_bytes() -> bytes:
    """Create a valid animated WebP (VP8X + ANIM + ANMF wrapping a 1x1 VP8L frame)."""
    vp8l_payload = bytes.fromhex("2f0000000007100000000100")
    vp8l_chunk = b"VP8L" + struct.pack("<I", len(vp8l_payload)) + vp8l_payload
    if len(vp8l_payload) % 2 == 1:
        vp8l_chunk += b"\x00"
    vp8x_payload = struct.pack("<B3s3s3s", 0x12, b"\x00\x00\x00", b"\x00\x00\x00", b"\x00\x00\x00")
    vp8x_chunk = b"VP8X" + struct.pack("<I", len(vp8x_payload)) + vp8x_payload
    anim_chunk = b"ANIM" + struct.pack("<I", 6) + b"\x00" * 6
    anmf_header = b"\x00" * 12 + struct.pack("<I", 100)
    anmf_payload = anmf_header + vp8l_chunk
    anmf_chunk = b"ANMF" + struct.pack("<I", len(anmf_payload)) + anmf_payload
    body = b"WEBP" + vp8x_chunk + anim_chunk + anmf_chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


_PROBE_GD = r'''extends SceneTree

const _MOD_ROOT: String = "res://mods/fvtt-world-importer"
const _SDK_PATH: String = "res://shared/sdk/fu_sdk/v1.gd"


class _ConfigurableMockHost extends RefCounted:
	var root: Variant = null
	var destination: String = ""
	var cancel_policy: String = "never"
	var archive_policy: String = "mock_ok"
	var warnings: Array = []
	var reports: Array = []
	var archived_urls: Array = []
	var archived_requests: Array = []
	var in_prepare: bool = false
	var _report_count: int = 0
	var _geom_cancelled: bool = false

	func _init(p_cancel: String = "never", p_archive: String = "mock_ok") -> void:
		cancel_policy = p_cancel
		archive_policy = p_archive

	func cancelled() -> bool:
		if _geom_cancelled:
			return true
		if cancel_policy == "immediate":
			return true
		if cancel_policy == "on_prepare_start" and in_prepare:
			return true
		if cancel_policy == "on_inspect_report" and not in_prepare and _report_count >= 1:
			return true
		if cancel_policy == "on_prepare_report" and in_prepare and _report_count >= 2:
			return true
		return false

	func report(message: String) -> void:
		_report_count += 1
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
		archived_urls.append(url)
		archived_requests.append({"url": url, "proxy": proxy})
		if archive_policy == "fail_all":
			return {"ok": false, "reason": "offline_blocked", "reference": ""}
		var digest := url.sha256_text()
		return {
			"ok": true,
			"reference": "asset://%s.png" % digest,
			"size": Vector2(256, 256),
			"bytes": 1024,
		}

	func begin_preview(_total: int, _bounds: Rect2) -> void:
		pass

	func preview_entity(_entity: Dictionary, _kind: String) -> void:
		pass

	func finish_geometry_preview() -> bool:
		if cancel_policy == "on_finish_geometry_preview":
			_geom_cancelled = true
			return false
		if cancel_policy == "fail_finish_geometry_preview":
			return false
		return true


class _MockSharedAssetStore extends RefCounted:
	var _records: Dictionary = {}
	var _rev: int = 1
	var adopted: Array = []
	var shared: Array = []
	var published_paths: Array = []

	func _root_for(dest: String) -> String:
		var norm := dest.replace("\\", "/")
		var parts := norm.split("/", false)
		if parts.size() >= 2 and (parts[parts.size() - 2] == "sessions" or parts[parts.size() - 2] == "recycle"):
			var idx := norm.rfind("/" + parts[parts.size() - 2] + "/")
			if idx > 0:
				return dest.substr(0, idx)
		return ""

	func Publish(dest: String, reference: String, bytes: PackedByteArray) -> String:
		if _root_for(dest).is_empty():
			return JSON.stringify({"ok": false, "reason": "invalid_destination"})
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
		return {"ok": true, "records": _records.duplicate(), "revision": "rev_%d" % _rev}

	func WriteLibraryRecord(_root: String, id: String, expected: PackedByteArray, desired: PackedByteArray, expected_rev: String) -> String:
		if expected_rev != ("rev_%d" % _rev):
			return JSON.stringify({"ok": false, "reason": "revision_mismatch"})
		var cur: PackedByteArray = _records.get(id, PackedByteArray())
		if cur != expected:
			return JSON.stringify({"ok": false, "reason": "expected_mismatch"})
		_records[id] = desired
		_rev += 1
		return JSON.stringify({"ok": true, "changed": true, "revision": "rev_%d" % _rev})

	func AdoptLibraryAsset(_root: String, _campaign: String, reference: String) -> String:
		adopted.append(reference)
		return JSON.stringify({"ok": true})

	func ShareLibraryAsset(_root: String, reference: String) -> String:
		shared.append(reference)
		return JSON.stringify({"ok": true})


class _MockAssetSource extends RefCounted:
	var files: Dictionary = {}

	func read_bytes(rel_path: String) -> PackedByteArray:
		return files.get(rel_path, PackedByteArray())


func _read_json_arg(path: String) -> Variant:
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		return null
	var text := f.get_as_text()
	f.close()
	var j := JSON.new()
	if j.parse(text) != OK:
		return null
	return j.data


func _write_json_out(path: String, payload: Dictionary) -> void:
	var f := FileAccess.open(path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(payload))
		f.close()


func _bounded_size_estimate(val: Variant, depth: int = 0) -> int:
	if depth > 32:
		return -1
	match typeof(val):
		TYPE_STRING, TYPE_STRING_NAME, TYPE_NODE_PATH:
			return 16 + str(val).length() * 4
		TYPE_PACKED_BYTE_ARRAY:
			return 16 + (val as PackedByteArray).size()
		TYPE_PACKED_INT32_ARRAY:
			return 16 + (val as PackedInt32Array).size() * 4
		TYPE_PACKED_FLOAT32_ARRAY:
			return 16 + (val as PackedFloat32Array).size() * 4
		TYPE_PACKED_INT64_ARRAY:
			return 16 + (val as PackedInt64Array).size() * 8
		TYPE_PACKED_FLOAT64_ARRAY:
			return 16 + (val as PackedFloat64Array).size() * 8
		TYPE_PACKED_VECTOR2_ARRAY:
			return 16 + (val as PackedVector2Array).size() * 16
		TYPE_PACKED_VECTOR3_ARRAY:
			return 16 + (val as PackedVector3Array).size() * 24
		TYPE_PACKED_VECTOR4_ARRAY:
			return 16 + (val as PackedVector4Array).size() * 32
		TYPE_PACKED_COLOR_ARRAY:
			return 16 + (val as PackedColorArray).size() * 32
		TYPE_PACKED_STRING_ARRAY:
			if depth + 1 > 32:
				return -1
			var total_ps: int = 16
			for s: String in val as PackedStringArray:
				total_ps += 16 + s.length() * 4
			return total_ps
		TYPE_DICTIONARY:
			var total: int = 16
			var d: Dictionary = val as Dictionary
			for k: Variant in d.keys():
				var kc: int = _bounded_size_estimate(k, depth + 1)
				var vc: int = _bounded_size_estimate(d[k], depth + 1)
				if kc < 0 or vc < 0:
					return -1
				total += kc + vc
			return total
		TYPE_ARRAY:
			var total_a: int = 16
			for item: Variant in val as Array:
				var ic: int = _bounded_size_estimate(item, depth + 1)
				if ic < 0:
					return -1
				total_a += ic
			return total_a
		_:
			return 256


func _validate_world_v3_quick(world: Dictionary) -> Array[String]:
	var errs: Array[String] = []
	if str(world.get("format", "")) != "fus.practice.world" or int(world.get("version", -1)) != 3:
		errs.append("bad format/version")
	var cat: Dictionary = world.get("catalog", {})
	var floors: Array = cat.get("floors", [])
	if floors.is_empty() or floors.size() > 512:
		errs.append("floors out of 1..512: %d" % floors.size())
	var fuid_set: Dictionary = {}
	for f: Variant in floors:
		var fd: Dictionary = f as Dictionary
		var fuid := str(fd.get("floor_uid", ""))
		var fname := str(fd.get("name", ""))
		if fuid.length() != 32 or fuid_set.has(fuid):
			errs.append("bad floor_uid: " + fuid)
		fuid_set[fuid] = true
		if fname.is_empty() or fname.length() > 96 or fname != fname.strip_edges():
			errs.append("bad floor name: " + fname)
	if not fuid_set.has(str(cat.get("active_floor_uid", ""))):
		errs.append("missing active_floor_uid")

	var lfloors: Array = cat.get("layers", {}).get("floors", [])
	var layer_owner: Dictionary = {}
	for lf: Variant in lfloors:
		var lfd: Dictionary = lf as Dictionary
		for l: Variant in lfd.get("layers", []):
			layer_owner[str((l as Dictionary).get("layer_uid", ""))] = str(lfd.get("floor_uid", ""))

	var ents: Array = world.get("entity_state", {}).get("entities", [])
	if ents.size() > 10000:
		errs.append("entities > 10000: %d" % ents.size())
	var eids: Dictionary = {}
	for e: Variant in ents:
		var ed: Dictionary = e as Dictionary
		var eid := str(ed.get("id", ""))
		if eid.is_empty() or eids.has(eid):
			errs.append("bad entity id")
		eids[eid] = true
		var comps: Array = ed.get("components", [])
		if comps.size() < 2:
			errs.append("components < 2")
		elif str(comps[0].get("script", "")) != "res://scenes/entities/components/comp_visual.gd" or str(comps[1].get("script", "")) != "res://scenes/entities/components/comp_permission.gd":
			errs.append("bad core components")
		var sp := str(comps[0].get("state", {}).get("sprite_path", ""))
		if sp.begins_with("user://") or sp.begins_with("file://") or sp.ends_with(".svg"):
			errs.append("bad sprite_path: " + sp)

	for m: Variant in world.get("members", []):
		var md: Dictionary = m as Dictionary
		if not eids.has(str(md.get("entity_id", ""))):
			errs.append("member missing eid")
		if str(layer_owner.get(str(md.get("layer_uid", "")), "")) != str(md.get("floor_uid", "")):
			errs.append("member layer/floor mismatch")

	var mods: Dictionary = world.get("modules", {})
	var entries: Dictionary = mods.get("entries", {})
	for k: Variant in entries.keys():
		var st: Dictionary = entries[k]["state"]
		var eb: int = _bounded_size_estimate(st)
		if var_to_bytes(st).size() > 6 * 1024 * 1024 or eb < 0 or eb > 6 * 1024 * 1024:
			errs.append("module entry > 6MiB: " + str(k))
	var tb: int = _bounded_size_estimate(mods)
	if var_to_bytes(mods).size() > 8 * 1024 * 1024 or tb < 0 or tb > 8 * 1024 * 1024:
		errs.append("modules total > 8MiB")
	var wb := var_to_bytes(world)
	if wb.size() > 32 * 1024 * 1024:
		errs.append("world > 32MiB")
	return errs


func _find_diff(a: Variant, b: Variant, p: String) -> String:
	if typeof(a) != typeof(b):
		return "%s type mismatch" % p
	if a is Dictionary:
		var da: Dictionary = a
		var db: Dictionary = b
		if da.size() != db.size():
			return "%s dict size mismatch" % p
		for k in da.keys():
			if not db.has(k):
				return "%s missing key %s" % [p, str(k)]
			var sub := _find_diff(da[k], db[k], p + "." + str(k))
			if not sub.is_empty():
				return sub
		return ""
	if a is Array:
		var aa: Array = a
		var ab: Array = b
		if aa.size() != ab.size():
			return "%s array size mismatch" % p
		for i in aa.size():
			var sub := _find_diff(aa[i], ab[i], "%s[%d]" % [p, i])
			if not sub.is_empty():
				return sub
		return ""
	if a is float and is_nan(a) and is_nan(b):
		return ""
	if a != b:
		return "%s value mismatch" % p
	return ""


func _init() -> void:
	var cfg_path: String = ""
	var out_path: String = ""
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with("--cfg="):
			cfg_path = arg.substr(6)
		elif arg.begins_with("--out="):
			out_path = arg.substr(6)
	if cfg_path.is_empty() or out_path.is_empty():
		quit(2)
		return
	var cfg_v: Variant = _read_json_arg(cfg_path)
	if not (cfg_v is Dictionary):
		_write_json_out(out_path, {"ok": false, "reason": "bad_cfg"})
		quit(1)
		return
	var cfg: Dictionary = cfg_v as Dictionary

	var sdk_scr := load(_SDK_PATH) as Script
	var assets_scr := load(_MOD_ROOT.path_join("src/fuvtt_assets.gd")) as Script
	var mapper_scr := load(_MOD_ROOT.path_join("src/fuvtt_mapper.gd")) as Script
	var entry_scr := load(_MOD_ROOT.path_join("entry.gd")) as Script
	var sdk: RefCounted = sdk_scr.new()
	var results: Dictionary = {}

	# 1. Assets valid formats & conversions (PNG, JPG, WEBP, BMP->PNG, SVG->PNG, unsafe SVG, oversized SVG)
	var png_bytes: PackedByteArray = Marshalls.base64_to_raw(str(cfg["png_b64"]))
	var bmp_bytes: PackedByteArray = Marshalls.base64_to_raw(str(cfg["bmp_b64"]))
	var svg_bytes: PackedByteArray = Marshalls.base64_to_raw(str(cfg["svg_b64"]))
	var img_tmp := Image.create(2, 2, false, Image.FORMAT_RGB8)
	img_tmp.fill(Color(0.2, 0.5, 0.8))
	var jpg_bytes: PackedByteArray = img_tmp.save_jpg_to_buffer()
	var webp_bytes: PackedByteArray = img_tmp.save_webp_to_buffer()

	var ah_fmt: RefCounted = assets_scr.new()
	var h_fmt := _ConfigurableMockHost.new()
	var s_fmt = sdk.create_session(h_fmt, {"skip_missing_assets": true})
	var store_fmt := _MockSharedAssetStore.new()
	var dest_fmt := str(cfg["run_dir"]).path_join("fmt_root/sessions/桌面 2026-11-20 120000_0123456789abcdef0123456789abcdef")
	h_fmt.destination = dest_fmt
	ah_fmt.set_shared_asset_store(store_fmt, true)

	var res_png: Dictionary = ah_fmt.publish_local_bytes(png_bytes, "png", h_fmt, s_fmt)
	var res_jpg: Dictionary = ah_fmt.publish_local_bytes(jpg_bytes, "jpg", h_fmt, s_fmt)
	var res_webp: Dictionary = ah_fmt.publish_local_bytes(webp_bytes, "webp", h_fmt, s_fmt)
	var res_bmp: Dictionary = ah_fmt.publish_local_bytes(bmp_bytes, "bmp", h_fmt, s_fmt)
	var res_svg: Dictionary = ah_fmt.publish_local_bytes(svg_bytes, "svg", h_fmt, s_fmt)
	var bmp_published_magic := ""
	if bool(res_bmp.get("ok", false)):
		var bname := str(res_bmp["sprite_path"]).substr(8)
		var bf := FileAccess.open(dest_fmt.path_join("assets").path_join(bname), FileAccess.READ)
		if bf != null:
			bmp_published_magic = bf.get_buffer(8).hex_encode()
			bf.close()
	var xxe_svg := '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><!DOCTYPE foo><!ENTITY x "y"></svg>'.to_ascii_buffer()
	var big_svg := '<svg xmlns="http://www.w3.org/2000/svg" width="40000" height="16"></svg>'.to_ascii_buffer()
	var res_xxe: Dictionary = ah_fmt.publish_local_bytes(xxe_svg, "svg", h_fmt, s_fmt)
	var res_big: Dictionary = ah_fmt.publish_local_bytes(big_svg, "svg", h_fmt, s_fmt)
	results["assets_formats"] = {
		"png": res_png, "jpg": res_jpg, "webp": res_webp,
		"bmp": res_bmp, "bmp_magic": bmp_published_magic,
		"svg": res_svg, "xxe": res_xxe, "big": res_big,
	}

	# 2. GIF & corrupt bytes zero Godot errors
	var gif_bytes := PackedByteArray([0x47, 0x49, 0x46, 0x38, 0x39, 0x61, 0x01, 0x00, 0x01, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0x21, 0xF9, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00, 0x2C, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0x02, 0x02, 0x44, 0x01, 0x00, 0x3B])
	var ah_gif: RefCounted = assets_scr.new()
	var h_gif_skip := _ConfigurableMockHost.new()
	var s_gif_skip = sdk.create_session(h_gif_skip, {"skip_missing_assets": true})
	var r_gif_skip: Dictionary = ah_gif.resolve_sprite_ref("anim.gif", {"kind": "local", "ext": "gif", "unsupported_ext": true, "resolved_path_or_url": "anim.gif"}, null, h_gif_skip, s_gif_skip, {"skip_missing_assets": true})
	var ah_gif2: RefCounted = assets_scr.new()
	var h_gif_strict := _ConfigurableMockHost.new()
	var s_gif_strict = sdk.create_session(h_gif_strict, {"skip_missing_assets": false})
	var r_gif_strict: Dictionary = ah_gif2.resolve_sprite_ref("anim.gif", {"kind": "local", "ext": "gif", "unsupported_ext": true, "resolved_path_or_url": "anim.gif"}, null, h_gif_strict, s_gif_strict, {"skip_missing_assets": false})
	var r_gif_magic: Dictionary = ah_gif2.publish_local_bytes(gif_bytes, "png", h_gif_strict, s_gif_strict)
	var r_empty_b: Dictionary = ah_gif2.publish_local_bytes(PackedByteArray(), "png", h_gif_strict, s_gif_strict)
	var r_rand_b: Dictionary = ah_gif2.publish_local_bytes(PackedByteArray([0xFF, 0xFE, 0x00, 0x80, 0x67, 0x61]), "png", h_gif_strict, s_gif_strict)
	var r_trunc_png: Dictionary = ah_gif2.publish_local_bytes(png_bytes.slice(0, 12), "png", h_gif_strict, s_gif_strict)
	results["assets_gif_corrupt"] = {
		"gif_skip": r_gif_skip, "gif_skip_warns": h_gif_skip.warnings.size(),
		"gif_strict": r_gif_strict, "gif_magic": r_gif_magic,
		"empty": r_empty_b, "rand": r_rand_b, "trunc_png": r_trunc_png,
	}

	# 3. Remote archive ok/fail/dedup/disabled
	var ah_rem: RefCounted = assets_scr.new()
	var h_rem_ok := _ConfigurableMockHost.new("never", "mock_ok")
	var rem_opts := {"proxy": "http://127.0.0.1:8080", "skip_missing_assets": true, "download_remote_assets": true}
	var s_rem_ok = sdk.create_session(h_rem_ok, rem_opts)
	var rem_entry := {"kind": "remote", "resolved_path_or_url": "https://example.com/a.png"}
	var r_rem1: Dictionary = ah_rem.resolve_sprite_ref("https://example.com/a.png", rem_entry, null, h_rem_ok, s_rem_ok, rem_opts)
	var r_rem2: Dictionary = ah_rem.resolve_sprite_ref("https://example.com/a.png", rem_entry, null, h_rem_ok, s_rem_ok, rem_opts)

	var ah_rem_f: RefCounted = assets_scr.new()
	var h_rem_f := _ConfigurableMockHost.new("never", "fail_all")
	var s_rem_f = sdk.create_session(h_rem_f, {"skip_missing_assets": true})
	var r_rem_f_skip: Dictionary = ah_rem_f.resolve_sprite_ref("https://example.com/b.png", {"kind": "remote", "resolved_path_or_url": "https://example.com/b.png"}, null, h_rem_f, s_rem_f, {"skip_missing_assets": true, "download_remote_assets": true})
	var ah_rem_s: RefCounted = assets_scr.new()
	var s_rem_s = sdk.create_session(h_rem_f, {"skip_missing_assets": false})
	var r_rem_f_strict: Dictionary = ah_rem_s.resolve_sprite_ref("https://example.com/c.png", {"kind": "remote", "resolved_path_or_url": "https://example.com/c.png"}, null, h_rem_f, s_rem_s, {"skip_missing_assets": false, "download_remote_assets": true})
	var ah_rem_off: RefCounted = assets_scr.new()
	var h_rem_off := _ConfigurableMockHost.new("never", "mock_ok")
	var s_rem_off = sdk.create_session(h_rem_off, {"download_remote_assets": false})
	var r_rem_off: Dictionary = ah_rem_off.resolve_sprite_ref("https://example.com/d.png", {"kind": "remote", "resolved_path_or_url": "https://example.com/d.png"}, null, h_rem_off, s_rem_off, {"download_remote_assets": false})
	results["assets_remote"] = {
		"ok1": r_rem1, "ok2": r_rem2, "archived_count": h_rem_ok.archived_urls.size(), "requests": h_rem_ok.archived_requests,
		"fail_skip": r_rem_f_skip, "fail_strict": r_rem_f_strict,
		"disabled": r_rem_off, "disabled_urls": h_rem_off.archived_urls.size(),
	}

	# 4. Mapper walls/doors/windows/ethereal/degenerate skip
	var h_w := _ConfigurableMockHost.new()
	var s_w = sdk.create_session(h_w, {})
	var b_w = sdk.create_world_builder(null, 150.0)
	var m_w = mapper_scr.new()
	var a_w = assets_scr.new()
	var model_walls := {
		"world_meta": {"id": "mw", "title": "Walls", "core_version": "10", "system": "dnd5e", "system_version": "2.0", "source_kind": "dir"},
		"scenes": [{
			"id": "sc1", "name": "Wall Room", "active": true, "width": 1000.0, "height": 1000.0, "scene_x": 0.0, "scene_y": 0.0,
			"grid_size": 100.0, "grid_type": 1, "grid_distance": 5.0, "grid_units": "ft",
			"background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [], "lights": [], "tokens": [],
			"walls": [
				{"id": "w_ok", "c": [0.0, 0.0, 300.0, 0.0], "door": 0, "ds": 0, "move": 20, "sight": 20, "light": 20, "sense": 20},
				{"id": "w_tiny", "c": [100.0, 100.0, 100.2, 100.2], "door": 0, "ds": 0, "move": 20, "sight": 20, "light": 20, "sense": 20},
				{"id": "d_zero", "c": [200.0, 200.0, 200.0, 200.0], "door": 1, "ds": 0, "move": 20, "sight": 20, "light": 20, "sense": 20},
				{"id": "d_closed", "c": [0.0, 100.0, 100.0, 100.0], "door": 1, "ds": 0, "move": 20, "sight": 20, "light": 20, "sense": 20},
				{"id": "d_open", "c": [0.0, 200.0, 100.0, 200.0], "door": 1, "ds": 1, "move": 20, "sight": 20, "light": 20, "sense": 20},
				{"id": "d_secret", "c": [0.0, 300.0, 100.0, 300.0], "door": 2, "ds": 0, "move": 20, "sight": 20, "light": 20, "sense": 20},
				{"id": "win", "c": [0.0, 400.0, 100.0, 400.0], "door": 0, "ds": 0, "move": 20, "sight": 0, "light": 0, "sense": 0},
				{"id": "eth", "c": [0.0, 500.0, 100.0, 500.0], "door": 0, "ds": 0, "move": 0, "sight": 0, "light": 0, "sense": 0},
			],
		}],
		"actors": [], "assets": {}, "source_records": 9,
	}
	var mw_res: Dictionary = m_w.map_to_world(model_walls, b_w, a_w, null, h_w, s_w, {})
	var w_world: Dictionary = b_w.get_world()
	var w_kinds := {}
	var w_ring_sizes: Array = []
	var door_opens: Array = []
	for ent: Dictionary in w_world["entity_state"]["entities"]:
		var vd: Dictionary = ent["components"][0]["state"].get("vector_drawing", {})
		var src: Dictionary = vd.get("source", {})
		var k := str(src.get("kind", ""))
		w_kinds[k] = int(w_kinds.get(k, 0)) + 1
		for rng in vd.get("paths", []):
			w_ring_sizes.append((rng as PackedVector2Array).size() if rng is PackedVector2Array else (rng as Array).size())
		if k == "door":
			door_opens.append(bool(src.get("open", false)))
	results["mapper_walls"] = {
		"ok": mw_res.get("ok", false), "kinds": w_kinds, "ring_sizes": w_ring_sizes,
		"door_opens": door_opens, "warnings": h_w.warnings, "v3_errs": _validate_world_v3_quick(w_world),
	}

	# 5. Mapper lights, fallback_color suppression, multi-grid scaling & grid_alignment
	var h_l := _ConfigurableMockHost.new()
	var s_l = sdk.create_session(h_l, {})
	var b_l = sdk.create_world_builder(null, 150.0)
	var m_l = mapper_scr.new()
	var a_l = assets_scr.new()
	var model_lg := {
		"world_meta": {"id": "mlg", "title": "LightsGrid", "core_version": "10", "system": "dnd5e", "system_version": "2.0", "source_kind": "dir"},
		"scenes": [
			{
				"id": "sg1", "name": "Grid100", "active": true, "width": 1000.0, "height": 1000.0, "scene_x": 0.0, "scene_y": 0.0,
				"grid_size": 100.0, "grid_type": 1, "grid_distance": 5.0, "grid_units": "ft",
				"background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [], "walls": [], "tokens": [],
				"lights": [{"id": "lt1", "x": -50.0, "y": -50.0, "bright": 20.0, "dim": 40.0, "angle": 360.0, "hidden": false}],
			},
			{
				"id": "sg2", "name": "Grid50", "active": false, "width": 1000.0, "height": 1000.0, "scene_x": 0.0, "scene_y": 0.0,
				"grid_size": 50.0, "grid_type": 1, "grid_distance": 5.0, "grid_units": "ft",
				"background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [], "walls": [],
				"lights": [],
				"tokens": [{"id": "tk_s2", "name": "ScaledTok", "actor_id": "", "actor_type": "npc", "img_ref": "", "x": 100.0, "y": 100.0, "width": 1.0, "height": 1.0, "scale": 1.0, "rotation": 0.0, "hidden": false, "disposition": -1, "actor_link": false, "sight_enabled": false, "sight_range": 0.0, "sight_angle": 360.0}],
			},
			{
				"id": "sg3", "name": "Gridless70", "active": false, "width": 1000.0, "height": 1000.0, "scene_x": 0.0, "scene_y": 0.0,
				"grid_size": 70.0, "grid_type": 0, "grid_distance": 5.0, "grid_units": "ft",
				"background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [], "walls": [], "lights": [],
				"tokens": [{"id": "tk_s3", "name": "GridlessTok", "actor_id": "", "actor_type": "npc", "img_ref": "", "x": 100.0, "y": 100.0, "width": 1.0, "height": 1.0, "scale": 1.0, "rotation": 0.0, "hidden": false, "disposition": -1, "actor_link": false, "sight_enabled": false, "sight_range": 0.0, "sight_angle": 360.0}],
			},
		],
		"actors": [], "assets": {}, "source_records": 3,
	}
	m_l.map_to_world(model_lg, b_l, a_l, null, h_l, s_l, {})
	var l_world: Dictionary = b_l.get_world()
	var lt_info: Dictionary = {}
	var tok_positions: Dictionary = {}
	for ent: Dictionary in l_world["entity_state"]["entities"]:
		if str(ent.get("display_name", "")) == "Light":
			var lt_comp: Dictionary = ent["components"][2]["state"]
			lt_info = {
				"ent_alpha": (ent["fallback_color"] as Color).a,
				"vis_alpha": (ent["components"][0]["state"]["fallback_color"] as Color).a,
				"show_fallback": ent["components"][0]["state"]["show_fallback"],
				"radius": lt_comp["radius"],
				"view_angle": lt_comp["view_angle"],
				"pos_x": (ent["xform"]["pos"] as Vector2).x,
			}
		else:
			tok_positions[str(ent.get("display_name", ""))] = [
				(ent["xform"]["pos"] as Vector2).x,
				(ent["xform"]["pos"] as Vector2).y,
			]
	var ga_entry: Dictionary = l_world["modules"]["entries"].get("grid_alignment", {})
	results["mapper_lights_grid"] = {
		"light": lt_info,
		"tok_positions": tok_positions,
		"ga_keys": ga_entry.get("state", {}).keys(),
		"ga_version": ga_entry.get("version", 0),
		"ga_state": ga_entry.get("state", {}),
		"v3_errs": _validate_world_v3_quick(l_world),
	}

	# 6. Floor 0 rename, active_floor_uid, 0-scene fallback, 512/10000 caps
	var h_f := _ConfigurableMockHost.new()
	var s_f = sdk.create_session(h_f, {})
	var b_f = sdk.create_world_builder(null, 150.0)
	var m_f = mapper_scr.new()
	m_f.map_to_world({
		"world_meta": {"id": "f2", "title": "Floors", "core_version": "10", "system": "dnd5e", "system_version": "2", "source_kind": "dir"},
		"scenes": [
			{"id": "s1", "name": "S1", "active": false, "width": 1000.0, "height": 1000.0, "scene_x": 0.0, "scene_y": 0.0, "grid_size": 100.0, "grid_type": 1, "grid_distance": 5.0, "grid_units": "ft", "background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [], "walls": [{"id": "w1", "c": [0.0, 0.0, 100.0, 0.0], "door": 0, "ds": 0, "move": 20, "sight": 20, "light": 20, "sense": 20}], "lights": [], "tokens": []},
			{"id": "s2", "name": "S2", "active": true, "width": 1000.0, "height": 1000.0, "scene_x": 0.0, "scene_y": 0.0, "grid_size": 100.0, "grid_type": 1, "grid_distance": 5.0, "grid_units": "ft", "background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [], "walls": [{"id": "w2", "c": [0.0, 0.0, 100.0, 0.0], "door": 0, "ds": 0, "move": 20, "sight": 20, "light": 20, "sense": 20}], "lights": [], "tokens": []},
		],
		"actors": [], "assets": {}, "source_records": 4,
	}, b_f, assets_scr.new(), null, h_f, s_f, {})
	var f_world: Dictionary = b_f.get_world()
	var fl_names: Array = []
	var fl_uids: Array = []
	for fl: Dictionary in f_world["catalog"]["floors"]:
		fl_names.append(fl["name"])
		fl_uids.append(fl["floor_uid"])
	var member_floors: Array = []
	for mb: Dictionary in f_world["members"]:
		member_floors.append(mb["floor_uid"])

	# 0 scenes + 1 actor
	var h_z := _ConfigurableMockHost.new()
	var b_z = sdk.create_world_builder(null, 150.0)
	mapper_scr.new().map_to_world({
		"world_meta": {"id": "z0", "title": "ZeroScenes", "core_version": "10", "system": "dnd5e", "system_version": "2", "source_kind": "dir"},
		"scenes": [],
		"actors": [{"id": "a1", "name": "Solo Hero", "actor_type": "character", "sub_type": "", "folder_name": "", "img_ref": "", "token_img_ref": "", "token_width": 1.0, "token_height": 1.0, "token_scale": 1.0, "disposition": 1, "actor_link": true, "ac": 16, "hp_value": 20, "hp_max": 20, "cr_or_level": 3.0, "abilities": {}, "speed": {}, "senses": {"darkvision": 60.0}, "biography": "", "raw_summary": {}}],
		"assets": {}, "source_records": 1,
	}, b_z, assets_scr.new(), null, h_z, sdk.create_session(h_z, {}), {})
	var z_world: Dictionary = b_z.get_world()

	# 515 scenes cap
	var scenes_515: Array = []
	for idx515: int in range(515):
		scenes_515.append({"id": "sc_%d" % idx515, "name": "Floor_%d" % idx515, "active": idx515 == 0, "width": 500.0, "height": 500.0, "scene_x": 0.0, "scene_y": 0.0, "grid_size": 100.0, "grid_type": 1, "grid_distance": 5.0, "grid_units": "ft", "background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [], "walls": [], "lights": [], "tokens": []})
	var h_515 := _ConfigurableMockHost.new()
	var b_515 = sdk.create_world_builder(null, 150.0)
	mapper_scr.new().map_to_world({"world_meta": {"id": "c515", "title": "Cap512", "core_version": "10", "system": "dnd5e", "system_version": "2", "source_kind": "dir"}, "scenes": scenes_515, "actors": [], "assets": {}, "source_records": 515}, b_515, assets_scr.new(), null, h_515, sdk.create_session(h_515, {}), {})

	# 10050 walls cap
	var walls_10050: Array = []
	for w_i: int in range(10050):
		walls_10050.append({"id": "wc_%d" % w_i, "c": [0.0, float(w_i), 100.0, float(w_i)], "door": 0, "ds": 0, "move": 20, "sight": 20, "light": 20, "sense": 20})
	var h_10k := _ConfigurableMockHost.new()
	var b_10k = sdk.create_world_builder(null, 150.0)
	mapper_scr.new().map_to_world({
		"world_meta": {"id": "c10k", "title": "Cap10k", "core_version": "10", "system": "dnd5e", "system_version": "2", "source_kind": "dir"},
		"scenes": [{"id": "s10k", "name": "Crowded", "active": true, "width": 500.0, "height": 500.0, "scene_x": 0.0, "scene_y": 0.0, "grid_size": 100.0, "grid_type": 1, "grid_distance": 5.0, "grid_units": "ft", "background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [], "walls": walls_10050, "lights": [], "tokens": []}],
		"actors": [], "assets": {}, "source_records": 10050,
	}, b_10k, assets_scr.new(), null, h_10k, sdk.create_session(h_10k, {}), {})
	var w_10k: Dictionary = b_10k.get_world()
	results["mapper_floors_caps"] = {
		"fl_names": fl_names, "fl_uids": fl_uids, "active_uid": f_world["catalog"]["active_floor_uid"],
		"member_floors": member_floors, "f_v3_errs": _validate_world_v3_quick(f_world),
		"z_floor0_name": z_world["catalog"]["floors"][0]["name"],
		"z_entities": z_world["entity_state"]["entities"].size(),
		"z_v3_errs": _validate_world_v3_quick(z_world),
		"cap512_count": b_515.get_world()["catalog"]["floors"].size(),
		"cap512_warns": h_515.warnings.size(),
		"cap10k_count": w_10k["entity_state"]["entities"].size(),
		"cap10k_warns": h_10k.warnings.size(),
		"cap10k_v3_errs": _validate_world_v3_quick(w_10k),
	}

	# 7. world.modules 6/8/30 MiB budget trimming
	var long_bio := "B".repeat(5000)
	var big_actors: Array = []
	for ba_i: int in range(900):
		big_actors.append({
			"id": "ba_%d" % ba_i, "name": "BioActor_%d" % ba_i, "actor_type": "npc", "sub_type": "",
			"folder_name": "BigFolder", "img_ref": "", "token_img_ref": "",
			"token_width": 1.0, "token_height": 1.0, "token_scale": 1.0, "disposition": -1, "actor_link": false,
			"ac": 12, "hp_value": 10, "hp_max": 10, "cr_or_level": 1.0,
			"abilities": {"str": {"value": 10, "mod": 0}}, "speed": {"walk": 30.0}, "senses": {"darkvision": 0.0},
			"biography": long_bio, "raw_summary": {"classes": [], "sub_type": "", "folder": "BigFolder"},
		})
	var h_bud := _ConfigurableMockHost.new()
	var b_bud = sdk.create_world_builder(null, 150.0)
	mapper_scr.new().map_to_world({
		"world_meta": {"id": "bud", "title": "Budget", "core_version": "10", "system": "dnd5e", "system_version": "2", "source_kind": "dir"},
		"scenes": [{"id": "sb", "name": "S", "active": true, "width": 500.0, "height": 500.0, "scene_x": 0.0, "scene_y": 0.0, "grid_size": 100.0, "grid_type": 1, "grid_distance": 5.0, "grid_units": "ft", "background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [], "walls": [], "lights": [], "tokens": []}],
		"actors": big_actors, "assets": {}, "source_records": 901,
	}, b_bud, assets_scr.new(), null, h_bud, sdk.create_session(h_bud, {}), {})
	var bud_world: Dictionary = b_bud.get_world()
	var bud_entry: Dictionary = bud_world["modules"]["entries"].get("fvtt_world_importer", {})
	var bud_state: Dictionary = bud_entry.get("state", {})
	var bud_bio_len := -1
	if not (bud_state.get("actors", []) as Array).is_empty():
		bud_bio_len = str(bud_state["actors"][0].get("biography", "")).length()
	results["mapper_budget"] = {
		"v3_errs": _validate_world_v3_quick(bud_world),
		"warns": h_bud.warnings,
		"entry_var_bytes": var_to_bytes(bud_state).size(),
		"entry_bounded": _bounded_size_estimate(bud_state),
		"first_bio_len": bud_bio_len,
	}

	# 8. entity-library 4-gate checks (MockHostBridge, mismatched root/dest, matching mock store)
	var h_lib_none := _ConfigurableMockHost.new()
	var b_lib_none = sdk.create_world_builder(null, 150.0)
	var m_lib_none = mapper_scr.new()
	var single_actor := [{"id": "lib1", "name": "LibGoblin", "actor_type": "npc", "sub_type": "", "folder_name": "Monsters/Goblins", "img_ref": "", "token_img_ref": "", "token_width": 1.0, "token_height": 1.0, "token_scale": 1.0, "disposition": -1, "actor_link": false, "ac": 15, "hp_value": 7, "hp_max": 7, "cr_or_level": 0.25, "abilities": {}, "speed": {}, "senses": {}, "biography": "", "raw_summary": {}}]
	var lib_res_none: Dictionary = m_lib_none.map_to_world({
		"world_meta": {"id": "libw", "title": "Lib", "core_version": "10", "system": "dnd5e", "system_version": "2", "source_kind": "dir"},
		"scenes": [], "actors": single_actor, "assets": {}, "source_records": 1,
	}, b_lib_none, assets_scr.new(), null, h_lib_none, sdk.create_session(h_lib_none, {}), {"register_entity_library": true})

	var lib_root := str(cfg["run_dir"]).path_join("lib_root")
	var lib_dest := lib_root.path_join("sessions/桌面 2026-11-20 120000_abcdefabcdefabcdefabcdefabcdefab")
	var mock_store := _MockSharedAssetStore.new()
	var h_lib_bad := _ConfigurableMockHost.new()
	h_lib_bad.root = str(cfg["run_dir"]).path_join("other_root")
	h_lib_bad.destination = lib_dest
	var m_lib_bad = mapper_scr.new()
	m_lib_bad.set_shared_asset_store(mock_store, true)
	var lib_res_bad: Dictionary = m_lib_bad.map_to_world({
		"world_meta": {"id": "libw", "title": "Lib", "core_version": "10", "system": "dnd5e", "system_version": "2", "source_kind": "dir"},
		"scenes": [], "actors": single_actor, "assets": {}, "source_records": 1,
	}, sdk.create_world_builder(null, 150.0), assets_scr.new(), null, h_lib_bad, sdk.create_session(h_lib_bad, {}), {"register_entity_library": true})

	var h_lib_ok := _ConfigurableMockHost.new()
	h_lib_ok.root = lib_root
	h_lib_ok.destination = lib_dest
	var m_lib_ok = mapper_scr.new()
	m_lib_ok.set_shared_asset_store(mock_store, true)
	var lib_res_ok: Dictionary = m_lib_ok.map_to_world({
		"world_meta": {"id": "libw", "title": "Lib", "core_version": "10", "system": "dnd5e", "system_version": "2", "source_kind": "dir"},
		"scenes": [], "actors": single_actor, "assets": {}, "source_records": 1,
	}, sdk.create_world_builder(null, 150.0), assets_scr.new(), null, h_lib_ok, sdk.create_session(h_lib_ok, {}), {"register_entity_library": true})
	results["mapper_entity_lib"] = {
		"none_count": lib_res_none.get("registered_library_count", -1),
		"bad_count": lib_res_bad.get("registered_library_count", -1),
		"ok_count": lib_res_ok.get("registered_library_count", -1),
		"stored_keys": mock_store._records.size(),
	}

	# 9. Entry hostile options & cancellation + cleanup_published
	var entry_inst: RefCounted = entry_scr.new()
	var h_hostile := _ConfigurableMockHost.new("never", "mock_ok")
	h_hostile.in_prepare = true
	var hostile_opts := {
		"proxy": null,
		"import_scenes": "false",
		"import_characters": 0,
		"import_monsters": [],
		"include_hidden": {},
		"skip_missing_assets": NAN,
		"extra_inf": INF,
	}
	var prep_hostile: Dictionary = entry_inst.prepare_import(str(cfg["hostile_wj"]), hostile_opts, h_hostile)
	var hostile_world: Dictionary = prep_hostile.get("world", {})
	var hostile_unit_names: Array = []
	for e_h: Dictionary in hostile_world.get("entity_state", {}).get("entities", []):
		if str(e_h.get("entity_type", "")) == "unit":
			hostile_unit_names.append(e_h.get("display_name", ""))
	var proxy_vals: Array = []
	for r_h: Dictionary in h_hostile.archived_requests:
		proxy_vals.append(r_h.get("proxy", ""))

	# Cancellation policies on entry
	var cancel_results: Dictionary = {}
	for pol: String in ["immediate", "on_inspect_report", "on_prepare_start", "on_prepare_report", "on_finish_geometry_preview"]:
		var h_c := _ConfigurableMockHost.new(pol, "mock_ok")
		if pol == "immediate" or pol == "on_inspect_report":
			cancel_results[pol] = entry_scr.new().inspect_import(str(cfg["hostile_wj"]), {}, h_c)
		else:
			h_c.in_prepare = true
			cancel_results[pol] = entry_scr.new().prepare_import(str(cfg["hostile_wj"]), {}, h_c)
	var h_gf := _ConfigurableMockHost.new("fail_finish_geometry_preview", "mock_ok")
	h_gf.in_prepare = true
	var geom_fail_res: Dictionary = entry_scr.new().prepare_import(str(cfg["hostile_wj"]), {}, h_gf)

	# Verify cleanup_published deletes newly published files on cancel/failure
	var clean_dest := str(cfg["run_dir"]).path_join("clean_root/sessions/桌面 2026-11-20 120000_11111111111111111111111111111111")
	var clean_store := _MockSharedAssetStore.new()
	var h_clean := _ConfigurableMockHost.new()
	h_clean.destination = clean_dest
	var ah_clean: RefCounted = assets_scr.new()
	ah_clean.set_shared_asset_store(clean_store, true)
	var pub_c: Dictionary = ah_clean.publish_local_bytes(png_bytes, "png", h_clean, sdk.create_session(h_clean, {}))
	var pub_file := clean_dest.path_join("assets").path_join(str(pub_c.get("sprite_path", "")).substr(8))
	var existed_after_pub := FileAccess.file_exists(pub_file)
	ah_clean.cleanup_published()
	var existed_after_cleanup := FileAccess.file_exists(pub_file)
	results["entry_hostile_cancel"] = {
		"hostile_ok": prep_hostile.get("ok", false),
		"hostile_units": hostile_unit_names,
		"hostile_v3_errs": _validate_world_v3_quick(hostile_world),
		"proxy_vals": proxy_vals,
		"cancel_results": cancel_results,
		"geom_fail_res": geom_fail_res,
		"existed_after_pub": existed_after_pub,
		"existed_after_cleanup": existed_after_cleanup,
	}

	# 10. Optional bgdia dir & zip tests
	var bgdia_out: Dictionary = {}
	for bkey: String in ["bgdia_dir_wj", "bgdia_zip"]:
		var bpath := str(cfg.get(bkey, ""))
		if bpath.is_empty():
			continue
		var h_b := _ConfigurableMockHost.new("never", "fail_all")
		var b_ins: Dictionary = entry_scr.new().inspect_import(bpath, {}, h_b)
		h_b.in_prepare = true
		var b_prep: Dictionary = entry_scr.new().prepare_import(bpath, {}, h_b)
		var b_world: Dictionary = b_prep.get("world", {})
		var b_bytes: PackedByteArray = var_to_bytes(b_world)
		var b_dec: Variant = bytes_to_var(b_bytes)
		var b_diff := _find_diff(b_world, b_dec, "$") if (b_dec is Dictionary) else "not_dict"
		var b_units := 0
		for e_b: Dictionary in b_world.get("entity_state", {}).get("entities", []):
			if str(e_b.get("entity_type", "")) == "unit":
				b_units += 1
		bgdia_out[bkey] = {
			"ins_ok": b_ins.get("ok", false),
			"ins_decoded_bytes": b_ins.get("decoded_bytes", 0),
			"ins_counts": b_ins.get("counts", {}),
			"prep_ok": b_prep.get("ok", false),
			"floors": b_world.get("catalog", {}).get("floors", []).size(),
			"units": b_units,
			"serialized_bytes": b_bytes.size(),
			"roundtrip_diff": b_diff,
			"v3_errs": _validate_world_v3_quick(b_world),
		}
	results["bgdia"] = bgdia_out

	# 11. Iteration 2 regression cases:
	# 11a. Malformed SVG XML & invalid UTF-8 SVG (must not crash or emit errors)
	var ah_reg: RefCounted = assets_scr.new()
	var h_reg := _ConfigurableMockHost.new()
	var s_reg = sdk.create_session(h_reg, {"skip_missing_assets": false})
	var svg_malformed := '<svg width="16" height="16"><rect<</svg>'.to_ascii_buffer()
	var svg_unclosed := '<svg width="16" height="16">not valid xml'.to_ascii_buffer()
	var svg_mismatch := '<svg width="16" height="16"><rect></g></svg>'.to_ascii_buffer()
	var svg_bad_utf8 := PackedByteArray([0xFF, 0xFE]) + '<svg width="16" height="16"></svg>'.to_ascii_buffer()

	# 11b. Top-down 24-bit & 32-bit BMPs and bottom-up 32-bit BMP
	var bmp24_td: PackedByteArray = Marshalls.base64_to_raw(str(cfg["bmp24_td_b64"]))
	var bmp32_td: PackedByteArray = Marshalls.base64_to_raw(str(cfg["bmp32_td_b64"]))
	var bmp32_bu: PackedByteArray = Marshalls.base64_to_raw(str(cfg["bmp32_bu_b64"]))
	var store_reg := _MockSharedAssetStore.new()
	var dest_reg := str(cfg["run_dir"]).path_join("reg_root/sessions/桌面 2026-11-20 120000_fedcba9876543210fedcba9876543210")
	h_reg.destination = dest_reg
	ah_reg.set_shared_asset_store(store_reg, true)
	var res_bmp24_td: Dictionary = ah_reg.publish_local_bytes(bmp24_td, "bmp", h_reg, s_reg)
	var res_bmp32_td: Dictionary = ah_reg.publish_local_bytes(bmp32_td, "bmp", h_reg, s_reg)
	var res_bmp32_bu: Dictionary = ah_reg.publish_local_bytes(bmp32_bu, "bmp", h_reg, s_reg)

	# 11c. Corrupt/truncated PNG, JPG, WEBP, BMP headers (must fail with 0 Godot ERRORs)
	var corrupt_cases := {
		"png_24b": png_bytes.slice(0, mini(24, png_bytes.size())),
		"png_only_ihdr": Marshalls.base64_to_raw(str(cfg["png_only_ihdr_b64"])),
		"png_bad_crc": Marshalls.base64_to_raw(str(cfg["png_bad_crc_b64"])),
		"png_trunc_idat": Marshalls.base64_to_raw(str(cfg["png_trunc_idat_b64"])),
		"bad_ct_png": Marshalls.base64_to_raw(str(cfg["bad_ct_png_b64"])),
		"jpg_sof_corrupt": Marshalls.base64_to_raw(str(cfg["jpg_sof_corrupt_b64"])),
		"webp_vp8_trunc": Marshalls.base64_to_raw(str(cfg["webp_vp8_trunc_b64"])),
		"webp_vp8x_trunc": Marshalls.base64_to_raw(str(cfg["webp_vp8x_trunc_b64"])),
		"vp8l_trunc": Marshalls.base64_to_raw(str(cfg["vp8l_trunc_b64"])),
		"bmp_trunc30": bmp24_td.slice(0, 30),
	}
	var corrupt_out: Dictionary = {}
	for ckey: String in corrupt_cases.keys():
		corrupt_out[ckey] = ah_reg.publish_local_bytes(corrupt_cases[ckey], "png", h_reg, s_reg)

	results["iter2_assets"] = {
		"svg_malformed": ah_reg.publish_local_bytes(svg_malformed, "svg", h_reg, s_reg),
		"svg_unclosed": ah_reg.publish_local_bytes(svg_unclosed, "svg", h_reg, s_reg),
		"svg_mismatch": ah_reg.publish_local_bytes(svg_mismatch, "svg", h_reg, s_reg),
		"svg_bad_utf8": ah_reg.publish_local_bytes(svg_bad_utf8, "svg", h_reg, s_reg),
		"bmp24_td": res_bmp24_td,
		"bmp32_td": res_bmp32_td,
		"bmp32_bu": res_bmp32_bu,
		"corrupt": corrupt_out,
		"store_has_rootfor": store_reg.has_method("RootFor"),
	}

	# 11d. >= 2,500 numeric-heavy actors -> world.modules passes WorldModuleState._bounded() (6 MiB / 8 MiB)
	var actors_2500: Array = []
	for a25_i: int in range(2500):
		actors_2500.append({
			"id": "a25_%d" % a25_i,
			"name": "NumActor_%d" % a25_i,
			"actor_type": "npc",
			"sub_type": "humanoid",
			"folder_name": "NumFolder",
			"img_ref": "",
			"token_img_ref": "",
			"token_width": 1.0,
			"token_height": 1.0,
			"token_scale": 1.0,
			"disposition": -1,
			"actor_link": false,
			"ac": 13,
			"hp_value": 22,
			"hp_max": 22,
			"cr_or_level": 1.0,
			"abilities": {
				"str": {"value": 14, "mod": 2},
				"dex": {"value": 12, "mod": 1},
				"con": {"value": 13, "mod": 1},
				"int": {"value": 10, "mod": 0},
				"wis": {"value": 11, "mod": 0},
				"cha": {"value": 9, "mod": -1},
			},
			"speed": {"walk": 30.0, "fly": 0.0, "swim": 0.0, "climb": 0.0, "burrow": 0.0},
			"senses": {"darkvision": 60.0, "blindsight": 0.0, "tremorsense": 0.0, "truesight": 0.0},
			"biography": "",
			"raw_summary": {"classes": [], "sub_type": "humanoid", "folder": "NumFolder"},
		})
	var h_2500 := _ConfigurableMockHost.new()
	var b_2500 = sdk.create_world_builder(null, 150.0)
	var m_2500_res: Dictionary = mapper_scr.new().map_to_world({
		"world_meta": {"id": "m2500", "title": "Heavy2500", "core_version": "10", "system": "dnd5e", "system_version": "2", "source_kind": "dir"},
		"scenes": [{"id": "s_2500", "name": "S", "active": true, "width": 500.0, "height": 500.0, "scene_x": 0.0, "scene_y": 0.0, "grid_size": 100.0, "grid_type": 1, "grid_distance": 5.0, "grid_units": "ft", "background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [], "walls": [], "lights": [], "tokens": []}],
		"actors": actors_2500,
		"assets": {},
		"source_records": 2501,
	}, b_2500, assets_scr.new(), null, h_2500, sdk.create_session(h_2500, {}), {})
	var w_2500: Dictionary = b_2500.get_world()
	var mods_2500: Dictionary = w_2500.get("modules", {})
	var has_imp_2500: bool = mods_2500.get("entries", {}).has("fvtt_world_importer")
	var imp_2500_bounded: int = _bounded_size_estimate(mods_2500.get("entries", {}).get("fvtt_world_importer", {}).get("state", {})) if has_imp_2500 else 0
	results["iter2_2500"] = {
		"ok": m_2500_res.get("ok", false),
		"v3_errs": _validate_world_v3_quick(w_2500),
		"mods_bounded": _bounded_size_estimate(mods_2500),
		"mods_var_bytes": var_to_bytes(mods_2500).size(),
		"has_importer_mod": has_imp_2500,
		"imp_entry_bounded": imp_2500_bounded,
	}

	# 11e. Two scenes with empty "id": "" -> zero duplicate entity IDs
	var h_emp := _ConfigurableMockHost.new()
	var b_emp = sdk.create_world_builder(null, 150.0)
	var m_emp_res: Dictionary = mapper_scr.new().map_to_world({
		"world_meta": {"id": "emp", "title": "EmptySceneIds", "core_version": "10", "system": "dnd5e", "system_version": "2", "source_kind": "dir"},
		"scenes": [
			{
				"id": "", "name": "EmptyA", "active": true, "width": 800.0, "height": 600.0, "scene_x": 0.0, "scene_y": 0.0,
				"grid_size": 100.0, "grid_type": 1, "grid_distance": 5.0, "grid_units": "ft",
				"background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [],
				"walls": [{"id": "", "c": [0.0, 0.0, 100.0, 0.0], "door": 0, "ds": 0, "move": 20, "sight": 20, "light": 20, "sense": 20}],
				"lights": [{"id": "", "x": 100.0, "y": 100.0, "bright": 10.0, "dim": 20.0, "angle": 0.0, "hidden": false}],
				"tokens": [{"id": "", "name": "TokA", "actor_id": "", "actor_type": "npc", "img_ref": "", "x": 100.0, "y": 100.0, "width": 1.0, "height": 1.0, "scale": 1.0, "rotation": 0.0, "hidden": false, "disposition": -1, "actor_link": false, "sight_enabled": false, "sight_range": 0.0, "sight_angle": 360.0}],
			},
			{
				"id": "", "name": "EmptyB", "active": false, "width": 800.0, "height": 600.0, "scene_x": 0.0, "scene_y": 0.0,
				"grid_size": 100.0, "grid_type": 1, "grid_distance": 5.0, "grid_units": "ft",
				"background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [],
				"walls": [{"id": "", "c": [0.0, 0.0, 100.0, 0.0], "door": 0, "ds": 0, "move": 20, "sight": 20, "light": 20, "sense": 20}],
				"lights": [{"id": "", "x": 100.0, "y": 100.0, "bright": 10.0, "dim": 20.0, "angle": 0.0, "hidden": false}],
				"tokens": [{"id": "", "name": "TokB", "actor_id": "", "actor_type": "npc", "img_ref": "", "x": 100.0, "y": 100.0, "width": 1.0, "height": 1.0, "scale": 1.0, "rotation": 0.0, "hidden": false, "disposition": -1, "actor_link": false, "sight_enabled": false, "sight_range": 0.0, "sight_angle": 360.0}],
			},
		],
		"actors": [], "assets": {}, "source_records": 8,
	}, b_emp, assets_scr.new(), null, h_emp, sdk.create_session(h_emp, {}), {})
	var w_emp: Dictionary = b_emp.get_world()
	results["iter2_empty_ids"] = {
		"ok": m_emp_res.get("ok", false),
		"v3_errs": _validate_world_v3_quick(w_emp),
		"entity_count": w_emp.get("entity_state", {}).get("entities", []).size(),
	}

	# 12. Iteration 3 Challenger regression cases (0 Godot ERRORs / WARNINGs)
	var anim_webp_bytes: PackedByteArray = Marshalls.base64_to_raw(str(cfg["anim_webp_b64"]))
	var bmp_os2_bytes: PackedByteArray = Marshalls.base64_to_raw(str(cfg["bmp_os2_b64"]))
	var bmp8_nopal_bytes: PackedByteArray = Marshalls.base64_to_raw(str(cfg["bmp8_nopal_b64"]))
	var bmp1_nopal_bytes: PackedByteArray = Marshalls.base64_to_raw(str(cfg["bmp1_nopal_b64"]))
	var bmp8_pal_bytes: PackedByteArray = Marshalls.base64_to_raw(str(cfg["bmp8_pal_b64"]))
	var jpg_no_dqt_bytes: PackedByteArray = Marshalls.base64_to_raw(str(cfg["jpg_no_dqt_b64"]))
	var svg_ns_bytes: PackedByteArray = Marshalls.base64_to_raw(str(cfg["svg_ns_b64"]))

	var src_anim := _MockAssetSource.new()
	src_anim.files["anim.webp"] = anim_webp_bytes
	var h_anim_skip := _ConfigurableMockHost.new()
	var s_anim_skip = sdk.create_session(h_anim_skip, {"skip_missing_assets": true})
	var ah_anim_skip: RefCounted = assets_scr.new()
	var r_anim_skip: Dictionary = ah_anim_skip.resolve_sprite_ref(
		"anim.webp",
		{"kind": "local", "ext": "webp", "resolved_path_or_url": "anim.webp"},
		src_anim,
		h_anim_skip,
		s_anim_skip,
		{"skip_missing_assets": true}
	)
	var h_anim_strict := _ConfigurableMockHost.new()
	var s_anim_strict = sdk.create_session(h_anim_strict, {"skip_missing_assets": false})
	var ah_anim_strict: RefCounted = assets_scr.new()
	var r_anim_strict: Dictionary = ah_anim_strict.resolve_sprite_ref(
		"anim.webp",
		{"kind": "local", "ext": "webp", "resolved_path_or_url": "anim.webp"},
		src_anim,
		h_anim_strict,
		s_anim_strict,
		{"skip_missing_assets": false}
	)

	var r_svg_ns: Dictionary = ah_reg.publish_local_bytes(svg_ns_bytes, "svg", h_reg, s_reg)
	var svg_ns_magic := ""
	if bool(r_svg_ns.get("ok", false)):
		var sname := str(r_svg_ns["sprite_path"]).substr(8)
		var sf := FileAccess.open(dest_reg.path_join("assets").path_join(sname), FileAccess.READ)
		if sf != null:
			svg_ns_magic = sf.get_buffer(8).hex_encode()
			sf.close()

	results["iter3_assets"] = {
		"anim_webp_pub": ah_reg.publish_local_bytes(anim_webp_bytes, "webp", h_reg, s_reg),
		"anim_webp_skip": r_anim_skip,
		"anim_webp_skip_warns": h_anim_skip.warnings.size(),
		"anim_webp_strict": r_anim_strict,
		"bmp_os2": ah_reg.publish_local_bytes(bmp_os2_bytes, "bmp", h_reg, s_reg),
		"bmp8_nopal": ah_reg.publish_local_bytes(bmp8_nopal_bytes, "bmp", h_reg, s_reg),
		"bmp1_nopal": ah_reg.publish_local_bytes(bmp1_nopal_bytes, "bmp", h_reg, s_reg),
		"bmp8_pal": ah_reg.publish_local_bytes(bmp8_pal_bytes, "bmp", h_reg, s_reg),
		"jpg_no_dqt": ah_reg.publish_local_bytes(jpg_no_dqt_bytes, "jpg", h_reg, s_reg),
		"svg_ns": r_svg_ns,
		"svg_ns_magic": svg_ns_magic,
	}

	# 13. Iteration 4 SVG regression cases (0 Godot ERRORs / WARNINGs)
	var svg_cdata_bytes := '<s:svg xmlns:s="http://www.w3.org/2000/svg" width="16" height="16"><s:style><![CDATA[.r { fill: #ff0000; }]]></s:style><s:rect class="r" width="16" height="16"/></s:svg>'.to_utf8_buffer()
	var svg_multipfx_bytes := '<s:svg xmlns:s="http://www.w3.org/2000/svg" xmlns:g="http://www.w3.org/2000/svg" width="16" height="16"><g:rect width="16" height="16" fill="#00ff00"/></s:svg>'.to_utf8_buffer()
	var svg_child_scoped_bytes := '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><g:rect xmlns:g="http://www.w3.org/2000/svg" width="16" height="16" fill="#0000ff"/></svg>'.to_utf8_buffer()
	var svg_unprefixed_multipfx_bytes := '<svg xmlns="http://www.w3.org/2000/svg" xmlns:g="http://www.w3.org/2000/svg" width="16" height="16"><g:rect width="16" height="16" fill="#ff00ff"/></svg>'.to_utf8_buffer()
	var svg_xlink_bytes := '<s:svg xmlns:s="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="16" height="16"><s:defs><s:rect id="r" width="16" height="16" fill="#00ff00"/></s:defs><s:use xlink:href="#r"/></s:svg>'.to_utf8_buffer()
	var svg_escaped_lt_bytes := '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" data-x="a &lt; b"><rect width="16" height="16" fill="#ff0000"/></svg>'.to_utf8_buffer()
	var svg_ns_escaped_lt_bytes := '<s:svg xmlns:s="http://www.w3.org/2000/svg" width="16" height="16" data-x="a &lt; b"><s:rect width="16" height="16" fill="#ff0000"/></s:svg>'.to_utf8_buffer()
	var svg_unclosed_attr_bytes := '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="8" <rect/></svg>'.to_utf8_buffer()
	var svg_unclosed_quote_bytes := '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="8 <rect/></svg>'.to_utf8_buffer()
	var svg_raw_lt_attr_bytes := '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" data-x="a < b"><rect width="16" height="16"/></svg>'.to_utf8_buffer()
	var svg_bad_roots := {
		"leading_colon": '<:svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16"/></:svg>'.to_utf8_buffer(),
		"double_colon": '<a:s:svg xmlns:a="http://www.w3.org/2000/svg" width="16" height="16"/>'.to_utf8_buffer(),
		"upper_svg": '<SVG xmlns="http://www.w3.org/2000/svg" width="16" height="16"/>'.to_utf8_buffer(),
		"upper_ns_svg": '<S:SVG xmlns:S="http://www.w3.org/2000/svg" width="16" height="16"/>'.to_utf8_buffer(),
		"wrong_ns": '<s:svg xmlns:s="http://example.com/not-svg" width="16" height="16"/>'.to_utf8_buffer(),
	}
	var iter4_good_inputs := {
		"cdata": svg_cdata_bytes,
		"multipfx": svg_multipfx_bytes,
		"child_scoped": svg_child_scoped_bytes,
		"unprefixed_multipfx": svg_unprefixed_multipfx_bytes,
		"xlink": svg_xlink_bytes,
		"escaped_lt": svg_escaped_lt_bytes,
		"ns_escaped_lt": svg_ns_escaped_lt_bytes,
	}
	var iter4_good_out := {}
	for gkey: String in iter4_good_inputs.keys():
		var gres: Dictionary = ah_reg.publish_local_bytes(iter4_good_inputs[gkey], "svg", h_reg, s_reg)
		var px := []
		if bool(gres.get("ok", false)):
			var gname := str(gres["sprite_path"]).substr(8)
			var gpath := dest_reg.path_join("assets").path_join(gname)
			var gimg := Image.new()
			if gimg.load_png_from_buffer(FileAccess.get_file_as_bytes(gpath)) == OK and not gimg.is_empty():
				var c := gimg.get_pixel(0, 0)
				px = [c.r8, c.g8, c.b8, c.a8]
		iter4_good_out[gkey] = {"res": gres, "px": px}
	var iter4_bad_roots_out := {}
	for bkey: String in svg_bad_roots.keys():
		iter4_bad_roots_out[bkey] = ah_reg.publish_local_bytes(svg_bad_roots[bkey], "svg", h_reg, s_reg)
	results["iter4_svg"] = {
		"good": iter4_good_out,
		"bad_roots": iter4_bad_roots_out,
		"unclosed_attr": ah_reg.publish_local_bytes(svg_unclosed_attr_bytes, "svg", h_reg, s_reg),
		"unclosed_quote": ah_reg.publish_local_bytes(svg_unclosed_quote_bytes, "svg", h_reg, s_reg),
		"raw_lt_attr": ah_reg.publish_local_bytes(svg_raw_lt_attr_bytes, "svg", h_reg, s_reg),
	}

	_write_json_out(out_path, {"ok": true, "results": results})
	quit(0)
'''


class TestFuvttMapperStaticHygiene(unittest.TestCase):
    def test_m4_gd_hygiene_and_plugin_json_contract(self) -> None:
        for rel in ("entry.gd", "src/fuvtt_assets.gd", "src/fuvtt_mapper.gd"):
            fpath = MOD_DIR / rel
            self.assertTrue(fpath.is_file(), f"Missing {fpath}")
            raw = fpath.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"{rel} must not contain UTF-8 BOM")
            self.assertNotIn(b"\r", raw, f"{rel} must use LF-only line endings")
            text = raw.decode("utf-8")
            self.assertTrue(text.startswith("extends RefCounted\n"), f"{rel} must start with 'extends RefCounted'")
            self.assertNotRegex(text, r"(?m)^\s*class_name\b", f"{rel} must not declare class_name")
            self.assertNotIn("preload(", text, f"{rel} must not call preload()")
            self.assertNotIn("JSON.parse_string", text, f"{rel} must not call JSON.parse_string")
            self.assertNotRegex(
                text,
                r"(?i)(?:[a-z]:\\\\Users\\\\|[a-z]:/Users/|/Users/|/home/|AppData[/\\\\]Local)",
                f"{rel} must not contain machine-local paths",
            )
            if rel.startswith("src/"):
                self.assertNotIn("load(", text, f"{rel} must not call cross-file load()")

        pj_path = MOD_DIR / "plugin.json"
        pj_raw = pj_path.read_bytes()
        self.assertFalse(pj_raw.startswith(b"\xef\xbb\xbf"), "plugin.json must not contain UTF-8 BOM")
        self.assertNotIn(b"\r", pj_raw, "plugin.json must use LF-only line endings")
        manifest = json.loads(pj_raw.decode("utf-8"))
        by_id = {s["id"]: s for s in manifest["settings"]}
        self.assertEqual(set(by_id.keys()), EXPECTED_SETTING_IDS)


class TestFuvttMapperWithGodot(unittest.TestCase):
    run_dir: Path
    probe_dir: Path
    godot_bin: Path
    results: dict
    bgdia_dir_wj: Path | None
    bgdia_zip: Path | None

    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_WORKSPACE_ROOT)
        if cfg.godot_bin is None or not cfg.godot_bin.is_file():
            raise unittest.SkipTest("GODOT_BIN not configured or unavailable")
        try:
            ver = subprocess.run(
                [str(cfg.godot_bin), "--headless", "--quit", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise unittest.SkipTest(f"GODOT_BIN cannot be executed: {exc}") from exc
        if ver.returncode != 0:
            raise unittest.SkipTest(f"GODOT_BIN --version exited {ver.returncode}")

        cls.godot_bin = cfg.godot_bin
        cls.run_dir = TEST_TMP_ROOT / f"fuvtt_mapper_{uuid.uuid4().hex[:10]}"
        cls.probe_dir = cls.run_dir / "probe_project"
        try:
            cls._prepare_and_run()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def _prepare_and_run(cls) -> None:
        import base64

        cls.probe_dir.mkdir(parents=True, exist_ok=True)
        (cls.probe_dir / "project.godot").write_text(
            'config_version=5\n\n[application]\nconfig/name="fuvtt_mapper_test"\n',
            encoding="utf-8",
            newline="\n",
        )
        mod_copy = cls.probe_dir / "mods" / "fvtt-world-importer"
        (mod_copy / "src").mkdir(parents=True, exist_ok=True)
        shutil.copy2(MOD_DIR / "plugin.json", mod_copy / "plugin.json")
        shutil.copy2(MOD_DIR / "entry.gd", mod_copy / "entry.gd")
        for gd in SRC_DIR.glob("*.gd"):
            shutil.copy2(gd, mod_copy / "src" / gd.name)

        sdk_copy = cls.probe_dir / "shared" / "sdk" / "fu_sdk"
        (sdk_copy / "adapters").mkdir(parents=True, exist_ok=True)
        shutil.copy2(SDK_DIR / "v1.gd", sdk_copy / "v1.gd")
        shutil.copy2(SDK_DIR / "adapters" / "host_v1_adapter.gd", sdk_copy / "adapters" / "host_v1_adapter.gd")

        (cls.probe_dir / "probe.gd").write_text(_PROBE_GD, encoding="utf-8", newline="\n")

        png = make_png_bytes(4, 4)
        bmp = make_bmp_bytes(2, 2)
        bmp24_td = make_bmp_bytes(4, 4, bpp=24, top_down=True)
        bmp32_td = make_bmp_bytes(4, 4, bpp=32, top_down=True)
        bmp32_bu = make_bmp_bytes(4, 4, bpp=32, top_down=False)
        svg = make_svg_bytes(16, 16)

        png_bad_crc = bytearray(png)
        png_bad_crc[30] ^= 0xFF
        jpg_sof_corrupt = (
            b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x04\x00\x04\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01\xff\xda\x12\x34"
        )
        webp_vp8_trunc = b"RIFF\x20\x00\x00\x00WEBPVP8 \x0a\x00\x00\x00\x00\x00\x00\x9d\x01\x2a\x04\x00\x04\x00"
        webp_vp8x_trunc = b"RIFF\x16\x00\x00\x00WEBPVP8X\x0a\x00\x00\x00\x00\x00\x00\x00\x03\x00\x00\x03\x00\x00"
        vp8l_trunc = b"RIFF\x11\x00\x00\x00WEBPVP8L\x05\x00\x00\x00\x2f\x03\x00\x00\x00"

        anim_webp = make_animated_webp_bytes()
        bmp_os2 = make_os2_bmp_bytes(2, 2)
        bmp8_nopal = make_paletteless_indexed_bmp_bytes(bpp=8, width=2, height=2)
        bmp1_nopal = make_paletteless_indexed_bmp_bytes(bpp=1, width=2, height=2)
        bmp8_pal = make_indexed_bmp_with_palette_bytes(bpp=8, width=2, height=2)
        jpg_no_dqt = (
            b"\xff\xd8"
            b"\xff\xc0\x00\x0b\x08\x00\x02\x00\x02\x01\x01\x11\x00"
            b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00"
            b"\x01\x02\x03"
            b"\xff\xd9"
        )
        svg_ns = (
            b'<s:svg xmlns:s="http://www.w3.org/2000/svg" width="16" height="16">'
            b'<s:rect width="8" height="8" fill="#336699"/></s:svg>'
        )

        hostile_dir = cls.run_dir / "hostile_world"
        hostile_wj = build_v9_world(
            hostile_dir,
            world_json=make_v9_world_json(name="hw", title="Hostile World"),
            scenes=[make_v9_scene("s1", "Remote Scene", img="https://example.com/hostile_bg.png")],
            actors=[
                make_v9_actor("pc1", "HeroPC", actor_type="character"),
                make_v9_actor("npc1", "TrollNPC", actor_type="npc"),
            ],
        )

        cls.bgdia_dir_wj = resolve_bgdia_dir_world_json(workspace_root=_WORKSPACE_ROOT)
        cls.bgdia_zip = resolve_bgdia_zip_path(workspace_root=_WORKSPACE_ROOT)

        cfg_payload = {
            "run_dir": str(cls.run_dir),
            "png_b64": base64.b64encode(png).decode("ascii"),
            "bmp_b64": base64.b64encode(bmp).decode("ascii"),
            "bmp24_td_b64": base64.b64encode(bmp24_td).decode("ascii"),
            "bmp32_td_b64": base64.b64encode(bmp32_td).decode("ascii"),
            "bmp32_bu_b64": base64.b64encode(bmp32_bu).decode("ascii"),
            "svg_b64": base64.b64encode(svg).decode("ascii"),
            "png_only_ihdr_b64": base64.b64encode(png[:33]).decode("ascii"),
            "png_bad_crc_b64": base64.b64encode(bytes(png_bad_crc)).decode("ascii"),
            "png_trunc_idat_b64": base64.b64encode(png[:45]).decode("ascii"),
            "bad_ct_png_b64": base64.b64encode(make_bad_ct_png_bytes()).decode("ascii"),
            "jpg_sof_corrupt_b64": base64.b64encode(jpg_sof_corrupt).decode("ascii"),
            "webp_vp8_trunc_b64": base64.b64encode(webp_vp8_trunc).decode("ascii"),
            "webp_vp8x_trunc_b64": base64.b64encode(webp_vp8x_trunc).decode("ascii"),
            "vp8l_trunc_b64": base64.b64encode(vp8l_trunc).decode("ascii"),
            "anim_webp_b64": base64.b64encode(anim_webp).decode("ascii"),
            "bmp_os2_b64": base64.b64encode(bmp_os2).decode("ascii"),
            "bmp8_nopal_b64": base64.b64encode(bmp8_nopal).decode("ascii"),
            "bmp1_nopal_b64": base64.b64encode(bmp1_nopal).decode("ascii"),
            "bmp8_pal_b64": base64.b64encode(bmp8_pal).decode("ascii"),
            "jpg_no_dqt_b64": base64.b64encode(jpg_no_dqt).decode("ascii"),
            "svg_ns_b64": base64.b64encode(svg_ns).decode("ascii"),
            "hostile_wj": str(hostile_wj),
            "bgdia_dir_wj": str(cls.bgdia_dir_wj) if (cls.bgdia_dir_wj and cls.bgdia_dir_wj.is_file()) else "",
            "bgdia_zip": str(cls.bgdia_zip) if (cls.bgdia_zip and cls.bgdia_zip.is_file()) else "",
        }
        cfg_path = cls.run_dir / "probe_cfg.json"
        out_path = cls.run_dir / "probe_out.json"
        write_json_file(cfg_path, cfg_payload)

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
                str(cls.godot_bin),
                "--headless",
                "--quit",
                "--path",
                str(cls.probe_dir),
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
            timeout=240,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log_text = godot_log.read_text(encoding="utf-8", errors="replace") if godot_log.is_file() else ""
        log_errors = analyze_godot_logs(log_text, proc.stdout, proc.stderr)
        combined_logs = f"{log_text}\n{proc.stdout}\n{proc.stderr}"
        if "WARNING: Reading less data than requested" in combined_logs:
            log_errors.append("WARNING: Reading less data than requested")
        if proc.returncode != 0 or log_errors:
            redacted = redact_bgdia_path(
                f"rc={proc.returncode} errors={log_errors}\nstdout={proc.stdout[-800:]}\nstderr={proc.stderr[-800:]}",
                bgdia_dir_world_json=cls.bgdia_dir_wj,
                bgdia_zip_path=cls.bgdia_zip,
            )
            raise AssertionError(f"Headless Godot probe failed or emitted ERROR logs:\n{redacted}")

        parsed = json.loads(out_path.read_text(encoding="utf-8"))
        if not parsed.get("ok"):
            raise AssertionError(f"Probe returned failure: {parsed}")
        cls.results = parsed["results"]

    @classmethod
    def tearDownClass(cls) -> None:
        run_dir = getattr(cls, "run_dir", None)
        if run_dir is not None and run_dir.exists():
            for _ in range(5):
                shutil.rmtree(run_dir, ignore_errors=True)
                if not run_dir.exists():
                    break
                time.sleep(0.05)

    def test_assets_valid_formats_and_conversions(self) -> None:
        r = self.results["assets_formats"]
        for k, ext in (("png", ".png"), ("jpg", ".jpg"), ("webp", ".webp"), ("bmp", ".png"), ("svg", ".png")):
            self.assertTrue(r[k]["ok"], f"{k} failed: {r[k]}")
            self.assertTrue(r[k]["sprite_path"].startswith("asset://"), r[k])
            self.assertTrue(r[k]["sprite_path"].endswith(ext), r[k])
        self.assertEqual(r["bmp_magic"], "89504e470d0a1a0a")
        self.assertFalse(r["xxe"]["ok"])
        self.assertFalse(r["big"]["ok"])

    def test_assets_gif_and_corrupt_bytes_zero_godot_errors(self) -> None:
        r = self.results["assets_gif_corrupt"]
        self.assertTrue(r["gif_skip"]["ok"])
        self.assertEqual(r["gif_skip"]["status"], "unsupported")
        self.assertEqual(r["gif_skip"]["sprite_path"], "")
        self.assertGreaterEqual(r["gif_skip_warns"], 1)
        self.assertFalse(r["gif_strict"]["ok"])
        self.assertFalse(r["gif_magic"]["ok"])
        self.assertFalse(r["empty"]["ok"])
        self.assertFalse(r["rand"]["ok"])
        self.assertFalse(r["trunc_png"]["ok"])

    def test_assets_remote_archive_ok_and_fail(self) -> None:
        r = self.results["assets_remote"]
        self.assertTrue(r["ok1"]["ok"])
        self.assertTrue(r["ok1"]["sprite_path"].startswith("asset://"))
        self.assertEqual(r["ok1"]["sprite_path"], r["ok2"]["sprite_path"])
        self.assertEqual(r["archived_count"], 1)
        self.assertEqual(r["requests"][0]["proxy"], "http://127.0.0.1:8080")
        self.assertTrue(r["fail_skip"]["ok"])
        self.assertEqual(r["fail_skip"]["sprite_path"], "")
        self.assertFalse(r["fail_strict"]["ok"])
        self.assertTrue(r["disabled"]["ok"])
        self.assertEqual(r["disabled"]["sprite_path"], "")
        self.assertEqual(r["disabled_urls"], 0)

    def test_mapper_walls_doors_windows_and_degenerate_skip(self) -> None:
        r = self.results["mapper_walls"]
        self.assertTrue(r["ok"])
        self.assertEqual(r["v3_errs"], [])
        self.assertEqual(r["kinds"].get("wall", 0), 1)
        self.assertEqual(r["kinds"].get("door", 0), 3)
        self.assertEqual(r["kinds"].get("window", 0), 1)
        self.assertEqual(len(r["ring_sizes"]), 5)
        for sz in r["ring_sizes"]:
            self.assertEqual(sz, 4)
        self.assertEqual(sorted(r["door_opens"]), [False, False, True])
        self.assertGreaterEqual(len(r["warnings"]), 2)

    def test_mapper_lights_fallback_color_and_grid_scaling(self) -> None:
        r = self.results["mapper_lights_grid"]
        self.assertEqual(r["v3_errs"], [])
        lt = r["light"]
        self.assertEqual(lt["ent_alpha"], 0.0)
        self.assertEqual(lt["vis_alpha"], 0.0)
        self.assertFalse(lt["show_fallback"])
        self.assertAlmostEqual(lt["view_angle"], 360.0, places=2)
        self.assertAlmostEqual(lt["radius"], 512.0, places=2)
        self.assertLess(lt["pos_x"], 0.0)

        # ScaledTok: scene grid=50 -> scene_scale=2.0 -> center=(100+25)*2=250 -> *0.64 = 160.0
        # GridlessTok: grid_type=0 -> scene_scale=1.0 -> center=(100+35)*1=135 -> *0.64 = 86.4
        self.assertAlmostEqual(r["tok_positions"]["ScaledTok"][0], 160.0, places=2)
        self.assertAlmostEqual(r["tok_positions"]["GridlessTok"][0], 86.4, places=2)

        self.assertEqual(r["ga_version"], 1)
        self.assertEqual(
            set(r["ga_keys"]),
            {"schema", "version", "cell_size", "offset", "color", "line_width", "snap_enabled", "snap_strength"},
        )
        self.assertEqual(r["ga_state"]["schema"], "fus.grid_alignment.config")
        self.assertAlmostEqual(r["ga_state"]["cell_size"], 64.0, places=2)

    def test_mapper_floor0_rename_and_512_10000_caps(self) -> None:
        r = self.results["mapper_floors_caps"]
        self.assertEqual(r["f_v3_errs"], [])
        self.assertEqual(r["fl_names"], ["S1", "S2"])
        self.assertEqual(r["active_uid"], r["fl_uids"][1])
        self.assertEqual(r["member_floors"], [r["fl_uids"][0], r["fl_uids"][1]])
        self.assertEqual(r["z_floor0_name"], "1F")
        self.assertEqual(r["z_entities"], 1)
        self.assertEqual(r["z_v3_errs"], [])
        self.assertEqual(r["cap512_count"], 512)
        self.assertGreaterEqual(r["cap512_warns"], 1)
        self.assertEqual(r["cap10k_count"], 10000)
        self.assertGreaterEqual(r["cap10k_warns"], 1)
        self.assertEqual(r["cap10k_v3_errs"], [])

    def test_mapper_world_modules_budget_trimming(self) -> None:
        r = self.results["mapper_budget"]
        self.assertEqual(r["v3_errs"], [])
        self.assertLessEqual(r["entry_var_bytes"], 6 * 1024 * 1024)
        self.assertLessEqual(r["entry_bounded"], 6 * 1024 * 1024)
        if r["first_bio_len"] >= 0:
            self.assertLessEqual(r["first_bio_len"], 2048)
        self.assertGreaterEqual(len(r["warns"]), 1)

    def test_mapper_entity_library_gate_with_mock_host(self) -> None:
        r = self.results["mapper_entity_lib"]
        self.assertEqual(r["none_count"], 0)
        self.assertEqual(r["bad_count"], 0)
        self.assertEqual(r["ok_count"], 1)
        self.assertEqual(r["stored_keys"], 3)  # 2 nested folders + 1 unit

    def test_entry_hostile_variant_options_and_cancellation(self) -> None:
        r = self.results["entry_hostile_cancel"]
        self.assertTrue(r["hostile_ok"])
        self.assertEqual(r["hostile_v3_errs"], [])
        self.assertEqual(r["hostile_units"], ["TrollNPC"])
        for pval in r["proxy_vals"]:
            self.assertEqual(pval, "")
        for pol, cres in r["cancel_results"].items():
            self.assertEqual(cres, {"ok": False, "reason": "cancelled"}, f"policy {pol} -> {cres}")
        self.assertEqual(r["geom_fail_res"], {"ok": False, "reason": "geometry_preview_failed"})
        self.assertTrue(r["existed_after_pub"])
        self.assertFalse(r["existed_after_cleanup"])

    def test_entry_bgdia_dir_and_zip_if_configured(self) -> None:
        bgdia = self.results.get("bgdia", {})
        if not bgdia:
            self.skipTest("Neither FUVTT_BGDIA_DIR nor FUVTT_BGDIA_ZIP is configured")
        for bkey, bres in bgdia.items():
            self.assertTrue(bres["ins_ok"], bkey)
            self.assertGreater(bres["ins_decoded_bytes"], 0, bkey)
            self.assertGreaterEqual(bres["ins_counts"]["maps"], 31, bkey)
            self.assertTrue(bres["prep_ok"], bkey)
            self.assertEqual(bres["floors"], 31, bkey)
            self.assertGreaterEqual(bres["units"], 618, bkey)
            self.assertLessEqual(bres["serialized_bytes"], 30 * 1024 * 1024, bkey)
            self.assertEqual(bres["roundtrip_diff"], "", bkey)
            self.assertEqual(bres["v3_errs"], [], bkey)

    def test_assets_regression_malformed_svg_topdown_bmp_and_corrupt_headers(self) -> None:
        r = self.results["iter2_assets"]
        self.assertFalse(r["store_has_rootfor"])
        for skey in ("svg_malformed", "svg_unclosed", "svg_mismatch", "svg_bad_utf8"):
            self.assertFalse(r[skey]["ok"], f"{skey} must fail cleanly: {r[skey]}")
        for bkey in ("bmp24_td", "bmp32_td", "bmp32_bu"):
            self.assertTrue(r[bkey]["ok"], f"{bkey} failed: {r[bkey]}")
            self.assertTrue(r[bkey]["sprite_path"].startswith("asset://"), r[bkey])
            self.assertTrue(r[bkey]["sprite_path"].endswith(".png"), r[bkey])
        for ckey, cres in r["corrupt"].items():
            self.assertFalse(cres["ok"], f"{ckey} must fail cleanly: {cres}")

    def test_mapper_2500_actors_world_module_bounded_budget(self) -> None:
        r = self.results["iter2_2500"]
        self.assertTrue(r["ok"])
        self.assertEqual(r["v3_errs"], [])
        self.assertLessEqual(r["mods_bounded"], 8 * 1024 * 1024)
        self.assertLessEqual(r["mods_var_bytes"], 8 * 1024 * 1024)
        if r["has_importer_mod"]:
            self.assertLessEqual(r["imp_entry_bounded"], 6 * 1024 * 1024)

    def test_mapper_two_empty_scene_ids_unique_entities(self) -> None:
        r = self.results["iter2_empty_ids"]
        self.assertTrue(r["ok"])
        self.assertEqual(r["v3_errs"], [])
        self.assertEqual(r["entity_count"], 6)

    def test_assets_regression_iter3_challenger_findings(self) -> None:
        r = self.results["iter3_assets"]

        # 1. Animated WebP rejected cleanly as unsupported=true, and skipped/failed per skip_missing_assets
        self.assertFalse(r["anim_webp_pub"]["ok"])
        self.assertTrue(r["anim_webp_pub"]["unsupported"])
        self.assertEqual(r["anim_webp_pub"]["reason"], "unsupported_image_format:animated_webp")
        self.assertTrue(r["anim_webp_skip"]["ok"])
        self.assertEqual(r["anim_webp_skip"]["sprite_path"], "")
        self.assertEqual(r["anim_webp_skip"]["status"], "unsupported")
        self.assertGreaterEqual(r["anim_webp_skip_warns"], 1)
        self.assertFalse(r["anim_webp_strict"]["ok"])
        self.assertEqual(r["anim_webp_strict"]["reason"], "unsupported_image_format:animated_webp")

        # 2. OS/2 v1 BMP (dib_size == 12) rejected cleanly as unsupported=true
        self.assertFalse(r["bmp_os2"]["ok"])
        self.assertTrue(r["bmp_os2"]["unsupported"])
        self.assertEqual(r["bmp_os2"]["reason"], "unsupported_bmp_os2")

        # 3. Palette-less 8-bit & 1-bit indexed BMPs rejected cleanly without Godot WARNING; valid palette BMP succeeds
        self.assertFalse(r["bmp8_nopal"]["ok"])
        self.assertEqual(r["bmp8_nopal"]["reason"], "missing_bmp_palette")
        self.assertFalse(r["bmp1_nopal"]["ok"])
        self.assertEqual(r["bmp1_nopal"]["reason"], "missing_bmp_palette")
        self.assertTrue(r["bmp8_pal"]["ok"], r["bmp8_pal"])
        self.assertTrue(r["bmp8_pal"]["sprite_path"].startswith("asset://"))
        self.assertTrue(r["bmp8_pal"]["sprite_path"].endswith(".png"))

        # 4. JPEG lacking DQT rejected cleanly
        self.assertFalse(r["jpg_no_dqt"]["ok"])
        self.assertEqual(r["jpg_no_dqt"]["reason"], "missing_jpg_dqt")

        # 5. Namespaced <s:svg> accepted and transcoded to PNG
        self.assertTrue(r["svg_ns"]["ok"], r["svg_ns"])
        self.assertTrue(r["svg_ns"]["sprite_path"].startswith("asset://"))
        self.assertTrue(r["svg_ns"]["sprite_path"].endswith(".png"))
        self.assertEqual(r["svg_ns_magic"], "89504e470d0a1a0a")

    def test_assets_regression_iter4_svg_findings(self) -> None:
        r = self.results["iter4_svg"]
        expected_px = {
            "cdata": [255, 0, 0, 255],
            "multipfx": [0, 255, 0, 255],
            "child_scoped": [0, 0, 255, 255],
            "unprefixed_multipfx": [255, 0, 255, 255],
            "xlink": [0, 255, 0, 255],
            "escaped_lt": [255, 0, 0, 255],
            "ns_escaped_lt": [255, 0, 0, 255],
        }
        for k, px in expected_px.items():
            entry = r["good"][k]
            self.assertTrue(entry["res"]["ok"], f"{k} failed: {entry}")
            self.assertTrue(entry["res"]["sprite_path"].startswith("asset://"), entry)
            self.assertTrue(entry["res"]["sprite_path"].endswith(".png"), entry)
            self.assertEqual(entry["px"], px, f"{k} unexpected pixel: {entry}")

        for bk, bres in r["bad_roots"].items():
            self.assertFalse(bres["ok"], f"{bk} must fail cleanly: {bres}")
            self.assertEqual(bres["reason"], "missing_svg_root", f"{bk} -> {bres}")

        for mkey in ("unclosed_attr", "unclosed_quote", "raw_lt_attr"):
            self.assertFalse(r[mkey]["ok"], f"{mkey} must fail cleanly: {r[mkey]}")
            self.assertEqual(r[mkey]["reason"], "malformed_svg_xml", f"{mkey} -> {r[mkey]}")


class TestFuvttMapperPackagedHost(unittest.TestCase):
    cfg = None
    tmp_dir: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = load_config(_WORKSPACE_ROOT)
        if cls.cfg.godot_bin is None or not cls.cfg.godot_bin.is_file():
            raise unittest.SkipTest("GODOT_BIN not configured or unavailable")
        try:
            ver = subprocess.run(
                [str(cls.cfg.godot_bin), "--headless", "--quit", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise unittest.SkipTest(f"GODOT_BIN cannot be executed: {exc}") from exc
        if ver.returncode != 0:
            raise unittest.SkipTest(f"GODOT_BIN --version exited {ver.returncode}")

        vrep = validate_mod_dir(MOD_DIR, mod_name="fvtt-world-importer", sdk_dir=SDK_DIR)
        if not vrep.ok:
            raise AssertionError(f"validate_mod_dir failed: {vrep.errors}")
        artifact = build_mod("fvtt-world-importer", config=cls.cfg, bump_dev=False)
        zerrs = validate_zip_archive(artifact.zip_path)
        if zerrs:
            raise AssertionError(f"validate_zip_archive failed: {zerrs}")

        cls.tmp_dir = TEST_TMP_ROOT / f"fuvtt_mapper_pkg_{uuid.uuid4().hex[:10]}"
        cls.tmp_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        tmp_dir = getattr(cls, "tmp_dir", None)
        if tmp_dir is not None and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def _run_verify_and_cleanup(self, sample_path: Path):
        vres = verify_mod_with_host("fvtt-world-importer", config=self.cfg, sample_path=sample_path, timeout_seconds=180)
        report_data = json.loads(vres.report_path.read_text(encoding="utf-8-sig")) if vres.report_path.is_file() else {}
        if vres.evidence_dir.exists():
            shutil.rmtree(vres.evidence_dir, ignore_errors=True)
        return vres, report_data

    def test_verify_host_synthetic_v9_zip_and_v14_dir(self) -> None:
        png = make_png_bytes(4, 4)
        bmp = make_bmp_bytes(2, 2)
        svg = make_svg_bytes(16, 16)
        gif = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"

        v9_dir = self.tmp_dir / "v9_pkg"
        build_v9_world(
            v9_dir,
            world_json=make_v9_world_json(name="v9pkg", title="Packaged V9"),
            scenes=[
                make_v9_scene(
                    "s1",
                    "V9 Scene",
                    img="worlds/v9pkg/bg.bmp",
                    walls=[
                        make_wall("w1", [0, 0, 200, 0], door=0),
                        make_wall("d1", [200, 0, 300, 0], door=1, ds=0),
                        make_wall("wn1", [300, 0, 400, 0], door=0, move=20, sight=0, light=0),
                    ],
                    lights=[make_light("lt1", 100, 100, bright=20, dim=40, angle=0)],
                    tiles=[make_tile("tl1", "worlds/v9pkg/tile.svg")],
                    tokens=[
                        make_v9_token("tk1", "Hero", actor_id="pc1", img="worlds/v9pkg/tok.png"),
                        make_v9_token("tk2", "Anim", actor_id="npc1", img="worlds/v9pkg/anim.gif"),
                    ],
                )
            ],
            actors=[
                make_v9_actor("pc1", "Hero", actor_type="character", img="worlds/v9pkg/tok.png"),
                make_v9_actor("npc1", "Goblin", actor_type="npc", img="worlds/v9pkg/anim.gif"),
            ],
            assets={"bg.bmp": bmp, "tile.svg": svg, "tok.png": png, "anim.gif": gif},
        )
        v9_zip = pack_world_zip(v9_dir, self.tmp_dir / "v9_pkg.zip", depth=1, root_name="v9pkg")
        vres9, rep9 = self._run_verify_and_cleanup(v9_zip)
        self.assertTrue(vres9.ok, f"verify-host v9 zip failed: {vres9.failures} logs={vres9.log_errors}")
        self.assertEqual(vres9.log_errors, [])
        self.assertGreater(vres9.serialized_bytes, 0)
        self.assertTrue(rep9.get("inspect_summary", {}).get("ok"))
        self.assertGreaterEqual(rep9.get("inspect_summary", {}).get("counts", {}).get("maps", 0), 1)
        self.assertGreaterEqual(rep9.get("prepare_counts", {}).get("entities", 0), 1)

        v14_dir = self.tmp_dir / "v14_pkg"
        v14_wj = build_v14_world(
            v14_dir,
            world_json=make_v14_world_json(world_id="v14pkg", title="Packaged V14"),
            scenes=[make_v9_scene("s1", "V14 Scene", img="worlds/v14pkg/bg.png")],
            actors=[make_v9_actor("pc1", "Hero14", actor_type="character")],
            folders=[make_folder("fl1", "Heroes")],
            assets={"bg.png": png},
        )
        vres14, _ = self._run_verify_and_cleanup(v14_wj)
        self.assertTrue(vres14.ok, f"verify-host v14 dir failed: {vres14.failures} logs={vres14.log_errors}")
        self.assertEqual(vres14.log_errors, [])

    def test_verify_host_negative_samples_clean_fail(self) -> None:
        bad_zip = self.tmp_dir / "corrupt.zip"
        bad_zip.write_bytes(b"NOT_A_ZIP_ARCHIVE")
        vres_z, rep_z = self._run_verify_and_cleanup(bad_zip)
        self.assertFalse(vres_z.ok)
        self.assertEqual(vres_z.exit_code, 1)
        self.assertFalse(rep_z.get("inspect_summary", {}).get("ok", True))
        for le in vres_z.log_errors:
            self.assertIn("FUVTT_VERIFY_HOST CHECK_FAIL:", le)
            self.assertNotIn("SCRIPT ERROR", le)
            self.assertNotIn("ObjectDB", le)

        gw_json = self.tmp_dir / "gateway.json"
        write_json_file(gw_json, {"gateway": "https://example.invalid"})
        vres_g, rep_g = self._run_verify_and_cleanup(gw_json)
        self.assertFalse(vres_g.ok)
        self.assertEqual(vres_g.exit_code, 1)
        self.assertFalse(rep_g.get("inspect_summary", {}).get("ok", True))
        for le in vres_g.log_errors:
            self.assertIn("FUVTT_VERIFY_HOST CHECK_FAIL:", le)
            self.assertNotIn("SCRIPT ERROR", le)
            self.assertNotIn("ObjectDB", le)

    def test_verify_host_bgdia_if_configured(self) -> None:
        bgdia_dir_wj = resolve_bgdia_dir_world_json(workspace_root=_WORKSPACE_ROOT)
        bgdia_zip = resolve_bgdia_zip_path(workspace_root=_WORKSPACE_ROOT)
        if not ((bgdia_dir_wj and bgdia_dir_wj.is_file()) or (bgdia_zip and bgdia_zip.is_file())):
            self.skipTest("Neither FUVTT_BGDIA_DIR nor FUVTT_BGDIA_ZIP is configured")
        if bgdia_dir_wj and bgdia_dir_wj.is_file():
            vres_d, _ = self._run_verify_and_cleanup(bgdia_dir_wj)
            self.assertTrue(vres_d.ok, redact_bgdia_path(str(vres_d.failures), bgdia_dir_world_json=bgdia_dir_wj))
            self.assertEqual(vres_d.log_errors, [])
            self.assertGreater(vres_d.serialized_bytes, 0)
        if bgdia_zip and bgdia_zip.is_file():
            vres_z, _ = self._run_verify_and_cleanup(bgdia_zip)
            self.assertTrue(vres_z.ok, redact_bgdia_path(str(vres_z.failures), bgdia_zip_path=bgdia_zip))
            self.assertEqual(vres_z.log_errors, [])
            self.assertGreater(vres_z.serialized_bytes, 0)


if __name__ == "__main__":
    unittest.main()
