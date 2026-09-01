# Changing the extension

This document is for work **on this repo** — amending the extension's
primitives, presets, shared tools, or hooks. It does not ship with the
extension. Redesigning an individual project's artifact system is the
`improve-artifacts` skill, not this.

The dividing line: a fix needed by one project is a project redesign; the
same fix appearing in every project's redesign is a preset or primitive
amendment, made here.

## Rules

**Evidence-gated.** Every change cites friction entries (this repo's
dogfood ledger or project ledgers the user points at) or concrete observed
use. Proposals without evidence are rejected by default — expect most
friction entries to be rejected; a healthy system anneals.

**Rigor asymmetry.** Changes that reduce rigor — removing required fields,
weakening append-only or at-the-moment rules, relaxing verifier blindness,
loosening lint — require explicit human sign-off, named as rigor-reducing.

**Human-approved.** Amendments happen in an explicit session with review,
never silently mid-task.

## Workflow

1. Gather evidence: friction ledgers, recurring project-redesign patterns.
2. Propose changes by target, in rising order of bar:
   - **shared tools / hooks** — behavior; test before shipping
   - **presets** — defaults new projects design from
   - **primitives** — conventions; highest bar: lint and every existing
     project depend on them
3. Apply after approval. Convention changes require a corresponding
   `tools/lint.py` change and a note in the affected primitive doc — the
   spec and the enforcer move together or not at all.
4. Convention changes only: add a short changelog line at the bottom of
   the amended primitive doc — installed copies carry no git history, and
   a project designed under the old convention is otherwise undebuggable.
   Additive changes (new presets, new tools) get no note; this repo's git
   history suffices.
