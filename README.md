# AE2Claude

让 AI 通过 MCP、命令行或 Python 操控 After Effects：读取工程、编辑图层与关键帧、运行 JSX、预览画面。

**当前版本：AE2Claude 4.5.0**，包含原生批量能力及 9 月 29 日的回归修复。
[下载 Windows x64 完整发布包](https://github.com/backtime1993/AE2Claude/releases/tag/v4.5.0)；另提供 Python wheel、sdist、校验和与验证报告。
已有实机验收记录：Windows x64 · After Effects 2025 25.6.4x3 / Beta 27.0x58 · Python 3.12；详见下方验收文档。

## 主要能力

- **工程与动画**：稳定 ID 寻址、属性批处理、原生批量关键帧和变换采样。
- **画面检查**：单帧预览、时间线拼图、修改前后像素差分。
- **自动化**：JSX 脚本库、后台任务、检查点、结构化错误与急停。
- **可复用任务**：项目/用户 Skill 发现、`/skill-name` 任务包、工具白名单及只读 PV/关键帧报告。
- **PV 制作接口**：MOGRT / Essential Graphics、形状操作器与虚线、保留样式的局部改字、关键帧插值、工程归类及渲染输出，默认先生成方案。参见[参数与使用边界](docs/PRODUCTION.md)。
- **客户端**：Codex、Claude Code 和其他 MCP 客户端；也可直接使用 CLI / Python。

## 安装与连接

1. 获取仓库，在仓库目录运行 `uv sync --locked`。
2. 完整 Windows 发布包已含 `build/Release/AE2Claude.aex`；源码用户按 [构建说明](docs/BUILDING.md) 编译。单独的 Python wheel 不包含原生插件。
3. 将 Python 3.12 的 `python312.dll` 放到 AE 的 `Support Files` 目录，关闭 AE，再运行 `deploy.bat`。默认目标为 Beta；其他安装可传完整产品名。
4. 重启 AE，将 [MCP 配置模板](.mcp.json.template) 中的路径改成仓库绝对路径，添加到客户端。

Codex 可安装仓库内的[单入口插件](.codex-plugin/plugin.json)。先运行 `uv sync` 安装锁定依赖；MCP 启动使用 `uv run --no-sync`，不安装依赖、不启动 AE。原生插件仍需完成上述安装。

当前源码的 AE 桥默认端口为 **18889**，PinClicker 仍为 **8891**。从旧版升级时同步更新服务文件和 MCP 配置中的 `AE2CLAUDE_PORT`；旧版 v4.4.0 发布包仍使用 8089，不要混用两版配置。

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

## Skill 与 PV 检查

```powershell
uv run ae2claude skills
uv run ae2claude skill /pv-preflight --run
uv run ae2claude skill /motion-review --run
uv run ae2claude skill "/motion-review 检查标题出场" --offline
```

把团队任务放在 `<项目>/skills/<name>/SKILL.md` 或 `<项目>/.ae2claude/skills/<name>/SKILL.md`；
个人任务默认放在 `~/.ae2claude/skills`。缺省只读、空工具白名单；需要哪些工具就明确声明哪些。
MCP 客户端用 `ae_skills` → `ae_skill` → `ae_skill_execute`；两个内置检查可直接用 `ae_skill_run`。
自定义 Skill 提供给外部 Agent 执行，不会凭 Markdown 自动运行脚本或启动模型。
详情见 [Skill 协议、示例与权限边界](docs/SKILLS.md)。

## 文档

| 内容 | 入口 |
| --- | --- |
| 版本变化、升级与限制 | [CHANGELOG](CHANGELOG.md) |
| CLI / Python / Puppet 使用参考 | [使用参考](docs/USAGE.md) |
| 可复用 Skill 与只读 PV / 动画检查 | [Skill 能力系统](docs/SKILLS.md) |
| 原生批量关键帧与采样 | [原生自动化](docs/NATIVE_AUTOMATION.md) |
| 拼图、差分与 JSX 脚本库 | [多帧预览与脚本库](docs/FRAME_REVIEW_AND_LIBRARY.md) |
| 构建、安装与回退 | [构建说明](docs/BUILDING.md) |
| 跳过主页、崩溃修复提示与回退 | [启动设置](docs/STARTUP.md) |
| 9 月 29 日本机问题修复与验证 | [实机回归记录](docs/LIVE_REGRESSIONS_20260929.md) |
| Beta 第二轮批处理修复 | [199 项回归与限制](docs/BETA_BATCH_INTEGRITY_20260929.md) |
| 长时间轴、批次依赖与静态赋值修复 | [两版 AE 的 214 项回归记录](docs/BETA_TIMELINE_20260929.md) |
| Beta 激活后缩成标题栏 | [还原矩形根因与修复](docs/WINDOW_FOCUS_20260929.md) |
| 测试及发布前验收 | [测试](docs/TESTING.md) · [发布清单](docs/RELEASE_CHECKLIST.md) |

## 致谢与许可

阻塞报错排障：[`ae_capture_blocked_ui`](docs/BLOCKED_UI_CAPTURE.md) 在 AE 被模态弹窗阻塞时按需返回完整弹窗图片；正常状态不截图，无需调用 JSX 或 Computer Use 获取该类证据。

原生核心基于 [PyShiftAE](https://github.com/Trentonom0r3/PyShiftAE)，采用 [AGPL-3.0](LICENSE)。其他设计参考与依赖说明见 [第三方声明](THIRD_PARTY_NOTICES.md)。
