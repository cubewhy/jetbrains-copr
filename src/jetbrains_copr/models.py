"""Typed project models."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


CODE_PATTERN = re.compile(r"^[A-Z0-9]+$")
RPM_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9+_.-]*$")


class Architecture(StrEnum):
    """Supported package architectures."""

    X86_64 = "x86_64"
    AARCH64 = "aarch64"

    @property
    def api_key(self) -> str:
        if self is Architecture.X86_64:
            return "linux"
        return "linuxARM64"

    @property
    def rpm_target(self) -> str:
        return f"{self.value}-redhat-linux"


ARCHITECTURE_ORDER = [Architecture.X86_64, Architecture.AARCH64]


class ProductConfig(BaseModel):
    """Config entry for a single JetBrains product."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    rpm_name: str = Field(min_length=1)
    executable_name: str = Field(min_length=1)
    desktop_file_name: str = Field(min_length=1)
    icon_path: str = Field(min_length=1)
    startup_wm_class: str = Field(min_length=1)
    comment: str = Field(min_length=1)
    categories: list[str] = Field(min_length=1)
    enabled: bool = True

    @field_validator(
        "code",
        "name",
        "rpm_name",
        "executable_name",
        "desktop_file_name",
        "icon_path",
        "startup_wm_class",
        "comment",
        mode="before",
    )
    @classmethod
    def strip_text_fields(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        if not CODE_PATTERN.fullmatch(value):
            raise ValueError("must contain only uppercase letters and digits")
        return value

    @field_validator("rpm_name")
    @classmethod
    def validate_rpm_name(cls, value: str) -> str:
        if not RPM_NAME_PATTERN.fullmatch(value):
            raise ValueError("must match RPM package naming rules")
        return value

    @field_validator("desktop_file_name")
    @classmethod
    def validate_desktop_name(cls, value: str) -> str:
        if not value.endswith(".desktop"):
            raise ValueError("must end with .desktop")
        return value

    @field_validator("icon_path")
    @classmethod
    def validate_icon_path(cls, value: str) -> str:
        if value.startswith("/"):
            raise ValueError("must be a path relative to the archive root")
        return value

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if isinstance(item, str) and item.strip()]
        if not cleaned:
            raise ValueError("must contain at least one non-empty category")
        return cleaned


class ProductsConfig(BaseModel):
    """Top-level product configuration file."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    products: list[ProductConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_fields(self) -> "ProductsConfig":
        codes: set[str] = set()
        rpm_names: set[str] = set()
        for product in self.products:
            if product.code in codes:
                raise ValueError(f"duplicate product code: {product.code}")
            if product.rpm_name in rpm_names:
                raise ValueError(f"duplicate rpm_name: {product.rpm_name}")
            codes.add(product.code)
            rpm_names.add(product.rpm_name)
        return self


class DownloadInfo(BaseModel):
    """Release download metadata for one architecture."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    link: str = Field(min_length=1)
    checksum_link: str | None = None
    size: int | None = None


class ReleaseInfo(BaseModel):
    """Normalized release metadata returned by the JetBrains API."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    version: str = Field(min_length=1)
    build: str = Field(min_length=1)
    release_date: date
    notes_url: str | None = None
    downloads: dict[Architecture, DownloadInfo] = Field(default_factory=dict)

    def available_architectures(self) -> list[Architecture]:
        return [arch for arch in ARCHITECTURE_ORDER if arch in self.downloads]


class StateEntry(BaseModel):
    """Saved release state for a product."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    build: str = Field(min_length=1)
    rpm_name: str = Field(min_length=1)
    updated_at: datetime


class StateFile(BaseModel):
    """Persistent state file."""

    model_config = ConfigDict(extra="forbid")

    products: dict[str, StateEntry] = Field(default_factory=dict)
