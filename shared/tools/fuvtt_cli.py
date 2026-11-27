#!/usr/bin/env python3
"""Unified CLI entry point for Fu vtt Monorepo developer tools."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

# Ensure local package resolution regardless of invocation working directory
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from fuvtt_devtools.client_inspector import (  # noqa: E402
    PckFormatError,
    format_inspection_report,
    inspect_client,
)
from fuvtt_devtools.deployer import (  # noqa: E402
    DeployError,
    serve_builds,
    sync_mods,
)
from fuvtt_devtools.env_config import ConfigError, WorkspaceConfig, load_config  # noqa: E402
from fuvtt_devtools.host_verifier import HostVerifyError, verify_mods_with_host  # noqa: E402
from fuvtt_devtools.packager import PackageError, build_mods  # noqa: E402
from fuvtt_devtools.scaffold import ScaffoldError, scaffold_mod  # noqa: E402
from fuvtt_devtools.validator import ValidationError, validate_mods  # noqa: E402
from fuvtt_devtools.win32_wid_host import Win32WidError  # noqa: E402


def _configure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fuvtt_cli.py",
        description="Fu vtt 插件脚手架、Practice 宿主门禁、防腐层打包、无损同步、双源巡检与真机无头验证工具",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. init
    p_init = subparsers.add_parser("init", help="从标准模板创建新插件 (kebab-case -> snake_case)")
    p_init.add_argument("mod_name", metavar="<mod-name>", help="新插件目录名（kebab-case，如 dd2vtt-importer）")
    p_init.add_argument(
        "--mode",
        choices=("session-plugin", "desktop-module", "world-plugin"),
        default=None,
        help="插件协议模式：session-plugin（默认 v1）、desktop-module（纯 ZIP 本机表现模块）、world-plugin（v2 世界模块）",
    )
    p_init.add_argument(
        "--schema",
        choices=("fus.session-plugin.v1", "fus.desktop-module.v1", "fus.plugin.v2"),
        default=None,
        help="显式指定清单 schema（可替代或校验 --mode）",
    )
    p_init.add_argument(
        "--namespace",
        choices=("mods", "external_modules"),
        default=None,
        help="域内模块命名空间（默认 desktop-module 用 mods，world-plugin 用 external_modules）",
    )
    p_init.add_argument(
        "--pack-file",
        dest="pack_file",
        default=None,
        help="world-plugin 模式的 PCK 文件名（默认 content.pck；传空串 \"\" 使用纯 ZIP 直挂）",
    )
    p_init.add_argument("--name", dest="display_name", help="插件显示名称（默认根据目录名生成，1..80 字符）")
    p_init.add_argument(
        "--ext",
        dest="extensions",
        action="append",
        help="支持的导入文件后缀（不含点号，1..12 位小写字母数字，最多 8 个）",
    )
    p_init.add_argument("--action-label", dest="action_label", help="客户端导入菜单按钮文案")
    p_init.add_argument("--description", dest="description", help="插件功能简述（<= 2000 字符）")
    p_init.add_argument("--force", action="store_true", help="若目标目录已存在则强制覆盖")

    # 2. validate
    p_val = subparsers.add_parser("validate", help="对插件执行 Practice C# 宿主级静态契约、UTF-8 无 BOM 与配额校验")
    p_val.add_argument("mod_name", nargs="?", metavar="<mod-name>", help="指定单个插件目录名（如 _template 或 my-mod）")
    p_val.add_argument("--all", dest="select_all", action="store_true", help="校验 mods/ 下全部插件")
    p_val.add_argument("--include-template", action="store_true", help="配合 --all 时额外包含模板目录")

    # 3. build
    p_build = subparsers.add_parser("build", help="校验、自动内嵌 SDK 并生成确定性 .zip 或 .fup 插件包与哈希清单")
    p_build.add_argument("mod_name", nargs="?", metavar="<mod-name>", help="指定单个插件目录名")
    p_build.add_argument("--all", dest="select_all", action="store_true", help="打包 mods/ 下全部插件")
    p_build.add_argument("--include-template", action="store_true", help="配合 --all 时额外包含模板目录")
    p_build.add_argument(
        "--bump-dev",
        action="store_true",
        help="打包前自动递增 plugin.json 的补丁版本号 (patch)，防止本地热更新触发 plugin_version_conflict",
    )
    p_build.add_argument("--no-sdk", action="store_true", help="不自动内嵌 shared/sdk/fu_sdk 或 fu_runtime")
    p_build.add_argument("--godot-bin", dest="godot_bin", help="显式指定 Godot 控制台可执行文件路径（用于 .fup/.pck 打包）")

    # 4. sync
    p_sync = subparsers.add_parser("sync", help="离线内容寻址部署并无损合并更新客户端 registry.json（含 file_hashes/settings）")
    p_sync.add_argument("mod_name", nargs="?", metavar="<mod-name>", help="指定单个插件目录名")
    p_sync.add_argument("--all", dest="select_all", action="store_true", help="同步 mods/ 下全部插件")
    p_sync.add_argument("--include-template", action="store_true", help="配合 --all 时额外包含模板目录")
    p_sync.add_argument("--dry-run", action="store_true", help="仅预演部署路径与哈希，不实际写入客户端目录")
    p_sync.add_argument(
        "--allow-same-version",
        dest="allow_same_version",
        action="store_true",
        help="允许开发态同版本不同 SHA-256 覆盖安装，并自动清理旧包目录",
    )
    p_sync.add_argument(
        "--target-dir",
        dest="target_dir",
        help="显式指定目标 session_plugins 目录（覆盖 .env.local 配置，常用于测试）",
    )
    p_sync.add_argument("--godot-bin", dest="godot_bin", help="显式指定 Godot 控制台可执行文件路径（自动重打包 .fup 时使用）")

    # 5. serve
    p_serve = subparsers.add_parser("serve", help="启动本地 HTTP 静态源以配合客户端 UI 免重启检查更新")
    p_serve.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    p_serve.add_argument("--port", type=int, default=8765, help="监听端口（默认 8765）")

    # 6. inspect-client
    p_insp = subparsers.add_parser("inspect-client", help="解包或巡检 Steam PCK 与官方 FUS Git 双源宿主契约变更")
    p_insp.add_argument("--extract", action="store_true", help="从客户端 FUS.exe 提取 Embedded PCK 至 build/extracted_pck/")
    p_insp.add_argument("--diff", action="store_true", help="对比上次基线快照（若基线已存在默认自动对比）")
    p_insp.add_argument("--fail-on-change", action="store_true", help="若检测到契约/字节码指纹变更则返回非零退出码")
    p_insp.add_argument(
        "--source",
        choices=("auto", "steam", "git", "both"),
        default="auto",
        help="巡检数据源：steam、git、both 或 auto（若配置了 FUS_REPO_DIR 则自动双源 both，否则 steam）",
    )
    p_insp.add_argument("--git-ref", dest="git_ref", help="官方 FUS 只读 Git 引用（默认取 FUS_SOURCE_REF）")
    p_insp.add_argument("--fus-repo", dest="fus_repo", help="显式指定官方 FUS 只读源码仓路径（覆盖 FUS_REPO_DIR）")
    p_insp.add_argument("--exe-path", dest="exe_path", help="显式指定 FUS.exe 路径")
    p_insp.add_argument("--extracted-dir", dest="extracted_dir", help="显式指定已解包 PCK 目录（默认 build/extracted_pck）")
    p_insp.add_argument("--json", dest="as_json", action="store_true", help="以 JSON 格式输出快照与比对结果")

    # 7. verify-host
    p_ver = subparsers.add_parser("verify-host", help="使用隔离 Godot 4.8-beta1 无头引擎真实编译并执行插件契约冒烟")
    p_ver.add_argument("mod_name", nargs="?", metavar="<mod-name>", help="指定单个插件目录名（如 _template 或 my-mod）")
    p_ver.add_argument("--all", dest="select_all", action="store_true", help="验证 mods/ 下全部插件")
    p_ver.add_argument("--include-template", action="store_true", help="配合 --all 时额外包含模板目录")
    p_ver.add_argument("--sample", dest="sample_path", help="可选：显式指定传入 inspect_import/prepare_import 的样本文件路径")
    p_ver.add_argument("--godot-bin", dest="godot_bin", help="显式指定 Godot 控制台可执行文件路径（覆盖 GODOT_BIN）")
    p_ver.add_argument(
        "--fus-repo",
        dest="fus_repo",
        nargs="?",
        const="auto",
        default=None,
        help="可选：使用只读暂存的官方 FUS 源码仓执行宿主级联动验证（不填路径则读取 FUS_REPO_DIR）",
    )
    p_ver.add_argument(
        "--ui-wid",
        dest="ui_wid",
        action="store_true",
        help="启用 Windows 隐藏宿主窗口 (--wid) 真实渲染校验，挂载宿主主题并输出 PNG 截图证据",
    )
    p_ver.add_argument("--timeout", type=int, default=120, help="单个插件无头校验超时秒数（默认 120）")

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    config: WorkspaceConfig | None = None,
) -> int:
    _configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    active_cfg: WorkspaceConfig | None = config
    try:
        cfg = active_cfg or load_config()
        active_cfg = cfg

        if args.command == "init":
            res = scaffold_mod(
                args.mod_name,
                config=cfg,
                display_name=args.display_name,
                import_extensions=args.extensions,
                action_label=args.action_label,
                description=args.description,
                force=args.force,
                mode=args.mode,
                schema=args.schema,
                namespace=args.namespace,
                pack_file=args.pack_file,
            )
            rel_dir = res.target_dir.relative_to(cfg.workspace_root).as_posix()
            print(f"[OK] 已创建插件脚手架：{rel_dir}")
            print(f"  - 协议 Schema:          {res.schema}")
            print(f"  - 清单 ID (snake_case): {res.plugin_id}")
            print(f"  - 显示名称:             {res.display_name}")
            if res.entry_scene_path is not None:
                rel_scene = res.entry_scene_path.relative_to(cfg.workspace_root).as_posix()
                print(f"  - 入口场景:             {rel_scene}")
            print(f"  - 下一步校验命令:       python shared/tools/fuvtt_cli.py validate {res.mod_name}")
            return 0

        if args.command == "validate":
            reports = validate_mods(
                cfg,
                mod_name=args.mod_name,
                select_all=args.select_all,
                include_template=args.include_template,
            )
            if not reports:
                print("[WARN] mods/ 目录下未找到可校验的插件。")
                return 0

            any_failed = False
            for rep in reports:
                if rep.ok:
                    ver = rep.manifest.get("version") if rep.manifest else "?"
                    pid = rep.manifest.get("id") if rep.manifest else "?"
                    print(
                        f"[PASS] {rep.mod_name} (id={pid}, v{ver}, files={rep.runtime_file_count}, estimated={rep.estimated_bytes} B)"
                    )
                    for warn in rep.warnings:
                        print(f"  [WARN] {warn}")
                else:
                    any_failed = True
                    print(f"[FAIL] {rep.mod_name}")
                    for err in rep.errors:
                        print(f"  [ERROR] {err}")
                    for warn in rep.warnings:
                        print(f"  [WARN]  {warn}")
            return 1 if any_failed else 0

        if args.command == "build":
            artifacts = build_mods(
                cfg,
                mod_name=args.mod_name,
                select_all=args.select_all,
                include_template=args.include_template,
                bump_dev=args.bump_dev,
                no_sdk=args.no_sdk,
                godot_bin=args.godot_bin,
            )
            if not artifacts:
                print("[WARN] 未找到可构建的插件。")
                return 0

            for art in artifacts:
                rel_pkg = art.zip_path.relative_to(cfg.workspace_root).as_posix()
                if not art.sdk_bundled:
                    sdk_tag = "no-sdk"
                elif art.schema in ("fus.desktop-module.v1", "fus.plugin.v2"):
                    sdk_tag = "with fu_runtime+fu_sdk"
                else:
                    sdk_tag = "with fu_sdk"
                print(
                    f"[BUILT] {art.mod_name} -> {rel_pkg} "
                    f"(schema={art.schema}, id={art.plugin_id}, v{art.version}, "
                    f"{art.zip_size_bytes} B, files={len(art.files)}, {sdk_tag})"
                )
                print(f"  SHA-256: {art.sha256}")
            return 0

        if args.command == "sync":
            results = sync_mods(
                cfg,
                mod_name=args.mod_name,
                select_all=args.select_all,
                include_template=args.include_template,
                dry_run=args.dry_run,
                target_dir=args.target_dir,
                allow_same_version=args.allow_same_version,
                godot_bin=args.godot_bin,
            )
            if not results:
                print("[WARN] 未找到可同步的插件。")
                return 0

            mode_prefix = "[DRY-RUN]" if args.dry_run else "[SYNCED]"
            for res in results:
                redacted_pkg = cfg.redact_path(res.package_dir)
                redacted_reg = cfg.redact_path(res.registry_path)
                print(
                    f"{mode_prefix} {res.mod_name} (id={res.plugin_id}, v{res.version}, "
                    f"enabled={res.enabled}, file_hashes={res.file_hashes_count})"
                )
                print(f"  目标包目录: {redacted_pkg}")
                print(f"  注册表文件: {redacted_reg}")
                if res.backup_path is not None:
                    rel_bak = res.backup_path.relative_to(cfg.workspace_root).as_posix()
                    print(f"  注册表备份: {rel_bak}")
                if res.cleaned_old_package_dir is not None:
                    print(f"  已清理旧包: {cfg.redact_path(res.cleaned_old_package_dir)}")
            return 0

        if args.command == "serve":
            serve_builds(cfg, host=args.host, port=args.port)
            return 0

        if args.command == "inspect-client":
            result = inspect_client(
                cfg,
                extract=args.extract,
                exe_path=args.exe_path,
                extracted_dir=args.extracted_dir,
                source=args.source,
                git_ref=args.git_ref,
                fus_repo_dir=args.fus_repo,
            )
            if args.as_json:
                payload = {
                    "snapshot": result.snapshot,
                    "diff": {
                        "has_previous": result.diff.has_previous,
                        "is_clean": result.diff.is_clean,
                        "summary_status": result.diff.summary_status,
                        "client_version_change": result.diff.client_version_change,
                        "builtin_plugin_changes": result.diff.builtin_plugin_changes,
                        "changed_contract_files": result.diff.changed_contract_files,
                        "changed_external_files": result.diff.changed_external_files,
                        "git_version_change": result.diff.git_version_change,
                        "changed_git_files": result.diff.changed_git_files,
                    },
                }
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print(format_inspection_report(result, cfg))

            if args.fail_on_change and result.diff.has_previous and not result.diff.is_clean:
                return 2
            return 0

        if args.command == "verify-host":
            results = verify_mods_with_host(
                cfg,
                mod_name=args.mod_name,
                select_all=args.select_all,
                include_template=args.include_template,
                sample_path=args.sample_path,
                godot_bin=args.godot_bin,
                timeout_seconds=args.timeout,
                fus_repo=args.fus_repo,
                ui_wid=args.ui_wid,
            )
            if not results:
                print("[WARN] mods/ 目录下未找到可验证的插件。")
                return 0

            any_failed = False
            for vres in results:
                rel_ev = vres.evidence_dir.relative_to(cfg.workspace_root).as_posix()
                if vres.ok:
                    print(
                        f"[PASS] {vres.mod_name} (schema={vres.schema}, id={vres.plugin_id}, v{vres.version}, "
                        f"checks={vres.passed_checks}, scripts={len(vres.loaded_scripts)}, "
                        f"entities={vres.entity_count}, bytes={vres.serialized_bytes})"
                    )
                    if vres.host_contract_probe:
                        print(
                            f"  FUS 宿主联动校验: ok={vres.host_contract_probe.get('ok')} "
                            f"(checks={vres.host_contract_probe.get('passed_checks', 0)})"
                        )
                    if vres.ui_screenshot_path is not None:
                        rel_shot = vres.ui_screenshot_path.relative_to(cfg.workspace_root).as_posix()
                        focus_ok = vres.ui_wid_telemetry.get("focus_unchanged", True)
                        print(f"  UI 渲染截图: {rel_shot} (focus_unchanged={focus_ok})")
                    print(f"  验证证据: {rel_ev}")
                    for warn in vres.warnings:
                        print(f"  [WARN] {warn}")
                else:
                    any_failed = True
                    print(
                        f"[FAIL] {vres.mod_name} (schema={vres.schema}, exit={vres.exit_code}, timed_out={vres.timed_out}, "
                        f"checks={vres.passed_checks})"
                    )
                    if vres.ui_screenshot_path is not None:
                        rel_shot = vres.ui_screenshot_path.relative_to(cfg.workspace_root).as_posix()
                        print(f"  UI 渲染截图: {rel_shot}")
                    print(f"  验证证据: {rel_ev}")
                    for fail in vres.failures:
                        print(f"  [ERROR] {cfg.redact_path(fail)}")
                    for lerr in vres.log_errors:
                        print(f"  [LOG]   {cfg.redact_path(lerr)}")
            return 1 if any_failed else 0

        parser.error(f"未知子命令：{args.command}")
        return 2

    except (
        ConfigError,
        ScaffoldError,
        ValidationError,
        PackageError,
        DeployError,
        PckFormatError,
        HostVerifyError,
        Win32WidError,
        FileNotFoundError,
    ) as exc:
        msg = active_cfg.redact_path(str(exc)) if active_cfg is not None else str(exc)
        print(f"[ERROR] {msg}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
