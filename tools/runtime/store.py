"""JSON filesystem store for contract-bound semantic records.

Mutations never read-modify-write a record file directly: `create_record`
and `write_record` append an immutable op to that record's chain (see
`oplog.py`), then fold the chain to decide accept/reject and to materialize
`records/<type>/<id>.md` -- the same on-disk shape `query.py`, `derive.py`,
`handoff.py`, and `validation.py` already read, so nothing downstream of the
materialized store changed. `expected_revision` conflicts are therefore
detected by folding, not by locking the record file, and concurrent writers
to different (or even the same) record chain never block each other.
Multi-record operations (e.g. supersede, capture) are still not
transactional across records. Validation detects orphan superseded records,
partial lineage, and path/layout tampering.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

from contract import contract_digest
from paths import (
    PathValidationError,
    SUPPORTED_STORE_VERSIONS,
    revision_filename,
    type_dir_name,
    validate_record_id,
    validate_record_type,
)
from oplog import CHECKPOINT_KIND, OP_SUFFIX, append_resolved_op, fold, prune_before, purge_chain, read_ops
from record_file import (
    RECORD_GLOB,
    RECORD_SUFFIX,
    RecordFileError,
    dump_record,
    load_record,
    prepare_record,
)
from revision import compute_revision, with_revision

CHECKPOINT_THRESHOLD = 32

LOCK_FILENAME = ".write.lock"
LOCK_RETRY_ATTEMPTS = 20
LOCK_RETRY_INTERVAL_SECONDS = 0.05


class StoreError(Exception):
    pass


class StaleWriteError(StoreError):
    pass


class ContractBindingError(StoreError):
    pass


class StoreNotInitializedError(StoreError):
    pass


class PartialStoreError(StoreError):
    pass


class StoreLockError(StoreError):
    pass


def _load_json_file(path: Path, label: str) -> Any:
    try:
        with path.open() as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise StoreError(f"malformed JSON in {label}: {exc}") from exc


def _load_record_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text()
    except OSError as exc:
        raise StoreError(f"cannot read record file {path}: {exc}") from exc
    try:
        return load_record(text, path)
    except RecordFileError as exc:
        raise StoreError(str(exc)) from exc


def _decide_create(current: dict[str, Any] | None, record: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if current is not None:
        return "rejected_exists", current, {"conflict_revision": current.get("revision")}
    new_state = with_revision(prepare_record(record))
    return "accepted", new_state, {}


def _decide_write(
    current: dict[str, Any] | None, record: dict[str, Any], expected_revision: str | None
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if current is not None:
        if expected_revision is None:
            return "rejected_missing_expected", current, {"conflict_revision": current.get("revision")}
        if expected_revision != current.get("revision"):
            return "rejected_stale", current, {"conflict_revision": current.get("revision")}
    new_state = with_revision(prepare_record(record))
    return "accepted", new_state, {}


class Store:
    STORE_VERSION = 1

    def __init__(self, root: Path):
        self.root = root
        self.records_dir = root / "records"
        self.history_dir = root / "history"
        self.log_dir = root / "log"

    def meta_path(self) -> Path:
        return self.root / "meta.json"

    def lock_path(self) -> Path:
        return self.root / LOCK_FILENAME

    @contextlib.contextmanager
    def write_lock(self) -> Iterator[None]:
        """Advisory single-writer lock for the store, held for one mutating operation.

        Fails fast (after a short bounded retry) instead of blocking forever, since a
        stuck writer should surface as an error, not a hang.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.lock_path()
        handle = path.open("a+")
        try:
            acquired = False
            holder: str | None = None
            for attempt in range(LOCK_RETRY_ATTEMPTS):
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError:
                    handle.seek(0)
                    holder = handle.read().strip() or None
                    if attempt < LOCK_RETRY_ATTEMPTS - 1:
                        time.sleep(LOCK_RETRY_INTERVAL_SECONDS)
            if not acquired:
                detail = f" (held by {holder})" if holder else ""
                raise StoreLockError(f"store is locked for writing{detail}: {path}")
            handle.seek(0)
            handle.truncate()
            handle.write(f"pid:{os.getpid()}\n")
            handle.flush()
            try:
                yield
            finally:
                handle.seek(0)
                handle.truncate()
                handle.flush()
                # Leave nothing behind to be swept into a commit by `git add -A`.
                with contextlib.suppress(OSError):
                    path.unlink()
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def is_absent(self) -> bool:
        if not self.root.exists():
            return True
        if self.meta_path().is_file():
            return False
        return not self._has_partial_content()

    def _has_partial_content(self) -> bool:
        if self.meta_path().exists() and not self.meta_path().is_file():
            return True
        for base in (self.records_dir, self.history_dir):
            if base.is_dir() and any(base.rglob(RECORD_GLOB)):
                return True
        if self.log_dir.is_dir() and any(self.log_dir.rglob(f"*{OP_SUFFIX}")):
            return True
        return False

    def load_meta(self) -> dict[str, Any]:
        if not self.meta_path().is_file():
            if self._has_partial_content():
                raise PartialStoreError("store exists without valid meta.json")
            raise StoreNotInitializedError("store not initialized")
        meta = _load_json_file(self.meta_path(), "meta.json")
        if not isinstance(meta, dict):
            raise StoreError("meta.json must be a JSON object")
        version = meta.get("store_version")
        if version not in SUPPORTED_STORE_VERSIONS:
            raise StoreError(f"unsupported store version {version!r}")
        if not meta.get("contract_digest"):
            raise StoreError("meta.json missing contract_digest")
        return meta

    def require_initialized(self, contract: dict[str, Any]) -> None:
        self.assert_contract(contract)

    def assert_contract(self, contract: dict[str, Any]) -> None:
        meta = self.load_meta()
        expected = meta.get("contract_digest")
        actual = contract_digest(contract)
        if expected != actual:
            raise ContractBindingError(
                f"contract digest mismatch: store pins {expected}, loaded contract is {actual}"
            )

    def type_dir(self, record_type: str) -> Path:
        try:
            dirname = type_dir_name(record_type)
        except PathValidationError as exc:
            raise StoreError(str(exc)) from exc
        return self.records_dir / dirname

    def record_path(self, record_type: str, record_id: str) -> Path:
        try:
            validate_record_type(record_type)
            validate_record_id(record_id)
        except PathValidationError as exc:
            raise StoreError(str(exc)) from exc
        return self.type_dir(record_type) / f"{record_id}{RECORD_SUFFIX}"

    def _chain_dir(self, record_type: str, record_id: str) -> Path:
        try:
            validate_record_type(record_type)
            validate_record_id(record_id)
        except PathValidationError as exc:
            raise StoreError(str(exc)) from exc
        return self.log_dir / type_dir_name(record_type) / record_id

    def history_snapshot_path(self, record_type: str, record_id: str, revision: str) -> Path:
        try:
            validate_record_type(record_type)
            validate_record_id(record_id)
            filename = revision_filename(revision)
        except PathValidationError as exc:
            raise StoreError(str(exc)) from exc
        return self.history_dir / type_dir_name(record_type) / record_id / filename

    def init(self, contract: dict[str, Any], contract_path: Path) -> str:
        digest = contract_digest(contract)
        if self.meta_path().is_file():
            meta = self.load_meta()
            if meta.get("contract_digest") == digest:
                return "already_initialized"
            raise StoreError(
                "store already initialized with a different contract; refusing to rebind"
            )
        if self._has_partial_content():
            raise PartialStoreError("refusing to init over partial store without valid meta.json")
        self.root.mkdir(parents=True, exist_ok=True)
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        resolved_contract_path = contract_path.resolve()
        try:
            contract_ref = resolved_contract_path.relative_to(
                self.root.resolve().parent
            ).as_posix()
        except ValueError:
            contract_ref = str(resolved_contract_path)
        meta = {
            "store_version": self.STORE_VERSION,
            "contract": contract_ref,
            "contract_digest": digest,
        }
        self._atomic_write(self.meta_path(), json.dumps(meta, indent=2) + "\n")
        return "initialized"

    def _atomic_write(self, path: Path, content: str, *, overwrite: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not overwrite and path.exists():
            raise StoreError(f"refusing to overwrite existing file: {path}")
        # Unique per call, not just per target: concurrent writers materializing
        # the same record now race on this path, and a shared tmp name would let
        # one process's replace() steal the file out from under another's.
        tmp = path.with_suffix(f"{path.suffix}.tmp-{uuid.uuid4().hex}")
        try:
            tmp.write_text(content)
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)

    def _history_content(self, record: dict[str, Any]) -> str:
        return dump_record(record)

    def archive_history(self, record: dict[str, Any]) -> None:
        path = self.history_snapshot_path(
            record["record_type"], record["id"], record["revision"]
        )
        content = self._history_content(record)
        if path.exists():
            existing = path.read_text()
            if existing == content:
                return
            raise StoreError(f"history snapshot conflict at {path}")
        self._atomic_write(path, content, overwrite=False)

    def iter_history(self) -> Iterator[tuple[Path, dict[str, Any]]]:
        if not self.history_dir.is_dir():
            return iter(())
        for path in sorted(self.history_dir.rglob(RECORD_GLOB)):
            snapshot = _load_record_file(path)
            yield path, snapshot

    def _materialize(self, record_type: str, record_id: str, state: dict[str, Any]) -> None:
        self._atomic_write(self.record_path(record_type, record_id), dump_record(state))

    def _maybe_checkpoint(self, chain_dir: Path) -> None:
        """Bound chain growth once it passes a threshold.

        The checkpoint op is appended the same way any other op is (see
        `oplog.append_resolved_op`) -- always "accepted", since it is a
        snapshot rather than a conflicting mutation -- so it is crash-safe
        the same way. Its record is whatever `append_resolved_op` folds
        fresh at the moment it claims its slot, never a state captured
        earlier by the caller: a checkpoint is itself an accepted op, so it
        wins the fold like any other, and baking in a snapshot from before
        its own commit could paper back over an op that landed in between,
        permanently losing it once `prune_before` deletes the pre-checkpoint
        files. Pruning the ops it subsumes is a best-effort cleanup
        afterward: folding a checkpoint plus leftover pre-checkpoint files
        still yields the identical final state, so a crash or race mid-prune
        only costs a temporarily larger chain, never a wrong answer. Safe to
        run concurrently with another writer that just appended one of the
        ops being pruned: that writer already has its own outcome baked into
        the op it wrote and never needs to re-read that specific file.
        """
        if len(read_ops(chain_dir)) < CHECKPOINT_THRESHOLD:
            return
        checkpoint = append_resolved_op(chain_dir, CHECKPOINT_KIND, lambda current: ("accepted", current, {}))
        prune_before(chain_dir, checkpoint["seq"])

    def write_record(
        self,
        record: dict[str, Any],
        *,
        expected_revision: str | None = None,
        archive_prior: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record_type = record["record_type"]
        record_id = record["id"]
        self.record_path(record_type, record_id)  # validate path components early
        chain_dir = self._chain_dir(record_type, record_id)
        state_before: list[dict[str, Any] | None] = []

        def decide(current: dict[str, Any] | None) -> tuple[str, dict[str, Any], dict[str, Any]]:
            state_before.append(current)
            return _decide_write(current, record, expected_revision)

        written = append_resolved_op(chain_dir, "write", decide)
        # Re-fold rather than trust written["record"]: another writer's op may
        # have landed after this one, and that newer state is what belongs on
        # disk -- re-folding never needs this op's own file to still exist.
        # Do this -- and the checkpoint check -- unconditionally, including on
        # a rejected outcome: a chain under heavy contention accumulates far
        # more rejected attempts than accepted ones, and skipping the bound
        # on the reject path is what would let it grow without bound.
        final_state = fold(read_ops(chain_dir))
        assert final_state is not None
        self._materialize(record_type, record_id, final_state)
        self._maybe_checkpoint(chain_dir)
        if written["outcome"] == "rejected_missing_expected":
            raise StoreError(f"record {record_id} exists; expected revision required")
        if written["outcome"] == "rejected_stale":
            raise StaleWriteError(
                f"stale write for {record_id}: expected {expected_revision}, "
                f"got {written.get('conflict_revision')}"
            )
        if state_before[-1] is not None and archive_prior is not None:
            self.archive_history(archive_prior)
        return with_revision(prepare_record(record))

    def create_record(self, record: dict[str, Any]) -> dict[str, Any]:
        record_type = record["record_type"]
        record_id = record["id"]
        self.record_path(record_type, record_id)  # validate path components early
        chain_dir = self._chain_dir(record_type, record_id)
        written = append_resolved_op(chain_dir, "create", lambda current: _decide_create(current, record))
        final_state = fold(read_ops(chain_dir))
        assert final_state is not None
        self._materialize(record_type, record_id, final_state)
        self._maybe_checkpoint(chain_dir)
        if written["outcome"] == "rejected_exists":
            raise StoreError(f"record already exists: {record_id}")
        return with_revision(prepare_record(record))

    def record_exists(self, record_type: str, record_id: str) -> bool:
        return self.record_path(record_type, record_id).is_file()

    def delete_record_file(self, record_type: str, record_id: str) -> None:
        """Remove a record file, e.g. to unwind a partially-written multi-record bundle.

        Silent no-op if already absent, so rollback is safe to call twice. Also
        purges the record's op chain: ids are never reused, so nothing will
        ever append to this chain again, and leaving it behind would only grow
        the log for no reason.
        """
        self.record_path(record_type, record_id).unlink(missing_ok=True)
        purge_chain(self._chain_dir(record_type, record_id))

    def delete_history_snapshot(self, record_type: str, record_id: str, revision: str) -> None:
        """Companion to delete_record_file for append-only types' history snapshot."""
        self.history_snapshot_path(record_type, record_id, revision).unlink(missing_ok=True)

    def read_record(self, record_type: str, record_id: str) -> dict[str, Any]:
        path = self.record_path(record_type, record_id)
        if not path.is_file():
            raise StoreError(f"unknown record: {record_id}")
        record = _load_record_file(path)
        if record.get("revision") != compute_revision(record):
            raise StoreError(f"revision tamper detected for {record_id}")
        return record

    def iter_records(self, record_type: str | None = None) -> Iterator[dict[str, Any]]:
        if not self.records_dir.is_dir():
            return iter(())
        if record_type is not None:
            type_dirs = [self.type_dir(record_type)]
        else:
            type_dirs = sorted(p for p in self.records_dir.iterdir() if p.is_dir())
        for type_dir in type_dirs:
            stray = sorted(
                p.name
                for p in type_dir.glob("*")
                if p.is_file() and p.suffix != RECORD_SUFFIX
            )
            if stray:
                # Silently skipping these would report an unmigrated store as empty,
                # which reads as "valid" everywhere downstream.
                raise StoreError(
                    f"unrecognized record files in {type_dir}: {stray}; "
                    f"expected {RECORD_SUFFIX} (run migrate_records_to_markdown.py)"
                )
            for path in sorted(type_dir.glob(RECORD_GLOB)):
                record = _load_record_file(path)
                if record.get("revision") != compute_revision(record):
                    raise StoreError(
                        f"revision tamper detected for {record.get('id', path.name)}"
                    )
                yield record

    def list_records(
        self,
        record_type: str | None = None,
        lifecycle_state: str | None = None,
    ) -> list[dict[str, Any]]:
        records = list(self.iter_records(record_type))
        if lifecycle_state is not None:
            records = [r for r in records if r.get("lifecycle_state") == lifecycle_state]
        return records

    def new_id(self) -> str:
        return f"rec-{uuid.uuid4()}"
