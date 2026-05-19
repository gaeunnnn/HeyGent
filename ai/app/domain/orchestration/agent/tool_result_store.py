from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Any

from app.core.utils.ids import new_id


RAW_REF_PREFIX = "tool-result://"
DEFAULT_RETENTION_DAYS = 7
DEFAULT_READ_LIMIT_CHARS = 8_000
MAX_READ_LIMIT_CHARS = 12_000


def store_raw_tool_result(
    *,
    tool_name: str,
    tool_call_id: str,
    task_run_id: str | None,
    result: Any,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, Any]:
    """큰 도구 결과 원문을 모델 transcript/DB payload 밖의 파일 저장소에 보관한다."""

    artifact_id = new_id("tool_result_raw")
    created_at = _now()
    expires_at = created_at + timedelta(days=max(1, int(retention_days or DEFAULT_RETENTION_DAYS)))
    raw_text = _stable_json(result)
    payload = {
        "id": artifact_id,
        "raw_ref": f"{RAW_REF_PREFIX}{artifact_id}",
        "tool_name": str(tool_name or ""),
        "tool_call_id": str(tool_call_id or ""),
        "task_run_id": str(task_run_id or "") or None,
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "raw_chars": len(raw_text),
        "result": result,
    }
    path = _artifact_path(artifact_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {
        "raw_ref": payload["raw_ref"],
        "raw_chars": payload["raw_chars"],
        "expires_at": payload["expires_at"],
    }


def read_raw_tool_result_chunk(raw_ref: str, *, offset: int = 0, limit: int = DEFAULT_READ_LIMIT_CHARS) -> dict[str, Any]:
    artifact_id = _parse_raw_ref(raw_ref)
    if artifact_id is None:
        return {
            "ok": False,
            "error": {
                "code": "invalid_raw_ref",
                "message": "raw_ref must use the tool-result:// prefix.",
            },
        }
    path = _artifact_path(artifact_id)
    if not path.exists():
        return {
            "ok": False,
            "error": {
                "code": "raw_result_not_found",
                "message": "The referenced raw tool result is not available.",
            },
        }

    payload = json.loads(path.read_text(encoding="utf-8"))
    expires_at = _parse_datetime(payload.get("expires_at"))
    if expires_at is not None and expires_at < _now():
        return {
            "ok": False,
            "error": {
                "code": "raw_result_expired",
                "message": "The referenced raw tool result has expired.",
            },
        }

    raw_text = _stable_json(payload.get("result"))
    normalized_offset = max(0, int(offset or 0))
    normalized_limit = max(1, min(int(limit or DEFAULT_READ_LIMIT_CHARS), MAX_READ_LIMIT_CHARS))
    end = min(len(raw_text), normalized_offset + normalized_limit)
    chunk = raw_text[normalized_offset:end]
    return {
        "ok": True,
        "raw_ref": f"{RAW_REF_PREFIX}{artifact_id}",
        "tool_name": payload.get("tool_name"),
        "tool_call_id": payload.get("tool_call_id"),
        "task_run_id": payload.get("task_run_id"),
        "raw_chars": len(raw_text),
        "offset": normalized_offset,
        "limit": normalized_limit,
        "returned_chars": len(chunk),
        "has_more": end < len(raw_text),
        "next_offset": end if end < len(raw_text) else None,
        "expires_at": payload.get("expires_at"),
        "content": chunk,
    }


def _artifact_path(artifact_id: str) -> Path:
    return _store_root() / f"{artifact_id}.json"


def _store_root() -> Path:
    configured = os.environ.get("HEYGENT_TOOL_RESULT_STORE_DIR")
    if configured and configured.strip():
        return Path(configured).expanduser()
    # 기본값은 AI/tmp 아래다. 루트 .gitignore와 AI/.gitignore 모두 tmp/를 제외하므로
    # 큰 원본 결과가 실수로 커밋될 가능성을 낮춘다.
    return Path(__file__).resolve().parents[4] / "tmp" / "tool-results"


def _parse_raw_ref(raw_ref: str) -> str | None:
    value = str(raw_ref or "").strip()
    if not value.startswith(RAW_REF_PREFIX):
        return None
    artifact_id = value[len(RAW_REF_PREFIX) :].strip()
    if not artifact_id or "/" in artifact_id or "\\" in artifact_id:
        return None
    return artifact_id


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
