"""ClaudeStructurer tests. The Anthropic client is replaced by a tiny stub; no network."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from socioscope_core.adapters.claude_structurer import ClaudeStructurer, JsonlLlmCache
from socioscope_core.ports.structurer import StructurerUnavailableError


class Share(BaseModel):
    year: int
    top1_share: float
    source_quote: str


class _Resp:
    def __init__(self, parsed: BaseModel | None, stop_reason: str = "end_turn") -> None:
        self.parsed_output = parsed
        self.stop_reason = stop_reason


class _Messages:
    def __init__(self, responses: list[_Resp]) -> None:
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def parse(self, **kwargs: Any) -> _Resp:
        self.calls.append(kwargs)
        return self._responses.pop(0)


class StubClient:
    def __init__(self, responses: list[_Resp]) -> None:
        self.messages = _Messages(responses)


def make(tmp_path: Path, client: StubClient | None, api_key: str | None = "k") -> ClaudeStructurer:
    return ClaudeStructurer(
        cache=JsonlLlmCache(tmp_path / "llm_cache"),
        model="claude-opus-5-5",
        api_key=api_key,
        now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
        client=client,  # type: ignore[arg-type]
    )


def test_first_call_hits_api_and_second_call_replays_from_cache(tmp_path: Path) -> None:
    expected = Share(year=1990, top1_share=0.12, source_quote="top 1% held 12%")
    client = StubClient([_Resp(expected)])
    s = make(tmp_path, client)

    out1 = s.structure("text", Share, schema_version="1")
    out2 = s.structure("text", Share, schema_version="1")

    assert out1 == out2 == expected
    assert len(client.messages.calls) == 1
    assert client.messages.calls[0]["model"] == "claude-opus-5-5"
    assert client.messages.calls[0]["output_format"] is Share
    lines = (tmp_path / "llm_cache" / "Share.jsonl").read_text().splitlines()
    assert len(lines) == 1 and '"schema_version":"1"' in lines[0]


def test_cache_is_replayable_without_credentials(tmp_path: Path) -> None:
    expected = Share(year=1990, top1_share=0.12, source_quote="q")
    make(tmp_path, StubClient([_Resp(expected)])).structure("text", Share, schema_version="1")
    offline = make(tmp_path, client=None, api_key=None)
    assert offline.structure("text", Share, schema_version="1") == expected


def test_without_key_and_cache_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(StructurerUnavailableError, match="ANTHROPIC_API_KEY"):
        make(tmp_path, client=None, api_key=None).structure("text", Share, schema_version="1")


def test_refusal_is_not_cached(tmp_path: Path) -> None:
    s = make(tmp_path, StubClient([_Resp(None, stop_reason="refusal")]))
    with pytest.raises(StructurerUnavailableError, match="refusal"):
        s.structure("text", Share, schema_version="1")
    assert not (tmp_path / "llm_cache" / "Share.jsonl").exists()


def test_repr_does_not_leak_key(tmp_path: Path) -> None:
    assert "secret" not in repr(make(tmp_path, StubClient([]), api_key="secret"))
