---
name: reassess-artifacts
description: >-
  Reassess a project's artifact design when its shape changes: new
  pattern types, views, bundles, occupancy, or gaps. Use only when the
  user explicitly asks to reassess or redesign artifacts, or invokes
  /reassess-artifacts. Never used to edit record contents.
disable-model-invocation: true
---

# Reassess Artifacts

The only sanctioned path for changing a project's design.
Deliberately not ambient: redesign stays invisible during normal work
so the contract cannot be rewritten mid-task.

Scope is the project's `project-design@0.3.0` document (`records`,
views, bundles, lock, occupancy, gaps). Amending this extension's
catalog, runtime, or hooks is out of scope — capture that friction
in this repo's store; apply only with human approval.

## When to reassess

Reassess when the project shape changes, not every session and not only
after failure:

- a single agent becomes multiple agents
- a prototype becomes a production system
- external research becomes a significant part of the work
- the repository becomes expensive to navigate
- an external platform becomes or stops being canonical
- sensitivity or role boundaries change
- concurrent writers are introduced
- recurring artifact friction exceeds the value of the current design
- a needed type should be declared from a pattern
- the user explicitly asks

## Rules

**Evidence-gated.** Cite shape-change evidence, recurring friction, or
a catalog version delta. "Feels cleaner" is not an argument. Expect
most proposed changes to be rejected; a healthy system anneals.

**Human-approved.** Produce a recommendation. Do not silently rewrite
the roster or re-init the store.

**No live inheritance.** Projects do not pick up later catalog versions
by existing. An upgrade is an explicit reassessment with a new
`source_lock`.

**Rigor asymmetry.** Weakening append-only occurrence rules, dropping
stewardship, or relaxing validation requires explicit human sign-off,
named as rigor-reducing.

**Do not retro-migrate occurrences.** Existing `recorded` events stay.
Current-claims may be superseded at their next natural change, not in a
bulk rewrite to match a new view parameter.

**`overrides` stay empty.** Recurring shared needs may be listed as
`gaps`. They do not block declaring a pattern type now.

## Workflow

1. Read the current project-design, its resolved contract, and why
   reassessment was triggered (evidence, not vibe).
2. Re-run the `design-artifacts` assessment against **current** shape.
   Compare project pattern records, views, and bundles.
3. Propose, per change: add/remove/change a pattern type, view, or
   bundle; view parameter change; occupancy change; new gap; or
   rejection with reason.
4. Human approves. Write a successor project-design. Fill `source_lock`
   from the tool (never by hand):

   ```bash
   adaptive-artifacts lock
   ```

5. Resolve the new design. It must succeed before finishing:

   ```bash
   adaptive-artifacts --root <project> resolve
   ```

6. If a live store exists, a contract-digest change is a rebind: the
   experimental `init` will not overwrite a store pinned to a different
   digest. Plan the store cutover with the human; do not delete the
   store as a side effect of editing JSON.

## Finish

Report: trigger, approved changes, rejected proposals, new types and
views, lock, store impact. Commit only if asked.
