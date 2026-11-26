# Shared Tools — Fu vtt 零依赖自动化开发、双模打包与无头验证工具链

> [!WARNING]
> **Playtest 内测阶段说明（验证基准：2026-11-25）**
> 当前工具链契约 100% 锚定现役 **Practice 主线**（Git `origin/codex/v065-unified-20261125` `v0.0.65`，Commit `468999d4` / Steam Playtest 客户端，支持 `fus.session-plugin.v1`、`fus.desktop-module.v1` 与 `fus.plugin.v2` 三协议，Godot `4.8.beta1.mono` + `.NET 10`）。后续客户端推送更新时，请先执行 `inspect-client --extract --source both` 检查宿主契约与上游源码变动。

本目录提供纯 Python 3 标准库实现（零第三方依赖、完全兼容离线沙箱）的命令行工具包 `fuvtt_cli.py`，覆盖三模式脚手架初始化、Practice 宿主级静态门禁校验（含二进制禁用与局内 `class_name` 禁用）、`fu_sdk` / `fu_runtime` 自动内嵌、确定性 `.zip` 与 `.fup`（`content.pck` + `SHA256SUMS.txt`）打包、本地无损部署（`sync` / `serve`）、Steam PCK + 官方 Git 双源金丝雀巡检，以及隔离 Godot 4.8-beta1 真机无头与宿主联动验证（`verify-host`）。

---

## 1. 目录结构

- `fuvtt_cli.py`：统一命令行入口。
- `fuvtt_devtools/`：核心功能模块包：
  - `env_config.py`：`.env.local` 解析（支持 `FUVTT_INSTALL_DIR`、`FUS_REPO_DIR`、`FUS_SOURCE_REF`（默认 `origin/codex/v065-unified-20261125`）、`GODOT_BIN`）、`BUILD_DIR` / `CACHE_DIR` 沙箱边界强校验与多路径脱敏（`<FUVTT_INSTALL_DIR>` / `<FUS_REPO_DIR>` / `<GODOT_BIN>`）。
  - `scaffold.py`：三模式 `kebab-case` 插件脚手架初始化（`session-plugin` / `desktop-module` / `world-plugin`）与 `snake_case` 清单 ID 自动转换，生成合规 `plugin.json`、入口脚本/场景与局部说明。
  - `validator.py`：对齐 `PluginPackageJob.cs`、`tools/build_world_plugin.gd` 与 `tests/check_world_module_plugin_v2.gd` 的三协议静态契约与归档校验（UTF-8 无 BOM、`fus.session-plugin.v1` / `fus.desktop-module.v1` / `fus.plugin.v2` 字段规则、`modules` / `module`、`local_only` / `network_version`、`pack_file` 与 `SHA256SUMS.txt`、全局 `class_name` 拦截、禁用原生/脚本二进制扩展名拦截、symlink 与大小写碰撞拦截）。
  - `packager.py`：
    - `fus.session-plugin.v1`：递归内嵌 `shared/sdk/fu_sdk/**/*.gd`（35 个脚本）至 `lib/fu_sdk/`，输出 `build/<mod>/<mod>.zip`。
    - `fus.desktop-module.v1`：读取 `shared/sdk/fu_runtime/runtime_manifest.json` 并将 `fu_runtime`（6 脚本）与共享 `fu_sdk`（6 脚本）内嵌至 `<ns_root>/lib/{fu_runtime,fu_sdk}/`，输出纯 `.zip`。
    - `fus.plugin.v2`：同样内嵌 `fu_runtime` + 共享 `fu_sdk`，当设置 `pack_file`（默认 `"content.pck"`）时调用无头 `GODOT_BIN` `PCKPacker` 导出 `content.pck`（`GDPC`），生成 `SHA256SUMS.txt` 并封装确定性 `build/<mod>/<mod>.fup`（`--pack-file ""` 时退化为纯 `.zip`）。
  - `deployer.py`：离线内容寻址原子直写（`sync`，同时支持 `.zip` 与 `.fup`、`registry.json` 无损合并并把省略的局内 `settings` 归一为 `[]`）与免重启本地 HTTP 静态源（`serve`，提供 `.zip` 与 `.fup` 下载及 `X-Plugin-Schema` / `X-Plugin-SHA256` 响应头）。
  - `client_inspector.py`：Godot 4 Embedded PCK (`GDPC` v4) 解析提取、`Practice.dll` / `.fus-storage.json` 监控，以及只读 `git show` 双源契约巡检（`--source steam|git|both`）。
  - `host_verifier.py`：隔离 Godot 4.8-beta1 无头探针执行器（`verify-host`），针对 `v1` 执行 `MockHostBridge` 导入回合与 `var_to_bytes` 往返校验；针对局内 `fus.desktop-module.v1` / `fus.plugin.v2` 执行场景加载、零 `class_name`、`CompBase` / `public_state` / `WorldModuleState` / 槽位 / 零 `ObjectDB` 泄漏校验；传入 `--fus-repo` 时通过 `git archive` 暂存只读官方源码仓并运行真实宿主联动探针。
- `tests/`：`unittest` / `pytest` 自动化测试与需求驱动 E2E 套件（含 `test_devtools.py`、`test_devtools_inworld.py`、`test_fu_runtime_sdk.py`、`test_fu_sdk_*.py`、`test_console_log_mod.py` 与 `e2e_dual_mode/`；临时数据隔离于工作区 `.cache/test_tmp/`）。

---

## 2. 环境配置与安全边界

1. 在工作区根目录将 `.env.example` 复制为 `.env.local`，按需填写本地外部路径：
   ```dotenv
   FUVTT_INSTALL_DIR=<path/to/Steam/steamapps/common/fuvtt>
   FUS_REPO_DIR=<path/to/official/FUS>
   FUS_SOURCE_REF=origin/codex/v065-unified-20261125
   GODOT_BIN=<path/to/Godot_v4.8-beta1_mono_win64_console.exe>
   BUILD_DIR=build
   CACHE_DIR=.cache
   ```
2. **安全与隔离约束**：
   - `BUILD_DIR` 与 `CACHE_DIR` 必须解析在工作区根目录内部，越界路径会被 `env_config` 直接拦截。
   - 控制台日志与快照文件会自动将 `FUVTT_INSTALL_DIR`、`FUS_REPO_DIR` 与 `GODOT_BIN` 脱敏为 `<FUVTT_INSTALL_DIR>`、`<FUS_REPO_DIR>`、`<GODOT_BIN>`，严禁在受控源码硬编码本机路径。
   - 对 `FUS_REPO_DIR` 全程严格只读（仅调用 `git show` / `git archive` / `rev-parse`），绝不执行写入或 `git checkout`。
   - `verify-host` 与 `build`（`.fup`）强制将 Godot 子进程的 `APPDATA`、`LOCALAPPDATA`、`TEMP` 与日志全部重定向至工作区内隔离目录，零污染系统目录或玩家存档。

---

## 3. CLI 子命令速查

### 3.1 `init` — 创建双模新插件脚手架

```powershell
# 1. 局外导入插件（默认 --mode session-plugin，生成 entry.gd）
python shared/tools/fuvtt_cli.py init dd2vtt-importer --mode session-plugin --name "Universal VTT 地图导入" --ext uvtt --ext dd2vtt

# 2. 局内纯本机桌面模块（生成 mods/<id>/module.tscn + module.gd）
python shared/tools/fuvtt_cli.py init crit-banner --mode desktop-module --name "暴击横幅表现"

# 3. 局内联机世界模块（生成 external_modules/<id>/feature_<id>.tscn + comp_<id>__marker.*）
python shared/tools/fuvtt_cli.py init aura-marker --mode world-plugin --name "光环战术标记" --namespace external_modules --pack-file content.pck
```
- `--mode {session-plugin,desktop-module,world-plugin}`：选择插件协议模式（缺省为 `session-plugin`）；亦可用 `--schema {fus.session-plugin.v1,fus.desktop-module.v1,fus.plugin.v2}` 显式指定。
- `--namespace {mods,external_modules}`：指定局内模块命名空间（`desktop-module` 默认 `mods`，`world-plugin` 默认 `external_modules`）。
- `--pack-file PACK_FILE`：`world-plugin` 默认 `"content.pck"`；传入 `""` 可生成纯 `.zip` 直挂模式，不可用于 `session-plugin` 或 `desktop-module`。
- 校验 `kebab-case`（`<= 64` 字符，禁止保留名 `_template` / `_template-*`），自动转为 `snake_case` 清单 `id`，生成 UTF-8 无 BOM 骨架；`--ext`（最多 8 个 `^[a-z0-9]{1,12}$`）、`--action-label`、`--name`、`--description`、`--force` 均可按需指定。

### 3.2 `validate` — 三协议静态契约与安全门禁

```powershell
python shared/tools/fuvtt_cli.py validate dd2vtt-importer
python shared/tools/fuvtt_cli.py validate _template-desktop-module
python shared/tools/fuvtt_cli.py validate _template-world-plugin
python shared/tools/fuvtt_cli.py validate --all --include-template
```
核心门禁项（对齐 `PluginPackageJob.cs` 与 `build_world_plugin.gd`）：
- 自动忽略非运行期条目（`AGENTS.md`、`README.md`、`.gitkeep`、点开头隐藏文件、`__pycache__` 及局内 `.uid` 文件）；
- 拦截含 UTF-8 BOM (`EF BB BF`) 或非 UTF-8 编码的 `.json` / `.gd` / `.md` / `.cfg` / `.tscn` / `.tres` 文件；
- **`fus.session-plugin.v1`**：强制 `host_api == 1`、`scope == "session"`、非空 `import_extensions`（1..8 项）、必填 `settings`（`<= 32` 项，仅 `"bool"`/`"string"`）与 `entry`（`extends RefCounted` 含 `inspect_import` / `prepare_import`）；
- **`fus.desktop-module.v1`**：允许 `host_api` 为 `1` 或 `2`、`scope` 为 `"" | "desktop" | "world" | "hybrid"`，**禁止 `pack_file` / `pck` 与归档内 `.pck`**，校验 `modules` / `module`（1..16 项）中 `local_only === true`、`network_version === 0` 且 `entry_scene` 位于 `res://(mods|external_modules)/<plugin_id>/.*\.tscn`；
- **`fus.plugin.v2`**：允许 `host_api` 为 `1` 或 `2`、`scope` 为 `"" | "desktop" | "world" | "hybrid"`、`pack_file`（如 `"content.pck"`），`local_only == false` 时校验 `network_version >= 0`（推荐 `>= 1`），`settings` 可选（允许省略）；若同时声明 `import_extensions` 或 `entry`，一并校验混合导入入口；
- **安全红线**：局内 `.gd` 严禁全局 `class_name`；所有模式均严禁 `.dll` / `.exe` / `.so` / `.dylib` / `.gdextension` / `.bat` / `.cmd` / `.ps1` / `.sh` 二进制、symlink / NTFS ReparsePoint、路径穿越、Windows 大小写碰撞及超配额归档（单文件 & 归档 `<= 64 MiB`，展开 `<= 256 MiB`，`plugin.json` & `SHA256SUMS.txt <= 128 KiB`，归档条目 `2..1000`）。

### 3.3 `build` — 自动内嵌 SDK 与 `.zip` / `.fup` 确定性打包

```powershell
python shared/tools/fuvtt_cli.py build dd2vtt-importer
python shared/tools/fuvtt_cli.py build _template-desktop-module
python shared/tools/fuvtt_cli.py build _template-world-plugin --godot-bin <GODOT_BIN>
python shared/tools/fuvtt_cli.py build dd2vtt-importer --bump-dev
python shared/tools/fuvtt_cli.py build --all --include-template --no-sdk
```
- **局外 `v1`**：递归将 `shared/sdk/fu_sdk/**/*.gd`（35 脚本）内嵌至 `lib/fu_sdk/`，输出 `build/<mod>/<mod>.zip`；
- **局内 `fus.desktop-module.v1`**：按 `runtime_manifest.json` 将 `fu_runtime`（6 脚本）与共享 `fu_sdk`（6 脚本）内嵌至 `<ns_root>/lib/{fu_runtime,fu_sdk}/`，输出纯 `.zip`；
- **局内 `fus.plugin.v2`（含 `pack_file`）**：同样内嵌 `fu_runtime` + 共享 `fu_sdk`，通过 `--godot-bin`（或 `.env.local` 中的 `GODOT_BIN`）调用无头 `PCKPacker` 导出 `content.pck`（`GDPC` 魔数，自动纳入 `.godot/imported/*` 导出资源），生成 `SHA256SUMS.txt` 并输出 `build/<mod>/<mod>.fup`（传 `--no-sdk` 可跳过 SDK 注入）；
- 全部产物均执行后置归档校验并在 `build/<mod>/build-manifest.json` 写出 `file_hashes`；`--bump-dev` 递增 `patch` 数字段。

### 3.4 双模本地联调部署（`serve` 与 `sync`）

> [!IMPORTANT]
> 切勿手工修改客户端 `FUS_Data/session_plugins/packages/<id>/<sha256>/` 下的已解压脚本或 `.pck`，否则客户端 `InstalledValid()` 哈希校验会报 `plugin_files_changed` 并自动禁用插件。

#### 方式 A（推荐）：`serve` 原生 HTTP 安装与免重启热更新
```powershell
python shared/tools/fuvtt_cli.py serve --host 127.0.0.1 --port 8765
```
- 同时托管 `build/` 下的 `.zip` 与 `.fup` 产物（路由 `/<mod-name>.{zip,fup}`、别名 `/<plugin_id>.{zip,fup}` 与 `/index.json`），附带 `Cache-Control: no-store` 与 `X-Plugin-Id` / `X-Plugin-Version` / `X-Plugin-SHA256` / `X-Plugin-Schema` 响应头。

#### 方式 B：`sync` 离线内容寻址原子直写（兼容 `.zip` 与 `.fup`）
```powershell
python shared/tools/fuvtt_cli.py sync dd2vtt-importer --dry-run
python shared/tools/fuvtt_cli.py sync _template-desktop-module --allow-same-version
python shared/tools/fuvtt_cli.py sync _template-world-plugin --godot-bin <GODOT_BIN> --allow-same-version
python shared/tools/fuvtt_cli.py sync --all --include-template --target-dir build/test_session_plugins
```
- 若构建产物缺失或过期会自动重打包（`.fup` 支持 `--godot-bin`），自动备份旧 `registry.json` 至 `.cache/registry_backups/`，核验 `file_hashes`、无损合并 `settings`（省略的局内 `settings` 归一为 `[]`）、拦截版本降级（`plugin_version_older`）与未加 `--allow-same-version` 的哈希冲突（`plugin_version_conflict`）。

### 3.5 `inspect-client` — Steam PCK + 官方 Git 双源契约巡检

```powershell
# 自动双源巡检（配置 FUS_REPO_DIR 时等价 --source both，否则 steam）
python shared/tools/fuvtt_cli.py inspect-client

# Steam 更新后：提取最新 Embedded PCK 并同步比对官方 Practice 分支源码
python shared/tools/fuvtt_cli.py inspect-client --extract --source both

# 仅巡检指定官方 Git 只读分支（绝不修改官方仓）
python shared/tools/fuvtt_cli.py inspect-client --source git --git-ref origin/codex/v065-unified-20261125
```
- **Steam 轨**：监控 `CONTRACT_WATCH_FILES`（**52** 项核心与扩展基线 `.gdc`）+ `V065_CONTRACT_WATCH_FILES`（**12** 项 `v0.0.65` 局内模块宿主 `.gdc`，含 `desktop_api_service`、`comp_base`、`state_value`、`entity_component_page`、`world_overlay_host`、`module_settings_host`、`entity_extension_actions`、`mode_bar`、`network_module_contract`、`module_action_exchange`、`module_projections`、`world_disclosure`）、`Practice.dll` 与 `.fus-storage.json`（可选传 `--exe-path` / `--extracted-dir` / `--diff` / `--fail-on-change` / `--json`）；
- **Git 只读轨**：通过 `git -C <FUS_REPO_DIR> show <ref>:<path>` 监控 **73** 份核心与局内契约源码（`GIT_PRACTICE_WATCH_FILES`，可选传 `--fus-repo`），在报告顶部输出 Steam vs Git 版本代差对照。

### 3.6 `verify-host` — Godot 4.8-beta1 真机无头与官方宿主联动验证

```powershell
python shared/tools/fuvtt_cli.py verify-host _template
python shared/tools/fuvtt_cli.py verify-host _template-desktop-module --fus-repo
python shared/tools/fuvtt_cli.py verify-host _template-world-plugin --godot-bin <GODOT_BIN> --fus-repo
python shared/tools/fuvtt_cli.py verify-host dd2vtt-importer --sample tests/fixture.uvtt --timeout 120
python shared/tools/fuvtt_cli.py verify-host --all --include-template
```
- **局外 `v1` 探针**：解包 `.zip` 至隔离探针工程，在 `GODOT_BIN --headless` 中编译全量 `.gd`、运行 `MockHostBridge` 回合冒烟、`var_to_bytes` 无损往返及 `fu_sdk`（`LogBus`、`ModuleRegistry`、23 分脚本）探针；
- **局内 `fus.desktop-module.v1` / `fus.plugin.v2` 探针**：校验零全局 `class_name`、主入口场景实例化、`ExtensionBase._on_register`/`_on_unregister`、`CompBase` + `public_state` + `EntityComponentPage`、`WorldModuleState` 三阶段持久化、`HookIds` / 槽位注册及退出零 `ObjectDB` 泄漏；
- **官方只读宿主联动（`--fus-repo`）**：通过 `git archive` 在 `.cache/fus_host_stage/` 暂存只读 `<FUS_REPO_DIR>` 副本（绝不改动原官方仓），针对真实 FUS `ExtensionRuntime`、`DesktopFeatureCatalog.set_external_entries`、`DesktopApiService`、`WorldOverlayHost` 与 `ModuleProjections` 执行全链路宿主契约联动验证。

---

## 4. 运行自动化单元测试与 E2E 套件

```powershell
# 全量单元测试（覆盖 test_devtools、test_devtools_inworld、test_fu_runtime_sdk、test_fu_sdk_* 等）
python -m unittest discover -s shared/tools/tests -p "test_*.py" -v

# 需求驱动 4 层双模 E2E 测试套件（Godot 无头环境）
python shared/tools/tests/e2e_dual_mode/run_e2e.py --tier 0 1 2 3 4 --require-godot -v
```
