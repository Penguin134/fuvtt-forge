extends PanelContainer
## 右侧抽屉面板模板（ui.desktop_panels）：实现 bind_provider(provider) -> bool、activate()、deactivate() 与 WeakRef 清理。

var _provider_ref: WeakRef = null
var _active: bool = false


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
	if ctx_obj.has_method(&"is_active") and not bool(ctx_obj.call(&"is_active")):
		if not ctx_obj.has_method(&"can_initialize") or not bool(ctx_obj.call(&"can_initialize")):
			return false
	deactivate()
	_provider_ref = weakref(provider)
	var cb := Callable(self, &"_on_markers_changed")
	if provider.has_signal(&"markers_changed") and not provider.is_connected(&"markers_changed", cb):
		provider.connect(&"markers_changed", cb)
	return true


func activate() -> void:
	_active = true
	refresh_list()


func deactivate() -> void:
	_active = false
	var p: Object = _provider()
	if p != null:
		var cb := Callable(self, &"_on_markers_changed")
		if p.has_signal(&"markers_changed") and p.is_connected(&"markers_changed", cb):
			p.disconnect(&"markers_changed", cb)
	_provider_ref = null


func _on_markers_changed() -> void:
	if _active and is_visible_in_tree():
		refresh_list()


func refresh_list() -> void:
	if not is_node_ready():
		return
	var p: Object = _provider()
	if p == null or not p.has_method(&"collect_active_markers"):
		return
	var rows: Array = p.call(&"collect_active_markers") as Array
	var summary := get_node_or_null("%SummaryLabel") as Label
	if summary != null:
		summary.text = "当前楼层标记数：%d" % rows.size()
	var list_box := get_node_or_null("%MarkerList") as VBoxContainer
	if list_box == null:
		return
	while list_box.get_child_count() > rows.size():
		var extra := list_box.get_child(list_box.get_child_count() - 1)
		list_box.remove_child(extra)
		extra.queue_free()
	while list_box.get_child_count() < rows.size():
		var item := Label.new()
		list_box.add_child(item)
	for i: int in rows.size():
		var info: Dictionary = rows[i] as Dictionary
		var lbl := list_box.get_child(i) as Label
		if lbl != null:
			lbl.text = "%s · %s (%d 格)" % [
				str(info.get("unit_name", "")),
				str(info.get("title", "")),
				int(info.get("cells", 0)),
			]


func _exit_tree() -> void:
	deactivate()
