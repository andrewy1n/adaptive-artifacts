# Gate: blinded verification

A gate checks whether a milestone met its bar. The result is recorded in a
ledger-discipline type (see the verification preset), but the load-bearing
part is how the check is constructed, not the document.

## The blindness rule (non-negotiable)

The check is performed by a fresh subagent whose prompt contains **only**:

1. The bar being checked, stated precisely
2. Paths to the project's snapshot artifacts (state, scope, plan)
3. Instructions to verify independently against the actual codebase

It must NOT receive: the parent conversation, the parent's reasoning about
why the work is correct, or any evidence artifacts. A verifier that can see
the expected answer pattern-matches instead of checking. If it independently
reproduces what evidence claims, that agreement is the point.

Record the result whether it passed or failed. Failed gates stay in the
ledger — no delete-and-rerun-until-green.

## Tool gates

Mechanical checks (lint passes, tests run, references resolve) are cheaper
than agent gates and run first — automate the checkable, reserve agent and
human attention for what can't be scripted. `tools/lint.py` is itself a
standing gate wired into the stop hook.
