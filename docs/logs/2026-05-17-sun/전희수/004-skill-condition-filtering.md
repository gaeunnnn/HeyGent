# 작업 로그

## 날짜

2026-05-17

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: 현재 작업 브랜치
- PR: 미정

## 작업 목적

- skill 설명 주입 단계에서 실제 사용 가능한 runtime tool 기준의 optional condition 필터를 적용한다.
- 조건 없는 skill은 기존처럼 노출하고, 조건이 있는 skill만 tool/toolset availability에 따라 숨긴다.

## 변경 요약

- `SKILL.md` YAML frontmatter의 nested `metadata`를 보존하도록 skill loader를 보강했다.
- `fallback_for_toolsets`, `requires_toolsets`, `fallback_for_tools`, `requires_tools` 조건 필터를 `SkillPromptBuilder`에 추가했다.
- agent loop prompt 생성 시 실제 available tool 목록을 skill catalog 필터에 전달하도록 연결했다.
- capability resolver가 `requires_toolsets` metadata도 인식하도록 보완했다.
- `web-search-fallback` skill은 `web_search`가 없고 `terminal`이 있을 때만 보이는 fallback으로 조정했다.

## 주요 파일

- `ai/app/domain/orchestration/prompts/skill_utils.py`
- `ai/app/domain/orchestration/prompts/skill_prompt.py`
- `ai/app/domain/orchestration/prompts/prompt_builder.py`
- `ai/app/domain/orchestration/capabilities.py`
- `ai/app/skills/web/web-search-fallback/SKILL.md`
- `ai/tests/test_model_loop_contract.py`
- `ai/tests/domain/test_capability_resolver.py`

## 테스트 / 확인

- `AI\.venv\Scripts\python.exe -m pytest AI\tests\test_model_loop_contract.py AI\tests\domain\test_capability_resolver.py AI\tests\tools\test_runtime_tools.py`
- `AI\.venv\Scripts\python.exe -m compileall AI\app\domain\orchestration\prompts AI\app\domain\orchestration\capabilities.py`
- `git diff --check`

## 결정 / 이슈

- 모든 skill에 `requires_tools`를 강제하지 않고, 조건 metadata가 있는 skill만 필터링한다.
- available tool 정보가 없는 호출은 backward compatibility를 위해 기존처럼 skill을 모두 보여준다.
- fallback skill은 원래 도구가 실제 available일 때 숨기고, 원래 도구가 없을 때만 prompt catalog에 남긴다.

## 다음 단계

- 남아 있는 browser config 호환 흔적은 runtime 노출과 분리해서 별도 정리 여부를 판단한다.
- 단순 생활정보 요청의 budget/fast-path 정책을 이어서 조정한다.
