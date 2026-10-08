# v4.5.0 发布验收清单

发布范围：Windows x64 原生插件完整包、Python wheel/sdist、源码标签、发布说明、验证报告与 SHA-256。各表面版本为 4.5.0，PinClicker 自身版本为 0.6.1。

## 本次发布证据

- 最终源码提交、CI run、附件名称与哈希写入 Release 的 `VALIDATION-4.5.0.json` 和 `SHA256SUMS-4.5.0.txt`。
- GitHub CI：215 项 Python 测试（156 通过、59 项需要 AE 的测试跳过）、GCC/MSVC 两组 SDK 独立原生测试、PinClicker 语法检查、安装后 wheel 冒烟测试。
- 完整包需从最终源码归档组装，含 `build/Release/AE2Claude.aex`、配套 Python/MCP/CLI、配置、scripts、presets、扩展源码与部署工具；逐文件清单随包提供。
- 解压后的新副本验证内容哈希，并在隔离虚拟环境验证 Python 包及 MCP 工具发现。发布后重新下载附件验证 SHA-256。

## 复用的原生与实机验收

- 原生源码树与提交 `df2708b` 一致；AEX 为 2026-09-29 验收的相同二进制，大小 2,462,720 字节。
- AEX SHA-256：`aa5e9bbb8c5968faf3b84f7b87394c8f28568c790a1fbef4accd5f5dc3b584e8`。
- [两版 AE 的历史 214 项验收](BETA_TIMELINE_20260929.md)：AE 2025 25.6.4x3 与 Beta 27.0x58。包括原生时间溢出、静态赋值、批次状态和失败依赖修复。
- [更早的实机回归与压力记录](LIVE_REGRESSIONS_20260929.md)涵盖冷启动 JSON、模态窗口、预合成、蒙版、定格和倒放等；各统计保留原日期和原范围。
- 2026-10-08 只读健康检查确认运行中的 Beta 加载同一 AEX，bridge 4.5.0、18889 端口及 `native-automation-20260926` 能力可见。

## 边界

本次发布不修改或重启用户的 AE，不重跑会写入工程的整套实机测试，也不宣称重新完成全新 Windows 安装或升级/回退验收。复用的 AEX 有原始实机记录，原生源码未变；新增连接配置由云端测试覆盖。

完整包不包含 Adobe SDK、AE、Python 3.12 运行时或第三方依赖环境。用户需按[安装说明](BUILDING.md)准备依赖；可选 PinClicker 按其 [README](../extensions/pin-clicker/README.md)安装。Python wheel 不包含 AEX。

发布必须核对最终标签和 master 的提交、GitHub Latest 指向 v4.5.0、资产数量与下载哈希。旧版 v4.4.0 保留作回退，使用旧版时恢复其配套端口 8089 和配置。
