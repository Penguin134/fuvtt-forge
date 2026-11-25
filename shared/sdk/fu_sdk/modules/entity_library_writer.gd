extends RefCounted
## Fu vtt SDK v1.2.0 — Generalized Entity Library Writer
##
## Safely registers reusable folder / unit / preset templates into the Practice
## host `<root>/entity-library/` directory via `SharedAssetStore.cs`, with
## strict 4-gate destination checks, deterministic 32-hex UIDs, `.revision`
## chaining, `AdoptLibraryAsset`, and atomic rollback on cancel or abort.

const _SHARED_ASSET_STORE_PATH: String = "res://services/storage/SharedAssetStore.cs"
const _COMP_VISUAL_SCRIPT: String = "res://scenes/entities/components/comp_visual.gd"
const _COMP_PERMISSION_SCRIPT: String = "res://scenes/entities/components/comp_permission.gd"
const _COMP_UNIT_SCRIPT: String = "res://scenes/entities/components/comp_unit.gd"
const _COMP_SIMPLE_VISION_SCRIPT: String = "res://modules/simple_fog/comp_simple_vision.gd"
const _MIN_FOOTPRINT_RADIUS: float = 0.5
const _MAX_FOOTPRINT_RADIUS: float = 4096.0
const _MIN_ENTITY_SIZE: Vector2 = Vector2(4.0, 4.0)
const _DEFAULT_FALLBACK_COLOR: Color = Color(0.84, 0.87, 0.92, 1.0)
const _ALLOWED_ASSET_EXTS: Array[String] = ["png", "jpg", "jpeg", "webp", "bmp"]

var _shared_asset_store: Variant = null
var _allow_mock_store: bool = false
var _store_explicitly_set: bool = false
var _last_lib_rollback: Dictionary = {}


func set_shared_asset_store(store: Variant, allow_mock: bool = false) -> void:
	_shared_asset_store = store
	_allow_mock_store = allow_mock
	_store_explicitly_set = true


func _resolve_shared_asset_store() -> Variant:
	if _shared_asset_store != null:
		if ResourceLoader.exists(_SHARED_ASSET_STORE_PATH) or _allow_mock_store:
			return _shared_asset_store
		return null
	if _store_explicitly_set:
		return null
	if ResourceLoader.exists(_SHARED_ASSET_STORE_PATH):
		var store_res: Variant = load(_SHARED_ASSET_STORE_PATH)
		if store_res is Script and (store_res as Script).can_instantiate():
			_shared_asset_store = (store_res as Script).new()
			return _shared_asset_store
	return null


func _is_cancelled(session: RefCounted) -> bool:
	if session != null and session.has_method("is_cancelled"):
		return bool(session.is_cancelled())
	return false


func _warn(session: RefCounted, msg: String) -> void:
	if session != null and session.has_method("add_warning"):
		session.add_warning(msg)


func _parse_json_dict(raw: Variant) -> Dictionary:
	if raw is Dictionary:
		return raw as Dictionary
	if raw is String:
		var j := JSON.new()
		if j.parse(raw as String) == OK and j.data is Dictionary:
			return j.data as Dictionary
	return {}


func _normalize_abs_dir(raw_path: String) -> String:
	var p: String = raw_path.strip_edges().replace("\\", "/").simplify_path()
	while p.length() > 1 and p.ends_with("/"):
		if p.length() == 3 and p.substr(1, 2) == ":/":
			break
		p = p.left(p.length() - 1)
	return p


func _validate_session_destination(global_root: String, global_dest: String) -> bool:
	var root_norm: String = _normalize_abs_dir(global_root)
	var dest_norm: String = _normalize_abs_dir(global_dest)
	if root_norm.is_empty() or dest_norm.is_empty():
		return false
	var dest_leaf: String = dest_norm.get_file()
	var parent_dir: String = _normalize_abs_dir(dest_norm.get_base_dir())
	var parent_name: String = parent_dir.get_file()
	if parent_name != "sessions" and parent_name != "recycle":
		return false
	var rx := RegEx.new()
	if rx.compile("^.+_[0-9a-f]{32}$") != OK:
		return false
	if rx.search(dest_leaf) == null:
		return false
	var grandparent_dir: String = _normalize_abs_dir(parent_dir.get_base_dir())
	if grandparent_dir.is_empty():
		return false
	if OS.get_name() == "Windows":
		return grandparent_dir.to_lower() == root_norm.to_lower()
	return grandparent_dir == root_norm


func _strip_leading_bom(text: String) -> String:
	var cleaned: String = text
	while cleaned.begins_with(char(0xfeff)):
		cleaned = cleaned.substr(1)
	return cleaned


func _safe_str(v: Variant, fallback: String = "") -> String:
	if v is String or v is StringName:
		return str(v)
	return fallback


func _safe_bytes(v: Variant) -> PackedByteArray:
	if v is PackedByteArray:
		return v as PackedByteArray
	return PackedByteArray()


func _sanitize_name(raw_name: String, fallback: String) -> String:
	var cleaned: String = _strip_leading_bom(raw_name).replace("\r", " ").replace("\n", " ").replace("\t", " ")
	var out: String = ""
	for i: int in range(cleaned.length()):
		var cp: int = cleaned.unicode_at(i)
		if cp >= 32 and not (cp >= 127 and cp <= 159):
			out += cleaned[i]
	while true:
		var next_out: String = _strip_leading_bom(out).strip_edges()
		if next_out == out:
			break
		out = next_out
	out = out.left(256).strip_edges()
	if out.is_empty():
		return fallback
	return out


func _to_float(v: Variant, fallback: float) -> float:
	match typeof(v):
		TYPE_INT:
			return float(v)
		TYPE_FLOAT:
			var f: float = float(v)
			return f if is_finite(f) else fallback
		TYPE_STRING, TYPE_STRING_NAME:
			var s: String = str(v)
			while true:
				var next_s: String = _strip_leading_bom(s).strip_edges()
				if next_s == s:
					break
				s = next_s
			if s.is_valid_float():
				var fs: float = s.to_float()
				if is_finite(fs):
					return fs
	return fallback


func _to_bool(v: Variant, fallback: bool) -> bool:
	match typeof(v):
		TYPE_BOOL:
			return v == true
		TYPE_INT:
			return int(v) != 0
		TYPE_FLOAT:
			var f: float = float(v)
			if not is_finite(f):
				return fallback
			return f != 0.0
		TYPE_STRING, TYPE_STRING_NAME:
			var cleaned: String = str(v)
			while true:
				var next_cleaned: String = _strip_leading_bom(cleaned).strip_edges()
				if next_cleaned == cleaned:
					break
				cleaned = next_cleaned
			var s: String = cleaned.to_lower()
			match s:
				"true", "1", "yes", "on":
					return true
				"false", "0", "no", "off":
					return false
	return fallback


func _to_vec2(v: Variant, fallback: Vector2) -> Vector2:
	if v is Vector2:
		var vec: Vector2 = v as Vector2
		if is_finite(vec.x) and is_finite(vec.y):
			return vec
	elif v is Array and (v as Array).size() >= 2:
		var arr: Array = v as Array
		return Vector2(_to_float(arr[0], fallback.x), _to_float(arr[1], fallback.y))
	return fallback


func _is_valid_asset_ref(ref_str: String) -> bool:
	if not ref_str.begins_with("asset://"):
		return false
	var rest: String = ref_str.substr(8)
	var dot: int = rest.rfind(".")
	if dot != 64:
		return false
	var digest: String = rest.substr(0, 64)
	if digest.length() != 64:
		return false
	for i: int in range(64):
		var c: int = digest.unicode_at(i)
		if not ((c >= 48 and c <= 57) or (c >= 97 and c <= 102)):
			return false
	var ext: String = rest.substr(65)
	return ext in _ALLOWED_ASSET_EXTS


func _resolve_validated_paths(host: RefCounted) -> Dictionary:
	var store: Variant = _resolve_shared_asset_store()
	if store == null or host == null:
		return {"ok": false}
	var root_var: Variant = host.get("root")
	var dest_var: Variant = host.get("destination")
	if not (root_var is String) or not (dest_var is String):
		return {"ok": false}
	var raw_root: String = (root_var as String).strip_edges()
	var raw_dest: String = (dest_var as String).strip_edges()
	if raw_root.is_empty() or raw_dest.is_empty():
		return {"ok": false}
	var global_root: String = ProjectSettings.globalize_path(raw_root)
	var global_dest: String = ProjectSettings.globalize_path(raw_dest)
	if not _validate_session_destination(global_root, global_dest):
		return {"ok": false}
	return {
		"ok": true,
		"store": store,
		"global_root": global_root,
		"global_dest": global_dest,
	}


func can_write_library(host: RefCounted) -> bool:
	var gate: Dictionary = _resolve_validated_paths(host)
	return bool(gate.get("ok", false))


func _rollback_library_mutations(
	store: Variant,
	global_root: String,
	mutations: Array[Dictionary],
	initial_rev: String
) -> void:
	if store == null or mutations.is_empty():
		return
	var rev: String = initial_rev
	if rev.is_empty() and store.has_method("ReadLibraryRecords"):
		var r_var: Variant = store.ReadLibraryRecords(global_root)
		if r_var is Dictionary and bool((r_var as Dictionary).get("ok", false)):
			rev = _safe_str((r_var as Dictionary).get("revision", ""), "")
	for idx: int in range(mutations.size() - 1, -1, -1):
		var mut: Dictionary = mutations[idx]
		var rec_id: String = _safe_str(mut.get("id", ""), "")
		var written_b: PackedByteArray = _safe_bytes(mut.get("written_bytes", null))
		var prev_b: PackedByteArray = _safe_bytes(mut.get("prev_bytes", null))
		var rb_res: Dictionary = _parse_json_dict(
			store.WriteLibraryRecord(global_root, rec_id, written_b, prev_b, rev)
		)
		if bool(rb_res.get("ok", false)):
			rev = _safe_str(rb_res.get("revision", rev), rev)
		elif store.has_method("ReadLibraryRecords"):
			var r2_var: Variant = store.ReadLibraryRecords(global_root)
			if r2_var is Dictionary and bool((r2_var as Dictionary).get("ok", false)):
				var r2: Dictionary = r2_var as Dictionary
				rev = _safe_str(r2.get("revision", rev), rev)
				var cur_recs: Dictionary = r2.get("records", {}) if r2.get("records", null) is Dictionary else {}
				var cur_b: PackedByteArray = _safe_bytes(cur_recs.get(rec_id, null))
				var rb2: Dictionary = _parse_json_dict(
					store.WriteLibraryRecord(global_root, rec_id, cur_b, prev_b, rev)
				)
				if bool(rb2.get("ok", false)):
					rev = _safe_str(rb2.get("revision", rev), rev)


func rollback_last_registration() -> void:
	if _last_lib_rollback.is_empty():
		return
	var store: Variant = _last_lib_rollback.get("store", null)
	if store == null:
		store = _resolve_shared_asset_store()
	var gr: String = _safe_str(_last_lib_rollback.get("global_root", ""), "")
	var muts_raw: Variant = _last_lib_rollback.get("mutations", [])
	var rev: String = _safe_str(_last_lib_rollback.get("rev", ""), "")
	_last_lib_rollback = {}
	if store == null or gr.is_empty() or not (muts_raw is Array):
		return
	var muts: Array[Dictionary] = []
	for m: Variant in muts_raw as Array:
		if m is Dictionary:
			muts.append(m as Dictionary)
	_rollback_library_mutations(store, gr, muts, rev)


func _build_unit_row(
	row_id: String,
	row_name: String,
	folder_id: String,
	sprite_ref: String,
	row_size: Vector2
) -> Dictionary:
	return {
		"version": 1,
		"id": row_id,
		"name": row_name,
		"kind": "unit",
		"folder_id": folder_id,
		"reference": sprite_ref,
		"size": row_size,
		"record": {
			"data": {
				"id": row_id,
				"name": row_name,
				"type": "generic",
				"category": "library",
				"size": row_size,
				"color": Color.WHITE,
				"sprite": sprite_ref,
				"components": {"unit": {}},
				"selectable_in_select_mode": false,
			},
			"source_info": {},
			"kind": "unit",
		},
	}


func _build_preset_row(
	row_id: String,
	row_name: String,
	folder_id: String,
	sprite_ref: String,
	row_size: Vector2,
	footprint_radius: float,
	scale_vec: Vector2,
	all_players_can_operate: bool,
	vision_radius: float,
	vision_angle: float
) -> Dictionary:
	var comps: Array = [
		{
			"script": _COMP_VISUAL_SCRIPT,
			"state": {
				"enabled": true,
				"show_fallback": true,
				"fallback_color": _DEFAULT_FALLBACK_COLOR,
				"sprite_path": sprite_ref,
				"source_info": {},
			},
		},
		{
			"script": _COMP_PERMISSION_SCRIPT,
			"state": {
				"owners_csv": "",
				"gm_can_operate": true,
				"all_players_can_operate": all_players_can_operate,
				"owner_peers": PackedInt32Array(),
				"owner_player_ids": PackedStringArray(),
			},
		},
		{
			"script": _COMP_UNIT_SCRIPT,
			"state": {"schema_version": 1},
		},
	]
	if vision_radius > 0.0:
		comps.append({
			"script": _COMP_SIMPLE_VISION_SCRIPT,
			"state": {
				"enabled": true,
				"requires_light": false,
				"radius": maxf(0.0, vision_radius),
				"view_angle": clampf(vision_angle, 0.0, 360.0),
			},
		})
	var snapshot: Dictionary = {
		"version": 3,
		"entities": [
			{
				"id": row_id,
				"display_name": row_name,
				"entity_type": "unit",
				"entity_size": row_size,
				"selectable_in_select_mode": true,
				"footprint_radius": footprint_radius,
				"fallback_color": Color.WHITE,
				"xform": {
					"pos": Vector2.ZERO,
					"rot": 0.0,
					"scale": scale_vec,
				},
				"flags": {
					"entity_hidden": false,
					"entity_locked": false,
				},
				"components": comps,
			},
		],
	}
	return {
		"version": 1,
		"id": row_id,
		"name": row_name,
		"kind": "preset",
		"folder_id": folder_id,
		"reference": sprite_ref,
		"size": row_size,
		"record": {
			"data": {
				"id": row_id,
				"name": row_name,
				"type": "generic",
				"category": "library",
				"size": row_size,
				"color": Color.WHITE,
				"sprite": sprite_ref,
				"components": {},
				"selectable_in_select_mode": false,
			},
			"source_info": {},
			"kind": "preset",
			"snapshot": snapshot,
		},
	}


func register_entries(
	namespace_id: String,
	entries: Array,
	host: RefCounted,
	session: RefCounted = null,
	enabled: bool = true
) -> Dictionary:
	_last_lib_rollback = {}
	if not enabled:
		return {"ok": true, "count": 0, "skipped": true, "reason": "disabled"}
	var gate: Dictionary = _resolve_validated_paths(host)
	if not bool(gate.get("ok", false)):
		return {"ok": true, "count": 0, "skipped": true, "reason": "library_gate_not_met"}
	if _is_cancelled(session):
		return {"ok": false, "count": 0, "skipped": false, "reason": "cancelled"}
	if entries.is_empty():
		return {"ok": true, "count": 0, "skipped": true, "reason": "empty_entries"}

	var ns: String = namespace_id.strip_edges()
	if ns.is_empty():
		ns = "fu_sdk_default"

	var store: Variant = gate["store"]
	var global_root: String = str(gate["global_root"])
	var global_dest: String = str(gate["global_dest"])

	var open_res: Dictionary = _parse_json_dict(store.OpenLibrary(global_root))
	if not bool(open_res.get("ok", false)):
		var open_reason: String = _safe_str(open_res.get("reason", "open_library_failed"), "open_library_failed")
		if open_reason.is_empty():
			open_reason = "open_library_failed"
		_warn(session, "打开素材库失败，已跳过素材库注册：" + open_reason)
		return {"ok": true, "count": 0, "skipped": true, "reason": open_reason}

	var read_var: Variant = store.ReadLibraryRecords(global_root)
	if not (read_var is Dictionary):
		_warn(session, "读取素材库记录失败，已跳过素材库注册")
		return {"ok": true, "count": 0, "skipped": true, "reason": "read_library_records_failed"}
	var read_res: Dictionary = read_var as Dictionary
	if not bool(read_res.get("ok", false)):
		var read_reason: String = _safe_str(read_res.get("reason", "read_library_records_failed"), "read_library_records_failed")
		if read_reason.is_empty():
			read_reason = "read_library_records_failed"
		_warn(session, "读取素材库记录失败，已跳过素材库注册：" + read_reason)
		return {"ok": true, "count": 0, "skipped": true, "reason": read_reason}

	var records: Dictionary = read_res.get("records", {}) if read_res.get("records", null) is Dictionary else {}
	var current_rev: String = _safe_str(read_res.get("revision", ""), "")
	var registered_count: int = 0
	var mutations: Array[Dictionary] = []

	# 1. Deterministic folder hierarchy creation (cycle-free)
	var folder_ids: Dictionary = {}
	for raw_entry: Variant in entries:
		if _is_cancelled(session):
			_rollback_library_mutations(store, global_root, mutations, current_rev)
			return {"ok": false, "count": 0, "skipped": false, "reason": "cancelled"}
		if not (raw_entry is Dictionary):
			continue
		var entry: Dictionary = raw_entry as Dictionary
		var folder_raw: Variant = entry.get("folder_name", "")
		var fname_path: String = _safe_str(folder_raw, "").strip_edges()
		if fname_path.is_empty():
			continue
		var parts: PackedStringArray = fname_path.replace("\\", "/").split("/", false)
		var parent_id: String = ""
		var prefix_path: String = ""
		for seg: String in parts:
			if _is_cancelled(session):
				_rollback_library_mutations(store, global_root, mutations, current_rev)
				return {"ok": false, "count": 0, "skipped": false, "reason": "cancelled"}
			var clean_seg: String = _sanitize_name(seg, "")
			if clean_seg.is_empty():
				continue
			prefix_path = clean_seg if prefix_path.is_empty() else (prefix_path + "/" + clean_seg)
			if folder_ids.has(prefix_path):
				parent_id = str(folder_ids[prefix_path])
				continue
			var fid: String = ("fus:lib:folder:%s:%s" % [ns, prefix_path]).sha256_text().left(32)
			if fid == parent_id:
				continue
			var folder_row: Dictionary = {
				"version": 1,
				"id": fid,
				"name": clean_seg,
				"kind": "folder",
				"folder_id": parent_id,
			}
			var desired_f: PackedByteArray = var_to_bytes(folder_row)
			var expected_f: PackedByteArray = _safe_bytes(records.get(fid, null))
			var folder_ok: bool = false
			if desired_f == expected_f:
				folder_ok = true
			else:
				var wf_res: Dictionary = _parse_json_dict(
					store.WriteLibraryRecord(global_root, fid, expected_f, desired_f, current_rev)
				)
				if bool(wf_res.get("ok", false)):
					current_rev = _safe_str(wf_res.get("revision", current_rev), current_rev)
					mutations.append({
						"id": fid,
						"prev_bytes": expected_f,
						"written_bytes": desired_f,
					})
					records[fid] = desired_f
					folder_ok = true
				else:
					var wf_reason: String = _safe_str(wf_res.get("reason", "unknown"), "unknown")
					_warn(session, "写入素材库目录失败（%s）：%s" % [clean_seg, wf_reason if not wf_reason.is_empty() else "unknown"])
					if records.has(fid):
						folder_ok = true
			if folder_ok:
				folder_ids[prefix_path] = fid
				parent_id = fid
			else:
				break

	# 2. Register unit / preset entries
	var seen_keys: Dictionary = {}
	for i: int in range(entries.size()):
		if _is_cancelled(session):
			_rollback_library_mutations(store, global_root, mutations, current_rev)
			return {"ok": false, "count": 0, "skipped": false, "reason": "cancelled"}
		if not (entries[i] is Dictionary):
			continue
		var entry: Dictionary = entries[i] as Dictionary
		var raw_id: Variant = entry.get("id", "")
		var base_key: String = _safe_str(raw_id, "").strip_edges()
		if base_key.is_empty():
			base_key = "_idx_%d" % i
		var key: String = base_key
		var dup_idx: int = 1
		while seen_keys.has(key):
			key = "%s_%d" % [base_key, dup_idx]
			dup_idx += 1
		seen_keys[key] = true

		var sprite_raw: Variant = entry.get("sprite_ref", "")
		var sprite_ref: String = _safe_str(sprite_raw, "").strip_edges()
		if not sprite_ref.is_empty():
			if _is_valid_asset_ref(sprite_ref):
				var adopt_res: Dictionary = _parse_json_dict(
					store.AdoptLibraryAsset(global_root, global_dest, sprite_ref)
				)
				if bool(adopt_res.get("ok", false)):
					if store.has_method("ShareLibraryAsset"):
						var share_res: Dictionary = _parse_json_dict(
							store.ShareLibraryAsset(global_root, sprite_ref)
						)
						if not bool(share_res.get("ok", false)):
							var share_reason: String = _safe_str(share_res.get("reason", "unknown"), "unknown")
							_warn(session, "素材库共享贴图失败（%s）：%s" % [sprite_ref, share_reason if not share_reason.is_empty() else "unknown"])
				else:
					var adopt_reason: String = _safe_str(adopt_res.get("reason", "unknown"), "unknown")
					_warn(session, "素材库归档贴图失败（%s）：%s" % [sprite_ref, adopt_reason if not adopt_reason.is_empty() else "unknown"])
					sprite_ref = ""
			else:
				sprite_ref = ""

		var folder_raw2: Variant = entry.get("folder_name", "")
		var folder_path: String = _safe_str(folder_raw2, "").strip_edges()
		var target_folder_id: String = ""
		if not folder_path.is_empty():
			var clean_segs: Array[String] = []
			for seg2: String in folder_path.replace("\\", "/").split("/", false):
				var cs: String = _sanitize_name(seg2, "")
				if not cs.is_empty():
					clean_segs.append(cs)
			var clean_key: String = "/".join(clean_segs)
			target_folder_id = str(folder_ids.get(clean_key, ""))

		var raw_name_v: Variant = entry.get("name", "")
		var raw_name: String = _safe_str(raw_name_v, "")
		var row_name: String = _sanitize_name(raw_name, "Unnamed Unit")

		var raw_size: Vector2 = _to_vec2(entry.get("size_world", Vector2(64.0, 64.0)), Vector2(64.0, 64.0))
		var row_size := Vector2(maxf(_MIN_ENTITY_SIZE.x, raw_size.x), maxf(_MIN_ENTITY_SIZE.y, raw_size.y))
		var footprint_radius: float = clampf(
			_to_float(entry.get("footprint_radius", 32.0), 32.0),
			_MIN_FOOTPRINT_RADIUS,
			_MAX_FOOTPRINT_RADIUS
		)
		var raw_scale: Vector2 = _to_vec2(entry.get("scale", Vector2.ONE), Vector2.ONE)
		if is_zero_approx(raw_scale.x):
			raw_scale.x = 1.0
		if is_zero_approx(raw_scale.y):
			raw_scale.y = 1.0
		var all_players_can_operate: bool = _to_bool(entry.get("all_players_can_operate", false), false)
		var create_preset: bool = _to_bool(entry.get("create_preset", true), true)
		var vision_radius: float = maxf(0.0, _to_float(entry.get("vision_radius", 0.0), 0.0))
		var vision_angle: float = clampf(_to_float(entry.get("vision_angle", 360.0), 360.0), 0.0, 360.0)

		var row_id: String
		var row_dict: Dictionary
		if create_preset:
			row_id = ("fus:lib:preset:%s:%s" % [ns, key]).sha256_text().left(32)
			row_dict = _build_preset_row(
				row_id,
				row_name,
				target_folder_id,
				sprite_ref,
				row_size,
				footprint_radius,
				raw_scale,
				all_players_can_operate,
				vision_radius,
				vision_angle
			)
		else:
			row_id = ("fus:lib:unit:%s:%s" % [ns, key]).sha256_text().left(32)
			row_dict = _build_unit_row(row_id, row_name, target_folder_id, sprite_ref, row_size)

		var desired_u: PackedByteArray = var_to_bytes(row_dict)
		var expected_u: PackedByteArray = _safe_bytes(records.get(row_id, null))
		if desired_u == expected_u:
			registered_count += 1
			continue
		var wu_res: Dictionary = _parse_json_dict(
			store.WriteLibraryRecord(global_root, row_id, expected_u, desired_u, current_rev)
		)
		if bool(wu_res.get("ok", false)):
			current_rev = _safe_str(wu_res.get("revision", current_rev), current_rev)
			mutations.append({
				"id": row_id,
				"prev_bytes": expected_u,
				"written_bytes": desired_u,
			})
			records[row_id] = desired_u
			registered_count += 1
		else:
			var wu_reason: String = _safe_str(wu_res.get("reason", "unknown"), "unknown")
			_warn(session, "写入素材库条目失败（%s）：%s" % [row_name, wu_reason if not wu_reason.is_empty() else "unknown"])

	if _is_cancelled(session):
		_rollback_library_mutations(store, global_root, mutations, current_rev)
		return {"ok": false, "count": 0, "skipped": false, "reason": "cancelled"}

	_last_lib_rollback = {
		"store": store,
		"global_root": global_root,
		"mutations": mutations,
		"rev": current_rev,
	}
	return {"ok": true, "count": registered_count, "skipped": false, "reason": ""}
