"""Tier 5 White-Box Adversarial Tests.

Covers:
1. Challenger 1 gaps: error propagation (`zip_*`, `:snappy_`, `:block_`, `< 11` NeDB fallback),
   ZIP structural & RFC 1951 edge cases (duplicate CD, Data Descriptor, LFH/CD extra diff, ZIP64,
   encrypted, unsupported method, ratio bomb, 15-bit slow-path Huffman, multi-block BTYPE=2->1->0,
   empty distance tree), LevelDB multi-block Snappy & equal-seq `(seq, vt)` collision & Snappy
   edge cases, Normalizer extreme coords (`INF`/`grid < 0`), heavy armor negative DEX & dual armor
   ranking, `_strip_html` `<script>`/`<style>`/literal `<`, and depth-60 + cyclic assigned folders.
2. Challenger 2 gaps: `fuvtt_mapper.gd` direct `map_to_world()` with `null`/`NAN`/`INF`/`1e20` walls,
   `entity-library` failure paths & mid-loop/post-map cancel rollback, gridless-only `grid_alignment`
   & `4600`-actor module omission, `fuvtt_assets.gd` corrupt ZIP image error propagation, BMP
   `BI_BITFIELDS` offset validation & publish rollback, SVG unquoted/self-closing/PI/namespace
   variants, and `entry.gd` hard `:snappy_` / `:block_` error + `null` host handling.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
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
from fuvtt_devtools.host_verifier import analyze_godot_logs  # noqa: E402
from e2e_fvtt_importer.fixtures import (  # noqa: E402
    _encode_varint32,
    build_manifest_bytes,
    build_sstable_bytes,
    build_v14_world,
    build_v9_world,
    build_wal_bytes,
    encode_write_batch,
    leveldb_masked_crc32c,
    make_armor_item,
    make_folder,
    make_png_bytes,
    make_v14_world_json,
    make_v9_actor,
    make_v9_scene,
    make_v9_token,
    make_v9_world_json,
    make_wall,
    resolve_bgdia_dir_world_json,
    write_json_file,
)

TEST_TMP_ROOT = _WORKSPACE_ROOT / ".cache" / "test_tmp"
MOD_ENTRY_GD = (_WORKSPACE_ROOT / "mods" / "fvtt-world-importer" / "entry.gd").as_posix()
SRC_DIR = (_WORKSPACE_ROOT / "mods" / "fvtt-world-importer" / "src").as_posix()
SDK_GD = (_WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk" / "v1.gd").as_posix()


class _BitWriter:
    def __init__(self) -> None:
        self.buf = bytearray()
        self.acc = 0
        self.bits = 0

    def write_lsb(self, val: int, n: int) -> None:
        for i in range(n):
            self.acc |= ((val >> i) & 1) << self.bits
            self.bits += 1
            if self.bits == 8:
                self.buf.append(self.acc)
                self.acc = 0
                self.bits = 0

    def write_msb(self, val: int, n: int) -> None:
        for i in range(n - 1, -1, -1):
            self.acc |= ((val >> i) & 1) << self.bits
            self.bits += 1
            if self.bits == 8:
                self.buf.append(self.acc)
                self.acc = 0
                self.bits = 0

    def align_byte(self) -> None:
        if self.bits > 0:
            self.buf.append(self.acc)
            self.acc = 0
            self.bits = 0

    def finish(self) -> bytes:
        self.align_byte()
        return bytes(self.buf)


def _canonical_codes(lengths: list[int]) -> dict[int, tuple[int, int]]:
    bl_count = [0] * 16
    for ln in lengths:
        if ln > 0:
            bl_count[ln] += 1
    code = 0
    next_code = [0] * 16
    for bits in range(1, 16):
        code = (code + bl_count[bits - 1]) << 1
        next_code[bits] = code
    codes: dict[int, tuple[int, int]] = {}
    for sym, ln in enumerate(lengths):
        if ln > 0:
            codes[sym] = (next_code[ln], ln)
            next_code[ln] += 1
    return codes


def _deflate_raw(data: bytes) -> bytes:
    co = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    return co.compress(data) + co.flush()


def _build_raw_zip(path: Path, specs: list[dict], *, eocd_override: dict | None = None) -> None:
    buf = bytearray()
    cds = []
    for sp in specs:
        nb = sp["name_bytes"]
        payload = sp["payload"]
        method = sp.get("comp_method", 8)
        flags = sp.get("flags", 0)
        crc = sp.get("crc", zlib.crc32(payload) & 0xFFFFFFFF)
        usize = sp.get("uncomp_size", len(payload))
        comp = sp["comp_bytes"] if "comp_bytes" in sp else (payload if method == 0 else _deflate_raw(payload))
        csize = sp.get("comp_size", len(comp))
        lfh_off = len(buf)
        lfh_ex = sp.get("lfh_extra", b"")
        cd_ex = sp.get("cd_extra", b"")
        lfh_crc = 0 if (flags & 0x0008) else crc
        lfh_csz = 0 if (flags & 0x0008) else csize
        lfh_usz = 0 if (flags & 0x0008) else usize
        buf.extend(struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, flags, method, 0, 0, lfh_crc, lfh_csz, lfh_usz, len(nb), len(lfh_ex)))
        buf.extend(nb + lfh_ex + comp)
        if flags & 0x0008:
            if sp.get("dd_sig", True):
                buf.extend(struct.pack("<IIII", 0x08074B50, crc, csize, usize))
            else:
                buf.extend(struct.pack("<III", crc, csize, usize))
        cds.append((nb, flags, method, crc, csize, usize, lfh_off, cd_ex))
    cd_off = len(buf)
    for nb, flags, method, crc, csize, usize, lfh_off, cd_ex in cds:
        buf.extend(struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, flags, method, 0, 0, crc, csize, usize, len(nb), len(cd_ex), 0, 0, 0, 0, lfh_off))
        buf.extend(nb + cd_ex)
    cd_sz = len(buf) - cd_off
    n_ent = len(cds)
    if eocd_override:
        n_ent = eocd_override.get("total_entries", n_ent)
        cd_sz = eocd_override.get("cd_size", cd_sz)
        cd_off = eocd_override.get("cd_offset", cd_off)
    buf.extend(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, n_ent, n_ent, cd_sz, cd_off, 0))
    path.write_bytes(bytes(buf))


def _make_bitfields_bmp(
    width: int = 2,
    height: int = 2,
    bpp: int = 16,
    dib_size: int = 40,
    include_masks: bool = True,
) -> bytes:
    """Create a BI_BITFIELDS (compression=3) BMP with optional 12-byte RGB masks."""
    row_stride = ((width * bpp + 31) // 32) * 4
    pixel_size = row_stride * height
    masks = struct.pack("<III", 0xF800, 0x07E0, 0x001F) if bpp == 16 else struct.pack("<III", 0x00FF0000, 0x0000FF00, 0x000000FF)
    extra_hdr = masks if (dib_size == 40 and include_masks) else (b"\x00" * max(0, dib_size - 40))
    bf_off = 14 + 40 + len(extra_hdr)
    file_size = bf_off + pixel_size
    file_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, bf_off)
    info_header = struct.pack("<IiiHHIIiiII", dib_size, width, height, 1, bpp, 3, pixel_size, 2835, 2835, 0, 0)
    if dib_size > 40:
        # Place RGB masks at bytes 40..52 inside V4/V5 header
        extra_hdr = masks + b"\x00" * (dib_size - 40 - len(masks))
    px = b"\x00\xf8" if bpp == 16 else b"\xff\x00\x00\xff"
    row = (px * width).ljust(row_stride, b"\x00")
    return file_header + info_header + extra_hdr + (row * height)


def _make_corrupt_sstable_block_bytes() -> tuple[bytes, bytes]:
    """Build an SSTable whose data block has invalid restart count (`block_invalid_restarts`)."""
    bad_blk = b"\x00\x01\x02\xff\xff\xff\x7f"
    bad_blk_f = bad_blk + b"\x00" + struct.pack("<I", leveldb_masked_crc32c(bad_blk + b"\x00"))
    ikey = b"!scenes!s1" + struct.pack("<Q", (1 << 8) | 1)
    idx_v = _encode_varint32(0) + _encode_varint32(len(bad_blk))
    idx_r = _encode_varint32(0) + _encode_varint32(len(ikey)) + _encode_varint32(len(idx_v)) + ikey + idx_v + struct.pack("<II", 0, 1)
    idx_f = idx_r + b"\x00" + struct.pack("<I", leveldb_masked_crc32c(idx_r + b"\x00"))
    meta_r = struct.pack("<II", 0, 1)
    meta_f = meta_r + b"\x00" + struct.pack("<I", leveldb_masked_crc32c(meta_r + b"\x00"))
    h_blk = _encode_varint32(len(bad_blk_f) + len(idx_f)) + _encode_varint32(len(meta_r)) + _encode_varint32(len(bad_blk_f)) + _encode_varint32(len(idx_r))
    sst = bad_blk_f + idx_f + meta_f + h_blk.ljust(40, b"\x00") + struct.pack("<Q", 0xDB4775248B80FB57)
    return sst, ikey


_WEBP_ORACLE_GD = r'''extends SceneTree

func _make_noisy_img(w: int, h: int, fmt: Image.Format, seed_val: int) -> Image:
	var img := Image.create(w, h, false, fmt)
	var rng := RandomNumberGenerator.new()
	rng.seed = seed_val
	var has_alpha: bool = (fmt == Image.FORMAT_RGBA8)
	for y: int in range(h):
		for x: int in range(w):
			var a: float = (0.25 + 0.75 * rng.randf()) if has_alpha else 1.0
			img.set_pixel(x, y, Color(rng.randf(), rng.randf(), rng.randf(), a))
	return img

func _find_vp8_chunk(buf: PackedByteArray) -> int:
	var pos: int = 12
	while pos + 8 <= buf.size():
		var tag: String = buf.slice(pos, pos + 4).get_string_from_ascii()
		var csz: int = int(buf.decode_u32(pos + 4))
		if tag == "VP8 ":
			return pos
		pos += 8 + csz + (csz & 1)
	return -1

func _initialize() -> void:
	var out_path: String = ""
	for a: String in OS.get_cmdline_user_args():
		if a.begins_with("--out="):
			out_path = a.substr(6)

	var w48_b := _make_noisy_img(48, 48, Image.FORMAT_RGB8, 987654).save_webp_to_buffer(true, 0.85)
	var w32_smooth := Image.create(32, 32, false, Image.FORMAT_RGB8)
	for y: int in range(32):
		for x: int in range(32):
			w32_smooth.set_pixel(x, y, Color(float(x) / 31.0, 0.5, float(y) / 31.0, 1.0))
	var w32_rgb_b := w32_smooth.save_webp_to_buffer(true, 0.75)
	var w64_rgba_b := _make_noisy_img(64, 64, Image.FORMAT_RGBA8, 13579).save_webp_to_buffer(true, 0.80)
	var w17_odd_b := _make_noisy_img(17, 19, Image.FORMAT_RGB8, 24680).save_webp_to_buffer(true, 0.90)
	var w128_pcat_b := _make_noisy_img(128, 128, Image.FORMAT_RGBA8, 424242).save_webp_to_buffer(true, 0.95)

	var bases: Array = [
		["w48_b", w48_b],
		["w32_smooth_rgb", w32_rgb_b],
		["w64_noisy_rgba", w64_rgba_b],
		["w17_odd_rgb", w17_odd_b],
		["w128_pcat", w128_pcat_b],
	]
	var vectors: Array = []
	for item: Array in bases:
		var lbl: String = str(item[0])
		var base_w: PackedByteArray = item[1]
		var vpos: int = _find_vp8_chunk(base_w)
		if vpos < 12:
			vectors.append({"id": lbl + "_missing_vp8", "label": lbl, "trim": 0, "godot_err": -1, "b64": ""})
			continue
		var base_csz: int = int(base_w.decode_u32(vpos + 4))
		for trim_i: int in range(0, 7):
			var w_trim: PackedByteArray
			if trim_i == 0:
				w_trim = base_w
			else:
				var new_csz: int = maxi(12, base_csz - trim_i)
				w_trim = base_w.slice(0, vpos + 8 + new_csz)
				w_trim.encode_u32(vpos + 4, new_csz)
				if (new_csz & 1) == 1:
					w_trim.append(0)
				w_trim.encode_u32(4, w_trim.size() - 8)
			var img_chk := Image.new()
			var g_err: int = int(img_chk.load_webp_from_buffer(w_trim))
			vectors.append({
				"id": "%s_trim_%d" % [lbl, trim_i],
				"label": lbl,
				"trim": trim_i,
				"godot_err": g_err,
				"b64": Marshalls.raw_to_base64(w_trim),
			})

	if FileAccess.file_exists("res://vp8_4part.bin"):
		var b4: PackedByteArray = FileAccess.get_file_as_bytes("res://vp8_4part.bin")
		var vp4: int = _find_vp8_chunk(b4)
		if vp4 >= 12:
			var b4_csz: int = int(b4.decode_u32(vp4 + 4))
			var ft4: int = int(b4[vp4 + 8]) | (int(b4[vp4 + 9]) << 8) | (int(b4[vp4 + 10]) << 16)
			var p0_4: int = (ft4 >> 5) & 0x7FFFF
			var dct_off: int = vp4 + 8 + 10 + p0_4
			var s1: int = int(b4[dct_off]) | (int(b4[dct_off + 1]) << 8) | (int(b4[dct_off + 2]) << 16)
			var s2: int = int(b4[dct_off + 3]) | (int(b4[dct_off + 4]) << 8) | (int(b4[dct_off + 5]) << 16)
			var s3: int = int(b4[dct_off + 6]) | (int(b4[dct_off + 7]) << 8) | (int(b4[dct_off + 8]) << 16)
			var base_hdr: int = 10 + p0_4 + 9
			var cut_points: Array[int] = [
				b4_csz,
				base_hdr + maxi(1, s1 / 2),
				base_hdr + s1 + maxi(1, s2 / 2),
				base_hdr + s1 + s2 + maxi(1, s3 / 2),
				base_hdr + s1 + s2 + s3 + 2,
				b4_csz - 2,
				b4_csz - 4,
			]
			for ci: int in range(cut_points.size()):
				var ncsz: int = clampi(cut_points[ci], 12, b4_csz)
				var w4: PackedByteArray = b4.slice(0, vp4 + 8 + ncsz)
				w4.encode_u32(vp4 + 4, ncsz)
				if (ncsz & 1) == 1:
					w4.append(0)
				w4.encode_u32(4, w4.size() - 8)
				var im4 := Image.new()
				var ge4: int = int(im4.load_webp_from_buffer(w4))
				vectors.append({
					"id": "vp8_4part_cut_%d" % ci,
					"label": "vp8_4part",
					"trim": ci,
					"godot_err": ge4,
					"b64": Marshalls.raw_to_base64(w4),
				})

	var fo := FileAccess.open(out_path, FileAccess.WRITE)
	fo.store_string(JSON.stringify({"vectors": vectors}))
	fo.close()
	quit(0)
'''


_TIER5_PROBE_GD = r'''extends SceneTree

class Tier5MockHost extends RefCounted:
	var root: Variant = null
	var cache: String = ""
	var destination: String = ""
	var file: String = ""
	var settings: Dictionary = {}
	var expected_sha256: String = ""
	var warnings: Array[String] = []
	var cancel_flag: bool = false
	var cancel_after_finish_geom: bool = false
	var evil_archive: bool = false
	var _geom_done: bool = false
	func cancelled() -> bool:
		return cancel_flag or (cancel_after_finish_geom and _geom_done)
	func report(_t: String) -> void: pass
	func warn(t: String) -> void: warnings.append(t)
	func begin_preview(_n: int, _r: Rect2) -> void: pass
	func preview_entity(_e: Dictionary, _k: String) -> void: pass
	func finish_geometry_preview() -> bool:
		_geom_done = true
		return true
	func archive_image(_url: String, _proxy: String) -> Dictionary:
		if evil_archive:
			return {"ok": true, "reference": "user://evil.png"}
		return {"ok": false, "reason": "disabled"}
	func empty_world() -> Dictionary:
		var floor_uid := "fus.floor.mock.1f".sha256_text().left(32)
		var entity_uid := ("fus.layer.default.v1:" + floor_uid).sha256_text().left(32)
		var map_uid := ("fus.layer.map:" + floor_uid).sha256_text().left(32)
		var obstacle_uid := ("fus.layer.obstacle:" + floor_uid).sha256_text().left(32)
		return {
			"ok": true,
			"data": {
				"format": "fus.practice.world", "version": 3,
				"catalog": {
					"floor_identity_version": 1,
					"floors": [{"id": 0, "floor_uid": floor_uid, "name": "1F", "color": Color(0.28, 0.65, 0.40)}],
					"layers": {"schema": "fus.floor_layers.v2", "floors": [{
						"floor_uid": floor_uid, "default_layer_uid": entity_uid,
						"layers": [
							{"layer_uid": map_uid, "name": "m", "kind": "map", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
							{"layer_uid": entity_uid, "name": "e", "kind": "entity", "visible": true, "locked": false, "persistent": true, "access": "all", "viewers": []},
							{"layer_uid": obstacle_uid, "name": "o", "kind": "obstacle", "visible": true, "locked": false, "persistent": true, "access": "host", "viewers": []},
						],
					}]},
					"active_floor_uid": floor_uid,
				},
				"entity_state": {"version": 3, "entities": []}, "members": [], "modules": {"version": 2, "entries": {}},
			},
		}

class Tier5MockStore extends RefCounted:
	var _records: Dictionary = {}
	var _rev: int = 1
	var fail_open: bool = false
	var fail_read_mode: String = "" # "", "non_dict", "err_dict"
	var fail_write_kind: String = "" # "", "folder", "unit"
	var fail_adopt: bool = false
	var fail_share: bool = false
	var fail_publish_reason: String = ""
	var write_calls: int = 0
	var publish_calls: Array = []
	var cancel_host: Tier5MockHost = null
	var cancel_on_write_call: int = -1

	func Publish(dest: String, reference: String, bytes: PackedByteArray) -> String:
		if not fail_publish_reason.is_empty():
			return JSON.stringify({"ok": false, "reason": fail_publish_reason})
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
		publish_calls.append({"ref": reference, "reused": existed, "path": fpath})
		return JSON.stringify({"ok": true, "reused": existed, "new_bytes": 0 if existed else bytes.size()})

	func OpenLibrary(root: String) -> String:
		if fail_open:
			return JSON.stringify({"ok": false, "reason": "open_lib_denied"})
		DirAccess.make_dir_recursive_absolute(root.path_join("entity-library/assets"))
		DirAccess.make_dir_recursive_absolute(root.path_join("entity-library/records"))
		return JSON.stringify({"ok": true})

	func ReadLibraryRecords(_root: String) -> Variant:
		if fail_read_mode == "non_dict":
			return "corrupt_non_dict"
		if fail_read_mode == "err_dict":
			return {"ok": false, "reason": "read_records_failed"}
		return {"ok": true, "records": _records.duplicate(), "revision": "rev_%d" % _rev}

	func WriteLibraryRecord(_root: String, id: String, expected: PackedByteArray, desired: PackedByteArray, expected_rev: String) -> String:
		write_calls += 1
		if expected_rev != ("rev_%d" % _rev):
			return JSON.stringify({"ok": false, "reason": "revision_mismatch"})
		var cur: PackedByteArray = _records.get(id, PackedByteArray())
		if cur != expected:
			return JSON.stringify({"ok": false, "reason": "expected_mismatch"})
		if not fail_write_kind.is_empty() and not desired.is_empty():
			var parsed: Variant = bytes_to_var(desired)
			if parsed is Dictionary and str((parsed as Dictionary).get("kind", "")) == fail_write_kind:
				return JSON.stringify({"ok": false, "reason": "write_%s_denied" % fail_write_kind})
		if desired.is_empty():
			_records.erase(id)
		else:
			_records[id] = desired
		_rev += 1
		if cancel_host != null and cancel_on_write_call > 0 and write_calls >= cancel_on_write_call:
			cancel_host.cancel_flag = true
		return JSON.stringify({"ok": true, "changed": true, "revision": "rev_%d" % _rev})

	func AdoptLibraryAsset(_root: String, _campaign: String, _ref: String) -> String:
		if fail_adopt:
			return JSON.stringify({"ok": false, "reason": "adopt_failed"})
		return JSON.stringify({"ok": true})

	func ShareLibraryAsset(_root: String, _ref: String) -> String:
		if fail_share:
			return JSON.stringify({"ok": false, "reason": "share_failed"})
		return JSON.stringify({"ok": true})

func _sha256(data: PackedByteArray) -> String:
	var ctx := HashingContext.new()
	ctx.start(HashingContext.HASH_SHA256)
	ctx.update(data)
	return ctx.finish().hex_encode()

func _check_all_floats_finite(val: Variant) -> bool:
	match typeof(val):
		TYPE_FLOAT:
			return is_finite(float(val))
		TYPE_ARRAY:
			for it: Variant in (val as Array):
				if not _check_all_floats_finite(it):
					return false
		TYPE_DICTIONARY:
			var d := val as Dictionary
			for k: Variant in d.keys():
				if not _check_all_floats_finite(d[k]):
					return false
	return true

func _validate_world_v3_quick(world: Dictionary) -> Array[String]:
	var errs: Array[String] = []
	if str(world.get("format", "")) != "fus.practice.world" or int(world.get("version", -1)) != 3:
		errs.append("bad format/version")
	var cat: Dictionary = world.get("catalog", {})
	var floors: Array = cat.get("floors", [])
	if floors.is_empty() or floors.size() > 512:
		errs.append("floors out of 1..512")
	var fuid_set: Dictionary = {}
	for f: Variant in floors:
		var fd: Dictionary = f as Dictionary
		var fuid := str(fd.get("floor_uid", ""))
		if fuid.length() != 32 or fuid_set.has(fuid):
			errs.append("bad floor_uid")
		fuid_set[fuid] = true
	if not fuid_set.has(str(cat.get("active_floor_uid", ""))):
		errs.append("bad active_floor_uid")
	return errs

func _initialize() -> void:
	var cfg_path: String = ""
	var out_path: String = ""
	for a: String in OS.get_cmdline_user_args():
		if a.begins_with("--cfg="): cfg_path = a.substr(6)
		elif a.begins_with("--out="): out_path = a.substr(6)
	var f := FileAccess.open(cfg_path, FileAccess.READ)
	var j := JSON.new()
	j.parse(f.get_as_text())
	f.close()
	var cfg: Dictionary = j.data
	var entry_scr := load(str(cfg["entry_gd"])) as Script
	var sdk_scr := load(str(cfg["sdk_gd"])) as Script
	var src_scr := load(str(cfg["src_dir"]) + "/fvtt_source.gd") as Script
	var snappy_scr := load(str(cfg["src_dir"]) + "/snappy.gd") as Script
	var norm_scr := load(str(cfg["src_dir"]) + "/fvtt_normalizer.gd") as Script
	var nedb_scr := load(str(cfg["src_dir"]) + "/fvtt_nedb.gd") as Script
	var leveldb_scr := load(str(cfg["src_dir"]) + "/fvtt_leveldb.gd") as Script
	var mapper_scr := load(str(cfg["src_dir"]) + "/fuvtt_mapper.gd") as Script
	var assets_scr := load(str(cfg["src_dir"]) + "/fuvtt_assets.gd") as Script

	var entry: RefCounted = entry_scr.new()
	var src: RefCounted = src_scr.new()
	var snappy: RefCounted = snappy_scr.new()
	var norm: RefCounted = norm_scr.new()
	var nedb: RefCounted = nedb_scr.new()
	var leveldb: RefCounted = leveldb_scr.new()

	var out: Dictionary = {
		"entry_cases": {}, "rfc_entries": {}, "snappy_edges": {}, "norm_scenes": {},
		"mapper_null_nan": {}, "entity_lib": {}, "gridless_omission": {},
		"assets_adv": {}, "svg_adv": {}, "null_host": {},
		"resolve_adv": {}, "img_bad_adv": {}, "webp_tail_parity": {}, "integ_t5": {},
		"bgdia_sweep": {"total": 0, "ok": 0, "fails": []},
		"preval_t5": {}, "r17_grid": {}, "r17_src": {}, "r17_ldb": {}, "r17_norm": {},
		"vp8l_const": {}, "actor_dup_cases": {},
	}

	# A. Entry cases (Challenger 1 + block/v10 fallback + skip_missing=true ZIP CRC)
	for item: Dictionary in cfg["entry_cases"]:
		var cid: String = item["id"]
		var p: String = item["path"]
		var opts: Dictionary = item.get("opts", {})
		var mh := Tier5MockHost.new()
		mh.file = p
		var ins: Dictionary = entry.inspect_import(p, opts, mh)
		var prep: Dictionary = entry.prepare_import(p, opts, mh)
		var row: Dictionary = {
			"ins_ok": ins.get("ok", false),
			"ins_reason": ins.get("reason", ""),
			"ins_counts": ins.get("counts", {}),
			"ins_decoded_bytes": ins.get("decoded_bytes", -1),
			"prep_ok": prep.get("ok", false),
			"prep_reason": prep.get("reason", ""),
			"warnings": mh.warnings,
		}
		if bool(prep.get("ok", false)):
			var w: Dictionary = prep["world"]
			var st: Dictionary = w.get("modules", {}).get("entries", {}).get("fvtt_world_importer", {}).get("state", {})
			row["actors"] = st.get("actors", [])
			var floor_names: Array = []
			for fl_row: Dictionary in w.get("catalog", {}).get("floors", []):
				floor_names.append(str(fl_row.get("name", "")))
			var wall_cnt_row: int = 0
			for ent_row: Dictionary in w.get("entity_state", {}).get("entities", []):
				var comps_row: Array = ent_row.get("components", [])
				if not comps_row.is_empty() and comps_row[0] is Dictionary:
					var vd_row: Variant = (comps_row[0] as Dictionary).get("state", {}).get("vector_drawing", null)
					if vd_row is Dictionary and not (vd_row as Dictionary).is_empty():
						wall_cnt_row += 1
			row["floors"] = floor_names.size()
			row["floor_names"] = floor_names
			row["wall_count"] = wall_cnt_row
		out["entry_cases"][cid] = row

	# B. RFC 1951 & ZIP edge cases
	var o_rfc: Dictionary = src.open(str(cfg["rfc_zip"]))
	out["rfc_open_ok"] = o_rfc.get("ok", false)
	for fn: String in ["raw15.bin", "multi.bin", "empty_dist.bin"]:
		var d: PackedByteArray = src.read_bytes(fn)
		out["rfc_entries"][fn] = {"len": d.size(), "sha256": _sha256(d), "err": src.get_last_read_error()}
	src.close()

	# C. Snappy edge vectors
	for k_sn: String in cfg["snappy_vectors"]:
		var raw_sn: PackedByteArray = Marshalls.base64_to_raw(str(cfg["snappy_vectors"][k_sn]))
		out["snappy_edges"][k_sn] = snappy.decompress(raw_sn)

	# D. Normalizer extreme coords
	var o_ext: Dictionary = src.open(str(cfg["ext_world"]))
	if bool(o_ext.get("ok", false)):
		var nr: Dictionary = norm.normalize(o_ext["world_json"], {"scenes": nedb.read_collection(src, "scenes"), "actors": nedb.read_collection(src, "actors")}, src, {})
		src.close()
		if bool(nr.get("ok", false)):
			var sc: Dictionary = (nr["model"]["scenes"] as Array)[0]
			out["norm_scenes"]["ext"] = {
				"scene_x_finite": is_finite(float(sc.get("scene_x", INF))),
				"scene_y_finite": is_finite(float(sc.get("scene_y", INF))),
				"grid_size": sc.get("grid_size", -1),
			}

	# E. Challenger 2 Test 1: direct map_to_world with null / NAN / INF / 1e20 wall
	var h_mn := Tier5MockHost.new()
	var s_mn = sdk_scr.new().create_session(h_mn, {})
	var b_mn = sdk_scr.new().create_world_builder(null, 150.0)
	var m_mn = mapper_scr.new()
	var model_mn: Dictionary = {
		"world_meta": {"id": "mn", "title": "MN", "core_version": "12", "system": "dnd5e", "system_version": "3.0", "source_kind": "dir"},
		"scenes": [{
			"id": "sc_mn", "name": "MN Scene", "active": true, "width": null, "height": 1000.0,
			"scene_x": null, "scene_y": 0.0, "grid_size": 100.0, "grid_type": 1, "grid_distance": 5.0, "grid_units": "ft",
			"background_ref": "", "foreground_ref": "", "hidden": false,
			"tiles": [
				{"id": "tl_null", "img_ref": "", "x": 0.0, "y": 0.0, "width": null, "height": null, "rotation": null, "z_order": "99999999999999999999999999", "hidden": false},
				{"id": "tl_min", "img_ref": "", "x": 10.0, "y": 10.0, "width": 50.0, "height": 50.0, "rotation": 0.0, "z_order": "-9223372036854775809", "hidden": false},
			],
			"walls": [
				{"id": "w_null", "c": [null, 0, 100, 0], "door": 0, "ds": 0, "move": 20, "sight": 20, "light": 20},
				{"id": "w_huge", "c": [0, 0, 1e20, 0], "door": 0, "ds": 0, "move": 20, "sight": 20, "light": 20},
				{"id": "w_good", "c": [0, 0, 100, 0], "door": 0, "ds": 0, "move": 20, "sight": 20, "light": 20},
			],
			"lights": [{"id": "lt_null", "x": null, "y": 10.0, "bright": null, "dim": 20.0, "angle": null, "hidden": false}],
			"tokens": [{"id": "tk_null", "name": "T", "actor_id": "a_mn", "actor_type": "character", "img_ref": "", "x": 10.0, "y": 10.0, "width": null, "height": null, "scale": null, "rotation": null, "hidden": false, "disposition": null, "actor_link": null, "sight_enabled": false, "sight_range": null, "sight_angle": null}],
		}],
		"actors": [{
			"id": "a_mn", "name": "NanHero", "actor_type": "character", "sub_type": "", "folder_name": "",
			"img_ref": "", "token_img_ref": "", "token_width": null, "token_height": null, "token_scale": null,
			"disposition": null, "actor_link": null, "ac": null, "hp_value": null, "hp_max": null,
			"cr_or_level": NAN,
			"abilities": {"str": {"value": INF, "mod": NAN}},
			"speed": {"walk": INF},
			"senses": {"darkvision": INF},
			"biography": "bio",
			"raw_summary": {"bad": NAN, "nested": [INF, -INF]},
		}],
		"assets": {}, "source_records": "99999999999999999999999999",
	}
	var res_mn: Dictionary = m_mn.map_to_world(model_mn, b_mn, assets_scr.new(), null, h_mn, s_mn, {})
	var w_mn: Dictionary = b_mn.get_world()
	var mod_state_mn: Dictionary = w_mn.get("modules", {}).get("entries", {}).get("fvtt_world_importer", {}).get("state", {})
	var wall_cnt_mn: int = 0
	for ent: Dictionary in w_mn.get("entity_state", {}).get("entities", []):
		var comps: Array = ent.get("components", [])
		if not comps.is_empty() and comps[0] is Dictionary:
			var vd: Variant = (comps[0] as Dictionary).get("state", {}).get("vector_drawing", null)
			if vd is Dictionary and not (vd as Dictionary).is_empty():
				wall_cnt_mn += 1
	out["mapper_null_nan"] = {
		"ok": res_mn.get("ok", false),
		"source_records": res_mn.get("source_records", -1),
		"all_finite": _check_all_floats_finite(mod_state_mn),
		"wall_count": wall_cnt_mn,
		"warnings": h_mn.warnings,
		"v3_errs": _validate_world_v3_quick(w_mn),
	}

	# F. Challenger 2 Test 2: entity-library failure paths + mid-loop cancel rollback
	var run_dir: String = str(cfg["run_dir"])
	var lib_root: String = run_dir.path_join("lib_root")
	var lib_dest: String = lib_root.path_join("sessions/桌面 2026-11-20 120000_abcdefabcdefabcdefabcdefabcdefab")
	var lib_actors: Array = [
		{"id": "la1", "name": "Unit1", "actor_type": "npc", "folder_name": "F1/F2", "token_width": 1.0, "token_height": 1.0},
		{"id": "la2", "name": "Unit2", "actor_type": "npc", "folder_name": "F1/F2", "token_width": 1.0, "token_height": 1.0},
	]
	var png_b := FileAccess.get_file_as_bytes(str(cfg["png_path"]))
	var lib_res_map: Dictionary = {}
	for mode: String in ["open_fail", "read_non_dict", "read_err_dict", "write_folder_fail", "write_unit_fail", "adopt_fail", "share_fail", "cancel_mid_loop"]:
		var st_m := Tier5MockStore.new()
		var h_m := Tier5MockHost.new()
		h_m.root = lib_root
		h_m.destination = lib_dest
		var ah_m: RefCounted = assets_scr.new()
		ah_m.set_shared_asset_store(st_m, true)
		var s_m = sdk_scr.new().create_session(h_m, {})
		var pub_m: Dictionary = ah_m.publish_local_bytes(png_b, "png", h_m, s_m)
		var sref_m: String = str(pub_m.get("sprite_path", ""))
		var src_mock := _MockByteSource.new({"a.png": png_b})
		var amap_m := {"a.png": {"kind": "local", "resolved_path_or_url": "a.png", "ext": "png", "exists": true}}
		if mode == "open_fail": st_m.fail_open = true
		elif mode == "read_non_dict": st_m.fail_read_mode = "non_dict"
		elif mode == "read_err_dict": st_m.fail_read_mode = "err_dict"
		elif mode == "write_folder_fail": st_m.fail_write_kind = "folder"
		elif mode == "write_unit_fail": st_m.fail_write_kind = "unit"
		elif mode == "adopt_fail": st_m.fail_adopt = true
		elif mode == "share_fail": st_m.fail_share = true
		elif mode == "cancel_mid_loop":
			st_m.cancel_host = h_m
			st_m.cancel_on_write_call = 3
		var actors_cur: Array = []
		for a0: Dictionary in lib_actors:
			var a1: Dictionary = a0.duplicate()
			a1["token_img_ref"] = "a.png"
			actors_cur.append(a1)
		var m_m: RefCounted = mapper_scr.new()
		m_m.set_shared_asset_store(st_m, true)
		var r_m: Dictionary = m_m.map_to_world({
			"world_meta": {"id": "lw_" + mode, "title": "LW", "core_version": "12", "system": "dnd5e", "system_version": "3", "source_kind": "dir"},
			"scenes": [], "actors": actors_cur, "assets": amap_m, "source_records": 2,
		}, sdk_scr.new().create_world_builder(null, 150.0), ah_m, src_mock, h_m, s_m, {"register_entity_library": true})
		var rec_refs: Array = []
		for rv: Variant in st_m._records.values():
			var d_rv: Variant = bytes_to_var(rv as PackedByteArray)
			if d_rv is Dictionary and str((d_rv as Dictionary).get("kind", "")) == "unit":
				rec_refs.append((d_rv as Dictionary).get("reference", ""))
		lib_res_map[mode] = {
			"ok": r_m.get("ok", false),
			"reason": r_m.get("reason", ""),
			"warnings": h_m.warnings,
			"records_count": st_m._records.size(),
			"unit_refs": rec_refs,
		}
	# Also verify post-map rollback_entity_library() hook used by entry.gd
	var st_post := Tier5MockStore.new()
	var h_post := Tier5MockHost.new()
	h_post.root = lib_root
	h_post.destination = lib_dest
	var ah_post: RefCounted = assets_scr.new()
	ah_post.set_shared_asset_store(st_post, true)
	var m_post: RefCounted = mapper_scr.new()
	m_post.set_shared_asset_store(st_post, true)
	var r_post: Dictionary = m_post.map_to_world({
		"world_meta": {"id": "lw_post", "title": "LWPost", "core_version": "12", "system": "dnd5e", "system_version": "3", "source_kind": "dir"},
		"scenes": [], "actors": lib_actors, "assets": {}, "source_records": 2,
	}, sdk_scr.new().create_world_builder(null, 150.0), ah_post, null, h_post, sdk_scr.new().create_session(h_post, {}), {"register_entity_library": true})
	var pre_rb_cnt: int = st_post._records.size()
	m_post.rollback_entity_library()
	lib_res_map["post_map_rollback"] = {"ok": r_post.get("ok", false), "before": pre_rb_cnt, "after": st_post._records.size()}
	out["entity_lib"] = lib_res_map

	# G. Challenger 2 Test 3: gridless-only grid_alignment + 12000-actor full module omission (exceeds v0.0.60 16 MiB entry cap)
	var h_go := Tier5MockHost.new()
	var s_go = sdk_scr.new().create_session(h_go, {})
	var b_go = sdk_scr.new().create_world_builder(null, 150.0)
	var big_name := "N".repeat(400)
	var actors_big: Array = []
	for i46: int in range(12000):
		actors_big.append({
			"id": "a_%d" % i46, "name": big_name, "actor_type": "npc", "sub_type": "", "folder_name": "Big",
			"img_ref": "", "token_img_ref": "", "token_width": 1.0, "token_height": 1.0, "token_scale": 1.0,
			"disposition": -1, "actor_link": false, "ac": 10, "hp_value": 10, "hp_max": 10, "cr_or_level": 1.0,
			"abilities": {}, "speed": {}, "senses": {}, "biography": "", "raw_summary": {},
		})
	var r_go: Dictionary = mapper_scr.new().map_to_world({
		"world_meta": {"id": "go", "title": "Gridless", "core_version": "12", "system": "dnd5e", "system_version": "3", "source_kind": "dir"},
		"scenes": [
			{"id": "sg_a", "name": "Tavern", "active": true, "width": 500.0, "height": 500.0, "scene_x": 0.0, "scene_y": 0.0, "grid_size": 100.0, "grid_type": 0, "grid_distance": 5.0, "grid_units": "ft", "background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [], "walls": [], "lights": [], "tokens": []},
			{"id": "sg_b", "name": "Tavern", "active": false, "width": 500.0, "height": 500.0, "scene_x": 0.0, "scene_y": 0.0, "grid_size": 100.0, "grid_type": 0, "grid_distance": 5.0, "grid_units": "ft", "background_ref": "", "foreground_ref": "", "hidden": false, "tiles": [], "walls": [], "lights": [], "tokens": []},
		],
		"actors": actors_big, "assets": {}, "source_records": 12002,
	}, b_go, assets_scr.new(), null, h_go, s_go, {})
	var w_go: Dictionary = b_go.get_world()
	var f_uids_go: Array = []
	for fl: Dictionary in w_go.get("catalog", {}).get("floors", []):
		f_uids_go.append(fl.get("floor_uid", ""))
	var entries_go: Dictionary = w_go.get("modules", {}).get("entries", {})
	out["gridless_omission"] = {
		"ok": r_go.get("ok", false),
		"floor_uids": f_uids_go,
		"snap_enabled": entries_go.get("grid_alignment", {}).get("state", {}).get("snap_enabled", true),
		"has_importer_module": entries_go.has("fvtt_world_importer"),
		"warnings": h_go.warnings,
		"v3_errs": _validate_world_v3_quick(w_go),
	}

	# H. Challenger 2 Test 4: BMP BI_BITFIELDS, Publish fail, unsafe strict, and multi-scene publish rollback
	var ah_bmp: RefCounted = assets_scr.new()
	var h_bmp := Tier5MockHost.new()
	var s_bmp = sdk_scr.new().create_session(h_bmp, {})
	var bmp_nomask := FileAccess.get_file_as_bytes(str(cfg["bmp_nomask"]))
	var bmp_mask := FileAccess.get_file_as_bytes(str(cfg["bmp_mask"]))
	var bmp_v4 := FileAccess.get_file_as_bytes(str(cfg["bmp_v4"]))
	var bmp_v5 := FileAccess.get_file_as_bytes(str(cfg["bmp_v5"]))

	var st_disk := Tier5MockStore.new()
	st_disk.fail_publish_reason = "disk_full"
	var ah_disk: RefCounted = assets_scr.new()
	ah_disk.set_shared_asset_store(st_disk, true)
	var h_disk := Tier5MockHost.new()
	h_disk.destination = run_dir.path_join("disk_dest/sessions/桌面 2026-11-20 120000_22222222222222222222222222222222")
	var r_disk: Dictionary = ah_disk.publish_local_bytes(png_b, "png", h_disk, sdk_scr.new().create_session(h_disk, {}))

	var ah_uns: RefCounted = assets_scr.new()
	var r_uns: Dictionary = ah_uns.resolve_sprite_ref("user://secret.png", {"kind": "unsafe", "unsafe": true}, null, h_bmp, s_bmp, {"skip_missing_assets": false})

	# Multi-scene publish rollback preserving pre-existing exact-hash & preexisting.png
	var rb_dest: String = run_dir.path_join("rb_root/sessions/桌面 2026-11-20 120000_33333333333333333333333333333333")
	var rb_assets: String = rb_dest.path_join("assets")
	DirAccess.make_dir_recursive_absolute(rb_assets)
	var pre_png_b := FileAccess.get_file_as_bytes(str(cfg["pre_png"]))
	var pre_hash_hex := _sha256(pre_png_b)
	var pre_exact_path := rb_assets.path_join(pre_hash_hex + ".png")
	var pre_other_path := rb_assets.path_join("preexisting.png")
	var fp1 := FileAccess.open(pre_exact_path, FileAccess.WRITE); fp1.store_buffer(pre_png_b); fp1.close()
	var fp2 := FileAccess.open(pre_other_path, FileAccess.WRITE); fp2.store_buffer(pre_png_b); fp2.close()
	var new_scene_png_b := FileAccess.get_file_as_bytes(str(cfg["new_scene_png"]))
	var new_hash_hex := _sha256(new_scene_png_b)
	var new_hash_path := rb_assets.path_join(new_hash_hex + ".png")

	var st_rb := Tier5MockStore.new()
	var h_rb := Tier5MockHost.new()
	h_rb.destination = rb_dest
	var opts_rb := {"skip_missing_assets": false, "register_entity_library": false}
	var s_rb = sdk_scr.new().create_session(h_rb, opts_rb)
	var ah_rb: RefCounted = assets_scr.new()
	ah_rb.set_shared_asset_store(st_rb, true)
	var src_rb: RefCounted = src_scr.new()
	var open_rb: Dictionary = src_rb.open(str(cfg["rb_world"]))
	var norm_rb: Dictionary = norm.normalize(
		open_rb.get("world_json", {}),
		{"scenes": nedb.read_collection(src_rb, "scenes"), "actors": nedb.read_collection(src_rb, "actors")},
		src_rb,
		opts_rb,
		s_rb
	)
	var m_rb: RefCounted = mapper_scr.new()
	var b_rb = sdk_scr.new().create_world_builder(null, 150.0)
	var prep_rb: Dictionary = m_rb.map_to_world(norm_rb["model"], b_rb, ah_rb, src_rb, h_rb, s_rb, opts_rb)
	src_rb.close()
	var new_existed_before := FileAccess.file_exists(new_hash_path)
	var pre_exact_existed_before := FileAccess.file_exists(pre_exact_path)
	var pre_other_existed_before := FileAccess.file_exists(pre_other_path)
	ah_rb.cleanup_published()
	out["assets_adv"] = {
		"bmp_nomask": ah_bmp.publish_local_bytes(bmp_nomask, "bmp", h_bmp, s_bmp),
		"bmp_mask": ah_bmp.publish_local_bytes(bmp_mask, "bmp", h_bmp, s_bmp),
		"bmp_v4": ah_bmp.publish_local_bytes(bmp_v4, "bmp", h_bmp, s_bmp),
		"bmp_v5": ah_bmp.publish_local_bytes(bmp_v5, "bmp", h_bmp, s_bmp),
		"publish_disk_full": r_disk,
		"unsafe_strict": r_uns,
		"rb_prep_ok": prep_rb.get("ok", false),
		"rb_prep_reason": prep_rb.get("reason", ""),
		"rb_publish_calls": st_rb.publish_calls,
		"rb_pre_ref": "asset://" + pre_hash_hex + ".png",
		"rb_new_ref": "asset://" + new_hash_hex + ".png",
		"new_existed_before": new_existed_before,
		"pre_exact_existed_before": pre_exact_existed_before,
		"pre_other_existed_before": pre_other_existed_before,
		"new_file_exists_after_fail": FileAccess.file_exists(new_hash_path),
		"pre_exact_exists": FileAccess.file_exists(pre_exact_path),
		"pre_other_exists": FileAccess.file_exists(pre_other_path),
	}

	# I. Challenger 2 Test 5: SVG variants
	var ah_svg: RefCounted = assets_scr.new()
	var svg_cases: Dictionary = cfg["svg_vectors"]
	for sk: String in svg_cases:
		var sb: PackedByteArray = Marshalls.base64_to_raw(str(svg_cases[sk]))
		out["svg_adv"][sk] = ah_svg.publish_local_bytes(sb, "svg", h_bmp, s_bmp)

	# J. Challenger 2 Test 6: null host
	var nh_ins: Dictionary = entry.inspect_import(str(cfg["simple_wj"]), {"download_remote_assets": false}, null)
	var nh_prep: Dictionary = entry.prepare_import(str(cfg["simple_wj"]), {}, null)
	out["null_host"] = {"ins": nh_ins, "prep": nh_prep}

	# K. Challenger 1 Iter 2: resolve_asset_ref percent-decoded / NUL / traversal / scheme vectors
	if bool(src.open(str(cfg["simple_wj"])).get("ok", false)):
		for rvec: String in cfg["resolve_vectors"]:
			out["resolve_adv"][rvec] = src.resolve_asset_ref(rvec, "t5")
		src.close()

	# L. Challenger 2 Iter 2: PNG/JPG/WebP outer header & chunk pre-validation (zero Godot errors)
	var img_bad_vecs: Dictionary = cfg["img_bad_vectors"]
	for ik: String in img_bad_vecs:
		var iv: Dictionary = img_bad_vecs[ik]
		var ib: PackedByteArray = Marshalls.base64_to_raw(str(iv["b64"]))
		var res_ik: Dictionary = ah_bmp.publish_local_bytes(ib, str(iv["ext"]), h_bmp, s_bmp)
		if bool(iv.get("check_native_png", false)):
			var im_nat := Image.new()
			res_ik["native_err"] = int(im_nat.load_png_from_buffer(ib))
			res_ik["native_w"] = im_nat.get_width()
			res_ik["native_h"] = im_nat.get_height()
		out["img_bad_adv"][ik] = res_ik
	var real_jpg_img := Image.create(4, 4, false, Image.FORMAT_RGBA8)
	real_jpg_img.fill(Color(0.2, 0.4, 0.6, 1.0))
	var real_jpg_b: PackedByteArray = real_jpg_img.save_jpg_to_buffer()
	var app1_payload := PackedByteArray([0x45, 0x78, 0x69, 0x66, 0x00, 0x00, 0xFF, 0xD8, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x02, 0x00, 0x02, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xD9])
	var app1_len: int = 2 + app1_payload.size()
	var app1_seg := PackedByteArray([0xFF, 0xE1, (app1_len >> 8) & 0xFF, app1_len & 0xFF])
	app1_seg.append_array(app1_payload)
	var jpg_app1_b := PackedByteArray()
	jpg_app1_b.append_array(real_jpg_b.slice(0, 2))
	jpg_app1_b.append_array(app1_seg)
	jpg_app1_b.append_array(real_jpg_b.slice(2))
	out["img_bad_adv"]["jpg_with_app1_thumb_markers"] = ah_bmp.publish_local_bytes(jpg_app1_b, "jpg", h_bmp, s_bmp)

	# M. Phase 2 Iter 13: Godot-generated WebP positive controls & payload-mutated WebP vectors
	var w_rgba := Image.create(32, 32, false, Image.FORMAT_RGBA8)
	for wy: int in range(32):
		for wx: int in range(32):
			w_rgba.set_pixel(wx, wy, Color(float(wx) / 31.0, float(wy) / 31.0, float((wx + wy) & 31) / 31.0, 0.75))
	var w_lossless_b: PackedByteArray = w_rgba.save_webp_to_buffer(false)
	var w_lossy_alpha_b: PackedByteArray = w_rgba.save_webp_to_buffer(true, 0.75)
	var w_rgb := Image.create(32, 32, false, Image.FORMAT_RGB8)
	for wy2: int in range(32):
		for wx2: int in range(32):
			w_rgb.set_pixel(wx2, wy2, Color(float(wx2) / 31.0, 0.5, float(wy2) / 31.0, 1.0))
	var w_lossy_rgb_b: PackedByteArray = w_rgb.save_webp_to_buffer(true, 0.75)
	out["img_bad_adv"]["webp_valid_lossless_complex"] = ah_bmp.publish_local_bytes(w_lossless_b, "webp", h_bmp, s_bmp)
	out["img_bad_adv"]["webp_valid_lossy_alpha"] = ah_bmp.publish_local_bytes(w_lossy_alpha_b, "webp", h_bmp, s_bmp)
	out["img_bad_adv"]["webp_valid_lossy_rgb"] = ah_bmp.publish_local_bytes(w_lossy_rgb_b, "webp", h_bmp, s_bmp)

	var w_ll_bad_end := w_lossless_b.duplicate()
	w_ll_bad_end[w_ll_bad_end.size() - 2] ^= 0xFF
	out["img_bad_adv"]["webp_real_lossless_bad_end"] = ah_bmp.publish_local_bytes(w_ll_bad_end, "webp", h_bmp, s_bmp)

	var w_alph_rsv := w_lossy_alpha_b.duplicate()
	w_alph_rsv[38] |= 0xC0
	out["img_bad_adv"]["webp_alph_rsv_bits"] = ah_bmp.publish_local_bytes(w_alph_rsv, "webp", h_bmp, s_bmp)

	var alph_off: int = 12
	while alph_off + 8 <= w_lossy_alpha_b.size():
		var actag: String = w_lossy_alpha_b.slice(alph_off, alph_off + 4).get_string_from_ascii()
		var acsz: int = int(w_lossy_alpha_b.decode_u32(alph_off + 4))
		if actag == "ALPH":
			break
		alph_off += 8 + acsz + (acsz & 1)
	for p_val: int in [1, 2, 3]:
		var w_ap := w_lossy_alpha_b.duplicate()
		w_ap[alph_off + 8] = (int(w_ap[alph_off + 8]) & 0xCF) | (p_val << 4)
		out["img_bad_adv"]["webp_alph_p%d" % p_val] = ah_bmp.publish_local_bytes(w_ap, "webp", h_bmp, s_bmp)

	var w_alph_bad_vp8l := w_lossy_alpha_b.duplicate()
	w_alph_bad_vp8l[42] ^= 0xFF
	out["img_bad_adv"]["webp_alph_corrupt_vp8l"] = ah_bmp.publish_local_bytes(w_alph_bad_vp8l, "webp", h_bmp, s_bmp)

	var w_vp8_cs := w_lossy_rgb_b.duplicate()
	w_vp8_cs[30] ^= 0x80
	out["img_bad_adv"]["webp_vp8_colorspace_bit"] = ah_bmp.publish_local_bytes(w_vp8_cs, "webp", h_bmp, s_bmp)

	var vp8_sf_pos: int = 12
	while vp8_sf_pos + 8 <= w_lossy_rgb_b.size():
		var sftag: String = w_lossy_rgb_b.slice(vp8_sf_pos, vp8_sf_pos + 4).get_string_from_ascii()
		var sfcsz: int = int(w_lossy_rgb_b.decode_u32(vp8_sf_pos + 4))
		if sftag == "VP8 ":
			break
		vp8_sf_pos += 8 + sfcsz + (sfcsz & 1)
	var w_vp8_noshow := w_lossy_rgb_b.duplicate()
	w_vp8_noshow[vp8_sf_pos + 8] = int(w_vp8_noshow[vp8_sf_pos + 8]) & (~0x10)
	out["img_bad_adv"]["webp_vp8_show_frame_0"] = ah_bmp.publish_local_bytes(w_vp8_noshow, "webp", h_bmp, s_bmp)
	var noshow_asset_p: String = str(cfg.get("webp_noshow_asset_path", ""))
	var noshow_wj_p: String = str(cfg.get("webp_noshow_wj", ""))
	if not noshow_asset_p.is_empty() and not noshow_wj_p.is_empty():
		var fnos := FileAccess.open(noshow_asset_p, FileAccess.WRITE)
		fnos.store_buffer(w_vp8_noshow)
		fnos.close()
		var h_ns_strict := Tier5MockHost.new()
		var prep_ns_strict: Dictionary = entry.prepare_import(noshow_wj_p, {"skip_missing_assets": false}, h_ns_strict)
		var h_ns_skip := Tier5MockHost.new()
		var prep_ns_skip: Dictionary = entry.prepare_import(noshow_wj_p, {"skip_missing_assets": true}, h_ns_skip)
		out["img_bad_adv"]["webp_vp8_show_frame_0_entry"] = {
			"strict_ok": prep_ns_strict.get("ok", false),
			"strict_reason": prep_ns_strict.get("reason", ""),
			"skip_ok": prep_ns_skip.get("ok", false),
			"skip_warnings": h_ns_skip.warnings,
		}

	var ftag: int = int(w_lossy_rgb_b[20]) | (int(w_lossy_rgb_b[21]) << 8) | (int(w_lossy_rgb_b[22]) << 16)
	var fp0_sz: int = (ftag >> 5) & 0x7FFFF
	var w_vp8_trunc := w_lossy_rgb_b.slice(0, mini(w_lossy_rgb_b.size() - 2, 20 + 10 + fp0_sz + 4))
	w_vp8_trunc.encode_u32(4, w_vp8_trunc.size() - 8)
	w_vp8_trunc.encode_u32(16, w_vp8_trunc.size() - 20)
	out["img_bad_adv"]["webp_vp8_trunc_dct"] = ah_bmp.publish_local_bytes(w_vp8_trunc, "webp", h_bmp, s_bmp)

	var w_vp8_mid := w_lossy_rgb_b.duplicate()
	w_vp8_mid[20 + 10 + fp0_sz / 2] ^= 0xFF
	out["img_bad_adv"]["webp_vp8_flip_mid_dct"] = ah_bmp.publish_local_bytes(w_vp8_mid, "webp", h_bmp, s_bmp)

	var w_vp8_nodct := w_lossy_rgb_b.slice(0, 20 + 10 + fp0_sz)
	w_vp8_nodct.encode_u32(4, w_vp8_nodct.size() - 8)
	w_vp8_nodct.encode_u32(16, w_vp8_nodct.size() - 20)
	out["img_bad_adv"]["webp_vp8_only_part0_no_dct"] = ah_bmp.publish_local_bytes(w_vp8_nodct, "webp", h_bmp, s_bmp)

	# N. Phase 2 Iter 13: Synthetic WebP multi-tile VP8L & high-freq Pcat VP8 positive controls + VP8X/ALPH+VP8L
	var w_tile := Image.create(128, 128, false, Image.FORMAT_RGBA8)
	var rng_w := RandomNumberGenerator.new()
	rng_w.seed = 424242
	for wy3: int in range(128):
		for wx3: int in range(128):
			if (wx3 < 64 and wy3 < 64):
				w_tile.set_pixel(wx3, wy3, Color(float((wx3 * 7 + wy3) & 255) / 255.0, float((wx3 ^ wy3) & 255) / 255.0, 0.25, 1.0))
			else:
				w_tile.set_pixel(wx3, wy3, Color(rng_w.randf(), rng_w.randf(), rng_w.randf(), rng_w.randf()))
	var w_tile_ll_b: PackedByteArray = w_tile.save_webp_to_buffer(false)
	var w_pcat_lossy_b: PackedByteArray = w_tile.save_webp_to_buffer(true, 0.95)
	out["img_bad_adv"]["webp_valid_vp8l_multitile"] = ah_bmp.publish_local_bytes(w_tile_ll_b, "webp", h_bmp, s_bmp)
	out["img_bad_adv"]["webp_valid_vp8_pcat"] = ah_bmp.publish_local_bytes(w_pcat_lossy_b, "webp", h_bmp, s_bmp)
	var vp8l_payload_raw := w_lossless_b.slice(12)
	var vp8x_al_body := PackedByteArray()
	vp8x_al_body.append_array("WEBP".to_ascii_buffer())
	vp8x_al_body.append_array("VP8X".to_ascii_buffer())
	vp8x_al_body.append_array(PackedByteArray([10, 0, 0, 0, 0x10, 0, 0, 0, 31, 0, 0, 31, 0, 0]))
	vp8x_al_body.append_array(vp8l_payload_raw)
	var vp8x_al_riff := PackedByteArray()
	vp8x_al_riff.append_array("RIFF".to_ascii_buffer())
	var rsz_al: int = vp8x_al_body.size()
	vp8x_al_riff.append_array(PackedByteArray([rsz_al & 0xFF, (rsz_al >> 8) & 0xFF, (rsz_al >> 16) & 0xFF, (rsz_al >> 24) & 0xFF]))
	vp8x_al_riff.append_array(vp8x_al_body)
	out["img_bad_adv"]["webp_valid_vp8x_alpha_vp8l"] = ah_bmp.publish_local_bytes(vp8x_al_riff, "webp", h_bmp, s_bmp)

	# N2. Phase 2 Iter 14: VP8X+ALPH+VP8 tail-lookahead positive control (eof==2, bc==1), non-final MB truncation, and -1..-4 tail truncation sweep
	var rgb_vp8_csz: int = int(w_lossy_rgb_b.decode_u32(16))
	var rgb_vp8_trim3 := w_lossy_rgb_b.slice(20, 20 + rgb_vp8_csz - 3)
	var vp8x_al_vp8_body := PackedByteArray()
	vp8x_al_vp8_body.append_array("WEBP".to_ascii_buffer())
	vp8x_al_vp8_body.append_array("VP8X".to_ascii_buffer())
	vp8x_al_vp8_body.append_array(PackedByteArray([10, 0, 0, 0, 0x10, 0, 0, 0, 31, 0, 0, 31, 0, 0]))
	vp8x_al_vp8_body.append_array("ALPH".to_ascii_buffer())
	var alph_len: int = 1 + 32 * 32
	vp8x_al_vp8_body.append_array(PackedByteArray([alph_len & 0xFF, (alph_len >> 8) & 0xFF, (alph_len >> 16) & 0xFF, (alph_len >> 24) & 0xFF, 0]))
	var alph_px := PackedByteArray()
	alph_px.resize(32 * 32)
	alph_px.fill(0xFF)
	vp8x_al_vp8_body.append_array(alph_px)
	if (alph_len & 1) == 1:
		vp8x_al_vp8_body.append(0)
	vp8x_al_vp8_body.append_array("VP8 ".to_ascii_buffer())
	var t3_sz: int = rgb_vp8_trim3.size()
	vp8x_al_vp8_body.append_array(PackedByteArray([t3_sz & 0xFF, (t3_sz >> 8) & 0xFF, (t3_sz >> 16) & 0xFF, (t3_sz >> 24) & 0xFF]))
	vp8x_al_vp8_body.append_array(rgb_vp8_trim3)
	if (t3_sz & 1) == 1:
		vp8x_al_vp8_body.append(0)
	var vp8x_al_vp8_riff := PackedByteArray()
	vp8x_al_vp8_riff.append_array("RIFF".to_ascii_buffer())
	var rsz_al_vp8: int = vp8x_al_vp8_body.size()
	vp8x_al_vp8_riff.append_array(PackedByteArray([rsz_al_vp8 & 0xFF, (rsz_al_vp8 >> 8) & 0xFF, (rsz_al_vp8 >> 16) & 0xFF, (rsz_al_vp8 >> 24) & 0xFF]))
	vp8x_al_vp8_riff.append_array(vp8x_al_vp8_body)
	out["img_bad_adv"]["webp_valid_vp8x_alpha_vp8_tail"] = ah_bmp.publish_local_bytes(vp8x_al_vp8_riff, "webp", h_bmp, s_bmp)

	var pcat_vp8_pos: int = 12
	while pcat_vp8_pos + 8 <= w_pcat_lossy_b.size():
		var ctag: String = w_pcat_lossy_b.slice(pcat_vp8_pos, pcat_vp8_pos + 4).get_string_from_ascii()
		var csz: int = int(w_pcat_lossy_b.decode_u32(pcat_vp8_pos + 4))
		if ctag == "VP8 ":
			break
		pcat_vp8_pos += 8 + csz + (csz & 1)
	var pcat_ftag: int = int(w_pcat_lossy_b[pcat_vp8_pos + 8]) | (int(w_pcat_lossy_b[pcat_vp8_pos + 9]) << 8) | (int(w_pcat_lossy_b[pcat_vp8_pos + 10]) << 16)
	var pcat_fp0_sz: int = (pcat_ftag >> 5) & 0x7FFFF
	var nonfinal_csz: int = 10 + pcat_fp0_sz + 16
	var w_vp8_nonfinal := w_pcat_lossy_b.slice(0, pcat_vp8_pos + 8 + nonfinal_csz)
	w_vp8_nonfinal.encode_u32(pcat_vp8_pos + 4, nonfinal_csz)
	if (nonfinal_csz & 1) == 1:
		w_vp8_nonfinal.append(0)
	w_vp8_nonfinal.encode_u32(4, w_vp8_nonfinal.size() - 8)
	out["img_bad_adv"]["webp_vp8_trunc_nonfinal_mb"] = ah_bmp.publish_local_bytes(w_vp8_nonfinal, "webp", h_bmp, s_bmp)

	for trim_i: int in range(1, 5):
		for pair: Array in [["rgb", w_lossy_rgb_b, 12], ["pcat", w_pcat_lossy_b, pcat_vp8_pos]]:
			var p_lbl: String = str(pair[0])
			var base_w: PackedByteArray = pair[1]
			var vpos: int = int(pair[2])
			var base_csz: int = int(base_w.decode_u32(vpos + 4))
			var new_csz: int = maxi(12, base_csz - trim_i)
			var w_trim := base_w.slice(0, vpos + 8 + new_csz)
			w_trim.encode_u32(vpos + 4, new_csz)
			if (new_csz & 1) == 1:
				w_trim.append(0)
			w_trim.encode_u32(4, w_trim.size() - 8)
			out["img_bad_adv"]["webp_tail_%s_%d" % [p_lbl, trim_i]] = ah_bmp.publish_local_bytes(w_trim, "webp", h_bmp, s_bmp)

	for wtv: Dictionary in cfg.get("webp_tail_vectors", []):
		var wt_id: String = str(wtv["id"])
		var wt_bytes: PackedByteArray = Marshalls.base64_to_raw(str(wtv["b64"]))
		out["webp_tail_parity"][wt_id] = ah_bmp.publish_local_bytes(wt_bytes, "webp", h_bmp, s_bmp)

	for vcc: Dictionary in cfg.get("vp8l_const_cases", []):
		var vc_id: String = str(vcc["id"])
		var vc_bytes: PackedByteArray = Marshalls.base64_to_raw(str(vcc["b64"]))
		var vc_t0: int = Time.get_ticks_msec()
		var vc_res: Dictionary = ah_bmp.publish_local_bytes(vc_bytes, "webp", h_bmp, s_bmp)
		var vc_dt: int = Time.get_ticks_msec() - vc_t0
		var vc_row: Dictionary = {
			"ok": bool(vc_res.get("ok", false)),
			"reason": str(vc_res.get("reason", "")),
			"ms": vc_dt,
		}
		if bool(vcc.get("check_native", false)):
			var vc_im := Image.new()
			vc_row["native_err"] = int(vc_im.load_webp_from_buffer(vc_bytes))
			vc_row["native_w"] = vc_im.get_width()
			vc_row["native_h"] = vc_im.get_height()
		out["vp8l_const"][vc_id] = vc_row

	for adc: Dictionary in cfg.get("actor_dup_cases", []):
		var ad_id: String = str(adc["id"])
		var ad_path: String = str(adc["path"])
		var ad_opts: Dictionary = adc.get("opts", {})
		var h_ad := Tier5MockHost.new()
		h_ad.root = run_dir.path_join("ad_root_" + ad_id)
		h_ad.destination = run_dir.path_join("ad_dest_" + ad_id)
		var ad_prep: Dictionary = entry.prepare_import(ad_path, ad_opts, h_ad)
		var ad_row: Dictionary = {
			"ok": bool(ad_prep.get("ok", false)),
			"reason": str(ad_prep.get("reason", "")),
			"warnings": h_ad.warnings,
		}
		if bool(ad_prep.get("ok", false)):
			var w_ad: Dictionary = ad_prep["world"]
			ad_row["v3_errs"] = _validate_world_v3_quick(w_ad)
			var seen_eids: Dictionary = {}
			var dup_eids: Array[String] = []
			var tok_sprites: Array[String] = []
			var ents_ad: Array = w_ad.get("entity_state", {}).get("entities", [])
			for e_ad: Dictionary in ents_ad:
				var eid_ad: String = str(e_ad.get("id", ""))
				if seen_eids.has(eid_ad):
					dup_eids.append(eid_ad)
				seen_eids[eid_ad] = true
				for c_ad: Variant in e_ad.get("components", []):
					if c_ad is Dictionary and str((c_ad as Dictionary).get("script", "")).ends_with("comp_visual.gd"):
						tok_sprites.append(str((c_ad as Dictionary).get("state", {}).get("sprite_path", "")))
			var st_ad: Dictionary = w_ad.get("modules", {}).get("entries", {}).get("fvtt_world_importer", {}).get("state", {})
			var arch_sprites: Array[String] = []
			for aa_row: Dictionary in st_ad.get("actors", []):
				arch_sprites.append(str(aa_row.get("sprite_ref", "")))
			ad_row["ent_count"] = ents_ad.size()
			ad_row["unique_id_count"] = seen_eids.size()
			ad_row["dup_ids"] = dup_eids
			ad_row["tok_sprites"] = tok_sprites
			ad_row["arch_sprites"] = arch_sprites
		out["actor_dup_cases"][ad_id] = ad_row

	# O. Phase 2 Iter 13: Integration edge cases (non-ASCII 0-byte CD, evil archive_image, post-map entry cancel)
	out["integ_t5"]["cd_nonascii_0b"] = entry._sum_zip_cd_uncompressed(str(cfg["z_nonascii_0b"]))
	var h_evil := Tier5MockHost.new()
	h_evil.evil_archive = true
	out["integ_t5"]["evil_archive_strict"] = entry.prepare_import(str(cfg["d_rem_evil"]), {"skip_missing_assets": false, "download_remote_assets": true}, h_evil)
	var h_pc := Tier5MockHost.new()
	h_pc.root = run_dir.path_join("pc_entry_root")
	h_pc.destination = run_dir.path_join("pc_entry_dest")
	h_pc.cancel_after_finish_geom = true
	var pc_entry_res: Dictionary = entry.prepare_import(str(cfg["d_post_cancel"]), {"skip_missing_assets": false, "register_entity_library": true}, h_pc)
	var pc_rem: Array = []
	var pc_da := DirAccess.open(h_pc.destination.path_join("assets"))
	if pc_da != null:
		pc_da.list_dir_begin()
		var pcf: String = pc_da.get_next()
		while not pcf.is_empty():
			if not pcf.begins_with("."):
				pc_rem.append(pcf)
			pcf = pc_da.get_next()
	out["integ_t5"]["entry_post_map_cancel"] = {"res": pc_entry_res, "rem_assets": pc_rem}

	# P. Optional bgdia full image sweep (0 false-positive rejections)
	for bg_item: Dictionary in cfg.get("bgdia_images", []):
		out["bgdia_sweep"]["total"] += 1
		var bg_bs := FileAccess.get_file_as_bytes(str(bg_item["path"]))
		var bg_r: Dictionary = ah_bmp.publish_local_bytes(bg_bs, str(bg_item["ext"]), null, null)
		if bool(bg_r.get("ok", false)):
			out["bgdia_sweep"]["ok"] += 1
		else:
			(out["bgdia_sweep"]["fails"] as Array).append({"path": bg_item["path"], "reason": bg_r.get("reason", "")})

	# Q. Challenger 1 Gap: prevalidate_local_refs() >512 batching + batch.size()==1, >128 MiB split, mid-collection & inter-batch cancel
	var pv_refs_513: Array[String] = []
	var pv_assets_513: Dictionary = {}
	var pv_bytes_513: Dictionary = {}
	for i513: int in range(513):
		var p_key: String = ""
		var p_ext: String = ""
		var p_raw := PackedByteArray()
		if i513 < 100:
			p_key = "pv_png_%03d.png" % i513
			p_ext = "png"
			var im_pv := Image.create(2, 2, false, Image.FORMAT_RGBA8)
			im_pv.fill(Color(float(i513) / 255.0, float((i513 * 7) & 255) / 255.0, 0.4, 1.0))
			p_raw = im_pv.save_png_to_buffer()
		elif i513 < 500:
			p_key = "pv_svg_%03d.svg" % i513
			p_ext = "svg"
			p_raw = ('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><rect id="r%d" width="2" height="2"/></svg>' % i513).to_utf8_buffer()
		elif i513 < 506:
			p_key = "pv_badpng_%03d.png" % i513
			p_ext = "png"
			p_raw = ("BADPNG_%03d" % i513).to_utf8_buffer()
		else:
			p_key = "pv_badsvg_%03d.svg" % i513
			p_ext = "svg"
			p_raw = ("<svg><broken_%03d" % i513).to_utf8_buffer()
		pv_refs_513.append(p_key)
		pv_assets_513[p_key] = {"kind": "local", "resolved_path_or_url": p_key, "ext": p_ext, "exists": true}
		pv_bytes_513[p_key] = p_raw

	var src_pv_pre := _MockPrevalSource.new(pv_bytes_513)
	var src_pv_seq := _MockPrevalSource.new(pv_bytes_513)
	var h_pv_pre := Tier5MockHost.new()
	var h_pv_seq := Tier5MockHost.new()
	var s_pv_pre = sdk_scr.new().create_session(h_pv_pre, {})
	var s_pv_seq = sdk_scr.new().create_session(h_pv_seq, {})
	var ah_pv_pre: RefCounted = assets_scr.new()
	var ah_pv_seq: RefCounted = assets_scr.new()
	ah_pv_pre.prevalidate_local_refs(pv_refs_513, pv_assets_513, src_pv_pre, s_pv_pre)
	var pv_cache_before: int = (ah_pv_pre.get("_prep_cache") as Dictionary).size()
	var pv_ok_cnt: int = 0
	var pv_fail_cnt: int = 0
	var pv_mismatch: int = 0
	for rk513: String in pv_refs_513:
		var r_pre: Dictionary = ah_pv_pre.resolve_sprite_ref(rk513, pv_assets_513[rk513], src_pv_pre, h_pv_pre, s_pv_pre, {"skip_missing_assets": true})
		var r_seq: Dictionary = ah_pv_seq.resolve_sprite_ref(rk513, pv_assets_513[rk513], src_pv_seq, h_pv_seq, s_pv_seq, {"skip_missing_assets": true})
		if (
			bool(r_pre.get("ok", false)) != bool(r_seq.get("ok", false))
			or str(r_pre.get("sprite_path", "")) != str(r_seq.get("sprite_path", ""))
			or str(r_pre.get("status", "")) != str(r_seq.get("status", ""))
		):
			pv_mismatch += 1
		if str(r_pre.get("status", "")) == "local_published":
			pv_ok_cnt += 1
		else:
			pv_fail_cnt += 1
	var pv_cache_after: int = (ah_pv_pre.get("_prep_cache") as Dictionary).size()

	# >128 MiB split (3 x 4096x4096 24-bit BMPs ~= 151 MB)
	var bmp_bytes_map: Dictionary = {}
	var bmp_assets_map: Dictionary = {}
	var bmp_refs: Array[String] = []
	for bi: int in range(3):
		var bkey: String = "big_%d.bmp" % bi
		bmp_refs.append(bkey)
		bmp_assets_map[bkey] = {"kind": "local", "resolved_path_or_url": bkey, "ext": "bmp", "exists": true}
		bmp_bytes_map[bkey] = _make_24bit_bmp(4096, 4096, bi + 1)
	var ah_128m: RefCounted = assets_scr.new()
	var h_128m := Tier5MockHost.new()
	var s_128m = sdk_scr.new().create_session(h_128m, {})
	var src_128m := _MockPrevalSource.new(bmp_bytes_map)
	ah_128m.prevalidate_local_refs(bmp_refs, bmp_assets_map, src_128m, s_128m)
	var bmp128_cache_sz: int = (ah_128m.get("_prep_cache") as Dictionary).size()
	var bmp128_sprites: Array[String] = []
	for br: String in bmp_refs:
		var br_res: Dictionary = ah_128m.resolve_sprite_ref(br, bmp_assets_map[br], src_128m, h_128m, s_128m, {"skip_missing_assets": false})
		bmp128_sprites.append(str(br_res.get("sprite_path", "")))
	bmp_bytes_map.clear()

	# Mid-collection cancel & inter-batch cancel (520 unique SVGs)
	var mc_refs: Array[String] = []
	var mc_assets: Dictionary = {}
	var mc_bytes: Dictionary = {}
	for mci: int in range(520):
		var mck: String = "mc_%03d.svg" % mci
		mc_refs.append(mck)
		mc_assets[mck] = {"kind": "local", "resolved_path_or_url": mck, "ext": "svg", "exists": true}
		mc_bytes[mck] = ('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><rect id="m%d" width="1" height="1"/></svg>' % mci).to_utf8_buffer()

	var h_mc := Tier5MockHost.new()
	var s_mc = sdk_scr.new().create_session(h_mc, {})
	var src_mc := _MockPrevalSource.new(mc_bytes)
	src_mc.cancel_host = h_mc
	src_mc.cancel_at_read = 100
	var ah_mc: RefCounted = assets_scr.new()
	ah_mc.prevalidate_local_refs(mc_refs, mc_assets, src_mc, s_mc)

	var s_ib := _InterBatchCancelSession.new()
	s_ib.cancel_on_check = 523
	var src_ib := _MockPrevalSource.new(mc_bytes)
	var ah_ib: RefCounted = assets_scr.new()
	ah_ib.prevalidate_local_refs(mc_refs, mc_assets, src_ib, s_ib)

	out["preval_t5"] = {
		"proc_count": OS.get_processor_count(),
		"batch513_cache_before": pv_cache_before,
		"batch513_cache_after": pv_cache_after,
		"batch513_ok": pv_ok_cnt,
		"batch513_fail": pv_fail_cnt,
		"batch513_mismatch": pv_mismatch,
		"bmp128_cache_sz": bmp128_cache_sz,
		"bmp128_sprites": bmp128_sprites,
		"mid_cancel_reads": src_mc.read_count,
		"mid_cancel_cache_sz": (ah_mc.get("_prep_cache") as Dictionary).size(),
		"inter_batch_checks": s_ib.checks,
		"inter_batch_cache_sz": (ah_ib.get("_prep_cache") as Dictionary).size(),
	}

	# R. Challenger 2 Challenges 2-5
	# R2: Extreme grid_size (1e-308, 1e-20, 1e40) through entry.prepare_import()
	for g_case: Dictionary in cfg.get("r17_grid_cases", []):
		var gc_id: String = str(g_case["id"])
		var gc_path: String = str(g_case["path"])
		var h_gc := Tier5MockHost.new()
		var pr_gc: Dictionary = entry.prepare_import(gc_path, {"skip_missing_assets": false}, h_gc)
		var gc_row: Dictionary = {
			"ok": pr_gc.get("ok", false),
			"reason": pr_gc.get("reason", ""),
			"counts": pr_gc.get("counts", {}),
			"warnings": h_gc.warnings,
		}
		if bool(pr_gc.get("ok", false)):
			var w_gc: Dictionary = pr_gc["world"]
			gc_row["v3_errs"] = _validate_world_v3_quick(w_gc)
			gc_row["all_finite"] = _check_all_floats_finite(w_gc)
			var unit_sizes: Array = []
			var obstacles: Array = []
			var all_xform_finite: bool = true
			for ent_g: Dictionary in w_gc.get("entity_state", {}).get("entities", []):
				var xf: Dictionary = ent_g.get("xform", {})
				var p_v: Variant = xf.get("pos", Vector2.ZERO)
				if p_v is Vector2 and not (is_finite((p_v as Vector2).x) and is_finite((p_v as Vector2).y)):
					all_xform_finite = false
				var sz_v: Variant = ent_g.get("entity_size", Vector2.ZERO)
				if sz_v is Vector2 and not (is_finite((sz_v as Vector2).x) and is_finite((sz_v as Vector2).y)):
					all_xform_finite = false
				var sc_v: Variant = xf.get("scale", Vector2.ONE)
				for cg: Variant in ent_g.get("components", []):
					if cg is Dictionary and str((cg as Dictionary).get("script", "")).ends_with("comp_unit.gd"):
						if sz_v is Vector2:
							unit_sizes.append([(sz_v as Vector2).x, (sz_v as Vector2).y])
					elif cg is Dictionary and str((cg as Dictionary).get("script", "")).ends_with("comp_visual.gd"):
						var vd_g: Variant = (cg as Dictionary).get("state", {}).get("vector_drawing", null)
						if vd_g is Dictionary and not (vd_g as Dictionary).is_empty():
							var vdd: Dictionary = vd_g as Dictionary
							var obs_kind: String = str(vdd.get("source", {}).get("kind", ""))
							var obs_paths: Array = vdd.get("paths", [])
							if not obs_paths.is_empty() and sz_v is Vector2 and p_v is Vector2 and sc_v is Vector2:
								var norm_ring: PackedVector2Array = obs_paths[0]
								var sz_vec: Vector2 = sz_v as Vector2
								var pos_vec: Vector2 = p_v as Vector2
								var sc_vec: Vector2 = sc_v as Vector2
								var local_ring: Array[Vector2] = []
								var max_local_pt: float = 0.0
								var max_world_pt: float = 0.0
								for np: Vector2 in norm_ring:
									var lp: Vector2 = np * sz_vec
									var wp: Vector2 = pos_vec + lp * sc_vec
									local_ring.append(lp)
									max_local_pt = maxf(max_local_pt, maxf(absf(lp.x), absf(lp.y)))
									max_world_pt = maxf(max_world_pt, maxf(absf(wp.x), absf(wp.y)))
								var p0_eq_p3: bool = local_ring.size() >= 4 and local_ring[0] == local_ring[3]
								var p1_eq_p2: bool = local_ring.size() >= 4 and local_ring[1] == local_ring[2]
								var area2: float = absf((local_ring[1] - local_ring[0]).cross(local_ring[2] - local_ring[0])) if local_ring.size() >= 3 else 0.0
								obstacles.append({
									"kind": obs_kind,
									"max_local_pt": max_local_pt,
									"max_world_pt": max_world_pt,
									"p0_eq_p3": p0_eq_p3,
									"p1_eq_p2": p1_eq_p2,
									"area2": area2,
								})
			gc_row["all_xform_finite"] = all_xform_finite
			gc_row["unit_sizes"] = unit_sizes
			gc_row["obstacles"] = obstacles
		out["r17_grid"][gc_id] = gc_row

	# R3: ./world.json ZIP + duplicate ./world.json deduplication + cyclic directory junction
	for s_case: Dictionary in cfg.get("r17_source_cases", []):
		var sc_id: String = str(s_case["id"])
		var sc_path: String = str(s_case["path"])
		var h_sc := Tier5MockHost.new()
		var ins_sc: Dictionary = entry.inspect_import(sc_path, {"skip_missing_assets": false}, h_sc)
		var prep_sc: Dictionary = entry.prepare_import(sc_path, {"skip_missing_assets": false}, h_sc)
		var o_sc: Dictionary = src.open(sc_path)
		src.close()
		var cd_sum_sc: int = entry._sum_zip_cd_uncompressed(sc_path) if sc_path.to_lower().ends_with(".zip") else -1
		out["r17_src"][sc_id] = {
			"open_ok": o_sc.get("ok", false),
			"open_decoded_bytes": o_sc.get("decoded_bytes", -1),
			"open_warnings": o_sc.get("warnings", []),
			"ins_ok": ins_sc.get("ok", false),
			"ins_decoded_bytes": ins_sc.get("decoded_bytes", -1),
			"cd_sum_bytes": cd_sum_sc,
			"prep_ok": prep_sc.get("ok", false),
			"prep_reason": prep_sc.get("reason", ""),
			"prep_counts": prep_sc.get("counts", {}),
			"warnings": h_sc.warnings,
		}

	# R4: LevelDB partial missing SSTable + missing MANIFEST + embedded levels
	for l_case: Dictionary in cfg.get("r17_ldb_cases", []):
		var lc_id: String = str(l_case["id"])
		var lc_path: String = str(l_case["path"])
		var o_lc: Dictionary = src.open(lc_path)
		var col_lc: Dictionary = leveldb.read_collection(src, "scenes", snappy)
		src.close()
		var h_lc := Tier5MockHost.new()
		var prep_lc: Dictionary = entry.prepare_import(lc_path, {"skip_missing_assets": false}, h_lc)
		out["r17_ldb"][lc_id] = {
			"open_ok": o_lc.get("ok", false),
			"col_ok": col_lc.get("ok", false),
			"doc_ids": (col_lc.get("docs", []) as Array).map(func(d: Variant) -> String: return str((d as Dictionary).get("_id", ""))),
			"col_warnings": col_lc.get("warnings", []),
			"prep_ok": prep_lc.get("ok", false),
			"host_warnings": h_lc.warnings,
		}
	var emb_wj: String = str(cfg.get("r17_emb_levels_wj", ""))
	if not emb_wj.is_empty():
		var o_emb: Dictionary = src.open(emb_wj)
		var nr_emb: Dictionary = norm.normalize(
			o_emb.get("world_json", {}),
			{"scenes": nedb.read_collection(src, "scenes"), "actors": nedb.read_collection(src, "actors")},
			src,
			{}
		)
		src.close()
		var h_emb := Tier5MockHost.new()
		var prep_emb: Dictionary = entry.prepare_import(emb_wj, {"skip_missing_assets": false}, h_emb)
		var emb_bg: String = ""
		if bool(nr_emb.get("ok", false)) and not (nr_emb["model"]["scenes"] as Array).is_empty():
			emb_bg = str(((nr_emb["model"]["scenes"] as Array)[0] as Dictionary).get("background_ref", ""))
		out["r17_ldb"]["embedded_levels"] = {
			"norm_ok": nr_emb.get("ok", false),
			"bg_ref": emb_bg,
			"prep_ok": prep_emb.get("ok", false),
			"prep_counts": prep_emb.get("counts", {}),
		}

	# R5: INT64_MIN ability score modifier (no signed int64 underflow wrap)
	var nr_i64: Dictionary = norm.normalize(
		{"id": "i64", "title": "Int64Min", "system": "dnd5e", "coreVersion": "12"},
		{
			"scenes": {"ok": true, "docs": [], "sublevels": {}},
			"actors": {
				"ok": true,
				"docs": [{
					"_id": "a_i64",
					"name": "MinAb",
					"type": "npc",
					"system": {
						"abilities": {
							"str": {"value": "-9223372036854775808"},
							"dex": {"value": "9223372036854775807"},
						}
					},
				}],
				"sublevels": {},
			},
		},
		null,
		{}
	)
	var i64_str_mod: Variant = null
	var i64_dex_mod: Variant = null
	if bool(nr_i64.get("ok", false)) and not (nr_i64["model"]["actors"] as Array).is_empty():
		var abs_i64: Dictionary = ((nr_i64["model"]["actors"] as Array)[0] as Dictionary).get("abilities", {})
		i64_str_mod = (abs_i64.get("str", {}) as Dictionary).get("mod", null)
		i64_dex_mod = (abs_i64.get("dex", {}) as Dictionary).get("mod", null)
	out["r17_norm"] = {
		"ok": nr_i64.get("ok", false),
		"str_mod": i64_str_mod,
		"dex_mod": i64_dex_mod,
	}

	var fo := FileAccess.open(out_path, FileAccess.WRITE)
	fo.store_string(JSON.stringify(out, "\t"))
	fo.close()
	quit(0)

class _MockByteSource extends RefCounted:
	var _m: Dictionary = {}
	func _init(m: Dictionary) -> void: _m = m
	func get_last_read_error() -> String: return ""
	func read_bytes(p: String) -> PackedByteArray: return _m.get(p, PackedByteArray())

class _MockPrevalSource extends RefCounted:
	var _m: Dictionary = {}
	var read_count: int = 0
	var cancel_host: Tier5MockHost = null
	var cancel_at_read: int = -1
	func _init(m: Dictionary) -> void: _m = m
	func get_last_read_error() -> String: return ""
	func read_bytes(p: String) -> PackedByteArray:
		read_count += 1
		if cancel_host != null and cancel_at_read > 0 and read_count >= cancel_at_read:
			cancel_host.cancel_flag = true
		return _m.get(p, PackedByteArray())

class _InterBatchCancelSession extends RefCounted:
	var checks: int = 0
	var cancel_on_check: int = -1
	var warnings: Array[String] = []
	func is_cancelled() -> bool:
		checks += 1
		return cancel_on_check > 0 and checks >= cancel_on_check
	func add_warning(m: String) -> void: warnings.append(m)
	func validate_sprite_path(p: String) -> String: return p

static func _make_24bit_bmp(w: int, h: int, tag_byte: int) -> PackedByteArray:
	var row_stride: int = ((w * 24 + 31) >> 5) << 2
	var pix_sz: int = row_stride * h
	var fsize: int = 54 + pix_sz
	var buf := PackedByteArray()
	buf.resize(fsize)
	buf[0] = 0x42
	buf[1] = 0x4D
	buf.encode_u32(2, fsize)
	buf.encode_u32(10, 54)
	buf.encode_u32(14, 40)
	buf.encode_s32(18, w)
	buf.encode_s32(22, h)
	buf.encode_u16(26, 1)
	buf.encode_u16(28, 24)
	buf.encode_u32(34, pix_sz)
	buf[54] = tag_byte & 0xFF
	return buf
'''


class TestFvttTier5Adversarial(unittest.TestCase):
    run_dir: Path
    results: dict
    dup_expected_bytes: int
    rfc_shas: dict[str, str]
    bgdia_wj: Path | None = None
    has_bgdia_dir: bool = False
    webp_tail_oracle: dict[str, dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_WORKSPACE_ROOT)
        if cfg.godot_bin is None or not cfg.godot_bin.is_file():
            raise unittest.SkipTest("GODOT_BIN unavailable")
        cls.run_dir = TEST_TMP_ROOT / f"tier5_adv_{uuid.uuid4().hex[:10]}"
        probe_dir = cls.run_dir / "probe"
        fdir = cls.run_dir / "fixtures"
        probe_dir.mkdir(parents=True, exist_ok=True)
        fdir.mkdir(parents=True, exist_ok=True)
        try:
            (probe_dir / "project.godot").write_text('config_version=5\n[application]\nconfig/name="tier5"\n', encoding="utf-8")
            (probe_dir / "probe.gd").write_text(_TIER5_PROBE_GD, encoding="utf-8")
            png = make_png_bytes(4, 4)
            png_pre = make_png_bytes(2, 2)
            png_new = make_png_bytes(3, 3)
            png_p = fdir / "sample.png"
            pre_png_p = fdir / "pre.png"
            new_png_p = fdir / "new.png"
            png_p.write_bytes(png)
            pre_png_p.write_bytes(png_pre)
            new_png_p.write_bytes(png_new)

            wj_b = json.dumps(make_v9_world_json(name="t5", title="Tier5")).encode("utf-8")
            sc_b = (json.dumps(make_v9_scene("s1", "S1")) + "\n").encode("utf-8")
            ac_b = (json.dumps(make_v9_actor("a1", "A1")) + "\n").encode("utf-8")

            entry_cases: list[dict] = []

            # 1. Corrupt deflate/CRC with intact EOCD/CD/LFH
            z_bad_wj_crc = fdir / "bad_wj_crc.zip"
            _build_raw_zip(z_bad_wj_crc, [{"name_bytes": b"world.json", "payload": wj_b, "crc": (zlib.crc32(wj_b) ^ 1) & 0xFFFFFFFF}])
            entry_cases.append({"id": "zip_wj_bad_crc", "path": str(z_bad_wj_crc)})

            z_bad_db_def = fdir / "bad_db_def.zip"
            _build_raw_zip(z_bad_db_def, [
                {"name_bytes": b"world.json", "payload": wj_b},
                {"name_bytes": b"data/scenes.db", "payload": sc_b, "comp_bytes": b"\x06\x00"},
                {"name_bytes": b"data/actors.db", "payload": ac_b},
            ])
            entry_cases.append({"id": "zip_db_bad_deflate", "path": str(z_bad_db_def)})

            v14_dir = fdir / "v14_src"
            build_v14_world(v14_dir, world_json=make_v14_world_json(world_id="v14z", title="V14Z"), scenes=[make_v9_scene("s1", "S1")], actors=[make_v9_actor("a1", "A1")])
            wj14_b = (v14_dir / "world.json").read_bytes()
            ldb_b = (v14_dir / "data" / "scenes" / "000005.ldb").read_bytes()
            man_b = (v14_dir / "data" / "scenes" / "MANIFEST-000001").read_bytes()
            cur_b = (v14_dir / "data" / "scenes" / "CURRENT").read_bytes()
            wal_b = build_wal_bytes([encode_write_batch(10, [("put", b"!scenes!s2", json.dumps(make_v9_scene("s2", "S2")).encode("utf-8"))])])
            act_ldb_b = (v14_dir / "data" / "actors" / "000005.ldb").read_bytes()
            act_man_b = (v14_dir / "data" / "actors" / "MANIFEST-000001").read_bytes()
            act_cur_b = (v14_dir / "data" / "actors" / "CURRENT").read_bytes()

            z_bad_ldb_crc = fdir / "bad_ldb_crc.zip"
            _build_raw_zip(z_bad_ldb_crc, [
                {"name_bytes": b"world.json", "payload": wj14_b},
                {"name_bytes": b"data/scenes/000005.ldb", "payload": ldb_b, "crc": (zlib.crc32(ldb_b) ^ 1) & 0xFFFFFFFF},
                {"name_bytes": b"data/scenes/MANIFEST-000001", "payload": man_b},
                {"name_bytes": b"data/scenes/CURRENT", "payload": cur_b},
                {"name_bytes": b"data/actors/000005.ldb", "payload": act_ldb_b},
                {"name_bytes": b"data/actors/MANIFEST-000001", "payload": act_man_b},
                {"name_bytes": b"data/actors/CURRENT", "payload": act_cur_b},
            ])
            entry_cases.append({"id": "zip_ldb_bad_crc", "path": str(z_bad_ldb_crc)})

            z_bad_wal_def = fdir / "bad_wal_def.zip"
            _build_raw_zip(z_bad_wal_def, [
                {"name_bytes": b"world.json", "payload": wj14_b},
                {"name_bytes": b"data/scenes/000005.ldb", "payload": ldb_b},
                {"name_bytes": b"data/scenes/000006.log", "payload": wal_b, "comp_bytes": b"\x06\x00"},
                {"name_bytes": b"data/scenes/MANIFEST-000001", "payload": man_b},
                {"name_bytes": b"data/scenes/CURRENT", "payload": cur_b},
                {"name_bytes": b"data/actors/000005.ldb", "payload": act_ldb_b},
                {"name_bytes": b"data/actors/MANIFEST-000001", "payload": act_man_b},
                {"name_bytes": b"data/actors/CURRENT", "payload": act_cur_b},
            ])
            entry_cases.append({"id": "zip_wal_bad_deflate", "path": str(z_bad_wal_def)})

            # 2. Corrupt Snappy and corrupt LevelDB block in scenes while actors is valid (+ v10 NeDB fallback must not bypass)
            bad_snappy = b"\x05\xff\xff\xff\xff\xff"
            bad_sn_f = bad_snappy + b"\x01" + struct.pack("<I", leveldb_masked_crc32c(bad_snappy + b"\x01"))
            ikey = b"!scenes!s1" + struct.pack("<Q", (1 << 8) | 1)
            idx_v = _encode_varint32(0) + _encode_varint32(len(bad_snappy))
            idx_r = _encode_varint32(0) + _encode_varint32(len(ikey)) + _encode_varint32(len(idx_v)) + ikey + idx_v + struct.pack("<II", 0, 1)
            idx_f = idx_r + b"\x00" + struct.pack("<I", leveldb_masked_crc32c(idx_r + b"\x00"))
            meta_r = struct.pack("<II", 0, 1)
            meta_f = meta_r + b"\x00" + struct.pack("<I", leveldb_masked_crc32c(meta_r + b"\x00"))
            h_sn = _encode_varint32(len(bad_sn_f) + len(idx_f)) + _encode_varint32(len(meta_r)) + _encode_varint32(len(bad_sn_f)) + _encode_varint32(len(idx_r))
            sst_bad_sn = bad_sn_f + idx_f + meta_f + h_sn.ljust(40, b"\x00") + struct.pack("<Q", 0xDB4775248B80FB57)

            d_snappy = fdir / "dir_bad_snappy"
            build_v14_world(d_snappy, world_json=make_v14_world_json(world_id="bsn", title="BadSnappy"), scenes=[make_v9_scene("s1", "S1")], actors=[make_v9_actor("a1", "A1")])
            (d_snappy / "data" / "scenes" / "000005.ldb").write_bytes(sst_bad_sn)
            (d_snappy / "data" / "scenes" / "MANIFEST-000001").write_bytes(build_manifest_bytes(ldb_files=[(5, len(sst_bad_sn), ikey, ikey)], log_number=6, next_file_number=7, last_sequence=1))
            entry_cases.append({"id": "dir_ldb_bad_snappy", "path": str(d_snappy / "world.json")})

            # v10 world with BOTH data/scenes.db and corrupt Snappy data/scenes/000005.ldb -> must hard-fail!
            d_snappy_v10 = fdir / "dir_v10_bad_snappy"
            build_v14_world(d_snappy_v10, world_json=make_v9_world_json(name="v10sn", title="V10Sn", core_version="10.291"), scenes=[make_v9_scene("s1", "S1")], actors=[make_v9_actor("a1", "A1")])
            (d_snappy_v10 / "data" / "scenes" / "000005.ldb").write_bytes(sst_bad_sn)
            (d_snappy_v10 / "data" / "scenes" / "MANIFEST-000001").write_bytes(build_manifest_bytes(ldb_files=[(5, len(sst_bad_sn), ikey, ikey)], log_number=6, next_file_number=7, last_sequence=1))
            (d_snappy_v10 / "data" / "scenes.db").write_bytes(sc_b)
            entry_cases.append({"id": "dir_v10_ldb_bad_snappy", "path": str(d_snappy_v10 / "world.json")})

            # Corrupt LevelDB block (block_invalid_restarts)
            sst_bad_blk, blk_ikey = _make_corrupt_sstable_block_bytes()
            d_blk = fdir / "dir_bad_block"
            build_v14_world(d_blk, world_json=make_v14_world_json(world_id="bblk", title="BadBlock"), scenes=[make_v9_scene("s1", "S1")], actors=[make_v9_actor("a1", "A1")])
            (d_blk / "data" / "scenes" / "000005.ldb").write_bytes(sst_bad_blk)
            (d_blk / "data" / "scenes" / "MANIFEST-000001").write_bytes(build_manifest_bytes(ldb_files=[(5, len(sst_bad_blk), blk_ikey, blk_ikey)], log_number=6, next_file_number=7, last_sequence=1))
            entry_cases.append({"id": "dir_ldb_bad_block", "path": str(d_blk / "world.json")})

            # 3. ZIP structural cases
            z_dup = fdir / "dup_cd.zip"
            sc_pad = sc_b + b" " * 500
            _build_raw_zip(z_dup, [
                {"name_bytes": b"world.json", "payload": wj_b, "comp_method": 0},
                {"name_bytes": b"data/scenes.db", "payload": sc_pad, "comp_method": 0},
                {"name_bytes": b"data/scenes.db", "payload": sc_pad, "comp_method": 0},
                {"name_bytes": b"data/actors.db", "payload": ac_b, "comp_method": 0},
            ])
            entry_cases.append({"id": "zip_dup_cd", "path": str(z_dup)})
            cls.dup_expected_bytes = len(wj_b) + len(sc_pad) + len(ac_b)

            z_dd = fdir / "dd.zip"
            _build_raw_zip(z_dd, [
                {"name_bytes": b"world.json", "payload": wj_b, "flags": 0x0008, "dd_sig": True},
                {"name_bytes": b"data/scenes.db", "payload": sc_b, "flags": 0x0008, "dd_sig": False},
                {"name_bytes": b"data/actors.db", "payload": ac_b, "flags": 0x0008, "dd_sig": True},
            ])
            entry_cases.append({"id": "zip_data_desc", "path": str(z_dd)})

            z_extra = fdir / "extra_diff.zip"
            _build_raw_zip(z_extra, [
                {"name_bytes": b"world.json", "payload": wj_b, "lfh_extra": b"ABCD", "cd_extra": b"1234567890"},
                {"name_bytes": b"data/scenes.db", "payload": sc_b},
                {"name_bytes": b"data/actors.db", "payload": ac_b},
            ])
            entry_cases.append({"id": "zip_extra_diff", "path": str(z_extra)})

            z_64 = fdir / "zip64.zip"
            _build_raw_zip(z_64, [{"name_bytes": b"world.json", "payload": wj_b}], eocd_override={"total_entries": 0xFFFF})
            entry_cases.append({"id": "zip64", "path": str(z_64)})

            z_enc = fdir / "enc.zip"
            _build_raw_zip(z_enc, [{"name_bytes": b"world.json", "payload": wj_b, "flags": 0x0001}])
            entry_cases.append({"id": "zip_encrypted", "path": str(z_enc)})

            z_meth = fdir / "meth.zip"
            _build_raw_zip(z_meth, [{"name_bytes": b"world.json", "payload": wj_b, "comp_method": 12}])
            entry_cases.append({"id": "zip_bad_method", "path": str(z_meth)})

            z_bomb = fdir / "bomb.zip"
            _build_raw_zip(z_bomb, [
                {"name_bytes": b"world.json", "payload": wj_b},
                {"name_bytes": b"data/scenes.db", "payload": sc_b, "comp_bytes": b"\x03\x00", "comp_size": 2, "uncomp_size": 5000000},
            ])
            entry_cases.append({"id": "zip_ratio_bomb", "path": str(z_bomb)})

            z_img_crc = fdir / "bad_img_crc.zip"
            sc_img = (json.dumps(make_v9_scene("s1", "Img", img="worlds/t5/assets/bg.png")) + "\n").encode("utf-8")
            _build_raw_zip(z_img_crc, [
                {"name_bytes": b"world.json", "payload": wj_b},
                {"name_bytes": b"data/scenes.db", "payload": sc_img},
                {"name_bytes": b"data/actors.db", "payload": ac_b},
                {"name_bytes": b"assets/bg.png", "payload": png, "crc": (zlib.crc32(png) ^ 0x12345678) & 0xFFFFFFFF},
            ])
            entry_cases.append({"id": "zip_bad_img_strict", "path": str(z_img_crc), "opts": {"skip_missing_assets": False}})
            entry_cases.append({"id": "zip_bad_img_skip", "path": str(z_img_crc), "opts": {"skip_missing_assets": True}})

            # 4. Multi-block Snappy SSTable + Sequence collision inside SSTable
            d_mb = fdir / "ldb_multiblock"
            scs_40 = [make_v9_scene(f"sc_{i:02d}", f"MB_{i:02d}") for i in range(40)]
            build_v14_world(d_mb, world_json=make_v14_world_json(world_id="mb", title="MB"), scenes=scs_40, actors=[make_v9_actor("a1", "A1")])
            recs_40 = [(f"!scenes!sc_{i:02d}".encode("utf-8"), 10 + i, 1, json.dumps(scs_40[i]).encode("utf-8")) for i in range(40)]
            sst_mb, mb_min, mb_max = build_sstable_bytes(recs_40, compress_snappy=True, block_size=256)
            (d_mb / "data" / "scenes" / "000005.ldb").write_bytes(sst_mb)
            (d_mb / "data" / "scenes" / "MANIFEST-000001").write_bytes(build_manifest_bytes(ldb_files=[(5, len(sst_mb), mb_min, mb_max)], log_number=6, next_file_number=7, last_sequence=50))
            entry_cases.append({"id": "ldb_multiblock_snappy", "path": str(d_mb / "world.json")})

            d_seq = fdir / "ldb_seq_col"
            build_v14_world(d_seq, world_json=make_v14_world_json(world_id="scol", title="SeqCol"), scenes=[make_v9_scene("s1", "Alive")], actors=[make_v9_actor("a1", "A1")])
            sst_col, cmin, cmax = build_sstable_bytes([
                (b"!scenes!s1", 10, 1, json.dumps(make_v9_scene("s1", "AliveAtSameSeq")).encode("utf-8")),
                (b"!scenes!s1", 10, 0, b""),
            ])
            (d_seq / "data" / "scenes" / "000005.ldb").write_bytes(sst_col)
            (d_seq / "data" / "scenes" / "MANIFEST-000001").write_bytes(build_manifest_bytes(ldb_files=[(5, len(sst_col), cmin, cmax)], log_number=6, next_file_number=7, last_sequence=10))
            entry_cases.append({"id": "ldb_seq_collision", "path": str(d_seq / "world.json")})

            # 5. Normalizer adversarial cases
            d_ext = fdir / "norm_ext"
            sc_ext = make_v9_scene("s_ext", "Ext", width=1e200, height=1e200, grid=-50)
            sc_ext["padding"] = 1e200
            sc_ext["walls"] = [
                make_wall("w_nan", ["NaN", 0, 100, 0]),
                make_wall("w_null", [None, 0, 100, 0]),
                make_wall("w_ok", [0, 0, 100, 0]),
            ]
            a_nd = make_v9_actor(
                "a_nd", "ClumsyKnight", actor_type="character",
                abilities={"str": 16, "dex": 6, "con": 14, "int": 10, "wis": 10, "cha": 10},
                ac_flat=None, ac_calc="default",
                items=[make_armor_item("ar_p", "Plate", armor_type="heavy", armor_value=18, dex_cap=0, equipped=True)],
                biography="<p>Roll < 10 misses.</p><p>Keep this < 5 forever",
            )
            a_nd["folder"] = "fcyc1"
            a_dual = make_v9_actor(
                "a_dual", "DualArmor", actor_type="character",
                abilities={"str": 12, "dex": 18, "con": 12, "int": 10, "wis": 10, "cha": 10},
                ac_flat=None, ac_calc="default",
                items=[
                    make_armor_item("ar1", "Studded", armor_type="light", armor_value=12, dex_cap=None, equipped=True),
                    make_armor_item("ar2", "ChainShirt", armor_type="medium", armor_value=13, dex_cap=2, equipped=True),
                ],
                biography="<script>alert(1)</script><style>.h{color:red}</style><p>Bio &amp; &lt;text&gt;</p>",
            )
            deep_folders = [make_folder(f"fd_{i}", f"D{i}", parent=(f"fd_{i-1}" if i > 0 else None)) for i in range(60)]
            a_deep = make_v9_actor("a_deep", "DeepActor", actor_type="npc")
            a_deep["folder"] = "fd_59"
            build_v9_world(
                d_ext,
                world_json=make_v9_world_json(name="ext", title="Ext"),
                scenes=[sc_ext],
                actors=[a_nd, a_dual, a_deep],
                folders=deep_folders + [make_folder("fcyc1", "CycA", parent="fcyc2"), make_folder("fcyc2", "CycB", parent="fcyc1")],
            )
            entry_cases.append({"id": "norm_ext", "path": str(d_ext / "world.json")})

            # 6. RFC 1951 ZIP
            cl_order = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]
            lit_lens = [i + 1 if i < 13 else 0 for i in range(286)]
            lit_lens[65], lit_lens[256], lit_lens[285] = 14, 15, 15
            lit_c = _canonical_codes(lit_lens)
            dist_lens = [i + 1 if i < 14 else 0 for i in range(30)]
            dist_lens[14], dist_lens[29] = 15, 15
            dist_c = _canonical_codes(dist_lens)
            cl_lens = [4 if s < 15 else 0 for s in range(19)]
            cl_lens[15], cl_lens[18] = 5, 5
            cl_c = _canonical_codes(cl_lens)
            bw = _BitWriter()
            bw.write_lsb(1, 1); bw.write_lsb(2, 2)
            bw.write_lsb(286 - 257, 5); bw.write_lsb(30 - 1, 5); bw.write_lsb(19 - 4, 4)
            for s in cl_order: bw.write_lsb(cl_lens[s], 3)
            all_l = lit_lens + dist_lens
            idx = 0
            while idx < len(all_l):
                if all_l[idx] == 0:
                    j = idx
                    while j < len(all_l) and all_l[j] == 0 and (j - idx) < 138:
                        j += 1
                    if j - idx >= 11:
                        bw.write_msb(*cl_c[18]); bw.write_lsb((j - idx) - 11, 7)
                        idx = j; continue
                bw.write_msb(*cl_c[all_l[idx]])
                idx += 1
            for _ in range(24578): bw.write_msb(*lit_c[65])
            bw.write_msb(*lit_c[285]); bw.write_msb(*dist_c[29]); bw.write_lsb(1, 13); bw.write_msb(*lit_c[256])
            raw15 = bw.finish()
            exp15 = b"A" * 24836

            bw2 = _BitWriter()
            lit2 = [0] * 257
            lit2[0] = lit2[254] = lit2[255] = lit2[256] = 2
            cl2 = [0] * 19
            cl2[0] = cl2[2] = cl2[16] = cl2[18] = 2
            cl2_c = _canonical_codes(cl2)
            bw2.write_lsb(0, 1); bw2.write_lsb(2, 2)
            bw2.write_lsb(0, 5); bw2.write_lsb(3, 5); bw2.write_lsb(15, 4)
            for s in cl_order: bw2.write_lsb(cl2[s], 3)
            bw2.write_msb(*cl2_c[2])
            bw2.write_msb(*cl2_c[18]); bw2.write_lsb(138 - 11, 7)
            bw2.write_msb(*cl2_c[18]); bw2.write_lsb(115 - 11, 7)
            bw2.write_msb(*cl2_c[2]); bw2.write_msb(*cl2_c[16]); bw2.write_lsb(3, 2)
            l2_c = _canonical_codes(lit2)
            bw2.write_msb(*l2_c[0]); bw2.write_msb(*l2_c[256])
            bw2.write_lsb(0, 1); bw2.write_lsb(1, 2)
            for ch in b"XY": bw2.write_msb(0x30 + ch, 8)
            bw2.write_msb(0, 7)
            bw2.write_lsb(1, 1); bw2.write_lsb(0, 2); bw2.align_byte()
            bw2.buf.extend(struct.pack("<HH", 6, 6 ^ 0xFFFF) + b"STORED")
            raw_multi = bytes(bw2.buf)
            exp_multi = b"\x00XYSTORED"

            bw3 = _BitWriter()
            lit3 = [0] * 257
            lit3[66] = lit3[256] = 1
            cl3 = [0] * 19
            cl3[0] = cl3[1] = 2; cl3[18] = 1
            cl3_c = _canonical_codes(cl3)
            bw3.write_lsb(1, 1); bw3.write_lsb(2, 2)
            bw3.write_lsb(0, 5); bw3.write_lsb(0, 5); bw3.write_lsb(15, 4)
            for s in cl_order: bw3.write_lsb(cl3[s], 3)
            bw3.write_msb(*cl3_c[18]); bw3.write_lsb(66 - 11, 7); bw3.write_msb(*cl3_c[1])
            bw3.write_msb(*cl3_c[18]); bw3.write_lsb(138 - 11, 7)
            bw3.write_msb(*cl3_c[18]); bw3.write_lsb(51 - 11, 7)
            bw3.write_msb(*cl3_c[1]); bw3.write_msb(*cl3_c[0])
            l3_c = _canonical_codes(lit3)
            for _ in range(5): bw3.write_msb(*l3_c[66])
            bw3.write_msb(*l3_c[256])
            raw_ed = bw3.finish()
            exp_ed = b"BBBBB"

            z_rfc = fdir / "rfc.zip"
            _build_raw_zip(z_rfc, [
                {"name_bytes": b"world.json", "payload": wj_b},
                {"name_bytes": b"raw15.bin", "payload": exp15, "comp_bytes": raw15},
                {"name_bytes": b"multi.bin", "payload": exp_multi, "comp_bytes": raw_multi},
                {"name_bytes": b"empty_dist.bin", "payload": exp_ed, "comp_bytes": raw_ed},
            ])
            cls.rfc_shas = {
                "raw15.bin": hashlib.sha256(exp15).hexdigest(),
                "multi.bin": hashlib.sha256(exp_multi).hexdigest(),
                "empty_dist.bin": hashlib.sha256(exp_ed).hexdigest(),
            }

            snappy_vecs = {
                "zero_len": base64.b64encode(b"\x00").decode("ascii"),
                "trailing_zero": base64.b64encode(b"\x00\x01").decode("ascii"),
                "varint_ovf": base64.b64encode(b"\x80\x80\x80\x80\x10").decode("ascii"),
                "trunc_copy1": base64.b64encode(b"\x0a\x00A\x01").decode("ascii"),
                "trunc_copy2": base64.b64encode(b"\x0a\x00A\x02\x01").decode("ascii"),
                "trunc_copy4": base64.b64encode(b"\x0a\x00A\x03\x01\x00").decode("ascii"),
            }

            # 7. BMP BI_BITFIELDS files
            bmp_nomask_p = fdir / "bmp16_nomask.bmp"
            bmp_mask_p = fdir / "bmp16_mask.bmp"
            bmp_v4_p = fdir / "bmp32_v4.bmp"
            bmp_v5_p = fdir / "bmp32_v5.bmp"
            bmp_nomask_p.write_bytes(_make_bitfields_bmp(2, 2, 16, 40, False))
            bmp_mask_p.write_bytes(_make_bitfields_bmp(2, 2, 16, 40, True))
            bmp_v4_p.write_bytes(_make_bitfields_bmp(2, 2, 32, 108, True))
            bmp_v5_p.write_bytes(_make_bitfields_bmp(2, 2, 32, 124, True))

            # 8. Rollback world (Scene 1 publishes pre.png + new.png, Scene 2 has missing PNG -> strict fail)
            d_rb = fdir / "rb_world"
            build_v9_world(
                d_rb,
                world_json=make_v9_world_json(name="rbw", title="RBWorld"),
                scenes=[
                    make_v9_scene(
                        "s_rb1",
                        "S1",
                        img="worlds/rbw/assets/pre.png",
                        foreground="worlds/rbw/assets/new.png",
                    ),
                    make_v9_scene("s_rb2", "S2", img="worlds/rbw/assets/missing_fail.png"),
                ],
                actors=[make_v9_actor("a_rb", "RBActor")],
            )
            (d_rb / "assets").mkdir(parents=True, exist_ok=True)
            (d_rb / "assets" / "pre.png").write_bytes(png_pre)
            (d_rb / "assets" / "new.png").write_bytes(png_new)

            # 9. Simple world for null-host test & resolve_asset_ref edge cases
            d_simple = fdir / "simple_world"
            build_v9_world(
                d_simple,
                world_json=make_v9_world_json(name="simp", title="Simple"),
                scenes=[make_v9_scene("ss1", "S1")],
                actors=[make_v9_actor("sa1", "A1")],
            )
            (d_simple / "map name.png").write_bytes(png)
            (d_simple / "50%_off.png").write_bytes(png)
            (d_simple / "foo..bar.png").write_bytes(png)
            (d_simple / "assets" / "a").mkdir(parents=True, exist_ok=True)
            (d_simple / "assets" / "a" / "b.png").write_bytes(png)

            # 10. SVG variants
            svg_vecs = {
                "unquoted_root": base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" width=16 height="16"></svg>').decode("ascii"),
                "unquoted_child": base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect id=r1 x="0" y="0" width="8" height="8"/></svg>').decode("ascii"),
                "unquoted_ns_child": base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:g="http://www.w3.org/2000/svg" width="16" height="16"><g:rect id=r1 x="0" y="0" width="8" height="8"/></svg>').decode("ascii"),
                "self_close": base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"/>').decode("ascii"),
                "pct_vb_comma": base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0,0,16,16"/>').decode("ascii"),
                "vb_nan": base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 NaN 16"/>').decode("ascii"),
                "pi_comment_ns": base64.b64encode(b'<?xml version="1.0" encoding="UTF-8"?><!-- c --><s:svg xmlns:s="http://www.w3.org/2000/svg" width="16" height="16"><s:rect x="0" y="0" width="8" height="8"/></s:svg>').decode("ascii"),
            }

            # 11. Challenger 1 Iter 2 additional entry cases: d_folders_snappy, z_gbk, z_bslash, d_prev_log
            d_folders_snappy = fdir / "dir_folders_bad_snappy"
            build_v14_world(
                d_folders_snappy,
                world_json=make_v14_world_json(world_id="fsn", title="FoldersSnappy"),
                scenes=[make_v9_scene("s1", "S1")],
                actors=[make_v9_actor("a1", "A1")],
            )
            f_dir = d_folders_snappy / "data" / "folders"
            f_dir.mkdir(parents=True, exist_ok=True)
            f_ikey = b"!folders!f1" + struct.pack("<Q", (1 << 8) | 1)
            f_idx_v = _encode_varint32(0) + _encode_varint32(len(bad_snappy))
            f_idx_r = _encode_varint32(0) + _encode_varint32(len(f_ikey)) + _encode_varint32(len(f_idx_v)) + f_ikey + f_idx_v + struct.pack("<II", 0, 1)
            f_idx_f = f_idx_r + b"\x00" + struct.pack("<I", leveldb_masked_crc32c(f_idx_r + b"\x00"))
            f_h_sn = _encode_varint32(len(bad_sn_f) + len(f_idx_f)) + _encode_varint32(len(meta_r)) + _encode_varint32(len(bad_sn_f)) + _encode_varint32(len(f_idx_r))
            sst_folders_bad_sn = bad_sn_f + f_idx_f + meta_f + f_h_sn.ljust(40, b"\x00") + struct.pack("<Q", 0xDB4775248B80FB57)
            (f_dir / "000005.ldb").write_bytes(sst_folders_bad_sn)
            (f_dir / "MANIFEST-000001").write_bytes(build_manifest_bytes(ldb_files=[(5, len(sst_folders_bad_sn), f_ikey, f_ikey)], log_number=6, next_file_number=7, last_sequence=1))
            (f_dir / "CURRENT").write_bytes(b"MANIFEST-000001\n")
            (f_dir / "LOCK").write_bytes(b"")
            entry_cases.append({"id": "d_folders_snappy", "path": str(d_folders_snappy / "world.json")})

            z_gbk = fdir / "gbk_entry.zip"
            _build_raw_zip(z_gbk, [
                {"name_bytes": b"world.json", "payload": wj_b},
                {"name_bytes": b"data/scenes.db", "payload": sc_b},
                {"name_bytes": b"data/actors.db", "payload": ac_b},
                {"name_bytes": "资产/地图.png".encode("gbk"), "payload": png},
            ])
            entry_cases.append({"id": "z_gbk", "path": str(z_gbk)})

            z_bslash = fdir / "bslash.zip"
            sc_bs = (json.dumps(make_v9_scene("s_bs", "BackslashScene", img="worlds/t5/assets/bg.png")) + "\n").encode("utf-8")
            _build_raw_zip(z_bslash, [
                {"name_bytes": b"sub\\world.json", "payload": wj_b},
                {"name_bytes": b"sub\\data\\scenes.db", "payload": sc_bs},
                {"name_bytes": b"sub\\data\\actors.db", "payload": ac_b},
                {"name_bytes": b"sub\\assets\\bg.png", "payload": png},
            ])
            entry_cases.append({"id": "z_bslash", "path": str(z_bslash)})

            d_prev_log = fdir / "dir_prev_log"
            sc_alive = make_v9_scene("s_alive", "AliveAt10")
            sc_obs = make_v9_scene("s_obs", "ObsoleteLog")
            sc_prev = make_v9_scene("s_prev", "PrevLog")
            sc_curr = make_v9_scene("s_curr", "CurrLog")
            build_v14_world(
                d_prev_log,
                world_json=make_v14_world_json(world_id="prevlog", title="PrevLogWorld"),
                scenes=[sc_alive],
                actors=[make_v9_actor("a1", "A1")],
            )
            sst_pl, pl_min, pl_max = build_sstable_bytes([
                (b"!scenes!s_alive", 10, 1, json.dumps(sc_alive).encode("utf-8")),
            ])
            (d_prev_log / "data" / "scenes" / "000005.ldb").write_bytes(sst_pl)
            (d_prev_log / "data" / "scenes" / "000004.log").write_bytes(
                build_wal_bytes([encode_write_batch(20, [("put", b"!scenes!s_obs", json.dumps(sc_obs).encode("utf-8"))])])
            )
            (d_prev_log / "data" / "scenes" / "000005.log").write_bytes(
                build_wal_bytes([encode_write_batch(5, [("put", b"!scenes!s_prev", json.dumps(sc_prev).encode("utf-8"))])])
            )
            (d_prev_log / "data" / "scenes" / "000006.log").write_bytes(
                build_wal_bytes([
                    encode_write_batch(10, [("delete", b"!scenes!s_alive", b"")]),
                    encode_write_batch(11, [("put", b"!scenes!s_curr", json.dumps(sc_curr).encode("utf-8"))]),
                ])
            )
            man_edit = bytearray()
            comp_name = b"leveldb.BytewiseComparator"
            man_edit.extend(_encode_varint32(1) + _encode_varint32(len(comp_name)) + comp_name)
            man_edit.extend(_encode_varint32(2) + _encode_varint32(6))
            man_edit.extend(_encode_varint32(9) + _encode_varint32(5))
            man_edit.extend(_encode_varint32(3) + _encode_varint32(7))
            man_edit.extend(_encode_varint32(4) + _encode_varint32(11))
            man_edit.extend(_encode_varint32(7) + _encode_varint32(0) + _encode_varint32(5) + _encode_varint32(len(sst_pl)))
            man_edit.extend(_encode_varint32(len(pl_min)) + pl_min + _encode_varint32(len(pl_max)) + pl_max)
            (d_prev_log / "data" / "scenes" / "MANIFEST-000001").write_bytes(build_wal_bytes([bytes(man_edit)]))
            entry_cases.append({"id": "d_prev_log", "path": str(d_prev_log / "world.json")})

            resolve_vectors = [
                "%75%73%65%72%3a%2f%2fsecret.png",
                "worlds/t5/%2e%2e/secret.png",
                "assets/%FF%FE.png",
                "assets/a%00b.png",
                "javascript:alert(1)",
                "map%20name.png?v=1#top",
                "50%_off.png",
                "foo..bar.png",
                "%20user://secret.png",
                "assets/..",
                "assets/a%5cb.png",
                "C:\\evil.png",
            ]

            # 12. Challenger 2 Iter 2 image outer-header & chunk-order vectors
            def _mk_png_chunk(ctype: bytes, data: bytes) -> bytes:
                crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
                return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)

            ihdr_4x4 = struct.pack(">IIBBBBB", 4, 4, 8, 6, 0, 0, 0)
            png_fdict_b = (
                b"\x89PNG\r\n\x1a\n"
                + _mk_png_chunk(b"IHDR", ihdr_4x4)
                + _mk_png_chunk(b"IDAT", b"\x78\xbb\x00\x00\x00\x00\x01")
                + _mk_png_chunk(b"IEND", b"")
            )
            ihdr_1x1_idx = struct.pack(">IIBBBBB", 1, 1, 8, 3, 0, 0, 0)
            png_plte_after_idat_b = (
                b"\x89PNG\r\n\x1a\n"
                + _mk_png_chunk(b"IHDR", ihdr_1x1_idx)
                + _mk_png_chunk(b"IDAT", zlib.compress(b"\x00\x00"))
                + _mk_png_chunk(b"PLTE", b"\xff\x00\x00")
                + _mk_png_chunk(b"IEND", b"")
            )
            z_4x4 = zlib.compress(b"\x00" * (4 * 17))
            z_mid = len(z_4x4) // 2
            z_part1 = z_4x4[:z_mid]
            z_part2 = z_4x4[z_mid:]
            png_noncontig_idat_b = (
                b"\x89PNG\r\n\x1a\n"
                + _mk_png_chunk(b"IHDR", ihdr_4x4)
                + _mk_png_chunk(b"IDAT", z_part1)
                + _mk_png_chunk(b"tEXt", b"k\x00v")
                + _mk_png_chunk(b"IDAT", z_part2)
                + _mk_png_chunk(b"IEND", b"")
            )
            png_contig_split_b = (
                b"\x89PNG\r\n\x1a\n"
                + _mk_png_chunk(b"IHDR", ihdr_4x4)
                + _mk_png_chunk(b"IDAT", z_part1)
                + _mk_png_chunk(b"IDAT", z_part2)
                + _mk_png_chunk(b"tEXt", b"k\x00v")
                + _mk_png_chunk(b"IEND", b"")
            )
            png_dup_ihdr_b = (
                b"\x89PNG\r\n\x1a\n"
                + _mk_png_chunk(b"IHDR", ihdr_4x4)
                + _mk_png_chunk(b"IHDR", ihdr_4x4)
                + _mk_png_chunk(b"IDAT", z_4x4)
                + _mk_png_chunk(b"IEND", b"")
            )
            dqt_seg = b"\xff\xdb" + struct.pack(">H", 67) + b"\x00" + (b"\x10" * 64)
            sos_seg = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00\x00"
            jpg_12bit_b = (
                b"\xff\xd8"
                + dqt_seg
                + b"\xff\xc0" + struct.pack(">HBHHB", 11, 12, 4, 4, 1) + b"\x01\x11\x00"
                + sos_seg
                + b"\xff\xd9"
            )
            jpg_sof3_b = (
                b"\xff\xd8"
                + dqt_seg
                + b"\xff\xc3" + struct.pack(">HBHHB", 11, 8, 4, 4, 1) + b"\x01\x11\x00"
                + sos_seg
                + b"\xff\xd9"
            )
            sof0_1comp_seg = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, 4, 4, 1) + b"\x01\x11\x00"
            sof2_1comp_seg = b"\xff\xc2" + struct.pack(">HBHHB", 11, 8, 8, 8, 1) + b"\x01\x11\x00"
            dht_dc_seg = b"\xff\xc4" + struct.pack(">H", 31) + b"\x00" + bytes([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]) + bytes(range(12))
            dht_ac_seg = b"\xff\xc4" + struct.pack(">H", 181) + b"\x10" + bytes([0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D]) + bytes(162)
            jpg_dup_soi_b = b"\xff\xd8\xff\xd8" + dqt_seg + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_dup_sof0_b = b"\xff\xd8" + dqt_seg + sof0_1comp_seg + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_hv_zero_b = (
                b"\xff\xd8"
                + dqt_seg
                + b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, 4, 4, 1) + b"\x01\x00\x00"
                + sos_seg
                + b"\xff\xd9"
            )
            sos_3comp_seg = b"\xff\xda" + struct.pack(">H", 12) + b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00\x00"
            jpg_sos_more_comp_than_sof_b = b"\xff\xd8" + dqt_seg + sof0_1comp_seg + sos_3comp_seg + b"\xff\xd9"
            sos_prog_dc = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x00\x00\x00"
            sos_prog_ac = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x01\x3f\x00\x00"
            jpg_sof2_bad_2nd_sos_ncomp_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + sos_3comp_seg + b"\xff\xd9"
            sos_bad_len_10 = b"\xff\xda" + struct.pack(">H", 10) + b"\x01\x01\x00\x01\x3f\x00\x00\x00\x00"
            jpg_sof2_bad_2nd_sos_len_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + sos_bad_len_10 + b"\xff\xd9"
            jpg_sof2_dup_sof_between_scans_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + sof0_1comp_seg + sos_prog_ac + b"\xff\xd9"
            jpg_sof2_dup_soi_between_scans_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + b"\xff\xd8" + sos_prog_ac + b"\xff\xd9"
            jpg_tq_out_of_range_b = (
                b"\xff\xd8"
                + dqt_seg
                + b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, 4, 4, 1) + b"\x01\x11\x04"
                + sos_seg
                + b"\xff\xd9"
            )
            sof0_mcu11_seg = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x01\x33\x00\x02\x11\x00\x03\x11\x00"
            jpg_mcu_sum_11_interleaved_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_mcu11_seg + sos_3comp_seg + b"\xff\xd9"
            jpg_sos_unknown_cs_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_1comp_seg + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x63\x00\x00\x3f\x00\x00\xff\xd9"
            sof0_3comp_seg = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00"
            jpg_sos_dup_cs_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_3comp_seg + b"\xff\xda" + struct.pack(">H", 10) + b"\x02\x01\x00\x01\x00\x00\x3f\x00" + (b"\x00" * 8) + b"\xff\xd9"
            jpg_valid_sof2_progressive_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + sos_prog_ac + b"\xff\xd9"
            sof0_48_seg = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x01\x44\x00\x02\x44\x00\x03\x44\x00"
            jpg_valid_mcu_48_noninterleaved_b = (
                b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_48_seg
                + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00" + (b"\x00" * 32)
                + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x02\x00\x00\x3f\x00" + (b"\x00" * 32)
                + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x03\x00\x00\x3f\x00" + (b"\x00" * 32)
                + b"\xff\xd9"
            )
            # Phase 2 Iter 7 outer JPEG header/marker vectors & positive controls
            jpg_dht_bad_tc_b = b"\xff\xd8" + dqt_seg + b"\xff\xc4" + struct.pack(">H", 31) + b"\x20" + bytes([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]) + bytes(range(12)) + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_dht_bad_th_b = b"\xff\xd8" + dqt_seg + b"\xff\xc4" + struct.pack(">H", 31) + b"\x04" + bytes([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]) + bytes(range(12)) + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_dht_bad_len_b = b"\xff\xd8" + dqt_seg + b"\xff\xc4\x00\x05\x00\x00\x00" + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_dht_sum_gt_256_b = b"\xff\xd8" + dqt_seg + b"\xff\xc4" + struct.pack(">H", 276) + b"\x00" + bytes([255, 2] + [0] * 14) + bytes(257) + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_dht_mid_bad_len_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + b"\xff\xc4\x00\x05\x00\x00\x00" + sos_prog_ac + b"\xff\xd9"
            jpg_dqt_mid_bad_len_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + b"\xff\xdb\x00\x05\x00\x00\x00" + sos_prog_ac + b"\xff\xd9"
            jpg_dri_bad_len_2_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + b"\xff\xdd\x00\x02" + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_dri_bad_len_6_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + b"\xff\xdd\x00\x06\x00\x01\x00\x00" + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_dri_mid_bad_len_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + b"\xff\xdd\x00\x06\x00\x01\x00\x00" + sos_prog_ac + b"\xff\xd9"
            jpg_sos_bad_td_ta_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_1comp_seg + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x44\x00\x3f\x00\x00\xff\xd9"
            sof2_3comp_seg = b"\xff\xc2" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00"
            jpg_sof2_ss_gt_se_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x10\x05\x00\x00\xff\xd9"
            jpg_sof2_se_64_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x01\x40\x00\x00\xff\xd9"
            jpg_sof2_ss0_se63_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00\x00\xff\xd9"
            jpg_sof2_ac_multi_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_3comp_seg + b"\xff\xda" + struct.pack(">H", 10) + b"\x02\x01\x00\x02\x11\x01\x3f\x00\x00\xff\xd9"
            jpg_sof2_ah14_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x00\xe0\x00\xff\xd9"
            jpg_sof2_refinement_al_diff_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x00\x20\x00\xff\xd9"
            jpg_sof2_ac_ah1_al2_bad_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x01\x3f\x12\x00\xff\xd9"
            jpg_marker_c8_before_b = b"\xff\xd8" + dqt_seg + b"\xff\xc8\x00\x04\x00\x00" + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_marker_c8_mid_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + b"\xff\xc8\x00\x04\x00\x00" + sos_prog_ac + b"\xff\xd9"
            jpg_marker_de_dhp_b = b"\xff\xd8" + dqt_seg + b"\xff\xde\x00\x04\x00\x00" + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_marker_df_exp_b = b"\xff\xd8" + dqt_seg + b"\xff\xdf\x00\x04\x00\x00" + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_marker_cc_dac_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + b"\xff\xcc\x00\x04\x00\x05" + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_marker_02_before_b = b"\xff\xd8" + dqt_seg + b"\xff\x02" + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_marker_02_in_entropy_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_1comp_seg + sos_seg + b"\xff\x02\x00\x00\xff\xd9"
            jpg_marker_f0_before_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + b"\xff\xf0\x00\x04\x00\x00" + sof0_1comp_seg + sos_seg + b"\xff\xd9"

            jpg_valid_ff_pad_b = b"\xff\xd8\xff\xff" + dqt_seg + b"\xff\xff" + dht_dc_seg + b"\xff\xff" + dht_ac_seg + b"\xff\xff" + sof0_1comp_seg + b"\xff\xff" + sos_seg + b"\xff\xff\xd9"
            dht_dc_body = b"\x00" + bytes([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]) + bytes(range(12))
            dht_ac_body = b"\x10" + bytes([0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D]) + bytes(162)
            dht_multi_seg = b"\xff\xc4" + struct.pack(">H", 2 + len(dht_dc_body) + len(dht_ac_body)) + dht_dc_body + dht_ac_body
            jpg_valid_dht_multi_b = b"\xff\xd8" + dqt_seg + dht_multi_seg + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            jpg_valid_dri_4_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + b"\xff\xdd\x00\x04\x00\x01" + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            dht_dc_th2_seg = b"\xff\xc4" + struct.pack(">H", 31) + b"\x02" + bytes([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]) + bytes(range(12))
            dht_ac_th2_seg = b"\xff\xc4" + struct.pack(">H", 181) + b"\x12" + bytes([0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D]) + bytes(162)
            jpg_valid_sof0_th2_td2_b = b"\xff\xd8" + dqt_seg + dht_dc_th2_seg + dht_ac_th2_seg + sof0_1comp_seg + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x22\x00\x3f\x00\x00\xff\xd9"
            jpg_valid_sof2_refinement_b = (
                b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg
                + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x00\x01\x00"
                + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x00\x10\x00"
                + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x01\x3f\x01\x00"
                + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x01\x3f\x10\x00"
                + b"\xff\xd9"
            )
            jpg_valid_dnl_marker_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_1comp_seg + sos_seg + b"\xff\xdc\x00\x04\x00\x04\xff\xd9"
            # Phase 2 Iter 8 outer JPEG table/colorspace/Kraft/SOF2 Td-Ta vectors & positive controls
            sof0_4comp_seg = b"\xff\xc0" + struct.pack(">HBHHB", 20, 8, 4, 4, 4) + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00\x04\x11\x00"
            sos_4comp_seg = b"\xff\xda" + struct.pack(">H", 14) + b"\x04\x01\x00\x02\x00\x03\x00\x04\x00\x00\x3f\x00\x00"
            jpg_4comp_cmyk_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_4comp_seg + sos_4comp_seg + b"\xff\xd9"
            sof0_1comp_tq1_seg = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, 4, 4, 1) + b"\x01\x11\x01"
            jpg_sof0_tq1_undef_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_1comp_tq1_seg + sos_seg + b"\xff\xd9"
            dht_kraft_65536_seg = b"\xff\xc4" + struct.pack(">H", 182) + b"\x10" + bytes([0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7E]) + bytes(163)
            jpg_dht_kraft_65536_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_kraft_65536_seg + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            dht_oversub_seg = b"\xff\xc4" + struct.pack(">H", 22) + b"\x00" + bytes([3] + [0] * 15) + bytes(3)
            jpg_dht_kraft_oversub_b = b"\xff\xd8" + dqt_seg + dht_oversub_seg + dht_ac_seg + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            sos_prog_dc_td1 = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x10\x00\x00\x00\x00"
            jpg_sof2_undef_dc_td_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc_td1 + sos_prog_ac + b"\xff\xd9"
            sos_prog_ac_ta1 = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x01\x01\x3f\x00\x00"
            jpg_sof2_undef_ac_ta_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + sos_prog_ac_ta1 + b"\xff\xd9"
            sos_prog_ac_first = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x01\x3f\x01\x00"
            sos_prog_ac_refine_ta1 = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x01\x01\x3f\x10\x00"
            jpg_sof2_refine_undef_ta_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + sos_prog_ac_first + sos_prog_ac_refine_ta1 + b"\xff\xd9"

            dqt_tq1_seg = b"\xff\xdb" + struct.pack(">H", 67) + b"\x01" + (b"\x10" * 64)
            jpg_valid_tq1_after_sof_b = b"\xff\xd8" + dht_dc_seg + dht_ac_seg + sof0_1comp_tq1_seg + dqt_tq1_seg + sos_seg + b"\xff\xd9"
            jpg_valid_dht_kraft_65535_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            sos_prog_dc_td0_ta1 = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x01\x00\x00\x00\x00"
            jpg_valid_sof2_dc_undef_ta_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc_td0_ta1 + sos_prog_ac + b"\xff\xd9"
            sos_prog_ac_td1_ta0 = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x10\x01\x3f\x00\x00"
            jpg_valid_sof2_ac_undef_td_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + sos_prog_ac_td1_ta0 + b"\xff\xd9"
            sos_prog_dc_first_al1 = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x00\x01\x00"
            sos_prog_dc_refine_td1 = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x10\x00\x00\x10\x00"
            jpg_valid_sof2_dc_refine_undef_td_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc_first_al1 + sos_prog_dc_refine_td1 + sos_prog_ac + b"\xff\xd9"
            # Phase 2 Iter 9 outer JPEG DC sym<=15, APP14 Adobe transform, and sequential duplicate SOS vectors
            dht_dc_sym16_seg = b"\xff\xc4" + struct.pack(">H", 31) + b"\x00" + bytes([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]) + bytes(range(11)) + bytes([16])
            jpg_dc_sym_16_b = b"\xff\xd8" + dqt_seg + dht_dc_sym16_seg + dht_ac_seg + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            dht_dc_th1_sym16_seg = b"\xff\xc4" + struct.pack(">H", 31) + b"\x01" + bytes([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]) + bytes(range(11)) + bytes([16])
            jpg_sof2_interscan_dc_sym16_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_1comp_seg + sos_prog_dc + dht_dc_th1_sym16_seg + sos_prog_ac + b"\xff\xd9"
            app14_t2_seg = b"\xff\xee" + struct.pack(">H", 14) + b"Adobe\x00\x64\x00\x00\x00\x00\x02"
            jpg_app14_3comp_t2_b = b"\xff\xd8" + app14_t2_seg + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_3comp_seg + sos_3comp_seg + b"\xff\xd9"
            jpg_app14_after_sof_t2_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_3comp_seg + app14_t2_seg + sos_3comp_seg + b"\xff\xd9"
            jpg_sof0_1comp_two_sos_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_1comp_seg + sos_seg + sos_seg + b"\xff\xd9"
            sof1_1comp_seg = b"\xff\xc1" + struct.pack(">HBHHB", 11, 8, 4, 4, 1) + b"\x01\x11\x00"
            jpg_sof1_1comp_two_sos_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof1_1comp_seg + sos_seg + sos_seg + b"\xff\xd9"

            dht_dc_sym15_seg = b"\xff\xc4" + struct.pack(">H", 31) + b"\x00" + bytes([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]) + bytes(range(11)) + bytes([15])
            jpg_valid_dc_sym_15_b = b"\xff\xd8" + dqt_seg + dht_dc_sym15_seg + dht_ac_seg + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            dht_ac_symff_seg = b"\xff\xc4" + struct.pack(">H", 181) + b"\x10" + bytes([0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D]) + (b"\x00" * 161) + b"\xff"
            jpg_valid_ac_sym_ff_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_symff_seg + sof0_1comp_seg + sos_seg + b"\xff\xd9"
            app14_t0_seg = b"\xff\xee" + struct.pack(">H", 14) + b"Adobe\x00\x64\x00\x00\x00\x00\x00"
            jpg_valid_app14_3comp_t0_b = b"\xff\xd8" + app14_t0_seg + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_3comp_seg + sos_3comp_seg + b"\x00\x00\xff\xd9"
            app14_t1_seg = b"\xff\xee" + struct.pack(">H", 14) + b"Adobe\x00\x64\x00\x00\x00\x00\x01"
            jpg_valid_app14_3comp_t1_b = b"\xff\xd8" + app14_t1_seg + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_3comp_seg + sos_3comp_seg + b"\x00\x00\xff\xd9"
            sos_2comp_12_seg = b"\xff\xda" + struct.pack(">H", 10) + b"\x02\x01\x00\x02\x00\x00\x3f\x00\x00"
            sos_1comp_3_seg = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x03\x00\x00\x3f\x00\x00"
            jpg_valid_sof0_3_2_plus_1_scans_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_3comp_seg + sos_2comp_12_seg + sos_1comp_3_seg + b"\xff\xd9"
            dht_ac_th1_seg = b"\xff\xc4" + struct.pack(">H", 181) + b"\x11" + bytes([0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7D]) + bytes(162)
            jpg_valid_sof2_interscan_dht_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + sof2_1comp_seg + sos_prog_dc + dht_ac_th1_seg + sos_prog_ac_ta1 + b"\xff\xd9"
            # Phase 2 Iter 10 outer JPEG sequential undef Td/Ta >= 2 and SOS component ordering vectors
            jpg_sof0_undef_td2_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_1comp_seg + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x20\x00\x3f\x00\x00\xff\xd9"
            jpg_sof0_undef_ta2_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_1comp_seg + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x02\x00\x3f\x00\x00\xff\xd9"
            jpg_sof1_undef_td3_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof1_1comp_seg + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x30\x00\x3f\x00\x00\xff\xd9"
            sos_3comp_321_seg = b"\xff\xda" + struct.pack(">H", 12) + b"\x03\x03\x00\x02\x00\x01\x00\x00\x3f\x00\x00"
            sos_3comp_132_seg = b"\xff\xda" + struct.pack(">H", 12) + b"\x03\x01\x00\x03\x00\x02\x00\x00\x3f\x00\x00"
            sos_3comp_123_seg = b"\xff\xda" + struct.pack(">H", 12) + b"\x03\x01\x00\x02\x00\x03\x00\x00\x3f\x00\x00"
            sof0_3comp_rev_seg = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x03\x11\x00\x02\x11\x00\x01\x11\x00"
            sos_prog_3comp_321_dc = b"\xff\xda" + struct.pack(">H", 12) + b"\x03\x03\x00\x02\x00\x01\x00\x00\x00\x00\x00"
            jpg_sof0_3_sos_3_2_1_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_3comp_seg + sos_3comp_321_seg + b"\xff\xd9"
            jpg_sof0_3_sos_1_3_2_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_3comp_seg + sos_3comp_132_seg + b"\xff\xd9"
            jpg_sof2_3_sos_3_2_1_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_3comp_seg + sos_prog_3comp_321_dc + b"\xff\xd9"
            jpg_sof0_3_rev_sof_sos_1_2_3_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_3comp_rev_seg + sos_3comp_123_seg + b"\xff\xd9"

            jpg_valid_sof0_def_dc2_td2_ta0_b = b"\xff\xd8" + dqt_seg + dht_dc_th2_seg + dht_ac_seg + sof0_1comp_seg + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x20\x00\x3f\x00\x00\xff\xd9"
            jpg_valid_sof0_interscan_dht2_b = (
                b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_3comp_seg
                + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00\x00"
                + dht_dc_th2_seg + dht_ac_th2_seg
                + b"\xff\xda" + struct.pack(">H", 10) + b"\x02\x02\x22\x03\x22\x00\x3f\x00\x00"
                + b"\xff\xd9"
            )
            jpg_valid_sof0_3_sos_1_3_then_2_b = (
                b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_3comp_seg
                + b"\xff\xda" + struct.pack(">H", 10) + b"\x02\x01\x00\x03\x00\x00\x3f\x00\x00"
                + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x02\x00\x00\x3f\x00\x00"
                + b"\xff\xd9"
            )
            jpg_valid_sof0_3_rev_sof_sos_3_2_1_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_3comp_rev_seg + sos_3comp_321_seg + b"\xff\xd9"
            jpg_valid_sof0_3_2nd_scan_3_then_1_b = (
                b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_3comp_seg
                + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x03\x00\x00\x3f\x00\x00"
                + b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00\x00"
                + b"\xff\xd9"
            )
            # Phase 2 Iter 11 outer JPEG SOF fractional sampling factor vectors & positive controls
            sof0_h321_seg = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x01\x31\x00\x02\x21\x00\x03\x11\x00"
            sof0_v431_seg = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x01\x14\x00\x02\x13\x00\x03\x11\x00"
            sof2_h321_seg = b"\xff\xc2" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x01\x31\x00\x02\x21\x00\x03\x11\x00"
            sos_1c_1 = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00\x00"
            sos_1c_2 = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x02\x00\x00\x3f\x00\x00"
            sos_1c_3 = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x03\x00\x00\x3f\x00\x00"
            sos_prog_1c_1_dc = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x00\x00\x00"
            sos_prog_1c_2_dc = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x02\x00\x00\x00\x00\x00"
            sos_prog_1c_3_dc = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x03\x00\x00\x00\x00\x00"
            jpg_sof0_h_3_2_1_inter_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_h321_seg + sos_3comp_seg + b"\x00\x00\xff\xd9"
            jpg_sof0_h_3_2_1_noninter_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_h321_seg + sos_1c_1 + sos_1c_2 + sos_1c_3 + b"\xff\xd9"
            jpg_sof0_v_4_3_1_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_v431_seg + sos_3comp_seg + b"\x00\x00\xff\xd9"
            jpg_sof2_h_3_2_1_noninter_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_h321_seg + sos_prog_1c_1_dc + sos_prog_1c_2_dc + sos_prog_1c_3_dc + b"\xff\xd9"

            sof0_h421_seg = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x01\x41\x00\x02\x21\x00\x03\x11\x00"
            sof0_h311_seg = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x01\x31\x00\x02\x11\x00\x03\x11\x00"
            sof0_hv311211_seg = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x01\x31\x00\x02\x12\x00\x03\x11\x00"
            jpg_valid_sof0_h_4_2_1_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_h421_seg + sos_3comp_seg + b"\x00\x00\xff\xd9"
            jpg_valid_sof0_h_3_1_1_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_h311_seg + sos_3comp_seg + b"\x00\x00\xff\xd9"
            jpg_valid_sof0_hv_31_12_11_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_hv311211_seg + sos_3comp_seg + b"\x00\x00\xff\xd9"
            # Phase 2 Iter 12 outer JPEG SOF duplicate-cid vectors & positive control
            sof0_dup_cid_44_11_seg = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x01\x44\x00\x01\x11\x00\x02\x11\x00"
            sof2_dup_cid_44_11_seg = b"\xff\xc2" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x01\x44\x00\x01\x11\x00\x02\x11\x00"
            sof0_dup_cid_11_44_seg = b"\xff\xc0" + struct.pack(">HBHHB", 17, 8, 8, 8, 3) + b"\x01\x11\x00\x01\x44\x00\x02\x11\x00"
            sos_prog_2comp_12_dc = b"\xff\xda" + struct.pack(">H", 10) + b"\x02\x01\x00\x02\x00\x00\x00\x00\x00"
            jpg_sof0_dup_cid_44_11_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_dup_cid_44_11_seg + sos_2comp_12_seg + b"\xff\xd9"
            jpg_sof2_dup_cid_44_11_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof2_dup_cid_44_11_seg + sos_prog_2comp_12_dc + b"\xff\xd9"
            jpg_valid_sof0_dup_cid_11_44_b = b"\xff\xd8" + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_dup_cid_11_44_seg + sos_2comp_12_seg + b"\x00\x00\xff\xd9"
            vp8x_4x4 = b"VP8X" + struct.pack("<I", 10) + b"\x00\x00\x00\x00" + struct.pack("<I", 3)[:3] + struct.pack("<I", 3)[:3]
            vp8_8x8 = b"VP8 " + struct.pack("<I", 12) + b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", 8, 8) + b"\x00\x00"
            webp_body_mm = b"WEBP" + vp8x_4x4 + vp8_8x8
            webp_vp8x_mismatch_b = b"RIFF" + struct.pack("<I", len(webp_body_mm)) + webp_body_mm

            vp8_16383 = b"VP8 " + struct.pack("<I", 12) + b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", 16383, 16383) + b"\x00\x00"
            webp_body_os = b"WEBP" + vp8x_4x4 + vp8_16383
            webp_vp8x_oversized_b = b"RIFF" + struct.pack("<I", len(webp_body_os)) + webp_body_os

            img_bad_vectors = {
                "png_fdict": {"ext": "png", "b64": base64.b64encode(png_fdict_b).decode("ascii")},
                "png_plte_after_idat": {"ext": "png", "b64": base64.b64encode(png_plte_after_idat_b).decode("ascii")},
                "png_noncontig_idat": {"ext": "png", "b64": base64.b64encode(png_noncontig_idat_b).decode("ascii")},
                "png_contig_split": {"ext": "png", "b64": base64.b64encode(png_contig_split_b).decode("ascii")},
                "png_dup_ihdr": {"ext": "png", "b64": base64.b64encode(png_dup_ihdr_b).decode("ascii")},
                "jpg_12bit": {"ext": "jpg", "b64": base64.b64encode(jpg_12bit_b).decode("ascii")},
                "jpg_sof3": {"ext": "jpg", "b64": base64.b64encode(jpg_sof3_b).decode("ascii")},
                "jpg_dup_soi": {"ext": "jpg", "b64": base64.b64encode(jpg_dup_soi_b).decode("ascii")},
                "jpg_dup_sof0": {"ext": "jpg", "b64": base64.b64encode(jpg_dup_sof0_b).decode("ascii")},
                "jpg_hv_zero": {"ext": "jpg", "b64": base64.b64encode(jpg_hv_zero_b).decode("ascii")},
                "jpg_sos_more_comp_than_sof": {"ext": "jpg", "b64": base64.b64encode(jpg_sos_more_comp_than_sof_b).decode("ascii")},
                "jpg_sof2_bad_2nd_sos_ncomp": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_bad_2nd_sos_ncomp_b).decode("ascii")},
                "jpg_sof2_bad_2nd_sos_len": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_bad_2nd_sos_len_b).decode("ascii")},
                "jpg_sof2_dup_sof_between_scans": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_dup_sof_between_scans_b).decode("ascii")},
                "jpg_sof2_dup_soi_between_scans": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_dup_soi_between_scans_b).decode("ascii")},
                "jpg_tq_out_of_range": {"ext": "jpg", "b64": base64.b64encode(jpg_tq_out_of_range_b).decode("ascii")},
                "jpg_mcu_sum_11_interleaved": {"ext": "jpg", "b64": base64.b64encode(jpg_mcu_sum_11_interleaved_b).decode("ascii")},
                "jpg_sos_unknown_cs": {"ext": "jpg", "b64": base64.b64encode(jpg_sos_unknown_cs_b).decode("ascii")},
                "jpg_sos_dup_cs": {"ext": "jpg", "b64": base64.b64encode(jpg_sos_dup_cs_b).decode("ascii")},
                "jpg_valid_sof2_progressive": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof2_progressive_b).decode("ascii")},
                "jpg_valid_mcu_48_noninterleaved": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_mcu_48_noninterleaved_b).decode("ascii")},
                "jpg_dht_bad_tc": {"ext": "jpg", "b64": base64.b64encode(jpg_dht_bad_tc_b).decode("ascii")},
                "jpg_dht_bad_th": {"ext": "jpg", "b64": base64.b64encode(jpg_dht_bad_th_b).decode("ascii")},
                "jpg_dht_bad_len": {"ext": "jpg", "b64": base64.b64encode(jpg_dht_bad_len_b).decode("ascii")},
                "jpg_dht_sum_gt_256": {"ext": "jpg", "b64": base64.b64encode(jpg_dht_sum_gt_256_b).decode("ascii")},
                "jpg_dht_mid_bad_len": {"ext": "jpg", "b64": base64.b64encode(jpg_dht_mid_bad_len_b).decode("ascii")},
                "jpg_dqt_mid_bad_len": {"ext": "jpg", "b64": base64.b64encode(jpg_dqt_mid_bad_len_b).decode("ascii")},
                "jpg_dri_bad_len_2": {"ext": "jpg", "b64": base64.b64encode(jpg_dri_bad_len_2_b).decode("ascii")},
                "jpg_dri_bad_len_6": {"ext": "jpg", "b64": base64.b64encode(jpg_dri_bad_len_6_b).decode("ascii")},
                "jpg_dri_mid_bad_len": {"ext": "jpg", "b64": base64.b64encode(jpg_dri_mid_bad_len_b).decode("ascii")},
                "jpg_sos_bad_td_ta": {"ext": "jpg", "b64": base64.b64encode(jpg_sos_bad_td_ta_b).decode("ascii")},
                "jpg_sof2_ss_gt_se": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_ss_gt_se_b).decode("ascii")},
                "jpg_sof2_se_64": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_se_64_b).decode("ascii")},
                "jpg_sof2_ss0_se63": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_ss0_se63_b).decode("ascii")},
                "jpg_sof2_ac_multi": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_ac_multi_b).decode("ascii")},
                "jpg_sof2_ah14": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_ah14_b).decode("ascii")},
                "jpg_sof2_refinement_al_diff": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_refinement_al_diff_b).decode("ascii")},
                "jpg_sof2_ac_ah1_al2_bad": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_ac_ah1_al2_bad_b).decode("ascii")},
                "jpg_marker_c8_before": {"ext": "jpg", "b64": base64.b64encode(jpg_marker_c8_before_b).decode("ascii")},
                "jpg_marker_c8_mid": {"ext": "jpg", "b64": base64.b64encode(jpg_marker_c8_mid_b).decode("ascii")},
                "jpg_marker_de_dhp": {"ext": "jpg", "b64": base64.b64encode(jpg_marker_de_dhp_b).decode("ascii")},
                "jpg_marker_df_exp": {"ext": "jpg", "b64": base64.b64encode(jpg_marker_df_exp_b).decode("ascii")},
                "jpg_marker_cc_dac": {"ext": "jpg", "b64": base64.b64encode(jpg_marker_cc_dac_b).decode("ascii")},
                "jpg_marker_02_before": {"ext": "jpg", "b64": base64.b64encode(jpg_marker_02_before_b).decode("ascii")},
                "jpg_marker_02_in_entropy": {"ext": "jpg", "b64": base64.b64encode(jpg_marker_02_in_entropy_b).decode("ascii")},
                "jpg_marker_f0_before": {"ext": "jpg", "b64": base64.b64encode(jpg_marker_f0_before_b).decode("ascii")},
                "jpg_valid_ff_pad": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_ff_pad_b).decode("ascii")},
                "jpg_valid_dht_multi": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_dht_multi_b).decode("ascii")},
                "jpg_valid_dri_4": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_dri_4_b).decode("ascii")},
                "jpg_valid_sof0_th2_td2": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof0_th2_td2_b).decode("ascii")},
                "jpg_valid_sof2_refinement": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof2_refinement_b).decode("ascii")},
                "jpg_valid_dnl_marker": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_dnl_marker_b).decode("ascii")},
                "jpg_4comp_cmyk": {"ext": "jpg", "b64": base64.b64encode(jpg_4comp_cmyk_b).decode("ascii")},
                "jpg_sof0_tq1_undef": {"ext": "jpg", "b64": base64.b64encode(jpg_sof0_tq1_undef_b).decode("ascii")},
                "jpg_dht_kraft_65536": {"ext": "jpg", "b64": base64.b64encode(jpg_dht_kraft_65536_b).decode("ascii")},
                "jpg_dht_kraft_oversub": {"ext": "jpg", "b64": base64.b64encode(jpg_dht_kraft_oversub_b).decode("ascii")},
                "jpg_sof2_undef_dc_td": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_undef_dc_td_b).decode("ascii")},
                "jpg_sof2_undef_ac_ta": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_undef_ac_ta_b).decode("ascii")},
                "jpg_sof2_refine_undef_ta": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_refine_undef_ta_b).decode("ascii")},
                "jpg_valid_tq1_after_sof": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_tq1_after_sof_b).decode("ascii")},
                "jpg_valid_dht_kraft_65535": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_dht_kraft_65535_b).decode("ascii")},
                "jpg_valid_sof2_dc_undef_ta": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof2_dc_undef_ta_b).decode("ascii")},
                "jpg_valid_sof2_ac_undef_td": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof2_ac_undef_td_b).decode("ascii")},
                "jpg_valid_sof2_dc_refine_undef_td": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof2_dc_refine_undef_td_b).decode("ascii")},
                "jpg_dc_sym_16": {"ext": "jpg", "b64": base64.b64encode(jpg_dc_sym_16_b).decode("ascii")},
                "jpg_sof2_interscan_dc_sym16": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_interscan_dc_sym16_b).decode("ascii")},
                "jpg_app14_3comp_t2": {"ext": "jpg", "b64": base64.b64encode(jpg_app14_3comp_t2_b).decode("ascii")},
                "jpg_app14_after_sof_t2": {"ext": "jpg", "b64": base64.b64encode(jpg_app14_after_sof_t2_b).decode("ascii")},
                "jpg_sof0_1comp_two_sos": {"ext": "jpg", "b64": base64.b64encode(jpg_sof0_1comp_two_sos_b).decode("ascii")},
                "jpg_sof1_1comp_two_sos": {"ext": "jpg", "b64": base64.b64encode(jpg_sof1_1comp_two_sos_b).decode("ascii")},
                "jpg_valid_dc_sym_15": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_dc_sym_15_b).decode("ascii")},
                "jpg_valid_ac_sym_ff": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_ac_sym_ff_b).decode("ascii")},
                "jpg_valid_app14_3comp_t0": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_app14_3comp_t0_b).decode("ascii")},
                "jpg_valid_app14_3comp_t1": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_app14_3comp_t1_b).decode("ascii")},
                "jpg_valid_sof0_3_2_plus_1_scans": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof0_3_2_plus_1_scans_b).decode("ascii")},
                "jpg_valid_sof2_interscan_dht": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof2_interscan_dht_b).decode("ascii")},
                "jpg_sof0_undef_td2": {"ext": "jpg", "b64": base64.b64encode(jpg_sof0_undef_td2_b).decode("ascii")},
                "jpg_sof0_undef_ta2": {"ext": "jpg", "b64": base64.b64encode(jpg_sof0_undef_ta2_b).decode("ascii")},
                "jpg_sof1_undef_td3": {"ext": "jpg", "b64": base64.b64encode(jpg_sof1_undef_td3_b).decode("ascii")},
                "jpg_sof0_3_sos_3_2_1": {"ext": "jpg", "b64": base64.b64encode(jpg_sof0_3_sos_3_2_1_b).decode("ascii")},
                "jpg_sof0_3_sos_1_3_2": {"ext": "jpg", "b64": base64.b64encode(jpg_sof0_3_sos_1_3_2_b).decode("ascii")},
                "jpg_sof2_3_sos_3_2_1": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_3_sos_3_2_1_b).decode("ascii")},
                "jpg_sof0_3_rev_sof_sos_1_2_3": {"ext": "jpg", "b64": base64.b64encode(jpg_sof0_3_rev_sof_sos_1_2_3_b).decode("ascii")},
                "jpg_valid_sof0_def_dc2_td2_ta0": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof0_def_dc2_td2_ta0_b).decode("ascii")},
                "jpg_valid_sof0_interscan_dht2": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof0_interscan_dht2_b).decode("ascii")},
                "jpg_valid_sof0_3_sos_1_3_then_2": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof0_3_sos_1_3_then_2_b).decode("ascii")},
                "jpg_valid_sof0_3_rev_sof_sos_3_2_1": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof0_3_rev_sof_sos_3_2_1_b).decode("ascii")},
                "jpg_valid_sof0_3_2nd_scan_3_then_1": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof0_3_2nd_scan_3_then_1_b).decode("ascii")},
                "jpg_sof0_h_3_2_1_inter": {"ext": "jpg", "b64": base64.b64encode(jpg_sof0_h_3_2_1_inter_b).decode("ascii")},
                "jpg_sof0_h_3_2_1_noninter": {"ext": "jpg", "b64": base64.b64encode(jpg_sof0_h_3_2_1_noninter_b).decode("ascii")},
                "jpg_sof0_v_4_3_1": {"ext": "jpg", "b64": base64.b64encode(jpg_sof0_v_4_3_1_b).decode("ascii")},
                "jpg_sof2_h_3_2_1_noninter": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_h_3_2_1_noninter_b).decode("ascii")},
                "jpg_valid_sof0_h_4_2_1": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof0_h_4_2_1_b).decode("ascii")},
                "jpg_valid_sof0_h_3_1_1": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof0_h_3_1_1_b).decode("ascii")},
                "jpg_valid_sof0_hv_31_12_11": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof0_hv_31_12_11_b).decode("ascii")},
                "jpg_sof0_dup_cid_44_11": {"ext": "jpg", "b64": base64.b64encode(jpg_sof0_dup_cid_44_11_b).decode("ascii")},
                "jpg_sof2_dup_cid_44_11": {"ext": "jpg", "b64": base64.b64encode(jpg_sof2_dup_cid_44_11_b).decode("ascii")},
                "jpg_valid_sof0_dup_cid_11_44": {"ext": "jpg", "b64": base64.b64encode(jpg_valid_sof0_dup_cid_11_44_b).decode("ascii")},
                "webp_vp8x_mismatch": {"ext": "webp", "b64": base64.b64encode(webp_vp8x_mismatch_b).decode("ascii")},
                "webp_vp8x_oversized": {"ext": "webp", "b64": base64.b64encode(webp_vp8x_oversized_b).decode("ascii")},
            }

            # 13. Phase 2 Iter 13: PNG IDAT/Adam7/PLTE, WebP container/bitstream, BMP bfSize/bitfields/16-bit/topdown, JPEG APP0, SVG <use>/units/viewBox/subpixel, MIME mismatch
            def _mk_custom_png(w: int, h: int, bd: int, ct: int, raw_scanlines: bytes, extra_chunks: list[tuple[bytes, bytes]] = (), interlace: int = 0, idat_override: bytes | None = None) -> bytes:
                ihdr = struct.pack(">IIBBBBB", w, h, bd, ct, 0, 0, interlace)
                parts = [b"\x89PNG\r\n\x1a\n", _mk_png_chunk(b"IHDR", ihdr)]
                for ctype, cdata in extra_chunks:
                    parts.append(_mk_png_chunk(ctype, cdata))
                parts.append(_mk_png_chunk(b"IDAT", zlib.compress(raw_scanlines) if idat_override is None else idat_override))
                parts.append(_mk_png_chunk(b"IEND", b""))
                return b"".join(parts)

            def _mk_bmp_adv(w: int, h_signed: int, bpp: int, comp: int, dib: int = 40, colors_used: int = 0, pal_entries: list[bytes] = (), masks: tuple[int, int, int] = (0, 0, 0), bf_size_override: int | None = None) -> bytes:
                h_abs = abs(h_signed)
                row_stride = ((w * bpp + 31) // 32) * 4
                pix_sz = row_stride * h_abs
                extra = b""
                if dib == 40 and comp == 3:
                    extra = struct.pack("<III", *masks)
                elif dib > 40:
                    extra = struct.pack("<III", *masks) if comp == 3 else b""
                    extra = extra.ljust(dib - 40, b"\x00")
                pal = b"".join(pal_entries)
                bf_off = 14 + 40 + len(extra) + len(pal)
                fsize = (bf_off + pix_sz) if bf_size_override is None else bf_size_override
                fh = struct.pack("<2sIHHI", b"BM", fsize, 0, 0, bf_off)
                ih = struct.pack("<IiiHHIIiiII", dib, w, h_signed, 1, bpp, comp, pix_sz, 2835, 2835, colors_used, 0)
                return fh + ih + extra + pal + (b"\x00" * pix_sz)

            def _mk_webp_riff(chunks: list[tuple[bytes, bytes]]) -> bytes:
                body = bytearray(b"WEBP")
                for tag, payload in chunks:
                    body.extend(tag + struct.pack("<I", len(payload)) + payload)
                    if len(payload) & 1:
                        body.append(0)
                return b"RIFF" + struct.pack("<I", len(body)) + bytes(body)

            def _build_vp8_bpred_2part_webp(log2_parts: int = 1) -> bytes:
                kf_bmode = bytes.fromhex(
                    "e7783059737178987098b3407eaa762e465faf458f505552489b67383a0aabda"
                    "bd110d9890470a26abd590221a721a11a32cc3150aad791850c31a3e2c4055aa"
                    "2e371388a021ce473f14087272d00c09e251280b60b6541d102486b759896265"
                    "6aa59448bb64829d6f204b504266a7634a3e28ea80293509b2f18d1a086b684f"
                    "0c1bd9ff5711074a2b1a9249a631179d412669a033341f73805744472c72330f"
                    "ba172f290e6eb6b71511c2422d1966c5bd171216585893962a2e2dc4cd2b61b7"
                    "75552623b33d2735c8571a152be8ab3822336872661d5d4d6b36201a3301512b"
                    "1f271c55ab3aa55a6240221674ce17222ba64944196a1640ab24e17222131566"
                    "84bc104c7c3e124e5f5539323033c165239fd76f592e6f3c941facdbe415126f"
                    "70714d55b3ff267872282a01c4f5d10a196d6450082b9a01331a47582b1d8ca6"
                    "d5252b9a3d3f1e9b432d4401d18e4e4e10ff8022c5ab29280566d3b70401dd33"
                    "3211a8d1c01719527d622a58685575af525f543559806471652d4b4f7b2f3380"
                    "51ab013911054766393529317315020a66ffa6170626210d7939491a0155290a"
                    "438a4d6e5a2f72651d100a558065c41a39120a6666d522142b75140f24a38044"
                    "011a8a1f24ab1ba6262ce543573aa952731a3bb33f3b5ab43ba65d499a282815"
                    "748fd12227af392e161880013611252f0f10b722df312db72e1121b706620f20"
                    "b7412049731c801780cd2803097333c01206df572509733b4d40152f68372cda"
                    "09363582e2405a46cd2829171a39363970b8052926a6d51e221a8598740a2086"
                    "4b200c33c0ffa02b33271335dd1a722049ff1f0941ea020f017649581f234366"
                    "5537ba553815176f3bcd2d25c03726467c4966012262663d472522351ff3c045"
                    "3c472649771cde25442d8022012f0bf5ab3e1113469255373e464b0f090940ff"
                    "b87710252b259a64a355a0013f095c881c4020c95556061c0540ff19f8013808"
                    "118489ff3774803a0f145287391a7928a4321f899a851923da33672c83837b1f"
                    "069e5628408794e02db780161a1183f09a0e01d1530c0d36c0ff442f1c2d1015"
                    "5b40de0701c53815279b3c8a1766d5551a555580802092ab120b073f90ab0404"
                    "f6231b0a92aeab0c1a80be502363b4507e362d557e2f57b033291420654b808b"
                    "769274805538290fb0ec5525093e9224131eabff611b14471e117776ff11128a"
                    "65263c8a37462b1a8e8a2d3d3edb0151bc4020291475978e1415a370130c3dc3"
                    "80300418"
                )
                coeff_update = bytes.fromhex(
                    "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffb0f6ffffffffffffffffffdff1fcfffffffffffffffff9fdfdfffffffffffffffffff4fcffffffffffffffffeafefefffffffffffffffffdfffffffffffffffffffffff6feffffffffffffffffeffdfefffffffffffffffffefffefffffffffffffffffff8fefffffffffffffffffbfffefffffffffffffffffffffffffffffffffffffffffdfefffffffffffffffffbfefefffffffffffffffffefffefffffffffffffffffffefdfffefffffffffffffafffefffefffffffffffffeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffd9ffffffffffffffffffffe1fcf1fdfffffeffffffffeafaf1fafdfffdfefffffffffeffffffffffffffffffdffefeffffffffffffffffeefdfefefffffffffffffffff8fefffffffffffffffff9fefffffffffffffffffffffffffffffffffffffffffffdfffffffffffffffffff7fefffffffffffffffffffffffffffffffffffffffffffdfefffffffffffffffffcfffffffffffffffffffffffffffffffffffffffffffffefefffffffffffffffffdfffffffffffffffffffffffffffffffffffffffffffffefdfffffffffffffffffafffffffffffffffffffffeffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffbafbfaffffffffffffffffeafbf4fefffffffffffffffbfbf3fdfefffefffffffffffdfeffffffffffffffffecfdfefffffffffffffffffbfdfdfefefffffffffffffffefefffffffffffffffffefefefffffffffffffffffffffffffffffffffffffffffefffffffffffffffffffefefffffffffffffffffffefffffffffffffffffffffffffffffffffffffffffffefffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff8fffffffffffffffffffffafefcfefffffffffffffff8fef9fdfffffffffffffffffdfdfffffffffffffffff6fdfdfffffffffffffffffcfefbfefefffffffffffffffefcfffffffffffffffff8fefdfffffffffffffffffdfffefefffffffffffffffffbfefffffffffffffffff5fbfefffffffffffffffffdfdfefffffffffffffffffffbfdfffffffffffffffffcfdfefffffffffffffffffffefffffffffffffffffffffcfffffffffffffffffff9fffefffffffffffffffffffffefffffffffffffffffffffdfffffffffffffffffafffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffeffffffffffffffffffffffffffffffffffffffffff"
                )
                default_coeff_p0_b0 = (0xCA, 0x80)  # type 3 (Y with DC) band 0 ctx 0 EOB=0xCA, type 2 (UV) band 0 ctx 0 EOB=0xCA

                class _VP8BoolEnc:
                    def __init__(self) -> None:
                        self.low = 0
                        self.rng = 255
                        self.cnt = -24
                        self.out = bytearray()

                    def put(self, bit: int, prob: int = 128) -> None:
                        split = 1 + (((self.rng - 1) * prob) >> 8)
                        if bit:
                            self.low += split
                            self.rng -= split
                        else:
                            self.rng = split
                        while self.rng < 128:
                            self.rng <<= 1
                            self.low <<= 1
                            self.cnt += 1
                            if self.cnt == 0:
                                if self.low & (1 << 32):
                                    idx = len(self.out) - 1
                                    while idx >= 0 and self.out[idx] == 255:
                                        self.out[idx] = 0
                                        idx -= 1
                                    if idx >= 0:
                                        self.out[idx] += 1
                                self.out.append((self.low >> 24) & 0xFF)
                                self.low &= 0xFFFFFF
                                self.cnt = -8

                    def put_uint(self, val: int, nbits: int) -> None:
                        for sh in range(nbits - 1, -1, -1):
                            self.put((val >> sh) & 1, 128)

                    def finish(self) -> bytes:
                        for _ in range(32):
                            self.put(0, 128)
                        return bytes(self.out)

                def _put_bmode(enc: _VP8BoolEnc, poff: int, bm: int) -> None:
                    if bm == 0:
                        enc.put(0, kf_bmode[poff]); return
                    enc.put(1, kf_bmode[poff])
                    if bm == 1:
                        enc.put(0, kf_bmode[poff + 1]); return
                    enc.put(1, kf_bmode[poff + 1])
                    if bm == 2:
                        enc.put(0, kf_bmode[poff + 2]); return
                    enc.put(1, kf_bmode[poff + 2])
                    if bm in (3, 5, 6):
                        enc.put(0, kf_bmode[poff + 3])
                        if bm == 3:
                            enc.put(0, kf_bmode[poff + 4]); return
                        enc.put(1, kf_bmode[poff + 4])
                        enc.put(0 if bm == 5 else 1, kf_bmode[poff + 5])
                        return
                    enc.put(1, kf_bmode[poff + 3])
                    if bm == 4:
                        enc.put(0, kf_bmode[poff + 6]); return
                    enc.put(1, kf_bmode[poff + 6])
                    if bm == 7:
                        enc.put(0, kf_bmode[poff + 7]); return
                    enc.put(1, kf_bmode[poff + 7])
                    enc.put(0 if bm == 8 else 1, kf_bmode[poff + 8])

                mb_dim = 8 if log2_parts == 2 else 2
                px_dim = mb_dim * 16
                num_parts = 1 << log2_parts
                p0 = _VP8BoolEnc()
                for _ in range(3):
                    p0.put(0, 128)  # cs, clamp, seg
                p0.put(0, 128)  # filter_type
                p0.put_uint(0, 6)  # lf_level
                p0.put_uint(0, 3)  # sharpness
                p0.put(0, 128)  # lf_delta
                p0.put_uint(log2_parts, 2)  # log2_parts => 2 or 4 DCT partitions
                p0.put_uint(0, 7)  # y_ac_qi
                for _ in range(5):
                    p0.put(0, 128)
                p0.put(0, 128)  # refresh_probs
                for cu_p in coeff_update:
                    p0.put(0, cu_p)
                p0.put(0, 128)  # mb_no_skip
                above_b = [0] * (mb_dim * 4)
                seq_modes = [4, 5, 6, 4, 5, 6, 4, 5, 6, 4, 5, 6, 0, 1, 2, 3]
                for _my in range(mb_dim):
                    left_b = [0] * 4
                    for mx in range(mb_dim):
                        p0.put(0, 145)  # y_mode = 4 (B_PRED)
                        mx4 = mx * 4
                        k_bm = 0
                        for by in range(4):
                            for bx in range(4):
                                bm = seq_modes[k_bm]
                                k_bm += 1
                                poff = (above_b[mx4 + bx] * 10 + left_b[by]) * 9
                                _put_bmode(p0, poff, bm)
                                above_b[mx4 + bx] = bm
                                left_b[by] = bm
                        p0.put(0, 142)  # uv_mode = 0
                p0_bytes = p0.finish()
                d_parts = []
                rows_per_part = mb_dim // num_parts
                for _part in range(num_parts):
                    de = _VP8BoolEnc()
                    for _row in range(rows_per_part):
                        for _mb in range(mb_dim):
                            for _blk in range(24):
                                de.put(0, default_coeff_p0_b0[0])
                    d_parts.append(de.finish())
                ftag = (1 << 4) | (len(p0_bytes) << 5)
                vp8_hdr = bytes([ftag & 0xFF, (ftag >> 8) & 0xFF, (ftag >> 16) & 0xFF, 0x9D, 0x01, 0x2A]) + struct.pack("<HH", px_dim, px_dim)
                dct_hdr = b"".join(struct.pack("<I", len(d_parts[pi]))[:3] for pi in range(num_parts - 1))
                return _mk_webp_riff([(b"VP8 ", vp8_hdr + p0_bytes + dct_hdr + b"".join(d_parts))])

            png_bad_adler = bytearray(_mk_custom_png(1, 1, 8, 6, b"\x00\x01\x02\x03\x04"))
            # Flip last byte of IDAT zlib payload (before 4-byte IDAT CRC and 12-byte IEND)
            idat_end_pos = len(png_bad_adler) - 12 - 4 - 1
            png_bad_adler[idat_end_pos] ^= 0xFF
            # Fix IDAT CRC (IDAT starts after 8B sig + 25B IHDR = 33; chunk len is at 33..37)
            idat_len = struct.unpack(">I", png_bad_adler[33:37])[0]
            new_crc = zlib.crc32(png_bad_adler[37:37 + 4 + idat_len]) & 0xFFFFFFFF
            png_bad_adler[37 + 4 + idat_len:37 + 4 + idat_len + 4] = struct.pack(">I", new_crc)

            # Stored zlib (BTYPE=0) 4x4 RGBA8 positive control
            raw_4x4 = b"\x00" * (4 * 17)
            stored_zlib = b"\x78\x01\x01" + struct.pack("<HH", len(raw_4x4), len(raw_4x4) ^ 0xFFFF) + raw_4x4 + struct.pack(">I", zlib.adler32(raw_4x4) & 0xFFFFFFFF)

            # Valid VP8L 4x4 chunk (simple tree 1 sym) for container tests
            bw_vp8l = _BitWriter()
            bw_vp8l.write_lsb(0, 1)  # no transforms
            bw_vp8l.write_lsb(0, 1)  # no color cache
            bw_vp8l.write_lsb(0, 1)  # no meta huffman
            for _t in range(4):
                bw_vp8l.write_lsb(1, 1); bw_vp8l.write_lsb(0, 1); bw_vp8l.write_lsb(0, 1); bw_vp8l.write_lsb(0, 1)
            bw_vp8l.write_lsb(1, 1); bw_vp8l.write_lsb(0, 1); bw_vp8l.write_lsb(0, 1); bw_vp8l.write_lsb(0, 1)
            vp8l_4x4_bits = struct.pack("<BI", 0x2F, (3) | (3 << 14)) + bw_vp8l.finish()
            vp8_4x4_hdr = b"\x00\x00\x00\x9d\x01\x2a" + struct.pack("<HH", 4, 4)

            app0_v2 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x02\x00\x01\x00\x48\x00\x48\x00\x00"
            app0_v0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x00\x01\x01\x00\x48\x00\x48\x00\x00"
            app0_v1 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x01\x00\x48\x00\x48\x00\x00"

            billion_use_svg = (
                b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
                b'<g id="g0"><rect width="1" height="1"/></g>'
                + "".join(
                    f'<g id="g{i}">' + (f'<use href="#g{i-1}"/>' * 8) + "</g>"
                    for i in range(1, 9)
                ).encode("ascii")
                + b'<use href="#g8"/></svg>'
            )

            t5_extra_imgs = {
                # PNG IDAT / Adam7 / PLTE
                "png_corrupt_deflate": ("png", _mk_custom_png(4, 4, 8, 6, b"", idat_override=b"\x78\x9c\xff\xff\xff\xff\xff")),
                "png_trunc_scanlines": ("png", _mk_custom_png(4, 4, 8, 6, b"\x00" * 4)),
                "png_bad_filter_byte": ("png", _mk_custom_png(1, 1, 8, 6, b"\x09\x00\x00\x00\x00")),
                "png_bad_adler32": ("png", bytes(png_bad_adler)),
                "png_huge_decompress_trunc": ("png", _mk_custom_png(1000, 1000, 8, 6, b"\x00" * 100)),
                "png_interlaced_trunc": ("png", _mk_custom_png(8, 8, 8, 6, b"\x00" * 10, interlace=1)),
                "png_valid_adam7": ("png", _mk_custom_png(8, 8, 8, 6, b"\x00" * 271, interlace=1)),
                "png_valid_stored_zlib": ("png", _mk_custom_png(4, 4, 8, 6, b"", idat_override=stored_zlib)),
                "png_gray_with_plte": ("png", _mk_custom_png(1, 1, 8, 0, b"\x00\x80", [(b"PLTE", b"\x00\x00\x00\xff\xff\xff")])),
                "png_gray_alpha_with_plte": ("png", _mk_custom_png(1, 1, 8, 4, b"\x00\x80\xff", [(b"PLTE", b"\x00\x00\x00\xff\xff\xff")])),
                "png_1bit_plte_oversized": ("png", _mk_custom_png(2, 2, 1, 3, b"\x00\x00\x00\x00", [(b"PLTE", b"\x00\x00\x00\x11\x11\x11\x22\x22\x22\x33\x33\x33")])),
                "png_plte_oob_idx": ("png", _mk_custom_png(1, 1, 8, 3, b"\x00\x05", [(b"PLTE", b"\x00\x00\x00\xff\xff\xff")])),
                "png_trns_gt_plte": ("png", _mk_custom_png(1, 1, 8, 3, b"\x00\x00", [(b"PLTE", b"\x00\x00\x00\xff\xff\xff"), (b"tRNS", b"\xff\x80\x40\x20")])),
                # WebP container & bitstream
                "webp_vp8_trunc_payload": ("webp", _mk_webp_riff([(b"VP8 ", vp8_4x4_hdr + b"\x00\x00")])),
                "webp_vp8_bad_part0": ("webp", _mk_webp_riff([(b"VP8 ", b"\x00\x10\x00\x9d\x01\x2a" + struct.pack("<HH", 4, 4) + b"\x00\x00")])),
                "webp_vp8l_trunc_payload": ("webp", _mk_webp_riff([(b"VP8L", struct.pack("<BI", 0x2F, 3 | (3 << 14)) + b"\x00")])),
                "webp_vp8l_bad_version": ("webp", _mk_webp_riff([(b"VP8L", struct.pack("<BI", 0x2F, 3 | (3 << 14) | (1 << 29)) + vp8l_4x4_bits[5:])])),
                "webp_vp8x_odd_len": ("webp", _mk_webp_riff([(b"VP8X", b"\x00" * 12), (b"VP8L", vp8l_4x4_bits)])),
                "webp_alph_empty": ("webp", _mk_webp_riff([(b"VP8X", b"\x10\x00\x00\x00\x03\x00\x00\x03\x00\x00"), (b"ALPH", b""), (b"VP8 ", vp8_4x4_hdr + b"\x00\x00")])),
                "webp_alph_bad_method": ("webp", _mk_webp_riff([(b"VP8X", b"\x10\x00\x00\x00\x03\x00\x00\x03\x00\x00"), (b"ALPH", b"\x03\x00"), (b"VP8 ", vp8_4x4_hdr + b"\x00\x00")])),
                "webp_dual_vp8": ("webp", _mk_webp_riff([(b"VP8 ", vp8_4x4_hdr + b"\x00\x00"), (b"VP8 ", vp8_4x4_hdr + b"\x00\x00")])),
                "webp_vp8x_alpha_no_alph": ("webp", _mk_webp_riff([(b"VP8X", b"\x10\x00\x00\x00\x03\x00\x00\x03\x00\x00"), (b"VP8 ", vp8_4x4_hdr + b"\x00\x00")])),
                "webp_alph_no_vp8x": ("webp", _mk_webp_riff([(b"ALPH", b"\x00" * 17), (b"VP8 ", vp8_4x4_hdr + b"\x00\x00")])),
                "webp_vp8x_noflag_plus_alph": ("webp", _mk_webp_riff([(b"VP8X", b"\x00\x00\x00\x00\x03\x00\x00\x03\x00\x00"), (b"ALPH", b"\x00" * 17), (b"VP8 ", vp8_4x4_hdr + b"\x00\x00")])),
                "webp_vp8x_after_vp8": ("webp", _mk_webp_riff([(b"VP8L", vp8l_4x4_bits), (b"VP8X", b"\x00\x00\x00\x00\x03\x00\x00\x03\x00\x00")])),
                "webp_valid_vp8_bpred_multipart": ("webp", _build_vp8_bpred_2part_webp()),
                # BMP bfSize, bitfields zero masks, 16-bit BI_RGB, 24-bit colors_used, combined top-down + short palette
                "bmp_bfsize_0": ("bmp", _mk_bmp_adv(2, 2, 24, 0, 40, bf_size_override=0)),
                "bmp_bfsize_69": ("bmp", _mk_bmp_adv(2, 2, 24, 0, 40, bf_size_override=69)),
                "bmp_bfsize_70": ("bmp", _mk_bmp_adv(2, 2, 24, 0, 40, bf_size_override=70)),
                "bmp_bfsize_999": ("bmp", _mk_bmp_adv(2, 2, 24, 0, 40, bf_size_override=999)),
                "bmp_bf_zero_d40": ("bmp", _mk_bmp_adv(2, 2, 16, 3, 40, masks=(0, 0, 0))),
                "bmp_bf_zero_d108": ("bmp", _mk_bmp_adv(2, 2, 32, 3, 108, masks=(0, 0, 0))),
                "bmp_bf_zero_d124": ("bmp", _mk_bmp_adv(2, 2, 32, 3, 124, masks=(0, 0, 0))),
                "bmp_16bit_bi_rgb": ("bmp", _mk_bmp_adv(2, 2, 16, 0, 40)),
                "bmp_24bit_colors_used_999999": ("bmp", _mk_bmp_adv(2, 2, 24, 0, 40, colors_used=999999)),
                "bmp_8bit_topdown_short_pal": ("bmp", _mk_bmp_adv(2, -2, 8, 0, 40, colors_used=2, pal_entries=[b"\x10\x20\x30\x00", b"\x40\x50\x60\x00"])),
                "bmp_1bit_topdown_short_pal": ("bmp", _mk_bmp_adv(2, -2, 1, 0, 40, colors_used=1, pal_entries=[b"\x10\x20\x30\x00"])),
                "bmp_4bit_topdown_short_pal": ("bmp", _mk_bmp_adv(2, -2, 4, 0, 40, colors_used=2, pal_entries=[b"\x10\x20\x30\x00", b"\x40\x50\x60\x00"])),
                # JPEG APP0 JFIF version
                "jpg_app0_v2": ("jpg", b"\xff\xd8" + app0_v2 + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_1comp_seg + sos_seg + b"\xff\xd9"),
                "jpg_app0_v0": ("jpg", b"\xff\xd8" + app0_v0 + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_1comp_seg + sos_seg + b"\xff\xd9"),
                "jpg_app0_v1_ok": ("jpg", b"\xff\xd8" + app0_v1 + dqt_seg + dht_dc_seg + dht_ac_seg + sof0_1comp_seg + sos_seg + b"\x00\x00\xff\xd9"),
                # SVG <use>, CSS units, viewBox whitespace, subpixel, extreme viewBox
                "svg_mutual_use_cycle": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><g id="a"><use href="#b"/></g><g id="b"><use href="#a"/></g><use href="#a"/></svg>'),
                "svg_xlink_use_cycle": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="16" height="16"><g id="a"><use xlink:href="#b"/></g><g id="b"><use xlink:href="#a"/></g><use xlink:href="#a"/></svg>'),
                "svg_billion_use": ("svg", billion_use_svg),
                "svg_valid_use": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><defs><rect id="r" width="4" height="4"/></defs><use href="#r" x="2" y="2"/></svg>'),
                "svg_unit_pt": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="16pt" height="16pt"><rect width="16" height="16"/></svg>'),
                "svg_unit_pc": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="2pc" height="2pc"><rect width="16" height="16"/></svg>'),
                "svg_unit_in": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="1in" height="1in"><rect width="16" height="16"/></svg>'),
                "svg_unit_cm": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="1cm" height="1cm"><rect width="16" height="16"/></svg>'),
                "svg_unit_mm": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="10mm" height="10mm"><rect width="16" height="16"/></svg>'),
                "svg_unit_q": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="40q" height="40q"><rect width="16" height="16"/></svg>'),
                "svg_unit_pct_bad": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="50%" height="50%"><rect width="16" height="16"/></svg>'),
                "svg_unit_em_bad": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="2em" height="2em"><rect width="16" height="16"/></svg>'),
                "svg_vb_whitespace": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0\t0\n16\r16"><rect width="16" height="16"/></svg>'),
                "svg_subpixel_0_1": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="0.1" height="0.1"><rect width="1" height="1"/></svg>'),
                "svg_extreme_vb_100000": ("svg", b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 100000 100000"><rect width="100000" height="100000"/></svg>'),
                # MIME/ext mismatch
                "mime_png_as_jpg": ("jpg", png),
            }
            for k_ex, (ext_ex, b_ex) in t5_extra_imgs.items():
                img_bad_vectors[k_ex] = {"ext": ext_ex, "b64": base64.b64encode(b_ex).decode("ascii")}

            # R5 PNG chunk bit validation (critical c0&0x20==0 & reserved c2&0x20!=0 before IDAT; post-IDAT & valid ancillary allowed)
            png_2x2_raw = b"\x00" * 18
            png_chunk_foob_crit_b = _mk_custom_png(2, 2, 8, 6, png_2x2_raw, [(b"FOOB", b"test")])
            png_chunk_foob_crit_lower3_b = _mk_custom_png(2, 2, 8, 6, png_2x2_raw, [(b"FOOb", b"test")])
            png_chunk_foob_rsv_b = _mk_custom_png(2, 2, 8, 6, png_2x2_raw, [(b"foob", b"test")])
            png_chunk_fOOb_before_b = _mk_custom_png(2, 2, 8, 6, png_2x2_raw, [(b"fOOb", b"test")])
            png_chunk_foOb_before_b = _mk_custom_png(2, 2, 8, 6, png_2x2_raw, [(b"foOb", b"test")])
            png_chunk_foob_after_b = (
                b"\x89PNG\r\n\x1a\n"
                + _mk_png_chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0))
                + _mk_png_chunk(b"IDAT", zlib.compress(png_2x2_raw))
                + _mk_png_chunk(b"FOOB", b"test")
                + _mk_png_chunk(b"IEND", b"")
            )
            for k_pngc, b_pngc, chk_nat in (
                ("png_chunk_FOOB_before", png_chunk_foob_crit_b, False),
                ("png_chunk_FOOb_before", png_chunk_foob_crit_lower3_b, False),
                ("png_chunk_foob_before", png_chunk_foob_rsv_b, False),
                ("png_chunk_fOOb_before", png_chunk_fOOb_before_b, True),
                ("png_chunk_foOb_before", png_chunk_foOb_before_b, True),
                ("png_chunk_FOOB_after", png_chunk_foob_after_b, True),
            ):
                img_bad_vectors[k_pngc] = {
                    "ext": "png",
                    "b64": base64.b64encode(b_pngc).decode("ascii"),
                    "check_native_png": chk_nat,
                }

            d_png_crit = fdir / "png_crit_before"
            build_v9_world(
                d_png_crit,
                world_json=make_v9_world_json(name="pcrit", title="PngCrit"),
                scenes=[make_v9_scene("s1", "S1", img="worlds/pcrit/assets/crit.png")],
                actors=[make_v9_actor("a1", "A1")],
            )
            (d_png_crit / "assets").mkdir(parents=True, exist_ok=True)
            (d_png_crit / "assets" / "crit.png").write_bytes(png_chunk_foob_crit_b)
            entry_cases.append({"id": "png_crit_before_strict", "path": str(d_png_crit / "world.json"), "opts": {"skip_missing_assets": False}})
            entry_cases.append({"id": "png_crit_before_skip", "path": str(d_png_crit / "world.json"), "opts": {"skip_missing_assets": True}})

            d_png_rsv = fdir / "png_rsv_before"
            build_v9_world(
                d_png_rsv,
                world_json=make_v9_world_json(name="prsv", title="PngRsv"),
                scenes=[make_v9_scene("s1", "S1", img="worlds/prsv/assets/rsv.png")],
                actors=[make_v9_actor("a1", "A1")],
            )
            (d_png_rsv / "assets").mkdir(parents=True, exist_ok=True)
            (d_png_rsv / "assets" / "rsv.png").write_bytes(png_chunk_foob_rsv_b)
            entry_cases.append({"id": "png_rsv_before_strict", "path": str(d_png_rsv / "world.json"), "opts": {"skip_missing_assets": False}})
            entry_cases.append({"id": "png_rsv_before_skip", "path": str(d_png_rsv / "world.json"), "opts": {"skip_missing_assets": True}})

            # R5 NeDB $$indexCreated/$$indexRemoved directive filtering + anonymous namespace isolation
            d_nedb_idx_anon = fdir / "nedb_idx_anon"
            build_v9_world(
                d_nedb_idx_anon,
                world_json=make_v9_world_json(name="nida", title="NedbIdxAnon"),
                scenes=[],
                actors=[],
            )
            (d_nedb_idx_anon / "data" / "scenes.db").write_text(
                "\n".join([
                    json.dumps({"$$indexCreated": {"fieldName": "_id", "unique": True}}),
                    json.dumps(make_v9_scene("s1", "Real Tavern")),
                    json.dumps({"$$indexRemoved": "sort"}),
                ]) + "\n",
                encoding="utf-8",
            )
            (d_nedb_idx_anon / "data" / "actors.db").write_text(
                "\n".join([
                    json.dumps({"name": "AnonLine1", "type": "npc"}),
                    json.dumps({"_id": "__anon_1", "name": "ExplicitAnon1", "type": "npc"}),
                    json.dumps({"$$deleted": True, "_id": "__anon_1"}),
                    json.dumps({"$$indexCreated": {"fieldName": "folder"}}),
                    json.dumps({"$$indexRemoved": "type"}),
                    json.dumps(make_v9_actor("a1", "Goblin", actor_type="npc")),
                ]) + "\n",
                encoding="utf-8",
            )
            entry_cases.append({"id": "nedb_idx_anon", "path": str(d_nedb_idx_anon / "world.json"), "opts": {"skip_missing_assets": False}})

            # Integration cases: token-inherits-actor (%20 & #), 0-byte ZIP asset, .gif ext with PNG bytes, non-ASCII 0-byte ZIP CD, evil archive_image, post-map cancel
            d_tok_pct = fdir / "tok_pct"
            build_v9_world(
                d_tok_pct,
                world_json=make_v9_world_json(name="pw", title="PctWorld"),
                scenes=[make_v9_scene("s1", "S1", tokens=[make_v9_token("t1", "T1", actor_id="a1", img="")])],
                actors=[make_v9_actor("a1", "A1", img="worlds/pw/assets/100%2520ok.png")],
            )
            (d_tok_pct / "assets").mkdir(parents=True, exist_ok=True)
            (d_tok_pct / "assets" / "100%20ok.png").write_bytes(png)
            entry_cases.append({"id": "tok_inherits_pct", "path": str(d_tok_pct / "world.json"), "opts": {"skip_missing_assets": False}})

            d_tok_hash = fdir / "tok_hash"
            build_v9_world(
                d_tok_hash,
                world_json=make_v9_world_json(name="hw", title="HashWorld"),
                scenes=[make_v9_scene("s1", "S1", tokens=[make_v9_token("t1", "T1", actor_id="a1", img="")])],
                actors=[make_v9_actor("a1", "A1", img="worlds/hw/assets/photo%231.png")],
            )
            (d_tok_hash / "assets").mkdir(parents=True, exist_ok=True)
            (d_tok_hash / "assets" / "photo#1.png").write_bytes(png)
            entry_cases.append({"id": "tok_inherits_hash", "path": str(d_tok_hash / "world.json"), "opts": {"skip_missing_assets": False}})

            z_zero_asset = fdir / "zero_asset.zip"
            _build_raw_zip(z_zero_asset, [
                {"name_bytes": b"world.json", "payload": wj_b},
                {"name_bytes": b"data/scenes.db", "payload": (json.dumps(make_v9_scene("s1", "S1", img="worlds/t5/assets/empty.png")) + "\n").encode("utf-8")},
                {"name_bytes": b"data/actors.db", "payload": ac_b},
                {"name_bytes": b"assets/empty.png", "payload": b""},
            ])
            entry_cases.append({"id": "zip_zero_asset_strict", "path": str(z_zero_asset), "opts": {"skip_missing_assets": False}})
            entry_cases.append({"id": "zip_zero_asset_skip", "path": str(z_zero_asset), "opts": {"skip_missing_assets": True}})

            d_gif_png = fdir / "gif_png"
            build_v9_world(
                d_gif_png,
                world_json=make_v9_world_json(name="gp", title="GifPng"),
                scenes=[make_v9_scene("s1", "S1", img="worlds/gp/assets/fake.gif")],
                actors=[make_v9_actor("a1", "A1")],
            )
            (d_gif_png / "assets").mkdir(parents=True, exist_ok=True)
            (d_gif_png / "assets" / "fake.gif").write_bytes(png)
            entry_cases.append({"id": "gif_png_strict", "path": str(d_gif_png / "world.json"), "opts": {"skip_missing_assets": False}})
            entry_cases.append({"id": "gif_png_skip", "path": str(d_gif_png / "world.json"), "opts": {"skip_missing_assets": True}})

            z_nonascii_0b = fdir / "nonascii_0b.zip"
            _build_raw_zip(z_nonascii_0b, [{"name_bytes": b"\x80\x81\xfe.png", "payload": b"", "comp_method": 0}])

            d_rem_evil = fdir / "rem_evil"
            build_v9_world(
                d_rem_evil,
                world_json=make_v9_world_json(name="re", title="RemEvil"),
                scenes=[make_v9_scene("s1", "S1", img="https://example.com/evil.png")],
                actors=[make_v9_actor("a1", "A1")],
            )

            d_post_cancel = fdir / "post_cancel"
            build_v9_world(
                d_post_cancel,
                world_json=make_v9_world_json(name="pc", title="PostCancel"),
                scenes=[make_v9_scene("s1", "S1", img="worlds/pc/assets/bg.png")],
                actors=[make_v9_actor("a1", "A1", actor_type="character")],
            )
            (d_post_cancel / "assets").mkdir(parents=True, exist_ok=True)
            (d_post_cancel / "assets" / "bg.png").write_bytes(png)

            bgdia_images: list[dict[str, str]] = []
            cls.bgdia_wj = resolve_bgdia_dir_world_json(workspace_root=_WORKSPACE_ROOT)
            cls.has_bgdia_dir = cls.bgdia_wj is not None and cls.bgdia_wj.is_file()
            if cls.has_bgdia_dir:
                assert cls.bgdia_wj is not None
                bg_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".svg", ".gif"}
                for p_bg in sorted(cls.bgdia_wj.parent.rglob("*")):
                    if p_bg.is_file() and p_bg.suffix.lower() in bg_exts:
                        bgdia_images.append({"path": str(p_bg), "ext": p_bg.suffix.lower().lstrip(".")})

            iso = cls.run_dir / "iso"
            iso.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            env["APPDATA"] = env["LOCALAPPDATA"] = env["TEMP"] = env["TMP"] = str(iso)

            (probe_dir / "oracle.gd").write_text(_WEBP_ORACLE_GD, encoding="utf-8")
            (probe_dir / "vp8_4part.bin").write_bytes(_build_vp8_bpred_2part_webp(2))
            oracle_out_p = cls.run_dir / "oracle_out.json"
            oracle_log_p = cls.run_dir / "oracle_godot.log"
            oracle_proc = subprocess.run(
                [str(cfg.godot_bin), "--headless", "--quit", "--path", str(probe_dir), "--log-file", str(oracle_log_p), "--script", "res://oracle.gd", "--", f"--out={oracle_out_p}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if oracle_proc.returncode != 0 or not oracle_out_p.is_file():
                raise AssertionError(f"WebP oracle failed rc={oracle_proc.returncode}\nSTDERR:\n{oracle_proc.stderr[-1000:]}")
            oracle_vecs = json.loads(oracle_out_p.read_text(encoding="utf-8")).get("vectors", [])
            cls.webp_tail_oracle = {str(v["id"]): v for v in oracle_vecs}

            # Phase 2 Iter 16 (Challenger 2 Challenges 2-5) fixtures
            r17_grid_cases: list[dict[str, str]] = []
            for g_id, g_scenes in (
                (
                    "tiny_1e_308",
                    [
                        make_v9_scene("s0", "Base100", grid=100, img="worlds/r17g/assets/bg.png"),
                        make_v9_scene(
                            "s1",
                            "Tiny308",
                            grid=1e-308,
                            img="worlds/r17g/assets/bg.png",
                            walls=[make_wall("w1", [0, 0, 100, 0])],
                            lights=[{"_id": "l1", "x": 150, "y": 150, "bright": 20, "dim": 40, "angle": 360, "hidden": False}],
                            tokens=[make_v9_token("tk1", "Tok1", actor_id="a1", x=200, y=300, width=1, height=1)],
                        ),
                    ],
                ),
                (
                    "tiny_1e_20",
                    [
                        make_v9_scene("s0", "Base100", grid=100, img="worlds/r17g/assets/bg.png"),
                        make_v9_scene(
                            "s1",
                            "Tiny20",
                            grid=1e-20,
                            img="worlds/r17g/assets/bg.png",
                            walls=[make_wall("w1", [0, 0, 100, 0])],
                            lights=[{"_id": "l1", "x": 150, "y": 150, "bright": 20, "dim": 40, "angle": 360, "hidden": False}],
                            tokens=[make_v9_token("tk1", "Tok1", actor_id="a1", x=200, y=300, width=1, height=1)],
                        ),
                    ],
                ),
                (
                    "huge_1e40",
                    [
                        make_v9_scene(
                            "s0",
                            "Huge40",
                            grid=1e40,
                            img="worlds/r17g/assets/bg.png",
                            walls=[make_wall("w1", [0, 0, 100, 0])],
                            lights=[{"_id": "l1", "x": 150, "y": 150, "bright": 20, "dim": 40, "angle": 360, "hidden": False}],
                            tokens=[make_v9_token("tk1", "Tok1", actor_id="a1", x=200, y=300, width=1, height=1)],
                        ),
                    ],
                ),
                (
                    "ortho_huge_wall",
                    [
                        make_v9_scene(
                            "s0",
                            "OrthoHugeWall",
                            grid=1.0,
                            img="worlds/r17g/assets/bg.png",
                            walls=[make_wall("w_ortho_1e37", [1e37, 0, 1e37, 1e18])],
                            tokens=[make_v9_token("tk1", "Tok1", actor_id="a1", x=200, y=300, width=1, height=1)],
                        ),
                    ],
                ),
                (
                    "wall_ulp_and_bound_mix",
                    [
                        make_v9_scene(
                            "s0",
                            "WallUlpBoundMix",
                            grid=1.0,
                            img="worlds/r17g/assets/bg.png",
                            walls=[
                                make_wall("w_diag_8e7", [-8e7, -8e7, 8e7, 8e7]),
                                make_wall("w_ortho_2e8", [-2e8, 0, 2e8, 0]),
                                make_wall("w_diag_1e15", [-1e15, -1e15, 1e15, 1e15]),
                                make_wall("w_valid_wall", [0, 0, 100, 0]),
                                make_wall("d_valid_door", [50, -40, 50, 40], door=1),
                            ],
                            tokens=[make_v9_token("tk1", "Tok1", actor_id="a1", x=200, y=300, width=1, height=1)],
                        ),
                    ],
                ),
            ):
                g_dir = fdir / f"r17_grid_{g_id}"
                build_v9_world(
                    g_dir,
                    world_json=make_v9_world_json(name="r17g", title=g_id),
                    scenes=g_scenes,
                    actors=[make_v9_actor("a1", "Tok1", actor_type="character")],
                )
                (g_dir / "assets").mkdir(parents=True, exist_ok=True)
                (g_dir / "assets" / "bg.png").write_bytes(png)
                r17_grid_cases.append({"id": g_id, "path": str(g_dir / "world.json")})

            z_dot_slash = fdir / "r17_dot_slash.zip"
            wj_ds_b = json.dumps(make_v9_world_json(name="ds", title="DotSlash")).encode("utf-8")
            sc_ds_b = (json.dumps(make_v9_scene("s1", "DotScene", img="worlds/ds/assets/bg.png")) + "\n").encode("utf-8")
            _build_raw_zip(z_dot_slash, [
                {"name_bytes": b"./world.json", "payload": wj_ds_b},
                {"name_bytes": b"./data/scenes.db", "payload": sc_ds_b},
                {"name_bytes": b"./data/actors.db", "payload": ac_b},
                {"name_bytes": b"./assets/bg.png", "payload": png},
            ])
            z_dot_slash_dup = fdir / "r17_dot_slash_dup.zip"
            _build_raw_zip(z_dot_slash_dup, [
                {"name_bytes": b"world.json", "payload": wj_ds_b, "comp_method": 0},
                {"name_bytes": b"./world.json", "payload": wj_ds_b, "comp_method": 0},
                {"name_bytes": b"data/scenes.db", "payload": sc_ds_b, "comp_method": 0},
                {"name_bytes": b"./data/scenes.db", "payload": sc_ds_b, "comp_method": 0},
                {"name_bytes": b"data/actors.db", "payload": ac_b, "comp_method": 0},
                {"name_bytes": b"./assets/bg.png", "payload": png, "comp_method": 0},
            ])
            cls.r17_dot_dup_expected_bytes = len(wj_ds_b) + len(sc_ds_b) + len(ac_b) + len(png)

            z_three_way_dup = fdir / "r18_three_way_dup.zip"
            sc_3way_b = (json.dumps(make_v9_scene("s1", "ThreeWayScene", img="worlds/ds/assets/big.png")) + "\n").encode("utf-8")
            _build_raw_zip(z_three_way_dup, [
                {"name_bytes": b"world.json", "payload": wj_ds_b, "comp_method": 0},
                {"name_bytes": b"data/scenes.db", "payload": sc_3way_b, "comp_method": 0},
                {"name_bytes": b"data/actors.db", "payload": ac_b, "comp_method": 0},
                {"name_bytes": b"assets/big.png", "payload": b"X" * 2000, "comp_method": 0},
                {"name_bytes": b"assets/./big.png", "payload": png, "comp_method": 0},
                {"name_bytes": b"assets/big.png", "payload": png, "comp_method": 0},
            ])
            cls.r18_three_way_expected_bytes = len(wj_ds_b) + len(sc_3way_b) + len(ac_b) + len(png)

            d_junction = fdir / "junction_world"
            build_v9_world(
                d_junction,
                world_json=make_v9_world_json(name="jw", title="JunctionWorld"),
                scenes=[make_v9_scene("s1", "JScene", img="worlds/jw/assets/bg.png")],
                actors=[make_v9_actor("a1", "JActor")],
            )
            (d_junction / "assets").mkdir(parents=True, exist_ok=True)
            (d_junction / "assets" / "bg.png").write_bytes(png)
            j_link = d_junction / "assets" / "loop"
            if os.name == "nt":
                subprocess.run(
                    ["cmd", "/c", "mklink", "/J", str(j_link), str(d_junction)],
                    check=True,
                    capture_output=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                os.symlink(str(d_junction), str(j_link))

            z_junk_lead = fdir / "r19_junk_lead.zip"
            sc_jl_b = (json.dumps(make_v9_scene("s1", "JunkLeadScene", img="worlds/ds/assets/ok.png")) + "\n").encode("utf-8")
            _build_raw_zip(z_junk_lead, [
                {"name_bytes": b"world.json", "payload": wj_ds_b, "comp_method": 0},
                {"name_bytes": b"data/scenes.db", "payload": sc_jl_b, "comp_method": 0},
                {"name_bytes": b"data/actors.db", "payload": ac_b, "comp_method": 0},
                {"name_bytes": b"assets/ok.png", "payload": png, "comp_method": 0},
                {"name_bytes": b"/._foo/bar.png", "payload": b"J" * 500, "comp_method": 0},
                {"name_bytes": b"C:/._foo/bar.png", "payload": b"K" * 600, "comp_method": 0},
                {"name_bytes": b"/foo/.DS_Store/bar.png", "payload": b"L" * 700, "comp_method": 0},
                {"name_bytes": b"/foo/__MACOSX", "payload": b"M" * 800, "comp_method": 0},
                {"name_bytes": b"\\._bs\\x.png", "payload": b"N" * 300, "comp_method": 0},
                {"name_bytes": b"D:\\foo\\__MACOSX", "payload": b"P" * 400, "comp_method": 0},
            ])
            cls.r19_junk_lead_expected_bytes = len(wj_ds_b) + len(sc_jl_b) + len(ac_b) + len(png)

            d_webp_noshow = fdir / "r19_webp_noshow"
            build_v9_world(
                d_webp_noshow,
                world_json=make_v9_world_json(name="wnoshow", title="WebpNoShow"),
                scenes=[make_v9_scene("s1", "BadWebpScene", img="worlds/wnoshow/assets/bad.webp")],
                actors=[make_v9_actor("a1", "A1")],
            )
            (d_webp_noshow / "assets").mkdir(parents=True, exist_ok=True)
            webp_noshow_asset_p = d_webp_noshow / "assets" / "bad.webp"

            r17_source_cases = [
                {"id": "dot_slash_zip", "path": str(z_dot_slash)},
                {"id": "dot_slash_dup_zip", "path": str(z_dot_slash_dup)},
                {"id": "three_way_dot_slash_dup_zip", "path": str(z_three_way_dup)},
                {"id": "junk_lead_colon_zip", "path": str(z_junk_lead)},
                {"id": "junction_dir", "path": str(d_junction / "world.json")},
            ]

            d_partial_sst = fdir / "r17_partial_sst"
            build_v14_world(
                d_partial_sst,
                world_json=make_v14_world_json(world_id="psst", title="PartialSST"),
                scenes=[make_v9_scene("s1", "AliveSST")],
                actors=[make_v9_actor("a1", "A1")],
            )
            sst5 = (d_partial_sst / "data" / "scenes" / "000005.ldb").read_bytes()
            k5 = b"!scenes!s1\x00\x00\x00\x00\x00\x00\x00\x01"
            k8 = b"!scenes!s2\x00\x00\x00\x00\x00\x00\x00\x01"
            (d_partial_sst / "data" / "scenes" / "MANIFEST-000001").write_bytes(
                build_manifest_bytes(
                    ldb_files=[(5, len(sst5), k5, k5), (8, 128, k8, k8)],
                    log_number=9,
                    next_file_number=10,
                    last_sequence=10,
                )
            )

            d_miss_man = fdir / "r17_miss_man"
            build_v14_world(
                d_miss_man,
                world_json=make_v14_world_json(world_id="mman", title="MissMan"),
                scenes=[make_v9_scene("s1", "FallbackScene")],
                actors=[make_v9_actor("a1", "A1")],
            )
            (d_miss_man / "data" / "scenes" / "CURRENT").write_bytes(b"MANIFEST-000099\n")

            d_emb_lvl = fdir / "r17_emb_levels"
            sc_emb = {
                "_id": "s_emb",
                "name": "EmbLevelScene",
                "active": True,
                "width": 1000,
                "height": 1000,
                "grid": {"size": 100, "type": 1, "distance": 5, "units": "ft"},
                "levels": [{"_id": "lv1", "background": {"src": "worlds/embl/assets/emb_bg.png"}}],
                "initialLevel": "lv1",
            }
            build_v9_world(
                d_emb_lvl,
                world_json=make_v14_world_json(world_id="embl", title="EmbLevels"),
                scenes=[sc_emb],
                actors=[make_v9_actor("a1", "A1")],
            )
            (d_emb_lvl / "assets").mkdir(parents=True, exist_ok=True)
            (d_emb_lvl / "assets" / "emb_bg.png").write_bytes(png)

            r17_ldb_cases = [
                {"id": "partial_missing_sst", "path": str(d_partial_sst / "world.json")},
                {"id": "missing_manifest_file", "path": str(d_miss_man / "world.json")},
            ]

            def _write_vp8l_s1(bw: _BitWriter, sym: int) -> None:
                bw.write_lsb(1, 1)
                bw.write_lsb(0, 1)
                if sym <= 1:
                    bw.write_lsb(0, 1)
                    bw.write_lsb(sym, 1)
                else:
                    bw.write_lsb(1, 1)
                    bw.write_lsb(sym, 8)

            def _write_vp8l_s2(bw: _BitWriter, sym0: int, sym1: int) -> None:
                bw.write_lsb(1, 1)
                bw.write_lsb(1, 1)
                if sym0 <= 1:
                    bw.write_lsb(0, 1)
                    bw.write_lsb(sym0, 1)
                else:
                    bw.write_lsb(1, 1)
                    bw.write_lsb(sym0, 8)
                bw.write_lsb(sym1, 8)

            def _mk_vp8l_webp(w_px: int, h_px: int, payload_bits: bytes) -> bytes:
                hdr = struct.pack("<BI", 0x2F, ((w_px - 1) & 0x3FFF) | (((h_px - 1) & 0x3FFF) << 14))
                return _mk_webp_riff([(b"VP8L", hdr + payload_bits)])

            # 16384x8192 (134,217,728 == _MAX_IMAGE_PIXELS) minimal 1-symbol constant VP8L
            bw_16k = _BitWriter()
            bw_16k.write_lsb(0, 1); bw_16k.write_lsb(0, 1); bw_16k.write_lsb(0, 1)
            for _ in range(5):
                _write_vp8l_s1(bw_16k, 0)
            vp8l_16k_const_b = _mk_vp8l_webp(16384, 8192, bw_16k.finish())

            # 16384x8192 with use_cc=1 (cc_bits=4) + 1-symbol constant VP8L
            bw_16k_cc = _BitWriter()
            bw_16k_cc.write_lsb(0, 1); bw_16k_cc.write_lsb(1, 1); bw_16k_cc.write_lsb(4, 4); bw_16k_cc.write_lsb(0, 1)
            for sym_v in (0, 0, 0, 255, 0):
                _write_vp8l_s1(bw_16k_cc, sym_v)
            vp8l_16k_cc_const_b = _mk_vp8l_webp(16384, 8192, bw_16k_cc.finish())

            # 8192x8192 with use_meta=1, huffman_bits=2 (prefix_bits=4), constant meta_pixels selecting gid=1 (num_groups=2)
            bw_8k_meta = _BitWriter()
            bw_8k_meta.write_lsb(0, 1); bw_8k_meta.write_lsb(0, 1); bw_8k_meta.write_lsb(1, 1); bw_8k_meta.write_lsb(2, 3)
            bw_8k_meta.write_lsb(0, 1)  # meta no cc
            for sym_v in (1, 0, 0, 255, 0):
                _write_vp8l_s1(bw_8k_meta, sym_v)
            for sym_v in (0, 0, 0, 255, 0):  # group 0
                _write_vp8l_s1(bw_8k_meta, sym_v)
            for sym_v in (0, 0, 255, 255, 0):  # group 1
                _write_vp8l_s1(bw_8k_meta, sym_v)
            vp8l_8k_meta_const_b = _mk_vp8l_webp(8192, 8192, bw_8k_meta.finish())

            # 8192x8192 with use_meta=1, huffman_bits=0 (prefix_bits=2, 4.19M meta pixels), constant meta_pixels gid=0
            bw_8k_hb0 = _BitWriter()
            bw_8k_hb0.write_lsb(0, 1); bw_8k_hb0.write_lsb(0, 1); bw_8k_hb0.write_lsb(1, 1); bw_8k_hb0.write_lsb(0, 3)
            bw_8k_hb0.write_lsb(0, 1)
            for sym_v in (0, 0, 0, 255, 0):
                _write_vp8l_s1(bw_8k_hb0, sym_v)
            for sym_v in (0, 128, 0, 255, 0):
                _write_vp8l_s1(bw_8k_hb0, sym_v)
            vp8l_8k_meta_hbits0_const_b = _mk_vp8l_webp(8192, 8192, bw_8k_hb0.finish())

            # 64x64 valid multi-group control: meta_pixels 2x2 [0, 1, 0, 1], group 0 constant, group 1 non-constant (2-sym B)
            bw_64_mg = _BitWriter()
            bw_64_mg.write_lsb(0, 1); bw_64_mg.write_lsb(0, 1); bw_64_mg.write_lsb(1, 1); bw_64_mg.write_lsb(3, 3)
            bw_64_mg.write_lsb(0, 1)  # meta no cc
            _write_vp8l_s2(bw_64_mg, 0, 1)
            for sym_v in (0, 0, 255, 0):
                _write_vp8l_s1(bw_64_mg, sym_v)
            bw_64_mg.write_lsb(0, 1); bw_64_mg.write_lsb(1, 1); bw_64_mg.write_lsb(0, 1); bw_64_mg.write_lsb(1, 1)
            for sym_v in (0, 255, 0, 255, 0):  # group 0: constant red
                _write_vp8l_s1(bw_64_mg, sym_v)
            _write_vp8l_s1(bw_64_mg, 0)    # group 1 G
            _write_vp8l_s1(bw_64_mg, 0)    # group 1 R
            _write_vp8l_s2(bw_64_mg, 0, 255)  # group 1 B (1 bit/px)
            _write_vp8l_s1(bw_64_mg, 255)  # group 1 A
            _write_vp8l_s1(bw_64_mg, 0)    # group 1 Dist
            for px_i in range(2048):
                bw_64_mg.write_lsb(px_i & 1, 1)
            vp8l_64x64_multigroup_valid_b = _mk_vp8l_webp(64, 64, bw_64_mg.finish())

            # Negative control 1: 64x64 constant meta_pixels gid=2 (needs 3 groups) but stream only defines 2 groups
            bw_64_oob1 = _BitWriter()
            bw_64_oob1.write_lsb(0, 1); bw_64_oob1.write_lsb(0, 1); bw_64_oob1.write_lsb(1, 1); bw_64_oob1.write_lsb(3, 3)
            bw_64_oob1.write_lsb(0, 1)
            for sym_v in (2, 0, 0, 255, 0):
                _write_vp8l_s1(bw_64_oob1, sym_v)
            for _grp in range(2):
                for sym_v in (0, 0, 0, 255, 0):
                    _write_vp8l_s1(bw_64_oob1, sym_v)
            vp8l_64x64_meta_gid_oob_b = _mk_vp8l_webp(64, 64, bw_64_oob1.finish())

            # Negative control 2: 64x64 non-constant meta_pixels [0, 3, 0, 3] (needs 4 groups) but stream only defines 2 groups
            bw_64_oob2 = _BitWriter()
            bw_64_oob2.write_lsb(0, 1); bw_64_oob2.write_lsb(0, 1); bw_64_oob2.write_lsb(1, 1); bw_64_oob2.write_lsb(3, 3)
            bw_64_oob2.write_lsb(0, 1)
            _write_vp8l_s2(bw_64_oob2, 0, 3)
            for sym_v in (0, 0, 255, 0):
                _write_vp8l_s1(bw_64_oob2, sym_v)
            bw_64_oob2.write_lsb(0, 1); bw_64_oob2.write_lsb(1, 1); bw_64_oob2.write_lsb(0, 1); bw_64_oob2.write_lsb(1, 1)
            for _grp in range(2):
                for sym_v in (0, 0, 0, 255, 0):
                    _write_vp8l_s1(bw_64_oob2, sym_v)
            vp8l_64x64_meta_nonconst_gid_oob_b = _mk_vp8l_webp(64, 64, bw_64_oob2.finish())

            vp8l_const_cases = [
                {"id": "vp8l_16k_const", "b64": base64.b64encode(vp8l_16k_const_b).decode("ascii"), "check_native": False},
                {"id": "vp8l_16k_cc_const", "b64": base64.b64encode(vp8l_16k_cc_const_b).decode("ascii"), "check_native": False},
                {"id": "vp8l_8k_meta_const", "b64": base64.b64encode(vp8l_8k_meta_const_b).decode("ascii"), "check_native": True},
                {"id": "vp8l_8k_meta_hbits0_const", "b64": base64.b64encode(vp8l_8k_meta_hbits0_const_b).decode("ascii"), "check_native": False},
                {"id": "vp8l_64x64_multigroup_valid", "b64": base64.b64encode(vp8l_64x64_multigroup_valid_b).decode("ascii"), "check_native": True},
                {"id": "vp8l_64x64_meta_gid_oob", "b64": base64.b64encode(vp8l_64x64_meta_gid_oob_b).decode("ascii"), "check_native": False},
                {"id": "vp8l_64x64_meta_nonconst_gid_oob", "b64": base64.b64encode(vp8l_64x64_meta_nonconst_gid_oob_b).decode("ascii"), "check_native": False},
            ]

            # Standalone actor key collision cases (NeDB _idx_0 collision & LevelDB duplicate _id with import_scenes=false)
            d_nedb_anon_col = fdir / "nedb_anon_col"
            build_v9_world(
                d_nedb_anon_col,
                world_json=make_v9_world_json(name="nac", title="NedbAnonCol"),
                scenes=[],
                actors=[],
            )
            (d_nedb_anon_col / "assets").mkdir(parents=True, exist_ok=True)
            (d_nedb_anon_col / "assets" / "a0.png").write_bytes(png)
            (d_nedb_anon_col / "assets" / "a1.png").write_bytes(png_pre)
            (d_nedb_anon_col / "assets" / "a2.png").write_bytes(png_new)
            (d_nedb_anon_col / "data" / "actors.db").write_text(
                "\n".join([
                    json.dumps({"name": "AnonZero", "type": "npc", "img": "worlds/nac/assets/a0.png"}),
                    json.dumps({"_id": "_idx_0", "name": "ExplicitIdx0", "type": "npc", "img": "worlds/nac/assets/a1.png"}),
                    json.dumps({"_id": "_idx_0_1", "name": "SuffixCollision", "type": "character", "img": "worlds/nac/assets/a2.png"}),
                ]) + "\n",
                encoding="utf-8",
            )

            d_ldb_dup = fdir / "ldb_dup_id"
            build_v14_world(
                d_ldb_dup,
                world_json=make_v14_world_json(world_id="ldup", title="LdbDupId"),
                scenes=[make_v9_scene("s1", "IgnoredScene")],
                actors=[],
            )
            (d_ldb_dup / "assets").mkdir(parents=True, exist_ok=True)
            (d_ldb_dup / "assets" / "l0.png").write_bytes(png)
            (d_ldb_dup / "assets" / "l1.png").write_bytes(png_pre)
            dup_a0 = make_v9_actor("same_id", "LdbActorA", img="worlds/ldup/assets/l0.png")
            dup_a1 = make_v9_actor("same_id", "LdbActorB", img="worlds/ldup/assets/l1.png")
            sst_dup, dup_min, dup_max = build_sstable_bytes([
                (b"!actors!k1", 10, 1, json.dumps(dup_a0).encode("utf-8")),
                (b"!actors!k2", 11, 1, json.dumps(dup_a1).encode("utf-8")),
            ])
            (d_ldb_dup / "data" / "actors" / "000005.ldb").write_bytes(sst_dup)
            (d_ldb_dup / "data" / "actors" / "MANIFEST-000001").write_bytes(
                build_manifest_bytes(ldb_files=[(5, len(sst_dup), dup_min, dup_max)], log_number=6, next_file_number=7, last_sequence=11)
            )

            actor_dup_cases = [
                {"id": "nedb_anon_collision", "path": str(d_nedb_anon_col / "world.json"), "opts": {"skip_missing_assets": False}},
                {"id": "ldb_dup_id", "path": str(d_ldb_dup / "world.json"), "opts": {"import_scenes": False, "skip_missing_assets": False}},
            ]

            cfg_p = cls.run_dir / "cfg.json"
            out_p = cls.run_dir / "out.json"
            write_json_file(cfg_p, {
                "entry_gd": MOD_ENTRY_GD,
                "src_dir": SRC_DIR,
                "sdk_gd": SDK_GD,
                "run_dir": str(cls.run_dir),
                "entry_cases": entry_cases,
                "rfc_zip": str(z_rfc),
                "snappy_vectors": snappy_vecs,
                "ext_world": str(d_ext / "world.json"),
                "png_path": str(png_p),
                "pre_png": str(pre_png_p),
                "new_scene_png": str(new_png_p),
                "bmp_nomask": str(bmp_nomask_p),
                "bmp_mask": str(bmp_mask_p),
                "bmp_v4": str(bmp_v4_p),
                "bmp_v5": str(bmp_v5_p),
                "rb_world": str(d_rb / "world.json"),
                "simple_wj": str(d_simple / "world.json"),
                "svg_vectors": svg_vecs,
                "resolve_vectors": resolve_vectors,
                "img_bad_vectors": img_bad_vectors,
                "webp_tail_vectors": [{"id": v["id"], "b64": v["b64"]} for v in oracle_vecs],
                "vp8l_const_cases": vp8l_const_cases,
                "actor_dup_cases": actor_dup_cases,
                "z_nonascii_0b": str(z_nonascii_0b),
                "d_rem_evil": str(d_rem_evil / "world.json"),
                "d_post_cancel": str(d_post_cancel / "world.json"),
                "bgdia_images": bgdia_images,
                "r17_grid_cases": r17_grid_cases,
                "r17_source_cases": r17_source_cases,
                "r17_ldb_cases": r17_ldb_cases,
                "r17_emb_levels_wj": str(d_emb_lvl / "world.json"),
                "webp_noshow_asset_path": str(webp_noshow_asset_p),
                "webp_noshow_wj": str(d_webp_noshow / "world.json"),
            })
            log_p = cls.run_dir / "godot.log"
            proc = subprocess.run(
                [str(cfg.godot_bin), "--headless", "--quit", "--path", str(probe_dir), "--log-file", str(log_p), "--script", "res://probe.gd", "--", f"--cfg={cfg_p}", f"--out={out_p}"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=240,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            log_txt = log_p.read_text(encoding="utf-8", errors="replace") if log_p.is_file() else ""
            errs = analyze_godot_logs(log_txt, proc.stdout, proc.stderr)
            if proc.returncode != 0 or errs:
                raise AssertionError(f"Godot rc={proc.returncode} errs={errs}\nLOG:\n{log_txt[-2000:]}")
            cls.results = json.loads(out_p.read_text(encoding="utf-8"))
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        rd = getattr(cls, "run_dir", None)
        if rd is not None and rd.exists():
            j_link = rd / "fixtures" / "junction_world" / "assets" / "loop"
            if j_link.exists() or j_link.is_symlink():
                try:
                    os.rmdir(j_link) if (os.name == "nt" and not j_link.is_symlink()) else j_link.unlink()
                except OSError:
                    pass
            for _ in range(5):
                shutil.rmtree(rd, ignore_errors=True)
                if not rd.exists():
                    break
                time.sleep(0.05)

    def test_error_propagation_intact_zip_and_leveldb_snappy(self) -> None:
        ec = self.results["entry_cases"]
        self.assertFalse(ec["zip_wj_bad_crc"]["ins_ok"])
        self.assertIn("zip_crc32_mismatch", ec["zip_wj_bad_crc"]["ins_reason"])
        self.assertFalse(ec["zip_db_bad_deflate"]["ins_ok"])
        self.assertIn("zip_deflate_", ec["zip_db_bad_deflate"]["ins_reason"])
        self.assertFalse(ec["zip_ldb_bad_crc"]["ins_ok"])
        self.assertIn("zip_crc32_mismatch", ec["zip_ldb_bad_crc"]["ins_reason"])
        self.assertFalse(ec["zip_wal_bad_deflate"]["ins_ok"])
        self.assertIn("zip_deflate_", ec["zip_wal_bad_deflate"]["ins_reason"])
        self.assertFalse(ec["dir_ldb_bad_snappy"]["ins_ok"])
        self.assertIn("snappy_", ec["dir_ldb_bad_snappy"]["ins_reason"])
        self.assertFalse(ec["dir_ldb_bad_snappy"]["prep_ok"])
        self.assertFalse(ec["dir_ldb_bad_block"]["ins_ok"])
        self.assertIn("block_", ec["dir_ldb_bad_block"]["ins_reason"])
        self.assertFalse(ec["dir_v10_ldb_bad_snappy"]["ins_ok"])
        self.assertIn("snappy_", ec["dir_v10_ldb_bad_snappy"]["ins_reason"])
        self.assertFalse(ec["zip_bad_img_strict"]["prep_ok"])
        self.assertIn("zip_crc32_mismatch", ec["zip_bad_img_strict"]["prep_reason"])
        self.assertFalse(ec["zip_bad_img_skip"]["prep_ok"])
        self.assertIn("zip_crc32_mismatch", ec["zip_bad_img_skip"]["prep_reason"])

    def test_zip_structural_and_rfc1951_edge_cases(self) -> None:
        ec = self.results["entry_cases"]
        self.assertTrue(ec["zip_dup_cd"]["ins_ok"])
        self.assertEqual(ec["zip_dup_cd"]["ins_decoded_bytes"], self.dup_expected_bytes)
        self.assertTrue(ec["zip_data_desc"]["prep_ok"])
        self.assertTrue(ec["zip_extra_diff"]["prep_ok"])
        self.assertFalse(ec["zip64"]["ins_ok"])
        self.assertIn("zip64_unsupported", ec["zip64"]["ins_reason"])
        self.assertFalse(ec["zip_encrypted"]["ins_ok"])
        self.assertIn("zip_encrypted_unsupported", ec["zip_encrypted"]["ins_reason"])
        self.assertFalse(ec["zip_bad_method"]["ins_ok"])
        self.assertIn("zip_unsupported_method", ec["zip_bad_method"]["ins_reason"])
        self.assertFalse(ec["zip_ratio_bomb"]["ins_ok"])
        self.assertIn("zip_suspicious_ratio", ec["zip_ratio_bomb"]["ins_reason"])

        self.assertTrue(self.results["rfc_open_ok"])
        for fn, exp_sha in self.rfc_shas.items():
            self.assertEqual(self.results["rfc_entries"][fn]["err"], "")
            self.assertEqual(self.results["rfc_entries"][fn]["sha256"], exp_sha)

    def test_leveldb_multiblock_seq_collision_and_snappy_edges(self) -> None:
        ec = self.results["entry_cases"]
        self.assertTrue(ec["ldb_multiblock_snappy"]["prep_ok"])
        self.assertEqual(ec["ldb_multiblock_snappy"]["floors"], 40)
        self.assertTrue(ec["ldb_seq_collision"]["ins_ok"])
        self.assertEqual(ec["ldb_seq_collision"]["ins_counts"]["maps"], 1)

        sn = self.results["snappy_edges"]
        self.assertTrue(sn["zero_len"]["ok"])
        self.assertFalse(sn["trailing_zero"]["ok"])
        self.assertFalse(sn["varint_ovf"]["ok"])
        self.assertFalse(sn["trunc_copy1"]["ok"])
        self.assertFalse(sn["trunc_copy2"]["ok"])
        self.assertFalse(sn["trunc_copy4"]["ok"])

    def test_normalizer_extreme_coords_ac_html_and_folders(self) -> None:
        ns = self.results["norm_scenes"]["ext"]
        self.assertTrue(ns["scene_x_finite"])
        self.assertTrue(ns["scene_y_finite"])
        self.assertGreaterEqual(ns["grid_size"], 0.0)

        ext = self.results["entry_cases"]["norm_ext"]
        self.assertTrue(ext["prep_ok"])
        self.assertEqual(ext["ins_counts"]["walls"], 1)
        self.assertEqual(ext["wall_count"], 1)
        self.assertTrue(any("非有限" in w for w in ext["warnings"]))
        actors = {a["name"]: a for a in ext["actors"]}
        self.assertEqual(actors["ClumsyKnight"]["ac"], 18)
        self.assertEqual(actors["ClumsyKnight"]["folder_name"], "CycB/CycA")
        self.assertEqual(actors["ClumsyKnight"]["biography"], "Roll < 10 misses. Keep this < 5 forever")
        self.assertEqual(actors["DualArmor"]["ac"], 16)
        self.assertEqual(actors["DualArmor"]["biography"], "Bio & <text>")
        self.assertEqual(actors["DeepActor"]["folder_name"], "/".join(f"D{i}" for i in range(60)))

    def test_mapper_direct_null_nan_inf_and_huge_wall(self) -> None:
        mn = self.results["mapper_null_nan"]
        self.assertTrue(mn["ok"])
        self.assertEqual(mn["source_records"], 0)
        self.assertTrue(mn["all_finite"])
        self.assertEqual(mn["v3_errs"], [])
        self.assertEqual(mn["wall_count"], 1)
        self.assertTrue(any("非有限" in w or "溢出" in w or "退化" in w for w in mn["warnings"]))

    def test_mapper_entity_library_failure_paths_and_cancel_rollback(self) -> None:
        el = self.results["entity_lib"]
        for mode in ["open_fail", "read_non_dict", "read_err_dict", "write_folder_fail", "write_unit_fail", "adopt_fail", "share_fail"]:
            self.assertTrue(el[mode]["ok"], msg=f"mode={mode} res={el[mode]}")
            self.assertTrue(len(el[mode]["warnings"]) >= 1, msg=f"mode={mode} missing warning")
        self.assertEqual(el["adopt_fail"]["unit_refs"], ["", ""])
        self.assertTrue(all(str(r).startswith("asset://") for r in el["share_fail"]["unit_refs"]))
        self.assertFalse(el["cancel_mid_loop"]["ok"])
        self.assertEqual(el["cancel_mid_loop"]["reason"], "cancelled")
        self.assertEqual(el["cancel_mid_loop"]["records_count"], 0)
        self.assertTrue(el["post_map_rollback"]["ok"])
        self.assertGreater(el["post_map_rollback"]["before"], 0)
        self.assertEqual(el["post_map_rollback"]["after"], 0)

    def test_mapper_gridless_only_ga_and_module_full_omission(self) -> None:
        go = self.results["gridless_omission"]
        self.assertTrue(go["ok"])
        self.assertEqual(go["v3_errs"], [])
        self.assertEqual(len(set(go["floor_uids"])), 2)
        self.assertFalse(go["snap_enabled"])
        self.assertFalse(go["has_importer_module"])
        self.assertTrue(any("省略可选 fvtt_world_importer 档案模块" in w for w in go["warnings"]))

    def test_assets_zip_corrupt_crc_bmp_bitfields_and_publish_rollback(self) -> None:
        aa = self.results["assets_adv"]
        self.assertFalse(aa["bmp_nomask"]["ok"])
        self.assertEqual(aa["bmp_nomask"]["reason"], "missing_bmp_bitfields")
        self.assertTrue(aa["bmp_mask"]["ok"])
        self.assertTrue(aa["bmp_v4"]["ok"])
        self.assertTrue(aa["bmp_v5"]["ok"])
        self.assertFalse(aa["publish_disk_full"]["ok"])
        self.assertEqual(aa["publish_disk_full"]["reason"], "shared_asset_publish_failed:disk_full")
        self.assertFalse(aa["unsafe_strict"]["ok"])
        self.assertEqual(aa["unsafe_strict"]["reason"], "unsafe_asset_ref:user://secret.png")
        self.assertFalse(aa["rb_prep_ok"])
        self.assertIn("missing_asset:", aa["rb_prep_reason"])
        pub_by_ref = {c["ref"]: c for c in aa["rb_publish_calls"]}
        self.assertEqual(len(aa["rb_publish_calls"]), 2)
        self.assertTrue(pub_by_ref[aa["rb_pre_ref"]]["reused"])
        self.assertFalse(pub_by_ref[aa["rb_new_ref"]]["reused"])
        self.assertTrue(aa["new_existed_before"])
        self.assertTrue(aa["pre_exact_existed_before"])
        self.assertTrue(aa["pre_other_existed_before"])
        self.assertFalse(aa["new_file_exists_after_fail"])
        self.assertTrue(aa["pre_exact_exists"])
        self.assertTrue(aa["pre_other_exists"])

    def test_assets_svg_unquoted_selfclose_and_pi_variants(self) -> None:
        sa = self.results["svg_adv"]
        self.assertFalse(sa["unquoted_root"]["ok"])
        self.assertIn(sa["unquoted_root"]["reason"], ("malformed_svg_xml", "invalid_svg_dimensions"))
        self.assertFalse(sa["vb_nan"]["ok"])
        self.assertEqual(sa["vb_nan"]["reason"], "invalid_svg_dimensions")
        self.assertTrue(sa["self_close"]["ok"])
        self.assertTrue(sa["pct_vb_comma"]["ok"])
        self.assertTrue(sa["pi_comment_ns"]["ok"])
        self.assertTrue(sa["unquoted_child"]["ok"])
        self.assertTrue(sa["unquoted_ns_child"]["ok"])

    def test_entry_hard_snappy_error_and_null_host(self) -> None:
        ec = self.results["entry_cases"]
        self.assertFalse(ec["dir_ldb_bad_snappy"]["ins_ok"])
        self.assertIn(":snappy_", ec["dir_ldb_bad_snappy"]["ins_reason"])
        self.assertFalse(ec["dir_ldb_bad_snappy"]["prep_ok"])
        self.assertIn(":snappy_", ec["dir_ldb_bad_snappy"]["prep_reason"])
        nh = self.results["null_host"]
        self.assertTrue(nh["ins"]["ok"])
        self.assertEqual(nh["ins"]["assets"], {})
        self.assertFalse(nh["prep"]["ok"])
        self.assertEqual(nh["prep"]["reason"], "host_empty_world_unavailable")

    def test_folders_snappy_gbk_bslash_and_prev_log(self) -> None:
        ec = self.results["entry_cases"]
        fsn = ec["d_folders_snappy"]
        self.assertFalse(fsn["ins_ok"])
        self.assertIn("data/folders/000005.ldb:snappy_", fsn["ins_reason"])
        self.assertFalse(fsn["prep_ok"])
        self.assertIn("data/folders/000005.ldb:snappy_", fsn["prep_reason"])

        gbk = ec["z_gbk"]
        self.assertTrue(gbk["ins_ok"])
        self.assertTrue(gbk["prep_ok"])

        bs = ec["z_bslash"]
        self.assertTrue(bs["ins_ok"])
        self.assertTrue(bs["prep_ok"])
        self.assertEqual(bs["ins_counts"]["images"], 1)
        self.assertEqual(bs["ins_counts"]["selected_images"], 1)
        self.assertEqual(bs["floors"], 1)

        pl = ec["d_prev_log"]
        self.assertTrue(pl["ins_ok"])
        self.assertTrue(pl["prep_ok"])
        self.assertEqual(pl["floors"], 3)
        self.assertEqual(sorted(pl["floor_names"]), ["AliveAt10", "CurrLog", "PrevLog"])

    def test_resolve_asset_ref_percent_nul_traversal_and_schemes(self) -> None:
        ra = self.results["resolve_adv"]
        for vec in (
            "%75%73%65%72%3a%2f%2fsecret.png",
            "worlds/t5/%2e%2e/secret.png",
            "assets/%FF%FE.png",
            "assets/a%00b.png",
            "javascript:alert(1)",
        ):
            self.assertEqual(ra[vec]["kind"], "unsafe", msg=f"vec={vec} got={ra[vec]}")
            self.assertTrue(ra[vec]["unsafe"], msg=f"vec={vec} got={ra[vec]}")
            self.assertFalse(ra[vec]["exists"], msg=f"vec={vec} got={ra[vec]}")

    def test_image_header_and_chunk_prevalidation_zero_godot_errors(self) -> None:
        ia = self.results["img_bad_adv"]
        self.assertFalse(ia["png_fdict"]["ok"])
        self.assertEqual(ia["png_fdict"]["reason"], "invalid_png_zlib_header")
        self.assertFalse(ia["png_plte_after_idat"]["ok"])
        self.assertEqual(ia["png_plte_after_idat"]["reason"], "invalid_png_plte_order")
        self.assertFalse(ia["png_noncontig_idat"]["ok"])
        self.assertEqual(ia["png_noncontig_idat"]["reason"], "invalid_png_idat_order")
        self.assertTrue(ia["png_contig_split"]["ok"])
        self.assertFalse(ia["png_dup_ihdr"]["ok"])
        self.assertEqual(ia["png_dup_ihdr"]["reason"], "duplicate_png_ihdr")
        self.assertFalse(ia["jpg_12bit"]["ok"])
        self.assertTrue(ia["jpg_12bit"]["unsupported"])
        self.assertEqual(ia["jpg_12bit"]["reason"], "unsupported_jpg_precision")
        self.assertFalse(ia["jpg_sof3"]["ok"])
        self.assertTrue(ia["jpg_sof3"]["unsupported"])
        self.assertEqual(ia["jpg_sof3"]["reason"], "unsupported_jpg_sof")
        self.assertFalse(ia["jpg_dup_soi"]["ok"])
        self.assertEqual(ia["jpg_dup_soi"]["reason"], "invalid_jpg_marker")
        self.assertFalse(ia["jpg_dup_sof0"]["ok"])
        self.assertEqual(ia["jpg_dup_sof0"]["reason"], "duplicate_jpg_sof")
        self.assertFalse(ia["jpg_hv_zero"]["ok"])
        self.assertEqual(ia["jpg_hv_zero"]["reason"], "invalid_jpg_sof")
        self.assertFalse(ia["jpg_sos_more_comp_than_sof"]["ok"])
        self.assertEqual(ia["jpg_sos_more_comp_than_sof"]["reason"], "invalid_jpg_sos")
        self.assertFalse(ia["jpg_sof2_bad_2nd_sos_ncomp"]["ok"])
        self.assertEqual(ia["jpg_sof2_bad_2nd_sos_ncomp"]["reason"], "invalid_jpg_sos")
        self.assertFalse(ia["jpg_sof2_bad_2nd_sos_len"]["ok"])
        self.assertEqual(ia["jpg_sof2_bad_2nd_sos_len"]["reason"], "invalid_jpg_sos")
        self.assertFalse(ia["jpg_sof2_dup_sof_between_scans"]["ok"])
        self.assertEqual(ia["jpg_sof2_dup_sof_between_scans"]["reason"], "duplicate_jpg_sof")
        self.assertFalse(ia["jpg_sof2_dup_soi_between_scans"]["ok"])
        self.assertEqual(ia["jpg_sof2_dup_soi_between_scans"]["reason"], "invalid_jpg_marker")
        self.assertFalse(ia["jpg_tq_out_of_range"]["ok"])
        self.assertEqual(ia["jpg_tq_out_of_range"]["reason"], "invalid_jpg_sof")
        for k_sof in (
            "jpg_sof0_h_3_2_1_inter",
            "jpg_sof0_h_3_2_1_noninter",
            "jpg_sof0_v_4_3_1",
            "jpg_sof2_h_3_2_1_noninter",
        ):
            self.assertFalse(ia[k_sof]["ok"], msg=k_sof)
            self.assertFalse(ia[k_sof]["unsupported"], msg=k_sof)
            self.assertEqual(ia[k_sof]["reason"], "invalid_jpg_sof", msg=k_sof)
        self.assertFalse(ia["jpg_mcu_sum_11_interleaved"]["ok"])
        self.assertEqual(ia["jpg_mcu_sum_11_interleaved"]["reason"], "invalid_jpg_sos")
        self.assertFalse(ia["jpg_sos_unknown_cs"]["ok"])
        self.assertEqual(ia["jpg_sos_unknown_cs"]["reason"], "invalid_jpg_sos")
        self.assertFalse(ia["jpg_sos_dup_cs"]["ok"])
        self.assertEqual(ia["jpg_sos_dup_cs"]["reason"], "invalid_jpg_sos")
        self.assertTrue(ia["jpg_valid_sof2_progressive"]["ok"])
        self.assertTrue(ia["jpg_valid_mcu_48_noninterleaved"]["ok"])
        self.assertTrue(ia["jpg_with_app1_thumb_markers"]["ok"])
        for k_dht in (
            "jpg_dht_bad_tc",
            "jpg_dht_bad_th",
            "jpg_dht_bad_len",
            "jpg_dht_sum_gt_256",
            "jpg_dht_mid_bad_len",
            "jpg_dht_kraft_65536",
            "jpg_dht_kraft_oversub",
            "jpg_dc_sym_16",
            "jpg_sof2_interscan_dc_sym16",
        ):
            self.assertFalse(ia[k_dht]["ok"], msg=k_dht)
            self.assertEqual(ia[k_dht]["reason"], "invalid_jpg_dht", msg=k_dht)
        for k_cs in (
            "jpg_4comp_cmyk",
            "jpg_app14_3comp_t2",
            "jpg_app14_after_sof_t2",
        ):
            self.assertFalse(ia[k_cs]["ok"], msg=k_cs)
            self.assertTrue(ia[k_cs]["unsupported"], msg=k_cs)
            self.assertEqual(ia[k_cs]["reason"], "unsupported_jpg_colorspace", msg=k_cs)
        self.assertFalse(ia["jpg_sof0_tq1_undef"]["ok"])
        self.assertEqual(ia["jpg_sof0_tq1_undef"]["reason"], "missing_jpg_dqt")
        self.assertFalse(ia["jpg_dqt_mid_bad_len"]["ok"])
        self.assertEqual(ia["jpg_dqt_mid_bad_len"]["reason"], "invalid_jpg_dqt")
        for k_dri in ("jpg_dri_bad_len_2", "jpg_dri_bad_len_6", "jpg_dri_mid_bad_len"):
            self.assertFalse(ia[k_dri]["ok"], msg=k_dri)
            self.assertEqual(ia[k_dri]["reason"], "invalid_jpg_dri", msg=k_dri)
        for k_sos in (
            "jpg_sos_bad_td_ta",
            "jpg_sof2_ss_gt_se",
            "jpg_sof2_se_64",
            "jpg_sof2_ss0_se63",
            "jpg_sof2_ac_multi",
            "jpg_sof2_ah14",
            "jpg_sof2_refinement_al_diff",
            "jpg_sof2_ac_ah1_al2_bad",
            "jpg_sof2_undef_dc_td",
            "jpg_sof2_undef_ac_ta",
            "jpg_sof2_refine_undef_ta",
            "jpg_sof0_1comp_two_sos",
            "jpg_sof1_1comp_two_sos",
            "jpg_sof0_undef_td2",
            "jpg_sof0_undef_ta2",
            "jpg_sof1_undef_td3",
            "jpg_sof0_3_sos_3_2_1",
            "jpg_sof0_3_sos_1_3_2",
            "jpg_sof2_3_sos_3_2_1",
            "jpg_sof0_3_rev_sof_sos_1_2_3",
            "jpg_sof0_dup_cid_44_11",
            "jpg_sof2_dup_cid_44_11",
        ):
            self.assertFalse(ia[k_sos]["ok"], msg=k_sos)
            self.assertFalse(ia[k_sos]["unsupported"], msg=k_sos)
            self.assertEqual(ia[k_sos]["reason"], "invalid_jpg_sos", msg=k_sos)
        for k_unsup in (
            "jpg_marker_c8_before",
            "jpg_marker_c8_mid",
            "jpg_marker_de_dhp",
            "jpg_marker_df_exp",
            "jpg_marker_cc_dac",
        ):
            self.assertFalse(ia[k_unsup]["ok"], msg=k_unsup)
            self.assertTrue(ia[k_unsup]["unsupported"], msg=k_unsup)
            self.assertEqual(ia[k_unsup]["reason"], "unsupported_jpg_marker", msg=k_unsup)
        for k_invm in (
            "jpg_marker_02_before",
            "jpg_marker_02_in_entropy",
            "jpg_marker_f0_before",
        ):
            self.assertFalse(ia[k_invm]["ok"], msg=k_invm)
            self.assertFalse(ia[k_invm]["unsupported"], msg=k_invm)
            self.assertEqual(ia[k_invm]["reason"], "invalid_jpg_marker", msg=k_invm)
        for k_ok in (
            "jpg_valid_ff_pad",
            "jpg_valid_dht_multi",
            "jpg_valid_dri_4",
            "jpg_valid_sof0_th2_td2",
            "jpg_valid_sof2_refinement",
            "jpg_valid_dnl_marker",
            "jpg_valid_tq1_after_sof",
            "jpg_valid_dht_kraft_65535",
            "jpg_valid_sof2_dc_undef_ta",
            "jpg_valid_sof2_ac_undef_td",
            "jpg_valid_sof2_dc_refine_undef_td",
            "jpg_valid_dc_sym_15",
            "jpg_valid_ac_sym_ff",
            "jpg_valid_app14_3comp_t0",
            "jpg_valid_app14_3comp_t1",
            "jpg_valid_sof0_3_2_plus_1_scans",
            "jpg_valid_sof2_interscan_dht",
            "jpg_valid_sof0_def_dc2_td2_ta0",
            "jpg_valid_sof0_interscan_dht2",
            "jpg_valid_sof0_3_sos_1_3_then_2",
            "jpg_valid_sof0_3_rev_sof_sos_3_2_1",
            "jpg_valid_sof0_3_2nd_scan_3_then_1",
            "jpg_valid_sof0_h_4_2_1",
            "jpg_valid_sof0_h_3_1_1",
            "jpg_valid_sof0_hv_31_12_11",
            "jpg_valid_sof0_dup_cid_11_44",
        ):
            self.assertTrue(ia[k_ok]["ok"], msg=f"{k_ok}: {ia[k_ok]}")
        self.assertFalse(ia["webp_vp8x_mismatch"]["ok"])
        self.assertEqual(ia["webp_vp8x_mismatch"]["reason"], "invalid_webp_dimensions_mismatch")
        self.assertFalse(ia["webp_vp8x_oversized"]["ok"])
        self.assertEqual(ia["webp_vp8x_oversized"]["reason"], "image_dimensions_out_of_bounds")

    def test_t5_png_webp_bmp_jpeg_svg_hardening_and_positive_controls(self) -> None:
        ia = self.results["img_bad_adv"]
        # PNG IDAT / Adam7 / PLTE
        for k_png_bad in (
            "png_corrupt_deflate",
            "png_trunc_scanlines",
            "png_bad_filter_byte",
            "png_bad_adler32",
            "png_huge_decompress_trunc",
            "png_interlaced_trunc",
            "png_gray_with_plte",
            "png_gray_alpha_with_plte",
            "png_1bit_plte_oversized",
        ):
            self.assertFalse(ia[k_png_bad]["ok"], msg=f"{k_png_bad}: {ia[k_png_bad]}")
            self.assertNotEqual(ia[k_png_bad]["reason"], "image_decode_failed:png", msg=k_png_bad)
        self.assertTrue(ia["png_valid_adam7"]["ok"], msg=ia["png_valid_adam7"])
        self.assertTrue(ia["png_valid_stored_zlib"]["ok"], msg=ia["png_valid_stored_zlib"])
        self.assertTrue(ia["png_plte_oob_idx"]["ok"], msg=ia["png_plte_oob_idx"])
        self.assertTrue(ia["png_trns_gt_plte"]["ok"], msg=ia["png_trns_gt_plte"])

        # WebP container & bitstream + multi-tile VP8L & Pcat VP8 positive controls
        for k_webp_bad in (
            "webp_vp8_trunc_payload",
            "webp_vp8_bad_part0",
            "webp_vp8l_trunc_payload",
            "webp_vp8l_bad_version",
            "webp_vp8x_odd_len",
            "webp_alph_empty",
            "webp_alph_bad_method",
            "webp_dual_vp8",
            "webp_vp8x_alpha_no_alph",
            "webp_alph_no_vp8x",
            "webp_vp8x_noflag_plus_alph",
            "webp_vp8x_after_vp8",
            "webp_real_lossless_bad_end",
            "webp_alph_rsv_bits",
            "webp_alph_corrupt_vp8l",
            "webp_vp8_colorspace_bit",
            "webp_vp8_trunc_dct",
            "webp_vp8_only_part0_no_dct",
            "webp_vp8_trunc_nonfinal_mb",
        ):
            self.assertFalse(ia[k_webp_bad]["ok"], msg=f"{k_webp_bad}: {ia[k_webp_bad]}")
            self.assertNotEqual(ia[k_webp_bad]["reason"], "image_decode_failed:webp", msg=k_webp_bad)
        self.assertEqual(ia["webp_vp8_trunc_nonfinal_mb"]["reason"], "truncated_webp_vp8")
        if not ia["webp_vp8_flip_mid_dct"]["ok"]:
            self.assertNotEqual(ia["webp_vp8_flip_mid_dct"]["reason"], "image_decode_failed:webp")
        for trim_i in range(1, 5):
            for p_lbl in ("rgb", "pcat"):
                tk = f"webp_tail_{p_lbl}_{trim_i}"
                if not ia[tk]["ok"]:
                    self.assertEqual(ia[tk]["reason"], "truncated_webp_vp8", msg=f"{tk}: {ia[tk]}")
        self.assertFalse(ia["webp_tail_rgb_4"]["ok"])
        self.assertFalse(ia["webp_tail_pcat_4"]["ok"])
        for k_webp_ok in (
            "webp_valid_lossless_complex",
            "webp_valid_lossy_alpha",
            "webp_valid_lossy_rgb",
            "webp_valid_vp8l_multitile",
            "webp_valid_vp8_pcat",
            "webp_valid_vp8x_alpha_vp8l",
            "webp_valid_vp8_bpred_multipart",
            "webp_valid_vp8x_alpha_vp8_tail",
        ):
            self.assertTrue(ia[k_webp_ok]["ok"], msg=f"{k_webp_ok}: {ia[k_webp_ok]}")

        # BMP bfSize, bitfields zero masks, 16-bit BI_RGB, 24-bit colors_used, combined top-down + short palette
        for k_bmp_bad in ("bmp_bfsize_0", "bmp_bfsize_69"):
            self.assertFalse(ia[k_bmp_bad]["ok"], msg=f"{k_bmp_bad}: {ia[k_bmp_bad]}")
            self.assertEqual(ia[k_bmp_bad]["reason"], "invalid_bmp_file_size", msg=k_bmp_bad)
        for k_bmp_ok in (
            "bmp_bfsize_70",
            "bmp_bfsize_999",
            "bmp_bf_zero_d40",
            "bmp_bf_zero_d108",
            "bmp_bf_zero_d124",
            "bmp_16bit_bi_rgb",
            "bmp_24bit_colors_used_999999",
            "bmp_8bit_topdown_short_pal",
            "bmp_1bit_topdown_short_pal",
            "bmp_4bit_topdown_short_pal",
        ):
            self.assertTrue(ia[k_bmp_ok]["ok"], msg=f"{k_bmp_ok}: {ia[k_bmp_ok]}")

        # JPEG APP0 JFIF version
        for k_app0_bad in ("jpg_app0_v2", "jpg_app0_v0"):
            self.assertFalse(ia[k_app0_bad]["ok"], msg=f"{k_app0_bad}: {ia[k_app0_bad]}")
            self.assertEqual(ia[k_app0_bad]["reason"], "unsupported_jpg_jfif_version", msg=k_app0_bad)
        self.assertTrue(ia["jpg_app0_v1_ok"]["ok"], msg=ia["jpg_app0_v1_ok"])

        # SVG <use>, CSS units, viewBox whitespace, subpixel, extreme viewBox
        self.assertFalse(ia["svg_mutual_use_cycle"]["ok"])
        self.assertEqual(ia["svg_mutual_use_cycle"]["reason"], "svg_use_cycle")
        self.assertFalse(ia["svg_xlink_use_cycle"]["ok"])
        self.assertEqual(ia["svg_xlink_use_cycle"]["reason"], "svg_use_cycle")
        self.assertFalse(ia["svg_billion_use"]["ok"])
        self.assertEqual(ia["svg_billion_use"]["reason"], "svg_use_limit_exceeded")
        self.assertFalse(ia["svg_unit_pct_bad"]["ok"])
        self.assertEqual(ia["svg_unit_pct_bad"]["reason"], "invalid_svg_dimensions")
        self.assertFalse(ia["svg_unit_em_bad"]["ok"])
        self.assertEqual(ia["svg_unit_em_bad"]["reason"], "invalid_svg_dimensions")
        for k_svg_ok in (
            "svg_valid_use",
            "svg_unit_pt",
            "svg_unit_pc",
            "svg_unit_in",
            "svg_unit_cm",
            "svg_unit_mm",
            "svg_unit_q",
            "svg_vb_whitespace",
            "svg_subpixel_0_1",
            "svg_extreme_vb_100000",
        ):
            self.assertTrue(ia[k_svg_ok]["ok"], msg=f"{k_svg_ok}: {ia[k_svg_ok]}")

        # MIME/extension mismatch
        self.assertTrue(ia["mime_png_as_jpg"]["ok"], msg=ia["mime_png_as_jpg"])
        self.assertTrue(str(ia["mime_png_as_jpg"]["sprite_path"]).endswith(".png"), msg=ia["mime_png_as_jpg"])

    def test_t5_bgdia_image_sweep_zero_false_positives(self) -> None:
        if not self.has_bgdia_dir:
            self.skipTest("Unpacked bgdia world.json not found in environment")
        bg = self.results["bgdia_sweep"]
        non_gif_fails = [f for f in bg["fails"] if not str(f["path"]).lower().endswith(".gif")]
        gif_fails = [f for f in bg["fails"] if str(f["path"]).lower().endswith(".gif")]
        self.assertEqual(non_gif_fails, [], msg=f"bgdia false-positive rejections: {non_gif_fails[:10]}")
        for gf in gif_fails:
            self.assertEqual(gf["reason"], "unsupported_image_format:gif", msg=gf)
        self.assertEqual(bg["ok"] + len(gif_fails), bg["total"])
        self.assertGreaterEqual(bg["total"], 2167)
        self.assertGreaterEqual(bg["ok"], 2166)

    def test_t5_webp_vp8_tail_trim_libwebp_parity(self) -> None:
        parity = self.results["webp_tail_parity"]
        self.assertGreaterEqual(len(self.webp_tail_oracle), 35)
        seen_pass = 0
        seen_fail = 0
        w48_errs: dict[int, int] = {}
        for vid, meta in self.webp_tail_oracle.items():
            self.assertNotIn("_missing_vp8", vid, msg=f"Oracle failed to find VP8 chunk: {meta}")
            godot_err = int(meta["godot_err"])
            res = parity[vid]
            expected_ok = (godot_err == 0)
            self.assertEqual(
                bool(res["ok"]),
                expected_ok,
                msg=f"{vid}: publish ok={res['ok']} != libwebp ok={expected_ok} (godot_err={godot_err}, res={res})",
            )
            if expected_ok:
                seen_pass += 1
            else:
                seen_fail += 1
                self.assertEqual(res["reason"], "truncated_webp_vp8", msg=f"{vid}: {res}")
            if meta["label"] == "w48_b":
                w48_errs[int(meta["trim"])] = godot_err
        self.assertGreater(seen_pass, 0)
        self.assertGreater(seen_fail, 0)
        for t_ok in range(0, 4):
            self.assertEqual(w48_errs.get(t_ok), 0, msg=f"w48_b trim={t_ok} expected libwebp OK, got {w48_errs}")
        for t_bad in range(4, 7):
            self.assertNotEqual(w48_errs.get(t_bad, 0), 0, msg=f"w48_b trim={t_bad} expected libwebp ERR, got {w48_errs}")

    def test_t5_integration_token_inherit_zip_zero_rollback_and_resolve_edges(self) -> None:
        ec = self.results["entry_cases"]
        self.assertTrue(ec["tok_inherits_pct"]["prep_ok"], msg=ec["tok_inherits_pct"])
        self.assertTrue(ec["tok_inherits_hash"]["prep_ok"], msg=ec["tok_inherits_hash"])

        self.assertFalse(ec["zip_zero_asset_strict"]["prep_ok"])
        self.assertEqual(ec["zip_zero_asset_strict"]["prep_reason"], "empty_or_unreadable_asset:assets/empty.png")
        self.assertTrue(ec["zip_zero_asset_skip"]["prep_ok"], msg=ec["zip_zero_asset_skip"])

        self.assertFalse(ec["gif_png_strict"]["prep_ok"])
        self.assertEqual(ec["gif_png_strict"]["prep_reason"], "unsupported_image_format:gif")
        self.assertTrue(ec["gif_png_skip"]["prep_ok"], msg=ec["gif_png_skip"])

        it = self.results["integ_t5"]
        self.assertEqual(it["cd_nonascii_0b"], 0)
        self.assertFalse(it["evil_archive_strict"]["ok"])
        self.assertTrue(str(it["evil_archive_strict"]["reason"]).startswith("remote_archive_failed:"), msg=it["evil_archive_strict"])
        self.assertFalse(it["entry_post_map_cancel"]["res"]["ok"])
        self.assertEqual(it["entry_post_map_cancel"]["res"]["reason"], "cancelled")
        self.assertEqual(it["entry_post_map_cancel"]["rem_assets"], [])

        ra = self.results["resolve_adv"]
        self.assertEqual(ra["map%20name.png?v=1#top"]["kind"], "local")
        self.assertTrue(ra["map%20name.png?v=1#top"]["exists"])
        self.assertEqual(ra["map%20name.png?v=1#top"]["rel_path"], "map name.png")
        self.assertEqual(ra["50%_off.png"]["kind"], "local")
        self.assertTrue(ra["50%_off.png"]["exists"])
        self.assertEqual(ra["foo..bar.png"]["kind"], "local")
        self.assertTrue(ra["foo..bar.png"]["exists"])
        self.assertEqual(ra["assets/a%5cb.png"]["kind"], "local")
        self.assertTrue(ra["assets/a%5cb.png"]["exists"])
        self.assertEqual(ra["assets/a%5cb.png"]["rel_path"], "assets/a/b.png")
        for unsafe_v in ("%20user://secret.png", "assets/..", "C:\\evil.png"):
            self.assertEqual(ra[unsafe_v]["kind"], "unsafe", msg=f"{unsafe_v}: {ra[unsafe_v]}")
            self.assertTrue(ra[unsafe_v]["unsafe"], msg=f"{unsafe_v}: {ra[unsafe_v]}")

    def test_t5_prevalidate_worker_pool_batching_and_cancel(self) -> None:
        pv = self.results["preval_t5"]
        self.assertGreater(pv["proc_count"], 1, "Test host expected >1 logical CPU for WorkerThreadPool")
        self.assertEqual(pv["batch513_cache_before"], 513)
        self.assertEqual(pv["batch513_cache_after"], 13)
        self.assertEqual(pv["batch513_ok"], 500)
        self.assertEqual(pv["batch513_fail"], 13)
        self.assertEqual(pv["batch513_mismatch"], 0)
        self.assertEqual(pv["bmp128_cache_sz"], 3)
        self.assertEqual(len(pv["bmp128_sprites"]), 3)
        for sp in pv["bmp128_sprites"]:
            self.assertTrue(str(sp).startswith("asset://") and str(sp).endswith(".png"), msg=sp)
        self.assertEqual(pv["mid_cancel_reads"], 100)
        self.assertEqual(pv["mid_cancel_cache_sz"], 0)
        self.assertEqual(pv["inter_batch_checks"], 523)
        self.assertEqual(pv["inter_batch_cache_sz"], 512)

    def test_t5_webp_4part_nonlast_dct_truncation_parity(self) -> None:
        parity = self.results["webp_tail_parity"]
        four_part = {k: v for k, v in self.webp_tail_oracle.items() if v.get("label") == "vp8_4part"}
        self.assertEqual(len(four_part), 7)
        self.assertEqual(four_part["vp8_4part_cut_0"]["godot_err"], 0)
        self.assertTrue(parity["vp8_4part_cut_0"]["ok"], msg=parity["vp8_4part_cut_0"])
        seen_fail = 0
        for vid, meta in four_part.items():
            res = parity[vid]
            expected_ok = (int(meta["godot_err"]) == 0)
            self.assertEqual(bool(res["ok"]), expected_ok, msg=f"{vid}: {res} vs oracle={meta['godot_err']}")
            if not expected_ok:
                seen_fail += 1
                self.assertEqual(res["reason"], "truncated_webp_vp8", msg=f"{vid}: {res}")
        self.assertGreaterEqual(seen_fail, 4)

    def test_t5_extreme_grid_size_entry_prepare_import(self) -> None:
        gr = self.results["r17_grid"]
        for gid in ("tiny_1e_308", "tiny_1e_20", "huge_1e40"):
            row = gr[gid]
            self.assertTrue(row["ok"], msg=f"{gid}: {row}")
            self.assertEqual(row["v3_errs"], [], msg=gid)
            self.assertTrue(row["all_finite"], msg=gid)
            self.assertTrue(row["all_xform_finite"], msg=gid)
            self.assertGreaterEqual(int(row["counts"].get("merged_walls", 0)), 1, msg=f"{gid}: {row}")
            self.assertTrue(len(row["unit_sizes"]) >= 1, msg=gid)
            for sx, sy in row["unit_sizes"]:
                self.assertGreater(sx, 4.0, msg=f"{gid} collapsed unit size: {sx},{sy}")
                self.assertGreater(sy, 4.0, msg=f"{gid} collapsed unit size: {sx},{sy}")

    def test_t5_dot_slash_zip_and_directory_junction_cycle(self) -> None:
        sr = self.results["r17_src"]
        ds = sr["dot_slash_zip"]
        self.assertTrue(ds["open_ok"], msg=ds)
        self.assertTrue(ds["ins_ok"], msg=ds)
        self.assertTrue(ds["prep_ok"], msg=ds)
        self.assertEqual(ds["prep_counts"]["assets"], 1)

        dsd = sr["dot_slash_dup_zip"]
        self.assertTrue(dsd["open_ok"], msg=dsd)
        self.assertTrue(dsd["ins_ok"], msg=dsd)
        self.assertEqual(dsd["ins_decoded_bytes"], self.r17_dot_dup_expected_bytes)
        self.assertTrue(dsd["prep_ok"], msg=dsd)
        self.assertEqual(dsd["prep_counts"]["assets"], 1)

        jw = sr["junction_dir"]
        self.assertTrue(jw["open_ok"], msg=jw)
        self.assertTrue(jw["ins_ok"], msg=jw)
        self.assertTrue(jw["prep_ok"], msg=jw)
        self.assertEqual(jw["prep_counts"]["assets"], 1)
        self.assertTrue(any("符号链接或目录联接" in str(w) for w in jw["open_warnings"]), msg=jw)
        self.assertTrue(any("符号链接或目录联接" in str(w) for w in jw["warnings"]), msg=jw)

    def test_t5_leveldb_missing_manifest_partial_sst_and_embedded_levels(self) -> None:
        lr = self.results["r17_ldb"]
        ps = lr["partial_missing_sst"]
        self.assertTrue(ps["open_ok"], msg=ps)
        self.assertTrue(ps["col_ok"], msg=ps)
        self.assertEqual(ps["doc_ids"], ["s1"])
        self.assertTrue(any("部分 SSTable 缺失" in str(w) for w in ps["col_warnings"]), msg=ps)
        self.assertTrue(ps["prep_ok"], msg=ps)
        self.assertTrue(any("部分 SSTable 缺失" in str(w) for w in ps["host_warnings"]), msg=ps)

        mm = lr["missing_manifest_file"]
        self.assertTrue(mm["open_ok"], msg=mm)
        self.assertTrue(mm["col_ok"], msg=mm)
        self.assertEqual(mm["doc_ids"], ["s1"])
        self.assertTrue(any("MANIFEST 文件缺失" in str(w) for w in mm["col_warnings"]), msg=mm)
        self.assertTrue(mm["prep_ok"], msg=mm)
        self.assertTrue(any("MANIFEST 文件缺失" in str(w) for w in mm["host_warnings"]), msg=mm)

        el = lr["embedded_levels"]
        self.assertTrue(el["norm_ok"], msg=el)
        self.assertEqual(el["bg_ref"], "assets/emb_bg.png")
        self.assertTrue(el["prep_ok"], msg=el)
        self.assertEqual(el["prep_counts"]["assets"], 1)

    def test_t5_normalizer_int64_min_ability_modifier(self) -> None:
        rn = self.results["r17_norm"]
        self.assertTrue(rn["ok"], msg=rn)
        self.assertLess(rn["str_mod"], 0)
        self.assertEqual(rn["str_mod"], -4611686018427387904)
        self.assertEqual(rn["dex_mod"], 4611686018427387904)

    def test_t5_webp_alph_preprocessing_bits(self) -> None:
        ia = self.results["img_bad_adv"]
        self.assertTrue(ia["webp_alph_p1"]["ok"], msg=ia["webp_alph_p1"])
        for p_bad in ("webp_alph_p2", "webp_alph_p3"):
            self.assertFalse(ia[p_bad]["ok"], msg=f"{p_bad}: {ia[p_bad]}")
            self.assertFalse(ia[p_bad]["unsupported"], msg=f"{p_bad}: {ia[p_bad]}")
            self.assertEqual(ia[p_bad]["reason"], "invalid_webp_alph", msg=f"{p_bad}: {ia[p_bad]}")

    def test_t5_orthogonal_huge_wall_finite_xform(self) -> None:
        row = self.results["r17_grid"]["ortho_huge_wall"]
        self.assertTrue(row["ok"], msg=row)
        self.assertEqual(row["v3_errs"], [], msg=row)
        self.assertTrue(row["all_finite"], msg=row)
        self.assertTrue(row["all_xform_finite"], msg=row)
        self.assertEqual(int(row["counts"].get("merged_walls", -1)), 0, msg=row)
        self.assertTrue(
            any("跳过退化零长度或超长溢出墙体或门" in str(w) and "w_ortho_1e37" in str(w) for w in row["warnings"]),
            msg=row["warnings"],
        )

    def test_t5_zip_3way_mixed_dot_slash_duplicate_decoded_bytes(self) -> None:
        tw = self.results["r17_src"]["three_way_dot_slash_dup_zip"]
        self.assertTrue(tw["open_ok"], msg=tw)
        self.assertEqual(tw["open_decoded_bytes"], self.r18_three_way_expected_bytes, msg=tw)
        self.assertTrue(tw["ins_ok"], msg=tw)
        self.assertEqual(tw["ins_decoded_bytes"], self.r18_three_way_expected_bytes, msg=tw)
        self.assertEqual(tw["cd_sum_bytes"], self.r18_three_way_expected_bytes, msg=tw)
        self.assertTrue(tw["prep_ok"], msg=tw)
        self.assertEqual(tw["prep_counts"]["assets"], 1, msg=tw)

    def test_t5_wall_bounds_and_post_extrusion_nondegenerate(self) -> None:
        row = self.results["r17_grid"]["wall_ulp_and_bound_mix"]
        self.assertTrue(row["ok"], msg=row)
        self.assertEqual(row["v3_errs"], [], msg=row)
        self.assertTrue(row["all_finite"], msg=row)
        self.assertTrue(row["all_xform_finite"], msg=row)
        self.assertEqual(int(row["counts"].get("merged_walls", -1)), 2, msg=row)
        for bad_wid in ("w_diag_8e7", "w_ortho_2e8", "w_diag_1e15"):
            self.assertTrue(
                any("跳过退化零长度或超长溢出墙体或门" in str(w) and bad_wid in str(w) for w in row["warnings"]),
                msg=f"Missing warning for {bad_wid}: {row['warnings']}",
            )
        obs = row["obstacles"]
        self.assertEqual(len(obs), 2, msg=obs)
        self.assertEqual(sorted(str(o["kind"]) for o in obs), ["door", "wall"], msg=obs)
        for o in obs:
            self.assertLessEqual(float(o["max_local_pt"]), 1e7, msg=o)
            self.assertLessEqual(float(o["max_world_pt"]), 1e7, msg=o)
            self.assertFalse(bool(o["p0_eq_p3"]), msg=o)
            self.assertFalse(bool(o["p1_eq_p2"]), msg=o)
            self.assertGreater(float(o["area2"]), 1e-3, msg=o)

    def test_t5_webp_vp8_show_frame_zero_rejected(self) -> None:
        pub = self.results["img_bad_adv"]["webp_vp8_show_frame_0"]
        self.assertFalse(pub["ok"], msg=pub)
        self.assertFalse(pub["unsupported"], msg=pub)
        self.assertNotEqual(pub["reason"], "image_decode_failed:webp", msg=pub)
        self.assertEqual(pub["reason"], "invalid_webp_vp8_keyframe", msg=pub)

        ent = self.results["img_bad_adv"]["webp_vp8_show_frame_0_entry"]
        self.assertFalse(ent["strict_ok"], msg=ent)
        self.assertNotEqual(ent["strict_reason"], "image_decode_failed:webp", msg=ent)
        self.assertEqual(ent["strict_reason"], "invalid_webp_vp8_keyframe", msg=ent)
        self.assertTrue(ent["skip_ok"], msg=ent)
        self.assertTrue(
            any("invalid_webp_vp8_keyframe" in str(w) and "image_decode_failed" not in str(w) for w in ent["skip_warnings"]),
            msg=ent,
        )

    def test_t5_zip_cd_sum_junk_segments_with_leading_slash_and_colon(self) -> None:
        jl = self.results["r17_src"]["junk_lead_colon_zip"]
        self.assertTrue(jl["open_ok"], msg=jl)
        self.assertEqual(jl["open_decoded_bytes"], self.r19_junk_lead_expected_bytes, msg=jl)
        self.assertTrue(jl["ins_ok"], msg=jl)
        self.assertEqual(jl["ins_decoded_bytes"], self.r19_junk_lead_expected_bytes, msg=jl)
        self.assertEqual(jl["cd_sum_bytes"], jl["open_decoded_bytes"], msg=jl)
        self.assertTrue(jl["prep_ok"], msg=jl)
        self.assertEqual(jl["prep_counts"]["assets"], 1, msg=jl)

    def test_t5_vp8l_constant_group_fast_path_and_meta_bounds(self) -> None:
        vc = self.results["vp8l_const"]
        for fast_id in ("vp8l_16k_const", "vp8l_16k_cc_const", "vp8l_8k_meta_const", "vp8l_8k_meta_hbits0_const"):
            row = vc[fast_id]
            self.assertTrue(row["ok"], msg=f"{fast_id}: {row}")
            self.assertLess(int(row["ms"]), 2000, msg=f"{fast_id} exceeded 2000 ms: {row}")
        self.assertEqual(vc["vp8l_8k_meta_const"]["native_err"], 0, msg=vc["vp8l_8k_meta_const"])
        self.assertEqual(vc["vp8l_8k_meta_const"]["native_w"], 8192)
        self.assertEqual(vc["vp8l_8k_meta_const"]["native_h"], 8192)

        mg_ok = vc["vp8l_64x64_multigroup_valid"]
        self.assertTrue(mg_ok["ok"], msg=mg_ok)
        self.assertEqual(mg_ok["native_err"], 0, msg=mg_ok)
        self.assertEqual(mg_ok["native_w"], 64)
        self.assertEqual(mg_ok["native_h"], 64)

        for oob_id in ("vp8l_64x64_meta_gid_oob", "vp8l_64x64_meta_nonconst_gid_oob"):
            bad = vc[oob_id]
            self.assertFalse(bad["ok"], msg=f"{oob_id}: {bad}")
            self.assertEqual(bad["reason"], "invalid_webp_vp8l", msg=f"{oob_id}: {bad}")

    def test_t5_standalone_actor_key_dedup_no_entity_id_collision(self) -> None:
        adc = self.results["actor_dup_cases"]
        for cid, exp_cnt in (("nedb_anon_collision", 3), ("ldb_dup_id", 2)):
            row = adc[cid]
            self.assertTrue(row["ok"], msg=f"{cid}: {row}")
            self.assertEqual(row["v3_errs"], [], msg=f"{cid}: {row}")
            self.assertEqual(row["ent_count"], exp_cnt, msg=f"{cid}: {row}")
            self.assertEqual(row["unique_id_count"], exp_cnt, msg=f"{cid}: {row}")
            self.assertEqual(row["dup_ids"], [], msg=f"{cid}: {row}")
            self.assertEqual(len(set(row["tok_sprites"])), exp_cnt, msg=f"{cid} sprite overwrite: {row}")
            self.assertEqual(len(set(row["arch_sprites"])), exp_cnt, msg=f"{cid} archive sprite overwrite: {row}")

    def test_t5_png_chunk_bits_and_nedb_index_anon_isolation(self) -> None:
        ia = self.results["img_bad_adv"]
        for k_crit in ("png_chunk_FOOB_before", "png_chunk_FOOb_before"):
            self.assertFalse(ia[k_crit]["ok"], msg=f"{k_crit}: {ia[k_crit]}")
            self.assertTrue(ia[k_crit]["unsupported"], msg=f"{k_crit}: {ia[k_crit]}")
            self.assertEqual(ia[k_crit]["reason"], "unsupported_png_critical_chunk", msg=f"{k_crit}: {ia[k_crit]}")
        self.assertFalse(ia["png_chunk_foob_before"]["ok"], msg=ia["png_chunk_foob_before"])
        self.assertFalse(ia["png_chunk_foob_before"]["unsupported"], msg=ia["png_chunk_foob_before"])
        self.assertEqual(ia["png_chunk_foob_before"]["reason"], "invalid_png_chunk_type", msg=ia["png_chunk_foob_before"])
        for k_pos in ("png_chunk_fOOb_before", "png_chunk_foOb_before", "png_chunk_FOOB_after"):
            self.assertTrue(ia[k_pos]["ok"], msg=f"{k_pos}: {ia[k_pos]}")
            self.assertEqual(ia[k_pos]["native_err"], 0, msg=f"{k_pos}: {ia[k_pos]}")
            self.assertEqual(ia[k_pos]["native_w"], 2, msg=f"{k_pos}: {ia[k_pos]}")
            self.assertEqual(ia[k_pos]["native_h"], 2, msg=f"{k_pos}: {ia[k_pos]}")

        ec = self.results["entry_cases"]
        self.assertFalse(ec["png_crit_before_strict"]["prep_ok"], msg=ec["png_crit_before_strict"])
        self.assertEqual(ec["png_crit_before_strict"]["prep_reason"], "unsupported_png_critical_chunk")
        self.assertTrue(ec["png_crit_before_skip"]["prep_ok"], msg=ec["png_crit_before_skip"])
        self.assertTrue(
            any("unsupported_png_critical_chunk" in str(w) and "image_decode_failed" not in str(w) for w in ec["png_crit_before_skip"]["warnings"]),
            msg=ec["png_crit_before_skip"],
        )
        self.assertFalse(ec["png_rsv_before_strict"]["prep_ok"], msg=ec["png_rsv_before_strict"])
        self.assertEqual(ec["png_rsv_before_strict"]["prep_reason"], "invalid_png_chunk_type")
        self.assertTrue(ec["png_rsv_before_skip"]["prep_ok"], msg=ec["png_rsv_before_skip"])
        self.assertTrue(
            any("invalid_png_chunk_type" in str(w) and "image_decode_failed" not in str(w) for w in ec["png_rsv_before_skip"]["warnings"]),
            msg=ec["png_rsv_before_skip"],
        )

        na = ec["nedb_idx_anon"]
        self.assertTrue(na["ins_ok"], msg=na)
        self.assertEqual(na["ins_counts"]["maps"], 1, msg=na)
        self.assertEqual(na["ins_counts"]["objects"], 2, msg=na)
        self.assertEqual(na["ins_counts"]["records"], 3, msg=na)
        self.assertTrue(na["prep_ok"], msg=na)
        self.assertEqual(na["floors"], 1, msg=na)
        self.assertEqual(na["floor_names"], ["Real Tavern"], msg=na)
        self.assertEqual([str(a["name"]) for a in na["actors"]], ["AnonLine1", "Goblin"], msg=na)


if __name__ == "__main__":
    unittest.main()
