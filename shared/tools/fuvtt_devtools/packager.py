"""Deterministic plugin packager with automatic `fu_sdk` / `fu_runtime` vendoring (`build` subcommand)."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any
import zipfile

from .env_config import ConfigError, WorkspaceConfig, load_config
from .validator import (
    GDPC_MAGIC,
    INWORLD_SCHEMAS,
    MAX_PACKAGE_BYTES,
    extract_module_namespace_roots,
    is_inworld_runtime_file,
    is_runtime_file,
    resolve_runtime_sdk_bundle,
    resolve_target_mods,
    validate_fup_archive,
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

PCK_BUILDER_PROJECT_GODOT = """config_version=5

[application]

config/name="FuVTT_PckBuilder"
config/features=PackedStringArray("4.8", "GL Compatibility")
"""

PCK_BUILDER_GD = """extends SceneTree


func _initialize() -> void:
\tvar spec_path := ""
\tfor arg: String in OS.get_cmdline_user_args():
\t\tif arg.begins_with("--spec="):
\t\t\tspec_path = arg.trim_prefix("--spec=")
\tif spec_path.is_empty():
\t\tprinterr("[build_pck] missing --spec=")
\t\tquit(2)
\t\treturn
\tvar raw := FileAccess.get_file_as_string(spec_path)
\tvar parsed: Variant = JSON.parse_string(raw)
\tif not (parsed is Dictionary):
\t\tprinterr("[build_pck] invalid spec json")
\t\tquit(3)
\t\treturn
\tvar spec := parsed as Dictionary
\tvar output_pck := String(spec.get("output_pck", ""))
\tvar entries: Variant = spec.get("entries", [])
\tif output_pck.is_empty() or not (entries is Array) or (entries as Array).is_empty():
\t\tprinterr("[build_pck] empty output_pck or entries")
\t\tquit(4)
\t\treturn
\tvar packer := PCKPacker.new()
\tvar err: Error = packer.pck_start(output_pck)
\tif err != OK:
\t\tprinterr("[build_pck] pck_start failed: %d" % err)
\t\tquit(5)
\t\treturn
\tfor item: Variant in (entries as Array):
\t\tif not (item is Dictionary):
\t\t\tcontinue
\t\tvar d := item as Dictionary
\t\tvar vfs := String(d.get("vfs", ""))
\t\tvar src := String(d.get("src", ""))
\t\tvar add_err: Error = packer.add_file(vfs, src)
\t\tif add_err != OK:
\t\t\tprinterr("[build_pck] add_file failed for %s: %d" % [vfs, add_err])
\t\t\tquit(6)
\t\t\treturn
\tvar flush_err: Error = packer.flush(false)
\tif flush_err != OK:
\t\tprinterr("[build_pck] flush failed: %d" % flush_err)
\t\tquit(7)
\t\treturn
\tprint("FUVTT_PCK_OK count=%d" % (entries as Array).size())
\tquit(0)
"""


class PackageError(RuntimeError):
    """Raised when plugin validation or packaging fails."""


@dataclass(frozen=True)
class BuildArtifact:
    """Result metadata for a built plugin `.zip` or `.fup` package."""

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
    package_ext: str = ".zip"
    schema: str = "fus.session-plugin.v1"
    pck_path: Path | None = None
    pck_sha256: str | None = None
    packed_files: list[str] = field(default_factory=list)


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


def _write_text_utf8_no_bom(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n")
    path.write_bytes(normalized.encode("utf-8"))


def _write_deterministic_archive(
    archive_path: Path,
    entries: list[tuple[str, bytes]],
) -> dict[str, str]:
    """Write a deterministic ZIP/FUP archive atomically and return `{member: sha256}`."""
    tmp_path = archive_path.parent / f".{archive_path.name}.tmp.{os.getpid()}"
    if tmp_path.exists():
        tmp_path.unlink()

    sorted_entries = sorted(entries, key=lambda item: item[0])
    file_hashes: dict[str, str] = {}
    try:
        with zipfile.ZipFile(tmp_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for posix_rel, data in sorted_entries:
                info = zipfile.ZipInfo(filename=posix_rel, date_time=DETERMINISTIC_ZIP_DATETIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = REGULAR_FILE_EXTERNAL_ATTR
                file_hashes[posix_rel] = hashlib.sha256(data).hexdigest()
                zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)

        archive_size = tmp_path.stat().st_size
        if archive_size > MAX_PACKAGE_BYTES:
            raise PackageError(
                f"构建产物 '{archive_path.name}' 体积 ({archive_size} 字节) 超过客户端 64 MB 限制 ({MAX_PACKAGE_BYTES} 字节)。"
            )

        zip_errors = validate_fup_archive(tmp_path)
        if zip_errors:
            joined = "\n  - ".join(zip_errors)
            raise PackageError(f"构建产物 '{archive_path.name}' 归档级后置校验失败：\n  - {joined}")

        try:
            os.replace(tmp_path, archive_path)
        except PermissionError:
            shutil.copyfile(tmp_path, archive_path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    return file_hashes


def _run_pck_packer(
    *,
    godot_exe: Path,
    pck_builder_dir: Path,
    output_pck: Path,
    packed_entries: list[tuple[str, Path]],
    timeout_seconds: int = 120,
) -> None:
    """Invoke headless Godot `PCKPacker` in an isolated temporary project."""
    _reset_stage_dir(pck_builder_dir)
    env_root = pck_builder_dir / "_env"
    appdata = env_root / "appdata"
    localappdata = env_root / "localappdata"
    temp_dir = env_root / "temp"
    for d in (appdata, localappdata, temp_dir):
        d.mkdir(parents=True, exist_ok=True)

    _write_text_utf8_no_bom(pck_builder_dir / "project.godot", PCK_BUILDER_PROJECT_GODOT)
    _write_text_utf8_no_bom(pck_builder_dir / "build_pck.gd", PCK_BUILDER_GD)

    spec_path = pck_builder_dir / "pck_spec.json"
    spec_payload = {
        "output_pck": output_pck.resolve().as_posix(),
        "entries": [
            {"vfs": f"res://{rel}", "src": src.resolve().as_posix()}
            for rel, src in sorted(packed_entries, key=lambda p: p[0])
        ],
    }
    _write_json_utf8_no_bom(spec_path, spec_payload)

    child_env = dict(os.environ)
    child_env["APPDATA"] = str(appdata)
    child_env["LOCALAPPDATA"] = str(localappdata)
    child_env["TEMP"] = str(temp_dir)
    child_env["TMP"] = str(temp_dir)
    child_env["GODOT_SILENCE_ROOT_WARNING"] = "1"

    cmd = [
        str(godot_exe),
        "--headless",
        "--quit",
        "--path",
        str(pck_builder_dir),
        "--script",
        "res://build_pck.gd",
        "--",
        f"--spec={spec_path.resolve().as_posix()}",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(pck_builder_dir),
            env=child_env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise PackageError(f"Godot PCKPacker 打包超时（>{timeout_seconds}s）：{exc}") from exc
    except OSError as exc:
        raise PackageError(f"无法启动 Godot PCKPacker 进程：{exc}") from exc

    if proc.returncode != 0 or not output_pck.is_file():
        raise PackageError(
            f"Godot PCKPacker 构建失败 (exit={proc.returncode}):\n"
            f"stdout: {proc.stdout.strip()}\nstderr: {proc.stderr.strip()}"
        )
    with output_pck.open("rb") as fp:
        magic = fp.read(4)
    if magic != GDPC_MAGIC:
        raise PackageError(f"生成的 PCK 文件 '{output_pck.name}' 缺少 GDPC 魔数（实际：{magic!r}）。")


def _extract_pack_file(manifest: dict[str, Any]) -> str:
    raw_pf = manifest.get("pack_file")
    if isinstance(raw_pf, str) and raw_pf != "":
        return raw_pf
    raw_pck = manifest.get("pck")
    if isinstance(raw_pck, str) and raw_pck != "":
        return raw_pck
    return ""


def _collect_imported_assets_for_mod(mod_dir: Path, mod_rel_paths: list[str]) -> list[tuple[str, Path]]:
    """Collect `.godot/imported/*-<md5>.*` assets matching `res://<rel>` MD5s (`build_world_plugin.gd:98-113`)."""
    imported_dir = mod_dir / ".godot" / "imported"
    if not imported_dir.is_dir():
        return []
    allowed_hashes = {
        hashlib.md5(f"res://{rel}".encode("utf-8")).hexdigest()
        for rel in mod_rel_paths
    }
    matched: list[tuple[str, Path]] = []
    for imp_file in sorted(imported_dir.rglob("*")):
        if not imp_file.is_file() or imp_file.name.startswith(".") or imp_file.suffix.lower() == ".uid":
            continue
        fname = imp_file.name
        if any(f"-{md5_hex}." in fname for md5_hex in allowed_hashes):
            rel = imp_file.relative_to(mod_dir).as_posix()
            matched.append((rel, imp_file))
    return matched


def build_mod(
    mod_name: str,
    config: WorkspaceConfig | None = None,
    *,
    bump_dev: bool = False,
    no_sdk: bool = False,
    godot_bin: Path | str | None = None,
) -> BuildArtifact:
    """Validate, stage, vendor SDK (`fu_sdk`/`fu_runtime`), and build deterministic `.zip` or `.fup`."""
    cfg = config or load_config()
    clean_name = mod_name.strip()
    mod_dir = cfg.mods_dir / clean_name

    effective_sdk_dir = None if no_sdk else cfg.sdk_dir
    effective_runtime_sdk_dir = None if no_sdk else cfg.resolved_runtime_sdk_dir
    report = validate_mod_dir(
        mod_dir,
        mod_name=clean_name,
        sdk_dir=effective_sdk_dir,
        runtime_sdk_dir=effective_runtime_sdk_dir,
    )
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
    schema = str(plugin_manifest.get("schema") or "fus.session-plugin.v1")
    pack_file = _extract_pack_file(plugin_manifest) if schema == "fus.plugin.v2" else ""

    mod_build_root = cfg.build_dir / clean_name
    stage_dir = mod_build_root / "stage"
    _reset_stage_dir(stage_dir)

    if schema == "fus.session-plugin.v1":
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

        zip_filename = f"{clean_name}.zip"
        zip_path = mod_build_root / zip_filename
        archive_bytes_entries = [(rel, path.read_bytes()) for rel, path in staged_entries]
        file_hashes = _write_deterministic_archive(zip_path, archive_bytes_entries)
        zip_size = zip_path.stat().st_size
        sha256_hex = compute_file_sha256(zip_path)
        file_list = [posix_rel for posix_rel, _ in staged_entries]

        build_manifest_path = mod_build_root / "build-manifest.json"
        build_manifest_data: dict[str, Any] = {
            "mod_name": clean_name,
            "plugin_id": plugin_id,
            "schema": schema,
            "host_api": plugin_manifest.get("host_api"),
            "version": version,
            "zip_filename": zip_filename,
            "zip_size_bytes": zip_size,
            "archive_filename": zip_filename,
            "archive_size_bytes": zip_size,
            "package_ext": ".zip",
            "pack_file": "",
            "pck_sha256": None,
            "sha256": sha256_hex,
            "sdk_bundled": sdk_bundled,
            "file_count": len(file_list),
            "files": file_list,
            "packed_files": [],
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
            package_ext=".zip",
            schema=schema,
        )

    # In-world build (`fus.desktop-module.v1` or `fus.plugin.v2`)
    if schema not in INWORLD_SCHEMAS:
        raise PackageError(f"不支持的插件 schema：{schema!r}")

    ns_roots = extract_module_namespace_roots(plugin_manifest, plugin_id)
    mod_ns_prefixes = (f"mods/{plugin_id}/", f"external_modules/{plugin_id}/")
    raw_hybrid_entry = plugin_manifest.get("entry")
    hybrid_entry = raw_hybrid_entry if isinstance(raw_hybrid_entry, str) else ""

    # 1. Copy runtime files from mods/<mod-name>/ into stage_dir
    mod_rel_paths: list[str] = []
    for src_file in sorted(mod_dir.rglob("*")):
        if not src_file.is_file():
            continue
        rel = src_file.relative_to(mod_dir)
        if not is_inworld_runtime_file(rel):
            continue
        posix_rel = rel.as_posix()
        dst_file = stage_dir / rel
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_file, dst_file)
        if posix_rel.startswith(mod_ns_prefixes):
            mod_rel_paths.append(posix_rel)

    # 2. Bundle fu_runtime + shared_fu_sdk_scripts under <ns_root>/lib/
    sdk_bundled = False
    if not no_sdk:
        rt_items, fu_sdk_items, bundle_errors = resolve_runtime_sdk_bundle(
            cfg.sdk_dir, cfg.resolved_runtime_sdk_dir
        )
        if bundle_errors:
            raise PackageError("运行时 SDK 清单解析失败：\n  - " + "\n  - ".join(bundle_errors))
        if ns_roots and (rt_items or fu_sdk_items):
            for ns_root in ns_roots:
                for rel_rt, src_rt in rt_items:
                    dst_rt = stage_dir / Path(*ns_root.split("/")) / "lib" / "fu_runtime" / Path(*rel_rt.split("/"))
                    dst_rt.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src_rt, dst_rt)
                    sdk_bundled = True
                for rel_sdk, src_sdk in fu_sdk_items:
                    dst_sdk = stage_dir / Path(*ns_root.split("/")) / "lib" / "fu_sdk" / Path(*rel_sdk.split("/"))
                    dst_sdk.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src_sdk, dst_sdk)
                    sdk_bundled = True
        if hybrid_entry and cfg.sdk_dir.is_dir():
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

    # Pure-ZIP mode (`fus.desktop-module.v1` or `fus.plugin.v2` without `pack_file`)
    if not pack_file:
        staged_entries = []
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

        zip_filename = f"{clean_name}.zip"
        zip_path = mod_build_root / zip_filename
        file_hashes = _write_deterministic_archive(
            zip_path,
            [(rel, path.read_bytes()) for rel, path in staged_entries],
        )
        zip_size = zip_path.stat().st_size
        sha256_hex = compute_file_sha256(zip_path)
        file_list = [rel for rel, _ in staged_entries]

        build_manifest_path = mod_build_root / "build-manifest.json"
        build_manifest_data = {
            "mod_name": clean_name,
            "plugin_id": plugin_id,
            "schema": schema,
            "host_api": plugin_manifest.get("host_api"),
            "version": version,
            "zip_filename": zip_filename,
            "zip_size_bytes": zip_size,
            "archive_filename": zip_filename,
            "archive_size_bytes": zip_size,
            "package_ext": ".zip",
            "pack_file": "",
            "pck_sha256": None,
            "sha256": sha256_hex,
            "sdk_bundled": sdk_bundled,
            "file_count": len(file_list),
            "files": file_list,
            "packed_files": file_list,
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
            package_ext=".zip",
            schema=schema,
            packed_files=list(file_list),
        )

    # PCK + .fup mode (`fus.plugin.v2` with `pack_file`)
    try:
        godot_exe = cfg.resolve_godot_bin(override_bin=godot_bin)
    except ConfigError as exc:
        raise PackageError(str(exc)) from exc
    if not godot_exe.is_file():
        raise PackageError(
            f"找不到 Godot 控制台可执行文件：{cfg.redact_path(godot_exe)}。"
            " 请在 .env.local 配置 GODOT_BIN 或通过 --godot-bin 指定。"
        )

    # Include matching `.godot/imported/*-<md5>.*` assets into stage_dir for PCK packing
    for imp_rel, imp_src in _collect_imported_assets_for_mod(mod_dir, mod_rel_paths):
        dst_imp = stage_dir / Path(*imp_rel.split("/"))
        dst_imp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(imp_src, dst_imp)

    packed_entries: list[tuple[str, Path]] = []
    for item in stage_dir.rglob("*"):
        if not item.is_file():
            continue
        posix_rel = item.relative_to(stage_dir).as_posix()
        if posix_rel == "plugin.json":
            continue
        if hybrid_entry and posix_rel == hybrid_entry:
            continue
        if posix_rel.startswith(mod_ns_prefixes) or posix_rel.startswith(".godot/imported/"):
            packed_entries.append((posix_rel, item))
    packed_entries.sort(key=lambda pair: pair[0])
    if not packed_entries:
        raise PackageError(f"插件 '{clean_name}' 在命名空间目录下无任何可打入 {pack_file} 的文件。")

    pck_path = mod_build_root / pack_file
    _run_pck_packer(
        godot_exe=godot_exe,
        pck_builder_dir=mod_build_root / "pck_builder",
        output_pck=pck_path,
        packed_entries=packed_entries,
    )

    manifest_bytes = (stage_dir / "plugin.json").read_bytes()
    pck_bytes = pck_path.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    pck_sha = hashlib.sha256(pck_bytes).hexdigest()

    sums_lines = [
        f"{manifest_sha}  plugin.json",
        f"{pck_sha}  {pack_file}",
    ]
    outer_entries: list[tuple[str, bytes]] = [
        ("plugin.json", manifest_bytes),
        (pack_file, pck_bytes),
    ]
    if hybrid_entry:
        hybrid_bytes = (stage_dir / Path(*hybrid_entry.split("/"))).read_bytes()
        hybrid_sha = hashlib.sha256(hybrid_bytes).hexdigest()
        sums_lines.append(f"{hybrid_sha}  {hybrid_entry}")
        outer_entries.append((hybrid_entry, hybrid_bytes))
        lib_fu_sdk_dir = stage_dir / "lib" / "fu_sdk"
        if lib_fu_sdk_dir.is_dir():
            for sdk_file in sorted(lib_fu_sdk_dir.rglob("*.gd")):
                if not sdk_file.is_file():
                    continue
                sdk_rel = sdk_file.relative_to(stage_dir).as_posix()
                sdk_bytes = sdk_file.read_bytes()
                sdk_sha = hashlib.sha256(sdk_bytes).hexdigest()
                sums_lines.append(f"{sdk_sha}  {sdk_rel}")
                outer_entries.append((sdk_rel, sdk_bytes))

    sums_bytes = ("\n".join(sums_lines) + "\n").encode("utf-8")
    outer_entries.append(("SHA256SUMS.txt", sums_bytes))
    outer_entries.sort(key=lambda item: item[0])

    fup_filename = f"{clean_name}.fup"
    fup_path = mod_build_root / fup_filename
    file_hashes = _write_deterministic_archive(fup_path, outer_entries)
    fup_size = fup_path.stat().st_size
    sha256_hex = compute_file_sha256(fup_path)
    file_list = [rel for rel, _ in outer_entries]
    packed_list = [rel for rel, _ in packed_entries]

    build_manifest_path = mod_build_root / "build-manifest.json"
    build_manifest_data = {
        "mod_name": clean_name,
        "plugin_id": plugin_id,
        "schema": schema,
        "host_api": plugin_manifest.get("host_api"),
        "version": version,
        "zip_filename": fup_filename,
        "zip_size_bytes": fup_size,
        "archive_filename": fup_filename,
        "archive_size_bytes": fup_size,
        "package_ext": ".fup",
        "pack_file": pack_file,
        "pck_sha256": pck_sha,
        "sha256": sha256_hex,
        "sdk_bundled": sdk_bundled,
        "file_count": len(file_list),
        "files": file_list,
        "packed_files": packed_list,
        "file_hashes": file_hashes,
    }
    _write_json_utf8_no_bom(build_manifest_path, build_manifest_data)

    return BuildArtifact(
        mod_name=clean_name,
        plugin_id=plugin_id,
        version=version,
        stage_dir=stage_dir,
        zip_path=fup_path,
        manifest_path=build_manifest_path,
        zip_size_bytes=fup_size,
        sha256=sha256_hex,
        sdk_bundled=sdk_bundled,
        files=file_list,
        plugin_manifest=plugin_manifest,
        file_hashes=file_hashes,
        package_ext=".fup",
        schema=schema,
        pck_path=pck_path,
        pck_sha256=pck_sha,
        packed_files=packed_list,
    )


def build_mods(
    config: WorkspaceConfig | None = None,
    *,
    mod_name: str | None = None,
    select_all: bool = False,
    include_template: bool = False,
    bump_dev: bool = False,
    no_sdk: bool = False,
    godot_bin: Path | str | None = None,
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
                godot_bin=godot_bin,
            )
        )
    return artifacts
