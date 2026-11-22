# Shared Tools — Fu vtt 零依赖自动化开发、双源巡检与无头验证工具链

> [!WARNING]
> **Playtest 内测阶段说明（验证基准：2026-11-20）**
> 当前工具链契约 100% 锚定现役 **Practice 主线**（Git `origin/codex/fuvtt-project-sync` `v0.0.56` / Steam Playtest 客户端 `v0.0.57`，`fus.session-plugin.v1` / `host_api = 1`，Godot `4.8.beta1.mono` + `.NET 10`）。后续客户端推送更新时，请先执行 `inspect-client --extract --source both` 检查宿主契约与上游源码变动。

本目录提供纯 Python 3 标准库实现（零第三方依赖、完全兼容离线沙箱）的命令行工具包 `fuvtt_cli.py`，覆盖脚手架初始化、Practice C# 宿主级静态门禁校验、防腐层 SDK 自动内嵌与确定性打包、本地无损部署（`sync` / `serve`）、Steam PCK + 官方 Git 双源金丝雀巡检，以及隔离 Godot 4.8-beta1 真机无头验证（`verify-host`）。

---

## 1. 目录结构

- `fuvtt_cli.py`：统一命令行入口。
- `fuvtt_devtools/`：核心功能模块包：
  - `env_config.py`：`.env.local` 解析（支持 `FUVTT_INSTALL_DIR`、`FUS_REPO_DIR`、`FUS_SOURCE_REF`、`GODOT_BIN`）、`BUILD_DIR` / `CACHE_DIR` 沙箱边界强校验与多路径脱敏（`<FUVTT_INSTALL_DIR>` / `<FUS_REPO_DIR>` / `<GODOT_BIN>`）。
  - `scaffold.py`：`kebab-case` 插件目录初始化与 `snake_case` 清单 ID 自动转换（对齐宿主 64 字符 ID / 80 字符名称 / 最多 8 个 1..12 位扩展名约束）。
  - `validator.py`：100% 对齐 `PluginPackageJob.cs` 的静态契约与归档校验（UTF-8 无 BOM、`id`/`settings[i].id` 正则、必填 `settings`/`import_extensions`、`plugin.json <= 128 KiB`、ZIP 2..1000 条目、解压 `<= 256 MiB`、大小写碰撞、尾随点/空格与 symlink/ReparsePoint 拦截）。
  - `packager.py`：自动内嵌 `shared/sdk/fu_sdk/` 至 `lib/fu_sdk/`，生成确定性 ZIP 归档、执行归档后置校验并在 `build-manifest.json` 输出逐文件 `file_hashes`。
  - `deployer.py`：离线内容寻址原子直写（`sync`，完整写入 `file_hashes`/`settings`/`source_url`/`installed_at` 并防降级与同版本冲突）与免重启本地 HTTP 静态源（`serve`）。
  - `client_inspector.py`：Godot 4 Embedded PCK (`GDPC` v4) 解析提取、`Practice.dll` / `.fus-storage.json` 监控，以及只读 `git show` 双源契约巡检（`--source steam|git|both`）。
  - `host_verifier.py`：隔离 Godot 4.8-beta1 无头探针执行器（`verify-host`），完成全量 `.gd` 真实编译、`MockHostBridge` 回合冒烟、`fus.practice.world` v3 结构不变量检查与 `bytes_to_var(var_to_bytes(world))` 二进制无损往返验证。
- `tests/test_devtools.py`：`unittest` 自动化单元测试套件（临时数据隔离于工作区 `.cache/test_tmp/`）。

---

## 2. 环境配置与安全边界

1. 在工作区根目录将 `.env.example` 复制为 `.env.local`，填写本地外部路径：
   ```dotenv
   FUVTT_INSTALL_DIR=<path/to/Steam/steamapps/common/fuvtt>
   FUS_REPO_DIR=<path/to/official/FUS>
   FUS_SOURCE_REF=origin/codex/fuvtt-project-sync
   GODOT_BIN=<path/to/Godot_v4.8-beta1_mono_win64_console.exe>
   BUILD_DIR=build
   CACHE_DIR=.cache
   ```
2. **安全与隔离约束**：
   - `BUILD_DIR` 与 `CACHE_DIR` 必须解析在工作区根目录内部，越界路径会被 `env_config` 直接拦截。
   - 控制台日志与快照文件会自动将 `FUVTT_INSTALL_DIR`、`FUS_REPO_DIR` 与 `GODOT_BIN` 脱敏为 `<FUVTT_INSTALL_DIR>`、`<FUS_REPO_DIR>`、`<GODOT_BIN>`，严禁在受控源码硬编码本机路径。
   - 对 `FUS_REPO_DIR` 全程严格只读（仅调用 `git show` / `rev-parse`），绝不执行写入或 `git checkout`。
   - `verify-host` 强制将 Godot 子进程的 `APPDATA`、`LOCALAPPDATA`、`TEMP` 与日志全部重定向至工作区内 `build/<mod-name>/verify_evidence/<run-id>/`，零污染系统目录或玩家存档。

---

## 3. CLI 子命令速查

### 3.1 `init` — 创建新插件脚手架

```powershell
python shared/tools/fuvtt_cli.py init dd2vtt-importer --name "Universal VTT 地图导入" --ext uvtt --ext dd2vtt
```
- 校验 `kebab-case` 且长度 `<= 64`，自动转换为 `snake_case` 清单 `id`（`^[a-z][a-z0-9_]{0,63}$`）。
- 自动规范化扩展名（最多 8 个，每项 `^[a-z0-9]{1,12}$`），生成 UTF-8 无 BOM 的 `plugin.json`、`entry.gd` 与局部 `AGENTS.md`。

### 3.2 `validate` — Practice 宿主级静态契约门禁

```powershell
python shared/tools/fuvtt_cli.py validate dd2vtt-importer
python shared/tools/fuvtt_cli.py validate _template
python shared/tools/fuvtt_cli.py validate --all
```
核心门禁项（1-to-1 对齐 `services/plugins/PluginPackageJob.cs`）：
- 拦截含 UTF-8 BOM (`EF BB BF`) 或非 UTF-8 编码的 `.json` / `.gd` / `.md` / `.cfg` 文件；
- 校验 `schema == "fus.session-plugin.v1"`、`host_api == 1`、`scope == "session"`、`id` 与 `settings[i].id` 匹配 `^[a-z][a-z0-9_]{0,63}$`、`name` 1..80 字符、`description <= 2000` 字符、`entry` 匹配 `^[a-zA-Z0-9_/-]+\.gd$`；
- 硬必填 `settings` 数组（允许 `[]`，`<= 32` 项，仅支持 `bool`/`string`，`label` 1..80，`string default <= 2048`）与 `import_extensions` 数组（1..8 项，`^[a-z0-9]{1,12}$`）；
- 校验 `plugin.json <= 128 KiB`、运行时文件数 `2..1000`、展开总大小 `<= 256 MiB`、单文件 `<= 64 MiB`、Windows 大小写路径去重、路径段禁 `.` / `..` / 尾随点或空格、拒绝 symlink / NTFS ReparsePoint；
- 检查 `entry.gd` 去注释后声明 `extends RefCounted` 及 `inspect_import(`、`prepare_import(`。

### 3.3 `build` — 内嵌防腐层 SDK 与确定性打包

```powershell
python shared/tools/fuvtt_cli.py build dd2vtt-importer
python shared/tools/fuvtt_cli.py build dd2vtt-importer --bump-dev
python shared/tools/fuvtt_cli.py build --all
```
- 自动将 `shared/sdk/fu_sdk/` 下所有 `.gd` 脚本内嵌至压缩包 `lib/fu_sdk/`（`--no-sdk` 可禁用）。
- 打包后执行归档级后置校验（条目数、解压上限、无 symlink 属性位 `0xA000`），并在 `build/<mod>/build-manifest.json` 写出逐文件 `file_hashes`。
- `--bump-dev` 严格递增 `major.minor.patch` 的 `patch` 数字段，适配宿主 `Split('-', '+')[0]` 版本比较逻辑。

### 3.4 双模本地联调部署（`serve` 与 `sync`）

> [!IMPORTANT]
> 切勿直接手工修改客户端 `FUS_Data/session_plugins/packages/<id>/<sha256>/` 下的已解压脚本，否则客户端 `InstalledValid()` 哈希校验会报 `plugin_files_changed`。

#### 方式 A（推荐）：`serve` 原生 HTTP 安装与免重启热更新
```powershell
python shared/tools/fuvtt_cli.py serve --host 127.0.0.1 --port 8765
```

#### 方式 B：`sync` 离线内容寻址原子直写（严格兼容 `PluginPackageJob.ReadRegistry`）
```powershell
python shared/tools/fuvtt_cli.py sync dd2vtt-importer --dry-run
python shared/tools/fuvtt_cli.py sync dd2vtt-importer
# 开发态同版本不同 SHA-256 覆盖安装（自动清理旧包目录）：
python shared/tools/fuvtt_cli.py sync dd2vtt-importer --allow-same-version
```
- 自动备份旧 `registry.json` 至 `.cache/registry_backups/`，解压并校验落盘 `file_hashes` 与 ZIP 一致；
- 完整写入宿主 `ReadRegistry()` 强校验字段：`file_hashes`、`settings`（无损保留已有合法用户配置、剔除废弃键、补齐新增默认键）、`source_url`、`installed_at`、`enabled`；
- 自动拦截版本降级（`plugin_version_older`）与未加开关的同版本哈希冲突（`plugin_version_conflict`）。

### 3.5 `inspect-client` — Steam PCK + 官方 Git 双源契约巡检

```powershell
# 自动双源巡检（配置 FUS_REPO_DIR 时等价 --source both，否则 steam）
python shared/tools/fuvtt_cli.py inspect-client

# Steam 更新后：提取最新 Embedded PCK 并同步比对官方 Practice 分支源码
python shared/tools/fuvtt_cli.py inspect-client --extract --source both

# 仅巡检指定官方 Git 只读分支（绝不修改官方仓）
python shared/tools/fuvtt_cli.py inspect-client --source git --git-ref origin/codex/fuvtt-project-sync
```
- Steam 轨同时监控 12 个核心 PCK `.gdc` 文件、`data_Practice_windows_x86_64/Practice.dll`、与 `FUS_Data/.fus-storage.json`；
- Git 轨只读监控 `PluginPackageJob.cs`、`session_plugins.gd`、`import_bridge.gd`、`desktop_feature_catalog.gd`、`obstacle_shape_data.gd` 等 13 份核心契约源码，并在报告顶部输出 Steam vs Git 版本代差对照。

### 3.6 `verify-host` — Godot 4.8-beta1 真机无头编译与回合验证

```powershell
python shared/tools/fuvtt_cli.py verify-host _template
python shared/tools/fuvtt_cli.py verify-host dd2vtt-importer --sample tests/fixture.uvtt
```
- 将构建好的 `.zip` 解包到隔离探针工程 `build/<mod>/verify_evidence/<run-id>/probe_project/`，调用 `GODOT_BIN --headless` 执行：
  1. 递归 `load()` 包内所有 `.gd` 脚本捕获语法/编译错误；
  2. 实例化 `entry.gd`，通过完整 `MockHostBridge` 驱动 `inspect_import()` + `prepare_import()`；
  3. 断言 `sha256`、`counts.unsupported`、`fus.practice.world` v3 / `fus.floor_layers.v2` / `entity_state` v3、`components[0..1]` 快路径、有限非零变换、`vector_drawing` 边界以及真实 Godot `bytes_to_var(var_to_bytes(world))` 无损往返；
  4. 扫描 `godot.log` / `stdout.log` / `stderr.log` 确认零 `SCRIPT ERROR` / `ERROR` / 对象泄漏告警。

---

## 4. 运行自动化单元测试

```powershell
python -m unittest discover -s shared/tools/tests -p "test_*.py" -v
```
