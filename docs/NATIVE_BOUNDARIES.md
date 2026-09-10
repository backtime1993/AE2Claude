# Native dispatcher and transport contract

Revision `dispatcher-20260910`, AE SDK header verified locally on 2026-09-10.

- `MessageQueue` caches the SDK's explicitly thread-safe idle wake function on the AE main thread. Worker threads never acquire SDK suites to wake AE. Main-thread nested calls execute inline.
- `AEGP_IdleHook` sleep is in 1/60-second ticks: pending 1, empty 15. Drain stops between tasks after 4 ms or 32 messages; one running SDK call can exceed that budget.
- Queue capacity 128. Pending work can be cancelled atomically before execution. Running work cannot be forcibly interrupted. Its caller stays alive until completion to protect captured references.
- Native JSX wait accepts 1–600000 ms. Client HTTP deadlines are independent: disconnection/timeout means unknown outcome, never proof of cancellation and never permission to retry a write. MCP background cancellation stops future steps only.
- HTTP transport has at most 16 worker connections and a 2 MiB body limit. Health does not enqueue AE work. Python and JSX execution share one nonblocking lock across HTTP and pipe; concurrent execution receives `busy`, `outcome=not_started`, `retrySafe=true`. Reads that require AE also obey this serialization.
- Health responsiveness depends on a running Python interpreter/GIL. Native SDK/JSX waits release the GIL. Arbitrary extension code holding it can still delay health. A modal or long render may prevent AE from draining the main-thread queue.
- `ae_native_status` exposes queue, idle, execution, and deadline metrics without scheduling an AE task. `ae_validate_expressions` checks an active comp at one time, scans at most 20000 properties and returns at most 200 errors. Disabled expressions' existing errors are included; only enabled expressions are evaluated. It is not whole-timeline validation.
- Kill switch blocks new operations, not already running AE code. Dialog recovery is limited to the separate, scoped script-error watchdog. It cannot safely dismiss arbitrary dialogs or stop a render.
- `ae_exec` and generic Python execution remain privileged local automation, not a sandbox. Loopback binding does not authenticate other local processes. Unknown endpoints and malformed/oversized bodies are rejected before execution.

## Validation

`python -m unittest discover -s tests -v` covers HTTP health under a blocked task, shared execution rejection, limits, deadline negotiation, no double guard, lazy imports, existing workflows and library behavior.

`tests/native_queue_test.cpp` needs C++17 and no Adobe SDK. Build with MSVC `/std:c++17 /EHsc /W4 /WX`, or GCC `-std=c++17 -pthread -Wall -Wextra -Werror`. It covers queued cancellation, running lifetime, 500 execution/cancellation races, inline dispatch, overload, shutdown, idle budget and JSON escaping. Linux CI runs it without distributing Adobe headers.

Full AEX builds require licensed local Adobe SDK links plus Python 3.12, pybind11, vcpkg and MSVC. Publish only `build/Release/AE2Claude.aex`. Run `tools/sync-installation.ps1 -Mode Verify`, then `-Mode Apply -Target 'Adobe After Effects (Beta)'` with AE closed. Apply preserves backups and refuses a running AE process. Verify file hashes and live `ae_native_status` after launch; file copies alone do not prove the new AEX is loaded.
