# AE2Claude Skill 能力系统

## 从 AE AI Assistant 学到的机制

2026-10-12 核查了 Adobe 官方更新、帮助文档及本机助手的 README、模板、
preflight/spellcheck 文件。正式版发布说明当前列 26.5（2026 年 9 月）；
用户 Skill 公告发表于 10 月 9 日，要求 Beta 27.1 x8 起。本机可执行文件的
四段文件版本是 27.0.0.63；Skills 文件存在不等于该构建已经完整加载了新功能。

- [正式版更新](https://helpx.adobe.com/after-effects/desktop/what-s-new/whats-new.html)
- [AI Assistant 最新公告及讨论](https://community.adobe.com/announcements-532/new-in-after-effects-beta-after-effects-ai-assistant-1635658)
- [助手的权限和撤销](https://helpx.adobe.com/after-effects/desktop/work-with-after-effects-ai-assistant/use-after-effects-ai-assistant.html)
- [UXP 私测公告](https://forums.creativeclouddeveloper.com/t/after-effects-is-adding-uxp-plugin-support-private-beta-now-open/12273)

官方 Skill 是任务指导文件：目录名、frontmatter 的 name 和斜杠命令一致；
公开模板列 name/description，自定义偏好覆盖默认行为，规则仅对这项任务生效。
preflight 强调全工程证据、区分明确问题和可能有意的状态、修改后重新检查。
官方权限设置可逐动作询问或自动批准，Undo 仍逐动作撤销。

本机只读代码检查还看到：助手面板通过 UXP 的宿主接口访问内部 MCP；
Skill 列表使用 resources/list、resources/read 和 `skill://ae/` 资源，携带
验证错误；Skills 窗口会刷新缓存。本机 AE 分支的 checkpoint/rollback 适配
返回不可用，不能据此承诺完整请求回滚。以上是本机构建实现细节，不是公开稳定 API。

官方尚未公开承诺用户可接入第三方 AE MCP，UXP 私测也不等于该入口。
本次借鉴任务层设计，不连接 Adobe 内部私有服务、不改 Adobe 安装文件。
`read_only`、`allowed_tools`、版本和哈希是 AE2Claude 自己的运行时扩展；
不宣称 Adobe 会识别或强制执行这些字段。

## 发现与覆盖

优先级从高到低：

1. `<project>/skills/<name>/SKILL.md`
2. `<project>/.ae2claude/skills/<name>/SKILL.md`
3. `<user-dir>/<name>/SKILL.md`，缺省 `~/.ae2claude/skills`
4. Python 包内 `ae2claude_mcp/builtin_skills`

项目根目录取显式 `project_dir`，否则 `AE2CLAUDE_PROJECT_ROOT`，否则当前目录。
用户目录可用 `user_dir` 或 `AE2CLAUDE_USER_SKILLS_DIR` 指定。没有隐式遍历
父目录，也不根据 AE 打开的文件自动载入陌生项目的技能。无 AE 时仍可发现。

高优先级同名技能覆盖低优先级；坏的覆盖文件会报告错误，绝不静默降级。
目录逃逸被拒绝。单文件上限 128 KiB，frontmatter 上限 256 行。使用 YAML
SafeLoader，拒绝重复字段、拼错/不支持的字段及权限字段的错误类型。

只读发现加载元数据后校验工具存在性，返回元数据、内容哈希和错误；正文只在
调用时交给 Agent。旧 Codex 插件的 `skills/ae-workbench` 也会被列出，但没有
运行时工具白名单的文件缺省不可执行桥接操作。

## 元数据与团队示例

将以下文件放到 `skills/team-review/SKILL.md`，提交进团队项目仓库：

```markdown
---
name: team-review
description: Review the current PV composition before handoff.
version: "1.0.0"
requires: [comp_info]
allowed_tools: [project_info, comp_info, get_selected_layers, get_preflight_snapshot]
read_only: true
---

Inspect the current PV. Preserve the project. Use the team's 30 fps delivery
standard, report missing dependencies and partial work areas, and distinguish
definite errors from intentional exceptions. Include IDs and incomplete coverage.
```

`version` 是非空字符串，缺省 `1.0.0`；`requires` 是必需的**桥接方法名**，
必须在 `allowed_tools` 中。两项缺省都是空列表，不支持通配符、任意脚本路径或
嵌套 Skill 调用。`read_only` 缺省 true；只读技能不能声明修改型工具。
需要写入的 Skill 必须显式 `read_only: false` 并列出具体方法。

## 调用协议

```powershell
uv run ae2claude skills --project-dir F:\work\我的项目
uv run ae2claude skill "/team-review 检查交付" --project-dir F:\work\我的项目
uv run ae2claude skill /team-review --offline --project-dir F:\work\我的项目
```

MCP 用 `ae_skills` 发现、`ae_skill(command="/team-review ...")` 准备。
也可调用 MCP prompt `ae_skill_task`。准备包包含正文、版本/哈希、用户请求、
工程/活动合成/选中层上下文及允许的方法 JSON schemas。上下文来自固定的最小
只读查询；未连接或读取失败时明确 `context.captured=false`。不存在内置 LLM
对话循环，包由 Codex、Claude 等外部 Agent 消费。

Agent 每一步通过 `ae_skill_execute` 提交 operations；传 preparation 返回的
`expected_sha256`、`project_dir` 和 `user_dir`。结构与原 `ae_batch` 一样，支持
`$0.field` 结果引用、dry_run、fail_fast。CLI 对应：

```powershell
uv run ae2claude skill /team-review --execute operations.json --expected-sha256 <准备包的哈希> --project-dir F:\work\我的项目
```

执行端先重新读取文件、比较哈希、校验**整个计划**的工具白名单及只读约束，
再进入原批处理执行。文件或覆盖来源改变时重新准备。执行型 Skill 即使全局
为 auto/bypass，写入仍要求 `confirm=true` / `--confirm`；全局 readonly 和
急停继续有效，不会被技能覆盖。通用批处理仍按每个操作撤销，不是事务回滚。

这是 **Skill 执行入口的权限约束**，不是隔离一个拥有其他工具的外部 Agent。
旧 `ae_call`、`ae_batch`、JSX API 保持兼容，Agent 若绕去旧入口就离开该约束；
可信客户端必须将 Skill 任务路由到专用执行入口。不能把仅在 prompt 中写
“请勿修改”当作强制权限。

## 两个内置报告

```powershell
uv run ae2claude skill /pv-preflight --run
uv run ae2claude skill /pv-preflight --run --options '{"allowed_fps":[25,30,60],"expected_working_space":"sRGB IEC61966-2.1"}'
uv run ae2claude skill /motion-review --run --options '{"comp_id":123,"max_properties":128,"max_keys":1000}'
```

MCP 等价 `ae_skill_run(command="/pv-preflight", options={...})`。
同名项目/用户覆盖技能走 Agent 准备协议，不能借名字触发内置代码。

PV preflight 检查：所有已扫描合成的帧率、时长、画幅/像素比记录、默认/重复
名称、空合成、solo 图层、工作区；缺失素材/代理、无引用素材、替代字体；
各合成**当前时间**的已启用表达式；Render Queue 输出路径/父目录；工程保存
状态及项目色彩工作空间。缺省接受常见帧率，明确交付标准时传 `allowed_fps`。

Motion review：自动发现一个合成的动画属性，复用 `get_native_keyframes`
读取 interpolation、temporalEase、spatialTangents；识别混合插值、线性/Bezier
端点不一致、无效缓动、速度/影响不对称、一帧内密集键和空间切线转角。
烘焙动画、转角及不对称缓动仅作提示，不自动“修顺”。

报告包含 errors/warnings/info、稳定 ID/路径、coverage、limitations；
status 为 pass/issues/incomplete，工具成功不等于工程合格。默认 max_items=2000、
max_expression_properties=5000；motion max_properties=128、max_nodes=5000、
max_keys=1000。截断或缺失 API 时不能给出完整通过。无需更新 AEX。

## 已知限制

- 表达式不是全时间轴验证；文本字体的全工程覆盖依赖宿主 usedFonts API。
- 色彩只查工程工作空间，未自动查素材解释/输出色彩配置、ACES/OCIO 全链路。
- 暂未做音频预期、占位文案、逐源素材帧率及可见动画的视觉验收。
- Motion 仅一个合成、原生数值流；形状路径/文本流可能不支持，不走失败后的
  JSX 重放，也不修改现有 Graph Editor 或批量关键帧 API。
- 最大一次 Skill batch 256 个操作。整次请求没有单一 Undo/原子回滚。
- CLI 用 `skill /name`；直接在外部聊天框输入 `/name` 是否被路由由客户端决定。

## 测试

```powershell
uv sync --locked
uv run python -m unittest discover -s tests -v
uv build --no-sources
```

`tests/test_skills.py` 覆盖优先级、坏覆盖、YAML 权限陷阱、哈希变更、拒绝后零
派发、全局策略、只读报告和关键帧范围。现有 MCP stdio 和 wheel 安装检查扩展
验证 Skill 入口与打包的 Markdown；实时宿主检查另记录，不与 mock 混称。
