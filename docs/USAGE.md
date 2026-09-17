# 使用参考

常用入口见 [README](../README.md)。完整方法与参数以 `ae_capabilities` / `uv run ae2claude capabilities` 返回的 schema 为准。

新增能力：[原生自动化](NATIVE_AUTOMATION.md)、[多帧预览与脚本库](FRAME_REVIEW_AND_LIBRARY.md)。

MCP 暴露以下核心能力：

- `ae_ping` / `ae_status` / `ae_diagnose`：连接与故障定位
- `ae_recover_script_dialog`：后台关闭阻塞桥接的 AE 脚本错误框，并返回结构化恢复结果
- `ae_overview` / `ae_layers` / `ae_methods`：渐进读取工程状态
- `ae_effects` / `ae_describe_effect`：搜索 AE 实际安装的完整效果库并读取属性结构
- `ae_add_effect` / `ae_set_effect_property` / `ae_get_effect_property`：按稳定 `matchName` 通用操控效果
- `ae_scripts` / `ae_run_script`：模糊搜索并安全运行仓库内登记的 JSX 工具
- `ae_call`：调用全部公开 AEBridge 方法
- `ae_exec`：执行原始 ExtendScript，可在执行前自动建检查点
- `ae_preview_frame`：返回适合模型查看的真实合成帧 PNG 和结构化元数据
- `ae_checkpoint` / `ae_checkpoints` / `ae_revert`：完整 AEP 快照与恢复
- `ae_set_enabled`：立即关闭或恢复所有 MCP 驱动操作
- `ae_capabilities`：返回可搜索的方法 schema、风险和 Agent 能力协议
- `ae_inspect_properties` / `ae_get_property` / `ae_set_property`：按稳定 ID 和 `matchName` 路径开放 AE 属性树
- `ae_property_batch`：最多 256 项参数读写，一次主线程调度、一次撤销、支持试运行
- `ae_batch`：跨能力工作流，支持 `$0.field` 结果链；撤销边界遵循各底层方法
- `ae_submit` / `ae_task` / `ae_cancel` / `ae_events`：后台任务、协作式取消和增量事件流

### MCP 运行边界（2026-09-05 修复）

- `ae_ping` / `ae_status` 的 `ok` 表示已启用、AE 已连接且工程可读取；
  `serviceReady`、`bridgeReady`、`projectReadable` 分别报告各层状态。
  AE 关闭时返回 `state=offline`，不会把 MCP 服务启动成功当作工程可用。
- 批次执行前检查所有步骤的参数名称、必填参数、重复传参及引用顺序。
  引用只能指向此前步骤；结果字段、数组范围及 AE 对象是否存在仍需运行时确认。
- 急停开关在每一步执行前检查，关闭后剩余步骤不再执行，即使 `fail_fast=false`。
  已经进入 AE 的单步操作无法强制中断；返回 `stopReason=disabled` 说明停止原因。
- `ae_exec` / `ae_run_script` 同步执行最多 120 秒，为连接器默认 180 秒超时留出余量。
  超过上限的请求在脚本执行和检查点写入之前拒绝；长脚本改用 `ae_submit`：

```json
{"operations":[{"method":"run_jsx","kwargs":{"code":"/* your script */","timeout":600000}}],"confirm":true}
```

使用返回的 `taskId` 调用 `ae_task`，建议每 30 秒查询一次。
后台任务仅在当前 MCP 服务进程内保留，运行期间不要刷新连接器或停止轮询超过其空闲回收时间。
需要检查点时先单独调用 `ae_checkpoint`。超时不能证明操作未生效，先回读结果再决定是否重试。

安全模式通过 `AE2CLAUDE_APPROVAL_MODE` 控制：

| 模式 | 行为 |
|------|------|
| `readonly` | 只允许读取 |
| `manual` | 所有写入都要求 `confirm=true` |
| `auto` | 普通写入自动执行，破坏性操作仍要求确认（默认） |
| `bypass` | 不做确认门禁 |

检查点会先保存当前项目，再复制完整 AEP；回滚会先创建恢复检查点，
然后原子替换原项目文件并重新打开。未保存项目会安全跳过检查点创建。

### 基本使用

4.3 新版结构化 CLI：

```powershell
uv run ae2claude status
uv run ae2claude capabilities property
uv run ae2claude inspect --layer id:42 --depth 4
uv run ae2claude get --layer id:42 --path '["ADBE Transform Group","ADBE Position"]'
uv run ae2claude set --layer id:42 --path '["ADBE Transform Group","ADBE Opacity"]' --value 70
uv run ae2claude property-batch plan.json --layer id:42 --dry-run
uv run ae2claude batch workflow.json --confirm
```

新 CLI 支持 `--format json|text|ndjson`，原仓库根目录 CLI 继续保留兼容。完整设计见
[`AGENT_ARCHITECTURE.md`](AGENT_ARCHITECTURE.md)。

旧 CLI 快捷命令：

```bash
ae2claude                              # 检查连接状态
ae2claude layers                       # 查看当前合成里的图层
ae2claude pixel 100 200               # 精确读取单个像素
ae2claude pixels 100 200 300 400      # 精确读取多个像素点
ae2claude color 31                    # 快速判断第 31 层的大概颜色（32x32 降采样）
ae2claude colors 31 32                # 批量快速判断多层的大概颜色
ae2claude call auto_place_puppet_pins 31 --pin_count 4 --clear_existing true  # 自动按轮廓打 Puppet 点
ae2claude call list_puppet_pins 31    # 查看当前图层的 Puppet 点
ae2claude call add_text_layer "Hello"  # 创建文字图层
ae2claude call set_text_style "Hello" --font_size 72 --fill_color "[1,0,0]"
ae2claude call set_keyframes "Hello" opacity "[[0,0],[1,100]]"  # 淡入动画
ae2claude call add_effect "Hello" gaussian_blur                  # 加模糊
ae2claude call set_effect_props "Hello" 1 "{\"blurriness\": 20}" # 设模糊值
ae2claude call remove_solid_background_layers --max_layers 2     # 清理底部灰/白底色层
ae2claude snapshot                     # 截图保存当前帧
ae2claude help                         # 查看所有命令
```

### 像素读取两档

- `ae2claude pixel` / `ae2claude pixels`
  精确取点。适合确认某个坐标的真实颜色。
- `ae2claude color` / `ae2claude colors`
  快速近似取色。内部会把目标层按 `32x32` 级别降采样，再返回整层的大概颜色、透明度范围等统计。

### Puppet 自动打点

- `ae2claude call auto_place_puppet_pins <layer> --pin_count 4`
  当前会先做轮廓检测并返回建议坐标，但**不会再假装后台已成功落 pin**。
  已确认纯 JSX 路线无法写入隐藏的 `ADBE FreePin3 PosPin Vtx Index`，脚本创建的 pin 会保持未绑定状态（`-1`）。
- 当前 C++/SDK 深挖已经确认：底层可以读写隐藏流 `Vtx Index / Vtx Offset / Position`。
  在一个简单 `100x240` solid 探针里，真实点击生成的第一个 pin 读回 `Vtx Index = 7`，而 `PosPin Position` 会对应到图层 source 坐标。
  但“任意生产图层如何从目标点直接算出正确 binding 三元组”还没完全反推出来，所以这个能力暂时还没有开放成稳定的用户接口。
- `ae2claude call add_puppet_pins <layer> "[[x1,y1],[x2,y2]]"`
  当前仅返回转换后的建议坐标和明确错误，避免向工程写入不可见的假 pin。
- `ae2claude call list_puppet_pins <layer>`
  返回当前图层上已经存在的 Puppet pin 的 source/comp 坐标，适合检查人工打点或其他流程生成的真实 pins。
- 现在新增了一条“真实模板层”后台路线：
  - `instantiate_puppet_template_layer(target_layer, template_layer, template_comp=...)`
    会复制一个已经带真实 seed pin 的模板层，并 `replaceSource(...)` 到目标图层 source
  - `set_puppet_pin_positions(layer, points, remove_extra=True)`
    会把模板里已经存在的真实 pins 批量重定位到新的检测坐标上；适合“模板里本来就有 N 个真实 pins”的稳定后台路线
  - `auto_place_puppet_pins_from_multi_pin_template(target_layer, template_layer, template_comp=..., pin_count=4)`
    会优先走“多真实 pin 模板 -> replaceSource -> 后台重定位已有真实 pins”
    这是当前 **3 个及以上可用 pin** 的推荐纯后台方案
  - `add_puppet_pins_on_real_mesh(layer, points, ...)`
    会在这个 real mesh 上后台重定位第 1 个 pin，再补其余 pins
    这条 `seed + 补 pin` 路线目前更偏研究用途；实测只稳定确认到“已有真实 mesh + 第 1 个脚本新增 pin”可形变
  - `auto_place_puppet_pins_from_template(target_layer, template_layer, template_comp=..., pin_count=4)`
    会把上面两步和 Spine 风格边缘检测串起来
- 这条模板路线的前提是：**模板层里必须先有至少 1 个真实点击创建的 seed pin**
  - 一旦模板存在，后续 `replaceSource + 后台补 pin` 就不再依赖截图或真实 viewer click
  - 当前高层接口默认会把原目标层 `disable`，避免被新建的 Puppet 副本盖住或反过来挡住形变结果
- 已用 `puppet_template_backend_autoplace_probe.py` 实测：
  - `real template -> replaceSource -> 后台自动补 3 个 pin -> 再移动 pin`
  - 渲染帧 `md5` 发生变化，说明这条模板后台路线会真实形变，不是壳 pin
- 已用 `puppet_multi_real_template_probe.py` 继续实测：
  - 先自动创建一个 **4 个真实 pin** 的模板层
  - 再走 `replaceSource -> 后台重定位已有真实 pins`
  - 最后分别移动第 `1/2/3/4` 个 pin，渲染帧 `md5` 全部变化
  - 这说明：**多真实 pin 模板重定位** 已经打通，且不依赖截图判断最终 pin 坐标

### Python 调用

```python
from ae_bridge import AEBridge

with AEBridge() as ae:
    ae.add_text_layer("Hello")
    ae.set_text_style("Hello", font_size=56, fill_color=[1,1,1])
    ae.set_keyframes("Hello", "opacity", [(0, 0), (1, 100)])
    ae.apply_transform_easing("Hello", "opacity")

    idx = ae.add_effect("Hello", "gaussian_blur")
    ae.set_effect_props("Hello", idx, {"blurriness": 10})

    # 精确取点
    pixel = ae.sample_pixel(100, 200)

    # 单层 / 多层快速近似取色
    color = ae.approximate_layer_color(31)
    colors = ae.approximate_layers_color([31, 32])

    # 自动 Puppet 打点坐标建议（当前 JSX 后台落 pin 不可用）
    pins = ae.auto_place_puppet_pins(31, pin_count=4)
    print(pins["suggested_comp_points"])

    # 真实模板层后台打点（模板 comp/layer 里需预先有 1 个真实 seed pin）
    rig = ae.auto_place_puppet_pins_from_template(
        target_layer=31,
        template_layer="__codex_real_pin_layer__",
        template_comp="__codex_real_pin_probe__",
        pin_count=4,
    )
    print(rig["layer_name"], rig["pin_count"])

    # 多真实 pin 模板后台打点（模板层里预先已有足够数量的真实 pins）
    rig2 = ae.auto_place_puppet_pins_from_multi_pin_template(
        target_layer=31,
        template_layer="__codex_real_pin_4_template__",
        template_comp="__codex_real_pin_probe__",
        pin_count=4,
    )
    print(rig2["layer_name"], rig2["strategy"])
```

