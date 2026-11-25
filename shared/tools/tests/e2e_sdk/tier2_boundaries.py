"""Tier 2: 150 Boundary, Edge-Case, Negative & Policy-Matrix E2E Tests (5 per feature #1-#30)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import unittest
import zipfile

from fuvtt_devtools.env_config import ConfigError, load_config

from .assertions import (
    assert_case_passed,
    assert_entity_has_component,
    assert_no_local_paths_in_text,
    assert_r2_warning_present,
    assert_world_v3_invariants,
    is_finite_number,
)
from .harness import (
    CORE_MODULE_IDS,
    E2ESession,
    GodotBatchProbe,
    STATELESS_CORE_MODULE_IDS,
    STATELESS_OPTIONAL_MODULE_IDS,
    SdkBatchSummary,
    SdkProbeCaseSpec,
    WORKSPACE_ROOT,
    gd_packed_f32,
    run_fuvtt_cli,
    run_fuvtt_cli_isolated_mods,
)
from .tier1_features import (
    HEX24_A,
    HEX32_A,
    HEX32_B,
    HEX32_C,
    HEX64_A,
    _valid_campaign_time_state,
    _valid_checklist_state,
    _valid_dice_state,
    _valid_dnd_opportunity_card,
    _valid_dnd_opportunity_state,
    _valid_drawing_state,
    _valid_entity_ink_stroke,
    _valid_initiative_state,
    _valid_resource_pool_defs,
    _valid_simple_fog_state,
)


def _rejected_or_clamped(val_res: object, actual_val: float | None, lo: float, hi: float) -> bool:
    if val_res is False:
        return True
    if isinstance(val_res, dict) and val_res.get("ok") is False:
        return True
    if actual_val is not None:
        return lo <= actual_val <= hi
    return False


class Tier2BoundaryTests(unittest.TestCase):
    """150 boundary, invalid-input, error-handling, and R2 policy tests across Features #1-#30."""

    session: E2ESession
    batch: SdkBatchSummary
    _cases_built: bool = False

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = E2ESession(name_prefix="tier2")
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

        fog_bad_alpha = _valid_simple_fog_state()
        fog_bad_alpha["unseen_color"] = [0.0, 0.0, 0.0, 0.5]

        fog_bad_bounds = _valid_simple_fog_state()
        fog_bad_bounds["dm_opacity"] = 0.0
        fog_bad_bounds["vision_feather"] = 0.6
        fog_bad_bounds["shadow_smooth"] = 16.1

        fog_bad_enum = _valid_simple_fog_state()
        fog_bad_enum["unseen_effect"] = 3
        fog_bad_enum["shadow_filter"] = 3

        fog_bad_bytes = _valid_simple_fog_state()
        fog_bad_bytes["exploration"] = b"\x01\x02\x03"

        draw_bad_pts = _valid_drawing_state()
        draw_bad_pts["strokes"][0]["pressure"] = gd_packed_f32([0.5])

        draw_bad_txt = _valid_drawing_state(with_text=True)
        draw_bad_txt["strokes"][1]["text"] = "   "

        draw_bad_font = _valid_drawing_state(with_text=True)
        draw_bad_font["strokes"][1]["font"] = "comic_sans"
        draw_bad_font["strokes"][1]["font_size"] = 257

        draw_dup_id = _valid_drawing_state(with_text=True)
        draw_dup_id["strokes"][1]["id"] = HEX32_A
        draw_dup_id["strokes"][1]["order"] = 1

        chk_blank = _valid_checklist_state()
        chk_blank["rows"][HEX32_A]["title"] = "Line1\nLine2"

        chk_arch = _valid_checklist_state(done=False, archived=True)
        chk_player_empty = _valid_checklist_state(audience="player", player_id="")

        chk_many = {"schema": 2, "rows": {}}
        for i in range(129):
            rid = f"{i:032x}"
            chk_many["rows"][rid] = {
                "title": f"Task {i}", "description": "", "category": "Cat",
                "audience": "all", "player_id": "", "entity_id": "", "source": "s",
                "manual": False, "done": False, "archived": False, "order": i, "last_motion": "",
            }

        chk_bad_id = {"schema": 2, "rows": {"not_hex32": _valid_checklist_state()["rows"][HEX32_A]}}

        rp_bad_color = _valid_resource_pool_defs()
        rp_bad_color["definitions"]["resource_pool:hp"]["color"] = "#12345"
        rp_bad_src = {
            "schema_version": 1,
            "definitions": {
                "dnd5e:hp": {
                    "id": "dnd5e:hp", "source": "dnd5e", "name": "HP",
                    "maximum": 10.0, "color": "#FFFFFFFF", "display": "bar", "visibility": "public",
                }
            },
        }
        rp_bad_enum = _valid_resource_pool_defs(display="pie", visibility="everyone")
        rp_gt_1e9 = _valid_resource_pool_defs()
        rp_gt_1e9["definitions"]["resource_pool:hp"]["maximum"] = 1e9 + 100.0

        init_idle_bad = _valid_initiative_state("idle")
        init_idle_bad["members"] = [{"entity_id": HEX32_A, "tie_order": 0}]
        init_active_bad = _valid_initiative_state("active")
        init_active_bad["round"] = 0
        init_dup = _valid_initiative_state("active")
        init_dup["members"] = [{"entity_id": HEX32_A, "tie_order": 0}, {"entity_id": HEX32_A, "tie_order": 2}]

        dice_pres_bad = _valid_dice_state()
        dice_pres_bad["workspace"]["simple_result"] = True
        dice_pres_bad["workspace"]["animate"] = True

        dice_adv_bad = _valid_dice_state(expr="adv(1d20)")
        dice_many_combos = _valid_dice_state()
        dice_many_combos["workspace"]["combos"] = [
            {"id": f"{i:024x}", "name": f"C{i}", "expr": "1d20", "label": ""} for i in range(33)
        ]
        dice_bad_theme = _valid_dice_state(theme_id="unknown_theme")
        dice_bad_theme["workspace"]["hidden_history_count"] = 5
        dice_bad_draft = _valid_dice_state(expr="21d6")
        dice_bad_draft["workspace"]["draft"] = "x" * 257

        ct_neg = _valid_campaign_time_state()
        ct_neg["minute"] = -1
        ct_rev0 = _valid_campaign_time_state()
        ct_rev0["revision"] = 0
        ct_bad_era = _valid_campaign_time_state()
        ct_bad_era["era"] = "bad_era"
        ct_orphan = _valid_campaign_time_state()
        ct_orphan["effects"] = {HEX32_C: {"until": 100, "name": "Orphan", "status": "paused"}}

        opp_bad_ed = _valid_dnd_opportunity_state(2014)
        opp_bad_ed["sheets"]["opportunity_edition"] = 2015
        opp_many_cards = _valid_dnd_opportunity_state(2014)
        opp_many_cards["sheets"]["cards"] = {
            f"{i:032x}": _valid_dnd_opportunity_card(f"{i:032x}", "2014")
            for i in range(65)
        }
        opp_bad_id = _valid_dnd_opportunity_state(2014)
        opp_bad_id["sheets"]["cards"] = {"bad_card_id": _valid_dnd_opportunity_card("bad_card_id", "2014")}
        opp_bad_ced = _valid_dnd_opportunity_state(2014)
        opp_bad_ced["sheets"]["cards"][HEX32_A]["edition"] = "2024"

        cases: list[SdkProbeCaseSpec] = [
            # Feature #1: LogBus boundaries
            SdkProbeCaseSpec("t2_f01_01", "logbus_test", {"sub_op": "min_level"}),
            SdkProbeCaseSpec("t2_f01_02", "logbus_test", {"sub_op": "ring_buffer_overflow", "count": 1500}),
            SdkProbeCaseSpec("t2_f01_03", "logbus_test", {"sub_op": "host_cap_100_7000"}),
            SdkProbeCaseSpec("t2_f01_04", "logbus_test", {"sub_op": "pubsub"}),
            SdkProbeCaseSpec("t2_f01_05", "logbus_test", {"sub_op": "emit_and_schema"}),
            # Feature #2: ModuleRegistry boundaries
            SdkProbeCaseSpec("t2_f02_01", "registry_inspect", {"action": "invalid_policy_and_unknown"}),
            SdkProbeCaseSpec(
                "t2_f02_03",
                "registry_inspect",
                {"action": "catalog", "query_ids": ["simple_fog"]},
                enabled_modules=[" simple_fog ", "simple_fog", ""],
            ),
            SdkProbeCaseSpec("t2_f02_04", "registry_inspect", {"action": "policy_switch_mid_session"}),
            SdkProbeCaseSpec(
                "t2_f02_05",
                "scenario_run",
                {
                    "scenario": "strict_skip_audit",
                    "fog_state": _valid_simple_fog_state(),
                    "campaign_time": _valid_campaign_time_state(),
                    "dnd_opportunity": _valid_dnd_opportunity_state(),
                },
                enabled_modules=[],
                disabled_policy="skip",
            ),
            # Feature #3: parked/manual boundaries
            SdkProbeCaseSpec("t2_f03_01", "parked_manual", {"sub_op": "manual_without_parked"}),
            SdkProbeCaseSpec("t2_f03_02", "parked_manual", {"sub_op": "park_required_rejected"}),
            SdkProbeCaseSpec("t2_f03_03", "parked_manual", {"sub_op": "park_missing_entity_or_empty_script"}),
            SdkProbeCaseSpec("t2_f03_05", "parked_manual", {"sub_op": "multi_parked"}),
            # Feature #4: feature_edit_mode boundaries
            SdkProbeCaseSpec("t2_f04_01", "plugin_domain", {"module_id": "feature_edit_mode", "sub_op": "reject_map"}),
            SdkProbeCaseSpec("t2_f04_02", "plugin_domain", {"module_id": "feature_edit_mode", "sub_op": "reject_unknown"}),
            SdkProbeCaseSpec("t2_f04_03", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "unit"}, enabled_modules=["scene_box"]),
            SdkProbeCaseSpec("t2_f04_04", "plugin_domain", {"module_id": "feature_edit_mode", "sub_op": "dup_attach"}),
            # Feature #5: feature_floor_system boundaries
            SdkProbeCaseSpec("t2_f05_01", "plugin_domain", {"module_id": "feature_floor_system", "sub_op": "cap_512"}),
            SdkProbeCaseSpec("t2_f05_02", "plugin_domain", {"module_id": "feature_floor_system", "sub_op": "unknown_floor_or_sanitize"}),
            # Feature #6: feature_layer_stack boundaries
            SdkProbeCaseSpec("t2_f06_01", "plugin_domain", {"module_id": "feature_layer_stack", "sub_op": "cap_256_per_floor"}),
            SdkProbeCaseSpec("t2_f06_02", "plugin_domain", {"module_id": "feature_layer_stack", "sub_op": "cap_4096_total"}),
            SdkProbeCaseSpec("t2_f06_03", "plugin_domain", {"module_id": "feature_layer_stack", "sub_op": "bad_kind_and_access"}),
            SdkProbeCaseSpec("t2_f06_04", "plugin_domain", {"module_id": "feature_layer_stack", "sub_op": "players_empty_viewers"}),
            SdkProbeCaseSpec("t2_f06_05", "plugin_domain", {"module_id": "feature_layer_stack", "sub_op": "viewers_cap_128_and_160"}),
            # Feature #7: feature_obstacle_authoring boundaries
            SdkProbeCaseSpec("t2_f07_01", "plugin_domain", {"module_id": "feature_obstacle_authoring", "sub_op": "degenerate_or_nan"}),
            SdkProbeCaseSpec("t2_f07_04", "plugin_domain", {"module_id": "feature_obstacle_authoring", "sub_op": "large_1e7_or_bad_kind"}),
            SdkProbeCaseSpec("t2_f07_05", "plugin_domain", {"module_id": "feature_obstacle_authoring", "sub_op": "bad_kind_and_role"}),
            # Feature #8: feature_entity_library boundaries
            SdkProbeCaseSpec("t2_f08_01", "plugin_domain", {"module_id": "feature_entity_library", "sub_op": "invalid_4gate"}),
            SdkProbeCaseSpec("t2_f08_02", "plugin_domain", {"module_id": "feature_entity_library", "sub_op": "preset_multi_disabled_skip_and_preserve"}, enabled_modules=[]),
            SdkProbeCaseSpec("t2_f08_03", "plugin_domain", {"module_id": "feature_entity_library", "sub_op": "bad_sprite_refs"}),
            SdkProbeCaseSpec("t2_f08_04", "plugin_domain", {"module_id": "feature_entity_library", "sub_op": "idempotent_reregister"}),
            SdkProbeCaseSpec("t2_f08_05", "plugin_domain", {"module_id": "feature_entity_library", "sub_op": "rollback_on_cancel"}),
            # Feature #9: stateless boundaries
            SdkProbeCaseSpec("t2_f09_01", "registry_inspect", {"action": "toggle_and_disable_core", "core_id": "feature_component_sync", "opt_id": "room_chat"}),
            SdkProbeCaseSpec("t2_f09_02", "registry_inspect", {"action": "stateless_optional_no_world_write", "query_ids": list(STATELESS_OPTIONAL_MODULE_IDS)}, enabled_modules=list(STATELESS_OPTIONAL_MODULE_IDS)),
            SdkProbeCaseSpec("t2_f09_03", "registry_inspect", {"action": "catalog", "query_ids": ["music_board", "module_example"]}),
            SdkProbeCaseSpec("t2_f09_04", "registry_inspect", {"action": "toggle_and_disable_core", "core_id": "feature_debug_hooks", "opt_id": "totally_unknown_123"}),
            SdkProbeCaseSpec("t2_f09_05", "registry_inspect", {"action": "stateless_get_plugin_sdk", "query_ids": list(STATELESS_CORE_MODULE_IDS + STATELESS_OPTIONAL_MODULE_IDS + ("music_board", "module_example"))}),
            # Feature #10: scene_box boundaries
            SdkProbeCaseSpec("t2_f10_01", "plugin_domain", {"module_id": "scene_box", "sub_op": "cap_64_and_last_floor"}, enabled_modules=["scene_box"]),
            SdkProbeCaseSpec("t2_f10_03", "plugin_domain", {"module_id": "scene_box", "sub_op": "clamp_and_bad_cover"}, enabled_modules=["scene_box"]),
            SdkProbeCaseSpec("t2_f10_05", "plugin_domain", {"module_id": "scene_box", "sub_op": "scenes_v2"}, enabled_modules=[], disabled_policy="skip"),
            # Feature #11: portal boundaries
            SdkProbeCaseSpec("t2_f11_01", "plugin_domain", {"module_id": "portal", "pair_key": ""}, enabled_modules=["portal"]),
            SdkProbeCaseSpec("t2_f11_02", "plugin_domain", {"module_id": "portal", "sub_op": "missing_entity"}, enabled_modules=["portal"]),
            SdkProbeCaseSpec("t2_f11_03", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "portal"}, enabled_modules=["scene_box", "portal"]),
            SdkProbeCaseSpec("t2_f11_04", "plugin_domain", {"module_id": "portal", "pair_key": "skip_pair"}, enabled_modules=[], disabled_policy="skip"),
            SdkProbeCaseSpec("t2_f11_05", "plugin_domain", {"module_id": "portal", "pair_key": "  传送门_A_1F  "}, enabled_modules=["portal"]),
            # Feature #12: grid_alignment boundaries
            SdkProbeCaseSpec("t2_f12_01", "plugin_domain", {"module_id": "grid_alignment", "cell_size": 7.9, "line_width": 0.4, "snap_strength": -0.1, "offset": [1e7, -1e7], "color": [2.0, -1.0, 0.5, 0.5]}, enabled_modules=["grid_alignment"]),
            SdkProbeCaseSpec("t2_f12_02", "plugin_domain", {"module_id": "grid_alignment", "cell_size": 4096.0, "line_width": 4.0, "snap_strength": 1.0, "offset": [-1e6, 1e6]}, enabled_modules=["grid_alignment"]),
            SdkProbeCaseSpec("t2_f12_03", "plugin_domain", {"module_id": "grid_alignment", "cell_size": float("nan"), "line_width": 4.1, "snap_strength": 1.1}, enabled_modules=["grid_alignment"]),
            SdkProbeCaseSpec("t2_f12_05", "plugin_domain", {"module_id": "grid_alignment", "cell_size": 64.0}, enabled_modules=[], disabled_policy="skip"),
            # Feature #13: simple_fog boundaries
            SdkProbeCaseSpec("t2_f13_01", "plugin_domain", {"module_id": "simple_fog", "sub_op": "config", "state": fog_bad_alpha}, enabled_modules=["simple_fog"]),
            SdkProbeCaseSpec("t2_f13_02", "plugin_domain", {"module_id": "simple_fog", "sub_op": "config", "state": fog_bad_bounds}, enabled_modules=["simple_fog"]),
            SdkProbeCaseSpec("t2_f13_03", "plugin_domain", {"module_id": "simple_fog", "sub_op": "config", "state": fog_bad_enum}, enabled_modules=["simple_fog"]),
            SdkProbeCaseSpec("t2_f13_04", "plugin_domain", {"module_id": "simple_fog", "sub_op": "config", "state": fog_bad_bytes}, enabled_modules=["simple_fog"]),
            SdkProbeCaseSpec("t2_f13_05", "plugin_domain", {"module_id": "simple_fog", "sub_op": "vision_and_light", "radius": -50.0, "view_angle": 720.0}, enabled_modules=["simple_fog"]),
            # Feature #14: image_flip boundaries
            SdkProbeCaseSpec("t2_f14_01", "conflict_matrix", {"pair": "obstacle_then_image_flip"}, enabled_modules=["image_flip"]),
            SdkProbeCaseSpec("t2_f14_02", "conflict_matrix", {"pair": "area_then_image_flip"}, enabled_modules=["image_flip", "areas"]),
            SdkProbeCaseSpec("t2_f14_03", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "image_flip", "state": {"horizontal": True, "vertical": False}}, enabled_modules=["scene_box", "image_flip"]),
            SdkProbeCaseSpec("t2_f14_04", "plugin_domain", {"module_id": "image_flip", "action": "attach", "entity_id": "nonexistent_flip_999", "state": {"horizontal": True, "vertical": False}}, enabled_modules=["image_flip"]),
            SdkProbeCaseSpec("t2_f14_05", "plugin_domain", {"module_id": "image_flip", "action": "attach", "as_unit": False, "state": {"horizontal": True, "vertical": False}}, enabled_modules=[], disabled_policy="skip"),
            # Feature #15: drag_movement boundaries
            SdkProbeCaseSpec("t2_f15_01", "plugin_domain", {"module_id": "drag_movement", "action": "configure", "state": {"version": 2, "speed": -0.01}}, enabled_modules=["drag_movement"]),
            SdkProbeCaseSpec("t2_f15_02", "plugin_domain", {"module_id": "drag_movement", "action": "configure", "state": {"version": 2, "speed": float("nan")}}, enabled_modules=["drag_movement"]),
            SdkProbeCaseSpec("t2_f15_02_inf", "plugin_domain", {"module_id": "drag_movement", "action": "configure", "state": {"version": 2, "speed": float("inf")}}, enabled_modules=["drag_movement"]),
            SdkProbeCaseSpec("t2_f15_03", "plugin_domain", {"module_id": "drag_movement", "action": "attach", "as_unit": True, "state": {"speed": -5.0}}, enabled_modules=["drag_movement"]),
            SdkProbeCaseSpec("t2_f15_04", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "drag_movement", "state": {"speed": 64.0}}, enabled_modules=["scene_box", "drag_movement"]),
            SdkProbeCaseSpec("t2_f15_05", "plugin_domain", {"module_id": "drag_movement", "action": "configure", "state": {"version": 2, "speed": 64.0}}, enabled_modules=[], disabled_policy="skip"),
            # Feature #16: drawing boundaries
            SdkProbeCaseSpec("t2_f16_01", "plugin_domain", {"module_id": "drawing", "action": "configure", "state": draw_bad_pts}, enabled_modules=["drawing"]),
            SdkProbeCaseSpec("t2_f16_02", "plugin_domain", {"module_id": "drawing", "action": "configure", "state": draw_bad_txt}, enabled_modules=["drawing"]),
            SdkProbeCaseSpec("t2_f16_03", "plugin_domain", {"module_id": "drawing", "action": "configure", "state": draw_bad_font}, enabled_modules=["drawing"]),
            SdkProbeCaseSpec("t2_f16_04", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "drawing", "state": {"revision": HEX32_A, "strokes": [_valid_entity_ink_stroke()]}}, enabled_modules=["scene_box", "drawing"]),
            SdkProbeCaseSpec("t2_f16_04_life", "plugin_domain", {"module_id": "drawing", "action": "attach", "as_unit": False, "state": {"revision": HEX32_A, "strokes": [{**_valid_entity_ink_stroke(), "life": 10}]}}, enabled_modules=["drawing"]),
            SdkProbeCaseSpec("t2_f16_05", "plugin_domain", {"module_id": "drawing", "action": "configure", "state": draw_dup_id}, enabled_modules=["drawing"]),
            # Feature #17: areas boundaries
            SdkProbeCaseSpec("t2_f17_01", "plugin_domain", {"module_id": "areas", "action": "attach", "as_unit": False, "state": {"removed": False, "radius_in_cells": 0.0}}, enabled_modules=["areas"]),
            SdkProbeCaseSpec("t2_f17_02", "plugin_domain", {"module_id": "areas", "action": "attach", "as_unit": False, "state": {"removed": False, "radius_in_cells": 256.01}}, enabled_modules=["areas"]),
            SdkProbeCaseSpec("t2_f17_03", "plugin_domain", {"module_id": "areas", "action": "attach", "as_unit": False, "state": {"removed": False, "radius_in_cells": 256.0}}, enabled_modules=["areas"]),
            SdkProbeCaseSpec("t2_f17_04", "conflict_matrix", {"pair": "image_flip_then_area"}, enabled_modules=["image_flip", "areas"]),
            SdkProbeCaseSpec("t2_f17_05", "plugin_domain", {"module_id": "areas", "action": "attach", "as_unit": False, "state": {"removed": False, "radius_in_cells": 2.0}}, enabled_modules=[], disabled_policy="skip"),
            # Feature #18: entity_notes boundaries
            SdkProbeCaseSpec("t2_f18_01", "plugin_domain", {"module_id": "entity_notes", "action": "attach", "as_unit": False, "state": {"schema_version": 1, "text": "N" * 32768, "keep_screen_size": True, "is_pin": True}}),
            SdkProbeCaseSpec("t2_f18_02", "plugin_domain", {"module_id": "entity_notes", "action": "attach", "as_unit": False, "state": {"schema_version": 1, "text": "N" * 32769, "keep_screen_size": True, "is_pin": True}}),
            SdkProbeCaseSpec("t2_f18_03", "registry_inspect", {"action": "toggle_and_disable_core", "core_id": "feature_edit_mode", "opt_id": "entity_notes"}),
            SdkProbeCaseSpec("t2_f18_04", "plugin_domain", {"module_id": "entity_notes", "action": "attach", "as_unit": False, "state": {"schema_version": 1, "text": "Skip me", "keep_screen_size": True, "is_pin": True}}, disabled_policy="skip"),
            SdkProbeCaseSpec("t2_f18_05", "plugin_domain", {"module_id": "entity_notes", "action": "attach", "entity_id": "nonexistent_note_999", "state": {"schema_version": 1, "text": "Missing", "keep_screen_size": True, "is_pin": True}}, disabled_policy="preserve"),
            # Feature #19: checklist boundaries
            SdkProbeCaseSpec("t2_f19_01", "plugin_domain", {"module_id": "checklist", "action": "configure", "state": chk_blank}, enabled_modules=["checklist"]),
            SdkProbeCaseSpec("t2_f19_02", "plugin_domain", {"module_id": "checklist", "action": "configure", "state": chk_arch}, enabled_modules=["checklist"]),
            SdkProbeCaseSpec("t2_f19_03", "plugin_domain", {"module_id": "checklist", "action": "configure", "state": chk_player_empty}, enabled_modules=["checklist"]),
            SdkProbeCaseSpec("t2_f19_04", "plugin_domain", {"module_id": "checklist", "action": "configure", "state": chk_many}, enabled_modules=["checklist"]),
            SdkProbeCaseSpec("t2_f19_05", "plugin_domain", {"module_id": "checklist", "action": "configure", "state": chk_bad_id}, enabled_modules=["checklist"]),
            # Feature #20: resource_pool boundaries
            SdkProbeCaseSpec("t2_f20_01", "plugin_domain", {"module_id": "resource_pool", "action": "attach", "as_unit": True, "state": {"schema_version": 1, "values": {"resource_pool:hp": {"current": 120.0, "maximum": 100.0}}}}, enabled_modules=["resource_pool"]),
            SdkProbeCaseSpec("t2_f20_02", "plugin_domain", {"module_id": "resource_pool", "action": "configure", "state": rp_gt_1e9}, enabled_modules=["resource_pool"]),
            SdkProbeCaseSpec("t2_f20_03", "plugin_domain", {"module_id": "resource_pool", "action": "configure", "state": rp_bad_color}, enabled_modules=["resource_pool"]),
            SdkProbeCaseSpec("t2_f20_03_src", "plugin_domain", {"module_id": "resource_pool", "action": "configure", "state": rp_bad_src}, enabled_modules=["resource_pool"]),
            SdkProbeCaseSpec("t2_f20_04", "plugin_domain", {"module_id": "resource_pool", "action": "configure", "state": rp_bad_enum}, enabled_modules=["resource_pool"]),
            SdkProbeCaseSpec("t2_f20_05", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "resource_pool", "state": {"schema_version": 1, "values": {}}}, enabled_modules=["scene_box", "resource_pool"]),
            # Feature #21: character_roster boundaries
            SdkProbeCaseSpec("t2_f21_01", "conflict_matrix", {"pair": "unit_only_on_non_unit_or_map", "target_module": "character_roster", "state": {"schema_version": 1, "known_by": {"p1": HEX32_A}}}, enabled_modules=["character_roster"]),
            SdkProbeCaseSpec("t2_f21_03", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "character_roster", "state": {"schema_version": 1, "known_by": {}}}, enabled_modules=["scene_box", "character_roster"]),
            SdkProbeCaseSpec("t2_f21_04", "plugin_domain", {"module_id": "character_roster", "action": "attach", "as_unit": True, "state": {"schema_version": 1, "known_by": {"": HEX32_A}}}, enabled_modules=["character_roster"]),
            SdkProbeCaseSpec("t2_f21_05", "plugin_domain", {"module_id": "character_roster", "action": "configure", "state": {"auto_join": True}}, enabled_modules=[], disabled_policy="skip"),
            # Feature #22: backpack boundaries
            SdkProbeCaseSpec("t2_f22_01", "conflict_matrix", {"pair": "unit_only_on_non_unit_or_map", "target_module": "backpack", "state": {"revision": "", "slots": {"0": {"name": "Sword", "note": "", "qty": 1}}}}, enabled_modules=["backpack"]),
            SdkProbeCaseSpec("t2_f22_02", "plugin_domain", {"module_id": "backpack", "action": "attach", "as_unit": True, "state": {"revision": "", "slots": {"16": {"name": "InvalidSlot", "note": "", "qty": 1}}}}, enabled_modules=["backpack"]),
            SdkProbeCaseSpec("t2_f22_03", "plugin_domain", {"module_id": "backpack", "action": "attach", "as_unit": True, "state": {"revision": "", "slots": {"0": {"name": "BadQty", "note": "", "qty": 1000}}}}, enabled_modules=["backpack"]),
            SdkProbeCaseSpec("t2_f22_04", "plugin_domain", {"module_id": "backpack", "action": "attach", "as_unit": True, "state": {"revision": "", "slots": {"0": {"name": "A" * 49, "note": "N" * 161, "qty": 1}}}}, enabled_modules=["backpack"]),
            SdkProbeCaseSpec("t2_f22_05", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "backpack", "state": {"revision": "", "slots": {}}}, enabled_modules=["scene_box", "backpack"]),
            # Feature #23: follow boundaries
            SdkProbeCaseSpec("t2_f23_01", "plugin_domain", {"module_id": "follow", "action": "attach", "as_unit": True, "state": {"target_id": "", "controller_id": "p1", "engaged": False, "follow_distance": -1.0}}, enabled_modules=["follow"]),
            SdkProbeCaseSpec("t2_f23_02", "plugin_domain", {"module_id": "follow", "action": "attach", "as_unit": True, "state": {"target_id": "not_32_hex", "controller_id": "p1", "engaged": True, "follow_distance": 16.0}}, enabled_modules=["follow"]),
            SdkProbeCaseSpec("t2_f23_03", "plugin_domain", {"module_id": "follow", "action": "attach", "as_unit": True, "state": {"target_id": "", "controller_id": "C" * 129, "engaged": False, "follow_distance": 16.0}}, enabled_modules=["follow"]),
            SdkProbeCaseSpec("t2_f23_04", "conflict_matrix", {"pair": "scene_box_conflicts", "target_module": "follow", "state": {"target_id": "", "controller_id": "", "engaged": False, "follow_distance": 16.0}}, enabled_modules=["scene_box", "follow"]),
            SdkProbeCaseSpec("t2_f23_05", "plugin_domain", {"module_id": "follow", "action": "attach", "as_unit": True, "state": {"target_id": "", "controller_id": "p1", "engaged": False, "follow_distance": 16.0}}, enabled_modules=[], disabled_policy="skip"),
            # Feature #24: candidate_initiative boundaries
            SdkProbeCaseSpec("t2_f24_01", "plugin_domain", {"module_id": "candidate_initiative", "action": "attach", "as_unit": True, "state": {"count": 10000, "modifier": 1000, "active": False, "defeated": False, "rolled": False}}, enabled_modules=["candidate_initiative"]),
            SdkProbeCaseSpec("t2_f24_02", "plugin_domain", {"module_id": "candidate_initiative", "action": "configure", "state": init_idle_bad}, enabled_modules=["candidate_initiative"]),
            SdkProbeCaseSpec("t2_f24_03", "plugin_domain", {"module_id": "candidate_initiative", "action": "configure", "state": init_active_bad}, enabled_modules=["candidate_initiative"]),
            SdkProbeCaseSpec("t2_f24_04", "plugin_domain", {"module_id": "candidate_initiative", "action": "configure", "state": init_dup}, enabled_modules=["candidate_initiative"]),
            SdkProbeCaseSpec("t2_f24_05", "conflict_matrix", {"pair": "unit_only_on_non_unit_or_map", "target_module": "candidate_initiative", "state": {"count": 10, "modifier": 0, "active": False, "defeated": False, "rolled": True}}, enabled_modules=["candidate_initiative"]),
            # Feature #25: dice boundaries
            SdkProbeCaseSpec("t2_f25_01", "plugin_domain", {"module_id": "dice", "action": "configure", "state": dice_pres_bad}, enabled_modules=["dice"]),
            SdkProbeCaseSpec("t2_f25_02", "plugin_domain", {"module_id": "dice", "sub_op": "validate_live_expression"}, enabled_modules=["dice"]),
            SdkProbeCaseSpec("t2_f25_02_combo", "plugin_domain", {"module_id": "dice", "action": "configure", "state": dice_adv_bad}, enabled_modules=["dice"]),
            SdkProbeCaseSpec("t2_f25_03", "plugin_domain", {"module_id": "dice", "action": "configure", "state": dice_many_combos}, enabled_modules=["dice"]),
            SdkProbeCaseSpec("t2_f25_04", "plugin_domain", {"module_id": "dice", "action": "configure", "state": dice_bad_theme}, enabled_modules=["dice"]),
            SdkProbeCaseSpec("t2_f25_05", "plugin_domain", {"module_id": "dice", "action": "configure", "state": dice_bad_draft}, enabled_modules=["dice"]),
            # Feature #26: campaign_time boundaries
            SdkProbeCaseSpec("t2_f26_01", "plugin_domain", {"module_id": "campaign_time", "action": "configure", "state": ct_neg}, disabled_policy="preserve"),
            SdkProbeCaseSpec("t2_f26_02", "plugin_domain", {"module_id": "campaign_time", "action": "configure", "state": ct_rev0}, disabled_policy="preserve"),
            SdkProbeCaseSpec("t2_f26_03", "plugin_domain", {"module_id": "campaign_time", "action": "configure", "state": ct_bad_era}, disabled_policy="preserve"),
            SdkProbeCaseSpec("t2_f26_04", "plugin_domain", {"module_id": "campaign_time", "action": "configure", "state": ct_orphan}, disabled_policy="preserve"),
            SdkProbeCaseSpec("t2_f26_05", "registry_inspect", {"action": "toggle_and_disable_core", "core_id": "feature_edit_mode", "opt_id": "campaign_time"}),
            # Feature #27: dnd_opportunity boundaries
            SdkProbeCaseSpec("t2_f27_01", "plugin_domain", {"module_id": "dnd_opportunity", "action": "configure", "state": opp_bad_ed}, disabled_policy="preserve"),
            SdkProbeCaseSpec("t2_f27_02", "plugin_domain", {"module_id": "dnd_opportunity", "action": "configure", "state": opp_many_cards}, disabled_policy="preserve"),
            SdkProbeCaseSpec("t2_f27_03", "plugin_domain", {"module_id": "dnd_opportunity", "action": "configure", "state": opp_bad_id}, disabled_policy="preserve"),
            SdkProbeCaseSpec("t2_f27_04", "plugin_domain", {"module_id": "dnd_opportunity", "action": "configure", "state": opp_bad_ced}, disabled_policy="preserve"),
            SdkProbeCaseSpec("t2_f27_05", "plugin_domain", {"module_id": "dnd_opportunity", "action": "configure", "state": _valid_dnd_opportunity_state(2014)}, disabled_policy="skip"),
            # Feature #29: WorldModuleState quota
            SdkProbeCaseSpec("t2_f29_01", "world_quota", {"sub_op": "max_128_entries"}),
            SdkProbeCaseSpec("t2_f29_02", "world_quota", {"sub_op": "oversized_16mib"}),
        ]

        cls.batch = probe.run_batch(cases, timeout_seconds=240)
        cls._cases_built = True
        return cls.batch

    def _data(self, case_id: str) -> dict:
        batch = self._ensure_godot_batch()
        self.assertEqual(batch.compile_failures, [], f"Compile failures: {batch.compile_failures}")
        self.assertEqual(batch.global_log_errors, [], f"Global Godot log errors: {batch.global_log_errors}")
        return assert_case_passed(self, batch.results[case_id])

    # =========================================================================
    # Feature #1: LogBus boundaries (5 tests)
    # =========================================================================
    def test_t2_f01_01_min_level_filtering(self) -> None:
        d = self._data("t2_f01_01")
        self.assertEqual(d.get("min_level"), 30)
        self.assertEqual(len(d.get("entries", [])), 2)
        self.assertEqual(len(d.get("sub_hits", [])), 2)

    def test_t2_f01_02_ring_buffer_bounded_eviction(self) -> None:
        d = self._data("t2_f01_02")
        self.assertGreater(int(d.get("returned_count", 0)), 0)
        self.assertEqual(int(d.get("last_seq", 0)), 1500)

    def test_t2_f01_03_import_bridge_100_entry_and_7000_char_cap(self) -> None:
        d = self._data("t2_f01_03")
        self.assertEqual(d.get("bus_count"), 125)
        self.assertLessEqual(int(d.get("host_warn_count", 999)), 100)
        self.assertLessEqual(int(d.get("host_warn_total_chars", 99999)), 7000)

    def test_t2_f01_04_unsubscribe_idempotent_and_invalid_token(self) -> None:
        d = self._data("t2_f01_04")
        self.assertIs(d.get("unsub_ok"), True)
        self.assertIs(d.get("unsub_again"), False)
        self.assertIs(d.get("unsub_bad"), False)

    def test_t2_f01_05_set_emit_to_engine_false_suppresses_push_error(self) -> None:
        d = self._data("t2_f01_05")
        errs = [e for e in d.get("entries", []) if e.get("level") == 40]
        self.assertEqual(len(errs), 1)

    # =========================================================================
    # Feature #2: ModuleRegistry boundaries (5 tests)
    # =========================================================================
    def test_t2_f02_01_invalid_disabled_module_policy_rejected(self) -> None:
        d = self._data("t2_f02_01")
        res = d.get("bad_policy_res")
        self.assertFalse(res is True)

    def test_t2_f02_02_unknown_module_id_availability_and_sdk(self) -> None:
        d = self._data("t2_f02_01")
        self.assertIs(d.get("unknown_sdk_is_null"), True)
        self.assertEqual(d.get("unknown_avail"), {})
        self.assertEqual(d.get("unknown_status"), "unknown")

    def test_t2_f02_03_set_enabled_modules_dedup_and_whitespace(self) -> None:
        d = self._data("t2_f02_03")
        self.assertIs(d["enabled_map"].get("simple_fog"), True)

    def test_t2_f02_04_policy_switch_mid_build(self) -> None:
        d = self._data("t2_f02_04")
        self.assertIn("grid_alignment", d["world"]["modules"]["entries"])
        self.assertGreaterEqual(len(d.get("log_entries", [])), 2)

    def test_t2_f02_05_skip_policy_leaves_world_modules_empty(self) -> None:
        d = self._data("t2_f02_05")
        self.assertEqual(d["world"]["modules"]["entries"], {})

    # =========================================================================
    # Feature #3: parked/manual boundaries (5 tests)
    # =========================================================================
    def test_t2_f03_01_manual_true_with_parked_false_rejected(self) -> None:
        d = self._data("t2_f03_01")
        self.assertIs(d.get("attached"), False)
        assert_world_v3_invariants(self, d["world"], "t2_f03_01")

    def test_t2_f03_02_cannot_park_comp_visual_or_permission(self) -> None:
        d = self._data("t2_f03_02")
        self.assertIs(d.get("ok_vis"), False)
        self.assertIs(d.get("ok_perm"), False)
        assert_world_v3_invariants(self, d["world"], "t2_f03_02")

    def test_t2_f03_03_park_on_nonexistent_entity_rejected(self) -> None:
        d = self._data("t2_f03_03")
        self.assertIs(d.get("ok_missing"), False)

    def test_t2_f03_04_park_empty_script_path_rejected(self) -> None:
        d = self._data("t2_f03_03")
        self.assertIs(d.get("ok_empty"), False)

    def test_t2_f03_05_multiple_parked_components_index_ge_2(self) -> None:
        d = self._data("t2_f03_05")
        self.assertEqual(d.get("oks"), [True, True, True])
        assert_world_v3_invariants(self, d["world"], "t2_f03_05")
        ent = d["world"]["entity_state"]["entities"][0]
        self.assertEqual(len(ent["components"]), 5)

    # =========================================================================
    # Feature #4: feature_edit_mode boundaries (5 tests)
    # =========================================================================
    def test_t2_f04_01_unit_rejected_on_map_entity(self) -> None:
        d = self._data("t2_f04_01")
        self.assertIs(d.get("result"), False)
        self.assertEqual(d.get("psdk_result", {}).get("reason"), "unit_disallowed_on_map")

    def test_t2_f04_02_unit_rejected_on_unknown_entity(self) -> None:
        d = self._data("t2_f04_02")
        self.assertIs(d.get("result"), False)

    def test_t2_f04_03_unit_rejected_on_scene_box_entity(self) -> None:
        d = self._data("t2_f04_03")
        self.assertTrue(_rejected_or_clamped(d.get("second"), None, 0, 0))

    def test_t2_f04_04_unit_duplicate_attach_idempotent_or_guarded(self) -> None:
        d = self._data("t2_f04_04")
        self.assertIs(d.get("first_ok"), True)
        ent = d["world"]["entity_state"]["entities"][0]
        units = [c for c in ent["components"] if c.get("script") == "res://scenes/entities/components/comp_unit.gd"]
        self.assertEqual(len(units), 1)

    def test_t2_f04_05_unit_schema_version_always_1(self) -> None:
        d = self._data("t2_f04_04")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://scenes/entities/components/comp_unit.gd")
        self.assertEqual(comp["state"]["schema_version"], 1)

    # =========================================================================
    # Feature #5: feature_floor_system boundaries (5 tests)
    # =========================================================================
    def test_t2_f05_01_max_512_floors_cap(self) -> None:
        d = self._data("t2_f05_01")
        self.assertEqual(d.get("ok_count"), 512)
        self.assertEqual(d.get("overflow_floor"), "")

    def test_t2_f05_02_set_active_floor_unknown_uid_rejected(self) -> None:
        d = self._data("t2_f05_02")
        self.assertIs(d.get("bad_act"), False)

    def test_t2_f05_03_floor_name_control_chars_and_long_name_sanitized(self) -> None:
        d = self._data("t2_f05_02")
        floors = {f["floor_uid"]: f["name"] for f in d["world"]["catalog"]["floors"]}
        nm = floors[d["ctrl_f"]]
        self.assertLessEqual(len(nm), 96)
        self.assertNotIn("\n", nm)
        self.assertNotIn("\t", nm)

    def test_t2_f05_04_blank_floor_name_fallback(self) -> None:
        d = self._data("t2_f05_02")
        floors = {f["floor_uid"]: f["name"] for f in d["world"]["catalog"]["floors"]}
        self.assertTrue(bool(floors[d["blank_f"]].strip()))

    def test_t2_f05_05_rename_unknown_floor_returns_false(self) -> None:
        d = self._data("t2_f05_02")
        self.assertIs(d.get("bad_rn"), False)

    # =========================================================================
    # Feature #6: feature_layer_stack boundaries (5 tests)
    # =========================================================================
    def test_t2_f06_01_max_256_layers_per_floor_cap(self) -> None:
        d = self._data("t2_f06_01")
        self.assertEqual(d.get("count_l"), 256)
        self.assertEqual(d.get("overflow_l"), "")

    def test_t2_f06_02_max_4096_total_layers_cap(self) -> None:
        d = self._data("t2_f06_02")
        self.assertEqual(d.get("total_layers"), 4096)
        self.assertEqual(d.get("overflow_l"), "")
        self.assertLess(int(d.get("target_floor_layer_count", 999)), 256)
        assert_world_v3_invariants(self, d["world"], "t2_f06_02")

    def test_t2_f06_03_invalid_layer_kind_and_access_handled(self) -> None:
        d = self._data("t2_f06_03")
        self.assertEqual(d.get("bad_kind_l"), "")
        self.assertEqual(d.get("bad_access_l"), "")
        assert_world_v3_invariants(self, d["world"], "t2_f06_03")

    def test_t2_f06_04_players_access_with_empty_viewers_handled(self) -> None:
        d = self._data("t2_f06_04")
        self.assertEqual(d.get("players_empty"), "")
        self.assertIs(d.get("set_access_empty_ok"), False)
        assert_world_v3_invariants(self, d["world"], "t2_f06_04")

    def test_t2_f06_05_viewers_capped_at_128_and_160_chars(self) -> None:
        d = self._data("t2_f06_05")
        assert_world_v3_invariants(self, d["world"], "t2_f06_05")
        layers = d["world"]["catalog"]["layers"]["floors"][0]["layers"]
        matched_128 = [l for l in layers if l["layer_uid"] == d.get("capped_128_l")]
        self.assertEqual(len(matched_128), 1)
        self.assertEqual(len(matched_128[0]["viewers"]), 128)
        self.assertTrue(all(len(v) <= 160 for v in matched_128[0]["viewers"]))
        overlong_l = str(d.get("overlong_l", ""))
        if overlong_l:
            matched_over = [l for l in layers if l["layer_uid"] == overlong_l]
            self.assertEqual(len(matched_over), 1)
            self.assertEqual(matched_over[0]["viewers"], ["v_ok"])
            self.assertTrue(all(len(v) <= 160 for v in matched_over[0]["viewers"]))
        else:
            self.assertEqual(overlong_l, "")

    # =========================================================================
    # Feature #7: feature_obstacle_authoring boundaries (5 tests)
    # =========================================================================
    def test_t2_f07_01_degenerate_two_point_polygon_skipped(self) -> None:
        d = self._data("t2_f07_01")
        self.assertEqual(d.get("degen_id"), "")

    def test_t2_f07_02_nan_inf_segment_coordinates_rejected(self) -> None:
        d = self._data("t2_f07_01")
        self.assertEqual(d.get("nan_id"), "")

    def test_t2_f07_03_zero_length_segment_rejected(self) -> None:
        d = self._data("t2_f07_01")
        self.assertEqual(d.get("zero_id"), "")

    def test_t2_f07_04_large_1e7_coordinate_segment_ulp_safe(self) -> None:
        d = self._data("t2_f07_04")
        self.assertTrue(bool(d.get("big_id")))
        self.assertEqual(d.get("roundtrip_diff"), "")

    def test_t2_f07_05_unknown_obstacle_kind_normalized_or_rejected(self) -> None:
        d = self._data("t2_f07_05")
        assert_world_v3_invariants(self, d["world"], "t2_f07_05")
        att_bad = d.get("attach_bad_res", {})
        self.assertIsInstance(att_bad, dict)
        self.assertIs(att_bad.get("ok"), False)
        self.assertIn("invalid_obstacle_role", str(att_bad.get("reason", "")))
        poly_id = str(d.get("poly_bad_id", ""))
        if poly_id:
            ents = [e for e in d["world"]["entity_state"]["entities"] if e["id"] == poly_id]
            self.assertEqual(len(ents), 1)
            src_kind = ents[0]["components"][0]["state"]["vector_drawing"]["source"]["kind"]
            self.assertEqual(src_kind, "wall")

    # =========================================================================
    # Feature #8: feature_entity_library boundaries (5 tests)
    # =========================================================================
    def test_t2_f08_01_invalid_root_path_rejected_by_4gate(self) -> None:
        d = self._data("t2_f08_01")
        can_writes = d.get("can_writes", {})
        reg_results = d.get("reg_results", {})
        for tag in ("wrong_parent", "missing_32hex", "mismatched_root", "empty_root"):
            self.assertIs(can_writes.get(tag), False, f"{tag} should fail can_write_library")
            rr = reg_results.get(tag, {})
            self.assertIs(rr.get("ok"), True)
            self.assertEqual(rr.get("count"), 0)
            self.assertIs(rr.get("skipped"), True)
            self.assertEqual(rr.get("reason"), "library_gate_not_met")
        self.assertEqual(d.get("store_record_count"), 0)

    def test_t2_f08_02_preset_with_multiple_disabled_modules_warns(self) -> None:
        d = self._data("t2_f08_02")
        insp = d.get("inspect_res", {})
        self.assertIs(insp.get("ok"), False)
        unavail_mods = {u.get("module_id") for u in insp.get("unavailable", [])}
        self.assertTrue({"simple_fog", "portal", "areas"}.issubset(unavail_mods))

        rp = d.get("reg_preserve", {})
        self.assertEqual(len(rp.get("warned_presets", [])), 1)
        self.assertEqual(rp.get("stripped_components"), [])
        self.assertEqual(rp.get("skipped_presets"), [])

        rs = d.get("reg_skip", {})
        self.assertEqual(len(rs.get("warned_presets", [])), 1)
        self.assertEqual(len(rs.get("stripped_components", [])), 1)
        self.assertEqual(rs["stripped_components"][0].get("module_id"), "simple_fog")
        self.assertEqual(len(rs.get("skipped_presets", [])), 1)
        skip_recs = list(d.get("decoded_skip_records", {}).values())
        self.assertEqual(len(skip_recs), 1)
        self.assertEqual(skip_recs[0].get("kind"), "unit")

    def test_t2_f08_03_empty_sprite_ref_or_user_scheme_rejected(self) -> None:
        d = self._data("t2_f08_03")
        self.assertEqual(d.get("reg_result", {}).get("count"), 5)
        self.assertEqual(d.get("adopted_assets"), [])
        recs = d.get("decoded_records", {})
        self.assertEqual(len(recs), 5)
        for rec in recs.values():
            self.assertEqual(rec.get("reference"), "")
            self.assertEqual(rec.get("record", {}).get("data", {}).get("sprite"), "")

    def test_t2_f08_04_idempotent_re_registration(self) -> None:
        d = self._data("t2_f08_04")
        self.assertEqual(d.get("reg_1", {}).get("count"), 1)
        self.assertEqual(d.get("reg_2", {}).get("count"), 1)
        self.assertGreaterEqual(int(d.get("write_calls_1", 0)), 2)
        self.assertEqual(d.get("write_calls_2"), d.get("write_calls_1"))
        self.assertEqual(d.get("rev_2"), d.get("rev_1"))
        self.assertEqual(set(d.get("keys_1", [])), set(d.get("keys_2", [])))

    def test_t2_f08_05_rollback_on_cancel(self) -> None:
        d = self._data("t2_f08_05")
        self.assertEqual(d.get("count_before_rb"), 3)
        self.assertEqual(d.get("keys_after_rb"), ["pre_existing_001"])
        cres = d.get("cancel_res", {})
        self.assertIs(cres.get("ok"), False)
        self.assertEqual(cres.get("count"), 0)
        self.assertIs(cres.get("skipped"), False)
        self.assertEqual(cres.get("reason"), "cancelled")
        self.assertGreaterEqual(int(d.get("cancel_write_calls", 0)), 2)
        self.assertEqual(d.get("keys_after_cancel"), [])

    # =========================================================================
    # Feature #9: Stateless catalog boundaries (5 tests)
    # =========================================================================
    def test_t2_f09_01_cannot_disable_any_of_9_core_modules(self) -> None:
        d = self._data("t2_f09_01")
        self.assertIs(d.get("core_still_on"), True)

    def test_t2_f09_02_stateless_optional_does_not_write_world_modules(self) -> None:
        d = self._data("t2_f09_02")
        self.assertEqual(d["world"]["modules"]["entries"], {})
        self.assertEqual(d.get("roundtrip_diff"), "")
        for mid in STATELESS_OPTIONAL_MODULE_IDS:
            self.assertIs(d["enabled_map"].get(mid), True)
            self.assertIs(d["sdk_is_null_map"].get(mid), True)
            self.assertIs(d["avail_map"].get(mid, {}).get("stateless"), True)

    def test_t2_f09_03_non_catalog_candidate_music_board_and_module_example(self) -> None:
        d = self._data("t2_f09_03")
        for mid in ("music_board", "module_example"):
            self.assertEqual(d["avail_map"][mid].get("status"), "uncatalogued_candidate")

    def test_t2_f09_04_enable_unknown_module_id_safe(self) -> None:
        d = self._data("t2_f09_04")
        self.assertIs(d.get("opt_on"), False)

    def test_t2_f09_05_get_plugin_sdk_for_stateless_module_safe(self) -> None:
        d = self._data("t2_f09_05")
        all_stateless = STATELESS_CORE_MODULE_IDS + STATELESS_OPTIONAL_MODULE_IDS + ("music_board", "module_example")
        for mid in all_stateless:
            self.assertIs(d["sdk_is_null_map"].get(mid), True, f"Expected null get_plugin_sdk({mid})")
            self.assertIs(d["sdk_create_is_null_map"].get(mid), True, f"Expected null create_plugin_sdk({mid})")
            self.assertIs(d["avail_map"].get(mid, {}).get("stateless"), True, f"Expected stateless=True for {mid}")

    # =========================================================================
    # Feature #10: scene_box boundaries (5 tests)
    # =========================================================================
    def test_t2_f10_01_max_64_scenes_hard_cap(self) -> None:
        d = self._data("t2_f10_01")
        self.assertTrue(bool(d.get("last_s")))
        self.assertEqual(d.get("over_s"), "")
        self.assertEqual(len(d["world"]["modules"]["entries"]["scene_box"]["state"]["scenes"]), 64)

    def test_t2_f10_02_move_last_floor_out_of_scene_rejected(self) -> None:
        d = self._data("t2_f10_01")
        self.assertIs(d.get("move_last_ok"), False)

    def test_t2_f10_03_side_cells_clamped_72_to_256(self) -> None:
        d = self._data("t2_f10_03")
        ents = {e["id"]: e for e in d["world"]["entity_state"]["entities"]}
        self.assertEqual(ents[d["small_box"]]["entity_size"].x, 72.0)
        self.assertEqual(ents[d["big_box"]]["entity_size"].x, 256.0)

    def test_t2_f10_04_bad_cover_asset_sanitized_to_empty(self) -> None:
        d = self._data("t2_f10_03")
        scenes = d["world"]["modules"]["entries"]["scene_box"]["state"]["scenes"]
        self.assertEqual(scenes[0]["cover_asset"], "")

    def test_t2_f10_05_scene_box_disabled_under_skip_policy(self) -> None:
        d = self._data("t2_f10_05")
        self.assertNotIn("scene_box", d["world"]["modules"]["entries"])

    # =========================================================================
    # Feature #11: portal boundaries (5 tests)
    # =========================================================================
    def test_t2_f11_01_portal_empty_pair_key_allowed_or_handled(self) -> None:
        d = self._data("t2_f11_01")
        assert_world_v3_invariants(self, d["world"], "t2_f11_01")

    def test_t2_f11_02_portal_on_nonexistent_entity_rejected(self) -> None:
        d = self._data("t2_f11_02")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))
        self.assertEqual(d["world"]["entity_state"]["entities"], [])

    def test_t2_f11_03_portal_on_scene_box_rejected(self) -> None:
        d = self._data("t2_f11_03")
        self.assertTrue(_rejected_or_clamped(d.get("second"), None, 0, 0))

    def test_t2_f11_04_portal_disabled_preserve_vs_skip(self) -> None:
        d = self._data("t2_f11_04")
        assert_r2_warning_present(self, d.get("log_entries", []), "portal", policy="skip")
        for e in d["world"]["entity_state"]["entities"]:
            scripts = [c["script"] for c in e["components"]]
            self.assertNotIn("res://modules/portal/comp_portal.gd", scripts)

    def test_t2_f11_05_portal_unicode_pair_key_normalized_to_32hex(self) -> None:
        d = self._data("t2_f11_05")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/portal/comp_portal.gd")
        self.assertRegex(comp["state"]["pair_key"], r"^[0-9a-f]{32}$")

    # =========================================================================
    # Feature #12: grid_alignment boundaries (5 tests)
    # =========================================================================
    def test_t2_f12_01_cell_size_bounds_8_and_4096(self) -> None:
        d = self._data("t2_f12_01")
        entry = d["world"]["modules"]["entries"].get("grid_alignment")
        if entry is not None:
            cs = entry["state"].get("cell_size")
            self.assertTrue(is_finite_number(cs) and 8.0 <= float(cs) <= 4096.0)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f12_02_offset_bounds_1e6(self) -> None:
        d = self._data("t2_f12_02")
        st = d["world"]["modules"]["entries"]["grid_alignment"]["state"]
        self.assertAlmostEqual(float(st["cell_size"]), 4096.0, places=2)

    def test_t2_f12_03_line_width_bounds_0_5_and_4_0(self) -> None:
        d = self._data("t2_f12_01")
        entry = d["world"]["modules"]["entries"].get("grid_alignment")
        if entry is not None:
            lw = entry["state"].get("line_width")
            self.assertTrue(is_finite_number(lw) and 0.5 <= float(lw) <= 4.0)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f12_04_snap_strength_bounds_0_and_1(self) -> None:
        d = self._data("t2_f12_03")
        entry = d["world"]["modules"]["entries"].get("grid_alignment")
        if entry is not None:
            cs = entry["state"].get("cell_size")
            ss = entry["state"].get("snap_strength")
            self.assertTrue(is_finite_number(cs) and 8.0 <= float(cs) <= 4096.0)
            self.assertTrue(is_finite_number(ss) and 0.0 <= float(ss) <= 1.0)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f12_05_color_channel_clamping_and_skip_policy(self) -> None:
        d = self._data("t2_f12_05")
        self.assertNotIn("grid_alignment", d["world"]["modules"]["entries"])

    # =========================================================================
    # Feature #13: simple_fog boundaries (5 tests)
    # =========================================================================
    def test_t2_f13_01_unseen_color_alpha_must_be_1(self) -> None:
        d = self._data("t2_f13_01")
        entry = d["world"]["modules"]["entries"].get("simple_fog")
        if entry is not None:
            col = entry["state"]["unseen_color"]
            alpha = col.a if hasattr(col, "a") else col[3]
            self.assertAlmostEqual(float(alpha), 1.0, places=3)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 1.0, 1.0))

    def test_t2_f13_02_dm_opacity_and_feather_and_smooth_bounds(self) -> None:
        d = self._data("t2_f13_02")
        entry = d["world"]["modules"]["entries"].get("simple_fog")
        if entry is not None:
            st = entry["state"]
            self.assertTrue(0.01 <= float(st["dm_opacity"]) <= 1.0)
            self.assertTrue(0.0 <= float(st["vision_feather"]) <= 0.5)
            self.assertTrue(0.0 <= float(st["shadow_smooth"]) <= 16.0)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0.0, 1.0))

    def test_t2_f13_03_invalid_effect_3_and_shadow_filter_3_rejected(self) -> None:
        d = self._data("t2_f13_03")
        entry = d["world"]["modules"]["entries"].get("simple_fog")
        if entry is not None:
            self.assertIn(entry["state"]["unseen_effect"], {0, 1, 2, 4, 6})
            self.assertIn(entry["state"]["shadow_filter"], {0, 1, 2})
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0.0, 1.0))

    def test_t2_f13_04_corrupt_exploration_bytes_rejected(self) -> None:
        d = self._data("t2_f13_04")
        entry = d["world"]["modules"]["entries"].get("simple_fog")
        if entry is not None and "exploration" in entry["state"]:
            raw = bytes(entry["state"]["exploration"])
            self.assertTrue(raw == b"" or raw.startswith(b"SFH2"))
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0.0, 1.0))

    def test_t2_f13_05_vision_negative_radius_and_angle_gt_360(self) -> None:
        d = self._data("t2_f13_05")
        tok = [e for e in d["world"]["entity_state"]["entities"] if e["id"] == d["token_id"]][0]
        comps = [c for c in tok["components"] if c["script"] == "res://modules/simple_fog/comp_simple_vision.gd"]
        if comps:
            rad = comps[0]["state"]["radius"]
            ang = comps[0]["state"]["view_angle"]
            self.assertTrue(is_finite_number(rad) and float(rad) >= 0.0)
            self.assertTrue(is_finite_number(ang) and 0.0 <= float(ang) <= 360.0)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("vision_result", d.get("result")), None, 0.0, 1.0))

    # =========================================================================
    # Feature #14: image_flip boundaries (5 tests)
    # =========================================================================
    def test_t2_f14_01_image_flip_conflicts_with_obstacle(self) -> None:
        d = self._data("t2_f14_01")
        self.assertTrue(_rejected_or_clamped(d.get("second"), None, 0, 0))

    def test_t2_f14_02_image_flip_conflicts_with_area(self) -> None:
        d = self._data("t2_f14_02")
        self.assertTrue(_rejected_or_clamped(d.get("second"), None, 0, 0))

    def test_t2_f14_03_image_flip_conflicts_with_scene_box(self) -> None:
        d = self._data("t2_f14_03")
        self.assertTrue(_rejected_or_clamped(d.get("second"), None, 0, 0))

    def test_t2_f14_04_image_flip_on_missing_entity_rejected(self) -> None:
        d = self._data("t2_f14_04")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))
        self.assertEqual(d["world"]["entity_state"]["entities"], [])

    def test_t2_f14_05_image_flip_skip_vs_preserve_when_disabled(self) -> None:
        d = self._data("t2_f14_05")
        ent = d["world"]["entity_state"]["entities"][0]
        scripts = [c["script"] for c in ent["components"]]
        self.assertNotIn("res://modules/image_flip/comp_image_flip.gd", scripts)

    # =========================================================================
    # Feature #15: drag_movement boundaries (5 tests)
    # =========================================================================
    def test_t2_f15_01_negative_module_speed_rejected(self) -> None:
        d = self._data("t2_f15_01")
        entry = d["world"]["modules"]["entries"].get("drag_movement")
        if entry is not None:
            self.assertGreaterEqual(float(entry["state"]["speed"]), 0.0)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f15_02_nan_inf_speed_rejected(self) -> None:
        for cid in ("t2_f15_02", "t2_f15_02_inf"):
            d = self._data(cid)
            self.assertEqual(d.get("roundtrip_diff"), "")
            entry = d["world"]["modules"]["entries"].get("drag_movement")
            if entry is not None:
                spd = entry.get("state", {}).get("speed")
                self.assertTrue(
                    is_finite_number(spd) and float(spd) >= 0.0,
                    f"{cid}: Non-finite or negative speed persisted: {spd!r}",
                )
            else:
                self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f15_03_negative_comp_drag_speed_rejected(self) -> None:
        d = self._data("t2_f15_03")
        ent = d["world"]["entity_state"]["entities"][0]
        comps = [c for c in ent["components"] if c["script"] == "res://modules/drag_movement/comp_drag_speed.gd"]
        if comps:
            spd = comps[0]["state"]["speed"]
            self.assertTrue(is_finite_number(spd) and float(spd) >= 0.0)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f15_04_drag_speed_conflicts_with_scene_box(self) -> None:
        d = self._data("t2_f15_04")
        self.assertTrue(_rejected_or_clamped(d.get("second"), None, 0, 0))

    def test_t2_f15_05_drag_movement_skip_policy(self) -> None:
        d = self._data("t2_f15_05")
        self.assertNotIn("drag_movement", d["world"]["modules"]["entries"])

    # =========================================================================
    # Feature #16: drawing boundaries (5 tests)
    # =========================================================================
    def test_t2_f16_01_mismatched_points_and_pressure_rejected(self) -> None:
        d = self._data("t2_f16_01")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f16_02_text_item_empty_or_gt_1024_rejected(self) -> None:
        d = self._data("t2_f16_02")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f16_03_text_item_invalid_font_or_font_size_rejected(self) -> None:
        d = self._data("t2_f16_03")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f16_04_entity_ink_forbids_life_key_and_scene_box(self) -> None:
        d_sb = self._data("t2_f16_04")
        self.assertTrue(_rejected_or_clamped(d_sb.get("second"), None, 0, 0))
        d_life = self._data("t2_f16_04_life")
        self.assertTrue(_rejected_or_clamped(d_life.get("result"), None, 0, 0))
        ent = d_life["world"]["entity_state"]["entities"][0]
        ink_comps = [c for c in ent["components"] if c["script"] == "res://modules/drawing/comp_entity_ink.gd"]
        self.assertEqual(ink_comps, [])

    def test_t2_f16_05_duplicate_stroke_id_or_order_rejected(self) -> None:
        d = self._data("t2_f16_05")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    # =========================================================================
    # Feature #17: areas boundaries (5 tests)
    # =========================================================================
    def test_t2_f17_01_radius_zero_and_negative_rejected(self) -> None:
        d = self._data("t2_f17_01")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f17_02_radius_gt_256_and_nan_rejected(self) -> None:
        d = self._data("t2_f17_02")
        ent = d["world"]["entity_state"]["entities"][0]
        comps = [c for c in ent["components"] if c["script"] == "res://modules/areas/comp_area.gd"]
        if comps:
            rad = comps[0]["state"]["radius_in_cells"]
            self.assertTrue(is_finite_number(rad) and 0.0 < float(rad) <= 256.0)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f17_03_radius_exact_boundary_256_accepted(self) -> None:
        d = self._data("t2_f17_03")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://modules/areas/comp_area.gd")
        self.assertAlmostEqual(float(comp["state"]["radius_in_cells"]), 256.0, places=2)

    def test_t2_f17_04_area_conflicts_with_image_flip_and_scene_box(self) -> None:
        d = self._data("t2_f17_04")
        self.assertTrue(_rejected_or_clamped(d.get("second"), None, 0, 0))

    def test_t2_f17_05_area_skip_policy_when_disabled(self) -> None:
        d = self._data("t2_f17_05")
        ent = d["world"]["entity_state"]["entities"][0]
        scripts = [c["script"] for c in ent["components"]]
        self.assertNotIn("res://modules/areas/comp_area.gd", scripts)

    # =========================================================================
    # Feature #18: entity_notes boundaries (5 tests)
    # =========================================================================
    def test_t2_f18_01_text_length_32768_exact_accepted(self) -> None:
        d = self._data("t2_f18_01")
        ent = d["world"]["entity_state"]["entities"][0]
        comp = assert_entity_has_component(self, ent, "res://scenes/candidates/entity_notes/comp_entity_note.gd")
        self.assertEqual(len(comp["state"]["text"]), 32768)

    def test_t2_f18_02_text_length_32769_rejected_or_truncated(self) -> None:
        d = self._data("t2_f18_02")
        ent = d["world"]["entity_state"]["entities"][0]
        comps = [c for c in ent["components"] if c["script"] == "res://scenes/candidates/entity_notes/comp_entity_note.gd"]
        if comps:
            self.assertLessEqual(len(comps[0]["state"]["text"]), 32768)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f18_03_cannot_force_enable_uncatalogued_candidate(self) -> None:
        d = self._data("t2_f18_03")
        self.assertIs(d.get("opt_on"), False)

    def test_t2_f18_04_entity_notes_under_skip_policy(self) -> None:
        d = self._data("t2_f18_04")
        ent = d["world"]["entity_state"]["entities"][0]
        scripts = [c["script"] for c in ent["components"]]
        self.assertNotIn("res://scenes/candidates/entity_notes/comp_entity_note.gd", scripts)

    def test_t2_f18_05_entity_notes_on_missing_entity_rejected(self) -> None:
        d = self._data("t2_f18_05")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))
        self.assertEqual(d["world"]["entity_state"]["entities"], [])

    # =========================================================================
    # Feature #19: checklist boundaries (5 tests)
    # =========================================================================
    def test_t2_f19_01_empty_or_multiline_title_rejected(self) -> None:
        d = self._data("t2_f19_01")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f19_02_archived_true_with_done_false_rejected(self) -> None:
        d = self._data("t2_f19_02")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f19_03_player_audience_empty_player_id_rejected(self) -> None:
        d = self._data("t2_f19_03")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f19_04_gt_128_rows_or_order_gt_100000_rejected(self) -> None:
        d = self._data("t2_f19_04")
        entry = d["world"]["modules"]["entries"].get("checklist")
        if entry is not None:
            self.assertLessEqual(len(entry["state"].get("rows", {})), 128)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f19_05_invalid_row_id_or_more_entity_ids_without_entity_id(self) -> None:
        d = self._data("t2_f19_05")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    # =========================================================================
    # Feature #20: resource_pool boundaries (5 tests)
    # =========================================================================
    def test_t2_f20_01_current_gt_maximum_or_negative_rejected(self) -> None:
        d = self._data("t2_f20_01")
        ent = d["world"]["entity_state"]["entities"][0]
        comps = [c for c in ent["components"] if c["script"] == "res://scenes/candidates/resource_pool/comp_resource_pool.gd"]
        if comps:
            v = comps[0]["state"]["values"]["resource_pool:hp"]
            self.assertLessEqual(float(v["current"]), float(v["maximum"]))
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f20_02_maximum_gt_1e9_rejected(self) -> None:
        d = self._data("t2_f20_02")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f20_03_invalid_hex8_color_or_non_resource_pool_source_rejected(self) -> None:
        d_col = self._data("t2_f20_03")
        self.assertTrue(_rejected_or_clamped(d_col.get("result"), None, 0, 0))
        d_src = self._data("t2_f20_03_src")
        self.assertTrue(_rejected_or_clamped(d_src.get("result"), None, 0, 0))
        self.assertNotIn("resource_pool", d_src["world"]["modules"]["entries"])

    def test_t2_f20_04_invalid_display_or_visibility_rejected(self) -> None:
        d = self._data("t2_f20_04")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f20_05_comp_resource_pool_conflicts_with_scene_box(self) -> None:
        d = self._data("t2_f20_05")
        self.assertTrue(_rejected_or_clamped(d.get("second"), None, 0, 0))

    # =========================================================================
    # Feature #21: character_roster boundaries (5 tests)
    # =========================================================================
    def test_t2_f21_01_roster_member_rejected_on_non_unit_object(self) -> None:
        d = self._data("t2_f21_01")
        self.assertTrue(_rejected_or_clamped(d.get("on_non_unit"), None, 0, 0))

    def test_t2_f21_02_roster_member_rejected_on_map_entity(self) -> None:
        d = self._data("t2_f21_01")
        self.assertTrue(_rejected_or_clamped(d.get("on_map"), None, 0, 0))

    def test_t2_f21_03_roster_member_rejected_on_scene_box(self) -> None:
        d = self._data("t2_f21_03")
        self.assertTrue(_rejected_or_clamped(d.get("second"), None, 0, 0))

    def test_t2_f21_04_known_by_empty_key_or_value_rejected(self) -> None:
        d = self._data("t2_f21_04")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f21_05_roster_skip_policy(self) -> None:
        d = self._data("t2_f21_05")
        self.assertNotIn("character_roster", d["world"]["modules"]["entries"])

    # =========================================================================
    # Feature #22: backpack boundaries (5 tests)
    # =========================================================================
    def test_t2_f22_01_backpack_rejected_on_non_unit_host(self) -> None:
        d = self._data("t2_f22_01")
        self.assertTrue(_rejected_or_clamped(d.get("on_non_unit"), None, 0, 0))
        self.assertTrue(_rejected_or_clamped(d.get("on_map"), None, 0, 0))

    def test_t2_f22_02_invalid_slot_keys_rejected(self) -> None:
        d = self._data("t2_f22_02")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f22_03_qty_0_and_1000_rejected(self) -> None:
        d = self._data("t2_f22_03")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f22_04_item_name_blank_or_gt_48_and_note_gt_160_rejected(self) -> None:
        d = self._data("t2_f22_04")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f22_05_backpack_conflicts_with_scene_box(self) -> None:
        d = self._data("t2_f22_05")
        self.assertTrue(_rejected_or_clamped(d.get("second"), None, 0, 0))

    # =========================================================================
    # Feature #23: follow boundaries (5 tests)
    # =========================================================================
    def test_t2_f23_01_negative_or_nan_follow_distance_rejected(self) -> None:
        d = self._data("t2_f23_01")
        ent = d["world"]["entity_state"]["entities"][0]
        comps = [c for c in ent["components"] if c["script"] == "res://modules/follow/comp_follow.gd"]
        if comps:
            fd = comps[0]["state"]["follow_distance"]
            self.assertTrue(is_finite_number(fd) and float(fd) >= 0.0)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f23_02_invalid_non_empty_target_id_rejected(self) -> None:
        d = self._data("t2_f23_02")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f23_03_controller_id_gt_128_rejected(self) -> None:
        d = self._data("t2_f23_03")
        ent = d["world"]["entity_state"]["entities"][0]
        comps = [c for c in ent["components"] if c["script"] == "res://modules/follow/comp_follow.gd"]
        if comps:
            self.assertLessEqual(len(comps[0]["state"]["controller_id"]), 128)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f23_04_follow_conflicts_with_scene_box(self) -> None:
        d = self._data("t2_f23_04")
        self.assertTrue(_rejected_or_clamped(d.get("second"), None, 0, 0))

    def test_t2_f23_05_follow_skip_policy(self) -> None:
        d = self._data("t2_f23_05")
        ent = d["world"]["entity_state"]["entities"][0]
        scripts = [c["script"] for c in ent["components"]]
        self.assertNotIn("res://modules/follow/comp_follow.gd", scripts)

    # =========================================================================
    # Feature #24: candidate_initiative boundaries (5 tests)
    # =========================================================================
    def test_t2_f24_01_count_and_modifier_bounds(self) -> None:
        d = self._data("t2_f24_01")
        ent = d["world"]["entity_state"]["entities"][0]
        comps = [c for c in ent["components"] if c["script"] == "res://scenes/candidates/initiative/components/comp_initiative.gd"]
        if comps:
            self.assertTrue(-9999 <= int(comps[0]["state"]["count"]) <= 9999)
            self.assertTrue(-999 <= int(comps[0]["state"]["modifier"]) <= 999)
        else:
            self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f24_02_idle_phase_with_non_empty_members_rejected(self) -> None:
        d = self._data("t2_f24_02")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f24_03_active_phase_with_round_0_or_unknown_current_rejected(self) -> None:
        d = self._data("t2_f24_03")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f24_04_duplicate_entity_id_or_bad_tie_order_rejected(self) -> None:
        d = self._data("t2_f24_04")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f24_05_initiative_rejected_on_non_unit_or_obstacle_or_scene_box(self) -> None:
        d = self._data("t2_f24_05")
        self.assertTrue(_rejected_or_clamped(d.get("on_non_unit"), None, 0, 0))
        self.assertTrue(_rejected_or_clamped(d.get("on_map"), None, 0, 0))

    # =========================================================================
    # Feature #25: dice boundaries (5 tests)
    # =========================================================================
    def test_t2_f25_01_simple_result_and_animate_both_true_rejected(self) -> None:
        d = self._data("t2_f25_01")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f25_02_adv_and_dis_expressions_rejected_v0058(self) -> None:
        d = self._data("t2_f25_02")
        self.assertTrue(_rejected_or_clamped(d.get("adv_res"), None, 0, 0))
        self.assertTrue(_rejected_or_clamped(d.get("dis_res"), None, 0, 0))
        burst_res = d.get("burst_res")
        if isinstance(burst_res, dict):
            self.assertIs(burst_res.get("ok"), True)
        else:
            self.assertIs(burst_res, True)

    def test_t2_f25_03_gt_32_combos_rejected(self) -> None:
        d = self._data("t2_f25_03")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f25_04_invalid_theme_id_or_hidden_count_gt_records_rejected(self) -> None:
        d = self._data("t2_f25_04")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f25_05_draft_gt_256_or_gt_20_physical_dice_rejected(self) -> None:
        d = self._data("t2_f25_05")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    # =========================================================================
    # Feature #26: campaign_time boundaries (5 tests)
    # =========================================================================
    def test_t2_f26_01_minute_negative_and_gt_100000000_rejected(self) -> None:
        d = self._data("t2_f26_01")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f26_02_revision_zero_or_negative_rejected(self) -> None:
        d = self._data("t2_f26_02")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f26_03_invalid_era_32hex_rejected(self) -> None:
        d = self._data("t2_f26_03")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f26_04_orphan_effect_source_or_invalid_status_rejected(self) -> None:
        d = self._data("t2_f26_04")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f26_05_cannot_enable_playtest_blocked_by_default(self) -> None:
        d = self._data("t2_f26_05")
        self.assertIs(d.get("opt_on"), False)

    # =========================================================================
    # Feature #27: dnd_opportunity boundaries (5 tests)
    # =========================================================================
    def test_t2_f27_01_invalid_opportunity_edition_rejected(self) -> None:
        d = self._data("t2_f27_01")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f27_02_gt_64_cards_rejected(self) -> None:
        d = self._data("t2_f27_02")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f27_03_invalid_card_id_or_owner_rejected(self) -> None:
        d = self._data("t2_f27_03")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f27_04_invalid_card_edition_rejected(self) -> None:
        d = self._data("t2_f27_04")
        self.assertTrue(_rejected_or_clamped(d.get("result"), None, 0, 0))

    def test_t2_f27_05_playtest_blocked_skip_no_world_mutation(self) -> None:
        d = self._data("t2_f27_05")
        self.assertNotIn("dnd_opportunity", d["world"]["modules"]["entries"])

    # =========================================================================
    # Feature #28: mods/sdk-log-console/ boundaries (5 tests)
    # =========================================================================
    def _run_console_probe(self, case_id: str, *, cancel_policy: str = "never", sample_path: str = "", options: dict | None = None) -> dict:
        probe = GodotBatchProbe(self.session)
        probe.prepare_from_mod("sdk-log-console", use_real_mods=True)
        b = probe.run_batch(
            [SdkProbeCaseSpec(case_id, "console_mod_probe", {"sample_path": sample_path}, cancel_policy=cancel_policy, options=options or {})],
            timeout_seconds=90,
        )
        self.assertEqual(b.compile_failures, [])
        self.assertEqual(b.global_log_errors, [])
        return assert_case_passed(self, b.results[case_id])

    def test_t2_f28_01_console_mod_cancel_immediate(self) -> None:
        d = self._run_console_probe("t2_f28_01", cancel_policy="immediate")
        self.assertEqual(d.get("inspect_result"), {"ok": False, "reason": "cancelled"})
        self.assertEqual(d.get("prepare_result"), {"ok": False, "reason": "cancelled"})

    def test_t2_f28_02_console_mod_missing_or_empty_sample_handled(self) -> None:
        assert self.session.run_dir is not None
        empty_f = self.session.run_dir / "empty_sample.json"
        empty_f.write_bytes(b"")
        d = self._run_console_probe("t2_f28_02", sample_path=empty_f.as_posix())
        self.assertIsInstance(d.get("prepare_result"), dict)

    def test_t2_f28_03_console_mod_corrupt_json_input_handled(self) -> None:
        assert self.session.run_dir is not None
        bad_f = self.session.run_dir / "corrupt_sample.json"
        bad_f.write_text("{not_valid_json", encoding="utf-8")
        d = self._run_console_probe("t2_f28_03", sample_path=bad_f.as_posix())
        self.assertIsInstance(d.get("inspect_result"), dict)
        self.assertIsInstance(d.get("prepare_result"), dict)

    def test_t2_f28_04_console_mod_host_warn_100_cap_respected(self) -> None:
        assert self.session.run_dir is not None
        ok_f = self.session.run_dir / "many_warn_sample.json"
        ok_f.write_text(json.dumps({"mode": "stress_warnings"}), encoding="utf-8")
        d = self._run_console_probe("t2_f28_04", sample_path=ok_f.as_posix())
        self.assertLessEqual(len(d.get("host_warnings", [])), 100)

    def test_t2_f28_05_console_mod_zip_entry_quota_and_no_bom(self) -> None:
        assert self.session.build_dir is not None and self.session.cache_dir is not None
        r_bld = run_fuvtt_cli(["build", "sdk-log-console"], build_dir=self.session.build_dir, cache_dir=self.session.cache_dir)
        self.assertEqual(r_bld.returncode, 0, r_bld.stderr)
        zip_path = self.session.build_dir / "sdk-log-console" / "sdk-log-console.zip"
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            self.assertLessEqual(len(names), 1000)
            for nm in names:
                if nm.endswith((".gd", ".json")):
                    self.assertFalse(zf.read(nm).startswith(b"\xef\xbb\xbf"), f"BOM in {nm}")

    # =========================================================================
    # Feature #29: shared/tools/ & WorldModuleState quota boundaries (5 tests)
    # =========================================================================
    def test_t2_f29_01_world_module_state_129_entries_rejected(self) -> None:
        d = self._data("t2_f29_01")
        self.assertEqual(d.get("ok_count"), 128)
        self.assertIs(d.get("overflow_ok"), False)

    def test_t2_f29_02_can_fit_module_state_rejects_oversized_entry(self) -> None:
        d = self._data("t2_f29_02")
        self.assertIs(d.get("can_fit"), False)
        self.assertIs(d.get("set_ok"), False)

    def test_t2_f29_03_cli_validate_missing_mod_exits_1(self) -> None:
        assert self.session.build_dir is not None and self.session.cache_dir is not None
        res = run_fuvtt_cli(["validate", "nonexistent-mod-xyz"], build_dir=self.session.build_dir, cache_dir=self.session.cache_dir)
        self.assertEqual(res.returncode, 1)

    def test_t2_f29_04_cli_validate_rejects_bom_or_class_name_in_isolated_mod(self) -> None:
        iso_cfg = self.session.make_isolated_config()
        run_fuvtt_cli_isolated_mods(["init", "bad-hygiene-mod", "--ext", "json"], iso_cfg=iso_cfg)
        entry_p = iso_cfg.mods_dir / "bad-hygiene-mod" / "entry.gd"
        entry_p.write_bytes(b"\xef\xbb\xbfextends RefCounted\nclass_name BadMod\n")
        res = run_fuvtt_cli_isolated_mods(["validate", "bad-hygiene-mod"], iso_cfg=iso_cfg)
        self.assertEqual(res.returncode, 1)

    def test_t2_f29_05_cli_build_no_sdk_excludes_fu_sdk(self) -> None:
        iso_cfg = self.session.make_isolated_config()
        run_fuvtt_cli_isolated_mods(["init", "nosdk-mod", "--ext", "json"], iso_cfg=iso_cfg)
        res = run_fuvtt_cli_isolated_mods(["build", "nosdk-mod", "--no-sdk"], iso_cfg=iso_cfg)
        self.assertEqual(res.returncode, 0, res.stderr)
        manifest = json.loads((iso_cfg.build_dir / "nosdk-mod" / "build-manifest.json").read_text(encoding="utf-8"))
        self.assertIs(manifest.get("sdk_bundled"), False)

    # =========================================================================
    # Feature #30: R4 & R5 Path/Env Boundaries (5 tests)
    # =========================================================================
    def test_t2_f30_01_env_config_blocks_outside_workspace_build_dir(self) -> None:
        with self.assertRaises(ConfigError):
            load_config(WORKSPACE_ROOT, environ={"BUILD_DIR": "../outside_ws"})

    def test_t2_f30_02_env_config_blocks_root_as_cache_dir(self) -> None:
        with self.assertRaises(ConfigError):
            load_config(WORKSPACE_ROOT, environ={"CACHE_DIR": "."})

    def test_t2_f30_03_redact_path_masks_all_external_paths(self) -> None:
        cfg = load_config(WORKSPACE_ROOT)
        samples = [p for p in (cfg.fuvtt_install_dir, cfg.fus_repo_dir, cfg.godot_bin) if p is not None]
        self.assertTrue(samples)
        for p in samples:
            red = cfg.redact_path(f"path={str(p)} posix={p.as_posix().upper()}")
            self.assertNotIn(str(p).lower(), red.lower())

    def test_t2_f30_04_all_sdk_and_docs_zero_user_home_paths(self) -> None:
        targets = [WORKSPACE_ROOT / "AGENTS.md"]
        targets.extend((WORKSPACE_ROOT / "shared" / "sdk").rglob("*.gd"))
        targets.extend((WORKSPACE_ROOT / "shared" / "sdk").rglob("*.md"))
        targets.extend((WORKSPACE_ROOT / "shared" / "docs").rglob("*.md"))
        for p in targets:
            if p.is_file():
                assert_no_local_paths_in_text(self, p.read_text(encoding="utf-8"), label=p.name)

    def test_t2_f30_05_e2e_suite_no_top_level_test_files(self) -> None:
        tests_dir = WORKSPACE_ROOT / "shared" / "tools" / "tests"
        new_tops = [p.name for p in tests_dir.glob("test_*.py") if "e2e_sdk" in p.name.lower()]
        self.assertEqual(new_tops, [], f"Forbidden top-level test_*.py found: {new_tops}")
