# AI Runtime

## TaskRun

TaskRun은 사용자 요청 하나를 실제로 처리하는 실행 묶음입니다. 채팅에서 요청이 들어오면 AI 서버는 TaskRun을 만들고, 실행 상태와 결과를 저장합니다.

## StepRun

StepRun은 TaskRun 안의 실행 단계입니다. 모델 호출, 도구 실행, 승인 대기, worker 위임, 결과 정리 같은 과정이 StepRun으로 남습니다.

## Agent Loop

Agent loop는 AI가 생각하고, 도구를 호출하고, 결과를 보고, 다음 행동을 정하는 반복 실행 구조입니다. HeyGent의 강점은 이 내부 루프를 화면에서 이해 가능한 실행 기록으로 바꾼다는 점입니다.

## Tool Runtime

Tool runtime은 AI가 실제 행동을 할 수 있게 하는 계층입니다. 터미널, 파일, 브라우저, Notion, Gmail, Mattermost, prototype, work, session 도구가 여기에 포함됩니다.

## Skill Runtime

스킬은 특정 작업을 잘 수행하기 위한 절차와 지식입니다. 모델은 스킬 목록을 보고 적합한 스킬을 읽은 뒤, 스킬 본문에 맞춰 실제 런타임 도구를 사용합니다.

## Memory

장기기억은 사용자의 선호, 반복 절차, 개인화 정보를 저장하고 다음 요청에서 필요한 정보만 recall합니다. 사용된 기억은 mark used로 기록해 품질을 추적합니다.
