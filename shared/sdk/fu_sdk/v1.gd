extends RefCounted
## Fu vtt 防腐层共享 SDK 门面 (v1)
##
## 面向下游业务模组（mods/<mod-name>/entry.gd）提供稳定的跑团场景导入语义契约，
## 彻底隔离宿主底层 ImportBridge 强校验细节、图层 UID 索引与 ECS 组件内部路径。
##
## 推荐用法（外层实例工厂，100% 规避 Godot 4 内部类 get_script() 路径解析陷阱）：
##   var sdk := FuSdkScript.new()
##   var session = sdk.create_session(host, options)
##   var builder = sdk.create_world_builder(session, 150.0)
## 同时也完全兼容 FuSdkScript.ImportSession.new(...) 与 FuSdkScript.WorldBuilder.new() 直接实例化。

const SDK_VERSION: String = "1.3.0"
const ADAPTER_REL_PATH: String = "adapters/host_v1_adapter.gd"
const DEV_FALLBACK_ADAPTER_PATH: String = "shared/sdk/fu_sdk/adapters/host_v1_adapter.gd"
const DEV_FALLBACK_SDK_DIR: String = "shared/sdk/fu_sdk/"

var _adapter_script: Script = null
var _helper_adapter: RefCounted = null
var _sub_script_cache: Dictionary = {}


func _init(custom_adapter_script: Script = null) -> void:
	if custom_adapter_script != null:
		_adapter_script = custom_adapter_script
	else:
		_adapter_script = _load_adapter_from_outer_script()
	if _adapter_script != null:
		ImportSession.set_default_adapter_script(_adapter_script)
		WorldBuilder.set_default_adapter_script(_adapter_script)


func create_adapter() -> RefCounted:
	if _adapter_script == null:
		_adapter_script = _load_adapter_from_outer_script()
	if _adapter_script != null:
		ImportSession.set_default_adapter_script(_adapter_script)
		WorldBuilder.set_default_adapter_script(_adapter_script)
		return _adapter_script.new()
	return null


func create_session(host: RefCounted, options: Dictionary = {}) -> ImportSession:
	return ImportSession.new(host, options, create_adapter())


func create_world_builder(
	session: ImportSession = null,
	source_units_per_cell: float = 150.0
) -> WorldBuilder:
	var adapter_inst: RefCounted = session.get_adapter() if session != null else create_adapter()
	var builder := WorldBuilder.new(adapter_inst)
	if session != null:
		builder.setup(session, source_units_per_cell)
	return builder


func create_asset_publisher() -> RefCounted:
	var scr: Script = _load_sdk_sub_script("modules/asset_publisher.gd")
	return scr.new() if scr != null else null


func create_entity_library_writer() -> RefCounted:
	var scr: Script = _load_sdk_sub_script("modules/entity_library_writer.gd")
	return scr.new() if scr != null else null


func create_package_source() -> RefCounted:
	var scr: Script = _load_sdk_sub_script("modules/package_source.gd")
	return scr.new() if scr != null else null


func create_snappy_codec() -> RefCounted:
	var scr: Script = _load_sdk_sub_script("modules/snappy.gd")
	return scr.new() if scr != null else null


func coerce_bool(value: Variant, fallback: bool = false) -> bool:
	var adapter: RefCounted = _get_helper_adapter()
	if adapter != null:
		return bool(adapter.coerce_bool(value, fallback))
	if typeof(value) == TYPE_BOOL:
		return value == true
	return fallback


func coerce_string(value: Variant, fallback: String = "") -> String:
	var adapter: RefCounted = _get_helper_adapter()
	if adapter != null:
		return str(adapter.coerce_string(value, fallback))
	if typeof(value) == TYPE_STRING:
		return value as String
	return fallback


func coerce_int(value: Variant, fallback: int = 0) -> int:
	var adapter: RefCounted = _get_helper_adapter()
	if adapter != null:
		return int(adapter.coerce_int(value, fallback))
	if typeof(value) == TYPE_INT:
		return int(value)
	return fallback


func coerce_float(value: Variant, fallback: float = 0.0) -> float:
	var adapter: RefCounted = _get_helper_adapter()
	if adapter != null:
		return float(adapter.coerce_float(value, fallback))
	if typeof(value) == TYPE_INT or typeof(value) == TYPE_FLOAT:
		var f: float = float(value)
		return f if is_finite(f) else fallback
	return fallback


func _get_helper_adapter() -> RefCounted:
	if _helper_adapter == null:
		_helper_adapter = create_adapter()
	return _helper_adapter


func _load_sdk_sub_script(rel_path: String) -> Script:
	var clean_rel: String = rel_path.strip_edges()
	if clean_rel.is_empty():
		return null
	if _sub_script_cache.has(clean_rel):
		return _sub_script_cache[clean_rel] as Script
	var outer_scr := get_script() as Script
	if outer_scr != null and not outer_scr.resource_path.is_empty():
		var clean_path: String = outer_scr.resource_path.split("::")[0]
		var candidate: String = clean_path.get_base_dir().path_join(clean_rel)
		if FileAccess.file_exists(candidate) or ResourceLoader.exists(candidate):
			var loaded := load(candidate) as Script
			if loaded != null:
				_sub_script_cache[clean_rel] = loaded
				return loaded
	var fallback_path: String = DEV_FALLBACK_SDK_DIR.path_join(clean_rel)
	if FileAccess.file_exists(fallback_path) or ResourceLoader.exists(fallback_path):
		var loaded_fb := load(fallback_path) as Script
		if loaded_fb != null:
			_sub_script_cache[clean_rel] = loaded_fb
			return loaded_fb
	return null


func _load_adapter_from_outer_script() -> Script:
	return _load_sdk_sub_script(ADAPTER_REL_PATH)


class ImportSession extends RefCounted:
	static var _default_adapter_script: Script = null

	var _host: RefCounted = null
	var _options: Dictionary = {}
	var _adapter: RefCounted = null
	var _image_cache: Dictionary = {}
	var _archived_ok_count: int = 0

	static func set_default_adapter_script(adapter_script: Script) -> void:
		if adapter_script != null:
			_default_adapter_script = adapter_script

	func _init(
		host: RefCounted = null,
		options: Dictionary = {},
		adapter: RefCounted = null
	) -> void:
		_host = host
		_options = options.duplicate(true)
		_adapter = _resolve_adapter(adapter)

	func get_host() -> RefCounted:
		return _host

	func get_options() -> Dictionary:
		return _options

	func get_option(key: String, default_value: Variant = null) -> Variant:
		return _options.get(key, default_value)

	func get_bool_option(key: String, fallback: bool = false) -> bool:
		if not _options.has(key):
			return fallback
		var raw: Variant = _options[key]
		if _adapter != null:
			return bool(_adapter.coerce_bool(raw, fallback))
		if typeof(raw) == TYPE_BOOL:
			return raw == true
		return fallback

	func get_string_option(key: String, fallback: String = "") -> String:
		if not _options.has(key):
			return fallback
		var raw: Variant = _options[key]
		if _adapter != null:
			return str(_adapter.coerce_string(raw, fallback))
		if typeof(raw) == TYPE_STRING:
			return raw as String
		return fallback

	func get_int_option(key: String, fallback: int = 0) -> int:
		if not _options.has(key):
			return fallback
		var raw: Variant = _options[key]
		if _adapter != null:
			return int(_adapter.coerce_int(raw, fallback))
		if typeof(raw) == TYPE_INT:
			return int(raw)
		return fallback

	func get_float_option(key: String, fallback: float = 0.0) -> float:
		if not _options.has(key):
			return fallback
		var raw: Variant = _options[key]
		if _adapter != null:
			return float(_adapter.coerce_float(raw, fallback))
		if typeof(raw) == TYPE_INT or typeof(raw) == TYPE_FLOAT:
			var f: float = float(raw)
			return f if is_finite(f) else fallback
		return fallback

	func sanitize_options(defaults: Dictionary) -> Dictionary:
		var out: Dictionary = {}
		for raw_key: Variant in defaults.keys():
			var key: String = str(raw_key)
			var def_val: Variant = defaults[raw_key]
			match typeof(def_val):
				TYPE_BOOL:
					out[key] = get_bool_option(key, def_val == true)
				TYPE_STRING:
					out[key] = get_string_option(key, str(def_val))
				TYPE_INT:
					out[key] = get_int_option(key, int(def_val))
				TYPE_FLOAT:
					out[key] = get_float_option(key, float(def_val))
				_:
					out[key] = _options.get(key, def_val)
		return out

	func get_adapter() -> RefCounted:
		return _adapter

	func get_archived_asset_count() -> int:
		return _archived_ok_count

	func is_cancelled() -> bool:
		if _adapter != null:
			return bool(_adapter.is_cancelled(_host))
		if _host != null and _host.has_method("cancelled"):
			return bool(_host.cancelled())
		return false

	func report_progress(message: String) -> void:
		if _adapter != null:
			_adapter.report_progress(_host, message)
		elif _host != null and _host.has_method("report"):
			_host.report(message)

	func add_warning(message: String) -> void:
		if _adapter != null:
			_adapter.add_warning(_host, message)
		elif _host != null and _host.has_method("warn"):
			_host.warn(message)

	func inspect_source(path: String) -> Dictionary:
		if _adapter != null:
			return _adapter.inspect_source(_host, path)
		if _host != null and _host.has_method("inspect_source"):
			var raw_res: Variant = _host.inspect_source(path)
			if raw_res is Dictionary:
				return raw_res
		return {"ok": false, "reason": "inspect_source_unavailable"}

	func decode_source(path: String) -> Dictionary:
		if _adapter != null:
			return _adapter.decode_source(_host, path)
		if _host != null and _host.has_method("decode_source"):
			var raw_res: Variant = _host.decode_source(path)
			if raw_res is Dictionary:
				return raw_res
		return {"ok": false, "reason": "decode_source_unavailable"}

	func validate_sprite_path(sprite_ref: String) -> String:
		if _adapter == null:
			return sprite_ref
		var checked: Dictionary = _adapter.sanitize_sprite_path(sprite_ref)
		if not bool(checked.get("ok", false)):
			add_warning("已拦截非法图片路径（宿主仅允许 asset:// 或 res://）：" + str(checked.get("rejected", sprite_ref)))
		return str(checked.get("path", ""))

	func archive_remote_image(url: String, proxy: String = "") -> String:
		if url.is_empty():
			return ""
		if _image_cache.has(url):
			return str(_image_cache[url])

		var effective_proxy: String = proxy.strip_edges()
		if effective_proxy.is_empty() and _options.has("proxy"):
			var raw_proxy: Variant = _options.get("proxy", null)
			if typeof(raw_proxy) == TYPE_STRING:
				effective_proxy = (raw_proxy as String).strip_edges()

		var archive_res: Dictionary = {}
		if _adapter != null:
			archive_res = _adapter.archive_image(_host, url, effective_proxy)
		elif _host != null and _host.has_method("archive_image"):
			var raw_res: Variant = _host.archive_image(url, effective_proxy)
			if raw_res is Dictionary:
				archive_res = raw_res

		if bool(archive_res.get("ok", false)):
			var ref_path: String = validate_sprite_path(str(archive_res.get("reference", "")))
			_image_cache[url] = ref_path
			if not ref_path.is_empty():
				_archived_ok_count += 1
			return ref_path

		add_warning("图片未下载：" + url + "（" + str(archive_res.get("reason", "unknown")) + "）")
		_image_cache[url] = ""
		return ""

	func ok_inspect(
		source_path: String,
		counts_override: Dictionary = {},
		remote_assets: Dictionary = {},
		decoded_bytes: int = -1,
		display_name: String = ""
	) -> Dictionary:
		if _adapter != null:
			return _adapter.build_inspect_ok(
				source_path,
				counts_override,
				remote_assets,
				decoded_bytes,
				display_name
			)
		var fallback_sha256: String = ""
		var source_bytes: int = 0
		if not source_path.is_empty() and FileAccess.file_exists(source_path):
			fallback_sha256 = FileAccess.get_sha256(source_path)
			var f: FileAccess = FileAccess.open(source_path, FileAccess.READ)
			if f != null:
				source_bytes = maxi(0, int(f.get_length()))
				f.close()
		var counts: Dictionary = {
			"records": 0,
			"images": 0,
			"selected_images": 0,
			"maps": 0,
			"characters": 0,
			"objects": 0,
			"text": 0,
			"drawings": 0,
			"walls": 0,
			"doors": 0,
			"hidden": 0,
			"unsupported": 0,
		}
		for raw_key: Variant in counts_override.keys():
			counts[str(raw_key)] = int(counts_override[raw_key])
		var final_decoded_bytes: int = decoded_bytes if decoded_bytes >= 0 else source_bytes
		var unique_images: int = maxi(int(counts.get("images", 0)), remote_assets.size())
		var clean_name: String = display_name.strip_edges()
		if clean_name.is_empty() and not source_path.is_empty():
			clean_name = source_path.get_file().get_basename().strip_edges()
		return {
			"ok": true,
			"name": clean_name,
			"sha256": fallback_sha256,
			"source_bytes": source_bytes,
			"decoded_bytes": final_decoded_bytes,
			"unique_images": unique_images,
			"counts": counts,
			"assets": remote_assets.duplicate(),
		}

	func err_cancelled() -> Dictionary:
		if _adapter != null:
			return _adapter.build_cancelled()
		return {"ok": false, "reason": "cancelled"}

	func err_failed(reason: String) -> Dictionary:
		if _adapter != null:
			return _adapter.build_failed(reason)
		return {"ok": false, "reason": reason if not reason.is_empty() else "import_failed"}

	func _resolve_adapter(explicit_adapter: RefCounted) -> RefCounted:
		if explicit_adapter != null:
			return explicit_adapter
		if _default_adapter_script != null:
			return _default_adapter_script.new()
		var discovered := _discover_adapter_script()
		if discovered != null:
			_default_adapter_script = discovered
			return discovered.new()
		return null

	func _discover_adapter_script() -> Script:
		var inner_scr := get_script() as Script
		if inner_scr != null and not inner_scr.resource_path.is_empty():
			var base_path: String = inner_scr.resource_path.split("::")[0].get_base_dir()
			var candidate: String = base_path.path_join(ADAPTER_REL_PATH)
			if FileAccess.file_exists(candidate) or ResourceLoader.exists(candidate):
				return load(candidate) as Script

		var stack_frames: Array = get_stack()
		for raw_frame: Variant in stack_frames:
			if raw_frame is Dictionary:
				var src_file: String = str((raw_frame as Dictionary).get("source", ""))
				if not src_file.is_empty():
					var candidate_from_stack: String = src_file.get_base_dir().path_join(ADAPTER_REL_PATH)
					if FileAccess.file_exists(candidate_from_stack) or ResourceLoader.exists(candidate_from_stack):
						return load(candidate_from_stack) as Script

		if FileAccess.file_exists(DEV_FALLBACK_ADAPTER_PATH) or ResourceLoader.exists(DEV_FALLBACK_ADAPTER_PATH):
			return load(DEV_FALLBACK_ADAPTER_PATH) as Script
		return null


class WorldBuilder extends RefCounted:
	static var _default_adapter_script: Script = null

	var _adapter: RefCounted = null
	var _session: ImportSession = null
	var _world: Dictionary = {}
	var _floor_uid: String = ""
	var _layers: Dictionary = {}
	var _floor_layers: Dictionary = {}
	var _layer_to_floor: Dictionary = {}
	var _active_scene_uid: String = ""
	var _source_units_per_cell: float = 150.0
	var _source_to_world: float = 64.0 / 150.0
	var _is_ready: bool = false
	var _setup_result: Dictionary = {}
	var _preview_active: bool = false
	var _entity_count: int = 0
	var _used_sprite_refs: Dictionary = {}
	var _entity_by_id: Dictionary = {}

	static func set_default_adapter_script(adapter_script: Script) -> void:
		if adapter_script != null:
			_default_adapter_script = adapter_script

	func _init(adapter: RefCounted = null) -> void:
		if adapter != null:
			_adapter = adapter
		elif _default_adapter_script != null:
			_adapter = _default_adapter_script.new()

	func setup(session: ImportSession, source_units_per_cell: float = 150.0) -> Dictionary:
		if session == null:
			_is_ready = false
			_setup_result = {"ok": false, "reason": "missing_import_session"}
			return _setup_result

		# 若通过 sdk.create_world_builder(session, units) 已完成初始化且尚未写入实体，避免重复调用 host.empty_world()
		if (
			_is_ready
			and _session == session
			and _entity_count == 0
			and is_equal_approx(_source_units_per_cell, source_units_per_cell)
		):
			return _setup_result

		_session = session
		if _adapter == null:
			_adapter = session.get_adapter()
		if _adapter == null and _default_adapter_script != null:
			_adapter = _default_adapter_script.new()
		if _adapter == null:
			_is_ready = false
			_setup_result = {"ok": false, "reason": "host_adapter_unavailable"}
			return _setup_result

		_source_units_per_cell = maxf(0.0001, source_units_per_cell if is_finite(source_units_per_cell) else 150.0)
		_source_to_world = _adapter.compute_source_to_world_scale(_source_units_per_cell)

		var world_init: Dictionary = _adapter.init_empty_world(session.get_host())
		if not bool(world_init.get("ok", false)):
			_is_ready = false
			_setup_result = world_init
			return _setup_result

		_world = world_init["world"]
		_floor_uid = str(world_init["floor_uid"])
		_layers = (world_init["layers"] as Dictionary).duplicate()
		_floor_layers = {_floor_uid: _layers.duplicate()}
		_layer_to_floor.clear()
		_active_scene_uid = ""
		_rebuild_layer_to_floor_index()
		_preview_active = false
		_entity_count = 0
		_used_sprite_refs.clear()
		_entity_by_id.clear()
		_is_ready = true
		_setup_result = {"ok": true}
		return _setup_result

	func is_ready() -> bool:
		return _is_ready

	func get_setup_result() -> Dictionary:
		return _setup_result

	func get_world() -> Dictionary:
		return _world

	func get_source_to_world_scale() -> float:
		return _source_to_world

	func to_world_pos(pos_src: Vector2) -> Vector2:
		if _adapter != null:
			return _adapter.sanitize_finite_vec2(pos_src, Vector2.ZERO) * _source_to_world
		return pos_src * _source_to_world

	func get_active_floor_uid() -> String:
		return _floor_uid

	func get_layer_uid(kind: String, floor_uid: String = "") -> String:
		var target_floor: String = floor_uid if not floor_uid.is_empty() else _floor_uid
		if _floor_layers.has(target_floor):
			return str((_floor_layers[target_floor] as Dictionary).get(kind, ""))
		if _adapter != null:
			var resolved: Dictionary = _adapter.get_floor_layer_map(_world, target_floor)
			if not resolved.is_empty():
				_floor_layers[target_floor] = resolved
				_index_floor_layers(target_floor, resolved)
				return str(resolved.get(kind, ""))
		return ""

	func add_floor(
		name: String,
		color: Color = Color(0.28, 0.65, 0.40),
		activate: bool = false
	) -> String:
		if not _is_ready or _adapter == null:
			return ""
		if has_scenes_configured():
			var target_scene: String = _active_scene_uid if not _active_scene_uid.is_empty() else get_entry_scene_uid()
			return add_floor_to_scene(target_scene, name, color, false, activate)
		var res: Dictionary = _adapter.create_floor(_world, name, color)
		if not bool(res.get("ok", false)):
			_warn("新建楼层失败（" + name + "）：" + str(res.get("reason", "unknown")))
			return ""
		var new_uid: String = str(res["floor_uid"])
		var layer_map: Dictionary = (res["layers"] as Dictionary).duplicate()
		_floor_layers[new_uid] = layer_map
		_index_floor_layers(new_uid, layer_map)
		if activate:
			set_active_floor(new_uid)
		return new_uid

	func set_active_floor(floor_uid: String) -> bool:
		if not _is_ready or _adapter == null or floor_uid.is_empty():
			return false
		var res: Dictionary = _adapter.set_active_floor(_world, floor_uid)
		if not bool(res.get("ok", false)):
			_warn("切换活动楼层失败：" + str(res.get("reason", "unknown")))
			return false
		_floor_uid = floor_uid
		if _floor_layers.has(floor_uid):
			_layers = (_floor_layers[floor_uid] as Dictionary).duplicate()
		else:
			_layers = _adapter.get_floor_layer_map(_world, floor_uid)
			_floor_layers[floor_uid] = _layers.duplicate()
			_index_floor_layers(floor_uid, _layers)
		if has_scenes_configured():
			var owner_scene: String = _adapter.get_scene_for_floor(_world, floor_uid)
			if not owner_scene.is_empty():
				_adapter.set_active_scene(_world, owner_scene, floor_uid, true)
				_active_scene_uid = owner_scene
		return true

	func rename_floor(floor_uid: String, new_name: String) -> bool:
		if not _is_ready or _adapter == null or floor_uid.is_empty():
			return false
		var res: Dictionary = _adapter.rename_floor(_world, floor_uid, new_name)
		if not bool(res.get("ok", false)):
			_warn("重命名楼层失败（%s）：%s" % [floor_uid, str(res.get("reason", "unknown"))])
			return false
		return true

	func add_layer(
		name: String,
		kind: String = "entity",
		access: String = "all",
		floor_uid: String = "",
		viewers: Array = [],
		locked: bool = false,
		visible: bool = true,
		persistent: bool = true
	) -> String:
		if not _is_ready or _adapter == null:
			return ""
		var target_floor: String = floor_uid if not floor_uid.is_empty() else _floor_uid
		var res: Dictionary = _adapter.create_layer(
			_world,
			target_floor,
			name,
			kind,
			access,
			viewers,
			locked,
			visible,
			persistent
		)
		if not bool(res.get("ok", false)):
			_warn("新建图层失败（" + name + "）：" + str(res.get("reason", "unknown")))
			return ""
		var new_layer_uid: String = str(res["layer_uid"])
		_layer_to_floor[new_layer_uid] = target_floor
		var normalized_kind: String = str(res["kind"])
		if not _floor_layers.has(target_floor):
			_floor_layers[target_floor] = _adapter.get_floor_layer_map(_world, target_floor)
		var floor_map: Dictionary = _floor_layers[target_floor]
		if not floor_map.has(normalized_kind):
			floor_map[normalized_kind] = new_layer_uid
			if target_floor == _floor_uid:
				_layers[normalized_kind] = new_layer_uid
		return new_layer_uid

	func has_scenes_configured() -> bool:
		if not _is_ready or _adapter == null:
			return false
		return bool(_adapter.has_scene_repository_state(_world))

	func configure_entry_scene(
		scene_name: String = "主场景",
		initial_floor_name: String = "",
		cover_asset: String = ""
	) -> String:
		if not _is_ready or _adapter == null:
			return ""
		var res: Dictionary = _adapter.configure_entry_scene_state(_world, scene_name, cover_asset)
		if not bool(res.get("ok", false)):
			_warn("配置入口场景失败：" + str(res.get("reason", "unknown")))
			return ""
		if bool(res.get("cover_sanitized", false)):
			_warn("场景“%s”封面路径非法（仅允许已归档 asset:// 64位十六进制 PNG/JPG/WEBP/BMP），已重置为空。" % scene_name)
		var entry_uid: String = str(res.get("entry_scene_uid", ""))
		if not initial_floor_name.is_empty():
			var default_fuid: String = str(res.get("default_floor_uid", _floor_uid))
			if not default_fuid.is_empty():
				rename_floor(default_fuid, initial_floor_name)
		if _active_scene_uid.is_empty():
			_active_scene_uid = entry_uid
		_rebuild_layer_to_floor_index()
		return entry_uid

	func add_scene(
		scene_name: String,
		initial_floor_name: String = "1F",
		floor_color: Color = Color(0.32, 0.56, 0.44),
		cover_asset: String = "",
		make_active: bool = true
	) -> String:
		if not _is_ready or _adapter == null:
			return ""
		var res: Dictionary = _adapter.create_scene(
			_world,
			scene_name,
			initial_floor_name,
			floor_color,
			cover_asset,
			make_active
		)
		if not bool(res.get("ok", false)):
			_warn("新建场景失败（" + scene_name + "）：" + str(res.get("reason", "unknown")))
			return ""
		if bool(res.get("cover_sanitized", false)):
			_warn("场景“%s”封面路径非法（仅允许已归档 asset:// 64位十六进制 PNG/JPG/WEBP/BMP），已重置为空。" % scene_name)
		var scene_uid: String = str(res["scene_uid"])
		var floor_uid: String = str(res["floor_uid"])
		var layer_map: Dictionary = (res["layers"] as Dictionary).duplicate()
		_floor_layers[floor_uid] = layer_map
		_index_floor_layers(floor_uid, layer_map)
		if make_active:
			_active_scene_uid = scene_uid
			_floor_uid = floor_uid
			_layers = layer_map.duplicate()
		elif _active_scene_uid.is_empty():
			_active_scene_uid = get_entry_scene_uid()
		return scene_uid

	func set_active_scene(
		scene_uid: String,
		floor_uid: String = "",
		mark_host_visited: bool = true
	) -> bool:
		if not _is_ready or _adapter == null or scene_uid.is_empty():
			return false
		var res: Dictionary = _adapter.set_active_scene(_world, scene_uid, floor_uid, mark_host_visited)
		if not bool(res.get("ok", false)):
			_warn("切换当前场景失败：" + str(res.get("reason", "unknown")))
			return false
		var resolved_floor: String = str(res.get("floor_uid", ""))
		_active_scene_uid = scene_uid
		_floor_uid = resolved_floor
		if _floor_layers.has(resolved_floor):
			_layers = (_floor_layers[resolved_floor] as Dictionary).duplicate()
		else:
			_layers = _adapter.get_floor_layer_map(_world, resolved_floor)
			_floor_layers[resolved_floor] = _layers.duplicate()
			_index_floor_layers(resolved_floor, _layers)
		return true

	func set_entry_scene(scene_uid: String) -> bool:
		if not _is_ready or _adapter == null or scene_uid.is_empty():
			return false
		var res: Dictionary = _adapter.set_entry_scene(_world, scene_uid)
		if not bool(res.get("ok", false)):
			_warn("设置入口场景失败：" + str(res.get("reason", "unknown")))
			return false
		return true

	func rename_scene(scene_uid: String, new_name: String) -> bool:
		if not _is_ready or _adapter == null or scene_uid.is_empty():
			return false
		var res: Dictionary = _adapter.rename_scene(_world, scene_uid, new_name)
		if not bool(res.get("ok", false)):
			_warn("重命名场景失败（%s）：%s" % [scene_uid, str(res.get("reason", "unknown"))])
			return false
		return true

	func set_scene_cover_asset(scene_uid: String, cover_asset: String) -> bool:
		if not _is_ready or _adapter == null or scene_uid.is_empty():
			return false
		var res: Dictionary = _adapter.set_scene_cover_asset(_world, scene_uid, cover_asset)
		if not bool(res.get("ok", false)):
			_warn("设置场景封面失败（%s）：%s" % [scene_uid, str(res.get("reason", "unknown"))])
			return false
		if bool(res.get("cover_sanitized", false)):
			_warn("场景“%s”封面引用非法（仅允许已归档 asset:// 64位十六进制 PNG/JPG/WEBP/BMP），已重置为空。" % scene_uid)
		return true

	func set_scene_host_view(
		scene_uid: String,
		camera_pos_src: Vector2,
		camera_zoom: Vector2 = Vector2.ONE,
		active_floor_uid: String = ""
	) -> bool:
		if not _is_ready or _adapter == null or scene_uid.is_empty():
			return false
		var res: Dictionary = _adapter.set_scene_host_view(
			_world,
			scene_uid,
			to_world_pos(camera_pos_src),
			camera_zoom,
			active_floor_uid
		)
		if not bool(res.get("ok", false)):
			_warn("保存场景视角失败（%s）：%s" % [scene_uid, str(res.get("reason", "unknown"))])
			return false
		return true

	func get_entry_scene_uid() -> String:
		if not _is_ready or _adapter == null:
			return ""
		return str(_adapter.get_entry_scene_uid(_world))

	func get_active_scene_uid() -> String:
		if not _is_ready or _adapter == null:
			return ""
		if has_scenes_configured():
			var active_in_world: String = str(_adapter.get_active_scene_uid(_world))
			if not active_in_world.is_empty():
				return active_in_world
		return _active_scene_uid

	func get_scene_uids() -> Array[String]:
		if not _is_ready or _adapter == null:
			return []
		var raw: Array[String] = _adapter.get_scene_uids(_world)
		return raw

	func add_floor_to_scene(
		scene_uid: String,
		floor_name: String,
		color: Color = Color(0.28, 0.65, 0.40),
		make_default: bool = false,
		make_active: bool = false
	) -> String:
		if not _is_ready or _adapter == null or scene_uid.is_empty():
			return ""
		var res: Dictionary = _adapter.add_floor_to_scene(
			_world,
			scene_uid,
			floor_name,
			color,
			make_default,
			make_active
		)
		if not bool(res.get("ok", false)):
			_warn("向场景追加楼层失败（%s -> %s）：%s" % [scene_uid, floor_name, str(res.get("reason", "unknown"))])
			return ""
		var floor_uid: String = str(res["floor_uid"])
		var layer_map: Dictionary = (res["layers"] as Dictionary).duplicate()
		_floor_layers[floor_uid] = layer_map
		_index_floor_layers(floor_uid, layer_map)
		if make_active:
			_active_scene_uid = scene_uid
			_floor_uid = floor_uid
			_layers = layer_map.duplicate()
		return floor_uid

	func set_scene_default_floor(scene_uid: String, floor_uid: String) -> bool:
		if not _is_ready or _adapter == null or scene_uid.is_empty():
			return false
		var res: Dictionary = _adapter.set_scene_default_floor(_world, scene_uid, floor_uid)
		if not bool(res.get("ok", false)):
			_warn("设置场景默认楼层失败：" + str(res.get("reason", "unknown")))
			return false
		return true

	func move_floor_to_scene(
		floor_uid: String,
		target_scene_uid: String,
		make_default: bool = false
	) -> bool:
		if not _is_ready or _adapter == null or floor_uid.is_empty() or target_scene_uid.is_empty():
			return false
		var res: Dictionary = _adapter.attach_existing_floor_to_scene(_world, target_scene_uid, floor_uid, make_default)
		if not bool(res.get("ok", false)):
			_warn("跨场景移动楼层失败（%s -> %s）：%s" % [floor_uid, target_scene_uid, str(res.get("reason", "unknown"))])
			return false
		if floor_uid == _floor_uid:
			_active_scene_uid = target_scene_uid
		return true

	func get_scene_floor_uids(scene_uid: String = "") -> Array[String]:
		if not _is_ready or _adapter == null:
			return []
		var target_scene: String = scene_uid if not scene_uid.is_empty() else get_active_scene_uid()
		if target_scene.is_empty():
			return []
		return _adapter.get_scene_floors(_world, target_scene)

	func get_scene_default_floor_uid(scene_uid: String = "") -> String:
		if not _is_ready or _adapter == null:
			return ""
		var target_scene: String = scene_uid if not scene_uid.is_empty() else get_active_scene_uid()
		if target_scene.is_empty():
			return ""
		return str(_adapter.get_scene_default_floor_uid(_world, target_scene))

	func get_scene_for_floor(floor_uid: String = "") -> String:
		if not _is_ready or _adapter == null:
			return ""
		var target_floor: String = floor_uid if not floor_uid.is_empty() else _floor_uid
		if target_floor.is_empty():
			return ""
		return str(_adapter.get_scene_for_floor(_world, target_floor))

	func get_scene_layer_uid(scene_uid: String, kind: String, floor_uid: String = "") -> String:
		if not _is_ready or _adapter == null or scene_uid.is_empty():
			return ""
		var scene_floors: Array[String] = get_scene_floor_uids(scene_uid)
		if scene_floors.is_empty():
			return ""
		var target_floor: String = floor_uid if not floor_uid.is_empty() else get_scene_default_floor_uid(scene_uid)
		if target_floor.is_empty() or not (target_floor in scene_floors):
			return ""
		return get_layer_uid(kind, target_floor)

	func get_floor_layers(floor_uid: String = "") -> Array:
		if not _is_ready or _adapter == null:
			return []
		var target_floor: String = floor_uid if not floor_uid.is_empty() else _floor_uid
		if target_floor.is_empty():
			return []
		return _adapter.get_floor_layers(_world, target_floor)

	func begin_bounds_preview(total_items: int, source_bounds: Rect2) -> void:
		if not _is_ready or _session == null or _adapter == null:
			return
		_preview_active = true
		_adapter.begin_preview(_session.get_host(), total_items, source_bounds, _source_to_world)

	func finish_geometry_preview() -> bool:
		if _session == null or _adapter == null:
			return true
		return bool(_adapter.finish_geometry_preview(_session.get_host()))

	func add_map_tile(
		source_id: String,
		name: String,
		center_src: Vector2,
		size_src: Vector2,
		sprite_ref: String,
		rotation_rad: float = 0.0,
		scale: Vector2 = Vector2.ONE,
		hidden: bool = false,
		layer_uid_override: String = "",
		locked: bool = false
	) -> String:
		var target_layer: String = layer_uid_override if not layer_uid_override.is_empty() else str(_layers.get("map", ""))
		return _add_sprite_entity(
			target_layer,
			"map",
			source_id,
			name,
			center_src,
			size_src,
			sprite_ref,
			rotation_rad,
			scale,
			false,
			hidden,
			32.0,
			locked
		)

	func add_token(
		source_id: String,
		name: String,
		center_src: Vector2,
		size_src: Vector2,
		sprite_ref: String,
		rotation_rad: float = 0.0,
		scale: Vector2 = Vector2.ONE,
		hidden: bool = false,
		footprint_radius: float = 32.0,
		locked: bool = false,
		permission_state: Dictionary = {},
		layer_uid_override: String = ""
	) -> String:
		var target_layer: String = layer_uid_override if not layer_uid_override.is_empty() else str(_layers.get("entity", ""))
		return _add_sprite_entity(
			target_layer,
			"object",
			source_id,
			name,
			center_src,
			size_src,
			sprite_ref,
			rotation_rad,
			scale,
			true,
			hidden,
			footprint_radius,
			locked,
			permission_state
		)

	func add_object_sprite(
		source_id: String,
		name: String,
		center_src: Vector2,
		size_src: Vector2,
		sprite_ref: String,
		rotation_rad: float = 0.0,
		scale: Vector2 = Vector2.ONE,
		hidden: bool = false,
		layer_uid_override: String = "",
		locked: bool = false
	) -> String:
		var target_layer: String = layer_uid_override if not layer_uid_override.is_empty() else str(_layers.get("entity", ""))
		return _add_sprite_entity(
			target_layer,
			"object",
			source_id,
			name,
			center_src,
			size_src,
			sprite_ref,
			rotation_rad,
			scale,
			false,
			hidden,
			32.0,
			locked
		)

	func add_polygon_obstacle(
		source_id: String,
		name: String,
		center_src: Vector2,
		polygons_src: Array,
		kind: String = "wall",
		is_open_door: bool = false,
		enabled: bool = true,
		layer_uid_override: String = ""
	) -> String:
		if not _is_ready or _adapter == null:
			return ""
		var built: Dictionary = _adapter.make_polygon_obstacle_visual(polygons_src, kind, is_open_door, enabled)
		var skipped_rings: int = int(built.get("skipped_rings", 0))
		if skipped_rings > 0:
			_warn("障碍物“%s”已过滤 %d 个少于 3 顶点的退化多边形环。" % [name if not name.is_empty() else source_id, skipped_rings])
		if int(built.get("valid_face_count", 0)) <= 0:
			_warn("障碍物“%s”无有效闭合面，已跳过写入。" % [name if not name.is_empty() else source_id])
			return ""
		if bool(built.get("truncated", false)):
			_warn("障碍物“%s”顶点数超过宿主矢量上限，已按上限安全截断。" % [name if not name.is_empty() else source_id])

		var obstacle_size: Vector2 = built["size"]
		var visual: Dictionary = built["visual"]
		var normalized_kind: String = kind.strip_edges().to_lower()
		var default_label: String = _default_obstacle_label(normalized_kind, is_open_door)
		var final_label: String = name if not name.is_empty() else default_label
		var preview_kind: String = "door" if normalized_kind in ["door", "window"] else "wall"
		var target_layer: String = layer_uid_override if not layer_uid_override.is_empty() else str(_layers.get("obstacle", ""))
		return _commit_entity(
			target_layer,
			preview_kind,
			source_id,
			final_label,
			center_src,
			obstacle_size,
			0.0,
			Vector2.ONE,
			visual,
			false,
			false
		)

	func add_wall(
		source_id: String,
		name: String,
		center_src: Vector2,
		polygons_src: Array,
		enabled: bool = true,
		layer_uid_override: String = ""
	) -> String:
		return add_polygon_obstacle(source_id, name, center_src, polygons_src, "wall", false, enabled, layer_uid_override)

	func add_door(
		source_id: String,
		name: String,
		center_src: Vector2,
		polygons_src: Array,
		is_open: bool = false,
		enabled: bool = true,
		layer_uid_override: String = ""
	) -> String:
		return add_polygon_obstacle(source_id, name, center_src, polygons_src, "door", is_open, enabled, layer_uid_override)

	func add_window(
		source_id: String,
		name: String,
		center_src: Vector2,
		polygons_src: Array,
		is_open: bool = false,
		enabled: bool = true,
		layer_uid_override: String = ""
	) -> String:
		return add_polygon_obstacle(source_id, name, center_src, polygons_src, "window", is_open, enabled, layer_uid_override)

	func add_glass_wall(
		source_id: String,
		name: String,
		center_src: Vector2,
		polygons_src: Array,
		enabled: bool = true,
		layer_uid_override: String = ""
	) -> String:
		return add_polygon_obstacle(source_id, name, center_src, polygons_src, "glass", false, enabled, layer_uid_override)

	func add_air_cutout(
		source_id: String,
		name: String,
		center_src: Vector2,
		polygons_src: Array,
		enabled: bool = true,
		layer_uid_override: String = ""
	) -> String:
		return add_polygon_obstacle(source_id, name, center_src, polygons_src, "air", false, enabled, layer_uid_override)

	func extrude_segment_to_quad(
		p0: Vector2,
		p1: Vector2,
		half_width: float = 6.0,
		min_length: float = 0.5
	) -> PackedVector2Array:
		if _adapter == null:
			return PackedVector2Array()
		return _adapter.extrude_segment_to_quad(p0, p1, half_width, min_length)

	func add_segment_obstacle(
		source_id: String,
		name: String,
		p0_src: Vector2,
		p1_src: Vector2,
		half_width_src: float = 6.0,
		kind: String = "wall",
		is_open_door: bool = false,
		enabled: bool = true,
		layer_uid_override: String = ""
	) -> String:
		if not _is_ready or _adapter == null:
			return ""
		var label_hint: String = name if not name.is_empty() else source_id
		if (
			not is_finite(p0_src.x)
			or not is_finite(p0_src.y)
			or not is_finite(p1_src.x)
			or not is_finite(p1_src.y)
			or not is_finite(half_width_src)
		):
			_warn("障碍物“%s”包含非有限线段坐标，已跳过写入。" % label_hint)
			return ""
		var center_src: Vector2 = p0_src * 0.5 + p1_src * 0.5
		if not is_finite(center_src.x) or not is_finite(center_src.y):
			_warn("障碍物“%s”线段中心坐标溢出，已跳过写入。" % label_hint)
			return ""
		# 先平移至相对中点的局部坐标再挤出，彻底规避大坐标 (如 1e7) 下的 float32 ULP 精度坍缩。
		var local_p0: Vector2 = p0_src - center_src
		var local_p1: Vector2 = p1_src - center_src
		var quad: PackedVector2Array = _adapter.extrude_segment_to_quad(local_p0, local_p1, half_width_src)
		if quad.size() < 4:
			_warn("障碍物“%s”线段退化或长度不足，已跳过写入。" % label_hint)
			return ""
		return add_polygon_obstacle(
			source_id,
			name,
			center_src,
			[quad],
			kind,
			is_open_door,
			enabled,
			layer_uid_override
		)

	func add_segment_wall(
		source_id: String,
		name: String,
		p0_src: Vector2,
		p1_src: Vector2,
		half_width_src: float = 6.0,
		enabled: bool = true,
		layer_uid_override: String = ""
	) -> String:
		return add_segment_obstacle(source_id, name, p0_src, p1_src, half_width_src, "wall", false, enabled, layer_uid_override)

	func add_segment_door(
		source_id: String,
		name: String,
		p0_src: Vector2,
		p1_src: Vector2,
		half_width_src: float = 6.0,
		is_open: bool = false,
		enabled: bool = true,
		layer_uid_override: String = ""
	) -> String:
		return add_segment_obstacle(source_id, name, p0_src, p1_src, half_width_src, "door", is_open, enabled, layer_uid_override)

	func add_segment_window(
		source_id: String,
		name: String,
		p0_src: Vector2,
		p1_src: Vector2,
		half_width_src: float = 6.0,
		is_open: bool = false,
		enabled: bool = true,
		layer_uid_override: String = ""
	) -> String:
		return add_segment_obstacle(source_id, name, p0_src, p1_src, half_width_src, "window", is_open, enabled, layer_uid_override)

	func add_segment_glass_wall(
		source_id: String,
		name: String,
		p0_src: Vector2,
		p1_src: Vector2,
		half_width_src: float = 6.0,
		enabled: bool = true,
		layer_uid_override: String = ""
	) -> String:
		return add_segment_obstacle(source_id, name, p0_src, p1_src, half_width_src, "glass", false, enabled, layer_uid_override)

	func add_text_note(
		source_id: String,
		text: String,
		center_src: Vector2,
		size_src: Vector2,
		font_size: float = 24.0,
		hidden: bool = false,
		layer_uid_override: String = ""
	) -> String:
		if not _is_ready or _adapter == null:
			return ""
		var visual: Dictionary = _adapter.make_text_visual(text, font_size)
		var label: String = text if not text.is_empty() else "文字注释"
		var target_layer: String = layer_uid_override if not layer_uid_override.is_empty() else str(_layers.get("entity", ""))
		return _commit_entity(
			target_layer,
			"text",
			source_id,
			label,
			center_src,
			size_src,
			0.0,
			Vector2.ONE,
			visual,
			false,
			hidden
		)

	func add_text_pin(
		source_id: String,
		text: String,
		center_src: Vector2,
		name: String = "",
		keep_screen_size: bool = true,
		size_src: Vector2 = Vector2(48.0, 60.0),
		hidden: bool = false,
		layer_uid_override: String = ""
	) -> String:
		if not _is_ready or _adapter == null:
			return ""
		var visual: Dictionary = _adapter.make_sprite_visual("")
		var label: String = name if not name.is_empty() else (text.left(32) if not text.is_empty() else "文本图钉")
		var target_layer: String = layer_uid_override if not layer_uid_override.is_empty() else str(_layers.get("entity", ""))
		var entity_id: String = _commit_entity(
			target_layer,
			"text",
			source_id,
			label,
			center_src,
			size_src,
			0.0,
			Vector2.ONE,
			visual,
			false,
			hidden
		)
		if entity_id.is_empty():
			return ""
		var note_state: Dictionary = _adapter.make_entity_note_state(text, true, keep_screen_size)
		attach_component(entity_id, _adapter.COMP_ENTITY_NOTE_SCRIPT, note_state, false)
		return entity_id

	func add_vector_drawing(
		source_id: String,
		name: String,
		center_src: Vector2,
		size_src: Vector2,
		paths_local: Array,
		fill_color: Color = Color.TRANSPARENT,
		line_color: Color = Color(0.086, 0.227, 0.275),
		rotation_rad: float = 0.0,
		scale: Vector2 = Vector2.ONE,
		hidden: bool = false,
		layer_uid_override: String = ""
	) -> String:
		if not _is_ready or _adapter == null:
			return ""
		var visual: Dictionary = _adapter.make_custom_drawing_visual(
			size_src,
			paths_local,
			fill_color,
			line_color
		)
		var target_layer: String = layer_uid_override if not layer_uid_override.is_empty() else str(_layers.get("entity", ""))
		return _commit_entity(
			target_layer,
			"object",
			source_id,
			name,
			center_src,
			size_src,
			rotation_rad,
			scale,
			visual,
			false,
			hidden
		)

	func attach_component(
		entity_id: String,
		script_path: String,
		state: Dictionary = {},
		parked: bool = false
	) -> bool:
		if not _is_ready or _adapter == null or entity_id.is_empty():
			return false
		var entity: Dictionary = _lookup_entity(entity_id)
		var res: Dictionary = _adapter.append_entity_component(entity, script_path, state, parked)
		if not bool(res.get("ok", false)):
			_warn("挂载组件失败（%s -> %s）：%s" % [entity_id, script_path, str(res.get("reason", "unknown"))])
			return false
		return true

	func suppress_entity_fallback_box(entity_id: String) -> bool:
		if not _is_ready or _adapter == null or entity_id.is_empty():
			return false
		var entity: Dictionary = _lookup_entity(entity_id)
		return bool(_adapter.suppress_entity_fallback_box(entity))

	func add_point_light(
		source_id: String,
		center_src: Vector2,
		radius_world: float,
		view_angle_deg: float = 360.0,
		name: String = "Light",
		hidden: bool = false,
		enabled: bool = true,
		size_src: Vector2 = Vector2(32.0, 32.0),
		layer_uid_override: String = ""
	) -> String:
		if not _is_ready or _adapter == null:
			return ""
		var final_name: String = name if not name.strip_edges().is_empty() else "Light"
		var entity_id: String = add_object_sprite(
			source_id,
			final_name,
			center_src,
			size_src,
			"",
			0.0,
			Vector2.ONE,
			hidden,
			layer_uid_override,
			false
		)
		if entity_id.is_empty():
			return ""
		suppress_entity_fallback_box(entity_id)
		attach_simple_light(entity_id, radius_world, view_angle_deg, enabled)
		return entity_id

	func attach_unit_marker(entity_id: String) -> bool:
		if not _is_ready or _adapter == null:
			return false
		return attach_component(entity_id, _adapter.COMP_UNIT_SCRIPT, _adapter.make_unit_marker_state(), false)

	func attach_portal(entity_id: String, pair_key: String) -> bool:
		if not _is_ready or _adapter == null:
			return false
		return attach_component(entity_id, _adapter.COMP_PORTAL_SCRIPT, _adapter.make_portal_state(pair_key), false)

	func attach_simple_vision(
		entity_id: String,
		radius: float = 640.0,
		view_angle_deg: float = 360.0,
		requires_light: bool = false,
		enabled: bool = true
	) -> bool:
		if not _is_ready or _adapter == null:
			return false
		var state: Dictionary = _adapter.make_simple_vision_state(radius, view_angle_deg, requires_light, enabled)
		return attach_component(entity_id, _adapter.COMP_SIMPLE_VISION_SCRIPT, state, false)

	func attach_simple_light(
		entity_id: String,
		radius: float = 640.0,
		view_angle_deg: float = 360.0,
		enabled: bool = true
	) -> bool:
		if not _is_ready or _adapter == null:
			return false
		var state: Dictionary = _adapter.make_simple_light_state(radius, view_angle_deg, enabled)
		return attach_component(entity_id, _adapter.COMP_SIMPLE_LIGHT_SCRIPT, state, false)

	func add_scene_box(
		source_id: String,
		name: String,
		center_src: Vector2,
		target_scene_uid: String,
		side_cells: float = 1.5,
		cover_asset: String = "",
		preview_policy: String = "visited_unlock",
		all_players_can_enter: bool = true,
		owner_player_ids: Array = [],
		hidden_from_players: bool = false,
		locked: bool = false,
		layer_uid_override: String = ""
	) -> String:
		if not _is_ready or _adapter == null:
			return ""
		var target_layer: String = layer_uid_override if not layer_uid_override.is_empty() else str(_layers.get("entity", ""))
		if target_layer.is_empty():
			_warn("创建场景盒子失败：目标图层为空。")
			return ""
		var owner_floor_uid: String = _resolve_floor_for_layer(target_layer)
		var center_world: Vector2 = to_world_pos(center_src)
		var safe_cells: float = side_cells if is_finite(side_cells) else 1.5
		var side_world: float = safe_cells * _adapter.WORLD_UNITS_PER_CELL
		var res: Dictionary = _adapter.append_scene_box_entity(
			_world,
			owner_floor_uid,
			target_layer,
			source_id,
			name,
			center_world,
			target_scene_uid,
			side_world,
			cover_asset,
			preview_policy,
			all_players_can_enter,
			owner_player_ids,
			hidden_from_players,
			locked
		)
		if not bool(res.get("ok", false)):
			_warn("创建场景盒子失败（%s）：%s" % [name if not name.is_empty() else source_id, str(res.get("reason", "unknown"))])
			return ""
		if bool(res.get("cover_sanitized", false)):
			_warn("场景盒子“%s”封面引用非法（仅允许已归档 asset:// 64位十六进制 PNG/JPG/WEBP/BMP），已重置为空。" % (name if not name.is_empty() else source_id))
		var safe_cover: String = str(res.get("cover_asset", ""))
		if not safe_cover.is_empty():
			_used_sprite_refs[safe_cover] = true
		_entity_count += 1
		var entity_id: String = str(res.get("entity_id", ""))
		var entity_var: Variant = res.get("entity", null)
		if not entity_id.is_empty() and entity_var is Dictionary:
			_entity_by_id[entity_id] = entity_var
			if _preview_active and _session != null:
				_adapter.preview_entity(_session.get_host(), entity_var as Dictionary, "object")
		return entity_id

	func attach_scene_box(
		entity_id: String,
		target_scene_uid: String,
		cover_asset: String = "",
		preview_policy: String = "visited_unlock",
		all_players_can_enter: bool = true,
		owner_player_ids: Array = []
	) -> bool:
		if not _is_ready or _adapter == null or entity_id.is_empty():
			return false
		var res: Dictionary = _adapter.attach_scene_box_to_entity(
			_world,
			entity_id,
			target_scene_uid,
			cover_asset,
			preview_policy,
			all_players_can_enter,
			owner_player_ids
		)
		if not bool(res.get("ok", false)):
			_warn("挂载场景盒子组件失败（%s）：%s" % [entity_id, str(res.get("reason", "unknown"))])
			return false
		if bool(res.get("cover_sanitized", false)):
			_warn("场景盒子“%s”封面引用非法（仅允许已归档 asset:// 64位十六进制 PNG/JPG/WEBP/BMP），已重置为空。" % entity_id)
		var safe_cover: String = str(res.get("cover_asset", ""))
		if not safe_cover.is_empty():
			_used_sprite_refs[safe_cover] = true
		return true

	func set_module_state(module_id: String, version: int, state: Dictionary) -> bool:
		if not _is_ready or _adapter == null:
			return false
		var res: Dictionary = _adapter.set_module_state(_world, module_id, version, state)
		if not bool(res.get("ok", false)):
			_warn("写入模块数据失败（%s）：%s" % [module_id, str(res.get("reason", "unknown"))])
			return false
		return true

	func configure_grid_alignment(
		cell_size: float = 64.0,
		snap_enabled: bool = true,
		offset: Vector2 = Vector2.ZERO,
		color: Color = Color(0.5, 0.55, 0.65, 0.7),
		line_width: float = 1.0,
		snap_strength: float = 0.1
	) -> bool:
		if not _is_ready or _adapter == null:
			return false
		var state: Dictionary = _adapter.make_grid_alignment_state(
			cell_size,
			snap_enabled,
			offset,
			color,
			line_width,
			snap_strength
		)
		return set_module_state("grid_alignment", 1, state)

	func sanitize_module_data(value: Variant) -> Variant:
		if _adapter == null:
			return value
		return _adapter.sanitize_module_value(value)

	func can_fit_module_state(
		module_id: String,
		version: int,
		state: Dictionary,
		max_world_bytes: int = 30 * 1024 * 1024
	) -> bool:
		if not _is_ready or _adapter == null:
			return false
		return bool(_adapter.can_fit_module_state(_world, module_id, version, state, max_world_bytes))

	func build_result(source_record_count: int = 0, merged_wall_count: int = 0) -> Dictionary:
		if not _is_ready or _adapter == null:
			if not _setup_result.is_empty():
				return _setup_result
			return {"ok": false, "reason": "world_builder_not_initialized"}
		var archived_total: int = _session.get_archived_asset_count() if _session != null else 0
		var asset_total: int = maxi(_used_sprite_refs.size(), archived_total)
		return _adapter.build_prepare_ok(_world, asset_total, source_record_count, merged_wall_count)

	func _index_floor_layers(floor_uid: String, layers_map: Dictionary) -> void:
		if floor_uid.is_empty():
			return
		for raw_kind: Variant in layers_map.keys():
			var uid: String = str(layers_map[raw_kind])
			if not uid.is_empty():
				_layer_to_floor[uid] = floor_uid

	func _rebuild_layer_to_floor_index() -> void:
		_layer_to_floor.clear()
		var catalog_var: Variant = _world.get("catalog", null)
		if not (catalog_var is Dictionary):
			return
		var layers_var: Variant = (catalog_var as Dictionary).get("layers", null)
		if not (layers_var is Dictionary):
			return
		var layer_floors_var: Variant = (layers_var as Dictionary).get("floors", null)
		if not (layer_floors_var is Array):
			return
		for raw_floor: Variant in layer_floors_var as Array:
			if not (raw_floor is Dictionary):
				continue
			var fd: Dictionary = raw_floor as Dictionary
			var fuid: String = str(fd.get("floor_uid", ""))
			if fuid.is_empty():
				continue
			var rows_var: Variant = fd.get("layers", [])
			if rows_var is Array:
				var kind_map: Dictionary = {}
				for raw_layer: Variant in rows_var as Array:
					if raw_layer is Dictionary:
						var lrow: Dictionary = raw_layer as Dictionary
						var luid: String = str(lrow.get("layer_uid", ""))
						var lkind: String = str(lrow.get("kind", ""))
						if not luid.is_empty():
							_layer_to_floor[luid] = fuid
							if not lkind.is_empty() and not kind_map.has(lkind):
								kind_map[lkind] = luid
				if not _floor_layers.has(fuid) and not kind_map.is_empty():
					_floor_layers[fuid] = kind_map

	func _resolve_floor_for_layer(layer_uid: String) -> String:
		if not layer_uid.is_empty():
			var cached_floor: String = str(_layer_to_floor.get(layer_uid, ""))
			if not cached_floor.is_empty():
				return cached_floor
			if _adapter != null:
				var looked_up: String = str(_adapter.get_floor_for_layer(_world, layer_uid))
				if not looked_up.is_empty():
					_layer_to_floor[layer_uid] = looked_up
					return looked_up
		return _floor_uid

	func _warn(message: String) -> void:
		if _session != null:
			_session.add_warning(message)

	func _default_obstacle_label(kind: String, is_open: bool) -> String:
		match kind:
			"door":
				return "门（开）" if is_open else "门（关）"
			"window":
				return "窗（开）" if is_open else "窗（关）"
			"glass":
				return "可见遮挡体"
			"air":
				return "空气挖空"
			_:
				return "墙体"

	func _add_sprite_entity(
		layer_uid: String,
		preview_kind: String,
		source_id: String,
		label: String,
		center_src: Vector2,
		size_src: Vector2,
		sprite_ref: String,
		rotation_rad: float,
		scale: Vector2,
		is_unit: bool,
		hidden: bool,
		footprint_radius: float = 32.0,
		locked: bool = false,
		permission_state: Dictionary = {}
	) -> String:
		if not _is_ready or _adapter == null:
			return ""
		var checked_sprite: Dictionary = _adapter.sanitize_sprite_path(sprite_ref)
		if not bool(checked_sprite.get("ok", false)):
			_warn("实体“%s”图片路径非法（宿主禁止 user://，仅允许 asset:// 或 res://），已回退占位色块：%s" % [
				label if not label.is_empty() else source_id,
				str(checked_sprite.get("rejected", sprite_ref)),
			])
		var safe_ref: String = str(checked_sprite.get("path", ""))
		if not safe_ref.is_empty():
			_used_sprite_refs[safe_ref] = true
		var visual: Dictionary = _adapter.make_sprite_visual(safe_ref)
		return _commit_entity(
			layer_uid,
			preview_kind,
			source_id,
			label,
			center_src,
			size_src,
			rotation_rad,
			scale,
			visual,
			is_unit,
			hidden,
			footprint_radius,
			locked,
			permission_state
		)

	func _lookup_entity(entity_id: String) -> Dictionary:
		var cached: Variant = _entity_by_id.get(entity_id, null)
		if cached is Dictionary and str((cached as Dictionary).get("id", "")) == entity_id:
			return cached as Dictionary
		if _adapter != null:
			var found: Dictionary = _adapter.find_entity_by_id(_world, entity_id)
			if not found.is_empty():
				_entity_by_id[entity_id] = found
			return found
		return {}

	func _commit_entity(
		layer_uid: String,
		preview_kind: String,
		source_id: String,
		label: String,
		center_src: Vector2,
		size_src: Vector2,
		rotation_rad: float,
		scale: Vector2,
		visual: Dictionary,
		is_unit: bool,
		hidden: bool,
		footprint_radius: float = 32.0,
		locked: bool = false,
		permission_state: Dictionary = {}
	) -> String:
		if layer_uid.is_empty():
			return ""
		var owner_floor_uid: String = _resolve_floor_for_layer(layer_uid)
		var entity: Dictionary = _adapter.append_entity(
			_world,
			owner_floor_uid,
			layer_uid,
			source_id,
			label,
			center_src,
			size_src,
			rotation_rad,
			scale,
			_source_to_world,
			visual,
			is_unit,
			hidden,
			_adapter.DEFAULT_ID_NAMESPACE,
			footprint_radius,
			locked,
			permission_state
		)
		_entity_count += 1
		var entity_id: String = str(entity.get("id", ""))
		if not entity_id.is_empty():
			_entity_by_id[entity_id] = entity
		if _preview_active and _session != null:
			_adapter.preview_entity(_session.get_host(), entity, preview_kind)
		return entity_id
