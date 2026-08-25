# AE2Claude 测试分层

## 每次提交

```powershell
uv sync --locked
uv run python -m unittest discover -s tests -v
npm.cmd ci --omit=dev --no-audit --no-fund --prefix extensions\pin-clicker
npm.cmd run check --prefix extensions\pin-clicker
```

## 原生构建

设置 `PYTHON_DIR`、`VCPKG_INSTALLED`、`PYBIND11_DIR` 后，以 VS 2022 Release/x64 构建 `src\PyShiftAE\Win\PyShiftAE.vcxproj`。成功产物必须是 `build\Release\AE2Claude.aex`。

## AE 实机验收

AE 正在运行且插件已加载时：

```powershell
$env:AE2CLAUDE_LIVE_TEST='1'
uv run python -m unittest discover -s tests -v
uv run python test_v3.py
uv run python tools\stress_test.py --requests 200 --workers 8 --write-cycles 12 --layers-per-cycle 30
```

压力测试包含 8089、8891、并发 JSX 只读、MCP 门面与受控写入。写入阶段只有在 AE 是空白且未保存的工程时才执行；每轮创建的合成和图层会在返回前删除。完整 JSON 报告写入 `artifacts\stress`。

只有以下条件全部满足才算通过：

- 单元测试、实机测试、原生构建均为零失败；
- 8089 与 8891 压测零失败；
- AE 版本、主桥、MCP、PinClicker 版本一致；
- 写入压力结束后工程条目数恢复为零；
- 安装目录与 Release AEX 的 SHA-256 一致。
