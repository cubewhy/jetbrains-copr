"""Configuration loading and validation."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from jetbrains_copr.errors import ConfigError
from jetbrains_copr.models import ProductsConfig


def load_products_config(path: Path) -> ProductsConfig:
    """Load and validate the product configuration JSON file."""

    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file does not exist: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"Configuration file could not be read: {path}: {exc}") from exc

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Configuration file is not valid JSON: {path}: {exc}") from exc

    try:
        return ProductsConfig.model_validate(payload)
    except ValidationError as exc:
        raise ConfigError(f"Configuration validation failed for {path}:\n{exc}") from exc
