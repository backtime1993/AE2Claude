# AE2Claude PinClicker

## Endpoints (listen on `127.0.0.1:8891`)

| Method | Path | Purpose |
|---|---|---|
| GET  | `/health` | Liveness, AE version, mouse subsystem status |
| POST | `/eval` | Run arbitrary ExtendScript, JSON-decoded result |
| GET  | `/viewer-state` | Active composition, viewer zoom, view options |
| POST | `/click-screen` | Synthesize a left click at absolute screen coords (uses `SendInput` via koffi) |
| POST | `/begin-session` | Snapshot active item / selection / solo / enabled / time / tool |
| POST | `/end-session` | Restore snapshot |

Higher level `/place-pin` + viewer↔screen mapping land in v0.2.

## Why this exists

HANDOFF for `F:/claude/projects/原画skill制作` established that JSX / SDK alone cannot
create *real* Puppet pins — only a real viewer click initializes the mesh binding.
We need a reliable in-process click endpoint that does not depend on third-party panels.

## Install / update

Panel lives at `F:/claude/longterm/AE2ClaudePinClicker/`. A symlink in
`%APPDATA%/Roaming/Adobe/CEP/extensions/AE2ClaudePinClicker` points to this tree
so code edits are picked up on the next AE launch.

`PlayerDebugMode=1` must be set under `HKCU\Software\Adobe\CSXS.9..12` (already done on this host).

After editing `client/main.js` or `CSXS/manifest.xml`, fully restart AE for the
panel to reload (panel JS is not hot-reloaded).

## koffi SendInput

`client/main.js` loads `koffi` from local `node_modules` and defines an `INPUT`
struct that matches Windows x64 layout. Mouse clicks use `MOUSEEVENTF_ABSOLUTE`
over the primary screen — caller must pass physical screen pixels.
