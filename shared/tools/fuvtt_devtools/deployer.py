"""Dual-mode local plugin deployer: atomic direct `sync` and zero-restart HTTP `serve`.

`sync` is aligned with Practice host `services/plugins/PluginPackageJob.cs` (`ReadRegistry`,
`ValidateSettings`, `InstalledValid`, and version conflict guards).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any, Mapping
from urllib.parse import urlsplit
import uuid
import zipfile

from .env_config import WorkspaceConfig, load_config
from .packager import (
    BuildArtifact,
    _collect_imported_assets_for_mod,
    _extract_pack_file,
    build_mod,
    compute_file_sha256,
    parse_numeric_semver,
)
from .validator import (
    INWORLD_SCHEMAS,
    MAX_ARCHIVE_ENTRIES,
    MAX_EXPANDED_BYTES,
    MAX_PACKAGE_BYTES,
    MAX_SETTING_STRING_DEFAULT_LENGTH,
    MIN_ARCHIVE_ENTRIES,
    check_zip_member_path,
    extract_module_namespace_roots,
    is_inworld_runtime_file,
    is_runtime_file,
    resolve_runtime_sdk_bundle,
    resolve_target_mods,
)


MAX_INSTALLED_PLUGINS = 128


class DeployError(RuntimeError):
    """Raised when syncing or serving plugin packages fails."""


@dataclass(frozen=True)
class SyncResult:
    """Outcome of syncing a built plugin into a client `session_plugins` directory."""

    mod_name: str
    plugin_id: str
    version: str
    sha256: str
    session_plugins_dir: Path
    package_dir: Path
    registry_path: Path
    backup_path: Path | None
    rebuilt: bool
    dry_run: bool
    enabled: bool
    file_hashes_count: int = 0
    cleaned_old_package_dir: Path | None = None


@dataclass(frozen=True)
class HostedPackage:
    """Metadata for a built `.zip` or `.fup` package exposed via `serve`."""

    mod_name: str
    plugin_id: str
    version: str
    sha256: str
    zip_path: Path
    zip_size_bytes: int
    archive_ext: str = ".zip"
    schema: str = "fus.session-plugin.v1"


def _latest_source_mtime_ns(
    mod_dir: Path,
    sdk_dir: Path,
    *,
    runtime_sdk_dir: Path | None = None,
    schema: str = "fus.session-plugin.v1",
) -> int:
    latest = 0
    if mod_dir.is_dir():
        for item in mod_dir.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(mod_dir)
            if schema in INWORLD_SCHEMAS:
                if is_inworld_runtime_file(rel) or rel.as_posix().startswith(".godot/imported/"):
                    latest = max(latest, item.stat().st_mtime_ns)
            else:
                if is_runtime_file(rel):
                    latest = max(latest, item.stat().st_mtime_ns)
    if schema in INWORLD_SCHEMAS:
        if runtime_sdk_dir is not None and runtime_sdk_dir.is_dir():
            manifest_file = runtime_sdk_dir / "runtime_manifest.json"
            if manifest_file.is_file():
                latest = max(latest, manifest_file.stat().st_mtime_ns)
            rt_items, fu_sdk_items, _ = resolve_runtime_sdk_bundle(sdk_dir, runtime_sdk_dir)
            for _, rt_file in rt_items:
                if rt_file.is_file():
                    latest = max(latest, rt_file.stat().st_mtime_ns)
            for _, sdk_file in fu_sdk_items:
                if sdk_file.is_file():
                    latest = max(latest, sdk_file.stat().st_mtime_ns)
        if sdk_dir.is_dir():
            for sdk_item in sdk_dir.rglob("*.gd"):
                if sdk_item.is_file():
                    latest = max(latest, sdk_item.stat().st_mtime_ns)
    elif sdk_dir.is_dir():
        for sdk_item in sdk_dir.rglob("*.gd"):
            if sdk_item.is_file():
                latest = max(latest, sdk_item.stat().st_mtime_ns)
    return latest


def _expected_source_files(
    mod_dir: Path,
    sdk_dir: Path,
    *,
    sdk_bundled: bool,
    runtime_sdk_dir: Path | None = None,
    schema: str = "fus.session-plugin.v1",
    plugin_manifest: Mapping[str, Any] | None = None,
) -> list[str]:
    expected: list[str] = []
    if schema in INWORLD_SCHEMAS:
        if mod_dir.is_dir():
            for item in mod_dir.rglob("*"):
                if item.is_file() and is_inworld_runtime_file(item.relative_to(mod_dir)):
                    expected.append(item.relative_to(mod_dir).as_posix())
        if sdk_bundled and plugin_manifest is not None and runtime_sdk_dir is not None and runtime_sdk_dir.is_dir():
            ns_roots = extract_module_namespace_roots(plugin_manifest)
            rt_items, fu_sdk_items, _ = resolve_runtime_sdk_bundle(sdk_dir, runtime_sdk_dir)
            for ns_root in ns_roots:
                for rel_rt, _ in rt_items:
                    expected.append(f"{ns_root}/lib/fu_runtime/{rel_rt}")
                for rel_sdk, _ in fu_sdk_items:
                    expected.append(f"{ns_root}/lib/fu_sdk/{rel_sdk}")
        if sdk_bundled and plugin_manifest is not None and str(plugin_manifest.get("entry") or "").strip() and sdk_dir.is_dir():
            for sdk_item in sdk_dir.rglob("*.gd"):
                if not sdk_item.is_file():
                    continue
                rel_sdk = sdk_item.relative_to(sdk_dir)
                if any(part.startswith(".") or part == "__pycache__" for part in rel_sdk.parts):
                    continue
                expected.append(f"lib/fu_sdk/{rel_sdk.as_posix()}")
        expected.sort()
        return expected

    if mod_dir.is_dir():
        for item in mod_dir.rglob("*"):
            if item.is_file() and is_runtime_file(item.relative_to(mod_dir)):
                expected.append(item.relative_to(mod_dir).as_posix())
    if sdk_bundled and sdk_dir.is_dir():
        for sdk_item in sdk_dir.rglob("*.gd"):
            if not sdk_item.is_file():
                continue
            rel_sdk = sdk_item.relative_to(sdk_dir)
            if any(part.startswith(".") or part == "__pycache__" for part in rel_sdk.parts):
                continue
            expected.append(f"lib/fu_sdk/{rel_sdk.as_posix()}")
    expected.sort()
    return expected


def _expected_fup_packed_files(
    mod_dir: Path,
    sdk_dir: Path,
    *,
    sdk_bundled: bool,
    runtime_sdk_dir: Path | None,
    plugin_manifest: Mapping[str, Any],
) -> list[str]:
    plugin_id = str(plugin_manifest.get("id") or "")
    hybrid_entry = str(plugin_manifest.get("entry") or "").strip()
    mod_ns_prefixes = (f"mods/{plugin_id}/", f"external_modules/{plugin_id}/")
    mod_rels: list[str] = []
    packed: list[str] = []
    if mod_dir.is_dir():
        for item in mod_dir.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(mod_dir)
            if not is_inworld_runtime_file(rel):
                continue
            posix_rel = rel.as_posix()
            if posix_rel == "plugin.json" or (hybrid_entry and posix_rel == hybrid_entry):
                continue
            if posix_rel.startswith(mod_ns_prefixes):
                mod_rels.append(posix_rel)
                packed.append(posix_rel)
        for imp_rel, _ in _collect_imported_assets_for_mod(mod_dir, mod_rels):
            packed.append(imp_rel)
    if sdk_bundled and runtime_sdk_dir is not None and runtime_sdk_dir.is_dir():
        ns_roots = extract_module_namespace_roots(plugin_manifest, plugin_id)
        rt_items, fu_sdk_items, _ = resolve_runtime_sdk_bundle(sdk_dir, runtime_sdk_dir)
        for ns_root in ns_roots:
            for rel_rt, _ in rt_items:
                packed.append(f"{ns_root}/lib/fu_runtime/{rel_rt}")
            for rel_sdk, _ in fu_sdk_items:
                packed.append(f"{ns_root}/lib/fu_sdk/{rel_sdk}")
    packed.sort()
    return packed


def _load_or_build_artifact(
    mod_name: str,
    cfg: WorkspaceConfig,
    *,
    godot_bin: Path | str | None = None,
) -> tuple[BuildArtifact, bool]:
    """Return an up-to-date BuildArtifact, running `build_mod` automatically if missing or stale."""
    mod_dir = cfg.mods_dir / mod_name
    if not mod_dir.is_dir():
        raise DeployError(f"找不到插件源码目录：mods/{mod_name}")

    mod_build_root = cfg.build_dir / mod_name
    build_manifest_path = mod_build_root / "build-manifest.json"
    plugin_json_path = mod_dir / "plugin.json"

    pm: dict[str, Any] | None = None
    schema = "fus.session-plugin.v1"
    pack_file = ""
    if plugin_json_path.is_file():
        try:
            loaded_pm = json.loads(plugin_json_path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded_pm, dict):
                pm = loaded_pm
                schema = str(pm.get("schema") or "fus.session-plugin.v1")
                if schema == "fus.plugin.v2":
                    pack_file = _extract_pack_file(pm)
        except (OSError, ValueError):
            pm = None

    archive_ext = ".fup" if (schema == "fus.plugin.v2" and pack_file) else ".zip"
    archive_path = mod_build_root / f"{mod_name}{archive_ext}"

    needs_build = not (archive_path.is_file() and build_manifest_path.is_file() and pm is not None)
    if not needs_build:
        archive_mtime = archive_path.stat().st_mtime_ns
        src_mtime = _latest_source_mtime_ns(
            mod_dir,
            cfg.sdk_dir,
            runtime_sdk_dir=cfg.resolved_runtime_sdk_dir,
            schema=schema,
        )
        if src_mtime > archive_mtime:
            needs_build = True

    if not needs_build and pm is not None:
        try:
            bm = json.loads(build_manifest_path.read_text(encoding="utf-8-sig"))
            actual_sha = compute_file_sha256(archive_path)
            sdk_bundled = bool(bm.get("sdk_bundled", True))
            recorded_files = bm.get("files")
            if (
                actual_sha != bm.get("sha256")
                or bm.get("schema") != schema
                or not isinstance(bm.get("file_hashes"), dict)
                or not isinstance(recorded_files, list)
            ):
                needs_build = True
            elif archive_ext == ".fup":
                raw_hybrid_entry = pm.get("entry")
                hybrid_entry = raw_hybrid_entry if isinstance(raw_hybrid_entry, str) else ""
                hybrid_sdk_rels: list[str] = []
                if hybrid_entry and sdk_bundled and cfg.sdk_dir.is_dir():
                    for sdk_item in sorted(cfg.sdk_dir.rglob("*.gd")):
                        if not sdk_item.is_file():
                            continue
                        rel_sdk = sdk_item.relative_to(cfg.sdk_dir)
                        if any(part.startswith(".") or part == "__pycache__" for part in rel_sdk.parts):
                            continue
                        hybrid_sdk_rels.append(f"lib/fu_sdk/{rel_sdk.as_posix()}")
                expected_outer = sorted(
                    ["SHA256SUMS.txt", pack_file, "plugin.json"]
                    + ([hybrid_entry] if hybrid_entry else [])
                    + hybrid_sdk_rels
                )
                pck_path = mod_build_root / pack_file
                expected_packed = _expected_fup_packed_files(
                    mod_dir,
                    cfg.sdk_dir,
                    sdk_bundled=sdk_bundled,
                    runtime_sdk_dir=cfg.resolved_runtime_sdk_dir,
                    plugin_manifest=pm,
                )
                recorded_packed = bm.get("packed_files")
                if (
                    sorted(str(x) for x in recorded_files) != expected_outer
                    or not pck_path.is_file()
                    or compute_file_sha256(pck_path) != bm.get("pck_sha256")
                    or not isinstance(recorded_packed, list)
                    or sorted(str(x) for x in recorded_packed) != expected_packed
                ):
                    needs_build = True
                else:
                    return (
                        BuildArtifact(
                            mod_name=mod_name,
                            plugin_id=str(bm["plugin_id"]),
                            version=str(bm["version"]),
                            stage_dir=mod_build_root / "stage",
                            zip_path=archive_path,
                            manifest_path=build_manifest_path,
                            zip_size_bytes=int(bm.get("archive_size_bytes", bm["zip_size_bytes"])),
                            sha256=actual_sha,
                            sdk_bundled=sdk_bundled,
                            files=list(recorded_files),
                            plugin_manifest=pm,
                            file_hashes=dict(bm.get("file_hashes", {})),
                            package_ext=".fup",
                            schema=schema,
                            pck_path=pck_path,
                            pck_sha256=str(bm.get("pck_sha256") or ""),
                            packed_files=list(recorded_packed),
                        ),
                        False,
                    )
            else:
                expected_files = _expected_source_files(
                    mod_dir,
                    cfg.sdk_dir,
                    sdk_bundled=sdk_bundled,
                    runtime_sdk_dir=cfg.resolved_runtime_sdk_dir,
                    schema=schema,
                    plugin_manifest=pm,
                )
                if sorted(str(x) for x in recorded_files) != expected_files:
                    needs_build = True
                else:
                    return (
                        BuildArtifact(
                            mod_name=mod_name,
                            plugin_id=str(bm["plugin_id"]),
                            version=str(bm["version"]),
                            stage_dir=mod_build_root / "stage",
                            zip_path=archive_path,
                            manifest_path=build_manifest_path,
                            zip_size_bytes=int(bm.get("archive_size_bytes", bm["zip_size_bytes"])),
                            sha256=actual_sha,
                            sdk_bundled=sdk_bundled,
                            files=list(recorded_files),
                            plugin_manifest=pm,
                            file_hashes=dict(bm.get("file_hashes", {})),
                            package_ext=".zip",
                            schema=schema,
                            packed_files=list(bm.get("packed_files") or []),
                        ),
                        False,
                    )
        except (OSError, ValueError, KeyError, TypeError):
            needs_build = True

    artifact = build_mod(mod_name, config=cfg, godot_bin=godot_bin)
    return artifact, True


def compute_zip_file_hashes(zip_path: Path) -> dict[str, str]:
    """Compute per-entry lowercase SHA-256 hashes for all non-directory members inside a ZIP."""
    hashes: dict[str, str] = {}
    with zipfile.ZipFile(zip_path, mode="r") as zf:
        for member in sorted(zf.infolist(), key=lambda m: m.filename):
            if member.filename.endswith("/"):
                continue
            hashes[member.filename] = hashlib.sha256(zf.read(member)).hexdigest()
    return hashes


def compute_directory_file_hashes(package_dir: Path) -> dict[str, str]:
    """Compute per-file lowercase SHA-256 hashes for all deployed files under `package_dir`."""
    hashes: dict[str, str] = {}
    for item in sorted(package_dir.rglob("*"), key=lambda p: p.relative_to(package_dir).as_posix()):
        if not item.is_file():
            continue
        rel = item.relative_to(package_dir).as_posix()
        hashes[rel] = compute_file_sha256(item)
    return hashes


def build_reconciled_settings(
    plugin_manifest: Mapping[str, Any],
    existing_settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile plugin `settings` to strictly match `manifest['settings']` (`PluginPackageJob.cs:133-141, 590-597`).

    Preserves valid existing user values, drops obsolete keys removed from the manifest,
    and initializes newly declared settings to their manifest defaults.
    For `fus.desktop-module.v1` and `fus.plugin.v2`, omitted or `None` `settings` defaults to `[]`.
    """
    raw_fields = plugin_manifest.get("settings")
    if raw_fields is None and plugin_manifest.get("schema") in INWORLD_SCHEMAS:
        raw_fields = []
    if not isinstance(raw_fields, list):
        raise DeployError("invalid_plugin_settings: plugin.json 缺少合法的 settings 数组。")

    prior = existing_settings if isinstance(existing_settings, Mapping) else {}
    reconciled: dict[str, Any] = {}
    for field in raw_fields:
        if not isinstance(field, Mapping):
            raise DeployError("invalid_plugin_settings: manifest settings 条目必须为字典。")
        key = str(field.get("id") or "")
        ftype = str(field.get("type") or "")
        if not key or "default" not in field:
            raise DeployError(f"invalid_plugin_settings: 设置项 {key!r} 缺少 id 或 default。")

        value: Any = field["default"]
        if key in prior:
            candidate = prior[key]
            if ftype == "bool" and isinstance(candidate, bool):
                value = candidate
            elif (
                ftype == "string"
                and isinstance(candidate, str)
                and len(candidate) <= MAX_SETTING_STRING_DEFAULT_LENGTH
            ):
                value = candidate

        reconciled[key] = value
    return reconciled


def _remove_tree_best_effort(target: Path) -> None:
    if not target.exists():
        return
    try:
        shutil.rmtree(target)
        return
    except PermissionError:
        pass
    for dirpath, dirnames, filenames in os.walk(target, topdown=False, followlinks=False):
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
        target.rmdir()
    except OSError:
        pass


def safe_extract_zip(zip_path: Path, destination_dir: Path) -> None:
    """Safely extract a plugin `.zip` into `destination_dir`, blocking traversal, bad segments, and symlinks."""
    parent_dir = destination_dir.parent
    parent_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = parent_dir / f".{destination_dir.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    resolved_tmp = tmp_dir.resolve()

    try:
        seen_lower: set[str] = set()
        declared_files_lower: set[str] = set()
        declared_dirs_lower: set[str] = set()
        with zipfile.ZipFile(zip_path, mode="r") as zf:
            infos = zf.infolist()
            if len(infos) < MIN_ARCHIVE_ENTRIES or len(infos) > MAX_ARCHIVE_ENTRIES:
                raise DeployError(
                    f"plugin_file_limit: ZIP 条目数 ({len(infos)}) 不在宿主允许范围 {MIN_ARCHIVE_ENTRIES}..{MAX_ARCHIVE_ENTRIES} 内。"
                )
            declared_total = 0
            actual_total = 0
            for member in infos:
                raw_name = member.filename
                orig_name = getattr(member, "orig_filename", raw_name)
                issues = check_zip_member_path(orig_name)
                if orig_name != raw_name:
                    for issue in check_zip_member_path(raw_name):
                        if issue not in issues:
                            issues.append(issue)
                if "\x00" in orig_name:
                    issues.append(f"路径 {orig_name!r} 包含空字节 '\\x00'")
                if issues:
                    raise DeployError(f"unsafe_zip_path: 拒绝解压非法路径 {orig_name!r} ({'; '.join(issues)})")

                if ((member.external_attr >> 16) & 0xF000) == 0xA000:
                    raise DeployError(f"zip_link_rejected: 拒绝解压符号链接条目 {raw_name!r}")

                if member.file_size > MAX_PACKAGE_BYTES:
                    raise DeployError(
                        f"plugin_expanded_limit: 单文件 {raw_name!r} 体积 ({member.file_size} B) 超过 64 MiB 上限。"
                    )
                declared_total += member.file_size
                if declared_total > MAX_EXPANDED_BYTES:
                    raise DeployError(
                        f"plugin_expanded_limit: 声明解压总体积超过 256 MiB 上限 ({MAX_EXPANDED_BYTES} B)。"
                    )

                folded = raw_name.lower()
                if folded in seen_lower:
                    raise DeployError(f"unsafe_zip_path: 拒绝解压大小写冲突条目 {raw_name!r}")
                seen_lower.add(folded)

                trimmed_lower = raw_name[:-1].lower() if raw_name.endswith("/") else folded
                segs_lower = [seg for seg in trimmed_lower.split("/") if seg != ""]
                if raw_name.endswith("/"):
                    if trimmed_lower in declared_files_lower:
                        raise DeployError(f"unsafe_zip_path: 拒绝解压文件与目录同名冲突 {raw_name!r}")
                    declared_dirs_lower.add(trimmed_lower)
                    for i in range(1, len(segs_lower)):
                        anc = "/".join(segs_lower[:i])
                        if anc in declared_files_lower:
                            raise DeployError(f"unsafe_zip_path: 拒绝解压文件与目录同名冲突 {raw_name!r}")
                        declared_dirs_lower.add(anc)
                    continue

                if trimmed_lower in declared_dirs_lower:
                    raise DeployError(f"unsafe_zip_path: 拒绝解压文件与目录同名冲突 {raw_name!r}")
                for i in range(1, len(segs_lower)):
                    anc = "/".join(segs_lower[:i])
                    if anc in declared_files_lower:
                        raise DeployError(f"unsafe_zip_path: 拒绝解压文件与目录同名冲突 {raw_name!r}")
                    declared_dirs_lower.add(anc)
                declared_files_lower.add(trimmed_lower)

                parts = [seg for seg in raw_name.split("/") if seg != ""]
                out_file = (resolved_tmp / Path(*parts)).resolve()
                if not out_file.is_relative_to(resolved_tmp):
                    raise DeployError(f"unsafe_zip_path: 解压目标越出包目录 {raw_name!r}")

                try:
                    out_file.parent.mkdir(parents=True, exist_ok=True)
                    entry_written = 0
                    with zf.open(member, "r") as src_fp, out_file.open("wb") as dst_fp:
                        while True:
                            chunk = src_fp.read(65536)
                            if not chunk:
                                break
                            entry_written += len(chunk)
                            actual_total += len(chunk)
                            if entry_written > MAX_PACKAGE_BYTES or actual_total > MAX_EXPANDED_BYTES:
                                raise DeployError(
                                    f"plugin_expanded_limit: 解压实际字节数超过宿主上限 (single<=64MiB, total<=256MiB) at {raw_name!r}。"
                                )
                            dst_fp.write(chunk)
                except DeployError:
                    raise
                except OSError as exc:
                    raise DeployError(f"unsafe_zip_path: 解压路径冲突或写入失败 {raw_name!r} ({exc})") from exc

        if destination_dir.exists():
            try:
                shutil.rmtree(destination_dir)
            except PermissionError:
                _remove_tree_best_effort(destination_dir)

        placed = False
        if not destination_dir.exists():
            for attempt in range(4):
                try:
                    os.replace(tmp_dir, destination_dir)
                    placed = True
                    break
                except PermissionError:
                    if attempt < 3:
                        time.sleep(0.05)

        if not placed:
            if destination_dir.exists():
                _remove_tree_best_effort(destination_dir)
            destination_dir.mkdir(parents=True, exist_ok=True)
            for item in sorted(tmp_dir.rglob("*")):
                rel = item.relative_to(tmp_dir)
                dst_item = destination_dir / rel
                if item.is_dir():
                    dst_item.mkdir(parents=True, exist_ok=True)
                elif item.is_file():
                    dst_item.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(item, dst_item)
    finally:
        _remove_tree_best_effort(tmp_dir)


def _default_registry() -> dict[str, Any]:
    return {
        "version": 1,
        "plugins": {},
        "playtest_fobr_offered": True,
    }


def _check_version_transition(
    existing_entry: Mapping[str, Any] | None,
    *,
    new_version: str,
    new_sha256: str,
    allow_same_version: bool,
) -> str | None:
    """Enforce `PluginPackageJob.cs:284-289` version monotonicity and conflict rules.

    Returns the previous `sha256` if an old package directory should be cleaned up on same-version overwrite.
    """
    if not isinstance(existing_entry, Mapping):
        return None
    old_manifest = existing_entry.get("manifest")
    if not isinstance(old_manifest, Mapping):
        return None
    old_version = str(old_manifest.get("version") or "").strip()
    old_sha256 = str(existing_entry.get("sha256") or "").strip()
    if not old_version:
        return None

    old_numeric = parse_numeric_semver(old_version)
    new_numeric = parse_numeric_semver(new_version)
    if new_numeric < old_numeric:
        raise DeployError(
            f"plugin_version_older: 拒绝降级安装 ({old_version} -> {new_version})；请递增版本号后再同步。"
        )
    if new_version == old_version and old_sha256 and new_sha256 != old_sha256:
        if not allow_same_version:
            raise DeployError(
                f"plugin_version_conflict: 插件版本 {new_version} 与已安装哈希不一致 "
                f"({old_sha256[:12]} -> {new_sha256[:12]})。请使用 `build --bump-dev` 递增补丁号，"
                "或显式传入 `--allow-same-version` 进行开发态覆盖。"
            )
        return old_sha256
    return None


def merge_registry_plugin_entry(
    registry: dict[str, Any],
    *,
    plugin_id: str,
    plugin_manifest: dict[str, Any],
    sha256: str,
    file_hashes: Mapping[str, str],
    installed_at: str | None = None,
    allow_same_version: bool = False,
) -> tuple[dict[str, Any], bool, str | None]:
    """Losslessly merge a plugin entry into `registry`, satisfying all `PluginPackageJob.ReadRegistry()` invariants."""
    merged_root = dict(registry)
    if "version" not in merged_root:
        merged_root["version"] = 1
    else:
        reg_ver = merged_root["version"]
        if not (isinstance(reg_ver, int) and not isinstance(reg_ver, bool) and reg_ver == 1):
            raise DeployError(f"invalid_plugin_registry: registry version 必须为 1，当前值：{reg_ver!r}")

    raw_plugins = merged_root.get("plugins")
    if not isinstance(raw_plugins, dict):
        plugins_map: dict[str, Any] = {}
    else:
        plugins_map = dict(raw_plugins)

    existing_entry = plugins_map.get(plugin_id)
    if existing_entry is None and len(plugins_map) >= MAX_INSTALLED_PLUGINS:
        raise DeployError(
            f"plugin_count_limit: 客户端已安装插件数达到上限 ({MAX_INSTALLED_PLUGINS})。"
        )

    replaced_old_sha = _check_version_transition(
        existing_entry if isinstance(existing_entry, Mapping) else None,
        new_version=str(plugin_manifest.get("version") or ""),
        new_sha256=sha256,
        allow_same_version=allow_same_version,
    )

    if isinstance(existing_entry, dict):
        entry = dict(existing_entry)
        raw_enabled = existing_entry.get("enabled")
        enabled = raw_enabled if isinstance(raw_enabled, bool) else True
        existing_settings = existing_entry.get("settings") if isinstance(existing_entry.get("settings"), Mapping) else None
        raw_source_url = existing_entry.get("source_url")
        source_url = raw_source_url if isinstance(raw_source_url, str) else ""
    else:
        entry = {}
        enabled = True
        existing_settings = None
        source_url = ""

    reconciled_settings = build_reconciled_settings(plugin_manifest, existing_settings)
    timestamp = installed_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    normalized_manifest = dict(plugin_manifest)
    if normalized_manifest.get("schema") in INWORLD_SCHEMAS and normalized_manifest.get("settings") is None:
        normalized_manifest["settings"] = []

    entry["manifest"] = normalized_manifest
    entry["directory"] = f"packages/{plugin_id}/{sha256}"
    entry["sha256"] = sha256
    entry["source_url"] = source_url
    entry["enabled"] = enabled
    entry["settings"] = reconciled_settings
    entry["file_hashes"] = {str(k): str(v) for k, v in sorted(file_hashes.items())}
    entry["installed_at"] = timestamp

    plugins_map[plugin_id] = entry
    merged_root["plugins"] = plugins_map
    return merged_root, enabled, replaced_old_sha


def _atomic_write_utf8_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").replace("\r\n", "\n").encode("utf-8")
    try:
        with tmp_path.open("wb") as fp:
            fp.write(encoded)
            fp.flush()
            os.fsync(fp.fileno())
        try:
            os.replace(tmp_path, path)
        except PermissionError:
            with path.open("wb") as dst_fp:
                dst_fp.write(encoded)
                dst_fp.flush()
                os.fsync(dst_fp.fileno())
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def sync_mod(
    mod_name: str,
    config: WorkspaceConfig | None = None,
    *,
    dry_run: bool = False,
    target_dir: Path | str | None = None,
    allow_same_version: bool = False,
    godot_bin: Path | str | None = None,
) -> SyncResult:
    """Build (if needed) and atomically deploy a plugin (`.zip` or `.fup`) to `session_plugins/`."""
    cfg = config or load_config()
    clean_name = mod_name.strip()
    artifact, rebuilt = _load_or_build_artifact(clean_name, cfg, godot_bin=godot_bin)
    session_plugins_dir = cfg.resolve_session_plugins_dir(override_dir=target_dir)

    # Read plugin.json & per-file hashes directly from the built ZIP
    with zipfile.ZipFile(artifact.zip_path, mode="r") as zf:
        zip_plugin_manifest = json.loads(zf.read("plugin.json").decode("utf-8"))
    zip_file_hashes = compute_zip_file_hashes(artifact.zip_path)

    plugin_id = str(zip_plugin_manifest["id"])
    version = str(zip_plugin_manifest["version"])
    sha256 = artifact.sha256

    package_dir = session_plugins_dir / "packages" / plugin_id / sha256
    registry_path = session_plugins_dir / "registry.json"

    existing_registry_bytes: bytes | None = None
    if registry_path.is_file():
        existing_registry_bytes = registry_path.read_bytes()
        try:
            current_registry = json.loads(existing_registry_bytes.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DeployError(
                f"客户端注册表 JSON 解析失败 ({cfg.redact_path(registry_path)})：{exc}"
            ) from exc
        if not isinstance(current_registry, dict):
            raise DeployError(f"客户端注册表顶层结构异常 ({cfg.redact_path(registry_path)})：预期 JSON Object。")
    else:
        current_registry = _default_registry()

    # Pre-validate version transition and settings before touching disk
    preview_registry, enabled, replaced_old_sha = merge_registry_plugin_entry(
        current_registry,
        plugin_id=plugin_id,
        plugin_manifest=zip_plugin_manifest,
        sha256=sha256,
        file_hashes=zip_file_hashes,
        allow_same_version=allow_same_version,
    )

    if dry_run:
        return SyncResult(
            mod_name=clean_name,
            plugin_id=plugin_id,
            version=version,
            sha256=sha256,
            session_plugins_dir=session_plugins_dir,
            package_dir=package_dir,
            registry_path=registry_path,
            backup_path=None,
            rebuilt=rebuilt,
            dry_run=True,
            enabled=enabled,
            file_hashes_count=len(zip_file_hashes),
        )

    backup_path: Path | None = None
    if existing_registry_bytes is not None:
        backup_dir = cfg.cache_dir / "registry_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backup_dir / f"registry_{stamp}_{uuid.uuid4().hex[:6]}.json"
        backup_path.write_bytes(existing_registry_bytes)

    safe_extract_zip(artifact.zip_path, package_dir)
    disk_file_hashes = compute_directory_file_hashes(package_dir)
    if disk_file_hashes != zip_file_hashes:
        raise DeployError(
            f"plugin_files_changed: 落盘文件哈希与 ZIP 不一致 ({cfg.redact_path(package_dir)})。"
        )

    updated_registry, enabled, replaced_old_sha = merge_registry_plugin_entry(
        current_registry,
        plugin_id=plugin_id,
        plugin_manifest=zip_plugin_manifest,
        sha256=sha256,
        file_hashes=disk_file_hashes,
        allow_same_version=allow_same_version,
    )
    _atomic_write_utf8_json(registry_path, updated_registry)

    cleaned_old_dir: Path | None = None
    if replaced_old_sha and replaced_old_sha != sha256:
        plugin_pkg_root = (session_plugins_dir / "packages" / plugin_id).resolve()
        candidate_old = (plugin_pkg_root / replaced_old_sha).resolve()
        if candidate_old.is_relative_to(plugin_pkg_root) and candidate_old != plugin_pkg_root and candidate_old.is_dir():
            _remove_tree_best_effort(candidate_old)
            cleaned_old_dir = candidate_old

        plugin_cache_root = (session_plugins_dir / "cache" / plugin_id).resolve()
        candidate_old_cache = (plugin_cache_root / f"{replaced_old_sha}.zip").resolve()
        if candidate_old_cache.is_relative_to(plugin_cache_root) and candidate_old_cache.is_file():
            try:
                candidate_old_cache.unlink(missing_ok=True)
            except PermissionError:
                pass

    return SyncResult(
        mod_name=clean_name,
        plugin_id=plugin_id,
        version=version,
        sha256=sha256,
        session_plugins_dir=session_plugins_dir,
        package_dir=package_dir,
        registry_path=registry_path,
        backup_path=backup_path,
        rebuilt=rebuilt,
        dry_run=False,
        enabled=enabled,
        file_hashes_count=len(disk_file_hashes),
        cleaned_old_package_dir=cleaned_old_dir,
    )


def sync_mods(
    config: WorkspaceConfig | None = None,
    *,
    mod_name: str | None = None,
    select_all: bool = False,
    include_template: bool = False,
    dry_run: bool = False,
    target_dir: Path | str | None = None,
    allow_same_version: bool = False,
    godot_bin: Path | str | None = None,
) -> list[SyncResult]:
    """Sync one or multiple plugins into the client `session_plugins` directory."""
    cfg = config or load_config()
    targets = resolve_target_mods(
        cfg,
        mod_name=mod_name,
        select_all=select_all,
        include_template=include_template,
    )
    results: list[SyncResult] = []
    for name in targets:
        results.append(
            sync_mod(
                name,
                config=cfg,
                dry_run=dry_run,
                target_dir=target_dir,
                allow_same_version=allow_same_version,
                godot_bin=godot_bin,
            )
        )
    return results


def discover_built_packages(build_dir: Path) -> list[HostedPackage]:
    """Discover all built `<mod-name>.zip` and `<mod-name>.fup` artifacts under `build/`."""
    if not build_dir.is_dir():
        return []

    packages: list[HostedPackage] = []
    for sub in sorted(build_dir.iterdir(), key=lambda p: p.name):
        if not sub.is_dir() or sub.name.startswith(".") or sub.name == "extracted_pck":
            continue

        plugin_id = sub.name.replace("-", "_")
        version = "0.0.0"
        sha256 = ""
        schema = "fus.session-plugin.v1"
        archive_path: Path | None = None
        archive_ext = ".zip"

        manifest_path = sub / "build-manifest.json"
        if manifest_path.is_file():
            try:
                bm = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                plugin_id = str(bm.get("plugin_id") or plugin_id)
                version = str(bm.get("version") or version)
                sha256 = str(bm.get("sha256") or "")
                schema = str(bm.get("schema") or schema)
                bm_filename = str(bm.get("archive_filename") or bm.get("zip_filename") or "").strip()
                if bm_filename:
                    cand = sub / bm_filename
                    if cand.is_file():
                        archive_path = cand
                        archive_ext = cand.suffix.lower() or str(bm.get("package_ext") or ".zip")
            except (OSError, ValueError):
                pass

        if archive_path is None:
            for ext in (".fup", ".zip"):
                cand = sub / f"{sub.name}{ext}"
                if cand.is_file():
                    archive_path = cand
                    archive_ext = ext
                    break

        if archive_path is None or not archive_path.is_file():
            continue

        if not sha256:
            sha256 = compute_file_sha256(archive_path)

        packages.append(
            HostedPackage(
                mod_name=sub.name,
                plugin_id=plugin_id,
                version=version,
                sha256=sha256,
                zip_path=archive_path,
                zip_size_bytes=archive_path.stat().st_size,
                archive_ext=archive_ext,
                schema=schema,
            )
        )
    return packages


def resolve_hosted_package(request_path: str, build_dir: Path) -> HostedPackage | None:
    """Resolve `/<mod-name>.{zip,fup}` or `/<plugin_id>.{zip,fup}` to a built `HostedPackage`."""
    clean_path = urlsplit(request_path).path.strip("/")
    if "/" in clean_path or "\\" in clean_path or ".." in clean_path:
        return None
    ext = ""
    if clean_path.endswith(".zip"):
        ext = ".zip"
    elif clean_path.endswith(".fup"):
        ext = ".fup"
    else:
        return None
    stem = clean_path[: -len(ext)]
    if not stem:
        return None

    for pkg in discover_built_packages(build_dir):
        if pkg.archive_ext == ext and (stem == pkg.mod_name or stem == pkg.plugin_id):
            return pkg
    return None


def resolve_hosted_zip(request_path: str, build_dir: Path) -> HostedPackage | None:
    """Resolve `/<mod-name>.zip` or `/<plugin_id>.zip` to a built `HostedPackage` (backward-compatible)."""
    clean_path = urlsplit(request_path).path.strip("/")
    if not clean_path.endswith(".zip"):
        return None
    return resolve_hosted_package(request_path, build_dir)


def create_dev_http_server(
    config: WorkspaceConfig | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    quiet: bool = False,
) -> ThreadingHTTPServer:
    """Create a local HTTP server hosting built `.zip` / `.fup` packages with `Cache-Control: no-store`."""
    cfg = config or load_config()
    build_dir = cfg.build_dir

    class PluginPackageHTTPHandler(BaseHTTPRequestHandler):
        server_version = "FuVTTDevServer/0.2"

        def _send_no_store_headers(self, content_type: str, content_length: int) -> None:
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(content_length))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")

        def _handle_request(self, send_body: bool) -> None:
            clean_path = urlsplit(self.path).path
            if clean_path in ("/", "/index.json"):
                pkgs = discover_built_packages(build_dir)
                bound_host, bound_port = self.server.server_address[:2]
                display_host = "127.0.0.1" if bound_host in ("0.0.0.0", "") else bound_host
                catalog = {
                    "service": "fuvtt-devtools-serve",
                    "packages": [
                        {
                            "mod_name": p.mod_name,
                            "plugin_id": p.plugin_id,
                            "schema": p.schema,
                            "format": p.archive_ext.lstrip("."),
                            "version": p.version,
                            "sha256": p.sha256,
                            "size_bytes": p.zip_size_bytes,
                            "url": f"http://{display_host}:{bound_port}/{p.mod_name}{p.archive_ext}",
                            "alias_url": f"http://{display_host}:{bound_port}/{p.plugin_id}{p.archive_ext}",
                        }
                        for p in pkgs
                    ],
                }
                body = (json.dumps(catalog, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                self.send_response(200)
                self._send_no_store_headers("application/json; charset=utf-8", len(body))
                self.end_headers()
                if send_body:
                    self.wfile.write(body)
                return

            pkg = resolve_hosted_package(self.path, build_dir)
            if pkg is None or not pkg.zip_path.is_file():
                err_body = json.dumps(
                    {"error": "not_found", "path": clean_path},
                    ensure_ascii=False,
                ).encode("utf-8")
                self.send_response(404)
                self._send_no_store_headers("application/json; charset=utf-8", len(err_body))
                self.end_headers()
                if send_body:
                    self.wfile.write(err_body)
                return

            data = pkg.zip_path.read_bytes()
            content_type = "application/zip" if pkg.archive_ext == ".zip" else "application/octet-stream"
            self.send_response(200)
            self._send_no_store_headers(content_type, len(data))
            self.send_header("X-Plugin-Id", pkg.plugin_id)
            self.send_header("X-Plugin-Version", pkg.version)
            self.send_header("X-Plugin-SHA256", pkg.sha256)
            self.send_header("X-Plugin-Schema", pkg.schema)
            self.end_headers()
            if send_body:
                self.wfile.write(data)

        def _drain_request_body(self, max_bytes: int = 65536) -> None:
            headers = getattr(self, "headers", None)
            if headers is None:
                return
            raw_len = headers.get("Content-Length")
            if not raw_len:
                return
            try:
                content_len = int(raw_len)
            except ValueError:
                return
            if 0 < content_len <= max_bytes:
                conn = getattr(self, "connection", None)
                prev_timeout = conn.gettimeout() if conn is not None else None
                try:
                    if conn is not None:
                        conn.settimeout(1.0)
                    self.rfile.read(content_len)
                except OSError:
                    pass
                finally:
                    if conn is not None:
                        try:
                            conn.settimeout(prev_timeout)
                        except OSError:
                            pass

        def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
            self._drain_request_body()
            super().send_error(code, message, explain)

        def do_GET(self) -> None:  # noqa: N802
            self._handle_request(send_body=True)

        def do_HEAD(self) -> None:  # noqa: N802
            self._handle_request(send_body=False)

        def log_message(self, fmt: str, *args: Any) -> None:
            if not quiet:
                super().log_message(fmt, *args)

    return ThreadingHTTPServer((host, port), PluginPackageHTTPHandler)


def format_serve_banner(packages: list[HostedPackage], host: str, port: int) -> str:
    """Format human-friendly startup instructions and pasteable URLs for `serve`."""
    display_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    base_url = f"http://{display_host}:{port}"
    lines = [
        f"Fu vtt 本地插件热更新服务已启动：{base_url}/",
        "响应头已启用 Cache-Control: no-store（每次拉取均为最新构建产物）",
        "",
    ]
    if not packages:
        lines.append("当前 build/ 目录下尚无已构建的 .zip / .fup 包。")
        lines.append("请先在另一终端运行：python shared/tools/fuvtt_cli.py build <mod-name>")
    else:
        lines.append("可直接粘贴至客户端【插件面板 -> 链接输入框】的安装地址：")
        for pkg in packages:
            lines.append(
                f"  - [{pkg.mod_name}] (id={pkg.plugin_id}, schema={pkg.schema}, v{pkg.version}, sha256={pkg.sha256[:12]}...)"
            )
            lines.append(f"      主链接:   {base_url}/{pkg.mod_name}{pkg.archive_ext}")
            if pkg.plugin_id != pkg.mod_name:
                lines.append(f"      别名链接: {base_url}/{pkg.plugin_id}{pkg.archive_ext}")

    lines.extend(
        [
            "",
            "免重启热更新流程：",
            "  1. 首次在客户端插件面板粘贴上方 .zip / .fup 链接并点击【安装】；",
            "  2. 修改插件代码后执行：python shared/tools/fuvtt_cli.py build <mod-name> --bump-dev",
            "  3. 回到客户端插件面板点击【检查更新】，即可走原生下载校验管线完成热更新（按 Ctrl+C 停止服务）。",
        ]
    )
    return "\n".join(lines)


def serve_builds(
    config: WorkspaceConfig | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Run blocking local HTTP package server until interrupted."""
    cfg = config or load_config()
    server = create_dev_http_server(cfg, host=host, port=port)
    actual_host, actual_port = server.server_address[:2]
    packages = discover_built_packages(cfg.build_dir)
    print(format_serve_banner(packages, str(actual_host), int(actual_port)), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止本地插件托管服务。", flush=True)
    finally:
        server.server_close()
