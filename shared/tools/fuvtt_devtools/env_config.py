"""Workspace environment configuration, sandbox boundary enforcement, and path redaction."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
from typing import Mapping


DEFAULT_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FUS_SOURCE_REF = "origin/codex/v065-unified-20261125"

REDACTED_INSTALL_PLACEHOLDER = "<FUVTT_INSTALL_DIR>"
REDACTED_FUS_REPO_PLACEHOLDER = "<FUS_REPO_DIR>"
REDACTED_GODOT_BIN_PLACEHOLDER = "<GODOT_BIN>"

_KNOWN_ENV_KEYS = (
    "FUVTT_INSTALL_DIR",
    "FUVTT_MODS_SUBDIR",
    "FUS_REPO_DIR",
    "FUS_SOURCE_REF",
    "GODOT_BIN",
    "BUILD_DIR",
    "CACHE_DIR",
)


class ConfigError(ValueError):
    """Raised when configuration is missing, malformed, or violates workspace boundaries."""


def _strip_inline_comment(raw_value: str) -> str:
    """Strip unquoted inline comments preceded by whitespace."""
    for idx, ch in enumerate(raw_value):
        if ch == "#" and (idx == 0 or raw_value[idx - 1].isspace()):
            return raw_value[:idx].rstrip()
    return raw_value.strip()


def parse_dotenv_text(content: str) -> dict[str, str]:
    """Parse `.env` formatted text using only standard library primitives."""
    if content.startswith("\ufeff"):
        content = content.lstrip("\ufeff")

    parsed: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") and "=" in line:
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue

        key, raw_val = line.split("=", 1)
        key = key.strip()
        if not key:
            continue

        val = raw_val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1].strip()
        else:
            val = _strip_inline_comment(val)
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1].strip()

        parsed[key] = val
    return parsed


def parse_dotenv_file(env_file: Path) -> dict[str, str]:
    """Read and parse a `.env` file if it exists."""
    if not env_file.is_file():
        return {}
    try:
        content = env_file.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"环境配置文件 '{env_file}' 不是合法 UTF-8 编码：{exc}") from exc
    if "\x00" in content:
        raise ConfigError(f"环境配置文件 '{env_file}' 包含非法 NUL 字节。")
    return parse_dotenv_text(content)


def _ensure_inside_workspace(target_path: Path, workspace_root: Path, var_name: str) -> Path:
    """Ensure a directory resolves strictly inside workspace_root (not outside and not root itself)."""
    resolved_root = workspace_root.resolve()
    resolved_target = target_path.resolve()
    if not resolved_target.is_relative_to(resolved_root):
        raise ConfigError(
            f"安全边界拦截：{var_name} 解析路径 '{resolved_target}' 越出工作区根目录 '{resolved_root}'。"
        )
    if resolved_target == resolved_root:
        raise ConfigError(
            f"安全边界拦截：{var_name} 不能直接指向工作区根目录 '{resolved_root}'，请指定子目录（如 build 或 .cache）。"
        )
    return resolved_target


def _collect_path_variants(raw_target: Path | str) -> list[str]:
    raw_str = str(raw_target).strip()
    if not raw_str:
        return []

    candidates: list[str] = []
    try:
        candidates.append(str(Path(raw_str).resolve()))
    except OSError:
        pass
    candidates.append(raw_str)

    variants: list[str] = []
    for base in candidates:
        cleaned = base.rstrip("\\/")
        if not cleaned:
            continue
        cleaned_posix = cleaned.replace("\\", "/")
        cleaned_win = cleaned.replace("/", "\\")
        for item in (cleaned, cleaned_posix, cleaned_win):
            if item and item not in variants:
                variants.append(item)
    return variants


def _replace_variants(rendered: str, replacements: list[tuple[str, str]]) -> str:
    """Replace path variants longest-first (case-insensitive on Windows)."""
    sorted_pairs = sorted(replacements, key=lambda pair: len(pair[0]), reverse=True)
    for variant, placeholder in sorted_pairs:
        if not variant:
            continue
        if os.name == "nt":
            lower_rendered = rendered.lower()
            lower_variant = variant.lower()
            start = 0
            pieces: list[str] = []
            while True:
                idx = lower_rendered.find(lower_variant, start)
                if idx == -1:
                    pieces.append(rendered[start:])
                    break
                pieces.append(rendered[start:idx])
                pieces.append(placeholder)
                start = idx + len(variant)
            rendered = "".join(pieces)
        else:
            rendered = rendered.replace(variant, placeholder)
    return rendered


def redact_path(
    text: str | Path,
    install_dir: Path | str | None = None,
    placeholder: str = REDACTED_INSTALL_PLACEHOLDER,
    *,
    fus_repo_dir: Path | str | None = None,
    godot_bin: Path | str | None = None,
) -> str:
    """Replace local external paths (`FUVTT_INSTALL_DIR`, `FUS_REPO_DIR`, `GODOT_BIN`) with placeholders."""
    rendered = str(text)
    replacements: list[tuple[str, str]] = []

    if install_dir is not None and str(install_dir).strip():
        for variant in _collect_path_variants(install_dir):
            replacements.append((variant, placeholder))

    if fus_repo_dir is not None and str(fus_repo_dir).strip():
        for variant in _collect_path_variants(fus_repo_dir):
            replacements.append((variant, REDACTED_FUS_REPO_PLACEHOLDER))

    if godot_bin is not None and str(godot_bin).strip():
        godot_path = Path(str(godot_bin).strip())
        for variant in _collect_path_variants(godot_path):
            replacements.append((variant, REDACTED_GODOT_BIN_PLACEHOLDER))
        # Also redact the parent toolchain directory when paths refer to sibling files next to Godot
        if godot_path.parent and str(godot_path.parent) not in ("", ".", "/", "\\"):
            parent_str = str(godot_path.parent)
            if len(parent_str.rstrip("\\/")) > 3:
                for variant in _collect_path_variants(godot_path.parent):
                    replacements.append((variant, f"{REDACTED_GODOT_BIN_PLACEHOLDER}_DIR"))

    if not replacements:
        return rendered
    return _replace_variants(rendered, replacements)


@dataclass(frozen=True)
class WorkspaceConfig:
    """Resolved workspace configuration with sandbox boundary guarantees."""

    workspace_root: Path
    mods_dir: Path
    sdk_dir: Path
    build_dir: Path
    cache_dir: Path
    fuvtt_install_dir: Path | None = None
    fuvtt_mods_subdir: str | None = None
    fus_repo_dir: Path | None = None
    fus_source_ref: str = DEFAULT_FUS_SOURCE_REF
    godot_bin: Path | None = None
    raw_env: Mapping[str, str] = field(default_factory=dict, repr=False)
    runtime_sdk_dir: Path | None = None

    @property
    def resolved_runtime_sdk_dir(self) -> Path:
        """Resolve `shared/sdk/fu_runtime` path (defaulting relative to `workspace_root`)."""
        if self.runtime_sdk_dir is not None:
            return self.runtime_sdk_dir
        return self.workspace_root / "shared" / "sdk" / "fu_runtime"

    def redact_path(self, text: str | Path) -> str:
        """Redact FUVTT_INSTALL_DIR, FUS_REPO_DIR, and GODOT_BIN from log or status text."""
        return redact_path(
            text,
            self.fuvtt_install_dir,
            fus_repo_dir=self.fus_repo_dir,
            godot_bin=self.godot_bin,
        )

    def resolve_session_plugins_dir(
        self,
        override_dir: Path | str | None = None,
        *,
        platform_name: str | None = None,
        home_dir: Path | None = None,
    ) -> Path:
        """Resolve client `session_plugins` directory with `.env.local` and macOS fallback."""
        if override_dir is not None and str(override_dir).strip():
            return Path(override_dir).expanduser().resolve()

        plat = platform_name or sys.platform
        user_home = (home_dir or Path.home()).expanduser()
        macos_default = user_home / "Library" / "Application Support" / "FuVTT" / "session_plugins"

        if self.fuvtt_mods_subdir:
            sub_path = Path(self.fuvtt_mods_subdir).expanduser()
            if sub_path.is_absolute():
                return sub_path.resolve()
            if self.fuvtt_install_dir is None:
                raise ConfigError(
                    "已配置相对路径 FUVTT_MODS_SUBDIR，但未设置 FUVTT_INSTALL_DIR。"
                    " 请在 .env.local 中填写 FUVTT_INSTALL_DIR，或使用 --target-dir。"
                )
            return (self.fuvtt_install_dir / sub_path).resolve()

        if self.fuvtt_install_dir is not None:
            portable_dir = self.fuvtt_install_dir / "FUS_Data" / "session_plugins"
            if plat == "darwin" and not (self.fuvtt_install_dir / "FUS_Data").exists():
                if macos_default.exists() or self.fuvtt_install_dir.suffix == ".app":
                    return macos_default.resolve()
            return portable_dir.resolve()

        if plat == "darwin":
            return macos_default.resolve()

        raise ConfigError(
            "未配置 FUVTT_INSTALL_DIR。请在工作区根目录 .env.local 中配置客户端安装目录，或通过 --target-dir 指定目标目录。"
        )

    def resolve_client_exe(self, override_exe: Path | str | None = None) -> Path:
        """Resolve path to Fu vtt client executable (`FUS.exe`)."""
        if override_exe is not None and str(override_exe).strip():
            return Path(override_exe).expanduser().resolve()

        if self.fuvtt_install_dir is None:
            raise ConfigError(
                "未配置 FUVTT_INSTALL_DIR。请在 .env.local 中设置客户端安装路径，或通过 --exe-path 指定 FUS.exe。"
            )

        candidates = [
            self.fuvtt_install_dir / "FUS.exe",
            self.fuvtt_install_dir / "FUS.x86_64",
            self.fuvtt_install_dir / "FUS",
        ]
        for cand in candidates:
            if cand.is_file():
                return cand.resolve()
        return candidates[0].resolve()

    def resolve_fus_repo_dir(self, override_repo: Path | str | None = None) -> Path:
        """Resolve read-only official FUS Git repository root."""
        if override_repo is not None and str(override_repo).strip():
            return Path(override_repo).expanduser().resolve()
        if self.fus_repo_dir is None:
            raise ConfigError(
                "未配置 FUS_REPO_DIR。请在 .env.local 中配置官方 FUS 只读源码仓路径，或通过 --fus-repo 指定。"
            )
        return self.fus_repo_dir.resolve()

    def resolve_godot_bin(self, override_bin: Path | str | None = None) -> Path:
        """Resolve Godot console executable path for headless verification (`verify-host`)."""
        if override_bin is not None and str(override_bin).strip():
            return Path(override_bin).expanduser().resolve()
        if self.godot_bin is None:
            raise ConfigError(
                "未配置 GODOT_BIN。请在 .env.local 中配置 Godot 控制台可执行文件路径（*_console.exe），或通过 --godot-bin 指定。"
            )
        return self.godot_bin.resolve()


def _parse_optional_path(raw: str | None) -> Path | None:
    cleaned = (raw or "").strip()
    if not cleaned:
        return None
    return Path(cleaned).expanduser().resolve()


def load_config(
    workspace_root: Path | str | None = None,
    *,
    env_file: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> WorkspaceConfig:
    """Load `.env.local` + environment variables and enforce workspace directory boundaries."""
    ws_root = Path(workspace_root).resolve() if workspace_root is not None else DEFAULT_WORKSPACE_ROOT
    dotenv_path = Path(env_file) if env_file is not None else (ws_root / ".env.local")

    merged: dict[str, str] = parse_dotenv_file(dotenv_path)
    env_source = os.environ if environ is None else environ
    for key in _KNOWN_ENV_KEYS:
        if key in env_source:
            raw_env_val = str(env_source[key]).strip()
            if len(raw_env_val) >= 2 and raw_env_val[0] == raw_env_val[-1] and raw_env_val[0] in ('"', "'"):
                raw_env_val = raw_env_val[1:-1].strip()
            if raw_env_val != "" or key not in merged:
                merged[key] = raw_env_val

    build_raw = merged.get("BUILD_DIR", "").strip() or "build"
    cache_raw = merged.get("CACHE_DIR", "").strip() or ".cache"

    build_candidate = Path(build_raw)
    if not build_candidate.is_absolute():
        build_candidate = ws_root / build_candidate
    build_dir = _ensure_inside_workspace(build_candidate, ws_root, "BUILD_DIR")

    cache_candidate = Path(cache_raw)
    if not cache_candidate.is_absolute():
        cache_candidate = ws_root / cache_candidate
    cache_dir = _ensure_inside_workspace(cache_candidate, ws_root, "CACHE_DIR")

    install_dir = _parse_optional_path(merged.get("FUVTT_INSTALL_DIR"))
    fus_repo_dir = _parse_optional_path(merged.get("FUS_REPO_DIR"))
    godot_bin = _parse_optional_path(merged.get("GODOT_BIN"))

    mods_subdir_raw = merged.get("FUVTT_MODS_SUBDIR", "").strip()
    mods_subdir = mods_subdir_raw if mods_subdir_raw else None

    source_ref_raw = merged.get("FUS_SOURCE_REF", "").strip()
    fus_source_ref = source_ref_raw if source_ref_raw else DEFAULT_FUS_SOURCE_REF

    return WorkspaceConfig(
        workspace_root=ws_root,
        mods_dir=ws_root / "mods",
        sdk_dir=ws_root / "shared" / "sdk" / "fu_sdk",
        build_dir=build_dir,
        cache_dir=cache_dir,
        fuvtt_install_dir=install_dir,
        fuvtt_mods_subdir=mods_subdir,
        fus_repo_dir=fus_repo_dir,
        fus_source_ref=fus_source_ref,
        godot_bin=godot_bin,
        raw_env=merged,
        runtime_sdk_dir=ws_root / "shared" / "sdk" / "fu_runtime",
    )
