"""Godot 4 Embedded PCK v4 extractor and dual-source (Steam PCK + FUS Git) host-contract inspector."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
from typing import Any, BinaryIO, Callable, Mapping
import uuid
import zipfile

from .env_config import DEFAULT_FUS_SOURCE_REF, WorkspaceConfig, load_config


GDPC_MAGIC = b"GDPC"
PACK_DIR_AT_END_FLAG = 2
PCK_HEADER_FILE_BASE_V4 = 112

BUILTIN_FOBR_ZIP_REL = "plugin_packages/fobr-world-import.zip"
BUILD_IDENTITY_REL = "data/build_identity.json"

# Steam / Practice Embedded PCK monitored contract files (v0.0.53 ~ v0.0.57+)
CONTRACT_WATCH_FILES: tuple[str, ...] = (
    "project.binary",
    "services/plugins/session_plugins.gdc",
    "scenes/session/plugins/plugin_import.gdc",
    "scenes/session/plugins/import_bridge.gdc",
    "scenes/session/plugins/plugin_panel.gdc",
    "scenes/session/plugins/session_plugin_drop.gdc",
    "scenes/systems/world/world_defaults.gdc",
    "scenes/extension/desktop_feature_catalog.gdc",
    "scenes/board/networking/network_session.gdc",
    "services/storage_paths.gdc",
    "services/storage_bootstrap.gdc",
    "modules/obstacle_authoring/obstacle_shape_data.gdc",
)

# External non-PCK Steam install files monitored alongside FUS.exe
STEAM_EXTERNAL_PRACTICE_DLL_REL = "data_Practice_windows_x86_64/Practice.dll"
STEAM_EXTERNAL_STORAGE_JSON_REL = "FUS_Data/.fus-storage.json"

# Read-only Practice Git source watch files (queried via `git show <ref>:<path>`)
GIT_PRACTICE_WATCH_FILES: tuple[str, ...] = (
    "project.godot",
    "Practice.csproj",
    "services/plugins/PluginPackageJob.cs",
    "services/plugins/PluginPackageJob.Probe.cs",
    "services/plugins/session_plugins.gd",
    "scenes/session/plugins/import_bridge.gd",
    "scenes/session/plugins/plugin_import.gd",
    "scenes/session/plugins/plugin_panel.gd",
    "scenes/session/plugins/session_plugin_drop.gd",
    "scenes/systems/world/world_defaults.gd",
    "scenes/extension/desktop_feature_catalog.gd",
    "modules/obstacle_authoring/obstacle_shape_data.gd",
    "plugin_packages/fobr_world_import/plugin.json",
)

_PROJECT_GODOT_VERSION_RE = re.compile(r'(?m)^config/version="([^"]+)"')
_VALID_SOURCES = frozenset({"steam", "git", "both"})


class PckFormatError(ValueError):
    """Raised when an executable, PCK container, or read-only Git source fails inspection."""


@dataclass(frozen=True)
class PckEntry:
    """Single resource entry inside a Godot PCK directory table."""

    res_path: str
    rel_path: str
    offset: int
    size: int
    md5: str
    flags: int


@dataclass(frozen=True)
class EmbeddedPckInfo:
    """Parsed header and directory index of an Embedded PCK v4 executable."""

    exe_size: int
    pck_start: int
    pck_size: int
    pack_format: int
    engine_version: str
    pack_flags: int
    file_base: int
    dir_offset: int
    entries: list[PckEntry]


@dataclass
class ContractDiffReport:
    """Structured diff between previous and current client/git contract snapshots."""

    has_previous: bool
    is_clean: bool
    summary_status: str
    client_version_change: dict[str, str | None] | None = None
    builtin_plugin_changes: list[str] = field(default_factory=list)
    changed_contract_files: list[dict[str, Any]] = field(default_factory=list)
    changed_external_files: list[dict[str, Any]] = field(default_factory=list)
    git_version_change: dict[str, str | None] | None = None
    changed_git_files: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class InspectionResult:
    """Combined result of `inspect_client`."""

    snapshot: dict[str, Any]
    snapshot_path: Path
    diff: ContractDiffReport
    extracted_files_count: int = 0


def _sanitize_res_path(res_path: str) -> str:
    clean = res_path
    if clean.startswith("res://"):
        clean = clean[len("res://") :]
    clean = clean.lstrip("/")
    if "\\" in clean or ":" in clean:
        raise PckFormatError(f"PCK 条目包含非法字符路径：{res_path!r}")
    parts = [p for p in clean.split("/") if p != ""]
    if not parts or ".." in parts:
        raise PckFormatError(f"PCK 条目包含路径穿越：{res_path!r}")
    return "/".join(parts)


def parse_embedded_pck_stream(fp: BinaryIO) -> EmbeddedPckInfo:
    """Parse Godot Embedded PCK v4 trailer, header, and directory table from a binary stream."""
    fp.seek(0, os.SEEK_END)
    exe_size = fp.tell()
    if exe_size < 52:
        raise PckFormatError(f"文件过小 ({exe_size} 字节)，不包含有效的 Embedded PCK 结构。")

    fp.seek(-12, os.SEEK_END)
    trailer = fp.read(12)
    pck_size = struct.unpack("<Q", trailer[:8])[0]
    trailer_magic = trailer[8:12]
    if trailer_magic != GDPC_MAGIC:
        raise PckFormatError(
            f"未检测到 Embedded PCK 尾部魔数 'GDPC'（实际读取：{trailer_magic!r}）。"
        )

    pck_start = exe_size - 12 - pck_size
    if pck_start < 0 or pck_start >= exe_size - 12:
        raise PckFormatError(
            f"非法 PCK 起始偏移计算结果：exe_size={exe_size}, pck_size={pck_size}, pck_start={pck_start}"
        )

    fp.seek(pck_start)
    header_magic = fp.read(4)
    if header_magic != GDPC_MAGIC:
        raise PckFormatError(
            f"偏移 {pck_start} 处未找到 PCK 头部魔数 'GDPC'（实际读取：{header_magic!r}）。"
        )

    header_raw = fp.read(36)
    if len(header_raw) < 36:
        raise PckFormatError("PCK 头部字段不完整。")

    pack_format, v_maj, v_min, v_pat, pack_flags = struct.unpack("<IIIII", header_raw[:20])
    file_base, dir_offset = struct.unpack("<QQ", header_raw[20:36])

    dir_abs_offset = pck_start + dir_offset
    if dir_abs_offset < pck_start or dir_abs_offset > exe_size - 16:
        raise PckFormatError(f"PCK 目录表偏移越界：dir_offset={dir_offset}")

    fp.seek(dir_abs_offset)
    count_raw = fp.read(4)
    if len(count_raw) < 4:
        raise PckFormatError("无法读取 PCK 目录表条目数量。")
    file_count = struct.unpack("<I", count_raw)[0]
    if file_count > 500_000:
        raise PckFormatError(f"PCK 目录条目数异常过大：{file_count}")

    entries: list[PckEntry] = []
    for idx in range(file_count):
        plen_raw = fp.read(4)
        if len(plen_raw) < 4:
            raise PckFormatError(f"目录表在第 {idx} 项提前截断。")
        path_len = struct.unpack("<I", plen_raw)[0]
        if path_len == 0 or path_len > 8192:
            raise PckFormatError(f"目录表第 {idx} 项路径长度非法：{path_len}")

        path_bytes = fp.read(path_len)
        if len(path_bytes) < path_len:
            raise PckFormatError(f"目录表第 {idx} 项路径字节截断。")
        res_path = path_bytes.decode("utf-8", errors="replace").rstrip("\x00")
        rel_path = _sanitize_res_path(res_path)

        meta_raw = fp.read(36)
        if len(meta_raw) < 36:
            raise PckFormatError(f"目录表第 {idx} 项元数据截断。")
        offset, size = struct.unpack("<QQ", meta_raw[:16])
        md5_hex = meta_raw[16:32].hex()
        entry_flags = struct.unpack("<I", meta_raw[32:36])[0]

        phys_offset = pck_start + file_base + offset
        if phys_offset < pck_start or phys_offset + size > exe_size - 12:
            raise PckFormatError(
                f"PCK 条目 '{res_path}' 数据区间越界 (offset={offset}, size={size})。"
            )

        entries.append(
            PckEntry(
                res_path=res_path,
                rel_path=rel_path,
                offset=offset,
                size=size,
                md5=md5_hex,
                flags=entry_flags,
            )
        )

    return EmbeddedPckInfo(
        exe_size=exe_size,
        pck_start=pck_start,
        pck_size=pck_size,
        pack_format=pack_format,
        engine_version=f"{v_maj}.{v_min}.{v_pat}",
        pack_flags=pack_flags,
        file_base=file_base,
        dir_offset=dir_offset,
        entries=entries,
    )


def parse_embedded_pck(exe_path: Path) -> EmbeddedPckInfo:
    """Parse Embedded PCK metadata and directory index from `FUS.exe`."""
    with exe_path.open("rb") as fp:
        return parse_embedded_pck_stream(fp)


def extract_embedded_pck(exe_path: Path, output_dir: Path) -> tuple[EmbeddedPckInfo, int]:
    """Extract all resources from an Embedded PCK v4 executable into `output_dir`."""
    resolved_out = output_dir.resolve()
    resolved_out.mkdir(parents=True, exist_ok=True)

    with exe_path.open("rb") as fp:
        info = parse_embedded_pck_stream(fp)
        extracted_count = 0
        for entry in info.entries:
            target_file = (resolved_out / Path(*entry.rel_path.split("/"))).resolve()
            if not target_file.is_relative_to(resolved_out):
                raise PckFormatError(f"安全拦截：解包目标越界 '{entry.rel_path}'")

            target_file.parent.mkdir(parents=True, exist_ok=True)
            fp.seek(info.pck_start + info.file_base + entry.offset)
            remaining = entry.size
            with target_file.open("wb") as out_fp:
                while remaining > 0:
                    chunk = fp.read(min(65536, remaining))
                    if not chunk:
                        raise PckFormatError(f"读取条目 '{entry.rel_path}' 时意外遇到 EOF。")
                    out_fp.write(chunk)
                    remaining -= len(chunk)
            extracted_count += 1

    return info, extracted_count


def build_synthetic_embedded_pck_exe(
    files: Mapping[str, bytes],
    *,
    pe_stub: bytes = b"MZ\x90\x00FAKE_PE_HEADER_STUB_FOR_TEST",
    engine_version: tuple[int, int, int] = (4, 8, 0),
    pack_format: int = 4,
) -> bytes:
    """Build a spec-compliant Godot 4 Embedded PCK (`PACK_DIR_AT_END`) binary for testing."""
    buf = io.BytesIO()
    buf.write(pe_stub)
    while buf.tell() % 8 != 0:
        buf.write(b"\x00")

    pck_start = buf.tell()
    file_base = PCK_HEADER_FILE_BASE_V4
    buf.write(b"\x00" * file_base)

    dir_records: list[tuple[str, int, int, bytes]] = []
    for raw_path in sorted(files.keys()):
        payload = files[raw_path]
        res_path = raw_path if raw_path.startswith("res://") else f"res://{raw_path.lstrip('/')}"
        rel_offset = (buf.tell() - pck_start) - file_base
        buf.write(payload)
        while (buf.tell() - pck_start) % 8 != 0:
            buf.write(b"\x00")
        md5_digest = hashlib.md5(payload).digest()
        dir_records.append((res_path, rel_offset, len(payload), md5_digest))

    dir_offset = buf.tell() - pck_start
    buf.write(struct.pack("<I", len(dir_records)))
    for res_path, rel_offset, size, md5_digest in dir_records:
        encoded_path = res_path.encode("utf-8") + b"\x00"
        pad_len = (4 - (len(encoded_path) % 4)) % 4
        encoded_path += b"\x00" * pad_len
        buf.write(struct.pack("<I", len(encoded_path)))
        buf.write(encoded_path)
        buf.write(struct.pack("<QQ", rel_offset, size))
        buf.write(md5_digest)
        buf.write(struct.pack("<I", 0))

    pck_end = buf.tell()
    pck_size = pck_end - pck_start
    buf.write(struct.pack("<Q", pck_size))
    buf.write(GDPC_MAGIC)

    v_maj, v_min, v_pat = engine_version
    header = io.BytesIO()
    header.write(GDPC_MAGIC)
    header.write(struct.pack("<IIIII", pack_format, v_maj, v_min, v_pat, PACK_DIR_AT_END_FLAG))
    header.write(struct.pack("<QQ", file_base, dir_offset))
    header.write(b"\x00" * (file_base - 40))

    full_bytes = bytearray(buf.getvalue())
    full_bytes[pck_start : pck_start + file_base] = header.getvalue()
    return bytes(full_bytes)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _inspect_fobr_zip_bytes(zip_bytes: bytes) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "exists": True,
        "zip_size_bytes": len(zip_bytes),
        "zip_sha256": _sha256_bytes(zip_bytes),
        "manifest": None,
        "entry_gd_sha256": None,
    }
    with zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r") as zf:
        names = set(zf.namelist())
        manifest_entry_name = "entry.gd"
        if "plugin.json" in names:
            raw_manifest = json.loads(zf.read("plugin.json").decode("utf-8-sig"))
            if isinstance(raw_manifest, dict):
                manifest_entry_name = str(raw_manifest.get("entry") or "entry.gd")
                summary["manifest"] = {
                    "schema": raw_manifest.get("schema"),
                    "host_api": raw_manifest.get("host_api"),
                    "scope": raw_manifest.get("scope"),
                    "id": raw_manifest.get("id"),
                    "version": raw_manifest.get("version"),
                    "entry": manifest_entry_name,
                    "import_extensions": raw_manifest.get("import_extensions"),
                }
        if manifest_entry_name in names:
            summary["entry_gd_sha256"] = _sha256_bytes(zf.read(manifest_entry_name))
    return summary


def _inspect_steam_external_files(install_dir: Path | None) -> dict[str, dict[str, Any]]:
    """Inspect non-PCK Steam install artifacts (`Practice.dll` and `FUS_Data/.fus-storage.json`)."""
    results: dict[str, dict[str, Any]] = {}
    if install_dir is None or not install_dir.is_dir():
        results[STEAM_EXTERNAL_PRACTICE_DLL_REL] = {"exists": False, "size_bytes": None, "sha256": None}
        results[STEAM_EXTERNAL_STORAGE_JSON_REL] = {
            "exists": False,
            "size_bytes": None,
            "sha256": None,
            "format": None,
            "profile_schema": None,
        }
        return results

    dll_path = install_dir / Path(*STEAM_EXTERNAL_PRACTICE_DLL_REL.split("/"))
    if dll_path.is_file():
        results[STEAM_EXTERNAL_PRACTICE_DLL_REL] = {
            "exists": True,
            "size_bytes": dll_path.stat().st_size,
            "sha256": _sha256_file(dll_path),
        }
    else:
        results[STEAM_EXTERNAL_PRACTICE_DLL_REL] = {"exists": False, "size_bytes": None, "sha256": None}

    storage_path = install_dir / Path(*STEAM_EXTERNAL_STORAGE_JSON_REL.split("/"))
    if storage_path.is_file():
        raw_bytes = storage_path.read_bytes()
        fmt = None
        schema_ver = None
        try:
            parsed = json.loads(raw_bytes.decode("utf-8-sig"))
            if isinstance(parsed, dict):
                fmt = parsed.get("format")
                schema_ver = parsed.get("profile_schema")
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        results[STEAM_EXTERNAL_STORAGE_JSON_REL] = {
            "exists": True,
            "size_bytes": len(raw_bytes),
            "sha256": _sha256_bytes(raw_bytes),
            "format": fmt,
            "profile_schema": schema_ver,
        }
    else:
        results[STEAM_EXTERNAL_STORAGE_JSON_REL] = {
            "exists": False,
            "size_bytes": None,
            "sha256": None,
            "format": None,
            "profile_schema": None,
        }
    return results


def _run_git_readonly(repo_dir: Path, args: list[str]) -> subprocess.CompletedProcess[bytes]:
    """Execute a strictly read-only git command against `repo_dir`."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except OSError as exc:
        raise PckFormatError(f"无法执行只读 git 命令：{exc}") from exc


def inspect_git_source(
    repo_dir: Path,
    git_ref: str = DEFAULT_FUS_SOURCE_REF,
    *,
    watch_files: tuple[str, ...] = GIT_PRACTICE_WATCH_FILES,
    redacted_repo_label: str = "<FUS_REPO_DIR>",
) -> dict[str, Any]:
    """Stream-inspect a Git ref inside the official FUS repo without modifying or checking out anything."""
    if not repo_dir.is_dir():
        raise PckFormatError(f"官方 FUS 只读源码仓不存在：{redacted_repo_label}")

    rev_proc = _run_git_readonly(repo_dir, ["show", "-s", "--format=%H|%h|%cI|%s", git_ref])
    if rev_proc.returncode != 0:
        err_text = rev_proc.stderr.decode("utf-8", errors="replace").strip()
        raise PckFormatError(f"无法在 {redacted_repo_label} 解析 Git 引用 '{git_ref}'：{err_text}")

    meta_line = rev_proc.stdout.decode("utf-8", errors="replace").strip()
    parts = meta_line.split("|", 3)
    commit_full = parts[0] if len(parts) > 0 else ""
    commit_short = parts[1] if len(parts) > 1 else ""
    commit_date = parts[2] if len(parts) > 2 else ""
    commit_subject = parts[3] if len(parts) > 3 else ""

    file_records: dict[str, dict[str, Any]] = {}
    raw_blobs: dict[str, bytes] = {}
    for rel_path in watch_files:
        show_proc = _run_git_readonly(repo_dir, ["show", f"{git_ref}:{rel_path}"])
        if show_proc.returncode == 0:
            blob = show_proc.stdout
            raw_blobs[rel_path] = blob
            file_records[rel_path] = {
                "exists": True,
                "size_bytes": len(blob),
                "sha256": _sha256_bytes(blob),
            }
        else:
            file_records[rel_path] = {
                "exists": False,
                "size_bytes": None,
                "sha256": None,
            }

    app_version: str | None = None
    if "project.godot" in raw_blobs:
        pg_text = raw_blobs["project.godot"].decode("utf-8", errors="replace")
        ver_match = _PROJECT_GODOT_VERSION_RE.search(pg_text)
        if ver_match:
            raw_ver = ver_match.group(1).strip()
            app_version = raw_ver if raw_ver.startswith("v") else f"v{raw_ver}"

    fobr_manifest: dict[str, Any] | None = None
    if "plugin_packages/fobr_world_import/plugin.json" in raw_blobs:
        try:
            parsed_m = json.loads(raw_blobs["plugin_packages/fobr_world_import/plugin.json"].decode("utf-8-sig"))
            if isinstance(parsed_m, dict):
                fobr_manifest = {
                    "schema": parsed_m.get("schema"),
                    "host_api": parsed_m.get("host_api"),
                    "scope": parsed_m.get("scope"),
                    "id": parsed_m.get("id"),
                    "version": parsed_m.get("version"),
                }
        except (UnicodeDecodeError, json.JSONDecodeError):
            fobr_manifest = None

    return {
        "repo": redacted_repo_label,
        "ref": git_ref,
        "commit": commit_short,
        "commit_full": commit_full,
        "commit_date": commit_date,
        "commit_subject": commit_subject,
        "version": app_version,
        "fobr_manifest": fobr_manifest,
        "watch_files": file_records,
    }


def _build_snapshot_from_reader(
    read_file_fn: Callable[[str], bytes | None],
    *,
    source_label: str,
    pck_info: EmbeddedPckInfo | None = None,
    external_files: dict[str, dict[str, Any]] | None = None,
    git_source: dict[str, Any] | None = None,
    inspect_mode: str = "steam",
) -> dict[str, Any]:
    build_identity: dict[str, Any] | None = None
    raw_identity = read_file_fn(BUILD_IDENTITY_REL)
    if raw_identity is not None:
        try:
            parsed_id = json.loads(raw_identity.decode("utf-8-sig"))
            if isinstance(parsed_id, dict):
                build_identity = {
                    "version": parsed_id.get("version"),
                    "commit": parsed_id.get("commit"),
                    "build_date": parsed_id.get("build-date") or parsed_id.get("build_date"),
                    "dirty": parsed_id.get("dirty"),
                }
        except (UnicodeDecodeError, json.JSONDecodeError):
            build_identity = {"parse_error": True}

    raw_fobr_zip = read_file_fn(BUILTIN_FOBR_ZIP_REL)
    if raw_fobr_zip is not None:
        builtin_plugin = _inspect_fobr_zip_bytes(raw_fobr_zip)
    else:
        builtin_plugin = {
            "exists": False,
            "zip_size_bytes": None,
            "zip_sha256": None,
            "manifest": None,
            "entry_gd_sha256": None,
        }

    contract_files: dict[str, dict[str, Any]] = {}
    for rel_path in CONTRACT_WATCH_FILES:
        file_bytes = read_file_fn(rel_path)
        if file_bytes is None:
            contract_files[rel_path] = {
                "exists": False,
                "size_bytes": None,
                "sha256": None,
            }
        else:
            contract_files[rel_path] = {
                "exists": True,
                "size_bytes": len(file_bytes),
                "sha256": _sha256_bytes(file_bytes),
            }

    pck_header: dict[str, Any] | None = None
    if pck_info is not None:
        pck_header = {
            "pack_format": pck_info.pack_format,
            "engine_version": pck_info.engine_version,
            "pack_flags": pck_info.pack_flags,
            "file_count": len(pck_info.entries),
            "pck_size": pck_info.pck_size,
            "exe_size": pck_info.exe_size,
        }

    return {
        "schema_version": 2,
        "inspect_mode": inspect_mode,
        "inspected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source_label,
        "pck_header": pck_header,
        "build_identity": build_identity,
        "builtin_plugin": builtin_plugin,
        "contract_files": contract_files,
        "external_files": external_files if external_files is not None else {},
        "git_source": git_source,
    }


def _diff_file_maps(
    prev_files: Mapping[str, Any],
    curr_files: Mapping[str, Any],
) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    all_keys = sorted(set(prev_files.keys()) | set(curr_files.keys()))
    for path_key in all_keys:
        pf = prev_files.get(path_key) or {}
        cf = curr_files.get(path_key) or {}
        p_exists = bool(pf.get("exists"))
        c_exists = bool(cf.get("exists"))
        p_sha = pf.get("sha256")
        c_sha = cf.get("sha256")

        if p_exists and not c_exists:
            changed.append({"path": path_key, "change": "removed", "old_sha256": p_sha, "new_sha256": None})
        elif not p_exists and c_exists:
            changed.append({"path": path_key, "change": "added", "old_sha256": None, "new_sha256": c_sha})
        elif p_sha != c_sha:
            changed.append({"path": path_key, "change": "modified", "old_sha256": p_sha, "new_sha256": c_sha})
    return changed


def compare_snapshots(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any],
) -> ContractDiffReport:
    """Compare two client/git contract snapshots and generate a structured drift report."""
    if previous is None:
        return ContractDiffReport(
            has_previous=False,
            is_clean=True,
            summary_status="INITIAL_BASELINE",
        )

    prev_id = previous.get("build_identity") or {}
    curr_id = current.get("build_identity") or {}
    prev_ver = prev_id.get("version") if isinstance(prev_id, dict) else None
    curr_ver = curr_id.get("version") if isinstance(curr_id, dict) else None
    version_change = None
    if prev_ver != curr_ver:
        version_change = {"from": prev_ver, "to": curr_ver}

    plugin_changes: list[str] = []
    prev_bp = previous.get("builtin_plugin") or {}
    curr_bp = current.get("builtin_plugin") or {}
    if isinstance(prev_bp, dict) and isinstance(curr_bp, dict):
        if prev_bp.get("exists") != curr_bp.get("exists"):
            plugin_changes.append(
                f"builtin fobr-world-import.zip exists: {prev_bp.get('exists')} -> {curr_bp.get('exists')}"
            )
        prev_m = prev_bp.get("manifest") or {}
        curr_m = curr_bp.get("manifest") or {}
        if isinstance(prev_m, dict) and isinstance(curr_m, dict):
            for key in ("schema", "host_api", "scope", "version"):
                if prev_m.get(key) != curr_m.get(key):
                    plugin_changes.append(
                        f"builtin plugin.json '{key}': {prev_m.get(key)!r} -> {curr_m.get(key)!r}"
                    )
        if prev_bp.get("entry_gd_sha256") != curr_bp.get("entry_gd_sha256"):
            plugin_changes.append(
                f"builtin entry.gd sha256: {prev_bp.get('entry_gd_sha256')} -> {curr_bp.get('entry_gd_sha256')}"
            )

    changed_files = _diff_file_maps(
        previous.get("contract_files") or {},
        current.get("contract_files") or {},
    )

    prev_ext = previous.get("external_files") or {}
    curr_ext = current.get("external_files") or {}
    changed_external_files = _diff_file_maps(prev_ext, curr_ext) if (prev_ext and curr_ext) else []

    prev_git = previous.get("git_source")
    curr_git = current.get("git_source")
    git_version_change = None
    changed_git_files: list[dict[str, Any]] = []
    if isinstance(prev_git, Mapping) and isinstance(curr_git, Mapping):
        if prev_git.get("version") != curr_git.get("version") or prev_git.get("commit") != curr_git.get("commit"):
            git_version_change = {
                "from": f"{prev_git.get('version') or '?'} ({prev_git.get('commit') or '?'})",
                "to": f"{curr_git.get('version') or '?'} ({curr_git.get('commit') or '?'})",
            }
        changed_git_files = _diff_file_maps(
            prev_git.get("watch_files") or {},
            curr_git.get("watch_files") or {},
        )

    is_clean = (
        len(plugin_changes) == 0
        and len(changed_files) == 0
        and len(changed_external_files) == 0
        and len(changed_git_files) == 0
    )
    status = "CLEAN / NO BREAKING CHANGES" if is_clean else "CONTRACT_DRIFT_DETECTED"

    return ContractDiffReport(
        has_previous=True,
        is_clean=is_clean,
        summary_status=status,
        client_version_change=version_change,
        builtin_plugin_changes=plugin_changes,
        changed_contract_files=changed_files,
        changed_external_files=changed_external_files,
        git_version_change=git_version_change,
        changed_git_files=changed_git_files,
    )


def _atomic_write_snapshot(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").replace("\r\n", "\n").encode("utf-8")
    try:
        with tmp.open("wb") as fp:
            fp.write(payload)
            fp.flush()
            os.fsync(fp.fileno())
        try:
            os.replace(tmp, path)
        except PermissionError:
            # Windows sandbox fallback when replacing a pre-existing cross-session file
            with path.open("wb") as dst_fp:
                dst_fp.write(payload)
                dst_fp.flush()
                os.fsync(dst_fp.fileno())
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def inspect_client(
    config: WorkspaceConfig | None = None,
    *,
    extract: bool = False,
    exe_path: Path | str | None = None,
    extracted_dir: Path | str | None = None,
    snapshot_path: Path | str | None = None,
    source: str = "steam",
    git_ref: str | None = None,
    fus_repo_dir: Path | str | None = None,
) -> InspectionResult:
    """Inspect Fu vtt Steam PCK and/or official FUS Git source ref and diff against baseline."""
    cfg = config or load_config()
    norm_source = (source or "steam").strip().lower()
    if norm_source == "auto":
        has_repo = (fus_repo_dir is not None and str(fus_repo_dir).strip() != "") or (
            cfg.fus_repo_dir is not None and cfg.fus_repo_dir.is_dir()
        )
        norm_source = "both" if has_repo else "steam"
    if norm_source not in _VALID_SOURCES:
        raise PckFormatError(f"不支持的巡检数据源 '{source}'，仅允许：steam、git、both。")

    target_extracted = (
        Path(extracted_dir).resolve()
        if extracted_dir is not None
        else (cfg.build_dir / "extracted_pck").resolve()
    )
    target_snapshot = (
        Path(snapshot_path).resolve()
        if snapshot_path is not None
        else (cfg.cache_dir / "client_contract_snapshot.json").resolve()
    )

    if not target_snapshot.is_relative_to(cfg.workspace_root):
        raise PckFormatError(f"安全拦截：快照输出路径必须位于工作区内部：{target_snapshot}")

    git_source_data: dict[str, Any] | None = None
    if norm_source in ("git", "both"):
        resolved_repo = cfg.resolve_fus_repo_dir(override_repo=fus_repo_dir)
        effective_ref = (git_ref or cfg.fus_source_ref or DEFAULT_FUS_SOURCE_REF).strip()
        git_source_data = inspect_git_source(
            resolved_repo,
            effective_ref,
            redacted_repo_label=cfg.redact_path(resolved_repo),
        )

    pck_info: EmbeddedPckInfo | None = None
    extracted_count = 0

    if norm_source == "git":
        snapshot = {
            "schema_version": 2,
            "inspect_mode": "git",
            "inspected_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": f"{git_source_data['repo']}@{git_source_data['ref']}",
            "pck_header": None,
            "build_identity": None,
            "builtin_plugin": {"exists": False, "zip_size_bytes": None, "zip_sha256": None, "manifest": None, "entry_gd_sha256": None},
            "contract_files": {},
            "external_files": {},
            "git_source": git_source_data,
        }
    else:
        install_root_for_external: Path | None = cfg.fuvtt_install_dir
        if exe_path is not None and str(exe_path).strip():
            install_root_for_external = Path(exe_path).expanduser().resolve().parent

        external_files = _inspect_steam_external_files(install_root_for_external)

        if extract:
            if not target_extracted.is_relative_to(cfg.workspace_root):
                raise PckFormatError(f"安全拦截：PCK 解包输出目录必须位于工作区内部：{target_extracted}")
            resolved_exe = cfg.resolve_client_exe(override_exe=exe_path)
            if not resolved_exe.is_file():
                raise FileNotFoundError(f"找不到客户端可执行文件：{cfg.redact_path(resolved_exe)}")
            pck_info, extracted_count = extract_embedded_pck(resolved_exe, target_extracted)

        if exe_path is not None and not extract and extracted_dir is None:
            resolved_exe = cfg.resolve_client_exe(override_exe=exe_path)
            if not resolved_exe.is_file():
                raise FileNotFoundError(f"找不到客户端可执行文件：{cfg.redact_path(resolved_exe)}")
            with resolved_exe.open("rb") as fp:
                pck_info = parse_embedded_pck_stream(fp)
                entry_map = {e.rel_path: e for e in pck_info.entries}

                def _read_from_exe(rel: str) -> bytes | None:
                    ent = entry_map.get(rel)
                    if ent is None:
                        return None
                    fp.seek(pck_info.pck_start + pck_info.file_base + ent.offset)
                    return fp.read(ent.size)

                snapshot = _build_snapshot_from_reader(
                    _read_from_exe,
                    source_label=cfg.redact_path(resolved_exe),
                    pck_info=pck_info,
                    external_files=external_files,
                    git_source=git_source_data,
                    inspect_mode=norm_source,
                )
        elif target_extracted.is_dir():
            def _read_from_dir(rel: str) -> bytes | None:
                candidate = target_extracted / Path(*rel.split("/"))
                if candidate.is_file():
                    return candidate.read_bytes()
                return None

            try:
                rel_label = target_extracted.relative_to(cfg.workspace_root).as_posix()
            except ValueError:
                rel_label = cfg.redact_path(target_extracted)

            snapshot = _build_snapshot_from_reader(
                _read_from_dir,
                source_label=rel_label,
                pck_info=pck_info,
                external_files=external_files,
                git_source=git_source_data,
                inspect_mode=norm_source,
            )
        else:
            resolved_exe = cfg.resolve_client_exe(override_exe=exe_path)
            if not resolved_exe.is_file():
                raise FileNotFoundError(
                    f"未找到已解包目录 '{cfg.redact_path(target_extracted)}'，且客户端可执行文件不存在：{cfg.redact_path(resolved_exe)}"
                )
            with resolved_exe.open("rb") as fp:
                pck_info = parse_embedded_pck_stream(fp)
                entry_map = {e.rel_path: e for e in pck_info.entries}

                def _read_from_default_exe(rel: str) -> bytes | None:
                    ent = entry_map.get(rel)
                    if ent is None:
                        return None
                    fp.seek(pck_info.pck_start + pck_info.file_base + ent.offset)
                    return fp.read(ent.size)

                snapshot = _build_snapshot_from_reader(
                    _read_from_default_exe,
                    source_label=cfg.redact_path(resolved_exe),
                    pck_info=pck_info,
                    external_files=external_files,
                    git_source=git_source_data,
                    inspect_mode=norm_source,
                )

    previous_snapshot: dict[str, Any] | None = None
    if target_snapshot.is_file():
        try:
            loaded = json.loads(target_snapshot.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                previous_snapshot = loaded
        except (OSError, ValueError):
            previous_snapshot = None

    diff = compare_snapshots(previous_snapshot, snapshot)
    try:
        _atomic_write_snapshot(target_snapshot, snapshot)
    except PermissionError:
        same_schema = (
            isinstance(previous_snapshot, dict)
            and previous_snapshot.get("schema_version") == snapshot.get("schema_version")
            and previous_snapshot.get("inspect_mode") == snapshot.get("inspect_mode")
        )
        if not (diff.has_previous and diff.is_clean and same_schema):
            raise

    return InspectionResult(
        snapshot=snapshot,
        snapshot_path=target_snapshot,
        diff=diff,
        extracted_files_count=extracted_count,
    )


def format_inspection_report(result: InspectionResult, config: WorkspaceConfig | None = None) -> str:
    """Format a human-readable summary of dual-source (Steam + Git) contract inspection and diff results."""
    cfg = config or load_config()
    snap = result.snapshot
    diff = result.diff

    lines: list[str] = ["=== Fu vtt 客户端与源码双源宿主契约巡检报告 (Canary Inspector) ==="]
    lines.append(f"巡检模式: {snap.get('inspect_mode', 'steam')} | 分析来源: {snap.get('source')}")
    if result.extracted_files_count > 0:
        lines.append(f"本次解包资源数: {result.extracted_files_count}")

    identity = snap.get("build_identity")
    git_src = snap.get("git_source")

    if isinstance(identity, dict) and isinstance(git_src, dict):
        steam_ver = identity.get("version") or "unknown"
        steam_commit = identity.get("commit") or "unknown"
        git_ver = git_src.get("version") or "unknown"
        git_commit = git_src.get("commit") or "unknown"
        lines.append(
            f"版本代差对照: Steam 线上包 {steam_ver} ({steam_commit}) vs Git {git_src.get('ref')} {git_ver} ({git_commit})"
        )

    pck_hdr = snap.get("pck_header")
    if isinstance(pck_hdr, dict):
        lines.append(
            f"PCK 容器: format=v{pck_hdr.get('pack_format')}, "
            f"engine=Godot {pck_hdr.get('engine_version')}, "
            f"entries={pck_hdr.get('file_count')}"
        )

    if isinstance(identity, dict):
        lines.append(
            f"Steam 客户端版本: {identity.get('version') or 'unknown'} "
            f"(commit={identity.get('commit') or 'unknown'}, date={identity.get('build_date') or 'unknown'})"
        )

    bp = snap.get("builtin_plugin") or {}
    if isinstance(bp, dict) and bp.get("exists"):
        m = bp.get("manifest") or {}
        lines.append(
            f"内置插件契约: schema={m.get('schema')}, host_api={m.get('host_api')}, "
            f"scope={m.get('scope')}, fobr_version={m.get('version')}"
        )
        lines.append(f"内置 entry.gd SHA-256: {bp.get('entry_gd_sha256')}")
    elif snap.get("inspect_mode") != "git":
        lines.append("内置插件契约: [未找到 plugin_packages/fobr-world-import.zip]")

    ext_files = snap.get("external_files") or {}
    if ext_files:
        lines.append("")
        lines.append("Steam 客户端外部程序集与存储标识:")
        for rel_path, meta in ext_files.items():
            if meta.get("exists"):
                extra = f", format={meta['format']}" if meta.get("format") else ""
                lines.append(
                    f"  [OK]      {rel_path} -> {meta.get('sha256')[:16]}... ({meta.get('size_bytes')} B{extra})"
                )
            else:
                lines.append(f"  [MISSING] {rel_path}")

    cfiles = snap.get("contract_files") or {}
    if cfiles:
        lines.append("")
        lines.append("核心宿主字节码/文件指纹 (Steam PCK):")
        for rel_path, meta in cfiles.items():
            if meta.get("exists"):
                lines.append(f"  [OK]      {rel_path} -> {meta.get('sha256')[:16]}... ({meta.get('size_bytes')} B)")
            else:
                lines.append(f"  [MISSING] {rel_path}")

    if isinstance(git_src, dict):
        lines.append("")
        lines.append(
            f"官方 Git 只读源码指纹 ({git_src.get('ref')} @ {git_src.get('commit')}, "
            f"version={git_src.get('version') or 'unknown'}, date={git_src.get('commit_date') or 'unknown'}):"
        )
        for rel_path, meta in (git_src.get("watch_files") or {}).items():
            if meta.get("exists"):
                lines.append(f"  [OK]      {rel_path} -> {meta.get('sha256')[:16]}... ({meta.get('size_bytes')} B)")
            else:
                lines.append(f"  [MISSING] {rel_path}")

    lines.append("")
    lines.append(f"基线比对结果: {diff.summary_status}")
    if diff.client_version_change:
        lines.append(
            f"  Steam 版本变动: {diff.client_version_change['from']} -> {diff.client_version_change['to']}"
        )
    if diff.git_version_change:
        lines.append(
            f"  Git 源码变动:   {diff.git_version_change['from']} -> {diff.git_version_change['to']}"
        )
    if not diff.has_previous:
        lines.append("  首次生成宿主契约基线快照。")
    elif diff.is_clean:
        lines.append("  所有受监控宿主契约、程序集与源码指纹与上一版基线完全一致。")
    else:
        for item in diff.builtin_plugin_changes:
            lines.append(f"  [插件契约变更] {item}")
        for fchg in diff.changed_contract_files:
            lines.append(
                f"  [PCK 宿主变更] {fchg['path']} ({fchg['change']}): "
                f"{(fchg['old_sha256'] or 'none')[:12]} -> {(fchg['new_sha256'] or 'none')[:12]}"
            )
        for echg in diff.changed_external_files:
            lines.append(
                f"  [外部文件变更] {echg['path']} ({echg['change']}): "
                f"{(echg['old_sha256'] or 'none')[:12]} -> {(echg['new_sha256'] or 'none')[:12]}"
            )
        for gchg in diff.changed_git_files:
            lines.append(
                f"  [Git 源码变更] {gchg['path']} ({gchg['change']}): "
                f"{(gchg['old_sha256'] or 'none')[:12]} -> {(gchg['new_sha256'] or 'none')[:12]}"
            )
        lines.append("  建议核查 shared/sdk/fu_sdk/adapters/host_v1_adapter.gd 是否需适配新版宿主接口。")

    try:
        snap_display = result.snapshot_path.relative_to(cfg.workspace_root).as_posix()
    except ValueError:
        snap_display = cfg.redact_path(result.snapshot_path)
    lines.append(f"快照已保存至: {snap_display}")
    return "\n".join(lines)
