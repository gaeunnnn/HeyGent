from __future__ import annotations

import json
import re

from app.domain.providers.model.base import AgentMessage
from app.domain.orchestration.prompts.compression import compress_prompt_sections
from app.domain.orchestration.prompts.gateway_context_prompt import build_gateway_context_prompt
from app.domain.orchestration.prompts.project_context_prompt import build_project_context_prompt
from app.domain.orchestration.prompts.skill_prompt import SkillPromptBuilder
from app.domain.orchestration.prompts.step_context_prompt import build_step_context_prompt
from app.domain.orchestration.prompts.step_run_boundary_prompt import build_step_run_boundary_prompt
from app.domain.orchestration.prompts.step_run_prompt import build_step_run_prompt
from app.domain.orchestration.prompts.task_context_prompt import build_task_context_prompt

_MEMORY_APPLICATION_BLOCK_PATTERN = re.compile(
    r"(?s)<memory-application-instructions>.*?</memory-application-instructions>"
)


def assemble_agent_loop_messages(
    *,
    system_prompt_snapshot: str,
    conversation_history: list[dict[str, str]],
    current_user_prompt: str,
    runtime_prompt_suffix: str,
) -> list[AgentMessage]:
    """provider에 넘길 native message 배열을 만든다.

    공개 대화 history는 참고 맥락으로만 전달한다. 과거 user 메시지를 native user message로
    다시 주입하면 모델이 이미 끝난 요청을 이번 turn의 실행 지시로 오해할 수 있다.
    현재 turn의 실행 지시는 항상 마지막 user message에 명시적으로 격리한다.
    """

    messages: list[AgentMessage] = []
    snapshot = str(system_prompt_snapshot or "").strip()
    if snapshot:
        messages.append(AgentMessage(role="system", content=snapshot))

    current_parts = [str(current_user_prompt or "").strip(), str(runtime_prompt_suffix or "").strip()]
    current_content = "\n\n".join(part for part in current_parts if part)
    user_parts = [
        _render_conversation_history_context(conversation_history),
        _wrap_current_turn(current_content),
    ]
    messages.append(AgentMessage(role="user", content="\n\n".join(part for part in user_parts if part)))
    return messages


def _render_conversation_history_context(conversation_history: list[dict[str, str]]) -> str:
    """과거 공개 대화를 실행 지시가 아닌 참고 맥락으로 낮춰 렌더링한다."""

    lines = [
        "이전 대화 기록입니다.",
        "이 내용은 참고 맥락일 뿐이며, 과거 사용자 요청을 다시 실행하지 마세요.",
        "이번 turn에서 실행할 대상은 다음 메시지의 <current_turn> 안에 있는 최신 요청뿐입니다.",
        "",
        "<conversation_history>",
    ]
    rendered_count = 0
    for index, item in enumerate(conversation_history or [], start=1):
        role = str(item.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        rendered_count += 1
        lines.append(f"[{index}] {role}: {content}")

    if rendered_count == 0:
        return ""
    lines.append("</conversation_history>")
    return "\n".join(lines)


def _wrap_current_turn(current_content: str) -> str:
    content = str(current_content or "").strip() or "현재 요청을 처리해 주세요."
    return "\n".join(
        [
            "이번 turn에서 실행할 현재 입력입니다.",
            "과거 대화와 충돌하면 이 current_turn 내용을 우선하세요.",
            "",
            "<current_turn>",
            content,
            "</current_turn>",
        ]
    )


def render_single_prompt_fallback(messages: list[AgentMessage]) -> str:
    """native message를 지원하지 않는 provider에서만 사용하는 텍스트 fallback이다."""

    sections: list[str] = []
    for message in messages:
        content = str(message.content or "").strip()
        if not content:
            continue
        sections.append(f"[{message.role}]\n{content}")
    return "\n\n".join(sections)


class PromptBuilder:
    """Assemble runtime prompts from stable context sections."""

    def __init__(self, skill_prompt_builder: SkillPromptBuilder) -> None:
        self.skill_prompt_builder = skill_prompt_builder

    def build_model_prompt(self, *, input_payload: dict, available_tools: list[dict[str, str]] | None = None) -> str:
        base_prompt = str(input_payload.get("prompt", "")).strip() or "안녕하세요. 현재 연결 상태를 짧게 요약해 주세요."
        parts = compress_prompt_sections(
            [
                self.skill_prompt_builder.build(input_payload=input_payload, available_tools=available_tools),
                build_project_context_prompt(input_payload=input_payload),
                build_gateway_context_prompt(input_payload=input_payload),
                build_work_context_prompt(input_payload=input_payload),
                build_attachment_context_prompt(input_payload=input_payload),
                self.skill_prompt_builder.build_catalog(input_payload=input_payload, available_tools=available_tools),
                base_prompt,
                str(input_payload.get("persistent_memory_context", "")).strip(),
            ]
        )
        return "\n\n".join(parts)

    def build_runtime_prompt(self, *, task=None, step=None, input_payload: dict | None = None) -> str:
        payload = input_payload or {}
        parts = compress_prompt_sections(
            [
                self.skill_prompt_builder.build(input_payload=payload),
                build_task_context_prompt(task=task, input_payload=payload),
                build_step_context_prompt(step=step),
                build_step_run_prompt(step_title=step.title if step is not None else "현재 단계"),
            ]
        )
        return "\n\n".join(parts)

    def build_agent_loop_prompt(
        self,
        *,
        input_payload: dict,
        available_tools: list[dict[str, str]],
        tool_results: list[dict],
        task_todo_state: dict | None,
        resume_payload: dict | None,
        turn_index: int,
        max_iterations: int,
    ) -> str:
        base_prompt = self.build_model_prompt(input_payload=input_payload, available_tools=available_tools)
        sections = [base_prompt]
        sections.append(
            "\n".join(
                [
                    "세션 에이전트 라우팅 기준:",
                    "세션 에이전트 후보를 볼 때는 후보의 이름, 호칭, 할 수 있는 일, 연결된 스킬 이름과 공용 스킬 설명이 사용자 요청과 맞아야 합니다.",
                    "사용자 요청 전체 또는 요청 안의 의미 있는 하위 작업이 다른 세션 에이전트의 skill 이름이나 설명과 맞고, 그 에이전트가 해당 skill을 바탕으로 현재 실행 에이전트보다 더 적합하게 처리할 가능성이 있으면 session_agent_task 로 맡기세요.",
                    "현재 실행 에이전트가 직접 답할 수 있더라도 위 조건을 만족하면 호출을 우선하세요.",
                    "위 조건을 만족하면 현재 응답의 progressUpdate에 세션 에이전트 실행 상태를 남긴 뒤 session_agent_task 를 호출하고, 후보 실행 결과를 받은 다음 최종 답변을 작성하세요.",
                    "session_agent_task 는 작업 보드에 보이는 하위 작업과 실제 세션 에이전트 실행을 묶는 도구입니다.",
                    "후보가 요청의 핵심 부분을 수행할 수 있고, 독립 산출물이나 책임 분리가 자연스러울 때 세션 에이전트 작업으로 분리하세요.",
                    "단순 응답, 맥락 정리, 최종 종합, 또는 분리할 실익이 낮은 작업은 팀장이 직접 처리해도 됩니다.",
                    "수행할 수 있는 세션 에이전트가 없으면 임의로 배정하지 말고 팀장이 직접 진행하거나 필요한 정보와 사용자 결정 지점을 남기세요.",
                    "세션 에이전트 후보의 skill 설명은 위임 판단용입니다. 현재 실행 에이전트가 직접 보유한 skill이 아니면 `skills.read`로 읽지 마세요.",
                    "특정 skill 절차가 필요한 하위 작업이면 session_agent_task 입력의 requiredSkillNames에 필요한 skill 이름을 담으세요.",
                    "session_agent_task 입력에는 담당자가 다시 묻지 않아도 실행할 수 있도록 제목, 지시, 기대 산출물, 완료 기준, 제약을 구체적으로 담으세요.",
                    "도메인 스킬 결과 보존 규칙:",
                    "- 안전, 건강, 법률, 금융처럼 근거와 제한 문구가 중요한 스킬을 가진 세션 에이전트에게 위임한 경우, 팀장은 하위 에이전트 답변의 구조와 제한 문구를 보존합니다.",
                    "- 보존 대상 스킬: `health-condition-check`",
                    "- 보존 대상 스킬의 하위 에이전트 본문은 요약하거나 재작성하지 말고, 최종 응답의 본문으로 그대로 복사해 전달합니다.",
                    "- 필요한 경우 본문 앞에 `아래는 {세션 에이전트 이름}의 {작업 제목} 결과입니다.` 형식의 짧은 안내 문장만 덧붙일 수 있습니다.",
                ]
            )
        )
        if available_tools:
            sections.append(self._build_tool_catalog_prompt(available_tools))
        if tool_results:
            sections.append(
                "현재까지 실행된 로컬 도구 결과:\n" + json.dumps(tool_results, ensure_ascii=False, indent=2)
            )
        sections.append(build_step_run_boundary_prompt())
        if task_todo_state and list(task_todo_state.get("items") or []):
            sections.append(self._build_task_todo_prompt(task_todo_state))
        if resume_payload:
            sections.append(
                "승인 재개 입력:\n" + json.dumps(resume_payload, ensure_ascii=False, indent=2)
            )
        if input_payload.get("approval_required"):
            approval_reason = str(input_payload.get("approval_reason") or "사용자 승인이 필요합니다").strip()
            sections.append(
                "\n".join(
                    [
                        "이번 실행은 approval_required=true 입니다.",
                        "승인이 필요한 작업이라도 필요한 도구 호출 자체는 먼저 native tool call로 반환하세요.",
                        "runtime은 실제 도구 실행 직전에 WAITING으로 내려가고, 승인 후 같은 tool_call_id로 결과를 이어붙입니다.",
                        f"승인 사유: {approval_reason}",
                    ]
                )
            )
        if not input_payload.get("prompt") and tool_results:
            sections.append("위 결과를 바탕으로 현재 상태를 짧고 명확하게 요약하세요.")
        sections.append(
            "\n".join(
                [
                    f"현재는 tool-calling loop {turn_index}/{max_iterations} 턴입니다.",
                    "추가 정보나 로컬 실행이 실제로 필요할 때만 제공된 도구 호출 기능을 사용하세요.",
                    "도구 호출은 본문 JSON으로 쓰지 말고 모델의 tool call 응답으로 반환하세요.",
                    "이미 충분한 정보가 있으면 더 이상 도구를 부르지 말고 일반 답변으로 종료하세요.",
                    "직전에 같은 도구를 같은 인자로 실행했다면 반복하지 말고 답변 종료를 우선하세요.",
                    "workId가 연결된 실행은 최종 assistant 응답의 workDisposition 필드로 작업 상태를 명시하세요.",
                    "완료 조건을 만족하면 done, 산출물은 있지만 사용자나 담당자의 확인이 필요하면 in_review, 실제 선행 작업/필수 입력/권한/도구가 없어 더 진행할 수 없을 때만 blocked, 등록만 요청한 작업이면 todo를 남기세요.",
                    "승인이 없으면 진행하면 안 되는 경우에만 approval 을 요청하세요.",
                    "사용자에게 보일 현재 진행 상태는 assistant 응답의 progressUpdate로 갱신하고, 세부 체크리스트는 todo 도구로 갱신하세요.",
                    "사용자가 저장 위치로 폴더 경로를 주고 파일명을 생략하면, 그 폴더 경로 자체를 파일명으로 바꾸지 말고 폴더 안에 의미 있는 파일명을 만들어 저장하세요.",
                    "사용자가 자신의 이름, 호칭, 프로필, 선호, 비선호, 반복 행동, 작업 습관 같은 지속 정보를 알려주면 자연스럽게 확인하고, 필요하면 앞으로 어떻게 부르면 될지나 어떻게 반영할지 짧게 물어보세요.",
                    "최종 답변은 내부 상태 문구처럼 쓰지 말고, 사용자가 바로 이해할 수 있는 결과와 다음에 이어갈 내용을 자연어로 작성하세요.",
                ]
            )
        )
        memory_application_instructions = _memory_application_instructions(input_payload)
        if memory_application_instructions:
            sections.append(memory_application_instructions)
        return "\n\n".join(compress_prompt_sections(sections))

    def _merge_skill_context(self, *, base_prompt: str, input_payload: dict) -> str:
        skill_context = self.skill_prompt_builder.build(input_payload=input_payload)
        if not skill_context:
            return base_prompt
        return f"{skill_context}\n\n{base_prompt}"

    @staticmethod
    def _build_tool_catalog_prompt(available_tools: list[dict[str, str]]) -> str:
        lines = ["현재 사용할 수 있는 로컬 도구:"]
        for tool in available_tools:
            name = str(tool.get("name") or "").strip()
            summary = str(tool.get("summary") or "").strip()
            toolset = str(tool.get("toolset") or "").strip()
            if name and summary:
                lines.append(f"- {name} [{toolset}]: {summary}")
            elif name:
                lines.append(f"- {name} [{toolset}]")
        return "\n".join(lines)

    @staticmethod
    def _build_task_todo_prompt(task_todo_state: dict) -> str:
        lines = ["현재 task todo 상태:"]
        current_key = str(task_todo_state.get("currentKey") or task_todo_state.get("currentId") or "").strip()
        for raw_item in list(task_todo_state.get("items") or []):
            if not isinstance(raw_item, dict):
                continue
            key = str(raw_item.get("id") or raw_item.get("key") or "").strip()
            title = str(raw_item.get("content") or raw_item.get("title") or key).strip()
            status = str(raw_item.get("status") or "pending").strip()
            marker = ">" if key and key == current_key else "-"
            if key and title:
                lines.append(f"{marker} {key}: {title} ({status})")
        return "\n".join(lines)


def build_work_context_prompt(*, input_payload: dict) -> str:
    work_context = input_payload.get("workContext")
    target_agent_profile = input_payload.get("targetAgentProfile")
    target_agent_instructions = input_payload.get("targetAgentInstructions")
    session_agent_profiles = input_payload.get("sessionAgentProfiles")
    work_id = str(input_payload.get("workId") or "").strip()
    work_identifier = str(input_payload.get("workIdentifier") or "").strip()
    assignee_agent_id = str(input_payload.get("workAssigneeAgentId") or "").strip()
    has_session_agent_profiles = isinstance(session_agent_profiles, list) and bool(session_agent_profiles)
    if not work_id and not work_identifier and not isinstance(work_context, dict) and not has_session_agent_profiles:
        return ""

    lines = ["연결된 작업 컨텍스트:" if work_id or work_identifier or isinstance(work_context, dict) else "세션 에이전트 컨텍스트:"]
    if work_identifier:
        lines.append(f"- 작업 번호: {work_identifier}")
    if assignee_agent_id:
        lines.append(f"- 담당 에이전트: {assignee_agent_id}")
        if assignee_agent_id != "CEO":
            lines.append("- 담당자가 팀장이 아니면 현재 실행은 해당 세션 에이전트가 맡은 작업 실행입니다.")
            lines.append("- 담당 작업 실행 자체를 worker delegate로 다시 위임하지 마세요.")
    if isinstance(target_agent_profile, dict):
        profile_lines = _build_target_agent_profile_lines(target_agent_profile)
        if profile_lines:
            lines.append("- 실행 에이전트 설정:")
            lines.extend(f"  - {line}" for line in profile_lines)
    if isinstance(target_agent_instructions, dict):
        instruction_lines = _build_target_agent_instruction_lines(target_agent_instructions)
        if instruction_lines:
            lines.append("- 실행 에이전트 지침:")
            lines.extend(instruction_lines)
    if has_session_agent_profiles:
        profile_lines = _build_session_agent_profile_lines(session_agent_profiles)
        if profile_lines:
            lines.append("- 세션 에이전트 후보:")
            lines.extend(f"  - {line}" for line in profile_lines)
        skill_description_lines = _build_session_agent_skill_description_lines(session_agent_profiles)
        if skill_description_lines:
            lines.append("- 세션 에이전트 공용 스킬 설명:")
            lines.extend(f"  - {line}" for line in skill_description_lines)
    if isinstance(work_context, dict):
        title = str(work_context.get("title") or "").strip()
        if title:
            lines.append(f"- 제목: {title}")
        labels = work_context.get("labels")
        if isinstance(labels, list) and labels:
            lines.append("- 라벨: " + ", ".join(str(label) for label in labels if str(label).strip()))
        prompt_preview = str(work_context.get("promptPreview") or "").strip()
        if prompt_preview:
            lines.append("- 요약:")
            lines.append(prompt_preview)
    return "\n".join(lines)


def build_attachment_context_prompt(*, input_payload: dict) -> str:
    raw_attachments = input_payload.get("sessionAttachments") or input_payload.get("attachments")
    if not isinstance(raw_attachments, list) or not raw_attachments:
        return ""

    lines = ["첨부 파일 컨텍스트:"]
    for index, raw_attachment in enumerate(raw_attachments, start=1):
        if not isinstance(raw_attachment, dict):
            continue
        name = str(raw_attachment.get("name") or f"attachment-{index}").strip()
        content_type = str(raw_attachment.get("type") or "application/octet-stream").strip()
        size = raw_attachment.get("size")
        error = str(raw_attachment.get("error") or "").strip()
        text = str(raw_attachment.get("text") or "").strip()
        text_truncated = bool(raw_attachment.get("textTruncated"))
        is_image = bool(raw_attachment.get("isImage"))

        detail = f"- {index}. {name} ({content_type}"
        if isinstance(size, int):
            detail += f", {size} bytes"
        detail += ")"
        if error:
            detail += f" - {error}"
        elif is_image:
            detail += " - 이미지 파일"
        lines.append(detail)

        if text:
            lines.append("  내용:")
            lines.append(_indent_attachment_text(text[:8000]))
            if text_truncated or len(text) > 8000:
                lines.append("  [첨부 텍스트가 길어 일부만 포함되었습니다.]")

    return "\n".join(lines)


def _indent_attachment_text(value: str) -> str:
    return "\n".join(f"  {line}" for line in value.splitlines())


def _build_session_agent_profile_lines(profiles: list) -> list[str]:
    lines: list[str] = []
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        config = profile.get("configSnapshot") or profile.get("config_snapshot") or {}
        if not isinstance(config, dict):
            config = {}
        profile_id = str(profile.get("profileId") or profile.get("profile_id") or "").strip()
        name = str(config.get("name") or profile.get("profileKey") or profile.get("profile_key") or "").strip()
        title = str(config.get("title") or "").strip()
        description = str(config.get("description") or "").strip()
        role = str(config.get("role") or profile.get("agentType") or profile.get("agent_type") or "").strip()
        skills = _text_list(config.get("skills") or profile.get("skills"))
        parts = []
        if name:
            parts.append(f"이름={name}")
        if title:
            parts.append(f"호칭={title}")
        if description:
            parts.append(f"할 수 있는 일={description}")
        if skills:
            parts.append("스킬=" + ", ".join(skills))
        if role:
            parts.append(f"참고 분류={role}")
        if profile_id and parts:
            lines.append(f"{profile_id}: " + " / ".join(parts))
        elif profile_id:
            lines.append(profile_id)
    return lines


def _build_session_agent_skill_description_lines(profiles: list) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        config = profile.get("configSnapshot") or profile.get("config_snapshot") or {}
        if not isinstance(config, dict):
            config = {}
        for line in _skill_description_lines(profile.get("skillDescriptions") or config.get("skillDescriptions")):
            name = line.split(":", 1)[0].strip()
            key = name or line
            if key in seen:
                continue
            seen.add(key)
            lines.append(line)
    return lines


def _build_target_agent_profile_lines(profile: dict) -> list[str]:
    config = profile.get("configSnapshot") or profile.get("config_snapshot") or {}
    if not isinstance(config, dict):
        config = {}
    fields = [
        ("name", "이름"),
        ("role", "역할"),
        ("title", "타이틀"),
        ("description", "설명"),
        ("adapterType", "연결 방식"),
        ("model", "모델"),
    ]
    lines: list[str] = []
    for key, label in fields:
        value = str(config.get(key) or profile.get(key) or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    skills = config.get("skills") or profile.get("skills")
    if isinstance(skills, list):
        skill_names = [str(skill).strip() for skill in skills if str(skill).strip()]
        if skill_names:
            lines.append("스킬: " + ", ".join(skill_names))
    return lines


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _skill_description_lines(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("skillId") or item.get("skill_id") or "").strip()
        description = str(item.get("description") or "").strip()
        if not name:
            continue
        if len(description) > 80:
            description = description[:77].rstrip() + "..."
        detail_parts = [part for part in [description] if part]
        lines.append(f"{name}: " + " / ".join(detail_parts) if detail_parts else name)
    return lines


def _build_target_agent_instruction_lines(bundle: dict) -> list[str]:
    entry_key = str(bundle.get("entryDocumentKey") or bundle.get("entry_document_key") or "AGENTS.md").strip()
    documents = bundle.get("documents")
    if not isinstance(documents, list):
        return []
    lines: list[str] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        key = str(document.get("documentKey") or document.get("document_key") or "").strip()
        content = str(document.get("content") or "").strip()
        if not key or not content:
            continue
        prefix = "기본 지침 문서" if key == entry_key else "참고 지침 문서"
        lines.append(f"  - {prefix}: {key}")
        lines.append(content[:6000])
    return lines


def _memory_application_instructions(input_payload: dict[str, object]) -> str:
    memory_context = str(input_payload.get("persistent_memory_context", "")).strip()
    if not memory_context:
        return ""
    match = _MEMORY_APPLICATION_BLOCK_PATTERN.search(memory_context)
    return match.group(0).strip() if match else ""


class PromptManager(PromptBuilder):
    """Backward-compatible name for the prompt assembly service."""
