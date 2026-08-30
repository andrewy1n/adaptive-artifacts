# Preset: evidence

Raw output grounding a claim. Written while the output is still in context —
the moment "tests pass" / "X is 3x faster" / "migration is idempotent"
enters state, plan, or a report, the grounding lands here.

## Schema

```json
{
  "name": "evidence",
  "version": 1,
  "purpose": "Verbatim output grounding claims, with reproduction procedure",
  "discipline": "ledger",
  "layout": "collection",
  "path": "evidence",
  "id_format": "NNN-slug",
  "fields": [
    { "name": "Claim", "required": true, "hint": "the exact claim, as stated where it's used" },
    { "name": "Procedure", "required": true, "hint": "command or steps sufficient to re-run" },
    { "name": "Output", "required": true, "hint": "verbatim, trimmed to the relevant part; long output in raw/" },
    { "name": "Context", "required": true, "hint": "commit hash + environment notes affecting reproducibility" }
  ]
}
```

Long raw output goes in `evidence/raw/<id>-<slug>.txt`, referenced from the
entry's Output field. Subdirectories are ignored by lint field checks.

## Quality bar

Bad (asserts, doesn't ground): *"The new query is much faster. Verified
locally."*

Good: Claim *"batched lookup reduces p50 340ms→31ms (plan, item 4)"*;
Procedure `python bench/query_bench.py --rows 2000000 --runs 50` on seeded
snapshot; Output verbatim p50/p95 lines; Context *"commit 4f2a91c, local
Postgres 16, prod-like indexes; not yet measured under prod load."*
