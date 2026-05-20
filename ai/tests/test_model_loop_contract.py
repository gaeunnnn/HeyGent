from pathlib import Path
from types import SimpleNamespace

from app.clients.backend_memory import BackendMemoryItem
from app.domain.orchestration.agent.tool_calling_loop import ToolCallingLoopHandler
from app.domain.orchestration.prompts.persistent_memory_prompt import build_persistent_memory_prompt
from app.domain.orchestration.prompts.prompt_builder import (
    PromptBuilder,
    assemble_agent_loop_messages,
    build_work_context_prompt,
    render_single_prompt_fallback,
)
from app.domain.orchestration.prompts.skill_prompt import SkillLoader, SkillPromptBuilder, SkillRegistry


def test_prompt_builder_includes_native_tool_call_and_termination_guidance():
    prompt_builder = PromptBuilder(SkillPromptBuilder(SkillRegistry()))

    prompt = prompt_builder.build_agent_loop_prompt(
        input_payload={"prompt": "필요한 작업을 판단해."},
        available_tools=[{"name": "skills.list", "summary": "skill 목록 조회", "toolset": "skills"}],
        tool_results=[],
        task_todo_state=None,
        resume_payload=None,
        turn_index=1,
        max_iterations=4,
    )

    assert "모델의 tool call 응답으로 반환하세요" in prompt
    assert "이미 충분한 정보가 있으면 더 이상 도구를 부르지 말고 일반 답변으로 종료하세요." in prompt
    assert "직전에 같은 도구를 같은 인자로 실행했다면 반복하지 말고 답변 종료를 우선하세요." in prompt
    assert "사용자에게 보일 현재 진행 상태는 assistant 응답의 progressUpdate로 갱신하고, 세부 체크리스트는 todo 도구로 갱신하세요." in prompt
    assert "사용자 요청 전체 또는 요청 안의 의미 있는 하위 작업이 다른 세션 에이전트의 skill 이름이나 설명과 맞고" in prompt
    assert "현재 실행 에이전트가 직접 답할 수 있더라도 위 조건을 만족하면 호출을 우선하세요." in prompt
    assert "session_agent_task 는 작업 보드에 보이는 하위 작업과 실제 세션 에이전트 실행을 묶는 도구입니다." in prompt
    assert "후보의 이름, 호칭, 할 수 있는 일, 연결된 스킬 이름과 공용 스킬 설명이 사용자 요청과 맞아야 합니다." in prompt
    assert "후보가 요청의 핵심 부분을 수행할 수 있고, 독립 산출물이나 책임 분리가 자연스러울 때" in prompt
    assert "독립 산출물이나 책임 분리가 자연스러울 때 세션 에이전트 작업으로 분리하세요." in prompt
    assert "분리할 실익이 낮은 작업은 팀장이 직접 처리해도 됩니다." in prompt
    assert "수행할 수 있는 세션 에이전트가 없으면 임의로 배정하지 말고" in prompt
    assert "세션 에이전트 후보의 skill 설명은 위임 판단용입니다." in prompt
    assert "현재 실행 에이전트가 직접 보유한 skill이 아니면 `skills.read`로 읽지 마세요." in prompt
    assert "requiredSkillNames에 필요한 skill 이름을 담으세요." in prompt
    assert "폴더 경로 자체를 파일명으로 바꾸지 말고 폴더 안에 의미 있는 파일명을 만들어 저장하세요." in prompt
    assert "사용자가 자신의 이름, 호칭, 프로필, 선호, 비선호, 반복 행동, 작업 습관 같은 지속 정보를 알려주면" in prompt
    assert "`progressUpdate`는 현재 StepRun에 표시할 진행 상태입니다." in prompt
    assert "`progressUpdate.title`은 대상/주제/산출물과 작업 행위를 함께 포함하세요." in prompt
    assert "작업을 끝낼 때 workId가 연결되어 있으면 `workDisposition`" in prompt


def test_session_agent_task_parent_disposition_is_used_as_task_work_disposition():
    disposition = ToolCallingLoopHandler._parent_work_disposition_from_tool_results(
        [
            {
                "name": "session_agent_task",
                "result": {
                    "ok": True,
                    "parentWorkDisposition": {
                        "workId": "work-parent",
                        "status": "in_review",
                        "summary": "하위 작업 결과를 반영함",
                    },
                },
            }
        ]
    )

    assert disposition == {
        "workId": "work-parent",
        "status": "in_review",
        "summary": "하위 작업 결과를 반영함",
    }


def test_dynamic_work_link_updates_tool_runtime_context():
    task_input = {"prompt": "k-skill 써서 지하철 노선도 알아봐봐"}
    task = SimpleNamespace(
        input_payload={
            **task_input,
            "workId": "work-skill",
            "workIdentifier": "TASK-1",
            "workTitle": "skill-index 스킬 실행",
            "workContext": {"title": "skill-index 스킬 실행"},
            "workLinkReason": "skill_use",
        }
    )
    tool_runtime = SimpleNamespace(runtime_context=dict(task_input))

    ToolCallingLoopHandler._sync_dynamic_runtime_context(
        task=task,
        task_input=task_input,
        tool_runtime=tool_runtime,
    )

    assert task_input["workId"] == "work-skill"
    assert task_input["workIdentifier"] == "TASK-1"
    assert tool_runtime.runtime_context["workId"] == "work-skill"
    assert tool_runtime.runtime_context["workLinkReason"] == "skill_use"


def test_prompt_builder_explains_approval_tool_call_boundary():
    prompt_builder = PromptBuilder(SkillPromptBuilder(SkillRegistry()))

    prompt = prompt_builder.build_agent_loop_prompt(
        input_payload={
            "prompt": "터미널 확인이 필요해.",
            "approval_required": True,
            "approval_reason": "터미널 실행 전 확인",
        },
        available_tools=[{"name": "terminal_run", "summary": "터미널 실행", "toolset": "terminal"}],
        tool_results=[],
        task_todo_state=None,
        resume_payload=None,
        turn_index=1,
        max_iterations=4,
    )

    assert "approval_required=true" in prompt
    assert "도구 호출 자체는 먼저 native tool call로 반환하세요" in prompt
    assert "같은 tool_call_id" in prompt


def test_prompt_builder_places_persistent_memory_after_current_prompt_for_turn_application():
    prompt_builder = PromptBuilder(SkillPromptBuilder(SkillRegistry()))
    memory_context = "<memory-context>\ncontent: 사용자는 짧은 답변을 선호한다.\n</memory-context>"

    prompt = prompt_builder.build_model_prompt(
        input_payload={
            "prompt": "오늘 회의 정리해줘",
            "persistent_memory_context": memory_context,
        }
    )

    assert memory_context in prompt
    assert prompt.index("오늘 회의 정리해줘") < prompt.index("<memory-context>")


def test_build_agent_loop_prompt_repeats_memory_application_instructions_at_end():
    prompt_builder = PromptBuilder(SkillPromptBuilder(SkillRegistry()))
    memory_context = """
<memory-context>
content: 사용자는 짧은 답변을 선호한다.
</memory-context>

<memory-application-instructions>
현재 턴 답변 직전에 반드시 확인하세요.
</memory-application-instructions>
""".strip()

    prompt = prompt_builder.build_agent_loop_prompt(
        input_payload={
            "prompt": "서울 여행 계획 짜줘",
            "persistent_memory_context": memory_context,
        },
        available_tools=[],
        tool_results=[],
        task_todo_state=None,
        resume_payload=None,
        turn_index=1,
        max_iterations=4,
    )

    assert prompt.count("<memory-application-instructions>") == 2
    assert prompt.rfind("<memory-application-instructions>") > prompt.rfind("최종 답변은 내부 상태 문구처럼 쓰지 말고")


def test_prompt_builder_includes_work_assignment_context_before_current_prompt():
    prompt_builder = PromptBuilder(SkillPromptBuilder(SkillRegistry()))

    prompt = prompt_builder.build_model_prompt(
        input_payload={
            "prompt": "결과를 파일로 저장해줘",
            "workId": "work-1",
            "workIdentifier": "TASK-7",
            "workAssigneeAgentId": "agent-researcher",
            "workContext": {
                "title": "삼성전자와 SK하이닉스 조사",
                "labels": ["research"],
                "promptPreview": "최근 이슈를 요약한다.",
            },
        }
    )

    assert "연결된 작업 컨텍스트" in prompt
    assert "TASK-7" in prompt
    assert "agent-researcher" in prompt
    assert "담당 작업 실행 자체를 worker delegate로 다시 위임하지 마세요." in prompt
    assert prompt.index("연결된 작업 컨텍스트") < prompt.index("결과를 파일로 저장해줘")


def test_prompt_builder_promotes_session_agent_task_from_candidate_profiles():
    prompt_builder = PromptBuilder(SkillPromptBuilder(SkillRegistry()))

    prompt = prompt_builder.build_agent_loop_prompt(
        input_payload={
            "prompt": "이번 주 금요일 부산 출발 수서역 도착 SRT 오후 4시에서 6시 사이 열차 예약 가능 여부를 확인해줘.",
            "workId": "work-ceo-1",
            "workIdentifier": "TASK-31",
            "workAssigneeAgentId": "CEO",
            "workContext": {"title": "SRT 예약 가능 여부 확인"},
            "sessionAgentProfiles": [
                {
                    "profileId": "agent-travel",
                    "configSnapshot": {
                        "name": "교통 예약 에이전트",
                        "role": "travel",
                        "title": "열차 예약 확인",
                        "description": "열차 시간표와 예약 가능 여부를 확인한다.",
                        "skills": ["seoul-subway-arrival"],
                    },
                },
                {
                    "profileId": "agent-report",
                    "configSnapshot": {
                        "name": "보고서 에이전트",
                        "role": "writer",
                        "description": "확인 결과를 사용자에게 전달할 문장으로 정리한다.",
                    },
                },
            ],
        },
        available_tools=[
            {"name": "session_agent_task", "summary": "세션 에이전트에게 하위 작업 위임", "toolset": "work"},
            {"name": "http_get", "summary": "HTTP 조회", "toolset": "web"},
        ],
        tool_results=[],
        task_todo_state=None,
        resume_payload=None,
        turn_index=1,
        max_iterations=4,
    )

    assert "세션 에이전트 후보:" in prompt
    assert "agent-travel: 이름=교통 예약 에이전트 / 호칭=열차 예약 확인 / 할 수 있는 일=열차 시간표와 예약 가능 여부를 확인한다. / 스킬=seoul-subway-arrival / 참고 분류=travel" in prompt
    assert "agent-report: 이름=보고서 에이전트 / 할 수 있는 일=확인 결과를 사용자에게 전달할 문장으로 정리한다. / 참고 분류=writer" in prompt
    assert "후보의 이름, 호칭, 할 수 있는 일, 연결된 스킬 이름과 공용 스킬 설명이 사용자 요청과 맞아야 합니다." in prompt
    assert "사용자 요청 전체 또는 요청 안의 의미 있는 하위 작업이 다른 세션 에이전트의 skill 이름이나 설명과 맞고" in prompt
    assert "그 에이전트가 해당 skill을 바탕으로 현재 실행 에이전트보다 더 적합하게 처리할 가능성이 있으면" in prompt
    assert "현재 실행 에이전트가 직접 답할 수 있더라도 위 조건을 만족하면 호출을 우선하세요." in prompt
    assert "현재 응답의 progressUpdate에 세션 에이전트 실행 상태를 남긴 뒤 session_agent_task" in prompt
    assert "단순 응답, 맥락 정리, 최종 종합" in prompt
    assert "CEO가 직접" not in prompt
    assert "관점/영역별로 독립된 delegate_task" not in prompt


def test_work_context_prompt_does_not_infer_session_agents_from_user_text():
    prompt = build_work_context_prompt(
        input_payload={
            "prompt": "서브에이전트 써서 확인해줘. 여러 명 불러도 돼.",
        }
    )

    assert prompt == ""


def test_work_context_prompt_can_show_explicit_session_agent_candidates_without_work():
    prompt = build_work_context_prompt(
        input_payload={
            "prompt": "서브에이전트 써서 확인해줘.",
            "sessionAgentProfiles": [
                {
                    "profileId": "agent-travel",
                    "configSnapshot": {
                        "name": "교통 예약 에이전트",
                        "role": "travel",
                        "description": "열차 시간표와 예매 조건을 확인한다.",
                    },
                }
            ],
        }
    )

    assert "세션 에이전트 후보:" in prompt
    assert "agent-travel: 이름=교통 예약 에이전트 / 할 수 있는 일=열차 시간표와 예매 조건을 확인한다. / 참고 분류=travel" in prompt


def test_work_context_prompt_shows_session_agent_skill_descriptions():
    prompt = build_work_context_prompt(
        input_payload={
            "prompt": "지하철에서 지갑 잃어버렸어.",
            "sessionAgentProfiles": [
                {
                    "profileId": "agent-k",
                    "configSnapshot": {
                        "name": "K-에이전트",
                        "skills": ["subway-lost-property"],
                    },
                    "skillDescriptions": [
                        {
                            "name": "subway-lost-property",
                            "description": "서울 지하철 유실물 접수와 보관 장소 조회를 돕는다.",
                            "usage": "\"강남역에서 지갑 잃어버렸는데 어디서 찾아?\"",
                        }
                    ],
                }
            ],
        }
    )

    assert "스킬=subway-lost-property" in prompt
    assert "세션 에이전트 공용 스킬 설명:" in prompt
    assert "subway-lost-property: 서울 지하철 유실물 접수와 보관 장소 조회를 돕는다." in prompt
    assert "사용 예시" not in prompt
    assert "강남역에서 지갑" not in prompt


def test_work_context_prompt_deduplicates_shared_session_agent_skill_descriptions():
    prompt = build_work_context_prompt(
        input_payload={
            "sessionAgentProfiles": [
                {
                    "profileId": "agent-k",
                    "configSnapshot": {"name": "K-에이전트", "skills": ["subway-lost-property"]},
                    "skillDescriptions": [
                        {
                            "name": "subway-lost-property",
                            "description": "서울 지하철 유실물 접수와 보관 장소 조회를 돕는다.",
                        }
                    ],
                },
                {
                    "profileId": "agent-general",
                    "configSnapshot": {"name": "기본 에이전트", "skills": ["subway-lost-property"]},
                    "skillDescriptions": [
                        {
                            "name": "subway-lost-property",
                            "description": "서울 지하철 유실물 접수와 보관 장소 조회를 돕는다.",
                        }
                    ],
                },
            ]
        }
    )

    assert prompt.count("subway-lost-property: 서울 지하철 유실물 접수와 보관 장소 조회를 돕는다.") == 1
    assert "agent-k: 이름=K-에이전트 / 스킬=subway-lost-property" in prompt
    assert "agent-general: 이름=기본 에이전트 / 스킬=subway-lost-property" in prompt


def test_work_context_prompt_truncates_session_agent_skill_descriptions_for_routing():
    prompt = build_work_context_prompt(
        input_payload={
            "sessionAgentProfiles": [
                {
                    "profileId": "agent-k",
                    "configSnapshot": {"name": "K-에이전트", "skills": ["korea-weather"]},
                    "skillDescriptions": [
                        {
                            "name": "korea-weather",
                            "description": (
                                "한국 날씨를 기상청 단기예보 조회서비스와 프록시 경유로 조회해 요약하고, "
                                "지역 좌표와 날짜 기준을 바탕으로 사용자가 바로 이해할 수 있게 설명한다."
                            ),
                        }
                    ],
                }
            ]
        }
    )

    assert (
        "korea-weather: 한국 날씨를 기상청 단기예보 조회서비스와 프록시 경유로 조회해 요약하고, "
        "지역 좌표와 날짜 기준을 바탕으로 사용자가 바로 이해할 수 있게..."
    ) in prompt
    assert "설명한다" not in prompt


def test_persistent_memory_prompt_sanitizes_metadata():
    prompt = build_persistent_memory_prompt(
        [
            BackendMemoryItem(
                id=10,
                memory_type="PREFERENCE",
                store_type="PROFILE",
                scope_type="GLOBAL",
                content="사용자는 한국어 답변을 선호한다.",
                summary="언어 선호",
                metadata={
                    "workspaceKey": "team-a",
                    "token": "secret-token",
                    "tags": ["language"],
                    "category": "preference",
                    "ttl": "long",
                    "sourceTimestamp": "2026-05-11T10:30:00",
                    "eventTime": "2026-05-11T09:00:00",
                    "reason": "발표 응답 톤을 맞추기 위해 저장한다.",
                    "sensitivity": "medium",
                },
            )
        ]
    )

    assert "<memory-context>" in prompt
    assert "사용자는 한국어 답변을 선호한다." in prompt
    assert "workspaceKey" in prompt
    assert "preference" in prompt
    assert "sourceTimestamp" in prompt
    assert "eventTime" in prompt
    assert "발표 응답 톤" in prompt
    assert "secret-token" not in prompt
    assert "sensitivity" not in prompt


def test_persistent_memory_prompt_applies_relevant_instructions():
    prompt = build_persistent_memory_prompt(
        [
            BackendMemoryItem(
                id=11,
                memory_type="INSTRUCTION",
                store_type="AGENT_MEMORY",
                scope_type="GLOBAL",
                content="여행 계획 요청 시 날짜와 예산을 먼저 확인한 뒤 교통편, 숙소, 식당 순서로 계획한다.",
                summary="여행 계획 절차",
                metadata={"category": "instruction", "tags": ["travel", "planning"]},
            )
        ]
    )

    assert "INSTRUCTION/PROCEDURE 기억은 관련 요청의 답변 방식이나 진행 절차에 적용하세요." in prompt
    assert "필요한 조건을 먼저 짧게 물어보세요." in prompt
    assert "작업 수행을 요청하는 말은 선확인 절차와 충돌하는 지시가 아닙니다." in prompt
    assert "여행 계획 요청 시 날짜와 예산" in prompt
    assert "<memory-application-instructions>" in prompt
    assert prompt.index("</memory-context>") < prompt.index("<memory-application-instructions>")
    assert "현재 턴 답변 직전에 반드시 확인하세요." in prompt
    assert "현재 요청과 관련 있는 INSTRUCTION/PROCEDURE가 있으면, 그 절차를 답변 구조와 순서에 적용하세요." in prompt
    assert "세부 결과를 만들지 말고 필요한 조건만 먼저 짧게 물어보세요." in prompt


def test_prompt_builder_includes_skill_description_catalog_without_reader_tool_policy():
    registry = SkillRegistry()
    registry.register_many(SkillLoader().load_builtin())
    prompt_builder = PromptBuilder(SkillPromptBuilder(registry))

    prompt = prompt_builder.build_agent_loop_prompt(
        input_payload={"prompt": "강남구 날씨 알려줘"},
        available_tools=[
            {"name": "http_get", "summary": "HTTP 조회", "toolset": "web"},
        ],
        tool_results=[],
        task_todo_state=None,
        resume_payload=None,
        turn_index=1,
        max_iterations=4,
    )

    assert "사용 가능한 skill 설명" in prompt
    assert "현재 실행 에이전트가 직접 사용할 수 있는 skill의 이름과 설명입니다." in prompt
    assert "작업을 시작할 때 먼저 아래 목록에서 사용자 요청을 처리할 수 있는 skill 후보가 있는지 확인하세요." in prompt
    assert "세션 에이전트 후보가 더 직접적으로 맞으면 이 목록에 억지로 맞추지 말고 세션 에이전트 배정을 검토하세요." in prompt
    assert "사용자 입력을 직접 수행할 수 있는 skill이 있으면 일반 도구를 바로 호출하기보다 해당 skill을 최대한 우선 후보로 삼으세요." in prompt
    assert "관련 skill 후보를 선택했다면 `skills.read` 또는 `skill.execute`로 본문을 먼저 확인한 뒤" in prompt
    assert "전혀 관련 있는 skill이 없을 때만 skill 없이 진행하고, skill 본문에 제한이나 우선 절차가 있으면 그 절차를 우선하세요." in prompt
    assert "skills.read" in prompt
    assert "skills.read_file" not in prompt
    assert "k-skills`를 우선" not in prompt
    assert "`korea-weather`" in prompt
    assert "한국 날씨를 기상청 단기예보 조회서비스" in prompt


def test_heygent_catalog_description_surfaces_openclaw_answer_priorities():
    registry = SkillRegistry()
    registry.register_many(SkillLoader().load_builtin())
    prompt_builder = PromptBuilder(SkillPromptBuilder(registry))

    prompt = prompt_builder.build_agent_loop_prompt(
        input_payload={
            "prompt": "너가 오픈클로보다 나은게 뭐야",
            "enabledSkillNames": ["heygent"],
        },
        available_tools=[
            {"name": "skills.read", "summary": "skill 본문 조회", "toolset": "skills"},
        ],
        tool_results=[],
        task_todo_state=None,
        resume_payload=None,
        turn_index=1,
        max_iterations=4,
    )

    assert "`heygent`" in prompt
    assert "OpenClaw" in prompt
    assert "클라우드 기억 비서" in prompt
    assert "쉬운 사용" in prompt
    assert "credential 암호화 저장" in prompt
    assert "Windows 앱 컨테이너" in prompt


def test_session_agent_context_precedes_direct_skill_catalog_for_routing():
    registry = SkillRegistry()
    registry.register_many(
        [
            {
                "name": "mattermost-send",
                "description": "사용자가 명시한 메시지를 Mattermost 채널로 전송한다.",
            },
            {
                "name": "subway-lost-property",
                "description": "지하철 유실물 접수와 보관 장소 조회를 돕는다.",
            },
        ]
    )
    prompt_builder = PromptBuilder(SkillPromptBuilder(registry))

    prompt = prompt_builder.build_model_prompt(
        input_payload={
            "prompt": "어제 강남역 지하철에서 지갑 잃어버렸어.",
            "enabledSkillNames": ["mattermost-send"],
            "targetAgentProfile": {
                "configSnapshot": {
                    "name": "팀장",
                    "skills": ["mattermost-send"],
                }
            },
            "sessionAgentProfiles": [
                {
                    "profileId": "agent-k",
                    "configSnapshot": {
                        "name": "K-에이전트",
                        "description": "한국 지하철 유실물 안내를 맡습니다.",
                        "skills": ["subway-lost-property"],
                    },
                    "skillDescriptions": [
                        {
                            "name": "subway-lost-property",
                            "description": "지하철 유실물 접수와 보관 장소 조회를 돕는다.",
                        }
                    ],
                }
            ],
        }
    )

    assert prompt.index("세션 에이전트 후보:") < prompt.index("사용 가능한 skill 설명:")
    assert "스킬: mattermost-send" in prompt
    assert "subway-lost-property: 지하철 유실물 접수와 보관 장소 조회를 돕는다." in prompt


def test_prompt_builder_filters_skill_catalog_by_enabled_skill_names():
    registry = SkillRegistry()
    registry.register_many(
        [
            {"name": "korea-weather", "description": "한국 날씨 조회"},
            {"name": "zipcode-search", "description": "우편번호 조회"},
        ]
    )
    prompt_builder = PromptBuilder(SkillPromptBuilder(registry))

    prompt = prompt_builder.build_model_prompt(
        input_payload={
            "prompt": "날씨 확인",
            "enabledSkillNames": ["korea-weather"],
        }
    )

    assert "`korea-weather`" in prompt
    assert "`zipcode-search`" not in prompt


def test_skill_catalog_filters_optional_tool_conditions_like_reference():
    registry = SkillRegistry()
    registry.register_many(
        [
            {"name": "general-note", "description": "도구 전제가 없는 일반 지침"},
            {
                "name": "browser-only",
                "description": "브라우저가 있을 때만 보여야 하는 스킬",
                "metadata": {"runtime": {"requires_tools": ["browser_navigate"]}},
            },
            {
                "name": "web-search-fallback",
                "description": "removed_search가 없을 때만 보여야 하는 대체 검색 스킬",
                "metadata": {"runtime": {"requires_toolsets": ["terminal"], "fallback_for_tools": ["removed_search"]}},
            },
        ]
    )
    prompt_builder = PromptBuilder(SkillPromptBuilder(registry))

    prompt_without_removed_search = prompt_builder.build_agent_loop_prompt(
        input_payload={"prompt": "검색해줘"},
        available_tools=[
            {"name": "terminal.run", "summary": "터미널 실행", "toolset": "terminal"},
            {"name": "http_get", "summary": "HTTP 조회", "toolset": "web"},
        ],
        tool_results=[],
        task_todo_state=None,
        resume_payload=None,
        turn_index=1,
        max_iterations=4,
    )
    prompt_with_removed_search = prompt_builder.build_agent_loop_prompt(
        input_payload={"prompt": "검색해줘"},
        available_tools=[
            {"name": "terminal.run", "summary": "터미널 실행", "toolset": "terminal"},
            {"name": "removed_search", "summary": "제거 예정 검색", "toolset": "web"},
        ],
        tool_results=[],
        task_todo_state=None,
        resume_payload=None,
        turn_index=1,
        max_iterations=4,
    )

    assert "`general-note`" in prompt_without_removed_search
    assert "`web-search-fallback`" in prompt_without_removed_search
    assert "`browser-only`" not in prompt_without_removed_search
    assert "`general-note`" in prompt_with_removed_search
    assert "`web-search-fallback`" not in prompt_with_removed_search
    assert "`browser-only`" not in prompt_with_removed_search


def test_assemble_agent_loop_messages_wraps_history_as_context_only():
    messages = assemble_agent_loop_messages(
        system_prompt_snapshot="고정 system prompt",
        conversation_history=[
            {"role": "user", "content": "이전 요청"},
            {"role": "assistant", "content": "이전 답변"},
        ],
        current_user_prompt="지금 질문",
        runtime_prompt_suffix="도구 사용 지침",
    )

    assert [message.role for message in messages] == ["system", "user"]
    assert messages[0].content == "고정 system prompt"
    assert "참고 맥락" in str(messages[1].content)
    assert "과거 사용자 요청을 다시 실행하지 마세요" in str(messages[1].content)
    assert "[1] user: 이전 요청" in str(messages[1].content)
    assert "[2] assistant: 이전 답변" in str(messages[1].content)
    assert "<current_turn>" in str(messages[1].content)
    assert "지금 질문" in str(messages[1].content)
    assert "도구 사용 지침" in str(messages[1].content)
    assert str(messages[1].content).rfind("<conversation_history>") < str(messages[1].content).rfind("<current_turn>")


def test_single_prompt_fallback_is_the_only_history_text_renderer():
    fallback = render_single_prompt_fallback(
        assemble_agent_loop_messages(
            system_prompt_snapshot="고정 system prompt",
            conversation_history=[{"role": "user", "content": "이전 요청"}],
            current_user_prompt="지금 질문",
            runtime_prompt_suffix="",
        )
    )

    assert "고정 system prompt" in fallback
    assert "이전 요청" in fallback
    assert "지금 질문" in fallback


def test_builtin_browser_web_skills_are_loaded_from_app_skills():
    loaded = {skill["name"]: skill for skill in SkillLoader().load_builtin()}

    for name in {
        "web-scraping",
        "academic-paper-search",
        "domain-intelligence",
    }:
        assert name in loaded
        assert "Hermes" not in loaded[name]["body"]
        assert "metadata:\n  runtime:" in loaded[name]["body"]


def test_first_batch_k_skills_are_loaded_from_app_skills():
    loaded = {skill["name"]: skill for skill in SkillLoader().load_builtin()}

    expected = {
        "korea-weather",
        "fine-dust-location",
        "han-river-water-level",
        "seoul-subway-arrival",
        "real-estate-search",
        "zipcode-search",
        "geeknews-search",
        "korean-character-count",
    }

    assert expected <= set(loaded)
    assert "https://k-skill-proxy.nomadamas.org" in loaded["korea-weather"]["body"]
    assert "`http_get` runtime tool" in loaded["korea-weather"]["body"]
    assert "https://k-skill-proxy.nomadamas.org" in loaded["seoul-subway-arrival"]["body"]
    assert (Path(loaded["zipcode-search"]["path"]).parent / "scripts" / "zipcode_search.py").is_file()
    assert "scripts/geeknews_search.py" in loaded["geeknews-search"]["body"]
    assert "scripts/korean_character_count.js" in loaded["korean-character-count"]["body"]


def test_second_batch_k_skills_are_loaded_from_app_skills():
    loaded = {skill["name"]: skill for skill in SkillLoader().load_builtin()}

    expected = {
        "joseon-sillok-search",
        "library-book-search",
        "k-schoollunch-menu",
        "cheap-gas-nearby",
        "lotto-results",
    }

    assert expected <= set(loaded)
    assert "scripts/sillok_search.py" in loaded["joseon-sillok-search"]["body"]
    assert "/v1/data4library/book-search" in loaded["library-book-search"]["body"]
    assert "/v1/neis/school-search" in loaded["k-schoollunch-menu"]["body"]
    assert "/v1/opinet/around" in loaded["cheap-gas-nearby"]["body"]
    assert "k-lotto" in loaded["lotto-results"]["body"]


def test_third_batch_k_skills_are_loaded_from_app_skills():
    loaded = {skill["name"]: skill for skill in SkillLoader().load_builtin()}

    expected = {
        "household-waste-info",
        "public-restroom-nearby",
        "subway-lost-property",
    }

    assert expected <= set(loaded)
    assert "/v1/household-waste/info" in loaded["household-waste-info"]["body"]
    assert "cond[SGG_NM::LIKE]" in loaded["household-waste-info"]["body"]
    assert "공중화장실" in loaded["public-restroom-nearby"]["body"]
    assert "scripts/subway_lost_property.py" in loaded["subway-lost-property"]["body"]
    assert "LOST112" in loaded["subway-lost-property"]["body"]


def test_third_batch_k_skills_include_safety_guidance():
    loaded = {skill["name"]: skill for skill in SkillLoader().load_builtin()}

    household = loaded["household-waste-info"]["body"]
    restroom = loaded["public-restroom-nearby"]["body"]
    lost_property = loaded["subway-lost-property"]["body"]

    assert "serviceKey" in household
    assert "proxy" in household
    assert "pageNo=1" in household
    assert "numOfRows=100" in household
    assert "사용자 측 로컬 환경에 `DATA_GO_KR_API_KEY`를 둘 필요가 없다" in household

    assert "반드시 먼저 현재 위치를 질문" in restroom
    assert "KAKAO_REST_API_KEY" in restroom
    assert "CSV 단일 소스" in restroom
    assert "위치 기준점이 흔들릴 수 있다" in restroom

    assert "안내형/하이브리드" in lost_property
    assert "완전 자동 조회형으로 확장하려면" in lost_property
    assert "runnable `curl` 예시" in lost_property


def test_skill_index_is_loaded_from_app_skills():
    loaded = {skill["name"]: skill for skill in SkillLoader().load_builtin()}

    assert "skill-index" in loaded
    assert "web-search-fallback" in loaded["skill-index"]["body"]
    assert "korea-weather" in loaded["skill-index"]["body"]
    assert "korean-character-count" in loaded["skill-index"]["body"]
    assert "joseon-sillok-search" in loaded["skill-index"]["body"]
    assert "library-book-search" in loaded["skill-index"]["body"]
    assert "household-waste-info" in loaded["skill-index"]["body"]
    assert "public-restroom-nearby" in loaded["skill-index"]["body"]
    assert "subway-lost-property" in loaded["skill-index"]["body"]


def test_worker_payload_cannot_enable_delegation_toolsets():
    requested = ToolCallingLoopHandler._requested_toolsets(
        {
            "role": "worker",
            "worker": {"leaf": True},
            "enabled_toolsets": ["all", "web", "delegation", "delegate_task", "file"],
        }
    )

    assert requested == ("web", "file")
