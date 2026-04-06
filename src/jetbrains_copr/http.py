"""HTTP helpers with retries and sensible defaults."""

from __future__ import annotations

from pathlib import Path
import time

import httpx

from jetbrains_copr.errors import ApiError


class RetryingHttpClient:
    """Small wrapper around httpx with limited retries."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        retries: int = 3,
        backoff_seconds: float = 1.0,
        user_agent: str = "jetbrains-copr/0.1.0",
    ) -> None:
        self._retries = retries
        self._backoff_seconds = backoff_seconds
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        )

    def close(self) -> None:
        """Close the underlying client."""

        self._client.close()

    def __enter__(self) -> "RetryingHttpClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def request_json(self, url: str, *, params: dict[str, str] | None = None) -> object:
        response = self._request("GET", url, params=params)
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError(f"Response from {url} was not valid JSON.") from exc

    def request_text(self, url: str) -> str:
        response = self._request("GET", url)
        return response.text

    def download_file(self, url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp_destination = destination.with_suffix(destination.suffix + ".part")
        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                with self._client.stream("GET", url) as response:
                    if response.status_code in {408, 429} or 500 <= response.status_code < 600:
                        if attempt == self._retries:
                            response.raise_for_status()
                        time.sleep(self._backoff_seconds * attempt)
                        continue
                    response.raise_for_status()
                    with tmp_destination.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
                tmp_destination.replace(destination)
                return destination
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                retriable = True
                if isinstance(exc, httpx.HTTPStatusError):
                    status_code = exc.response.status_code
                    retriable = status_code in {408, 429} or 500 <= status_code < 600
                tmp_destination.unlink(missing_ok=True)
                if attempt == self._retries or not retriable:
                    break
                time.sleep(self._backoff_seconds * attempt)

        raise ApiError(f"Download from {url} failed after {self._retries} attempts: {last_error}") from last_error

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                response = self._client.request(method, url, params=params)
                if response.status_code in {408, 429} or 500 <= response.status_code < 600:
                    if attempt == self._retries:
                        response.raise_for_status()
                    time.sleep(self._backoff_seconds * attempt)
                    continue
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                retriable = True
                if isinstance(exc, httpx.HTTPStatusError):
                    status_code = exc.response.status_code
                    retriable = status_code in {408, 429} or 500 <= status_code < 600
                if attempt == self._retries or not retriable:
                    break
                time.sleep(self._backoff_seconds * attempt)

        raise ApiError(f"Request to {url} failed after {self._retries} attempts: {last_error}") from last_error
