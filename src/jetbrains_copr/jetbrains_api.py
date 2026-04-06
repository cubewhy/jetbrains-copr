"""JetBrains releases API client."""

from __future__ import annotations

from datetime import date
from typing import Any

from jetbrains_copr.errors import ApiError
from jetbrains_copr.http import RetryingHttpClient
from jetbrains_copr.models import Architecture, DownloadInfo, ReleaseInfo


JETBRAINS_RELEASES_ENDPOINT = "https://data.services.jetbrains.com/products/releases"


class JetBrainsReleaseClient:
    """Client for JetBrains product release metadata."""

    def __init__(self, http_client: RetryingHttpClient) -> None:
        self._http_client = http_client

    def fetch_latest_release(self, product_code: str, *, release_type: str = "release") -> ReleaseInfo | None:
        payload = self._http_client.request_json(
            JETBRAINS_RELEASES_ENDPOINT,
            params={
                "code": product_code,
                "latest": "true",
                "type": release_type,
            },
        )
        return self.parse_latest_release(product_code, payload)

    @staticmethod
    def parse_latest_release(product_code: str, payload: object) -> ReleaseInfo | None:
        """Parse a single-product latest-release response."""

        if not isinstance(payload, dict):
            raise ApiError(f"JetBrains API response for {product_code} was not an object.")

        releases = payload.get(product_code)
        if releases is None:
            return None
        if not isinstance(releases, list):
            raise ApiError(f"JetBrains API response for {product_code} did not contain a release list.")
        if not releases:
            return None

        latest = releases[0]
        if not isinstance(latest, dict):
            raise ApiError(f"JetBrains API release entry for {product_code} was malformed.")

        version = latest.get("version")
        build = latest.get("build")
        raw_date = latest.get("date")
        if not isinstance(version, str) or not version.strip():
            raise ApiError(f"JetBrains API release for {product_code} did not include a valid version.")
        if not isinstance(build, str) or not build.strip():
            raise ApiError(f"JetBrains API release for {product_code} did not include a valid build number.")
        if not isinstance(raw_date, str) or not raw_date.strip():
            raise ApiError(f"JetBrains API release for {product_code} did not include a valid date.")

        try:
            release_date = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ApiError(f"JetBrains API date for {product_code} was not ISO-8601: {raw_date}") from exc

        downloads_payload = latest.get("downloads")
        downloads: dict[Architecture, DownloadInfo] = {}
        if isinstance(downloads_payload, dict):
            for architecture in (Architecture.X86_64, Architecture.AARCH64):
                parsed = JetBrainsReleaseClient._parse_download(downloads_payload, architecture)
                if parsed is not None:
                    downloads[architecture] = parsed

        notes_link = latest.get("notesLink")
        notes_url = notes_link if isinstance(notes_link, str) and notes_link.strip() else None

        return ReleaseInfo(
            code=product_code,
            version=version.strip(),
            build=build.strip(),
            release_date=release_date,
            notes_url=notes_url,
            downloads=downloads,
        )

    @staticmethod
    def _parse_download(downloads_payload: dict[str, Any], architecture: Architecture) -> DownloadInfo | None:
        entry = downloads_payload.get(architecture.api_key)
        if not isinstance(entry, dict):
            return None

        link = entry.get("link")
        if not isinstance(link, str) or not link.strip():
            return None

        checksum_link = entry.get("checksumLink")
        size = entry.get("size")
        normalized_checksum_link = checksum_link.strip() if isinstance(checksum_link, str) and checksum_link.strip() else None
        normalized_size = size if isinstance(size, int) else None

        return DownloadInfo(
            link=link.strip(),
            checksum_link=normalized_checksum_link,
            size=normalized_size,
        )
