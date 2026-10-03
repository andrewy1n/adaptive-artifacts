# CLAUDE.md

Follow [AGENTS.md](AGENTS.md). Same session protocol and
extension-change gate.

## Testing

While editing, run the affected files under `tools/runtime/tests/`.
Before closing a task:

```bash
python3 -m pytest tools/runtime/tests -q
```

Tests call `tools/artifacts.py`. Session capture uses the installed
`adaptive-artifacts` CLI, not a hand-edited record. Views under
`.artifacts/views/` are derived — regenerate them.

## se-workflow

`~/se-workflow` depends on this CLI. Its suite shells out to
`tools/artifacts.py`. A request that comes from that repo still follows
"Changing the extension" in [AGENTS.md](AGENTS.md): capture the
amendment in this store and apply it only with human approval.

If the need fits se-workflow's `contract/project-design.json`, change
that contract in `~/se-workflow` and leave this runtime as it is.
`reassess-artifacts` redesigns a project's own contract. It does not
edit this extension.

Python 3.8+, stdlib only. Sync a plugin payload with
`scripts/sync-plugin.sh`. Do not include this repo's `.artifacts/`
store in that payload, and do not point Cursor at this git tree as the
plugin root.
