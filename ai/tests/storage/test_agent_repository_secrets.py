from __future__ import annotations

import json

from app.domain.agents.secret_documents import MASKED_SECRET_VALUE
from app.storage.postgres.agent_repository import PostgresAgentRepository


class _Cursor:
    def __init__(self, *, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return list(self._rows)


class _Connection:
    def __init__(self) -> None:
        self.saved_params = None
        self.secret_params = []
        self.profile_update_params = None
        self.secret_rows = [
            {
                "section_key": "srt-booking",
                "secret_key": "KSKILL_SRT_ID",
                "encrypted_value": "encrypted:my-id",
            }
        ]

    def execute(self, sql: str, params: tuple | None = None):
        normalized = " ".join(sql.split())
        if "FROM ai_agent_profiles p LEFT JOIN ai_agent_instruction_bundles b" in normalized:
            return _Cursor(
                row={
                    "profile_id": "profile-1",
                    "owner_key": "owner-1",
                    "owner_user_id": 7,
                    "session_id": "session-1",
                    "bundle_id": "bundle-1",
                    "entry_document_key": "AGENTS.md",
                    "config_snapshot": "{}",
                    "delegation_policy": "{}",
                }
            )
        if "SELECT * FROM ai_agent_instruction_documents" in normalized:
            return _Cursor(rows=[])
        if "FROM ai_agent_secret_values" in normalized:
            return _Cursor(rows=self.secret_rows)
        if "UPDATE ai_agent_profiles SET profile_version" in normalized:
            self.profile_update_params = params
            return _Cursor()
        if normalized.startswith("UPDATE ai_agent_instruction_bundles"):
            return _Cursor()
        if "INSERT INTO ai_agent_instruction_documents" in normalized:
            self.saved_params = params
            return _Cursor(
                row={
                    "document_id": "document-1",
                    "bundle_id": "bundle-1",
                    "document_key": params[2],
                    "display_name": params[3],
                    "content_format": "markdown",
                    "content": params[4],
                    "version": 1,
                }
            )
        if "INSERT INTO ai_agent_secret_values" in normalized:
            self.secret_params.append(params)
            return _Cursor()
        return _Cursor()

    def commit(self) -> None:
        pass


def test_save_instruction_document_masks_secrets_document_before_persisting():
    connection = _Connection()
    repository = PostgresAgentRepository(lambda: connection, secret_cipher=_FakeSecretCipher())

    document = repository.save_instruction_document(
        profile_id="profile-1",
        owner_key="owner-1",
        document_key="SECRETS.md",
        display_name="비밀값 입력",
        content="## srt-booking\nKSKILL_SRT_ID=my-id\nKSKILL_SRT_PASSWORD=my-password\n",
    )

    saved_content = connection.saved_params[4]
    assert "my-id" not in saved_content
    assert "my-password" not in saved_content
    assert f"KSKILL_SRT_ID={MASKED_SECRET_VALUE}" in saved_content
    assert document["content"] == saved_content
    assert [params[6] for params in connection.secret_params] == [
        "KSKILL_SRT_ID",
        "KSKILL_SRT_PASSWORD",
    ]
    assert [params[7] for params in connection.secret_params] == [
        "encrypted:my-id",
        "encrypted:my-password",
    ]


def test_save_instruction_document_rejects_raw_secrets_when_store_is_not_configured():
    connection = _Connection()
    repository = PostgresAgentRepository(lambda: connection)

    try:
        repository.save_instruction_document(
            profile_id="profile-1",
            owner_key="owner-1",
            document_key="SECRETS.md",
            display_name="비밀값 입력",
            content="## srt-booking\nKSKILL_SRT_PASSWORD=my-password\n",
        )
    except RuntimeError as error:
        assert "agent secret store is not configured" in str(error)
    else:
        raise AssertionError("raw secrets must not be accepted without a configured secret store")

    assert connection.saved_params is None
    assert connection.secret_params == []


def test_update_session_agent_masks_secrets_document_before_profile_and_document_persist():
    connection = _Connection()
    repository = PostgresAgentRepository(lambda: connection, secret_cipher=_FakeSecretCipher())

    repository.update_session_agent(
        session_id="session-1",
        owner_key="owner-1",
        profile_id="profile-1",
        config_snapshot={
            "name": "K-에이전트",
            "documents": [
                {
                    "documentKey": "SECRETS.md",
                    "displayName": "비밀값 입력",
                    "content": "## srt-booking\nKSKILL_SRT_ID=my-id\nKSKILL_SRT_PASSWORD=my-password\n",
                }
            ],
        },
    )

    saved_profile_config = json.loads(connection.profile_update_params[3])
    saved_profile_content = saved_profile_config["documents"][0]["content"]
    saved_document_content = connection.saved_params[4]
    assert "my-id" not in saved_profile_content
    assert "my-password" not in saved_profile_content
    assert saved_document_content == saved_profile_content
    assert f"KSKILL_SRT_ID={MASKED_SECRET_VALUE}" in saved_document_content
    assert [params[6] for params in connection.secret_params] == [
        "KSKILL_SRT_ID",
        "KSKILL_SRT_PASSWORD",
    ]


def test_get_agent_secret_values_decrypts_stored_values_by_section():
    connection = _Connection()
    repository = PostgresAgentRepository(lambda: connection, secret_cipher=_FakeSecretCipher())

    values = repository.get_agent_secret_values(
        profile_id="profile-1",
        owner_key="owner-1",
        section_key="srt-booking",
    )

    assert values == {"srt-booking": {"KSKILL_SRT_ID": "my-id"}}


class _FakeSecretCipher:
    def encrypt(self, value: str) -> str:
        return f"encrypted:{value}"

    def decrypt(self, value: str) -> str:
        return value.removeprefix("encrypted:")
