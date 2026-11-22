"""Plugin scaffolding generator (`init` subcommand)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Sequence

from .env_config import WorkspaceConfig, load_config


KEBAB_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
EXT_TOKEN_RE = re.compile(r"^[a-z0-9]{1,12}$")
MAX_PLUGIN_ID_LEN = 64
MAX_IMPORT_EXTENSIONS = 8
MAX_DISPLAY_NAME_LEN = 80
MAX_DESCRIPTION_LEN = 2000

DEFAULT_ENTRY_GD = """extends RefCounted

const _SDK_PACKAGED_REL_PATH: String = "lib/fu_sdk/v1.gd"
const _SDK_DEV_REL_PATH: String = "../../shared/sdk/fu_sdk/v1.gd"


func _load_sdk_script() -> Script:
\tvar self_script := get_script() as Script
\tif self_script == null or self_script.resource_path.is_empty():
\t\treturn null
\tvar base_dir: String = self_script.resource_path.get_base_dir()
\tvar packaged_path: String = base_dir.path_join(_SDK_PACKAGED_REL_PATH)
\tif FileAccess.file_exists(packaged_path) or ResourceLoader.exists(packaged_path):
\t\treturn load(packaged_path) as Script
\tvar dev_path: String = base_dir.path_join(_SDK_DEV_REL_PATH).simplify_path()
\tif FileAccess.file_exists(dev_path) or ResourceLoader.exists(dev_path):
\t\treturn load(dev_path) as Script
\treturn null


func _create_sdk() -> RefCounted:
\tvar sdk_script: Script = _load_sdk_script()
\tif sdk_script == null:
\t\treturn null
\treturn sdk_script.new()


func inspect_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:
\tvar sdk: RefCounted = _create_sdk()
\tif sdk == null:
\t\treturn {"ok": false, "reason": "fu_sdk_not_found"}
\tvar session = sdk.create_session(host, options)
\tif session.is_cancelled():
\t\treturn session.err_cancelled()
\treturn session.ok_inspect(path, {"records": 0, "unsupported": 0}, {})


func prepare_import(path: String, options: Dictionary, host: RefCounted) -> Dictionary:
\tvar sdk: RefCounted = _create_sdk()
\tif sdk == null:
\t\treturn {"ok": false, "reason": "fu_sdk_not_found"}
\tvar session = sdk.create_session(host, options)
\tif session.is_cancelled():
\t\treturn session.err_cancelled()
\tvar builder = sdk.create_world_builder(session, 150.0)
\tvar init_res: Dictionary = builder.setup(session, 150.0)
\tif not bool(init_res.get("ok", false)):
\t\treturn init_res
\treturn builder.build_result(0, 0)
"""


class ScaffoldError(ValueError):
    """Raised when plugin scaffolding arguments or filesystem targets are invalid."""


@dataclass(frozen=True)
class ScaffoldResult:
    """Metadata describing a newly scaffolded plugin directory."""

    mod_name: str
    plugin_id: str
    display_name: str
    target_dir: Path
    manifest_path: Path
    entry_path: Path


def validate_kebab_mod_name(mod_name: str) -> str:
    """Validate that `mod_name` is strict kebab-case, not reserved, and fits host 64-char ID limit."""
    cleaned = mod_name.strip()
    if cleaned == "_template":
        raise ScaffoldError("不允许使用保留模板名称 '_template'。")
    if not KEBAB_CASE_RE.match(cleaned):
        raise ScaffoldError(
            f"插件目录名 '{mod_name}' 不符合 kebab-case 规范（仅允许小写字母开头、小写字母/数字与单连字符，如 'dd2vtt-importer'）。"
        )
    if len(cleaned) > MAX_PLUGIN_ID_LEN:
        raise ScaffoldError(
            f"插件目录名 '{mod_name}' 长度 ({len(cleaned)}) 超过宿主插件 ID 上限 {MAX_PLUGIN_ID_LEN} 字符。"
        )
    return cleaned


def mod_name_to_plugin_id(mod_name: str) -> str:
    """Convert kebab-case `mod_name` into host-compliant snake_case `plugin_id`."""
    validated = validate_kebab_mod_name(mod_name)
    return validated.replace("-", "_")


def mod_name_to_display_name(mod_name: str) -> str:
    """Generate a default human-friendly title from kebab-case `mod_name`."""
    return " ".join(part.capitalize() for part in mod_name.strip().split("-") if part)[:MAX_DISPLAY_NAME_LEN]


def normalize_extension(ext: str) -> str:
    """Normalize and validate an import extension token (`^[a-z0-9]{1,12}$`)."""
    token = ext.strip().lstrip(".").lower()
    if not token or not EXT_TOKEN_RE.match(token):
        raise ScaffoldError(
            f"导入文件扩展名 '{ext}' 非法：仅允许 1..12 位纯小写字母与数字（如 'uvtt' 或 'dd2vtt'），无需包含特殊符号。"
        )
    return token


def _default_manifest(plugin_id: str, display_name: str) -> dict[str, Any]:
    return {
        "schema": "fus.session-plugin.v1",
        "host_api": 1,
        "scope": "session",
        "id": plugin_id,
        "version": "0.1.0",
        "name": display_name,
        "description": "基于 Fu vtt 防腐层 SDK 构建的会话导入插件。",
        "entry": "entry.gd",
        "import_extensions": ["fusdemo"],
        "import_action_label": "导入示例场景文件",
        "settings": [
            {
                "id": "proxy",
                "type": "string",
                "label": "图片下载代理",
                "placeholder": "留空使用系统网络，或填写 http://127.0.0.1:7890",
                "default": "",
            },
            {
                "id": "include_hidden",
                "type": "bool",
                "label": "包含源文件中的隐藏图层与物件",
                "default": True,
            },
        ],
    }


def _write_utf8_no_bom(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n")
    path.write_bytes(normalized.encode("utf-8"))


def scaffold_mod(
    mod_name: str,
    config: WorkspaceConfig | None = None,
    *,
    display_name: str | None = None,
    import_extensions: Sequence[str] | None = None,
    action_label: str | None = None,
    description: str | None = None,
    force: bool = False,
) -> ScaffoldResult:
    """Create a new plugin under `mods/<mod-name>/` from `mods/_template/`."""
    cfg = config or load_config()
    clean_mod_name = validate_kebab_mod_name(mod_name)
    plugin_id = clean_mod_name.replace("-", "_")
    resolved_display_name = (
        display_name.strip() if display_name and display_name.strip() else mod_name_to_display_name(clean_mod_name)
    )
    if len(resolved_display_name) > MAX_DISPLAY_NAME_LEN:
        raise ScaffoldError(
            f"插件显示名称长度 ({len(resolved_display_name)}) 超过宿主上限 {MAX_DISPLAY_NAME_LEN} 字符。"
        )
    if description is not None and len(description.strip()) > MAX_DESCRIPTION_LEN:
        raise ScaffoldError(
            f"插件描述长度 ({len(description.strip())}) 超过宿主上限 {MAX_DESCRIPTION_LEN} 字符。"
        )

    normalized_exts: list[str] | None = None
    if import_extensions is not None:
        deduped: list[str] = []
        for raw_ext in import_extensions:
            for piece in str(raw_ext).split(","):
                if piece.strip():
                    norm = normalize_extension(piece)
                    if norm not in deduped:
                        deduped.append(norm)
        if not deduped:
            raise ScaffoldError("至少需要提供一个有效的导入文件后缀（--ext）。")
        if len(deduped) > MAX_IMPORT_EXTENSIONS:
            raise ScaffoldError(
                f"导入文件后缀数量 ({len(deduped)}) 超过宿主上限 {MAX_IMPORT_EXTENSIONS} 个。"
            )
        normalized_exts = deduped

    template_dir = cfg.mods_dir / "_template"
    if not template_dir.is_dir():
        raise ScaffoldError(f"找不到标准脚手架模板目录：{template_dir}")

    target_dir = cfg.mods_dir / clean_mod_name
    if target_dir.exists():
        if not force:
            raise ScaffoldError(
                f"目标插件目录已存在：mods/{clean_mod_name}（如需覆盖请显式传入 --force）。"
            )
        for dirpath, dirnames, filenames in os.walk(target_dir, topdown=False, followlinks=False):
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
            target_dir.rmdir()
        except OSError:
            pass

    target_dir.mkdir(parents=True, exist_ok=True)
    for src_item in sorted(template_dir.rglob("*")):
        rel = src_item.relative_to(template_dir)
        # Skip legacy placeholder manifest.json if still present in template
        if rel.as_posix() == "manifest.json":
            continue
        dst_item = target_dir / rel
        if src_item.is_dir():
            dst_item.mkdir(parents=True, exist_ok=True)
        else:
            dst_item.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_item, dst_item)

    # Ensure standard subdirectories exist
    (target_dir / "src").mkdir(parents=True, exist_ok=True)
    (target_dir / "assets").mkdir(parents=True, exist_ok=True)

    # Load or synthesize plugin.json
    manifest_path = target_dir / "plugin.json"
    if manifest_path.is_file():
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        if not isinstance(manifest_data, dict):
            manifest_data = _default_manifest(plugin_id, resolved_display_name)
    else:
        manifest_data = _default_manifest(plugin_id, resolved_display_name)

    manifest_data["schema"] = "fus.session-plugin.v1"
    manifest_data["host_api"] = 1
    manifest_data["scope"] = "session"
    manifest_data["id"] = plugin_id
    manifest_data["version"] = str(manifest_data.get("version") or "0.1.0")
    manifest_data["name"] = resolved_display_name
    manifest_data["entry"] = str(manifest_data.get("entry") or "entry.gd")

    if description is not None and description.strip():
        manifest_data["description"] = description.strip()
    elif manifest_data.get("description") == "基于 Fu vtt 防腐层 SDK 构建的会话导入插件模板。":
        manifest_data["description"] = "基于 Fu vtt 防腐层 SDK 构建的会话导入插件。"

    if normalized_exts is not None:
        manifest_data["import_extensions"] = normalized_exts
        if action_label and action_label.strip():
            manifest_data["import_action_label"] = action_label.strip()
        else:
            manifest_data["import_action_label"] = f"导入 {normalized_exts[0].upper()} 文件"
    else:
        existing_exts = manifest_data.get("import_extensions")
        if not isinstance(existing_exts, list) or not existing_exts:
            manifest_data["import_extensions"] = ["fusdemo"]
        else:
            manifest_data["import_extensions"] = [normalize_extension(str(x)) for x in existing_exts]
        if action_label and action_label.strip():
            manifest_data["import_action_label"] = action_label.strip()
        elif not manifest_data.get("import_action_label"):
            manifest_data["import_action_label"] = f"导入 {resolved_display_name} 文件"

    manifest_json = json.dumps(manifest_data, ensure_ascii=False, indent=2) + "\n"
    _write_utf8_no_bom(manifest_path, manifest_json)

    # Ensure entry.gd exists and has UTF-8 without BOM
    entry_rel = str(manifest_data["entry"])
    entry_path = target_dir / entry_rel
    if entry_path.is_file():
        entry_text = entry_path.read_text(encoding="utf-8-sig")
        entry_text = entry_text.replace("template_mod", plugin_id).replace("template-mod", clean_mod_name)
        _write_utf8_no_bom(entry_path, entry_text)
    else:
        _write_utf8_no_bom(entry_path, DEFAULT_ENTRY_GD)

    # Update local AGENTS.md placeholders and CLI command targets
    agents_md_path = target_dir / "AGENTS.md"
    if agents_md_path.is_file():
        agents_text = agents_md_path.read_text(encoding="utf-8-sig")
        agents_text = (
            agents_text.replace("# 插件模板（`<mod-name>`）", f"# 插件开发规范（`{clean_mod_name}`）")
            .replace("<your-mod-name>", clean_mod_name)
            .replace("<mod-name>", clean_mod_name)
            .replace("template-mod", clean_mod_name)
            .replace("template_mod", plugin_id)
        )
        agents_text = re.sub(
            r"\b(validate|build|sync)\s+_template\b",
            rf"\1 {clean_mod_name}",
            agents_text,
        )
        _write_utf8_no_bom(agents_md_path, agents_text)

    return ScaffoldResult(
        mod_name=clean_mod_name,
        plugin_id=plugin_id,
        display_name=resolved_display_name,
        target_dir=target_dir,
        manifest_path=manifest_path,
        entry_path=entry_path,
    )
