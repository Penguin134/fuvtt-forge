# Template World Plugin (`mods/_template-world-plugin/`)

> **Fu vtt `fus.plugin.v2`（`.fup` + `content.pck`）外置世界模块插件模板**

## 特性概览

1. **`.fup` + `content.pck` 完整打包链路**：构建时自动内嵌 `fu_runtime` 及共享 `fu_sdk` 工具至 `lib/`，调用无头 Godot `PCKPacker` 生成 `content.pck`（`GDPC`）与 `SHA256SUMS.txt` 并封装为 `.fup`。
2. **`CompBase` 实体组件与 `public_state` 披露**：内置 `comp_template_world_plugin__marker.gd`，支持 `network_scope: "shared"`、主持暗藏（非授权端自动剥离）与 `dominance_priority` 仲裁。
3. **`EntityComponentPage` + `EditModeController` 撤销栈**：提供 `marker_component_page.tscn`/`.gd` 属性面板，通过 `edit_requested(&"field", ...)` 提交可撤销编辑。
4. **`WorldModuleState` 三阶段持久化与联机同步**：实现 `prepare_module_state`、`apply_module_state`、`serialize_module_state` 及完整 `network.actions`（3 方法）+ `network.projections`（`projection_changed` + 8 方法）。
5. **全量桌面槽位接入**：包含 `ui.desktop_panels`（右侧抽屉）、`ui.module_settings`（模块设置页）、`ui.mode_bar`（检视模式，`on_enter -> true`）、`ui.entity_actions`（行动栏与右键轮盘）及 `world.overlays`（`below_entities`）。

## 快速使用

```powershell
python shared/tools/fuvtt_cli.py init my-world-mod --mode world-plugin
python shared/tools/fuvtt_cli.py validate my-world-mod
python shared/tools/fuvtt_cli.py build my-world-mod
python shared/tools/fuvtt_cli.py verify-host my-world-mod --fus-repo auto
```
