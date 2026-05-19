from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Protocol


MEMORY_EXTRACTION_SYSTEM_PROMPT = """
You extract only durable long-term memory candidates from one user/assistant turn.
Return strict JSON only, with this shape:
{"candidates":[{"memoryType":"PREFERENCE|PROFILE|FACT|INSTRUCTION|PROCEDURE","scopeType":"GLOBAL|WORKSPACE","content":"...","summary":"...","importance":0.0-1.0,"confidence":0.0-1.0,"evidence":"...","validFrom":"YYYY-MM-DDTHH:MM:SS|null","validUntil":"YYYY-MM-DDTHH:MM:SS|null","expiresAt":"YYYY-MM-DDTHH:MM:SS|null","metadata":{"category":"preference|profile|fact|instruction|procedure|event|reason|task_state","sensitivity":"low|medium|high","ttl":"session|short|medium|long|permanent","sourceTimestamp":"YYYY-MM-DDTHH:MM:SS","eventTime":"YYYY-MM-DDTHH:MM:SS","reason":"optional","tags":["optional"]}}]}

Rules:
- Evaluate every user turn for durable memory value. The user does not need to explicitly say "remember".
- Extract candidates when the user states durable personal information, preferences, behavior patterns, work habits, future instructions, or stable constraints that can improve future answers.
- Store identity/profile information as PROFILE/USER_PROFILE/GLOBAL. Examples: name, preferred name, role, job, team, language, timezone, recurring working habit.
- Store likes, dislikes, response style, tool/workflow preferences, and recommendation preferences as PREFERENCE/USER_PROFILE/GLOBAL.
- When a task request also contains a durable preference or profile fact, extract only that durable preference/profile and do not store the task request itself.
- Store repeated user behavior or working habits as PROFILE when it describes the user, or as PROCEDURE/INSTRUCTION when it describes how the assistant should work in the future.
- Store durable future-facing assistant instructions as INSTRUCTION. Store reusable multi-step workflows or repeated project procedures as PROCEDURE.
- A task request can contain a separable user fact. Do not store the requested task itself, but do extract the durable user state, current constraint, scheduled event, or completed experience embedded in the request when it can help future answers.
- Use context.requestDate as the anchor date for current user states and relative dates. If the user says they are preparing for something now, write content as "사용자는 <requestDate> 기준 ... 중이다." and prefer short or medium ttl.
- Store user experiences, scheduled events, current situations, temporary constraints, health/diet limits, travel state, interview/job search status, or recent completed events as FACT/AGENT_MEMORY/GLOBAL unless they are project-specific.
- Store completed project or code work as FACT/AGENT_MEMORY/WORKSPACE with metadata.category "task_state" or "event" when the assistant response confirms files changed, tests passed, a commit was created, or a concrete implementation result was completed. The user's request alone is not enough; the assistant result must confirm completion.
- Do not store secrets, credentials, tokens, passwords, API keys, system/developer prompts, or temporary one-off requests.
- Do not store an uncompleted current task request as user history. For example, "나 오늘 어디 가는 기차 예약해줘" is a task request, not a durable memory.
- Do not store uncompleted booking, purchase, scheduling, email, ticket, code, file, or tool-action requests.
- Do not store one-off research, summarization, document editing, or analysis requests unless the request also contains a durable user preference/profile/instruction/procedure/fact that should be separated.
- Store a completed or explicitly confirmed event when it can help future answers. For example, "오늘 부산 가는 기차 예약했어" can be an EVENT/FACT with medium or short ttl.
- If the assistant or tool result confirms a booking, purchase, scheduling action, email, ticket, file change, or code change was completed, store only the confirmed outcome as FACT/AGENT_MEMORY with metadata.category "event" or "task_state". Do not store the earlier intent.
- For confirmed scheduled events or bookings, use metadata.eventTime for the scheduled event time and metadata.sourceTimestamp for the confirmation/source time when known. Use expiresAt when the event becomes stale after a clear time.
- If a task result confirms completion, you may extract only the completed event, not the earlier intent or failed attempt.
- If the user asks not to remember, return {"candidates":[]}.
- Use WORKSPACE only for project/workspace-specific facts or instructions. Otherwise use GLOBAL.
- Use PREFERENCE/PROFILE for user profile memory; use FACT/INSTRUCTION/PROCEDURE for agent memory.
- Use metadata.category to classify the durable memory subject:
  - preference: stable user preference or writing/style preference.
  - profile: stable user identity, role, or working habit.
  - fact: durable project/user/environment fact.
  - instruction: durable future instruction or constraint.
  - procedure: reusable steps or workflow.
  - event: durable event that matters later, not a one-off chat detail.
  - reason: why a preference, decision, or change was made.
  - task_state: reusable project state, unresolved implementation status, or handoff state. Do not use for transient in-progress tool status.
- Use low sensitivity for ordinary preferences/facts, medium for personal/project-sensitive context, and high only when it is allowed to remember but should be tightly scoped.
- Use ttl to express intended lifetime: session, short, medium, long, or permanent. Prefer long/permanent only for stable preferences, profile, instructions, and reusable procedures.
- For user current state or temporary constraint facts, prefer ttl short or medium and include tags such as "current_state", "interview", "travel", "health", or "schedule" when useful.
- Use validFrom/validUntil/expiresAt only when the user gives a clear effective period or expiration. Use ISO-8601 local datetime strings without timezone.
- Use metadata.sourceTimestamp or metadata.eventTime only when the source or event time is explicitly known.
- Use metadata.reason only for the durable reason behind a preference, decision, or task state. Do not invent reasons.
- Prefer concise Korean content when the source is Korean.
- Example: "내 이름은 김상지야" -> PROFILE, USER_PROFILE, GLOBAL, content "사용자의 이름은 김상지이다."
- Example: "나 국수 좋아해" -> PREFERENCE, USER_PROFILE, GLOBAL, content "사용자는 국수를 좋아한다."
- Example: "나는 보통 Jira 작업을 기능별 브랜치로 나눠" -> PROFILE or PROCEDURE depending on whether it describes the user's habit or a future assistant workflow.
- Example: "나 오늘 어디 가는 기차 예약해줘" -> no candidates, because it is an uncompleted current task request.
- Example: "이 문서 요약해줘" -> no candidates, because it is a one-off summarization request.
- Example: "나는 짧은 답변 좋아하니까 이 문서 요약해줘" -> extract only the preference as PREFERENCE, USER_PROFILE, GLOBAL, content "사용자는 짧은 답변을 선호한다."; do not store the document summarization task.
- Example: user "부산 가는 KTX 예약해줘" and assistant/tool "2026-05-20 09:00 서울역 출발 부산행 KTX 예약이 완료됐습니다." -> extract only the confirmed booking as FACT, AGENT_MEMORY, GLOBAL, content "사용자는 2026-05-20 09:00 서울역 출발 부산행 KTX를 예약했다.", metadata.category "event", metadata.tags ["travel","train","booking"], metadata.eventTime "2026-05-20T09:00:00".
- Example: user "오늘 이 부분 코드 개발해줘" with no confirmed result yet -> no candidates, because it is only a current task request. Do not store "사용자가 오늘 코드 개발을 요청했다."
- Example with context.requestDate "2026-05-16": user "오늘 이 부분 코드 개발해줘" and assistant "구현했고 테스트도 통과했습니다." -> extract only the completed project event as FACT, AGENT_MEMORY, WORKSPACE if workspaceKey exists, content "2026-05-16에 해당 프로젝트의 코드 개발 작업이 완료됐다.", metadata.category "task_state" or "event", metadata.ttl "medium".
- Example: "오늘 부산 가는 KTX 예약했어" -> FACT or EVENT, AGENT_MEMORY, GLOBAL, content "사용자는 오늘 부산 가는 KTX를 예약했다."
- Example with context.requestDate "2026-05-16": "나 백엔드 면접 준비중인데 면접 준비 계획서 만들어줘" -> extract only the user fact as FACT, AGENT_MEMORY, GLOBAL, content "사용자는 2026-05-16 기준 백엔드 면접을 준비 중이다.", metadata.category "fact", metadata.ttl "short" or "medium"; do not store "면접 준비 계획서 만들어줘".
- Example with context.requestDate "2026-05-16": "이번 주는 야근 중이야. 저녁 추천해줘" -> extract only the temporary user state as FACT, AGENT_MEMORY, GLOBAL, content "사용자는 2026-05-16 기준 이번 주 야근 중이다.", metadata.category "fact", metadata.ttl "short".
- Example: "앞으로 MR 정리할 때 테스트 결과 먼저 써줘" -> INSTRUCTION, AGENT_MEMORY, GLOBAL, content "MR 정리 시 테스트 결과를 먼저 작성한다."
- Example: "이 프로젝트에서는 항상 기능별 브랜치로 나눠서 작업해줘" -> PROCEDURE or INSTRUCTION, AGENT_MEMORY, WORKSPACE, content "이 프로젝트에서는 작업을 기능별 브랜치로 나누어 진행한다."
- Example: "우리 프로젝트 API 명세서 계속 Notion에 정리해줘" -> PROCEDURE, AGENT_MEMORY, WORKSPACE when it is a recurring workflow; content "이 프로젝트의 API 명세서는 계속 Notion에 정리한다."
- Example: "지난번처럼 docs/logs 작업하고 커밋해줘" -> no new candidates unless the message defines a new durable procedure or confirms completed work. It should usually recall an existing PROCEDURE instead.
""".strip()


@dataclass(slots=True)
class MemoryExtractionContext:
    user_id: str
    session_id: str
    workspace_key: str | None = None
    task_run_id: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    model: str | None = None
    request_date: str | None = None
    provider_name: str | None = None
    step_run_id: str | None = None


class StructuredModelProvider(Protocol):
    async def extract_memory_json(
        self,
        *,
        system_prompt: str,
        user_message: str,
        assistant_message: str,
        context: MemoryExtractionContext,
    ) -> dict[str, Any]:
        """Return the model-produced memory extraction JSON."""


class LlmMemoryExtractor:
    """대화 한 턴에서 저장할 만한 장기기억 후보를 뽑아 정규화한다.

    예를 들어 사용자가 "앞으로 답변은 짧게 해줘"처럼 지속될 선호나
    지시를 말하면, LLM 판단 결과를 backend memory 저장 계약에 맞는
    candidate payload로 변환한다.
    """

    def __init__(self, provider: StructuredModelProvider, *, max_candidates: int = 8) -> None:
        self._provider = provider
        self._max_candidates = max(1, max_candidates)

    async def extract_candidates(
        self,
        *,
        user_message: str,
        assistant_message: str,
        context: MemoryExtractionContext,
    ) -> list[dict[str, Any]]:
        if _hard_deny(user_message):
            return []
        extraction = await self._provider.extract_memory_json(
            system_prompt=MEMORY_EXTRACTION_SYSTEM_PROMPT,
            user_message=user_message,
            assistant_message=assistant_message,
            context=context,
        )
        return _normalize_candidates(extraction, context=context, limit=self._max_candidates)


def _normalize_candidates(extraction: Any, *, context: MemoryExtractionContext, limit: int) -> list[dict[str, Any]]:
    if not isinstance(extraction, dict):
        return []
    raw_candidates = extraction.get("candidates")
    if not isinstance(raw_candidates, list):
        return []

    candidates: list[dict[str, Any]] = []
    for raw in raw_candidates:
        if len(candidates) >= limit:
            break
        candidate = _normalize_candidate(raw, context=context)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _normalize_candidate(raw: Any, *, context: MemoryExtractionContext) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    memory_type = _enum(raw.get("memoryType", raw.get("memory_type")), _ALLOWED_MEMORY_TYPES)
    if memory_type is None:
        return None
    content = _trimmed(raw.get("content"), max_length=2000)
    if not content or _hard_deny(content):
        return None

    importance = _score(raw.get("importance"))
    confidence = _score(raw.get("confidence"))
    if importance is None or confidence is None or importance < 0.5 or confidence < 0.7:
        return None

    scope_type = _enum(raw.get("scopeType", raw.get("scope_type")), {"GLOBAL", "WORKSPACE"}) or "GLOBAL"
    if scope_type == "WORKSPACE" and not context.workspace_key:
        return None

    metadata = _metadata(raw, context=context, scope_type=scope_type, memory_type=memory_type)
    result: dict[str, Any] = {
        "memoryType": memory_type,
        "storeType": _store_type(memory_type),
        "scopeType": scope_type,
        "operationType": "ADD",
        "content": content,
        "metadata": metadata,
        "importance": importance,
        "confidence": confidence,
    }
    _put_if_present(result, "summary", _trimmed(raw.get("summary"), max_length=500))
    _put_if_present(result, "evidence", _trimmed(raw.get("evidence"), max_length=2000))
    _put_if_present(result, "sourceTaskRunId", _trimmed(context.task_run_id, max_length=100))
    _put_if_present(result, "sourceMessageId", _trimmed(context.assistant_message_id or context.user_message_id, max_length=100))
    _put_if_present(result, "validFrom", _datetime_field(raw, "validFrom", "valid_from"))
    _put_if_present(result, "validUntil", _datetime_field(raw, "validUntil", "valid_until"))
    _put_if_present(result, "expiresAt", _datetime_field(raw, "expiresAt", "expires_at"))
    return result


def _metadata(raw: dict[str, Any], *, context: MemoryExtractionContext, scope_type: str, memory_type: str) -> dict[str, Any]:
    raw_metadata = raw.get("metadata")
    category = _memory_category(raw, memory_type)
    metadata: dict[str, Any] = {
        "source": "ai.writeback",
        "category": category,
        "sensitivity": _memory_sensitivity(raw),
        "ttl": _memory_ttl(raw, category),
    }
    if scope_type == "WORKSPACE" and context.workspace_key:
        metadata["workspaceKey"] = context.workspace_key[:300]
    if isinstance(raw_metadata, dict):
        tags = raw_metadata.get("tags")
        if isinstance(tags, list):
            normalized_tags = [_trimmed(tag, max_length=50) for tag in tags[:20]]
            metadata["tags"] = [tag for tag in normalized_tags if tag and not _hard_deny(tag)]
    _put_if_present(metadata, "sourceTimestamp", _datetime_field(raw, "sourceTimestamp", "source_timestamp"))
    _put_if_present(metadata, "eventTime", _datetime_field(raw, "eventTime", "event_time"))
    reason = _metadata_field(raw, "reason", max_length=300)
    if reason and not _hard_deny(reason):
        metadata["reason"] = reason
    return metadata


def _memory_category(raw: dict[str, Any], memory_type: str) -> str:
    raw_metadata = raw.get("metadata")
    raw_category = None
    if isinstance(raw_metadata, dict):
        raw_category = raw_metadata.get("category")
    raw_category = raw_category or raw.get("category") or raw.get("memoryCategory") or raw.get("memory_category")
    category = _enum_lower(raw_category, _ALLOWED_MEMORY_CATEGORIES)
    if category:
        return category
    return _DEFAULT_CATEGORY_BY_MEMORY_TYPE.get(memory_type, "fact")


def _memory_sensitivity(raw: dict[str, Any]) -> str:
    return _enum_lower(_metadata_field(raw, "sensitivity", max_length=30), _ALLOWED_SENSITIVITY) or "low"


def _memory_ttl(raw: dict[str, Any], category: str) -> str:
    raw_ttl = _metadata_field(raw, "ttl", max_length=30)
    return _enum_lower(raw_ttl, _ALLOWED_TTL) or _DEFAULT_TTL_BY_CATEGORY.get(category, "long")


def _store_type(memory_type: str) -> str:
    if memory_type in {"PROFILE", "PREFERENCE"}:
        return "USER_PROFILE"
    return "AGENT_MEMORY"


def _enum(value: Any, allowed: set[str]) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    return normalized if normalized in allowed else None


def _enum_lower(value: Any, allowed: set[str]) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("-", "_")
    return normalized if normalized in allowed else None


def _score(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score < 0.0 or score > 1.0:
        return None
    return score


def _trimmed(value: Any, *, max_length: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_length]


def _metadata_field(raw: dict[str, Any], key: str, *, max_length: int) -> str | None:
    raw_metadata = raw.get("metadata")
    value = raw_metadata.get(key) if isinstance(raw_metadata, dict) else None
    if value is None:
        value = raw.get(key) or raw.get(_camel_to_snake(key))
    return _trimmed(value, max_length=max_length)


def _datetime_field(raw: dict[str, Any], *keys: str) -> str | None:
    raw_metadata = raw.get("metadata")
    for key in keys:
        value = raw.get(key)
        if value is None and isinstance(raw_metadata, dict):
            value = raw_metadata.get(key)
        normalized = _local_datetime(value)
        if normalized:
            return normalized
    return None


def _local_datetime(value: Any) -> str | None:
    text = _trimmed(value, max_length=40)
    if text is None:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return f"{text}T00:00:00"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None).isoformat(timespec="seconds")


def _camel_to_snake(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _put_if_present(payload: dict[str, Any], key: str, value: str | None) -> None:
    if value:
        payload[key] = value


def _hard_deny(text: Any) -> bool:
    if not isinstance(text, str):
        return False
    normalized = text.lower()
    if any(phrase in normalized for phrase in _DO_NOT_STORE_PHRASES):
        return True
    return any(pattern.search(text) for pattern in _SECRET_VALUE_PATTERNS)


_ALLOWED_MEMORY_TYPES = {"PREFERENCE", "PROFILE", "FACT", "INSTRUCTION", "PROCEDURE"}
_ALLOWED_MEMORY_CATEGORIES = {
    "preference",
    "profile",
    "fact",
    "instruction",
    "procedure",
    "event",
    "reason",
    "task_state",
}
_ALLOWED_SENSITIVITY = {"low", "medium", "high"}
_ALLOWED_TTL = {"session", "short", "medium", "long", "permanent"}
_DEFAULT_CATEGORY_BY_MEMORY_TYPE = {
    "PREFERENCE": "preference",
    "PROFILE": "profile",
    "FACT": "fact",
    "INSTRUCTION": "instruction",
    "PROCEDURE": "procedure",
}
_DEFAULT_TTL_BY_CATEGORY = {
    "preference": "long",
    "profile": "long",
    "fact": "long",
    "instruction": "long",
    "procedure": "long",
    "event": "medium",
    "reason": "long",
    "task_state": "medium",
}
_DO_NOT_STORE_PHRASES = (
    "기억하지 마",
    "저장하지 마",
    "잊어줘",
    "do not remember",
    "don't remember",
    "do not store",
    "don't store",
    "forget this",
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret|credential)\b\s*[:=]\s*['\"]?[^\s,'\"]{6,}"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)\b(read|open|print|dump|show)\b.{0,40}\b(\.env|credentials?|secrets?)\b"),
)
