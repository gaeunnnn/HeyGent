from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TranscriptStore(Protocol):
    """agent.loop transcript와 세션 검색 저장소가 지켜야 하는 계약이다."""

    def create_session(
        self,
        *,
        session_id: str,
        session_key: str,
        source: str,
        user_id: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        parent_session_id: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """새 transcript/session 레코드를 만든다."""
        ...

    def end_session(self, session_id: str, *, end_reason: str | None = None) -> None:
        """열린 transcript/session을 종료 상태로 표시한다."""
        ...

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """식별자로 transcript/session 메타데이터를 조회한다."""
        ...

    def list_sessions(
        self,
        owner: str | None = None,
        *,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False,
        include_deleted: bool = False,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        """owner 범위의 transcript/session 목록을 최근 업데이트 순서로 조회한다."""
        ...

    def count_sessions(
        self,
        owner: str | None = None,
        *,
        user_id: str | None = None,
        include_archived: bool = False,
        include_deleted: bool = False,
        source: str | None = None,
    ) -> int:
        """조건에 맞는 transcript/session 개수를 조회한다."""
        ...

    def get_latest_session_by_key(self, session_key: str, *, owner: str | None = None) -> dict[str, Any] | None:
        """동일 owner/session_key 중 가장 최근 transcript/session을 조회한다."""
        ...

    def append_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str | None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        finish_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """transcript/session에 메시지 한 건을 추가한다."""
        ...

    def list_messages(self, session_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        """저장된 메시지를 provider replay 순서로 조회한다."""
        ...

    def search_sessions(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """메시지 본문 기준으로 transcript/session을 검색한다."""
        ...

    def append_user_message_and_start_task(
        self,
        *,
        owner_key: str,
        session_id: str,
        content: str,
        client_message_id: str,
        task_run_id: str,
        base_history_version: int,
        metadata_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """user message 저장과 running guard 획득은 하나의 상태 전이다.

        같은 client_message_id가 이미 저장되어 있으면 새 TaskRun을 만들지 않고
        기존 task 정보를 반환한다. 네트워크 재전송은 중복 실행이 아니라 같은 명령의 재확인이다.
        """
        ...

    def append_assistant_message_and_finish_task(
        self,
        *,
        owner_key: str,
        session_id: str,
        task_run_id: str,
        content: str,
        completion_expected_version: int,
        status: str,
    ) -> dict[str, Any]:
        """assistant message 저장과 running guard 해제는 같은 transaction에서 끝낸다."""
        ...

    def clear_stale_running_task(
        self,
        *,
        owner_key: str,
        session_id: str,
        task_run_id: str,
    ) -> bool:
        """완료/실패 TaskRun이 남긴 guard만 소유 확인 후 정리한다."""
        ...

    def search_public_sessions(
        self,
        query: str,
        *,
        owner_key: str,
        workspace_key: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """사용자-facing session 검색이다. owner 없는 호출은 허용하지 않는다."""
        ...

    def search_transcript_sessions(
        self,
        query: str,
        *,
        owner_key: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """내부 실행 transcript 검색이다. owner 없는 호출은 허용하지 않는다."""
        ...

    def close(self) -> None:
        """저장소 연결과 관련 자원을 닫는다."""
        ...
