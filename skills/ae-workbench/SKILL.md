---
name: ae-workbench
description: "Control or troubleshoot After Effects projects through AE2Claude: native properties, animation, previews, rendering and bridge recovery."
---

# After Effects Workbench

Use this single entry for AE2Claude 4.5.0. The MCP starts without AE or network probes; install dependencies with `uv sync` before using the `uv run --no-sync` configuration.

1. Check `ae_native_status` for queue state and `features.nativeOperations` for the loaded AEX's actual exports. Then use `ae_ping` or a small native read to prove a round trip. An open port alone is insufficient.
2. Use stable composition/layer IDs and matchName paths. `ae_overview` and paginated `ae_layers` read only the requested rows in one JSX dispatch.
3. Prefer structured operations: `ae_sample_properties` batches numeric sampling; `ae_footage_inventory` reads native main/proxy metadata; `ae_native_keyframes` includes spatial tangents. Read the [native contract](../../docs/native-automation-4.5.md) before using ease/layer writes.
4. `ae_set_native_keyframe_ease` and `ae_set_native_layer_controls` default to dry-run. Inspect preflight, then write within existing authorization and read back. Each real call uses one undo group. A partial SDK failure is not automatically rolled back.
5. Use checkpoints before risky multi-step edits. Use existing batch/jobs/script-library surfaces rather than starting another bridge. See the [bridge reference](references/bridge/bridge.md) for legacy CLI details; prefer `python -m ae2claude_mcp.cli capabilities --category native-automation` for current schemas.
6. Start the visible queue through `start_render`: it uses `renderAsync()` and refuses synchronous fallback. If the host lacks that capability, use the AE UI. Native reads may wait during rendering; health is independent of the main-thread queue. Verify the output file and render status after completion.
7. Use raw JSX only for API gaps. Send long scripts by file/stdin. Never retry a write with `outcome=unknown`; wait for idle and inspect the actual result. A timeout/cancel does not interrupt already running AE work.

Both loopback HTTP adapters reject browser-origin requests. Use the local MCP/CLI/Python client. The optional undocumented Adobe preview service is no longer enabled by default; discover and verify it separately if explicitly needed.

After upgrading the AEX, close AE normally, deploy with `tools/sync-installation.ps1`, verify hashes, then restart AE. Do not overwrite a loaded AEX. MCP process startup, loaded native version, and a real host operation are separate acceptance checks.
