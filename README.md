# Fu vtt Mod 开发工作区（`fuvtt-forge`）

面向 Steam 虚拟桌面跑团软件 **Fu vtt**（Steam App ID: `3177780`，当前适配基准：Playtest `v0.0.60`）的会话导入 Mod 开发仓库。本仓库为 Mod SDK，非游戏本体。特别感谢 [弗人](https://github.com/FullPeople)。

本仓库内置了屏蔽底层引擎细节的共享开发库 **`fu_sdk`（`v1.3.0`）** 与零第三方依赖的 **Python 打包部署工具链（`fuvtt_cli.py`）**。你**不需要事先了解 Godot 引擎**，也无需安装重型编译环境，只需具备基础编程经验并安装 Python 3.10+，即可快速编写、打包并将自定义地图或战役导入插件加载进游戏。

> **内测版本提示**：Fu vtt 目前处于 Steam Playtest 阶段，当前sdk开放的是**离线会话导入插件（`fus.session-plugin.v1`）**——即读取外部地图/战役文件（如 `.json`、`.uvtt`、`.zip` 等），生成带多场景、多楼层、碰撞墙门、角色棋子、动态视野光源与场景传送盒的可联机 `.world` 存档。局内实时脚本与自定义角色卡 UI 暂待sdk开发。

## 1. 快速上手：如何把 Mod 构建并导入游戏

克隆本仓库后，`mods/` 目录默认仅包含标准脚手架模板 `mods/_template/`（其余具体插件子目录均已配置 `.gitignore` 忽略，便于各插件作为独立 Git 仓库单独维护）。你可以用 3 分钟先生成一个最小示例插件并完整走通导入游戏的流程：

### 前置准备

1. 本机已安装 **Python 3.10+**（工具链仅使用 Python 标准库，无需 `pip install` 任何依赖）。
2. 本机已通过 Steam 安装 **Fu vtt Playtest** 客户端。

### 第一步：准备插件目录并打包构建（生成 `.zip` 插件包）

在仓库根目录打开终端：如果你还没有放入现成的插件源码目录，可先用 `init` 从内置模板一键生成最小可运行插件 `demo-mod`，随后运行 `build` 打包（若已在 `mods/<mod-name>/` 下放有独立插件目录，直接运行第二条 `build` 命令即可）：

```powershell
# 1. （首次体验）从内置 _template 生成一个可运行的示例插件 mods/demo-mod/
python shared/tools/fuvtt_cli.py init demo-mod --name "示例导入插件" --ext fusdemo

# 2. 校验并打包构建（将 demo-mod 替换为你实际的插件目录名 <mod-name>）
python shared/tools/fuvtt_cli.py build demo-mod
```

构建工具会自动完成静态规范检查，将共享库 `shared/sdk/fu_sdk/` 自动注入压缩包内的 `lib/fu_sdk/` 目录（终端玩家零前置依赖），并在 `build/demo-mod/demo-mod.zip` 输出最终插件包。

### 第二步：将 Mod 导入本地 Fu vtt 游戏客户端（二选一）

Fu vtt 客户端会对已安装插件执行严格的逐文件 SHA-256 防篡改校验，因此**不能直接把源码文件夹手工拷进游戏目录**。本仓库提供以下两种官方兼容的导入方式：

#### 方式 A：本地 HTTP 直链安装与免重启热更新（最推荐，日常开发首选）

无需填写任何本地路径配置文件，100% 走客户端原生下载安装流程：

1. 在终端启动内置的本地包托管服务（保持窗口运行）：
   ```powershell
   python shared/tools/fuvtt_cli.py serve --host 127.0.0.1 --port 8765
   ```
2. 启动 **Fu vtt** 游戏客户端 -> 进入**会话管理页** -> 打开**插件面板**。
3. 复制终端打印的安装直链（格式为 `http://127.0.0.1:8765/<mod-name>.zip`，例如 `http://127.0.0.1:8765/demo-mod.zip`），粘贴到插件面板的链接输入框中，点击 **安装**，并确认插件开关处于**已启用**状态。
4. **后续改代码免重启热更**：修改插件代码后，在另一个终端执行带 `--bump-dev` 的构建命令（自动递增补丁版本号，如 `0.1.0 -> 0.1.1`）：
   ```powershell
   python shared/tools/fuvtt_cli.py build demo-mod --bump-dev
   ```
   随后切回游戏客户端的**插件面板**点击 **检查更新**，无需重启游戏即可加载最新代码。

#### 方式 B：离线一键同步到游戏目录（无需保持终端开启 HTTP 服务）

1. 在仓库根目录将 `.env.example` 复制一份并重命名为 `.env.local`，填入你本机的游戏安装根目录（即包含 `FUS.exe` 的文件夹）：
   ```ini
   # 示例路径，请替换为你本机包含 FUS.exe 的实际安装目录
   FUVTT_INSTALL_DIR=D:/SteamLibrary/steamapps/common/fuvtt
   ```
2. 在终端运行 `sync` 命令（若源码有改动会自动重新打包，并将插件安全解压至 `<FUVTT_INSTALL_DIR>/FUS_Data/session_plugins/`、自动更新 `registry.json` 校验表）：
   ```powershell
   python shared/tools/fuvtt_cli.py sync demo-mod --allow-same-version
   ```
3. 启动游戏客户端即可生效；如果同步时游戏已经打开，只需在**会话管理页 -> 插件面板**点击 **刷新** 即可重新加载。

> **重要防踩坑提示**：请始终在仓库 `mods/<mod-name>/` 下修改代码并通过 `serve` 或 `sync` 更新，**切勿直接用编辑器修改游戏目录 `FUS_Data/session_plugins/packages/` 里已解压的文件**，否则客户端会检测到哈希不匹配（报错 `plugin_files_changed`）并自动禁用该插件。

### 第三步：在游戏中使用该 Mod 导入外部文件

1. 确认插件在客户端**插件面板**中处于**已启用**状态（若插件提供了代理地址 `proxy` 或隐藏图层开关等配置项，可在面板内按需调整）。
2. 回到客户端**会话管理页**，此时界面上会出现该插件注册的导入按钮（如“导入示例场景文件”）：
   * 点击该导入按钮选择对应后缀的源文件，**或者直接将源文件用鼠标拖入会话管理页窗口**。
3. 客户端会先调用插件预检并弹出**导入确认页**（展示地图、墙体、角色棋子数量及待下载网络图片大小），点击确认后即自动转换并保存为 `.world` 世界存档。
4. **多人联机说明**：转换生成的 `.world` 是纯数据标准存档。作为房主（DM/GM）导入生成世界后，**进房游玩的普通玩家不需要安装该导入插件**即可直接联机。

### 如何把做好的 Mod 发布给其他玩家使用？

客户端目前通过 `http://` 或 `https://` 直链安装插件包：只需将构建生成的单个文件 `build/<mod-name>/<mod-name>.zip` 上传至 GitHub Releases、对象存储（OSS / S3 / R2）或任意支持直链下载的静态站点，把 `.zip` 下载链接发给玩家，玩家在游戏**插件面板**粘贴链接点击 **安装** 即可。

## 2. 从零开发一个新 Mod 的基本流程

1. **生成标准脚手架**：在仓库根目录运行 `init`，工具会自动创建合规目录并把 `kebab-case` 目录名转为 `snake_case` 插件 ID：
   ```powershell
   python shared/tools/fuvtt_cli.py init my-map-importer --name "我的地图导入器" --ext mymap --action-label "导入 .mymap 地图"
   ```
2. **编写清单与导入逻辑**：打开生成的 `mods/my-map-importer/`，核心只需关注两个文件（统一使用 **UTF-8 无 BOM** 编码保存）：
   * `plugin.json`：声明插件基础信息、支持的文件扩展名数组 `import_extensions`（不含点号）以及暴露给用户的 `settings` 配置开关（支持 `"bool"` 复选框与 `"string"` 输入框）。
   * `entry.gd`：调用已预置加载好的 `fu_sdk` 接口，实现 `inspect_import(path, options, host)`（导入前快速统计）与 `prepare_import(path, options, host)`（调用 `WorldBuilder` 添加场景、楼层、底图、墙门、角色棋子与光源）。
3. **本地校验与打包**：
   
   ```powershell
   python shared/tools/fuvtt_cli.py validate my-map-importer
   python shared/tools/fuvtt_cli.py build my-map-importer
   ```
4. 按上方第 1 节的 `serve` 或 `sync` 方式装入游戏实测即可。若该插件需要独立做版本控制，可直接在 `mods/my-map-importer/` 目录内执行 `git init` 关联你自己的独立插件仓库（外层工作区会自动忽略 `mods/` 下的非模板子目录）。

## 3. 仓库目录结构说明

```text
fuvtt-forge/
├── mods/                            # 独立 Mod 源码根目录（除 _template 外均被主仓 .gitignore 忽略，支持各插件独立建仓）
│   ├── _template/                   # 随主仓版本控制的标准插件脚手架模板（供 init 命令生成新插件使用）
│   └── <your-mod>/                  # 通过 init 新建或从其他独立仓库克隆放入的业务插件目录（不随本主仓提交）
├── shared/                          # 跨插件共享基础设施
│   ├── sdk/
│   │   └── fu_sdk/                  # 核心 SDK（v1.gd 门面、宿主适配器与 4 个扩展子模块，build 时自动打入插件包）
│   ├── tools/
│   │   ├── fuvtt_cli.py             # 命令行工具统一入口（零外部依赖 Python 3 实现）
│   │   ├── fuvtt_devtools/          # 脚手架、静态校验、打包、HTTP 热更服务、离线同步与无头测试模块
│   │   └── tests/                   # 工具链与 SDK 自动化单元测试套件
│   └── docs/                        # 宿主底层协议与客户端版本演进实测笔记
├── build/                           # 打包生成的 .zip 产物、哈希清单与测试日志输出目录（Git 忽略）
├── .cache/                          # 注册表自动备份与本地缓存目录（Git 忽略）
├── .env.example                     # 本地环境变量模板（复制为 .env.local 后使用）
└── README.md                        # 仓库快速上手说明（本文档）
```

## 4. CLI 常用命令速查表

| 命令示例 | 功能说明 |
| :--- | :--- |
| `python shared/tools/fuvtt_cli.py init <mod-name> --name "名称" --ext <后缀>` | 从 `_template` 模板创建新插件目录并自动生成合规 `plugin.json` 与 `entry.gd` |
| `python shared/tools/fuvtt_cli.py validate <mod-name>`（或 `--all`） | 执行与游戏客户端一致的编码、JSON 字段、路径安全与配额静态检查 |
| `python shared/tools/fuvtt_cli.py build <mod-name>` | 校验源码、自动内嵌 `fu_sdk` 并打包输出 `build/<mod-name>/<mod-name>.zip` |
| `python shared/tools/fuvtt_cli.py build <mod-name> --bump-dev` | 自动递增 `plugin.json` 补丁版本号并重新打包，配合 `serve` 免重启更新 |
| `python shared/tools/fuvtt_cli.py serve --port 8765` | 启动本地 HTTP 插件源，输出可粘贴进客户端插件面板安装的直链 |
| `python shared/tools/fuvtt_cli.py sync <mod-name> --allow-same-version` | 将插件离线原子部署至 `.env.local` 配置的游戏目录并更新注册表 |
| `python shared/tools/fuvtt_cli.py verify-host <mod-name> --sample <测试文件>` | （可选，需配置 `GODOT_BIN`）使用无头引擎编译全部脚本并验证导入序列化往返 |
| `python shared/tools/fuvtt_cli.py inspect-client --extract` | （可选）Steam 客户端更新后提取并检查宿主插件协议是否发生变更 |

## 5. 开发者文档与 SDK Wiki 导览

详细的零 Godot 基础入门教程、`plugin.json` 字段表与 `fu_sdk v1.3.0` 全量 API 参数/返回值参考已按模块拆分发布至 [fuvtt-forge Wiki](https://github.com/Penguin134/fuvtt-forge/wiki)，建议按以下顺序查阅：

1. **[首页：概念映射与 API 速查](https://github.com/Penguin134/fuvtt-forge/wiki)**（`Home.md`）— 了解插件能力边界、世界“场景 -> 楼层 -> 图层 -> 实体”空间模型、数据类型与通用编程语言对照表，以及“想实现什么功能该调哪个 API”的全局索引表。
2. **[快速上手：构建并导入完整 Demo](https://github.com/Penguin134/fuvtt-forge/wiki/Quickstart-and-Demo)**（`Quickstart-and-Demo.md`）— 跟着一个完整的 `.roomjson` 房间导入器实例（含输入 JSON 字段定义表与逐段注释代码）从零跑通开发闭环。
3. **[清单规范与生命周期](https://github.com/Penguin134/fuvtt-forge/wiki/Manifest-and-Lifecycle)**（`Manifest-and-Lifecycle.md`）— 查阅 `plugin.json` 全部 11 个顶层字段与 `settings` 控件规则、SDK 动态导入模板及 `entry.gd` 两阶段钩子契约。
4. **[核心 API（一）：FuSdk 与 ImportSession](https://github.com/Penguin134/fuvtt-forge/wiki/API-Facade-and-Session)**（`API-Facade-and-Session.md`）— 查阅顶层工厂、脏数据类型安全清洗、用户设置读取、远端图片下载归档及预检字典构造器。
5. **[核心 API（二）：WorldBuilder 世界构建](https://github.com/Penguin134/fuvtt-forge/wiki/API-WorldBuilder)**（`API-WorldBuilder.md`）— 查阅多场景、多楼层、权限图层、底图、棋子、多边形/线段墙门、迷雾视野光源、Scene Box 传送盒及模块数据持久化的完整参数与返回值。
6. **[扩展子模块 API](https://github.com/Penguin134/fuvtt-forge/wiki/API-Extension-Modules)**（`API-Extension-Modules.md`）— 查阅 `.zip`/目录统一读取器 `PackageSource`、本地贴图预检转码发布器 `AssetPublisher`、全局角色素材库写入器 `EntityLibraryWriter` 与 `SnappyCodec`。
7. **[CLI 工具全解、玩家安装与排错指南](https://github.com/Penguin134/fuvtt-forge/wiki/CLI-and-Troubleshooting)**（`CLI-and-Troubleshooting.md`）— 查阅 `.env.local` 配置项、7 大 CLI 子命令细节与常见报错代码排查方法。
