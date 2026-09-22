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
