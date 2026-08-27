---
name: ae-workbench
description: "After Effects Beta workbench for Codex. Use for AE, AE Beta, After Effects, Adobe's bundled preview MCP, AE2Claude, JSX, compositions, layers, properties, effects, keyframes, previews, checkpoints, 3D, MOGRT, rendering, and blocking script-dialog recovery."
---

# After Effects Beta Workbench

Use this entry for After Effects work. It combines the preview MCP bundled with After Effects Beta 27 and AE2Claude 4.3.1. Prefer structured MCP tools; use raw JSX only when neither structured surface covers the operation.

## Primary Route

1. Inspect the running application and current project before making changes.
2. Prefer the bundled preview MCP for native composition editing, animation, 3D, Essential Graphics, MOGRT, and rendering when its live schema supports the requested operation.
3. Use AE2Claude for stable IDs, locale-independent `matchName` property paths, checkpoints, recovery, batch/background jobs, events, Puppet Pin work, pixel sampling, and controlled JSX.
4. Before risky multi-step edits, create an AEP checkpoint. Destructive operations require explicit confirmation.
5. If one channel is unavailable, diagnose it independently and continue only through a channel that has been verified live.

The bundled preview server uses Streamable HTTP at `http://localhost:3100/aftereffects/mcp`. Keep `localhost` in the URL because the service may listen only on IPv6 `::1`. It is Adobe-shipped but undocumented preview functionality, so enumerate its current tools after After Effects Beta updates instead of assuming schemas are stable.

## Blocking Errors

- AE2Claude wraps ExtendScript failures so syntax and runtime errors return machine-readable fields instead of opening a modal dialog.
- If a legacy or external script still opens a blocking AE script-error dialog, call `ae_recover_script_dialog(confirm=true)`. It uses the independent helper to close only an AE `#32770` script dialog and returns a structured recovery result.
- Use visible desktop control only for other UI-only work. Do not replace native AE control with browser automation.

## Verification Boundary

- An MCP process starting is not proof that After Effects is connected. Verify both the MCP service and the live AE bridge.
- If AE is closed, report the control service as available but the application bridge as offline.
- After any write, read back the affected project, composition, layer, or property and preview visually when the result is appearance-sensitive.
