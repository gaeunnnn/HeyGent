from __future__ import annotations

from app.domain.session.conversation_history import build_conversation_history
from app.domain.session.history_compaction import compact_conversation_history
from app.domain.session.session_runtime_state import get_system_prompt_snapshot


def test_build_conversation_history_keeps_user_assistant_turns_only():
    rows = [
        {"id": 1, "role": "user", "content": "강남역에서 지갑 잃어버렸어", "metadata": {}},
        {"id": 2, "role": "assistant", "content": "공식 조회 경로를 확인했습니다.", "metadata": {}},
        {"id": 3, "role": "tool", "content": "internal", "metadata": {"tool_name": "http_get"}},
        {"id": 4, "role": "user", "content": "ㄴㄴ 분실물 찾은 거", "metadata": {}},
    ]

    history = build_conversation_history(rows, max_messages=20)

    assert history == [
        {"role": "user", "content": "강남역에서 지갑 잃어버렸어"},
        {"role": "assistant", "content": "공식 조회 경로를 확인했습니다."},
        {"role": "user", "content": "ㄴㄴ 분실물 찾은 거"},
    ]


def test_build_conversation_history_truncates_and_tail_limits_non_empty_turns_only():
    rows = [
        {"role": "system", "content": "내부 지시"},
        {"role": "user", "content": "   "},
        {"role": "assistant", "content": "a" * 8},
        {"role": "internal", "content": "숨김"},
        {"role": "user", "content": "짧은 요청"},
        {"role": "assistant", "content": "마지막 답변"},
    ]

    history = build_conversation_history(rows, max_messages=2, max_chars_per_message=20)

    assert history == [
        {"role": "user", "content": "짧은 요청"},
        {"role": "assistant", "content": "마지막 답변"},
    ]


def test_build_conversation_history_truncates_long_content():
    rows = [{"role": "assistant", "content": "가나다라마"}]

    history = build_conversation_history(rows, max_chars_per_message=3)

    assert history == [
        {
            "role": "assistant",
            "content": "가나다\n[이전 메시지가 길어 일부를 생략했습니다.]",
        }
    ]


def test_compaction_keeps_tail_latest_user_and_uses_synthetic_summary():
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"메시지 {i}"}
        for i in range(40)
    ]

    compacted = compact_conversation_history(
        history,
        protect_tail_n=8,
        max_messages=16,
    )

    assert compacted[0]["role"] == "assistant"
    assert "이전 대화 요약" in compacted[0]["content"]
    assert "메시지 0" not in [item["content"] for item in compacted]
    assert compacted[-1]["content"] == "메시지 39"
    assert len(compacted) <= 16
    assert all(item["role"] != "system" for item in compacted)


def test_compaction_default_does_not_pin_oldest_head_request():
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"메시지 {i}"}
        for i in range(40)
    ]

    compacted = compact_conversation_history(
        history,
        protect_tail_n=8,
        max_messages=12,
    )

    assert compacted[0]["role"] == "assistant"
    assert "이전 대화 요약" in compacted[0]["content"]
    assert "메시지 0" not in [item["content"] for item in compacted]
    assert compacted[-1]["content"] == "메시지 39"
    assert len(compacted) <= 12


def test_compaction_does_not_mutate_original_or_compact_when_not_helpful():
    history = [
        {"role": "user", "content": "처음"},
        {"role": "assistant", "content": "응답"},
        {"role": "user", "content": "마지막"},
    ]
    original = [item.copy() for item in history]

    compacted = compact_conversation_history(history, max_messages=3)

    assert compacted == original
    assert history == original
    assert compacted is not history


def test_system_prompt_snapshot_reuses_session_metadata_value():
    session = {"metadata": {"system_prompt_snapshot": "고정 system prompt"}}

    assert get_system_prompt_snapshot(session) == "고정 system prompt"
    assert get_system_prompt_snapshot({"metadata": {"system_prompt": "저장된 system prompt"}}) == "저장된 system prompt"
    assert get_system_prompt_snapshot({"metadata": {}}) == ""
