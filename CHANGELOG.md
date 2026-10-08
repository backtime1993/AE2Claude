# Changelog

## Unreleased — 2026-10-08 upstream sync

- Synced the eight existing local commits covering AE regressions, startup
  preferences, batch integrity, timeline precision and the bridge port change.
- Completed the 18889 default-port migration in both MCP configuration templates,
  PinClicker's Python client and the pressure-test harness. PinClicker's CEP
  endpoint remains 8891. Existing v4.4.0 installations still use 8089.
- Corrected the README's release link and candidate status. v4.4.0 remains the
  latest published binary release; this source update does not publish a new AEX
  package or claim a new live AE acceptance run.

## Unreleased — 2026-09-29

- Fixed 17 locally reproduced JSX/native regressions in layer ordering,
  track mattes, precompose, expression sampling, masks, parenting, time remap,
  render-queue counts, Unicode strings, cold-start JSON, native property paths,
  2D Position and unsupported easing. Windows modal JSX calls now return a
  retry-safe not-started result before invoking the host script engine.
- Added an opt-in, backed-up startup preferences tool to skip Home and the
  previous-crash repair prompt. The version-specific debug key is validated
  before any write; project auto-save/recovery behavior is retained.
- Local Windows / AE Beta 27.0x58 acceptance: 179 tests, 650 pressure requests,
  360 temporary layers and 9 rendered verification frames passed. Native fixes
  require rebuilding and restarting AE. No new release is implied.
  See [evidence and limits](docs/LIVE_REGRESSIONS_20260929.md).

## 4.5.0 candidate — 2026-09-26

- Added native single-dispatch multi-property sampling, main/proxy footage
  inventory, manual keyframe Bezier easing, spatial tangent readback and bulk
  layer switches/blend modes. New writes preflight all targets, default to
  dry-run and use one undo group. Native revision: `native-automation-20260926`.
- Bounded overview/layer pagination now traverses only requested rows. Avoid
  redundant health and modern JSX watchdog round trips. Local 2048-value batch
  sampling measured 15.40 ms versus 171.09 ms for sequential requests.
- Reject browser-origin and unexpected Host requests on both loopback adapters;
  reject ambiguous HTTP framing on the native server and bound CEP JSON bodies.
- Advertise actual loaded native operations independently of static MCP/CLI
  schemas. Consolidate repository plugin discovery to one router and one lazy
  MCP; dependency installation is explicit (`uv sync`), startup uses `--no-sync`.
- Reviewed community MCP, CLI and Skill designs; see
  `docs/community-review-20260926.md` for primary sources and adoption decisions.

- `start_render()` now calls AE's capability-checked `renderAsync()` and returns
  `render_started` immediately. It no longer blocks the native idle hook until
  export completes. Hosts without this API fail explicitly and require the UI;
  there is no synchronous fallback. Callers must stop treating return as completion.
- Added `get_render_status()` with named queue statuses. AE can defer JSX status
  reads until rendering ends; use the visible queue for progress and pause/stop.
  `render_started` is acceptance only. Never automatically replay an unknown result.
- Windows AE 27 output paths now use `setSettings` / `Full Flat Path`; assigning
  `OutputModule.file` corrupted Chinese directory names to `?` in live testing.
  Apply templates before paths, and reacquire the output module afterwards.
- Escape output paths and templates, reject invalid queue indexes and non-comp
  selections, roll back newly added items when configuration fails, and propagate
  malformed queue responses instead of reporting an empty queue.
- Verified through the installed personal plugin: a 60-second 1280x720 H.264
  export returned in 0.062 s instead of 29.187 s; Windows hung-window samples
  dropped from 95/114 to 0/112. Both outputs contained 1,800 frames. A separate
  Chinese-path export and failed-template rollback passed. The render fix alone
  needs no AEX replacement; the new native operations above require the matching build.

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
