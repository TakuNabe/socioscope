from typing import Protocol


class FetchError(Exception):
    """Raised by a SourceFetcher when the remote source cannot be read."""


class SourceFetcher(Protocol):
    def fetch(self, url: str) -> bytes:
        """Return the raw bytes at *url*. Raise FetchError on failure."""
        ...
