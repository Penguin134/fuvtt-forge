"""Programmatic opaque-box fixture generators for v1, `fus.desktop-module.v1`, `fus.plugin.v2`, `hybrid`, and negative/boundary mods."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
import zipfile

from .harness import write_utf8_no_bom_lf


def _write_json(path: Path, data: Any) -> None:
    write_utf8_no_bom_lf(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def create_v1_session_plugin(
    mods_dir: Path,
    mod_name: str,
    *,
    plugin_id: str | None = None,
    version: str = "1.0.0",
    host_api: int = 1,
    scope: str = "session",
    extends_base: str = "RefCounted",
    bad_inspect_missing_unsupported: bool = False,
    bad_asset_url: bool = False,
) -> Path:
    pid = plugin_id or mod_name.replace("-", "_")
    mod_dir = mods_dir / mod_name
    mod_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        mod_dir / "plugin.json",
        {
            "schema": "fus.session-plugin.v1",
            "host_api": host_api,
            "scope": scope,
            "id": pid,
            "name": f"Fixture {pid}",
            "version": version,
            "description": "Synthetic v1 session plugin fixture.",
            "entry": "entry.gd",
            "import_extensions": ["fx1"],
            "action_label": "Import FX1",
            "settings": [
                {"id": "proxy", "type": "string", "label": "Proxy", "default": ""},
            ],
        },
    )
    counts_entries = [
        '"records": 1',
        '"images": 1',
        '"selected_images": 1',
        '"maps": 1',
        '"characters": 0',
        '"objects": 0',
        '"text": 0',
        '"drawings": 0',
        '"walls": 0',
        '"doors": 0',
        '"hidden": 0',
    ]
    if not bad_inspect_missing_unsupported:
        counts_entries.append('"unsupported": 0')
    counts_block = "{" + ", ".join(counts_entries) + "}"
    asset_url = "ftp://example.invalid/bad.png" if bad_asset_url else "https://example.invalid/ok.png"
    entry_code = f"""extends {extends_base}

const _SDK_REL := "lib/fu_sdk/v1.gd"

func inspect_import(path: String, _options: Dictionary, _host: Variant) -> Dictionary:
\tvar sha: String = FileAccess.get_sha256(path) if (not path.is_empty() and FileAccess.file_exists(path)) else ""
\tvar src_bytes: int = FileAccess.get_file_as_bytes(path).size() if (not path.is_empty() and FileAccess.file_exists(path)) else 0
\tvar counts: Dictionary = {counts_block}
\treturn {{
\t\t"ok": true,
\t\t"name": path.get_file() if not path.is_empty() else "fixture.fx1",
\t\t"source_bytes": src_bytes,
\t\t"decoded_bytes": src_bytes,
\t\t"unique_images": 1,
\t\t"sha256": sha,
\t\t"summary": "fixture inspect",
\t\t"counts": counts,
\t\t"assets": {{"{asset_url}": 65536}},
\t}}

func prepare_import(_path: String, _options: Dictionary, host: Variant) -> Dictionary:
\tvar counts: Dictionary = {counts_block}
\tif host != null and host.has_method(&"empty_world"):
\t\tvar w: Dictionary = host.call(&"empty_world")
\t\tif bool(w.get("ok", false)):
\t\t\treturn {{"ok": true, "world": w.get("data", {{}}), "counts": counts, "warnings": []}}
\treturn {{"ok": false, "reason": "empty_world_failed"}}
"""
    write_utf8_no_bom_lf(mod_dir / "entry.gd", entry_code)
    return mod_dir


def create_desktop_module_fixture(
    mods_dir: Path,
    mod_name: str,
    *,
    plugin_id: str | None = None,
    module_id: str | None = None,
    version: str = "1.0.0",
    host_api: int = 2,
    scope: str = "desktop",
    ns_dir: str = "mods",
    use_plural_modules: bool = False,
    omit_settings: bool = False,
    local_only: bool = True,
    network_version: int = 0,
    pack_file: str | None = None,
    entry_scene_override: str | None = None,
    include_extra_non_ns_file: bool = False,
    use_fu_runtime: bool = True,
    hybrid_entry: bool = False,
) -> Path:
    pid = plugin_id or mod_name.replace("-", "_")
    mid = module_id or f"mod.{pid}"
    mod_dir = mods_dir / mod_name
    ns_root = mod_dir / ns_dir / pid
    ns_root.mkdir(parents=True, exist_ok=True)

    entry_scene = entry_scene_override or f"res://{ns_dir}/{pid}/module.tscn"
    module_def: dict[str, Any] = {
        "id": mid,
        "display_name": f"Desktop {pid}",
        "entry_scene": entry_scene,
        "version": 1,
        "network_version": network_version,
        "local_only": local_only,
        "isolated_lifecycle": True,
        "requires": [],
        "conflicts": [],
        "description": "Synthetic desktop-module fixture.",
        "disable_effect": "Cleanly removes overlays and nodes.",
    }
    manifest: dict[str, Any] = {
        "schema": "fus.desktop-module.v1",
        "host_api": host_api,
        "scope": scope,
        "id": pid,
        "version": version,
        "name": f"Desktop Mod {pid}",
        "description": "Synthetic fus.desktop-module.v1 fixture.",
    }
    if pack_file is not None:
        manifest["pack_file"] = pack_file
    if use_plural_modules:
        manifest["modules"] = [module_def]
    else:
        manifest["module"] = module_def
    if not omit_settings:
        manifest["settings"] = [
            {"id": "enable_fx", "type": "bool", "label": "Enable FX", "default": True},
        ]
    if hybrid_entry:
        manifest["import_extensions"] = ["fxh"]
        manifest["entry"] = "entry.gd"
        manifest["action_label"] = f"Import {pid} FXH"

    _write_json(mod_dir / "plugin.json", manifest)

    sdk_loader_block = ""
    if use_fu_runtime:
        sdk_loader_block = f"""
func _load_runtime_sdk() -> RefCounted:
\tvar self_scr := get_script() as Script
\tvar base_dir := self_scr.resource_path.get_base_dir()
\tvar rt_path := base_dir.path_join("lib/fu_runtime/v2.gd")
\tif ResourceLoader.exists(rt_path) or FileAccess.file_exists(rt_path):
\t\tvar rt_scr := load(rt_path) as Script
\t\tif rt_scr != null:
\t\t\treturn rt_scr.new()
\treturn null
"""

    module_gd = f"""extends ExtensionBase

const PLUGIN_ID := "{pid}"
const MODULE_ID := "{mid}"
const SERVICE_ID := "{pid}.service"
const CUSTOM_HOOK := &"mod.{pid}.burst"

var _api: Object = null
var _rt_sdk: RefCounted = null
var _event_log: Array[Dictionary] = []
var _banner: CanvasLayer = null
var _overlay: Node2D = null
{sdk_loader_block}
func _on_register(context: ExtensionContext) -> void:
\t_api = context.consume_service("desktop_api")
\tcontext.publish_service(SERVICE_ID, self)
\t{"_rt_sdk = _load_runtime_sdk()" if use_fu_runtime else ""}
\t_overlay = Node2D.new()
\t_overlay.name = "FxShockwaveOverlay"
\tcontext.register_slot_item(&"world.overlays", {{
\t\t"id": "{mid}.overlay",
\t\t"band": "above_entities",
\t\t"priority": 50,
\t\t"node": _overlay,
\t}})
\tvar desktop: Node = _api.call(&"get_desktop") as Node if _api != null else (context.runtime_node().get_desktop() if context.runtime_node() != null else null)
\tif is_instance_valid(desktop):
\t\t_banner = CanvasLayer.new()
\t\t_banner.name = "FxBannerLayer_{pid}"
\t\tcontext.mount_node(desktop, _banner)
\tcontext.subscribe_hook(&"dice.rolled", _on_dice_rolled)
\tcontext.subscribe_hook(&"vitals.downed", _on_vitals_downed)
\tcontext.subscribe_hook(CUSTOM_HOOK, _on_custom_burst)

func _on_unregister() -> void:
\t_event_log.clear()
\t_banner = null
\t_overlay = null
\t_rt_sdk = null
\t_api = null

func _on_dice_rolled(payload: Dictionary) -> void:
\t_event_log.append({{"hook": "dice.rolled", "payload": payload}})

func _on_vitals_downed(payload: Dictionary) -> void:
\t_event_log.append({{"hook": "vitals.downed", "payload": payload}})

func _on_custom_burst(payload: Dictionary) -> void:
\t_event_log.append({{"hook": String(CUSTOM_HOOK), "payload": payload}})

func emit_custom_burst(label: String) -> bool:
\tif ctx == null or not ctx.is_active():
\t\treturn false
\treturn ctx.emit_hook(CUSTOM_HOOK, [{{"label": label, "plugin_id": PLUGIN_ID}}])

func get_event_log() -> Array[Dictionary]:
\treturn _event_log.duplicate(true)

func get_runtime_sdk() -> RefCounted:
\treturn _rt_sdk
"""
    write_utf8_no_bom_lf(ns_root / "module.gd", module_gd)
    write_utf8_no_bom_lf(
        ns_root / "module.tscn",
        f"""[gd_scene format=3]

[ext_resource type="Script" path="res://{ns_dir}/{pid}/module.gd" id="1"]

[node name="Feature_{pid}" type="Node2D"]
script = ExtResource("1")
""",
    )
    if hybrid_entry:
        hybrid_entry_gd = """extends RefCounted

func inspect_import(path: String, _options: Dictionary, _host: Variant) -> Dictionary:
\tvar sha: String = FileAccess.get_sha256(path) if (not path.is_empty() and FileAccess.file_exists(path)) else ""
\tvar src_bytes: int = FileAccess.get_file_as_bytes(path).size() if (not path.is_empty() and FileAccess.file_exists(path)) else 0
\treturn {
\t\t"ok": true,
\t\t"name": path.get_file() if not path.is_empty() else "hybrid.fxh",
\t\t"source_bytes": src_bytes,
\t\t"decoded_bytes": src_bytes,
\t\t"unique_images": 0,
\t\t"sha256": sha,
\t\t"summary": "hybrid desktop-module inspect",
\t\t"counts": {"records": 1, "images": 0, "selected_images": 0, "maps": 0, "characters": 0, "objects": 0, "text": 0, "drawings": 0, "walls": 0, "doors": 0, "hidden": 0, "unsupported": 0},
\t\t"assets": {},
\t}

func prepare_import(_path: String, _options: Dictionary, host: Variant) -> Dictionary:
\tvar counts := {"records": 1, "images": 0, "selected_images": 0, "maps": 0, "characters": 0, "objects": 0, "text": 0, "drawings": 0, "walls": 0, "doors": 0, "hidden": 0, "unsupported": 0}
\tif host != null and host.has_method(&"empty_world"):
\t\tvar w: Dictionary = host.call(&"empty_world")
\t\tif bool(w.get("ok", false)):
\t\t\treturn {"ok": true, "world": w.get("data", {}), "counts": counts, "warnings": []}
\treturn {"ok": false, "reason": "empty_world_failed"}
"""
        write_utf8_no_bom_lf(mod_dir / "entry.gd", hybrid_entry_gd)
    if include_extra_non_ns_file:
        write_utf8_no_bom_lf(mod_dir / "README.md", "# Non-namespace readme\n")
    return mod_dir


def create_world_plugin_fixture(
    mods_dir: Path,
    mod_name: str,
    *,
    plugin_id: str | None = None,
    module_id: str | None = None,
    version: str = "1.0.0",
    host_api: int = 2,
    scope: str = "world",
    ns_dir: str = "external_modules",
    pack_file: str | None = "content.pck",
    local_only: bool = False,
    network_version: int | None = 1,
    slot_module_id_override: str | None = None,
    comp_filename_override: str | None = None,
    comp_id_override: str | None = None,
    omit_public_state: bool = False,
    bad_page_base: bool = False,
    bad_mode_on_enter_null: bool = False,
    bad_action_id_no_dot: bool = False,
    module_count: int = 1,
) -> Path:
    pid = plugin_id or mod_name.replace("-", "_")
    mid = module_id or f"{pid}.core"
    slot_mid = slot_module_id_override or mid
    comp_id = comp_id_override or f"{pid}__emitter"
    comp_fname = comp_filename_override or f"comp_{comp_id}.gd"

    mod_dir = mods_dir / mod_name
    ns_root = mod_dir / ns_dir / pid
    ns_root.mkdir(parents=True, exist_ok=True)

    modules_list: list[dict[str, Any]] = []
    for idx in range(module_count):
        m_id = mid if idx == 0 else f"{pid}.sub_{idx}"
        m_def: dict[str, Any] = {
            "id": m_id,
            "display_name": f"World {m_id}",
            "entry_scene": f"res://{ns_dir}/{pid}/feature_{pid}.tscn",
            "version": 1,
            "local_only": local_only,
            "isolated_lifecycle": True,
            "requires": [],
            "conflicts": [],
            "description": "Synthetic fus.plugin.v2 world module.",
            "disable_effect": "Parks components cleanly.",
        }
        if network_version is not None:
            m_def["network_version"] = network_version
        modules_list.append(m_def)

    manifest: dict[str, Any] = {
        "schema": "fus.plugin.v2",
        "host_api": host_api,
        "scope": scope,
        "min_host_version": "0.0.64",
        "id": pid,
        "version": version,
        "name": f"World Plugin {pid}",
        "author": "E2E Fixture",
        "description": "Synthetic fus.plugin.v2 fixture.",
        "capabilities": ["world_modules"],
        "permissions": [],
        "modules": modules_list,
        "settings": [
            {"id": "cell_feet", "type": "string", "label": "Feet per cell", "default": "5"},
        ],
    }
    if pack_file is not None:
        manifest["pack_file"] = pack_file
    _write_json(mod_dir / "plugin.json", manifest)

    # 1. CompBase script & scene
    public_state_fn = "" if omit_public_state else """
func public_state(state: Dictionary, peer: int) -> Dictionary:
\tvar secret: bool = bool(state.get("dm_secret", dm_secret))
\tif secret and peer > 1:
\t\tvar token: BoardToken = get_parent() as BoardToken
\t\tvar perm: CompPermission = token.get_component_by_id("permission") as CompPermission if token != null else null
\t\tif perm == null or not perm.can_command(peer):
\t\t\treturn {}
\treturn {
\t\t"schema_version": 1,
\t\t"radius_cells": clampi(int(state.get("radius_cells", radius_cells)), 1, 24),
\t\t"aura_title": String(state.get("aura_title", aura_title)).strip_edges().left(32),
\t\t"dm_secret": secret,
\t}
"""
    comp_gd = f"""extends CompBase

signal aura_changed

const SCHEMA_VERSION := 1
const PAGE_SCENE_PATH := "res://{ns_dir}/{pid}/comp_page.tscn"

@export var schema_version := SCHEMA_VERSION
@export var radius_cells := 2
@export var aura_title := "Guard Aura"
@export var dm_secret := false

func editable_fields() -> Array[String]:
\treturn ["radius_cells", "aura_title", "dm_secret"]

func component_tags() -> PackedStringArray:
\treturn PackedStringArray(["unit_trait", "aura"])

func get_comp_page_scene() -> String:
\treturn PAGE_SCENE_PATH

func accepts_state(state: Dictionary) -> bool:
\tif not super.accepts_state(state):
\t\treturn false
\tvar cells: Variant = state.get("radius_cells", 2)
\treturn (cells is int or cells is float) and int(cells) >= 1 and int(cells) <= 24

func apply_state(state: Dictionary) -> bool:
\tif not super.apply_state(state):
\t\treturn false
\taura_changed.emit()
\treturn true
{public_state_fn}
"""
    write_utf8_no_bom_lf(ns_root / comp_fname, comp_gd)
    write_utf8_no_bom_lf(
        ns_root / f"comp_{comp_id}.tscn",
        f"""[gd_scene format=3]

[ext_resource type="Script" path="res://{ns_dir}/{pid}/{comp_fname}" id="1"]

[node name="Comp_{comp_id}" type="Node2D"]
script = ExtResource("1")
""",
    )

    # 2. EntityComponentPage scene & script
    page_base = "Node" if bad_page_base else "EntityComponentPage"
    page_node_type = "Node" if bad_page_base else "VBoxContainer"
    if bad_page_base:
        emit_block = "\tpass"
    else:
        emit_block = f"""\tif _targets.is_empty():
\t\treturn
\tvar comps: Array[CompBase] = []
\tvar before: Array = []
\tfor t: BoardToken in _targets:
\t\tvar c := t.get_component_by_id("{comp_id}")
\t\tif c != null:
\t\t\tcomps.append(c)
\t\t\tbefore.append(int(c.get("radius_cells")))
\tif comps.is_empty():
\t\treturn
\tediting_started.emit()
\tedit_requested.emit(&"field", {{
\t\t"targets": _targets.duplicate(),
\t\t"components": comps,
\t\t"field": "radius_cells",
\t\t"before": before,
\t\t"value": next_val,
\t}})"""
    write_utf8_no_bom_lf(
        ns_root / "comp_page.gd",
        f"""extends {page_base}

var _targets: Array[BoardToken] = []
var _last_bound_count: int = 0

func bind_entities(entities: Array[BoardToken]) -> void:
\t_targets = entities.duplicate()
\t_last_bound_count = _targets.size()
\trefresh()

func refresh() -> void:
\tpass

func emit_radius_edit(_next_val: int) -> void:
{emit_block}
""".replace("emit_radius_edit(_next_val: int)" if not bad_page_base else "NOOP_KEEP_NEXT_VAL", "emit_radius_edit(next_val: int)"),
    )
    write_utf8_no_bom_lf(
        ns_root / "comp_page.tscn",
        f"""[gd_scene format=3]

[ext_resource type="Script" path="res://{ns_dir}/{pid}/comp_page.gd" id="1"]

[node name="CompPage" type="{page_node_type}"]
script = ExtResource("1")
""",
    )

    # 3. Sidebar & Settings UI panels
    write_utf8_no_bom_lf(
        ns_root / "sidebar_panel.gd",
        """extends PanelContainer

var _provider: Variant = null
var _active: bool = false

func bind_provider(provider: Variant) -> bool:
\tif not is_instance_valid(provider):
\t\treturn false
\t_provider = provider
\treturn true

func activate() -> void:
\t_active = true

func deactivate() -> void:
\t_active = false
""",
    )
    write_utf8_no_bom_lf(
        ns_root / "sidebar_panel.tscn",
        f"""[gd_scene format=3]

[ext_resource type="Script" path="res://{ns_dir}/{pid}/sidebar_panel.gd" id="1"]

[node name="SidebarPanel" type="PanelContainer"]
script = ExtResource("1")
""",
    )
    write_utf8_no_bom_lf(
        ns_root / "settings_page.gd",
        """extends VBoxContainer

var _provider: Variant = null
var _editable: bool = true

func bind_provider(provider: Variant) -> bool:
\tif not is_instance_valid(provider):
\t\treturn false
\t_provider = provider
\trefresh()
\treturn true

func refresh() -> void:
\tif is_instance_valid(_provider) and _provider.has_method(&"can_author_world"):
\t\t_editable = bool(_provider.call(&"can_author_world"))

func deactivate() -> void:
\t_provider = null
""",
    )
    write_utf8_no_bom_lf(
        ns_root / "settings_page.tscn",
        f"""[gd_scene format=3]

[ext_resource type="Script" path="res://{ns_dir}/{pid}/settings_page.gd" id="1"]

[node name="SettingsPage" type="VBoxContainer"]
script = ExtResource("1")
""",
    )

    # 4. World overlay & feature entry script
    mode_on_enter_body = "pass" if bad_mode_on_enter_null else "return true"
    action_id = f"{pid}_toggle" if bad_action_id_no_dot else f"{pid}.toggle"
    feature_gd = f"""extends ExtensionBase

signal auras_changed
signal projection_changed(peer: int)

const PLUGIN_ID := "{pid}"
const MODULE_ID := "{mid}"
const SERVICE_ID := "{pid}.service"
const COMP_ID := "{comp_id}"
const COMP_PATH := "res://{ns_dir}/{pid}/{comp_fname}"
const COMP_SCENE_PATH := "res://{ns_dir}/{pid}/comp_{comp_id}.tscn"
const SIDEBAR_SCENE_PATH := "res://{ns_dir}/{pid}/sidebar_panel.tscn"
const SETTINGS_SCENE_PATH := "res://{ns_dir}/{pid}/settings_page.tscn"

var _desktop: Node = null
var _sync: Variant = null
var _cell_feet: int = 5
var _show_labels: bool = true
var _projection_rev: int = 1
var _replica_payload: Dictionary = {{}}
var _custom_node: Node2D = null
var _mode_active: bool = false

func _on_register(context: ExtensionContext) -> void:
\tset_meta(&"module_id", MODULE_ID)
\tvar rt := context.runtime_node()
\t_desktop = rt.get_desktop() if rt != null and rt.has_method(&"get_desktop") else null
\t_sync = context.consume_service("component_sync")
\tcontext.publish_service(SERVICE_ID, self)
\tvar comp_scene := load(COMP_SCENE_PATH) as PackedScene
\tcontext.register_component({{
\t\t"id": COMP_ID,
\t\t"path": COMP_PATH,
\t\t"scene": comp_scene,
\t\t"version": 1,
\t\t"label": "Aura",
\t\t"network_scope": "shared",
\t\t"library_visible": true,
\t\t"entity_local_membership": true,
\t}})
\tcontext.register_slot_item(&"network.actions", {{"id": "{slot_mid}"}})
\tcontext.register_slot_item(&"network.projections", {{
\t\t"id": "{slot_mid}",
\t\t"replica_presentation_only": true,
\t}})
\tcontext.register_slot_item(&"ui.desktop_panels", {{
\t\t"id": "{pid}.panel",
\t\t"label": "Aura Panel",
\t\t"scene": load(SIDEBAR_SCENE_PATH),
\t\t"provider": self,
\t\t"priority": 18,
\t\t"dm_only": false,
\t}})
\tcontext.register_slot_item(&"ui.module_settings", {{
\t\t"id": "{pid}.settings",
\t\t"label": "Aura Settings",
\t\t"scene": load(SETTINGS_SCENE_PATH),
\t\t"provider": self,
\t\t"priority": 18,
\t\t"dm_only": false,
\t}})
\tcontext.register_slot_item(&"ui.mode_bar", {{
\t\t"id": "{pid}.inspect",
\t\t"label": "Inspect Aura",
\t\t"priority": -40,
\t\t"predicate": func(_d: Node) -> bool: return true,
\t\t"on_enter": _on_mode_enter,
\t\t"on_exit": _on_mode_exit,
\t}})
\tcontext.register_slot_item(&"ui.entity_actions", {{
\t\t"id": "{action_id}",
\t\t"label": "Toggle Aura",
\t\t"priority": 36,
\t\t"dm_only": true,
\t\t"surfaces": ["action_bar", "context_wheel"],
\t\t"wheel_ring": 0,
\t\t"wheel_slot": 1,
\t\t"predicate": func(_d: Node, targets: Array) -> bool: return not targets.is_empty(),
\t\t"presentation": func(_d: Node, _targets: Array) -> Dictionary: return {{"label": "Toggle Aura", "enabled": true}},
\t\t"execute": func(_d: Node, _targets: Array) -> bool: return true,
\t}})
\tcontext.register_slot_item(&"world.overlays", {{
\t\t"id": "{pid}.ground_halo",
\t\t"band": "below_entities",
\t\t"priority": 20,
\t\t"factory": func() -> Node2D:
\t\t\tvar n := Node2D.new()
\t\t\tn.name = "GroundHalo"
\t\t\treturn n,
\t}})
\tif is_instance_valid(_desktop):
\t\tvar world_node := _desktop.get_node_or_null("World")
\t\tif world_node != null:
\t\t\t_custom_node = Node2D.new()
\t\t\t_custom_node.name = "CustomFreeNode_{pid}"
\t\t\tcontext.mount_node(world_node, _custom_node)

func _on_unregister() -> void:
\t_custom_node = null
\t_desktop = null
\t_sync = null
\t_replica_payload.clear()

func _on_mode_enter(_desk: Node):
\t_mode_active = true
\t{mode_on_enter_body}

func _on_mode_exit(_desk: Node) -> void:
\t_mode_active = false

func can_author_world() -> bool:
\treturn is_instance_valid(_desktop) and _desktop.has_method(&"can_author_world") and bool(_desktop.call(&"can_author_world"))

func get_module_settings() -> Dictionary:
\treturn {{"cell_feet": _cell_feet, "show_labels": _show_labels}}

func prepare_module_state(state: Dictionary) -> Dictionary:
\tif state.is_empty():
\t\treturn {{"ok": true, "data": {{"version": 1, "cell_feet": 5, "show_labels": true}}}}
\tif int(state.get("version", 0)) != 1:
\t\treturn {{"ok": false, "reason": "unsupported_version"}}
\tvar ft: Variant = state.get("cell_feet", 5)
\tvar sl: Variant = state.get("show_labels", true)
\tif not (ft is int or ft is float) or int(ft) < 1 or int(ft) > 100 or not (sl is bool):
\t\treturn {{"ok": false, "reason": "invalid_fields"}}
\treturn {{"ok": true, "data": {{"version": 1, "cell_feet": int(ft), "show_labels": bool(sl)}}}}

func apply_module_state(state: Dictionary) -> bool:
\tvar prep := prepare_module_state(state)
\tif not bool(prep.get("ok", false)):
\t\treturn false
\tvar d := prep["data"] as Dictionary
\t_cell_feet = int(d["cell_feet"])
\t_show_labels = bool(d["show_labels"])
\t_projection_rev += 1
\treturn true

func serialize_module_state() -> Dictionary:
\treturn {{"version": 1, "cell_feet": _cell_feet, "show_labels": _show_labels}}

func persistent_state_revision() -> int:
\treturn _projection_rev

func network_action_valid(payload: Variant) -> bool:
\treturn payload is Dictionary and (payload as Dictionary).get("op") == "set_radius" and int((payload as Dictionary).get("radius_cells", 0)) >= 1

func network_action_revoked(peer: int, payload: Dictionary) -> String:
\tif not network_action_valid(payload):
\t\treturn "invalid_action"
\tif peer > 1 and not bool(payload.get("commanded", false)):
\t\treturn "permission_denied"
\treturn ""

func network_request(peer: int, payload: Dictionary) -> Dictionary:
\tvar reason := network_action_revoked(peer, payload)
\tif not reason.is_empty():
\t\treturn {{"ok": false, "reason": reason}}
\t_projection_rev += 1
\tprojection_changed.emit(peer)
\treturn {{"ok": true, "reason": "", "history": _projection_rev}}

func network_projection(_peer: int, _confirmed: Dictionary, _reset: bool) -> Dictionary:
\treturn {{"version": 1, "revision": _projection_rev, "settings": serialize_module_state()}}

func network_cursor(payload: Dictionary) -> Dictionary:
\treturn {{"version": 1, "revision": int(payload.get("revision", 0))}}

func network_revoked(peer: int, cursor: Dictionary) -> bool:
\treturn peer <= 0 or int(cursor.get("revision", -1)) != _projection_rev

func validate_replica_projection(payload: Dictionary, _writer: Variant) -> Dictionary:
\tvar ok: bool = payload.has("settings") and bool(prepare_module_state(payload.get("settings", {{}})).get("ok", false))
\treturn {{"ok": ok, "data": payload.duplicate(true) if ok else {{}}}}

func capture_replica_projection() -> Dictionary:
\treturn _replica_payload.duplicate(true)

func _owns_projection(writer: Variant) -> bool:
\treturn (
\t\tctx != null
\t\tand ctx.is_active()
\t\tand writer != null
\t\tand is_instance_valid(writer)
\t\tand _sync != null
\t\tand writer == _sync
\t\tand writer.has_method(&"owns_module_projection_write")
\t\tand bool(writer.call(&"owns_module_projection_write", self))
\t)

func stage_replica_projection(payload: Dictionary, checked: Dictionary, writer: Variant) -> bool:
\tif not _owns_projection(writer) or not bool(checked.get("ok", false)):
\t\treturn false
\t_replica_payload = payload.duplicate(true)
\treturn true

func publish_replica_projection(writer: Variant) -> void:
\tif _owns_projection(writer) and not _replica_payload.is_empty():
\t\tapply_module_state(_replica_payload.get("settings", {{}}))

func restore_replica_projection(previous: Dictionary, writer: Variant) -> bool:
\tif not _owns_projection(writer):
\t\treturn false
\t_replica_payload = previous.duplicate(true)
\tif previous.is_empty():
\t\t_cell_feet = 5
\t\t_show_labels = true
\telse:
\t\tapply_module_state(previous.get("settings", {{}}))
\treturn true
"""
    write_utf8_no_bom_lf(ns_root / f"feature_{pid}.gd", feature_gd)
    write_utf8_no_bom_lf(
        ns_root / f"feature_{pid}.tscn",
        f"""[gd_scene format=3]

[ext_resource type="Script" path="res://{ns_dir}/{pid}/feature_{pid}.gd" id="1"]

[node name="Feature_{pid}" type="Node2D"]
script = ExtResource("1")
""",
    )
    return mod_dir


def corrupt_fup_pck(fup_path: Path, out_path: Path, *, bad_magic: bool = False, bad_sums: bool = False, missing_pck: bool = False) -> Path:
    """Create a mutated `.fup` archive for Tier 2 negative archive tests."""
    with zipfile.ZipFile(fup_path, "r") as zin, zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "content.pck":
                if missing_pck:
                    continue
                if bad_magic:
                    data = b"BAD!" + data[4:]
            elif info.filename == "SHA256SUMS.txt" and bad_sums:
                data = ("0" * 64 + "  content.pck\n").encode("utf-8")
            zout.writestr(info.filename, data)
    return out_path
