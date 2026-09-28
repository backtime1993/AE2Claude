# 直接进入 AE 工作界面（Windows）

`tools/configure_startup.py` 是一次性、可回退的启动设置工具。关闭主屏幕后，普通启动直接进入工作界面；关闭上次崩溃修复提示后，异常退出后的启动继续加载现有配置。它使用 AE 自身的持久设置，不安装常驻点击程序。

目前实机验证为 Windows x64、After Effects Beta **27.0x58**。必须先关闭所有 AE 实例。

```powershell
# 先查看将要修改的设置。按实际版本修改 prefs-dir。
uv run python tools/configure_startup.py --prefs-dir "$env:APPDATA/Adobe/After Effects (Beta)/27.0" --home-screen skip --crash-repair continue

# 应用并备份；重复执行不会重复修改。
uv run python tools/configure_startup.py --prefs-dir "$env:APPDATA/Adobe/After Effects (Beta)/27.0" --home-screen skip --crash-repair continue --apply --backup-dir state/backups/startup
```

修改范围只有两处现有值：

| 设置 | 值 | 行为 |
| --- | --- | --- |
| General Section / Show Welcome Screen | 00 | 跳过主页 |
| Debug Database / AE.DebugShowPreviousCrashWarning | false | 上次异常退出后不显示崩溃修复选项，继续正常启动 |

第二项是 AE 的版本相关调试设置，并非跨版本稳定的公开接口。缺少该键、格式或位置不符、存在多个匹配项时，工具拒绝写入，不猜测新增键。升级 AE、切换正式版/Beta 或重置首选项后需重新验证。工具仅覆盖已指定版本的首选项目录。

自动保存、未保存工程的恢复提示和崩溃报告保持原设置；这项能力针对“崩溃修复选项”的“继续”。它不会自动丢弃或恢复未保存工程，也不处理缺失插件、登录、许可证或其他阻塞窗口。

应用前备份原文件和清单；写入采用原子替换并逐字节回读，后续文件写入失败会恢复已写文件。保留原编码、换行和 Debug Database 默认值列。实际 27.0 文件含 CRCRLF，此格式已有回归测试。

要恢复提示，关闭 AE 后运行：

```powershell
uv run python tools/configure_startup.py --prefs-dir "$env:APPDATA/Adobe/After Effects (Beta)/27.0" --home-screen show --crash-repair show --apply --backup-dir state/backups/startup
```

实机验收使用单独测试工程：先复现异常退出后的崩溃修复窗口，再应用设置、终止测试实例并重新启动。验证无需点击按钮即可进入空白工作界面。不要以生产工程制造崩溃复现。

本机 Computer Use 的首选项快捷键会导致窗口缩成标题栏，已验证通过菜单操作可规避，见[窗口问题记录](WINDOW_FOCUS_20260929.md)。
