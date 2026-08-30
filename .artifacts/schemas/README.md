# Schema format

Every designed artifact type is defined by one JSON file in the project's
`.artifacts/schemas/` directory. These schemas are the project's contract:
`tools/lint.py` enforces exactly what is written here, and a cold agent
parses artifacts by reading schemas first. If it isn't in the schema, it
isn't enforced.

## Schema file: `.artifacts/schemas/<name>.json`

```json
{
  "name": "failures",
  "version": 1,
  "purpose": "What was tried and abandoned, why, and what that rules out",
  "discipline": "ledger",
  "layout": "collection",
  "path": "failures",
  "id_format": "NNN-slug",
  "fields": [
    { "name": "Attempted", "required": true, "hint": "what was done, concretely" },
    { "name": "Observed", "required": true, "hint": "exact failure, verbatim over paraphrase" },
    { "name": "Cause", "required": true, "hint": "confirmed|suspected — inference" },
    { "name": "Rules out", "required": true, "hint": "what not to retry, and what would change that" }
  ]
}
```

| Key | Values | Meaning |
|---|---|---|
| `name` | string | Type name; must match filename `<name>.json` |
| `version` | integer | Bumped on any field/shape change |
| `purpose` | string | One line; shown to cold readers |
| `discipline` | `"snapshot"` \| `"ledger"` | Rewritable vs append-only (see disciplines.md) |
| `layout` | `"file"` \| `"collection"` | Single md file vs folder of md entries (see layouts.md) |
| `path` | string | Relative to `.artifacts/` — a `.md` file or a directory |
| `budget_lines` | integer, optional | Hard line cap; lint errors above it. Use for snapshots read every session |
| `id_format` | `"NNN-slug"`, optional | Collection entry filename convention |
| `fields` | array | Required/optional fields; `hint` guides writers |

## Markdown conventions (what lint checks)

**snapshot + file:** each required field appears as a `## <Name>` heading in
the document.

**ledger + file:** each entry is a section starting `## #<number>`; each
required field appears as a `**<Name>:**` label inside the entry.

**collection (either discipline):** each `.md` file directly in the
directory is one entry/document; each required field appears as
`**<Name>:**` or `## <Name>` in that file. Non-`.md` files (raw output,
assets) are ignored by field checks and may live in subdirectories.

**`id_format: "NNN-slug"`:** entry filenames match `<number>-<slug>.md`,
zero-padded 3+ digits, lowercase slug (`003-alb-idle-timeout.md`). Numbers
never reused or renumbered; gaps warn, duplicates error.

Field name matching is case-insensitive. Optional fields may be absent —
never write filler like "None" to satisfy a template.

## Design freedom and its limits

Free at design time: type names, which fields and their meanings, discipline
+ layout combination, folder organization (by topic, phase, component),
budgets, how many types.

Not free, ever: the conventions above (lint depends on them), append-only
for ledgers, budgets once set (raise only via redesign), schema edits
outside an explicit design/redesign step with human review.
