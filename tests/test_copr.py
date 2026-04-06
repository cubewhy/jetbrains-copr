from __future__ import annotations

from pathlib import Path
import subprocess

from jetbrains_copr.copr import CoprPublisher


def test_copr_publish_uses_explicit_config_argument(monkeypatch, tmp_path: Path):
    srpm_path = tmp_path / "package.src.rpm"
    srpm_path.write_text("x", encoding="utf-8")
    config_path = tmp_path / "copr.conf"
    config_path.write_text("[copr-cli]\n", encoding="utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr("jetbrains_copr.copr.require_command", lambda _command: "/usr/bin/copr-cli")
    monkeypatch.setattr(CoprPublisher, "_resolve_config_path", lambda self: config_path)

    def fake_run(command, capture_output, text, check):
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("jetbrains_copr.copr.subprocess.run", fake_run)

    CoprPublisher().publish(project="cubewhy/jetbrains", srpm_path=srpm_path)

    assert captured["command"] == [
        "copr-cli",
        "--config",
        str(config_path),
        "build",
        "cubewhy/jetbrains",
        str(srpm_path),
    ]
