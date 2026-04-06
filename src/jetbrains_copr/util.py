"""General utilities."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import re
import shutil

from jetbrains_copr.errors import SetupError


RPM_VERSION_ALLOWED = re.compile(r"[^A-Za-z0-9._+~^]")
RPM_RELEASE_ALLOWED = re.compile(r"[^A-Za-z0-9._+~^]")
TAG_ALLOWED = re.compile(r"[^A-Za-z0-9._-]")


def ensure_directory(path: Path) -> Path:
    """Create a directory and return it."""

    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_rpm_version(value: str) -> str:
    """Sanitize a value for use in the RPM Version field."""

    sanitized = RPM_VERSION_ALLOWED.sub("_", value.strip())
    sanitized = sanitized.strip("._+~^-")
    if not sanitized:
        raise ValueError("RPM version sanitized to an empty value")
    return sanitized


def sanitize_rpm_release(value: str) -> str:
    """Sanitize a value for use in the RPM Release field."""

    sanitized = RPM_RELEASE_ALLOWED.sub("_", value.strip())
    sanitized = sanitized.strip("._+~^-")
    if not sanitized:
        raise ValueError("RPM release sanitized to an empty value")
    return sanitized


def sanitize_tag_component(value: str) -> str:
    """Create a safe deterministic Git tag component."""

    sanitized = TAG_ALLOWED.sub("-", value.strip())
    sanitized = re.sub(r"-{2,}", "-", sanitized)
    sanitized = sanitized.strip("-.")
    if not sanitized:
        raise ValueError("tag component sanitized to an empty value")
    return sanitized


def utcnow() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(timezone.utc)


def format_rpm_changelog_date(value: date | datetime) -> str:
    """Format a date for the RPM changelog header."""

    if isinstance(value, datetime):
        value = value.astimezone(timezone.utc).date()
    return value.strftime("%a %b %d %Y")


def require_command(command: str) -> str:
    """Resolve a command from PATH or raise a clear setup error."""

    resolved = shutil.which(command)
    if resolved is None:
        raise SetupError(f"Required command '{command}' was not found in PATH.")
    return resolved


def tail_lines(text: str, *, count: int = 40) -> str:
    """Return the last lines of a command output for error messages."""

    lines = text.strip().splitlines()
    if len(lines) <= count:
        return text.strip()
    return "\n".join(lines[-count:])
