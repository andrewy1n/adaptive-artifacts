# Agent Artifact System

## Status

Unpublished experimental design rationale. Not the live protocol (that
is `AGENTS.md`) and not a store authority (that is `.artifacts/`
records). The executable contract is `design/contracts/` plus a
project's `project-design.json`. This document can drift from what
actually runs.

## Problem

Agents lose useful context across sessions, roles, and parallel work. Projects
address this with plans, handoff notes, research logs, decision records, and
other artifacts, but their setup is inconsistent:

- similar projects receive different artifact systems depending on which agent
  designed them;
- planning documents become the default even when research, operations, or
  coordination are the dominant needs;
- copied facts compete with their real source of truth and silently become
  stale;
- documents combine information with different ownership and lifecycle rules;
- useful records are often written retrospectively, after their original
  context has already been lost;
- storage mechanics such as Markdown and Git are confused with the underlying
  information model.

The system should standardize how artifact systems are designed without forcing
every project to use the same artifacts.

## Core idea

An artifact system is a durable transfer from a context that may disappear to a
reader who may never share that context. It manages three different things:
source resources, typed semantic records, and composed views.

An artifact earns its maintenance cost when it preserves information that would
otherwise be lost, expensive to reconstruct, or difficult to coordinate. This
includes planning, but also decisions, failed approaches, findings, operational
events, handoffs, and carefully bounded caches of external truth.

The system standardizes the design procedure and lifecycle rules. It does not
standardize every project into one fixed roster.

## Design principles

1. **One resolution authority per scoped claim or facet.** Code, a record, an
   issue tracker, or another system may be authoritative, but scope,
   jurisdiction, and effective interval must be explicit.
2. **One semantic contract per record, not per file.** Physical documents may
   contain mixed information. Typed semantic records remain independently
   governed, and views may combine them for convenient reading.
3. **Lifecycle is constrained by meaning.** The agent declares a pattern;
   traits derive states, storage, and required dimensions. Families do not
   invent private lifecycles.
4. **Capture at the information-loss boundary.** Events, observations,
   decisions, and commitments are written when they occur, before context is
   sanitized or forgotten.
5. **Design recommendations are explainable, not automatic truth.** The agent
   proposes a roster from declared project characteristics; a human approves or
   overrides it.
6. **No artifacts is valid.** A short, single-context task may not justify a
   durable artifact system.
7. **Agent-first, human-reviewable.** Managed records and views are optimized
   for reliable agent consumption while remaining understandable and editable
   by humans.
8. **Storage is replaceable.** The semantic model must not depend on Markdown,
   a repository, or Git, even when those are the first implementation.

## Semantic architecture

The system distinguishes resources, semantic records, and views. Treating all
three as interchangeable "documents" is the source of many ownership and
lifecycle errors.

### Resources

A resource is a physical or externally addressable container:

- a Markdown file;
- a source file;
- an issue-tracker object;
- an email or transcript;
- a signed contract;
- a notebook;
- a dataset;
- an API response or monitoring stream.

Resources may contain several semantic kinds at once. An incident document can
contain events, observations, diagnoses, decisions, and commitments. A court
order is both evidence that an order was issued and a container for effective
obligations. The system does not split or rewrite a source resource merely to
make its semantics uniform.

Resources have identity, location, revision, provenance, access constraints,
and preservation policy. They may be canonical sources, replicas, or inputs to
derived records and views.

### Semantic records

A semantic record is the smallest managed unit with one ownership and lifecycle
contract. It may occupy its own resource or be represented inside, extracted
from, or linked to a compound resource.

The shared base vocabulary is:

- **event** — something occurred;
- **observation** — something was measured, perceived, or reported;
- **claim** — an assertion that may be supported, disputed, or retracted;
- **question** — a recognized unknown requiring resolution;
- **proposal** — an option offered for adoption;
- **decision** — an authoritative selection among possibilities;
- **commitment** — an actor has undertaken an action or outcome;
- **instruction** — prescribed behavior or procedure;
- **definition** — the declared meaning, structure, or executable form of
  something.

Project types pick a pattern rather than replacing
this vocabulary. A work-item is a `current-status` claim; a check-run is an
`event`; an acceptance bar is a `definition` mapped onto a current claim.

The base kinds are intentionally small. Payload fields carry domain-specific
detail.

### Views

A view composes resources and semantic records for a reader or task:

- agent handoff;
- current project plan;
- incident summary;
- status report;
- architecture overview;
- publication or release narrative.

Views are derived by default and therefore do not become competing authorities.
Their definitions declare inputs, transformation version, freshness, ordering,
redaction, and conflict behavior. A practical view may look like one ordinary
document even when its contents have different underlying contracts.

If a view is used to collect edits, those edits must be resolved into explicit
record operations before becoming canonical. Editable view behavior is a
write-interface concern, not permission for a derived document to silently
become authoritative.

## The three design lenses

Direction, authority, and validity remain mandatory questions during design,
but they are not exclusive schema enums. Stress tests across software delivery,
research, operations, legal work, and editorial work show that real records can
occupy several former values simultaneously.

### Direction lens

Ask how the information relates to time and action:

- Does it describe an event, a present position, a possible future, a forecast,
  or intended action?
- Is it descriptive, interrogative, deliberative, or prescriptive?

The answer helps select a base record kind. It is not stored as a single
`record | position | intent` value: a forecast is future-directed without being
an intention, and an instruction is prescriptive without merely describing a
future event.

### Authority lens

Ask who may authoritatively resolve this exact information:

- What precisely is the subject, claim, or facet?
- Which actor or system is its steward?
- Over what scope, jurisdiction, and effective interval?
- Is this representation original, replicated, or transformed?

Canonicality and lineage are separate. A derived dataset can be canonical for
its own identity while remaining derived from raw inputs. A finding can be the
canonical record of an investigation's conclusion without becoming the
canonical specification of an external API.

The ownership rule is therefore:

> One declared resolution authority per precisely scoped claim or facet,
> jurisdiction, and effective interval.

Different systems may own different facets of a broad subject. Git may own
configuration, deployment infrastructure the deployed revision, and monitoring
the observed runtime health of the same service.

### Validity lens

Ask why the information currently deserves to be used:

- When did it occur or become effective?
- Is it an observation, assertion, supported claim, disputed claim, or
  retracted claim?
- Is it proposed, adopted, required, permitted, prohibited, rejected, or
  superseded?
- What conditions, evidence, or authority sustain it?
- What would make it stale, inapplicable, or false?

Temporal applicability, epistemic status, and normative force are separate. A
policy may be currently effective, normatively required, and contingent on
jurisdiction at the same time.

## Enforceable record dimensions

The design lenses resolve into explicit dimensions where applicable:

- **identity** — stable record identity, version, aliases, and merge/split
  lineage;
- **kind** — shared base kind plus optional project subtype;
- **subject and scope** — the precise thing the record concerns;
- **stewardship** — authority, jurisdiction, and effective interval;
- **representation** — original, replica, or derived;
- **provenance** — source resources, source records, actors, and transformation;
- **time** — occurrence, observation, transaction, effective interval, and
  as-of revision as appropriate;
- **epistemic status** — unknown, asserted, supported, disputed, refuted, or
  retracted when the record makes a claim;
- **adoption or deontic status** — draft, proposed, adopted, required,
  permitted, prohibited, rejected, or superseded when authority is relevant;
- **coverage** — represented scope, completeness, and whether absence means
  unknown, inaccessible, not applicable, or known not to exist;
- **lifecycle state** — a pattern-derived state with allowed transitions;
- **relationships** — supports, contradicts, derives from, implements, verifies,
  supersedes, retracts, or resolves.

Not every record carries every dimension. The pattern (via traits) declares
which dimensions and relationships are required.

## Operational properties

Semantic dimensions are not the complete contract. Record subtypes, resources,
and views also declare operational properties:

- **capture trigger** — event, session boundary, source change, milestone, or
  explicit request;
- **audience** — all agents, a particular role, humans, or a blinded verifier;
- **scope** — task, component, project, workspace, or organization;
- **retention** — ephemeral, durable, or archived;
- **writer model** — single writer or concurrent writers;
- **sensitivity** — public, internal, or restricted;
- **granularity** — one record per event, claim, transition, or stable subject;
- **read policy** — always loaded, routed by relevance, queried, or generated on
  demand.

These properties affect implementation but do not replace the semantic model.

## Lifecycle constraints

Semantics constrain lifecycle. Patterns derive states and transitions from
traits. Payload and views carry domain difference; a proposal and an incident
do not get private lifecycle tables.

Universal constraints still follow from record dimensions:

- occurrence records require auditable append; the original observation is not
  silently rewritten, and correction status is derived from a successor record
  rather than mutating the original under append-only storage;
- corrections, reinterpretations, retractions, and changed decisions create
  linked successors;
- current representations require an as-of boundary and refresh trigger;
- claims require basis, epistemic status, and invalidation conditions
  appropriate to their subtype;
- adopted instructions, definitions, decisions, and commitments require a
  steward, effective interval, and supersession path;
- replicas require an upstream source and source revision;
- derived records and views require lineage and a transformation version;
- generated views must propagate sensitivity, uncertainty, and staleness from
  their inputs;
- session-loaded views require strict size budgets;
- blinded audiences require an enforced information boundary, not merely an
  instruction to ignore other context.

Append-only ledgers and rewritable snapshots remain useful storage patterns, but
they are implementations of these constraints rather than the ontology itself.

## Pattern primitives

The agent-facing design language is a closed set of **patterns**, not a
preset menu and not trait names. For each type the agent declares `pattern`,
`canonical_for` (or `replica_of`), `capture`, `read`, and domain `payload`
names. The resolver maps the pattern onto traits. The agent does not choose
append-versus-rewrite or lifecycle tables.

| Pattern | Meaning | Derives to |
|---|---|---|
| `current-status` | True now; replaced when reality changes | `entity` + `stewarded` + `current-claim` |
| `event` | It happened; the original is not rewritten | `entity` + `occurrence` + `evidence-linked` |
| `observation` | Something was measured or reported; original not rewritten | `entity` + `occurrence` |
| `finding` | Contingent claim with basis and expiry | `entity` + `epistemic-claim` |
| `question` | Unknown with a resolution path | `entity` + `stewarded` + `open-question` |
| `commitment` | An actor has undertaken an outcome | `entity` + `stewarded` + `active-undertaking` |
| `decision` | Authoritative choice among alternatives | same traits as `current-status`; `pattern` remains `decision` |
| `definition` | Adopted criterion or meaning | same traits as `current-status`; `pattern` remains `definition` |
| `replica` | Copy of an external owner | same traits as `current-status`; requires `replica_of` and source payload |

`decision` and `definition` share the `current-claim` lifecycle (`active` →
`superseded`) so they stay executable against the current trait table. They
are not interchangeable with `current-status` at design time: `canonical_for`
and `pattern` say what the type owns. A later trait split is an explicit
catalog change.

Always declared with the pattern:

- `name`, `purpose`
- `canonical_for` or `replica_of` / `derived_from`
- `capture`: `at_event` | `session_boundary` | `source_change` | `explicit`
- `read`: `always` | `if_relevant` | `query`
- `payload`: domain field names only

Illegal combinations fail resolution (two types with the same `canonical_for`;
`replica` without `replica_of`; `event` given a rewrite lifecycle).

Example — software delivery types from patterns:

```json
{
  "name": "work-item",
  "pattern": "current-status",
  "canonical_for": "whether this task or phase is the live work",
  "capture": "at_event",
  "read": "if_relevant",
  "payload": ["title", "phase"]
}
```

Completing a work-item supersedes it. Use `commitment` instead if the project
needs `active → completed`. Acceptance is `definition`. A verification run is
`event`. The plan document is a **view** over those types.

A session position type is the same shape (`current-position` is
`current-status`, `read: always`) plus a handoff view that occupies it.

## Project views and bundles

Views and bundles are declared on the project, in the same document as
pattern types. There is no family catalog. A later project that needs the
same session packet declares the same patterns, roles, and templates.

A view role names an `occupant` (a declared type) and a `selection`
predicate. Optional `requires`, `requires_payload`, and `base_kind` refine
who may occupy the role; omitted fields derive from the occupant. Views do
not own facts.

A bundle is a capture template over declared types. Links in a bundle must
be advertised by the source record's traits.

## How types and views compose

A project declares pattern types, views, bundles, or any combination.

Composition rules:

1. Types, views, and bundles do not automatically create documents.
2. Project `records` use the pattern language and compile through traits.
3. Equivalent types with the same `canonical_for` are rejected; one owner per
   scoped claim.
4. Records with different patterns remain distinct even if a view presents
   them together.
5. Compound source resources remain intact.
6. Cross-cutting summaries are derived views.
7. Gaps name recurring needs. They do not block a project type.

## Versioning and project resolution

Catalog, traits, and backends are versioned and locked. Project pattern
records, views, and bundles live in the design document.

Projects also store a resolved local contract. A cold agent can therefore
understand and validate the project without access to the original extension
or registry. Conceptually, the project contains:

- the design assessment;
- project pattern records and their `canonical_for` declarations;
- resolved record subtypes, lifecycle definitions, and view definitions;
- scoped stewardship declarations;
- resource and relationship definitions;
- backend bindings;
- the revision at which the assessment was last valid.

Projects do not silently inherit later catalog versions. Upgrades are
explicit reassessment events.

## Design procedure

The setup agent follows a reproducible procedure.

### 1. Inventory existing truth

Identify current resources, systems of record, and authority boundaries:

- code and configuration;
- issue trackers;
- documentation;
- datasets;
- experiment systems;
- operational platforms;
- existing project artifacts.

The agent records stewardship at the claim or facet level before proposing new
records. New records may own previously unrecorded information, preserve source
resources, or serve as declared replicas and derivations; they may not create
accidental competing authorities.

### 2. Assess project shape

The agent assesses qualitative inputs using repository evidence and user
context:

- discontinuity across sessions, agents, roles, and time;
- amount of exploration and abandoned work;
- dependence on expensive external investigation;
- decision density;
- verification cost;
- orientation cost;
- operational risk;
- concurrency;
- sensitivity and access boundaries.

False numerical precision is unnecessary. The assessment must state the
evidence behind each conclusion.

### 3. Apply the no-artifact gate

If information can be reconstructed cheaply and there is little discontinuity,
the agent recommends no durable artifacts or only a minimal handoff.

### 4. Propose types

For each information-loss event, declare `pattern` + payload + `canonical_for`.
Declare views the cold session must read. Declare bundles only as capture
templates.

### 5. Resolve resources, records, and views

The agent:

- preserves compound source resources without pretending they have one
  semantic classification;
- compiles pattern declarations and project views into one contract;
- rejects duplicate `canonical_for`;
- identifies precise stewardship boundaries;
- proposes derived views for practical reading and coordination.

Each scoped claim or facet receives one resolution authority for an effective
interval.

### 6. Confirm derived policy

Lenses may still be asked as questions. The stored contract is the pattern
and the derived traits, not a free lifecycle table. For every type, check:

- pattern and `canonical_for`;
- derived traits, dimensions, and relationships;
- capture and read policy;
- universal constraints implied by the pattern.

For every resource and view, the agent defines identity, provenance, lineage,
freshness, access, and write behavior as applicable.

### 7. Apply the value test

For every candidate, estimate:

> rederivation, information-loss, and coordination cost avoided  
> minus capture, maintenance, and recurring read cost

Candidates with negative expected value are removed. The design records
important omissions and why they were omitted.

### 8. Review with the human

The agent presents:

- project assessment;
- adopted starters and versions;
- project types (pattern, `canonical_for`, payload);
- proposed resources and views;
- scoped stewardship assignments;
- omitted candidates and starter-suggestion gaps;
- estimated costs;
- unresolved trade-offs.

The human approves or overrides the recommendation. Overrides and rationale are
recorded so later agents do not mistake them for accidental inconsistency.

### 9. Materialize and validate

The approved design resolves to a local contract and backend bindings.
Validation checks semantic constraints, required dimensions and relationships,
stewardship conflicts, view lineage, backend capabilities, and lifecycle
invariants.

## Runtime procedure

At runtime, resources, records, and views are loaded and written according to
their policies:

1. Read the project catalog and active continuity view.
2. Route task-specific resources and records by relevance rather than loading
   everything.
3. Capture events, observations, decisions, and commitments at the moment they
   occur.
4. Preserve compound source resources and link typed records to them.
5. Refresh replicas and current views at their declared trigger.
6. Advance records only through pattern-derived lifecycle transitions.
7. Preserve provenance, basis, epistemic status, effective time, and
   supersession relationships as required.
8. Generate cross-cutting human or agent views on demand.
9. Validate semantic and lifecycle constraints at session boundaries and before
   publishing.

The system should make the correct capture moment easy and delayed
retrospective capture conspicuous.

## Reassessment

The design is reassessed when the shape of the project materially changes, not
on every session and not only after failure.

Candidate triggers include:

- a single agent becomes multiple agents;
- a prototype becomes a production system;
- external research becomes a significant part of the work;
- the repository becomes expensive to navigate;
- an external platform becomes or stops being canonical;
- sensitivity or role boundaries change;
- concurrent writers are introduced;
- recurring artifact friction exceeds the value of the current design;
- a needed type or view is missing from the current roster.

Reassessment produces a recommendation for human approval. It does not silently
rewrite the roster.

## Backend-neutral storage model

The semantic contract is independent of storage. Backends advertise
capabilities needed by artifact policies, such as:

- stable resource and semantic-record identifiers;
- read, list, and relationship queries;
- append with audit history;
- conditional mutation by revision and lifecycle state;
- supersession links;
- provenance and source revisions;
- history or immutability verification;
- atomic writes;
- access control;
- query and generated-view support.

A Git-backed filesystem can provide the initial adapter:

- paths bind resource and record identities;
- commits provide revisions and history;
- diffs support append-only validation;
- Markdown supports human review;
- repository distribution supports cold readers.

Future adapters could use a database, object storage, issue tracker, notebook
system, or knowledge service. They must provide the capabilities required by
the bound record and resource contracts. A backend that cannot verify
append-only history, for example, cannot safely host immutable occurrence
records without another audit mechanism.

The model uses `preserve`, `observe`, `assert`, `propose`, `decide`, `commit`,
`append`, `transition`, `supersede`, `retract`, and `derive` as logical
operations. Git commits and files are one implementation substrate, not their
definition.

## Example

Consider a multi-session service integrating several uncertain vendor APIs.
Assessment finds high discontinuity, high external investigation, moderate
decision density, high verification cost, low orientation cost, and no current
production operations.

The recommended types are declared from patterns: session position and
commitments, work items and acceptance, investigation observations and
findings, decisions. Orientation and operations types are omitted.

The resolved model might contain:

- current-position claims and active commitments composed into a handoff view;
- proposals and commitments composed into a plan view;
- acceptance-criterion definitions with an adopted effective status;
- decision records linked to the proposals they resolved;
- failed-attempt event records linked to observations and conclusions;
- investigation finding claims with provenance and epistemic status;
- verification observations linked to criteria and tested revisions.

A codebase map is rejected because the repository remains cheap to inspect. An
incident type is rejected because the service is not yet deployed. Handoff,
plan, and status documents are generated views rather than independent
authorities.

When the service enters production, reassessment may add incident and
intervention types. When the codebase becomes expensive to navigate,
reassessment may add an orientation replica pinned to source revisions.

## Contract fixture exercise

This exercise tests whether the same session roster — declared independently
from patterns on each project — resolves for three unlike projects without
hiding domain differences in overrides. Types compile from reusable semantic
traits. Views bind roles by occupant and optional trait/payload interface.
The same files are the provisional project-contract format; the three
fixtures remain the regression harness, not a universal contract linter.

### Shared semantic traits

| Trait | Base kind | Bundles | Storage |
|---|---|---|---|
| `entity` | — | identity, kind, subject | — |
| `stewarded` | — | stewardship | — |
| `current-claim` | claim | as-of time, epistemic status, `active → superseded` | conditional mutation + history |
| `active-undertaking` | commitment | deontic status, `active → completed, cancelled, superseded` | conditional mutation + history |
| `open-question` | question | `open → answered, deferred, closed` | conditional mutation |
| `occurrence` | — | provenance, time; original stays `recorded`; correction status derived from successor | append with audit |
| `evidence-linked` | — | `informed_by` relationship only | — |
| `epistemic-claim` | claim | provenance, `asserted → supported, disputed, refuted, retracted` | conditional mutation + history |

`current-claim`, `epistemic-claim`, `active-undertaking`, and `occurrence` are
pairwise incompatible. A subtype composes compatible traits plus extra payload
and operational policy.

**Trait-composed records.** A trait-composed definition (experimental candidates, tests) may specify only:
`name`, `traits`, `payload`, `capture`, `read_policy`, and `base_kind` when no
trait supplies one. Lifecycle, required dimensions, relationships, storage
capabilities, update/correction/contradiction semantics, and correction-status
derivation come exclusively from traits. The resolver rejects trait-composed records
that restate trait-owned fields. Bundle capture templates may declare links
between co-captured records, but each link type must be advertised by the
source record's traits; the link is written on the source record during
capture. Bundles do not override trait semantics or become authorities.

### Shared session-position types

Each fixture declares these position types from patterns:

| Subtype | Traits | Extra payload | Lifecycle from |
|---|---|---|---|
| `current-position` | entity, stewarded, current-claim | position, scope | current-claim |
| `active-goal` | entity, stewarded, current-claim | goal, scope | current-claim |
| `next-action` | entity, stewarded, current-claim | next, scope | current-claim |
| `active-commitment` | entity, stewarded, active-undertaking | actor, outcome, owner, effective time, scope | active-undertaking |
| `continuity-question` | entity, stewarded, open-question | owner, blocking, scope | open-question |

`handoff` is a view. Its roles require traits and payload fields, not type names:

| Role | Required traits | Required payload | Default occupant |
|---|---|---|---|
| `goal` | entity, stewarded, current-claim | goal, scope | `active-goal` |
| `position` | entity, stewarded, current-claim | position, scope | `current-position` |
| `next` | entity, stewarded, current-claim | next, scope | `next-action` |
| `commitment` | entity, stewarded, active-undertaking | scope | `active-commitment` |
| `blocking-question` | entity, stewarded, open-question | blocking, scope | `continuity-question` |

Goal, position, and next all use `current-claim`. Payload requirements keep them
from occupying each other's roles.

Optional bundle `session-continuity` captures the five records together at a
session boundary. It is a write convenience, not an authority. The same local
bundle name may appear in another namespace; project designs reference
bundles by qualified id (`project:session-continuity`, etc.).

### Shared investigation types

Each fixture declares these investigation types from patterns:

| Subtype | Traits | Extra payload | Lifecycle from |
|---|---|---|---|
| `investigation-question` | entity, stewarded, open-question | motivation, owner | open-question |
| `investigation-observation` | entity, occurrence | source, observed time, environment, what was observed | occurrence |
| `finding` | entity, epistemic-claim | claim, basis, invalidated when | epistemic-claim |
| `failed-attempt` | entity, occurrence, evidence-linked | attempted action, retry when | occurrence |

A failed attempt is atomic: it records only what was tried and when retry may
be reconsidered. Associated observations and conclusions are separate records
linked through the `abandoned-path` bundle, not embedded payload on the
attempt itself.

`investigation-question` and `continuity-question` share the same traits. They
remain distinct records because payload, read policy, and default view
occupancy differ. `investigation-observation` and `failed-attempt` share
`occurrence` and are distinguished by base kind.

`investigation-summary` roles:

| Role | Required traits | Default occupant |
|---|---|---|
| `question` | entity, open-question | `investigation-question` |
| `observation` | entity, occurrence; observation | `investigation-observation` |
| `finding` | entity, epistemic-claim | `finding` |
| `failed-attempt` | entity, occurrence; event | `failed-attempt` |

Optional bundles `abandoned-path` and `concluded-investigation` capture the
usual multi-record write sets. The `abandoned-path` bundle writes a failed
attempt and its supporting observation together, declaring that the attempt
`informed_by` the observation. Bundles are capture conveniences, not
transaction guarantees or authorities. Correction still creates a successor
with a `corrects` link; the original occurrence stays in `recorded` state and
its effective correction status is derived from the successor, not from
mutating the original under `append_with_audit` alone.

### Fixture A: ParcelPipe software service

ParcelPipe imports orders from several vendor APIs. Work spans multiple agents,
and external behavior is uncertain.

Assessment:

- discontinuity: high;
- external investigation: high;
- decision density: medium;
- orientation cost: low;
- operational risk: low before launch.

Resolved continuity records:

- project and integration workstream positions;
- commitments to implement individual import paths;
- blocking questions about vendor behavior;
- a handoff view grouped by integration.

Resolved exploration records:

- questions about API ordering, retries, and identifiers;
- observations tied to API version, request fixtures, and environment;
- findings with vendor documentation or experiment output as provenance;
- failed implementation approaches with changed conditions for retry;
- an investigation summary grouped by vendor.

Project bindings:

- Git-backed Markdown resources;
- source revisions use commits for code and dated API versions or URLs for
  vendor material;
- the handoff view is generated into the agent's session context.

No project override is needed for the semantic records. Vendor-specific source
identifiers are binding configuration, not schema changes.

Result: the shared session roster resolves cleanly. ParcelPipe also declares
`work-item` as `current-status`, `acceptance` as `definition`, and
`check-run` as `event`. A decision type remains a gap, not a blocker.

### Fixture B: ML research project

The project compares model architectures across evolving datasets. Runs occur
over several weeks and may be resumed by different agents.

Assessment:

- discontinuity: high;
- investigation and failed work: high;
- provenance and reproducibility requirements: high;
- decision density: medium;
- operational risk: low.

Resolved continuity records:

- the currently active research question and workstream position;
- commitments to run or analyze specific experiments;
- blocking questions about data quality or evaluation;
- a handoff view grouped by study.

Resolved exploration records:

- investigation questions about libraries, data behavior, and analysis methods;
- observations linked to notebook, dataset, code, environment, and run
  resources;
- findings with epistemic status and invalidation conditions;
- failed tooling or analysis approaches;
- an investigation summary grouped by research question.

The shared investigation types are insufficient for experimental science by themselves:

- a protocol is a versioned definition, not merely an investigation question;
- an experiment run is an event with exact inputs, parameters, seeds,
  environment, and outputs;
- a negative result is not automatically a failed attempt;
- dataset and model lineage need stronger resource contracts;
- independent replication differs from rerunning the same computation.

These are not appropriate silent overrides because they recur across research
projects. Later research types should occupy existing roles by composing
the same traits, or add types that do not fit those roles:

- `hypothesis` would occupy `investigation-summary.finding` by providing
  `entity` and `epistemic-claim`, plus preregistration payload;
- `experimental-observation` would occupy `observation` by providing
  `entity` and `occurrence`, plus run and instrument payload;
- `experiment-run` and `protocol` would not occupy current roles: a
  reproducible run is not an occurrence-correction contract, and a protocol
  is a definition.

Result: the shared roster resolves with default occupants. Future
research types bind through traits, not by forking these contracts.

### Fixture C: production incident response

A team operates a payment service during a live availability incident. Several
agents investigate, coordinate mitigation, and prepare a postmortem.

Assessment:

- discontinuity and concurrency: high;
- investigation: high;
- decision and commitment density: high;
- operational risk and urgency: high;
- read latency: critical;

Resolved continuity records:

- current impact, response phase, and workstream positions;
- active mitigation and investigation commitments with owners;
- blocking questions;
- a compact handoff view grouped by response role.

Resolved exploration records:

- diagnosis questions;
- monitoring and command observations tied to time and source;
- diagnosis claims with support, contradiction, and confidence;
- failed diagnostic or mitigation attempts;
- an investigation summary ordered by current relevance.

The shared roster does not model the entire incident:

- an incident has severity, commander, phase, and declaration/resolution
  transitions;
- a mitigation is an authorized intervention, not merely a failed or successful
  attempt;
- operational decisions may require explicit approval authority;
- the timeline is an event projection with strict ordering;
- postmortem actions become commitments with organizational ownership.

These recurring semantics belong in later operations types. They would occupy
existing roles by composing the same traits, or add types that do not fit:

- `incident-position` would occupy `handoff.position` by providing
  `current-claim`. Phase, severity, and commander are extra payload, not a
  replacement lifecycle;
- `diagnosis` would occupy `finding` by providing `epistemic-claim`;
- `intervention` would occupy `handoff.commitment` by providing
  `active-undertaking`, plus authorization payload;
- `incident` would not occupy the position role: declaration and resolution
  are not `active → superseded`;
- `incident-event` would not occupy `failed-attempt`: timeline events need
  their own role.

Result: the shared roster resolves with default occupants. Operations
types can bind through traits without forking these contracts.

### Findings from the fixtures

The exercise supports several parts of the design:

1. **The same pattern roster composes.** The same session types provide useful
   records across all three projects without pretending to define the whole
   project.
2. **Views absorb presentation differences.** Handoff roles are the same
   trait requirements in all three projects. Grouping and ordering are
   project parameters.
3. **Bindings absorb storage differences.** Source identifiers and revisions
   vary without changing semantic contracts. The resolver checks that the
   backend advertises every capability the composed records require.
4. **Project overrides should be rare.** Repeated domain requirements are
   future types that occupy roles by trait, or new types that do not fit
   current roles.
5. **Refinement is trait occupancy, not subtype inheritance.** A later type
   may occupy `handoff.position` only if it provides `current-claim`. If it
   needs a different lifecycle, it is a new type and cannot fill that role.
6. **Base kinds are plausible but not yet proven minimal.** Event, observation,
   claim, question, and commitment were exercised directly. Proposal, decision,
   instruction, and definition appear in uncovered domain requirements and
   should be tested through later types.

### Machine-readable fixtures

The tables above are encoded under `design/contracts/`:

- `catalog.json` declares document-format, catalog, trait, and backend versions
  plus baseline backend capabilities (`stable_ids`, `read`, `list`);
- `traits.json` is the shared semantic trait catalog;
- `backends.json` advertises storage capabilities and explicit writer,
  atomicity, conflict-detection, multi-record, and durability guarantees;
- project designs declare pattern records, views, and bundles;
- `fixtures/` are project designs: a required `source_lock` (catalog version
  and canonical digests of catalog, traits, and backends), backend,
  namespace-qualified view-parameter references, optional occupancy
  overrides, experimental candidates, and gaps for genuinely unresolved
  future types;
- `resolve.py` generates `resolved/<project>.json` and is the format
  validator for project designs;
- `validate.py` is the three-fixture regression harness: occupancy, backend
  match, source locks, and negative cases.

```bash
python3 design/contracts/validate.py
```

The three designs use `adaptive-artifacts/project-design@0.3.0` and trait
catalog `0.3.0` / backend catalog `0.4.0`. Each fixture carries a required
`source_lock` whose canonical digests must match the current catalog,
traits, and backends before resolution proceeds; stale digests are rejected. Resolved contracts echo the lock, record a
`design_digest` over the canonical project design input, and list digests
only for the pinned semantic sources. Gaps name only genuinely unresolved
future types; executable fixture-local `experimental_candidates` validate
`role_compatibility` without duplicating those types as gaps or selecting
them as default occupants. `ephemeral-memory` is rejected because exploration
occurrences require `append_with_audit`. Composing `current-claim` with
`occurrence` is rejected as a lifecycle and storage conflict.

This is the executable v0.2 project-contract format, documented in
`design/contracts/README.md`.

### Draft composition rule

A project type is a named pattern plus extra payload and operational policy. View roles declare required traits, optional base kind and
payload interface, and an explicit selection predicate. The resolver occupies
a role with the default record unless the project selects another candidate
that satisfies the complete role interface.

**Incompatible traits do not compose.** `current-claim` and `occurrence` cannot
appear on one subtype: one rewrites a current representation, the other
appends a correctable event. The same check rejects a backend that cannot
provide the union of baseline and trait-derived storage capabilities.

**Namespace-qualified identifiers.** Records, views, and bundles resolve to
`project:name` identifiers. Project designs and resolved contracts use
qualified ids for bundles, view parameters, occupancy overrides, and role
occupants. Experimental candidates may use another namespace (`research:`,
`operations:`) to prove role compatibility without becoming occupants.

**Reproducible resolution.** Each project design carries a required
`source_lock`: catalog version, canonical digest of `catalog.json`, and
canonical digests of traits and backends.
Whitespace-only JSON edits do not change digests. Resolution fails when any
locked digest does not match the workspace. The resolved `resolution` block
echoes the lock, records `design_digest` over the canonical project design
input, and lists digests only for the pinned semantic sources.

**Occurrence correction is append-only.** The original stays `recorded`.
A successor with a `corrects` relationship carries the correction; effective
`corrected` status is derived from that link, not from mutating the original
under `append_with_audit` alone.

**Role compatibility is not selection.** `incident-position` can satisfy
`project:handoff.position` because it provides `current-claim`; phase is
extra payload. An `incident` record with declare/resolve states is a new type
and does not satisfy that role. Fixture-local experimental candidates prove
compatibility for research and operations types without becoming the selected
default occupant.

**View selection is contractual.** v0.2 supports conjunctions of equality
clauses over `lifecycle_state` and one-level `payload.<field>` paths. Empty
conjunctions explicitly select every record of the occupant type. A predicate
must be valid for every compatible occupant. Consequently,
`handoff.blocking-question` requires a `blocking` payload field; a generic
open question without that field is not a compatible occupant.

**Backend guarantees are contractual.** The Git-filesystem binding declares
one writer, atomic per-record replacement, revision-token conflict detection,
non-transactional multi-record writes, and working-tree durability. These are
reported in resolved contracts rather than left as runtime assumptions.

**Correction is not contradiction.** `occurrence` corrects by successor
record with derived status. `epistemic-claim` contradicts with a separate
record and an epistemic transition.

**Bundles are optional capture templates.** They group records commonly
written together and may declare links between them. Each link type must be
advertised by the source record's traits and both endpoints must belong to
the bundle. The link is written on the source record during capture. Bundles
do not guarantee atomic multi-record writes and do not create a fourth
authority beside resources, records, and views.

Still unresolved:

- whether a multi-writer backend and stronger transaction capability are
  necessary beyond the explicit single-writer v0.2 boundary;
- how an editable handoff view would resolve writes into the underlying
  records;
- which traits belong in the shared catalog versus a later pattern;
- whether experimental candidates should graduate into declared project types
  or remain fixture-local.

## Runtime (`tools/artifacts.py`)

The shipped installer exercises the resolved contract. This repo declares its session types from patterns. Project design,
resolved contract, and the optional live store share `.artifacts/`.


### What it proves

- A runtime can consume `resolved-contract.json` from `resolve.py` instead of
  hard-coding lifecycle tables; store `meta.json` pins the contract digest and
  rejects drift on every store+contract command.
- Continuity record types (`current-position`, `active-goal`, `next-action`,
  `active-commitment`, `continuity-question`) can be stored as JSON collections with stable IDs,
  contract-derived lifecycle transitions, canonical revision tokens, and
  supersession via new record IDs (not in-place `update` to `superseded`).
- Exploration record types (`investigation-question`, `investigation-observation`,
  `finding`, `failed-attempt`) run in the same store. Occurrences are
  append-only: correction creates a successor with `corrects`, and the original
  stays `recorded`. Findings use epistemic transitions and separate-record
  contradiction. `abandoned-path` writes `informed_by` at capture time.
- Records whose contract requires `history` archive the exact prior revision in
  an append-only store area before mutation. Append-only types archive the
  create revision as their audit snapshot.
- Conditional writes reject stale revisions without mutating store files.
- Store `meta.json` pins the contract digest; every normal store command requires
  initialization and rejects contract drift. Hooks skip only when the store is
  truly absent; partial stores without valid meta error.
- Path components (record types, IDs, history layout) are validated before use.
- History archives are content-addressed, retry-idempotent, and layout-validated.
- View rendering, role occupancy, grouping, and selection predicates come from
  the resolved contract. `project:handoff` is one view, not a runtime invariant.
- Session hooks emit derived views at start and validate the store at stop.

### What it does not prove

- Delivery, decision, research, or operations type packs as a catalog; external
  dependencies; multi-file transactions; or automatic Git commits.
- Handoff-only resume: trials stayed at median confidence 3/5. Adding
  protocol (this repo's rule / skill) with the derived views is the session
  packet. Do not dual-write a STATE snapshot.

### Commands

```bash
# Print source_lock (never type digests by hand)
adaptive-artifacts lock

# Materialize frozen contract from .artifacts/project-design.json
adaptive-artifacts resolve

# Initialize store (git context required; default store .artifacts/, override with --store, --root, or ARTIFACTS_STORE)
adaptive-artifacts init

# Record operations
adaptive-artifacts create --type project:current-position --subject PROJECT --payload '{"position":"…","scope":"…"}'
adaptive-artifacts supersede --type project:current-position --id REC_ID --expected-revision sha256:… --payload '{"position":"…","scope":"…"}'
adaptive-artifacts update --type project:continuity-question --id REC_ID --transition answered --expected-revision sha256:…
adaptive-artifacts correct --type project:investigation-observation --id REC_ID --payload '{…}'
adaptive-artifacts capture --bundle project:abandoned-path --records '[{…},{…}]'
adaptive-artifacts handoff [--out views/handoff.md]
adaptive-artifacts view [--id project:investigation-summary] [--out views/investigation-summary.md]
adaptive-artifacts validate

# Hook adapters (read-only / validate-only)
adaptive-artifacts hook-start
adaptive-artifacts hook-stop
```

```bash
python3 -m unittest discover -s tools/runtime/tests
python3 design/contracts/validate.py
```

### Known limitations

- Single-writer assumption: each record and history file is atomically written,
  but supersede and other multi-record operations are not transactional. An
  interrupted supersede is detected as invalid and requires deliberate
  recovery from Git or another known-good copy.
- `init` is idempotent only when the existing store pins the same contract digest;
  it refuses to rebind or init over a partial store.
- Git backend confirms repository context only; Git history supplements but
  does not replace the store's append-only revision archive for contract-bound
  records.
- The v0.2 predicate grammar intentionally supports only conjunction and
  equality over lifecycle state and one-level payload fields.
- View presentation is generic title-case over contract role names, not a
  type-pack-specific template language.
- Malformed JSON in records/history surfaces as validation errors where
  practical; not every read path wraps all I/O failures as validation output.

## Relationship to the current project

If adopted, this design changes the foundation rather than adding another layer
to the existing system:

- files stop being assumed to be the unit of semantic classification;
- resources, semantic records, and views become separate concepts;
- the three original axes become design lenses rather than exclusive schema
  enums;
- snapshot versus ledger becomes one possible storage policy;
- presets become pattern-declared project types with derived lifecycles;
- project initialization becomes assessment and recommendation;
- the manifest becomes a catalog, stewardship registry, source lock, resource
  index, view registry, and backend binding;
- schema validation gains semantic, provenance, lifecycle, and stewardship
  constraints;
- redesign becomes triggered reassessment;
- Git-specific rules move behind a storage adapter contract.

No compatibility promise is made yet. The semantic model should first be tested
against several unlike projects to discover whether the shared base kinds,
pattern types, record dimensions, and resource/view split describe real work
without excessive fragmentation.

## Anti-goals

This system is not:

- a universal project-management workflow;
- a requirement that every project maintain extensive documentation;
- a replacement for code, issue trackers, or domain systems that already own
  their information;
- a transcript archive;
- an unbounded knowledge base;
- a requirement to physically split compound source documents into atomic
  files;
- a claim that every record uses every semantic dimension;
- a universal lifecycle shared by unrelated domains;
- a live inheritance system that silently changes project contracts;
- a claim that agent judgment can be replaced by a scoring formula;
- a commitment to Git or repository-local storage forever;
- a closed type catalog that is the only way to obtain a type.

## Open questions

- Is the shared base vocabulary sufficient, or are some kinds redundant?
- What is the right granularity for a semantic record in practical agent work?
- How should editable composite views resolve changes into atomic record
  operations?
- Which semantic dimensions belong in the universal core versus a later
  trait?
- What is the smallest useful shared session roster?
- How should later types share a view? The fixture draft: compose via
  patterns, occupy roles by trait and payload.
- Which traits belong in the shared catalog versus a later pattern?
- Which reassessment triggers can be detected mechanically?
- How should correction, retraction, and supersession work across backends?
- What concurrency guarantees are required for current canonical records?
- How should restricted and blinded resources and records participate in
  derived views without leaking information?
- How should partial coverage and unknown information propagate through views?
- What evidence demonstrates that an artifact saves more than it costs?
- Which parts of the existing implementation remain valuable after the
  conceptual rewrite?
