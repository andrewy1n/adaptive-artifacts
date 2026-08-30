# Plan
as_of: 2026-08-30 @ 62a0cc4db2d9

## Objective
Validate v0.1 of the extension across session boundaries, then promote it from this repo's project-local wiring to something installable. Core (skills, primitives, presets, lint, hooks) already exists.

## Approach
Dogfood on this repo first (the system using itself), then mechanical tests for lint and the scaffolder, then the cross-session skill tests from the original build plan. Platform workarounds stay documented, not patched around. New types only via friction → `improve-artifacts`.

## Items
- [x] Dogfood init: `.artifacts/` designed, snapshots from present reality, discovery pointers planted
- [x] Tests for `tools/lint.py`: valid tree, missing required field, budget overrun, manifest/schema mismatch, append-only edit of a committed ledger entry, collection id duplicates/gaps, staleness semantics (18 tests)
- [x] Tests for `tools/new_entry.py`: collection next-id, single-file append, refuse snapshots (4 tests)
- [x] `git init` + first commits; `head_commit` and append-only lint live
- [ ] Routing smoke: trivial one-file task in a fresh session; pass = agent completes it creating no `.artifacts/` files and no manifest rows
- [x] Cold-read: fresh-context subagent restricted to `.artifacts/` reconstructed goal, position, next action, and ruled-out items; 4/5 self-rated confidence (2026-08-30)
- [ ] Resume-with-trap: session 2 does not re-attempt a logged dead end
- [ ] Drift check: State rewritten at session end without human reminder (hooks)
- [ ] User-wide Cursor install + Claude Code plugin load after the above pass

## Decisions
- Evidence and verification types omitted at init; add from presets unmodified when a non-automatable claim or named gate appears.
- Staleness = commits since `head_commit` touching files outside `.artifacts/`; artifact-only commits never count (FRICTION.md #1, applied at extension level).
