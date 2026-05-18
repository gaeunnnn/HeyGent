# 프로토타입 preview 검증 추가

- 날짜: 2026-05-18
- 작성자: 전희수
- 관련 브랜치 또는 PR: AI-fix/model-RPM-set
- 작업 목적: `prototype.create_artifact`가 preview에서 바로 깨질 수 있는 import/export 오류를 저장 전에 잡아, 깨진 artifact를 완료 상태로 남기지 않도록 한다.

## 변경 요약

- React 프로토타입 파일 저장 직전에 preview 지원 패키지, `lucide-react` 브랜드 아이콘 import, entry 파일 default export를 검증하도록 추가했다.
- 검증 실패 시 artifact를 저장하지 않고 `prototype_validation_failed`와 `details.issues`를 반환하도록 했다.
- `awesome-design` 스킬에 브랜드 아이콘은 `react-icons/fa`를 쓰고, 검증 실패 시 오류를 고쳐 다시 `prototype.create_artifact`를 호출하라는 규칙을 추가했다.
- 개발자 포트폴리오 첫 화면 요청으로 신규 세션을 만들어 실제 생성/preview 렌더링을 확인했다.

## 주요 파일

- `AI/app/tools/prototype/prototype_validation.py`
- `AI/app/tools/runtime/local_tool_runtime.py`
- `AI/app/tools/prototype/prototype_tool.py`
- `AI/app/skills/design/awesome-design/SKILL.md`
- `AI/tests/tools/test_prototype_runtime_tool.py`

## 테스트 또는 확인 내용

- `AI/.venv/Scripts/python.exe -m pytest tests/tools/test_prototype_runtime_tool.py`: 7 passed
- `docker compose -f compose.yml up -d --build ai` 후 `GET /ai/api/v1/ready`: ready
- 컨테이너 내부 validator smoke에서 `import { Github } from "lucide-react"`가 `unsupported_lucide_brand_icon`으로 잡히고 `react-icons/fa: FaGithub`를 제안하는 것을 확인했다.
- 신규 세션 `session_b03e182941944037aa0839b0a30f73d7`에서 개발자 포트폴리오 첫 화면 생성을 실행했고, `prototype_artifact_8973cd73f9b541d88bcdc86da0613d06` / `prototype_version_79b26f8b57334cb9b5d37dde88a87e08`가 생성됐다.
- 생성 결과는 `lucide-react`의 일반 아이콘과 `react-icons/fa`의 `FaGithub`, `FaLinkedinIn`을 사용했고, Playwright preview에서 이전 `TopNav` invalid element 오류 없이 렌더링됐다.

## 결정, 이슈, 리스크

- 이번 검증은 전체 Vite build가 아니라 저장 전 정적 preview 검증이다. import/export에서 자주 터지는 오류를 빠르게 막는 목적이다.
- 로컬 host `frontend/node_modules`에는 `react-icons`가 없어 임시 Vite build는 dependency resolve에서 실패했지만, 실제 frontend 컨테이너에는 `react-icons`와 `lucide-react`가 설치되어 preview 렌더링은 정상 확인했다.
- preview 콘솔에 Sandpack telemetry 타임아웃이 있었지만 React render/import 오류는 아니었다.

## 다음 단계

- 필요하면 다음 단계로 artifact 생성 후 실제 bundle/build 검증 및 1회 자동 수정 루프까지 확장한다.
