# adaptive-artifacts

Agent-designed, machine-enforced project artifacts that survive across
sessions and agents. Agent protocol: [AGENTS.md](AGENTS.md). Design
rationale (experimental, not authority): [design/DESIGN.md](design/DESIGN.md).

## Project status

Unpublished experimental **0.1.0**. Nothing is released; this is local
dogfood only. Plugin manifests use `0.1.0`. The catalog
(`design/contracts/catalog.json`, currently `0.6.0`) is experimental
too — an internal iteration, not a published language. Contract
*format* remains `project-design@0.3.0` under `design/contracts/`.

The user-facing command is `adaptive-artifacts` (wraps
`tools/artifacts.py`). This repo's live memory is `.artifacts/`.
Skills: `design-artifacts`, `artifact-runtime`, `reassess-artifacts`.

## Layout

```
bin/
  adaptive-artifacts      # user-facing CLI (wraps tools/artifacts.py)
scripts/
  sync-plugin.sh          # copy a clean payload (no .artifacts/ store)
skills/
  design-artifacts/       # explicit: assess + pattern types, views, bundles
  artifact-runtime/       # ambient: session protocol
  reassess-artifacts/     # explicit: triggered redesign of a project contract
tools/
  artifacts.py            # resolve, init, lock, record ops, views, hook adapters
  runtime/                # store, contract loader, tests
hooks/
  session-start.py        # inject derived views
  session-stop.py         # session-end store validation
  hooks.json              # Claude Code hook wiring
  hooks-cursor.json       # Cursor hook wiring
AGENTS.md                 # live agent protocol for this repo
design/DESIGN.md          # experimental design rationale (not authority)
design/contracts/         # catalog, traits, backends, resolver
.artifacts/               # project design, resolved contract, optional live store
.claude-plugin/           # Claude plugin manifest + marketplace catalog
.cursor-plugin/           # Cursor plugin manifest
.cursor/rules/            # discovery rule only; skills and hooks come from the plugin
```

Requires `python3` (3.8+, stdlib only).

## What a designed project looks like

```
.artifacts/
  project-design.json     # approved project-design@0.3.0
  resolved-contract.json  # frozen resolution (source_lock + types)
  meta.json               # present after init; pins contract path + digest
  records/                # typed JSON records
  history/                # append-only revision archive
  views/                  # derived markdown (regenerate, do not edit)
```

Design-only (`.artifacts/` with a design and no `meta.json`) is a correct
state.

## Install

Unpublished experimental **0.1.0**. Not in Anthropic's official plugin
list.

- **Cursor** — sync a clean payload (no `.artifacts/` store) into
  `~/.cursor/plugins/local/`; do not point Cursor at this git tree as
  the plugin root.
- **Claude Code** — add this GitHub repo as a marketplace, then install
  `adaptive-artifacts@adaptive-artifacts` (two steps; see below).

### Cursor (local)

1. From this repo, copy the payload:

   ```bash
   scripts/sync-plugin.sh
   ```

   Default destination: `~/.cursor/plugins/local/adaptive-artifacts`.
   Pass another directory as `$1` if needed.

2. Put the CLI on PATH:

   ```bash
   ln -s ~/.cursor/plugins/local/adaptive-artifacts/bin/adaptive-artifacts ~/.local/bin/adaptive-artifacts
   ```

   Ensure `~/.local/bin` is on PATH.

3. Reload Cursor. Enable third-party / local plugins if prompted.

After sync, this source repo uses the installed plugin for skills and
hooks. Do not keep project-local `.cursor/skills` or `.cursor/hooks.json`.

Known limitation: Cursor currently drops `additional_context` from
`sessionStart` hooks (confirmed bug). Discovery in Cursor rests on the
rule pointer `design-artifacts` plants (`.cursor/rules/artifacts.mdc`);
the hook ships anyway and activates when fixed. The `stop` validation
gate works today.

### Claude Code

Two steps: add the marketplace, then install the plugin. It is **not**
in Anthropic's official marketplace — install fails with "not found"
if you skip the add.

```bash
claude plugin marketplace add andrewy1n/adaptive-artifacts
claude plugin install adaptive-artifacts@adaptive-artifacts -y
```

The install id is `plugin@marketplace` → `adaptive-artifacts@adaptive-artifacts`.

Local payload (after `scripts/sync-plugin.sh`) works the same way:

```bash
claude plugin marketplace add ~/.cursor/plugins/local/adaptive-artifacts
claude plugin install adaptive-artifacts@adaptive-artifacts -y
```

If a marketplace named `adaptive-artifacts` already points somewhere
else, remove it first: `claude plugin marketplace remove adaptive-artifacts`.

Claude puts plugin `bin/` on PATH. For Cursor-only use, keep the
`~/.local/bin` symlink above.

## Usage

- `/design-artifacts` — design session: assess shape, declare pattern types,
  views, and bundles, review with human, write `.artifacts/project-design.json`
- normal work — `artifact-runtime` applies ambiently; capture at the event;
  views are derived
- `/reassess-artifacts` — triggered redesign of a project's contract
  (changing the extension itself is this repo's store plus human approval)
- `adaptive-artifacts` (optional `--root <project>`; defaults to cwd) —
  `lock`, `resolve`, `init`, `create`, …

Projects are self-describing (design + resolved contract + optional store),
so agents without this extension can still read records and views.
