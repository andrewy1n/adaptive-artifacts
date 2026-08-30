# State
as_of: 2026-08-30 @ 0000000

## Goal
Ship v0.1 of adaptive-artifacts: a dual-platform extension that designs, enforces, and evolves per-project artifact systems.

## Now
Extension core exists, wired project-locally: skills `adaptive-artifacts` (runtime), `init-artifacts`, `improve-artifacts`; primitives + seven presets; `tools/lint.py` and `tools/new_entry.py` (Python 3.8+, stdlib); session-start/stop hooks for Cursor and Claude Code (`.cursor/hooks.json`, `hooks/hooks.json`, `.claude-plugin/plugin.json`). README covers install and the Cursor bug that drops `sessionStart` `additional_context` — discovery is the rule pointer, not the hook. Not a git repo, so append-only lint and `head_commit` freshness are inert (`0000000` placeholder). No tests. This repo now dogfoods its own system: schemas, snapshots, and pointers written this session.

## Next
1. Mechanical tests for `tools/lint.py` (required fields, budget, manifest cross-check, append-only once git exists, id gaps).
2. Tests for `tools/new_entry.py`.
3. `git init` so ledger append-only and manifest staleness actually run.
4. Cross-session skill tests: routing to empty set, cold-read, resume-with-trap.
5. Promote from project-local to user-wide / Claude plugin install after those survive.

## Open
- Cursor `sessionStart` still drops `additional_context` (platform); stop hook works. Workaround is `.cursor/rules/artifacts.mdc`.
- Not a git repository — `head_commit` is `0000000` until first commit.
