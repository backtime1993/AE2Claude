---
name: pv-preflight
description: Check PV project delivery readiness, dependencies and composition settings; report without modifying the project.
version: "1.0.0"
requires: [get_preflight_snapshot]
allowed_tools: [get_preflight_snapshot, project_info, comp_info, get_selected_layers]
read_only: true
---

# PV preflight

Use `ae_skill_run` for a reproducible report. Review all project compositions,
missing footage/proxies, substituted fonts, enabled expression errors, delivery
frame rates, work areas, composition names, output paths and unused footage.
Check the project working space against a supplied delivery requirement.

## Customize for delivery

Pass `allowed_fps` and `expected_working_space` in runner options when the
delivery standard is known. Common frame rates alone do not establish a
project's intended delivery. A short layer, unused asset or unassigned working
space may be intentional; treat it as a review hint rather than an error.

## Boundaries and evidence

Report only; do not repair, delete, rename, save or render. Missing checks,
unsupported APIs and traversal limits must stay visible. Project-wide claims
require project-wide coverage. Expressions are sampled at each composition's
current time; this is not proof that every frame evaluates correctly. Imported
footage/output color profiles are outside the automated check.

Separate clear errors, review warnings and informational notes. Include stable
IDs, property paths, coverage and limitations. Never describe a fix as verified
without a fresh read; this Skill itself makes no fixes.
