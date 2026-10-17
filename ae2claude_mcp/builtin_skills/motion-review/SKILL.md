---
name: motion-review
description: Review keyframe interpolation, easing and spatial tangents in a composition; report animation QC hints without changing keys.
version: "1.0.0"
requires: [get_keyframe_qc_targets, get_native_keyframes]
allowed_tools: [get_keyframe_qc_targets, get_native_keyframes, project_info, comp_info, get_selected_layers]
read_only: true
---

# Motion review

Use `ae_skill_run` to inspect the active composition or a supplied `comp_id`.
Discover animated property paths, then read native keyframe pages with stable
composition/layer IDs. Native key indices are zero-based. Native interpolation
uses 1=linear, 2=Bezier, 3=hold; ease influence is a fraction, not UI percent.

Review mixed interpolation, inconsistent segment endpoints, invalid temporal
ease, asymmetric speed/influence, dense key spacing and spatial corners. Baked
animation, holds, sharp corners and asymmetric acceleration may be intentional.
Label heuristic findings accordingly; do not claim they prove a visible defect.

Report only; never smooth, remove or replace keys. Keep missing native support,
unsupported streams and truncated discovery/key pages visible. This checks one
composition's numeric native streams, not nested comps, shape/text animation,
expressions or rendered motion. A clean numerical report does not establish
visual quality.
