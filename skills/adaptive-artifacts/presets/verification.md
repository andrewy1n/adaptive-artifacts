# Preset: verification

Gate results: did a milestone meet its bar. Only exists if gates are wanted.
Construction of the check follows primitives/gate.md — blinded subagent,
non-negotiable. Failed gates stay recorded.

## Schema

```json
{
  "name": "verification",
  "version": 1,
  "purpose": "Gate results from blinded verification, pass or fail",
  "discipline": "ledger",
  "layout": "file",
  "path": "VERIFICATION.md",
  "fields": [
    { "name": "Bar", "required": true, "hint": "exact criterion given to the verifier" },
    { "name": "Method", "required": true, "hint": "what the verifier actually did" },
    { "name": "Result", "required": true, "hint": "pass|fail" },
    { "name": "Findings", "required": true, "hint": "specifics; on fail, exactly what missed; surprises even on pass" }
  ]
}
```

Entries: `## #<n> — <bar, short> (<date>)`. Switch layout to collection if
gates are frequent.

## Quality bar

Bad (rubber stamp): *"Result: pass. Everything looks good."*

Good: Bar *"import handles malformed CSV without data loss"*; Method *"5
corrupt fixtures (truncated, bad encoding, embedded newline, dup header,
empty), ran importer, diffed rows"*; Result fail; Findings
*"embedded-newline drops the following valid row — off-by-one in resync
loop, importer.py:141; empty file exits 0 silently, bar doesn't cover it,
flagging."*
