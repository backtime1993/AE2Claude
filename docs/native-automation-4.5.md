# Native automation 4.5.0

Native revision: `native-automation-20260926`. The shared JSON allowlist, Python bridge, MCP and CLI use the same contract. No source evaluation is required by `/native`. Discover client schemas with `ae_capabilities`; verify actual loaded exports in `ae_native_status.features.nativeOperations`. Client descriptors alone do not prove host availability.

| Operation / MCP tool | Contract |
| --- | --- |
| `sample_properties` / `ae_sample_properties` | 1–64 `{layer_id,path}` properties, shared times up to 2048, maximum 4096 values. Resolve the comp and each property once; one main-thread dispatch. |
| `footage_inventory` / `ae_footage_inventory` | Paginate SDK project enumeration (including root), up to 2000 scanned items per page. Main/proxy paths, source signatures, file counts and AE missing flags. Sequence paths identify the first main file, not every disk file. |
| `get_keyframes` / `ae_native_keyframes` | Exact rational time, value, interpolation enum, flags, temporal ease and `[in,out]` spatial tangents; empty tangents for nonspatial properties. SDK position may have 3 dimensions even for a 2D layer. |
| `set_keyframe_ease` / `ae_set_native_keyframe_ease` | Up to 4096 `{index,temporal_ease}` records; zero-based indices. Each temporal dimension is `[inSpeed,inInfluence,outSpeed,outInfluence]`. Native influence is **0.001–1**, not JSX/UI percent. Sets manual Bezier, clears temporal auto/continuous flags, preserves time/value/spatial tangents. Rejects roving keys and locked layers. |
| `set_layer_controls` / `ae_set_native_layer_controls` | Up to 256 unique `{layer_id,flags?,blend_mode?}` records. Flags: enabled, audio_active, effects_active, motion_blur, shy, solo, guide, adjustment. Modes: normal, add, multiply, screen, overlay, difference. Keeps transfer flags and track-matte association. Rejects locked layers and incompatible AV-only controls before mutation. |

Both new write tools default to dry-run. Preflight resolves every target before the undo group begins. Real writes use one undo group; SDK failure after mutation reports `outcome=unknown`, may leave partial changes and is never automatically retried. Undo is recovery, not a transaction guarantee. Read-only policy blocks real writes even when `confirm=true`.

Blend-mode preflight accepts AEGP AV, text and shape/vector layers; other object
types are rejected before mutation. Blend support does not widen the existing
AV-only restriction for `audio_active`, `effects_active` or `adjustment`, even
when the requested flag value is false. Those flag capabilities require separate
host validation. A transfer-mode read failure during preflight is `not_started`;
setter failures after the undo group begins remain `unknown`.

`tests/native_automation_test.cpp` covers the production capability validator.
`tests/test_native_layer_controls_live.py` adds all six modes on AV/text/shape,
mixed invalid batches, dry-run, independent JSX readback of transfer/matte state
and single-step Undo. Run it with `AE2CLAUDE_LIVE_TEST=1`, a rebuilt AEX and an
empty unsaved AE project. This regression is not covered by the earlier live
acceptance measurements below; a new Windows build and host run are required.

Example via Python (the same keyword arguments work with MCP):

```python
ae.set_native_keyframe_ease(
    layer_id, ["ADBE Transform Group", "ADBE Opacity"],
    [{"index": 0, "temporal_ease": [[0, .73, 0, .61]]}],
    comp_id=comp_id, dry_run=True,
)
ae.set_native_layer_controls(
    [{"layer_id": layer_id, "flags": {"motion_blur": True}, "blend_mode": "screen"}],
    comp_id=comp_id, dry_run=True,
)
```

## Performance and live acceptance

Measured locally on AE Beta on 2026-09-26 with a saved, isolated 16-layer fixture; timings are medians of seven calls, not rendering throughput or universal guarantees.

| Call | Before | After |
| --- | ---: | ---: |
| Overview | 85.88 ms | 16.70 ms |
| Layer page | 54.10 ms | 15.30 ms |
| Native status | 15.90 ms | 1.03 ms |
| 16 properties × 128 times, sequential vs batch on the same new build | 171.09 ms | 15.40 ms |

2048 sampled values matched exactly; native diagnostics confirmed one dispatch for the batch. Large mocked 100,000-layer comps verified pagination visits only requested layers. Structured JSX errors allow removing the redundant CEP watchdog round trip; old servers retain their compatibility path.

Live ease writes read back as 73% / 61% through independent JSX. Two-key and two-layer edits were each restored with one AE Undo; invalid later targets and dry-runs left earlier targets unchanged. Spatial tangents matched `[-3,-4,0]` / `[5,6,0]`. Unicode main/proxy footage, missing placeholder flags and multi-page inventory were verified.

The preceding render fix changed `renderQueue.render()` to capability-tested `renderAsync()`: the same 1800-frame fixture had 95/114 hung-window polls before and 0/112 after, with roughly equal 29 s render duration. It fixes UI responsiveness; it does not claim a faster renderer. Queue inspection may be deferred during rendering. Output files must still be verified.

## Local transport boundaries

Ports 8089 and 8891 bind loopback and reject Origin/Sec-Fetch-Site headers and unexpected or duplicate Host values before dispatch. Port 8089 rejects ambiguous HTTP framing; CEP bodies are bounded to 4 MiB and JSON objects. This prevents browser-driven localhost requests and common rebinding, but is not authentication against other local processes. Deliberate local clients retain the user's existing automation privileges.

Use one discoverable router Skill and one lazy MCP definition. Dependencies are installed explicitly, never during `initialize`/`tools/list`. Native SDK headers are developer-supplied and must not be committed. Build using the local licensed SDK, then deploy only with AE closed and verify the loaded artifact hash.
