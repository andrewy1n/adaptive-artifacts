# AGENTS.md

Unpublished experimental **0.1.0**. The catalog, contract formats, and
design rationale are experimental too — not a released language.

## Live protocol

This repo lives on the experimental contract runtime under `.artifacts/`.
At session start, if views were not injected, run
`adaptive-artifacts hook-start` and read the derived views (also under
`.artifacts/views/` after a start hook). Capture records at the event
with `adaptive-artifacts` (installed plugin CLI, not
`./tools/artifacts.py`). Views are derived — regenerate, do not edit.
At session end, if facts changed write records, regenerate views, and
run `adaptive-artifacts hook-stop`. Fix validation errors before
finishing.

## Changing the extension

Amendments to what this repo ships (catalog, runtime, hooks, skills)
are captured in this store and applied only with human approval —
not mid-task. `reassess-artifacts` is only for redesigning a project's
own artifact contract, never for editing the extension, and is not this
repo's live protocol. Skill names: `design-artifacts`,
`artifact-runtime`, `reassess-artifacts`.

Do not recreate a separate `.records/` or `adaptive-artifacts/` tree.

## What to read

| Need | Where |
|---|---|
| Live goal, position, next | `.artifacts/views/handoff.md` (derived) |
| This protocol | this file |
| Proposed design rationale | `design/DESIGN.md` (experimental, not authority) |
| Executable contract format | `design/contracts/` |
| This project's design | `.artifacts/project-design.json` |

Do not treat `design/DESIGN.md` as the live protocol. It is unpublished
design rationale and can drift from the executable contract.

## Working in this tree

Python 3.8+, stdlib only. The user-facing command is
`adaptive-artifacts` (`bin/adaptive-artifacts`, wrapping
`tools/artifacts.py`). Session capture uses that installed CLI. This
repo's tests call `tools/artifacts.py` directly.

Layout, install, and the three skills (`design-artifacts`,
`artifact-runtime`, `reassess-artifacts`) are in [README.md](README.md).
Do not point Cursor at this git tree as the plugin root. Sync with
`scripts/sync-plugin.sh`. The payload must not include this repo's
`.artifacts/` store.

While editing, run the affected files under `tools/runtime/tests/`.
Before closing a task, run the suite:

```bash
python3 -m pytest tools/runtime/tests -q
```

Records stay authoritative. Do not hand-edit a record file to make a
test pass. Views are regenerated.

## se-workflow

`~/se-workflow` is a separate plugin. It consumes this CLI and ships
its own contract at `contract/project-design.json`. Its tests subprocess
this repo's `tools/artifacts.py` (`ADAPTIVE_ARTIFACTS_ROOT` overrides
the default `~/adaptive-artifacts`). Keep the public CLI's observable
behavior stable for that suite.

A se-workflow task that needs a catalog, runtime, hook, or skill change
here is an extension amendment. Capture it in this store and wait for
human approval. Do not apply it from the se-workflow session. If
se-workflow's own contract can express the need, the edit belongs in
that repo, not here.
