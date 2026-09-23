"""Append-only per-record operation log underneath the materialized record store.

Each record's mutation history is its own chain of immutable op files under
`log/<type_dir>/<record_id>/`. Appending a file is the only write this module
performs; there is no shared file that a writer reads and then rewrites.

A conflicting op (`create` over a live record, `write` against a stale
`expected_revision`) must be decided against the exact state that precedes
it, but that state can't be read once and trusted -- another writer may land
an op in the gap between the read and the append. So `append_resolved_op`
folds up front, decides, and bakes the outcome and resulting record straight
into the op file, then claims the *exact* next sequence slot with `os.link`
(atomic and exclusive: it fails with `FileExistsError` if the name is
already taken). A collision means some other op landed in that slot first,
so this op's decision was made against a prefix that's no longer current --
the whole read-decide-claim cycle just retries against the now-current
chain. Landing the exact next slot proves nothing appeared between the read
and the claim, so the baked decision is correct the instant it commits.

Because the outcome is already decided and stored in the op itself, folding
a chain is just replaying "apply every accepted op's record, in seq order"
-- no re-derivation, so any process folding the same files reaches the same
answer. It also means nothing -- not even the op's own writer -- ever needs
to revisit a specific earlier slot to learn what happened to it, only ever
"what is the current state", which remains answerable from whatever files
happen to exist. That is what makes it safe for a checkpoint to prune an
older slot immediately: a writer that appended it and is about to fold the
chain again never needs that exact file back.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Callable

OP_SUFFIX = ".op.json"
CHECKPOINT_KIND = "checkpoint"
_SEQ_WIDTH = 12

Decision = tuple[str, Any, dict[str, Any]]


class OpLogError(Exception):
    pass


def _seq_name(seq: int) -> str:
    return f"{seq:0{_SEQ_WIDTH}d}{OP_SUFFIX}"


def _parse_seq(name: str) -> int | None:
    if not name.endswith(OP_SUFFIX):
        return None
    digits = name[: -len(OP_SUFFIX)]
    if len(digits) != _SEQ_WIDTH or not digits.isdigit():
        return None
    return int(digits)


def _existing_seqs(chain_dir: Path) -> list[int]:
    if not chain_dir.is_dir():
        return []
    seqs = [s for name in os.listdir(chain_dir) if (s := _parse_seq(name)) is not None]
    seqs.sort()
    return seqs


def read_ops(chain_dir: Path) -> list[dict[str, Any]]:
    """Return every op in the chain, oldest first, each annotated with its 'seq'.

    Retries the whole scan if a listed file vanishes mid-read -- a concurrent
    checkpoint pruned it. The replacing checkpoint always sorts later than
    anything it subsumes, so a fresh scan is guaranteed to observe it and
    recover what the vanished file would have contributed; silently
    dropping the missing file instead would fold a chain with a hole in it
    and nothing to compensate for it.
    """
    while True:
        seqs = _existing_seqs(chain_dir)
        ops: list[dict[str, Any]] = []
        for seq in seqs:
            path = chain_dir / _seq_name(seq)
            try:
                text = path.read_text()
            except FileNotFoundError:
                break
            op = json.loads(text)
            op["seq"] = seq
            ops.append(op)
        else:
            return ops


def fold(ops: list[dict[str, Any]]) -> Any | None:
    """Replay a chain's baked outcomes and return the resulting state.

    Every op already carries the decision made when it was appended, so this
    is a pure replay, not a re-derivation: apply each accepted op's record,
    in seq order, and reject ops are simply skipped.
    """
    current = None
    for op in ops:
        if op.get("outcome") == "accepted":
            current = op["record"]
    return current


def append_resolved_op(
    chain_dir: Path, kind: str, decide: Callable[[Any | None], Decision]
) -> dict[str, Any]:
    """Append an op whose accept/reject decision is baked in atomically.

    `decide(current_state)` returns (outcome, record, extra_fields) given the
    state folded from every op that will precede the slot this call is about
    to claim. Retries the whole read-decide-claim cycle whenever another op
    wins the slot first (see module docstring for why that makes the baked
    decision correct). Returns the full stored op dict, including 'seq'.
    """
    chain_dir.mkdir(parents=True, exist_ok=True)
    while True:
        seen = read_ops(chain_dir)
        current_state = fold(seen)
        outcome, record, extra = decide(current_state)
        next_seq = (seen[-1]["seq"] if seen else 0) + 1
        op_id = uuid.uuid4().hex
        full_op: dict[str, Any] = {"op_id": op_id, "kind": kind, "outcome": outcome, "record": record}
        full_op.update(extra)
        content = json.dumps(full_op, sort_keys=True, separators=(",", ":"))
        tmp = chain_dir / f".tmp-{op_id}"
        tmp.write_text(content)
        try:
            try:
                os.link(tmp, chain_dir / _seq_name(next_seq))
            except FileExistsError:
                continue
            full_op["seq"] = next_seq
            return full_op
        finally:
            tmp.unlink(missing_ok=True)


def prune_before(chain_dir: Path, checkpoint_seq: int) -> None:
    """Best-effort delete of ops made redundant by a checkpoint at checkpoint_seq.

    Safe to crash or race mid-loop: every op here has already been folded into
    the checkpoint's materialized record, so a leftover file only costs a
    slightly larger chain on the next read, never a wrong answer. Never
    touches the checkpoint file itself or anything after it.
    """
    for seq in _existing_seqs(chain_dir):
        if seq >= checkpoint_seq:
            continue
        (chain_dir / _seq_name(seq)).unlink(missing_ok=True)


def purge_chain(chain_dir: Path) -> None:
    """Remove an entire chain, e.g. to unwind a rolled-back create.

    Best-effort: record ids are never reused, so a chain that is purged is
    never written to again.
    """
    if not chain_dir.is_dir():
        return
    for name in os.listdir(chain_dir):
        path = chain_dir / name
        try:
            path.unlink()
        except OSError:
            pass
    try:
        chain_dir.rmdir()
    except OSError:
        pass
