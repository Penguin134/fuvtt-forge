extends RefCounted
## Fu vtt SDK 共享有界轻量深拷贝与环检测工具（BoundedCloner）
##
## 收敛各分插件（drawing、feature_floor_system、feature_layer_stack、backpack、
## character_roster、checklist、dice、grid_alignment、resource_pool、dnd_opportunity、
## simple_fog）的 4 类轻量有界深拷贝与环检测逻辑，保持各自既有预算、非标量键处理、
## Packed*Array 复制与错误理由语义。
## 本脚本为纯叶子级静态工具集：不声明 class_name，不调用动态 load 或 preload。

const MAX_DEPTH: int = 32
const DEFAULT_SIMPLE_BUDGET: int = 4096
const DEFAULT_FALLBACK_BUDGET: int = 16384
const DRAWING_FALLBACK_BUDGET: int = 2097152
const DEFAULT_DND_VISITS: int = 262144
const DEFAULT_SHARED_UNFOLD: int = 8192
const MEMO_BUCKET_CAP: int = 64


## 回退深拷贝上下文（用于 FallbackClone 模式，64 槽环形逻辑节点记忆化）。
class FallbackCloneCtx extends RefCounted:
	var shared_unfold: int = 0
	var max_shared_unfold: int = DEFAULT_SHARED_UNFOLD
	var last_logical_nodes: int = 1
	var exhausted: bool = false
	var dict_memo: Dictionary = {}
	var arr_memo: Dictionary = {}


## DnD 借机与卡牌深拷贝/环检测上下文（支持字典非标量键递归）。
class DndTravCtx extends RefCounted:
	var nodes: int = 0
	var max_nodes: int = DEFAULT_DND_VISITS
	var shared_unfold: int = 0
	var max_shared_unfold: int = DEFAULT_SHARED_UNFOLD
	var last_logical_nodes: int = 1
	var exhausted: bool = false
	var dict_memo: Dictionary = {}
	var arr_memo: Dictionary = {}


## 在固定容量环形桶中按引用身份查找整型缓存值（未命中返回 -1）。
static func memo_get_int(buckets: Dictionary, key: int, target: Variant) -> int:
	if not buckets.has(key):
		return -1
	var b: Dictionary = buckets[key] as Dictionary
	var refs: Array = b["refs"] as Array
	var vals: Array = b["vals"] as Array
	for i: int in range(refs.size()):
		if is_same(refs[i], target):
			return int(vals[i])
	return -1


## 将目标引用及对应整型指标写入固定容量环形桶（超出 bucket_cap 时覆盖最旧游标槽位）。
static func memo_put_int(
	buckets: Dictionary,
	key: int,
	target: Variant,
	val: int,
	bucket_cap: int = MEMO_BUCKET_CAP
) -> void:
	var b: Dictionary
	if buckets.has(key):
		b = buckets[key] as Dictionary
	else:
		b = {"refs": [], "vals": [], "cursor": 0}
		buckets[key] = b
	var refs: Array = b["refs"] as Array
	var vals: Array = b["vals"] as Array
	for i: int in range(refs.size()):
		if is_same(refs[i], target):
			vals[i] = val
			return
	if refs.size() < bucket_cap:
		refs.append(target)
		vals.append(val)
	else:
		var c: int = int(b["cursor"])
		refs[c] = target
		vals[c] = val
		b["cursor"] = (c + 1) % bucket_cap


## 优先通过适配器 _safe_clone_variant 深拷贝；适配器缺失时回退至有界 FallbackClone。
static func safe_clone_via_adapter(
	value: Variant,
	adapter: RefCounted = null,
	default_budget: int = DEFAULT_FALLBACK_BUDGET
) -> Variant:
	if adapter != null and adapter.has_method("_safe_clone_variant"):
		return adapter._safe_clone_variant(value, 0, [], [])
	return bounded_fallback_clone(value, 0, [], [default_budget, false], default_budget)


## 有界共享展开回退深拷贝（跳过容器/对象类字典键，复制 Packed*Array）。
static func bounded_fallback_clone(
	value: Variant,
	depth: int = 0,
	active_stack: Array = [],
	budget: Array = [],
	default_budget: int = DEFAULT_FALLBACK_BUDGET,
	max_shared_unfold: int = DEFAULT_SHARED_UNFOLD
) -> Variant:
	var active_budget: Array = budget if not budget.is_empty() else [default_budget, false]
	var ctx := FallbackCloneCtx.new()
	ctx.max_shared_unfold = max_shared_unfold
	var res: Variant = bounded_fallback_clone_node(value, depth, active_stack, active_budget, ctx, false)
	if res == null and ctx.exhausted:
		if value is Dictionary:
			return {}
		if value is Array:
			return []
	return res


## FallbackClone 单节点递归实现：保持共享展开上限与零 null 合成语义。
static func bounded_fallback_clone_node(
	value: Variant,
	depth: int,
	active_stack: Array,
	budget: Array,
	ctx: FallbackCloneCtx,
	in_unfold: bool
) -> Variant:
	var rem: int = int(budget[0])
	if rem <= 0 or depth > MAX_DEPTH or ctx.exhausted or (budget.size() > 1 and bool(budget[1])):
		ctx.exhausted = true
		if budget.size() > 1:
			budget[1] = true
		ctx.last_logical_nodes = 1
		return null
	budget[0] = rem - 1
	if value is Dictionary:
		var d: Dictionary = value as Dictionary
		for item: Variant in active_stack:
			if is_same(item, d):
				ctx.exhausted = true
				if budget.size() > 1:
					budget[1] = true
				ctx.last_logical_nodes = 1
				return null
		var d_sz: int = d.size()
		var child_unfold: bool = in_unfold
		if d_sz > 0:
			var mln: int = memo_get_int(ctx.dict_memo, d_sz, d)
			if mln >= 0:
				if not in_unfold:
					if ctx.shared_unfold + mln > ctx.max_shared_unfold:
						ctx.exhausted = true
						if budget.size() > 1:
							budget[1] = true
						ctx.last_logical_nodes = 1
						return null
					ctx.shared_unfold += mln
				child_unfold = true
		active_stack.append(d)
		var out_d: Dictionary = {}
		var logical_nodes: int = 1
		for k: Variant in d.keys():
			if typeof(k) in [TYPE_DICTIONARY, TYPE_ARRAY, TYPE_OBJECT, TYPE_CALLABLE, TYPE_SIGNAL, TYPE_RID]:
				continue
			if depth >= MAX_DEPTH or int(budget[0]) <= 0 or ctx.exhausted or (budget.size() > 1 and bool(budget[1])):
				ctx.exhausted = true
				if budget.size() > 1:
					budget[1] = true
				break
			budget[0] = int(budget[0]) - 1
			var cv: Variant = bounded_fallback_clone_node(d[k], depth + 1, active_stack, budget, ctx, child_unfold)
			if ctx.exhausted or (budget.size() > 1 and bool(budget[1])):
				break
			out_d[k] = cv
			logical_nodes += 1 + ctx.last_logical_nodes
		active_stack.pop_back()
		if not ctx.exhausted and not (budget.size() > 1 and bool(budget[1])) and d_sz > 0 and logical_nodes >= 3:
			memo_put_int(ctx.dict_memo, d_sz, d, logical_nodes)
		ctx.last_logical_nodes = logical_nodes
		return out_d
	if value is Array:
		var a: Array = value as Array
		for item: Variant in active_stack:
			if is_same(item, a):
				ctx.exhausted = true
				if budget.size() > 1:
					budget[1] = true
				ctx.last_logical_nodes = 1
				return null
		var a_sz: int = a.size()
		var child_unfold_a: bool = in_unfold
		if a_sz > 0:
			var mlna: int = memo_get_int(ctx.arr_memo, a_sz, a)
			if mlna >= 0:
				if not in_unfold:
					if ctx.shared_unfold + mlna > ctx.max_shared_unfold:
						ctx.exhausted = true
						if budget.size() > 1:
							budget[1] = true
						ctx.last_logical_nodes = 1
						return null
					ctx.shared_unfold += mlna
				child_unfold_a = true
		active_stack.append(a)
		var out_a: Array = []
		var logical_nodes_a: int = 1
		for item_v: Variant in a:
			if depth >= MAX_DEPTH or int(budget[0]) <= 0 or ctx.exhausted or (budget.size() > 1 and bool(budget[1])):
				ctx.exhausted = true
				if budget.size() > 1:
					budget[1] = true
				break
			var ci: Variant = bounded_fallback_clone_node(item_v, depth + 1, active_stack, budget, ctx, child_unfold_a)
			if ctx.exhausted or (budget.size() > 1 and bool(budget[1])):
				break
			out_a.append(ci)
			logical_nodes_a += ctx.last_logical_nodes
		active_stack.pop_back()
		if not ctx.exhausted and not (budget.size() > 1 and bool(budget[1])) and a_sz > 0 and logical_nodes_a >= 3:
			memo_put_int(ctx.arr_memo, a_sz, a, logical_nodes_a)
		ctx.last_logical_nodes = logical_nodes_a
		return out_a
	ctx.last_logical_nodes = 1
	if typeof(value) >= TYPE_PACKED_BYTE_ARRAY:
		return value.duplicate()
	return value


## 无记忆化轻量有界字典深拷贝（默认 4096 访问预算；用于简单状态与 dag24 预算耗尽检测）。
static func simple_clone_dict(
	d: Dictionary,
	depth: int = 0,
	stack: Array = [],
	budget: Array = [],
	duplicate_packed: bool = false
) -> Dictionary:
	var active_budget: Array = budget if not budget.is_empty() else [DEFAULT_SIMPLE_BUDGET, false]
	var res: Variant = simple_clone_var(d, depth, stack, active_budget, duplicate_packed)
	return res as Dictionary if res is Dictionary else {}


## 无记忆化轻量有界数组深拷贝（默认 4096 访问预算）。
static func simple_clone_array(
	arr: Array,
	depth: int = 0,
	stack: Array = [],
	budget: Array = [],
	duplicate_packed: bool = false
) -> Array:
	var active_budget: Array = budget if not budget.is_empty() else [DEFAULT_SIMPLE_BUDGET, false]
	var res: Variant = simple_clone_var(arr, depth, stack, active_budget, duplicate_packed)
	return res as Array if res is Array else []


## 无记忆化轻量有界 Variant 深拷贝：严格保持中止/深度>=32 时零 null 合成语义。
static func simple_clone_var(
	v: Variant,
	depth: int = 0,
	stack: Array = [],
	budget: Array = [],
	duplicate_packed: bool = false
) -> Variant:
	var active_budget: Array = budget if not budget.is_empty() else [DEFAULT_SIMPLE_BUDGET, false]
	if depth > MAX_DEPTH:
		if active_budget.size() > 1:
			active_budget[1] = true
		return null
	if int(active_budget[0]) <= 0:
		if active_budget.size() > 1:
			active_budget[1] = true
		return null
	active_budget[0] = int(active_budget[0]) - 1
	if v is Dictionary:
		var d: Dictionary = v as Dictionary
		for s: Variant in stack:
			if is_same(s, d):
				if active_budget.size() > 1:
					active_budget[1] = true
				return null
		stack.append(d)
		var out := {}
		for k: Variant in d.keys():
			if depth >= MAX_DEPTH or int(active_budget[0]) <= 0 or (active_budget.size() > 1 and bool(active_budget[1])):
				if active_budget.size() > 1:
					active_budget[1] = true
				break
			var ck: Variant = simple_clone_var(k, depth + 1, stack, active_budget, duplicate_packed)
			if (active_budget.size() > 1 and bool(active_budget[1])) or int(active_budget[0]) <= 0:
				if active_budget.size() > 1:
					active_budget[1] = true
				break
			var cv: Variant = simple_clone_var(d[k], depth + 1, stack, active_budget, duplicate_packed)
			if active_budget.size() > 1 and bool(active_budget[1]):
				break
			out[ck] = cv
		stack.pop_back()
		return out
	if v is Array:
		var arr: Array = v as Array
		for s: Variant in stack:
			if is_same(s, arr):
				if active_budget.size() > 1:
					active_budget[1] = true
				return null
		stack.append(arr)
		var out_a := []
		for item: Variant in arr:
			if depth >= MAX_DEPTH or int(active_budget[0]) <= 0 or (active_budget.size() > 1 and bool(active_budget[1])):
				if active_budget.size() > 1:
					active_budget[1] = true
				break
			var ci: Variant = simple_clone_var(item, depth + 1, stack, active_budget, duplicate_packed)
			if active_budget.size() > 1 and bool(active_budget[1]):
				break
			out_a.append(ci)
		stack.pop_back()
		return out_a
	if duplicate_packed and typeof(v) >= TYPE_PACKED_BYTE_ARRAY:
		return v.duplicate()
	return v


## 检测任意 Variant（含字典键中的嵌套容器）是否存在循环引用、超深或超出访问预算。
static func has_cycle(
	v: Variant,
	depth: int = 0,
	stack: Array = [],
	budget: Array = [],
	max_visits: int = DEFAULT_DND_VISITS
) -> bool:
	var tctx := DndTravCtx.new()
	tctx.max_nodes = int(budget[0]) if not budget.is_empty() else max_visits
	var h: int = cycle_check_height(v, depth, stack, tctx)
	if not budget.is_empty():
		budget[0] = maxi(0, tctx.max_nodes - tctx.nodes)
	return h < 0


## 计算容器高度并检测环路；异常时返回 -1，合法 DAG 子树高度写入记忆化桶。
static func cycle_check_height(v: Variant, depth: int, stack: Array, tctx: DndTravCtx) -> int:
	if depth > MAX_DEPTH:
		return -1
	tctx.nodes += 1
	if tctx.nodes > tctx.max_nodes:
		return -1
	if v is Dictionary:
		var d: Dictionary = v as Dictionary
		for s: Variant in stack:
			if is_same(s, d):
				return -1
		var d_sz: int = d.size()
		if depth == MAX_DEPTH:
			return 0 if d_sz == 0 else -1
		if d_sz > 0:
			var cached_h: int = memo_get_int(tctx.dict_memo, d_sz, d)
			if cached_h >= 0:
				return cached_h if depth + cached_h <= MAX_DEPTH else -1
		var start_nodes: int = tctx.nodes
		stack.append(d)
		var max_h: int = 0
		var d_keys: Array = d.keys()
		var d_vals: Array = d.values()
		for i: int in range(d_sz):
			var k: Variant = d_keys[i]
			if k is Dictionary or k is Array:
				var kh: int = cycle_check_height(k, depth + 1, stack, tctx)
				if kh < 0:
					stack.pop_back()
					return -1
				max_h = maxi(max_h, 1 + kh)
			else:
				tctx.nodes += 1
				if tctx.nodes > tctx.max_nodes:
					stack.pop_back()
					return -1
				max_h = maxi(max_h, 1)
			var val: Variant = d_vals[i]
			if val is Dictionary or val is Array:
				var vh: int = cycle_check_height(val, depth + 1, stack, tctx)
				if vh < 0:
					stack.pop_back()
					return -1
				max_h = maxi(max_h, 1 + vh)
			else:
				tctx.nodes += 1
				if tctx.nodes > tctx.max_nodes:
					stack.pop_back()
					return -1
				max_h = maxi(max_h, 1)
		stack.pop_back()
		if d_sz > 0 and (max_h >= 2 or (tctx.nodes - start_nodes) >= 10):
			memo_put_int(tctx.dict_memo, d_sz, d, max_h)
		return max_h
	if v is Array:
		var arr: Array = v as Array
		for s: Variant in stack:
			if is_same(s, arr):
				return -1
		var a_sz: int = arr.size()
		if depth == MAX_DEPTH:
			return 0 if a_sz == 0 else -1
		if a_sz > 0:
			var cached_ha: int = memo_get_int(tctx.arr_memo, a_sz, arr)
			if cached_ha >= 0:
				return cached_ha if depth + cached_ha <= MAX_DEPTH else -1
		var start_nodes_a: int = tctx.nodes
		stack.append(arr)
		var max_ha: int = 0
		for item: Variant in arr:
			if item is Dictionary or item is Array:
				var ih: int = cycle_check_height(item, depth + 1, stack, tctx)
				if ih < 0:
					stack.pop_back()
					return -1
				max_ha = maxi(max_ha, 1 + ih)
			else:
				tctx.nodes += 1
				if tctx.nodes > tctx.max_nodes:
					stack.pop_back()
					return -1
				max_ha = maxi(max_ha, 1)
		stack.pop_back()
		if a_sz > 0 and (max_ha >= 2 or (tctx.nodes - start_nodes_a) >= 10):
			memo_put_int(tctx.arr_memo, a_sz, arr, max_ha)
		return max_ha
	return 0


## DnD 专用的有界深拷贝字典入口（支持嵌套容器键与 Packed*Array 复制）。
static func dnd_clone_dict(
	d: Dictionary,
	depth: int = 0,
	stack: Array = [],
	budget: Array = [],
	max_visits: int = DEFAULT_DND_VISITS,
	max_shared_unfold: int = DEFAULT_SHARED_UNFOLD
) -> Dictionary:
	var active_budget: Array = budget if not budget.is_empty() else [max_visits, false]
	var res: Variant = dnd_clone_var(d, depth, stack, active_budget, max_visits, max_shared_unfold)
	return res as Dictionary if res is Dictionary else {}


## DnD 专用的有界深拷贝 Variant 入口。
static func dnd_clone_var(
	v: Variant,
	depth: int = 0,
	stack: Array = [],
	budget: Array = [],
	max_visits: int = DEFAULT_DND_VISITS,
	max_shared_unfold: int = DEFAULT_SHARED_UNFOLD
) -> Variant:
	var active_budget: Array = budget if not budget.is_empty() else [max_visits, false]
	var tctx := DndTravCtx.new()
	tctx.max_nodes = max_visits
	tctx.max_shared_unfold = max_shared_unfold
	return dnd_clone_node(v, depth, stack, active_budget, tctx, false)


## DnD 有界深拷贝单节点递归实现（含共享展开上限与 Packed*Array.duplicate()）。
static func dnd_clone_node(
	v: Variant,
	depth: int,
	stack: Array,
	active_budget: Array,
	tctx: DndTravCtx,
	in_unfold: bool
) -> Variant:
	if depth > MAX_DEPTH or int(active_budget[0]) <= 0 or tctx.exhausted or (active_budget.size() > 1 and bool(active_budget[1])):
		tctx.exhausted = true
		if active_budget.size() > 1:
			active_budget[1] = true
		tctx.last_logical_nodes = 1
		return null
	active_budget[0] = int(active_budget[0]) - 1
	if v is Dictionary:
		var d: Dictionary = v as Dictionary
		for s: Variant in stack:
			if is_same(s, d):
				tctx.exhausted = true
				if active_budget.size() > 1:
					active_budget[1] = true
				tctx.last_logical_nodes = 1
				return null
		var d_sz: int = d.size()
		var child_unfold: bool = in_unfold
		if d_sz > 0:
			var mln: int = memo_get_int(tctx.dict_memo, d_sz, d)
			if mln >= 0:
				if not in_unfold:
					if tctx.shared_unfold + mln > tctx.max_shared_unfold:
						tctx.exhausted = true
						if active_budget.size() > 1:
							active_budget[1] = true
						tctx.last_logical_nodes = 1
						return null
					tctx.shared_unfold += mln
				child_unfold = true
		stack.append(d)
		var out := {}
		var logical_nodes: int = 1
		var d_keys: Array = d.keys()
		var d_vals: Array = d.values()
		for i: int in range(d_sz):
			if depth >= MAX_DEPTH or int(active_budget[0]) <= 0 or tctx.exhausted or (active_budget.size() > 1 and bool(active_budget[1])):
				tctx.exhausted = true
				if active_budget.size() > 1:
					active_budget[1] = true
				break
			var k: Variant = d_keys[i]
			var ck: Variant
			if not (k is Dictionary or k is Array):
				if int(active_budget[0]) <= 0:
					tctx.exhausted = true
					if active_budget.size() > 1:
						active_budget[1] = true
					break
				active_budget[0] = int(active_budget[0]) - 1
				ck = k.duplicate() if typeof(k) >= TYPE_PACKED_BYTE_ARRAY else k
				logical_nodes += 1
			else:
				ck = dnd_clone_node(k, depth + 1, stack, active_budget, tctx, child_unfold)
				if tctx.exhausted or (active_budget.size() > 1 and bool(active_budget[1])) or int(active_budget[0]) <= 0:
					tctx.exhausted = true
					if active_budget.size() > 1:
						active_budget[1] = true
					break
				logical_nodes += tctx.last_logical_nodes
			var raw_val: Variant = d_vals[i]
			var cv: Variant
			if not (raw_val is Dictionary or raw_val is Array):
				if int(active_budget[0]) <= 0:
					tctx.exhausted = true
					if active_budget.size() > 1:
						active_budget[1] = true
					break
				active_budget[0] = int(active_budget[0]) - 1
				cv = raw_val.duplicate() if typeof(raw_val) >= TYPE_PACKED_BYTE_ARRAY else raw_val
				logical_nodes += 1
			else:
				cv = dnd_clone_node(raw_val, depth + 1, stack, active_budget, tctx, child_unfold)
				if tctx.exhausted or (active_budget.size() > 1 and bool(active_budget[1])):
					break
				logical_nodes += tctx.last_logical_nodes
			out[ck] = cv
		stack.pop_back()
		if not tctx.exhausted and not (active_budget.size() > 1 and bool(active_budget[1])) and d_sz > 0 and logical_nodes >= 3:
			memo_put_int(tctx.dict_memo, d_sz, d, logical_nodes)
		tctx.last_logical_nodes = logical_nodes
		return out
	if v is Array:
		var arr: Array = v as Array
		for s: Variant in stack:
			if is_same(s, arr):
				tctx.exhausted = true
				if active_budget.size() > 1:
					active_budget[1] = true
				tctx.last_logical_nodes = 1
				return null
		var a_sz: int = arr.size()
		var child_unfold_a: bool = in_unfold
		if a_sz > 0:
			var mlna: int = memo_get_int(tctx.arr_memo, a_sz, arr)
			if mlna >= 0:
				if not in_unfold:
					if tctx.shared_unfold + mlna > tctx.max_shared_unfold:
						tctx.exhausted = true
						if active_budget.size() > 1:
							active_budget[1] = true
						tctx.last_logical_nodes = 1
						return null
					tctx.shared_unfold += mlna
				child_unfold_a = true
		stack.append(arr)
		var out_a := []
		var logical_nodes_a: int = 1
		for item: Variant in arr:
			if depth >= MAX_DEPTH or int(active_budget[0]) <= 0 or tctx.exhausted or (active_budget.size() > 1 and bool(active_budget[1])):
				tctx.exhausted = true
				if active_budget.size() > 1:
					active_budget[1] = true
				break
			var ci: Variant
			if not (item is Dictionary or item is Array):
				if int(active_budget[0]) <= 0:
					tctx.exhausted = true
					if active_budget.size() > 1:
						active_budget[1] = true
					break
				active_budget[0] = int(active_budget[0]) - 1
				ci = item.duplicate() if typeof(item) >= TYPE_PACKED_BYTE_ARRAY else item
				logical_nodes_a += 1
			else:
				ci = dnd_clone_node(item, depth + 1, stack, active_budget, tctx, child_unfold_a)
				if tctx.exhausted or (active_budget.size() > 1 and bool(active_budget[1])):
					break
				logical_nodes_a += tctx.last_logical_nodes
			out_a.append(ci)
		stack.pop_back()
		if not tctx.exhausted and not (active_budget.size() > 1 and bool(active_budget[1])) and a_sz > 0 and logical_nodes_a >= 3:
			memo_put_int(tctx.arr_memo, a_sz, arr, logical_nodes_a)
		tctx.last_logical_nodes = logical_nodes_a
		return out_a
	tctx.last_logical_nodes = 1
	return v.duplicate() if typeof(v) >= TYPE_PACKED_BYTE_ARRAY else v


## 简单迷雾配置覆盖字典深拷贝：严格校验 String 键、深度、预算与环路并返回原因码。
static func clone_fog_overrides(
	value: Variant,
	depth: int = 0,
	stack: Array = [],
	budget: Array = []
) -> Dictionary:
	var active_budget: Array = budget if not budget.is_empty() else [DEFAULT_SIMPLE_BUDGET]
	if depth > MAX_DEPTH:
		return {"ok": false, "reason": "fog_config_too_deep"}
	var rem: int = int(active_budget[0]) - 1
	if rem < 0:
		return {"ok": false, "reason": "fog_config_too_large"}
	active_budget[0] = rem
	if value is Dictionary:
		var d: Dictionary = value as Dictionary
		for s: Variant in stack:
			if is_same(s, d):
				return {"ok": false, "reason": "invalid_fog_config_cycle"}
		stack.append(d)
		var out_d: Dictionary = {}
		for k: Variant in d.keys():
			if not (k is String):
				stack.pop_back()
				return {"ok": false, "reason": "unknown_fog_config_key_type"}
			var cloned_v: Dictionary = clone_fog_overrides(d[k], depth + 1, stack, active_budget)
			if not bool(cloned_v.get("ok", false)):
				stack.pop_back()
				return cloned_v
			out_d[k as String] = cloned_v["value"]
		stack.pop_back()
		return {"ok": true, "value": out_d}
	if value is Array:
		var arr: Array = value as Array
		for s: Variant in stack:
			if is_same(s, arr):
				return {"ok": false, "reason": "invalid_fog_config_cycle"}
		stack.append(arr)
		var out_a: Array = []
		for item: Variant in arr:
			var cloned_i: Dictionary = clone_fog_overrides(item, depth + 1, stack, active_budget)
			if not bool(cloned_i.get("ok", false)):
				stack.pop_back()
				return cloned_i
			out_a.append(cloned_i["value"])
		stack.pop_back()
		return {"ok": true, "value": out_a}
	if value is PackedByteArray:
		return {"ok": true, "value": (value as PackedByteArray).duplicate()}
	return {"ok": true, "value": value}
