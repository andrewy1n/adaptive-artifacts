# Plan
as_of: 2026-08-30 @ 0000000

## Objective
Validate v0.1 of the extension across session boundaries, then promote it from this repo's project-local wiring to something installable. Core (skills, primitives, presets, lint, hooks) already exists.

## Approach
Dogfood on this repo first (the system using itself), then mechanical tests for lint and the scaffolder, then the cross-session skill tests from the original build plan. Platform workarounds stay documented, not patched around. New types only via friction → `improve-artifacts`.

## Items
- [x] Dogfood init: `.artifacts/` designed, snapshots from present reality, discovery pointers planted
- [ ] Tests for `tools/lint.py`: valid tree, missing required field, budget overrun, manifest/schema mismatch, append-only edit of a committed ledger entry, collection id duplicates/gaps
- [ ] Tests for `tools/new_entry.py`: collection next-id, single-file append, refuse snapshots
- [ ] `git init` so `head_commit` and append-only lint are live
- [ ] Routing smoke: trivial one-file task routes to no artifacts
- [ ] Cold-read: fresh session reconstructs position from artifacts only
- [ ] Resume-with-trap: session 2 does not re-attempt a logged dead end
- [ ] Drift check: State rewritten at session end without human reminder (hooks)
- [ ] User-wide Cursor install + Claude Code plugin load after the above pass

## Decisions
- Evidence and verification types omitted at init; add from presets unmodified when a non-automatable claim or named gate appears.
- `head_commit` is `0000000` until the repo has git.
