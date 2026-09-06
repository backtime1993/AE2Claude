# Script error guard, 2026-09-06

## Reproduction
AE Beta 27.0x22; bridge 4.3.1; PinClicker 0.6.0.
Ordinary runtime and syntax errors returned structured errors. The earlier project-read timeout did not recur in this session; it must not be attributed conclusively to this defect.
Temporarily setting JSON to undefined around the old guard, restoring it in finally, caused the error handler itself to throw TypeError. Native execution reproduced one modal; the existing CEP watchdog dismissed it at 118 ms.

## Change
Client and server guards now serialize error fields without the optional ExtendScript JSON global. They evaluate user code inside try/catch, beginSuppressDialogs before evaluation, and endSuppressDialogs(false) in finally. Success values and numeric error line fields are preserved.
Client run_jsx now actually uses its guard and interprets the returned error marker, including when an older server is still loaded. No CEP availability is required to catch ordinary parse/runtime failures. Existing watchdog remains a secondary fallback.
This guard is scoped to bridge execution; it is not a global dismissal of arbitrary AE warnings, Save dialogs, explicit script UI dialogs, or errors from scripts launched independently through File > Scripts.

## Validation
39 tests passed: error-hook behavior plus MCP runtime, project governance and audit hardening.
Real AE: same missing-JSON probe returned the original Error; watchdog found=0 and dismissed=0 across its 1200 ms observation window. Client calls with watchdog arming disabled returned runtime/syntax errors and then 42 for 6*7.
Active project path, 13 project items, and dirty=false were unchanged after probes.
Backups: state/backups/20260906-error-hook/.
Installation and post-restart results are recorded by tools/sync-installation.ps1 and the task report.
