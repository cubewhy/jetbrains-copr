"""Git repository synchronization helpers."""

from __future__ import annotations

from pathlib import Path
import logging
import subprocess

from jetbrains_copr.errors import PublishingError, SetupError
from jetbrains_copr.models import ProductConfig, ReleaseInfo
from jetbrains_copr.util import require_command, tail_lines


LOGGER = logging.getLogger(__name__)


class GitStateSynchronizer:
    """Commit and push state file updates from inside a git worktree."""

    def __init__(self, *, state_path: Path):
        self.state_path = state_path.resolve()
        self._repo_root: Path | None = None

    def sync(self, product: ProductConfig, release: ReleaseInfo) -> None:
        """Commit and push the current state file change."""

        repo_root = self._resolve_repo_root()
        state_rel_path = self._resolve_state_path(repo_root)

        if self._state_diff_is_clean(repo_root, state_rel_path):
            LOGGER.info("Skipping git state sync for %s because %s has no changes.", product.identity, state_rel_path)
            return

        commit_message = f"Update release state for {product.identity} {release.version} ({release.build})"
        self._run(["git", "add", "--", state_rel_path.as_posix()], cwd=repo_root)
        self._run(["git", "commit", "-m", commit_message], cwd=repo_root)
        self._run(["git", "pull", "--rebase"], cwd=repo_root)
        self._run(["git", "push"], cwd=repo_root)

    def _resolve_repo_root(self) -> Path:
        if self._repo_root is not None:
            return self._repo_root

        require_command("git")
        probe_dir = self.state_path.parent if self.state_path.parent.exists() else None
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
            cwd=probe_dir,
        )
        if completed.returncode != 0:
            details = "\n".join(part for part in [tail_lines(completed.stdout), tail_lines(completed.stderr)] if part)
            raise SetupError(f"Could not locate the git repository for state sync.\n{details}")

        repo_root = completed.stdout.strip()
        if not repo_root:
            raise SetupError("Git reported an empty repository root while preparing state sync.")

        self._repo_root = Path(repo_root).resolve()
        return self._repo_root

    def _resolve_state_path(self, repo_root: Path) -> Path:
        try:
            return self.state_path.relative_to(repo_root)
        except ValueError as exc:
            raise SetupError(f"State file {self.state_path} is outside the git repository {repo_root}.") from exc

    def _state_diff_is_clean(self, repo_root: Path, state_rel_path: Path) -> bool:
        completed = subprocess.run(
            ["git", "diff", "--quiet", "--", state_rel_path.as_posix()],
            capture_output=True,
            text=True,
            check=False,
            cwd=repo_root,
        )
        if completed.returncode == 0:
            return True
        if completed.returncode == 1:
            return False

        details = "\n".join(part for part in [tail_lines(completed.stdout), tail_lines(completed.stderr)] if part)
        raise PublishingError(f"Could not determine whether {state_rel_path} changed before git sync.\n{details}")

    def _run(self, command: list[str], *, cwd: Path) -> None:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
        )
        if completed.returncode != 0:
            details = "\n".join(part for part in [tail_lines(completed.stdout), tail_lines(completed.stderr)] if part)
            raise PublishingError(f"Git state sync failed: {' '.join(command)}\n{details}")
