# AE2Claude

After Effects AEGP 插件，为 Claude / AI Agent 提供与 AE 通信的完整通道。

## 致谢

本项目 C++ AEGP 插件核心基于 [PyShiftAE](https://github.com/Trentonom0r3/PyShiftAE) by [Trentonom0r3](https://github.com/Trentonom0r3)，在其基础上进行了大量扩展：

- 新增 StreamSuite / KeyframeSuite / DynamicStreamSuite / MaskSuite / EffectSuite 原生绑定
- 新增 Layer/CompItem/Item/Footage/Project 完整 pybind11 属性扩展
- 新增 Layer Styles 脚本化支持（通过 DynamicStreamSuite flag 操作，纯脚本做不到）
- 新增 HTTP 服务器 + CLI 工具 + ae_bridge.py 原子化 API
- 新增 40+ 原生 PyShiftCore API（关键帧 CRUD、效果 CRUD、属性树导航、表达式读写等）
- 新增 renderFramePixels：原生渲染管线，返回 numpy RGBA 数组，支持像素级采样

原项目采用 **AGPL-3.0** 许可证，本项目遵循相同许可。

## 架构

```
Terminal ──ae2claude CLI──┐
                          ├──HTTP──> AE2Claude Server (port 8089) ──AEGP SDK──> After Effects
Python ──ae_bridge.py─────┘          │
                                     ├─ POST /jsx    ExtendScript 执行 (AEGP_ExecuteScript)
                                     ├─ POST /       Python 代码执行 (PyShiftCore 原生 API)
                                     └─ GET  /       Health check
```

### 设计原则 (v3.0)

1. **一个方法 = 一个 AE 逻辑操作** — 不做胖方法，创建和样式分开，添加效果和设属性分开
2. **Agent 负责编排** — 循环、过滤、多步组合由调用方（Agent）完成，bridge 不做
3. **语义化属性名** — Agent 说 `"position"` `"opacity"`，不接触 AE 内部路径

## 文件

| 文件 | 说明 |
|------|------|
| `AE2Claude.aex` | AEGP 插件 (Release x64)，内嵌 Python 3.12 + HTTP 服务器 + PyShiftCore |
| `ae2claude_server.py` | HTTP/Pipe 服务器脚本，插件启动时自动加载 |
| `ae_bridge.py` | Python 桥接模块 v3.0（~50 原子方法，通过 JSX 操作 AE） |
| `ae2claude` | CLI 工具，终端直接操控 AE（`ae2claude help` 查看全部命令） |
| `src/` | C++ AEGP 插件源码（PyShiftAE/PyShiftCore） |
| `scripts/` | 51 个 JSX 用户脚本 + 效果/预设目录 |
| `presets/` | 自定义 AE 预设 (.ffx) |
| `test_v3.py` | 自包含集成测试（73 项，自动创建/清理合成） |
| `deploy.bat` | 一键部署到 AE 插件目录 |

## 部署

1. 关闭 AE
2. 运行 `deploy.bat`（需管理员权限）
3. 确保 `python312.dll` 在 AE Support Files 目录
4. 启动 AE
5. 可选：将 `ae2claude` 放入 PATH 目录（如 `~/bin/`）

## CLI 使用

```bash
ae2claude                              # health check
ae2claude help                         # 全部命令速查
ae2claude version                      # AE 版本
ae2claude comps                        # 列出所有合成
ae2claude layers                       # 当前合成图层
ae2claude jsx "app.version"            # 执行 ExtendScript
ae2claude py "psc.app.project.name"    # 执行 Python (PyShiftCore)
ae2claude call comp_info               # 调用 ae_bridge 方法
ae2claude call get_value Text1 opacity # 读属性值
ae2claude call get_keyframes Text1 opacity  # 读关键帧
ae2claude call sample_pixel 960 540    # 采样像素颜色 (原生渲染)
ae2claude snapshot                     # 截帧保存 PNG
ae2claude run 摄像机                    # 运行用户脚本
ae2claude scripts                      # 列出全部脚本
ae2claude methods                      # 列出全部方法
```

空项目时执行 `call`/`run`/`layers`/`snapshot` 会自动创建默认合成 (1920x1080, 30fps, 10s)。

## ae_bridge.py API (v3.0)

```python
from ae_bridge import AEBridge

with AEBridge() as ae:
    # 查询
    ae.comp_info()
    ae.list_layers()
    ae.get_value("Layer", "position")
    ae.get_keyframes("Layer", "opacity")

    # 创建
    ae.add_text_layer("Hello")
    ae.set_text_style("Hello", font_size=56, fill_color=[1,1,1])
    ae.add_solid("BG", [0, 0, 0])
    ae.create_camera("Cam", zoom=1200)

    # 动画
    ae.set_keyframes("Layer", "opacity", [(0, 0), (1, 100)])
    ae.set_value("Layer", "position", [960, 540])
    ae.apply_transform_easing("Layer", "opacity")

    # 效果 (index-based)
    idx = ae.add_effect("Layer", "gaussian_blur")
    ae.set_effect_props("Layer", idx, {"blurriness": 10})
    ae.set_effect_keyframes("Layer", idx, {"blurriness": [(0, 0), (1, 50)]})
    ae.apply_effect_easing("Layer", idx, "blurriness")

    # 文本
    ae.set_text_content("Hello", "New Text")
    ae.add_text_animator("Hello", {"opacity": 0})

    # 蒙版
    ae.add_mask("Layer", [[0,0],[500,0],[500,500],[0,500]], feather=10)

    # 预合成
    ae.precompose(["L1", "L2"], "PreComp")
```

## PyShiftCore 原生 API (40+ 函数，通过 POST / 调用)

高性能路径，跳过 JSX 序列化，直接内存操作 AEGP SDK：

```python
import PyShiftCore as psc

# 关键帧 CRUD
psc.insert_keyframe(layer, ["ADBE Transform Group", "ADBE Opacity"], 1.0)
psc.get_keyframe_value(layer, path, 0)
psc.delete_keyframe(layer, path, 0)
psc.set_keyframe_ease(layer, path, 0, 0, 80, 0, 80)

# 效果
psc.apply_effect(layer, "ADBE Gaussian Blur 2")
psc.delete_effect(layer, 0)

# 属性树
psc.get_stream_value(layer, ["ADBE Transform Group", "ADBE Position"], 0)
psc.list_streams(layer, ["ADBE Effect Parade"])

# 表达式
psc.set_expression(layer, path, "wiggle(2,50)")

# Layer Styles (纯脚本做不到)
psc.enable_layer_style(layer, "dropShadow/enabled", True)

# 像素级渲染 (原生管线)
pixels = comp.renderFramePixels(0.0)  # numpy (H, W, 4) uint8 RGBA
print(pixels[540, 960])               # 采样中心像素
```

## 构建

C++ 源码在 `src/` 目录。构建需要：

- Visual Studio 2022 Build Tools (v143)
- vcpkg: boost x64-windows-static
- pybind11 v2.13.6
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
python test_v3.py    # 73 项集成测试，需 AE 运行中
```

测试自动创建合成和图层，运行完自动清理。

## 环境要求

- After Effects 2025 (25.x) 或 Beta 26.x (Windows x64)
- Python 3.12 (`python312.dll` + `python3.dll` 在 AE Support Files 目录)
- 无外部 Python 包依赖（仅标准库）
