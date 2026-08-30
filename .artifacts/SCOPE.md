# Scope
as_of: 2026-08-30 @ 0000000

## What
adaptive-artifacts is a Cursor and Claude Code extension that lets an agent design a project-specific artifact system from fixed primitives (disciplines, layouts, schema format, manifest, gates), freeze it as an in-repo schema registry, and enforce it with lint and session hooks. Agents continuing the work are the audience; humans review design sessions. Rationale: `IDEA.md`.

## Out of scope
- Interop with GSD, Memory Bank, or other existing artifact systems (v1 is the general core; they are specialized instances).
- Concurrency: single-writer; parallel-worktree snapshot merge is unsolved.
- Metrics or an eval harness; evaluation is informal judgment and felt friction.
- Documentation/wiki for readers who weren't part of the work; transcript archives; substituting for git history.
- Marketplace / packaged distribution until dogfood and tests survive.
- Designing new artifact types mid-task (that's `improve-artifacts`, after friction).

## Done means
- A designed project is self-describing: manifest, schemas, conventions README, and a rule pointer a cold agent can find without this extension installed.
- `tools/lint.py` enforces that project's schemas (including append-only ledgers against git) and gates session end.
- `init-artifacts` produces a lint-clean system; `improve-artifacts` is the only path to change designs.
- This repo dogfoods its own system. Tests cover lint's load-bearing checks. Cursor discovery works via the rule pointer; Claude Code session-start injection works.
