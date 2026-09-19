# 构建、安装与回退

当前候选版本尚未发布。CI 的 wheel / sdist 只包含 Python 客户端；它们不能
代替 `AE2Claude.aex`，也不能证明 AE 真机验收通过。

## 从源码构建原生插件

需要 Windows x64、Visual Studio 2022 C++ 工具、Python 3.12、pybind11、
vcpkg（Boost）和本地授权 Adobe AE SDK。SDK suite 要求见
[原生自动化](NATIVE_AUTOMATION.md#build-and-acceptance)；SDK 文件不进入 Git。

先按 [工程治理](PROJECT_GOVERNANCE.md) 用 `tools/bootstrap.ps1` 配置
本地 SDK 联接，再在 VS Developer Command Prompt 中设置实际依赖路径：

```bat
set PYTHON_DIR=C:\Python312
set VCPKG_INSTALLED=C:\vcpkg\installed
set PYBIND11_DIR=C:\pybind11
MSBuild src\PyShiftAE\Win\PyShiftAE.vcxproj /p:Configuration=Release /p:Platform=x64
```

唯一部署产物为 `build/Release/AE2Claude.aex`。保留构建日志、源码提交和
SHA-256；在更换版本后重新构建，不能凭磁盘上存在 AEX 就当作当前产物。

## 安装或升级

1. 保留上个版本的完整包、Python 依赖锁文件和 AEX；保存自己的工程。
2. 在新版本仓库运行 `uv sync --locked`；如使用 PinClicker，在
   `extensions/pin-clicker` 运行 `npm ci --omit=dev --no-audit --no-fund`。
3. 确保目标 AE 的 `Support Files/python312.dll` 存在，关闭目标 AE。
4. 运行 `deploy.bat`（默认 Beta）或 `deploy.bat "Adobe After Effects 2025"`。
   同步包括 AEX、server、bridge、`ae_native_protocol.py`、旧 CLI、scripts 和 presets。
5. 在重启前用以下命令逐文件核验，再启动 AE 并重启 MCP 客户端：

```powershell
pwsh -File tools/sync-installation.ps1 -Mode Verify -AllSupported
uv run ae2claude status
```

通过 MCP 调用 `ae_native_status`，核对插件路径与哈希，并检查
`features.nativeAutomation` 和 `native.automationRevision`。磁盘文件已复制
不代表运行中的 AE 已加载它。安装脚本识别旧 AE 产品名不等于已验证其兼容性。

## 回退

关闭 AE 和 MCP 客户端，切回保存的旧版本目录及其匹配 AEX，用该版本的
同步脚本恢复对应文件，然后重新安装该版本的锁定依赖并重启。
同步备份在 `state/backups`，它只保存被替换文件，不是完整工程或完整安装备份。
同步不会自动删除新增文件；检查新版本独有文件（如 `ae_native_protocol.py`），
根据旧版完整清单处理。再次核对哈希、版本和只读工程访问，勿混用新旧 server/AEX。

Python 安装包构建：`uv build --no-sources`。完整原生发布包还需配套源码、
脚本、预设、安装工具、依赖清单、第三方声明及 SHA-256，详见
[发布清单](RELEASE_CHECKLIST.md)。


### Windows installation failure safety

Run `deploy.bat` from an elevated terminal. Apply rejects a non-administrator
before any installed file changes. For each AE target, all changed files are
preflighted, staged on the target volume, hashed, and backed up before commit.
An in-process failure restores replaced files and removes only newly installed
files; `state/backups/.../transaction.json` records committed, rolled-back or
rollback-failed state. This is not crash-atomic across the entire file set: a
power loss or a rollback permission failure requires recovery from the journal
and backup before launching AE. Close AE before deployment.

PiPL preprocessing uses UTF-8 MSBuild Exec tasks and relative intermediate names;
space-containing and Chinese project paths are supported. C4700, C4715, C4302,
C4311 and C4286 diagnostics are build errors instead of ignored warnings.
