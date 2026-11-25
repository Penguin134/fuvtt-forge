"""Static contract validator for Fu vtt session plugins (`validate` subcommand).

Aligned 1-to-1 with Practice host `services/plugins/PluginPackageJob.cs`
(`fus.session-plugin.v1`, `host_api = 1`, `scope = "session"`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
import zipfile

from .env_config import WorkspaceConfig, load_config


EXPECTED_SCHEMA = "fus.session-plugin.v1"
EXPECTED_HOST_API = 1
EXPECTED_SCOPE = "session"

# Exact limits from Practice host `services/plugins/PluginPackageJob.cs`
MAX_PACKAGE_BYTES = 64 * 1024 * 1024        # MaxArchive = 64 MiB (ZIP archive & single entry)
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

PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}\Z")
SEMVER_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9._-]+)?\Z")
ENTRY_REL_RE = re.compile(r"^[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_-]+)*\.gd\Z")
IMPORT_EXT_RE = re.compile(r"^[a-z0-9]{1,12}\Z")

EXTENDS_REFCOUNTED_RE = re.compile(r"(?m)^\s*extends\s+RefCounted\b")
FUNC_INSPECT_RE = re.compile(r"(?m)^\s*func\s+inspect_import\s*\(")
FUNC_PREPARE_RE = re.compile(r"(?m)^\s*func\s+prepare_import\s*\(")

TEXT_CHECK_EXTENSIONS = frozenset({".json", ".gd", ".md", ".cfg"})
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


def is_runtime_file(rel_path: Path) -> bool:
    """Return True if a file inside `mods/<mod-name>/` is packaged into the runtime ZIP."""
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


def validate_zip_archive(zip_path: Path) -> list[str]:
    """Post-build archive-level validation mirroring `PluginPackageJob.Install` (`PluginPackageJob.cs:266-281`)."""
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
                member_names.add(name)
                for issue in check_zip_member_path(name):
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
                                entry_rel = _validate_manifest_dict(zip_manifest, None, errors, [])
                                if entry_rel is not None:
                                    if entry_rel not in member_names:
                                        errors.append(
                                            f"[ZIP plugin_entry_missing] 压缩包缺少入口脚本（大小写敏感）：'{entry_rel}'。"
                                        )
                                    else:
                                        entry_info = zf.getinfo(entry_rel)
                                        if entry_info.file_size <= MAX_PACKAGE_BYTES:
                                            with zf.open(entry_info, mode="r") as ef:
                                                entry_bytes = ef.read(MAX_PACKAGE_BYTES + 1)
                                            if len(entry_bytes) <= MAX_PACKAGE_BYTES:
                                                entry_text = _decode_utf8_no_bom_bytes(entry_bytes, f"ZIP {entry_rel}", errors)
                                                if entry_text is not None:
                                                    stripped_gd = strip_gdscript_comments(entry_text)
                                                    if not EXTENDS_REFCOUNTED_RE.search(stripped_gd):
                                                        errors.append(f"[ZIP {entry_rel}] 入口脚本必须声明 'extends RefCounted'。")
                                                    if not FUNC_INSPECT_RE.search(stripped_gd):
                                                        errors.append(f"[ZIP {entry_rel}] 入口脚本缺少必需生命周期方法 'func inspect_import('。")
                                                    if not FUNC_PREPARE_RE.search(stripped_gd):
                                                        errors.append(f"[ZIP {entry_rel}] 入口脚本缺少必需生命周期方法 'func prepare_import('。")
    except zipfile.BadZipFile as exc:
        errors.append(f"ZIP 归档损坏：{exc}")

    return errors


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


def _validate_manifest_dict(
    manifest: dict[str, Any],
    resolved_name: str | None,
    errors: list[str],
    warnings: list[str],
) -> str | None:
    # Required top-level host compatibility fields
    schema = manifest.get("schema")
    if schema != EXPECTED_SCHEMA:
        errors.append(
            f"[plugin.json] schema 必须为 '{EXPECTED_SCHEMA}'，当前值：{schema!r} (plugin_host_api_incompatible)。"
        )

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

    # id: ^[a-z][a-z0-9_]{0,63}\Z
    plugin_id = manifest.get("id")
    if not isinstance(plugin_id, str) or not PLUGIN_ID_RE.match(plugin_id):
        errors.append(
            f"[plugin.json] id 必须匹配宿主正则 '^[a-z][a-z0-9_]{{0,63}}$'（小写字母开头、≤64字符），当前值：{plugin_id!r}。"
        )
    elif resolved_name is not None and resolved_name != "_template":
        expected_id = resolved_name.replace("-", "_")
        if plugin_id != expected_id:
            warnings.append(
                f"[plugin.json] id '{plugin_id}' 与目录名推导值 '{expected_id}' 不一致，建议保持对应。"
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
        settings = manifest["settings"]
        if not isinstance(settings, list):
            errors.append("[plugin.json] settings 必须为数组 (invalid_plugin_settings)。")
        elif len(settings) > MAX_SETTINGS_COUNT:
            errors.append(
                f"[plugin.json] settings 项数 ({len(settings)}) 超过宿主上限 {MAX_SETTINGS_COUNT} 项 (invalid_plugin_settings)。"
            )
        else:
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

    return _validate_manifest_entry_field(manifest, errors)


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
    total_runtime_bytes = 0
    runtime_files: list[str] = []
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
                total_runtime_bytes += fsize
                runtime_files.append(posix_rel)

    # Account for bundled SDK files if present
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
            f"预计未压缩体积 {total_runtime_bytes} B 超过 64 MiB（打包后若 ZIP 仍超 64 MiB 将被宿主 plugin_download_limit 拦截）。"
        )

    # Validate plugin.json existence & size limit (<= 128 KiB)
    manifest_file = _resolve_exact_case_rel_path(mod_dir, "plugin.json")
    if manifest_file is None or not manifest_file.is_file():
        report.errors.append("缺少必需清单文件 'plugin.json' (plugin_manifest_missing)。")
        return report

    manifest_size = manifest_file.stat().st_size
    if manifest_size > MAX_MANIFEST_BYTES:
        report.errors.append(
            f"[plugin.json] 文件体积 ({manifest_size} B) 超过宿主 128 KiB 上限 ({MAX_MANIFEST_BYTES} B，plugin_manifest_limit)。"
        )

    manifest_raw = decoded_texts.get("plugin.json")
    if manifest_raw is None:
        return report

    try:
        manifest = json.loads(manifest_raw)
    except json.JSONDecodeError as exc:
        report.errors.append(f"[plugin.json] JSON 语法解析失败：{exc}")
        return report

    if not isinstance(manifest, dict):
        report.errors.append("[plugin.json] 顶层结构必须为 JSON Object (字典)。")
        return report

    report.manifest = manifest
    entry_rel = _validate_manifest_dict(manifest, resolved_name, report.errors, report.warnings)
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
        stripped_gd = strip_gdscript_comments(entry_text)
        if not EXTENDS_REFCOUNTED_RE.search(stripped_gd):
            report.errors.append(f"[{entry_posix}] 入口脚本必须声明 'extends RefCounted'。")
        if not FUNC_INSPECT_RE.search(stripped_gd):
            report.errors.append(f"[{entry_posix}] 入口脚本缺少必需生命周期方法 'func inspect_import('。")
        if not FUNC_PREPARE_RE.search(stripped_gd):
            report.errors.append(f"[{entry_posix}] 入口脚本缺少必需生命周期方法 'func prepare_import('。")

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
    has_template = False
    for child in sorted(config.mods_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name == "_template":
            has_template = True
            continue
        mods.append(child.name)

    if include_template and has_template:
        mods.insert(0, "_template")
    elif not mods and has_template:
        # Empty workspace fallback: validate _template when no business mods exist yet
        mods.append("_template")

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
            )
        )
    return reports
