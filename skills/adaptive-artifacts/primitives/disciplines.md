# Disciplines: snapshot vs ledger

Every artifact type declares one. They fail differently and are maintained
differently — the distinction is structural, not stylistic.

## Snapshot

Rewritten in place; represents *current* truth. Examples: state, scope,
plan.

- Bounded: give session-read snapshots a `budget_lines`; when exceeded,
  compress or push detail elsewhere — the read tax recurs every session
- Rots: staleness is the failure mode. Carry an `as_of: <date> @ <commit>`
  line near the top; distrust on commit mismatch
- Written for a cold reader: no "the approach we discussed" — name it

## Ledger

Append-only; represents *history that must not be sanitized*. Examples:
failures, evidence, verification results, friction.

- Never edit, reword, renumber, or delete an existing entry — lint compares
  against git history and errors on any modification
- Written at the moment of the event (abandonment, claim, gate), never
  retroactively at session end: retrospective entries are rationalized
  fiction
- Never backfilled from memory when adopting artifacts mid-project
- Bloats: the failure mode is size. Archive by moving whole old entries to
  an `archive/` subdirectory — never by editing them

## Combining with layouts

All four combinations are valid: a snapshot collection is a folder of
rewritable docs (e.g. one plan file per phase); a ledger collection is a
folder of immutable entries (e.g. one file per failure). See layouts.md.
