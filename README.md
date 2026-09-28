# AE2Claude

让 AI 通过 MCP、命令行或 Python 操控 After Effects：读取工程、编辑图层与关键帧、运行 JSX、预览画面。

**当前版本：AE2Claude 4.5.0**。
[下载 Windows x64 完整发布包](https://github.com/backtime1993/AE2Claude/releases/tag/v4.5.0)。
当前实机验收基线：Windows x64 · After Effects Beta 27.0 · Python 3.12。

## 主要能力

- **工程与动画**：稳定 ID 寻址、属性批处理、原生批量关键帧和变换采样。
- **画面检查**：单帧预览、时间线拼图、修改前后像素差分。
- **自动化**：JSX 脚本库、后台任务、检查点、结构化错误与急停。
- **客户端**：Codex、Claude Code 和其他 MCP 客户端；也可直接使用 CLI / Python。

## 安装与连接

1. 获取仓库，在仓库目录运行 `uv sync --locked`。
2. 完整 Windows 发布包已含 `build/Release/AE2Claude.aex`；源码用户按 [构建说明](docs/BUILDING.md) 编译。单独的 Python wheel 不包含原生插件。
3. 将 Python 3.12 的 `python312.dll` 放到 AE 的 `Support Files` 目录，关闭 AE，再运行 `deploy.bat`。默认目标为 Beta；其他安装可传完整产品名。
4. 重启 AE，将 [MCP 配置模板](.mcp.json.template) 中的路径改成仓库绝对路径，添加到客户端。

Codex 可安装仓库内的[单入口插件](.codex-plugin/plugin.json)。先运行 `uv sync` 安装锁定依赖；MCP 启动使用 `uv run --no-sync`，不安装依赖、不启动 AE。原生插件仍需完成上述安装。

4.5.0 新增原生批量采样、素材/代理清单、关键帧缓动与空间切线读取、图层标志和混合模式控制，并修复同步渲染阻塞与本地接口网页来源校验。参见[原生能力与验证](docs/native-automation-4.5.md)及[社区实现对照](docs/community-review-20260926.md)。

## 常用命令

在仓库目录运行：

```powershell
uv run ae2claude status
uv run ae2claude capabilities
uv run ae2claude --help
```

连接后可以直接让 AI：

> 读取当前合成，列出图层；不要修改工程。
>
> 在 0、0.5、1 秒抽帧，生成时间线拼图。

普通写入默认自动执行，破坏性操作要求确认；仅查看时可在 MCP 配置中设置 `AE2CLAUDE_APPROVAL_MODE=readonly`。超时或急停不会强制终止已经进入 AE 的操作，重试前应先回读结果。

## 文档

| 内容 | 入口 |
| --- | --- |
| 版本变化、升级与限制 | [CHANGELOG](CHANGELOG.md) |
| CLI / Python / Puppet 使用参考 | [使用参考](docs/USAGE.md) |
| 原生批量关键帧与采样 | [原生自动化](docs/NATIVE_AUTOMATION.md) |
| 拼图、差分与 JSX 脚本库 | [多帧预览与脚本库](docs/FRAME_REVIEW_AND_LIBRARY.md) |
| 构建、安装与回退 | [构建说明](docs/BUILDING.md) |
| 测试及发布前验收 | [测试](docs/TESTING.md) · [发布清单](docs/RELEASE_CHECKLIST.md) |

## 致谢与许可

原生核心基于 [PyShiftAE](https://github.com/Trentonom0r3/PyShiftAE)，采用 [AGPL-3.0](LICENSE)。其他设计参考与依赖说明见 [第三方声明](THIRD_PARTY_NOTICES.md)。
