"""COPR submission helpers."""

from __future__ import annotations

from pathlib import Path
import logging
import os
import subprocess
import tempfile

from jetbrains_copr.errors import PublishingError, SetupError
from jetbrains_copr.util import require_command, tail_lines


LOGGER = logging.getLogger(__name__)


class CoprPublisher:
    """Submit SRPM builds to COPR with copr-cli."""

    def ensure_ready(self) -> None:
        require_command("copr-cli")
        self._resolve_config_path()

    def publish(self, *, project: str, srpm_path: Path) -> None:
        """Submit the SRPM to COPR."""

        self.ensure_ready()
        config_path = self._resolve_config_path()
        LOGGER.info("Running copr-cli build for %s using config %s", srpm_path.name, config_path)

        completed = subprocess.run(
            ["copr-cli", "--config", str(config_path), "build", project, str(srpm_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            details = "\n".join(part for part in [tail_lines(completed.stdout), tail_lines(completed.stderr)] if part)
            raise PublishingError(f"COPR submission failed for {srpm_path.name}.\n{details}")

    def _resolve_config_path(self) -> Path:
        explicit = os.environ.get("COPR_CONFIG")
        if explicit:
            path = Path(explicit).expanduser()
            if path.exists():
                return path
            raise SetupError(f"COPR_CONFIG points to a missing file: {path}")

        default_path = Path("~/.config/copr").expanduser()
        if default_path.exists():
            return default_path

        login = os.environ.get("COPR_LOGIN")
        username = os.environ.get("COPR_USERNAME")
        token = os.environ.get("COPR_TOKEN")
        if login and username and token:
            temp_dir = Path(tempfile.gettempdir()) / "jetbrains-copr"
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_path = temp_dir / "copr.conf"
            temp_path.write_text(
                "\n".join(
                    [
                        "[copr-cli]",
                        f"login = {login}",
                        f"username = {username}",
                        f"token = {token}",
                        "copr_url = https://copr.fedorainfracloud.org",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            temp_path.chmod(0o600)
            return temp_path

        raise SetupError(
            "COPR publishing is enabled, but no COPR config file or COPR_LOGIN/COPR_USERNAME/COPR_TOKEN environment variables are available."
        )
