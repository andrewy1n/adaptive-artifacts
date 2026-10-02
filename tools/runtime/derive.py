"""Read-time derivation of `ready`/`wave`/`referenced_by` from record relationships.

`ready`/`wave` come from the `staged-progress` `depends_on` graph. They used to
be hand-maintained payload integers. They drifted from reality because nothing
computed or checked them. This module computes them instead, purely from data
already on disk (lifecycle_state + the `depends_on` relationship) -- so they
can never drift, and are never themselves persisted (see the HARD CONSTRAINTS
note below).

`referenced_by` is the inverse of every relationship stored on every record:
relationships are written on the source record only ("this decision
contradicts that finding"), so "what points at this record" is otherwise
answerable only by scanning the whole store. It is generic over relationship
type and record type -- it walks whatever `relationships` dict a record
happens to carry, unlike `ready`/`wave` which are specific to `depends_on`
on contract-declared `depends_on`-bearing types.

Terminal success state
-----------------------
`ready` needs to know which lifecycle state means "this record's work is done,
successfully" for an arbitrary record type -- without hardcoding a state name
like "done". `superseded` is already a reserved, cross-cutting state elsewhere
in this codebase (contract.advertises_supersedes, validation's orphan/identity
checks): it means "replaced by a successor record", not a progress outcome, and
it is reachable from many states in most lifecycles. So a state is a candidate
"terminal success" state if it has no outgoing transitions once transitions
into "superseded" are disregarded -- i.e. it is a dead end for forward
progress. Among candidates, the terminal success state is the one furthest
(by transition hop count) from the lifecycle's initial state: the state only
reached after the most forward progress. For `staged-progress`
(planned -> in_progress -> done, with withdrawn/superseded as side exits),
this yields "done" without ever naming it. A lifecycle with no such dead end
(purely cyclic, or every state has real outgoing progress) has no terminal
success state, so nothing can ever become ready via it.

A dependency in a terminal-but-not-success state (e.g. withdrawn) therefore
makes its dependent NOT ready, with no special-casing required: its
lifecycle_state simply never equals the terminal success state. This is a
deliberate choice -- abandonment must never be silently read as satisfaction.

Cycles and dangling dependencies
---------------------------------
`ready` only ever inspects a dependency's own `lifecycle_state` (one dict
lookup), never its `ready`/`wave`, so it cannot recurse and cannot hang; a
cycle in `depends_on` just makes every member's readiness a plain (and
possibly always-false) equality check.

`wave` is a genuine graph walk (topological depth) and does need cycle
handling: computed with one iterative (non-recursive, so a deep chain cannot
blow the interpreter stack) DFS over the whole record set, coloring nodes
white/gray/black, so it is O(records + edges) total, not O(records) DFS calls.
A back edge (dependency reaching a node still on the current path) marks every
node currently on that path as cyclic; a cyclic record's wave is reported as
`None` rather than a guessed number, and `None` propagates to anything that
(transitively) depends on it -- a wave built on an undefined foundation is
itself undefined. This satisfies "reported, not hung on or silently
mis-numbered".

A dependency id that names no record ("dangling") is a data-integrity problem
local to one edge, not a structural graph problem: `ready` treats it as
"can't be verified done" (not ready) -- the conservative, safe answer -- but
`wave` simply skips that edge when computing depth, as if the reference did
not exist, rather than poisoning every downstream wave number with `None`
over one bad reference. In practice `validate_relationships` already forbids
writing a `depends_on` target that doesn't exist, so this path is a defensive
fallback, not a normal occurrence.

HARD CONSTRAINTS
-----------------
Everything here is read-time-only: callers attach `derived` to a *copy* of a
record (see `attach_derived`) for query/view purposes. Nothing here ever
writes to the store, and the attached copy must never be handed to
`Store.write_record`/`create_record` (which would fold it into
`compute_revision`'s hash and persist it). `Store.iter_records` is
deliberately left untouched; derivation is a layer above it.
"""

from __future__ import annotations

from typing import Any

from contract import record_defs

_SUPERSEDED = "superseded"


def eligible_record_types(contract: dict[str, Any]) -> set[str]:
    """Record type ids whose contract-declared relationships include depends_on."""
    return {
        record_id
        for record_id, record_def in record_defs(contract).items()
        if "depends_on" in (record_def.get("relationships") or [])
    }


def terminal_success_state(record_def: dict[str, Any]) -> str | None:
    """The lifecycle state meaning "done, successfully" for this record type.

    See the module docstring for the derivation. Returns None when the
    lifecycle has no state that qualifies (e.g. purely cyclic).
    """
    lifecycle = record_def.get("lifecycle") or {}
    states = lifecycle.get("states") or []
    initial = lifecycle.get("initial")
    transitions = lifecycle.get("transitions") or {}
    if not states or initial not in states:
        return None

    def progress_targets(state: str) -> list[str]:
        return [dest for dest in transitions.get(state, []) if dest != _SUPERSEDED]

    candidates = [state for state in states if state != _SUPERSEDED and not progress_targets(state)]
    if not candidates:
        return None

    distances: dict[str, int] = {initial: 0}
    frontier = [initial]
    while frontier:
        next_frontier: list[str] = []
        for state in frontier:
            for dest in transitions.get(state, []):
                if dest not in distances:
                    distances[dest] = distances[state] + 1
                    next_frontier.append(dest)
        frontier = next_frontier

    reachable = [state for state in candidates if state in distances]
    if not reachable:
        return None
    farthest = max(distances[state] for state in reachable)
    # Ties are resolved deterministically (alphabetically); a lifecycle with
    # two equally-deep dead ends (e.g. "completed" vs "cancelled" at the same
    # depth) is genuinely ambiguous without more information than the
    # lifecycle graph carries. No shipped depends_on-bearing record type hits
    # this today.
    return sorted(state for state in reachable if distances[state] == farthest)[0]


def _dependency_ids(record: dict[str, Any]) -> list[str]:
    return list((record.get("relationships") or {}).get("depends_on") or [])


def _is_ready(
    record: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    defs: dict[str, dict[str, Any]],
    success_cache: dict[str, str | None],
) -> bool:
    deps = _dependency_ids(record)
    if not deps:
        return True
    for dep_id in deps:
        target = by_id.get(dep_id)
        if target is None:
            return False  # dangling: can't be verified done
        target_type = target.get("record_type")
        target_def = defs.get(target_type)
        if target_def is None:
            return False
        if target_type not in success_cache:
            success_cache[target_type] = terminal_success_state(target_def)
        success = success_cache[target_type]
        if success is None or target.get("lifecycle_state") != success:
            return False
    return True


def _compute_waves(by_id: dict[str, dict[str, Any]]) -> dict[str, int | None]:
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {}
    wave: dict[str, int | None] = {}
    cyclic: set[str] = set()

    def deps_of(record_id: str) -> list[str]:
        record = by_id.get(record_id)
        return _dependency_ids(record) if record is not None else []

    for start_id in by_id:
        if color.get(start_id, WHITE) != WHITE:
            continue
        stack: list[list[Any]] = [[start_id, deps_of(start_id), 0]]
        color[start_id] = GRAY
        while stack:
            frame = stack[-1]
            node, deps, idx = frame[0], frame[1], frame[2]
            if idx < len(deps):
                frame[2] += 1
                dep = deps[idx]
                dep_color = color.get(dep, WHITE)
                if dep_color == WHITE:
                    if dep in by_id:
                        color[dep] = GRAY
                        stack.append([dep, deps_of(dep), 0])
                    # else: dangling, no node to descend into
                elif dep_color == GRAY:
                    # back edge: everything on the current path is unresolved
                    for pending_id, _, _ in stack:
                        cyclic.add(pending_id)
                continue
            stack.pop()
            color[node] = BLACK
            if node in cyclic:
                wave[node] = None
                continue
            contributing: list[int] = []
            undefined = False
            for dep in deps:
                if dep not in by_id:
                    continue  # dangling: does not contribute depth
                dep_wave = wave.get(dep)
                if dep_wave is None:
                    undefined = True
                    break
                contributing.append(dep_wave)
            wave[node] = None if undefined else (1 + max(contributing) if contributing else 1)
    return wave


def compute_inverse(records: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    """{target_id: {relationship_type: [source_id, ...]}} over every relationship
    edge in the record set, regardless of record type or contract.

    Pure data walk: a record's `relationships` dict is always {type: [target_ids]}
    by construction (validate_relationships enforces this on write), so this
    needs no contract to interpret it. Source ids are sorted for determinism --
    two records referencing the same target in different id order must not
    make an otherwise-unchanged store's derived output differ.
    """
    inverse: dict[str, dict[str, list[str]]] = {}
    for record in records:
        source_id = record.get("id")
        for rel_type, targets in (record.get("relationships") or {}).items():
            for target_id in targets or []:
                inverse.setdefault(target_id, {}).setdefault(rel_type, []).append(source_id)
    for by_type in inverse.values():
        for sources in by_type.values():
            sources.sort()
    return inverse


def compute_derived(
    records: list[dict[str, Any]], contract: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """{record_id: {...}} of read-time-only values, never persisted.

    `ready`/`wave` are attached only for records of a type whose
    contract-declared relationships include `depends_on`. `referenced_by` is
    attached for any record that is the target of at least one relationship
    from another record, regardless of type -- a contract that declares
    nothing depends_on-eligible and a store with no cross-references both
    still yield `{}` here, so nothing changes for a store that uses neither
    feature.

    Must be called with the full record set (not pre-filtered by type or
    lifecycle_state) -- a dependency or relationship can name a record of any
    type, and filtering first would misreport real targets as dangling or
    unreferenced. Does one graph walk and one relationship walk for the whole
    set, not one per record.
    """
    eligible = eligible_record_types(contract)
    inverse = compute_inverse(records)
    if not eligible and not inverse:
        return {}
    defs = record_defs(contract)
    by_id = {record["id"]: record for record in records}
    wave = _compute_waves(by_id) if eligible else {}
    success_cache: dict[str, str | None] = {}
    derived: dict[str, dict[str, Any]] = {}
    for record in records:
        record_id = record["id"]
        entry: dict[str, Any] = {}
        if record.get("record_type") in eligible:
            entry["ready"] = _is_ready(record, by_id, defs, success_cache)
            entry["wave"] = wave.get(record_id)
        if record_id in inverse:
            entry["referenced_by"] = inverse[record_id]
            if "corrects" in inverse[record_id]:
                entry["corrected"] = True
        if entry:
            derived[record_id] = entry
    return derived


def attach_derived(
    record: dict[str, Any], derived_map: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """A copy of `record` with a top-level `derived` mapping, or `record`
    itself, unmodified, when it has no derived values (so a contract that
    declares nothing derived renders exactly as it always has)."""
    values = derived_map.get(record.get("id"))
    if values is None:
        return record
    out = dict(record)
    out["derived"] = dict(values)
    return out


def attach_derived_all(
    records: list[dict[str, Any]], derived_map: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    if not derived_map:
        return records
    return [attach_derived(record, derived_map) for record in records]
