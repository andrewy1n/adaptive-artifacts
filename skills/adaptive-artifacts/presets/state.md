# Preset: state

Where things stand right now and what's next. The one type almost every
multi-session project needs. Rewritten at session end; budgeted because its
read tax recurs every session. Written for a cold reader — no "the approach
we discussed", name it.

## Schema (adapt fields to the project, keep the shape)

```json
{
  "name": "state",
  "version": 1,
  "purpose": "Where things stand and what's next; rewritten every session",
  "discipline": "snapshot",
  "layout": "file",
  "path": "STATE.md",
  "budget_lines": 60,
  "fields": [
    { "name": "Goal", "required": true, "hint": "one line" },
    { "name": "Now", "required": true, "hint": "position not activity: what exists, works, is half-done" },
    { "name": "Next", "required": true, "hint": "ordered concrete actions, most specific first" },
    { "name": "Open", "required": false, "hint": "blockers/questions and what resolves them; omit if empty" },
    { "name": "Ruled out", "required": false, "hint": "one-liners pointing at failure ledger entries" }
  ]
}
```

## Template

```markdown
# State
as_of: <date> @ <commit>

## Goal
<one line>

## Now
<what exists and works, what is half-done>

## Next
1. <most concrete next action>

## Ruled out
- <one line> (failures/003)
```

## Quality bar

Bad "Now" (activity, useless cold): *"Made good progress today. Worked on
the parser and fixed several bugs."*

Good "Now" (position, cold-readable): *"Tokenizer and parser complete and
tested (`tests/parser_test.py`, 34 passing). Evaluator handles arithmetic
but not variable scoping — `src/eval.py:88` has the stub."*
