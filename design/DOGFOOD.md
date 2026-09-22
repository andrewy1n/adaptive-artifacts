# Continuity dogfood protocol

> Historical trial log. The shipped CLI is now `tools/artifacts.py`; the store is `.records/`.

The repository's live store is `.continuity/`. `.artifacts/` was removed
after the Round 3 trial. The continuity store is tracked source data;
`.continuity/views/` is derived and must be regenerated rather than edited.

## Trial

Run for three real session boundaries. At each start:

1. Run `python3 tools/continuity.py hook-start`.
2. Give the worker the handoff text. Rounds 1–2: handoff only. Round 3: the
   worker may also read `.artifacts/STATE.md` and this file, and nothing else.
3. Ask for the current goal, position, next actions, active commitments, and
   blocking questions, plus a 1–5 resume-confidence rating.
4. Compare the answer with repository reality and `.artifacts/STATE.md`.

At each stop, mutate records only when their facts changed, regenerate the
handoff, and run `python3 tools/continuity.py hook-stop`.
Every continuity record in this trial carries `payload.scope` so `group_by:
scope` keeps related facts in one section. A contract digest change requires
deleting and re-initializing `.continuity/`; `init` will not rebind.

An interrupted supersede can leave an orphan that validation detects but the
CLI cannot repair. Treat that as a failed boundary, preserve the files for
diagnosis, and recover deliberately from Git or a known-good copy; do not
hand-edit revisions to make validation pass.

Pass bar: active-fact reconstruction and stale-fact exclusion both hold, no
repair, and median worker confidence is at least 4/5.

## Round 1 (handoff without goal/next)

| Boundary | Active facts correct | Stale/omitted facts | Worker confidence (1–5) | Record operations | Validation/repair | Notes |
|---|---:|---:|---:|---:|---|---|
| 1 | 2/2 | 0 stale as current; STATE goal/open omitted | 3 | 2 | none | Seed handoff. Worker reconstructed position and commitment; invented no blockers. Confidence dropped because trial count and resume procedure were absent. |
| 2 | 3/3 | 0; superseded B1 position stayed out | 3 | 2 | none | After position supersede plus a blocking question. Worker saw 1/3 progress and the blocker; still wanted scoring rubric and next actions. |
| 3 | 2/2 | 0; answered blocker and completed work stayed out | 3 | 3 | none | After answering the blocker. Worker kept it closed, reconstructed 2/3 plus next action, still rated 3/5. |

Verdict: **did not pass**. Active-fact reconstruction and stale-fact exclusion both held. No repair. Mean 2.3 record operations per boundary. Median confidence **3/5**, below the 4/5 bar. Putting trial progress into `current-position` raised status fidelity but did not raise confidence: workers still wanted goal, rubric, and procedure that live in `.artifacts/STATE.md`.

During the three simulated boundaries, `STATE.md` still said the trial had not started. That lag is a dual-write omission, not a continuity validation failure. Continuity was current; STATE was stale until that session's end rewrite.

## Round 2 (typed goal/next slots)

Continuity family `0.6.0` adds `active-goal` and `next-action` as distinct
`current-claim` records. Payload requirements keep them from occupying the
position role. This round tests whether those slots raise median confidence to
4/5 without turning the handoff into a STATE duplicate.

| Boundary | Active facts correct | Stale/omitted facts | Worker confidence (1–5) | Record operations | Validation/repair | Notes |
|---|---:|---:|---:|---:|---|---|
| 1 | 5/5 | 0; non-blocking dual-write question stayed out | 3 | 2 | none | Seed handoff with goal/next. Worker reconstructed all five slots; still wanted rubric, store location, and Round 1 details. |
| 2 | 5/5 | 0; superseded B1 position and next stayed out | 3 | 2 | none | Worker saw 1/3 progress and the new next; still wanted rubric, Round 1 details, and mutation procedure. |
| 3 | 5/5 | 0; superseded B2 position and next stayed out | 3 | 5 | none | Worker kept 2/3 and Score Boundary 3; still wanted rubric/procedure and treated the missing B3 packet as a gap. |

Verdict: **did not pass**. Reconstruction and stale-fact exclusion both held at 5/5. No repair. Mean 3.0 record operations per boundary. Median confidence **3/5**, unchanged from Round 1. Typed goal/next made the handoff complete as a fact list and did not raise resume confidence: workers still wanted scoring rubric and procedure from DOGFOOD.md / STATE.md. Goal and next now dual-write STATE's Goal and Next.

The blocking question is answered: median confidence did not reach 4/5. The non-blocking dual-write question is answered: adding the slots duplicates STATE fields and adds a second writer for the same facts.

## Round 3 (handoff + STATE.md + DOGFOOD.md)

Workers receive the derived handoff and may read `.artifacts/STATE.md` and
this file. No other files. Keep STATE in sync with continuity at each
boundary so the packet matches the intended architecture (handoff supplements
STATE). Count continuity record operations as before; note STATE rewrites
separately.

| Boundary | Active facts correct | Stale/omitted facts | Worker confidence (1–5) | Record operations | Validation/repair | Notes |
|---|---:|---:|---:|---:|---|---|
| 1 | 5/5 | 0; used STATE next list and DOGFOOD rubric | 4 | 2 | none | Worker reconstructed all five slots, cited Round 1–2 history and pass bar. Confidence 4/5: could not verify live store files. |
| 2 | 5/5 | 0; superseded B1 start position stayed out | 4 | 2 | none | Worker saw 1/3 and the new next; still 4/5 because live store files are outside the packet. |
| 3 | 5/5 | 0; superseded 1/3 position stayed out | 4 | 4 | none | Worker kept 2/3 and Score Boundary 3; still 4/5 because live store files are outside the packet. |

Verdict: **passed**. Reconstruction and stale-fact exclusion both held at 5/5. No repair. Mean 2.7 continuity record operations per boundary, plus one STATE rewrite each boundary. Median confidence **4/5**. The remaining gap is the same each time: workers cannot verify `.continuity/` files from the allowed packet. That is expected; the derived handoff is the store view.

The blocking question is answered: yes, median confidence reached 4/5 once STATE and DOGFOOD were readable. Handoff-only (rounds 1–2) did not.

## Current seed

Round 3 complete. Position records the passed 4/5 bar. `.artifacts/` has
been removed; this repo's live store is `.records/` and the session
packet is generated views plus the repo rule. v0.2 packaging shipped the runtime; it was later renamed to `tools/artifacts.py`.
