extends Node2D
## 桌面模块世界覆盖层画布（world.overlays / above_entities）
## 遵循无 class_name、无 preload、WeakRef 反引与 deactivate() 零泄漏契约。

var _provider_ref: WeakRef = null
var _waves: Array[Dictionary] = []


func bind_provider(provider: Object) -> bool:
	if provider == null or not is_instance_valid(provider):
		return false
	deactivate()
	_provider_ref = weakref(provider)
	if provider.has_signal(&"burst_triggered"):
		var cb := Callable(self, &"_on_burst_triggered")
		if not provider.is_connected(&"burst_triggered", cb):
			provider.connect(&"burst_triggered", cb)
	set_process(false)
	return true


func deactivate() -> void:
	if _provider_ref != null:
		var provider: Variant = _provider_ref.get_ref()
		if provider is Object and is_instance_valid(provider):
			var p_obj := provider as Object
			var cb := Callable(self, &"_on_burst_triggered")
			if p_obj.has_signal(&"burst_triggered") and p_obj.is_connected(&"burst_triggered", cb):
				p_obj.disconnect(&"burst_triggered", cb)
	_provider_ref = null
	_waves.clear()
	set_process(false)
	queue_redraw()


func _exit_tree() -> void:
	deactivate()


func _on_burst_triggered(world_pos: Vector2, color: Color, _label: String) -> void:
	spawn_wave(world_pos, color, 150.0)


func spawn_wave(world_pos: Vector2, color: Color, max_radius: float = 140.0) -> void:
	if not world_pos.is_finite():
		return
	_waves.append({
		"pos": world_pos,
		"color": color,
		"max_radius": maxf(24.0, max_radius),
		"elapsed": 0.0,
		"duration": 0.85,
	})
	set_process(true)
	queue_redraw()


func active_wave_count() -> int:
	return _waves.size()


func _process(delta: float) -> void:
	if _waves.is_empty():
		set_process(false)
		return
	for i: int in range(_waves.size() - 1, -1, -1):
		var w: Dictionary = _waves[i]
		var next_t: float = float(w.get("elapsed", 0.0)) + delta
		var dur: float = maxf(0.01, float(w.get("duration", 0.85)))
		if next_t >= dur:
			_waves.remove_at(i)
		else:
			w["elapsed"] = next_t
	queue_redraw()


func _draw() -> void:
	for w: Dictionary in _waves:
		var dur: float = maxf(0.01, float(w.get("duration", 0.85)))
		var t: float = clampf(float(w.get("elapsed", 0.0)) / dur, 0.0, 1.0)
		var ease_t: float = 1.0 - pow(1.0 - t, 3.0)
		var radius: float = lerpf(18.0, float(w.get("max_radius", 140.0)), ease_t)
		var base_col: Color = w.get("color", Color(0.95, 0.78, 0.25)) as Color
		var ring_col := Color(base_col.r, base_col.g, base_col.b, (1.0 - t) * 0.9)
		var fill_col := Color(base_col.r, base_col.g, base_col.b, (1.0 - t) * 0.2)
		var center: Vector2 = w.get("pos", Vector2.ZERO) as Vector2
		draw_circle(center, radius * 0.72, fill_col)
		draw_arc(center, radius, 0.0, TAU, 48, ring_col, lerpf(5.0, 1.5, t), true)
