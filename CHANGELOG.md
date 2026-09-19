# Changelog

## v4.4.0 — 2026-09-19

Windows x64 release validated on After Effects Beta 27.0x22, Python 3.12.
Includes the post-v4.3.1 native automation work and Windows acceptance fixes.

### Added

- Five single-dispatch AEGP tools: `ae_native_snapshot`, `ae_sample_property`,
  `ae_native_keyframes`, `ae_set_native_keyframes`, and `ae_layer_transforms`.
  These use stable IDs and bounded numeric operations without changing focus.
- Timeline contact sheets (`ae_preview_frames`), stored A/B pixel differences
  (`ae_compare_frames`), and persistent capture IDs.
- A reusable JSX library: capture successful explicit scripts as unverified
  candidates, inspect and save them, then explicitly replay the hash-checked source.
- Native queue/idle/deadline diagnostics and bounded expression checking at one time.

### Fixed and improved

- Batch argument preflight, emergency-stop checks between steps, synchronous
  script deadlines and separate service/bridge/project readiness reporting.
- Structured JSX parse/runtime errors even when ExtendScript's JSON global is
  absent; ordinary script errors do not depend on the CEP watchdog for recovery.
- Proxy-free loopback transport, rejected redirects, combined status snapshots,
  and no automatic replay after interrupted or malformed execution responses.
- Native queue lifetime, cancellation races, overload handling and idle budgets;
  health avoids scheduling AE work, and native waits release the Python GIL.
- Windows Node test-output decoding explicitly uses UTF-8. This fixes the test
  harness; it is not a claim that every Windows Unicode path has been verified.
- Release preparation adds version checks across Python, CLI, lockfile and plugin,
  GCC/MSVC standalone tests, retained CI reports, and an installed-wheel smoke check.

### Compatibility and behavior to review before upgrading

- Baseline: Windows x64, Python 3.12, AE Beta 27.0; the existing native record is
  specifically for 27.0x22. AE 2023/2024/2025 deployment targets are not evidence
  that this candidate has passed those hosts. PinClicker remains 0.6.0.
- Replace the AEX and its matching Python files together, including the new
  `ae_native_protocol.py`; restart AE and the MCP client, then verify hashes and
  `features.nativeAutomation` / `native.automationRevision`. Version 4.x alone
  does not prove the loaded native capability is present.
- Native keyframe writes default to `dry_run=true`, accept at most 4096 strictly
  increasing times after SDK time quantization, and update supplied times while
  retaining unrelated keys. Existing ease is preserved; new keys use AE defaults.
  This is not complete curve replacement or a rollback-guaranteed transaction.
- `busy` with `outcome=not_started` differs from `outcome=unknown` with
  `retrySafe=false`. HTTP timeout, disconnect or emergency stop cannot forcibly
  interrupt an already-running AE call. Read back state before retrying a write;
  native errors do not trigger an automatic JSX fallback.
- `ae_ping` / `ae_status` now distinguish `serviceReady`, `bridgeReady` and
  `projectReadable`; `ok` requires an enabled, connected, readable project.
- Contact sheets sample sequentially (up to 16 frames), not atomically. Differences
  measure decoded 8-bit preview pixels, possibly resized, not HDR scene values or
  animation quality. Previews/manifests are pruned after 24 hours on later captures.
- Explicit successful JSX is captured locally by default. Candidates expire after
  seven inactive days (maximum 200); saved scripts persist. Configure storage with
  `AE2CLAUDE_LIBRARY_DIR`, or disable capture with `AE2CLAUDE_CAPTURE_SCRIPTS=0`.
  Replaying a saved script still requires inspecting project-specific assumptions.
- Health can still be delayed by extension code holding the GIL; modal dialogs and
  rendering can block AE's main thread. Expression checks cover one time only.

### Windows acceptance fixes

- Preserve server serialization while bounded read-stress retries handle explicit
  `busy/not_started/retrySafe` backpressure. Never replay unknown write outcomes.
- Preflight administrator access and file locks; stage, hash-check and replace the
  complete installation, restoring originals on a normal commit failure.
- Normalize 2D Position writes to the SDK's three-component representation while
  retaining strict 3D validation and rejecting invalid values before mutation.
- Build PiPL resources under paths containing spaces and Chinese characters.
- Initialize SDK outputs, complete return paths, remove handle truncation and
  unreachable catches; enforce selected high-risk compiler warnings as errors.
- Apply one preview deadline across dispatch, PNG stabilization and processing.

### Validation and release scope

- Windows Release x64 AEX built; source, installed file and loaded-module hashes
  verified. Native revision: `native-automation-20260919`.
- Repaired candidate: 122/122 Python tests with live AE enabled, 73/73 legacy API
  checks, 650/650 logical pressure requests; 207 raw busy rejections retained.
- 360 temporary layers and 200 property operations verified and cleaned up;
  4096-key, undo, fractional frame-rate, recovery and preview boundaries passed.
- Clean mapped-file installation, upgrade, rollback to 4.3.1 and re-upgrade passed.
  This uses an existing runtime, not a new Windows machine dependency bootstrap.
- Stable-version checks and CI are recorded with the release assets. Tests on
  other AE versions are not claimed. PinClicker remains independently versioned.
- Wait for AE startup/modal initialization to complete before dispatching scripts;
  an HTTP health response alone does not prove the main thread is ready.
- Installation rollback covers handled failures, not cross-file atomic recovery
  after power loss or forcibly terminating the installer; retain its backups.
- Full native builds retain lower-risk conversion/deprecation warnings. Existing
  render calls cannot be forcibly interrupted by a client timeout.

## v4.3.1 — 2026-08-27

Dual-MCP Codex plugin and non-blocking JSX recovery. See the existing
[release notes](https://github.com/backtime1993/AE2Claude/releases/tag/v4.3.1).
