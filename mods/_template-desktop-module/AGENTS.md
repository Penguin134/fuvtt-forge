# 桌面表现模块模板（`<mod-name>`）

> 推荐使用 `python shared/tools/fuvtt_cli.py init <your-mod-name> --mode desktop-module` 自动从本模板生成新模块；若手动复制本目录为 `mods/<your-mod-name>/`，请同步替换 `plugin.json`、`mods/` 子目录与本文档中的占位说明。

## 1. 业务目标与适用范围

- **模块目录名**：`_template-desktop-module`（新模块请使用 `kebab-case`）
- **清单插件 ID**：`template_desktop_module`（`plugin.json` 中 `id` 必须匹配 `^[a-z][a-z0-9_]{0,63}$`）
- **核心目标**：演示 Fu vtt 纯本机桌面表现模块（`fus.desktop-module.v1`）的完整接入方式，无需导出 `.pck`，开启后不阻断联机开房。
- **目标宿主契约**：`fus.desktop-module.v1`（`host_api: 2`、`scope: "desktop"`、`local_only: true`、`network_version: 0`）。

## 2. 目录结构与 `fu_runtime` SDK 规范

- `plugin.json`：遵循 `fus.desktop-module.v1` 契约的清单（严禁包含 `pack_file` / `pck`；`modules[0].local_only` 必须为 `true` 且 `network_version` 为 `0`）。
- `mods/template_desktop_module/module.tscn`：入口场景（`Node2D` 根节点挂载 `module.gd`）。
- `mods/template_desktop_module/module.gd`：继承 `ExtensionBase`，动态加载 `lib/fu_runtime/v2.gd`（开发态自动回退至 `../../../../shared/sdk/fu_runtime/v2.gd`）。
- `mods/template_desktop_module/overlay_canvas.gd`：世界覆盖层画布脚本，实现 `bind_provider(provider) -> bool` 与 `deactivate()`。
- **硬性编码约束**：
  - 全部 `.gd` 脚本严禁声明全局 `class_name` 或使用 `preload(...)`（统一使用 `load(...)` 与相对路径解析）。
  - 文本源码与配置统一使用 UTF-8 无 BOM 与 LF（`\n`）换行，严禁写入本机绝对路径。
  - `local_only` 模块严禁注册 `network.actions`、`network.projections` 或 `network.presentations`。

## 3. 校验、构建与本地联调命令

在工作区根目录下执行以下命令（构建输出位于 `build/<mod-name>/`，路径配置从根目录 `.env.local` 读取）：

```powershell
# 1. 静态契约门禁校验
python shared/tools/fuvtt_cli.py validate _template-desktop-module --include-template

# 2. 纯 ZIP 确定性打包（自动内嵌 fu_runtime 与所需 fu_sdk 脚本至 lib/）
python shared/tools/fuvtt_cli.py build _template-desktop-module

# 3. Godot 无头编译、SDK 与宿主契约验证
python shared/tools/fuvtt_cli.py verify-host _template-desktop-module --fus-repo auto

# 4. 从本模板生成新桌面模块
python shared/tools/fuvtt_cli.py init my-desktop-fx --mode desktop-module
```

## 4. 所需共享文档（按需引用）

- 运行时与防腐层 SDK 说明：`@../../shared/sdk/README.md`
- 插件入口与清单规范：`@../../shared/docs/plugin-lifecycle.md`
- 桌面、场景与覆盖层接口：`@../../shared/docs/desktop-and-scene-api.md`
- 宏系统钩子与 HookIds 规范：`@../../shared/docs/macro-and-rules.md`
