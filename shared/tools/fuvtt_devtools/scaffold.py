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

MODE_TO_SCHEMA: dict[str, str] = {
    "session-plugin": "fus.session-plugin.v1",
    "desktop-module": "fus.desktop-module.v1",
    "world-plugin": "fus.plugin.v2",
}
SCHEMA_TO_MODE: dict[str, str] = {v: k for k, v in MODE_TO_SCHEMA.items()}
VALID_NAMESPACES = ("mods", "external_modules")
PACK_FILE_NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+\.pck$")

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

DEFAULT_INWORLD_MODULE_GD = """extends ExtensionBase

const _RUNTIME_PACKAGED_REL_PATH: String = "lib/fu_runtime/v2.gd"
const _RUNTIME_DEV_REL_PATH: String = "../../../../shared/sdk/fu_runtime/v2.gd"

var _runtime_sdk: RefCounted = null
var _overlay_node: Node2D = null


func _load_runtime_sdk() -> RefCounted:
\tvar self_script := get_script() as Script
\tif self_script == null or self_script.resource_path.is_empty():
\t\treturn null
\tvar base_dir: String = self_script.resource_path.split("::")[0].get_base_dir()
\tvar packaged_path: String = base_dir.path_join(_RUNTIME_PACKAGED_REL_PATH)
\tif FileAccess.file_exists(packaged_path) or ResourceLoader.exists(packaged_path):
\t\tvar scr: Script = load(packaged_path) as Script
\t\tif scr != null:
\t\t\treturn scr.new()
\tvar dev_path: String = base_dir.path_join(_RUNTIME_DEV_REL_PATH).simplify_path()
\tif FileAccess.file_exists(dev_path) or ResourceLoader.exists(dev_path):
\t\tvar dev_scr: Script = load(dev_path) as Script
\t\tif dev_scr != null:
\t\t\treturn dev_scr.new()
\treturn null


func _on_register(context: ExtensionContext) -> void:
\t_runtime_sdk = _load_runtime_sdk()
\tvar desktop_api: Object = context.consume_service("desktop_api")
\tvar world_node: Node = null
\tif desktop_api != null and desktop_api.has_method(&"get_desktop"):
\t\tvar desktop: Node = desktop_api.call(&"get_desktop") as Node
\t\tif is_instance_valid(desktop):
\t\t\tworld_node = desktop.get_node_or_null("World")
\tif is_instance_valid(world_node):
\t\t_overlay_node = Node2D.new()
\t\t_overlay_node.name = "__PASCAL_NAME__Overlay"
\t\tcontext.mount_node(world_node, _overlay_node)


func _on_unregister() -> void:
\t_overlay_node = null
\t_runtime_sdk = null


func serialize_module_state() -> Dictionary:
\treturn {}


func prepare_module_state(state: Dictionary) -> Dictionary:
\treturn {"ok": state.is_empty(), "reason": "unsupported_module_state" if not state.is_empty() else ""}


func apply_module_state(state: Dictionary) -> bool:
\treturn state.is_empty()
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
    schema: str = "fus.session-plugin.v1"
    entry_scene_path: Path | None = None


def resolve_scaffold_schema(mode: str | None = None, schema: str | None = None) -> str:
    """Resolve target plugin schema from `--mode` and/or `--schema` flags."""
    norm_mode = mode.strip().lower() if isinstance(mode, str) and mode.strip() else None
    norm_schema = schema.strip() if isinstance(schema, str) and schema.strip() else None

    if norm_mode is not None and norm_mode not in MODE_TO_SCHEMA:
        raise ScaffoldError(
            f"不支持的脚手架模式 '{mode}'；可选值：{', '.join(MODE_TO_SCHEMA.keys())}。"
        )
    if norm_schema is not None and norm_schema not in SCHEMA_TO_MODE:
        raise ScaffoldError(
            f"不支持的插件 schema '{schema}'；可选值：{', '.join(SCHEMA_TO_MODE.keys())}。"
        )
    if norm_mode is not None and norm_schema is not None:
        expected = MODE_TO_SCHEMA[norm_mode]
        if expected != norm_schema:
            raise ScaffoldError(
                f"--mode={norm_mode} (对应 {expected}) 与 --schema={norm_schema} 冲突。"
            )
    if norm_schema is not None:
        return norm_schema
    if norm_mode is not None:
        return MODE_TO_SCHEMA[norm_mode]
    return "fus.session-plugin.v1"


def validate_kebab_mod_name(mod_name: str) -> str:
    """Validate that `mod_name` is strict kebab-case, not reserved, and fits host 64-char ID limit."""
    cleaned = mod_name.strip()
    if cleaned == "_template" or cleaned.startswith("_template-"):
        raise ScaffoldError(f"不允许使用保留模板名称 '{cleaned}'。")
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


def _default_inworld_manifest(
    *,
    schema: str,
    plugin_id: str,
    display_name: str,
    namespace: str,
    pack_file: str,
    scene_rel: str,
    description: str | None,
    import_extensions: list[str] | None,
    action_label: str | None,
) -> dict[str, Any]:
    is_desktop = schema == "fus.desktop-module.v1"
    module_id = f"mod.{plugin_id}" if is_desktop else f"{plugin_id}.core"
    default_desc = (
        "基于 Fu vtt fu_runtime 构建的纯本机桌面表现模块。"
        if is_desktop
        else "基于 Fu vtt fu_runtime 构建的联机世界模块插件。"
    )
    manifest: dict[str, Any] = {
        "schema": schema,
        "host_api": 2,
        "scope": "hybrid" if import_extensions is not None else ("desktop" if is_desktop else "world"),
        "id": plugin_id,
        "version": "0.1.0",
        "name": display_name,
        "description": description.strip() if description and description.strip() else default_desc,
    }
    if not is_desktop and pack_file:
        manifest["pack_file"] = pack_file
    manifest["modules"] = [
        {
            "id": module_id,
            "display_name": display_name,
            "entry_scene": f"res://{namespace}/{plugin_id}/{scene_rel}",
            "version": 1,
            "network_version": 0 if is_desktop else 1,
            "local_only": is_desktop,
            "isolated_lifecycle": True,
            "requires": [],
            "conflicts": [],
            **({} if is_desktop else {"suppresses": []}),
        }
    ]
    manifest["settings"] = []
    if import_extensions is not None:
        manifest["entry"] = "entry.gd"
        manifest["import_extensions"] = import_extensions
        manifest["import_action_label"] = (
            action_label.strip()
            if action_label and action_label.strip()
            else f"导入 {import_extensions[0].upper()} 文件"
        )
    return manifest


def _snake_to_pascal(snake: str) -> str:
    return "".join(part.capitalize() for part in snake.split("_") if part) or "ModEntry"


def _clear_target_dir(target_dir: Path) -> None:
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


def _render_inworld_tscn(node_name: str, script_res_path: str) -> str:
    return (
        "[gd_scene load_steps=2 format=3]\n\n"
        f'[ext_resource type="Script" path="{script_res_path}" id="1_entry"]\n\n'
        f'[node name="{node_name}" type="Node2D"]\n'
        'script = ExtResource("1_entry")\n'
    )


def _render_inworld_agents_md(clean_mod_name: str, plugin_id: str, schema: str, namespace: str) -> str:
    return (
        f"# 插件开发规范（`{clean_mod_name}`）\n\n"
        f"- **Schema**: `{schema}`\n"
        f"- **Plugin ID**: `{plugin_id}`\n"
        f"- **模块资源根路径**: `res://{namespace}/{plugin_id}/`\n"
        "- **禁止全局 `class_name`**：外置模块脚本不得声明 `class_name`，避免污染宿主全局类名表。\n"
        "- **常用命令**：\n"
        f"  - `python shared/tools/fuvtt_cli.py validate {clean_mod_name}`\n"
        f"  - `python shared/tools/fuvtt_cli.py build {clean_mod_name}`\n"
        f"  - `python shared/tools/fuvtt_cli.py verify-host {clean_mod_name}`\n"
    )


def _scaffold_inworld_mod(
    *,
    cfg: WorkspaceConfig,
    clean_mod_name: str,
    plugin_id: str,
    resolved_display_name: str,
    target_schema: str,
    namespace: str | None,
    pack_file: str | None,
    description: str | None,
    normalized_exts: list[str] | None,
    action_label: str | None,
    force: bool,
) -> ScaffoldResult:
    is_desktop = target_schema == "fus.desktop-module.v1"
    resolved_ns = (namespace.strip() if isinstance(namespace, str) and namespace.strip() else None) or (
        "mods" if is_desktop else "external_modules"
    )
    if resolved_ns not in VALID_NAMESPACES:
        raise ScaffoldError(
            f"不支持的命名空间 '{resolved_ns}'；仅允许：{', '.join(VALID_NAMESPACES)}。"
        )

    if is_desktop:
        if pack_file is not None and pack_file.strip() != "":
            raise ScaffoldError("fus.desktop-module.v1 为纯 ZIP 直挂模式，不支持 --pack-file。")
        resolved_pack_file = ""
    else:
        if pack_file is None:
            resolved_pack_file = "content.pck"
        else:
            resolved_pack_file = pack_file.strip()
            if resolved_pack_file and (
                ".." in resolved_pack_file or not PACK_FILE_NAME_RE.match(resolved_pack_file)
            ):
                raise ScaffoldError(
                    f"非法的 --pack-file '{pack_file}'：必须匹配 ^[a-zA-Z0-9_.-]+\\.pck$ 且不含 '..'。"
                )

    template_name = "_template-desktop-module" if is_desktop else "_template-world-plugin"
    template_dir = cfg.mods_dir / template_name
    target_dir = cfg.mods_dir / clean_mod_name
    if target_dir.exists():
        if not force:
            raise ScaffoldError(
                f"目标插件目录已存在：mods/{clean_mod_name}（如需覆盖请显式传入 --force）。"
            )
        _clear_target_dir(target_dir)

    target_dir.mkdir(parents=True, exist_ok=True)
    pascal_name = _snake_to_pascal(plugin_id)
    scene_rel = "module.tscn" if is_desktop else f"feature_{plugin_id}.tscn"
    script_rel = "module.gd" if is_desktop else f"feature_{plugin_id}.gd"

    if template_dir.is_dir():
        tpl_plugin_id = template_name.lstrip("_").replace("-", "_")
        tpl_manifest_file = template_dir / "plugin.json"
        if tpl_manifest_file.is_file():
            try:
                tpl_manifest_raw = json.loads(tpl_manifest_file.read_text(encoding="utf-8-sig"))
                if isinstance(tpl_manifest_raw, dict) and isinstance(tpl_manifest_raw.get("id"), str):
                    tpl_plugin_id = tpl_manifest_raw["id"].strip() or tpl_plugin_id
            except (OSError, ValueError):
                pass

        for src_item in sorted(template_dir.rglob("*")):
            rel = src_item.relative_to(template_dir)
            rel_posix = rel.as_posix()
            if rel_posix == "manifest.json":
                continue
            parts = list(rel.parts)
            if len(parts) >= 2 and parts[0] in VALID_NAMESPACES and parts[1] == tpl_plugin_id:
                parts[0] = resolved_ns
                parts[1] = plugin_id
            if len(parts) >= 3 and parts[-1] == f"feature_{tpl_plugin_id}.tscn":
                parts[-1] = scene_rel
            elif len(parts) >= 3 and parts[-1] == f"feature_{tpl_plugin_id}.gd":
                parts[-1] = script_rel
            elif len(parts) >= 3 and tpl_plugin_id in parts[-1]:
                parts[-1] = parts[-1].replace(tpl_plugin_id, plugin_id)
            dst_item = target_dir / Path(*parts)
            if src_item.is_dir():
                dst_item.mkdir(parents=True, exist_ok=True)
            else:
                dst_item.parent.mkdir(parents=True, exist_ok=True)
                if src_item.suffix.lower() in (".json", ".gd", ".tscn", ".tres", ".md", ".cfg"):
                    text = src_item.read_text(encoding="utf-8-sig")
                    text = (
                        text.replace(f"res://mods/{tpl_plugin_id}/", f"res://{resolved_ns}/{plugin_id}/")
                        .replace(f"res://external_modules/{tpl_plugin_id}/", f"res://{resolved_ns}/{plugin_id}/")
                        .replace(f"feature_{tpl_plugin_id}", f"feature_{plugin_id}")
                        .replace(tpl_plugin_id, plugin_id)
                        .replace(template_name, clean_mod_name)
                    )
                    _write_utf8_no_bom(dst_item, text)
                else:
                    shutil.copy2(src_item, dst_item)

    manifest_path = target_dir / "plugin.json"
    if manifest_path.is_file():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            manifest_data = None
        if not isinstance(manifest_data, dict):
            manifest_data = _default_inworld_manifest(
                schema=target_schema,
                plugin_id=plugin_id,
                display_name=resolved_display_name,
                namespace=resolved_ns,
                pack_file=resolved_pack_file,
                scene_rel=scene_rel,
                description=description,
                import_extensions=normalized_exts,
                action_label=action_label,
            )
        else:
            manifest_data["schema"] = target_schema
            manifest_data["host_api"] = int(manifest_data.get("host_api") or 2)
            manifest_data["scope"] = (
                "hybrid"
                if normalized_exts is not None
                else ("desktop" if is_desktop else str(manifest_data.get("scope") or "world"))
            )
            manifest_data["id"] = plugin_id
            manifest_data["version"] = str(manifest_data.get("version") or "0.1.0")
            manifest_data["name"] = resolved_display_name
            if description and description.strip():
                manifest_data["description"] = description.strip()
            if is_desktop:
                manifest_data.pop("pack_file", None)
                manifest_data.pop("pck", None)
            elif resolved_pack_file:
                manifest_data["pack_file"] = resolved_pack_file
            else:
                manifest_data.pop("pack_file", None)
                manifest_data.pop("pck", None)
            mods_list = manifest_data.get("modules")
            if isinstance(mods_list, list) and mods_list and isinstance(mods_list[0], dict):
                mods_list[0]["id"] = f"mod.{plugin_id}" if is_desktop else f"{plugin_id}.core"
                mods_list[0]["display_name"] = resolved_display_name
                mods_list[0]["entry_scene"] = f"res://{resolved_ns}/{plugin_id}/{scene_rel}"
                mods_list[0]["local_only"] = is_desktop
                mods_list[0]["network_version"] = 0 if is_desktop else int(mods_list[0].get("network_version") or 1)
            if normalized_exts is not None:
                manifest_data["entry"] = str(manifest_data.get("entry") or "entry.gd")
                manifest_data["import_extensions"] = normalized_exts
                manifest_data["import_action_label"] = (
                    action_label.strip()
                    if action_label and action_label.strip()
                    else f"导入 {normalized_exts[0].upper()} 文件"
                )
    else:
        manifest_data = _default_inworld_manifest(
            schema=target_schema,
            plugin_id=plugin_id,
            display_name=resolved_display_name,
            namespace=resolved_ns,
            pack_file=resolved_pack_file,
            scene_rel=scene_rel,
            description=description,
            import_extensions=normalized_exts,
            action_label=action_label,
        )

    _write_utf8_no_bom(manifest_path, json.dumps(manifest_data, ensure_ascii=False, indent=2) + "\n")

    ns_dir = target_dir / resolved_ns / plugin_id
    ns_dir.mkdir(parents=True, exist_ok=True)
    entry_scene_path = ns_dir / scene_rel
    entry_script_path = ns_dir / script_rel
    if not entry_script_path.is_file():
        _write_utf8_no_bom(
            entry_script_path,
            DEFAULT_INWORLD_MODULE_GD.replace("__PASCAL_NAME__", pascal_name),
        )
    if not entry_scene_path.is_file():
        _write_utf8_no_bom(
            entry_scene_path,
            _render_inworld_tscn(pascal_name, f"res://{resolved_ns}/{plugin_id}/{script_rel}"),
        )

    if normalized_exts is not None:
        hybrid_entry_rel = str(manifest_data.get("entry") or "entry.gd")
        hybrid_entry_path = target_dir / hybrid_entry_rel
        if not hybrid_entry_path.is_file():
            _write_utf8_no_bom(hybrid_entry_path, DEFAULT_ENTRY_GD)

    agents_md_path = target_dir / "AGENTS.md"
    if agents_md_path.is_file():
        agents_text = agents_md_path.read_text(encoding="utf-8-sig")
        agents_text = (
            agents_text.replace("<your-mod-name>", clean_mod_name)
            .replace("<mod-name>", clean_mod_name)
            .replace(template_name, clean_mod_name)
        )
        agents_text = re.sub(
            rf"\b(validate|build|sync|verify-host)\s+{re.escape(template_name)}\b",
            rf"\1 {clean_mod_name}",
            agents_text,
        )
        _write_utf8_no_bom(agents_md_path, agents_text)
    else:
        _write_utf8_no_bom(
            agents_md_path,
            _render_inworld_agents_md(clean_mod_name, plugin_id, target_schema, resolved_ns),
        )

    return ScaffoldResult(
        mod_name=clean_mod_name,
        plugin_id=plugin_id,
        display_name=resolved_display_name,
        target_dir=target_dir,
        manifest_path=manifest_path,
        entry_path=entry_script_path,
        schema=target_schema,
        entry_scene_path=entry_scene_path,
    )


def scaffold_mod(
    mod_name: str,
    config: WorkspaceConfig | None = None,
    *,
    display_name: str | None = None,
    import_extensions: Sequence[str] | None = None,
    action_label: str | None = None,
    description: str | None = None,
    force: bool = False,
    mode: str | None = None,
    schema: str | None = None,
    namespace: str | None = None,
    pack_file: str | None = None,
) -> ScaffoldResult:
    """Create a new plugin under `mods/<mod-name>/` for v1 session plugins or in-world modules."""
    cfg = config or load_config()
    target_schema = resolve_scaffold_schema(mode, schema)
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

    if target_schema != "fus.session-plugin.v1":
        return _scaffold_inworld_mod(
            cfg=cfg,
            clean_mod_name=clean_mod_name,
            plugin_id=plugin_id,
            resolved_display_name=resolved_display_name,
            target_schema=target_schema,
            namespace=namespace,
            pack_file=pack_file,
            description=description,
            normalized_exts=normalized_exts,
            action_label=action_label,
            force=force,
        )

    if namespace is not None and namespace.strip():
        raise ScaffoldError("fus.session-plugin.v1 会话插件不使用 --namespace。")
    if pack_file is not None and pack_file.strip():
        raise ScaffoldError("fus.session-plugin.v1 会话插件不使用 --pack-file。")

    template_dir = cfg.mods_dir / "_template"
    if not template_dir.is_dir():
        raise ScaffoldError(f"找不到标准脚手架模板目录：{template_dir}")

    target_dir = cfg.mods_dir / clean_mod_name
    if target_dir.exists():
        if not force:
            raise ScaffoldError(
                f"目标插件目录已存在：mods/{clean_mod_name}（如需覆盖请显式传入 --force）。"
            )
        _clear_target_dir(target_dir)

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
