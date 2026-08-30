# Preset: plan

The content actually being built: task breakdown, argument structure,
design. Loosest-shaped preset — adapt freely. Division of labor with state:
state says *where things stand*, plan says *what the work is*.

## Schema — single file (small projects)

```json
{
  "name": "plan",
  "version": 1,
  "purpose": "The work being built: breakdown, approach, open decisions",
  "discipline": "snapshot",
  "layout": "file",
  "path": "PLAN.md",
  "fields": [
    { "name": "Objective", "required": true, "hint": "what this delivers, one paragraph" },
    { "name": "Approach", "required": true, "hint": "chosen approach; one-line why if alternatives were live" },
    { "name": "Items", "required": true, "hint": "breakdown with status markers [ ] [~] [x] [!]" },
    { "name": "Decisions", "required": false, "hint": "open decisions with options; omit if none" }
  ]
}
```

## Variant — collection by phase/component (larger projects)

For work with natural phases or components, make plan a snapshot collection
instead: one file per phase, order-prefixed names, same fields per file.

```json
{
  "name": "plan",
  "version": 1,
  "purpose": "Per-phase plans; one rewritable doc per phase",
  "discipline": "snapshot",
  "layout": "collection",
  "path": "plan",
  "fields": [
    { "name": "Objective", "required": true },
    { "name": "Items", "required": true },
    { "name": "Decisions", "required": false }
  ]
}
```

Files: `plan/01-ingest.md`, `plan/02-index.md`, ... State's "Next" points at
the active phase file.

## Quality bar

Bad item (not checkable): *"- [ ] Improve the API"*

Good item (a cold reader can tell when it's done): *"- [ ] Add cursor-based
pagination to `GET /events` (page token in response, `limit` capped at 100),
with a test for the empty-last-page case"*
