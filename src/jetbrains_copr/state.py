"""Persistent version state management."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from jetbrains_copr.errors import StateError
from jetbrains_copr.models import ProductConfig, ReleaseInfo, StateEntry, StateFile
from jetbrains_copr.util import utcnow


def load_state(path: Path) -> StateFile:
    """Load a state file. Missing files produce an empty state."""

    if not path.exists():
        return StateFile()

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StateError(f"State file could not be read: {path}: {exc}") from exc

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise StateError(f"State file is not valid JSON: {path}: {exc}") from exc

    try:
        return StateFile.model_validate(payload)
    except ValidationError as exc:
        raise StateError(f"State file validation failed for {path}:\n{exc}") from exc


def save_state(path: Path, state: StateFile) -> None:
    """Write state atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(state.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def state_entry_for_product(state: StateFile, product: ProductConfig) -> StateEntry | None:
    """Return the saved state entry for a product variant.

    Stable releases fall back to the legacy bare-code key so older state files
    remain valid after introducing release channel support.
    """

    entry = state.products.get(product.identity)
    if entry is not None:
        return entry
    if product.release_type == "release":
        return state.products.get(product.code)
    return None


def release_matches_state(state: StateFile, product: ProductConfig, release: ReleaseInfo) -> bool:
    """Return True if the release is already marked as processed."""

    entry = state_entry_for_product(state, product)
    if entry is None:
        return False
    return entry.version == release.version and entry.build == release.build


def update_state_for_release(state: StateFile, product: ProductConfig, release: ReleaseInfo) -> None:
    """Record a successful build and publish for a product."""

    state.products[product.identity] = StateEntry(
        version=release.version,
        build=release.build,
        rpm_name=product.rpm_name,
        updated_at=utcnow(),
    )
    if product.release_type == "release":
        state.products.pop(product.code, None)
