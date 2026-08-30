# Agent-Managed Adaptive Artifacts: Design Rationale

Distilled from comparing two independently-developed systems — GSD (software
delivery planning) and ARA / "Agent-Native Research Artifacts" (scientific
publishing) — that converge on the same architecture from opposite domains,
then refined through design discussion. This document is the *rationale*:
principles and the reasoning behind them. Operational content (trigger tables,
schemas, rubric wording) belongs in the eventual SKILL.md, not here. When a
design question comes up that the skill's rules don't cover, this is the
document to consult.

Positioning: this is the **general core** of the pattern. Heavyweight systems
like GSD are specialized instances of it. No interop with existing systems is
attempted in v1.

## Core principle

**The artifact is the primary object; any narrative form (a PR description, a
paper, a status update) is a compiled view generated *from* it, not the other
way around.** Nothing gets written first as prose and then "captured" into
structure after the fact — the structure *is* the record, from the start.

## Where the value comes from

Not "agents remember things." The mechanism is an **economic asymmetry**:
certain information is nearly free to capture at one specific moment and
expensive to recompute at any later moment. The system is an arbitrage on that
gap.

The clearest case: at the instant an approach is abandoned, everything about
the dead end — what was tried, the exact failure, what it rules out — is in
context, and writing it down costs a paragraph. Three sessions later, the same
information costs re-running the exploration. Every artifact kind earns its
existence by identifying such a moment: capture-cheap, rederive-expensive.

Consequences:

1. **Value scales with discontinuity** — number of sessions, number of
   distinct agents, time gaps between them. A one-session task has zero
   arbitrage available, so instantiating *no* artifacts must be a legitimate,
   respectable outcome. The strongest use cases are parallel agents and
   handoffs, not just serial solo sessions: artifacts as coordination
   substrate, not diary.
2. **The margin can go negative.** Every artifact carries a maintenance tax
   (updating it) and a read tax (context spent loading it). The design goal is
   maximizing `(rederivation cost avoided) − (maintenance + read cost)`, and
   that inequality should drive nearly every design decision.

A second, independent value source: **de-biasing**. A verifier spawned fresh
with only artifact paths cannot pattern-match against the answer the parent
expected — it has to actually check. This value comes from *withholding*
context, not persisting it, and is why visibility boundaries belong in this
system rather than being a separate concern.

Evaluation of whether the system is working is informal for now — judgment
and felt friction, not metrics.

## Six commitments

### 1. Narrative compilation is lossy in a specific, named way
Detail sufficient to convince a reader is not detail sufficient for a machine
to execute, and exploration that didn't make the final cut gets discarded
entirely. Naming the failure mode precisely is what justifies the structure.

### 2. Fixed, typed schema for anything a second agent has to consume
Files that cross a role boundary use a small set of required fields, not
free-form prose. Flexibility at write time becomes unpredictability at read
time; a differently-scoped agent must be able to parse the file cold. The
schemas themselves may be designed per project — but once designed they are
frozen, machine-readable, and carried in the repo, so the cold-parse
guarantee holds.

### 3. Role separation enforced by information access, not convention
In practice the only real enforcement mechanism is subagent construction: a
verifier's prompt is built from artifact paths plus the claim being checked —
never from the parent's conversation, never from the evidence layer. Anything
else is a polite request.

### 4. Escalating automation before human judgment — never replacing it
Mechanical checks (schema conformance, does it run) are automated and gate
progression. Human attention is reserved for what can't be checked
mechanically and pushed as late as possible — but never removed.

### 5. Process and failure are retained as first-class data
What didn't work is the expensive, hard-won part. A dead-end record prevents
the next agent or session from re-spending the same effort.

### 6. The record survives the session that produced it
State that matters is written down; state that isn't written down is treated
as lost, not "probably still in context." Artifacts are committed to git.

## What "adaptive" means

The fixed/adaptive split lives at the **meta level**, not the type level:

**Fixed (extension-wide):** the primitives — disciplines (snapshot vs
ledger), layouts (file vs collection), the schema format and its markdown
conventions, the manifest, the gate/blindness rule — plus the universal
invariants: append-only ledgers, at-the-moment writes, budgets, cold
readability.

**Adaptive (per project, agent-designed):** the concrete artifact types. At
init the agent runs a *design session*: composes types from the primitives,
tunes fields to the domain, chooses folder organization (by topic, phase,
component), and writes the result as the project's own machine-readable
schema registry (`.artifacts/schemas/*.json`). Presets (state, scope, plan,
failures, evidence, verification, friction) are starting points, not a
ceiling.

The read-time contract survives because designs are **frozen after design
time and self-described in-repo**: a cold reader parses manifest → schemas →
artifacts, and a lint tool enforces the schemas mechanically. Freedom at
design time, rigidity at write time. Mid-task schema improvisation stays
forbidden — redesign is an explicit, human-reviewed step.

Escalation remains trigger-based: start minimal, instantiate an
already-designed or preset type when its event fires (first abandoned
approach creates the failure ledger). Designing a *new* type mid-task is not
escalation; it goes through the friction ledger to a design session.

### Tooling layer

Machine-readable schemas buy mechanical enforcement (commitment #4
realized): a generic `lint` validates any designed system — required
fields, budgets, manifest coverage, id sequences, append-only against git
history — and runs as a session-end gate via hooks. A scaffolder stamps new
ledger entries from schemas. Projects may add their own tools (compiled
views, queries, capture helpers), registered in the manifest; read tools
are free, write tools must emit lint-clean output so the schema registry
stays the single source of truth.

## System design

**A manifest as single entry point.** One small file listing which kinds exist
in this project, where each lives, the schema version each was written
against, and the commit hash each was last accurate against. Adaptivity is
only safe if presence/absence is itself machine-readable. Session start
injects the manifest, not every artifact; the agent pulls individual artifacts
on relevance, keeping read tax proportional to the task.

**Two storage disciplines.** *Snapshots* (Scope, State, Plan) are rewritten in
place and bounded — State gets a hard size budget because its read tax recurs
every session. *Ledgers* (Failure log, Evidence, Verification) are
append-only, never rewritten: their value is precisely that nobody sanitized
them after the fact. The failure modes differ — snapshots rot (staleness),
ledgers bloat (archive, never edit).

**Event-driven lifecycle, enforced where possible.** Session start: read
manifest; if its commit hash doesn't match HEAD, trust is off and State must
be diffed against reality. Abandonment: append the failure entry *before
proceeding*. Session end: rewrite State. Hooks enforce the session boundaries
(mechanically detectable); skill discipline carries the mid-session triggers
(only the agent can see an abandonment).

**Verification as a construction rule.** The Verification document is
downstream; the load-bearing rule is how the verifier subagent's prompt is
built (commitment #3).

## What choices the agent gets

The organizing pattern: **freedom where the agent has information the design
doesn't (task-specific judgment); rigidity where the agent has incentives the
design doesn't want** (looking diligent, telling a clean story, saving effort
at write time and externalizing the cost to a future reader).

**Agent decides freely** (judgment, cheap to get wrong, reversible):
- Routing: which kinds this project needs, including none; escalating when a
  trigger fires.
- Significance thresholds: is this dead end worth an entry? Heuristic: log if
  rediscovery would cost more than ~15 minutes or the failure is non-obvious.
- Compaction: when State exceeds budget, what gets summarized vs archived.
- All prose inside required fields.

**Agent decides within constraints:**
- What to load at session start (manifest mandatory; artifacts on relevance).
- Whether to trust State (mandatory re-verification on commit-hash mismatch).

**Agent gets no choice:**
- Schema shape per kind.
- *When* the failure log is written. At session end an agent narrates the path
  that worked and rationalizes away detours; retrospective failure logging
  produces sanitized fiction. The entry is written at the moment of
  abandonment or its information is already degraded.
- Reading the manifest at session start. Optional reading is how compliance
  drift starts.
- The verifier's blindness.

## Design evolution

The system's design is changeable — but slowly, with evidence, at the right
level, and never mid-flight.

**Three layers, different change costs.** Schemas are the constitutional layer
(amendable, deliberately hard — every cold reader depends on them). Routing
rubric and thresholds are tuning parameters (cheap to change, break nothing).
Lifecycle triggers are in between: adding one is safe, weakening one is not.

Evolution happens at two levels: **project redesign** (this project's
schemas and tools, evidenced by its own friction ledger) and **extension
amendment** (primitives, presets, shared tools — evidenced by friction
recurring across projects). A fix one project needs is a redesign; the same
fix appearing in every project's redesign is a preset or primitive
amendment.

**Mechanism: the friction log** — a ledger-kind artifact whose subject is the
artifact system itself. When the design fails the agent (a field that's always
boilerplate, a missing field it keeps wanting, a useless trigger, a missing
kind), it appends an entry at the moment of friction and moves on.

Two properties carry the weight:
1. **Proposals are decoupled from application.** The agent never edits a
   schema mid-task. An agent that can rewrite the rules mid-task rewrites them
   toward less work right now and calls it improvement.
2. **Changes are evidence-gated.** An amendment cites the friction entries
   that motivated it. "Empty boilerplate in 9 of 11 uses" is an argument;
   "feels cleaner" is not.

**Amendment asymmetries:**
- Rigor-reducing changes (removing required fields, weakening mandatory
  triggers, relaxing verifier blindness) require human ratification. The
  friction an agent feels is the friction of doing the work; the cost of
  missing information lands on a future session that can't file the
  complaint.
- Changes flow to the **library** (the skill), versioned — never to project
  instances. Per-project schema forks recreate the improvisation the fixed
  schemas exist to prevent.
- The manifest's version stamps let readers tolerate one schema version back;
  no migration machinery needed.
- Ledgers are never retro-migrated. A migration pass is a rewrite pass with
  good intentions.

**Expected trajectory:** high amendment rate early, declining over time — the
system should anneal. Persistent schema churn after months of use means the
kinds were mis-drawn, not that amending should continue. Steady state:
thresholds tune occasionally, schemas almost never move, and most friction
entries are rejected at review.

## Anti-goals

This system is **not**:
- **Documentation or a wiki** — those serve readers who weren't part of the
  work; artifacts serve agents continuing it.
- **A transcript archive** — artifacts are distillation; raw conversation is
  treated as lost by design (commitment #6 cuts both ways).
- **A substitute for git history** — git records what changed; artifacts
  record intent, state, and what was ruled out.
- **Ceremony** — routing to the empty set is a first-class outcome, and the
  skill must say so explicitly, or agents will instantiate artifacts to look
  diligent.

## Adoption and scope limits

**Mid-project adoption:** Scope and State are written from present reality.
Ledgers start empty — **never backfill a failure log from memory**; a
reconstructed ledger is exactly the sanitized fiction the at-the-moment
discipline exists to prevent.

**Concurrency (out of scope, v1):** single-writer assumption. Ledger appends
are naturally merge-friendly; snapshot merge semantics (two agents rewriting
State in parallel worktrees) are deliberately unsolved. Stated now because
"we assumed single-writer" is cheap to declare and expensive to discover.