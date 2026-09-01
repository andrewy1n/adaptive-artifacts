# Friction

## #1 — manifest stamp chicken-egg (2026-08-30)

**Level:** extension

**Where:** manifest primitive / lint + stop-hook staleness check

**What happened:** committing an artifact update moves HEAD past the just-
written `head_commit`, so plain `stamp != HEAD` comparison flagged every
project stale immediately after its own stamping commit — a false positive
on the very first dogfood commit of this repo.

**Proposal:** stale only when commits since the stamp touch files outside
`.artifacts/`. Applied same session (human-directed): `tools/lint.py`
`stale_since()`, mirrored in `hooks/session-stop.py`, documented in
`primitives/manifest.md`, covered by two tests.

## #2 — no home for positive research knowledge (2026-08-30)

**Level:** extension

**Where:** preset roster / init-artifacts roles list

**What happened:** user observed the presets only capture negative
knowledge (failures) and claim-grounding (evidence, which requires a
reproduction procedure). One-off research findings, case studies, and
how-a-thing-works investigations that succeed have no artifact home —
they'd be shoehorned into evidence or lost in transcripts.

**Proposal:** add a `findings` preset (ledger/collection: Question,
Finding, Basis, Expires when) and a "durable knowledge" role in
init-artifacts. Applied same session (human-directed).

## #3 — amendment changelog rule overbroad (2026-08-30)

**Level:** extension

**Where:** improve-artifacts, extension amendment workflow step 4

**What happened:** the rule required a changelog line at the bottom of any
amended file; applying it to the additive findings-preset change put
repo-specific noise into generically-shipped skill files, loaded into
context on every activation. Its rationale (installed copies lack git
history) only holds for convention changes that alter lint behavior.

**Proposal:** scope the note to convention/primitive changes; additive
changes ride on this repo's git history. Applied same session
(human-directed).

## #4 — extension amendment shipped inside improve-artifacts (2026-08-30)

**Level:** extension

**Where:** improve-artifacts skill, two-level design

**What happened:** the skill shipped both project redesign and the
extension-amendment workflow, but amending the extension only ever happens
in this repo — every installed copy carried instructions for editing a
repo its users don't have, and agents in this repo (twice this session)
treated generic skill files as amendable through a shipped skill path.

**Proposal:** improve-artifacts is solely project redesign; the extension
amendment process moves to repo-local `CONTRIBUTING.md`, pointed to from
`CLAUDE.md`. Applied same session (human-directed).
