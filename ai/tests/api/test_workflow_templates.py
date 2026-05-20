from app.domain.workflow_templates.models import (
    WorkflowTemplate,
    WorkflowTemplateEdge,
    WorkflowTemplateGraph,
    WorkflowTemplateNode,
)
from tests.tools.test_runtime_tools import FakeRuntimeWorkRepository


class FakeWorkflowTemplateRepository:
    def __init__(self, template):
        self.template = template

    def get(self, template_id: str, *, owner_key: str):
        if template_id == self.template.template_id and owner_key == self.template.owner_key:
            return self.template
        return None


def test_instantiate_workflow_template_returns_root_and_child_mapping(client):
    session_id = "workflow-session"
    owner_key = "workflow-owner"
    client.app.state.session_store.create_session(
        session_id=session_id,
        session_key=session_id,
        source="api.session",
        user_id=owner_key,
        metadata={"source": "api.session"},
    )
    template = WorkflowTemplate(
        template_id="wftmpl-test",
        owner_key=owner_key,
        owner_user_id=None,
        session_id=session_id,
        name="삼성 관련 조사 공유 및 UX 화면 확인",
        description="삼성 관련 조사 결과를 Mattermost 우리만 채널로 보내고, UX 디자이너가 만든 화면을 확인한 뒤 사용자에게 보여준다.",
        graph=WorkflowTemplateGraph(
            nodes=[
                WorkflowTemplateNode(
                    slot_key="research",
                    title="삼성 관련 조사",
                    description="삼성 관련 최신 동향을 조사한다.",
                    assignee_agent_id="agent-dev",
                    template_key="coder",
                ),
                WorkflowTemplateNode(
                    slot_key="screen",
                    title="조사 기반 화면 작성",
                    description="삼성 관련 조사 결과를 바탕으로 화면을 만든다.",
                    assignee_agent_id="agent-ux",
                    template_key="ux_designer",
                ),
            ],
            edges=[
                WorkflowTemplateEdge(source_slot_key="research", target_slot_key="screen"),
            ],
        ),
    )
    client.app.state.workflow_template_repository = FakeWorkflowTemplateRepository(template)
    client.app.state.work_repository = FakeRuntimeWorkRepository()

    response = client.post(
        f"/ai/api/v1/sessions/{session_id}/workflow-templates/{template.template_id}/instantiate",
        headers={"Authorization": f"Bearer {owner_key}"},
        json={},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "workIds" not in payload
    assert payload["rootWorkId"]
    assert len(payload["childWorkIds"]) == 2
    assert payload["childrenBySlotKey"] == {
        "research": payload["childWorkIds"][0],
        "screen": payload["childWorkIds"][1],
    }
    assert payload["children"][0]["slotKey"] == "research"
    assert payload["children"][0]["workId"] == payload["childWorkIds"][0]
    assert payload["children"][0]["identifier"].startswith("TASK-")
    assert payload["children"][1]["slotKey"] == "screen"
