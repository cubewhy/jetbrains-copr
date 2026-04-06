"""GitHub Release publishing via gh CLI."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import tempfile

from jetbrains_copr.errors import PublishingError, SetupError
from jetbrains_copr.util import require_command, tail_lines


class GitHubReleasePublisher:
    """Idempotent GitHub Release publisher based on gh CLI."""

    def ensure_ready(self) -> None:
        require_command("gh")
        if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
            return
        completed = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise SetupError(
                "GitHub Release publishing is enabled, but gh is not authenticated and no GH_TOKEN or GITHUB_TOKEN is set."
            )

    def publish(
        self,
        *,
        repository: str,
        tag: str,
        title: str,
        notes: str,
        assets: list[Path],
    ) -> None:
        """Create or update a release and upload assets."""

        self.ensure_ready()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(notes)
            notes_file = Path(handle.name)

        try:
            release_exists = self._release_exists(repository, tag)
            if release_exists:
                self._run(
                    [
                        "gh",
                        "release",
                        "edit",
                        tag,
                        "--repo",
                        repository,
                        "--title",
                        title,
                        "--notes-file",
                        str(notes_file),
                    ]
                )
            else:
                command = [
                    "gh",
                    "release",
                    "create",
                    tag,
                    "--repo",
                    repository,
                    "--title",
                    title,
                    "--notes-file",
                    str(notes_file),
                ]
                command.extend(str(asset) for asset in assets)
                self._run(command)
                return

            if assets:
                upload_command = [
                    "gh",
                    "release",
                    "upload",
                    tag,
                    "--repo",
                    repository,
                    "--clobber",
                    *(str(asset) for asset in assets),
                ]
                self._run(upload_command)
        finally:
            notes_file.unlink(missing_ok=True)

    def _release_exists(self, repository: str, tag: str) -> bool:
        completed = subprocess.run(
            ["gh", "release", "view", tag, "--repo", repository],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            return True
        combined = "\n".join(part for part in [completed.stdout, completed.stderr] if part).lower()
        if "not found" in combined or "could not find" in combined:
            return False
        raise PublishingError(f"Could not determine whether GitHub release {tag} exists.\n{tail_lines(combined)}")

    def _run(self, command: list[str]) -> None:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            details = "\n".join(part for part in [tail_lines(completed.stdout), tail_lines(completed.stderr)] if part)
            raise PublishingError(f"GitHub Release command failed: {' '.join(command)}\n{details}")
