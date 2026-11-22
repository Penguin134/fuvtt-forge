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

const SDK_VERSION: String = "1.1.0"
const ADAPTER_REL_PATH: String = "adapters/host_v1_adapter.gd"
const DEV_FALLBACK_ADAPTER_PATH: String = "shared/sdk/fu_sdk/adapters/host_v1_adapter.gd"

var _adapter_script: Script = null


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


func _load_adapter_from_outer_script() -> Script:
	var outer_scr := get_script() as Script
	if outer_scr != null and not outer_scr.resource_path.is_empty():
		var clean_path: String = outer_scr.resource_path.split("::")[0]
		var candidate: String = clean_path.get_base_dir().path_join(ADAPTER_REL_PATH)
		if FileAccess.file_exists(candidate) or ResourceLoader.exists(candidate):
			return load(candidate) as Script
	if FileAccess.file_exists(DEV_FALLBACK_ADAPTER_PATH) or ResourceLoader.exists(DEV_FALLBACK_ADAPTER_PATH):
		return load(DEV_FALLBACK_ADAPTER_PATH) as Script
	return null


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

		var effective_proxy: String = proxy
		if effective_proxy.is_empty() and _options.has("proxy"):
			effective_proxy = str(_options.get("proxy", ""))

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
		remote_assets: Dictionary = {}
	) -> Dictionary:
		if _adapter != null:
			return _adapter.build_inspect_ok(source_path, counts_override, remote_assets)
		var fallback_sha256: String = ""
		if not source_path.is_empty() and FileAccess.file_exists(source_path):
			fallback_sha256 = FileAccess.get_sha256(source_path)
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
		return {
			"ok": true,
			"sha256": fallback_sha256,
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
	var _source_units_per_cell: float = 150.0
	var _source_to_world: float = 64.0 / 150.0
	var _is_ready: bool = false
	var _setup_result: Dictionary = {}
	var _preview_active: bool = false
	var _entity_count: int = 0
	var _used_sprite_refs: Dictionary = {}

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
		_preview_active = false
		_entity_count = 0
		_used_sprite_refs.clear()
		_is_ready = true
		_setup_result = {"ok": true}
		return _setup_result

	func is_ready() -> bool:
		return _is_ready

	func get_setup_result() -> Dictionary:
		return _setup_result

	func get_world() -> Dictionary:
		return _world

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
				return str(resolved.get(kind, ""))
		return ""

	func add_floor(
		name: String,
		color: Color = Color(0.28, 0.65, 0.40),
		activate: bool = false
	) -> String:
		if not _is_ready or _adapter == null:
			return ""
		var res: Dictionary = _adapter.create_floor(_world, name, color)
		if not bool(res.get("ok", false)):
			_warn("新建楼层失败（" + name + "）：" + str(res.get("reason", "unknown")))
			return ""
		var new_uid: String = str(res["floor_uid"])
		_floor_layers[new_uid] = (res["layers"] as Dictionary).duplicate()
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
		var normalized_kind: String = str(res["kind"])
		if not _floor_layers.has(target_floor):
			_floor_layers[target_floor] = _adapter.get_floor_layer_map(_world, target_floor)
		var floor_map: Dictionary = _floor_layers[target_floor]
		if not floor_map.has(normalized_kind):
			floor_map[normalized_kind] = new_layer_uid
			if target_floor == _floor_uid:
				_layers[normalized_kind] = new_layer_uid
		return new_layer_uid

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
		var entity: Dictionary = _adapter.find_entity_by_id(_world, entity_id)
		var res: Dictionary = _adapter.append_entity_component(entity, script_path, state, parked)
		if not bool(res.get("ok", false)):
			_warn("挂载组件失败（%s -> %s）：%s" % [entity_id, script_path, str(res.get("reason", "unknown"))])
			return false
		return true

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

	func set_module_state(module_id: String, version: int, state: Dictionary) -> bool:
		if not _is_ready or _adapter == null:
			return false
		var res: Dictionary = _adapter.set_module_state(_world, module_id, version, state)
		if not bool(res.get("ok", false)):
			_warn("写入模块数据失败（%s）：%s" % [module_id, str(res.get("reason", "unknown"))])
			return false
		return true

	func build_result(source_record_count: int = 0, merged_wall_count: int = 0) -> Dictionary:
		if not _is_ready or _adapter == null:
			if not _setup_result.is_empty():
				return _setup_result
			return {"ok": false, "reason": "world_builder_not_initialized"}
		var archived_total: int = _session.get_archived_asset_count() if _session != null else 0
		var asset_total: int = maxi(_used_sprite_refs.size(), archived_total)
		return _adapter.build_prepare_ok(_world, asset_total, source_record_count, merged_wall_count)

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
		var entity: Dictionary = _adapter.append_entity(
			_world,
			_floor_uid,
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
		if _preview_active and _session != null:
			_adapter.preview_entity(_session.get_host(), entity, preview_kind)
		return str(entity.get("id", ""))
