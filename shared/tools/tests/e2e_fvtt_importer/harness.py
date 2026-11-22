"""Opaque-box E2E execution harness for `fvtt-world-importer`.

Builds and validates the packaged plugin ZIP via `fuvtt_devtools`, extracts it into
an isolated probe workspace inside `.cache/test_tmp/e2e_fvtt_importer/`, drives
headless Godot 4.8-beta1 Mono via `e2e_probe.gd`, attributes logs per case, and
automatically bisects crashed/aborted batches.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
import uuid
from typing import Any, Mapping


TOOLS_DIR = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = TOOLS_DIR.parents[1]
TEST_TMP_ROOT = WORKSPACE_ROOT / ".cache" / "test_tmp" / "e2e_fvtt_importer"
PROBE_GD_SOURCE = Path(__file__).resolve().with_name("e2e_probe.gd")

if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from fuvtt_devtools.deployer import safe_extract_zip  # noqa: E402
from fuvtt_devtools.env_config import WorkspaceConfig, load_config  # noqa: E402
from fuvtt_devtools.host_verifier import PROBE_PROJECT_GODOT, analyze_godot_logs  # noqa: E402
from fuvtt_devtools.packager import BuildArtifact, build_mod  # noqa: E402
from fuvtt_devtools.validator import validate_mod_dir, validate_zip_archive  # noqa: E402


MOD_NAME = "fvtt-world-importer"
_CASE_START_RE = re.compile(r"^=== E2E_CASE_START (\S+) ===\s*$")
_CASE_END_RE = re.compile(r"^=== E2E_CASE_END (\S+) ===\s*$")


class GodotUnavailableError(RuntimeError):
    """Raised when GODOT_BIN is missing or unexecutable."""


@dataclass(frozen=True)
class GdVector2:
    x: float
    y: float

    def __getitem__(self, idx: int) -> float:
        if idx == 0:
            return self.x
        if idx == 1:
            return self.y
        raise IndexError(idx)

    def __iter__(self):
        yield self.x
        yield self.y


@dataclass(frozen=True)
class GdVector2i:
    x: int
    y: int


@dataclass(frozen=True)
class GdRect2:
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class GdColor:
    r: float
    g: float
    b: float
    a: float


@dataclass(frozen=True)
class GdPackedVector2ArraySummary:
    size: int
    all_finite: bool
    sample: list[list[float]]


def _decode_float_token(v: Any) -> Any:
    if v == "__NAN__":
        return float("nan")
    if v == "__INF__":
        return float("inf")
    if v == "__-INF__":
        return float("-inf")
    return v


def decode_gd_json(val: Any) -> Any:
    """Recursively decode typed Godot JSON wrappers emitted by `e2e_probe.gd`."""
    if isinstance(val, str):
        return _decode_float_token(val)
    if isinstance(val, list):
        return [decode_gd_json(x) for x in val]
    if isinstance(val, dict):
        gd_type = val.get("__gd_type")
        if gd_type == "Vector2":
            return GdVector2(float(_decode_float_token(val["x"])), float(_decode_float_token(val["y"])))
        if gd_type == "Vector2i":
            return GdVector2i(int(val["x"]), int(val["y"]))
        if gd_type == "Rect2":
            return GdRect2(
                float(_decode_float_token(val["x"])),
                float(_decode_float_token(val["y"])),
                float(_decode_float_token(val["w"])),
                float(_decode_float_token(val["h"])),
            )
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
        if gd_type == "PackedVector2Array_summary":
            return GdPackedVector2ArraySummary(
                size=int(val.get("size", 0)),
                all_finite=bool(val.get("all_finite", False)),
                sample=[[float(_decode_float_token(c)) for c in pt] for pt in val.get("sample", [])],
            )
        return {k: decode_gd_json(v) for k, v in val.items()}
    return val


def encode_special_inputs(val: Any) -> Any:
    """Encode Python NaN/Inf floats into tagged dicts so JSON stays RFC-8259 strict."""
    if isinstance(val, float):
        if math.isnan(val):
            return {"__gd_type": "float", "value": "NaN"}
        if math.isinf(val):
            return {"__gd_type": "float", "value": "Inf" if val > 0 else "-Inf"}
        return val
    if isinstance(val, list):
        return [encode_special_inputs(x) for x in val]
    if isinstance(val, dict):
        return {str(k): encode_special_inputs(v) for k, v in val.items()}
    return val


def _write_utf8_no_bom_lf(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cleaned = text.lstrip("\ufeff").replace("\r\n", "\n")
    path.write_bytes(cleaned.encode("utf-8"))


@dataclass
class ProbeCaseSpec:
    case_id: str
    sample_path: str
    options: Mapping[str, Any] = field(default_factory=dict)
    run_inspect: bool = True
    run_prepare: bool = True
    cancel_policy: str = "never"
    archive_policy: str = "mock_ok"
    expected_sha256: str = ""
    settings: Mapping[str, Any] = field(default_factory=dict)
    max_vertex_dump: int = 4096
    skip_deep_diff: bool = False


@dataclass
class ProbeCaseResult:
    case_id: str
    completed: bool
    crashed_or_timed_out: bool
    inspect_result: dict[str, Any] | None
    prepare_result: dict[str, Any] | None
    inspect_ms: float
    prepare_ms: float
    prepare_meta: dict[str, Any]
    host_trace: dict[str, Any]
    gd_check_failures: list[str]
    log_errors: list[str]
    exit_code: int = 0
    timed_out: bool = False


@dataclass
class BatchExecutionSummary:
    loaded_scripts: list[str]
    compile_failures: list[str]
    entry_valid: bool
    global_log_errors: list[str]
    results: dict[str, ProbeCaseResult]


def build_and_validate_plugin(config: WorkspaceConfig | None = None) -> tuple[WorkspaceConfig, BuildArtifact]:
    """Validate `mods/fvtt-world-importer/`, build packaged ZIP, and validate the ZIP."""
    cfg = config or load_config(WORKSPACE_ROOT)
    mod_dir = cfg.mods_dir / MOD_NAME
    v_report = validate_mod_dir(mod_dir, mod_name=MOD_NAME, sdk_dir=cfg.sdk_dir)
    if not v_report.ok:
        raise AssertionError(f"Static validation failed for {MOD_NAME}: {v_report.errors}")
    artifact = build_mod(MOD_NAME, config=cfg, bump_dev=False)
    zip_errors = validate_zip_archive(artifact.zip_path)
    if zip_errors:
        raise AssertionError(f"ZIP validation failed for {artifact.zip_path}: {zip_errors}")
    return cfg, artifact


def resolve_godot_or_skip(test_case: unittest.TestCase | type[unittest.TestCase], cfg: WorkspaceConfig) -> Path:
    """Resolve `GODOT_BIN`; fail loudly if FUVTT_E2E_REQUIRE_GODOT=1, else skipTest."""
    require = os.environ.get("FUVTT_E2E_REQUIRE_GODOT") == "1"
    try:
        godot_bin = cfg.resolve_godot_bin()
    except Exception as exc:
        if require:
            raise AssertionError(f"FUVTT_E2E_REQUIRE_GODOT=1 but GODOT_BIN resolution failed: {exc}") from exc
        raise unittest.SkipTest(f"GODOT_BIN unavailable: {exc}") from exc

    if not godot_bin.is_file():
        msg = f"GODOT_BIN not found: {cfg.redact_path(godot_bin)}"
        if require:
            raise AssertionError(msg)
        raise unittest.SkipTest(msg)
    return godot_bin


def _attribute_logs_by_case(stdout_text: str, godot_log_text: str, stderr_text: str) -> tuple[dict[str, list[str]], list[str]]:
    """Split log lines between `=== E2E_CASE_START/END <id> ===` markers per case."""
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


class ProbeSession:
    """Manages an isolated `.cache/test_tmp/e2e_fvtt_importer/<run_id>/` workspace."""

    def __init__(self, name_prefix: str = "run", config: WorkspaceConfig | None = None) -> None:
        self.cfg = config or load_config(WORKSPACE_ROOT)
        self.name_prefix = name_prefix
        self.run_dir: Path | None = None
        self.fixture_dir: Path | None = None
        self.probe_project: Path | None = None
        self.pkg_dir: Path | None = None
        self.env_dirs: dict[str, Path] = {}
        self.artifact: BuildArtifact | None = None
        self.godot_bin: Path | None = None

    def setup(self, *, require_godot: bool = True) -> None:
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.run_dir = (TEST_TMP_ROOT / f"{self.name_prefix}_{stamp}_{uuid.uuid4().hex[:8]}").resolve()
        if not self.run_dir.is_relative_to(WORKSPACE_ROOT.resolve()):
            raise RuntimeError(f"Sandbox violation: run_dir outside workspace: {self.run_dir}")

        self.fixture_dir = self.run_dir / "fixtures"
        self.probe_project = self.run_dir / "probe_project"
        self.pkg_dir = self.probe_project / "pkg"
        env_root = self.run_dir / "isolated_env"
        self.env_dirs = {
            "appdata": env_root / "appdata",
            "localappdata": env_root / "localappdata",
            "temp": env_root / "temp",
        }
        for d in (self.fixture_dir, self.probe_project, *self.env_dirs.values()):
            d.mkdir(parents=True, exist_ok=True)

        self.cfg, self.artifact = build_and_validate_plugin(self.cfg)
        safe_extract_zip(self.artifact.zip_path, self.pkg_dir)

        project_godot = PROBE_PROJECT_GODOT.replace('config/name="FuVTT_VerifyHostProbe"', 'config/name="FuVTT_E2EProbe"')
        _write_utf8_no_bom_lf(self.probe_project / "project.godot", project_godot)
        probe_src = PROBE_GD_SOURCE.read_text(encoding="utf-8")
        _write_utf8_no_bom_lf(self.probe_project / "e2e_probe.gd", probe_src)

        if require_godot:
            self.godot_bin = resolve_godot_or_skip(unittest.TestCase, self.cfg)

    def cleanup(self) -> None:
        if os.environ.get("FUVTT_E2E_KEEP_EVIDENCE") == "1":
            return
        if self.run_dir is None or not self.run_dir.exists():
            return
        try:
            shutil.rmtree(self.run_dir)
            return
        except OSError:
            pass
        for dirpath, dirnames, filenames in os.walk(self.run_dir, topdown=False, followlinks=False):
            dp = Path(dirpath)
            for fname in filenames:
                fp = dp / fname
                try:
                    fp.chmod(0o666)
                    fp.unlink(missing_ok=True)
                except OSError:
                    pass
            for dname in dirnames:
                sub = dp / dname
                try:
                    sub.chmod(0o777)
                    sub.rmdir()
                except OSError:
                    pass
        try:
            self.run_dir.chmod(0o777)
            self.run_dir.rmdir()
        except OSError:
            pass

    def _invoke_godot(
        self,
        sub_id: str,
        cases: list[ProbeCaseSpec],
        *,
        timeout_seconds: int,
    ) -> tuple[int, bool, dict[str, Any], str, str, str, Path]:
        assert self.run_dir is not None and self.probe_project is not None and self.godot_bin is not None
        batch_dir = self.run_dir / "batches" / sub_id
        out_dir = batch_dir / "out"
        cases_dir = batch_dir / "cases"
        out_dir.mkdir(parents=True, exist_ok=True)
        cases_dir.mkdir(parents=True, exist_ok=True)

        payload_cases: list[dict[str, Any]] = []
        for c in cases:
            c_dir = cases_dir / c.case_id
            cache_dir = c_dir / "cache"
            dest_dir = c_dir / "destination"
            cache_dir.mkdir(parents=True, exist_ok=True)
            dest_dir.mkdir(parents=True, exist_ok=True)
            payload_cases.append(
                {
                    "case_id": c.case_id,
                    "sample_path": c.sample_path,
                    "options": encode_special_inputs(dict(c.options)),
                    "run_inspect": c.run_inspect,
                    "run_prepare": c.run_prepare,
                    "cancel_policy": c.cancel_policy,
                    "archive_policy": c.archive_policy,
                    "expected_sha256": c.expected_sha256,
                    "settings": encode_special_inputs(dict(c.settings)),
                    "cache_dir": cache_dir.as_posix(),
                    "destination_dir": dest_dir.as_posix(),
                    "max_vertex_dump": c.max_vertex_dump,
                    "skip_deep_diff": c.skip_deep_diff,
                }
            )

        batch_in_path = batch_dir / "batch_in.json"
        batch_out_path = batch_dir / "batch_out.json"
        godot_log_path = batch_dir / "godot.log"
        _write_utf8_no_bom_lf(
            batch_in_path,
            json.dumps({"out_dir": out_dir.as_posix(), "cases": payload_cases}, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        )

        cmd = [
            str(self.godot_bin),
            "--headless",
            "--quit",
            "--path",
            str(self.probe_project),
            "--log-file",
            str(godot_log_path),
            "--script",
            "res://e2e_probe.gd",
            "--",
            "--pkg-root=res://pkg",
            f"--batch-in={batch_in_path.as_posix()}",
            f"--batch-out={batch_out_path.as_posix()}",
        ]

        child_env = dict(os.environ)
        child_env["APPDATA"] = str(self.env_dirs["appdata"])
        child_env["LOCALAPPDATA"] = str(self.env_dirs["localappdata"])
        child_env["TEMP"] = str(self.env_dirs["temp"])
        child_env["TMP"] = str(self.env_dirs["temp"])
        child_env["GODOT_SILENCE_ROOT_WARNING"] = "1"

        timed_out = False
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.probe_project),
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
            stdout_text = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
            stderr_text = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")

        _write_utf8_no_bom_lf(batch_dir / "stdout.log", stdout_text)
        _write_utf8_no_bom_lf(batch_dir / "stderr.log", stderr_text)
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
    ) -> BatchExecutionSummary:
        """Run cases in one Godot invocation; automatically bisect on mid-batch crash/abort."""
        counter = _sub_counter if _sub_counter is not None else [0]
        sub_id = f"b{counter[0]:03d}"
        counter[0] += 1

        exit_code, timed_out, summary, stdout_text, stderr_text, godot_log_text, out_dir = self._invoke_godot(
            sub_id, cases, timeout_seconds=timeout_seconds
        )
        per_case_errors, global_errors = _attribute_logs_by_case(stdout_text, godot_log_text, stderr_text)

        loaded_scripts = [str(x) for x in summary.get("loaded_scripts", [])]
        compile_failures = [str(x) for x in summary.get("compile_failures", [])]
        entry_valid = bool(summary.get("entry_valid", False))

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
                    inspect_result=decoded.get("inspect_result"),
                    prepare_result=decoded.get("prepare_result"),
                    inspect_ms=float(decoded.get("inspect_ms", 0.0)),
                    prepare_ms=float(decoded.get("prepare_ms", 0.0)),
                    prepare_meta=decoded.get("prepare_meta", {}),
                    host_trace=decoded.get("host_trace", {}),
                    gd_check_failures=[str(x) for x in decoded.get("gd_check_failures", [])],
                    log_errors=per_case_errors.get(c.case_id, []),
                    exit_code=exit_code,
                    timed_out=False,
                )
            else:
                incomplete.append(c)

        # Bisection fallback if batch aborted/timed out or exited non-zero with missing outputs
        if incomplete:
            if len(cases) > 1:
                mid = max(1, len(incomplete) // 2)
                left = incomplete[:mid]
                right = incomplete[mid:]
                for half in (left, right):
                    if not half:
                        continue
                    sub_res = self.run_batch(half, timeout_seconds=timeout_seconds, _sub_counter=counter)
                    results.update(sub_res.results)
                    if not loaded_scripts and sub_res.loaded_scripts:
                        loaded_scripts = sub_res.loaded_scripts
                    compile_failures.extend(x for x in sub_res.compile_failures if x not in compile_failures)
                    entry_valid = entry_valid or sub_res.entry_valid
                    global_errors.extend(x for x in sub_res.global_log_errors if x not in global_errors)
            else:
                c = incomplete[0]
                c_errs = list(per_case_errors.get(c.case_id, []))
                c_errs.extend(x for x in global_errors if x not in c_errs)
                results[c.case_id] = ProbeCaseResult(
                    case_id=c.case_id,
                    completed=False,
                    crashed_or_timed_out=True,
                    inspect_result=None,
                    prepare_result=None,
                    inspect_ms=0.0,
                    prepare_ms=0.0,
                    prepare_meta={},
                    host_trace={},
                    gd_check_failures=[],
                    log_errors=c_errs,
                    exit_code=exit_code,
                    timed_out=timed_out,
                )

        return BatchExecutionSummary(
            loaded_scripts=loaded_scripts,
            compile_failures=compile_failures,
            entry_valid=entry_valid,
            global_log_errors=global_errors,
            results=results,
        )
