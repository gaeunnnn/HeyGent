class FakePrototypeRepository:
    def __init__(self) -> None:
        self.active = None

    def get_active_artifact(self, *, session_id: str, owner_key: str):
        if self.active and self.active["session_id"] == session_id and self.active["owner_key"] == owner_key:
            return self.active
        return None

    def get_version_code(self, *, session_id: str, owner_key: str, artifact_id: str, version_id: str):
        if (
            self.active
            and self.active["session_id"] == session_id
            and self.active["owner_key"] == owner_key
            and self.active["artifact_id"] == artifact_id
            and self.active["version_id"] == version_id
        ):
            return self.active
        return None


def test_get_active_prototype_artifact_returns_react_files(client):
    create_response = client.post(
        "/ai/api/v1/sessions",
        json={"title": "디자인 세션"},
        headers={"Authorization": "Bearer local-user"},
    )
    session_id = create_response.json()["sessionId"]
    repository = FakePrototypeRepository()
    repository.active = {
        "artifact_id": "artifact_1",
        "version_id": "version_1",
        "session_id": session_id,
        "owner_key": "local-user",
        "title": "AI 고객지원 SaaS 대시보드",
        "framework": "react",
        "styling": "css",
        "design_preset_id": "stripe",
        "entry_file": "/src/App.tsx",
        "files": {
            "/src/App.tsx": {"code": "export default function App() { return <main /> }"},
            "/src/styles.css": {"code": ":root { --primary: #533afd; }"},
        },
        "version_number": 1,
        "summary": "디자인 규칙을 반영한 프로토타입",
        "created_at": "2026-05-15T00:00:00Z",
        "updated_at": "2026-05-15T00:00:00Z",
    }
    client.app.state.prototype_repository = repository

    response = client.get(
        f"/ai/api/v1/sessions/{session_id}/artifacts/active",
        headers={"Authorization": "Bearer local-user"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["activeArtifactId"] == "artifact_1"
    assert body["activeArtifactVersionId"] == "version_1"
    assert body["artifact"]["framework"] == "react"
    assert body["artifact"]["designPresetId"] == "stripe"
    assert body["artifact"]["files"]["/src/styles.css"]["code"] == ":root { --primary: #533afd; }"


def test_get_active_prototype_artifact_returns_null_when_missing(client):
    create_response = client.post(
        "/ai/api/v1/sessions",
        json={"title": "빈 디자인 세션"},
        headers={"Authorization": "Bearer local-user"},
    )
    session_id = create_response.json()["sessionId"]
    client.app.state.prototype_repository = FakePrototypeRepository()

    response = client.get(
        f"/ai/api/v1/sessions/{session_id}/artifacts/active",
        headers={"Authorization": "Bearer local-user"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "activeArtifactId": None,
        "activeArtifactVersionId": None,
        "artifact": None,
    }


def test_get_prototype_code_requires_session_owner(client):
    owner_response = client.post(
        "/ai/api/v1/sessions",
        json={"title": "소유자 세션"},
        headers={"Authorization": "Bearer owner-a"},
    )
    session_id = owner_response.json()["sessionId"]
    client.app.state.prototype_repository = FakePrototypeRepository()

    response = client.get(
        f"/ai/api/v1/sessions/{session_id}/artifacts/active",
        headers={"Authorization": "Bearer owner-b"},
    )

    assert response.status_code == 403
