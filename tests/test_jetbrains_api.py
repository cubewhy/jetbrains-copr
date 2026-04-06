from __future__ import annotations

import pytest

from jetbrains_copr.errors import ApiError
from jetbrains_copr.jetbrains_api import JetBrainsReleaseClient
from jetbrains_copr.models import Architecture


def test_parse_latest_release_with_both_architectures():
    release = JetBrainsReleaseClient.parse_latest_release(
        "IIU",
        {
            "IIU": [
                {
                    "date": "2026-03-25",
                    "type": "release",
                    "downloads": {
                        "linux": {
                            "link": "https://download.jetbrains.com/idea/idea-2026.1.tar.gz",
                            "size": 1565208103,
                            "checksumLink": "https://download.jetbrains.com/idea/idea-2026.1.tar.gz.sha256",
                        },
                        "linuxARM64": {
                            "link": "https://download.jetbrains.com/idea/idea-2026.1-aarch64.tar.gz",
                            "size": 1560324895,
                            "checksumLink": "https://download.jetbrains.com/idea/idea-2026.1-aarch64.tar.gz.sha256",
                        },
                    },
                    "version": "2026.1",
                    "build": "261.22158.277",
                    "notesLink": "https://youtrack.jetbrains.com/articles/IDEA-A-2100662652",
                }
            ]
        },
    )

    assert release is not None
    assert release.version == "2026.1"
    assert release.build == "261.22158.277"
    assert release.release_date.isoformat() == "2026-03-25"
    assert release.available_architectures() == [Architecture.X86_64, Architecture.AARCH64]
    assert release.downloads[Architecture.AARCH64].checksum_link.endswith(".sha256")


def test_parse_latest_release_skips_missing_architecture_downloads():
    release = JetBrainsReleaseClient.parse_latest_release(
        "GO",
        {
            "GO": [
                {
                    "date": "2026-03-25",
                    "downloads": {
                        "linux": {
                            "link": "https://download.jetbrains.com/go/goland-2026.1.tar.gz",
                        }
                    },
                    "version": "2026.1",
                    "build": "261.1",
                }
            ]
        },
    )

    assert release is not None
    assert release.available_architectures() == [Architecture.X86_64]
    assert Architecture.AARCH64 not in release.downloads


def test_parse_latest_release_rejects_missing_build():
    with pytest.raises(ApiError, match="build number"):
        JetBrainsReleaseClient.parse_latest_release(
            "WS",
            {
                "WS": [
                    {
                        "date": "2026-03-25",
                        "downloads": {
                            "linux": {
                                "link": "https://download.jetbrains.com/webstorm/webstorm-2026.1.tar.gz",
                            }
                        },
                        "version": "2026.1",
                    }
                ]
            },
        )
