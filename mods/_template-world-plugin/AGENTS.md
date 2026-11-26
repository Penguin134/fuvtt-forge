# 世界模块插件模板（`<mod-name>`）

> 推荐使用 `python shared/tools/fuvtt_cli.py init <your-mod-name> --mode world-plugin` 自动从本模板生成新世界模块插件；若手动复制本目录为 `mods/<your-mod-name>/`，请同步替换 `plugin.json`、`external_modules/` 子目录、文件名前缀与本文档占位说明。

## 1. 业务目标与适用范围

- **插件目录名**：`_template-world-plugin`（新插件请使用 `kebab-case`）
- **清单插件 ID**：`template_world_plugin`（`plugin.json` 中 `id` 必须匹配 `^[a-z][a-z0-9_]{0,63}$`）
- **核心目标**：演示 Fu vtt 完整外置世界模块插件（`fus.plugin.v2` / `.fup` + `content.pck`）架构，涵盖联机同步组件、撤销栈属性页、三阶段模块持久化、RPC 动作/投影与全套桌面 UI 槽位。
- **目标宿主契约**：`fus.plugin.v2`（`host_api: 2`、`scope: "world"`、`pack_file: "content.pck"`、`local_only: false`、`network_version: 1`）。

## 2. 目录结构与 `fu_runtime` SDK 规范

- `plugin.json`：遵循 `fus.plugin.v2` 契约，声明 `pack_file: "content.pck"` 与 `modules[0]`（`entry_scene` 指向 `res://external_modules/template_world_plugin/feature_template_world_plugin.tscn`）。
- `external_modules/template_world_plugin/feature_template_world_plugin.tscn` / `.gd`：继承 `ExtensionBase`，动态加载 `lib/fu_runtime/v2.gd`（开发态自动回退至 `../../../../shared/sdk/fu_runtime/v2.gd`），实现 `WorldModuleState`、`network.actions` 与 `network.projections`。
- `external_modules/template_world_plugin/comp_template_world_plugin__marker.tscn` / `.gd`：继承 `CompBase`，实现 `public_state(state, peer)`、`accepts_state`、`editable_fields` 与 `dominance_priority`。
- `external_modules/template_world_plugin/marker_component_page.tscn` / `.gd`：继承 `EntityComponentPage`，通过 `edit_requested(&"field", ...)` 对接 `EditModeController` 撤销栈。
- `marker_sidebar_panel.tscn` / `.gd`、`marker_settings_page.tscn` / `.gd`、`marker_world_overlay.gd`：桌面抽屉、模块设置页与世界覆盖层。
- **硬性编码约束**：
  - 全部 `.gd` 脚本严禁声明全局 `class_name` 或使用 `preload(...)`（统一使用 `load(...)`）。
  - 组件文件必须严格命名为 `comp_<plugin_id>__<name>.gd`（使 `CompBase.id_from_path()` 与注册 `id` 一致）。
  - `network.actions` 与 `network.projections` 的 `spec.id` 必须严格等于 `MODULE_ID`。
  - 文本源码与配置统一使用 UTF-8 无 BOM 与 LF（`\n`）换行，严禁写入本机绝对路径。

## 3. 校验、构建与本地联调命令

在工作区根目录下执行以下命令（构建输出位于 `build/<mod-name>/`，路径配置从根目录 `.env.local` 读取）：

```powershell
# 1. 静态契约门禁校验
python shared/tools/fuvtt_cli.py validate _template-world-plugin --include-template

# 2. 无头 Godot 导出 content.pck + SHA256SUMS.txt + .fup 打包
python shared/tools/fuvtt_cli.py build _template-world-plugin

# 3. Godot 无头编译、组件/网络契约与 FUS 宿主验证
python shared/tools/fuvtt_cli.py verify-host _template-world-plugin --fus-repo auto

# 4. 从本模板生成新世界模块插件
python shared/tools/fuvtt_cli.py init my-world-mod --mode world-plugin
```

## 4. 所需共享文档（按需引用）

- 运行时与防腐层 SDK 说明：`@../../shared/sdk/README.md`
- 插件入口与清单规范：`@../../shared/docs/plugin-lifecycle.md`
- 桌面、场景与覆盖层接口：`@../../shared/docs/desktop-and-scene-api.md`
- 规则、组件与钩子接口：`@../../shared/docs/macro-and-rules.md`
