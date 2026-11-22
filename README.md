# Fu vtt (Steam Playtest) Mod Monorepo

用于开发与维护 Steam 平台虚拟桌面跑团软件 **Fu vtt**（Steam App ID: `3177780`，模块化 2D/3D TRPG 平台）的独立插件、规则扩展模块与共享工程基础设施。

> [!WARNING]
> **Playtest 内测阶段说明**  
> **当前处于 Steam Playtest 内测阶段，后续 Mod 接口可能发生变更。**  
> 当前仓库工具链、防腐层 SDK 与共享技术知识库 100% 锚定官方现役 **`Practice` 主线**（源码基准 `v0.0.56` / Git `282aee64`，本机 Steam 客户端实测基准 **`v0.0.57`** / Commit `3f20e8e`，验证日期 `2026-11-20`，`Godot Engine v4.8.beta1.mono` + `.NET 10`）。  
> 早期非 Mono 原型分支（`FUS-F2` / `f2.feature_plugin.v1`）与现役 Steam 客户端不兼容，仅作为文档层的前瞻设计参考，不生成生产脚手架。

## 核心架构原则

1. **Monorepo 隔离与防腐层 SDK（`fu_sdk`）**：
   - 各业务插件独立存放在 `mods/<mod-name>/`，插件间禁止跨包私自引用内部源码。
   - **构建期自动内嵌防腐层**：由于现役 Playtest 客户端尚未实装 Steam 创意工坊（`ISteamUGC`）与跨插件前置依赖机制，所有插件统一调用 `shared/sdk/fu_sdk/v1.gd` 稳定语义接口（`ImportSession` 与 `WorldBuilder`），由构建器在打包期自动注入每个插件 ZIP 的 `lib/fu_sdk/` 目录。当客户端升级底层结构时，仅需单点更新 `shared/sdk/fu_sdk/adapters/` 并执行 `build --all`，下游业务插件源码无需修改。
2. **分层 `AGENTS.md` + 按需懒加载**：
   - 根目录 [AGENTS.md](AGENTS.md)（< 150 行）仅作全局路由与沙箱约束，不堆砌底层 API 细节。
   - 共享知识库 `shared/docs/` 按领域拆分沉淀源码级实证规范，仅在对应任务需要时按需读取。
   - 插件目录 `mods/<mod-name>/AGENTS.md` 记录单插件业务目标、进度、独立构建命令与所需文档索引。
3. **沙箱边界与环境隔离**：
   - 所有打包输出、解包产物与无头验证证据统一收敛在工作区内 `build/`，临时缓存与契约基线快照统一收敛在工作区内 `.cache/`。
   - 外部路径仅通过 `.env.local` 注入（`FUVTT_INSTALL_DIR`、可选 `FUS_REPO_DIR` / `FUS_SOURCE_REF` / `GODOT_BIN`），严禁在受控文件中硬编码本机路径、提交凭证或修改外部只读源码库。

## 目录结构

```text
.
├── .agents/                         # Antigravity 全局协作规则与工作流预留目录
│   ├── rules/
│   └── workflows/
├── mods/                            # 独立插件包目录（kebab-case 命名）
│   └── _template/                   # 标准会话插件脚手架模板（fus.session-plugin.v1）
│       ├── AGENTS.md                # 单插件局部协作上下文模板
│       ├── plugin.json              # 插件清单模板
│       ├── entry.gd                 # 基于 fu_sdk 防腐层的入口脚本模板
│       ├── src/                     # 业务子脚本目录
│       └── assets/                  # 插件静态资源目录
├── shared/                          # 跨插件共享基础设施层
│   ├── docs/                        # 按需懒加载的底层实证技术知识库
│   │   ├── plugin-lifecycle.md      # 插件清单、C# 强校验、按需加载生命周期与热更新规范
│   │   ├── desktop-and-scene-api.md # 2D/3D 场景世界结构、多楼层图层、18 个 ECS 组件与权限规范
│   │   ├── macro-and-rules.md       # 障碍物自动烘焙、内置规则模块现状与前瞻规则架构参考
│   │   └── playtest-notes.md        # 双代码线辨析、v0.0.53→v0.0.57 演进、PCK 解包与巡检规范
│   ├── sdk/                         # 跨插件共享防腐层 SDK
│   │   └── fu_sdk/                  # v1 稳定门面 API 与宿主版本适配器（打包自动内嵌至 lib/fu_sdk/）
│   └── tools/                       # 零外部依赖 Python 自动化工具链
│       ├── fuvtt_cli.py             # CLI 统一命令行入口
│       ├── fuvtt_devtools/          # 脚手架、C# 等价校验、打包、同步/热更新、双源巡检与无头验证
│       └── tests/                   # 工具链自动化单元测试套件
├── build/                           # 统一构建、解包与 verify-host 证据根目录（已加入 .gitignore）
├── .cache/                          # 工作区缓存、注册表备份与客户端契约快照（已加入 .gitignore）
├── AGENTS.md                        # 全局协作路由总线
├── .env.example                     # 本地环境变量配置模板
├── .gitignore                       # Git 忽略规则
└── README.md                        # 工作区说明文档
```

## 快速开始与自动化工具链

### 1. 配置本地环境（`.env.local`）

复制 [.env.example](.env.example) 为 `.env.local`，按需填入本机路径（切勿填写任何 Steam 账号或私人凭证）：

```ini
# 必填：本地 Steam Fu vtt Playtest 安装目录
FUVTT_INSTALL_DIR=<FUVTT_INSTALL_DIR>

# 可选：只读官方源码库与现役 Practice 分支引用（供双源巡检使用，工具绝不写入或 checkout）
FUS_REPO_DIR=<FUS_REPO_DIR>
FUS_SOURCE_REF=origin/codex/fuvtt-project-sync

# 可选：Godot 4.8-beta1 Mono 控制台可执行文件（供 verify-host 真机无头验证使用）
GODOT_BIN=<GODOT_BIN>
```

> 默认便携数据目录会自动解析至 `<FUVTT_INSTALL_DIR>/FUS_Data/session_plugins`。

### 2. 核心 CLI 命令速查（`shared/tools/fuvtt_cli.py`）

工具链基于纯 Python 3 标准库实现，零第三方依赖：

```powershell
# 1) 从标准模板初始化新插件（目录名使用 kebab-case，自动生成合规 snake_case 插件 ID）
python shared/tools/fuvtt_cli.py init my-map-importer --name "自定义地图导入" --ext "uvtt"

# 2) 静态契约与 C# PluginPackageJob 等价强门禁校验（UTF-8 无 BOM、必填数组、配额与路径安全）
python shared/tools/fuvtt_cli.py validate my-map-importer
python shared/tools/fuvtt_cli.py validate --all

# 3) 构建确定性 ZIP 包（自动内嵌 shared/sdk/fu_sdk/ 至包内 lib/fu_sdk/，写出逐文件 file_hashes）
python shared/tools/fuvtt_cli.py build my-map-importer
python shared/tools/fuvtt_cli.py build my-map-importer --bump-dev   # 递增 patch 数字段，用于原生热更新

# 4) Godot 4.8-beta1 Mono 真机无头编译、导入回合与 var_to_bytes 往返冒烟验证（证据隔离于 build/）
python shared/tools/fuvtt_cli.py verify-host my-map-importer

# 5) 本地客户端部署（二选一，切勿直接手动修改已解压包内的文件，否则触发宿主防篡改禁用）
# 方式 A：离线原子直写 FUS_Data/session_plugins/（自动写入 file_hashes 与对齐后的 settings）
python shared/tools/fuvtt_cli.py sync my-map-importer
python shared/tools/fuvtt_cli.py sync my-map-importer --allow-same-version  # 开发态同版本覆盖重装
# 方式 B：启动本地 HTTP 热更新静态源，复制输出的 URL 至客户端插件面板安装/检查更新
python shared/tools/fuvtt_cli.py serve --host 127.0.0.1 --port 8765

# 6) Steam PCK + Git 官方源码双源金丝雀契约巡检（解包 FUS.exe、核对 Practice.dll 与源码代差）
python shared/tools/fuvtt_cli.py inspect-client --extract --source both
```
