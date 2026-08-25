# AE2Claude Known Issues

## C++ Native API 稳定性分级

### 稳定 ✅（可放心使用）
- `comp.name/width/height/duration/frameRate/bgColor/workAreaStart/workAreaDuration`
- `comp.addSolid/addNull/addCamera/addLight/addText/addShape`
- `layer.name/label/is3D/layerID/parent/transferMode/stretch/objectType`
- `psc.refresh_ui()`
- `psc.agent_stream_batch()`（整批只进入一次 AE 主线程）
- `psc.agent_inspect_streams()`（整棵属性树只进入一次 AE 主线程）
- `AEBridge.property_batch/get_property/set_property/inspect_properties`

### 不稳定 ⚠️（多步链式调用，可能死锁）
以下 API 因 `enqueueSyncTaskQuiet` + `wait()` 链式调用机制，在 HTTP 线程中可能死锁。**请走 JSX (ae_bridge.py) 替代**：
- `psc.get_stream_value / list_streams / unhide_stream_children`
- `psc.get_keyframe_value / get_keyframe_time / insert_keyframe / delete_keyframe`
- `psc.set_keyframe_ease / set_keyframe_interpolation`
- `psc.get_expression / set_expression`
- `psc.enable_layer_style / set_stream_flag`（Layer Styles 唯一 AEGP-only 功能，偶尔可用但不保证稳定）
- `psc.apply_effect / delete_effect / set_effect_enabled / duplicate_effect / reorder_effect`
- `psc.replace_footage / import_footage / get_footage_path`
- `psc.open_project / save_project / is_project_dirty`
- 所有 Item/Project 原生操作

### 根因
AE 的 AEGP idle hook 从非主线程唤醒不可靠：
- `CauseIdleRoutinesToBeCalled` 必须主线程调（非主线程 crash）
- `PostMessage(WM_NULL)` + `max_sleep=10ms` 不能保证及时响应
- 链式 `enqueueSyncTaskQuiet → wait()` 在 idle 未及时触发时死锁

### 4.3 已落地的解决方案

新 Agent property API 已将多步 stream 寻址、预检、读写和释放封装成单个 task，一次 enqueue 完成整批工作。上面列出的旧 `psc.*` 链式 API 为了兼容仍保留且继续标记不稳定；Agent 和新 CLI 不应再直接使用它们。
