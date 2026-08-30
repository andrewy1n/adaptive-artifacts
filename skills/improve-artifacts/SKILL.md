---
name: improve-artifacts
description: >-
  Review friction ledgers and amend artifact designs at two levels: redesign
  a project's artifact system (its schema registry and tools) or amend the
  adaptive-artifacts extension itself (primitives, presets, shared tools).
  Use only when the user explicitly asks to review friction, redesign or
  amend artifact schemas, or invokes /improve-artifacts. Never used to edit
  a project's artifact contents.
disable-model-invocation: true
---

# Improve Artifacts (redesign session)

The only sanctioned path for changing artifact designs. Deliberately not
ambient: amendment machinery stays invisible during normal work so rules
cannot be rewritten mid-task.

Two distinct levels — establish which one the user means first:

| Level | Target | Evidence |
|---|---|---|
| **Project redesign** | `.artifacts/schemas/*.json`, project tools | This project's friction ledger + observed use |
| **Extension amendment** | `primitives/`, `presets/`, shared `tools/`, hooks | Friction across projects; recurring redesigns pointing the same way |

A fix needed by one project is a redesign; the same fix appearing in every
project's redesign is a preset or primitive amendment.

## Shared rules (both levels)

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

## Project redesign workflow

1. Read the project's friction ledger; group entries by design element,
   note frequency.
2. Propose per group: schema change (fields, layout, budgets, new/retired
   types), tool change, or rejection with reason.
3. Human approves; apply to `.artifacts/schemas/` with `version` bumped on
   any shape change.
4. Refresh affected project tools; a write-tool that now emits lint-invalid
   output is broken until fixed.
5. Run `tools/lint.py` — clean before finishing. Update the manifest.

## Extension amendment workflow

1. Gather evidence: friction ledgers the user points at, plus any recurring
   project-redesign patterns.
2. Propose changes to primitives (conventions — highest bar: lint and every
   existing project depend on them), presets (defaults — moderate bar), or
   shared tools/hooks (behavior — test before shipping).
3. Human approves; apply in the extension repo. Convention changes require
   a corresponding `tools/lint.py` change and a note in the affected
   primitive doc — the spec and the enforcer move together or not at all.
4. Note what changed at the bottom of the amended file (short changelog
   line), so projects designed under older conventions are debuggable.
