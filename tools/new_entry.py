#!/usr/bin/env python3
"""Scaffold a new ledger entry from a project schema.

Usage: new_entry.py <type> [--title "short title"] [--root <project-root>]

Collections get a new NNN-slug.md file; single-file ledgers get an appended
## #N section. Snapshots are rewritten by hand and are refused here.
"""
import argparse
import datetime
import json
import os
import re
import sys


def slugify(title):
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "entry"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("type")
    ap.add_argument("--title", default="untitled")
    ap.add_argument("--root", default=os.getcwd())
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    spath = os.path.join(root, ".artifacts", "schemas", f"{args.type}.json")
    if not os.path.isfile(spath):
        sys.exit(f"no schema at {spath}")
    with open(spath) as f:
        schema = json.load(f)
    if schema.get("discipline") != "ledger":
        sys.exit(f"'{args.type}' is a {schema.get('discipline')} — "
                 "snapshots are rewritten by hand, not scaffolded")

    today = datetime.date.today().isoformat()
    fields = schema.get("fields", [])

    def field_lines():
        lines = []
        for fld in fields:
            line = f"**{fld['name']}:** "
            if not fld.get("required"):
                line += "<!-- optional; delete if unused -->"
            lines.append(line)
            lines.append("")
        return lines

    apath = os.path.join(root, ".artifacts", schema["path"].rstrip("/"))

    if schema["layout"] == "collection":
        os.makedirs(apath, exist_ok=True)
        ids = [int(m.group(1)) for n in os.listdir(apath)
               if (m := re.match(r"(\d+)-", n))]
        next_id = max(ids, default=0) + 1
        fname = f"{next_id:03d}-{slugify(args.title)}.md"
        fpath = os.path.join(apath, fname)
        content = [f"# {args.title} ({today})", ""] + field_lines()
        with open(fpath, "w") as f:
            f.write("\n".join(content).rstrip() + "\n")
        print(fpath)
    else:
        existing = ""
        if os.path.isfile(apath):
            with open(apath) as f:
                existing = f.read()
        ids = [int(m) for m in re.findall(r"^##\s+#(\d+)", existing, re.M)]
        next_id = max(ids, default=0) + 1
        section = [f"## #{next_id} — {args.title} ({today})", ""] + field_lines()
        body = existing.rstrip() + "\n\n" if existing.strip() else \
            f"# {schema['name'].capitalize()}\n\n"
        with open(apath, "w") as f:
            f.write(body + "\n".join(section).rstrip() + "\n")
        print(f"{apath} (appended #{next_id})")


main()
