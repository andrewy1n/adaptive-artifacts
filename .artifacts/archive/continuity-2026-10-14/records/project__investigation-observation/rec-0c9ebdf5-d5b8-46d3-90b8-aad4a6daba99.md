---
{
  "base_kind": "observation",
  "id": "rec-0c9ebdf5-d5b8-46d3-90b8-aad4a6daba99",
  "identity": "unknown",
  "lifecycle_state": "recorded",
  "payload": {
    "environment": "live session capture in adaptive-artifacts repo",
    "observed_time": "2026-10-14T08:06:00+00:00",
    "source": "tools/runtime/validation.py:456-498 and tools/artifacts.py:1504-1520 (cmd_hook_stop)",
    "what_was_observed": "When <store>/views/*.md files are tracked in git HEAD, regenerating views after record writes causes validate_immutability (validation.py:456-498) to fail with immutability violation: committed store path modified or deleted (git status M): .artifacts/views/handoff.md, while NOT regenerating them causes cmd_hook_stop (artifacts.py:1504-1520) to fail with stale_views. Commit f392f74 exempted op-log-backed record rewrites under records/ so hook-stop would not depend on git commit hygiene, but did not exempt derived views under views/."
  },
  "provenance": {
    "sources": [
      "tools/runtime/validation.py:456-498 and tools/artifacts.py:1504-1520 (cmd_hook_stop)"
    ]
  },
  "record_type": "project:investigation-observation",
  "recorded_at": "2026-10-14T08:05:21+00:00",
  "relationships": {},
  "revision": "sha256:9f7e3c90dec2fde923da1b5a9c9ff3eeffd890501bac3d3496663ae28de6ff64",
  "subject": "adaptive-artifacts",
  "time": {
    "observed": "2026-10-14T08:06:00+00:00",
    "recorded": "2026-10-14T08:05:21+00:00"
  }
}
---

