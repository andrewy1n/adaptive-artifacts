# Layouts: file vs collection

Orthogonal to discipline. Chosen per type at design time.

## File

One markdown document at `path`. Right when the type is read as a whole
(state, scope) or entries are short and few (a verification log with a
handful of gates).

## Collection

A directory at `path`; each `.md` file directly inside is one entry or
document. Right when:

- Entries are long or numerous (failures, evidence, experiments) — one file
  per entry keeps reads targeted and appends merge-friendly
- The type has natural sub-structure — phases, topics, components — and a
  folder mirrors it (e.g. `plan/01-ingest.md`, `plan/02-index.md`)
- Entries carry attachments: non-`.md` files and subdirectories (e.g.
  `evidence/raw/`) are ignored by field checks

Conventions:

- Ledger collections use `id_format` filenames (`003-alb-idle-timeout.md`);
  snapshot collections use meaningful stable names, optionally
  order-prefixed (`01-ingest.md`)
- No nesting of entries: entries live directly in the directory;
  subdirectories are for attachments or archive only
- An index file is optional and derived — if present, it is generated (by a
  project tool), never the source of truth

Deeper organization (topics containing subtopics) is expressed as multiple
collection types with their own schemas, not nested entries — each schema
stays independently lintable.
