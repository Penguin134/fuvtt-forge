extends RefCounted
## Fu vtt 原生可选插件 SDK：drawing（协作绘画画布 v1、text_ink 矢量文字与实体表面涂鸦 comp_entity_ink）
##
## 对应官方源码：modules/drawing/drawing.gd、ink.gd、text_ink.gd、
## comp_entity_ink.gd、entity_stroke.gd、studio_catalog.gd。

const MODULE_ID: String = "drawing"
const MODULE_VERSION: int = 1
const STATE_VERSION: int = 1
const COMP_ENTITY_INK_SCRIPT: String = "res://modules/drawing/comp_entity_ink.gd"

const TOOLS: Array[String] = [
	"round", "marker", "soft", "ink", "pencil", "chalk", "spray", "dry",
	"line", "arrow", "box", "ellipse", "polyline", "polygon", "bezier",
	"freepath", "dynamic", "multi", "calligraphy", "panel", "text",
	"gradient", "enclose", "reference", "clone",
]
const TWO_POINTS_TOOLS: Array[String] = ["line", "arrow", "box", "ellipse", "panel", "gradient", "reference"]
const COORDS: Array[String] = ["world", "screen"]
const LIFE_VALUES: Array[int] = [0, 3, 5, 10, 30]
const BLEND_MODES: Array[String] = ["multiply", "add", "subtract"]

const TEXT_FONTS: Array[String] = ["sans", "zhuokai"]
const DEFAULT_TEXT_FONT: String = "zhuokai"
const MIN_TEXT_SIZE: int = 12
const MAX_TEXT_SIZE: int = 256
const DEFAULT_TEXT_SIZE: int = 42

const MAX_SAMPLES: int = 2048
const MAX_STAMP_SAMPLES: int = 384
const MAX_STROKES: int = 4096
const MAX_TEXT_ITEMS: int = 1024
const MAX_TEXT_LENGTH: int = 1024
const MAX_SAMPLES_TOTAL: int = 120000

const ENTITY_INK_MAX_STROKES: int = 256
const ENTITY_INK_MAX_POINTS: int = 1536
const ENTITY_INK_MAX_TOTAL: int = 16000
const ENTITY_INK_MAX_PATCH_TOTAL: int = 8 * 1024 * 1024
const ENTITY_INK_MAX_PATCH_BYTES: int = 1024 * 1024 * 4 + 65536
const ENTITY_INK_MAX_MARGIN: int = 25
const ENTITY_INK_DEFAULT_MARGIN: int = 8
const ENTITY_INK_MIN_WIDTH: float = 0.0005
const ENTITY_INK_MAX_WIDTH: float = 0.16

var _world_builder_ref: WeakRef = null
var _module_registry: RefCounted = null
var _log_bus: RefCounted = null
var _util_scripts: Dictionary = {}


## 按相对路径动态加载并缓存 utils/*.gd 叶子工具脚本（仅保存在当前实例上，不产生跨对象循环引用）。
func _load_util_script(file_name: String) -> Variant:
	if _util_scripts.has(file_name):
		return _util_scripts[file_name]
	var rel_from_subdir: String = "../utils/" + file_name
	var self_scr := get_script() as Script
	if self_scr != null and not self_scr.resource_path.is_empty():
		var base_dir: String = self_scr.resource_path.split("::")[0].get_base_dir()
		var candidate: String = base_dir.path_join(rel_from_subdir).simplify_path()
		if FileAccess.file_exists(candidate) or ResourceLoader.exists(candidate):
			var loaded := load(candidate) as Script
			if loaded != null:
				_util_scripts[file_name] = loaded
				return loaded
	for raw_frame: Variant in get_stack():
		if raw_frame is Dictionary:
			var src_file: String = str((raw_frame as Dictionary).get("source", ""))
			if not src_file.is_empty():
				var stack_cand: String = src_file.get_base_dir().path_join(rel_from_subdir).simplify_path()
				if FileAccess.file_exists(stack_cand) or ResourceLoader.exists(stack_cand):
					var loaded_stack := load(stack_cand) as Script
					if loaded_stack != null:
						_util_scripts[file_name] = loaded_stack
						return loaded_stack
	for fb_path: String in [
		"res://shared/sdk/fu_sdk/utils/" + file_name,
		"shared/sdk/fu_sdk/utils/" + file_name,
	]:
		if FileAccess.file_exists(fb_path) or ResourceLoader.exists(fb_path):
			var loaded_fb := load(fb_path) as Script
			if loaded_fb != null:
				_util_scripts[file_name] = loaded_fb
				return loaded_fb
	return null


func _bounded_cloner() -> Variant:
	return _load_util_script("bounded_cloner.gd")


func _value_utils() -> Variant:
	return _load_util_script("value_utils.gd")


func _validation_utils() -> Variant:
	return _load_util_script("validation_utils.gd")


func configure(
	world_builder: RefCounted,
	module_registry: RefCounted = null,
	log_bus: RefCounted = null
) -> void:
	_world_builder_ref = weakref(world_builder) if world_builder != null else null
	_module_registry = module_registry
	_log_bus = log_bus


func _wb() -> RefCounted:
	if _world_builder_ref == null:
		return null
	var inst: Variant = _world_builder_ref.get_ref()
	return inst as RefCounted if inst is RefCounted else null


func is_enabled() -> bool:
	if _module_registry != null:
		return bool(_module_registry.is_module_enabled(MODULE_ID))
	return false


func get_availability() -> Dictionary:
	if _module_registry != null:
		return _module_registry.get_module_entry(MODULE_ID)
	return {
		"id": MODULE_ID,
		"core": false,
		"status": "disabled",
		"enabled": false,
		"floor_content_records": "strokes",
	}


func make_text_transform(
	origin_offset: Vector2 = Vector2.ZERO,
	rotation_rad: float = 0.0,
	scale_vec: Vector2 = Vector2.ONE
) -> Transform2D:
	var sx: float = scale_vec.x if (is_finite(scale_vec.x) and not is_zero_approx(scale_vec.x)) else 1.0
	var sy: float = scale_vec.y if (is_finite(scale_vec.y) and not is_zero_approx(scale_vec.y)) else 1.0
	var rot: float = rotation_rad if is_finite(rotation_rad) else 0.0
	var orig: Vector2 = origin_offset if origin_offset.is_finite() else Vector2.ZERO
	return Transform2D(rot, Vector2(sx, sy), 0.0, orig)


func make_stroke_item(
	floor_uid: String,
	points: Variant,
	color: Color = Color.BLACK,
	width: float = 6.0,
	tool: String = "round",
	coords: String = "world",
	order: int = 1,
	owner: String = "host",
	opacity: float = 1.0,
	hardness: float = 1.0,
	filled: bool = false,
	pressure: PackedFloat32Array = PackedFloat32Array(),
	id_override: String = "",
	extras: Dictionary = {}
) -> Dictionary:
	var norm_coords: String = coords.strip_edges().to_lower()
	if not (norm_coords in COORDS):
		norm_coords = "world"
	var norm_floor: String = "" if norm_coords == "screen" else floor_uid.strip_edges().to_lower()
	var norm_tool: String = tool.strip_edges().to_lower()
	if not (norm_tool in TOOLS) or norm_tool == "text":
		norm_tool = "round"

	var pts: PackedVector2Array = _to_packed_vec2(points)
	var prs: PackedFloat32Array = PackedFloat32Array()
	if pressure.size() == pts.size():
		for p: float in pressure:
			prs.append(clampf(p if is_finite(p) else 1.0, 0.05, 1.0))
	else:
		prs.resize(pts.size())
		for i: int in range(pts.size()):
			prs[i] = 1.0

	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	var safe_order: int = maxi(1, mini(order, 0x7fffffff))
	var safe_color: Color = val_u.clamp_color(color, Color.BLACK)
	var safe_width: float = clampf(width if is_finite(width) else 6.0, 1.0, 128.0)
	var item_id: String = id_override.strip_edges().to_lower()
	if not bool(valid_u.is_valid_uid(item_id)):
		var pt_parts := PackedStringArray()
		for pt: Vector2 in pts:
			pt_parts.append("%.4f,%.4f" % [pt.x, pt.y])
		item_id = ("fu_sdk:drawing:stroke:%s:%s:%d:%s:%s:%.4f" % [
			norm_floor,
			norm_tool,
			safe_order,
			";".join(pt_parts),
			safe_color.to_html(true),
			safe_width,
		]).sha256_text().left(32)

	var row: Dictionary = {
		"id": item_id,
		"floor": norm_floor,
		"coords": norm_coords,
		"tool": norm_tool,
		"points": pts,
		"pressure": prs,
		"color": safe_color,
		"width": safe_width,
		"opacity": clampf(opacity if is_finite(opacity) else 1.0, 0.02, 1.0),
		"hardness": clampf(hardness if is_finite(hardness) else 1.0, 0.05, 1.0),
		"filled": filled,
		"life": 0,
		"owner": owner.left(128),
		"order": safe_order,
	}
	for ek: Variant in extras.keys():
		if ek is String and str(ek) in ["blend", "affine", "clip", "secondary", "width_profile", "cuts", "hints", "image", "stamp_rect", "stamp_ref", "stamp_bytes"]:
			row[ek] = _safe_clone_via_adapter(extras[ek])
	return row


func make_text_item(
	floor_uid: String,
	position: Vector2,
	text: String,
	color: Color = Color.BLACK,
	font: String = DEFAULT_TEXT_FONT,
	font_size: int = DEFAULT_TEXT_SIZE,
	affine: Transform2D = Transform2D.IDENTITY,
	coords: String = "world",
	order: int = 1,
	owner: String = "host",
	opacity: float = 1.0,
	id_override: String = "",
	blend: String = "",
	clip: Variant = null
) -> Dictionary:
	var norm_coords: String = coords.strip_edges().to_lower()
	if not (norm_coords in COORDS):
		norm_coords = "world"
	var norm_floor: String = "" if norm_coords == "screen" else floor_uid.strip_edges().to_lower()
	var safe_pos: Vector2 = position if position.is_finite() else Vector2.ZERO
	var safe_font_size: int = clampi(font_size, MIN_TEXT_SIZE, MAX_TEXT_SIZE)
	var norm_font: String = font.strip_edges().to_lower()
	if not (norm_font in TEXT_FONTS):
		norm_font = DEFAULT_TEXT_FONT
	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	var safe_order: int = maxi(1, mini(order, 0x7fffffff))
	var safe_color: Color = val_u.clamp_color(color, Color.BLACK)
	var item_id: String = id_override.strip_edges().to_lower()
	if not bool(valid_u.is_valid_uid(item_id)):
		item_id = ("fu_sdk:drawing:text:%s:%d:%.4f,%.4f:%s:%d:%s:%s" % [
			norm_floor,
			safe_order,
			safe_pos.x,
			safe_pos.y,
			norm_font,
			safe_font_size,
			safe_color.to_html(true),
			text.left(64),
		]).sha256_text().left(32)

	var row: Dictionary = {
		"id": item_id,
		"floor": norm_floor,
		"coords": norm_coords,
		"tool": "text",
		"points": PackedVector2Array([safe_pos]),
		"pressure": PackedFloat32Array([1.0]),
		"color": safe_color,
		"width": clampf(float(safe_font_size), 1.0, 128.0),
		"opacity": clampf(opacity if is_finite(opacity) else 1.0, 0.02, 1.0),
		"hardness": 1.0,
		"filled": false,
		"life": 0,
		"owner": owner.left(128),
		"order": safe_order,
		"text": text,
		"font": norm_font,
		"font_size": safe_font_size,
	}
	if affine != Transform2D.IDENTITY:
		row["affine"] = affine
	var norm_blend: String = blend.strip_edges().to_lower()
	if norm_blend in BLEND_MODES:
		row["blend"] = norm_blend
	if clip is Rect2:
		row["clip"] = clip
	return row


func validate_ink_row(row: Variant, require_persistent: bool = true) -> Dictionary:
	if not (row is Dictionary):
		return {"ok": false, "reason": "drawing_stroke_not_dict"}
	var d: Dictionary = row as Dictionary
	var req: Array[String] = [
		"id", "floor", "coords", "tool", "points", "pressure", "color",
		"width", "opacity", "hardness", "filled", "life", "owner", "order",
	]
	for k: String in req:
		if not d.has(k):
			return {"ok": false, "reason": "drawing_stroke_missing_key:" + k}

	var valid_u: Variant = _validation_utils()
	var id_v: Variant = d["id"]
	if not (id_v is String) or not bool(valid_u.is_valid_uid(str(id_v))):
		return {"ok": false, "reason": "drawing_stroke_invalid_id"}
	var coords_v: Variant = d["coords"]
	if not (coords_v is String) or not (str(coords_v) in COORDS):
		return {"ok": false, "reason": "drawing_stroke_invalid_coords"}
	var coords_s: String = str(coords_v)
	var tool_v: Variant = d["tool"]
	if not (tool_v is String) or not (str(tool_v) in TOOLS):
		return {"ok": false, "reason": "drawing_stroke_invalid_tool"}
	var tool_s: String = str(tool_v)

	var floor_v: Variant = d["floor"]
	if not (floor_v is String):
		return {"ok": false, "reason": "drawing_stroke_invalid_floor"}
	if coords_s == "screen":
		if str(floor_v) != "":
			return {"ok": false, "reason": "drawing_screen_stroke_must_have_empty_floor"}
	elif not bool(valid_u.is_valid_uid(str(floor_v))):
		return {"ok": false, "reason": "drawing_world_stroke_invalid_floor_uid"}

	var owner_v: Variant = d["owner"]
	if not (owner_v is String) or str(owner_v).length() > 128:
		return {"ok": false, "reason": "drawing_stroke_invalid_owner"}

	var order_v: Variant = d["order"]
	var min_order: int = 1 if require_persistent else 0
	if not (order_v is int) or int(order_v) < min_order or int(order_v) > 0x7fffffff:
		return {"ok": false, "reason": "drawing_stroke_invalid_order"}

	var life_v: Variant = d["life"]
	if not (life_v is int) or not (int(life_v) in LIFE_VALUES):
		return {"ok": false, "reason": "drawing_stroke_invalid_life"}
	if require_persistent and int(life_v) != 0:
		return {"ok": false, "reason": "drawing_stroke_must_be_persistent"}

	if not (d["filled"] is bool):
		return {"ok": false, "reason": "drawing_stroke_invalid_filled"}

	var pts_v: Variant = d["points"]
	var prs_v: Variant = d["pressure"]
	if not (pts_v is PackedVector2Array) or not (prs_v is PackedFloat32Array):
		return {"ok": false, "reason": "drawing_stroke_invalid_points_or_pressure_type"}
	var pts: PackedVector2Array = pts_v as PackedVector2Array
	var prs: PackedFloat32Array = prs_v as PackedFloat32Array
	if pts.is_empty() or pts.size() > MAX_SAMPLES or pts.size() != prs.size():
		return {"ok": false, "reason": "drawing_stroke_invalid_sample_count"}
	if tool_s in TWO_POINTS_TOOLS and pts.size() > 2:
		return {"ok": false, "reason": "drawing_stroke_too_many_points_for_shape"}
	if tool_s == "text" and pts.size() != 1:
		return {"ok": false, "reason": "drawing_text_must_have_one_point"}
	if tool_s == "bezier" and pts.size() > 4:
		return {"ok": false, "reason": "drawing_bezier_too_many_points"}
	if tool_s == "clone" and pts.size() > MAX_STAMP_SAMPLES:
		return {"ok": false, "reason": "drawing_clone_too_many_points"}

	for i: int in range(pts.size()):
		var pt: Vector2 = pts[i]
		if not pt.is_finite() or not _number_in(prs[i], 0.05, 1.0):
			return {"ok": false, "reason": "drawing_stroke_invalid_point_or_pressure"}
		if coords_s == "screen":
			if pt.x < 0.0 or pt.y < 0.0 or pt.x > 1.0 or pt.y > 1.0:
				return {"ok": false, "reason": "drawing_screen_point_out_of_range"}
		elif maxf(absf(pt.x), absf(pt.y)) > 10000000.0:
			return {"ok": false, "reason": "drawing_world_point_out_of_range"}

	var val_u: Variant = _value_utils()
	if not (d["color"] is Color) or not bool(val_u.is_unit_color(d["color"] as Color)):
		return {"ok": false, "reason": "drawing_stroke_invalid_color"}
	if not _number_in(d["width"], 1.0, 128.0):
		return {"ok": false, "reason": "drawing_stroke_invalid_width"}
	if not _number_in(d["opacity"], 0.02, 1.0):
		return {"ok": false, "reason": "drawing_stroke_invalid_opacity"}
	if not _number_in(d["hardness"], 0.05, 1.0):
		return {"ok": false, "reason": "drawing_stroke_invalid_hardness"}

	var expected_keys: int = 14
	if d.has("times") or d.has("elapsed"):
		if int(life_v) == 0 or not d.has("times") or not d.has("elapsed"):
			return {"ok": false, "reason": "drawing_stroke_invalid_trail_keys"}
		expected_keys += 2
	if d.has("cuts"):
		if not _valid_cuts(d["cuts"]):
			return {"ok": false, "reason": "drawing_stroke_invalid_cuts"}
		expected_keys += 1
	if d.has("width_profile"):
		if not (tool_s in ["round", "clone"]) or not (d["width_profile"] is bool) or d["width_profile"] != true:
			return {"ok": false, "reason": "drawing_stroke_invalid_width_profile"}
		expected_keys += 1
	if d.has("blend"):
		if tool_s == "clone" or not (d["blend"] is String) or not (str(d["blend"]) in BLEND_MODES):
			return {"ok": false, "reason": "drawing_stroke_invalid_blend"}
		expected_keys += 1

	if tool_s == "text":
		var txt_v: Variant = d.get("text", null)
		if not (txt_v is String) or str(txt_v).strip_edges().is_empty() or str(txt_v).length() > MAX_TEXT_LENGTH:
			return {"ok": false, "reason": "drawing_text_invalid"}
		expected_keys += 1
		if d.has("font"):
			if not (d["font"] is String) or not (str(d["font"]) in TEXT_FONTS):
				return {"ok": false, "reason": "drawing_text_invalid_font"}
			expected_keys += 1
		if d.has("font_size"):
			var fs_v: Variant = d["font_size"]
			if not (fs_v is int) or int(fs_v) < MIN_TEXT_SIZE or int(fs_v) > MAX_TEXT_SIZE:
				return {"ok": false, "reason": "drawing_text_invalid_font_size"}
			expected_keys += 1

	if tool_s in ["gradient", "panel"]:
		var sec_v: Variant = d.get("secondary", null)
		if not (sec_v is Color) or not bool(val_u.is_unit_color(sec_v as Color)):
			return {"ok": false, "reason": "drawing_stroke_invalid_secondary_color"}
		expected_keys += 1

	if tool_s == "clone":
		var sr_v: Variant = d.get("stamp_rect", null)
		if not (sr_v is Rect2):
			return {"ok": false, "reason": "drawing_clone_missing_stamp_rect"}
		var sr: Rect2 = sr_v as Rect2
		if not sr.is_finite() or not sr.has_area() or sr.position.length() > 30000000.0 or sr.size.length() > 30000000.0:
			return {"ok": false, "reason": "drawing_clone_invalid_stamp_rect"}
		if d.has("clip") or d.has("affine"):
			return {"ok": false, "reason": "drawing_clone_disallows_clip_or_affine"}
		expected_keys += 1
		if d.has("stamp_ref"):
			if not d.has("stamp_bytes"):
				return {"ok": false, "reason": "drawing_clone_missing_stamp_bytes"}
			expected_keys += 2
		else:
			if not (d.get("image", null) is PackedByteArray):
				return {"ok": false, "reason": "drawing_clone_missing_image"}
			expected_keys += 1
	elif tool_s == "reference":
		var img_v: Variant = d.get("image", null)
		if not (img_v is PackedByteArray) or (img_v as PackedByteArray).size() < 33 or (img_v as PackedByteArray).size() > 18000:
			return {"ok": false, "reason": "drawing_reference_invalid_image"}
		expected_keys += 1

	if d.has("hints"):
		if tool_s != "reference" or not (d["hints"] is Array) or (d["hints"] as Array).size() > 32:
			return {"ok": false, "reason": "drawing_stroke_invalid_hints"}
		expected_keys += 1

	if d.has("affine"):
		var xf_v: Variant = d["affine"]
		if not (xf_v is Transform2D):
			return {"ok": false, "reason": "drawing_stroke_invalid_affine"}
		var xf: Transform2D = xf_v as Transform2D
		if not xf.is_finite() or absf(xf.determinant()) < 0.000001:
			return {"ok": false, "reason": "drawing_stroke_singular_affine"}
		if xf.x.length() > 20000000.0 or xf.y.length() > 20000000.0 or xf.origin.length() > 20000000.0:
			return {"ok": false, "reason": "drawing_stroke_affine_out_of_range"}
		expected_keys += 1

	if d.has("clip"):
		var cl_v: Variant = d["clip"]
		if not (cl_v is Rect2) or not (cl_v as Rect2).is_finite() or not (cl_v as Rect2).has_area():
			return {"ok": false, "reason": "drawing_stroke_invalid_clip"}
		expected_keys += 1

	if d.size() != expected_keys:
		return {"ok": false, "reason": "drawing_stroke_unexpected_keys"}

	return {"ok": true, "reason": ""}


func make_world_drawing_state(strokes: Array = [], visible: bool = true) -> Dictionary:
	var cloned_strokes: Variant = _safe_clone_via_adapter(strokes)
	var arr: Array = cloned_strokes as Array if cloned_strokes is Array else []
	var state: Dictionary = {
		"version": STATE_VERSION,
		"strokes": arr,
	}
	if not visible:
		state["visible"] = false
	return state


func validate_world_drawing_state(state: Dictionary) -> Dictionary:
	if state.is_empty():
		return {"ok": true, "reason": ""}
	var expected_sz: int = 3 if state.has("visible") else 2
	if (
		state.size() != expected_sz
		or not (state.get("visible", true) is bool)
		or not (state.get("version", null) is int)
		or int(state.get("version", -1)) != STATE_VERSION
		or not (state.get("strokes", null) is Array)
	):
		return {"ok": false, "reason": "drawing_state_invalid"}
	var strokes: Array = state["strokes"] as Array
	if strokes.size() > MAX_STROKES + MAX_TEXT_ITEMS:
		return {"ok": false, "reason": "drawing_state_invalid"}

	var seen_ids: Dictionary = {}
	var seen_orders: Dictionary = {}
	var sample_total: int = 0
	var stroke_count: int = 0
	var text_count: int = 0

	for raw_row: Variant in strokes:
		var checked: Dictionary = validate_ink_row(raw_row, true)
		if not bool(checked.get("ok", false)):
			return {"ok": false, "reason": "drawing_stroke_invalid", "detail": str(checked.get("reason", ""))}
		var row: Dictionary = raw_row as Dictionary
		var rid: String = str(row["id"])
		var rorder: int = int(row["order"])
		if seen_ids.has(rid) or seen_orders.has(rorder):
			return {"ok": false, "reason": "drawing_stroke_invalid"}
		seen_ids[rid] = true
		seen_orders[rorder] = true
		if str(row["tool"]) == "text":
			text_count += 1
		else:
			stroke_count += 1
			sample_total += _row_sample_count(row)

	if stroke_count > MAX_STROKES or text_count > MAX_TEXT_ITEMS or sample_total > MAX_SAMPLES_TOTAL:
		return {"ok": false, "reason": "drawing_capacity"}
	return {"ok": true, "reason": ""}


func configure_world_drawing(strokes: Array = [], visible: bool = true) -> Dictionary:
	var gate: Dictionary = _check_gate("configure_world_drawing")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}

	var state: Dictionary = make_world_drawing_state(strokes, visible)
	var checked: Dictionary = validate_world_drawing_state(state)
	if not bool(checked.get("ok", false)):
		return checked
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, state))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"state": state,
		"enabled": bool(gate.get("enabled", false)),
		"policy": str(gate.get("policy", "preserve")),
	}


func configure_drawing(state_or_strokes: Variant = [], visible: bool = true) -> Dictionary:
	if state_or_strokes is Array:
		return configure_world_drawing(state_or_strokes as Array, visible)
	var gate: Dictionary = _check_gate("configure_drawing")
	if not bool(gate.get("ok", true)):
		return gate
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}
	if not (state_or_strokes is Dictionary):
		return {"ok": false, "reason": "drawing_state_invalid"}

	var d: Dictionary = state_or_strokes as Dictionary
	var norm_strokes: Array = []
	var eff_visible: bool = visible
	if not d.is_empty():
		for raw_k: Variant in d.keys():
			if not (raw_k is String) or not (str(raw_k) in ["version", "strokes", "visible"]):
				return {"ok": false, "reason": "drawing_state_invalid"}
		if d.has("version"):
			var ver_p: Dictionary = _value_utils().parse_int_val(d["version"])
			if not bool(ver_p["ok"]) or int(ver_p["value"]) != STATE_VERSION:
				return {"ok": false, "reason": "drawing_state_invalid"}
		if d.has("visible"):
			if not (d["visible"] is bool):
				return {"ok": false, "reason": "drawing_state_invalid"}
			eff_visible = bool(d["visible"])
		if not d.has("strokes") or not (d["strokes"] is Array):
			return {"ok": false, "reason": "drawing_state_invalid"}
		norm_strokes = _normalize_world_drawing_strokes(d["strokes"] as Array)

	var state: Dictionary = make_world_drawing_state(norm_strokes, eff_visible)
	var checked: Dictionary = validate_world_drawing_state(state)
	if not bool(checked.get("ok", false)):
		return checked
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, state))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"state": state,
		"enabled": bool(gate.get("enabled", false)),
		"policy": str(gate.get("policy", "preserve")),
	}


func add_world_stroke(stroke: Dictionary) -> Dictionary:
	var gate: Dictionary = _check_gate("add_world_stroke")
	if not bool(gate.get("ok", true)):
		return gate
	return _append_world_drawing_item(stroke)


func add_world_text(text_item: Dictionary) -> Dictionary:
	var gate: Dictionary = _check_gate("add_world_text")
	if not bool(gate.get("ok", true)):
		return gate
	return _append_world_drawing_item(text_item)


func get_world_drawing_state() -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {}
	if wb.has_method("get_module_state"):
		return wb.get_module_state(MODULE_ID)
	var adapter: RefCounted = _get_adapter()
	if adapter != null and adapter.has_method("get_module_state"):
		return adapter.get_module_state(wb.get_world(), MODULE_ID)
	return {}


func make_entity_stroke(
	points: Variant,
	color: Color = Color.BLACK,
	width: float = 0.02,
	opacity: float = 1.0,
	erase: bool = false,
	margin: int = ENTITY_INK_DEFAULT_MARGIN,
	pressure: PackedFloat32Array = PackedFloat32Array(),
	id_override: String = ""
) -> Dictionary:
	var val_u: Variant = _value_utils()
	var valid_u: Variant = _validation_utils()
	var pts: PackedVector2Array = _to_packed_vec2(points)
	var safe_margin: int = clampi(margin, 0, ENTITY_INK_MAX_MARGIN)
	var item_id: String = id_override.strip_edges().to_lower()
	if not bool(valid_u.is_valid_uid(item_id)):
		item_id = ("fu_sdk:entity_ink:%d:%s" % [pts.size(), str(color)]).sha256_text().left(32)
	var row: Dictionary = {
		"id": item_id,
		"erase": erase,
		"color": val_u.clamp_color(color, Color.BLACK),
		"width": clampf(width if is_finite(width) else 0.02, ENTITY_INK_MIN_WIDTH, ENTITY_INK_MAX_WIDTH),
		"opacity": clampf(opacity if is_finite(opacity) else 1.0, 0.0001, 1.0),
		"points": pts,
		"margin": safe_margin,
	}
	if not pressure.is_empty() and pressure.size() == pts.size():
		var prs := PackedFloat32Array()
		for p: float in pressure:
			prs.append(clampf(p if is_finite(p) else 1.0, 0.05, 1.0))
		row["pressure"] = prs
	return row


func make_entity_ink_state(strokes: Array = [], revision: String = "") -> Dictionary:
	var cloned_strokes: Variant = _safe_clone_via_adapter(strokes)
	var arr: Array = cloned_strokes as Array if cloned_strokes is Array else []
	var clean_rev: String = revision.strip_edges().to_lower()
	return {
		"strokes": arr,
		"revision": clean_rev,
	}


func validate_entity_ink_state(state: Dictionary, entity: Dictionary = {}) -> Dictionary:
	var valid_u: Variant = _validation_utils()
	if not entity.is_empty():
		var comps_var: Variant = entity.get("components", [])
		if comps_var is Array:
			for raw_c: Variant in comps_var as Array:
				if raw_c is Dictionary:
					var scr: String = str((raw_c as Dictionary).get("script", ""))
					var cid: String = str(valid_u.component_id_from_script(scr))
					if cid == "scene_box":
						return {"ok": false, "reason": "component_conflict_with_scene_box:entity_ink"}

	if state.is_empty():
		return {"ok": true, "reason": ""}
	if state.size() != 2 or not (state.get("strokes", null) is Array):
		return {"ok": false, "reason": "entity_ink_invalid_header"}
	var rev_v: Variant = state.get("revision", null)
	if not (rev_v is String) or (not str(rev_v).is_empty() and not bool(valid_u.is_valid_uid(str(rev_v)))):
		return {"ok": false, "reason": "entity_ink_invalid_revision"}
	var strokes: Array = state["strokes"] as Array
	if strokes.size() > ENTITY_INK_MAX_STROKES:
		return {"ok": false, "reason": "entity_ink_stroke_limit_exceeded"}

	var seen_ids: Dictionary = {}
	var total_pts: int = 0
	var total_patch_bytes: int = 0
	for raw_s: Variant in strokes:
		var s_check: Dictionary = _validate_entity_stroke(raw_s)
		if not bool(s_check.get("ok", false)):
			return s_check
		var s: Dictionary = raw_s as Dictionary
		if s.has("life"):
			return {"ok": false, "reason": "entity_ink_disallows_life"}
		if s.has("clone_offset") and not s.has("patch"):
			return {"ok": false, "reason": "entity_ink_clone_requires_patch"}
		var sid: String = str(s["id"])
		if seen_ids.has(sid):
			return {"ok": false, "reason": "entity_ink_duplicate_stroke_id"}
		seen_ids[sid] = true
		total_pts += (s["points"] as PackedVector2Array).size()
		if s.has("patch"):
			total_patch_bytes += (s["patch"] as PackedByteArray).size()
		if total_pts > ENTITY_INK_MAX_TOTAL or total_patch_bytes > ENTITY_INK_MAX_PATCH_TOTAL:
			return {"ok": false, "reason": "entity_ink_capacity_exceeded"}

	return {"ok": true, "reason": ""}


func attach_entity_ink(
	entity_id: String,
	strokes_or_state: Variant = [],
	revision: String = "",
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	var gate: Dictionary = _check_gate("attach_entity_ink")
	if not bool(gate.get("ok", true)):
		return gate
	var eff_strokes: Array = []
	var eff_revision: String = revision
	var eff_parked: bool = parked
	var eff_manual: bool = manual
	var input_err: String = ""

	if strokes_or_state is Array:
		eff_strokes = strokes_or_state as Array
	elif strokes_or_state is Dictionary:
		var sd: Dictionary = strokes_or_state as Dictionary
		for raw_k: Variant in sd.keys():
			if not (raw_k is String) or not (str(raw_k) in ["strokes", "revision", "parked", "manual"]):
				input_err = "entity_ink_invalid_header"
				break
		if input_err.is_empty() and sd.has("parked"):
			if sd["parked"] is bool:
				eff_parked = bool(sd["parked"])
			else:
				input_err = "entity_ink_invalid_header"
		if input_err.is_empty() and sd.has("manual"):
			if sd["manual"] is bool:
				eff_manual = bool(sd["manual"])
			else:
				input_err = "entity_ink_invalid_header"
		if input_err.is_empty() and sd.has("revision"):
			if sd["revision"] is String:
				eff_revision = str(sd["revision"])
			else:
				input_err = "entity_ink_invalid_revision"
		if input_err.is_empty() and sd.has("strokes"):
			if sd["strokes"] is Array:
				eff_strokes = _normalize_entity_ink_strokes(sd["strokes"] as Array)
			else:
				input_err = "entity_ink_invalid_header"
	else:
		input_err = "entity_ink_invalid_header"

	if eff_manual and not eff_parked:
		return {"ok": false, "reason": "manual_requires_parked"}
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}
	var entity: Dictionary = _lookup_entity(entity_id)
	if entity.is_empty():
		return {"ok": false, "reason": "entity_not_found"}
	if not input_err.is_empty():
		_warn("无法挂载 entity_ink 组件（%s）：%s" % [entity_id, input_err])
		return {"ok": false, "reason": input_err}

	var state: Dictionary = make_entity_ink_state(eff_strokes, eff_revision)
	var checked: Dictionary = validate_entity_ink_state(state, entity)
	if not bool(checked.get("ok", false)):
		var reason: String = str(checked.get("reason", "invalid_entity_ink"))
		_warn("无法挂载 entity_ink 组件（%s）：%s" % [entity_id, reason])
		return {"ok": false, "reason": reason}

	var effective_parked: bool = eff_parked or (not bool(gate.get("enabled", false)))
	var effective_manual: bool = eff_manual if (eff_parked and eff_manual) else false
	var ok: bool = bool(wb.attach_component(
		entity_id,
		COMP_ENTITY_INK_SCRIPT,
		state,
		effective_parked,
		effective_manual
	))
	if not ok:
		return {"ok": false, "reason": "attach_component_failed"}
	return {
		"ok": true,
		"entity_id": entity_id,
		"parked": effective_parked,
		"manual": effective_manual,
	}


func set_entity_ink(
	entity_id: String,
	strokes_or_state: Variant = [],
	revision: String = "",
	parked: bool = false,
	manual: bool = false
) -> Dictionary:
	return attach_entity_ink(entity_id, strokes_or_state, revision, parked, manual)


func _append_world_drawing_item(raw_item: Dictionary) -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or not bool(wb.is_ready()):
		return {"ok": false, "reason": "world_builder_not_ready"}
	var current: Dictionary = get_world_drawing_state()
	var strokes: Array = []
	var visible: bool = true
	if not current.is_empty():
		if current.get("strokes", null) is Array:
			var cloned: Variant = _safe_clone_via_adapter(current["strokes"])
			if cloned is Array:
				strokes = cloned as Array
		if current.get("visible", null) is bool:
			visible = bool(current["visible"])

	var max_order: int = 0
	var seen_orders: Dictionary = {}
	var seen_ids: Dictionary = {}
	for existing: Variant in strokes:
		if existing is Dictionary:
			var ex_d: Dictionary = existing as Dictionary
			if ex_d.get("order", null) is int:
				var ex_ord: int = int(ex_d["order"])
				seen_orders[ex_ord] = true
				max_order = maxi(max_order, ex_ord)
			if ex_d.get("id", null) is String:
				seen_ids[str(ex_d["id"])] = true

	var item_copy: Variant = _safe_clone_via_adapter(raw_item)
	if not (item_copy is Dictionary):
		return {"ok": false, "reason": "drawing_stroke_invalid"}
	var item: Dictionary = item_copy as Dictionary
	if not item.has("order") or (item["order"] is int and (int(item["order"]) < 1 or seen_orders.has(int(item["order"])))):
		item["order"] = max_order + 1
	if item.get("id", null) is String and seen_ids.has(str(item["id"])):
		var base_id: String = str(item["id"])
		var salt: int = strokes.size() + 1
		var candidate_id: String = ("%s:%d:%d" % [base_id, int(item.get("order", 0)), salt]).sha256_text().left(32)
		while seen_ids.has(candidate_id):
			salt += 1
			candidate_id = ("%s:%d:%d" % [base_id, int(item.get("order", 0)), salt]).sha256_text().left(32)
		item["id"] = candidate_id

	strokes.append(item)
	var next_state: Dictionary = make_world_drawing_state(strokes, visible)
	var checked: Dictionary = validate_world_drawing_state(next_state)
	if not bool(checked.get("ok", false)):
		return checked
	var ok: bool = bool(wb.set_module_state(MODULE_ID, MODULE_VERSION, next_state))
	if not ok:
		return {"ok": false, "reason": "set_module_state_failed"}
	return {
		"ok": true,
		"id": str(item.get("id", "")),
		"order": int(item.get("order", 0)),
		"strokes_total": strokes.size(),
	}


func _validate_entity_stroke(raw_s: Variant) -> Dictionary:
	if not (raw_s is Dictionary):
		return {"ok": false, "reason": "entity_ink_stroke_not_dict"}
	var s: Dictionary = raw_s as Dictionary
	if not (s.get("id", null) is String) or not bool(_validation_utils().is_valid_uid(str(s.get("id", "")))):
		return {"ok": false, "reason": "entity_ink_invalid_stroke_id"}
	var expected_fields: int = 7 if s.has("pressure") else 6
	var margin_v: Variant = s.get("margin", 0)
	if not (margin_v is int) or int(margin_v) < 0 or int(margin_v) > ENTITY_INK_MAX_MARGIN:
		return {"ok": false, "reason": "entity_ink_invalid_margin"}
	var margin: int = int(margin_v)
	if s.has("margin"):
		expected_fields += 1
	if s.has("clone_offset"):
		var co: Variant = s["clone_offset"]
		if not (co is Vector2) or not (co as Vector2).is_finite() or absf((co as Vector2).x) > 1.5 or absf((co as Vector2).y) > 1.5 or s.get("erase", null) != false:
			return {"ok": false, "reason": "entity_ink_invalid_clone_offset"}
		expected_fields += 1
		if s.has("patch_at"):
			if s.has("patch_grid"):
				expected_fields += 1
			if not (s.get("patch_at", null) is Vector2i):
				return {"ok": false, "reason": "entity_ink_invalid_patch_at"}
			expected_fields += 1
			if s.has("patch"):
				if not (s["patch"] is PackedByteArray) or (s["patch"] as PackedByteArray).size() > ENTITY_INK_MAX_PATCH_BYTES:
					return {"ok": false, "reason": "entity_ink_invalid_patch"}
				expected_fields += 1
			elif s.has("stamp_ref") and s.has("stamp_bytes"):
				expected_fields += 2
			else:
				return {"ok": false, "reason": "entity_ink_missing_patch"}
	if s.size() != expected_fields:
		return {"ok": false, "reason": "entity_ink_unexpected_keys"}
	if not (s.get("erase", null) is bool) or not (s.get("color", null) is Color) or not (s.get("width", null) is float) or not (s.get("opacity", null) is float):
		return {"ok": false, "reason": "entity_ink_invalid_field_types"}
	if not bool(_value_utils().is_unit_color(s["color"] as Color)):
		return {"ok": false, "reason": "entity_ink_invalid_color"}
	var w: float = float(s["width"])
	var op: float = float(s["opacity"])
	if not is_finite(w) or w < ENTITY_INK_MIN_WIDTH or w > ENTITY_INK_MAX_WIDTH:
		return {"ok": false, "reason": "entity_ink_width_out_of_range"}
	if not is_finite(op) or op <= 0.0 or op > 1.0:
		return {"ok": false, "reason": "entity_ink_opacity_out_of_range"}
	var pts_v: Variant = s.get("points", null)
	if not (pts_v is PackedVector2Array):
		return {"ok": false, "reason": "entity_ink_invalid_points"}
	var pts: PackedVector2Array = pts_v as PackedVector2Array
	if pts.is_empty() or pts.size() > ENTITY_INK_MAX_POINTS:
		return {"ok": false, "reason": "entity_ink_points_count_out_of_range"}
	var pad: float = float(margin) / 100.0
	for p: Vector2 in pts:
		if not p.is_finite() or p.x < -pad or p.y < -pad or p.x > 1.0 + pad or p.y > 1.0 + pad:
			return {"ok": false, "reason": "entity_ink_point_out_of_bounds"}
	if s.has("pressure"):
		var prs_v: Variant = s["pressure"]
		if not (prs_v is PackedFloat32Array) or (prs_v as PackedFloat32Array).size() != pts.size():
			return {"ok": false, "reason": "entity_ink_invalid_pressure"}
		for force: float in prs_v as PackedFloat32Array:
			if not is_finite(force) or force < 0.05 or force > 1.0:
				return {"ok": false, "reason": "entity_ink_pressure_out_of_range"}
	return {"ok": true, "reason": ""}


func _valid_cuts(cuts_v: Variant) -> bool:
	if not (cuts_v is Array):
		return false
	var cuts: Array = cuts_v as Array
	if cuts.is_empty() or cuts.size() > 64:
		return false
	var total_pts: int = 0
	for raw_cut: Variant in cuts:
		if not (raw_cut is Dictionary):
			return false
		var cut: Dictionary = raw_cut as Dictionary
		if not (cut.get("segments", null) is PackedVector2Array):
			return false
		total_pts += (cut["segments"] as PackedVector2Array).size()
		if total_pts > 4096:
			return false
	return true


func _row_sample_count(row: Dictionary) -> int:
	var count: int = (row["points"] as PackedVector2Array).size()
	if row.has("cuts") and row["cuts"] is Array:
		for raw_cut: Variant in row["cuts"] as Array:
			if raw_cut is Dictionary and (raw_cut as Dictionary).get("segments", null) is PackedVector2Array:
				count += ((raw_cut as Dictionary)["segments"] as PackedVector2Array).size()
	return count


func _to_packed_vec2(raw: Variant) -> PackedVector2Array:
	if raw is PackedVector2Array:
		return (raw as PackedVector2Array).duplicate()
	var out := PackedVector2Array()
	if raw is Array:
		for item: Variant in raw as Array:
			if item is Vector2 and (item as Vector2).is_finite():
				out.append(item as Vector2)
			elif item is Array and (item as Array).size() >= 2:
				var pair: Array = item as Array
				if (pair[0] is int or pair[0] is float) and (pair[1] is int or pair[1] is float):
					var v := Vector2(float(pair[0]), float(pair[1]))
					if v.is_finite():
						out.append(v)
	return out


func _number_in(value: Variant, low: float, high: float) -> bool:
	if not (value is int or value is float):
		return false
	var f: float = float(value)
	return is_finite(f) and f >= low and f <= high


func _lookup_entity(entity_id: String) -> Dictionary:
	var wb: RefCounted = _wb()
	if wb == null or entity_id.is_empty():
		return {}
	if wb.has_method("get_entity"):
		return wb.get_entity(entity_id)
	return {}


func _get_adapter() -> RefCounted:
	var wb: RefCounted = _wb()
	if wb != null and wb.has_method("get_adapter"):
		return wb.get_adapter()
	return null


func _check_gate(action: String) -> Dictionary:
	if _module_registry != null:
		return _module_registry.check_and_warn(MODULE_ID, action)
	return {"ok": true, "enabled": false, "policy": "preserve", "skipped": false}


func _warn(message: String) -> void:
	if _log_bus != null:
		_log_bus.warn(MODULE_ID, message)
	else:
		push_warning("[FuSdk/WARNING][%s] %s" % [MODULE_ID, message])


## 优先委托宿主适配器深拷贝；缺失时回退至 BoundedCloner（2097152 预算）。
func _safe_clone_via_adapter(value: Variant) -> Variant:
	var bc: Variant = _bounded_cloner()
	return bc.safe_clone_via_adapter(value, _get_adapter(), bc.DRAWING_FALLBACK_BUDGET)


## 保持白盒测试兼容性：委托 utils/bounded_cloner.gd 执行 2097152 预算有界回退克隆。
func _bounded_fallback_clone(value: Variant, depth: int = 0, active_stack: Array = [], budget: Array = []) -> Variant:
	var bc: Variant = _bounded_cloner()
	return bc.bounded_fallback_clone(value, depth, active_stack, budget, bc.DRAWING_FALLBACK_BUDGET)


func _normalize_world_drawing_strokes(raw_strokes: Array) -> Array:
	var val_u: Variant = _value_utils()
	var out: Array = []
	for raw_row: Variant in raw_strokes:
		var cloned: Variant = _safe_clone_via_adapter(raw_row)
		if cloned is Dictionary:
			var row_d: Dictionary = cloned as Dictionary
			for int_k: String in ["order", "life", "font_size", "elapsed"]:
				if row_d.has(int_k):
					var p: Dictionary = val_u.parse_int_val(row_d[int_k])
					if bool(p["ok"]):
						row_d[int_k] = int(p["value"])
			out.append(row_d)
		else:
			out.append(cloned)
	return out


func _normalize_entity_ink_strokes(raw_strokes: Array) -> Array:
	var val_u: Variant = _value_utils()
	var out: Array = []
	for raw_s: Variant in raw_strokes:
		var cloned: Variant = _safe_clone_via_adapter(raw_s)
		if cloned is Dictionary:
			var s_d: Dictionary = cloned as Dictionary
			for int_k: String in ["margin", "elapsed"]:
				if s_d.has(int_k):
					var p: Dictionary = val_u.parse_int_val(s_d[int_k])
					if bool(p["ok"]):
						s_d[int_k] = int(p["value"])
			out.append(s_d)
		else:
			out.append(cloned)
	return out
