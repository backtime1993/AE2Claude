# AE2Claude 测试分层

当前版本的证据归档与验证边界见 [发布清单](RELEASE_CHECKLIST.md)。CI 保留
Python 测试日志、GCC/MSVC 独立 C++ 测试日志及 Python 安装包检查结果 30 天；
这些云端检查不替代以下 AE 真机验收。

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
$env:AE2CLAUDE_EXPECTED_AE_MAJOR='27' # AE 2025 改为 25
uv run python -m unittest discover -s tests -v
uv run python test_v3.py
uv run python tools\stress_test.py --ae-major 27 --requests 200 --workers 8 --write-cycles 12 --layers-per-cycle 30 --agent-operations 200
```

AE 2025 同时将环境变量和压力测试的 `--ae-major` 改为 `25`；默认仍为 `27`，连接到不符的宿主必须失败。两套 AE 逐个运行，不同时占用 18889/8891。先确认插件启动完成且空白工程可读，再开始会修改工程的测试。

压力测试包含 18889、8891、并发 JSX 只读、MCP 门面、受控写入，以及 Agent 属性树的单次 AEGP 批处理与逐条请求对比。写入阶段只有在 AE 是空白且未保存的工程时才执行；每轮创建的合成和图层会在返回前删除。完整 JSON 报告写入 `artifacts\stress`。

只有以下条件全部满足才算通过：

- 单元测试、实机测试、原生构建均为零失败；
- 18889 与 8891 压测零失败；
- AE 版本、主桥、MCP、PinClicker 版本一致；
- 写入压力结束后工程条目数恢复为零；
- 安装目录与 Release AEX 的 SHA-256 一致。


## Windows acceptance fixes

The concurrent read stress client handles server backpressure with at most 100
attempts within a five-second retry budget. It retries only explicit
`kind=busy, outcome=not_started, retrySafe=true` responses; transport errors and
unknown write outcomes are never replayed. The report retains `backpressure`
rejection counts alongside successful logical requests. Passing requires every
logical read and write to succeed within its budget, not zero admission rejections.

`tests/test_release_repairs.py` exercises real Windows file locks, successful
installation, and a failure after both a replacement and a new-file creation.
`tests/test_release_live.py` verifies 2D Position, dry run, single undo, 3D
validation, and unchanged keys after rejection against the loaded AEX.

Preview deadlines include the bridge call, asynchronous PNG stabilization and
image processing. A timed-out preview is not replayed; an AE render already in
progress may still complete. Confirm host recovery before another operation.
