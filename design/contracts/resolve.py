#!/usr/bin/env python3
"""Resolve a project design into a contract from patterns, traits, and backends."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
FIXTURE_DIR = ROOT / "fixtures"
RESOLVED_DIR = ROOT / "resolved"

# Semantic dimensions owned exclusively by traits.
RECORD_TRAIT_OWNED = {
    "lifecycle",
    "required_dimensions",
    "storage_capabilities",
    "update",
    "correction",
    "correction_status",
    "contradiction",
    "relationships",
}

# Keys a trait-composed record (experimental candidates, tests) may specify.
RECORD_TRAIT_COMPOSE_ALLOWED = {
    "name",
    "traits",
    "payload",
    "capture",
    "read_policy",
    "base_kind",
    "required_sections",
    "payload_references",
}

RECORD_PATTERN_ALLOWED = {
    "name",
    "pattern",
    "purpose",
    "canonical_for",
    "replica_of",
    "derived_from",
    "capture",
    "read",
    "read_policy",
    "payload",
    "namespace",
    "required_sections",
    "payload_references",
}

VIEW_ROLE_ALLOWED = {
    "name",
    "occupant",
    "selection",
    "requires",
    "requires_payload",
    "base_kind",
}

PATTERN_TRAITS = {
    "current-status": {
        "traits": ["entity", "stewarded", "current-claim"],
        "base_kind": "claim",
    },
    "event": {
        "traits": ["entity", "occurrence", "evidence-linked"],
        "base_kind": "event",
    },
    "observation": {
        "traits": ["entity", "occurrence"],
        "base_kind": "observation",
    },
    "finding": {
        "traits": ["entity", "epistemic-claim"],
        "base_kind": "claim",
    },
    "question": {
        "traits": ["entity", "stewarded", "open-question"],
        "base_kind": "question",
    },
    "commitment": {
        "traits": ["entity", "stewarded", "active-undertaking"],
        "base_kind": "commitment",
    },
    "decision": {
        "traits": ["entity", "stewarded", "current-claim", "contradictable"],
        "base_kind": "claim",
    },
    "definition": {
        "traits": ["entity", "stewarded", "current-claim"],
        "base_kind": "claim",
    },
    "replica": {
        "traits": ["entity", "stewarded", "current-claim"],
        "base_kind": "claim",
    },
    "task": {
        "traits": ["entity", "stewarded", "staged-progress"],
        "base_kind": "task",
    },
    "phase": {
        "traits": ["entity", "stewarded", "staged-progress"],
        "base_kind": "phase",
    },
}

READ_POLICY = {
    "always": "always_loaded",
    "if_relevant": "routed_by_relevance",
    "query": "queried",
    "always_loaded": "always_loaded",
    "routed_by_relevance": "routed_by_relevance",
    "queried": "queried",
}

CAPTURE_TRIGGER = {
    "at_event": ["event"],
    "session_boundary": ["session_boundary"],
    "source_change": ["source_change"],
    "explicit": ["explicit_request"],
}


STORAGE_CONFLICTS = (("append_with_audit", "conditional_mutation"),)
BACKEND_GUARANTEE_KEYS = {
    "writer_model",
    "record_write",
    "conflict_detection",
    "multi_record_write",
    "durability",
}
BACKEND_GUARANTEE_VALUES = {
    "writer_model": {"single_writer", "single_process", "multi_writer"},
    "record_write": {"atomic_replace", "process_atomic"},
    "conflict_detection": {"revision_token", "none"},
    "multi_record_write": {"non_transactional", "transactional"},
    "durability": {"working_tree", "process_lifetime"},
}


class ResolveError(Exception):
    pass


def load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def canonical_digest(data: Any) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def design_digest(design: dict) -> str:
    return canonical_digest(design)


def format_id(kind: str, version: str) -> str:
    return f"adaptive-artifacts/{kind}@{version}"


def validate_project_design_format(design: dict, catalog: dict) -> None:
    expected = format_id(
        "project-design", catalog["meta"]["project_design_format"]
    )
    if design.get("format") != expected:
        raise ResolveError(
            f"{design.get('project', '<unknown>')}: format "
            f"{design.get('format')!r} != {expected!r}"
        )


def qualified(namespace: str, name: str) -> str:
    return f"{namespace}:{name}"


def parse_qualified(ref: str, label: str) -> tuple[str, str]:
    if ":" not in ref:
        raise ResolveError(f"{label}: must be namespace-qualified, got {ref!r}")
    namespace, local = ref.split(":", 1)
    if not namespace or not local:
        raise ResolveError(f"{label}: invalid qualified reference {ref!r}")
    return namespace, local


def qualify_local(ref: str, namespace: str) -> str:
    if ":" in ref:
        return ref
    return qualified(namespace, ref)


def load_catalog(root: Path = ROOT) -> dict:
    catalog_meta = load_json(root / "catalog.json")
    traits = load_json(root / "traits.json")
    backends = load_json(root / "backends.json")
    return {
        "meta": catalog_meta,
        "traits": traits,
        "backends": backends,
        "catalog_digest": canonical_digest(catalog_meta),
        "traits_digest": canonical_digest(traits),
        "backends_digest": canonical_digest(backends),
    }


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def scalar(name: str, values: list[Any], label: str) -> Any:
    present = [value for value in values if value is not None]
    if not present:
        return None
    first = present[0]
    for value in present[1:]:
        if value != first:
            raise ResolveError(f"{label}: conflicting {name}: {present}")
    return first


def lifecycle_restricts(inner: dict, outer: dict) -> bool:
    inner_states = set(inner["states"])
    outer_states = set(outer["states"])
    if not inner_states <= outer_states:
        return False
    if inner["initial"] not in inner_states:
        return False
    outer_transitions = {
        src: set(dests) for src, dests in outer.get("transitions", {}).items()
    }
    for src, dests in inner.get("transitions", {}).items():
        allowed = outer_transitions.get(src, set())
        if not set(dests) <= allowed:
            return False
    return True


def merge_lifecycles(lifecycles: list[dict], label: str) -> dict | None:
    if not lifecycles:
        return None
    if all(item == lifecycles[0] for item in lifecycles):
        return lifecycles[0]
    chosen = lifecycles[0]
    for other in lifecycles[1:]:
        if other == chosen:
            continue
        if lifecycle_restricts(other, chosen):
            chosen = other
        elif lifecycle_restricts(chosen, other):
            continue
        else:
            raise ResolveError(f"{label}: incompatible lifecycles")
    return chosen


def check_storage_compat(caps: list[str], label: str) -> None:
    have = set(caps)
    for left, right in STORAGE_CONFLICTS:
        if left in have and right in have:
            raise ResolveError(
                f"{label}: storage conflict {left} vs {right}"
            )


def check_trait_incompat(names: list[str], traits: dict, label: str) -> None:
    have = set(names)
    for name in names:
        forbidden = set(traits[name].get("incompatible_with", []))
        clash = have & forbidden
        if clash:
            raise ResolveError(f"{label}: traits {name} incompatible with {sorted(clash)}")


def check_record_definition(record: dict, namespace: str, *, experimental: bool = False) -> None:
    label = record.get("id") or f"{namespace}.{record['name']}"
    if experimental:
        allowed = RECORD_TRAIT_COMPOSE_ALLOWED | {"namespace", "role_compatibility", "id"}
    else:
        allowed = RECORD_TRAIT_COMPOSE_ALLOWED
    extra = set(record) - allowed
    if extra:
        raise ResolveError(f"{label}: forbidden keys {sorted(extra)}")
    owned = RECORD_TRAIT_OWNED & set(record)
    if owned:
        raise ResolveError(f"{label}: {sorted(owned)} must come from traits")


def compose_record(
    record: dict,
    namespace: str,
    traits: dict,
    *,
    experimental: bool = False,
) -> dict:
    check_record_definition(record, namespace, experimental=experimental)
    local_name = record["name"]
    label = f"{namespace}.{local_name}"
    trait_names = record["traits"]
    missing = [item for item in trait_names if item not in traits]
    if missing:
        raise ResolveError(f"{label}: unknown traits {missing}")
    check_trait_incompat(trait_names, traits, label)

    composed = [traits[item] for item in trait_names]
    base_kind = scalar(
        "base_kind",
        [item.get("base_kind") for item in composed] + [record.get("base_kind")],
        label,
    )
    if base_kind is None:
        raise ResolveError(f"{label}: no base_kind from traits or record")

    dimensions: list[str] = []
    payload: list[str] = []
    relationships: list[str] = []
    caps: list[str] = []
    lifecycles: list[dict] = []
    for item in composed:
        dimensions.extend(item.get("required_dimensions", []))
        payload.extend(item.get("payload", []))
        relationships.extend(item.get("relationships", []))
        caps.extend(item.get("storage_capabilities", []))
        if "lifecycle" in item:
            lifecycles.append(item["lifecycle"])
    payload.extend(record.get("payload", []))
    payload = unique(payload)
    relationships = unique(relationships)
    caps = unique(caps)
    check_storage_compat(caps, label)

    lifecycle = merge_lifecycles(lifecycles, label)
    if lifecycle is None:
        raise ResolveError(f"{label}: no lifecycle")

    composed_record = {
        "id": qualified(namespace, local_name),
        "name": local_name,
        "namespace": namespace,
        "experimental": experimental,
        "traits": list(trait_names),
        "base_kind": base_kind,
        "required_dimensions": unique(dimensions),
        "payload": payload,
        "lifecycle": lifecycle,
        "relationships": relationships,
        "update": scalar("update", [item.get("update") for item in composed], label),
        "correction": scalar(
            "correction", [item.get("correction") for item in composed], label
        ),
        "correction_status": scalar(
            "correction_status",
            [item.get("correction_status") for item in composed],
            label,
        ),
        "contradiction": scalar(
            "contradiction", [item.get("contradiction") for item in composed], label
        ),
        "capture": record.get("capture"),
        "read_policy": record.get("read_policy"),
        "storage_capabilities": caps,
        "required_sections": list(record.get("required_sections") or []) or None,
        "payload_references": dict(record.get("payload_references") or {}) or None,
    }
    return {key: value for key, value in composed_record.items() if value is not None}


def normalize_capture(capture: Any, label: str) -> dict | None:
    if capture is None:
        return None
    if isinstance(capture, dict):
        return capture
    if capture not in CAPTURE_TRIGGER:
        raise ResolveError(f"{label}: unknown capture {capture!r}")
    return {"trigger": list(CAPTURE_TRIGGER[capture])}


def normalize_read(record: dict, label: str) -> str | None:
    raw = record.get("read", record.get("read_policy"))
    if raw is None:
        return None
    if raw not in READ_POLICY:
        raise ResolveError(f"{label}: unknown read {raw!r}")
    return READ_POLICY[raw]


def compose_pattern_record(record: dict, traits: dict) -> dict:
    extra = set(record) - RECORD_PATTERN_ALLOWED
    if extra:
        raise ResolveError(f"{record.get('name', '<unnamed>')}: forbidden keys {sorted(extra)}")
    name = record.get("name")
    if not name:
        raise ResolveError("project record missing name")
    namespace = record.get("namespace") or "project"
    label = f"{namespace}.{name}"
    pattern = record.get("pattern")
    if pattern not in PATTERN_TRAITS:
        raise ResolveError(f"{label}: unknown pattern {pattern!r}")
    if pattern == "replica":
        if not record.get("replica_of"):
            raise ResolveError(f"{label}: replica requires replica_of")
    elif not record.get("canonical_for"):
        raise ResolveError(f"{label}: missing canonical_for")
    spec = PATTERN_TRAITS[pattern]
    payload = list(record.get("payload") or [])
    if pattern == "replica":
        for field in ("source", "source_revision"):
            if field not in payload:
                payload.append(field)
    trait_shaped = {
        "name": name,
        "traits": list(spec["traits"]),
        "payload": payload,
        "base_kind": spec["base_kind"],
    }
    capture = normalize_capture(record.get("capture"), label)
    if capture:
        trait_shaped["capture"] = capture
    read_policy = normalize_read(record, label)
    if read_policy:
        trait_shaped["read_policy"] = read_policy
    if record.get("required_sections"):
        trait_shaped["required_sections"] = list(record["required_sections"])
    if record.get("payload_references"):
        trait_shaped["payload_references"] = dict(record["payload_references"])
    composed = compose_record(trait_shaped, namespace, traits, experimental=False)
    composed["pattern"] = pattern
    for key in ("purpose", "canonical_for", "replica_of", "derived_from"):
        if record.get(key):
            composed[key] = record[key]
    return composed


def compose_project_records(design: dict, traits: dict, records: dict[str, dict]) -> None:
    seen_owners: dict[str, str] = {}
    for raw in design.get("records") or []:
        composed = compose_pattern_record(raw, traits)
        if composed["id"] in records:
            raise ResolveError(f"duplicate record {composed['id']}")
        owner = composed.get("canonical_for") or (
            "replica:" + composed.get("replica_of", "")
        )
        if owner in seen_owners:
            raise ResolveError(
                f"{design['project']}: {composed['id']} and {seen_owners[owner]} "
                f"share ownership {owner!r}"
            )
        seen_owners[owner] = composed["id"]
        records[composed["id"]] = composed


def satisfies(record: dict, role: dict) -> bool:
    if not set(role["requires"]) <= set(record["traits"]):
        return False
    if not set(role.get("requires_payload", [])) <= set(record.get("payload", [])):
        return False
    required_kind = role.get("base_kind")
    return required_kind is None or record["base_kind"] == required_kind


def validate_selection(selection: Any, candidates: list[dict], label: str) -> None:
    if not isinstance(selection, dict) or set(selection) != {"all"}:
        raise ResolveError(f"{label}: selection must contain only an 'all' list")
    clauses = selection["all"]
    if not isinstance(clauses, list):
        raise ResolveError(f"{label}: selection.all must be a list")
    for clause in clauses:
        if not isinstance(clause, dict) or set(clause) != {"field", "equals"}:
            raise ResolveError(
                f"{label}: each selection clause requires only field and equals"
            )
        field = clause["field"]
        if field == "lifecycle_state":
            invalid = [
                record["id"]
                for record in candidates
                if clause["equals"] not in record["lifecycle"]["states"]
            ]
        elif isinstance(field, str) and field.startswith("payload."):
            payload_field = field[len("payload.") :]
            if not payload_field or "." in payload_field:
                raise ResolveError(f"{label}: invalid selection field {field!r}")
            invalid = [
                record["id"]
                for record in candidates
                if payload_field not in record.get("payload", [])
            ]
        else:
            raise ResolveError(f"{label}: unsupported selection field {field!r}")
        if invalid:
            raise ResolveError(
                f"{label}: selection field/value incompatible with {invalid}"
            )


def resolve_views(
    view_specs: list[dict],
    records: dict[str, dict],
    occupancy: dict,
    view_params: dict,
    namespace: str = "project",
    design_label: str = "<unknown design>",
) -> list[dict]:
    views = []
    for view in view_specs:
        name = view.get("name")
        if not name:
            raise ResolveError("view missing name")
        view_id = qualified(namespace, name)
        extra_view = set(view) - {
            "name",
            "owns_facts",
            "freshness",
            "parameters",
            "roles",
        }
        if extra_view:
            raise ResolveError(f"{view_id}: forbidden keys {sorted(extra_view)}")
        if view.get("owns_facts") is not False:
            raise ResolveError(f"{view_id}: views must not own facts")
        params = view_params.get(view_id, {})
        unknown = set(params) - set(view.get("parameters", []))
        if unknown:
            raise ResolveError(f"{view_id}: unknown parameters {sorted(unknown)}")
        chosen = occupancy.get(view_id, {})
        roles = []
        for role in view.get("roles") or []:
            extra_role = set(role) - VIEW_ROLE_ALLOWED
            if extra_role:
                raise ResolveError(
                    f"{view_id}.{role.get('name', '<unnamed>')}: "
                    f"forbidden keys {sorted(extra_role)}"
                )
            role_name = role.get("name")
            if not role_name:
                raise ResolveError(f"{view_id}: role missing name")
            if not role.get("requires_payload"):
                raise ResolveError(
                    f"{view_id}.{role_name}: requires_payload must be a non-empty "
                    f"list (design {design_label})"
                )
            occupant_ref = chosen.get(role_name, role.get("occupant"))
            if not occupant_ref:
                raise ResolveError(f"{view_id}.{role_name}: missing occupant")
            occupant = qualify_local(occupant_ref, namespace)
            occupant_record = records.get(occupant)
            if occupant_record is None:
                raise ResolveError(f"{view_id}.{role_name}: unknown occupant {occupant}")
            resolved_role = {
                "name": role_name,
                "requires": list(role.get("requires") or occupant_record["traits"]),
                "requires_payload": list(role.get("requires_payload", [])),
                "base_kind": role.get("base_kind", occupant_record["base_kind"]),
                "selection": role.get("selection"),
            }
            if "selection" not in role:
                raise ResolveError(f"{view_id}.{role_name}: missing explicit selection")
            candidate_records = [
                record for record in records.values() if satisfies(record, resolved_role)
            ]
            candidates = [record["id"] for record in candidate_records]
            validate_selection(
                resolved_role["selection"],
                candidate_records,
                f"{view_id}.{role_name}",
            )
            if occupant not in candidates:
                raise ResolveError(
                    f"{view_id}.{role_name}: {occupant} does not satisfy role"
                )
            extra = set(chosen) - {item["name"] for item in view["roles"]}
            if extra:
                raise ResolveError(f"{view_id}: unknown occupancy roles {sorted(extra)}")
            roles.append({**resolved_role, "occupant": occupant, "candidates": candidates})
        views.append(
            {
                "id": view_id,
                "name": name,
                "namespace": namespace,
                "owns_facts": False,
                "freshness": view.get("freshness"),
                "parameters": params,
                "roles": roles,
            }
        )
    return views


def validate_bundle_links(
    bundle_id: str,
    namespace: str,
    bundle: dict,
    records: dict[str, dict],
) -> list[dict]:
    record_locals = set(bundle["records"])
    links = []
    for link in bundle.get("relationships", []):
        from_local = link["from"]
        to_local = link["to"]
        if from_local not in record_locals:
            raise ResolveError(
                f"{bundle_id}: link source {from_local!r} not in bundle records"
            )
        if to_local not in record_locals:
            raise ResolveError(
                f"{bundle_id}: link target {to_local!r} not in bundle records"
            )
        from_id = qualify_local(from_local, namespace)
        rel_type = link["type"]
        source = records[from_id]
        allowed = set(source.get("relationships", []))
        if rel_type not in allowed:
            raise ResolveError(
                f"{bundle_id}: {from_id} does not advertise relationship {rel_type!r}"
            )
        links.append(
            {
                "from": from_id,
                "to": qualify_local(to_local, namespace),
                "type": rel_type,
            }
        )
    return links


def resolve_bundles(
    bundle_specs: list[dict],
    records: dict[str, dict],
    namespace: str = "project",
) -> list[dict]:
    bundles = []
    seen: set[str] = set()
    for bundle in bundle_specs:
        name = bundle.get("name")
        if not name:
            raise ResolveError("bundle missing name")
        bundle_id = qualified(namespace, name)
        if bundle_id in seen:
            raise ResolveError(f"duplicate bundle {bundle_id}")
        seen.add(bundle_id)
        extra = set(bundle) - {
            "name",
            "optional",
            "records",
            "relationships",
            "capture",
        }
        if extra:
            raise ResolveError(f"{bundle_id}: forbidden keys {sorted(extra)}")
        record_ids = []
        for local in bundle.get("records") or []:
            record_id = qualify_local(local, namespace)
            if record_id not in records:
                raise ResolveError(f"{bundle_id}: unknown record {local!r}")
            record_ids.append(record_id)
        links = validate_bundle_links(bundle_id, namespace, bundle, records)
        bundles.append(
            {
                "id": bundle_id,
                "name": name,
                "namespace": namespace,
                "optional": bundle.get("optional", True),
                "records": record_ids,
                "relationships": links,
                "capture": bundle.get("capture"),
            }
        )
    return bundles


def match_backend(
    name: str,
    backends: dict,
    baseline: list[str],
    records: list[dict],
) -> dict:
    if name not in backends:
        raise ResolveError(f"unknown backend {name!r}")
    guarantees = backends[name].get("guarantees")
    if not isinstance(guarantees, dict) or set(guarantees) != BACKEND_GUARANTEE_KEYS:
        raise ResolveError(
            f"backend {name!r}: guarantees must define "
            f"{sorted(BACKEND_GUARANTEE_KEYS)}"
        )
    for key, value in guarantees.items():
        if value not in BACKEND_GUARANTEE_VALUES[key]:
            raise ResolveError(
                f"backend {name!r}: unsupported {key} guarantee {value!r}"
            )
    trait_required = unique(
        [cap for record in records for cap in record["storage_capabilities"]]
    )
    required = unique(baseline + trait_required)
    advertised = list(backends[name]["capabilities"])
    missing = [cap for cap in required if cap not in advertised]
    return {
        "name": name,
        "capabilities": advertised,
        "guarantees": guarantees,
        "baseline_required": list(baseline),
        "trait_required": trait_required,
        "required": required,
        "missing": missing,
        "match": "ok" if not missing else "incompatible",
    }


def build_source_lock(catalog: dict) -> dict:
    return {
        "catalog_version": catalog["meta"]["version"],
        "catalog": catalog["catalog_digest"],
        "traits": catalog["traits_digest"],
        "backends": catalog["backends_digest"],
    }


def validate_source_lock(design: dict, catalog: dict) -> dict:
    lock = design.get("source_lock")
    if not lock:
        raise ResolveError(f"{design['project']}: missing required source_lock")
    meta = catalog["meta"]
    extra = set(lock) - {"catalog_version", "catalog", "traits", "backends"}
    if extra:
        raise ResolveError(
            f"{design['project']}: source_lock unknown keys {sorted(extra)}"
        )
    if lock.get("catalog_version") != meta["version"]:
        raise ResolveError(
            f"{design['project']}: source_lock catalog_version "
            f"{lock.get('catalog_version')} != {meta['version']}"
        )
    if lock.get("catalog") != catalog["catalog_digest"]:
        raise ResolveError(f"{design['project']}: source_lock catalog digest mismatch")
    if lock.get("traits") != catalog["traits_digest"]:
        raise ResolveError(f"{design['project']}: source_lock traits digest mismatch")
    if lock.get("backends") != catalog["backends_digest"]:
        raise ResolveError(f"{design['project']}: source_lock backends digest mismatch")
    return lock


def compose_experimental_candidates(
    design: dict,
    traits: dict,
    views: list[dict],
) -> list[dict]:
    candidates = []
    view_index = {view["id"]: view for view in views}
    for raw in design.get("experimental_candidates", []):
        namespace = raw["namespace"]
        composed = compose_record(raw, namespace, traits, experimental=True)
        compat = raw.get("role_compatibility")
        if compat:
            view_id = compat["view"]
            parse_qualified(view_id, f"{composed['id']} role_compatibility.view")
            view = view_index.get(view_id)
            if view is None:
                raise ResolveError(f"{composed['id']}: unknown view {view_id}")
            role = next(
                (item for item in view["roles"] if item["name"] == compat["role"]),
                None,
            )
            if role is None:
                raise ResolveError(
                    f"{composed['id']}: unknown role {compat['role']} in {view_id}"
                )
            if not satisfies(composed, role):
                raise ResolveError(
                    f"{composed['id']}: incompatible with {view_id}.{compat['role']}"
                )
            validate_selection(
                role["selection"],
                [composed],
                f"{composed['id']} compatibility with {view_id}.{compat['role']}",
            )
            composed["role_compatibility"] = {
                "view": view_id,
                "role": compat["role"],
                "compatible": True,
            }
        candidates.append(composed)
    return candidates


def resolution_block(catalog: dict, lock: dict, design: dict) -> dict:
    meta = catalog["meta"]
    return {
        "catalog_version": meta["version"],
        "project_design_format": meta["project_design_format"],
        "resolved_contract_format": meta["resolved_contract_format"],
        "traits_version": meta["traits_version"],
        "backends_version": meta["backends_version"],
        "design_digest": design_digest(design),
        "source_lock": lock,
        "source_digests": {
            "catalog.json": catalog["catalog_digest"],
            "traits.json": catalog["traits_digest"],
            "backends.json": catalog["backends_digest"],
        },
    }


def check_qualified_project_refs(design: dict) -> None:
    project = design["project"]
    for key in design.get("view_params", {}):
        parse_qualified(key, f"{project} view_params")
    for key in design.get("occupancy", {}):
        parse_qualified(key, f"{project} occupancy")


def resolve_project(
    design: dict, catalog: dict, design_path: str | Path | None = None
) -> dict:
    design_label = str(design_path) if design_path is not None else design.get(
        "project", "<unknown project>"
    )
    validate_project_design_format(design, catalog)
    if "families" in design:
        raise ResolveError(
            f"{design['project']}: families are not part of this format; "
            "declare records, views, and bundles on the project"
        )
    if design.get("overrides"):
        raise ResolveError(f"{design['project']}: overrides must be empty")
    lock = validate_source_lock(design, catalog)
    check_qualified_project_refs(design)
    records: dict[str, dict] = {}
    compose_project_records(design, catalog["traits"], records)
    record_list = list(records.values())
    baseline = catalog["meta"]["baseline_backend_capabilities"]
    backend = match_backend(
        design["backend"], catalog["backends"], baseline, record_list
    )
    if backend["match"] != "ok":
        raise ResolveError(
            f"{design['project']}: backend {backend['name']} missing {backend['missing']}"
        )
    views = resolve_views(
        design.get("views") or [],
        records,
        design.get("occupancy", {}),
        design.get("view_params", {}),
        design_label=design_label,
    )
    bundles = resolve_bundles(design.get("bundles") or [], records)
    experimental = compose_experimental_candidates(design, catalog["traits"], views)
    all_records = record_list + experimental
    backend_with_experimental = match_backend(
        design["backend"], catalog["backends"], baseline, all_records
    )
    if backend_with_experimental["match"] != "ok":
        raise ResolveError(
            f"{design['project']}: experimental candidates need {backend_with_experimental['missing']}"
        )
    return {
        "format": format_id(
            "resolved-contract", catalog["meta"]["resolved_contract_format"]
        ),
        "project": design["project"],
        "resolution": resolution_block(catalog, lock, design),
        "backend": backend_with_experimental,
        "records": record_list,
        "views": views,
        "bundles": bundles,
        "experimental_candidates": experimental,
        "source_revisions": design.get("source_revisions", {}),
        "gaps": design.get("gaps", []),
    }


def dump_contract(contract: dict) -> str:
    return json.dumps(contract, indent=2) + "\n"


def write_contract(contract: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_contract(contract))


def resolve_fixture(path: Path, catalog: dict | None = None) -> dict:
    catalog = catalog or load_catalog()
    return resolve_project(load_json(path), catalog, design_path=path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="resolve.py")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("lock", help="print source_lock for catalog, traits, and backends")
    project_p = sub.add_parser("project", help="resolve one project design")
    project_p.add_argument("design", type=Path)
    project_p.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    catalog = load_catalog()
    if args.cmd == "lock":
        print(json.dumps(build_source_lock(catalog), indent=2))
        return 0
    if args.cmd == "project":
        contract = resolve_project(load_json(args.design), catalog, design_path=args.design)
        if args.out:
            write_contract(contract, args.out)
            print(f"wrote {args.out}")
        else:
            print(dump_contract(contract), end="")
        return 0

    fixtures = sorted(FIXTURE_DIR.glob("*.json"))
    if not fixtures:
        print("no fixtures", file=sys.stderr)
        return 1
    for path in fixtures:
        contract = resolve_fixture(path, catalog)
        out = RESOLVED_DIR / f"{contract['project']}.json"
        write_contract(contract, out)
        print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ResolveError as exc:
        print(f"resolve: {exc}", file=sys.stderr)
        sys.exit(1)
