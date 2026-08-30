# Preset: friction

Ledger whose subject is the artifact system itself — schema doesn't fit,
field is always boilerplate, trigger fired uselessly, missing type. Append
at the moment of friction, then **follow the existing rule anyway**. Designs
change only at explicit review (`improve-artifacts`), never mid-task.

Instantiate this in every project that gets artifacts at all — it is the
input channel for redesign.

## Schema

```json
{
  "name": "friction",
  "version": 1,
  "purpose": "Where this project's artifact design failed its users; input to redesign",
  "discipline": "ledger",
  "layout": "file",
  "path": "FRICTION.md",
  "fields": [
    { "name": "Where", "required": true, "hint": "which type/field/trigger/threshold" },
    { "name": "What happened", "required": true, "hint": "the concrete mismatch" },
    { "name": "Proposal", "required": false, "hint": "suggested change, or omit" }
  ]
}
```

Entries: `## #<n> — <where, short> (<date>)`.

## Quality bar

Bad (vibes, unreviewable): *"State feels too rigid. Should be more
flexible."*

Good: *"Where: failures schema, Observed field. What happened: third entry
in a row where the failure was a design realization, not a command output —
nothing verbatim to paste, wrote prose in a field hinted 'verbatim'.
Proposal: soften hint to 'exact failure; verbatim where output exists'."*
