# AE2Claude

After Effects AEGP 插件，为 Claude 提供与 AE 通信的唯一通道。

## 架构

```
Terminal ──ae2claude CLI──┐
                          ├──HTTP──> AE2Claude Server (port 8089) ──AEGP SDK──> After Effects
Python ──ae_bridge.py─────┘          │
                                     ├─ POST /jsx    ExtendScript 执行 (AEGP_ExecuteScript)
                                     ├─ POST /       Python 代码执行 (PyShiftCore)
                                     └─ GET  /       Health check
```

## 文件

| 文件 | 说明 |
|------|------|
| `AE2Claude.aex` | AEGP 插件 (Release x64)，内嵌 Python 3.12 + HTTP 服务器 |
| `ae2claude_server.py` | HTTP/Pipe 服务器脚本，插件启动时自动加载 |
| `ae_bridge.py` | Python 桥接模块，提供 40+ 高层 AE 操作 API |
| `ae2claude` | CLI 工具，终端直接操控 AE |
| `deploy.bat` | 一键部署到 AE 插件目录 |

## 部署

1. 关闭 AE
2. 运行 `deploy.bat`（需管理员权限）
3. 确保 `python312.dll` 在 AE Support Files 目录
4. 启动 AE
5. 可选：将 `ae2claude` 放入 PATH 目录（如 `~/bin/`）

## CLI 使用

```bash
ae2claude                        # health check
ae2claude version                # AE 版本
ae2claude comps                  # 列出所有合成
ae2claude layers                 # 当前合成图层
ae2claude jsx "app.version"      # 执行任意 ExtendScript
ae2claude py "psc.app.project.name"  # 执行任意 Python
```

## Python API

```python
from ae_bridge import AEBridge

with AEBridge() as ae:
    print(ae.comp_info())
    ae.begin_undo("My Edit")
    ae.add_text_layer("Hello", name="Title", start=1.0, end=5.0)
    ae.add_effect("Title", "gaussian_blur", props={"blurriness": 10})
    ae.end_undo()
```

## 构建

需要 VS 2022 Build Tools + vcpkg boost + pybind11 + Python 3.12 + AE SDK 25.6。

```bash
cd src/PyShiftAE/Win
MSBuild PyShiftAE.vcxproj /p:Configuration=Release /p:Platform=x64
```

## 依赖

- After Effects Beta 26.x
- Python 3.12
- 无外部 Python 包依赖（仅标准库）
