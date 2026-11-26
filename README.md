# Fu vtt Mod 开发工作区（`fuvtt-forge`）

面向 Steam 虚拟桌面跑团软件 **Fu vtt**（Steam App ID: `3177780`，当前适配基准：Playtest `v0.0.65`）的官方双模 Mod 开发仓库。本仓库为 Mod SDK 与自动化工具链，非游戏本体。特别感谢 [弗人](https://github.com/FullPeople)。

本仓库内置了面向局外存档导入的 **`fu_sdk`（`v1.3.0`）**、面向局内实时桌面与联机世界扩展的 **`fu_runtime`（`v2.0.0`）**，以及零第三方依赖的 **Python 打包部署工具链（`fuvtt_cli.py`）**。你**无需事先深入 Godot 底层或 C# 宿主源码**，只需安装 **Python 3.10+** 即可开始开发并构建纯 `.zip` 插件（仅在构建需要打包 `content.pck` 的 `fus.plugin.v2` 世界模块或运行 `verify-host` 无头验证时，才需额外指定本机 Godot 4.8-beta1 Mono 控制台可执行文件）。

> **双模扩展能力概览（Playtest `v0.0.65`）**：
> - **局外会话导入插件（`fus.session-plugin.v1`，`.zip`）**：在“会话管理页”运行于后台线程，读取 `.json` / `.uvtt` / `.zip` 等外部战役文件并生成带多场景、多楼层、物理墙门、棋子、迷雾光源与场景传送盒的标准 `.world` 存档（进房联机的普通玩家无需安装该导入插件）。
> - **局内纯本机桌面模块（`fus.desktop-module.v1`，`local_only`，纯 `.zip` 直挂）**：在桌面对局内实时运行，通过 `desktop_api` 查询权限/棋子生命/GM 存档、订阅 `HookBus` 内置及自定义事件、绘制 `world.overlays` 世界覆盖层并通过 `mount_node` 挂载本地 HUD。无需导出 `.pck`，纯本机生效、不参与联机状态握手。
> - **局内联机世界模块（`fus.plugin.v2`，`.fup` 含 `content.pck` + `SHA256SUMS.txt`）**：完整接入 `CompBase` 自定义实体组件与 `public_state` 联机披露、属性页撤销重做、`WorldModuleState` 三阶段持久化、`network.actions` / `network.projections` 联机同步以及侧栏面板、模块设置页、模式栏与实体动作槽位。

---

## 1. 快速上手：3 分钟跑通构建与导入

克隆本仓库后，`mods/` 目录默认随仓包含四份可参考实现：`mods/_template/`（`fus.session-plugin.v1`）、`mods/_template-desktop-module/`（`fus.desktop-module.v1`）、`mods/_template-world-plugin/`（`fus.plugin.v2`）以及 `mods/sdk-log-console/`（`fus.desktop-module.v1`，`scope: "hybrid"` 局外 + 局内双激活示例）。其余具体插件子目录均已通过 `.gitignore` 忽略，便于你独立维护。

### 前置准备

1. 本机已安装 **Python 3.10+**（工具链仅使用 Python 标准库，无需 `pip install` 任何依赖）。
2. 本机已安装 **Fu vtt Playtest** 客户端。
3. （仅 `world-plugin` `.fup` 打包及 `verify-host` 无头验证需要）在 `.env.local` 中配置 `GODOT_BIN`（Godot 4.8-beta1 Mono 控制台版路径）。

### 第一步：初始化插件目录并打包构建

根据你要开发的功能形态选择对应 `--mode`（默认为 `session-plugin`）：

```powershell
# 1A. 生成局外导入插件（输出 .zip，无需 GODOT_BIN）
python shared/tools/fuvtt_cli.py init demo-importer --mode session-plugin --name "示例导入插件" --ext fusdemo
python shared/tools/fuvtt_cli.py build demo-importer

# 1B. 生成局内纯本机桌面表现模块（输出 .zip，无需 GODOT_BIN）
python shared/tools/fuvtt_cli.py init demo-overlay --mode desktop-module --name "示例桌面表现"
python shared/tools/fuvtt_cli.py build demo-overlay

# 1C. 生成局内联机世界模块（打包 .fup + content.pck，需配置 GODOT_BIN 或传 --godot-bin）
python shared/tools/fuvtt_cli.py init demo-world-mod --mode world-plugin --name "示例世界模块"
python shared/tools/fuvtt_cli.py build demo-world-mod
```

构建工具会自动执行静态规范校验，将共享 SDK（v1 注入 `lib/fu_sdk/`；局内模式注入 `<ns>/lib/fu_runtime/` 与精简 `fu_sdk` 共享模块）打入归档，并在 `build/<mod-name>/` 下输出 `<mod-name>.zip` 或 `<mod-name>.fup`（另含逐文件 SHA-256 清单 `build-manifest.json`）。

### 第二步：将 Mod 安装到本地 Fu vtt 客户端（二选一）

Fu vtt 客户端会对已安装插件执行严格的逐文件 SHA-256 防篡改校验，**切勿手工将源码拷入客户端解压目录**。请选用以下任一方式：

#### 方式 A：本地 HTTP 直链安装与免重启热更新（日常开发首选，零 `.env` 配置）

1. 在终端启动内置本地静态包源：
   ```powershell
   python shared/tools/fuvtt_cli.py serve --host 127.0.0.1 --port 8765
   ```
2. 启动 **Fu vtt** 客户端 -> 进入**会话管理页** -> 打开**插件面板**。
3. 复制终端打印的直链（`.zip` 如 `http://127.0.0.1:8765/demo-importer.zip`，`.fup` 如 `http://127.0.0.1:8765/demo-world-mod.fup`），粘贴进安装链接框点击 **安装**，确认开关处于**已启用**。
4. **后续改代码热更新**：在另一终端加上 `--bump-dev` 重新打包（自动递增补丁版本号，如 `0.1.0 -> 0.1.1`）：
   ```powershell
   python shared/tools/fuvtt_cli.py build demo-importer --bump-dev
   ```
   回到客户端**插件面板**点击 **检查更新** 即可拉取最新版本（注：修改了局内 `.pck`/模块代码且当前已在桌内运行时，客户端会提示需重启或重进会话生效）。

#### 方式 B：离线一键原子同步到游戏目录

1. 在仓库根目录将 `.env.example` 复制为 `.env.local`，填入本地客户端目录（即包含 `FUS.exe` 的文件夹）：
   ```ini
   FUVTT_INSTALL_DIR=<your-steam-library>/steamapps/common/fuvtt
   ```
2. 执行 `sync`（若源码变动会自动重打包，并原子写入 `<FUVTT_INSTALL_DIR>/FUS_Data/session_plugins/` 与 `registry.json`）：
   ```powershell
   python shared/tools/fuvtt_cli.py sync demo-importer --allow-same-version
   ```
3. 启动或切回客户端**插件面板**点击 **刷新** 即可生效。

> **重要防踩坑提示**：始终在 `mods/<mod-name>/` 中修改源码并通过 `serve` 或 `sync` 更新，**切勿直接修改 `FUS_Data/session_plugins/packages/` 内的已解压文件**，否则客户端会检出哈希篡改（`plugin_files_changed`）并自动禁用该插件。

### 第三步：在游戏内使用与对外分发

* **使用导入插件（`fus.session-plugin.v1`）**：启用后在**会话管理页**点击插件导入按钮或直接拖入对应后缀文件，确认预检统计后即生成 `.world` 存档；**普通联机玩家无需安装导入插件**即可进房游玩。
* **使用局内模块（`fus.desktop-module.v1` / `fus.plugin.v2`）**：在**插件面板**启用插件后，在新建或编辑战役的**模块选择设置**中勾选你的模块即可进入桌面运行；`fus.desktop-module.v1` 仅作用于安装者本机，`fus.plugin.v2` 的联机扩展需房间参与方按契约一致性安装对应版本。
* **发布分发**：将构建产物 `build/<mod-name>/<mod-name>.zip` 或 `<mod-name>.fup` 上传至 GitHub Releases 或任意直链存储，把下载链接发给玩家，对方在**插件面板**粘贴链接点击 **安装** 即可（终端用户无需安装 Python 或本仓库）。

---

## 2. 从零开发新 Mod 的标准步骤

1. **生成脚手架**：使用 `init` 选择 `--mode session-plugin`、`--mode desktop-module` 或 `--mode world-plugin`。
2. **编写清单与核心脚本**（全部文本文件统一 **UTF-8 无 BOM**、LF 换行，局内模块严禁声明全局 `class_name` 或调用 `preload()`）：
   * `fus.session-plugin.v1`：编辑 `plugin.json`（含必填 `import_extensions` 与 `settings`）和 `entry.gd`（`extends RefCounted`，实现 `inspect_import` 与 `prepare_import`）。
   * `fus.desktop-module.v1`：编辑 `plugin.json`（`local_only: true`, `network_version: 0`）与 `mods/<plugin_id>/module.tscn` + `module.gd`（`extends ExtensionBase`，动态加载 `lib/fu_runtime/v2.gd`）。
   * `fus.plugin.v2`：编辑 `plugin.json`（`pack_file: "content.pck"`）与 `external_modules/<plugin_id>/feature_<plugin_id>.tscn` + `.gd`（`extends ExtensionBase`）及 `comp_<plugin_id>__<name>.tscn`/`.gd`（`extends CompBase`）。
3. **静态校验与打包**：运行 `validate <mod-name>` 与 `build <mod-name>`。
4. **无头引擎验收（推荐）**：配置 `.env.local` 中的 `GODOT_BIN`（及可选 `FUS_REPO_DIR`）后运行 `verify-host <mod-name> --fus-repo`，确认脚本编译、契约联动与零 `ObjectDB` 对象泄漏。
5. **独立版本控制**：需要单独托管仓库时，直接在 `mods/<mod-name>/` 内执行 `git init`，外层 Monorepo 会自动忽略非模板子目录。

---

## 3. 仓库目录结构概览

```text
fuvtt-forge/
├── mods/                            # 独立 Mod 源码目录（非模板子目录均已 .gitignore 忽略）
│   ├── _template/                   # 随仓模板：fus.session-plugin.v1 局外导入脚手架
│   ├── _template-desktop-module/    # 随仓模板：fus.desktop-module.v1 纯本机桌面模块脚手架
│   ├── _template-world-plugin/      # 随仓模板：fus.plugin.v2 联机世界模块脚手架
│   ├── sdk-log-console/             # 随仓示例：fus.desktop-module.v1 (scope: hybrid) 双激活控制台诊断插件
│   └── <your-mod>/                  # 你的独立业务插件目录
├── shared/                          # 跨插件共享基础设施
│   ├── sdk/
│   │   ├── fu_sdk/                  # 局外导入 SDK（v1.3.0，35 个脚本；utils/ 与 logging/ 同时供局内复用）
│   │   └── fu_runtime/              # 局内运行时 SDK（v2.0.0，desktop_api/hook/slot/comp/network 助手）
│   ├── tools/
│   │   ├── fuvtt_cli.py             # 零依赖 Python 3 统一命令行入口
│   │   ├── fuvtt_devtools/          # 脚手架、静态校验、.zip/.fup 打包、HTTP 热更、同步与无头验证核心库
│   │   └── tests/                   # 自动化单元测试与双模端到端（e2e_dual_mode）测试套件
│   └── docs/                        # 宿主底层协议、场景组件 API 与 Playtest 版本演进实测文档
├── build/                           # 打包产物 (.zip/.fup)、哈希清单与无头验证证据目录（Git 忽略）
├── .cache/                          # 注册表备份、客户端契约快照与暂存目录（Git 忽略）
├── .env.example                     # 本地环境变量模板（复制为 .env.local 后按需填写）
└── README.md                        # 仓库快速上手说明（本文档）
```

---

## 4. CLI 常用命令速查表

| 命令示例 | 功能说明 |
| :--- | :--- |
| `python shared/tools/fuvtt_cli.py init <mod> --mode session-plugin --ext <后缀>` | 生成 `fus.session-plugin.v1` 局外导入插件脚手架 |
| `python shared/tools/fuvtt_cli.py init <mod> --mode desktop-module` | 生成 `fus.desktop-module.v1` 纯本机桌面模块脚手架 |
| `python shared/tools/fuvtt_cli.py init <mod> --mode world-plugin` | 生成 `fus.plugin.v2` 联机世界模块脚手架 |
| `python shared/tools/fuvtt_cli.py validate <mod>`（或 `--all --include-template`） | 执行三协议对齐的编码、清单、二进制禁用与 `class_name` 静态校验 |
| `python shared/tools/fuvtt_cli.py build <mod>`（可加 `--bump-dev` / `--godot-bin`） | 自动内嵌对应 SDK 并打包输出 `.zip` 或 `.fup`（含 `content.pck` + `SHA256SUMS.txt`） |
| `python shared/tools/fuvtt_cli.py serve --port 8765` | 启动本地 HTTP 插件源，输出 `.zip` 与 `.fup` 直链供客户端免重启热更新 |
| `python shared/tools/fuvtt_cli.py sync <mod> --allow-same-version` | 原子部署至 `.env.local` 配置的游戏目录并更新 `registry.json` |
| `python shared/tools/fuvtt_cli.py verify-host <mod> --fus-repo` | 使用无头 Godot 编译脚本、验证契约并在只读宿主镜像中执行联动检查 |
| `python shared/tools/fuvtt_cli.py inspect-client --extract --source both` | 提取 Steam 客户端 PCK 并比对官方只读 Git 基线契约指纹 |

---

## 5. 开发者文档与 SDK Wiki 导览

完整的零基础入门教程、`plugin.json` 三协议清单规范、`fu_sdk`（`v1.3.0`）与 `fu_runtime`（`v2.0.0`）全部 API 手册以及分插件图鉴已同步发布至 [fuvtt-forge Wiki](https://github.com/Penguin134/fuvtt-forge/wiki)（其余实战教程与 API 手册均可通过 Wiki 首页与侧栏折叠目录直达）：

1. **[Wiki 首页（Home）](https://github.com/Penguin134/fuvtt-forge/wiki)** — 浏览三秒可读的目录导航树，按核心概念、实战教程、运行时 API、分插件图鉴与 CLI 工具链快速定位。
2. **[上手导读与架构总览（Getting-Started）](https://github.com/Penguin134/fuvtt-forge/wiki/Getting-Started)** — 对比三类协议选型路线、双模对象协作链路、GDScript 类型对照及最小生命周期骨架。
