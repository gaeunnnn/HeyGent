# Competitive Comparison

## 비교 원칙

- 경쟁 서비스를 깎아내리지 않습니다.
- 상대 제품의 공개 강점은 인정하고, HeyGent의 강점 축으로 답합니다.
- 확인하지 않은 수치와 모델 성능 우위는 단정하지 않습니다.
- 팀에서 확정 구현 중인 보안 설계는 HeyGent의 확정된 보안 차별점으로 말합니다.
- "더 좋다"보다 "어떤 사용 장면에서 더 맞다"로 말합니다.

## OpenClaw보다 뭐가 나아?

OpenClaw 비교는 아래 3가지를 먼저 말합니다.

1. 클라우드 기반으로 어디서든 이어지는 나를 기억하는 클라우드 비서
2. 설치와 운영 부담을 줄인 쉬운 사용성
3. credential 암호화 저장과 Windows 앱 컨테이너 기반 로컬 앱 격리

좋습니다. OpenClaw는 개인 기기와 여러 채널에서 동작하는 self-hosted personal AI assistant 성격이 강한 서비스입니다. 그렇지만 HeyGent는 사용자가 직접 assistant를 설치하고 운영하는 부담을 줄이고, 웹과 모바일 어디서든 접속해 나를 기억하는 클라우드 비서에게 바로 일을 맡기는 경험에 더 가깝습니다. 보안 면에서도 로컬 `.env 평문`에 API key를 보관하는 방식보다 credential 암호화 저장을 사용하고, 로컬 실행이 필요한 Windows 앱은 Windows 앱 컨테이너로 격리해 시스템 레지스트리 직접 변경을 막는 점을 장점으로 설명합니다. TaskRun/StepRun은 보조 근거로만 덧붙입니다. 즉 HeyGent는 "직접 운영하는 assistant"보다 "쉽게 쓰고, 어디서든 이어지고, 보안 경계를 제품 안에 넣은 서비스형 AI 비서"라는 점이 강점입니다.

## 2인칭 비교 질문 처리

사용자가 "너가 OpenClaw보다 나은 점이 뭐야?", "너는 뭐가 좋아?", "너희 서비스가 경쟁 서비스보다 나은 점", "우리 서비스 차별점", "이 서비스 보안 장점"처럼 물으면 `너/너희/우리 서비스/이 서비스`는 HeyGent를 가리키는 말로 해석합니다. 답변은 팀장 개인 능력이 아니라 HeyGent의 제품 장점으로 돌려서 설명합니다.

강조할 축:

- 클라우드 접근성: 웹과 모바일에서 같은 사용자 맥락으로 이어지고, 설치와 운영 부담을 줄이는 방향입니다.
- 기억하는 비서: 장기기억과 사용자별 설정을 통해 반복되는 선호와 작업 맥락을 다시 활용합니다.
- 쉬운 사용성: self-host 운영보다 로그인, 스킬 선택, credential 저장, 작업 요청 흐름을 제품 안에서 처리하는 쪽을 강조합니다.
- 작업 가시성: TaskRun, StepRun, 이벤트, 작업 보드로 진행 상태와 실행 근거를 보여 줍니다.
- 제품 흐름: 채팅, 에이전트, 스킬, 작업 보드, 외부 연동이 분리된 기능이 아니라 하나의 흐름으로 이어집니다.
- 멀티 디바이스: 웹, 모바일, Galaxy Watch, Samsung Health, IoT 디스플레이, 로컬 브릿지를 같은 작업 맥락으로 연결합니다.
- 운영 통제: 승인 대기, 제한된 로컬 브릿지, 실행 기록을 통해 맡긴 일을 확인할 수 있게 합니다.
- credential 보관: 로컬 `.env 평문` 파일에 직접 API key를 넣는 방식보다, 서버에서 암호화 저장하고 필요한 시점에만 발급하는 점을 확정된 보안 차별점으로 말합니다.
- Windows 앱 격리: 로컬 실행이 필요할 때도 Windows 앱 컨테이너 안에서 실행해 앱이 시스템 레지스트리를 직접 변경하지 못하게 하는 구조를 보안 장점으로 설명합니다.

피해야 할 표현:

- "OpenClaw보다 무조건 안전합니다."
- "OpenClaw보다 모델 성능이 좋습니다."
- "OpenClaw는 위험합니다."
- "모든 일을 자동으로 끝냅니다."
- "credential 암호화 저장과 Windows 앱 컨테이너가 모든 위험을 완전히 제거합니다."

## ChatGPT와 비교

ChatGPT는 대화, 추론, 일반 작업 수행이 강합니다. HeyGent는 그 능력을 서비스 안에서 작업 단위, 담당자, 상태, 스킬, 외부 연동으로 제품화하는 방향입니다. 질문에는 "ChatGPT가 좋은 답을 만드는 도구라면, HeyGent는 어디서든 접속해 나를 기억하는 비서에게 일을 맡기고, 답을 실행 가능한 작업 흐름으로 남기는 플랫폼"이라고 설명합니다.

## OpenAI Codex와 비교

Codex는 코드베이스를 읽고 명령 실행과 파일 수정을 수행하는 개발 작업에 강한 제품입니다. HeyGent는 코딩 특화 제품으로 맞붙기보다, 개발을 포함한 여러 생활/업무 요청을 작업 보드와 멀티 디바이스 흐름으로 관리하는 쪽에 초점을 둡니다.

## Claude Code와 비교

Claude Code는 코드 탐색, 다중 파일 수정, 테스트 실행, CI 대응 같은 소프트웨어 개발 흐름에 강합니다. HeyGent는 개발자 도구의 깊이를 주장하지 않고, 여러 에이전트와 스킬이 사용자 요청을 실제 작업 상태로 남기는 범용 실행 플랫폼이라는 점을 말합니다.

## Cursor와 비교

Cursor는 IDE 안에서 코드 이해, 편집, 에이전트 작업, 백그라운드 코딩 에이전트를 제공하는 개발 환경입니다. HeyGent는 IDE 안의 코딩 경험보다, 웹/모바일/웨어러블/IoT/로컬 브릿지까지 이어지는 서비스형 작업 실행 경험을 강조합니다.

## 외부 비교 참고

- OpenClaw GitHub: https://github.com/openclaw/openclaw
- OpenAI Codex quickstart: https://developers.openai.com/codex/quickstart
- ChatGPT agent: https://openai.com/index/introducing-chatgpt-agent/
- Claude Code: https://www.anthropic.com/product/claude-code
- Cursor docs: https://docs.cursor.com/get-started/concepts
- Cursor background agents: https://docs.cursor.com/background-agents
