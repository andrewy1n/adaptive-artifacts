# Friction

## #1 — manifest stamp chicken-egg (2026-08-30)

**Level:** extension

**Where:** manifest primitive / lint + stop-hook staleness check

**What happened:** committing an artifact update moves HEAD past the just-
written `head_commit`, so plain `stamp != HEAD` comparison flagged every
project stale immediately after its own stamping commit — a false positive
on the very first dogfood commit of this repo.

**Proposal:** stale only when commits since the stamp touch files outside
`.artifacts/`. Applied same session (human-directed): `tools/lint.py`
`stale_since()`, mirrored in `hooks/session-stop.py`, documented in
`primitives/manifest.md`, covered by two tests.
