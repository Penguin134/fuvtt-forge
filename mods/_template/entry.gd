extends RefCounted

const _SDK_PACKAGED_REL_PATH: String = "lib/fu_sdk/v1.gd"
const _SDK_DEV_REL_PATH: String = "../../shared/sdk/fu_sdk/v1.gd"


func _load_sdk_script() -> Script:
	var self_script := get_script() as Script
	if self_script == null or self_script.resource_path.is_empty():
		return null
	var base_dir: String = self_script.resource_path.split("::")[0].get_base_dir()
	var packaged_path: String = base_dir.path_join(_SDK_PACKAGED_REL_PATH)
	if FileAccess.file_exists(packaged_path) or ResourceLoader.exists(packaged_path):
		return load(packaged_path) as Script
	var dev_path: String = base_dir.path_join(_SDK_DEV_REL_PATH).simplify_path()
	if FileAccess.file_exists(dev_path) or ResourceLoader.exists(dev_path):
		return load(dev_path) as Script
	return null


func _create_sdk() -> RefCounted:
	var sdk_script: Script = _load_sdk_script()
	if sdk_script == null:
		return null
	return sdk_script.new()


func inspect_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:
	var sdk: RefCounted = _create_sdk()
	if sdk == null:
		return {"ok": false, "reason": "fu_sdk_not_found"}
	var session = sdk.create_session(host, options)
	if session.is_cancelled():
		return session.err_cancelled()
	# TODO: 解析源文件统计各类型记录数量与远端图片资源（key: url, value: 最大像素面积）
	return session.ok_inspect(path, {"records": 0, "unsupported": 0}, {})


func prepare_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:
	var sdk: RefCounted = _create_sdk()
	if sdk == null:
		return {"ok": false, "reason": "fu_sdk_not_found"}
	var session = sdk.create_session(host, options)
	if session.is_cancelled():
		return session.err_cancelled()
	var builder = sdk.create_world_builder(session, 150.0)
	var init_res: Dictionary = builder.setup(session, 150.0)
	if not bool(init_res.get("ok", false)):
		return init_res

	var _include_hidden: bool = session.get_bool_option("include_hidden", true)
	var _proxy: String = session.get_string_option("proxy", "")

	# 推荐两阶段导入顺序（对齐官方 ImportBridge 预览流协议）：
	# 阶段 1：先构建墙体/门窗/空气挖空/文字/矢量等轻量几何体并通知宿主完成几何预览。
	# builder.begin_bounds_preview(total_items, source_bounds)
	# builder.add_wall("wall_1", "外墙", Vector2.ZERO, [outer_ring])
	# builder.add_door("door_1", "木门", Vector2(150.0, 0.0), [door_ring], false)
	# builder.add_air_cutout("air_1", "洞口", Vector2(75.0, 0.0), [air_ring])
	if not builder.finish_geometry_preview():
		return session.err_cancelled() if session.is_cancelled() else session.err_failed("几何预览未能显示，请重新导入。")

	# 阶段 2：再按需归档远端重资产（必须使用 session.archive_remote_image 返回的 asset:// 引用，严禁写入 user://）。
	# var map_ref: String = session.archive_remote_image(map_url, _proxy)
	# if map_ref.is_empty():
	# 	session.add_warning("地图底图未归档，已使用默认占位色块显示。")
	# builder.add_map_tile("map_1", "主地图", Vector2.ZERO, Vector2(1500.0, 1500.0), map_ref)
	# var hero_id: String = builder.add_token("hero_1", "冒险者", Vector2(150.0, 150.0), Vector2(150.0, 150.0), "")
	# builder.attach_simple_vision(hero_id, 640.0, 360.0)

	if path.is_empty():
		session.add_warning("输入路径为空，已输出空白示例世界。")

	return builder.build_result(0, 0)
