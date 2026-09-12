# Native automation

Native revision: `native-automation-20260912`. This is an additive extension of
the existing AE2Claude bridge, queue and busy gate. It adds no service or dependency.
The Python package version remains 4.3.1; loaded native capability is identified by
`/health` → `native.automationRevision` and `features.nativeAutomation`.

## Entry points

| MCP tool | AEBridge / `ae2claude call` method | Purpose and bounds |
| --- | --- | --- |
| `ae_native_snapshot` | `get_native_snapshot` | Project item graph and one composition's layers; up to 2000 items and 2000 layers. Separate truncation flags. |
| `ae_sample_property` | `sample_native_property` | Resolve a numeric property once and sample up to 2048 composition times. Optional pre-expression values. |
| `ae_native_keyframes` | `get_native_keyframes` | Up to 4096 raw key values, rational times, interpolation, flags and temporal ease. Zero-based paging. |
| `ae_set_native_keyframes` | `set_native_keyframes` | Add/update up to 4096 sorted `{time,value}` entries using `StartAddKeyframes / AddKeyframes / SetAddKeyframe / EndAddKeyframes`. Default `dry_run=true`. |
| `ae_layer_transforms` | `get_native_layer_transforms` | Layer-to-world matrices including parents. Up to 64 layers, 64 times, and 1024 matrices in total. |

All tools return `backend=aegp-native`, `revision` and `dispatches=1` on a
successful native response. This describes queue submissions, not a measured
speed multiplier. `comp_id` is a stable project item ID; `0` selects the most
recently used composition. A nonzero ID is preferable in unattended work.
`layer_id` must belong to that composition. No operation changes the active
composition, selection or playhead. No AE handle is retained between requests.

Paths use matchNames for named groups and zero-based integer indices for indexed
groups (for example repeated effects). Names and layer indices are not accepted
as substitutes for stable layer IDs. Numeric streams support scalar, 2D/3D and
spatial variants, and RGBA color. Text, mask, arbitrary-data and marker streams
continue to use the existing structured/script interfaces.

Times are composition seconds, finite and within +/-86400. Input precision is
rounded to the signed 32-bit SDK `A_Time`: microseconds on shorter timelines,
10 or 100 microseconds on longer ones. Keyframe times must remain strictly
increasing after this rounding. Reads include exact SDK time numerator/scale.
`temporalEase` contains one `[inSpeed,inInfluence,outSpeed,outInfluence]` row per
temporal dimension, using the SDK's units. Interpolation and flag fields are SDK
enum values, not ExtendScript enum integers. Matrices retain SDK `mat[row][column]`
layout; they are layer-to-world, not camera-projected screen coordinates.

## Write behavior

Dry-run resolves the layer and property, checks the locked state, verifies that the
stream supports animation, and validates every value's dimensions before opening
an undo group. Boolean, nonfinite, duplicate/quantized-duplicate times and unknown
arguments are rejected before dispatch. Writes obey MCP approval mode and kill switch.

The bulk writer updates supplied times and keeps unrelated keys. It does not change
dimension separation, expressions or interpolation explicitly; new key interpolation
uses AE defaults. It is not a complete animation-curve replacement API. Use the
existing property/JSX surface for custom ease or spatial-tangent editing.

The native operation uses one undo group and the SDK bulk-keyframe accumulator,
so it avoids a whole-stream undo copy for every key insertion. A failed commit is
reported as `outcome=unknown`, `retrySafe=false`, including when abort cleanup
succeeds. Verify the actual keys before deciding what to do next. No automatic
fallback to JSX, request replay or forced interruption is implemented.

## Thread and transport contract

`POST /native` accepts only `{operation,arguments}` from an explicit allowlist.
Client and server share dependency-free validation in `ae_native_protocol.py`.
The route shares the existing 2 MiB body limit, 16-connection ceiling and execution
lock with Python/JSX. A busy call returns `not_started`; health remains independent.
It never compiles/evaluates received Python or JSX source.

Every suite acquisition, handle lookup, SDK operation and handle disposal runs
inside one existing idle-queue task. Python input is parsed before releasing the
GIL; only owned C++ data crosses the queue, and Python results are built after
the GIL is reacquired. Sampling an expression can still take substantial time:
limits bound the number of calls, not the duration of one SDK call. HTTP timeout
does not stop a running native call or imply it is safe to repeat a write.
`get_native_diagnostics()` refreshes `/health` on every call, including when the
same Python client is reused, so queue and idle metrics are not connection-time snapshots.

## Build and acceptance

Build `Release|x64` with the local licensed Adobe SDK. The current implementation
uses ProjSuite6, ItemSuite9, CompSuite11, LayerSuite9, StreamSuite6,
DynamicStreamSuite4, KeyframeSuite5, EffectSuite4, MemorySuite1 and UtilitySuite6.
No Adobe SDK headers are committed.

Run `python -m unittest discover -s tests -v`, plus the SDK-independent C++ queue
and native automation validation tests. Transport tests use a simulated native
module; they prove validation, one native invocation, shared busy behavior and
error propagation, not behavior inside a real AE project.

Use `tools/sync-installation.ps1` with AE closed. It includes
`ae_native_protocol.py` in backup/copy/hash verification. The AEX source remains
`build/Release/AE2Claude.aex`. A running AEX cannot be replaced in memory.

After restart, verify the loaded AEX hash and automation revision, then test
snapshot/sampling against equivalent JSX reads. Use a disposable composition
for bulk writes, read keys back, and measure queue submissions and elapsed time
on the same data. Compilation and simulated tests alone are not live acceptance.

SDK reference: [AEGP suites and adding multiple keyframes](https://ae-plugins.docsforadobe.dev/aegps/aegp-suites/#adding-multiple-keyframes).

## Local verification, 2026-09-12

Release x64 was loaded and tested in After Effects Beta 27.0x22. Loaded AEX SHA-256:
`C17326732DACC68A1EE026F4D5D5A33904342C0DF3C990AB2C0D127C44C1643F`.
The complete Python suite ran 104 tests: 99 passed and 5 conditional tests were
skipped. Both SDK-independent C++ executables passed. Fresh MCP discovery exposed
all five added tools, and the installed connector returned real project data.

A disposable AE project passed 35 live checks: JSX/native value agreement,
pre/post-expression sampling, color values, parent transforms, nonactive comp
access, bounded paging, dry-run, bulk readback, existing-key upsert, custom ease
preservation, a single undo restoring the whole batch, and locked-layer rejection.
The original 145-item project, active composition, time and selection were restored;
the project remained unmodified.

| Same 256 values | Previous native property batch | New direct SDK batch | Queue submissions |
| --- | ---: | ---: | ---: |
| Write keyframes | 87.158 ms | 21.929 ms | 11 -> 1 |
| Read samples | 27.002 ms | 4.612 ms | 12 -> 1 |

These are local wall-clock observations for the validation fixture, including HTTP
overhead, not a general AE rendering or every-project speed guarantee. AE startup
and modal dialogs still require a responsive application main thread.
