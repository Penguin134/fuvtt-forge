"""Tests for M4 console-log-mod (`mods/sdk-log-console/`): packaging, Git tracking, and Godot headless probes."""

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
import zipfile

_TESTS_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _TESTS_DIR.parent
_WORKSPACE_ROOT = _TOOLS_DIR.parents[1]
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from fuvtt_devtools.env_config import load_config  # noqa: E402
from fuvtt_devtools.host_verifier import (  # noqa: E402
    PROBE_PROJECT_GODOT,
    _INWORLD_HOST_SHIMS,
    _render_global_script_class_cache,
    analyze_godot_logs,
    verify_mod_with_host,
)
from fuvtt_devtools.packager import build_mod  # noqa: E402
from fuvtt_devtools.validator import validate_mod_dir  # noqa: E402

MOD_NAME = "sdk-log-console"
MOD_DIR = _WORKSPACE_ROOT / "mods" / MOD_NAME
SDK_DIR = _WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk"
RUNTIME_SDK_DIR = _WORKSPACE_ROOT / "shared" / "sdk" / "fu_runtime"
TEST_TMP_ROOT = _WORKSPACE_ROOT / ".cache" / "test_tmp"

_FORBIDDEN_UI_PATTERNS = (
    re.compile(r"\b(?:Window|PopupPanel|Control)\.new\s*\("),
    re.compile(r"ui\.desktop_panels"),
)
_FORBIDDEN_NET_PATTERNS = (
    re.compile(r"network\.(?:actions|projections|presentations)"),
)

_EXPECTED_COUNT_KEYS = (
    "records",
    "images",
    "selected_images",
    "maps",
    "characters",
    "objects",
    "text",
    "drawings",
    "walls",
    "doors",
    "hidden",
    "unsupported",
)


def _make_isolated_config(tmp_root: Path):
    build_dir = tmp_root / "build"
    cache_dir = tmp_root / "cache"
    build_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return load_config(
        _WORKSPACE_ROOT,
        environ={
            "BUILD_DIR": str(build_dir.relative_to(_WORKSPACE_ROOT)),
            "CACHE_DIR": str(cache_dir.relative_to(_WORKSPACE_ROOT)),
        },
    )


class TestConsoleLogModPurePython(unittest.TestCase):
    """Pure-Python static contract, Git tracking, README proof, and ZIP packaging tests."""

    def test_validate_mod_dir_and_all_with_template(self) -> None:
        report = validate_mod_dir(
            MOD_DIR,
            mod_name=MOD_NAME,
            sdk_dir=SDK_DIR,
            runtime_sdk_dir=RUNTIME_SDK_DIR,
        )
        self.assertTrue(report.ok, f"validate_mod_dir failed: {report.errors}")
        self.assertIsNotNone(report.manifest)
        assert report.manifest is not None
        self.assertEqual(report.manifest.get("schema"), "fus.desktop-module.v1")
        self.assertEqual(report.manifest.get("host_api"), 2)
        self.assertEqual(report.manifest.get("scope"), "hybrid")
        self.assertNotIn("pack_file", report.manifest)
        self.assertNotIn("pck", report.manifest)
        self.assertEqual(report.manifest.get("id"), "sdk_log_console")
        self.assertEqual(report.manifest.get("entry"), "entry.gd")
        self.assertEqual(report.manifest.get("import_extensions"), ["json", "log"])
        for setting in report.manifest.get("settings", []):
            self.assertIn(setting.get("type"), ("bool", "string"))

        modules = report.manifest.get("modules", [])
        self.assertEqual(len(modules), 1)
        self.assertEqual(modules[0].get("id"), "mod.sdk_log_console")
        self.assertEqual(modules[0].get("entry_scene"), "res://mods/sdk_log_console/module.tscn")
        self.assertIs(modules[0].get("local_only"), True)
        self.assertEqual(modules[0].get("network_version"), 0)
        self.assertIs(modules[0].get("isolated_lifecycle"), True)

        proc = subprocess.run(
            [sys.executable, str(_TOOLS_DIR / "fuvtt_cli.py"), "validate", "--all", "--include-template"],
            cwd=str(_WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, f"validate --all failed:\n{proc.stdout}\n{proc.stderr}")

    def test_gdscript_hygiene_and_no_forbidden_ui_mounting(self) -> None:
        gd_files = sorted(MOD_DIR.rglob("*.gd"))
        expected_bases = {
            "entry.gd": ("extends RefCounted",),
            "module.gd": ("extends ExtensionBase",),
            "console_settings_page.gd": ("extends VBoxContainer", "extends Control"),
            "console_floating_window.gd": ("extends PanelContainer", "extends Control"),
        }
        found_names = {gd.name for gd in gd_files}
        self.assertTrue(set(expected_bases).issubset(found_names), f"Missing expected scripts: {set(expected_bases) - found_names}")

        for gd in gd_files:
            raw = gd.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"UTF-8 BOM in {gd}")
            self.assertNotIn(b"\r", raw, f"CR byte found in {gd}")
            text = raw.decode("utf-8")
            lines = [ln for ln in text.splitlines() if ln.strip()]
            self.assertGreater(len(lines), 0)
            allowed = expected_bases.get(gd.name, ("extends RefCounted", "extends ExtensionBase", "extends Control"))
            self.assertIn(lines[0].strip(), allowed, f"Unexpected base class {lines[0].strip()} in {gd}")
            self.assertNotRegex(text, re.compile(r"(?m)^\s*class_name\b"), f"class_name forbidden in {gd}")
            self.assertNotIn("preload(", text, f"preload() forbidden in {gd}")
            self.assertNotIn("build_world(", text, f"Non-existent build_world() found in {gd}")
            for pat in _FORBIDDEN_UI_PATTERNS:
                self.assertNotRegex(text, pat, f"Forbidden UI mounting pattern {pat.pattern} in {gd}")
            for pat in _FORBIDDEN_NET_PATTERNS:
                self.assertNotRegex(text, pat, f"Forbidden network registration {pat.pattern} in local-only {gd}")

        entry_text = (MOD_DIR / "entry.gd").read_text(encoding="utf-8")
        self.assertIn("lib/fu_sdk/v1.gd", entry_text)
        self.assertIn("../../shared/sdk/fu_sdk/v1.gd", entry_text)

        module_text = (MOD_DIR / "mods" / "sdk_log_console" / "module.gd").read_text(encoding="utf-8")
        self.assertIn("lib/fu_runtime/v2.gd", module_text)
        self.assertIn("../../../../shared/sdk/fu_runtime/v2.gd", module_text)

        tscn_files = sorted(MOD_DIR.rglob("*.tscn"))
        self.assertGreaterEqual(len(tscn_files), 3)
        for tscn in tscn_files:
            raw = tscn.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"UTF-8 BOM in {tscn}")
            self.assertNotIn(b"\r", raw, f"CR byte found in {tscn}")

    def test_gitignore_whitelist_and_git_tracking(self) -> None:
        gitignore_text = (_WORKSPACE_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!/mods/sdk-log-console/", gitignore_text)

        # Ensure no .log file exists inside mods/sdk-log-console/ (globally ignored by *.log)
        log_files = list(MOD_DIR.rglob("*.log"))
        self.assertEqual(log_files, [], f"Do not store .log files in {MOD_DIR}: {log_files}")

        for rel_target in (
            "mods/sdk-log-console/plugin.json",
            "mods/sdk-log-console/mods/sdk_log_console/module.gd",
        ):
            ci_proc = subprocess.run(
                ["git", "check-ignore", "-v", rel_target],
                cwd=str(_WORKSPACE_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            self.assertNotEqual(ci_proc.returncode, 0, f"{rel_target} is still git-ignored: {ci_proc.stdout}")

        ls_proc = subprocess.run(
            ["git", "ls-files", "--", "mods/sdk-log-console/"],
            cwd=str(_WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertEqual(ls_proc.returncode, 0, ls_proc.stderr)
        tracked = {ln.strip() for ln in ls_proc.stdout.splitlines() if ln.strip()}
        self.assertIn("mods/sdk-log-console/plugin.json", tracked)
        self.assertIn("mods/sdk-log-console/entry.gd", tracked)
        self.assertIn("mods/sdk-log-console/README.md", tracked)

    def test_readme_contains_source_level_proof_without_local_paths(self) -> None:
        readme_path = MOD_DIR / "README.md"
        self.assertTrue(readme_path.is_file())
        readme = readme_path.read_text(encoding="utf-8")
        cfg = load_config(_WORKSPACE_ROOT)
        for forbidden_path in (cfg.fus_repo_dir, cfg.fuvtt_install_dir, cfg.godot_bin):
            if forbidden_path is not None:
                self.assertNotIn(str(forbidden_path).lower(), readme.lower())
                self.assertNotIn(forbidden_path.as_posix().lower(), readme.lower())
        for marker in (
            "<FUS_REPO_DIR>",
            "PluginPackageJob.cs",
            "session_plugins.gd",
            "app.gd",
            "session_screen.gd",
            "plugin_import.gd",
            "session_plugin_actions.gd",
            "session_plugin_drop.gd",
            "desktop_screen.gd",
            "feature_manager.gd",
            "desktop_panel_host.gd",
            "debug_tools.gd",
            "diagnostic_logger.gd",
            "load_resource_pack",
            "ISteamUGC",
            "fus.desktop-module.v1",
            "hybrid",
            "local_only",
            "ui.module_settings",
            "fu_runtime",
            "verify-host",
        ):
            self.assertIn(marker, readme, f"Missing source-level proof citation {marker} in README.md")

    def test_build_bundles_all_modular_sdk_scripts_and_passes_zip_limits(self) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        run_dir = TEST_TMP_ROOT / f"console_build_{uuid.uuid4().hex[:10]}"
        try:
            iso_cfg = _make_isolated_config(run_dir)
            artifact = build_mod(MOD_NAME, config=iso_cfg)
            self.assertTrue(artifact.zip_path.is_file())
            self.assertTrue(artifact.sdk_bundled)
            self.assertEqual(artifact.schema, "fus.desktop-module.v1")
            self.assertEqual(artifact.zip_path.suffix, ".zip")

            expected_sdk = {
                f"lib/fu_sdk/{p.relative_to(SDK_DIR).as_posix()}"
                for p in SDK_DIR.rglob("*.gd")
                if not any(part.startswith(".") or part == "__pycache__" for part in p.relative_to(SDK_DIR).parts)
            }
            self.assertGreaterEqual(len(expected_sdk), 26)  # v1 + adapter + log_bus + registry + 23 plugins + modules

            runtime_manifest = json.loads((RUNTIME_SDK_DIR / "runtime_manifest.json").read_text(encoding="utf-8"))
            expected_inworld = {
                "mods/sdk_log_console/module.tscn",
                "mods/sdk_log_console/module.gd",
                "mods/sdk_log_console/console_settings_page.tscn",
                "mods/sdk_log_console/console_settings_page.gd",
                "mods/sdk_log_console/console_floating_window.tscn",
                "mods/sdk_log_console/console_floating_window.gd",
            }
            for rt_rel in runtime_manifest.get("runtime_scripts", []):
                expected_inworld.add(f"mods/sdk_log_console/lib/fu_runtime/{rt_rel}")
            for sdk_rel in runtime_manifest.get("shared_fu_sdk_scripts", []):
                expected_inworld.add(f"mods/sdk_log_console/lib/fu_sdk/{sdk_rel}")

            with zipfile.ZipFile(artifact.zip_path, "r") as zf:
                names = zf.namelist()
                self.assertLessEqual(len(names), 1000)
                self.assertGreaterEqual(len(names), 2)
                name_set = set(names)
                self.assertIn("plugin.json", name_set)
                self.assertIn("entry.gd", name_set)
                missing_sdk = sorted(expected_sdk - name_set)
                self.assertEqual(missing_sdk, [], f"Missing embedded SDK scripts: {missing_sdk}")
                missing_inworld = sorted(expected_inworld - name_set)
                self.assertEqual(missing_inworld, [], f"Missing in-world files: {missing_inworld}")
                for nm in names:
                    if nm.endswith((".gd", ".json", ".tscn")):
                        raw = zf.read(nm)
                        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"BOM in ZIP member {nm}")
                        if nm.endswith((".gd", ".tscn")):
                            self.assertNotIn(b"\r", raw, f"CR byte in ZIP member {nm}")
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)


_PROBE_GD = r'''extends SceneTree

var _out_path: String = ""
var _pkg_dir: String = ""


class MockHost:
	extends RefCounted

	var is_cancelled_flag: bool = false
	var progress_log: Array[String] = []
	var warnings: Array[String] = []
	var archived_urls: Array[String] = []

	func cancelled() -> bool:
		return is_cancelled_flag

	func report(text: String) -> void:
		progress_log.append(text)

	func warn(text: String) -> void:
		warnings.append(text)

	func empty_world() -> Dictionary:
		var floor_uid: String = "fus.floor.mock.1f".sha256_text().left(32)
		var entity_uid: String = ("fus.layer.default.v1:" + floor_uid).sha256_text().left(32)
		var map_uid: String = ("fus.layer.map:" + floor_uid).sha256_text().left(32)
		var obstacle_uid: String = ("fus.layer.obstacle:" + floor_uid).sha256_text().left(32)
		return {
			"ok": true,
			"data": {
				"format": "fus.practice.world",
				"version": 3,
				"catalog": {
					"floor_identity_version": 1,
					"floors": [
						{
							"id": 0,
							"floor_uid": floor_uid,
							"name": "1F",
							"color": Color(0.28, 0.65, 0.40),
						},
					],
					"layers": {
						"schema": "fus.floor_layers.v2",
						"floors": [
							{
								"floor_uid": floor_uid,
								"default_layer_uid": entity_uid,
								"layers": [
									{
										"layer_uid": map_uid,
										"name": "地图底图",
										"kind": "map",
										"visible": true,
										"locked": false,
										"persistent": true,
										"access": "all",
										"viewers": [],
									},
									{
										"layer_uid": entity_uid,
										"name": "实体",
										"kind": "entity",
										"visible": true,
										"locked": false,
										"persistent": true,
										"access": "all",
										"viewers": [],
									},
									{
										"layer_uid": obstacle_uid,
										"name": "障碍物",
										"kind": "obstacle",
										"visible": true,
										"locked": false,
										"persistent": true,
										"access": "host",
										"viewers": [],
									},
								],
							},
						],
					},
					"active_floor_uid": floor_uid,
				},
				"entity_state": {
					"version": 3,
					"entities": [],
				},
				"members": [],
				"modules": {
					"version": 2,
					"entries": {},
				},
			},
		}

	func archive_image(url: String, _proxy: String = "") -> Dictionary:
		archived_urls.append(url)
		return {"ok": false, "reason": "unsupported_in_test", "reference": ""}

	func begin_preview(_total: int, _bounds: Rect2) -> void:
		pass

	func preview_entity(_entity: Dictionary, _kind: String) -> void:
		pass

	func finish_geometry_preview() -> bool:
		return not is_cancelled_flag

	func inspect_source(_path: String) -> Dictionary:
		return {"ok": false, "reason": "not_fobr"}

	func decode_source(_path: String) -> Dictionary:
		return {"ok": false, "reason": "not_fobr"}


func _init() -> void:
	for raw_arg: String in OS.get_cmdline_user_args():
		if raw_arg.begins_with("--out="):
			_out_path = raw_arg.substr(6)
		elif raw_arg.begins_with("--pkg="):
			_pkg_dir = raw_arg.substr(6)
	call_deferred(&"_run")


func _write_json(data: Dictionary) -> void:
	var f: FileAccess = FileAccess.open(_out_path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(data, "\t"))
		f.close()


func _run_case(plugin: RefCounted, sample_path: String, options: Dictionary, cancel_flag: bool = false) -> Dictionary:
	var host := MockHost.new()
	host.is_cancelled_flag = cancel_flag
	var insp: Dictionary = plugin.inspect_import(sample_path, options.duplicate(true), host)
	var prep: Dictionary = plugin.prepare_import(sample_path, options.duplicate(true), host)
	var world_format: String = ""
	var world_version: int = -1
	var roundtrip_ok: bool = false
	var modules_entries: Dictionary = {}
	if bool(prep.get("ok", false)) and prep.get("world", null) is Dictionary:
		var w: Dictionary = prep["world"] as Dictionary
		world_format = str(w.get("format", ""))
		world_version = int(w.get("version", -1))
		var packed: PackedByteArray = var_to_bytes(w)
		var decoded: Variant = bytes_to_var(packed)
		roundtrip_ok = decoded is Dictionary and var_to_bytes(decoded) == packed
		var mods_v: Variant = w.get("modules", {})
		if mods_v is Dictionary:
			var ent_v: Variant = (mods_v as Dictionary).get("entries", {})
			if ent_v is Dictionary:
				modules_entries = ent_v as Dictionary
	var mod_state: Dictionary = {}
	if modules_entries.has("sdk_log_console") and modules_entries["sdk_log_console"] is Dictionary:
		mod_state = (modules_entries["sdk_log_console"] as Dictionary).get("state", {}) as Dictionary
	var warn_chars: int = 0
	for i: int in range(host.warnings.size()):
		if i > 0:
			warn_chars += 1
		warn_chars += host.warnings[i].length()
	var out: Dictionary = {
		"inspect": insp,
		"prepare_ok": bool(prep.get("ok", false)),
		"prepare_reason": str(prep.get("reason", "")),
		"world_format": world_format,
		"world_version": world_version,
		"roundtrip_ok": roundtrip_ok,
		"module_keys": modules_entries.keys(),
		"console_state": mod_state,
		"checklist_rows_count": ((modules_entries.get("checklist", {}).get("state", {}).get("rows", {})) as Dictionary).size() if modules_entries.has("checklist") else 0,
		"drawing_strokes_count": ((modules_entries.get("drawing", {}).get("state", {}).get("strokes", [])) as Array).size() if modules_entries.has("drawing") else 0,
		"host_progress_count": host.progress_log.size(),
		"host_warnings": host.warnings.duplicate(),
		"host_warnings_count": host.warnings.size(),
		"host_warnings_chars": warn_chars,
	}
	return out


func _run() -> void:
	var entry_scr: Script = load(_pkg_dir.path_join("entry.gd")) as Script
	if entry_scr == null:
		_write_json({"ok": false, "error": "failed_to_load_entry"})
		quit(1)
		return
	var plugin: RefCounted = entry_scr.new() as RefCounted
	if plugin == null:
		_write_json({"ok": false, "error": "failed_to_instantiate_entry"})
		quit(1)
		return

	var base_tmp: String = _out_path.get_base_dir()
	var valid_json_path: String = base_tmp.path_join("valid_diag.json")
	var log_path: String = base_tmp.path_join("sample_events.log")
	var empty_path: String = base_tmp.path_join("empty.json")
	var corrupt_path: String = base_tmp.path_join("corrupt.json")
	var stress_path: String = base_tmp.path_join("stress.json")
	var char_cap_path: String = base_tmp.path_join("char_cap.json")

	var f1: FileAccess = FileAccess.open(valid_json_path, FileAccess.WRITE)
	f1.store_string(JSON.stringify({
		"name": "Diag Probe",
		"audit_modules": ["simple_fog", "campaign_time", "checklist", "drawing"],
		"emit_debug": true,
		"emit_in_world": true,
		"entries": [
			{"level": "debug", "source": "probe", "message": "dbg line"},
			{"level": "info", "source": "probe", "message": "info line"},
			{"level": "warning", "source": "probe", "message": "warn line"},
			{"level": "error", "source": "probe", "message": "err line"},
		],
	}))
	f1.close()

	var f2: FileAccess = FileAccess.open(log_path, FileAccess.WRITE)
	f2.store_string("DEBUG init console\nINFO module check\nWARN disabled test\nERROR simulated error line\n")
	f2.close()

	var f3: FileAccess = FileAccess.open(empty_path, FileAccess.WRITE)
	f3.close()

	var f4: FileAccess = FileAccess.open(corrupt_path, FileAccess.WRITE)
	f4.store_string("{not_valid_json")
	f4.close()

	var f5: FileAccess = FileAccess.open(stress_path, FileAccess.WRITE)
	f5.store_string(JSON.stringify({"mode": "stress_warnings"}))
	f5.close()

	var long_entries: Array = []
	var pad: String = "x".repeat(320)
	for li: int in range(30):
		long_entries.append({"level": "warning", "source": "charcap", "message": "cap_%02d_%s" % [li, pad]})
	var f6: FileAccess = FileAccess.open(char_cap_path, FileAccess.WRITE)
	f6.store_string(JSON.stringify({"entries": long_entries}))
	f6.close()

	# Also test LogBus subscribe/get_entries/get_warnings/unsubscribe directly via packaged sdk
	var sdk_scr: Script = load(_pkg_dir.path_join("lib/fu_sdk/v1.gd")) as Script
	var sdk: RefCounted = sdk_scr.new() as RefCounted
	var host_bus := MockHost.new()
	var sess: RefCounted = sdk.create_session(host_bus, {})
	var bus: RefCounted = sess.get_logger()
	var sub_seen: Array[Dictionary] = []
	var tok: int = int(bus.subscribe(func(entry: Dictionary) -> void:
		sub_seen.append(entry)
	))
	bus.debug("direct", "d1")
	bus.info("direct", "i1")
	bus.warn("direct", "w1")
	var unsub_ok: bool = bool(bus.unsubscribe(tok))
	bus.info("direct", "after_unsub")
	var buf_entries: Array = bus.get_entries(0, 0, 0)
	var buf_warns: Array = bus.get_warnings(0)

	var results: Dictionary = {
		"cancel_immediate": _run_case(plugin, "", {}, true),
		"valid_json_preserve": _run_case(plugin, valid_json_path, {"disabled_policy": "preserve", "emit_in_world": true}),
		"valid_json_skip": _run_case(plugin, valid_json_path, {"disabled_policy": "skip", "emit_in_world": true, "enabled_modules": ""}),
		"plain_log": _run_case(plugin, log_path, {}),
		"empty_file": _run_case(plugin, empty_path, {}),
		"missing_path": _run_case(plugin, "", {}),
		"corrupt_json": _run_case(plugin, corrupt_path, {}),
		"empty_options": _run_case(plugin, valid_json_path, {}),
		"stress_warnings": _run_case(plugin, stress_path, {}),
		"stress_char_cap": _run_case(plugin, char_cap_path, {}),
		"nul_mid_log": _run_case(plugin, base_tmp.path_join("nul_mid.log"), {"audit_modules": "simple_fog"}),
		"bad_utf8_log": _run_case(plugin, base_tmp.path_join("bad_utf8.log"), {"audit_modules": "simple_fog"}),
		"json_nul_numeric": _run_case(plugin, base_tmp.path_join("json_nul_numeric.json"), {"audit_modules": "simple_fog"}),
		"array_module_options": _run_case(plugin, log_path, {"enabled_modules": ["simple_fog", "checklist"], "audit_modules": ["simple_fog", "checklist"]}),
		"min_level_error_preserves_r2": _run_case(plugin, log_path, {"min_level": "error", "stress_warnings": true, "audit_modules": "simple_fog", "disabled_policy": "preserve"}),
		"dir_and_scalar_json": _run_case(plugin, base_tmp, {"audit_modules": "simple_fog"}),
		"null_host_inspect": plugin.inspect_import(valid_json_path, {}, null),
		"null_host_prepare": plugin.prepare_import(valid_json_path, {}, null),
		"isolation_after_custom": _run_case(plugin, empty_path, {}),
		"logbus_parity": {
			"sub_seen_count": sub_seen.size(),
			"unsub_ok": unsub_ok,
			"buf_entries_count": buf_entries.size(),
			"buf_warns_count": buf_warns.size(),
			"sub_matches_first_3": sub_seen.size() == 3 and buf_entries.size() == 4 and buf_warns.size() == 1,
		},
	}

	_write_json({"ok": true, "results": results})
	quit(0)
'''


class TestConsoleLogModHeadlessGodot(unittest.TestCase):
    """Real headless Godot tests for verify-host and all console mod behaviors."""

    run_dir: Path | None = None
    results: dict = {}
    verify_host_result = None
    combined_godot_logs: str = ""

    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_WORKSPACE_ROOT)
        godot_bin = cfg.godot_bin
        if godot_bin is None or not godot_bin.is_file():
            raise unittest.SkipTest("GODOT_BIN not configured in .env.local; skipping headless Godot tests")

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.run_dir = TEST_TMP_ROOT / f"console_godot_{uuid.uuid4().hex[:10]}"
        iso_cfg = _make_isolated_config(cls.run_dir)

        cls.verify_host_result = verify_mod_with_host(MOD_NAME, config=iso_cfg)

        # Unpack built ZIP into isolated Godot probe project
        zip_path = iso_cfg.build_dir / MOD_NAME / f"{MOD_NAME}.zip"
        probe_dir = cls.run_dir / "probe_proj"
        pkg_dir = probe_dir / "pkg"
        pkg_dir.mkdir(parents=True, exist_ok=True)
        (probe_dir / "project.godot").write_bytes(
            b'config_version=5\n\n[application]\nconfig/name="console_mod_probe"\n'
        )
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(pkg_dir)

        (probe_dir / "probe.gd").write_bytes(_PROBE_GD.encode("utf-8"))

        (cls.run_dir / "nul_mid.log").write_bytes(
            b"INFO first\x00after_nul\r\nWARN second_line\r\nERROR third_line\r\n"
        )
        (cls.run_dir / "bad_utf8.log").write_bytes(
            b"INFO ok\r\nWARN \xff\xfe_bad\r\n"
        )
        (cls.run_dir / "json_nul_numeric.json").write_bytes(
            b'{"entries":[{"level":10,"source":"num_src","message":"dbg_10"},'
            b'{"level":20,"source":"num_src","message":"inf_20"},'
            b'{"level":30,"source":"num_src","message":"wrn_30"},'
            b'{"level":40,"source":"num_src","message":"A\\u0000B"},'
            b'{"level":40,"source":"esc_src","message":"X\\\\u0000Y"}]}'
        )

        out_path = cls.run_dir / "probe_out.json"
        isolated_env = cls.run_dir / "isolated_env"
        isolated_env.mkdir(parents=True, exist_ok=True)
        godot_log = cls.run_dir / "godot.log"
        env = dict(os.environ)
        env["APPDATA"] = str(isolated_env)
        env["LOCALAPPDATA"] = str(isolated_env)
        env["TEMP"] = str(isolated_env)
        env["TMP"] = str(isolated_env)
        env["GODOT_SILENCE_ROOT_WARNING"] = "1"

        proc = subprocess.run(
            [
                str(godot_bin),
                "--headless",
                "--quit",
                "--path",
                str(probe_dir),
                "--log-file",
                str(godot_log),
                "--script",
                "res://probe.gd",
                "--",
                f"--out={out_path}",
                "--pkg=res://pkg",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log_text = godot_log.read_text(encoding="utf-8", errors="replace") if godot_log.is_file() else ""
        cls.combined_godot_logs = "\n".join((log_text, proc.stdout, proc.stderr))
        log_errors = analyze_godot_logs(log_text, proc.stdout, proc.stderr)
        if proc.returncode != 0 or log_errors:
            redacted = cfg.redact_path(
                f"rc={proc.returncode} errors={log_errors}\n"
                f"stdout={proc.stdout[-1200:]}\nstderr={proc.stderr[-1200:]}"
            )
            raise AssertionError(f"Headless Godot console probe failed:\n{redacted}")

        parsed = json.loads(out_path.read_text(encoding="utf-8"))
        if not parsed.get("ok"):
            raise AssertionError(f"Console probe returned failure: {parsed}")
        cls.results = parsed["results"]

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.run_dir is not None and cls.run_dir.exists():
            shutil.rmtree(cls.run_dir, ignore_errors=True)
        if TEST_TMP_ROOT.exists():
            try:
                if not any(TEST_TMP_ROOT.iterdir()):
                    TEST_TMP_ROOT.rmdir()
            except OSError:
                pass

    def test_verify_host_passes_with_zero_errors(self) -> None:
        res = self.verify_host_result
        self.assertIsNotNone(res)
        assert res is not None
        self.assertTrue(res.ok, f"verify-host failed: failures={res.failures} log_errors={res.log_errors}")
        self.assertEqual(res.failures, [])
        self.assertEqual(res.log_errors, [])
        self.assertGreater(res.passed_checks, 0)

    def test_cancel_immediate_short_circuits_before_path_check(self) -> None:
        c = self.results["cancel_immediate"]
        self.assertEqual(c["inspect"], {"ok": False, "reason": "cancelled"})
        self.assertIs(c["prepare_ok"], False)
        self.assertEqual(c["prepare_reason"], "cancelled")

    def test_valid_json_preserve_emits_r2_warnings_and_in_world_board(self) -> None:
        r = self.results["valid_json_preserve"]
        insp = r["inspect"]
        self.assertIs(insp.get("ok"), True)
        self.assertEqual(len(str(insp.get("sha256", ""))), 64)
        self.assertGreater(insp.get("source_bytes", 0), 0)
        self.assertGreater(insp.get("decoded_bytes", 0), 0)
        for key in _EXPECTED_COUNT_KEYS:
            self.assertIn(key, insp.get("counts", {}))

        self.assertIs(r["prepare_ok"], True)
        self.assertEqual(r["world_format"], "fus.practice.world")
        self.assertEqual(r["world_version"], 3)
        self.assertIs(r["roundtrip_ok"], True)
        self.assertGreater(r["host_progress_count"], 0)
        self.assertIn("sdk_log_console", r["module_keys"])
        self.assertIn("checklist", r["module_keys"])
        self.assertIn("drawing", r["module_keys"])
        self.assertGreater(r["checklist_rows_count"], 0)
        self.assertGreater(r["drawing_strokes_count"], 0)

        joined_warns = "\n".join(r["host_warnings"])
        self.assertIn("simple_fog", joined_warns)
        self.assertIn("campaign_time", joined_warns)
        self.assertIn("playtest_blocked", joined_warns)

        state = r["console_state"]
        self.assertGreater(state.get("live_subscribed_count", 0), 0)
        self.assertEqual(state.get("total_entries"), state.get("live_subscribed_count"))

    def test_skip_policy_prevents_disabled_checklist_and_drawing_writes(self) -> None:
        r = self.results["valid_json_skip"]
        self.assertIs(r["prepare_ok"], True)
        self.assertIn("sdk_log_console", r["module_keys"])
        self.assertNotIn("checklist", r["module_keys"])
        self.assertNotIn("drawing", r["module_keys"])
        joined_warns = "\n".join(r["host_warnings"])
        self.assertIn("policy=skip", joined_warns)

    def test_plain_log_and_error_replay_safe(self) -> None:
        r = self.results["plain_log"]
        self.assertIs(r["inspect"].get("ok"), True)
        self.assertEqual(r["inspect"]["counts"]["records"], 4)
        self.assertIs(r["prepare_ok"], True)
        self.assertIs(r["roundtrip_ok"], True)
        tail = r["console_state"].get("entries_tail", [])
        levels = {e.get("level_name") for e in tail}
        self.assertIn("ERROR", levels)
        self.assertIn("WARNING", levels)

    def test_empty_missing_corrupt_and_empty_options(self) -> None:
        for key in ("empty_file", "missing_path", "corrupt_json", "empty_options"):
            r = self.results[key]
            self.assertIs(r["inspect"].get("ok"), True, f"{key} inspect failed")
            self.assertIs(r["prepare_ok"], True, f"{key} prepare failed")
            self.assertIs(r["roundtrip_ok"], True, f"{key} roundtrip failed")
            self.assertGreater(r["host_progress_count"], 0, f"{key} missing host progress")

        self.assertEqual(self.results["corrupt_json"]["inspect"]["counts"]["unsupported"], 1)

    def test_stress_warnings_respects_host_100_and_7000_caps(self) -> None:
        r = self.results["stress_warnings"]
        self.assertIs(r["prepare_ok"], True)
        self.assertEqual(r["host_warnings_count"], 100)
        self.assertLessEqual(r["host_warnings_chars"], 7000)
        state = r["console_state"]
        self.assertGreaterEqual(state.get("warning_count", 0), 120)
        self.assertEqual(state.get("host_warning_count"), 100)
        self.assertLessEqual(state.get("host_warning_chars", 9999), 7000)

        rc = self.results["stress_char_cap"]
        self.assertIs(rc["prepare_ok"], True)
        self.assertLessEqual(rc["host_warnings_chars"], 7000)
        self.assertLess(rc["host_warnings_count"], 30)
        self.assertLessEqual(rc["console_state"].get("host_warning_chars", 9999), 7000)

    def test_logbus_subscribe_get_entries_and_unsubscribe_parity(self) -> None:
        p = self.results["logbus_parity"]
        self.assertIs(p["unsub_ok"], True)
        self.assertIs(p["sub_matches_first_3"], True)
        self.assertEqual(p["sub_seen_count"], 3)
        self.assertEqual(p["buf_entries_count"], 4)
        self.assertEqual(p["buf_warns_count"], 1)

    def test_multiline_log_with_mid_nul_bytes_not_truncated(self) -> None:
        r = self.results["nul_mid_log"]
        insp = r["inspect"]
        self.assertIs(insp.get("ok"), True)
        self.assertEqual(insp["counts"]["records"], 3)
        self.assertIs(r["prepare_ok"], True)
        self.assertIs(r["roundtrip_ok"], True)
        tail = r["console_state"].get("entries_tail", [])
        log_input_entries = [e for e in tail if e.get("source") == "log_input"]
        self.assertEqual(len(log_input_entries), 3)
        self.assertEqual([e.get("level_name") for e in log_input_entries], ["INFO", "WARNING", "ERROR"])
        self.assertIn("INFO firstafter_nul", str(log_input_entries[0].get("message", "")))
        self.assertIn("WARN second_line", str(log_input_entries[1].get("message", "")))
        self.assertIn("ERROR third_line", str(log_input_entries[2].get("message", "")))
        self.assertNotIn("Unicode parsing error", self.combined_godot_logs)

    def test_invalid_utf8_log_and_json_nul_numeric_level_no_unicode_errors(self) -> None:
        bad = self.results["bad_utf8_log"]
        self.assertIs(bad["inspect"].get("ok"), True)
        self.assertEqual(bad["inspect"]["counts"]["records"], 2)
        self.assertIs(bad["prepare_ok"], True)
        self.assertIs(bad["roundtrip_ok"], True)
        bad_log_entries = [
            e for e in bad["console_state"].get("entries_tail", []) if e.get("source") == "log_input"
        ]
        self.assertEqual([e.get("level_name") for e in bad_log_entries], ["INFO", "WARNING"])

        jn = self.results["json_nul_numeric"]
        self.assertIs(jn["inspect"].get("ok"), True)
        self.assertEqual(jn["inspect"]["counts"]["records"], 5)
        self.assertIs(jn["prepare_ok"], True)
        self.assertIs(jn["roundtrip_ok"], True)
        tail = jn["console_state"].get("entries_tail", [])
        num_entries = [e for e in tail if e.get("source") == "num_src"]
        self.assertEqual(
            [(e.get("level_name"), e.get("message")) for e in num_entries],
            [
                ("DEBUG", "dbg_10"),
                ("INFO", "inf_20"),
                ("WARNING", "wrn_30"),
                ("ERROR", "AB"),
            ],
        )
        esc_entries = [e for e in tail if e.get("source") == "esc_src"]
        self.assertEqual(
            [(e.get("level_name"), e.get("message")) for e in esc_entries],
            [("ERROR", "X\\u0000Y")],
        )
        self.assertNotIn("Unicode parsing error", self.combined_godot_logs)

    def test_tier5_array_module_options_and_min_level_error_r2_warnings(self) -> None:
        arr_case = self.results["array_module_options"]
        self.assertIs(arr_case["prepare_ok"], True)
        arr_st = arr_case["console_state"]
        audited_arr = arr_st.get("audited_modules", {})
        self.assertEqual(sorted(audited_arr.keys()), ["checklist", "simple_fog"])
        self.assertIs(audited_arr["simple_fog"]["enabled"], True)
        self.assertIs(audited_arr["checklist"]["enabled"], True)

        min_err = self.results["min_level_error_preserves_r2"]
        self.assertIs(min_err["prepare_ok"], True)
        self.assertGreaterEqual(min_err["host_warnings_count"], 1)
        self.assertTrue(any("simple_fog" in w for w in min_err.get("host_warnings", [])))
        self.assertEqual(
            [e for e in min_err["console_state"].get("entries_tail", []) if e.get("level") == 30],
            [],
        )

        null_insp = self.results["null_host_inspect"]
        null_prep = self.results["null_host_prepare"]
        self.assertIs(null_insp.get("ok"), True)
        self.assertIs(null_prep.get("ok"), False)

        dir_case = self.results["dir_and_scalar_json"]
        self.assertIs(dir_case["prepare_ok"], True)

        iso_case = self.results["isolation_after_custom"]
        self.assertIs(iso_case["prepare_ok"], True)
        self.assertEqual(
            sorted(iso_case["console_state"].get("audited_modules", {}).keys()),
            ["campaign_time", "checklist", "drawing", "simple_fog"],
        )


_INWORLD_PROBE_GD = r'''extends SceneTree

var _out_path: String = ""
var _zip_path: String = ""


class _MockEngineLogger:
	extends RefCounted

	var text: String = "[100] INFO MOCK_ENGINE_LINE_OK\n[101] WARNING MOCK_ENGINE_WARN_LINE"
	var line_count: int = 2
	var dropped: int = 0

	func capture() -> Dictionary:
		return {
			"text": text,
			"bytes": text.length(),
			"lines": line_count,
			"dropped": dropped,
		}


class _MockDevTools:
	extends CanvasLayer

	var _engine_logger := _MockEngineLogger.new()


class _MockDesktopApi:
	extends "res://_host_shims/desktop_api_service.gd"

	var saved_entries: Dictionary = {}

	func is_gm() -> bool:
		return true

	func network_role() -> String:
		return "solo"

	func active_scene_name() -> String:
		return "HybridDebugArena"

	func active_floor_uid() -> String:
		return "0123456789abcdef0123456789abcdef"

	func read_saved_module_entry(module_id: String) -> Dictionary:
		if saved_entries.has(module_id):
			return (saved_entries[module_id] as Dictionary).duplicate(true)
		return {}


class _MockScreenHost:
	extends Control

	var mounted_panels: Array[Control] = []

	func mount_floating_panel(panel: Control) -> bool:
		if not is_instance_valid(panel) or panel.get_parent() != null or panel.is_queued_for_deletion():
			return false
		mounted_panels.append(panel)
		add_child(panel)
		return panel.get_parent() == self


class _MockRuntime:
	extends Node

	var slots: SlotRegistry
	var hooks: HookBus
	var _desktop_ref: WeakRef
	var _screen_host: Control
	var _services: Dictionary = {}
	var _gen: int = 1

	func setup(desktop: Node, screen_host: Control) -> void:
		_desktop_ref = weakref(desktop)
		_screen_host = screen_host
		slots = SlotRegistry.new()
		slots.name = "SlotRegistry"
		add_child(slots)
		hooks = HookBus.new()
		hooks.name = "HookBus"
		add_child(hooks)

	func get_desktop() -> Node:
		return _desktop_ref.get_ref() as Node if _desktop_ref != null else null

	func get_screen_host() -> Control:
		return _screen_host

	func accepting_registrations() -> bool:
		return true

	func create_context(ext_owner: Node) -> ExtensionContext:
		var ctx := ExtensionContext.new()
		ctx._bind(ext_owner, self, _gen, false)
		return ctx

	func publish_service_entry(service_id: String, service: Object) -> void:
		_services[service_id] = service

	func unpublish_service_entry(service_id: String, service: Object) -> void:
		if _services.get(service_id) == service:
			_services.erase(service_id)

	func consume_service_entry(service_id: String) -> Object:
		return _services.get(service_id, null) as Object


class _MockDesktop:
	extends Node2D

	var _runtime: _MockRuntime
	var _network_session: DesktopNetworkSession

	func set_runtime(rt: _MockRuntime) -> void:
		_runtime = rt

	func get_extension_runtime() -> Node:
		return _runtime

	func set_network_session(net: DesktopNetworkSession) -> void:
		_network_session = net

	func get_network_session() -> DesktopNetworkSession:
		return _network_session

	func can_author_world() -> bool:
		return _network_session != null and _network_session.can_author_world()


func _init() -> void:
	for raw_arg: String in OS.get_cmdline_user_args():
		if raw_arg.begins_with("--out="):
			_out_path = raw_arg.substr(6)
		elif raw_arg.begins_with("--zip="):
			_zip_path = raw_arg.substr(6)
	call_deferred(&"_run")


func _write_json(data: Dictionary) -> void:
	var f: FileAccess = FileAccess.open(_out_path, FileAccess.WRITE)
	if f != null:
		f.store_string(JSON.stringify(data, "\t"))
		f.close()


func _run_one_lifecycle(
	mod_scene: PackedScene,
	saved_entry: Dictionary,
	exercise_interactions: bool
) -> Dictionary:
	var devtools := _MockDevTools.new()
	devtools.name = "DevTools"
	root.add_child(devtools)

	var desktop := _MockDesktop.new()
	desktop.name = "DesktopScreen"
	var screen_host := _MockScreenHost.new()
	screen_host.name = "ScreenHost"
	screen_host.size = Vector2(1280, 720)
	desktop.add_child(screen_host)

	var runtime := _MockRuntime.new()
	runtime.name = "ExtensionRuntime"
	desktop.add_child(runtime)
	desktop.set_runtime(runtime)

	var net_session := DesktopNetworkSession.new()
	net_session.name = "NetworkSession"
	desktop.add_child(net_session)
	desktop.set_network_session(net_session)

	var features := Node2D.new()
	features.name = "Features"
	runtime.add_child(features)

	root.add_child(desktop)
	runtime.setup(desktop, screen_host)

	var api_service := _MockDesktopApi.new(desktop)
	api_service.saved_entries["sdk_log_console"] = saved_entry.duplicate(true)
	runtime.publish_service_entry("desktop_api", api_service)

	var mod_inst := mod_scene.instantiate() as ExtensionBase
	mod_inst.set_meta(&"module_id", "mod.sdk_log_console")
	mod_inst.set_meta(&"module_core", true)
	features.add_child(mod_inst)

	var out: Dictionary = {
		"ctx_active": mod_inst.ctx != null and mod_inst.ctx.is_active(),
		"net_actions_count": runtime.slots.get_items(&"network.actions").size(),
		"net_projections_count": runtime.slots.get_items(&"network.projections").size(),
		"net_presentations_count": runtime.slots.get_items(&"network.presentations").size(),
		"settings_items_count": runtime.slots.get_items(&"ui.module_settings").size(),
	}

	# Verify NetworkHelper rejects network registration when local_only == true
	var sdk_scr := load("res://mods/sdk_log_console/lib/fu_runtime/v2.gd") as Script
	var sdk := sdk_scr.new() as RefCounted
	var net_helper := sdk.call(&"create_network_helper", "mod.sdk_log_console", true, mod_inst.ctx, null) as RefCounted
	var net_reg_res: Dictionary = net_helper.call(&"register_network_actions", mod_inst) as Dictionary
	out["local_only_net_helper_rejected"] = not bool(net_reg_res.get("ok", true))
	out["local_only_net_helper_reason"] = str(net_reg_res.get("reason", ""))
	net_helper.call(&"unbind")
	net_helper = null

	var settings_items: Array = runtime.slots.get_items(&"ui.module_settings")
	if not settings_items.is_empty():
		var spec: Dictionary = (settings_items[0] as Dictionary).get("spec", {})
		var settings_scene := spec.get("scene") as PackedScene
		var provider: Object = spec.get("provider") as Object
		var settings_ctrl := settings_scene.instantiate() as Control
		desktop.add_child(settings_ctrl)
		var bound_ok: bool = bool(settings_ctrl.call(&"bind_provider", provider))
		settings_ctrl.call(&"refresh")
		out["settings_bind_ok"] = bound_ok

		var win := mod_inst.call(&"get_floating_window") as Control
		out["initial_visible"] = bool(mod_inst.call(&"is_console_visible"))
		out["initial_window_open"] = bool(win.call(&"is_console_open")) if is_instance_valid(win) else false
		out["window_mounted_to_screen_host"] = is_instance_valid(win) and win.get_parent() == screen_host

		if exercise_interactions and is_instance_valid(win):
			var vis_chk := settings_ctrl.get_node_or_null("%ConsoleVisibleCheck") as CheckButton
			vis_chk.set_pressed(true)
			out["after_open_visible"] = bool(mod_inst.call(&"is_console_visible"))
			out["after_open_window_open"] = bool(win.call(&"is_console_open"))
			out["after_open_node_visible"] = win.visible

			runtime.hooks.emit_hook(&"dice.rolled", [{"expr": "1d20", "total": 18}])
			runtime.hooks.emit_hook(&"combat.started", [{"round": 1}])
			runtime.hooks.emit_hook(&"mode.changed", ["select", "build"])
			runtime.hooks.emit_hook(&"mod.sdk_log_console.diagnostic", [{"level": "warning", "source": "probe.custom", "message": "CUSTOM_HOOK_WARNING_OK"}])

			mod_inst.call(&"run_console_command", "help")
			mod_inst.call(&"run_console_command", "status")
			mod_inst.call(&"run_console_command", "entities")
			mod_inst.call(&"run_console_command", "hooks")
			mod_inst.call(&"run_console_command", "unknown_cmd_test")

			win.call(&"refresh_logs")
			var rendered_all: String = str(win.call(&"get_rendered_log_text"))
			var log_rt := win.get_node_or_null("%LogOutput") as RichTextLabel
			var parsed_all: String = log_rt.get_parsed_text() if log_rt != null else ""
			out["rendered_all"] = rendered_all
			out["parsed_all"] = parsed_all

			win.call(&"set_filter", "warning", "CUSTOM_HOOK_WARNING_OK")
			out["filtered_warn"] = str(win.call(&"get_rendered_log_text"))
			win.call(&"set_filter", "all", "")

			var tog_btn := settings_ctrl.get_node_or_null("%ToggleConsoleButton") as Button
			tog_btn.pressed.emit()
			out["after_close_visible"] = bool(mod_inst.call(&"is_console_visible"))
			out["after_close_window_open"] = bool(win.call(&"is_console_open"))
			out["after_close_node_visible"] = win.visible

			# Regression: deactivate() -> refresh() must preserve _provider_ref, reconnect signals, and stay interactive
			settings_ctrl.call(&"deactivate")
			settings_ctrl.call(&"refresh")
			var vis_chk_reactivated := settings_ctrl.get_node_or_null("%ConsoleVisibleCheck") as CheckButton
			out["after_deactivate_refresh_chk_disabled"] = vis_chk_reactivated.disabled if vis_chk_reactivated != null else true
			var sibling_panel := Control.new()
			sibling_panel.name = "SiblingPanel"
			screen_host.add_child(sibling_panel)
			out["before_reopen_behind_sibling"] = win.get_index() < sibling_panel.get_index()
			mod_inst.call(&"set_console_visible", true)
			out["after_deactivate_refresh_signal_pressed"] = vis_chk_reactivated.button_pressed if vis_chk_reactivated != null else false
			out["after_deactivate_refresh_win_open"] = bool(win.call(&"is_console_open"))
			out["after_open_moved_to_front"] = win.get_index() > sibling_panel.get_index()
			screen_host.remove_child(sibling_panel)
			sibling_panel.free()
			tog_btn.pressed.emit()
			out["after_deactivate_refresh_toggled_closed"] = (not bool(mod_inst.call(&"is_console_visible"))) and (not bool(win.call(&"is_console_open")))

			# Regression: 1-arg mode.changed defensive handling & _engine_logger ring-buffer wraparound
			runtime.hooks.emit_hook(&"mode.changed", ["build"])
			var st_after_1arg: Dictionary = mod_inst.call(&"get_status_summary") as Dictionary
			var hook_counts_after: Dictionary = st_after_1arg.get("hook_counts", {}) as Dictionary
			out["hook_mode_changed_count"] = int(hook_counts_after.get("mode.changed", 0))

			devtools._engine_logger.text = "[101] WARNING MOCK_ENGINE_WARN_LINE\n[102] INFO WRAP_ENGINE_LINE_OK"
			devtools._engine_logger.line_count = 2
			devtools._engine_logger.dropped = 1
			out["engine_wrap_added"] = int(mod_inst.call(&"ingest_engine_logger"))
			win.call(&"refresh_logs")
			out["engine_wrap_rendered"] = str(win.call(&"get_rendered_log_text"))

			# Regression: multi-line ScriptBacktrace ring-buffer wraparound (same-size 5->5, shrink 5->1, evict-only)
			var ml1_head := "[200] SCRIPT res://a.gd:1 ML1_OLD_HEAD\n  f1\n  f2\n  f3\n  f4"
			var ml1_mid := "[201] INFO ML1_E1\n[202] INFO ML1_E2\n[203] INFO ML1_E3\n[204] INFO ML1_E4\n[205] INFO ML1_E5"
			devtools._engine_logger.text = ml1_head + "\n" + ml1_mid
			devtools._engine_logger.line_count = 6
			devtools._engine_logger.dropped = 10
			out["ml_init_added"] = int(mod_inst.call(&"ingest_engine_logger"))
			var ml1_new := "[206] SCRIPT res://b.gd:2 NEW_STACK_HEAD\n  nf1\n  nf2\n  nf3\n  nf4"
			devtools._engine_logger.text = ml1_mid + "\n" + ml1_new
			devtools._engine_logger.line_count = 6
			devtools._engine_logger.dropped = 11
			out["ml_same_size_added"] = int(mod_inst.call(&"ingest_engine_logger"))
			out["ml_new_stack_head_count"] = (mod_inst.call(&"get_console_entries", "all", "NEW_STACK_HEAD") as Array).size()

			var ml2_head := "[300] SCRIPT res://c.gd:1 ML2_OLD_HEAD\n  g1\n  g2\n  g3\n  g4"
			var ml2_mid := "[301] INFO ML2_E1\n[302] INFO ML2_E2\n[303] INFO ML2_E3\n[304] INFO ML2_E4\n[305] INFO ML2_E5"
			devtools._engine_logger.text = ml2_head + "\n" + ml2_mid
			devtools._engine_logger.line_count = 6
			devtools._engine_logger.dropped = 20
			out["ml2_init_added"] = int(mod_inst.call(&"ingest_engine_logger"))
			devtools._engine_logger.text = ml2_mid + "\n[306] INFO ML2_E6_NEW"
			devtools._engine_logger.line_count = 6
			devtools._engine_logger.dropped = 21
			out["ml2_shrink_added"] = int(mod_inst.call(&"ingest_engine_logger"))
			out["ml2_dup_e1_count"] = (mod_inst.call(&"get_console_entries", "all", "ML2_E1") as Array).size()
			out["ml2_new_e6_count"] = (mod_inst.call(&"get_console_entries", "all", "ML2_E6_NEW") as Array).size()
			devtools._engine_logger.text = "[302] INFO ML2_E2\n[303] INFO ML2_E3\n[304] INFO ML2_E4\n[305] INFO ML2_E5\n[306] INFO ML2_E6_NEW"
			devtools._engine_logger.line_count = 5
			devtools._engine_logger.dropped = 22
			out["ml2_evict_only_added"] = int(mod_inst.call(&"ingest_engine_logger"))

			# Regression a6b: full FIFO rollover (>4096 entries) with recurring ScriptBacktrace frame
			devtools._engine_logger.text = "[20000] SCRIPT res://main.gd:42 PREV_ERR\n  at: _process (res://main.gd:42)"
			devtools._engine_logger.line_count = 1
			devtools._engine_logger.dropped = 5000
			out["a6b_pre_added"] = int(mod_inst.call(&"ingest_engine_logger"))

			var burst_entries: PackedStringArray = PackedStringArray()
			for bi: int in range(4096):
				if bi == 2000:
					burst_entries.append("[32000] SCRIPT res://main.gd:42 BURST_ERR_2000\n  at: _process (res://main.gd:42)")
				else:
					burst_entries.append("[%d] INFO BURST_LOG_%04d" % [30000 + bi, bi])
			devtools._engine_logger.text = "\n".join(burst_entries)
			devtools._engine_logger.line_count = 4096
			devtools._engine_logger.dropped = 10000

			var a6b_seen := {"has_0000": false, "has_2000_err": false}
			var mod_bus := mod_inst.get(&"_logger") as RefCounted
			var a6b_tok: int = -1
			if mod_bus != null:
				a6b_tok = int(mod_bus.call(&"subscribe", func(entry: Dictionary) -> void:
					var msg: String = str(entry.get("message", ""))
					if msg.contains("BURST_LOG_0000"):
						a6b_seen["has_0000"] = true
					if msg.contains("BURST_ERR_2000") and str(entry.get("level_name", "")) == "ERROR":
						a6b_seen["has_2000_err"] = true
				))
			out["a6b_burst_added"] = int(mod_inst.call(&"ingest_engine_logger"))
			if mod_bus != null and a6b_tok >= 0:
				mod_bus.call(&"unsubscribe", a6b_tok)
			mod_bus = null
			out["a6b_burst_0000_present"] = bool(a6b_seen["has_0000"])
			out["a6b_burst_2000_err_present"] = bool(a6b_seen["has_2000_err"])
			out["a6b_burst_4095_present"] = (mod_inst.call(&"get_console_entries", "all", "BURST_LOG_4095") as Array).size() == 1

			# Regression a6c: MAX_BYTES rollover (64 entries, dropped_delta=65) with recurring "[message truncated]" trailer
			var trunc_pre: PackedStringArray = PackedStringArray()
			for ti: int in range(64):
				if ti == 63:
					trunc_pre.append("[40063] BIG_TRUNC_PREV\n[message truncated]")
				else:
					trunc_pre.append("[%d] INFO TRUNC_PREV_%02d" % [40000 + ti, ti])
			devtools._engine_logger.text = "\n".join(trunc_pre)
			devtools._engine_logger.line_count = 64
			devtools._engine_logger.dropped = 10000
			out["a6c_pre_added"] = int(mod_inst.call(&"ingest_engine_logger"))

			var trunc_new: PackedStringArray = PackedStringArray()
			for ni: int in range(64):
				if ni == 50:
					trunc_new.append("[41050] INFO TRUNC_MID_50\n[message truncated]")
				else:
					trunc_new.append("[%d] INFO TRUNC_NEW_%02d" % [41000 + ni, ni])
			devtools._engine_logger.text = "\n".join(trunc_new)
			devtools._engine_logger.line_count = 64
			devtools._engine_logger.dropped = 10065
			out["a6c_burst_added"] = int(mod_inst.call(&"ingest_engine_logger"))
			out["a6c_new_00_present"] = (mod_inst.call(&"get_console_entries", "all", "TRUNC_NEW_00") as Array).size() == 1
			out["a6c_new_63_present"] = (mod_inst.call(&"get_console_entries", "all", "TRUNC_NEW_63") as Array).size() == 1

			# Regression: invalid / missing-ctx providers must be rejected by both settings page and floating window
			var probe_settings := settings_scene.instantiate() as Control
			desktop.add_child(probe_settings)
			var plain_node := Node.new()
			var bare_ext := ExtensionBase.new()
			out["settings_invalid_null"] = bool(probe_settings.call(&"bind_provider", null))
			out["settings_invalid_node"] = bool(probe_settings.call(&"bind_provider", plain_node))
			out["settings_invalid_bare_ext"] = bool(probe_settings.call(&"bind_provider", bare_ext))
			var probe_chk := probe_settings.get_node_or_null("%ConsoleVisibleCheck") as CheckButton
			out["settings_invalid_chk_disabled"] = probe_chk.disabled if probe_chk != null else false
			out["settings_rebind_valid"] = bool(probe_settings.call(&"bind_provider", mod_inst))
			out["settings_rebind_chk_enabled"] = not probe_chk.disabled if probe_chk != null else false
			out["settings_rebind_invalid_node"] = bool(probe_settings.call(&"bind_provider", plain_node))
			out["settings_rebind_invalid_chk_disabled"] = probe_chk.disabled if probe_chk != null else false
			var probe_sum := probe_settings.get_node_or_null("%StatusSummaryLabel") as Label
			out["settings_rebind_invalid_summary"] = probe_sum.text if probe_sum != null else ""
			desktop.remove_child(probe_settings)
			probe_settings.free()

			var win_scene := load("res://mods/sdk_log_console/console_floating_window.tscn") as PackedScene
			var probe_win := win_scene.instantiate() as Control
			desktop.add_child(probe_win)
			out["window_invalid_null"] = bool(probe_win.call(&"bind_provider", null))
			out["window_invalid_node"] = bool(probe_win.call(&"bind_provider", plain_node))
			out["window_invalid_bare_ext"] = bool(probe_win.call(&"bind_provider", bare_ext))
			out["window_rebind_valid"] = bool(probe_win.call(&"bind_provider", mod_inst))
			out["window_rebind_valid_has_logs"] = str(probe_win.call(&"get_rendered_log_text")).contains("BURST_LOG_4095")
			out["window_rebind_invalid_node"] = bool(probe_win.call(&"bind_provider", plain_node))
			out["window_rebind_invalid_rendered"] = str(probe_win.call(&"get_rendered_log_text"))
			desktop.remove_child(probe_win)
			probe_win.free()
			bare_ext.free()
			plain_node.free()

		settings_ctrl.call(&"deactivate")
		desktop.remove_child(settings_ctrl)
		settings_ctrl.free()

	mod_inst.deregister_now()
	features.remove_child(mod_inst)
	mod_inst.free()
	out["screen_host_children_after_unregister"] = screen_host.get_child_count()

	runtime.unpublish_service_entry("desktop_api", api_service)
	api_service = null
	root.remove_child(desktop)
	desktop.free()
	root.remove_child(devtools)
	devtools.free()
	return out


func _run() -> void:
	if _zip_path.is_empty() or not FileAccess.file_exists(_zip_path):
		_write_json({"ok": false, "error": "missing_zip_path"})
		quit(1)
		return
	var mounted: bool = ProjectSettings.load_resource_pack(_zip_path, false)
	if not mounted:
		_write_json({"ok": false, "error": "load_resource_pack_failed"})
		quit(1)
		return

	var mod_scene := load("res://mods/sdk_log_console/module.tscn") as PackedScene
	if mod_scene == null:
		_write_json({"ok": false, "error": "module_scene_load_failed"})
		quit(1)
		return

	var saved_entry: Dictionary = {
		"version": 1,
		"state": {
			"input_kind": "json",
			"total_entries": 2,
			"warning_count": 1,
			"entries_tail": [
				{
					"seq": 1,
					"level": 20,
					"level_name": "INFO",
					"source": "imported_session",
					"message": "SAVED_IMPORT_MARKER_OK",
				}
			],
		},
	}

	# Cycle 1: Warm-up + full functional verification
	var res: Dictionary = _run_one_lifecycle(mod_scene, saved_entry, true)

	# Cycle 2: Measure ObjectDB delta across a complete lifecycle
	var obj_before: float = Performance.get_monitor(Performance.OBJECT_COUNT)
	var _cycle2: Dictionary = _run_one_lifecycle(mod_scene, saved_entry, true)
	var obj_after: float = Performance.get_monitor(Performance.OBJECT_COUNT)
	res["object_count_before"] = obj_before
	res["object_count_after"] = obj_after
	res["object_count_delta"] = obj_after - obj_before

	_write_json({"ok": true, "result": res})
	quit(0)
'''


class TestConsoleLogModInWorldHeadlessGodot(unittest.TestCase):
    """Real headless Godot tests for hybrid in-world local-only activation, settings UI, console window, and ObjectDB teardown."""

    run_dir: Path | None = None
    verify_host_result = None
    inworld_result: dict = {}
    combined_godot_logs: str = ""

    @classmethod
    def setUpClass(cls) -> None:
        cfg = load_config(_WORKSPACE_ROOT)
        godot_bin = cfg.godot_bin
        if godot_bin is None or not godot_bin.is_file():
            raise unittest.SkipTest("GODOT_BIN not configured in .env.local; skipping in-world headless Godot tests")

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        cls.run_dir = TEST_TMP_ROOT / f"console_inworld_{uuid.uuid4().hex[:10]}"
        (cls.run_dir / "build").mkdir(parents=True, exist_ok=True)
        # Reuse workspace .cache/fus_host_stage when present so --fus-repo auto does not re-stage FUS from scratch.
        iso_cfg = load_config(
            _WORKSPACE_ROOT,
            environ={
                "BUILD_DIR": str((cls.run_dir / "build").relative_to(_WORKSPACE_ROOT)),
                "CACHE_DIR": str(cfg.cache_dir.relative_to(_WORKSPACE_ROOT)),
            },
        )
        fus_repo_arg = "auto" if (cfg.fus_repo_dir and cfg.fus_repo_dir.is_dir()) else None
        cls.verify_host_result = verify_mod_with_host(MOD_NAME, config=iso_cfg, fus_repo=fus_repo_arg)

        zip_path = iso_cfg.build_dir / MOD_NAME / f"{MOD_NAME}.zip"
        probe_dir = cls.run_dir / "inworld_probe_proj"
        shims_dir = probe_dir / "_host_shims"
        godot_dir = probe_dir / ".godot"
        shims_dir.mkdir(parents=True, exist_ok=True)
        godot_dir.mkdir(parents=True, exist_ok=True)

        (probe_dir / "project.godot").write_bytes(PROBE_PROJECT_GODOT.encode("utf-8"))
        for fname, (_, code) in _INWORLD_HOST_SHIMS.items():
            (shims_dir / fname).write_bytes(code.encode("utf-8"))
        (godot_dir / "global_script_class_cache.cfg").write_bytes(
            _render_global_script_class_cache().encode("utf-8")
        )
        (probe_dir / "inworld_probe.gd").write_bytes(_INWORLD_PROBE_GD.encode("utf-8"))

        out_path = cls.run_dir / "inworld_out.json"
        isolated_env = cls.run_dir / "isolated_env"
        isolated_env.mkdir(parents=True, exist_ok=True)
        godot_log = cls.run_dir / "godot_inworld.log"
        env = dict(os.environ)
        env["APPDATA"] = str(isolated_env)
        env["LOCALAPPDATA"] = str(isolated_env)
        env["TEMP"] = str(isolated_env)
        env["TMP"] = str(isolated_env)
        env["GODOT_SILENCE_ROOT_WARNING"] = "1"

        proc = subprocess.run(
            [
                str(godot_bin),
                "--headless",
                "--quit",
                "--path",
                str(probe_dir),
                "--log-file",
                str(godot_log),
                "--script",
                "res://inworld_probe.gd",
                "--",
                f"--out={out_path}",
                f"--zip={zip_path}",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log_text = godot_log.read_text(encoding="utf-8", errors="replace") if godot_log.is_file() else ""
        cls.combined_godot_logs = "\n".join((log_text, proc.stdout, proc.stderr))
        log_errors = analyze_godot_logs(log_text, proc.stdout, proc.stderr)
        if proc.returncode != 0 or log_errors:
            redacted = cfg.redact_path(
                f"rc={proc.returncode} errors={log_errors}\n"
                f"stdout={proc.stdout[-1200:]}\nstderr={proc.stderr[-1200:]}"
            )
            raise AssertionError(f"Headless Godot in-world probe failed:\n{redacted}")

        parsed = json.loads(out_path.read_text(encoding="utf-8"))
        if not parsed.get("ok"):
            raise AssertionError(f"In-world probe returned failure: {parsed}")
        cls.inworld_result = parsed["result"]

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.run_dir is not None and cls.run_dir.exists():
            shutil.rmtree(cls.run_dir, ignore_errors=True)
        if TEST_TMP_ROOT.exists():
            try:
                if not any(TEST_TMP_ROOT.iterdir()):
                    TEST_TMP_ROOT.rmdir()
            except OSError:
                pass

    def test_verify_host_hybrid_and_fus_local_only_contract(self) -> None:
        res = self.verify_host_result
        self.assertIsNotNone(res)
        assert res is not None
        self.assertTrue(res.ok, f"verify-host failed: failures={res.failures} log_errors={res.log_errors}")
        self.assertEqual(res.schema, "fus.desktop-module.v1")
        self.assertEqual(res.failures, [])
        self.assertEqual(res.log_errors, [])
        self.assertIn("res://pkg/entry.gd", res.loaded_scripts)
        self.assertIn("res://mods/sdk_log_console/module.gd", res.loaded_scripts)
        self.assertIn("res://mods/sdk_log_console/lib/fu_runtime/v2.gd", res.loaded_scripts)
        cfg = load_config(_WORKSPACE_ROOT)
        if cfg.fus_repo_dir and cfg.fus_repo_dir.is_dir():
            self.assertTrue(res.host_contract_probe.get("ok"), f"FUS host probe failed: {res.host_contract_probe}")

    def test_local_only_zero_network_slots(self) -> None:
        r = self.inworld_result
        self.assertIs(r.get("ctx_active"), True)
        self.assertEqual(r.get("net_actions_count"), 0)
        self.assertEqual(r.get("net_projections_count"), 0)
        self.assertEqual(r.get("net_presentations_count"), 0)
        self.assertIs(r.get("local_only_net_helper_rejected"), True)
        self.assertEqual(r.get("local_only_net_helper_reason"), "local_only_network_disabled")

    def test_module_settings_ui_toggles_floating_console_window(self) -> None:
        r = self.inworld_result
        self.assertEqual(r.get("settings_items_count"), 1)
        self.assertIs(r.get("settings_bind_ok"), True)
        self.assertIs(r.get("window_mounted_to_screen_host"), True)
        self.assertIs(r.get("initial_visible"), False)
        self.assertIs(r.get("initial_window_open"), False)
        self.assertIs(r.get("after_open_visible"), True)
        self.assertIs(r.get("after_open_window_open"), True)
        self.assertIs(r.get("after_open_node_visible"), True)
        self.assertIs(r.get("after_close_visible"), False)
        self.assertIs(r.get("after_close_window_open"), False)
        self.assertIs(r.get("after_close_node_visible"), False)

    def test_floating_console_renders_logs_hooks_imports_engine_and_commands(self) -> None:
        r = self.inworld_result
        rendered = str(r.get("rendered_all", ""))
        parsed = str(r.get("parsed_all", ""))
        self.assertTrue(rendered)
        self.assertTrue(parsed)
        for text in (rendered, parsed):
            self.assertIn("SDK Log Console activated (local_only=true", text)
            self.assertIn("SAVED_IMPORT_MARKER_OK", text)
            self.assertIn("MOCK_ENGINE_LINE_OK", text)
            self.assertIn("hook.dice.rolled", text)
            self.assertIn("hook.combat.started", text)
            self.assertIn("hook.mode.changed", text)
            self.assertIn("CUSTOM_HOOK_WARNING_OK", text)
            self.assertIn("Commands: help | status", text)
            self.assertIn("status: module=mod.sdk_log_console", text)

        filtered = str(r.get("filtered_warn", ""))
        self.assertIn("CUSTOM_HOOK_WARNING_OK", filtered)
        self.assertNotIn("SAVED_IMPORT_MARKER_OK", filtered)

    def test_clean_unregister_teardown_zero_objectdb_leaks(self) -> None:
        r = self.inworld_result
        self.assertEqual(r.get("screen_host_children_after_unregister"), 0)
        self.assertEqual(r.get("object_count_delta"), 0.0)

    def test_settings_page_deactivate_refresh_and_invalid_provider_rejection(self) -> None:
        r = self.inworld_result
        self.assertIs(r.get("after_deactivate_refresh_chk_disabled"), False)
        self.assertIs(r.get("before_reopen_behind_sibling"), True)
        self.assertIs(r.get("after_deactivate_refresh_signal_pressed"), True)
        self.assertIs(r.get("after_deactivate_refresh_win_open"), True)
        self.assertIs(r.get("after_open_moved_to_front"), True)
        self.assertIs(r.get("after_deactivate_refresh_toggled_closed"), True)
        self.assertEqual(r.get("hook_mode_changed_count"), 2)
        self.assertEqual(r.get("engine_wrap_added"), 1)
        self.assertIn("WRAP_ENGINE_LINE_OK", str(r.get("engine_wrap_rendered", "")))
        self.assertEqual(r.get("ml_init_added"), 10)
        self.assertEqual(r.get("ml_same_size_added"), 5)
        self.assertEqual(r.get("ml_new_stack_head_count"), 1)
        self.assertEqual(r.get("ml2_init_added"), 10)
        self.assertEqual(r.get("ml2_shrink_added"), 1)
        self.assertEqual(r.get("ml2_dup_e1_count"), 1)
        self.assertEqual(r.get("ml2_new_e6_count"), 1)
        self.assertEqual(r.get("ml2_evict_only_added"), 0)
        self.assertIs(r.get("settings_invalid_null"), False)
        self.assertIs(r.get("settings_invalid_node"), False)
        self.assertIs(r.get("settings_invalid_bare_ext"), False)
        self.assertIs(r.get("settings_invalid_chk_disabled"), True)
        self.assertIs(r.get("settings_rebind_valid"), True)
        self.assertIs(r.get("settings_rebind_chk_enabled"), True)
        self.assertIs(r.get("settings_rebind_invalid_node"), False)
        self.assertIs(r.get("settings_rebind_invalid_chk_disabled"), True)
        self.assertEqual(r.get("settings_rebind_invalid_summary"), "模块未绑定或已停用。")
        self.assertIs(r.get("window_invalid_null"), False)
        self.assertIs(r.get("window_invalid_node"), False)
        self.assertIs(r.get("window_invalid_bare_ext"), False)
        self.assertIs(r.get("window_rebind_valid"), True)
        self.assertIs(r.get("window_rebind_valid_has_logs"), True)
        self.assertIs(r.get("window_rebind_invalid_node"), False)
        self.assertIn("暂无匹配日志", str(r.get("window_rebind_invalid_rendered", "")))
        self.assertNotIn("BURST_LOG_4095", str(r.get("window_rebind_invalid_rendered", "")))

    def test_engine_logger_full_fifo_rollover_burst_and_max_bytes_truncation(self) -> None:
        r = self.inworld_result
        # a6b: >4096-line burst with recurring ScriptBacktrace frame
        self.assertEqual(r.get("a6b_pre_added"), 2)
        self.assertEqual(r.get("a6b_burst_added"), 4097)
        self.assertIs(r.get("a6b_burst_0000_present"), True)
        self.assertIs(r.get("a6b_burst_2000_err_present"), True)
        self.assertIs(r.get("a6b_burst_4095_present"), True)
        # a6c: MAX_BYTES rollover (64 entries, dropped_delta=65) with recurring "[message truncated]" trailer
        self.assertEqual(r.get("a6c_pre_added"), 65)
        self.assertEqual(r.get("a6c_burst_added"), 65)
        self.assertIs(r.get("a6c_new_00_present"), True)
        self.assertIs(r.get("a6c_new_63_present"), True)


if __name__ == "__main__":
    unittest.main()
