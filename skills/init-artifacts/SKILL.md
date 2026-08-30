---
name: init-artifacts
description: >-
  Design a project's artifact system: compose artifact types from the
  adaptive-artifacts primitives, write the schema registry, manifest,
  discovery pointers, and optional project tools. Use when the user asks to
  initialize, design, or adopt project artifacts, or invokes /init-artifacts.
disable-model-invocation: true
---

# Init Artifacts (design session)

Designs a project-specific artifact system from the adaptive-artifacts
primitives. The output is a frozen, self-describing contract in the repo:
schemas, manifest, pointers, and optionally tools. Design happens here,
with human review — never silently mid-task later.

Read first: the adaptive-artifacts skill's `primitives/schema-format.md`
(design freedom and its limits), `disciplines.md`, `layouts.md`. Presets in
`presets/` are starting points — adapt fields, layouts, and names to the
project; don't copy blindly, don't improvise where a preset already fits.

## Workflow

### 1. Inspect

- `.artifacts/` already exists → stop; report state, suggest
  `improve-artifacts` for redesign.
- Read the repo: purpose, structure, history, kind of work ahead
  (delivery? research? exploration-heavy? phased?).

### 2. Design

**Recommending no artifacts is a first-class outcome** — one-session work
with no handoff gets none. Otherwise design the smallest system the work
justifies:

- Which types, from what roles: current position (state), boundaries
  (scope), the work itself (plan), dead ends (failures), grounding
  (evidence), gates (verification), design feedback (friction — include it
  whenever anything else exists)
- Per type: fields tuned to the domain (an experiments ledger for research
  has different fields than a delivery failure log), discipline, layout,
  budgets
- Folder organization where structure is real: collections per topic,
  phase, or component (e.g. `plan/01-ingest.md`; `experiments/` one file
  per run). Don't folder-ize types with few short entries
- Types not covered by presets are allowed — compose from primitives,
  respecting the markdown conventions lint enforces
- Optional project tools: compiled views (status report from artifacts),
  domain queries, capture helpers. Write-tools must emit lint-clean output

### 3. Review with the human

Present the design compactly: each type with purpose, discipline+layout,
fields with one-line rationale for non-obvious choices, what was left out
and why. Apply their overrides. Do not create files before this step.

### 4. Instantiate

- `.artifacts/schemas/<type>.json` per approved design
- `.artifacts/MANIFEST.md` per `primitives/manifest.md`, `head_commit` =
  current HEAD
- Snapshot artifacts written **from present reality** — read the repo,
  don't guess. Ledgers start empty even mid-project: **never backfill from
  memory**; first entries come from future events
- Copy `primitives/schema-format.md` to `.artifacts/schemas/README.md` so
  agents without this extension can parse the conventions
- Project tools (if designed) in `.artifacts/tools/`, registered in the
  manifest's Tools section
- Run `tools/lint.py --root <project>` — must pass clean before finishing

### 5. Plant discovery pointers

A cold session must find the artifacts deterministically, not by luck:

**Cursor** — `.cursor/rules/artifacts.mdc`:

```markdown
---
alwaysApply: true
---
This repo uses adaptive artifacts. At session start read
`.artifacts/MANIFEST.md`; verify head_commit against HEAD before trusting
snapshots. Type schemas: `.artifacts/schemas/` (conventions in
schemas/README.md). Append to ledgers at the moment of the event. At
session end rewrite the state artifact, update the manifest, and pass
`.artifacts` lint. Follow the adaptive-artifacts skill if installed.
```

**Claude Code** — same content as a `## Project artifacts` section in
`CLAUDE.md` (create if absent).

Hooks are per-user enhancement, not the discovery mechanism (Cursor's
sessionStart injection is currently unreliable); the rule pointer is the
deterministic path.

### 6. Finish

Ensure `.artifacts/` isn't gitignored (artifacts are committed). Report:
types designed and why, presets adapted vs custom, what was deliberately
omitted. Commit only if asked.
