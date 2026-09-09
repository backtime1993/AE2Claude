# AE connection channel update — 2026-09-09

The MCP and CLI share the existing `ae_bridge.py`; no new server or dependency is required.

- Loopback HTTP uses an explicit proxy-free opener per thread. It refuses redirects and never replays a submitted script.
- Interrupted or malformed JSX responses report `outcome=unknown`, `retrySafe=false`, elapsed time, and instructions to read project state before retrying. A client timeout cannot cancel AE execution.
- MCP ping/status now read AE version and project state together in one 5-second JSX call instead of two. The snapshot works without ExtendScript JSON and includes dirty state. A fresh bridge is still created per MCP call, so AE restart does not leave a cached connection.

## Verification

Tests cover proxy-discovery isolation, redirect rejection, no replay on timeout/reset/malformed responses, reconnect after offline, JSON-independent Unicode and unsaved-project snapshots, and preserving the distinction between bridge readiness and project readability.

Live comparison against AE Beta 27.0x22 with the same 840-item project: three paired status reads were 285.2/143.2, 282.5/133.4, 293.5/141.3 milliseconds (old/new, including bridge construction). This small sample is not a guarantee while AE is busy. A prior trivial script took 4659.5 ms inside AE; client optimization cannot eliminate main-thread waits.

## Deployment boundary

The source workspace was clean before this change. Update only the shared client, MCP facade, and related tests; do not restart After Effects or save the user's dirty project. Verify the loaded MCP by the new `transport=http-loopback-direct` snapshot field.

AE's installed `ae_bridge.py` and `ae2claude_server.py` already differed from the repository before this update. The native AEX hash matched. Installed Python synchronization is still pending an AE restart; it is not part of the live client update. Use the existing `tools/sync-installation.ps1` flow during an authorized maintenance window, then verify installation hashes and live project access separately.

Rollback the client change using its dedicated Git commit after checking subsequent edits. No Codex plugin cache, skill, memory, or user project was modified.

## Final acceptance

61 non-live tests and 4 live tests passed (65 total); the empty-project-only CLI test was skipped because the working project is populated. The first full-suite attempt hit sandbox temp/subprocess permissions; rerun with the task temp directory and permitted execution passed. The broker reported no background tasks before its native refresh. After refresh, ae_ping returned state=ready, transport=http-loopback-direct, projectDirty=true, and elapsedMs=62. AE stayed running; its project was not saved or edited by this task.

