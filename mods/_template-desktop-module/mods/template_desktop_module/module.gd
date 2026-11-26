extends ExtensionBase
## 纯本机桌面表现模块模板（fus.desktop-module.v1 / local_only / 纯 ZIP 直挂）
##
## 演示能力：
## 1. 动态加载 fu_runtime SDK（优先包内 lib/fu_runtime/v2.gd，回退开发态 shared/sdk/fu_runtime/v2.gd）；
## 2. 通过 DesktopApiHelper 读取 GM 权限、网络角色、格子尺度、选中单位生命值（含 masked 校验）与 GM 专有模块存档；
## 3. 通过 HookHelper 订阅官方内置 HookIds 与自定义命名空间事件 mod.template_desktop_module.burst_triggered；
## 4. 通过 SlotHelper 注册 world.overlays（above_entities）并借助 mount_node 在桌面挂载可自动回收的 HUD 横幅层。

signal burst_triggered(world_pos: Vector2, color: Color, label: String)

const PLUGIN_ID := "template_desktop_module"
const MODULE_ID := "mod.template_desktop_module"
const SERVICE_ID := "template_desktop_module.service"
const OVERLAY_SLOT_ID := "mod.template_desktop_module.overlay"
const OVERLAY_SCRIPT_PATH := "res://mods/template_desktop_module/overlay_canvas.gd"

const _RUNTIME_PACKAGED_REL_PATH := "lib/fu_runtime/v2.gd"
const _RUNTIME_DEV_REL_PATH := "../../../../shared/sdk/fu_runtime/v2.gd"

var _runtime_sdk: RefCounted = null
var _logger: RefCounted = null
var _api_helper: RefCounted = null
var _hook_helper: RefCounted = null
var _slot_helper: RefCounted = null

var _custom_burst_hook: StringName = &""
var _banner_layer: CanvasLayer = null
var _banner_panel: PanelContainer = null
var _banner_label: Label = null
var _banner_timer: float = 0.0
var _event_log: Array[Dictionary] = []


func _load_runtime_sdk() -> RefCounted:
	var self_scr := get_script() as Script
	var base_dir: String = ""
	if self_scr != null and not self_scr.resource_path.is_empty():
		base_dir = self_scr.resource_path.split("::")[0].get_base_dir()

	var candidates: Array[String] = []
	if not base_dir.is_empty():
		candidates.append(base_dir.path_join(_RUNTIME_PACKAGED_REL_PATH).simplify_path())
		candidates.append(base_dir.path_join(_RUNTIME_DEV_REL_PATH).simplify_path())
	candidates.append("res://shared/sdk/fu_runtime/v2.gd")
	candidates.append("shared/sdk/fu_runtime/v2.gd")

	for path: String in candidates:
		if ResourceLoader.exists(path) or FileAccess.file_exists(path):
			var loaded := load(path) as Script
			if loaded != null:
				var inst: Variant = loaded.new()
				if inst is RefCounted:
					return inst as RefCounted
	return null


func _on_register(context: ExtensionContext) -> void:
	set_meta(&"module_id", MODULE_ID)
	_runtime_sdk = _load_runtime_sdk()
	if _runtime_sdk == null:
		push_warning("[%s] Unable to load fu_runtime/v2.gd" % PLUGIN_ID)
		return

	_logger = _runtime_sdk.call(&"create_logger", {"emit_to_engine": true}) as RefCounted
	_api_helper = _runtime_sdk.call(&"create_desktop_api_helper", context, _logger) as RefCounted
	_hook_helper = _runtime_sdk.call(&"create_hook_helper", context, _logger) as RefCounted
	_slot_helper = _runtime_sdk.call(&"create_slot_helper", context, _logger) as RefCounted

	context.publish_service(SERVICE_ID, self)

	# 1. 注册 world.overlays（使用工厂按需生成 CanvasItem，由世界覆盖层宿主统一管理 bind_provider / deactivate）
	if _slot_helper != null:
		var ov_res: Dictionary = _slot_helper.call(&"register_world_overlay", OVERLAY_SLOT_ID, "above_entities", {
			"priority": 50,
			"factory": Callable(self, &"_create_overlay_node"),
		})
		if not bool(ov_res.get("ok", false)) and _logger != null:
			_logger.call(&"warn", PLUGIN_ID, "Failed to register world.overlays", ov_res)

	# 2. 通过 ExtensionContext.mount_node 在桌面挂载自由 CanvasLayer 横幅（退出或停用时自动卸载并释放）
	var desktop: Node = _api_helper.call(&"get_desktop") as Node if _api_helper != null else null
	if not is_instance_valid(desktop) and context.has_method(&"runtime_node"):
		var rt_node: Variant = context.call(&"runtime_node")
		if rt_node is Object and (rt_node as Object).has_method(&"get_desktop"):
			desktop = (rt_node as Object).call(&"get_desktop") as Node

	if is_instance_valid(desktop) and _slot_helper != null:
		_build_banner_layer()
		var mount_res: Dictionary = _slot_helper.call(&"mount_node", desktop, _banner_layer)
		if not bool(mount_res.get("ok", false)):
			if is_instance_valid(_banner_layer):
				_banner_layer.free()
			_banner_layer = null
			_banner_panel = null
			_banner_label = null

	# 3. 订阅官方内置 HookIds 与自定义命名空间事件 mod.<plugin_id>.burst_triggered（arity = 1）
	if _hook_helper != null:
		_hook_helper.call(&"subscribe", &"dice.rolled", Callable(self, &"_on_dice_rolled"))
		_hook_helper.call(&"subscribe", &"vitals.changed", Callable(self, &"_on_vitals_changed"))
		_hook_helper.call(&"subscribe", &"vitals.downed", Callable(self, &"_on_vitals_downed"))
		_hook_helper.call(&"subscribe", &"combat.started", Callable(self, &"_on_combat_started"))
		_custom_burst_hook = _hook_helper.call(&"build_custom_hook_id", "mod", PLUGIN_ID, "burst_triggered") as StringName
		if _custom_burst_hook != &"":
			_hook_helper.call(&"subscribe", _custom_burst_hook, Callable(self, &"_on_custom_burst"))

	# 4. 读取当前桌面上下文摘要（demonstrates desktop_api vitals + GM-only saved entry）
	_inspect_desktop_snapshot()
	set_process(false)


func _on_unregister() -> void:
	set_process(false)
	_event_log.clear()
	_custom_burst_hook = &""
	if _hook_helper != null:
		_hook_helper.call(&"unbind")
	if _slot_helper != null:
		_slot_helper.call(&"unbind")
	if _api_helper != null:
		_api_helper.call(&"unbind")
	_hook_helper = null
	_slot_helper = null
	_api_helper = null
	_logger = null
	_runtime_sdk = null
	_banner_layer = null
	_banner_panel = null
	_banner_label = null


func _create_overlay_node() -> Node2D:
	var ov_scr := load(OVERLAY_SCRIPT_PATH) as Script
	if ov_scr == null:
		return Node2D.new()
	var inst: Variant = ov_scr.new()
	if inst is Node2D:
		return inst as Node2D
	if inst is Node:
		(inst as Node).free()
	return Node2D.new()


func _build_banner_layer() -> void:
	_banner_layer = CanvasLayer.new()
	_banner_layer.name = "TemplateDesktopBannerLayer"
	_banner_layer.layer = 88

	var root_ctrl := Control.new()
	root_ctrl.set_anchors_preset(Control.PRESET_FULL_RECT)
	root_ctrl.mouse_filter = Control.MOUSE_FILTER_IGNORE

	_banner_panel = PanelContainer.new()
	_banner_panel.name = "TemplateDesktopBannerPanel"
	_banner_panel.visible = false
	_banner_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_banner_panel.anchor_left = 0.5
	_banner_panel.anchor_right = 0.5
	_banner_panel.anchor_top = 0.08
	_banner_panel.anchor_bottom = 0.08
	_banner_panel.offset_left = -240.0
	_banner_panel.offset_right = 240.0
	_banner_panel.offset_top = 0.0
	_banner_panel.offset_bottom = 56.0

	_banner_label = Label.new()
	_banner_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_banner_label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_banner_label.add_theme_font_size_override("font_size", 22)

	_banner_panel.add_child(_banner_label)
	root_ctrl.add_child(_banner_panel)
	_banner_layer.add_child(root_ctrl)


func _inspect_desktop_snapshot() -> Dictionary:
	if _api_helper == null or not bool(_api_helper.call(&"is_available")):
		return {}
	var is_gm_flag: bool = bool(_api_helper.call(&"is_gm"))
	var role: String = str(_api_helper.call(&"network_role"))
	var cell_px: float = float(_api_helper.call(&"world_units_per_cell"))
	var selected: Array = _api_helper.call(&"selected_entities") as Array
	if selected.is_empty():
		selected = _api_helper.call(&"get_entities", true) as Array

	var vitals_sample: Dictionary = {}
	var vitals_masked: bool = false
	if not selected.is_empty():
		vitals_sample = _api_helper.call(&"read_entity_vitals", selected[0]) as Dictionary
		vitals_masked = bool(_api_helper.call(&"is_vitals_masked", vitals_sample))

	var saved_entry: Dictionary = {}
	if is_gm_flag:
		saved_entry = _api_helper.call(&"read_saved_module_entry", MODULE_ID) as Dictionary

	var summary: Dictionary = {
		"is_gm": is_gm_flag,
		"network_role": role,
		"cell_px": cell_px,
		"entity_count": selected.size(),
		"vitals_ok": bool(vitals_sample.get("ok", false)),
		"vitals_masked": vitals_masked,
		"has_saved_entry": not saved_entry.is_empty(),
	}
	if _logger != null:
		_logger.call(&"debug", PLUGIN_ID, "Desktop snapshot initialized", summary)
	return summary


func _process(delta: float) -> void:
	if _banner_timer <= 0.0:
		set_process(false)
		if is_instance_valid(_banner_panel):
			_banner_panel.visible = false
		return
	_banner_timer -= delta
	if _banner_timer <= 0.0:
		if is_instance_valid(_banner_panel):
			_banner_panel.visible = false
		set_process(false)


func show_banner(text: String, color: Color, world_pos: Variant = null) -> void:
	var clean_text: String = str(_runtime_sdk.call(&"sanitize_line_text", text)) if _runtime_sdk != null else text
	if is_instance_valid(_banner_label) and is_instance_valid(_banner_panel):
		_banner_label.text = clean_text
		_banner_label.modulate = color
		_banner_panel.visible = true
		_banner_timer = 2.2
		set_process(true)
	var target_pos: Vector2 = _resolve_focus_world_pos(world_pos)
	if target_pos.is_finite():
		burst_triggered.emit(target_pos, color, clean_text)


func _resolve_focus_world_pos(explicit_pos: Variant) -> Vector2:
	if explicit_pos is Vector2 and (explicit_pos as Vector2).is_finite():
		return explicit_pos as Vector2
	if _api_helper != null:
		var sel: Array = _api_helper.call(&"selected_entities") as Array
		if not sel.is_empty() and sel[0] is Node2D:
			return (sel[0] as Node2D).global_position
		var cam_pos: Variant = _api_helper.call(&"camera_position")
		if cam_pos is Vector2 and (cam_pos as Vector2).is_finite():
			return cam_pos as Vector2
	return Vector2(512.0, 512.0)


func trigger_custom_burst(title: String, world_pos: Vector2 = Vector2(320.0, 320.0)) -> bool:
	if _hook_helper == null or _custom_burst_hook == &"":
		return false
	var payload: Dictionary = {
		"title": title,
		"pos": world_pos,
	}
	var res: Dictionary = _hook_helper.call(&"emit_custom", _custom_burst_hook, payload) as Dictionary
	return bool(res.get("ok", false)) and bool(res.get("emitted", false))


func get_recent_events() -> Array[Dictionary]:
	return _event_log.duplicate(true)


func _record_event(kind: String, summary: Dictionary) -> void:
	var cloned: Dictionary = _runtime_sdk.call(&"safe_clone_dict", summary) as Dictionary if _runtime_sdk != null else summary.duplicate(true)
	cloned["hook"] = kind
	_event_log.append(cloned)
	if _event_log.size() > 64:
		_event_log.pop_front()


func _on_dice_rolled(payload: Dictionary) -> void:
	var actor: String = str(payload.get("actor_name", "Adventurer"))
	var total: int = int(payload.get("total", 0))
	var is_nat20: bool = bool(payload.get("is_nat20", false))
	var is_nat1: bool = bool(payload.get("is_nat1", false))
	_record_event("dice.rolled", {
		"actor_name": actor,
		"total": total,
		"is_nat20": is_nat20,
		"is_nat1": is_nat1,
	})
	if is_nat20:
		show_banner("大成功 NATURAL 20 · %s (%d)" % [actor, total], Color(1.0, 0.84, 0.22))
	elif is_nat1:
		show_banner("大失败 NATURAL 1 · %s (%d)" % [actor, total], Color(0.95, 0.32, 0.28))


func _on_vitals_changed(payload: Dictionary) -> void:
	var entity_id: String = str(payload.get("entity_id", ""))
	var masked: bool = false
	if _api_helper != null and not entity_id.is_empty():
		var vitals: Dictionary = _api_helper.call(&"read_entity_vitals", entity_id) as Dictionary
		masked = bool(_api_helper.call(&"is_vitals_masked", vitals))
	_record_event("vitals.changed", {
		"entity_id": entity_id,
		"name": str(payload.get("name", "")),
		"delta_hp": int(payload.get("delta_hp", 0)),
		"masked": masked,
	})


func _on_vitals_downed(payload: Dictionary) -> void:
	var unit_name: String = str(payload.get("name", "单位"))
	var tok: Node2D = payload.get("entity") as Node2D if payload.get("entity") is Node2D else null
	var wpos: Variant = tok.global_position if is_instance_valid(tok) else null
	_record_event("vitals.downed", {
		"entity_id": str(payload.get("entity_id", "")),
		"name": unit_name,
	})
	show_banner("%s 生命归零倒地" % unit_name, Color(0.96, 0.22, 0.26), wpos)


func _on_combat_started(payload: Dictionary) -> void:
	var round_no: int = int(payload.get("round", 1))
	_record_event("combat.started", {"round": round_no})
	show_banner("遭遇战开始 · 第 %d 轮" % round_no, Color(0.38, 0.78, 1.0))


func _on_custom_burst(payload: Dictionary) -> void:
	var title: String = str(payload.get("title", "奥术爆发"))
	var pos: Variant = payload.get("pos", Vector2(320.0, 320.0))
	_record_event(String(_custom_burst_hook), {"title": title})
	show_banner(title, Color(0.82, 0.52, 1.0), pos)
