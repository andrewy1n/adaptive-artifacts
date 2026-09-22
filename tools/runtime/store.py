"""JSON filesystem store for contract-bound semantic records.

Single-writer assumption: each record and history file is atomically written,
but multi-record operations are not transactional. Validation detects orphan
superseded records, partial lineage, and path/layout tampering.
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
from record_file import (
    RECORD_GLOB,
    RECORD_SUFFIX,
    RecordFileError,
    dump_record,
    load_record,
    prepare_record,
)
from revision import compute_revision, with_revision

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


class Store:
    STORE_VERSION = 1

    def __init__(self, root: Path):
        self.root = root
        self.records_dir = root / "records"
        self.history_dir = root / "history"

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
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content)
        tmp.replace(path)

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

    def write_record(
        self,
        record: dict[str, Any],
        *,
        expected_revision: str | None = None,
        archive_prior: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record_type = record["record_type"]
        record_id = record["id"]
        path = self.record_path(record_type, record_id)
        if path.exists():
            if expected_revision is None:
                raise StoreError(f"record {record_id} exists; expected revision required")
            current = self.read_record(record_type, record_id)["revision"]
            if current != expected_revision:
                raise StaleWriteError(
                    f"stale write for {record_id}: expected {expected_revision}, got {current}"
                )
            if archive_prior is not None:
                self.archive_history(archive_prior)
        stored = with_revision(prepare_record(record))
        self._atomic_write(path, dump_record(stored))
        return stored

    def create_record(self, record: dict[str, Any]) -> dict[str, Any]:
        path = self.record_path(record["record_type"], record["id"])
        if path.exists():
            raise StoreError(f"record already exists: {record['id']}")
        stored = with_revision(prepare_record(record))
        self._atomic_write(path, dump_record(stored))
        return stored

    def record_exists(self, record_type: str, record_id: str) -> bool:
        return self.record_path(record_type, record_id).is_file()

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
