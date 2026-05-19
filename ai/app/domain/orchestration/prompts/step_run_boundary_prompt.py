from __future__ import annotations


def build_step_run_boundary_prompt() -> str:
    return "\n".join(
        [
            "작업 단계 표시 규칙:",
            "- StepRun은 runtime이 이미 만든 현재 실행 anchor입니다. 상태 표시를 위해 별도 도구를 호출하지 마세요.",
            "- 매 assistant 응답 본문은 가능하면 JSON object로 작성하고, `text`, `progressUpdate`, `workDisposition` 필드를 사용하세요.",
            "- `text`는 사용자에게 보여 줄 답변입니다. 도구 호출이 필요한 중간 턴이면 빈 문자열이어도 됩니다.",
            "- `progressUpdate`는 현재 StepRun에 표시할 진행 상태입니다. `title`과 `summary`를 짧게 넣으세요.",
            "- `progressUpdate.title`은 대상/주제/산출물과 작업 행위를 함께 포함하세요.",
            "- `progressUpdate.summary`는 결과 보고가 아니라 현재 진행 상태를 간단히 나타냅니다.",
            "- 같은 의미 목표를 달성하기 위한 도구 실패, 재시도, 대체 도구 사용은 새 StepRun으로 만들지 말고 현재 StepRun 내부 operation으로 누적됩니다.",
            "- 작업을 끝낼 때 workId가 연결되어 있으면 `workDisposition`에 `status`, `summary`, 필요 시 `nextAction`을 넣으세요.",
            "- 완료 조건을 만족하면 done, 산출물은 있지만 사용자나 담당자의 확인이 필요하면 in_review, 실제 선행 작업/필수 입력/권한/도구가 없어 더 진행할 수 없을 때만 blocked, 등록만 요청한 작업이면 todo를 남기세요.",
        ]
    )
