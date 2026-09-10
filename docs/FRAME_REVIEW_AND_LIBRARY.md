# Timeline review and reusable JSX

These additions reuse AE2Claude's native connection, existing PNG capture and Pillow.
No additional AE panel, plug-in binary or dependency is required. The design was
informed by JUNKDOGE-JOE/after-effects-mcp's contact sheets and Tool Library;
implementation is local Python code, not a transplanted CEP server.

## Timeline contact sheets and A/B comparisons

- `ae_preview_frames(times=[0, 0.5, 1])`, or
  `ae_preview_frames(start=0, end=2, count=6)`, returns one labeled contact sheet,
  per-frame metadata and a persistent `captureId`. At most 16 frames per call.
- `ae_compare_frames(capture_a=ID, index_a=0, capture_b=ID, index_b=1)` returns
  labeled A/B images, a red difference map, changed pixel count/ratio, mean/max
  absolute difference, and the changed region. Indices are zero-based.
- For before/after work, capture the same time with the same `max_width` before
  editing, then again after editing, and compare the two capture IDs.
- Files are hash-checked; altered/missing frames and different image dimensions
  are rejected. Persistent IDs survive an MCP service restart until the preview
  files expire. Sequential captures are not an atomic project snapshot.
- Metrics describe **decoded 8-bit preview pixels**, potentially resized, not
  original HDR scene values. RGB is compared over black, with alpha included;
  invisible RGB changes are ignored. A changed pixel has any channel difference
  **greater than** `threshold` (default 8). `bbox` uses preview coordinates with
  exclusive right/bottom edges; null means unchanged. These metrics do not judge
  animation quality and an all-zero difference is not proof of correct animation.
- Sampling does not intentionally move the playhead, save or edit the project.
  Heavy compositions should use fewer samples per call; the capture loop has a
  110-second dispatch budget plus PNG completion. Cancellation checks the existing
  emergency switch between frames; a running AE frame cannot be forcibly cancelled.
- Inline images are reduced to fit the response budget while artifact files remain
  intact. `AE2CLAUDE_PREVIEW_ROOT` overrides the existing temporary preview directory;
  previews and capture manifests expire after 24 hours. Copy useful artifacts into
  the task's AE workspace to retain them.

## Script capture, inspection and promotion

Explicit successful `ae_exec`, `ae_run_script`, and `ae_call` / `ae_batch` /
`ae_submit` calls to `run_jsx` or `run_jsx_checked` automatically capture the exact
JSX as an **unverified candidate**. Internal inspection/preview scripts and legacy
CLI calls are not captured. Capture never executes an additional AE command.

1. Read the returned `capture.artifactId`, or search with
   `ae_script_library(action="search", status="candidate")`.
2. Inspect exact source with `action="inspect", artifact_id=ID`.
3. Independently inspect the AE result/preview, then promote with
   `action="save", artifact_id=ID, name="...", description="...", tags=["..."],
   verified=True`. Keep `verified=False` if only script execution was checked.
4. Search the saved library by name/description/tags. Before reuse, inspect source
   and check hard-coded project paths, composition/layer IDs, timing and assumptions.
5. `ae_replay_script(artifact_id=ID, confirm=True)` executes hash-checked source
   under the original raw-JSX authorization boundary. An optional
   `checkpoint_label` uses the existing AEP checkpoint behavior, which saves the
   current project. Never add it to a read-only request without authorization.

`action="archive"` hides a script from default search and blocks replay; saving it
again restores it. Candidates expire after 7 days of inactivity, capped at 200;
saved and archived scripts persist. Identical source is deduplicated by SHA-256;
name, validation flag and saved state survive recapture. Usage counters track
successful explicit replay, not visual verification. Changing code requires a new
execution/candidate and therefore a new ID.

SQLite state lives in `<AE2Claude root>/state/script-library/` (git-ignored), or
`AE2CLAUDE_LIBRARY_DIR`. It opens only when a library operation/capture is needed.
`AE2CLAUDE_CAPTURE_SCRIPTS=0` disables automatic capture. No script outputs are
stored. Source above 1 MB or matching the conservative credential filter is not
captured; the filter is not an exhaustive secret detector. Treat saved source as
private local data. Explicit script-reported `ok:false`, `success:false`, false,
or `outcome:unknown` is not captured. Exceptions/timeouts are not captured or
automatically retried. Storage failure returns a capture warning instead of turning
a completed AE write into a retryable tool failure.

The existing `ae_scripts` / `ae_run_script` registered catalog remains available;
the new library supplements it rather than overwriting bundled tools.
