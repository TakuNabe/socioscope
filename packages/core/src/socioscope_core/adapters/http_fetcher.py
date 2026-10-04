import httpx

from socioscope_core.ports.fetcher import FetchError


class HttpxFetcher:
    """SourceFetcher over HTTP(S). No credentials; public sources only."""

    def __init__(self, *, user_agent: str, timeout_s: float = 60.0, retries: int = 2) -> None:
        self._client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=timeout_s,
            follow_redirects=True,
            transport=httpx.HTTPTransport(retries=retries),
        )

    def fetch(self, url: str) -> bytes:
        if not url.startswith(("https://", "http://")):
            msg = f"unsupported URL scheme: {url}"
            raise FetchError(msg)
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            msg = f"fetch failed: {url} ({type(e).__name__})"
            raise FetchError(msg) from e
        return resp.content
