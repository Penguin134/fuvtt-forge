"""Isolated opaque-box E2E harness for `fu_sdk` modular plugins, R2/R3 APIs, R5 CLI, and R6 console mod."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import unittest
import uuid
from typing import Any, Mapping, Sequence


TOOLS_DIR = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = TOOLS_DIR.parents[1]
TEST_TMP_ROOT = WORKSPACE_ROOT / ".cache" / "test_tmp" / "e2e_sdk"
PROBE_GD_SOURCE = Path(__file__).resolve().with_name("e2e_sdk_probe.gd")

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from fuvtt_devtools.deployer import safe_extract_zip  # noqa: E402
from fuvtt_devtools.env_config import WorkspaceConfig, load_config  # noqa: E402
from fuvtt_devtools.host_verifier import (  # noqa: E402
    PROBE_PROJECT_GODOT,
    _INWORLD_HOST_SHIMS,
    _render_global_script_class_cache,
    analyze_godot_logs,
)
from fuvtt_devtools.packager import BuildArtifact, build_mod  # noqa: E402
from fuvtt_devtools.validator import INWORLD_SCHEMAS, validate_mod_dir, validate_zip_archive  # noqa: E402


_CASE_START_RE = re.compile(r"^=== E2E_CASE_START (\S+) ===\s*$")
_CASE_END_RE = re.compile(r"^=== E2E_CASE_END (\S+) ===\s*$")

# Authoritative catalog constants from PROJECT.md / <FUS_REPO_DIR> DesktopFeatureCatalog
CORE_MODULE_IDS: tuple[str, ...] = (
    "feature_networking",
    "feature_component_sync",
    "feature_debug_hooks",
    "feature_component_library",
    "feature_edit_mode",
    "feature_floor_system",
    "feature_layer_stack",
    "feature_obstacle_authoring",
    "feature_entity_library",
)

STATELESS_CORE_MODULE_IDS: tuple[str, ...] = (
    "feature_networking",
    "feature_component_sync",
    "feature_debug_hooks",
    "feature_component_library",
)

CORE_PLUGIN_SDK_IDS: tuple[str, ...] = (
    "feature_edit_mode",
    "feature_floor_system",
    "feature_layer_stack",
    "feature_obstacle_authoring",
    "feature_entity_library",
)

STATELESS_OPTIONAL_MODULE_IDS: tuple[str, ...] = (
    "room_chat",
    "player_cursors",
    "map_fog_editor",
    "detached_sidebar",
)

OPTIONAL_PLUGIN_SDK_IDS: tuple[str, ...] = (
    "scene_box",
    "portal",
    "grid_alignment",
    "simple_fog",
    "image_flip",
    "drag_movement",
    "drawing",
    "areas",
    "checklist",
    "resource_pool",
    "character_roster",
    "backpack",
    "follow",
    "candidate_initiative",
    "dice",
    "campaign_time",
    "dnd_opportunity",
)

OPTIONAL_MODULE_IDS: tuple[str, ...] = STATELESS_OPTIONAL_MODULE_IDS + OPTIONAL_PLUGIN_SDK_IDS
CANDIDATE_MODULE_IDS: tuple[str, ...] = ("entity_notes", "music_board", "module_example")
PLAYTEST_BLOCKED_MODULE_IDS: tuple[str, ...] = ("campaign_time", "dnd_opportunity")

ALL_PLUGIN_SDK_IDS: tuple[str, ...] = (
    CORE_PLUGIN_SDK_IDS + OPTIONAL_PLUGIN_SDK_IDS + ("entity_notes",)
)


@dataclass(frozen=True)
class GdVector2:
    x: float
    y: float


@dataclass(frozen=True)
class GdColor:
    r: float
    g: float
    b: float
    a: float


@dataclass(frozen=True)
class CliResult:
    returncode: int
    stdout: str
    stderr: str
    args: list[str]


@dataclass
class SdkProbeCaseSpec:
    case_id: str
    op: str
    params: Mapping[str, Any] = field(default_factory=dict)
    enabled_modules: Sequence[str] = ()
    disabled_policy: str = "preserve"
    cancel_policy: str = "never"
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class SdkProbeCaseResult:
    case_id: str
    completed: bool
    crashed_or_timed_out: bool
    ok: bool
    data: dict[str, Any]
    gd_check_failures: list[str]
    log_errors: list[str]
    exit_code: int = 0
    timed_out: bool = False


@dataclass
class SdkBatchSummary:
    loaded_scripts: list[str]
    compile_failures: list[str]
    sdk_loaded: bool
    sdk_version: str
    global_log_errors: list[str]
    results: dict[str, SdkProbeCaseResult]


def _decode_float_token(v: Any) -> Any:
    if v == "__NAN__":
        return float("nan")
    if v == "__INF__":
        return float("inf")
    if v == "__-INF__":
        return float("-inf")
    return v


def decode_gd_json(val: Any) -> Any:
    """Recursively decode typed Godot JSON wrappers emitted by `e2e_sdk_probe.gd`."""
    if isinstance(val, str):
        return _decode_float_token(val)
    if isinstance(val, list):
        return [decode_gd_json(x) for x in val]
    if isinstance(val, dict):
        gd_type = val.get("__gd_type")
        if gd_type == "Vector2":
            return GdVector2(float(_decode_float_token(val["x"])), float(_decode_float_token(val["y"])))
        if gd_type == "Color":
            return GdColor(
                float(_decode_float_token(val["r"])),
                float(_decode_float_token(val["g"])),
                float(_decode_float_token(val["b"])),
                float(_decode_float_token(val["a"])),
            )
        if gd_type == "PackedVector2Array":
            pts = val.get("points", [])
            return [GdVector2(float(_decode_float_token(p[0])), float(_decode_float_token(p[1]))) for p in pts]
        if gd_type == "PackedFloat32Array":
            return [float(_decode_float_token(v)) for v in val.get("values", [])]
        if gd_type == "PackedInt32Array":
            return [int(v) for v in val.get("values", [])]
        if gd_type == "PackedByteArray":
            return bytes(int(b) & 0xFF for b in val.get("bytes", []))
        return {k: decode_gd_json(v) for k, v in val.items()}
    return val


def gd_vec2(x: float, y: float) -> dict[str, Any]:
    return {
        "__gd_type": "Vector2",
        "x": encode_special_inputs(x),
        "y": encode_special_inputs(y),
    }


def gd_color(r: float, g: float, b: float, a: float = 1.0) -> dict[str, Any]:
    return {
        "__gd_type": "Color",
        "r": encode_special_inputs(r),
        "g": encode_special_inputs(g),
        "b": encode_special_inputs(b),
        "a": encode_special_inputs(a),
    }


def gd_packed_vec2(points: Sequence[Sequence[float]]) -> dict[str, Any]:
    return {
        "__gd_type": "PackedVector2Array",
        "points": [[encode_special_inputs(p[0]), encode_special_inputs(p[1])] for p in points],
    }


def gd_packed_f32(values: Sequence[float]) -> dict[str, Any]:
    return {
        "__gd_type": "PackedFloat32Array",
        "values": [encode_special_inputs(v) for v in values],
    }


def gd_packed_i32(values: Sequence[int]) -> dict[str, Any]:
    return {
        "__gd_type": "PackedInt32Array",
        "values": [int(v) for v in values],
    }


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


def resolve_godot_or_skip(test_case: unittest.TestCase | type[unittest.TestCase], cfg: WorkspaceConfig) -> Path:
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


def run_fuvtt_cli(
    args: Sequence[str],
    *,
    build_dir: Path,
    cache_dir: Path,
    config: WorkspaceConfig | None = None,
    timeout: int = 180,
) -> CliResult:
    """Invoke `shared/tools/fuvtt_cli.py` in subprocess with workspace-isolated `BUILD_DIR` & `CACHE_DIR`."""
    cfg = config or load_workspace_config()
    rel_build = build_dir.resolve().relative_to(WORKSPACE_ROOT.resolve()).as_posix()
    rel_cache = cache_dir.resolve().relative_to(WORKSPACE_ROOT.resolve()).as_posix()

    env = dict(os.environ)
    env["BUILD_DIR"] = rel_build
    env["CACHE_DIR"] = rel_cache
    env["PYTHONUTF8"] = "1"
    env["GODOT_SILENCE_ROOT_WARNING"] = "1"

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
    )


def run_fuvtt_cli_isolated_mods(
    args: Sequence[str],
    *,
    iso_cfg: WorkspaceConfig,
    timeout: int = 180,
) -> CliResult:
    """Run `fuvtt_cli.main(..., config=iso_cfg)` in an isolated subprocess without touching real `mods/`."""
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
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["GODOT_SILENCE_ROOT_WARNING"] = "1"
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
    )


def run_git_readonly(args: Sequence[str], *, repo_dir: Path | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    """Run strictly read-only git inspection commands (`status`, `ls-files`, `check-ignore`, `rev-parse`)."""
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


def is_git_ignored(rel_path: str) -> bool:
    proc = run_git_readonly(["check-ignore", "-q", rel_path])
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    raise RuntimeError(f"git check-ignore failed ({proc.returncode}): {proc.stderr}")


def list_git_tracked(rel_dir: str) -> list[str]:
    proc = run_git_readonly(["ls-files", "--", rel_dir])
    if proc.returncode != 0:
        raise RuntimeError(f"git ls-files failed ({proc.returncode}): {proc.stderr}")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


class E2ESession:
    """Manages an isolated `.cache/test_tmp/e2e_sdk/<run_id>/` workspace."""

    def __init__(self, name_prefix: str = "run", config: WorkspaceConfig | None = None) -> None:
        self.cfg = config or load_workspace_config()
        self.name_prefix = name_prefix
        self.run_dir: Path | None = None
        self.build_dir: Path | None = None
        self.cache_dir: Path | None = None
        self.mods_dir: Path | None = None
        self.probe_project: Path | None = None
        self.pkg_dir: Path | None = None
        self.env_dirs: dict[str, Path] = {}
        self.godot_bin: Path | None = None

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
        self.pkg_dir = self.probe_project / "pkg"
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
            *self.env_dirs.values(),
        ):
            d.mkdir(parents=True, exist_ok=True)

        src_tpl = self.cfg.mods_dir / "_template"
        dst_tpl = self.mods_dir / "_template"
        if src_tpl.is_dir() and not dst_tpl.exists():
            shutil.copytree(src_tpl, dst_tpl)
            _clear_readonly_tree(dst_tpl)

        if require_godot:
            self.godot_bin = resolve_godot_or_skip(unittest.TestCase, self.cfg)

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


class GodotBatchProbe:
    """Drives `e2e_sdk_probe.gd` against packaged ZIP `res://pkg/lib/fu_sdk/v1.gd` with bisection."""

    def __init__(self, session: E2ESession) -> None:
        self.session = session
        self.artifact: BuildArtifact | None = None
        self.godot_bin: Path | None = None

    def prepare_from_mod(self, mod_name: str = "_template", *, use_real_mods: bool = True) -> BuildArtifact:
        assert self.session.build_dir is not None and self.session.cache_dir is not None
        assert self.session.probe_project is not None and self.session.pkg_dir is not None
        self.godot_bin = self.session.godot_bin or resolve_godot_or_skip(unittest.TestCase, self.session.cfg)

        mods_dir = self.session.cfg.mods_dir if use_real_mods else self.session.mods_dir
        assert mods_dir is not None
        iso_cfg = self.session.make_isolated_config(mods_dir=mods_dir)
        v_rep = validate_mod_dir(iso_cfg.mods_dir / mod_name, mod_name=mod_name, sdk_dir=iso_cfg.sdk_dir)
        if not v_rep.ok:
            raise AssertionError(f"Static validation failed for {mod_name}: {v_rep.errors}")
        artifact = build_mod(mod_name, config=iso_cfg, bump_dev=False)
        zip_errs = validate_zip_archive(artifact.zip_path)
        if zip_errs:
            raise AssertionError(f"ZIP validation failed for {artifact.zip_path}: {zip_errs}")
        self.artifact = artifact

        if self.session.pkg_dir.exists():
            _rmtree_force(self.session.pkg_dir)
        safe_extract_zip(artifact.zip_path, self.session.pkg_dir)

        shims_dir = self.session.probe_project / "_host_shims"
        godot_dir = self.session.probe_project / ".godot"
        if artifact.schema in INWORLD_SCHEMAS:
            shims_dir.mkdir(parents=True, exist_ok=True)
            godot_dir.mkdir(parents=True, exist_ok=True)
            for fname, (_, code) in _INWORLD_HOST_SHIMS.items():
                write_utf8_no_bom_lf(shims_dir / fname, code)
            write_utf8_no_bom_lf(
                godot_dir / "global_script_class_cache.cfg",
                _render_global_script_class_cache(),
            )
        else:
            if shims_dir.exists():
                _rmtree_force(shims_dir)
            cache_cfg = godot_dir / "global_script_class_cache.cfg"
            if cache_cfg.exists():
                cache_cfg.unlink()

        project_godot = PROBE_PROJECT_GODOT.replace(
            'config/name="FuVTT_VerifyHostProbe"', 'config/name="FuVTT_E2ESdkProbe"'
        )
        write_utf8_no_bom_lf(self.session.probe_project / "project.godot", project_godot)
        write_utf8_no_bom_lf(
            self.session.probe_project / "e2e_sdk_probe.gd",
            PROBE_GD_SOURCE.read_text(encoding="utf-8"),
        )
        return artifact

    def _invoke_godot(
        self,
        sub_id: str,
        cases: list[SdkProbeCaseSpec],
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
            payload_cases.append(
                {
                    "case_id": c.case_id,
                    "op": c.op,
                    "params": encode_special_inputs(dict(c.params)),
                    "enabled_modules": list(c.enabled_modules),
                    "disabled_policy": c.disabled_policy,
                    "cancel_policy": c.cancel_policy,
                    "options": encode_special_inputs(dict(c.options)),
                    "case_dir": c_dir.as_posix(),
                }
            )

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
            "res://e2e_sdk_probe.gd",
            "--",
            "--pkg-root=res://pkg",
            f"--batch-in={batch_in_path.as_posix()}",
            f"--batch-out={batch_out_path.as_posix()}",
        ]

        child_env = dict(os.environ)
        child_env["APPDATA"] = str(self.session.env_dirs["appdata"])
        child_env["LOCALAPPDATA"] = str(self.session.env_dirs["localappdata"])
        child_env["TEMP"] = str(self.session.env_dirs["temp"])
        child_env["TMP"] = str(self.session.env_dirs["temp"])
        child_env["GODOT_SILENCE_ROOT_WARNING"] = "1"

        timed_out = False
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.session.probe_project),
                env=child_env,
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
            stdout_text = (
                exc.stdout
                if isinstance(exc.stdout, str)
                else (exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
            )
            stderr_text = (
                exc.stderr
                if isinstance(exc.stderr, str)
                else (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")
            )

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
        cases: list[SdkProbeCaseSpec],
        *,
        timeout_seconds: int = 120,
        _sub_counter: list[int] | None = None,
    ) -> SdkBatchSummary:
        """Execute cases in one headless Godot invocation; bisect on crash/timeout."""
        counter = _sub_counter if _sub_counter is not None else [0]
        sub_id = f"b{counter[0]:03d}"
        counter[0] += 1

        exit_code, timed_out, summary, stdout_text, stderr_text, godot_log_text, out_dir = self._invoke_godot(
            sub_id, cases, timeout_seconds=timeout_seconds
        )
        per_case_errors, global_errors = _attribute_logs_by_case(stdout_text, godot_log_text, stderr_text)

        loaded_scripts = [str(x) for x in summary.get("loaded_scripts", [])]
        compile_failures = [str(x) for x in summary.get("compile_failures", [])]
        sdk_loaded = bool(summary.get("sdk_loaded", False))
        sdk_version = str(summary.get("sdk_version", ""))

        results: dict[str, SdkProbeCaseResult] = {}
        incomplete: list[SdkProbeCaseSpec] = []

        for c in cases:
            out_file = out_dir / f"{c.case_id}.json"
            if out_file.is_file() and not timed_out:
                raw_payload = json.loads(out_file.read_text(encoding="utf-8-sig"))
                decoded = decode_gd_json(raw_payload)
                results[c.case_id] = SdkProbeCaseResult(
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
                    sub_res = self.run_batch(half, timeout_seconds=timeout_seconds, _sub_counter=counter)
                    results.update(sub_res.results)
                    if not loaded_scripts and sub_res.loaded_scripts:
                        loaded_scripts = sub_res.loaded_scripts
                    compile_failures.extend(x for x in sub_res.compile_failures if x not in compile_failures)
                    sdk_loaded = sdk_loaded or sub_res.sdk_loaded
                    if not sdk_version and sub_res.sdk_version:
                        sdk_version = sub_res.sdk_version
                    global_errors.extend(x for x in sub_res.global_log_errors if x not in global_errors)
            else:
                c = incomplete[0]
                c_errs = list(per_case_errors.get(c.case_id, []))
                c_errs.extend(x for x in global_errors if x not in c_errs)
                results[c.case_id] = SdkProbeCaseResult(
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

        return SdkBatchSummary(
            loaded_scripts=loaded_scripts,
            compile_failures=compile_failures,
            sdk_loaded=sdk_loaded,
            sdk_version=sdk_version,
            global_log_errors=global_errors,
            results=results,
        )
