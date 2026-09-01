# Preset: findings

Standalone positive knowledge: what an investigation established. The
complement of failures — that type captures what was ruled *out*; this one
captures what was learned. Distinct from evidence, which grounds a claim
already being made elsewhere and demands a reproduction procedure; a
finding is its own payoff — how a library actually behaves, what a case
study showed, what a comparative read of the options concluded.

Threshold: log if learning it cost real effort (reading, tracing,
experimenting) **and** a future session would plausibly need it. A
bookmark or a fact one search away doesn't qualify.

Findings decay in a way failure entries don't: a failure is a historical
fact, a finding is a claim about the world — libraries upgrade, code
moves, vendors change terms. Basis pins what the finding was true *of*;
Expires when says what would void it.

## Schema

```json
{
  "name": "findings",
  "version": 1,
  "purpose": "What investigations established: durable positive knowledge with its basis",
  "discipline": "ledger",
  "layout": "collection",
  "path": "findings",
  "id_format": "NNN-slug",
  "fields": [
    { "name": "Question", "required": true, "hint": "what prompted the investigation, as actually asked" },
    { "name": "Finding", "required": true, "hint": "the answer, stated falsifiably" },
    { "name": "Basis", "required": true, "hint": "how it's known: docs (version), code read (path @ commit), experiment, external source (link); long material in raw/" },
    { "name": "Expires when", "required": false, "hint": "what would invalidate this — an upgrade, a code change, time" }
  ]
}
```

Long source material (vendored docs excerpts, traces, notes) goes in
`findings/raw/`, referenced from Basis. Subdirectories are ignored by lint
field checks.

## Quality bar

Bad (vibes, unsourced, undecayable): *"Looked into queue libraries; BullMQ
seems like the best fit for us."*

Good: Question *"can we drop the Redis dependency by moving scheduled jobs
to pg-boss?"*; Finding *"yes for our volume — pg-boss handles cron +
retries natively, but max throughput is ~2k jobs/min on one worker,
~40x our peak"*; Basis *"pg-boss 10.1 docs (scheduling, retry sections);
throughput measured with bench script in raw/007-pgboss-bench.txt against
local Postgres 16"*; Expires when *"job volume approaches ~1k/min, or
pg-boss major version change."*
