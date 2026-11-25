extends RefCounted
## Fu vtt SDK 共享标识符校验、控制字符清理与宿主实体判断工具（ValidationUtils）
##
## 收敛 host_v1_adapter、log_bus 与各分插件中的十六进制 UID/SHA256 校验、
## UTF-8 BOM/NUL/控制字符剥离与检测、组件脚本 ID 提取及 unit 宿主判断逻辑。
## 本脚本为纯叶子级静态工具集：不声明 class_name，不调用动态 load 或 preload。


## 校验定长十六进制字符串（allow_uppercase=false 时仅允许小写 [0-9a-f]）。
static func is_valid_hex(val: String, expected_len: int, allow_uppercase: bool = false) -> bool:
	if val.length() != expected_len:
		return false
	for i: int in range(expected_len):
		var c: int = val.unicode_at(i)
		var is_digit: bool = c >= 48 and c <= 57
		var is_hex_lower: bool = c >= 97 and c <= 102
		var is_hex_upper: bool = allow_uppercase and c >= 65 and c <= 70
		if not is_digit and not is_hex_lower and not is_hex_upper:
			return false
	return true


## 校验 32 位小写十六进制 UID（如 floor_uid / layer_uid / entity_id / scene_uid）。
static func is_valid_uid(uid: String) -> bool:
	return is_valid_hex(uid, 32, false)


## 校验 24 位小写十六进制标识符（如 dice 请求/记录 ID）。
static func is_valid_hex24(val: String) -> bool:
	return is_valid_hex(val, 24, false)


## 校验 64 位十六进制摘要/修订哈希（如 SHA-256；allow_uppercase=true 时兼容大写修订号）。
static func is_valid_hex64(val: String, allow_uppercase: bool = false) -> bool:
	return is_valid_hex(val, 64, allow_uppercase)


## 剥离字符串头部连续 UTF-8 BOM (0xFEFF)。
static func strip_leading_bom(text: String) -> String:
	var cleaned: String = text
	while cleaned.begins_with(char(0xfeff)):
		cleaned = cleaned.substr(1)
	return cleaned


## 循环剥离头部 BOM 与首尾空白直至不动点，避免“空白+BOM”绕过单次 strip_edges()。
static func strip_bom_and_edges(text: String) -> String:
	var cleaned: String = text
	while true:
		var next_cleaned: String = strip_leading_bom(cleaned).strip_edges()
		if next_cleaned == cleaned:
			break
		cleaned = next_cleaned
	return cleaned


## 检测字符串是否包含 NUL 字节 (0x00)。
static func has_nul(text: String) -> bool:
	for i: int in range(text.length()):
		if text.unicode_at(i) == 0:
			return true
	return false


## 剥离字符串中的 NUL 字节 (0x00)；无 NUL 时走快速路径零拷贝返回原串。
static func strip_nul(text: String) -> String:
	var found_nul: bool = false
	for idx: int in range(text.length()):
		if text.unicode_at(idx) == 0:
			found_nul = true
			break
	if not found_nul:
		return text
	var out: String = ""
	for idx: int in range(text.length()):
		if text.unicode_at(idx) != 0:
			out += text.substr(idx, 1)
	return out


## 剥离 NUL 字节、头部 BOM 及首尾空白（用于 portal pair_key 等严格标识规整）。
static func strip_control_and_edges(text: String) -> String:
	return strip_leading_bom(strip_nul(text)).strip_edges()


## 清理单行日志文本：移除回车符 \r 与 NUL 字节。
static func sanitize_line_text(text: String) -> String:
	return strip_nul(text.replace("\r", ""))


## 检测字符串是否包含 ASCII 控制字符（<32 或 ==127）；include_c1=true 时同步拦截 C1 控制字符 (127..159)。
static func has_control_chars(text: String, include_c1: bool = false) -> bool:
	for i: int in range(text.length()):
		var c: int = text.unicode_at(i)
		if include_c1:
			if c < 32 or (c >= 127 and c <= 159):
				return true
		elif c < 32 or c == 127:
			return true
	return false


## 检测是否包含除水平制表符 (\t, 9) 外的 ASCII 控制字符。
static func has_control_except_tab(text: String) -> bool:
	for i: int in range(text.length()):
		var c: int = text.unicode_at(i)
		if (c < 32 and c != 9) or c == 127:
			return true
	return false


## 从组件脚本路径（如 res://.../comp_unit.gd）提取规范组件 ID（剥离 comp_ 前缀）。
static func component_id_from_script(script_path: String) -> String:
	var base: String = script_path.get_file().get_basename()
	return base.substr(5) if base.begins_with("comp_") else base


## 判断实体字典是否满足“单位宿主（unit host）”契约（map 排除，selectable 或未停放 comp_unit 放行）。
static func is_unit_host(entity: Dictionary) -> bool:
	var raw_etype: Variant = entity.get("entity_type", "")
	var etype: String = str(raw_etype) if (raw_etype is String or raw_etype is StringName) else ""
	if etype == "map":
		return false
	if bool(entity.get("selectable_in_select_mode", false)):
		return true
	var components_var: Variant = entity.get("components", null)
	if components_var is Array:
		for raw_comp: Variant in components_var as Array:
			if raw_comp is Dictionary:
				var c: Dictionary = raw_comp as Dictionary
				var raw_scr: Variant = c.get("script", "")
				var scr: String = str(raw_scr) if (raw_scr is String or raw_scr is StringName) else ""
				if component_id_from_script(scr) == "unit" and not bool(c.get("parked", false)):
					return true
	return false
