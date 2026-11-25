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
from fuvtt_devtools.host_verifier import analyze_godot_logs, verify_mod_with_host  # noqa: E402
from fuvtt_devtools.packager import build_mod  # noqa: E402
from fuvtt_devtools.validator import validate_mod_dir  # noqa: E402

MOD_NAME = "sdk-log-console"
MOD_DIR = _WORKSPACE_ROOT / "mods" / MOD_NAME
SDK_DIR = _WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk"
TEST_TMP_ROOT = _WORKSPACE_ROOT / ".cache" / "test_tmp"

_FORBIDDEN_UI_PATTERNS = (
    re.compile(r"\b(?:Window|PopupPanel|Control)\.new\s*\("),
    re.compile(r"ui\.desktop_panels"),
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
        report = validate_mod_dir(MOD_DIR, mod_name=MOD_NAME, sdk_dir=SDK_DIR)
        self.assertTrue(report.ok, f"validate_mod_dir failed: {report.errors}")
        self.assertIsNotNone(report.manifest)
        assert report.manifest is not None
        self.assertEqual(report.manifest.get("schema"), "fus.session-plugin.v1")
        self.assertEqual(report.manifest.get("host_api"), 1)
        self.assertEqual(report.manifest.get("scope"), "session")
        self.assertEqual(report.manifest.get("id"), "sdk_log_console")
        self.assertEqual(report.manifest.get("entry"), "entry.gd")
        self.assertEqual(report.manifest.get("import_extensions"), ["json", "log"])
        for setting in report.manifest.get("settings", []):
            self.assertIn(setting.get("type"), ("bool", "string"))

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
        self.assertTrue(gd_files, "Expected at least entry.gd in mods/sdk-log-console/")
        for gd in gd_files:
            raw = gd.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"UTF-8 BOM in {gd}")
            self.assertNotIn(b"\r", raw, f"CR byte found in {gd}")
            text = raw.decode("utf-8")
            lines = [ln for ln in text.splitlines() if ln.strip()]
            self.assertGreater(len(lines), 0)
            self.assertEqual(lines[0].strip(), "extends RefCounted", f"First line must be extends RefCounted in {gd}")
            self.assertNotRegex(text, re.compile(r"(?m)^\s*class_name\b"), f"class_name forbidden in {gd}")
            self.assertNotIn("preload(", text, f"preload() forbidden in {gd}")
            self.assertNotIn("build_world(", text, f"Non-existent build_world() found in {gd}")
            for pat in _FORBIDDEN_UI_PATTERNS:
                self.assertNotRegex(text, pat, f"Forbidden UI mounting pattern {pat.pattern} in {gd}")

        entry_text = (MOD_DIR / "entry.gd").read_text(encoding="utf-8")
        self.assertIn("lib/fu_sdk/v1.gd", entry_text)
        self.assertIn("../../shared/sdk/fu_sdk/v1.gd", entry_text)

    def test_gitignore_whitelist_and_git_tracking(self) -> None:
        gitignore_text = (_WORKSPACE_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!/mods/sdk-log-console/", gitignore_text)

        # Ensure no .log file exists inside mods/sdk-log-console/ (globally ignored by *.log)
        log_files = list(MOD_DIR.rglob("*.log"))
        self.assertEqual(log_files, [], f"Do not store .log files in {MOD_DIR}: {log_files}")

        ci_proc = subprocess.run(
            ["git", "check-ignore", "-v", "mods/sdk-log-console/plugin.json"],
            cwd=str(_WORKSPACE_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertNotEqual(ci_proc.returncode, 0, f"plugin.json is still git-ignored: {ci_proc.stdout}")

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

            expected_sdk = {
                f"lib/fu_sdk/{p.relative_to(SDK_DIR).as_posix()}"
                for p in SDK_DIR.rglob("*.gd")
                if not any(part.startswith(".") or part == "__pycache__" for part in p.relative_to(SDK_DIR).parts)
            }
            self.assertGreaterEqual(len(expected_sdk), 26)  # v1 + adapter + log_bus + registry + 23 plugins + modules

            with zipfile.ZipFile(artifact.zip_path, "r") as zf:
                names = zf.namelist()
                self.assertLessEqual(len(names), 1000)
                self.assertGreaterEqual(len(names), 2)
                name_set = set(names)
                self.assertIn("plugin.json", name_set)
                self.assertIn("entry.gd", name_set)
                missing_sdk = sorted(expected_sdk - name_set)
                self.assertEqual(missing_sdk, [], f"Missing embedded SDK scripts: {missing_sdk}")
                for nm in names:
                    if nm.endswith((".gd", ".json")):
                        raw = zf.read(nm)
                        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f"BOM in ZIP member {nm}")
                        if nm.endswith(".gd"):
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


if __name__ == "__main__":
    unittest.main()
