"""Standalone unit test suite for Milestone M3 FVTT parser & normalizer GDScript modules.

Tests:
- Static hygiene on `mods/fvtt-world-importer/src/*.gd` (UTF-8 no BOM, LF only, no `preload(`, no `class_name`,
  no top-level cross-file `load(`, no machine-local absolute paths).
- Real headless Godot (`GODOT_BIN`) execution of:
  1. Synthetic Snappy, NeDB, LevelDB (WAL multi-block >32KiB, tombstones, kDeletedFile, bit-63 seq, invalid UTF-8),
     Source (depth 0/1/2/multi/corrupt ZIP, gateway.json, junk filter, percent-decode, unsafe refs), and Normalizer
     (character class-level sum, equipped armor+shield AC, custom formula, ac.override, foreground, gridless/gridded,
     token actor-type resolution before filtering, LevelDB-over-NeDB priority, .gif unsupported count).
  2. Unpacked `bgdia` (v14 LevelDB, if present in environment) — 31 scenes, 229 actors, 3734 walls, 123 doors,
     131 lights, 227 tiles, 618 tokens, 5 dangling, 62 folders, 1178 assets, option filtering, known ACs.
  3. Zipped `bgdia` (v9 NeDB CJK archive, if present in environment) — strict 0/229 AC parity & scene/actor parity
     against unpacked `bgdia`.
- Every Godot invocation isolates APPDATA/LOCALAPPDATA/TEMP/TMP under `.cache/test_tmp/` and asserts zero
  `ERROR:` / `SCRIPT ERROR:` / `Unicode parsing error` / leak lines via `host_verifier.analyze_godot_logs()`.
"""

from __future__ import annotations

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
    build_manifest_bytes,
    build_sstable_bytes,
    build_v14_world,
    build_v9_world,
    build_wal_bytes,
    encode_write_batch,
    leveldb_masked_crc32c,
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
    pack_world_zip,
    redact_bgdia_path,
    resolve_bgdia_dir_world_json,
    resolve_bgdia_zip_path,
    snappy_compress,
    write_json_file,
    write_nedb_file,
)


SRC_DIR = _WORKSPACE_ROOT / "mods" / "fvtt-world-importer" / "src"
TEST_TMP_ROOT = _WORKSPACE_ROOT / ".cache" / "test_tmp"

M3_GD_FILES = (
    "fvtt_source.gd",
    "fvtt_nedb.gd",
    "snappy.gd",
    "fvtt_leveldb.gd",
    "fvtt_normalizer.gd",
)

# GDScript probe executed inside an isolated temp Godot project under .cache/test_tmp/
_PROBE_RUNNER_GD = r'''extends SceneTree

var _src_dir: String = "res://src"


class _MockWeirdSource extends RefCounted:
	var _kind_val: Variant = "dir"
	var _reply: Dictionary = {}

	func _init(reply: Dictionary, kind_val: Variant = "dir") -> void:
		_reply = reply
		_kind_val = kind_val

	func get_source_kind() -> Variant:
		return _kind_val

	func resolve_asset_ref(_ref: String, _world_id: String = "") -> Dictionary:
		return _reply


func _load_mod(name: String) -> RefCounted:
	var scr := load(_src_dir.path_join(name)) as Script
	if scr == null:
		return null
	return scr.new()


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
		f.store_string(JSON.stringify(payload, "\t"))
		f.close()


func _core_major(world_json: Dictionary) -> int:
	var cv := str(world_json.get("coreVersion", world_json.get("version", ""))).strip_edges()
	if cv.is_empty():
		return 0
	var first := cv.split(".", false)[0]
	return int(first) if first.is_valid_int() else 0


func _read_collection_auto(source: RefCounted, coll: String, core_major: int, nedb: RefCounted, leveldb: RefCounted, snappy: RefCounted) -> Dictionary:
	if leveldb.has_collection(source, coll):
		return leveldb.read_collection(source, coll, snappy)
	if (core_major <= 0 or core_major < 11) and source.has_file("data/%s.db" % coll):
		return nedb.read_collection(source, coll)
	return {"ok": false, "reason": "collection_not_found:" + coll}


func _inspect_world(world_path: String, options: Dictionary) -> Dictionary:
	var src := _load_mod("fvtt_source.gd")
	var nedb := _load_mod("fvtt_nedb.gd")
	var snappy := _load_mod("snappy.gd")
	var leveldb := _load_mod("fvtt_leveldb.gd")
	var norm := _load_mod("fvtt_normalizer.gd")

	var open_res: Dictionary = src.open(world_path)
	if not bool(open_res.get("ok", false)):
		return {"ok": false, "stage": "open", "reason": str(open_res.get("reason", ""))}

	var wj: Dictionary = open_res["world_json"]
	var major: int = _core_major(wj)
	var collections: Dictionary = {}
	for cname: String in ["scenes", "actors", "folders"]:
		collections[cname] = _read_collection_auto(src, cname, major, nedb, leveldb, snappy)

	var norm_res: Dictionary = norm.normalize(wj, collections, src, options)
	var kind: String = src.get_source_kind()
	src.close()
	if not bool(norm_res.get("ok", false)):
		return {"ok": false, "stage": "normalize", "reason": str(norm_res.get("reason", ""))}

	var model: Dictionary = norm_res["model"]
	var actor_rows: Array = []
	for a: Dictionary in model["actors"]:
		actor_rows.append({
			"id": a["id"],
			"name": a["name"],
			"actor_type": a["actor_type"],
			"sub_type": a["sub_type"],
			"folder_name": a["folder_name"],
			"ac": a["ac"],
			"hp_value": a["hp_value"],
			"hp_max": a["hp_max"],
			"cr_or_level": a["cr_or_level"],
			"dex_mod": a["abilities"]["dex"]["mod"],
		})

	var scene_rows: Array = []
	var total_dangling: int = 0
	for sc: Dictionary in model["scenes"]:
		var d_cnt: int = 0
		var wall_cnt: int = 0
		var door_cnt: int = 0
		for w: Dictionary in sc["walls"]:
			if int(w["door"]) == 0:
				wall_cnt += 1
			else:
				door_cnt += 1
		var tok_names: Array = []
		for tok: Dictionary in sc["tokens"]:
			tok_names.append(tok["name"])
			if bool(tok["actor_missing"]):
				d_cnt += 1
		total_dangling += d_cnt
		scene_rows.append({
			"id": sc["id"],
			"name": sc["name"],
			"grid_size": sc["grid_size"],
			"grid_type": sc["grid_type"],
			"scene_x": sc["scene_x"],
			"scene_y": sc["scene_y"],
			"background_ref": sc["background_ref"],
			"foreground_ref": sc["foreground_ref"],
			"walls": wall_cnt,
			"doors": door_cnt,
			"lights": sc["lights"].size(),
			"tiles": sc["tiles"].size(),
			"tokens": sc["tokens"].size(),
			"dangling_tokens": d_cnt,
			"token_names": tok_names,
			"lights_data": sc["lights"],
			"tokens_data": sc["tokens"],
		})

	return {
		"ok": true,
		"source_kind": kind,
		"world_meta": model["world_meta"],
		"inspect_counts": model["inspect_counts"],
		"remote_assets_count": model["remote_assets"].size(),
		"remote_assets": model["remote_assets"],
		"assets": model["assets"],
		"warnings_count": model["warnings"].size(),
		"warnings": model["warnings"],
		"dangling_tokens_total": total_dangling,
		"scenes_count": scene_rows.size(),
		"actors_count": actor_rows.size(),
		"folders_count": (collections["folders"].get("docs", []) as Array).size(),
		"scenes": scene_rows,
		"actors": actor_rows,
	}


func _sha256_bytes(data: PackedByteArray) -> String:
	var ctx := HashingContext.new()
	ctx.start(HashingContext.HASH_SHA256)
	ctx.update(data)
	return ctx.finish().hex_encode()


func _run_unit_suite(cfg: Dictionary) -> Dictionary:
	var results: Dictionary = {}
	var snappy := _load_mod("snappy.gd")
	var nedb := _load_mod("fvtt_nedb.gd")
	var leveldb := _load_mod("fvtt_leveldb.gd")
	var src := _load_mod("fvtt_source.gd")

	# 1. Snappy binary test vectors (copy4, l6=62, l6=63, overlap RLE, errors)
	var snappy_results: Dictionary = {}
	var vectors_b64: Dictionary = cfg.get("snappy_vectors", {})
	for vk: Variant in vectors_b64.keys():
		var raw: PackedByteArray = Marshalls.base64_to_raw(str(vectors_b64[vk]))
		var sres: Dictionary = snappy.decompress(raw)
		if bool(sres.get("ok", false)):
			var d: PackedByteArray = sres["data"]
			snappy_results[str(vk)] = {"ok": true, "sha256": _sha256_bytes(d), "len": d.size(), "prefix": d.slice(0, mini(32, d.size())).get_string_from_ascii() if d.size() <= 64 else ""}
		else:
			snappy_results[str(vk)] = {"ok": false, "reason": str(sres.get("reason", ""))}
	var bad_limit_raw: PackedByteArray = Marshalls.base64_to_raw(str(vectors_b64.get("overlap", "")))
	snappy_results["limit_reject"] = snappy.decompress(bad_limit_raw, 4)
	results["snappy"] = snappy_results

	# 2. NeDB synthetic test (BOM, CRLF, duplicate _id, $$deleted, bad JSON, invalid UTF-8)
	var nedb_b64: String = str(cfg.get("nedb_bytes_b64", ""))
	if not nedb_b64.is_empty():
		var nraw: PackedByteArray = Marshalls.base64_to_raw(nedb_b64)
		var nres: Dictionary = nedb.parse_jsonl(nraw)
		results["nedb"] = {
			"ok": nres["ok"],
			"docs": nres["docs"],
			"raw_lines": nres["raw_lines"],
			"deleted_count": nres["deleted_count"],
			"parse_errors": nres["parse_errors"],
			"warnings_count": (nres["warnings"] as Array).size(),
		}

	# 3. LevelDB synthetic test (WAL multi-block >32KiB, tombstones, kDeletedFile, bit-63 seq, invalid UTF-8)
	var ldb_dir_world: String = str(cfg.get("leveldb_edge_world", ""))
	if not ldb_dir_world.is_empty():
		var o_res: Dictionary = src.open(ldb_dir_world)
		var col_res: Dictionary = leveldb.read_collection(src, "scenes", snappy)
		var trunc_wal_b64: String = str(cfg.get("truncated_wal_b64", ""))
		var twal_res: Dictionary = leveldb.parse_wal_bytes(Marshalls.base64_to_raw(trunc_wal_b64))
		var bad_ldb_b64: String = str(cfg.get("bad_ldb_b64", ""))
		var bldb_res: Dictionary = leveldb.parse_ldb_bytes(Marshalls.base64_to_raw(bad_ldb_b64), snappy)
		src.close()
		results["leveldb_edge"] = {
			"open_ok": o_res.get("ok", false),
			"col_ok": col_res.get("ok", false),
			"docs": col_res.get("docs", []),
			"parse_errors": col_res.get("parse_errors", 0),
			"warnings": col_res.get("warnings", []),
			"trunc_wal_records": (twal_res.get("records", []) as Array).size(),
			"trunc_wal_errors": twal_res.get("parse_errors", 0),
			"bad_ldb": bldb_res,
		}

	# 4. World inspection cases (error cases + synthetic worlds + optional bgdia)
	var world_cases: Array = cfg.get("world_cases", [])
	var world_results: Dictionary = {}
	for wc: Dictionary in world_cases:
		var cid: String = str(wc["id"])
		var wpath: String = str(wc["path"])
		var opts: Dictionary = wc.get("options", {})
		world_results[cid] = _inspect_world(wpath, opts)
	results["worlds"] = world_results

	# 5. Iteration 2 regression probes (NeDB reinsert, LevelDB int64 overflow, Normalizer null-safety/rfind, depth-0 ZIP + subdir shadow)
	var regressions: Dictionary = {}

	var reinsert_b64: String = str(cfg.get("nedb_reinsert_b64", ""))
	if not reinsert_b64.is_empty():
		var rres: Dictionary = nedb.parse_jsonl(Marshalls.base64_to_raw(reinsert_b64))
		regressions["nedb_reinsert"] = {
			"ok": rres.get("ok", false),
			"docs": rres.get("docs", []),
			"deleted_count": rres.get("deleted_count", 0),
		}

	var del_null_b64: String = str(cfg.get("nedb_deleted_null_false_b64", ""))
	if not del_null_b64.is_empty():
		var dnres: Dictionary = nedb.parse_jsonl(Marshalls.base64_to_raw(del_null_b64))
		regressions["nedb_deleted_null_false"] = {
			"ok": dnres.get("ok", false),
			"docs": dnres.get("docs", []),
			"deleted_count": dnres.get("deleted_count", 0),
			"parse_errors": dnres.get("parse_errors", -1),
		}

	var del_mixed_b64: String = str(cfg.get("nedb_deleted_mixed_b64", ""))
	if not del_mixed_b64.is_empty():
		var dmres: Dictionary = nedb.parse_jsonl(Marshalls.base64_to_raw(del_mixed_b64))
		regressions["nedb_deleted_mixed"] = {
			"ok": dmres.get("ok", false),
			"docs": dmres.get("docs", []),
			"deleted_count": dmres.get("deleted_count", 0),
			"parse_errors": dmres.get("parse_errors", -1),
		}

	var sst_idx_b64: String = str(cfg.get("sst_idx_overflow_b64", ""))
	if not sst_idx_b64.is_empty():
		regressions["sst_idx_overflow"] = leveldb.parse_ldb_bytes(Marshalls.base64_to_raw(sst_idx_b64), snappy)

	var sst_ns_b64: String = str(cfg.get("sst_blk_ns_overflow_b64", ""))
	if not sst_ns_b64.is_empty():
		regressions["sst_blk_ns_overflow"] = leveldb.parse_ldb_bytes(Marshalls.base64_to_raw(sst_ns_b64), snappy)

	var wb_klen_b64: String = str(cfg.get("wal_wb_klen_overflow_b64", ""))
	if not wb_klen_b64.is_empty():
		regressions["wal_wb_klen_overflow"] = leveldb._parse_write_batch(Marshalls.base64_to_raw(wb_klen_b64))

	var wal_ovf_world: String = str(cfg.get("wal_overflow_world", ""))
	if not wal_ovf_world.is_empty():
		var wov_open: Dictionary = src.open(wal_ovf_world)
		var wov_col: Dictionary = leveldb.read_collection(src, "scenes", snappy)
		src.close()
		regressions["wal_overflow_col"] = {
			"open_ok": wov_open.get("ok", false),
			"col_ok": wov_col.get("ok", false),
			"parse_errors": wov_col.get("parse_errors", 0),
			"warnings": wov_col.get("warnings", []),
		}

	var norm := _load_mod("fvtt_normalizer.gd")
	var null_col_res: Dictionary = norm.normalize(
		{"id": "nulltest", "title": "Null Test", "system": "dnd5e", "coreVersion": "14.369"},
		{
			"scenes": {
				"ok": true,
				"docs": [{"_id": "s.dot.1", "name": "DotScene"}],
				"sublevels": {
					"scenes.walls": {
						"s.dot.1.w1": {"_id": "w1", "c": [0, 0, 10, 0], "sense": null, "sound": 10},
					},
					"scenes.lights": {
						"s.dot.1.lt1": {"_id": "lt1", "x": 10, "y": 20, "config": {"bright": null, "dim": null, "angle": null}, "bright": 15.0, "dim": 30.0, "angle": 90.0},
					},
					"scenes.tiles": {
						"s.dot.1.tl1": {"_id": "tl1", "sort": null, "z": 7},
					},
					"scenes.tokens": {
						"s.dot.1.tk1": {"_id": "tk1", "actorId": "a1", "width": null, "height": null, "disposition": null, "actorLink": null},
					},
				},
				"parse_errors": null,
				"warnings": null,
			},
			"actors": {
				"ok": true,
				"docs": [{
					"_id": "a1",
					"name": "LinkedPC",
					"type": "character",
					"prototypeToken": {"width": 2.0, "height": 2.0, "disposition": 1, "actorLink": true},
				}],
				"sublevels": {},
				"warnings": null,
			},
		},
		null,
		{}
	)
	var null_check: Dictionary = {"ok": null_col_res.get("ok", false)}
	if bool(null_check["ok"]):
		var nm: Dictionary = null_col_res["model"]
		var nsc: Dictionary = (nm["scenes"] as Array)[0]
		null_check["walls_count"] = (nsc["walls"] as Array).size()
		null_check["wall_sense"] = ((nsc["walls"] as Array)[0] as Dictionary).get("sense", -1) if (nsc["walls"] as Array).size() > 0 else -1
		null_check["light"] = (nsc["lights"] as Array)[0] if (nsc["lights"] as Array).size() > 0 else {}
		null_check["tile_z"] = ((nsc["tiles"] as Array)[0] as Dictionary).get("z_order", -1) if (nsc["tiles"] as Array).size() > 0 else -1
		null_check["token"] = (nsc["tokens"] as Array)[0] if (nsc["tokens"] as Array).size() > 0 else {}
	regressions["normalizer_null_and_rfind"] = null_check

	regressions["normalizer_null_ok_guard"] = norm.normalize(
		{"id": "nullok", "title": "Null OK", "system": "dnd5e", "coreVersion": "14.369"},
		{"scenes": {"ok": null}, "actors": {"ok": null}},
		null,
		{}
	)

	# 6. Iteration 4 regressions:
	#    (a) normalize(null / non-Dictionary args)
	var valid_min_cols: Dictionary = {
		"scenes": {"ok": true, "docs": [], "sublevels": {}},
		"actors": {"ok": true, "docs": [], "sublevels": {}},
	}
	regressions["iter4_norm_null_wj"] = norm.normalize(null, valid_min_cols, null, {})
	regressions["iter4_norm_int_wj"] = norm.normalize(123, valid_min_cols, null, {})
	regressions["iter4_norm_null_cols"] = norm.normalize({}, null, null, {})
	regressions["iter4_norm_arr_cols"] = norm.normalize({}, [], null, {})
	var null_opts_res: Dictionary = norm.normalize(
		{"id": "optnull", "title": "Opt Null", "system": "dnd5e", "coreVersion": "14.369"},
		valid_min_cols,
		null,
		null
	)
	var str_opts_res: Dictionary = norm.normalize(
		{"id": "optstr", "title": "Opt Str", "system": "dnd5e", "coreVersion": "14.369"},
		valid_min_cols,
		null,
		"not_a_dict"
	)
	regressions["iter4_norm_null_opts_ok"] = null_opts_res.get("ok", false)
	regressions["iter4_norm_str_opts_ok"] = str_opts_res.get("ok", false)

	#    (b) >64-bit integer strings in _to_int, _eval_simple_int_expr, _parse_file_number, and normalizer fields/formulas
	regressions["iter4_to_int_huge"] = norm._to_int("99999999999999999999999999", -77)
	regressions["iter4_to_int_over_max"] = norm._to_int("9223372036854775808", -77)
	regressions["iter4_to_int_under_min"] = norm._to_int("-9223372036854775809", -77)
	regressions["iter4_to_int_exact_max"] = str(norm._to_int("9223372036854775807", -77))
	regressions["iter4_to_int_exact_min"] = str(norm._to_int("-9223372036854775808", -77))
	regressions["iter4_to_int_sci_huge"] = norm._to_int("1e30", -77)
	regressions["iter4_expr_huge"] = norm._eval_simple_int_expr("99999999999999999999999999 + 2")
	regressions["iter4_expr_add_ovf"] = norm._eval_simple_int_expr("9223372036854775807 + 1")
	regressions["iter4_expr_valid_min"] = str(norm._eval_simple_int_expr("-9223372036854775808 + 1"))
	regressions["iter4_ldb_fnum_huge"] = leveldb._parse_file_number("99999999999999999999999999.ldb")

	var huge_actor_res: Dictionary = norm.normalize(
		{"id": "hugeint", "title": "Huge Int", "system": "dnd5e", "coreVersion": "14.369"},
		{
			"scenes": {"ok": true, "docs": [], "sublevels": {}},
			"actors": {
				"ok": true,
				"docs": [{
					"_id": "a_huge",
					"name": "OverflowTester",
					"type": "npc",
					"system": {
						"abilities": {"dex": {"value": 14}},
						"attributes": {
							"hp": {"value": "99999999999999999999999999", "max": "9223372036854775808", "temp": "-9223372036854775809"},
							"ac": {"calc": "custom", "formula": "99999999999999999999999999 + @attributes.ac.dex"},
						},
					},
				}],
				"sublevels": {},
			},
		},
		null,
		{}
	)
	var huge_actor: Dictionary = {}
	if bool(huge_actor_res.get("ok", false)) and (huge_actor_res["model"]["actors"] as Array).size() == 1:
		huge_actor = (huge_actor_res["model"]["actors"] as Array)[0]
	regressions["iter4_huge_actor_ok"] = huge_actor_res.get("ok", false)
	regressions["iter4_huge_actor_ac"] = huge_actor.get("ac", -1)
	regressions["iter4_huge_actor_hp_max"] = huge_actor.get("hp_max", -1)
	regressions["iter4_huge_actor_hp_temp"] = huge_actor.get("hp_temp", -1)

	#    (c) _register_asset with mock source returning unsafe: null, exists: null
	var weird_src1 := _MockWeirdSource.new({"kind": "local", "rel_path": "a.png", "url": "", "exists": null, "unsafe": null, "ext": "png"})
	var weird_res1: Dictionary = norm.normalize(
		{"id": "weird1", "title": "Weird1", "system": "dnd5e", "coreVersion": "14.369", "background": "a.png"},
		valid_min_cols,
		weird_src1,
		{}
	)
	var weird_src2 := _MockWeirdSource.new({"kind": null, "rel_path": null, "url": null, "exists": null, "unsafe": null, "ext": null}, null)
	var weird_res2: Dictionary = norm.normalize(
		{"id": "weird2", "title": "Weird2", "system": "dnd5e", "coreVersion": "14.369", "background": "b.png"},
		valid_min_cols,
		weird_src2,
		{}
	)
	regressions["iter4_weird_src1_ok"] = weird_res1.get("ok", false)
	regressions["iter4_weird_src1_asset"] = (weird_res1.get("model", {}).get("assets", {}) as Dictionary).get("a.png", {})
	regressions["iter4_weird_src2_ok"] = weird_res2.get("ok", false)
	regressions["iter4_weird_src2_assets_size"] = (weird_res2.get("model", {}).get("assets", {}) as Dictionary).size()

	#    (d) fvtt_nedb $$deleted numeric edge cases (JSON 1 -> float 1.0, 0, 2, 1.5, null, "false", true, NAN, INF)
	var nedb_num_b64: String = str(cfg.get("nedb_deleted_numeric_b64", ""))
	if not nedb_num_b64.is_empty():
		var nnres: Dictionary = nedb.parse_jsonl(Marshalls.base64_to_raw(nedb_num_b64))
		regressions["iter4_nedb_deleted_numeric"] = {
			"ok": nnres.get("ok", false),
			"docs": nnres.get("docs", []),
			"deleted_count": nnres.get("deleted_count", 0),
			"parse_errors": nnres.get("parse_errors", -1),
		}
	regressions["iter4_nedb_truthy_nan"] = nedb._is_truthy_deleted(NAN)
	regressions["iter4_nedb_truthy_inf"] = nedb._is_truthy_deleted(INF)
	regressions["iter4_nedb_truthy_int1"] = nedb._is_truthy_deleted(1)
	regressions["iter4_nedb_truthy_float1"] = nedb._is_truthy_deleted(1.0)
	regressions["iter4_nedb_truthy_float15"] = nedb._is_truthy_deleted(1.5)

	var d0_zip: String = str(cfg.get("depth0_zip_path", ""))
	if not d0_zip.is_empty():
		var d0_open: Dictionary = src.open(d0_zip)
		var top_subdirs: Array = Array(src.list_subdirs(""))
		var assets_subdirs: Array = Array(src.list_subdirs("assets"))
		var has_ldb_shadow: bool = leveldb.has_collection(src, "scenes")
		var auto_col: Dictionary = _read_collection_auto(src, "scenes", 9, nedb, leveldb, snappy)
		src.close()
		regressions["depth0_and_shadow"] = {
			"open_ok": d0_open.get("ok", false),
			"source_kind": d0_open.get("source_kind", ""),
			"top_subdirs": top_subdirs,
			"assets_subdirs": assets_subdirs,
			"has_ldb_shadow": has_ldb_shadow,
			"auto_col_ok": auto_col.get("ok", false),
			"auto_col_docs": auto_col.get("docs", []),
		}

	# 7. Iteration 20 regressions: NeDB $$indexCreated/$$indexRemoved & anonymous namespace isolation
	for idx_key: String in ["nedb_index_directives_b64", "nedb_anon_both_b64", "nedb_anon_tombstone_b64"]:
		var b64_v: String = str(cfg.get(idx_key, ""))
		if not b64_v.is_empty():
			var n_res: Dictionary = nedb.parse_jsonl(Marshalls.base64_to_raw(b64_v))
			regressions[idx_key] = {
				"ok": n_res.get("ok", false),
				"docs": n_res.get("docs", []),
				"deleted_count": n_res.get("deleted_count", -1),
				"parse_errors": n_res.get("parse_errors", -1),
				"warnings": n_res.get("warnings", []),
			}

	results["regressions"] = regressions

	return results


func _initialize() -> void:
	var args: PackedStringArray = OS.get_cmdline_user_args()
	var cfg_path: String = ""
	var out_path: String = ""
	for a: String in args:
		if a.begins_with("--cfg="):
			cfg_path = a.substr(6)
		elif a.begins_with("--out="):
			out_path = a.substr(6)

	var cfg_var: Variant = _read_json_arg(cfg_path)
	if not (cfg_var is Dictionary):
		_write_json_out(out_path, {"ok": false, "reason": "bad_probe_cfg"})
		quit(2)
		return

	var out: Dictionary = _run_unit_suite(cfg_var as Dictionary)
	out["ok"] = true
	_write_json_out(out_path, out)
	quit(0)
'''


def _encode_varint32(val: int) -> bytes:
    buf = bytearray()
    v = val & 0xFFFFFFFF
    while v >= 0x80:
        buf.append((v & 0x7F) | 0x80)
        v >>= 7
    buf.append(v)
    return bytes(buf)


def _encode_varint64(val: int) -> bytes:
    buf = bytearray()
    v = val & 0xFFFFFFFFFFFFFFFF
    while v >= 0x80:
        buf.append((v & 0x7F) | 0x80)
        v >>= 7
    buf.append(v)
    return bytes(buf)


def _snappy_literal_with_l6(payload: bytes, forced_l6: int) -> bytes:
    """Build a valid Snappy stream encoding `payload` with an explicit l6 (60..63) literal tag."""
    extra = forced_l6 - 59
    length_minus_1 = len(payload) - 1
    hdr = bytes([forced_l6 << 2]) + length_minus_1.to_bytes(extra, "little")
    return _encode_varint32(len(payload)) + hdr + payload


def _snappy_copy4_stream(prefix: bytes, offset: int, length: int) -> bytes:
    """Build a valid Snappy stream emitting `prefix` literal followed by a 4-byte copy4 op."""
    ulen = len(prefix) + length
    lit_tag = bytes([(len(prefix) - 1) << 2])
    copy4_tag = bytes([((length - 1) << 2) | 0x03]) + struct.pack("<I", offset)
    return _encode_varint32(ulen) + lit_tag + prefix + copy4_tag


class TestFvttParserStaticHygiene(unittest.TestCase):
    def test_src_gd_hygiene_and_isolation(self) -> None:
        self.assertTrue(SRC_DIR.is_dir(), f"Missing {SRC_DIR}")
        for fname in M3_GD_FILES:
            fpath = SRC_DIR / fname
            self.assertTrue(fpath.is_file(), f"Missing M3 file: {fname}")
            raw = fpath.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"{fname} must not contain UTF-8 BOM")
            self.assertNotIn(b"\r", raw, f"{fname} must use LF-only line endings (found CR)")
            text = raw.decode("utf-8")
            self.assertTrue(text.startswith("extends RefCounted\n"), f"{fname} must start with 'extends RefCounted'")
            self.assertNotRegex(text, r"(?m)^\s*class_name\b", f"{fname} must not declare class_name")
            self.assertNotIn("preload(", text, f"{fname} must not call preload()")
            self.assertNotIn("load(", text, f"{fname} must not call cross-file load()")
            self.assertNotIn("JSON.parse_string", text, f"{fname} must use JSON.new().parse()")
            self.assertNotIn("0xdb4775248b80fb57", text.lower(), f"{fname} must not embed 64-bit >INT64_MAX literal")
            self.assertNotRegex(text, r"(?i)(?:[a-z]:\\\\Users\\\\|[a-z]:/Users/|/Users/|/home/|AppData[/\\\\]Local)", f"{fname} must not contain machine-local paths")


class TestFvttParserWithGodot(unittest.TestCase):
    run_dir: Path
    probe_dir: Path
    godot_bin: Path
    batch_results: dict
    bgdia_dir_wj: Path | None
    bgdia_zip: Path | None

    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_WORKSPACE_ROOT)
        if cfg.godot_bin is None or not cfg.godot_bin.is_file():
            raise unittest.SkipTest("GODOT_BIN not configured or unavailable in this environment")
        try:
            ver = subprocess.run(
                [str(cfg.godot_bin), "--headless", "--quit", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise unittest.SkipTest(f"GODOT_BIN cannot be executed in current environment: {exc}") from exc
        if ver.returncode != 0:
            raise unittest.SkipTest(f"GODOT_BIN --version exited {ver.returncode}")

        cls.godot_bin = cfg.godot_bin
        cls.run_dir = TEST_TMP_ROOT / f"fvtt_parser_{uuid.uuid4().hex[:10]}"
        cls.probe_dir = cls.run_dir / "probe_project"
        try:
            cls._prepare_and_run_probe()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def _prepare_and_run_probe(cls) -> None:
        cls.probe_dir.mkdir(parents=True, exist_ok=True)
        (cls.probe_dir / "project.godot").write_text(
            'config_version=5\n\n[application]\nconfig/name="fvtt_parser_test"\n',
            encoding="utf-8",
            newline="\n",
        )
        src_copy_dir = cls.probe_dir / "src"
        src_copy_dir.mkdir(parents=True, exist_ok=True)
        for fname in M3_GD_FILES:
            shutil.copy2(SRC_DIR / fname, src_copy_dir / fname)
        (cls.probe_dir / "probe.gd").write_text(_PROBE_RUNNER_GD, encoding="utf-8", newline="\n")

        fixtures_dir = cls.run_dir / "fixtures"
        fixtures_dir.mkdir(parents=True, exist_ok=True)
        png = make_png_bytes(4, 4)

        # --- Synthetic Snappy binary vectors ---
        import base64
        l6_62_payload = b"S" * 65537
        l6_63_payload = b"Z" * 260
        snappy_vectors = {
            "overlap": base64.b64encode(snappy_compress(b"ABC" * 50)).decode("ascii"),
            "copy4": base64.b64encode(_snappy_copy4_stream(b"WXYZ", 4, 12)).decode("ascii"),
            "l6_62": base64.b64encode(_snappy_literal_with_l6(l6_62_payload, 62)).decode("ascii"),
            "l6_63": base64.b64encode(_snappy_literal_with_l6(l6_63_payload, 63)).decode("ascii"),
            "bad_empty": base64.b64encode(b"").decode("ascii"),
            "bad_zero_offset": base64.b64encode(b"\x05\x00A\x01\x00").decode("ascii"),
            "bad_oob_offset": base64.b64encode(b"\x05\x00A\x01\x05").decode("ascii"),
            "bad_len_mismatch": base64.b64encode(b"\x04\x00A").decode("ascii"),
        }

        # --- Synthetic NeDB bytes ---
        nedb_bytes = (
            b"\xef\xbb\xbf"
            b'{"_id":"a1","name":"First"}\r\n'
            b"\n   \r\n"
            b'{"_id":"a1","name":"Updated"}\n'
            b'{"_id":"a2","name":"Gone"}\r\n'
            b'{"$$deleted":true,"_id":"a2"}\n'
            b'{"$$deleted":true}\n'
            b"{broken_json\n"
            b'["array_not_dict"]\n'
            b'{"_id":"bad_utf8","raw":"\xff\xfe"}\n'
            b'{"_id":"a3","name":"Survivor"}\n'
        )
        # Replace "\xff\xfe" string escape with actual raw invalid UTF-8 bytes
        nedb_bytes = nedb_bytes.replace(b'"\\xff\\xfe"', b'"\xff\xfe"')

        # --- Synthetic LevelDB edge world (non-empty WAL >32KiB First/Middle/Last, tombstones, kDeletedFile, bit-63 seq, bad UTF-8) ---
        ldb_edge_dir = cls.run_dir / "ldb_edge"
        ldb_edge_dir.mkdir(parents=True, exist_ok=True)
        write_json_file(ldb_edge_dir / "world.json", make_v14_world_json(world_id="ldb_edge", title="LevelDB Edge"))
        edge_data = ldb_edge_dir / "data" / "scenes"
        edge_data.mkdir(parents=True, exist_ok=True)

        # Bit-63 InternalKey tag: seq = (1 << 55) + 50 => (seq << 8) has bit 63 set!
        high_seq = (1 << 55) + 50
        s_deleted_sst = make_v9_scene("s_del_sst", "DeletedInSST")
        s_deleted_wal = make_v9_scene("s_del_wal", "DeletedInWAL")
        s_kept_sst = make_v9_scene("s_kept", "KeptFromSST")
        s_stale_deleted_sst = make_v9_scene("s_stale", "StaleSST")

        # Obsolete SSTable 000005.ldb that MANIFEST marks kDeletedFile
        sst_old, old_min, old_max = build_sstable_bytes([
            (b"!scenes!s_ghost", 1, 1, json.dumps(make_v9_scene("s_ghost", "GhostFromDeletedSST")).encode("utf-8")),
        ])
        (edge_data / "000005.ldb").write_bytes(sst_old)

        # Active SSTable 000008.ldb
        sst_active, act_min, act_max = build_sstable_bytes([
            (b"!scenes!s_kept", high_seq, 1, json.dumps(s_kept_sst).encode("utf-8")),
            (b"!scenes!s_del_sst", 20, 0, b""),  # Put at seq=10, Delete tombstone at seq=20
            (b"!scenes!s_del_sst", 10, 1, json.dumps(s_deleted_sst).encode("utf-8")),
            (b"!scenes!s_del_wal", 15, 1, json.dumps(s_deleted_wal).encode("utf-8")),
            (b"!scenes!s_stale", 5, 1, json.dumps(s_stale_deleted_sst).encode("utf-8")),
            (b"!scenes!\xff\xfe", 30, 1, b'{"_id":"bad"}'),  # Invalid UTF-8 key
            (b"!scenes!bad_val", 31, 1, b'{"_id":"bad_val","n":"\xff"}'),  # Invalid UTF-8 value
        ])
        (edge_data / "000008.ldb").write_bytes(sst_active)

        # Multi-block WAL > 40 KiB (forces kFirstType -> kMiddleType -> kLastType across 32 KiB boundary)
        big_pad = "P" * 42000
        s_wal_big = make_v9_scene("s_wal_big", "BigWALScene")
        s_wal_big["flags"] = {"pad": big_pad}
        wb_big = encode_write_batch(
            high_seq + 100,
            [
                ("put", b"!scenes!s_wal_big", json.dumps(s_wal_big).encode("utf-8")),
                ("delete", b"!scenes!s_del_wal", b""),
            ],
        )
        (edge_data / "000009.log").write_bytes(build_wal_bytes([wb_big]))

        # Build MANIFEST with kNewFile(5), kNewFile(8), kDeletedFile(5)
        edit1 = bytearray()
        edit1.extend(_encode_varint32(2) + _encode_varint32(9))  # kLogNumber = 9
        edit1.extend(_encode_varint32(7) + _encode_varint32(0) + _encode_varint32(5) + _encode_varint32(len(sst_old)) + _encode_varint32(len(old_min)) + old_min + _encode_varint32(len(old_max)) + old_max)
        edit1.extend(_encode_varint32(7) + _encode_varint32(0) + _encode_varint32(8) + _encode_varint32(len(sst_active)) + _encode_varint32(len(act_min)) + act_min + _encode_varint32(len(act_max)) + act_max)
        edit1.extend(_encode_varint32(6) + _encode_varint32(0) + _encode_varint32(5))  # kDeletedFile (0, 5)
        (edge_data / "MANIFEST-000002").write_bytes(build_wal_bytes([bytes(edit1)]))
        (edge_data / "CURRENT").write_bytes(b"MANIFEST-000002\n")

        # Truncated WAL bytes & bad-magic .ldb bytes
        full_wal = build_wal_bytes([encode_write_batch(1, [("put", b"!scenes!x", b'{"_id":"x"}')])])
        truncated_wal = full_wal[:15]
        bad_ldb = b"NOT_AN_SSTABLE" * 5

        # --- Synthetic Normalizer & Error World Cases ---
        world_cases: list[dict] = []

        # Case 1: Character class-level sum + Half Plate + Shield (AC 19) + custom AC + override + foreground + padding/shift + sightAngle=0 + unsafe/gif
        sc_fg = make_v9_scene(
            "sc1",
            "Ship Layout",
            width=3100,
            height=2185,
            grid=51,
            grid_type=1,
            shift_x=23,
            shift_y=45,
            img="worlds/syn/scenes/Side%20View%20(1).png",
            foreground="worlds/syn/scenes/fg.png",
            walls=[
                {"_id": "w1", "c": [0, 0, 100, 0], "door": 0, "ds": 0, "move": 20, "sight": 20, "light": 20, "sense": 20},
                {"_id": "d1", "c": [100, 0, 200, 0], "door": 2, "ds": 0, "move": 20, "sight": 20, "light": 20, "sound": 20},
            ],
            lights=[
                {"_id": "l1", "x": 50, "y": 50, "bright": 20, "dim": 40, "angle": 0, "hidden": False},
            ],
            tiles=[
                make_tile("tl1", "worlds/syn/anim.gif", hidden=True),
            ],
            tokens=[
                make_v9_token("tk1", "Fighter", actor_id="pc_fighter", vision=True, dim_sight=60, sight_angle=0),
                make_v9_token("tk2", "Dangling", actor_id="missing_id", img="user://bad/pic.png"),
            ],
        )
        sc_fg["padding"] = 0.25
        sc_gridless = make_v9_scene("sc2", "Overland", width=2000, height=1500, grid=70, grid_type=0, img="worlds/syn/scenes/Side%20View%20(1).png")
        sc_gridless["padding"] = 0.1

        pc_fighter = make_v9_actor(
            "pc_fighter",
            "Valen",
            actor_type="character",
            abilities={"str": 16, "dex": 16, "con": 14, "int": 10, "wis": 12, "cha": 10},
            ac_flat=None,
            ac_calc="default",
            level=None,
            items=[
                {"_id": "cl1", "name": "Fighter", "type": "class", "system": {"levels": 3}},
                {"_id": "cl2", "name": "Wizard", "type": "class", "data": {"levels": 2}},
                make_armor_item("ar1", "Half Plate", armor_type="medium", armor_value=15, dex_cap=2, equipped=True),
                make_armor_item("ar2", "Shield", armor_type="shield", armor_value=2, dex_cap=None, equipped=True),
                make_armor_item("ar3", "Plate", armor_type="heavy", armor_value=18, dex_cap=0, equipped=False),
            ],
        )
        npc_custom = make_v9_actor(
            "npc_custom",
            "Bone Guard",
            actor_type="npc",
            abilities={"str": 12, "dex": 14, "con": 12, "int": 6, "wis": 8, "cha": 5},
            ac_flat=99,
            ac_calc="custom",
            cr="1/4",
            biography="<p>Guarded by <b>magic</b> &amp; steel.</p>",
        )
        npc_custom["data"]["attributes"]["ac"]["formula"] = "@attributes.ac.armor + @attributes.ac.dex + 1"

        npc_override = make_v9_actor(
            "npc_override",
            "Iron Golem",
            actor_type="npc",
            ac_flat=10,
            ac_calc="default",
        )
        npc_override["data"]["attributes"]["ac"]["override"] = 21

        npc_bad_formula = make_v9_actor(
            "npc_bad_formula",
            "Motionless",
            actor_type="npc",
            abilities={"str": 10, "dex": 12, "con": 10, "int": 10, "wis": 10, "cha": 10},
            ac_flat=99,
            ac_calc="custom",
        )
        npc_bad_formula["data"]["attributes"]["ac"]["formula"] = "19 while motionless"

        npc_neg_dex_plus = make_v9_actor(
            "npc_neg_dex_plus",
            "Clumsy Guard",
            actor_type="npc",
            abilities={"str": 10, "dex": 8, "con": 10, "int": 10, "wis": 10, "cha": 10},
            ac_flat=99,
            ac_calc="custom",
        )
        npc_neg_dex_plus["data"]["attributes"]["ac"]["formula"] = "@attributes.ac.armor + @attributes.ac.dex + 1"

        npc_neg_dex_minus = make_v9_actor(
            "npc_neg_dex_minus",
            "Inverse Guard",
            actor_type="npc",
            abilities={"str": 10, "dex": 8, "con": 10, "int": 10, "wis": 10, "cha": 10},
            ac_flat=99,
            ac_calc="custom",
        )
        npc_neg_dex_minus["data"]["attributes"]["ac"]["formula"] = "10 - @attributes.ac.dex"

        syn_dir = fixtures_dir / "syn_world"
        syn_wj = build_v9_world(
            syn_dir,
            world_json=make_v9_world_json(name="syn", title="Synthetic World"),
            scenes=[sc_fg, sc_gridless],
            actors=[pc_fighter, npc_custom, npc_override, npc_bad_formula, npc_neg_dex_plus, npc_neg_dex_minus],
            folders=[
                make_folder("f1", "Root"),
                make_folder("f2", "Sub", parent="f1"),
                make_folder("fcyc1", "CycA", parent="fcyc2"),
                make_folder("fcyc2", "CycB", parent="fcyc1"),
            ],
            assets={
                "scenes/Side View (1).png": png,
                "scenes/fg.png": png,
                "anim.gif": b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            },
        )
        world_cases.append({"id": "syn_all", "path": str(syn_wj), "options": {}})
        world_cases.append({
            "id": "syn_no_chars",
            "path": str(syn_wj),
            "options": {"import_characters": False, "import_monsters": True, "include_hidden": False},
        })

        # Case 2: LevelDB priority over stale .db + v14 foreground dict
        v14_prio_dir = fixtures_dir / "v14_prio"
        sc_v14 = make_v9_scene("s1", "LevelDB Scene", img="worlds/p/bg.png", foreground="worlds/p/fg.png")
        v14_prio_wj = build_v14_world(
            v14_prio_dir,
            world_json=make_v14_world_json(world_id="p", title="Prio Test"),
            scenes=[sc_v14],
            actors=[make_v9_actor("a1", "Goblin", actor_type="npc")],
            folders=[make_folder("fl1", "LdbFolder")],
            assets={"bg.png": png, "fg.png": png},
            also_nedb=True,
        )
        # Overwrite scenes.db with 2 stale scenes to prove LevelDB wins
        write_nedb_file(
            v14_prio_dir / "data" / "scenes.db",
            [make_v9_scene("stale1", "Stale1"), make_v9_scene("stale2", "Stale2")],
        )
        world_cases.append({"id": "v14_prio", "path": str(v14_prio_wj), "options": {}})

        # Case 3: Error cases
        corrupt_zip = fixtures_dir / "corrupt.zip"
        corrupt_zip.write_bytes(b"PK\x03\x04CORRUPT_ZIP_PAYLOAD")
        world_cases.append({"id": "err_corrupt_zip", "path": str(corrupt_zip), "options": {}})

        gateway_json = fixtures_dir / "gateway.json"
        write_json_file(gateway_json, {"gateway": "https://example.invalid"})
        world_cases.append({"id": "err_gateway_json", "path": str(gateway_json), "options": {}})

        not_fvtt_wj = fixtures_dir / "bad_wj" / "world.json"
        write_json_file(not_fvtt_wj, {"hello": "world"})
        world_cases.append({"id": "err_not_fvtt_wj", "path": str(not_fvtt_wj), "options": {}})

        depth2_zip = pack_world_zip(syn_dir, fixtures_dir / "depth2.zip", depth=2, root_name="a/b")
        world_cases.append({"id": "err_depth2_zip", "path": str(depth2_zip), "options": {}})

        multi_zip = fixtures_dir / "multi_root.zip"
        with zipfile.ZipFile(multi_zip, "w") as zf:
            zf.writestr("w1/world.json", json.dumps(make_v9_world_json(name="w1")))
            zf.writestr("w2/world.json", json.dumps(make_v9_world_json(name="w2")))
        world_cases.append({"id": "err_multi_zip", "path": str(multi_zip), "options": {}})

        no_data_wj = fixtures_dir / "no_data" / "world.json"
        write_json_file(no_data_wj, make_v9_world_json(name="empty", title="No Data"))
        world_cases.append({"id": "err_no_data", "path": str(no_data_wj), "options": {}})

        # Case 4: Real bgdia dir and zip (optional if present in env)
        cls.bgdia_dir_wj = resolve_bgdia_dir_world_json(workspace_root=_WORKSPACE_ROOT)
        cls.bgdia_zip = resolve_bgdia_zip_path(workspace_root=_WORKSPACE_ROOT)
        if cls.bgdia_dir_wj is not None and cls.bgdia_dir_wj.is_file():
            world_cases.append({"id": "bgdia_dir_default", "path": str(cls.bgdia_dir_wj), "options": {}})
            world_cases.append({
                "id": "bgdia_dir_filtered",
                "path": str(cls.bgdia_dir_wj),
                "options": {
                    "import_scenes": False,
                    "import_characters": False,
                    "import_monsters": False,
                    "include_hidden": False,
                    "download_remote_assets": False,
                },
            })
        if cls.bgdia_zip is not None and cls.bgdia_zip.is_file():
            world_cases.append({"id": "bgdia_zip_default", "path": str(cls.bgdia_zip), "options": {}})

        # --- Iteration 2 & 3 Regression Fixtures ---
        nedb_reinsert_bytes = (
            b'{"_id":"re1","v":1}\n'
            b'{"$$deleted":true,"_id":"re1"}\n'
            b'{"_id":"re1","v":2}\n'
        )
        nedb_deleted_null_false_bytes = (
            b'{"_id":"k1","v":1,"$$deleted":null}\n'
            b'{"_id":"k2","v":2,"$$deleted":"false"}\n'
        )
        nedb_deleted_mixed_bytes = (
            b'{"_id":"k1","v":1,"$$deleted":null}\n'
            b'{"_id":"k2","v":2,"$$deleted":"false"}\n'
            b'{"_id":"k3","v":3}\n'
            b'{"$$deleted":true,"_id":"k3"}\n'
        )
        nedb_deleted_numeric_bytes = (
            b'{"_id":"k_del1","v":10}\n'
            b'{"_id":"k_del1","$$deleted":1}\n'
            b'{"_id":"k_zero","v":20,"$$deleted":0}\n'
            b'{"_id":"k_two","v":30,"$$deleted":2}\n'
            b'{"_id":"k_frac","v":40,"$$deleted":1.5}\n'
            b'{"_id":"k_null","v":50,"$$deleted":null}\n'
            b'{"_id":"k_strfalse","v":60,"$$deleted":"false"}\n'
            b'{"_id":"k_true","v":70}\n'
            b'{"_id":"k_true","$$deleted":true}\n'
        )

        # SSTable footer index_offset = 0x7FFFFFFFFFFFFFF0, index_size = 30
        huge_u64 = 0x7FFFFFFFFFFFFFF0
        footer_handles = b"\x00\x00" + _encode_varint64(huge_u64) + _encode_varint64(30)
        footer_handles_padded = footer_handles.ljust(40, b"\x00")
        sst_idx_overflow = b"\x00" * 16 + footer_handles_padded + struct.pack("<Q", 0xDB4775248B80FB57)

        # SSTable data block with non_shared = 0x7FFFFFFFFFFFFFF0
        bad_data_blk = _encode_varint64(0) + _encode_varint64(huge_u64) + _encode_varint64(1) + b"x" + struct.pack("<II", 0, 1)
        bad_data_framed = bad_data_blk + b"\x00" + struct.pack("<I", leveldb_masked_crc32c(bad_data_blk + b"\x00"))
        idx_handle_val = _encode_varint64(0) + _encode_varint64(len(bad_data_blk))
        idx_blk = _encode_varint64(0) + _encode_varint64(1) + _encode_varint64(len(idx_handle_val)) + b"k" + idx_handle_val + struct.pack("<II", 0, 1)
        idx_off = len(bad_data_framed)
        idx_framed = idx_blk + b"\x00" + struct.pack("<I", leveldb_masked_crc32c(idx_blk + b"\x00"))
        blk_ns_footer = (b"\x00\x00" + _encode_varint64(idx_off) + _encode_varint64(len(idx_blk))).ljust(40, b"\x00") + struct.pack("<Q", 0xDB4775248B80FB57)
        sst_blk_ns_overflow = bad_data_framed + idx_framed + blk_ns_footer

        # WriteBatch with klen = 0x7FFFFFFFFFFFFFF0
        wb_klen_overflow = struct.pack("<QI", 1, 1) + b"\x01" + _encode_varint64(huge_u64)
        wal_ovf_dir = fixtures_dir / "wal_ovf_world"
        wal_ovf_dir.mkdir(parents=True, exist_ok=True)
        write_json_file(wal_ovf_dir / "world.json", make_v14_world_json(world_id="wal_ovf", title="WAL OVF"))
        wal_ovf_data = wal_ovf_dir / "data" / "scenes"
        wal_ovf_data.mkdir(parents=True, exist_ok=True)
        (wal_ovf_data / "000001.log").write_bytes(build_wal_bytes([wb_klen_overflow]))

        # Depth-0 world.json ZIP + subdir listing + nested subdir non-shadowing
        depth0_zip = fixtures_dir / "depth0_shadow.zip"
        with zipfile.ZipFile(depth0_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("world.json", json.dumps(make_v9_world_json(name="d0", title="Depth0")))
            zf.writestr("data/scenes.db", json.dumps(make_v9_scene("sc_d0", "Depth0 Scene")) + "\n")
            zf.writestr("data/scenes/backup/000001.ldb", b"SHADOW_IGNORED")
            zf.writestr("assets/maps/bg.png", png)

        # Iteration 20 NeDB $$indexCreated/$$indexRemoved & anonymous namespace isolation fixtures
        nedb_index_directives_bytes = (
            b'{"$$indexCreated":{"fieldName":"_id","unique":true,"sparse":false}}\n'
            b'{"_id":"s1","name":"Real Tavern"}\n'
            b'{"$$indexRemoved":"sort"}\n'
        )
        nedb_anon_both_bytes = (
            b'{"name":"AnonLine1","type":"npc"}\n'
            b'{"_id":"__anon_1","name":"ExplicitAnon1","type":"npc"}\n'
            b'{"_id":"anon:1","name":"ExplicitColon1","type":"npc"}\n'
        )
        nedb_anon_tombstone_bytes = (
            b'{"name":"AnonLine1","type":"npc"}\n'
            b'{"_id":"__anon_1","name":"ExplicitAnon1","type":"npc"}\n'
            b'{"$$deleted":true,"_id":"__anon_1"}\n'
        )
        nedb_idx_world_dir = fixtures_dir / "nedb_idx_world"
        nedb_idx_world_wj = build_v9_world(
            nedb_idx_world_dir,
            world_json=make_v9_world_json(name="nidx", title="NeDB Index World"),
            scenes=[],
            actors=[],
        )
        (nedb_idx_world_dir / "data" / "scenes.db").write_text(
            "\n".join([
                json.dumps({"$$indexCreated": {"fieldName": "_id", "unique": True}}),
                json.dumps(make_v9_scene("s1", "Real Tavern")),
                json.dumps({"$$indexRemoved": "sort"}),
            ]) + "\n",
            encoding="utf-8",
        )
        (nedb_idx_world_dir / "data" / "actors.db").write_text(
            "\n".join([
                json.dumps({"$$indexCreated": {"fieldName": "folder"}}),
                json.dumps(make_v9_actor("a1", "Goblin", actor_type="npc")),
                json.dumps({"$$indexRemoved": "type"}),
            ]) + "\n",
            encoding="utf-8",
        )
        world_cases.append({"id": "nedb_index_world", "path": str(nedb_idx_world_wj), "options": {}})

        probe_cfg = {
            "snappy_vectors": snappy_vectors,
            "nedb_bytes_b64": base64.b64encode(nedb_bytes).decode("ascii"),
            "nedb_reinsert_b64": base64.b64encode(nedb_reinsert_bytes).decode("ascii"),
            "nedb_deleted_null_false_b64": base64.b64encode(nedb_deleted_null_false_bytes).decode("ascii"),
            "nedb_deleted_mixed_b64": base64.b64encode(nedb_deleted_mixed_bytes).decode("ascii"),
            "nedb_deleted_numeric_b64": base64.b64encode(nedb_deleted_numeric_bytes).decode("ascii"),
            "nedb_index_directives_b64": base64.b64encode(nedb_index_directives_bytes).decode("ascii"),
            "nedb_anon_both_b64": base64.b64encode(nedb_anon_both_bytes).decode("ascii"),
            "nedb_anon_tombstone_b64": base64.b64encode(nedb_anon_tombstone_bytes).decode("ascii"),
            "sst_idx_overflow_b64": base64.b64encode(sst_idx_overflow).decode("ascii"),
            "sst_blk_ns_overflow_b64": base64.b64encode(sst_blk_ns_overflow).decode("ascii"),
            "wal_wb_klen_overflow_b64": base64.b64encode(wb_klen_overflow).decode("ascii"),
            "wal_overflow_world": str(wal_ovf_dir / "world.json"),
            "depth0_zip_path": str(depth0_zip),
            "leveldb_edge_world": str(ldb_edge_dir / "world.json"),
            "truncated_wal_b64": base64.b64encode(truncated_wal).decode("ascii"),
            "bad_ldb_b64": base64.b64encode(bad_ldb).decode("ascii"),
            "world_cases": world_cases,
        }
        cfg_path = cls.run_dir / "probe_cfg.json"
        out_path = cls.run_dir / "probe_out.json"
        write_json_file(cfg_path, probe_cfg)

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
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log_text = godot_log.read_text(encoding="utf-8", errors="replace") if godot_log.is_file() else ""
        log_errors = analyze_godot_logs(log_text, proc.stdout, proc.stderr)
        if proc.returncode != 0 or log_errors:
            redacted = redact_bgdia_path(
                f"rc={proc.returncode} errors={log_errors}\nstdout={proc.stdout[-800:]}\nstderr={proc.stderr[-800:]}",
                bgdia_dir_world_json=cls.bgdia_dir_wj,
                bgdia_zip_path=cls.bgdia_zip,
            )
            raise AssertionError(f"Headless Godot probe failed or emitted ERROR logs:\n{redacted}")

        if not out_path.is_file():
            raise AssertionError("Probe did not write output JSON")
        cls.batch_results = json.loads(out_path.read_text(encoding="utf-8"))
        if not cls.batch_results.get("ok"):
            raise AssertionError(f"Probe returned failure: {cls.batch_results}")

    @classmethod
    def tearDownClass(cls) -> None:
        run_dir = getattr(cls, "run_dir", None)
        if run_dir is not None and run_dir.exists():
            for _ in range(5):
                shutil.rmtree(run_dir, ignore_errors=True)
                if not run_dir.exists():
                    break
                time.sleep(0.05)

    def test_snappy_copy4_l6_62_63_overlap_and_errors(self) -> None:
        import hashlib
        sn = self.batch_results["snappy"]
        self.assertTrue(sn["overlap"]["ok"])
        self.assertEqual(sn["overlap"]["sha256"], hashlib.sha256(b"ABC" * 50).hexdigest())

        self.assertTrue(sn["copy4"]["ok"])
        self.assertEqual(sn["copy4"]["sha256"], hashlib.sha256(b"WXYZ" * 4).hexdigest())

        self.assertTrue(sn["l6_62"]["ok"])
        self.assertEqual(sn["l6_62"]["len"], 65537)
        self.assertEqual(sn["l6_62"]["sha256"], hashlib.sha256(b"S" * 65537).hexdigest())

        self.assertTrue(sn["l6_63"]["ok"])
        self.assertEqual(sn["l6_63"]["len"], 260)
        self.assertEqual(sn["l6_63"]["sha256"], hashlib.sha256(b"Z" * 260).hexdigest())

        self.assertFalse(sn["bad_empty"]["ok"])
        self.assertFalse(sn["bad_zero_offset"]["ok"])
        self.assertFalse(sn["bad_oob_offset"]["ok"])
        self.assertFalse(sn["bad_len_mismatch"]["ok"])
        self.assertFalse(sn["limit_reject"]["ok"])

    def test_nedb_bom_tombstones_last_write_wins_and_bad_lines(self) -> None:
        nd = self.batch_results["nedb"]
        self.assertTrue(nd["ok"])
        self.assertEqual(nd["deleted_count"], 2)
        self.assertEqual(nd["parse_errors"], 3)
        docs = {d["_id"]: d["name"] for d in nd["docs"]}
        self.assertEqual(docs, {"a1": "Updated", "a3": "Survivor"})

    def test_leveldb_wal_multiblock_tombstones_deleted_file_bit63_and_bad_utf8(self) -> None:
        le = self.batch_results["leveldb_edge"]
        self.assertTrue(le["open_ok"])
        self.assertTrue(le["col_ok"])
        ids = sorted(d["_id"] for d in le["docs"])
        self.assertEqual(ids, ["s_kept", "s_stale", "s_wal_big"])
        self.assertEqual(le["parse_errors"], 2)  # 1 bad UTF-8 key + 1 bad UTF-8 value
        self.assertEqual(le["trunc_wal_records"], 0)
        self.assertEqual(le["trunc_wal_errors"], 1)
        self.assertFalse(le["bad_ldb"]["ok"])

    def test_synthetic_normalizer_ac_levels_coords_assets_and_filtering(self) -> None:
        syn = self.batch_results["worlds"]["syn_all"]
        self.assertTrue(syn["ok"], syn)
        self.assertEqual(syn["scenes_count"], 2)
        self.assertEqual(syn["actors_count"], 6)

        actors = {a["name"]: a for a in syn["actors"]}
        self.assertEqual(actors["Valen"]["actor_type"], "character")
        self.assertEqual(actors["Valen"]["cr_or_level"], 5.0)
        self.assertEqual(actors["Valen"]["ac"], 19)  # Half Plate (15) + capped dex (+2) + Shield (2)
        self.assertEqual(actors["Bone Guard"]["ac"], 13)  # 10 + dex (+2) + 1
        self.assertEqual(actors["Bone Guard"]["cr_or_level"], 0.25)
        self.assertEqual(actors["Iron Golem"]["ac"], 21)  # ac.override
        self.assertEqual(actors["Motionless"]["ac"], 11)  # unparseable custom fallback to 10 + dex(+1)
        self.assertEqual(actors["Clumsy Guard"]["ac"], 10)  # 10 + (-1) + 1 == 10
        self.assertEqual(actors["Inverse Guard"]["ac"], 11)  # 10 - (-1) == 11

        sc1 = syn["scenes"][0]
        self.assertAlmostEqual(sc1["scene_x"], 839.0, places=2)
        self.assertAlmostEqual(sc1["scene_y"], 606.0, places=2)
        self.assertEqual(sc1["background_ref"], "scenes/Side View (1).png")
        self.assertEqual(sc1["foreground_ref"], "scenes/fg.png")
        self.assertEqual(sc1["lights_data"][0]["angle"], 360.0)
        self.assertEqual(sc1["tokens_data"][0]["sight_angle"], 360.0)
        self.assertEqual(sc1["tokens_data"][1]["actor_missing"], True)

        ic = syn["inspect_counts"]
        self.assertEqual(ic["maps"], 2)
        self.assertEqual(ic["characters"], 1)
        self.assertEqual(ic["walls"], 1)
        self.assertEqual(ic["doors"], 1)
        self.assertGreaterEqual(ic["unsupported"], 2)  # .gif + user://

        # Token actor_type must be resolved BEFORE filtering out characters
        no_chars = self.batch_results["worlds"]["syn_no_chars"]
        self.assertTrue(no_chars["ok"])
        self.assertEqual(no_chars["actors_count"], 5)
        self.assertEqual(no_chars["scenes"][0]["token_names"], ["Dangling"])
        self.assertEqual(no_chars["scenes"][0]["tiles"], 0)

    def test_iteration2_regressions(self) -> None:
        reg = self.batch_results["regressions"]

        # 1. NeDB delete-then-reinsert same _id emits strictly 1 doc with updated value
        nr = reg["nedb_reinsert"]
        self.assertTrue(nr["ok"])
        self.assertEqual(nr["deleted_count"], 1)
        self.assertEqual(len(nr["docs"]), 1)
        self.assertEqual(nr["docs"][0]["_id"], "re1")
        self.assertEqual(nr["docs"][0]["v"], 2)

        # 2. LevelDB 0x7FFFFFFFFFFFFFF0 varint64 overflow returns {ok: false} cleanly with 0 Godot errors
        self.assertFalse(reg["sst_idx_overflow"]["ok"])
        self.assertEqual(reg["sst_idx_overflow"]["reason"], "sstable_block_oob")
        self.assertFalse(reg["sst_blk_ns_overflow"]["ok"])
        self.assertEqual(reg["sst_blk_ns_overflow"]["reason"], "block_entry_oob")
        self.assertFalse(reg["wal_wb_klen_overflow"]["ok"])
        self.assertEqual(reg["wal_wb_klen_overflow"]["reason"], "write_batch_key_oob")
        wov = reg["wal_overflow_col"]
        self.assertTrue(wov["open_ok"])
        self.assertTrue(wov["col_ok"])
        self.assertEqual(wov["parse_errors"], 1)
        self.assertTrue(any("write_batch_key_oob" in str(w) for w in wov["warnings"]))

        # 3. Normalizer warnings: null, null-key fallbacks, and rfind(".") dotted parentId
        nn = reg["normalizer_null_and_rfind"]
        self.assertTrue(nn["ok"])
        self.assertEqual(nn["walls_count"], 1)
        self.assertEqual(nn["wall_sense"], 10)
        self.assertAlmostEqual(nn["light"]["bright"], 15.0)
        self.assertAlmostEqual(nn["light"]["dim"], 30.0)
        self.assertAlmostEqual(nn["light"]["angle"], 90.0)
        self.assertEqual(nn["tile_z"], 7)
        self.assertAlmostEqual(nn["token"]["width"], 2.0)
        self.assertAlmostEqual(nn["token"]["height"], 2.0)
        self.assertEqual(nn["token"]["disposition"], 1)
        self.assertEqual(nn["token"]["actor_link"], True)

        # 4. Depth-0 world.json ZIP + list_subdirs + has_collection nested subdir non-shadowing
        d0 = reg["depth0_and_shadow"]
        self.assertTrue(d0["open_ok"])
        self.assertEqual(d0["source_kind"], "zip")
        self.assertEqual(d0["top_subdirs"], ["assets", "data"])
        self.assertEqual(d0["assets_subdirs"], ["assets/maps"])
        self.assertFalse(d0["has_ldb_shadow"])
        self.assertTrue(d0["auto_col_ok"])
        self.assertEqual(len(d0["auto_col_docs"]), 1)
        self.assertEqual(d0["auto_col_docs"][0]["_id"], "sc_d0")

    def test_iteration3_nedb_deleted_variant_and_normalizer_ok_guard(self) -> None:
        reg = self.batch_results["regressions"]

        dnf = reg["nedb_deleted_null_false"]
        self.assertTrue(dnf["ok"])
        self.assertEqual(dnf["deleted_count"], 0)
        self.assertEqual(dnf["parse_errors"], 0)
        self.assertEqual(len(dnf["docs"]), 2)
        self.assertEqual({d["_id"]: d["v"] for d in dnf["docs"]}, {"k1": 1, "k2": 2})

        dmx = reg["nedb_deleted_mixed"]
        self.assertTrue(dmx["ok"])
        self.assertEqual(dmx["deleted_count"], 1)
        self.assertEqual(dmx["parse_errors"], 0)
        self.assertEqual(len(dmx["docs"]), 2)
        self.assertEqual({d["_id"]: d["v"] for d in dmx["docs"]}, {"k1": 1, "k2": 2})

        nok = reg["normalizer_null_ok_guard"]
        self.assertFalse(nok["ok"])
        self.assertEqual(nok["reason"], "missing_required_collections")

    def test_iteration4_variant_int64_bool_and_nedb_float_regressions(self) -> None:
        reg = self.batch_results["regressions"]

        # 1. normalize() with null / non-Dictionary world_json, collections, options
        self.assertFalse(reg["iter4_norm_null_wj"]["ok"])
        self.assertEqual(reg["iter4_norm_null_wj"]["reason"], "invalid_world_json")
        self.assertFalse(reg["iter4_norm_int_wj"]["ok"])
        self.assertEqual(reg["iter4_norm_int_wj"]["reason"], "invalid_world_json")
        self.assertFalse(reg["iter4_norm_null_cols"]["ok"])
        self.assertEqual(reg["iter4_norm_null_cols"]["reason"], "missing_required_collections")
        self.assertFalse(reg["iter4_norm_arr_cols"]["ok"])
        self.assertEqual(reg["iter4_norm_arr_cols"]["reason"], "missing_required_collections")
        self.assertTrue(reg["iter4_norm_null_opts_ok"])
        self.assertTrue(reg["iter4_norm_str_opts_ok"])

        # 2. >64-bit integer string guards in _to_int, _eval_simple_int_expr, _parse_file_number, and normalizer
        self.assertEqual(reg["iter4_to_int_huge"], -77)
        self.assertEqual(reg["iter4_to_int_over_max"], -77)
        self.assertEqual(reg["iter4_to_int_under_min"], -77)
        self.assertEqual(reg["iter4_to_int_exact_max"], "9223372036854775807")
        self.assertEqual(reg["iter4_to_int_exact_min"], "-9223372036854775808")
        self.assertEqual(reg["iter4_to_int_sci_huge"], -77)
        self.assertIsNone(reg["iter4_expr_huge"])
        self.assertIsNone(reg["iter4_expr_add_ovf"])
        self.assertEqual(reg["iter4_expr_valid_min"], "-9223372036854775807")
        self.assertEqual(reg["iter4_ldb_fnum_huge"], -1)
        self.assertTrue(reg["iter4_huge_actor_ok"])
        self.assertEqual(reg["iter4_huge_actor_ac"], 12)  # fallback 10 + dex(+2)
        self.assertEqual(reg["iter4_huge_actor_hp_max"], 0)
        self.assertEqual(reg["iter4_huge_actor_hp_temp"], 0)

        # 3. _register_asset with mock source returning null unsafe/exists/kind/rel_path
        self.assertTrue(reg["iter4_weird_src1_ok"])
        wa1 = reg["iter4_weird_src1_asset"]
        self.assertEqual(wa1["unsafe"], False)
        self.assertEqual(wa1["external_or_missing"], True)
        self.assertTrue(reg["iter4_weird_src2_ok"])
        self.assertEqual(reg["iter4_weird_src2_assets_size"], 0)

        # 4. fvtt_nedb $$deleted numeric 1 (decoded as JSON float 1.0) vs 0/2/1.5/null/"false"/true/NaN/Inf
        ndn = reg["iter4_nedb_deleted_numeric"]
        self.assertTrue(ndn["ok"])
        self.assertEqual(ndn["deleted_count"], 2)
        self.assertEqual(ndn["parse_errors"], 0)
        self.assertEqual(
            {d["_id"]: d["v"] for d in ndn["docs"]},
            {"k_zero": 20, "k_two": 30, "k_frac": 40, "k_null": 50, "k_strfalse": 60},
        )
        self.assertFalse(reg["iter4_nedb_truthy_nan"])
        self.assertFalse(reg["iter4_nedb_truthy_inf"])
        self.assertTrue(reg["iter4_nedb_truthy_int1"])
        self.assertTrue(reg["iter4_nedb_truthy_float1"])
        self.assertFalse(reg["iter4_nedb_truthy_float15"])

    def test_leveldb_priority_over_stale_nedb(self) -> None:
        prio = self.batch_results["worlds"]["v14_prio"]
        self.assertTrue(prio["ok"])
        self.assertEqual(prio["scenes_count"], 1)
        self.assertEqual(prio["scenes"][0]["name"], "LevelDB Scene")
        self.assertEqual(prio["scenes"][0]["foreground_ref"], "fg.png")
        self.assertEqual(prio["folders_count"], 1)

    def test_error_cases(self) -> None:
        worlds = self.batch_results["worlds"]
        for err_id in ("err_corrupt_zip", "err_gateway_json", "err_not_fvtt_wj", "err_depth2_zip", "err_multi_zip", "err_no_data"):
            self.assertFalse(worlds[err_id]["ok"], f"Expected failure for {err_id}, got {worlds[err_id]}")
            self.assertTrue(bool(worlds[err_id]["reason"]), f"Expected non-empty reason for {err_id}")

    def test_bgdia_unpacked_v14_dir(self) -> None:
        if self.bgdia_dir_wj is None or not self.bgdia_dir_wj.is_file():
            self.skipTest("Unpacked bgdia world.json not found in environment")
        res = self.batch_results["worlds"]["bgdia_dir_default"]
        self.assertTrue(res["ok"], redact_bgdia_path(str(res), bgdia_dir_world_json=self.bgdia_dir_wj))
        self.assertEqual(res["source_kind"], "dir")
        self.assertEqual(res["world_meta"]["id"], "bgdia")
        self.assertEqual(res["scenes_count"], 31)
        self.assertEqual(res["actors_count"], 229)
        self.assertEqual(res["folders_count"], 62)
        self.assertEqual(res["dangling_tokens_total"], 5)

        ic = res["inspect_counts"]
        self.assertEqual(ic["maps"], 31)
        self.assertEqual(ic["walls"], 3734)
        self.assertEqual(ic["doors"], 123)
        self.assertGreaterEqual(ic["hidden"], 577)
        self.assertEqual(ic["unsupported"], 0)
        self.assertEqual(ic["images"], 1178)
        self.assertEqual(res["remote_assets_count"], 217)

        self.assertEqual(sum(s["lights"] for s in res["scenes"]), 131)
        self.assertEqual(sum(s["tiles"] for s in res["scenes"]), 227)
        self.assertEqual(sum(s["tokens"] for s in res["scenes"]), 618)

        actors = {a["name"]: a for a in res["actors"]}
        expected_ac = {
            "Fist of Bane": 18,
            "Skeleton": 13,
            "Arkhan the Cruel": 22,
            "Scavenger": 20,
            "Horned Devil": 18,
            "Demon Grinder": 19,
            "Devil's Ride": 23,
            "Tormentor": 21,
            "Golden Doom": 19,
        }
        for aname, ac_val in expected_ac.items():
            self.assertIn(aname, actors)
            self.assertEqual(actors[aname]["ac"], ac_val, f"AC mismatch for {aname}")

        vehicles = [a["name"] for a in res["actors"] if a["sub_type"] == "vehicle"]
        self.assertEqual(len(vehicles), 5)

        # Filtered options preserve pre-filter counts while zeroing active selection counts
        flt = self.batch_results["worlds"]["bgdia_dir_filtered"]
        self.assertTrue(flt["ok"])
        self.assertEqual(flt["inspect_counts"]["walls"], 3734)
        self.assertEqual(flt["inspect_counts"]["doors"], 123)
        self.assertEqual(flt["inspect_counts"]["images"], 1178)
        self.assertEqual(flt["inspect_counts"]["maps"], 0)
        self.assertEqual(flt["inspect_counts"]["characters"], 0)
        self.assertEqual(flt["inspect_counts"]["objects"], 0)
        self.assertEqual(flt["inspect_counts"]["selected_images"], 0)
        self.assertEqual(flt["remote_assets_count"], 0)

    def test_bgdia_zip_v9_and_strict_parity_with_unpacked(self) -> None:
        if self.bgdia_zip is None or not self.bgdia_zip.is_file():
            self.skipTest("bgdia .zip archive not found in environment")
        zres = self.batch_results["worlds"]["bgdia_zip_default"]
        self.assertTrue(zres["ok"], redact_bgdia_path(str(zres), bgdia_zip_path=self.bgdia_zip))
        self.assertEqual(zres["source_kind"], "zip")
        self.assertEqual(zres["scenes_count"], 31)
        self.assertEqual(zres["actors_count"], 229)
        self.assertEqual(zres["folders_count"], 53)
        self.assertEqual(zres["dangling_tokens_total"], 2)
        self.assertEqual(zres["inspect_counts"]["walls"], 3734)
        self.assertEqual(zres["inspect_counts"]["doors"], 123)
        self.assertEqual(sum(s["lights"] for s in zres["scenes"]), 131)
        self.assertEqual(sum(s["tiles"] for s in zres["scenes"]), 227)
        self.assertEqual(sum(s["tokens"] for s in zres["scenes"]), 618)

        if self.bgdia_dir_wj is None or not self.bgdia_dir_wj.is_file():
            return
        dres = self.batch_results["worlds"]["bgdia_dir_default"]

        d_actors = {a["id"]: a for a in dres["actors"]}
        z_actors = {a["id"]: a for a in zres["actors"]}
        self.assertEqual(set(d_actors.keys()), set(z_actors.keys()))
        ac_diffs = [
            (aid, d_actors[aid]["name"], d_actors[aid]["ac"], z_actors[aid]["ac"])
            for aid in d_actors
            if d_actors[aid]["ac"] != z_actors[aid]["ac"]
        ]
        self.assertEqual(ac_diffs, [], f"Actor AC parity mismatches: {ac_diffs}")

        d_scenes = {s["id"]: s for s in dres["scenes"]}
        z_scenes = {s["id"]: s for s in zres["scenes"]}
        self.assertEqual(set(d_scenes.keys()), set(z_scenes.keys()))
        for sid in d_scenes:
            ds, zs = d_scenes[sid], z_scenes[sid]
            for fld in ("name", "grid_size", "grid_type", "walls", "doors", "lights", "tiles", "tokens", "background_ref"):
                self.assertEqual(ds[fld], zs[fld], f"Scene {sid} ({ds['name']}) mismatch on {fld}")

    def test_nedb_index_directives_and_anon_namespace_isolation(self) -> None:
        reg = self.batch_results["regressions"]

        nid = reg["nedb_index_directives_b64"]
        self.assertTrue(nid["ok"])
        self.assertEqual(nid["parse_errors"], 0)
        self.assertEqual(nid["deleted_count"], 0)
        self.assertEqual(nid["warnings"], [])
        self.assertEqual(nid["docs"], [{"_id": "s1", "name": "Real Tavern"}])

        nw = self.batch_results["worlds"]["nedb_index_world"]
        self.assertTrue(nw["ok"], nw)
        self.assertEqual(nw["scenes_count"], 1)
        self.assertEqual(nw["actors_count"], 1)
        self.assertEqual(nw["scenes"][0]["name"], "Real Tavern")
        self.assertEqual(nw["actors"][0]["name"], "Goblin")
        self.assertEqual(nw["inspect_counts"]["maps"], 1)
        self.assertEqual(nw["inspect_counts"]["objects"], 1)
        self.assertEqual(nw["inspect_counts"]["records"], 2)

        nab = reg["nedb_anon_both_b64"]
        self.assertTrue(nab["ok"])
        self.assertEqual(nab["parse_errors"], 0)
        self.assertEqual([d["name"] for d in nab["docs"]], ["AnonLine1", "ExplicitAnon1", "ExplicitColon1"])

        nat = reg["nedb_anon_tombstone_b64"]
        self.assertTrue(nat["ok"])
        self.assertEqual(nat["deleted_count"], 1)
        self.assertEqual(nat["parse_errors"], 0)
        self.assertEqual(len(nat["docs"]), 1)
        self.assertEqual(nat["docs"][0]["name"], "AnonLine1")


if __name__ == "__main__":
    unittest.main()
