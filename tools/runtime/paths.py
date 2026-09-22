"""Safe path component rules for store layout."""

from __future__ import annotations

import re

from record_file import RECORD_SUFFIX

SAFE_SEGMENT = re.compile(r"^[a-z][a-z0-9-]*$")
RECORD_ID = re.compile(
    r"^rec-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
SUPPORTED_STORE_VERSIONS = {1}


class PathValidationError(ValueError):
    pass


def validate_record_type(record_type: str) -> tuple[str, str]:
    if not record_type or record_type.count(":") != 1:
        raise PathValidationError(f"invalid qualified record type {record_type!r}")
    namespace, local = record_type.split(":", 1)
    if not namespace or not local:
        raise PathValidationError(f"invalid qualified record type {record_type!r}")
    for label, part in (("namespace", namespace), ("local name", local)):
        if not SAFE_SEGMENT.match(part):
            raise PathValidationError(f"unsafe {label} in record type {record_type!r}")
        if ".." in part or "/" in part or "\\" in part:
            raise PathValidationError(f"unsafe {label} in record type {record_type!r}")
    return namespace, local


def validate_record_id(record_id: str) -> None:
    if not record_id or not RECORD_ID.match(record_id):
        raise PathValidationError(f"unsafe record id {record_id!r}")


def type_dir_name(record_type: str) -> str:
    namespace, local = validate_record_type(record_type)
    return f"{namespace}__{local}"


def revision_filename(revision: str) -> str:
    if not revision or not revision.startswith("sha256:"):
        raise PathValidationError(f"invalid revision {revision!r}")
    digest = revision[7:]
    if len(digest) != 64 or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise PathValidationError(f"invalid revision {revision!r}")
    return f"sha256_{digest}{RECORD_SUFFIX}"
