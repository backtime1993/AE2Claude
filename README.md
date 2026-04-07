# AE2Claude

After Effects AEGP 插件，为 Claude / AI Agent 提供与 AE 通信的完整通道。

## 致谢

本项目 C++ AEGP 插件核心基于 [PyShiftAE](https://github.com/Trentonom0r3/PyShiftAE) by [Trentonom0r3](https://github.com/Trentonom0r3)，在其基础上进行了大量扩展：

- 新增 StreamSuite / KeyframeSuite / DynamicStreamSuite / MaskSuite / EffectSuite 原生绑定
- 新增 Layer/CompItem/Item/Footage/Project 完整 pybind11 属性扩展
- 新增 Layer Styles 脚本化支持（通过 DynamicStreamSuite flag 操作，纯脚本做不到）
- 新增 HTTP 服务器 + CLI 工具 + ae_bridge.py 高层 API（65+ 方法）
- 新增 40+ 原生 PyShiftCore API（关键帧 CRUD、效果 CRUD、属性树导航、表达式读写等）

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

## 文件

| 文件 | 说明 |
|------|------|
| `AE2Claude.aex` | AEGP 插件 (Release x64)，内嵌 Python 3.12 + HTTP 服务器 + PyShiftCore |
| `ae2claude_server.py` | HTTP/Pipe 服务器脚本，插件启动时自动加载 |
| `ae_bridge.py` | Python 桥接模块 v2.0（65+ 高层方法，通过 JSX 操作 AE） |
| `ae2claude` | CLI 工具，终端直接操控 AE（`ae2claude help` 查看全部命令） |
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
ae2claude call get_keyframes Text1 opacity  # 读关键帧
ae2claude methods                      # 列出全部 65+ 方法
```

## ae_bridge.py API (65+ 方法)

```python
from ae_bridge import AEBridge

with AEBridge() as ae:
    # 查询
    ae.comp_info()
    ae.list_layers()
    ae.get_transform_value("Layer", "position")
    ae.get_keyframes("Layer", "opacity")

    # 创建
    ae.add_text_layer("Hello", font_size=56)
    ae.add_shape_layer("BG")
    ae.create_camera("Cam", zoom=1200)

    # 动画
    ae.set_opacity_keyframes("Layer", [(0, 0), (1, 100)])
    ae.apply_easing("Layer", ["opacity", "position"])

    # 效果 + 样式
    ae.add_effect("Layer", "gaussian_blur", props={"blurriness": 10})
    ae.add_layer_style("Layer", "drop_shadow")

    # 蒙版 + 预合成
    ae.add_mask_rect("Layer", 0, 0, 500, 500, feather=10)
    ae.precompose(["L1", "L2"], "PreComp")
```

## PyShiftCore 原生 API (40+ 函数，通过 POST / 调用)

高性能路径，跳过 JSX 序列化，直接内存操作 AEGP SDK：

```python
import PyShiftCore as psc

# 关键帧 CRUD
psc.insert_keyframe(layer, ["ADBE Transform Group", "ADBE Opacity"], 1.0)
psc.get_keyframe_value(layer, path, 0)
psc.get_keyframe_time(layer, path, 0)
psc.delete_keyframe(layer, path, 0)
psc.set_keyframe_ease(layer, path, 0, 0, 80, 0, 80)

# 效果
psc.apply_effect(layer, "ADBE Gaussian Blur 2")
psc.delete_effect(layer, 0)
psc.set_effect_enabled(layer, 0, False)

# 属性树
psc.get_stream_value(layer, ["ADBE Transform Group", "ADBE Position"], 0)
psc.list_streams(layer, ["ADBE Effect Parade"])
psc.unhide_stream_children(layer, ["ADBE Layer Styles"])

# 表达式
psc.get_expression(layer, path)
psc.set_expression(layer, path, "wiggle(2,50)")

# Layer Styles (纯脚本做不到)
psc.enable_layer_style(layer, "dropShadow/enabled", True)

# 素材
psc.replace_footage(item, "/new/path.mov")
psc.import_footage("/path/to/file.mov")

# 项目
psc.open_project("/path/to/project.aep")
psc.save_project("/path/to/save.aep")
psc.is_project_dirty()
```

## 构建

C++ 源码在独立仓库 [PyShiftAE](https://github.com/Trentonom0r3/PyShiftAE)（上游）的 fork 中维护。
本仓库只包含预编译的 `AE2Claude.aex` 和 Python/JSX 层。

如需从源码构建，需要：VS 2022 Build Tools + vcpkg boost + pybind11 + Python 3.12 + AE SDK 25.6。

## 环境要求

- After Effects Beta 26.x (Windows x64)
- Python 3.12 (`python312.dll` 在 AE Support Files 目录)
- 无外部 Python 包依赖（仅标准库）
