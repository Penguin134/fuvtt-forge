"""Unit and headless Godot integration tests for M2 Dual-Mode CLI & Devtools (`fus.desktop-module.v1` & `fus.plugin.v2`)."""

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
import threading
import time
import unittest
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen
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
    GIT_PRACTICE_WATCH_FILES,
    V065_CONTRACT_WATCH_FILES,
    inspect_client,
)
from fuvtt_devtools.deployer import (  # noqa: E402
    DeployError,
    create_dev_http_server,
    discover_built_packages,
    format_serve_banner,
    resolve_hosted_package,
    resolve_hosted_zip,
    safe_extract_zip,
    sync_mod,
)
from fuvtt_devtools.env_config import (  # noqa: E402
    DEFAULT_FUS_SOURCE_REF,
    WorkspaceConfig,
    load_config,
)
from fuvtt_devtools.host_verifier import _INWORLD_HOST_SHIMS, verify_mod_with_host  # noqa: E402
from fuvtt_devtools.packager import PackageError, _extract_pack_file, build_mod  # noqa: E402
from fuvtt_devtools.scaffold import ScaffoldError, scaffold_mod  # noqa: E402
from fuvtt_devtools.validator import (  # noqa: E402
    CANONICAL_RUNTIME_FU_SDK_SCRIPTS,
    resolve_runtime_sdk_bundle,
    resolve_target_mods,
    validate_fup_archive,
    validate_mod_dir,
    validate_zip_archive,
)


def _write_utf8(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.lstrip("\ufeff").replace("\r\n", "\n").encode("utf-8"))


class BaseInWorldDevtoolsTestCase(unittest.TestCase):
    """Isolated mock workspace inside `.cache/test_tmp/<uuid>/` with mock `fu_sdk` & `fu_runtime`."""

    def setUp(self) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.case_dir = TEST_TMP_ROOT / f"inworld_{uuid.uuid4().hex[:10]}"
        self.ws_root = self.case_dir / "mock_ws"
        self.fake_steam_dir = self.case_dir / "FakeSteam" / "Fu vtt"
        self.fake_godot_bin = self.case_dir / "FakeGodot" / "Godot_console.exe"
        self.fake_godot_bin.parent.mkdir(parents=True, exist_ok=True)
        self.fake_godot_bin.write_bytes(b"FAKE_GODOT_BIN")

        # v1 _template
        tpl_dir = self.ws_root / "mods" / "_template"
        (tpl_dir / "src").mkdir(parents=True, exist_ok=True)
        _write_utf8(
            tpl_dir / "plugin.json",
            json.dumps(
                {
                    "schema": "fus.session-plugin.v1",
                    "host_api": 1,
                    "scope": "session",
                    "id": "template_mod",
                    "version": "0.1.0",
                    "name": "Template Mod",
                    "entry": "entry.gd",
                    "import_extensions": ["fusdemo"],
                    "settings": [],
                },
                indent=2,
            )
            + "\n",
        )
        _write_utf8(
            tpl_dir / "entry.gd",
            "extends RefCounted\nfunc inspect_import(_p, _o, _h):\n\treturn {\"ok\": true}\n"
            "func prepare_import(_p, _o, _h):\n\treturn {\"ok\": true}\n",
        )

        # Mock shared/sdk/fu_sdk/ with the 6 canonical scripts + v1.gd
        self.sdk_dir = self.ws_root / "shared" / "sdk" / "fu_sdk"
        _write_utf8(self.sdk_dir / "v1.gd", 'extends RefCounted\nconst SDK_VERSION := "1.3.0"\n')
        for rel in CANONICAL_RUNTIME_FU_SDK_SCRIPTS:
            _write_utf8(
                self.sdk_dir / Path(*rel.split("/")),
                f'extends RefCounted\nconst REL_ID := "{rel}"\n',
            )

        # Mock shared/sdk/fu_runtime/ with runtime_manifest.json
        self.runtime_sdk_dir = self.ws_root / "shared" / "sdk" / "fu_runtime"
        _write_utf8(
            self.runtime_sdk_dir / "v2.gd",
            'extends RefCounted\nconst SDK_VERSION := "2.0.0-test"\n',
        )
        _write_utf8(
            self.runtime_sdk_dir / "desktop_api_helper.gd",
            "extends RefCounted\n",
        )
        _write_utf8(
            self.runtime_sdk_dir / "runtime_manifest.json",
            json.dumps(
                {
                    "runtime_scripts": ["v2.gd", "desktop_api_helper.gd"],
                    "shared_fu_sdk_scripts": list(CANONICAL_RUNTIME_FU_SDK_SCRIPTS),
                },
                indent=2,
            )
            + "\n",
        )

        self.env_file = self.ws_root / ".env.local"
        _write_utf8(
            self.env_file,
            f'FUVTT_INSTALL_DIR="{self.fake_steam_dir.as_posix()}"\n'
            f'GODOT_BIN="{self.fake_godot_bin.as_posix()}"\n'
            "BUILD_DIR=build\n"
            "CACHE_DIR=.cache\n",
        )
        self.cfg = load_config(self.ws_root, env_file=self.env_file, environ={})

    def tearDown(self) -> None:
        if self.case_dir.exists():
            shutil.rmtree(self.case_dir, ignore_errors=True)


def _create_fake_pck(output_pck: Path, entries: list[tuple[str, Path]]) -> None:
    """Create a valid GDPC-header standalone PCK payload for mock packager tests."""
    output_pck.parent.mkdir(parents=True, exist_ok=True)
    header = bytearray(112)
    header[0:4] = b"GDPC"
    header[4:8] = (4).to_bytes(4, "little")
    payload = b"".join(f"{rel}:{p.stat().st_size}\n".encode("utf-8") for rel, p in entries)
    output_pck.write_bytes(bytes(header) + payload)


class EnvConfigAndInspectorInWorldTests(BaseInWorldDevtoolsTestCase):
    def test_default_fus_source_ref_and_env_example_hygiene(self) -> None:
        self.assertEqual(DEFAULT_FUS_SOURCE_REF, "origin/codex/v065-unified-20261125")
        env_example = (WORKSPACE_ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("FUS_SOURCE_REF=origin/codex/v065-unified-20261125", env_example)
        self.assertIn("FUVTT_INSTALL_DIR=\n", env_example.replace("\r\n", "\n"))
        self.assertIn("FUS_REPO_DIR=\n", env_example.replace("\r\n", "\n"))
        self.assertIn("GODOT_BIN=\n", env_example.replace("\r\n", "\n"))
        self.assertNotRegex(env_example, r"(?i)[a-z]:\\")
        self.assertNotIn("/Users/", env_example)

    def test_workspace_config_backward_compat_without_runtime_sdk_dir(self) -> None:
        cfg_legacy = WorkspaceConfig(
            workspace_root=self.ws_root,
            mods_dir=self.ws_root / "mods",
            sdk_dir=self.sdk_dir,
            build_dir=self.ws_root / "build",
            cache_dir=self.ws_root / ".cache",
        )
        self.assertIsNone(cfg_legacy.runtime_sdk_dir)
        self.assertEqual(cfg_legacy.resolved_runtime_sdk_dir, self.ws_root / "shared" / "sdk" / "fu_runtime")

    def test_v065_watchlists_and_synthetic_git_drift(self) -> None:
        self.assertEqual(len(CONTRACT_WATCH_FILES), len(set(CONTRACT_WATCH_FILES)))
        self.assertEqual(len(V065_CONTRACT_WATCH_FILES), len(set(V065_CONTRACT_WATCH_FILES)))
        self.assertEqual(len(GIT_PRACTICE_WATCH_FILES), len(set(GIT_PRACTICE_WATCH_FILES)))
        for req in (
            "scenes/extension/extension_base.gd",
            "scenes/extension/extension_context.gd",
            "scenes/extension/desktop_api_service.gd",
            "scenes/entities/components/comp_base.gd",
            "scenes/desktop/entities/entity_component_page.gd",
            "services/plugins/PluginPackageJob.cs",
            "tools/build_world_plugin.gd",
            "tests/check_world_module_plugin_v2.gd",
        ):
            self.assertIn(req, GIT_PRACTICE_WATCH_FILES)

        repo = self.case_dir / "SyntheticFusRepo"
        repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
        _write_utf8(repo / "project.godot", 'config/version="0.0.65"\n')
        _write_utf8(repo / "tools" / "build_world_plugin.gd", "extends SceneTree\n# v1\n")
        _write_utf8(repo / "scenes" / "extension" / "desktop_api_service.gd", "extends RefCounted\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "v065"], check=True)

        snap_path = self.cfg.cache_dir / "snap.json"
        git_cfg = WorkspaceConfig(
            workspace_root=self.ws_root,
            mods_dir=self.ws_root / "mods",
            sdk_dir=self.sdk_dir,
            build_dir=self.cfg.build_dir,
            cache_dir=self.cfg.cache_dir,
            fus_repo_dir=repo,
            fus_source_ref="HEAD",
        )
        r1 = inspect_client(git_cfg, source="git", snapshot_path=snap_path)
        self.assertTrue(r1.snapshot["git_source"]["watch_files"]["tools/build_world_plugin.gd"]["exists"])
        self.assertTrue(r1.snapshot["git_source"]["watch_files"]["scenes/extension/desktop_api_service.gd"]["exists"])

        _write_utf8(repo / "tools" / "build_world_plugin.gd", "extends SceneTree\n# v2\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "change packager"], check=True)

        r2 = inspect_client(git_cfg, source="git", snapshot_path=snap_path)
        self.assertFalse(r2.diff.is_clean)
        changed = {item["path"] for item in r2.diff.changed_git_files}
        self.assertIn("tools/build_world_plugin.gd", changed)


class ScaffoldAndValidatorInWorldTests(BaseInWorldDevtoolsTestCase):
    def test_scaffold_all_three_modes_and_cli_init(self) -> None:
        # Default session-plugin
        v1 = scaffold_mod("v1-importer", config=self.cfg)
        self.assertEqual(v1.schema, "fus.session-plugin.v1")
        self.assertEqual(json.loads(v1.manifest_path.read_text(encoding="utf-8"))["schema"], "fus.session-plugin.v1")

        # Desktop module via CLI
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fuvtt_cli.main(
                ["init", "crit-fx", "--mode", "desktop-module", "--name", "Crit FX"],
                config=self.cfg,
            )
        self.assertEqual(rc, 0)
        crit_manifest = json.loads((self.ws_root / "mods" / "crit-fx" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(crit_manifest["schema"], "fus.desktop-module.v1")
        self.assertEqual(crit_manifest["modules"][0]["entry_scene"], "res://mods/crit_fx/module.tscn")
        self.assertTrue(crit_manifest["modules"][0]["local_only"])
        self.assertEqual(crit_manifest["modules"][0]["network_version"], 0)
        self.assertNotIn("class_name", (self.ws_root / "mods" / "crit-fx" / "mods" / "crit_fx" / "module.gd").read_text(encoding="utf-8"))

        # World plugin v2
        v2 = scaffold_mod("aura-test", config=self.cfg, mode="world-plugin")
        self.assertEqual(v2.schema, "fus.plugin.v2")
        v2_manifest = json.loads(v2.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(v2_manifest["pack_file"], "content.pck")
        self.assertEqual(v2_manifest["modules"][0]["entry_scene"], "res://external_modules/aura_test/feature_aura_test.tscn")
        self.assertFalse(v2_manifest["modules"][0]["local_only"])
        self.assertEqual(v2_manifest["modules"][0]["network_version"], 1)

        # Reject template names and conflicting mode/schema
        for reserved in ("_template", "_template-desktop-module", "_template-world-plugin"):
            with self.assertRaises(ScaffoldError):
                scaffold_mod(reserved, config=self.cfg)
        with self.assertRaises(ScaffoldError):
            scaffold_mod("bad-combo", config=self.cfg, mode="desktop-module", schema="fus.plugin.v2")

        # Validate both generated in-world mods
        rep_d = validate_mod_dir(
            self.ws_root / "mods" / "crit-fx",
            sdk_dir=self.sdk_dir,
            runtime_sdk_dir=self.runtime_sdk_dir,
        )
        self.assertTrue(rep_d.ok, msg=f"desktop-module errors: {rep_d.errors}")
        rep_w = validate_mod_dir(
            self.ws_root / "mods" / "aura-test",
            sdk_dir=self.sdk_dir,
            runtime_sdk_dir=self.runtime_sdk_dir,
        )
        self.assertTrue(rep_w.ok, msg=f"world-plugin errors: {rep_w.errors}")

    def test_scaffold_copies_inworld_template_dir_if_present(self) -> None:
        tpl = self.ws_root / "mods" / "_template-desktop-module"
        _write_utf8(
            tpl / "plugin.json",
            json.dumps(
                {
                    "schema": "fus.desktop-module.v1",
                    "host_api": 2,
                    "scope": "desktop",
                    "id": "template_desktop_module",
                    "version": "0.1.0",
                    "name": "Template Desktop",
                    "modules": [
                        {
                            "id": "mod.template_desktop_module",
                            "display_name": "Template Desktop",
                            "entry_scene": "res://mods/template_desktop_module/module.tscn",
                            "version": 1,
                            "network_version": 0,
                            "local_only": True,
                        }
                    ],
                    "settings": [],
                }
            )
            + "\n",
        )
        _write_utf8(
            tpl / "mods" / "template_desktop_module" / "module.tscn",
            '[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://mods/template_desktop_module/module.gd" id="1"]\n[node name="Root" type="Node2D"]\nscript = ExtResource("1")\n',
        )
        _write_utf8(tpl / "mods" / "template_desktop_module" / "module.gd", "extends ExtensionBase\n# from tpl\n")
        res = scaffold_mod("custom-fx", config=self.cfg, mode="desktop-module")
        self.assertIn("# from tpl", (res.target_dir / "mods" / "custom_fx" / "module.gd").read_text(encoding="utf-8"))
        self.assertIn("res://mods/custom_fx/module.gd", res.entry_scene_path.read_text(encoding="utf-8"))

    def test_scaffold_remaps_world_plugin_component_filenames(self) -> None:
        tpl = self.ws_root / "mods" / "_template-world-plugin"
        _write_utf8(
            tpl / "plugin.json",
            json.dumps(
                {
                    "schema": "fus.plugin.v2",
                    "host_api": 2,
                    "scope": "world",
                    "id": "template_world_plugin",
                    "version": "0.1.0",
                    "name": "Template World",
                    "pack_file": "content.pck",
                    "modules": [
                        {
                            "id": "template_world_plugin.core",
                            "display_name": "Template World",
                            "entry_scene": "res://external_modules/template_world_plugin/feature_template_world_plugin.tscn",
                            "version": 1,
                            "network_version": 1,
                            "local_only": False,
                        }
                    ],
                    "settings": [],
                }
            )
            + "\n",
        )
        _write_utf8(
            tpl / "external_modules" / "template_world_plugin" / "feature_template_world_plugin.tscn",
            '[gd_scene load_steps=2 format=3]\n'
            '[ext_resource type="Script" path="res://external_modules/template_world_plugin/feature_template_world_plugin.gd" id="1"]\n'
            '[node name="Root" type="Node2D"]\nscript = ExtResource("1")\n',
        )
        _write_utf8(
            tpl / "external_modules" / "template_world_plugin" / "feature_template_world_plugin.gd",
            'extends ExtensionBase\n'
            'const COMP_PATH := "res://external_modules/template_world_plugin/comp_template_world_plugin__sample.gd"\n'
            'const COMP_SCENE := preload("res://external_modules/template_world_plugin/comp_template_world_plugin__sample.tscn")\n',
        )
        _write_utf8(
            tpl / "external_modules" / "template_world_plugin" / "comp_template_world_plugin__sample.gd",
            "extends CompBase\nfunc public_state(state: Dictionary, _peer: int) -> Dictionary:\n\treturn state.duplicate(true)\n",
        )
        _write_utf8(
            tpl / "external_modules" / "template_world_plugin" / "comp_template_world_plugin__sample.tscn",
            '[gd_scene load_steps=2 format=3]\n'
            '[ext_resource type="Script" path="res://external_modules/template_world_plugin/comp_template_world_plugin__sample.gd" id="1"]\n'
            '[node name="SampleComp" type="Node2D"]\nscript = ExtResource("1")\n',
        )

        res = scaffold_mod("my-aura", config=self.cfg, mode="world-plugin")
        mod_ns = res.target_dir / "external_modules" / "my_aura"
        self.assertTrue((mod_ns / "feature_my_aura.gd").is_file())
        self.assertTrue((mod_ns / "feature_my_aura.tscn").is_file())
        self.assertTrue((mod_ns / "comp_my_aura__sample.gd").is_file())
        self.assertTrue((mod_ns / "comp_my_aura__sample.tscn").is_file())
        self.assertFalse((mod_ns / "comp_template_world_plugin__sample.gd").exists())
        self.assertFalse((mod_ns / "comp_template_world_plugin__sample.tscn").exists())
        self.assertIn(
            "res://external_modules/my_aura/comp_my_aura__sample.gd",
            (mod_ns / "feature_my_aura.gd").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "res://external_modules/my_aura/comp_my_aura__sample.gd",
            (mod_ns / "comp_my_aura__sample.tscn").read_text(encoding="utf-8"),
        )
        rep = validate_mod_dir(res.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertTrue(rep.ok, msg=rep.errors)

    def test_validator_enforces_local_only_owner_class_name_binaries_and_fup(self) -> None:
        res = scaffold_mod("sec-desktop", config=self.cfg, mode="desktop-module")
        mpath = res.manifest_path
        base_manifest = json.loads(mpath.read_text(encoding="utf-8"))

        # 1. Singular `module` + omitted `settings` is valid for desktop-module
        singular = dict(base_manifest)
        singular["module"] = singular.pop("modules")[0]
        singular.pop("settings", None)
        _write_utf8(mpath, json.dumps(singular, indent=2) + "\n")
        rep = validate_mod_dir(res.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertTrue(rep.ok, msg=rep.errors)

        # 2. desktop-module rejecting local_only=false, network_version!=0, pack_file
        bad = json.loads(json.dumps(base_manifest))
        bad["pack_file"] = "content.pck"
        bad["modules"][0]["local_only"] = False
        bad["modules"][0]["network_version"] = 2
        _write_utf8(mpath, json.dumps(bad, indent=2) + "\n")
        rep = validate_mod_dir(res.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertFalse(rep.ok)
        joined = "\n".join(rep.errors)
        self.assertIn("invalid_plugin_pack", joined)
        self.assertIn("invalid_plugin_module_version", joined)

        # 3. module id ownership + scene outside namespace
        bad_owner = json.loads(json.dumps(base_manifest))
        bad_owner["modules"][0]["id"] = "other_plugin.core"
        bad_owner["modules"][0]["entry_scene"] = "res://mods/other_plugin/module.tscn"
        _write_utf8(mpath, json.dumps(bad_owner, indent=2) + "\n")
        rep = validate_mod_dir(res.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertFalse(rep.ok)
        joined = "\n".join(rep.errors)
        self.assertIn("invalid_plugin_module_id", joined)
        self.assertIn("invalid_plugin_module_scene", joined)

        # Restore valid manifest
        _write_utf8(mpath, json.dumps(base_manifest, indent=2) + "\n")

        # 4. Commented `class_name` allowed; real `class_name` rejected
        gd_path = res.entry_path
        _write_utf8(gd_path, "extends ExtensionBase\n# class_name CommentOnly\nvar x := 'class_name InString'\n")
        rep = validate_mod_dir(res.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertTrue(rep.ok, msg=rep.errors)

        _write_utf8(gd_path, "extends ExtensionBase\nclass_name IllegalGlobal\n")
        rep = validate_mod_dir(res.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertFalse(rep.ok)
        self.assertTrue(any("global_class_name_not_allowed" in e for e in rep.errors))
        _write_utf8(gd_path, "extends ExtensionBase\n")

        # 5. Forbidden binary extension rejected
        bad_bin = res.target_dir / "mods" / "sec_desktop" / "native.dll"
        bad_bin.write_bytes(b"MZ")
        rep = validate_mod_dir(res.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertFalse(rep.ok)
        self.assertTrue(any("unsafe_plugin_binary" in e for e in rep.errors))
        bad_bin.unlink()

        # 6. v2 omitting network_version when local_only=false rejected
        v2_res = scaffold_mod("v2-net", config=self.cfg, mode="world-plugin")
        v2_m = json.loads(v2_res.manifest_path.read_text(encoding="utf-8"))
        v2_m["modules"][0].pop("network_version", None)
        _write_utf8(v2_res.manifest_path, json.dumps(v2_m, indent=2) + "\n")
        rep_v2 = validate_mod_dir(v2_res.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertFalse(rep_v2.ok)
        self.assertTrue(any("invalid_plugin_module_version" in e for e in rep_v2.errors))

        # 7. Hybrid import_extensions without entry rejected
        v2_m["modules"][0]["network_version"] = 1
        v2_m["import_extensions"] = ["uvtt"]
        _write_utf8(v2_res.manifest_path, json.dumps(v2_m, indent=2) + "\n")
        rep_hyb = validate_mod_dir(v2_res.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertFalse(rep_hyb.ok)
        self.assertTrue(any("invalid_plugin_entry" in e for e in rep_hyb.errors))

        # 8. .fup archive checks: bad GDPC magic & SHA256SUMS mismatch
        bad_fup = self.case_dir / "bad.fup"
        valid_manifest_bytes = json.dumps(
            {
                "schema": "fus.plugin.v2",
                "host_api": 2,
                "id": "v2_net",
                "version": "0.1.0",
                "name": "V2 Net",
                "pack_file": "content.pck",
                "modules": [
                    {
                        "id": "v2_net.core",
                        "display_name": "V2 Net",
                        "entry_scene": "res://external_modules/v2_net/feature_v2_net.tscn",
                        "version": 1,
                        "network_version": 1,
                    }
                ],
            }
        ).encode("utf-8")
        bad_pck_bytes = b"NOTP_BAD"
        with zipfile.ZipFile(bad_fup, "w") as zf:
            zf.writestr("plugin.json", valid_manifest_bytes)
            zf.writestr("content.pck", bad_pck_bytes)
            zf.writestr("SHA256SUMS.txt", f"{'0' * 64}  plugin.json\n{'0' * 64}  content.pck\n")
        fup_errs = validate_fup_archive(bad_fup)
        self.assertTrue(any("invalid_plugin_pack" in e for e in fup_errs))
        self.assertTrue(any("SHA256SUMS.txt" in e for e in fup_errs))

        # 9. .fup SHA256SUMS.txt > 128 KiB rejection (must NOT silently skip verification)
        good_pck_bytes = b"GDPC\x04\x00\x00\x00FAKE_PCK"
        big_sums_fup = self.case_dir / "bigsums.fup"
        big_sums_text = ("# padding line for oversized sha256sums\n" * 4500)
        self.assertGreater(len(big_sums_text.encode("utf-8")), 128 * 1024)
        with zipfile.ZipFile(big_sums_fup, "w") as zf:
            zf.writestr("plugin.json", valid_manifest_bytes)
            zf.writestr("content.pck", good_pck_bytes)
            zf.writestr("SHA256SUMS.txt", big_sums_text)
        big_errs = validate_fup_archive(big_sums_fup)
        self.assertTrue(any("SHA256SUMS.txt" in e and "128 KiB" in e for e in big_errs), msg=big_errs)

        # 10. .fup duplicate target entries in SHA256SUMS.txt rejected
        manifest_sha = hashlib.sha256(valid_manifest_bytes).hexdigest()
        pck_sha = hashlib.sha256(good_pck_bytes).hexdigest()
        dup_sums_fup = self.case_dir / "dupsums.fup"
        with zipfile.ZipFile(dup_sums_fup, "w") as zf:
            zf.writestr("plugin.json", valid_manifest_bytes)
            zf.writestr("content.pck", good_pck_bytes)
            zf.writestr(
                "SHA256SUMS.txt",
                f"{'0' * 64}  plugin.json\n{manifest_sha}  plugin.json\n{pck_sha}  content.pck\n",
            )
        dup_errs = validate_fup_archive(dup_sums_fup)
        self.assertTrue(any("SHA256SUMS.txt" in e and "重复" in e for e in dup_errs), msg=dup_errs)

        # 11. Real ZIP with raw backslash in Central Directory (`orig_filename` != `filename` on Windows)
        bslash_zip = self.case_dir / "backslash_cd.zip"
        with zipfile.ZipFile(bslash_zip, "w") as zf:
            zf.writestr(
                "plugin.json",
                json.dumps(
                    {
                        "schema": "fus.desktop-module.v1",
                        "host_api": 2,
                        "id": "bslash_mod",
                        "version": "0.1.0",
                        "name": "Backslash Mod",
                        "modules": [
                            {
                                "id": "mod.bslash_mod",
                                "display_name": "Backslash Mod",
                                "entry_scene": "res://mods/bslash_mod/module.tscn",
                                "version": 1,
                                "network_version": 0,
                                "local_only": True,
                            }
                        ],
                    }
                ),
            )
            zf.writestr("mods/bad_entry.gd", "extends ExtensionBase\n")
        raw_bytes = bslash_zip.read_bytes()
        patched_bytes = raw_bytes.replace(b"mods/bad_entry.gd", b"mods\\bad_entry.gd")
        self.assertNotEqual(raw_bytes, patched_bytes)
        bslash_zip.write_bytes(patched_bytes)
        with zipfile.ZipFile(bslash_zip, "r") as zf_check:
            orig_names = [getattr(info, "orig_filename", info.filename) for info in zf_check.infolist()]
            self.assertIn("mods\\bad_entry.gd", orig_names)
        bslash_errs = validate_zip_archive(bslash_zip)
        self.assertTrue(any("unsafe_zip_path" in e and "\\" in e for e in bslash_errs), msg=bslash_errs)
        with self.assertRaises(DeployError) as cm_bslash:
            safe_extract_zip(bslash_zip, self.case_dir / "extract_bslash")
        self.assertIn("unsafe_zip_path", str(cm_bslash.exception))

    def test_resolve_target_mods_with_multiple_template_dirs(self) -> None:
        (self.ws_root / "mods" / "_template-desktop-module").mkdir(parents=True, exist_ok=True)
        (self.ws_root / "mods" / "_template-world-plugin").mkdir(parents=True, exist_ok=True)
        self.assertEqual(
            resolve_target_mods(self.cfg, select_all=True),
            ["_template", "_template-desktop-module", "_template-world-plugin"],
        )
        scaffold_mod("real-mod", config=self.cfg, mode="desktop-module")
        self.assertEqual(resolve_target_mods(self.cfg, select_all=True), ["real-mod"])
        self.assertEqual(
            resolve_target_mods(self.cfg, select_all=True, include_template=True),
            ["_template", "_template-desktop-module", "_template-world-plugin", "real-mod"],
        )

    def test_zip_archive_and_safe_extract_reject_raw_backslash_orig_filename(self) -> None:
        manifest_bytes = json.dumps(
            {
                "schema": "fus.desktop-module.v1",
                "host_api": 2,
                "scope": "desktop",
                "id": "bs_test",
                "version": "0.1.0",
                "name": "Backslash Test",
                "modules": [
                    {
                        "id": "bs_test.core",
                        "display_name": "Backslash Test",
                        "entry_scene": "res://mods/bs_test/module.tscn",
                        "version": 1,
                        "network_version": 0,
                        "local_only": True,
                    }
                ],
                "settings": [],
            }
        ).encode("utf-8")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("plugin.json", manifest_bytes)
            zf.writestr("mods/bs_test/module.tscn", '[gd_scene format=3]\n[node name="Root" type="Node2D"]\n')
            zf.writestr("mods/bs_test/module.gd", "extends ExtensionBase\n")

        raw_zip = buf.getvalue()
        needle = b"mods/bs_test/module.gd"
        # Both Local File Header and Central Directory File Header must be patched.
        self.assertEqual(raw_zip.count(needle), 2)
        patched_zip = raw_zip.replace(needle, b"mods\\bs_test\\module.gd")

        backslash_zip = self.case_dir / "raw_backslash.zip"
        backslash_zip.write_bytes(patched_zip)

        with zipfile.ZipFile(backslash_zip, "r") as zf:
            self.assertIsNone(zf.testzip())
            orig_names = [getattr(info, "orig_filename", info.filename) for info in zf.infolist()]
            self.assertIn("mods\\bs_test\\module.gd", orig_names)

        errs = validate_zip_archive(backslash_zip)
        self.assertTrue(any("unsafe_zip_path" in e for e in errs), msg=errs)

        extract_dest = self.case_dir / "extract_backslash_out"
        with self.assertRaises(DeployError) as cm:
            safe_extract_zip(backslash_zip, extract_dest)
        self.assertIn("unsafe_zip_path", str(cm.exception))
        self.assertFalse(extract_dest.exists())


class PackagerAndDeployerInWorldTests(BaseInWorldDevtoolsTestCase):
    def test_desktop_module_zip_bundles_fu_runtime_and_canonical_fu_sdk_and_fallback(self) -> None:
        res = scaffold_mod("crit-vfx", config=self.cfg, mode="desktop-module")
        # Godot .uid sidecar must be ignored
        (res.target_dir / "mods" / "crit_vfx" / "module.gd.uid").write_bytes(b"uid://ignored\n")

        art = build_mod("crit-vfx", config=self.cfg)
        self.assertEqual(art.package_ext, ".zip")
        self.assertEqual(art.schema, "fus.desktop-module.v1")
        self.assertTrue(art.sdk_bundled)
        with zipfile.ZipFile(art.zip_path, "r") as zf:
            names = set(zf.namelist())
            self.assertIn("mods/crit_vfx/lib/fu_runtime/v2.gd", names)
            self.assertIn("mods/crit_vfx/lib/fu_runtime/desktop_api_helper.gd", names)
            for rel in CANONICAL_RUNTIME_FU_SDK_SCRIPTS:
                self.assertIn(f"mods/crit_vfx/lib/fu_sdk/{rel}", names)
            self.assertNotIn("mods/crit_vfx/module.gd.uid", names)
            self.assertNotIn("lib/fu_sdk/v1.gd", names)

        # Without runtime_manifest.json: fallback picks *.gd + 6 canonical fu_sdk scripts
        (self.runtime_sdk_dir / "runtime_manifest.json").unlink()
        art_fallback = build_mod("crit-vfx", config=self.cfg)
        with zipfile.ZipFile(art_fallback.zip_path, "r") as zf:
            names = set(zf.namelist())
            self.assertIn("mods/crit_vfx/lib/fu_runtime/v2.gd", names)
            self.assertIn("mods/crit_vfx/lib/fu_sdk/logging/log_bus.gd", names)

        # --no-sdk skips bundling
        art_nosdk = build_mod("crit-vfx", config=self.cfg, no_sdk=True)
        self.assertFalse(art_nosdk.sdk_bundled)
        self.assertNotIn("mods/crit_vfx/lib/fu_runtime/v2.gd", art_nosdk.files)

    def test_world_plugin_fup_packaging_serve_and_sync(self) -> None:
        res = scaffold_mod("aura-rings", config=self.cfg, mode="world-plugin")
        # Add an imported asset matching MD5 of res://external_modules/aura_rings/ring.png
        _write_utf8(res.target_dir / "external_modules" / "aura_rings" / "ring.png", "PNG_PLACEHOLDER")
        vfs_md5 = hashlib.md5(b"res://external_modules/aura_rings/ring.png").hexdigest()
        imp_file = res.target_dir / ".godot" / "imported" / f"ring.png-{vfs_md5}.ctex"
        imp_file.parent.mkdir(parents=True, exist_ok=True)
        imp_file.write_bytes(b"CTEX")

        def _fake_pck_packer(*, godot_exe, pck_builder_dir, output_pck, packed_entries, timeout_seconds=120):
            _create_fake_pck(output_pck, packed_entries)

        with mock.patch("fuvtt_devtools.packager._run_pck_packer", side_effect=_fake_pck_packer):
            art = build_mod("aura-rings", config=self.cfg)

        self.assertEqual(art.package_ext, ".fup")
        self.assertEqual(art.zip_path.name, "aura-rings.fup")
        self.assertIsNotNone(art.pck_path)
        self.assertIn(f".godot/imported/ring.png-{vfs_md5}.ctex", art.packed_files)
        self.assertIn("external_modules/aura_rings/lib/fu_runtime/v2.gd", art.packed_files)
        self.assertEqual(sorted(art.files), ["SHA256SUMS.txt", "content.pck", "plugin.json"])
        self.assertEqual(validate_fup_archive(art.zip_path), [])

        # Also build a desktop-module (with omitted settings) to test dual-mode serve + sync
        dm = scaffold_mod("crit-fx", config=self.cfg, mode="desktop-module")
        dm_manifest = json.loads(dm.manifest_path.read_text(encoding="utf-8"))
        dm_manifest.pop("settings", None)
        _write_utf8(dm.manifest_path, json.dumps(dm_manifest, indent=2) + "\n")
        dm_art = build_mod("crit-fx", config=self.cfg)

        # Discover & resolve packages
        pkgs = discover_built_packages(self.cfg.build_dir)
        self.assertEqual({p.mod_name: p.archive_ext for p in pkgs}, {"aura-rings": ".fup", "crit-fx": ".zip"})
        self.assertEqual(resolve_hosted_package("/aura_rings.fup", self.cfg.build_dir).mod_name, "aura-rings")
        self.assertIsNone(resolve_hosted_package("/aura_rings.zip", self.cfg.build_dir))
        self.assertIsNone(resolve_hosted_zip("/aura_rings.fup", self.cfg.build_dir))
        self.assertEqual(resolve_hosted_zip("/crit_fx.zip", self.cfg.build_dir).mod_name, "crit-fx")
        banner = format_serve_banner(pkgs, "127.0.0.1", 8765)
        self.assertIn("/aura-rings.fup", banner)
        self.assertIn("/crit-fx.zip", banner)

        # Live HTTP server GET/HEAD for .fup and .zip
        server = create_dev_http_server(self.cfg, host="127.0.0.1", port=0, quiet=True)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{port}/index.json", timeout=5) as resp:
                idx = json.loads(resp.read().decode("utf-8"))
            by_name = {row["mod_name"]: row for row in idx["packages"]}
            self.assertEqual(by_name["aura-rings"]["format"], "fup")
            self.assertTrue(by_name["aura-rings"]["url"].endswith("/aura-rings.fup"))
            self.assertEqual(by_name["crit-fx"]["format"], "zip")

            with urlopen(f"http://127.0.0.1:{port}/aura_rings.fup", timeout=5) as resp:
                self.assertEqual(resp.headers.get("Content-Type"), "application/octet-stream")
                self.assertEqual(resp.headers.get("X-Plugin-Schema"), "fus.plugin.v2")
                self.assertEqual(resp.read(), art.zip_path.read_bytes())

            req_head = Request(f"http://127.0.0.1:{port}/crit-fx.zip", method="HEAD")
            with urlopen(req_head, timeout=5) as resp:
                self.assertEqual(resp.headers.get("Content-Type"), "application/zip")
                self.assertEqual(resp.headers.get("X-Plugin-Schema"), "fus.desktop-module.v1")
        finally:
            server.shutdown()
            server.server_close()

        # Sync both .fup and .zip into fake session_plugins
        target_sp = self.fake_steam_dir / "FUS_Data" / "session_plugins"
        with mock.patch("fuvtt_devtools.packager._run_pck_packer", side_effect=_fake_pck_packer):
            sync_fup = sync_mod("aura-rings", config=self.cfg, target_dir=target_sp)
            sync_zip = sync_mod("crit-fx", config=self.cfg, target_dir=target_sp)

        self.assertFalse(sync_fup.rebuilt)
        self.assertFalse(sync_zip.rebuilt)
        self.assertEqual(sync_fup.file_hashes_count, 3)
        reg = json.loads((target_sp / "registry.json").read_text(encoding="utf-8"))
        # Omitted settings normalized to [] in registry manifest for ReadRegistry() parity
        self.assertEqual(reg["plugins"]["crit_fx"]["manifest"]["settings"], [])
        self.assertEqual(reg["plugins"]["crit_fx"]["settings"], {})
        self.assertIn("content.pck", reg["plugins"]["aura_rings"]["file_hashes"])

        # Same-version overwrite cleans stale packages/<id>/<old_sha> AND cache/<id>/<old_sha>.zip
        stale_cache_zip = target_sp / "cache" / "crit_fx" / f"{dm_art.sha256}.zip"
        stale_cache_zip.parent.mkdir(parents=True, exist_ok=True)
        stale_cache_zip.write_bytes(b"STALE_CACHE")
        _write_utf8(dm.entry_path, "extends ExtensionBase\n# changed\n")
        time.sleep(0.02)
        os.utime(dm.entry_path, (time.time() + 5, time.time() + 5))
        sync_zip2 = sync_mod("crit-fx", config=self.cfg, target_dir=target_sp, allow_same_version=True)
        self.assertTrue(sync_zip2.rebuilt)
        self.assertFalse(stale_cache_zip.exists())
        self.assertIsNotNone(sync_zip2.cleaned_old_package_dir)
        self.assertFalse(sync_zip2.cleaned_old_package_dir.exists())


class HostVerifierInWorldTests(BaseInWorldDevtoolsTestCase):
    def test_verify_host_inworld_mock_and_readonly_fus_stage(self) -> None:
        scaffold_mod("crit-vfx", config=self.cfg, mode="desktop-module")
        fake_fus = self.case_dir / "ReadOnlyFus"
        _write_utf8(fake_fus / "project.godot", 'config/name="FUS"\nconfig/features=PackedStringArray("4.8", "C#")\n[dotnet]\nproject/assembly_name="Practice"\n')
        _write_utf8(fake_fus / "scenes" / "entities" / "state_value.gd", 'extends RefCounted\nstatic var _packed_validation = load("res://services/storage/PackedValueValidation.cs").new() if ClassDB.class_exists("CSharpScript") else null\n')
        subprocess.run(["git", "init", "-q", str(fake_fus)], check=True)
        subprocess.run(["git", "-C", str(fake_fus), "config", "user.email", "t@e.com"], check=True)
        subprocess.run(["git", "-C", str(fake_fus), "config", "user.name", "T"], check=True)
        subprocess.run(["git", "-C", str(fake_fus), "add", "."], check=True)
        subprocess.run(["git", "-C", str(fake_fus), "commit", "-q", "-m", "init"], check=True)

        invoked_cmds: list[list[str]] = []

        def _mock_runner(cmd, *, cwd, env, timeout_seconds):
            invoked_cmds.append(list(cmd))
            for arg in cmd:
                if arg.startswith("--report="):
                    rep_path = Path(arg.split("=", 1)[1])
                    if rep_path.name == "fus-host-report.json":
                        _write_utf8(rep_path, json.dumps({"ok": True, "passed_checks": 6, "failures": []}))
                    else:
                        _write_utf8(
                            rep_path,
                            json.dumps(
                                {
                                    "ok": True,
                                    "schema": "fus.desktop-module.v1",
                                    "passed_checks": 9,
                                    "loaded_scripts": ["res://mods/crit_vfx/module.gd"],
                                    "failures": [],
                                    "warnings": [],
                                    "entity_count": 1,
                                    "serialized_bytes": 0,
                                    "sdk_probe": {"sdk_version": "2.0.0-test"},
                                }
                            ),
                        )
            return 0, "FUVTT_VERIFY_HOST PASS", "", False

        res = verify_mod_with_host("crit-vfx", config=self.cfg, runner=_mock_runner, fus_repo=fake_fus)
        self.assertTrue(res.ok, msg=res.failures)
        self.assertEqual(res.schema, "fus.desktop-module.v1")
        self.assertTrue(res.host_contract_probe.get("ok"))
        self.assertTrue((res.evidence_dir / "probe_project" / "_host_shims" / "extension_base.gd").is_file())
        self.assertTrue((res.evidence_dir / "probe_project" / ".godot" / "global_script_class_cache.cfg").is_file())
        self.assertTrue((res.evidence_dir / "probe_project" / "inworld_probe.gd").is_file())

        # Read-only source repo MUST remain completely untouched (zero .godot/, clean git status)
        self.assertFalse((fake_fus / ".godot").exists())
        st = subprocess.run(["git", "-C", str(fake_fus), "status", "--short"], capture_output=True, text=True, check=True)
        self.assertEqual(st.stdout.strip(), "")

        # Staged copy in .cache/fus_host_stage/ has pure-GDScript patched project.godot
        stage_dir = Path(res.host_contract_probe["stage_dir"])
        self.assertTrue(stage_dir.is_relative_to(self.cfg.cache_dir))
        self.assertNotIn("[dotnet]", (stage_dir / "project.godot").read_text(encoding="utf-8"))

    def test_real_godot_inworld_desktop_module_and_world_plugin_if_available(self) -> None:
        real_cfg = load_config(WORKSPACE_ROOT)
        if real_cfg.godot_bin is None or not real_cfg.godot_bin.is_file():
            self.skipTest("GODOT_BIN not configured")
        try:
            probe = subprocess.run(
                [str(real_cfg.godot_bin), "--headless", "--quit", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            self.skipTest("GODOT_BIN cannot execute in current sandbox")
        if probe.returncode != 0:
            self.skipTest(f"GODOT_BIN --version exited {probe.returncode}")

        iso_cfg = WorkspaceConfig(
            workspace_root=self.ws_root,
            mods_dir=self.ws_root / "mods",
            sdk_dir=self.sdk_dir,
            build_dir=self.cfg.build_dir,
            cache_dir=self.cfg.cache_dir,
            godot_bin=real_cfg.godot_bin,
            runtime_sdk_dir=self.runtime_sdk_dir,
        )

        # 1. Real Godot verify-host on fus.desktop-module.v1 (.zip mount + ExtensionBase + desktop_api + world.overlays node + mount_node)
        dm_res = scaffold_mod("real-desktop", config=iso_cfg, mode="desktop-module")
        _write_utf8(
            dm_res.entry_path,
            "extends ExtensionBase\n"
            "var _ov: Node2D = null\n"
            "var _mounted: CanvasLayer = null\n"
            "func _on_register(context: ExtensionContext) -> void:\n"
            "\tvar api := context.consume_service(\"desktop_api\")\n"
            "\tvar desktop: Node = api.call(&\"get_desktop\") if api != null else null\n"
            "\t_ov = Node2D.new()\n"
            "\tcontext.register_slot_item(&\"world.overlays\", {\"id\": \"mod.real_desktop.ov\", \"band\": \"above_entities\", \"node\": _ov})\n"
            "\tif is_instance_valid(desktop):\n"
            "\t\t_mounted = CanvasLayer.new()\n"
            "\t\tcontext.mount_node(desktop, _mounted)\n"
            "\tcontext.subscribe_hook(&\"mod.real_desktop.ping\", func(_p: Dictionary) -> void: pass)\n"
            "func _on_unregister() -> void:\n"
            "\t_ov = null\n"
            "\t_mounted = null\n",
        )
        res_d = verify_mod_with_host("real-desktop", config=iso_cfg)
        self.assertTrue(res_d.ok, msg=f"desktop-module Godot verify failed: {res_d.failures} / {res_d.log_errors}")
        self.assertEqual(res_d.log_errors, [])
        self.assertIn("res://mods/real_desktop/module.gd", res_d.loaded_scripts)
        self.assertIn("res://mods/real_desktop/lib/fu_runtime/v2.gd", res_d.loaded_scripts)

        # 2. Real Godot PCKPacker build + verify-host on fus.plugin.v2 (.fup + content.pck + CompBase + public_state)
        v2_res = scaffold_mod("real-world", config=iso_cfg, mode="world-plugin")
        _write_utf8(
            v2_res.target_dir / "external_modules" / "real_world" / "comp_real_world__marker.gd",
            'extends CompBase\n@export var label: String = "alpha"\nfunc public_state(state: Dictionary, _peer: int) -> Dictionary:\n\treturn state.duplicate(true)\n',
        )
        _write_utf8(
            v2_res.entry_path,
            "extends ExtensionBase\n"
            "func _on_register(context: ExtensionContext) -> void:\n"
            '\tcontext.register_component({"id": "real_world__marker", "path": "res://external_modules/real_world/comp_real_world__marker.gd", "network_scope": "shared"})\n',
        )
        art_w = build_mod("real-world", config=iso_cfg)
        self.assertEqual(art_w.package_ext, ".fup")
        res_w = verify_mod_with_host("real-world", config=iso_cfg)
        self.assertTrue(res_w.ok, msg=f"world-plugin Godot verify failed: {res_w.failures} / {res_w.log_errors}")
        self.assertIn("res://external_modules/real_world/feature_real_world.gd", res_w.loaded_scripts)
        self.assertIn("res://external_modules/real_world/comp_real_world__marker.gd", res_w.loaded_scripts)

        # 3. Negative Godot check: CompBase missing public_state with network_scope="shared" must fail
        _write_utf8(
            v2_res.target_dir / "external_modules" / "real_world" / "comp_real_world__marker.gd",
            'extends CompBase\n@export var label: String = "alpha"\n',
        )
        build_mod("real-world", config=iso_cfg)
        res_bad = verify_mod_with_host("real-world", config=iso_cfg)
        self.assertFalse(res_bad.ok)
        self.assertTrue(any("public_state" in f for f in res_bad.failures))

    def test_real_fu_runtime_bundling_and_godot_verify_if_available(self) -> None:
        real_rt_dir = WORKSPACE_ROOT / "shared" / "sdk" / "fu_runtime"
        real_sdk_dir = WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk"
        if not (real_rt_dir / "runtime_manifest.json").is_file():
            self.skipTest("shared/sdk/fu_runtime/runtime_manifest.json not present")

        manifest_meta = json.loads((real_rt_dir / "runtime_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest_meta.get("schema"), "fu_runtime.manifest.v1")

        real_cfg = load_config(WORKSPACE_ROOT)
        if real_cfg.godot_bin is None or not real_cfg.godot_bin.is_file():
            self.skipTest("GODOT_BIN not configured")
        try:
            probe = subprocess.run(
                [str(real_cfg.godot_bin), "--headless", "--quit", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            self.skipTest("GODOT_BIN cannot execute in current sandbox")
        if probe.returncode != 0:
            self.skipTest(f"GODOT_BIN --version exited {probe.returncode}")

        iso_cfg = WorkspaceConfig(
            workspace_root=self.ws_root,
            mods_dir=self.ws_root / "mods",
            sdk_dir=real_sdk_dir,
            build_dir=self.cfg.build_dir,
            cache_dir=self.cfg.cache_dir,
            godot_bin=real_cfg.godot_bin,
            runtime_sdk_dir=real_rt_dir,
        )

        # 1. fus.desktop-module.v1 bundling real fu_runtime + 6 shared fu_sdk scripts
        dm = scaffold_mod("rt-desktop", config=iso_cfg, mode="desktop-module")
        _write_utf8(
            dm.entry_path,
            "extends ExtensionBase\n"
            "var _rt: RefCounted = null\n"
            "func _on_register(context: ExtensionContext) -> void:\n"
            "\tvar self_scr := get_script() as Script\n"
            "\tvar v2_scr := load(self_scr.resource_path.get_base_dir().path_join(\"lib/fu_runtime/v2.gd\")) as Script\n"
            "\t_rt = v2_scr.new()\n"
            "\tvar logger: RefCounted = _rt.call(&\"get_logger\")\n"
            "\tvar api_h: RefCounted = _rt.call(&\"create_desktop_api_helper\", context, logger)\n"
            "\tvar hook_h: RefCounted = _rt.call(&\"create_hook_helper\", context, logger)\n"
            "\tif api_h != null and hook_h != null:\n"
            "\t\tvar hid: StringName = hook_h.call(&\"build_custom_hook_id\", \"mod\", \"rt_desktop\", \"ready\")\n"
            "\t\thook_h.call(&\"subscribe\", hid, func(_p: Dictionary) -> void: pass)\n"
            "func _on_unregister() -> void:\n"
            "\t_rt = null\n",
        )
        art_d = build_mod("rt-desktop", config=iso_cfg)
        for rt_rel in manifest_meta["runtime_scripts"]:
            self.assertIn(f"mods/rt_desktop/lib/fu_runtime/{rt_rel}", art_d.files)
        for sdk_rel in manifest_meta["shared_fu_sdk_scripts"]:
            self.assertIn(f"mods/rt_desktop/lib/fu_sdk/{sdk_rel}", art_d.files)
        vr_d = verify_mod_with_host("rt-desktop", config=iso_cfg)
        self.assertTrue(vr_d.ok, msg=f"real fu_runtime desktop-module failed: {vr_d.failures} / {vr_d.log_errors}")
        self.assertEqual(vr_d.log_errors, [])
        self.assertEqual(vr_d.sdk_probe.get("sdk_version"), manifest_meta["sdk_version"])

        # 2. fus.plugin.v2 (.fup) bundling real fu_runtime + 6 shared fu_sdk scripts
        wm = scaffold_mod("rt-world", config=iso_cfg, mode="world-plugin")
        _write_utf8(
            wm.entry_path,
            "extends ExtensionBase\n"
            "var _rt: RefCounted = null\n"
            "func _on_register(context: ExtensionContext) -> void:\n"
            "\tvar self_scr := get_script() as Script\n"
            "\tvar v2_scr := load(self_scr.resource_path.get_base_dir().path_join(\"lib/fu_runtime/v2.gd\")) as Script\n"
            "\t_rt = v2_scr.new()\n"
            "\tvar slot_h: RefCounted = _rt.call(&\"create_slot_helper\", context)\n"
            "\tvar net_h: RefCounted = _rt.call(&\"create_network_helper\", \"rt_world.core\", false, context)\n"
            "\tif slot_h != null and net_h != null:\n"
            "\t\tvar _safe: Dictionary = _rt.call(&\"safe_clone_dict\", {\"ok\": true})\n"
            "func _on_unregister() -> void:\n"
            "\t_rt = null\n",
        )
        art_w = build_mod("rt-world", config=iso_cfg)
        self.assertEqual(art_w.package_ext, ".fup")
        for rt_rel in manifest_meta["runtime_scripts"]:
            self.assertIn(f"external_modules/rt_world/lib/fu_runtime/{rt_rel}", art_w.packed_files)
        for sdk_rel in manifest_meta["shared_fu_sdk_scripts"]:
            self.assertIn(f"external_modules/rt_world/lib/fu_sdk/{sdk_rel}", art_w.packed_files)
        vr_w = verify_mod_with_host("rt-world", config=iso_cfg)
        self.assertTrue(vr_w.ok, msg=f"real fu_runtime world-plugin failed: {vr_w.failures} / {vr_w.log_errors}")
        self.assertEqual(vr_w.log_errors, [])

    def test_real_godot_multiline_docstring_and_hybrid_entry_if_available(self) -> None:
        real_cfg = load_config(WORKSPACE_ROOT)
        if real_cfg.godot_bin is None or not real_cfg.godot_bin.is_file():
            self.skipTest("GODOT_BIN not configured")
        try:
            probe = subprocess.run(
                [str(real_cfg.godot_bin), "--headless", "--quit", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            self.skipTest("GODOT_BIN cannot execute in current sandbox")
        if probe.returncode != 0:
            self.skipTest(f"GODOT_BIN --version exited {probe.returncode}")

        iso_cfg = WorkspaceConfig(
            workspace_root=self.ws_root,
            mods_dir=self.ws_root / "mods",
            sdk_dir=self.sdk_dir,
            build_dir=self.cfg.build_dir,
            cache_dir=self.cfg.cache_dir,
            godot_bin=real_cfg.godot_bin,
            runtime_sdk_dir=self.runtime_sdk_dir,
        )

        # 1. Multiline docstring containing `class_name` passes both validate_mod_dir and verify_mod_with_host
        ml = scaffold_mod("ml-doc", config=iso_cfg, mode="desktop-module", import_extensions=["hyb"])
        _write_utf8(
            ml.entry_path,
            'extends ExtensionBase\n'
            'const DOC_A := """\n'
            'class_name FakeClassInsideDoubleMultiline\n'
            '"""\n'
            "const DOC_B := '''\n"
            "class_name FakeClassInsideSingleMultiline\n"
            "'''\n"
            'func _on_register(_context: ExtensionContext) -> void:\n'
            '\tpass\n',
        )
        _write_utf8(
            ml.target_dir / "entry.gd",
            "extends RefCounted\n"
            "func inspect_import(_p: String, _o: Dictionary, _h: Object) -> Dictionary:\n"
            '\treturn {"ok": true}\n'
            "func prepare_import(_p: String, _o: Dictionary, _h: Object) -> Dictionary:\n"
            '\treturn {"ok": true}\n',
        )
        rep = validate_mod_dir(ml.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertTrue(rep.ok, msg=rep.errors)
        vr = verify_mod_with_host("ml-doc", config=iso_cfg)
        self.assertTrue(vr.ok, msg=f"multiline docstring + hybrid entry failed: {vr.failures} / {vr.log_errors}")
        self.assertEqual(vr.log_errors, [])
        self.assertIn("res://pkg/entry.gd", vr.loaded_scripts)

        # 2. Hybrid entry missing prepare_import inside packaged archive fails verify_mod_with_host
        zip_path = self.cfg.build_dir / "ml-doc" / "ml-doc.zip"
        self.assertTrue(zip_path.is_file())
        with zipfile.ZipFile(zip_path, "r") as zin:
            entries = [(info.filename, zin.read(info.filename)) for info in zin.infolist()]
        with zipfile.ZipFile(zip_path, "w") as zout:
            for fname, data in entries:
                if fname == "entry.gd":
                    data = (
                        b"extends RefCounted\n"
                        b"func inspect_import(_p: String, _o: Dictionary, _h: Object) -> Dictionary:\n"
                        b'\treturn {"ok": true}\n'
                    )
                zout.writestr(fname, data)
        future_ts = time.time() + 10
        os.utime(zip_path, (future_ts, future_ts))
        bmanifest_path = self.cfg.build_dir / "ml-doc" / "build-manifest.json"
        bmanifest = json.loads(bmanifest_path.read_text(encoding="utf-8"))
        bmanifest["sha256"] = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        _write_utf8(bmanifest_path, json.dumps(bmanifest, indent=2) + "\n")
        os.utime(bmanifest_path, (future_ts, future_ts))
        vr_bad = verify_mod_with_host("ml-doc", config=iso_cfg)
        self.assertFalse(vr_bad.ok)
        self.assertTrue(any("prepare_import" in f for f in vr_bad.failures), msg=vr_bad.failures)

    def test_real_godot_fus_host_overlays_node_and_network_session_if_available(self) -> None:
        real_cfg = load_config(WORKSPACE_ROOT)
        if real_cfg.godot_bin is None or not real_cfg.godot_bin.is_file():
            self.skipTest("GODOT_BIN not configured")
        if real_cfg.fus_repo_dir is None or not real_cfg.fus_repo_dir.is_dir():
            self.skipTest("FUS_REPO_DIR not configured")
        try:
            probe = subprocess.run(
                [str(real_cfg.godot_bin), "--headless", "--quit", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            self.skipTest("GODOT_BIN cannot execute in current sandbox")
        if probe.returncode != 0:
            self.skipTest(f"GODOT_BIN --version exited {probe.returncode}")

        iso_cfg = WorkspaceConfig(
            workspace_root=self.ws_root,
            mods_dir=self.ws_root / "mods",
            sdk_dir=self.sdk_dir,
            build_dir=self.cfg.build_dir,
            cache_dir=real_cfg.cache_dir,
            godot_bin=real_cfg.godot_bin,
            fus_repo_dir=real_cfg.fus_repo_dir,
            runtime_sdk_dir=self.runtime_sdk_dir,
        )

        mod = scaffold_mod("fus-host-node-net", config=iso_cfg, mode="desktop-module")
        _write_utf8(
            mod.entry_path,
            "extends ExtensionBase\n"
            "var _ov: Node2D = null\n"
            "var _net: DesktopNetworkSession = null\n"
            "func _on_register(context: ExtensionContext) -> void:\n"
            "\tvar desk: Node = context.runtime_node().get_desktop()\n"
            "\t_net = desk.get_network_session()\n"
            "\tassert(_net != null)\n"
            "\t_ov = Node2D.new()\n"
            '\tcontext.register_slot_item(&"world.overlays", {"id": "mod.fus_host_node_net.ov", "band": "above_entities", "node": _ov})\n'
            "func _on_unregister() -> void:\n"
            "\t_ov = null\n"
            "\t_net = null\n",
        )
        res = verify_mod_with_host("fus-host-node-net", config=iso_cfg, fus_repo="auto")
        self.assertTrue(res.ok, msg=f"fus_repo=auto host check failed: {res.failures} / {res.log_errors}")
        self.assertEqual(res.failures, [])
        self.assertEqual(res.log_errors, [])
        self.assertTrue(res.host_contract_probe.get("ok"), msg=res.host_contract_probe)

    def test_hybrid_ext_bundles_fu_sdk_for_zip_and_fup_and_verifies_default_entry(self) -> None:
        """C1: Hybrid desktop-module & world-plugin bundle lib/fu_sdk/* so default entry.gd executes cleanly."""
        real_sdk = WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk"
        real_rt = WORKSPACE_ROOT / "shared" / "sdk" / "fu_runtime"
        real_cfg = load_config(WORKSPACE_ROOT)
        iso_cfg = WorkspaceConfig(
            workspace_root=self.ws_root,
            mods_dir=self.ws_root / "mods",
            sdk_dir=real_sdk,
            build_dir=self.cfg.build_dir,
            cache_dir=self.cfg.cache_dir,
            godot_bin=real_cfg.godot_bin,
            runtime_sdk_dir=real_rt,
        )

        # 1. Hybrid desktop-module (.zip)
        dm = scaffold_mod("hyb-dm-sdk", config=iso_cfg, mode="desktop-module", import_extensions=["uvtt"])
        dm_manifest = json.loads((dm.target_dir / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(dm_manifest.get("scope"), "hybrid")
        self.assertEqual(dm_manifest.get("entry"), "entry.gd")
        self.assertEqual(dm_manifest.get("import_extensions"), ["uvtt"])
        self.assertTrue(validate_mod_dir(dm.target_dir, sdk_dir=real_sdk, runtime_sdk_dir=real_rt).ok)
        art_dm = build_mod("hyb-dm-sdk", config=iso_cfg)
        self.assertEqual(art_dm.package_ext, ".zip")
        self.assertEqual(validate_zip_archive(art_dm.zip_path), [])
        with zipfile.ZipFile(art_dm.zip_path, "r") as zf:
            names = set(zf.namelist())
            self.assertIn("entry.gd", names)
            self.assertIn("lib/fu_sdk/v1.gd", names)
            self.assertTrue(any(n.startswith("mods/hyb_dm_sdk/lib/fu_runtime/") for n in names))

        # 2. Hybrid world-plugin (.fup outer package + default entry verification via real Godot)
        wp = scaffold_mod("hyb-wp-sdk", config=iso_cfg, mode="world-plugin", import_extensions=["uvtt"])
        wp_manifest = json.loads((wp.target_dir / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(wp_manifest.get("scope"), "hybrid")
        self.assertEqual(wp_manifest.get("entry"), "entry.gd")
        self.assertEqual(wp_manifest.get("import_extensions"), ["uvtt"])
        self.assertTrue(validate_mod_dir(wp.target_dir, sdk_dir=real_sdk, runtime_sdk_dir=real_rt).ok)

        if real_cfg.godot_bin is None or not real_cfg.godot_bin.is_file():
            return
        try:
            probe = subprocess.run(
                [str(real_cfg.godot_bin), "--headless", "--quit", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            return
        if probe.returncode != 0:
            return

        art_wp = build_mod("hyb-wp-sdk", config=iso_cfg)
        self.assertEqual(art_wp.package_ext, ".fup")
        self.assertEqual(validate_zip_archive(art_wp.zip_path), [])
        with zipfile.ZipFile(art_wp.zip_path, "r") as zf:
            names = set(zf.namelist())
            self.assertIn("entry.gd", names)
            self.assertIn("lib/fu_sdk/v1.gd", names)
            self.assertIn("SHA256SUMS.txt", names)
            self.assertIn("content.pck", names)
            sums_text = zf.read("SHA256SUMS.txt").decode("utf-8")
            self.assertIn("lib/fu_sdk/v1.gd", sums_text)

        vr_dm = verify_mod_with_host("hyb-dm-sdk", config=iso_cfg)
        self.assertTrue(vr_dm.ok, msg=f"hybrid desktop-module default entry failed: {vr_dm.failures} / {vr_dm.log_errors}")
        self.assertIn("res://pkg/entry.gd", vr_dm.loaded_scripts)
        self.assertEqual(vr_dm.log_errors, [])

        vr_wp = verify_mod_with_host("hyb-wp-sdk", config=iso_cfg)
        self.assertTrue(vr_wp.ok, msg=f"hybrid world-plugin default entry failed: {vr_wp.failures} / {vr_wp.log_errors}")
        self.assertIn("res://pkg/entry.gd", vr_wp.loaded_scripts)
        self.assertEqual(vr_wp.log_errors, [])

    def test_desktop_api_service_shim_parity_and_can_author_world(self) -> None:
        """C2: _INWORLD_HOST_SHIMS['desktop_api_service.gd'] matches real FUS DesktopApiService and _MockDesktop exposes can_author_world."""
        _shim_class, shim_src = _INWORLD_HOST_SHIMS["desktop_api_service.gd"]
        for required_method in (
            "func get_entities(",
            "func selected_entities(",
            "func find_entity(",
            "func read_entity_vitals(",
            "func read_saved_module_entry(",
            "func request_roll(",
            "func can_command_entity(",
            "func camera_position(",
            "func camera_zoom(",
            "func screen_to_world(",
            "func world_to_screen(",
            "func current_mode(",
            "func set_mode(",
        ):
            self.assertIn(required_method, shim_src, msg=f"Missing real FUS DesktopApiService method: {required_method}")

        for stale_method in (
            "func list_entities(",
            "func get_entity(",
            "func get_entity_vitals(",
            "func get_entity_sheet(",
            "func get_saved_module_entry(",
            "func list_saved_module_entries(",
        ):
            self.assertNotIn(stale_method, shim_src, msg=f"Stale nonexistent shim method still present: {stale_method}")

        real_cfg = load_config(WORKSPACE_ROOT)
        if real_cfg.godot_bin is None or not real_cfg.godot_bin.is_file():
            return
        try:
            probe = subprocess.run(
                [str(real_cfg.godot_bin), "--headless", "--quit", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            return
        if probe.returncode != 0:
            return

        iso_cfg = WorkspaceConfig(
            workspace_root=self.ws_root,
            mods_dir=self.ws_root / "mods",
            sdk_dir=self.sdk_dir,
            build_dir=self.cfg.build_dir,
            cache_dir=self.cfg.cache_dir,
            godot_bin=real_cfg.godot_bin,
            runtime_sdk_dir=self.runtime_sdk_dir,
        )
        mod = scaffold_mod("dapi-parity", config=iso_cfg, mode="desktop-module")
        _write_utf8(
            mod.entry_path,
            "extends ExtensionBase\n"
            "func _on_register(context: ExtensionContext) -> void:\n"
            "\tvar dapi: Object = context.consume_service(\"desktop_api\")\n"
            "\tassert(dapi != null)\n"
            "\tassert(bool(dapi.call(&\"is_gm\")))\n"
            "\tassert((dapi.call(&\"get_entities\") as Array).size() == 0)\n"
            "\tassert((dapi.call(&\"selected_entities\") as Array).size() == 0)\n"
            "\tassert(dapi.call(&\"find_entity\", \"tok_1\") == null)\n"
            "\tvar vitals: Dictionary = dapi.call(&\"read_entity_vitals\", \"tok_1\")\n"
            "\tassert(vitals.has(\"ok\"))\n"
            "\tvar saved: Dictionary = dapi.call(&\"read_saved_module_entry\", \"dapi_parity\")\n"
            "\tassert(typeof(saved) == TYPE_DICTIONARY)\n"
            "\tvar roll: Dictionary = dapi.call(&\"request_roll\", \"1d20+2\", \"Test\")\n"
            "\tassert(roll.has(\"ok\") and roll.has(\"reason\"))\n"
            "\tassert(typeof(dapi.call(&\"camera_position\")) == TYPE_VECTOR2)\n"
            "\tassert(typeof(dapi.call(&\"screen_to_world\", Vector2.ZERO)) == TYPE_VECTOR2)\n"
            "\tassert(typeof(dapi.call(&\"world_to_screen\", Vector2.ZERO)) == TYPE_VECTOR2)\n"
            "\tassert(bool(dapi.call(&\"set_mode\", \"edit\")) and str(dapi.call(&\"current_mode\")) == \"edit\")\n"
            "\tvar desk: Node = context.runtime_node().get_desktop()\n"
            "\tassert(desk != null and desk.has_method(&\"can_author_world\"))\n"
            "\tassert(bool(desk.call(&\"can_author_world\")))\n"
            "func _on_unregister() -> void:\n"
            "\tpass\n",
        )
        vr = verify_mod_with_host("dapi-parity", config=iso_cfg)
        self.assertTrue(vr.ok, msg=f"DesktopApiService parity check failed: {vr.failures} / {vr.log_errors}")
        self.assertEqual(vr.log_errors, [])

    def test_inworld_validator_blocks_semicolon_class_name_non_list_manifest_and_non_namespace_fup_files(self) -> None:
        """C4: Catch semicolon class_name bypass, non-list runtime_manifest fields, and un-packable .fup non-namespace files."""
        # 1. Semicolon class_name bypass
        semi = scaffold_mod("semi-class", config=self.cfg, mode="desktop-module")
        _write_utf8(
            semi.entry_path,
            "extends ExtensionBase; class_name EvilGlobalClass\n"
            "func _on_register(_context: ExtensionContext) -> void:\n"
            "\tpass\n",
        )
        rep_semi = validate_mod_dir(semi.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertFalse(rep_semi.ok)
        self.assertTrue(any("class_name" in e for e in rep_semi.errors), msg=rep_semi.errors)
        with self.assertRaises(PackageError):
            build_mod("semi-class", config=self.cfg)

        # Even if zipped directly, validate_zip_archive catches semicolon class_name in in-world .zip
        bad_zip = self.case_dir / "semi_class_direct.zip"
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("plugin.json", (semi.target_dir / "plugin.json").read_text(encoding="utf-8"))
            zf.writestr("mods/semi_class/module.gd", "extends ExtensionBase; class_name EvilArchiveClass\n")
        z_errs = validate_zip_archive(bad_zip)
        self.assertTrue(any("class_name" in e for e in z_errs), msg=z_errs)

        # 2. Non-list runtime_scripts / shared_fu_sdk_scripts rejected by resolve_runtime_sdk_bundle
        bad_rt_dir = self.case_dir / "bad_runtime_manifest"
        bad_rt_dir.mkdir(parents=True, exist_ok=True)
        _write_utf8(
            bad_rt_dir / "runtime_manifest.json",
            json.dumps(
                {
                    "schema": "fu_runtime.bundle.v1",
                    "version": "2.0.0",
                    "runtime_scripts": {"v2": "v2.gd"},
                    "shared_fu_sdk_scripts": "utils/type_utils.gd",
                }
            ),
        )
        _, _, rt_errs = resolve_runtime_sdk_bundle(self.sdk_dir, bad_rt_dir)
        self.assertTrue(any("runtime_scripts" in e for e in rt_errs), msg=rt_errs)
        self.assertTrue(any("shared_fu_sdk_scripts" in e for e in rt_errs), msg=rt_errs)

        # 3. Non-namespace extra file inside world-plugin (.fup) mod dir rejected cleanly
        wp = scaffold_mod("fup-extra", config=self.cfg, mode="world-plugin")
        _write_utf8(wp.target_dir / "assets" / "extra.txt", "would be silently dropped from content.pck")
        rep_wp = validate_mod_dir(wp.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertFalse(rep_wp.ok)
        self.assertTrue(any("assets/extra.txt" in e for e in rep_wp.errors), msg=rep_wp.errors)

    def test_whitespace_entry_and_pack_file_rejected_matching_fus_host(self) -> None:
        """R2-2: Non-empty whitespace-only or padded entry/pack_file/pck must be rejected (PluginPackageJob parity)."""
        self.assertEqual(_extract_pack_file({"pack_file": "", "pck": "content.pck"}), "content.pck")
        self.assertEqual(_extract_pack_file({"pack_file": "   ", "pck": "content.pck"}), "   ")
        self.assertEqual(_extract_pack_file({"pack_file": " content.pck "}), " content.pck ")

        dm = scaffold_mod("ws-desk", config=self.cfg, mode="desktop-module")
        dm_base = json.loads(dm.manifest_path.read_text(encoding="utf-8"))
        for key, bad_val, expected_err in (
            ("entry", "   ", "invalid_plugin_entry"),
            ("entry", " entry.gd ", "invalid_plugin_entry"),
            ("pack_file", "   ", "invalid_plugin_pack"),
            ("pck", "   ", "invalid_plugin_pack"),
        ):
            m = json.loads(json.dumps(dm_base))
            m[key] = bad_val
            _write_utf8(dm.manifest_path, json.dumps(m, indent=2) + "\n")
            rep = validate_mod_dir(dm.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
            self.assertFalse(rep.ok, msg=f"desktop-module accepted {key}={bad_val!r}")
            self.assertTrue(any(expected_err in e for e in rep.errors), msg=rep.errors)
            with self.assertRaises(PackageError):
                build_mod("ws-desk", config=self.cfg)

        wp = scaffold_mod("ws-world", config=self.cfg, mode="world-plugin")
        wp_base = json.loads(wp.manifest_path.read_text(encoding="utf-8"))
        for patch, expected_err in (
            ({"entry": "   "}, "invalid_plugin_entry"),
            ({"entry": " entry.gd "}, "invalid_plugin_entry"),
            ({"pack_file": "   "}, "invalid_plugin_pack"),
            ({"pack_file": " content.pck "}, "invalid_plugin_pack"),
            ({"pack_file": "", "pck": "   "}, "invalid_plugin_pack"),
            ({"pack_file": "", "pck": " content.pck "}, "invalid_plugin_pack"),
            ({"pack_file": "   ", "pck": "content.pck"}, "invalid_plugin_pack"),
        ):
            m = json.loads(json.dumps(wp_base))
            m.pop("pack_file", None)
            m.pop("pck", None)
            m.update(patch)
            _write_utf8(wp.manifest_path, json.dumps(m, indent=2) + "\n")
            rep = validate_mod_dir(wp.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
            self.assertFalse(rep.ok, msg=f"world-plugin accepted patch={patch!r}")
            self.assertTrue(any(expected_err in e for e in rep.errors), msg=rep.errors)

    def test_empty_pack_file_falls_back_to_pck_in_host_verifier(self) -> None:
        """R2-1: `{\"pack_file\": \"\", \"pck\": \"content.pck\"}` must validate, build .fup, and pass verify-host."""
        real_cfg = load_config(WORKSPACE_ROOT)
        if real_cfg.godot_bin is None or not real_cfg.godot_bin.is_file():
            self.skipTest("GODOT_BIN not configured")
        try:
            probe = subprocess.run(
                [str(real_cfg.godot_bin), "--headless", "--quit", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            self.skipTest("GODOT_BIN cannot execute in current sandbox")
        if probe.returncode != 0:
            self.skipTest(f"GODOT_BIN --version exited {probe.returncode}")

        iso_cfg = WorkspaceConfig(
            workspace_root=self.ws_root,
            mods_dir=self.ws_root / "mods",
            sdk_dir=self.sdk_dir,
            build_dir=self.cfg.build_dir,
            cache_dir=self.cfg.cache_dir,
            godot_bin=real_cfg.godot_bin,
            runtime_sdk_dir=self.runtime_sdk_dir,
        )
        wp = scaffold_mod("pck-fallback", config=iso_cfg, mode="world-plugin")
        m = json.loads(wp.manifest_path.read_text(encoding="utf-8"))
        m["pack_file"] = ""
        m["pck"] = "content.pck"
        _write_utf8(wp.manifest_path, json.dumps(m, indent=2) + "\n")

        rep = validate_mod_dir(wp.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertTrue(rep.ok, msg=rep.errors)
        art = build_mod("pck-fallback", config=iso_cfg)
        self.assertEqual(art.package_ext, ".fup")
        self.assertEqual(validate_fup_archive(art.zip_path), [])
        vr = verify_mod_with_host("pck-fallback", config=iso_cfg)
        self.assertTrue(vr.ok, msg=f"verify-host failed on empty pack_file + pck fallback: {vr.failures} / {vr.log_errors}")
        self.assertEqual(vr.log_errors, [])

    def test_empty_and_null_entry_scene_display_name_aliases_pass_verify_host_and_fus_repo(self) -> None:
        """R3-1: `entry_scene: \"\"/None` -> `path` and `display_name: \"\"/None` -> `name` must pass validate, build, and verify-host (incl. --fus-repo auto)."""
        # 1. Static validate + build works even without Godot for desktop-module
        dm = scaffold_mod("alias-desk", config=self.cfg, mode="desktop-module")
        dm_m = json.loads(dm.manifest_path.read_text(encoding="utf-8"))
        orig_scene = dm_m["modules"][0]["entry_scene"]
        orig_dname = dm_m["modules"][0]["display_name"]
        dm_m["modules"][0]["entry_scene"] = ""
        dm_m["modules"][0]["path"] = orig_scene
        dm_m["modules"][0]["display_name"] = ""
        dm_m["modules"][0]["name"] = orig_dname
        _write_utf8(dm.manifest_path, json.dumps(dm_m, indent=2) + "\n")
        rep = validate_mod_dir(dm.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertTrue(rep.ok, msg=rep.errors)
        art = build_mod("alias-desk", config=self.cfg)
        self.assertEqual(art.package_ext, ".zip")
        self.assertEqual(validate_zip_archive(art.zip_path), [])

        real_cfg = load_config(WORKSPACE_ROOT)
        if real_cfg.godot_bin is None or not real_cfg.godot_bin.is_file():
            self.skipTest("GODOT_BIN not configured")
        try:
            probe = subprocess.run(
                [str(real_cfg.godot_bin), "--headless", "--quit", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            self.skipTest("GODOT_BIN cannot execute in current sandbox")
        if probe.returncode != 0:
            self.skipTest(f"GODOT_BIN --version exited {probe.returncode}")

        has_fus = real_cfg.fus_repo_dir is not None and real_cfg.fus_repo_dir.is_dir()
        iso_cfg = WorkspaceConfig(
            workspace_root=self.ws_root,
            mods_dir=self.ws_root / "mods",
            sdk_dir=self.sdk_dir,
            build_dir=self.cfg.build_dir,
            cache_dir=real_cfg.cache_dir if has_fus else self.cfg.cache_dir,
            godot_bin=real_cfg.godot_bin,
            fus_repo_dir=real_cfg.fus_repo_dir if has_fus else None,
            runtime_sdk_dir=self.runtime_sdk_dir,
        )

        # Verify empty-string alias on desktop-module (with --fus-repo auto if available)
        vr_dm = verify_mod_with_host("alias-desk", config=iso_cfg, fus_repo="auto" if has_fus else None)
        self.assertTrue(vr_dm.ok, msg=f"verify-host failed on empty entry_scene/display_name alias: {vr_dm.failures} / {vr_dm.log_errors}")
        self.assertEqual(vr_dm.log_errors, [])
        if has_fus:
            self.assertTrue(vr_dm.host_contract_probe.get("ok"), msg=vr_dm.host_contract_probe)

        # 2. Verify null alias on world-plugin (.fup + content.pck + --fus-repo auto)
        wp = scaffold_mod("alias-wp", config=iso_cfg, mode="world-plugin")
        wp_m = json.loads(wp.manifest_path.read_text(encoding="utf-8"))
        wp_orig_scene = wp_m["modules"][0]["entry_scene"]
        wp_orig_dname = wp_m["modules"][0]["display_name"]
        wp_m["modules"][0]["entry_scene"] = None
        wp_m["modules"][0]["path"] = wp_orig_scene
        wp_m["modules"][0]["display_name"] = None
        wp_m["modules"][0]["name"] = wp_orig_dname
        _write_utf8(wp.manifest_path, json.dumps(wp_m, indent=2) + "\n")
        rep_wp = validate_mod_dir(wp.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertTrue(rep_wp.ok, msg=rep_wp.errors)
        art_wp = build_mod("alias-wp", config=iso_cfg)
        self.assertEqual(art_wp.package_ext, ".fup")
        vr_wp = verify_mod_with_host("alias-wp", config=iso_cfg, fus_repo="auto" if has_fus else None)
        self.assertTrue(vr_wp.ok, msg=f"verify-host failed on null entry_scene/display_name alias: {vr_wp.failures} / {vr_wp.log_errors}")
        self.assertEqual(vr_wp.log_errors, [])
        if has_fus:
            self.assertTrue(vr_wp.host_contract_probe.get("ok"), msg=vr_wp.host_contract_probe)

    def test_whitespace_entry_scene_with_path_fallback_rejected_matching_fus_host(self) -> None:
        """R3-2: Whitespace-only `entry_scene: \"   \"` must NOT fall back to `path`, failing with `invalid_plugin_module_scene`."""
        dm = scaffold_mod("ws-scene", config=self.cfg, mode="desktop-module")
        base_m = json.loads(dm.manifest_path.read_text(encoding="utf-8"))
        orig_scene = base_m["modules"][0]["entry_scene"]
        orig_dname = base_m["modules"][0]["display_name"]

        # Positive control: exact empty string "" falls back to path / name
        m_ok = json.loads(json.dumps(base_m))
        m_ok["modules"][0]["entry_scene"] = ""
        m_ok["modules"][0]["path"] = orig_scene
        m_ok["modules"][0]["display_name"] = ""
        m_ok["modules"][0]["name"] = orig_dname
        _write_utf8(dm.manifest_path, json.dumps(m_ok, indent=2) + "\n")
        rep_ok = validate_mod_dir(dm.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertTrue(rep_ok.ok, msg=rep_ok.errors)

        # Negative case 1: whitespace-only entry_scene with valid path -> invalid_plugin_module_scene
        m_ws_scene = json.loads(json.dumps(base_m))
        m_ws_scene["modules"][0]["entry_scene"] = "   "
        m_ws_scene["modules"][0]["path"] = orig_scene
        _write_utf8(dm.manifest_path, json.dumps(m_ws_scene, indent=2) + "\n")
        rep_ws_scene = validate_mod_dir(dm.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertFalse(rep_ws_scene.ok, msg="whitespace-only entry_scene must not fall back to path")
        self.assertTrue(any("invalid_plugin_module_scene" in e for e in rep_ws_scene.errors), msg=rep_ws_scene.errors)

        # Negative case 2: whitespace-only display_name with valid name -> invalid_plugin_modules
        m_ws_disp = json.loads(json.dumps(base_m))
        m_ws_disp["modules"][0]["display_name"] = "   "
        m_ws_disp["modules"][0]["name"] = orig_dname
        _write_utf8(dm.manifest_path, json.dumps(m_ws_disp, indent=2) + "\n")
        rep_ws_disp = validate_mod_dir(dm.target_dir, sdk_dir=self.sdk_dir, runtime_sdk_dir=self.runtime_sdk_dir)
        self.assertFalse(rep_ws_disp.ok, msg="whitespace-only display_name must not fall back to name")
        self.assertTrue(any("invalid_plugin_modules" in e for e in rep_ws_disp.errors), msg=rep_ws_disp.errors)


if __name__ == "__main__":
    unittest.main()
