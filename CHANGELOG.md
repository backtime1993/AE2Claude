# Changelog

## v4.4.0-rc.1 — Unreleased

Candidate preparation only; no tag, GitHub Release or production acceptance is
implied. Python identifies this candidate as `4.4.0rc1` (PEP 440); the Codex
plugin uses `4.4.0-rc.1` (SemVer). Target stable version: v4.4.0.

Changes below include all seven commits after v4.3.1 through `f1e5f8a`, not only
the September 9–13 work. See the [full comparison](https://github.com/backtime1993/AE2Claude/compare/v4.3.1...f1e5f8afd72cce4ee5cc808b22e7277f0b813017).

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

### Validation evidence and remaining gates

- Baseline `f1e5f8a` CI: 104 Python tests, 99 passed and 5 live-dependent tests
  skipped; GCC queue/validation executables and PinClicker syntax check passed.
- The [September 12 local record](docs/NATIVE_AUTOMATION.md#local-verification-2026-09-12)
  reports 35 native live checks on AE Beta 27.0x22 and the loaded AEX SHA-256.
  For the same 256-value fixture, key writes were 87.158 → 21.929 ms and sample
  reads 27.002 → 4.612 ms. These are local observations, not universal speedups;
  `dispatches=1` counts queue submissions, not an acceleration factor.
- These are historical results, not a completed candidate release sign-off. Use
  the candidate PR's CI reports for its current counts and exact tested commit.
  Full AEX build, live integration, legacy regression, stress, installation and
  rollback evidence remain required by the [release checklist](docs/RELEASE_CHECKLIST.md).
- CI wheel/sdist artifacts contain the Python client, not an installable AEX bundle.
  No package upload or GitHub Release is performed by CI.

## v4.3.1 — 2026-08-27

Dual-MCP Codex plugin and non-blocking JSX recovery. See the existing
[release notes](https://github.com/backtime1993/AE2Claude/releases/tag/v4.3.1).
