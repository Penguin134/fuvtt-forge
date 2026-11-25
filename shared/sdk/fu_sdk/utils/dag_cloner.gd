extends RefCounted
## Fu vtt SDK 共享有界 DAG 深拷贝与防抖记忆化工具（DagCloner）
##
## 收敛 host_v1_adapter、log_bus、module_registry、feature_entity_library 与
## feature_obstacle_authoring 共同使用的有界 DAG 遍历、循环引用拦截、深度裁剪（默认 32）
## 与双层防抖记忆化缓存（heavy / ring / ghost / ghost_prob + clipped_buckets）。
## 本脚本为纯叶子级静态工具集：不声明 class_name，不调用动态 load 或 preload。

const MAX_CLONE_VISITS: int = 2097152
const MAX_ESTIMATE_VISITS: int = 2097152
const DEFAULT_MAX_CLONE_BYTES: int = 16 * 1024 * 1024
const LOG_BUS_MAX_CLONE_BYTES: int = 4 * 1024 * 1024
const DEFAULT_MAX_DEPTH: int = 32
const MAX_DAG_MEMO_ENTRIES: int = 32
const MAX_DAG_MEMO_HEAVY: int = 20
const DAG_MEMO_RING_CAP: int = 12
const DAG_MEMO_GHOST_CAP: int = 128
const DAG_MEMO_GHOST_PROB_CAP: int = 128
const DAG_MEMO_AGE_STEP: int = 256
const DAG_MEMO_AGE_SHIFT: int = 8
const DAG_MEMO_MIN_LOGICAL_NODES: int = 16
const DAG_MEMO_MIN_HEIGHT: int = 1
const MAX_DAG_LOGICAL_NODES_CLAMP: int = 1073741824
const MAX_CLONE_SHARED_SUBTREE: int = 4096
const MAX_CLONE_SHARED_UNFOLD: int = 8192


## 记忆化缓存条目，记录子树的引用、高度、估算字节数、逻辑节点数与已克隆结果。
class DagMemoEntry extends RefCounted:
	var ref: Variant = null
	var height: int = 0
	var size: int = 0
	var logical_nodes: int = 1
	var work_nodes: int = 1
	var owner_frame: int = 0
	var clock: int = 0
	var age_clock: int = 0
	var hits: int = 0
	var cloned: Variant = null


## 按容器长度分桶的防抖记忆化桶：包含 heavy 常驻层、ring 候选环、ghost 幽灵历史与概率幽灵层。
class DagMemoBucket extends RefCounted:
	var heavy: Array = []
	var heavy_refs: Array = []
	var ring: Array = []
	var ring_refs: Array = []
	var ghost: Array = []
	var ghost_h: Array = []
	var ghost_hits: Array = []
	var ghost_work: Array = []
	var ghost_clock: Array = []
	var ghost_by_h: Dictionary = {}
	var ghost_prob: Array = []
	var ghost_prob_h: Array = []
	var ghost_prob_hits: Array = []
	var ghost_prob_by_h: Dictionary = {}
	var ghost_prob_cursor: int = 0
	var ghost_prob_zero_cnt: int = 0
	var ghost_dirty: bool = true
	var ghost_min_u_idx: int = -1
	var ghost_min_u_work: int = 0x7fffffff
	var ghost_min_g_idx: int = -1
	var ghost_min_g_score: int = 0x7fffffffffffffff
	var ghost_min_g_hits: int = 0x7fffffff
	var ghost_min_g_work: int = 0x7fffffff
	var clock: int = 0
	var hit_clock: int = 0


## 单次 DAG 遍历（clone / validate / sanitize / estimate）共享的上下文与预算状态。
class DagTravCtx extends RefCounted:
	var mode: String = ""
	var nodes: int = 0
	var max_nodes: int = MAX_CLONE_VISITS
	var bytes: int = 0
	var max_bytes: int = DEFAULT_MAX_CLONE_BYTES
	var max_depth: int = DEFAULT_MAX_DEPTH
	var shared_unfold: int = 0
	var aborted: bool = false
	var depth_clipped: bool = false
	var cycle_clipped: bool = false
	var limit_exceeded: bool = false
	var last_height: int = 0
	var last_bytes: int = 0
	var last_logical_nodes: int = 1
	var frame_seq: int = 0
	var active_frames: Array = []
	var live_frames: Dictionary = {}
	var dict_buckets: Dictionary = {}
	var arr_buckets: Dictionary = {}
	var clipped_dict_buckets: Dictionary = {}
	var clipped_arr_buckets: Dictionary = {}
	var _frame_counts: Dictionary = {}


## 判断目标容器是否处于当前递归调用栈中（用于拦截直接或间接循环引用）。
static func is_in_active_stack(target: Variant, active_stack: Array) -> bool:
	for item: Variant in active_stack:
		if is_same(item, target):
			return true
	return false


## 按命中时钟衰减陈旧重条目的 hits 计数，避免一次性热点长期霸占 heavy 槽位。
static func memo_age_entry(b: DagMemoBucket, cur: DagMemoEntry) -> void:
	if cur.hits <= 0:
		return
	var last_act: int = maxi(cur.age_clock, 0)
	var elapsed: int = b.hit_clock - last_act
	if elapsed >= DAG_MEMO_AGE_STEP:
		var shifts: int = mini(30, elapsed >> DAG_MEMO_AGE_SHIFT)
		if shifts > 0:
			cur.hits = cur.hits >> shifts
			cur.age_clock = b.hit_clock


## 从主 ghost 队列及按高度索引表中移除指定槽位。
static func memo_remove_ghost_at(b: DagMemoBucket, g_idx: int) -> void:
	var old_ref: Variant = b.ghost[g_idx]
	var old_h: int = int(b.ghost_h[g_idx])
	b.ghost.remove_at(g_idx)
	b.ghost_h.remove_at(g_idx)
	b.ghost_hits.remove_at(g_idx)
	b.ghost_work.remove_at(g_idx)
	b.ghost_clock.remove_at(g_idx)
	b.ghost_dirty = true
	if b.ghost_by_h.has(old_h):
		var gh_arr: Array = b.ghost_by_h[old_h] as Array
		for i: int in range(gh_arr.size()):
			if is_same(gh_arr[i], old_ref):
				gh_arr.remove_at(i)
				break
		if gh_arr.is_empty():
			b.ghost_by_h.erase(old_h)


## 从概率 ghost 队列及按高度索引表中移除指定槽位，并修正轮转游标。
static func memo_remove_ghost_prob_at(b: DagMemoBucket, p_idx: int) -> void:
	var old_ref: Variant = b.ghost_prob[p_idx]
	var old_h: int = int(b.ghost_prob_h[p_idx])
	if int(b.ghost_prob_hits[p_idx]) <= 0:
		b.ghost_prob_zero_cnt = maxi(0, b.ghost_prob_zero_cnt - 1)
	b.ghost_prob.remove_at(p_idx)
	b.ghost_prob_h.remove_at(p_idx)
	b.ghost_prob_hits.remove_at(p_idx)
	var gp_sz: int = b.ghost_prob.size()
	if gp_sz == 0:
		b.ghost_prob_cursor = 0
	elif p_idx < b.ghost_prob_cursor:
		b.ghost_prob_cursor = maxi(0, b.ghost_prob_cursor - 1)
	elif b.ghost_prob_cursor >= gp_sz:
		b.ghost_prob_cursor = 0
	if b.ghost_prob_by_h.has(old_h):
		var gp_arr: Array = b.ghost_prob_by_h[old_h] as Array
		for i: int in range(gp_arr.size()):
			if is_same(gp_arr[i], old_ref):
				gp_arr.remove_at(i)
				break
		if gp_arr.is_empty():
			b.ghost_prob_by_h.erase(old_h)


## 将被主 ghost 淘汰或降级的引用写入概率幽灵层，保护高命中引用不被零命中噪声驱逐。
static func memo_push_ghost_prob(b: DagMemoBucket, target_ref: Variant, height: int, hits: int) -> void:
	if target_ref == null:
		return
	var norm_hits: int = maxi(0, hits)
	var cap_sz: int = b.ghost_prob.size()
	if cap_sz >= DAG_MEMO_GHOST_PROB_CAP:
		if norm_hits <= 0 and b.ghost_prob_zero_cnt <= 0:
			return
		var start_c: int = b.ghost_prob_cursor if b.ghost_prob_cursor < cap_sz else 0
		var ev_idx: int = -1
		if b.ghost_prob_zero_cnt > 0:
			for idx: int in range(start_c, cap_sz):
				if int(b.ghost_prob_hits[idx]) <= 0:
					ev_idx = idx
					break
			if ev_idx < 0:
				for idx: int in range(0, start_c):
					if int(b.ghost_prob_hits[idx]) <= 0:
						ev_idx = idx
						break
			if ev_idx < 0:
				b.ghost_prob_zero_cnt = 0
				if norm_hits <= 0:
					return
		if ev_idx < 0:
			if norm_hits <= 1:
				ev_idx = start_c
			else:
				for idx: int in range(start_c, cap_sz):
					if int(b.ghost_prob_hits[idx]) < norm_hits:
						ev_idx = idx
						break
				if ev_idx < 0:
					for idx: int in range(0, start_c):
						if int(b.ghost_prob_hits[idx]) < norm_hits:
							ev_idx = idx
							break
				if ev_idx < 0:
					ev_idx = start_c
		b.ghost_prob_cursor = ev_idx + 1 if ev_idx + 1 < cap_sz else 0
		var old_ref: Variant = b.ghost_prob[ev_idx]
		var old_h: int = int(b.ghost_prob_h[ev_idx])
		var old_hits: int = int(b.ghost_prob_hits[ev_idx])
		if old_hits <= 0 and norm_hits > 0:
			b.ghost_prob_zero_cnt = maxi(0, b.ghost_prob_zero_cnt - 1)
		elif old_hits > 0 and norm_hits <= 0:
			b.ghost_prob_zero_cnt += 1
		b.ghost_prob[ev_idx] = target_ref
		b.ghost_prob_h[ev_idx] = height
		b.ghost_prob_hits[ev_idx] = norm_hits
		if old_h == height:
			var gp_same: Array = b.ghost_prob_by_h[height] as Array
			if gp_same.size() == cap_sz:
				gp_same[ev_idx] = target_ref
			else:
				for j: int in range(gp_same.size()):
					if is_same(gp_same[j], old_ref):
						gp_same[j] = target_ref
						break
		else:
			if b.ghost_prob_by_h.has(old_h):
				var gp_old: Array = b.ghost_prob_by_h[old_h] as Array
				for j: int in range(gp_old.size()):
					if is_same(gp_old[j], old_ref):
						gp_old.remove_at(j)
						break
				if gp_old.is_empty():
					b.ghost_prob_by_h.erase(old_h)
			if not b.ghost_prob_by_h.has(height):
				b.ghost_prob_by_h[height] = [target_ref]
			else:
				var gp_new: Array = b.ghost_prob_by_h[height] as Array
				var ins_pos: int = 0
				for k: int in range(ev_idx):
					if int(b.ghost_prob_h[k]) == height:
						ins_pos += 1
				gp_new.insert(ins_pos, target_ref)
		return
	if norm_hits <= 0:
		b.ghost_prob_zero_cnt += 1
	b.ghost_prob.append(target_ref)
	b.ghost_prob_h.append(height)
	b.ghost_prob_hits.append(norm_hits)
	if not b.ghost_prob_by_h.has(height):
		b.ghost_prob_by_h[height] = [target_ref]
	else:
		(b.ghost_prob_by_h[height] as Array).append(target_ref)


## 在标准桶（Dictionary 或 Array 按长度分桶）中查找目标容器的记忆化条目。
static func memo_find(tctx: DagTravCtx, is_dict: bool, sz: int, target: Variant) -> DagMemoEntry:
	return memo_find_in_buckets(tctx, tctx.dict_buckets if is_dict else tctx.arr_buckets, sz, target)


## 将 ring 候选层中再次命中的条目晋升至 heavy 常驻层，必要时驱逐冷帧或低分条目。
static func memo_promote_ring_entry(tctx: DagTravCtx, b: DagMemoBucket, r_idx: int, e: DagMemoEntry) -> void:
	if b.heavy.size() < MAX_DAG_MEMO_HEAVY:
		b.heavy.append(e)
		b.heavy_refs.append(e.ref)
		b.ring.remove_at(r_idx)
		b.ring_refs.remove_at(r_idx)
		return
	var live: Dictionary = tctx.live_frames
	var cur_owner: int = int(tctx.active_frames[tctx.active_frames.size() - 1]) if not tctx.active_frames.is_empty() else 0
	var e_score: int = (mini(maxi(0, e.hits), 1048576) + 1) * mini(maxi(1, e.work_nodes), 1048576)
	var can_age: bool = b.hit_clock >= DAG_MEMO_AGE_STEP
	var cold_idx: int = -1
	var cold_hits: int = 0x7fffffff
	var cold_work: int = 0x7fffffff
	var cold_clock: int = 0x7fffffff
	var outer_unhit_idx: int = -1
	var outer_work: int = 0x7fffffff
	var outer_clock: int = 0x7fffffff
	var weaker_idx: int = -1
	var weak_score: int = 0x7fffffffffffffff
	var weak_hits: int = 0x7fffffff
	var weak_clock: int = 0x7fffffff
	for idx: int in range(MAX_DAG_MEMO_HEAVY):
		var cur: DagMemoEntry = b.heavy[idx] as DagMemoEntry
		var cur_f: int = cur.owner_frame
		if cur_f != 0 and not live.has(cur_f):
			if cur.hits < cold_hits or (cur.hits == cold_hits and (cur.work_nodes < cold_work or (cur.work_nodes == cold_work and cur.clock < cold_clock))):
				cold_hits = cur.hits
				cold_work = cur.work_nodes
				cold_clock = cur.clock
				cold_idx = idx
		elif cold_idx < 0:
			if can_age and cur.hits > 0 and b.hit_clock - cur.age_clock >= DAG_MEMO_AGE_STEP:
				memo_age_entry(b, cur)
			if cur.hits == 0 and cur_f != e.owner_frame and cur_f != cur_owner and (e.hits >= 2 or cur.work_nodes <= e_score):
				if cur.work_nodes < outer_work or (cur.work_nodes == outer_work and cur.clock < outer_clock):
					outer_work = cur.work_nodes
					outer_clock = cur.clock
					outer_unhit_idx = idx
			var cur_score: int = (mini(maxi(0, cur.hits), 1048576) + 1) * mini(maxi(1, cur.work_nodes), 1048576)
			if cur_score < weak_score or (cur_score == weak_score and (cur.hits < weak_hits or (cur.hits == weak_hits and cur.clock < weak_clock))):
				if cur_score < e_score or (cur_score == e_score and cur.hits < e.hits):
					weak_score = cur_score
					weak_hits = cur.hits
					weak_clock = cur.clock
					weaker_idx = idx
	var v_idx: int = cold_idx if cold_idx >= 0 else (outer_unhit_idx if outer_unhit_idx >= 0 else weaker_idx)
	if v_idx >= 0:
		var displaced: DagMemoEntry = b.heavy[v_idx] as DagMemoEntry
		b.heavy[v_idx] = e
		b.heavy_refs[v_idx] = e.ref
		b.ring[r_idx] = displaced
		b.ring_refs[r_idx] = displaced.ref


## 原地替换主 ghost 队列指定槽位，并维护 ghost_by_h 高度索引一致。
static func memo_replace_ghost_at(
	b: DagMemoBucket,
	g_idx: int,
	target_ref: Variant,
	height: int,
	safe_hits: int,
	safe_work: int
) -> void:
	var old_ref: Variant = b.ghost[g_idx]
	var old_h: int = int(b.ghost_h[g_idx])
	var g_sz: int = b.ghost.size()
	b.ghost[g_idx] = target_ref
	b.ghost_h[g_idx] = height
	b.ghost_hits[g_idx] = safe_hits
	b.ghost_work[g_idx] = safe_work
	b.ghost_clock[g_idx] = b.clock
	b.ghost_dirty = true
	if old_h == height:
		var gh_same: Array = b.ghost_by_h[height] as Array
		if gh_same.size() == g_sz:
			gh_same[g_idx] = target_ref
		else:
			for j: int in range(gh_same.size()):
				if is_same(gh_same[j], old_ref):
					gh_same[j] = target_ref
					break
	else:
		if b.ghost_by_h.has(old_h):
			var gh_old: Array = b.ghost_by_h[old_h] as Array
			for j: int in range(gh_old.size()):
				if is_same(gh_old[j], old_ref):
					gh_old.remove_at(j)
					break
			if gh_old.is_empty():
				b.ghost_by_h.erase(old_h)
		if not b.ghost_by_h.has(height):
			b.ghost_by_h[height] = [target_ref]
		else:
			var gh_new: Array = b.ghost_by_h[height] as Array
			var ins_pos: int = 0
			for k: int in range(g_idx):
				if int(b.ghost_h[k]) == height:
					ins_pos += 1
			gh_new.insert(ins_pos, target_ref)


## 将被淘汰条目的历史引用压入主 ghost 层；满容时按工作量与命中分值准入/降级。
static func memo_push_ghost(b: DagMemoBucket, target_ref: Variant, height: int, hits: int = 0, work_nodes: int = 1) -> void:
	if target_ref == null:
		return
	var safe_hits: int = maxi(0, hits)
	var safe_work: int = maxi(1, work_nodes)
	var g_sz: int = b.ghost.size()
	if g_sz >= DAG_MEMO_GHOST_CAP:
		if b.ghost_dirty:
			var r_u_idx: int = -1
			var r_u_work: int = 0x7fffffff
			var r_u_clock: int = 0x7fffffff
			var r_g_idx: int = -1
			var r_g_score: int = 0x7fffffffffffffff
			var r_g_hits: int = 0x7fffffff
			var r_g_work: int = 0x7fffffff
			var r_g_clock: int = 0x7fffffff
			for i: int in range(g_sz):
				var gh: int = int(b.ghost_hits[i])
				var gw: int = int(b.ghost_work[i])
				var gc: int = int(b.ghost_clock[i])
				if gh <= 0:
					if gw < r_u_work or (gw == r_u_work and gc < r_u_clock):
						r_u_work = gw
						r_u_clock = gc
						r_u_idx = i
				elif r_u_idx < 0:
					var h_c: int = mini(gh, 1048576) + 1
					var w_c: int = mini(maxi(1, gw), 1048576)
					var gs: int = h_c * w_c
					if gs < r_g_score or (gs == r_g_score and (gh < r_g_hits or (gh == r_g_hits and gc < r_g_clock))):
						r_g_score = gs
						r_g_hits = gh
						r_g_work = gw
						r_g_clock = gc
						r_g_idx = i
			b.ghost_min_u_idx = r_u_idx
			b.ghost_min_u_work = r_u_work
			b.ghost_min_g_idx = r_g_idx
			b.ghost_min_g_score = r_g_score
			b.ghost_min_g_hits = r_g_hits
			b.ghost_min_g_work = r_g_work
			b.ghost_dirty = false
		var min_u_idx: int = b.ghost_min_u_idx
		var min_u_work: int = b.ghost_min_u_work
		var min_g_idx: int = b.ghost_min_g_idx
		var min_g_score: int = b.ghost_min_g_score
		var min_g_hits: int = b.ghost_min_g_hits
		var min_g_work: int = b.ghost_min_g_work
		var cand_score: int = (mini(safe_hits, 1048576) + 1) * mini(safe_work, 1048576) if safe_hits > 0 else mini(safe_work, 1048576)
		if min_u_idx >= 0:
			if safe_hits > 0 or safe_work > min_u_work:
				memo_replace_ghost_at(b, min_u_idx, target_ref, height, safe_hits, safe_work)
				return
			memo_push_ghost_prob(b, target_ref, height, 0)
			return
		elif safe_hits > 0 and min_g_idx >= 0 and (safe_hits > min_g_hits or cand_score > min_g_score or (safe_hits == min_g_hits and safe_work > min_g_work)):
			var dem_ref: Variant = b.ghost[min_g_idx]
			var dem_h: int = int(b.ghost_h[min_g_idx])
			var dem_hits: int = int(b.ghost_hits[min_g_idx])
			memo_replace_ghost_at(b, min_g_idx, target_ref, height, safe_hits, safe_work)
			memo_push_ghost_prob(b, dem_ref, dem_h, dem_hits)
			return
		else:
			memo_push_ghost_prob(b, target_ref, height, safe_hits)
			return
	b.ghost.append(target_ref)
	b.ghost_h.append(height)
	b.ghost_hits.append(safe_hits)
	b.ghost_work.append(safe_work)
	b.ghost_clock.append(b.clock)
	b.ghost_dirty = true
	if not b.ghost_by_h.has(height):
		b.ghost_by_h[height] = [target_ref]
	else:
		(b.ghost_by_h[height] as Array).append(target_ref)


## 查询并弹出 ghost / ghost_prob 中匹配的同高度引用，返回继承后的初始命中次数。
static func memo_pop_matching_ghost(b: DagMemoBucket, target: Variant, height: int) -> int:
	if b.ghost_by_h.is_empty() and b.ghost_prob_by_h.is_empty():
		return 0
	if b.ghost_by_h.has(height):
		var gh_arr: Array = b.ghost_by_h[height] as Array
		var gh_sz: int = gh_arr.size()
		var g_full_same: bool = gh_sz == b.ghost.size()
		for gh_i: int in range(gh_sz):
			if is_same(gh_arr[gh_i], target):
				var g_idx: int = gh_i
				if not g_full_same:
					g_idx = -1
					for gi: int in range(b.ghost.size()):
						if is_same(b.ghost[gi], target):
							g_idx = gi
							break
				if g_idx >= 0:
					var prev_hits: int = int(b.ghost_hits[g_idx])
					memo_remove_ghost_at(b, g_idx)
					return prev_hits + 1
				break
	if b.ghost_prob_by_h.has(height):
		var gp_arr: Array = b.ghost_prob_by_h[height] as Array
		var gp_sz: int = gp_arr.size()
		var gp_full_same: bool = gp_sz == b.ghost_prob.size()
		for gp_i: int in range(gp_sz):
			if is_same(gp_arr[gp_i], target):
				var p_idx: int = gp_i
				if not gp_full_same:
					p_idx = -1
					for pi: int in range(b.ghost_prob.size()):
						if is_same(b.ghost_prob[pi], target):
							p_idx = pi
							break
				if p_idx >= 0:
					var prev_p_hits: int = int(b.ghost_prob_hits[p_idx])
					memo_remove_ghost_prob_at(b, p_idx)
					return prev_p_hits + 1
				break
	return 0


## 在指定桶映射中按 bucket_key 查找目标引用；命中 ring 时自动尝试晋升至 heavy。
static func memo_find_in_buckets(tctx: DagTravCtx, buckets: Dictionary, bucket_key: int, target: Variant) -> DagMemoEntry:
	var b_var: Variant = buckets.get(bucket_key, null)
	if b_var == null:
		return null
	var b: DagMemoBucket = b_var as DagMemoBucket
	var h_refs: Array = b.heavy_refs
	for h_idx: int in range(h_refs.size()):
		if is_same(h_refs[h_idx], target):
			var e: DagMemoEntry = b.heavy[h_idx] as DagMemoEntry
			b.clock += 1
			b.hit_clock += 1
			e.clock = b.clock
			e.age_clock = b.hit_clock
			e.hits += 1
			return e
	var r_refs: Array = b.ring_refs
	for r_idx: int in range(r_refs.size()):
		if is_same(r_refs[r_idx], target):
			var re: DagMemoEntry = b.ring[r_idx] as DagMemoEntry
			b.clock += 1
			b.hit_clock += 1
			re.clock = b.clock
			re.age_clock = b.hit_clock
			re.hits += 1
			memo_promote_ring_entry(tctx, b, r_idx, re)
			return re
	return null


## 将子容器遍历结果写入标准桶（仅当高度 >= 1 且逻辑节点数 >= 16 时入桶防抖）。
static func memo_store(
	tctx: DagTravCtx,
	is_dict: bool,
	sz: int,
	target: Variant,
	height: int,
	size_val: int,
	ln: int,
	cloned_val: Variant = null,
	work_nodes: int = 1
) -> void:
	var buckets: Dictionary = tctx.dict_buckets if is_dict else tctx.arr_buckets
	memo_store_in_buckets(tctx, buckets, sz, target, height, size_val, ln, cloned_val, work_nodes)


## 将子容器遍历结果写入指定桶映射，协调 heavy / ring / ghost 三级防抖驱逐。
static func memo_store_in_buckets(
	tctx: DagTravCtx,
	buckets: Dictionary,
	bucket_key: int,
	target: Variant,
	height: int,
	size_val: int,
	ln: int,
	cloned_val: Variant = null,
	work_nodes: int = 1
) -> void:
	if height < DAG_MEMO_MIN_HEIGHT or ln < DAG_MEMO_MIN_LOGICAL_NODES:
		return
	var b: DagMemoBucket
	if buckets.has(bucket_key):
		b = buckets[bucket_key] as DagMemoBucket
	else:
		b = DagMemoBucket.new()
		buckets[bucket_key] = b
	b.clock += 1
	var initial_hits: int = memo_pop_matching_ghost(b, target, height)
	if initial_hits > 0:
		b.hit_clock += 1
	var owner_f: int = int(tctx.active_frames[tctx.active_frames.size() - 1]) if not tctx.active_frames.is_empty() else 0
	var safe_work: int = maxi(1, work_nodes)

	if b.heavy.size() < MAX_DAG_MEMO_HEAVY:
		var new_e_fast := DagMemoEntry.new()
		new_e_fast.ref = target
		new_e_fast.height = height
		new_e_fast.size = size_val
		new_e_fast.logical_nodes = ln
		new_e_fast.work_nodes = safe_work
		new_e_fast.owner_frame = owner_f
		new_e_fast.clock = b.clock
		new_e_fast.age_clock = b.hit_clock
		new_e_fast.hits = initial_hits
		new_e_fast.cloned = cloned_val
		b.heavy.append(new_e_fast)
		b.heavy_refs.append(target)
		return

	var live: Dictionary = tctx.live_frames
	var can_age: bool = b.hit_clock >= DAG_MEMO_AGE_STEP
	var new_score: int = (mini(maxi(0, initial_hits), 1048576) + 1) * mini(safe_work, 1048576)
	var cold_idx: int = -1
	var cold_hits: int = 0x7fffffff
	var cold_work: int = 0x7fffffff
	var cold_clock: int = 0x7fffffff
	var our_count: int = 0
	var min_unhit_idx: int = -1
	var min_unhit_work: int = 0x7fffffff
	var min_unhit_clock: int = 0x7fffffff
	var min_score_idx: int = -1
	var min_heavy_score: int = 0x7fffffffffffffff
	var min_heavy_hits: int = 0x7fffffff
	var min_heavy_clock: int = 0x7fffffff
	var other_unhit_idx: int = -1
	var other_unhit_clock: int = 0x7fffffff
	var other_old_idx: int = -1
	var other_old_clock: int = 0x7fffffff
	for idx: int in range(MAX_DAG_MEMO_HEAVY):
		var cur: DagMemoEntry = b.heavy[idx] as DagMemoEntry
		var cur_f: int = cur.owner_frame
		if cur_f != 0 and not live.has(cur_f):
			if cur.hits < cold_hits or (cur.hits == cold_hits and (cur.work_nodes < cold_work or (cur.work_nodes == cold_work and cur.clock < cold_clock))):
				cold_hits = cur.hits
				cold_work = cur.work_nodes
				cold_clock = cur.clock
				cold_idx = idx
		elif cold_idx < 0:
			if cur_f == owner_f:
				our_count += 1
			else:
				if cur.hits == 0 and cur.clock < other_unhit_clock:
					other_unhit_clock = cur.clock
					other_unhit_idx = idx
				if cur.clock < other_old_clock:
					other_old_clock = cur.clock
					other_old_idx = idx
			if cur.hits == 0 and (cur.work_nodes < min_unhit_work or (cur.work_nodes == min_unhit_work and cur.clock < min_unhit_clock)):
				min_unhit_work = cur.work_nodes
				min_unhit_clock = cur.clock
				min_unhit_idx = idx
			if initial_hits > 0:
				if can_age and cur.hits > 0 and b.hit_clock - cur.age_clock >= DAG_MEMO_AGE_STEP:
					memo_age_entry(b, cur)
				var cur_score: int = (mini(maxi(0, cur.hits), 1048576) + 1) * mini(maxi(1, cur.work_nodes), 1048576)
				if cur_score < min_heavy_score or (cur_score == min_heavy_score and (cur.hits < min_heavy_hits or (cur.hits == min_heavy_hits and cur.clock < min_heavy_clock))):
					min_heavy_score = cur_score
					min_heavy_hits = cur.hits
					min_heavy_clock = cur.clock
					min_score_idx = idx

	var victim_idx: int = -1
	if cold_idx >= 0:
		victim_idx = cold_idx
	elif min_unhit_idx >= 0 and (new_score > min_unhit_work or (initial_hits > 0 and new_score >= min_unhit_work)):
		victim_idx = min_unhit_idx
	elif initial_hits > 0 and min_score_idx >= 0 and new_score > min_heavy_score:
		victim_idx = min_score_idx
	elif our_count == 0 and owner_f != 0:
		var frame_counts: Dictionary = tctx._frame_counts
		frame_counts.clear()
		var best_f: int = 0
		var best_cnt: int = 1
		for idx: int in range(MAX_DAG_MEMO_HEAVY):
			var cur_f2: int = (b.heavy[idx] as DagMemoEntry).owner_frame
			var nc: int = int(frame_counts.get(cur_f2, 0)) + 1
			frame_counts[cur_f2] = nc
			if nc > best_cnt:
				best_cnt = nc
				best_f = cur_f2
		if best_cnt > 1:
			var best_hits: int = 0x7fffffff
			var best_work: int = 0x7fffffff
			var best_clock: int = 0x7fffffff
			for idx: int in range(MAX_DAG_MEMO_HEAVY):
				var cur2: DagMemoEntry = b.heavy[idx] as DagMemoEntry
				if cur2.owner_frame == best_f:
					if cur2.hits < best_hits or (cur2.hits == best_hits and (cur2.work_nodes < best_work or (cur2.work_nodes == best_work and cur2.clock < best_clock))):
						best_hits = cur2.hits
						best_work = cur2.work_nodes
						best_clock = cur2.clock
						victim_idx = idx
		else:
			victim_idx = other_unhit_idx if other_unhit_idx >= 0 else other_old_idx

	var pre_r_victim: int = -1
	if victim_idx < 0 and b.ring.size() >= DAG_MEMO_RING_CAP and initial_hits == 0:
		var r_cold_idx0: int = -1
		var r_cold_hits0: int = 0x7fffffff
		var r_cold_work0: int = 0x7fffffff
		var r_cold_clock0: int = 0x7fffffff
		var r_small_idx0: int = -1
		var r_small_work0: int = 0x7fffffff
		var r_small_clock0: int = 0x7fffffff
		for r_i: int in range(DAG_MEMO_RING_CAP):
			var rc0: DagMemoEntry = b.ring[r_i] as DagMemoEntry
			var rf0: int = rc0.owner_frame
			if rf0 != 0 and not live.has(rf0):
				if rc0.hits < r_cold_hits0 or (rc0.hits == r_cold_hits0 and (rc0.work_nodes < r_cold_work0 or (rc0.work_nodes == r_cold_work0 and rc0.clock < r_cold_clock0))):
					r_cold_hits0 = rc0.hits
					r_cold_work0 = rc0.work_nodes
					r_cold_clock0 = rc0.clock
					r_cold_idx0 = r_i
			elif r_cold_idx0 < 0 and rc0.hits == 0 and rc0.work_nodes < safe_work:
				if rc0.work_nodes < r_small_work0 or (rc0.work_nodes == r_small_work0 and rc0.clock < r_small_clock0):
					r_small_work0 = rc0.work_nodes
					r_small_clock0 = rc0.clock
					r_small_idx0 = r_i
		pre_r_victim = r_cold_idx0 if r_cold_idx0 >= 0 else r_small_idx0
		if pre_r_victim < 0:
			memo_push_ghost(b, target, height, 0, safe_work)
			return

	var new_e := DagMemoEntry.new()
	new_e.ref = target
	new_e.height = height
	new_e.size = size_val
	new_e.logical_nodes = ln
	new_e.work_nodes = safe_work
	new_e.owner_frame = owner_f
	new_e.clock = b.clock
	new_e.age_clock = b.hit_clock
	new_e.hits = initial_hits
	new_e.cloned = cloned_val

	var ring_cand: DagMemoEntry = new_e
	if victim_idx >= 0:
		var displaced: DagMemoEntry = b.heavy[victim_idx] as DagMemoEntry
		b.heavy[victim_idx] = new_e
		b.heavy_refs[victim_idx] = target
		var disp_f: int = displaced.owner_frame
		if disp_f != 0 and not live.has(disp_f) and b.ring.size() >= DAG_MEMO_RING_CAP:
			memo_push_ghost(b, displaced.ref, displaced.height, displaced.hits, displaced.work_nodes)
			return
		ring_cand = displaced

	if b.ring.size() < DAG_MEMO_RING_CAP:
		b.ring.append(ring_cand)
		b.ring_refs.append(ring_cand.ref)
		return

	var r_victim: int = pre_r_victim
	if r_victim < 0:
		var r_cold_idx: int = -1
		var r_cold_hits: int = 0x7fffffff
		var r_cold_work: int = 0x7fffffff
		var r_cold_clock: int = 0x7fffffff
		var r_small_idx: int = -1
		var r_small_work: int = 0x7fffffff
		var r_small_clock: int = 0x7fffffff
		var r_min_idx: int = -1
		var r_min_score: int = 0x7fffffffffffffff
		var r_min_hits: int = 0x7fffffff
		var r_min_clock: int = 0x7fffffff
		var cand_work: int = ring_cand.work_nodes
		var cand_hits: int = ring_cand.hits
		var cand_score: int = (mini(maxi(0, cand_hits), 1048576) + 1) * mini(maxi(1, cand_work), 1048576) if cand_hits > 0 else mini(maxi(1, cand_work), 1048576)
		for r_i: int in range(DAG_MEMO_RING_CAP):
			var rc: DagMemoEntry = b.ring[r_i] as DagMemoEntry
			var rf: int = rc.owner_frame
			if rf != 0 and not live.has(rf):
				if rc.hits < r_cold_hits or (rc.hits == r_cold_hits and (rc.work_nodes < r_cold_work or (rc.work_nodes == r_cold_work and rc.clock < r_cold_clock))):
					r_cold_hits = rc.hits
					r_cold_work = rc.work_nodes
					r_cold_clock = rc.clock
					r_cold_idx = r_i
			elif r_cold_idx < 0:
				if cand_hits == 0:
					if rc.hits == 0 and rc.work_nodes < cand_work:
						if rc.work_nodes < r_small_work or (rc.work_nodes == r_small_work and rc.clock < r_small_clock):
							r_small_work = rc.work_nodes
							r_small_clock = rc.clock
							r_small_idx = r_i
				else:
					if can_age and rc.hits > 0 and b.hit_clock - rc.age_clock >= DAG_MEMO_AGE_STEP:
						memo_age_entry(b, rc)
					var rc_score: int = (mini(maxi(0, rc.hits), 1048576) + 1) * mini(maxi(1, rc.work_nodes), 1048576)
					if rc_score < r_min_score or (rc_score == r_min_score and (rc.hits < r_min_hits or (rc.hits == r_min_hits and rc.clock < r_min_clock))):
						r_min_score = rc_score
						r_min_hits = rc.hits
						r_min_clock = rc.clock
						r_min_idx = r_i
		if r_cold_idx >= 0:
			r_victim = r_cold_idx
		elif cand_hits == 0:
			r_victim = r_small_idx
		elif r_min_idx >= 0 and (cand_hits >= 2 or cand_score > r_min_score or (r_min_hits == 0 and cand_score >= r_min_score)):
			r_victim = r_min_idx

	if r_victim >= 0:
		var evicted_r: DagMemoEntry = b.ring[r_victim] as DagMemoEntry
		memo_push_ghost(b, evicted_r.ref, evicted_r.height, evicted_r.hits, evicted_r.work_nodes)
		b.ring[r_victim] = ring_cand
		b.ring_refs[r_victim] = ring_cand.ref
	else:
		memo_push_ghost(b, ring_cand.ref, ring_cand.height, ring_cand.hits, ring_cand.work_nodes)


## 计算 Packed*Array 的估算字节开销；超出 max_allowed 时提前返回 -1。
static func packed_array_byte_cost(value: Variant, max_allowed: int = -1) -> int:
	var cost: int = -1
	match typeof(value):
		TYPE_PACKED_BYTE_ARRAY:
			cost = 16 + (value as PackedByteArray).size()
		TYPE_PACKED_INT32_ARRAY:
			cost = 16 + (value as PackedInt32Array).size() * 4
		TYPE_PACKED_FLOAT32_ARRAY:
			cost = 16 + (value as PackedFloat32Array).size() * 4
		TYPE_PACKED_INT64_ARRAY:
			cost = 16 + (value as PackedInt64Array).size() * 8
		TYPE_PACKED_FLOAT64_ARRAY:
			cost = 16 + (value as PackedFloat64Array).size() * 8
		TYPE_PACKED_VECTOR2_ARRAY:
			cost = 16 + (value as PackedVector2Array).size() * 16
		TYPE_PACKED_VECTOR3_ARRAY:
			cost = 16 + (value as PackedVector3Array).size() * 24
		TYPE_PACKED_VECTOR4_ARRAY:
			cost = 16 + (value as PackedVector4Array).size() * 32
		TYPE_PACKED_COLOR_ARRAY:
			cost = 16 + (value as PackedColorArray).size() * 32
		TYPE_PACKED_STRING_ARRAY:
			cost = 16
			if max_allowed >= 0 and cost > max_allowed:
				return -1
			for s: String in value as PackedStringArray:
				cost += 16 + s.length() * 4
				if max_allowed >= 0 and cost > max_allowed:
					return -1
		_:
			return -1
	if max_allowed >= 0 and cost > max_allowed:
		return -1
	return cost


## 有界深拷贝 Dictionary（超限或中止时返回空字典 {}）。
static func safe_clone_dict(
	raw: Dictionary,
	max_bytes: int = DEFAULT_MAX_CLONE_BYTES,
	max_depth: int = DEFAULT_MAX_DEPTH
) -> Dictionary:
	var cloned: Variant = safe_clone_variant(raw, 0, [], [], max_bytes, max_depth)
	return cloned as Dictionary if cloned is Dictionary else {}


## 按指定初始深度与字节预算校验并深拷贝 Dictionary，返回 {"ok": bool, "dict"?: Dictionary}。
static func safe_clone_validated_dict(
	raw: Dictionary,
	max_bytes: int = DEFAULT_MAX_CLONE_BYTES,
	initial_depth: int = 0,
	max_depth: int = DEFAULT_MAX_DEPTH
) -> Dictionary:
	var tctx := DagTravCtx.new()
	tctx.max_nodes = MAX_CLONE_VISITS + MAX_CLONE_SHARED_UNFOLD
	tctx.max_bytes = max_bytes
	tctx.max_depth = max_depth
	var cloned: Variant = safe_clone_node(raw, initial_depth, [], tctx)
	if tctx.aborted or not (cloned is Dictionary):
		return {"ok": false}
	return {"ok": true, "dict": cloned as Dictionary}


## 有界深拷贝任意 Variant；支持可选 visit_budget 数组与字节/深度上限。
static func safe_clone_variant(
	value: Variant,
	depth: int = 0,
	active_stack: Array = [],
	visit_budget: Array = [],
	max_bytes: int = DEFAULT_MAX_CLONE_BYTES,
	max_depth: int = DEFAULT_MAX_DEPTH
) -> Variant:
	var max_nodes: int = MAX_CLONE_VISITS
	if not visit_budget.is_empty():
		max_nodes = mini(MAX_CLONE_VISITS, maxi(0, int(visit_budget[0])))
	var tctx := DagTravCtx.new()
	tctx.max_nodes = max_nodes
	tctx.max_bytes = max_bytes
	tctx.max_depth = max_depth
	var cloned: Variant = safe_clone_node(value, depth, active_stack, tctx)
	if not visit_budget.is_empty():
		visit_budget[0] = maxi(0, max_nodes - tctx.nodes)
	if tctx.aborted:
		if value is Dictionary:
			return {}
		if value is Array:
			return []
		return null
	return cloned


## 递归执行单节点有界 DAG 深拷贝（带环截断、depth==max_depth 空容器折叠及防抖记忆化）。
static func safe_clone_node(value: Variant, depth: int, active_stack: Array, tctx: DagTravCtx) -> Variant:
	if tctx.aborted:
		if value is Dictionary:
			return {}
		if value is Array:
			return []
		return null
	tctx.nodes += 1
	if tctx.nodes > tctx.max_nodes:
		tctx.aborted = true
		if value is Dictionary:
			return {}
		if value is Array:
			return []
		return null
	if depth > tctx.max_depth:
		tctx.depth_clipped = true
		tctx.cycle_clipped = false
		tctx.last_height = 0
		tctx.last_bytes = 8
		tctx.last_logical_nodes = 1
		if value is Dictionary:
			return {}
		if value is Array:
			return []
		return null
	var vtype: int = typeof(value)
	if vtype == TYPE_DICTIONARY:
		var d: Dictionary = value as Dictionary
		if is_in_active_stack(d, active_stack):
			tctx.depth_clipped = false
			tctx.cycle_clipped = true
			tctx.last_height = 0
			tctx.last_bytes = 8
			tctx.last_logical_nodes = 1
			return null
		if depth == tctx.max_depth:
			tctx.depth_clipped = not d.is_empty()
			tctx.cycle_clipped = false
			tctx.bytes += 16
			if tctx.bytes > tctx.max_bytes:
				tctx.aborted = true
				return {}
			tctx.last_height = 0
			tctx.last_bytes = 16
			tctx.last_logical_nodes = 1
			return {}
		var allow_memo: bool = true
		var try_clipped_memo: bool = true
		var d_sz: int = d.size()
		if d_sz > 0:
			var m: DagMemoEntry = memo_find(tctx, true, d_sz, d)
			if m != null:
				var mh: int = m.height
				var mb: int = m.size
				var mln: int = m.logical_nodes
				if depth + mh <= tctx.max_depth:
					try_clipped_memo = false
					if tctx.bytes + mb > tctx.max_bytes or tctx.nodes + 1 > tctx.max_nodes:
						tctx.aborted = true
						return {}
					if mln <= MAX_CLONE_SHARED_SUBTREE and tctx.shared_unfold + mln <= MAX_CLONE_SHARED_UNFOLD:
						tctx.shared_unfold += mln
						allow_memo = false
					else:
						tctx.bytes += mb
						tctx.depth_clipped = false
						tctx.cycle_clipped = false
						tctx.last_height = mh
						tctx.last_bytes = mb
						tctx.last_logical_nodes = mln
						return m.cloned
				else:
					allow_memo = false
			if try_clipped_memo:
				var mc: DagMemoEntry = memo_find_in_buckets(tctx, tctx.clipped_dict_buckets, (d_sz << 6) | (depth & 0x3f), d)
				if mc != null:
					if tctx.bytes + mc.size > tctx.max_bytes or tctx.nodes + 1 > tctx.max_nodes:
						tctx.aborted = true
						return {}
					tctx.bytes += mc.size
					tctx.depth_clipped = true
					tctx.cycle_clipped = false
					tctx.last_height = mc.height
					tctx.last_bytes = mc.size
					tctx.last_logical_nodes = mc.logical_nodes
					return mc.cloned
		tctx.bytes += 16
		if tctx.bytes > tctx.max_bytes:
			tctx.aborted = true
			return {}
		var rem_d: int = tctx.max_bytes - tctx.bytes
		if d_sz > rem_d / 16:
			tctx.aborted = true
			return {}
		var start_nodes_d: int = tctx.nodes
		active_stack.append(d)
		tctx.frame_seq += 1
		var fid: int = tctx.frame_seq
		tctx.active_frames.append(fid)
		tctx.live_frames[fid] = true
		var out_d: Dictionary = {}
		var max_h: int = 0
		var total_b: int = 16
		var logical_nodes: int = 1
		var any_depth_clipped: bool = false
		var any_cycle: bool = false
		var d_keys: Array = d.keys()
		var d_vals: Array = []
		var has_d_vals: bool = false
		for k_idx: int in range(d_keys.size()):
			var k: Variant = d_keys[k_idx]
			var ck: Variant = k
			var kc: int = 0
			var scalar_k: bool = false
			if k is String:
				scalar_k = true
				kc = 16 + (k as String).length() * 4
				tctx.bytes += kc
				if tctx.bytes > tctx.max_bytes:
					tctx.aborted = true
					tctx.live_frames.erase(fid)
					tctx.active_frames.pop_back()
					active_stack.pop_back()
					return {}
				max_h = maxi(max_h, 1)
			elif k is StringName or k is int or k is float or k is bool or k is NodePath or k == null:
				scalar_k = true
				if k is NodePath:
					kc = 32 + str(k).length() * 8
				elif k is StringName:
					kc = 16 + str(k).length() * 4
				elif k == null:
					kc = 8
				else:
					kc = 16
				tctx.bytes += kc
				if tctx.bytes > tctx.max_bytes:
					tctx.aborted = true
					tctx.live_frames.erase(fid)
					tctx.active_frames.pop_back()
					active_stack.pop_back()
					return {}
				max_h = maxi(max_h, 1)
			else:
				tctx.depth_clipped = false
				tctx.cycle_clipped = false
				ck = safe_clone_node(k, depth + 1, active_stack, tctx)
				if tctx.aborted:
					tctx.live_frames.erase(fid)
					tctx.active_frames.pop_back()
					active_stack.pop_back()
					return {}
				any_depth_clipped = any_depth_clipped or tctx.depth_clipped
				any_cycle = any_cycle or tctx.cycle_clipped
				kc = tctx.last_bytes
				max_h = maxi(max_h, 1 + tctx.last_height)
				logical_nodes = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes + tctx.last_logical_nodes)
			var val_v: Variant
			if scalar_k:
				val_v = d[k]
			else:
				if not has_d_vals:
					d_vals = d.values()
					has_d_vals = true
				val_v = d_vals[k_idx]
			var vt: int = typeof(val_v)
			var cv: Variant
			var vc: int = 0
			if vt == TYPE_NIL or vt == TYPE_BOOL or vt == TYPE_INT or vt == TYPE_FLOAT or vt == TYPE_STRING or vt == TYPE_STRING_NAME or vt == TYPE_NODE_PATH:
				tctx.nodes += 1
				if tctx.nodes > tctx.max_nodes:
					tctx.aborted = true
					tctx.live_frames.erase(fid)
					tctx.active_frames.pop_back()
					active_stack.pop_back()
					return {}
				if vt == TYPE_NIL:
					vc = 8
				elif vt == TYPE_STRING:
					vc = 16 + (val_v as String).length() * 4
				elif vt == TYPE_STRING_NAME:
					vc = 16 + str(val_v).length() * 4
				elif vt == TYPE_NODE_PATH:
					vc = 32 + str(val_v).length() * 8
				else:
					vc = 16
				tctx.bytes += vc
				if tctx.bytes > tctx.max_bytes:
					tctx.aborted = true
					tctx.live_frames.erase(fid)
					tctx.active_frames.pop_back()
					active_stack.pop_back()
					return {}
				cv = val_v
				max_h = maxi(max_h, 1)
				logical_nodes = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes + 1)
			else:
				tctx.depth_clipped = false
				tctx.cycle_clipped = false
				cv = safe_clone_node(val_v, depth + 1, active_stack, tctx)
				if tctx.aborted:
					tctx.live_frames.erase(fid)
					tctx.active_frames.pop_back()
					active_stack.pop_back()
					return {}
				any_depth_clipped = any_depth_clipped or tctx.depth_clipped
				any_cycle = any_cycle or tctx.cycle_clipped
				vc = tctx.last_bytes
				max_h = maxi(max_h, 1 + tctx.last_height)
				logical_nodes = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes + tctx.last_logical_nodes)
			total_b += kc + vc
			out_d[ck] = cv
		tctx.live_frames.erase(fid)
		tctx.active_frames.pop_back()
		active_stack.pop_back()
		if not any_cycle:
			if any_depth_clipped:
				memo_store_in_buckets(tctx, tctx.clipped_dict_buckets, (d_sz << 6) | (depth & 0x3f), d, max_h, total_b, logical_nodes, out_d, maxi(1, tctx.nodes - start_nodes_d))
			elif allow_memo:
				memo_store(tctx, true, d_sz, d, max_h, total_b, logical_nodes, out_d, maxi(1, tctx.nodes - start_nodes_d))
		tctx.depth_clipped = any_depth_clipped
		tctx.cycle_clipped = any_cycle
		tctx.last_height = max_h
		tctx.last_bytes = total_b
		tctx.last_logical_nodes = logical_nodes
		return out_d
	if vtype == TYPE_ARRAY:
		var arr: Array = value as Array
		if is_in_active_stack(arr, active_stack):
			tctx.depth_clipped = false
			tctx.cycle_clipped = true
			tctx.last_height = 0
			tctx.last_bytes = 8
			tctx.last_logical_nodes = 1
			return null
		if depth == tctx.max_depth:
			tctx.depth_clipped = not arr.is_empty()
			tctx.cycle_clipped = false
			tctx.bytes += 16
			if tctx.bytes > tctx.max_bytes:
				tctx.aborted = true
				return []
			tctx.last_height = 0
			tctx.last_bytes = 16
			tctx.last_logical_nodes = 1
			return []
		var allow_memo_a: bool = true
		var try_clipped_memo_a: bool = true
		var a_sz: int = arr.size()
		if a_sz > 0:
			var ma: DagMemoEntry = memo_find(tctx, false, a_sz, arr)
			if ma != null:
				var mha: int = ma.height
				var mba: int = ma.size
				var mlna: int = ma.logical_nodes
				if depth + mha <= tctx.max_depth:
					try_clipped_memo_a = false
					if tctx.bytes + mba > tctx.max_bytes or tctx.nodes + 1 > tctx.max_nodes:
						tctx.aborted = true
						return []
					if mlna <= MAX_CLONE_SHARED_SUBTREE and tctx.shared_unfold + mlna <= MAX_CLONE_SHARED_UNFOLD:
						tctx.shared_unfold += mlna
						allow_memo_a = false
					else:
						tctx.bytes += mba
						tctx.depth_clipped = false
						tctx.cycle_clipped = false
						tctx.last_height = mha
						tctx.last_bytes = mba
						tctx.last_logical_nodes = mlna
						return ma.cloned
				else:
					allow_memo_a = false
			if try_clipped_memo_a:
				var mca: DagMemoEntry = memo_find_in_buckets(tctx, tctx.clipped_arr_buckets, (a_sz << 6) | (depth & 0x3f), arr)
				if mca != null:
					if tctx.bytes + mca.size > tctx.max_bytes or tctx.nodes + 1 > tctx.max_nodes:
						tctx.aborted = true
						return []
					tctx.bytes += mca.size
					tctx.depth_clipped = true
					tctx.cycle_clipped = false
					tctx.last_height = mca.height
					tctx.last_bytes = mca.size
					tctx.last_logical_nodes = mca.logical_nodes
					return mca.cloned
		tctx.bytes += 16
		if tctx.bytes > tctx.max_bytes:
			tctx.aborted = true
			return []
		var rem_a: int = tctx.max_bytes - tctx.bytes
		if a_sz > rem_a / 8:
			tctx.aborted = true
			return []
		var start_nodes_a: int = tctx.nodes
		active_stack.append(arr)
		tctx.frame_seq += 1
		var fid_a: int = tctx.frame_seq
		tctx.active_frames.append(fid_a)
		tctx.live_frames[fid_a] = true
		var out_a: Array = []
		out_a.resize(a_sz)
		var max_ha: int = 0
		var total_ba: int = 16
		var logical_nodes_a: int = 1
		var any_depth_clipped_a: bool = false
		var any_cycle_a: bool = false
		for idx: int in range(a_sz):
			var item: Variant = arr[idx]
			var it: int = typeof(item)
			if it == TYPE_NIL or it == TYPE_BOOL or it == TYPE_INT or it == TYPE_FLOAT or it == TYPE_STRING or it == TYPE_STRING_NAME or it == TYPE_NODE_PATH:
				tctx.nodes += 1
				if tctx.nodes > tctx.max_nodes:
					tctx.aborted = true
					tctx.live_frames.erase(fid_a)
					tctx.active_frames.pop_back()
					active_stack.pop_back()
					return []
				var ic_fast: int = 8
				if it == TYPE_STRING:
					ic_fast = 16 + (item as String).length() * 4
				elif it == TYPE_STRING_NAME:
					ic_fast = 16 + str(item).length() * 4
				elif it == TYPE_NODE_PATH:
					ic_fast = 32 + str(item).length() * 8
				elif it != TYPE_NIL:
					ic_fast = 16
				tctx.bytes += ic_fast
				if tctx.bytes > tctx.max_bytes:
					tctx.aborted = true
					tctx.live_frames.erase(fid_a)
					tctx.active_frames.pop_back()
					active_stack.pop_back()
					return []
				out_a[idx] = item
				total_ba += ic_fast
				max_ha = maxi(max_ha, 1)
				logical_nodes_a = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_a + 1)
			else:
				tctx.depth_clipped = false
				tctx.cycle_clipped = false
				var ci: Variant = safe_clone_node(item, depth + 1, active_stack, tctx)
				if tctx.aborted:
					tctx.live_frames.erase(fid_a)
					tctx.active_frames.pop_back()
					active_stack.pop_back()
					return []
				any_depth_clipped_a = any_depth_clipped_a or tctx.depth_clipped
				any_cycle_a = any_cycle_a or tctx.cycle_clipped
				out_a[idx] = ci
				total_ba += tctx.last_bytes
				max_ha = maxi(max_ha, 1 + tctx.last_height)
				logical_nodes_a = mini(MAX_DAG_LOGICAL_NODES_CLAMP, logical_nodes_a + tctx.last_logical_nodes)
		tctx.live_frames.erase(fid_a)
		tctx.active_frames.pop_back()
		active_stack.pop_back()
		if not any_cycle_a:
			if any_depth_clipped_a:
				memo_store_in_buckets(tctx, tctx.clipped_arr_buckets, (a_sz << 6) | (depth & 0x3f), arr, max_ha, total_ba, logical_nodes_a, out_a, maxi(1, tctx.nodes - start_nodes_a))
			elif allow_memo_a:
				memo_store(tctx, false, a_sz, arr, max_ha, total_ba, logical_nodes_a, out_a, maxi(1, tctx.nodes - start_nodes_a))
		tctx.depth_clipped = any_depth_clipped_a
		tctx.cycle_clipped = any_cycle_a
		tctx.last_height = max_ha
		tctx.last_bytes = total_ba
		tctx.last_logical_nodes = logical_nodes_a
		return out_a
	var packed_cost: int = packed_array_byte_cost(value, tctx.max_bytes - tctx.bytes)
	if packed_cost >= 0:
		tctx.bytes += packed_cost
		tctx.depth_clipped = false
		tctx.cycle_clipped = false
		tctx.last_height = 0
		tctx.last_bytes = packed_cost
		tctx.last_logical_nodes = 1
		return value.duplicate()
	if vtype >= TYPE_PACKED_BYTE_ARRAY:
		tctx.aborted = true
		return null
	var sc_cost: int = 8 if vtype == TYPE_NIL else ((16 + (value as String).length() * 4) if vtype == TYPE_STRING else ((32 + str(value).length() * 8) if vtype == TYPE_NODE_PATH else ((16 + str(value).length() * 4) if vtype == TYPE_STRING_NAME else 16)))
	tctx.bytes += sc_cost
	if tctx.bytes > tctx.max_bytes:
		tctx.aborted = true
		return null
	tctx.depth_clipped = false
	tctx.cycle_clipped = false
	tctx.last_height = 0
	tctx.last_bytes = sc_cost
	tctx.last_logical_nodes = 1
	return value
