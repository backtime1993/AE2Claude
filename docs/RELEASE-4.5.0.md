# AE2Claude v4.5.0

Windows x64 完整发布，2026-10-08。包含原生批量采样、素材/代理清单、关键帧缓动及空间切线读取、图层控制、异步渲染，以及 9 月 29 日完成的 AE 回归与长时间轴修复。

## 下载

- `AE2Claude-4.5.0-windows-x64.zip`：含原生 AEX、完整配套源码、MCP/CLI、脚本、预设、PinClicker 扩展源码和部署工具。
- `ae2claude-4.5.0-py3-none-any.whl` 与 `ae2claude-4.5.0.tar.gz`：Python 客户端，不含 AEX。
- `VALIDATION-4.5.0.json`、`SHA256SUMS-4.5.0.txt` 和验证日志归档：版本、源码/产物对应关系、检查结果及下载校验。

## 升级

1. 备份旧完整包并保存工程，关闭 AE。
2. 将完整 zip 解压到独立目录，在该目录运行 `uv sync --locked`。准备 Python 3.12，并将其 `python312.dll` 放在目标 AE 的 `Support Files` 中。
3. 在管理员 PowerShell 7 中运行 `deploy.bat`（Beta），或 `deploy.bat "Adobe After Effects 2025"`。
4. 按 `.mcp.json.template` 配置仓库绝对路径，使用 **18889** 端口。v4.4.0 的旧端口为 8089，须同步更新客户端与服务文件。
5. 重启 AE 和 MCP 客户端，运行 `uv run ae2claude status`；核对加载 AEX 哈希与原生能力。PinClicker CEP 仍使用 **8891**，可选扩展按其 README 安装。

完整 zip 不是包含 AE、Python 或 Adobe SDK 的离线安装器。仅安装 wheel 不会更新原生插件。

## 验证与限制

本次 CI 验证 215 项 Python 测试：156 通过，59 项 AE 真机测试跳过；另覆盖 GCC/MSVC SDK 独立原生测试、PinClicker 语法检查及安装后的 Python 包和 MCP 工具发现。

原生 AEX 复用 2026-09-29 在 AE 2025 25.6.4x3 / Beta 27.0x58 验收的相同二进制；该次两版各 214 项测试通过。发布原生源码树未变，二进制 SHA-256 为 `aa5e9bbb8c5968faf3b84f7b87394c8f28568c790a1fbef4accd5f5dc3b584e8`。本次确认运行中的 Beta 加载该哈希，不把历史结果当作今天重新执行的实机测试。

未重新执行全新系统安装、完整宿主写入测试或升级/回退流程；未验证其他 AE 版本、macOS 或所有第三方插件组合。同步器支持某个安装目录名不等于已验证该 AE 版本。

旧版 v4.4.0 Release 保留用于回退；关闭 AE 后恢复整套匹配文件和 8089 配置，重新核对哈希，避免新旧文件混用。
