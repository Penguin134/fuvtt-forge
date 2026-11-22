"""Comprehensive unit tests for Fu vtt zero-dependency developer toolchain."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import unittest
import uuid
import zipfile

TOOLS_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = TOOLS_DIR.parents[1]
TEST_TMP_ROOT = WORKSPACE_ROOT / ".cache" / "test_tmp"

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import fuvtt_cli  # noqa: E402
from fuvtt_devtools.client_inspector import (  # noqa: E402
    CONTRACT_WATCH_FILES,
    STEAM_EXTERNAL_PRACTICE_DLL_REL,
    STEAM_EXTERNAL_STORAGE_JSON_REL,
    build_synthetic_embedded_pck_exe,
    format_inspection_report,
    inspect_client,
    parse_embedded_pck,
)
from fuvtt_devtools.deployer import (  # noqa: E402
    DeployError,
    build_reconciled_settings,
    discover_built_packages,
    format_serve_banner,
    resolve_hosted_zip,
    safe_extract_zip,
    sync_mod,
)
from fuvtt_devtools.env_config import (  # noqa: E402
    ConfigError,
    DEFAULT_FUS_SOURCE_REF,
    DEFAULT_WORKSPACE_ROOT,
    WorkspaceConfig,
    load_config,
    redact_path,
)
from fuvtt_devtools.host_verifier import (  # noqa: E402
    analyze_godot_logs,
    prepare_probe_workspace,
    verify_mod_with_host,
)
from fuvtt_devtools.packager import PackageError, build_mod, bump_patch_version  # noqa: E402
from fuvtt_devtools.scaffold import ScaffoldError, scaffold_mod  # noqa: E402
from fuvtt_devtools.validator import (  # noqa: E402
    MAX_MANIFEST_BYTES,
    UTF8_BOM,
    validate_mod_dir,
    validate_mods,
    validate_zip_archive,
)


def _make_mock_fobr_zip(host_api: int = 1, entry_body: str = "extends RefCounted\n") -> bytes:
    buf = io.BytesIO()
    manifest = {
        "schema": "fus.session-plugin.v1",
        "host_api": host_api,
        "scope": "session",
        "id": "fobr_world_import",
        "version": "0.5.1",
        "name": "FOBR 导入",
        "entry": "entry.gd",
        "import_extensions": ["fobr"],
        "settings": [],
    }
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("plugin.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("entry.gd", entry_body)
    return buf.getvalue()


class BaseDevtoolsTestCase(unittest.TestCase):
    """Creates an isolated mock workspace inside `.cache/test_tmp/<uuid>/`."""

    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.case_dir = TEST_TMP_ROOT / f"case_{uuid.uuid4().hex[:10]}"
        self.ws_root = self.case_dir / "mock_ws"
        self.fake_steam_dir = self.case_dir / "FakeSteam" / "Fu vtt"
        self.fake_fus_repo = self.case_dir / "FakeFusRepo"
        self.fake_godot_bin = self.case_dir / "FakeGodot" / "Godot_v4.8-beta1_mono_win64_console.exe"

        # Build mock workspace layout
        (self.ws_root / "mods" / "_template" / "src").mkdir(parents=True, exist_ok=True)
        (self.ws_root / "mods" / "_template" / "assets").mkdir(parents=True, exist_ok=True)
        (self.ws_root / "mods" / "_template" / "src" / ".gitkeep").write_bytes(b"")
        (self.ws_root / "mods" / "_template" / "assets" / ".gitkeep").write_bytes(b"")

        template_manifest = {
            "schema": "fus.session-plugin.v1",
            "host_api": 1,
            "scope": "session",
            "id": "template_mod",
            "version": "0.1.0",
            "name": "Template Mod",
            "description": "基于 Fu vtt 防腐层 SDK 构建的会话导入插件模板。",
            "entry": "entry.gd",
            "import_extensions": ["fusdemo"],
            "import_action_label": "导入示例场景文件",
            "settings": [
                {
                    "id": "proxy",
                    "type": "string",
                    "label": "图片下载代理",
                    "default": "",
                },
                {
                    "id": "include_hidden",
                    "type": "bool",
                    "label": "包含隐藏物件",
                    "default": True,
                },
            ],
        }
        (self.ws_root / "mods" / "_template" / "plugin.json").write_bytes(
            (json.dumps(template_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        )
        (self.ws_root / "mods" / "_template" / "entry.gd").write_bytes(
            (
                "extends RefCounted\n\n"
                "func inspect_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:\n"
                "\treturn {\"ok\": true}\n\n"
                "func prepare_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:\n"
                "\treturn {\"ok\": true}\n"
            ).encode("utf-8")
        )
        (self.ws_root / "mods" / "_template" / "AGENTS.md").write_bytes(
            (
                "# 插件模板（`<mod-name>`）\n"
                "- 标识：`template-mod` (`template_mod`)\n"
                "python shared/tools/fuvtt_cli.py validate _template\n"
                "python shared/tools/fuvtt_cli.py build _template --bump-dev\n"
                "python shared/tools/fuvtt_cli.py sync _template\n"
            ).encode("utf-8")
        )

        # Populate mock shared/sdk/fu_sdk/
        sdk_root = self.ws_root / "shared" / "sdk" / "fu_sdk"
        (sdk_root / "adapters").mkdir(parents=True, exist_ok=True)
        (sdk_root / "v1.gd").write_bytes(b"extends RefCounted\nconst SDK_VERSION := \"1.1.0\"\n")
        (sdk_root / "adapters" / "host_v1_adapter.gd").write_bytes(
            b"extends RefCounted\nconst WORLD_UNITS_PER_CELL := 64.0\n"
        )

        # Mock .env.local inside mock_ws (never reading real workspace .env.local)
        self.env_file = self.ws_root / ".env.local"
        self.env_file.write_bytes(
            (
                "# Mock environment config\n"
                f'FUVTT_INSTALL_DIR="{self.fake_steam_dir.as_posix()}" # inline comment\n'
                "BUILD_DIR=build\n"
                "CACHE_DIR=.cache\n"
            ).encode("utf-8")
        )
        self.cfg: WorkspaceConfig = load_config(self.ws_root, env_file=self.env_file, environ={})

    def tearDown(self) -> None:
        if self.case_dir.exists():
            shutil.rmtree(self.case_dir, ignore_errors=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if TEST_TMP_ROOT.exists():
            try:
                if not any(TEST_TMP_ROOT.iterdir()):
                    TEST_TMP_ROOT.rmdir()
            except OSError:
                pass


class EnvConfigTests(BaseDevtoolsTestCase):
    def test_default_workspace_root_points_to_monorepo_root(self) -> None:
        self.assertEqual(DEFAULT_WORKSPACE_ROOT, WORKSPACE_ROOT.resolve())
        self.assertTrue((DEFAULT_WORKSPACE_ROOT / "AGENTS.md").is_file())
        self.assertTrue((DEFAULT_WORKSPACE_ROOT / "mods" / "_template").is_dir())

    def test_dotenv_parsing_and_env_override(self) -> None:
        self.assertEqual(self.cfg.fuvtt_install_dir, self.fake_steam_dir.resolve())
        self.assertEqual(self.cfg.build_dir, (self.ws_root / "build").resolve())
        self.assertEqual(self.cfg.cache_dir, (self.ws_root / ".cache").resolve())
        self.assertEqual(self.cfg.fus_source_ref, DEFAULT_FUS_SOURCE_REF)
        self.assertIsNone(self.cfg.fus_repo_dir)
        self.assertIsNone(self.cfg.godot_bin)

        override_cfg = load_config(
            self.ws_root,
            env_file=self.env_file,
            environ={
                "BUILD_DIR": "build/custom_out",
                "FUS_REPO_DIR": str(self.fake_fus_repo),
                "FUS_SOURCE_REF": "origin/codex/fuvtt-v056-map-editors",
                "GODOT_BIN": str(self.fake_godot_bin),
            },
        )
        self.assertEqual(override_cfg.build_dir, (self.ws_root / "build" / "custom_out").resolve())
        self.assertEqual(override_cfg.resolve_fus_repo_dir(), self.fake_fus_repo.resolve())
        self.assertEqual(override_cfg.fus_source_ref, "origin/codex/fuvtt-v056-map-editors")
        self.assertEqual(override_cfg.resolve_godot_bin(), self.fake_godot_bin.resolve())

    def test_redact_path_hides_install_fus_repo_and_godot_bin(self) -> None:
        rich_cfg = load_config(
            self.ws_root,
            env_file=self.env_file,
            environ={
                "FUS_REPO_DIR": str(self.fake_fus_repo),
                "GODOT_BIN": str(self.fake_godot_bin),
            },
        )
        secret_msg = (
            f"steam={self.fake_steam_dir.resolve()}\\FUS_Data\\session_plugins | "
            f"repo={self.fake_fus_repo.resolve().as_posix()}/project.godot | "
            f"godot={self.fake_godot_bin.resolve()}"
        )
        redacted = rich_cfg.redact_path(secret_msg)
        self.assertNotIn("FakeSteam", redacted)
        self.assertNotIn("FakeFusRepo", redacted)
        self.assertNotIn("FakeGodot", redacted)
        self.assertIn("<FUVTT_INSTALL_DIR>", redacted)
        self.assertIn("<FUS_REPO_DIR>", redacted)
        self.assertIn("<GODOT_BIN>", redacted)

        direct = redact_path(
            self.fake_steam_dir.resolve().as_posix() + "/FUS_Data/session_plugins/registry.json",
            self.fake_steam_dir,
        )
        self.assertEqual(direct, "<FUVTT_INSTALL_DIR>/FUS_Data/session_plugins/registry.json")

    def test_out_of_bounds_build_or_cache_dir_blocked(self) -> None:
        with self.assertRaises(ConfigError):
            load_config(
                self.ws_root,
                env_file=self.env_file,
                environ={"BUILD_DIR": "../outside_sandbox"},
            )
        with self.assertRaises(ConfigError):
            load_config(
                self.ws_root,
                env_file=self.env_file,
                environ={"CACHE_DIR": str(self.case_dir.resolve())},
            )
        with self.assertRaises(ConfigError):
            load_config(
                self.ws_root,
                env_file=self.env_file,
                environ={"BUILD_DIR": "."},
            )

    def test_session_plugins_resolution_and_macos_fallback(self) -> None:
        default_sp = self.cfg.resolve_session_plugins_dir(platform_name="win32")
        self.assertEqual(
            default_sp,
            (self.fake_steam_dir / "FUS_Data" / "session_plugins").resolve(),
        )

        sub_cfg = load_config(
            self.ws_root,
            env_file=self.env_file,
            environ={"FUVTT_MODS_SUBDIR": "CustomData/plugins"},
        )
        self.assertEqual(
            sub_cfg.resolve_session_plugins_dir(),
            (self.fake_steam_dir / "CustomData" / "plugins").resolve(),
        )

        no_install_cfg = load_config(self.ws_root, env_file=self.ws_root / "nonexistent.env", environ={})
        fake_home = self.case_dir / "mac_home"
        mac_sp = no_install_cfg.resolve_session_plugins_dir(platform_name="darwin", home_dir=fake_home)
        self.assertEqual(
            mac_sp,
            (fake_home / "Library" / "Application Support" / "FuVTT" / "session_plugins").resolve(),
        )


class ScaffoldTests(BaseDevtoolsTestCase):
    def test_scaffold_kebab_to_snake_and_placeholders(self) -> None:
        res = scaffold_mod(
            "my-awesome-mod",
            config=self.cfg,
            display_name="我的超酷模组",
            import_extensions=[".UVTT", "dd2vtt"],
        )
        self.assertEqual(res.mod_name, "my-awesome-mod")
        self.assertEqual(res.plugin_id, "my_awesome_mod")
        self.assertTrue(res.manifest_path.is_file())
        self.assertFalse(res.manifest_path.read_bytes().startswith(UTF8_BOM))

        manifest = json.loads(res.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], "my_awesome_mod")
        self.assertEqual(manifest["name"], "我的超酷模组")
        self.assertEqual(manifest["import_extensions"], ["uvtt", "dd2vtt"])

        agents_md = (res.target_dir / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("validate my-awesome-mod", agents_md)
        self.assertNotIn("validate _template", agents_md)

        report = validate_mod_dir(res.target_dir, mod_name="my-awesome-mod", sdk_dir=self.cfg.sdk_dir)
        self.assertTrue(report.ok, msg=f"Unexpected validation errors: {report.errors}")

    def test_scaffold_rejects_invalid_names_lengths_and_extensions(self) -> None:
        for bad_name in ("_template", "MyMod", "my_mod", "-leading", "trailing-", "double--dash", "", "a" * 65):
            with self.assertRaises(ScaffoldError, msg=f"Expected failure for {bad_name!r}"):
                scaffold_mod(bad_name, config=self.cfg)

        with self.assertRaises(ScaffoldError):
            scaffold_mod("too-long-title", config=self.cfg, display_name="X" * 81)
        with self.assertRaises(ScaffoldError):
            scaffold_mod("too-many-exts", config=self.cfg, import_extensions=[f"e{i}" for i in range(9)])
        with self.assertRaises(ScaffoldError):
            scaffold_mod("too-long-ext", config=self.cfg, import_extensions=["abcdefghijklm"])

        scaffold_mod("valid-mod", config=self.cfg)
        with self.assertRaises(ScaffoldError):
            scaffold_mod("valid-mod", config=self.cfg, force=False)
        scaffold_mod("valid-mod", config=self.cfg, force=True)


class ValidatorTests(BaseDevtoolsTestCase):
    def test_detects_utf8_bom(self) -> None:
        res = scaffold_mod("bom-test", config=self.cfg)
        raw = res.manifest_path.read_bytes()
        res.manifest_path.write_bytes(UTF8_BOM + raw)

        report = validate_mod_dir(res.target_dir, mod_name="bom-test")
        self.assertFalse(report.ok)
        self.assertTrue(any("BOM" in err for err in report.errors), msg=str(report.errors))

    def test_detects_illegal_settings_numeric_type_and_missing_settings_array(self) -> None:
        res = scaffold_mod("bad-settings", config=self.cfg)
        manifest = json.loads(res.manifest_path.read_text(encoding="utf-8"))
        manifest["settings"].append({"id": "grid_size", "type": "int", "label": "网格尺寸", "default": 64})
        res.manifest_path.write_bytes(json.dumps(manifest, indent=2).encode("utf-8"))

        report = validate_mod_dir(res.target_dir, mod_name="bad-settings")
        self.assertFalse(report.ok)
        self.assertTrue(any("settings[2].type='int'" in err for err in report.errors), msg=str(report.errors))

        # Missing `settings` key must fail (hard required by PluginPackageJob.cs:106)
        del manifest["settings"]
        res.manifest_path.write_bytes(json.dumps(manifest, indent=2).encode("utf-8"))
        report_missing = validate_mod_dir(res.target_dir, mod_name="bad-settings")
        self.assertFalse(report_missing.ok)
        self.assertTrue(any("invalid_plugin_settings" in err for err in report_missing.errors))

        # Empty `settings: []` must pass
        manifest["settings"] = []
        res.manifest_path.write_bytes(json.dumps(manifest, indent=2).encode("utf-8"))
        report_empty = validate_mod_dir(res.target_dir, mod_name="bad-settings")
        self.assertTrue(report_empty.ok, msg=str(report_empty.errors))

    def test_practice_csharp_id_length_and_field_bounds(self) -> None:
        res = scaffold_mod("bounds-test", config=self.cfg)
        manifest = json.loads(res.manifest_path.read_text(encoding="utf-8"))
        manifest["id"] = "9_starts_with_digit"
        manifest["name"] = "A" * 81
        manifest["description"] = "D" * 2001
        manifest["import_extensions"] = [f"ext{i}" for i in range(9)]
        manifest["settings"] = [
            {
                "id": "_leading_underscore",
                "type": "string",
                "label": "L" * 81,
                "default": "x" * 2049,
            }
        ]
        res.manifest_path.write_bytes(json.dumps(manifest, indent=2).encode("utf-8"))

        report = validate_mod_dir(res.target_dir, mod_name="bounds-test")
        self.assertFalse(report.ok)
        joined = "\n".join(report.errors)
        self.assertIn("^[a-z][a-z0-9_]{0,63}$", joined)
        self.assertIn("name 长度", joined)
        self.assertIn("description 长度", joined)
        self.assertIn("import_extensions 数量", joined)
        self.assertIn("label 长度", joined)
        self.assertIn("plugin_setting_limit", joined)

    def test_settings_max_32_and_extension_max_12_chars(self) -> None:
        res = scaffold_mod("limit-test", config=self.cfg)
        manifest = json.loads(res.manifest_path.read_text(encoding="utf-8"))
        manifest["settings"] = [
            {"id": f"opt_{i}", "type": "bool", "label": f"选项 {i}", "default": False} for i in range(33)
        ]
        manifest["import_extensions"] = ["toolongext123"]
        res.manifest_path.write_bytes(json.dumps(manifest, indent=2).encode("utf-8"))

        report = validate_mod_dir(res.target_dir, mod_name="limit-test")
        self.assertFalse(report.ok)
        joined = "\n".join(report.errors)
        self.assertIn("超过宿主上限 32", joined)
        self.assertIn("1..12 位", joined)

    def test_manifest_size_limit_128_kib_and_entry_subdirectory_support(self) -> None:
        res = scaffold_mod("subentry-mod", config=self.cfg)
        sub_entry = res.target_dir / "src" / "main_entry.gd"
        sub_entry.write_bytes(res.entry_path.read_bytes())
        manifest = json.loads(res.manifest_path.read_text(encoding="utf-8"))
        manifest["entry"] = "src/main_entry.gd"
        res.manifest_path.write_bytes(json.dumps(manifest, indent=2).encode("utf-8"))

        ok_report = validate_mod_dir(res.target_dir, mod_name="subentry-mod")
        self.assertTrue(ok_report.ok, msg=str(ok_report.errors))

        # Invalid entry characters rejected
        manifest["entry"] = "src/bad entry!.gd"
        res.manifest_path.write_bytes(json.dumps(manifest, indent=2).encode("utf-8"))
        bad_entry_report = validate_mod_dir(res.target_dir, mod_name="subentry-mod")
        self.assertFalse(bad_entry_report.ok)
        self.assertTrue(any("invalid_plugin_entry" in e for e in bad_entry_report.errors))

        # Oversized plugin.json (> 128 KiB) rejected
        manifest["entry"] = "src/main_entry.gd"
        manifest["extra_blob"] = "z" * (MAX_MANIFEST_BYTES + 1024)
        res.manifest_path.write_bytes(json.dumps(manifest).encode("utf-8"))
        big_report = validate_mod_dir(res.target_dir, mod_name="subentry-mod")
        self.assertFalse(big_report.ok)
        self.assertTrue(any("plugin_manifest_limit" in e for e in big_report.errors))

    def test_zip_archive_checks_case_collision_symlink_and_trailing_dot(self) -> None:
        bad_zip = self.case_dir / "bad_rules.zip"
        with zipfile.ZipFile(bad_zip, mode="w") as zf:
            zf.writestr("plugin.json", "{}")
            zf.writestr("Entry.gd", "extends RefCounted\n")
            zf.writestr("entry.gd", "extends RefCounted\n")
            zf.writestr("bad_dir./file.txt", "oops")
            link_info = zipfile.ZipInfo("link.gd")
            link_info.external_attr = (0o120777 << 16)
            zf.writestr(link_info, "entry.gd")

        errs = validate_zip_archive(bad_zip)
        joined = "\n".join(errs)
        self.assertIn("大小写冲突", joined)
        self.assertIn("zip_link_rejected", joined)
        self.assertIn("以 '.' 或空格结尾", joined)

    def test_detects_missing_or_commented_prepare_import(self) -> None:
        res = scaffold_mod("missing-hook", config=self.cfg)
        res.entry_path.write_bytes(
            (
                "extends RefCounted\n"
                "func inspect_import(path, options, host):\n"
                "\treturn {\"ok\": true}\n"
                "# func prepare_import(path, options, host):\n"
                "# \tpass\n"
            ).encode("utf-8")
        )
        report = validate_mod_dir(res.target_dir, mod_name="missing-hook")
        self.assertFalse(report.ok)
        self.assertTrue(any("prepare_import" in err for err in report.errors), msg=str(report.errors))

    def test_detects_dot_prefixed_extension_and_boolean_host_api(self) -> None:
        res = scaffold_mod("bad-ext", config=self.cfg)
        manifest = json.loads(res.manifest_path.read_text(encoding="utf-8"))
        manifest["host_api"] = True
        manifest["import_extensions"] = [".uvtt"]
        res.manifest_path.write_bytes(json.dumps(manifest, indent=2).encode("utf-8"))

        report = validate_mod_dir(res.target_dir, mod_name="bad-ext")
        self.assertFalse(report.ok)
        self.assertTrue(any("host_api" in err for err in report.errors))
        self.assertTrue(any("import_extensions" in err for err in report.errors))

    def test_validate_all_falls_back_to_template_when_empty(self) -> None:
        reports = validate_mods(self.cfg, select_all=True)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].mod_name, "_template")
        self.assertTrue(reports[0].ok)

    def test_validator_rejects_missing_refcounted_and_too_few_files(self) -> None:
        res = scaffold_mod("no-refcount", config=self.cfg)
        res.entry_path.write_bytes(
            b"extends Node\nfunc prepare_import(path, options, host):\n\treturn {}\n"
        )
        rep = validate_mod_dir(res.target_dir, mod_name="no-refcount")
        self.assertFalse(rep.ok)
        joined = "\n".join(rep.errors)
        self.assertIn("extends RefCounted", joined)
        self.assertIn("inspect_import", joined)

        # Single-file directory without SDK violates plugin_file_limit (< 2)
        solo_dir = self.ws_root / "mods" / "solo-file"
        solo_dir.mkdir(parents=True, exist_ok=True)
        (solo_dir / "plugin.json").write_bytes(res.manifest_path.read_bytes())
        solo_rep = validate_mod_dir(solo_dir, mod_name="solo-file", sdk_dir=None)
        self.assertFalse(solo_rep.ok)
        self.assertTrue(any("plugin_file_limit" in e for e in solo_rep.errors))


class PackagerTests(BaseDevtoolsTestCase):
    def test_deterministic_zip_sdk_bundling_file_hashes_and_bump_dev(self) -> None:
        res = scaffold_mod("uvtt-importer", config=self.cfg, import_extensions=["uvtt"])
        helper_gd = res.target_dir / "src" / "parser.gd"
        helper_gd.write_bytes(b"extends RefCounted\n")

        art1 = build_mod("uvtt-importer", config=self.cfg)
        bytes1 = art1.zip_path.read_bytes()

        future = time.time() + 120
        os.utime(res.entry_path, (future, future))
        art2 = build_mod("uvtt-importer", config=self.cfg)
        bytes2 = art2.zip_path.read_bytes()

        self.assertEqual(art1.sha256, art2.sha256)
        self.assertEqual(bytes1, bytes2)
        self.assertTrue(art1.sdk_bundled)

        bm = json.loads(art1.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(bm["schema"], "fus.session-plugin.v1")
        self.assertEqual(bm["host_api"], 1)
        self.assertEqual(bm["file_count"], len(art1.files))
        self.assertIn("file_hashes", bm)
        self.assertEqual(set(bm["file_hashes"].keys()), set(art1.files))
        for digest in bm["file_hashes"].values():
            self.assertRegex(digest, r"^[a-f0-9]{64}$")

        with zipfile.ZipFile(art1.zip_path, "r") as zf:
            names = zf.namelist()
            for name in names:
                self.assertNotIn("\\", name)
                self.assertFalse(name.startswith("/"))
            self.assertIn("plugin.json", names)
            self.assertIn("entry.gd", names)
            self.assertIn("src/parser.gd", names)
            self.assertIn("lib/fu_sdk/v1.gd", names)
            self.assertNotIn("AGENTS.md", names)
            self.assertNotIn("src/.gitkeep", names)

        art3 = build_mod("uvtt-importer", config=self.cfg, bump_dev=True)
        self.assertEqual(art3.version, "0.1.1")
        self.assertNotEqual(art3.sha256, art1.sha256)
        raw_manifest = (res.target_dir / "plugin.json").read_bytes()
        self.assertFalse(raw_manifest.startswith(UTF8_BOM))
        self.assertEqual(json.loads(raw_manifest.decode("utf-8"))["version"], "0.1.1")

        # Verify prerelease numeric patch bump
        self.assertEqual(bump_patch_version("0.2.3-beta.1+exp"), "0.2.4-beta.1+exp")

        # PackageError when validation fails
        (res.target_dir / "plugin.json").write_bytes(UTF8_BOM + raw_manifest)
        with self.assertRaises(PackageError):
            build_mod("uvtt-importer", config=self.cfg)

    def test_packager_no_sdk_mode_and_zip_min_entries_guard(self) -> None:
        scaffold_mod("lite-mod", config=self.cfg, import_extensions=["uvtt"])
        art = build_mod("lite-mod", config=self.cfg, no_sdk=True)
        self.assertFalse(art.sdk_bundled)
        self.assertEqual(art.files, ["entry.gd", "plugin.json"])

        one_entry_zip = self.case_dir / "one_entry.zip"
        with zipfile.ZipFile(one_entry_zip, mode="w") as zf:
            zf.writestr("plugin.json", "{}")
        errs = validate_zip_archive(one_entry_zip)
        self.assertTrue(any("plugin_file_limit" in e for e in errs))


class DeployerTests(BaseDevtoolsTestCase):
    def test_sync_writes_full_practice_registry_fields_and_reconciles_settings(self) -> None:
        res = scaffold_mod("map-pack", config=self.cfg, import_extensions=["dd2vtt"])
        target_sp = self.fake_steam_dir / "FUS_Data" / "session_plugins"

        target_sp.mkdir(parents=True, exist_ok=True)
        initial_registry = {
            "version": 1,
            "custom_top_flag": "keep_me",
            "playtest_fobr_offered": True,
            "plugins": {
                "fobr_world_import": {
                    "manifest": {"id": "fobr_world_import", "version": "0.5.1"},
                    "directory": "packages/fobr_world_import/abc",
                    "sha256": "a" * 64,
                    "enabled": True,
                }
            },
        }
        (target_sp / "registry.json").write_bytes(json.dumps(initial_registry, indent=2).encode("utf-8"))

        # First sync must write file_hashes, settings, source_url, installed_at
        sync1 = sync_mod("map-pack", config=self.cfg)
        self.assertTrue(sync1.rebuilt)
        self.assertGreaterEqual(sync1.file_hashes_count, 4)

        reg1 = json.loads((target_sp / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(reg1["custom_top_flag"], "keep_me")
        mp1 = reg1["plugins"]["map_pack"]
        self.assertEqual(mp1["directory"], f"packages/map_pack/{sync1.sha256}")
        self.assertTrue(mp1["enabled"])
        self.assertEqual(mp1["source_url"], "")
        self.assertTrue(mp1["installed_at"].endswith("Z"))
        self.assertEqual(mp1["settings"], {"proxy": "", "include_hidden": True})
        self.assertIn("plugin.json", mp1["file_hashes"])
        self.assertIn("entry.gd", mp1["file_hashes"])
        self.assertEqual(
            mp1["file_hashes"]["entry.gd"],
            hashlib.sha256((sync1.package_dir / "entry.gd").read_bytes()).hexdigest(),
        )

        # Simulate user saving custom settings, obsolete key, source_url, and disabling plugin
        mp1["settings"] = {
            "proxy": "http://127.0.0.1:7890",
            "include_hidden": False,
            "obsolete_old_key": "should_be_pruned",
        }
        mp1["source_url"] = "http://127.0.0.1:8765/map-pack.zip"
        mp1["enabled"] = False
        (target_sp / "registry.json").write_bytes(json.dumps(reg1, ensure_ascii=False, indent=2).encode("utf-8"))

        # Add a new setting to manifest, bump version, and sync again
        manifest = json.loads(res.manifest_path.read_text(encoding="utf-8"))
        manifest["settings"].append(
            {"id": "wall_width", "type": "string", "label": "墙体宽度", "default": "12"}
        )
        res.manifest_path.write_bytes(json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        art_v2 = build_mod("map-pack", config=self.cfg, bump_dev=True)
        sync2 = sync_mod("map-pack", config=self.cfg)
        self.assertEqual(sync2.version, "0.1.1")

        reg2_bytes = (target_sp / "registry.json").read_bytes()
        self.assertFalse(reg2_bytes.startswith(UTF8_BOM))
        reg2 = json.loads(reg2_bytes.decode("utf-8"))
        mp2 = reg2["plugins"]["map_pack"]
        self.assertEqual(mp2["sha256"], art_v2.sha256)
        self.assertEqual(
            mp2["settings"],
            {"proxy": "http://127.0.0.1:7890", "include_hidden": False, "wall_width": "12"},
        )
        self.assertEqual(mp2["source_url"], "http://127.0.0.1:8765/map-pack.zip")
        self.assertFalse(mp2["enabled"])
        self.assertIn("fobr_world_import", reg2["plugins"])

    def test_sync_blocks_downgrade_and_handles_same_version_conflict_flag(self) -> None:
        res = scaffold_mod("ver-guard", config=self.cfg, import_extensions=["uvtt"])
        # Set version to 0.2.0 and sync
        manifest = json.loads(res.manifest_path.read_text(encoding="utf-8"))
        manifest["version"] = "0.2.0"
        res.manifest_path.write_bytes(json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        sync1 = sync_mod("ver-guard", config=self.cfg)
        old_pkg_dir = sync1.package_dir
        self.assertTrue(old_pkg_dir.is_dir())

        # Attempt downgrade to 0.1.9 -> rejected with plugin_version_older
        manifest["version"] = "0.1.9"
        res.manifest_path.write_bytes(json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        build_mod("ver-guard", config=self.cfg)
        with self.assertRaises(DeployError) as cm_down:
            sync_mod("ver-guard", config=self.cfg)
        self.assertIn("plugin_version_older", str(cm_down.exception))

        # Restore 0.2.0 but change entry.gd -> same version different sha256 -> plugin_version_conflict
        manifest["version"] = "0.2.0"
        res.manifest_path.write_bytes(json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
        res.entry_path.write_bytes(res.entry_path.read_bytes() + b"\n# dev edit\n")
        build_mod("ver-guard", config=self.cfg)

        with self.assertRaises(DeployError) as cm_conf:
            sync_mod("ver-guard", config=self.cfg, allow_same_version=False)
        self.assertIn("plugin_version_conflict", str(cm_conf.exception))

        # With allow_same_version=True -> succeeds and removes obsolete old sha256 package dir
        sync2 = sync_mod("ver-guard", config=self.cfg, allow_same_version=True)
        self.assertNotEqual(sync2.sha256, sync1.sha256)
        self.assertTrue(sync2.package_dir.is_dir())
        self.assertFalse(old_pkg_dir.exists())
        self.assertEqual(sync2.cleaned_old_package_dir, old_pkg_dir.resolve())

    def test_build_reconciled_settings_rejects_oversized_string_back_to_default(self) -> None:
        manifest = {
            "settings": [
                {"id": "proxy", "type": "string", "label": "代理", "default": "http://default"},
                {"id": "flag", "type": "bool", "label": "开关", "default": True},
            ]
        }
        reconciled = build_reconciled_settings(
            manifest,
            {"proxy": "x" * 3000, "flag": "not_a_bool", "stale": 123},
        )
        self.assertEqual(reconciled, {"proxy": "http://default", "flag": True})

    def test_safe_extract_blocks_zip_traversal_symlink_and_serve_alias_routing(self) -> None:
        evil_zip = self.case_dir / "evil.zip"
        with zipfile.ZipFile(evil_zip, "w") as zf:
            zf.writestr("../escape.gd", "extends RefCounted\n")
        with self.assertRaises(DeployError):
            safe_extract_zip(evil_zip, self.case_dir / "extract_out")

        symlink_zip = self.case_dir / "symlink.zip"
        with zipfile.ZipFile(symlink_zip, "w") as zf:
            info = zipfile.ZipInfo("link.gd")
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, "target.gd")
        with self.assertRaises(DeployError):
            safe_extract_zip(symlink_zip, self.case_dir / "extract_symlink_out")

        scaffold_mod("my-cool-mod", config=self.cfg)
        art = build_mod("my-cool-mod", config=self.cfg)

        pkgs = discover_built_packages(self.cfg.build_dir)
        self.assertEqual(len(pkgs), 1)
        by_mod = resolve_hosted_zip("/my-cool-mod.zip?ts=123", self.cfg.build_dir)
        by_id = resolve_hosted_zip("/my_cool_mod.zip", self.cfg.build_dir)
        self.assertIsNotNone(by_mod)
        self.assertIsNotNone(by_id)
        self.assertEqual(by_mod.sha256, art.sha256)
        self.assertEqual(by_id.sha256, art.sha256)
        self.assertIsNone(resolve_hosted_zip("/../secret.zip", self.cfg.build_dir))

        banner = format_serve_banner(pkgs, "127.0.0.1", 8765)
        self.assertIn("http://127.0.0.1:8765/my-cool-mod.zip", banner)
        self.assertIn("http://127.0.0.1:8765/my_cool_mod.zip", banner)


class ClientInspectorTests(BaseDevtoolsTestCase):
    def _create_synthetic_git_repo(self, version: str = "0.0.56") -> Path:
        repo = self.fake_fus_repo
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "TestBot"], check=True)

        (repo / "project.godot").write_bytes(
            f'[application]\nconfig/name="FuVTT"\nconfig/version="{version}"\n'.encode("utf-8")
        )
        (repo / "Practice.csproj").write_bytes(b"<Project Sdk=\"Godot.NET.Sdk/4.8.0-beta.1\"/>\n")
        (repo / "services" / "plugins").mkdir(parents=True, exist_ok=True)
        (repo / "services" / "plugins" / "PluginPackageJob.cs").write_bytes(b"// v1\n")
        (repo / "services" / "plugins" / "session_plugins.gd").write_bytes(b"extends Node\n")
        (repo / "plugin_packages" / "fobr_world_import").mkdir(parents=True, exist_ok=True)
        (repo / "plugin_packages" / "fobr_world_import" / "plugin.json").write_bytes(
            json.dumps(
                {
                    "schema": "fus.session-plugin.v1",
                    "host_api": 1,
                    "scope": "session",
                    "id": "fobr_world_import",
                    "version": "0.5.1",
                }
            ).encode("utf-8")
        )
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "initial"], check=True)
        return repo

    def test_synthetic_embedded_pck_external_files_and_snapshot_diff(self) -> None:
        pck_files: dict[str, bytes] = {
            "res://data/build_identity.json": json.dumps(
                {"version": "v0.0.56", "commit": "80c36de", "build-date": "2026-11-19", "dirty": "false"}
            ).encode("utf-8"),
            "res://plugin_packages/fobr-world-import.zip": _make_mock_fobr_zip(host_api=1),
        }
        for idx, rel_path in enumerate(CONTRACT_WATCH_FILES):
            pck_files[f"res://{rel_path}"] = f"GDC_BYTECODE_V1_{idx}".encode("utf-8")

        fake_exe = self.fake_steam_dir / "FUS.exe"
        fake_exe.parent.mkdir(parents=True, exist_ok=True)
        fake_exe.write_bytes(build_synthetic_embedded_pck_exe(pck_files, engine_version=(4, 8, 0)))

        # Seed external Practice.dll & FUS_Data/.fus-storage.json
        dll_path = self.fake_steam_dir / Path(*STEAM_EXTERNAL_PRACTICE_DLL_REL.split("/"))
        dll_path.parent.mkdir(parents=True, exist_ok=True)
        dll_path.write_bytes(b"FAKE_PRACTICE_DLL_V1")
        storage_path = self.fake_steam_dir / Path(*STEAM_EXTERNAL_STORAGE_JSON_REL.split("/"))
        storage_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.write_bytes(json.dumps({"format": "fus.practice.data/1", "profile_schema": 1}).encode("utf-8"))

        parsed = parse_embedded_pck(fake_exe)
        self.assertEqual(parsed.pack_format, 4)
        self.assertEqual(len(parsed.entries), len(pck_files))

        res1 = inspect_client(self.cfg, extract=True, source="steam")
        self.assertEqual(res1.extracted_files_count, len(pck_files))
        self.assertFalse(res1.diff.has_previous)
        self.assertTrue(res1.snapshot["external_files"][STEAM_EXTERNAL_PRACTICE_DLL_REL]["exists"])
        self.assertEqual(
            res1.snapshot["external_files"][STEAM_EXTERNAL_STORAGE_JSON_REL]["format"],
            "fus.practice.data/1",
        )
        self.assertNotIn("FakeSteam", json.dumps(res1.snapshot))

        res2 = inspect_client(self.cfg, extract=False, source="steam")
        self.assertTrue(res2.diff.is_clean)

        # Modify Practice.dll & import_bridge.gdc -> drift detected
        dll_path.write_bytes(b"FAKE_PRACTICE_DLL_V2_UPDATED")
        pck_files["res://data/build_identity.json"] = json.dumps(
            {"version": "v0.0.57", "commit": "3f20e8e", "build-date": "2026-11-20", "dirty": "false"}
        ).encode("utf-8")
        pck_files["res://scenes/session/plugins/import_bridge.gdc"] = b"GDC_BYTECODE_V2_MODIFIED"
        fake_exe.write_bytes(build_synthetic_embedded_pck_exe(pck_files, engine_version=(4, 8, 0)))

        res3 = inspect_client(self.cfg, extract=True, source="steam")
        self.assertFalse(res3.diff.is_clean)
        self.assertEqual(res3.diff.client_version_change, {"from": "v0.0.56", "to": "v0.0.57"})
        self.assertEqual([c["path"] for c in res3.diff.changed_contract_files], ["scenes/session/plugins/import_bridge.gdc"])
        self.assertEqual([c["path"] for c in res3.diff.changed_external_files], [STEAM_EXTERNAL_PRACTICE_DLL_REL])

    def test_dual_source_steam_plus_git_inspection_and_diff(self) -> None:
        repo = self._create_synthetic_git_repo(version="0.0.56")
        pck_files: dict[str, bytes] = {
            "res://data/build_identity.json": json.dumps(
                {"version": "v0.0.57", "commit": "3f20e8e", "build-date": "2026-11-20", "dirty": "false"}
            ).encode("utf-8"),
            "res://plugin_packages/fobr-world-import.zip": _make_mock_fobr_zip(host_api=1),
        }
        for idx, rel_path in enumerate(CONTRACT_WATCH_FILES):
            pck_files[f"res://{rel_path}"] = f"GDC_{idx}".encode("utf-8")

        fake_exe = self.fake_steam_dir / "FUS.exe"
        fake_exe.parent.mkdir(parents=True, exist_ok=True)
        fake_exe.write_bytes(build_synthetic_embedded_pck_exe(pck_files))

        dual_cfg = load_config(
            self.ws_root,
            env_file=self.env_file,
            environ={"FUS_REPO_DIR": str(repo), "FUS_SOURCE_REF": "HEAD"},
        )
        res1 = inspect_client(dual_cfg, extract=True, source="both")
        self.assertEqual(res1.snapshot["git_source"]["version"], "v0.0.56")
        self.assertEqual(res1.snapshot["git_source"]["repo"], "<FUS_REPO_DIR>")
        report_txt = format_inspection_report(res1, dual_cfg)
        self.assertIn("版本代差对照: Steam 线上包 v0.0.57 (3f20e8e) vs Git HEAD v0.0.56", report_txt)
        self.assertNotIn("FakeFusRepo", report_txt)

        # Commit a change to PluginPackageJob.cs in synthetic git repo -> drift detected on 2nd run
        (repo / "services" / "plugins" / "PluginPackageJob.cs").write_bytes(b"// v2 contract change\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "update job"], check=True)

        res2 = inspect_client(dual_cfg, extract=False, source="both")
        self.assertFalse(res2.diff.is_clean)
        self.assertEqual(
            [c["path"] for c in res2.diff.changed_git_files],
            ["services/plugins/PluginPackageJob.cs"],
        )

    def test_git_only_source_inspection_and_report_formatting(self) -> None:
        repo = self._create_synthetic_git_repo(version="0.0.56")
        git_cfg = load_config(
            self.ws_root,
            env_file=self.ws_root / "missing.env",
            environ={"FUS_REPO_DIR": str(repo), "FUS_SOURCE_REF": "HEAD"},
        )
        res = inspect_client(git_cfg, source="git")
        self.assertEqual(res.snapshot["inspect_mode"], "git")
        self.assertEqual(res.snapshot["git_source"]["version"], "v0.0.56")
        self.assertTrue(res.snapshot["git_source"]["watch_files"]["services/plugins/PluginPackageJob.cs"]["exists"])
        text = format_inspection_report(res, git_cfg)
        self.assertIn("巡检模式: git", text)
        self.assertIn("services/plugins/PluginPackageJob.cs", text)

    def test_real_workspace_extracted_pck_if_present(self) -> None:
        real_extracted = WORKSPACE_ROOT / "build" / "extracted_pck"
        if not real_extracted.is_dir():
            self.skipTest("Workspace build/extracted_pck not present")

        temp_snap = self.cfg.cache_dir / "real_pck_snapshot.json"
        res = inspect_client(
            self.cfg,
            extract=False,
            extracted_dir=real_extracted,
            snapshot_path=temp_snap,
            source="steam",
        )
        ver = res.snapshot["build_identity"]["version"]
        self.assertRegex(ver, r"^v\d+\.\d+\.\d+")
        self.assertEqual(res.snapshot["builtin_plugin"]["manifest"]["schema"], "fus.session-plugin.v1")
        self.assertEqual(res.snapshot["builtin_plugin"]["manifest"]["host_api"], 1)
        for rel_path in CONTRACT_WATCH_FILES:
            self.assertTrue(
                res.snapshot["contract_files"][rel_path]["exists"],
                msg=f"Expected contract file {rel_path} to exist in build/extracted_pck",
            )


class HostVerifierTests(BaseDevtoolsTestCase):
    def test_analyze_godot_logs_detects_script_errors_and_leaks(self) -> None:
        clean_log = (
            "Godot Engine v4.8.beta1.mono\n"
            "ERROR: .NET: Assemblies not found\n"
            "   at: initialize (modules/mono/mono_gd/gd_mono.cpp:650)\n"
            "FUVTT_VERIFY_HOST PASS checks=18 scripts=3\n"
        )
        self.assertEqual(analyze_godot_logs(clean_log), [])

        dirty_log = (
            "SCRIPT ERROR: Parse Error: Unexpected token\n"
            "ERROR: Failed loading resource: res://pkg/entry.gd\n"
            "WARNING: 2 ObjectDB instances leaked at exit\n"
        )
        findings = analyze_godot_logs(dirty_log)
        self.assertEqual(len(findings), 3)

    def test_analyze_godot_logs_catches_fatal_and_unicode_parse_error(self) -> None:
        findings = analyze_godot_logs(
            "FATAL: Assertion failed\n"
            "Unicode parsing error, some characters were replaced\n"
            "WARNING: 1 resources still in use at exit\n"
        )
        self.assertEqual(len(findings), 3)

    def test_prepare_probe_workspace_and_mock_runner_pass_and_fail(self) -> None:
        scaffold_mod("probe-demo", config=self.cfg, import_extensions=["uvtt"])
        art = build_mod("probe-demo", config=self.cfg)
        ev_dir = self.cfg.build_dir / "probe-demo" / "verify_evidence" / "unit_test_prep"
        paths = prepare_probe_workspace(
            zip_path=art.zip_path,
            plugin_manifest=art.plugin_manifest,
            evidence_dir=ev_dir,
        )
        self.assertTrue((paths["probe_project"] / "project.godot").is_file())
        self.assertTrue((paths["probe_project"] / "headless_probe.gd").is_file())
        self.assertTrue((paths["pkg_dir"] / "plugin.json").is_file())
        self.assertTrue((paths["pkg_dir"] / "lib" / "fu_sdk" / "v1.gd").is_file())
        self.assertTrue(paths["sample"].is_file())
        self.assertTrue(paths["sample"].name.endswith(".uvtt"))

        verify_cfg = load_config(
            self.ws_root,
            env_file=self.env_file,
            environ={"GODOT_BIN": str(self.fake_godot_bin)},
        )

        # Simulated PASS runner
        def _pass_runner(cmd, *, cwd, env, timeout_seconds):
            self.assertIn("--headless", cmd)
            self.assertIn("isolated_env", env["APPDATA"])
            self.assertEqual(env["GODOT_SILENCE_ROOT_WARNING"], "1")
            report_arg = [a for a in cmd if a.startswith("--report=")][0].split("=", 1)[1]
            Path(report_arg).write_text(
                json.dumps(
                    {
                        "ok": True,
                        "passed_checks": 24,
                        "failures": [],
                        "loaded_scripts": ["res://pkg/entry.gd", "res://pkg/lib/fu_sdk/v1.gd"],
                        "warnings": [],
                        "entity_count": 2,
                        "serialized_bytes": 512,
                    }
                ),
                encoding="utf-8",
            )
            return 0, "FUVTT_VERIFY_HOST PASS checks=24\n", "", False

        pass_res = verify_mod_with_host("probe-demo", config=verify_cfg, runner=_pass_runner)
        self.assertTrue(pass_res.ok)
        self.assertEqual(pass_res.passed_checks, 24)
        self.assertEqual(pass_res.entity_count, 2)
        self.assertEqual(pass_res.serialized_bytes, 512)

        # Simulated FAIL runner with SCRIPT ERROR in stderr even if report says ok
        def _dirty_log_runner(cmd, *, cwd, env, timeout_seconds):
            report_arg = [a for a in cmd if a.startswith("--report=")][0].split("=", 1)[1]
            Path(report_arg).write_text(json.dumps({"ok": True, "passed_checks": 10, "failures": []}), encoding="utf-8")
            return 0, "", "SCRIPT ERROR: simulated compile error\n", False

        fail_res = verify_mod_with_host("probe-demo", config=verify_cfg, runner=_dirty_log_runner)
        self.assertFalse(fail_res.ok)
        self.assertEqual(len(fail_res.log_errors), 1)

    def test_real_godot_verify_host_on_workspace_template_if_available(self) -> None:
        real_cfg = load_config(WORKSPACE_ROOT)
        if real_cfg.godot_bin is None or not real_cfg.godot_bin.is_file():
            self.skipTest("GODOT_BIN not configured or unavailable in this environment")
        try:
            probe_ver = subprocess.run(
                [str(real_cfg.godot_bin), "--headless", "--quit", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            self.skipTest("GODOT_BIN cannot be executed inside current sandbox")
        if probe_ver.returncode != 0:
            self.skipTest(f"GODOT_BIN --version returned {probe_ver.returncode}")

        # Run verify-host in an isolated temporary build_dir so we don't leave test debris in build/_template
        iso_cfg = WorkspaceConfig(
            workspace_root=WORKSPACE_ROOT.resolve(),
            mods_dir=WORKSPACE_ROOT / "mods",
            sdk_dir=WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk",
            build_dir=(self.case_dir / "iso_build").resolve(),
            cache_dir=(self.case_dir / "iso_cache").resolve(),
            fuvtt_install_dir=real_cfg.fuvtt_install_dir,
            fus_repo_dir=real_cfg.fus_repo_dir,
            fus_source_ref=real_cfg.fus_source_ref,
            godot_bin=real_cfg.godot_bin,
        )
        res = verify_mod_with_host("_template", config=iso_cfg)
        self.assertTrue(
            res.ok,
            msg=f"Real Godot verify-host failed: failures={res.failures}, log_errors={res.log_errors}",
        )
        self.assertGreaterEqual(len(res.loaded_scripts), 3)
        self.assertGreater(res.serialized_bytes, 0)

    def test_real_godot_verify_host_exercises_upgraded_fu_sdk_v1_1_features(self) -> None:
        real_cfg = load_config(WORKSPACE_ROOT)
        if real_cfg.godot_bin is None or not real_cfg.godot_bin.is_file():
            self.skipTest("GODOT_BIN not configured or unavailable in this environment")
        try:
            probe_ver = subprocess.run(
                [str(real_cfg.godot_bin), "--headless", "--quit", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            self.skipTest("GODOT_BIN cannot be executed inside current sandbox")
        if probe_ver.returncode != 0:
            self.skipTest(f"GODOT_BIN --version returned {probe_ver.returncode}")

        # Build a temporary high-level SDK stress plugin inside isolated case_dir (never touching workspace mods/)
        iso_mods = self.case_dir / "iso_mods"
        iso_mod_dir = iso_mods / "sdk-stress"
        iso_mod_dir.mkdir(parents=True, exist_ok=True)
        stress_manifest = {
            "schema": "fus.session-plugin.v1",
            "host_api": 1,
            "scope": "session",
            "id": "sdk_stress",
            "version": "0.1.0",
            "name": "SDK Stress",
            "description": "Tests multi-floor, 5 obstacle kinds with holes, degenerate ring, and component attachment.",
            "entry": "entry.gd",
            "import_extensions": ["fusstress"],
            "settings": [],
        }
        (iso_mod_dir / "plugin.json").write_bytes(
            (json.dumps(stress_manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        )
        stress_entry = """extends RefCounted

const _SDK_PACKAGED_REL_PATH: String = "lib/fu_sdk/v1.gd"

func _create_sdk() -> RefCounted:
\tvar self_script := get_script() as Script
\tvar sdk_script: Script = load(self_script.resource_path.get_base_dir().path_join(_SDK_PACKAGED_REL_PATH)) as Script
\treturn sdk_script.new() if sdk_script != null else null

func inspect_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:
\tvar sdk := _create_sdk()
\tvar session = sdk.create_session(host, options)
\treturn session.ok_inspect(path, {"records": 8, "unsupported": 0}, {})

func prepare_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:
\tvar sdk := _create_sdk()
\tvar session = sdk.create_session(host, options)
\tvar builder = sdk.create_world_builder(session, 150.0)
\tvar init_res: Dictionary = builder.setup(session, 150.0)
\tif not bool(init_res.get("ok", false)):
\t\treturn init_res
\tvar f2_uid: String = builder.add_floor("2F", Color(0.3, 0.5, 0.7), true)
\tif not f2_uid.is_empty():
\t\tbuilder.set_active_floor(f2_uid)
\tbuilder.add_layer("触发区", "area")
\tvar outer := [Vector2(-100, -100), Vector2(100, -100), Vector2(100, 100), Vector2(-100, 100)]
\tvar hole := [Vector2(-30, -30), Vector2(30, -30), Vector2(30, 30), Vector2(-30, 30)]
\tvar degen := [Vector2(0, 0), Vector2(10, 0)]
\tbuilder.add_wall("w1", "带孔墙", Vector2(0, 0), [{"outer": outer, "holes": [hole]}, degen])
\tbuilder.add_air_cutout("a1", "挑空", Vector2(200, 0), [outer])
\tbuilder.add_door("d1", "木门", Vector2(300, 0), [outer], false)
\tbuilder.add_window("win1", "窗户", Vector2(400, 0), [outer])
\tbuilder.add_glass_wall("g1", "玻璃幕墙", Vector2(500, 0), [outer])
\tbuilder.add_text_pin("tp1", "大厅说明", Vector2(100, 100), "主厅备注")
\tvar tok_id: String = builder.add_token("hero1", "勇者", Vector2(50, 50), Vector2(64, 64), "user://bad.png", 0.0, Vector2.ONE, false)
\tbuilder.attach_simple_vision(tok_id, 300.0)
\tbuilder.set_module_state("custom_test", 1, {"enabled": true})
\tbuilder.finish_geometry_preview()
\treturn builder.build_result(8, 1)
"""
        (iso_mod_dir / "entry.gd").write_bytes(stress_entry.encode("utf-8"))

        iso_cfg = WorkspaceConfig(
            workspace_root=WORKSPACE_ROOT.resolve(),
            mods_dir=iso_mods,
            sdk_dir=WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk",
            build_dir=(self.case_dir / "iso_stress_build").resolve(),
            cache_dir=(self.case_dir / "iso_stress_cache").resolve(),
            fuvtt_install_dir=real_cfg.fuvtt_install_dir,
            fus_repo_dir=real_cfg.fus_repo_dir,
            fus_source_ref=real_cfg.fus_source_ref,
            godot_bin=real_cfg.godot_bin,
        )
        res = verify_mod_with_host("sdk-stress", config=iso_cfg)
        self.assertTrue(
            res.ok,
            msg=f"SDK v1.1 stress verify-host failed: failures={res.failures}, log_errors={res.log_errors}",
        )
        self.assertEqual(res.entity_count, 7)
        self.assertGreaterEqual(len(res.warnings), 2)
        self.assertGreater(res.serialized_bytes, 0)


class CliEntrypointTests(BaseDevtoolsTestCase):
    def test_cli_end_to_end_workflow(self) -> None:
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            self.assertEqual(
                fuvtt_cli.main(["init", "cli-demo", "--name", "CLI 示例", "--ext", "uvtt"], config=self.cfg),
                0,
            )
            self.assertEqual(fuvtt_cli.main(["validate", "cli-demo"], config=self.cfg), 0)
            self.assertEqual(fuvtt_cli.main(["build", "cli-demo"], config=self.cfg), 0)
            self.assertEqual(fuvtt_cli.main(["sync", "cli-demo", "--dry-run"], config=self.cfg), 0)
            self.assertEqual(fuvtt_cli.main(["sync", "cli-demo"], config=self.cfg), 0)
            # Re-sync same version with modified script using --allow-same-version
            entry_p = self.ws_root / "mods" / "cli-demo" / "entry.gd"
            entry_p.write_bytes(entry_p.read_bytes() + b"\n# update\n")
            self.assertEqual(fuvtt_cli.main(["build", "cli-demo"], config=self.cfg), 0)
            self.assertEqual(
                fuvtt_cli.main(["sync", "cli-demo", "--allow-same-version"], config=self.cfg),
                0,
            )
        out = captured.getvalue()
        self.assertIn("<FUVTT_INSTALL_DIR>", out)
        self.assertNotIn("FakeSteam", out)
        self.assertIn("file_hashes=", out)


if __name__ == "__main__":
    unittest.main()
