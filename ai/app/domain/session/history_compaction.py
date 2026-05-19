from __future__ import annotations


def compact_conversation_history(
    history: list[dict[str, str]],
    *,
    protect_tail_n: int = 12,
    max_messages: int = 32,
) -> list[dict[str, str]]:
    """긴 공개 대화 history를 active context용 메시지 배열로 압축한다.

    원본 row는 삭제하거나 수정하지 않는다. 압축 결과는 모델 입력에 쓰는 파생 배열이며,
    감사와 검색의 기준은 별도 영속 메시지에 남아야 한다.
    """

    if max_messages <= 0:
        return []

    normalized = _copy_visible_messages(history)
    if len(normalized) <= max_messages:
        return normalized

    tail_count = max(0, protect_tail_n)

    protected_tail_start = max(len(normalized) - tail_count, 0)
    latest_user_index = _latest_user_index(normalized)
    if latest_user_index is not None:
        protected_tail_start = min(protected_tail_start, latest_user_index)

    tail = normalized[protected_tail_start:]
    available_tail_count = max_messages - 1
    if available_tail_count <= 0:
        tail = []
    elif len(tail) > available_tail_count:
        tail = tail[-available_tail_count:]

    middle = normalized[: len(normalized) - len(tail)]
    summary = _build_summary_message(middle)
    compacted = [summary, *tail]

    # 압축이 길이를 줄이지 못하면 요약 메시지만 누적되어 다음 턴의 context 예산을 더 악화시킨다.
    if len(compacted) >= len(normalized):
        return normalized

    return compacted[:max_messages]


def _copy_visible_messages(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """system 역할은 provider prefix 전용이므로 대화 압축 결과에 남기지 않는다."""

    copied: list[dict[str, str]] = []
    for item in history:
        role = str(item.get("role") or "").strip()
        if role == "system":
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        copied.append({"role": role, "content": content})
    return copied


def _latest_user_index(history: list[dict[str, str]]) -> int | None:
    for index in range(len(history) - 1, -1, -1):
        if history[index]["role"] == "user":
            return index
    return None


def _build_summary_message(messages: list[dict[str, str]]) -> dict[str, str]:
    count = len(messages)
    preview = _summary_preview(messages)
    content = f"이전 대화 요약: 오래된 대화 {count}개를 압축했습니다."
    if preview:
        content = f"{content} 주요 맥락: {preview}"
    return {"role": "assistant", "content": content}


def _summary_preview(messages: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for item in messages[:3]:
        content = item["content"].replace("\n", " ").strip()
        if len(content) > 80:
            content = f"{content[:80].rstrip()}..."
        if content:
            parts.append(content)
    return " / ".join(parts)
