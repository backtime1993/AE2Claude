# AE2Claude

让 AI 操控 After Effects 的插件。通过终端命令或 Python 代码，直接创建图层、设关键帧、加效果、渲染——不用打开 AE 界面手动操作。

## 它能做什么

- 在终端输入命令，AE 就会执行对应操作
- AI Agent（如 Claude）可以通过它自动化 AE 工作流
- 支持几乎所有 AE 操作：图层、关键帧、效果、蒙版、文字、摄像机、渲染等
- 可检测并删除 PSD/纯色素材里的纯灰/纯白底色层（适合原画包装流程）

## 快速上手

### 安装

1. 关闭 After Effects
2. 双击运行 `deploy.bat`（会自动找到你的 AE 安装位置）
3. 确保 AE 目录里有 `python312.dll`（从 Python 3.12 安装目录复制）
4. 启动 After Effects

### 基本使用

```bash
ae2claude                              # 检查连接状态
ae2claude layers                       # 查看当前合成里的图层
ae2claude pixel 100 200               # 精确读取单个像素
ae2claude pixels 100 200 300 400      # 精确读取多个像素点
ae2claude color 31                    # 快速判断第 31 层的大概颜色（32x32 降采样）
ae2claude colors 31 32                # 批量快速判断多层的大概颜色
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
```

## 设计原则

1. **一个方法做一件事** — 创建和样式分开，添加效果和设参数分开
2. **AI 负责编排** — 循环、过滤、多步操作由 AI 组合调用完成
3. **语义化参数** — 用 `"opacity"` `"position"` 这样的名称，不用 AE 内部代码

## 文件说明

| 文件 | 干什么的 |
|------|----------|
| `AE2Claude.aex` | AE 插件本体（装到 AE 插件目录） |
| `ae2claude_server.py` | 插件内部的通信服务器 |
| `ae_bridge.py` | Python API（~50 个方法） |
| `ae2claude` | 终端命令行工具 |
| `src/` | C++ 插件源码 |
| `scripts/` | 51 个 JSX 脚本工具 |
| `presets/` | 自定义 AE 预设 |
| `deploy.bat` | 一键安装脚本 |
| `test_v3.py` | 自动化测试（73 项） |

## 从源码构建（可选）

普通用户不需要构建——直接用 `deploy.bat` 安装预编译的插件即可。

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
python test_v3.py    # 73 项测试，需要 AE 正在运行
```

## 环境要求

- Windows 10/11 (x64)
- After Effects 2023 / 2024 / 2025 / Beta
- Python 3.12（`python312.dll` 放到 AE 目录）

## 致谢

C++ 插件核心基于 [PyShiftAE](https://github.com/Trentonom0r3/PyShiftAE) by [Trentonom0r3](https://github.com/Trentonom0r3)。采用 **AGPL-3.0** 许可证。
