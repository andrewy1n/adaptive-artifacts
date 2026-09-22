---
name: artifact-runtime
description: >-
  Maintain a project's designed artifact system: pattern types, semantic
  records, and derived views so work survives across sessions and agents.
  Use when a project has a project-design contract or a record store, when
  starting or resuming multi-session work, when an approach is abandoned,
  at session end, or when the user mentions artifacts, handoff, or
  resuming work.
---

# Artifact Runtime

This is the runtime discipline for an already-designed system.
Designing one is `design-artifacts`; changing a design is
`reassess-artifacts`.

Records are the authority. Views (handoff, investigation summary, status
narrative) are derived — regenerate them; do not edit view files as if
they were source.

## Detect the project state

1. **Live record store** (`.artifacts/` with `meta.json`) —
   follow Session start below.
2. **Design only** (`.artifacts/project-design.json`, no `meta.json`) —
   the design is the contract; do not invent a parallel note system.
   Suggest store init only if the user wants a live store.
3. **Neither** — having none is correct. If the work looks multi-session,
   suggest `design-artifacts`; otherwise proceed without artifacts.

## Session start (mandatory when a store exists)

1. If views were not injected, generate them:

   ```bash
   adaptive-artifacts hook-start
   ```

   Read the derived views (also under `.artifacts/views/` after a start
   hook). Do not re-read if they are already in context.
2. Route other records by relevance. Never bulk-read the store.
3. Treat views as stale relative to records. If you will act on a
   current-claim, prefer the record over a view that might lag.

## Working discipline

Capture at the information-loss boundary — when the event, observation,
decision, or commitment happens, not at session end from memory.

Shipped CLI (`adaptive-artifacts`, wrapping `tools/artifacts.py`; `--root` defaults to cwd):

| Need | Command |
|---|---|
| new current-claim, question, finding | `create --type <project:name> --subject … --payload '…'` |
| replace a current-claim | `supersede --type … --id … --expected-revision … --payload '…'` |
| lifecycle transition (question answered, …) | `update --type … --id … --transition … --expected-revision …` |
| correct an occurrence | `correct --type … --id … --payload '…'` |
| contradict a finding | `contradict --type … --id … --payload '…'` |
| multi-record write set | `capture --bundle <project:name> --records '[…]'` |

Rules that follow from the contract:

- Supersede current-claims with a new id; do not `update` them to
  `superseded`.
- Occurrences stay `recorded`. Correction writes a successor with
  `corrects`; do not mutate the original.
- Contradiction is a separate finding plus an epistemic transition, not
  an occurrence correction.
- Bundles are capture templates, not transactions or authorities.
- Follow the record's lifecycle. Illegal transitions fail validation.
- Conditional writes need `--expected-revision`. A stale revision is a
  rejected write, not a prompt to hand-edit files.

## Session end (mandatory when facts changed)

1. Write or supersede the records whose facts changed. Do not rewrite
   unchanged current-claims for ceremony.
2. Regenerate views:

   ```bash
   adaptive-artifacts handoff --out views/handoff.md
   adaptive-artifacts view --id project:investigation-summary --out views/investigation-summary.md
   adaptive-artifacts hook-stop
   ```

3. Fix validation errors before finishing.

## Escalation and change boundaries

- Instantiating a record type that is already in the resolved contract:
  allowed.
- Adding a type, changing occupancy, or editing the design: not allowed
  mid-task. Note the need and raise it; design happens in
  `reassess-artifacts` with human review.
- Traits, backends, and shipped skills are not edited mid-task.
  Recurring friction with the extension itself is captured in this
  repo's store and raised for human approval, not a project redesign.
- If the contract chafes, follow it anyway.

## Reference

- Design model (experimental): [design/DESIGN.md](../../design/DESIGN.md)
- Contract format: [design/contracts/README.md](../../design/contracts/README.md)
- Runtime: `adaptive-artifacts` (wraps `tools/artifacts.py`)
