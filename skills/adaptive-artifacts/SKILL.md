---
name: adaptive-artifacts
description: >-
  Maintain a project's designed artifact system: structured files under
  .artifacts/ defined by the project's own schema registry, letting work
  survive across sessions and agents. Use when a project has an .artifacts/
  directory, when starting or resuming multi-session project work, when an
  approach is abandoned or a dead end is hit, at session end, when verifying
  a milestone, or when the user mentions artifacts, project memory, handoff,
  or resuming work.
---

# Adaptive Artifacts (runtime)

Projects carry structured artifacts under `.artifacts/`, with types
**designed per project** from fixed primitives. The design lives in the
project itself: `.artifacts/schemas/*.json` defines every type's fields,
discipline, and layout. This skill is the runtime discipline for working
inside an already-designed system. Designing one is `init-artifacts`;
changing a design is `improve-artifacts`.

The artifact is the primary record; narrative (PR descriptions, status
reports) is compiled *from* it.

## Session start (mandatory)

1. If `.artifacts/MANIFEST.md` exists, read it (a session-start hook may
   have injected it — don't re-read if in context). It lists types, paths,
   schemas, tools, and the `head_commit` staleness stamp.
2. If `head_commit` doesn't match current `HEAD`, don't trust snapshot
   artifacts — diff them against reality (git log since that commit, the
   files they mention) before acting on them.
3. Read a type's schema in `.artifacts/schemas/` before writing that
   artifact. Load artifact content on relevance only; never bulk-read.
4. No `.artifacts/` and work looks multi-session? Suggest `init-artifacts`
   to the user, or proceed without artifacts — **having none is a correct
   state**, not a deficiency to fix silently.

## Working discipline

**Snapshots** (rewritten-in-place types): keep within `budget_lines`; carry
`as_of: <date> @ <commit>`; write for a cold reader — position, not
activity narration.

**Ledgers** (append-only types): write entries **at the moment of the
event** — an abandoned approach is logged before starting the next one, a
claim is grounded while its output is still in context. Never edit,
renumber, or delete committed entries; never backfill from memory. Lint
enforces this against git history.

Scaffold ledger entries with the extension's tool (next id + field
skeleton):

```bash
python3 <extension>/tools/new_entry.py <type> --title "short title" --root <project>
```

**Project tools:** the manifest's Tools section lists project-specific
tools (queries, compiled views, capture helpers). Use them; a tool not
listed there does not exist. Read-only tools may be added freely; tools
that *write* artifacts must produce lint-clean output.

## Session end (mandatory)

1. Rewrite the project's state-role snapshot per its schema.
2. Update `MANIFEST.md`: `head_commit` to current HEAD, `updated` date.
3. Run lint; fix errors before finishing (the stop hook re-checks):

```bash
python3 <extension>/tools/lint.py --root <project>
```

## Escalation and change boundaries

- Instantiating a type that is already designed (schema exists) or adding
  one **from a preset unmodified** mid-work: allowed — write the schema
  JSON, add the manifest row, proceed.
- Designing a *new or modified* type mid-task: not allowed. Note the need
  in the friction ledger and raise it with the user; design happens in
  `init-artifacts` / `improve-artifacts` with human review.
- Schemas are never edited mid-task, in any direction. If a schema chafes,
  append to the friction ledger and **follow it anyway**.
- Verification gates use blinded subagents per
  [primitives/gate.md](primitives/gate.md) — the verifier gets the bar and
  snapshot paths only, never parent conversation or evidence. Never
  relaxed.

## Reference

Primitives (fixed rules of the system):
[schema-format](primitives/schema-format.md) ·
[disciplines](primitives/disciplines.md) ·
[layouts](primitives/layouts.md) ·
[manifest](primitives/manifest.md) ·
[gate](primitives/gate.md)

Presets (starting points for common types):
[state](presets/state.md) · [scope](presets/scope.md) ·
[plan](presets/plan.md) · [failures](presets/failures.md) ·
[evidence](presets/evidence.md) · [verification](presets/verification.md) ·
[friction](presets/friction.md)
