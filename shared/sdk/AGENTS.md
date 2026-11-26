# Shared SDK (`fu_sdk`) 局部开发与质量守卫规范

本规范仅作用于 `shared/sdk/` 目录及其子目录，用于在扩展或维护 `fu_sdk` 防腐层与原生插件 SDK 时阻断历史高频返工模式。完整 API 清单请参阅同级 `README.md`。

## 1. 模块拆分与加载边界

- **一插件一脚本与模块/叶子边界**：`fu_sdk/plugins/<module_id>.gd` 必须按原生模块拆分为独立脚本，严禁将多个原生插件混写在同一 `.gd` 文件中；`fu_sdk/modules/*.gd` 纯功能子模块保持自包含，内部严禁 `load()` 同级 `modules/*.gd` 或 `utils/*.gd`；`fu_sdk/utils/*.gd`（`dag_cloner.gd`、`bounded_cloner.gd`、`value_utils.gd`、`validation_utils.gd`）为纯叶子级静态工具集，**严禁调用任何 `load()` 或 `preload()`**，仅使用 `extends RefCounted` 与 `static func`。调用方（`v1.gd`、`adapters/`、`logging/`、`plugins/`）须在各自实例级 `_util_scripts: Dictionary = {}` 中通过 `_load_util_script(...)` 按相对路径按需缓存 `Script` 句柄。
- **纯动态加载与文件卫生**：全部 `.gd` 脚本首行必须为 `extends RefCounted`，采用 UTF-8 无 BOM 与 LF（`\n`）换行；严禁使用 `class_name`、`preload(` 或硬编码本机路径（除 `fu_sdk/utils/*.gd` 纯叶子脚本外，其余脚本运行时统一基于 `(get_script() as Script).resource_path.split("::")[0].get_base_dir()` 调用 `load()`）。

## 2. 内存安全与单一克隆源不变量（防返工核心）

- **反向引用一律 `WeakRef`（零 `ObjectDB` 泄漏）**：任何被 `WorldBuilder`、`ImportSession` 或注册表缓存的子模块（含全部 `plugins/*.gd`），在反向持有父构建器/宿主实例时**必须使用 `WeakRef`**（`_world_builder_ref = weakref(world_builder)` + `_wb()` 判空解引），严禁持有强 `RefCounted` 引用形成循环泄漏；调用方的 `_util_scripts` 仅允许缓存 `Script` 资源句柄，严禁保存反向 `RefCounted` 引用；新增或修改子模块必须在无头测试中验证 `Performance.OBJECT_COUNT` 差值为 `0.0` 且父对象释放后调用安全降级。
- **单一公共工具与克隆源（指定 `fu_sdk/utils/` 为唯一规范源，禁止跨文件复制粘贴）**：`fu_sdk/utils/{dag_cloner,bounded_cloner,value_utils,validation_utils}.gd` 为全 SDK 唯一规范共享实现——重度 DAG 深拷贝与防抖记忆化（`DagMemo*` / `DagTravCtx` / `safe_clone_*`，保留 `log_bus.gd` `4 MiB` 与其余重度调用方 `16 MiB` 上限）统一复用 `fu_sdk/utils/dag_cloner.gd`；轻量有界深拷贝与环检测（`FallbackCloneCtx` / `bounded_fallback_clone*` / `simple_clone_*` / `DndTravCtx` / `dnd_clone_*` / `has_cycle` / `clone_fog_overrides`）统一复用 `fu_sdk/utils/bounded_cloner.gd`；数值/布尔/浮点/字符串/颜色强转与 `parse_int_*` 统一复用 `fu_sdk/utils/value_utils.gd`；Hex/UID 校验、BOM/NUL/控制字符清理、`component_id_from_script` 与 `is_unit_host` 统一复用 `fu_sdk/utils/validation_utils.gd`。严禁在 `v1.gd`、`adapters/`、`logging/` 或任何 `plugins/*.gd` 中手写或复制粘贴 `_DagMemo*`、`_FallbackCloneCtx`、`_safe_clone_*`、`_parse_int_val` 等重复实现（`modules/*.gd` 因自包含隔离约束除外），且节点预算必须大于该模块在 `<FUS_REPO_DIR>` 中的最大合法容量，**超限时必须显式报错或拒绝写入，严禁静默截断合法字典字段**。

## 3. GDScript 4 类型安全与宿主契约对齐

- **入口宽松归一、落盘严格对齐 `typeof`**：Godot 4 `JSON.parse_string()` 会将所有 JSON 数字解码为 `TYPE_FLOAT`。SDK 公开写入/配置入口须对有限整数值浮点（如 `2.0 -> 2`）做安全归一，而底层 `validate_*` 与落盘字典必须严格对齐 `<FUS_REPO_DIR>` 源码的 `TYPE_INT` / `TYPE_FLOAT` 要求（如浮点字段不得写入 `int`）。
- **禁止对未校验 `Variant` 裸写 `as Dictionary` / `as Array`**：读取外部或存档字典嵌套容器前，必须先判 `val is Dictionary`（或 `typeof(val) == TYPE_DICTIONARY`）与 `val is Array`，严禁直接 `raw.get("k") as Dictionary` 触发 Godot 运行时转型报错。
- **字符串与字节安全**：严禁在 `.gd` 源码中书写字面 `\u0000`；处理外部日志或文本字节流时须先剥离 `0x00` 并校验 UTF-8 合法性。
- **统一入口动词与停放签名**：新建分插件 SDK 时，世界级模块统一暴露 `configure_<module_id>` / `set_world_config`（兼容字典与位置参数），实体组件挂载统一暴露 `attach_<component>` 且末尾保持 `parked: bool = false, manual: bool = false`（强制拦截 `manual and not parked`）。

## 4. 跨里程碑同步与验证门禁

- 修改任何跨模块公共约定（如引用持有方式、错误返回结构、注册表字段）时，必须一次性同步全部受影响 `plugins/*.gd` 与 `shared/sdk/README.md`，避免遗留新旧分裂。
- 交付前必须通过：`python shared/tools/fuvtt_cli.py validate --all --include-template`、`verify-host` 及对应 `shared/tools/tests/` 套件。

## 5. 游戏内运行时 SDK（`fu_runtime/`）扩展与不变量

- **`fu_sdk/` 35 脚本不可变边界**：`shared/sdk/fu_sdk/` 必须保持既有的 **35 个 `.gd` 脚本**（受 `test_devtools.py` 锁定，供 `fus.session-plugin.v1` 使用）；所有面向 `fus.desktop-module.v1` 与 `fus.plugin.v2` 的游戏内运行时封装一律置于同级目录 `shared/sdk/fu_runtime/`（含 `v2.gd`、`desktop_api_helper.gd`、`hook_helper.gd`、`slot_helper.gd`、`comp_helper.gd`、`network_helper.gd` 与 `runtime_manifest.json`）。
- **文件卫生与无全局注册**：`fu_runtime/*.gd` 全部首行必须为 `extends RefCounted`，使用 UTF-8 无 BOM 与 LF（`\n`）换行，**严禁声明 `class_name`、调用 `preload(`、硬编码本机路径或书写字面 `\u0000`**（对齐 `<FUS_REPO_DIR>` `tools/build_world_plugin.gd` 打包校验）。
- **双定位相对加载契约**：`fu_runtime/` 内部统一通过 `(get_script() as Script).resource_path.split("::")[0].get_base_dir()`（附 `get_stack()` 与相对开发路径回退）同时解析同级辅助脚本与 `../fu_sdk/` 共享模块，并检测 `ResourceLoader.exists(p) or FileAccess.file_exists(p)` 以兼容 `.pck`（`fus.plugin.v2`）与纯 `.zip`（`fus.desktop-module.v1`）挂载。
- **零重复复用与 `runtime_manifest.json` 同步**：`fu_runtime/` 必须直接复用 `../fu_sdk/utils/{dag_cloner,bounded_cloner,value_utils,validation_utils}.gd`、`../fu_sdk/logging/log_bus.gd` 与 `../fu_sdk/plugins/module_registry.gd`，严禁复制实现任何深拷贝、周期检测、日志总线或标量强转逻辑；增删脚本时必须同步更新 `shared/sdk/fu_runtime/runtime_manifest.json`（由 `packager.py` 据此打包至 `<namespace_root>/lib/{fu_runtime,fu_sdk}/`）。
- **`WeakRef` 零泄漏与宿主契约守卫**：反向持有 `FuRuntime`、`ExtensionContext`、`ExtensionBase`、`DesktopApiService` 或 `LogBus` 一律使用 `WeakRef`（仅 `_sub_script_cache` / `_util_scripts` 缓存 `Script` 句柄），无头测试必须保持 `Performance.OBJECT_COUNT` 差值为 `0.0`；`fus.desktop-module.v1`（`local_only`）严禁注册 `network.actions`/`network.projections`；`ui.mode_bar` 的 `on_enter` 必须严格返回 `bool` `true`；`network.*` 槽位 `spec.id` 必须严格等于 `MODULE_ID`。
