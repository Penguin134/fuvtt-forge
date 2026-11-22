"""Deterministic plugin packager with automatic `fu_sdk` vendoring (`build` subcommand)."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any
import zipfile

from .env_config import WorkspaceConfig, load_config
from .validator import (
    MAX_PACKAGE_BYTES,
    is_runtime_file,
    resolve_target_mods,
    validate_mod_dir,
    validate_zip_archive,
)


DETERMINISTIC_ZIP_DATETIME = (2026, 1, 1, 0, 0, 0)
REGULAR_FILE_EXTERNAL_ATTR = 0o100644 << 16

SEMVER_PARSE_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?P<prerelease>-[0-9A-Za-z._-]+)?"
    r"(?P<build>\+[0-9A-Za-z._-]+)?$"
)


class PackageError(RuntimeError):
    """Raised when plugin validation or packaging fails."""


@dataclass(frozen=True)
class BuildArtifact:
    """Result metadata for a built plugin `.zip` package."""

    mod_name: str
    plugin_id: str
    version: str
    stage_dir: Path
    zip_path: Path
    manifest_path: Path
    zip_size_bytes: int
    sha256: str
    sdk_bundled: bool
    files: list[str]
    plugin_manifest: dict[str, Any]
    file_hashes: dict[str, str] = field(default_factory=dict)


def parse_numeric_semver(version: str) -> tuple[int, int, int]:
    """Extract numeric `(major, minor, patch)` matching `PluginPackageJob.cs` `Split('-', '+')[0]`."""
    match = SEMVER_PARSE_RE.match(version.strip())
    if not match:
        raise PackageError(f"非标准语义化版本号：{version!r}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
    )


def bump_patch_version(version: str) -> str:
    """Increment the numeric `patch` segment of a SemVer string (e.g., `0.1.0` -> `0.1.1`).

    Aligned with `PluginPackageJob.CheckUpdates` (`Version.Parse(version.Split('-', '+')[0])`),
    which compares only the numeric `major.minor.patch` triplet.
    """
    match = SEMVER_PARSE_RE.match(version.strip())
    if not match:
        raise PackageError(f"无法递增非标准语义化版本号：{version!r}")
    major = int(match.group("major"))
    minor = int(match.group("minor"))
    patch = int(match.group("patch")) + 1
    prerelease = match.group("prerelease") or ""
    build_meta = match.group("build") or ""
    return f"{major}.{minor}.{patch}{prerelease}{build_meta}"


def compute_file_sha256(path: Path) -> str:
    """Compute lowercase hexadecimal SHA-256 digest of a file."""
    hasher = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _write_json_utf8_no_bom(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").replace("\r\n", "\n")
    path.write_bytes(text.encode("utf-8"))


def _reset_stage_dir(stage_dir: Path) -> None:
    """Remove all staged files and best-effort prune subdirectories (Windows sandbox safe)."""
    if stage_dir.exists():
        for dirpath, dirnames, filenames in os.walk(stage_dir, topdown=False, followlinks=False):
            dp = Path(dirpath)
            for fname in filenames:
                fpath = dp / fname
                try:
                    fpath.chmod(0o666)
                except OSError:
                    pass
                fpath.unlink(missing_ok=True)
            for dname in dirnames:
                try:
                    (dp / dname).rmdir()
                except OSError:
                    pass
        try:
            stage_dir.rmdir()
        except OSError:
            pass
    stage_dir.mkdir(parents=True, exist_ok=True)


def build_mod(
    mod_name: str,
    config: WorkspaceConfig | None = None,
    *,
    bump_dev: bool = False,
    no_sdk: bool = False,
) -> BuildArtifact:
    """Validate, stage, vendor `fu_sdk`, and create a deterministic `.zip` archive."""
    cfg = config or load_config()
    clean_name = mod_name.strip()
    mod_dir = cfg.mods_dir / clean_name

    effective_sdk_dir = None if no_sdk else cfg.sdk_dir
    report = validate_mod_dir(mod_dir, mod_name=clean_name, sdk_dir=effective_sdk_dir)
    if not report.ok or report.manifest is None:
        joined_errors = "\n  - ".join(report.errors)
        raise PackageError(f"插件 '{clean_name}' 静态契约校验未通过，终止打包：\n  - {joined_errors}")

    plugin_manifest = dict(report.manifest)
    if bump_dev:
        old_ver = str(plugin_manifest["version"])
        new_ver = bump_patch_version(old_ver)
        plugin_manifest["version"] = new_ver
        _write_json_utf8_no_bom(mod_dir / "plugin.json", plugin_manifest)

    plugin_id = str(plugin_manifest["id"])
    version = str(plugin_manifest["version"])

    mod_build_root = cfg.build_dir / clean_name
    stage_dir = mod_build_root / "stage"
    _reset_stage_dir(stage_dir)

    # 1. Copy runtime files from mods/<mod-name>/
    for src_file in sorted(mod_dir.rglob("*")):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(mod_dir)
        if not is_runtime_file(rel):
            continue
        dst_file = stage_dir / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_file, dst_file)

    # 2. Vendor shared/sdk/fu_sdk/*.gd -> stage/lib/fu_sdk/
    sdk_bundled = False
    if not no_sdk and cfg.sdk_dir.is_dir():
        sdk_files = [
            f
            for f in sorted(cfg.sdk_dir.rglob("*.gd"))
            if f.is_file()
            and not any(part.startswith(".") or part == "__pycache__" for part in f.relative_to(cfg.sdk_dir).parts)
        ]
        for sdk_file in sdk_files:
            rel_sdk = sdk_file.relative_to(cfg.sdk_dir)
            dst_sdk = stage_dir / "lib" / "fu_sdk" / rel_sdk
            dst_sdk.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sdk_file, dst_sdk)
            sdk_bundled = True

    # 3. Collect all staged regular files in deterministic POSIX lexicographical order
    staged_entries: list[tuple[str, Path]] = []
    for item in stage_dir.rglob("*"):
        if not item.is_file():
            continue
        posix_rel = item.relative_to(stage_dir).as_posix()
        if "\\" in posix_rel or posix_rel.startswith("/") or ".." in posix_rel.split("/"):
            raise PackageError(f"暂存区检测到不安全归档路径：{posix_rel!r}")
        staged_entries.append((posix_rel, item))

    staged_entries.sort(key=lambda pair: pair[0])
    if not staged_entries:
        raise PackageError(f"插件 '{clean_name}' 无任何可打包文件。")

    # 4. Write deterministic ZIP archive atomically and record per-file SHA-256 hashes
    zip_filename = f"{clean_name}.zip"
    zip_path = mod_build_root / zip_filename
    tmp_zip_path = mod_build_root / f".{zip_filename}.tmp.{os.getpid()}"
    if tmp_zip_path.exists():
        tmp_zip_path.unlink()

    file_hashes: dict[str, str] = {}
    try:
        with zipfile.ZipFile(tmp_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for posix_rel, file_path in staged_entries:
                info = zipfile.ZipInfo(filename=posix_rel, date_time=DETERMINISTIC_ZIP_DATETIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3  # Unix permissions semantics (non-symlink regular file)
                info.external_attr = REGULAR_FILE_EXTERNAL_ATTR
                data = file_path.read_bytes()
                file_hashes[posix_rel] = hashlib.sha256(data).hexdigest()
                zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

        zip_size = tmp_zip_path.stat().st_size
        if zip_size > MAX_PACKAGE_BYTES:
            raise PackageError(
                f"构建产物 '{zip_filename}' 体积 ({zip_size} 字节) 超过客户端 64 MB 限制 ({MAX_PACKAGE_BYTES} 字节)。"
            )

        # Post-build archive-level validation mirroring PluginPackageJob.Install
        zip_errors = validate_zip_archive(tmp_zip_path)
        if zip_errors:
            joined = "\n  - ".join(zip_errors)
            raise PackageError(f"构建产物 '{zip_filename}' 归档级后置校验失败：\n  - {joined}")

        try:
            os.replace(tmp_zip_path, zip_path)
        except PermissionError:
            shutil.copyfile(tmp_zip_path, zip_path)
    finally:
        if tmp_zip_path.exists():
            tmp_zip_path.unlink()

    sha256_hex = compute_file_sha256(zip_path)
    file_list = [posix_rel for posix_rel, _ in staged_entries]

    build_manifest_path = mod_build_root / "build-manifest.json"
    build_manifest_data: dict[str, Any] = {
        "mod_name": clean_name,
        "plugin_id": plugin_id,
        "schema": plugin_manifest.get("schema"),
        "host_api": plugin_manifest.get("host_api"),
        "version": version,
        "zip_filename": zip_filename,
        "zip_size_bytes": zip_size,
        "sha256": sha256_hex,
        "sdk_bundled": sdk_bundled,
        "file_count": len(file_list),
        "files": file_list,
        "file_hashes": file_hashes,
    }
    _write_json_utf8_no_bom(build_manifest_path, build_manifest_data)

    return BuildArtifact(
        mod_name=clean_name,
        plugin_id=plugin_id,
        version=version,
        stage_dir=stage_dir,
        zip_path=zip_path,
        manifest_path=build_manifest_path,
        zip_size_bytes=zip_size,
        sha256=sha256_hex,
        sdk_bundled=sdk_bundled,
        files=file_list,
        plugin_manifest=plugin_manifest,
        file_hashes=file_hashes,
    )


def build_mods(
    config: WorkspaceConfig | None = None,
    *,
    mod_name: str | None = None,
    select_all: bool = False,
    include_template: bool = False,
    bump_dev: bool = False,
    no_sdk: bool = False,
) -> list[BuildArtifact]:
    """Build one or multiple plugins."""
    cfg = config or load_config()
    targets = resolve_target_mods(
        cfg,
        mod_name=mod_name,
        select_all=select_all,
        include_template=include_template,
    )
    artifacts: list[BuildArtifact] = []
    for name in targets:
        artifacts.append(
            build_mod(
                name,
                config=cfg,
                bump_dev=bump_dev,
                no_sdk=no_sdk,
            )
        )
    return artifacts
