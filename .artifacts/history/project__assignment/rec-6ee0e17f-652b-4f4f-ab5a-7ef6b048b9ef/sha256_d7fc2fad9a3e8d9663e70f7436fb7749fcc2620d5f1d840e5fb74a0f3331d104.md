---
{
  "base_kind": "instruction",
  "id": "rec-6ee0e17f-652b-4f4f-ab5a-7ef6b048b9ef",
  "identity": "unknown",
  "lifecycle_state": "recorded",
  "payload": {
    "effort": "aa-cli-ergonomics",
    "executor": "inline",
    "work_item": "discovery-hooks"
  },
  "provenance": {
    "sources": [
      "discovery-hooks"
    ]
  },
  "record_type": "project:assignment",
  "recorded_at": "2026-10-14T09:31:42+00:00",
  "relationships": {},
  "revision": "sha256:d7fc2fad9a3e8d9663e70f7436fb7749fcc2620d5f1d840e5fb74a0f3331d104",
  "subject": "discovery-hooks",
  "time": {
    "observed": "2026-10-14T09:31:42+00:00",
    "recorded": "2026-10-14T09:31:42+00:00"
  }
}
---

## Orientation

Worktree: /home/andrewyin/adaptive-artifacts--aa-cli-surface. Store writes stay on primary checkout.

### Requirements
R7: Worktree store discovery + session-hooks no-clobber.

### Design invariants
- Records authoritative; views derived.
- Qualified names and explicit revisions remain valid.
