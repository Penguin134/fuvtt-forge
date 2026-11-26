"""Static contract validator for Fu vtt session plugins and in-world modules (`validate` subcommand).

Aligned 1-to-1 with Practice host `services/plugins/PluginPackageJob.cs`
(`fus.session-plugin.v1`, `fus.desktop-module.v1`, `fus.plugin.v2`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping
import zipfile

from .env_config import WorkspaceConfig, load_config


EXPECTED_SCHEMA = "fus.session-plugin.v1"
EXPECTED_HOST_API = 1
EXPECTED_SCOPE = "session"

SUPPORTED_SCHEMAS = frozenset(
    {
        "fus.session-plugin.v1",
        "fus.desktop-module.v1",
        "fus.plugin.v2",
    }
)
INWORLD_SCHEMAS = frozenset({"fus.desktop-module.v1", "fus.plugin.v2"})
V2_SCOPES = frozenset({"", "desktop", "world", "hybrid"})

# Exact limits from Practice host `services/plugins/PluginPackageJob.cs`
MAX_PACKAGE_BYTES = 64 * 1024 * 1024        # MaxArchive = 64 MiB (ZIP/.fup archive & single entry)
MAX_EXPANDED_BYTES = 256 * 1024 * 1024      # MaxExpanded = 256 MiB (sum of uncompressed entries)
MAX_MANIFEST_BYTES = 128 * 1024             # plugin.json <= 128 KiB
MIN_ARCHIVE_ENTRIES = 2                     # plugin_file_limit: < 2 rejected
MAX_ARCHIVE_ENTRIES = 1000                  # plugin_file_limit: > 1000 rejected
MAX_NAME_LENGTH = 80                        # name length 1..80
MAX_DESCRIPTION_LENGTH = 2000               # description length <= 2000
MAX_SETTINGS_COUNT = 32                     # settings array <= 32 items
MAX_SETTING_LABEL_LENGTH = 80               # setting.label length 1..80
MAX_SETTING_STRING_DEFAULT_LENGTH = 2048    # setting.default (string) <= 2048
MAX_IMPORT_EXTENSIONS = 8                   # import_extensions <= 8 items
MAX_MODULES_COUNT = 16                      # modules array 1..16 items
MAX_MODULE_ID_LENGTH = 128                  # module.id <= 128 chars
MAX_MODULE_RELATIONS = 32                   # requires/conflicts/suppresses <= 32 items

PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}\Z")
MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}(?:\.[a-z0-9_]{1,63})*\Z")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9._-]+)?\Z")
ENTRY_REL_RE = re.compile(r"^[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*\.gd\Z")
IMPORT_EXT_RE = re.compile(r"^[a-z0-9]{1,12}\Z")
PACK_FILE_RE = re.compile(r"^[a-zA-Z0-9_.-]+\.pck\Z")
SHA256SUMS_LINE_RE = re.compile(r"^([a-fA-F0-9]{64})  (.+)\Z")

EXTENDS_REFCOUNTED_RE = re.compile(r"(?m)^\s*extends\s+RefCounted\b")
FUNC_INSPECT_RE = re.compile(r"(?m)^\s*func\s+inspect_import\s*\(")
FUNC_PREPARE_RE = re.compile(r"(?m)^\s*func\s+prepare_import\s*\(")
CLASS_NAME_RE = re.compile(r"(?m)(?:^|;)\s*class_name\b")

FORBIDDEN_BINARY_EXTENSIONS = frozenset(
    {
        ".dll",
        ".exe",
        ".so",
        ".dylib",
        ".gdextension",
        ".bat",
        ".cmd",
        ".ps1",
        ".sh",
    }
)
GDPC_MAGIC = b"GDPC"
CANONICAL_RUNTIME_FU_SDK_SCRIPTS: tuple[str, ...] = (
    "utils/dag_cloner.gd",
    "utils/bounded_cloner.gd",
    "utils/value_utils.gd",
    "utils/validation_utils.gd",
    "logging/log_bus.gd",
    "plugins/module_registry.gd",
)

TEXT_CHECK_EXTENSIONS = frozenset({".json", ".gd", ".md", ".cfg", ".tscn", ".tres"})
NON_RUNTIME_FILENAMES = frozenset({"AGENTS.md", "README.md", ".gitkeep"})
UTF8_BOM = b"\xef\xbb\xbf"
UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


class ValidationError(ValueError):
    """Raised when validation fails or target plugin selection is invalid."""


@dataclass
class ValidationReport:
    """Detailed static check results for a single plugin directory."""

    mod_name: str
    mod_dir: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manifest: dict[str, Any] | None = None
    estimated_bytes: int = 0
    runtime_file_count: int = 0

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def is_template_mod_name(name: str) -> bool:
    """Return True if `name` is a scaffold template directory (`_template` or `_template-*`)."""
    return name == "_template" or name.startswith("_template-")


def is_forbidden_binary_path(raw_path: str) -> bool:
    """Return True if a path ends with a forbidden native binary or shell script extension."""
    return Path(raw_path).suffix.lower() in FORBIDDEN_BINARY_EXTENSIONS


def is_runtime_file(rel_path: Path) -> bool:
    """Return True if a file inside `mods/<mod-name>/` is packaged into the runtime archive."""
    parts = rel_path.parts
    if not parts:
        return False
    for part in parts:
        if part == "__pycache__" or part.startswith("."):
            return False
    name = rel_path.name
    if name in NON_RUNTIME_FILENAMES:
        return False
    if name.endswith((".pyc", ".pyo")):
        return False
    return True


def is_inworld_runtime_file(rel_path: Path) -> bool:
    """Return True for in-world runtime files (additionally excluding Godot `.uid` sidecars)."""
    return is_runtime_file(rel_path) and rel_path.suffix.lower() != ".uid"


def extract_module_namespace_roots(manifest: Mapping[str, Any], plugin_id: str | None = None) -> list[str]:
    """Extract unique `mods/<id>` / `external_modules/<id>` roots from manifest modules."""
    pid = str(plugin_id if plugin_id is not None else (manifest.get("id") or "")).strip()
    raw_modules = manifest.get("modules")
    if raw_modules is None and isinstance(manifest.get("module"), Mapping):
        raw_modules = [manifest["module"]]
    roots: list[str] = []
    if isinstance(raw_modules, list):
        for item in raw_modules:
            if not isinstance(item, Mapping):
                continue
            raw_scene = item.get("entry_scene")
            if raw_scene is None or raw_scene == "":
                raw_scene = item.get("path")
            scene = raw_scene.strip() if isinstance(raw_scene, str) else ""
            if not scene.startswith("res://"):
                continue
            rel = scene[len("res://") :]
            parts = rel.split("/")
            if len(parts) >= 2 and parts[0] in ("mods", "external_modules"):
                owner = pid or parts[1]
                ns_root = f"{parts[0]}/{owner}"
                if ns_root not in roots:
                    roots.append(ns_root)
    return roots


def resolve_runtime_sdk_bundle(
    sdk_dir: Path | None,
    runtime_sdk_dir: Path | None,
) -> tuple[list[tuple[str, Path]], list[tuple[str, Path]], list[str]]:
    """Resolve `(fu_runtime_items, fu_sdk_items, errors)` from `runtime_manifest.json` or fallback."""
    if runtime_sdk_dir is None or not runtime_sdk_dir.is_dir():
        return ([], [], [])

    errors: list[str] = []
    runtime_rels: list[str] | None = None
    fu_sdk_rels: list[str] | None = None
    manifest_file = runtime_sdk_dir / "runtime_manifest.json"
    if manifest_file.is_file():
        try:
            parsed = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            return ([], [], [f"[fu_runtime/runtime_manifest.json] 解析失败：{exc}"])
        if not isinstance(parsed, dict):
            return ([], [], ["[fu_runtime/runtime_manifest.json] 顶层必须为 JSON Object。"])

        if "runtime_scripts" in parsed:
            raw_rt = parsed.get("runtime_scripts")
            if isinstance(raw_rt, list):
                runtime_rels = []
                for item in raw_rt:
                    if not isinstance(item, str) or check_zip_member_path(item):
                        errors.append(f"[fu_runtime/runtime_manifest.json] 非法 runtime_scripts 条目：{item!r}")
                    else:
                        runtime_rels.append(item)
            else:
                errors.append("[fu_runtime/runtime_manifest.json] runtime_scripts 必须为数组。")
                runtime_rels = []

        if "shared_fu_sdk_scripts" in parsed:
            raw_sdk = parsed.get("shared_fu_sdk_scripts")
            if isinstance(raw_sdk, list):
                fu_sdk_rels = []
                for item in raw_sdk:
                    if not isinstance(item, str) or check_zip_member_path(item):
                        errors.append(f"[fu_runtime/runtime_manifest.json] 非法 shared_fu_sdk_scripts 条目：{item!r}")
                    else:
                        fu_sdk_rels.append(item)
            else:
                errors.append("[fu_runtime/runtime_manifest.json] shared_fu_sdk_scripts 必须为数组。")
                fu_sdk_rels = []

    if runtime_rels is None:
        runtime_rels = [
            f.relative_to(runtime_sdk_dir).as_posix()
            for f in sorted(runtime_sdk_dir.rglob("*.gd"))
            if f.is_file()
            and not any(part.startswith(".") or part == "__pycache__" for part in f.relative_to(runtime_sdk_dir).parts)
        ]

    if fu_sdk_rels is None:
        fu_sdk_rels = list(CANONICAL_RUNTIME_FU_SDK_SCRIPTS)

    runtime_items: list[tuple[str, Path]] = []
    for rel in sorted(dict.fromkeys(runtime_rels)):
        src = runtime_sdk_dir / Path(*rel.split("/"))
        if src.is_file():
            runtime_items.append((rel, src))
        else:
            errors.append(f"[fu_runtime] 缺少 runtime_manifest 声明的脚本：shared/sdk/fu_runtime/{rel}")

    fu_sdk_items: list[tuple[str, Path]] = []
    if sdk_dir is not None and sdk_dir.is_dir():
        for rel in sorted(dict.fromkeys(fu_sdk_rels)):
            src = sdk_dir / Path(*rel.split("/"))
            if src.is_file():
                fu_sdk_items.append((rel, src))
            elif manifest_file.is_file():
                errors.append(f"[fu_runtime] 缺少共享基础脚本：shared/sdk/fu_sdk/{rel}")

    return (runtime_items, fu_sdk_items, errors)


def is_symlink_or_reparse_point(path: Path) -> bool:
    """Return True if `path` is a symlink or a Windows NTFS reparse point (junction/mount)."""
    if path.is_symlink():
        return True
    if os.name == "nt":
        try:
            st = os.lstat(path)
            attrs = getattr(st, "st_file_attributes", 0)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if (attrs & reparse_flag) != 0:
                return True
        except OSError:
            pass
    return False


def check_zip_member_path(raw_name: str) -> list[str]:
    """Validate an archive relative path against `PluginPackageJob.cs:271` rules."""
    issues: list[str] = []
    if not raw_name:
        issues.append("路径为空")
        return issues
    if "\\" in raw_name:
        issues.append(f"路径 '{raw_name}' 包含反斜杠 '\\'（必须使用 POSIX '/' 相对路径）")
    if ":" in raw_name:
        issues.append(f"路径 '{raw_name}' 包含盘符或冒号 ':'")
    if raw_name.startswith("/"):
        issues.append(f"路径 '{raw_name}' 不能以 '/' 开头")

    trimmed = raw_name[:-1] if raw_name.endswith("/") else raw_name
    segments = trimmed.split("/") if trimmed else []
    if not segments:
        issues.append(f"路径 '{raw_name}' 不包含有效路径段")
    for seg in segments:
        if seg == "":
            issues.append(f"路径 '{raw_name}' 包含空路径段 '//'")
        elif seg == "..":
            issues.append(f"路径 '{raw_name}' 包含非法上级目录跳转 '..'")
        elif seg == ".":
            issues.append(f"路径 '{raw_name}' 包含非法当前目录段 '.'")
        elif seg.endswith(".") or seg.endswith(" "):
            issues.append(
                f"路径 '{raw_name}' 的路径段 '{seg}' 以 '.' 或空格结尾（Windows 不安全路径，宿主 unsafe_zip_path 会拒绝）"
            )
    return issues


def _validate_entry_gd_source(entry_text: str, label: str, errors: list[str]) -> None:
    stripped_gd = strip_gdscript_comments(entry_text)
    if not EXTENDS_REFCOUNTED_RE.search(stripped_gd):
        errors.append(f"[{label}] 入口脚本必须声明 'extends RefCounted'。")
    if not FUNC_INSPECT_RE.search(stripped_gd):
        errors.append(f"[{label}] 入口脚本缺少必需生命周期方法 'func inspect_import('。")
    if not FUNC_PREPARE_RE.search(stripped_gd):
        errors.append(f"[{label}] 入口脚本缺少必需生命周期方法 'func prepare_import('。")


def validate_zip_archive(zip_path: Path) -> list[str]:
    """Post-build archive-level validation mirroring `PluginPackageJob.Install` for `.zip` and `.fup`."""
    errors: list[str] = []
    if not zip_path.is_file():
        return [f"归档文件不存在：{zip_path}"]

    zip_size = zip_path.stat().st_size
    if zip_size > MAX_PACKAGE_BYTES:
        errors.append(
            f"归档体积 ({zip_size} B) 超过宿主 64 MiB 上限 ({MAX_PACKAGE_BYTES} B，plugin_download_limit)。"
        )

    try:
        with zipfile.ZipFile(zip_path, mode="r") as zf:
            infos = zf.infolist()
            if len(infos) < MIN_ARCHIVE_ENTRIES or len(infos) > MAX_ARCHIVE_ENTRIES:
                errors.append(
                    f"ZIP 条目数 ({len(infos)}) 越界：宿主 plugin_file_limit 要求在 {MIN_ARCHIVE_ENTRIES}..{MAX_ARCHIVE_ENTRIES} 之间。"
                )

            seen_lower: dict[str, str] = {}
            member_names: set[str] = set()
            total_expanded = 0
            manifest_member: zipfile.ZipInfo | None = None

            for member in infos:
                name = member.filename
                orig_name = getattr(member, "orig_filename", name)
                member_names.add(name)
                path_issues = check_zip_member_path(orig_name)
                if orig_name != name:
                    for issue in check_zip_member_path(name):
                        if issue not in path_issues:
                            path_issues.append(issue)
                if "\x00" in orig_name:
                    path_issues.append(f"路径 {orig_name!r} 包含空字节 '\\x00'")
                for issue in path_issues:
                    errors.append(f"[ZIP unsafe_zip_path] {issue}")

                folded = name.lower()
                if folded in seen_lower:
                    errors.append(
                        f"[ZIP unsafe_zip_path] 检测到 Windows 大小写冲突条目：'{seen_lower[folded]}' 与 '{name}'。"
                    )
                else:
                    seen_lower[folded] = name

                if ((member.external_attr >> 16) & 0xF000) == 0xA000:
                    errors.append(f"[ZIP zip_link_rejected] 拒绝符号链接条目：'{name}'。")

                if not name.endswith("/") and is_forbidden_binary_path(name):
                    errors.append(
                        f"[ZIP unsafe_plugin_binary] 禁止包含可执行/原生二进制或脚本文件：'{name}'。"
                    )

                if member.file_size > MAX_PACKAGE_BYTES:
                    errors.append(
                        f"[ZIP plugin_expanded_limit] 单文件 '{name}' 展开体积 ({member.file_size} B) 超过 64 MiB 上限。"
                    )
                total_expanded += member.file_size
                if total_expanded > MAX_EXPANDED_BYTES:
                    errors.append(
                        f"[ZIP plugin_expanded_limit] 解压总体积超过 256 MiB 上限 ({MAX_EXPANDED_BYTES} B)。"
                    )
                    break

                if name == "plugin.json":
                    manifest_member = member
                    if member.file_size > MAX_MANIFEST_BYTES:
                        errors.append(
                            f"[ZIP plugin_manifest_limit] plugin.json 体积 ({member.file_size} B) 超过 128 KiB 上限 ({MAX_MANIFEST_BYTES} B)。"
                        )

            if manifest_member is None:
                errors.append("[ZIP plugin_manifest_missing] 压缩包根目录缺少 'plugin.json'。")
            elif manifest_member.file_size <= MAX_MANIFEST_BYTES:
                with zf.open(manifest_member, mode="r") as mf:
                    manifest_bytes = mf.read(MAX_MANIFEST_BYTES + 1)
                if len(manifest_bytes) > MAX_MANIFEST_BYTES:
                    errors.append(
                        f"[ZIP plugin_manifest_limit] plugin.json 实际解压体积超过 128 KiB 上限 ({MAX_MANIFEST_BYTES} B)。"
                    )
                else:
                    manifest_text = _decode_utf8_no_bom_bytes(manifest_bytes, "ZIP plugin.json", errors)
                    if manifest_text is not None:
                        try:
                            zip_manifest = json.loads(manifest_text)
                        except json.JSONDecodeError as exc:
                            errors.append(f"[ZIP plugin.json] JSON 语法解析失败：{exc}")
                        else:
                            if not isinstance(zip_manifest, dict):
                                errors.append("[ZIP plugin.json] 顶层结构必须为 JSON Object (字典)。")
                            else:
                                ctx = _validate_manifest_context(zip_manifest, None, errors, [])
                                if ctx.schema not in INWORLD_SCHEMAS:
                                    if ctx.entry_rel is not None:
                                        if ctx.entry_rel not in member_names:
                                            errors.append(
                                                f"[ZIP plugin_entry_missing] 压缩包缺少入口脚本（大小写敏感）：'{ctx.entry_rel}'。"
                                            )
                                        else:
                                            entry_info = zf.getinfo(ctx.entry_rel)
                                            if entry_info.file_size <= MAX_PACKAGE_BYTES:
                                                with zf.open(entry_info, mode="r") as ef:
                                                    entry_bytes = ef.read(MAX_PACKAGE_BYTES + 1)
                                                if len(entry_bytes) <= MAX_PACKAGE_BYTES:
                                                    entry_text = _decode_utf8_no_bom_bytes(
                                                        entry_bytes, f"ZIP {ctx.entry_rel}", errors
                                                    )
                                                    if entry_text is not None:
                                                        _validate_entry_gd_source(
                                                            entry_text, f"ZIP {ctx.entry_rel}", errors
                                                        )
                                elif ctx.schema in INWORLD_SCHEMAS:
                                    if ctx.entry_rel:
                                        if ctx.entry_rel not in member_names:
                                            errors.append(
                                                f"[ZIP plugin_entry_missing] 压缩包缺少混合导入入口脚本（大小写敏感）：'{ctx.entry_rel}'。"
                                            )
                                        else:
                                            entry_info = zf.getinfo(ctx.entry_rel)
                                            if entry_info.file_size <= MAX_PACKAGE_BYTES:
                                                with zf.open(entry_info, mode="r") as ef:
                                                    entry_bytes = ef.read(MAX_PACKAGE_BYTES + 1)
                                                if len(entry_bytes) <= MAX_PACKAGE_BYTES:
                                                    entry_text = _decode_utf8_no_bom_bytes(
                                                        entry_bytes, f"ZIP {ctx.entry_rel}", errors
                                                    )
                                                    if entry_text is not None:
                                                        _validate_entry_gd_source(
                                                            entry_text, f"ZIP {ctx.entry_rel}", errors
                                                        )

                                    if ctx.pack_file:
                                        if ctx.pack_file not in member_names:
                                            errors.append(
                                                f"[ZIP plugin_pack_missing] .fup 归档缺少 pack_file '{ctx.pack_file}'。"
                                            )
                                        else:
                                            pck_info = zf.getinfo(ctx.pack_file)
                                            if pck_info.file_size < 4:
                                                errors.append(
                                                    f"[ZIP invalid_plugin_pack] pack_file '{ctx.pack_file}' 体积过小，缺少 GDPC 魔数。"
                                                )
                                            else:
                                                with zf.open(pck_info, mode="r") as pf:
                                                    magic = pf.read(4)
                                                if magic != GDPC_MAGIC:
                                                    errors.append(
                                                        f"[ZIP invalid_plugin_pack] pack_file '{ctx.pack_file}' 魔数必须为 'GDPC'，实际：{magic!r}。"
                                                    )

                                        if "SHA256SUMS.txt" not in member_names:
                                            errors.append(
                                                "[ZIP plugin_pack_missing] .fup 归档缺少 'SHA256SUMS.txt' 校验清单。"
                                            )
                                        else:
                                            sums_info = zf.getinfo("SHA256SUMS.txt")
                                            if sums_info.file_size > MAX_MANIFEST_BYTES:
                                                errors.append(
                                                    f"[ZIP SHA256SUMS.txt] 校验清单体积 ({sums_info.file_size} B) "
                                                    f"超过 128 KiB 上限 ({MAX_MANIFEST_BYTES} B)。"
                                                )
                                            else:
                                                with zf.open(sums_info, mode="r") as sf:
                                                    sums_bytes = sf.read(MAX_MANIFEST_BYTES + 1)
                                                if len(sums_bytes) > MAX_MANIFEST_BYTES:
                                                    errors.append(
                                                        f"[ZIP SHA256SUMS.txt] 校验清单实际解压体积超过 128 KiB 上限 ({MAX_MANIFEST_BYTES} B)。"
                                                    )
                                                    sums_text = None
                                                else:
                                                    sums_text = _decode_utf8_no_bom_bytes(
                                                        sums_bytes, "ZIP SHA256SUMS.txt", errors
                                                    )
                                                if sums_text is not None:
                                                    parsed_sums: dict[str, str] = {}
                                                    for line_no, raw_line in enumerate(
                                                        sums_text.splitlines(), start=1
                                                    ):
                                                        if not raw_line.strip():
                                                            continue
                                                        m = SHA256SUMS_LINE_RE.match(raw_line)
                                                        if not m:
                                                            errors.append(
                                                                f"[ZIP SHA256SUMS.txt] 第 {line_no} 行格式非法：{raw_line!r}"
                                                            )
                                                            continue
                                                        digest_hex, rel_target = m.group(1).lower(), m.group(2)
                                                        if rel_target in parsed_sums:
                                                            errors.append(
                                                                f"[ZIP SHA256SUMS.txt] 第 {line_no} 行存在重复条目：'{rel_target}'。"
                                                            )
                                                            continue
                                                        parsed_sums[rel_target] = digest_hex
                                                    for required_sum in ("plugin.json", ctx.pack_file):
                                                        if required_sum not in parsed_sums:
                                                            errors.append(
                                                                f"[ZIP SHA256SUMS.txt] 缺少必需条目 '{required_sum}' 的 SHA-256 摘要。"
                                                            )
                                                    for sum_target, expected_hex in parsed_sums.items():
                                                        if sum_target not in member_names:
                                                            errors.append(
                                                                f"[ZIP SHA256SUMS.txt] 清单声明的条目 '{sum_target}' 不存在于归档中。"
                                                            )
                                                        else:
                                                            target_info = zf.getinfo(sum_target)
                                                            if target_info.file_size <= MAX_PACKAGE_BYTES:
                                                                actual_hex = hashlib.sha256(
                                                                    zf.read(target_info)
                                                                ).hexdigest()
                                                                if actual_hex != expected_hex:
                                                                    errors.append(
                                                                        f"[ZIP SHA256SUMS.txt] '{sum_target}' 摘要不匹配 "
                                                                        f"(expected={expected_hex[:12]}..., actual={actual_hex[:12]}...)。"
                                                                    )
                                    else:
                                        if ctx.schema == "fus.desktop-module.v1":
                                            for mname in sorted(member_names):
                                                if mname.lower().endswith(".pck"):
                                                    errors.append(
                                                        f"[ZIP invalid_plugin_pack] fus.desktop-module.v1 纯 ZIP 模式不允许包含 PCK 文件：'{mname}'。"
                                                    )
                                        if ctx.plugin_id:
                                            mod_prefix = f"mods/{ctx.plugin_id}/"
                                            ext_prefix = f"external_modules/{ctx.plugin_id}/"
                                            if not any(
                                                not n.endswith("/")
                                                and (n.startswith(mod_prefix) or n.startswith(ext_prefix))
                                                for n in member_names
                                            ):
                                                errors.append(
                                                    f"[ZIP plugin_pack_missing] 压缩包缺少模块命名空间文件 ('{mod_prefix}' 或 '{ext_prefix}')。"
                                                )
                                        for mod_item in ctx.modules:
                                            raw_scene = mod_item.get("entry_scene")
                                            if raw_scene is None or raw_scene == "":
                                                raw_scene = mod_item.get("path")
                                            scene_val = raw_scene if isinstance(raw_scene, str) else ""
                                            if scene_val.startswith("res://"):
                                                scene_rel = scene_val[len("res://") :]
                                                if scene_rel not in member_names:
                                                    errors.append(
                                                        f"[ZIP plugin_module_scene_missing] 压缩包缺少模块入口场景（大小写敏感）：'{scene_rel}'。"
                                                    )

                                for member in infos:
                                    if not member.filename.endswith("/") and member.filename.lower().endswith(".gd"):
                                        if member.file_size <= MAX_PACKAGE_BYTES:
                                            gd_bytes = zf.read(member)
                                            gd_text = _decode_utf8_no_bom_bytes(
                                                gd_bytes, f"ZIP {member.filename}", errors
                                            )
                                            if gd_text is not None:
                                                if CLASS_NAME_RE.search(strip_gdscript_comments(gd_text)):
                                                    errors.append(
                                                        f"[ZIP {member.filename}] 外置插件/模块脚本禁止声明全局 class_name (global_class_name_not_allowed)。"
                                                    )
    except zipfile.BadZipFile as exc:
        errors.append(f"ZIP 归档损坏：{exc}")

    return errors


validate_fup_archive = validate_zip_archive


def _decode_utf8_no_bom_bytes(raw: bytes, label: str, errors: list[str]) -> str | None:
    if raw.startswith(UTF8_BOM):
        errors.append(f"[{label}] 禁止包含 UTF-8 BOM (\\xef\\xbb\\xbf)。")
        return None
    if raw.startswith(UTF16_BOMS):
        errors.append(f"[{label}] 禁止使用 UTF-16 编码。")
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"[{label}] 非法 UTF-8 编码：{exc}")
        return None


def _resolve_exact_case_rel_path(root: Path, rel_path: str) -> Path | None:
    """Resolve `rel_path` segment-by-segment using exact case-sensitive `os.scandir` matching."""
    cur = root
    for seg in rel_path.split("/"):
        if not seg or seg in (".", "..") or not cur.is_dir():
            return None
        matched: Path | None = None
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    if entry.name == seg:
                        matched = Path(entry.path)
                        break
        except OSError:
            return None
        if matched is None:
            return None
        cur = matched
    return cur


def _validate_manifest_entry_field(manifest: dict[str, Any], errors: list[str]) -> str | None:
    entry_rel = manifest.get("entry")
    if not isinstance(entry_rel, str) or not entry_rel.strip():
        errors.append("[plugin.json] entry 必须为非空字符串（如 'entry.gd'）(invalid_plugin_entry)。")
        return None

    path_issues = _check_safe_relative_path(entry_rel)
    if path_issues:
        for issue in path_issues:
            errors.append(f"[plugin.json] entry {issue} (invalid_plugin_entry)")
        return None

    if not ENTRY_REL_RE.match(entry_rel):
        errors.append(
            f"[plugin.json] entry '{entry_rel}' 不符合宿主正则 '^[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*\\.gd$' (invalid_plugin_entry)。"
        )
        return None

    return entry_rel


@dataclass
class _ManifestValidationContext:
    schema: str
    plugin_id: str
    entry_rel: str | None
    pack_file: str
    modules: list[dict[str, Any]]
    namespace_roots: list[str]


def _validate_settings_array(settings: Any, errors: list[str]) -> None:
    if not isinstance(settings, list):
        errors.append("[plugin.json] settings 必须为数组 (invalid_plugin_settings)。")
        return
    if len(settings) > MAX_SETTINGS_COUNT:
        errors.append(
            f"[plugin.json] settings 项数 ({len(settings)}) 超过宿主上限 {MAX_SETTINGS_COUNT} 项 (invalid_plugin_settings)。"
        )
        return

    seen_setting_ids: set[str] = set()
    for idx, item in enumerate(settings):
        prefix = f"[plugin.json] settings[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{prefix} 必须为对象字典。")
            continue

        sid = item.get("id")
        stype = item.get("type")
        slabel = item.get("label")

        if not isinstance(sid, str) or not PLUGIN_ID_RE.match(sid):
            errors.append(
                f"{prefix}.id 必须匹配宿主正则 '^[a-z][a-z0-9_]{{0,63}}$'，当前值：{sid!r}。"
            )
        elif sid in seen_setting_ids:
            errors.append(f"{prefix}.id '{sid}' 重复定义。")
        else:
            seen_setting_ids.add(sid)

        if not isinstance(slabel, str) or not slabel.strip():
            errors.append(f"{prefix}.label 必须为非空字符串。")
        elif len(slabel) > MAX_SETTING_LABEL_LENGTH:
            errors.append(
                f"{prefix}.label 长度 ({len(slabel)}) 超过宿主上限 {MAX_SETTING_LABEL_LENGTH} 字符。"
            )

        if "placeholder" in item and not isinstance(item["placeholder"], str):
            errors.append(f"{prefix}.placeholder 若提供必须为字符串。")

        if "default" not in item:
            errors.append(f"{prefix} 缺少必需字段 'default'。")
            has_default = False
            sdefault = None
        else:
            has_default = True
            sdefault = item["default"]

        if stype == "bool":
            if has_default and not isinstance(sdefault, bool):
                errors.append(
                    f"{prefix} type='bool' 时 default 必须为布尔值，当前为 {type(sdefault).__name__} ({sdefault!r})。"
                )
        elif stype == "string":
            if has_default and not isinstance(sdefault, str):
                errors.append(
                    f"{prefix} type='string' 时 default 必须为字符串，当前为 {type(sdefault).__name__} ({sdefault!r})。"
                )
            elif has_default and isinstance(sdefault, str) and len(sdefault) > MAX_SETTING_STRING_DEFAULT_LENGTH:
                errors.append(
                    f"{prefix}.default 字符串长度 ({len(sdefault)}) 超过宿主上限 {MAX_SETTING_STRING_DEFAULT_LENGTH} 字符 (plugin_setting_limit)。"
                )
        else:
            errors.append(
                f"{prefix}.type={stype!r} 不受 Practice 宿主契约允许：仅支持 'bool' 或 'string' "
                "(PluginPackageJob.cs:109 安装阶段即直接抛出 invalid_plugin_settings)。"
            )


def _is_valid_module_id(raw_id: Any) -> bool:
    return (
        isinstance(raw_id, str)
        and len(raw_id) <= MAX_MODULE_ID_LENGTH
        and bool(MODULE_ID_RE.match(raw_id))
    )


def _validate_manifest_context(
    manifest: dict[str, Any],
    resolved_name: str | None,
    errors: list[str],
    warnings: list[str],
) -> _ManifestValidationContext:
    raw_schema = manifest.get("schema")
    schema = raw_schema if isinstance(raw_schema, str) else ""
    if schema not in SUPPORTED_SCHEMAS:
        errors.append(
            f"[plugin.json] schema 不受支持，当前值：{raw_schema!r}；"
            f"允许值：{sorted(SUPPORTED_SCHEMAS)} (plugin_host_api_incompatible)。"
        )

    # id: ^[a-z][a-z0-9_]{0,63}\Z
    raw_id = manifest.get("id")
    plugin_id = raw_id if isinstance(raw_id, str) else ""
    if not isinstance(raw_id, str) or not PLUGIN_ID_RE.match(raw_id):
        errors.append(
            f"[plugin.json] id 必须匹配宿主正则 '^[a-z][a-z0-9_]{{0,63}}$'（小写字母开头、≤64字符），当前值：{raw_id!r}。"
        )
    elif resolved_name is not None and not is_template_mod_name(resolved_name):
        expected_id = resolved_name.replace("-", "_")
        if raw_id != expected_id:
            warnings.append(
                f"[plugin.json] id '{raw_id}' 与目录名推导值 '{expected_id}' 不一致，建议保持对应。"
            )

    # version: SemVer
    version = manifest.get("version")
    if not isinstance(version, str) or not SEMVER_RE.match(version):
        errors.append(
            f"[plugin.json] version 必须为合法语义化版本号 (如 '0.1.0')，当前值：{version!r}。"
        )

    # name: 1..80 chars
    name_val = manifest.get("name")
    if not isinstance(name_val, str) or not name_val.strip():
        errors.append("[plugin.json] name 必须为非空字符串。")
    elif len(name_val) > MAX_NAME_LENGTH:
        errors.append(
            f"[plugin.json] name 长度 ({len(name_val)}) 超过宿主上限 {MAX_NAME_LENGTH} 字符 (invalid_plugin_manifest)。"
        )

    # description: optional (null allowed per PluginPackageJob.cs:114), if non-null must be string <= 2000 chars
    if "description" in manifest and manifest["description"] is not None:
        desc_val = manifest["description"]
        if not isinstance(desc_val, str):
            errors.append("[plugin.json] description 必须为字符串或 null。")
        elif len(desc_val) > MAX_DESCRIPTION_LENGTH:
            errors.append(
                f"[plugin.json] description 长度 ({len(desc_val)}) 超过宿主上限 {MAX_DESCRIPTION_LENGTH} 字符 (invalid_plugin_manifest)。"
            )

    if schema in INWORLD_SCHEMAS:
        host_api = manifest.get("host_api")
        if not (isinstance(host_api, int) and not isinstance(host_api, bool) and host_api in (1, 2)):
            errors.append(
                f"[plugin.json] host_api 必须为整数 1 或 2，当前值：{host_api!r} (plugin_host_api_incompatible)。"
            )

        raw_scope = manifest.get("scope")
        if raw_scope is None:
            scope_val = ""
        elif isinstance(raw_scope, str):
            scope_val = raw_scope
        else:
            scope_val = "__invalid__"
        if scope_val not in V2_SCOPES:
            errors.append(
                f"[plugin.json] scope 必须为空或属于 {sorted(x for x in V2_SCOPES if x)}，当前值：{raw_scope!r} (plugin_host_api_incompatible)。"
            )

        # settings: optional in v2/desktop-module, defaults to []
        if "settings" in manifest and manifest["settings"] is not None:
            _validate_settings_array(manifest["settings"], errors)

        # import_extensions: optional in v2/desktop-module
        import_exts_list: list[Any] = []
        if "import_extensions" in manifest and manifest["import_extensions"] is not None:
            raw_exts = manifest["import_extensions"]
            if not isinstance(raw_exts, list):
                errors.append("[plugin.json] import_extensions 必须为数组 (invalid_plugin_extensions)。")
            elif len(raw_exts) > MAX_IMPORT_EXTENSIONS:
                errors.append(
                    f"[plugin.json] import_extensions 数量 ({len(raw_exts)}) 超过宿主上限 {MAX_IMPORT_EXTENSIONS} 项 (invalid_plugin_extensions)。"
                )
            else:
                import_exts_list = raw_exts
                for idx, ext_item in enumerate(raw_exts):
                    if not isinstance(ext_item, str) or not IMPORT_EXT_RE.match(ext_item):
                        errors.append(
                            f"[plugin.json] import_extensions[{idx}] 值 {ext_item!r} 非法："
                            "必须为不含前导 '.' 的 1..12 位纯小写字母与数字。"
                        )

        # entry: required if import_extensions is non-empty; validated if present and non-empty
        entry_rel: str | None = None
        raw_entry = manifest.get("entry")
        if raw_entry is not None and not isinstance(raw_entry, str):
            errors.append("[plugin.json] entry 必须为字符串 (invalid_plugin_entry)。")
        else:
            if len(import_exts_list) > 0:
                entry_rel = _validate_manifest_entry_field(manifest, errors)
            elif isinstance(raw_entry, str) and raw_entry != "":
                entry_rel = _validate_manifest_entry_field(manifest, errors)

        # pack_file / pck
        raw_pack_file = manifest.get("pack_file")
        raw_pck = manifest.get("pck")
        if raw_pack_file is not None and not isinstance(raw_pack_file, str):
            errors.append("[plugin.json] pack_file 必须为字符串 (invalid_plugin_pack)。")
        if raw_pck is not None and not isinstance(raw_pck, str):
            errors.append("[plugin.json] pck 必须为字符串 (invalid_plugin_pack)。")
        pf_val = raw_pack_file if isinstance(raw_pack_file, str) else ""
        pck_val = raw_pck if isinstance(raw_pck, str) else ""
        if pf_val and pck_val and pf_val != pck_val:
            errors.append(
                f"[plugin.json] pack_file ({pf_val!r}) 与 pck ({pck_val!r}) 声明冲突 (invalid_plugin_pack)。"
            )
        pack_file = pf_val or pck_val
        if schema == "fus.desktop-module.v1":
            if pack_file:
                errors.append(
                    f"[plugin.json] fus.desktop-module.v1 为纯 ZIP 直挂模式，禁止声明 pack_file/pck ({pack_file!r}) (invalid_plugin_pack)。"
                )
                pack_file = ""
        elif pack_file:
            if ".." in pack_file or not PACK_FILE_RE.match(pack_file):
                errors.append(
                    f"[plugin.json] pack_file '{pack_file}' 非法：必须匹配 ^[a-zA-Z0-9_.-]+\\.pck$ 且不含 '..' (invalid_plugin_pack)。"
                )

        # modules / module
        validated_modules: list[dict[str, Any]] = []
        raw_modules: Any = None
        if "modules" in manifest and manifest["modules"] is not None:
            raw_modules = manifest["modules"]
        elif "module" in manifest and manifest["module"] is not None:
            if isinstance(manifest["module"], dict):
                raw_modules = [manifest["module"]]
            else:
                errors.append("[plugin.json] module 必须为 JSON Object 字典 (invalid_plugin_modules)。")
                raw_modules = []
        else:
            errors.append("[plugin.json] 缺少必需字段 'modules' 或 'module' (invalid_plugin_modules)。")
            raw_modules = []

        if not isinstance(raw_modules, list):
            errors.append("[plugin.json] modules 必须为数组 (invalid_plugin_modules)。")
        elif len(raw_modules) == 0 or len(raw_modules) > MAX_MODULES_COUNT:
            if "modules" in manifest or "module" in manifest:
                errors.append(
                    f"[plugin.json] modules 数量 ({len(raw_modules)}) 必须在 1..{MAX_MODULES_COUNT} 之间 (invalid_plugin_modules)。"
                )
        else:
            seen_mod_ids: set[str] = set()
            mod_prefix = f"res://mods/{plugin_id}/"
            ext_prefix = f"res://external_modules/{plugin_id}/"
            for idx, raw_mod in enumerate(raw_modules):
                mprefix = f"[plugin.json] modules[{idx}]"
                if not isinstance(raw_mod, dict):
                    errors.append(f"{mprefix} 必须为对象字典 (invalid_plugin_modules)。")
                    continue
                validated_modules.append(raw_mod)

                mid = raw_mod.get("id")
                if not _is_valid_module_id(mid):
                    errors.append(
                        f"{mprefix}.id 非法（须 ≤128 字符且匹配 ^[a-z][a-z0-9_]{0,63}(?:\\.[a-z0-9_]{1,63})*$），"
                        f"当前值：{mid!r} (invalid_plugin_module_id)。"
                    )
                else:
                    if plugin_id:
                        valid_owner = (
                            mid == plugin_id
                            or mid.startswith(plugin_id + ".")
                            or mid == f"mod.{plugin_id}"
                            or mid.startswith(f"mod.{plugin_id}.")
                        )
                        if not valid_owner:
                            errors.append(
                                f"{mprefix}.id '{mid}' 不属于插件 ID '{plugin_id}' 命名空间"
                                "（须为 id / id.* / mod.id / mod.id.*）(invalid_plugin_module_id)。"
                            )
                    if mid in seen_mod_ids:
                        errors.append(f"{mprefix}.id '{mid}' 重复定义 (invalid_plugin_module_id)。")
                    else:
                        seen_mod_ids.add(mid)

                disp = raw_mod.get("display_name")
                if disp is None or disp == "":
                    disp = raw_mod.get("name")
                if not isinstance(disp, str) or not disp.strip() or len(disp) > MAX_NAME_LENGTH:
                    errors.append(
                        f"{mprefix}.display_name (或 name) 必须为 1..{MAX_NAME_LENGTH} 字符的非空字符串 (invalid_plugin_modules)。"
                    )

                for text_key in ("description", "disable_effect"):
                    if text_key in raw_mod and raw_mod[text_key] is not None:
                        tval = raw_mod[text_key]
                        if not isinstance(tval, str) or len(tval) > MAX_DESCRIPTION_LENGTH:
                            errors.append(
                                f"{mprefix}.{text_key} 必须为 ≤{MAX_DESCRIPTION_LENGTH} 字符的字符串 (invalid_plugin_modules)。"
                            )

                scene_val = raw_mod.get("entry_scene")
                if scene_val is None or scene_val == "":
                    scene_val = raw_mod.get("path")
                if not isinstance(scene_val, str) or not scene_val.strip():
                    errors.append(
                        f"{mprefix}.entry_scene (或 path) 必须为非空 res:// 场景路径 (invalid_plugin_module_scene)。"
                    )
                else:
                    if not scene_val.endswith(".tscn") or ".." in scene_val:
                        errors.append(
                            f"{mprefix}.entry_scene '{scene_val}' 必须以 '.tscn' 结尾且不含 '..' (invalid_plugin_module_scene)。"
                        )
                    elif plugin_id and not (
                        scene_val.startswith(mod_prefix) or scene_val.startswith(ext_prefix)
                    ):
                        errors.append(
                            f"{mprefix}.entry_scene '{scene_val}' 必须位于 '{mod_prefix}' 或 '{ext_prefix}' 命名空间内 (invalid_plugin_module_scene)。"
                        )
                    elif scene_val.startswith("res://"):
                        scene_rel = scene_val[len("res://") :]
                        for issue in check_zip_member_path(scene_rel):
                            errors.append(
                                f"{mprefix}.entry_scene 路径不安全：{issue} (invalid_plugin_module_scene)"
                            )
                    else:
                        errors.append(
                            f"{mprefix}.entry_scene '{scene_val}' 必须以 'res://' 开头 (invalid_plugin_module_scene)。"
                        )

                raw_local_only = raw_mod.get("local_only")
                if raw_local_only is not None and not isinstance(raw_local_only, bool):
                    errors.append(
                        f"{mprefix}.local_only 若提供必须为布尔值 (invalid_plugin_module_version)。"
                    )
                local_only = raw_local_only if isinstance(raw_local_only, bool) else False

                raw_mver = raw_mod.get("version")
                if raw_mver is None:
                    mver = 1
                elif isinstance(raw_mver, int) and not isinstance(raw_mver, bool):
                    mver = raw_mver
                else:
                    mver = -1
                if mver < 1:
                    errors.append(
                        f"{mprefix}.version 必须为 ≥1 的整数，当前值：{raw_mver!r} (invalid_plugin_module_version)。"
                    )

                has_net_ver = "network_version" in raw_mod and raw_mod["network_version"] is not None
                raw_net_ver = raw_mod.get("network_version")
                if has_net_ver:
                    if isinstance(raw_net_ver, int) and not isinstance(raw_net_ver, bool):
                        net_ver = raw_net_ver
                    else:
                        net_ver = -1
                else:
                    net_ver = 0 if local_only else -1

                if schema == "fus.desktop-module.v1":
                    if raw_local_only is not True:
                        errors.append(
                            f"{mprefix}.local_only 在 fus.desktop-module.v1 中必须显式为 true (invalid_plugin_module_version)。"
                        )
                    if has_net_ver and net_ver != 0:
                        errors.append(
                            f"{mprefix}.network_version 在 fus.desktop-module.v1 中必须为 0，当前值：{raw_net_ver!r} (invalid_plugin_module_version)。"
                        )
                else:
                    if not local_only:
                        if not has_net_ver or net_ver < 0:
                            errors.append(
                                f"{mprefix}.network_version 在 local_only=false 时必须为 ≥0 的整数，当前值：{raw_net_ver!r} (invalid_plugin_module_version)。"
                            )
                        elif net_ver == 0:
                            warnings.append(
                                f"{mprefix} local_only=false 且 network_version=0 时将不参与联机版本握手。"
                            )
                    elif net_ver < 0:
                        errors.append(
                            f"{mprefix}.network_version 必须为 ≥0 的整数，当前值：{raw_net_ver!r} (invalid_plugin_module_version)。"
                        )

                for rel_key in ("requires", "conflicts", "suppresses"):
                    if rel_key not in raw_mod or raw_mod[rel_key] is None:
                        continue
                    rel_arr = raw_mod[rel_key]
                    if not isinstance(rel_arr, list) or len(rel_arr) > MAX_MODULE_RELATIONS:
                        errors.append(
                            f"{mprefix}.{rel_key} 必须为 ≤{MAX_MODULE_RELATIONS} 项的数组 (invalid_plugin_module_relations)。"
                        )
                        continue
                    for ridx, ritem in enumerate(rel_arr):
                        if not _is_valid_module_id(ritem):
                            errors.append(
                                f"{mprefix}.{rel_key}[{ridx}] 模块 ID {ritem!r} 非法 (invalid_plugin_module_relations)。"
                            )

        ns_roots = extract_module_namespace_roots(manifest, plugin_id)
        return _ManifestValidationContext(
            schema=schema,
            plugin_id=plugin_id,
            entry_rel=entry_rel,
            pack_file=pack_file,
            modules=validated_modules,
            namespace_roots=ns_roots,
        )

    # Default / v1 (`fus.session-plugin.v1`) checks
    host_api = manifest.get("host_api")
    if not (isinstance(host_api, int) and not isinstance(host_api, bool) and host_api == EXPECTED_HOST_API):
        errors.append(
            f"[plugin.json] host_api 必须为整数 {EXPECTED_HOST_API}，当前值：{host_api!r} (plugin_host_api_incompatible)。"
        )

    scope = manifest.get("scope")
    if scope != EXPECTED_SCOPE:
        errors.append(
            f"[plugin.json] scope 必须为 '{EXPECTED_SCOPE}'，当前值：{scope!r} (plugin_host_api_incompatible)。"
        )

    # import_extensions: HARD REQUIRED list, 1..8 items, each ^[a-z0-9]{1,12}$
    if "import_extensions" not in manifest:
        errors.append(
            "[plugin.json] 缺少必需数组字段 'import_extensions' (invalid_plugin_extensions)。"
        )
    else:
        import_exts = manifest["import_extensions"]
        if not isinstance(import_exts, list) or len(import_exts) == 0:
            errors.append(
                "[plugin.json] import_extensions 必须为非空字符串数组（为空会导致客户端隐藏导入按钮）。"
            )
        elif len(import_exts) > MAX_IMPORT_EXTENSIONS:
            errors.append(
                f"[plugin.json] import_extensions 数量 ({len(import_exts)}) 超过宿主上限 {MAX_IMPORT_EXTENSIONS} 项 (invalid_plugin_extensions)。"
            )
        else:
            for idx, ext_item in enumerate(import_exts):
                if not isinstance(ext_item, str) or not IMPORT_EXT_RE.match(ext_item):
                    errors.append(
                        f"[plugin.json] import_extensions[{idx}] 值 {ext_item!r} 非法："
                        "必须为不含前导 '.' 的 1..12 位纯小写字母与数字（如 'fobr'、'uvtt'）。"
                    )

    # settings: HARD REQUIRED list (may be empty []), max 32 items
    if "settings" not in manifest:
        errors.append(
            "[plugin.json] 缺少必需数组字段 'settings'（即使无配置项也必须显式声明为 []，否则宿主抛出 invalid_plugin_settings）。"
        )
    else:
        _validate_settings_array(manifest["settings"], errors)

    entry_rel = _validate_manifest_entry_field(manifest, errors)
    return _ManifestValidationContext(
        schema=schema or EXPECTED_SCHEMA,
        plugin_id=plugin_id,
        entry_rel=entry_rel,
        pack_file="",
        modules=[],
        namespace_roots=[],
    )


def _validate_manifest_dict(
    manifest: dict[str, Any],
    resolved_name: str | None,
    errors: list[str],
    warnings: list[str],
) -> str | None:
    return _validate_manifest_context(manifest, resolved_name, errors, warnings).entry_rel


def strip_gdscript_comments(source: str) -> str:
    """Strip `#` comments and blank string literal interiors from GDScript while preserving line numbers."""
    out_lines: list[str] = []
    in_multiline: str | None = None

    for line in source.splitlines():
        i = 0
        n = len(line)
        buf: list[str] = []
        in_single_quote: str | None = None

        while i < n:
            if in_multiline is not None:
                if line[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if line.startswith(in_multiline, i):
                    buf.append(in_multiline)
                    i += 3
                    in_multiline = None
                else:
                    i += 1
                continue

            if in_single_quote is not None:
                ch = line[i]
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == in_single_quote:
                    buf.append(ch)
                    in_single_quote = None
                i += 1
                continue

            ch = line[i]
            if ch == "r" and (i == 0 or not (line[i - 1].isalnum() or line[i - 1] == "_")):
                if line.startswith('r"""', i) or line.startswith("r'''", i):
                    in_multiline = line[i + 1 : i + 4]
                    buf.append(line[i : i + 4])
                    i += 4
                    continue
                if i + 1 < n and line[i + 1] in ('"', "'"):
                    in_single_quote = line[i + 1]
                    buf.append(line[i : i + 2])
                    i += 2
                    continue

            if line.startswith('"""', i) or line.startswith("'''", i):
                in_multiline = line[i : i + 3]
                buf.append(in_multiline)
                i += 3
                continue

            if ch in ('"', "'"):
                in_single_quote = ch
                buf.append(ch)
                i += 1
                continue

            if ch == "#":
                break

            buf.append(ch)
            i += 1

        out_lines.append("".join(buf))

    return "\n".join(out_lines)


def _check_safe_relative_path(raw_rel: str) -> list[str]:
    return check_zip_member_path(raw_rel)


def _check_utf8_no_bom(file_path: Path, label: str, errors: list[str]) -> str | None:
    raw = file_path.read_bytes()
    if raw.startswith(UTF8_BOM):
        errors.append(f"[{label}] 检测到 UTF-8 BOM (EF BB BF)，宿主与规范要求必须使用 UTF-8 无 BOM 编码。")
        raw = raw[len(UTF8_BOM) :]
    elif raw.startswith(UTF16_BOMS):
        errors.append(f"[{label}] 检测到 UTF-16 BOM，必须转换为 UTF-8 无 BOM 编码。")
        return None

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"[{label}] 非合法 UTF-8 文本编码：{exc}")
        return None


def validate_mod_dir(
    mod_dir: Path,
    *,
    mod_name: str | None = None,
    sdk_dir: Path | None = None,
    runtime_sdk_dir: Path | None = None,
) -> ValidationReport:
    """Run full static contract checks against a plugin directory."""
    resolved_name = mod_name or mod_dir.name
    report = ValidationReport(mod_name=resolved_name, mod_dir=mod_dir)

    if not mod_dir.exists() or not mod_dir.is_dir():
        report.errors.append(f"插件目录不存在：{mod_dir}")
        return report

    if is_symlink_or_reparse_point(mod_dir):
        report.errors.append(f"安全拦截 (linked_plugin_path)：插件根目录 '{resolved_name}' 不能为符号链接或 ReparsePoint。")
        return report

    resolved_mod_root = mod_dir.resolve()
    raw_runtime_entries: list[tuple[str, Path, int]] = []
    seen_casefold_paths: dict[str, str] = {}
    decoded_texts: dict[str, str] = {}

    # Walk directory using os.walk to inspect raw filenames, symlinks/reparse points, and case collisions
    for root, dirnames, filenames in os.walk(mod_dir, followlinks=False):
        dirnames.sort()
        filenames.sort()
        root_path = Path(root)

        safe_dirnames: list[str] = []
        for dname in dirnames:
            dpath = root_path / dname
            rel_dir = dpath.relative_to(mod_dir)
            posix_dir = rel_dir.as_posix()
            if is_symlink_or_reparse_point(dpath):
                report.errors.append(
                    f"安全拦截 (linked_plugin_path)：目录 '{posix_dir}' 为符号链接或 NTFS ReparsePoint，宿主拒绝加载。"
                )
                continue
            if not (dname == "__pycache__" or dname.startswith(".")):
                if dname.endswith(".") or dname.endswith(" "):
                    report.errors.append(
                        f"不安全目录名 (unsafe_zip_path)：'{posix_dir}' 包含以 '.' 或空格结尾的目录段。"
                    )
            safe_dirnames.append(dname)
        dirnames[:] = safe_dirnames

        for fname in filenames:
            fpath = root_path / fname
            rel_path = fpath.relative_to(mod_dir)
            posix_rel = rel_path.as_posix()

            if is_symlink_or_reparse_point(fpath):
                report.errors.append(
                    f"安全拦截 (linked_plugin_path)：文件 '{posix_rel}' 为符号链接或 NTFS ReparsePoint，宿主拒绝加载。"
                )
                continue

            if fpath.suffix.lower() in TEXT_CHECK_EXTENSIONS:
                text = _check_utf8_no_bom(fpath, posix_rel, report.errors)
                if text is not None:
                    decoded_texts[posix_rel] = text

            if is_runtime_file(rel_path):
                if is_forbidden_binary_path(posix_rel):
                    report.errors.append(
                        f"安全拦截 (unsafe_plugin_binary)：禁止包含可执行/原生二进制或脚本文件 '{posix_rel}'。"
                    )
                for issue in check_zip_member_path(posix_rel):
                    report.errors.append(f"[unsafe_zip_path] {issue}")

                folded = posix_rel.lower()
                if folded in seen_casefold_paths:
                    report.errors.append(
                        f"[unsafe_zip_path] 检测到 Windows 大小写冲突路径：'{seen_casefold_paths[folded]}' 与 '{posix_rel}'。"
                    )
                else:
                    seen_casefold_paths[folded] = posix_rel

                fsize = fpath.stat().st_size
                if fsize > MAX_PACKAGE_BYTES:
                    report.errors.append(
                        f"单文件超限 (plugin_expanded_limit)：'{posix_rel}' ({fsize} B) 超过 64 MiB 上限。"
                    )
                raw_runtime_entries.append((posix_rel, fpath, fsize))

    # Parse plugin.json before accounting for bundled SDK files so schema determines SDK layout
    manifest_file = _resolve_exact_case_rel_path(mod_dir, "plugin.json")
    manifest: dict[str, Any] | None = None
    manifest_ctx: _ManifestValidationContext | None = None
    if manifest_file is None or not manifest_file.is_file():
        report.errors.append("缺少必需清单文件 'plugin.json' (plugin_manifest_missing)。")
    else:
        manifest_size = manifest_file.stat().st_size
        if manifest_size > MAX_MANIFEST_BYTES:
            report.errors.append(
                f"[plugin.json] 文件体积 ({manifest_size} B) 超过宿主 128 KiB 上限 ({MAX_MANIFEST_BYTES} B，plugin_manifest_limit)。"
            )
        manifest_raw = decoded_texts.get("plugin.json")
        if manifest_raw is not None:
            try:
                parsed_manifest = json.loads(manifest_raw)
            except json.JSONDecodeError as exc:
                report.errors.append(f"[plugin.json] JSON 语法解析失败：{exc}")
            else:
                if not isinstance(parsed_manifest, dict):
                    report.errors.append("[plugin.json] 顶层结构必须为 JSON Object (字典)。")
                else:
                    manifest = parsed_manifest
                    report.manifest = manifest
                    manifest_ctx = _validate_manifest_context(
                        manifest, resolved_name, report.errors, report.warnings
                    )

    is_inworld = manifest_ctx is not None and manifest_ctx.schema in INWORLD_SCHEMAS
    runtime_files: list[str] = []
    total_runtime_bytes = 0
    for posix_rel, fpath, fsize in raw_runtime_entries:
        if is_inworld and fpath.suffix.lower() == ".uid":
            continue
        runtime_files.append(posix_rel)
        total_runtime_bytes += fsize

    if manifest_ctx is not None and manifest_ctx.schema in INWORLD_SCHEMAS:
        effective_runtime_sdk = runtime_sdk_dir
        if effective_runtime_sdk is None and sdk_dir is not None:
            candidate_rt = sdk_dir.parent / "fu_runtime"
            if candidate_rt.is_dir():
                effective_runtime_sdk = candidate_rt

        rt_items, fu_sdk_items, bundle_errors = resolve_runtime_sdk_bundle(sdk_dir, effective_runtime_sdk)
        report.errors.extend(bundle_errors)
        if manifest_ctx.namespace_roots and (rt_items or fu_sdk_items):
            for ns_root in manifest_ctx.namespace_roots:
                for rel_rt, rt_file in rt_items:
                    if is_symlink_or_reparse_point(rt_file):
                        report.errors.append(
                            f"安全拦截 (linked_plugin_path)：SDK 文件 'shared/sdk/fu_runtime/{rel_rt}' 为符号链接。"
                        )
                        continue
                    _check_utf8_no_bom(rt_file, f"shared/sdk/fu_runtime/{rel_rt}", report.errors)
                    vendored_posix = f"{ns_root}/lib/fu_runtime/{rel_rt}"
                    folded = vendored_posix.lower()
                    if folded in seen_casefold_paths:
                        report.errors.append(
                            f"[unsafe_zip_path] 插件文件与内嵌 SDK 路径冲突：'{seen_casefold_paths[folded]}' vs '{vendored_posix}'。"
                        )
                    else:
                        seen_casefold_paths[folded] = vendored_posix
                    total_runtime_bytes += rt_file.stat().st_size
                    runtime_files.append(vendored_posix)

                for rel_sdk, sdk_file in fu_sdk_items:
                    if is_symlink_or_reparse_point(sdk_file):
                        report.errors.append(
                            f"安全拦截 (linked_plugin_path)：SDK 文件 'shared/sdk/fu_sdk/{rel_sdk}' 为符号链接。"
                        )
                        continue
                    _check_utf8_no_bom(sdk_file, f"shared/sdk/fu_sdk/{rel_sdk}", report.errors)
                    vendored_posix = f"{ns_root}/lib/fu_sdk/{rel_sdk}"
                    folded = vendored_posix.lower()
                    if folded in seen_casefold_paths:
                        report.errors.append(
                            f"[unsafe_zip_path] 插件文件与内嵌 SDK 路径冲突：'{seen_casefold_paths[folded]}' vs '{vendored_posix}'。"
                        )
                    else:
                        seen_casefold_paths[folded] = vendored_posix
                    total_runtime_bytes += sdk_file.stat().st_size
                    runtime_files.append(vendored_posix)

        if manifest_ctx.entry_rel and sdk_dir is not None and sdk_dir.is_dir():
            for sdk_file in sorted(sdk_dir.rglob("*.gd")):
                rel_sdk = sdk_file.relative_to(sdk_dir)
                if any(part.startswith(".") or part == "__pycache__" for part in rel_sdk.parts):
                    continue
                if is_symlink_or_reparse_point(sdk_file):
                    report.errors.append(
                        f"安全拦截 (linked_plugin_path)：SDK 文件 'shared/sdk/fu_sdk/{rel_sdk.as_posix()}' 为符号链接。"
                    )
                    continue
                _check_utf8_no_bom(sdk_file, f"shared/sdk/fu_sdk/{rel_sdk.as_posix()}", report.errors)
                vendored_posix = f"lib/fu_sdk/{rel_sdk.as_posix()}"
                folded = vendored_posix.lower()
                if folded in seen_casefold_paths:
                    report.errors.append(
                        f"[unsafe_zip_path] 插件文件与内嵌 SDK 路径冲突：'{seen_casefold_paths[folded]}' vs '{vendored_posix}'。"
                    )
                else:
                    seen_casefold_paths[folded] = vendored_posix
                total_runtime_bytes += sdk_file.stat().st_size
                runtime_files.append(vendored_posix)
    else:
        # v1 (or unparsed manifest) accounts for fu_sdk -> lib/fu_sdk/
        if sdk_dir is not None and sdk_dir.is_dir():
            for sdk_file in sorted(sdk_dir.rglob("*.gd")):
                rel_sdk = sdk_file.relative_to(sdk_dir)
                if any(part.startswith(".") or part == "__pycache__" for part in rel_sdk.parts):
                    continue
                if is_symlink_or_reparse_point(sdk_file):
                    report.errors.append(
                        f"安全拦截 (linked_plugin_path)：SDK 文件 'shared/sdk/fu_sdk/{rel_sdk.as_posix()}' 为符号链接。"
                    )
                    continue
                _check_utf8_no_bom(sdk_file, f"shared/sdk/fu_sdk/{rel_sdk.as_posix()}", report.errors)
                vendored_posix = f"lib/fu_sdk/{rel_sdk.as_posix()}"
                folded = vendored_posix.lower()
                if folded in seen_casefold_paths:
                    report.errors.append(
                        f"[unsafe_zip_path] 插件文件与内嵌 SDK 路径冲突：'{seen_casefold_paths[folded]}' vs '{vendored_posix}'。"
                    )
                else:
                    seen_casefold_paths[folded] = vendored_posix
                total_runtime_bytes += sdk_file.stat().st_size
                runtime_files.append(vendored_posix)

    report.estimated_bytes = total_runtime_bytes
    report.runtime_file_count = len(runtime_files)

    if len(runtime_files) < MIN_ARCHIVE_ENTRIES or len(runtime_files) > MAX_ARCHIVE_ENTRIES:
        report.errors.append(
            f"文件数越界 (plugin_file_limit)：运行时文件数 {len(runtime_files)} 不在宿主允许范围 {MIN_ARCHIVE_ENTRIES}..{MAX_ARCHIVE_ENTRIES} 内。"
        )
    if total_runtime_bytes > MAX_EXPANDED_BYTES:
        report.errors.append(
            f"展开体积超限 (plugin_expanded_limit)：预计解压总大小 {total_runtime_bytes} B 超过 256 MiB 上限 ({MAX_EXPANDED_BYTES} B)。"
        )
    elif total_runtime_bytes > MAX_PACKAGE_BYTES:
        report.warnings.append(
            f"预计未压缩体积 {total_runtime_bytes} B 超过 64 MiB（打包后若归档仍超 64 MiB 将被宿主 plugin_download_limit 拦截）。"
        )

    if manifest_ctx is None:
        return report

    for posix_rel, fpath, _ in raw_runtime_entries:
        if fpath.suffix.lower() != ".gd":
            continue
        gd_text = decoded_texts.get(posix_rel)
        if gd_text is not None and CLASS_NAME_RE.search(strip_gdscript_comments(gd_text)):
            report.errors.append(
                f"[{posix_rel}] 外置插件/模块脚本禁止声明全局 class_name (global_class_name_not_allowed)。"
            )

    if manifest_ctx.schema == "fus.session-plugin.v1":
        entry_rel = manifest_ctx.entry_rel
        if entry_rel is None:
            return report
        entry_file = (mod_dir / entry_rel).resolve()
        if not entry_file.is_relative_to(resolved_mod_root) or not entry_file.is_file():
            report.errors.append(f"[plugin.json] entry 指向的入口脚本不存在：{entry_rel} (plugin_entry_missing)。")
            return report
        exact_entry_file = _resolve_exact_case_rel_path(mod_dir, entry_rel)
        if exact_entry_file is None or not exact_entry_file.is_file():
            report.errors.append(
                f"[plugin.json] entry 路径大小写与磁盘实际文件名不一致：'{entry_rel}' (plugin_entry_missing)。"
            )
            return report
        entry_posix = entry_file.relative_to(resolved_mod_root).as_posix()
        entry_text = decoded_texts.get(entry_posix)
        if entry_text is None:
            entry_text = _check_utf8_no_bom(entry_file, entry_posix, report.errors)
        if entry_text is not None:
            _validate_entry_gd_source(entry_text, entry_posix, report.errors)
        return report

    # In-world module checks (`fus.desktop-module.v1` / `fus.plugin.v2`)
    if manifest_ctx.plugin_id:
        mod_prefix = f"mods/{manifest_ctx.plugin_id}/"
        ext_prefix = f"external_modules/{manifest_ctx.plugin_id}/"
        if not any(r.startswith(mod_prefix) or r.startswith(ext_prefix) for r in runtime_files):
            report.errors.append(
                f"缺少模块源码目录文件：必须在 '{mod_prefix}' 或 '{ext_prefix}' 下包含至少 1 个运行时文件 (plugin_pack_missing)。"
            )
        if manifest_ctx.pack_file:
            for posix_rel, fpath, _ in raw_runtime_entries:
                if fpath.suffix.lower() == ".uid":
                    continue
                if posix_rel == "plugin.json":
                    continue
                if manifest_ctx.entry_rel and posix_rel == manifest_ctx.entry_rel:
                    continue
                if posix_rel.startswith(mod_prefix) or posix_rel.startswith(ext_prefix):
                    continue
                report.errors.append(
                    f"[{posix_rel}] .fup 打包模式仅收录 '{mod_prefix}' 或 '{ext_prefix}' 命名空间下的资源文件"
                    "（以及根目录 plugin.json / 混合导入 entry 脚本），非命名空间文件将被丢弃。"
                )

    for mod_item in manifest_ctx.modules:
        raw_scene = mod_item.get("entry_scene")
        if raw_scene is None or raw_scene == "":
            raw_scene = mod_item.get("path")
        scene_val = raw_scene if isinstance(raw_scene, str) else ""
        if scene_val.startswith("res://") and ".." not in scene_val:
            scene_rel = scene_val[len("res://") :]
            scene_file = (mod_dir / scene_rel).resolve()
            if not scene_file.is_relative_to(resolved_mod_root) or not scene_file.is_file():
                report.errors.append(
                    f"[plugin.json] module.entry_scene 指向的场景不存在：{scene_rel} (plugin_module_scene_missing)。"
                )
            else:
                exact_scene = _resolve_exact_case_rel_path(mod_dir, scene_rel)
                if exact_scene is None or not exact_scene.is_file():
                    report.errors.append(
                        f"[plugin.json] module.entry_scene 路径大小写与磁盘实际文件名不一致：'{scene_rel}' (plugin_module_scene_missing)。"
                    )

    if manifest_ctx.entry_rel:
        entry_rel = manifest_ctx.entry_rel
        entry_file = (mod_dir / entry_rel).resolve()
        if not entry_file.is_relative_to(resolved_mod_root) or not entry_file.is_file():
            report.errors.append(f"[plugin.json] entry 指向的混合导入脚本不存在：{entry_rel} (plugin_entry_missing)。")
        else:
            exact_entry_file = _resolve_exact_case_rel_path(mod_dir, entry_rel)
            if exact_entry_file is None or not exact_entry_file.is_file():
                report.errors.append(
                    f"[plugin.json] entry 路径大小写与磁盘实际文件名不一致：'{entry_rel}' (plugin_entry_missing)。"
                )
            else:
                entry_posix = entry_file.relative_to(resolved_mod_root).as_posix()
                entry_text = decoded_texts.get(entry_posix) or _check_utf8_no_bom(entry_file, entry_posix, report.errors)
                if entry_text is not None:
                    _validate_entry_gd_source(entry_text, entry_posix, report.errors)

    return report


def resolve_target_mods(
    config: WorkspaceConfig,
    *,
    mod_name: str | None = None,
    select_all: bool = False,
    include_template: bool = False,
) -> list[str]:
    """Resolve list of target mod folder names under `mods/`."""
    if mod_name and select_all:
        raise ValidationError("不能同时指定单个 <mod-name> 与 --all。")

    if mod_name:
        cleaned = mod_name.strip()
        if not cleaned or "/" in cleaned or "\\" in cleaned or ".." in cleaned:
            raise ValidationError(f"非法插件名称：{mod_name!r}")
        return [cleaned]

    if not select_all:
        raise ValidationError("请指定目标 <mod-name> 或使用 --all。")

    if not config.mods_dir.is_dir():
        return []

    mods: list[str] = []
    templates: list[str] = []
    for child in sorted(config.mods_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if is_template_mod_name(child.name):
            templates.append(child.name)
            continue
        mods.append(child.name)

    templates.sort(key=lambda name: (0 if name == "_template" else 1, name))
    if include_template and templates:
        return [*templates, *mods]
    if not mods and templates:
        # Empty workspace fallback: validate templates when no business mods exist yet
        return templates

    return mods


def validate_mods(
    config: WorkspaceConfig | None = None,
    *,
    mod_name: str | None = None,
    select_all: bool = False,
    include_template: bool = False,
) -> list[ValidationReport]:
    """Validate one or more mods according to selection flags."""
    cfg = config or load_config()
    targets = resolve_target_mods(
        cfg,
        mod_name=mod_name,
        select_all=select_all,
        include_template=include_template,
    )
    reports: list[ValidationReport] = []
    for name in targets:
        reports.append(
            validate_mod_dir(
                cfg.mods_dir / name,
                mod_name=name,
                sdk_dir=cfg.sdk_dir,
                runtime_sdk_dir=cfg.resolved_runtime_sdk_dir,
            )
        )
    return reports
