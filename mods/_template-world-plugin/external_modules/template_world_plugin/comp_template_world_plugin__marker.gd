extends CompBase
## 外置世界模块自定义实体组件模板（comp_<plugin_id>__<name>.gd）
## 遵循无全局 class_name、无 preload、纯数据导出与 public_state 披露契约。

signal marker_changed

const SCHEMA_VERSION := 1
const PAGE_SCENE_PATH := "res://external_modules/template_world_plugin/marker_component_page.tscn"

@export var schema_version: int = SCHEMA_VERSION
@export var range_cells: int = 2:
	set(value):
		var clamped := clampi(value, 1, 24)
		if range_cells == clamped:
			return
		range_cells = clamped
		if not _applying_state:
			marker_changed.emit()
			notify_data_changed()

@export var marker_title: String = "战术标记":
	set(value):
		var clean := value.strip_edges().left(32)
		if marker_title == clean:
			return
		marker_title = clean
		if not _applying_state:
			marker_changed.emit()
			notify_data_changed()

@export var marker_color: Color = Color(0.24, 0.78, 0.96, 0.35):
	set(value):
		var finite_ok := is_finite(value.r) and is_finite(value.g) and is_finite(value.b) and is_finite(value.a)
		if not finite_ok or marker_color == value:
			return
		marker_color = value
		if not _applying_state:
			marker_changed.emit()
			notify_data_changed()

@export var dm_secret: bool = false:
	set(value):
		if dm_secret == value:
			return
		dm_secret = value
		if not _applying_state:
			marker_changed.emit()
			notify_data_changed()


func editable_fields() -> Array[String]:
	return ["range_cells", "marker_title", "marker_color", "dm_secret"]


func preset_field_resets() -> Variant:
	return {"dm_secret": false}


func supports_partial_property_selection() -> bool:
	return true


func component_tags() -> PackedStringArray:
	return PackedStringArray(["unit_trait", "marker"])


func dominance_priority() -> int:
	return 10


func suppresses_components() -> PackedStringArray:
	return PackedStringArray()


func suppression_allowlist() -> PackedStringArray:
	return PackedStringArray()


func supports_host(host: Node) -> bool:
	if not (host is BoardToken):
		return false
	var token := host as BoardToken
	return token.entity_type != "map"


func get_comp_page_scene() -> String:
	return PAGE_SCENE_PATH


func get_comp_quick_page_scene() -> String:
	return PAGE_SCENE_PATH


func accepts_state(state: Dictionary) -> bool:
	if not super.accepts_state(state):
		return false
	if int(state.get("schema_version", SCHEMA_VERSION)) != SCHEMA_VERSION:
		return false
	var cells: Variant = state.get("range_cells", 2)
	if not (cells is int) or int(cells) < 1 or int(cells) > 24:
		return false
	var title: Variant = state.get("marker_title", "")
	if not (title is String) or String(title).length() > 32:
		return false
	if state.has("marker_color"):
		var col_var: Variant = state.get("marker_color")
		if not (col_var is Color):
			return false
		var c := col_var as Color
		if not (is_finite(c.r) and is_finite(c.g) and is_finite(c.b) and is_finite(c.a)):
			return false
	if state.has("dm_secret") and not (state.get("dm_secret") is bool):
		return false
	return true


func apply_state(state: Dictionary) -> bool:
	if not super.apply_state(state):
		return false
	marker_changed.emit()
	return true


func public_state(state: Dictionary, peer: int) -> Dictionary:
	var secret: bool = bool(state.get("dm_secret", dm_secret))
	if secret and peer != 1:
		var token: BoardToken = get_parent() as BoardToken
		var perm: CompPermission = token.get_component_by_id("permission") as CompPermission if token != null else null
		if perm == null or not perm.can_command(peer):
			return {}
	var raw_color: Variant = state.get("marker_color", marker_color)
	var safe_color: Color = raw_color as Color if raw_color is Color else marker_color
	if not (is_finite(safe_color.r) and is_finite(safe_color.g) and is_finite(safe_color.b) and is_finite(safe_color.a)):
		safe_color = Color(0.24, 0.78, 0.96, 0.35)
	return {
		"schema_version": SCHEMA_VERSION,
		"range_cells": clampi(int(state.get("range_cells", range_cells)), 1, 24),
		"marker_title": String(state.get("marker_title", marker_title)).strip_edges().left(32),
		"marker_color": safe_color,
		"dm_secret": secret,
	}
