extends EntityComponentPage
## 实体属性页模板：继承 EntityComponentPage，通过 edit_requested(&"field", ...) 接入 EditModeController 撤销栈。

var _targets: Array[BoardToken] = []
var _range_label: Label = null
var _minus_btn: Button = null
var _plus_btn: Button = null
var _secret_check: CheckBox = null
var _title_edit: LineEdit = null


func _ready() -> void:
	_range_label = %RangeValue
	_minus_btn = %MinusBtn
	_plus_btn = %PlusBtn
	_secret_check = %SecretCheck
	_title_edit = %TitleEdit

	if _minus_btn != null:
		_minus_btn.pressed.connect(_on_minus_pressed)
	if _plus_btn != null:
		_plus_btn.pressed.connect(_on_plus_pressed)
	if _secret_check != null:
		_secret_check.toggled.connect(_on_secret_toggled)
	if _title_edit != null:
		_title_edit.text_submitted.connect(_on_title_submitted)
	refresh()


func bind_entities(entities: Array[BoardToken]) -> void:
	_targets = entities.duplicate()
	refresh()


func _components() -> Array[CompBase]:
	var list: Array[CompBase] = []
	for entity: BoardToken in _targets:
		if not is_instance_valid(entity) or not entity.is_inside_tree():
			return []
		var comp := entity.get_component_by_id(component_id)
		if comp == null or comp.ctx == null or not comp.ctx.is_active():
			return []
		list.append(comp)
	return list


func refresh() -> void:
	if not is_node_ready():
		return
	var comps := _components()
	visible = not comps.is_empty()
	if comps.is_empty():
		return
	var first := comps[0]
	var cells := int(first.get(&"range_cells"))
	if _range_label != null:
		_range_label.text = "%d 格" % cells
	if _minus_btn != null:
		_minus_btn.disabled = cells <= 1
	if _plus_btn != null:
		_plus_btn.disabled = cells >= 24
	if _secret_check != null:
		var all_secret := true
		for c: CompBase in comps:
			if not bool(c.get(&"dm_secret")):
				all_secret = false
				break
		_secret_check.set_pressed_no_signal(all_secret)
	if _title_edit != null:
		var current_title := str(first.get(&"marker_title"))
		if not _title_edit.has_focus() and _title_edit.text != current_title:
			_title_edit.text = current_title


func _on_minus_pressed() -> void:
	_step_range(-1)


func _on_plus_pressed() -> void:
	_step_range(1)


func _step_range(delta: int) -> void:
	var comps := _components()
	if comps.is_empty():
		return
	editing_started.emit()
	var before: Array = []
	for c: CompBase in comps:
		before.append(int(c.get(&"range_cells")))
	var next_val: int = clampi(int(comps[0].get(&"range_cells")) + delta, 1, 24)
	edit_requested.emit(&"field", {
		"targets": _targets.duplicate(),
		"components": comps,
		"field": "range_cells",
		"before": before,
		"value": next_val,
	})
	refresh()


func _on_secret_toggled(value: bool) -> void:
	var comps := _components()
	if comps.is_empty():
		return
	editing_started.emit()
	var before: Array = []
	for c: CompBase in comps:
		before.append(bool(c.get(&"dm_secret")))
	edit_requested.emit(&"field", {
		"targets": _targets.duplicate(),
		"components": comps,
		"field": "dm_secret",
		"before": before,
		"value": value,
	})
	refresh()


func _on_title_submitted(new_text: String) -> void:
	var comps := _components()
	if comps.is_empty():
		return
	var clean: String = new_text.strip_edges().left(32)
	editing_started.emit()
	var before: Array = []
	for c: CompBase in comps:
		before.append(str(c.get(&"marker_title")))
	edit_requested.emit(&"field", {
		"targets": _targets.duplicate(),
		"components": comps,
		"field": "marker_title",
		"before": before,
		"value": clean,
	})
	refresh()
