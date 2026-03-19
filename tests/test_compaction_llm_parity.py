from __future__ import annotations

from time import time

from ai import AssistantMessage, Model, Usage, text_block
from coding_agent.core.compaction import CompactionSettings, compact, prepare_compaction


def _assistant_message(text: str, timestamp: int) -> dict:
    return {
        "role": "assistant",
        "content": [text_block(text)],
        "api": "mock",
        "provider": "mock",
        "model": "echo",
        "usage": {"input": 10, "output": 5, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 15, "cost": {"total": 0}},
        "stopReason": "stop",
        "timestamp": timestamp,
    }


def test_prepare_compaction_detects_split_turn_boundary() -> None:
    entries = [
        {"id": "u1", "type": "message", "message": {"role": "user", "content": "task 1", "timestamp": 1}},
        {"id": "a1", "type": "message", "message": _assistant_message("done 1", 2)},
        {"id": "tr1", "type": "message", "message": {"role": "toolResult", "content": [text_block("ok")], "timestamp": 3}},
        {"id": "u2", "type": "message", "message": {"role": "user", "content": "task 2", "timestamp": 4}},
        {"id": "a2", "type": "message", "message": _assistant_message("done 2", 5)},
        {"id": "tr2", "type": "message", "message": {"role": "toolResult", "content": [text_block("ok")], "timestamp": 6}},
    ]

    preparation = prepare_compaction(entries, CompactionSettings(enabled=True, reserve_tokens=100, keep_recent_tokens=1))
    assert preparation is not None
    assert preparation["isSplitTurn"] is True
    assert preparation["firstKeptEntryId"] == "a2"
    assert preparation["turnPrefixMessages"]
    assert preparation["turnPrefixMessages"][0]["role"] == "user"


def test_compact_prefers_llm_summary_when_available() -> None:
    model = Model(provider="mock", id="echo", api="mock")
    preparation = {
        "firstKeptEntryId": "x1",
        "messagesToSummarize": [{"role": "user", "content": "hello", "timestamp": 1}],
        "turnPrefixMessages": [{"role": "user", "content": "prefix", "timestamp": 2}],
        "isSplitTurn": True,
        "tokensBefore": 200,
        "previousSummary": None,
        "details": {"readFiles": [], "modifiedFiles": []},
        "settings": CompactionSettings(),
    }
    calls = {"count": 0}

    def fake_complete(m, context, options):  # noqa: ANN001
        del context, options
        calls["count"] += 1
        text = "history summary" if calls["count"] == 1 else "prefix summary"
        return AssistantMessage(
            content=[text_block(text)],
            api=m.api,
            provider=m.provider,
            model=m.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time() * 1000),
        )

    result = compact(preparation, model, complete_fn=fake_complete)
    assert "history summary" in result["summary"]
    assert "prefix summary" in result["summary"]
    assert calls["count"] == 2


def test_compact_falls_back_when_llm_summary_fails() -> None:
    model = Model(provider="mock", id="echo", api="mock")
    preparation = {
        "firstKeptEntryId": "x1",
        "messagesToSummarize": [{"role": "user", "content": "hello", "timestamp": 1}],
        "turnPrefixMessages": [],
        "isSplitTurn": False,
        "tokensBefore": 200,
        "previousSummary": None,
        "details": {"readFiles": [], "modifiedFiles": []},
        "settings": CompactionSettings(),
    }

    def always_fail(m, context, options):  # noqa: ANN001
        del m, context, options
        raise RuntimeError("failed")

    result = compact(preparation, model, complete_fn=always_fail)
    assert result["summary"].startswith("## Goal")
