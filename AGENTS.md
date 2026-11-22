# Fu vtt Mod Monorepo 全局协作路由规范

本仓库为虚拟桌面跑团软件 **Fu vtt**（Steam App ID: 3177780，Playtest 内测阶段）的 Antigravity 友好型 Monorepo 工作区，用于统一管理多个独立插件与规则模块。本文件仅作为全局路由总线，禁止写入具体底层 API 细节、解包数据结构或长篇代码示例。

## 1. 工作区目录路由表

- `.agents/rules/`：预留全局协作规则目录（当前保持空置，避免无关规则注入默认上下文）。
- `.agents/workflows/`：预留常用自动化工作流目录。
- `mods/_template/`：标准插件脚手架模板，新建插件从此目录复制。
- `mods/<mod-name>/`：独立插件包目录（包含专属 `AGENTS.md`、`src/`、`assets/` 与清单文件）。
- `shared/docs/`：共享底层技术知识库（纯按需懒加载，禁止默认预加载）。
- `shared/sdk/`：跨插件复用的已验证公共类型声明与纯工具函数目录。
- `shared/tools/`：本地构建、打包、真机无头验证与客户端巡检脚本目录（读取 `.env.local` 配置）。
- `build/`：所有插件的统一构建输出、解包与无头验证证据根目录（按 `build/<mod-name>/` 隔离，已加入 `.gitignore`）。
- `.cache/`：包管理器与构建工具临时缓存根目录（已加入 `.gitignore`）。

## 2. 分层上下文与按需懒加载协议（Lazy-Loading）

1. **根路由优先，严格精简**：本文件仅负责目录路由、沙箱边界与通用规范，保持在 150 行以内。
2. **插件局部上下文**：开发或修改具体插件时，优先读取目标插件的 `mods/<mod-name>/AGENTS.md`，获取该插件的业务目标、当前进度、独立构建命令与所需文档索引。
3. **共享文档按需显式读取**：仅在任务涉及对应领域时，按需打开 `shared/docs/` 下对应文档，禁止全量预加载：
   - `shared/docs/plugin-lifecycle.md` — 插件入口、配置清单与加载生命周期
   - `shared/docs/desktop-and-scene-api.md` — 2D/3D 场景地图、战争迷雾、多层高度与角色权限接口
   - `shared/docs/macro-and-rules.md` — 内置宏系统钩子、障碍物烘焙与 TRPG 规则数据适配
   - `shared/docs/playtest-notes.md` — Steam Playtest 双代码线辨析、版本变动与兼容性踩坑记录
4. **零幻觉与实证原则**：Fu vtt 处于 Steam Playtest 阶段，严禁凭空编造未验证的底层 API、Manifest 字段或钩子签名，严禁将 Fu vtt 与 Foundry VTT 等其他 VTT 平台接口混用；所有接口必须先依据本地 Playtest 客户端或只读官方源码核实后，再沉淀至 `shared/docs/`。

## 3. 沙箱边界与环境隔离约束

- **产物与缓存收敛**：所有编译输出、解包与无头测试隔离目录统一写入工作区内 `build/<mod-name>/`，所有缓存与契约快照统一指向 `.cache/`，严禁向工作区外用户主目录或系统全局目录写入缓存，防止触发沙箱 `Permission Denied`。
- **外部路径统一配置**：本地客户端目录（`FUVTT_INSTALL_DIR`）、只读官方源码库（`FUS_REPO_DIR` / `FUS_SOURCE_REF`）与 Godot 无头控制台（`GODOT_BIN`）仅通过未入库的 `.env.local` 配置（模板见 `.env.example`）；严禁在代码、脚本、配置或文档中硬编码本机绝对路径（文档与脱敏日志统一使用 `<FUVTT_INSTALL_DIR>`、`<FUS_REPO_DIR>`、`<GODOT_BIN>` 占位符）。
- **外部官方源码仓只读与双线防混淆铁律**：仅允许以纯只读方式（如 `git -C <FUS_REPO_DIR> show <ref>:<path>`）核对契约，**严禁对 `<FUS_REPO_DIR>` 执行任何文件写入、删除或 `git checkout`**；生产插件、SDK 与脚手架 100% 锚定现役 `Practice` 主线（`origin/codex/fuvtt-project-sync` / Steam 客户端，`fus.session-plugin.v1`），严禁将已替代的早期 `FUS-F2` 原型分支（`f2.feature_plugin.v1`）契约混用于生产交付。
- **凭证与权限边界**：严禁读取、打印或提交任何 Steam 账号信息、发布令牌或私人存档；需要访问工作区外部路径时，必须遵守沙箱边界与用户显式授权。
- **跨包依赖隔离**：`mods/<mod-a>/` 禁止直接引用 `mods/<mod-b>/src/` 内部实现；经过验证可复用的类型或工具函数，必须提炼至 `shared/sdk/` 后再跨插件复用。

## 4. 通用代码与提交规范

- **文件编码与命名**：全部文本源码、配置与文档统一使用 UTF-8 无 BOM 编码；插件目录命名统一采用 `kebab-case`（如 `dnd5e-sheet-helper`）。
- **提交信息前缀**：采用约定式提交前缀：`feat(<mod>):`、`fix(<mod>):`、`docs(shared):`、`chore(tools):`、`refactor(<scope>):`。
- **文档同步要求**：每当从 Playtest 客户端或官方源码核实新接口、字段或兼容问题并更新 `shared/docs/` 时，须同步记录对应客户端版本号、Commit 哈希与验证日期。
