# 插件模板（`<mod-name>`）

> 推荐使用 `python shared/tools/fuvtt_cli.py init <your-mod-name>` 自动从本模板生成新插件；若手动复制本目录为 `mods/<your-mod-name>/`，请同步替换 `plugin.json` 与本文档中的占位说明。

## 1. 业务目标与适用范围

- **插件目录名**：`template-mod`（目录使用 `kebab-case`）
- **清单插件 ID**：`template_mod`（`plugin.json` 中 `id` 必须匹配 `^[a-z][a-z0-9_]{0,63}$`，小写字母开头、最长 64 字符）
- **核心目标**：简述本插件在 Fu vtt 中转换或导入的目标格式（如 Universal VTT `.dd2vtt` / `.uvtt`、Foundry 导出场景、自定义地图包等）。
- **目标宿主契约**：现役 `Practice` 主线（Steam Playtest `v0.0.56` / `v0.0.57`），会话导入插件（`schema: "fus.session-plugin.v1"`、`scope: "session"`、`host_api: 1`）。

## 2. 目录结构与防腐层 SDK 规范

- `plugin.json`：遵循 `fus.session-plugin.v1` 契约的插件清单（UTF-8 无 BOM，`<= 128 KiB`）；`settings` 与 `import_extensions` 均为硬必填数组，且 `settings` 仅允许 `"string"` 与 `"bool"` 类型。
- `entry.gd`：继承 `RefCounted` 的插件入口，必须暴露 `inspect_import(path, options, host)` 与 `prepare_import(path, options, host)`。
- `src/`：存放本插件拆分的纯解析器或业务子脚本（通过相对路径 `load()` 加载，禁止使用 `preload()`）。
- `assets/`：存放插件自带静态资源。
- **`fu_sdk` 防腐层调用约束**：
  - 严禁在业务代码中直接拼装底层 `world.entity_state`、`world.members`、`fus.floor_layers.v2` 图层结构或硬编码 `res://scenes/entities/components/...` 路径。
  - 严禁向 `sprite_path` 写入 `user://` 路径（宿主仅接受 `""`、`asset://<sha256>.<ext>` 或 `res://` 贴图）。
  - 推荐两阶段导入顺序：先写入墙体/门窗/空气挖空/文字/矢量并调用 `builder.finish_geometry_preview()`，再归档重型图片并写入地图与棋子。
  - 统一通过 `entry.gd` 中的 `_create_sdk()` 动态加载 `lib/fu_sdk/v1.gd`（构建打包态优先，源码开发态自动回退至 `../../shared/sdk/fu_sdk/v1.gd`），调用 `ImportSession` 与 `WorldBuilder` 完成探测与场景构建。

## 3. 当前进度

- [x] 对齐 `fus.session-plugin.v1` 清单与 `fu_sdk` v1.1 防腐层入口骨架
- [ ] 实现源文件格式解析与 `inspect_import` 资源统计
- [ ] 实现 `prepare_import` 两阶段几何/资产转换逻辑
- [ ] 通过 `validate`、`build`、`verify-host` 闭环校验并在本地 Playtest 客户端完成导入回归验证

## 4. 校验、构建与本地联调命令

在工作区根目录下执行以下命令（构建输出统一位于 `../../build/<mod-name>/`，缓存位于 `../../.cache/`，客户端与引擎路径从根目录 `.env.local` 读取）：

```powershell
# 1. 静态契约门禁校验（对齐 C# PluginPackageJob 9 项强门禁）
python shared/tools/fuvtt_cli.py validate _template

# 2. 确定性打包（自动将 shared/sdk/fu_sdk/ 内嵌至包内 lib/fu_sdk/）
python shared/tools/fuvtt_cli.py build _template

# 3. Godot 4.8-beta1 Mono 真机无头编译与导入回合验收（隔离证据收敛于 build/<mod>/verify_evidence/）
python shared/tools/fuvtt_cli.py verify-host _template

# 4A. 本地 HTTP 托管热更新流（推荐：配合 --bump-dev 在客户端插件面板“检查更新”免重启生效）
python shared/tools/fuvtt_cli.py build _template --bump-dev
python shared/tools/fuvtt_cli.py serve

# 4B. 离线原子直写同步流（写入 FUS_Data/session_plugins/ 并补全 file_hashes + settings 合并 registry.json）
python shared/tools/fuvtt_cli.py sync _template
```

## 5. 所需共享文档（按需引用）

开发本插件时，按当前任务仅读取所需文档，禁止全量无关加载：

- 防腐层 SDK 接口说明：`@../../shared/sdk/README.md`
- 插件入口与清单规范：`@../../shared/docs/plugin-lifecycle.md`
- 场景、迷雾、高度与权限接口：`@../../shared/docs/desktop-and-scene-api.md`
- 宏系统钩子与规则数据适配：`@../../shared/docs/macro-and-rules.md`
- 内测版本变动与兼容性记录：`@../../shared/docs/playtest-notes.md`
