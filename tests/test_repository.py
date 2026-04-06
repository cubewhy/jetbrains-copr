from __future__ import annotations

from datetime import date
from pathlib import Path
import subprocess

from jetbrains_copr.models import ProductConfig, ReleaseInfo
from jetbrains_copr.repository import GitStateSynchronizer


def make_product() -> ProductConfig:
    return ProductConfig(
        code="IIU",
        name="IntelliJ IDEA Ultimate",
        rpm_name="jetbrains-idea-ultimate",
        executable_name="idea",
        desktop_file_name="jetbrains-idea-ultimate.desktop",
        icon_path="bin/idea.png",
        startup_wm_class="jetbrains-idea",
        comment="JetBrains IntelliJ IDEA Ultimate IDE",
        categories=["Development", "IDE"],
    )


def make_release() -> ReleaseInfo:
    return ReleaseInfo(
        code="IIU",
        version="2026.1",
        build="261.22158.277",
        release_date=date(2026, 3, 25),
        downloads={},
    )


def test_git_state_synchronizer_commits_and_pushes_state_updates(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    state_path = repo_root / "state" / "versions.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{}\n", encoding="utf-8")
    calls: list[tuple[list[str], Path | None]] = []

    def fake_run(command: list[str], *, capture_output: bool, text: bool, check: bool, cwd: Path | None = None):
        calls.append((command, cwd))
        if command == ["git", "rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(command, 0, f"{repo_root}\n", "")
        if command == ["git", "diff", "--quiet", "--", "state/versions.json"]:
            return subprocess.CompletedProcess(command, 1, "", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("jetbrains_copr.repository.require_command", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr("jetbrains_copr.repository.subprocess.run", fake_run)

    GitStateSynchronizer(state_path=state_path).sync(make_product(), make_release())

    assert [command for command, _cwd in calls] == [
        ["git", "rev-parse", "--show-toplevel"],
        ["git", "diff", "--quiet", "--", "state/versions.json"],
        ["git", "add", "--", "state/versions.json"],
        ["git", "commit", "-m", "Update release state for IIU:release 2026.1 (261.22158.277)"],
        ["git", "pull", "--rebase"],
        ["git", "push"],
    ]
    assert calls[0][1] == state_path.parent
    assert all(cwd == repo_root for _command, cwd in calls[1:])


def test_git_state_synchronizer_skips_clean_state_file(monkeypatch, tmp_path: Path):
    repo_root = tmp_path / "repo"
    state_path = repo_root / "state" / "versions.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{}\n", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, capture_output: bool, text: bool, check: bool, cwd: Path | None = None):
        calls.append(command)
        if command == ["git", "rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(command, 0, f"{repo_root}\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("jetbrains_copr.repository.require_command", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr("jetbrains_copr.repository.subprocess.run", fake_run)

    GitStateSynchronizer(state_path=state_path).sync(make_product(), make_release())

    assert calls == [
        ["git", "rev-parse", "--show-toplevel"],
        ["git", "diff", "--quiet", "--", "state/versions.json"],
    ]
