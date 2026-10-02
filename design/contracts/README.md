# Provisional project contract format

`design/contracts/` is the executable candidate for the adaptive-artifacts
project-contract format. Unpublished experimental — not a released
language. Continuity-shaped and exploration-shaped types are declared
on the project from patterns; views and bundles are project
declarations too. Other backends still require runtime evidence.

## Documents

- A project design uses `adaptive-artifacts/project-design@0.3.0`.
- Resolution produces `adaptive-artifacts/resolved-contract@0.3.0`.
- `catalog.json` versions the available trait and backend catalogs
  (`status: experimental`; `0.6.0` is an internal iteration).
- `source_lock` pins canonical SHA-256 digests of catalog, traits, and
  backends.

Format versions describe document shape and interpretation. Catalog,
trait, and backend versions describe semantic sources. Changing either
requires an explicit version change; a digest mismatch is always an error.

## Project design

A project design declares `records` from closed patterns
(`current-status`, `event`, `observation`, `finding`, `question`,
`commitment`, `decision`, `definition`, `replica`, `task`, `phase`,
`instruction`), plus `views` and `bundles`. It locks semantic sources and may supply view parameters and
occupancy. `overrides` remain empty. `gaps` name recurring needs and do
not block pattern types. A `families` key is rejected.

All project-facing record, view, and bundle references are
namespace-qualified (`project:name`). Resolution rejects incompatible
traits, lifecycle composition, missing backend capabilities, invalid
occupancy, and stale source locks.

`resolve_project()` is the format validator for project designs.
`validate.py` is intentionally the regression harness for the three
included fixtures; its project-specific assertions are not a universal
contract linter.

```bash
# Print source_lock (never type digests by hand)
python3 design/contracts/resolve.py lock

# Resolve one project design
python3 design/contracts/resolve.py project path/to/project.json --out resolved.json

# Resolve the three fixtures (default)
python3 design/contracts/resolve.py
python3 design/contracts/validate.py
```

## Views

Views never own facts. Each role declares:

- an `occupant` (declared project type);
- an explicit `selection` predicate;
- optional semantic requirements (`requires`, `base_kind`,
  `requires_payload`). Omitted fields derive from the occupant.

The predicate grammar is deliberately small:

```json
{
  "all": [
    { "field": "lifecycle_state", "equals": "active" },
    { "field": "payload.blocking", "equals": true }
  ]
}
```

Only conjunction, equality, `lifecycle_state`, and one-level
`payload.<field>` paths are supported, plus one relative time window:

```json
{ "field": "recorded_at", "within": "24h" }
```

`within` takes a positive integer with unit `m`, `h`, or `d` and applies
only to `recorded_at`. It matches records recorded no earlier than that
long before render time; a record without `recorded_at` never matches. An empty `all` list explicitly
selects every record of the occupant type. Predicates must be valid for
every compatible occupant so a project cannot select a role occupant
that makes the view silently meaningless.

## Current implementation boundary

The runtime in `../../tools/runtime/` executes this format against the
`git-filesystem` backend. It assumes one writer. Individual writes are
atomic and revision-checked; supersede is a detectable two-record
operation, not a transaction. Occurrence correction appends a successor
and leaves the original `recorded`. Bundles are capture templates, not
transactions. Runtime loading checks the resolved structure and requires
those backend guarantees before initializing a store. An interrupted
supersede is detected but currently requires deliberate recovery. Shipped
hooks call `tools/artifacts.py`. No editable view write-back is part of
this candidate.

Run:

```bash
python3 design/contracts/validate.py
python3 -m unittest discover -s tools/runtime/tests
```
