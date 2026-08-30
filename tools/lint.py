#!/usr/bin/env python3
"""Lint a project's .artifacts/ tree against its own schema registry.

Usage: lint.py [--root <project-root>]

Checks (per primitives/schema-format.md):
  - manifest present, head_commit stamped, tables cross-check schemas/
  - schema JSON files valid
  - required fields present per discipline/layout conventions
  - budget_lines respected
  - collection id_format: duplicates error, gaps warn
  - ledgers append-only vs git HEAD (edits/deletes of committed entries)
  - unregistered files under .artifacts/ warned

Exit 1 on any error, 0 otherwise.
"""
import argparse
import json
import os
import re
import subprocess
import sys

DISCIPLINES = {"snapshot", "ledger"}
LAYOUTS = {"file", "collection"}
RESERVED = {"MANIFEST.md", "schemas", "tools"}

errors = []
warnings = []


def err(where, msg):
    errors.append(f"ERROR {where}: {msg}")


def warn(where, msg):
    warnings.append(f"WARN {where}: {msg}")


def git(root, *args):
    try:
        r = subprocess.run(["git", "-C", root, *args],
                           capture_output=True, text=True, timeout=15)
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


def heading_names(text):
    return {m.group(1).strip().casefold()
            for m in re.finditer(r"^#{2,3}\s+(?!#)(.+?)\s*$", text, re.M)}


def has_field(text, name):
    if name.casefold() in heading_names(text):
        return True
    pat = r"\*\*\s*" + re.escape(name) + r"\s*:\s*\*\*"
    return re.search(pat, text, re.I) is not None


def ledger_file_entries(text):
    """Split a single-file ledger into (id, body) entry sections."""
    parts = re.split(r"^(##\s+#\d+.*)$", text, flags=re.M)
    entries = []
    for i in range(1, len(parts), 2):
        m = re.match(r"##\s+#(\d+)", parts[i])
        body = parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")
        entries.append((int(m.group(1)), body))
    return entries


def load_schemas(art_dir):
    schemas = {}
    sdir = os.path.join(art_dir, "schemas")
    if not os.path.isdir(sdir):
        err("schemas/", "missing schemas directory")
        return schemas
    for fn in sorted(os.listdir(sdir)):
        if not fn.endswith(".json"):
            continue
        where = f"schemas/{fn}"
        try:
            with open(os.path.join(sdir, fn)) as f:
                s = json.load(f)
        except Exception as e:
            err(where, f"invalid JSON: {e}")
            continue
        name = s.get("name")
        if name != fn[:-5]:
            err(where, f"name '{name}' does not match filename")
        if s.get("discipline") not in DISCIPLINES:
            err(where, f"discipline must be one of {sorted(DISCIPLINES)}")
            continue
        if s.get("layout") not in LAYOUTS:
            err(where, f"layout must be one of {sorted(LAYOUTS)}")
            continue
        if not s.get("path"):
            err(where, "missing path")
            continue
        if not isinstance(s.get("fields", []), list):
            err(where, "fields must be a list")
            continue
        for fld in s.get("fields", []):
            if not fld.get("name"):
                err(where, "field without a name")
        schemas[name] = s
    return schemas


def parse_manifest(art_dir):
    path = os.path.join(art_dir, "MANIFEST.md")
    if not os.path.isfile(path):
        err("MANIFEST.md", "missing")
        return None
    with open(path) as f:
        text = f.read()
    m = re.search(r"head_commit:\s*([0-9a-fA-F]{7,40})", text)
    if not m:
        err("MANIFEST.md", "missing or malformed head_commit stamp")
    rows = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] not in ("Type", "Tool") \
                and not all(re.fullmatch(r":?-+:?", c or "-") for c in cells):
            rows.append(cells)
    artifact_rows = [r for r in rows if len(r) >= 3 and r[2].startswith("schemas/")]
    return {"head_commit": m.group(1) if m else "", "rows": artifact_rows}


def check_fields(schema, where, text):
    for fld in schema.get("fields", []):
        if fld.get("required") and not has_field(text, fld["name"]):
            err(where, f"missing required field '{fld['name']}'")


def check_ids(schema, where, names):
    ids = []
    for n in names:
        m = re.fullmatch(r"(\d{3,})-([a-z0-9][a-z0-9-]*)\.md", n)
        if not m:
            err(f"{where}/{n}", "filename does not match id_format NNN-slug")
            continue
        ids.append(int(m.group(1)))
    dupes = {i for i in ids if ids.count(i) > 1}
    for d in sorted(dupes):
        err(where, f"duplicate entry id {d}")
    if ids:
        missing = sorted(set(range(min(ids), max(ids) + 1)) - set(ids))
        if missing:
            warn(where, f"id sequence gaps: {missing}")


def stale_since(repo_top, recorded):
    """Stale only if commits since `recorded` touched files outside
    .artifacts/ — the artifact-stamping commit itself never counts."""
    rc, out = git(repo_top, "log", "--name-only", "--format=",
                  f"{recorded}..HEAD")
    if rc != 0:
        return True  # unknown recorded commit: distrust
    return any(l.strip() and not l.startswith(".artifacts/")
               for l in out.splitlines())


def check_append_only_file(root, repo_top, apath, where):
    rel = os.path.relpath(apath, repo_top)
    rc, committed = git(repo_top, "show", f"HEAD:{rel}")
    if rc != 0:
        return  # not committed yet
    with open(apath) as f:
        working = f.read()
    cl, wl = committed.splitlines(), working.splitlines()
    if wl[:len(cl)] != cl:
        err(where, "ledger modified above the append point "
                   "(committed entries must never be edited)")


def check_append_only_collection(root, repo_top, adir, where):
    rel = os.path.relpath(adir, repo_top)
    rc, out = git(repo_top, "ls-tree", "-r", "HEAD", "--name-only", "--", rel)
    if rc != 0:
        return
    for cpath in out.splitlines():
        if not cpath.endswith(".md"):
            continue
        base = os.path.basename(cpath)
        if os.path.dirname(cpath) != rel:
            continue  # attachments/archive handled below
        wpath = os.path.join(repo_top, cpath)
        _, committed = git(repo_top, "show", f"HEAD:{cpath}")
        if not os.path.isfile(wpath):
            arch = os.path.join(adir, "archive", base)
            if os.path.isfile(arch) and open(arch).read() == committed:
                continue
            err(f"{where}/{base}", "committed ledger entry deleted "
                                   "(archive by moving to archive/, unmodified)")
        elif open(wpath).read() != committed:
            err(f"{where}/{base}", "committed ledger entry modified")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.getcwd())
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    art_dir = os.path.join(root, ".artifacts")
    if not os.path.isdir(art_dir):
        print(f"ERROR .artifacts: not found under {root}")
        sys.exit(1)

    schemas = load_schemas(art_dir)
    manifest = parse_manifest(art_dir)

    rc, top = git(root, "rev-parse", "--show-toplevel")
    repo_top = top.strip() if rc == 0 else ""
    if manifest and manifest["head_commit"] and repo_top:
        _, head = git(repo_top, "rev-parse", "HEAD")
        head = head.strip()
        rec = manifest["head_commit"]
        if head and not (head.startswith(rec) or rec.startswith(head)) \
                and stale_since(repo_top, rec):
            warn("MANIFEST.md", f"head_commit {rec[:12]} != HEAD {head[:12]} "
                                "with non-artifact commits since "
                                "(stale; update at session end)")

    manifest_paths = {}
    if manifest:
        for row in manifest["rows"]:
            manifest_paths[row[1].rstrip("/")] = row
        for name, s in schemas.items():
            p = s["path"].rstrip("/")
            if p not in manifest_paths:
                err("MANIFEST.md", f"no Artifacts row for type '{name}' ({p})")
        for p, row in manifest_paths.items():
            spath = os.path.join(art_dir, row[2])
            if not os.path.isfile(spath):
                err("MANIFEST.md", f"row '{row[0]}' points at missing {row[2]}")

    covered = set()
    for name, s in schemas.items():
        p = s["path"].rstrip("/")
        covered.add(p.split("/")[0])
        apath = os.path.join(art_dir, p)
        where = p
        if s["layout"] == "file":
            if not os.path.isfile(apath):
                if s["discipline"] == "snapshot":
                    err(where, "snapshot file missing")
                continue
            with open(apath) as f:
                text = f.read()
            if s.get("budget_lines") and len(text.splitlines()) > s["budget_lines"]:
                err(where, f"{len(text.splitlines())} lines exceeds "
                           f"budget_lines {s['budget_lines']}")
            if s["discipline"] == "snapshot":
                check_fields(s, where, text)
            else:
                entries = ledger_file_entries(text)
                for eid, body in entries:
                    check_fields(s, f"{where}#{eid}", body)
                ids = [e[0] for e in entries]
                for d in sorted({i for i in ids if ids.count(i) > 1}):
                    err(where, f"duplicate entry id #{d}")
                if repo_top and s["discipline"] == "ledger":
                    check_append_only_file(root, repo_top, apath, where)
        else:  # collection
            if not os.path.isdir(apath):
                if s["discipline"] == "snapshot":
                    err(where, "snapshot collection directory missing")
                continue
            entry_files = sorted(n for n in os.listdir(apath)
                                 if n.endswith(".md")
                                 and os.path.isfile(os.path.join(apath, n)))
            for n in entry_files:
                with open(os.path.join(apath, n)) as f:
                    text = f.read()
                check_fields(s, f"{where}/{n}", text)
                if s.get("budget_lines") and len(text.splitlines()) > s["budget_lines"]:
                    err(f"{where}/{n}", f"exceeds budget_lines {s['budget_lines']}")
            if s.get("id_format") == "NNN-slug":
                check_ids(s, where, entry_files)
            if repo_top and s["discipline"] == "ledger":
                check_append_only_collection(root, repo_top, apath, where)

    for entry in sorted(os.listdir(art_dir)):
        if entry in RESERVED or entry.split(".")[0] in covered or entry in covered:
            continue
        warn(entry, "not covered by any schema (unregistered artifact?)")

    for line in errors + warnings:
        print(line)
    print(f"lint: {len(errors)} errors, {len(warnings)} warnings")
    sys.exit(1 if errors else 0)


main()
