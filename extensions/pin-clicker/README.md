# AE2Claude PinClicker

Current extension version: PinClicker 0.6.1. The AE2Claude v4.5.0 historical
acceptance covers AE 2025 25.6.4x3 and Beta 27.0x58 on Windows x64.

## Endpoints (listen on `127.0.0.1:8891`)

| Method | Path | Purpose |
|---|---|---|
| GET  | `/health` | Liveness, AE version, mouse subsystem status |
| POST | `/eval` | Run arbitrary ExtendScript, JSON-decoded result |
| GET  | `/viewer-state` | Active composition, viewer zoom, view options |
| POST | `/click-screen` | Synthesize a left click at absolute screen coords (uses `SendInput` via koffi) |
| POST | `/begin-session` | Snapshot active item / selection / solo / enabled / time / tool |
| POST | `/end-session` | Restore snapshot |

`/place-pin`, viewer↔screen mapping, session restore, and version-independent
`AE_CApplication*` window discovery are available in v0.6.

## Why this exists

HANDOFF for `F:/claude/projects/原画skill制作` established that JSX / SDK alone cannot
create *real* Puppet pins — only a real viewer click initializes the mesh binding.
We need a reliable in-process click endpoint that does not depend on third-party panels.

## Install / update

The extension is maintained in `AE2Claude/extensions/pin-clicker`, inside the
main repository rather than a separate project.

From the extracted AE2Claude package, run
`npm ci --omit=dev --no-audit --no-fund --prefix extensions/pin-clicker`.
Copy the complete `extensions/pin-clicker` directory, including its local
`node_modules`, to `%APPDATA%\Adobe\CEP\extensions\AE2ClaudePinClicker`.
Alternatively, link that destination to the extracted directory. The core AEX
deployer does not install this optional CEP panel.

For this unsigned development panel, enable `PlayerDebugMode` as the string `1`
under the `HKCU\Software\Adobe\CSXS.<version>` key used by your AE CEP runtime.
Restart AE and open AE2Claude PinClicker from Window > Extensions.
Its CEP endpoint uses 8891; the Python helper's AE bridge endpoint uses 18889.

After editing `client/main.js` or `CSXS/manifest.xml`, fully restart AE for the
panel to reload (panel JS is not hot-reloaded).

## koffi SendInput

`client/main.js` loads `koffi` from local `node_modules` and defines an `INPUT`
struct that matches Windows x64 layout. Mouse clicks use `MOUSEEVENTF_ABSOLUTE`
over the primary screen — caller must pass physical screen pixels.
