---
{
  "base_kind": "instruction",
  "id": "rec-9764d49a-c885-4c7b-a2c5-d6df7b496c4e",
  "identity": "unknown",
  "lifecycle_state": "recorded",
  "payload": {
    "effort": "aa-cli-ergonomics",
    "executor": "inline",
    "work_item": "short-name-resolution"
  },
  "provenance": {
    "sources": [
      "short-name-resolution"
    ]
  },
  "record_type": "project:assignment",
  "recorded_at": "2026-10-14T09:30:23+00:00",
  "relationships": {},
  "revision": "sha256:79c5c4e1faf10fcf17af4f05ee71cbea44be32bbf1d1dea4ea5ae304cbb5c3f8",
  "subject": "short-name-resolution",
  "time": {
    "observed": "2026-10-14T09:30:23+00:00",
    "recorded": "2026-10-14T09:30:23+00:00"
  }
}
---

## Orientation

Worktree: /home/andrewyin/adaptive-artifacts--aa-cli-surface. Store writes stay on primary checkout.

### Requirements
R2: Universal short type/view/bundle names; ambiguous/unknown fail structurally.

### Design invariants
- Qualified names remain valid.
- Short-name resolution is shared across mutators and readers.
