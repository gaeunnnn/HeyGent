# 작업 로그

## 날짜

2026-05-16

## 작성자

김상지

## 관련 브랜치 / PR

- 브랜치: AI-feat/ai-provider-selection
- PR: 예정

## 작업 목적

- Gemini provider 연결 이후 `delegate_task` 기반 worker subagent 실행 경로가 OpenAI 기본값으로 떨어질 수 있는지 코드 중심으로 점검하고 보정한다.

## 변경 요약

- delegate worker contract에 `provider_name`을 포함하도록 보정했다.
- worker input payload에 `provider_name`과 `providerName`을 함께 전달해 runtime provider 선택이 Gemini 설정을 유지하도록 했다.
- worker session metadata와 handoff input에도 provider 정보를 남겨 추적 가능하게 했다.
- provider가 명시되지 않아도 worker model이 `gemini-*`이면 `gemini_api_key`로 추론하도록 했다.

## 주요 파일

- `ai/app/domain/orchestration/delegation/delegate_runtime.py`
- `ai/tests/test_delegate_runtime_handoff.py`

## 테스트 / 확인

- `cd ai && .\.venv\Scripts\python.exe -m pytest tests\test_delegate_runtime_handoff.py`
- `cd ai && .\.venv\Scripts\python.exe -m pytest tests\test_delegate_runtime_handoff.py tests\test_agent_tool_guard_loop.py tests\providers\test_gemini_provider.py tests\providers\test_openai_provider.py`

## 결정 / 이슈

- 일반 session agent work assignment 경로는 이미 profile provider를 task input에 붙이고 있었다.
- `delegate_task` worker child session 경로만 model은 유지하지만 provider를 넘기지 않아 Gemini worker가 OpenAI provider 기본값을 타는 리스크가 있었다.

## 다음 단계

- 배포 환경에서 Gemini worker profile로 실제 delegate 실행을 한 번 확인한다.
