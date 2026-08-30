# Preset: failures

What was tried and abandoned, why, and what that rules out. Highest
value-per-byte type: the only one that prevents re-*spending* effort.
Written **at the moment of abandonment, before starting the next approach**
— never at session end, never backfilled. Retrospective entries are
sanitized fiction.

Threshold: log if rediscovery would cost more than ~15 minutes or the
failure is non-obvious. Typos and wrong flags don't qualify.

## Schema

```json
{
  "name": "failures",
  "version": 1,
  "purpose": "Dead ends: what was tried, what happened, what that rules out",
  "discipline": "ledger",
  "layout": "collection",
  "path": "failures",
  "id_format": "NNN-slug",
  "fields": [
    { "name": "Attempted", "required": true, "hint": "concrete enough to recognize the approach if reconsidered" },
    { "name": "Observed", "required": true, "hint": "exact error/output/measurement, verbatim over paraphrase" },
    { "name": "Cause", "required": true, "hint": "confirmed|suspected — the inference" },
    { "name": "Rules out", "required": true, "hint": "what not to retry, and under what changed conditions it becomes viable" }
  ]
}
```

"Rules out" is the payoff field: *"don't use library X"* is weaker than
*"don't use X for streaming — it buffers fully; fine for small payloads."*

## Entry template (`failures/003-alb-idle-timeout.md`)

```markdown
# ALB idle timeout kills websockets (2026-09-02)

**Attempted:** `ws://` endpoint on events service, client
reconnect-with-backoff, deployed to staging behind existing ALB.

**Observed:** connections dropped at exactly 60s idle regardless of client
keepalive; ALB logs show idle timeout closing them.

**Cause:** confirmed — ALB idle timeout is 60s, shared, infra declined to
raise it (INFRA-412).

**Rules out:** websockets through *this* ALB. Viable again if events
service gets its own NLB, or if sub-60s app-level ping is acceptable
(rejected: mobile battery).
```

Bad entry (unfalsifiable, saves nobody time): *"Tried websockets, didn't
work, went with polling."*
