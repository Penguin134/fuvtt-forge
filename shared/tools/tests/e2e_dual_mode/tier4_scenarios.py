"""Tier 4: Real-World End-to-End Application & Isolation Scenarios (12 cases: `t4_w1_01`..`t4_w4_03`)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import unittest
import urllib.request

from .assertions import (
    assert_fu_sdk_35_invariance,
    assert_fup_archive_contract,
    assert_fus_repo_clean,
    assert_no_local_paths_in_text,
    assert_parity_clean,
    assert_registry_json_valid,
    assert_zip_archive_contract,
)
from .fixtures import create_desktop_module_fixture, create_world_plugin_fixture
from .harness import (
    TOOLS_DIR,
    WORKSPACE_ROOT,
    CliRunner,
    E2ESession,
    FUSBuildParityRunner,
    FUSShadowMirrorRunner,
    resolve_fus_repo_or_skip,
    resolve_godot_or_skip,
    resolve_wiki_dir,
    run_git_readonly,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Tier4ScenarioTests(unittest.TestCase):
    """12 end-to-end real-world workflow & isolation tests (`t4_w1_01`..`t4_w4_03`)."""

    session: E2ESession
    cli: CliRunner

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = E2ESession(name_prefix="tier4")
        cls.session.setup(require_godot=False)
        cls.cli = CliRunner(cls.session)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.session.cleanup()

    # =========================================================================
    # W1: fus.desktop-module.v1 Full Lifecycle
    # =========================================================================
    def test_t4_w1_01_desktop_module_init_validate_build(self) -> None:
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        self.assertEqual(self.cli.run_isolated(["init", "w1-crit-demo", "--mode", "desktop-module"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["validate", "w1-crit-demo"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["build", "w1-crit-demo"]).returncode, 0)
        zip_path = self.session.build_dir / "w1-crit-demo" / "w1-crit-demo.zip"
        assert_zip_archive_contract(
            self,
            zip_path,
            expected_schema="fus.desktop-module.v1",
            plugin_id="w1_crit_demo",
            expect_sdk=True,
            namespace_prefix="mods/w1_crit_demo",
        )

    def test_t4_w1_02_desktop_module_sync_serve_verify_host(self) -> None:
        godot_bin = resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None and self.session.target_plugins_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "w1-crit-vh", plugin_id="w1_crit_vh")
        self.assertEqual(self.cli.run_isolated(["build", "w1-crit-vh"]).returncode, 0)
        zip_path = self.session.build_dir / "w1-crit-vh" / "w1-crit-vh.zip"
        zip_bytes = zip_path.read_bytes()
        expected_sha = hashlib.sha256(zip_bytes).hexdigest()

        target_dir = self.session.target_plugins_dir / "w1_02"
        self.assertEqual(self.cli.run_isolated(["sync", "w1-crit-vh", "--target-dir", str(target_dir)]).returncode, 0)
        assert_registry_json_valid(self, target_dir / "registry.json", ("w1_crit_vh",))

        with self.cli.isolated_serve() as (port, opener):
            with opener.open(f"http://127.0.0.1:{port}/index.json", timeout=2) as resp:
                idx_data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("w1-crit-vh", {row.get("mod_name") for row in idx_data.get("packages", [])})
            with opener.open(f"http://127.0.0.1:{port}/w1-crit-vh.zip", timeout=2) as r_zip:
                self.assertEqual(r_zip.status, 200)
                self.assertIn("no-store", (r_zip.headers.get("Cache-Control") or "").lower())
                self.assertEqual(r_zip.headers.get("X-Plugin-SHA256"), expected_sha)
                self.assertEqual(r_zip.read(), zip_bytes)

        vh = self.cli.run_isolated(["verify-host", "w1-crit-vh", "--godot-bin", str(godot_bin)], timeout=180)
        self.assertEqual(vh.returncode, 0, f"{vh.stdout}\n{vh.stderr}")

    def test_t4_w1_03_desktop_module_shadow_fus_host_load(self) -> None:
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_desktop_module_fixture(self.session.mods_dir, "w1-crit-host", plugin_id="w1_crit_host")
        self.assertEqual(self.cli.run_isolated(["build", "w1-crit-host"]).returncode, 0)
        zip_path = self.session.build_dir / "w1-crit-host" / "w1-crit-host.zip"

        res = FUSShadowMirrorRunner(self.session).run_host_probe(mode="desktop", zip_pkg=zip_path)
        self.assertEqual(res["returncode"], 0, f"FUS host probe failed:\n{res['stdout']}\n{res['stderr']}")
        self.assertEqual(res["log_errors"], [])
        self.assertIs(res["report"].get("ok"), True, f"Host load report failed: {res['report']}")
        self.assertGreaterEqual(int(res["report"].get("details", {}).get("slot_items_while_enabled", 0)), 1)

    # =========================================================================
    # W2: fus.plugin.v2 Full Lifecycle
    # =========================================================================
    def test_t4_w2_01_world_plugin_init_validate_build_fup(self) -> None:
        resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        self.assertEqual(self.cli.run_isolated(["init", "w2-aura-demo", "--mode", "world-plugin"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["validate", "w2-aura-demo"]).returncode, 0)
        self.assertEqual(self.cli.run_isolated(["build", "w2-aura-demo"]).returncode, 0)
        fup_path = self.session.build_dir / "w2-aura-demo" / "w2-aura-demo.fup"
        assert_fup_archive_contract(self, fup_path, plugin_id="w2_aura_demo")

    def test_t4_w2_02_world_plugin_sync_verify_host_and_parity(self) -> None:
        godot_bin = resolve_godot_or_skip(self.session.cfg)
        assert self.session.mods_dir is not None and self.session.target_plugins_dir is not None and self.session.run_dir is not None
        mod_dir = create_world_plugin_fixture(self.session.mods_dir, "w2-aura-vh", plugin_id="w2_aura_vh")
        self.assertEqual(self.cli.run_isolated(["build", "w2-aura-vh"]).returncode, 0)
        target_dir = self.session.target_plugins_dir / "w2_02"
        self.assertEqual(self.cli.run_isolated(["sync", "w2-aura-vh", "--target-dir", str(target_dir)]).returncode, 0)
        assert_registry_json_valid(self, target_dir / "registry.json", ("w2_aura_vh",))

        vh = self.cli.run_isolated(["verify-host", "w2-aura-vh", "--godot-bin", str(godot_bin)], timeout=180)
        self.assertEqual(vh.returncode, 0, f"{vh.stdout}\n{vh.stderr}")

        parity = FUSBuildParityRunner(self.session).run_build_world_plugin(mod_dir, self.session.run_dir / "w2_parity")
        assert_parity_clean(self, parity)

    def test_t4_w2_03_world_plugin_shadow_fus_host_load(self) -> None:
        assert self.session.mods_dir is not None and self.session.build_dir is not None
        create_world_plugin_fixture(self.session.mods_dir, "w2-aura-host", plugin_id="w2_aura_host")
        self.assertEqual(self.cli.run_isolated(["build", "w2-aura-host"]).returncode, 0)
        fup_path = self.session.build_dir / "w2-aura-host" / "w2-aura-host.fup"

        res = FUSShadowMirrorRunner(self.session).run_host_probe(
            mode="world",
            fup_pkg=fup_path,
            extra_args=("--comp-path=res://external_modules/w2_aura_host/comp_w2_aura_host__emitter.gd",),
        )
        self.assertEqual(res["returncode"], 0, f"FUS host probe failed:\n{res['stdout']}\n{res['stderr']}")
        self.assertEqual(res["log_errors"], [])
        self.assertIs(res["report"].get("ok"), True, f"Host load report failed: {res['report']}")
        self.assertGreaterEqual(int(res["report"].get("details", {}).get("slot_items_while_enabled", 0)), 1)
        self.assertIs(res["report"].get("details", {}).get("component_attached"), True)

    # =========================================================================
    # W3: Dual-Mode Coexistence & Backward Compat
    # =========================================================================
    def test_t4_w3_01_real_repo_templates_validate_build_verify_host_all(self) -> None:
        godot_bin = resolve_godot_or_skip(self.session.cfg)
        expected_templates = ("_template", "sdk-log-console", "_template-desktop-module", "_template-world-plugin")
        for tpl in expected_templates:
            self.assertTrue((WORKSPACE_ROOT / "mods" / tpl / "plugin.json").is_file(), f"Missing repo template: mods/{tpl}")

        v = self.cli.run_real(["validate", "--all", "--include-template"])
        self.assertEqual(v.returncode, 0, f"validate --all failed:\n{v.stdout}\n{v.stderr}")
        for tpl in expected_templates:
            self.assertIn(f"[PASS] {tpl} (", v.stdout, f"Missing validate [PASS] for {tpl}:\n{v.stdout}")

        b = self.cli.run_real(["build", "--all", "--include-template"])
        self.assertEqual(b.returncode, 0, f"build --all failed:\n{b.stdout}\n{b.stderr}")
        for tpl in expected_templates:
            self.assertIn(f"[BUILT] {tpl} ->", b.stdout, f"Missing build [BUILT] for {tpl}:\n{b.stdout}")

        vh = self.cli.run_real(["verify-host", "--all", "--include-template", "--godot-bin", str(godot_bin)], timeout=300)
        self.assertEqual(vh.returncode, 0, f"verify-host --all failed:\n{vh.stdout}\n{vh.stderr}")
        for tpl in expected_templates:
            self.assertIn(f"[PASS] {tpl} (", vh.stdout, f"Missing verify-host [PASS] for {tpl}:\n{vh.stdout}")

    def test_t4_w3_02_tri_schema_coexistence_in_shadow_fus_session_plugins(self) -> None:
        assert self.session.build_dir is not None
        for tpl in ("_template", "_template-desktop-module", "_template-world-plugin"):
            self.assertTrue((WORKSPACE_ROOT / "mods" / tpl / "plugin.json").is_file(), f"Missing repo template: mods/{tpl}")
            b = self.cli.run_real(["build", tpl])
            self.assertEqual(b.returncode, 0, f"build {tpl} failed:\n{b.stdout}\n{b.stderr}")

        v1_zip = self.session.build_dir / "_template" / "_template.zip"
        dm_zip = self.session.build_dir / "_template-desktop-module" / "_template-desktop-module.zip"
        wp_fup = self.session.build_dir / "_template-world-plugin" / "_template-world-plugin.fup"

        res = FUSShadowMirrorRunner(self.session).run_host_probe(
            mode="coexist",
            v1_pkg=v1_zip,
            zip_pkg=dm_zip,
            fup_pkg=wp_fup,
        )
        self.assertEqual(res["returncode"], 0, f"{res['stdout']}\n{res['stderr']}")
        self.assertEqual(res["log_errors"], [])
        self.assertIs(res["report"].get("ok"), True, f"Coexistence report failed: {res['report']}")
        details = res["report"].get("details", {})
        self.assertGreaterEqual(int(details.get("installed_rows", 0)), 3)

        expected_mod_ids: list[str] = []
        for tpl in ("_template-desktop-module", "_template-world-plugin"):
            tpl_manifest = json.loads((WORKSPACE_ROOT / "mods" / tpl / "plugin.json").read_text(encoding="utf-8"))
            mods_arr = tpl_manifest.get("modules") or (
                [tpl_manifest["module"]] if isinstance(tpl_manifest.get("module"), dict) else []
            )
            for mod_entry in mods_arr:
                if isinstance(mod_entry, dict) and mod_entry.get("id"):
                    expected_mod_ids.append(str(mod_entry["id"]))
        catalog_ids = details.get("catalog_ids", [])
        self.assertGreaterEqual(
            len(expected_mod_ids),
            2,
            f"Expected >= 2 module entries across in-world templates, got: {expected_mod_ids}",
        )
        for mid in expected_mod_ids:
            self.assertIn(
                mid,
                catalog_ids,
                f"External module ID {mid!r} missing from DesktopFeatureCatalog catalog_ids={catalog_ids}",
            )

    def test_t4_w3_03_inspect_client_v0065_and_existing_devtools_regression(self) -> None:
        fus_repo = resolve_fus_repo_or_skip(self.session.cfg)
        insp = self.cli.run_real(["inspect-client", "--source", "git", "--fus-repo", str(fus_repo), "--git-ref", "HEAD", "--json"])
        self.assertEqual(insp.returncode, 0, insp.stderr)
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "shared/tools/tests/test_devtools.py", "-q"],
            cwd=str(WORKSPACE_ROOT),
            env=self.session.child_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.assertEqual(proc.returncode, 0, f"test_devtools.py failed:\n{proc.stdout}\n{proc.stderr}")

    # =========================================================================
    # W4: Docs, Wiki & Repo Hygiene Audit
    # =========================================================================
    def test_t4_w4_01_docs_and_wiki_sync_integrity(self) -> None:
        wiki_dir = resolve_wiki_dir()
        if not wiki_dir.is_dir():
            raise unittest.SkipTest("Wiki dir not present")
        repo_docs = [
            WORKSPACE_ROOT / "README.md",
            WORKSPACE_ROOT / "AGENTS.md",
            WORKSPACE_ROOT / "shared" / "sdk" / "README.md",
            WORKSPACE_ROOT / "shared" / "tools" / "README.md",
            *sorted((WORKSPACE_ROOT / "shared" / "docs").glob("*.md")),
        ]
        repo_text = "\n".join(p.read_text(encoding="utf-8") for p in repo_docs)
        for schema in ("fus.session-plugin.v1", "fus.desktop-module.v1", "fus.plugin.v2"):
            self.assertIn(schema, repo_text)

        root_readme_text = (WORKSPACE_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("Quickstart-and-Demo", root_readme_text, "README.md must not link to deleted Quickstart-and-Demo")
        self.assertIn("/wiki/Getting-Started", root_readme_text, "README.md must link to stable /wiki/Getting-Started")
        agents_text = (WORKSPACE_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn(".meta/terminology.md", agents_text, "AGENTS.md must not reference deleted .meta/terminology.md")

        self.assertFalse((wiki_dir / ".meta").exists(), "Wiki must not contain .meta/ directory")
        nested_mds = [
            str(p.relative_to(wiki_dir))
            for p in wiki_dir.rglob("*.md")
            if ".git" not in p.parts and len(p.relative_to(wiki_dir).parts) > 1
        ]
        self.assertEqual(nested_mds, [], f"Wiki .md files must be flat at root: {nested_mds}")

        wiki_files = sorted(wiki_dir.glob("*.md"))
        stems = {p.stem for p in wiki_files}
        self.assertIn("Home", stems)
        self.assertIn("_Sidebar", stems)
        self.assertIn("Guide-Hybrid-Dual-Activation", stems)
        wiki_text = "\n".join(p.read_text(encoding="utf-8") for p in wiki_files)
        for token in ("fus.session-plugin.v1", "fus.desktop-module.v1", "fus.plugin.v2", "sdk_log_console", "mod.sdk_log_console"):
            self.assertIn(token, wiki_text, f"Wiki missing token {token}")
        mediawiki_re = re.compile(r"\[\[([^\]]+)\]\]")
        md_link_re = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
        hardcoded_wiki_re = re.compile(r"https?://github\.com/[^/\s)]+/[^/\s)]+/wiki(?:/[^\s)]*)?", re.IGNORECASE)
        for md in wiki_files:
            in_fence = False
            for line_no, raw_line in enumerate(md.read_text(encoding="utf-8").splitlines(), start=1):
                if raw_line.lstrip(" ").startswith(("```", "~~~")):
                    in_fence = not in_fence
                    continue
                if in_fence:
                    continue
                self.assertIsNone(
                    mediawiki_re.search(raw_line),
                    f"MediaWiki [[...]] link found in {md.name}:L{line_no}",
                )
                self.assertIsNone(
                    hardcoded_wiki_re.search(raw_line),
                    f"Hardcoded GitHub Wiki URL found in {md.name}:L{line_no}",
                )
                for _label, raw_target in md_link_re.findall(raw_line):
                    target = raw_target.strip().split()[0]
                    if target.startswith(("http://", "https://", "mailto:", "#")):
                        continue
                    slug_part = target.split("#", 1)[0]
                    if not slug_part:
                        continue
                    self.assertFalse(
                        slug_part.endswith(".md"),
                        f"Intra-Wiki link '{target}' must not include .md in {md.name}:L{line_no}",
                    )
                    self.assertNotIn(
                        "/",
                        slug_part,
                        f"Intra-Wiki link '{target}' must not contain '/' in {md.name}:L{line_no}",
                    )
                    self.assertIn(
                        slug_part,
                        stems,
                        f"Broken Wiki link '{target}' in {md.name}:L{line_no}",
                    )

    def test_t4_w4_02_path_leak_scan_and_fu_sdk_35_invariance(self) -> None:
        assert_fu_sdk_35_invariance(self, WORKSPACE_ROOT / "shared" / "sdk" / "fu_sdk")
        scan_roots: list[Path] = [
            WORKSPACE_ROOT / "README.md",
            WORKSPACE_ROOT / "AGENTS.md",
            WORKSPACE_ROOT / "shared" / "sdk" / "README.md",
            WORKSPACE_ROOT / "shared" / "sdk" / "AGENTS.md",
            WORKSPACE_ROOT / "shared" / "tools" / "README.md",
            WORKSPACE_ROOT / "shared" / "tools" / "fuvtt_cli.py",
            *sorted((WORKSPACE_ROOT / "shared" / "docs").glob("*.md")),
            *sorted((WORKSPACE_ROOT / "shared" / "sdk" / "fu_runtime").glob("*.gd")),
            *sorted((WORKSPACE_ROOT / "shared" / "sdk" / "fu_runtime").glob("*.json")),
            *sorted((WORKSPACE_ROOT / "shared" / "tools" / "fuvtt_devtools").glob("*.py")),
            *sorted((WORKSPACE_ROOT / "shared" / "tools" / "tests" / "e2e_dual_mode").glob("*.py")),
            *sorted((WORKSPACE_ROOT / "shared" / "tools" / "tests" / "e2e_dual_mode").glob("*.gd")),
        ]
        mods_root = WORKSPACE_ROOT / "mods"
        if mods_root.is_dir():
            for child in sorted(mods_root.iterdir()):
                if child.is_dir() and (child.name == "_template" or child.name.startswith("_template-") or child.name == "sdk-log-console"):
                    for f in sorted(child.rglob("*")):
                        if f.is_file() and f.suffix.lower() in {".gd", ".tscn", ".json", ".md"}:
                            scan_roots.append(f)
        for p in scan_roots:
            if p.is_file():
                assert_no_local_paths_in_text(self, p.read_text(encoding="utf-8"), label=str(p.relative_to(WORKSPACE_ROOT)))
        wiki_dir = resolve_wiki_dir()
        if wiki_dir.is_dir():
            for wp in sorted(wiki_dir.glob("*.md")):
                assert_no_local_paths_in_text(self, wp.read_text(encoding="utf-8"), label=f"wiki/{wp.name}")

    def test_t4_w4_03_strict_repository_isolation_check(self) -> None:
        assert_fus_repo_clean(self, self.session.cfg.fus_repo_dir)
        # Ensure no synthetic test mods remain in real mods/
        for child in (WORKSPACE_ROOT / "mods").iterdir():
            if child.is_dir():
                self.assertFalse(
                    child.name.startswith(("t1-", "t2-", "t3-", "w1-", "w2-", "smoke-")),
                    f"Synthetic test mod leaked into real mods/: {child.name}",
                )
        # Verify `.cache/` and `build/` stay inside workspace
        self.assertTrue(self.session.cfg.build_dir.is_relative_to(WORKSPACE_ROOT.resolve()))
        self.assertTrue(self.session.cfg.cache_dir.is_relative_to(WORKSPACE_ROOT.resolve()))
