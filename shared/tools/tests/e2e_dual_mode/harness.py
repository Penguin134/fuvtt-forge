"""Isolated opaque-box E2E harness for Dual-Mode Fu vtt SDK (`fu_sdk` + `fu_runtime`), CLI, Templates & FUS Host-Load."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
import uuid
import zipfile
from typing import Any, Iterator, Mapping, Sequence


TOOLS_DIR = Path(__file__).resolve().parents[2]
TESTS_DIR = TOOLS_DIR / "tests"
WORKSPACE_ROOT = TOOLS_DIR.parents[1]
TEST_TMP_ROOT = WORKSPACE_ROOT / ".cache" / "test_tmp" / "e2e_dual_mode"
PROBE_GD_SOURCE = Path(__file__).resolve().with_name("e2e_dual_mode_probe.gd")
FUS_HOST_PROBE_SOURCE = Path(__file__).resolve().with_name("fus_host_load_probe.gd")

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from fuvtt_devtools.deployer import safe_extract_zip  # noqa: E402
from fuvtt_devtools.env_config import WorkspaceConfig, load_config  # noqa: E402
from fuvtt_devtools.host_verifier import PROBE_PROJECT_GODOT, analyze_godot_logs  # noqa: E402


_CASE_START_RE = re.compile(r"^=== E2E_CASE_START (\S+) ===\s*$")
_CASE_END_RE = re.compile(r"^=== E2E_CASE_END (\S+) ===\s*$")

_MIRROR_EXCLUDE_DIRS = frozenset({
    ".git",
    ".godot",
    ".vs",
    "probe_runs",
    "f2_data",
    "docs",
    "AI_CONTEXT",
    ".import",
})

# Minimal contract-faithful host shims staged ONLY inside `.cache/test_tmp/.../probe_project/fus_host_shims/`
# so standalone headless Godot can compile & test `extends ExtensionBase`, `extends CompBase`,
# `extends EntityComponentPage`, `HookIds`, and `BoardToken` without needing a C# build.
_FUS_HOST_SHIMS: dict[str, str] = {
    "fus_host_shims/hook_ids.gd": """extends RefCounted
class_name HookIds

const TABLE: Dictionary = {
\t&"entity.spawned": {"cancellable": false, "args": ["entity:BoardToken"]},
\t&"entity.removed": {"cancellable": false, "args": ["entity:BoardToken"]},
\t&"entity.trashed": {"cancellable": false, "args": ["entity:Node"]},
\t&"entity.restored": {"cancellable": false, "args": ["entity:Node"]},
\t&"entity.property_changed": {"cancellable": false, "args": ["entity:BoardToken", "prop:String", "old:Variant", "new:Variant"]},
\t&"entity.moved": {"cancellable": false, "args": ["entity:BoardToken", "from:Vector2", "to:Vector2"]},
\t&"entity.motion_committed": {"cancellable": false, "args": ["event:Dictionary"]},
\t&"entity.selected": {"cancellable": false, "args": ["entity:BoardToken"]},
\t&"entity.deselected": {"cancellable": false, "args": ["entity:BoardToken"]},
\t&"comp.added": {"cancellable": false, "args": ["host:Node", "comp:CompBase"]},
\t&"comp.removed": {"cancellable": false, "args": ["host:Node", "comp:CompBase"]},
\t&"comp.state_changed": {"cancellable": false, "args": ["host:Node", "comp:CompBase"]},
\t&"mode.pre_change": {"cancellable": true, "args": ["old:String", "new:String"]},
\t&"mode.changed": {"cancellable": false, "args": ["old:String", "new:String"]},
\t&"selection.changed": {"cancellable": false, "args": ["selected:Array"]},
\t&"viewpoint.changed": {"cancellable": false, "args": ["peer_id:int"]},
\t&"input.mouse_button": {"cancellable": true, "args": ["event:InputEventMouseButton"]},
\t&"input.mouse_motion": {"cancellable": true, "args": ["event:InputEventMouseMotion"]},
\t&"input.key": {"cancellable": true, "args": ["event:InputEventKey"]},
\t&"frame.process": {"cancellable": false, "args": ["delta:float"]},
\t&"frame.physics": {"cancellable": false, "args": ["delta:float"]},
\t&"room.player_joined": {"cancellable": false, "args": ["peer_id:int", "info:Dictionary"]},
\t&"room.player_left": {"cancellable": false, "args": ["peer_id:int"]},
\t&"room.player_connection_info_changed": {"cancellable": false, "args": ["peer_id:int", "info:Dictionary"]},
\t&"room.permission_changed": {"cancellable": false, "args": ["host:Node", "peer:int", "granted:bool"]},
\t&"save.pre_capture": {"cancellable": false, "args": ["snapshot:Dictionary"]},
\t&"save.post_capture": {"cancellable": false, "args": ["snapshot:Dictionary"]},
\t&"save.pre_restore": {"cancellable": false, "args": ["snapshot:Dictionary"]},
\t&"save.post_restore": {"cancellable": false, "args": ["snapshot:Dictionary"]},
\t&"palette.armed": {"cancellable": false, "args": ["id:String", "kind:String"]},
\t&"palette.placed": {"cancellable": false, "args": ["placed_node:Node"]},
\t&"combat.round_start": {"cancellable": false, "args": ["combat:Object"]},
\t&"combat.round_end": {"cancellable": false, "args": ["combat:Object"]},
\t&"combat.turn_start": {"cancellable": false, "args": ["combat:Object", "actor:Node"]},
\t&"combat.turn_end": {"cancellable": false, "args": ["combat:Object", "actor:Node"]},
\t&"area.enter": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"area.exit": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"area.stay_tick": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"door.toggled": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"portal.teleported": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"trap.triggered": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"transform.changed": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"rest.short": {"cancellable": false, "args": ["actor:Node"]},
\t&"rest.long": {"cancellable": false, "args": ["actor:Node"]},
\t&"camera.navigated": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"drawing.stroke_committed": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"ui.panel_opened": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"floor.changed": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"module.toggled": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"scene.switched": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"scene.created": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"entity_box.acted": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"dice.rolled": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"combat.started": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"combat.ended": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"vitals.changed": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"vitals.downed": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"chat.message_received": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"avg.stage_changed": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"avg.dialogue_shown": {"cancellable": false, "args": ["payload:Dictionary"]},
\t&"checklist.completed": {"cancellable": false, "args": ["payload:Dictionary"]},
}

static func is_custom_namespaced(hook_id: StringName) -> bool:
\tvar text := String(hook_id)
\tif not (text.begins_with("ext.") or text.begins_with("mod.")):
\t\treturn false
\tvar parts := text.split(".")
\tif parts.size() < 3 or text.length() > 128:
\t\treturn false
\tfor idx: int in range(1, parts.size()):
\t\tvar seg: String = parts[idx]
\t\tif seg.is_empty():
\t\t\treturn false
\t\tfor ch: String in seg:
\t\t\tvar code: int = ch.unicode_at(0)
\t\t\tvar ok: bool = (code >= 97 and code <= 122) or (code >= 48 and code <= 57) or code == 95
\t\t\tif not ok:
\t\t\t\treturn false
\treturn true

static func expected_arity(hook_id: StringName) -> int:
\tif TABLE.has(hook_id):
\t\treturn ((TABLE[hook_id] as Dictionary)["args"] as Array).size()
\tif is_custom_namespaced(hook_id):
\t\treturn 1
\treturn -1

static func is_registered(hook_id: StringName) -> bool:
\treturn TABLE.has(hook_id) or is_custom_namespaced(hook_id)

static func is_cancellable(hook_id: StringName) -> bool:
\tvar info: Dictionary = TABLE.get(hook_id, {})
\treturn bool(info.get("cancellable", false))
""",
    "fus_host_shims/token.gd": """extends RefCounted
class_name ExtToken

var label: String = ""
var last_rejection: String = ""
var _callback: Callable = Callable()
var _active: bool = true

static func make(callback: Callable, token_label: String = "") -> ExtToken:
\tvar tok := ExtToken.new()
\ttok.label = token_label
\ttok._callback = callback
\treturn tok

static func rejected(reason: String, token_label: String = "") -> ExtToken:
\tvar tok := ExtToken.new()
\ttok._active = false
\ttok.last_rejection = reason
\ttok.label = token_label
\treturn tok

func is_active() -> bool:
\treturn _active

func revert() -> void:
\tif not _active:
\t\treturn
\t_active = false
\tvar cb := _callback
\t_callback = Callable()
\tif cb.is_valid():
\t\tcb.call()
""",
    "fus_host_shims/extension_context.gd": """extends RefCounted
class_name ExtensionContext

var _owner_ref: WeakRef
var _runtime_ref: WeakRef
var _active: bool = true
var _mounted_nodes: Array[Node] = []
var _hook_tokens: Array[ExtToken] = []
var _signal_tokens: Array[Dictionary] = []

func _init(owner_node: Node = null, runtime_node_val: Node = null) -> void:
\t_owner_ref = weakref(owner_node) if is_instance_valid(owner_node) else null
\t_runtime_ref = weakref(runtime_node_val) if is_instance_valid(runtime_node_val) else null

func is_active() -> bool:
\treturn _active

func can_initialize() -> bool:
\treturn _active

func runtime_node() -> Node:
\treturn _runtime_ref.get_ref() as Node if _runtime_ref != null else null

func consume_service(service_id: String) -> Variant:
\tvar rt := runtime_node()
\tif rt != null and rt.has_method(&"consume_service"):
\t\treturn rt.call(&"consume_service", service_id)
\treturn null

func publish_service(service_id: String, provider: Variant) -> void:
\tvar rt := runtime_node()
\tif rt != null and rt.has_method(&"publish_service"):
\t\trt.call(&"publish_service", service_id, provider)

func register_slot_item(slot_id: StringName, spec: Dictionary) -> ExtToken:
\tvar rt := runtime_node()
\tif rt != null and rt.has_method(&"register_slot_item"):
\t\tvar res: Variant = rt.call(&"register_slot_item", slot_id, spec, self)
\t\tif res is Dictionary and bool((res as Dictionary).get("ok", false)):
\t\t\treturn ExtToken.make(Callable(), String(spec.get("id", String(slot_id))))
\t\tvar reason := String((res as Dictionary).get("reason", "slot_registration_rejected")) if res is Dictionary else "slot_registration_rejected"
\t\treturn ExtToken.rejected(reason, String(slot_id))
\treturn ExtToken.rejected("runtime_unavailable", String(slot_id))

func register_component(spec: Dictionary) -> ExtToken:
\tvar rt := runtime_node()
\tif rt != null and rt.has_method(&"register_component"):
\t\tvar res: Variant = rt.call(&"register_component", spec, self)
\t\tif res is Dictionary and bool((res as Dictionary).get("ok", false)):
\t\t\treturn ExtToken.make(Callable(), String(spec.get("id", "")))
\t\tvar reason := String((res as Dictionary).get("reason", "component_registration_rejected")) if res is Dictionary else "component_registration_rejected"
\t\treturn ExtToken.rejected(reason, String(spec.get("id", "")))
\treturn ExtToken.rejected("runtime_unavailable", String(spec.get("id", "")))

func mount_node(parent: Node, child: Node, index: int = -1) -> ExtToken:
\tvar rt := runtime_node()
\tif rt == null or not rt.has_method(&"get_desktop"):
\t\treturn ExtToken.rejected("mount_node_unavailable")
\tvar desk: Node = rt.call(&"get_desktop") as Node
\tif not is_instance_valid(desk) or not is_instance_valid(parent) or not is_instance_valid(child):
\t\treturn ExtToken.rejected("mount_node_invalid_target")
\tif parent != desk and not desk.is_ancestor_of(parent):
\t\treturn ExtToken.rejected("mount_node_invalid_target")
\tif child.get_parent() != null:
\t\treturn ExtToken.rejected("mount_node_invalid_target")
\tparent.add_child(child)
\tif index >= 0 and index < parent.get_child_count():
\t\tparent.move_child(child, index)
\t_mounted_nodes.append(child)
\treturn ExtToken.make(Callable(), child.name)

func subscribe_hook(hook_id: StringName, callback: Callable, priority: int = 0) -> ExtToken:
\tvar rt := runtime_node()
\tif rt != null and rt.has_method(&"subscribe_hook"):
\t\tvar res: Dictionary = rt.call(&"subscribe_hook", hook_id, callback, priority, self)
\t\tif bool(res.get("ok", false)):
\t\t\tvar tok := ExtToken.make(Callable(), String(hook_id))
\t\t\t_hook_tokens.append(tok)
\t\t\treturn tok
\t\treturn ExtToken.rejected(String(res.get("reason", "hook_unknown:" + String(hook_id))), String(hook_id))
\treturn ExtToken.rejected("hook_unknown:" + String(hook_id), String(hook_id))

func emit_hook(hook_id: StringName, args: Array = []) -> bool:
\tvar rt := runtime_node()
\tif not _active or rt == null:
\t\treturn false
\tif rt.has_method(&"configuration_is_publishing") and bool(rt.call(&"configuration_is_publishing")):
\t\treturn false
\tif rt.has_method(&"emit_hook"):
\t\treturn bool(rt.call(&"emit_hook", hook_id, args))
\treturn false

func subscribe_signal(emitter: Object, sig_name: StringName, callback: Callable) -> void:
\tif is_instance_valid(emitter) and emitter.has_signal(sig_name):
\t\temitter.connect(sig_name, callback)
\t\t_signal_tokens.append({"emitter": weakref(emitter), "sig": sig_name, "cb": callback})

func revert_all() -> void:
\t_active = false
\tvar rt := runtime_node()
\tif rt != null and rt.has_method(&"unsubscribe_context"):
\t\trt.call(&"unsubscribe_context", self)
\tfor tok: Dictionary in _signal_tokens:
\t\tvar em: Object = (tok["emitter"] as WeakRef).get_ref() as Object
\t\tif is_instance_valid(em) and em.is_connected(tok["sig"] as StringName, tok["cb"] as Callable):
\t\t\tem.disconnect(tok["sig"] as StringName, tok["cb"] as Callable)
\t_signal_tokens.clear()
\tfor node: Node in _mounted_nodes:
\t\tif is_instance_valid(node):
\t\t\tif node.has_method(&"deactivate"):
\t\t\t\tnode.call(&"deactivate")
\t\t\tif node.get_parent() != null:
\t\t\t\tnode.get_parent().remove_child(node)
\t\t\tnode.queue_free()
\t_mounted_nodes.clear()
\tfor htok: ExtToken in _hook_tokens:
\t\thtok.revert()
\t_hook_tokens.clear()
\t_owner_ref = null
\t_runtime_ref = null
""",
    "fus_host_shims/extension_base.gd": """extends Node2D
class_name ExtensionBase

var ctx: ExtensionContext = null

func _on_register(_context: ExtensionContext) -> void:
\tpass

func _on_unregister() -> void:
\tpass

func register_with_context(context: ExtensionContext) -> void:
\tctx = context
\t_on_register(context)

func unregister_with_context() -> void:
\t_on_unregister()
\tif ctx != null:
\t\tctx.revert_all()
\tctx = null
""",
    "fus_host_shims/comp_base.gd": """extends ExtensionBase
class_name CompBase

var _applying_state: bool = false
var _parked: bool = false

signal data_changed

static func id_from_path(path: String) -> String:
\tvar fname := path.get_file().get_basename()
\tif fname.begins_with("comp_"):
\t\treturn fname.trim_prefix("comp_")
\treturn fname

func get_comp_id() -> String:
\tvar scr := get_script() as Script
\tif scr != null and not scr.resource_path.is_empty():
\t\treturn id_from_path(scr.resource_path)
\treturn name

func notify_data_changed() -> void:
\tdata_changed.emit()

func component_tags() -> PackedStringArray:
\treturn PackedStringArray()

func exclusive_group() -> String:
\treturn ""

func conflicts_with_components() -> PackedStringArray:
\treturn PackedStringArray()

func suppresses_components() -> PackedStringArray:
\treturn PackedStringArray()

func suppression_allowlist() -> PackedStringArray:
\treturn PackedStringArray()

func dominance_priority() -> int:
\treturn 0

func editable_fields() -> Array[String]:
\treturn []

func supports_host(_host: Node) -> bool:
\treturn true

func accepts_state(state: Dictionary) -> bool:
\treturn state is Dictionary

func apply_state(state: Dictionary) -> bool:
\tif not accepts_state(state):
\t\treturn false
\t_applying_state = true
\tfor k: Variant in state.keys():
\t\tvar key_str := String(k)
\t\tif key_str in self:
\t\t\tset(key_str, state[k])
\t_applying_state = false
\treturn true

func serialize_state() -> Dictionary:
\tvar out: Dictionary = {}
\tfor prop: Dictionary in get_property_list():
\t\tvar usage := int(prop.get("usage", 0))
\t\tvar pname := String(prop.get("name", ""))
\t\tif (usage & PROPERTY_USAGE_SCRIPT_VARIABLE) != 0 and not pname.begins_with("_") and pname != "ctx":
\t\t\tout[pname] = get(pname)
\treturn out
""",
    "fus_host_shims/comp_permission.gd": """extends CompBase
class_name CompPermission

signal entry_permission_review_needed

var commanders: Array[int] = [1]
@export var owners_csv: String = ""
@export var gm_can_operate: bool = true
@export var all_players_can_operate: bool = false
@export var owner_peers: PackedInt32Array = PackedInt32Array()
@export var owner_player_ids: PackedStringArray = PackedStringArray()

func get_comp_id() -> String:
\treturn "permission"

func editable_fields() -> Array[String]:
\treturn ["all_players_can_operate", "owners_csv", "owner_player_ids"]

func has_owner_identity(identity: String) -> bool:
\treturn identity in owner_player_ids

func can_command(peer_id: int) -> bool:
\treturn can_command_in(peer_id, null)

func can_command_in(peer_id: int, _expected_session: DesktopNetworkSession = null) -> bool:
\tif peer_id <= 0:
\t\treturn false
\tif all_players_can_operate or (peer_id == 1 and gm_can_operate):
\t\treturn true
\treturn peer_id in commanders
""",
    "fus_host_shims/board_token.gd": """extends Node2D
class_name BoardToken

@export var display_name: String = "Token"
@export var entity_type: String = "unit"
@export var entity_locked: bool = false
@export var entity_hidden: bool = false
@export var selectable_in_select_mode: bool = true

var _components: Dictionary = {}
var _parked: Dictionary = {}
var component_pair_rejections: int = 0

signal transform_changed
signal flags_changed

func is_unit() -> bool:
\treturn entity_type == "unit"

func visual_world_size() -> Vector2:
\treturn Vector2(64.0, 64.0)

func has_component_record(comp_id: String) -> bool:
\treturn _components.has(comp_id) or _parked.has(comp_id)

func get_component_by_id(comp_id: String) -> CompBase:
\treturn _components.get(comp_id, null) as CompBase

func parked_component_count() -> int:
\treturn _parked.size()

func is_component_suppressed(comp_id: String) -> bool:
\treturn _parked.has(comp_id)

func _is_suppressed_by(dominant: CompBase, target: CompBase) -> bool:
\tvar sup: PackedStringArray = dominant.suppresses_components()
\tif sup.is_empty():
\t\treturn false
\tvar tid := target.get_comp_id()
\tif tid in ["visual", "permission"]:
\t\treturn false
\tvar allow := dominant.suppression_allowlist()
\tif tid in allow:
\t\treturn false
\tif "*" in sup or tid in sup:
\t\treturn true
\tfor t: String in target.component_tags():
\t\tif ("tag:" + t) in sup:
\t\t\treturn true
\treturn false

func add_component(comp: CompBase) -> bool:
\tif comp == null or not comp.supports_host(self):
\t\treturn false
\tvar cid := comp.get_comp_id()
\tif _components.has(cid):
\t\treturn false
\t# Check if blocked by an already-active dominant component or exclusive_group
\tfor existing_id: Variant in _components.keys():
\t\tvar ex := _components[existing_id] as CompBase
\t\tif _is_suppressed_by(ex, comp):
\t\t\tcomponent_pair_rejections += 1
\t\t\treturn false
\t\tif not ex.exclusive_group().is_empty() and ex.exclusive_group() == comp.exclusive_group():
\t\t\tcomponent_pair_rejections += 1
\t\t\treturn false
\t\tif cid in ex.conflicts_with_components() or String(existing_id) in comp.conflicts_with_components():
\t\t\tcomponent_pair_rejections += 1
\t\t\treturn false
\t# Suppress lower-priority existing components if new comp is dominant
\tvar to_park: Array[String] = []
\tfor existing_id: Variant in _components.keys():
\t\tvar ex := _components[existing_id] as CompBase
\t\tif _is_suppressed_by(comp, ex):
\t\t\tto_park.append(String(existing_id))
\tfor pid: String in to_park:
\t\tvar parked_comp := _components[pid] as CompBase
\t\t_components.erase(pid)
\t\tremove_child(parked_comp)
\t\tparked_comp._parked = true
\t\t_parked[pid] = parked_comp
\t_components[cid] = comp
\tcomp._parked = false
\tadd_child(comp)
\treturn true

func purge_component_by_id(comp_id: String) -> bool:
\tvar removed := false
\tif _components.has(comp_id):
\t\tvar c := _components[comp_id] as CompBase
\t\t_components.erase(comp_id)
\t\tremove_child(c)
\t\tc.free()
\t\tremoved = true
\telif _parked.has(comp_id):
\t\tvar pc := _parked[comp_id] as CompBase
\t\t_parked.erase(comp_id)
\t\tpc.free()
\t\tremoved = true
\tif removed:
\t\tvar to_revive: Array[String] = []
\t\tfor pid: Variant in _parked.keys():
\t\t\tvar pcomp := _parked[pid] as CompBase
\t\t\tvar still_suppressed := false
\t\t\tfor eid: Variant in _components.keys():
\t\t\t\tif _is_suppressed_by(_components[eid] as CompBase, pcomp):
\t\t\t\t\tstill_suppressed = true
\t\t\t\t\tbreak
\t\t\tif not still_suppressed:
\t\t\t\tto_revive.append(String(pid))
\t\tfor rid: String in to_revive:
\t\t\tvar rcomp := _parked[rid] as CompBase
\t\t\t_parked.erase(rid)
\t\t\trcomp._parked = false
\t\t\t_components[rid] = rcomp
\t\t\tadd_child(rcomp)
\treturn removed

func cleanup_all_components() -> void:
\tfor c: CompBase in _components.values():
\t\tif is_instance_valid(c):
\t\t\tif c.get_parent() == self:
\t\t\t\tremove_child(c)
\t\t\tc.free()
\t_components.clear()
\tfor pc: CompBase in _parked.values():
\t\tif is_instance_valid(pc):
\t\t\tpc.free()
\t_parked.clear()
""",
    "fus_host_shims/entity_component_page.gd": """extends VBoxContainer
class_name EntityComponentPage

signal editing_started
signal edit_requested(kind: StringName, payload: Dictionary)

var component_id: String = ""

func bind_entities(_entities: Array[BoardToken]) -> void:
\tpass

func refresh() -> void:
\tpass
""",
    "fus_host_shims/edit_mode_controller.gd": """extends Node
class_name EditModeController

var undo_stack: Array[Dictionary] = []
var redo_stack: Array[Dictionary] = []
var _history_seq: int = 0
var _last_author_history: Dictionary = {}

func components_request(targets: Array, comp_path: String, op: StringName) -> bool:
\tvar scr := load(comp_path) as Script
\tif scr == null:
\t\treturn false
\tvar cid := CompBase.id_from_path(comp_path)
\tvar changed := false
\tfor t: Variant in targets:
\t\tif not (t is BoardToken):
\t\t\tcontinue
\t\tvar tok := t as BoardToken
\t\tif op == &"activate":
\t\t\tvar inst := scr.new() as CompBase
\t\t\tinst.ctx = ExtensionContext.new(tok, null)
\t\t\tif tok.add_component(inst):
\t\t\t\tchanged = true
\t\t\telse:
\t\t\t\tinst.free()
\t\telif op == &"park":
\t\t\tif tok.get_component_by_id(cid) != null:
\t\t\t\tvar c := tok.get_component_by_id(cid)
\t\t\t\ttok._components.erase(cid)
\t\t\t\ttok.remove_child(c)
\t\t\t\tc._parked = true
\t\t\t\ttok._parked[cid] = c
\t\t\t\tchanged = true
\tif changed:
\t\t_history_seq += 1
\t\tundo_stack.append({"op": String(op), "comp_path": comp_path, "id": _history_seq})
\treturn changed

func configure_components(targets: Array, comp_path: String, prev_list: Array, desired_list: Array, guard: Callable, author: String, _merge: bool) -> bool:
\tif guard.is_valid() and not bool(guard.call()):
\t\treturn false
\tvar cid := CompBase.id_from_path(comp_path)
\tfor idx: int in range(targets.size()):
\t\tvar tok := targets[idx] as BoardToken
\t\tvar comp := tok.get_component_by_id(cid)
\t\tif comp == null:
\t\t\treturn false
\t\tvar prev_state := (prev_list[idx] as Dictionary).get("state", {}) as Dictionary
\t\tif prev_state.is_empty():
\t\t\tprev_state = comp.serialize_state()
\t\tvar desired := (desired_list[idx] as Dictionary).get("state", {}) as Dictionary
\t\tif not comp.accepts_state(desired):
\t\t\treturn false
\t\tvar editable := comp.editable_fields()
\t\tvar fields: Array = prev_state.keys()
\t\tfor key: Variant in desired.keys():
\t\t\tif key not in fields:
\t\t\t\tfields.append(key)
\t\tfor key: Variant in fields:
\t\t\tvar kstr := String(key)
\t\t\tif prev_state.get(key) != desired.get(key) and kstr not in editable:
\t\t\t\treturn false
\tfor idx: int in range(targets.size()):
\t\tvar tok := targets[idx] as BoardToken
\t\tvar comp := tok.get_component_by_id(cid)
\t\tvar desired := (desired_list[idx] as Dictionary).get("state", {}) as Dictionary
\t\tcomp.apply_state(desired)
\t_history_seq += 1
\tvar rec := {"id": _history_seq, "author": author, "targets": targets, "comp_path": comp_path, "prev": prev_list, "desired": desired_list}
\tundo_stack.append(rec)
\tredo_stack.clear()
\t_last_author_history[author] = rec
\treturn true

func undo() -> bool:
\tif undo_stack.is_empty():
\t\treturn false
\tvar rec := undo_stack.pop_back() as Dictionary
\tif rec.has("prev"):
\t\tvar targets: Array = rec["targets"]
\t\tvar cid := CompBase.id_from_path(String(rec["comp_path"]))
\t\tvar prev_list: Array = rec["prev"]
\t\tfor idx: int in range(targets.size()):
\t\t\tvar comp := (targets[idx] as BoardToken).get_component_by_id(cid)
\t\t\tif comp != null:
\t\t\t\tcomp.apply_state((prev_list[idx] as Dictionary).get("state", {}) as Dictionary)
\t\tredo_stack.append(rec)
\treturn true

func redo() -> bool:
\tif redo_stack.is_empty():
\t\treturn false
\tvar rec := redo_stack.pop_back() as Dictionary
\tif rec.has("desired"):
\t\tvar targets: Array = rec["targets"]
\t\tvar cid := CompBase.id_from_path(String(rec["comp_path"]))
\t\tvar desired_list: Array = rec["desired"]
\t\tfor idx: int in range(targets.size()):
\t\t\tvar comp := (targets[idx] as BoardToken).get_component_by_id(cid)
\t\t\tif comp != null:
\t\t\t\tcomp.apply_state((desired_list[idx] as Dictionary).get("state", {}) as Dictionary)
\t\tundo_stack.append(rec)
\treturn true

func author_history(_include_world: bool, author: String) -> Dictionary:
\treturn _last_author_history.get(author, {}) as Dictionary
""",
    "fus_host_shims/desktop_network_session.gd": """extends Node
class_name DesktopNetworkSession

var players: Dictionary = {1: {"name": "GM", "peer_id": 1}}
var admitted_peers: Dictionary = {1: true}
var _is_gm: bool = true
var _local_peer: int = 1

static func _valid_identity(v: Variant) -> bool:
\treturn v is String and not String(v).strip_edges().is_empty() and String(v).length() <= 128

func can_author_world() -> bool:
\treturn _is_gm

func local_peer_id() -> int:
\treturn _local_peer

func is_admitted(peer: int) -> bool:
\treturn bool(admitted_peers.get(peer, false))

func get_peer_stable_id(peer: int) -> String:
\treturn "host" if peer == 1 else "peer_%d" % peer

func module_lifecycle_context() -> Dictionary:
\treturn {"role": "host" if _is_gm else "client"}
""",
    "fus_host_shims/slot_registry.gd": """extends Node
class_name SlotRegistry

var _items: Dictionary = {}

func register_item(slot_id: StringName, spec: Dictionary) -> bool:
\tif not _items.has(slot_id):
\t\t_items[slot_id] = []
\t(_items[slot_id] as Array).append(spec)
\treturn true

func has_slot(slot_id: StringName) -> bool:
\treturn _items.has(slot_id) and not (_items[slot_id] as Array).is_empty()

func items(slot_id: StringName) -> Array:
\treturn (_items.get(slot_id, []) as Array).duplicate()

func items_by_source(source_id: String) -> Array:
\tvar out: Array = []
\tfor arr: Array in _items.values():
\t\tfor item: Dictionary in arr:
\t\t\tif String(item.get("source", "")) == source_id:
\t\t\t\tout.append(item)
\treturn out
""",
}


@dataclass(frozen=True)
class CliResult:
    returncode: int
    stdout: str
    stderr: str
    args: list[str]
    raw_stdout: str = ""
    raw_stderr: str = ""


@dataclass
class ProbeCaseSpec:
    case_id: str
    op: str
    params: Mapping[str, Any] = field(default_factory=dict)
    pack_path: str = ""
    sdk_root: str = "res://sdk_stage/fu_runtime/v2.gd"
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ProbeCaseResult:
    case_id: str
    completed: bool
    crashed_or_timed_out: bool
    ok: bool
    data: dict[str, Any]
    gd_check_failures: list[str]
    log_errors: list[str]
    exit_code: int = 0
    timed_out: bool = False
    global_log_errors: list[str] = field(default_factory=list)
    compile_failures: list[str] = field(default_factory=list)


@dataclass
class ProbeBatchSummary:
    loaded_scripts: list[str]
    compile_failures: list[str]
    global_log_errors: list[str]
    results: dict[str, ProbeCaseResult]


def encode_special_inputs(val: Any) -> Any:
    """Encode Python NaN/Inf/bytes into tagged JSON structures so JSON remains RFC-8259 strict."""
    if isinstance(val, float):
        if math.isnan(val):
            return {"__gd_type": "float", "value": "NaN"}
        if math.isinf(val):
            return {"__gd_type": "float", "value": "Inf" if val > 0 else "-Inf"}
        return val
    if isinstance(val, (bytes, bytearray)):
        return {"__gd_type": "PackedByteArray", "bytes": [int(b) for b in val]}
    if isinstance(val, tuple):
        return [encode_special_inputs(x) for x in val]
    if isinstance(val, list):
        return [encode_special_inputs(x) for x in val]
    if isinstance(val, dict):
        return {str(k): encode_special_inputs(v) for k, v in val.items()}
    return val


def _decode_float_token(v: Any) -> Any:
    if v == "__NAN__":
        return float("nan")
    if v == "__INF__":
        return float("inf")
    if v == "__-INF__":
        return float("-inf")
    return v


def decode_gd_json(val: Any) -> Any:
    if isinstance(val, str):
        return _decode_float_token(val)
    if isinstance(val, list):
        return [decode_gd_json(x) for x in val]
    if isinstance(val, dict):
        gd_type = val.get("__gd_type")
        if gd_type == "Vector2":
            return (float(_decode_float_token(val["x"])), float(_decode_float_token(val["y"])))
        if gd_type == "Color":
            return (
                float(_decode_float_token(val["r"])),
                float(_decode_float_token(val["g"])),
                float(_decode_float_token(val["b"])),
                float(_decode_float_token(val["a"])),
            )
        if gd_type == "PackedByteArray":
            return bytes(int(b) & 0xFF for b in val.get("bytes", []))
        return {k: decode_gd_json(v) for k, v in val.items()}
    return val


def write_utf8_no_bom_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = text.lstrip("\ufeff").replace("\r\n", "\n")
    path.write_bytes(cleaned.encode("utf-8"))


def _clear_readonly_tree(root: Path) -> None:
    if not root.exists():
        return
    for current_root, dir_names, file_names in os.walk(root):
        for name in (*dir_names, *file_names):
            target = Path(current_root) / name
            try:
                os.chmod(target, os.stat(target).st_mode | stat.S_IWRITE)
            except OSError:
                pass
    try:
        os.chmod(root, os.stat(root).st_mode | stat.S_IWRITE)
    except OSError:
        pass


def _rmtree_force(root: Path) -> None:
    if not root.exists():
        return

    def _on_exc(func: Any, path: str, _exc: BaseException) -> None:
        os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
        func(path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(root, onexc=_on_exc)
    else:
        def _on_err(func: Any, path: str, _exc_info: Any) -> None:
            os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
            func(path)
        shutil.rmtree(root, onerror=_on_err)


def load_workspace_config() -> WorkspaceConfig:
    return load_config(WORKSPACE_ROOT)


def resolve_wiki_dir() -> Path:
    """Resolve Wiki directory via `FUVTT_WIKI_DIR` env var or sibling `fuvtt-mod-wiki` directory."""
    raw = os.environ.get("FUVTT_WIKI_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (WORKSPACE_ROOT.parent / "fuvtt-mod-wiki").resolve()


def resolve_godot_or_skip(cfg: WorkspaceConfig) -> Path:
    """Resolve `GODOT_BIN`; fail loudly if `FUVTT_E2E_REQUIRE_GODOT=1`, else `unittest.SkipTest`."""
    require = os.environ.get("FUVTT_E2E_REQUIRE_GODOT") == "1"
    try:
        godot_bin = cfg.resolve_godot_bin()
    except Exception as exc:  # noqa: BLE001
        if require:
            raise AssertionError(f"FUVTT_E2E_REQUIRE_GODOT=1 but GODOT_BIN resolution failed: {exc}") from exc
        raise unittest.SkipTest(f"GODOT_BIN unavailable: {exc}") from exc

    if not godot_bin.is_file():
        msg = f"GODOT_BIN not found: {cfg.redact_path(godot_bin)}"
        if require:
            raise AssertionError(msg)
        raise unittest.SkipTest(msg)
    return godot_bin


def resolve_fus_repo_or_skip(cfg: WorkspaceConfig, *, require_mirror: bool = False) -> Path:
    """Resolve `<FUS_REPO_DIR>`; fail loudly if required, else `unittest.SkipTest`."""
    require = require_mirror or os.environ.get("FUVTT_E2E_REQUIRE_FUS_MIRROR") == "1"
    try:
        fus_repo = cfg.resolve_fus_repo_dir()
    except Exception as exc:  # noqa: BLE001
        if require:
            raise AssertionError(f"FUS_REPO_DIR required but unavailable: {exc}") from exc
        raise unittest.SkipTest(f"FUS_REPO_DIR unavailable: {exc}") from exc
    if not fus_repo.is_dir():
        msg = f"FUS_REPO_DIR not found: {cfg.redact_path(fus_repo)}"
        if require:
            raise AssertionError(msg)
        raise unittest.SkipTest(msg)
    return fus_repo


def run_git_readonly(
    args: Sequence[str], *, repo_dir: Path | None = None, timeout: int = 30
) -> subprocess.CompletedProcess[str]:
    """Run strictly read-only git commands."""
    allowed_subcommands = {"status", "ls-files", "check-ignore", "rev-parse", "diff", "log", "show", "config"}
    if not args or args[0] not in allowed_subcommands:
        raise ValueError(f"Disallowed non-readonly git command: {args!r}")
    target_dir = repo_dir or WORKSPACE_ROOT
    return subprocess.run(
        ["git", "-C", str(target_dir), *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _attribute_logs_by_case(
    stdout_text: str, godot_log_text: str, stderr_text: str
) -> tuple[dict[str, list[str]], list[str]]:
    per_case_lines: dict[str, list[str]] = {}
    outside_lines: list[str] = []

    for stream_text in (stdout_text, godot_log_text):
        current_case: str | None = None
        for line in stream_text.splitlines():
            m_start = _CASE_START_RE.match(line.strip())
            if m_start:
                current_case = m_start.group(1)
                per_case_lines.setdefault(current_case, [])
                continue
            m_end = _CASE_END_RE.match(line.strip())
            if m_end:
                current_case = None
                continue
            if current_case is not None:
                per_case_lines[current_case].append(line)
            else:
                outside_lines.append(line)

    per_case_errors: dict[str, list[str]] = {}
    for cid, lines in per_case_lines.items():
        per_case_errors[cid] = analyze_godot_logs("\n".join(lines))

    global_errors = analyze_godot_logs("\n".join(outside_lines), stderr_text)
    return per_case_errors, global_errors


class E2ESession:
    """Manages an isolated `.cache/test_tmp/e2e_dual_mode/<run_id>/` workspace."""

    def __init__(self, name_prefix: str = "run", config: WorkspaceConfig | None = None) -> None:
        self.cfg = config or load_workspace_config()
        self.name_prefix = name_prefix
        self.run_dir: Path | None = None
        self.build_dir: Path | None = None
        self.cache_dir: Path | None = None
        self.mods_dir: Path | None = None
        self.probe_project: Path | None = None
        self.extracted_dir: Path | None = None
        self.target_plugins_dir: Path | None = None
        self.env_dirs: dict[str, Path] = {}
        self.godot_bin: Path | None = None
        self._e2e_batch_counter: int = 0
        self._e2e_parity_counter: int = 0

    def setup(self, *, require_godot: bool = False) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.run_dir = (TEST_TMP_ROOT / f"{self.name_prefix}_{stamp}_{uuid.uuid4().hex[:8]}").resolve()
        if not self.run_dir.is_relative_to(WORKSPACE_ROOT.resolve()):
            raise RuntimeError(f"Sandbox violation: run_dir outside workspace: {self.run_dir}")

        self.build_dir = self.run_dir / "build"
        self.cache_dir = self.run_dir / "cache"
        self.mods_dir = self.run_dir / "mods"
        self.probe_project = self.run_dir / "probe_project"
        self.extracted_dir = self.run_dir / "extracted"
        self.target_plugins_dir = self.run_dir / "target_plugins"
        env_root = self.run_dir / "isolated_env"
        self.env_dirs = {
            "appdata": env_root / "appdata",
            "localappdata": env_root / "localappdata",
            "temp": env_root / "temp",
        }
        for d in (
            self.build_dir,
            self.cache_dir,
            self.mods_dir,
            self.probe_project,
            self.extracted_dir,
            self.target_plugins_dir,
            *self.env_dirs.values(),
        ):
            d.mkdir(parents=True, exist_ok=True)

        # Copy existing templates into isolated mods/ if present so `init` / baseline tests stay isolated
        for tpl_name in ("_template", "_template-desktop-module", "_template-world-plugin"):
            src_tpl = self.cfg.mods_dir / tpl_name
            dst_tpl = self.mods_dir / tpl_name
            if src_tpl.is_dir() and not dst_tpl.exists():
                shutil.copytree(src_tpl, dst_tpl)
                _clear_readonly_tree(dst_tpl)

        if require_godot:
            self.godot_bin = resolve_godot_or_skip(self.cfg)

    def make_isolated_config(self, mods_dir: Path | None = None) -> WorkspaceConfig:
        assert self.build_dir is not None and self.cache_dir is not None and self.mods_dir is not None
        return WorkspaceConfig(
            workspace_root=WORKSPACE_ROOT.resolve(),
            mods_dir=(mods_dir or self.mods_dir).resolve(),
            sdk_dir=self.cfg.sdk_dir,
            build_dir=self.build_dir.resolve(),
            cache_dir=self.cache_dir.resolve(),
            fuvtt_install_dir=self.cfg.fuvtt_install_dir,
            fuvtt_mods_subdir=self.cfg.fuvtt_mods_subdir,
            fus_repo_dir=self.cfg.fus_repo_dir,
            fus_source_ref=self.cfg.fus_source_ref,
            godot_bin=self.cfg.godot_bin,
        )

    def child_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["APPDATA"] = str(self.env_dirs["appdata"])
        env["LOCALAPPDATA"] = str(self.env_dirs["localappdata"])
        env["TEMP"] = str(self.env_dirs["temp"])
        env["TMP"] = str(self.env_dirs["temp"])
        env["PYTHONUTF8"] = "1"
        env["GODOT_SILENCE_ROOT_WARNING"] = "1"
        return env

    def cleanup(self) -> None:
        if os.environ.get("FUVTT_E2E_KEEP_EVIDENCE") == "1":
            return
        if self.run_dir is None or not self.run_dir.exists():
            return
        _rmtree_force(self.run_dir)
        if TEST_TMP_ROOT.exists():
            try:
                if not any(TEST_TMP_ROOT.iterdir()):
                    TEST_TMP_ROOT.rmdir()
            except OSError:
                pass


class CliRunner:
    """Runs `shared/tools/fuvtt_cli.py` either against isolated mods or real workspace mods."""

    def __init__(self, session: E2ESession) -> None:
        self.session = session

    def run_real(self, args: Sequence[str], *, timeout: int = 180) -> CliResult:
        """Invoke `fuvtt_cli.py` subprocess with `BUILD_DIR` and `CACHE_DIR` isolated to session."""
        assert self.session.build_dir is not None and self.session.cache_dir is not None
        cfg = self.session.cfg
        rel_build = self.session.build_dir.resolve().relative_to(WORKSPACE_ROOT.resolve()).as_posix()
        rel_cache = self.session.cache_dir.resolve().relative_to(WORKSPACE_ROOT.resolve()).as_posix()

        env = self.session.child_env()
        env["BUILD_DIR"] = rel_build
        env["CACHE_DIR"] = rel_cache

        cmd = [sys.executable, str(TOOLS_DIR / "fuvtt_cli.py"), *args]
        proc = subprocess.run(
            cmd,
            cwd=str(WORKSPACE_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return CliResult(
            returncode=proc.returncode,
            stdout=cfg.redact_path(proc.stdout),
            stderr=cfg.redact_path(proc.stderr),
            args=list(args),
            raw_stdout=proc.stdout,
            raw_stderr=proc.stderr,
        )

    def run_isolated(
        self,
        args: Sequence[str],
        *,
        mods_dir: Path | None = None,
        timeout: int = 180,
    ) -> CliResult:
        """Invoke `fuvtt_cli.main(..., config=iso_cfg)` in an isolated subprocess without touching real `mods/`."""
        iso_cfg = self.session.make_isolated_config(mods_dir=mods_dir)
        bootstrap = (
            "import json, sys; from pathlib import Path; "
            f"sys.path.insert(0, {json.dumps(str(TOOLS_DIR))}); "
            "import fuvtt_cli; from fuvtt_devtools.env_config import WorkspaceConfig, load_config; "
            "base = load_config(Path(sys.argv[1])); "
            "cfg = WorkspaceConfig("
            "workspace_root=base.workspace_root, "
            "mods_dir=Path(sys.argv[2]), "
            "sdk_dir=Path(sys.argv[3]), "
            "build_dir=Path(sys.argv[4]), "
            "cache_dir=Path(sys.argv[5]), "
            "fuvtt_install_dir=base.fuvtt_install_dir, "
            "fus_repo_dir=base.fus_repo_dir, "
            "fus_source_ref=base.fus_source_ref, "
            "godot_bin=base.godot_bin); "
            "raise SystemExit(fuvtt_cli.main(json.loads(sys.argv[6]), config=cfg))"
        )
        env = self.session.child_env()
        cmd = [
            sys.executable,
            "-c",
            bootstrap,
            str(iso_cfg.workspace_root),
            str(iso_cfg.mods_dir),
            str(iso_cfg.sdk_dir),
            str(iso_cfg.build_dir),
            str(iso_cfg.cache_dir),
            json.dumps(list(args)),
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(WORKSPACE_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return CliResult(
            returncode=proc.returncode,
            stdout=iso_cfg.redact_path(proc.stdout),
            stderr=iso_cfg.redact_path(proc.stderr),
            args=list(args),
            raw_stdout=proc.stdout,
            raw_stderr=proc.stderr,
        )

    @contextlib.contextmanager
    def isolated_serve(
        self,
        *,
        mods_dir: Path | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
        timeout: float = 30.0,
    ) -> Iterator[tuple[int, urllib.request.OpenerDirector]]:
        """Start an isolated `fuvtt_cli.py serve` subprocess on an ephemeral port with proxy-free HTTP opener."""
        iso_cfg = self.session.make_isolated_config(mods_dir=mods_dir)
        bootstrap = (
            "import sys; from pathlib import Path; "
            f"sys.path.insert(0, {json.dumps(str(TOOLS_DIR))}); "
            "import fuvtt_cli; from fuvtt_devtools.env_config import WorkspaceConfig, load_config; "
            "base = load_config(Path(sys.argv[1])); "
            "cfg = WorkspaceConfig("
            "workspace_root=base.workspace_root, "
            "mods_dir=Path(sys.argv[2]), "
            "sdk_dir=Path(sys.argv[3]), "
            "build_dir=Path(sys.argv[4]), "
            "cache_dir=Path(sys.argv[5]), "
            "fuvtt_install_dir=base.fuvtt_install_dir, "
            "fus_repo_dir=base.fus_repo_dir, "
            "fus_source_ref=base.fus_source_ref, "
            "godot_bin=base.godot_bin); "
            f"fuvtt_cli.main(['serve', '--host', {json.dumps(host)}, '--port', {json.dumps(str(port))}], config=cfg)"
        )
        proc = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-c",
                bootstrap,
                str(iso_cfg.workspace_root),
                str(iso_cfg.mods_dir),
                str(iso_cfg.sdk_dir),
                str(iso_cfg.build_dir),
                str(iso_cfg.cache_dir),
            ],
            cwd=str(WORKSPACE_ROOT),
            env=self.session.child_env(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        out_lines: list[str] = []
        err_lines: list[str] = []
        bound_port: list[int] = []
        ready_ev = threading.Event()
        port_re = re.compile(r"http://127\.0\.0\.1:(\d+)/")

        def _drain_stdout() -> None:
            assert proc.stdout is not None
            for line in proc.stdout:
                out_lines.append(line)
                m = port_re.search(line)
                if m and not bound_port:
                    bound_port.append(int(m.group(1)))
                    ready_ev.set()

        def _drain_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                err_lines.append(line)

        t_out = threading.Thread(target=_drain_stdout, daemon=True)
        t_err = threading.Thread(target=_drain_stderr, daemon=True)
        t_out.start()
        t_err.start()

        try:
            deadline = time.monotonic() + timeout
            while not ready_ev.is_set() and time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                ready_ev.wait(timeout=0.1)

            if not bound_port:
                raise AssertionError(
                    f"serve did not report bound port within {timeout}s (rc={proc.poll()}): "
                    f"stdout={''.join(out_lines)!r} stderr={''.join(err_lines)!r}"
                )

            actual_port = bound_port[0]
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            last_exc: Exception | None = None
            idx_ready = False
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    with opener.open(f"http://127.0.0.1:{actual_port}/index.json", timeout=2) as resp:
                        if resp.status == 200:
                            idx_ready = True
                            break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    time.sleep(0.1)
            if not idx_ready:
                raise AssertionError(
                    f"serve /index.json did not respond in time on port {actual_port} "
                    f"(rc={proc.poll()}, last_exc={last_exc!r}): stderr={''.join(err_lines)!r}"
                )

            yield actual_port, opener
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass


class GodotBatchProbe:
    """Stages isolated `probe_project/` with host shims + `e2e_dual_mode_probe.gd` and runs batched Godot probes."""

    def __init__(self, session: E2ESession) -> None:
        self.session = session
        self.godot_bin: Path | None = None
        self.staged = False
        self._local_batch_counter: int = 0

    def prepare_probe_project(self, *, stage_shared_sdk: bool = True) -> Path:
        assert self.session.probe_project is not None
        self.godot_bin = self.session.godot_bin or resolve_godot_or_skip(self.session.cfg)
        proj = self.session.probe_project

        project_godot = PROBE_PROJECT_GODOT.replace(
            'config/name="FuVTT_VerifyHostProbe"', 'config/name="FuVTT_E2EDualModeProbe"'
        )
        write_utf8_no_bom_lf(proj / "project.godot", project_godot)
        for rel_path, content in _FUS_HOST_SHIMS.items():
            write_utf8_no_bom_lf(proj / rel_path, content)
        write_utf8_no_bom_lf(
            proj / "e2e_dual_mode_probe.gd",
            PROBE_GD_SOURCE.read_text(encoding="utf-8"),
        )

        if stage_shared_sdk:
            sdk_stage = proj / "sdk_stage"
            if sdk_stage.exists():
                _rmtree_force(sdk_stage)
            fu_sdk_src = WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk"
            if fu_sdk_src.is_dir():
                shutil.copytree(fu_sdk_src, sdk_stage / "fu_sdk")
            fu_rt_src = WORKSPACE_ROOT / "shared" / "sdk" / "fu_runtime"
            if fu_rt_src.is_dir():
                shutil.copytree(fu_rt_src, sdk_stage / "fu_runtime")

        # Refresh Godot global script class cache cleanly via `--headless --quit` if shims exist
        # Godot 4 automatically scans class_name scripts when `--editor` or normal project open runs,
        # or we can generate `.godot/global_script_class_cache.cfg` directly!
        self._write_shim_class_cache(proj)
        self.staged = True
        return proj

    def _write_shim_class_cache(self, proj: Path) -> None:
        """Write `.godot/global_script_class_cache.cfg` so headless `--script` resolves host shim `class_name`s without `--editor`."""
        entries = [
            ("HookIds", "RefCounted", "res://fus_host_shims/hook_ids.gd"),
            ("ExtToken", "RefCounted", "res://fus_host_shims/token.gd"),
            ("DesktopNetworkSession", "Node", "res://fus_host_shims/desktop_network_session.gd"),
            ("ExtensionContext", "RefCounted", "res://fus_host_shims/extension_context.gd"),
            ("ExtensionBase", "Node2D", "res://fus_host_shims/extension_base.gd"),
            ("CompBase", "ExtensionBase", "res://fus_host_shims/comp_base.gd"),
            ("CompPermission", "CompBase", "res://fus_host_shims/comp_permission.gd"),
            ("BoardToken", "Node2D", "res://fus_host_shims/board_token.gd"),
            ("EntityComponentPage", "VBoxContainer", "res://fus_host_shims/entity_component_page.gd"),
            ("EditModeController", "Node", "res://fus_host_shims/edit_mode_controller.gd"),
            ("SlotRegistry", "Node", "res://fus_host_shims/slot_registry.gd"),
        ]
        lines = ["list=["]
        for cls_name, base_name, res_path in entries:
            lines.extend([
                "{",
                f'"base": &"{base_name}",',
                f'"class": &"{cls_name}",',
                '"icon": "",',
                '"is_abstract": false,',
                '"is_tool": false,',
                '"language": &"GDScript",',
                f'"path": "{res_path}"',
                "},",
            ])
        lines.append("]")
        write_utf8_no_bom_lf(proj / ".godot" / "global_script_class_cache.cfg", "\n".join(lines) + "\n")

    def extract_fup_pck(self, fup_path: Path, target_name: str = "content.pck") -> Path:
        assert self.session.extracted_dir is not None
        out_dir = self.session.extracted_dir / f"{fup_path.stem}_{uuid.uuid4().hex[:6]}"
        safe_extract_zip(fup_path, out_dir)
        pck = out_dir / target_name
        if not pck.is_file():
            raise FileNotFoundError(f"{target_name} missing inside {fup_path}")
        return pck

    def _invoke_godot(
        self,
        sub_id: str,
        cases: list[ProbeCaseSpec],
        *,
        timeout_seconds: int,
    ) -> tuple[int, bool, dict[str, Any], str, str, str, Path]:
        assert self.session.run_dir is not None and self.session.probe_project is not None
        assert self.godot_bin is not None
        batch_dir = self.session.run_dir / "batches" / sub_id
        out_dir = batch_dir / "out"
        cases_dir = batch_dir / "cases"
        out_dir.mkdir(parents=True, exist_ok=True)
        cases_dir.mkdir(parents=True, exist_ok=True)

        payload_cases: list[dict[str, Any]] = []
        for c in cases:
            c_dir = cases_dir / c.case_id
            c_dir.mkdir(parents=True, exist_ok=True)
            payload_cases.append({
                "case_id": c.case_id,
                "op": c.op,
                "pack_path": c.pack_path,
                "sdk_root": c.sdk_root,
                "params": encode_special_inputs(dict(c.params)),
                "options": encode_special_inputs(dict(c.options)),
                "case_dir": c_dir.as_posix(),
            })

        batch_in_path = batch_dir / "batch_in.json"
        batch_out_path = batch_dir / "batch_out.json"
        godot_log_path = batch_dir / "godot.log"
        write_utf8_no_bom_lf(
            batch_in_path,
            json.dumps(
                {"out_dir": out_dir.as_posix(), "cases": payload_cases},
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
            )
            + "\n",
        )

        cmd = [
            str(self.godot_bin),
            "--headless",
            "--quit",
            "--path",
            str(self.session.probe_project),
            "--log-file",
            str(godot_log_path),
            "--script",
            "res://e2e_dual_mode_probe.gd",
            "--",
            f"--batch-in={batch_in_path.as_posix()}",
            f"--batch-out={batch_out_path.as_posix()}",
        ]

        timed_out = False
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.session.probe_project),
                env=self.session.child_env(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            exit_code = proc.returncode
            stdout_text = proc.stdout
            stderr_text = proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = 124
            stdout_text = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
            stderr_text = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")

        write_utf8_no_bom_lf(batch_dir / "stdout.log", stdout_text)
        write_utf8_no_bom_lf(batch_dir / "stderr.log", stderr_text)
        godot_log_text = godot_log_path.read_text(encoding="utf-8", errors="replace") if godot_log_path.is_file() else ""

        batch_summary: dict[str, Any] = {}
        if batch_out_path.is_file():
            try:
                parsed = json.loads(batch_out_path.read_text(encoding="utf-8-sig"))
                if isinstance(parsed, dict):
                    batch_summary = parsed
            except (OSError, ValueError):
                batch_summary = {}

        return exit_code, timed_out, batch_summary, stdout_text, stderr_text, godot_log_text, out_dir

    def run_batch(
        self,
        cases: list[ProbeCaseSpec],
        *,
        timeout_seconds: int = 120,
        _sub_counter: list[int] | None = None,
    ) -> ProbeBatchSummary:
        if not self.staged:
            self.prepare_probe_project()

        if _sub_counter is not None:
            batch_idx = _sub_counter[0]
            _sub_counter[0] += 1
        elif hasattr(self.session, "_e2e_batch_counter"):
            batch_idx = int(getattr(self.session, "_e2e_batch_counter"))
            setattr(self.session, "_e2e_batch_counter", batch_idx + 1)
        else:
            batch_idx = self._local_batch_counter
            self._local_batch_counter += 1
        sub_id = f"b{batch_idx:03d}"

        exit_code, timed_out, summary, stdout_text, stderr_text, godot_log_text, out_dir = self._invoke_godot(
            sub_id, cases, timeout_seconds=timeout_seconds
        )
        per_case_errors, global_errors = _attribute_logs_by_case(stdout_text, godot_log_text, stderr_text)

        loaded_scripts = [str(x) for x in summary.get("loaded_scripts", [])]
        compile_failures = [str(x) for x in summary.get("compile_failures", [])]

        results: dict[str, ProbeCaseResult] = {}
        incomplete: list[ProbeCaseSpec] = []

        for c in cases:
            out_file = out_dir / f"{c.case_id}.json"
            if out_file.is_file() and not timed_out:
                raw_payload = json.loads(out_file.read_text(encoding="utf-8-sig"))
                decoded = decode_gd_json(raw_payload)
                results[c.case_id] = ProbeCaseResult(
                    case_id=c.case_id,
                    completed=True,
                    crashed_or_timed_out=False,
                    ok=bool(decoded.get("ok", False)),
                    data=decoded.get("data", {}) if isinstance(decoded.get("data"), dict) else {},
                    gd_check_failures=[str(x) for x in decoded.get("gd_check_failures", [])],
                    log_errors=per_case_errors.get(c.case_id, []),
                    exit_code=exit_code,
                    timed_out=False,
                )
            else:
                incomplete.append(c)

        if incomplete:
            if len(cases) > 1:
                mid = max(1, len(incomplete) // 2)
                for half in (incomplete[:mid], incomplete[mid:]):
                    if not half:
                        continue
                    sub_res = self.run_batch(half, timeout_seconds=timeout_seconds, _sub_counter=_sub_counter)
                    results.update(sub_res.results)
                    if not loaded_scripts and sub_res.loaded_scripts:
                        loaded_scripts = sub_res.loaded_scripts
                    compile_failures.extend(x for x in sub_res.compile_failures if x not in compile_failures)
                    global_errors.extend(x for x in sub_res.global_log_errors if x not in global_errors)
            else:
                c = incomplete[0]
                c_errs = list(per_case_errors.get(c.case_id, []))
                c_errs.extend(x for x in global_errors if x not in c_errs)
                results[c.case_id] = ProbeCaseResult(
                    case_id=c.case_id,
                    completed=False,
                    crashed_or_timed_out=True,
                    ok=False,
                    data={},
                    gd_check_failures=[],
                    log_errors=c_errs,
                    exit_code=exit_code,
                    timed_out=timed_out,
                )

        for res in results.values():
            res.global_log_errors = list(global_errors)
            res.compile_failures = list(compile_failures)

        return ProbeBatchSummary(
            loaded_scripts=loaded_scripts,
            compile_failures=compile_failures,
            global_log_errors=global_errors,
            results=results,
        )


class FUSBuildParityRunner:
    """Runs a read-only copy of `<FUS_REPO_DIR>/tools/build_world_plugin.gd` inside isolated `probe_project/`."""

    def __init__(self, session: E2ESession) -> None:
        self.session = session
        self._local_parity_counter: int = 0

    def run_build_world_plugin(self, source_dir: Path, out_dir: Path, *, timeout_seconds: int = 120) -> dict[str, Any]:
        assert self.session.run_dir is not None
        fus_repo = resolve_fus_repo_or_skip(self.session.cfg)
        godot_bin = resolve_godot_or_skip(self.session.cfg)

        src_script = fus_repo / "tools" / "build_world_plugin.gd"
        if not src_script.is_file():
            raise unittest.SkipTest("tools/build_world_plugin.gd missing in FUS_REPO_DIR")

        if hasattr(self.session, "_e2e_parity_counter"):
            parity_idx = int(getattr(self.session, "_e2e_parity_counter"))
            setattr(self.session, "_e2e_parity_counter", parity_idx + 1)
        else:
            parity_idx = self._local_parity_counter
            self._local_parity_counter += 1

        parity_proj = self.session.run_dir / "fus_parity_project"
        parity_proj.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)
        write_utf8_no_bom_lf(
            parity_proj / "project.godot",
            PROBE_PROJECT_GODOT.replace('config/name="FuVTT_VerifyHostProbe"', 'config/name="FuVTT_BuildParity"'),
        )
        write_utf8_no_bom_lf(parity_proj / "build_world_plugin.gd", src_script.read_text(encoding="utf-8"))
        run_log_dir = parity_proj / "runs" / f"p{parity_idx:03d}"
        run_log_dir.mkdir(parents=True, exist_ok=True)
        log_file = run_log_dir / "build_world_plugin.log"

        cmd = [
            str(godot_bin),
            "--headless",
            "--quit",
            "--path",
            str(parity_proj),
            "--log-file",
            str(log_file),
            "--script",
            "res://build_world_plugin.gd",
            "--",
            f"--source={source_dir.resolve().as_posix()}",
            f"--output={out_dir.resolve().as_posix()}",
        ]
        timed_out = False
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(parity_proj),
                env=self.session.child_env(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            returncode = proc.returncode
            raw_stdout = proc.stdout
            raw_stderr = proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            returncode = 124
            raw_stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
            raw_stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")

        log_text = log_file.read_text(encoding="utf-8", errors="replace") if log_file.is_file() else ""
        log_errors = analyze_godot_logs(raw_stdout, raw_stderr, log_text)
        if timed_out:
            log_errors.append(f"ERROR: build_world_plugin.gd timed out after {timeout_seconds}s")
        parsed: dict[str, Any] = {}
        for line in reversed(raw_stdout.splitlines()):
            s = line.strip()
            if s.startswith("{") and s.endswith("}"):
                try:
                    obj = json.loads(s)
                    if isinstance(obj, dict):
                        parsed = obj
                        break
                except ValueError:
                    pass
        return {
            "returncode": returncode,
            "result": parsed,
            "stdout": self.session.cfg.redact_path(raw_stdout),
            "stderr": self.session.cfg.redact_path(raw_stderr),
            "log_errors": log_errors,
            "log_file": log_file,
        }


class FUSShadowMirrorRunner:
    """Maintains a cached `.cache/fus_host_mirror/<short_sha>/` copy of `<FUS_REPO_DIR>` for real host-load tests."""

    def __init__(self, session: E2ESession) -> None:
        self.session = session

    def ensure_mirror_ready(self, *, timeout_seconds: int = 300) -> Path:
        fus_repo = resolve_fus_repo_or_skip(self.session.cfg)
        godot_bin = resolve_godot_or_skip(self.session.cfg)

        require_mirror = os.environ.get("FUVTT_E2E_REQUIRE_FUS_MIRROR") == "1"
        dotnet_exe = shutil.which("dotnet")
        if not dotnet_exe:
            if require_mirror:
                raise AssertionError("FUVTT_E2E_REQUIRE_FUS_MIRROR=1 but `dotnet` CLI not found on PATH.")
            raise unittest.SkipTest("dotnet CLI not found on PATH")

        head_proc = run_git_readonly(["rev-parse", "--short=8", "HEAD"], repo_dir=fus_repo)
        if head_proc.returncode != 0 or not head_proc.stdout.strip():
            raise RuntimeError(f"Failed to resolve FUS HEAD sha: {head_proc.stderr}")
        short_sha = head_proc.stdout.strip()

        mirror_root = WORKSPACE_ROOT / ".cache" / "fus_host_mirror" / short_sha
        marker = mirror_root / ".mirror_ready.json"
        if marker.is_file():
            try:
                meta = json.loads(marker.read_text(encoding="utf-8"))
                if meta.get("sha") == short_sha and meta.get("imported") is True and (mirror_root / ".godot").is_dir():
                    return mirror_root
            except (OSError, ValueError):
                pass

        if mirror_root.exists():
            _rmtree_force(mirror_root)
        mirror_root.mkdir(parents=True, exist_ok=True)

        def _ignore_filter(src: str, names: list[str]) -> set[str]:
            return {n for n in names if n in _MIRROR_EXCLUDE_DIRS}

        shutil.copytree(fus_repo, mirror_root, dirs_exist_ok=True, ignore=_ignore_filter)
        _clear_readonly_tree(mirror_root)

        dotnet_env_root = WORKSPACE_ROOT / ".cache" / "dotnet_env"
        cli_home = dotnet_env_root / "cli-home"
        nuget_dir = dotnet_env_root / "nuget"
        dotnet_tmp = dotnet_env_root / "temp"
        for d in (cli_home, nuget_dir, dotnet_tmp):
            d.mkdir(parents=True, exist_ok=True)

        build_env = self.session.child_env()
        build_env["DOTNET_CLI_HOME"] = str(cli_home)
        build_env["NUGET_PACKAGES"] = str(nuget_dir)
        build_env["TEMP"] = str(dotnet_tmp)
        build_env["TMP"] = str(dotnet_tmp)

        csproj = mirror_root / "Practice.csproj"
        if csproj.is_file():
            build_proc = subprocess.run(
                [dotnet_exe, "build", str(csproj), "--no-incremental", "-v", "minimal", "--disable-build-servers"],
                cwd=str(mirror_root),
                env=build_env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if build_proc.returncode != 0:
                raise AssertionError(
                    f"dotnet build Practice.csproj failed ({build_proc.returncode}): "
                    f"{self.session.cfg.redact_path(build_proc.stdout)}\n{self.session.cfg.redact_path(build_proc.stderr)}"
                )

        import_log = mirror_root / "import.log"
        imp_proc = subprocess.run(
            [
                str(godot_bin),
                "--headless",
                "--editor",
                "--import",
                "--path",
                str(mirror_root),
                "--log-file",
                str(import_log),
            ],
            cwd=str(mirror_root),
            env=self.session.child_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if imp_proc.returncode not in (0,):
            imp_text = import_log.read_text(encoding="utf-8", errors="replace") if import_log.is_file() else ""
            raise AssertionError(
                f"Godot --editor --import failed ({imp_proc.returncode}): {self.session.cfg.redact_path(imp_text[-2000:])}"
            )

        write_utf8_no_bom_lf(
            marker,
            json.dumps({"sha": short_sha, "imported": True}, indent=2) + "\n",
        )
        return mirror_root

    def run_host_probe(
        self,
        *,
        mode: str,
        zip_pkg: Path | None = None,
        fup_pkg: Path | None = None,
        v1_pkg: Path | None = None,
        extra_args: Sequence[str] = (),
        timeout_seconds: int = 180,
    ) -> dict[str, Any]:
        assert self.session.run_dir is not None
        godot_bin = resolve_godot_or_skip(self.session.cfg)
        mirror_root = self.ensure_mirror_ready()

        tests_dir = mirror_root / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        probe_dst = tests_dir / "check_fuvtt_forge_host_load.gd"
        write_utf8_no_bom_lf(probe_dst, FUS_HOST_PROBE_SOURCE.read_text(encoding="utf-8"))

        out_dir = self.session.run_dir / "fus_host_out" / f"{mode}_{uuid.uuid4().hex[:6]}"
        out_dir.mkdir(parents=True, exist_ok=True)
        log_file = out_dir / "fus_host.log"

        user_args = [
            f"--test-output={out_dir.resolve().as_posix()}",
            f"--suite-label=forge-{mode}",
            f"--mode={mode}",
        ]
        if zip_pkg is not None:
            user_args.append(f"--zip-pkg={zip_pkg.resolve().as_posix()}")
        if fup_pkg is not None:
            user_args.append(f"--fup-pkg={fup_pkg.resolve().as_posix()}")
        if v1_pkg is not None:
            user_args.append(f"--v1-pkg={v1_pkg.resolve().as_posix()}")
        user_args.extend(extra_args)

        cmd = [
            str(godot_bin),
            "--headless",
            "--max-fps",
            "120",
            "--path",
            str(mirror_root),
            "--script",
            "res://tests/check_fuvtt_forge_host_load.gd",
            "--quit-after",
            "24000",
            "--log-file",
            str(log_file),
            "--",
            *user_args,
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(mirror_root),
            env=self.session.child_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log_text = log_file.read_text(encoding="utf-8", errors="replace") if log_file.is_file() else ""
        log_errors = analyze_godot_logs(proc.stdout, proc.stderr, log_text)
        report_path = out_dir / "host_probe_report.json"
        if not report_path.is_file():
            report_path = out_dir / "report.json"
        report: dict[str, Any] = {}
        if report_path.is_file():
            try:
                parsed = json.loads(report_path.read_text(encoding="utf-8-sig"))
                if isinstance(parsed, dict):
                    report = parsed
            except (OSError, ValueError):
                report = {}

        ui_report: dict[str, Any] = {}
        ui_report_path = out_dir / "report.json"
        if ui_report_path.is_file():
            try:
                parsed_ui = json.loads(ui_report_path.read_text(encoding="utf-8-sig"))
                if isinstance(parsed_ui, dict):
                    ui_report = parsed_ui
            except (OSError, ValueError):
                ui_report = {}

        return {
            "returncode": proc.returncode,
            "report": report,
            "ui_report": ui_report,
            "log_errors": log_errors,
            "stdout": self.session.cfg.redact_path(proc.stdout),
            "stderr": self.session.cfg.redact_path(proc.stderr),
            "out_dir": out_dir,
        }
