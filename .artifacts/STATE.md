# State
as_of: 2026-08-30 @ 62a0cc4db2d9

## Goal
Ship v0.1 of adaptive-artifacts: a dual-platform extension that designs, enforces, and evolves per-project artifact systems.

## Now
Repo is git-backed (first commits this session), so append-only lint and manifest staleness are live. Test suite exists and passes: 22 tests in `tests/` covering `tools/lint.py` (required fields, budgets, manifest cross-checks, append-only for file and collection ledgers, archive moves, id gaps/dupes, staleness) and `tools/new_entry.py` (next-id, file append, snapshot refusal). Staleness semantics fixed: stale only when commits since `head_commit` touch files outside `.artifacts/` (see FRICTION.md #1). Extension amended: `findings` preset for standalone positive research knowledge, plus a "durable knowledge" role in init-artifacts (FRICTION.md #2); improve-artifacts stripped to project redesign only, extension-amendment process moved to repo-local CONTRIBUTING.md pointed from CLAUDE.md (FRICTION.md #3, #4). Otherwise three skills, primitives + presets, hooks wired for Cursor and Claude Code.

## Next
1. Routing smoke: trivial one-file task in a fresh session routes to no artifacts.
2. Resume-with-trap: session 2 does not re-attempt a logged dead end.
3. Drift check: State rewritten at session end without human reminder (hooks).
4. User-wide Cursor install + Claude Code plugin load after the above pass.

## Open
- Cursor `sessionStart` still drops `additional_context` (platform bug); discovery relies on `.cursor/rules/artifacts.mdc`, stop hook works.
