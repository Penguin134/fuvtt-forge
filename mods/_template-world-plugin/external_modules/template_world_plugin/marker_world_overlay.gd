extends Node2D
## 世界空间标记覆盖层模板（world.overlays / below_entities）：使用 WeakRef 避免循环引用。

var _provider_ref: WeakRef = null
var draw_calls: int = 0


func _provider() -> Object:
	if _provider_ref == null:
		return null
	var obj: Variant = _provider_ref.get_ref()
	if obj == null or not is_instance_valid(obj):
		return null
	return obj as Object


func bind_provider(provider: Object) -> bool:
	if provider == null or not is_instance_valid(provider):
		return false
	var ctx_var: Variant = provider.get(&"ctx")
	if not (ctx_var is Object) or not is_instance_valid(ctx_var):
		return false
	var ctx_obj := ctx_var as Object
	if ctx_obj.has_method(&"can_initialize") and not bool(ctx_obj.call(&"can_initialize")):
		return false
	deactivate()
	_provider_ref = weakref(provider)
	var cb := Callable(self, &"notify_changed")
	if provider.has_signal(&"markers_changed") and not provider.is_connected(&"markers_changed", cb):
		provider.connect(&"markers_changed", cb)
	queue_redraw()
	return true


func deactivate() -> void:
	var p: Object = _provider()
	if p != null:
		var cb := Callable(self, &"notify_changed")
		if p.has_signal(&"markers_changed") and p.is_connected(&"markers_changed", cb):
			p.disconnect(&"markers_changed", cb)
	_provider_ref = null


func notify_changed() -> void:
	queue_redraw()


func _exit_tree() -> void:
	deactivate()


func _draw() -> void:
	var p: Object = _provider()
	if p == null:
		return
	var ctx_var: Variant = p.get(&"ctx")
	if not (ctx_var is Object) or not is_instance_valid(ctx_var):
		return
	var ctx_obj := ctx_var as Object
	if ctx_obj.has_method(&"is_active") and not bool(ctx_obj.call(&"is_active")):
		return
	draw_calls += 1
	var rows: Array = p.call(&"collect_active_markers") as Array if p.has_method(&"collect_active_markers") else []
	var cfg: Dictionary = p.call(&"get_module_settings") as Dictionary if p.has_method(&"get_module_settings") else {}
	var show_text: bool = bool(cfg.get("show_labels", true))
	var inspect_on: bool = p.has_method(&"is_inspect_mode_active") and bool(p.call(&"is_inspect_mode_active"))
	var font: Font = ThemeDB.fallback_font
	for raw_info: Variant in rows:
		if not (raw_info is Dictionary):
			continue
		var info := raw_info as Dictionary
		var center: Vector2 = info.get("world_pos", Vector2.ZERO) as Vector2
		var radius_px: float = float(info.get("radius_world", 64.0))
		var fill_col: Color = info.get("color", Color(0.24, 0.78, 0.96, 0.35)) as Color
		var alpha_boost: float = 0.16 if inspect_on else 0.0
		var fill_draw := Color(fill_col.r, fill_col.g, fill_col.b, clampf(fill_col.a + alpha_boost, 0.08, 0.72))
		var ring_col := Color(fill_col.r, fill_col.g, fill_col.b, clampf(fill_col.a + 0.45, 0.25, 1.0))
		draw_circle(center, radius_px, fill_draw)
		draw_arc(center, radius_px, 0.0, TAU, 64, ring_col, 3.2 if inspect_on else 2.0, true)
		if (show_text or inspect_on) and font != null:
			var caption: String = "%s · %d 格" % [str(info.get("title", "")), int(info.get("cells", 0))]
			draw_string(font, center + Vector2(-42.0, -radius_px - 8.0), caption, HORIZONTAL_ALIGNMENT_LEFT, -1, 15, Color(1, 1, 1, 0.92))
