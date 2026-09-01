# CLAUDE.md

## Project artifacts

This repo uses adaptive artifacts. At session start read
`.artifacts/MANIFEST.md`; verify head_commit against HEAD before trusting
snapshots. Type schemas: `.artifacts/schemas/` (conventions in
schemas/README.md). Append to ledgers at the moment of the event. At
session end rewrite the state artifact, update the manifest, and pass
`.artifacts` lint. Follow the adaptive-artifacts skill if installed.

## Changing the extension

Amendments to what this repo ships (primitives, presets, shared tools,
hooks) follow `CONTRIBUTING.md` — evidence-gated, human-approved. The
`improve-artifacts` skill is only for redesigning a project's own
`.artifacts/` system, never for editing the extension.
