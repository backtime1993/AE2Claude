# AE2Claude Known Bugs

## BUG-1: CauseIdleRoutinesToBeCalled crash (CRITICAL)
- **现象**: 调用 C++ 原生 stream/keyframe/effect API 时 AE 崩溃
- **原因**: `enqueueSyncTask`(TaskUtils.h) 每次调用都触发 `CauseIdleRoutinesToBeCalled`，该 API 只允许主线程调用。HTTP 服务器线程连续触发 5-10 次后 assert 溢出崩溃
- **影响范围**: 所有 `bindStreamUtils` 里的 lambda 函数（get_stream_value, get_keyframe_value, insert_keyframe, apply_effect, replace_footage 等）
- **修复方案**: 创建 `enqueueSyncTaskQuiet`（不调 CauseIdleRoutinesToBeCalled），链式操作只第一次用 `enqueueSyncTask`，后续用 quiet 版
- **状态**: 待修复

## BUG-2: animate_text_selector selector index 无效
- **现象**: `ae.animate_text_selector('Text1', keyframes=...)` 报 "参数 1，无法调用 property。范围没有值"
- **原因**: 新建 Animator 后 selector 的 property 索引不稳定，`property("ADBE Text Selectors").property(1)` 可能为空
- **修复方案**: 改为用 matchName 或先检查 numProperties
- **状态**: 待修复

## BUG-3: reorder_layer 用了 moveTo 报错
- **现象**: `ae.reorder_layer('Layer', 1)` 报 "无法使用 moveTo"
- **原因**: JSX 中 `layer.moveTo()` 是 AE layer 方法，不是 property 方法。当前代码可能在错误的上下文调用
- **修复方案**: 检查 JSX 语法，确认 moveTo 的正确用法
- **状态**: 待修复
