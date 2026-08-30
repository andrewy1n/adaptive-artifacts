# Manifest: `.artifacts/MANIFEST.md`

Single entry point. A cold agent must learn from this file alone: what
artifact types exist, where, under which schema, how stale, and what tools
are available. Updated whenever any artifact or schema is written.

## Format

```markdown
# Artifact Manifest
manifest_version: 2
head_commit: <full or short commit hash artifacts were last accurate against>
updated: <YYYY-MM-DD>

## Artifacts
| Type | Path | Schema | Since |
|---|---|---|---|
| state | STATE.md | schemas/state.json | 2026-08-30 |
| failures | failures/ | schemas/failures.json | 2026-09-02 |

## Tools
| Tool | Usage |
|---|---|
| tools/report.py | Compile status report from state + failures |
```

Rules:

- List only types that have been instantiated (schema exists; for ledgers
  the path may not exist yet — first entry creates it)
- `## Tools` section only if project tools exist. An unregistered tool
  does not exist for a cold agent
- `head_commit` is the staleness stamp: artifacts are stale when commits
  since it touch files *outside* `.artifacts/` — the artifact-stamping
  commit itself never counts. Sessions verify before trusting snapshots;
  lint warns and the stop hook nudges on drift
- Lint cross-checks this table against `schemas/` and the filesystem in
  both directions
