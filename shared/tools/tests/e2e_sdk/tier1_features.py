"""Tier 1: 150 Isolated Happy-Path E2E Feature Tests (5 per feature across Features #1-#30)."""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
import zipfile

from fuvtt_devtools.validator import validate_mod_dir

from .assertions import (
    EXPECTED_MODULAR_SDK_FILES,
    HEX8_COLOR_RE,
    UID_32_RE,
    assert_build_artifact_bundles_sdk,
    assert_case_passed,
    assert_entity_has_component,
    assert_gdscript_hygiene,
    assert_logbus_entry_schema,
    assert_no_local_paths_in_text,
    assert_r2_warning_present,
    assert_world_module_entry,
    assert_world_v3_invariants,
)
from .harness import (
    ALL_PLUGIN_SDK_IDS,
    CANDIDATE_MODULE_IDS,
    CORE_MODULE_IDS,
    E2ESession,
    GodotBatchProbe,
    OPTIONAL_MODULE_IDS,
    PLAYTEST_BLOCKED_MODULE_IDS,
    STATELESS_CORE_MODULE_IDS,
    STATELESS_OPTIONAL_MODULE_IDS,
    SdkBatchSummary,
    SdkProbeCaseSpec,
    TOOLS_DIR,
    WORKSPACE_ROOT,
    gd_color,
    gd_packed_f32,
    gd_packed_vec2,
    is_git_ignored,
    list_git_tracked,
    load_workspace_config,
    run_fuvtt_cli,
    run_git_readonly,
)


HEX32_A = "a" * 32
HEX32_B = "b" * 32
HEX32_C = "c" * 32
HEX64_A = "a" * 64
HEX24_A = "d" * 24
DEFAULT_FLOOR_UID = "33b819c3605991c4c63c2439af5f882c"
VALID_SFH2_BYTES = bytes.fromhex(
    "53464832" "3b000000"
    "a00310"
    "01000000" "04686f7374" "01000000"
    "206161616161616161616161616161616161616161616161616161616161616161"
    "01000000" "00000000" "00000000" "01"
    "03"
)


def _valid_drawing_state(*, with_text: bool = False, floor_uid: str = DEFAULT_FLOOR_UID) -> dict:
    strokes = [
        {
            "id": HEX32_A,
            "floor": floor_uid,
            "coords": "world",
            "tool": "round",
            "points": gd_packed_vec2([[0.0, 0.0], [64.0, 64.0]]),
            "pressure": gd_packed_f32([0.5, 0.8]),
            "color": gd_color(0.1, 0.2, 0.3, 1.0),
            "width": 4.0,
            "opacity": 0.9,
            "hardness": 0.8,
            "filled": False,
            "life": 0,
            "owner": "",
            "order": 1,
        }
    ]
    if with_text:
        strokes.append(
            {
                "id": HEX32_B,
                "floor": floor_uid,
                "coords": "world",
                "tool": "text",
                "points": gd_packed_vec2([[128.0, 128.0]]),
                "pressure": gd_packed_f32([1.0]),
                "color": gd_color(1.0, 1.0, 1.0, 1.0),
                "width": 24.0,
                "opacity": 1.0,
                "hardness": 1.0,
                "filled": False,
                "life": 0,
                "owner": "",
                "order": 2,
                "text": "Dragon Lair",
                "font": "sans",
                "font_size": 24,
            }
        )
    return {"version": 1, "visible": True, "strokes": strokes}


def _valid_entity_ink_stroke(*, stroke_id: str = HEX32_C, with_pressure: bool = True, erase: bool = False) -> dict:
    stroke: dict = {
        "id": stroke_id,
        "erase": erase,
        "color": gd_color(1.0, 0.0, 0.0, 1.0),
        "width": 0.05,
        "opacity": 1.0,
        "points": gd_packed_vec2([[0.1, 0.1], [0.5, 0.5]]),
    }
    if with_pressure:
        stroke["pressure"] = gd_packed_f32([1.0, 1.0])
    return stroke


def _valid_simple_fog_state(*, with_exploration: bool = False) -> dict:
    st: dict = {
        "version": 2,
        "unseen_color": [0.0, 0.0, 0.0, 1.0],
        "visible_tint": [1.0, 1.0, 1.0, 0.0],
        "history_color": [0.1, 0.1, 0.15, 0.7],
        "unseen_effect": 0,
        "visible_effect": 0,
        "history_effect": 1,
        "history_enabled": True,
        "dm_opacity": 0.45,
        "vision_threshold": 0.1,
        "vision_feather": 0.15,
        "shadow_filter": 1,
        "shadow_smooth": 4.0,
        "hide_unseen_entities": True,
    }
    if with_exploration:
        st["exploration"] = VALID_SFH2_BYTES
    return st


def _valid_checklist_state(*, audience: str = "all", player_id: str = "", done: bool = False, archived: bool = False, entity_id: str = "", more_entity_ids: list[str] | None = None) -> dict:
    row: dict = {
        "title": "Defeat Goblin Boss",
        "description": "Clear the cavern entrance.",
        "category": "Main Quest",
        "audience": audience,
        "player_id": player_id,
        "entity_id": entity_id,
        "source": "mod:test",
        "manual": False,
        "done": done,
        "archived": archived,
        "order": 1,
        "last_motion": "",
    }
    if more_entity_ids:
        row["more_entity_ids"] = more_entity_ids
    return {"schema": 2, "rows": {HEX32_A: row}}


def _valid_resource_pool_defs(*, display: str = "bar", visibility: str = "public") -> dict:
    return {
        "schema_version": 1,
        "definitions": {
            "resource_pool:hp": {
                "id": "resource_pool:hp",
                "source": "resource_pool",
                "name": "Hit Points",
                "maximum": 100.0,
                "color": "#CC2222FF",
                "display": display,
                "visibility": visibility,
            }
        },
    }


def _valid_initiative_state(phase: str = "idle") -> dict:
    if phase == "active":
        return {
            "schema": 2,
            "world_id": "world_e2e_1",
            "phase": "active",
            "members": [{"entity_id": HEX32_A, "tie_order": 0}],
            "current_id": HEX32_A,
            "round": 1,
            "generation": 1,
            "revision": 1,
            "settings": {"descending": True, "starting_round": 1, "show_bar": True},
        }
    return {
        "schema": 2,
        "world_id": "world_e2e_1",
        "phase": "idle",
        "members": [],
        "current_id": "",
        "round": 0,
        "generation": 1,
        "revision": 0,
        "settings": {"descending": True, "starting_round": 1, "show_bar": True},
    }


def _valid_dice_state(*, expr: str = "2d6+3", label: str = "", theme_id: str = "royal_ember_resin", visibility: str = "public") -> dict:
    return {
        "schema_version": 5,
        "history": {"schema": "fus.candidate.dice.history.v1", "world_id": "world_e2e_1", "records": []},
        "workspace": {
            "schema_version": 4,
            "simple_result": True,
            "animate": False,
            "combos": [{"id": HEX24_A, "name": "Attack", "expr": expr, "label": label}],
            "hidden_history_count": 0,
            "draft": "1d20",
            "visibility": visibility,
            "theme_id": theme_id,
        },
        "ownership": [],
        "archive": {},
    }


def _valid_campaign_time_state() -> dict:
    return {
        "minute": 720,
        "era": HEX32_A,
        "revision": 1,
        "sources": {HEX32_B: {"fingerprint": "torch_burn", "minute": 720}},
        "effects": {HEX32_B: {"until": 780, "name": "Torch", "status": "active"}},
    }


def _valid_dnd_opportunity_card(card_id: str = HEX32_A, card_edition: str = "2014") -> dict:
    form = {
        "name": "Hero",
        "job": "fighter",
        "race": "丘陵矮人",
        "background": "士兵",
        "source": "manual_total",
        "scores": [16, 10, 16, 10, 12, 8],
        "skills": ["特技", "察觉"],
        "replace": {},
        "expert": [],
        "enemy": "",
        "terrain": "",
    }
    return {
        "id": card_id,
        "edition": card_edition,
        "owner": "host",
        "access": True,
        "revision": 1,
        "birth": HEX64_A,
        "form": form,
        "steps": [],
        "prepared": [],
        "offered": 1,
        "entity": "",
        "work": [],
        "notes": {},
    }


def _valid_dnd_opportunity_state(edition: int = 2014) -> dict:
    return {
        "combined": 1,
        "sheets": {
            "schema": 1,
            "opportunity_edition": edition,
            "cards": {
                HEX32_A: _valid_dnd_opportunity_card(HEX32_A, "2014"),
            },
        },
        "encounter": {},
    }


class Tier1FeatureTests(unittest.TestCase):
    """150 isolated happy-path E2E tests covering Features #1-#30 (5 cases each)."""

    session: E2ESession
    batch: SdkBatchSummary
    _cases_built: bool = False

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = E2ESession(name_prefix="tier1")
        cls.session.setup(require_godot=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.session.cleanup()

    @classmethod
    def _ensure_godot_batch(cls) -> SdkBatchSummary:
        if cls._cases_built:
            return cls.batch
        probe = GodotBatchProbe(cls.session)
        probe.prepare_from_mod("_template", use_real_mods=True)

        cases: list[SdkProbeCaseSpec] = [
            # Feature #1: LogBus
            SdkProbeCaseSpec("t1_f01_01", "logbus_test", {"sub_op": "constants"}),
            SdkProbeCaseSpec("t1_f01_02", "logbus_test", {"sub_op": "emit_and_schema"}),
            SdkProbeCaseSpec("t1_f01_03", "logbus_test", {"sub_op": "query_and_clear"}),
            SdkProbeCaseSpec("t1_f01_04", "logbus_test", {"sub_op": "pubsub"}),
            SdkProbeCaseSpec("t1_f01_05", "logbus_test", {"sub_op": "session_builder_host"}),
            # Feature #2: ModuleRegistry
            SdkProbeCaseSpec(
                "t1_f02_01",
                "registry_inspect",
                {"action": "catalog", "query_ids": list(CORE_MODULE_IDS + OPTIONAL_MODULE_IDS + CANDIDATE_MODULE_IDS)},
            ),
            SdkProbeCaseSpec(
                "t1_f02_03",
                "registry_inspect",
                {"action": "catalog", "query_ids": ["simple_fog", "portal", "backpack"]},
                enabled_modules=["simple_fog", "portal", "backpack"],
            ),
            SdkProbeCaseSpec(
                "t1_f02_04",
                "plugin_domain",
                {"module_id": "grid_alignment", "cell_size": 64.0},
                enabled_modules=[],
                disabled_policy="preserve",
            ),
            SdkProbeCaseSpec(
                "t1_f02_05",
                "plugin_domain",
                {"module_id": "grid_alignment", "cell_size": 64.0},
                enabled_modules=[],
                disabled_policy="skip",
            ),
            # Feature #3: parked / manual
            SdkProbeCaseSpec("t1_f03_01", "parked_manual", {"sub_op": "unparked"}),
            SdkProbeCaseSpec("t1_f03_02", "parked_manual", {"sub_op": "parked_auto"}),
            SdkProbeCaseSpec("t1_f03_03", "parked_manual", {"sub_op": "parked_manual"}),
            SdkProbeCaseSpec(
                "t1_f03_04",
                "plugin_domain",
                {"module_id": "areas", "action": "attach", "as_unit": False, "state": {"removed": False, "radius_in_cells": 2.0}},
                enabled_modules=[],
                disabled_policy="preserve",
            ),
            # Feature #4: feature_edit_mode
            SdkProbeCaseSpec("t1_f04_01", "plugin_lifecycle", {"module_id": "feature_edit_mode"}),
            SdkProbeCaseSpec("t1_f04_02", "plugin_domain", {"module_id": "feature_edit_mode", "sub_op": "attach_unit"}),
            SdkProbeCaseSpec("t1_f04_03", "plugin_domain", {"module_id": "feature_edit_mode", "sub_op": "add_token"}),
            # Feature #5: feature_floor_system
            SdkProbeCaseSpec("t1_f05_01", "plugin_lifecycle", {"module_id": "feature_floor_system"}),
            SdkProbeCaseSpec("t1_f05_02", "plugin_domain", {"module_id": "feature_floor_system", "sub_op": "add_and_activate"}),
            SdkProbeCaseSpec("t1_f05_03", "plugin_domain", {"module_id": "feature_floor_system", "sub_op": "rename"}),
            SdkProbeCaseSpec("t1_f05_04", "plugin_domain", {"module_id": "feature_floor_system", "sub_op": "active_membership"}),
            # Feature #6: feature_layer_stack
            SdkProbeCaseSpec("t1_f06_01", "plugin_lifecycle", {"module_id": "feature_layer_stack"}),
            SdkProbeCaseSpec("t1_f06_03", "plugin_domain", {"module_id": "feature_layer_stack", "sub_op": "add_area_layer"}),
            SdkProbeCaseSpec("t1_f06_04", "plugin_domain", {"module_id": "feature_layer_stack", "sub_op": "players_layer_viewers"}),
            SdkProbeCaseSpec("t1_f06_05", "plugin_domain", {"module_id": "feature_layer_stack", "sub_op": "layer_override"}),
            # Feature #7: feature_obstacle_authoring
            SdkProbeCaseSpec("t1_f07_01", "plugin_lifecycle", {"module_id": "feature_obstacle_authoring"}),
            SdkProbeCaseSpec("t1_f07_02", "plugin_domain", {"module_id": "feature_obstacle_authoring", "sub_op": "wall_and_air"}),
            SdkProbeCaseSpec("t1_f07_03", "plugin_domain", {"module_id": "feature_obstacle_authoring", "sub_op": "door_window_glass"}),
            SdkProbeCaseSpec("t1_f07_04", "plugin_domain", {"module_id": "feature_obstacle_authoring", "sub_op": "segments"}),
            # Feature #8: feature_entity_library
            SdkProbeCaseSpec("t1_f08_01", "plugin_lifecycle", {"module_id": "feature_entity_library"}),
            SdkProbeCaseSpec("t1_f08_02", "plugin_domain", {"module_id": "feature_entity_library", "sub_op": "register_unit"}),
            SdkProbeCaseSpec("t1_f08_03", "plugin_domain", {"module_id": "feature_entity_library", "sub_op": "register_preset_enabled"}, enabled_modules=["simple_fog"]),
            SdkProbeCaseSpec("t1_f08_04", "plugin_domain", {"module_id": "feature_entity_library", "sub_op": "register_preset_disabled_warn"}, enabled_modules=[]),
            SdkProbeCaseSpec("t1_f08_05", "plugin_domain", {"module_id": "feature_entity_library", "sub_op": "template_and_validate_preset"}, enabled_modules=[]),
            # Feature #9: Stateless catalog
            SdkProbeCaseSpec("t1_f09_05", "registry_inspect", {"action": "toggle_and_disable_core", "core_id": "feature_networking", "opt_id": "backpack"}),
            # Feature #10: scene_box
            SdkProbeCaseSpec("t1_f10_01", "plugin_lifecycle", {"module_id": "scene_box"}, enabled_modules=["scene_box"]),
            SdkProbeCaseSpec("t1_f10_02", "plugin_domain", {"module_id": "scene_box", "sub_op": "scenes_v2"}, enabled_modules=["scene_box"]),
            SdkProbeCaseSpec("t1_f10_03", "plugin_domain", {"module_id": "scene_box", "sub_op": "scene_box_entity"}, enabled_modules=["scene_box"]),
            SdkProbeCaseSpec("t1_f10_04", "plugin_domain", {"module_id": "scene_box", "sub_op": "attach_and_view"}, enabled_modules=["scene_box"]),
            # Feature #11: portal
            SdkProbeCaseSpec("t1_f11_01", "plugin_lifecycle", {"module_id": "portal"}, enabled_modules=["portal"]),
            SdkProbeCaseSpec("t1_f11_02", "plugin_domain", {"module_id": "portal", "pair_key": HEX32_A}, enabled_modules=["portal"]),
            SdkProbeCaseSpec("t1_f11_03", "plugin_domain", {"module_id": "portal", "pair_key": "stairs_1f_2f"}, enabled_modules=["portal"]),
            SdkProbeCaseSpec("t1_f11_05", "plugin_domain", {"module_id": "portal", "pair_key": "stairs_disabled"}, enabled_modules=[], disabled_policy="preserve"),
            # Feature #12: grid_alignment
            SdkProbeCaseSpec("t1_f12_01", "plugin_lifecycle", {"module_id": "grid_alignment"}, enabled_modules=["grid_alignment"]),
            SdkProbeCaseSpec("t1_f12_02", "plugin_domain", {"module_id": "grid_alignment", "cell_size": 64.0}, enabled_modules=["grid_alignment"]),
            SdkProbeCaseSpec(
                "t1_f12_03",
                "plugin_domain",
                {
                    "module_id": "grid_alignment",
                    "via_plugin_sdk": True,
                    "cell_size": 128.0,
                    "snap_enabled": False,
                    "offset": [32.0, -16.0],
                    "color": [1.0, 0.0, 0.0, 0.5],
                    "line_width": 2.5,
                    "snap_strength": 0.75,
                },
                enabled_modules=["grid_alignment"],
            ),
            # Feature #13: simple_fog
            SdkProbeCaseSpec("t1_f13_01", "plugin_lifecycle", {"module_id": "simple_fog"}, enabled_modules=["simple_fog"]),
            SdkProbeCaseSpec("t1_f13_02", "plugin_domain", {"module_id": "simple_fog", "sub_op": "config", "state": _valid_simple_fog_state()}, enabled_modules=["simple_fog"]),
            SdkProbeCaseSpec("t1_f13_03", "plugin_domain", {"module_id": "simple_fog", "sub_op": "vision_and_light"}, enabled_modules=["simple_fog"]),
            SdkProbeCaseSpec("t1_f13_05", "plugin_domain", {"module_id": "simple_fog", "sub_op": "config", "state": _valid_simple_fog_state(with_exploration=True)}, enabled_modules=["simple_fog"]),
            # Feature #14: image_flip
            SdkProbeCaseSpec("t1_f14_01", "plugin_lifecycle", {"module_id": "image_flip"}, enabled_modules=["image_flip"]),
            SdkProbeCaseSpec("t1_f14_02", "plugin_domain", {"module_id": "image_flip", "action": "attach", "as_unit": False, "state": {"horizontal": True, "vertical": False}}, enabled_modules=["image_flip"]),
            SdkProbeCaseSpec("t1_f14_03", "plugin_domain", {"module_id": "image_flip", "action": "attach", "as_unit": False, "state": {"horizontal": True, "vertical": True}}, enabled_modules=["image_flip"]),
            SdkProbeCaseSpec("t1_f14_05", "plugin_domain", {"module_id": "image_flip", "action": "attach", "as_unit": False, "state": {"horizontal": False, "vertical": True}}, enabled_modules=[], disabled_policy="preserve"),
            # Feature #15: drag_movement
            SdkProbeCaseSpec("t1_f15_01", "plugin_lifecycle", {"module_id": "drag_movement"}, enabled_modules=["drag_movement"]),
            SdkProbeCaseSpec("t1_f15_02", "plugin_domain", {"module_id": "drag_movement", "action": "configure", "state": {"version": 2, "speed": 128.0}}, enabled_modules=["drag_movement"]),
            SdkProbeCaseSpec("t1_f15_03", "plugin_domain", {"module_id": "drag_movement", "action": "attach", "as_unit": True, "state": {"speed": 96.0}}, enabled_modules=["drag_movement"]),
            SdkProbeCaseSpec("t1_f15_04", "plugin_domain", {"module_id": "drag_movement", "action": "configure", "state": {"version": 2, "speed": 0.0}}, enabled_modules=["drag_movement"]),
            SdkProbeCaseSpec("t1_f15_05", "plugin_domain", {"module_id": "drag_movement", "action": "configure", "state": {"version": 2, "speed": 64.0}}, enabled_modules=[], disabled_policy="preserve"),
            # Feature #16: drawing
            SdkProbeCaseSpec("t1_f16_01", "plugin_lifecycle", {"module_id": "drawing"}, enabled_modules=["drawing"]),
            SdkProbeCaseSpec("t1_f16_02", "plugin_domain", {"module_id": "drawing", "action": "configure", "state": _valid_drawing_state(with_text=False)}, enabled_modules=["drawing"]),
            SdkProbeCaseSpec("t1_f16_03", "plugin_domain", {"module_id": "drawing", "action": "configure", "state": _valid_drawing_state(with_text=True)}, enabled_modules=["drawing"]),
            SdkProbeCaseSpec("t1_f16_04", "plugin_domain", {"module_id": "drawing", "action": "attach", "as_unit": False, "state": {"revision": HEX32_A, "strokes": [_valid_entity_ink_stroke()]}}, enabled_modules=["drawing"]),
            SdkProbeCaseSpec("t1_f16_05", "plugin_domain", {"module_id": "drawing", "action": "configure", "state": _valid_drawing_state()}, enabled_modules=[], disabled_policy="preserve"),
            # Feature #17: areas
            SdkProbeCaseSpec("t1_f17_01", "plugin_lifecycle", {"module_id": "areas"}, enabled_modules=["areas"]),
            SdkProbeCaseSpec("t1_f17_02", "plugin_domain", {"module_id": "areas", "action": "attach", "as_unit": False, "state": {"removed": False, "radius_in_cells": 3.0}}, enabled_modules=["areas"]),
            SdkProbeCaseSpec("t1_f17_03", "plugin_domain", {"module_id": "areas", "action": "attach", "as_unit": False, "state": {"removed": True, "radius_in_cells": 0.5}}, enabled_modules=["areas"]),
            # Feature #18: entity_notes
            SdkProbeCaseSpec("t1_f18_01", "plugin_lifecycle", {"module_id": "entity_notes"}),
            SdkProbeCaseSpec("t1_f18_02", "plugin_domain", {"module_id": "entity_notes", "action": "attach", "as_unit": False, "state": {"schema_version": 1, "text": "Secret trapdoor", "keep_screen_size": True, "is_pin": True}}),
            # Feature #19: checklist
            SdkProbeCaseSpec("t1_f19_01", "plugin_lifecycle", {"module_id": "checklist"}, enabled_modules=["checklist"]),
            SdkProbeCaseSpec("t1_f19_02", "plugin_domain", {"module_id": "checklist", "action": "configure", "state": _valid_checklist_state()}, enabled_modules=["checklist"]),
            SdkProbeCaseSpec("t1_f19_03", "plugin_domain", {"module_id": "checklist", "action": "configure", "state": _valid_checklist_state(audience="player", player_id="p_alice", entity_id=HEX32_B, more_entity_ids=[HEX32_C])}, enabled_modules=["checklist"]),
            SdkProbeCaseSpec("t1_f19_04", "plugin_domain", {"module_id": "checklist", "action": "configure", "state": _valid_checklist_state(done=True, archived=True)}, enabled_modules=["checklist"]),
            SdkProbeCaseSpec("t1_f19_05", "plugin_domain", {"module_id": "checklist", "action": "configure", "state": _valid_checklist_state()}, enabled_modules=[], disabled_policy="preserve"),
            # Feature #20: resource_pool
            SdkProbeCaseSpec("t1_f20_01", "plugin_lifecycle", {"module_id": "resource_pool"}, enabled_modules=["resource_pool"]),
            SdkProbeCaseSpec("t1_f20_02", "plugin_domain", {"module_id": "resource_pool", "action": "configure", "state": _valid_resource_pool_defs()}, enabled_modules=["resource_pool"]),
            SdkProbeCaseSpec("t1_f20_03", "plugin_domain", {"module_id": "resource_pool", "action": "attach", "as_unit": True, "state": {"schema_version": 1, "values": {"resource_pool:hp": {"current": 45.0, "maximum": 100.0}}}}, enabled_modules=["resource_pool"]),
            SdkProbeCaseSpec("t1_f20_04", "plugin_domain", {"module_id": "resource_pool", "action": "configure", "state": _valid_resource_pool_defs(display="count", visibility="controllers")}, enabled_modules=["resource_pool"]),
            SdkProbeCaseSpec("t1_f20_05", "plugin_domain", {"module_id": "resource_pool", "action": "configure", "state": _valid_resource_pool_defs()}, enabled_modules=[], disabled_policy="preserve"),
            # Feature #21: character_roster
            SdkProbeCaseSpec("t1_f21_01", "plugin_lifecycle", {"module_id": "character_roster"}, enabled_modules=["character_roster"]),
            SdkProbeCaseSpec("t1_f21_02", "plugin_domain", {"module_id": "character_roster", "action": "configure", "state": {"auto_join": True}}, enabled_modules=["character_roster"]),
            SdkProbeCaseSpec("t1_f21_03", "plugin_domain", {"module_id": "character_roster", "action": "attach", "as_unit": True, "state": {"schema_version": 1, "known_by": {"p1": HEX32_A}}}, enabled_modules=["character_roster"]),
            SdkProbeCaseSpec("t1_f21_05", "plugin_domain", {"module_id": "character_roster", "action": "configure", "state": {"auto_join": False}}, enabled_modules=[], disabled_policy="preserve"),
            # Feature #22: backpack
            SdkProbeCaseSpec("t1_f22_01", "plugin_lifecycle", {"module_id": "backpack"}, enabled_modules=["backpack"]),
            SdkProbeCaseSpec("t1_f22_02", "plugin_domain", {"module_id": "backpack", "action": "attach", "as_unit": True, "state": {"revision": HEX32_A, "slots": {"0": {"name": "Longsword", "note": "+1", "qty": 1}}}}, enabled_modules=["backpack"]),
            SdkProbeCaseSpec("t1_f22_03", "plugin_domain", {"module_id": "backpack", "action": "attach", "as_unit": True, "state": {"revision": "", "slots": {str(i): {"name": f"Item_{i}", "note": "", "qty": i + 1} for i in range(16)}}}, enabled_modules=["backpack"]),
            SdkProbeCaseSpec("t1_f22_04", "plugin_domain", {"module_id": "backpack", "action": "attach", "as_unit": True, "state": {"revision": HEX32_A, "slots": {"15": {"name": "Potion", "note": "Heal", "qty": 3}}, "receipts": {HEX32_B: HEX64_A}}}, enabled_modules=["backpack"]),
            SdkProbeCaseSpec("t1_f22_05", "plugin_domain", {"module_id": "backpack", "action": "attach", "as_unit": True, "state": {"revision": "", "slots": {"0": {"name": "Rope", "note": "", "qty": 1}}}}, enabled_modules=[], disabled_policy="preserve"),
            # Feature #23: follow
            SdkProbeCaseSpec("t1_f23_01", "plugin_lifecycle", {"module_id": "follow"}, enabled_modules=["follow"]),
            SdkProbeCaseSpec("t1_f23_02", "plugin_domain", {"module_id": "follow", "action": "attach", "as_unit": True, "state": {"target_id": HEX32_A, "controller_id": "p1", "engaged": True, "follow_distance": 32.0}}, enabled_modules=["follow"]),
            SdkProbeCaseSpec("t1_f23_03", "plugin_domain", {"module_id": "follow", "action": "attach", "as_unit": True, "state": {"target_id": "", "controller_id": "", "engaged": False, "follow_distance": 16.0}}, enabled_modules=["follow"]),
            SdkProbeCaseSpec("t1_f23_05", "plugin_domain", {"module_id": "follow", "action": "attach", "as_unit": True, "state": {"target_id": HEX32_A, "controller_id": "p1", "engaged": True, "follow_distance": 16.0}}, enabled_modules=[], disabled_policy="preserve"),
            # Feature #24: candidate_initiative
            SdkProbeCaseSpec("t1_f24_01", "plugin_lifecycle", {"module_id": "candidate_initiative"}, enabled_modules=["candidate_initiative"]),
            SdkProbeCaseSpec("t1_f24_02", "plugin_domain", {"module_id": "candidate_initiative", "action": "configure", "state": _valid_initiative_state(phase="idle")}, enabled_modules=["candidate_initiative"]),
            SdkProbeCaseSpec("t1_f24_03", "plugin_domain", {"module_id": "candidate_initiative", "action": "configure", "state": _valid_initiative_state(phase="active")}, enabled_modules=["candidate_initiative"]),
            SdkProbeCaseSpec("t1_f24_04", "plugin_domain", {"module_id": "candidate_initiative", "action": "attach", "as_unit": True, "state": {"count": 18, "modifier": 3, "active": True, "defeated": False, "rolled": True}}, enabled_modules=["candidate_initiative"]),
            SdkProbeCaseSpec("t1_f24_05", "plugin_domain", {"module_id": "candidate_initiative", "action": "configure", "state": _valid_initiative_state(phase="idle")}, enabled_modules=[], disabled_policy="preserve"),
            # Feature #25: dice
            SdkProbeCaseSpec("t1_f25_01", "plugin_lifecycle", {"module_id": "dice"}, enabled_modules=["dice"]),
            SdkProbeCaseSpec("t1_f25_02", "plugin_domain", {"module_id": "dice", "action": "configure", "state": _valid_dice_state()}, enabled_modules=["dice"]),
            SdkProbeCaseSpec("t1_f25_03", "plugin_domain", {"module_id": "dice", "action": "configure", "state": _valid_dice_state(expr="burst(2d6)")}, enabled_modules=["dice"]),
            SdkProbeCaseSpec("t1_f25_04", "plugin_domain", {"module_id": "dice", "action": "configure", "state": _valid_dice_state(theme_id="godot_blue_cat_eye", visibility="private")}, enabled_modules=["dice"]),
            SdkProbeCaseSpec("t1_f25_05", "plugin_domain", {"module_id": "dice", "action": "configure", "state": _valid_dice_state()}, enabled_modules=[], disabled_policy="preserve"),
            # Feature #26: campaign_time
            SdkProbeCaseSpec("t1_f26_01", "plugin_lifecycle", {"module_id": "campaign_time"}),
            SdkProbeCaseSpec("t1_f26_02", "plugin_domain", {"module_id": "campaign_time", "action": "configure", "state": _valid_campaign_time_state()}, disabled_policy="preserve"),
            SdkProbeCaseSpec("t1_f26_04", "plugin_domain", {"module_id": "campaign_time", "action": "configure", "state": _valid_campaign_time_state()}, disabled_policy="skip"),
            # Feature #27: dnd_opportunity
            SdkProbeCaseSpec("t1_f27_01", "plugin_lifecycle", {"module_id": "dnd_opportunity"}),
            SdkProbeCaseSpec("t1_f27_02", "plugin_domain", {"module_id": "dnd_opportunity", "action": "configure", "state": _valid_dnd_opportunity_state(2014)}, disabled_policy="preserve"),
            SdkProbeCaseSpec("t1_f27_03", "plugin_domain", {"module_id": "dnd_opportunity", "action": "configure", "state": _valid_dnd_opportunity_state(2024)}, disabled_policy="preserve"),
            SdkProbeCaseSpec("t1_f27_04", "plugin_domain", {"module_id": "dnd_opportunity", "action": "configure", "state": _valid_dnd_opportunity_state(2014)}, disabled_policy="skip"),
        ]

        cls.batch = probe.run_batch(cases, timeout_seconds=180)
        cls._cases_built = True
        return cls.batch

    def _data(self, case_id: str) -> dict:
        batch = self._ensure_godot_batch()
        self.assertEqual(batch.compile_failures, [], f"Compile failures: {batch.compile_failures}")
        self.assertEqual(batch.global_log_errors, [], f"Global Godot log errors: {batch.global_log_errors}")
        return assert_case_passed(self, batch.results[case_id])

    # =========================================================================
    # Feature #1: R3 LogBus (5 tests)
    # =========================================================================
    def test_t1_f01_01_logbus_script_and_level_constants(self) -> None:
        d = self._data("t1_f01_01")
        self.assertEqual(d.get("LEVEL_DEBUG"), 10)
        self.assertEqual(d.get("LEVEL_INFO"), 20)
        self.assertEqual(d.get("LEVEL_WARNING"), 30)
        self.assertEqual(d.get("LEVEL_ERROR"), 40)

    def test_t1_f01_02_logbus_multi_level_emit_and_entry_schema(self) -> None:
        d = self._data("t1_f01_02")
        entries = d.get("entries", [])
        self.assertEqual(len(entries), 5)
        for idx, e in enumerate(entries):
            assert_logbus_entry_schema(self, e)
            if idx > 0:
                self.assertGreater(e["seq"], entries[idx - 1]["seq"])
        self.assertEqual(len(d.get("warnings", [])), 2)

    def test_t1_f01_03_logbus_query_filter_and_clear(self) -> None:
        d = self._data("t1_f01_03")
        self.assertEqual(d.get("all_count"), 4)
        self.assertEqual(len(d.get("warn_and_above", [])), 2)
        self.assertEqual(len(d.get("since_first", [])), 3)
        self.assertEqual(len(d.get("limited_2", [])), 2)
        self.assertEqual(len(d.get("warnings_since", [])), 2)
        self.assertEqual(d.get("after_clear_count"), 0)

    def test_t1_f01_04_logbus_pubsub_subscribe_and_unsubscribe(self) -> None:
        d = self._data("t1_f01_04")
        self.assertIsInstance(d.get("tok_a"), int)
        self.assertIsInstance(d.get("tok_b"), int)
        self.assertNotEqual(d.get("tok_a"), d.get("tok_b"))
        self.assertIs(d.get("unsub_ok"), True)
        self.assertIs(d.get("unsub_again"), False)
        self.assertIs(d.get("unsub_bad"), False)
        self.assertEqual(len(d.get("received_a", [])), 1)
        self.assertEqual(len(d.get("received_b", [])), 2)

    def test_t1_f01_05_logbus_session_and_builder_integration_with_host(self) -> None:
        d = self._data("t1_f01_05")
        self.assertIs(d.get("same_logger"), True)
        self.assertEqual(d.get("before_forward_count"), 0)
        self.assertEqual(d.get("progress_before_opt_in"), [])
        self.assertGreaterEqual(len(d.get("entries", [])), 2)
        joined_progress = " ".join(d.get("host_progress", []))
        self.assertIn("progress hello", joined_progress)
        self.assertIn("direct session report", joined_progress)
        self.assertIn("warning hello", " ".join(d.get("host_warnings", [])))

    # =========================================================================
    # Feature #2: R2 ModuleRegistry (5 tests)
    # =========================================================================
    def test_t1_f02_01_registry_full_30_plus_3_catalog(self) -> None:
        d = self._data("t1_f02_01")
        avail = d.get("avail_map", {})
        for mid in CORE_MODULE_IDS + OPTIONAL_MODULE_IDS + CANDIDATE_MODULE_IDS:
            self.assertIn(mid, avail, f"Missing module in registry: {mid}")
            self.assertIsInstance(avail[mid], dict)
            self.assertTrue(str(avail[mid].get("status", "")), f"Empty availability status for {mid}")

    def test_t1_f02_02_core_always_enabled_and_optional_default_disabled(self) -> None:
        d = self._data("t1_f02_01")
        avail = d.get("avail_map", {})
        enabled = d.get("enabled_map", {})
        for cid in CORE_MODULE_IDS:
            self.assertIs(enabled.get(cid), True, f"Core module {cid} must be enabled")
            self.assertEqual(avail[cid].get("status"), "core")
        for oid in OPTIONAL_MODULE_IDS:
            self.assertIs(enabled.get(oid), False, f"Optional module {oid} must default disabled")
            expected_status = "playtest_blocked" if oid in PLAYTEST_BLOCKED_MODULE_IDS else "disabled"
            self.assertEqual(avail[oid].get("status"), expected_status)
        for cand in CANDIDATE_MODULE_IDS:
            self.assertIs(enabled.get(cand), False)
            self.assertEqual(avail[cand].get("status"), "uncatalogued_candidate")

    def test_t1_f02_03_set_enabled_modules_and_toggle(self) -> None:
        d = self._data("t1_f02_03")
        avail = d.get("avail_map", {})
        enabled = d.get("enabled_map", {})
        for mid in ("simple_fog", "portal", "backpack"):
            self.assertIs(enabled.get(mid), True)
            self.assertEqual(avail[mid].get("status"), "enabled")

    def test_t1_f02_04_disabled_write_warning_and_preserve_policy(self) -> None:
        d = self._data("t1_f02_04")
        assert_r2_warning_present(self, d.get("log_entries", []), "grid_alignment", status="disabled", policy="preserve")
        assert_r2_warning_present(self, d.get("host_warnings", []), "grid_alignment")
        assert_world_module_entry(self, d["world"], "grid_alignment", expected_version=1)

    def test_t1_f02_05_disabled_write_skip_policy_no_mutation(self) -> None:
        d = self._data("t1_f02_05")
        assert_r2_warning_present(self, d.get("log_entries", []), "grid_alignment", status="disabled", policy="skip")
        entries = d["world"].get("modules", {}).get("entries", {})
        self.assertNotIn("grid_alignment", entries)
        res = d.get("result")
        if isinstance(res, dict):
            self.assertIs(res.get("ok"), False)
            self.assertIs(res.get("skipped"), True)
        else:
            self.assertIs(res, False)

    # =========================================================================
    # Feature #3: parked: true, manual: true component support (5 tests)
    # =========================================================================
    def test_t1_f03_01_attach_component_unparked_keys(self) -> None:
        d = self._data("t1_f03_01")
        assert_world_v3_invariants(self, d["world"], "t1_f03_01")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/areas/comp_area.gd")
        self.assertEqual(set(comp.keys()), {"script", "state"})

    def test_t1_f03_02_attach_component_parked_auto_resume(self) -> None:
        d = self._data("t1_f03_02")
        assert_world_v3_invariants(self, d["world"], "t1_f03_02")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/areas/comp_area.gd", parked=True, manual=False)
        self.assertNotIn("manual", comp)

    def test_t1_f03_03_attach_component_parked_manual_true(self) -> None:
        d = self._data("t1_f03_03")
        assert_world_v3_invariants(self, d["world"], "t1_f03_03")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/areas/comp_area.gd", parked=True, manual=True)
        self.assertEqual(set(comp.keys()), {"script", "state", "parked", "manual"})

    def test_t1_f03_04_disabled_module_preserve_parks_component(self) -> None:
        d = self._data("t1_f03_04")
        assert_world_v3_invariants(self, d["world"], "t1_f03_04")
        assert_r2_warning_present(self, d.get("log_entries", []), "areas")
        ent = d["world"]["entity_state"]["entities"][0]
        assert_entity_has_component(self, ent, "res://modules/areas/comp_area.gd", parked=True)

    def test_t1_f03_05_parked_manual_var_to_bytes_roundtrip(self) -> None:
        d = self._data("t1_f03_03")
        self.assertEqual(d.get("roundtrip_diff"), "")
        self.assertGreater(int(d.get("serialized_bytes", 0)), 0)

    # =========================================================================
    # Feature #4: Core SDK feature_edit_mode (5 tests)
    # =========================================================================
    def test_t1_f04_01_plugin_script_and_core_availability(self) -> None:
        d = self._data("t1_f04_01")
        self.assertEqual(d.get("module_id"), "feature_edit_mode")
        self.assertIs(d.get("is_enabled"), True)
        self.assertEqual(d["availability"].get("status"), "core")
        self.assertTrue(d.get("domain_methods"))

    def test_t1_f04_02_attach_unit_marker_via_builder(self) -> None:
        d = self._data("t1_f04_02")
        self.assertIs(d.get("result"), True)
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://scenes/entities/components/comp_unit.gd")
        self.assertEqual(comp["state"].get("schema_version"), 1)

    def test_t1_f04_03_add_token_creates_selectable_unit(self) -> None:
        d = self._data("t1_f04_03")
        self.assertIs(d.get("is_unit"), True)
        self.assertIs(d.get("perm_ok"), True)
        self.assertIs(d.get("validate_unit", {}).get("ok"), True)
        ent = d["world"]["entity_state"]["entities"][0]
        self.assertEqual(ent.get("entity_type"), "unit")
        self.assertIs(ent.get("selectable_in_select_mode"), True)

    def test_t1_f04_04_unit_component_survives_roundtrip(self) -> None:
        d = self._data("t1_f04_02")
        assert_world_v3_invariants(self, d["world"], "t1_f04_04")
        self.assertEqual(d.get("roundtrip_diff"), "")

    def test_t1_f04_05_core_module_zero_disabled_warnings(self) -> None:
        d = self._data("t1_f04_02")
        self.assertEqual(d.get("host_warnings"), [])

    # =========================================================================
    # Feature #5: Core SDK feature_floor_system (5 tests)
    # =========================================================================
    def test_t1_f05_01_plugin_script_and_core_availability(self) -> None:
        d = self._data("t1_f05_01")
        self.assertEqual(d.get("module_id"), "feature_floor_system")
        self.assertIs(d.get("is_enabled"), True)
        self.assertEqual(d["availability"].get("status"), "core")

    def test_t1_f05_02_add_and_activate_floor(self) -> None:
        d = self._data("t1_f05_02")
        self.assertRegex(d.get("floor_uid", ""), UID_32_RE)
        self.assertEqual(d.get("active_floor_uid"), d.get("floor_uid"))
        self.assertEqual(len(d["world"]["catalog"]["floors"]), 2)

    def test_t1_f05_03_rename_floor_sanitized(self) -> None:
        d = self._data("t1_f05_03")
        self.assertIs(d.get("result"), True)
        names = [f["name"] for f in d["world"]["catalog"]["floors"]]
        self.assertIn("NewFloor", names)

    def test_t1_f05_04_set_active_floor_and_entity_membership(self) -> None:
        d = self._data("t1_f05_04")
        members = d["world"]["members"]
        self.assertEqual(members[0]["entity_id"], d["entity_id"])
        self.assertEqual(members[0]["floor_uid"], d["floor_uid"])

    def test_t1_f05_05_floor_catalog_v3_roundtrip(self) -> None:
        d = self._data("t1_f05_04")
        assert_world_v3_invariants(self, d["world"], "t1_f05_05")
        self.assertEqual(d.get("roundtrip_diff"), "")

    # =========================================================================
    # Feature #6: Core SDK feature_layer_stack (5 tests)
    # =========================================================================
    def test_t1_f06_01_plugin_script_and_core_availability(self) -> None:
        d = self._data("t1_f06_01")
        self.assertEqual(d.get("module_id"), "feature_layer_stack")
        self.assertIs(d.get("is_enabled"), True)
        self.assertEqual(d["availability"].get("status"), "core")

    def test_t1_f06_02_default_floor_layers_v2_schema(self) -> None:
        d = self._data("t1_f06_03")
        layers_root = d["world"]["catalog"]["layers"]
        self.assertEqual(layers_root.get("schema"), "fus.floor_layers.v2")
        kinds = {l["kind"] for l in layers_root["floors"][0]["layers"]}
        self.assertTrue({"map", "entity", "obstacle"}.issubset(kinds))

    def test_t1_f06_03_add_custom_area_layer_all_access(self) -> None:
        d = self._data("t1_f06_03")
        self.assertRegex(d.get("layer_uid", ""), UID_32_RE)

    def test_t1_f06_04_add_players_layer_with_viewers(self) -> None:
        d = self._data("t1_f06_04")
        luid = d.get("layer_uid")
        layers = d["world"]["catalog"]["layers"]["floors"][0]["layers"]
        matched = [l for l in layers if l["layer_uid"] == luid]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["access"], "players")
        self.assertEqual(matched[0]["viewers"], ["p1", "p2"])
        self.assertIs(matched[0]["locked"], True)
        self.assertIs(matched[0]["visible"], False)

    def test_t1_f06_05_layer_uid_override_entity_placement(self) -> None:
        d = self._data("t1_f06_05")
        assert_world_v3_invariants(self, d["world"], "t1_f06_05")
        m = d["world"]["members"][0]
        self.assertEqual(m["floor_uid"], d["floor_uid"])
        self.assertEqual(m["layer_uid"], d["layer_uid"])

    # =========================================================================
    # Feature #7: Core SDK feature_obstacle_authoring (5 tests)
    # =========================================================================
    def test_t1_f07_01_plugin_script_and_core_availability(self) -> None:
        d = self._data("t1_f07_01")
        self.assertEqual(d.get("module_id"), "feature_obstacle_authoring")
        self.assertIs(d.get("is_enabled"), True)
        self.assertEqual(d["availability"].get("status"), "core")

    def test_t1_f07_02_polygon_wall_and_air_cutout(self) -> None:
        d = self._data("t1_f07_02")
        self.assertEqual(len(d.get("ids", [])), 2)
        self.assertEqual(len(d["world"]["entity_state"]["entities"]), 2)

    def test_t1_f07_03_door_window_glass_roles(self) -> None:
        d = self._data("t1_f07_03")
        self.assertEqual(len(d.get("ids", [])), 3)
        self.assertEqual(len(d["world"]["entity_state"]["entities"]), 3)

    def test_t1_f07_04_segment_extrusion_and_segment_obstacles(self) -> None:
        d = self._data("t1_f07_04")
        self.assertEqual(len(d.get("ids", [])), 4)
        self.assertEqual(len(d["world"]["entity_state"]["entities"]), 4)

    def test_t1_f07_05_obstacles_roundtrip_and_zero_warnings(self) -> None:
        d = self._data("t1_f07_04")
        assert_world_v3_invariants(self, d["world"], "t1_f07_05")
        self.assertEqual(d.get("roundtrip_diff"), "")
        self.assertEqual(d.get("host_warnings"), [])

    # =========================================================================
    # Feature #8: Core SDK feature_entity_library (5 tests)
    # =========================================================================
    def test_t1_f08_01_plugin_script_and_core_availability(self) -> None:
        d = self._data("t1_f08_01")
        self.assertEqual(d.get("module_id"), "feature_entity_library")
        self.assertIs(d.get("is_enabled"), True)
        self.assertEqual(d["availability"].get("status"), "core")

    def test_t1_f08_02_register_unit_in_library(self) -> None:
        d = self._data("t1_f08_02")
        self.assertIs(d.get("can_write"), True)
        self.assertEqual(
            set(d.get("template_keys", [])),
            {"id", "name", "type", "category", "size", "color", "sprite", "components", "selectable_in_select_mode"},
        )
        reg = d.get("reg_result", {})
        self.assertIs(reg.get("ok"), True)
        self.assertEqual(reg.get("count"), 1)
        self.assertIs(reg.get("skipped"), False)
        records = d.get("decoded_records", {})
        self.assertEqual(len(records), 3)  # Monsters, Monsters/LowCR, goblin_1
        kinds = [rec.get("kind") for rec in records.values()]
        self.assertEqual(kinds.count("folder"), 2)
        self.assertEqual(kinds.count("unit"), 1)
        expected_sprite = "asset://" + "a" * 64 + ".png"
        self.assertIn(expected_sprite, d.get("adopted_assets", []))
        self.assertIn(expected_sprite, d.get("shared_assets", []))

    def test_t1_f08_03_register_preset_with_enabled_modules(self) -> None:
        d = self._data("t1_f08_03")
        self.assertIs(d.get("inspect_res", {}).get("ok"), True)
        reg = d.get("reg_result", {})
        self.assertIs(reg.get("ok"), True)
        self.assertEqual(reg.get("count"), 1)
        self.assertEqual(reg.get("warned_presets"), [])
        records = d.get("decoded_records", {})
        presets = [rec for rec in records.values() if rec.get("kind") == "preset"]
        self.assertEqual(len(presets), 1)
        snap_comps = presets[0]["record"]["snapshot"]["entities"][0]["components"]
        self.assertIn("res://modules/simple_fog/comp_simple_vision.gd", [c["script"] for c in snap_comps])

    def test_t1_f08_04_preset_with_disabled_module_component_warns(self) -> None:
        d = self._data("t1_f08_04")
        insp = d.get("inspect_res", {})
        self.assertIs(insp.get("ok"), False)
        self.assertEqual(insp.get("reason"), "preset_component_unavailable")
        reg = d.get("reg_result", {})
        self.assertIs(reg.get("ok"), True)
        self.assertEqual(len(reg.get("warned_presets", [])), 1)
        assert_r2_warning_present(self, d.get("log_entries", []), "simple_fog")

    def test_t1_f08_05_library_favorites_or_metadata_query(self) -> None:
        d = self._data("t1_f08_05")
        self.assertIs(d.get("no_favorites_api"), True)
        tpl_u = d.get("tpl_unit", {})
        self.assertEqual(
            set(tpl_u.keys()),
            {"id", "name", "type", "category", "size", "color", "sprite", "components", "selectable_in_select_mode"},
        )
        self.assertIn("unit", tpl_u.get("components", {}))
        self.assertIn("extra", tpl_u.get("components", {}))
        self.assertIs(tpl_u.get("selectable_in_select_mode"), True)
        self.assertIs(d.get("tpl_obj", {}).get("selectable_in_select_mode"), False)
        self.assertEqual(d.get("bad_tpl"), {})
        self.assertIs(d.get("val_core_ok", {}).get("ok"), True)
        val_dis = d.get("val_disabled_res", {})
        self.assertIs(val_dis.get("ok"), False)
        self.assertEqual(val_dis.get("reason"), "preset_component_unavailable")

    # =========================================================================
    # Feature #9: Stateless Core & Optional Catalog Metadata (5 tests)
    # =========================================================================
    def test_t1_f09_01_stateless_core_modules_registered(self) -> None:
        d = self._data("t1_f02_01")
        avail = d["avail_map"]
        for mid in STATELESS_CORE_MODULE_IDS:
            self.assertEqual(avail[mid].get("status"), "core")

    def test_t1_f09_02_stateless_optional_modules_registered(self) -> None:
        d = self._data("t1_f02_01")
        avail = d["avail_map"]
        for mid in STATELESS_OPTIONAL_MODULE_IDS:
            self.assertEqual(avail[mid].get("status"), "disabled")

    def test_t1_f09_03_non_catalog_candidates_registered(self) -> None:
        d = self._data("t1_f02_01")
        avail = d["avail_map"]
        for mid in CANDIDATE_MODULE_IDS:
            self.assertEqual(avail[mid].get("status"), "uncatalogued_candidate")

    def test_t1_f09_04_stateless_metadata_query_is_stateless(self) -> None:
        d = self._data("t1_f02_01")
        listed = d.get("listed_modules", [])
        self.assertGreaterEqual(len(listed), 30)
        self.assertEqual(d["world"]["modules"]["entries"], {})

    def test_t1_f09_05_core_modules_cannot_be_disabled(self) -> None:
        d = self._data("t1_f09_05")
        self.assertIs(d.get("core_still_on"), True)
        self.assertIs(d.get("opt_on"), True)

    # =========================================================================
    # Feature #10: Optional SDK scene_box (5 tests)
    # =========================================================================
    def test_t1_f10_01_plugin_script_and_enabled_availability(self) -> None:
        d = self._data("t1_f10_01")
        self.assertEqual(d.get("module_id"), "scene_box")
        self.assertIs(d.get("is_enabled"), True)
        self.assertEqual(d["availability"].get("status"), "enabled")

    def test_t1_f10_02_configure_entry_and_add_scene_v2(self) -> None:
        d = self._data("t1_f10_02")
        st = assert_world_module_entry(self, d["world"], "scene_box", expected_version=1)
        self.assertEqual(st.get("schema_version"), 2)
        self.assertEqual(len(st.get("scenes", [])), 2)

    def test_t1_f10_03_add_scene_box_entity_and_policies(self) -> None:
        d = self._data("t1_f10_03")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/scene_box/comp_scene_box.gd")
        self.assertEqual(comp["state"].get("preview_policy"), "visited_unlock")
        self.assertEqual(comp["state"].get("enter_policy"), "players_allowed")

    def test_t1_f10_04_attach_scene_box_and_host_view(self) -> None:
        d = self._data("t1_f10_04")
        self.assertIs(d.get("result"), True)
        st = assert_world_module_entry(self, d["world"], "scene_box")
        self.assertTrue(st.get("host_views"))

    def test_t1_f10_05_scene_box_var_to_bytes_roundtrip(self) -> None:
        d = self._data("t1_f10_03")
        assert_world_v3_invariants(self, d["world"], "t1_f10_05")
        self.assertEqual(d.get("roundtrip_diff"), "")

    # =========================================================================
    # Feature #11: Optional SDK portal (5 tests)
    # =========================================================================
    def test_t1_f11_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f11_01")
        self.assertEqual(d.get("module_id"), "portal")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f11_02_attach_portal_32hex_pair_key(self) -> None:
        d = self._data("t1_f11_02")
        self.assertEqual(d.get("result"), [True, True])
        for ent in d["world"]["entity_state"]["entities"]:
            comp = assert_entity_has_component(self, ent, "res://modules/portal/comp_portal.gd")
            self.assertEqual(comp["state"].get("pair_key"), HEX32_A)

    def test_t1_f11_03_attach_portal_normalizes_human_pair_key(self) -> None:
        d = self._data("t1_f11_03")
        keys = []
        for ent in d["world"]["entity_state"]["entities"]:
            comp = assert_entity_has_component(self, ent, "res://modules/portal/comp_portal.gd")
            pk = comp["state"].get("pair_key", "")
            self.assertRegex(pk, UID_32_RE)
            keys.append(pk)
        self.assertEqual(keys[0], keys[1])

    def test_t1_f11_04_portal_cross_floor_pair_and_roundtrip(self) -> None:
        d = self._data("t1_f11_03")
        assert_world_v3_invariants(self, d["world"], "t1_f11_04")
        self.assertEqual(d.get("roundtrip_diff"), "")

    def test_t1_f11_05_portal_disabled_emits_r2_warning(self) -> None:
        d = self._data("t1_f11_05")
        assert_r2_warning_present(self, d.get("log_entries", []) + d.get("host_warnings", []), "portal")

    # =========================================================================
    # Feature #12: Optional SDK grid_alignment (5 tests)
    # =========================================================================
    def test_t1_f12_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f12_01")
        self.assertEqual(d.get("module_id"), "grid_alignment")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f12_02_exact_8_keys_and_schema(self) -> None:
        d = self._data("t1_f12_02")
        st = assert_world_module_entry(self, d["world"], "grid_alignment", expected_version=1)
        self.assertEqual(
            set(st.keys()),
            {"schema", "version", "cell_size", "offset", "color", "line_width", "snap_enabled", "snap_strength"},
        )
        self.assertEqual(st["schema"], "fus.grid_alignment.config")
        self.assertEqual(st["version"], 1)

    def test_t1_f12_03_custom_cell_size_offset_color(self) -> None:
        d = self._data("t1_f12_03")
        st = assert_world_module_entry(self, d["world"], "grid_alignment")
        self.assertAlmostEqual(float(st["cell_size"]), 128.0, places=3)
        self.assertIs(st["snap_enabled"], False)
        self.assertAlmostEqual(float(st["line_width"]), 2.5, places=3)
        self.assertAlmostEqual(float(st["snap_strength"]), 0.75, places=3)

    def test_t1_f12_04_grid_alignment_roundtrip(self) -> None:
        d = self._data("t1_f12_03")
        self.assertEqual(d.get("roundtrip_diff"), "")

    def test_t1_f12_05_grid_alignment_disabled_warns(self) -> None:
        d = self._data("t1_f02_04")
        assert_r2_warning_present(self, d.get("log_entries", []), "grid_alignment")

    # =========================================================================
    # Feature #13: Optional SDK simple_fog (5 tests)
    # =========================================================================
    def test_t1_f13_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f13_01")
        self.assertEqual(d.get("module_id"), "simple_fog")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f13_02_fog_config_v2_module_state(self) -> None:
        d = self._data("t1_f13_02")
        st = assert_world_module_entry(self, d["world"], "simple_fog", expected_version=1)
        self.assertEqual(st.get("version"), 2)
        self.assertIs(st.get("history_enabled"), True)

    def test_t1_f13_03_attach_simple_vision_component(self) -> None:
        d = self._data("t1_f13_03")
        tok = [e for e in d["world"]["entity_state"]["entities"] if e["id"] == d["token_id"]][0]
        comp = assert_entity_has_component(self, tok, "res://modules/simple_fog/comp_simple_vision.gd")
        self.assertAlmostEqual(float(comp["state"]["radius"]), 400.0, places=2)

    def test_t1_f13_04_attach_simple_light_and_point_light(self) -> None:
        d = self._data("t1_f13_03")
        lgt = [e for e in d["world"]["entity_state"]["entities"] if e["id"] == d["light_id"]][0]
        comp = assert_entity_has_component(self, lgt, "res://modules/simple_fog/comp_simple_light.gd")
        self.assertAlmostEqual(float(comp["state"]["radius"]), 320.0, places=2)

    def test_t1_f13_05_exploration_sfh2_bytes_and_roundtrip(self) -> None:
        d = self._data("t1_f13_05")
        st = assert_world_module_entry(self, d["world"], "simple_fog")
        self.assertTrue(bytes(st.get("exploration", b"")).startswith(b"SFH2"))
        self.assertEqual(d.get("roundtrip_diff"), "")

    # =========================================================================
    # Feature #14: Optional SDK image_flip (5 tests)
    # =========================================================================
    def test_t1_f14_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f14_01")
        self.assertEqual(d.get("module_id"), "image_flip")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f14_02_attach_horizontal_flip(self) -> None:
        d = self._data("t1_f14_02")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/image_flip/comp_image_flip.gd")
        self.assertIs(comp["state"].get("horizontal"), True)
        self.assertIs(comp["state"].get("vertical"), False)

    def test_t1_f14_03_attach_vertical_and_both_flip(self) -> None:
        d = self._data("t1_f14_03")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/image_flip/comp_image_flip.gd")
        self.assertIs(comp["state"].get("horizontal"), True)
        self.assertIs(comp["state"].get("vertical"), True)

    def test_t1_f14_04_image_flip_var_to_bytes_roundtrip(self) -> None:
        d = self._data("t1_f14_02")
        self.assertEqual(d.get("roundtrip_diff"), "")

    def test_t1_f14_05_image_flip_disabled_warns(self) -> None:
        d = self._data("t1_f14_05")
        assert_r2_warning_present(self, d.get("log_entries", []), "image_flip", status="disabled", policy="preserve")

    # =========================================================================
    # Feature #15: Optional SDK drag_movement (5 tests)
    # =========================================================================
    def test_t1_f15_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f15_01")
        self.assertEqual(d.get("module_id"), "drag_movement")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f15_02_module_state_v2_default_and_custom_speed(self) -> None:
        d = self._data("t1_f15_02")
        st = assert_world_module_entry(self, d["world"], "drag_movement")
        self.assertEqual(st.get("version"), 2)
        self.assertAlmostEqual(float(st.get("speed", -1.0)), 128.0, places=2)

    def test_t1_f15_03_attach_comp_drag_speed(self) -> None:
        d = self._data("t1_f15_03")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/drag_movement/comp_drag_speed.gd")
        self.assertAlmostEqual(float(comp["state"].get("speed", -1.0)), 96.0, places=2)

    def test_t1_f15_04_drag_movement_zero_speed_allowed(self) -> None:
        d = self._data("t1_f15_04")
        st = assert_world_module_entry(self, d["world"], "drag_movement")
        self.assertAlmostEqual(float(st.get("speed", -1.0)), 0.0, places=3)

    def test_t1_f15_05_drag_movement_roundtrip_and_disabled_warn(self) -> None:
        d = self._data("t1_f15_05")
        assert_r2_warning_present(self, d.get("log_entries", []), "drag_movement")
        self.assertEqual(d.get("roundtrip_diff"), "")

    # =========================================================================
    # Feature #16: Optional SDK drawing (5 tests)
    # =========================================================================
    def test_t1_f16_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f16_01")
        self.assertEqual(d.get("module_id"), "drawing")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f16_02_world_drawing_strokes_v1(self) -> None:
        d = self._data("t1_f16_02")
        st = assert_world_module_entry(self, d["world"], "drawing")
        self.assertEqual(st.get("version"), 1)
        self.assertEqual(len(st.get("strokes", [])), 1)

    def test_t1_f16_03_drawing_text_item_v0061(self) -> None:
        d = self._data("t1_f16_03")
        st = assert_world_module_entry(self, d["world"], "drawing")
        strokes = st.get("strokes", [])
        self.assertEqual(len(strokes), 2)
        self.assertEqual(strokes[1].get("tool"), "text")
        self.assertEqual(strokes[1].get("text"), "Dragon Lair")

    def test_t1_f16_04_attach_comp_entity_ink(self) -> None:
        d = self._data("t1_f16_04")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/drawing/comp_entity_ink.gd")
        self.assertTrue(comp["state"].get("strokes"))

    def test_t1_f16_05_drawing_roundtrip_and_disabled_warn(self) -> None:
        d = self._data("t1_f16_05")
        assert_r2_warning_present(self, d.get("log_entries", []), "drawing")
        self.assertEqual(d.get("roundtrip_diff"), "")

    # =========================================================================
    # Feature #17: Optional SDK areas (5 tests)
    # =========================================================================
    def test_t1_f17_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f17_01")
        self.assertEqual(d.get("module_id"), "areas")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f17_02_attach_comp_area_default(self) -> None:
        d = self._data("t1_f17_02")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/areas/comp_area.gd")
        self.assertAlmostEqual(float(comp["state"].get("radius_in_cells", 0.0)), 3.0, places=2)
        self.assertIs(comp["state"].get("removed"), False)

    def test_t1_f17_03_attach_comp_area_removed_flag(self) -> None:
        d = self._data("t1_f17_03")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/areas/comp_area.gd")
        self.assertIs(comp["state"].get("removed"), True)

    def test_t1_f17_04_areas_roundtrip(self) -> None:
        d = self._data("t1_f17_02")
        self.assertEqual(d.get("roundtrip_diff"), "")

    def test_t1_f17_05_areas_disabled_warns(self) -> None:
        d = self._data("t1_f03_04")
        assert_r2_warning_present(self, d.get("log_entries", []), "areas", status="disabled", policy="preserve")

    # =========================================================================
    # Feature #18: Candidate SDK entity_notes (5 tests)
    # =========================================================================
    def test_t1_f18_01_plugin_script_and_uncatalogued_status(self) -> None:
        d = self._data("t1_f18_01")
        self.assertEqual(d.get("module_id"), "entity_notes")
        self.assertIs(d.get("is_enabled"), False)
        self.assertEqual(d["availability"].get("status"), "uncatalogued_candidate")

    def test_t1_f18_02_attach_comp_entity_note(self) -> None:
        d = self._data("t1_f18_02")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://scenes/candidates/entity_notes/comp_entity_note.gd")
        self.assertEqual(comp["state"].get("text"), "Secret trapdoor")

    def test_t1_f18_03_add_text_pin_compat(self) -> None:
        d = self._data("t1_f18_02")
        assert_world_v3_invariants(self, d["world"], "t1_f18_03")

    def test_t1_f18_04_uncatalogued_candidate_emits_warning_and_parks(self) -> None:
        d = self._data("t1_f18_02")
        assert_r2_warning_present(self, d.get("log_entries", []), "entity_notes", status="uncatalogued_candidate")
        ent = d["world"]["entity_state"]["entities"][0]
        assert_entity_has_component(self, ent, "res://scenes/candidates/entity_notes/comp_entity_note.gd", parked=True)

    def test_t1_f18_05_entity_notes_var_to_bytes_roundtrip(self) -> None:
        d = self._data("t1_f18_02")
        self.assertEqual(d.get("roundtrip_diff"), "")

    # =========================================================================
    # Feature #19: Optional SDK checklist (5 tests)
    # =========================================================================
    def test_t1_f19_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f19_01")
        self.assertEqual(d.get("module_id"), "checklist")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f19_02_checklist_schema2_all_audience_row(self) -> None:
        d = self._data("t1_f19_02")
        st = assert_world_module_entry(self, d["world"], "checklist")
        self.assertEqual(st.get("schema"), 2)
        self.assertIn(HEX32_A, st.get("rows", {}))

    def test_t1_f19_03_checklist_player_and_gm_rows(self) -> None:
        d = self._data("t1_f19_03")
        st = assert_world_module_entry(self, d["world"], "checklist")
        row = st["rows"][HEX32_A]
        self.assertEqual(row.get("audience"), "player")
        self.assertEqual(row.get("player_id"), "p_alice")

    def test_t1_f19_04_checklist_done_and_archived_row(self) -> None:
        d = self._data("t1_f19_04")
        row = assert_world_module_entry(self, d["world"], "checklist")["rows"][HEX32_A]
        self.assertIs(row.get("done"), True)
        self.assertIs(row.get("archived"), True)

    def test_t1_f19_05_checklist_roundtrip_and_disabled_warn(self) -> None:
        d = self._data("t1_f19_05")
        assert_r2_warning_present(self, d.get("log_entries", []), "checklist")
        self.assertEqual(d.get("roundtrip_diff"), "")

    # =========================================================================
    # Feature #20: Optional SDK resource_pool (5 tests)
    # =========================================================================
    def test_t1_f20_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f20_01")
        self.assertEqual(d.get("module_id"), "resource_pool")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f20_02_define_resource_pool_module_state(self) -> None:
        d = self._data("t1_f20_02")
        st = assert_world_module_entry(self, d["world"], "resource_pool")
        self.assertEqual(st.get("schema_version"), 1)
        hp_def = st["definitions"]["resource_pool:hp"]
        self.assertEqual(hp_def.get("source"), "resource_pool")
        self.assertRegex(hp_def["color"], HEX8_COLOR_RE)

    def test_t1_f20_03_attach_comp_resource_pool_values(self) -> None:
        d = self._data("t1_f20_03")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://scenes/candidates/resource_pool/comp_resource_pool.gd")
        self.assertAlmostEqual(float(comp["state"]["values"]["resource_pool:hp"]["current"]), 45.0, places=2)

    def test_t1_f20_04_multiple_definitions_bar_number_count(self) -> None:
        d = self._data("t1_f20_04")
        hp_def = assert_world_module_entry(self, d["world"], "resource_pool")["definitions"]["resource_pool:hp"]
        self.assertEqual(hp_def["display"], "count")
        self.assertEqual(hp_def["visibility"], "controllers")

    def test_t1_f20_05_resource_pool_roundtrip_and_disabled_warn(self) -> None:
        d = self._data("t1_f20_05")
        assert_r2_warning_present(self, d.get("log_entries", []), "resource_pool")
        self.assertEqual(d.get("roundtrip_diff"), "")

    # =========================================================================
    # Feature #21: Optional SDK character_roster (5 tests)
    # =========================================================================
    def test_t1_f21_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f21_01")
        self.assertEqual(d.get("module_id"), "character_roster")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f21_02_module_state_auto_join_true_false(self) -> None:
        d = self._data("t1_f21_02")
        st = assert_world_module_entry(self, d["world"], "character_roster")
        self.assertIs(st.get("auto_join"), True)

    def test_t1_f21_03_attach_comp_character_roster_member_on_unit(self) -> None:
        d = self._data("t1_f21_03")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/character_roster/comp_character_roster_member.gd")
        self.assertEqual(comp["state"].get("known_by"), {"p1": HEX32_A})

    def test_t1_f21_04_character_roster_roundtrip(self) -> None:
        d = self._data("t1_f21_03")
        self.assertEqual(d.get("roundtrip_diff"), "")

    def test_t1_f21_05_character_roster_disabled_warns(self) -> None:
        d = self._data("t1_f21_05")
        assert_r2_warning_present(self, d.get("log_entries", []), "character_roster")

    # =========================================================================
    # Feature #22: Optional SDK backpack (5 tests)
    # =========================================================================
    def test_t1_f22_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f22_01")
        self.assertEqual(d.get("module_id"), "backpack")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f22_02_attach_comp_backpack_on_unit(self) -> None:
        d = self._data("t1_f22_02")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/backpack/comp_backpack.gd")
        self.assertEqual(comp["state"]["slots"]["0"]["name"], "Longsword")

    def test_t1_f22_03_backpack_slots_0_through_15(self) -> None:
        d = self._data("t1_f22_03")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/backpack/comp_backpack.gd")
        self.assertEqual(len(comp["state"]["slots"]), 16)

    def test_t1_f22_04_backpack_revision_and_receipts_roundtrip(self) -> None:
        d = self._data("t1_f22_04")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/backpack/comp_backpack.gd")
        self.assertEqual(comp["state"].get("revision"), HEX32_A)
        self.assertEqual(comp["state"].get("receipts"), {HEX32_B: HEX64_A})
        self.assertEqual(d.get("roundtrip_diff"), "")

    def test_t1_f22_05_backpack_disabled_warns(self) -> None:
        d = self._data("t1_f22_05")
        assert_r2_warning_present(self, d.get("log_entries", []), "backpack")

    # =========================================================================
    # Feature #23: Optional SDK follow (5 tests)
    # =========================================================================
    def test_t1_f23_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f23_01")
        self.assertEqual(d.get("module_id"), "follow")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f23_02_attach_comp_follow_with_target(self) -> None:
        d = self._data("t1_f23_02")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/follow/comp_follow.gd")
        self.assertEqual(comp["state"].get("target_id"), HEX32_A)
        self.assertIs(comp["state"].get("engaged"), True)

    def test_t1_f23_03_attach_comp_follow_unengaged_empty_target(self) -> None:
        d = self._data("t1_f23_03")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/follow/comp_follow.gd")
        self.assertEqual(comp["state"].get("target_id"), "")
        self.assertIs(comp["state"].get("engaged"), False)

    def test_t1_f23_04_follow_roundtrip(self) -> None:
        d = self._data("t1_f23_02")
        self.assertEqual(d.get("roundtrip_diff"), "")

    def test_t1_f23_05_follow_disabled_warns(self) -> None:
        d = self._data("t1_f23_05")
        assert_r2_warning_present(self, d.get("log_entries", []), "follow")

    # =========================================================================
    # Feature #24: Optional SDK candidate_initiative (5 tests)
    # =========================================================================
    def test_t1_f24_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f24_01")
        self.assertEqual(d.get("module_id"), "candidate_initiative")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f24_02_initiative_idle_module_state(self) -> None:
        d = self._data("t1_f24_02")
        st = assert_world_module_entry(self, d["world"], "candidate_initiative")
        self.assertEqual(st.get("schema"), 2)
        self.assertEqual(st.get("phase"), "idle")
        self.assertEqual(st.get("members"), [])

    def test_t1_f24_03_initiative_active_encounter_members(self) -> None:
        d = self._data("t1_f24_03")
        st = assert_world_module_entry(self, d["world"], "candidate_initiative")
        self.assertEqual(st.get("phase"), "active")
        self.assertEqual(st.get("round"), 1)
        self.assertEqual(st.get("current_id"), HEX32_A)

    def test_t1_f24_04_attach_comp_initiative_on_unit(self) -> None:
        d = self._data("t1_f24_04")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://scenes/candidates/initiative/components/comp_initiative.gd")
        self.assertEqual(comp["state"].get("count"), 18)

    def test_t1_f24_05_initiative_roundtrip_and_disabled_warn(self) -> None:
        d = self._data("t1_f24_05")
        assert_r2_warning_present(self, d.get("log_entries", []), "candidate_initiative")
        self.assertEqual(d.get("roundtrip_diff"), "")

    # =========================================================================
    # Feature #25: Optional SDK dice (5 tests)
    # =========================================================================
    def test_t1_f25_01_plugin_script_and_availability(self) -> None:
        d = self._data("t1_f25_01")
        self.assertEqual(d.get("module_id"), "dice")
        self.assertIs(d.get("is_enabled"), True)

    def test_t1_f25_02_dice_schema5_workspace_v4(self) -> None:
        d = self._data("t1_f25_02")
        st = assert_world_module_entry(self, d["world"], "dice")
        self.assertEqual(st.get("schema_version"), 5)
        self.assertEqual(st["workspace"].get("schema_version"), 4)

    def test_t1_f25_03_dice_combos_and_burst_expr(self) -> None:
        d = self._data("t1_f25_03")
        st = assert_world_module_entry(self, d["world"], "dice")
        self.assertEqual(st["workspace"]["combos"][0]["expr"], "burst(2d6)")

    def test_t1_f25_04_dice_themes_and_visibility(self) -> None:
        d = self._data("t1_f25_04")
        ws = assert_world_module_entry(self, d["world"], "dice")["workspace"]
        self.assertEqual(ws.get("theme_id"), "godot_blue_cat_eye")
        self.assertEqual(ws.get("visibility"), "private")

    def test_t1_f25_05_dice_roundtrip_and_disabled_warn(self) -> None:
        d = self._data("t1_f25_05")
        assert_r2_warning_present(self, d.get("log_entries", []), "dice")
        self.assertEqual(d.get("roundtrip_diff"), "")

    # =========================================================================
    # Feature #26: Optional SDK Playtest-Blocked campaign_time (5 tests)
    # =========================================================================
    def test_t1_f26_01_plugin_script_and_playtest_blocked_status(self) -> None:
        d = self._data("t1_f26_01")
        self.assertEqual(d.get("module_id"), "campaign_time")
        self.assertIs(d.get("is_enabled"), False)
        self.assertEqual(d["availability"].get("status"), "playtest_blocked")

    def test_t1_f26_02_campaign_time_write_under_preserve_emits_blocked_warning(self) -> None:
        d = self._data("t1_f26_02")
        assert_r2_warning_present(self, d.get("log_entries", []), "campaign_time", status="playtest_blocked", policy="preserve")
        assert_world_module_entry(self, d["world"], "campaign_time")

    def test_t1_f26_03_campaign_time_schema_era_sources_effects(self) -> None:
        d = self._data("t1_f26_02")
        st = assert_world_module_entry(self, d["world"], "campaign_time")
        self.assertEqual(st.get("minute"), 720)
        self.assertRegex(st.get("era", ""), UID_32_RE)
        self.assertIn(HEX32_B, st.get("sources", {}))
        self.assertIn(HEX32_B, st.get("effects", {}))

    def test_t1_f26_04_campaign_time_skip_policy(self) -> None:
        d = self._data("t1_f26_04")
        assert_r2_warning_present(self, d.get("log_entries", []), "campaign_time", status="playtest_blocked", policy="skip")
        self.assertNotIn("campaign_time", d["world"]["modules"]["entries"])

    def test_t1_f26_05_campaign_time_var_to_bytes_roundtrip(self) -> None:
        d = self._data("t1_f26_02")
        self.assertEqual(d.get("roundtrip_diff"), "")

    # =========================================================================
    # Feature #27: Optional SDK Playtest-Blocked dnd_opportunity (5 tests)
    # =========================================================================
    def test_t1_f27_01_plugin_script_and_playtest_blocked_status(self) -> None:
        d = self._data("t1_f27_01")
        self.assertEqual(d.get("module_id"), "dnd_opportunity")
        self.assertIs(d.get("is_enabled"), False)
        self.assertEqual(d["availability"].get("status"), "playtest_blocked")

    def test_t1_f27_02_dnd_opportunity_write_under_preserve_emits_blocked_warning(self) -> None:
        d = self._data("t1_f27_02")
        assert_r2_warning_present(self, d.get("log_entries", []), "dnd_opportunity", status="playtest_blocked", policy="preserve")
        assert_world_module_entry(self, d["world"], "dnd_opportunity")

    def test_t1_f27_03_dnd_opportunity_editions_2014_2024(self) -> None:
        d14 = self._data("t1_f27_02")
        d24 = self._data("t1_f27_03")
        st14 = assert_world_module_entry(self, d14["world"], "dnd_opportunity")
        st24 = assert_world_module_entry(self, d24["world"], "dnd_opportunity")
        self.assertEqual(st14["sheets"].get("opportunity_edition", 2014), 2014)
        self.assertEqual(st24["sheets"].get("opportunity_edition"), 2024)

    def test_t1_f27_04_dnd_opportunity_skip_policy(self) -> None:
        d = self._data("t1_f27_04")
        assert_r2_warning_present(self, d.get("log_entries", []), "dnd_opportunity", status="playtest_blocked", policy="skip")
        self.assertNotIn("dnd_opportunity", d["world"]["modules"]["entries"])

    def test_t1_f27_05_dnd_opportunity_var_to_bytes_roundtrip(self) -> None:
        d = self._data("t1_f27_02")
        self.assertEqual(d.get("roundtrip_diff"), "")

    # =========================================================================
    # Feature #28: R6 Console Log Mod & Git Tracking (5 tests)
    # =========================================================================
    def test_t1_f28_01_console_mod_manifest_contract(self) -> None:
        mod_dir = WORKSPACE_ROOT / "mods" / "sdk-log-console"
        manifest_path = mod_dir / "plugin.json"
        self.assertTrue(manifest_path.is_file(), f"Missing console mod manifest: {manifest_path}")
        raw = manifest_path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        manifest = json.loads(raw.decode("utf-8"))
        self.assertEqual(manifest.get("schema"), "fus.session-plugin.v1")
        self.assertEqual(manifest.get("host_api"), 1)
        self.assertEqual(manifest.get("scope"), "session")
        self.assertEqual(manifest.get("id"), "sdk_log_console")
        self.assertEqual(manifest.get("entry"), "entry.gd")
        self.assertTrue(manifest.get("import_extensions"))

    def test_t1_f28_02_console_mod_gitignore_and_git_tracking(self) -> None:
        gitignore_txt = (WORKSPACE_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!/mods/sdk-log-console/", gitignore_txt)
        self.assertFalse(is_git_ignored("mods/sdk-log-console/plugin.json"))
        tracked = list_git_tracked("mods/sdk-log-console/")
        self.assertIn("mods/sdk-log-console/plugin.json", tracked)
        self.assertIn("mods/sdk-log-console/entry.gd", tracked)

    def test_t1_f28_03_console_mod_no_forbidden_ui_mounting(self) -> None:
        mod_dir = WORKSPACE_ROOT / "mods" / "sdk-log-console"
        self.assertTrue(mod_dir.is_dir(), f"Missing console mod dir: {mod_dir}")
        for gd in sorted(mod_dir.rglob("*.gd")):
            txt = gd.read_text(encoding="utf-8")
            self.assertNotRegex(txt, re.compile(r"\b(?:Window|PopupPanel|Control)\.new\s*\("))
            self.assertNotIn("ui.desktop_panels", txt)

    def test_t1_f28_04_console_mod_cli_validate_and_build(self) -> None:
        assert self.session.build_dir is not None and self.session.cache_dir is not None
        r_val = run_fuvtt_cli(["validate", "sdk-log-console"], build_dir=self.session.build_dir, cache_dir=self.session.cache_dir)
        self.assertEqual(r_val.returncode, 0, f"validate sdk-log-console failed: {r_val.stdout}\n{r_val.stderr}")
        r_bld = run_fuvtt_cli(["build", "sdk-log-console"], build_dir=self.session.build_dir, cache_dir=self.session.cache_dir)
        self.assertEqual(r_bld.returncode, 0, f"build sdk-log-console failed: {r_bld.stdout}\n{r_bld.stderr}")
        assert_build_artifact_bundles_sdk(self, self.session.build_dir, "sdk-log-console")

    def test_t1_f28_05_console_mod_cli_verify_host_and_logs(self) -> None:
        assert self.session.build_dir is not None and self.session.cache_dir is not None
        r_ver = run_fuvtt_cli(["verify-host", "sdk-log-console"], build_dir=self.session.build_dir, cache_dir=self.session.cache_dir)
        self.assertEqual(r_ver.returncode, 0, f"verify-host sdk-log-console failed: {r_ver.stdout}\n{r_ver.stderr}")
        self.assertIn("[PASS] sdk-log-console", r_ver.stdout)

    # =========================================================================
    # Feature #29: R5 Tooling Sync (5 tests)
    # =========================================================================
    def test_t1_f29_01_build_bundles_all_modular_sdk_scripts(self) -> None:
        assert self.session.build_dir is not None and self.session.cache_dir is not None
        r_bld = run_fuvtt_cli(["build", "_template"], build_dir=self.session.build_dir, cache_dir=self.session.cache_dir)
        self.assertEqual(r_bld.returncode, 0, r_bld.stderr)
        assert_build_artifact_bundles_sdk(self, self.session.build_dir, "_template", expected_sdk_files=EXPECTED_MODULAR_SDK_FILES)

    def test_t1_f29_02_all_sdk_scripts_pass_gdscript_hygiene(self) -> None:
        cfg = load_workspace_config()
        for rel in EXPECTED_MODULAR_SDK_FILES:
            p = cfg.sdk_dir / rel
            self.assertTrue(p.is_file(), f"Missing expected modular SDK script: {p}")
            assert_gdscript_hygiene(self, p, sdk_root=cfg.sdk_dir)

    def test_t1_f29_03_verify_host_supports_sdk_and_template(self) -> None:
        assert self.session.build_dir is not None and self.session.cache_dir is not None
        r_ver = run_fuvtt_cli(["verify-host", "_template"], build_dir=self.session.build_dir, cache_dir=self.session.cache_dir)
        self.assertEqual(r_ver.returncode, 0, f"verify-host _template failed: {r_ver.stdout}\n{r_ver.stderr}")

    def test_t1_f29_04_host_verifier_and_client_inspector_unit_suite(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "shared/tools/tests/test_devtools.py"],
            cwd=str(WORKSPACE_ROOT),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.assertEqual(proc.returncode, 0, f"test_devtools.py failed:\n{proc.stdout}\n{proc.stderr}")

    def test_t1_f29_05_build_all_mods_succeeds(self) -> None:
        assert self.session.build_dir is not None and self.session.cache_dir is not None
        r_bld = run_fuvtt_cli(["build", "--all", "--include-template"], build_dir=self.session.build_dir, cache_dir=self.session.cache_dir)
        self.assertEqual(r_bld.returncode, 0, f"build --all failed: {r_bld.stdout}\n{r_bld.stderr}")

    # =========================================================================
    # Feature #30: R4 & R5 Env & Docs Compliance (5 tests)
    # =========================================================================
    def test_t1_f30_01_env_local_fus_repo_dir_and_godot_bin(self) -> None:
        cfg = load_workspace_config()
        self.assertIsNotNone(cfg.fus_repo_dir, "FUS_REPO_DIR not configured in .env.local")
        assert cfg.fus_repo_dir is not None
        self.assertTrue(cfg.fus_repo_dir.is_dir(), "Configured FUS_REPO_DIR does not exist")
        self.assertIsNotNone(cfg.godot_bin, "GODOT_BIN not configured in .env.local")
        assert cfg.godot_bin is not None
        self.assertTrue(cfg.godot_bin.is_file(), "Configured GODOT_BIN does not exist")

    def test_t1_f30_02_agents_md_placeholder_and_no_local_paths(self) -> None:
        txt = (WORKSPACE_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("<FUS_REPO_DIR>", txt)
        assert_no_local_paths_in_text(self, txt, label="AGENTS.md")

    def test_t1_f30_03_sdk_readme_documents_modular_sdk_and_logging(self) -> None:
        readme = WORKSPACE_ROOT / "shared" / "sdk" / "README.md"
        self.assertTrue(readme.is_file(), f"Missing {readme}")
        txt = readme.read_text(encoding="utf-8")
        assert_no_local_paths_in_text(self, txt, label="shared/sdk/README.md")
        for token in ("log_bus", "module_registry", "plugins/"):
            self.assertIn(token, txt, f"shared/sdk/README.md missing documentation for {token!r}")

    def test_t1_f30_04_shared_docs_updated_with_version_and_date(self) -> None:
        docs_dir = WORKSPACE_ROOT / "shared" / "docs"
        md_files = sorted(docs_dir.glob("*.md"))
        self.assertGreaterEqual(len(md_files), 4)
        combined = []
        for md in md_files:
            t = md.read_text(encoding="utf-8")
            assert_no_local_paths_in_text(self, t, label=md.name)
            combined.append(t)
        all_docs = "\n".join(combined)
        self.assertIn("LogBus", all_docs)
        self.assertIn("ModuleRegistry", all_docs)
        self.assertIn("sdk-log-console", all_docs)

    def test_t1_f30_05_fus_repo_dir_completely_unmodified(self) -> None:
        cfg = load_workspace_config()
        repo = cfg.resolve_fus_repo_dir()
        proc = run_git_readonly(["status", "-s"], repo_dir=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "", f"<FUS_REPO_DIR> has uncommitted changes: {proc.stdout}")
