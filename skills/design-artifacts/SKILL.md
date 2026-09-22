---
name: design-artifacts
description: >-
  Design a project's artifact system by assessing information-loss events
  and declaring record types, views, and bundles from closed patterns.
  Use when the user asks to initialize, design, or adopt project artifacts,
  or invokes /design-artifacts.
disable-model-invocation: true
---

# Design Artifacts

Designs a project artifact system as a `project-design@0.3.0` contract.
The output is assessment, **pattern-declared types**, project views and
bundles, and a `source_lock` — not a roster of Markdown files and not a
family pin. Design happens here, with review. Never silently mid-task later.

Runtime after a design exists is `artifact-runtime`. Changing an existing
design is `reassess-artifacts`.

Read first: `design/DESIGN.md` (pattern primitives, design procedure,
no-artifact gate) and `design/contracts/README.md` (document shape).
The catalog is unpublished experimental. Declare types from patterns.
There is no family catalog to adopt.

## Workflow

### 1. Inspect

- A `project-design@0.3.0` document already exists → stop; report it;
  suggest `reassess-artifacts`.
- Read the repo: purpose, existing systems of record, kind of work
  ahead.

### 2. Inventory existing truth

Identify current resources and authority boundaries before proposing
records: code, issue trackers, docs, datasets, experiment systems,
operational platforms, existing artifacts.

New records may own previously unrecorded information, preserve a
source, or serve as a declared replica. They may not create a competing
authority for a claim something else already owns.

### 3. Assess project shape

Qualitative levels (`low` / `medium` / `high`) with evidence. Do not
invent a score. Record the signals that imply information-loss events:

- discontinuity across sessions, agents, roles, time
- exploration and abandoned work
- expensive external investigation
- decision density
- verification cost
- orientation cost
- operational risk
- concurrency
- sensitivity

### 4. No-artifact gate

If reconstruction is cheap and discontinuity is low, recommend **no
durable artifacts**. That is a first-class outcome: no design file, no
store. A short single-context task gets none. Stop after the human
agrees.

A minimal handoff (position across sessions, no investigation store) is
a `current-status` type plus a handoff view — declare them. Do not invent
a custom note format.

### 5. Propose types, views, and bundles

For each information-loss event, declare a project record:

| Field | Values |
|---|---|
| `pattern` | `current-status` `event` `observation` `finding` `question` `commitment` `decision` `definition` `replica` |
| `canonical_for` | scoped claim this type owns (required unless `replica_of`) |
| `capture` | `at_event` `session_boundary` `source_change` `explicit` |
| `read` | `always` `if_relevant` `query` |
| `payload` | domain field names only |

The agent does not choose lifecycle or append-versus-rewrite. Those
derive from the pattern (see `design/DESIGN.md`).

Declare views the cold session must read. Each role names an `occupant`
(a declared type) and an explicit `selection`. `requires` / `requires_payload`
/ `base_kind` are optional; omitted fields derive from the occupant.

Declare bundles only as capture templates for records commonly written
together.

Current catalog (`design/contracts/catalog.json`): unpublished
experimental. project-design `0.3.0`, catalog `0.6.0`, traits `0.3.0`,
backends `0.4.0`. Default backend: `git-filesystem`. `overrides` stay
`[]`.

### 6. Resolve the proposal

Also propose, where relevant:

- `view_params` (`group_by` / `order_by` as a view allows)
- `source_revisions` for external truth
- occupancy only when selecting a compatible non-default occupant
- `gaps` for recurring needs that are not yet types, not for missing
  project types

Apply the value test: omit a type or view when capture and read cost
exceed the rederivation, information-loss, and coordination cost
avoided. Duplicate `canonical_for` is illegal.

### 7. Review with the human

Present compactly, then stop. Do not write files before approval:

- assessment with evidence
- project types: pattern, `canonical_for`, payload
- views, bundles, occupancy
- stewardship / existing authorities
- gaps and deliberate omissions
- unresolved trade-offs

Apply their changes and record the rationale so later agents do not
treat them as accidents.

### 8. Materialize

Fill `source_lock` from the tool — never type digests by hand:

```bash
adaptive-artifacts lock
```

Write the approved `adaptive-artifacts/project-design@0.3.0` document
(see template below). Resolve it:

```bash
adaptive-artifacts --root <project> resolve
```

Write the design at `.artifacts/project-design.json` and the
resolved contract at `.artifacts/resolved-contract.json`.
Resolution must succeed before finishing. A validated design without a
live store is a correct state.

If the human asks to initialize a live store:

```bash
adaptive-artifacts --root <project> resolve
adaptive-artifacts --root <project> init
```

Seed current-claim / commitment records from present reality. Do not
backfill exploration occurrences from memory.

### 9. Plant discovery pointers

A cold session must find the design deterministically.

**Host-neutral** — `AGENTS.md` with the protocol below.
**Cursor** — `.cursor/rules/artifacts.mdc` (always apply) pointing at
`AGENTS.md`. **Claude Code** — `CLAUDE.md` that follows `AGENTS.md`
(same gate; do not duplicate a second protocol).

Planted text must tell agents to invoke `adaptive-artifacts` (optional
`--root <project>`; defaults to cwd). Never expect `./tools/artifacts.py`
in the consuming project; the plugin owns the CLI. Do not plant a CLI
copy. Point at the design path, the store if one exists, and
`artifact-runtime`. State that views are derived and records are
captured at the event. Example for `AGENTS.md`:

```
This project lives on the experimental contract runtime under `.artifacts/`.
At session start, if views were not injected, run `adaptive-artifacts hook-start`
and read the derived views (also under `.artifacts/views/` after a start hook).
Capture records at the event with `adaptive-artifacts` (`create`, `supersede`,
`update`, `correct`, `contradict`, `capture`). Views are derived — regenerate,
do not edit. At session end, if facts changed write records, regenerate views,
and run `adaptive-artifacts hook-stop`. Fix validation errors before finishing.
Never expect `./tools/artifacts.py` in this project; the plugin owns the CLI
(`adaptive-artifacts`, optional `--root <project>`; defaults to cwd).
```

Do not write a parallel `adaptive-artifacts/` or `.records/` tree.
Do not amend this extension's catalog, runtime, skills, or `hooks/`
mid-task. Capture that friction; extension changes are this repo's
store plus human approval.

## Project-design template

```json
{
  "format": "adaptive-artifacts/project-design@0.3.0",
  "project": "<slug>",
  "kind": "<short label>",
  "assessment": {
    "discontinuity": "low|medium|high",
    "external_investigation": "low|medium|high"
  },
  "records": [
    {
      "name": "current-position",
      "pattern": "current-status",
      "purpose": "Live position",
      "canonical_for": "the live position of this subject",
      "capture": "at_event",
      "read": "always",
      "payload": ["position", "scope"]
    }
  ],
  "views": [
    {
      "name": "handoff",
      "owns_facts": false,
      "parameters": ["group_by"],
      "roles": [
        {
          "name": "position",
          "occupant": "current-position",
          "requires_payload": ["position", "scope"],
          "selection": {
            "all": [{ "field": "lifecycle_state", "equals": "active" }]
          }
        }
      ]
    }
  ],
  "bundles": [],
  "overrides": [],
  "source_lock": {},
  "backend": "git-filesystem",
  "view_params": {
    "project:handoff": { "group_by": "<facet>" }
  },
  "source_revisions": { "code": "git_commit" },
  "occupancy": {},
  "gaps": []
}
```

JSON assessment stores levels. Evidence belongs in the review.

Qualified ids (`project:name`) for view parameters, occupancy, and
runtime type / view / bundle references.

## Finish

Report: assessment, project types (pattern + ownership), views, bundles,
gaps, omissions, whether a store was initialized. Commit only if asked.
