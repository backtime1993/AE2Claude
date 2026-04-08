# AE2Claude v3.0 — Atomic API Redesign

## Summary

Breaking restructure of ae_bridge.py (~65 methods → ~50) based on two principles from brandkickagency/aftereffects-mcp:
1. **Atomic operations** — one method = one AE logical action
2. **Agent orchestrates** — loops, filtering, composition of calls belong to the Agent, not the bridge

Version bump: v2.0.0 → v3.0.0 (breaking, no deprecation shims).

## Design Principles

### P1: One method = one AE logical action
- Creating a text layer only creates it. Setting font/color is a separate call.
- Adding an effect only adds it. Setting props/keyframes are separate calls.
- Setting keyframes only sets keyframes. Easing is a separate call.

### P2: Agent orchestrates, bridge executes
- Bridge does NOT loop over layers, filter by name/prefix, or combine multiple unrelated operations.
- `render_comp` (add_to_queue + set_output + start_render) is Agent's job.
- `remove_layers_by_prefix` (list + filter + remove loop) is Agent's job.
- `batch_jsx` (bundling multiple JSX scripts) is Agent's job.
- Default parameter lists (apply_easing defaulting to 3 properties) are removed — Agent decides explicitly.

### P3: Semantic property names, hide AE internals
- Agent says `"position"`, `"opacity"`, `"scale"` — never AE property paths.
- Bridge maintains `PROP_MAP: semantic_name → AE_path` internally.
- Unknown prop names are NOT transparently passed through. Raw AE access only via `run_jsx`.
- Effect properties use `effect_index` + `prop_key` from the EFFECTS registry, no invented DSL.

## Method Inventory by Domain

### Comp (6 methods)

| Method | Signature | Notes |
|--------|-----------|-------|
| `create_comp` | `(name, width, height, duration, fps)` | unchanged |
| `comp_info` | `()` | unchanged |
| `list_comps` | `()` | unchanged |
| `set_active_comp` | `(name)` | unchanged |
| `set_active_comp_by_id` | `(comp_id)` | unchanged |
| `project_info` | `()` | unchanged, project-level query |

### Layer (18 methods)

| Method | Signature | Change |
|--------|-----------|--------|
| `add_text_layer` | `(text, name=None)` | **slimmed**: removed font/color/timing/label params |
| `add_shape_layer` | `(name=None, label=None)` | unchanged |
| `add_solid` | `(name, color, width=None, height=None)` | **new** |
| `create_null_control` | `(name=None, ...)` | unchanged |
| `create_camera` | `(name, type, zoom, ...)` | unchanged |
| `create_light` | `(name, type, intensity, ...)` | unchanged |
| `remove_layer` | `(name)` | unchanged |
| `rename_layer` | `(old_name, new_name)` | unchanged |
| `set_layer_timing` | `(name, start, end, ...)` | unchanged |
| `set_layer_label` | `(name, label)` | unchanged |
| `set_3d_layer` | `(name, enabled)` | unchanged |
| `set_blending_mode` | `(name, mode)` | unchanged |
| `get_blending_mode` | `(name)` | unchanged |
| `duplicate_layer` | `(name)` | unchanged |
| `reorder_layer` | `(name, new_index)` | unchanged |
| `set_parent` / `remove_parent` / `get_parent` | `(name, ...)` | unchanged |
| `set_layer_selected` | `(name, selected: bool)` | **new**: replaces `select_layers(names: List)` |
| `deselect_all` | `()` | kept — single AE action, not orchestration |

**Query methods (kept):**
- `list_layers`, `get_layer_info`, `get_layer_by_id`, `get_selected_layers`

**Removed:**
- ~~`remove_layers_by_prefix`~~ → Agent: list_layers → filter → remove_layer loop
- ~~`layer_exists`~~ → Agent: list_layers → check in result
- ~~`select_layers(names: List)`~~ → replaced by `set_layer_selected` per-layer

### Transform (5 methods, merged from ~10)

| Method | Signature | Change |
|--------|-----------|--------|
| `set_value` | `(name, prop, value, at_time=None)` | **new**: unified setter |
| `get_value` | `(name, prop, at_time=None)` | **merged** from `get_transform_value` + `get_property_value` |
| `set_keyframes` | `(name, prop, keyframes)` | **merged** from 4 specific + 1 generic set_*_keyframes |
| `get_keyframes` | `(name, prop)` | **merged** from `get_keyframes` + `get_property_keyframes` |
| `center_anchor` | `(name, at_time=0)` | kept — has sourceRectAtTime geometry calculation |

`prop` uses semantic names resolved via internal `PROP_MAP`:
```python
PROP_MAP = {
    "position":     'property("Transform").property("Position")',
    "scale":        'property("Transform").property("Scale")',
    "rotation":     'property("Transform").property("Rotation")',
    "opacity":      'property("Transform").property("Opacity")',
    "anchor_point": 'property("Transform").property("Anchor Point")',
}
```
Unknown prop names raise an error. No transparent passthrough.

**Removed:**
- ~~`set_position_keyframes`~~ / ~~`set_opacity_keyframes`~~ / ~~`set_scale_keyframes`~~ / ~~`set_rotation_keyframes`~~ → `set_keyframes`
- ~~`set_property_keyframes`~~ → `set_keyframes` (but only for known props)
- ~~`get_transform_value`~~ / ~~`get_property_value`~~ → `get_value`
- ~~`get_property_keyframes`~~ → `get_keyframes`

### Effect (7 methods)

| Method | Signature | Change |
|--------|-----------|--------|
| `add_effect` | `(name, effect_type) → effect_index` | **slimmed**: returns index, no props/keyframes |
| `set_effect_props` | `(name, effect_index, props)` | **new**: split from add_effect |
| `set_effect_keyframes` | `(name, effect_index, keyframes)` | **new**: split from add_effect |
| `get_effect_param` | `(name, effect_index, prop_key)` | **changed**: uses effect_index instead of matchName |
| `get_effect_keyframes` | `(name, effect_index, prop_key)` | **changed**: uses effect_index |
| `enumerate_effects` | `(name)` | unchanged — returns index/name/matchName list |
| `list_available_effects` / `describe_effect` | | unchanged — discovery/query |

Key change: all effect operations use `effect_index` (returned by `add_effect` or discovered via `enumerate_effects`) instead of `effect_type` string. This correctly handles multiple same-type effects on one layer.

### Easing (2 methods, split by target type)

| Method | Signature | Change |
|--------|-----------|--------|
| `apply_transform_easing` | `(name, prop, speed=0, influence=80)` | **new**: single-prop, semantic prop name |
| `apply_effect_easing` | `(name, effect_index, prop_key, speed=0, influence=80)` | **renamed**: uses effect_index |

No polymorphism, no DSL. Two separate methods with different signatures.

**Removed:**
- ~~`apply_easing(properties: List)`~~ → Agent calls `apply_transform_easing` per-prop

### Mask (8 methods)

| Method | Signature | Change |
|--------|-----------|--------|
| `add_mask` | `(name, vertices, ...)` | unchanged |
| `set_mask_path` | `(name, mask_index, vertices, ...)` | unchanged |
| `set_mask_feather` | `(name, mask_index, feather)` | unchanged |
| `set_mask_opacity` | `(name, mask_index, opacity)` | unchanged |
| `set_mask_expansion` | `(name, mask_index, expansion)` | unchanged |
| `animate_mask_path` | `(name, mask_index, keyframes)` | unchanged |
| `remove_mask` | `(name, mask_index)` | unchanged |
| `list_masks` | `(name)` | unchanged |

**Removed:**
- ~~`add_mask_rect`~~ / ~~`add_mask_ellipse`~~ → syntactic sugar, Agent computes vertices

### Text (5 methods)

| Method | Signature | Change |
|--------|-----------|--------|
| `set_text_content` | `(name, text)` | **new**: change text without recreating layer |
| `set_text_style` | `(name, font, size, fill_color, stroke_color, stroke_width, justification)` | **new**: split from add_text_layer |
| `add_text_animator` | `(name, properties)` | unchanged |
| `set_text_animator_selector` | `(name, animator_index, start, end, offset, shape, based_on, mode)` | unchanged |
| `animate_text_selector` | `(name, animator_index, selector_index, keyframes)` | unchanged |

### Render (5 methods)

| Method | Signature | Change |
|--------|-----------|--------|
| `add_to_render_queue` | `(comp_name, output_path, template)` | unchanged |
| `set_render_output` | `(rq_index, output_path, template)` | unchanged |
| `remove_render_item` | `(rq_index)` | unchanged |
| `clear_render_queue` | `()` | unchanged |
| `start_render` | `()` | unchanged |
| `render_queue_info` | `()` | unchanged, query |

**Removed:**
- ~~`render_comp`~~ → Agent orchestrates: add_to_queue → set_output → start_render

### Other (kept as-is)

| Method | Reason |
|--------|--------|
| `run_jsx` / `run_jsx_checked` | escape hatch |
| `exec_jsx_file` | execute external JSX files |
| `begin_undo` / `end_undo` | AE-specific, Agent cannot replace |
| `import_file` | AE-specific |
| `precompose` / `precompose_by_index` / `list_precomps` / `open_precomp` / `add_comp_to_comp` | comp nesting |
| `set_track_matte` / `remove_track_matte` | track matte |
| `set_expression` / `clear_expression` | expressions |
| `enable_time_remap` / `set_time_remap_keyframes` / `freeze_frame` / `reverse_layer` | time remap |
| `sample_pixel` / `sample_pixels` | pixel sampling |
| `add_layer_marker` / `list_layer_markers` / `remove_layer_marker` | markers |
| `add_comp_marker` / `list_comp_markers` / `remove_comp_marker` | markers |
| `set_camera_property` / `set_light_property` | camera/light props |

### Experimental (clearly marked)

| Method | Reason |
|--------|--------|
| `add_layer_style` | AE returns ERR:not_scriptable for most styles |
| `enable_layer_style` | same limitation |

These will be kept but clearly documented as `@experimental` — may not work, use at own risk.

### Removed (no replacement)

| Method | Reason |
|--------|--------|
| ~~`batch_jsx`~~ | Agent orchestration — Agent decides call sequence |
| ~~`render_comp`~~ | Agent orchestration — Agent chains the 3 atomic calls |
| ~~`remove_layers_by_prefix`~~ | Agent orchestration — Agent lists, filters, removes |
| ~~`layer_exists`~~ | Agent can derive from list_layers |
| ~~`select_layers(names)`~~ | Replaced by per-layer `set_layer_selected` |
| ~~`add_mask_rect`~~ | Syntactic sugar for add_mask |
| ~~`add_mask_ellipse`~~ | Syntactic sugar for add_mask |

## Summary Table

| Domain | v2 count | v3 count | Net |
|--------|----------|----------|-----|
| Comp | 6 | 6 | 0 |
| Layer | 18 | 18 | 0 |
| Transform | 10 | 5 | -5 |
| Effect | 6 | 7 | +1 |
| Easing | 2 | 2 | 0 |
| Mask | 8 | 8 | 0 |  
| Text | 3 | 5 | +2 |
| Render | 6 | 6 | 0 |
| Other | 28 | 28 | 0 |
| Experimental | 2 | 2 | 0 |
| **Total** | **~65** | **~50** | **-15** |

Removed: 15 methods (fat methods split into new atomics + orchestration methods + syntactic sugar)
New: 7 methods (set_text_content, set_text_style, add_solid, set_layer_selected, set_effect_props, set_effect_keyframes, apply_transform_easing)
Merged: 7→2 (keyframe read/write unified)

## CLI Impact

`~/bin/ae2claude` CLI shell must be rewritten to match new signatures:
- `ae2claude call set_keyframes <layer> <prop> <kf_json>` replaces 4 separate keyframe commands
- `ae2claude call add_effect <layer> <type>` no longer accepts inline props
- `ae2claude call set_effect_props <layer> <effect_index> <props_json>` is new
- All effect commands now require `effect_index` instead of `effect_type`

## Migration Notes

- No backward compatibility shims. Clean break.
- ae2claude-bridge skill must be updated to use new method names.
- EFFECTS registry (matchName mapping) is unchanged — only the method signatures around it change.
- PROP_MAP is new internal infrastructure — Agent never sees AE paths.
- `_esc()` helper and Dialog Dismisser are unchanged infrastructure.
