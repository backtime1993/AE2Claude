# AE2Claude Agent 架构

AE2Claude 4.3 的目标不是继续增加孤立命令，而是让 Agent 能发现、组合、批量执行和追踪 AE 能力，同时保留旧版 `AEBridge` 方法。

## 分层

```text
Agent / CLI / MCP client
        |
        v
Capability schema + safety + batch/task/event runtime
        |
        v
AEBridge (stable IDs, matchName paths, legacy methods)
        |
        +--> AEGP single-dispatch property engine
        |      one queued main-thread task per batch
        |
        +--> JSX single-dispatch fallback
               TextDocument, Shape and other scriptable values
```

AE 的 SDK 调用必须在主线程完成。旧属性函数会把“找根节点、逐段寻址、读取类型、读写值、释放句柄”拆成多条队列消息，既慢又可能在空闲钩子与工作线程之间卡住。`psc.agent_stream_batch` 和 `psc.agent_inspect_streams` 把完整操作封装成一条消息；进入主线程后直接调用 AEGP suites，完成后一次返回。

## Agent 地址模型

- 合成和图层优先使用 AE 的稳定 `id`，不依赖可能重复的名称或会变化的索引。
- 属性使用 locale-independent `matchName` 路径。
- Indexed Group 使用从 `0` 开始的整数路径项，因此同一种效果的多个实例也可准确寻址。
- `ae_inspect_properties` 返回可直接传给 `ae_get_property`、`ae_set_property` 或 `ae_property_batch` 的路径。

示例：

```json
{
  "layer": {"id": 42},
  "operations": [
    {"action": "get", "path": ["ADBE Transform Group", "ADBE Position"]},
    {"action": "set", "path": ["ADBE Transform Group", "ADBE Opacity"], "value": 70}
  ]
}
```

## 两类批处理

`ae_property_batch` 面向性能敏感的参数操作：最多 256 个读写、一次 AE 主线程调度、一次 undo group、执行前全路径预检，并支持 `dry_run`。

`ae_batch` 面向跨能力工作流：每项调用一个公开 `AEBridge` 方法，后续参数可用 `$0`、`$0.field` 或 `$0.items[1]` 引用前序结果。它保持兼容性，但只有 `ae_property_batch` 保证底层单次调度和单次撤销。通用批次的写操作遵循各底层方法自己的撤销边界；Adobe 明确说明单个脚本结束时会自动关闭 undo group，因此不能跨多个桥接请求虚假承诺一个撤销组。

## 后台任务与事件

- `ae_submit` 返回 MCP Tasks 风格的 `taskId`、状态、时间、TTL 和建议轮询间隔。
- `ae_task` / `ae_tasks` 获取状态和结果；`ae_cancel` 进行协作式取消。
- AE 正在执行的一条 JSX/AEGP 调用不能安全抢占；取消会在排队阶段或两个操作之间生效，不会假装已经中断主线程。
- `ae_events` 使用递增 cursor 获取 task/batch/operation 事件，支持最长 30 秒 long-poll，Agent 不必反复全量读取工程。
- 当前任务在 MCP server 会话内持久；MCP Tasks 标准仍属实验性，待 Python MCP SDK 稳定暴露原生 task capability 后可无损迁移协议层。

## CLI

安装项目后使用统一入口：

```powershell
uv run ae2claude status
uv run ae2claude capabilities property
uv run ae2claude inspect --layer id:42 --depth 4
uv run ae2claude get --layer id:42 --path '["ADBE Transform Group","ADBE Position"]'
uv run ae2claude set --layer id:42 --path '["ADBE Transform Group","ADBE Opacity"]' --value 70
uv run ae2claude property-batch plan.json --layer id:42 --dry-run
uv run ae2claude batch workflow.json --confirm
```

所有新命令支持 `--format json|text|ndjson`，并以 `0/3/4` 区分成功、连接失败和操作失败。原仓库根目录的旧 CLI 继续保留兼容。

## 安全与资源边界

- 仅绑定 `127.0.0.1`，继续使用审批模式和 kill switch。
- 原始 JSX 与破坏性方法仍需确认。
- 原生队列、属性批次、后台任务、事件缓冲和 TTL 都有上限。
- 任务审计不记录原始 JSX 内容，避免把工程数据或敏感文本写入日志。

## 参考架构

- [MCP Tasks specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)：任务状态、轮询、取消、TTL 与资源边界。
- [Unreal Engine Remote Control](https://dev.epicgames.com/documentation/unreal-engine/remote-control-for-unreal-engine)：把属性和函数作为可发现的远程能力开放。
- [Unity MCP](https://github.com/mitchchristow/unity-mcp)：批处理、结果链、单次撤销和 dry-run。
- [Blender MCP](https://github.com/ahujasid/blender-mcp)：网络线程接收请求、DCC 主线程执行命令的桥接模型。

这些项目用于架构取样；AE2Claude 的实现仍以 Adobe AEGP/ExtendScript 的线程和对象生命周期约束为准。
