# PV production authoring

These operations reuse AE2Claude's current bridge and the host's scripting DOM;
they do not require Adobe AI Assistant or access its private tools. Host support
is checked at invocation. `ae_capabilities(category="production")` discovers the
bridge getters, `set_production` and `export_mogrt`. MCP clients can use
`ae_production(action, options, dry_run=true, confirm=false)` directly.

Every edit defaults to a host-side plan. Apply the reviewed options with
`dry_run=false`; the configured write policy still applies. Read-only mode permits
MCP plans but blocks edits. An export also requires `confirm=true` in auto mode.
Unknown/failed writes must be inspected before retrying: an undo group is not a
transaction or automatic rollback. Never retry `outcome="unknown"` blindly.

Use stable composition IDs (`comp_id`; 0 means active composition) and layer IDs
(`layer: {"id":123}`). Layer selectors also accept unique names or one-based
`{"index":1}`. Property paths contain matchNames and **zero-based** indexed-group
steps. Key indices and shape move indices are zero-based. **EGP controller indices
are one-based.** Shape paths are relative to Contents; Essential Property paths
are relative to the precomp layer's Essential Properties. Other paths start at
the layer. Always refresh paths after adding, moving or removing properties.

## Actions and options

All actions accept `comp_id`; folder/project organization does not need a comp.

| Action | Additional options | Result / constraint |
|---|---|---|
| `essential_graphics` | none | Read template name, controller names/indices |
| `template_settings` | `name` | Set the MOGRT name |
| `expose_control` | `layer`, `path` (empty for eligible media layer), optional `name` | Check eligibility before adding a named control |
| `rename_control` | `index`, `name` | Rename an existing EGP control and read back |
| `essential_properties` | `layer`, optional `max_nodes` (default 512, max 4096) | Bounded property tree, source links and media replacement eligibility |
| `essential_property` | `layer`, `path`, exactly one of `value` or `alternate_source_id`; optional `time` | Set a scriptable scalar/vector value or compatible media item; animated values require time; expression-driven values rejected. Source Text formatting uses `text_range` in the source comp. |
| `export_mogrt` | optional `output_dir`, `overwrite` (false) | Requires a saved clean project and existing destination; reports actual nonempty file. No automatic save. |
| `shape_contents` | `layer`, optional `max_nodes` | Bounded shape tree with paths, names and values |
| `shape_operator` | `layer`, `path`, `operation`; add: `match_name`/optional `name`; rename: `name`; move: `index`; enable: `enabled`; remove: no extra field | Add/remove/rename/move/enable groups, shapes, fills/strokes and operators. Add to root uses `path:[]`. |
| `stroke_dashes` | `layer`, stroke `path`, `dashes` (0–6 alternating dash/gap lengths), optional `offset` | Replace static dashes; refuses animated/expression-driven dash slots |
| `text_range` | `layer`, `start`, `end`, `text`; optional `key_index` | Replace the half-open UTF-16 range through CharacterRange (AE 24.3+), preserving surrounding styles; refuses split surrogate pairs and expressions. Animated text requires an explicit key index. |
| `keyframe_interpolation` | `layer`, `path`, `key_indices`, `in_type`, optional `out_type`, `temporal_auto_bezier`, `temporal_continuous` | linear/bezier/hold; validates all indices first. Use existing native ease API for speed/influence/spatial tangents. |
| `create_folder` | `name`, optional `parent_id` (0 = project root) | Reuses one matching folder; never creates duplicate folders on retry |
| `project_items` | `changes:[{item_id,name?,folder_id?}]`, optional `fix_expressions` (true) | Explicit rename/reparent plan, cycle checks and conservative expression-name collision checks. No deleting unused footage or automatic classification. |
| `render_output` | optional `output_path`, `render_template`, `output_template`, `overwrite` (false) | Adds one queue item and reads actual output path; template failure removes only the new item. Existing output is refused by default. Does not start rendering. |

With omitted output path, `render_output` picks an unused .mov filename next to
the saved AEP. Prefer an explicit project delivery path and templates verified
on the current host. A template can change the final extension; use the returned
path. The plan cannot validate template names without creating a queue item;
apply validates them and removes the new item on failure. Do not infer codec,
alpha, audio or color settings from the filename. Read the actual output module.

## Examples

```python
# MCP: inspect, plan, then apply an authorized local edit.
ae_production("essential_graphics", {"comp_id": 100})
ae_production("text_range", {
    "comp_id": 100, "layer": {"id": 200}, "start": 4, "end": 7, "text": "新版"
})
ae_production("text_range", {
    "comp_id": 100, "layer": {"id": 200}, "start": 4, "end": 7, "text": "新版"
}, dry_run=False, confirm=True)
```

If an existing chat has not reloaded `ae_production`, use its generic `ae_call`
with bridge methods `get_essential_graphics`, `get_essential_properties`,
`get_shape_contents`, `set_production`, or `export_mogrt`. The generic call policy
is conservative: a write-classified method requires write permission even for
a plan. The CLI accepts `ae2claude call set_production --kwargs '<JSON>'`;
for quote-heavy payloads prefer a Python script that reads JSON from a file and
calls `AEBridge.set_production(...)` directly.
Do not send code in JSON option fields; use existing safe JSX only for operations
that the structured surface cannot express.

`start_render` remains capability-tested and asynchronous. It starts the host
queue, so first inspect and isolate the requested queue items. Follow progress
with `get_render_status`; success means DONE **and** a readable output with the
expected duration, dimensions, codec and appearance. Queue submission is not a
finished export. Do not fall back to synchronous `renderQueue.render()`.

## Validation

`python -m unittest tests.test_production` checks input/policy boundaries, folder
cycles, all-key preflight, Unicode transport and render collision/rollback.
`tests.test_production_live` is explicitly opt-in, refuses nonempty/saved projects,
exercises all seven groups in the real host, exports a MOGRT and a short movie,
and returns the initially empty project to an empty state. Set
`AE2CLAUDE_PRODUCTION_LIVE_TEST=1` and a fresh `AE2CLAUDE_PRODUCTION_TEST_DIR`.
This test does not prove Premiere import compatibility or exercise every possible
font, effect, media replacement source or output-module template.
