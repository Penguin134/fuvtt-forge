extends VBoxContainer
## 模块设置页模板（ui.module_settings）：实现 bind_provider(provider) -> bool、refresh()、deactivate() 与 WeakRef 清理。

var _provider_ref: WeakRef = null


func _ready() -> void:
	var show_check := get_node_or_null("%ShowLabelsCheck") as CheckBox
	if show_check != null:
		show_check.toggled.connect(_on_show_labels_toggled)
	var range_spin := get_node_or_null("%RangeSpin") as SpinBox
	if range_spin != null:
		range_spin.value_changed.connect(_on_range_changed)
	refresh()


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
	var cb := Callable(self, &"refresh")
	if provider.has_signal(&"settings_changed") and not provider.is_connected(&"settings_changed", cb):
		provider.connect(&"settings_changed", cb)
	return true


func refresh() -> void:
	if not is_node_ready():
		return
	var p: Object = _provider()
	if p == null or not p.has_method(&"get_module_settings"):
		return
	var cfg: Dictionary = p.call(&"get_module_settings") as Dictionary
	var editable: bool = p.has_method(&"can_author_world") and bool(p.call(&"can_author_world"))
	var show_check := get_node_or_null("%ShowLabelsCheck") as CheckBox
	if show_check != null:
		show_check.disabled = not editable
		show_check.set_pressed_no_signal(bool(cfg.get("show_labels", true)))
	var range_spin := get_node_or_null("%RangeSpin") as SpinBox
	if range_spin != null:
		range_spin.editable = editable
		range_spin.set_value_no_signal(float(cfg.get("default_range_cells", 2)))


func deactivate() -> void:
	var p: Object = _provider()
	if p != null:
		var cb := Callable(self, &"refresh")
		if p.has_signal(&"settings_changed") and p.is_connected(&"settings_changed", cb):
			p.disconnect(&"settings_changed", cb)
	_provider_ref = null


func _on_show_labels_toggled(value: bool) -> void:
	var p: Object = _provider()
	if p != null and p.has_method(&"set_module_setting"):
		p.call(&"set_module_setting", "show_labels", value)


func _on_range_changed(value: float) -> void:
	var p: Object = _provider()
	if p != null and p.has_method(&"set_module_setting"):
		p.call(&"set_module_setting", "default_range_cells", int(value))


func _exit_tree() -> void:
	deactivate()
