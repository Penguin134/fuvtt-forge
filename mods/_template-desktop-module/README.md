# Template Desktop Module (`mods/_template-desktop-module/`)

> **Fu vtt `fus.desktop-module.v1`（纯 ZIP 直挂 / `local_only`）桌面表现模块模板**

## 特性概览

1. **纯 ZIP 直挂（无 `.pck` 导出）**：遵循 `fus.desktop-module.v1` 契约，`local_only: true`、`network_version: 0`，构建产物为 `build/<mod>/<mod>.zip`。
2. **共享运行时 SDK 复用**：通过 `_load_runtime_sdk()` 加载 `fu_runtime/v2.gd`（优先包内 `lib/fu_runtime/v2.gd`，开发态回退至 `../../../../shared/sdk/fu_runtime/v2.gd`），复用 `DesktopApiHelper`、`HookHelper`、`SlotHelper` 与 `LogBus`。
3. **官方 `desktop_api` 接入**：读取 GM 状态、网络角色、网格尺度、选中单位生命值（自动识别 `is_vitals_masked`）与 GM 专有保存模块记录 `read_saved_module_entry`。
4. **事件与表现双轨挂载**：
   - 订阅内置 `HookIds`（`dice.rolled`、`vitals.changed`、`vitals.downed`、`combat.started`）与自定义命名空间 Hook `mod.template_desktop_module.burst_triggered`。
   - 通过 `world.overlays`（`above_entities`）注册世界空间波纹画布，并通过 `ExtensionContext.mount_node` 挂载桌面顶部播报横幅，停用时零泄漏自动清理。

## 快速使用

```powershell
python shared/tools/fuvtt_cli.py init my-desktop-fx --mode desktop-module
python shared/tools/fuvtt_cli.py validate my-desktop-fx
python shared/tools/fuvtt_cli.py build my-desktop-fx
python shared/tools/fuvtt_cli.py verify-host my-desktop-fx --fus-repo auto
```
