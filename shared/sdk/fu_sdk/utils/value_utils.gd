extends RefCounted
## Fu vtt SDK 共享基础类型转换、整数解析与颜色规整工具（ValueUtils）
##
## 收敛 host_v1_adapter、v1.gd 与各分插件中的整数/布尔/浮点/字符串强制转换、
## 64 位有符号整数安全解析及 Color 值校验与归一化逻辑，消除跨模块重复实现并
## 保留各调用方既有边界语义（如 JSON 浮点整数化、64 位溢出拒收、NaN 透传开关等）。
## 本脚本为纯叶子级静态工具集：不声明 class_name，不调用动态 load 或 preload。

const MAX_SAFE_FLOAT_INT: float = 9007199254740991.0
const MIN_SAFE_FLOAT_INT: float = -9007199254740991.0


## 剥离字符串头部连续 UTF-8 BOM (0xFEFF) 与首尾空白，直至收敛（叶子隔离内部辅助）。
static func _strip_bom_and_edges(text: String) -> String:
	var cleaned: String = text
	while true:
		var next_cleaned: String = cleaned
		while next_cleaned.begins_with(char(0xfeff)):
			next_cleaned = next_cleaned.substr(1)
		next_cleaned = next_cleaned.strip_edges()
		if next_cleaned == cleaned:
			break
		cleaned = next_cleaned
	return cleaned


## 解析严格整型值：接受 int 或在 JS 安全整数范围内的有限整数值 float，拒绝 String 与 bool。
static func parse_int_val(v: Variant) -> Dictionary:
	if v is int:
		return {"ok": true, "value": int(v)}
	if v is float:
		var f: float = float(v)
		if is_finite(f) and f == floor(f) and f >= MIN_SAFE_FLOAT_INT and f <= MAX_SAFE_FLOAT_INT:
			return {"ok": true, "value": int(f)}
	return {"ok": false, "value": 0}


## 精确解析 64 位有符号整数字符串（规避 Godot String.to_int() 溢出静默钳制，超界返回 null）。
static func parse_int64_str(s: String) -> Variant:
	var t: String = s.strip_edges()
	if t.is_empty():
		return null
	var negative: bool = false
	var idx: int = 0
	var first_ch: int = t.unicode_at(0)
	if first_ch == 45:
		negative = true
		idx = 1
	elif first_ch == 43:
		idx = 1
	var n: int = t.length()
	if idx >= n:
		return null
	for i: int in range(idx, n):
		var c: int = t.unicode_at(i)
		if c < 48 or c > 57:
			return null
	while idx < n and t.unicode_at(idx) == 48:
		idx += 1
	if idx == n:
		return 0
	var digits: String = t.substr(idx)
	var dlen: int = digits.length()
	if dlen > 19:
		return null
	if dlen == 19:
		var limit: String = "9223372036854775808" if negative else "9223372036854775807"
		if digits > limit:
			return null
		if negative and digits == "9223372036854775808":
			return -9223372036854775807 - 1
	var mag: int = int(digits)
	return -mag if negative else mag


## 将 Variant 安全转换为 bool（支持布尔、数值及常见真假字符串；可选是否剥离头部 BOM）。
static func coerce_bool(value: Variant, fallback: bool = false, strip_bom: bool = true) -> bool:
	match typeof(value):
		TYPE_BOOL:
			return value == true
		TYPE_INT:
			return int(value) != 0
		TYPE_FLOAT:
			var num: float = float(value)
			if not is_finite(num):
				return fallback
			return num != 0.0
		TYPE_STRING, TYPE_STRING_NAME:
			var normalized: String = (_strip_bom_and_edges(str(value)) if strip_bom else String(value).strip_edges()).to_lower()
			match normalized:
				"true", "1", "yes", "on":
					return true
				"false", "0", "no", "off":
					return false
				_:
					return fallback
		_:
			return fallback


## 将 Variant 安全转换为 int；strict_int64=true 时启用 BOM 清理、64 位溢出拒收与浮点字符串回退。
static func coerce_int(value: Variant, fallback: int = 0, strict_int64: bool = true) -> int:
	if value == null:
		return fallback
	var t: int = typeof(value)
	if t == TYPE_INT:
		return int(value)
	if t == TYPE_FLOAT:
		var f: float = float(value)
		if is_finite(f) and f >= -9223372036854775808.0 and f < 9223372036854775808.0:
			return int(f)
		return fallback
	if strict_int64:
		if t == TYPE_STRING or t == TYPE_STRING_NAME:
			var s: String = _strip_bom_and_edges(str(value))
			var parsed_i64: Variant = parse_int64_str(s)
			if parsed_i64 != null:
				return int(parsed_i64)
			if s.is_valid_int():
				return fallback
			if s.is_valid_float():
				var fs: float = s.to_float()
				if is_finite(fs) and fs >= -9223372036854775808.0 and fs < 9223372036854775808.0:
					return int(fs)
	elif t == TYPE_STRING and str(value).is_valid_int():
		return str(value).to_int()
	return fallback


## 将 Variant 安全转换为 float；require_finite=false 时保留 NAN/INF 供下游数值校验显式拒绝。
static func coerce_float(value: Variant, fallback: float = 0.0, require_finite: bool = true) -> float:
	if value == null:
		return fallback
	var t: int = typeof(value)
	if t == TYPE_INT:
		return float(value)
	if t == TYPE_FLOAT:
		var f: float = float(value)
		if not require_finite:
			return f
		return f if is_finite(f) else fallback
	if require_finite:
		if t == TYPE_STRING or t == TYPE_STRING_NAME:
			var s: String = _strip_bom_and_edges(str(value))
			if s.is_valid_float():
				var fs: float = s.to_float()
				if is_finite(fs):
					return fs
	elif t == TYPE_STRING and str(value).is_valid_float():
		return str(value).to_float()
	return fallback


## 严格提取 TYPE_STRING 值（不隐式转换 StringName/数值/容器），否则返回 fallback。
static func coerce_string(value: Variant, fallback: String = "") -> String:
	if typeof(value) == TYPE_STRING:
		return value as String
	return fallback


## 提取 String 或 StringName 文本，其他类型安全返回 fallback（避免 str(容器) 崩溃或泄漏）。
static func as_str(value: Variant, fallback: String = "") -> String:
	if value is String:
		return value as String
	if value is StringName:
		return String(value)
	return fallback


## 标量字符串提取（兼容 String / StringName / NodePath / bool / int / float，绝不展开容器或 Object）。
static func coerce_str_scalar(value: Variant, fallback: String = "") -> String:
	match typeof(value):
		TYPE_STRING, TYPE_STRING_NAME, TYPE_NODE_PATH:
			return String(value)
		TYPE_BOOL, TYPE_INT, TYPE_FLOAT:
			return str(value)
		_:
			return fallback


## 判断 Color 四通道是否均为有限浮点数。
static func is_finite_color(c: Color) -> bool:
	return is_finite(c.r) and is_finite(c.g) and is_finite(c.b) and is_finite(c.a)


## 判断 Color 四通道是否有限且均处于单位区间 [0.0, 1.0]。
static func is_unit_color(c: Color) -> bool:
	return (
		is_finite_color(c)
		and c.r >= 0.0 and c.r <= 1.0
		and c.g >= 0.0 and c.g <= 1.0
		and c.b >= 0.0 and c.b <= 1.0
		and c.a >= 0.0 and c.a <= 1.0
	)


## 将 Color 四通道钳位至 [0.0, 1.0]；若存在非有限通道则返回 fallback。
static func clamp_color(c: Color, fallback: Color = Color.BLACK) -> Color:
	if not is_finite_color(c):
		return fallback
	return Color(
		clampf(c.r, 0.0, 1.0),
		clampf(c.g, 0.0, 1.0),
		clampf(c.b, 0.0, 1.0),
		clampf(c.a, 0.0, 1.0)
	)


## 校验 8 位十六进制 RGBA 颜色字符串（格式 #RRGGBBAA）。
static func is_hex8_color(color_str: String) -> bool:
	if color_str.length() != 9 or not color_str.begins_with("#"):
		return false
	for i: int in range(1, 9):
		var c: int = color_str.unicode_at(i)
		var ok: bool = (c >= 48 and c <= 57) or (c >= 97 and c <= 102) or (c >= 65 and c <= 70)
		if not ok:
			return false
	return true


## 将 Color / [r,g,b(,a)] / {r,g,b(,a)} / HTML 颜色字符串规整为 {"ok": bool, "color": Color}。
static func coerce_color_value(raw: Variant, fallback: Color = Color.BLACK) -> Dictionary:
	if raw is Color:
		var c: Color = raw as Color
		if is_unit_color(c):
			return {"ok": true, "color": c}
		return {"ok": false, "color": fallback}
	if raw is Array:
		var arr: Array = raw as Array
		if arr.size() == 3 or arr.size() == 4:
			var ch: Array[float] = []
			for i: int in range(arr.size()):
				var v: Variant = arr[i]
				if not (v is int or v is float):
					return {"ok": false, "color": fallback}
				var fv: float = float(v)
				if not is_finite(fv) or fv < 0.0 or fv > 1.0:
					return {"ok": false, "color": fallback}
				ch.append(fv)
			var a_val: float = ch[3] if ch.size() == 4 else 1.0
			return {"ok": true, "color": Color(ch[0], ch[1], ch[2], a_val)}
		return {"ok": false, "color": fallback}
	if raw is Dictionary:
		var d: Dictionary = raw as Dictionary
		if d.has("r") and d.has("g") and d.has("b"):
			var r_v: Variant = d.get("r")
			var g_v: Variant = d.get("g")
			var b_v: Variant = d.get("b")
			var a_v: Variant = d.get("a", 1.0)
			if (
				(r_v is int or r_v is float)
				and (g_v is int or g_v is float)
				and (b_v is int or b_v is float)
				and (a_v is int or a_v is float)
			):
				var rf: float = float(r_v)
				var gf: float = float(g_v)
				var bf: float = float(b_v)
				var af: float = float(a_v)
				if (
					is_finite(rf) and rf >= 0.0 and rf <= 1.0
					and is_finite(gf) and gf >= 0.0 and gf <= 1.0
					and is_finite(bf) and bf >= 0.0 and bf <= 1.0
					and is_finite(af) and af >= 0.0 and af <= 1.0
				):
					return {"ok": true, "color": Color(rf, gf, bf, af)}
		return {"ok": false, "color": fallback}
	if raw is String or raw is StringName:
		var s: String = str(raw).strip_edges()
		if not s.is_empty() and Color.html_is_valid(s):
			var parsed: Color = Color.html(s)
			if is_unit_color(parsed):
				return {"ok": true, "color": parsed}
		return {"ok": false, "color": fallback}
	return {"ok": false, "color": fallback}


## 将颜色输入转换为未钳位 RGBA 四元数组（供 grid_alignment validate_config 捕获越界通道）；不匹配时原样返回。
static func coerce_color_array(raw: Variant) -> Variant:
	if raw is Color:
		var c: Color = raw as Color
		return [c.r, c.g, c.b, c.a]
	if raw is Array:
		var arr: Array = raw as Array
		if arr.size() == 3:
			return [arr[0], arr[1], arr[2], 1.0]
		return arr.duplicate()
	if raw is String or raw is StringName:
		var s: String = str(raw).strip_edges()
		if not s.is_empty() and Color.html_is_valid(s):
			var parsed: Color = Color.html(s)
			return [parsed.r, parsed.g, parsed.b, parsed.a]
		return raw
	if raw is Dictionary:
		var d: Dictionary = raw as Dictionary
		if d.has("r") and d.has("g") and d.has("b"):
			return [d["r"], d["g"], d["b"], d.get("a", 1.0)]
	return raw
