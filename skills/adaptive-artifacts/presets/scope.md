# Preset: scope

What this is and what it explicitly is not. Changes rarely — an edit here is
a real pivot and should be called out to the human.

## Schema

```json
{
  "name": "scope",
  "version": 1,
  "purpose": "What this is, what's explicitly out, what done means",
  "discipline": "snapshot",
  "layout": "file",
  "path": "SCOPE.md",
  "fields": [
    { "name": "What", "required": true, "hint": "1-3 sentences: the thing and for whom" },
    { "name": "Out of scope", "required": true, "hint": "adjacent things deliberately excluded" },
    { "name": "Done means", "required": true, "hint": "observable completion criteria" }
  ]
}
```

## Quality bar

Bad "Out of scope" (excludes nothing anyone would assume): *"Perfect code.
Features we haven't thought of."*

Good (excludes something an agent would otherwise drift into):
*"Concurrency: single-writer assumption; parallel-worktree merge semantics
deliberately unsolved in v1."*
