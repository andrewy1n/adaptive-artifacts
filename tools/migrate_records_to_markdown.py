#!/usr/bin/env python3
"""Rewrite a store's JSON record files as Markdown frontmatter + body files.

Revision tokens are preserved: an empty body is omitted from canonicalization,
so a record that had no body before the migration hashes the same after it.
A record whose stored revision does not already match its content is reported
and left alone rather than silently re-signed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RUNTIME = Path(__file__).resolve().parent / "runtime"
sys.path.insert(0, str(RUNTIME))

from record_file import RECORD_SUFFIX, dump_record  # noqa: E402
from revision import compute_revision  # noqa: E402


def iter_json_records(store: Path):
    for base in ("records", "history"):
        root = store / base
        if root.is_dir():
            yield from sorted(root.rglob("*.json"))


def migrate(store: Path, apply: bool) -> int:
    planned: list[tuple[Path, Path]] = []
    skipped: list[str] = []

    for path in iter_json_records(store):
        try:
            record = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            skipped.append(f"malformed JSON, left in place: {path}: {exc}")
            continue
        if not isinstance(record, dict) or "id" not in record:
            skipped.append(f"not a record object, left in place: {path}")
            continue

        record.setdefault("body", "")
        if record.get("revision") != compute_revision(record):
            skipped.append(f"revision does not match content, left in place: {path}")
            continue

        target = path.with_suffix(RECORD_SUFFIX)
        if target.exists():
            skipped.append(f"target already exists, left in place: {target}")
            continue
        planned.append((path, target))

        if apply:
            target.write_text(dump_record(record))
            path.unlink()

    verb = "migrated" if apply else "would migrate"
    print(f"{verb}: {len(planned)}")
    for source, target in planned:
        print(f"  {source.name} -> {target.name}")
    if skipped:
        print(f"skipped: {len(skipped)}")
        for line in skipped:
            print(f"  {line}")
    if not apply:
        print("\ndry run; pass --apply to write")
    return 1 if skipped else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", type=Path, help="path to the .artifacts store root")
    parser.add_argument("--apply", action="store_true", help="write changes")
    args = parser.parse_args(argv)

    store = args.store.resolve()
    if not (store / "meta.json").is_file():
        parser.error(f"not a store (no meta.json): {store}")
    return migrate(store, args.apply)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
