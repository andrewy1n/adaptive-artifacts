# CLAUDE.md

## Project artifacts

This repo uses adaptive artifacts. At session start read
`.artifacts/MANIFEST.md`; verify head_commit against HEAD before trusting
snapshots. Type schemas: `.artifacts/schemas/` (conventions in
schemas/README.md). Append to ledgers at the moment of the event. At
session end rewrite the state artifact, update the manifest, and pass
`.artifacts` lint. Follow the adaptive-artifacts skill if installed.
