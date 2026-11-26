"""Automated static hygiene and headless Godot tests for shared/sdk/fu_runtime/ (M1)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
import uuid

_TESTS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _TESTS_DIR.parent
_WORKSPACE_ROOT = _TOOLS_DIR.parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from fuvtt_devtools.env_config import load_config  # noqa: E402
from fuvtt_devtools.host_verifier import analyze_godot_logs  # noqa: E402

FU_SDK_DIR = _WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk"
FU_RUNTIME_DIR = _WORKSPACE_ROOT / "shared" / "sdk" / "fu_runtime"
SDK_AGENTS_MD = _WORKSPACE_ROOT / "shared" / "sdk" / "AGENTS.md"
TEST_TMP_ROOT = _WORKSPACE_ROOT / ".cache" / "test_tmp"

HARDCODED_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[/\\](?:Users|Program Files|Steam|DND|Projects|Work|home)[/\\]|/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/)"
)

FORBIDDEN_DAG_MEMO_SYMBOLS = (
    "_DagMemoEntry",
    "_DagMemoBucket",
    "_DagTravCtx",
)

FORBIDDEN_DUPLICATED_HELPERS = (
    "class _FallbackCloneCtx",
    "class _DndTravCtx",
    "func _parse_int_val(",
    "func _is_valid_uid(",
    "func _is_valid_hex24(",
    "func _is_valid_hex64(",
    "func _has_nul(",
    "func _strip_nul(",
    "func _strip_leading_bom(",
    "func _strip_control_and_edges(",
    "func _has_control_chars(",
    "func _has_control_except_tab(",
    "func _component_id_from_script(",
    "func _is_unit_host(",
    "func _to_bool(",
    "func _coerce_int(",
    "func _coerce_bool(",
    "func _coerce_float(",
    "func _coerce_str(",
    "func _coerce_color_array(",
    "func _clamp_color(",
    "func _is_unit_color(",
    "func _is_hex8_color(",
    "func _safe_clone_fog_overrides(",
)

EXPECTED_RUNTIME_SCRIPTS = (
    "v2.gd",
    "desktop_api_helper.gd",
    "hook_helper.gd",
    "slot_helper.gd",
    "comp_helper.gd",
    "network_helper.gd",
)

EXPECTED_SHARED_FU_SDK_SCRIPTS = (
    "utils/dag_cloner.gd",
    "utils/bounded_cloner.gd",
    "utils/value_utils.gd",
    "utils/validation_utils.gd",
    "logging/log_bus.gd",
    "plugins/module_registry.gd",
)


class TestFuRuntimeStaticHygiene(unittest.TestCase):
    """Pure-Python hygiene, manifest consistency, non-duplication, and fu_sdk 35-script guard."""

    def test_fu_sdk_remains_exact_35_scripts(self) -> None:
        gd_files = sorted(p.relative_to(FU_SDK_DIR).as_posix() for p in FU_SDK_DIR.rglob("*.gd"))
        self.assertEqual(len(gd_files), 35, f"shared/sdk/fu_sdk/ must remain at 35 .gd scripts, found {len(gd_files)}")

    def test_runtime_manifest_matches_disk_files(self) -> None:
        manifest_path = FU_RUNTIME_DIR / "runtime_manifest.json"
        self.assertTrue(manifest_path.is_file(), f"Missing {manifest_path}")
        raw = manifest_path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), "runtime_manifest.json must not have UTF-8 BOM")
        self.assertNotIn(b"\r", raw, "runtime_manifest.json must use LF-only line endings")
        data = json.loads(raw.decode("utf-8"))
        self.assertEqual(data.get("schema"), "fu_runtime.manifest.v1")
        self.assertEqual(data.get("sdk_version"), "2.0.0")
        self.assertEqual(data.get("runtime_dir"), "fu_runtime")
        self.assertEqual(data.get("fu_sdk_dir"), "fu_sdk")

        runtime_scripts = data.get("runtime_scripts", [])
        self.assertEqual(tuple(runtime_scripts), EXPECTED_RUNTIME_SCRIPTS)
        disk_gd = sorted(p.relative_to(FU_RUNTIME_DIR).as_posix() for p in FU_RUNTIME_DIR.rglob("*.gd"))
        self.assertEqual(sorted(runtime_scripts), disk_gd)

        shared_scripts = data.get("shared_fu_sdk_scripts", [])
        self.assertEqual(tuple(shared_scripts), EXPECTED_SHARED_FU_SDK_SCRIPTS)
        for rel in shared_scripts:
            self.assertTrue((FU_SDK_DIR / rel).is_file(), f"Manifest references missing fu_sdk script: {rel}")

    def test_runtime_scripts_hygiene_and_no_duplication(self) -> None:
        cfg = load_config(_WORKSPACE_ROOT)
        forbidden_locals: list[str] = []
        for candidate in (cfg.fuvtt_install_dir, cfg.fus_repo_dir, cfg.godot_bin):
            if candidate is not None:
                forbidden_locals.append(str(candidate))
                forbidden_locals.append(candidate.as_posix())

        for rel in EXPECTED_RUNTIME_SCRIPTS:
            fpath = FU_RUNTIME_DIR / rel
            self.assertTrue(fpath.is_file(), f"Missing runtime SDK script: {fpath}")
            raw = fpath.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"{rel} must not have UTF-8 BOM")
            self.assertNotIn(b"\r", raw, f"{rel} must use LF-only line endings")
            self.assertNotIn(b"\x00", raw, f"{rel} must not contain NUL bytes")
            text = raw.decode("utf-8")
            self.assertTrue(text.startswith("extends RefCounted\n"), f"{rel} must start with `extends RefCounted\\n`")
            self.assertNotIn("preload(", text, f"{rel} must not call preload()")
            self.assertIsNone(re.search(r"(?m)^\s*class_name\b", text), f"{rel} must not declare class_name")
            self.assertNotIn("\\u0000", text, f"{rel} must not contain literal \\u0000")
            self.assertIsNone(HARDCODED_PATH_RE.search(text), f"{rel} contains hardcoded machine-local path")
            for local_str in forbidden_locals:
                if local_str:
                    self.assertNotIn(local_str, text, f"{rel} leaks local environment path")
            for sym in FORBIDDEN_DAG_MEMO_SYMBOLS:
                self.assertNotIn(sym, text, f"{rel} must not duplicate {sym}")
            for helper_sig in FORBIDDEN_DUPLICATED_HELPERS:
                self.assertNotIn(helper_sig, text, f"{rel} must not duplicate {helper_sig}")
            if rel != "v2.gd":
                self.assertIn("weakref(", text, f"{rel} must use weakref() for parent/context back-references")
                self.assertIn("WeakRef", text, f"{rel} must type back-references as WeakRef")

    def test_sdk_agents_md_covers_both_fu_sdk_and_fu_runtime(self) -> None:
        self.assertTrue(SDK_AGENTS_MD.is_file())
        text = SDK_AGENTS_MD.read_text(encoding="utf-8")
        self.assertIn("fu_sdk", text)
        self.assertIn("fu_runtime", text)
        self.assertIn("35", text)
        self.assertIn("runtime_manifest.json", text)
        self.assertIn("WeakRef", text)


_PROBE_GD = r'''extends SceneTree

const _DIRECT_V2_PATH: String = "res://shared/sdk/fu_runtime/v2.gd"
const _BUNDLED_V2_PATH: String = "res://mods/demo_mod/lib/fu_runtime/v2.gd"


class _MockExtToken extends RefCounted:
	var _active: bool = true
	var _revert_cb: Callable = Callable()
	var last_rejection: String = ""
	var label: String = ""

	func _init(active: bool = true, revert_cb: Callable = Callable(), rej: String = "") -> void:
		_active = active
		_revert_cb = revert_cb
		last_rejection = rej
		if not rej.is_empty():
			label = "rejected:" + rej

	func is_active() -> bool:
		return _active

	func revert() -> void:
		if not _active:
			return
		_active = false
		if _revert_cb.is_valid():
			_revert_cb.call()


class _MockDesktopApi extends RefCounted:
	var gm: bool = true
	var role: String = "host"
	var peer: int = 1
	var player_id: String = "host"
	var scene_uid: String = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	var scene_name: String = "Tavern"
	var floor_uid: String = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
	var floor_id: int = 0
	var cell_size: float = 70.0
	var cam_pos: Vector2 = Vector2(100.0, 200.0)
	var cam_zoom: Vector2 = Vector2(1.5, 1.5)
	var mode: String = "select"
	var saved_entries: Dictionary = {
		"demo.mod": {"version": 1, "state": {"count": 3, "nested": {"flag": true}}}
	}
	var vitals_by_id: Dictionary = {
		"tok_1": {"ok": true, "source_kind": "monster", "name": "Goblin", "hp_cur": 7, "hp_max": 7, "shield": 0, "ac": 15, "hp_locked": false, "has_ac": true, "can_edit": true},
		"tok_masked": {"ok": true, "masked": true, "entity_id": "tok_masked", "name": "Dragon", "source_kind": "monster"},
	}

	func get_desktop() -> Node:
		return null

	func is_gm() -> bool:
		return gm

	func network_role() -> String:
		return role

	func local_peer_id() -> int:
		return peer

	func local_player_id() -> String:
		return player_id

	func joined_players() -> Array[Dictionary]:
		return [{"peer_id": 1, "name": "DM"}]

	func can_command_entity(_entity_or_id: Variant, _peer: int = 0) -> bool:
		return gm

	func active_scene_uid() -> String:
		return scene_uid

	func active_scene_name() -> String:
		return scene_name

	func active_floor_uid() -> String:
		return floor_uid

	func active_floor_id() -> int:
		return floor_id

	func world_units_per_cell() -> float:
		return cell_size

	func screen_to_world(screen_pos: Vector2) -> Vector2:
		return screen_pos + cam_pos

	func world_to_screen(world_pos: Vector2) -> Vector2:
		return world_pos - cam_pos

	func camera_position() -> Vector2:
		return cam_pos

	func camera_zoom() -> Vector2:
		return cam_zoom

	func focus_camera(world_pos: Vector2) -> bool:
		cam_pos = world_pos
		return true

	func focus_entity(entity_id: String) -> bool:
		return not entity_id.is_empty()

	func current_mode() -> String:
		return mode

	func set_mode(mode_id: String) -> bool:
		mode = mode_id
		return true

	var entities: Array = []

	func find_entity(entity_id: String) -> Object:
		if entity_id == "tok_1" and not entities.is_empty():
			return entities[0] as Object
		return null

	func get_entities(_active_floor_only: bool = true) -> Array:
		return entities.duplicate()

	func selected_entities() -> Array:
		return entities.duplicate()

	func read_entity_vitals(entity_or_id: Variant) -> Dictionary:
		var k: String = str(entity_or_id)
		return vitals_by_id.get(k, {"ok": false, "reason": "no_vitals_provider"})

	func request_roll(expression: String, label: String = "") -> Dictionary:
		return {"ok": true, "expr": expression, "label": label, "total": 14}

	func read_saved_module_entry(module_id: String) -> Dictionary:
		if not gm:
			return {}
		return (saved_entries.get(module_id, {}) as Dictionary).duplicate(true)


class _MockExtensionContext extends RefCounted:
	var active: bool = true
	var services: Dictionary = {}
	var hook_subs: Dictionary = {}
	var slots: Dictionary = {}
	var components: Array = []
	var tokens: Array = []
	var reject_next_slot: String = ""
	var inactive_next_hook: bool = false

	func is_active() -> bool:
		return active

	func can_initialize() -> bool:
		return active

	func consume_service(service_id: String) -> Object:
		if not active:
			return null
		return services.get(service_id, null) as Object

	func subscribe_hook(hook_id: StringName, callback: Callable, priority: int = 0) -> _MockExtToken:
		if inactive_next_hook:
			inactive_next_hook = false
			return _MockExtToken.new(false)
		if not hook_subs.has(hook_id):
			hook_subs[hook_id] = []
		var arr: Array = hook_subs[hook_id] as Array
		var entry: Dictionary = {"cb": callback, "priority": priority}
		arr.append(entry)
		var tok := _MockExtToken.new(true, func() -> void:
			arr.erase(entry)
		)
		tokens.append(tok)
		return tok

	func emit_hook(hook_id: StringName, arguments: Array = []) -> bool:
		if not active:
			return false
		var cancellable: bool = hook_id in [&"mode.pre_change", &"input.mouse_button", &"input.mouse_motion", &"input.key"]
		var subs: Array = hook_subs.get(hook_id, []) as Array
		for item: Variant in subs:
			var d := item as Dictionary
			var cb: Callable = d["cb"] as Callable
			var res: Variant = cb.callv(arguments)
			if cancellable and typeof(res) == TYPE_BOOL and res == false:
				return false
		return true

	func register_slot_item(slot_id: StringName, spec: Dictionary) -> _MockExtToken:
		if not reject_next_slot.is_empty():
			var rej := reject_next_slot
			reject_next_slot = ""
			var bad_tok := _MockExtToken.new(false, Callable(), rej)
			tokens.append(bad_tok)
			return bad_tok
		if not slots.has(slot_id):
			slots[slot_id] = []
		var copy_spec: Dictionary = spec.duplicate(true)
		(slots[slot_id] as Array).append(copy_spec)
		var tok := _MockExtToken.new(true, func() -> void:
			(slots[slot_id] as Array).erase(copy_spec)
		)
		tokens.append(tok)
		return tok

	func register_component(spec: Dictionary) -> _MockExtToken:
		var copy_spec: Dictionary = spec.duplicate(true)
		components.append(copy_spec)
		var tok := _MockExtToken.new(true, func() -> void:
			components.erase(copy_spec)
		)
		tokens.append(tok)
		return tok

	func mount_node(parent: Node, child: Node, index: int = -1) -> _MockExtToken:
		parent.add_child(child)
		if index >= 0 and index < parent.get_child_count():
			parent.move_child(child, index)
		var child_ref: WeakRef = weakref(child)
		var tok := _MockExtToken.new(true, func() -> void:
			var c: Variant = child_ref.get_ref()
			if c is Node and is_instance_valid(c):
				var cn := c as Node
				if cn.get_parent() != null:
					cn.get_parent().remove_child(cn)
				cn.queue_free()
		)
		tokens.append(tok)
		return tok

	func revert_all() -> void:
		var idx: int = tokens.size() - 1
		while idx >= 0:
			(tokens[idx] as _MockExtToken).revert()
			idx -= 1
		tokens.clear()


class _MockValidNetworkProvider extends RefCounted:
	signal projection_changed(peer: int)

	func network_action_valid(_payload: Variant) -> bool:
		return true

	func network_action_revoked(_peer: int, _payload: Dictionary) -> String:
		return ""

	func network_request(_peer: int, _payload: Dictionary) -> Dictionary:
		return {"ok": true, "history": 1}

	func network_projection(_peer: int, _confirmed: Dictionary, _reset: bool) -> Dictionary:
		return {"rev": 1}

	func network_cursor(_payload: Dictionary) -> Dictionary:
		return {"rev": 1}

	func network_revoked(_peer: int, _cursor: Dictionary) -> bool:
		return false

	func validate_replica_projection(_payload: Dictionary, _writer: Object) -> Dictionary:
		return {"ok": true}

	func capture_replica_projection() -> Dictionary:
		return {"rev": 0}

	func stage_replica_projection(_payload: Dictionary, _checked: Dictionary, _writer: Object) -> bool:
		return true

	func publish_replica_projection(_writer: Object) -> void:
		pass

	func restore_replica_projection(_previous: Dictionary, _writer: Object) -> bool:
		return true

	func presentation_current(_peer: int, _data: Dictionary) -> bool:
		return true

	func receive_presentation(_data: Dictionary, _sync: Object) -> bool:
		return true


class _MockInvalidNetworkProvider extends RefCounted:
	func network_action_valid(_payload: Variant) -> bool:
		return true


class _MockTokenNode extends Node:
	var comps: Dictionary = {}

	func get_component_by_id(comp_id: String) -> Object:
		return comps.get(comp_id, null) as Object


class _MockComp extends RefCounted:
	var ctx: _MockExtToken = _MockExtToken.new(true)


class _MockWorld extends RefCounted:
	var _rev: int = 4
	var content_notified: bool = false
	var published_rev: int = -1

	func notify_module_content_changed(_mod: Object) -> bool:
		content_notified = true
		return true

	func module_state_revision() -> int:
		return _rev

	func publish_module_state(rev: int) -> bool:
		published_rev = rev
		return true


var _failures: Array[String] = []


func _check(cond: bool, msg: String) -> void:
	if not cond:
		_failures.append(msg)


func _make_empty_control_pck_scene() -> PackedScene:
	var ctrl := Control.new()
	ctrl.name = "MockPanel"
	var ps := PackedScene.new()
	ps.pack(ctrl)
	ctrl.free()
	return ps


func _make_empty_comp_pck_scene() -> PackedScene:
	var n := Node.new()
	n.name = "MockComp"
	var ps := PackedScene.new()
	ps.pack(n)
	n.free()
	return ps


func _exercise_runtime(v2_path: String, tag: String) -> void:
	var v2_scr := load(v2_path) as Script
	_check(v2_scr != null, tag + ": failed to load v2.gd at " + v2_path)
	if v2_scr == null:
		return

	var rt: RefCounted = v2_scr.new()
	_check(rt.SDK_VERSION == "2.0.0", tag + ": SDK_VERSION mismatch")
	for util_name: String in ["dag_cloner", "bounded_cloner", "value_utils", "validation_utils"]:
		_check(rt.get_util_script(util_name) != null, tag + ": missing util " + util_name)
	_check(rt.get_util_script("nonexistent") == null, tag + ": unknown util should be null")

	# Shared logger + module registry from fu_sdk
	var logger: RefCounted = rt.create_logger({"max_entries": 16, "emit_to_engine": false})
	_check(logger != null, tag + ": create_logger failed")
	rt.set_logger(logger)
	var reg: RefCounted = rt.get_module_registry()
	_check(reg != null and reg.has_method(&"list_modules"), tag + ": get_module_registry failed")
	_check((reg.list_modules() as Array).size() >= 30, tag + ": module registry catalog incomplete")

	# Pass-through util checks
	_check(rt.coerce_int(2.0, -1) == 2, tag + ": coerce_int float->int failed")
	_check(rt.coerce_bool("true", false) == true, tag + ": coerce_bool failed")
	_check(rt.is_valid_uid("11111111111111111111111111111111"), tag + ": is_valid_uid failed")
	_check(rt.component_id_from_script("res://mods/demo/comp_demo__aura.gd") == "demo__aura", tag + ": component_id_from_script failed")

	# --- 1. desktop_api_helper ---
	var dapi_h: RefCounted = rt.create_desktop_api_helper()
	_check(not dapi_h.is_available(), tag + ": unbound desktop_api should be unavailable")
	_check(dapi_h.network_role() == "solo", tag + ": unbound network_role fallback")
	_check(dapi_h.local_peer_id() == 1, tag + ": unbound local_peer_id fallback")
	_check(dapi_h.world_units_per_cell() == 64.0, tag + ": unbound cell_size fallback")
	_check(not bool((dapi_h.read_entity_vitals("tok_1") as Dictionary).get("ok", true)), tag + ": unbound vitals should fail")
	_check((dapi_h.read_saved_module_entry("demo.mod") as Dictionary).is_empty(), tag + ": unbound saved entry should be empty")

	var mock_ctx := _MockExtensionContext.new()
	var mock_api := _MockDesktopApi.new()
	mock_ctx.services["desktop_api"] = mock_api
	_check(dapi_h.bind(mock_ctx), tag + ": bind via ExtensionContext failed")
	_check(dapi_h.is_available() and dapi_h.is_gm(), tag + ": bound desktop_api should report GM")
	_check(dapi_h.world_units_per_cell() == 70.0, tag + ": custom cell_size failed")
	_check(not dapi_h.focus_camera(Vector2(INF, 0.0)), tag + ": INF camera focus should be rejected")
	_check(dapi_h.focus_camera(Vector2(12.0, 34.0)) and mock_api.cam_pos == Vector2(12.0, 34.0), tag + ": valid camera focus failed")

	var v_unmasked: Dictionary = dapi_h.read_entity_vitals("tok_1")
	_check(bool(v_unmasked.get("ok", false)) and v_unmasked.get("masked", true) == false, tag + ": unmasked VitalsBridge normalization failed")
	var v_masked: Dictionary = dapi_h.read_entity_vitals("tok_masked")
	_check(dapi_h.is_vitals_masked(v_masked) and not v_masked.has("hp_cur"), tag + ": masked vitals failed")

	var saved_copy: Dictionary = dapi_h.read_saved_module_entry("demo.mod")
	_check(int((saved_copy.get("state", {}) as Dictionary).get("count", 0)) == 3, tag + ": read_saved_module_entry failed")
	(saved_copy["state"] as Dictionary)["count"] = 999
	_check(int(((mock_api.saved_entries["demo.mod"] as Dictionary)["state"] as Dictionary)["count"]) == 3, tag + ": read_saved_module_entry must isolate clone")

	var ent_node := _MockTokenNode.new()
	mock_api.entities = [ent_node]
	_check(dapi_h.find_entity("tok_1") == ent_node, tag + ": find_entity failed")
	_check(dapi_h.get_entities().size() == 1 and dapi_h.selected_entities().size() == 1, tag + ": get_entities/selected_entities failed")
	_check(dapi_h.can_command_entity("tok_1"), tag + ": GM can_command_entity failed")
	mock_api.gm = false
	_check(not dapi_h.can_command_entity("tok_1"), tag + ": non-GM can_command_entity must return false")
	_check((dapi_h.read_saved_module_entry("demo.mod") as Dictionary).is_empty(), tag + ": non-GM read_saved_module_entry must return {}")
	mock_api.entities.clear()
	ent_node.free()
	_check(not bool((dapi_h.request_roll("   ") as Dictionary).get("ok", true)), tag + ": empty roll expression must fail")
	_check(bool((dapi_h.request_roll("1d20+5", "Attack") as Dictionary).get("ok", false)), tag + ": valid roll failed")
	_check(dapi_h.network_role() == "host" and dapi_h.local_peer_id() == 1 and dapi_h.local_player_id() == "host", tag + ": role/peer/player_id failed")
	_check(dapi_h.joined_players().size() == 1, tag + ": joined_players failed")
	_check(dapi_h.active_scene_uid().length() == 32 and dapi_h.active_scene_name() == "Tavern", tag + ": active_scene failed")
	_check(dapi_h.active_floor_uid().length() == 32 and dapi_h.active_floor_id() == 0, tag + ": active_floor failed")
	_check(dapi_h.screen_to_world(Vector2(1.0, 2.0)) == Vector2(13.0, 36.0) and dapi_h.world_to_screen(Vector2(13.0, 36.0)) == Vector2(1.0, 2.0), tag + ": coord transforms failed")
	_check(dapi_h.camera_position() == Vector2(12.0, 34.0) and dapi_h.camera_zoom() == Vector2(1.5, 1.5), tag + ": camera getters failed")
	_check(dapi_h.focus_entity("tok_1") and dapi_h.set_mode("edit") and dapi_h.current_mode() == "edit", tag + ": focus_entity/mode failed")

	# --- 2. hook_helper ---
	var hook_h: RefCounted = rt.create_hook_helper(mock_ctx)
	_check(hook_h.BUILTIN_HOOKS.size() == 61, tag + ": BUILTIN_HOOKS must have 61 entries, got " + str(hook_h.BUILTIN_HOOKS.size()))
	_check(hook_h.is_cancellable(&"mode.pre_change") and hook_h.is_cancellable(&"input.key"), tag + ": cancellable hook check failed")
	_check(not hook_h.is_cancellable(&"dice.rolled"), tag + ": dice.rolled should not be cancellable")
	_check(hook_h.expected_arity(&"entity.property_changed") == 4, tag + ": entity.property_changed arity must be 4")
	_check(hook_h.is_custom_namespaced(&"mod.demo_mod.burst"), tag + ": valid custom hook rejected")
	_check(not hook_h.is_custom_namespaced(&"mod.bad"), tag + ": 2-segment custom hook must be rejected")
	_check(not hook_h.is_custom_namespaced(&"mod.BadCase.evt"), tag + ": uppercase custom hook must be rejected")
	_check(not hook_h.is_custom_namespaced(&"foo.demo.evt"), tag + ": non-ext/mod prefix must be rejected")
	var long_evt: String = "mod.demo." + "a".repeat(125)
	_check(not hook_h.is_custom_namespaced(StringName(long_evt)), tag + ": >128 char hook must be rejected")
	_check(hook_h.build_custom_hook_id("ext", "crit_vfx", "custom_burst") == &"ext.crit_vfx.custom_burst", tag + ": build_custom_hook_id failed")

	# Arity mismatch rejected (too few args on lambda, or extra required args on named method)
	var bad_sub: Variant = hook_h.subscribe(&"dice.rolled", func() -> void: pass)
	_check(bad_sub == null, tag + ": subscribe with too-few-arg lambda should fail")
	var bad_req_sub: Variant = hook_h.subscribe(&"dice.rolled", Callable(self, &"_probe_two_req"))
	_check(bad_req_sub == null, tag + ": subscribe with 2-required-arg named method for 1-arg hook should fail")

	# Optional default args accepted on both lambda and named method
	var opt_lambda_sub: Variant = hook_h.subscribe(&"dice.rolled", func(_a: Variant, _b: int = 7) -> void: pass)
	_check(opt_lambda_sub != null and (opt_lambda_sub as _MockExtToken).is_active(), tag + ": optional-default lambda should be accepted")
	var opt_method_sub: Variant = hook_h.subscribe(&"dice.rolled", Callable(self, &"_probe_opt_default"))
	_check(opt_method_sub != null and (opt_method_sub as _MockExtToken).is_active(), tag + ": optional-default named method should be accepted")

	# Inactive tokens from host must not be tracked
	var before_inactive_cnt: int = (hook_h._tokens as Array).size()
	mock_ctx.inactive_next_hook = true
	var inactive_sub: Variant = hook_h.subscribe(&"dice.rolled", func(_p: Dictionary) -> void: pass)
	_check(inactive_sub != null and not (inactive_sub as _MockExtToken).is_active(), tag + ": inactive token fixture check")
	_check((hook_h._tokens as Array).size() == before_inactive_cnt, tag + ": inactive token must not append to _tokens")

	# bind() to new context must revert previously tracked tokens cleanly
	var ctx_alt := _MockExtensionContext.new()
	hook_h.bind(ctx_alt)
	_check(not (opt_lambda_sub as _MockExtToken).is_active() and not (opt_method_sub as _MockExtToken).is_active(), tag + ": bind() must revert prior context tokens")
	_check((hook_h._tokens as Array).size() == 0, tag + ": _tokens after bind() revert must be empty")
	hook_h.bind(mock_ctx)

	var received_payload: Array = []
	var good_sub: Variant = hook_h.subscribe(&"mod.demo_mod.burst", func(payload: Dictionary) -> void:
		received_payload.append(payload)
	)
	_check(good_sub != null and (good_sub as _MockExtToken).is_active(), tag + ": valid custom subscribe failed")
	var emit_res: Dictionary = hook_h.emit_custom(&"mod.demo_mod.burst", {"dmg": 18})
	_check(bool(emit_res.get("ok", false)) and bool(emit_res.get("emitted", false)) and received_payload.size() == 1, tag + ": emit_custom failed")

	var cyc_dict: Dictionary = {}
	cyc_dict["self"] = cyc_dict
	var cyc_emit: Dictionary = hook_h.emit_custom(&"mod.demo_mod.burst", cyc_dict)
	_check(not bool(cyc_emit.get("ok", true)), tag + ": cyclic payload in custom hook must be rejected")

	# Cancellable built-in hook vs non-cancellable custom hook
	hook_h.subscribe(&"mode.pre_change", func(_old_m: String, _new_m: String) -> bool: return false)
	var cancel_res: Dictionary = hook_h.emit(&"mode.pre_change", ["select", "edit"])
	_check(bool(cancel_res.get("ok", false)) and not bool(cancel_res.get("emitted", true)), tag + ": cancellable hook returning false must cancel")
	hook_h.subscribe(&"mod.demo_mod.nocancel", func(_p: Dictionary) -> bool: return false)
	var nocancel_res: Dictionary = hook_h.emit_custom(&"mod.demo_mod.nocancel", {"x": 1})
	_check(bool(nocancel_res.get("ok", false)) and bool(nocancel_res.get("emitted", false)), tag + ": custom hook returning false must NOT cancel")

	hook_h.revert_tracked()
	_check(not (good_sub as _MockExtToken).is_active(), tag + ": revert_tracked failed")

	# --- 3. slot_helper ---
	var slot_h: RefCounted = rt.create_slot_helper(mock_ctx)
	var overlay_bad: Dictionary = slot_h.make_world_overlay_spec("ov", "invalid_band", {"factory": func() -> Node2D: return Node2D.new()})
	_check(not bool(overlay_bad.get("ok", true)), tag + ": invalid overlay band must fail")
	var overlay_node := Node2D.new()
	var ov_reg: Dictionary = slot_h.register_world_overlay("demo.overlay", "above_fog", {"node": overlay_node, "priority": 5})
	_check(bool(ov_reg.get("ok", false)), tag + ": register_world_overlay failed")

	var panel_ps: PackedScene = _make_empty_control_pck_scene()
	var panel_reg: Dictionary = slot_h.register_desktop_panel("demo.panel", "Demo Panel", panel_ps, mock_api, {"priority": 20})
	_check(bool(panel_reg.get("ok", false)), tag + ": register_desktop_panel failed")
	var settings_reg: Dictionary = slot_h.register_module_settings("demo.settings", "Demo Settings", panel_ps, mock_api)
	_check(bool(settings_reg.get("ok", false)), tag + ": register_module_settings failed")

	var mode_bad: Dictionary = slot_h.make_mode_bar_spec("select", "Select", func(_d: Node) -> bool: return true, func(_d: Node) -> void: pass, func(_d: Node) -> bool: return true)
	_check(not bool(mode_bad.get("ok", true)), tag + ": builtin mode id must be rejected")
	var mode_nodot: Dictionary = slot_h.make_mode_bar_spec("mymode", "MyMode", func(_d: Node) -> bool: return true, func(_d: Node) -> void: pass, func(_d: Node) -> bool: return true)
	_check(not bool(mode_nodot.get("ok", true)), tag + ": mode id without dot must be rejected")
	var mode_ok: Dictionary = slot_h.register_mode_bar("demo.inspect", "Inspect", func(_d: Node) -> bool: return slot_h.safe_mode_enter_result(true), func(_d: Node) -> void: pass, func(_d: Node) -> bool: return true)
	_check(bool(mode_ok.get("ok", false)), tag + ": valid mode_bar registration failed")
	var null_enter: Variant = null
	_check(slot_h.safe_mode_enter_result(null_enter) == false, tag + ": safe_mode_enter_result(null Variant) must return false")
	_check(slot_h.safe_mode_enter_result(false) == false, tag + ": safe_mode_enter_result(false) must return false")
	_check(slot_h.safe_mode_enter_result("true") == false, tag + ": safe_mode_enter_result(non-bool) must return false")
	var mode_bad_sf: Dictionary = slot_h.make_mode_bar_spec("demo.bad_sf", "BadSF", func(_d: Node) -> bool: return true, func(_d: Node) -> void: pass, func(_d: Node) -> bool: return true, {"selection_filter": "not_callable"})
	_check(not bool(mode_bad_sf.get("ok", true)) and mode_bad_sf.get("reason") == "invalid_selection_filter", tag + ": non-Callable selection_filter must be rejected")
	var mode_bad_pb: Dictionary = slot_h.make_mode_bar_spec("demo.bad_pb", "BadPB", func(_d: Node) -> bool: return true, func(_d: Node) -> void: pass, func(_d: Node) -> bool: return true, {"pick_boundary": 123})
	_check(not bool(mode_bad_pb.get("ok", true)) and mode_bad_pb.get("reason") == "invalid_pick_boundary", tag + ": non-Callable pick_boundary must be rejected")
	var ov_bad_fac: Dictionary = slot_h.make_world_overlay_spec("demo.bad_fac", "above_entities", {"scene": panel_ps, "factory": "not_callable"})
	_check(not bool(ov_bad_fac.get("ok", true)) and ov_bad_fac.get("reason") == "invalid_overlay_factory", tag + ": non-Callable overlay factory must be rejected")

	var act_default: Dictionary = slot_h.make_entity_action_spec("demo.act", "Act", func(_d: Node, _t: Array) -> bool: return true, func(_d: Node, _t: Array) -> bool: return true)
	_check(bool(act_default.get("ok", false)) and bool((act_default["spec"] as Dictionary).get("dm_only", false)) == true, tag + ": entity_action dm_only must default to true")
	var act_bad_pres: Dictionary = slot_h.make_entity_action_spec("demo.act", "Act", func(_d: Node, _t: Array) -> bool: return true, func(_d: Node, _t: Array) -> bool: return true, {"presentation": "not_callable"})
	_check(not bool(act_bad_pres.get("ok", true)) and act_bad_pres.get("reason") == "invalid_presentation_callback", tag + ": non-Callable presentation must be rejected")
	var act_bad_tm: Dictionary = slot_h.make_entity_action_spec("demo.act", "Act", func(_d: Node, _t: Array) -> bool: return true, func(_d: Node, _t: Array) -> bool: return true, {"target_matches": 42})
	_check(not bool(act_bad_tm.get("ok", true)) and act_bad_tm.get("reason") == "invalid_target_matches_callback", tag + ": non-Callable target_matches must be rejected")
	var act_bad_wheel: Dictionary = slot_h.make_entity_action_spec("demo.act", "Act", func(_d: Node, _t: Array) -> bool: return true, func(_d: Node, _t: Array) -> bool: return true, {"wheel_ring": 32})
	_check(not bool(act_bad_wheel.get("ok", true)), tag + ": wheel_ring > 31 must be rejected")
	var act_ok: Dictionary = slot_h.register_entity_action("demo.act", "Act", func(_d: Node, _t: Array) -> bool: return true, func(_d: Node, _t: Array) -> bool: return true, {"shortcut_key": KEY_A})
	_check(bool(act_ok.get("ok", false)), tag + ": register_entity_action failed")
	var canvas_ok: Dictionary = slot_h.register_canvas_action("demo.canvas_act", "Canvas", func(_d: Node, _c: Dictionary) -> bool: return true, func(_d: Node, _c: Dictionary) -> bool: return true)
	_check(bool(canvas_ok.get("ok", false)), tag + ": register_canvas_action failed")
	var prop_ok: Dictionary = slot_h.register_entity_properties("demo.props", panel_ps, mock_api)
	_check(bool(prop_ok.get("ok", false)), tag + ": register_entity_properties failed")
	mock_ctx.reject_next_slot = "duplicate_slot_id:demo.act"
	var rej_act: Dictionary = slot_h.register_entity_action("demo.act", "Act", func(_d: Node, _t: Array) -> bool: return true, func(_d: Node, _t: Array) -> bool: return true)
	_check(not bool(rej_act.get("ok", true)) and rej_act.get("reason") == "duplicate_slot_id:demo.act", tag + ": rejected slot must surface reason")
	var plain_node := Node.new()
	_check(not bool((slot_h.validate_panel_node(plain_node) as Dictionary).get("ok", true)), tag + ": non-Control panel root must fail validate_panel_node")
	plain_node.free()

	# mount_node lifecycle
	var parent_n := Node.new()
	var child_n := Node.new()
	var m_ok: Dictionary = slot_h.mount_node(parent_n, child_n)
	_check(bool(m_ok.get("ok", false)) and child_n.get_parent() == parent_n, tag + ": mount_node failed")
	var m_dup: Dictionary = slot_h.mount_node(parent_n, child_n)
	_check(not bool(m_dup.get("ok", true)) and m_dup.get("reason") == "child_already_parented", tag + ": already-parented child must be rejected")
	(m_ok["token"] as _MockExtToken).revert()
	_check(child_n.get_parent() == null, tag + ": mount_node revert must detach child")
	parent_n.free()
	# Cleanup overlay_node detached via revert_all later
	mock_ctx.revert_all()
	overlay_node.free()

	# --- 4. comp_helper ---
	var comp_h: RefCounted = rt.create_comp_helper(mock_ctx)
	var ns_id: String = comp_h.make_namespaced_comp_id("aura_rings", "emitter")
	_check(ns_id == "aura_rings__emitter", tag + ": make_namespaced_comp_id failed")
	_check(comp_h.is_valid_component_script_path("res://external_modules/aura_rings/comp_aura_rings__emitter.gd", ns_id), tag + ": valid comp path failed")
	_check(not comp_h.is_valid_component_script_path("res://external_modules/aura_rings/../evil.gd", ns_id), tag + ": .. path traversal must be rejected")
	_check(not comp_h.is_valid_component_script_path("res://external_modules/aura_rings\\\\comp_aura_rings__emitter.gd", ns_id), tag + ": backslash in comp path must be rejected")
	_check(not comp_h.is_valid_component_script_path("res://external_modules/aura_rings/./comp_aura_rings__emitter.gd", ns_id), tag + ": dot segment in comp path must be rejected")
	_check(not comp_h.is_valid_component_script_path("res://external_modules/aura_rings//comp_aura_rings__emitter.gd", ns_id), tag + ": empty segment in comp path must be rejected")
	_check(not comp_h.is_valid_component_script_path("res://mods/x/comp_visual.gd"), tag + ": required component visual must be forbidden")

	var comp_ps: PackedScene = _make_empty_comp_pck_scene()
	var bad_comp_scope: Dictionary = comp_h.make_component_spec(ns_id, "res://mods/a/comp_aura_rings__emitter.gd", comp_ps, {"network_scope": "shared", "entity_local_content": true})
	_check(not bool(bad_comp_scope.get("ok", true)), tag + ": entity_local_content without peer scope must fail")
	var bad_comp_rows: Dictionary = comp_h.make_component_spec(ns_id, "res://mods/a/comp_aura_rings__emitter.gd", comp_ps, {"network_scope": "peer", "entity_local_content": false, "recipient_component_rows": true})
	_check(not bool(bad_comp_rows.get("ok", true)), tag + ": recipient_component_rows without entity_local_content must fail")
	var ok_comp_reg: Dictionary = comp_h.register_component(ns_id, "res://mods/a/comp_aura_rings__emitter.gd", comp_ps, {"network_scope": "shared"})
	_check(bool(ok_comp_reg.get("ok", false)), tag + ": valid register_component failed")
	var bad_comp_pw: Dictionary = comp_h.make_component_spec(ns_id, "res://mods/a/comp_aura_rings__emitter.gd", comp_ps, {"prepare_world": "not_callable"})
	_check(not bool(bad_comp_pw.get("ok", true)) and bad_comp_pw.get("reason") == "invalid_prepare_world_callable", tag + ": non-Callable prepare_world must be rejected")
	var bad_comp_awd: Dictionary = comp_h.make_component_spec(ns_id, "res://mods/a/comp_aura_rings__emitter.gd", comp_ps, {"accepts_world_delta": 99})
	_check(not bool(bad_comp_awd.get("ok", true)) and bad_comp_awd.get("reason") == "invalid_accepts_world_delta_callable", tag + ": non-Callable accepts_world_delta must be rejected")

	# StateValue.is_data boundaries
	_check(comp_h.is_pure_data({"a": 1, "b": [Vector2(1, 2), Color(0.1, 0.2, 0.3, 1.0)], "c": PackedFloat32Array([1.0, 2.0])}), tag + ": valid pure data rejected")
	var temp_n := Node.new()
	_check(not comp_h.is_pure_data({"obj": temp_n}), tag + ": Object in pure data must be rejected")
	_check(not comp_h.is_pure_data(temp_n), tag + ": Node must fail is_pure_data")
	temp_n.free()
	_check(not comp_h.is_pure_data(func() -> void: pass), tag + ": Callable must fail is_pure_data")
	_check(not comp_h.is_pure_data({"nan": NAN}), tag + ": NAN must fail is_pure_data")
	_check(not comp_h.is_pure_data({"v": Vector2(INF, 0.0)}), tag + ": INF Vector2 must fail is_pure_data")
	_check(not comp_h.is_pure_data({"c": Color(NAN, 0.0, 0.0, 1.0)}), tag + ": NAN Color must fail is_pure_data")
	_check(not comp_h.is_pure_data(cyc_dict), tag + ": cyclic dict must fail is_pure_data")
	_check(not comp_h.is_pure_data(cyc_dict, 1), tag + ": cyclic dict at depth 1 must fail is_pure_data")
	_check(comp_h.is_pure_data({}, 32), tag + ": empty dict at depth 32 should be valid")
	_check(not comp_h.is_pure_data({"k": 1}, 32), tag + ": non-empty dict at depth 32 must fail")
	_check(comp_h.is_pure_data({"k": {}}, 31), tag + ": nested empty dict at depth 31->32 should be valid")
	_check(not comp_h.is_pure_data({"k": {"x": 1}}, 31), tag + ": depth 33 nested dict must fail")
	_check(comp_h.is_pure_data(Transform3D.IDENTITY, 31), tag + ": Transform3D at depth 31 should be valid")
	_check(not comp_h.is_pure_data(Transform3D.IDENTITY, 32), tag + ": Transform3D at depth 32 must fail")
	_check(comp_h.is_pure_data({"t": Transform3D.IDENTITY}, 30), tag + ": Transform3D inside dict at depth 30->31 should be valid")
	_check(not comp_h.is_pure_data({"t": Transform3D.IDENTITY}, 31), tag + ": Transform3D inside dict at depth 31->32 must fail")
	_check(comp_h.is_pure_data(PackedFloat32Array([1.0]), 31), tag + ": non-empty PackedFloat32Array at depth 31 should be valid")
	_check(comp_h.is_pure_data(PackedFloat32Array(), 32), tag + ": empty PackedFloat32Array at depth 32 should be valid")
	_check(not comp_h.is_pure_data(PackedFloat32Array([1.0]), 32), tag + ": non-empty PackedFloat32Array at depth 32 must fail")

	# O(n) diamond DAG memoization & height boundary in is_pure_data
	var dag_node: Dictionary = {"a": 1, "b": 2}
	for _dag_i: int in range(19):
		dag_node = {"a": dag_node, "b": dag_node}
	var dag_t0: int = Time.get_ticks_usec()
	var dag_ok: bool = comp_h.is_pure_data(dag_node)
	var dag_elapsed_ms: float = float(Time.get_ticks_usec() - dag_t0) / 1000.0
	_check(dag_ok, tag + ": depth-20 binary diamond DAG should pass is_pure_data")
	_check(dag_elapsed_ms < 100.0, tag + ": depth-20 binary diamond DAG took too long: " + str(dag_elapsed_ms) + "ms")
	_check(comp_h.is_pure_data(dag_node, 12), tag + ": depth-20 DAG at depth 12 (12+20=32) should pass")
	_check(not comp_h.is_pure_data(dag_node, 13), tag + ": depth-20 DAG at depth 13 (13+20=33) must fail")

	# Build a 33-level deep Dictionary (0..32 with leaf at depth 33)
	var deep_32: Dictionary = {"leaf": 1}
	for _d_idx: int in range(31):
		deep_32 = {"next": deep_32}

	# public_state
	var pub_gm: Dictionary = comp_h.build_public_state({"dm_secret": true, "radius": 2}, 1, {"radius": 1})
	_check(int(pub_gm.get("radius", 0)) == 2, tag + ": peer 1 should receive secret state")
	var pub_p0_denied: Dictionary = comp_h.build_public_state({"dm_secret": true, "radius": 2}, 0, {"radius": 1})
	_check(pub_p0_denied.is_empty(), tag + ": peer 0 without permission_check must return {} for dm_secret")
	var pub_pneg_denied: Dictionary = comp_h.build_public_state({"dm_secret": true, "radius": 2}, -1, {"radius": 1})
	_check(pub_pneg_denied.is_empty(), tag + ": peer -1 without permission_check must return {} for dm_secret")
	var pub_p0_default_denied: Dictionary = comp_h.build_public_state({"radius": 2}, 0, {"dm_secret": true, "radius": 1})
	_check(pub_p0_default_denied.is_empty(), tag + ": peer 0 inheriting dm_secret=true from defaults must return {}")
	var pub_p0_allowed: Dictionary = comp_h.build_public_state({"dm_secret": true, "radius": 2}, 0, {"radius": 1}, func(_p: int) -> bool: return true)
	_check(int(pub_p0_allowed.get("radius", 0)) == 2, tag + ": peer 0 with permission_check returning true should receive secret state")
	var pub_p2_denied: Dictionary = comp_h.build_public_state({"dm_secret": true, "radius": 2}, 2, {"radius": 1}, func(_p: int) -> bool: return false)
	_check(pub_p2_denied.is_empty(), tag + ": non-commanding peer should receive {} for dm_secret")
	var pub_p2_allowed: Dictionary = comp_h.build_public_state({"dm_secret": true, "radius": 2}, 2, {"radius": 1}, func(_p: int) -> bool: return true)
	_check(int(pub_p2_allowed.get("radius", 0)) == 2, tag + ": commanding peer should receive secret state")
	var pub_def_secret_denied: Dictionary = comp_h.build_public_state({}, 2, {"dm_secret": true, "radius": 5})
	_check(pub_def_secret_denied.is_empty(), tag + ": sparse state inheriting dm_secret=true from defaults must return {} for peer > 1")
	var pub_def_secret_override: Dictionary = comp_h.build_public_state({"dm_secret": false}, 2, {"dm_secret": true, "radius": 5})
	_check(int(pub_def_secret_override.get("radius", 0)) == 5, tag + ": explicit dm_secret=false must override default secret")
	var pub_def_secret_allowed: Dictionary = comp_h.build_public_state({}, 2, {"dm_secret": true, "radius": 5}, func(_p: int) -> bool: return true)
	_check(int(pub_def_secret_allowed.get("radius", 0)) == 5, tag + ": commanding peer should receive default dm_secret state")
	_check(comp_h.build_public_state({"dm_secret": false, "r": 2, "cyc": cyc_dict}, 2, {"r": 1}).is_empty(), tag + ": cyclic state in build_public_state must return {}")
	_check(comp_h.build_public_state({"dm_secret": false, "deep": deep_32}, 2, {"r": 1}).is_empty(), tag + ": depth-33 state in build_public_state must return {}")
	_check(comp_h.build_public_state({"dm_secret": false, "r": 2}, 2, {"cyc": cyc_dict}).is_empty(), tag + ": cyclic defaults in build_public_state must return {}")
	var oversized_pub := PackedByteArray()
	oversized_pub.resize(16 * 1024 * 1024 + 64)
	_check(comp_h.build_public_state({"dm_secret": false, "blob": oversized_pub}, 2, {"r": 1}).is_empty(), tag + ": >16MiB state in build_public_state must return {}")
	_check(comp_h.build_public_state({"dm_secret": false, "r": 2}, 2, {"r": 1}, Callable(), "dm_secret", func(_m: Dictionary, _p: int) -> Dictionary: return {"cyc": cyc_dict}).is_empty(), tag + ": cyclic sanitizer output in build_public_state must return {}")

	# dominance & suppression & conflict
	_check(comp_h.does_suppress("dom", PackedStringArray(["*"]), PackedStringArray(["tag:immune"]), "other", PackedStringArray([])), tag + ": wildcard suppression failed")
	_check(not comp_h.does_suppress("dom", PackedStringArray(["*"]), PackedStringArray(["tag:immune"]), "other", PackedStringArray(["immune"])), tag + ": allowlist exemption failed")
	_check(not comp_h.does_suppress("dom", PackedStringArray(["*"]), PackedStringArray(), "visual", PackedStringArray()), tag + ": required component visual must not be suppressed")
	_check(not comp_h.does_suppress("dom", PackedStringArray(["*"]), PackedStringArray(), "permission", PackedStringArray()), tag + ": required component permission must not be suppressed")
	_check(comp_h.has_symmetric_conflict({"id": "a", "exclusive_group": "g1"}, {"id": "b", "exclusive_group": "g1"}), tag + ": exclusive_group conflict failed")

	# undo payload builders
	var tok_node := _MockTokenNode.new()
	tok_node.comps[ns_id] = _MockComp.new()
	get_root().add_child(tok_node)
	var collected: Array = comp_h.collect_active_components([tok_node], ns_id)
	_check(collected.size() == 1, tag + ": collect_active_components failed")
	var f_payload: Dictionary = comp_h.make_field_edit_payload([tok_node], collected, "radius_cells", [2], 4)
	_check(f_payload.get("field") == "radius_cells" and int(f_payload.get("value", 0)) == 4, tag + ": make_field_edit_payload failed")
	var n_resp: Dictionary = {}
	var n_payload: Dictionary = comp_h.make_numeric_edit_payload([tok_node], collected, "radius_cells", [2], &"begin", tok_node, 7, [3], n_resp)
	_check(n_payload.get("phase") == &"begin" and int(n_payload.get("token", 0)) == 7, tag + ": make_numeric_edit_payload failed")
	get_root().remove_child(tok_node)
	tok_node.free()

	# --- 5. network_helper ---
	var net_local: RefCounted = rt.create_network_helper("demo.local_mod", true, mock_ctx)
	var valid_prov := _MockValidNetworkProvider.new()
	valid_prov.set_meta(&"module_id", "demo.local_mod")
	var blocked_act: Dictionary = net_local.register_network_actions(valid_prov)
	_check(not bool(blocked_act.get("ok", true)) and blocked_act.get("reason") == "local_only_network_disabled", tag + ": local_only must block network.actions")
	var blocked_proj: Dictionary = net_local.register_network_projections(valid_prov)
	_check(not bool(blocked_proj.get("ok", true)) and blocked_proj.get("reason") == "local_only_network_disabled", tag + ": local_only must block network.projections")

	var net_v2: RefCounted = rt.create_network_helper("demo.world_mod", false, mock_ctx)
	_check(net_v2.is_valid_module_id("demo.world_mod"), tag + ": valid module id rejected")
	_check(not net_v2.is_valid_module_id("Demo.World"), tag + ": uppercase module id must be rejected")
	_check(not net_v2.is_valid_module_id("1demo"), tag + ": leading-digit module id must be rejected")

	valid_prov.set_meta(&"module_id", "demo.world_mod")
	var mismatch_act: Dictionary = net_v2.register_network_actions(valid_prov, "demo.other")
	_check(not bool(mismatch_act.get("ok", true)) and mismatch_act.get("reason") == "module_id_mismatch", tag + ": mismatched spec.id must be rejected")

	var invalid_prov := _MockInvalidNetworkProvider.new()
	var bad_prov_act: Dictionary = net_v2.register_network_actions(invalid_prov)
	_check(not bool(bad_prov_act.get("ok", true)) and (bad_prov_act.get("missing_methods", []) as Array).size() == 2, tag + ": invalid action provider must fail")

	var ok_act: Dictionary = net_v2.register_network_actions(valid_prov)
	_check(bool(ok_act.get("ok", false)), tag + ": valid network.actions failed")
	var bad_rep_proj: Dictionary = net_v2.register_network_projections(valid_prov, "", {"replica_presentation_only": false})
	_check(not bool(bad_rep_proj.get("ok", true)), tag + ": replica_presentation_only=false must fail")
	var ok_proj: Dictionary = net_v2.register_network_projections(valid_prov)
	_check(bool(ok_proj.get("ok", false)), tag + ": valid network.projections failed")
	var ok_pres: Dictionary = net_v2.register_network_presentations(valid_prov)
	_check(bool(ok_pres.get("ok", false)), tag + ": valid network.presentations failed")

	# WorldModuleState 3-phase & quotas
	var entry_ok: Dictionary = net_v2.prepare_entry("demo.world_mod", 2.0, {"cells": 5, "arr": PackedInt32Array([1, 2, 3])})
	_check(bool(entry_ok.get("ok", false)) and typeof((entry_ok["entry"] as Dictionary)["version"]) == TYPE_INT, tag + ": prepare_entry float->int normalization failed")
	var entry_cyc: Dictionary = net_v2.prepare_entry("demo.world_mod", 1, cyc_dict)
	_check(not bool(entry_cyc.get("ok", true)), tag + ": cyclic prepare_entry must fail")
	var entry_big: Dictionary = net_v2.prepare_entry("demo.world_mod", 1, {"blob": PackedByteArray([0, 1])})
	_check(bool(entry_big.get("ok", false)), tag + ": small PackedByteArray prepare_entry failed")
	var oversized_bytes := PackedByteArray()
	oversized_bytes.resize(16 * 1024 * 1024 + 64)
	var entry_oversized: Dictionary = net_v2.prepare_entry("demo.world_mod", 1, {"blob": oversized_bytes})
	_check(not bool(entry_oversized.get("ok", true)) and entry_oversized.get("reason") == "module_entry_size_limit", tag + ": >16MiB entry must be rejected")
	_check(net_v2.estimate_bounded_bytes(cyc_dict) == -1, tag + ": estimate_bounded_bytes must reject cycle")
	_check(net_v2.estimate_bounded_bytes(cyc_dict, net_v2.MAX_ENTRY_BYTES, 1) == -1, tag + ": estimate_bounded_bytes at depth 1 must reject cycle")
	_check(net_v2.estimate_bounded_bytes(PackedStringArray(["hello"]), net_v2.MAX_ENTRY_BYTES, 32) == -1, tag + ": non-empty PackedStringArray at depth 32 must return -1")
	_check(net_v2.estimate_bounded_bytes(PackedStringArray(), net_v2.MAX_ENTRY_BYTES, 32) >= 0, tag + ": empty PackedStringArray at depth 32 should be valid")
	_check(net_v2.estimate_bounded_bytes(PackedStringArray(["hello"]), net_v2.MAX_ENTRY_BYTES, 31) >= 0, tag + ": non-empty PackedStringArray at depth 31 should be valid")

	var three_empty: Dictionary = net_v2.prepare_three_phase_state({}, 2, Callable(), {"cell_feet": 5})
	_check(bool(three_empty.get("ok", false)) and int((three_empty["data"] as Dictionary).get("version", 0)) == 2, tag + ": 3-phase empty defaults failed")
	var three_val_cb := func(d: Dictionary) -> Dictionary:
		if int(d.get("cell_feet", 0)) < 1:
			return {"ok": false, "reason": "bad_feet"}
		return {"ok": true, "data": d}
	var three_empty_bad_ver: Dictionary = net_v2.prepare_three_phase_state({}, 2, three_val_cb, {"version": 999, "cell_feet": -5})
	_check(not bool(three_empty_bad_ver.get("ok", true)) and three_empty_bad_ver.get("reason") == "unsupported_module_state_version", tag + ": 3-phase empty raw with mismatched defaults version must fail")
	var three_empty_str_ver: Dictionary = net_v2.prepare_three_phase_state({}, 2, three_val_cb, {"version": "2", "cell_feet": 5})
	_check(not bool(three_empty_str_ver.get("ok", true)) and three_empty_str_ver.get("reason") == "unsupported_module_state_version", tag + ": 3-phase empty raw with non-int defaults version must fail")
	var three_empty_bad_val: Dictionary = net_v2.prepare_three_phase_state({}, 2, three_val_cb, {"version": 2, "cell_feet": -5})
	_check(not bool(three_empty_bad_val.get("ok", true)) and three_empty_bad_val.get("reason") == "bad_feet", tag + ": 3-phase empty raw must invoke validator on defaults")
	var three_empty_omit_ver_bad_val: Dictionary = net_v2.prepare_three_phase_state({}, 2, three_val_cb, {"cell_feet": 0})
	_check(not bool(three_empty_omit_ver_bad_val.get("ok", true)) and three_empty_omit_ver_bad_val.get("reason") == "bad_feet", tag + ": 3-phase empty raw omitting version must still invoke validator")
	var three_empty_float_ver_ok: Dictionary = net_v2.prepare_three_phase_state({}, 2, three_val_cb, {"version": 2.0, "cell_feet": 7})
	_check(bool(three_empty_float_ver_ok.get("ok", false)) and typeof((three_empty_float_ver_ok["data"] as Dictionary).get("version")) == TYPE_INT and int((three_empty_float_ver_ok["data"] as Dictionary).get("version", 0)) == 2, tag + ": 3-phase empty raw float version defaults normalization failed")
	var three_bad_ver: Dictionary = net_v2.prepare_three_phase_state({"version": 99}, 2)
	_check(not bool(three_bad_ver.get("ok", true)), tag + ": 3-phase version mismatch must fail")
	var three_cyc_raw: Dictionary = net_v2.prepare_three_phase_state({"version": 2, "cyc": cyc_dict}, 2)
	_check(not bool(three_cyc_raw.get("ok", true)), tag + ": 3-phase cyclic raw_state must fail")
	var three_deep_raw: Dictionary = net_v2.prepare_three_phase_state({"version": 2, "deep": deep_32}, 2)
	_check(not bool(three_deep_raw.get("ok", true)), tag + ": 3-phase depth-33 raw_state must fail")
	var three_big_raw: Dictionary = net_v2.prepare_three_phase_state({"version": 2, "blob": oversized_bytes}, 2)
	_check(not bool(three_big_raw.get("ok", true)), tag + ": 3-phase >16MiB raw_state must fail")
	var three_cyc_def: Dictionary = net_v2.prepare_three_phase_state({}, 2, Callable(), {"cyc": cyc_dict})
	_check(not bool(three_cyc_def.get("ok", true)), tag + ": 3-phase cyclic defaults must fail")
	var three_deep_def: Dictionary = net_v2.prepare_three_phase_state({}, 2, Callable(), {"deep": deep_32})
	_check(not bool(three_deep_def.get("ok", true)), tag + ": 3-phase depth-33 defaults must fail")
	var three_big_def: Dictionary = net_v2.prepare_three_phase_state({}, 2, Callable(), {"blob": oversized_bytes})
	_check(not bool(three_big_def.get("ok", true)), tag + ": 3-phase >16MiB defaults must fail")
	var three_cyc_val: Dictionary = net_v2.prepare_three_phase_state({"version": 2}, 2, func(_d: Dictionary) -> Dictionary: return {"ok": true, "data": {"cyc": cyc_dict}})
	_check(not bool(three_cyc_val.get("ok", true)), tag + ": 3-phase validator returning cyclic dict must fail")
	var three_ok: Dictionary = net_v2.prepare_three_phase_state({"version": 2.0, "cell_feet": 10}, 2, func(d: Dictionary) -> Dictionary:
		if int(d.get("cell_feet", 0)) < 1:
			return {"ok": false, "reason": "bad_feet"}
		return {"ok": true, "data": d}
	)
	_check(bool(three_ok.get("ok", false)) and int((three_ok["data"] as Dictionary).get("cell_feet", 0)) == 10, tag + ": 3-phase valid state failed")

	var mw := _MockWorld.new()
	_check(net_v2.notify_module_content_changed(mw, valid_prov) and mw.content_notified, tag + ": notify_module_content_changed failed")
	_check(net_v2.publish_module_state(mw) and mw.published_rev == 4, tag + ": publish_module_state failed")

	mock_ctx.revert_all()


func _probe_two_req(_a: Variant, _b: Variant) -> void:
	pass


func _probe_opt_default(_a: Variant, _b: int = 7) -> void:
	pass


func _leak_iteration(v2_scr: Script) -> void:
	var rt: RefCounted = v2_scr.new()
	var logger: RefCounted = rt.create_logger({"emit_to_engine": false})
	rt.set_logger(logger)
	var _reg: RefCounted = rt.get_module_registry()
	var ctx := _MockExtensionContext.new()
	var api := _MockDesktopApi.new()
	ctx.services["desktop_api"] = api
	var dapi: RefCounted = rt.create_desktop_api_helper(ctx)
	var hook_h: RefCounted = rt.create_hook_helper(ctx)
	var slot_h: RefCounted = rt.create_slot_helper(ctx)
	var comp_h: RefCounted = rt.create_comp_helper(ctx)
	var net_h: RefCounted = rt.create_network_helper("demo.leak_test", false, ctx)
	var _g: bool = dapi.is_gm()
	var _tok: Variant = hook_h.subscribe(&"dice.rolled", func(_p: Dictionary) -> void: pass)
	var _spec: Dictionary = slot_h.make_mode_bar_spec("demo.m", "M", func(_d: Node) -> bool: return true, func(_d: Node) -> void: pass, func(_d: Node) -> bool: return true)
	var _pure: bool = comp_h.is_pure_data({"k": [1, 2, 3]})
	var _p3: Dictionary = net_h.prepare_three_phase_state({"version": 1}, 1)
	hook_h.revert_tracked()
	ctx.revert_all()


func _test_zero_leak_and_parent_release(v2_path: String) -> void:
	var v2_scr := load(v2_path) as Script
	_check(v2_scr != null, "leak check failed to load v2.gd")
	if v2_scr == null:
		return

	# Verify safe degradation after parent context is freed
	var rt: RefCounted = v2_scr.new()
	var temp_ctx := _MockExtensionContext.new()
	temp_ctx.services["desktop_api"] = _MockDesktopApi.new()
	var dapi: RefCounted = rt.create_desktop_api_helper(temp_ctx)
	var hook_h: RefCounted = rt.create_hook_helper(temp_ctx)
	_check(dapi.is_available(), "dapi should be available before context release")
	temp_ctx = null
	_check(not dapi.is_available(), "dapi must degrade safely after parent context release")
	_check(hook_h.subscribe(&"dice.rolled", func(_p: Dictionary) -> void: pass) == null, "hook_h must degrade safely after parent context release")
	rt = null
	dapi = null
	hook_h = null

	for _w: int in range(2):
		_leak_iteration(v2_scr)
	var obj_base: float = Performance.get_monitor(Performance.OBJECT_COUNT)
	for _i: int in range(20):
		_leak_iteration(v2_scr)
	var obj_after_20: float = Performance.get_monitor(Performance.OBJECT_COUNT)
	for _j: int in range(20):
		_leak_iteration(v2_scr)
	var obj_after_40: float = Performance.get_monitor(Performance.OBJECT_COUNT)
	_check(obj_after_20 - obj_base == 0.0, "OBJECT_COUNT leaked over 20 iters: delta=" + str(obj_after_20 - obj_base))
	_check(obj_after_40 - obj_after_20 == 0.0, "OBJECT_COUNT leaked over 40 iters: delta=" + str(obj_after_40 - obj_after_20))


var _done: bool = false


func _process(_delta: float) -> bool:
	if _done:
		return false
	_done = true
	_exercise_runtime(_DIRECT_V2_PATH, "direct")
	_exercise_runtime(_BUNDLED_V2_PATH, "bundled")
	_test_zero_leak_and_parent_release(_BUNDLED_V2_PATH)

	var out_path: String = ""
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with("--out="):
			out_path = arg.substr(6)
	var report: Dictionary = {
		"ok": _failures.is_empty(),
		"failures": _failures,
	}
	if not out_path.is_empty():
		var f := FileAccess.open(out_path, FileAccess.WRITE)
		if f != null:
			f.store_string(JSON.stringify(report))
			f.close()
	if not _failures.is_empty():
		for err: String in _failures:
			push_error(err)
		quit(1)
		return true
	quit(0)
	return true
'''


class TestFuRuntimeHeadlessGodot(unittest.TestCase):
    """Runs headless Godot against both direct shared/sdk/fu_runtime/ and simulated bundled lib/ layouts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = load_config(_WORKSPACE_ROOT)
        if cls.cfg.godot_bin is None or not cls.cfg.godot_bin.is_file():
            raise unittest.SkipTest("GODOT_BIN not configured; skipping headless Godot runtime SDK tests")
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.run_dir = TEST_TMP_ROOT / f"fu_runtime_probe_{uuid.uuid4().hex[:10]}"
        cls.proj_dir = cls.run_dir / "probe_proj"
        cls.proj_dir.mkdir(parents=True, exist_ok=True)
        (cls.proj_dir / "project.godot").write_text('config_version=5\n\n[application]\nconfig/name="FuRuntimeProbe"\n', encoding="utf-8")

        # 1. Direct shared/sdk layout
        shutil.copytree(FU_RUNTIME_DIR, cls.proj_dir / "shared" / "sdk" / "fu_runtime")
        shutil.copytree(FU_SDK_DIR, cls.proj_dir / "shared" / "sdk" / "fu_sdk")

        # 2. Simulated bundled module layout using ONLY runtime_manifest.json entries
        manifest = json.loads((FU_RUNTIME_DIR / "runtime_manifest.json").read_text(encoding="utf-8"))
        lib_dir = cls.proj_dir / "mods" / "demo_mod" / "lib"
        for rel in manifest["runtime_scripts"]:
            src = FU_RUNTIME_DIR / rel
            dst = lib_dir / "fu_runtime" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        for rel in manifest["shared_fu_sdk_scripts"]:
            src = FU_SDK_DIR / rel
            dst = lib_dir / "fu_sdk" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        (cls.proj_dir / "probe.gd").write_text(_PROBE_GD, encoding="utf-8", newline="\n")

    @classmethod
    def tearDownClass(cls) -> None:
        run_dir = getattr(cls, "run_dir", None)
        if run_dir is not None and run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)

    def test_headless_godot_dual_layout_helpers_and_zero_leaks(self) -> None:
        out_json = self.run_dir / "probe_out.json"
        godot_log = self.run_dir / "godot.log"
        iso_home = self.run_dir / "godot_home"
        iso_home.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["APPDATA"] = str(iso_home)
        env["LOCALAPPDATA"] = str(iso_home)
        env["TEMP"] = str(iso_home)
        env["TMP"] = str(iso_home)
        env["GODOT_SILENCE_ROOT_WARNING"] = "1"

        cmd = [
            str(self.cfg.godot_bin),
            "--headless",
            "--quit",
            "--path",
            str(self.proj_dir),
            "--log-file",
            str(godot_log),
            "--script",
            "res://probe.gd",
            "--",
            f"--out={out_json}",
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(self.proj_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log_text = godot_log.read_text(encoding="utf-8", errors="replace") if godot_log.is_file() else ""
        findings = analyze_godot_logs(log_text, proc.stdout, proc.stderr)
        redacted_stdout = self.cfg.redact_path(proc.stdout)
        redacted_stderr = self.cfg.redact_path(proc.stderr)
        self.assertEqual(
            proc.returncode,
            0,
            f"Godot probe failed (rc={proc.returncode}).\nSTDOUT:\n{redacted_stdout}\nSTDERR:\n{redacted_stderr}\nLOG:\n{self.cfg.redact_path(log_text)}",
        )
        self.assertEqual(findings, [], f"Unexpected Godot warnings/errors: {findings}")
        self.assertTrue(out_json.is_file(), "Godot probe did not write output JSON")
        report = json.loads(out_json.read_text(encoding="utf-8"))
        self.assertTrue(report.get("ok"), f"Godot probe reported failures: {report.get('failures')}")
