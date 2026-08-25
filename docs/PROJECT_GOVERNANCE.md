# AE2Claude 工程治理规范

## 唯一工程入口

- 主仓库：`F:\claude\longterm\AE2Claude`
- PinClicker：`extensions\pin-clicker`，与主仓库同版本、同 PR、同测试流程
- 本地 Adobe SDK：`vendor\after-effects-sdk`，只在本机保存，不提交 Git
- 通用构建依赖：`F:\claude\deps\vcpkg-repo` 与 `F:\claude\deps\pybind11`
- 构建产物：`build\Release\AE2Claude.aex`
- 测试报告：`artifacts\stress`
- 自动同步状态与部署备份：`state`

仓库根目录的 `Headers`、`Resources`、`Util` 只是指向本仓库 `vendor` 的本地联接，不能再指向旧 AE26 工程。初始化或修复联接统一运行：

```powershell
pwsh -File tools\bootstrap.ps1
```

## Git 与 PR

1. 功能开发从 `master` 建分支，不直接在 `master` 上试验。
2. PR 至少通过 Python 单元测试、PinClicker JavaScript 语法检查和 Windows Release 原生构建。
3. 有安全告警时先确认直接/传递依赖和可复现路径，再决定是否阻断。
4. PR 合并后只允许 `master` 快进同步；本地与远端分叉时停止自动流程，转人工审核。
5. `vendor`、虚拟环境、依赖目录、构建中间件、日志和压力报告不进入 Git。

## 上游与下游同步

`tools\auto-sync.ps1` 负责完整链路：

1. 要求 `master` 且工作树干净。
2. 拉取 `origin/master`，只做 fast-forward。
3. 有新提交时重装锁定依赖、跑单元测试、检查 PinClicker、重建 AEX。
4. 对 AE 2023/2024/2025/Beta 中已存在插件或 Python 运行时的受管实例执行哈希同步。
5. AE 正在运行时不覆盖对应插件，只记录 `pending-restart`，关闭 AE 后再次执行即可。

只检查、不写入：

```powershell
pwsh -File tools\sync-installation.ps1 -Mode Verify -AllSupported
```

应用并逐文件回读哈希：

```powershell
pwsh -File tools\sync-installation.ps1 -Mode Apply -AllSupported
```

同步脚本不会删除 AE 安装目录里不属于当前清单的文件；被替换的旧文件先进入 `state\backups`。

## 清理边界

`tools\clean.ps1` 只处理脚本内列出的缓存、日志、打包目录和编译中间件。默认仅报告；传入 `-Apply` 才删除。它明确保护 `.venv`、Release AEX、PinClicker `node_modules` 和本地 Adobe SDK。

旧仓库、旧实验工程和未提交补丁必须先做 Git bundle、binary patch 与 SHA-256 清单，再移入 `F:\claude\ae workspace` 的任务归档，不直接永久删除。
