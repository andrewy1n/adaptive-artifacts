---
name: improve-artifacts
description: >-
  Review a project's friction ledger and redesign its artifact system:
  amend the schema registry (.artifacts/schemas/) and project tools. Use
  only when the user explicitly asks to review friction or redesign
  artifact schemas, or invokes /improve-artifacts. Never used to edit a
  project's artifact contents.
disable-model-invocation: true
---

# Improve Artifacts (redesign session)

The only sanctioned path for changing a project's artifact design.
Deliberately not ambient: redesign machinery stays invisible during normal
work so rules cannot be rewritten mid-task.

Scope is the project: `.artifacts/schemas/*.json` and project tools,
evidenced by the project's friction ledger and observed use. Friction with
the extension itself (primitives, presets, shared tools, hooks) is out of
scope — leave it in the friction ledger and tell the user it needs an
upstream change to the extension.

## Rules

**Evidence-gated.** Every change cites friction entries or concrete
observed use. "Field was boilerplate in 9 of 11 entries" is an argument;
"feels cleaner" is not. Proposals without evidence are rejected by default
— expect most friction entries to be rejected; a healthy system anneals.

**Rigor asymmetry.** Changes that reduce rigor — removing required fields,
weakening append-only or at-the-moment rules, relaxing verifier blindness,
loosening lint — require explicit human sign-off, named as rigor-reducing.
The friction an agent feels is the friction of doing the work; the cost of
missing information lands on a future session that can't complain.

**Never retro-migrate ledgers.** Existing entries stay as written.
Snapshots may adopt a new schema at their next natural rewrite, not in a
bulk pass.

## Workflow

1. Read the project's friction ledger; group entries by design element,
   note frequency.
2. Propose per group: schema change (fields, layout, budgets, new/retired
   types), tool change, or rejection with reason.
3. Human approves; apply to `.artifacts/schemas/` with `version` bumped on
   any shape change.
4. Refresh affected project tools; a write-tool that now emits lint-invalid
   output is broken until fixed.
5. Run `tools/lint.py` — clean before finishing. Update the manifest.
