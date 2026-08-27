# AE2Claude

让 AI 操控 After Effects 的原生插件。通过 MCP、终端命令或 Python
代码直接创建图层、设关键帧、加效果、预览和渲染。

当前兼容基线：AE2Claude 4.3.0、After Effects Beta 27.0、Python 3.12。

## 它能做什么

- 在终端输入命令，AE 就会执行对应操作
- AI Agent（如 Claude）可以通过它自动化 AE 工作流
- Codex、Claude Code 和其他 MCP 客户端可直接连接
- 支持几乎所有 AE 操作：图层、关键帧、效果、蒙版、文字、摄像机、渲染等
- 可检测并删除 PSD/纯色素材里的纯灰/纯白底色层（适合原画包装流程）
- 提供真实合成帧预览、AEP 检查点/回滚、诊断、安全模式和急停开关

## 快速上手

### 安装

1. 关闭需要更新的 After Effects
2. 先构建 `build\Release\AE2Claude.aex`，再运行 `deploy.bat`（默认同步当前或 Beta；也可传入完整 AE 产品名）
3. 确保 AE 目录里有 `python312.dll`（从 Python 3.12 安装目录复制）
4. 启动 After Effects

只核验所有受支持安装、不写入：

```powershell
pwsh -File tools\sync-installation.ps1 -Mode Verify -AllSupported
```

### Codex 插件（双 MCP）

仓库根目录同时是一个可安装的 Codex 插件。插件会接入两个互补通道：

- AE2Claude MCP：稳定 ID、属性批处理、检查点、后台任务、安全 JSX 与故障恢复
- After Effects Beta 内置预览 MCP：原生工程检查、合成编辑、动画、3D、MOGRT 与渲染

Codex 插件清单位于 [`.codex-plugin/plugin.json`](.codex-plugin/plugin.json)，
双通道配置位于 [`.mcp.json`](.mcp.json)。Adobe 内置接口属于 Beta 27
随应用提供但尚未公开文档化的预览能力；不可用时会继续使用 AE2Claude。

### MCP 接入（推荐）

在仓库目录安装锁定依赖：

```powershell
uv sync
uv run ae2claude-mcp
```

把 [`.mcp.json.template`](.mcp.json.template) 复制到 MCP 客户端配置，
并将 `<ABSOLUTE_PATH_TO_AE2CLAUDE>` 换成仓库绝对路径。MCP 使用原有
AEGP 原生桥的 `8089` 端口，不需要额外 CEP 面板。

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
[`docs/AGENT_ARCHITECTURE.md`](docs/AGENT_ARCHITECTURE.md)。

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

## 设计原则

1. **原子方法 + 批处理协议** — 旧方法保持兼容，性能敏感参数通过单次主线程批处理
2. **可发现而不是猜命令** — Agent 先读 capability schema 和属性树，再组合工作流
3. **稳定寻址** — 优先使用合成/图层 ID 和跨语言 `matchName`，避免名称重复与索引漂移
4. **可恢复与可追踪** — 参数批次单次撤销，长任务有状态、取消、TTL 和事件 cursor

## 文件说明

| 文件 | 干什么的 |
|------|----------|
| `build/Release/AE2Claude.aex` | 当前源码构建出的 AE 插件本体（部署来源） |
| `ae2claude_server.py` | 插件内部的通信服务器 |
| `ae_bridge.py` | Python API（当前 123 个公开方法） |
| `ae2claude` | 终端命令行工具 |
| `ae2claude_mcp/` | MCP、诊断、预览、安全门禁和检查点实现 |
| `.mcp.json.template` | MCP 客户端配置模板 |
| `pyproject.toml` / `uv.lock` | 可复现的 Python 依赖 |
| `src/` | C++ 插件源码 |
| `scripts/` | 48 个已登记 JSX 脚本工具 |
| `presets/` | 自定义 AE 预设 |
| `deploy.bat` | 一键安装脚本 |
| `extensions/pin-clicker/` | 与主工程同版本管理的 Puppet Pin 精确点击端点 |
| `tools/` | 初始化、安装同步、自动拉齐、定向清理和压力测试 |
| `test_v3.py` | 自动化测试（73 项） |

## 从源码构建（可选）

`deploy.bat` 只部署 `build/Release/AE2Claude.aex`，避免误装仓库根目录里的旧二进制。

如果你想修改 C++ 插件源码，需要：

- Visual Studio 2022
- vcpkg（boost）
- pybind11
- Python 3.12
- AE SDK 25.6

设置环境变量后构建：
```bash
set PYTHON_DIR=C:\Python312
set VCPKG_INSTALLED=C:\vcpkg\installed
set PYBIND11_DIR=C:\pybind11
MSBuild src\PyShiftAE\Win\PyShiftAE.vcxproj /p:Configuration=Release /p:Platform=x64
```

## 测试

```bash
uv run python -m unittest discover -s tests -v  # MCP 与安全单元测试
python test_v3.py    # 73 项测试，需要 AE 正在运行
```

## 环境要求

- Windows 10/11 (x64)
- After Effects 2023 / 2024 / 2025 / Beta 27.0（当前实机基线）
- Python 3.12（`python312.dll` 放到 AE 目录）
- MCP Python SDK `>=1.27,<2` 与 Pillow（由 `uv sync` 自动安装）

## 致谢

C++ 插件核心基于 [PyShiftAE](https://github.com/Trentonom0r3/PyShiftAE) by [Trentonom0r3](https://github.com/Trentonom0r3)。采用 **AGPL-3.0** 许可证。

MCP 产品层设计参考了
[JUNKDOGE-JOE/after-effects-mcp](https://github.com/JUNKDOGE-JOE/after-effects-mcp)
的诊断、预览、检查点和审批思路；AE2Claude 保留自己的 AEGP 原生传输与
深度 AE 能力。详情见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
