# adaptive-artifacts

Agent-designed, machine-enforced project artifacts that survive across
sessions and agents. Design rationale in [IDEA.md](IDEA.md).

The extension ships **primitives** (disciplines, layouts, schema format,
manifest, gates), **presets** (starting-point designs for common types), and
**tools** (lint + entry scaffolder). Per project, an agent runs a design
session composing concrete artifact types from the primitives — fields tuned
to the domain, folder organization by topic/phase/component — and freezes
the design as a machine-readable schema registry in the repo. Lint enforces
the project's own schemas mechanically, including append-only ledgers
checked against git history.

## Layout

```
skills/
  adaptive-artifacts/     # ambient runtime: session protocol, disciplines
    primitives/           # fixed rules: schema format, disciplines, layouts, manifest, gate
    presets/              # adaptable starting designs (state, scope, plan,
                          #   failures, evidence, verification, friction)
  init-artifacts/         # explicit: the design session
  improve-artifacts/      # explicit: project redesign / extension amendment
tools/
  lint.py                 # validate .artifacts/ against its schema registry
  new_entry.py            # scaffold ledger entries from schemas
hooks/
  session-start.py        # inject MANIFEST.md into new sessions
  session-stop.py         # session-end gate: staleness + lint
  hooks.json              # Claude Code hook wiring
.claude-plugin/           # Claude Code plugin manifest
.cursor/                  # Cursor wiring for this repo (skills symlink + hooks.json)
```

Requires `python3` (3.8+, stdlib only).

## What a designed project looks like

```
.artifacts/
  MANIFEST.md             # entry point: types, paths, schemas, tools, staleness stamp
  schemas/                # the frozen design: one JSON per type + README (conventions)
  STATE.md                # e.g. snapshot/file, 60-line budget
  plan/                   # e.g. snapshot/collection, one doc per phase
  failures/               # e.g. ledger/collection, one immutable entry per dead end
  evidence/               # e.g. ledger/collection, with raw/ attachments
  FRICTION.md             # ledger: where this design failed its users
  tools/                  # optional project-designed tools, registered in manifest
```

## Install: Cursor

This repo is wired project-locally (`.cursor/skills -> ../skills`,
`.cursor/hooks.json`). User-wide: symlink `skills/*` into `~/.cursor/skills/`
and merge the two hook commands into `~/.cursor/hooks.json` (absolute paths,
`--cursor` flag, `loop_limit: 1` on stop).

Known limitation: Cursor currently drops `additional_context` from
`sessionStart` hooks (confirmed bug). Discovery in Cursor rests on the rule
pointer `init-artifacts` plants (`.cursor/rules/artifacts.mdc`); the hook
ships anyway and activates when fixed. The `stop` lint gate works today.

## Install: Claude Code

Repo root is a plugin (`.claude-plugin/plugin.json`; skills and hooks
auto-load). Both hooks work: SessionStart manifest injection and the Stop
lint gate.

## Usage

- `/init-artifacts` — design session: propose types, review with human,
  freeze schemas, plant discovery pointers
- normal work — `adaptive-artifacts` runtime applies ambiently; lint gates
  session end
- `/improve-artifacts` — friction-driven redesign (project) or amendment
  (extension)
- `python3 tools/lint.py --root <project>` / `python3 tools/new_entry.py
  <type> --title "..." --root <project>` — usable directly by any agent

Projects are self-describing (schemas + conventions README + rule pointer
live in the repo), so agents without this extension can still interact with
a project's artifacts correctly.
