# 작업 로그

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: 현재 작업 브랜치
- PR: 미생성

## 작업 목적

- Mattermost/Notion backend tool 호출 timeout을 10초로 분리한다.
- 세션 에이전트 위임 시 제외 문맥의 parent skill 이름을 required skill로 오인하는 문제를 보정한다.
- SRT 실제 요청 재실행 과정에서 예약 부작용과 후속 연동 결과를 확인한다.

## 변경 요약

- AI 설정에 `backend_tool_timeout_seconds`를 추가하고 기본값을 10초로 설정했다.
- Notion 실행 client와 Mattermost 전송 tool이 memory timeout이 아니라 backend tool timeout을 사용하게 변경했다.
- `session_agent_task`가 하위 작업 설명의 "Notion은 수행하지 않음" 같은 제외 문구를 skill 요구로 추가하지 않도록 보정했다.
- 새 기본 에이전트 세션의 K-agent에 기존 암호화 SRT secret store 값을 복사해 테스트했다.

## 주요 파일

- `ai/app/core/config.py`
- `ai/app/clients/backend_notion.py`
- `ai/app/tools/messaging/mattermost_tool.py`
- `ai/app/tools/runtime/local_tool_runtime.py`
- `ai/tests/core/test_config.py`
- `ai/tests/clients/test_backend_notion_client.py`
- `ai/tests/tools/test_mattermost_tool.py`
- `ai/tests/tools/test_runtime_tools.py`

## 테스트 / 확인

- `python -m pytest .\ai\tests\core\test_config.py .\ai\tests\clients\test_backend_notion_client.py .\ai\tests\tools\test_mattermost_tool.py .\ai\tests\tools\test_runtime_tools.py`
- 결과: 50 passed
- AI 컨테이너 재빌드 후 `backend_tool_timeout_seconds=10.0` 확인.
- SRT 예약 목록 확인 결과 0건.
- 최종 재실행에서 K-agent는 `srt-booking`만 required skill로 받아 실행됐고, 2026-06-05 16:00~18:00 부산→수서 일반실 3편 모두 매진/예약대기 불가로 예약은 생성되지 않았다.

## 결정 / 이슈

- parent skill 자동 추론은 유지하되, 제외/부정 문맥에서는 required skill로 추가하지 않는다.
- 예약이 성공하지 않았으므로 Mattermost 공유와 Notion 달력 등록은 실행하지 않는 것이 맞다.
- 새 세션에 secret을 복사한 것은 사용자가 명시 승인한 테스트용 처리이며, 비밀값 원문은 문서와 로그에 남기지 않았다.

## 다음 단계

- 사용자가 시간대 확대, 특실 허용, 대체역 허용 중 하나를 승인하면 같은 세션에서 재조회/예약을 진행한다.
- 장기적으로는 새 기본 에이전트 세션 생성 시 사용자가 저장한 K-agent secret을 어떻게 승계할지 제품 정책을 정해야 한다.
