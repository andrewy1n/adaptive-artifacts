"""Shared paths for the shipped artifact runtime."""

from __future__ import annotations

import json
import os
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parent
TOOLS_ROOT = RUNTIME_ROOT.parent
EXTENSION_ROOT = TOOLS_ROOT.parent
CONTRACTS_ROOT = EXTENSION_ROOT / "design" / "contracts"

DESIGN_DIR = ".artifacts"
LEGACY_DESIGN_DIR = "adaptive-artifacts"
PROJECT_DESIGN_NAME = "project-design.json"
RESOLVED_CONTRACT_NAME = "resolved-contract.json"
DEFAULT_STORE_NAME = ".artifacts"


def extension_root() -> Path:
    plugin = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin:
        candidate = Path(plugin)
        # Cursor may set this to an unrelated plugin while running project hooks.
        if (candidate / "tools" / "artifacts.py").is_file():
            return candidate
    return EXTENSION_ROOT


def contracts_root() -> Path:
    return extension_root() / "design" / "contracts"


def contracts_on_path() -> None:
    import sys

    root = str(contracts_root())
    if root not in sys.path:
        sys.path.insert(0, root)


def project_design_path(root: Path) -> Path:
    current = root / DESIGN_DIR / PROJECT_DESIGN_NAME
    if current.is_file():
        return current
    legacy = root / LEGACY_DESIGN_DIR / PROJECT_DESIGN_NAME
    if legacy.is_file():
        return legacy
    return current


def resolved_contract_path(root: Path) -> Path:
    return project_design_path(root).with_name(RESOLVED_CONTRACT_NAME)


def default_store_path(root: Path | None = None) -> Path:
    env = os.environ.get("ARTIFACTS_STORE")
    if env:
        return Path(env)
    base = root if root is not None else Path.cwd()
    return base / DEFAULT_STORE_NAME


def project_root_from_store(store: Path) -> Path:
    store = store.resolve()
    if store.name == DEFAULT_STORE_NAME:
        return store.parent
    return store.parent


def contract_path_from_meta(store: Path) -> Path | None:
    meta_path = store / "meta.json"
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(meta, dict):
        return None
    ref = meta.get("contract")
    if not isinstance(ref, str) or not ref:
        return None
    path = Path(ref)
    if path.is_absolute():
        return path
    return (project_root_from_store(store) / path).resolve()
